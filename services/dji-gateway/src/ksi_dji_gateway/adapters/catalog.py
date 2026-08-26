"""Candidate provider catalog; code readiness never implies capability verification."""

from __future__ import annotations

from collections.abc import Mapping

from ksi_dji_gateway.adapters.ports import (
    CandidateEdgeDispatchPort,
    CandidateEdgeUplinkPort,
    CandidateMediaTransferPort,
    CandidateMissionDeliveryPort,
)
from ksi_dji_gateway.adapters.transport import AdapterRuntimeConfig, BridgeClient
from ksi_dji_gateway.domain.capabilities import Capability, GatewayTransport, IntegrationPath
from ksi_dji_gateway.ports import RoutablePort

CANDIDATE_PATH_CAPABILITIES: Mapping[IntegrationPath, frozenset[Capability]] = {
    # Pilot-to-Cloud Wayline support is not evidenced for the RC-only M4D profile.
    IntegrationPath.DJI_CLOUD: frozenset({Capability.EDGE_UPLINK}),
    IntegrationPath.PSDK_MANIFOLD: frozenset(
        {Capability.WAYLINE_DELIVERY, Capability.EDGE_UPLINK, Capability.MEDIA_PULL}
    ),
    IntegrationPath.MANIFOLD_DIRECT: frozenset(
        {Capability.EDGE_DOWNLINK, Capability.EDGE_UPLINK, Capability.MEDIA_UPLOAD}
    ),
    IntegrationPath.MSDK_FIELD: frozenset({Capability.EDGE_DOWNLINK, Capability.MEDIA_PULL}),
    # Dock media pull/upload are separate narrow ports; no Dock+Manifold Edge inference.
    IntegrationPath.DJI_DOCK: frozenset(
        {Capability.WAYLINE_DELIVERY, Capability.MEDIA_PULL, Capability.MEDIA_UPLOAD}
    ),
}

SUPPORTED_TRANSPORTS: Mapping[IntegrationPath, frozenset[GatewayTransport]] = {
    IntegrationPath.DJI_CLOUD: frozenset(
        {GatewayTransport.RC_WIFI, GatewayTransport.RC_CELLULAR}
    ),
    IntegrationPath.PSDK_MANIFOLD: frozenset({GatewayTransport.MOP}),
    IntegrationPath.MANIFOLD_DIRECT: frozenset({GatewayTransport.MANIFOLD_CELLULAR}),
    IntegrationPath.MSDK_FIELD: frozenset({GatewayTransport.MOP}),
    IntegrationPath.DJI_DOCK: frozenset(
        {GatewayTransport.DOCK_ETHERNET, GatewayTransport.DOCK_CELLULAR}
    ),
}


def build_candidate_ports(
    config: AdapterRuntimeConfig,
    client: BridgeClient,
) -> tuple[RoutablePort, ...]:
    if config.transport not in SUPPORTED_TRANSPORTS[config.integration_path]:
        raise ValueError(
            f"{config.integration_path.value}에 {config.transport.value} transport를 사용할 수 없다"
        )
    ports: list[RoutablePort] = []
    for capability in sorted(
        CANDIDATE_PATH_CAPABILITIES[config.integration_path], key=lambda item: item.value
    ):
        if capability is Capability.WAYLINE_DELIVERY:
            ports.append(CandidateMissionDeliveryPort(config=config, client=client))
        elif capability is Capability.EDGE_DOWNLINK:
            ports.append(CandidateEdgeDispatchPort(config=config, client=client))
        elif capability is Capability.EDGE_UPLINK:
            ports.append(CandidateEdgeUplinkPort(config=config, client=client))
        else:
            ports.append(
                CandidateMediaTransferPort(
                    config=config,
                    client=client,
                    capability=capability,
                )
            )
    return tuple(ports)


__all__ = ["CANDIDATE_PATH_CAPABILITIES", "SUPPORTED_TRANSPORTS", "build_candidate_ports"]
