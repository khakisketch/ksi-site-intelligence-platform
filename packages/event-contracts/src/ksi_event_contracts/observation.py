"""Observation 계약 (Stage C-1) — Detection과 WorldEntity 사이의 단일 관측 기록.

AGENTS.md "Main contracts"가 ``Observation``을 WorldEntity와 나란히 열거하지만
``contracts/schemas/``에는 대응 JSON Schema가 **없다**. 따라서 이 모델은
world-entity/event-bundle과 달리 **Python-first**이며, JSON Schema SSOT 왕복 검증
대상이 아니다(그 사실을 숨기지 않기 위해 여기 명시한다). 스키마가 추가되면 P0-1
패턴대로 왕복 테스트를 붙이고 이 문단을 갱신해야 한다.

이벤트 상태머신에서의 위치(INV-031):

    Detection → **Observation** → Candidate → Evidence Collection → …

Detection(모델 출력)은 Event가 아니며, Observation은 그 Detection이 시간·좌표계·
불확실성을 얻어 세계 모델에 편입될 수 있게 된 첫 단계다. 상태 전이 자체는
:func:`ksi_domain.enums.assert_event_transition` 이 강제한다 — 이 모델은 그 전이의
입력이 되는 관측 사실만 담는다.

INV-020 강제: ``site_frame``·``observed_at``·``position_covariance``가 required —
세계좌표를 주장하는 순간 좌표계·시각·불확실성을 함께 가져야 한다.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class Observation(BaseModel):
    """단일 센서 관측 1건이 세계좌표로 해석된 결과.

    Attributes:
        observation_id: 관측 고유 식별자(EventBundle/WorldEntity lineage가 참조).
        track_id: 이 관측이 속한 track(다중 프레임 연결). 아직 track이 없으면 None.
        observed_at: 관측 시각. **timezone-aware UTC 강제** — naive 시각이 섞이면
            비교·정렬에서 런타임 예외가 되거나(TypeError) 서로 다른 기준의 시각을
            같은 축으로 착각한다. ``ksi_geo_core``의 UTC 도메인 규약과 같은 이유다.
        site_frame: 좌표계 식별자(CRS/site transform version) — INV-020.
        position: site_frame 기준 3D 위치.
        position_covariance: 3×3 공분산 row-major 9원소 — 단일 점 주장 금지(INV-021).
        detection_confidence: 원 Detection의 분류 신뢰도(0~1).
        geo_confidence: 좌표화 신뢰도 — ``ksi_geo_core.projection`` 산출값(0~1).
        sensor_id: 관측을 만든 센서/카메라 식별자.
        viewpoint_id: 관측이 이루어진 **관측점** 식별자.

            **의미 규약(HIL 이전 확정, 독립 검토 2026-07-27 지정):** 이 값은 임의 프레임
            ID가 **아니다.** 프레임마다 다른 값을 넣으면 정지 호버링 중 연속 프레임이
            서로 다른 관측점으로 계상되어, 시차 없는 관측이 다중 시점 증거로 오인된다
            (시점 다양성 게이트가 무력화된다).

            허용되는 값은 둘 중 하나다:

            1. **Calibrated camera pose 참조** — 보정된 카메라 Pose 레코드의 ID.
               같은 Pose에서 찍은 프레임은 같은 ``viewpoint_id`` 를 갖는다.
            2. **Viewpoint bin** — 위 Pose를 사용할 수 없을 때, 관측점 공간을 이산화한
               bin의 ID(:func:`viewpoint_bin_id` 로 생성). 기하적으로 의미 있는 시차가
               생기는 최소 간격 이상 떨어진 관측점만 서로 다른 bin에 들어간다.

            관측점을 추적하지 못하는 소스는 ``None`` 이며, 그 경우 조립은 시점 다양성을
            **주장하지 않는다**(CONFIRMED로 올리지 않는다).
        lineage: 모델·보정 버전 계보(INV-042). 자유 dict이며 상위 EventBundle의
            ``lineage``와 동일 의미를 갖는다.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    observation_id: str = Field(min_length=1)
    track_id: str | None = None
    observed_at: AwareDatetime
    site_frame: str
    position: list[float] = Field(min_length=3, max_length=3)
    position_covariance: list[float] = Field(min_length=9, max_length=9)
    detection_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    geo_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    sensor_id: str | None = None
    viewpoint_id: str | None = None
    lineage: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observation_id", "track_id", "viewpoint_id", "sensor_id")
    @classmethod
    def _reject_blank_identifier(cls, value: str | None) -> str | None:
        """공백·whitespace-only 식별자 거부 (독립 검토 2026-07-27 지정).

        ``" "`` 같은 값은 ``min_length=1`` 을 통과하지만 식별자로 쓸 수 없다 — 정렬·
        중복 판정·fingerprint에서 조용히 서로 다른 것을 같게(또는 그 반대로) 만든다.
        """
        if value is not None and not value.strip():
            raise ValueError("식별자는 공백만으로 구성될 수 없다")
        return value

    @field_validator("observed_at")
    @classmethod
    def _must_be_utc(cls, value: datetime) -> datetime:
        """tz-aware 인 것에 더해 **UTC 오프셋**을 요구한다.

        ``AwareDatetime`` 은 tzinfo 존재만 보장하므로 KST 같은 로컬 오프셋도 통과한다.
        서로 다른 오프셋이 섞이면 비교는 되지만 사람이 로그를 읽을 때 시각을 오해하고,
        digest·fingerprint 문자열이 같은 순간에 대해 달라진다 — UTC로 고정한다.
        """
        if value.utcoffset() != timedelta(0):
            raise ValueError(f"observed_at 은 UTC여야 한다 (offset={value.utcoffset()})")
        return value


