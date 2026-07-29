"""Mission Contract 발급 계약 (ADR-KSI-007) — 서명·구조·안전상수 고정을 검증한다.

발급된 계약이 ① MissionContractV1_2 구조를 만족하고 ② Ed25519 서명이
load_verified_contract로 VALID 검증되며 ③ 안전 관련 정책 상수(coverage/battery/
evidence/unknownObstacle)가 요청 값과 무관하게 FINAL_DECISION_LEDGER 값으로
고정되는지가 초점이다 — 발급 API가 안전 하한을 낮추는 우회로가 되지 않는지 반증.
"""

from __future__ import annotations

from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_mission_contracts.signing import KeyRegistry, SignatureVerdict, load_verified_contract

_SITE_FRAME = {
    "crs": "EPSG:5186",
    "verticalDatum": "KNGeoid2018",
    "unit": "meter",
    "transformVersion": "1.0.0",
}
_FLIGHT_ENVELOPE = {
    "allowedVolumes": ["vol-1"],
    "excludedVolumes": [],
    "minAltitudeM": 5.0,
    "maxAltitudeM": 120.0,
}


def _valid_request(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "missionId": "mission-001",
        "siteId": "site-001",
        "missionType": "AUTONOMOUS_PATROL",
        "siteFrame": _SITE_FRAME,
        "flightEnvelope": _FLIGHT_ENVELOPE,
        "objectives": ["현장 외곽 순찰"],
        "viewpointPolicyId": "vp-1",
        "riskPolicyPackId": "risk-1",
        "fallbackPolicyId": "fb-1",
        "capturePolicyId": "cap-1",
    }
    base.update(overrides)
    return base


def _client_with_signing() -> tuple[TestClient, KeyRegistry, str]:
    key_id = "core-issuer-key-1"
    private_key = Ed25519PrivateKey.generate()
    registry = KeyRegistry()
    registry.register(key_id, private_key.public_key())
    app = create_app(mission_signing_key=private_key, mission_signing_key_id=key_id)
    return TestClient(app), registry, key_id


def test_missing_signing_key_means_no_endpoint() -> None:
    """서명키 미주입 시 발급 엔드포인트가 존재하지 않는다(edge_sync_store와 동일 패턴)."""
    app = create_app()
    client = TestClient(app)
    response = client.post("/v1/missions/contracts", json=_valid_request())
    assert response.status_code == 404


def test_half_signing_config_rejected() -> None:
    """서명키·keyId 중 하나만 주어지면 조립 자체를 거부한다."""
    private_key = Ed25519PrivateKey.generate()
    try:
        create_app(mission_signing_key=private_key)
    except ValueError:
        pass
    else:
        raise AssertionError("절반만 있는 서명 설정이 조용히 통과했다")


def test_issued_contract_is_signature_valid() -> None:
    client, registry, _key_id = _client_with_signing()

    response = client.post("/v1/missions/contracts", json=_valid_request())

    assert response.status_code == 201
    contract = response.json()
    result = load_verified_contract(contract, registry, now=datetime.now(UTC))
    assert result.verdict is SignatureVerdict.VALID, result.detail


def test_safety_policies_are_server_fixed_not_client_supplied() -> None:
    """요청 바디에 안전 상수를 넣을 자리가 아예 없다 — extra=forbid로 거부된다."""
    client, _registry, _key_id = _client_with_signing()
    request = _valid_request()
    request["batteryPolicy"] = {
        "mode": "RETURN_ENERGY_PLUS_RESERVE",
        "defaultReservePercent": 0,
    }

    response = client.post("/v1/missions/contracts", json=request)

    assert response.status_code == 422


def test_issued_contract_carries_ledger_default_policies() -> None:
    client, _registry, _key_id = _client_with_signing()

    response = client.post("/v1/missions/contracts", json=_valid_request())

    policies = response.json()["policies"]
    assert policies["batteryPolicy"]["defaultReservePercent"] == 30
    assert policies["evidencePolicy"] == {
        "candidatePrePostSeconds": 3,
        "highPrePostSeconds": 5,
        "criticalPrePostSeconds": 10,
    }
    assert policies["coveragePolicy"]["mandatoryHazardCoverage"] == 1.0
    assert policies["coveragePolicy"]["mandatoryAssetCoverage"] == 1.0


def test_valid_for_hours_beyond_cap_rejected() -> None:
    client, _registry, _key_id = _client_with_signing()

    response = client.post(
        "/v1/missions/contracts", json=_valid_request(validForHours=169.0)
    )

    assert response.status_code == 422
