"""단면 작업 한 건: 봉인된 바이트 확인, 파일 사실 재대조, 한도 있는 계산, receipt 보고.

Core가 준 원본 capability로 바이트를 받아 길이와 SHA-256을 대조한 뒤에만 래스터를 연다.
계산은 `read_surface_profile` 하나를 호출하며 한도를 넓히지 않는다. 이 프로세스는 OS 수준
격리(자원 제한·네임스페이스)를 제공하지 않는다. 시간·메모리·동시성 한도는 별도 증거가 필요하다.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import cast, get_args
from uuid import uuid4

from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.surface_profile import (
    CreateSurfaceProfileV1,
    SurfaceProfileRefusalV1,
    SurfaceProfileResultV1,
)
from ksi_event_contracts.surface_profile_job import (
    SurfaceProfileAttemptV1,
    SurfaceProfileFrozenJobV1,
    SurfaceProfileJobReasonV1,
    SurfaceProfileReceiptV1,
)
from ksi_geo_spatial.crs import normalise_crs
from ksi_geo_spatial.surface_profile import (
    SurfaceProfileError,
    SurfaceProfilePolicy,
    inspect_profile_source,
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
)
from ksi_processing_controller.spatial_data_worker_config import (
    SpatialDataWorkerConfigError,
    require_owner_private_directory,
)
from ksi_processing_controller.surface_profile_core_client import (
    SurfaceProfileCoreClient,
    SurfaceProfileCoreClientError,
)
from ksi_processing_controller.surface_profile_worker import read_surface_profile


class SurfaceProfileWorkerError(RuntimeError):
    def __init__(self, reason: SurfaceProfileJobReasonV1) -> None:
        self.reason = reason
        super().__init__(reason)


class _LeaseGuard:
    def __init__(
        self,
        core: SurfaceProfileCoreClient,
        attempt: SurfaceProfileAttemptV1,
        job: SurfaceProfileFrozenJobV1,
        clock: Callable[[], datetime],
        heartbeat_millis: int,
    ) -> None:
        self.core, self.attempt, self.job, self.clock = core, attempt, job, clock
        self.interval = heartbeat_millis / 1000
        self.next_check = 0.0
        self.lost = False

    def check(self, *, force: bool = False) -> bool:
        if self.lost:
            return False
        try:
            # 만료 상한만 지역에서 본다. acquired_at은 Core 시계가 찍으므로 시계 오차로 방금 받은
            # lease를 거부하지 않는다. 권위 있는 만료 판단은 Core가 매 호출에서 한다.
            if not self.clock() < min(
                self.attempt.lease_until, self.job.deadline, self.job.grant.valid_until
            ):
                raise SurfaceProfileWorkerError("LEASE_EXPIRED")
            if force or monotonic() >= self.next_check:
                renewed = self.core.renew(attempt=self.attempt)
                if renewed.fence_digest() != self.attempt.fence_digest():
                    raise SurfaceProfileWorkerError("FENCE_CONFLICT")
                self.attempt = renewed
                self.next_check = monotonic() + self.interval
            return True
        except (SurfaceProfileCoreClientError, SurfaceProfileWorkerError, ValueError, OSError):
            self.lost = True
            return False

    def require(self, *, force: bool = False) -> None:
        if not self.check(force=force):
            raise SurfaceProfileWorkerError("CURRENTNESS_UNAVAILABLE")


def _same_file_facts(job: SurfaceProfileFrozenJobV1, staged: Path) -> None:
    """받은 파일에서 다시 읽은 사실이 봉인된 측정값과 같아야 한다. 검사 보고서는 파일이 아니다."""
    measured = job.source.inspection.measurements
    if measured is None:
        raise SurfaceProfileWorkerError("SOURCE_MEASUREMENTS_MISMATCH")
    try:
        facts = inspect_profile_source(staged)
        a, b, _, d, e, _ = measured.transform
        if (
            facts.width != measured.width
            or facts.height != measured.height
            or (b, d) != (0.0, 0.0)
            or (facts.cell_size_x, facts.cell_size_y) != (a, -e)
            or facts.horizontal_crs != normalise_crs(measured.observed_crs_identifier)
        ):
            raise SurfaceProfileWorkerError("SOURCE_MEASUREMENTS_MISMATCH")
    except SurfaceProfileError as exc:
        raise SurfaceProfileWorkerError(exc.reason.value) from exc


def _receipt(
    job: SurfaceProfileFrozenJobV1, result: SurfaceProfileResultV1, now: datetime
) -> SurfaceProfileReceiptV1:
    measured = job.source.inspection.measurements
    assert measured is not None
    return SurfaceProfileReceiptV1(
        job_id=job.job_id,
        job_digest=job.job_digest or "",
        source_digest=job.source.source_digest or "",
        request_digest=job.request_fingerprint,
        grant_digest=job.grant.grant_digest or "",
        data_policy_digest=job.data_policy_digest,
        policy_digest=job.policy.policy_digest or "",
        runtime_digest=job.runtime.runtime_digest or "",
        artifact_id=job.source.artifact_id,
        source_sha256=job.source.observed_sha256,
        source_size_bytes=job.source.observed_size_bytes,
        observed_crs_identifier=measured.observed_crs_identifier,
        observed_crs_digest=measured.observed_crs_digest,
        vertical_reference=job.vertical_reference,
        result_digest=result.result_digest or "",
        read_window=job.read_window,
        window_cells_read=result.window_cells_read,
        accuracy_assessed=False,
        prepared_at=now,
        attribution="KSI 단면 일꾼: 봉인된 원본 바이트를 한도 안에서 읽은 결과",
        limitations=("선을 따라 읽은 등록 격자의 값이며 측량 성과나 정확도 평가가 아니다.",),
    ).sealed()


def run_once(
    *,
    core: SurfaceProfileCoreClient,
    transport_policy: ExternalObjectTransportPolicyV1,
    clock: Callable[[], datetime],
    workspace_root: Path,
    heartbeat_millis: int,
) -> bool:
    """대기 중인 작업을 최대 한 건 시도한다. true는 시도했다는 뜻이며 성공을 뜻하지 않는다."""
    job_ids = core.pending(limit=1)
    if not job_ids:
        return False
    attempt = core.lease(job_id=job_ids[0], acquisition_id=str(uuid4()))
    guard: _LeaseGuard | None = None
    phase = "source"
    try:
        info = core.input(attempt=attempt)
        job = info.job
        guard = _LeaseGuard(core, attempt, job, clock, heartbeat_millis)
        envelope = job.policy.resource_envelope
        if not 0 < heartbeat_millis / 1000 < job.policy.lease_seconds / 3:
            raise SurfaceProfileWorkerError("RESOURCE_LIMIT_EXCEEDED")
        guard.require(force=True)
        try:
            require_owner_private_directory(workspace_root)
        except SpatialDataWorkerConfigError as exc:
            raise SurfaceProfileWorkerError("STORAGE_UNAVAILABLE") from exc
        cap = info.source_capability
        if cap.observed_size_bytes > min(envelope.max_input_bytes, envelope.max_streamed_bytes):
            raise SurfaceProfileWorkerError("RESOURCE_LIMIT_EXCEEDED")
        seconds = min((job.deadline - clock()).total_seconds(), envelope.max_deadline_seconds)
        with tempfile.TemporaryDirectory(prefix=".ksi-profile-", dir=workspace_root) as directory:
            staged = Path(directory) / "source.tif"
            artifact = ExternalArtifactInputV1(
                entry_id=job.source.artifact_id,
                observed_sha256=cap.observed_sha256,
                observed_size_bytes=cap.observed_size_bytes,
                kind=ProcessingArtifactKind(job.source.artifact_kind),
                content_type="image/tiff",
            )
            capability = ExternalObjectCapabilityV1(
                artifact=artifact,
                url=cap.download_url,
                required_headers={
                    k: v for k, v in cap.header_mapping().items() if k.lower() != "content-length"
                },
            )
            source = ExternalObjectHttpByteSource((capability,), policy=transport_policy)
            deadline = ProtocolDeadline(
                max(1, int(min(seconds, (cap.expires_at - clock()).total_seconds()) * 1000)),
                monotonic,
            )
            reader = source.open_bound_bytes(
                artifact,
                deadline=deadline,
                wait_is_current=guard.check,
                heartbeat_interval_millis=heartbeat_millis,
            )
            try:
                hashed, received = hashlib.sha256(), 0
                with staged.open("xb") as sink:
                    staged.chmod(0o600)
                    while True:
                        chunk = reader.read_chunk(
                            min(transport_policy.max_chunk_bytes, 65536),
                            deadline=deadline,
                            wait_is_current=guard.check,
                            heartbeat_interval_millis=heartbeat_millis,
                        )
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > cap.observed_size_bytes:
                            raise SurfaceProfileWorkerError("SOURCE_BYTES_MISMATCH")
                        sink.write(chunk)
                        hashed.update(chunk)
                if (
                    received != cap.observed_size_bytes
                    or "sha256:" + hashed.hexdigest() != cap.observed_sha256
                ):
                    raise SurfaceProfileWorkerError("SOURCE_BYTES_MISMATCH")
            finally:
                reader.close()
            guard.require(force=True)
            phase = "compute"
            _same_file_facts(job, staged)
            policy = job.policy
            outcome = read_surface_profile(
                CreateSurfaceProfileV1(
                    asset_ref=job.profile_request.asset_ref,
                    line=job.profile_request.line,
                    feature=job.profile_request.feature,
                    sample_spacing_m=job.profile_request.sample_spacing_m,
                ),
                staged,
                policy=SurfaceProfilePolicy(
                    maximum_vertices=policy.maximum_vertices,
                    maximum_samples=policy.maximum_samples,
                    maximum_line_length_m=policy.maximum_line_length_m,
                    maximum_window_cells=policy.maximum_window_cells,
                    maximum_source_block_cells=policy.maximum_source_block_cells,
                ),
            )
            if isinstance(outcome, SurfaceProfileRefusalV1):
                raise SurfaceProfileWorkerError(cast(SurfaceProfileJobReasonV1, outcome.reason))
            guard.require(force=True)
            receipt = _receipt(job, outcome, max(clock(), guard.attempt.acquired_at))
            phase = "report"
            core.complete(attempt=guard.attempt, result=outcome, receipt=receipt)
    except Exception as exc:
        if guard is not None and guard.lost:
            return True
        if isinstance(exc, SurfaceProfileWorkerError):
            reason: str = exc.reason
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
            reason = "STORAGE_UNAVAILABLE"
        elif isinstance(exc, (ProtocolViolation, SurfaceProfileCoreClientError)):
            reason = "INTEGRITY_MISMATCH" if phase != "report" else "WORKER_FAILED"
        else:
            reason = "WORKER_FAILED"
        if reason not in get_args(SurfaceProfileJobReasonV1):
            reason = "WORKER_FAILED"
        current = guard.attempt if guard is not None else attempt
        # 보고 단계에서 Core 통신이 실패하면 실패 보고도 못 할 수 있다. 완료를 꾸며내지 않는다.
        with suppress(SurfaceProfileCoreClientError, ValueError, OSError):
            core.failure(attempt=current, reason=cast(SurfaceProfileJobReasonV1, reason))
    return True
