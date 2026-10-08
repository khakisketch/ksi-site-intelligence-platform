"""HIL-0 Core transport, route producer, and production runner gates."""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from ksi_dji_gateway import (
    AdapterRuntimeConfig,
    Capability,
    CapabilityUnavailableError,
    CoreRuntimeTransportConfig,
    GatewayTransport,
    GatewayTransportError,
    HttpCoreRuntimeObservationPublisher,
    HttpCoreRuntimeRoutePreflight,
    IntegrationPath,
    OperationKind,
    PsdkMopObservationConfig,
    PsdkMopRuntimeObservationProducer,
    RuntimeRoutePreflightRequest,
    UnixJsonBridgeClient,
)
from ksi_dji_gateway.runner import (
    RuntimeObservationLoop,
    _close_runner_resources,
    _handler,
    load_runner_config,
)


def _secret(path: Path, value: str = "token") -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def _preflight_request() -> RuntimeRoutePreflightRequest:
    return RuntimeRoutePreflightRequest(
        organization_id="org-1",
        site_id="site-1",
        gateway_device_id="gateway-1",
        edge_device_id="edge-1",
        canonical_capability=Capability.EDGE_UPLINK,
        integration_path=IntegrationPath.PSDK_MANIFOLD,
        subject_port_id="psdk-uplink",
        transport=GatewayTransport.MOP,
        hardware_model="gateway-model",
        firmware_version="firmware-1",
        mission_id="mission-1",
        operation=OperationKind.EDGE_UPLINK,
        idempotency_key="uplink-1",
        activation_authorization_id="activation-1",
    )


def _serve_once(body: object, *, status: int = 200) -> tuple[ThreadingHTTPServer, threading.Thread]:
    encoded = json.dumps(body).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.server.captured_path = self.path  # type: ignore[attr-defined]
            self.server.captured_auth = self.headers.get("Authorization")  # type: ignore[attr-defined]
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(status)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    return server, thread


def _transport(token: Path, port: int) -> HttpCoreRuntimeRoutePreflight:
    return HttpCoreRuntimeRoutePreflight(
        CoreRuntimeTransportConfig(
            core_url=f"http://127.0.0.1:{port}",
            token_file=token,
            allow_loopback_http=True,
        )
    )


def test_real_http_preflight_transport_is_authenticated_and_strict(tmp_path: Path) -> None:
    response = {
        "durableAuthorityValid": True,
        "currentRuntimeReady": True,
        "currentMissionPolicyAllows": True,
        "operationallyUsable": True,
        "newRouteInvocationAllowed": True,
        "reason": "OPERATIONALLY_USABLE",
        "existingSignedMissionContractEffect": "UNCHANGED",
    }
    server, thread = _serve_once(response)
    decision = _transport(_secret(tmp_path / "token"), server.server_port).evaluate(
        _preflight_request()
    )
    thread.join(timeout=2)
    server.server_close()
    assert decision.operationally_usable is True
    assert server.captured_path == "/v1/capability-runtime/preflight"  # type: ignore[attr-defined]
    assert server.captured_auth == "Bearer token"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("response", "status"),
    [
        ({"operationallyUsable": True}, 200),
        (
            {
                "durableAuthorityValid": True,
                "currentRuntimeReady": True,
                "currentMissionPolicyAllows": True,
                "operationallyUsable": False,
                "newRouteInvocationAllowed": True,
                "reason": "bad",
                "existingSignedMissionContractEffect": "UNCHANGED",
            },
            200,
        ),
        ({"detail": "unavailable"}, 503),
    ],
)
def test_preflight_malformed_contradictory_or_error_response_fails_closed(
    tmp_path: Path, response: object, status: int
) -> None:
    server, thread = _serve_once(response, status=status)
    client = _transport(_secret(tmp_path / f"token-{status}"), server.server_port)
    with pytest.raises(CapabilityUnavailableError):
        client.evaluate(_preflight_request())
    thread.join(timeout=2)
    server.server_close()


def test_preflight_core_unavailable_has_no_offline_fallback(tmp_path: Path) -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])
    client = _transport(_secret(tmp_path / "unavailable-token"), port)
    with pytest.raises(CapabilityUnavailableError):
        client.evaluate(_preflight_request())


