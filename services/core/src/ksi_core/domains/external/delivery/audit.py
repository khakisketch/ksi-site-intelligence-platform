"""Fail-closed private download audit; byte counts mean acknowledged ASGI handoffs.

An unfinished start remains unfinished on restart. It is never evidence of a client
receiving bytes. No bearer, URL, filesystem path or storage key is accepted here.
"""

from __future__ import annotations

from threading import RLock
from typing import Annotated, Literal, Self

from ksi_event_contracts._spatial_data import (
    MAX_COUNTER,
    Digest,
    PositiveInt,
    SpatialDataDigestModel,
    SpatialDataModel,
    Text,
    UtcTimestamp,
)
from ksi_event_contracts.spatial_data import JobId, SpatialDataReasonV1
from ksi_event_contracts.spatial_data_authority import SpatialDataPolicyV1
from pydantic import Field, StrictInt, StringConstraints, model_validator

from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.foundation.durable_journal import DurableJournal

AuditId = Annotated[
    str,
    StringConstraints(
        strict=True, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    ),
]
AuditAction = Literal[
    "DOWNLOAD_ADMITTED",
    "DENIED",
    "STREAM_STARTED",
    "STREAM_COMPLETED",
    "STREAM_INTERRUPTED",
    "HEAD_STARTED",
    "HEAD_COMPLETED",
    "CLEANUP_STARTED",
    "CLEANUP_COMPLETED",
    "CLEANUP_FAILED",
]


class SpatialDataAuditEventV1(SpatialDataDigestModel):
    _digest_field = "event_digest"
    event_id: AuditId
    session_id: AuditId
    organization_id: Text
    principal_id: Text
    site_id: Text
    work_area_id: Text
    job_id: JobId
    at: UtcTimestamp
    action: AuditAction
    expected_size_bytes: PositiveInt
    output_sha256: Digest
    sent_bytes: Annotated[StrictInt, Field(ge=0, le=MAX_COUNTER)]
    reason: SpatialDataReasonV1 | None = None
    event_digest: Digest | None = None

    @model_validator(mode="after")
    def _reason_and_count(self) -> Self:
        if (self.action in {"DENIED", "STREAM_INTERRUPTED", "CLEANUP_FAILED"}) != (
            self.reason is not None
        ):
            raise ValueError("terminal denial/interruption requires a typed reason only")
        if (
            self.action
            in {
                "DOWNLOAD_ADMITTED",
                "DENIED",
                "STREAM_STARTED",
                "HEAD_STARTED",
                "HEAD_COMPLETED",
                "CLEANUP_STARTED",
                "CLEANUP_COMPLETED",
                "CLEANUP_FAILED",
            }
            and self.sent_bytes != 0
        ):
            raise ValueError("non-transfer action cannot claim sent bytes")
        return self


class _Record(SpatialDataModel):
    record_type: Literal["spatial-data-audit.v1"] = "spatial-data-audit.v1"
    sequence: PositiveInt
    event: SpatialDataAuditEventV1


class SpatialDataAuditRecoveryError(RuntimeError):
    pass


