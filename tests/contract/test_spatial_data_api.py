"""Mounted authentication/authorization/strict request transport over genuine Core journals."""

import hashlib
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, PrincipalTokenRecord, mount_auth
from spatial_data_job_fixture import NOW, job_graph, job_store


def mounted(path: Path) -> tuple[TestClient, SimpleNamespace]:
    from ksi_core.domains.external.delivery.api import build_spatial_data_router

    graph = job_graph(path)
    store = job_store(graph)
    app = FastAPI()
    foreign = replace(
        graph.principal, principal_id="foreign-operator", organization_id="foreign-organization"
    )
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=principal
            )
            for token, principal in (
                ("local-client", graph.principal),
                ("foreign-client", foreign),
                ("local-worker", graph.worker),
            )
        ]
    )
    mount_auth(app, registry)
    app.include_router(
        build_spatial_data_router(
            jobs=store,
            grants=graph.authorizer,
            sources=graph.sources,
            downloads=None,
            clock=lambda: NOW,
        )
    )
    graph.store, graph.app = store, app
    return TestClient(app), graph


def base(graph: SimpleNamespace) -> str:
    return f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}/spatial-data-requests"


def body(graph: SimpleNamespace) -> dict[str, Any]:
    return {
        "assetRef": graph.source.asset_ref,
        "requestedBounds": [0, 0, 1, 1],
        "observedCrsDigest": graph.source.inspection.measurements.observed_crs_digest,
        "resolutionMode": "NATIVE",
        "purpose": "GENERAL_DATA_USE",
    }


AUTH = {"Authorization": "Bearer local-client", "Idempotency-Key": "same"}


def test_mounted_issue_retry_status_and_history_return_exact_durable_id(tmp_path: Path) -> None:
    """The mounted API must not create a new request on retry or expose private worker authority."""
    client, graph = mounted(tmp_path)
    first = client.post(base(graph), json=body(graph), headers=AUTH)
    retry = client.post(base(graph), json=body(graph), headers=AUTH)
    assert (first.status_code, retry.status_code) == (201, 200)
    assert first.json()["jobId"] == retry.json()["jobId"]
    detail = client.get(base(graph) + "/" + first.json()["jobId"], headers=AUTH)
    assert detail.status_code == 200 and detail.json() == retry.json()
    page = client.get(base(graph), headers=AUTH)
    assert page.json()["items"] == [retry.json()]
    assert (
        "objectKey" not in first.text
        and "capability" not in first.text
        and "policy" not in first.text
    )


@pytest.mark.parametrize("field", ["organizationId", "policy", "url", "outputPath", "resampling"])
def test_public_body_cannot_override_authority_or_storage(tmp_path: Path, field: str) -> None:
    """Unknown authority/path fields must be refused before durable issuance."""
    client, graph = mounted(tmp_path)
    response = client.post(
        base(graph), json={**body(graph), field: "caller-injected"}, headers=AUTH
    )
    assert response.status_code == 422
    assert client.get(base(graph), headers=AUTH).json()["items"] == []
    assert "caller-injected" not in response.text


def test_foreign_file_head_and_status_have_identical_unknown_resource_errors(
    tmp_path: Path,
) -> None:
    """Valid foreign credentials must not reveal resource existence."""
    client, graph = mounted(tmp_path)
    issued = client.post(base(graph), json=body(graph), headers=AUTH).json()["jobId"]
    headers = {"Authorization": "Bearer foreign-client"}
    for suffix in ("", "/file"):
        found = client.get(base(graph) + "/" + issued + suffix, headers=headers)
        absent = client.get(
            base(graph) + "/sdj-v1-00000000-0000-4000-8000-000000000099" + suffix, headers=headers
        )
        assert found.status_code == absent.status_code == 404
        assert found.json() == absent.json()
    assert client.head(base(graph) + "/" + issued + "/file", headers=headers).status_code == 404


def test_missing_download_port_never_returns_fake_file_or_redirect(tmp_path: Path) -> None:
    """Until guarded downloads are implemented, explicit local routes remain byte-closed."""
    client, graph = mounted(tmp_path)
    issued = client.post(base(graph), json=body(graph), headers=AUTH).json()["jobId"]
    response = client.get(base(graph) + "/" + issued + "/file", headers=AUTH)
    assert response.status_code == 503 and response.json()["reason"] == "STORAGE_UNAVAILABLE"
    assert "Location" not in response.headers


def test_worker_cannot_request_data_and_authentication_precedes_hostile_body(
    tmp_path: Path,
) -> None:
    """Worker authority is not a public request role; unauthenticated bodies stay closed."""
    client, graph = mounted(tmp_path)
    assert (
        client.post(
            base(graph),
            json=body(graph),
            headers={"Authorization": "Bearer local-worker", "Idempotency-Key": "same"},
        ).status_code
        == 403
    )
    unauthenticated = client.post(base(graph), content=b"invalid json")
    assert unauthenticated.status_code == 401


