"""Immutable, grounded review record for one external single-volume report.

A sibling of ``external_result_review``: it retains the exact single-epoch
source chain a human reviewed and carries neither flight coordinates nor
acquisition or Mission authority.  The receipt union below lets one review
journal hold relative and single receipts, dispatched on ``contractVersion``;
the relative receipt, its schema and its sealed digest are unchanged.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    TypeAdapter,
    field_validator,
    model_validator,
)

from ksi_event_contracts.external_artifact_validation import DecisionVerdict, Digest
from ksi_event_contracts.external_relative_volume import (
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
)
from ksi_event_contracts.external_result_review import (
    ExternalResultReviewReceiptV1,
    _BoundedText,
    _digest,
    _FrozenResultReviewModel,
    _require_utc,
    _require_utc_wire,
)
from ksi_event_contracts.external_single_volume import (
    ExternalSingleVolumeDecisionV1,
    ExternalSingleVolumeExecutionPolicyV1,
    ExternalSingleVolumeReportV1,
    ExternalSingleVolumeRequestV1,
)

SINGLE_VOLUME_REVIEW_FACTUAL_LIMITATIONS: tuple[str, str, str] = (
    "SINGLE_VOLUME_IS_OPERATIONAL_ONLY",
    "ABSOLUTE_ACCURACY_NOT_CLAIMED",
    "NO_AUTOMATIC_REOBSERVATION_THRESHOLD",
)


class ExternalSingleVolumeResultReviewAuthorityV1(_FrozenResultReviewModel):
    """Exact server-resolved single-epoch authority retained with one reviewed report.

    Independent of the Core authority class; a Core adapter constructs it from
    actual Core history and callers never submit it through a public route.
    """

    contract_version: Literal["external-single-volume-result-review-authority.v1"] = (
        "external-single-volume-result-review-authority.v1"
    )
    organization_id: _BoundedText
    site_id: _BoundedText
    current_work_order_id: _BoundedText
    decision_id: _BoundedText
    decision_digest: Digest
    compatibility_mapping_digest: Digest
    target: ExternalVolumeInputBindingV1
    evidence_record_digests: tuple[Digest, ...] = Field(min_length=1, max_length=1)
    validation_policy_digest: Digest
    zone_snapshot: ExternalVolumeZoneSnapshotV1
    execution_policy: ExternalSingleVolumeExecutionPolicyV1
    authorized_actor_ids: tuple[_BoundedText, ...] = Field(min_length=1, max_length=64)
    valid_from: datetime
    valid_until: datetime
    historical_authority_digest: Digest
    target_rmse_m: StrictFloat | None = Field(default=None, ge=0.0, le=1e300)
    maximum_zone_cell_count: StrictInt = Field(ge=1, le=100_000_000)
    maximum_zone_area_m2: StrictFloat = Field(gt=0.0, le=1e300)
    synthetic_test_only: StrictBool
    authority_digest: Digest | None = None

    @field_validator("valid_from", "valid_until", mode="before")
    @classmethod
    def _times_are_wire_utc(cls, value: object, info: Any) -> object:
        return _require_utc_wire(value, info.field_name)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _require_utc(value, info.field_name)

    @model_validator(mode="after")
    def _binds_full_authority(self) -> ExternalSingleVolumeResultReviewAuthorityV1:
        if self.valid_from >= self.valid_until:
            raise ValueError("authority validity interval must be ordered")
        if len(set(self.evidence_record_digests)) != len(self.evidence_record_digests):
            raise ValueError("evidenceRecordDigests must be unique")
        if len(set(self.authorized_actor_ids)) != len(self.authorized_actor_ids):
            raise ValueError("authorizedActorIds must be unique")
        if (
            self.target.subject.work_order_id != self.current_work_order_id
            or self.target.subject.organization_id != self.organization_id
            or self.target.subject.site_id != self.site_id
            or self.zone_snapshot.organization_id != self.organization_id
            or self.zone_snapshot.site_id != self.site_id
            or self.execution_policy.policy_digest is None
            or self.zone_snapshot.definition_digest is None
        ):
            raise ValueError("review authority does not bind its exact source scope")
        if not math.isfinite(self.maximum_zone_area_m2):
            raise ValueError("maximumZoneAreaM2 must be finite")
        if self.target_rmse_m is not None and not math.isfinite(self.target_rmse_m):
            raise ValueError("targetRmseM must be finite when present")
        if self.authority_digest is not None and self.authority_digest != self.canonical_digest():
            raise ValueError("authorityDigest does not match canonical review authority")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"authority_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalSingleVolumeResultReviewAuthorityV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"authority_digest": validated.canonical_digest()}, deep=True
        )

    def is_active_at(self, evaluated_at: datetime) -> bool:
        offset = evaluated_at.utcoffset()
        return (
            evaluated_at.tzinfo is not None
            and offset is not None
            and offset.total_seconds() == 0
            and self.valid_from <= evaluated_at < self.valid_until
        )


class ExternalSingleVolumeResultReviewReceiptV1(_FrozenResultReviewModel):
    """A durable exact review of a server-resolved external single-volume report."""

    contract_version: Literal["external-single-volume-result-review-receipt.v1"] = (
        "external-single-volume-result-review-receipt.v1"
    )
    review_ref: _BoundedText
    organization_id: _BoundedText
    site_id: _BoundedText
    source_work_order_id: _BoundedText
    report_ref: _BoundedText
    request: ExternalSingleVolumeRequestV1
    report: ExternalSingleVolumeReportV1
    authority: ExternalSingleVolumeResultReviewAuthorityV1
    decision: ExternalSingleVolumeDecisionV1
    factual_limitations: tuple[_BoundedText, ...] = Field(min_length=3, max_length=3)
    reviewed_at: datetime
    review_digest: Digest | None = None

    @field_validator("reviewed_at", mode="before")
    @classmethod
    def _reviewed_at_is_wire_utc(cls, value: object) -> object:
        return _require_utc_wire(value, "reviewedAt")

    @field_validator("reviewed_at")
    @classmethod
    def _reviewed_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "reviewedAt")

    @model_validator(mode="after")
    def _binds_exact_grounded_source(self) -> ExternalSingleVolumeResultReviewReceiptV1:
        request, report, authority, decision = (
            self.request,
            self.report,
            self.authority,
            self.decision,
        )
        if (
            request.request_digest is None
            or request.request_digest != request.canonical_digest()
            or report.report_digest is None
            or report.report_digest != report.canonical_digest()
            or authority.authority_digest is None
            or authority.authority_digest != authority.canonical_digest()
            or decision.decision_digest is None
            or decision.decision_digest != decision.canonical_digest()
        ):
            raise ValueError("review requires sealed request, report, authority, and decision")
        if (
            self.organization_id != authority.organization_id
            or self.site_id != authority.site_id
            or self.source_work_order_id != authority.current_work_order_id
            or self.source_work_order_id != request.current_work_order_id
            or request.current_work_order_id != request.target.subject.work_order_id
            or request.decision_id != authority.decision_id
            or request.decision_digest != authority.decision_digest
            or request.target != authority.target
            or request.evidence_record_digests != authority.evidence_record_digests
            or request.validation_policy_digest != authority.validation_policy_digest
            or request.zone_snapshot != authority.zone_snapshot
            or request.execution_policy_digest != authority.execution_policy.policy_digest
        ):
            raise ValueError("review request does not match retained authority")
        if (
            report.request_id != request.request_id
            or report.request_digest != request.request_digest
            or report.payload.request_digest != request.request_digest
            or report.payload.decision_digest != request.decision_digest
            or report.payload.target_dsm_digest != request.target.observed_sha256
            or report.payload.zone_snapshot_digest != authority.zone_snapshot.canonical_digest()
            or report.payload.execution_policy_digest
            != authority.execution_policy.canonical_digest()
            or report.payload.algorithm_build_digest
            != authority.execution_policy.algorithm_build_digest
            or report.payload.config_digest != authority.execution_policy.config_digest
        ):
            raise ValueError("review report does not match sealed request authority")
        if (
            decision.use != "SINGLE_VOLUME"
            or decision.verdict is not DecisionVerdict.ELIGIBLE
            or decision.decision_id != request.decision_id
            or decision.decision_digest != request.decision_digest
            or decision.compatibility_mapping_digest != authority.compatibility_mapping_digest
            or decision.subject != request.target.subject
            or decision.policy_digest != request.validation_policy_digest
            or decision.inspection_report_digest != request.target.inspection_report_digest
            or decision.evidence_record_digests != request.evidence_record_digests
            or decision.zone != request.zone_snapshot.to_zone_reference()
        ):
            raise ValueError("review decision does not match the exact single-volume source")
        if tuple(self.factual_limitations) != SINGLE_VOLUME_REVIEW_FACTUAL_LIMITATIONS:
            raise ValueError(
                "review factual limitations must be the deterministic product limitations"
            )
        if self.review_digest is not None and self.review_digest != self.canonical_digest():
            raise ValueError("reviewDigest does not match canonical review receipt")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"review_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalSingleVolumeResultReviewReceiptV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"review_digest": validated.canonical_digest()}, deep=True
        )


ExternalResultReviewReceipt = Annotated[
    ExternalResultReviewReceiptV1 | ExternalSingleVolumeResultReviewReceiptV1,
    Field(discriminator="contract_version"),
]

_RECEIPT_ADAPTER: TypeAdapter[
    ExternalResultReviewReceiptV1 | ExternalSingleVolumeResultReviewReceiptV1
] = TypeAdapter(ExternalResultReviewReceipt)


def parse_external_result_review_receipt(
    raw: object,
) -> ExternalResultReviewReceiptV1 | ExternalSingleVolumeResultReviewReceiptV1:
    """Validate one stored review receipt of either family by ``contractVersion``."""
    return _RECEIPT_ADAPTER.validate_python(raw)


def external_single_volume_result_review_receipt_wire_dict(
    receipt: ExternalSingleVolumeResultReviewReceiptV1,
) -> dict[str, Any]:
    return receipt.sealed().model_dump(by_alias=True, mode="json", exclude_none=False)


__all__ = [
    "SINGLE_VOLUME_REVIEW_FACTUAL_LIMITATIONS",
    "ExternalResultReviewReceipt",
    "ExternalSingleVolumeResultReviewAuthorityV1",
    "ExternalSingleVolumeResultReviewReceiptV1",
    "external_single_volume_result_review_receipt_wire_dict",
    "parse_external_result_review_receipt",
]
