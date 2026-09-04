"""Real TCP seam: Core CAP-5 projector -> transport -> Gateway coordinator."""

from __future__ import annotations

import hashlib
import socket
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_execution import MissionExecutionStore
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_dji_gateway import (
    AdapterRuntimeConfig,
    Capability,
    CapabilityEvidence,
    CapabilityGateway,
    CapabilityRegistry,
    CapabilityRoute,
    CapabilityRouter,
    CapabilityStatus,
    CapabilityUnavailableError,
    CoreRuntimeTransportConfig,
    EdgeDispatchRequest,
    GatewayJournal,
    GatewayTransport,
    HttpCoreRuntimeRoutePreflight,
    IntegrationPath,
    ProviderReceipt,
    RouteActivationAuthorization,
    RoutingContext,
    build_candidate_ports,
)
from test_capability_runtime_projection import ACTIVE_NOW, _observation, _runtime
from test_mission_contract_roundtrip import _valid_contract_dict


class _RecordingBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, Mapping[str, Any]]] = []

    def invoke(
        self, *, operation: object, idempotency_key: str, payload: Mapping[str, Any]
    ) -> ProviderReceipt:
        self.calls.append((operation, idempotency_key, payload))
        return ProviderReceipt(
            provider_operation_id="provider-1",
            accepted_at=datetime.now(UTC).isoformat(),
            item_count=1,
        )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.parametrize(
    ("mission_id", "expected_provider_calls"),
    (("mission-1", 1), ("unknown-mission", 0)),
    ids=("allow", "core-mission-deny"),
)
def test_real_core_transport_and_gateway_coordinator_seam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mission_id: str,
    expected_provider_calls: int,
) -> None:
    monkeypatch.setattr("ksi_core.capability.runtime_api._utc_now", lambda: ACTIVE_NOW)
    _authority, activation, runtime_config, _observations, projector = _runtime(tmp_path)
    now = ACTIVE_NOW
    projector.ingest_observation(
        _observation(
            runtime_config,
            observed_at=now - timedelta(seconds=1),
            expires_at=now - timedelta(seconds=1) + timedelta(minutes=5),
        ),
        principal=Principal(
            principal_id="edge-runtime-1",
            kind=PrincipalKind.EDGE_DEVICE,
            role=None,
            device_id="edge-1",
            organization_id="org-1",
        ),
        received_at=now,
    )

    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    contract = _valid_contract_dict("1.2")
    contract["missionId"] = "mission-1"
    contract["siteId"] = "site-1"
    contract["validity"] = {
        "notBefore": (now - timedelta(minutes=1)).isoformat(),
        "notAfter": (now + timedelta(minutes=5)).isoformat(),
    }
    assert mission_store.record_issuance(
        MissionRecord(
            mission_id="mission-1",
            site_id="site-1",
            mission_type="UNIFIED_SITE_SURVEY",
            artifact_kind="contract",
            contract=contract,
            kmz_sha256=None,
            route_pattern=None,
            waypoint_count=None,
            planned_coverage_ratio=None,
            issued_at=now,
            issued_by="operator-1",
            organization_id="org-1",
            assigned_device_id="edge-1",
        )
    ).value == "RECORDED"
    execution_store = MissionExecutionStore(
        DurableJournal(tmp_path / "mission-execution.jsonl"), mission_store=mission_store
    )
    token = "gateway-preflight-token"
    auth = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(),
                principal=Principal(
                    principal_id="gateway-runtime-1",
                    kind=PrincipalKind.GATEWAY_DEVICE,
                    role=None,
                    device_id="gateway-1",
                    organization_id="org-1",
                ),
            )
        ]
    )
    app = create_app(
        auth_registry=auth,
        runtime_capability_projector=projector,
        mission_store=mission_store,
        mission_execution_store=execution_store,
    )
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started

    token_file = tmp_path / "gateway-token"
    token_file.write_text(token, encoding="utf-8")
    token_file.chmod(0o600)
    preflight = HttpCoreRuntimeRoutePreflight(
        CoreRuntimeTransportConfig(
            core_url=f"http://127.0.0.1:{port}",
            token_file=token_file,
            allow_loopback_http=True,
        )
    )
    bridge = _RecordingBridge()
    adapter = AdapterRuntimeConfig(
        adapter_id="msdk",
        integration_path=IntegrationPath.MSDK_FIELD,
        transport=GatewayTransport.MOP,
        organization_id="org-1",
        site_id="site-1",
        gateway_device_id="gateway-1",
        edge_device_id="edge-1",
        endpoint="https://unused.invalid",
        tls_certificate_sha256="a" * 64,
    )
    ports = build_candidate_ports(adapter, bridge)
    gateway_component = next(
        component
        for component in activation.configured_deployment.equipment_scope.components
        if component.role.value == "GATEWAY"
    )
    gateway_journal = GatewayJournal(tmp_path / "gateway.jsonl")
    gateway = CapabilityGateway(
        router=CapabilityRouter(
            routes=tuple(
                CapabilityRoute(port=item, priority=index)
                for index, item in enumerate(ports)
            ),
            registry=CapabilityRegistry(
                [
                    CapabilityEvidence(
                        path=IntegrationPath.MSDK_FIELD,
                        capability=Capability.EDGE_DOWNLINK,
                        status=CapabilityStatus.VERIFIED,
                        checked_at=now.isoformat(),
                        evidence_ref="hil://software-seam-only",
                        hardware_model=gateway_component.hardware_model,
                        firmware_version=gateway_component.firmware_or_image_version,
                    )
                ]
            ),
            feature_flags={Capability.EDGE_DOWNLINK: True},
        ),
        journal=gateway_journal,
        context=RoutingContext(
            organization_id="org-1",
            site_id="site-1",
            gateway_device_id="gateway-1",
            edge_device_id="edge-1",
            hardware_model=gateway_component.hardware_model,
            firmware_version=gateway_component.firmware_or_image_version,
            allowed_transports=frozenset({GatewayTransport.MOP}),
            activation_authorizations=(
                RouteActivationAuthorization(
                    canonical_capability=Capability.EDGE_DOWNLINK,
                    integration_path=IntegrationPath.MSDK_FIELD,
                    activation_authorization_id=activation.activation_authorization_id,
                ),
            ),
        ),
        runtime_preflight=preflight,
    )
    try:
        request = EdgeDispatchRequest(
            organization_id="org-1",
            site_id="site-1",
            mission_id=mission_id,
            edge_device_id="edge-1",
            contract_object_ref="objects/contracts/mission-1.json",
            contract_sha256="f" * 64,
            idempotency_key="dispatch-1",
        )
        if expected_provider_calls:
            receipt = gateway.dispatch_contract(request)
            assert receipt.provider_operation_id == "provider-1"
        else:
            with pytest.raises(CapabilityUnavailableError, match="route invoke"):
                gateway.dispatch_contract(request)
        assert len(bridge.calls) == expected_provider_calls
    finally:
        gateway_journal.close()
        server.should_exit = True
        thread.join(timeout=5)
