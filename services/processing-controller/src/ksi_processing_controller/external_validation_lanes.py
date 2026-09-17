"""Concrete external inspection lane; it owns no Core runtime or queue policy.

The runner supplies one already-fenced lease.  This adapter obtains a fresh
projection, turns only its private capabilities into bounded readers, and
returns Core's own terminal state.  It never interprets an unavailable runtime
as a rejected measurement.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
from typing import Protocol
from uuid import UUID, uuid4

from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ExternalArtifactInspectionReportV1,
)
from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestV1

from ksi_processing_controller.external_artifact_inspection_worker import (
    CurrentAuthorityLost,
    ExternalArtifactInputV1,
    ExternalArtifactInspectionWorker,
    ExternalInspectionCurrentInputV1,
    ExternalInspectionPhaseV1,
    ExternalInspectorLaunchContextV1,
    ExternalInspectorLaunchPort,
    InspectionAssemblyIncomplete,
    InspectorWorkerOperationProfilePort,
    WorkerAuthorityLimitsV1,
    assemble_complete_measurement_payload,
)
from ksi_processing_controller.external_display_publication import (
    DisplayPublicationCorePort,
    ExternalDisplayPublicationWorker,
    RetainedSanitizedCandidateOwnerPort,
)
from ksi_processing_controller.external_inspector_protocol import (
    BoundByteReceiptV1,
    DeadlineBoundedByteReaderPort,
    LocalLeaseFenceV1,
    ProtocolDeadline,
    ProtocolLimitsV1,
)
from ksi_processing_controller.external_measurement_client import ExternalMeasurementUdsClient
from ksi_processing_controller.external_measurement_core_client import (
    MeasurementLeaseGrantV1,
    MeasurementOperationV2,
)
from ksi_processing_controller.external_measurement_protocol import (
    MeasurementInputV2,
    MeasurementLaunchRequestV2,
)
from ksi_processing_controller.external_measurement_result import MeasurementResultV2
from ksi_processing_controller.external_object_streams import (
    ExternalObjectHttpByteSource,
    ExternalObjectTransportError,
    ExternalObjectTransportPolicyV1,
    SealedObjectByteSourceV1,
)
from ksi_processing_controller.external_validation_core_client import ExternalCoreClientError
from ksi_processing_controller.external_validation_runner import (
    ExternalLane,
    ExternalLaneUnavailable,
    ExternalWorkLease,
    TurnOutcome,
)

_RETRYABLE_CORE_CODES = frozenset(
    {
        "INVALID_CORE_RESPONSE",
        "CORE_HTTP_500",
        "CORE_HTTP_502",
        "CORE_HTTP_503",
        "CORE_HTTP_504",
    }
)
_RETRYABLE_OBJECT_CODES = frozenset(
    {
        "CONNECT_FAILED",
        "SOCKET_WRITE_FAILED",
        "SOCKET_READ_FAILED",
        "UNEXPECTED_HEADER_EOF",
        "UNEXPECTED_BODY_EOF",
    }
)


class InspectionCorePort(DisplayPublicationCorePort, Protocol):
    def list_pending(self, *, deadline_monotonic: float, limit: int = 50) -> tuple[object, ...]: ...

    def claim(
        self,
        request_id: str,
        *,
        worker_instance_id: str,
        acquisition_id: str,
        deadline_monotonic: float,
    ) -> object: ...

    def current_input(
        self, request_id: str, fence: LocalLeaseFenceV1, *, deadline_monotonic: float
    ) -> ExternalInspectionCurrentInputV1 | None: ...

    def heartbeat(
        self, request_id: str, fence: LocalLeaseFenceV1, *, deadline_monotonic: float
    ) -> bool: ...

    def capability_for(
        self, request_id: str, fence: LocalLeaseFenceV1, artifact: ExternalArtifactInputV1
    ) -> object: ...

    def record_report(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        report: ExternalArtifactInspectionReportV1,
        *,
        deadline_monotonic: float,
    ) -> ExternalArtifactInspectionReportV1: ...

    def record_incomplete_failure(
        self, request_id: str, fence: LocalLeaseFenceV1, reason: str, *, deadline_monotonic: float
    ) -> object: ...

    def release(self, request_id: str, fence: LocalLeaseFenceV1) -> None: ...


class MeasurementCorePort(Protocol):
    def list_pending(
        self, operation: MeasurementOperationV2, *, deadline_monotonic: float, limit: int = 50
    ) -> tuple[object, ...]: ...

    def claim(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        *,
        worker_instance_id: str,
        acquisition_id: str,
        deadline_monotonic: float,
    ) -> MeasurementLeaseGrantV1: ...

    def heartbeat(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        fence: LocalLeaseFenceV1,
        *,
        deadline_monotonic: float,
    ) -> MeasurementLeaseGrantV1 | None: ...

    def current_input(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        fence: LocalLeaseFenceV1,
        *,
        attempt_nonce: str,
        deadline_monotonic: float,
    ) -> MeasurementLaunchRequestV2 | None: ...

    def capability_for(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        fence: LocalLeaseFenceV1,
        artifact: MeasurementInputV2,
    ) -> object: ...

    def submit_result(
        self,
        launch: MeasurementLaunchRequestV2,
        result: MeasurementResultV2,
        *,
        manifest: InspectorExecutionManifestV1,
        limits: ProtocolLimitsV1,
        computed_at: datetime,
        deadline_monotonic: float,
    ) -> None: ...

    def record_incomplete_failure(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        fence: LocalLeaseFenceV1,
        reason: str,
        *,
        deadline_monotonic: float,
    ) -> None: ...

    def release(
        self, operation: MeasurementOperationV2, request_id: str, fence: LocalLeaseFenceV1
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class InspectionLaneDependencies:
    """Explicit reviewed ports; no factory, plugin, or default runtime is hidden here."""

    launcher: ExternalInspectorLaunchPort
    operation_profile: InspectorWorkerOperationProfilePort
    candidate_sink: RetainedSanitizedCandidateOwnerPort
    object_policy: ExternalObjectTransportPolicyV1
    worker_limits: WorkerAuthorityLimitsV1

    def __post_init__(self) -> None:
        if not isinstance(self.object_policy, ExternalObjectTransportPolicyV1):
            raise TypeError("inspection object policy must be explicit")
        if not isinstance(self.worker_limits, WorkerAuthorityLimitsV1):
            raise TypeError("inspection worker limits must be explicit")


class _DisplayPut:
    """Construct one bounded PUT transport for one Core-issued private grant."""

    def __init__(self, policy: ExternalObjectTransportPolicyV1) -> None:
        self._policy = policy

    def put_bound_bytes(
        self,
        capability: object,
        sealed_source: SealedObjectByteSourceV1,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> BoundByteReceiptV1:
        transport = ExternalObjectHttpByteSource((capability,), policy=self._policy)
        return transport.put_bound_bytes(
            capability,
            sealed_source,
            deadline=deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )


class InspectionValidationLane:
    """One inspection/display adapter with exact lease and retained-publication handling."""

    lane = ExternalLane.INSPECTION

    def __init__(
        self,
        *,
        core: InspectionCorePort,
        worker_instance_id: str,
        dependencies: InspectionLaneDependencies,
        report_id_factory: Callable[[], str] = lambda: str(uuid4()),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        try:
            parsed = UUID(worker_instance_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("inspection worker identity must be a UUID") from exc
        if parsed.version != 4 or str(parsed) != worker_instance_id:
            raise ValueError("inspection worker identity must be a canonical UUID4")
        if not callable(report_id_factory) or not callable(clock):
            raise TypeError("inspection lane identities and clock must be explicit")
        self._core = core
        self._worker_instance_id = worker_instance_id
        self._dependencies = dependencies
        self._report_id_factory = report_id_factory
        self._clock = clock
        self._closed = False

    def poll(self, *, deadline_monotonic: float) -> str | None:
        self._require_open()
        try:
            pending = self._core.list_pending(deadline_monotonic=deadline_monotonic, limit=1)
        except Exception as exc:
            raise ExternalLaneUnavailable("inspection queue unavailable") from exc
        if not isinstance(pending, tuple) or not pending:
            return None
        request_id = getattr(pending[0], "request_id", None)
        if not isinstance(request_id, str) or not request_id:
            raise ExternalLaneUnavailable("inspection queue identity unavailable")
        return request_id

    def claim(
        self, request_id: str, acquisition_id: str, *, deadline_monotonic: float
    ) -> ExternalWorkLease | None:
        self._require_open()
        try:
            lease = self._core.claim(
                request_id,
                worker_instance_id=self._worker_instance_id,
                acquisition_id=acquisition_id,
                deadline_monotonic=deadline_monotonic,
            )
            returned_request = getattr(getattr(lease, "request", None), "request_id", None)
            fence = LocalLeaseFenceV1.model_validate(getattr(lease, "fence", None))
        except Exception as exc:
            raise ExternalLaneUnavailable("inspection claim unavailable") from exc
        if (
            returned_request != request_id
            or fence.worker_instance_id != self._worker_instance_id
            or fence.lease_acquisition_id != acquisition_id
        ):
            raise ExternalLaneUnavailable("inspection claim binding differs")
        return ExternalWorkLease(request_id=request_id, fence=fence)

    def execute(
        self, lease: ExternalWorkLease, *, deadline_monotonic: float, stop: Event
    ) -> TurnOutcome:
        self._require_open()
        if stop.is_set():
            return TurnOutcome.STOPPED
        try:
            current = self._current(lease, deadline_monotonic)
        except CurrentAuthorityLost:
            return TurnOutcome.STOPPED if stop.is_set() else TurnOutcome.DEFERRED
        if current.phase is ExternalInspectionPhaseV1.INSPECTION:
            try:
                self._execute_inspection(current, lease, deadline_monotonic, stop)
            except (CurrentAuthorityLost, InspectionAssemblyIncomplete) as exc:
                if stop.is_set():
                    return TurnOutcome.STOPPED
                self._record_incomplete(lease, deadline_monotonic, exc)
                return TurnOutcome.DEFERRED
            except ExternalLaneUnavailable:
                raise
            except Exception as exc:
                raise ExternalLaneUnavailable("inspection execution unavailable") from exc
            # Core owns the accepted immutable report and decides whether it
            # made DISPLAY eligible. Refreshing under the still-live lease is
            # the only way to continue without assuming the INSPECTION
            # projection remains current after the terminal report.
            if stop.is_set():
                return TurnOutcome.STOPPED
            try:
                display_current = self._current(lease, deadline_monotonic)
            except CurrentAuthorityLost:
                # The report is already terminal. A lost or spent lease cannot
                # authorize an incomplete terminal, and Core will offer any
                # unfinished DISPLAY work to a later current lease.
                return TurnOutcome.STOPPED if stop.is_set() else TurnOutcome.COMPLETED
            if display_current.phase is ExternalInspectionPhaseV1.DISPLAY:
                try:
                    self._execute_display(display_current, lease, deadline_monotonic, stop)
                except CurrentAuthorityLost:
                    return TurnOutcome.STOPPED if stop.is_set() else TurnOutcome.DEFERRED
                except ExternalLaneUnavailable:
                    raise
                except Exception as exc:
                    raise ExternalLaneUnavailable("inspection display unavailable") from exc
        elif current.phase is ExternalInspectionPhaseV1.DISPLAY:
            try:
                self._execute_display(current, lease, deadline_monotonic, stop)
            except CurrentAuthorityLost:
                return TurnOutcome.STOPPED if stop.is_set() else TurnOutcome.DEFERRED
            except ExternalLaneUnavailable:
                raise
            except Exception as exc:
                raise ExternalLaneUnavailable("inspection display unavailable") from exc
        else:
            return TurnOutcome.DEFERRED
        return TurnOutcome.STOPPED if stop.is_set() else TurnOutcome.COMPLETED

    def release(self, lease: ExternalWorkLease) -> None:
        try:
            self._core.release(lease.request_id, lease.fence)
        except Exception as exc:
            raise ExternalLaneUnavailable("inspection release unavailable") from exc

    def close(self) -> None:
        self._closed = True

    def _execute_inspection(
        self,
        current: ExternalInspectionCurrentInputV1,
        lease: ExternalWorkLease,
        deadline_monotonic: float,
        stop: Event,
    ) -> None:
        worker = self._worker_for(current, lease, deadline_monotonic)

        def is_current(fence: LocalLeaseFenceV1) -> bool:
            return (
                not stop.is_set()
                and fence == lease.fence
                and self._is_current(current, lease, deadline_monotonic, stop)
            )

        def inspect_one(artifact: ExternalArtifactInputV1) -> ArtifactInspectionOutcomeV1:
            context = worker.launch_artifact_context(
                lease.request_id,
                lease.fence,
                artifact.entry_id,
                deadline_monotonic=deadline_monotonic,
                authority_is_current=lambda: is_current(lease.fence),
            )
            outcome = context.terminal.outcome
            if not isinstance(outcome, ArtifactInspectionOutcomeV1):
                raise InspectionAssemblyIncomplete("inspection terminal lacks an exact outcome")
            return outcome

        payload = assemble_complete_measurement_payload(
            current=current,
            fence=lease.fence,
            inspect_one=inspect_one,
            authority_is_current=is_current,
            is_cancelled=stop.is_set,
        )
        if not is_current(lease.fence):
            raise InspectionAssemblyIncomplete("inspection authority changed before report")
        policy_digest = current.policy.policy_digest
        if policy_digest is None:
            raise InspectionAssemblyIncomplete("inspection policy digest is unavailable")
        report = ExternalArtifactInspectionReportV1(
            report_id=self._report_id_factory(),
            request_id=lease.request_id,
            subject=current.request.subject,
            subject_digest=current.request.subject.canonical_digest(),
            sealed_manifest_digest=current.request.subject.manifest_digest,
            inspection_policy_digest=policy_digest,
            inspector_build_digest=current.policy.parser_build_digest,
            measurement_payload=payload,
            worker_instance_id=lease.fence.worker_instance_id,
            lease_acquisition_id=lease.fence.lease_acquisition_id,
            lease_generation=lease.fence.lease_generation,
            reported_at=self._clock(),
        ).sealed()
        self._record_report_retry(
            lease,
            report,
            deadline_monotonic,
            is_current=lambda: is_current(lease.fence),
            stop=stop,
        )

    def _execute_display(
        self,
        current: ExternalInspectionCurrentInputV1,
        lease: ExternalWorkLease,
        deadline_monotonic: float,
        stop: Event,
    ) -> None:
        artifacts = tuple(item for item in current.artifacts if item.kind.value == "ortho")
        if len(artifacts) != 1:
            raise CurrentAuthorityLost("display authority lacks one exact ORTHO")

        def is_current() -> bool:
            return self._is_current(current, lease, deadline_monotonic, stop)

        worker = self._worker_for(current, lease, deadline_monotonic)
        context = worker.launch_artifact_context(
            lease.request_id,
            lease.fence,
            artifacts[0].entry_id,
            deadline_monotonic=deadline_monotonic,
            authority_is_current=is_current,
        )
        publication = ExternalDisplayPublicationWorker(
            core=self._core,
            candidate_opener=self._dependencies.candidate_sink,
            object_transport=_DisplayPut(self._dependencies.object_policy),
        )
        try:
            if not is_current():
                raise CurrentAuthorityLost("inspection display was cancelled")
            for attempt in range(2):
                try:
                    publication.publish(context)
                    # The publisher has an exact terminal Core receipt and has
                    # retired the candidate.  Core may therefore already have
                    # consumed the DISPLAY lease; no later side effect remains
                    # for this turn to authorize.
                    return
                except BaseException as exc:
                    if attempt == 0 and self._retryable_display_failure(exc, context):
                        continue
                    raise
        except BaseException:
            self._abort_display_candidate_quietly(context)
            raise

    def _worker_for(
        self,
        current: ExternalInspectionCurrentInputV1,
        lease: ExternalWorkLease,
        deadline_monotonic: float,
    ) -> ExternalArtifactInspectionWorker:
        capabilities = tuple(
            self._core.capability_for(lease.request_id, lease.fence, artifact)
            for artifact in current.artifacts
        )
        byte_source = ExternalObjectHttpByteSource(
            capabilities, policy=self._dependencies.object_policy
        )
        return ExternalArtifactInspectionWorker(
            authority=self._core,
            byte_source=byte_source,
            launcher=self._dependencies.launcher,
            operation_profile=self._dependencies.operation_profile,
            limits=self._dependencies.worker_limits,
            attempt_nonce_factory=lambda: str(uuid4()),
        )

    def _current(
        self, lease: ExternalWorkLease, deadline_monotonic: float
    ) -> ExternalInspectionCurrentInputV1:
        try:
            current = self._core.current_input(
                lease.request_id, lease.fence, deadline_monotonic=deadline_monotonic
            )
        except Exception:
            raise CurrentAuthorityLost("inspection current input unavailable") from None
        if current is None or current.request.request_id != lease.request_id:
            raise CurrentAuthorityLost("inspection current input is unavailable")
        return current

    def _is_current(
        self,
        expected: ExternalInspectionCurrentInputV1,
        lease: ExternalWorkLease,
        deadline_monotonic: float,
        stop: Event | None = None,
    ) -> bool:
        if stop is not None and stop.is_set():
            return False
        try:
            if (
                self._core.heartbeat(
                    lease.request_id, lease.fence, deadline_monotonic=deadline_monotonic
                )
                is not True
            ):
                return False
            if stop is not None and stop.is_set():
                return False
            current = self._current(lease, deadline_monotonic)
            return current == expected and (stop is None or not stop.is_set())
        except Exception:
            return False

    def _record_report_retry(
        self,
        lease: ExternalWorkLease,
        report: ExternalArtifactInspectionReportV1,
        deadline_monotonic: float,
        *,
        is_current: Callable[[], bool],
        stop: Event,
    ) -> None:
        for attempt in range(2):
            # Before the first terminal submission, the INSPECTION projection must
            # still be current.  A lost response can mean Core committed that
            # exact report and moved to DISPLAY, so retrying the idempotent
            # terminal request must not demand the pre-terminal projection again.
            if attempt == 0 and is_current() is not True:
                raise CurrentAuthorityLost("inspection report authority changed")
            try:
                self._core.record_report(
                    lease.request_id, lease.fence, report, deadline_monotonic=deadline_monotonic
                )
                return
            except Exception as exc:
                if attempt == 0 and getattr(exc, "code", None) in _RETRYABLE_CORE_CODES:
                    if stop.is_set():
                        raise CurrentAuthorityLost("inspection report was cancelled") from exc
                    ProtocolDeadline.at_expires_at(deadline_monotonic).remaining()
                    continue
                raise ExternalLaneUnavailable("inspection report unavailable") from exc
        raise AssertionError("inspection report retry did not return")

    def _abort_display_candidate_quietly(self, context: ExternalInspectorLaunchContextV1) -> None:
        abort_attempt = getattr(self._dependencies.candidate_sink, "abort_attempt", None)
        if not callable(abort_attempt):
            return
        with suppress(BaseException):
            abort_attempt(context.retained_launch_request)

    @staticmethod
    def _retryable_display_failure(
        exc: BaseException, context: ExternalInspectorLaunchContextV1
    ) -> bool:
        retryable = (
            isinstance(exc, ExternalCoreClientError) and exc.code in _RETRYABLE_CORE_CODES
        ) or (isinstance(exc, ExternalObjectTransportError) and exc.code in _RETRYABLE_OBJECT_CODES)
        if not retryable:
            return False
        try:
            deadline = context.retained_deadline
            authority = context.retained_authority_is_current
            deadline.remaining()
            return authority() is True
        except BaseException:
            return False

    def _record_incomplete(
        self, lease: ExternalWorkLease, deadline_monotonic: float, cause: BaseException
    ) -> None:
        try:
            self._core.record_incomplete_failure(
                lease.request_id,
                lease.fence,
                "TRANSIENT_SERVICE_UNAVAILABLE",
                deadline_monotonic=deadline_monotonic,
            )
        except Exception:
            raise ExternalLaneUnavailable("inspection incomplete result unavailable") from cause

    def _require_open(self) -> None:
        if self._closed:
            raise ExternalLaneUnavailable("inspection lane is closed")


@dataclass(frozen=True, slots=True)
class MeasurementLaneDependencies:
    """Explicit V2 runtime and manifest bindings for one externally claimed lane."""

    manifest: InspectorExecutionManifestV1
    uds_client: ExternalMeasurementUdsClient
    protocol_limits: ProtocolLimitsV1
    heartbeat_interval_millis: int
    object_policy: ExternalObjectTransportPolicyV1

    def __post_init__(self) -> None:
        if not isinstance(self.object_policy, ExternalObjectTransportPolicyV1):
            raise TypeError("measurement object policy must be explicit")
        if not isinstance(self.protocol_limits, ProtocolLimitsV1):
            raise TypeError("measurement protocol limits must be explicit")
        if type(self.heartbeat_interval_millis) is not int or self.heartbeat_interval_millis <= 0:
            raise ValueError("measurement heartbeat interval must be explicit")


class MeasurementValidationLane:
    """Execute only sealed two-input V2 measurement truth through its Core lane."""

    def __init__(
        self,
        *,
        lane: ExternalLane,
        operation: MeasurementOperationV2,
        core: MeasurementCorePort,
        worker_instance_id: str,
        dependencies: MeasurementLaneDependencies,
        attempt_nonce_factory: Callable[[], str] = lambda: str(uuid4()),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        expected = {
            ExternalLane.CHECKPOINT: "CHECKPOINT_VALIDATION",
            ExternalLane.RELATIVE_VOLUME: "RELATIVE_VOLUME",
            ExternalLane.SINGLE_VOLUME: "SINGLE_VOLUME",
        }
        if lane not in expected or operation != expected[lane]:
            raise ValueError("measurement lane must retain its fixed Core operation")
        try:
            parsed = UUID(worker_instance_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("measurement worker identity must be a canonical UUID4") from exc
        if parsed.version != 4 or str(parsed) != worker_instance_id:
            raise ValueError("measurement worker identity must be a canonical UUID4")
        if not callable(attempt_nonce_factory) or not callable(clock):
            raise TypeError("measurement lane identity and clock must be explicit")
        self.lane = lane
        self._operation = operation
        self._core = core
        self._worker_instance_id = worker_instance_id
        self._dependencies = dependencies
        self._attempt_nonce_factory = attempt_nonce_factory
        self._clock = clock
        self._closed = False

    def poll(self, *, deadline_monotonic: float) -> str | None:
        self._require_open()
        try:
            pending = self._core.list_pending(
                self._operation, deadline_monotonic=deadline_monotonic, limit=1
            )
        except Exception as exc:
            raise ExternalLaneUnavailable("measurement queue unavailable") from exc
        if not isinstance(pending, tuple) or not pending:
            return None
        first = pending[0]
        request_id = getattr(first, "request_id", None)
        if (
            getattr(first, "operation", None) != self._operation
            or not isinstance(request_id, str)
            or not request_id
        ):
            raise ExternalLaneUnavailable("measurement queue identity unavailable")
        return request_id

    def claim(
        self, request_id: str, acquisition_id: str, *, deadline_monotonic: float
    ) -> ExternalWorkLease | None:
        self._require_open()
        try:
            grant = self._core.claim(
                self._operation,
                request_id,
                worker_instance_id=self._worker_instance_id,
                acquisition_id=acquisition_id,
                deadline_monotonic=deadline_monotonic,
            )
            fence = LocalLeaseFenceV1.model_validate(grant.fence.__dict__)
        except Exception as exc:
            raise ExternalLaneUnavailable("measurement claim unavailable") from exc
        if (
            grant.operation != self._operation
            or grant.request_id != request_id
            or fence.worker_instance_id != self._worker_instance_id
            or fence.lease_acquisition_id != acquisition_id
        ):
            raise ExternalLaneUnavailable("measurement claim binding differs")
        return ExternalWorkLease(request_id=request_id, fence=fence)

    def execute(
        self, lease: ExternalWorkLease, *, deadline_monotonic: float, stop: Event
    ) -> TurnOutcome:
        self._require_open()
        if stop.is_set():
            return TurnOutcome.STOPPED
        launch: MeasurementLaunchRequestV2 | None = None
        terminal_started = False
        try:
            launch = self._core.current_input(
                self._operation,
                lease.request_id,
                lease.fence,
                attempt_nonce=self._attempt_nonce(),
                deadline_monotonic=deadline_monotonic,
            )
            if launch is None:
                return TurnOutcome.DEFERRED
            if (
                launch.operation != self._operation
                or launch.request_id != lease.request_id
                or launch.fence != lease.fence
                or not self._is_current(lease, deadline_monotonic, stop)
            ):
                return TurnOutcome.STOPPED if stop.is_set() else TurnOutcome.DEFERRED
            result = self._execute_launch(launch, lease, deadline_monotonic, stop)
            terminal_started = True
            self._core.submit_result(
                launch,
                result,
                manifest=self._dependencies.manifest,
                limits=self._dependencies.protocol_limits,
                computed_at=self._clock(),
                deadline_monotonic=deadline_monotonic,
            )
        except Exception as exc:
            if stop.is_set():
                return TurnOutcome.STOPPED
            if launch is None:
                return TurnOutcome.DEFERRED
            if terminal_started:
                raise ExternalLaneUnavailable(
                    "measurement terminal adjudication unavailable"
                ) from exc
            try:
                self._core.record_incomplete_failure(
                    self._operation,
                    lease.request_id,
                    lease.fence,
                    "TRANSIENT_SERVICE_UNAVAILABLE",
                    deadline_monotonic=deadline_monotonic,
                )
            except Exception as record_exc:
                raise ExternalLaneUnavailable(
                    "measurement incomplete result unavailable"
                ) from record_exc
            return TurnOutcome.DEFERRED
        return TurnOutcome.STOPPED if stop.is_set() else TurnOutcome.COMPLETED

    def release(self, lease: ExternalWorkLease) -> None:
        try:
            self._core.release(self._operation, lease.request_id, lease.fence)
        except Exception as exc:
            raise ExternalLaneUnavailable("measurement release unavailable") from exc

    def close(self) -> None:
        self._closed = True

    def _execute_launch(
        self,
        launch: MeasurementLaunchRequestV2,
        lease: ExternalWorkLease,
        deadline_monotonic: float,
        stop: Event,
    ) -> MeasurementResultV2:
        def current() -> bool:
            return self._is_current(lease, deadline_monotonic, stop)

        deadline = ProtocolDeadline.at_expires_at(deadline_monotonic)
        capabilities = tuple(
            self._core.capability_for(self._operation, lease.request_id, lease.fence, item)
            for item in launch.inputs
        )
        byte_source = ExternalObjectHttpByteSource(
            capabilities, policy=self._dependencies.object_policy
        )
        sources: list[DeadlineBoundedByteReaderPort] = []
        try:
            for item in launch.inputs:
                sources.append(
                    byte_source.open_bound_bytes(
                        item,
                        deadline=deadline,
                        wait_is_current=current,
                        heartbeat_interval_millis=self._dependencies.heartbeat_interval_millis,
                    )
                )
        except BaseException:
            self._close_readers_quietly(sources)
            raise
        if len(sources) != 2:
            self._close_readers_quietly(sources)
            raise ExternalLaneUnavailable("measurement source count differs")
        try:
            result = self._dependencies.uds_client.execute(
                request=launch,
                manifest=self._dependencies.manifest,
                sources=(sources[0], sources[1]),
                deadline_monotonic=deadline_monotonic,
                authority_is_current=current,
            )
        except BaseException:
            self._close_readers_quietly(sources)
            raise
        self._close_readers(sources)
        return result

    def _is_current(self, lease: ExternalWorkLease, deadline_monotonic: float, stop: Event) -> bool:
        if stop.is_set():
            return False
        try:
            grant = self._core.heartbeat(
                self._operation,
                lease.request_id,
                lease.fence,
                deadline_monotonic=deadline_monotonic,
            )
        except Exception:
            return False
        return not stop.is_set() and grant is not None and grant.fence == lease.fence

    def _attempt_nonce(self) -> str:
        value = self._attempt_nonce_factory()
        try:
            parsed = UUID(value)
        except (TypeError, ValueError) as exc:
            raise ExternalLaneUnavailable("measurement attempt identity is invalid") from exc
        if parsed.version != 4 or str(parsed) != value:
            raise ExternalLaneUnavailable("measurement attempt identity is invalid")
        return value

    @staticmethod
    def _close_readers_quietly(readers: list[DeadlineBoundedByteReaderPort]) -> None:
        for reader in reversed(readers):
            with suppress(BaseException):
                reader.close()

    @staticmethod
    def _close_readers(readers: list[DeadlineBoundedByteReaderPort]) -> None:
        first_error: BaseException | None = None
        for reader in reversed(readers):
            try:
                reader.close()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise ExternalLaneUnavailable("measurement source cleanup unavailable") from first_error

    def _require_open(self) -> None:
        if self._closed:
            raise ExternalLaneUnavailable("measurement lane is closed")


__all__ = [
    "InspectionCorePort",
    "InspectionLaneDependencies",
    "InspectionValidationLane",
    "MeasurementCorePort",
    "MeasurementLaneDependencies",
    "MeasurementValidationLane",
]
