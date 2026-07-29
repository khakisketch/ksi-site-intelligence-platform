"""Capability Registry 노출 게이트 + 2-enum 분리 검증 (P0-5 수용기준, INV-041).

green≠작동 방지 핵심: "모델이 생성됨"이 아니라 "노출 규칙이 실제로 막는다"를 검증한다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
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
from ksi_domain.spike_evidence import IncompleteSpikeEvidenceError, SpikeEvidence


def _spike_evidence(operator: str = "hil-operator") -> SpikeEvidence:
    """VERIFIED 승격용 유효 증거 레코드 — 11개 필드 전부 채운다.

    실제 실기 세션에서는 이 값들이 측정·기록된 실물로 대체된다.
    """
    return SpikeEvidence(
        aircraft_firmware="M4D v08.02.0100",
        rc_firmware="RC Plus 2 v03.01.0200",
        manifold_image="Manifold3 JetPack 6.0 image 2026-07",
        psdk_version="PSDK 3.9.0",
        build_commit="6da9d16",
        test_procedure="카메라 스트림 개방 → 30초 프레임 수신 → 프레임 수·간격 기록",
        raw_log_ref="s3://ksi-hil-logs/2026-07-27/spike-dji-01.log",
        latency_result="frame interval p95 = 42ms (n=900)",
        failure_result="관측된 실패 없음 — 30초 구간에서 드롭 프레임 0, 재연결 0회",
        operator=operator,
        observed_at=datetime(2026, 7, 27, 5, 0, 0, tzinfo=UTC),
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
        spike_evidence=_spike_evidence(),
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
        capability_id,
        CapabilityVerificationState.VERIFIED,
        evidence="최초 HIL 통과",
        spike_evidence=_spike_evidence(),
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
        capability_id,
        CapabilityVerificationState.VERIFIED,
        evidence="최초 HIL 통과",
        spike_evidence=_spike_evidence(),
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


# ── Track A: 구조화 Spike 증거 게이트 ─────────────────────────────────────────


def test_verified_without_structured_spike_evidence_rejected() -> None:
    """[Track A] 문자열 evidence만으로는 VERIFIED 승격 불가.

    "테스트했음" 같은 문자열이 실기 검증으로 통과하면 증거 게이트가 형식적으로만
    존재하는 상태다 — 11개 필드를 구조로 요구한다.
    """
    registry = CapabilityRegistry()
    seed_prd_spikes(registry)
    capability_id = registry.list_all()[0].capability_id

    with pytest.raises(IllegalCapabilityTransitionError, match="SpikeEvidence"):
        registry.transition(
            capability_id,
            CapabilityVerificationState.VERIFIED,
            evidence="테스트했음",  # 문자열만 — 구조화 증거 없음
        )

    assert registry.list_operational() == [], "승격이 거부됐으므로 노출도 없어야 한다"


def test_blocked_still_accepts_string_reason_only() -> None:
    """차단은 보수적 방향이므로 구조화 증거를 요구하지 않는다(과잉 요구 방지)."""
    registry = CapabilityRegistry()
    seed_prd_spikes(registry)
    capability_id = registry.list_all()[0].capability_id

    record = registry.transition(
        capability_id,
        CapabilityVerificationState.BLOCKED,
        evidence="DJI 공식 문서상 제3자 Payload 미지원",
    )
    assert record.state is CapabilityVerificationState.BLOCKED
    assert record.spike_evidence is None


def test_verified_record_retains_structured_evidence() -> None:
    registry = CapabilityRegistry()
    seed_prd_spikes(registry)
    capability_id = registry.list_all()[0].capability_id

    record = registry.transition(
        capability_id,
        CapabilityVerificationState.VERIFIED,
        evidence="HIL 통과",
        spike_evidence=_spike_evidence(operator="김현장"),
    )

    assert record.spike_evidence is not None
    assert record.spike_evidence.operator == "김현장"
    assert "M4D" in record.spike_evidence.aircraft_firmware
    assert record.spike_evidence.summary().startswith("spike@")


def test_regression_to_blocked_clears_stale_evidence() -> None:
    """회귀 후 낡은 증거가 남아 다음 승격을 정당화하는 것처럼 보이면 안 된다."""
    registry = CapabilityRegistry()
    seed_prd_spikes(registry)
    capability_id = registry.list_all()[0].capability_id
    registry.transition(
        capability_id,
        CapabilityVerificationState.VERIFIED,
        evidence="최초 통과",
        spike_evidence=_spike_evidence(),
    )

    blocked = registry.transition(
        capability_id, CapabilityVerificationState.BLOCKED, evidence="회귀 발견"
    )

    assert blocked.spike_evidence is None, "BLOCKED 로 내려가면 증거도 함께 지워야 한다"


@pytest.mark.parametrize(
    "blank_field",
    [
        "aircraft_firmware",
        "rc_firmware",
        "manifold_image",
        "psdk_version",
        "build_commit",
        "test_procedure",
        "raw_log_ref",
        "latency_result",
        "failure_result",
        "operator",
    ],
)
def test_incomplete_spike_evidence_rejected(blank_field: str) -> None:
    """11개 필드 중 하나라도 비면 증거 레코드 자체를 만들 수 없다."""
    kwargs: dict[str, object] = {
        "aircraft_firmware": "M4D v08.02.0100",
        "rc_firmware": "RC Plus 2 v03.01.0200",
        "manifold_image": "Manifold3 JetPack 6.0",
        "psdk_version": "PSDK 3.9.0",
        "build_commit": "abc1234",
        "test_procedure": "절차",
        "raw_log_ref": "s3://log",
        "latency_result": "p95 42ms",
        "failure_result": "관측된 실패 없음",
        "operator": "operator",
        "observed_at": datetime(2026, 7, 27, 5, 0, 0, tzinfo=UTC),
    }
    kwargs[blank_field] = "   "  # whitespace-only
    with pytest.raises(IncompleteSpikeEvidenceError, match=blank_field):
        SpikeEvidence(**kwargs)  # type: ignore[arg-type]


def test_failure_result_cannot_be_blank() -> None:
    """실패 칸이 빈 증거는 '실패를 안 봤다'와 '찾지 않았다'를 구분할 수 없다."""
    with pytest.raises(IncompleteSpikeEvidenceError, match="failure_result"):
        SpikeEvidence(
            aircraft_firmware="M4D",
            rc_firmware="RC",
            manifold_image="img",
            psdk_version="3.9",
            build_commit="abc",
            test_procedure="절차",
            raw_log_ref="s3://log",
            latency_result="p95 42ms",
            failure_result="",
            operator="op",
            observed_at=datetime(2026, 7, 27, 5, 0, 0, tzinfo=UTC),
        )


def test_spike_evidence_requires_utc_timestamp() -> None:
    with pytest.raises(IncompleteSpikeEvidenceError, match="UTC"):
        SpikeEvidence(
            aircraft_firmware="M4D",
            rc_firmware="RC",
            manifold_image="img",
            psdk_version="3.9",
            build_commit="abc",
            test_procedure="절차",
            raw_log_ref="s3://log",
            latency_result="p95 42ms",
            failure_result="없음",
            operator="op",
            observed_at=datetime(2026, 7, 27, 14, 0, 0, tzinfo=timezone(timedelta(hours=9))),
        )


def test_demotion_clears_stale_verification_context() -> None:
    """[감사 #11] VERIFIED 이탈 시 firmware/sdk/aircraft 가 이월되지 않는다.

    이월되면 재승격 전 기간에 /capabilities·감사 경로가 "어느 펌웨어에서 검증
    됐는가"를 회귀로 차단됐던 낡은 값으로 공표한다 — INV-041 의 취지(검증 맥락의
    정직성) 잠식.
    """
    registry = CapabilityRegistry()
    registry.register("SPIKE-X", "테스트 capability")
    registry.transition(
        "SPIKE-X",
        CapabilityVerificationState.VERIFIED,
        evidence="hil-run-1",
        firmware="fw-1.0",
        sdk="psdk-3.9",
        aircraft="Matrice 4D",
        spike_evidence=_spike_evidence(),
    )
    record = registry.get("SPIKE-X")
    assert record is not None and record.firmware == "fw-1.0"

    registry.transition(
        "SPIKE-X", CapabilityVerificationState.BLOCKED, evidence="regression-found"
    )
    demoted = registry.get("SPIKE-X")
    assert demoted is not None
    assert demoted.firmware is None and demoted.sdk is None and demoted.aircraft is None, (
        "이탈 후에도 낡은 검증 맥락이 남았다"
    )
    assert demoted.verified_at is None and demoted.spike_evidence is None
