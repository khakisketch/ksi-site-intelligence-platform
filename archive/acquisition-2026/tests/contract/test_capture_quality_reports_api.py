"""Capture-quality Edge API authority and organization-boundary contracts.

The report is evidence for a later read-time decision.  It must not become a
shortcut that lets an operator, another device, or a report payload mark a
Mission complete.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from ksi_core.acquisition import (
    AcquisitionConnectivityStore,
    AcquisitionCoordinationStore,
    AcquisitionDeploymentProfileV1,
    GatewayKind,
    GatewayTransport,
    InternetGate,
    ManifoldDirectMode,
    MediaPolicy,
    MsdkBridgeMode,
    OperatingMode,
    RoutingPolicy,
)
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.capture_quality_reports import CaptureQualityReportStore
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_execution import MissionExecutionStore
from ksi_core.mission_records import MissionRecord, MissionRecordVerdict, MissionStore
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore
from ksi_domain.enums import MissionExecutionStatus
from ksi_mission_contracts.models import SiteFrame

_NOW = datetime(2026, 8, 27, 1, 0, tzinfo=UTC)
_OPERATOR_TOKEN = "capture-quality-operator"  # noqa: S105 -- test fixture
_OTHER_OPERATOR_TOKEN = "capture-quality-other-operator"  # noqa: S105 -- test fixture
_EDGE_TOKEN = "capture-quality-edge-1"  # noqa: S105 -- test fixture
_OTHER_EDGE_TOKEN = "capture-quality-edge-2"  # noqa: S105 -- test fixture
_GATEWAY_TOKEN = "capture-quality-gateway"  # noqa: S105 -- test fixture
_FRAME = SiteFrame(
    crs="EPSG:5186",
    vertical_datum="KNGeoid2018",
    unit="meter",
    transform_version="1.0.0",
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


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
                token_sha256=_digest(_OTHER_OPERATOR_TOKEN),
                principal=Principal(
                    principal_id="operator-2",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                    organization_id="org-2",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_EDGE_TOKEN),
                principal=Principal(
                    principal_id="edge-1",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id="edge-1",
                    organization_id="org-1",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OTHER_EDGE_TOKEN),
                principal=Principal(
                    principal_id="edge-2",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id="edge-2",
                    organization_id="org-1",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_GATEWAY_TOKEN),
                principal=Principal(
                    principal_id="gateway-1",
                    kind=PrincipalKind.GATEWAY_DEVICE,
                    role=None,
                    device_id="gateway-1",
                    organization_id="org-1",
                ),
            ),
        ]
    )


def _profile() -> AcquisitionDeploymentProfileV1:
    return AcquisitionDeploymentProfileV1(
        schema_version="1.0",
        site_id="site-1",
        operating_mode=OperatingMode.RC_ATTENDED,
        gateway_kind=GatewayKind.RC_PLUS_2,
        gateway_transports=(GatewayTransport.WIFI,),
        internet_gate=InternetGate.REQUIRED_FOR_MISSION_ISSUE,
        manifold_direct_mode=ManifoldDirectMode.DISABLED,
        routing_policy=RoutingPolicy.RC_STANDARD,
        media_policy=MediaPolicy.RESULTS_IMMEDIATE_RAW_POSTFLIGHT,
        msdk_bridge_mode=MsdkBridgeMode.CONDITIONAL_PREFLIGHT_POSTFLIGHT,
        edge_device_id="edge-1",
        gateway_device_id="gateway-1",
    )


def _report(**overrides: object) -> dict[str, object]:
    report: dict[str, object] = {
        "schemaVersion": "1.0",
        "reportId": "quality-report-1",
        "organizationId": "org-1",
        "siteId": "site-1",
        "workOrderId": "obs-work-00000001",
        "missionId": "mission-1",
        "deviceId": "edge-1",
        "capturePolicyId": "capture-policy-1",
        "measurements": [
            {
                "artifactId": "photo-1",
                "capturedAt": "2026-08-27T01:00:00+00:00",
                "blurScore": 0.1,
                "exposureOk": True,
                "gsdCmPerPx": 1.5,
                "overlapRatio": 0.8,
                "occlusionRatio": 0.1,
                "status": "ACCEPTED",
            }
        ],
        "startedAt": "2026-08-27T01:00:00+00:00",
        "completedAt": "2026-08-27T01:01:00+00:00",
    }
    report.update(overrides)
    return report


def _mission() -> MissionRecord:
    return MissionRecord(
        mission_id="mission-1",
        site_id="site-1",
        mission_type="BASELINE_MAPPING",
        artifact_kind="pair",
        contract={"schemaVersion": "1.2", "missionId": "mission-1"},
        kmz_sha256="sha256:" + "a" * 64,
        route_pattern="lawnmower",
        waypoint_count=4,
        planned_coverage_ratio=1.0,
        issued_at=_NOW,
        issued_by="operator-1",
        organization_id="org-1",
        plan_request={"workOrderId": "obs-work-00000001"},
        plan_request_digest="sha256:" + "b" * 64,
        assigned_device_id="edge-1",
    )


def _fixture(
    tmp_path: Path,
) -> tuple[TestClient, AcquisitionCoordinationStore, MissionExecutionStore]:
    sites = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    assert (
        sites.register(
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
        DurableJournal(tmp_path / "work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            sites.get_scoped(site_id, organization_id) is not None
        ),
    )
    order = work_orders.create_work_order(
        organization_id="org-1",
        site_id="site-1",
        name="Capture quality API",
        work_area_ids=["area-1"],
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
    missions = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    assert missions.record_issuance(_mission()) is MissionRecordVerdict.RECORDED
    connectivity = AcquisitionConnectivityStore(
        DurableJournal(tmp_path / "connectivity.jsonl"),
        site_exists=lambda site_id, organization_id: (
            sites.get_scoped(site_id, organization_id) is not None
        ),
    )
    connectivity.upsert_profile(_profile(), organization_id="org-1", actor="fixture", now=_NOW)
    coordination = AcquisitionCoordinationStore(DurableJournal(tmp_path / "runs.jsonl"))
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
    execution = MissionExecutionStore(
        DurableJournal(tmp_path / "execution.jsonl"), mission_store=missions
    )
    quality = CaptureQualityReportStore(
        DurableJournal(tmp_path / "capture-quality.jsonl"),
        mission_store=missions,
        work_order_store=work_orders,
        coordination_store=coordination,
    )
    return (
        TestClient(
            create_app(
                auth_registry=_registry(),
                site_store=sites,
                mission_store=missions,
                observation_work_order_store=work_orders,
                acquisition_connectivity_store=connectivity,
                acquisition_coordination_store=coordination,
                mission_execution_store=execution,
                capture_quality_report_store=quality,
            )
        ),
        coordination,
        execution,
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_capture_quality_api_requires_bound_edge_and_is_idempotent(tmp_path: Path) -> None:
    client, coordination, execution = _fixture(tmp_path)
    path = "/v1/missions/mission-1/capture-quality-report"
    initial_run = coordination.run_for_mission("mission-1", organization_id="org-1")
    assert initial_run is not None

    assert client.post(path, json=_report(), headers=_headers(_OPERATOR_TOKEN)).status_code == 403
    assert client.post(path, json=_report(), headers=_headers(_GATEWAY_TOKEN)).status_code == 403
    assert client.post(path, json=_report(), headers=_headers(_OTHER_EDGE_TOKEN)).status_code == 404
    assert (
        client.post(
            path,
            json=_report(reportId="wrong-device", deviceId="edge-2"),
            headers=_headers(_EDGE_TOKEN),
        ).status_code
        == 404
    )

    created = client.post(path, json=_report(), headers=_headers(_EDGE_TOKEN))
    assert created.status_code == 201, created.text
    assert created.json()["verdict"] == "RECORDED"
    assert client.post(path, json=_report(), headers=_headers(_EDGE_TOKEN)).status_code == 200

    # The immutable report remains evidence only: it cannot synthesize an
    # execution-complete fact or change the WorkOrder/Mission binding.
    assert execution.effective_status("mission-1") is MissionExecutionStatus.ISSUED
    assert execution.history("mission-1") == []
    assert coordination.run_for_mission("mission-1", organization_id="org-1") == initial_run


def test_capture_quality_api_rejects_cross_scope_body_and_hides_other_org(tmp_path: Path) -> None:
    client, _, _ = _fixture(tmp_path)
    path = "/v1/missions/mission-1/capture-quality-report"

    assert (
        client.post(
            "/v1/missions/not-mission-1/capture-quality-report",
            json=_report(),
            headers=_headers(_EDGE_TOKEN),
        ).status_code
        == 422
    )
    assert (
        client.post(
            path,
            json=_report(reportId="wrong-org", organizationId="org-2"),
            headers=_headers(_EDGE_TOKEN),
        ).status_code
        == 404
    )
    assert (
        client.post(
            path,
            json=_report(reportId="wrong-work-order", workOrderId="other-work-order"),
            headers=_headers(_EDGE_TOKEN),
        ).status_code
        == 404
    )
    assert client.post(path, json=_report(), headers=_headers(_EDGE_TOKEN)).status_code == 201

    same_org = client.get(path, headers=_headers(_OPERATOR_TOKEN))
    assert same_org.status_code == 200, same_org.text
    assert same_org.json()["report"]["reportId"] == "quality-report-1"

    other_org = client.get(path, headers=_headers(_OTHER_OPERATOR_TOKEN))
    assert other_org.status_code == 404
    assert "quality-report-1" not in other_org.text
