"""Actual Core report -> review -> proposal -> sole successor and cold replay."""

from datetime import timedelta
from pathlib import Path

from external_product_loop_fixture import build_graph, record_measurement, seed_original
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, mount_auth
from ksi_core.external_reobservation_proposals import build_external_reobservation_proposal_router
from ksi_core.external_result_workflow_api import build_external_result_workflow_router
from test_external_result_review_proposals import _NOW, _TOKEN, _token_record


def test_report_review_approval_and_restart_are_actual_durable_core(tmp_path: Path):
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    report = record_measurement(graph)
    clock = [_NOW]
    app = FastAPI()
    mount_auth(app, AuthRegistry([_token_record()]))
    app.include_router(
        build_external_result_workflow_router(graph.volumes, graph.service, clock=lambda: clock[0])
    )
    app.include_router(
        build_external_reobservation_proposal_router(graph.service, clock=lambda: clock[0])
    )
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    path = f"/v1/external-relative-volume-reports/{report.report_id}"
    assert client.get(path).status_code == 401
    shown = client.get(path, headers=headers)
    assert shown.status_code == 200
    assert shown.json()["report"]["payload"]["metrics"]["netM3"] == 4
    assert shown.json()["review"] is None and shown.json()["proposals"] == []
    reviewed = client.post(path + "/reviews", headers=headers)
    assert reviewed.status_code == 201, reviewed.text
    review_ref = reviewed.json()["review"]["reviewRef"]
    created = client.post(
        "/v1/external-reobservation-proposals",
        headers={**headers, "Idempotency-Key": "proposal"},
        json={
            "reportRef": report.report_id,
            "targetWorkAreaIds": [source.authority.zone_snapshot.work_area_id],
        },
    )
    assert created.status_code == 201, created.text
    proposal = created.json()["proposal"]
    original_before = graph.service.work_orders.get(
        source.authority.current_work_order_id, organization_id="org-a"
    ).model_dump_json(by_alias=True)
    approved = client.post(
        "/v1/external-reobservation-proposals/approve",
        headers={**headers, "Idempotency-Key": "approval"},
        json={"proposalRef": proposal["proposalRef"], "expectedVersion": 1},
    )
    assert approved.status_code == 200, approved.text
    successor = approved.json()["approvalReceipt"]["successorWorkOrderId"]
    assert successor != source.authority.current_work_order_id
    binding = graph.service.work_orders.get_external_reobservation_binding(
        successor, organization_id="org-a"
    )
    assert (
        binding is not None
        and not binding.acquisition_run_allowed
        and not binding.mission_issuance_allowed
    )
    assert (
        graph.service.work_orders.get(
            source.authority.current_work_order_id, organization_id="org-a"
        ).model_dump_json(by_alias=True)
        == original_before
    )
    joined = client.get(path, headers=headers).json()
    assert joined["review"]["reviewRef"] == review_ref
    assert joined["proposals"][0]["approvalReceipt"]["successorWorkOrderId"] == successor
    assert (
        client.get(f"/v1/external-result-reviews/{review_ref}", headers=headers).status_code == 200
    )
    assert (
        client.get(
            f"/v1/external-reobservation-proposals/{proposal['proposalRef']}", headers=headers
        ).json()["approvalReceipt"]["successorWorkOrderId"]
        == successor
    )
    clock[0] += timedelta(seconds=30)
    assert client.get(path, headers=headers).status_code == 200
    assert client.post(path + "/reviews", headers=headers).status_code == 409
    retry = client.post(
        "/v1/external-reobservation-proposals/approve",
        headers={**headers, "Idempotency-Key": "approval"},
        json={"proposalRef": proposal["proposalRef"], "expectedVersion": 1},
    )
    assert (
        retry.status_code == 200
        and retry.json()["approvalReceipt"]["successorWorkOrderId"] == successor
    )
    graph.close()
    journals_before = {p.name: p.read_bytes() for p in tmp_path.glob("*.jsonl")}
    replay = build_graph(tmp_path, source)
    assert (
        replay.service.work_orders.get_external_reobservation_binding(
            successor, organization_id="org-a"
        )
        == binding
    )
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.jsonl")} == journals_before
    assert not (tmp_path / "acquisition-runs.jsonl").exists()
    replay.close()


