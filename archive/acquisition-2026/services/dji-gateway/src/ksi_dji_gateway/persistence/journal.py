"""Gateway receipt journal with explicit v1.2/v1.3 receipt semantics."""

from __future__ import annotations

import fcntl
import json
import os
import threading
from dataclasses import asdict
from pathlib import Path

from ksi_dji_gateway.domain.capabilities import Capability, GatewayTransport, IntegrationPath
from ksi_dji_gateway.domain.models import IntegrationReceipt, OperationKind
from ksi_dji_gateway.errors import GatewayJournalRecoveryError, IdempotencyConflictError


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
                # v1.2에는 capability/transport/schema marker가 없다. 의미를 추측하지
                # 않고 None으로 읽어 rollback과 감사를 보존한다.
                receipt = IntegrationReceipt(
                    operation=OperationKind(raw["operation"]),
                    path=IntegrationPath(raw["path"]),
                    idempotency_key=raw["idempotency_key"],
                    request_sha256=raw["request_sha256"],
                    provider_operation_id=raw["provider_operation_id"],
                    accepted_at=raw["accepted_at"],
                    item_count=raw["item_count"],
                    manifest_ref=raw.get("manifest_ref"),
                    capability=(
                        Capability(raw["capability"]) if raw.get("capability") is not None else None
                    ),
                    transport=(
                        GatewayTransport(raw["transport"])
                        if raw.get("transport") is not None
                        else None
                    ),
                    journal_schema_version=raw.get("journal_schema_version", "1.2"),
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


__all__ = ["GatewayJournal"]
