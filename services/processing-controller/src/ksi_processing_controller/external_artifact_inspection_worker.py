"""Processing-controller mirrors and UDS client for one fenced inspector attempt.

This is deliberately a local authority adapter.  It imports immutable event
contracts but never imports ``ksi_core`` or exposes a Core route.  No URL,
header, object key, filename, Docker detail, parser, or artifact HTTP fetch is
representable in its launch DTO.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from contextlib import suppress
from enum import StrEnum
from math import isfinite
from typing import Annotated, BinaryIO, Protocol

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import (
    ArtifactOutcome,
    Digest,
    ExternalArtifactInspectionReportV1,
    ExternalArtifactInspectionRequestV1,
    ExternalValidationPolicyV1,
    PolicyStatus,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from pydantic import ConfigDict, Field, StrictInt, StringConstraints, model_validator

from ksi_processing_controller.external_inspector_launcher import InspectorOperationProfileDecision
from ksi_processing_controller.external_inspector_protocol import (
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

_BOUND_TEXT = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class CurrentAuthorityLost(RuntimeError):
    """The Core-fenced authority changed, disappeared, or failed closed during an attempt."""


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


class ExternalArtifactByteSourcePort(Protocol):
    """A later adapter supplies only the already-authorized bytes for this sealed projection."""

    def open_bound_bytes(
        self, artifact: ExternalArtifactInputV1, *, deadline_monotonic: float
    ) -> BinaryIO: ...


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
        source: BinaryIO,
        artifact_kind: ProcessingArtifactKind,
        content_type: str,
        deadline_monotonic: float,
        authority_is_current: Callable[[], bool],
    ) -> InspectorLaunchResultV1: ...


class SanitizedOutputSinkPort(Protocol):
    """Required bounded sink for raw derivative bytes; it owns no parser semantics."""

    def write(self, chunk: bytes, *, deadline_monotonic: float) -> None: ...


class ExternalInspectorUdsClient:
    """A supplied connector owns the provisioned UDS path; this class creates no listener."""

    def __init__(
        self,
        *,
        connect: Callable[[float], socket.socket],
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
        source: BinaryIO,
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
        connection = self._connect(deadline_monotonic)
        try:
            duration_millis = int(max(0.0, deadline_monotonic - self._monotonic()) * 1_000)
            if duration_millis <= 0:
                raise CurrentAuthorityLost("authority deadline elapsed before UDS launch")
            deadline = ProtocolDeadline(duration_millis, self._monotonic)
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
            read_completed_output(
                connection,
                terminal,
                self._protocol_limits,
                lambda chunk: self._write_sanitized_output(chunk, deadline),
                deadline=deadline,
                wait_is_current=authority_is_current,
                heartbeat_interval_millis=self._heartbeat_interval_millis,
            )
            if not authority_is_current():
                raise CurrentAuthorityLost("authority lost after UDS terminal frame")
            deadline.remaining()
            return terminal
        except (OSError, ProtocolViolation) as exc:
            raise CurrentAuthorityLost("UDS launch failed closed") from exc
        finally:
            with suppress(OSError):
                connection.close()

    def _write_sanitized_output(self, chunk: bytes, deadline: ProtocolDeadline) -> None:
        deadline.remaining()
        self._sanitized_output_sink.write(chunk, deadline_monotonic=deadline.expires_at)
        deadline.remaining()


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
        self._byte_source = byte_source
        self._launcher = launcher
        self._operation_profile = operation_profile
        self._limits = limits
        self._attempt_nonce_factory = attempt_nonce_factory
        self._monotonic = monotonic

    def launch_artifact(
        self, request_id: str, fence: LocalLeaseFenceV1, artifact_id: str
    ) -> InspectorLaunchResultV1:
        deadline = self._deadline()
        current = self._current_input(request_id, fence, deadline)
        artifact = self._artifact(current, artifact_id)
        operation = self._operation_for(current, artifact)
        self._require_profile(current, artifact, operation, deadline)
        self._heartbeat(request_id, fence, deadline)
        source = self._open_source(artifact, deadline)
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

            def authority_is_current() -> bool:
                try:
                    self._heartbeat(request_id, fence, deadline)
                except CurrentAuthorityLost:
                    return False
                return True

            result = self._launcher.execute(
                request=launch_request,
                source=source,
                artifact_kind=artifact.kind,
                content_type=artifact.content_type,
                deadline_monotonic=deadline,
                authority_is_current=authority_is_current,
            )
            self._require_authority_deadline(deadline)
            result.validate_for(launch_request)
            self._heartbeat(request_id, fence, deadline)
            latest = self._current_input(request_id, fence, deadline)
            if latest != current:
                raise CurrentAuthorityLost(
                    "current authority changed before terminal result return"
                )
            return result
        except CurrentAuthorityLost:
            raise
        except Exception as exc:
            raise CurrentAuthorityLost("worker launch failed closed") from exc
        finally:
            with suppress(Exception):
                source.close()

    def _deadline(self) -> float:
        now = self._monotonic()
        if not isfinite(now):
            raise CurrentAuthorityLost("monotonic authority clock is invalid")
        return now + self._limits.max_authority_wait_millis / 1_000

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
        self, artifact: ExternalArtifactInputV1, deadline_monotonic: float
    ) -> BinaryIO:
        self._require_authority_deadline(deadline_monotonic)
        try:
            source = self._byte_source.open_bound_bytes(
                artifact, deadline_monotonic=deadline_monotonic
            )
        except Exception as exc:
            raise CurrentAuthorityLost("sealed byte source unavailable") from exc
        try:
            self._require_authority_deadline(deadline_monotonic)
        except Exception:
            with suppress(Exception):
                source.close()
            raise
        return source


__all__ = [
    "CurrentAuthorityLost",
    "ExternalArtifactInputV1",
    "ExternalArtifactInspectionWorker",
    "ExternalInspectionCurrentInputV1",
    "ExternalInspectionNextActionV1",
    "ExternalInspectionPhaseV1",
    "ExternalInspectorUdsClient",
    "SanitizedOutputSinkPort",
    "WorkerAuthorityLimitsV1",
]
