"""C2 final-review proof of inline/count parity and valid-reference route closure."""

from types import SimpleNamespace
from typing import Any

from test_external_result_review_proposals import _NOW, _principal
from test_oidc_external_detail_scope import _client
from test_oidc_external_history_scope import history  # noqa: F401 -- shared pytest fixture


def test_visible_inline_counts_match_and_direct_valid_workflow_refs_remain_closed(
    history: tuple[Any, ...],  # noqa: F811 -- imported pytest fixture
) -> None:
    graph, _, report, area = history
    actor = _principal()
    review = graph.service.reviews.review(
        organization_id="org-a", report_ref=report.report_id, principal=actor, evaluated_at=_NOW
    )
    proposal = graph.service.create(
        organization_id="org-a",
        report_ref=report.report_id,
        target_work_area_ids=(area,),
        reason="Verified follow-up",
        idempotency_key="detail-counts",
        principal=actor,
        actor=actor.principal_id,
        now=_NOW,
    )
    client, headers = _client(SimpleNamespace(graph=graph, single=None), area)
    with client:
        raw = client.get(
            f"/v1/external-relative-volume-reports/{report.report_id}", headers=headers
        )
        assert raw.status_code == 200, raw.text
        listing = client.get("/v1/sites/site-a/external-volume-reports", headers=headers)
        assert listing.status_code == 200, listing.text
        row = listing.json()["items"][0]["result"]
        assert row["proposalCount"] == len(raw.json()["proposals"]) == 1
        assert row["approvedProposalCount"] == 0
        assert raw.json()["proposals"][0]["approvalReceipt"] is None
        for path in (
            f"/v1/external-result-reviews/{review.review_ref}",
            f"/v1/external-reobservation-proposals/{proposal.proposal_ref}",
        ):
            assert client.get(path, headers=headers).status_code == 403
