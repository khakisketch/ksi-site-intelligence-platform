"""Shared public DTOs for the additive Site/WorkArea Analysis API.

These records describe an API projection.  They carry no execution authority:
the Core facade resolves the selector, chooses the fixed AP/NX identity, and
issues the work.  Keeping this module independent from Core lets the API
schema, Core routes, Processing Controller boundary tests, and Dashboard share
one closed vocabulary without importing a service implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_relative_volume_calculation import RelativeVolumeCoverageWitnessV2

_Text = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
_ReasonCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]{0,127}$",
    ),
]
_Digest = Annotated[
    str,
    StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
]
_SubmissionRef = Annotated[
    str,
    StringConstraints(pattern=r"^ers-v1-[0-9a-f]{64}$"),
]
_Href = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=4,
        max_length=2048,
        pattern=r"^/v1/[A-Za-z0-9._~/%?=&;:@,\-]+$",
    ),
]


class AnalysisExecutionStateV1(StrEnum):
    """Lifecycle of the Core-recorded request, independent from suitability."""

    NOT_STARTED = "NOT_STARTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AnalysisSuitabilityStateV1(StrEnum):
    """Current AP/NX usability projection; it never certifies field accuracy."""

    BLOCKED = "BLOCKED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    PROVISIONAL_ACCURACY_UNVERIFIED = "PROVISIONAL_ACCURACY_UNVERIFIED"
    EVALUATED = "EVALUATED"
    REASSESSMENT_REQUIRED = "REASSESSMENT_REQUIRED"


class AnalysisObservationSelectorV1(_CamelModel):
    """The only caller-controlled epoch reference accepted by analysis create."""

    work_order_id: _Text
    submission_ref: _SubmissionRef
    revision: int = Field(ge=1)


class CreateAnalysisRequestV1(_CamelModel):
    """Two ordered selectors; caller policy/runtime/digest fields are forbidden."""

    baseline: AnalysisObservationSelectorV1
    current: AnalysisObservationSelectorV1

    @model_validator(mode="after")
    def _requires_two_distinct_selections(self) -> Self:
        if self.baseline == self.current:
            raise ValueError("baseline and current selectors must differ")
        return self


class AnalysisObservationOptionV1(_CamelModel):
    """Read-only candidate exposed to a Site-scoped selector UI."""

    selector: AnalysisObservationSelectorV1
    observation_epoch_id: _Text
    capture_started_at: datetime
    capture_ended_at: datetime

    @field_validator("capture_started_at", "capture_ended_at")
    @classmethod
    def _requires_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("capture times must be UTC")
        return value

    @model_validator(mode="after")
    def _requires_positive_capture_window(self) -> Self:
        if self.capture_started_at >= self.capture_ended_at:
            raise ValueError("capture interval must be positive")
        return self


class AnalysisObservationOptionsV1(_CamelModel):
    items: tuple[AnalysisObservationOptionV1, ...] = Field(max_length=500)


class AnalysisBlockerV1(_CamelModel):
    """Typed cause with optional epoch/evidence linkage for a fail-closed view."""

    code: _ReasonCode
    epoch: Literal["BASELINE", "CURRENT"] | None = None
    evidence_ref: _Text | None = None
    detail: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
        | None
    ) = None


class AnalysisEvidenceReferenceV1(_CamelModel):
    """Tenant-scoped resolvable evidence reference; a digest alone is insufficient."""

    kind: _Text
    record_id: _Text
    href: _Href


class AnalysisAuthorityReferencesV1(_CamelModel):
    """Opaque links to the AP/NX durable records used for this projection."""

    assessment_request_id: _Text | None = None
    admission_id: _Text | None = None
    admission_digest: _Digest | None = None
    calculation_identity_digest: _Digest | None = None
    calculation_request_id: _Text | None = None
    authorization_id: _Text | None = None
    report_digest: _Digest | None = None
    failure_digest: _Digest | None = None


class AnalysisMetricsV1(_CamelModel):
    cut_m3: float = Field(ge=0.0)
    fill_m3: float = Field(ge=0.0)
    net_m3: float
    threshold_m: float = Field(ge=0.0)
    uncertainty_m3: None = None

    @model_validator(mode="after")
    def _retains_fixed_profile_arithmetic(self) -> Self:
        if self.threshold_m != 0.0:
            raise ValueError("first analysis API profile requires zero threshold")
        if self.net_m3 != self.fill_m3 - self.cut_m3:
            raise ValueError("net volume must equal fill minus cut")
        return self


class AnalysisResultV1(_CamelModel):
    """Current completed numeric projection; no accuracy/settlement interpretation."""

    result_id: _Text
    result_revision: Literal[1] = 1
    report_digest: _Digest
    numeric_result_identity_digest: _Digest
    computed_at: datetime
    metrics: AnalysisMetricsV1
    coverage: RelativeVolumeCoverageWitnessV2
    limitation_codes: tuple[_ReasonCode, ...] = ()

    @field_validator("computed_at")
    @classmethod
    def _computed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("computedAt must be UTC")
        return value


class AnalysisPolicyEvidenceV1(_CamelModel):
    """Sealed fixed-profile facts used by the resolved calculation identity."""

    policy_id: _Text
    version: int = Field(ge=1)
    profile_id: _Text
    profile_digest: _Digest
    algorithm_digest: _Digest
    config_digest: _Digest
    policy_digest: _Digest


class AnalysisRuntimeEvidenceV1(_CamelModel):
    """Core-selected local runtime facts, not a signed-runtime claim."""

    worker_executable_digest: _Digest
    worker_build_digest: _Digest
    runtime_image_version: _Text
    runtime_image_oci_digest: _Digest
    dependency_lock_digest: _Digest


class AnalysisCalculationIdentityEvidenceV1(_CamelModel):
    """Non-numeric sealed calculation identity facts exposed by evidence GET."""

    calculation_id: _Text
    work_area_definition_digest: _Digest
    baseline_input_digest: _Digest
    current_input_digest: _Digest
    policy: AnalysisPolicyEvidenceV1
    runtime: AnalysisRuntimeEvidenceV1


class AnalysisEpochEvidenceV1(_CamelModel):
    """Resolved AP identity facts for one epoch, returned by the evidence endpoint."""

    selector: AnalysisObservationSelectorV1
    observation_epoch_id: _Text
    artifact_id: _Text
    observed_sha256: _Digest
    observed_size_bytes: int = Field(gt=0)
    observed_crs_identifier: _Text
    observed_crs_digest: _Digest
    vertical_reference_identifier: _Text
    vertical_reference_basis: _Text
    vertical_unit: Literal["metre"]
    transform: tuple[float, float, float, float, float, float]
    transform_digest: _Digest
    inspection_report_digest: _Digest
    inspection_report_ref: AnalysisEvidenceReferenceV1
    input_digest: _Digest


class AnalysisEvaluationEvidenceFactV1(_CamelModel):
    """Exact checkpoint authority consulted by one sealed AP evaluation revision."""

    evidence_ref: _Text
    context_id: _Text
    context_digest: _Digest
    evidence_manifest_digest: _Digest
    evidence_record_id: _Text
    evidence_record_digest: _Digest
    core_verdict: Literal["VALIDATED", "REJECTED"]
    href: _Href


class AnalysisEvaluationEvidenceV1(_CamelModel):
    """A recorded per-epoch suitability evaluation, never a newly computed verdict."""

    evaluation_id: _Text
    epoch: Literal["BASELINE", "CURRENT"]
    revision: int = Field(ge=1)
    evaluation_digest: _Digest
    outcome: Literal["PASS", "FAIL", "UNASSESSED", "UNAVAILABLE"]
    reason_codes: tuple[_ReasonCode, ...] = Field(min_length=1, max_length=64)
    assessed_at: datetime
    evidence_facts: tuple[AnalysisEvaluationEvidenceFactV1, ...] = Field(max_length=64)

    @field_validator("assessed_at")
    @classmethod
    def _assessed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("assessedAt must be UTC")
        return value


class AnalysisViewV1(_CamelModel):
    """Canonical create/list/detail/result projection shared by UI and API clients."""

    analysis_id: _Text
    site_id: _Text
    work_area_id: _Text
    baseline: AnalysisObservationSelectorV1
    current: AnalysisObservationSelectorV1
    execution_state: AnalysisExecutionStateV1
    suitability_state: AnalysisSuitabilityStateV1
    blockers: tuple[AnalysisBlockerV1, ...] = Field(max_length=128)
    evidence_refs: tuple[AnalysisEvidenceReferenceV1, ...] = Field(max_length=256)
    authority: AnalysisAuthorityReferencesV1 = Field(default_factory=AnalysisAuthorityReferencesV1)
    result: AnalysisResultV1 | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("createdAt must be UTC")
        return value

    @model_validator(mode="after")
    def _enforces_two_independent_states(self) -> Self:
        numeric_states = {
            AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED,
            AnalysisSuitabilityStateV1.EVALUATED,
        }
        if self.suitability_state is AnalysisSuitabilityStateV1.BLOCKED:
            if not self.blockers:
                raise ValueError("blocked analysis requires one or more typed blockers")
            if self.execution_state is AnalysisExecutionStateV1.FAILED:
                coverage_failure_codes = {
                    "EMPTY_COMMON_VALID_COVERAGE",
                    "INSUFFICIENT_COMMON_VALID_COVERAGE",
                }
                if len(self.blockers) != 1 or self.blockers[0].code not in coverage_failure_codes:
                    raise ValueError("failed blocked analysis requires one common-coverage blocker")
                if self.result is not None:
                    raise ValueError("failed blocked analysis must withhold numeric result")
            elif self.execution_state is not AnalysisExecutionStateV1.NOT_STARTED:
                raise ValueError("blocked analysis requires not-started or failed execution")
        if self.result is not None and (
            self.execution_state is not AnalysisExecutionStateV1.COMPLETED
            or self.suitability_state not in numeric_states
        ):
            raise ValueError("numeric result requires a current completed suitable analysis")
        if (
            self.execution_state is AnalysisExecutionStateV1.COMPLETED
            and self.suitability_state in numeric_states
            and self.result is None
        ):
            raise ValueError("current completed suitable analysis requires a numeric result")
        if (
            self.suitability_state
            in {
                AnalysisSuitabilityStateV1.REMEDIATION_REQUIRED,
                AnalysisSuitabilityStateV1.REASSESSMENT_REQUIRED,
            }
            and self.result is not None
        ):
            raise ValueError("remediation or reassessment must withhold numeric result")
        return self


class AnalysisListV1(_CamelModel):
    items: tuple[AnalysisViewV1, ...] = Field(max_length=500)


class AnalysisReadinessViewV1(_CamelModel):
    """Pure read-only preflight for one arbitrary selector pair.

    This projection never creates an intent, AP/NX record, or journal entry
    and grants no execution authority. It reuses the sealed AP decision
    predicates read-only; ``create`` rechecks the same predicates before any
    durable admission. ``coverageCheck`` never promises common-mask
    verification — that remains worker-validated.
    """

    contract_version: Literal["analysis-readiness.v1"] = "analysis-readiness.v1"
    site_id: _Text
    work_area_id: _Text
    baseline: AnalysisObservationSelectorV1
    current: AnalysisObservationSelectorV1
    suitability_state: AnalysisSuitabilityStateV1
    blockers: tuple[AnalysisBlockerV1, ...] = Field(max_length=128)
    limitation_codes: tuple[_ReasonCode, ...] = Field(max_length=128, default=())
    checked_at: datetime
    calculation_identity_digest: _Digest | None = None
    coverage_check: Literal["REQUIRES_WORKER_VALIDATION"] = "REQUIRES_WORKER_VALIDATION"

    @field_validator("checked_at")
    @classmethod
    def _checked_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("checkedAt must be UTC")
        return value

    @model_validator(mode="after")
    def _readiness_state_matches_blockers(self) -> Self:
        needs_blockers = {
            AnalysisSuitabilityStateV1.BLOCKED,
            AnalysisSuitabilityStateV1.REMEDIATION_REQUIRED,
            AnalysisSuitabilityStateV1.REASSESSMENT_REQUIRED,
        }
        if self.suitability_state in needs_blockers and not self.blockers:
            raise ValueError("unavailable readiness requires one or more typed blockers")
        if self.suitability_state not in needs_blockers and self.blockers:
            raise ValueError("available readiness must not carry blockers")
        if (
            self.suitability_state is not AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED
            and self.limitation_codes
        ):
            raise ValueError("only provisional readiness may carry limitation codes")
        return self


class AnalysisEvidenceViewV1(_CamelModel):
    analysis_id: _Text
    authority: AnalysisAuthorityReferencesV1
    baseline: AnalysisEpochEvidenceV1 | None = None
    current: AnalysisEpochEvidenceV1 | None = None
    calculation: AnalysisCalculationIdentityEvidenceV1 | None = None
    evaluations: tuple[AnalysisEvaluationEvidenceV1, ...] = Field(default=(), max_length=2)
    result: AnalysisResultV1 | None = None
    evidence_refs: tuple[AnalysisEvidenceReferenceV1, ...] = Field(max_length=256)


__all__ = [
    "AnalysisAuthorityReferencesV1",
    "AnalysisBlockerV1",
    "AnalysisCalculationIdentityEvidenceV1",
    "AnalysisEvidenceReferenceV1",
    "AnalysisEvidenceViewV1",
    "AnalysisEvaluationEvidenceFactV1",
    "AnalysisEvaluationEvidenceV1",
    "AnalysisEpochEvidenceV1",
    "AnalysisExecutionStateV1",
    "AnalysisListV1",
    "AnalysisMetricsV1",
    "AnalysisObservationOptionV1",
    "AnalysisObservationOptionsV1",
    "AnalysisObservationSelectorV1",
    "AnalysisPolicyEvidenceV1",
    "AnalysisReadinessViewV1",
    "AnalysisResultV1",
    "AnalysisRuntimeEvidenceV1",
    "AnalysisSuitabilityStateV1",
    "AnalysisViewV1",
    "CreateAnalysisRequestV1",
]
