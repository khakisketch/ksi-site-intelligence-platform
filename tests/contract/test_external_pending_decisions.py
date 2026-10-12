"""AX-4: external results that wait for a person, computed by Core from its ledgers."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

from external_product_loop_fixture import record_measurement
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, mount_auth
from ksi_core.domains.external.workflow.external_result_projection_models import (
    ExternalPendingDecisionItem,
)
from ksi_core.external_result_workflow_api import (
    ExternalResultReadProjector,
    build_external_result_workflow_router,
)
from ksi_event_contracts.external_result_review import ExternalReobservationProposalV1
from test_external_result_review_proposals import _NOW, _TOKEN, _principal, _token_record
from test_external_result_single_volume_projection import (  # noqa: F401 - pytest fixture
    _SITE,
    _Harness,
    _http_client,
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


def _propose(h: _Harness, report_ref: str, key: str) -> ExternalReobservationProposalV1:
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


def _pending(h: _Harness, organization_id: str = "org-a") -> list[ExternalPendingDecisionItem]:
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


def test_pending_route_is_authenticated_and_organization_scoped(harness: _Harness) -> None:  # noqa: F811
    report = record_measurement(harness.graph)
    path = "/v1/external-decisions/pending"
    with _http_client(harness) as client:
        assert client.get(path).status_code == 401
        mine = client.get(path, headers={"Authorization": f"Bearer {_TOKEN}"})
        assert mine.status_code == 200, mine.text
        body = mine.json()
        assert [(i["siteId"], i["reportRef"], i["stage"]) for i in body["items"]] == [
            ("site-a", report.report_id, "AWAITING_REVIEW")
        ]
        assert set(body["items"][0]) == {
            "siteId",
            "reportRef",
            "kind",
            "stage",
            "reportedAt",
            "netM3",
            "uncertaintyM3",
            "workAreaId",
        }
        other = client.get(path, headers={"Authorization": "Bearer other-org-fixture"})
        assert other.status_code == 200
        assert other.json() == {"items": []}


def test_pending_decisions_http_filters_rows_for_mapped_grants(harness: _Harness) -> None:  # noqa: F811
    """mapped OIDC 신원은 grant 밖 검토 대기 행을 HTTP 목록에서 받지 않는다."""
    from test_oidc_route_scope import _install_oidc_v2

    report = record_measurement(harness.graph)
    app = FastAPI()
    mount_auth(app, AuthRegistry([_token_record()]))
    app.include_router(
        build_external_result_workflow_router(
            harness.graph.volumes,
            harness.graph.service,
            single_volumes=harness.single,
            clock=lambda: _NOW,
        )
    )
    scoped = SimpleNamespace(app=app, organization_id="org-a")
    with TestClient(app) as client:
        # Legacy opaque 신원은 기존 조직 전체 목록을 유지한다.
        legacy = client.get(
            "/v1/external-decisions/pending",
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        assert legacy.status_code == 200, legacy.text
        assert [item["reportRef"] for item in legacy.json()["items"]] == [report.report_id]

        granted_token, _key = _install_oidc_v2(
            scoped, capabilities=[], site_ids=[_SITE], area_ids=None
        )
        granted = client.get(
            "/v1/external-decisions/pending",
            headers={"Authorization": f"Bearer {granted_token}"},
        )
        assert granted.status_code == 200, granted.text
        assert [item["reportRef"] for item in granted.json()["items"]] == [report.report_id]

        ungranted_token, _key = _install_oidc_v2(
            scoped, capabilities=[], site_ids=["site-ungranted"], area_ids=None
        )
        ungranted = client.get(
            "/v1/external-decisions/pending",
            headers={"Authorization": f"Bearer {ungranted_token}"},
        )
        assert ungranted.status_code == 200, ungranted.text
        assert ungranted.json()["items"] == []

        cross_org_token, _key = _install_oidc_v2(
            scoped,
            capabilities=[],
            site_ids=[_SITE],
            area_ids=None,
            organization_id="org-b",
        )
        cross_org = client.get(
            "/v1/external-decisions/pending",
            headers={"Authorization": f"Bearer {cross_org_token}"},
        )
        assert cross_org.status_code == 200, cross_org.text
        assert cross_org.json()["items"] == []