class SpatialDataAuditStore:
    """Bounded private projection; caller supplies current tenant authorization.

    This store is not a public query API. Capacity exhaustion is explicit and closes
    new admissions; it never forgets unfinished sessions or truncates history.
    """

    def __init__(self, journal: DurableJournal, *, policy: SpatialDataPolicyV1):
        self._policy = SpatialDataPolicyV1.model_validate(policy.__dict__)
        if self._policy.policy_digest != self._policy.canonical_digest():
            raise ValueError("sealed audit resource policy required")
        self._journal = journal
        self._lock = RLock()
        self._events: dict[str, SpatialDataAuditEventV1] = {}
        self._sessions: dict[str, tuple[SpatialDataAuditEventV1, ...]] = {}
        self._bytes = 0
        self._reserved_slots = 0
        self._sequence = 0
        self._sealed = False
        try:
            for raw in journal.replay():
                record = _Record.model_validate(raw)
                if record.sequence != self._sequence + 1 or record.event.event_id in self._events:
                    raise ValueError("audit sequence/identity corrupted")
                size = self._validate(record.event)
                self._project(record.event, size)
        except Exception as exc:
            self._sealed = True
            raise SpatialDataAuditRecoveryError("invalid spatial data audit history") from exc

    @property
    def policy(self) -> SpatialDataPolicyV1:
        return self._policy.model_copy(deep=True)

    def _validate(self, event: SpatialDataAuditEventV1) -> int:
        if event.event_digest != event.canonical_digest():
            raise ValueError("audit event not sealed")
        size = len(event.model_dump_json(by_alias=True).encode("utf-8"))
        if (
            size > self._policy.max_json_bytes
            or self._bytes + size > self._policy.max_snapshot_bytes
        ):
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        history = self._sessions.get(event.session_id, ())
        remaining = {
            "DOWNLOAD_ADMITTED": 2,
            "STREAM_STARTED": 1,
            "HEAD_STARTED": 1,
            "CLEANUP_STARTED": 1,
        }
        reserved = (
            self._reserved_slots
            - (remaining.get(history[-1].action, 0) if history else 0)
            + remaining.get(event.action, 0)
        )
        if (
            self._bytes + size + reserved * self._policy.max_json_bytes
            > self._policy.max_snapshot_bytes
        ):
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        if not history:
            if event.action not in {"DOWNLOAD_ADMITTED", "DENIED", "CLEANUP_STARTED"}:
                raise ValueError("audit session must start with admission or denial")
            if (
                len(self._sessions)
                >= self._policy.max_pending_records * self._policy.max_list_records
            ):
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        else:
            previous, first = history[-1], history[0]
            identities = (
                "organization_id",
                "principal_id",
                "site_id",
                "work_area_id",
                "job_id",
                "expected_size_bytes",
                "output_sha256",
            )
            if (
                any(getattr(event, name) != getattr(first, name) for name in identities)
                or event.at < previous.at
            ):
                raise ValueError("audit identity/time changed")
            allowed = {
                "DOWNLOAD_ADMITTED": {"STREAM_STARTED", "HEAD_STARTED", "DENIED"},
                "STREAM_STARTED": {"STREAM_COMPLETED", "STREAM_INTERRUPTED"},
                "HEAD_STARTED": {"HEAD_COMPLETED", "STREAM_INTERRUPTED"},
                "CLEANUP_STARTED": {"CLEANUP_COMPLETED", "CLEANUP_FAILED"},
            }
            if event.action not in allowed.get(previous.action, set()):
                raise ValueError("invalid audit transition")
        if event.sent_bytes > event.expected_size_bytes or (
            event.action == "STREAM_COMPLETED" and event.sent_bytes != event.expected_size_bytes
        ):
            raise ValueError("invalid sent byte evidence")
        return size

    def _project(self, event: SpatialDataAuditEventV1, size: int) -> None:
        remaining = {
            "DOWNLOAD_ADMITTED": 2,
            "STREAM_STARTED": 1,
            "HEAD_STARTED": 1,
            "CLEANUP_STARTED": 1,
        }
        history = self._sessions.get(event.session_id, ())
        self._reserved_slots += remaining.get(event.action, 0) - (
            remaining.get(history[-1].action, 0) if history else 0
        )
        self._sequence += 1
        self._bytes += size
        self._events[event.event_id] = event
        self._sessions[event.session_id] = self._sessions.get(event.session_id, ()) + (event,)

    def append(self, event: SpatialDataAuditEventV1) -> None:
        with self._lock:
            if self._sealed or self._journal.sealed_reason is not None:
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
            try:
                event = SpatialDataAuditEventV1.model_validate(event.__dict__)
                existing = self._events.get(event.event_id)
                if existing is not None:
                    if existing != event:
                        raise ValueError("audit retry changed")
                    return
                size = self._validate(event)
            except SpatialDataDomainError:
                raise
            except (ValueError, TypeError) as exc:
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
            record = _Record(sequence=self._sequence + 1, event=event)
            try:
                self._journal.append(record.model_dump(by_alias=True, mode="json"))
            except BaseException as exc:
                self._sealed = True
                if not isinstance(exc, Exception):
                    raise
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
            self._project(event, size)

    def _limit(self, limit: int) -> None:
        if type(limit) is not int or not 0 < limit <= self._policy.max_list_records:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 422)

    def events(
        self, *, organization_id: str, session_id: str, limit: int
    ) -> tuple[SpatialDataAuditEventV1, ...]:
        self._limit(limit)
        with self._lock:
            items = self._sessions.get(session_id, ())
            return tuple(
                item.model_copy(deep=True)
                for item in items
                if item.organization_id == organization_id
            )[:limit]

    def unfinished(
        self, *, organization_id: str, limit: int
    ) -> tuple[SpatialDataAuditEventV1, ...]:
        self._limit(limit)
        with self._lock:
            return tuple(
                items[-1].model_copy(deep=True)
                for items in self._sessions.values()
                if items[-1].organization_id == organization_id
                and items[-1].action
                in {"DOWNLOAD_ADMITTED", "STREAM_STARTED", "HEAD_STARTED", "CLEANUP_STARTED"}
            )[:limit]

    def close(self) -> None:
        with self._lock:
            self._sealed = True
            self._journal.close()
