"""Idempotent Gateway requests and provider-neutral receipts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ksi_dji_gateway.domain.capabilities import Capability, GatewayTransport, IntegrationPath
from ksi_dji_gateway.domain.validation import (
    SHA256,
    aware_datetime,
    validate_identifiers,
    validate_object_ref,
)


class OperationKind(StrEnum):
    WAYLINE_DISPATCH = "WAYLINE_DISPATCH"
    EDGE_DISPATCH = "EDGE_DISPATCH"
    EDGE_UPLINK = "EDGE_UPLINK"
    MEDIA_SYNC = "MEDIA_SYNC"


@dataclass(frozen=True, slots=True)
class WaylineDispatchRequest:
    organization_id: str
    site_id: str
    work_order_id: str
    mission_id: str
    wayline_object_ref: str
    wayline_sha256: str
    idempotency_key: str

    def __post_init__(self) -> None:
        validate_identifiers(
            self.organization_id,
            self.site_id,
            self.work_order_id,
            self.mission_id,
            self.idempotency_key,
        )
        validate_object_ref(self.wayline_object_ref)
        if SHA256.fullmatch(self.wayline_sha256) is None:
            raise ValueError("wayline_sha256은 소문자 SHA-256이어야 한다")


@dataclass(frozen=True, slots=True)
class EdgeDispatchRequest:
    organization_id: str
    site_id: str
    mission_id: str
    edge_device_id: str
    contract_object_ref: str
    contract_sha256: str
    idempotency_key: str

    def __post_init__(self) -> None:
        validate_identifiers(
            self.organization_id,
            self.site_id,
            self.mission_id,
            self.edge_device_id,
            self.idempotency_key,
        )
        validate_object_ref(self.contract_object_ref)
        if SHA256.fullmatch(self.contract_sha256) is None:
            raise ValueError("contract_sha256은 소문자 SHA-256이어야 한다")


@dataclass(frozen=True, slots=True)
class EdgeUplinkRequest:
    organization_id: str
    site_id: str
    mission_id: str
    edge_device_id: str
    bundle_object_ref: str
    bundle_sha256: str
    idempotency_key: str

    def __post_init__(self) -> None:
        validate_identifiers(
            self.organization_id,
            self.site_id,
            self.mission_id,
            self.edge_device_id,
            self.idempotency_key,
        )
        validate_object_ref(self.bundle_object_ref)
        if SHA256.fullmatch(self.bundle_sha256) is None:
            raise ValueError("bundle_sha256은 소문자 SHA-256이어야 한다")


@dataclass(frozen=True, slots=True)
class MediaSyncRequest:
    organization_id: str
    site_id: str
    work_order_id: str
    mission_id: str
    destination_prefix: str
    idempotency_key: str

    def __post_init__(self) -> None:
        validate_identifiers(
            self.organization_id,
            self.site_id,
            self.work_order_id,
            self.mission_id,
            self.idempotency_key,
        )
        validate_object_ref(self.destination_prefix)


@dataclass(frozen=True, slots=True)
class ProviderReceipt:
    provider_operation_id: str
    accepted_at: str
    item_count: int
    manifest_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.provider_operation_id.strip():
            raise ValueError("provider_operation_id는 비어 있을 수 없다")
        aware_datetime(self.accepted_at, field="accepted_at")
        if self.item_count < 0:
            raise ValueError("item_count는 음수일 수 없다")
        if self.manifest_ref is not None:
            validate_object_ref(self.manifest_ref)


@dataclass(frozen=True, slots=True)
class IntegrationReceipt:
    operation: OperationKind
    path: IntegrationPath
    idempotency_key: str
    request_sha256: str
    provider_operation_id: str
    accepted_at: str
    item_count: int
    manifest_ref: str | None
    capability: Capability | None = None
    transport: GatewayTransport | None = None
    journal_schema_version: str = "1.2"

    def __post_init__(self) -> None:
        validate_identifiers(self.idempotency_key)
        if SHA256.fullmatch(self.request_sha256) is None:
            raise ValueError("request_sha256은 소문자 SHA-256이어야 한다")
        if not self.provider_operation_id.strip():
            raise ValueError("provider_operation_id는 비어 있을 수 없다")
        aware_datetime(self.accepted_at, field="accepted_at")
        if self.item_count < 0:
            raise ValueError("item_count는 음수일 수 없다")
        if self.manifest_ref is not None:
            validate_object_ref(self.manifest_ref)
        if self.journal_schema_version not in {"1.2", "1.3"}:
            raise ValueError("journal_schema_version은 1.2 또는 1.3이어야 한다")
        if self.journal_schema_version == "1.3" and (
            self.capability is None or self.transport is None
        ):
            raise ValueError("v1.3 receipt는 capability와 transport가 필요하다")
        if self.journal_schema_version == "1.2" and (
            self.capability is not None or self.transport is not None
        ):
            raise ValueError("v1.2 receipt에는 capability와 transport를 기록할 수 없다")


GatewayRequest = WaylineDispatchRequest | EdgeDispatchRequest | EdgeUplinkRequest | MediaSyncRequest


__all__ = [
    "EdgeDispatchRequest",
    "EdgeUplinkRequest",
    "GatewayRequest",
    "IntegrationReceipt",
    "MediaSyncRequest",
    "OperationKind",
    "ProviderReceipt",
    "WaylineDispatchRequest",
]
