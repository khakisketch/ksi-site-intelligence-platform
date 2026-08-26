"""Compatibility facade for the structured RC-first DJI Gateway.

새 구현은 ``domain``·``ports``·``routing``·``persistence``가 소유한다. 이 모듈은
기존 ``ZeroTouchGateway`` 호출부와 공개 import를 보존하며, 새 코드는 capability별
``CapabilityRouter``와 좁은 port를 사용한다.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict
from typing import Any, Protocol

from ksi_dji_gateway.domain.capabilities import (
    Capability,
    CapabilityEvidence,
    CapabilityRegistry,
    CapabilityStatus,
    GatewayTransport,
    IntegrationPath,
)
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
from ksi_dji_gateway.errors import (
    CapabilityUnavailableError,
    GatewayError,
    GatewayJournalRecoveryError,
    IdempotencyConflictError,
)
from ksi_dji_gateway.persistence.journal import GatewayJournal
from ksi_dji_gateway.ports import (
    EdgeDispatchPort,
    EdgeUplinkPort,
    MediaTransferPort,
    MissionDeliveryPort,
    RoutablePort,
)
from ksi_dji_gateway.routing import CapabilityRoute, CapabilityRouter


class DjiProvider(Protocol):
    """v1.2 combined provider compatibility only; do not implement new adapters here."""

    @property
    def integration_path(self) -> IntegrationPath: ...

    def push_wayline(self, request: WaylineDispatchRequest) -> ProviderReceipt: ...

    def sync_media(self, request: MediaSyncRequest) -> ProviderReceipt: ...


class ZeroTouchGateway:
    """Legacy facade retained for rollback while feature-specific ports are adopted."""

    def __init__(
        self,
        *,
        provider: DjiProvider,
        capabilities: CapabilityRegistry,
        journal: GatewayJournal,
        wayline_dispatch_enabled: bool = False,
        media_sync_enabled: bool = False,
    ) -> None:
        self._provider = provider
        self._capabilities = capabilities
        self._journal = journal
        self._wayline_dispatch_enabled = wayline_dispatch_enabled
        self._media_sync_enabled = media_sync_enabled
        self._operation_lock = threading.Lock()

    def dispatch_wayline(self, request: WaylineDispatchRequest) -> IntegrationReceipt:
        if not self._wayline_dispatch_enabled:
            raise CapabilityUnavailableError("wayline dispatch feature flag가 꺼져 있다")
        return self._execute(
            OperationKind.WAYLINE_DISPATCH,
            request,
            (Capability.WAYLINE_PUSH, Capability.TASK_STATUS),
            self._provider.push_wayline,
        )

    def sync_media(self, request: MediaSyncRequest) -> IntegrationReceipt:
        if not self._media_sync_enabled:
            raise CapabilityUnavailableError("media sync feature flag가 꺼져 있다")
        return self._execute(
            OperationKind.MEDIA_SYNC,
            request,
            (Capability.CAMERA_MEDIA_PULL, Capability.MEDIA_UPLOAD),
            self._provider.sync_media,
        )

    def _execute(
        self,
        operation: OperationKind,
        request: WaylineDispatchRequest | MediaSyncRequest,
        required: tuple[Capability, ...],
        invoke: Any,
    ) -> IntegrationReceipt:
        request_sha256 = request_digest(request)
        with self._operation_lock:
            existing = self._journal.find(operation, request.idempotency_key)
            if existing is not None:
                if existing.request_sha256 != request_sha256:
                    raise IdempotencyConflictError(
                        "같은 idempotency key에 다른 요청 본문을 사용할 수 없다"
                    )
                return existing
            self._capabilities.require_verified(self._provider.integration_path, *required)
            provider_receipt = invoke(request)
            receipt = IntegrationReceipt(
                operation=operation,
                path=self._provider.integration_path,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                provider_operation_id=provider_receipt.provider_operation_id,
                accepted_at=provider_receipt.accepted_at,
                item_count=provider_receipt.item_count,
                manifest_ref=provider_receipt.manifest_ref,
                journal_schema_version="1.2",
            )
            self._journal.append(receipt)
            return receipt


def request_digest(request: GatewayRequest) -> str:
    payload = json.dumps(asdict(request), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "Capability",
    "CapabilityEvidence",
    "CapabilityRegistry",
    "CapabilityRoute",
    "CapabilityRouter",
    "CapabilityStatus",
    "CapabilityUnavailableError",
    "DjiProvider",
    "EdgeDispatchPort",
    "EdgeDispatchRequest",
    "EdgeUplinkPort",
    "EdgeUplinkRequest",
    "GatewayError",
    "GatewayJournal",
    "GatewayJournalRecoveryError",
    "GatewayTransport",
    "IdempotencyConflictError",
    "IntegrationPath",
    "IntegrationReceipt",
    "MediaSyncRequest",
    "MediaTransferPort",
    "MissionDeliveryPort",
    "OperationKind",
    "ProviderReceipt",
    "RoutablePort",
    "WaylineDispatchRequest",
    "ZeroTouchGateway",
    "request_digest",
]
