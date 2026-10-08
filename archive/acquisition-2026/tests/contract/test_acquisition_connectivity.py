from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from ksi_core.acquisition import (
    AcquisitionCapability,
    AcquisitionConnectivityStore,
    AcquisitionDeploymentProfileV1,
    CapabilityStatus,
    ConnectivitySnapshotV1,
    ReadinessStatus,
)
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionStore
from ksi_core.sites import SiteStore
from ksi_mission_contracts.models import SiteFrame

_ROOT = Path(__file__).resolve().parents[2]
_ADMIN_TOKEN = "acquisition-admin-token"  # noqa: S105
_GATEWAY_TOKEN = "acquisition-gateway-token"  # noqa: S105
_OTHER_GATEWAY_TOKEN = "acquisition-other-gateway-token"  # noqa: S105


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _profile(**overrides: Any) -> AcquisitionDeploymentProfileV1:
    raw: dict[str, Any] = {
        "schemaVersion": "1.0",
        "siteId": "site-1",
        "operatingMode": "RC_ATTENDED",
        "gatewayKind": "RC_PLUS_2",
        "gatewayTransports": ["WIFI", "CELLULAR"],
        "internetGate": "REQUIRED_FOR_MISSION_ISSUE",
        "manifoldDirectMode": "DISABLED",
        "routingPolicy": "RC_STANDARD",
        "mediaPolicy": "RESULTS_IMMEDIATE_RAW_POSTFLIGHT",
        "msdkBridgeMode": "CONDITIONAL_PREFLIGHT_POSTFLIGHT",
        "edgeDeviceId": "manifold-1",
        "gatewayDeviceId": "rc-plus-2-1",
    }
    raw.update(overrides)
    return AcquisitionDeploymentProfileV1.model_validate(raw)


def _snapshot(
    now: datetime,
    *,
    internet: bool = True,
    status: str = "VERIFIED",
    capabilities: tuple[AcquisitionCapability, ...] = tuple(AcquisitionCapability),
    **overrides: Any,
) -> ConnectivitySnapshotV1:
    raw: dict[str, Any] = {
        "schemaVersion": "1.0",
        "snapshotId": "snapshot-1",
        "siteId": "site-1",
        "gatewayDeviceId": "rc-plus-2-1",
        "edgeDeviceId": "manifold-1",
        "observedAt": now.isoformat(),
        "expiresAt": (now + timedelta(minutes=2)).isoformat(),
        "transport": "WIFI",
        "internetReachable": internet,
        "gatewayState": "CONNECTED",
        "edgeState": "CONNECTED",
        "directEdgeState": "DISABLED",
        "queuedEventCount": 0,
        "queuedMediaCount": 0,
        "lastSuccessReceiptId": None,
        "missionContractSync": "NOT_STARTED",
        "rawMediaSync": "NOT_STARTED",
        "capabilities": [
            {
                "capability": capability.value,
                "hardwareModel": "M4D-RC-PLUS-2-M3",
                "firmwareVersion": "HIL-PENDING",
                "status": status,
                "checkedAt": now.isoformat(),
                "evidenceRef": (
                    f"hil/session/{capability.value.lower()}" if status == "VERIFIED" else None
                ),
            }
            for capability in capabilities
        ],
    }
    raw.update(overrides)
    return ConnectivitySnapshotV1.model_validate(raw)


def _store(tmp_path: Path) -> AcquisitionConnectivityStore:
    return AcquisitionConnectivityStore(
        DurableJournal(tmp_path / "acquisition-connectivity.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_id == "site-1" and organization_id == "org-1"
        ),
    )


