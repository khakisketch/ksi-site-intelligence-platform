"""Capability-routed v1.3 gateway coordinator with durable idempotency."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from ksi_dji_gateway.domain.capabilities import Capability, GatewayTransport, IntegrationPath
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
from ksi_dji_gateway.domain.validation import validate_identifiers
from ksi_dji_gateway.errors import CapabilityUnavailableError, IdempotencyConflictError
from ksi_dji_gateway.gateway import request_digest
from ksi_dji_gateway.persistence.journal import GatewayJournal
from ksi_dji_gateway.ports import RoutablePort
from ksi_dji_gateway.routing.capability_router import (
    CapabilityRouter,
    RuntimeRoutePreflight,
    RuntimeRoutePreflightDecision,
    RuntimeRoutePreflightRequest,
)


@dataclass(frozen=True, slots=True)
class RouteActivationAuthorization:
    """Trusted exact capability/path binding to one CAP-4 authorization ID."""

    canonical_capability: Capability
    integration_path: IntegrationPath
    activation_authorization_id: str

    def __post_init__(self) -> None:
        if not self.activation_authorization_id.strip():
            raise ValueError("activation authorization ID는 비어 있을 수 없다")


@dataclass(frozen=True, slots=True)
class RoutingContext:
    organization_id: str
    site_id: str
    gateway_device_id: str
    edge_device_id: str
    hardware_model: str
    firmware_version: str
    allowed_transports: frozenset[GatewayTransport]
    activation_authorizations: tuple[RouteActivationAuthorization, ...] = ()

    def __post_init__(self) -> None:
        validate_identifiers(
            self.organization_id,
            self.site_id,
            self.gateway_device_id,
            self.edge_device_id,
        )
        if self.gateway_device_id == self.edge_device_id:
            raise ValueError("Gateway와 Edge 장치 신원은 달라야 한다")
        if not self.hardware_model.strip() or not self.firmware_version.strip():
            raise ValueError("routing context에는 exact hardware/firmware가 필요하다")
        if not self.allowed_transports:
            raise ValueError("routing context에는 허용 transport가 하나 이상 필요하다")

    def activation_authorization_id_for(
        self, capability: Capability, integration_path: IntegrationPath
    ) -> str:
        """Return one trusted exact activation ID; missing or ambiguous is unusable."""

        matches = tuple(
            binding.activation_authorization_id
            for binding in self.activation_authorizations
            if (
                binding.canonical_capability is capability
                and binding.integration_path is integration_path
            )
        )
        if len(matches) != 1:
            raise CapabilityUnavailableError(
                "exact capability/path activation authorization이 없거나 모호하다"
            )
        return matches[0]


class CapabilityGateway:
    """Invoke one narrow capability after router and CAP-5 runtime checks.

    The preflight applies only to a *new* provider port invocation.  It never
    cancels or changes an already-issued signed Mission Contract execution;
    idempotent receipt replay returns before this boundary because it performs
    no new device invocation.
    """

    def __init__(
        self,
        *,
        router: CapabilityRouter,
        journal: GatewayJournal,
        context: RoutingContext,
        runtime_preflight: RuntimeRoutePreflight | None = None,
    ) -> None:
        self._router = router
        self._journal = journal
        self._context = context
        self._runtime_preflight = runtime_preflight
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
        self._require_bound_request(request)
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
                organization_id=self._context.organization_id,
                site_id=self._context.site_id,
                gateway_device_id=self._context.gateway_device_id,
                edge_device_id=self._context.edge_device_id,
                hardware_model=self._context.hardware_model,
                firmware_version=self._context.firmware_version,
                allowed_transports=self._context.allowed_transports,
            )
            activation_authorization_id = self._context.activation_authorization_id_for(
                capability, port.integration_path
            )
            self._require_runtime_preflight(
                capability=capability,
                operation=operation,
                request=request,
                port=port,
                activation_authorization_id=activation_authorization_id,
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

    def _require_runtime_preflight(
        self,
        *,
        capability: Capability,
        operation: OperationKind,
        request: GatewayRequest,
        port: RoutablePort,
        activation_authorization_id: str,
    ) -> None:
        if self._runtime_preflight is None:
            raise CapabilityUnavailableError("CAP-5 runtime preflight가 주입되지 않았다")
        try:
            decision = self._runtime_preflight.evaluate(
                RuntimeRoutePreflightRequest(
                    organization_id=self._context.organization_id,
                    site_id=self._context.site_id,
                    gateway_device_id=self._context.gateway_device_id,
                    edge_device_id=self._context.edge_device_id,
                    canonical_capability=capability,
                    integration_path=port.integration_path,
                    subject_port_id=port.port_id,
                    transport=port.transport,
                    hardware_model=self._context.hardware_model,
                    firmware_version=self._context.firmware_version,
                    mission_id=request.mission_id,
                    operation=operation,
                    idempotency_key=request.idempotency_key,
                    activation_authorization_id=activation_authorization_id,
                )
            )
        except CapabilityUnavailableError:
            raise
        except Exception as exc:
            raise CapabilityUnavailableError(
                "CAP-5 runtime preflight가 fail-closed로 거부됐다"
            ) from exc
        if not isinstance(decision, RuntimeRoutePreflightDecision):
            raise CapabilityUnavailableError(
                "CAP-5 runtime preflight가 typed decision을 반환하지 않았다"
            )
        if not decision.operationally_usable:
            raise CapabilityUnavailableError(
                "CAP-5 runtime preflight가 route invoke를 허용하지 않았다"
            )

    def _require_bound_request(self, request: GatewayRequest) -> None:
        if (
            request.organization_id != self._context.organization_id
            or request.site_id != self._context.site_id
        ):
            raise CapabilityUnavailableError("요청 scope가 routing context와 일치하지 않는다")
        request_edge_device_id = getattr(request, "edge_device_id", None)
        if (
            request_edge_device_id is not None
            and request_edge_device_id != self._context.edge_device_id
        ):
            raise CapabilityUnavailableError("요청 scope가 routing context와 일치하지 않는다")


__all__ = ["CapabilityGateway", "RouteActivationAuthorization", "RoutingContext"]
