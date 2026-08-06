"""KinematicState 계약 — 장비 위치·속도 추정 1건 (Phase 3, PRD RISK-002/§12.7).

WorldEntity(INV-020)의 위치·불확실성 규약을 그대로 잇는다 —
:class:`~ksi_event_contracts.observation.Observation` 이 이미 확립한 "세계좌표를
주장하는 순간 좌표계·시각·공분산을 함께 갖는다"는 원칙을 속도 차원까지 확장한 것이
이 모델의 전부다. 새 원칙을 만들지 않는다.

## 이 모델이 하지 않는 것

- 궤적 융합·필터링(칼만 등)은 하지 않는다 — 이미 추정된 상태 1건을 typed 로
  나른다. 추정 알고리즘은 이 계약의 소비자(향후 tracking 계층) 몫이다.
- Manifold 로컬 판단·비행 명령은 만들지 않는다(CLAUDE.md Control boundaries) —
  이 패키지는 Core/Intelligence Plane 소비 대상이다.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class KinematicState(BaseModel):
    """장비(또는 작업자) 1개체의 위치·속도 추정 스냅샷 1건.

    Attributes:
        entity_id: 이 상태가 속한 WorldEntity 식별자.
        observed_at: 추정 기준 시각 — UTC 강제(Observation.observed_at 과 동일 규약).
        site_frame: 좌표계 식별자(CRS/site transform version) — INV-020.
        position: site_frame 기준 3D 위치(m).
        position_covariance: 3×3 공분산 row-major 9원소 — 단일 점 주장 금지
            (Observation.position_covariance 와 동일 규약, INV-021).
        velocity: site_frame 기준 3D 속도(m/s). 정지 상태는 ``[0, 0, 0]`` 로
            명시한다 — "속도 모름"은 이 필드가 아니라 상위 소비자의 미생성으로
            표현한다(이 계약은 항상 어떤 속도값을 주장한다).
        velocity_covariance: 3×3 공분산 row-major 9원소 — 속도판 position_covariance.
        heading_deg: 장비 지향각(도, 0=site_frame +x축, 반시계 — coverage.py 의
            수학 규약과 동일). ``None`` 이면 지향각 모름. **속도 방향과 다른
            개념이다** — 정지한 크레인도 붐 방향은 존재하므로 velocity=[0,0,0]
            이어도 heading_deg 는 의미를 가질 수 있다.
        source_class: 이 상태가 속한 장비 canonical class(예: "Excavator") —
            ``ksi_domain.capability.EquipmentSupportLevel`` 조회 키와 동일 값이어야
            한다(리스크 정책이 이 값으로 지원 수준을 찾는다). 이 패키지는 지원
            수준 상태머신을 별도로 두지 않는다 — SSOT는 ``packages/domain`` 이다
            (기존 INV-041 구현과의 중복 발견, 2026-08-06).
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )

    entity_id: str = Field(min_length=1)
    observed_at: AwareDatetime
    site_frame: str = Field(min_length=1)
    position: list[float] = Field(min_length=3, max_length=3)
    position_covariance: list[float] = Field(min_length=9, max_length=9)
    velocity: list[float] = Field(min_length=3, max_length=3)
    velocity_covariance: list[float] = Field(min_length=9, max_length=9)
    heading_deg: float | None = None
    source_class: str = Field(min_length=1)

    @field_validator("entity_id", "site_frame", "source_class")
    @classmethod
    def _reject_blank_identifier(cls, value: str) -> str:
        """공백만으로 구성된 식별자 거부(Observation 과 동일 규약)."""
        if not value.strip():
            raise ValueError("식별자는 공백만으로 구성될 수 없다")
        return value

    @field_validator("observed_at")
    @classmethod
    def _must_be_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError(f"observed_at 은 UTC여야 한다 (offset={value.utcoffset()})")
        return value

    @field_validator("position", "velocity", "position_covariance", "velocity_covariance")
    @classmethod
    def _reject_non_finite(cls, value: list[float]) -> list[float]:
        """NaN/Inf 는 "모름"이 아니라 산술 오염이다 — 조용히 통과시키지 않는다."""
        if not all(math.isfinite(v) for v in value):
            raise ValueError(f"비유한 값이 포함될 수 없다 (got {value!r})")
        return value

    @field_validator("heading_deg")
    @classmethod
    def _heading_finite_when_present(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError(f"heading_deg 는 finite 여야 한다 (got {value!r})")
        return value


__all__ = ["KinematicState"]
