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
from enum import StrEnum
from typing import Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel


class ViewpointEvidenceKind(StrEnum):
    """``viewpoint_id`` 가 **어떤 종류의 증거**인지 — 시점 다양성의 신뢰 등급 (INV-025).

    관측점 ID 문자열은 그 자체로 증거 강도를 말해주지 않는다. 보정된 카메라 Pose를
    가리키는 ID와, 관측점 좌표를 격자로 이산화한 bin ID는 문자열로는 구분되지 않지만
    **기하적 보장 수준이 다르다.** 이 등급이 그 차이를 계약에 명시한다.

    ``CALIBRATED_POSE``
        보정된 카메라 Pose 레코드 참조. 서로 다른 Pose는 실제로 서로 다른 관측점이며,
        시차(parallax) 기반 깊이 검증의 근거가 될 수 있다. **CONFIRMED 승격의 유일한
        허용 증거**다.

    ``SPATIAL_BIN``
        :func:`viewpoint_bin_id` 로 만든 이산 bin ID(폴백). 격자 경계를 걸친 근접
        관측점이 서로 다른 bin이 되므로 시점 다양성을 **과다 계상**할 수 있다 —
        안전하지 않은 방향의 오차이므로 **최대 LIKELY** 로 제한된다.

    ``UNKNOWN``
        출처를 보증할 수 없는 관측점 ID(또는 ID 자체가 없음). 기본값이며 **최대
        LIKELY** — 모르면 확신하지 않는다.

    기본값이 ``UNKNOWN`` 인 것은 의도적이다. 시점 다양성 주장은 생산자가 **명시적으로
    선언**해야 얻어지는 권한이며, 필드를 채우지 않은 소스가 우연히 CONFIRMED 를 얻는
    경로를 만들지 않는다(fail-safe).
    """

    CALIBRATED_POSE = "CALIBRATED_POSE"
    SPATIAL_BIN = "SPATIAL_BIN"
    UNKNOWN = "UNKNOWN"


# 시점 증거 강도 순서 — 관측 집합의 등급은 **가장 약한 관측**을 따른다(낙관적 병합 금지).
_VIEWPOINT_STRENGTH: dict[ViewpointEvidenceKind, int] = {
    ViewpointEvidenceKind.UNKNOWN: 0,
    ViewpointEvidenceKind.SPATIAL_BIN: 1,
    ViewpointEvidenceKind.CALIBRATED_POSE: 2,
}

# :func:`viewpoint_bin_id` 산출물의 고정 prefix — 계약 계층이 bin 을 식별하는 기준.
SPATIAL_BIN_ID_PREFIX = "vpbin:"


