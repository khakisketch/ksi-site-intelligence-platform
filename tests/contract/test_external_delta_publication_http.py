"""Bounded delta HTTP shapes and real authentication; synthetic source ports only."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.domains.external.quantity.external_delta_publication_api import (
    build_external_delta_publication_router,
)
from ksi_core.identity.auth import AuthRegistry, PrincipalTokenRecord, mount_auth
from ksi_event_contracts.external_delta_publication_api import (
    DeltaOutputObservationWireV1,
    DeltaPublicationViewV1,
)
from test_external_delta_output_observations import graph  # noqa: F401
from test_external_delta_publications import (
    CALC_DIGEST,
    COVERAGE_DIGEST,
    NUMERIC_DIGEST,
    _mcp_client,
    _observation,
    _operator,
    _processing_worker,
    _scoped_operator,
    _worker,
)

PATH = "/v1/sites/site-a/work-areas/work-area-a/delta-publications"
JOB = "/v1/internal/delta-publication-uploads/pub-01"


@pytest.fixture
def http(graph):  # noqa: F811 -- imported pytest fixture, not a runtime redefinition
    store, receipts, clock, source, authority, journal = graph
    principals = {
        "operator": _operator(),
        "worker": _worker(),
        "processing": _processing_worker(),
        "mcp": _mcp_client(),
        "foreign": _scoped_operator(frozenset({"other"}), frozenset({"other"})),
    }
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            tuple(
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(("synthetic-" + name).encode()).hexdigest(),
                    principal=principal,
                )
                for name, principal in principals.items()
            )
        ),
    )
    app.include_router(build_external_delta_publication_router(store=store, clock=clock))
    yield TestClient(app), store, journal


def _headers(role="operator", **extra):
    return {"Authorization": "Bearer synthetic-" + role, **extra}


def _body(**extra):
    return {
        "publicationId": "pub-01",
        "sourceCalculationIdentityDigest": CALC_DIGEST,
        "sourceNumericResultIdentityDigest": NUMERIC_DIGEST,
        "sourceCoverageWitnessDigest": COVERAGE_DIGEST,
        "lifetimeSeconds": 3600,
        **extra,
    }


@pytest.mark.parametrize(
    "extra", [{"gridRows": 4}, {"lifetimeSeconds": True}, {"downloadUrl": "https://x.invalid"}]
)
def test_create_accepts_only_closed_source_intent_no_grids_urls_or_coerced_lifetime(http, extra):
    client, _, journal = http
    before = list(journal.replay())
    assert client.post(PATH, headers=_headers(), json=_body(**extra)).status_code == 422
    assert list(journal.replay()) == before


def test_bounded_json_rejects_oversize_duplicates_and_unauthenticated_commands(http):
    client, _, journal = http
    before = list(journal.replay())
    assert (
        client.post(
            PATH, headers=_headers(**{"Content-Type": "application/json"}), content=b" " * 65537
        ).status_code
        == 413
    )
    payload = json.dumps(_body())[:-1] + ',"lifetimeSeconds":3600}'
    assert (
        client.post(
            PATH, headers=_headers(**{"Content-Type": "application/json"}), content=payload
        ).status_code
        == 422
    )
    assert client.post(PATH, json=_body()).status_code == 401
    assert list(journal.replay()) == before


def test_mcp_identity_ack_scoped_control_and_wrong_path_never_mutates(http):
    client, _, journal = http
    created = client.post(PATH, headers=_headers("mcp"), json=_body())
    assert created.status_code == 200, created.text
    assert created.headers["X-KSI-External-AI-Egress"] == "ALLOWED"
    assert created.headers["Cache-Control"] == "no-store"
    before = list(journal.replay())
    assert (
        client.post(
            PATH.replace("site-a", "other") + "/pub-01/cancel",
            headers=_headers(),
            json={"reason": "wrong path"},
        ).status_code
        == 404
    )
    assert client.post(PATH, headers=_headers("foreign"), json=_body()).status_code == 403
    # Machine identities have only the three audited consumer routes, never
    # human cancellation or an internal worker observation upload.
    assert (
        client.post(
            PATH + "/pub-01/cancel", headers=_headers("mcp"), json={"reason": "not granted"}
        ).status_code
        == 403
    )
    assert client.post(JOB + "/observation", headers=_headers("mcp"), json={}).status_code == 403
    assert list(journal.replay()) == before


def test_worker_output_observation_and_raw_upload_are_separate_guarded_steps(http):
    client, store, _ = http
    leased = client.post(
        JOB + "/lease",
        headers=_headers("worker"),
        json={"workerInstanceId": "inst-1", "leaseAcquisitionId": "acq-http"},
    )
    assert leased.status_code == 200, leased.text
    payload = b"synthetic-unit-payload-not-real-native-TIFF"
    observation = _observation(payload)
    wire = DeltaOutputObservationWireV1.model_validate(asdict(observation)).model_dump(
        by_alias=True,
        mode="json",
    )
    query = {"worker_instance_id": "inst-1", "lease_generation": 1}
    raw_headers = _headers("worker", **{"Content-Type": "application/octet-stream"})
    assert (
        client.post(JOB + "/bytes", headers=raw_headers, params=query, content=payload).status_code
        == 404
    )
    observed = client.post(JOB + "/observation", headers=_headers("worker"), json=wire)
    assert observed.status_code == 200, observed.text
    published = client.post(JOB + "/bytes", headers=raw_headers, params=query, content=payload)
    assert published.status_code == 200, published.text
    assert published.json()["descriptor"]["outputSha256"] == observation.output_sha256
    seen = client.get(PATH + "/pub-01", headers=_headers("mcp"))
    assert seen.status_code == 200 and seen.headers["X-KSI-External-AI-Egress"] == "ALLOWED"
    chunk = client.get(
        PATH + "/pub-01/bytes", headers=_headers("mcp"), params={"offset": 0, "length": 10}
    )
    assert chunk.status_code == 200 and chunk.headers["X-KSI-External-AI-Egress"] == "ALLOWED"
    store._egress.allowed = False
    assert (
        client.get(
            PATH + "/pub-01/bytes", headers=_headers("mcp"), params={"offset": 0, "length": 10}
        ).status_code
        == 403
    )
    # Revocation returns the immutable published descriptor, not the disjoint
    # upload-intent shape. Wrong path cannot revoke a valid record.
    denied = client.post(
        PATH.replace("site-a", "another") + "/pub-01/revoke",
        headers=_headers(),
        json={"reason": "wrong scope"},
    )
    assert denied.status_code == 404
    revoked = client.post(PATH + "/pub-01/revoke", headers=_headers(), json={"reason": "withdraw"})
    assert revoked.status_code == 200, revoked.text
    parsed = DeltaPublicationViewV1.model_validate(revoked.json())
    assert parsed.status == "REVOKED"
    assert parsed.descriptor.output_sha256 == observation.output_sha256
    unavailable = client.get(PATH + "/pub-01", headers=_headers())
    assert unavailable.status_code == 404
    assert unavailable.json() == {"detail": "DELTA_PUBLICATION_REVOKED"}


def test_bad_output_bytes_return_closed_conflict_without_claiming_publication(http):
    client, _, _ = http
    assert (
        client.post(
            JOB + "/lease",
            headers=_headers("worker"),
            json={
                "workerInstanceId": "inst-1",
                "leaseAcquisitionId": "bad-bytes-acquisition",
            },
        ).status_code
        == 200
    )
    observation = DeltaOutputObservationWireV1.model_validate(asdict(_observation(b"correct")))
    assert (
        client.post(
            JOB + "/observation",
            headers=_headers("worker"),
            json=observation.model_dump(
                by_alias=True,
                mode="json",
            ),
        ).status_code
        == 200
    )
    failed = client.post(
        JOB + "/bytes",
        headers=_headers(
            "worker",
            **{
                "Content-Type": "application/octet-stream",
            },
        ),
        params={"worker_instance_id": "inst-1", "lease_generation": 1},
        content=b"corrupt",
    )
    assert failed.status_code == 409, failed.text
    assert failed.json() == {"detail": "DELTA_OUTPUT_UPLOAD_REJECTED"}
    assert client.get(PATH + "/pub-01", headers=_headers()).status_code == 404


def test_pending_discovery_is_bounded_worker_only_and_does_not_mint_a_lease(http):
    client, _, journal = http
    before = list(journal.replay())
    pending = client.get(
        "/v1/internal/delta-publication-uploads", headers=_headers("worker"), params={"limit": 1}
    )
    assert pending.status_code == 200, pending.text
    assert pending.json() == {"publicationIds": ["pub-01"]}
    for role in ("operator", "mcp", "processing"):
        assert (
            client.get("/v1/internal/delta-publication-uploads", headers=_headers(role)).status_code
            == 403
        )
    assert (
        client.get(
            "/v1/internal/delta-publication-uploads",
            headers=_headers("worker"),
            params={"limit": 51},
        ).status_code
        == 422
    )
    assert list(journal.replay()) == before
    assert (
        client.post(
            JOB + "/lease",
            headers=_headers("worker"),
            json={
                "workerInstanceId": "inst-1",
                "leaseAcquisitionId": "discovery-acquisition",
            },
        ).status_code
        == 200
    )
    assert client.get(
        "/v1/internal/delta-publication-uploads", headers=_headers("worker")
    ).json() == {"publicationIds": []}


def test_authenticated_state_codes_distinguish_pending_from_terminal_without_disclosing_foreign_ids(
    http,
):
    client, _, _ = http
    pending = client.get(PATH + "/pub-01", headers=_headers())
    assert pending.status_code == 404
    assert pending.json() == {"detail": "DELTA_PUBLICATION_NOT_YET_PUBLISHED"}
    assert (
        client.post(
            PATH + "/pub-01/cancel", headers=_headers(), json={"reason": "operator canceled"}
        ).status_code
        == 200
    )
    canceled = client.get(PATH + "/pub-01", headers=_headers())
    assert canceled.status_code == 404
    assert canceled.json() == {"detail": "DELTA_PUBLICATION_CANCELED"}
    foreign = client.get(PATH.replace("site-a", "other") + "/pub-01", headers=_headers())
    missing = client.get(PATH + "/not-a-real-publication", headers=_headers())
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "DELTA_PUBLICATION_NOT_FOUND"}


def test_upload_and_slice_limits_cannot_be_bypassed_with_multipart_or_range(http):
    client, _, journal = http
    leased = client.post(
        JOB + "/lease",
        headers=_headers("worker"),
        json={"workerInstanceId": "inst-1", "leaseAcquisitionId": "acq-http"},
    )
    assert leased.status_code == 200
    before = list(journal.replay())
    query = {"worker_instance_id": "inst-1", "lease_generation": 1}
    assert (
        client.post(
            JOB + "/bytes",
            headers=_headers("worker"),
            params=query,
            files={"body": ("unbounded.tif", b"x")},
        ).status_code
        == 415
    )
    assert (
        client.post(
            JOB + "/bytes",
            headers=_headers("worker", **{"Content-Type": "application/octet-stream"}),
            params=query,
            content=b"x" * 1_000_001,
        ).status_code
        == 413
    )
    assert (
        client.get(
            PATH + "/pub-01/bytes", headers=_headers(), params={"offset": 0, "length": 1_048_577}
        ).status_code
        == 422
    )
    assert list(journal.replay()) == before


def test_openapi_declares_closed_request_and_observation_bodies(http):
    client, _, _ = http
    schema = client.app.openapi()
    template = "/v1/sites/{site_id}/work-areas/{work_area_id}/delta-publications"
    body = schema["paths"][template]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert body["additionalProperties"] is False
    assert "gridRows" not in body["properties"]
    assert "sourceNumericResultIdentityDigest" in body["required"]
