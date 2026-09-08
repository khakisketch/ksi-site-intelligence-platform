"""Immutable declared, observed, and Core-adjudicated external-evidence records.

Declaration is intentionally not independence proof.  Worker measurements stay
observed facts, and the Core result is a distinct later record.  These models
do not authenticate callers or make a trusted-runtime authority claim.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import (
    Field,
    StrictFloat,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from ksi_event_contracts.external_artifact_validation import (
    Digest,
    FactClass,
    SealedExternalSubjectV1,
    _FrozenExternalModel,
    _require_aware,
    _require_aware_datetime_wire_value,
)

_OBJECT_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*$"
_BoundedText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
_EvidenceText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)
]
_CoreReason = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]{0,127}$"
    ),
]


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class EvidenceIndependence(StrEnum):
    DECLARED = "DECLARED"


class EvidenceCoreVerdict(StrEnum):
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class ExternalEvidenceDeclarationV1(_FrozenExternalModel):
    """Customer/admin evidence declaration; independence remains only declared."""

    contract_version: Literal["external-evidence-declaration.v1"] = (
        "external-evidence-declaration.v1"
    )
    evidence_id: _BoundedText = Field(min_length=1, max_length=255)
    subject: SealedExternalSubjectV1
    subject_digest: Digest
    target_dsm_artifact_id: _BoundedText = Field(min_length=1, max_length=255)
    target_dsm_observed_sha256: Digest
    declared_content_digest: Digest
    declared_content_type: _BoundedText = Field(min_length=1, max_length=255)
    independence: Literal[EvidenceIndependence.DECLARED] = EvidenceIndependence.DECLARED
    independence_basis: _EvidenceText = Field(min_length=1, max_length=1_000)
    declared_at: datetime
    declaration_digest: Digest | None = None

    @field_validator("declared_at", mode="before")
    @classmethod
    def _declared_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_aware_datetime_wire_value(value, "declaredAt")

    @field_validator("declared_at")
    @classmethod
    def _declared_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "declaredAt")

    @model_validator(mode="after")
    def _declared_scope_and_digest_are_exact(self) -> ExternalEvidenceDeclarationV1:
        if self.subject_digest != self.subject.canonical_digest():
            raise ValueError("subjectDigest must bind subject")
        if (
            self.declaration_digest is not None
            and self.declaration_digest != self.canonical_digest()
        ):
            raise ValueError("declarationDigest does not match canonical declaration content")
        return self

    @property
    def fact_class(self) -> FactClass:
        return FactClass.DECLARED

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"declaration_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalEvidenceDeclarationV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"declaration_digest": validated.canonical_digest()}, deep=True
        )


class ExternalEvidenceManifestV1(_FrozenExternalModel):
    """Core-observed separate evidence bytes, linked one way to the target DSM."""

    contract_version: Literal["external-evidence-manifest.v1"] = "external-evidence-manifest.v1"
    evidence_manifest_id: _BoundedText = Field(min_length=1, max_length=255)
    evidence_id: _BoundedText = Field(min_length=1, max_length=255)
    declaration_digest: Digest
    subject: SealedExternalSubjectV1
    subject_digest: Digest
    target_dsm_artifact_id: _BoundedText = Field(min_length=1, max_length=255)
    target_dsm_observed_sha256: Digest
    observed_object_digest: Digest
    observed_size_bytes: StrictInt = Field(gt=0)
    observed_content_type: _BoundedText = Field(min_length=1, max_length=255)
    server_object_key: str = Field(min_length=1, max_length=1_024, pattern=_OBJECT_KEY_PATTERN)
    observed_at: datetime
    evidence_manifest_digest: Digest | None = None

    @field_validator("observed_at", mode="before")
    @classmethod
    def _observed_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_aware_datetime_wire_value(value, "observedAt")

    @field_validator("observed_at")
    @classmethod
    def _observed_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "observedAt")

    @field_validator("server_object_key")
    @classmethod
    def _server_key_is_relative(cls, value: str) -> str:
        if (
            value.startswith("/")
            or "//" in value
            or any(segment in {".", ".."} for segment in value.split("/"))
        ):
            raise ValueError("serverObjectKey must be a safe relative object key")
        return value

    @model_validator(mode="after")
    def _observed_scope_and_digest_are_exact(self) -> ExternalEvidenceManifestV1:
        if self.subject_digest != self.subject.canonical_digest():
            raise ValueError("subjectDigest must bind subject")
        if (
            self.evidence_manifest_digest is not None
            and self.evidence_manifest_digest != self.canonical_digest()
        ):
            raise ValueError("evidenceManifestDigest does not match canonical evidence manifest")
        return self

    @property
    def fact_class(self) -> FactClass:
        return FactClass.OBSERVED

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"evidence_manifest_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalEvidenceManifestV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"evidence_manifest_digest": validated.canonical_digest()}, deep=True
        )


class ExternalEvidenceValidationRequestV1(_FrozenExternalModel):
    """Core-issued validation request bound to exact evidence, DSM, and policy digests."""

    contract_version: Literal["external-evidence-validation-request.v1"] = (
        "external-evidence-validation-request.v1"
    )
    validation_id: _BoundedText = Field(min_length=1, max_length=255)
    evidence_manifest_digest: Digest
    subject_digest: Digest
    target_dsm_observed_sha256: Digest
    policy_id: _BoundedText = Field(min_length=1, max_length=255)
    policy_version: StrictInt = Field(ge=1)
    policy_digest: Digest
    issued_at: datetime
    idempotency_key: _BoundedText = Field(min_length=1, max_length=255)

    @field_validator("issued_at", mode="before")
    @classmethod
    def _issued_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_aware_datetime_wire_value(value, "issuedAt")

    @field_validator("issued_at")
    @classmethod
    def _issued_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "issuedAt")


class ExternalEvidenceMeasurementPayloadV1(_FrozenExternalModel):
    """Worker measurement facts; this payload cannot self-declare a Core verdict."""

    fact_class: Literal[FactClass.OBSERVED] = FactClass.OBSERVED
    validation_id: _BoundedText = Field(min_length=1, max_length=255)
    evidence_manifest_digest: Digest
    target_dsm_observed_sha256: Digest
    policy_digest: Digest
    measured_checkpoint_count: StrictInt = Field(gt=0)
    mean_error_m: StrictFloat
    mae_m: StrictFloat = Field(ge=0)
    rmse_m: StrictFloat = Field(ge=0)
    max_abs_error_m: StrictFloat = Field(ge=0)
    measured_at: datetime

    @field_validator("measured_at", mode="before")
    @classmethod
    def _measured_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_aware_datetime_wire_value(value, "measuredAt")

    @field_validator("measured_at")
    @classmethod
    def _measured_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "measuredAt")

    @model_validator(mode="after")
    def _metrics_are_finite_and_self_consistent(self) -> ExternalEvidenceMeasurementPayloadV1:
        metrics = (self.mean_error_m, self.mae_m, self.rmse_m, self.max_abs_error_m)
        if not all(math.isfinite(value) for value in metrics):
            raise ValueError("measurement metrics must be finite")
        tolerance = 1e-12
        if abs(self.mean_error_m) > self.mae_m + tolerance:
            raise ValueError("abs(meanErrorM) cannot exceed maeM")
        if self.mae_m > self.rmse_m + tolerance:
            raise ValueError("maeM cannot exceed rmseM")
        if self.rmse_m > self.max_abs_error_m + tolerance:
            raise ValueError("rmseM cannot exceed maxAbsErrorM")
        return self


class ExternalEvidenceRecordV1(_FrozenExternalModel):
    """Core verdict record distinct from declaration and worker measurement facts."""

    contract_version: Literal["external-evidence-record.v1"] = "external-evidence-record.v1"
    evidence_record_id: _BoundedText = Field(min_length=1, max_length=255)
    validation_id: _BoundedText = Field(min_length=1, max_length=255)
    subject_digest: Digest
    evidence_manifest_digest: Digest
    target_dsm_observed_sha256: Digest
    policy_digest: Digest
    measurement_payload: ExternalEvidenceMeasurementPayloadV1 | None = None
    core_verdict: EvidenceCoreVerdict
    core_reason: _CoreReason | None = None
    core_recorded_at: datetime
    evidence_record_digest: Digest | None = None

    @field_validator("core_recorded_at", mode="before")
    @classmethod
    def _core_recorded_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_aware_datetime_wire_value(value, "coreRecordedAt")

    @field_validator("core_recorded_at")
    @classmethod
    def _core_recorded_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "coreRecordedAt")

    @model_validator(mode="after")
    def _record_binds_payload_and_core_result(self) -> ExternalEvidenceRecordV1:
        payload = self.measurement_payload
        if payload is not None:
            if payload.validation_id != self.validation_id:
                raise ValueError("measurementPayload.validationId must bind validationId")
            if payload.evidence_manifest_digest != self.evidence_manifest_digest:
                raise ValueError(
                    "measurementPayload.evidenceManifestDigest must bind evidenceManifestDigest"
                )
            if payload.target_dsm_observed_sha256 != self.target_dsm_observed_sha256:
                raise ValueError("measurementPayload.targetDsmObservedSha256 must bind target DSM")
            if payload.policy_digest != self.policy_digest:
                raise ValueError("measurementPayload.policyDigest must bind policyDigest")
        if self.core_verdict is EvidenceCoreVerdict.REJECTED and self.core_reason is None:
            raise ValueError("REJECTED Core verdict requires coreReason")
        if self.core_verdict is EvidenceCoreVerdict.VALIDATED:
            if self.core_reason is not None:
                raise ValueError("VALIDATED Core verdict must not carry coreReason")
            if payload is None:
                raise ValueError("VALIDATED Core verdict requires measurementPayload")
        if self.evidence_record_digest is not None and (
            self.evidence_record_digest != self.canonical_digest()
        ):
            raise ValueError("evidenceRecordDigest does not match canonical evidence record")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"evidence_record_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalEvidenceRecordV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"evidence_record_digest": validated.canonical_digest()}, deep=True
        )


def _wire(model: _FrozenExternalModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=False)


def external_evidence_declaration_wire_dict(
    declaration: ExternalEvidenceDeclarationV1,
) -> dict[str, Any]:
    return _wire(declaration.sealed())


def external_evidence_manifest_wire_dict(manifest: ExternalEvidenceManifestV1) -> dict[str, Any]:
    return _wire(manifest.sealed())


def external_evidence_validation_request_wire_dict(
    request: ExternalEvidenceValidationRequestV1,
) -> dict[str, Any]:
    return _wire(ExternalEvidenceValidationRequestV1.model_validate(request.__dict__))


def external_evidence_record_wire_dict(record: ExternalEvidenceRecordV1) -> dict[str, Any]:
    return _wire(record.sealed())


__all__ = [
    "EvidenceCoreVerdict",
    "EvidenceIndependence",
    "ExternalEvidenceDeclarationV1",
    "ExternalEvidenceManifestV1",
    "ExternalEvidenceMeasurementPayloadV1",
    "ExternalEvidenceRecordV1",
    "ExternalEvidenceValidationRequestV1",
    "external_evidence_declaration_wire_dict",
    "external_evidence_manifest_wire_dict",
    "external_evidence_record_wire_dict",
    "external_evidence_validation_request_wire_dict",
]
