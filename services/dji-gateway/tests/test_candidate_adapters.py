"""Candidate adapter catalog, concrete bridge and coordinator safety gates."""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from ksi_dji_gateway import (
    CANDIDATE_PATH_CAPABILITIES,
    AdapterRuntimeConfig,
    BridgeOperation,
    Capability,
    CapabilityEvidence,
    CapabilityGateway,
    CapabilityRegistry,
    CapabilityRoute,
    CapabilityRouter,
    CapabilityStatus,
    CapabilityUnavailableError,
    EdgeUplinkRequest,
    GatewayJournal,
    GatewayTransport,
    IntegrationPath,
    OperationKind,
    ProviderReceipt,
    RouteActivationAuthorization,
    RoutingContext,
    RuntimeRoutePreflightDecision,
    RuntimeRoutePreflightRequest,
    UnixJsonBridgeClient,
    build_candidate_ports,
)

_NOW = "2026-08-26T09:00:00+00:00"


class _RecordingBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[BridgeOperation, str, Mapping[str, Any]]] = []

    def invoke(
        self,
        *,
        operation: BridgeOperation,
        idempotency_key: str,
        payload: Mapping[str, Any],
    ) -> ProviderReceipt:
        self.calls.append((operation, idempotency_key, payload))
        return ProviderReceipt(
            provider_operation_id=f"provider-{idempotency_key}",
            accepted_at=_NOW,
            item_count=1,
            manifest_ref=None,
        )


