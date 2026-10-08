"""RiskField 계약 — contracts/schemas/risk-field.v1.json 의 Python 대응
(PRD RISK-003/RISK-004, §12.6/§12.7).

## 이 모듈이 하지 않는 것 — 위험장 지오메트리 합성

RISK-003("동적 3D 위험장을 자동 생성한다")의 지오메트리 합성(스윕 볼륨·가려짐
반영 등)은 이 모듈의 범위 밖이다 — 그 자체로 별도 제품 결정(어떤 형상 근사를
쓸지, 카메라 가려짐을 어떻게 반영할지)이 필요한 큰 문제이고, Kinematic
State/CPA/TTC 계산기라는 이번 스코프를 넘는다. :func:`build_dynamic_risk_field`
는 ``geometry``·``sourceEntityIds``·``validity`` 를 호출자가 이미 만든 값으로
받는다 — 이 함수가 지어내지 않는다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from ksi_equipment_intelligence.cpa_ttc import (
    KinematicComparisonError,
    closest_point_of_approach,
    time_to_collision,
)
from ksi_equipment_intelligence.kinematic_state import KinematicState

RiskFieldType = Literal["STATIC", "DERIVED", "DYNAMIC", "PREDICTED"]
GeometryFormat = Literal[
    "GEOJSON_2D", "EXTRUDED_POLYGON", "MESH", "VOXEL_GRID", "PARAMETRIC_VOLUME"
]


class RiskFieldValidity(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    from_: AwareDatetime = Field(alias="from")
    to: AwareDatetime


class RiskFieldGeometry(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    format: GeometryFormat
    payload: Any = None


class RiskModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    policy_id: str = Field(min_length=1)
    severity: float = Field(ge=0.0, le=1.0)
    prediction_horizon_seconds: float
    closest_approach_m: float | None = None
    time_to_collision_s: float | None = None


class RiskFieldLineage(BaseModel):
    """v1.1 Edge 생성 RiskField의 재현 필수 계보.

    v1.0은 기존 Core 입력과의 호환을 위해 그대로 읽는다. v1.1은 RiskPolicyPack
    digest·보정 profile·근거 시각을 빼면 같은 위험장을 재현하거나 검증할 수 없으므로
    이 블록을 required로 둔다(INV-020/022).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    risk_policy_pack_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    calibration_profile_id: str = Field(min_length=1)
    source_timestamp: AwareDatetime
    sensor_timestamp: AwareDatetime | None = None


