"""Post-commit listeners fire once per new report/review/approval and never break the mutation."""

from __future__ import annotations

from pathlib import Path

from external_product_loop_fixture import build_graph, record_measurement, seed_original
from test_external_result_review_proposals import _NOW, _principal


def test_report_review_and_approval_listeners_fire_once_and_isolate_failures(
    tmp_path: Path,
) -> None:
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    reports: list[str] = []
    reviews: list[str] = []
    approvals: list[str] = []

    def failing(_record: object) -> None:
        raise RuntimeError("projection failed")

    graph.volumes.bind_report_listener(failing)
    graph.volumes.bind_report_listener(lambda record: reports.append(record.report.report_id))
    graph.volumes.bind_report_listener(failing)  # duplicate binding is ignored
    graph.service.reviews.bind_review_listener(lambda receipt: reviews.append(receipt.review_ref))
    graph.service.bind_approval_listener(
        lambda receipt: approvals.append(receipt.successor_work_order_id)
    )

    report = record_measurement(graph)
    assert reports == [report.report_id]

    principal = _principal()
    receipt = graph.service.reviews.review(
        organization_id="org-a", report_ref=report.report_id, principal=principal, evaluated_at=_NOW
    )
    again = graph.service.reviews.review(
        organization_id="org-a", report_ref=report.report_id, principal=principal, evaluated_at=_NOW
    )
    assert again == receipt and reviews == [receipt.review_ref]

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
    retry = graph.service.approve(
        organization_id="org-a",
        proposal_ref=created.proposal_ref,
        expected_version=1,
        principal=principal,
        actor=principal.principal_id,
        now=_NOW,
        idempotency_key="approve-1",
    )
    successor = approved.approval_receipt.successor_work_order_id
    assert retry.approval_receipt.successor_work_order_id == successor
    assert approvals == [successor]
    graph.close()
