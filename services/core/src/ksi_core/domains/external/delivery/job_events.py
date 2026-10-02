"""Strict private journal events: no bearer, presigned capability or mutable latest alias."""

from typing import Annotated, Literal, Self

from ksi_event_contracts._spatial_data import Digest, PositiveInt, SpatialDataModel, UtcTimestamp
from ksi_event_contracts.spatial_data import (
    JobId,
    SpatialDataAttemptV1,
    SpatialDataFrozenJobV1,
    SpatialDataReasonV1,
    SpatialDataReceiptV1,
)
from pydantic import Field, TypeAdapter, model_validator


class _Event(SpatialDataModel):
    job_id: JobId
    sequence: PositiveInt
    at: UtcTimestamp


class JobIssued(_Event):
    record_type: Literal["spatial-data-job.issued.v1"] = "spatial-data-job.issued.v1"
    job: SpatialDataFrozenJobV1

    @model_validator(mode="after")
    def sealed_job(self) -> Self:
        if self.sequence != 1 or self.job_id != self.job.job_id or self.at != self.job.created_at:
            raise ValueError("issuance identity/time/sequence mismatch")
        if self.job.job_digest != self.job.canonical_digest():
            raise ValueError("job snapshot must be sealed")
        return self


class JobLeased(_Event):
    record_type: Literal["spatial-data-job.leased.v1"] = "spatial-data-job.leased.v1"
    attempt: SpatialDataAttemptV1


class JobRenewed(_Event):
    record_type: Literal["spatial-data-job.renewed.v1"] = "spatial-data-job.renewed.v1"
    attempt: SpatialDataAttemptV1


class JobStateChanged(_Event):
    record_type: Literal["spatial-data-job.state.v1"] = "spatial-data-job.state.v1"
    state: Literal["QUEUED", "FAILED", "CANCELED", "EXPIRED"]
    reason: SpatialDataReasonV1
    next_available_at: UtcTimestamp | None = None
    attempt: SpatialDataAttemptV1 | None = None


class JobOutputReserved(_Event):
    record_type: Literal["spatial-data-job.output-reserved.v1"] = (
        "spatial-data-job.output-reserved.v1"
    )
    receipt: SpatialDataReceiptV1
    object_key: Annotated[str, Field(min_length=1, max_length=1024)]
    expires_at: UtcTimestamp
    upload_digest: Digest


class JobCompleted(_Event):
    record_type: Literal["spatial-data-job.completed.v1"] = "spatial-data-job.completed.v1"
    upload_digest: Digest
    object_key: Annotated[str, Field(min_length=1, max_length=1024)]
    version_id: Annotated[str, Field(min_length=1, max_length=1024)]
    size_bytes: PositiveInt
    sha256: Digest
    content_type: Literal["image/tiff"]


class JobCleanupChanged(_Event):
    record_type: Literal["spatial-data-job.cleanup.v1"] = "spatial-data-job.cleanup.v1"
    fence_digest: Digest
    cleanup_id: Annotated[
        str,
        Field(
            min_length=36,
            max_length=36,
            pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        ),
    ]
    attempt_number: PositiveInt
    state: Literal["STARTED", "COMPLETED", "FAILED"]
    reason: SpatialDataReasonV1 | None = None


JobEvent = Annotated[
    JobIssued
    | JobLeased
    | JobRenewed
    | JobStateChanged
    | JobOutputReserved
    | JobCompleted
    | JobCleanupChanged,
    Field(discriminator="record_type"),
]
JOB_EVENT: TypeAdapter[JobEvent] = TypeAdapter(JobEvent)
