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
from datetime import date, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

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
from pydantic import (
    ValidationError as _PydanticValidationError,
)

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.vertical_reference import VerticalReference, VerticalReferenceSource

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
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
            # V1 records accepted an instantaneous declared capture interval.
            # Keep recovery and digest validation compatible with those sealed
            # records; the new external-ingress boundary enforces positive time.
            if start > end:
                raise ValueError("captureStartedAt must be earlier than captureEndedAt")
        return self


class ExternalReconstructionSubmissionV3Producer(_FrozenExternalModel):
    """Customer declaration of the software run, or an explicit unknown.

    An unknown producer is typed nulls under ``producerKnowledge=UNKNOWN``.
    The fabricated label ``"unknown"`` is never stuffed into a would-be
    version string. When the engine is known but its version is not, PARTIAL
    keeps the known name with a null version instead of dropping the known
    fact or inventing a version; a version without a product name stays
    UNKNOWN. ``sourceNote`` carries the citation (for example a publisher page
    that names only a date); it is a declaration, never an observed fact.
    """

    producer_knowledge: Literal["DECLARED", "PARTIAL", "UNKNOWN"]
    software_name: _BoundedText | None
    software_version: _BoundedText | None
    build_identifier: _BoundedText | None
    producer_run_identifier: _BoundedText | None
    configuration_digest: str | None = Field(pattern=_DIGEST_PATTERN)
    completed_at: datetime | None
    source_note: _LongBoundedText | None

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

    @model_validator(mode="after")
    def _knowledge_matches_presence(self) -> ExternalReconstructionSubmissionV3Producer:
        if self.producer_knowledge == "UNKNOWN":
            if self.software_name is not None or self.software_version is not None:
                raise ValueError("unknown producer must not carry software name/version")
        elif self.producer_knowledge == "PARTIAL":
            if self.software_name is None or self.software_version is not None:
                raise ValueError(
                    "partial producer keeps the known software name with a null version"
                )
            if self.software_name.lower() == "unknown":
                raise ValueError(
                    "softwareName must not be the fabricated label 'unknown'; "
                    "use producerKnowledge UNKNOWN with nulls"
                )
        else:
            if self.software_name is None or self.software_version is None:
                raise ValueError("declared producer requires software name and version")
            for label, value in (
                ("softwareName", self.software_name),
                ("softwareVersion", self.software_version),
            ):
                if value.lower() == "unknown":
                    raise ValueError(
                        f"{label} must not be the fabricated label 'unknown'; "
                        "use producerKnowledge UNKNOWN with nulls"
                    )
        return self


class ExternalUpstreamSourceReferenceV3(_FrozenExternalModel):
    """Typed bounded reference to the upstream public source, never a measurement.

    This records where the bytes came from (portal URI), which upstream bytes
    were taken (their sha when known), and what licence the publisher page
    states. The licence string is a customer declaration transcribed from the
    publisher — it grants KSI no data right and verifies nothing. The upstream
    producer stays unknown; only the local derivative step (below) may carry a
    known tool identity.

    The URI is stored exactly as declared (no normalization rewrite, so the
    canonical digest stays stable) but must be a safe http(s) reference: no
    javascript/data/file schemes, no embedded credentials, no whitespace or
    control characters, and a real host. It is never fetched — there is no
    SSRF surface — and rejection messages never echo the supplied value.
    """

    source_uri: _LongBoundedText
    source_sha256: str | None = Field(default=None, pattern=_SHA256_HEX_PATTERN)
    licence_declaration: _LongBoundedText | None = None
    retrieval_note: _LongBoundedText | None = None

    @field_validator("source_uri")
    @classmethod
    def _source_uri_is_a_safe_public_reference(cls, value: str) -> str:
        if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            raise ValueError("sourceUri must not contain whitespace or control characters")
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise ValueError("sourceUri must use http or https")
        if "@" in parsed.netloc:
            raise ValueError("sourceUri must not embed credentials")
        if not parsed.hostname:
            raise ValueError("sourceUri must carry a host")
        return value


