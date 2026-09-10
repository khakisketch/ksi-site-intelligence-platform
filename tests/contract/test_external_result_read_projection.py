"""External results stay separate from managed projections and Copilot tools."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from external_product_loop_fixture import LoopGraph, build_graph, record_measurement, seed_original
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, mount_auth
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_reconstruction import (
    ExternalReconstructionStore,
    mount_external_reconstruction,
)
from ksi_core.external_relative_volumes import (
    ExternalRelativeVolumeVerdict,
    ResolvedRelativeVolumeReport,
)
from ksi_core.external_result_workflow_api import ExternalResultReadProjector
from ksi_core.external_use_decisions import ExternalDecisionIntent
from ksi_core.observation_work_orders import ExternalReobservationApprovalResult
from ksi_core.site_workspace import SiteWorkspaceProjector, build_workspace_copilot_handlers
from ksi_event_contracts.external_relative_volume import ExternalRelativeVolumeReportV1
from ksi_event_contracts.external_result_review import (
    ExternalReobservationProposalV1,
    ExternalResultReviewReceiptV1,
)
from test_external_relative_volumes import _fence
from test_external_result_review_proposals import _NOW, _TOKEN, _principal, _token_record


def _review_and_approve(
    graph: LoopGraph, report: ExternalRelativeVolumeReportV1
) -> tuple[
    ExternalResultReviewReceiptV1,
    ExternalReobservationProposalV1,
    ExternalReobservationApprovalResult,
]:
    review = graph.service.reviews.review(
        organization_id="org-a",
        report_ref=report.report_id,
        principal=_principal(),
        evaluated_at=_NOW,
    )
    proposal = graph.service.create(
        organization_id="org-a",
        report_ref=report.report_id,
        target_work_area_ids=(graph.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="read-projection-proposal",
    )
    approval = graph.service.approve(
        organization_id="org-a",
        proposal_ref=proposal.proposal_ref,
        expected_version=proposal.version,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="read-projection-approval",
    )
    return review, proposal, approval


def test_external_result_projection_joins_exact_source_successor_and_site_without_managed_promotion(
    tmp_path: Path,
) -> None:
    graph = build_graph(tmp_path, seed_original(tmp_path))
    try:
        report = record_measurement(graph)
        review, proposal, approval = _review_and_approve(graph, report)
        projector = ExternalResultReadProjector(
            volumes=graph.volumes,
            workflow=graph.service,
            clock=lambda: _NOW,
        )

        source = projector.for_work_order(
            graph.source.authority.current_work_order_id, organization_id="org-a"
        )
        successor = projector.for_work_order(
            approval.successor_work_order.work_order_id, organization_id="org-a"
        )
        site = projector.for_site("site-a", organization_id="org-a")

        assert source.state == "AVAILABLE"
        assert source.result is not None
        assert source.result.report_ref == report.report_id
        assert source.result.report_digest == report.report_digest
        assert source.result.request_ref == report.request_id
        assert source.result.source_work_order_id == graph.source.authority.current_work_order_id
        assert source.result.current_work_order_id == graph.source.authority.current_work_order_id
        assert (
            source.result.baseline_work_order_id
            == graph.source.authority.baseline.subject.work_order_id
        )
        assert source.result.decision_digest == graph.source.decision.decision_digest
        assert (
            source.result.zone_definition_digest
            == graph.source.authority.zone_snapshot.definition_digest
        )
        assert source.result.measurement_status == "SUCCEEDED"
        assert source.result.measurement_reason is None
        assert source.result.metrics is not None
        assert source.result.metrics.net_m3 == 4.0
        assert source.result.review_ref == review.review_ref
        assert source.result.review_digest == review.review_digest
        assert source.result.proposal_count == 1
        assert source.result.approved_proposal_count == 1
        assert successor.state == "AVAILABLE"
        assert successor.result == source.result
        assert site.state == "AVAILABLE"
        assert site.result == source.result

        workspace = SiteWorkspaceProjector(
            site_store=graph.service.sites,
            work_order_store=graph.service.work_orders,
            processing_job_store=None,
            event_store=None,
            external_results=projector,
        ).project("site-a", organization_id="org-a")
        assert workspace.latest_analysis.status == "UNAVAILABLE"
        assert workspace.latest_observation_at is None
        assert workspace.external_result == source
    finally:
        graph.close()


def test_external_result_context_reads_the_exact_source_and_successor_reports(
    tmp_path: Path,
) -> None:
    graph = build_graph(tmp_path, seed_original(tmp_path))
    reconstruction_journal = DurableJournal(tmp_path / "reconstruction.jsonl")
    try:
        report = record_measurement(graph)
        _, _, approval = _review_and_approve(graph, report)
        app = FastAPI()
        mount_auth(app, AuthRegistry([_token_record()]))
        mount_external_reconstruction(
            app,
            ExternalReconstructionStore(
                reconstruction_journal, coordinator=graph.service.coordinator
            ),
            work_orders=graph.service.work_orders,
            storage=object(),
            external_results=ExternalResultReadProjector(
                volumes=graph.volumes,
                workflow=graph.service,
                clock=lambda: _NOW,
            ),
        )
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {_TOKEN}"}
            source = client.get(
                "/v1/observation-work-orders/"
                f"{graph.source.authority.current_work_order_id}/external-reconstruction-context",
                headers=headers,
            )
            successor = client.get(
                "/v1/observation-work-orders/"
                f"{approval.successor_work_order.work_order_id}/external-reconstruction-context",
                headers=headers,
            )
        assert source.status_code == successor.status_code == 200
        assert source.json()["externalResult"]["result"]["reportRef"] == report.report_id
        assert successor.json()["externalResult"] == source.json()["externalResult"]
    finally:
        reconstruction_journal.close()
        graph.close()


def test_external_result_projection_fails_closed_when_historical_source_is_unavailable(
    tmp_path: Path,
) -> None:
    graph = build_graph(tmp_path, seed_original(tmp_path))
    try:
        report = record_measurement(graph)
        graph.authority_port.historical_authority = replace(
            graph.history.authority, decision_id="historical-source-withdrawn"
        )
        projector = ExternalResultReadProjector(
            volumes=graph.volumes,
            workflow=graph.service,
            clock=lambda: _NOW + timedelta(seconds=1),
        )

        result = projector.for_work_order(
            graph.source.authority.current_work_order_id, organization_id="org-a"
        )

        assert result.state == "HISTORICAL_SOURCE_UNAVAILABLE"
        assert result.result is None
        assert projector.citation_for(result, site_name="Synthetic site") is None
        with pytest.raises(LookupError):
            projector.for_work_order(
                graph.source.authority.current_work_order_id, organization_id="org-b"
            )
        assert projector.for_site("site-a", organization_id="org-a").result is None
        assert report.report_id
    finally:
        graph.close()


def test_external_result_projection_keeps_historically_resolved_report_after_live_expiry(
    tmp_path: Path,
) -> None:
    graph = build_graph(tmp_path, seed_original(tmp_path))
    try:
        report = record_measurement(graph)
        graph.authority_port.authority = replace(
            graph.authority_port.authority,
            valid_until=_NOW - timedelta(seconds=1),
        )
        projection = ExternalResultReadProjector(
            volumes=graph.volumes,
            workflow=graph.service,
            clock=lambda: _NOW + timedelta(seconds=1),
        ).for_work_order(graph.source.authority.current_work_order_id, organization_id="org-a")

        assert projection.state == "AVAILABLE"
        assert projection.result is not None
        assert projection.result.report_ref == report.report_id
    finally:
        graph.close()


def test_site_projection_does_not_fall_back_when_retained_latest_lacks_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = build_graph(tmp_path, seed_original(tmp_path))
    try:
        report = record_measurement(graph)
        latest_ref = "retained-latest-without-historical-source"
        resolved_refs: list[str] = []
        resolve = graph.volumes.resolve_historical_report_ref
        monkeypatch.setattr(
            graph.volumes,
            "report_refs_for_site",
            lambda _site_id, *, organization_id: (latest_ref, report.report_id),
        )

        def resolve_with_retained_latest(
            ref: str, *, organization_id: str, now: datetime
        ) -> ResolvedRelativeVolumeReport | None:
            resolved_refs.append(ref)
            if ref == latest_ref:
                return None
            return resolve(ref, organization_id=organization_id, now=now)

        monkeypatch.setattr(
            graph.volumes,
            "resolve_historical_report_ref",
            resolve_with_retained_latest,
        )
        projection = ExternalResultReadProjector(
            volumes=graph.volumes,
            workflow=graph.service,
            clock=lambda: _NOW,
        ).for_site("site-a", organization_id="org-a")

        assert projection.state == "HISTORICAL_SOURCE_UNAVAILABLE"
        assert projection.result is None
        assert resolved_refs == [latest_ref]
    finally:
        graph.close()


def test_external_result_projection_excludes_incomplete_coverage_without_a_numeric_result(
    tmp_path: Path,
) -> None:
    graph = build_graph(tmp_path, seed_original(tmp_path))
    try:
        graph.decisions.stage_evaluated(
            graph.source.decision,
            intent=ExternalDecisionIntent.from_candidate(graph.source.decision),
            principal=_principal(),
            idempotency_key="read-projection-failed-decision",
        )
        graph.decisions.reconcile_pending()
        issued = graph.volumes.issue(
            principal=_principal(),
            current_work_order_id=graph.source.authority.current_work_order_id,
            decision_ref=graph.source.decision.decision_id,
            idempotency_key="read-projection-failed-volume",
            now=_NOW,
        )
        assert issued.record is not None
        fence = _fence()
        assert graph.volumes.claim(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker",
            fence=fence,
            now=_NOW,
        ).verdict is ExternalRelativeVolumeVerdict.LEASED
        assert graph.volumes.record_incomplete_failure(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="worker",
            fence=fence,
            reason="NO_COMMON_COVERAGE",
            now=_NOW,
        ).verdict is ExternalRelativeVolumeVerdict.FAILED

        projector = ExternalResultReadProjector(
            volumes=graph.volumes,
            workflow=graph.service,
            clock=lambda: _NOW,
        )
        projection = projector.for_work_order(
            graph.source.authority.current_work_order_id, organization_id="org-a"
        )
        assert projection.state == "NO_RESULT"
        assert projection.result is None
        assert projector.citation_for(projection, site_name="Synthetic site") is None
    finally:
        graph.close()


def test_workspace_copilot_handlers_expose_only_exact_external_report_citation(
    tmp_path: Path,
) -> None:
    graph = build_graph(tmp_path, seed_original(tmp_path))
    try:
        report = record_measurement(graph)
        projector = ExternalResultReadProjector(
            volumes=graph.volumes,
            workflow=graph.service,
            clock=lambda: _NOW,
        )
        workspace = SiteWorkspaceProjector(
            site_store=graph.service.sites,
            work_order_store=graph.service.work_orders,
            processing_job_store=None,
            event_store=None,
            external_results=projector,
        )
        handlers = build_workspace_copilot_handlers(workspace, graph.service.work_orders)

        snapshot = handlers["site_snapshot"]("org-a", "site-a", None, {})
        latest = handlers["latest_progress"]("org-a", "site-a", None, {})
        evidence = handlers["evidence_index"](
            "org-a", "site-a", None, {"objectIds": [report.report_id]}
        )
        invented = handlers["evidence_index"]("org-a", "site-a", None, {"objectIds": ["invented"]})

        assert set(handlers) == {"site_snapshot", "latest_progress", "evidence_index"}
        assert latest.data["externalResult"]["state"] == "AVAILABLE"
        assert report.report_digest is not None
        assert latest.citations[0].citation_id == (
            f"external-relative-volume-report:{report.report_id}:{report.report_digest.removeprefix('sha256:')}"
        )
        assert latest.citations[0].object_type == "EXTERNAL_RELATIVE_VOLUME_REPORT"
        assert latest.citations[0].source_path == (
            f"/v1/external-relative-volume-reports/{report.report_id}"
        )
        assert latest.citations[0].uncertainty_summary is not None
        assert len(latest.citations[0].uncertainty_summary) <= 500
        assert snapshot.citations[-1] == latest.citations[0]
        assert evidence.citations == latest.citations
        assert invented.citations == ()
    finally:
        graph.close()
