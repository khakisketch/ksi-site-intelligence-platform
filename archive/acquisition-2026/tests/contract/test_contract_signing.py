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
import json
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


# ── 키 수명주기·정규화·합성 진입점 (감사 #9·#10·#12·#50 폐쇄) ────────────────


def test_duplicate_key_registration_rejected_no_revoked_resurrection() -> None:
    """[#9] 같은 keyId 재등록은 거부 — REVOKED 가 ACTIVE 로 부활하는 경로 차단."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    registry = KeyRegistry()
    registry.register("key-001", key.public_key())
    registry.revoke("key-001")
    with pytest.raises(ValueError, match="이미 등록"):
        registry.register("key-001", key.public_key())  # 부활 시도
    record = registry.get("key-001")
    assert record is not None and record.status.value == "REVOKED", "폐기 상태가 되돌려졌다"

    signed = sign_contract(_unsigned_contract(), key, "key-001")
    result = verify_contract(signed, registry, "1.2")
    assert result.verdict.value == "REVOKED_KEY", "폐기 키 서명이 여전히 유효 판정된다"


def test_revoke_unknown_key_rejected_and_revoke_is_idempotent() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    registry = KeyRegistry()
    with pytest.raises(ValueError, match="unknown keyId"):
        registry.revoke("no-such-key")
    registry.register("key-001", Ed25519PrivateKey.generate().public_key())
    registry.revoke("key-001")
    registry.revoke("key-001")  # 멱등 — 단조 방향 재적용은 무해
    record = registry.get("key-001")
    assert record is not None and record.status.value == "REVOKED"


def test_nan_in_contract_is_typed_failure_on_sign_and_malformed_on_verify() -> None:
    """[#10] NaN 계약은 발행 시 typed ValueError, 검증 시 MALFORMED_CONTRACT.

    allow_nan 기본값이면 Python 안에서는 서명·검증이 전부 통과하지만 그 바이트열은
    표준 JSON 파서(C++ 평면)로 재파싱 불가 — 정규화 규약 분열이었다.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    contract = _unsigned_contract()
    contract["objectives"] = [float("nan")]
    key = Ed25519PrivateKey.generate()
    with pytest.raises(ValueError, match="정규 JSON"):
        sign_contract(contract, key, "key-001")

    registry = KeyRegistry()
    registry.register("key-001", key.public_key())
    contract["signature"] = {
        "algorithm": "Ed25519", "keyId": "key-001",
        "digest": "sha256:" + "0" * 64, "signature": "AA==",
    }
    from datetime import datetime

    # validity 창 안의 now 로 고정 — 창 검사(EXPIRED)가 아니라 canonical 정규화
    # 단계까지 도달해야 이 반증이 성립한다(검증 순서: validity → digest).
    in_window = datetime.fromisoformat(
        contract["validity"]["notBefore"].replace("Z", "+00:00")
    )
    result = verify_contract(contract, registry, "1.2", now=in_window)
    assert result.verdict.value == "MALFORMED_CONTRACT", "NaN 계약이 예외/통과로 샜다"


def test_load_verified_contract_is_single_entrypoint() -> None:
    """[#12] 유효 서명 + 부적합 구조 = 거부 — verify_contract 단독 오용의 사각지대."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ksi_mission_contracts.signing import load_verified_contract

    key = Ed25519PrivateKey.generate()
    registry = KeyRegistry()
    registry.register("key-001", key.public_key())

    # 정상: 구조+서명 모두 유효
    signed = sign_contract(_unsigned_contract(), key, "key-001")
    loaded = load_verified_contract(signed, registry, now=IN_WINDOW)
    assert loaded.is_valid and loaded.model is not None
    assert loaded.model.mission_id == signed["missionId"]

    # 구조 위반(coverage 하한 붕괴)이지만 서명은 유효한 계약 — verify_contract 만
    # 호출하면 VALID 가 되던 바로 그 입력이 진입점에서는 거부된다.
    broken = _unsigned_contract()
    broken["policies"]["coveragePolicy"]["accessibleGeneralCoverage"] = 0.1  # < 0.95
    broken_signed = sign_contract(broken, key, "key-001")
    assert verify_contract(broken_signed, registry, "1.2", now=IN_WINDOW).is_valid, (
        "전제 확인: 서명 자체는 유효해야 이 반증이 성립한다"
    )
    loaded_broken = load_verified_contract(broken_signed, registry, now=IN_WINDOW)
    assert not loaded_broken.is_valid
    assert loaded_broken.verdict.value == "MALFORMED_CONTRACT"

    # 서명 위조는 여전히 서명 계층에서 거부
    tampered = dict(signed)
    tampered["missionId"] = "tampered"
    loaded_tampered = load_verified_contract(tampered, registry, now=IN_WINDOW)
    assert not loaded_tampered.is_valid
    assert loaded_tampered.verdict.value == "DIGEST_MISMATCH"


def test_flight_envelope_cross_field_validation() -> None:
    """[#50] min>max·음수 standoff 봉투는 계약 모델이 거부한다."""
    from ksi_mission_contracts.models import MissionContractV1_2

    base = _unsigned_contract()
    base["signature"] = {
        "algorithm": "Ed25519", "keyId": "k", "digest": "d", "signature": "s",
    }
    inverted = json.loads(json.dumps(base))
    inverted["flightEnvelope"]["minAltitudeM"] = 120.0
    inverted["flightEnvelope"]["maxAltitudeM"] = 30.0
    with pytest.raises(Exception, match="역전된 고도"):
        MissionContractV1_2.model_validate(inverted)

    negative = json.loads(json.dumps(base))
    negative["flightEnvelope"]["minimumPersonStandoffM"] = -5.0
    with pytest.raises(Exception, match="비음수"):
        MissionContractV1_2.model_validate(negative)
