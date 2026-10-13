"""C2: exact customer details reuse ALL-source history scope, never org-only joins."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from external_product_loop_fixture import build_graph
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, HumanAuthMode, mount_auth
from ksi_core.external_reobservation_proposals import ExternalReobservationProposalRecoveryError
from ksi_core.external_result_workflow_api import build_external_result_workflow_router
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig
from test_external_result_review_proposals import _NOW, _principal
from test_oidc_external_evidence_scope import _AUDIENCE, _ISSUER, _jwk, _token
from test_oidc_external_history_scope import history, mixed_history  # noqa: F401


def _client(
    harness: Any, area: str, *, sites: Any = None, areas: Any = None, org: str = "org-a"
) -> tuple[Any, dict[str, str]]:
    key = generate_private_key(public_exponent=65537, key_size=2048)
    app = FastAPI()
    mount_auth(app, AuthRegistry([]))
    app.include_router(
        build_external_result_workflow_router(
            harness.graph.volumes,
            harness.graph.service,
            single_volumes=harness.single,
            clock=lambda: _NOW,
        )
    )
    app.state.human_auth_mode = HumanAuthMode.OIDC
    app.state.oidc_verifier = OidcJwtVerifier(
        OidcVerifierConfig(issuer=_ISSUER, audience=_AUDIENCE, jwks_url=f"{_ISSUER}/jwks.json"),
        fetch_jwks=lambda: {"keys": [_jwk(key)]},
        subject_registry=OidcSubjectRegistry.from_document(
            {
                "version": "oidc-subject-registry.v1",
                "subjects": [
                    {
                        "issuer": _ISSUER,
                        "subject": "customer",
                        "principalId": "customer",
                        "organizationId": org,
                        "role": "FIELD_OPERATOR",
                        "status": "ACTIVE",
                        "allowedSiteIds": ["site-a"] if sites is None else sites,
                        "allowedWorkAreaIds": [area] if areas is None else areas,
                    }
                ],
            },
            expected_issuer=_ISSUER,
        ),
    )
    return TestClient(app), {"Authorization": f"Bearer {_token(key, 'customer')}"}


def _paths(relative: Any, single: Any) -> tuple[str, ...]:
    return (
        f"/v1/sites/site-a/observations/{relative.report_id}",
        f"/v1/external-relative-volume-reports/{relative.report_id}",
        f"/v1/sites/site-a/observations/{single.report_id}",
        f"/v1/external-single-volume-reports/{single.report_id}",
    )


def test_signed_customer_exact_details_preserve_original_digest_and_metrics(
    mixed_history: tuple[Any, ...],  # noqa: F811 -- imported pytest fixture
) -> None:
    harness, first, single, _, area = mixed_history
    client, headers = _client(harness, area)
    with client:
        for path, report in zip(_paths(first, single), (first, first, single, single), strict=True):
            response = client.get(path, headers=headers)
            assert response.status_code == 200, response.text
            body = response.json()
            if "/observations/" in path:
                assert body["state"] == "AVAILABLE"
                assert body["result"]["reportRef"] == report.report_id
                assert body["result"]["reportDigest"] == report.report_digest
            else:
                assert body["report"]["reportId"] == report.report_id
                assert body["report"]["reportDigest"] == report.report_digest
                assert (
                    body["request"]["currentWorkOrderId"]
                    == harness.graph.source.authority.current_work_order_id
                )
                assert body["review"] is None and body["proposals"] == []


@pytest.mark.parametrize(
    "scope",
    [
        {"areas": []},
        {"areas": ["other-area"]},
        {"sites": []},
        {"org": "org-b"},
    ],
)
def test_signed_hidden_detail_is_indistinguishable_from_missing(
    mixed_history: tuple[Any, ...],  # noqa: F811 -- imported pytest fixture
    scope: Any,  # noqa: F811 -- imported pytest fixture
) -> None:
    harness, first, single, _, area = mixed_history
    client, headers = _client(harness, area, **scope)
    with client:
        for path in _paths(first, single):
            response = client.get(path, headers=headers)
            missing = client.get(path.rsplit("/", 1)[0] + "/missing", headers=headers)
            assert response.status_code == missing.status_code == 404, response.text
            assert response.json() == missing.json()


def test_signed_unavailable_and_wrong_family_details_fail_closed(
    mixed_history: tuple[Any, ...],  # noqa: F811 -- imported pytest fixture
) -> None:
    harness, first, single, _, area = mixed_history
    harness.port.authority = replace(harness.port.authority, decision_id="withdrawn-history")
    client, headers = _client(harness, area)
    with client:
        paths = (
            f"/v1/sites/site-a/observations/{single.report_id}",
            f"/v1/external-single-volume-reports/{single.report_id}",
            f"/v1/external-relative-volume-reports/{single.report_id}",
            f"/v1/external-single-volume-reports/{first.report_id}",
            f"/v1/sites/other-site/observations/{first.report_id}",
        )
        for path in paths:
            assert client.get(path, headers=headers).status_code == 404


def test_signed_archived_details_remain_readable_without_mutation_permission(
    mixed_history: tuple[Any, ...],  # noqa: F811 -- imported pytest fixture
) -> None:
    harness, first, single, _, area = mixed_history
    harness.graph.service.work_areas.archive(area, site_id="site-a", actor="operator-a", now=_NOW)
    client, headers = _client(harness, area)
    with client:
        for path in _paths(first, single):
            assert client.get(path, headers=headers).status_code == 200
        # 2026-10-12: /v1/external-decisions/pending moved into the reviewed
        # matrix (grant-filtered read — see test_oidc_route_scope.py).
        for path in (
            "/v1/sites/site-a/external-relative-volume-reports",
            "/v1/external-reobservation-proposals/unknown",
            "/v1/external-result-reviews/unknown",
        ):
            assert client.get(path, headers=headers).status_code == 403
        # 2026-10-13: /v1/external-*-volume-reports/{report_ref}/reviews moved into
        # the reviewed matrix (console review flow — see test_oidc_route_scope.py).
        # The route is now reachable; the review source authority still refuses
        # this principal with 409 EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE.
        assert (
            client.post(
                f"/v1/external-relative-volume-reports/{first.report_id}/reviews", headers=headers
            ).status_code
            == 409
        )


@pytest.mark.parametrize(
    "history",
    [
        ("current", ["zone", "extra"]),
        ("baseline", ["zone", "extra"]),
    ],
    indirect=True,
)
def test_exact_relative_details_require_all_current_and_baseline_assignments(
    history: tuple[Any, ...],  # noqa: F811 -- imported pytest fixture
    tmp_path: Path,
) -> None:
    graph, _, report, area = history
    harness = SimpleNamespace(graph=graph, single=None)
    client, headers = _client(harness, area)
    with client:
        for path in (
            f"/v1/sites/site-a/observations/{report.report_id}",
            f"/v1/external-relative-volume-reports/{report.report_id}",
        ):
            assert client.get(path, headers=headers).status_code == 404


@pytest.mark.parametrize("divergent_target", [False, True])
def test_exact_detail_inlines_valid_proposal_and_cold_replay_rejects_divergent_target(
    history: tuple[Any, ...],  # noqa: F811 -- imported pytest fixture
    tmp_path: Path,
    divergent_target: bool,
) -> None:
    graph, _, report, area = history
    principal = _principal()
    review = graph.service.reviews.review(
        organization_id="org-a", report_ref=report.report_id, principal=principal, evaluated_at=_NOW
    )
    proposal = graph.service.create(
        organization_id="org-a",
        report_ref=report.report_id,
        target_work_area_ids=(area,),
        reason="Customer follow-up",
        idempotency_key="detail-proposal",
        principal=principal,
        actor=principal.principal_id,
        now=_NOW,
    )
    # Real sealed journal/replay path: simulate a legacy/corrupt target whose own
    # checksums are valid but polygon no longer equals the reviewed report zone.
    source = graph.source
    graph.close()
    if divergent_target:
        path = tmp_path / "proposals.jsonl"
        event = json.loads(path.read_text())
        target = (
            proposal.target_work_areas[0]
            .model_copy(
                update={
                    "polygon": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [0, 20], [20, 20], [0, 0]]],
                    },
                    "snapshot_digest": None,
                }
            )
            .sealed()
        )
        poisoned = proposal.model_copy(
            update={
                "target_work_areas": (target,),
                "proposal_digest": None,
            }
        ).sealed()
        event["proposal"] = poisoned.model_dump(by_alias=True, mode="json")
        body = {k: v for k, v in event.items() if k != "eventDigest"}
        event["eventDigest"] = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
                ).encode()
            ).hexdigest()
        )
        path.write_text(json.dumps(event) + "\n")
        with pytest.raises(ExternalReobservationProposalRecoveryError, match="historical lineage"):
            build_graph(tmp_path, source)
        return
    cold = build_graph(tmp_path, source)
    try:
        client, headers = _client(SimpleNamespace(graph=cold, single=None), area)
        with client:
            response = client.get(
                f"/v1/external-relative-volume-reports/{report.report_id}", headers=headers
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["review"]["reviewRef"] == review.review_ref
            assert body["review"]["request"]["requestDigest"] == review.request.request_digest
            refs = [item["proposal"]["proposalRef"] for item in body["proposals"]]
            assert refs == [proposal.proposal_ref]
    finally:
        cold.close()
