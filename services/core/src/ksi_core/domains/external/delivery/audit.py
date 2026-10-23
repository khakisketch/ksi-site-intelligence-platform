"""Fail-closed private download audit; byte counts mean acknowledged ASGI handoffs.

An unfinished start remains unfinished on restart. It is never evidence of a
client receiving bytes. No bearer, URL, filesystem path or storage key is
accepted here.

The default projection keeps every event and completed session in RAM with
the legacy finite admission bound. An explicitly versioned opt-in working set
(ADR-KSI-041) keeps only unfinished/active sessions live and serves retained
terminal history from a private derived index over the unchanged append-only
journal. Legacy behavior is unchanged when no valid opt-in is supplied.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import stat
from datetime import UTC, datetime
from threading import RLock
from time import monotonic, process_time
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
from pydantic import ConfigDict, Field, StrictInt, StringConstraints, model_validator

from ksi_core.domains.external.delivery.audit_history_index import (
    AuditHistoryIndex,
    AuditIndexCorruption,
    AuditIndexError,
    AuditIndexFull,
)
from ksi_core.domains.external.delivery.audit_working_set import SpatialDataAuditWorkingSetV1
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.foundation.durable_journal import (
    DurableJournal,
    JournalRecoveryError,
    JournalSealedError,
)

AuditId = Annotated[
    str,
    StringConstraints(
        strict=True, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    ),
]

logger = logging.getLogger("ksi_core.delivery.audit")
AuditAction = Literal[
    "DOWNLOAD_ADMITTED",
    "DENIED",
    "STREAM_STARTED",
    "STREAM_INTERRUPTED",
    "HEAD_STARTED",
    "HEAD_COMPLETED",
    "STREAM_COMPLETED",
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
    # Avoid data-dependent retained-history entries in Pydantic's bounded
    # global short-string cache (16,384 entries). Synthetic1531-record arms
    # retained ~210KiB by default versus ~13KiB here; neither figure proves
    # an aggregate native/transient RAM bound. False preserves JSON validation
    # and wire serialization semantics (no JSON-to-Python validation switch).
    model_config = ConfigDict(cache_strings=False)

    record_type: Literal["spatial-data-audit.v1"] = "spatial-data-audit.v1"
    sequence: PositiveInt
    event: SpatialDataAuditEventV1


class SpatialDataAuditRecoveryError(RuntimeError):
    pass


#: Session-start actions; everything else ends a session terminally.
_SESSION_START_ACTIONS = frozenset({"DOWNLOAD_ADMITTED", "DENIED", "CLEANUP_STARTED"})
_UNFINISHED_ACTIONS = frozenset(
    {"DOWNLOAD_ADMITTED", "STREAM_STARTED", "HEAD_STARTED", "CLEANUP_STARTED"}
)
_TERMINAL_BY_ACTION: dict[str, str | None] = {
    "DOWNLOAD_ADMITTED": None,
    "DENIED": "DENIED",
    "STREAM_STARTED": None,
    "STREAM_INTERRUPTED": "STREAM_INTERRUPTED",
    "HEAD_STARTED": None,
    "HEAD_COMPLETED": "HEAD_COMPLETED",
    "STREAM_COMPLETED": "STREAM_COMPLETED",
    "CLEANUP_STARTED": None,
    "CLEANUP_COMPLETED": "CLEANUP_COMPLETED",
    "CLEANUP_FAILED": "CLEANUP_FAILED",
}
_INDEX_PAGE_SIZE = 4096
_MAX_HISTORY_LOAD = 8

#: Structural pre-gate caps for one retained journal line (delivery mode).
#: Valid audit records are flat — ``{"recordType", "sequence",
#: "event":{...scalars...}}`` with ``extra="forbid"`` — so they never nest
#: deeper than 3, never use JSON arrays outside strings, and carry only a
#: small fixed key set. The gate scans raw bytes (O(1) memory, no JSON
#: parse, no object inflation) and rejects anything wilder BEFORE parsing:
#: an inflated shape such as ``{"junk":[...32700 items...]}`` is refused at
#: its opening bracket instead of being parsed — let alone deep-copied —
#: into megabytes of pointers. Margins (6/128) are multiples above every
#: valid record, so no valid history is rejected by this gate.
_MAX_AUDIT_LINE_DEPTH = 6
_MAX_AUDIT_LINE_COMMAS = 128


def _reject_unbounded_line_shape(line: bytes) -> None:
    """Refuse an inflated/unbounded retained line before parsing it.

    Raises ``ValueError`` for any line no valid ``_Record`` could produce.
    String contents are skipped (a bracket inside a quoted value is data,
    not structure); escapes are tracked so a quoted quote cannot end the
    string early. Callers map the refusal to journal-invalid, exactly like a
    failed model validation — malformed bytes were never trusted history.
    """
    depth = 0
    commas = 0
    in_string = False
    escaped = False
    for byte in line:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # closing quote
                in_string = False
            continue
        if byte == 0x22:  # opening quote
            in_string = True
        elif byte == 0x7B:  # {
            depth += 1
            if depth > _MAX_AUDIT_LINE_DEPTH:
                raise ValueError("retained line nests deeper than any valid audit record")
        elif byte == 0x7D:  # }
            depth -= 1
            if depth < 0:
                raise ValueError("retained line has unbalanced structure")
        elif byte == 0x5B:  # [ outside a string: no valid record has one
            raise ValueError("retained line uses an array shape no valid audit record has")
        elif byte == 0x2C:  # ,
            commas += 1
            if commas > _MAX_AUDIT_LINE_COMMAS:
                raise ValueError("retained line has more fields than any valid audit record")
    if in_string or depth != 0:
        raise ValueError("retained line is structurally incomplete")

#: Cold-boot derived disk peak: the retained index, the fresh rebuild target
#: and its transient rollback journal can coexist, plus bounded headers.
#: A cold boot holds no active spools, so this peak — not the 2x runtime
#: reserve — gates opt-in acceptance against the workspace envelope.
_INDEX_COLD_PEAK_MULTIPLIER = 3
_INDEX_COLD_OVERHEAD_BYTES = 16 * _INDEX_PAGE_SIZE


def audit_index_cold_peak_bytes(index_disk_bytes: int) -> int:
    """Worst-case derived disk footprint of a cold boot (no active spools).

    Counts the retained index at its page budget, the fresh rebuild target
    at the same budget, and its transient rollback journal, plus bounded
    file headers/framing. Runtime (which never rebuilds) instead reserves
    the configured 2x live+temp peak and admits spools by actual size.
    """
    return _INDEX_COLD_PEAK_MULTIPLIER * index_disk_bytes + _INDEX_COLD_OVERHEAD_BYTES

#: Record-envelope reserve added to the event cap for journal line bounds.
#: A valid audit record wraps one event (at most ``max_json_bytes``) in
#: ``{"recordType":"spatial-data-audit.v1","sequence":N,"event":...}`` — about
#: seventy bytes of framing plus sequence digits. The reserve keeps the line
#: bound queryable and safely above any valid record without approaching the
#: event cap itself.
_RECORD_ENVELOPE_RESERVE = 256


def audit_journal_max_line_bytes(policy: SpatialDataPolicyV1) -> int:
    """Largest journal line any valid audit record may occupy under ``policy``.

    Composition and boot stream bounds query this instead of hard-coding
    ``max_json_bytes + 1`` — a max-size event inside its record envelope is
    larger than one byte of framing, and that record must remain admissible.
    """
    return policy.max_json_bytes + _RECORD_ENVELOPE_RESERVE


class SpatialDataAuditStore:
    """Bounded private projection; caller supplies current tenant authorization.

    This store is not a public query API. Capacity exhaustion is explicit and
    closes new admissions; it never forgets unfinished sessions or truncates
    history.
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        policy: SpatialDataPolicyV1,
        working_set: SpatialDataAuditWorkingSetV1 | None = None,
    ) -> None:
        policy = SpatialDataPolicyV1.model_validate(policy.__dict__)
        if policy.policy_digest != policy.canonical_digest():
            raise ValueError("sealed audit resource policy required")
        self._journal = journal
        self._policy = policy
        self._working_set = working_set
        self._lock = RLock()
        self._events: dict[str, SpatialDataAuditEventV1] = {}
        self._sessions: dict[str, tuple[SpatialDataAuditEventV1, ...]] = {}
        self._session_bytes: dict[str, int] = {}
        self._bytes = 0
        self._reserved_slots = 0
        self._sequence = 0
        self._sealed = False
        self._history: AuditHistoryIndex | None = None
        # Constant-size run binding: the exact journal identity and derived
        # checkpoint this process validated at boot / last own commit. Run
        # paths re-check these before trusting an index miss or appending —
        # no per-append full scan, no history-sized state.
        self._run_journal_ident: tuple[int, int] | None = None
        self._run_journal_files = 0
        self._run_journal_end = 0
        self._run_data_version = 0
        self._pending_prev_config_digest: str | None = None
        # Single boot budget (blocker 6): one absolute wall deadline shared
        # from the journal open — never a fresh per-phase timer — plus a
        # separate process-CPU budget from the sealed envelope.
        self._boot_wall_deadline: float | None = None
        self._boot_cpu_start = 0.0
        self._boot_cpu_budget = float("inf")
        if working_set is None:
            try:
                for raw in journal.replay():
                    record = _Record.model_validate(raw)
                    if (
                        record.sequence != self._sequence + 1
                        or record.event.event_id in self._events
                    ):
                        raise ValueError("audit sequence/identity corrupted")
                    size = self._validate(record.event)
                    self._project(record.event, size)
            except Exception as exc:
                self._sealed = True
                raise SpatialDataAuditRecoveryError("invalid spatial data audit history") from exc
        else:
            try:
                self._boot_working_set(journal)
            except Exception as exc:
                self._sealed = True
                if self._history is not None:
                    with contextlib.suppress(AuditIndexError):
                        self._history.close()
                    self._history = None
                if isinstance(exc, SpatialDataAuditRecoveryError):
                    raise
                raise SpatialDataAuditRecoveryError(
                    "indexed audit working set refused to boot"
                ) from exc

    @property
    def policy(self) -> SpatialDataPolicyV1:
        return self._policy.model_copy(deep=True)

    @property
    def operation_scope(self) -> str:
        """Active operation scope — "full" legacy, "download-only" under opt-in."""
        if self._working_set is None:
            return "full"
        return self._working_set.allowed_operation_scope

    def disk_reserved_bytes(self) -> int:
        """Derived-index disk footprint counted in the shared workspace budget.

        A conservative configured constant — the live index at its page
        budget plus one equally sized rebuild/temp peak — not twice the
        current file size. The file grows toward the budget as retained
        history accumulates, so reserving only the current size would let
        spool admissions squeeze the index out later. Spool admission stays
        actual-size against the remaining workspace; session-count caps stay
        upper bounds, never a reason to reject the mode outright.
        Zero when the legacy projection is active, which keeps no derived
        disk state.
        """
        if self._working_set is None or self._history is None:
            return 0
        with self._lock:
            return self._working_set.index_disk_bytes * 2

    def _session_limit(self) -> int:
        if self._working_set is None:
            return self._policy.max_pending_records * self._policy.max_list_records
        return self._working_set.active_session_cap

    def _cache_allowance(self) -> int:
        if self._working_set is None:
            return 0
        return self._working_set.index_cache_allowance_bytes

    def _validate(self, event: SpatialDataAuditEventV1) -> int:
        return self._validate_with(event, self._sessions.get(event.session_id, ()))

    def _validate_with(
        self, event: SpatialDataAuditEventV1, history: tuple[SpatialDataAuditEventV1, ...]
    ) -> int:
        if event.event_digest != event.canonical_digest():
            raise ValueError("audit event not sealed")
        size = len(event.model_dump_json(by_alias=True).encode("utf-8"))
        if (
            size > self._policy.max_json_bytes
            or self._bytes + size > self._policy.max_snapshot_bytes
        ):
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
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
            self._bytes + size + reserved * self._policy.max_json_bytes + self._cache_allowance()
            > self._policy.max_snapshot_bytes
        ):
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        if not history:
            if event.action not in _SESSION_START_ACTIONS:
                raise ValueError("audit session must start with admission or denial")
            if len(self._sessions) >= self._session_limit():
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
        if self._working_set is not None:
            self._session_bytes[event.session_id] = (
                self._session_bytes.get(event.session_id, 0) + size
            )

    def _evict_terminal(self, session_id: str) -> None:
        """Drop a durably committed terminal session from the live working set.

        The session stays queryable through the retained journal + derived
        index. Only terminal sessions whose index commit succeeded may leave;
        unfinished sessions and their reservations are never evicted.
        """
        self._session_bytes.pop(session_id, None)
        if session_id in self._sessions:
            gone = {event.event_id for event in self._sessions[session_id]}
            self._events = {
                event_id: event for event_id, event in self._events.items() if event_id not in gone
            }
            del self._sessions[session_id]

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
                if self._history is not None:
                    self._append_indexed(event)
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

    def _find_indexed_event(self, event_id: str) -> SpatialDataAuditEventV1 | None:
        """Fetch one retained event by ID through the derived index (bounded).

        Returns None only when the run binding still proves the index tracks
        the journal exactly — a hot row deletion then seals instead of
        reporting a forged absence. Any addressed record whose bytes,
        session, organization, sequence or seal diverge seals the store.
        """
        assert self._history is not None
        try:
            found = self._history.find_event(event_id)
        except AuditIndexError as exc:
            self._sealed = True
            raise self._index_failure(exc) from exc
        if found is None:
            self._assert_run_binding()
            return None
        seq, row_session_id, file_index, offset, length = found
        if length > self._max_stream_line_bytes():
            self._sealed = True
            raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
        try:
            raw = self._journal.read_record_at(
                file_index, offset, length, max_bytes=self._max_stream_line_bytes()
            )
            record = _Record.model_validate(raw)
            organization = self._history.session_organization(row_session_id)
        except (JournalRecoveryError, JournalSealedError, ValueError, TypeError) as exc:
            self._sealed = True
            raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
        except AuditIndexError as exc:
            self._sealed = True
            raise self._index_failure(exc) from exc
        event = record.event
        if (
            record.sequence != seq
            or event.event_id != event_id
            or event.session_id != row_session_id
            or event.organization_id != organization
            or event.event_digest != event.canonical_digest()
        ):
            self._sealed = True
            raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
        return event

    def _append_indexed(self, event: SpatialDataAuditEventV1) -> None:
        """Indexed-history append: RAM validate, journal fsync, index commit, evict.

        The whole critical section runs under one held SQLite writer
        boundary: the writer lock is acquired BEFORE binding validation and
        identity/history queries, held across the authoritative journal fsync,
        and released only by the index commit. A hot external writer racing
        this section blocks or fails on the boundary instead of forking
        history underneath a check-then-act — no bare data-version re-check
        after the fact. A crash between the journal fsync and the index
        commit leaves the journal ahead of the checkpoint, which the bounded
        tail recovery replays on the next boot.
        """
        assert self._history is not None and self._working_set is not None
        history = self._history
        self._assert_run_binding()
        try:
            history.begin_write()
        except AuditIndexError as exc:
            self._sealed = True
            raise self._index_failure(exc) from exc
        try:
            self._assert_run_binding()
            indexed = self._find_indexed_event(event.event_id)
            if indexed is not None:
                if indexed != event:
                    raise ValueError("audit retry changed")
                history.commit_write()
                return
            if self._working_set.allowed_operation_scope == "history-only":
                # Recovery mode: retain and serve history, deny every NEW admission
                # (or conflicting retry) before any side effect. Exact retries of
                # retained events above remain silent no-ops.
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
            session_history = self._sessions.get(event.session_id)
            if session_history is None:
                session_history = self._indexed_session_state(event.session_id)
            try:
                size = self._validate_with(event, session_history)
            except SpatialDataDomainError:
                raise
            except (ValueError, TypeError) as exc:
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
            sequence = self._sequence + 1
            record = _Record(sequence=sequence, event=event)
            journal_end = self._journal_end_offset()
            try:
                self._journal.append(record.model_dump(by_alias=True, mode="json"))
            except BaseException as exc:
                self._sealed = True
                if not isinstance(exc, Exception):
                    raise
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
            journal_end_after = self._journal_end_offset()
            length = journal_end_after - journal_end
            if length <= 0:
                self._sealed = True
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
            if length > self._max_stream_line_bytes():
                # The journal just accepted a line no valid audit record can have.
                self._sealed = True
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
            # Post-fsync source/index binding: the writer boundary was held
            # from the pre-append checks through the journal fsync, so an
            # external SQLite commit could only have landed before we took
            # the boundary (already rejected by _assert_run_binding) or not
            # at all (it blocks on BEGIN IMMEDIATE with busy_timeout=0).
            # Re-pin the exact file identity, end offset and index version
            # after the fsync and before the index commit: a move or an
            # out-of-band index write here seals instead of manufacturing
            # absence or reopening a terminal session. The one legitimate
            # identity change is our own first append creating the lazily
            # created active file (run snapshot None, pre-stat end 0).
            try:
                post_ident = self._journal_identity()
                post_files = self._journal_file_count()
                post_version = history.data_version()
                post_checkpoint = history.checkpoint_seq()
            except (AuditIndexError, SpatialDataAuditRecoveryError) as exc:
                self._sealed = True
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
            if self._run_journal_ident is None:
                created_here = (
                    journal_end == 0
                    and journal_end_after == length
                    and post_ident is not None
                )
            else:
                created_here = False
            if (
                post_files != self._run_journal_files
                or journal_end != self._run_journal_end
                or journal_end_after != journal_end + length
                or post_version != self._run_data_version
                or post_checkpoint != self._sequence
                or (not created_here and post_ident != self._run_journal_ident)
            ):
                self._sealed = True
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
            try:
                history.commit_event_in_write_txn(
                    seq=sequence,
                    event_id=event.event_id,
                    session_id=event.session_id,
                    organization_id=event.organization_id,
                    terminal_action=_TERMINAL_BY_ACTION[event.action],
                    file_index=self._journal_file_count() - 1,
                    offset=journal_end,
                    length=length,
                    session_position=len(session_history),
                    checkpoint_meta=self._checkpoint_meta(
                        sequence,
                        end_offset=journal_end_after,
                        file_count=self._journal_file_count(),
                    ),
                )
            except AuditIndexError as exc:
                self._sealed = True
                raise self._index_failure(exc) from exc
            self._project(event, size)
            if _TERMINAL_BY_ACTION[event.action] is not None:
                self._bytes -= self._session_bytes.get(event.session_id, size)
                self._evict_terminal(event.session_id)
            # Adopt the pinned post-fsync proof BEFORE the releasing commit,
            # still under the boundary: the version read here is exact (our
            # uncommitted writes are visible to our reads while our commit
            # stays invisible to our version view). A foreign commit or a
            # late source replacement cannot land here unnoticed — both seal
            # instead of being adopted.
            try:
                self._adopt_validated_binding(
                    ident=post_ident,
                    files=post_files,
                    end=journal_end_after,
                    version=post_version,
                )
            except SpatialDataAuditRecoveryError as exc:
                self._sealed = True
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
            history.commit_write()
        except SpatialDataDomainError:
            history.rollback_write()
            raise
        except (ValueError, TypeError) as exc:
            history.rollback_write()
            raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
        except BaseException as exc:
            history.rollback_write()
            self._sealed = True
            if not isinstance(exc, Exception):
                raise
            raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc

    def _index_failure(self, exc: AuditIndexError) -> SpatialDataDomainError:
        if isinstance(exc, AuditIndexFull):
            return SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        return SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)

    def _indexed_session_state(self, session_id: str) -> tuple[SpatialDataAuditEventV1, ...]:
        """Session state for a session that left the live working set.

        Terminal sessions refuse before any history load. Unfinished sessions
        always live in RAM; finding one only in the index means the invariant
        broke, so the store seals instead of continuing on partial state.
        Unknown sessions on a validated-current index are genuinely new.
        """
        assert self._history is not None
        self._assert_run_binding()
        try:
            known = self._history.has_session(session_id)
            if not known:
                return ()
            terminal = self._history.session_terminal(session_id)
        except AuditIndexCorruption as exc:
            # The session vanished between the binding check and the read —
            # a hot change under this run, never a genuine state.
            self._sealed = True
            raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
        except AuditIndexError as exc:
            self._sealed = True
            raise self._index_failure(exc) from exc
        if terminal is not None:
            raise ValueError("audit session already terminal")
        self._sealed = True
        raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)

    def _terminal_history(
        self, session_id: str, *, limit: int
    ) -> tuple[SpatialDataAuditEventV1, ...]:
        """Serve one retained terminal session from journal + index (bounded).

        Every addressed record is verified against the index binding
        (sequence, session, event, identity, seal) before it is served. A
        divergent pointer seals the store instead of returning wrong history
        or an empty session. Tenant mismatch stays a silent empty result, so
        history existence is never disclosed across organizations.
        """
        assert self._history is not None
        try:
            organization = self._history.session_organization(session_id)
            addresses = self._history.session_events(
                session_id, limit=min(limit, _MAX_HISTORY_LOAD + 1)
            )
        except AuditIndexError as exc:
            self._sealed = True
            raise self._index_failure(exc) from exc
        if len(addresses) > _MAX_HISTORY_LOAD:
            # No legitimate session carries this many events: the transition
            # graph is acyclic and at most three deep.
            self._sealed = True
            raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
        found: list[SpatialDataAuditEventV1] = []
        for position, (seq, row_session, file_index, offset, length) in enumerate(addresses):
            if row_session != session_id:
                self._sealed = True
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
            try:
                raw = self._journal.read_record_at(
                    file_index, offset, length, max_bytes=self._max_stream_line_bytes()
                )
                record = _Record.model_validate(raw)
                bound_id = self._history.event_at(session_id, position)
            except (JournalRecoveryError, JournalSealedError, ValueError, TypeError) as exc:
                self._sealed = True
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
            except AuditIndexError as exc:
                self._sealed = True
                raise self._index_failure(exc) from exc
            event = record.event
            if (
                record.sequence != seq
                or event.session_id != session_id
                or event.event_id != bound_id
                or event.organization_id != organization
                or event.event_digest != event.canonical_digest()
            ):
                self._sealed = True
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
            found.append(event)
        return tuple(item for item in found if item.organization_id == organization)

    def _limit(self, limit: int) -> None:
        if type(limit) is not int or not 0 < limit <= self._policy.max_list_records:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 422)

    def events(
        self, *, organization_id: str, session_id: str, limit: int
    ) -> tuple[SpatialDataAuditEventV1, ...]:
        self._limit(limit)
        with self._lock:
            if self._history is not None and self._sealed:
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
            items = self._sessions.get(session_id)
            if items is not None:
                return tuple(
                    item.model_copy(deep=True)
                    for item in items
                    if item.organization_id == organization_id
                )[:limit]
            if self._history is None:
                return ()
            history = self._history
            try:
                history.begin_read()
            except AuditIndexError as exc:
                self._sealed = True
                raise self._index_failure(exc) from exc
            try:
                self._assert_run_binding()
                known = history.has_session(session_id)
                organization = history.session_organization(session_id) if known else None
                if not known or organization != organization_id:
                    found: tuple[SpatialDataAuditEventV1, ...] = ()
                else:
                    found = self._terminal_history(session_id, limit=limit)
            except BaseException as exc:
                history.rollback_write()
                if isinstance(exc, SpatialDataDomainError):
                    raise
                self._sealed = True
                if isinstance(exc, AuditIndexCorruption):
                    raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
                if isinstance(exc, AuditIndexError):
                    raise self._index_failure(exc) from exc
                raise
            try:
                history.end_read()
            except AuditIndexError as exc:
                self._sealed = True
                raise self._index_failure(exc) from exc
            return tuple(item.model_copy(deep=True) for item in found)[:limit]

    def unfinished(
        self, *, organization_id: str, limit: int
    ) -> tuple[SpatialDataAuditEventV1, ...]:
        self._limit(limit)
        with self._lock:
            if self._history is not None and self._sealed:
                raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
            if self._history is not None:
                self._assert_run_binding()
            return tuple(
                items[-1].model_copy(deep=True)
                for items in self._sessions.values()
                if items[-1].organization_id == organization_id
                and items[-1].action in _UNFINISHED_ACTIONS
            )[:limit]

    def close(self) -> None:
        with self._lock:
            self._sealed = True
            try:
                self._journal.close()
            finally:
                if self._history is not None:
                    with contextlib.suppress(AuditIndexError):
                        self._history.close()
                    self._history = None

    # -- Indexed-history working-set boot, rebuild and journal addressing --

    def _journal_file_count(self) -> int:
        return self._journal.file_count

    def _journal_end_offset(self) -> int:
        try:
            return self._journal.path.stat().st_size
        except FileNotFoundError:
            # The active journal file is created lazily on first append.
            return 0
        except OSError as exc:
            raise SpatialDataAuditRecoveryError(f"cannot stat audit journal: {exc}") from exc

    def _journal_identity(self) -> tuple[int, int] | None:
        """Live journal (dev, ino); None when the active file does not exist yet.

        A missing file with retained indexed history is evidence loss and must
        refuse; a missing file with an empty index is a fresh deploy.
        """
        try:
            entry = self._journal.path.stat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SpatialDataAuditRecoveryError(f"cannot identify audit journal: {exc}") from exc
        return (entry.st_dev, entry.st_ino)

    def _validate_journal_file(self) -> None:
        """Pin the authoritative journal file before derived state may trust it.

        Indexed mode only; legacy behavior is unchanged. A symlink, a
        non-regular file, a hard-linked file, or a file not exclusively owned
        0600 by this user is refused — the derived index may only track a
        source with exactly one pinned path. A missing file is a fresh
        deploy and passes; the binding checks handle retained history.
        """
        path = self._journal.path
        if path.is_symlink():
            raise SpatialDataAuditRecoveryError("audit journal must not be a symlink")
        try:
            entry = os.lstat(path)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise SpatialDataAuditRecoveryError(f"cannot inspect audit journal: {exc}") from exc
        if not stat.S_ISREG(entry.st_mode):
            raise SpatialDataAuditRecoveryError("audit journal must be a regular file")
        if entry.st_nlink != 1:
            raise SpatialDataAuditRecoveryError("audit journal must not be hard-linked")
        if entry.st_uid != os.geteuid() or stat.S_IMODE(entry.st_mode) != 0o600:
            raise SpatialDataAuditRecoveryError(
                "audit journal must be 0600 owned by the caller"
            )

    def _adopt_validated_binding(
        self,
        *,
        ident: tuple[int, int] | None,
        files: int,
        end: int,
        version: int,
    ) -> None:
        """Adopt EXACTLY the caller-validated source/binding proof token.

        The caller validated ``(ident, files, end)`` against the run binding
        (append: post-fsync pin) or the correspondence proof (boot: whole
        retained history); ``version`` is the index data version read
        alongside. This re-reads the live FS triple plus version/checkpoint
        under the held writer boundary and adopts the PINNED values only if
        everything still matches — a late source replacement (rename aside
        plus a fresh empty file installed between validation and adoption)
        seals here instead of being adopted just because the fresh path
        exists. The pinned triple must also extend the last committed
        checkpoint (same identity/files, end at or past the recorded
        offset); otherwise it is a replacement even if the tripwire itself
        raced, and the legitimate empty→first-inode creation stays allowed
        because the pin already validated that transition. No repair or
        truncation of authority files: a mismatch seals, and the next boot
        heals from the authoritative journal. Constant size.
        """
        assert self._history is not None and self._working_set is not None
        history = self._history
        try:
            live_ident = self._journal_identity()
            live_end = self._journal_end_offset()
            live_files = self._journal_file_count()
            live_version = history.data_version()
            live_checkpoint = history.checkpoint_seq()
            meta_dev = history.get_meta("journal_dev")
            meta_ino = history.get_meta("journal_ino")
            meta_files = history.get_meta("journal_files")
            meta_end = history.get_meta("journal_end_offset")
        except (AuditIndexError, SpatialDataAuditRecoveryError) as exc:
            self._sealed = True
            raise SpatialDataAuditRecoveryError(
                f"cannot adopt index run binding: {exc}"
            ) from exc
        if (
            live_ident != ident
            or live_files != files
            or live_end != end
            or live_version != version
            or live_checkpoint != self._sequence
        ):
            # Source or derived state moved between validation and adoption.
            self._sealed = True
            raise SpatialDataAuditRecoveryError(
                "source moved between validation and binding adoption — refuse"
            )
        if (
            meta_dev is not None
            and meta_ino is not None
            and meta_files is not None
            and meta_end is not None
        ):
            try:
                meta_files_int = int(meta_files)
                meta_end_int = int(meta_end)
            except (TypeError, ValueError) as exc:
                self._sealed = True
                raise SpatialDataAuditRecoveryError(
                    f"checkpoint offsets unreadable: {exc}"
                ) from exc
            if meta_dev == "0" and meta_ino == "0":
                # Fresh sentinel: no file identity was ever committed, so the
                # retained history must be empty — anything else is unindexed
                # content that the pre-boot rebuild would have established.
                if end != 0 or files != meta_files_int:
                    self._sealed = True
                    raise SpatialDataAuditRecoveryError(
                        "fresh checkpoint with non-empty source — refuse"
                    )
            else:
                try:
                    same_identity = ident is not None and (
                        str(ident[0]) == meta_dev and str(ident[1]) == meta_ino
                    )
                    same_files = files == meta_files_int
                    extends = end >= meta_end_int
                except (TypeError, ValueError) as exc:
                    self._sealed = True
                    raise SpatialDataAuditRecoveryError(
                        f"checkpoint offsets unreadable: {exc}"
                    ) from exc
                if not (same_identity and same_files and extends):
                    # A replacement file, not a continuation of the checkpoint.
                    self._sealed = True
                    raise SpatialDataAuditRecoveryError(
                        "adopted source does not extend the committed checkpoint — refuse"
                    )
        else:
            # No committed checkpoint yet: the retained history must be empty,
            # otherwise the pre-boot rebuild would have established one.
            if end != 0:
                self._sealed = True
                raise SpatialDataAuditRecoveryError(
                    "no committed checkpoint with non-empty source — refuse"
                )
        self._run_journal_ident = ident
        self._run_journal_files = files
        self._run_journal_end = end
        self._run_data_version = version
        assert live_checkpoint == self._sequence

    def _assert_run_binding(self) -> None:
        """Refuse (sealed) when source or derived state moved under this run.

        Boot validated an exact correspondence; run paths must not trust an
        index miss or accept an append once the journal identity, the file
        set, the end offset, the checkpoint, or any out-of-band index write
        (SQLite ``data_version``) changed. Own commits refresh the snapshot,
        so only foreign movement seals here.
        """
        assert self._working_set is not None and self._history is not None
        try:
            live_ident = self._journal_identity()
            live_end = self._journal_end_offset()
            live_files = self._journal_file_count()
            live_version = self._history.data_version()
            live_checkpoint = self._history.checkpoint_seq()
        except (AuditIndexError, SpatialDataAuditRecoveryError) as exc:
            self._sealed = True
            raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
        if (
            live_ident != self._run_journal_ident
            or live_files != self._run_journal_files
            or live_end != self._run_journal_end
            or live_version != self._run_data_version
            or live_checkpoint != self._sequence
        ):
            self._sealed = True
            raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)

    def _checkpoint_meta(
        self, sequence: int, *, end_offset: int, file_count: int
    ) -> dict[str, str]:
        assert self._working_set is not None
        identity = self._journal_identity()
        dev, ino = identity if identity is not None else (0, 0)
        return {
            "format": "audit-history-index.v1",
            "policy_digest": str(self._policy.policy_digest),
            "activation_id": self._working_set.activation_id,
            "journal_dev": str(dev),
            "journal_ino": str(ino),
            "journal_files": str(file_count),
            "journal_end_offset": str(end_offset),
            "max_seq": str(sequence),
        }

    def _max_stream_line_bytes(self) -> int:
        # A valid audit record wraps at most one max-JSON event in its small
        # record envelope; the bound is queryable from the policy so a
        # near-cap event stays admissible and every stream sight agrees.
        return audit_journal_max_line_bytes(self._policy)

    def _reset_active(self) -> None:
        self._events = {}
        self._sessions = {}
        self._session_bytes = {}
        self._bytes = 0
        self._reserved_slots = 0
        self._sequence = 0

    def _boot_working_set(self, journal: DurableJournal) -> None:
        """Boot the indexed mode: validate, verify/rebuild index, catch up, load."""
        assert self._working_set is not None
        working_set = self._working_set
        self._pending_prev_config_digest = None
        # One absolute boot budget shared from BEFORE the journal open: the
        # wall deadline is the journal's own recover deadline (its ctor
        # already enforced explicit bounds, starting from a timestamp the
        # composition captured before opening); a legacy journal without an
        # explicit deadline is bounded from its recorded open instant, never
        # a fresh per-phase timer. The CPU start is likewise the journal's
        # recorded open/start stamp, so recovery CPU already spent counts
        # against the same budget. Every I/O and SQL point below validates
        # both; a SQLite progress watch aborts long statements so exhaustion
        # fails closed instead of overrunning silently.
        wall_deadline = journal.recover_deadline
        if wall_deadline is None:
            journal_open_wall = getattr(journal, "open_monotonic", None)
            if journal_open_wall is None:
                wall_deadline = monotonic() + working_set.max_boot_seconds
            else:
                wall_deadline = float(journal_open_wall) + working_set.max_boot_seconds
        self._boot_wall_deadline = wall_deadline
        journal_cpu_start = getattr(journal, "recover_cpu_start", None)
        if journal_cpu_start is None:
            journal_cpu_start = getattr(journal, "open_cpu_start", None)
        self._boot_cpu_start = (
            float(journal_cpu_start) if journal_cpu_start is not None else process_time()
        )
        journal_cpu_budget = getattr(journal, "recover_cpu_budget", None)
        if journal_cpu_budget is None:
            self._boot_cpu_budget = min(
                float(self._policy.resource_envelope.max_cpu_seconds),
                float(working_set.max_boot_seconds),
            )
        else:
            self._boot_cpu_budget = min(
                float(self._policy.resource_envelope.max_cpu_seconds),
                float(working_set.max_boot_seconds),
                float(journal_cpu_budget),
            )
        scan = [0]
        if working_set.policy_digest != self._policy.policy_digest:
            raise SpatialDataAuditRecoveryError(
                "working-set policy digest does not match the sealed data policy"
            )
        if working_set.journal_file_name != journal.path.name:
            raise SpatialDataAuditRecoveryError(
                "working-set journal name does not match the mounted audit journal"
            )
        if self._policy.max_snapshot_bytes <= 2 * self._policy.max_json_bytes:
            raise SpatialDataAuditRecoveryError(
                "snapshot budget cannot admit any download under this working set"
            )
        workspace = self._policy.resource_envelope.max_workspace_bytes
        cold_peak = audit_index_cold_peak_bytes(working_set.index_disk_bytes)
        if cold_peak > workspace:
            # Cold-boot aggregate: the retained index, the fresh rebuild
            # target and its transient rollback journal (plus bounded
            # headers) coexist with no active spools. A 32M index on a 64M
            # workspace peaks near 96M, so it refuses here — no cap raise,
            # no silent sidecar. Runtime instead reserves 2x and admits
            # spools by actual size.
            raise SpatialDataAuditRecoveryError(
                "index cold-boot peak exceeds the workspace envelope"
            )
        session_bound = self._policy.max_pending_records * self._policy.max_list_records
        if working_set.active_session_cap > session_bound:
            # The working set can never admit more live sessions than the
            # sealed policy's own session bound — the opt-in carries no cap
            # increase, so a wider request fails closed here, not at 3am.
            raise SpatialDataAuditRecoveryError(
                "working-set session cap exceeds the sealed policy session bound"
            )
        if working_set.index_cache_allowance_bytes >= self._policy.max_snapshot_bytes:
            raise SpatialDataAuditRecoveryError(
                "working-set cache allowance leaves no snapshot for any admission"
            )
        self._validate_journal_file()
        journal_path = journal.path
        index_path = journal_path.with_name(journal_path.stem + ".ws.sqlite3")
        max_pages = working_set.index_disk_bytes // _INDEX_PAGE_SIZE
        watched: list[AuditHistoryIndex] = []
        try:
            try:
                history = AuditHistoryIndex(
                    index_path,
                    max_pages=max_pages,
                    create=True,
                    deadline=self._past_boot_deadline,
                )
            except AuditIndexCorruption:
                # Unreadable derived state (wrong page size, oversize budget) is
                # rebuilt from the authoritative journal, never reinterpreted.
                self._reset_active()
                self._rebuild_index(journal, scan, watched)
                assert self._history is not None
                history = self._history
            except AuditIndexError as exc:
                raise SpatialDataAuditRecoveryError(
                    f"cannot open audit history index: {exc}"
                ) from exc
            self._history = history
            watched.append(history)
            try:
                history.quick_check()
                if history.user_version() != 1:
                    raise AuditIndexCorruption("unknown index version")
                if not self._binding_current():
                    if self._journal_replaced():
                        raise SpatialDataAuditRecoveryError(
                            "audit journal was replaced under its index"
                            " — refuse, never rebuild over it"
                        )
                    self._reset_active()
                    self._rebuild_index(journal, scan, watched)
                self._ensure_config_binding(journal, scan, watched)
                self._catch_up_tail(journal, scan)
                self._verify_load_and_activate(journal, scan)
            except self._IndexContradiction as exc:
                # Present-but-contradictory derived rows: fail closed with a
                # sealed store instead of rebuilding over the contradiction.
                # Construction still succeeds so every later read or append
                # refuses loudly; the journal is untouched.
                self._sealed = True
                logger.warning("indexed audit history contradicts its journal: %s", exc)
                return
            except (AuditIndexError, AuditIndexCorruption) as exc:
                self._reset_active()
                try:
                    self._check_deadline()
                    self._rebuild_index(journal, scan, watched)
                    self._ensure_config_binding(journal, scan, watched)
                    self._catch_up_tail(journal, scan)
                    self._verify_load_and_activate(journal, scan)
                except SpatialDataAuditRecoveryError:
                    raise
                except self._IndexContradiction as retry_exc:
                    self._sealed = True
                    logger.warning(
                        "rebuilt audit index still contradicts its journal: %s", retry_exc
                    )
                    return
                except (AuditIndexError, AuditIndexCorruption) as retry_exc:
                    raise SpatialDataAuditRecoveryError(
                        f"indexed history rebuild refused after {type(exc).__name__}: {retry_exc}"
                    ) from retry_exc
        finally:
            for watched_history in watched:
                watched_history.unwatch_deadline()

    def _working_set_canonical_json(self) -> str:
        """Full versioned working-set binding in canonical form (traceability)."""
        assert self._working_set is not None
        return json.dumps(
            self._working_set.model_dump(by_alias=True, mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )

    def _ensure_config_binding(
        self, journal: DurableJournal, scan: list[int], watched: list[AuditHistoryIndex]
    ) -> None:
        """Enforce the versioned binding, allowing an explicit scope switch.

        An unchanged binding (or a fresh index) passes. A changed binding is
        refused — silently reinterpreting retained history under new bounds
        would break the activation's explicit contract — with exactly one
        approved transition: the operation scope alone changed while the
        sealed policy and the exact source journal stayed the same. That
        recovery transition rebuilds the derived index from the retained
        journal within explicit bounds (the journal itself is never
        rewritten) and records the previous digest for traceability. Any
        other change — bounds, activation, paths, policy, source — refuses.
        """
        assert self._history is not None and self._working_set is not None
        history = self._history
        try:
            recorded_digest = history.get_meta("config_digest")
            recorded_raw = history.get_meta("audit_working_set_json")
        except AuditIndexError as exc:
            raise SpatialDataAuditRecoveryError(f"cannot read index binding: {exc}") from exc
        current_digest = self._working_set.config_digest()
        if recorded_raw in (None, ""):
            if recorded_digest in (None, ""):
                # Fresh derived state (just rebuilt) — the activation trace
                # records the current binding below.
                return
            # A digest-only binding from a previous implementation cannot
            # prove a scope-only switch — a changed digest refuses here
            # instead of being silently reinterpreted.
            if recorded_digest != current_digest:
                raise SpatialDataAuditRecoveryError(
                    "working-set configuration changed under retained index — refuse"
                )
            return
        if recorded_digest == current_digest:
            return
        try:
            recorded = json.loads(recorded_raw)
            current_doc = json.loads(self._working_set_canonical_json())
        except ValueError as exc:
            raise SpatialDataAuditRecoveryError(
                "working-set configuration changed under retained index — refuse"
            ) from exc
        if not isinstance(recorded, dict) or not isinstance(current_doc, dict):
            raise SpatialDataAuditRecoveryError(
                "working-set configuration changed under retained index — refuse"
            )
        if recorded.get("policy_digest") != str(self._working_set.policy_digest):
            raise SpatialDataAuditRecoveryError(
                "working-set configuration changed under retained index — refuse"
            )
        if set(recorded) != set(current_doc) or {
            key for key in current_doc if recorded.get(key) != current_doc.get(key)
        } != {"allowed_operation_scope"}:
            raise SpatialDataAuditRecoveryError(
                "working-set configuration changed under retained index — refuse"
            )
        try:
            recorded_dev = history.get_meta("journal_dev")
            recorded_ino = history.get_meta("journal_ino")
        except AuditIndexError as exc:
            raise SpatialDataAuditRecoveryError(
                "working-set configuration changed under retained index — refuse"
            ) from exc
        live = self._journal_identity()
        if (
            live is None
            or recorded_dev != str(live[0])
            or recorded_ino != str(live[1])
        ):
            raise SpatialDataAuditRecoveryError(
                "working-set configuration changed under retained index — refuse"
            )
        self._pending_prev_config_digest = recorded_digest
        self._reset_active()
        self._rebuild_index(journal, scan, watched)

    def _verify_correspondence(self, journal: DurableJournal, scan: list[int]) -> None:
        """Prove the derived index addresses exactly the retained journal.

        Every journal record streams once as raw bytes within explicit
        byte/deadline bounds and is checked against the index row that must
        address it:
        sequence, event, session, organization, file position and length,
        session order position, and the canonical admission rules over
        bounded predecessors read back from the journal. Session starts,
        event counts, the checkpoint and the linkage aggregates must agree
        as well. Python RAM stays constant — one small raw-byte batch in
        flight, one structurally pre-gated record validated at a time, no
        history map — and every probe is a bounded seek or an indexed,
        sort-free SQL lookup. Journal-side invalidity refuses; index-side
        divergence raises corruption so boot rebuilds instead of trusting it.
        """
        assert self._history is not None and self._working_set is not None
        history = self._history
        budget = self._working_set.max_boot_scan_bytes
        expected = 0
        session_starts = 0
        cursor: tuple[int, int] = (0, 0)
        max_line = self._max_stream_line_bytes()
        while True:
            self._check_deadline()
            items, cursor, eof = journal.stream_record_bytes(
                cursor, limit_records=16, limit_bytes=256 * 1024, max_line_bytes=max_line
            )
            for file_index, offset, length, raw in items:
                self._check_deadline()
                scan[0] += length
                if scan[0] > budget:
                    raise SpatialDataAuditRecoveryError(
                        "correspondence scan exceeded its byte budget"
                    )
                try:
                    _reject_unbounded_line_shape(raw)
                    record = _Record.model_validate_json(raw)
                except (ValueError, TypeError) as exc:
                    raise SpatialDataAuditRecoveryError(
                        f"correspondence hit an invalid record: {exc}"
                    ) from exc
                expected += 1
                if record.sequence != expected:
                    raise SpatialDataAuditRecoveryError(
                        "correspondence hit a sequence gap in retained history"
                    )
                event = record.event
                if event.event_digest != event.canonical_digest():
                    raise SpatialDataAuditRecoveryError(
                        "correspondence hit an unsealed retained event"
                    )
                try:
                    found = history.find_event(event.event_id)
                except AuditIndexCorruption:
                    raise
                except AuditIndexError as exc:
                    raise SpatialDataAuditRecoveryError(
                        f"correspondence cannot load bounded prior state: {exc}"
                    ) from exc
                if found is None or tuple(found) != (
                    expected,
                    event.session_id,
                    file_index,
                    offset,
                    length,
                ):
                    if found is None:
                        # Incomplete derived state — the bounded rebuild below
                        # re-derives it from the journal; absence is never
                        # trusted as genuine here.
                        raise AuditIndexCorruption(
                            "index does not address the retained journal — rebuild or refuse"
                        )
                    # A present row pointing at the wrong bytes contradicts
                    # the authority — seal, never reinterpret or rewrite.
                    raise self._IndexContradiction(
                        f"indexed event {event.event_id} no longer addresses its journal record"
                    )
                try:
                    organization = history.session_organization(event.session_id)
                    addresses = history.session_events(
                        event.session_id, limit=_MAX_HISTORY_LOAD + 1
                    )
                except AuditIndexCorruption:
                    raise
                except AuditIndexError as exc:
                    raise SpatialDataAuditRecoveryError(
                        f"correspondence cannot load bounded prior state: {exc}"
                    ) from exc
                if len(addresses) > _MAX_HISTORY_LOAD:
                    raise SpatialDataAuditRecoveryError(
                        "correspondence hit an unbounded retained session"
                    )
                if organization != event.organization_id:
                    # The session row is present but names another tenant —
                    # contradiction, not absence: seal instead of rebuilding
                    # over it.
                    raise self._IndexContradiction(
                        f"indexed session {event.session_id} changed organization"
                    )
                position: int | None = None
                for probe0, (seq0, _row0, _file0, _off0, _len0) in enumerate(addresses):
                    if seq0 == expected:
                        position = probe0
                        break
                if position is None:
                    raise AuditIndexCorruption(
                        "indexed session order diverged from the journal"
                    )
                try:
                    bound = history.event_at(event.session_id, position)
                except AuditIndexCorruption:
                    raise
                except AuditIndexError as exc:
                    raise SpatialDataAuditRecoveryError(
                        f"correspondence cannot verify retained order: {exc}"
                    ) from exc
                if bound != event.event_id:
                    raise self._IndexContradiction(
                        f"indexed session {event.session_id} order contradicts its journal"
                    )
                if position == 0:
                    # Sessions are counted by verified order position, not by
                    # action membership: a valid DOWNLOAD_ADMITTED→DENIED
                    # session carries two start-action events but occupies
                    # exactly one session row.
                    session_starts += 1
                prior: tuple[SpatialDataAuditEventV1, ...] = ()
                for probe in range(position):
                    pseq, prow, pfile, poff, plen = addresses[probe]
                    if prow != event.session_id:
                        raise AuditIndexCorruption(
                            "indexed session order diverged from the journal"
                        )
                    scan[0] += plen
                    if scan[0] > budget:
                        raise SpatialDataAuditRecoveryError(
                            "correspondence scan exceeded its byte budget"
                        )
                    try:
                        praw = journal.read_record_at(
                            pfile, poff, plen, max_bytes=max_line
                        )
                        precord = _Record.model_validate(praw)
                        pbound = history.event_at(event.session_id, probe)
                    except (JournalRecoveryError, JournalSealedError, ValueError, TypeError) as exc:
                        raise SpatialDataAuditRecoveryError(
                            f"correspondence hit an unreadable retained predecessor: {exc}"
                        ) from exc
                    except AuditIndexCorruption:
                        raise
                    except AuditIndexError as exc:
                        raise SpatialDataAuditRecoveryError(
                            "correspondence cannot verify retained order"
                        ) from exc
                    if (
                        precord.sequence != pseq
                        or precord.event.session_id != event.session_id
                        or precord.event.event_id != pbound
                        or precord.event.event_digest != precord.event.canonical_digest()
                    ):
                        # The predecessor journal bytes were already verified
                        # this scan — a disagreeing index row now is a
                        # contradiction, not an incomplete derivation.
                        raise self._IndexContradiction(
                            "indexed predecessor contradicts the retained journal"
                        )
                    prior = prior + (precord.event,)
                try:
                    self._validate_with(event, prior)
                except SpatialDataDomainError as exc:
                    raise SpatialDataAuditRecoveryError(
                        f"correspondence retained history violates admission: {exc}"
                    ) from exc
                except (ValueError, TypeError) as exc:
                    raise SpatialDataAuditRecoveryError(
                        f"correspondence retained history invalid: {exc}"
                    ) from exc
            if eof:
                break
        try:
            indexed_sessions, indexed_events, indexed_max = history.stats()
            history.verify_linkage()
            checkpoint = history.checkpoint_seq()
        except AuditIndexCorruption:
            raise
        except AuditIndexError as exc:
            raise SpatialDataAuditRecoveryError(
                f"cannot read index correspondence: {exc}"
            ) from exc
        if checkpoint != indexed_max:
            # The checkpoint trails (or leads) the rows it claims to cover —
            # re-derive both from the journal instead of trusting either.
            raise AuditIndexCorruption(
                "index checkpoint does not match the indexed maximum"
            )
        if (session_starts, expected, expected) != (
            indexed_sessions,
            indexed_events,
            indexed_max,
        ):
            raise AuditIndexCorruption(
                "index does not cover the retained journal — rebuild or refuse"
            )
        self._verify_session_summaries(journal, scan, budget, indexed_sessions)

    def _verify_session_summaries(
        self, journal: DurableJournal, scan: list[int], budget: int, indexed_sessions: int
    ) -> None:
        """Re-prove every session summary row against authoritative journal bytes.

        The per-record pass above proves each event; this pass proves the
        session aggregates — ``organization_id``, ``terminal_action``,
        ``last_seq``, ``event_count``, ``created_seq`` — by paging every
        session in admission order and re-reading its bounded first/last
        history from the journal. Forging any single field (for example
        flipping an unfinished session's terminal action to hide its
        reservation, or inventing terminality) diverges here and routes to
        bounded rebuild or refusal with the journal untouched. Counts and
        created order are validated too, so no summary can hide or invent
        sessions. Python RAM stays one page plus one bounded session in
        flight; every probe is an indexed, sort-free lookup plus bounded
        seeks. Journal-side invalidity refuses; derived-side divergence is
        corruption.
        """
        assert self._history is not None and self._working_set is not None
        history = self._history
        max_line = self._max_stream_line_bytes()
        offset = 0
        previous_created = 0
        verified = 0
        while True:
            self._check_deadline()
            try:
                page = history.sessions_page(offset, 16)
            except AuditIndexCorruption:
                raise
            except AuditIndexError as exc:
                raise SpatialDataAuditRecoveryError(
                    f"correspondence cannot page session summaries: {exc}"
                ) from exc
            if not page:
                break
            offset += len(page)
            for session_id, organization, terminal, last_seq, event_count, created in page:
                self._check_deadline()
                verified += 1
                if not previous_created < created:
                    # Created order must be the true first-appearance order:
                    # strictly increasing in admission-order pagination.
                    raise AuditIndexCorruption(
                        "indexed session creation order diverged from the journal"
                    )
                previous_created = created
                if event_count < 1:
                    raise AuditIndexCorruption(
                        "indexed session summary claims an empty session"
                    )
                try:
                    addresses = history.session_events(
                        session_id, limit=_MAX_HISTORY_LOAD + 1
                    )
                except AuditIndexCorruption:
                    raise
                except AuditIndexError as exc:
                    raise SpatialDataAuditRecoveryError(
                        f"correspondence cannot load bounded prior state: {exc}"
                    ) from exc
                if len(addresses) != event_count or len(addresses) > _MAX_HISTORY_LOAD:
                    raise AuditIndexCorruption(
                        "indexed session event count diverged from its history"
                    )
                if addresses[0][0] != created or addresses[-1][0] != last_seq:
                    raise AuditIndexCorruption(
                        "indexed session first/last sequence diverged from its history"
                    )
                rebuilt: tuple[SpatialDataAuditEventV1, ...] = ()
                for position, (seq, row_session, file_index, offset_, length) in enumerate(
                    addresses
                ):
                    if row_session != session_id:
                        raise AuditIndexCorruption(
                            "indexed session order diverged from the journal"
                        )
                    scan[0] += length
                    if scan[0] > budget:
                        raise SpatialDataAuditRecoveryError(
                            "correspondence scan exceeded its byte budget"
                        )
                    try:
                        raw = journal.read_record_at(
                            file_index, offset_, length, max_bytes=max_line
                        )
                        record = _Record.model_validate(raw)
                        bound = history.event_at(session_id, position)
                    except (JournalRecoveryError, JournalSealedError, ValueError, TypeError) as exc:
                        raise SpatialDataAuditRecoveryError(
                            f"correspondence hit an unreadable retained session: {exc}"
                        ) from exc
                    except AuditIndexCorruption:
                        raise
                    except AuditIndexError as exc:
                        raise SpatialDataAuditRecoveryError(
                            "correspondence cannot verify retained order"
                        ) from exc
                    if (
                        record.sequence != seq
                        or record.event.session_id != session_id
                        or record.event.event_id != bound
                        or record.event.event_digest != record.event.canonical_digest()
                    ):
                        raise AuditIndexCorruption(
                            "indexed session history diverged from the journal"
                        )
                    rebuilt = rebuilt + (record.event,)
                first, last = rebuilt[0], rebuilt[-1]
                if organization != first.organization_id:
                    raise self._IndexContradiction(
                        f"indexed session {session_id} changed organization"
                    )
                if terminal != _TERMINAL_BY_ACTION[last.action]:
                    raise AuditIndexCorruption(
                        "indexed session terminal state diverged from its history"
                    )
                try:
                    chain: tuple[SpatialDataAuditEventV1, ...] = ()
                    for event in rebuilt:
                        self._validate_with(event, chain)
                        chain = chain + (event,)
                except SpatialDataDomainError as exc:
                    raise SpatialDataAuditRecoveryError(
                        f"correspondence retained session violates admission: {exc}"
                    ) from exc
                except (ValueError, TypeError) as exc:
                    raise SpatialDataAuditRecoveryError(
                        f"correspondence retained session invalid: {exc}"
                    ) from exc
        if verified != indexed_sessions:
            raise AuditIndexCorruption(
                "indexed session page walk diverged from the session count"
            )

    def _journal_replaced(self) -> bool:
        """True when the index names a different journal file than the live one.

        A replaced journal is refused, never silently re-indexed: rebuilding
        over a swapped source would drop retained history from the lookup.
        """
        assert self._history is not None
        try:
            recorded_dev = self._history.get_meta("journal_dev")
            recorded_ino = self._history.get_meta("journal_ino")
        except AuditIndexError:
            return False
        if recorded_dev is None or recorded_ino is None:
            return False
        if recorded_dev == "0" and recorded_ino == "0":
            # Fresh sentinel: no retained file identity was ever committed.
            return False
        live = self._journal_identity()
        if live is None:
            # Retained history is indexed but the journal file is gone.
            return True
        return recorded_dev != str(live[0]) or recorded_ino != str(live[1])

    def _verify_load_and_activate(self, journal: DurableJournal, scan: list[int]) -> None:
        """Prove correspondence and adopt the binding atomically (boot).

        The writer boundary is held from the correspondence proof through
        the activation-trace commit: no foreign commit can land between the
        proof and the adoption (it blocks on the boundary and is caught by
        the next run check). The source proof token is pinned before the
        proof and re-read after it — any FS replacement during verification
        seals instead of being adopted — and adoption reuses exactly the
        post-proof pin, fenced by the committed checkpoint. A foreign delete
        that slips in earlier is caught by the proof itself (corruption →
        bounded rebuild, contradiction → seal).
        """
        assert self._history is not None and self._working_set is not None
        history = self._history
        try:
            history.begin_write()
        except AuditIndexError as exc:
            raise SpatialDataAuditRecoveryError(
                f"index writer boundary refused: {exc}"
            ) from exc
        try:
            try:
                pre_ident = self._journal_identity()
                pre_end = self._journal_end_offset()
                pre_files = self._journal_file_count()
            except SpatialDataAuditRecoveryError as exc:
                raise SpatialDataAuditRecoveryError(
                    f"cannot pin pre-proof source state: {exc}"
                ) from exc
            self._verify_correspondence(journal, scan)
            self._load_unfinished(scan)
            assert self._history is not None
            self._sequence = self._history.checkpoint_seq()
            # Pin the validated source proof token: the correspondence proof
            # just covered exactly this journal state, so adoption below must
            # use THESE values — a late replacement is refused, never adopted.
            try:
                pinned_ident = self._journal_identity()
                pinned_end = self._journal_end_offset()
                pinned_files = self._journal_file_count()
                pinned_version = history.data_version()
            except (AuditIndexError, SpatialDataAuditRecoveryError) as exc:
                raise SpatialDataAuditRecoveryError(
                    f"cannot pin validated source state: {exc}"
                ) from exc
            if (
                pinned_ident != pre_ident
                or pinned_end != pre_end
                or pinned_files != pre_files
            ):
                raise SpatialDataAuditRecoveryError(
                    "source moved during verification — refuse"
                )
            self._write_activation_trace(
                pinned_ident=pinned_ident,
                pinned_files=pinned_files,
                pinned_end=pinned_end,
                pinned_version=pinned_version,
            )
            history.commit_write()
        except BaseException:
            history.rollback_write()
            raise

    def _write_activation_trace(
        self,
        *,
        pinned_ident: tuple[int, int] | None,
        pinned_files: int,
        pinned_end: int,
        pinned_version: int,
    ) -> None:
        """Traceability record of this activation on the derived index (not authority).

        Records the full versioned binding — canonical config JSON plus its
        digest, the sealed policy digest and the activation tag — never the
        tag alone, so a later boot can tell an approved scope switch from a
        reinterpretation. A scope-switch rebuild additionally records the
        previous digest it replaced. The run binding adoption here uses the
        caller-pinned validated source proof token: every later miss or
        append re-checks it before trusting the index.

        The caller holds the writer boundary and its single releasing commit
        applies these writes atomically with the adopted proof token, so no
        foreign change and no late source replacement is ever adopted.
        """
        assert self._history is not None and self._working_set is not None
        meta = {
            "activation_id": self._working_set.activation_id,
            "activated_at": datetime.now(UTC).isoformat(),
            "max_seq": str(self._sequence),
            "policy_digest": str(self._working_set.policy_digest),
            "config_digest": self._working_set.config_digest(),
            "audit_working_set_json": self._working_set_canonical_json(),
        }
        if self._pending_prev_config_digest is not None:
            meta["prev_config_digest"] = self._pending_prev_config_digest
        try:
            assert self._history is not None
            self._history.set_meta_in_write_txn(meta)
        except AuditIndexError as exc:
            raise SpatialDataAuditRecoveryError(f"cannot record activation trace: {exc}") from exc
        self._pending_prev_config_digest = None
        self._adopt_validated_binding(
            ident=pinned_ident,
            files=pinned_files,
            end=pinned_end,
            version=pinned_version,
        )
        self._check_deadline()

    def _check_deadline(self) -> None:
        if self._boot_wall_deadline is not None and monotonic() > self._boot_wall_deadline:
            raise SpatialDataAuditRecoveryError("working-set boot exceeded its deadline")
        if process_time() - self._boot_cpu_start > self._boot_cpu_budget:
            raise SpatialDataAuditRecoveryError("working-set boot exceeded its CPU budget")

    def _past_boot_deadline(self) -> bool:
        """True once the single shared boot budget is exhausted (wall OR CPU).

        The SQLite progress watch calls this during long statements, so CPU
        burned inside SQL aborts promptly even while wall time is unexpired.
        """
        if self._boot_wall_deadline is not None and monotonic() > self._boot_wall_deadline:
            return True
        return (process_time() - self._boot_cpu_start) > self._boot_cpu_budget

    def _binding_current(self) -> bool:
        """True when the derived index verifiably tracks this exact journal+policy."""
        assert self._history is not None and self._working_set is not None
        history = self._history
        try:
            if history.get_meta("format") != "audit-history-index.v1":
                return False
            if history.get_meta("policy_digest") != self._policy.policy_digest:
                return False
            live = self._journal_identity()
            if live is None:
                # No journal file yet: current only when the index also holds no
                # retained history (fresh deploy, zero committed sequence).
                return history.checkpoint_seq() == 0
            if history.get_meta("journal_dev") != str(live[0]):
                return False
            if history.get_meta("journal_ino") != str(live[1]):
                return False
            if history.get_meta("journal_files") != str(self._journal_file_count()):
                return False
            end = int(history.get_meta("journal_end_offset") or "-1")
        except (AuditIndexError, ValueError):
            return False
        try:
            live_end = self._journal_end_offset()
        except SpatialDataAuditRecoveryError:
            return False
        return end >= 0 and live_end >= end

    class _HistoricalInvalid(ValueError):
        """A retained record violates the canonical admission rules."""

    class _IndexContradiction(Exception):
        """Derived rows are present but contradict the retained journal.

        Absent rows heal from the authority via bounded rebuild; contradictory
        rows fail closed instead — the store seals and every later read or
        append refuses loudly without touching the journal.
        """

    def _commit_historical_record(
        self,
        history: AuditHistoryIndex,
        journal: DurableJournal,
        expected_seq: int,
        file_index: int,
        offset: int,
        length: int,
        raw: bytes,
        *,
        label: str,
    ) -> int:
        """Validate one retained record with the canonical rules and index it.

        Prior session state comes only from the bounded derived index — no
        history-sized RAM. Every rule the live append path enforces
        (identities, transitions, time, byte evidence, sealed events) applies
        identically here; legacy corruptions are refused, never normalized.
        Returns the predecessor bytes re-read so callers can account them
        against the same scan budget — the tail and rebuild windows stay
        total-bounded, not just stream-bounded. The raw line is refused by
        the structural pre-gate before any generic parse, so inflated shapes
        never accumulate as objects; one validated record at a time is held.
        """
        try:
            _reject_unbounded_line_shape(raw)
            record = _Record.model_validate_json(raw)
        except (ValueError, TypeError) as exc:
            raise self._HistoricalInvalid(f"{label} hit an invalid record: {exc}") from exc
        if record.sequence != expected_seq:
            raise self._HistoricalInvalid(f"{label} hit a sequence gap in retained history")
        event = record.event
        if event.event_digest != event.canonical_digest():
            raise self._HistoricalInvalid(f"{label} hit an unsealed retained event")
        try:
            if history.has_session(event.session_id):
                addresses = history.session_events(event.session_id, limit=_MAX_HISTORY_LOAD + 1)
            else:
                addresses = []
        except AuditIndexError as exc:
            raise SpatialDataAuditRecoveryError(
                f"{label} cannot load bounded prior state: {exc}"
            ) from exc
        if len(addresses) > _MAX_HISTORY_LOAD:
            raise self._HistoricalInvalid(f"{label} hit an unbounded retained session")
        prior: tuple[SpatialDataAuditEventV1, ...] = ()
        reread = 0
        for position0, (_seq, row_session0, file_index0, offset0, length0) in enumerate(addresses):
            if row_session0 != event.session_id:
                raise self._HistoricalInvalid(f"{label} hit a divergent retained predecessor")
            reread += length0
            try:
                raw0 = journal.read_record_at(
                    file_index0, offset0, length0, max_bytes=self._max_stream_line_bytes()
                )
                prior_record = _Record.model_validate(raw0)
            except (JournalRecoveryError, JournalSealedError, ValueError, TypeError) as exc:
                raise self._HistoricalInvalid(
                    f"{label} hit an unreadable retained predecessor: {exc}"
                ) from exc
            try:
                bound_id = history.event_at(event.session_id, position0)
            except AuditIndexError as exc:
                raise SpatialDataAuditRecoveryError(
                    f"{label} cannot verify retained order: {exc}"
                ) from exc
            if (
                prior_record.sequence != _seq
                or prior_record.event.session_id != event.session_id
                or prior_record.event.event_id != bound_id
                or prior_record.event.event_digest != prior_record.event.canonical_digest()
            ):
                raise self._HistoricalInvalid(f"{label} hit a divergent retained predecessor")
            prior = prior + (prior_record.event,)
        try:
            self._validate_with(event, prior)
        except SpatialDataDomainError as exc:
            raise self._HistoricalInvalid(
                f"{label} retained history violates admission: {exc}"
            ) from exc
        except (ValueError, TypeError) as exc:
            raise self._HistoricalInvalid(f"{label} retained history invalid: {exc}") from exc
        try:
            history.commit_event(
                seq=record.sequence,
                event_id=event.event_id,
                session_id=event.session_id,
                organization_id=event.organization_id,
                terminal_action=_TERMINAL_BY_ACTION[event.action],
                file_index=file_index,
                offset=offset,
                length=length,
                session_position=len(addresses),
                checkpoint_meta=self._checkpoint_meta(
                    record.sequence,
                    end_offset=offset + length,
                    file_count=self._journal_file_count(),
                ),
            )
        except AuditIndexError as exc:
            raise SpatialDataAuditRecoveryError(
                f"{label} cannot commit derived state: {exc}"
            ) from exc
        return reread

    def _rebuild_index(
        self, journal: DurableJournal, scan: list[int], watched: list[AuditHistoryIndex]
    ) -> None:
        """Bounded full re-index into a temp file, atomically renamed on success.

        The live index (if any) is left untouched until the replacement
        commits; a failed rebuild never deletes derived state still in use.
        A missing live index (failed open) simply means there is nothing to
        close before activation.
        """
        assert self._working_set is not None
        working_set = self._working_set
        journal_path = journal.path
        index_path = journal_path.with_name(journal_path.stem + ".ws.sqlite3")
        rebuild_path = journal_path.with_name(journal_path.stem + ".ws.rebuild.sqlite3")
        if rebuild_path.is_symlink() or (rebuild_path.exists() and not rebuild_path.is_file()):
            raise SpatialDataAuditRecoveryError("rebuild path is not a plain file")
        try:
            if rebuild_path.exists():
                rebuild_path.unlink()
        except OSError as exc:
            raise SpatialDataAuditRecoveryError(f"cannot clear stale rebuild file: {exc}") from exc
        max_pages = working_set.index_disk_bytes // _INDEX_PAGE_SIZE
        try:
            fresh = AuditHistoryIndex(
                rebuild_path,
                max_pages=max_pages,
                create=True,
                deadline=self._past_boot_deadline,
            )
        except AuditIndexError as exc:
            raise SpatialDataAuditRecoveryError(f"cannot stage rebuild index: {exc}") from exc
        watched.append(fresh)
        try:
            fresh.quick_check()
            expected = 0
            cursor: tuple[int, int] = (0, 0)
            while True:
                self._check_deadline()
                items, cursor, eof = journal.stream_record_bytes(
                    cursor,
                    limit_records=16,
                    limit_bytes=256 * 1024,
                    max_line_bytes=self._max_stream_line_bytes(),
                )
                for file_index, offset, length, raw in items:
                    self._check_deadline()
                    scan[0] += length
                    if scan[0] > working_set.max_boot_scan_bytes:
                        raise SpatialDataAuditRecoveryError("rebuild scan exceeded its byte budget")
                    try:
                        scan[0] += self._commit_historical_record(
                            fresh,
                            journal,
                            expected + 1,
                            file_index,
                            offset,
                            length,
                            raw,
                            label="rebuild",
                        )
                    except self._HistoricalInvalid as exc:
                        raise SpatialDataAuditRecoveryError(str(exc)) from exc
                    if scan[0] > working_set.max_boot_scan_bytes:
                        raise SpatialDataAuditRecoveryError("rebuild scan exceeded its byte budget")
                    expected += 1
                if eof:
                    break
            fresh.set_meta(
                self._checkpoint_meta(
                    expected,
                    end_offset=self._journal_end_offset(),
                    file_count=self._journal_file_count(),
                )
            )
        except BaseException:
            with contextlib.suppress(AuditIndexError):
                fresh.close()
            with contextlib.suppress(OSError):
                if rebuild_path.exists():
                    rebuild_path.unlink()
            raise
        old = self._history
        if old is not None:
            with contextlib.suppress(AuditIndexError):
                old.close()
        rebuilt: AuditHistoryIndex | None = None
        try:
            os.rename(rebuild_path, index_path)
            rebuilt = AuditHistoryIndex(
                index_path,
                max_pages=max_pages,
                create=False,
                deadline=self._past_boot_deadline,
            )
            watched.append(rebuilt)
            rebuilt.quick_check()
        except (OSError, AuditIndexError) as exc:
            if rebuilt is not None:
                with contextlib.suppress(AuditIndexError):
                    rebuilt.close()
            raise SpatialDataAuditRecoveryError(f"cannot activate rebuilt index: {exc}") from exc
        assert rebuilt is not None
        self._history = rebuilt
        self._sequence = expected

    def _catch_up_tail(self, journal: DurableJournal, scan: list[int]) -> None:
        """Index records appended after the checkpoint (bounded crash window)."""
        assert self._working_set is not None and self._history is not None
        working_set = self._working_set
        history = self._history
        try:
            end_offset = int(history.get_meta("journal_end_offset") or "0")
            files = int(history.get_meta("journal_files") or "0")
        except ValueError as exc:
            raise AuditIndexCorruption(f"invalid checkpoint offsets: {exc}") from exc
        live_files = self._journal_file_count()
        if files != live_files:
            raise AuditIndexCorruption("journal file set changed under the checkpoint")
        try:
            live_end = self._journal_end_offset()
        except SpatialDataAuditRecoveryError as exc:
            raise AuditIndexCorruption(f"cannot stat journal tail: {exc}") from exc
        if live_end < end_offset:
            raise AuditIndexCorruption("journal shrank under the checkpoint")
        if live_end == end_offset:
            self._sequence = history.checkpoint_seq()
            return
        cursor: tuple[int, int] = (live_files - 1, end_offset)
        scanned_records = 0
        scanned_bytes = 0
        expected = history.checkpoint_seq()
        while True:
            self._check_deadline()
            items, cursor, eof = journal.stream_record_bytes(
                cursor,
                limit_records=16,
                limit_bytes=256 * 1024,
                max_line_bytes=self._max_stream_line_bytes(),
            )
            for file_index, offset, length, raw in items:
                self._check_deadline()
                scanned_records += 1
                scanned_bytes += length
                scan[0] += length
                if (
                    scanned_records > working_set.max_tail_records
                    or scanned_bytes > working_set.max_tail_bytes
                    or scan[0] > working_set.max_boot_scan_bytes
                ):
                    raise AuditIndexCorruption("crash window exceeds the tail budget")
                try:
                    reread = self._commit_historical_record(
                        history,
                        journal,
                        expected + 1,
                        file_index,
                        offset,
                        length,
                        raw,
                        label="tail",
                    )
                except self._HistoricalInvalid as exc:
                    raise AuditIndexCorruption(str(exc)) from exc
                scanned_bytes += reread
                scan[0] += reread
                if (
                    scanned_records > working_set.max_tail_records
                    or scanned_bytes > working_set.max_tail_bytes
                    or scan[0] > working_set.max_boot_scan_bytes
                ):
                    raise AuditIndexCorruption("crash window exceeds the tail budget")
                expected += 1
            if eof:
                break
        self._sequence = expected

    def _load_unfinished(self, scan: list[int]) -> None:
        """Restore live unfinished sessions (bounded) from the validated index.

        Every re-read byte counts against the same shared boot scan budget —
        the unfinished tail cannot silently double the bounded total.
        """
        assert self._working_set is not None and self._history is not None
        history = self._history
        budget = self._working_set.max_boot_scan_bytes
        try:
            pending = history.unfinished(limit=self._working_set.active_session_cap + 1)
        except AuditIndexError as exc:
            raise self._index_failure(exc) from exc
        if len(pending) > self._working_set.active_session_cap:
            raise SpatialDataAuditRecoveryError("unfinished sessions exceed the active session cap")
        for session_id, _organization_id, _last_seq in pending:
            self._check_deadline()
            try:
                addresses = history.session_events(session_id, limit=_MAX_HISTORY_LOAD + 1)
            except AuditIndexError as exc:
                raise self._index_failure(exc) from exc
            if not addresses or len(addresses) > _MAX_HISTORY_LOAD:
                raise SpatialDataAuditRecoveryError("unfinished session history unbounded")
            rebuilt: tuple[SpatialDataAuditEventV1, ...] = ()
            for _seq, row_session, file_index, offset, length in addresses:
                if row_session != session_id:
                    raise SpatialDataAuditRecoveryError("unfinished session history diverged")
                scan[0] += length
                if scan[0] > budget:
                    raise SpatialDataAuditRecoveryError(
                        "unfinished load exceeded its byte budget"
                    )
                try:
                    raw = self._journal.read_record_at(
                        file_index, offset, length, max_bytes=self._max_stream_line_bytes()
                    )
                    record = _Record.model_validate(raw)
                except (JournalRecoveryError, JournalSealedError, ValueError, TypeError) as exc:
                    raise SpatialDataAuditRecoveryError(
                        f"cannot restore unfinished session: {exc}"
                    ) from exc
                event = record.event
                if event.event_digest != event.canonical_digest():
                    raise SpatialDataAuditRecoveryError("unfinished event unsealed")
                try:
                    size = self._validate_with(event, rebuilt)
                except SpatialDataDomainError as exc:
                    raise SpatialDataAuditRecoveryError(
                        f"retained unfinished history violates admission: {exc}"
                    ) from exc
                except (ValueError, TypeError) as exc:
                    raise SpatialDataAuditRecoveryError(
                        f"retained unfinished history invalid: {exc}"
                    ) from exc
                self._project(event, size)
                rebuilt = rebuilt + (event,)
            if not rebuilt or _TERMINAL_BY_ACTION.get(rebuilt[-1].action) is not None:
                raise SpatialDataAuditRecoveryError("indexed unfinished state diverged")
