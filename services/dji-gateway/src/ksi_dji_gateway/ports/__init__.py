"""Narrow adapter ports; no port owns another responsibility."""

from __future__ import annotations

from typing import Protocol

from ksi_dji_gateway.domain.capabilities import Capability, GatewayTransport, IntegrationPath
from ksi_dji_gateway.domain.models import (
    EdgeDispatchRequest,
    EdgeUplinkRequest,
    MediaSyncRequest,
    ProviderReceipt,
    WaylineDispatchRequest,
)


class RoutablePort(Protocol):
    @property
    def port_id(self) -> str: ...

    @property
    def integration_path(self) -> IntegrationPath: ...

    @property
    def transport(self) -> GatewayTransport: ...

    @property
    def capabilities(self) -> frozenset[Capability]: ...


class MissionDeliveryPort(RoutablePort, Protocol):
    def deliver_wayline(self, request: WaylineDispatchRequest) -> ProviderReceipt: ...


class EdgeDispatchPort(RoutablePort, Protocol):
    def dispatch_contract(self, request: EdgeDispatchRequest) -> ProviderReceipt: ...


class EdgeUplinkPort(RoutablePort, Protocol):
    def upload_edge_bundle(self, request: EdgeUplinkRequest) -> ProviderReceipt: ...


class MediaTransferPort(RoutablePort, Protocol):
    def transfer_media(self, request: MediaSyncRequest) -> ProviderReceipt: ...


__all__ = [
    "EdgeDispatchPort",
    "EdgeUplinkPort",
    "MediaTransferPort",
    "MissionDeliveryPort",
    "RoutablePort",
]