def test_observation_publisher_uses_authenticated_cap5_ingress(tmp_path: Path) -> None:
    server, thread = _serve_once({"disposition": "RECORDED", "observation": {}})
    config = CoreRuntimeTransportConfig(
        core_url=f"http://127.0.0.1:{server.server_port}",
        token_file=_secret(tmp_path / "edge-token", "edge-secret"),
        allow_loopback_http=True,
    )
    response = HttpCoreRuntimeObservationPublisher(config).publish(
        {"observationId": "observation-1"}
    )
    thread.join(timeout=2)
    server.server_close()
    assert response["disposition"] == "RECORDED"
    assert server.captured_path == "/v1/capability-runtime/observations"  # type: ignore[attr-defined]
    assert server.captured_auth == "Bearer edge-secret"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "response",
    [
        {"disposition": "RECORDED"},
        {"disposition": "UNKNOWN", "observation": {}},
        {"disposition": "RECORDED", "observation": {}, "extra": True},
    ],
)
def test_observation_publisher_rejects_malformed_core_ack(
    tmp_path: Path, response: Mapping[str, Any]
) -> None:
    server, thread = _serve_once(response)
    publisher = HttpCoreRuntimeObservationPublisher(
        CoreRuntimeTransportConfig(
            core_url=f"http://127.0.0.1:{server.server_port}",
            token_file=_secret(tmp_path / "ack-token"),
            allow_loopback_http=True,
        )
    )
    with pytest.raises(GatewayTransportError):
        publisher.publish({"observationId": "observation-1"})
    thread.join(timeout=2)
    server.server_close()


def test_observation_publisher_auth_failure_is_not_available(tmp_path: Path) -> None:
    server, thread = _serve_once({"detail": "unauthorized"}, status=401)
    publisher = HttpCoreRuntimeObservationPublisher(
        CoreRuntimeTransportConfig(
            core_url=f"http://127.0.0.1:{server.server_port}",
            token_file=_secret(tmp_path / "rejected-token"),
            allow_loopback_http=True,
        )
    )
    with pytest.raises(GatewayTransportError, match="HTTP 401"):
        publisher.publish({"availability": "REPORTED_AVAILABLE"})
    thread.join(timeout=2)
    server.server_close()


class _Publisher:
    def __init__(self) -> None:
        self.items: list[Mapping[str, Any]] = []

    def publish(self, observation: Mapping[str, Any]) -> Mapping[str, Any]:
        self.items.append(observation)
        return {"disposition": "RECORDED"}


class _LoopProducer:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.called = threading.Event()
        self.fail = fail
        self.shutdown_requested = threading.Event()

    def prepare_start(self) -> None:
        self.shutdown_requested.clear()

    def request_shutdown(self) -> None:
        self.shutdown_requested.set()

    def observe_once(self) -> Mapping[str, Any]:
        self.calls += 1
        self.called.set()
        if self.fail:
            raise GatewayTransportError("Core unavailable")
        return {"availability": "REPORTED_AVAILABLE"}


def test_observation_loop_runs_stops_and_restarts_without_cached_allow() -> None:
    producer = _LoopProducer(fail=True)
    lifecycle = RuntimeObservationLoop(producer, poll_interval_s=0.01, stop_timeout_s=1)
    lifecycle.start()
    assert producer.called.wait(timeout=1)
    lifecycle.stop()
    assert lifecycle.running is False
    assert lifecycle.attempt_count >= 1
    assert lifecycle.last_error is not None

    producer.called.clear()
    producer.fail = False
    lifecycle.start()
    assert producer.called.wait(timeout=1)
    lifecycle.stop()
    assert lifecycle.last_error is None


class _BlockingLoopProducer(_LoopProducer):
    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def observe_once(self) -> Mapping[str, Any]:
        self.calls += 1
        self.called.set()
        self.release.wait()
        return {"availability": "REPORTED_AVAILABLE"}


def test_join_timeout_is_diagnostic_but_only_daemon_thread_survives() -> None:
    producer = _BlockingLoopProducer()
    lifecycle = RuntimeObservationLoop(producer, poll_interval_s=1, stop_timeout_s=0.01)
    lifecycle.start()
    assert producer.called.wait(timeout=1)
    with pytest.raises(RuntimeError, match="bounded shutdown"):
        lifecycle.stop()
    assert producer.shutdown_requested.is_set()
    assert lifecycle.last_error == "RuntimeError: bounded observation shutdown failed"
    assert all(
        thread.daemon
        for thread in threading.enumerate()
        if thread.name == "ksi-psdk-runtime-observation"
    )
    producer.release.set()
    deadline = time.monotonic() + 1
    while lifecycle.running and time.monotonic() < deadline:
        time.sleep(0.01)
    lifecycle.stop()
    lifecycle.stop()


