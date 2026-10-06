"""Private AI metadata access audit; permitted responses only, never raw metadata.

Each event records one permitted publication attempt — authorized at audit
time, not client delivery or receipt. A send refused after the audit keeps its
attempt event. Each event carries the permitted operation, scope/identity,
response-payload digest, UTC time and an optional safe typed reason. No body,
URL, token, raw cursor, idempotency key, file path or storage key is accepted
here. Events use the private ``spatial-data-metadata-audit.v1`` journal, never
the byte-session audit events. Capacity exhaustion and seal/corruption close
new metadata, they never truncate history.
"""

from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Literal
from uuid import uuid4

from ksi_event_contracts._spatial_data import (
    Digest,
    PositiveInt,
    SpatialDataDigestModel,
    SpatialDataModel,
    Text,
    UtcTimestamp,
)
from ksi_event_contracts.spatial_data import SpatialDataReasonV1
from ksi_event_contracts.spatial_data_authority import SpatialDataPolicyV1
from pydantic import TypeAdapter

from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal

MetadataAuditOperationV1 = Literal[
    "LIST_ASSETS",
    "GET_ASSET",
    "CREATE_JOB",
    "LIST_JOBS",
    "GET_JOB",
    "CANCEL_JOB",
]

_OPERATION: TypeAdapter[MetadataAuditOperationV1] = TypeAdapter(MetadataAuditOperationV1)
_DIGEST: TypeAdapter[Digest] = TypeAdapter(Digest)
_REASON: TypeAdapter[SpatialDataReasonV1] = TypeAdapter(SpatialDataReasonV1)


class SpatialDataMetadataAuditEventV1(SpatialDataDigestModel):
    _digest_field = "event_digest"
    event_id: Text
    organization_id: Text
    principal_id: Text
    site_id: Text
    work_area_id: Text
    operation: MetadataAuditOperationV1
    payload_digest: Digest | None = None
    reason: SpatialDataReasonV1 | None = None
    at: UtcTimestamp
    event_digest: Digest | None = None


class _MetadataAuditRecord(SpatialDataModel):
    record_type: Literal["spatial-data-metadata-audit.v1"] = "spatial-data-metadata-audit.v1"
    sequence: PositiveInt
    event: SpatialDataMetadataAuditEventV1


class SpatialDataMetadataAuditRecoveryError(RuntimeError):
    """Corrupt metadata audit history cannot yield a partial usable projection."""


class SpatialDataMetadataAuditStore:
    """Bounded private metadata-access journal; this store is not a public query API."""

    def __init__(self, journal: DurableJournal, *, policy: SpatialDataPolicyV1) -> None:
        validated = SpatialDataPolicyV1.model_validate(policy.model_dump())
        if validated.policy_digest != validated.canonical_digest():
            raise ValueError("metadata audit requires a sealed explicit data policy")
        self._journal = journal
        self._policy = validated.model_copy(deep=True)
        self._lock = RLock()
        self._count = 0
        self._bytes = 0
        self._sequence = 0
        self._sealed = False
        try:
            for raw in journal.replay():
                record = _MetadataAuditRecord.model_validate(raw)
                if record.sequence != self._sequence + 1:
                    raise ValueError("metadata audit sequence corrupted")
                size = self._check_event(record.event)
                self._project(size)
        except Exception as exc:
            self._sealed = True
            raise SpatialDataMetadataAuditRecoveryError(
                "invalid spatial data metadata audit history"
            ) from exc

    @property
    def policy(self) -> SpatialDataPolicyV1:
        return self._policy.model_copy(deep=True)

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def _capacity(self) -> int:
        return self._policy.max_pending_records * self._policy.max_list_records

    def _check_event(self, event: SpatialDataMetadataAuditEventV1) -> int:
        validated = SpatialDataMetadataAuditEventV1.model_validate(event.__dict__)
        if validated.event_digest != validated.canonical_digest():
            raise ValueError("metadata audit event not sealed")
        size = len(validated.model_dump_json(by_alias=True).encode("utf-8"))
        if size > self._policy.max_json_bytes:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        if self._count + 1 > self._capacity():
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        if self._bytes + size > self._policy.max_snapshot_bytes:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        return size

    def _project(self, size: int) -> None:
        self._sequence += 1
        self._count += 1
        self._bytes += size

    def append(
        self,
        *,
        principal: Principal,
        site_id: str,
        work_area_id: str,
        operation: str,
        payload_digest: str | None,
        reason: SpatialDataReasonV1 | None,
        now: datetime,
    ) -> None:
        """Record one permitted metadata publication attempt.

        The attempt is authorized at audit time; input failures are typed
        denials. A later send refusal keeps the attempt event.
        """
        with self._lock:
            if self._sealed or self._journal.sealed_reason is not None:
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
            try:
                validated_operation = _OPERATION.validate_python(operation)
            except Exception as exc:
                raise ValueError(f"metadata audit operation not permitted: {operation!r}") from exc
            try:
                if type(principal) is not Principal:
                    raise ValueError("metadata audit requires a genuine principal")
                for name, value in (
                    ("organization_id", principal.organization_id),
                    ("principal_id", principal.principal_id),
                    ("site_id", site_id),
                    ("work_area_id", work_area_id),
                ):
                    if type(value) is not str or not value:
                        raise ValueError(f"metadata audit {name} must be nonempty")
                digest = None if payload_digest is None else _DIGEST.validate_python(payload_digest)
                safe_reason = None if reason is None else _REASON.validate_python(reason)
                event = SpatialDataMetadataAuditEventV1(
                    event_id=str(uuid4()),
                    organization_id=principal.organization_id,
                    principal_id=principal.principal_id,
                    site_id=site_id,
                    work_area_id=work_area_id,
                    operation=validated_operation,
                    payload_digest=digest,
                    reason=safe_reason,
                    at=now,
                ).sealed()
                size = self._check_event(event)
            except SpatialDataDomainError:
                raise
            except (ValueError, TypeError) as exc:
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
            record = _MetadataAuditRecord(sequence=self._sequence + 1, event=event)
            try:
                self._journal.append(record.model_dump(by_alias=True, mode="json"))
            except BaseException as exc:
                self._sealed = True
                if not isinstance(exc, Exception):
                    raise
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
            self._project(size)

    def close(self) -> None:
        with self._lock:
            self._sealed = True
            self._journal.close()
