"""Customer history scope regressions on real durable report/work-order graphs."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from external_product_loop_fixture import POLYGON, build_graph, record_measurement, seed_original
from external_single_volume_fixture import _AuthorityPort, _store
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, HumanAuthMode, Principal, PrincipalKind, Role, mount_auth
from ksi_core.external_reobservation_proposals import build_external_reobservation_proposal_router
from ksi_core.external_result_workflow_api import (
    ExternalResultReadProjector,
    build_external_result_workflow_router,
)
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig
from test_external_result_review_proposals import _NOW, _TOKEN, _sealed_source, _token_record
from test_external_result_single_volume_projection import (
    _Harness,
    _record_second_relative,
    _record_single,
    _single_authority,
)
from test_oidc_external_evidence_scope import _AUDIENCE, _ISSUER, _jwk, _token


def _principal(area: str, *, sites: frozenset[str] = frozenset({"site-a"})) -> Principal:
    return Principal(
        principal_id="customer-a", organization_id="org-a",
        kind=PrincipalKind.OPERATOR, role=Role.FIELD_OPERATOR, device_id=None,
        allowed_site_ids=sites, allowed_work_area_ids=frozenset({area}),
    )


@pytest.fixture
def history(tmp_path: Path, request):
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    area = source.authority.zone_snapshot.work_area_id
    current_id = source.authority.current_work_order_id
    source_areas = {"baseline": [area], "current": [area]}
    if hasattr(request, "param"):
        owner, assigned = request.param
        extra = graph.service.work_areas.register(
            "site-a", name="Unassigned zone", polygon=POLYGON, crs="EPSG:5186",
            supersedes=None, actor="operator-a", now=_NOW,
        ).work_area
        assert extra is not None
        source_areas[owner] = [
            area if value == "zone" else extra.work_area_id for value in assigned
        ]
        if owner == "current":
            current_id = graph.service.work_orders.create_work_order(
                organization_id="org-a", site_id="site-a", name="Current scoped source",
                work_area_ids=source_areas["current"], schedule_id=None,
                actor="operator-a", now=_NOW,
            ).work_order_id
    baseline = graph.service.work_orders.create_work_order(
        organization_id="org-a", site_id="site-a", name="Baseline",
        work_area_ids=source_areas["baseline"], schedule_id=None, actor="operator-a", now=_NOW,
    )
    graph.close()
    source = _sealed_source(
        source_work_order_id=current_id,
        baseline_work_order_id=baseline.work_order_id, work_area_id=area, polygon=POLYGON,
    )
    graph = build_graph(tmp_path, source)
    report = record_measurement(graph)
    projector = ExternalResultReadProjector(volumes=graph.volumes, workflow=graph.service,
                                            clock=lambda: _NOW)
    try:
        yield graph, projector, report, area
    finally:
        graph.close()


def test_scoped_history_returns_exact_bound_report(history) -> None:
    _, projector, report, area = history
    page = projector.history_for_site("site-a", organization_id="org-a", after=None, limit=20,
                                      principal=_principal(area))
    assert [row.report_ref for row in page.items] == [report.report_id]
    assert page.items[0].result.metrics.net_m3 == 4


@pytest.mark.parametrize("sites", [frozenset(), frozenset({"site-b"})])
def test_ungranted_site_is_not_found(history, sites) -> None:
    _, projector, _, area = history
    with pytest.raises(LookupError):
        projector.history_for_site("site-a", organization_id="org-a", after=None, limit=20,
                                    principal=_principal(area, sites=sites))


def test_hidden_report_is_not_an_unavailable_placeholder_or_cursor(history) -> None:
    _, projector, report, _ = history
    principal = _principal("ungranted-area")
    page = projector.history_for_site("site-a", organization_id="org-a", after=None, limit=1,
                                      principal=principal)
    assert page.items == [] and page.next_cursor is None
    with pytest.raises(LookupError):
        projector.history_for_site("site-a", organization_id="org-a", after=report.report_id,
                                    limit=1, principal=principal)


def test_missing_baseline_binding_hides_report(history, tmp_path: Path) -> None:
    graph, _, _, area = history
    # A distinct real graph with the legacy fixture's nonexistent baseline, not a mocked resolver.
    root = tmp_path / "missing-baseline"
    root.mkdir()
    source = seed_original(root)
    other = build_graph(root, source)
    try:
        record_measurement(other)
        projector = ExternalResultReadProjector(volumes=other.volumes, workflow=other.service,
                                                clock=lambda: _NOW)
        page = projector.history_for_site("site-a", organization_id="org-a", after=None, limit=20,
                                          principal=_principal(area))
        assert page.items == []
    finally:
        other.close()


def test_organization_argument_cannot_override_principal(history) -> None:
    _, projector, _, area = history
    with pytest.raises(LookupError):
        projector.history_for_site("site-a", organization_id="org-a", after=None, limit=20,
                                    principal=replace(_principal(area), organization_id="org-b"))


def test_unrestricted_existing_history_is_unchanged(history) -> None:
    _, projector, report, _ = history
    page = projector.history_for_site("site-a", organization_id="org-a", after=None, limit=20)
    assert [row.report_ref for row in page.items] == [report.report_id]


def test_scoped_history_proposals_cannot_target_another_zone(history: Any) -> None:
    graph, projector, report, area = history
    extra = graph.service.work_areas.register(
        "site-a", name="Other zone", polygon=POLYGON, crs="EPSG:5186",
        supersedes=None, actor="operator-a", now=_NOW,
    ).work_area
    assert extra is not None
    app = FastAPI()
    mount_auth(app, AuthRegistry([_token_record()]))
    app.include_router(build_external_result_workflow_router(
        graph.volumes, graph.service, clock=lambda: _NOW
    ))
    app.include_router(build_external_reobservation_proposal_router(
        graph.service, clock=lambda: _NOW
    ))
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    with TestClient(app) as client:
        assert client.post(
            f"/v1/external-relative-volume-reports/{report.report_id}/reviews", headers=headers
        ).status_code == 201
        response = client.post(
            "/v1/external-reobservation-proposals",
            headers={**headers, "Idempotency-Key": "hidden-proposal"},
            json={"reportRef": report.report_id, "targetWorkAreaIds": [extra.work_area_id]},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "EXTERNAL_REOBSERVATION_TARGET_NOT_REPORT_ZONE"
        visible = client.post(
            "/v1/external-reobservation-proposals",
            headers={**headers, "Idempotency-Key": "visible-proposal"},
            json={"reportRef": report.report_id, "targetWorkAreaIds": [area]},
        )
        assert visible.status_code == 201, visible.text
    full = projector.history_for_site("site-a", organization_id="org-a", after=None, limit=20)
    scoped = projector.history_for_site("site-a", organization_id="org-a", after=None, limit=20,
                                        principal=_principal(area))
    assert full.items[0].result.proposal_count == 1
    assert scoped.items[0].result.proposal_count == 1
    assert scoped.items[0].result.approved_proposal_count == 0
    assert scoped.items[0].result.metrics == full.items[0].result.metrics


def test_archived_zone_keeps_granted_history_readable(history: Any) -> None:
    graph, projector, report, area = history
    graph.service.work_areas.archive(area, site_id="site-a", actor="operator-a", now=_NOW)
    page = projector.history_for_site("site-a", organization_id="org-a", after=None, limit=20,
                                      principal=_principal(area))
    assert [row.report_ref for row in page.items] == [report.report_id]


@pytest.fixture
def customer_http(history):
    graph, _, report, area = history
    key = generate_private_key(public_exponent=65537, key_size=2048)
    app = FastAPI()
    mount_auth(app, AuthRegistry([]))
    app.include_router(build_external_result_workflow_router(
        graph.volumes, graph.service, clock=lambda: _NOW
    ))
    rows = []
    for subject, org, sites, areas, status in (
        ("granted", "org-a", ["site-a"], [area], "ACTIVE"),
        ("no-areas", "org-a", ["site-a"], [], "ACTIVE"),
        ("no-sites", "org-a", [], [area], "ACTIVE"),
        ("other-area", "org-a", ["site-a"], ["other-area"], "ACTIVE"),
        ("foreign", "org-b", ["site-a"], [area], "ACTIVE"),
        ("revoked", "org-a", ["site-a"], [area], "REVOKED"),
    ):
        rows.append({
            "issuer": _ISSUER, "subject": subject, "principalId": subject,
            "organizationId": org, "role": "FIELD_OPERATOR", "status": status,
            "allowedSiteIds": sites, "allowedWorkAreaIds": areas,
        })
    app.state.human_auth_mode = HumanAuthMode.OIDC
    app.state.oidc_verifier = OidcJwtVerifier(
        OidcVerifierConfig(issuer=_ISSUER, audience=_AUDIENCE, jwks_url=f"{_ISSUER}/jwks.json"),
        fetch_jwks=lambda: {"keys": [_jwk(key)]},
        subject_registry=OidcSubjectRegistry.from_document(
            {"version": "oidc-subject-registry.v1", "subjects": rows}, expected_issuer=_ISSUER
        ),
    )
    headers = {subject: {"Authorization": f"Bearer {_token(key, subject)}"} for subject in (
        "granted", "no-areas", "no-sites", "other-area", "foreign", "revoked"
    )}
    with TestClient(app) as client:
        yield client, headers, report


def test_signed_customer_reads_history_with_original_metrics(customer_http) -> None:
    client, headers, report = customer_http
    response = client.get("/v1/sites/site-a/external-volume-reports", headers=headers["granted"])
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["reportRef"] == report.report_id
    assert item["state"] == "AVAILABLE"
    assert item["result"]["metrics"]["netM3"] == 4
    assert item["result"]["baselineWorkOrderId"] != "work-baseline"
    assert response.json()["nextCursor"] is None


@pytest.mark.parametrize("subject", ["no-areas", "other-area"])
def test_signed_customer_cannot_enumerate_hidden_rows_or_cursors(customer_http, subject) -> None:
    client, headers, report = customer_http
    path = "/v1/sites/site-a/external-volume-reports"
    response = client.get(path, headers=headers[subject])
    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "nextCursor": None}
    hidden = client.get(path, params={"after": report.report_id}, headers=headers[subject])
    missing = client.get(path, params={"after": "missing"}, headers=headers[subject])
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


@pytest.mark.parametrize("subject,site", [
    ("no-sites", "site-a"), ("foreign", "site-a"), ("granted", "site-other"),
])
def test_signed_site_scope_denial_is_same_not_found(customer_http, subject, site) -> None:
    client, headers, _ = customer_http
    response = client.get(f"/v1/sites/{site}/external-volume-reports", headers=headers[subject])
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "EXTERNAL_VOLUME_REPORT_NOT_FOUND"}


def test_revoked_or_missing_auth_never_reads_history(customer_http) -> None:
    client, headers, _ = customer_http
    path = "/v1/sites/site-a/external-volume-reports"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers["revoked"]).status_code == 401


@pytest.mark.parametrize("path", [
    "/v1/external-decisions/pending",
    "/v1/sites/site-a/external-relative-volume-reports",
])
def test_adjacent_unaudited_reads_stay_closed(customer_http, path) -> None:
    client, headers, _ = customer_http
    assert client.get(path, headers=headers["granted"]).status_code == 403


def test_v1_mutation_and_report_detail_stay_closed(customer_http) -> None:
    client, headers, report = customer_http
    path = f"/v1/external-relative-volume-reports/{report.report_id}"
    assert client.get(path, headers=headers["granted"]).status_code == 403
    assert client.post(path + "/reviews", headers=headers["granted"]).status_code == 403


@pytest.fixture
def mixed_history(history, tmp_path: Path):
    graph, _, first, area = history
    port = _AuthorityPort(
        _single_authority(graph, captured_to=_NOW + timedelta(hours=4)),
        coordinator=graph.service.coordinator,
    )
    single = _store(tmp_path, port, now=_NOW)
    harness = _Harness(graph, port, single)
    try:
        single_report = _record_single(harness)
        latest = _record_second_relative(harness)
        yield harness, first, single_report, latest, area
    finally:
        single._journal.close()  # noqa: SLF001 -- test owns this real journal


def test_mixed_family_scoped_pagination_preserves_exact_order(mixed_history) -> None:
    harness, first, single, latest, area = mixed_history
    projector = harness.projector()
    principal = _principal(area)
    page = projector.history_for_site("site-a", organization_id="org-a", after=None, limit=1,
                                      principal=principal)
    assert [row.report_ref for row in page.items] == [latest.report_id]
    assert page.next_cursor == latest.report_id
    page2 = projector.history_for_site("site-a", organization_id="org-a", after=page.next_cursor,
                                       limit=1, principal=principal)
    assert [row.report_ref for row in page2.items] == [single.report_id]
    assert page2.items[0].result.kind == "EXTERNAL_SINGLE_VOLUME"
    assert page2.items[0].result.baseline_work_order_id is None
    assert page2.next_cursor == single.report_id
    last = projector.history_for_site("site-a", organization_id="org-a", after=page2.next_cursor,
                                      limit=1, principal=principal)
    assert [row.report_ref for row in last.items] == [first.report_id]
    assert last.next_cursor is None
    hidden = projector.history_for_site("site-a", organization_id="org-a", after=None, limit=1,
                                        principal=_principal("other-area"))
    assert hidden.items == [] and hidden.next_cursor is None


def test_provider_resolution_stops_at_page_plus_visible_lookahead(
    mixed_history, monkeypatch
) -> None:
    harness, _, _, latest, area = mixed_history
    # Instrument only the independent authority boundary, keep real stores/projections/joins.
    port = harness.graph.authority_port
    resolve = port.resolve_historical
    seen = []

    def observed(**kwargs):
        seen.append(kwargs["historical_authority_digest"])
        return resolve(**kwargs)

    monkeypatch.setattr(port, "resolve_historical", observed)
    page = harness.projector().history_for_site(
        "site-a", organization_id="org-a", after=None, limit=1, principal=_principal(area)
    )
    assert [row.report_ref for row in page.items] == [latest.report_id]
    assert harness.graph.source.authority.historical_authority_digest not in seen


def test_valid_cursor_skips_preceding_reports_without_provider_calls(mixed_history, monkeypatch):
    harness, first, single, _, area = mixed_history
    port = harness.graph.authority_port
    resolve = port.resolve_historical
    seen = []

    def observed(**kwargs):
        seen.append(kwargs["historical_authority_digest"])
        return resolve(**kwargs)

    monkeypatch.setattr(port, "resolve_historical", observed)
    page = harness.projector().history_for_site(
        "site-a", organization_id="org-a", after=single.report_id, limit=1,
        principal=_principal(area),
    )
    assert [row.report_ref for row in page.items] == [first.report_id]
    assert set(seen) == {harness.graph.source.authority.historical_authority_digest}


def test_hidden_single_family_row_does_not_consume_page_or_create_cursor(mixed_history) -> None:
    harness, first, single, latest, area = mixed_history
    harness.port.authority = replace(harness.port.authority, decision_id="withdrawn-history")
    projector = harness.projector()
    principal = _principal(area)
    page = projector.history_for_site(
        "site-a", organization_id="org-a", after=None, limit=1, principal=principal
    )
    assert [row.report_ref for row in page.items] == [latest.report_id]
    assert page.next_cursor == latest.report_id
    last = projector.history_for_site(
        "site-a", organization_id="org-a", after=latest.report_id, limit=1, principal=principal
    )
    assert [row.report_ref for row in last.items] == [first.report_id]
    assert last.next_cursor is None
    with pytest.raises(LookupError):
        projector.history_for_site(
            "site-a", organization_id="org-a", after=single.report_id, limit=1, principal=principal
        )


@pytest.mark.parametrize("history", [
    ("baseline", ["extra"]), ("current", ["extra"]),
    ("baseline", ["zone", "extra"]), ("current", ["zone", "extra"]),
], indirect=True)
def test_all_current_and_baseline_assignments_must_be_proven_and_granted(history) -> None:
    _, projector, _, area = history
    page = projector.history_for_site(
        "site-a", organization_id="org-a", after=None, limit=20, principal=_principal(area)
    )
    assert page.items == [] and page.next_cursor is None


def test_source_order_producer_rejects_empty_assignments(history) -> None:
    graph, _, _, _ = history
    with pytest.raises(ValueError):
        graph.service.work_orders.create_work_order(
            organization_id="org-a", site_id="site-a", name="Empty source",
            work_area_ids=[], schedule_id=None, actor="operator-a", now=_NOW,
        )
