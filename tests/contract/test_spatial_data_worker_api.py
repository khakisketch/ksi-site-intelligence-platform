"""Mounted dedicated-worker transport over genuine journal/fence/rights authorities.

Only the external byte provider is substituted; measurements remain explicitly synthetic.
"""

import base64
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry
from ksi_core.domains.external.delivery.storage_types import (
    SpatialDataObjectObservation,
    SpatialDataOutputTarget,
)
from ksi_event_contracts.spatial_data import SpatialDataAttemptV1, SpatialDataSourceV1
from ksi_event_contracts.spatial_data_worker import (
    SpatialDataRequiredHeaderV1,
    SpatialDataSourceCapabilityV1,
    SpatialDataUploadCapabilityV1,
    SpatialDataUploadDeclarationV1,
)
from spatial_data_job_fixture import NOW, receipt_for
from test_spatial_data_api import AUTH, base, body, mounted

INTERNAL = "/v1/internal/spatial-data-jobs"
INSTANCE = "X-Spatial-Data-Worker-Instance-Id"
DIGEST_HEADER = "X-Spatial-Data-Attempt-Digest"
WORKER = {"Authorization": "Bearer local-worker", INSTANCE: "instance-1"}


class LocalProvider:
    def __init__(self, graph: SimpleNamespace) -> None:
        self.graph = graph
        self.after_source = lambda: None
        self.after_upload = lambda: None
        self.after_head = lambda: None
        self.source_mutation = lambda cap: cap
        self.target: SpatialDataOutputTarget | None = None
        self.observation: SpatialDataObjectObservation | None = None
        self.heads = 0

    def issue_source_get(
        self, source: SpatialDataSourceV1, attempt: SpatialDataAttemptV1, *, expires_at: datetime
    ) -> SpatialDataSourceCapabilityV1:
        assert source.source_digest is not None
        self.after_source()
        return self.source_mutation(
            SpatialDataSourceCapabilityV1(
                artifact_id=source.artifact_id,
                source_digest=source.source_digest,
                observed_sha256=source.observed_sha256,
                observed_size_bytes=source.observed_size_bytes,
                download_url="https://store.invalid/source",
                required_headers=(),
                expires_at=expires_at,
            )
        )

    def issue_output_put(
        self,
        target: SpatialDataOutputTarget,
        *,
        sha256: str,
        size_bytes: int,
        content_type: str,
        expires_at: datetime,
    ) -> SpatialDataUploadCapabilityV1:
        assert content_type == "image/tiff"
        events = list(self.graph.store._journal.replay())  # noqa: SLF001
        assert any(
            event.get("recordType") == "spatial-data-job.output-reserved.v1" for event in events
        )
        self.target = target
        self.observation = SpatialDataObjectObservation(
            target.object_key, "version-1", size_bytes, sha256, "image/tiff"
        )
        self.after_upload()
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(size_bytes),
            "x-amz-checksum-sha256": base64.b64encode(bytes.fromhex(sha256[7:])).decode(),
        }
        return SpatialDataUploadCapabilityV1(
            receipt_digest=target.receipt_digest,
            sha256=sha256,
            size_bytes=size_bytes,
            content_type="image/tiff",
            expires_at=expires_at,
            upload_url="https://store.invalid/output",
            required_headers=tuple(
                SpatialDataRequiredHeaderV1.model_validate({"name": name, "value": value})
                for name, value in headers.items()
            ),
        )

    def observe_owned_output(self, target: SpatialDataOutputTarget) -> SpatialDataObjectObservation:
        assert target == self.target
        self.heads += 1
        self.after_head()
        assert self.observation is not None
        return self.observation

    def open_version(
        self, observation: SpatialDataObjectObservation, *, chunk_bytes: int, deadline: datetime
    ) -> AbstractContextManager[Iterator[bytes]]:
        raise NotImplementedError("This fixture proves transport binding, not byte serving")

    def list_owned_versions(self, target: SpatialDataOutputTarget, *, limit: int) -> NoReturn:
        raise NotImplementedError("This fixture does not prove cleanup")

    def delete_owned_version(self, target: SpatialDataOutputTarget, version_id: str) -> None:
        raise NotImplementedError("This fixture does not prove cleanup")


def worker_mounted(path: Path) -> tuple[TestClient, SimpleNamespace, LocalProvider]:
    from ksi_core.domains.external.delivery.worker_api import build_spatial_data_worker_router

    client, graph = mounted(path)
    provider = LocalProvider(graph)
    graph.time = NOW
    graph.app.include_router(
        build_spatial_data_worker_router(
            jobs=graph.store,
            storage=provider,
            activation=graph.activation,
            clock=lambda: graph.time,
        )
    )
    response = client.post(base(graph), json=body(graph), headers=AUTH)
    assert response.status_code == 201
    graph.job_id = response.json()["jobId"]
    return client, graph, provider


