"""Bounded V2 projections for Core-owned external Analysis records.

V2 deliberately separates compact structured views from the potentially large
coverage byte resource.  It projects existing V1 journal facts; it carries no
calculation or authority inputs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_analysis_api import (
    AnalysisBlockerV1,
    AnalysisCalculationIdentityEvidenceV1,
    AnalysisExecutionStateV1,
    AnalysisMetricsV1,
    AnalysisObservationSelectorV1,
    AnalysisSuitabilityStateV1,
)

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_ReasonCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]{0,127}$",
    ),
]
_Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
_Cursor = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
_Href = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=5,
        max_length=2048,
        pattern=r"^/v2/[A-Za-z0-9._~/%?=&;:@,\-]+$",
    ),
]
_EvidenceHref = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=5,
        max_length=2048,
        pattern=r"^/(?:v1|v2)/[A-Za-z0-9._~/%?=&;:@,\-]+$",
    ),
]
_Count = Annotated[int, Field(ge=0, le=1_000_000_000_000_000)]


class AnalysisCoverageSummaryV2(_CamelModel):
    """Small digest-bound coverage facts; coverage masks are never embedded."""

    coverage_witness_digest: _Digest
    rows: Annotated[int, Field(ge=1, le=1_000_000_000)]
    columns: Annotated[int, Field(ge=1, le=1_000_000_000)]
    selected_cell_count: _Count
    common_valid_cell_count: _Count
    unavailable_cell_count: _Count
    threshold_excluded_cell_count: _Count
    cell_area_m2: Annotated[float, Field(gt=0.0)]
    selected_area_m2: Annotated[float, Field(ge=0.0)]
    common_valid_area_m2: Annotated[float, Field(ge=0.0)]
    bounds: tuple[float, float, float, float]

    @model_validator(mode="after")
    def _counts_match_partition(self) -> Self:
        if self.selected_cell_count != (
            self.common_valid_cell_count
            + self.unavailable_cell_count
            + self.threshold_excluded_cell_count
        ):
            raise ValueError("coverage cell counts must partition selected cells")
        return self


class AnalysisResultSummaryV2(_CamelModel):
    """Compact numeric result projection with unchanged provisional semantics."""

    result_id: _Text
    report_digest: _Digest
    numeric_result_identity_digest: _Digest
    computed_at: datetime
    metrics: AnalysisMetricsV1
    coverage: AnalysisCoverageSummaryV2
    limitation_codes: tuple[_ReasonCode, ...] = Field(max_length=128)

    @field_validator("computed_at")
    @classmethod
    def _computed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("computedAt must be UTC")
        return value


class AnalysisViewV2(_CamelModel):
    """Bounded detail projection; evidence and full coverage are separate resources."""

    analysis_id: _Text
    site_id: _Text
    work_area_id: _Text
    baseline: AnalysisObservationSelectorV1
    current: AnalysisObservationSelectorV1
    execution_state: AnalysisExecutionStateV1
    suitability_state: AnalysisSuitabilityStateV1
    blockers: tuple[AnalysisBlockerV1, ...] = Field(max_length=128)
    result: AnalysisResultSummaryV2 | None = None
    evidence_revision: Annotated[int, Field(ge=1)]
    evidence_digest: _Digest
    evidence_href: _Href
    coverage_href: _Href | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("createdAt must be UTC")
        return value

    @model_validator(mode="after")
    def _result_matches_suitability(self) -> Self:
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
            elif self.execution_state is not AnalysisExecutionStateV1.NOT_STARTED:
                raise ValueError("blocked analysis requires not-started or failed execution")
        has_numeric_result = (
            self.execution_state is AnalysisExecutionStateV1.COMPLETED
            and self.suitability_state
            in {
                AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED,
                AnalysisSuitabilityStateV1.EVALUATED,
            }
        )
        if has_numeric_result != (self.result is not None):
            raise ValueError("result presence must match completed numeric suitability")
        if (
            self.execution_state is AnalysisExecutionStateV1.COMPLETED
            and self.result is None
            and self.suitability_state not in {
                AnalysisSuitabilityStateV1.BLOCKED,
                AnalysisSuitabilityStateV1.REMEDIATION_REQUIRED,
                AnalysisSuitabilityStateV1.REASSESSMENT_REQUIRED,
            }
        ):
            raise ValueError("completed analysis without result must explain its limitation")
        if self.result is not None and self.coverage_href is None:
            raise ValueError("numeric result requires a coverage resource link")
        return self


class AnalysisListItemV2(_CamelModel):
    """Small listing; limitation count covers blockers and result codes in analysisHref."""

    analysis_id: _Text
    site_id: _Text
    work_area_id: _Text
    execution_state: AnalysisExecutionStateV1
    suitability_state: AnalysisSuitabilityStateV1
    created_at: datetime
    result_id: _Text | None = None
    metrics: AnalysisMetricsV1 | None = None
    limitation_count: Annotated[
        int,
        Field(
            ge=0,
            le=256,
            description=(
                "Number of blocker and result limitation codes in the linked detail; the "
                "linked detail is authoritative and evidence pages may carry additional facts."
            ),
        ),
    ]
    analysis_href: _Href
    newer_sibling_analysis_ids: tuple[_Text, ...] = Field(
        default=(),
        max_length=50,
        description=(
            "Read-time derived continuers in the same Site/WorkArea whose baseline "
            "selector exactly equals this item current selector, ordered by "
            "(createdAt, analysisId). It names a shared-epoch link only; it never "
            "revises a record's result, suitability, or history. Detail, result, "
            "and evidence payloads of the earlier record stay byte-identical."
        ),
    )

    @field_validator("created_at")
    @classmethod
    def _created_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("createdAt must be UTC")
        return value

    @model_validator(mode="after")
    def _list_numeric_fields_are_paired(self) -> Self:
        if (self.result_id is None) != (self.metrics is None):
            raise ValueError("resultId and metrics must be present together")
        numeric_state = (
            self.execution_state is AnalysisExecutionStateV1.COMPLETED
            and self.suitability_state
            in {
                AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED,
                AnalysisSuitabilityStateV1.EVALUATED,
            }
        )
        if numeric_state != (self.result_id is not None):
            raise ValueError("numeric list fields require a completed numeric suitability")
        return self


class AnalysisListPageV2(_CamelModel):
    site_id: _Text
    items: tuple[AnalysisListItemV2, ...] = Field(max_length=50)
    next_cursor: _Cursor | None = None


class _EvidenceItemBaseV2(_CamelModel):
    """Common identity for one bounded fact; links exist only for real resolvers."""

    record_id: _Text
    digest: _Digest
    href: _EvidenceHref | None = None
    limitation_codes: tuple[_ReasonCode, ...] = Field(default=(), max_length=64)


class AnalysisEpochEvidenceItemV2(_EvidenceItemBaseV2):
    """Self-contained CRS, vertical, transform, and inspection-reference facts."""

    kind: Literal["EPOCH_IDENTITY"]
    epoch: Literal["BASELINE", "CURRENT"]
    selector: AnalysisObservationSelectorV1
    observation_epoch_id: _Text
    artifact_id: _Text
    observed_sha256: _Digest
    observed_size_bytes: Annotated[int, Field(gt=0)]
    observed_crs_identifier: _Text
    observed_crs_digest: _Digest
    vertical_reference_identifier: _Text
    vertical_reference_basis: _Text
    vertical_unit: Literal["metre"]
    transform: tuple[float, float, float, float, float, float]
    transform_digest: _Digest
    inspection_report_digest: _Digest
    inspection_report_record_id: _Text
    input_digest: _Digest


class AnalysisCalculationEvidenceItemV2(_EvidenceItemBaseV2):
    """Sealed AP calculation, policy, and runtime identity facts."""

    kind: Literal["CALCULATION_IDENTITY"]
    calculation: AnalysisCalculationIdentityEvidenceV1


class AnalysisEvaluationEvidenceItemV2(_EvidenceItemBaseV2):
    """One immutable AP evaluation header and every recorded reason code."""

    kind: Literal["EVALUATION"]
    evaluation_id: _Text
    epoch: Literal["BASELINE", "CURRENT"]
    revision: Annotated[int, Field(ge=1)]
    evaluation_digest: _Digest
    outcome: Literal["PASS", "FAIL", "UNASSESSED", "UNAVAILABLE"]
    reason_codes: tuple[_ReasonCode, ...] = Field(min_length=1, max_length=64)
    assessed_at: datetime

    @field_validator("assessed_at")
    @classmethod
    def _assessed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("assessedAt must be UTC")
        return value


class AnalysisCheckpointEvidenceItemV2(_EvidenceItemBaseV2):
    """One exact terminal checkpoint fact paired with its retained context."""

    kind: Literal["CHECKPOINT_FACT"]
    evaluation_id: _Text
    epoch: Literal["BASELINE", "CURRENT"]
    evaluation_revision: Annotated[int, Field(ge=1)]
    evidence_ref: _Text
    context_id: _Text
    context_digest: _Digest
    evidence_manifest_digest: _Digest
    evidence_record_id: _Text
    evidence_record_digest: _Digest
    core_verdict: Literal["VALIDATED", "REJECTED"]


class AnalysisAuthorityEvidenceItemV2(_EvidenceItemBaseV2):
    """One AP/NX authority reference without an invented fetch URL."""

    kind: Literal["AUTHORITY_REFERENCE"]
    reference_name: Literal[
        "assessmentRequestId",
        "admissionId",
        "admissionDigest",
        "calculationIdentityDigest",
        "calculationRequestId",
        "authorizationId",
        "reportDigest",
        "failureDigest",
    ]
    source_digest: _Digest | None = None


class AnalysisReferenceEvidenceItemV2(_EvidenceItemBaseV2):
    """One retained source reference; href is present only for a scoped resolver."""

    kind: Literal["SOURCE_REFERENCE"]
    reference_kind: _Text
    source_digest: _Digest | None = None


class AnalysisNumericResultEvidenceItemV2(_EvidenceItemBaseV2):
    """Identity of the immutable numeric report, without its coverage masks."""

    kind: Literal["NUMERIC_RESULT"]
    result_id: _Text
    report_digest: _Digest
    numeric_result_identity_digest: _Digest
    computed_at: datetime

    @field_validator("computed_at")
    @classmethod
    def _computed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("computedAt must be UTC")
        return value


class AnalysisLimitationEvidenceItemV2(_EvidenceItemBaseV2):
    """One blocker, result limitation, or other explicit reason."""

    kind: Literal["LIMITATION"]
    source: Literal["BLOCKER", "RESULT"]
    code: _ReasonCode
    epoch: Literal["BASELINE", "CURRENT"] | None = None
    evidence_ref: _Text | None = None
    detail: Annotated[str, StringConstraints(min_length=1, max_length=512)] | None = None


type AnalysisEvidenceItemV2 = Annotated[
    AnalysisEpochEvidenceItemV2
    | AnalysisCalculationEvidenceItemV2
    | AnalysisEvaluationEvidenceItemV2
    | AnalysisCheckpointEvidenceItemV2
    | AnalysisAuthorityEvidenceItemV2
    | AnalysisReferenceEvidenceItemV2
    | AnalysisNumericResultEvidenceItemV2
    | AnalysisLimitationEvidenceItemV2,
    Field(discriminator="kind"),
]


class AnalysisEvidencePageV2(_CamelModel):
    """At most 32 evidence records; each evaluation item can retain all 64 reasons."""

    analysis_id: _Text
    evidence_revision: Annotated[int, Field(ge=1)]
    evidence_digest: _Digest
    items: tuple[AnalysisEvidenceItemV2, ...] = Field(max_length=32)
    next_cursor: _Cursor | None = None


class AnalysisCoverageRangeV2(_CamelModel):
    """Metadata for one inclusive byte range of the separate coverage resource."""

    analysis_id: _Text
    coverage_digest: _Digest
    total_length_bytes: Annotated[int, Field(ge=1, le=2**63 - 1)]
    range_start: Annotated[int, Field(ge=0, le=2**63 - 1)]
    range_end: Annotated[int, Field(ge=0, le=2**63 - 1)]
    content_length_bytes: Annotated[int, Field(ge=1, le=65_536)]

    @model_validator(mode="after")
    def _range_is_one_bounded_inclusive_range(self) -> Self:
        if self.range_end < self.range_start or self.range_end >= self.total_length_bytes:
            raise ValueError("coverage byte range must lie within the resource")
        if self.content_length_bytes != self.range_end - self.range_start + 1:
            raise ValueError("Content-Length must match the inclusive byte range")
        if self.content_length_bytes > 65_536:
            raise ValueError("coverage byte range must not exceed 64 KiB")
        return self


__all__ = [
    "AnalysisCoverageRangeV2",
    "AnalysisCoverageSummaryV2",
    "AnalysisAuthorityEvidenceItemV2",
    "AnalysisCalculationEvidenceItemV2",
    "AnalysisCheckpointEvidenceItemV2",
    "AnalysisEpochEvidenceItemV2",
    "AnalysisEvidenceItemV2",
    "AnalysisEvaluationEvidenceItemV2",
    "AnalysisEvidencePageV2",
    "AnalysisLimitationEvidenceItemV2",
    "AnalysisListItemV2",
    "AnalysisListPageV2",
    "AnalysisNumericResultEvidenceItemV2",
    "AnalysisReferenceEvidenceItemV2",
    "AnalysisResultSummaryV2",
    "AnalysisViewV2",
]
