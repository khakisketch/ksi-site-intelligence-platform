"""Human-use reviews of exact V2 calculations, never V1 reports or accuracy approvals."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import ConfigDict, Field, StrictInt, StringConstraints, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import Digest

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Comment = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
ReviewLimitations = tuple[
    Literal["HUMAN_REVIEW_IS_NOT_ACCURACY_VALIDATION"],
    Literal["HUMAN_REVIEW_IS_NOT_FIELD_OR_FLIGHT_AUTHORIZATION"],
    Literal["RELATIVE_VOLUME_IS_NOT_SETTLEMENT_OR_COMPLETION_PROOF"],
]
REVIEW_LIMITATIONS: ReviewLimitations = (
    "HUMAN_REVIEW_IS_NOT_ACCURACY_VALIDATION",
    "HUMAN_REVIEW_IS_NOT_FIELD_OR_FLIGHT_AUTHORIZATION",
    "RELATIVE_VOLUME_IS_NOT_SETTLEMENT_OR_COMPLETION_PROOF",
)


class _Frozen(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always", extra="forbid")


class AnalysisReviewEvaluationV2(_Frozen):
    epoch: Literal["BASELINE", "CURRENT"]
    evaluation_id: Text
    revision: StrictInt = Field(ge=1)
    evaluation_digest: Digest


class AnalysisReviewTargetV2(_Frozen):
    result_id: Text
    result_revision: StrictInt = Field(ge=1, le=1)
    report_digest: Digest
    numeric_result_identity_digest: Digest
    calculation_identity_digest: Digest
    admission_digest: Digest
    evaluations: tuple[AnalysisReviewEvaluationV2, AnalysisReviewEvaluationV2]

    @model_validator(mode="after")
    def _ordered_epochs(self) -> Self:
        if tuple(item.epoch for item in self.evaluations) != ("BASELINE", "CURRENT"):
            raise ValueError("review evaluations must be ordered BASELINE, CURRENT")
        return self


class CreateAnalysisReviewV2(_Frozen):
    target: AnalysisReviewTargetV2
    decision: Literal["ACKNOWLEDGED", "NEEDS_FOLLOW_UP"]
    comment: Comment


class AnalysisReviewReceiptV2(_Frozen):
    contract_version: Literal["external-analysis-review-receipt.v2"] = (
        "external-analysis-review-receipt.v2"
    )
    review_ref: Text
    organization_id: Text
    site_id: Text
    work_area_id: Text
    analysis_id: Text
    reviewer_id: Text
    target: AnalysisReviewTargetV2
    decision: Literal["ACKNOWLEDGED", "NEEDS_FOLLOW_UP"]
    comment: Comment
    reviewed_at: datetime
    factual_limitations: ReviewLimitations = REVIEW_LIMITATIONS
    receipt_digest: Digest | None = None

    def canonical_digest(self) -> str:
        wire = self.model_dump(by_alias=True, mode="json")
        wire.pop("receiptDigest")
        return "sha256:" + hashlib.sha256(canonical_json_bytes(wire)).hexdigest()

    def sealed(self) -> Self:
        return self.model_copy(update={"receipt_digest": self.canonical_digest()})

    @model_validator(mode="after")
    def _exact_semantics(self) -> Self:
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() != UTC.utcoffset(
            self.reviewed_at
        ):
            raise ValueError("reviewedAt must be UTC")
        if self.factual_limitations != REVIEW_LIMITATIONS:
            raise ValueError("human review cannot remove factual limitations")
        if self.receipt_digest is not None and self.receipt_digest != self.canonical_digest():
            raise ValueError("review receipt digest is invalid")
        return self


class AnalysisReviewListV2(_CamelModel):
    """Historical receipts; no implication that a receipt reviews today's target."""

    items: tuple[AnalysisReviewReceiptV2, ...] = Field(max_length=50)
    next_cursor: Text | None = None