def test_shutdown_during_blocked_probe_cannot_publish_late_available() -> None:
    entered = threading.Event()
    release = threading.Event()
    publisher = _Publisher()

    class BlockingClient:
        def route_status(self, *, subject_port_id: str, edge_device_id: str) -> Any:
            entered.set()
            release.wait(timeout=1)
            return type(
                "Signal",
                (),
                {
                    "signal_id": "signal-after-stop",
                    "observed_at": "2026-09-03T01:02:03Z",
                    "psdk_initialized": True,
                    "mop_connected": True,
                    "handler_registered": True,
                },
            )()

    producer = PsdkMopRuntimeObservationProducer(
        _observation_config(), client=BlockingClient(), publisher=publisher
    )
    lifecycle = RuntimeObservationLoop(producer, poll_interval_s=1, stop_timeout_s=0.01)
    lifecycle.start()
    assert entered.wait(timeout=1)
    with pytest.raises(RuntimeError, match="bounded shutdown"):
        lifecycle.stop()
    release.set()
    deadline = time.monotonic() + 1
    while lifecycle.running and time.monotonic() < deadline:
        time.sleep(0.01)
    lifecycle.stop()
    assert publisher.items == []


def test_core_publish_blocked_at_shutdown_cannot_start_another_attempt() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingPublisher:
        def __init__(self) -> None:
            self.calls = 0

        def publish(self, observation: Mapping[str, Any]) -> Mapping[str, Any]:
            self.calls += 1
            entered.set()
            release.wait(timeout=1)
            return {"disposition": "RECORDED"}

    class ImmediateClient:
        def route_status(self, *, subject_port_id: str, edge_device_id: str) -> Any:
            return type(
                "Signal",
                (),
                {
                    "signal_id": "signal-before-stop",
                    "observed_at": "2026-09-03T01:02:03Z",
                    "psdk_initialized": True,
                    "mop_connected": True,
                    "handler_registered": True,
                },
            )()

    publisher = BlockingPublisher()
    producer = PsdkMopRuntimeObservationProducer(
        _observation_config(), client=ImmediateClient(), publisher=publisher
    )
    lifecycle = RuntimeObservationLoop(producer, poll_interval_s=0.01, stop_timeout_s=0.01)
    lifecycle.start()
    assert entered.wait(timeout=1)
    with pytest.raises(RuntimeError, match="bounded shutdown"):
        lifecycle.stop()
    release.set()
    deadline = time.monotonic() + 1
    while lifecycle.running and time.monotonic() < deadline:
        time.sleep(0.01)
    lifecycle.stop()
    assert publisher.calls == 1


def test_runner_cleanup_closes_server_and_journal_after_stop_failure() -> None:
    closed: list[str] = []

    class FailingLoop:
        def stop(self) -> None:
            closed.append("loop")
            raise RuntimeError("original observation shutdown failure")

    class Server:
        def server_close(self) -> None:
            closed.append("server")

    class Journal:
        def close(self) -> None:
            closed.append("journal")

    config = type(
        "Config",
        (),
        {"observation_loop": FailingLoop(), "journal": Journal()},
    )()
    with pytest.raises(RuntimeError, match="original observation shutdown failure"):
        _close_runner_resources(config, Server())  # type: ignore[arg-type]
    assert closed == ["loop", "server", "journal"]


def _observation_config() -> PsdkMopObservationConfig:
    return PsdkMopObservationConfig(
        organization_id="org-1",
        site_id="site-1",
        edge_device_id="edge-1",
        subject_port_id="psdk-uplink",
        configured_deployment_digest="sha256:" + "a" * 64,
        equipment_scope_digest="sha256:" + "b" * 64,
        runtime_build_digest="sha256:" + "c" * 64,
        freshness_policy_id="psdk-fast-v1",
        freshness_policy_digest=(
            "sha256:6bcc0a41cf695816fe9e2dc50ac39c922119484aaaea1699050165da05d00865"
        ),
        producer_principal_id="edge-runtime-1",
        freshness_ttl_s=10,
        minimum_refresh_margin_s=2,
    )