def test_contract_json_schemas_accept_wire_models() -> None:
    now = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    pairs = [
        (
            "acquisition-deployment-profile.v1.json",
            _profile().model_dump(mode="json", by_alias=True),
        ),
        ("connectivity-snapshot.v1.json", _snapshot(now).model_dump(mode="json", by_alias=True)),
    ]
    for filename, instance in pairs:
        schema = json.loads((_ROOT / "contracts" / "schemas" / filename).read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(instance)


def test_profile_rejects_device_alias_and_invalid_rc_transport() -> None:
    with pytest.raises(ValueError, match="서로 다른 장치"):
        _profile(edgeDeviceId="rc-plus-2-1")
    with pytest.raises(ValueError, match="WIFI"):
        _profile(gatewayTransports=["CELLULAR"])


def test_readiness_is_fail_closed_but_preserves_active_contract_policy(tmp_path: Path) -> None:
    now = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    store = _store(tmp_path)
    store.upsert_profile(_profile(), organization_id="org-1", actor="admin", now=now)

    missing = store.readiness("site-1", organization_id="org-1", now=now)
    assert missing.status is ReadinessStatus.CONNECTIVITY_MISSING

    store.observe(_snapshot(now, internet=False), organization_id="org-1", actor="gateway", now=now)
    offline = store.readiness("site-1", organization_id="org-1", now=now)
    assert offline.status is ReadinessStatus.INTERNET_REQUIRED
    assert not offline.ready_for_mission_issue
    assert offline.in_flight_contract_policy == "REMAINS_VALID_UNTIL_CONTRACT_EXPIRY"


def test_readiness_requires_each_independently_verified_capability(tmp_path: Path) -> None:
    now = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    store = _store(tmp_path)
    store.upsert_profile(_profile(), organization_id="org-1", actor="admin", now=now)
    store.observe(
        _snapshot(now, capabilities=(AcquisitionCapability.WAYLINE_DELIVERY,)),
        organization_id="org-1",
        actor="gateway",
        now=now,
    )
    blocked = store.readiness("site-1", organization_id="org-1", now=now)
    assert blocked.status is ReadinessStatus.CAPABILITY_NOT_VERIFIED
    assert "EDGE_DOWNLINK" in blocked.reasons[0]

    store.observe(
        _snapshot(now, snapshotId="snapshot-2"),
        organization_id="org-1",
        actor="gateway",
        now=now,
    )
    assert (
        store.readiness("site-1", organization_id="org-1", now=now).status is ReadinessStatus.READY
    )


def test_stale_snapshot_blocks_new_issue_and_replays(tmp_path: Path) -> None:
    now = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    journal_path = tmp_path / "acquisition-connectivity.jsonl"
    store = _store(tmp_path)
    store.upsert_profile(_profile(), organization_id="org-1", actor="admin", now=now)
    store.observe(_snapshot(now), organization_id="org-1", actor="gateway", now=now)
    store._journal.close()  # noqa: SLF001 -- explicit restart/replay contract

    replayed = AcquisitionConnectivityStore(
        DurableJournal(journal_path), site_exists=lambda _site, _org: True
    )
    result = replayed.readiness("site-1", organization_id="org-1", now=now + timedelta(minutes=3))
    assert result.status is ReadinessStatus.CONNECTIVITY_STALE


def test_snapshot_nonce_reuse_and_state_rollback_are_rejected(tmp_path: Path) -> None:
    now = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    store = _store(tmp_path)
    store.upsert_profile(_profile(), organization_id="org-1", actor="admin", now=now)
    store.observe(_snapshot(now), organization_id="org-1", actor="gateway", now=now)

    with pytest.raises(ValueError, match="재사용"):
        store.observe(
            _snapshot(now, internet=False),
            organization_id="org-1",
            actor="gateway",
            now=now,
        )

    with pytest.raises(ValueError, match="과거"):
        store.observe(
            _snapshot(
                now - timedelta(seconds=1),
                snapshotId="snapshot-2",
            ),
            organization_id="org-1",
            actor="gateway",
            now=now,
        )

    current = store.readiness("site-1", organization_id="org-1", now=now)
    assert current.ready_for_mission_issue


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_ADMIN_TOKEN),
                principal=Principal(
                    principal_id="admin",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                    organization_id="org-1",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_GATEWAY_TOKEN),
                principal=Principal(
                    principal_id="gateway-1",
                    kind=PrincipalKind.GATEWAY_DEVICE,
                    role=None,
                    device_id="rc-plus-2-1",
                    organization_id="org-1",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OTHER_GATEWAY_TOKEN),
                principal=Principal(
                    principal_id="gateway-2",
                    kind=PrincipalKind.GATEWAY_DEVICE,
                    role=None,
                    device_id="rc-plus-2-2",
                    organization_id="org-2",
                ),
            ),
        ]
    )


