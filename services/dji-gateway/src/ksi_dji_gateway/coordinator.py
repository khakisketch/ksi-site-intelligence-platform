"""Capability-routed v1.3 gateway coordinator with durable idempotency."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from ksi_dji_gateway.domain.capabilities import Capability, GatewayTransport
from ksi_dji_gateway.domain.models import (
    EdgeDispatchRequest,
    EdgeUplinkRequest,
    GatewayRequest,
    IntegrationReceipt,
    MediaSyncRequest,
    OperationKind,
    ProviderReceipt,
    WaylineDispatchRequest,
)
from ksi_dji_gateway.errors import CapabilityUnavailableError, IdempotencyConflictError
from ksi_dji_gateway.gateway import request_digest
from ksi_dji_gateway.persistence.journal import GatewayJournal
from ksi_dji_gateway.routing.capability_router import CapabilityRouter


@dataclass(frozen=True, slots=True)
class RoutingContext:
    hardware_model: str
    firmware_version: str
    allowed_transports: frozenset[GatewayTransport]

    def __post_init__(self) -> None:
        if not self.hardware_model.strip() or not self.firmware_version.strip():
            raise ValueError("routing context에는 exact hardware/firmware가 필요하다")
        if not self.allowed_transports:
            raise ValueError("routing context에는 허용 transport가 하나 이상 필요하다")


class CapabilityGateway:
    """Invoke one narrow capability only after router evidence and feature-flag checks."""

    def __init__(
        self,
        *,
        router: CapabilityRouter,
        journal: GatewayJournal,
        context: RoutingContext,
    ) -> None:
        self._router = router
        self._journal = journal
        self._context = context
        self._operation_lock = threading.Lock()

    def deliver_wayline(self, request: WaylineDispatchRequest) -> IntegrationReceipt:
        return self._execute(
            capability=Capability.WAYLINE_DELIVERY,
            operation=OperationKind.WAYLINE_DISPATCH,
            request=request,
            method_name="deliver_wayline",
        )

    def dispatch_contract(self, request: EdgeDispatchRequest) -> IntegrationReceipt:
        return self._execute(
            capability=Capability.EDGE_DOWNLINK,
            operation=OperationKind.EDGE_DISPATCH,
            request=request,
            method_name="dispatch_contract",
        )

    def upload_edge_bundle(self, request: EdgeUplinkRequest) -> IntegrationReceipt:
        return self._execute(
            capability=Capability.EDGE_UPLINK,
            operation=OperationKind.EDGE_UPLINK,
            request=request,
            method_name="upload_edge_bundle",
        )

    def transfer_media(
        self,
        capability: Capability,
        request: MediaSyncRequest,
    ) -> IntegrationReceipt:
        if capability not in {Capability.MEDIA_PULL, Capability.MEDIA_UPLOAD}:
            raise ValueError("media transfer는 MEDIA_PULL 또는 MEDIA_UPLOAD만 허용한다")
        return self._execute(
            capability=capability,
            operation=OperationKind.MEDIA_SYNC,
            request=request,
            method_name="transfer_media",
        )

    def _execute(
        self,
        *,
        capability: Capability,
        operation: OperationKind,
        request: GatewayRequest,
        method_name: str,
    ) -> IntegrationReceipt:
        request_sha256 = request_digest(request)
        with self._operation_lock:
            existing = self._journal.find(operation, request.idempotency_key)
            if existing is not None:
                if (
                    existing.request_sha256 != request_sha256
                    or existing.journal_schema_version != "1.3"
                    or existing.capability is not capability
                ):
                    raise IdempotencyConflictError(
                        "같은 idempotency key를 다른 request/capability schema에 사용할 수 없다"
                    )
                return existing
            port, _evidence = self._router.select(
                capability,
                hardware_model=self._context.hardware_model,
                firmware_version=self._context.firmware_version,
                allowed_transports=self._context.allowed_transports,
            )
            invoke: Any = getattr(port, method_name, None)
            if not callable(invoke):
                raise CapabilityUnavailableError(
                    f"{port.port_id}가 {capability.value} port method를 구현하지 않았다"
                )
            provider_receipt = invoke(request)
            if not isinstance(provider_receipt, ProviderReceipt):
                raise CapabilityUnavailableError(
                    "adapter가 typed ProviderReceipt를 반환하지 않았다"
                )
            receipt = IntegrationReceipt(
                operation=operation,
                path=port.integration_path,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                provider_operation_id=provider_receipt.provider_operation_id,
                accepted_at=provider_receipt.accepted_at,
                item_count=provider_receipt.item_count,
                manifest_ref=provider_receipt.manifest_ref,
                capability=capability,
                transport=port.transport,
                journal_schema_version="1.3",
            )
            self._journal.append(receipt)
            return receipt


__all__ = ["CapabilityGateway", "RoutingContext"]