def _psdk_client(socket_path: Path, *, timeout_s: float = 0.2) -> UnixJsonBridgeClient:
    return UnixJsonBridgeClient(
        AdapterRuntimeConfig(
            adapter_id="psdk-local",
            integration_path=IntegrationPath.PSDK_MANIFOLD,
            transport=GatewayTransport.MOP,
            organization_id="org-1",
            site_id="site-1",
            gateway_device_id="gateway-1",
            edge_device_id="edge-1",
            endpoint=f"unix://{socket_path}",
            timeout_s=timeout_s,
        )
    )


def _unix_signal_server(path: Path, response: Mapping[str, Any]) -> threading.Thread:
    ready = threading.Event()

    def serve() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            server.listen(1)
            ready.set()
            connection, _ = server.accept()
            with connection:
                while connection.recv(4096):
                    pass
                connection.sendall(json.dumps(response).encode())

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(timeout=1)
    return thread


def _unix_raw_server(
    path: Path, response: bytes, *, response_delay_s: float = 0
) -> threading.Thread:
    ready = threading.Event()

    def serve() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            server.listen(1)
            ready.set()
            connection, _ = server.accept()
            with connection:
                while connection.recv(4096):
                    pass
                if response_delay_s:
                    threading.Event().wait(response_delay_s)
                try:
                    connection.sendall(response)
                except BrokenPipeError:
                    return

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(timeout=1)
    return thread


def _route_signal(**updates: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "schemaVersion": "1.0",
        "signalId": "signal-1",
        "observedAt": "2026-09-03T01:02:03Z",
        "integrationPath": "PSDK_MANIFOLD",
        "canonicalCapabilityId": "EDGE_UPLINK",
        "subjectPortId": "psdk-uplink",
        "edgeDeviceId": "edge-1",
        "psdkInitialized": True,
        "mopConnected": True,
        "handlerRegistered": True,
    }
    raw.update(updates)
    return raw


def test_canonical_unix_client_returns_typed_route_status(tmp_path: Path) -> None:
    socket_path = tmp_path / "status.sock"
    thread = _unix_signal_server(socket_path, _route_signal(mopConnected=False))
    status = _psdk_client(socket_path).route_status(
        subject_port_id="psdk-uplink", edge_device_id="edge-1"
    )
    thread.join(timeout=2)
    assert status.psdk_initialized is True
    assert status.mop_connected is False
    assert status.handler_registered is True


@pytest.mark.parametrize(
    "response",
    [
        b"not-json",
        json.dumps({**_route_signal(), "extra": True}).encode(),
        json.dumps({k: v for k, v in _route_signal().items() if k != "signalId"}).encode(),
        json.dumps(_route_signal(schemaVersion="2.0")).encode(),
        json.dumps(_route_signal(integrationPath="MANIFOLD_DIRECT")).encode(),
        json.dumps(_route_signal(canonicalCapabilityId="MEDIA_PULL")).encode(),
        json.dumps(_route_signal(edgeDeviceId="edge-2")).encode(),
        json.dumps(_route_signal(subjectPortId="other-port")).encode(),
        json.dumps(_route_signal(mopConnected="true")).encode(),
        json.dumps(_route_signal(mopConnected=1)).encode(),
        json.dumps(_route_signal(mopConnected=float("nan"))).encode(),
        json.dumps(_route_signal(mopConnected=float("inf"))).encode(),
        json.dumps(_route_signal(signalId="bad signal id")).encode(),
        json.dumps(_route_signal(observedAt="not-a-time")).encode(),
        (
            b'{"schemaVersion":"1.0","schemaVersion":"1.0",'
            b'"signalId":"signal-1","observedAt":"2026-09-03T01:02:03Z",'
            b'"integrationPath":"PSDK_MANIFOLD",'
            b'"canonicalCapabilityId":"EDGE_UPLINK",'
            b'"subjectPortId":"psdk-uplink","edgeDeviceId":"edge-1",'
            b'"psdkInitialized":true,"mopConnected":true,'
            b'"handlerRegistered":true}'
        ),
    ],
)
def test_canonical_unix_status_rejects_hostile_exactness(tmp_path: Path, response: bytes) -> None:
    socket_path = tmp_path / "hostile.sock"
    thread = _unix_raw_server(socket_path, response)
    with pytest.raises(GatewayTransportError):
        _psdk_client(socket_path).route_status(
            subject_port_id="psdk-uplink", edge_device_id="edge-1"
        )
    thread.join(timeout=2)


