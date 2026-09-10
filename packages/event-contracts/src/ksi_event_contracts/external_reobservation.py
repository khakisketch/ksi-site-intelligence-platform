"""Immutable external reobservation approval and planning-only bindings.

The contracts bind a server-resolved external proposal to one later WorkOrder.
They do not grant acquisition, Mission, flight-coordinate, or device authority.
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
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.observation_work_order import TemporalCoherencePolicy
from ksi_event_contracts.work_area import assert_polygon_is_usable

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_RFC3339_AWARE_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)"
)

Digest = Annotated[str, Field(pattern=_DIGEST_PATTERN)]
_BoundedText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
_IdempotencyKey = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _require_aware_datetime_wire_value(value: object, field_name: str) -> object:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or _RFC3339_AWARE_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be a timezone-bearing RFC3339 date-time string or datetime"
        )
    return value


def _require_utc(value: datetime, field_name: str) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


class _FrozenExternalReobservationModel(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")


class ExternalWorkAreaSnapshotV1(_FrozenExternalReobservationModel):
    """An immutable, owned WorkArea revision used as a reobservation target."""

    work_area_id: _BoundedText
    revision: Literal[1] = 1
    polygon: dict[str, Any]
    crs: _BoundedText
    snapshot_digest: Digest | None = None

    @model_validator(mode="after")
    def _is_polygon_and_digest_matches(self) -> ExternalWorkAreaSnapshotV1:
        assert_polygon_is_usable(self.polygon, crs=self.crs)
        # Canonical WorkArea validates the horizontal pair. The external wire
        # also promises every optional coordinate component is a bounded number.
        for ring in self.polygon["coordinates"]:
            for position in ring:
                for component in position:
                    if (
                        type(component) not in (int, float)
                        or abs(component) > 1e300
                        or not math.isfinite(component)
                    ):
                        raise ValueError("every target coordinate must be finite and bounded")
        if self.snapshot_digest is not None and self.snapshot_digest != self.canonical_digest():
            raise ValueError("snapshotDigest does not match canonical WorkArea snapshot")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"snapshot_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalWorkAreaSnapshotV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"snapshot_digest": validated.canonical_digest()}, deep=True
        )


class ExternalReobservationApprovalInputV1(_FrozenExternalReobservationModel):
    """Minimal immutable approval input; acceptance is resolved by a Core-owned port."""

    contract_version: Literal["external-reobservation-approval-input.v1"] = (
        "external-reobservation-approval-input.v1"
    )
    organization_id: _BoundedText
    site_id: _BoundedText
    source_work_order_id: _BoundedText
    proposal_id: _BoundedText
    proposal_version: StrictInt = Field(ge=1)
    proposal_digest: Digest
    report_digest: Digest
    decision_digest: Digest
    zone_digest: Digest
    evidence_digests: tuple[Digest, ...] = Field(min_length=1, max_length=64)
    approval_input_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_exact_external_inputs(self) -> ExternalReobservationApprovalInputV1:
        if len(set(self.evidence_digests)) != len(self.evidence_digests):
            raise ValueError("evidenceDigests must be unique")
        if (
            self.approval_input_digest is not None
            and self.approval_input_digest != self.canonical_digest()
        ):
            raise ValueError("approvalInputDigest does not match canonical approval input")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"approval_input_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalReobservationApprovalInputV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"approval_input_digest": validated.canonical_digest()}, deep=True
        )


class ExternalReobservationProposalAuthorityV1(_FrozenExternalReobservationModel):
    """Server-resolved accepted proposal snapshot, never a customer assertion."""

    contract_version: Literal["external-reobservation-proposal-authority.v1"] = (
        "external-reobservation-proposal-authority.v1"
    )
    proposal_id: _BoundedText
    proposal_version: StrictInt = Field(ge=1)
    proposal_digest: Digest
    organization_id: _BoundedText
    site_id: _BoundedText
    source_work_order_id: _BoundedText
    report_digest: Digest
    decision_digest: Digest
    zone_digest: Digest
    evidence_digests: tuple[Digest, ...] = Field(min_length=1, max_length=64)
    target_work_areas: tuple[ExternalWorkAreaSnapshotV1, ...] = Field(min_length=1, max_length=64)
    authority_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_sealed_targets_and_digest(self) -> ExternalReobservationProposalAuthorityV1:
        if len(set(self.evidence_digests)) != len(self.evidence_digests):
            raise ValueError("evidenceDigests must be unique")
        if len({item.work_area_id for item in self.target_work_areas}) != len(
            self.target_work_areas
        ):
            raise ValueError("targetWorkAreas must have unique workAreaIds")
        if any(
            item.snapshot_digest is None or item.snapshot_digest != item.canonical_digest()
            for item in self.target_work_areas
        ):
            raise ValueError("targetWorkAreas must carry sealed WorkArea snapshots")
        if self.authority_digest is not None and self.authority_digest != self.canonical_digest():
            raise ValueError("authorityDigest does not match canonical proposal authority")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"authority_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalReobservationProposalAuthorityV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"authority_digest": validated.canonical_digest()}, deep=True
        )


class ExternalPlanningOnlyWorkOrderBindingV1(_FrozenExternalReobservationModel):
    """Separate successor binding that preserves the closed WorkOrder v1 wire."""

    contract_version: Literal["external-planning-only-work-order-binding.v1"] = (
        "external-planning-only-work-order-binding.v1"
    )
    mode: Literal["EXTERNAL_REOBSERVATION_PLANNING"] = "EXTERNAL_REOBSERVATION_PLANNING"
    organization_id: _BoundedText
    site_id: _BoundedText
    source_work_order_id: _BoundedText
    successor_work_order_id: _BoundedText
    approval_id: _BoundedText
    approved_by: _BoundedText
    approved_at: datetime
    proposal_id: _BoundedText
    proposal_version: StrictInt = Field(ge=1)
    proposal_digest: Digest
    report_digest: Digest
    decision_digest: Digest
    zone_digest: Digest
    evidence_digests: tuple[Digest, ...] = Field(min_length=1, max_length=64)
    target_work_areas: tuple[ExternalWorkAreaSnapshotV1, ...] = Field(min_length=1, max_length=64)
    temporal_policy: TemporalCoherencePolicy | None = None
    acquisition_run_allowed: Literal[False] = False
    mission_issuance_allowed: Literal[False] = False
    binding_digest: Digest | None = None

    @field_validator("approved_at", mode="before")
    @classmethod
    def _approved_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_aware_datetime_wire_value(value, "approvedAt")

    @field_validator("approved_at")
    @classmethod
    def _approved_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "approvedAt")

    @model_validator(mode="after")
    def _binds_sealed_targets_and_digest(self) -> ExternalPlanningOnlyWorkOrderBindingV1:
        if len(set(self.evidence_digests)) != len(self.evidence_digests):
            raise ValueError("evidenceDigests must be unique")
        if len({item.work_area_id for item in self.target_work_areas}) != len(
            self.target_work_areas
        ):
            raise ValueError("targetWorkAreas must have unique workAreaIds")
        if any(
            item.snapshot_digest is None or item.snapshot_digest != item.canonical_digest()
            for item in self.target_work_areas
        ):
            raise ValueError("targetWorkAreas must carry sealed WorkArea snapshots")
        if self.binding_digest is not None and self.binding_digest != self.canonical_digest():
            raise ValueError("bindingDigest does not match canonical planning binding")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"binding_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalPlanningOnlyWorkOrderBindingV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"binding_digest": validated.canonical_digest()}, deep=True
        )


class ExternalReobservationApprovalReceiptV1(_FrozenExternalReobservationModel):
    """Immutable human approval receipt for the exact external proposal snapshot."""

    contract_version: Literal["external-reobservation-approval-receipt.v1"] = (
        "external-reobservation-approval-receipt.v1"
    )
    approval_id: _BoundedText
    organization_id: _BoundedText
    site_id: _BoundedText
    source_work_order_id: _BoundedText
    successor_work_order_id: _BoundedText
    proposal_id: _BoundedText
    proposal_version: StrictInt = Field(ge=1)
    proposal_digest: Digest
    approval_input_digest: Digest
    binding_digest: Digest
    idempotency_key: _IdempotencyKey
    approved_by: _BoundedText
    approved_at: datetime
    receipt_digest: Digest | None = None

    @field_validator("approved_at", mode="before")
    @classmethod
    def _approved_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_aware_datetime_wire_value(value, "approvedAt")

    @field_validator("approved_at")
    @classmethod
    def _approved_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "approvedAt")

    @model_validator(mode="after")
    def _digest_matches(self) -> ExternalReobservationApprovalReceiptV1:
        if self.receipt_digest is not None and self.receipt_digest != self.canonical_digest():
            raise ValueError("receiptDigest does not match canonical approval receipt")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"receipt_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalReobservationApprovalReceiptV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"receipt_digest": validated.canonical_digest()}, deep=True
        )


__all__ = [
    "Digest",
    "ExternalPlanningOnlyWorkOrderBindingV1",
    "ExternalReobservationApprovalInputV1",
    "ExternalReobservationApprovalReceiptV1",
    "ExternalReobservationProposalAuthorityV1",
    "ExternalWorkAreaSnapshotV1",
]
