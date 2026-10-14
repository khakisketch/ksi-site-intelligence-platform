"""One fenced data preparation: private bytes, trusted transport, no parent raster decoding."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Protocol, cast, get_args
from uuid import uuid4

from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.spatial_data import (
    SpatialDataAttemptV1,
    SpatialDataFrozenJobV1,
    SpatialDataReasonV1,
    SpatialDataReceiptV1,
)
from ksi_event_contracts.spatial_data_worker import SpatialDataUploadDeclarationV1
from ksi_geo_spatial.external_native_window_geometry import (
    NativeWindowError,
    plan_external_native_window,
)

from ksi_processing_controller.external_artifact_inspection_worker import ExternalArtifactInputV1
from ksi_processing_controller.external_inspector_protocol import (
    ProtocolDeadline,
    ProtocolDeadlineExceeded,
    ProtocolViolation,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectCapabilityV1,
    ExternalObjectHttpByteSource,
    ExternalObjectTransportError,
    ExternalObjectTransportPolicyV1,
    SealedObjectByteSourceV1,
)
from ksi_processing_controller.spatial_data_core_client import (
    SpatialDataCoreClient,
    SpatialDataCoreClientError,
)
from ksi_processing_controller.spatial_data_worker_config import (
    SpatialDataWorkerConfigError,
    require_owner_private_directory,
)


class SpatialDataSandboxPort(Protocol):
    def prepare(
        self,
        *,
        job: SpatialDataFrozenJobV1,
        source_path: Path,
        output_parent: Path,
        is_current: Callable[[], bool],
    ) -> SpatialDataReceiptV1: ...


class SpatialDataWorkerError(RuntimeError):
    def __init__(self, reason: SpatialDataReasonV1) -> None:
        self.reason = reason
        super().__init__(reason)


class _LeaseGuard:
    def __init__(
        self,
        core: SpatialDataCoreClient,
        attempt: SpatialDataAttemptV1,
        job: SpatialDataFrozenJobV1,
        clock: Callable[[], datetime],
        heartbeat: int,
    ):
        self.core, self.attempt, self.job, self.clock = core, attempt, job, clock
        self.interval = heartbeat / 1000
        self.next_check = 0.0
        self.lost = False

    def check(self, *, force: bool = False) -> bool:
        if self.lost:
            return False
        try:
            now = self.clock()
            # Only expiry bounds are locally checkable; acquired_at is stamped by
            # the Core clock and must not fence a fresh lease under negative skew.
            # The Core refuses any use past its own authoritative bounds.
            if not now < min(
                self.attempt.lease_until, self.job.deadline, self.job.grant.valid_until
            ):
                raise SpatialDataWorkerError("LEASE_EXPIRED")
            if force or monotonic() >= self.next_check:
                renewed = self.core.renew(attempt=self.attempt)
                if renewed.fence_digest() != self.attempt.fence_digest():
                    raise SpatialDataWorkerError("FENCE_CONFLICT")
                self.attempt = renewed
                self.next_check = monotonic() + self.interval
            return True
        except (SpatialDataCoreClientError, SpatialDataWorkerError, ValueError, OSError):
            self.lost = True
            return False

    def require(self, *, force: bool = False) -> None:
        if not self.check(force=force):
            raise SpatialDataWorkerError("CURRENTNESS_UNAVAILABLE")


def _artifact(entry_id: str, sha256: str, size: int, kind: str) -> ExternalArtifactInputV1:
    return ExternalArtifactInputV1(
        entry_id=entry_id,
        observed_sha256=sha256,
        observed_size_bytes=size,
        kind=ProcessingArtifactKind(kind),
        content_type="image/tiff",
    )


def _capability(
    artifact: ExternalArtifactInputV1, url: str, headers: dict[str, str]
) -> ExternalObjectCapabilityV1:
    # This transport generates Content-Length from the sealed identity. Retain the
    # checksum/type authority and do not forward bearer/cookies/Host to object origins.
    return ExternalObjectCapabilityV1(
        artifact=artifact,
        url=url,
        required_headers={k: v for k, v in headers.items() if k.lower() != "content-length"},
    )


class _PrivateFileReader:
    """Bounded local descriptor reads, never a whole-output allocation."""

    def __init__(self, path: Path, maximum: int):
        self.fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        self.before = os.fstat(self.fd)
        if (
            not stat.S_ISREG(self.before.st_mode)
            or self.before.st_uid != os.geteuid()
            or stat.S_IMODE(self.before.st_mode) != 0o600
            or self.before.st_nlink != 1
            or not 0 < self.before.st_size <= maximum
        ):
            self.close()
            raise SpatialDataWorkerError("OUTPUT_VERIFICATION_FAILED")

    def read_chunk(
        self,
        maximum_bytes: int,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> bytes:
        deadline.remaining()
        if wait_is_current is None or wait_is_current() is not True:
            raise SpatialDataWorkerError("CURRENTNESS_UNAVAILABLE")
        chunk = os.read(self.fd, maximum_bytes)
        after = os.fstat(self.fd)
        if (
            self.before.st_dev,
            self.before.st_ino,
            self.before.st_size,
            self.before.st_mtime_ns,
            self.before.st_ctime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise SpatialDataWorkerError("OUTPUT_VERIFICATION_FAILED")
        deadline.remaining()
        if wait_is_current() is not True:
            raise SpatialDataWorkerError("CURRENTNESS_UNAVAILABLE")
        return chunk

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


def _receipt_matches(job: SpatialDataFrozenJobV1, receipt: SpatialDataReceiptV1) -> bool:
    source = job.source
    m = source.inspection.measurements
    assert m is not None
    geometry = plan_external_native_window(
        requested_bounds=job.request.requested_bounds,
        measurements=m,
        requested_crs_digest=job.request.observed_crs_digest,
    )
    return (
        receipt.receipt_digest == receipt.canonical_digest()
        and (
            receipt.job_id,
            receipt.job_digest,
            receipt.source_digest,
            receipt.request_digest,
            receipt.runtime_digest,
            receipt.policy_digest,
            receipt.grant_digest,
        )
        == (
            job.job_id,
            job.job_digest,
            source.source_digest,
            job.request.canonical_digest(),
            job.runtime.runtime_digest,
            job.policy.policy_digest,
            job.grant.grant_digest,
        )
        and (
            receipt.artifact_id,
            receipt.artifact_kind,
            receipt.source_sha256,
            receipt.source_size_bytes,
        )
        == (
            source.artifact_id,
            source.artifact_kind,
            source.observed_sha256,
            source.observed_size_bytes,
        )
        and (
            receipt.requested_bounds,
            receipt.requested_crs_digest,
            receipt.actual_bounds,
            receipt.pixel_window,
            receipt.transform,
        )
        == (
            job.request.requested_bounds,
            job.request.observed_crs_digest,
            geometry.actual_bounds,
            geometry.pixel_window,
            geometry.transform,
        )
        and (
            receipt.source_transform,
            receipt.source_resolution,
            receipt.observed_crs_identifier,
            receipt.observed_crs_digest,
            receipt.observed_vertical_reference,
            receipt.band_count,
            receipt.dtype,
            receipt.nodata_representation,
            receipt.nodata_value,
        )
        == (
            m.transform,
            (m.transform[0], -m.transform[4]),
            m.observed_crs_identifier,
            m.observed_crs_digest,
            m.observed_vertical_reference,
            m.band_count,
            m.dtype,
            m.nodata_representation,
            m.nodata_value,
        )
        and receipt.attribution == job.grant.attribution
        and (
            receipt.declaration_recorded_at,
            receipt.capture_started_at,
            receipt.capture_ended_at,
            receipt.producer_processed_at,
        )
        == (
            source.declaration_recorded_at,
            source.capture_started_at,
            source.capture_ended_at,
            source.producer_processed_at,
        )
        and receipt.accuracy_assessed is False
        and receipt.output_size_bytes <= job.policy.max_output_bytes
        and receipt.width * receipt.height <= job.policy.max_output_pixels
    )


def run_once(
    *,
    core: SpatialDataCoreClient,
    sandbox: SpatialDataSandboxPort,
    transport_policy: ExternalObjectTransportPolicyV1,
    worker_instance_id: str,
    clock: Callable[[], datetime],
    workspace_root: Path,
    heartbeat_interval_millis: int,
) -> bool:
    """Attempt at most one pending job; true means attempted, not successful publication.

    Transport/child ports own cancellable waits. Local filesystem I/O and Core HTTP
    phase timeouts are not hard host containment or arbitrary-I/O deadline evidence.
    """
    jobs = core.pending(limit=1)
    if not jobs:
        return False
    job = SpatialDataFrozenJobV1.model_validate(jobs[0].model_dump())
    if job.job_digest != job.canonical_digest():
        raise SpatialDataWorkerError("INTEGRITY_MISMATCH")
    env = job.policy.resource_envelope
    if (
        type(heartbeat_interval_millis) is not int
        or not 0 < heartbeat_interval_millis / 1000 < job.policy.lease_seconds / 3
    ):
        raise SpatialDataWorkerError("INVALID_RESOURCE_LIMIT")
    attempt = core.lease(job_id=job.job_id, acquisition_id=str(uuid4()))
    if (
        attempt.worker_instance_id != worker_instance_id
        or attempt.frozen_job_digest != job.job_digest
    ):
        raise SpatialDataWorkerError("FENCE_CONFLICT")
    guard = _LeaseGuard(core, attempt, job, clock, heartbeat_interval_millis)
    phase = "source"
    try:
        guard.require(force=True)
        info = core.input(attempt=guard.attempt)
        if info.job != job:
            raise SpatialDataWorkerError("INTEGRITY_MISMATCH")
        try:
            require_owner_private_directory(workspace_root)
        except SpatialDataWorkerConfigError as exc:
            raise SpatialDataWorkerError("PRIVATE_WORKSPACE_UNAVAILABLE") from exc
        if job.source.observed_size_bytes > min(env.max_input_bytes, env.max_streamed_bytes):
            raise SpatialDataWorkerError("INPUT_BYTE_LIMIT_EXCEEDED")
        seconds = min((job.deadline - clock()).total_seconds(), env.max_deadline_seconds)
        deadline = ProtocolDeadline(max(1, int(seconds * 1000)), monotonic)
        with tempfile.TemporaryDirectory(prefix=".ksi-data-", dir=workspace_root) as directory:
            private = Path(directory)
            staged = private / "source.tif"
            cap = info.source_capability
            artifact = _artifact(
                job.source.artifact_id,
                cap.observed_sha256,
                cap.observed_size_bytes,
                job.source.artifact_kind,
            )
            capability = _capability(artifact, cap.download_url, cap.header_mapping())
            source = ExternalObjectHttpByteSource((capability,), policy=transport_policy)
            source_deadline = ProtocolDeadline(
                max(1, int(min(seconds, (cap.expires_at - clock()).total_seconds()) * 1000)),
                monotonic,
            )
            reader = source.open_bound_bytes(
                artifact,
                deadline=source_deadline,
                wait_is_current=guard.check,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
            try:
                hashed, received = hashlib.sha256(), 0
                with staged.open("xb") as sink:
                    staged.chmod(0o600)
                    while True:
                        chunk = reader.read_chunk(
                            min(transport_policy.max_chunk_bytes, job.policy.stream_chunk_bytes),
                            deadline=source_deadline,
                            wait_is_current=guard.check,
                            heartbeat_interval_millis=heartbeat_interval_millis,
                        )
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > min(
                            cap.observed_size_bytes, env.max_input_bytes, env.max_streamed_bytes
                        ):
                            raise SpatialDataWorkerError("INPUT_BYTE_LIMIT_EXCEEDED")
                        sink.write(chunk)
                        hashed.update(chunk)
                if (
                    received != cap.observed_size_bytes
                    or "sha256:" + hashed.hexdigest() != cap.observed_sha256
                ):
                    raise SpatialDataWorkerError("SOURCE_BYTES_MISMATCH")
            finally:
                reader.close()
            guard.require(force=True)
            phase = "prepare"
            receipt = SpatialDataReceiptV1.model_validate(
                sandbox.prepare(
                    job=job, source_path=staged, output_parent=private, is_current=guard.check
                ).model_dump()
            )
            guard.require(force=True)
            if not _receipt_matches(job, receipt):
                raise SpatialDataWorkerError("OUTPUT_VERIFICATION_FAILED")
            candidate = private / "candidate.tif"
            reader = _PrivateFileReader(candidate, job.policy.max_output_bytes)
            try:
                hashed, received = hashlib.sha256(), 0
                while True:
                    chunk = reader.read_chunk(
                        job.policy.stream_chunk_bytes,
                        deadline=deadline,
                        wait_is_current=guard.check,
                        heartbeat_interval_millis=heartbeat_interval_millis,
                    )
                    if not chunk:
                        break
                    hashed.update(chunk)
                    received += len(chunk)
                if (
                    received != receipt.output_size_bytes
                    or "sha256:" + hashed.hexdigest() != receipt.output_sha256
                ):
                    raise SpatialDataWorkerError("OUTPUT_VERIFICATION_FAILED")
            finally:
                reader.close()
            guard.require(force=True)
            declaration = SpatialDataUploadDeclarationV1(
                attempt=guard.attempt,
                receipt=receipt,
                sha256=receipt.output_sha256,
                size_bytes=receipt.output_size_bytes,
                content_type="image/tiff",
            ).sealed()
            upload = core.output_upload(declaration=declaration)
            upload_capability = upload.capability
            phase = "upload"
            upload_artifact = _artifact(
                job.job_id,
                receipt.output_sha256,
                receipt.output_size_bytes,
                job.source.artifact_kind,
            )
            upload_cap = _capability(
                upload_artifact, upload_capability.upload_url, upload_capability.header_mapping()
            )
            output = ExternalObjectHttpByteSource((upload_cap,), policy=transport_policy)
            reader = _PrivateFileReader(candidate, job.policy.max_output_bytes)
            try:
                upload_deadline = ProtocolDeadline(
                    max(
                        1,
                        int(
                            min(
                                (upload_capability.expires_at - clock()).total_seconds(),
                                (job.deadline - clock()).total_seconds(),
                            )
                            * 1000
                        ),
                    ),
                    monotonic,
                )
                observed = output.put_bound_bytes(
                    upload_cap,
                    SealedObjectByteSourceV1(upload_artifact, reader),
                    deadline=upload_deadline,
                    wait_is_current=guard.check,
                    heartbeat_interval_millis=heartbeat_interval_millis,
                )
                if (observed.observed_sha256, observed.observed_size_bytes) != (
                    receipt.output_sha256,
                    receipt.output_size_bytes,
                ):
                    raise SpatialDataWorkerError("INTEGRITY_MISMATCH")
            finally:
                reader.close()
            guard.require(force=True)
            core.complete(attempt=guard.attempt, upload_digest=upload.upload_digest)
    except Exception as exc:
        if guard.lost:
            return True
        if isinstance(exc, (SpatialDataWorkerError, NativeWindowError)):
            reason = exc.reason
        elif isinstance(exc, ProtocolDeadlineExceeded):
            reason = "DEADLINE_EXCEEDED"
        elif isinstance(exc, ExternalObjectTransportError) and exc.code == "OBJECT_DIGEST_MISMATCH":
            reason = "SOURCE_BYTES_MISMATCH"
        elif isinstance(exc, ExternalObjectTransportError) and exc.code not in {
            "CONNECT_FAILED",
            "SOCKET_READ_FAILED",
            "SOCKET_WRITE_FAILED",
        }:
            reason = "INTEGRITY_MISMATCH"
        elif isinstance(exc, (ExternalObjectTransportError, OSError)):
            reason = "SOURCE_UNAVAILABLE" if phase == "source" else "STORAGE_UNAVAILABLE"
        elif isinstance(exc, ProtocolViolation):
            reason = "INTEGRITY_MISMATCH"
        else:
            reason = "RASTER_PREPARATION_FAILED"
        if guard.check(force=True):
            if reason not in get_args(SpatialDataReasonV1):
                reason = "RASTER_PREPARATION_FAILED"
            # Core retains the lease/cleanup obligation; never invent completion.
            with suppress(SpatialDataCoreClientError, ValueError, OSError):
                core.failure(attempt=guard.attempt, reason=cast(SpatialDataReasonV1, reason))
    return True
