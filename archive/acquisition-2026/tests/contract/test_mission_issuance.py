"""Mission Contract 발급 계약 (ADR-KSI-007) — 서명·구조·안전상수 고정을 검증한다.

발급된 계약이 ① MissionContractV1_2 구조를 만족하고 ② Ed25519 서명이
load_verified_contract로 VALID 검증되며 ③ 안전 관련 정책 상수(coverage/battery/
evidence/unknownObstacle)가 요청 값과 무관하게 FINAL_DECISION_LEDGER 값으로
고정되는지가 초점이다 — 발급 API가 안전 하한을 낮추는 우회로가 되지 않는지 반증.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from _site_lifecycle import advance_site_status
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionIssuanceSequenceStore, MissionStore
from ksi_core.sites import SiteStore
from ksi_domain.enums import SiteStatus
from ksi_mission_contracts.models import (
    _ABSOLUTE_MAX_ALTITUDE_M,
    FlightEnvelope,
    SiteFrame,
)
from ksi_mission_contracts.signing import KeyRegistry, SignatureVerdict, load_verified_contract
from pydantic import ValidationError

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


_ISSUER_TOKEN = "mission-issuer-token"  # noqa: S105 — 테스트 고정 토큰


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_ISSUER_TOKEN),
                principal=Principal(
                    principal_id="do-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            )
        ]
    )


def _client_with_signing(
    tmp_path: Path, *, writer_version: Literal["1.2", "1.3"] = "1.2"
) -> tuple[TestClient, KeyRegistry, str]:
    """서명키 + mission_store + site_store + auth_registry 최소 조립(ADR-KSI-008 §3).

    요청 site_id("site-001")는 발급 전 site_store 에 직접 등록한다 — precheck_issuance
    의 site_exists 게이트가 이제 이 저장소로 배선되기 때문(HTTP 왕복 없이 register()로
    직접 시드, API 자체는 test_sites_api.py 소관). 이 파일의 모든 테스트가
    ``_valid_request()`` 기본값(``missionType: AUTONOMOUS_PATROL``)을 그대로
    쓰므로, site 를 ``PATROL_READY`` 까지 전진시킨다(INV-052 임무타입×현장상태
    게이트, ADR-KSI-014) — 이 파일의 초점은 서명·정책 고정이지 게이트 자체가
    아니므로, 게이트 반증은 `test_mission_site_status_gate.py` 가 별도로 맡는다.
    """
    key_id = "core-issuer-key-1"
    private_key = Ed25519PrivateKey.generate()
    registry = KeyRegistry()
    registry.register(key_id, private_key.public_key())

    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    site_store.register(
        "site-001",
        "Site 001",
        SiteFrame.model_validate(_SITE_FRAME),
        actor="test-harness",
        now=datetime.now(UTC),
    )
    advance_site_status(site_store, "site-001", SiteStatus.PATROL_READY)
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    sequence_store = MissionIssuanceSequenceStore(
        DurableJournal(tmp_path / "mission-sequences.jsonl")
    )

    app = create_app(
        mission_signing_key=private_key,
        mission_signing_key_id=key_id,
        mission_store=mission_store,
        site_store=site_store,
        auth_registry=_auth_registry(),
        mission_contract_writer_version=writer_version,
        mission_contract_issuer_id="core-seoul-1" if writer_version == "1.3" else None,
        mission_sequence_store=sequence_store,
    )
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_ISSUER_TOKEN}"})
    return client, registry, key_id


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


def test_signing_key_without_mission_and_site_store_rejected() -> None:
    """[ADR-KSI-008 §3] 서명키만 있고 mission_store/site_store 가 없으면 조립 거부."""
    private_key = Ed25519PrivateKey.generate()
    with pytest.raises(ValueError, match="mission_store"):
        create_app(mission_signing_key=private_key, mission_signing_key_id="k1")


def test_issued_contract_is_signature_valid(tmp_path: Path) -> None:
    client, registry, _key_id = _client_with_signing(tmp_path)

    response = client.post("/v1/missions/contracts", json=_valid_request())

    assert response.status_code == 201
    contract = response.json()
    result = load_verified_contract(contract, registry, now=datetime.now(UTC))
    assert result.verdict is SignatureVerdict.VALID, result.detail


def test_v13_writer_assigns_core_owned_durable_site_sequence(tmp_path: Path) -> None:
    client, registry, _key_id = _client_with_signing(tmp_path, writer_version="1.3")

    first = client.post("/v1/missions/contracts", json=_valid_request(missionId="mission-001"))
    second = client.post("/v1/missions/contracts", json=_valid_request(missionId="mission-002"))

    assert first.status_code == 201, first.json()
    assert second.status_code == 201, second.json()
    assert first.json()["schemaVersion"] == "1.3"
    assert first.json()["issuance"]["issuerId"] == "core-seoul-1"
    assert first.json()["issuance"]["siteSequence"] == 1
    assert second.json()["issuance"]["siteSequence"] == 2
    assert "issuance" not in _valid_request()
    assert load_verified_contract(second.json(), registry, now=datetime.now(UTC)).is_valid


def test_v13_issuance_cannot_be_supplied_by_requester(tmp_path: Path) -> None:
    client, _registry, _key_id = _client_with_signing(tmp_path, writer_version="1.3")
    payload = _valid_request()
    payload["issuance"] = {
        "issuerId": "attacker",
        "siteSequence": 999,
        "issuedAt": datetime.now(UTC).isoformat(),
    }

    response = client.post("/v1/missions/contracts", json=payload)

    assert response.status_code == 422


def test_safety_policies_are_server_fixed_not_client_supplied(tmp_path: Path) -> None:
    """요청 바디에 안전 상수를 넣을 자리가 아예 없다 — extra=forbid로 거부된다."""
    client, _registry, _key_id = _client_with_signing(tmp_path)
    request = _valid_request()
    request["batteryPolicy"] = {
        "mode": "RETURN_ENERGY_PLUS_RESERVE",
        "defaultReservePercent": 0,
    }

    response = client.post("/v1/missions/contracts", json=request)

    assert response.status_code == 422


def test_issued_contract_carries_ledger_default_policies(tmp_path: Path) -> None:
    client, _registry, _key_id = _client_with_signing(tmp_path)

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


def test_assigned_device_id_is_not_signed_into_the_contract(tmp_path: Path) -> None:
    """[핵심] assignedDeviceId 는 Core 운영 메타데이터일 뿐 서명된 계약에는
    실리지 않는다(MissionRecord.assigned_device_id 문서) — 신뢰 경계 밖."""
    client, _registry, _key_id = _client_with_signing(tmp_path)
    request = _valid_request(assignedDeviceId="edge-001")

    response = client.post("/v1/missions/contracts", json=request)

    assert response.status_code == 201
    assert "assignedDeviceId" not in response.json()


def test_assigned_device_id_is_visible_on_mission_record(tmp_path: Path) -> None:
    """발급 시 신고한 배정이 조회 표면(GET /v1/missions/{id})에 그대로 보인다."""
    client, _registry, _key_id = _client_with_signing(tmp_path)
    request = _valid_request(assignedDeviceId="edge-001")
    issue_response = client.post("/v1/missions/contracts", json=request)
    assert issue_response.status_code == 201

    read_response = client.get(f"/v1/missions/{request['missionId']}")

    assert read_response.status_code == 200
    assert read_response.json()["assignedDeviceId"] == "edge-001"


def test_unassigned_mission_record_shows_null_device(tmp_path: Path) -> None:
    """생략하면 null — 배정 안 함과 배정을 다른 값으로 착각하게 만들지 않는다."""
    client, _registry, _key_id = _client_with_signing(tmp_path)
    request = _valid_request()  # assignedDeviceId 생략
    issue_response = client.post("/v1/missions/contracts", json=request)
    assert issue_response.status_code == 201

    read_response = client.get(f"/v1/missions/{request['missionId']}")

    assert read_response.json()["assignedDeviceId"] is None


def test_valid_for_hours_beyond_cap_rejected(tmp_path: Path) -> None:
    client, _registry, _key_id = _client_with_signing(tmp_path)

    response = client.post(
        "/v1/missions/contracts", json=_valid_request(validForHours=169.0)
    )

    assert response.status_code == 422


# ── C. FlightEnvelope 절대 sanity cap (P2 — 잠정, 원장 risk
#      flight-envelope-absolute-ceiling) ─────────────────────────────────────


def test_absolute_altitude_cap_is_the_decided_regulatory_limit() -> None:
    """[결정 고정] 고도 상한은 150m 다 — 항공안전법 일반 비행제한 고도(2026-08-05 확정).

    이 값은 서버 고정 안전상수라 요청·설정으로 바꿀 수 없다. 값 자체를 바꾸는 건
    규제 판단이므로 대표자 결정 사안이고, 코드에서 조용히 흘러가지 않도록 여기서
    못박는다 — 이 테스트가 깨지면 "누가 안전 상한을 바꿨나"를 먼저 물어야 한다.
    """
    assert _ABSOLUTE_MAX_ALTITUDE_M == 150.0


def test_flight_envelope_rejects_altitude_above_absolute_cap() -> None:
    """상한을 넘는 고도는 서명 계약으로 성립하지 않는다(fail-closed)."""
    with pytest.raises(ValidationError):
        FlightEnvelope(
            allowed_volumes=["vol-1"],
            excluded_volumes=[],
            min_altitude_m=5.0,
            max_altitude_m=_ABSOLUTE_MAX_ALTITUDE_M + 1.0,
        )


def test_flight_envelope_accepts_altitude_at_absolute_cap() -> None:
    """경계값 자체는 허용된다 — 상한은 초과(>)만 거부한다."""
    envelope = FlightEnvelope(
        allowed_volumes=["vol-1"],
        excluded_volumes=[],
        min_altitude_m=5.0,
        max_altitude_m=_ABSOLUTE_MAX_ALTITUDE_M,
    )
    assert envelope.max_altitude_m == _ABSOLUTE_MAX_ALTITUDE_M


def test_issuance_endpoint_rejects_envelope_above_absolute_cap(tmp_path: Path) -> None:
    """API 레벨 반증 — 요청 바디의 maxAltitudeM 이 규제 상한을 넘으면 422."""
    client, _registry, _key_id = _client_with_signing(tmp_path)

    response = client.post(
        "/v1/missions/contracts",
        json=_valid_request(
            flightEnvelope={
                "allowedVolumes": ["vol-1"],
                "excludedVolumes": [],
                "minAltitudeM": 5.0,
                "maxAltitudeM": _ABSOLUTE_MAX_ALTITUDE_M + 1.0,
            }
        ),
    )

    assert response.status_code == 422
