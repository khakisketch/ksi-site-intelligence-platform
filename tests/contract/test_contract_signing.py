"""ADR-KSI-002 Ed25519 서명 검증 네거티브 테스트 (P0-1 수용기준 + 반증 리뷰 반영).

필수 네거티브 커버리지:
    (a) 정상 서명 → VALID
    (b) payload 1필드 변조 → INVALID_SIGNATURE 또는 DIGEST_MISMATCH
    (c) unknown keyId → UNKNOWN_KEY
    (d) schemaVersion 불일치 → SCHEMA_VERSION_MISMATCH
    (e) REVOKED 키의 유효 서명 → REVOKED_KEY
    (f) signature 블록만 다른 두 계약의 canonical digest 동일성
    (g) not_after 지난 키 → KEY_EXPIRED

반증 리뷰(P0/P1) 추가 커버리지:
    (h) 계약 validity 창 밖(만료·미개시) → EXPIRED_CONTRACT  [INV-011 TTL]
    (i) digest는 정확하지만 서명 위조 → INVALID_SIGNATURE     [서명 경로 실증]
    (j) 다른 키 서명 + 재계산 digest 이식 → INVALID_SIGNATURE [바인딩 실증]
    (k) algorithm 위조 → INVALID_SIGNATURE
    (l) naive not_after 등록 → ValueError (fail-early)
    (m) validity 결손/naive → MALFORMED_CONTRACT
    (n) 비직렬화 값 포함 계약 → MALFORMED_CONTRACT (예외의 verdict 강등)
    (o) Pydantic 범위 강제: accessibleGeneralCoverage < 0.95 거부 [INV-010]
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_mission_contracts.models import parse_mission_contract
from ksi_mission_contracts.signing import (
    KeyRegistry,
    KeyStatus,
    SignatureVerdict,
    canonical_payload_bytes,
    sha256_digest,
    sign_contract,
    verify_contract,
)

# 계약 validity 창(2026-07-25 ~ 07-26 UTC) 안의 고정 검증 시각 — 시계 의존 제거
IN_WINDOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


def _unsigned_contract(mission_id: str = "mission-001") -> dict[str, Any]:
    """signature 없는 최소 v1.2 계약 payload (서명 대상)."""
    return {
        "schemaVersion": "1.2",
        "missionId": mission_id,
        "siteId": "site-001",
        "missionType": "UNIFIED_SITE_SURVEY",
        "validity": {
            "notBefore": "2026-07-25T00:00:00Z",
            "notAfter": "2026-07-26T00:00:00Z",
        },
        "siteFrame": {
            "crs": "EPSG:5186",
            "verticalDatum": "KNGeoid2018",
            "unit": "meter",
            "transformVersion": "1.0.0",
        },
        "flightEnvelope": {
            "allowedVolumes": ["vol-1"],
            "excludedVolumes": [],
            "minAltitudeM": 5.0,
            "maxAltitudeM": 120.0,
        },
        "objectives": ["현장 외곽 전체 커버리지 확보"],
        "policies": {
            "viewpointPolicyId": "vp-1",
            "riskPolicyPackId": "risk-1",
            "fallbackPolicyId": "fb-1",
            "capturePolicyId": "cap-1",
            "coveragePolicy": {
                "mandatoryHazardCoverage": 1.0,
                "mandatoryAssetCoverage": 1.0,
                "accessibleGeneralCoverage": 0.97,
            },
            "communicationLossPolicy": {
                "serverLink": "CONTINUE_WHILE_CONTRACT_AND_SAFETY_VALID",
                "rcCommandLink": "DELEGATE_TO_DJI_FLIGHT_CONTROLLER",
            },
            "batteryPolicy": {
                "mode": "RETURN_ENERGY_PLUS_RESERVE",
                "defaultReservePercent": 30,
            },
            "unknownObstaclePolicy": {
                "initialAction": "SLOW",
                "unresolvedAction": "RETREAT",
            },
            "evidencePolicy": {
                "candidatePrePostSeconds": 3,
                "highPrePostSeconds": 5,
                "criticalPrePostSeconds": 10,
            },
        },
        "artifacts": {"calibrationProfileId": "cal-1"},
    }


@pytest.fixture
def signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def test_a_valid_signature_verifies(signing_key: Ed25519PrivateKey) -> None:
    registry = KeyRegistry()
    registry.register("key-001", signing_key.public_key())
    signed = sign_contract(_unsigned_contract(), signing_key, "key-001")

    result = verify_contract(signed, registry, expected_schema_version="1.2", now=IN_WINDOW)

    assert result.verdict is SignatureVerdict.VALID
    assert result.is_valid


def test_b_tampered_payload_field_rejected(signing_key: Ed25519PrivateKey) -> None:
    registry = KeyRegistry()
    registry.register("key-001", signing_key.public_key())
    signed = sign_contract(_unsigned_contract(), signing_key, "key-001")

    signed["missionId"] = "mission-TAMPERED"
    result = verify_contract(signed, registry, expected_schema_version="1.2", now=IN_WINDOW)

    assert result.verdict in (SignatureVerdict.INVALID_SIGNATURE, SignatureVerdict.DIGEST_MISMATCH)


def test_c_unknown_key_id_rejected(signing_key: Ed25519PrivateKey) -> None:
    registry = KeyRegistry()  # key-001 미등록
    signed = sign_contract(_unsigned_contract(), signing_key, "key-001")

    result = verify_contract(signed, registry, expected_schema_version="1.2", now=IN_WINDOW)

    assert result.verdict is SignatureVerdict.UNKNOWN_KEY


def test_d_schema_version_mismatch_rejected(signing_key: Ed25519PrivateKey) -> None:
    registry = KeyRegistry()
    registry.register("key-001", signing_key.public_key())
    signed = sign_contract(_unsigned_contract(), signing_key, "key-001")

    result = verify_contract(signed, registry, expected_schema_version="1.1", now=IN_WINDOW)

    assert result.verdict is SignatureVerdict.SCHEMA_VERSION_MISMATCH


def test_e_revoked_key_valid_signature_rejected(signing_key: Ed25519PrivateKey) -> None:
    registry = KeyRegistry()
    registry.register("key-001", signing_key.public_key(), status=KeyStatus.REVOKED)
    signed = sign_contract(_unsigned_contract(), signing_key, "key-001")

    result = verify_contract(signed, registry, expected_schema_version="1.2", now=IN_WINDOW)

    assert result.verdict is SignatureVerdict.REVOKED_KEY


def test_f_canonical_digest_stable_across_signature_block(signing_key: Ed25519PrivateKey) -> None:
    """signature 블록만 다른 두 계약도 서명대상 정규화 바이트열·digest는 동일해야 한다."""
    other_key = Ed25519PrivateKey.generate()
    contract_a = sign_contract(_unsigned_contract(), signing_key, "key-001")
    contract_b = sign_contract(_unsigned_contract(), other_key, "key-002")

    assert contract_a["signature"] != contract_b["signature"]
    assert canonical_payload_bytes(contract_a) == canonical_payload_bytes(contract_b)
    assert sha256_digest(canonical_payload_bytes(contract_a)) == sha256_digest(
        canonical_payload_bytes(contract_b)
    )


def test_g_expired_key_rejected(signing_key: Ed25519PrivateKey) -> None:
    """키 만료는 계약 만료와 구분되는 KEY_EXPIRED다 (반증 리뷰 verdict 분리)."""
    registry = KeyRegistry()
    registry.register(
        "key-001", signing_key.public_key(), not_after=IN_WINDOW - timedelta(days=1)
    )
    signed = sign_contract(_unsigned_contract(), signing_key, "key-001")

    result = verify_contract(signed, registry, expected_schema_version="1.2", now=IN_WINDOW)

    assert result.verdict is SignatureVerdict.KEY_EXPIRED


def test_missing_signature_block_rejected() -> None:
    registry = KeyRegistry()
    contract = _unsigned_contract()

    result = verify_contract(contract, registry, expected_schema_version="1.2", now=IN_WINDOW)

    assert result.verdict is SignatureVerdict.INVALID_SIGNATURE


# ── 반증 리뷰(P0/P1/P2) 추가 네거티브 ──────────────────────────────────────────


def test_h_contract_outside_validity_window_rejected(signing_key: Ed25519PrivateKey) -> None:
    """[P0] 유효 서명이라도 계약 validity 창 밖이면 EXPIRED_CONTRACT (INV-011 TTL)."""
    registry = KeyRegistry()
    registry.register("key-001", signing_key.public_key())
    signed = sign_contract(_unsigned_contract(), signing_key, "key-001")

    expired = verify_contract(
        signed, registry, expected_schema_version="1.2",
        now=datetime(2026, 7, 27, 0, 0, tzinfo=UTC),  # notAfter 이후
    )
    not_yet = verify_contract(
        signed, registry, expected_schema_version="1.2",
        now=datetime(2026, 7, 24, 0, 0, tzinfo=UTC),  # notBefore 이전
    )

    assert expired.verdict is SignatureVerdict.EXPIRED_CONTRACT
    assert not_yet.verdict is SignatureVerdict.EXPIRED_CONTRACT


def test_i_forged_signature_with_correct_digest_rejected(
    signing_key: Ed25519PrivateKey,
) -> None:
    """[P1] digest 검사를 통과시키고 서명 검증 경로를 강제로 태운다 — tautology 제거."""
    registry = KeyRegistry()
    registry.register("key-001", signing_key.public_key())
    signed = sign_contract(_unsigned_contract(), signing_key, "key-001")

    forged = dict(signed)
    forged["signature"] = {
        **signed["signature"],
        "signature": base64.b64encode(b"\x00" * 64).decode("ascii"),  # digest는 그대로(정확)
    }
    result = verify_contract(forged, registry, expected_schema_version="1.2", now=IN_WINDOW)

    assert result.verdict is SignatureVerdict.INVALID_SIGNATURE


def test_j_transplanted_signature_from_other_key_rejected(
    signing_key: Ed25519PrivateKey,
) -> None:
    """[P1] 다른 키로 만든 서명 + 재계산된 정확한 digest 이식 → 서명이 바이트열·키에 바인딩."""
    registry = KeyRegistry()
    registry.register("key-001", signing_key.public_key())

    attacker_key = Ed25519PrivateKey.generate()
    victim = _unsigned_contract()
    attacker_signed = sign_contract(victim, attacker_key, "key-001")  # keyId 사칭
    # digest는 payload에서 재계산돼 정확하다 — 서명만 다른 키 산출물
    result = verify_contract(
        attacker_signed, registry, expected_schema_version="1.2", now=IN_WINDOW
    )

    assert result.verdict is SignatureVerdict.INVALID_SIGNATURE


def test_k_wrong_algorithm_rejected(signing_key: Ed25519PrivateKey) -> None:
    """[P2] algorithm 필드 위조 → 알고리즘 혼동 방어."""
    registry = KeyRegistry()
    registry.register("key-001", signing_key.public_key())
    signed = sign_contract(_unsigned_contract(), signing_key, "key-001")
    signed["signature"] = {**signed["signature"], "algorithm": "none"}

    result = verify_contract(signed, registry, expected_schema_version="1.2", now=IN_WINDOW)

    assert result.verdict is SignatureVerdict.INVALID_SIGNATURE


def test_l_naive_not_after_registration_rejected(signing_key: Ed25519PrivateKey) -> None:
    """[P1] naive not_after는 등록 시점에 거부 — 검증 시 TypeError fail-open 차단."""
    registry = KeyRegistry()
    with pytest.raises(ValueError, match="tz-aware"):
        registry.register(
            "key-001", signing_key.public_key(), not_after=datetime(2027, 1, 1)  # noqa: DTZ001
        )


def test_m_malformed_validity_rejected(signing_key: Ed25519PrivateKey) -> None:
    """[P1] validity 결손·naive 타임스탬프 → MALFORMED_CONTRACT (fail-closed)."""
    registry = KeyRegistry()
    registry.register("key-001", signing_key.public_key())

    no_validity = _unsigned_contract()
    del no_validity["validity"]
    signed_no_validity = sign_contract(no_validity, signing_key, "key-001")

    naive_validity = _unsigned_contract()
    naive_validity["validity"] = {
        "notBefore": "2026-07-25T00:00:00",  # 오프셋 없음(naive)
        "notAfter": "2026-07-26T00:00:00",
    }
    signed_naive = sign_contract(naive_validity, signing_key, "key-001")

    r1 = verify_contract(signed_no_validity, registry, expected_schema_version="1.2", now=IN_WINDOW)
    r2 = verify_contract(signed_naive, registry, expected_schema_version="1.2", now=IN_WINDOW)

    assert r1.verdict is SignatureVerdict.MALFORMED_CONTRACT
    assert r2.verdict is SignatureVerdict.MALFORMED_CONTRACT


def test_n_unserializable_contract_degrades_to_verdict(
    signing_key: Ed25519PrivateKey,
) -> None:
    """[P1] 비직렬화 값이 있어도 예외가 아니라 MALFORMED_CONTRACT verdict (fail-closed 강등)."""
    registry = KeyRegistry()
    registry.register("key-001", signing_key.public_key())
    signed = sign_contract(_unsigned_contract(), signing_key, "key-001")
    signed["artifacts"] = {"calibrationProfileId": datetime(2026, 1, 1, tzinfo=UTC)}

    result = verify_contract(signed, registry, expected_schema_version="1.2", now=IN_WINDOW)

    assert result.verdict is SignatureVerdict.MALFORMED_CONTRACT


def test_o_pydantic_enforces_coverage_lower_bound() -> None:
    """[P2] INV-010 — accessibleGeneralCoverage < 0.95는 모델 검증에서 거부."""
    contract = _unsigned_contract()
    contract["policies"]["coveragePolicy"]["accessibleGeneralCoverage"] = 0.5
    contract["signature"] = {
        "algorithm": "Ed25519",
        "keyId": "key-001",
        "digest": "sha256:00",
        "signature": "AA==",
    }
    with pytest.raises(ValueError):
        parse_mission_contract(contract)

    contract["policies"]["coveragePolicy"]["accessibleGeneralCoverage"] = 0.97
    parsed = parse_mission_contract(contract)
    assert parsed.policies.coverage_policy.accessible_general_coverage == 0.97
