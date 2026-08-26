"""REQ-ACQ/WRK/MSN/SEC acquisition coordination durability and API gates."""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core.acquisition import (
    AcquisitionConnectivityStore,
    AcquisitionCoordinationConflictError,
    AcquisitionCoordinationStore,
    AcquisitionDeploymentProfileV1,
    AcquisitionProgressProjector,
    AcquisitionRunStage,
    GatewayOperationReceiptRequest,
)
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_execution import MissionExecutionStore
from ksi_core.mission_records import MissionRecord, MissionRecordVerdict, MissionStore
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore
from ksi_domain.enums import MissionExecutionStatus
from ksi_event_contracts.observation_work_order import ObservationWorkOrder
from ksi_mission_contracts.models import SiteFrame

_NOW = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
_OPERATOR_TOKEN = "coordination-operator-token"  # noqa: S105
_GATEWAY_TOKEN = "coordination-gateway-token"  # noqa: S105
_OTHER_GATEWAY_TOKEN = "coordination-other-gateway-token"  # noqa: S105
_FRAME = SiteFrame(
    crs="EPSG:5186",
    vertical_datum="KNGeoid2018",
    unit="meter",
    transform_version="1.0.0",
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _order(*, status: str = "APPROVED", cycle: int = 1) -> ObservationWorkOrder:
    return ObservationWorkOrder.model_validate(
        {
            "schemaVersion": "1.0",
            "workOrderId": "obs-work-00000001",
            "organizationId": "org-1",
            "siteId": "site-1",
            "purpose": "PROGRESS_QUANTITY",
            "name": "주간 토공 관측",
            "workAreaIds": ["wa-1"],
            "scheduleId": None,
            "cycleNumber": cycle,
            "status": status,
            "statusReason": None,
            "missionIds": [],
            "processingJobIds": [],
            "reportRefs": [],
            "version": 2,
            "createdAt": _NOW.isoformat(),
            "updatedAt": _NOW.isoformat(),
            "createdBy": "operator-1",
            "approvedAt": _NOW.isoformat(),
            "approvedBy": "operator-1",
        }
    )


def _profile() -> AcquisitionDeploymentProfileV1:
    return AcquisitionDeploymentProfileV1.model_validate(
        {
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
    )


def _receipt(**overrides: object) -> GatewayOperationReceiptRequest:
    raw: dict[str, object] = {
        "schemaVersion": "1.0",
        "receiptId": "receipt-1",
        "idempotencyKey": "mission-1:wayline:1",
        "siteId": "site-1",
        "missionId": "mission-1",
        "capability": "WAYLINE_DELIVERY",
        "transport": "WIFI",
        "outcome": "SUCCEEDED",
        "artifactDigest": "sha256:" + "a" * 64,
        "observedAt": _NOW.isoformat(),
    }
    raw.update(overrides)
    return GatewayOperationReceiptRequest.model_validate(raw)


def _mission_record() -> MissionRecord:
    return MissionRecord(
        mission_id="mission-1",
        site_id="site-1",
        mission_type="BASELINE_MAPPING",
        artifact_kind="pair",
        contract={"schemaVersion": "1.2", "missionId": "mission-1"},
        kmz_sha256="sha256:" + "b" * 64,
        route_pattern="lawnmower",
        waypoint_count=4,
        planned_coverage_ratio=1.0,
        issued_at=_NOW,
        issued_by="operator-1",
        # This fixture is wired to org-1 Site/WorkOrder/Gateway profile. Keep
        # its Mission lineage explicit so request-scoped Mission visibility
        # exercises the same multi-organization boundary as production.
        organization_id="org-1",
        plan_request={"workOrderId": "obs-work-00000001"},
        plan_request_digest="sha256:" + "c" * 64,
        assigned_device_id="manifold-1",
    )


def test_run_receipt_idempotency_transport_fallback_and_replay(tmp_path: Path) -> None:
    journal_path = tmp_path / "acquisition-runs.jsonl"
    store = AcquisitionCoordinationStore(DurableJournal(journal_path))
    order = _order()
    first = store.ensure_run(order, actor="operator-1", now=_NOW)
    assert store.ensure_run(order, actor="operator-1", now=_NOW) == first
    linked = store.link_mission(order, "mission-1", actor="operator-1", now=_NOW)
    assert linked.mission_id == "mission-1"

    recorded, created = store.record_receipt(
        _receipt(),
        organization_id="org-1",
        gateway_device_id="rc-plus-2-1",
        actor="gateway-1",
        now=_NOW,
    )
    assert created
    retried, created = store.record_receipt(
        _receipt(),
        organization_id="org-1",
        gateway_device_id="rc-plus-2-1",
        actor="gateway-1",
        now=_NOW,
    )
    assert not created
    assert retried == recorded

    # Fallback transport intentionally retains the same idempotency key/digest.
    fallback, created = store.record_receipt(
        _receipt(receiptId="receipt-2", transport="CELLULAR"),
        organization_id="org-1",
        gateway_device_id="rc-plus-2-1",
        actor="gateway-1",
        now=_NOW + timedelta(seconds=1),
    )
    assert created and fallback.transport.value == "CELLULAR"

    with pytest.raises(AcquisitionCoordinationConflictError, match="digest"):
        store.record_receipt(
            _receipt(receiptId="receipt-3", artifactDigest="sha256:" + "d" * 64),
            organization_id="org-1",
            gateway_device_id="rc-plus-2-1",
            actor="gateway-1",
            now=_NOW,
        )

    store._journal.close()  # noqa: SLF001 -- explicit crash/restart contract
    replayed = AcquisitionCoordinationStore(DurableJournal(journal_path))
    assert replayed.run_for_mission("mission-1", organization_id="org-1") == linked
    assert [
        item.receipt_id
        for item in replayed.receipts_for_mission("mission-1", organization_id="org-1")
    ] == ["receipt-1", "receipt-2"]


def test_stale_connectivity_does_not_regress_activated_contract(tmp_path: Path) -> None:
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    assert mission_store.record_issuance(_mission_record()) is MissionRecordVerdict.RECORDED
    execution_store = MissionExecutionStore(
        DurableJournal(tmp_path / "mission-execution.jsonl"), mission_store=mission_store
    )
    execution_store.transition(
        "mission-1",
        MissionExecutionStatus.DISPATCHED,
        detail="gateway",
        actor="gateway-1",
        now=_NOW,
    )
    execution_store.transition(
        "mission-1",
        MissionExecutionStatus.ACTIVATED,
        detail="signed edge receipt",
        actor="manifold-1",
        now=_NOW + timedelta(seconds=1),
    )
    connectivity = AcquisitionConnectivityStore(
        DurableJournal(tmp_path / "connectivity.jsonl"), site_exists=lambda _site, _org: True
    )
    connectivity.upsert_profile(_profile(), organization_id="org-1", actor="admin", now=_NOW)
    coordination = AcquisitionCoordinationStore(DurableJournal(tmp_path / "runs.jsonl"))
    coordination.ensure_run(_order(), actor="operator-1", now=_NOW)
    coordination.link_mission(_order(), "mission-1", actor="operator-1", now=_NOW)

    view = AcquisitionProgressProjector(
        coordination_store=coordination,
        connectivity_store=connectivity,
        mission_execution_store=execution_store,
    ).project(_order(), now=_NOW + timedelta(hours=1))
    assert not view.readiness.ready_for_mission_issue
    assert view.stage is AcquisitionRunStage.READY_FOR_FLIGHT
    assert view.contract_activation.state == "ACTIVATED"
    assert view.in_flight_contract_policy == "REMAINS_VALID_UNTIL_CONTRACT_EXPIRY"


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_OPERATOR_TOKEN),
                principal=Principal(
                    principal_id="operator-1",
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
                    principal_id="gateway-other",
                    kind=PrincipalKind.GATEWAY_DEVICE,
                    role=None,
                    device_id="rc-plus-2-2",
                    organization_id="org-2",
                ),
            ),
        ]
    )