def test_api_separates_operator_gateway_and_organization_scope(tmp_path: Path) -> None:
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    store = AcquisitionConnectivityStore(
        DurableJournal(tmp_path / "acquisition.jsonl"), site_exists=lambda _site, _org: True
    )
    client = TestClient(
        create_app(
            auth_registry=_registry(),
            site_store=site_store,
            acquisition_connectivity_store=store,
        )
    )
    admin_headers = {"Authorization": f"Bearer {_ADMIN_TOKEN}"}
    gateway_headers = {"Authorization": f"Bearer {_GATEWAY_TOKEN}"}
    other_headers = {"Authorization": f"Bearer {_OTHER_GATEWAY_TOKEN}"}

    profile_wire = _profile().model_dump(mode="json", by_alias=True)
    assert (
        client.put(
            "/v1/sites/site-1/acquisition-profile", json=profile_wire, headers=admin_headers
        ).status_code
        == 200
    )

    now = datetime.now(UTC).replace(microsecond=0)
    snapshot_wire = _snapshot(now, status=CapabilityStatus.NOT_VERIFIED.value).model_dump(
        mode="json", by_alias=True
    )
    assert (
        client.post(
            "/v1/gateway-sync/heartbeats", json=snapshot_wire, headers=admin_headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/gateway-sync/heartbeats", json=snapshot_wire, headers=other_headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/gateway-sync/heartbeats", json=snapshot_wire, headers=gateway_headers
        ).status_code
        == 201
    )
    assert (
        client.get("/v1/sites/site-1/acquisition-profile", headers=other_headers).status_code == 403
    )


def test_configured_readiness_gate_blocks_new_mission_issue_until_ready(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    site_store.register(
        "site-1",
        "Site 1",
        SiteFrame.model_validate(
            {
                "crs": "EPSG:5186",
                "verticalDatum": "KNGeoid2018",
                "unit": "meter",
                "transformVersion": "1.0.0",
            }
        ),
        actor="admin",
        now=now,
        organization_id="org-1",
    )
    acquisition_store = AcquisitionConnectivityStore(
        DurableJournal(tmp_path / "acquisition-gate.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    acquisition_store.upsert_profile(
        _profile(), organization_id="org-1", actor="admin", now=now
    )
    app = create_app(
        auth_registry=_registry(),
        site_store=site_store,
        mission_store=MissionStore(DurableJournal(tmp_path / "missions.jsonl")),
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="test-key",
        acquisition_connectivity_store=acquisition_store,
        acquisition_issue_gate_enabled=True,
    )
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {_ADMIN_TOKEN}"}
    request = {
        "missionId": "mission-1",
        "siteId": "site-1",
        "missionType": "BASELINE_MAPPING",
        "siteFrame": {
            "crs": "EPSG:5186",
            "verticalDatum": "KNGeoid2018",
            "unit": "meter",
            "transformVersion": "1.0.0",
        },
        "flightEnvelope": {
            "allowedVolumes": ["volume-1"],
            "excludedVolumes": [],
            "minAltitudeM": 5,
            "maxAltitudeM": 100,
        },
        "objectives": ["baseline mapping"],
        "viewpointPolicyId": "vp-1",
        "riskPolicyPackId": "risk-1",
        "fallbackPolicyId": "fallback-1",
        "capturePolicyId": "capture-1",
    }

    blocked = client.post("/v1/missions/contracts", json=request, headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["detail"].startswith("ACQUISITION_NOT_READY")

    acquisition_store.observe(
        _snapshot(now), organization_id="org-1", actor="gateway", now=now
    )
    issued = client.post("/v1/missions/contracts", json=request, headers=headers)
    assert issued.status_code == 201, issued.json()


def test_issue_gate_cannot_be_enabled_without_the_readiness_store() -> None:
    with pytest.raises(ValueError, match="acquisition_connectivity_store"):
        create_app(acquisition_issue_gate_enabled=True)