def test_canonical_unix_status_rejects_oversize_and_timeout(tmp_path: Path) -> None:
    oversized_path = tmp_path / "oversized.sock"
    oversized = _unix_raw_server(oversized_path, b"x" * (64 * 1024 + 1))
    with pytest.raises(GatewayTransportError, match="64 KiB"):
        _psdk_client(oversized_path).route_status(
            subject_port_id="psdk-uplink", edge_device_id="edge-1"
        )
    oversized.join(timeout=2)

    timeout_path = tmp_path / "timeout.sock"
    timeout = _unix_raw_server(timeout_path, b"{}", response_delay_s=0.1)
    with pytest.raises(GatewayTransportError):
        _psdk_client(timeout_path, timeout_s=0.01).route_status(
            subject_port_id="psdk-uplink", edge_device_id="edge-1"
        )
    timeout.join(timeout=2)


@pytest.mark.parametrize("mask", range(8))
def test_psdk_producer_requires_all_eight_three_fact_combinations(
    tmp_path: Path, mask: int
) -> None:
    socket_path = tmp_path / "psdk.sock"
    updates = {
        "psdkInitialized": bool(mask & 1),
        "mopConnected": bool(mask & 2),
        "handlerRegistered": bool(mask & 4),
    }
    thread = _unix_signal_server(socket_path, _route_signal(**updates))
    publisher = _Publisher()
    producer = PsdkMopRuntimeObservationProducer(
        _observation_config(), client=_psdk_client(socket_path), publisher=publisher
    )
    observation = producer.observe_once()
    thread.join(timeout=2)
    assert observation["availability"] == (
        "REPORTED_AVAILABLE" if mask == 7 else "REPORTED_UNAVAILABLE"
    )
    assert observation["subjectPortId"] == "psdk-uplink"
    assert observation["integrationPath"] == "PSDK_MANIFOLD"
    assert observation["producerPrincipalKind"] == "EDGE_ROUTE_OBSERVER"
    assert publisher.items == [observation]


def test_psdk_producer_rejects_wrong_route_identity(tmp_path: Path) -> None:
    socket_path = tmp_path / "psdk.sock"
    thread = _unix_signal_server(socket_path, _route_signal(integrationPath="MANIFOLD_DIRECT"))
    publisher = _Publisher()
    observation = PsdkMopRuntimeObservationProducer(
        _observation_config(), client=_psdk_client(socket_path), publisher=publisher
    ).observe_once()
    thread.join(timeout=2)
    assert observation["availability"] == "REPORTED_UNAVAILABLE"


def test_missing_psdk_signal_reports_unavailable_never_available(tmp_path: Path) -> None:
    publisher = _Publisher()
    observation = PsdkMopRuntimeObservationProducer(
        _observation_config(),
        client=_psdk_client(tmp_path / "missing.sock"),
        publisher=publisher,
        clock=lambda: datetime(2026, 9, 3, 1, 2, 3, tzinfo=UTC),
    ).observe_once()
    assert observation["availability"] == "REPORTED_UNAVAILABLE"
    assert "probe-error" in str(observation["sourceObservationRef"])


