"""Bounded private transport for one distinct native-grid preparation worker."""

from __future__ import annotations

import base64
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field, StrictBool, StringConstraints, model_validator

from ksi_event_contracts._spatial_data import (
    Digest,
    PositiveInt,
    SpatialDataDigestModel,
    SpatialDataModel,
    Text,
    UtcTimestamp,
)
from ksi_event_contracts.spatial_data import (
    JobId,
    SpatialDataAttemptV1,
    SpatialDataFrozenJobV1,
    SpatialDataJobViewV1,
    SpatialDataReasonV1,
    SpatialDataReceiptV1,
)
from ksi_event_contracts.spatial_data_authority import SpatialDataActivationV1, SpatialDataRuntimeV1

SPATIAL_DATA_WORKER_INSTANCE_ID_HEADER = "X-Spatial-Data-Worker-Instance-Id"
SPATIAL_DATA_ATTEMPT_DIGEST_HEADER = "X-Spatial-Data-Attempt-Digest"
TRANSIENT_STORAGE_REASONS = frozenset({"STORAGE_UNAVAILABLE"})


def _url(value: str) -> str:
    if any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value:
        raise ValueError("capability URL contains whitespace/control/backslash")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("capability URL is invalid") from exc
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or "#" in value
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("capability URL must be credential-free HTTP(S), without fragment")
    return value


CapabilityUrl = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=16384), AfterValidator(_url)
]


def _header_value(value: str) -> str:
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("capability header contains control characters")
    return value


class SpatialDataRequiredHeaderV1(SpatialDataModel):
    """Allowlisted storage headers, never forwarding parent bearer/cookies/Host."""

    name: Literal[
        "Content-Type",
        "content-type",
        "Content-Length",
        "content-length",
        "x-amz-checksum-sha256",
        "X-Amz-Checksum-Sha256",
        "x-amz-checksum-mode",
        "X-Amz-Checksum-Mode",
    ]
    value: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=8192),
        AfterValidator(_header_value),
    ]


class _Capability(SpatialDataModel):
    required_headers: tuple[SpatialDataRequiredHeaderV1, ...] = Field(max_length=16)
    expires_at: UtcTimestamp

    @model_validator(mode="after")
    def _unique_header_names(self) -> Self:
        names = [header.name.lower() for header in self.required_headers]
        if len(set(names)) != len(names):
            raise ValueError("capability headers must be unique case-insensitively")
        return self

    def header_mapping(self) -> dict[str, str]:
        record = type(self).model_validate(self.__dict__)
        return {header.name: header.value for header in record.required_headers}


class SpatialDataSourceCapabilityV1(_Capability):
    artifact_id: Text
    source_digest: Digest
    observed_sha256: Digest
    observed_size_bytes: PositiveInt
    download_url: CapabilityUrl


class SpatialDataUploadCapabilityV1(_Capability):
    receipt_digest: Digest
    sha256: Digest
    size_bytes: PositiveInt
    content_type: Literal["image/tiff"]
    upload_url: CapabilityUrl

    @model_validator(mode="after")
    def _exact_upload_headers(self) -> Self:
        headers = {header.name.lower(): header.value for header in self.required_headers}
        required = {
            "content-type": self.content_type,
            "content-length": str(self.size_bytes),
            "x-amz-checksum-sha256": base64.b64encode(bytes.fromhex(self.sha256[7:])).decode(
                "ascii"
            ),
        }
        if headers != required:
            raise ValueError("upload headers must bind exact type, size and full SHA-256")
        return self


class SpatialDataLeaseRequestV1(SpatialDataModel):
    worker_instance_id: Text
    acquisition_id: Text


class _AttemptOperation(SpatialDataModel):
    attempt: SpatialDataAttemptV1

    @model_validator(mode="after")
    def _sealed_attempt(self) -> Self:
        if self.attempt.attempt_digest != self.attempt.canonical_digest():
            raise ValueError("worker operation requires sealed attempt")
        return self


class SpatialDataLeaseViewV1(_AttemptOperation):
    job_id: JobId

    @model_validator(mode="after")
    def _exact_job(self) -> Self:
        if self.attempt.job_id != self.job_id:
            raise ValueError("lease view must bind job")
        return self


class SpatialDataRenewRequestV1(_AttemptOperation):
    """Renew one exact leased acquisition, not arbitrary worker-selected state."""


