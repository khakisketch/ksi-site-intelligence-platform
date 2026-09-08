"""Additive customer-owned reconstruction declarations and observed byte manifests.

ADR-KSI-036 keeps these records distinct from KSI-managed ProcessingJob,
source-media authority, processing profiles, file-format validation, and any
quantitative-eligibility decision.  A submission records a customer claim;
the manifest records only bytes separately observed by a KSI service.
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
    StrictFloat,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.vertical_reference import VerticalReference, VerticalReferenceSource

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"
_BASENAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
_OBJECT_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*$"
_RFC3339_AWARE_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
)
_BoundedText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
_LongBoundedText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)
]


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _require_datetime_wire_value(value: object, field_name: str) -> object:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or _RFC3339_AWARE_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be a timezone-bearing RFC3339 date-time string or datetime"
        )
    return value


class _FrozenExternalModel(_CamelModel):
    """Freeze externally supplied contract snapshots after validation."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")


class ExternalDeclaredVerticalReferenceV1(VerticalReference):
    """A bounded external declaration, never a pipeline-produced fact."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    basis: _LongBoundedText
    source: Literal[VerticalReferenceSource.USER_DECLARED]


class ExternalReconstructionSubmissionV1Producer(_FrozenExternalModel):
    """Customer declaration of the software run; it is never KSI observation."""

    software_name: _BoundedText
    software_version: _BoundedText
    build_identifier: _BoundedText | None
    producer_run_identifier: _BoundedText | None
    configuration_digest: str | None = Field(pattern=_DIGEST_PATTERN)
    completed_at: datetime | None

    @field_validator("completed_at", mode="before")
    @classmethod
    def _completed_at_is_datetime_wire_value(cls, value: object) -> object:
        if value is None:
            return value
        return _require_datetime_wire_value(value, "completedAt")

    @field_validator("completed_at")
    @classmethod
    def _completed_at_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_aware(value, "completedAt")


class ExternalReconstructionSubmissionV1Input(_FrozenExternalModel):
    """Customer declaration about originals retained outside KSI."""

    raw_media_stored_by_ksi: Literal[False]
    original_retention_locus: Literal["customer_workstation"]
    local_input_manifest_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    image_count: StrictInt | None = Field(default=None, ge=1, le=10_000_000)
    capture_started_at: datetime | None = None
    capture_ended_at: datetime | None = None

    @field_validator("raw_media_stored_by_ksi", mode="before")
    @classmethod
    def _raw_media_stored_by_ksi_is_boolean(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("rawMediaStoredByKsi must be a JSON boolean")
        return value

    @field_validator("capture_started_at", "capture_ended_at", mode="before")
    @classmethod
    def _capture_times_are_datetime_wire_values(cls, value: object) -> object:
        if value is None:
            return value
        return _require_datetime_wire_value(value, "capture time")

    @model_validator(mode="after")
    def _capture_pair_is_aware_and_ordered(self) -> ExternalReconstructionSubmissionV1Input:
        start = self.capture_started_at
        end = self.capture_ended_at
        if (start is None) != (end is None):
            raise ValueError("captureStartedAt and captureEndedAt must both be absent or present")
        if start is not None and end is not None:
            _require_aware(start, "captureStartedAt")
            _require_aware(end, "captureEndedAt")
            if start > end:
                raise ValueError("captureStartedAt must not be after captureEndedAt")
        return self


class ExternalArtifactDeclarationV1(_FrozenExternalModel):
    """A declared external output, intentionally without a KSI object key."""

    artifact_id: _BoundedText
    kind: ProcessingArtifactKind
    file_name: str = Field(min_length=1, max_length=255, pattern=_BASENAME_PATTERN)
    format: _BoundedText
    content_type: _BoundedText
    declared_sha256: str = Field(pattern=_SHA256_HEX_PATTERN)
    declared_size_bytes: StrictInt = Field(ge=1, le=2**63 - 1)
    declared_crs: _LongBoundedText | None = None
    declared_vertical_reference: ExternalDeclaredVerticalReferenceV1 | None = None
    declared_gsd_m: StrictFloat | None = Field(default=None, gt=0)

    @field_validator("file_name")
    @classmethod
    def _file_name_is_a_safe_basename(cls, value: str) -> str:
        if value != value.strip() or value in {".", ".."}:
            raise ValueError("fileName must be a safe basename")
        return value

    @model_validator(mode="after")
    def _declared_values_are_safe(self) -> ExternalArtifactDeclarationV1:
        if self.declared_gsd_m is not None and not math.isfinite(self.declared_gsd_m):
            raise ValueError("declaredGsdM must be finite")
        if (
            self.declared_vertical_reference is not None
            and self.declared_vertical_reference.source is not VerticalReferenceSource.USER_DECLARED
        ):
            raise ValueError("declaredVerticalReference.source must be user_declared")
        return self


class ExternalReconstructionSubmissionV1(_FrozenExternalModel):
    """A sealed customer declaration, not an execution or eligibility record."""

    contract_version: Literal["external-reconstruction-submission.v1"] = (
        "external-reconstruction-submission.v1"
    )
    submission_id: _BoundedText
    revision: StrictInt = Field(ge=1)
    organization_id: _BoundedText
    site_id: _BoundedText
    observation_epoch_id: _BoundedText
    submitted_at: datetime
    submitted_by: _BoundedText
    execution_responsibility: Literal["customer_operator"] = "customer_operator"
    execution_locus: Literal["customer_workstation"] = "customer_workstation"
    producer_declaration: ExternalReconstructionSubmissionV1Producer
    input_declaration: ExternalReconstructionSubmissionV1Input
    artifacts: tuple[ExternalArtifactDeclarationV1, ...] = Field(min_length=1, max_length=8)
    submission_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)

    @field_validator("submitted_at", mode="before")
    @classmethod
    def _submitted_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_datetime_wire_value(value, "submittedAt")

    @field_validator("submitted_at")
    @classmethod
    def _submitted_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "submittedAt")

    @model_validator(mode="after")
    def _validate_submission(self) -> ExternalReconstructionSubmissionV1:
        kinds = [artifact.kind for artifact in self.artifacts]
        if kinds.count(ProcessingArtifactKind.ORTHO) != 1:
            raise ValueError("artifacts must contain exactly one ortho")
        if len(set(artifact.artifact_id for artifact in self.artifacts)) != len(self.artifacts):
            raise ValueError("artifactId values must be unique")
        if len(set(kinds)) != len(kinds):
            raise ValueError("each artifact kind may appear at most once")
        object.__setattr__(
            self,
            "artifacts",
            tuple(sorted(self.artifacts, key=lambda artifact: artifact.artifact_id)),
        )
        if self.submission_digest is not None and self.submission_digest != self.canonical_digest():
            raise ValueError("submissionDigest does not match canonical submission content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        payload = self.model_dump(by_alias=True, mode="json", exclude={"submission_digest"})
        payload["artifacts"] = sorted(
            payload["artifacts"], key=lambda artifact: artifact["artifactId"]
        )
        return payload

    def canonical_digest(self) -> str:
        payload = canonical_json_bytes(self.canonical_payload())
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    def sealed(self) -> ExternalReconstructionSubmissionV1:
        validated = type(self).model_validate(self.__dict__)
        payload = validated.model_dump(by_alias=True, mode="json")
        payload["submissionDigest"] = validated.canonical_digest()
        return type(self).model_validate(payload)

    @classmethod
    def digest_for_wire(cls, payload: dict[str, Any]) -> str:
        """Compute a fresh candidate digest through the sole canonicalization path.

        This helper intentionally ignores a supplied digest because callers use it to
        calculate a replacement candidate.  ``sealed`` and factory boundaries instead
        revalidate supplied digests.  Parsing here ensures timestamp spelling, numeric
        normalization, omitted defaults, whitespace, and ordering exactly match the
        canonical payload later verified by :meth:`model_validate`.
        """
        candidate = dict(payload)
        candidate.pop("submissionDigest", None)
        return cls.model_validate(candidate).canonical_digest()


class ExternalReconstructionManifestEntryV1(_FrozenExternalModel):
    """A server-observed byte identity; not a format or quality verdict."""

    artifact_id: _BoundedText
    kind: ProcessingArtifactKind
    object_key: str = Field(min_length=1, max_length=1_024, pattern=_OBJECT_KEY_PATTERN)
    observed_sha256: str = Field(pattern=_SHA256_HEX_PATTERN)
    observed_size_bytes: StrictInt = Field(ge=1, le=2**63 - 1)
    observed_content_type: _BoundedText

    @field_validator("object_key")
    @classmethod
    def _object_key_is_safe_relative_path(cls, value: str) -> str:
        if value.startswith("/") or "//" in value or any(
            segment in {".", ".."} for segment in value.split("/")
        ):
            raise ValueError("objectKey must be a safe relative object key")
        return value


class ExternalReconstructionManifestV1(_FrozenExternalModel):
    """Immutable observed-byte binding for one exact external submission revision."""

    contract_version: Literal["external-reconstruction-manifest.v1"] = (
        "external-reconstruction-manifest.v1"
    )
    manifest_id: _BoundedText
    submission_id: _BoundedText
    submission_revision: StrictInt = Field(ge=1)
    submission_digest: str = Field(pattern=_DIGEST_PATTERN)
    organization_id: _BoundedText
    site_id: _BoundedText
    observation_epoch_id: _BoundedText
    observed_at: datetime
    observed_by_service: _BoundedText
    entries: tuple[ExternalReconstructionManifestEntryV1, ...] = Field(min_length=1, max_length=8)
    manifest_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)

    @field_validator("observed_at", mode="before")
    @classmethod
    def _observed_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_datetime_wire_value(value, "observedAt")

    @field_validator("observed_at")
    @classmethod
    def _observed_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "observedAt")

    @model_validator(mode="after")
    def _validate_manifest(self) -> ExternalReconstructionManifestV1:
        if len(set(entry.artifact_id for entry in self.entries)) != len(self.entries):
            raise ValueError("manifest artifactId values must be unique")
        if len(set(entry.object_key for entry in self.entries)) != len(self.entries):
            raise ValueError("manifest objectKey values must be unique")
        object.__setattr__(
            self, "entries", tuple(sorted(self.entries, key=lambda entry: entry.artifact_id))
        )
        if self.manifest_digest is not None and self.manifest_digest != self.canonical_digest():
            raise ValueError("manifestDigest does not match canonical manifest content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        payload = self.model_dump(by_alias=True, mode="json", exclude={"manifest_digest"})
        payload["entries"] = sorted(payload["entries"], key=lambda entry: entry["artifactId"])
        return payload

    def canonical_digest(self) -> str:
        payload = canonical_json_bytes(self.canonical_payload())
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    def sealed(self) -> ExternalReconstructionManifestV1:
        validated = type(self).model_validate(self.__dict__)
        payload = validated.model_dump(by_alias=True, mode="json")
        payload["manifestDigest"] = validated.canonical_digest()
        return type(self).model_validate(payload)

    @classmethod
    def from_submission(
        cls,
        submission: ExternalReconstructionSubmissionV1,
        *,
        manifest_id: str,
        observed_at: datetime,
        observed_by_service: str,
        organization_id: str,
        site_id: str,
        observation_epoch_id: str,
        entries: tuple[ExternalReconstructionManifestEntryV1, ...],
    ) -> ExternalReconstructionManifestV1:
        validated_submission = ExternalReconstructionSubmissionV1.model_validate(
            submission.__dict__
        )
        validated_entries = tuple(
            ExternalReconstructionManifestEntryV1.model_validate(entry.__dict__)
            for entry in entries
        )
        expected_scope: dict[str, str] = {
            "organizationId": validated_submission.organization_id,
            "siteId": validated_submission.site_id,
            "observationEpochId": validated_submission.observation_epoch_id,
        }
        supplied_scope = {
            "organizationId": organization_id,
            "siteId": site_id,
            "observationEpochId": observation_epoch_id,
        }
        for field_name, expected in expected_scope.items():
            if supplied_scope[field_name] != expected:
                raise ValueError(f"{field_name} must match the submission scope")
        if validated_submission.submission_digest is None:
            raise ValueError("submissionDigest must be sealed before observation")
        declared = {artifact.artifact_id: artifact for artifact in validated_submission.artifacts}
        if {entry.artifact_id for entry in validated_entries} != set(declared):
            raise ValueError("manifest entries must bind every declared artifact exactly once")
        for entry in validated_entries:
            artifact = declared[entry.artifact_id]
            if entry.kind is not artifact.kind:
                raise ValueError("manifest kind must match the declared artifact kind")
            if entry.observed_sha256 != artifact.declared_sha256:
                raise ValueError("observedSha256 must match declaredSha256")
            if entry.observed_size_bytes != artifact.declared_size_bytes:
                raise ValueError("observedSizeBytes must match declaredSizeBytes")
        return cls(
            manifest_id=manifest_id,
            submission_id=validated_submission.submission_id,
            submission_revision=validated_submission.revision,
            submission_digest=validated_submission.submission_digest,
            organization_id=organization_id,
            site_id=site_id,
            observation_epoch_id=observation_epoch_id,
            observed_at=observed_at,
            observed_by_service=observed_by_service,
            entries=validated_entries,
        ).sealed()


def external_reconstruction_submission_wire_dict(
    submission: ExternalReconstructionSubmissionV1,
) -> dict[str, Any]:
    """Serialize a sealed customer declaration for the v1 JSON Schema."""
    return submission.sealed().model_dump(by_alias=True, mode="json")


def external_reconstruction_manifest_wire_dict(
    manifest: ExternalReconstructionManifestV1,
) -> dict[str, Any]:
    """Serialize a sealed observed-byte manifest for the v1 JSON Schema."""
    return manifest.sealed().model_dump(by_alias=True, mode="json")


__all__ = [
    "ExternalArtifactDeclarationV1",
    "ExternalDeclaredVerticalReferenceV1",
    "ExternalReconstructionManifestEntryV1",
    "ExternalReconstructionManifestV1",
    "ExternalReconstructionSubmissionV1",
    "ExternalReconstructionSubmissionV1Input",
    "ExternalReconstructionSubmissionV1Producer",
    "external_reconstruction_manifest_wire_dict",
    "external_reconstruction_submission_wire_dict",
]
