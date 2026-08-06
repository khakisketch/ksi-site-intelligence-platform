"""RiskField 계약 왕복 + build_dynamic_risk_field 조립 (Phase 3, PRD RISK-003/004,
contracts/schemas/risk-field.v1.json)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from ksi_equipment_intelligence.kinematic_state import KinematicState
from ksi_equipment_intelligence.risk_field import (
    RiskField,
    RiskFieldGeometry,
    RiskFieldValidity,
    build_dynamic_risk_field,
    risk_field_wire_dict,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "contracts" / "schemas" / "risk-field.v1.json"
_NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
_COV3 = [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")))


def _state(*, entity_id: str, position: list[float], velocity: list[float]) -> KinematicState:
    return KinematicState(
        entity_id=entity_id,
        observed_at=_NOW,
        site_frame="site-001",
        position=position,
        position_covariance=_COV3,
        velocity=velocity,
        velocity_covariance=_COV3,
        source_class="Excavator",
    )


def _validity() -> RiskFieldValidity:
    return RiskFieldValidity(from_=_NOW, to=_NOW + timedelta(seconds=30))  # type: ignore[call-arg]


def _geometry() -> RiskFieldGeometry:
    return RiskFieldGeometry(format="GEOJSON_2D", payload={"type": "Point", "coordinates": [0, 0]})


def test_model_output_satisfies_contract_schema() -> None:
    """Python 모델의 wire 산출이 계약 스키마를 만족한다 — 두 정본이 갈라지지 않게."""
    equipment = _state(entity_id="excavator-1", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    subject = _state(entity_id="worker-1", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    field = build_dynamic_risk_field(
        risk_field_id="rf-1",
        equipment_state=equipment,
        subject_state=subject,
        policy_id="policy-1",
        severity=0.8,
        horizon_s=100.0,
        combined_radius_m=1.0,
        validity=_validity(),
        geometry=_geometry(),
        hazard_type="STRUCK_BY",
    )
    _validator().validate(risk_field_wire_dict(field))


def test_wire_carries_camel_case_and_computed_fields() -> None:
    equipment = _state(entity_id="excavator-1", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    subject = _state(entity_id="worker-1", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    field = build_dynamic_risk_field(
        risk_field_id="rf-1",
        equipment_state=equipment,
        subject_state=subject,
        policy_id="policy-1",
        severity=0.8,
        horizon_s=100.0,
        combined_radius_m=1.0,
        validity=_validity(),
        geometry=_geometry(),
    )
    wire = risk_field_wire_dict(field)
    assert wire["riskFieldId"] == "rf-1"
    assert wire["type"] == "DYNAMIC"
    assert wire["sourceEntityIds"] == ["excavator-1", "worker-1"]
    assert wire["riskModel"]["closestApproachM"] == pytest.approx(0.0, abs=1e-9)
    assert wire["riskModel"]["timeToCollisionS"] == pytest.approx(4.5)
    assert wire["schemaVersion"] == "1.0"


def test_builder_omits_hazard_type_when_not_given() -> None:
    """hazard_type=None 은 exclude_none 이 wire 에서 빼야 한다(스키마 optional)."""
    equipment = _state(entity_id="e", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    subject = _state(entity_id="s", position=[100.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    field = build_dynamic_risk_field(
        risk_field_id="rf-2",
        equipment_state=equipment,
        subject_state=subject,
        policy_id="policy-1",
        severity=0.1,
        horizon_s=10.0,
        combined_radius_m=1.0,
        validity=_validity(),
        geometry=_geometry(),
    )
    wire = risk_field_wire_dict(field)
    assert "hazardType" not in wire


def test_no_future_collision_leaves_ttc_null_in_wire() -> None:
    equipment = _state(entity_id="e", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    subject = _state(entity_id="s", position=[1000.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    field = build_dynamic_risk_field(
        risk_field_id="rf-3",
        equipment_state=equipment,
        subject_state=subject,
        policy_id="policy-1",
        severity=0.1,
        horizon_s=10.0,
        combined_radius_m=1.0,
        validity=_validity(),
        geometry=_geometry(),
    )
    assert field.risk_model.time_to_collision_s is None
    wire = risk_field_wire_dict(field)
    assert "timeToCollisionS" not in wire  # exclude_none — null 을 명시적으로 내보내지 않는다


def test_geometry_payload_none_still_satisfies_schema_required() -> None:
    """[F2 회귀] geometry.payload=None이어도 wire에 payload 키가 남아야 한다.

    contracts/schemas/risk-field.v1.json의 geometry.required=["format","payload"]다
    — payload가 optional이 아니다. RiskFieldGeometry.payload 기본값이 None인 채로
    ``exclude_none=True``를 통짜로 쓰면 이 키가 wire에서 사라져 스키마 required를
    위반한다(2026-08-06 phase-3-kinematic-risk-field 재검증에서 재현·수정).
    """
    equipment = _state(entity_id="excavator-1", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    subject = _state(entity_id="worker-1", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    geometry = RiskFieldGeometry(format="GEOJSON_2D")  # payload 미지정 — 기본값 None
    field = build_dynamic_risk_field(
        risk_field_id="rf-f2",
        equipment_state=equipment,
        subject_state=subject,
        policy_id="policy-1",
        severity=0.5,
        horizon_s=100.0,
        combined_radius_m=1.0,
        validity=_validity(),
        geometry=geometry,
    )
    wire = risk_field_wire_dict(field)
    assert "payload" in wire["geometry"], "payload 키가 사라지면 스키마 required 위반"
    assert wire["geometry"]["payload"] is None
    _validator().validate(wire)  # 스키마 왕복 검증 자체가 통과해야 한다


def test_severity_out_of_range_rejected() -> None:
    with pytest.raises(Exception, match="severity|less than or equal"):
        RiskField.model_validate(
            {
                "riskFieldId": "rf-bad",
                "type": "STATIC",
                "sourceEntityIds": [],
                "validity": {
                    "from": _NOW.isoformat(),
                    "to": (_NOW + timedelta(seconds=1)).isoformat(),
                },
                "geometry": {"format": "GEOJSON_2D"},
                "riskModel": {
                    "policyId": "p",
                    "severity": 1.5,
                    "predictionHorizonSeconds": 1.0,
                },
                "uncertainty": {},
            }
        )
