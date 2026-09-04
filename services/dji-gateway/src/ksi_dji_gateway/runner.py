"""Minimum production DJI Gateway runner for the first HIL route.

Only PSDK/MOP EDGE_UPLINK is exposed and it remains behind field evidence,
feature flag, CAP-4 activation, CAP-5 observation, and Mission preflight gates.
The local HTTP command surface is loopback-only and bearer authenticated.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import signal
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol

from ksi_dji_gateway.adapters.catalog import build_candidate_ports
from ksi_dji_gateway.adapters.transport import AdapterRuntimeConfig, UnixJsonBridgeClient
from ksi_dji_gateway.coordinator import (
    CapabilityGateway,
    RouteActivationAuthorization,
    RoutingContext,
)
from ksi_dji_gateway.core_runtime import (
    CoreRuntimeTransportConfig,
    HttpCoreRuntimeObservationPublisher,
    HttpCoreRuntimeRoutePreflight,
    _validate_token_file,
)
from ksi_dji_gateway.domain.capabilities import (
    Capability,
    CapabilityEvidence,
    CapabilityRegistry,
    CapabilityStatus,
    GatewayTransport,
    IntegrationPath,
)
from ksi_dji_gateway.domain.models import EdgeUplinkRequest
from ksi_dji_gateway.errors import GatewayError, GatewayTransportError
from ksi_dji_gateway.persistence.journal import GatewayJournal
from ksi_dji_gateway.routing.capability_router import CapabilityRoute, CapabilityRouter
from ksi_dji_gateway.runtime_observation import (
    PsdkMopObservationConfig,
    PsdkMopRuntimeObservationProducer,
)

_MAX_REQUEST_BYTES = 64 * 1024


def _exact(raw: Any, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != fields:
        raise ValueError(f"{name} fields가 exact schema와 다르다")
    return raw


def _token_role_digest(path: Path) -> bytes:
    """Return only a normalized credential digest for role-separation checks."""

    _validate_token_file(path)
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("Core token file을 읽을 수 없다") from exc
    if not token or any(character.isspace() for character in token):
        raise ValueError("Core token file은 단일 비공백 token이어야 한다")
    return hashlib.sha256(token.encode()).digest()


class RuntimeObservationProducer(Protocol):
    def observe_once(self) -> Mapping[str, Any]: ...

    def prepare_start(self) -> None: ...

    def request_shutdown(self) -> None: ...


class RuntimeObservationLoop:
    """Bounded periodic observation publisher owned by the production runner."""

    def __init__(
        self,
        producer: RuntimeObservationProducer,
        *,
        poll_interval_s: float,
        stop_timeout_s: float,
    ) -> None:
        if not 0 < poll_interval_s <= 300:
            raise ValueError("observation poll interval은 0초 초과 300초 이하여야 한다")
        if not 0 < stop_timeout_s <= 95:
            raise ValueError("observation stop timeout이 유효하지 않다")
        self._producer = producer
        self._poll_interval_s = poll_interval_s
        self._stop_timeout_s = stop_timeout_s
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None
        self._attempt_count = 0

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def attempt_count(self) -> int:
        with self._lock:
            return self._attempt_count

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("observation lifecycle가 이미 실행 중이다")
            self._producer.prepare_start()
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="ksi-psdk-runtime-observation",
                # Every production I/O has a bounded timeout, but a defective
                # dependency or test double must still not pin process exit.
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
        if thread is None:
            return
        self._stop.set()
        self._producer.request_shutdown()
        thread.join(timeout=self._stop_timeout_s)
        if thread.is_alive():
            with self._lock:
                self._last_error = "RuntimeError: bounded observation shutdown failed"
            raise RuntimeError("observation lifecycle가 bounded shutdown에 실패했다")
        with self._lock:
            if self._thread is thread:
                self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            error: str | None = None
            try:
                self._producer.observe_once()
            except GatewayTransportError as exc:
                error = f"{type(exc).__name__}: observation publication failed"
            with self._lock:
                self._attempt_count += 1
                self._last_error = error
            if self._stop.wait(self._poll_interval_s):
                return


def _close_runner_resources(
    config: GatewayRunnerConfig, server: ThreadingHTTPServer
) -> None:
    """Attempt every shutdown action and then preserve the first failure.

    The observation lifecycle error is intentionally first: it is the most
    useful diagnostic for a publisher that failed to respect its bound, while
    server and journal cleanup must never be skipped because of it.
    """

    errors: list[BaseException] = []
    for cleanup in (
        config.observation_loop.stop,
        server.server_close,
        config.journal.close,
    ):
        try:
            cleanup()
        except BaseException as exc:  # noqa: BLE001 -- cleanup must continue
            errors.append(exc)
    if errors:
        raise errors[0]


@dataclass(frozen=True, slots=True)
class GatewayRunnerConfig:
    listen_host: str
    listen_port: int
    control_token_file: Path
    gateway: CapabilityGateway
    journal: GatewayJournal
    observation_loop: RuntimeObservationLoop


def load_runner_config(path: Path) -> GatewayRunnerConfig:
    """Load an owner-only exact config; missing/ambiguous values abort boot."""

    _validate_token_file(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Gateway config를 읽을 수 없다") from exc
    top = _exact(
        raw,
        {
            "schemaVersion",
            "listenHost",
            "listenPort",
            "controlTokenFile",
            "journalPath",
            "core",
            "deployment",
            "provider",
            "route",
            "observation",
        },
        "Gateway config",
    )
    if top["schemaVersion"] != "1.0" or top["listenHost"] not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        raise ValueError("Gateway runner는 schema 1.0과 loopback listen만 허용한다")
    if type(top["listenPort"]) is not int or not 1 <= top["listenPort"] <= 65535:
        raise ValueError("listenPort가 유효하지 않다")

    core = _exact(
        top["core"],
        {
            "url",
            "preflightTokenFile",
            "observationTokenFile",
            "tlsCertificateSha256",
            "timeoutSeconds",
            "allowLoopbackHttp",
        },
        "core",
    )
    if type(core["allowLoopbackHttp"]) is not bool:
        raise ValueError("allowLoopbackHttp는 boolean이어야 한다")
    preflight_token_path = Path(str(core["preflightTokenFile"]))
    observation_token_path = Path(str(core["observationTokenFile"]))
    if preflight_token_path.resolve() == observation_token_path.resolve():
        raise ValueError("preflight와 observation token file은 분리되어야 한다")
    if hmac.compare_digest(
        _token_role_digest(preflight_token_path),
        _token_role_digest(observation_token_path),
    ):
        raise ValueError("preflight와 observation token secret은 역할별로 달라야 한다")
    deployment = _exact(
        top["deployment"],
        {
            "organizationId",
            "siteId",
            "gatewayDeviceId",
            "edgeDeviceId",
            "hardwareModel",
            "firmwareVersion",
        },
        "deployment",
    )
    provider = _exact(
        top["provider"],
        {"adapterId", "unixEndpoint", "timeoutSeconds"},
        "provider",
    )
    route = _exact(
        top["route"],
        {
            "featureEnabled",
            "activationAuthorizationId",
            "evidenceStatus",
            "evidenceRef",
            "evidenceCheckedAt",
        },
        "route",
    )
    if type(route["featureEnabled"]) is not bool:
        raise ValueError("featureEnabled는 boolean이어야 한다")
    observation = _exact(
        top["observation"],
        {
            "subjectPortId",
            "configuredDeploymentDigest",
            "equipmentScopeDigest",
            "runtimeBuildDigest",
            "freshnessPolicyId",
            "freshnessPolicyDigest",
            "producerPrincipalId",
            "freshnessTtlSeconds",
            "minimumRefreshMarginSeconds",
            "pollIntervalSeconds",
        },
        "observation",
    )
    expected_subject_port_id = f"{provider['adapterId']}.edge_uplink"
    if observation["subjectPortId"] != expected_subject_port_id:
        raise ValueError("observation subjectPortId가 exact provider route port와 다르다")
    if (
        type(observation["freshnessTtlSeconds"]) is not int
        or type(observation["minimumRefreshMarginSeconds"]) not in {int, float}
        or type(observation["pollIntervalSeconds"]) not in {int, float}
        or float(observation["minimumRefreshMarginSeconds"]) <= 0
        or float(observation["pollIntervalSeconds"]) <= 0
        or float(observation["pollIntervalSeconds"])
        + float(observation["minimumRefreshMarginSeconds"])
        > observation["freshnessTtlSeconds"]
    ):
        raise ValueError(
            "observation poll interval은 explicit refresh margin을 남겨야 한다"
        )

    adapter_config = AdapterRuntimeConfig(
        adapter_id=str(provider["adapterId"]),
        integration_path=IntegrationPath.PSDK_MANIFOLD,
        transport=GatewayTransport.MOP,
        organization_id=str(deployment["organizationId"]),
        site_id=str(deployment["siteId"]),
        gateway_device_id=str(deployment["gatewayDeviceId"]),
        edge_device_id=str(deployment["edgeDeviceId"]),
        endpoint=str(provider["unixEndpoint"]),
        timeout_s=float(provider["timeoutSeconds"]),
    )
    companion_client = UnixJsonBridgeClient(adapter_config)
    ports = build_candidate_ports(adapter_config, companion_client)
    evidence = CapabilityEvidence(
        path=IntegrationPath.PSDK_MANIFOLD,
        capability=Capability.EDGE_UPLINK,
        status=CapabilityStatus(str(route["evidenceStatus"])),
        checked_at=str(route["evidenceCheckedAt"]),
        evidence_ref=(str(route["evidenceRef"]) if route["evidenceRef"] is not None else None),
        hardware_model=str(deployment["hardwareModel"]),
        firmware_version=str(deployment["firmwareVersion"]),
    )
    registry = CapabilityRegistry([evidence])
    router = CapabilityRouter(
        routes=tuple(
            CapabilityRoute(port=port, priority=index) for index, port in enumerate(ports)
        ),
        registry=registry,
        feature_flags={Capability.EDGE_UPLINK: route["featureEnabled"]},
    )
    context = RoutingContext(
        organization_id=str(deployment["organizationId"]),
        site_id=str(deployment["siteId"]),
        gateway_device_id=str(deployment["gatewayDeviceId"]),
        edge_device_id=str(deployment["edgeDeviceId"]),
        hardware_model=str(deployment["hardwareModel"]),
        firmware_version=str(deployment["firmwareVersion"]),
        allowed_transports=frozenset({GatewayTransport.MOP}),
        activation_authorizations=(
            RouteActivationAuthorization(
                canonical_capability=Capability.EDGE_UPLINK,
                integration_path=IntegrationPath.PSDK_MANIFOLD,
                activation_authorization_id=str(route["activationAuthorizationId"]),
            ),
        ),
    )
    preflight_core_config = CoreRuntimeTransportConfig(
        core_url=str(core["url"]),
        token_file=preflight_token_path,
        tls_certificate_sha256=(
            str(core["tlsCertificateSha256"]) if core["tlsCertificateSha256"] is not None else None
        ),
        timeout_s=float(core["timeoutSeconds"]),
        allow_loopback_http=core["allowLoopbackHttp"],
    )
    observation_core_config = CoreRuntimeTransportConfig(
        core_url=str(core["url"]),
        token_file=observation_token_path,
        tls_certificate_sha256=(
            str(core["tlsCertificateSha256"]) if core["tlsCertificateSha256"] is not None else None
        ),
        timeout_s=float(core["timeoutSeconds"]),
        allow_loopback_http=core["allowLoopbackHttp"],
    )
    observation_config = PsdkMopObservationConfig(
        organization_id=str(deployment["organizationId"]),
        site_id=str(deployment["siteId"]),
        edge_device_id=str(deployment["edgeDeviceId"]),
        subject_port_id=str(observation["subjectPortId"]),
        configured_deployment_digest=str(observation["configuredDeploymentDigest"]),
        equipment_scope_digest=str(observation["equipmentScopeDigest"]),
        runtime_build_digest=str(observation["runtimeBuildDigest"]),
        freshness_policy_id=str(observation["freshnessPolicyId"]),
        freshness_policy_digest=str(observation["freshnessPolicyDigest"]),
        producer_principal_id=str(observation["producerPrincipalId"]),
        freshness_ttl_s=observation["freshnessTtlSeconds"],
        minimum_refresh_margin_s=float(observation["minimumRefreshMarginSeconds"]),
    )
    observation_producer = PsdkMopRuntimeObservationProducer(
        observation_config,
        client=companion_client,
        publisher=HttpCoreRuntimeObservationPublisher(observation_core_config),
    )
    observation_loop = RuntimeObservationLoop(
        observation_producer,
        poll_interval_s=float(observation["pollIntervalSeconds"]),
        stop_timeout_s=float(core["timeoutSeconds"]) + float(provider["timeoutSeconds"]) + 1.0,
    )
    journal = GatewayJournal(Path(str(top["journalPath"])))
    gateway = CapabilityGateway(
        router=router,
        journal=journal,
        context=context,
        runtime_preflight=HttpCoreRuntimeRoutePreflight(preflight_core_config),
    )
    control_token_file = Path(str(top["controlTokenFile"]))
    _validate_token_file(control_token_file)
    return GatewayRunnerConfig(
        listen_host=str(top["listenHost"]),
        listen_port=top["listenPort"],
        control_token_file=control_token_file,
        gateway=gateway,
        journal=journal,
        observation_loop=observation_loop,
    )


def _control_token(path: Path) -> str:
    _validate_token_file(path)
    value = path.read_text(encoding="utf-8").strip()
    if not value or any(character.isspace() for character in value):
        raise ValueError("control token file은 단일 비공백 token이어야 한다")
    return value


def _handler(config: GatewayRunnerConfig) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "KsiDjiGateway/1.0"

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._json(HTTPStatus.OK, {"status": "alive"})
            elif self.path == "/ready":
                self._json(
                    HTTPStatus.OK,
                    {
                        "serviceReady": True,
                        "route": "PSDK_MANIFOLD/EDGE_UPLINK",
                        "warning": "readiness is not route authorization or HIL evidence",
                    },
                )
            else:
                self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/edge-uplink":
                self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
                return
            expected = f"Bearer {_control_token(config.control_token_file)}"
            if not hmac.compare_digest(self.headers.get("Authorization", ""), expected):
                self._json(HTTPStatus.UNAUTHORIZED, {"detail": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
                if not 0 <= length <= _MAX_REQUEST_BYTES:
                    raise ValueError("invalid content length")
                raw = _exact(
                    json.loads(self.rfile.read(length)),
                    {
                        "organizationId",
                        "siteId",
                        "missionId",
                        "edgeDeviceId",
                        "bundleObjectRef",
                        "bundleSha256",
                        "idempotencyKey",
                    },
                    "edge uplink request",
                )
                receipt = config.gateway.upload_edge_bundle(
                    EdgeUplinkRequest(
                        organization_id=str(raw["organizationId"]),
                        site_id=str(raw["siteId"]),
                        mission_id=str(raw["missionId"]),
                        edge_device_id=str(raw["edgeDeviceId"]),
                        bundle_object_ref=str(raw["bundleObjectRef"]),
                        bundle_sha256=str(raw["bundleSha256"]),
                        idempotency_key=str(raw["idempotencyKey"]),
                    )
                )
            except (GatewayError, ValueError, TypeError, json.JSONDecodeError):
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"detail": "route unavailable"})
                return
            self._json(
                HTTPStatus.OK,
                {
                    "operation": receipt.operation.value,
                    "path": receipt.path.value,
                    "idempotencyKey": receipt.idempotency_key,
                    "providerOperationId": receipt.provider_operation_id,
                    "acceptedAt": receipt.accepted_at,
                    "itemCount": receipt.item_count,
                },
            )

        def log_message(self, format: str, *args: object) -> None:
            # Do not print credentials or request bodies. The runner's outer
            # service manager owns structured access logging.
            return

        def _json(self, status: HTTPStatus, body: Mapping[str, Any]) -> None:
            encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="KSI production DJI Gateway runner")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = load_runner_config(args.config)
    server = ThreadingHTTPServer((config.listen_host, config.listen_port), _handler(config))
    config.observation_loop.start()
    # BaseServer.shutdown() must run from a different thread than
    # serve_forever(); invoking it directly in the main-thread signal handler
    # deadlocks during container termination.
    signal.signal(
        signal.SIGTERM,
        lambda *_args: threading.Thread(target=server.shutdown, daemon=True).start(),
    )
    try:
        server.serve_forever()
    finally:
        _close_runner_resources(config, server)


if __name__ == "__main__":
    main()