def leased(
    client: TestClient, graph: SimpleNamespace
) -> tuple[SpatialDataAttemptV1, dict[str, str]]:
    from ksi_event_contracts.spatial_data import SpatialDataAttemptV1

    response = client.post(
        INTERNAL + "/" + graph.job_id + "/lease",
        headers=WORKER,
        json={"workerInstanceId": "instance-1", "acquisitionId": "acquisition-1"},
    )
    assert response.status_code == 200, response.text
    attempt = SpatialDataAttemptV1.model_validate(response.json()["attempt"])
    assert attempt.attempt_digest is not None
    return attempt, {**WORKER, DIGEST_HEADER: attempt.attempt_digest}


def upload_body(
    graph: SimpleNamespace, attempt: SpatialDataAttemptV1
) -> SpatialDataUploadDeclarationV1:
    job = graph.store.get(job_id=graph.job_id, principal=graph.principal, now=NOW)
    receipt = receipt_for(graph.store, graph, job, attempt)
    return SpatialDataUploadDeclarationV1(
        attempt=attempt,
        receipt=receipt,
        sha256=receipt.output_sha256,
        size_bytes=receipt.output_size_bytes,
        content_type="image/tiff",
    ).sealed()


def test_worker_lease_input_upload_and_core_observed_completion(tmp_path: Path) -> None:
    """The worker cannot select output keys/versions or publish an unobserved output."""
    client, graph, provider = worker_mounted(tmp_path)
    pending = client.get(INTERNAL, headers=WORKER)
    assert pending.status_code == 200 and pending.json()["items"][0]["jobId"] == graph.job_id
    attempt, headers = leased(client, graph)
    request_path = INTERNAL + "/" + graph.job_id
    source = client.get(request_path + "/input", headers=headers)
    assert source.status_code == 200, source.text
    cap = source.json()["input"]["sourceCapability"]
    assert cap["expiresAt"] == attempt.model_dump(mode="json", by_alias=True)["leaseUntil"]
    declaration = upload_body(graph, attempt)
    upload = client.post(
        request_path + "/output-upload",
        headers=headers,
        json={"declaration": declaration.model_dump(mode="json", by_alias=True)},
    )
    assert upload.status_code == 200, upload.text
    assert "objectKey" not in upload.text and "versionId" not in upload.text
    completed = client.post(
        request_path + "/complete",
        headers=headers,
        json={
            "attempt": attempt.model_dump(mode="json", by_alias=True),
            "uploadDigest": declaration.upload_digest,
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["job"]["executionState"] == "COMPLETED" and provider.heads == 1
    assert "objectKey" not in completed.text and "versionId" not in completed.text
    # A late overwrite becomes an orphan, never the accepted version on an identical retry.
    from dataclasses import replace

    assert provider.observation is not None
    provider.observation = replace(provider.observation, version_id="late-version")
    retry = client.post(
        request_path + "/complete",
        headers=headers,
        json={
            "attempt": attempt.model_dump(mode="json", by_alias=True),
            "uploadDigest": declaration.upload_digest,
        },
    )
    assert retry.status_code == 200 and retry.json() == completed.json()
    assert provider.heads == 1


def test_public_principal_cannot_enter_worker_lane_and_input_requires_exact_headers(
    tmp_path: Path,
) -> None:
    """Permissions and exact live headers gate input before capability issuance."""
    client, graph, _ = worker_mounted(tmp_path)
    assert client.get(INTERNAL, headers=AUTH).status_code == 403
    attempt, headers = leased(client, graph)
    path = INTERNAL + "/" + graph.job_id + "/input"
    assert client.get(path, headers=WORKER).status_code == 409
    assert client.get(path, headers={**headers, INSTANCE: "other-instance"}).status_code == 409
    assert (
        client.get(path, headers={**headers, DIGEST_HEADER: "sha256:" + "0" * 64}).status_code
        == 409
    )
    assert client.get(path, headers=headers).status_code == 200


@pytest.mark.parametrize("withdrawal", ["lane", "credential"])
def test_input_authority_is_repeated_after_storage_io(tmp_path: Path, withdrawal: str) -> None:
    """Withdrawal during I/O must invalidate cached authority."""
    client, graph, provider = worker_mounted(tmp_path)
    _, headers = leased(client, graph)

    def withdraw() -> None:
        if withdrawal == "lane":
            graph.authority.enabled = False
        else:
            graph.app.state.auth_registry = AuthRegistry([])

    provider.after_source = withdraw
    response = client.get(INTERNAL + "/" + graph.job_id + "/input", headers=headers)
    assert response.status_code == (503 if withdrawal == "lane" else 401)
    assert "downloadUrl" not in response.text


def test_upload_post_io_denial_keeps_the_pre_signing_owned_cleanup_target(tmp_path: Path) -> None:
    """Post-sign withdrawal must retain orphan ownership without exposing the capability."""
    client, graph, provider = worker_mounted(tmp_path)
    attempt, headers = leased(client, graph)
    declaration = upload_body(graph, attempt)
    provider.after_upload = lambda: setattr(graph.authority, "enabled", False)
    response = client.post(
        INTERNAL + "/" + graph.job_id + "/output-upload",
        headers=headers,
        json={"declaration": declaration.model_dump(mode="json", by_alias=True)},
    )
    assert response.status_code == 503 and "uploadUrl" not in response.text
    pending = graph.store.cleanup_pending(limit=8, now=NOW + timedelta(seconds=31))
    assert len(pending) == 1 and pending[0].target == provider.target


def test_completion_post_head_denial_never_accepts_observed_bytes(tmp_path: Path) -> None:
    """An observation cannot authorize acceptance after currentness disappears."""
    client, graph, provider = worker_mounted(tmp_path)
    attempt, headers = leased(client, graph)
    declaration = upload_body(graph, attempt)
    path = INTERNAL + "/" + graph.job_id
    assert (
        client.post(
            path + "/output-upload",
            headers=headers,
            json={"declaration": declaration.model_dump(mode="json", by_alias=True)},
        ).status_code
        == 200
    )
    provider.after_head = lambda: setattr(graph.authority, "enabled", False)
    response = client.post(
        path + "/complete",
        headers=headers,
        json={
            "attempt": attempt.model_dump(mode="json", by_alias=True),
            "uploadDigest": declaration.upload_digest,
        },
    )
    assert response.status_code == 503
    assert (
        graph.store.get(job_id=graph.job_id, principal=graph.principal, now=NOW).execution_state
        == "RUNNING"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"artifact_id": "substituted-artifact"},
        {"download_url": "https://untrusted.invalid/source"},
        {"expires_at": NOW},
    ],
)
def test_substituted_source_capability_is_a_typed_safe_failure(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    """Invalid capabilities must be typed failures, not raw exceptions or usable inputs."""
    from fastapi.testclient import TestClient

    client, graph, provider = worker_mounted(tmp_path)
    _, headers = leased(client, graph)
    provider.source_mutation = lambda cap: cap.model_copy(update=changes)
    safe_client = TestClient(graph.app, raise_server_exceptions=False)
    response = safe_client.get(INTERNAL + "/" + graph.job_id + "/input", headers=headers)
    assert response.status_code == 503
    assert response.json()["reason"] == "INTEGRITY_MISMATCH"
    assert "downloadUrl" not in response.text and "substituted-artifact" not in response.text


def test_renewal_requires_current_headers_and_supersedes_the_full_attempt_digest(
    tmp_path: Path,
) -> None:
    """Renewal must bind the live full attempt; input cannot keep using the pre-renewal digest."""
    client, graph, _ = worker_mounted(tmp_path)
    attempt, headers = leased(client, graph)
    graph.time = NOW + timedelta(seconds=1)
    path = INTERNAL + "/" + graph.job_id
    payload = {"attempt": attempt.model_dump(by_alias=True, mode="json")}
    denied = client.post(
        path + "/renew", json=payload, headers={**headers, INSTANCE: "other-instance"}
    )
    assert denied.status_code == 409
    renewed = client.post(path + "/renew", json=payload, headers=headers)
    assert renewed.status_code == 200
    assert renewed.json()["attempt"]["leaseUntil"] != payload["attempt"]["leaseUntil"]
    assert client.get(path + "/input", headers=headers).status_code == 409
    fresh = {**headers, DIGEST_HEADER: renewed.json()["attempt"]["attemptDigest"]}
    assert client.get(path + "/input", headers=fresh).status_code == 200


@pytest.mark.parametrize(
    "reason,retryable,state",
    [
        ("STORAGE_UNAVAILABLE", True, "QUEUED"),
        ("SOURCE_UNAVAILABLE", False, "FAILED"),
        ("INTEGRITY_MISMATCH", False, "FAILED"),
    ],
)
def test_failure_transport_preserves_durable_retry_class_and_exact_fence(
    tmp_path: Path, reason: str, retryable: bool, state: str
) -> None:
    """Transport preserves retry/terminal classes and refuses unfenced failures."""
    client, graph, _ = worker_mounted(tmp_path)
    attempt, headers = leased(client, graph)
    path = INTERNAL + "/" + graph.job_id + "/failure"
    payload = {
        "attempt": attempt.model_dump(by_alias=True, mode="json"),
        "reason": reason,
        "retryable": retryable,
    }
    assert client.post(path, json=payload, headers=WORKER).status_code == 409
    assert (
        client.post(path, json={**payload, "retryable": not retryable}, headers=headers).status_code
        == 422
    )
    response = client.post(path, json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["job"]["executionState"] == state
    assert response.json()["job"]["reason"] == reason