class _RecordingRuntimePreflight:
    def __init__(self, response: object, *, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.requests: list[RuntimeRoutePreflightRequest] = []

    def evaluate(self, request: RuntimeRoutePreflightRequest) -> RuntimeRoutePreflightDecision:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return cast(RuntimeRoutePreflightDecision, self.response)


def _all_true_preflight_decision() -> RuntimeRoutePreflightDecision:
    return RuntimeRoutePreflightDecision(
        durable_authority_valid=True,
        current_runtime_ready=True,
        current_mission_policy_allows=True,
        operationally_usable=True,
    )


def _edge_uplink_request(idempotency_key: str = "edge-uplink-1") -> EdgeUplinkRequest:
    return EdgeUplinkRequest(
        organization_id="org-a",
        site_id="site-a",
        mission_id="mission-a",
        edge_device_id="edge-a",
        bundle_object_ref="objects/bundles/edge-a.json",
        bundle_sha256="b" * 64,
        idempotency_key=idempotency_key,
    )


def _config(path: IntegrationPath) -> AdapterRuntimeConfig:
    transports = {
        IntegrationPath.DJI_CLOUD: GatewayTransport.RC_WIFI,
        IntegrationPath.PSDK_MANIFOLD: GatewayTransport.MOP,
        IntegrationPath.MANIFOLD_DIRECT: GatewayTransport.MANIFOLD_CELLULAR,
        IntegrationPath.MSDK_FIELD: GatewayTransport.MOP,
        IntegrationPath.DJI_DOCK: GatewayTransport.DOCK_ETHERNET,
    }
    if path is IntegrationPath.PSDK_MANIFOLD:
        endpoint = "unix:///run/ksi/psdk-bridge.sock"
        pin = None
    else:
        endpoint = f"https://bridge.invalid/{path.value.lower()}"
        pin = "a" * 64
    return AdapterRuntimeConfig(
        adapter_id=f"candidate-{path.value.lower()}",
        integration_path=path,
        transport=transports[path],
        organization_id="org-a",
        site_id="site-a",
        gateway_device_id="gateway-a",
        edge_device_id="edge-a",
        endpoint=endpoint,
        tls_certificate_sha256=pin,
    )


def _cap5_edge_uplink_gateway(
    tmp_path: Path,
    *,
    bridge: _RecordingBridge,
    feature_enabled: bool,
    runtime_preflight: _RecordingRuntimePreflight | None,
    activation_authorizations: tuple[RouteActivationAuthorization, ...],
) -> tuple[CapabilityGateway, GatewayJournal, CapabilityRouter]:
    config = _config(IntegrationPath.MANIFOLD_DIRECT)
    ports = build_candidate_ports(config, bridge)
    router = CapabilityRouter(
        routes=tuple(CapabilityRoute(port, index) for index, port in enumerate(ports)),
        registry=CapabilityRegistry(
            [
                CapabilityEvidence(
                    path=IntegrationPath.MANIFOLD_DIRECT,
                    capability=Capability.EDGE_UPLINK,
                    status=CapabilityStatus.VERIFIED,
                    checked_at=_NOW,
                    evidence_ref="hil/session/edge-uplink.json",
                    hardware_model="M4D+M3+RC2",
                    firmware_version="firmware-1",
                )
            ]
        ),
        feature_flags={Capability.EDGE_UPLINK: feature_enabled},
    )
    journal = GatewayJournal(tmp_path / "gateway.jsonl")
    return (
        CapabilityGateway(
            router=router,
            journal=journal,
            context=RoutingContext(
                organization_id="org-a",
                site_id="site-a",
                gateway_device_id="gateway-a",
                edge_device_id="edge-a",
                hardware_model="M4D+M3+RC2",
                firmware_version="firmware-1",
                allowed_transports=frozenset({GatewayTransport.MANIFOLD_CELLULAR}),
                activation_authorizations=activation_authorizations,
            ),
            runtime_preflight=runtime_preflight,
        ),
        journal,
        router,
    )


def _edge_uplink_activation() -> RouteActivationAuthorization:
    return RouteActivationAuthorization(
        canonical_capability=Capability.EDGE_UPLINK,
        integration_path=IntegrationPath.MANIFOLD_DIRECT,
        activation_authorization_id="activation-edge-uplink-direct-1",
    )


def test_catalog_covers_all_paths_without_inferred_capabilities() -> None:
    assert set(CANDIDATE_PATH_CAPABILITIES) == set(IntegrationPath)
    assert Capability.WAYLINE_DELIVERY not in CANDIDATE_PATH_CAPABILITIES[
        IntegrationPath.DJI_CLOUD
    ]
    assert Capability.EDGE_DOWNLINK not in CANDIDATE_PATH_CAPABILITIES[
        IntegrationPath.PSDK_MANIFOLD
    ]
    assert CANDIDATE_PATH_CAPABILITIES[IntegrationPath.DJI_DOCK].isdisjoint(
        {Capability.EDGE_DOWNLINK, Capability.EDGE_UPLINK}
    )
    assert set(BridgeOperation) == {
        BridgeOperation.WAYLINE_UPLOAD_NO_START,
        BridgeOperation.SIGNED_CONTRACT_TRANSFER,
        BridgeOperation.EDGE_BUNDLE_UPLOAD,
        BridgeOperation.MEDIA_READ_ONE,
        BridgeOperation.MEDIA_UPLOAD_SYNTHETIC,
    }


@pytest.mark.parametrize("path", list(IntegrationPath))
def test_every_path_builds_only_single_capability_ports(path: IntegrationPath) -> None:
    ports = build_candidate_ports(_config(path), _RecordingBridge())
    advertised = frozenset(capability for port in ports for capability in port.capabilities)
    assert advertised == CANDIDATE_PATH_CAPABILITIES[path]
    assert all(len(port.capabilities) == 1 for port in ports)
    assert all(port.configuration_ready for port in ports)


def test_runtime_config_rejects_unpinned_http_query_and_open_secret(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="장치 신원"):
        AdapterRuntimeConfig(
            adapter_id="same-device",
            integration_path=IntegrationPath.MANIFOLD_DIRECT,
            transport=GatewayTransport.MANIFOLD_CELLULAR,
            organization_id="org-a",
            site_id="site-a",
            gateway_device_id="device-a",
            edge_device_id="device-a",
            endpoint="https://bridge.invalid",
            tls_certificate_sha256="a" * 64,
        )
    with pytest.raises(ValueError, match="https 또는 unix"):
        AdapterRuntimeConfig(
            adapter_id="bad-http",
            integration_path=IntegrationPath.MANIFOLD_DIRECT,
            transport=GatewayTransport.MANIFOLD_CELLULAR,
            organization_id="org-a",
            site_id="site-a",
            gateway_device_id="gateway-a",
            edge_device_id="edge-a",
            endpoint="http://bridge.invalid",
        )
    with pytest.raises(ValueError, match="query"):
        AdapterRuntimeConfig(
            adapter_id="bad-query",
            integration_path=IntegrationPath.DJI_CLOUD,
            transport=GatewayTransport.RC_WIFI,
            organization_id="org-a",
            site_id="site-a",
            gateway_device_id="gateway-a",
            edge_device_id="edge-a",
            endpoint="https://bridge.invalid/api?token=secret",
            tls_certificate_sha256="a" * 64,
        )
    with pytest.raises(ValueError, match="certificate"):
        AdapterRuntimeConfig(
            adapter_id="bad-pin",
            integration_path=IntegrationPath.DJI_DOCK,
            transport=GatewayTransport.DOCK_ETHERNET,
            organization_id="org-a",
            site_id="site-a",
            gateway_device_id="gateway-a",
            edge_device_id="edge-a",
            endpoint="https://bridge.invalid",
        )
    secret = tmp_path / "token"
    secret.write_text("secret-token\n", encoding="utf-8")
    secret.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        AdapterRuntimeConfig(
            adapter_id="bad-secret",
            integration_path=IntegrationPath.DJI_CLOUD,
            transport=GatewayTransport.RC_WIFI,
            organization_id="org-a",
            site_id="site-a",
            gateway_device_id="gateway-a",
            edge_device_id="edge-a",
            endpoint="https://bridge.invalid",
            tls_certificate_sha256="a" * 64,
            credential_file=secret,
        )


def test_router_rejects_unconfigured_port_even_with_evidence_and_flag() -> None:
    class _UnconfiguredPort:
        port_id = "unconfigured"
        integration_path = IntegrationPath.MANIFOLD_DIRECT
        transport = GatewayTransport.MANIFOLD_CELLULAR
        capabilities = frozenset({Capability.EDGE_UPLINK})
        configuration_ready = False
        organization_id = "org-a"
        site_id = "site-a"
        gateway_device_id = "gateway-a"
        edge_device_id = "edge-a"

    router = CapabilityRouter(
        routes=(CapabilityRoute(_UnconfiguredPort(), 0),),
        registry=CapabilityRegistry(
            [
                CapabilityEvidence(
                    path=IntegrationPath.MANIFOLD_DIRECT,
                    capability=Capability.EDGE_UPLINK,
                    status=CapabilityStatus.VERIFIED,
                    checked_at=_NOW,
                    evidence_ref="hil/session/edge-uplink.json",
                    hardware_model="M4D+M3+RC2",
                    firmware_version="firmware-1",
                )
            ]
        ),
        feature_flags={Capability.EDGE_UPLINK: True},
    )
    with pytest.raises(CapabilityUnavailableError, match="configuration"):
        router.select(
            Capability.EDGE_UPLINK,
            organization_id="org-a",
            site_id="site-a",
            gateway_device_id="gateway-a",
            edge_device_id="edge-a",
            hardware_model="M4D+M3+RC2",
            firmware_version="firmware-1",
            allowed_transports=frozenset({GatewayTransport.MANIFOLD_CELLULAR}),
        )


def test_cap5_preflight_applies_only_to_new_port_invoke_and_replays_receipt(tmp_path: Path) -> None:
    bridge = _RecordingBridge()
    preflight = _RecordingRuntimePreflight(_all_true_preflight_decision())
    gateway, journal, router = _cap5_edge_uplink_gateway(
        tmp_path,
        bridge=bridge,
        feature_enabled=True,
        runtime_preflight=preflight,
        activation_authorizations=(_edge_uplink_activation(),),
    )
    with pytest.raises(CapabilityUnavailableError, match="binding"):
        router.select(
            Capability.EDGE_UPLINK,
            organization_id="org-a",
            site_id="site-b",
            gateway_device_id="gateway-a",
            edge_device_id="edge-a",
            hardware_model="M4D+M3+RC2",
            firmware_version="firmware-1",
            allowed_transports=frozenset({GatewayTransport.MANIFOLD_CELLULAR}),
        )
    request = _edge_uplink_request()
    with pytest.raises(CapabilityUnavailableError, match="scope"):
        gateway.upload_edge_bundle(replace(request, organization_id="org-b"))
    with pytest.raises(CapabilityUnavailableError, match="scope"):
        gateway.upload_edge_bundle(replace(request, edge_device_id="edge-b"))
    assert bridge.calls == []
    first = gateway.upload_edge_bundle(request)
    second = gateway.upload_edge_bundle(request)
    assert first == second
    assert first.capability is Capability.EDGE_UPLINK
    assert first.transport is GatewayTransport.MANIFOLD_CELLULAR
    assert first.journal_schema_version == "1.3"
    assert len(bridge.calls) == 1
    assert bridge.calls[0][0] is BridgeOperation.EDGE_BUNDLE_UPLOAD
    assert len(preflight.requests) == 1
    preflight_request = preflight.requests[0]
    assert preflight_request.organization_id == "org-a"
    assert preflight_request.site_id == "site-a"
    assert preflight_request.gateway_device_id == "gateway-a"
    assert preflight_request.edge_device_id == "edge-a"
    assert preflight_request.canonical_capability is Capability.EDGE_UPLINK
    assert preflight_request.integration_path is IntegrationPath.MANIFOLD_DIRECT
    assert preflight_request.subject_port_id == "candidate-manifold_direct.edge_uplink"
    assert preflight_request.transport is GatewayTransport.MANIFOLD_CELLULAR
    assert preflight_request.hardware_model == "M4D+M3+RC2"
    assert preflight_request.firmware_version == "firmware-1"
    assert preflight_request.mission_id == "mission-a"
    assert preflight_request.operation is OperationKind.EDGE_UPLINK
    assert preflight_request.idempotency_key == "edge-uplink-1"
    assert preflight_request.activation_authorization_id == "activation-edge-uplink-direct-1"
    journal.close()


def test_runtime_preflight_decision_rejects_nonconjunctive_operationally_usable() -> None:
    with pytest.raises(ValueError, match="operationally_usable"):
        RuntimeRoutePreflightDecision(
            durable_authority_valid=True,
            current_runtime_ready=False,
            current_mission_policy_allows=True,
            operationally_usable=True,
        )


@pytest.mark.parametrize(
    ("feature_enabled", "decision"),
    [
        (False, _all_true_preflight_decision()),
        (
            True,
            RuntimeRoutePreflightDecision(
                durable_authority_valid=False,
                current_runtime_ready=True,
                current_mission_policy_allows=True,
                operationally_usable=False,
            ),
        ),
        (
            True,
            RuntimeRoutePreflightDecision(
                durable_authority_valid=True,
                current_runtime_ready=False,
                current_mission_policy_allows=True,
                operationally_usable=False,
            ),
        ),
        (
            True,
            RuntimeRoutePreflightDecision(
                durable_authority_valid=True,
                current_runtime_ready=True,
                current_mission_policy_allows=False,
                operationally_usable=False,
            ),
        ),
    ],
    ids=(
        "feature-flag-off",
        "durable-authority-invalid",
        "runtime-not-ready",
        "mission-policy-deny",
    ),
)
def test_cap5_requires_each_operational_prerequisite(
    tmp_path: Path,
    feature_enabled: bool,
    decision: RuntimeRoutePreflightDecision,
) -> None:
    bridge = _RecordingBridge()
    preflight = _RecordingRuntimePreflight(decision)
    gateway, journal, _router = _cap5_edge_uplink_gateway(
        tmp_path,
        bridge=bridge,
        feature_enabled=feature_enabled,
        runtime_preflight=preflight,
        activation_authorizations=(_edge_uplink_activation(),),
    )

    with pytest.raises(CapabilityUnavailableError):
        gateway.upload_edge_bundle(_edge_uplink_request())

    assert bridge.calls == []
    assert len(preflight.requests) == int(feature_enabled)
    journal.close()


def test_cap5_preflight_exception_fails_closed_before_bridge_invocation(
    tmp_path: Path,
) -> None:
    bridge = _RecordingBridge()
    preflight = _RecordingRuntimePreflight(
        _all_true_preflight_decision(), error=RuntimeError("Core preflight unavailable")
    )
    gateway, journal, _router = _cap5_edge_uplink_gateway(
        tmp_path,
        bridge=bridge,
        feature_enabled=True,
        runtime_preflight=preflight,
        activation_authorizations=(_edge_uplink_activation(),),
    )

    with pytest.raises(CapabilityUnavailableError, match="fail-closed"):
        gateway.upload_edge_bundle(_edge_uplink_request())

    assert len(preflight.requests) == 1
    assert bridge.calls == []
    journal.close()


def test_cap5_truthy_untyped_preflight_response_fails_closed_before_bridge_invocation(
    tmp_path: Path,
) -> None:
    bridge = _RecordingBridge()
    preflight = _RecordingRuntimePreflight(True)
    gateway, journal, _router = _cap5_edge_uplink_gateway(
        tmp_path,
        bridge=bridge,
        feature_enabled=True,
        runtime_preflight=preflight,
        activation_authorizations=(_edge_uplink_activation(),),
    )

    with pytest.raises(CapabilityUnavailableError, match="typed decision"):
        gateway.upload_edge_bundle(_edge_uplink_request())

    assert len(preflight.requests) == 1
    assert bridge.calls == []
    journal.close()


def test_cap5_new_route_invocation_fails_closed_without_preflight_or_activation(
    tmp_path: Path,
) -> None:
    bridge = _RecordingBridge()
    no_preflight, no_preflight_journal, _router = _cap5_edge_uplink_gateway(
        tmp_path / "no-preflight",
        bridge=bridge,
        feature_enabled=True,
        runtime_preflight=None,
        activation_authorizations=(_edge_uplink_activation(),),
    )
    with pytest.raises(CapabilityUnavailableError, match="preflight"):
        no_preflight.upload_edge_bundle(_edge_uplink_request("no-preflight"))
    no_preflight_journal.close()

    preflight = _RecordingRuntimePreflight(_all_true_preflight_decision())
    no_activation, no_activation_journal, _router = _cap5_edge_uplink_gateway(
        tmp_path / "no-activation",
        bridge=bridge,
        feature_enabled=True,
        runtime_preflight=preflight,
        activation_authorizations=(),
    )
    with pytest.raises(CapabilityUnavailableError, match="activation"):
        no_activation.upload_edge_bundle(_edge_uplink_request("no-activation"))
    assert bridge.calls == []
    assert preflight.requests == []
    no_activation_journal.close()


def test_cap5_ambiguous_activation_mapping_fails_closed(tmp_path: Path) -> None:
    bridge = _RecordingBridge()
    preflight = _RecordingRuntimePreflight(_all_true_preflight_decision())
    gateway, journal, _router = _cap5_edge_uplink_gateway(
        tmp_path,
        bridge=bridge,
        feature_enabled=True,
        runtime_preflight=preflight,
        activation_authorizations=(_edge_uplink_activation(), _edge_uplink_activation()),
    )

    with pytest.raises(CapabilityUnavailableError, match="모호"):
        gateway.upload_edge_bundle(_edge_uplink_request())

    assert bridge.calls == []
    assert preflight.requests == []
    journal.close()


def test_unix_bridge_exchanges_bounded_typed_json(tmp_path: Path) -> None:
    socket_path = tmp_path / "psdk.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)
    captured: list[dict[str, Any]] = []

    def serve() -> None:
        connection, _address = server.accept()
        with connection:
            payload = bytearray()
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                payload.extend(chunk)
            captured.append(json.loads(payload))
            connection.sendall(
                json.dumps(
                    {
                        "provider_operation_id": "psdk-op-1",
                        "accepted_at": _NOW,
                        "item_count": 1,
                        "manifest_ref": None,
                    }
                ).encode()
            )
        server.close()

    worker = threading.Thread(target=serve)
    worker.start()
    config = AdapterRuntimeConfig(
        adapter_id="psdk-local",
        integration_path=IntegrationPath.PSDK_MANIFOLD,
        transport=GatewayTransport.MOP,
        organization_id="org-a",
        site_id="site-a",
        gateway_device_id="gateway-a",
        edge_device_id="edge-a",
        endpoint=f"unix://{socket_path}",
    )
    receipt = UnixJsonBridgeClient(config).invoke(
        operation=BridgeOperation.WAYLINE_UPLOAD_NO_START,
        idempotency_key="wayline-1",
        payload={"wayline_sha256": "a" * 64},
    )
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert receipt.provider_operation_id == "psdk-op-1"
    assert captured[0]["operation"] == "WAYLINE_UPLOAD_NO_START"
    assert "ACTION" not in captured[0]["operation"]
