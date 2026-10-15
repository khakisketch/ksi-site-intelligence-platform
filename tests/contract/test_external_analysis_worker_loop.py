"""Loopback evidence for the authenticated V1 Analysis worker boundary."""

from __future__ import annotations

import json
import socket
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock, Thread
from typing import Any

import numpy as np
import pytest
from ksi_event_contracts.external_analysis_worker import (
    ANALYSIS_ATTEMPT_DIGEST_HEADER,
    ANALYSIS_WORKER_INSTANCE_ID_HEADER,
    AnalysisWorkerFailureRequestV1,
    AnalysisWorkerInputCapabilityV1,
    AnalysisWorkerInputResponseV1,
    AnalysisWorkerInputV1,
    AnalysisWorkerLeaseViewV1,
    AnalysisWorkerMutationViewV1,
    AnalysisWorkerPendingItemV1,
    AnalysisWorkerPendingListV1,
    AnalysisWorkerReportRequestV1,
)
from ksi_event_contracts.external_relative_volume_calculation import (
    AnalysisExecutionAttemptV2,
    RelativeVolumeCalculationFailureV2,
    RelativeVolumeCalculationReportV2,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from test_external_analysis_measurement import _attempt, _envelope, _identity, _write_dsm

_START = datetime(2026, 9, 21, tzinfo=UTC)
_ANALYSIS_ID = "analysis-loop-1"
_REQUEST_ID = "calculation-loop-1"
_WORKER_ID = "local-analysis-worker"


class _Clock:
    """A progressing UTC clock makes the terminal timestamp observable."""

    def __init__(self, *, step_millis: int = 10) -> None:
        self._calls = 0
        self._step_millis = step_millis

    def __call__(self) -> datetime:
        value = _START + timedelta(milliseconds=self._step_millis * self._calls)
        self._calls += 1
        return value


class _ObjectServer:
    def __init__(self, objects: dict[str, bytes], *, response_delay_seconds: float = 0.0) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                payload = objects.get(self.path)
                if payload is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if self.headers.get("X-Storage-Capability") != "loopback-object-token":
                    self.send_response(403)
                    self.end_headers()
                    return
                if response_delay_seconds:
                    time.sleep(response_delay_seconds)
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Content-Type", "image/tiff")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._server.server_address[:2]
        assert isinstance(host, str)
        assert isinstance(port, int)
        self.origin = f"http://{host}:{port}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
        assert not self._thread.is_alive()


class _SlowCoreResponseServer:
    """A loopback Core endpoint that keeps every individual socket wait active."""

    def __init__(self, *, drip_headers: bool, host: str = "127.0.0.1") -> None:
        payload = b'{"items":[]}'
        header = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Encoding: identity\r\n"
            + b"Content-Length: "
            + str(len(payload)).encode("ascii")
            + b"\r\n\r\n"
        )

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/core/v1/internal/analysis-jobs":
                    self.send_response(404)
                    self.end_headers()
                    return
                try:
                    if not drip_headers:
                        self.wfile.write(header)
                        self.wfile.flush()
                    for byte in header if drip_headers else payload:
                        self.wfile.write(bytes((byte,)))
                        self.wfile.flush()
                        time.sleep(0.015)
                    if drip_headers:
                        self.wfile.write(payload)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return

            def log_message(self, _format: str, *_args: object) -> None:
                return

        class Server(ThreadingHTTPServer):
            address_family = socket.AF_INET6 if ":" in host else socket.AF_INET

        self._server = Server((host, 0), Handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        bound_host, port = self._server.server_address[:2]
        assert isinstance(bound_host, str)
        assert isinstance(port, int)
        literal_host = f"[{bound_host}]" if ":" in bound_host else bound_host
        self.base_url = f"http://{literal_host}:{port}/core"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
        assert not self._thread.is_alive()


class _CoreState:
    def __init__(
        self,
        *,
        initial_attempt: AnalysisExecutionAttemptV2,
        renewed_attempt: AnalysisExecutionAttemptV2,
        input_value: AnalysisWorkerInputV1,
    ) -> None:
        self.initial_attempt = initial_attempt
        self.renewed_attempt = renewed_attempt
        self.input_value = input_value
        self.lease_acquisition_id: str | None = None
        self.renew_calls = 0
        self.renew_during_measurement = 0
        self.measurement_active = False
        self.lose_fence_on_renew = False
        self.slow_renew_during_measurement = False
        self.renew_started = Event()
        self.renew_finished = Event()
        self._renew_lock = Lock()
        self.renew_inflight = 0
        self.failure: RelativeVolumeCalculationFailureV2 | None = None
        self.report: RelativeVolumeCalculationReportV2 | None = None
        self.error: str | None = None

    def accept_lease(self, worker_instance_id: str, lease_acquisition_id: str) -> None:
        self.lease_acquisition_id = lease_acquisition_id
        self.initial_attempt = self.initial_attempt.model_copy(
            update={
                "worker_instance_id": worker_instance_id,
                "lease_acquisition_id": lease_acquisition_id,
                "execution_attempt_digest": None,
            }
        ).sealed()
        self.renewed_attempt = self.renewed_attempt.model_copy(
            update={
                "worker_instance_id": worker_instance_id,
                "lease_acquisition_id": lease_acquisition_id,
                "execution_attempt_digest": None,
            }
        ).sealed()
        self.input_value = self.input_value.model_copy(update={"attempt": self.initial_attempt})

    def begin_slow_renewal(self) -> None:
        with self._renew_lock:
            self.renew_inflight += 1
        self.renew_started.set()

    def finish_slow_renewal(self) -> None:
        with self._renew_lock:
            self.renew_inflight -= 1
        self.renew_finished.set()


class _CoreServer:
    def __init__(self, state: _CoreState) -> None:
        class Handler(BaseHTTPRequestHandler):
            def _json(self, value: object, status: int = 200) -> None:
                payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Encoding", "identity")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _slow_renew_json(self, value: object) -> None:
                payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
                state.begin_slow_renewal()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Encoding", "identity")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    for byte in payload:
                        self.wfile.write(bytes((byte,)))
                        self.wfile.flush()
                        time.sleep(0.015)
                except (BrokenPipeError, ConnectionResetError):
                    return
                finally:
                    state.finish_slow_renewal()

            def _body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                return json.loads(self.rfile.read(length))

            def _auth(self) -> bool:
                return self.headers.get("Authorization") == "Bearer local-worker-token"

            def do_GET(self) -> None:  # noqa: N802
                if not self._auth():
                    self._json({}, 401)
                    return
                if self.path == "/core/v1/internal/analysis-jobs":
                    self._json(
                        AnalysisWorkerPendingListV1(
                            items=(
                                AnalysisWorkerPendingItemV1(
                                    analysis_id=_ANALYSIS_ID,
                                    calculation_request_id=_REQUEST_ID,
                                    issued_at=_START,
                                ),
                            )
                        ).model_dump(by_alias=True, mode="json")
                    )
                    return
                if self.path == f"/core/v1/internal/analysis-jobs/{_ANALYSIS_ID}/input":
                    if (
                        self.headers.get(ANALYSIS_ATTEMPT_DIGEST_HEADER)
                        != state.initial_attempt.canonical_digest()
                        or self.headers.get(ANALYSIS_WORKER_INSTANCE_ID_HEADER) != _WORKER_ID
                    ):
                        self._json({}, 409)
                        return
                    self._json(
                        AnalysisWorkerInputResponseV1(input=state.input_value).model_dump(
                            by_alias=True, mode="json"
                        )
                    )
                    return
                self._json({}, 404)

            def do_POST(self) -> None:  # noqa: N802
                if not self._auth():
                    self._json({}, 401)
                    return
                body = self._body()
                if self.path == f"/core/v1/internal/analysis-jobs/{_ANALYSIS_ID}:lease":
                    if set(body) != {"workerInstanceId", "leaseAcquisitionId"} or body[
                        "workerInstanceId"
                    ] != _WORKER_ID:
                        self._json({}, 422)
                        return
                    state.accept_lease(body["workerInstanceId"], body["leaseAcquisitionId"])
                    self._json(
                        AnalysisWorkerLeaseViewV1(
                            analysis_id=_ANALYSIS_ID,
                            calculation_request_id=_REQUEST_ID,
                            attempt=state.initial_attempt,
                        ).model_dump(by_alias=True, mode="json")
                    )
                    return
                if self.path == f"/core/v1/internal/analysis-jobs/{_ANALYSIS_ID}:renew":
                    if state.lose_fence_on_renew:
                        self._json({}, 409)
                        return
                    if body.get("attempt") not in (
                        state.initial_attempt.model_dump(by_alias=True, mode="json"),
                        state.renewed_attempt.model_dump(by_alias=True, mode="json"),
                    ):
                        self._json({}, 409)
                        return
                    state.renew_calls += 1
                    if state.measurement_active:
                        state.renew_during_measurement += 1
                    response = AnalysisWorkerLeaseViewV1(
                        analysis_id=_ANALYSIS_ID,
                        calculation_request_id=_REQUEST_ID,
                        attempt=state.renewed_attempt,
                    ).model_dump(by_alias=True, mode="json")
                    if state.slow_renew_during_measurement and state.measurement_active:
                        self._slow_renew_json(response)
                    else:
                        self._json(response)
                    return
                if self.path == f"/core/v1/internal/analysis-jobs/{_ANALYSIS_ID}:report":
                    try:
                        report = AnalysisWorkerReportRequestV1.model_validate(body).report
                    except ValueError:
                        self._json({}, 422)
                        return
                    if report.attempt != state.renewed_attempt:
                        self._json({}, 409)
                        return
                    state.report = report
                    self._json(
                        AnalysisWorkerMutationViewV1(
                            analysis_id=_ANALYSIS_ID,
                            calculation_request_id=_REQUEST_ID,
                            execution_state="COMPLETED",
                            attempt=state.renewed_attempt,
                        ).model_dump(by_alias=True, mode="json")
                    )
                    return
                if self.path == f"/core/v1/internal/analysis-jobs/{_ANALYSIS_ID}:failure":
                    try:
                        failure = AnalysisWorkerFailureRequestV1.model_validate(body).failure
                    except ValueError:
                        self._json({}, 422)
                        return
                    if failure.attempt != state.renewed_attempt:
                        self._json({}, 409)
                        return
                    state.failure = failure
                    self._json(
                        AnalysisWorkerMutationViewV1(
                            analysis_id=_ANALYSIS_ID,
                            calculation_request_id=_REQUEST_ID,
                            execution_state="FAILED",
                            attempt=state.renewed_attempt,
                        ).model_dump(by_alias=True, mode="json")
                    )
                    return
                self._json({}, 404)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._server.server_address[:2]
        assert isinstance(host, str)
        assert isinstance(port, int)
        self.base_url = f"http://{host}:{port}/core"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
        assert not self._thread.is_alive()


@contextmanager
def _loopback_servers(
    state: _CoreState,
    objects: dict[str, bytes],
    *,
    response_delay_seconds: float = 0.0,
) -> Generator[tuple[_CoreServer, _ObjectServer], None, None]:
    object_server = _ObjectServer(objects, response_delay_seconds=response_delay_seconds)
    core_server = _CoreServer(state)
    try:
        yield core_server, object_server
    finally:
        core_server.close()
        object_server.close()


def _failure_state(
    tmp_path: Any, *, expires_at: datetime, envelope: Any = None
) -> tuple[Any, _CoreState]:
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    current = _write_dsm(tmp_path / "current.tif", np.full((2, 2), 100.0))
    identity = _identity(baseline, current)
    initial_attempt = _attempt(identity, envelope=envelope).model_copy(
        update={
            "issued_at": _START,
            "lease_expires_at": _START + timedelta(minutes=2),
            "execution_attempt_digest": None,
        }
    ).sealed()
    renewed_attempt = initial_attempt.model_copy(
        update={
            "issued_at": _START + timedelta(seconds=1),
            "lease_expires_at": _START + timedelta(minutes=3),
            "execution_attempt_digest": None,
        }
    ).sealed()
    return identity, _CoreState(
        initial_attempt=initial_attempt,
        renewed_attempt=renewed_attempt,
        input_value=AnalysisWorkerInputV1(
            analysis_id=_ANALYSIS_ID,
            calculation_request_id=_REQUEST_ID,
            attempt=initial_attempt,
            calculation_identity=identity,
            inputs=(
                AnalysisWorkerInputCapabilityV1(
                    role="BASELINE_DSM",
                    artifact_id=identity.baseline_dsm_artifact_id,
                    observed_sha256=identity.baseline_dsm_observed_sha256,
                    observed_size_bytes=baseline.stat().st_size,
                    download_url="http://127.0.0.1:1/baseline",
                    required_headers={"X-Storage-Capability": "loopback-object-token"},
                    expires_at=expires_at,
                ),
                AnalysisWorkerInputCapabilityV1(
                    role="CURRENT_DSM",
                    artifact_id=identity.current_dsm_artifact_id,
                    observed_sha256=identity.current_dsm_observed_sha256,
                    observed_size_bytes=current.stat().st_size,
                    download_url="http://127.0.0.1:1/current",
                    required_headers={"X-Storage-Capability": "loopback-object-token"},
                    expires_at=expires_at,
                ),
            ),
        ),
    )


def _unreachable_object_policy() -> ExternalObjectTransportPolicyV1:
    return ExternalObjectTransportPolicyV1(
        endpoints=(
            TrustedObjectEndpointV1(
                origin="http://127.0.0.1:1", addresses=("127.0.0.1",)
            ),
        ),
        max_header_bytes=4096,
        max_object_bytes=1_000_000,
        max_chunk_bytes=1024,
    )


@pytest.mark.parametrize("drip_headers", (True, False))
def test_core_client_applies_one_total_deadline_to_slow_headers_and_body(
    drip_headers: bool,
) -> None:
    """A peer cannot keep a Core call alive by continuously trickling bytes."""
    from ksi_processing_controller.external_analysis_core_client import (
        ExternalAnalysisCoreClient,
        ExternalAnalysisCoreClientError,
    )

    server = _SlowCoreResponseServer(drip_headers=drip_headers)
    try:
        with ExternalAnalysisCoreClient(
            base_url=server.base_url,
            worker_token="local-worker-token",
            worker_instance_id=_WORKER_ID,
            request_timeout_seconds=0.03,
        ) as client:
            started_monotonic = time.monotonic()
            with pytest.raises(ExternalAnalysisCoreClientError) as raised:
                client.list_pending()
            elapsed_wall_seconds = time.monotonic() - started_monotonic
    finally:
        server.close()

    assert raised.value.code == "CORE_HTTP_TIMEOUT"
    assert elapsed_wall_seconds < 0.3


@pytest.mark.parametrize(
    "base_url",
    (
        "https://core.invalid/analysis",
        "https://[fe80::1%lo]/analysis",
        "https://[fe80::1%25lo]/analysis",
    ),
)
def test_core_client_rejects_dns_and_scoped_ipv6_before_any_resolution(
    base_url: str, monkeypatch: Any
) -> None:
    """The local runner accepts only unscoped literal Core addresses."""
    from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient

    calls: list[object] = []

    def forbidden_resolution(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        raise AssertionError("hostname resolution must not be attempted")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden_resolution)
    with pytest.raises(ValueError, match="literal IP"):
        ExternalAnalysisCoreClient(
            base_url=base_url,
            worker_token="local-worker-token",
            worker_instance_id=_WORKER_ID,
        )
    assert calls == []


@pytest.mark.parametrize("host", ("127.0.0.1", "::1"))
def test_core_client_uses_no_resolver_for_unscoped_literal_ip_requests(
    host: str, monkeypatch: Any
) -> None:
    """Numeric HTTP Core URLs use the no-DNS transport path for IPv4 and IPv6."""
    from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient

    server = _SlowCoreResponseServer(drip_headers=False, host=host)
    calls: list[object] = []

    def forbidden_resolution(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        raise AssertionError("literal Core URL must not resolve through DNS")

    try:
        monkeypatch.setattr(socket, "getaddrinfo", forbidden_resolution)
        with ExternalAnalysisCoreClient(
            base_url=server.base_url,
            worker_token="local-worker-token",
            worker_instance_id=_WORKER_ID,
            request_timeout_seconds=1.0,
        ) as client:
            assert client.list_pending() == ()
    finally:
        server.close()

    assert calls == []


def test_analysis_runner_reads_a_bounded_private_token_file(
    tmp_path: Any, monkeypatch: Any
) -> None:
    """The local bearer value never appears in the standalone worker argv."""
    token_path = tmp_path / "analysis-worker-token"
    token_path.write_text("local-worker-token\n", encoding="ascii")
    token_path.chmod(0o600)
    import ksi_processing_controller.external_analysis_runner as runner

    captured: dict[str, str] = {}

    class Client:
        def __init__(self, **kwargs: str) -> None:
            captured["token"] = kwargs["worker_token"]

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(runner, "ExternalAnalysisCoreClient", Client)
    monkeypatch.setattr(runner, "run_once", lambda *_args: True)
    digest = "sha256:" + "0" * 64
    assert (
        runner.main(
            (
                "--core-url",
                "http://127.0.0.1:8080/core",
                "--worker-token-file",
                str(token_path),
                "--worker-instance-id",
                _WORKER_ID,
                "--worker-executable-digest",
                digest,
                "--worker-build-digest",
                digest,
                "--runtime-image-version",
                "local-test",
                "--runtime-image-oci-digest",
                digest,
                "--dependency-lock-digest",
                digest,
                "--trusted-object-endpoint",
                "http://127.0.0.1:8081=127.0.0.1",
                "--max-header-bytes",
                "4096",
                "--max-object-bytes",
                "1048576",
                "--max-chunk-bytes",
                "1024",
                "--request-timeout-seconds",
                "1",
                "--poll-interval-seconds",
                "1",
                "--once",
            )
        )
        == 0
    )
    assert captured == {"token": "local-worker-token"}
    assert "--worker-token " not in runner._parser().format_help()


def test_analysis_runner_token_file_errors_do_not_expose_its_contents(tmp_path: Any) -> None:
    """Malformed or over-limit files fail with a fixed message rather than a secret."""
    token_path = tmp_path / "analysis-worker-token"
    secret = "not-a-real-secret"
    token_path.write_text(secret * 300, encoding="ascii")
    token_path.chmod(0o600)
    import ksi_processing_controller.external_analysis_runner as runner

    with pytest.raises(ValueError) as raised:
        runner._worker_token_file(str(token_path))

    assert str(raised.value) == "worker token file is invalid"
    assert secret not in str(raised.value)


@pytest.mark.parametrize("limit_name", ("aggregate-stream", "workspace-snapshots"))
def test_run_once_rejects_aggregate_transfer_and_snapshot_workspace_before_network(
    tmp_path: Any, limit_name: str
) -> None:
    """Two individually valid DSMs must also fit every aggregate sealed budget."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    current = _write_dsm(tmp_path / "current.tif", np.full((2, 2), 100.0))
    total_input_bytes = baseline.stat().st_size + current.stat().st_size
    limits = {
        "max_input_bytes": total_input_bytes,
        "max_streamed_bytes": (
            total_input_bytes - 1 if limit_name == "aggregate-stream" else total_input_bytes
        ),
        "max_workspace_bytes": (
            2 * total_input_bytes
            if limit_name == "aggregate-stream"
            else 2 * total_input_bytes - 1
        ),
        "resource_envelope_digest": None,
    }
    envelope = _envelope().model_copy(update=limits).sealed()
    identity, state = _failure_state(
        tmp_path,
        expires_at=_START + timedelta(minutes=1),
        envelope=envelope,
    )
    from ksi_processing_controller.external_analysis_core_client import (
        ExternalAnalysisCoreClient,
    )
    from ksi_processing_controller.external_analysis_worker import (
        ProcessingWorkerRuntimeIdentityV1,
        run_once,
    )

    runtime = ProcessingWorkerRuntimeIdentityV1(
        worker_executable_digest=identity.worker_executable_digest,
        worker_build_digest=identity.worker_build_digest,
        runtime_image_version=identity.runtime_image_version,
        runtime_image_oci_digest=identity.runtime_image_oci_digest,
        dependency_lock_digest=identity.dependency_lock_digest,
    )
    with (
        _loopback_servers(state, {}) as (core_server, _object_server),
        ExternalAnalysisCoreClient(
            base_url=core_server.base_url,
            worker_token="local-worker-token",
            worker_instance_id=_WORKER_ID,
        ) as client,
    ):
        assert run_once(client, runtime, _unreachable_object_policy(), now=_Clock()) is True

    assert state.report is None
    assert state.failure is not None
    assert state.failure.reason_code == "RESOURCE_LIMIT_EXCEEDED"
    assert state.failure.attempt == state.renewed_attempt


def test_run_once_downloads_real_geotiffs_and_reseals_the_report_after_renewal(
    tmp_path: Any, monkeypatch: Any
) -> None:
    """A stale outer report must not relabel measured content after a lease renewal."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    current = _write_dsm(
        tmp_path / "current.tif", np.array([[101.0, 99.0], [100.0, 100.0]])
    )
    identity = _identity(baseline, current)
    initial_attempt = _attempt(identity).model_copy(
        update={
            "issued_at": _START,
            "lease_expires_at": _START + timedelta(milliseconds=150),
            "execution_attempt_digest": None,
        }
    ).sealed()
    renewed_attempt = initial_attempt.model_copy(
        update={
            "issued_at": _START + timedelta(milliseconds=10),
            "lease_expires_at": _START + timedelta(milliseconds=200),
            "execution_attempt_digest": None,
        }
    ).sealed()
    baseline_bytes = baseline.read_bytes()
    current_bytes = current.read_bytes()

    placeholder = "http://127.0.0.1:1/not-used"
    input_value = AnalysisWorkerInputV1(
        analysis_id=_ANALYSIS_ID,
        calculation_request_id=_REQUEST_ID,
        attempt=initial_attempt,
        calculation_identity=identity,
        inputs=(
            AnalysisWorkerInputCapabilityV1(
                role="BASELINE_DSM",
                artifact_id=identity.baseline_dsm_artifact_id,
                observed_sha256=identity.baseline_dsm_observed_sha256,
                observed_size_bytes=len(baseline_bytes),
                download_url=placeholder,
                required_headers={"X-Storage-Capability": "loopback-object-token"},
                expires_at=_START + timedelta(milliseconds=100),
            ),
            AnalysisWorkerInputCapabilityV1(
                role="CURRENT_DSM",
                artifact_id=identity.current_dsm_artifact_id,
                observed_sha256=identity.current_dsm_observed_sha256,
                observed_size_bytes=len(current_bytes),
                download_url=placeholder,
                required_headers={"X-Storage-Capability": "loopback-object-token"},
                expires_at=_START + timedelta(milliseconds=100),
            ),
        ),
    )
    state = _CoreState(
        initial_attempt=initial_attempt,
        renewed_attempt=renewed_attempt,
        input_value=input_value,
    )

    with _loopback_servers(state, {"/baseline": baseline_bytes, "/current": current_bytes}) as (
        core_server,
        object_server,
    ):
        state.input_value = state.input_value.model_copy(
            update={
                "inputs": (
                    state.input_value.inputs[0].model_copy(
                        update={"download_url": object_server.origin + "/baseline"}
                    ),
                    state.input_value.inputs[1].model_copy(
                        update={"download_url": object_server.origin + "/current"}
                    ),
                )
            }
        )

        # The production change that makes this fail is omitting the exact
        # runtime/fence/capability loop or reporting the old attempt after renew.
        import ksi_processing_controller.external_analysis_worker as worker_module
        from ksi_processing_controller.external_analysis_core_client import (
            ExternalAnalysisCoreClient,
        )
        from ksi_processing_controller.external_analysis_worker import (
            ProcessingWorkerRuntimeIdentityV1,
            run_once,
        )

        actual_measurement = worker_module.measure_external_relative_volume_v2

        def delayed_real_measurement(**kwargs: Any) -> object:
            state.measurement_active = True
            try:
                time.sleep(0.12)
                return actual_measurement(**kwargs)
            finally:
                state.measurement_active = False

        monkeypatch.setattr(
            worker_module, "measure_external_relative_volume_v2", delayed_real_measurement
        )

        policy = ExternalObjectTransportPolicyV1(
            endpoints=(
                TrustedObjectEndpointV1(
                    origin=object_server.origin, addresses=("127.0.0.1",)
                ),
            ),
            max_header_bytes=4096,
            max_object_bytes=1_000_000,
            max_chunk_bytes=1024,
        )
        runtime = ProcessingWorkerRuntimeIdentityV1(
            worker_executable_digest=identity.worker_executable_digest,
            worker_build_digest=identity.worker_build_digest,
            runtime_image_version=identity.runtime_image_version,
            runtime_image_oci_digest=identity.runtime_image_oci_digest,
            dependency_lock_digest=identity.dependency_lock_digest,
        )
        started_monotonic = time.monotonic()
        with ExternalAnalysisCoreClient(
            base_url=core_server.base_url,
            worker_token="local-worker-token",
            worker_instance_id=_WORKER_ID,
        ) as client:
            assert client.list_pending()[0].analysis_id == _ANALYSIS_ID
            worked = run_once(client, runtime, policy, now=_Clock(step_millis=1))
            assert state.lease_acquisition_id is not None
            assert worked is True
        elapsed_wall_seconds = time.monotonic() - started_monotonic

    assert state.lease_acquisition_id is not None
    assert state.renew_calls >= 1
    assert state.renew_during_measurement >= 1
    assert state.report is not None
    assert state.report.attempt == state.renewed_attempt
    assert state.report.attempt_digest == state.renewed_attempt.canonical_digest()
    assert state.report.computed_at <= state.report.reported_at
    assert state.report.reported_at != renewed_attempt.issued_at
    assert state.report.reported_at <= state.renewed_attempt.lease_expires_at
    assert elapsed_wall_seconds >= 0.12
    assert state.report.numeric_result.metrics.cut_m3 == 1.0
    assert state.report.numeric_result.metrics.fill_m3 == 1.0
    assert state.report.numeric_result.metrics.net_m3 == 0.0
    assert state.report.numeric_result.coverage.common_valid_cell_count == 4


def test_run_once_joins_a_timed_out_measurement_renewal_before_the_next_core_call(
    tmp_path: Any, monkeypatch: Any
) -> None:
    """A slow renewal cannot leave an active daemon request behind after run-once."""
    envelope = _envelope().model_copy(
        update={"max_deadline_seconds": 0.3, "resource_envelope_digest": None}
    ).sealed()
    identity, state = _failure_state(
        tmp_path,
        expires_at=_START + timedelta(minutes=1),
        envelope=envelope,
    )
    baseline_bytes = (tmp_path / "baseline.tif").read_bytes()
    current_bytes = (tmp_path / "current.tif").read_bytes()
    import ksi_processing_controller.external_analysis_worker as worker_module
    from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient
    from ksi_processing_controller.external_analysis_worker import (
        ProcessingWorkerRuntimeIdentityV1,
        run_once,
    )

    actual_measurement = worker_module.measure_external_relative_volume_v2

    def wait_for_slow_renewal(**kwargs: Any) -> object:
        state.measurement_active = True
        try:
            # CI runners are slower than a warm local box; the bound only prevents a
            # hang, it is not the behavior under test.
            assert state.renew_started.wait(timeout=15)
            return actual_measurement(**kwargs)
        finally:
            state.measurement_active = False

    monkeypatch.setattr(
        worker_module, "measure_external_relative_volume_v2", wait_for_slow_renewal
    )
    runtime = ProcessingWorkerRuntimeIdentityV1(
        worker_executable_digest=identity.worker_executable_digest,
        worker_build_digest=identity.worker_build_digest,
        runtime_image_version=identity.runtime_image_version,
        runtime_image_oci_digest=identity.runtime_image_oci_digest,
        dependency_lock_digest=identity.dependency_lock_digest,
    )
    with _loopback_servers(state, {"/baseline": baseline_bytes, "/current": current_bytes}) as (
        core_server,
        object_server,
    ):
        state.input_value = state.input_value.model_copy(
            update={
                "inputs": (
                    state.input_value.inputs[0].model_copy(
                        update={"download_url": object_server.origin + "/baseline"}
                    ),
                    state.input_value.inputs[1].model_copy(
                        update={"download_url": object_server.origin + "/current"}
                    ),
                )
            }
        )
        state.slow_renew_during_measurement = True
        policy = ExternalObjectTransportPolicyV1(
            endpoints=(
                TrustedObjectEndpointV1(
                    origin=object_server.origin, addresses=("127.0.0.1",)
                ),
            ),
            max_header_bytes=4096,
            max_object_bytes=1_000_000,
            max_chunk_bytes=1024,
        )
        with ExternalAnalysisCoreClient(
            base_url=core_server.base_url,
            worker_token="local-worker-token",
            worker_instance_id=_WORKER_ID,
            request_timeout_seconds=0.04,
        ) as client:
            started_monotonic = time.monotonic()
            assert run_once(client, runtime, policy, now=_Clock()) is True
            elapsed_wall_seconds = time.monotonic() - started_monotonic
            assert state.renew_finished.wait(timeout=15)
            assert state.renew_inflight == 0
            assert client.list_pending()

    assert state.report is None
    assert state.failure is None
    assert elapsed_wall_seconds >= 0.04


def test_run_once_reports_runtime_identity_mismatch_as_a_current_fenced_failure(
    tmp_path: Any,
) -> None:
    """Removing local runtime identity comparison would report an untrusted calculation."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    current = _write_dsm(tmp_path / "current.tif", np.full((2, 2), 100.0))
    identity = _identity(baseline, current)
    initial_attempt = _attempt(identity).model_copy(
        update={
            "issued_at": _START,
            "lease_expires_at": _START + timedelta(minutes=2),
            "execution_attempt_digest": None,
        }
    ).sealed()
    renewed_attempt = initial_attempt.model_copy(
        update={
            "issued_at": _START + timedelta(seconds=1),
            "lease_expires_at": _START + timedelta(minutes=3),
            "execution_attempt_digest": None,
        }
    ).sealed()
    input_value = AnalysisWorkerInputV1(
        analysis_id=_ANALYSIS_ID,
        calculation_request_id=_REQUEST_ID,
        attempt=initial_attempt,
        calculation_identity=identity,
        inputs=(
            AnalysisWorkerInputCapabilityV1(
                role="BASELINE_DSM",
                artifact_id=identity.baseline_dsm_artifact_id,
                observed_sha256=identity.baseline_dsm_observed_sha256,
                observed_size_bytes=baseline.stat().st_size,
                download_url="http://127.0.0.1:1/baseline",
                required_headers={"X-Storage-Capability": "loopback-object-token"},
                expires_at=_START + timedelta(minutes=1),
            ),
            AnalysisWorkerInputCapabilityV1(
                role="CURRENT_DSM",
                artifact_id=identity.current_dsm_artifact_id,
                observed_sha256=identity.current_dsm_observed_sha256,
                observed_size_bytes=current.stat().st_size,
                download_url="http://127.0.0.1:1/current",
                required_headers={"X-Storage-Capability": "loopback-object-token"},
                expires_at=_START + timedelta(minutes=1),
            ),
        ),
    )
    state = _CoreState(
        initial_attempt=initial_attempt,
        renewed_attempt=renewed_attempt,
        input_value=input_value,
    )

    with _loopback_servers(state, {}) as (core_server, _object_server):
        from ksi_processing_controller.external_analysis_core_client import (
            ExternalAnalysisCoreClient,
        )
        from ksi_processing_controller.external_analysis_worker import (
            ProcessingWorkerRuntimeIdentityV1,
            run_once,
        )

        policy = ExternalObjectTransportPolicyV1(
            endpoints=(
                TrustedObjectEndpointV1(
                    origin="http://127.0.0.1:1", addresses=("127.0.0.1",)
                ),
            ),
            max_header_bytes=4096,
            max_object_bytes=1_000_000,
            max_chunk_bytes=1024,
        )
        runtime = ProcessingWorkerRuntimeIdentityV1(
            worker_executable_digest="sha256:" + "0" * 64,
            worker_build_digest=identity.worker_build_digest,
            runtime_image_version=identity.runtime_image_version,
            runtime_image_oci_digest=identity.runtime_image_oci_digest,
            dependency_lock_digest=identity.dependency_lock_digest,
        )
        with ExternalAnalysisCoreClient(
            base_url=core_server.base_url,
            worker_token="local-worker-token",
            worker_instance_id=_WORKER_ID,
        ) as client:
            assert run_once(client, runtime, policy, now=_Clock()) is True

    assert state.report is None
    assert state.failure is not None
    assert state.failure.reason_code == "RUNTIME_IDENTITY_MISMATCH"
    assert state.failure.attempt == state.renewed_attempt
    assert state.failure.attempt_digest == state.renewed_attempt.canonical_digest()


def test_run_once_reports_expired_capability_as_a_current_fenced_failure(
    tmp_path: Any,
) -> None:
    """Expired byte authority is rejected before any object connection opens."""
    identity, state = _failure_state(tmp_path, expires_at=_START)
    from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient
    from ksi_processing_controller.external_analysis_worker import (
        ProcessingWorkerRuntimeIdentityV1,
        run_once,
    )

    runtime = ProcessingWorkerRuntimeIdentityV1(
        worker_executable_digest=identity.worker_executable_digest,
        worker_build_digest=identity.worker_build_digest,
        runtime_image_version=identity.runtime_image_version,
        runtime_image_oci_digest=identity.runtime_image_oci_digest,
        dependency_lock_digest=identity.dependency_lock_digest,
    )
    with (
        _loopback_servers(state, {}) as (core_server, _object_server),
        ExternalAnalysisCoreClient(
            base_url=core_server.base_url,
            worker_token="local-worker-token",
            worker_instance_id=_WORKER_ID,
        ) as client,
    ):
        assert run_once(client, runtime, _unreachable_object_policy(), now=_Clock()) is True

    assert state.report is None
    assert state.failure is not None
    assert state.failure.reason_code == "INPUT_CAPABILITY_EXPIRED"
    assert state.failure.attempt == state.renewed_attempt


def test_run_once_rechecks_capability_expiry_before_each_actual_download(
    tmp_path: Any,
) -> None:
    """The second URL cannot be used after its short-lived authority expires."""
    identity, state = _failure_state(
        tmp_path,
        expires_at=_START + timedelta(milliseconds=15),
    )
    baseline_bytes = (tmp_path / "baseline.tif").read_bytes()
    current_bytes = (tmp_path / "current.tif").read_bytes()
    from ksi_processing_controller.external_analysis_core_client import (
        ExternalAnalysisCoreClient,
    )
    from ksi_processing_controller.external_analysis_worker import (
        ProcessingWorkerRuntimeIdentityV1,
        run_once,
    )

    runtime = ProcessingWorkerRuntimeIdentityV1(
        worker_executable_digest=identity.worker_executable_digest,
        worker_build_digest=identity.worker_build_digest,
        runtime_image_version=identity.runtime_image_version,
        runtime_image_oci_digest=identity.runtime_image_oci_digest,
        dependency_lock_digest=identity.dependency_lock_digest,
    )
    with _loopback_servers(
        state, {"/baseline": baseline_bytes, "/current": current_bytes}
    ) as (core_server, object_server):
        state.input_value = state.input_value.model_copy(
            update={
                "inputs": (
                    state.input_value.inputs[0].model_copy(
                        update={"download_url": object_server.origin + "/baseline"}
                    ),
                    state.input_value.inputs[1].model_copy(
                        update={"download_url": object_server.origin + "/current"}
                    ),
                )
            }
        )
        policy = ExternalObjectTransportPolicyV1(
            endpoints=(
                TrustedObjectEndpointV1(
                    origin=object_server.origin, addresses=("127.0.0.1",)
                ),
            ),
            max_header_bytes=4096,
            max_object_bytes=1_000_000,
            max_chunk_bytes=1024,
        )
        with ExternalAnalysisCoreClient(
            base_url=core_server.base_url,
            worker_token="local-worker-token",
            worker_instance_id=_WORKER_ID,
        ) as client:
            assert run_once(client, runtime, policy, now=_Clock()) is True

    assert state.report is None
    assert state.failure is not None
    assert state.failure.reason_code == "INPUT_CAPABILITY_EXPIRED"
    assert state.failure.attempt == state.renewed_attempt


def test_run_once_stops_a_delayed_byte_read_when_its_capability_expires(
    tmp_path: Any,
) -> None:
    """The byte-source currentness callback rejects expiry while waiting for a response."""
    identity, state = _failure_state(
        tmp_path,
        expires_at=_START + timedelta(milliseconds=35),
    )
    baseline_bytes = (tmp_path / "baseline.tif").read_bytes()
    current_bytes = (tmp_path / "current.tif").read_bytes()
    from ksi_processing_controller.external_analysis_core_client import (
        ExternalAnalysisCoreClient,
    )
    from ksi_processing_controller.external_analysis_worker import (
        ProcessingWorkerRuntimeIdentityV1,
        run_once,
    )

    runtime = ProcessingWorkerRuntimeIdentityV1(
        worker_executable_digest=identity.worker_executable_digest,
        worker_build_digest=identity.worker_build_digest,
        runtime_image_version=identity.runtime_image_version,
        runtime_image_oci_digest=identity.runtime_image_oci_digest,
        dependency_lock_digest=identity.dependency_lock_digest,
    )
    with _loopback_servers(
        state,
        {"/baseline": baseline_bytes, "/current": current_bytes},
        response_delay_seconds=0.075,
    ) as (core_server, object_server):
        state.input_value = state.input_value.model_copy(
            update={
                "inputs": (
                    state.input_value.inputs[0].model_copy(
                        update={"download_url": object_server.origin + "/baseline"}
                    ),
                    state.input_value.inputs[1].model_copy(
                        update={"download_url": object_server.origin + "/current"}
                    ),
                )
            }
        )
        policy = ExternalObjectTransportPolicyV1(
            endpoints=(
                TrustedObjectEndpointV1(
                    origin=object_server.origin, addresses=("127.0.0.1",)
                ),
            ),
            max_header_bytes=4096,
            max_object_bytes=1_000_000,
            max_chunk_bytes=1024,
        )
        with ExternalAnalysisCoreClient(
            base_url=core_server.base_url,
            worker_token="local-worker-token",
            worker_instance_id=_WORKER_ID,
        ) as client:
            assert run_once(client, runtime, policy, now=_Clock()) is True

    assert state.report is None
    assert state.failure is not None
    assert state.failure.reason_code == "INPUT_CAPABILITY_EXPIRED"
    assert state.failure.attempt == state.renewed_attempt


def test_run_once_lost_fence_leaves_no_terminal_result_or_private_workspace(
    tmp_path: Any, monkeypatch: Any
) -> None:
    """A 409 renewal during transfer cannot be retried, relabeled, or reported."""
    identity, state = _failure_state(tmp_path, expires_at=_START + timedelta(minutes=1))
    baseline_bytes = (tmp_path / "baseline.tif").read_bytes()
    current_bytes = (tmp_path / "current.tif").read_bytes()
    import ksi_processing_controller.external_analysis_worker as worker_module
    from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient
    from ksi_processing_controller.external_analysis_worker import (
        ProcessingWorkerRuntimeIdentityV1,
        run_once,
    )

    monkeypatch.setattr(worker_module.tempfile, "tempdir", str(tmp_path))
    runtime = ProcessingWorkerRuntimeIdentityV1(
        worker_executable_digest=identity.worker_executable_digest,
        worker_build_digest=identity.worker_build_digest,
        runtime_image_version=identity.runtime_image_version,
        runtime_image_oci_digest=identity.runtime_image_oci_digest,
        dependency_lock_digest=identity.dependency_lock_digest,
    )
    with _loopback_servers(state, {"/baseline": baseline_bytes, "/current": current_bytes}) as (
        core_server,
        object_server,
    ):
        state.input_value = state.input_value.model_copy(
            update={
                "inputs": (
                    state.input_value.inputs[0].model_copy(
                        update={"download_url": object_server.origin + "/baseline"}
                    ),
                    state.input_value.inputs[1].model_copy(
                        update={"download_url": object_server.origin + "/current"}
                    ),
                )
            }
        )
        state.lose_fence_on_renew = True
        policy = ExternalObjectTransportPolicyV1(
            endpoints=(
                TrustedObjectEndpointV1(
                    origin=object_server.origin, addresses=("127.0.0.1",)
                ),
            ),
            max_header_bytes=4096,
            max_object_bytes=1_000_000,
            max_chunk_bytes=1024,
        )
        with ExternalAnalysisCoreClient(
            base_url=core_server.base_url,
            worker_token="local-worker-token",
            worker_instance_id=_WORKER_ID,
        ) as client:
            assert run_once(client, runtime, policy, now=_Clock()) is True

    assert state.report is None
    assert state.failure is None
    assert not tuple(tmp_path.glob("ksi-analysis-*"))


def test_run_once_uses_one_monotonic_deadline_across_actual_object_downloads(
    tmp_path: Any,
) -> None:
    """Two separately bounded reads still share the sealed end-to-end budget."""
    envelope = _envelope().model_copy(
        update={"max_deadline_seconds": 0.1, "resource_envelope_digest": None}
    ).sealed()
    identity, state = _failure_state(
        tmp_path,
        expires_at=_START + timedelta(minutes=1),
        envelope=envelope,
    )
    baseline_bytes = (tmp_path / "baseline.tif").read_bytes()
    current_bytes = (tmp_path / "current.tif").read_bytes()
    from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient
    from ksi_processing_controller.external_analysis_worker import (
        ProcessingWorkerRuntimeIdentityV1,
        run_once,
    )

    runtime = ProcessingWorkerRuntimeIdentityV1(
        worker_executable_digest=identity.worker_executable_digest,
        worker_build_digest=identity.worker_build_digest,
        runtime_image_version=identity.runtime_image_version,
        runtime_image_oci_digest=identity.runtime_image_oci_digest,
        dependency_lock_digest=identity.dependency_lock_digest,
    )
    with _loopback_servers(
        state,
        {"/baseline": baseline_bytes, "/current": current_bytes},
        response_delay_seconds=0.075,
    ) as (core_server, object_server):
        state.input_value = state.input_value.model_copy(
            update={
                "inputs": (
                    state.input_value.inputs[0].model_copy(
                        update={"download_url": object_server.origin + "/baseline"}
                    ),
                    state.input_value.inputs[1].model_copy(
                        update={"download_url": object_server.origin + "/current"}
                    ),
                )
            }
        )
        policy = ExternalObjectTransportPolicyV1(
            endpoints=(
                TrustedObjectEndpointV1(
                    origin=object_server.origin, addresses=("127.0.0.1",)
                ),
            ),
            max_header_bytes=4096,
            max_object_bytes=1_000_000,
            max_chunk_bytes=1024,
        )
        with ExternalAnalysisCoreClient(
            base_url=core_server.base_url,
            worker_token="local-worker-token",
            worker_instance_id=_WORKER_ID,
        ) as client:
            started_monotonic = time.monotonic()
            assert run_once(client, runtime, policy, now=_Clock()) is True
            elapsed_wall_seconds = time.monotonic() - started_monotonic

    assert state.report is None
    assert state.failure is not None
    assert state.failure.reason_code == "MEASUREMENT_INCOMPLETE"
    assert state.failure.attempt == state.renewed_attempt
    assert 0.075 <= elapsed_wall_seconds < 0.5
