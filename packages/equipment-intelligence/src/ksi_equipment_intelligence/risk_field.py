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

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ksi_equipment_intelligence.cpa_ttc import closest_point_of_approach, time_to_collision
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


class RiskField(BaseModel):
    """contracts/schemas/risk-field.v1.json 왕복 대상 — required 필드는 스키마와 동일."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    risk_field_id: str = Field(min_length=1)
    type: RiskFieldType
    hazard_type: str | None = None
    source_entity_ids: list[str]
    validity: RiskFieldValidity
    geometry: RiskFieldGeometry
    risk_model: RiskModel
    uncertainty: dict[str, Any] = Field(default_factory=dict)


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
    risk_model = wire.get("riskModel")
    if isinstance(risk_model, dict):
        if risk_model.get("closestApproachM") is None:
            risk_model.pop("closestApproachM", None)
        if risk_model.get("timeToCollisionS") is None:
            risk_model.pop("timeToCollisionS", None)
    return wire


def build_dynamic_risk_field(
    *,
    risk_field_id: str,
    equipment_state: KinematicState,
    subject_state: KinematicState,
    policy_id: str,
    severity: float,
    horizon_s: float,
    combined_radius_m: float,
    validity: RiskFieldValidity,
    geometry: RiskFieldGeometry,
    hazard_type: str | None = None,
) -> RiskField:
    """장비-대상 KinematicState 쌍에서 DYNAMIC RiskField 를 만든다(RISK-004).

    ``riskModel.closestApproachM``/``timeToCollisionS`` 를
    :func:`~ksi_equipment_intelligence.cpa_ttc.closest_point_of_approach`/
    :func:`~ksi_equipment_intelligence.cpa_ttc.time_to_collision` 로 채운다 —
    이 값들은 지어낼 수 없는 계산값이므로 이 함수가 유일한 조립 지점이다.
    ``geometry``/``validity``/``sourceEntityIds`` 는 호출자 책임(모듈 docstring).

    Raises:
        ksi_equipment_intelligence.cpa_ttc.KinematicComparisonError: 두 상태의
            site_frame 이 다르거나 horizon_s·combined_radius_m 이 유효하지 않을 때.
    """
    cpa = closest_point_of_approach(equipment_state, subject_state, horizon_s=horizon_s)
    ttc = time_to_collision(
        equipment_state,
        subject_state,
        combined_radius_m=combined_radius_m,
        horizon_s=horizon_s,
    )
    return RiskField(
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
    )


__all__ = [
    "GeometryFormat",
    "RiskField",
    "RiskFieldGeometry",
    "RiskFieldType",
    "RiskFieldValidity",
    "RiskModel",
    "build_dynamic_risk_field",
    "risk_field_wire_dict",
]
