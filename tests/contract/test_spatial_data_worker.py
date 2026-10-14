"""Dedicated Core client against mounted real authorities; object bytes are synthetic here."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from spatial_data_fixture import NOW as BYTE_NOW
from spatial_data_job_fixture import NOW
from test_spatial_data_worker_api import upload_body, worker_mounted


def core_client(
    graph: SimpleNamespace,
    transport: httpx.BaseTransport,
    *,
    clock: Any = None,
    activation: Any = None,
) -> Any:
    from ksi_processing_controller.spatial_data_core_client import SpatialDataCoreClient

    return SpatialDataCoreClient(
        base_url="https://core.invalid",
        token="local-worker",
        activation=activation if activation is not None else graph.activation,
        policy=graph.data_policy,
        runtime=graph.runtime,
        clock=clock if clock is not None else (lambda: NOW),
        maximum_response_bytes=graph.data_policy.max_snapshot_bytes,
        request_timeout_seconds=5,
        transport=transport,
    )


def mounted_transport(client: TestClient) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        response = client.request(
            request.method, request.url.path, headers=dict(request.headers), content=request.read()
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=dict(response.headers)
        )

    return httpx.MockTransport(handle)


def test_core_client_drives_mounted_exact_lease_input_upload_complete(tmp_path: Path) -> None:
    """The new client must use the dedicated lane, exact fence headers and sealed declaration."""
    client, graph, provider = worker_mounted(tmp_path)
    with core_client(graph, mounted_transport(client)) as core:
        jobs = core.pending(limit=1)
        assert len(jobs) == 1 and jobs[0].job_id == graph.job_id
        attempt = core.lease(job_id=graph.job_id, acquisition_id="worker-acquisition")
        inspected = core.input(attempt=attempt)
        assert inspected.job.job_id == graph.job_id
        assert inspected.source_capability.artifact_id == graph.source.artifact_id
        declaration = upload_body(graph, attempt)
        capability = core.output_upload(declaration=declaration)
        assert capability.upload_digest == declaration.upload_digest
        result = core.complete(attempt=attempt, upload_digest=declaration.upload_digest)
        assert result.execution_state == "COMPLETED" and provider.heads == 1


def test_core_client_accepts_a_fresh_lease_when_its_clock_is_behind_the_core(
    tmp_path: Path,
) -> None:
    """Routine negative skew (worker clock behind the Core) must not fence a fresh lease.

    acquired_at is stamped by the Core clock; requiring the worker clock to be at
    or past it made every lease fail on hosts whose clock ran milliseconds behind.
    """
    from datetime import timedelta

    client, graph, _ = worker_mounted(tmp_path)
    behind = NOW - timedelta(milliseconds=100)
    activation = graph.activation.model_copy(
        update={"valid_from": NOW - timedelta(seconds=1), "activation_digest": None}
    ).sealed()
    with core_client(
        graph, mounted_transport(client), clock=lambda: behind, activation=activation
    ) as core:
        attempt = core.lease(job_id=graph.job_id, acquisition_id="skewed-acquisition")
    assert attempt.worker_instance_id == graph.activation.worker_instance_id
    assert attempt.attempt_number == 1


def test_core_client_refuses_an_attempt_past_its_lease_expiry(tmp_path: Path) -> None:
    """The upper bound stays: a worker clock past lease_until must fence before any use."""
    from datetime import timedelta

    from ksi_processing_controller.spatial_data_core_client import SpatialDataCoreClientError

    client, graph, _ = worker_mounted(tmp_path)
    ahead = NOW + timedelta(seconds=30)
    with (
        core_client(graph, mounted_transport(client), clock=lambda: ahead) as core,
        pytest.raises(SpatialDataCoreClientError, match="FENCE_CONFLICT"),
    ):
        core.lease(job_id=graph.job_id, acquisition_id="expired-acquisition")


def test_core_client_rejects_path_injection_before_transport(tmp_path: Path) -> None:
    """Untrusted resource IDs must not become arbitrary requests even with a valid bearer."""
    from ksi_processing_controller.spatial_data_core_client import SpatialDataCoreClientError

    _, graph, _ = worker_mounted(tmp_path)
    calls: list[httpx.Request] = []


    def unexpected(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500)

    with core_client(graph, httpx.MockTransport(unexpected)) as core:
        for identity in (
            "../../v1/missions",
            graph.job_id + "?injected=true",
            graph.job_id + "/input",
        ):
            with pytest.raises(SpatialDataCoreClientError, match="INVALID_REQUEST"):
                core.lease(job_id=identity, acquisition_id="same")
    assert calls == []


@pytest.mark.parametrize(
    "payload",
    [
        b'{"items":[],"items":[]}',
        b'{"items":[],"x":NaN}',
        b"\xff",
        b'{"items":[],' + b" " * 1_048_576 + b'"x":0}',
    ],
    ids=["duplicate", "nonfinite", "invalid-utf8", "over-budget"],
)
def test_core_client_rejects_duplicate_nonfinite_invalid_and_oversized_response(
    tmp_path: Path, payload: bytes
) -> None:
    """Provider JSON must be strict and bounded before model validation."""
    from ksi_processing_controller.spatial_data_core_client import SpatialDataCoreClientError

    _, graph, _ = worker_mounted(tmp_path)
    with (
        core_client(
            graph, httpx.MockTransport(lambda request: httpx.Response(200, content=payload))
        ) as core,
        pytest.raises(SpatialDataCoreClientError),
    ):
        core.pending(limit=1)


def test_core_client_never_follows_redirect_or_reflects_server_details(tmp_path: Path) -> None:
    """Redirects must not forward bearer authority or leak server text."""
    from ksi_processing_controller.spatial_data_core_client import SpatialDataCoreClientError

    _, graph, _ = worker_mounted(tmp_path)
    calls = []

    def redirect(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "https://foreign.invalid/secret"},
            content=b"private-server-details",
        )

    with (
        core_client(graph, httpx.MockTransport(redirect)) as core,
        pytest.raises(SpatialDataCoreClientError) as caught,
    ):
        core.pending(limit=1)
    assert len(calls) == 1 and calls[0].startswith("https://core.invalid/")
    assert "private-server-details" not in str(caught.value)
    assert "local-worker" not in str(caught.value)


def test_core_client_preserves_terminal_source_failure_class(tmp_path: Path) -> None:
    """The data client must not reuse Analysis retry rules or forge a retryable source failure."""
    client, graph, _ = worker_mounted(tmp_path)
    with core_client(graph, mounted_transport(client)) as core:
        attempt = core.lease(job_id=graph.job_id, acquisition_id="one")
        result = core.failure(attempt=attempt, reason="SOURCE_UNAVAILABLE")
        assert result.execution_state == "FAILED" and result.reason == "SOURCE_UNAVAILABLE"


def test_core_client_refuses_encoded_response_before_consuming_it(tmp_path: Path) -> None:
    """Compressed responses must not bypass the allocation cap via automatic decompression."""
    import gzip

    from ksi_processing_controller.spatial_data_core_client import SpatialDataCoreClientError

    _, graph, _ = worker_mounted(tmp_path)
    compressed = gzip.compress(b'{"items":[]}')
    with (
        core_client(
            graph,
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200, headers={"Content-Encoding": "gzip"}, content=compressed
                )
            ),
        ) as core,
        pytest.raises(SpatialDataCoreClientError, match="INVALID_CORE_RESPONSE"),
    ):
        core.pending(limit=1)


@pytest.mark.parametrize("change", ["foreign-origin", "extended-expiry"])
def test_core_client_refuses_substituted_upload_authority(tmp_path: Path, change: str) -> None:
    """A reply must bind the same receipt bytes, activated origin and local attempt expiry."""
    from datetime import timedelta

    from ksi_processing_controller.spatial_data_core_client import SpatialDataCoreClientError

    client, graph, _ = worker_mounted(tmp_path)
    original = mounted_transport(client)

    def substituted(request: httpx.Request) -> httpx.Response:
        response = original.handle_request(request)
        if request.url.path.endswith("output-upload"):
            body = response.json()
            if change == "foreign-origin":
                body["capability"]["uploadUrl"] = "https://foreign.invalid/upload"
            else:
                body["capability"]["expiresAt"] = (NOW + timedelta(minutes=3)).isoformat()
            return httpx.Response(200, json=body)
        return response

    with core_client(graph, httpx.MockTransport(substituted)) as core:
        attempt = core.lease(job_id=graph.job_id, acquisition_id="one")
        declaration = upload_body(graph, attempt)
        with pytest.raises(SpatialDataCoreClientError, match="INVALID_CORE_RESPONSE"):
            core.output_upload(declaration=declaration)


def test_worker_stages_rehashes_puts_exact_private_bytes_and_cleans_workspace(
    tmp_path: Path,
) -> None:
    """Skipping source hash, exact PUT or post-upload renewal breaks observable publication."""
    from ksi_processing_controller.spatial_data_worker import run_once
    from spatial_data_worker_fixture import byte_lane, digest

    with byte_lane() as (core, sandbox, policy, uploads, headers):
        assert run_once(
            core=core,
            sandbox=sandbox,
            transport_policy=policy,
            worker_instance_id="instance-local",
            clock=lambda: BYTE_NOW,
            workspace_root=tmp_path,
            heartbeat_interval_millis=100,
        )
        assert uploads == [b"private-output" * 100]
        assert core.completed_reports[0].output_sha256 == digest(uploads[0])
        assert core.completed_reports[0].accuracy_assessed is False
        assert core.renewals >= 3
        assert all("Authorization" not in h and "Cookie" not in h for h in headers)
    assert list(tmp_path.iterdir()) == []


def test_worker_accepts_a_fresh_lease_when_its_clock_is_behind_the_core(tmp_path: Path) -> None:
    """The lease guard must not lose a just-issued attempt under negative skew."""
    from datetime import timedelta

    from ksi_processing_controller.spatial_data_worker import run_once
    from spatial_data_worker_fixture import byte_lane

    with byte_lane() as (core, sandbox, policy, uploads, headers):
        assert run_once(
            core=core,
            sandbox=sandbox,
            transport_policy=policy,
            worker_instance_id="instance-local",
            clock=lambda: BYTE_NOW - timedelta(seconds=2),
            workspace_root=tmp_path,
            heartbeat_interval_millis=100,
        )
        assert uploads == [b"private-output" * 100]
        assert core.completed_reports[0].accuracy_assessed is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("phase", ["download", "prepare", "upload"])
def test_worker_never_completes_after_current_lease_loss(tmp_path: Path, phase: str) -> None:
    """Renewal failure anywhere must fence completion and erase the private workspace."""
    from ksi_processing_controller.spatial_data_worker import run_once
    from spatial_data_worker_fixture import byte_lane

    with byte_lane(phase=phase, sandbox_change="lease-loss" if phase == "prepare" else None) as (
        core,
        sandbox,
        policy,
        uploads,
        _,
    ):
        assert run_once(
            core=core,
            sandbox=sandbox,
            transport_policy=policy,
            worker_instance_id="instance-local",
            clock=lambda: BYTE_NOW,
            workspace_root=tmp_path,
            heartbeat_interval_millis=100,
        )
        assert core.completed_reports == []
        if phase in ("download", "prepare"):
            assert uploads == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "change,reason",
    [
        ("source", "SOURCE_BYTES_MISMATCH"),
        ("tamper", "OUTPUT_VERIFICATION_FAILED"),
        ("receipt-source", "OUTPUT_VERIFICATION_FAILED"),
        ("native-failure", "EMPTY_VALID_WINDOW"),
        ("crash", "RASTER_PREPARATION_FAILED"),
    ],
)
def test_worker_refuses_corrupt_source_candidate_or_crashed_sandbox(
    tmp_path: Path, change: str, reason: str
) -> None:
    from ksi_processing_controller.spatial_data_worker import run_once
    from spatial_data_worker_fixture import byte_lane

    with byte_lane(bad_source=change == "source", sandbox_change=change) as (
        core,
        sandbox,
        policy,
        uploads,
        _,
    ):
        assert run_once(
            core=core,
            sandbox=sandbox,
            transport_policy=policy,
            worker_instance_id="instance-local",
            clock=lambda: BYTE_NOW,
            workspace_root=tmp_path,
            heartbeat_interval_millis=100,
        )
        assert core.completed_reports == [] and uploads == []
        assert core.failures == [reason]
        if change == "source":
            assert sandbox.calls == 0
    assert list(tmp_path.iterdir()) == []


def test_worker_malformed_upload_response_is_terminal_integrity_not_transient_storage(
    tmp_path: Path,
) -> None:
    from ksi_processing_controller.spatial_data_worker import run_once
    from spatial_data_worker_fixture import byte_lane

    with byte_lane(phase="bad-upload-response") as (core, sandbox, policy, uploads, _):
        assert run_once(
            core=core,
            sandbox=sandbox,
            transport_policy=policy,
            worker_instance_id="instance-local",
            clock=lambda: BYTE_NOW,
            workspace_root=tmp_path,
            heartbeat_interval_millis=100,
        )
        assert core.completed_reports == []
        assert core.failures == ["INTEGRITY_MISMATCH"]
    assert list(tmp_path.iterdir()) == []


def test_core_client_refreshes_separate_bearer_and_current_authority_each_request(
    tmp_path: Path,
) -> None:
    from ksi_processing_controller.spatial_data_core_client import (
        SpatialDataCoreClient,
        SpatialDataCoreClientError,
    )

    _, graph, _ = worker_mounted(tmp_path)
    tokens = ["fresh-one", "fresh-two"]
    headers = []
    enabled = True

    def transport(request: httpx.Request) -> httpx.Response:
        headers.append(request.headers["authorization"])
        return httpx.Response(200, json={"items": []})

    with SpatialDataCoreClient(
        base_url="https://core.invalid",
        token="initial-must-not-be-sent",
        activation=graph.activation,
        policy=graph.data_policy,
        runtime=graph.runtime,
        clock=lambda: NOW,
        maximum_response_bytes=graph.data_policy.max_snapshot_bytes,
        request_timeout_seconds=1,
        transport=httpx.MockTransport(transport),
        refresh_credentials=lambda: tokens.pop(0),
        authority_is_current=lambda: enabled,
    ) as core:
        assert core.pending(limit=1) == ()
        assert core.pending(limit=1) == ()
        enabled = False
        with pytest.raises(SpatialDataCoreClientError, match="ACTIVATION_UNAVAILABLE"):
            core.pending(limit=1)
    assert headers == ["Bearer fresh-one", "Bearer fresh-two"]


def test_core_client_failed_fresh_credential_never_uses_cached_token(tmp_path: Path) -> None:
    from ksi_processing_controller.spatial_data_core_client import (
        SpatialDataCoreClient,
        SpatialDataCoreClientError,
    )

    _, graph, _ = worker_mounted(tmp_path)
    calls: list[httpx.Request] = []

    def unexpected_request(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500)

    with (
        SpatialDataCoreClient(
            base_url="https://core.invalid",
            token="cached-must-not-be-used",
            activation=graph.activation,
            policy=graph.data_policy,
            runtime=graph.runtime,
            clock=lambda: NOW,
            maximum_response_bytes=graph.data_policy.max_snapshot_bytes,
            request_timeout_seconds=1,
            transport=httpx.MockTransport(unexpected_request),
            refresh_credentials=lambda: "\r\n",
        ) as core,
        pytest.raises(SpatialDataCoreClientError, match="ACTIVATION_UNAVAILABLE"),
    ):
        core.pending(limit=1)
    assert calls == []