def test_report_views_are_scoped_and_review_body_cannot_supply_authority(tmp_path: Path):
    import hashlib

    from ksi_core.auth import PrincipalTokenRecord
    from test_external_result_review_proposals import _principal

    graph = build_graph(tmp_path, seed_original(tmp_path))
    report = record_measurement(graph)
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                _token_record(),
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(b"other-org-fixture").hexdigest(),
                    principal=_principal(organization_id="org-b", principal_id="operator-b"),
                ),
            ]
        ),
    )
    app.include_router(
        build_external_result_workflow_router(graph.volumes, graph.service, clock=lambda: _NOW)
    )
    client = TestClient(app)
    path = f"/v1/external-relative-volume-reports/{report.report_id}"
    assert (
        client.get(path, headers={"Authorization": "Bearer other-org-fixture"}).status_code == 404
    )
    before = {p.name: p.read_bytes() for p in tmp_path.glob("*.jsonl")}
    assert (
        client.post(
            path + "/reviews",
            headers={"Authorization": f"Bearer {_TOKEN}"},
            json={"authorizedActorIds": ["operator-a"], "reviewedAt": _NOW.isoformat()},
        ).status_code
        == 422
    )
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.jsonl")} == before
    graph.close()


def test_startup_verifies_durable_owners_without_site_enumeration(tmp_path: Path):
    import pytest
    from ksi_core.external_reobservation_proposals import (
        ExternalReobservationProposalRecoveryError,
        verify_external_reobservation_graph,
    )
    from test_external_result_review_proposals import _harness

    harness = _harness(tmp_path)
    assert harness.service.reviews.organization_ids() == frozenset({"org-a"})
    assert harness.service.proposals.organization_ids() == frozenset()
    harness.source_port.source = None
    with pytest.raises(ExternalReobservationProposalRecoveryError):
        verify_external_reobservation_graph(service=harness.service)


def test_service_rejects_same_coordinator_but_different_durable_authority_graph(tmp_path: Path):
    from dataclasses import replace

    import pytest
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.external_reobservation_proposals import ExternalReobservationProposalStore
    from ksi_core.observation_work_orders import ObservationWorkOrderStore
    from test_external_result_review_proposals import _harness

    harness = _harness(tmp_path)
    other_proposals = ExternalReobservationProposalStore(
        DurableJournal(tmp_path / "other-proposals.jsonl"),
        coordinator=harness.service.coordinator,
    )
    with pytest.raises(ValueError, match="exact"):
        replace(harness.service, proposals=other_proposals)
    other_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "other-orders.jsonl"),
        site_exists=lambda *_: True,
    )
    with pytest.raises(ValueError, match="authority"):
        replace(harness.service, work_orders=other_orders)


def test_result_router_rejects_different_volume_store_with_shared_coordinator(tmp_path: Path):
    from datetime import timedelta

    import pytest
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.external_relative_volume_authorities import (
        DefaultClosedExternalRelativeVolumeAuthorityPort,
    )
    from ksi_core.external_relative_volumes import (
        ExternalRelativeVolumeQueuePolicy,
        ExternalRelativeVolumeStore,
    )

    graph = build_graph(tmp_path, seed_original(tmp_path))
    journal = DurableJournal(tmp_path / "other-volume.jsonl")
    try:
        other = ExternalRelativeVolumeStore(
            journal,
            authority_port=DefaultClosedExternalRelativeVolumeAuthorityPort(
                currentness_coordinator=graph.service.coordinator
            ),
            currentness_coordinator=graph.service.coordinator,
            queue_policy=ExternalRelativeVolumeQueuePolicy(
                lease_ttl=timedelta(seconds=5),
                deadline_after_issue=timedelta(seconds=30),
                max_attempts=1,
                max_active_requests_per_organization=2,
            ),
        )
        with pytest.raises(ValueError, match="exact volume store"):
            build_external_result_workflow_router(other, graph.service)
    finally:
        journal.close()
        graph.close()
