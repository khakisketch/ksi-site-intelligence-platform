"""AX-4: external results that wait for a person, computed by Core from its ledgers."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from external_product_loop_fixture import record_measurement
from ksi_core.external_result_workflow_api import ExternalResultReadProjector
from test_external_result_review_proposals import _NOW, _principal
from test_external_result_single_volume_projection import (  # noqa: F401 - pytest fixture
    _Harness,
    _record_second_relative,
    _record_single,
    harness,
)


def _review(h: _Harness, report_ref: str) -> None:
    h.graph.service.reviews.review(
        organization_id="org-a",
        report_ref=report_ref,
        principal=_principal(),
        evaluated_at=_NOW,
    )


def _propose(h: _Harness, report_ref: str, key: str):
    return h.graph.service.create(
        organization_id="org-a",
        report_ref=report_ref,
        target_work_area_ids=(h.graph.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key=key,
    )


def _pending(h: _Harness, organization_id: str = "org-a"):
    return h.projector().pending_decisions(organization_id=organization_id).items


def test_reported_result_waits_for_review_then_leaves_after_review(harness: _Harness) -> None:  # noqa: F811
    report = record_measurement(harness.graph)

    pending = _pending(harness)

    assert [(i.site_id, i.report_ref, i.stage) for i in pending] == [
        ("site-a", report.report_id, "AWAITING_REVIEW")
    ]
    assert pending[0].kind == "EXTERNAL_RELATIVE_VOLUME"
    assert pending[0].net_m3 == 4.0
    assert pending[0].reported_at == report.reported_at
    assert pending[0].work_area_id == harness.graph.source.authority.zone_snapshot.work_area_id

    _review(harness, report.report_id)

    assert _pending(harness) == []


def test_unapproved_proposal_waits_for_approval_and_leaves_after_approval(
    harness: _Harness,  # noqa: F811
) -> None:
    report = record_measurement(harness.graph)
    _review(harness, report.report_id)
    proposal = _propose(harness, report.report_id, "pending-approval-proposal")

    assert [(i.report_ref, i.stage) for i in _pending(harness)] == [
        (report.report_id, "AWAITING_APPROVAL")
    ]

    harness.graph.service.approve(
        organization_id="org-a",
        proposal_ref=proposal.proposal_ref,
        expected_version=proposal.version,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="pending-approval-approval",
    )

    assert _pending(harness) == []


def test_one_item_per_site_and_review_wait_ranks_before_approval_wait(
    harness: _Harness,  # noqa: F811
) -> None:
    relative = record_measurement(harness.graph)
    _review(harness, relative.report_id)
    _propose(harness, relative.report_id, "rank-proposal")
    single = _record_single(harness)

    pending = _pending(harness)

    assert [(i.site_id, i.report_ref, i.stage, i.kind) for i in pending] == [
        ("site-a", single.report_id, "AWAITING_REVIEW", "EXTERNAL_SINGLE_VOLUME")
    ]


def test_longest_waiting_unreviewed_report_is_chosen(harness: _Harness) -> None:  # noqa: F811
    first = record_measurement(harness.graph)
    second = _record_second_relative(harness)
    expected = min((first, second), key=lambda report: (report.reported_at, report.report_id))

    assert [i.report_ref for i in _pending(harness)] == [expected.report_id]


def test_other_organization_sees_nothing(harness: _Harness) -> None:  # noqa: F811
    record_measurement(harness.graph)

    assert _pending(harness, organization_id="org-b") == []


def test_unavailable_historical_source_is_skipped_not_guessed(harness: _Harness) -> None:  # noqa: F811
    record_measurement(harness.graph)
    graph = harness.graph
    graph.authority_port.historical_authority = replace(
        graph.history.authority, decision_id="historical-source-withdrawn"
    )
    projector = ExternalResultReadProjector(
        volumes=graph.volumes,
        workflow=graph.service,
        clock=lambda: _NOW + timedelta(seconds=1),
    )

    assert projector.pending_decisions(organization_id="org-a").items == []
