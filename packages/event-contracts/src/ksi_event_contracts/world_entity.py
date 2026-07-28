"""WorldEntity v1.0 Pydantic 모델 (contracts/schemas/world-entity.v1.json SSOT, Stage C-1).

4D World Model의 관측 대상 1건 — 사람·장비·구조물 등이 세계좌표와 불확실성을 갖고
표현된다(MASTER_PRD §11.2). camelCase 표현·``extra="forbid"``는 P0-1 계약 모델과 동일
규약이다.

INV-020 강제 지점: ``site_frame``(CRS 참조)·``timestamp``·``uncertainty.position_covariance``가
전부 required다 — 세계좌표를 가진 Entity는 "어느 좌표계에서, 언제, 얼마나 불확실하게"를
반드시 동반한다. 셋 중 하나라도 빠지면 모델 검증에서 거부된다.

INV-042 강제 지점: ``lineage``(track_id·model_versions·calibration_profile_id)가 required —
모든 결과는 Model/Calibration Version 계보를 가진다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class Pose(_CamelModel):
    """세계좌표계에서의 위치·자세·속도. ``position``만 필수(자세·속도는 관측 가능할 때만)."""

    position: list[float] = Field(min_length=3, max_length=3)
    orientation_quaternion: list[float] | None = Field(default=None, min_length=4, max_length=4)
    velocity: list[float] | None = Field(default=None, min_length=3, max_length=3)


class Uncertainty(_CamelModel):
    """INV-021 근거 데이터 — 위치 공분산은 필수다(단일 점으로 표현하지 않는다).

    ``position_covariance``는 3×3 공분산 행렬을 row-major 9원소로 편 것이다
    (스키마의 ``minItems/maxItems: 9``와 정합).
    """

    position_covariance: list[float] = Field(min_length=9, max_length=9)
    classification_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    localization_state: (
        Literal[
            "CONFIRMED",
            "LIKELY",
            "BOUNDARY_UNCERTAIN",
            "INSUFFICIENT_OBSERVATION",
            "STALE",
            "LOST",
        ]
        | None
    ) = None


class ClassificationSource(_CamelModel):
    """분류의 원시 출처 계보(INV-031) — 어떤 taxonomy 의 어떤 원시 클래스에서
    이 Entity 의 canonical class 가 번역됐는지."""

    taxonomy: str
    source_class_ids: list[int]
    source_class_names: list[str]


class EntityLineage(_CamelModel):
    """INV-042 — Track·Model·Calibration 계보. 관측 ID 목록으로 원본까지 역추적 가능.

    ``classification_ontology_version`` (INV-031, 독립 재검토 Blocker 5): 이 Entity 의
    class 문자열("Person")이 **어느 번역 규칙의 의미**인지 Entity 자체에서 알 수 있어야
    한다 — Observation 목록을 역조회해야만 알 수 있으면 계보가 아니다. Optional 인
    이유는 스키마 후방 호환(기존 산출물)이며, assembly 는 항상 채운다.
    """

    track_id: str
    model_versions: dict[str, Any]
    calibration_profile_id: str
    observation_ids: list[str] | None = None
    classification_ontology_version: str | None = None
    classification_source: ClassificationSource | None = None


class WorldEntity(_CamelModel):
    """world-entity.v1.json 대응 모델.

    ``entity_class``는 스키마의 ``class`` 필드에 대응한다 — ``class``가 Python 예약어라
    필드명을 바꾸고 ``Field(alias="class")``로 직렬화 이름을 고정했다(``alias_generator``
    보다 명시 alias가 우선한다).
    """

    schema_version: Literal["1.0"] = "1.0"
    entity_id: str
    entity_class: str = Field(alias="class")
    subclass: str | None = None
    timestamp: datetime
    site_frame: str
    pose: Pose
    uncertainty: Uncertainty
    kinematic_state: dict[str, Any] | None = None
    relationships: list[dict[str, Any]] | None = None
    lineage: EntityLineage
