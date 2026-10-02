"""Sequential local execution of one exact Analysis-worker lease at a time."""

from __future__ import annotations

import hashlib
import math
import os
import re
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, RLock, Thread

from ksi_event_contracts.external_analysis_worker import (
    AnalysisWorkerInputCapabilityV1,
    AnalysisWorkerInputV1,
    AnalysisWorkerLeaseViewV1,
)
from ksi_event_contracts.external_relative_volume_analysis import CalculationIdentityV2
from ksi_event_contracts.external_relative_volume_calculation import (
    AnalysisExecutionAttemptV2,
    RelativeVolumeCalculationFailureV2,
    RelativeVolumeCalculationReportV2,
)

from ksi_processing_controller.external_analysis_core_client import (
    ExternalAnalysisCoreClient,
    ExternalAnalysisCoreClientError,
)
from ksi_processing_controller.external_analysis_measurement import (
    measure_external_relative_volume_v2,
)
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedByteReaderPort,
    ProtocolDeadline,
    ProtocolDeadlineExceeded,
    ProtocolViolation,
)
from ksi_processing_controller.external_measurement_protocol import MeasurementInputV2
from ksi_processing_controller.external_object_streams import (
    ExternalObjectCapabilityV1,
    ExternalObjectHttpByteSource,
    ExternalObjectTransportError,
    ExternalObjectTransportPolicyV1,
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_INPUTS = 2


class _LeaseLost(RuntimeError):
    pass


class _WorkerFault(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProcessingWorkerRuntimeIdentityV1:
    """Local configuration assertions compared to Core's sealed calculation identity."""

    worker_executable_digest: str
    worker_build_digest: str
    runtime_image_version: str
    runtime_image_oci_digest: str
    dependency_lock_digest: str

    def __post_init__(self) -> None:
        for value in (
            self.worker_executable_digest,
            self.worker_build_digest,
            self.runtime_image_oci_digest,
            self.dependency_lock_digest,
        ):
            if type(value) is not str or _DIGEST.fullmatch(value) is None:
                raise ValueError("worker runtime digest must be an exact SHA-256 digest")
        if (
            type(self.runtime_image_version) is not str
            or not self.runtime_image_version
            or len(self.runtime_image_version) > 255
            or self.runtime_image_version.strip() != self.runtime_image_version
        ):
            raise ValueError("worker runtime image version is malformed")

    def matches(self, identity: CalculationIdentityV2) -> bool:
        return (
            self.worker_executable_digest == identity.worker_executable_digest
            and self.worker_build_digest == identity.worker_build_digest
            and self.runtime_image_version == identity.runtime_image_version
            and self.runtime_image_oci_digest == identity.runtime_image_oci_digest
            and self.dependency_lock_digest == identity.dependency_lock_digest
        )


class _LeaseKeeper:
    def __init__(
        self,
        *,
        client: ExternalAnalysisCoreClient,
        analysis_id: str,
        lease: AnalysisWorkerLeaseViewV1,
    ) -> None:
        self._client = client
        self._analysis_id = analysis_id
        self._calculation_request_id = lease.calculation_request_id
        self._attempt = lease.attempt
        self._lost = False
        self._lock = RLock()

    @property
    def attempt(self) -> AnalysisExecutionAttemptV2:
        with self._lock:
            return self._attempt

    def renew(self) -> AnalysisExecutionAttemptV2:
        with self._lock:
            if self._lost:
                raise _LeaseLost()
            try:
                view = self._client.renew(self._analysis_id, self._attempt)
            except ExternalAnalysisCoreClientError as exc:
                self._lost = True
                raise _LeaseLost() from exc
            if view.calculation_request_id != self._calculation_request_id:
                self._lost = True
                raise _LeaseLost()
            self._attempt = view.attempt
            return self._attempt

    def current(self) -> bool:
        try:
            self.renew()
        except _LeaseLost:
            return False
        return True


class _LeaseHeartbeat:
    """Renew one accepted fence during a synchronous real measurement."""

    def __init__(self, keeper: _LeaseKeeper, *, interval_seconds: float) -> None:
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("lease heartbeat interval must be positive and finite")
        self._keeper = keeper
        self._interval_seconds = interval_seconds
        self._stop = Event()
        self._lost = Event()
        self._thread = Thread(target=self._run, name="ksi-analysis-lease-heartbeat")

    @property
    def lost(self) -> bool:
        return self.is_lost()

    def is_lost(self) -> bool:
        return self._lost.is_set()

    def start(self) -> None:
        self._thread.start()

    def stop_and_join(self) -> bool:
        self._stop.set()
        self._thread.join()
        return not self._lost.is_set()

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._keeper.current():
                self._lost.set()
                return
            if self._stop.wait(self._interval_seconds):
                return


def _utc_now(now: Callable[[], datetime]) -> datetime:
    value = now()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise _WorkerFault("WORKER_CLOCK_INVALID")
    return value


def _resource_limits(input_value: AnalysisWorkerInputV1) -> None:
    envelope = input_value.attempt.authorization.resource_envelope
    values = input_value.inputs
    if len(values) != _MAX_INPUTS:
        raise _WorkerFault("WORKER_INPUT_BINDING_MISMATCH")
    maximum_per_input = min(envelope.max_input_bytes, envelope.max_streamed_bytes)
    total = 0
    for item in values:
        if item.observed_size_bytes > maximum_per_input:
            raise _WorkerFault("RESOURCE_LIMIT_EXCEEDED")
        total += item.observed_size_bytes
    if (
        total > envelope.max_input_bytes
        or total > envelope.max_streamed_bytes
        or 2 * total > envelope.max_workspace_bytes
    ):
        raise _WorkerFault("RESOURCE_LIMIT_EXCEEDED")
    if envelope.max_output_bytes <= 0 or envelope.max_deadline_seconds <= 0:
        raise _WorkerFault("RESOURCE_LIMIT_EXCEEDED")


def _capability_input(item: AnalysisWorkerInputCapabilityV1) -> MeasurementInputV2:
    return MeasurementInputV2(
        role=item.role,
        artifact_id=item.artifact_id,
        observed_sha256=item.observed_sha256,
        observed_size_bytes=item.observed_size_bytes,
    )


def _capability_is_current(
    capability: AnalysisWorkerInputCapabilityV1, now: Callable[[], datetime]
) -> bool:
    return capability.expires_at > _utc_now(now)


def _private_download(
    *,
    source: ExternalObjectHttpByteSource,
    capability: AnalysisWorkerInputCapabilityV1,
    path: Path,
    deadline: ProtocolDeadline,
    keeper: _LeaseKeeper,
    max_chunk_bytes: int,
    now: Callable[[], datetime],
) -> None:
    def download_is_current() -> bool:
        return keeper.current() and _capability_is_current(capability, now)

    def require_download_current() -> None:
        if not keeper.current():
            raise _LeaseLost()
        if not _capability_is_current(capability, now):
            raise _WorkerFault("INPUT_CAPABILITY_EXPIRED")

    identity = _capability_input(capability)
    descriptor: int | None = None
    reader: DeadlineBoundedByteReaderPort | None = None
    try:
        require_download_current()
        reader = source.open_bound_bytes(
            identity,
            deadline=deadline,
            wait_is_current=download_is_current,
            heartbeat_interval_millis=25,
        )
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600,
        )
        digest = hashlib.sha256()
        remaining = capability.observed_size_bytes
        while remaining:
            require_download_current()
            chunk = reader.read_chunk(
                min(remaining, max_chunk_bytes),
                deadline=deadline,
                wait_is_current=download_is_current,
                heartbeat_interval_millis=25,
            )
            if not chunk or len(chunk) > remaining:
                raise _WorkerFault("INPUT_BYTE_STREAM_INVALID")
            written = 0
            while written < len(chunk):
                count = os.write(descriptor, chunk[written:])
                if count <= 0:
                    raise _WorkerFault("INPUT_WORKSPACE_UNAVAILABLE")
                written += count
            digest.update(chunk)
            remaining -= len(chunk)
        require_download_current()
        if reader.read_chunk(
            1,
            deadline=deadline,
            wait_is_current=download_is_current,
            heartbeat_interval_millis=25,
        ):
            raise _WorkerFault("INPUT_BYTE_STREAM_INVALID")
        actual_digest = "sha256:" + digest.hexdigest()
        if (
            actual_digest != capability.observed_sha256
            or os.fstat(descriptor).st_size != capability.observed_size_bytes
        ):
            raise _WorkerFault("INPUT_BYTE_STREAM_INVALID")
    except ProtocolViolation:
        if not _capability_is_current(capability, now):
            raise _WorkerFault("INPUT_CAPABILITY_EXPIRED") from None
        raise
    finally:
        if reader is not None:
            reader.close()
        if descriptor is not None:
            os.close(descriptor)


def _failure(
    *, attempt: AnalysisExecutionAttemptV2, analysis_id: str, reason: str, failed_at: datetime
) -> RelativeVolumeCalculationFailureV2:
    failure_id = "failure-" + hashlib.sha256(
        (analysis_id + attempt.canonical_digest()).encode("utf-8")
    ).hexdigest()[:32]
    return RelativeVolumeCalculationFailureV2(
        failure_id=failure_id,
        attempt=attempt,
        attempt_digest=attempt.canonical_digest(),
        reason_code=reason,
        failed_at=failed_at,
    ).sealed()


def _reseal_report(
    report: RelativeVolumeCalculationReportV2,
    *,
    attempt: AnalysisExecutionAttemptV2,
    reported_at: datetime,
) -> RelativeVolumeCalculationReportV2:
    if reported_at < report.computed_at or reported_at > attempt.lease_expires_at:
        raise _WorkerFault("WORKER_CLOCK_INVALID")
    return RelativeVolumeCalculationReportV2(
        report_id=report.report_id,
        attempt=attempt,
        attempt_digest=attempt.canonical_digest(),
        numeric_result=report.numeric_result,
        numeric_result_identity_digest=report.numeric_result_identity_digest,
        computed_at=report.computed_at,
        reported_at=reported_at,
    ).sealed()


def _failure_reason(exception: BaseException) -> str:
    if isinstance(exception, _WorkerFault):
        return exception.code
    if isinstance(exception, ExternalObjectTransportError):
        return "INPUT_OBJECT_TRANSPORT_FAILED"
    if isinstance(exception, ProtocolDeadlineExceeded):
        return "MEASUREMENT_INCOMPLETE"
    if isinstance(exception, ProtocolViolation):
        return "INPUT_OBJECT_TRANSPORT_FAILED"
    if isinstance(exception, OSError):
        return "INPUT_WORKSPACE_UNAVAILABLE"
    return "WORKER_EXECUTION_FAILED"


def _record_failure(
    *,
    client: ExternalAnalysisCoreClient,
    keeper: _LeaseKeeper,
    analysis_id: str,
    reason: str,
    now: Callable[[], datetime],
) -> None:
    try:
        attempt = keeper.renew()
        failed_at = _utc_now(now)
        if failed_at > attempt.lease_expires_at:
            return
        client.failure(
            analysis_id,
            _failure(attempt=attempt, analysis_id=analysis_id, reason=reason, failed_at=failed_at),
        )
    except (_LeaseLost, ExternalAnalysisCoreClientError, _WorkerFault):
        return


def run_once(
    client: ExternalAnalysisCoreClient,
    runtime_identity: ProcessingWorkerRuntimeIdentityV1,
    transport_policy: ExternalObjectTransportPolicyV1,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> bool:
    """Attempt one pending job sequentially; a lost fence is never reacquired here."""
    if not isinstance(client, ExternalAnalysisCoreClient):
        raise TypeError("client must be an ExternalAnalysisCoreClient")
    if not isinstance(runtime_identity, ProcessingWorkerRuntimeIdentityV1):
        raise TypeError("runtime_identity must be a ProcessingWorkerRuntimeIdentityV1")
    if not isinstance(transport_policy, ExternalObjectTransportPolicyV1):
        raise TypeError("transport_policy must be an ExternalObjectTransportPolicyV1")
    try:
        pending = client.list_pending()
    except ExternalAnalysisCoreClientError:
        return False
    for item in pending:
        try:
            lease = client.lease(item.analysis_id, str(uuid.uuid4()))
        except ExternalAnalysisCoreClientError as exc:
            if exc.code in {"CORE_HTTP_404", "CORE_HTTP_409"}:
                continue
            return False
        if lease.calculation_request_id != item.calculation_request_id:
            return True
        keeper = _LeaseKeeper(client=client, analysis_id=item.analysis_id, lease=lease)
        try:
            input_value = client.input(item.analysis_id, keeper.attempt).input
            if input_value.calculation_request_id != lease.calculation_request_id:
                raise _WorkerFault("WORKER_INPUT_BINDING_MISMATCH")
            if not runtime_identity.matches(input_value.calculation_identity):
                raise _WorkerFault("RUNTIME_IDENTITY_MISMATCH")
            _resource_limits(input_value)
            started_at = _utc_now(now)
            if any(capability.expires_at <= started_at for capability in input_value.inputs):
                raise _WorkerFault("INPUT_CAPABILITY_EXPIRED")
            capabilities = tuple(
                ExternalObjectCapabilityV1(
                    artifact=_capability_input(capability),
                    url=capability.download_url,
                    required_headers=capability.required_headers,
                )
                for capability in input_value.inputs
            )
            source = ExternalObjectHttpByteSource(capabilities, policy=transport_policy)
            max_deadline_seconds = (
                input_value.attempt.authorization.resource_envelope.max_deadline_seconds
            )
            if not math.isfinite(max_deadline_seconds) or max_deadline_seconds <= 0:
                raise _WorkerFault("RESOURCE_LIMIT_EXCEEDED")
            duration_millis = int(max_deadline_seconds * 1000)
            if duration_millis <= 0:
                raise _WorkerFault("RESOURCE_LIMIT_EXCEEDED")
            execution_deadline = ProtocolDeadline(duration_millis, time.monotonic)
            with tempfile.TemporaryDirectory(prefix="ksi-analysis-") as workspace:
                workspace_path = Path(workspace)
                baseline_path = workspace_path / "baseline.tif"
                current_path = workspace_path / "current.tif"
                _private_download(
                    source=source,
                    capability=input_value.inputs[0],
                    path=baseline_path,
                    deadline=execution_deadline,
                    keeper=keeper,
                    max_chunk_bytes=transport_policy.max_chunk_bytes,
                    now=now,
                )
                _private_download(
                    source=source,
                    capability=input_value.inputs[1],
                    path=current_path,
                    deadline=execution_deadline,
                    keeper=keeper,
                    max_chunk_bytes=transport_policy.max_chunk_bytes,
                    now=now,
                )
                attempt = keeper.renew()
                computed_at = _utc_now(now)
                remaining_wall_seconds = execution_deadline.remaining()
                lease_seconds = (attempt.lease_expires_at - attempt.issued_at).total_seconds()
                heartbeat = _LeaseHeartbeat(
                    keeper,
                    interval_seconds=max(
                        0.01,
                        min(1.0, lease_seconds / 3, remaining_wall_seconds / 3),
                    ),
                )

                heartbeat.start()
                try:
                    measured = measure_external_relative_volume_v2(
                        attempt=attempt,
                        calculation_identity=input_value.calculation_identity,
                        baseline_path=baseline_path,
                        current_path=current_path,
                        report_id="report-"
                        + hashlib.sha256(item.analysis_id.encode("utf-8")).hexdigest()[:32],
                        computed_at=computed_at,
                        reported_at=computed_at,
                        maximum_wall_seconds=remaining_wall_seconds,
                        is_cancelled=heartbeat.is_lost,
                    )
                finally:
                    joined = heartbeat.stop_and_join()
                if not joined or heartbeat.lost:
                    return True
                execution_deadline.remaining()
            final_attempt = keeper.renew()
            if isinstance(measured, RelativeVolumeCalculationFailureV2):
                failed_at = _utc_now(now)
                if failed_at > final_attempt.lease_expires_at:
                    return True
                client.failure(
                    item.analysis_id,
                    _failure(
                        attempt=final_attempt,
                        analysis_id=item.analysis_id,
                        reason=measured.reason_code,
                        failed_at=failed_at,
                    ),
                )
                return True
            reported_at = _utc_now(now)
            execution_deadline.remaining()
            sealed_report = _reseal_report(
                measured,
                attempt=final_attempt,
                reported_at=reported_at,
            )
            serialized_report = sealed_report.model_dump_json(by_alias=True).encode("utf-8")
            if (
                len(serialized_report)
                > final_attempt.authorization.resource_envelope.max_output_bytes
            ):
                raise _WorkerFault("RESOURCE_LIMIT_EXCEEDED")
            client.report(item.analysis_id, sealed_report)
            return True
        except _LeaseLost:
            return True
        except ExternalAnalysisCoreClientError as exc:
            _record_failure(
                client=client,
                keeper=keeper,
                analysis_id=item.analysis_id,
                reason="CORE_WORKER_OPERATION_FAILED",
                now=now,
            )
            if exc.code in {"CORE_HTTP_404", "CORE_HTTP_409"}:
                return True
            return True
        except Exception as exc:
            _record_failure(
                client=client,
                keeper=keeper,
                analysis_id=item.analysis_id,
                reason=_failure_reason(exc),
                now=now,
            )
            return True
    return False


def poll(
    client: ExternalAnalysisCoreClient,
    runtime_identity: ProcessingWorkerRuntimeIdentityV1,
    transport_policy: ExternalObjectTransportPolicyV1,
    *,
    poll_interval_seconds: float,
    should_stop: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Run sequentially until the caller requests stop; no parallel lease ownership exists."""
    if (
        isinstance(poll_interval_seconds, bool)
        or not math.isfinite(poll_interval_seconds)
        or poll_interval_seconds <= 0
    ):
        raise ValueError("poll interval must be a positive finite duration")
    while not should_stop():
        if not run_once(client, runtime_identity, transport_policy, now=now):
            sleep(poll_interval_seconds)


__all__ = ["ProcessingWorkerRuntimeIdentityV1", "poll", "run_once"]
