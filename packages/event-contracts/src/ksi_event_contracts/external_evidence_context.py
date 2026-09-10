"""Exact checkpoint measurement rules and independently resolved attestation content.

A sealed model is an integrity witness, never proof of authorization. Core must
resolve the whole context from an independent trusted authority and exact sealed
inputs; neither customer declaration nor a rule/digest string establishes trust.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Annotated, Any, Literal, Self

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
from ksi_event_contracts.external_artifact_validation import Digest, SealedExternalSubjectV1

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Basis = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)]
Bound = Annotated[StrictFloat, Field(ge=0, le=1e300)]
_UTC_PATTERN = (
    r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T"
    r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|\+00:00)$"
)

UtcTime = Annotated[datetime, Field(json_schema_extra={"pattern": _UTC_PATTERN})]


class _ContextModel(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    @field_validator("*", mode="before")
    @classmethod
    def _strict_time(cls, value: object, info: Any) -> object:
        if info.field_name in {"confirmed_at", "active_from", "active_until"}:
            if isinstance(value, datetime):
                offset = value.utcoffset()
                if offset is None or offset.total_seconds() != 0:
                    raise ValueError("context timestamps must be UTC")
            elif not isinstance(value, str) or re.fullmatch(_UTC_PATTERN, value) is None:
                raise ValueError("context timestamps must be UTC RFC3339")
        return value

    def _payload(self, digest_field: str) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude={digest_field})

    def _digest(self, digest_field: str) -> str:
        return (
            "sha256:"
            + hashlib.sha256(canonical_json_bytes(self._payload(digest_field))).hexdigest()
        )

    def _seal(self, digest_field: str) -> Self:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={digest_field: validated._digest(digest_field)}, deep=True
        )


class ExternalIndependenceAttestationV1(_ContextModel):
    """Full separately authorized confirmation; never populated from independenceBasis."""

    contract_version: Literal["external-independence-attestation.v1"] = (
        "external-independence-attestation.v1"
    )
    attestation_id: Text
    evidence_manifest_digest: Digest
    subject_digest: Digest
    target_dsm_observed_sha256: Digest
    confirmed_by_actor_id: Text
    confirmed_at: UtcTime
    reconstruction_exclusion_basis: Basis
    synthetic_test_only: StrictBool
    attestation_digest: Digest | None = None

    @model_validator(mode="after")
    def _validate_digest(self) -> Self:
        if (
            self.attestation_digest is not None
            and self.attestation_digest != self.canonical_digest()
        ):
            raise ValueError("attestation digest differs from its exact content")
        return self

    def canonical_digest(self) -> str:
        return self._digest("attestation_digest")

    def sealed(self) -> Self:
        return self._seal("attestation_digest")


class ExternalEvidenceMeasurementContextV1(_ContextModel):
    """No numeric defaults or implicit independence; all rules are authority data."""

    contract_version: Literal["external-evidence-measurement-context.v1"] = (
        "external-evidence-measurement-context.v1"
    )
    context_id: Text
    subject: SealedExternalSubjectV1
    evidence_manifest_digest: Digest
    evidence_observed_sha256: Digest
    evidence_observed_size_bytes: StrictInt = Field(gt=0)
    target_dsm_artifact_id: Text
    target_dsm_observed_sha256: Digest
    policy_digest: Digest
    measurement_execution_manifest_digest: Digest
    rule_id: Literal["CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1"]
    csv_horizontal_crs: Basis
    csv_vertical_reference_digest: Digest
    minimum_checkpoint_count: StrictInt = Field(ge=1, le=1_000_000)
    maximum_checkpoint_count: StrictInt = Field(ge=1, le=1_000_000)
    maximum_rmse_m: Bound
    maximum_abs_mean_error_m: Bound
    maximum_abs_error_m: Bound
    independent_attestation: ExternalIndependenceAttestationV1 | None
    authorized_actor_ids: tuple[Text, ...] = Field(min_length=1, max_length=64)
    active_from: UtcTime
    active_until: UtcTime
    synthetic_test_only: StrictBool
    context_digest: Digest | None = None

    @model_validator(mode="after")
    def _validate_context(self) -> Self:
        if self.minimum_checkpoint_count > self.maximum_checkpoint_count:
            raise ValueError("checkpoint count interval is empty")
        if self.active_from >= self.active_until:
            raise ValueError("context authority interval is empty")
        if len(set(self.authorized_actor_ids)) != len(self.authorized_actor_ids):
            raise ValueError("context actors must be unique")
        attestation = self.independent_attestation
        if attestation is not None and (
            attestation.attestation_digest is None
            or attestation.attestation_digest != attestation.canonical_digest()
            or attestation.evidence_manifest_digest != self.evidence_manifest_digest
            or attestation.subject_digest != self.subject.canonical_digest()
            or attestation.target_dsm_observed_sha256 != self.target_dsm_observed_sha256
            or attestation.synthetic_test_only != self.synthetic_test_only
            or attestation.confirmed_by_actor_id not in self.authorized_actor_ids
            or attestation.confirmed_at > self.active_from
        ):
            raise ValueError("independent attestation does not bind context authority")
        if self.context_digest is not None and self.context_digest != self.canonical_digest():
            raise ValueError("context digest differs from its exact content")
        return self

    def canonical_digest(self) -> str:
        return self._digest("context_digest")

    def sealed(self) -> Self:
        return self._seal("context_digest")

    def is_active_at(self, now: datetime) -> bool:
        return now.utcoffset() is not None and self.active_from <= now < self.active_until