def _runner_payload(
    tmp_path: Path,
    *,
    core_url: str = "https://core.example",
    unix_endpoint: str = "unix:///run/ksi/psdk.sock",
    allow_loopback_http: bool = False,
) -> dict[str, Any]:
    control = _secret(tmp_path / "control-token")
    preflight_token = _secret(tmp_path / "preflight-token", "gateway-preflight-token")
    observation_token = _secret(tmp_path / "observation-token", "edge-route-observer-token")
    return {
        "schemaVersion": "1.0",
        "listenHost": "127.0.0.1",
        "listenPort": 18080,
        "controlTokenFile": str(control),
        "journalPath": str(tmp_path / "gateway-journal.jsonl"),
        "core": {
            "url": core_url,
            "preflightTokenFile": str(preflight_token),
            "observationTokenFile": str(observation_token),
            "tlsCertificateSha256": None if allow_loopback_http else "e" * 64,
            "timeoutSeconds": 5,
            "allowLoopbackHttp": allow_loopback_http,
        },
        "deployment": {
            "organizationId": "org-1",
            "siteId": "site-1",
            "gatewayDeviceId": "gateway-1",
            "edgeDeviceId": "edge-1",
            "hardwareModel": "model-gateway",
            "firmwareVersion": "firmware-1",
        },
        "provider": {
            "adapterId": "psdk",
            "unixEndpoint": unix_endpoint,
            "timeoutSeconds": 2,
        },
        "route": {
            "featureEnabled": False,
            "activationAuthorizationId": "activation-1",
            "evidenceStatus": "BLOCKED",
            "evidenceRef": None,
            "evidenceCheckedAt": "2026-09-03T01:02:03Z",
        },
        "observation": {
            "subjectPortId": "psdk.edge_uplink",
            "configuredDeploymentDigest": "sha256:" + "a" * 64,
            "equipmentScopeDigest": "sha256:" + "b" * 64,
            "runtimeBuildDigest": "sha256:" + "c" * 64,
            "freshnessPolicyId": "psdk-fast-v1",
            "freshnessPolicyDigest": (
                "sha256:6bcc0a41cf695816fe9e2dc50ac39c922119484aaaea1699050165da05d00865"
            ),
            "producerPrincipalId": "edge-runtime-1",
            "freshnessTtlSeconds": 10,
            "minimumRefreshMarginSeconds": 2,
            "pollIntervalSeconds": 2,
        },
    }


def test_runner_requires_exact_owner_only_explicit_psdk_configuration(tmp_path: Path) -> None:
    config_path = tmp_path / "gateway.json"
    raw = _runner_payload(tmp_path)
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config_path.chmod(0o600)
    config = load_runner_config(config_path)
    assert config.observation_loop.running is False
    assert config.observation_loop.attempt_count == 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    connection.request("GET", "/health")
    assert json.loads(connection.getresponse().read()) == {"status": "alive"}
    connection.request("GET", "/ready")
    ready = json.loads(connection.getresponse().read())
    assert ready["serviceReady"] is True
    assert "not route authorization" in ready["warning"]
    connection.close()
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()
    config.journal.close()

    raw["unexpected"] = True
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="exact schema"):
        load_runner_config(config_path)

    raw.pop("unexpected")
    raw["core"]["observationTokenFile"] = raw["core"]["preflightTokenFile"]
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="token file은 분리"):
        load_runner_config(config_path)

    same_secret_dir = tmp_path / "same-secret"
    same_secret_dir.mkdir()
    raw = _runner_payload(same_secret_dir)
    Path(raw["core"]["observationTokenFile"]).write_text(
        "gateway-preflight-token", encoding="utf-8"
    )
    config_path = tmp_path / "same-secret-gateway.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config_path.chmod(0o600)
    with pytest.raises(ValueError, match="token secret은 역할별로 달라"):
        load_runner_config(config_path)

    margin_dir = tmp_path / "insufficient-margin"
    margin_dir.mkdir()
    raw = _runner_payload(margin_dir)
    raw["observation"]["pollIntervalSeconds"] = 9
    config_path = tmp_path / "insufficient-margin-gateway.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config_path.chmod(0o600)
    with pytest.raises(ValueError, match="refresh margin"):
        load_runner_config(config_path)

    policy_dir = tmp_path / "policy-content-mismatch"
    policy_dir.mkdir()
    raw = _runner_payload(policy_dir)
    raw["observation"]["freshnessTtlSeconds"] = 9
    config_path = tmp_path / "policy-content-mismatch-gateway.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config_path.chmod(0o600)
    with pytest.raises(ValueError, match="canonical content"):
        load_runner_config(config_path)

    invalid_observer_dir = tmp_path / "invalid-observer-principal-id"
    invalid_observer_dir.mkdir()
    raw = _runner_payload(invalid_observer_dir)
    raw["observation"]["producerPrincipalId"] = "route/observer"
    config_path = tmp_path / "invalid-observer-principal-id-gateway.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config_path.chmod(0o600)
    with pytest.raises(ValueError, match="producerPrincipalId.*path-safe"):
        load_runner_config(config_path)


