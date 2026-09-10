"""Processing-controller mirrors and UDS client for one fenced inspector attempt.

This is deliberately a local authority adapter.  It imports immutable event
contracts but never imports ``ksi_core`` or exposes a Core route.  No URL,
header, object key, filename, Docker detail, parser, or artifact HTTP fetch is
representable in its launch DTO.
"""

from __future__ import annotations

import socket
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import Annotated, Any, Protocol, runtime_checkable

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    Digest,
    ExternalArtifactInspectionReportV1,
    ExternalArtifactInspectionRequestV1,
    ExternalInspectionMeasurementPayloadV1,
    ExternalValidationPolicyV1,
    PolicyStatus,
    SealedArtifactBindingV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from pydantic import ConfigDict, Field, StrictInt, StringConstraints, model_validator

from ksi_processing_controller.external_inspector_launcher import InspectorOperationProfileDecision
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedByteReaderPort,
    DeadlineBoundedByteSinkPort,
    DeadlineBoundedDiscardingSink,
    InspectorLaunchRequestV1,
    InspectorLaunchResultV1,
    InspectorOperation,
    LocalLeaseFenceV1,
    ProtocolDeadline,
    ProtocolLimitsV1,
    ProtocolViolation,
    SealedByteBindingV1,
    read_completed_output,
    read_launch_result,
    write_launch_request,
)
from ksi_processing_controller.external_inspector_staging import FileSystemOutputStaging

_BOUND_TEXT = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class CurrentAuthorityLost(RuntimeError):
    """The Core-fenced authority changed, disappeared, or failed closed during an attempt."""


class InspectionAssemblyIncomplete(RuntimeError):
    """A complete fenced payload cannot be formed without inventing an outcome."""