class ExternalDerivativeExportV3(_FrozenExternalModel):
    """Known local export step that produced the registered derived bytes.

    The originals (for example a 4-band RGBA JPEG-compressed ortho or a JP2
    ortho) are not relabelled here: this block names the actual tool and
    settings that exported the supported GeoTIFF derivatives now declared as
    artifacts. The tool identity is the exporter's, never the upstream
    reconstruction producer's.
    """

    tool_name: _BoundedText
    tool_version: _BoundedText
    settings_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    exported_at: datetime | None = None
    export_note: _LongBoundedText | None = None

    @field_validator("exported_at", mode="before")
    @classmethod
    def _exported_at_is_datetime_wire_value(cls, value: object) -> object:
        if value is None:
            return value
        return _require_datetime_wire_value(value, "exportedAt")

    @field_validator("exported_at")
    @classmethod
    def _exported_at_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_aware(value, "exportedAt")


class ExternalReconstructionSubmissionV3Input(_FrozenExternalModel):
    """Customer declaration about originals and capture timing with explicit gaps.

    Exact capture intervals stay strict datetimes when known. A known single
    calendar date without timezone/time is carried date-only
    (``captureBasis=DATE_ONLY``); unknown timing is ``captureBasis=UNKNOWN``
    with all time fields absent — never a midnight timestamp. Raw photos
    keep ``rawMediaStoredByKsi=false`` while their locus is declared honestly:
    ``customer_workstation`` only when the customer actually holds them,
    otherwise ``upstream_source`` (for example a public portal) or ``unknown``,
    with the citation in ``originalRetentionDetail``.
    """

    raw_media_stored_by_ksi: Literal[False]
    original_retention_locus: Literal["customer_workstation", "upstream_source", "unknown"]
    original_retention_detail: _LongBoundedText | None
    local_input_manifest_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    image_count: StrictInt | None = Field(default=None, ge=1, le=10_000_000)
    capture_started_at: datetime | None = None
    capture_ended_at: datetime | None = None
    capture_date: date | None = None
    capture_basis: Literal["EXACT_INTERVAL", "DATE_ONLY", "UNKNOWN"]
    upstream_source: ExternalUpstreamSourceReferenceV3 | None = None
    derivative_export: ExternalDerivativeExportV3 | None = None

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

    @field_validator("capture_date", mode="before")
    @classmethod
    def _capture_date_is_a_date_wire_value(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, datetime):
            raise ValueError("captureDate must be a calendar date, not a timestamp")
        if isinstance(value, date):
            return value
        if isinstance(value, str) and _DATE_PATTERN.fullmatch(value) is not None:
            return date.fromisoformat(value)
        raise ValueError("captureDate must be a YYYY-MM-DD calendar date string or date")

    @model_validator(mode="after")
    def _capture_basis_matches_presence(self) -> ExternalReconstructionSubmissionV3Input:
        start = self.capture_started_at
        end = self.capture_ended_at
        if self.capture_basis == "EXACT_INTERVAL":
            if self.capture_date is not None:
                raise ValueError("captureDate must be absent for an exact interval")
            if start is None or end is None:
                raise ValueError("EXACT_INTERVAL requires captureStartedAt and captureEndedAt")
            _require_aware(start, "captureStartedAt")
            _require_aware(end, "captureEndedAt")
            # V3 has no legacy sealed records, so a positive interval is strict.
            if start >= end:
                raise ValueError("captureStartedAt must be earlier than captureEndedAt")
        elif self.capture_basis == "DATE_ONLY":
            if self.capture_date is None:
                raise ValueError("DATE_ONLY requires captureDate")
            if start is not None or end is not None:
                raise ValueError(
                    "DATE_ONLY must not carry exact timestamps; unknown time stays unknown"
                )
        else:
            if self.capture_date is not None or start is not None or end is not None:
                raise ValueError("UNKNOWN capture must not carry any date or timestamps")
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