class RiskField(BaseModel):
    """v1.0/v1.1 RiskField transition reader.

    Core는 이행 기간에 두 wire 세대를 모두 읽는다. 새 Edge producer는 v1.1만
    만들며, 그 경우 ``lineage``와 ``EXTRUDED_POLYGON``을 강제한다.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0", "1.1"] = "1.0"
    risk_field_id: str = Field(min_length=1)
    type: RiskFieldType
    hazard_type: str | None = None
    source_entity_ids: list[str]
    validity: RiskFieldValidity
    geometry: RiskFieldGeometry
    risk_model: RiskModel
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    lineage: RiskFieldLineage | None = None

    @model_validator(mode="after")
    def _version_rules(self) -> RiskField:
        if self.schema_version == "1.0" and self.lineage is not None:
            raise ValueError("RiskField v1.0에는 lineage를 넣을 수 없다")
        if self.schema_version == "1.1":
            if self.lineage is None:
                raise ValueError("RiskField v1.1에는 lineage가 필수다")
            if self.geometry.format != "EXTRUDED_POLYGON":
                raise ValueError("새 Edge RiskField v1.1 geometry는 EXTRUDED_POLYGON이어야 한다")
        return self


def risk_field_wire_dict(field: RiskField) -> dict[str, Any]:
    """계약 스키마와 정확히 대조 가능한 wire 표현(왕복 검증 대상).

    ``model_dump(..., exclude_none=True)``를 통짜로 쓰지 않는다 — 그렇게 하면
    ``geometry.payload``가 None일 때 키 자체가 사라져 스키마 required
    (``contracts/schemas/risk-field.v1.json`` geometry.required=["format","payload"])를
    위반한다(F2, 2026-08-06 재검증에서 재현 확인). ``payload``는 값이 없어도 키는
    남아야 하므로, "값이 없으면 키를 뺀다"는 optional 필드(``hazardType``·
    ``riskModel.closestApproachM``·``riskModel.timeToCollisionS``)에만 선택적으로
    적용한다.
    """
    wire = field.model_dump(by_alias=True, mode="json", exclude_none=False)
    if wire.get("hazardType") is None:
        wire.pop("hazardType", None)
    if wire.get("lineage") is None:
        wire.pop("lineage", None)
    risk_model = wire.get("riskModel")
    if isinstance(risk_model, dict):
        if risk_model.get("closestApproachM") is None:
            risk_model.pop("closestApproachM", None)
        if risk_model.get("timeToCollisionS") is None:
            risk_model.pop("timeToCollisionS", None)
    lineage = wire.get("lineage")
    if isinstance(lineage, dict) and lineage.get("sensorTimestamp") is None:
        lineage.pop("sensorTimestamp", None)
    return wire


def _require_validity_covers_observations(
    validity: RiskFieldValidity, *states: KinematicState
) -> None:
    """유효구간이 근거 관측 시각을 덮는가(:func:`build_dynamic_risk_field` docstring).

    ``validity.from_ <= observed_at <= validity.to`` 를 요구한다. 경계 포함이다 —
    딱 그 순간에 관측한 위험장을 거부할 이유가 없다.
    """
    if validity.to < validity.from_:
        raise KinematicComparisonError(
            f"validity.to({validity.to.isoformat()}) 가 "
            f"validity.from({validity.from_.isoformat()}) 보다 앞선다"
        )
    for state in states:
        if not (validity.from_ <= state.observed_at <= validity.to):
            raise KinematicComparisonError(
                f"{state.entity_id!r} 의 observed_at({state.observed_at.isoformat()}) 이 "
                f"validity 구간[{validity.from_.isoformat()}, {validity.to.isoformat()}] "
                "밖이다 — 자기가 근거로 삼은 관측이 유효하지 않다고 선언하는 위험장은"
                " 만들지 않는다"
            )


def build_dynamic_risk_field(
    *,
    risk_field_id: str,
    equipment_state: KinematicState,
    subject_state: KinematicState,
    policy_id: str,
    severity: float,
    horizon_s: float,
    combined_radius_m: float,
    max_observation_gap_s: float,
    validity: RiskFieldValidity,
    geometry: RiskFieldGeometry,
    hazard_type: str | None = None,
    schema_version: Literal["1.0", "1.1"] = "1.0",
    lineage: RiskFieldLineage | None = None,
) -> RiskField:
    """장비-대상 KinematicState 쌍에서 DYNAMIC RiskField 를 만든다(RISK-004).

    ``riskModel.closestApproachM``/``timeToCollisionS`` 를
    :func:`~ksi_equipment_intelligence.cpa_ttc.closest_point_of_approach`/
    :func:`~ksi_equipment_intelligence.cpa_ttc.time_to_collision` 로 채운다 —
    이 값들은 지어낼 수 없는 계산값이므로 이 함수가 유일한 조립 지점이다.
    ``geometry``/``sourceEntityIds`` 는 호출자 책임(모듈 docstring). 새 Edge
    producer는 ``schema_version="1.1"``과 계보를 넘겨야 하며, 이때 geometry는
    보수적 이동 footprint를 담은 ``EXTRUDED_POLYGON``만 허용한다.

    ``validity`` 는 호출자가 만들지만 **관측 시각과의 관계는 여기서 검사한다** —
    두 상태를 관측한 시점이 유효구간 밖이면, 그 위험장은 자기가 근거로 삼은 관측이
    유효하지 않다고 스스로 선언하는 셈이다. 그런 RiskField 는 소비자가 "지금 유효한
    위험"으로 읽고 만료된 관측으로 행동하게 만든다. ``validity.to`` 가 관측 시각보다
    앞서는(이미 만료된 채로 태어나는) 경우도 같은 사유로 거부한다.

    Raises:
        ksi_equipment_intelligence.cpa_ttc.KinematicComparisonError: 두 상태의
            site_frame 이 다르거나, observed_at 시간차가 ``max_observation_gap_s`` 를
            넘거나, horizon_s·combined_radius_m 이 유효하지 않거나, 관측 시각이
            ``validity`` 구간 밖일 때.
    """
    cpa = closest_point_of_approach(
        equipment_state,
        subject_state,
        horizon_s=horizon_s,
        max_observation_gap_s=max_observation_gap_s,
    )
    ttc = time_to_collision(
        equipment_state,
        subject_state,
        combined_radius_m=combined_radius_m,
        horizon_s=horizon_s,
        max_observation_gap_s=max_observation_gap_s,
    )
    _require_validity_covers_observations(validity, equipment_state, subject_state)
    return RiskField(
        schema_version=schema_version,
        risk_field_id=risk_field_id,
        type="DYNAMIC",
        hazard_type=hazard_type,
        source_entity_ids=[equipment_state.entity_id, subject_state.entity_id],
        validity=validity,
        geometry=geometry,
        risk_model=RiskModel(
            policy_id=policy_id,
            severity=severity,
            prediction_horizon_seconds=horizon_s,
            closest_approach_m=cpa.distance_m,
            time_to_collision_s=ttc,
        ),
        lineage=lineage,
    )


__all__ = [
    "GeometryFormat",
    "RiskField",
    "RiskFieldGeometry",
    "RiskFieldLineage",
    "RiskFieldType",
    "RiskFieldValidity",
    "RiskModel",
    "build_dynamic_risk_field",
    "risk_field_wire_dict",
]
