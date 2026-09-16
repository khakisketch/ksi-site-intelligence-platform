"""External result briefings are deterministic, cited, idempotent and never block the mutation."""

from __future__ import annotations

from pathlib import Path

from external_product_loop_fixture import LoopGraph, build_graph, record_measurement, seed_original
from ksi_core.domains.external.workflow.external_result_briefings import (
    ExternalResultBriefingProjector,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_result_workflow_api import ExternalResultReadProjector
from ksi_core.site_workspace import SiteBriefingStore
from ksi_event_contracts.copilot import SiteBriefingStatus
from test_external_result_review_proposals import _NOW, _principal


def _projector(
    tmp_path: Path, graph: LoopGraph
) -> tuple[SiteBriefingStore, ExternalResultBriefingProjector]:
    briefings = SiteBriefingStore(
        DurableJournal(tmp_path / "site-briefings.jsonl"), site_store=graph.service.sites
    )
    read = ExternalResultReadProjector(
        volumes=graph.volumes, workflow=graph.service, clock=lambda: _NOW
    )
    projector = ExternalResultBriefingProjector(
        briefings=briefings, projector=read, work_areas=graph.service.work_areas, clock=lambda: _NOW
    )
    projector.bind(volumes=graph.volumes, reviews=graph.service.reviews, service=graph.service)
    return briefings, projector


def test_report_review_and_approval_each_record_one_cited_briefing(tmp_path: Path) -> None:
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    briefings, projector = _projector(tmp_path, graph)
    report = record_measurement(graph)
    assert projector.flush()

    first = briefings.latest("site-a", organization_id="org-a")
    assert first is not None and first.status is SiteBriefingStatus.READY
    assert first.source_watermark == f"external-report:{report.report_digest}:REPORTED"
    assert "순변화 4.0 m³" in first.what_changed
    assert "-0.0" not in first.what_changed
    assert "첫 결과" in first.why_it_matters
    assert first.decision_prompt == "결과와 근거를 검토하세요."
    assert {citation.source_path for citation in first.citations} == {
        f"/v1/external-relative-volume-reports/{report.report_id}",
        f"/v1/sites/site-a/observations/{report.report_id}",
    }

    principal = _principal()
    graph.service.reviews.review(
        organization_id="org-a", report_ref=report.report_id, principal=principal, evaluated_at=_NOW
    )
    assert projector.flush()
    reviewed = briefings.latest("site-a", organization_id="org-a")
    assert reviewed is not None and reviewed.source_watermark.endswith(":REVIEWED")
    assert reviewed.decision_prompt == "재관측이 필요하면 제안을 만들고 승인하세요."

    created = graph.service.create(
        organization_id="org-a",
        report_ref=report.report_id,
        target_work_area_ids=(source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=principal,
        actor=principal.principal_id,
        now=_NOW,
        idempotency_key="proposal-1",
    )
    approved = graph.service.approve(
        organization_id="org-a",
        proposal_ref=created.proposal_ref,
        expected_version=1,
        principal=principal,
        actor=principal.principal_id,
        now=_NOW,
        idempotency_key="approve-1",
    )
    assert projector.flush()
    done = briefings.latest("site-a", organization_id="org-a")
    assert done is not None and done.source_watermark.endswith(":APPROVED")
    assert approved.approval_receipt.successor_work_order_id in done.decision_prompt
    assert [item.briefing_id for item in briefings.latest_for_organization("org-a")] == [
        done.briefing_id
    ]
    assert briefings.latest_for_organization("org-b") == []
    graph.close()


def test_same_watermark_is_not_recorded_twice(tmp_path: Path) -> None:
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    briefings, projector = _projector(tmp_path, graph)
    report = record_measurement(graph)
    record = graph.volumes.get(report.request_id, organization_id="org-a")
    assert record is not None
    projector.on_report(record)  # duplicate delivery
    assert projector.flush()
    journal = (tmp_path / "site-briefings.jsonl").read_text().strip().splitlines()
    assert len(journal) == 1
    assert briefings.latest("site-a", organization_id="org-a") is not None
    graph.close()
