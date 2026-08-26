"""Narrow candidate ports backed by an explicit bridge client."""

from __future__ import annotations

from dataclasses import asdict

from ksi_dji_gateway.adapters.transport import (
    AdapterRuntimeConfig,
    BridgeClient,
    BridgeOperation,
)
from ksi_dji_gateway.domain.capabilities import Capability, GatewayTransport, IntegrationPath
from ksi_dji_gateway.domain.models import (
    EdgeDispatchRequest,
    EdgeUplinkRequest,
    MediaSyncRequest,
    ProviderReceipt,
    WaylineDispatchRequest,
)


class _CandidatePort:
    def __init__(
        self,
        *,
        config: AdapterRuntimeConfig,
        client: BridgeClient,
        capability: Capability,
    ) -> None:
        self._config = config
        self._client = client
        self._capability = capability

    @property
    def port_id(self) -> str:
        return f"{self._config.adapter_id}.{self._capability.value.lower()}"

    @property
    def integration_path(self) -> IntegrationPath:
        return self._config.integration_path

    @property
    def transport(self) -> GatewayTransport:
        return self._config.transport

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({self._capability})

    @property
    def configuration_ready(self) -> bool:
        return self._config.configuration_ready

    @property
    def organization_id(self) -> str:
        return self._config.organization_id

    @property
    def site_id(self) -> str:
        return self._config.site_id

    @property
    def gateway_device_id(self) -> str:
        return self._config.gateway_device_id

    @property
    def edge_device_id(self) -> str:
        return self._config.edge_device_id


class CandidateMissionDeliveryPort(_CandidatePort):
    def __init__(self, *, config: AdapterRuntimeConfig, client: BridgeClient) -> None:
        super().__init__(config=config, client=client, capability=Capability.WAYLINE_DELIVERY)

    def deliver_wayline(self, request: WaylineDispatchRequest) -> ProviderReceipt:
        return self._client.invoke(
            operation=BridgeOperation.WAYLINE_UPLOAD_NO_START,
            idempotency_key=request.idempotency_key,
            payload=asdict(request),
        )


class CandidateEdgeDispatchPort(_CandidatePort):
    def __init__(self, *, config: AdapterRuntimeConfig, client: BridgeClient) -> None:
        super().__init__(config=config, client=client, capability=Capability.EDGE_DOWNLINK)

    def dispatch_contract(self, request: EdgeDispatchRequest) -> ProviderReceipt:
        return self._client.invoke(
            operation=BridgeOperation.SIGNED_CONTRACT_TRANSFER,
            idempotency_key=request.idempotency_key,
            payload=asdict(request),
        )


class CandidateEdgeUplinkPort(_CandidatePort):
    def __init__(self, *, config: AdapterRuntimeConfig, client: BridgeClient) -> None:
        super().__init__(config=config, client=client, capability=Capability.EDGE_UPLINK)

    def upload_edge_bundle(self, request: EdgeUplinkRequest) -> ProviderReceipt:
        return self._client.invoke(
            operation=BridgeOperation.EDGE_BUNDLE_UPLOAD,
            idempotency_key=request.idempotency_key,
            payload=asdict(request),
        )


class CandidateMediaTransferPort(_CandidatePort):
    def __init__(
        self,
        *,
        config: AdapterRuntimeConfig,
        client: BridgeClient,
        capability: Capability,
    ) -> None:
        if capability not in {Capability.MEDIA_PULL, Capability.MEDIA_UPLOAD}:
            raise ValueError("media port는 MEDIA_PULL 또는 MEDIA_UPLOAD만 허용한다")
        super().__init__(config=config, client=client, capability=capability)

    def transfer_media(self, request: MediaSyncRequest) -> ProviderReceipt:
        operation = (
            BridgeOperation.MEDIA_READ_ONE
            if self._capability is Capability.MEDIA_PULL
            else BridgeOperation.MEDIA_UPLOAD_SYNTHETIC
        )
        return self._client.invoke(
            operation=operation,
            idempotency_key=request.idempotency_key,
            payload=asdict(request),
        )


__all__ = [
    "CandidateEdgeDispatchPort",
    "CandidateEdgeUplinkPort",
    "CandidateMediaTransferPort",
    "CandidateMissionDeliveryPort",
]
