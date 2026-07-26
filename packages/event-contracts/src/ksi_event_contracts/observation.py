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
        viewpoint_id: 관측이 이루어진 **관측점** 식별자(프레임/카메라 Pose 참조).
            서로 다른 ``observation_id`` 라도 같은 관측점에서 나온 관측이면 독립적인
            다중 시점 증거가 아니다 — 조립 계층이 이 값으로 시점 다양성을 판정한다.
            아직 관측점을 추적하지 못하는 소스는 None이며, 그 경우 조립은 시점 다양성을
            **주장하지 않는다**(CONFIRMED로 올리지 않는다).
        lineage: 모델·보정 버전 계보(INV-042). 자유 dict이며 상위 EventBundle의
            ``lineage``와 동일 의미를 갖는다.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    observation_id: str
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