class SpatialDataWorkerInputV1(SpatialDataModel):
    job: SpatialDataFrozenJobV1
    attempt: SpatialDataAttemptV1
    runtime: SpatialDataRuntimeV1
    activation: SpatialDataActivationV1
    source_capability: SpatialDataSourceCapabilityV1

    @model_validator(mode="after")
    def _exact_attempt_runtime_capability_and_expiry(self) -> Self:
        job, attempt, activation, cap = (
            self.job,
            self.attempt,
            self.activation,
            self.source_capability,
        )
        for snapshot in (job, attempt, self.runtime, activation):
            if getattr(snapshot, snapshot._digest_field) != snapshot.canonical_digest():
                raise ValueError("worker input requires sealed snapshots")
        if attempt.job_id != job.job_id or attempt.frozen_job_digest != job.job_digest:
            raise ValueError("worker input must bind exact frozen job and attempt")
        if self.runtime.runtime_digest != job.runtime.runtime_digest:
            raise ValueError("worker input runtime must match frozen job")
        if (
            activation.organization_id != job.organization_id
            or activation.worker_principal_id != attempt.worker_principal_id
            or activation.worker_instance_id != attempt.worker_instance_id
            or activation.runtime_digest != self.runtime.runtime_digest
            or activation.policy_digest != job.policy.policy_digest
        ):
            raise ValueError("activation must bind organization, worker, runtime and policy")
        if not activation.is_current_at(attempt.acquired_at):
            raise ValueError("activation is not current at lease acquisition")
        if (
            cap.expires_at
            > min(attempt.lease_until, job.deadline, job.grant.valid_until, activation.valid_until)
            or cap.expires_at <= attempt.acquired_at
        ):
            raise ValueError("source capability must be current and no longer than every gate")
        source = job.source
        if (cap.artifact_id, cap.source_digest, cap.observed_sha256, cap.observed_size_bytes) != (
            source.artifact_id,
            source.source_digest,
            source.observed_sha256,
            source.observed_size_bytes,
        ):
            raise ValueError("source capability must bind exact sealed bytes")
        parsed = urlsplit(cap.download_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in activation.trusted_endpoint_origins:
            raise ValueError("source capability origin is not activated")
        return self


class SpatialDataWorkerInputResponseV1(SpatialDataModel):
    input: SpatialDataWorkerInputV1


class SpatialDataUploadDeclarationV1(SpatialDataDigestModel):
    _digest_field = "upload_digest"
    attempt: SpatialDataAttemptV1
    receipt: SpatialDataReceiptV1
    sha256: Digest
    size_bytes: PositiveInt
    content_type: Literal["image/tiff"]
    upload_digest: Digest | None = None

    @model_validator(mode="after")
    def _exact_upload_binding(self) -> Self:
        attempt, receipt = self.attempt, self.receipt
        if attempt.attempt_digest != attempt.canonical_digest() or (
            receipt.receipt_digest != receipt.canonical_digest()
        ):
            raise ValueError("upload declaration requires sealed attempt and receipt")
        if attempt.job_id != receipt.job_id or attempt.frozen_job_digest != receipt.job_digest:
            raise ValueError("upload receipt must bind exact job/attempt")
        if self.sha256 != receipt.output_sha256 or self.size_bytes != receipt.output_size_bytes:
            raise ValueError("upload must bind exact output bytes")
        if not attempt.acquired_at <= receipt.prepared_at < attempt.lease_until:
            raise ValueError("preparation must be within active attempt interval")
        return self


class SpatialDataOutputUploadRequestV1(SpatialDataModel):
    declaration: SpatialDataUploadDeclarationV1


class SpatialDataOutputUploadViewV1(SpatialDataModel):
    upload_digest: Digest
    capability: SpatialDataUploadCapabilityV1


class SpatialDataCompleteRequestV1(_AttemptOperation):
    upload_digest: Digest


class SpatialDataFailureRequestV1(_AttemptOperation):
    reason: SpatialDataReasonV1
    retryable: StrictBool

    @model_validator(mode="after")
    def _transport_only_retry(self) -> Self:
        if self.retryable != (self.reason in TRANSIENT_STORAGE_REASONS):
            raise ValueError("only unavailable source/storage transport failures are retryable")
        return self


class SpatialDataWorkerPendingPageV1(SpatialDataModel):
    items: tuple[SpatialDataFrozenJobV1, ...] = Field(max_length=200)


class SpatialDataWorkerMutationViewV1(SpatialDataModel):
    job: SpatialDataJobViewV1
