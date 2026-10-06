"""Final C1 review coverage: single source scope and signed mixed HTTP pages."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from external_single_volume_fixture import _AuthorityPort, _store
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, HumanAuthMode, mount_auth
from ksi_core.external_result_workflow_api import build_external_result_workflow_router
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig
from test_external_result_review_proposals import _NOW
from test_external_result_single_volume_projection import (
    _Harness,
    _record_single,
    _single_authority,
)
from test_oidc_external_evidence_scope import _AUDIENCE, _ISSUER, _jwk, _token
from test_oidc_external_history_scope import _principal, history, mixed_history  # noqa: F401


@pytest.mark.parametrize("history", [
    ("current", ["extra"]), ("current", ["zone", "extra"]),
], indirect=True)
def test_single_target_source_requires_zone_and_all_assignments(
    history, tmp_path: Path  # noqa: F811 -- imported pytest fixture
) -> None:
    graph, _, _, area = history
    port = _AuthorityPort(
        _single_authority(graph, captured_to=_NOW + timedelta(hours=4)),
        coordinator=graph.service.coordinator,
    )
    single = _store(tmp_path, port, now=_NOW)
    harness = _Harness(graph, port, single)
    try:
        report = _record_single(harness)
        projector = harness.projector()
        page = projector.history_for_site(
            "site-a", organization_id="org-a", after=None, limit=20, principal=_principal(area)
        )
        assert page.items == [] and page.next_cursor is None
        with pytest.raises(LookupError):
            projector.history_for_site(
                "site-a", organization_id="org-a", after=report.report_id, limit=20,
                principal=_principal(area),
            )
    finally:
        single._journal.close()  # noqa: SLF001 -- fixture-owned real journal


def test_signed_mixed_pages_and_closed_siblings(mixed_history) -> None:  # noqa: F811 -- pytest fixture
    harness, first, single, latest, area = mixed_history
    key = generate_private_key(public_exponent=65537, key_size=2048)
    app = FastAPI()
    mount_auth(app, AuthRegistry([]))
    app.include_router(build_external_result_workflow_router(
        harness.graph.volumes, harness.graph.service, single_volumes=harness.single,
        clock=lambda: _NOW,
    ))
    app.state.human_auth_mode = HumanAuthMode.OIDC
    app.state.oidc_verifier = OidcJwtVerifier(
        OidcVerifierConfig(issuer=_ISSUER, audience=_AUDIENCE, jwks_url=f"{_ISSUER}/jwks.json"),
        fetch_jwks=lambda: {"keys": [_jwk(key)]},
        subject_registry=OidcSubjectRegistry.from_document({
            "version": "oidc-subject-registry.v1", "subjects": [{
                "issuer": _ISSUER, "subject": "customer", "principalId": "customer",
                "organizationId": "org-a", "role": "FIELD_OPERATOR", "status": "ACTIVE",
                "allowedSiteIds": ["site-a"], "allowedWorkAreaIds": [area],
            }],
        }, expected_issuer=_ISSUER),
    )
    headers = {"Authorization": f"Bearer {_token(key, 'customer')}"}
    path = "/v1/sites/site-a/external-volume-reports"
    with TestClient(app) as client:
        cursor = None
        for report, next_cursor in (
            (latest, latest.report_id), (single, single.report_id), (first, None)
        ):
            params = {"limit": 1}
            if cursor is not None:
                params["after"] = cursor
            response = client.get(path, params=params, headers=headers)
            assert response.status_code == 200, response.text
            assert [r["reportRef"] for r in response.json()["items"]] == [report.report_id]
            assert response.json()["nextCursor"] == next_cursor
            cursor = next_cursor
        # Real registered siblings must remain closed; no404 due to absent handlers.
        for sibling in (
            f"/v1/sites/site-a/observations/{latest.report_id}",
            f"/v1/external-single-volume-reports/{single.report_id}",
            "/v1/external-reobservation-proposals/unknown-proposal",
            "/v1/external-result-reviews/unknown-review",
        ):
            assert client.get(sibling, headers=headers).status_code == 403
        harness.port.authority = replace(
            harness.port.authority, decision_id="withdrawn-history"
        )
        hidden = client.get(path, params={"after": single.report_id}, headers=headers)
        missing = client.get(path, params={"after": "missing"}, headers=headers)
        assert hidden.status_code == missing.status_code == 404
        assert hidden.json() == missing.json()
        tail = client.get(path, params={"after": latest.report_id, "limit": 1}, headers=headers)
        assert tail.status_code == 200, tail.text
        assert [r["reportRef"] for r in tail.json()["items"]] == [first.report_id]
        assert tail.json()["nextCursor"] is None


def test_unrestricted_unavailable_single_is_retained_not_hidden(
    mixed_history,  # noqa: F811 -- imported pytest fixture
) -> None:
    harness, _, single, _, area = mixed_history
    harness.port.authority = replace(harness.port.authority, decision_id="withdrawn-history")
    projector = harness.projector()
    privileged = projector.history_for_site(
        "site-a", organization_id="org-a", after=None, limit=20
    )
    row = next(item for item in privileged.items if item.report_ref == single.report_id)
    assert row.state == "HISTORICAL_SOURCE_UNAVAILABLE"
    assert row.result is None
    restricted = projector.history_for_site(
        "site-a", organization_id="org-a", after=None, limit=20, principal=_principal(area)
    )
    assert single.report_id not in [item.report_ref for item in restricted.items]
