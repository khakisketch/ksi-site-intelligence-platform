"""Capability Registry 노출 게이트 + 2-enum 분리 검증 (P0-5 수용기준, INV-041).

green≠작동 방지 핵심: "모델이 생성됨"이 아니라 "노출 규칙이 실제로 막는다"를 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from ksi_core.capability.registry import CapabilityRegistry, seed_prd_spikes
from ksi_domain.capability import (
    CapabilityVerificationState,
    EquipmentSupportLevel,
    IllegalCapabilityTransitionError,
    IllegalSupportLevelTransitionError,
    assert_capability_transition,
    assert_support_level_transition,
    is_production_supported,
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "schemas"
    / "equipment-support-state.v1.json"
)


def test_register_verified_directly_rejected() -> None:
    """[반증 리뷰 P0] evidence 없이 state=VERIFIED로 초기 등록 → 노출 게이트 우회 차단."""
    registry = CapabilityRegistry()

    with pytest.raises(IllegalCapabilityTransitionError, match="초기 등록"):
        registry.register(
            "CAP-X", "Unverified capability",
            state=CapabilityVerificationState.VERIFIED,
            evidence=None,
        )

    assert registry.list_all() == []
    assert registry.list_operational() == []


def test_register_blocked_without_evidence_rejected() -> None:
    registry = CapabilityRegistry()
    with pytest.raises(IllegalCapabilityTransitionError, match="evidence"):
        registry.register(
            "CAP-Y", "Blocked without reason", state=CapabilityVerificationState.BLOCKED
        )


def test_register_blocked_with_evidence_allowed() -> None:
    registry = CapabilityRegistry()
    registry.register(
        "CAP-Y", "Known unsupported combo",
        state=CapabilityVerificationState.BLOCKED,
        evidence="DJI 공식 문서상 미지원 확인",
    )
    assert registry.get("CAP-Y") is not None
    assert registry.list_operational() == []


def test_register_duplicate_capability_id_rejected() -> None:
    registry = CapabilityRegistry()
    registry.register("CAP-Z", "First registration")

    with pytest.raises(ValueError, match="중복"):
        registry.register("CAP-Z", "Silent overwrite attempt")


def test_prd_spike_seed_all_hidden_from_operational() -> None:
    """PRD §20.3 9개 항목 시드 직후 — list_all()==9, list_operational()==0 (전부 미노출)."""
    registry = CapabilityRegistry()
    seed_prd_spikes(registry)

    assert len(registry.list_all()) == 9
    assert registry.list_operational() == []
    assert all(
        r.state is CapabilityVerificationState.SPIKE_REQUIRED for r in registry.list_all()
    )


def test_transition_to_verified_without_evidence_rejected() -> None:
    registry = CapabilityRegistry()
    seed_prd_spikes(registry)
    capability_id = registry.list_all()[0].capability_id

    with pytest.raises(IllegalCapabilityTransitionError, match="evidence"):
        registry.transition(capability_id, CapabilityVerificationState.VERIFIED, evidence="")

    with pytest.raises(IllegalCapabilityTransitionError, match="evidence"):
        registry.transition(
            capability_id, CapabilityVerificationState.VERIFIED, evidence="   "
        )


def test_transition_to_verified_with_evidence_appears_in_operational() -> None:
    registry = CapabilityRegistry()
    seed_prd_spikes(registry)
    capability_id = registry.list_all()[0].capability_id

    registry.transition(
        capability_id,
        CapabilityVerificationState.VERIFIED,
        evidence="HIL 2026-07-25 M4D+Manifold3 실기 검증 로그 #1234",
        firmware="v08.02.0100",
        sdk="PSDK 3.9",
        aircraft="Matrice 4D",
    )

    operational = registry.list_operational()
    assert len(operational) == 1
    assert operational[0].capability_id == capability_id
    assert operational[0].verified_at is not None
    # 나머지 8개는 여전히 노출되지 않는다.
    assert len(registry.list_all()) == 9


def test_blocked_never_appears_in_any_exposure_query() -> None:
    """BLOCKED는 list_operational() 뿐 아니라 어떤 노출 조회에도 나타나지 않아야 한다."""
    registry = CapabilityRegistry()
    seed_prd_spikes(registry)
    capability_id = registry.list_all()[0].capability_id

    registry.transition(
        capability_id,
        CapabilityVerificationState.BLOCKED,
        evidence="DJI Cloud API 제3자 Payload 미지원 확인",
    )

    assert registry.list_operational() == []
    blocked = registry.get(capability_id)
    assert blocked is not None
    assert blocked.state is CapabilityVerificationState.BLOCKED
    # list_all()에는 감사 목적으로 나타나지만(운영 노출 아님), operational에는 절대 없다.
    assert any(r.state is CapabilityVerificationState.BLOCKED for r in registry.list_all())


def test_verified_can_regress_to_blocked_with_evidence() -> None:
    registry = CapabilityRegistry()
    seed_prd_spikes(registry)
    capability_id = registry.list_all()[0].capability_id
    registry.transition(
        capability_id, CapabilityVerificationState.VERIFIED, evidence="최초 HIL 통과"
    )
    assert len(registry.list_operational()) == 1

    registry.transition(
        capability_id, CapabilityVerificationState.BLOCKED, evidence="후속 펌웨어에서 회귀 발견"
    )
    assert registry.list_operational() == []


def test_illegal_transition_verified_direct_to_spike_required_rejected() -> None:
    """VERIFIED→SPIKE_REQUIRED는 전이표에 없다 (BLOCKED를 거쳐야 함)."""
    registry = CapabilityRegistry()
    seed_prd_spikes(registry)
    capability_id = registry.list_all()[0].capability_id
    registry.transition(
        capability_id, CapabilityVerificationState.VERIFIED, evidence="최초 HIL 통과"
    )

    with pytest.raises(IllegalCapabilityTransitionError, match="허용되지 않은"):
        registry.transition(
            capability_id, CapabilityVerificationState.SPIKE_REQUIRED, evidence="재검토 필요"
        )


def test_domain_level_transition_function_matches_registry_behavior() -> None:
    """packages/domain의 순수 함수 자체도 동일 규칙을 강제한다(레지스트리 없이도)."""
    assert_capability_transition(
        CapabilityVerificationState.SPIKE_REQUIRED,
        CapabilityVerificationState.VERIFIED,
        evidence="증거 있음",
    )
    with pytest.raises(IllegalCapabilityTransitionError):
        assert_capability_transition(
            CapabilityVerificationState.SPIKE_REQUIRED,
            CapabilityVerificationState.VERIFIED,
            evidence=None,
        )
    with pytest.raises(IllegalCapabilityTransitionError):
        assert_capability_transition(
            CapabilityVerificationState.BLOCKED,
            CapabilityVerificationState.VERIFIED,  # BLOCKED는 SPIKE_REQUIRED로만 복귀 가능
            evidence="증거 있음",
        )


# ── EquipmentSupportLevel — 순차 승급만, 스킵 금지 ────────────────────────────────


def test_support_level_skip_promotion_rejected() -> None:
    with pytest.raises(IllegalSupportLevelTransitionError, match="스킵"):
        assert_support_level_transition(
            EquipmentSupportLevel.DATASET_AVAILABLE,
            EquipmentSupportLevel.FIELD_VALIDATED,  # BASELINE_DETECTION을 건너뜀
            evidence="현장 검증 완료",
        )


def test_support_level_sequential_promotion_with_evidence_allowed() -> None:
    assert_support_level_transition(
        EquipmentSupportLevel.DATASET_AVAILABLE,
        EquipmentSupportLevel.BASELINE_DETECTION,
        evidence="공개데이터셋 기반 baseline detector 학습 완료",
    )  # 예외 없이 통과해야 한다


def test_support_level_promotion_without_evidence_rejected() -> None:
    """[반증 리뷰 #5] 예외 타입은 IllegalSupportLevelTransitionError여야 한다(복붙 오류 수정)."""
    with pytest.raises(IllegalSupportLevelTransitionError, match="evidence"):
        assert_support_level_transition(
            EquipmentSupportLevel.DATASET_AVAILABLE,
            EquipmentSupportLevel.BASELINE_DETECTION,
            evidence=None,
        )


def test_support_level_demotion_always_allowed_without_evidence() -> None:
    assert_support_level_transition(
        EquipmentSupportLevel.PRODUCTION_SUPPORTED,
        EquipmentSupportLevel.RISK_VALIDATED,
        evidence=None,
    )  # 강등은 evidence 없이도 통과해야 한다


def test_only_production_supported_reports_true() -> None:
    for level in EquipmentSupportLevel:
        expected = level is EquipmentSupportLevel.PRODUCTION_SUPPORTED
        assert is_production_supported(level) is expected


def test_equipment_support_state_schema_accepts_all_levels() -> None:
    """equipment-support-state.v1.json ``state`` enum ↔ EquipmentSupportLevel 값 정합."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_values = set(schema["properties"]["state"]["enum"])
    enum_values = {level.value for level in EquipmentSupportLevel}
    assert schema_values == enum_values

    validator = jsonschema.Draft202012Validator(schema)
    for level in EquipmentSupportLevel:
        instance = {"classId": "tower-crane", "state": level.value}
        validator.validate(instance)


def test_two_enums_are_not_interchangeable_at_type_level() -> None:
    """두 enum이 값 공간을 공유하지 않음을 런타임으로도 확인 — 교차 대입은 거부되어야 한다."""
    verification_values = {s.value for s in CapabilityVerificationState}
    support_values = {s.value for s in EquipmentSupportLevel}
    assert verification_values.isdisjoint(support_values), (
        "CapabilityVerificationState와 EquipmentSupportLevel의 값 공간이 겹친다 — "
        "두 축이 혼용될 위험이 있다(반영사항 9 위반)"
    )
