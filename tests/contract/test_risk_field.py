"""RiskField 계약 왕복 + build_dynamic_risk_field 조립 (Phase 3, PRD RISK-003/004,
contracts/schemas/risk-field.v1.json)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from ksi_equipment_intelligence.cpa_ttc import KinematicComparisonError
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
# 이 파일의 상태들은 전부 동일 _NOW 를 쓴다 — 시간창 게이트 자체는
# test_cpa_ttc.py 가 고정하고, 여기서는 그 게이트를 통과시키기만 한다.
_MAX_GAP_S = 1.0


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
        max_observation_gap_s=_MAX_GAP_S,
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
        max_observation_gap_s=_MAX_GAP_S,
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
        max_observation_gap_s=_MAX_GAP_S,
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
        max_observation_gap_s=_MAX_GAP_S,
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
        max_observation_gap_s=_MAX_GAP_S,
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


# ── 왕복 역방향 (risk risk-field-round-trip-one-direction-only) ──────────────
#
# 기존 검증은 model→wire→schema 한 방향뿐이었다 — 스키마를 만족하는 wire dict 가
# 다시 모델로 파싱되는지는 아무도 보지 않았다. 실패를 예상하진 않지만, "왕복"이라는
# 표현이 절반만 검증된 상태로 남아 있으면 그 표현 자체가 근거가 되지 못한다.


def _built_field() -> RiskField:
    equipment = _state(entity_id="excavator-1", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    subject = _state(entity_id="worker-1", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    return build_dynamic_risk_field(
        risk_field_id="rf-roundtrip",
        equipment_state=equipment,
        subject_state=subject,
        policy_id="policy-1",
        severity=0.8,
        horizon_s=30.0,
        combined_radius_m=2.0,
        max_observation_gap_s=_MAX_GAP_S,
        validity=_validity(),
        geometry=_geometry(),
    )


def test_wire_dict_parses_back_into_an_equal_model() -> None:
    """wire → model 역방향이 원본과 **같은** 모델을 낸다(값 손실 없음)."""
    original = _built_field()
    wire = risk_field_wire_dict(original)
    assert not sorted(_validator().iter_errors(wire), key=lambda e: e.path)
    assert RiskField.model_validate(wire) == original


def test_optional_risk_model_fields_survive_the_round_trip() -> None:
    """closestApproachM/timeToCollisionS 가 None 인 경우도 왕복한다.

    risk_field_wire_dict 는 이 둘이 None 이면 키째 뺀다 — 그 상태의 wire 를 다시
    파싱했을 때 None 으로 복원되지 않으면 '없음'이 '0'으로 둔갑할 자리다.
    """
    far_apart = _state(entity_id="worker-2", position=[1000.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    still = _state(entity_id="excavator-2", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    field = build_dynamic_risk_field(
        risk_field_id="rf-none",
        equipment_state=still,
        subject_state=far_apart,
        policy_id="policy-1",
        severity=0.1,
        horizon_s=10.0,
        combined_radius_m=1.0,
        max_observation_gap_s=_MAX_GAP_S,
        validity=_validity(),
        geometry=_geometry(),
    )
    assert field.risk_model.time_to_collision_s is None
    wire = risk_field_wire_dict(field)
    assert "timeToCollisionS" not in wire["riskModel"]
    assert RiskField.model_validate(wire).risk_model.time_to_collision_s is None


# ── validity 가 근거 관측을 덮는가 (risk cpa-ttc-observed-at-mismatch-unchecked) ──


def test_observation_outside_validity_window_is_rejected() -> None:
    """자기가 근거로 삼은 관측이 유효하지 않다고 선언하는 위험장은 만들지 않는다.

    소비자는 이 RiskField 를 "지금 유효한 위험"으로 읽고 만료된 관측으로 행동한다.
    """
    equipment = _state(entity_id="excavator-1", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    subject = _state(entity_id="worker-1", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    future_only = RiskFieldValidity(  # type: ignore[call-arg]
        from_=_NOW + timedelta(minutes=5), to=_NOW + timedelta(minutes=10)
    )
    with pytest.raises(KinematicComparisonError, match="validity"):
        build_dynamic_risk_field(
            risk_field_id="rf-bad-validity",
            equipment_state=equipment,
            subject_state=subject,
            policy_id="policy-1",
            severity=0.8,
            horizon_s=30.0,
            combined_radius_m=2.0,
            max_observation_gap_s=_MAX_GAP_S,
            validity=future_only,
            geometry=_geometry(),
        )


def test_already_expired_validity_is_rejected() -> None:
    """validity.to 가 관측 시각보다 앞서면 태어나자마자 만료된 위험장이다."""
    equipment = _state(entity_id="excavator-1", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    subject = _state(entity_id="worker-1", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    expired = RiskFieldValidity(  # type: ignore[call-arg]
        from_=_NOW - timedelta(minutes=10), to=_NOW - timedelta(minutes=5)
    )
    with pytest.raises(KinematicComparisonError, match="validity"):
        build_dynamic_risk_field(
            risk_field_id="rf-expired",
            equipment_state=equipment,
            subject_state=subject,
            policy_id="policy-1",
            severity=0.8,
            horizon_s=30.0,
            combined_radius_m=2.0,
            max_observation_gap_s=_MAX_GAP_S,
            validity=expired,
            geometry=_geometry(),
        )


def test_observation_exactly_on_validity_boundary_is_accepted() -> None:
    """경계 포함 — 딱 그 순간에 관측한 위험장을 거부할 이유가 없다."""
    equipment = _state(entity_id="excavator-1", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    subject = _state(entity_id="worker-1", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    boundary = RiskFieldValidity(from_=_NOW, to=_NOW)  # type: ignore[call-arg]
    field = build_dynamic_risk_field(
        risk_field_id="rf-boundary",
        equipment_state=equipment,
        subject_state=subject,
        policy_id="policy-1",
        severity=0.8,
        horizon_s=30.0,
        combined_radius_m=2.0,
        max_observation_gap_s=_MAX_GAP_S,
        validity=boundary,
        geometry=_geometry(),
    )
    assert field.risk_field_id == "rf-boundary"