class ExternalReconstructionSubmissionV2(_FrozenExternalModel):
    """A customer declaration requiring one DSM, with an optional orthophoto.

    Declarations remain customer assertions. This version changes only the
    artifact-count contract and does not establish byte observation, quality,
    compatibility, or quantitative eligibility.
    """

    contract_version: Literal["external-reconstruction-submission.v2"] = (
        "external-reconstruction-submission.v2"
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
    def _validate_submission(self) -> ExternalReconstructionSubmissionV2:
        kinds = [artifact.kind for artifact in self.artifacts]
        if kinds.count(ProcessingArtifactKind.DSM) != 1:
            raise ValueError("artifacts must contain exactly one dsm")
        if kinds.count(ProcessingArtifactKind.ORTHO) > 1:
            raise ValueError("artifacts may contain at most one ortho")
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

    def sealed(self) -> ExternalReconstructionSubmissionV2:
        validated = type(self).model_validate(self.__dict__)
        payload = validated.model_dump(by_alias=True, mode="json")
        payload["submissionDigest"] = validated.canonical_digest()
        return type(self).model_validate(payload)

    @classmethod
    def digest_for_wire(cls, payload: dict[str, Any]) -> str:
        """Compute a candidate using the same validated canonical form as sealing."""
        candidate = dict(payload)
        candidate.pop("submissionDigest", None)
        return cls.model_validate(candidate).canonical_digest()


class ExternalReconstructionSubmissionV3(_FrozenExternalModel):
    """A customer declaration that tolerates honestly incomplete metadata.

    Unlike V1 (exactly one ortho) and V2 (exactly one DSM), V3 accepts an
    ortho-only or a DSM-only package (at most one of each, at least one of
    the two) so public or partially documented exports can be registered,
    inspected, and viewed. Unknown producers and date-only/unknown capture
    timing stay explicit nulls with a declared basis; analysis admission
    still refuses such epochs with typed blockers instead of inventing times.

    The top-level ``executionResponsibility='customer_operator'`` and
    ``executionLocus='customer_workstation'`` consts are the intake
    responsibility boundary, not an assertion of where any upstream
    reconstruction ran. They state that this declaration is customer-operated
    and assembled outside KSI execution (never a KSI-managed ProcessingJob,
    profile, or server run), per ADR-KSI-036 D1 (customer/KSI responsibility
    split) and D2 (separately identified externally produced result; no forged
    managed identity). The submission as a whole is "not an execution ...
    record" (V1 contract wording, unchanged); per-run facts live in
    ``producerDeclaration``/``inputDeclaration``/``upstreamSource``, where
    unknowns stay unknown. The consts are identical across V1/V2/V3 and can
    never express KSI execution.
    """

    contract_version: Literal["external-reconstruction-submission.v3"] = (
        "external-reconstruction-submission.v3"
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
    producer_declaration: ExternalReconstructionSubmissionV3Producer
    input_declaration: ExternalReconstructionSubmissionV3Input
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
    def _validate_submission(self) -> ExternalReconstructionSubmissionV3:
        kinds = [artifact.kind for artifact in self.artifacts]
        if kinds.count(ProcessingArtifactKind.DSM) > 1:
            raise ValueError("artifacts may contain at most one dsm")
        if kinds.count(ProcessingArtifactKind.ORTHO) > 1:
            raise ValueError("artifacts may contain at most one ortho")
        if ProcessingArtifactKind.DSM not in kinds and ProcessingArtifactKind.ORTHO not in kinds:
            raise ValueError("artifacts must contain a dsm or an ortho")
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

    def sealed(self) -> ExternalReconstructionSubmissionV3:
        validated = type(self).model_validate(self.__dict__)
        payload = validated.model_dump(by_alias=True, mode="json")
        payload["submissionDigest"] = validated.canonical_digest()
        return type(self).model_validate(payload)

    @classmethod
    def digest_for_wire(cls, payload: dict[str, Any]) -> str:
        """Compute a candidate using the same validated canonical form as sealing."""
        candidate = dict(payload)
        candidate.pop("submissionDigest", None)
        return cls.model_validate(candidate).canonical_digest()


ExternalReconstructionSubmission = (
    ExternalReconstructionSubmissionV1
    | ExternalReconstructionSubmissionV2
    | ExternalReconstructionSubmissionV3
)


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
        if (
            value.startswith("/")
            or "//" in value
            or any(segment in {".", ".."} for segment in value.split("/"))
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
        submission: ExternalReconstructionSubmission,
        *,
        manifest_id: str,
        observed_at: datetime,
        observed_by_service: str,
        organization_id: str,
        site_id: str,
        observation_epoch_id: str,
        entries: tuple[ExternalReconstructionManifestEntryV1, ...],
    ) -> ExternalReconstructionManifestV1:
        if isinstance(submission, ExternalReconstructionSubmissionV1):
            validated_submission: ExternalReconstructionSubmission = (
                ExternalReconstructionSubmissionV1.model_validate(submission.__dict__)
            )
        elif isinstance(submission, ExternalReconstructionSubmissionV2):
            validated_submission = ExternalReconstructionSubmissionV2.model_validate(
                submission.__dict__
            )
        elif isinstance(submission, ExternalReconstructionSubmissionV3):
            validated_submission = ExternalReconstructionSubmissionV3.model_validate(
                submission.__dict__
            )
        else:  # pragma: no cover - defensive runtime boundary for untyped callers
            raise TypeError("unsupported external reconstruction submission version")
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


def external_reconstruction_submission_v2_wire_dict(
    submission: ExternalReconstructionSubmissionV2,
) -> dict[str, Any]:
    """Serialize a sealed V2 customer declaration for its JSON Schema."""
    return submission.sealed().model_dump(by_alias=True, mode="json")


def parse_external_reconstruction_submission_v2(
    payload: dict[str, Any],
) -> ExternalReconstructionSubmissionV2:
    """Validate a V2 wire payload at the trusted application boundary.

    The JSON Schema describes structural constraints. This parser additionally
    enforces cross-artifact identity uniqueness and the canonical self-digest.
    """
    wire = _require_v2_wire_object_fields(
        payload,
        path="submission",
        fields=(
            "contractVersion",
            "submissionId",
            "revision",
            "organizationId",
            "siteId",
            "observationEpochId",
            "submittedAt",
            "submittedBy",
            "executionResponsibility",
            "executionLocus",
            "producerDeclaration",
            "inputDeclaration",
            "artifacts",
            "submissionDigest",
        ),
    )
    if wire["submissionDigest"] is None:
        raise ValueError("submissionDigest is required for a V2 wire payload")

    _require_v2_wire_object_fields(
        wire["producerDeclaration"],
        path="producerDeclaration",
        fields=(
            "softwareName",
            "softwareVersion",
            "buildIdentifier",
            "producerRunIdentifier",
            "configurationDigest",
            "completedAt",
        ),
    )
    _require_v2_wire_object_fields(
        wire["inputDeclaration"],
        path="inputDeclaration",
        fields=(
            "rawMediaStoredByKsi",
            "originalRetentionLocus",
            "localInputManifestDigest",
            "imageCount",
            "captureStartedAt",
            "captureEndedAt",
        ),
    )
    artifacts = wire["artifacts"]
    if not isinstance(artifacts, list):
        raise ValueError("artifacts must be an array")
    for index, artifact in enumerate(artifacts):
        artifact_path = f"artifacts[{index}]"
        artifact_object = _require_v2_wire_object_fields(
            artifact,
            path=artifact_path,
            fields=(
                "artifactId",
                "kind",
                "fileName",
                "format",
                "contentType",
                "declaredSha256",
                "declaredSizeBytes",
                "declaredCrs",
                "declaredVerticalReference",
                "declaredGsdM",
            ),
        )
        vertical_reference = artifact_object["declaredVerticalReference"]
        if vertical_reference is not None:
            _require_v2_wire_object_fields(
                vertical_reference,
                path=f"{artifact_path}.declaredVerticalReference",
                fields=("datum", "basis", "source"),
            )
    return ExternalReconstructionSubmissionV2.model_validate(payload)


def _require_v2_wire_object_fields(
    value: object,
    *,
    path: str,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    missing = [field for field in fields if field not in value]
    if missing:
        raise ValueError(f"{path} is missing required fields: {', '.join(missing)}")
    return value


def external_reconstruction_submission_v3_wire_dict(
    submission: ExternalReconstructionSubmissionV3,
) -> dict[str, Any]:
    """Serialize a sealed V3 customer declaration for its JSON Schema."""
    return submission.sealed().model_dump(by_alias=True, mode="json")


def parse_external_reconstruction_submission_v3(
    payload: dict[str, Any],
) -> ExternalReconstructionSubmissionV3:
    """Validate a V3 wire payload at the trusted application boundary.

    The JSON Schema describes structural constraints. This parser additionally
    enforces exact object fields, cross-artifact identity uniqueness, explicit
    unknown-producer/date-only/unknown-capture rules, and the canonical
    self-digest.
    """
    wire = _require_v2_wire_object_fields(
        payload,
        path="submission",
        fields=(
            "contractVersion",
            "submissionId",
            "revision",
            "organizationId",
            "siteId",
            "observationEpochId",
            "submittedAt",
            "submittedBy",
            "executionResponsibility",
            "executionLocus",
            "producerDeclaration",
            "inputDeclaration",
            "artifacts",
            "submissionDigest",
        ),
    )
    if wire["contractVersion"] != "external-reconstruction-submission.v3":
        raise ValueError("contractVersion must be external-reconstruction-submission.v3")
    if wire["submissionDigest"] is None:
        raise ValueError("submissionDigest is required for a V3 wire payload")

    _require_v2_wire_object_fields(
        wire["producerDeclaration"],
        path="producerDeclaration",
        fields=(
            "producerKnowledge",
            "softwareName",
            "softwareVersion",
            "buildIdentifier",
            "producerRunIdentifier",
            "configurationDigest",
            "completedAt",
            "sourceNote",
        ),
    )
    _require_v2_wire_object_fields(
        wire["inputDeclaration"],
        path="inputDeclaration",
        fields=(
            "rawMediaStoredByKsi",
            "originalRetentionLocus",
            "originalRetentionDetail",
            "localInputManifestDigest",
            "imageCount",
            "captureStartedAt",
            "captureEndedAt",
            "captureDate",
            "captureBasis",
            "upstreamSource",
            "derivativeExport",
        ),
    )
    upstream_source = wire["inputDeclaration"]["upstreamSource"]
    if upstream_source is not None:
        _require_v2_wire_object_fields(
            upstream_source,
            path="inputDeclaration.upstreamSource",
            fields=(
                "sourceUri",
                "sourceSha256",
                "licenceDeclaration",
                "retrievalNote",
            ),
        )
    derivative_export = wire["inputDeclaration"]["derivativeExport"]
    if derivative_export is not None:
        _require_v2_wire_object_fields(
            derivative_export,
            path="inputDeclaration.derivativeExport",
            fields=(
                "toolName",
                "toolVersion",
                "settingsDigest",
                "exportedAt",
                "exportNote",
            ),
        )
    artifacts = wire["artifacts"]
    if not isinstance(artifacts, list):
        raise ValueError("artifacts must be an array")
    for index, artifact in enumerate(artifacts):
        artifact_path = f"artifacts[{index}]"
        artifact_object = _require_v2_wire_object_fields(
            artifact,
            path=artifact_path,
            fields=(
                "artifactId",
                "kind",
                "fileName",
                "format",
                "contentType",
                "declaredSha256",
                "declaredSizeBytes",
                "declaredCrs",
                "declaredVerticalReference",
                "declaredGsdM",
            ),
        )
        vertical_reference = artifact_object["declaredVerticalReference"]
        if vertical_reference is not None:
            _require_v2_wire_object_fields(
                vertical_reference,
                path=f"{artifact_path}.declaredVerticalReference",
                fields=("datum", "basis", "source"),
            )
    try:
        return ExternalReconstructionSubmissionV3.model_validate(payload)
    except _PydanticValidationError as exc:
        # A credential-bearing URI must never be echoed back in an error:
        # rewrite source-reference failures with a static message.
        for error in exc.errors():
            if tuple(error.get("loc", ()))[:3] == (
                "inputDeclaration",
                "upstreamSource",
                "sourceUri",
            ):
                raise ValueError(
                    "inputDeclaration.upstreamSource.sourceUri must be "
                    "a safe public http(s) reference"
                ) from exc
        raise


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
    "ExternalReconstructionSubmission",
    "ExternalReconstructionSubmissionV1",
    "ExternalReconstructionSubmissionV1Input",
    "ExternalReconstructionSubmissionV1Producer",
    "ExternalReconstructionSubmissionV2",
    "ExternalReconstructionSubmissionV3",
    "ExternalReconstructionSubmissionV3Input",
    "ExternalReconstructionSubmissionV3Producer",
    "ExternalDerivativeExportV3",
    "ExternalUpstreamSourceReferenceV3",
    "external_reconstruction_manifest_wire_dict",
    "external_reconstruction_submission_wire_dict",
    "external_reconstruction_submission_v2_wire_dict",
    "external_reconstruction_submission_v3_wire_dict",
    "parse_external_reconstruction_submission_v2",
    "parse_external_reconstruction_submission_v3",
]
