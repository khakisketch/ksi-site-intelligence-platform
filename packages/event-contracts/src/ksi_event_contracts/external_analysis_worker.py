"""Strict internal transport for the local V1 Analysis worker loop.

These models name an authenticated worker's leased calculation and its two
short-lived byte capabilities.  They deliberately import only event contracts:
Processing Controller must never import Core stores to run a job.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import Digest
from ksi_event_contracts.external_relative_volume_analysis import CalculationIdentityV2
from ksi_event_contracts.external_relative_volume_calculation import (
    AnalysisExecutionAttemptV2,
    RelativeVolumeCalculationFailureV2,
    RelativeVolumeCalculationReportV2,
)

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_HeaderName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$",
    ),
]
_HeaderValue = Annotated[
    str, StringConstraints(strip_whitespace=False, min_length=1, max_length=8192)
]
_Url = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16384)]

# GET has no request body.  Both headers are required so a shared processing
# credential cannot retrieve the active capabilities of another instance.
ANALYSIS_ATTEMPT_DIGEST_HEADER = "X-Analysis-Attempt-Digest"
ANALYSIS_WORKER_INSTANCE_ID_HEADER = "X-Analysis-Worker-Instance-Id"


class _WorkerModel(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field} must be UTC")
    return value


class AnalysisWorkerPendingItemV1(_WorkerModel):
    analysis_id: _Text
    calculation_request_id: _Text
    issued_at: datetime

    @field_validator("issued_at")
    @classmethod
    def _issued_at_utc(cls, value: datetime) -> datetime:
        return _utc(value, "issuedAt")


class AnalysisWorkerPendingListV1(_WorkerModel):
    items: tuple[AnalysisWorkerPendingItemV1, ...] = Field(max_length=200)


class AnalysisWorkerLeaseRequestV1(_WorkerModel):
    worker_instance_id: _Text
    lease_acquisition_id: _Text


class AnalysisWorkerLeaseViewV1(_WorkerModel):
    analysis_id: _Text
    calculation_request_id: _Text
    attempt: AnalysisExecutionAttemptV2


class AnalysisWorkerRenewRequestV1(_WorkerModel):
    attempt: AnalysisExecutionAttemptV2


class AnalysisWorkerInputCapabilityV1(_WorkerModel):
    """One short-lived URL bound to one immutable DSM identity."""

    role: Literal["BASELINE_DSM", "CURRENT_DSM"]
    artifact_id: _Text
    observed_sha256: Digest
    observed_size_bytes: int = Field(gt=0)
    download_url: _Url
    required_headers: dict[_HeaderName, _HeaderValue] = Field(max_length=32)
    expires_at: datetime

    @field_validator("download_url")
    @classmethod
    def _capability_url_is_http(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "\r" in value
            or "\n" in value
        ):
            raise ValueError("downloadUrl must be a credential-free HTTP(S) URL")
        return value

    @field_validator("expires_at")
    @classmethod
    def _expires_at_utc(cls, value: datetime) -> datetime:
        return _utc(value, "expiresAt")


class AnalysisWorkerInputV1(_WorkerModel):
    """Exact attempt, identity, and ordered bounded inputs for one measurement."""

    analysis_id: _Text
    calculation_request_id: _Text
    attempt: AnalysisExecutionAttemptV2
    calculation_identity: CalculationIdentityV2
    inputs: tuple[AnalysisWorkerInputCapabilityV1, AnalysisWorkerInputCapabilityV1]

    @model_validator(mode="after")
    def _binds_exact_attempt_identity_and_inputs(self) -> Self:
        identity = self.calculation_identity
        if (
            identity.calculation_identity_digest is None
            or identity.calculation_identity_digest != identity.canonical_digest()
            or self.attempt.authorization.calculation_identity_digest
            != identity.calculation_identity_digest
        ):
            raise ValueError("worker input identity does not bind its exact attempt")
        baseline, current = self.inputs
        if (baseline.role, current.role) != ("BASELINE_DSM", "CURRENT_DSM"):
            raise ValueError("worker inputs must be ordered baseline then current")
        expected = (
            (
                identity.baseline_dsm_artifact_id,
                identity.baseline_dsm_observed_sha256,
                identity.baseline_dsm_observed_size_bytes,
            ),
            (
                identity.current_dsm_artifact_id,
                identity.current_dsm_observed_sha256,
                identity.current_dsm_observed_size_bytes,
            ),
        )
        supplied = tuple(
            (item.artifact_id, item.observed_sha256, item.observed_size_bytes)
            for item in self.inputs
        )
        if supplied != expected:
            raise ValueError("worker capabilities do not bind the calculation identity")
        if any(item.expires_at > self.attempt.lease_expires_at for item in self.inputs):
            raise ValueError("worker capability outlives its lease")
        return self


class AnalysisWorkerInputResponseV1(_WorkerModel):
    input: AnalysisWorkerInputV1


class AnalysisWorkerReportRequestV1(_WorkerModel):
    report: RelativeVolumeCalculationReportV2


class AnalysisWorkerFailureRequestV1(_WorkerModel):
    failure: RelativeVolumeCalculationFailureV2


class AnalysisWorkerMutationViewV1(_WorkerModel):
    analysis_id: _Text
    calculation_request_id: _Text
    execution_state: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
    attempt: AnalysisExecutionAttemptV2 | None = None


__all__ = [
    "ANALYSIS_ATTEMPT_DIGEST_HEADER",
    "ANALYSIS_WORKER_INSTANCE_ID_HEADER",
    "AnalysisWorkerFailureRequestV1",
    "AnalysisWorkerInputCapabilityV1",
    "AnalysisWorkerInputResponseV1",
    "AnalysisWorkerInputV1",
    "AnalysisWorkerLeaseRequestV1",
    "AnalysisWorkerLeaseViewV1",
    "AnalysisWorkerMutationViewV1",
    "AnalysisWorkerPendingItemV1",
    "AnalysisWorkerPendingListV1",
    "AnalysisWorkerRenewRequestV1",
    "AnalysisWorkerReportRequestV1",
]