def test_production_runner_observation_lifecycle_publishes_and_stops(
    tmp_path: Path,
) -> None:
    published = threading.Event()
    observations: list[Mapping[str, Any]] = []
    authorizations: list[str | None] = []

    class CoreHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers["Content-Length"])
            observation = json.loads(self.rfile.read(length))
            observations.append(observation)
            authorizations.append(self.headers.get("Authorization"))
            encoded = json.dumps({"disposition": "RECORDED", "observation": observation}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            published.set()

        def log_message(self, format: str, *args: object) -> None:
            return

    core = ThreadingHTTPServer(("127.0.0.1", 0), CoreHandler)
    core_thread = threading.Thread(target=core.serve_forever, daemon=True)
    core_thread.start()
    socket_path = tmp_path / "runner-psdk.sock"
    companion_thread = _unix_signal_server(
        socket_path, _route_signal(subjectPortId="psdk.edge_uplink")
    )
    raw = _runner_payload(
        tmp_path,
        core_url=f"http://127.0.0.1:{core.server_port}",
        unix_endpoint=f"unix://{socket_path}",
        allow_loopback_http=True,
    )
    config_path = tmp_path / "runner.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config_path.chmod(0o600)
    config = load_runner_config(config_path)
    try:
        config.observation_loop.start()
        assert published.wait(timeout=2)
        config.observation_loop.stop()
        assert config.observation_loop.running is False
        assert config.observation_loop.attempt_count == 1
        assert observations[0]["availability"] == "REPORTED_AVAILABLE"
        assert observations[0]["subjectPortId"] == "psdk.edge_uplink"
        assert observations[0]["producerPrincipalKind"] == "EDGE_ROUTE_OBSERVER"
        assert authorizations == ["Bearer edge-route-observer-token"]
    finally:
        if config.observation_loop.running:
            config.observation_loop.stop()
        config.journal.close()
        core.shutdown()
        core.server_close()
        core_thread.join(timeout=2)
        companion_thread.join(timeout=2)


def test_production_observation_lifecycle_core_outage_keeps_no_cached_available(
    tmp_path: Path,
) -> None:
    published = threading.Event()
    observations: list[Mapping[str, Any]] = []

    class CoreHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers["Content-Length"])
            observation = json.loads(self.rfile.read(length))
            observations.append(observation)
            encoded = json.dumps(
                {"disposition": "RECORDED", "observation": observation}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            published.set()

        def log_message(self, format: str, *args: object) -> None:
            return

    core = ThreadingHTTPServer(("127.0.0.1", 0), CoreHandler)
    core_thread = threading.Thread(target=core.serve_forever, daemon=True)
    core_thread.start()
    socket_path = tmp_path / "outage-psdk.sock"
    companion_thread = _unix_signal_server(
        socket_path, _route_signal(subjectPortId="psdk.edge_uplink")
    )
    raw = _runner_payload(
        tmp_path,
        core_url=f"http://127.0.0.1:{core.server_port}",
        unix_endpoint=f"unix://{socket_path}",
        allow_loopback_http=True,
    )
    raw["core"]["timeoutSeconds"] = 0.1
    raw["provider"]["timeoutSeconds"] = 0.1
    raw["observation"]["pollIntervalSeconds"] = 0.5
    config_path = tmp_path / "outage-runner.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config_path.chmod(0o600)
    config = load_runner_config(config_path)
    try:
        config.observation_loop.start()
        assert published.wait(timeout=2)
        assert observations[0]["availability"] == "REPORTED_AVAILABLE"

        core.shutdown()
        core.server_close()
        core_thread.join(timeout=2)
        deadline = time.monotonic() + 2
        while config.observation_loop.last_error is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert config.observation_loop.last_error is not None
        assert observations == [observations[0]]
        observed_at = datetime.fromisoformat(
            str(observations[0]["observedAt"]).replace("Z", "+00:00")
        )
        expires_at = datetime.fromisoformat(
            str(observations[0]["expiresAt"]).replace("Z", "+00:00")
        )
        assert expires_at - observed_at == timedelta(seconds=10)
    finally:
        config.observation_loop.stop()
        config.journal.close()
        core.shutdown()
        core.server_close()
        core_thread.join(timeout=2)
        companion_thread.join(timeout=2)