class Observation(BaseModel):
    """단일 센서 관측 1건이 세계좌표로 해석된 결과.

    Attributes:
        observation_id: 관측 고유 식별자(EventBundle/WorldEntity lineage가 참조).
        observed_class: 이 관측의 **Canonical Entity Class** ("Person" 등 —
            ``ksi_domain.ontology``). Detection 의 분류가 Observation 단계에서
            사라지면 하류가 상수값으로 대체하게 된다(INV-031 위반, F13) — 그래서
            **required** 다. 분류를 모르는 관측은 세계 모델에 편입될 수 없다.
        source_class_id: 모델 원시 클래스 index (분류 계보, 모를 수 있음).
        source_class_name: 모델 원시 클래스명 (분류 계보, 모를 수 있음).
        ontology_version: 원시→canonical 번역 규칙의 버전 (required — 버전 없는
            번역은 재현할 수 없다).
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
        viewpoint_kind: ``viewpoint_id`` 의 증거 등급(:class:`ViewpointEvidenceKind`).

            ID 문자열만으로는 두 형식(Pose 참조 / bin)을 구분할 수 없으므로 종류를
            **명시적으로 선언**한다. 기본값은 ``UNKNOWN`` 이며, 선언하지 않은 소스는
            시점 다양성을 주장하지 못한다(최대 LIKELY) — fail-safe.
        lineage: 모델·보정 버전 계보(INV-042). 자유 dict이며 상위 EventBundle의
            ``lineage``와 동일 의미를 갖는다.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    observation_id: str = Field(min_length=1)
    observed_class: str = Field(min_length=1)
    source_class_id: int | None = None
    source_class_name: str | None = None
    ontology_version: str = Field(min_length=1)
    track_id: str | None = None
    observed_at: AwareDatetime
    site_frame: str
    position: list[float] = Field(min_length=3, max_length=3)
    position_covariance: list[float] = Field(min_length=9, max_length=9)
    detection_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    geo_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    sensor_id: str | None = None
    viewpoint_id: str | None = None
    viewpoint_kind: ViewpointEvidenceKind = ViewpointEvidenceKind.UNKNOWN
    lineage: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _viewpoint_kind_matches_id(self) -> Observation:
        """선언한 증거 등급과 ID의 실제 형식이 어긋나면 거부한다.

        두 가지 모순을 막는다:

        1. **ID 없이 등급만 선언** — 관측점을 모르는데 증거 등급을 주장할 수 없다.
        2. **bin ID를 Pose로 위장** — :func:`viewpoint_bin_id` 산출물(``vpbin:`` prefix)은
           우리가 만드는 값이므로, 그것이 ``CALIBRATED_POSE`` 로 선언되는 것은 언제나
           오류다. 이 경로를 막지 않으면 격자 경계 과다계상(모듈 하단 참고)이 그대로
           CONFIRMED 승격 권한을 얻는다.

        반대로 "ID는 있는데 등급은 ``UNKNOWN``"은 **허용**한다 — 출처를 보증할 수 없다는
        정직한 선언이며, 그 결과는 시점 다양성 미주장(최대 LIKELY)이다.
        """
        if self.viewpoint_id is None and self.viewpoint_kind is not ViewpointEvidenceKind.UNKNOWN:
            raise ValueError(
                f"viewpoint_id 없이 viewpoint_kind={self.viewpoint_kind} 를 주장할 수 없다"
            )
        if (
            self.viewpoint_id is not None
            and self.viewpoint_id.startswith(SPATIAL_BIN_ID_PREFIX)
            and self.viewpoint_kind is ViewpointEvidenceKind.CALIBRATED_POSE
        ):
            raise ValueError(
                f"{SPATIAL_BIN_ID_PREFIX!r} 로 시작하는 관측점 ID는 이산 bin이므로 "
                "CALIBRATED_POSE 로 선언할 수 없다(시차 보장 없음)"
            )
        return self

    @field_validator(
        "observation_id",
        "observed_class",
        "ontology_version",
        "source_class_name",
        "track_id",
        "viewpoint_id",
        "sensor_id",
    )
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
    - **이 함수의 산출물은 ``CONFIRMED`` 승격 권한을 갖지 않는다.** 문서상의 주의가
      아니라 코드로 강제된다: 반환값은 ``vpbin:`` prefix를 갖고, 계약 계층이 이를
      :attr:`ViewpointEvidenceKind.SPATIAL_BIN` 으로 고정해(:func:`effective_viewpoint_kind`)
      조립 단계에서 최대 ``LIKELY`` 로 제한한다. 기선(baseline)·시차 조건 검증은 실제
      pose 데이터가 Observation에 실린 뒤 ``CALIBRATED_POSE`` 경로에 추가한다.
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
    return f"{SPATIAL_BIN_ID_PREFIX}{bin_meters:g}:{indices[0]}:{indices[1]}:{indices[2]}"


def effective_viewpoint_kind(
    viewpoint_id: str | None,
    declared: ViewpointEvidenceKind,
) -> ViewpointEvidenceKind:
    """선언된 등급과 ID 형식 중 **약한 쪽**을 실제 등급으로 삼는다.

    :class:`Observation` 검증기가 이미 모순 조합을 거부하므로 정상 경로에서는 선언값이
    그대로 나온다. 이 함수는 그 검증을 우회해 만들어진 객체(``model_construct``·수동
    구성·역직렬화 우회)까지 덮는 **2차 방어선**이다 — 시점 다양성은 CONFIRMED 승격의
    직접 근거이므로 단일 검증 지점에 의존하지 않는다.
    """
    if viewpoint_id is None:
        return ViewpointEvidenceKind.UNKNOWN
    if (
        viewpoint_id.startswith(SPATIAL_BIN_ID_PREFIX)
        and declared is ViewpointEvidenceKind.CALIBRATED_POSE
    ):
        return ViewpointEvidenceKind.SPATIAL_BIN
    return declared


def weakest_viewpoint_kind(kinds: list[ViewpointEvidenceKind]) -> ViewpointEvidenceKind:
    """관측 집합의 시점 증거 등급 — 가장 약한 관측이 전체를 결정한다.

    낙관적 병합 금지 원칙(분류 신뢰도의 ``min`` 병합과 동형)이다. 강한 증거 일부만
    골라 세면, 출처 불명 관측이 섞인 융합 결과가 CONFIRMED 를 얻는 경로가 열린다.
    빈 목록은 ``UNKNOWN`` 이다(주장할 근거 없음).
    """
    if not kinds:
        return ViewpointEvidenceKind.UNKNOWN
    return min(kinds, key=lambda k: _VIEWPOINT_STRENGTH[k])
