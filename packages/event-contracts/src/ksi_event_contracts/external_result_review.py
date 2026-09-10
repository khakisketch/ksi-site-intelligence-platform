"""Immutable, grounded review and planning-only reobservation proposal records.

These contracts retain the exact external relative-volume source chain that a
human may review.  They contain neither flight coordinates nor acquisition or
Mission authority.  A later Core-only authority port rechecks their current
dependencies before asking the accepted 5A WorkOrder kernel to append one
planning-only successor.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    Digest,
    ExternalPairUseDecisionV1,
)
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeExecutionPolicyV1,
    ExternalRelativeVolumeReportV1,
    ExternalRelativeVolumeRequestV1,
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
)
from ksi_event_contracts.external_reobservation import (
    ExternalReobservationProposalAuthorityV1,
    ExternalWorkAreaSnapshotV1,
)

_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)\Z")
_BoundedText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
_Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]

_FACTUAL_LIMITATIONS: tuple[str, ...] = (
    "RELATIVE_VOLUME_IS_OPERATIONAL_ONLY",
    "ABSOLUTE_ACCURACY_NOT_CLAIMED",
    "NO_AUTOMATIC_REOBSERVATION_THRESHOLD",
)


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _require_utc_wire(value: object, field_name: str) -> object:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a UTC RFC3339 timestamp or datetime")
    return value


def _require_utc(value: datetime, field_name: str) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{field_name} must be UTC")
    return value


class _FrozenResultReviewModel(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always", extra="forbid")


class ExternalResultReviewAuthorityV1(_FrozenResultReviewModel):
    """Exact server-resolved authority retained with one reviewed report.

    The type is deliberately independent of the Core 4B implementation class.
    A later adapter must construct it from actual Core history; callers never
    submit this model through a public route.
    """

    contract_version: Literal["external-result-review-authority.v1"] = (
        "external-result-review-authority.v1"
    )
    organization_id: _BoundedText
    site_id: _BoundedText
    current_work_order_id: _BoundedText
    decision_id: _BoundedText
    decision_digest: Digest
    compatibility_mapping_digest: Digest
    baseline: ExternalVolumeInputBindingV1
    current: ExternalVolumeInputBindingV1
    evidence_record_digests: tuple[Digest, ...] = Field(min_length=1, max_length=64)
    validation_policy_digest: Digest
    zone_snapshot: ExternalVolumeZoneSnapshotV1
    execution_policy: ExternalRelativeVolumeExecutionPolicyV1
    authorized_actor_ids: tuple[_BoundedText, ...] = Field(min_length=1, max_length=64)
    valid_from: datetime
    valid_until: datetime
    historical_authority_digest: Digest
    baseline_rmse_m: StrictFloat | None = Field(default=None, ge=0.0, le=1e300)
    current_rmse_m: StrictFloat | None = Field(default=None, ge=0.0, le=1e300)
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
    def _binds_full_authority(self) -> ExternalResultReviewAuthorityV1:
        if self.valid_from >= self.valid_until:
            raise ValueError("authority validity interval must be ordered")
        if len(set(self.evidence_record_digests)) != len(self.evidence_record_digests):
            raise ValueError("evidenceRecordDigests must be unique")
        if len(set(self.authorized_actor_ids)) != len(self.authorized_actor_ids):
            raise ValueError("authorizedActorIds must be unique")
        if (
            self.current.subject.work_order_id != self.current_work_order_id
            or self.baseline.subject.organization_id != self.organization_id
            or self.current.subject.organization_id != self.organization_id
            or self.baseline.subject.site_id != self.site_id
            or self.current.subject.site_id != self.site_id
            or self.zone_snapshot.organization_id != self.organization_id
            or self.zone_snapshot.site_id != self.site_id
            or self.execution_policy.policy_digest is None
            or self.zone_snapshot.definition_digest is None
        ):
            raise ValueError("review authority does not bind its exact source scope")
        if not math.isfinite(self.maximum_zone_area_m2):
            raise ValueError("maximumZoneAreaM2 must be finite")
        if any(
            value is not None and not math.isfinite(value)
            for value in (self.baseline_rmse_m, self.current_rmse_m)
        ):
            raise ValueError("RMSE values must be finite when present")
        if self.authority_digest is not None and self.authority_digest != self.canonical_digest():
            raise ValueError("authorityDigest does not match canonical review authority")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"authority_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalResultReviewAuthorityV1:
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


class ExternalResultReviewReceiptV1(_FrozenResultReviewModel):
    """A durable exact review of a server-resolved external relative-volume report."""

    contract_version: Literal["external-result-review-receipt.v1"] = (
        "external-result-review-receipt.v1"
    )
    review_ref: _BoundedText
    organization_id: _BoundedText
    site_id: _BoundedText
    source_work_order_id: _BoundedText
    report_ref: _BoundedText
    request: ExternalRelativeVolumeRequestV1
    report: ExternalRelativeVolumeReportV1
    authority: ExternalResultReviewAuthorityV1
    decision: ExternalPairUseDecisionV1
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
    def _binds_exact_grounded_source(self) -> ExternalResultReviewReceiptV1:
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
            or request.current_work_order_id != request.current.subject.work_order_id
            or request.decision_id != authority.decision_id
            or request.decision_digest != authority.decision_digest
            or request.baseline != authority.baseline
            or request.current != authority.current
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
            or report.payload.baseline_dsm_digest != request.baseline.observed_sha256
            or report.payload.current_dsm_digest != request.current.observed_sha256
            or report.payload.zone_snapshot_digest != authority.zone_snapshot.canonical_digest()
            or report.payload.execution_policy_digest
            != authority.execution_policy.canonical_digest()
            or report.payload.algorithm_build_digest
            != authority.execution_policy.algorithm_build_digest
            or report.payload.config_digest != authority.execution_policy.config_digest
        ):
            raise ValueError("review report does not match sealed request authority")
        if (
            decision.use != "RELATIVE_VOLUME"
            or decision.verdict is not DecisionVerdict.ELIGIBLE
            or decision.decision_id != request.decision_id
            or decision.decision_digest != request.decision_digest
            or decision.compatibility_mapping_digest != authority.compatibility_mapping_digest
            or decision.baseline_subject != request.baseline.subject
            or decision.current_subject != request.current.subject
            or decision.policy_digest != request.validation_policy_digest
            or decision.baseline_inspection_report_digest
            != request.baseline.inspection_report_digest
            or decision.current_inspection_report_digest != request.current.inspection_report_digest
            or decision.evidence_record_digests != request.evidence_record_digests
            or decision.zone != request.zone_snapshot.to_zone_reference()
        ):
            raise ValueError("review decision does not match the exact relative-volume source")
        if tuple(self.factual_limitations) != _FACTUAL_LIMITATIONS:
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

    def sealed(self) -> ExternalResultReviewReceiptV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"review_digest": validated.canonical_digest()}, deep=True
        )


class ExternalReobservationProposalV1(_FrozenResultReviewModel):
    """One human-authored, grounded planning proposal; approval remains separate."""

    contract_version: Literal["external-reobservation-proposal.v1"] = (
        "external-reobservation-proposal.v1"
    )
    proposal_ref: _BoundedText
    version: StrictInt = Field(ge=1)
    organization_id: _BoundedText
    site_id: _BoundedText
    source_work_order_id: _BoundedText
    review_ref: _BoundedText
    review_digest: Digest
    report_ref: _BoundedText
    report_digest: Digest
    decision_digest: Digest
    zone_digest: Digest
    evidence_digests: tuple[Digest, ...] = Field(min_length=1, max_length=64)
    target_work_areas: tuple[ExternalWorkAreaSnapshotV1, ...] = Field(min_length=1, max_length=1)
    reason: _Reason | None = None
    created_by: _BoundedText
    created_at: datetime
    proposal_digest: Digest | None = None

    @field_validator("created_at", mode="before")
    @classmethod
    def _created_at_is_wire_utc(cls, value: object) -> object:
        return _require_utc_wire(value, "createdAt")

    @field_validator("created_at")
    @classmethod
    def _created_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "createdAt")

    @model_validator(mode="after")
    def _has_one_sealed_target(self) -> ExternalReobservationProposalV1:
        if len(set(self.evidence_digests)) != len(self.evidence_digests):
            raise ValueError("evidenceDigests must be unique")
        if len({item.work_area_id for item in self.target_work_areas}) != 1:
            raise ValueError("proposal must select exactly one target WorkArea")
        if any(
            item.snapshot_digest is None or item.snapshot_digest != item.canonical_digest()
            for item in self.target_work_areas
        ):
            raise ValueError("proposal target must be a sealed WorkArea snapshot")
        if self.proposal_digest is not None and self.proposal_digest != self.canonical_digest():
            raise ValueError("proposalDigest does not match canonical proposal")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"proposal_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalReobservationProposalV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"proposal_digest": validated.canonical_digest()}, deep=True
        )

    def approval_authority(self) -> ExternalReobservationProposalAuthorityV1:
        if self.proposal_digest is None or self.proposal_digest != self.canonical_digest():
            raise ValueError("proposal must be sealed before it becomes approval authority")
        return ExternalReobservationProposalAuthorityV1(
            proposal_id=self.proposal_ref,
            proposal_version=self.version,
            proposal_digest=self.proposal_digest,
            organization_id=self.organization_id,
            site_id=self.site_id,
            source_work_order_id=self.source_work_order_id,
            report_digest=self.report_digest,
            decision_digest=self.decision_digest,
            zone_digest=self.zone_digest,
            evidence_digests=self.evidence_digests,
            target_work_areas=self.target_work_areas,
        ).sealed()


def external_result_review_receipt_wire_dict(
    receipt: ExternalResultReviewReceiptV1,
) -> dict[str, Any]:
    return receipt.sealed().model_dump(by_alias=True, mode="json", exclude_none=False)


def external_reobservation_proposal_wire_dict(
    proposal: ExternalReobservationProposalV1,
) -> dict[str, Any]:
    return proposal.sealed().model_dump(by_alias=True, mode="json", exclude_none=False)


__all__ = [
    "ExternalReobservationProposalV1",
    "ExternalResultReviewAuthorityV1",
    "ExternalResultReviewReceiptV1",
    "external_reobservation_proposal_wire_dict",
    "external_result_review_receipt_wire_dict",
]
