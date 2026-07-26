"""다중 시점 세계좌표 융합 (P1-1, MASTER_PRD §10.9).

여러 시점에서 관찰된 같은 대상의 위치 추정을 하나로 합친다. 단일 시점 깊이 추정에
의존하지 않는다는 PRD §10.9 원칙의 기준 구현이다.

## 방법: information-form(공분산 가중) 융합

각 관측이 평균 ``x_i``와 공분산 ``Σ_i``를 갖는 독립 Gaussian 추정일 때, 최적 융합은
정보행렬(공분산의 역)을 더하는 것이다:

    Σ_fused⁻¹ = Σ Σ_i⁻¹
    x_fused   = Σ_fused · Σ (Σ_i⁻¹ x_i)

이 형태를 쓰는 이유는 **불확실성이 자동으로 줄어든다**는 것이다(정보는 더해지므로) —
INV-021이 요구하는 "불확실성을 숨기지 않는다"를 산술 구조 자체로 보장한다. 관측이
많아질수록 공분산이 커지는 일은 이 형태에서 일어날 수 없다.

## 이 구현이 아닌 것 (범위 명시)

- **연관(association)은 다루지 않는다.** "어느 관측들이 같은 대상인가"는 별개의 어려운
  문제이며(Terra 감사가 중심점 greedy 방식을 REPLACE로 판정), 여기서는 이미 같은
  track으로 묶인 관측들을 받는다. 확률적 다특징 연관은 이후 단계다.
- **시간 진화(motion model)를 다루지 않는다.** 같은 순간의 여러 시점을 합치는 정적
  융합이며, 시간에 따라 움직이는 대상의 상태추정(Kalman/factor graph)은 이후 단계다.
  움직이는 대상에 이 함수를 쓰면 시간차만큼의 편향이 그대로 남는다 — 호출자가
  관측 시각 창을 좁게 유지할 책임이 있다.
- **이상치 제거(outlier rejection)를 하지 않는다.** 한 관측이 크게 틀렸으면 그
  가중치만큼 결과를 끌어당긴다. 강건 융합은 이후 단계다.

## 결정성 (P0-6 재현성 규약 계승)

부동소수 덧셈은 결합법칙이 성립하지 않으므로, 관측 순서가 다르면 비트 단위로 다른
결과가 나올 수 있다. 이 모듈은 융합 전 ``observation_id`` 기준으로 정렬해 순서를
정규화한다 — 같은 관측 집합은 입력 순서와 무관하게 **비트 동일한** 결과를 낸다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

# 3×3 공분산의 조건수 상한 — 이보다 나쁘면 역행렬이 수치적으로 신뢰 불가하다.
# 값 근거: float64 유효자리 ~1e16 이므로 1e12 를 넘기면 역행렬에 남는 유효자리가
# 4자리 미만이 된다. 실측 캘리브레이션 데이터로 조정할 여지가 있는 문턱이다.
_MAX_CONDITION_NUMBER = 1e12


class FusionStatus(StrEnum):
    """융합 결과 상태. 실패는 ``None``이 아니라 이 typed 값이다(INV-023 동형 설계)."""

    OK = "ok"
    NO_OBSERVATIONS = "no_observations"
    CRS_MISMATCH = "crs_mismatch"  # 서로 다른 좌표계 관측을 섞을 수 없다(INV-020)
    SINGULAR_COVARIANCE = "singular_covariance"  # 역행렬 수치 불가
    NONFINITE_INPUT = "nonfinite_input"
    NONFINITE_RESULT = "nonfinite_result"  # 입력은 정상이나 산출이 발산


@dataclass(frozen=True, slots=True)
class FusionObservation:
    """융합 입력 1건 — 이미 세계좌표로 해석된 관측.

    ``ksi_event_contracts.observation.Observation``과 같은 의미를 갖지만, geo-core는
    계약 패키지에 의존하지 않으므로(레이어 방향 유지) 필요한 필드만 담은 값 객체를
    따로 둔다. 계약 모델 → 이 값 객체 변환은 호출자(조립 계층)의 책임이다.
    """

    observation_id: str
    site_frame: str
    position: tuple[float, float, float]
    position_covariance: tuple[
        float, float, float, float, float, float, float, float, float
    ]  # row-major 3×3


@dataclass(frozen=True, slots=True)
class FusionResult:
    """융합 결과. ``status``가 OK일 때만 위치·공분산이 채워진다."""

    status: FusionStatus
    position: tuple[float, float, float] | None = None
    position_covariance: tuple[
        float, float, float, float, float, float, float, float, float
    ] | None = None
    site_frame: str | None = None
    observation_ids: tuple[str, ...] = ()
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is FusionStatus.OK


def _covariance_matrix(observation: FusionObservation) -> npt.NDArray[np.float64]:
    return np.array(observation.position_covariance, dtype=np.float64).reshape(3, 3)


def _is_finite_observation(observation: FusionObservation) -> bool:
    return all(math.isfinite(v) for v in observation.position) and all(
        math.isfinite(v) for v in observation.position_covariance
    )


def fuse_observations(observations: list[FusionObservation]) -> FusionResult:
    """공분산 가중으로 여러 관측을 하나의 위치 추정으로 융합한다.

    관측이 1건이면 그 관측을 그대로 돌려준다(융합할 것이 없으므로 — 다만 공분산
    역행렬 가능성은 여전히 검사해 일관된 실패 판정을 유지한다).

    예외를 던지지 않는다 — 모든 실패는 :class:`FusionStatus`로 반환된다(fail-closed).
    """
    if not observations:
        return FusionResult(status=FusionStatus.NO_OBSERVATIONS)

    # 결정성: observation_id 로 정렬해 부동소수 누산 순서를 정규화한다.
    ordered = sorted(observations, key=lambda o: o.observation_id)
    observation_ids = tuple(o.observation_id for o in ordered)

    site_frame = ordered[0].site_frame
    if any(o.site_frame != site_frame for o in ordered):
        frames = sorted({o.site_frame for o in ordered})
        return FusionResult(
            status=FusionStatus.CRS_MISMATCH,
            observation_ids=observation_ids,
            detail=f"서로 다른 site_frame 을 융합할 수 없다: {frames}",
        )

    for observation in ordered:
        if not _is_finite_observation(observation):
            return FusionResult(
                status=FusionStatus.NONFINITE_INPUT,
                observation_ids=observation_ids,
                detail=f"비유한 값 포함: {observation.observation_id}",
            )

    information_sum = np.zeros((3, 3), dtype=np.float64)
    weighted_sum = np.zeros(3, dtype=np.float64)

    for observation in ordered:
        covariance = _covariance_matrix(observation)
        # 조건수로 역행렬 신뢰성을 먼저 판정한다 — np.linalg.inv 는 특이행렬에서도
        # 조용히 거대한 값을 돌려줄 수 있어(경고만) 그대로 쓰면 fail-open이 된다.
        try:
            condition_number = float(np.linalg.cond(covariance))
        except np.linalg.LinAlgError:
            return FusionResult(
                status=FusionStatus.SINGULAR_COVARIANCE,
                observation_ids=observation_ids,
                detail=f"조건수 계산 실패: {observation.observation_id}",
            )
        if not math.isfinite(condition_number) or condition_number > _MAX_CONDITION_NUMBER:
            return FusionResult(
                status=FusionStatus.SINGULAR_COVARIANCE,
                observation_ids=observation_ids,
                detail=(
                    f"공분산 조건수 {condition_number:.3e} 가 상한 "
                    f"{_MAX_CONDITION_NUMBER:.0e} 초과: {observation.observation_id}"
                ),
            )
        try:
            information = np.linalg.inv(covariance)
        except np.linalg.LinAlgError:
            return FusionResult(
                status=FusionStatus.SINGULAR_COVARIANCE,
                observation_ids=observation_ids,
                detail=f"공분산 역행렬 실패: {observation.observation_id}",
            )
        position = np.array(observation.position, dtype=np.float64)
        information_sum += information
        weighted_sum += information @ position

    try:
        fused_covariance = np.linalg.inv(information_sum)
    except np.linalg.LinAlgError:
        return FusionResult(
            status=FusionStatus.SINGULAR_COVARIANCE,
            observation_ids=observation_ids,
            detail="정보행렬 합의 역행렬 실패",
        )
    fused_position = fused_covariance @ weighted_sum

    if not (np.all(np.isfinite(fused_position)) and np.all(np.isfinite(fused_covariance))):
        return FusionResult(
            status=FusionStatus.NONFINITE_RESULT,
            observation_ids=observation_ids,
            detail="융합 산출이 비유한 — 입력 조건수 재확인 필요",
        )

    return FusionResult(
        status=FusionStatus.OK,
        position=(
            float(fused_position[0]),
            float(fused_position[1]),
            float(fused_position[2]),
        ),
        position_covariance=tuple(float(v) for v in fused_covariance.reshape(9)),  # type: ignore[arg-type]
        site_frame=site_frame,
        observation_ids=observation_ids,
    )


def covariance_trace(covariance: tuple[float, ...]) -> float:
    """3×3 row-major 공분산의 trace — 불확실성 크기 비교용 스칼라 요약.

    융합이 불확실성을 줄였는지 확인하는 데 쓴다. trace 는 세 축 분산의 합이라
    Loewner 순서의 완전한 대체는 아니지만, 단조성 회귀 테스트에는 충분하고
    해석이 명확하다.
    """
    return covariance[0] + covariance[4] + covariance[8]