def test_duplicate_json_fields_and_oversized_chunked_body_are_refused(tmp_path: Path) -> None:
    """Last-value JSON parsing and whole-body buffering cannot weaken strict bounded admission."""
    import json

    client, graph = mounted(tmp_path)
    encoded = json.dumps(body(graph))[:-1] + ',"purpose":"GENERAL_DATA_USE"}'
    duplicate = client.post(
        base(graph), content=encoded, headers={**AUTH, "Content-Type": "application/json"}
    )
    assert duplicate.status_code == 422

    def oversized() -> Iterator[bytes]:
        for _ in range(20):
            yield b" " * 4096

    response = client.post(
        base(graph), content=oversized(), headers={**AUTH, "Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert client.get(base(graph), headers=AUTH).json()["items"] == []


def test_revocation_preserves_scoped_history_but_denies_new_preparation(tmp_path: Path) -> None:
    """A withdrawn byte grant must not erase durable metadata or permit another preparation."""
    from spatial_data_fixture import make_revocation

    client, graph = mounted(tmp_path)
    issued = client.post(base(graph), json=body(graph), headers=AUTH).json()["jobId"]
    grant = graph.grant
    graph.grants.revoke(
        make_revocation(
            grant_id=grant.grant_id,
            revision=grant.revision,
            organization_id=grant.organization_id,
            grant_digest=grant.grant_digest,
            revoked_at=NOW,
        )
    )
    detail = client.get(base(graph) + "/" + issued, headers=AUTH)
    assert detail.status_code == 200 and detail.json()["jobId"] == issued
    assert detail.json()["availability"] == "ACCESS_REVOKED"
    retry = client.post(base(graph), json=body(graph), headers=AUTH)
    assert retry.status_code == 403 and retry.json()["reason"] == "ACCESS_REVOKED"


def test_external_ai_is_not_implicitly_authorized_by_general_data_rights(tmp_path: Path) -> None:
    """Ordinary data authority cannot stand in for a purpose-specific AI grant/consent."""
    client, graph = mounted(tmp_path)
    response = client.post(
        base(graph), json={**body(graph), "purpose": "EXTERNAL_AI"}, headers=AUTH
    )
    assert response.status_code == 403
    assert client.get(base(graph), headers=AUTH).json()["items"] == []


def test_cancel_wrong_path_cannot_mutate_a_visible_job_and_range_checks_scope_first(
    tmp_path: Path,
) -> None:
    """Wrong paths cannot mutate jobs; foreign Range requests cannot reveal existence."""
    client, graph = mounted(tmp_path)
    issued = client.post(base(graph), json=body(graph), headers=AUTH).json()["jobId"]
    wrong = base(graph).replace("site-1", "site-not-found")
    response = client.post(wrong + "/" + issued + "/cancel", headers=AUTH)
    assert response.status_code == 404
    assert client.get(base(graph) + "/" + issued, headers=AUTH).json()["executionState"] == "QUEUED"
    assert (
        client.get(
            base(graph) + "/" + issued + "/file", headers={**AUTH, "Range": "bytes=0-1"}
        ).status_code
        == 416
    )
    assert (
        client.get(
            base(graph) + "/" + issued + "/file",
            headers={"Authorization": "Bearer foreign-client", "Range": "bytes=0-1"},
        ).status_code
        == 404
    )


def test_request_documentation_uses_exact_validation_schema_without_broken_refs(
    tmp_path: Path,
) -> None:
    """Manual bounded parsing must still document the actual strict request, not an untyped body."""
    import json

    from jsonschema import Draft202012Validator

    _, graph = mounted(tmp_path)
    from ksi_core.domains.external.delivery.api import PUBLIC_BASE

    schema = graph.app.openapi()["paths"][PUBLIC_BASE]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert "$ref" not in json.dumps(schema)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["purpose"]["enum"] == ["GENERAL_DATA_USE", "EXTERNAL_AI"]
    validator = Draft202012Validator(schema)
    assert not list(validator.iter_errors(body(graph)))
    assert list(validator.iter_errors({**body(graph), "purpose": "UNAUTHORIZED"}))
    assert list(validator.iter_errors({**body(graph), "outputPath": "caller-controlled"}))


def test_all_public_operation_ids_are_unique_including_file_head(tmp_path: Path) -> None:
    """A combined GET/HEAD route must not generate duplicate operation IDs for consumer clients."""
    _, graph = mounted(tmp_path)
    ids = [
        operation["operationId"]
        for path in graph.app.openapi()["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]
    assert len(ids) == len(set(ids))


def test_cancel_does_not_silently_accept_unknown_authority_body(tmp_path: Path) -> None:
    """Ignoring cancel JSON would silently accept controls that the public contract forbids."""
    client, graph = mounted(tmp_path)
    issued = client.post(base(graph), json=body(graph), headers=AUTH).json()["jobId"]
    response = client.post(
        base(graph) + "/" + issued + "/cancel", json={"organizationId": "injected"}, headers=AUTH
    )
    assert response.status_code == 422
    assert client.get(base(graph) + "/" + issued, headers=AUTH).json()["executionState"] == "QUEUED"
    canceled = client.post(base(graph) + "/" + issued + "/cancel", headers=AUTH)
    assert canceled.status_code == 200 and canceled.json()["executionState"] == "CANCELED"


def test_credential_withdrawal_while_reading_body_denies_admission(tmp_path: Path) -> None:
    """A Principal cached before body ingestion must not outlive a withdrawn request credential."""
    import json

    client, graph = mounted(tmp_path)

    def uploaded_body() -> Iterator[bytes]:
        graph.app.state.auth_registry = AuthRegistry([])
        yield json.dumps(body(graph)).encode()

    response = client.post(
        base(graph), content=uploaded_body(), headers={**AUTH, "Content-Type": "application/json"}
    )
    assert response.status_code == 401
    assert (
        graph.store.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=graph.principal,
            cursor=None,
            limit=1,
            now=NOW,
        ).items
        == ()
    )
