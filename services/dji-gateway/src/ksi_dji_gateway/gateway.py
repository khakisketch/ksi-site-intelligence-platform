"""무파일 수집을 위한 DJI provider-neutral gateway (REQ-ACQ-101, INV-041).

실제 DJI SDK 호출은 ``DjiProvider`` 구현체의 책임이다. 이 모듈은 실기 증거가
``VERIFIED``인 capability만 열고, 요청/영수증을 멱등 원장에 남기는 제품 경계다.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class GatewayError(RuntimeError):
    """Gateway fail-closed 오류."""


class CapabilityUnavailableError(GatewayError):
    pass


class IdempotencyConflictError(GatewayError):
    pass


class GatewayJournalRecoveryError(GatewayError):
    pass


class IntegrationPath(StrEnum):
    DJI_CLOUD = "DJI_CLOUD"
    PSDK_MANIFOLD = "PSDK_MANIFOLD"
    MSDK_FIELD = "MSDK_FIELD"


class Capability(StrEnum):
    WAYLINE_PUSH = "WAYLINE_PUSH"
    TASK_STATUS = "TASK_STATUS"
    CAMERA_MEDIA_PULL = "CAMERA_MEDIA_PULL"
    MEDIA_UPLOAD = "MEDIA_UPLOAD"


class CapabilityStatus(StrEnum):
    NOT_VERIFIED = "NOT_VERIFIED"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"


class OperationKind(StrEnum):
    WAYLINE_DISPATCH = "WAYLINE_DISPATCH"
    MEDIA_SYNC = "MEDIA_SYNC"


@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    path: IntegrationPath
    capability: Capability
    status: CapabilityStatus
    checked_at: str
    evidence_ref: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        _aware_datetime(self.checked_at, field="checked_at")
        if self.status is CapabilityStatus.VERIFIED and not self.evidence_ref:
            raise ValueError("VERIFIED capability에는 evidence_ref가 필수다")


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
        _validate_identifiers(
            self.organization_id,
            self.site_id,
            self.work_order_id,
            self.mission_id,
            self.idempotency_key,
        )
        _validate_object_ref(self.wayline_object_ref)
        if _SHA256.fullmatch(self.wayline_sha256) is None:
            raise ValueError("wayline_sha256은 소문자 SHA-256이어야 한다")


@dataclass(frozen=True, slots=True)
class MediaSyncRequest:
    organization_id: str
    site_id: str
    work_order_id: str
    mission_id: str
    destination_prefix: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _validate_identifiers(
            self.organization_id,
            self.site_id,
            self.work_order_id,
            self.mission_id,
            self.idempotency_key,
        )
        _validate_object_ref(self.destination_prefix)


@dataclass(frozen=True, slots=True)
class ProviderReceipt:
    provider_operation_id: str
    accepted_at: str
    item_count: int
    manifest_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.provider_operation_id.strip():
            raise ValueError("provider_operation_id는 비어 있을 수 없다")
        _aware_datetime(self.accepted_at, field="accepted_at")
        if self.item_count < 0:
            raise ValueError("item_count는 음수일 수 없다")
        if self.manifest_ref is not None:
            _validate_object_ref(self.manifest_ref)


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


class DjiProvider(Protocol):
    """DJI Cloud/PSDK/MSDK adapter가 구현하는 최소 포트."""

    @property
    def integration_path(self) -> IntegrationPath: ...

    def push_wayline(self, request: WaylineDispatchRequest) -> ProviderReceipt: ...

    def sync_media(self, request: MediaSyncRequest) -> ProviderReceipt: ...


class CapabilityRegistry:
    def __init__(self, evidence: list[CapabilityEvidence]) -> None:
        self._evidence: dict[tuple[IntegrationPath, Capability], CapabilityEvidence] = {}
        for item in evidence:
            key = (item.path, item.capability)
            if key in self._evidence:
                raise ValueError(f"capability evidence 중복: {key}")
            self._evidence[key] = item

    def require_verified(self, path: IntegrationPath, *capabilities: Capability) -> None:
        for capability in capabilities:
            evidence = self._evidence.get((path, capability))
            if evidence is None or evidence.status is not CapabilityStatus.VERIFIED:
                status = evidence.status if evidence is not None else CapabilityStatus.NOT_VERIFIED
                raise CapabilityUnavailableError(
                    f"{path.value}/{capability.value} capability는 {status.value}다"
                )


class GatewayJournal:
    """작은 append-only idempotency journal. 원문 media/KMZ는 기록하지 않는다."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_fd = os.open(
            path.with_suffix(path.suffix + ".lock"), os.O_CREAT | os.O_RDWR, 0o600
        )
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self._lock_fd)
            raise GatewayJournalRecoveryError(
                "다른 프로세스가 gateway journal을 소유 중이다"
            ) from exc
        self._records = self._recover()

    def _recover(self) -> dict[tuple[OperationKind, str], IntegrationReceipt]:
        recovered: dict[tuple[OperationKind, str], IntegrationReceipt] = {}
        if not self._path.exists():
            return recovered
        try:
            payload = self._path.read_bytes()
            if payload and not payload.endswith(b"\n"):
                raise ValueError("torn tail")
            for line in payload.splitlines():
                raw = json.loads(line)
                receipt = IntegrationReceipt(
                    operation=OperationKind(raw["operation"]),
                    path=IntegrationPath(raw["path"]),
                    idempotency_key=raw["idempotency_key"],
                    request_sha256=raw["request_sha256"],
                    provider_operation_id=raw["provider_operation_id"],
                    accepted_at=raw["accepted_at"],
                    item_count=raw["item_count"],
                    manifest_ref=raw.get("manifest_ref"),
                )
                key = (receipt.operation, receipt.idempotency_key)
                if key in recovered:
                    raise ValueError("중복 idempotency key")
                recovered[key] = receipt
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.close()
            raise GatewayJournalRecoveryError(f"gateway journal 재생 실패: {exc}") from exc
        return recovered

    def find(self, operation: OperationKind, key: str) -> IntegrationReceipt | None:
        with self._lock:
            return self._records.get((operation, key))

    def append(self, receipt: IntegrationReceipt) -> None:
        key = (receipt.operation, receipt.idempotency_key)
        encoded = (
            json.dumps(asdict(receipt), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            + "\n"
        ).encode()
        with self._lock:
            if key in self._records:
                raise IdempotencyConflictError("idempotency key가 이미 기록됐다")
            fd = os.open(self._path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                view = memoryview(encoded)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("gateway journal short write")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            self._records[key] = receipt

    def close(self) -> None:
        lock_fd = getattr(self, "_lock_fd", -1)
        if lock_fd >= 0:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            self._lock_fd = -1


class ZeroTouchGateway:
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
        request_sha256 = _request_digest(request)
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
            )
            self._journal.append(receipt)
            return receipt


def _request_digest(request: WaylineDispatchRequest | MediaSyncRequest) -> str:
    payload = json.dumps(asdict(request), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _validate_identifiers(*values: str) -> None:
    if any(_IDENTIFIER.fullmatch(value) is None for value in values):
        raise ValueError("식별자는 경로-안전 비공백 문자만 허용한다")


def _validate_object_ref(value: str) -> None:
    if not value.strip() or "?" in value or "#" in value:
        raise ValueError("object ref는 query/fragment가 없는 비공백 참조여야 한다")


def _aware_datetime(value: str, *, field: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"{field}는 tz-aware ISO-8601이어야 한다")
    return parsed.astimezone(UTC)


__all__ = [
    "Capability",
    "CapabilityEvidence",
    "CapabilityRegistry",
    "CapabilityStatus",
    "CapabilityUnavailableError",
    "DjiProvider",
    "GatewayJournal",
    "GatewayJournalRecoveryError",
    "IdempotencyConflictError",
    "IntegrationPath",
    "IntegrationReceipt",
    "MediaSyncRequest",
    "OperationKind",
    "ProviderReceipt",
    "WaylineDispatchRequest",
    "ZeroTouchGateway",
]