def _api_fixture(
    tmp_path: Path,
) -> tuple[
    TestClient,
    ObservationWorkOrderStore,
    AcquisitionCoordinationStore,
    MissionStore,
]:
    site_store = SiteStore(DurableJournal(tmp_path / "sites-api.jsonl"))
    registered = site_store.register(
        "site-1",
        "Site 1",
        _FRAME,
        organization_id="org-1",
        actor="fixture",
        now=_NOW,
    )
    assert registered.record is not None
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "work-orders-api.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    order = work_orders.create_work_order(
        organization_id="org-1",
        site_id="site-1",
        name="주간 토공 관측",
        work_area_ids=["wa-1"],
        schedule_id=None,
        actor="operator-1",
        now=_NOW,
    )
    order = work_orders.approve(
        order.work_order_id,
        organization_id="org-1",
        expected_version=order.version,
        actor="operator-1",
        now=_NOW,
    )
    mission_store = MissionStore(DurableJournal(tmp_path / "missions-api.jsonl"))
    assert mission_store.record_issuance(_mission_record()) is MissionRecordVerdict.RECORDED
    connectivity = AcquisitionConnectivityStore(
        DurableJournal(tmp_path / "connectivity-api.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    connectivity.upsert_profile(_profile(), organization_id="org-1", actor="operator-1", now=_NOW)
    coordination = AcquisitionCoordinationStore(DurableJournal(tmp_path / "runs-api.jsonl"))
    coordination.ensure_run(order, actor="operator-1", now=_NOW)
    coordination.link_mission(order, "mission-1", actor="operator-1", now=_NOW)
    work_orders.link_mission(
        order.work_order_id,
        organization_id="org-1",
        cycle_number=order.cycle_number,
        mission_id="mission-1",
        mission_site_id="site-1",
        actor="operator-1",
        now=_NOW,
        require_approved=True,
    )
    app = create_app(
        auth_registry=_registry(),
        site_store=site_store,
        mission_store=mission_store,
        observation_work_order_store=work_orders,
        acquisition_connectivity_store=connectivity,
        acquisition_coordination_store=coordination,
    )
    return TestClient(app), work_orders, coordination, mission_store


def test_operation_receipt_api_enforces_gateway_binding_and_digest(tmp_path: Path) -> None:
    client, work_orders, _, _ = _api_fixture(tmp_path)
    request = _receipt(observedAt=datetime.now(UTC).isoformat()).model_dump(
        mode="json", by_alias=True
    )
    operator_headers = {"Authorization": f"Bearer {_OPERATOR_TOKEN}"}
    gateway_headers = {"Authorization": f"Bearer {_GATEWAY_TOKEN}"}
    other_headers = {"Authorization": f"Bearer {_OTHER_GATEWAY_TOKEN}"}

    assert (
        client.post(
            "/v1/gateway-sync/operation-receipts", json=request, headers=operator_headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/gateway-sync/operation-receipts", json=request, headers=other_headers
        ).status_code
        == 404
    )
    created = client.post(
        "/v1/gateway-sync/operation-receipts", json=request, headers=gateway_headers
    )
    assert created.status_code == 201, created.text
    assert (
        client.post(
            "/v1/gateway-sync/operation-receipts", json=request, headers=gateway_headers
        ).status_code
        == 200
    )

    conflict = dict(request)
    conflict["receiptId"] = "receipt-conflict"
    conflict["artifactDigest"] = "sha256:" + "f" * 64
    assert (
        client.post(
            "/v1/gateway-sync/operation-receipts", json=conflict, headers=gateway_headers
        ).status_code
        == 409
    )

    work_order = work_orders.get("obs-work-00000001", organization_id="org-1")
    assert work_order is not None
    progress = client.get(
        f"/v1/observation-work-orders/{work_order.work_order_id}/acquisition-progress",
        headers=operator_headers,
    )
    assert progress.status_code == 200, progress.text
    assert progress.json()["gateway"]["succeededCapabilities"] == ["WAYLINE_DELIVERY"]


def test_approval_creates_one_run_and_coordinator_failure_does_not_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, work_orders, coordination, _ = _api_fixture(tmp_path)
    headers = {"Authorization": f"Bearer {_OPERATOR_TOKEN}"}
    created = client.post(
        "/v1/sites/site-1/observation-work-orders",
        headers=headers,
        json={"name": "승인 callback", "workAreaIds": ["wa-2"]},
    )
    assert created.status_code == 201, created.text
    approved = client.post(
        f"/v1/observation-work-orders/{created.json()['workOrderId']}/approve",
        headers=headers,
        json={"expectedVersion": created.json()["version"]},
    )
    assert approved.status_code == 200, approved.text
    run = coordination.get_run(
        created.json()["workOrderId"], organization_id="org-1", cycle_number=1
    )
    assert run is not None
    stored_order = work_orders.get(created.json()["workOrderId"], organization_id="org-1")
    assert stored_order is not None
    assert (
        coordination.ensure_run(
            stored_order,
            actor="operator-1",
            now=_NOW,
        )
        == run
    )

    created_with_failure = client.post(
        "/v1/sites/site-1/observation-work-orders",
        headers=headers,
        json={"name": "coordinator failure", "workAreaIds": ["wa-3"]},
    )
    assert created_with_failure.status_code == 201

    def fail_run(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected coordinator failure")

    monkeypatch.setattr(coordination, "ensure_run", fail_run)
    still_approved = client.post(
        f"/v1/observation-work-orders/{created_with_failure.json()['workOrderId']}/approve",
        headers=headers,
        json={"expectedVersion": created_with_failure.json()["version"]},
    )
    assert still_approved.status_code == 200
    persisted = work_orders.get(created_with_failure.json()["workOrderId"], organization_id="org-1")
    assert persisted is not None and persisted.status.value == "APPROVED"


def test_work_order_mission_link_rejects_site_and_cycle_mismatch(tmp_path: Path) -> None:
    _, work_orders, _, _ = _api_fixture(tmp_path)
    with pytest.raises(ValueError, match="Site"):
        work_orders.link_mission(
            "obs-work-00000001",
            organization_id="org-1",
            cycle_number=1,
            mission_id="mission-other",
            mission_site_id="site-other",
            actor="operator-1",
            now=_NOW,
            require_approved=True,
        )
    with pytest.raises(RuntimeError, match="CYCLE"):
        work_orders.link_mission(
            "obs-work-00000001",
            organization_id="org-1",
            cycle_number=2,
            mission_id="mission-other",
            mission_site_id="site-1",
            actor="operator-1",
            now=_NOW,
            require_approved=True,
        )


def test_mission_plan_work_order_lineage_is_idempotently_linked(tmp_path: Path) -> None:
    site_store = SiteStore(DurableJournal(tmp_path / "sites-plan.jsonl"))
    assert (
        site_store.register(
            "site-1",
            "Site 1",
            _FRAME,
            organization_id="org-1",
            actor="fixture",
            now=_NOW,
        ).record
        is not None
    )
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "work-orders-plan.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    order = work_orders.create_work_order(
        organization_id="org-1",
        site_id="site-1",
        name="주간 토공 관측",
        work_area_ids=["wa-1"],
        schedule_id=None,
        actor="operator-1",
        now=_NOW,
    )
    order = work_orders.approve(
        order.work_order_id,
        organization_id="org-1",
        expected_version=order.version,
        actor="operator-1",
        now=_NOW,
    )
    mission_store = MissionStore(DurableJournal(tmp_path / "missions-plan.jsonl"))
    connectivity = AcquisitionConnectivityStore(
        DurableJournal(tmp_path / "connectivity-plan.jsonl"),
        site_exists=lambda _site, _org: True,
    )
    coordination = AcquisitionCoordinationStore(DurableJournal(tmp_path / "runs-plan.jsonl"))
    client = TestClient(
        create_app(
            auth_registry=_registry(),
            site_store=site_store,
            mission_store=mission_store,
            mission_signing_key=Ed25519PrivateKey.generate(),
            mission_signing_key_id="test-key",
            observation_work_order_store=work_orders,
            acquisition_connectivity_store=connectivity,
            acquisition_coordination_store=coordination,
        )
    )
    dlat = 100.0 / (math.radians(1.0) * 6_378_137.0)
    dlon = 100.0 / (math.radians(1.0) * 6_378_137.0 * math.cos(math.radians(37.5)))
    request = {
        "workOrderId": order.work_order_id,
        "contract": {
            "missionId": "mission-linked",
            "siteId": "site-1",
            "missionType": "BASELINE_MAPPING",
            "siteFrame": _FRAME.model_dump(mode="json", by_alias=True),
            "flightEnvelope": {
                "allowedVolumes": ["volume-1"],
                "excludedVolumes": [],
                "minAltitudeM": 5,
                "maxAltitudeM": 100,
            },
            "objectives": ["baseline"],
            "viewpointPolicyId": "vp-1",
            "riskPolicyPackId": "risk-1",
            "fallbackPolicyId": "fallback-1",
            "capturePolicyId": "capture-1",
        },
        "aoi": {
            "vertices": [
                {"latDeg": 37.5, "lonDeg": 127.0},
                {"latDeg": 37.5, "lonDeg": 127.0 + dlon},
                {"latDeg": 37.5 + dlat, "lonDeg": 127.0 + dlon},
                {"latDeg": 37.5 + dlat, "lonDeg": 127.0},
            ]
        },
        "route": {"altitudeM": 40, "spacingM": 20, "captureIntervalM": 15},
        "drone": {
            "droneEnumValue": 99,
            "droneSubEnumValue": 0,
            "payloadEnumValue": 65534,
        },
        "wayline": {
            "autoFlightSpeedMs": 5,
            "takeoffSecurityHeightM": 20,
            "globalTransitionalSpeedMs": 10,
        },
    }
    headers = {"Authorization": f"Bearer {_OPERATOR_TOKEN}"}
    issued = client.post("/v1/missions/plans", json=request, headers=headers)
    assert issued.status_code == 201, issued.text
    retried = client.post("/v1/missions/plans", json=request, headers=headers)
    assert retried.status_code == 200, retried.text

    linked_order = work_orders.get(order.work_order_id, organization_id="org-1")
    assert linked_order is not None
    assert linked_order.mission_ids == ["mission-linked"]
    run = coordination.get_run(
        order.work_order_id,
        organization_id="org-1",
        cycle_number=order.cycle_number,
    )
    assert run is not None and run.mission_id == "mission-linked"
    record = mission_store.get("mission-linked")
    assert record is not None and record.plan_request is not None
    assert record.plan_request["workOrderId"] == order.work_order_id