class _FrozenWorkerModel(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")


class ExternalInspectionPhaseV1(StrEnum):
    INSPECTION = "INSPECTION"
    DISPLAY = "DISPLAY"


class ExternalInspectionNextActionV1(StrEnum):
    INSPECT = "INSPECT"
    SANITIZE_DISPLAY = "SANITIZE_DISPLAY"


class ExternalArtifactInputV1(_FrozenWorkerModel):
    """Capability-stripped mirror of a Core input artifact projection."""

    entry_id: _BOUND_TEXT
    kind: ProcessingArtifactKind
    observed_sha256: Digest
    observed_size_bytes: StrictInt = Field(gt=0)
    content_type: _BOUND_TEXT


class ExternalInspectionCurrentInputV1(_FrozenWorkerModel):
    """Current immutable Core projection; it never carries a URL, header, or object key."""

    request: ExternalArtifactInspectionRequestV1
    policy: ExternalValidationPolicyV1
    artifacts: tuple[ExternalArtifactInputV1, ...] = Field(min_length=1, max_length=8)
    phase: ExternalInspectionPhaseV1
    next_action: ExternalInspectionNextActionV1
    accepted_report: ExternalArtifactInspectionReportV1 | None = None

    @model_validator(mode="after")
    def _current_projection_binds_request_policy_and_action(
        self,
    ) -> ExternalInspectionCurrentInputV1:
        policy = ExternalValidationPolicyV1.model_validate(self.policy.__dict__)
        request = ExternalArtifactInspectionRequestV1.model_validate(self.request.__dict__)
        if (
            policy.status is not PolicyStatus.ACTIVE
            or policy.policy_digest is None
            or policy.resource_envelope is None
            or policy.resource_envelope_digest is None
            or request.inspection_policy_id != policy.policy_id
            or request.inspection_policy_version != policy.version
            or request.inspection_policy_digest != policy.policy_digest
        ):
            raise ValueError("current input policy must exactly bind request")
        ids = [artifact.entry_id for artifact in self.artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("current input artifact entry ids must be unique")
        if (
            self.phase is ExternalInspectionPhaseV1.INSPECTION
            and self.next_action is not ExternalInspectionNextActionV1.INSPECT
        ) or (
            self.phase is ExternalInspectionPhaseV1.DISPLAY
            and self.next_action is not ExternalInspectionNextActionV1.SANITIZE_DISPLAY
        ):
            raise ValueError("current input phase and next action must be exact")
        return self


@dataclass(frozen=True, slots=True)
class ExternalInspectorLaunchContextV1:
    """The exact retained launch authority needed by a later private handoff.

    This carries immutable DTOs, the original absolute deadline, and its
    captured authority fence.  It deliberately exposes no source capability,
    local path, descriptor, or publication authority.
    """

    current: ExternalInspectionCurrentInputV1
    artifact: ExternalArtifactInputV1
    launch_request: InspectorLaunchRequestV1
    terminal: InspectorLaunchResultV1
    deadline: ProtocolDeadline
    authority_is_current: Callable[[], bool] = field(repr=False, compare=False)
    heartbeat_interval_millis: int = 1
    _retained_current: ExternalInspectionCurrentInputV1 = field(
        init=False, repr=False, compare=False
    )
    _retained_artifact: ExternalArtifactInputV1 = field(init=False, repr=False, compare=False)
    _retained_launch_request: InspectorLaunchRequestV1 = field(
        init=False, repr=False, compare=False
    )
    _retained_terminal: InspectorLaunchResultV1 = field(init=False, repr=False, compare=False)
    _retained_deadline: ProtocolDeadline = field(init=False, repr=False, compare=False)
    _retained_authority_is_current: Callable[[], bool] = field(
        init=False, repr=False, compare=False
    )
    _retained_heartbeat_interval_millis: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        current = ExternalInspectionCurrentInputV1.model_validate(self.current.__dict__)
        artifact = ExternalArtifactInputV1.model_validate(self.artifact.__dict__)
        launch_request = InspectorLaunchRequestV1.model_validate(self.launch_request.__dict__)
        terminal = InspectorLaunchResultV1.model_validate(self.terminal.__dict__)
        if not isinstance(self.deadline, ProtocolDeadline):
            raise TypeError("launch context requires the original protocol deadline")
        if not callable(self.authority_is_current):
            raise TypeError("launch context requires an authority guard")
        if type(self.heartbeat_interval_millis) is not int or self.heartbeat_interval_millis <= 0:
            raise ValueError("launch context heartbeat interval must be a positive integer")
        if (
            artifact not in current.artifacts
            or launch_request.request != current.request
            or launch_request.policy != current.policy
            or launch_request.sealed_byte_binding.artifact_id != artifact.entry_id
            or launch_request.sealed_byte_binding.observed_sha256 != artifact.observed_sha256
            or launch_request.sealed_byte_binding.observed_size_bytes
            != artifact.observed_size_bytes
        ):
            raise ValueError("launch context must bind one exact current artifact")
        terminal.validate_for(launch_request)
        if launch_request.operation is InspectorOperation.SANITIZE:
            report = current.accepted_report
            if (
                report is None
                or report.request_id != launch_request.request.request_id
                or report.subject != current.request.subject
                or report.subject_digest != current.request.subject.canonical_digest()
                or report.inspection_policy_digest != current.policy.policy_digest
                or report.inspector_build_digest != current.policy.parser_build_digest
                or report.report_digest is None
                or report != report.sealed()
            ):
                raise ValueError("SANITIZE launch context must bind the retained report evidence")
            measured = tuple(
                outcome
                for outcome in report.measurement_payload.outcomes
                if outcome.artifact_id == artifact.entry_id
                and outcome.observed_sha256 == artifact.observed_sha256
                and outcome.outcome is ArtifactOutcome.MEASURED
            )
            if (
                len(measured) != 1
                or measured[0].measurements is None
                or measured[0].measurements.band_count not in {3, 4}
                or measured[0].measurements.dtype != "uint8"
            ):
                raise ValueError("SANITIZE launch context must bind measured ORTHO evidence")
        object.__setattr__(self, "current", current)
        object.__setattr__(self, "artifact", artifact)
        object.__setattr__(self, "launch_request", launch_request)
        object.__setattr__(self, "terminal", terminal)
        object.__setattr__(self, "_retained_current", current)
        object.__setattr__(self, "_retained_artifact", artifact)
        object.__setattr__(self, "_retained_launch_request", launch_request)
        object.__setattr__(self, "_retained_terminal", terminal)
        object.__setattr__(self, "_retained_deadline", self.deadline)
        object.__setattr__(self, "_retained_authority_is_current", self.authority_is_current)
        object.__setattr__(
            self, "_retained_heartbeat_interval_millis", self.heartbeat_interval_millis
        )

    @property
    def retained_current(self) -> ExternalInspectionCurrentInputV1:
        return self._retained_current

    @property
    def retained_artifact(self) -> ExternalArtifactInputV1:
        return self._retained_artifact

    @property
    def retained_launch_request(self) -> InspectorLaunchRequestV1:
        return self._retained_launch_request

    @property
    def retained_terminal(self) -> InspectorLaunchResultV1:
        return self._retained_terminal

    @property
    def retained_deadline(self) -> ProtocolDeadline:
        return self._retained_deadline

    @property
    def retained_authority_is_current(self) -> Callable[[], bool]:
        return self._retained_authority_is_current

    @property
    def retained_heartbeat_interval_millis(self) -> int:
        return self._retained_heartbeat_interval_millis


def assemble_complete_measurement_payload(
    *,
    current: ExternalInspectionCurrentInputV1,
    fence: LocalLeaseFenceV1,
    inspect_one: Callable[[ExternalArtifactInputV1], ArtifactInspectionOutcomeV1],
    authority_is_current: Callable[[LocalLeaseFenceV1], bool],
    is_cancelled: Callable[[], bool] | None = None,
) -> ExternalInspectionMeasurementPayloadV1:
    """Return one fenced outcome for every sealed artifact, or no payload at all.

    Structural/profile rejection is artifact-local only when the scanner actually
    examined that exact sealed binding.  Cancellation, stale authority, or a
    runtime/pre-examination failure is request-level: this function raises
    instead of fabricating results for remaining artifacts.
    """

    _require_assembly_current(authority_is_current, fence, is_cancelled)
    outcomes: list[ArtifactInspectionOutcomeV1] = []
    for artifact in sorted(current.artifacts, key=lambda item: item.entry_id):
        _require_assembly_current(authority_is_current, fence, is_cancelled)
        try:
            outcome = inspect_one(artifact)
        except InspectionAssemblyIncomplete:
            raise
        except Exception as exc:
            raise InspectionAssemblyIncomplete("artifact examination is incomplete") from exc
        _require_assembly_current(authority_is_current, fence, is_cancelled)
        _require_outcome_binding(artifact, outcome)
        outcomes.append(_discard_measurement_for_kind_mismatch(artifact, outcome))
    _require_assembly_current(authority_is_current, fence, is_cancelled)
    policy_digest = current.policy.policy_digest
    if policy_digest is None:
        raise InspectionAssemblyIncomplete("current policy is not sealed")
    return ExternalInspectionMeasurementPayloadV1(
        subject_digest=current.request.subject.canonical_digest(),
        sealed_manifest_digest=current.request.subject.manifest_digest,
        inspection_policy_digest=policy_digest,
        inspector_build_digest=current.policy.parser_build_digest,
        artifact_bindings=tuple(
            SealedArtifactBindingV1(
                artifact_id=artifact.entry_id,
                observed_sha256=artifact.observed_sha256,
            )
            for artifact in current.artifacts
        ),
        outcomes=tuple(outcomes),
    )


def _require_assembly_current(
    authority_is_current: Callable[[LocalLeaseFenceV1], bool],
    fence: LocalLeaseFenceV1,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    if is_cancelled is not None and is_cancelled():
        raise InspectionAssemblyIncomplete("inspection request was cancelled")
    try:
        current = authority_is_current(fence)
    except Exception as exc:
        raise InspectionAssemblyIncomplete("inspection authority is unavailable") from exc
    if current is not True:
        raise InspectionAssemblyIncomplete("inspection authority is no longer current")


def _require_outcome_binding(
    artifact: ExternalArtifactInputV1,
    outcome: ArtifactInspectionOutcomeV1,
) -> None:
    if (
        outcome.artifact_id != artifact.entry_id
        or outcome.observed_sha256 != artifact.observed_sha256
    ):
        raise InspectionAssemblyIncomplete("inspection outcome does not bind the examined artifact")


def _discard_measurement_for_kind_mismatch(
    artifact: ExternalArtifactInputV1,
    outcome: ArtifactInspectionOutcomeV1,
) -> ArtifactInspectionOutcomeV1:
    """The server kind is authoritative for the report, never an entrypoint hint."""

    measurements = outcome.measurements
    if outcome.outcome is not ArtifactOutcome.MEASURED or measurements is None:
        return outcome
    expected = (
        artifact.kind is ProcessingArtifactKind.ORTHO
        and measurements.band_count in {3, 4}
        and measurements.dtype == "uint8"
    ) or (
        artifact.kind is ProcessingArtifactKind.DSM
        and measurements.band_count == 1
        and measurements.dtype in {"float32", "float64"}
    )
    if expected:
        return outcome
    return ArtifactInspectionOutcomeV1(
        artifact_id=artifact.entry_id,
        observed_sha256=artifact.observed_sha256,
        outcome=ArtifactOutcome.REJECTED,
        reason="UNSUPPORTED_RASTER",
    )


def _discard_launch_measurement_for_kind_mismatch(
    artifact: ExternalArtifactInputV1,
    result: InspectorLaunchResultV1,
) -> InspectorLaunchResultV1:
    """Keep a single-artifact launch on the same declared-kind boundary as reports."""

    if not isinstance(result.outcome, ArtifactInspectionOutcomeV1):
        return result
    normalized = _discard_measurement_for_kind_mismatch(artifact, result.outcome)
    if normalized == result.outcome:
        return result
    if result.canonical_input_digest is None or result.inspector_build_digest is None:
        raise CurrentAuthorityLost("completed inspection result lacks exact bindings")
    return InspectorLaunchResultV1.completed_inspection(
        result.attempt_nonce,
        result.canonical_input_digest,
        result.inspector_build_digest,
        normalized,
    )


class WorkerAuthorityLimitsV1(_FrozenWorkerModel):
    """Explicit finite authority cadence/wait limits; this class provides no values."""

    heartbeat_interval_millis: StrictInt = Field(gt=0)
    max_authority_wait_millis: StrictInt = Field(gt=0)


class ExternalInspectionAuthorityPort(Protocol):
    def current_input(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        *,
        deadline_monotonic: float,
    ) -> ExternalInspectionCurrentInputV1 | None: ...

    def heartbeat(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        *,
        deadline_monotonic: float,
    ) -> bool: ...


class ExternalArtifactByteSourcePort(ABC):
    """Supply only deadline-bounded bytes for one already-authorized sealed projection."""

    @abstractmethod
    def open_bound_bytes(
        self,
        artifact: ExternalArtifactInputV1,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> DeadlineBoundedByteReaderPort: ...


class InspectorWorkerOperationProfilePort(Protocol):
    """Required trusted parser-profile gate; MIME is only one input and never a default."""

    def allows(
        self,
        *,
        parser_build_digest: str,
        grammar_digest: str,
        artifact_kind: ProcessingArtifactKind,
        content_type: str,
        operation: InspectorOperation,
        deadline_monotonic: float,
    ) -> InspectorOperationProfileDecision: ...


class ExternalInspectorLaunchPort(Protocol):
    def execute(
        self,
        *,
        request: InspectorLaunchRequestV1,
        source: DeadlineBoundedByteReaderPort,
        artifact_kind: ProcessingArtifactKind,
        content_type: str,
        deadline_monotonic: float,
        authority_is_current: Callable[[], bool],
    ) -> InspectorLaunchResultV1: ...


@runtime_checkable
class RetainedSanitizedCandidateAbortPort(Protocol):
    """A SANITIZE launcher retains an exact private-candidate retirement capability."""

    def abort_private_candidate(self, request: InspectorLaunchRequestV1) -> None: ...


@runtime_checkable
class PrivateSanitizedCandidateReaderPort(DeadlineBoundedByteReaderPort, Protocol):
    """Opaque bounded bytes for one retained, exact SANITIZE candidate."""


class PrivateSanitizedCandidateOpenerPort(Protocol):
    """Private byte binding only; this neither authorizes nor creates publication."""

    def open_private_candidate(
        self,
        request: InspectorLaunchRequestV1,
        terminal: InspectorLaunchResultV1,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int | None,
    ) -> PrivateSanitizedCandidateReaderPort: ...


class SanitizedOutputSinkPort(Protocol):
    """Attempt-scoped private candidate factory; it has no publication operation."""

    def begin(
        self,
        request: InspectorLaunchRequestV1,
        *,
        maximum_bytes: int,
        deadline_monotonic: float,
    ) -> SanitizedOutputTransactionPort: ...


class SanitizedOutputTransactionPort(DeadlineBoundedByteSinkPort, Protocol):
    """A raw derivative remains private until a later Task 7 handoff path exists."""

    def write(self, chunk: bytes, *, deadline_monotonic: float) -> None: ...

    def finish(
        self,
        terminal: InspectorLaunchResultV1,
        *,
        deadline_monotonic: float,
    ) -> None: ...

    def abort(self) -> None: ...


class FileSystemSanitizedOutputSink:
    """Private anonymous candidates keyed by one sealed local launch attempt.

    This is intentionally not a publication interface: it exposes no path,
    descriptor, display reference, or receipt.  Its sole Task 7C reader is an
    opaque, exact private byte binding; the caller still owns later Core
    authority validation and any publication decision.
    """

    def __init__(self, *, private_root: Path) -> None:
        self._staging = FileSystemOutputStaging(private_root=private_root)
        self._lock = threading.RLock()
        self._active: dict[tuple[str, str], _PrivateSanitizedOutputTransaction] = {}
        self._sealed: dict[tuple[str, str], _PrivateSanitizedOutputTransaction] = {}
        self._uncertain: dict[tuple[str, str], _PrivateSanitizedOutputTransaction] = {}

    def begin(
        self,
        request: InspectorLaunchRequestV1,
        *,
        maximum_bytes: int,
        deadline_monotonic: float,
    ) -> SanitizedOutputTransactionPort:
        key = _private_candidate_key(request)
        with self._lock:
            if self._uncertain:
                raise CurrentAuthorityLost("private SANITIZE cleanup uncertainty closes admission")
            if key in self._active or key in self._sealed:
                raise CurrentAuthorityLost("private SANITIZE candidate already exists for launch")
            staged = self._staging.begin(
                maximum_bytes=maximum_bytes,
                deadline_monotonic=deadline_monotonic,
            )
            transaction = _PrivateSanitizedOutputTransaction(
                owner=self,
                key=key,
                staged=staged,
            )
            self._active[key] = transaction
            return transaction

    def open_private_candidate(
        self,
        request: InspectorLaunchRequestV1,
        terminal: InspectorLaunchResultV1,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int | None,
    ) -> PrivateSanitizedCandidateReaderPort:
        """Open an exact, closed, anonymous candidate without publishing it.

        ``deadline`` and ``wait_is_current`` are captured by the returned
        capability.  Later reads can only add a stricter guard or shorten the
        captured absolute deadline.
        """

        request, terminal = _require_private_candidate_open_arguments(
            request=request,
            terminal=terminal,
            deadline=deadline,
            wait_is_current=wait_is_current,
        )
        key = _private_candidate_key(request)
        with self._lock:
            if self._uncertain:
                raise CurrentAuthorityLost("private SANITIZE cleanup uncertainty closes admission")
            transaction = self._sealed.get(key)
        if transaction is None:
            raise CurrentAuthorityLost("private SANITIZE candidate is not sealed for exact launch")
        return transaction.open_private_reader(
            request=request,
            terminal=terminal,
            deadline=deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )

    def abort_attempt(self, request: InspectorLaunchRequestV1) -> None:
        """Discard exactly one private candidate; no path or broad cleanup exists."""

        key = _private_candidate_key(request)
        with self._lock:
            transaction = self._active.get(key) or self._sealed.get(key) or self._uncertain.get(key)
        if transaction is None:
            return
        transaction.abort()

    def abort_all(self) -> None:
        """Shutdown-only bounded cleanup of candidates registered by this sink instance."""

        with self._lock:
            transactions = tuple(self._active.values()) + tuple(self._sealed.values())
        failures: list[Exception] = []
        for transaction in transactions:
            try:
                transaction.abort()
            except Exception as exc:  # preserve all exact candidates before surfacing failure
                failures.append(exc)
        if failures:
            raise CurrentAuthorityLost("private SANITIZE candidate cleanup failed") from failures[0]
        with self._lock:
            if self._uncertain:
                raise CurrentAuthorityLost("private SANITIZE cleanup uncertainty remains")

    def _finish(
        self,
        key: tuple[str, str],
        transaction: _PrivateSanitizedOutputTransaction,
    ) -> None:
        with self._lock:
            if self._active.get(key) is not transaction:
                raise CurrentAuthorityLost("private SANITIZE candidate ownership changed")
            del self._active[key]
            self._sealed[key] = transaction

    def _abort(
        self,
        key: tuple[str, str],
        transaction: _PrivateSanitizedOutputTransaction,
    ) -> None:
        with self._lock:
            if self._active.get(key) is transaction:
                del self._active[key]
            if self._sealed.get(key) is transaction:
                del self._sealed[key]

    def _mark_cleanup_uncertain(
        self,
        key: tuple[str, str],
        transaction: _PrivateSanitizedOutputTransaction,
    ) -> None:
        """Retain the exact uncertain owner; a descriptor number is never retried."""

        with self._lock:
            if self._active.get(key) is transaction:
                del self._active[key]
            if self._sealed.get(key) is transaction:
                del self._sealed[key]
            existing = self._uncertain.get(key)
            if existing is not None and existing is not transaction:
                raise CurrentAuthorityLost("private SANITIZE cleanup ownership is uncertain")
            self._uncertain[key] = transaction


class _PrivateSanitizedOutputTransaction:
    """One anonymous O_TMPFILE candidate with a closed write/finish/abort lifetime."""

    def __init__(
        self,
        *,
        owner: FileSystemSanitizedOutputSink,
        key: tuple[str, str],
        staged: Any,
    ) -> None:
        self._owner = owner
        self._key = key
        self._staged = staged
        self._finished = False
        self._aborted = False
        self._cleanup_uncertain = False
        self._terminal: InspectorLaunchResultV1 | None = None
        self._lifecycle_lock = threading.RLock()

    def write(self, chunk: bytes, *, deadline_monotonic: float) -> None:
        self.write_chunk(
            chunk,
            deadline=ProtocolDeadline.at_expires_at(deadline_monotonic),
            wait_is_current=None,
            heartbeat_interval_millis=None,
        )

    def write_chunk(
        self,
        chunk: bytes,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> None:
        with self._lifecycle_lock:
            if self._finished or self._aborted or self._cleanup_uncertain:
                raise CurrentAuthorityLost("private SANITIZE candidate is no longer writable")
            writer = getattr(self._staged, "write_chunk", None)
            if not callable(writer):
                raise CurrentAuthorityLost("private SANITIZE staging lacks bounded file I/O")
            writer(
                chunk,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )

    def finish(
        self,
        terminal: InspectorLaunchResultV1,
        *,
        deadline_monotonic: float,
    ) -> None:
        with self._lifecycle_lock:
            if self._finished or self._aborted or self._cleanup_uncertain:
                raise CurrentAuthorityLost("private SANITIZE candidate cannot be sealed twice")
            if (
                terminal.result != "COMPLETED"
                or terminal.outcome != "SANITIZED"
                or terminal.output_size_bytes is None
                or terminal.output_sha256 is None
            ):
                raise CurrentAuthorityLost("SANITIZE terminal cannot bind a private candidate")
            self._staged.finish_bounded(
                deadline=ProtocolDeadline.at_expires_at(deadline_monotonic),
                wait_is_current=None,
                heartbeat_interval_millis=None,
            )
            if (
                self._staged.size_bytes != terminal.output_size_bytes
                or self._staged.sha256 != terminal.output_sha256
            ):
                raise CurrentAuthorityLost(
                    "private SANITIZE candidate differs from terminal binding"
                )
            self._owner._finish(self._key, self)
            self._terminal = terminal
            self._finished = True

    def open_private_reader(
        self,
        *,
        request: InspectorLaunchRequestV1,
        terminal: InspectorLaunchResultV1,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int | None,
    ) -> PrivateSanitizedCandidateReaderPort:
        """Create a closable reader while this transaction remains sink-owned."""

        with self._lifecycle_lock:
            if (
                not self._finished
                or self._aborted
                or self._cleanup_uncertain
                or self._key != _private_candidate_key(request)
            ):
                raise CurrentAuthorityLost("private SANITIZE candidate terminal is not exact")
            if self._terminal is None:
                raise CurrentAuthorityLost("private SANITIZE candidate terminal is not retained")
            retained_terminal = _validated_sanitized_terminal(self._terminal, retained=True)
            if retained_terminal != terminal:
                raise CurrentAuthorityLost("private SANITIZE candidate terminal is not exact")
            _require_private_candidate_current(deadline, wait_is_current)
            opener = getattr(self._staged, "open_sealed_reader", None)
            if not callable(opener):
                raise CurrentAuthorityLost("private SANITIZE staging lacks bounded private reads")
            try:
                handle = opener()
            except ProtocolViolation:
                raise
            except Exception as exc:
                raise CurrentAuthorityLost(
                    "private SANITIZE candidate cannot open sealed reader"
                ) from exc
            read_at = getattr(handle, "read_at", None)
            close = getattr(handle, "close", None)
            if not callable(read_at) or not callable(close):
                if callable(close):
                    with suppress(Exception):
                        close()
                raise CurrentAuthorityLost("private SANITIZE reader lacks bounded explicit reads")
            return _PrivateSanitizedCandidateReader(
                transaction=self,
                handle=handle,
                original_deadline=deadline,
                original_wait_is_current=wait_is_current,
                original_heartbeat_interval_millis=heartbeat_interval_millis,
            )

    def read_private_candidate(
        self,
        *,
        handle: Any,
        offset: int,
        maximum_bytes: int,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int | None,
    ) -> bytes:
        """Serialize explicit-offset reads with the sole candidate retirement owner."""

        with self._lifecycle_lock:
            if not self._finished or self._aborted or self._cleanup_uncertain:
                raise CurrentAuthorityLost("private SANITIZE candidate was retired")
            _require_private_candidate_current(deadline, wait_is_current)
            try:
                payload = handle.read_at(
                    offset=offset,
                    maximum_bytes=maximum_bytes,
                    deadline=deadline,
                    wait_is_current=wait_is_current,
                    heartbeat_interval_millis=heartbeat_interval_millis,
                )
            except ProtocolViolation:
                raise
            except Exception as exc:
                raise CurrentAuthorityLost(
                    "private SANITIZE candidate bounded read failed"
                ) from exc
            _require_private_candidate_current(deadline, wait_is_current)
            if not isinstance(payload, bytes) or len(payload) > maximum_bytes:
                raise CurrentAuthorityLost(
                    "private SANITIZE candidate exceeded explicit read bound"
                )
            return payload

    def abort(self) -> None:
        with self._lifecycle_lock:
            if self._aborted:
                return
            if self._cleanup_uncertain:
                raise CurrentAuthorityLost("private SANITIZE cleanup remains uncertain")
            try:
                self._staged.abort()
            except Exception:
                self._cleanup_uncertain = True
                self._owner._mark_cleanup_uncertain(self._key, self)
                raise
            self._owner._abort(self._key, self)
            self._aborted = True


class _PrivateSanitizedCandidateReader:
    """One retryable cursor over a sink-owned anonymous candidate.

    The only resource this object owns is its private staged-reader capability.
    Its ``close`` cannot retire the candidate; the sink remains the only owner
    allowed to abort it after upload/grant/seal retries.
    """

    def __init__(
        self,
        *,
        transaction: _PrivateSanitizedOutputTransaction,
        handle: Any,
        original_deadline: ProtocolDeadline,
        original_wait_is_current: Callable[[], bool],
        original_heartbeat_interval_millis: int | None,
    ) -> None:
        self._transaction = transaction
        self._handle = handle
        self._deadline = original_deadline
        self._wait_is_current = original_wait_is_current
        self._heartbeat_interval_millis = original_heartbeat_interval_millis
        self._offset = 0
        self._closed = False
        self._lock = threading.RLock()

    def read_chunk(
        self,
        maximum_bytes: int,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> bytes:
        if type(maximum_bytes) is not int or maximum_bytes <= 0:
            raise CurrentAuthorityLost("private SANITIZE candidate read bound is invalid")
        if not isinstance(deadline, ProtocolDeadline):
            raise CurrentAuthorityLost("private SANITIZE candidate deadline is required")
        with self._lock:
            if self._closed:
                raise CurrentAuthorityLost("private SANITIZE candidate reader is closed")
            deadline.remaining()
            self._deadline.cap_expires_at(deadline.expires_at)
            combined_current = _combined_private_candidate_current(
                self._wait_is_current,
                wait_is_current,
            )
            _require_private_candidate_current(self._deadline, combined_current)
            payload = self._transaction.read_private_candidate(
                handle=self._handle,
                offset=self._offset,
                maximum_bytes=maximum_bytes,
                deadline=self._deadline,
                wait_is_current=combined_current,
                heartbeat_interval_millis=_stricter_heartbeat_interval(
                    self._heartbeat_interval_millis,
                    heartbeat_interval_millis,
                ),
            )
            _require_private_candidate_current(self._deadline, combined_current)
            self._offset += len(payload)
            return payload

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            close = getattr(self._handle, "close", None)
            if not callable(close):
                raise CurrentAuthorityLost("private SANITIZE reader close is unavailable")
            try:
                close()
            except Exception as exc:
                raise CurrentAuthorityLost("private SANITIZE reader close failed") from exc


def _require_private_candidate_open_arguments(
    *,
    request: InspectorLaunchRequestV1,
    terminal: InspectorLaunchResultV1,
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool],
) -> tuple[InspectorLaunchRequestV1, InspectorLaunchResultV1]:
    try:
        request = InspectorLaunchRequestV1.model_validate(request.__dict__)
    except (AttributeError, TypeError, ValueError) as exc:
        raise CurrentAuthorityLost("private SANITIZE launch is not canonically sealed") from exc
    terminal = _validated_sanitized_terminal(terminal)
    if request.operation is not InspectorOperation.SANITIZE:
        raise CurrentAuthorityLost("private candidate requires a SANITIZE launch")
    if not isinstance(deadline, ProtocolDeadline) or not callable(wait_is_current):
        raise CurrentAuthorityLost("private candidate requires a bounded current authority guard")
    try:
        terminal.validate_for(request)
    except ProtocolViolation as exc:
        raise CurrentAuthorityLost("private SANITIZE terminal does not bind launch") from exc
    if (
        terminal.result != "COMPLETED"
        or terminal.outcome != "SANITIZED"
        or terminal.output_size_bytes is None
        or terminal.output_sha256 is None
    ):
        raise CurrentAuthorityLost("private SANITIZE terminal is not a completed candidate")
    return request, terminal


def _validated_sanitized_terminal(
    terminal: InspectorLaunchResultV1,
    *,
    retained: bool = False,
) -> InspectorLaunchResultV1:
    label = "retained terminal" if retained else "terminal"
    try:
        terminal = InspectorLaunchResultV1.model_validate(terminal.__dict__)
    except (AttributeError, TypeError, ValueError) as exc:
        raise CurrentAuthorityLost(f"private SANITIZE {label} is not strictly valid") from exc
    if (
        terminal.result != "COMPLETED"
        or terminal.outcome != "SANITIZED"
        or terminal.output_size_bytes is None
        or terminal.output_sha256 is None
    ):
        raise CurrentAuthorityLost(f"private SANITIZE {label} is not a completed candidate")
    return terminal


def _require_private_candidate_current(
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool],
) -> None:
    deadline.remaining()
    try:
        current = wait_is_current()
    except Exception as exc:
        raise CurrentAuthorityLost("private SANITIZE authority is unavailable") from exc
    if current is not True:
        raise CurrentAuthorityLost("private SANITIZE authority is no longer current")


def _combined_private_candidate_current(
    original: Callable[[], bool],
    later: Callable[[], bool] | None,
) -> Callable[[], bool]:
    """Never throw from the helper callback; false forces bounded helper reaping."""

    def current() -> bool:
        try:
            if original() is not True:
                return False
            return later is None or later() is True
        except Exception:
            return False

    return current


def _stricter_heartbeat_interval(
    original: int | None,
    later: int | None,
) -> int | None:
    if original is None:
        return later
    if later is None:
        return original
    if type(later) is not int or later <= 0:
        raise CurrentAuthorityLost("private SANITIZE heartbeat interval is invalid")
    if type(original) is not int or original <= 0:
        raise CurrentAuthorityLost("private SANITIZE heartbeat interval is invalid")
    return min(original, later)


def _private_candidate_key(request: InspectorLaunchRequestV1) -> tuple[str, str]:
    return request.attempt_nonce, request.canonical_input_digest


class InspectorUdsConnectorPort(Protocol):
    """One owned connection wait bound to the caller's authority and deadline."""

    def __call__(
        self,
        deadline_monotonic: float,
        *,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> socket.socket: ...


class ExternalInspectorUdsClient:
    """A supplied connector owns the provisioned UDS path; this class creates no listener."""

    def __init__(
        self,
        *,
        connect: InspectorUdsConnectorPort,
        protocol_limits: ProtocolLimitsV1,
        sanitized_output_sink: SanitizedOutputSinkPort,
        heartbeat_interval_millis: int,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(heartbeat_interval_millis) is not int or heartbeat_interval_millis <= 0:
            raise ValueError("heartbeat_interval_millis must be a positive integer")
        self._connect = connect
        self._protocol_limits = protocol_limits
        self._sanitized_output_sink = sanitized_output_sink
        self._heartbeat_interval_millis = heartbeat_interval_millis
        self._monotonic = monotonic

    def execute(
        self,
        *,
        request: InspectorLaunchRequestV1,
        source: DeadlineBoundedByteReaderPort,
        artifact_kind: ProcessingArtifactKind,
        content_type: str,
        deadline_monotonic: float,
        authority_is_current: Callable[[], bool],
    ) -> InspectorLaunchResultV1:
        del artifact_kind, content_type
        if not authority_is_current():
            raise CurrentAuthorityLost("authority lost before UDS launch")
        if self._monotonic() >= deadline_monotonic:
            raise CurrentAuthorityLost("authority deadline elapsed before UDS launch")
        connection = self._connect(
            deadline_monotonic,
            wait_is_current=authority_is_current,
            heartbeat_interval_millis=self._heartbeat_interval_millis,
        )
        transaction: SanitizedOutputTransactionPort | None = None
        try:
            deadline = ProtocolDeadline.at_expires_at(deadline_monotonic, self._monotonic)
            deadline.remaining()
            write_launch_request(
                connection,
                request,
                source,
                self._protocol_limits,
                deadline=deadline,
                wait_is_current=authority_is_current,
                heartbeat_interval_millis=self._heartbeat_interval_millis,
            )
            accepted = read_launch_result(
                connection,
                self._protocol_limits,
                deadline=deadline,
                wait_is_current=authority_is_current,
                heartbeat_interval_millis=self._heartbeat_interval_millis,
            )
            accepted.validate_for(request)
            if accepted.result != "ACCEPTED":
                raise CurrentAuthorityLost("launcher did not acknowledge current fenced input")
            terminal = read_launch_result(
                connection,
                self._protocol_limits,
                deadline=deadline,
                wait_is_current=authority_is_current,
                heartbeat_interval_millis=self._heartbeat_interval_millis,
            )
            terminal.validate_for(request)
            if terminal.result != "COMPLETED":
                raise CurrentAuthorityLost("launcher returned a non-completed terminal frame")
            if terminal.output_size_bytes:
                transaction = self._begin_private_output(request, deadline)
            output_sink: DeadlineBoundedByteSinkPort = (
                transaction if transaction is not None else DeadlineBoundedDiscardingSink()
            )
            read_completed_output(
                connection,
                terminal,
                self._protocol_limits,
                output_sink,
                deadline=deadline,
                wait_is_current=authority_is_current,
                heartbeat_interval_millis=self._heartbeat_interval_millis,
            )
            if not authority_is_current():
                raise CurrentAuthorityLost("authority lost after UDS terminal frame")
            if transaction is not None:
                transaction.finish(terminal, deadline_monotonic=deadline.expires_at)
                if not authority_is_current():
                    raise CurrentAuthorityLost("authority lost after private candidate seal")
            deadline.remaining()
            transaction = None
            return terminal
        except (OSError, ProtocolViolation) as exc:
            with suppress(BaseException):
                self._abort_private_output(transaction)
            raise CurrentAuthorityLost("UDS launch failed closed") from exc
        except BaseException:
            # A candidate is still owned here until a terminal is returned to
            # the caller.  Retire it for cancellation and interruption too,
            # without replacing the originating failure if cleanup itself fails.
            with suppress(BaseException):
                self._abort_private_output(transaction)
            raise
        finally:
            with suppress(OSError):
                connection.close()

    def abort_private_candidate(self, request: InspectorLaunchRequestV1) -> None:
        """Retire only this sealed attempt when its owning worker cannot return it."""

        abort_attempt = getattr(self._sanitized_output_sink, "abort_attempt", None)
        if not callable(abort_attempt):
            raise CurrentAuthorityLost("private SANITIZE retirement capability is unavailable")
        try:
            abort_attempt(request)
        except CurrentAuthorityLost:
            raise
        except Exception as exc:
            raise CurrentAuthorityLost("private SANITIZE candidate cleanup failed") from exc

    def _begin_private_output(
        self,
        request: InspectorLaunchRequestV1,
        deadline: ProtocolDeadline,
    ) -> SanitizedOutputTransactionPort:
        envelope = request.policy.resource_envelope
        if envelope is None:
            raise CurrentAuthorityLost("current SANITIZE policy has no finite output cap")
        try:
            return self._sanitized_output_sink.begin(
                request,
                maximum_bytes=min(
                    self._protocol_limits.max_output_bytes,
                    envelope.max_output_bytes,
                ),
                deadline_monotonic=deadline.expires_at,
            )
        except Exception as exc:
            raise CurrentAuthorityLost("private SANITIZE candidate is unavailable") from exc

    @staticmethod
    def _abort_private_output(transaction: SanitizedOutputTransactionPort | None) -> None:
        if transaction is None:
            return
        try:
            transaction.abort()
        except Exception as exc:
            raise CurrentAuthorityLost("private SANITIZE candidate cleanup failed") from exc


class ExternalArtifactInspectionWorker:
    """Build exactly one local launch from a fresh fenced Core projection."""

    def __init__(
        self,
        *,
        authority: ExternalInspectionAuthorityPort,
        byte_source: ExternalArtifactByteSourcePort,
        launcher: ExternalInspectorLaunchPort,
        operation_profile: InspectorWorkerOperationProfilePort,
        limits: WorkerAuthorityLimitsV1,
        attempt_nonce_factory: Callable[[], str],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._authority = authority
        if not isinstance(byte_source, ExternalArtifactByteSourcePort):
            raise TypeError("byte_source must own deadline-bounded source opening")
        self._byte_source = byte_source
        self._launcher = launcher
        self._operation_profile = operation_profile
        self._limits = limits
        self._attempt_nonce_factory = attempt_nonce_factory
        self._monotonic = monotonic

    def launch_artifact(
        self, request_id: str, fence: LocalLeaseFenceV1, artifact_id: str
    ) -> InspectorLaunchResultV1:
        """Preserve the terminal-only facade for existing callers."""
        return self.launch_artifact_context(request_id, fence, artifact_id).terminal

    def launch_artifact_context(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        artifact_id: str,
        *,
        deadline_monotonic: float | None = None,
        authority_is_current: Callable[[], bool] | None = None,
    ) -> ExternalInspectorLaunchContextV1:
        """Return one validated launch together with its original authority boundary."""
        deadline = self._deadline(deadline_monotonic)

        def caller_is_current() -> bool:
            if authority_is_current is None:
                return True
            try:
                return authority_is_current() is True
            except Exception:
                return False

        def require_caller_current() -> None:
            if not caller_is_current():
                raise CurrentAuthorityLost("caller authority is no longer current")

        require_caller_current()
        current = self._current_input(request_id, fence, deadline)
        require_caller_current()
        artifact = self._artifact(current, artifact_id)
        operation = self._operation_for(current, artifact)
        if operation is InspectorOperation.SANITIZE and not isinstance(
            self._launcher, RetainedSanitizedCandidateAbortPort
        ):
            raise CurrentAuthorityLost("SANITIZE launcher cannot retire its private candidate")
        self._require_profile(current, artifact, operation, deadline)
        require_caller_current()
        self._heartbeat(request_id, fence, deadline)
        require_caller_current()
        launch_request: InspectorLaunchRequestV1 | None = None

        def launch_authority_is_current() -> bool:
            if not caller_is_current():
                return False
            try:
                self._heartbeat(request_id, fence, deadline)
                # A heartbeat alone only proves the lease is live.  The
                # private candidate also remains bound to the immutable
                # report, sealed bytes, policy, and build projection that
                # authorized this launch.
                latest = self._current_input(request_id, fence, deadline)
            except CurrentAuthorityLost:
                return False
            return caller_is_current() and latest == current

        source = self._open_source(artifact, deadline, launch_authority_is_current)
        try:
            launch_request = InspectorLaunchRequestV1.seal(
                operation=operation,
                request=current.request,
                fence=fence,
                subject=current.request.subject,
                sealed_byte_binding=SealedByteBindingV1(
                    artifact_id=artifact.entry_id,
                    observed_sha256=artifact.observed_sha256,
                    observed_size_bytes=artifact.observed_size_bytes,
                ),
                policy=current.policy,
                attempt_nonce=self._attempt_nonce_factory(),
            )

            result = self._launcher.execute(
                request=launch_request,
                source=source,
                artifact_kind=artifact.kind,
                content_type=artifact.content_type,
                deadline_monotonic=deadline,
                authority_is_current=launch_authority_is_current,
            )
            require_caller_current()
            self._require_authority_deadline(deadline)
            result.validate_for(launch_request)
            result = _discard_launch_measurement_for_kind_mismatch(artifact, result)
            result.validate_for(launch_request)
            self._heartbeat(request_id, fence, deadline)
            require_caller_current()
            latest = self._current_input(request_id, fence, deadline)
            if not caller_is_current() or latest != current:
                raise CurrentAuthorityLost(
                    "current authority changed before terminal result return"
                )
            return ExternalInspectorLaunchContextV1(
                current=current,
                artifact=artifact,
                launch_request=launch_request,
                terminal=result,
                deadline=ProtocolDeadline.at_expires_at(deadline, self._monotonic),
                authority_is_current=launch_authority_is_current,
                heartbeat_interval_millis=self._limits.heartbeat_interval_millis,
            )
        except CurrentAuthorityLost:
            with suppress(BaseException):
                self._abort_private_candidate(launch_request)
            raise
        except Exception as exc:
            with suppress(BaseException):
                self._abort_private_candidate(launch_request)
            raise CurrentAuthorityLost("worker launch failed closed") from exc
        except BaseException:
            with suppress(BaseException):
                self._abort_private_candidate(launch_request)
            raise
        finally:
            with suppress(BaseException):
                source.close()

    def _deadline(self, caller_deadline_monotonic: float | None) -> float:
        now = self._monotonic()
        if not isfinite(now):
            raise CurrentAuthorityLost("monotonic authority clock is invalid")
        local_deadline = now + self._limits.max_authority_wait_millis / 1_000
        if caller_deadline_monotonic is None:
            return local_deadline
        if (
            isinstance(caller_deadline_monotonic, bool)
            or not isinstance(caller_deadline_monotonic, (int, float))
            or not isfinite(caller_deadline_monotonic)
            or caller_deadline_monotonic <= now
        ):
            raise CurrentAuthorityLost("caller authority deadline is invalid")
        return min(local_deadline, caller_deadline_monotonic)

    def _current_input(
        self, request_id: str, fence: LocalLeaseFenceV1, deadline_monotonic: float
    ) -> ExternalInspectionCurrentInputV1:
        self._require_authority_deadline(deadline_monotonic)
        try:
            current = self._authority.current_input(
                request_id, fence, deadline_monotonic=deadline_monotonic
            )
        except Exception as exc:
            raise CurrentAuthorityLost("current authority input unavailable") from exc
        self._require_authority_deadline(deadline_monotonic)
        if current is None or current.request.request_id != request_id:
            raise CurrentAuthorityLost("current authority input is unavailable")
        return current

    def _heartbeat(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        deadline_monotonic: float,
    ) -> None:
        self._require_authority_deadline(deadline_monotonic)
        try:
            current = self._authority.heartbeat(
                request_id, fence, deadline_monotonic=deadline_monotonic
            )
        except Exception as exc:
            raise CurrentAuthorityLost("authority heartbeat unavailable") from exc
        self._require_authority_deadline(deadline_monotonic)
        if current is not True:
            raise CurrentAuthorityLost("authority lost while waiting for launcher")

    def _require_authority_deadline(self, deadline_monotonic: float) -> None:
        now = self._monotonic()
        if not isfinite(now) or now >= deadline_monotonic:
            raise CurrentAuthorityLost("authority wait deadline elapsed")

    def _abort_private_candidate(self, request: InspectorLaunchRequestV1 | None) -> None:
        if request is None or request.operation is not InspectorOperation.SANITIZE:
            return
        launcher = self._launcher
        if not isinstance(launcher, RetainedSanitizedCandidateAbortPort):
            raise CurrentAuthorityLost("private SANITIZE retirement capability is unavailable")
        launcher.abort_private_candidate(request)

    @staticmethod
    def _artifact(
        current: ExternalInspectionCurrentInputV1, artifact_id: str
    ) -> ExternalArtifactInputV1:
        for artifact in current.artifacts:
            if artifact.entry_id == artifact_id:
                return artifact
        raise CurrentAuthorityLost("current authority does not contain requested artifact")

    @staticmethod
    def _operation_for(
        current: ExternalInspectionCurrentInputV1, artifact: ExternalArtifactInputV1
    ) -> InspectorOperation:
        if current.phase is ExternalInspectionPhaseV1.INSPECTION:
            if (
                current.next_action is not ExternalInspectionNextActionV1.INSPECT
                or artifact.kind not in {ProcessingArtifactKind.ORTHO, ProcessingArtifactKind.DSM}
            ):
                raise CurrentAuthorityLost("operation is not approved for current artifact")
            return InspectorOperation.INSPECT
        if (
            current.phase is not ExternalInspectionPhaseV1.DISPLAY
            or current.next_action is not ExternalInspectionNextActionV1.SANITIZE_DISPLAY
            or artifact.kind is not ProcessingArtifactKind.ORTHO
        ):
            raise CurrentAuthorityLost("operation is not approved for current artifact")
        report = current.accepted_report
        if report is None:
            raise CurrentAuthorityLost("retained accepted report is required for sanitization")
        if (
            report.request_id != current.request.request_id
            or report.subject != current.request.subject
            or report.inspection_policy_digest != current.policy.policy_digest
            or report.inspector_build_digest != current.policy.parser_build_digest
        ):
            raise CurrentAuthorityLost("retained report does not bind current display authority")
        matching = [
            outcome
            for outcome in report.measurement_payload.outcomes
            if outcome.artifact_id == artifact.entry_id
            and outcome.observed_sha256 == artifact.observed_sha256
            and outcome.outcome is ArtifactOutcome.MEASURED
        ]
        if len(matching) != 1:
            raise CurrentAuthorityLost("retained report lacks measured exact ORTHO binding")
        measurements = matching[0].measurements
        if (
            measurements is None
            or measurements.band_count not in {3, 4}
            or measurements.dtype != "uint8"
        ):
            raise CurrentAuthorityLost("retained report ORTHO measurement model is incompatible")
        return InspectorOperation.SANITIZE

    def _require_profile(
        self,
        current: ExternalInspectionCurrentInputV1,
        artifact: ExternalArtifactInputV1,
        operation: InspectorOperation,
        deadline_monotonic: float,
    ) -> None:
        self._require_authority_deadline(deadline_monotonic)
        try:
            decision = self._operation_profile.allows(
                parser_build_digest=current.policy.parser_build_digest,
                grammar_digest=current.policy.grammar_digest,
                artifact_kind=artifact.kind,
                content_type=artifact.content_type,
                operation=operation,
                deadline_monotonic=deadline_monotonic,
            )
        except Exception as exc:
            raise CurrentAuthorityLost("trusted operation profile unavailable") from exc
        self._require_authority_deadline(deadline_monotonic)
        if decision is not InspectorOperationProfileDecision.ALLOW:
            raise CurrentAuthorityLost("trusted operation profile denied current artifact")

    def _open_source(
        self,
        artifact: ExternalArtifactInputV1,
        deadline_monotonic: float,
        authority_is_current: Callable[[], bool],
    ) -> DeadlineBoundedByteReaderPort:
        self._require_authority_deadline(deadline_monotonic)
        deadline = ProtocolDeadline.at_expires_at(deadline_monotonic, self._monotonic)
        deadline.remaining()
        try:
            source = self._byte_source.open_bound_bytes(
                artifact,
                deadline=deadline,
                wait_is_current=authority_is_current,
                heartbeat_interval_millis=self._limits.heartbeat_interval_millis,
            )
        except Exception as exc:
            raise CurrentAuthorityLost("sealed byte source unavailable") from exc
        if not isinstance(source, DeadlineBoundedByteReaderPort):
            raise CurrentAuthorityLost("sealed byte source lacks deadline-bounded reads")
        try:
            self._require_authority_deadline(deadline_monotonic)
        except Exception:
            with suppress(Exception):
                source.close()
            raise
        return source


__all__ = [
    "assemble_complete_measurement_payload",
    "CurrentAuthorityLost",
    "ExternalArtifactInputV1",
    "ExternalArtifactByteSourcePort",
    "ExternalArtifactInspectionWorker",
    "ExternalInspectionCurrentInputV1",
    "ExternalInspectorLaunchContextV1",
    "ExternalInspectionNextActionV1",
    "ExternalInspectionPhaseV1",
    "ExternalInspectorUdsClient",
    "InspectorUdsConnectorPort",
    "FileSystemSanitizedOutputSink",
    "InspectionAssemblyIncomplete",
    "PrivateSanitizedCandidateOpenerPort",
    "PrivateSanitizedCandidateReaderPort",
    "RetainedSanitizedCandidateAbortPort",
    "SanitizedOutputSinkPort",
    "SanitizedOutputTransactionPort",
    "WorkerAuthorityLimitsV1",
]
