"""A real planning-only successor can register later external work without a run.

Only proposal authority and object storage are fixture ports. Approval, journals,
scoped HTTP context, list projection and reconstruction registration are actual Core.
"""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from ksi_core.acquisition import observation_epoch_id
from ksi_core.acquisition.coordination import AcquisitionCoordinationStore
from ksi_core.acquisition.store import AcquisitionConnectivityStore
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.mission_records import MissionStore
from ksi_core.sites import SiteStore
from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1
from ksi_mission_contracts.models import SiteFrame
from test_external_reconstruction_api import _record, _Storage, _submission
from test_external_reobservation_successor import _approve, _store_with_source


def test_successor_list_context_and_external_registration_do_not_create_acquisition(tmp_path: Path):
    _, orders, authority = _store_with_source(tmp_path)
    source = orders.get(authority.source_work_order_id, organization_id="org-1")
    source_before = source.model_dump_json(by_alias=True)
    approval = _approve(orders, authority)
    successor = approval.successor_work_order
    order_journal_before = (tmp_path / "work-orders.jsonl").read_bytes()
    sites = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    sites.register(
        "site-1",
        "Fixture site",
        SiteFrame(
            crs="EPSG:5186", vertical_datum="KNGeoid2018", unit="meter", transform_version="1.0.0"
        ),
        organization_id="org-1",
        actor="fixture",
        now=datetime.now(UTC),
    )
    run_path = tmp_path / "acquisition-runs.jsonl"
    runs = AcquisitionCoordinationStore(
        DurableJournal(run_path), work_order_execution_guard=orders.assert_execution_allowed
    )
    run_before = run_path.read_bytes() if run_path.exists() else b""
    token = "successor-context-fixture"  # noqa: S105 -- fixture only
    client = TestClient(
        create_app(
            auth_registry=AuthRegistry(
                [_record(token, principal_id="operator-1", organization_id="org-1")]
            ),
            site_store=sites,
            observation_work_order_store=orders,
            mission_store=MissionStore(DurableJournal(tmp_path / "missions.jsonl")),
            acquisition_connectivity_store=AcquisitionConnectivityStore(
                DurableJournal(tmp_path / "connectivity.jsonl"),
                site_exists=lambda site_id, organization_id: (
                    sites.get_scoped(site_id, organization_id) is not None
                ),
            ),
            acquisition_coordination_store=runs,
            evidence_storage=_Storage(),
            external_reconstruction_store=ExternalReconstructionStore(
                DurableJournal(tmp_path / "external.jsonl")
            ),
        )
    )
    headers = {"Authorization": f"Bearer {token}"}
    listed = client.get("/v1/sites/site-1/observation-work-orders", headers=headers)
    assert listed.status_code == 200, listed.text
    assert successor.work_order_id in [item["workOrderId"] for item in listed.json()["workOrders"]]
    prefix = f"/v1/observation-work-orders/{successor.work_order_id}"
    denied = client.get(prefix + "/acquisition-progress", headers=headers)
    assert denied.status_code == 409, denied.text
    assert "PLANNING_ONLY" in denied.text
    context = client.get(prefix + "/external-reconstruction-context", headers=headers)
    assert context.status_code == 200, context.text
    assert context.json() == {
        "workOrderId": successor.work_order_id,
        "siteId": "site-1",
        "expectedEpochId": observation_epoch_id(successor),
        "cycleNumber": 1,
        "workOrderVersion": successor.version,
        "externalPlanningBinding": orders.get_external_reobservation_binding(
            successor.work_order_id, organization_id="org-1"
        ).model_dump(mode="json", by_alias=True),
        "externalResult": {"state": "NOT_CONFIGURED", "result": None},
    }
    assert context.json()["expectedEpochId"] != observation_epoch_id(source)
    assert context.json()["externalPlanningBinding"]["acquisitionRunAllowed"] is False
    assert context.json()["externalPlanningBinding"]["missionIssuanceAllowed"] is False
    managed = client.get(
        f"/v1/observation-work-orders/{source.work_order_id}/external-reconstruction-context",
        headers=headers,
    )
    assert managed.status_code == 200
    assert managed.json()["externalPlanningBinding"] is None
    submission = _submission(
        work_order_id=successor.work_order_id,
        epoch_id=context.json()["expectedEpochId"],
        organization_id="org-1",
        site_id="site-1",
        submitted_by="operator-1",
    )
    submission["submittedAt"] = "2026-09-09T03:00:00Z"
    submission["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(submission)
    registered = client.post(
        prefix + "/external-reconstruction-submissions", headers=headers, json=submission
    )
    assert registered.status_code == 201, registered.text
    assert (
        orders.get(source.work_order_id, organization_id="org-1").model_dump_json(by_alias=True)
        == source_before
    )
    assert (tmp_path / "work-orders.jsonl").read_bytes() == order_journal_before
    assert (run_path.read_bytes() if run_path.exists() else b"") == run_before