# 관측점 bin 기본 간격 — 이보다 가까운 두 관측점은 같은 bin(=같은 시점)으로 본다.
# 근거: 시차(parallax) 기반 깊이 검증이 의미를 가지려면 기선(baseline)이 대상 거리에
# 비해 무시할 수 없어야 한다. 2m는 수십 m 거리 대상에 대한 보수적 최소 기선이며,
# **실측 미검증 임시값**이다(PRD_AMBIGUITY_REGISTER의 렌즈별 위치오차 계열이 확정할
# 파라미터). Geo Safety Profile로 승격되기 전까지 이 값을 검증된 것으로 취급하지 않는다.
DEFAULT_VIEWPOINT_BIN_METERS = 2.0


def viewpoint_bin_id(
    position: tuple[float, float, float],
    *,
    bin_meters: float = DEFAULT_VIEWPOINT_BIN_METERS,
) -> str:
    """관측점 좌표를 이산 bin ID로 변환한다 — ``viewpoint_id`` 의 **차선** 형식.

    Calibrated camera pose 레코드를 아직 쓸 수 없을 때의 폴백이다. 관측점 위치를
    격자로 이산화해 대부분의 호버링 프레임이 같은 bin에 묶이게 한다.

    ## 알려진 한계 — 격자 경계 민감성 (숨기지 않고 기록)

    격자 방식은 **경계를 걸친 두 관측점을 서로 다른 bin으로 본다.** 예컨대 bin 2m에서
    ``x=9.9`` 와 ``x=10.0`` 은 0.1m 차이지만 각각 bin 4·5에 들어간다. 이는 시점
    다양성을 **과다 계상**하는 방향의 오차다(실제로는 시차가 없는데 서로 다른 시점으로
    보임) — 안전하지 않은 방향이므로 반드시 인지해야 한다.

    따라서:

    - **권위 있는 형식은 calibrated camera pose 참조다.** 실기 보정이 붙는 시점에
      그쪽으로 옮기고 이 폴백은 개발·재생 전용으로 격하한다.
    - 이 함수만으로 ``CONFIRMED`` 승격을 정당화하지 않는다. 시점 다양성은 필요조건이며,
      기선(baseline) 기반 검증은 pose 데이터가 Observation에 실린 뒤 추가한다.
    - 경계 민감성은 ``tests/replay`` 에 명시적 회귀 테스트로 고정돼 있다(숨은 성질이
      아니라 알려진 성질로 다룬다).

    Args:
        position: 관측점(카메라) 위치. ``site_frame`` 기준 3D 좌표.
        bin_meters: bin 한 변의 길이(m). 양의 유한값이어야 한다.

    Raises:
        ValueError: ``bin_meters`` 가 비유한·비양수이거나 position에 비유한 값이 있을 때.
    """
    if not (math.isfinite(bin_meters) and bin_meters > 0):
        raise ValueError(f"bin_meters 는 finite한 양수여야 한다 (got {bin_meters!r})")
    if not all(math.isfinite(v) for v in position):
        raise ValueError(f"position 에 비유한 값이 있다 (got {position!r})")
    indices = tuple(math.floor(v / bin_meters) for v in position)
    return f"vpbin:{bin_meters:g}:{indices[0]}:{indices[1]}:{indices[2]}"
