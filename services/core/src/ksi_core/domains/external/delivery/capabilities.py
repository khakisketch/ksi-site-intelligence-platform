"""Worker-only storage authority: reservation first, currentness repeated after every I/O."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlsplit

from ksi_event_contracts.spatial_data import SpatialDataAttemptV1, SpatialDataJobViewV1
from ksi_event_contracts.spatial_data_authority import SpatialDataActivationV1
from ksi_event_contracts.spatial_data_worker import (
    SpatialDataOutputUploadViewV1,
    SpatialDataUploadCapabilityV1,
    SpatialDataUploadDeclarationV1,
    SpatialDataWorkerInputV1,
)

from ksi_core.domains.external.delivery.credential_currentness import (
    SpatialDataCredentialCurrentness,
)
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.jobs import SpatialDataJobStore
from ksi_core.domains.external.delivery.storage import SpatialDataStoragePort
from ksi_core.identity.auth import Principal


class SpatialDataWorkerCapabilities:
    def __init__(
        self,
        *,
        jobs: SpatialDataJobStore,
        storage: SpatialDataStoragePort,
        activation: SpatialDataActivationV1,
        clock: Callable[[], datetime],
    ) -> None:
        activation = SpatialDataActivationV1.model_validate(activation.__dict__)
        if (
            activation.activation_digest != activation.canonical_digest()
            or activation != jobs.activation
            or not callable(clock)
        ):
            raise ValueError(
                "worker capabilities require exact authorized job activation and clock"
            )
        self.jobs = jobs
        self.storage = storage
        self.activation = activation.model_copy(deep=True)
        self.clock = clock

    def input(
        self,
        *,
        job_id: str,
        worker: Principal,
        attempt: SpatialDataAttemptV1,
        credentials: SpatialDataCredentialCurrentness,
    ) -> SpatialDataWorkerInputV1:
        job = self.jobs.worker_input(
            job_id=job_id, worker=worker, attempt=attempt, now=self.clock()
        )
        expires = min(
            attempt.lease_until, job.deadline, job.grant.valid_until, self.activation.valid_until
        )
        cap = self.storage.issue_source_get(job.source, attempt, expires_at=expires)
        worker = credentials.resolve(now=self.clock())
        self.jobs.worker_input(job_id=job_id, worker=worker, attempt=attempt, now=self.clock())
        if cap.expires_at > expires:
            raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
        try:
            result = SpatialDataWorkerInputV1(
                job=job,
                attempt=attempt,
                runtime=job.runtime,
                activation=self.activation,
                source_capability=cap,
            )
            if cap.expires_at <= self.clock():
                raise ValueError("provider returned expired capability")
            return result
        except ValueError as exc:
            raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503) from exc

    def upload(
        self,
        *,
        job_id: str,
        worker: Principal,
        declaration: SpatialDataUploadDeclarationV1,
        credentials: SpatialDataCredentialCurrentness,
    ) -> SpatialDataOutputUploadViewV1:
        if declaration.upload_digest != declaration.canonical_digest():
            raise SpatialDataDomainError("REPORT_CONFLICT", 409)
        attempt = declaration.attempt
        job = self.jobs.worker_input(
            job_id=job_id, worker=worker, attempt=attempt, now=self.clock()
        )
        owned = self.jobs.reserved_output(
            job_id=job_id,
            worker=worker,
            attempt=attempt,
            upload_digest=declaration.upload_digest,
            now=self.clock(),
        )
        expires = (
            owned[0].expires_at
            if owned is not None
            else min(
                attempt.lease_until,
                job.deadline,
                job.grant.valid_until,
                self.activation.valid_until,
            )
        )
        target = self.jobs.reserve_output(
            job_id=job_id,
            worker=worker,
            attempt=attempt,
            receipt=declaration.receipt,
            expires_at=expires,
            now=self.clock(),
        )
        cap = self.storage.issue_output_put(
            target,
            sha256=declaration.sha256,
            size_bytes=declaration.size_bytes,
            content_type=declaration.content_type,
            expires_at=expires,
        )
        worker = credentials.resolve(now=self.clock())
        self.jobs.worker_input(job_id=job_id, worker=worker, attempt=attempt, now=self.clock())
        try:
            cap = SpatialDataUploadCapabilityV1.model_validate(cap.__dict__)
        except ValueError as exc:
            raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503) from exc
        parsed = urlsplit(cap.upload_url)
        if (
            f"{parsed.scheme}://{parsed.netloc}" not in self.activation.trusted_endpoint_origins
            or not self.clock() < cap.expires_at <= expires
            or cap.receipt_digest != declaration.receipt.receipt_digest
            or cap.sha256 != declaration.sha256
            or cap.size_bytes != declaration.size_bytes
        ):
            raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
        return SpatialDataOutputUploadViewV1(
            upload_digest=declaration.upload_digest, capability=cap
        )

    def complete(
        self,
        *,
        job_id: str,
        worker: Principal,
        attempt: SpatialDataAttemptV1,
        upload_digest: str,
        credentials: SpatialDataCredentialCurrentness,
    ) -> SpatialDataJobViewV1:
        owned = self.jobs.reserved_output(
            job_id=job_id,
            worker=worker,
            attempt=attempt,
            upload_digest=upload_digest,
            now=self.clock(),
        )
        if owned is None:
            raise SpatialDataDomainError("REPORT_CONFLICT", 409)
        target, accepted = owned
        observation = (
            accepted if accepted is not None else self.storage.observe_owned_output(target)
        )
        worker = credentials.resolve(now=self.clock())
        return self.jobs.complete(
            job_id=job_id,
            worker=worker,
            attempt=attempt,
            upload_digest=upload_digest,
            observation=observation,
            now=self.clock(),
        )
