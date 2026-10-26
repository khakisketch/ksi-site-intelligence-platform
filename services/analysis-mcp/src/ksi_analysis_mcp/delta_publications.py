"""Closed additive helper for external-consumer delta-publication tools.

Owns the three delta-publication argument shapes, fixed Core paths, and strict
Core-response checks (scope echo, digest shape, base64 bounds). It never
recomputes or parses TIFF bytes: a byte chunk is passed through exactly as the
authenticated worker stored it after opaque base64 validation.

Every response still requires the machine-channel acknowledgment
``X-KSI-External-AI-Egress: ALLOWED``; that check lives in
:mod:`ksi_analysis_mcp.core_client` and applies to these tools unchanged. There
is no human-header fallback and no ordinary download path.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Literal
from urllib.parse import quote, urlencode

from ksi_event_contracts.external_delta_publication_api import (
    CreateDeltaPublicationV1,
    DeltaPublicationBytesV1,
    DeltaPublicationIntentViewV1,
    DeltaPublicationViewV1,
)
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

MAX_DELTA_SLICE_BYTES = 1024 * 1024
# Finite 32-bit protocol bound only; retention/policy ceilings belong to Core,
# which rejects over-policy lifetimes with an explicit typed error.
MAX_DELTA_LIFETIME_SECONDS = 2**31 - 1
MAX_DELTA_BYTES_RESPONSE_BYTES = 1_600_000

_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}\Z")
_SAFE_PUBLICATION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class DeltaPublicationError(ValueError):
    """A safe typed failure that never carries a raw Core response body."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _safe_identifier(value: str) -> str:
    if _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError("identifier must be a path-safe resource identifier")
    return value


def _safe_publication_id(value: str) -> str:
    if _SAFE_PUBLICATION_ID.fullmatch(value) is None:
        raise ValueError("publication id must be an opaque Core identifier")
    return value


def _safe_digest(value: str) -> str:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError("digest must be a sha256 hex digest")
    return value


class DeltaPublicationScopeArguments(_ClosedModel):
    site_id: str = Field(alias="siteId", min_length=1, max_length=255)
    work_area_id: str = Field(alias="workAreaId", min_length=1, max_length=255)
    publication_id: str = Field(alias="publicationId", min_length=1, max_length=128)

    @field_validator("site_id", "work_area_id")
    @classmethod
    def _safe_scope(cls, value: str) -> str:
        return _safe_identifier(value)

    @field_validator("publication_id")
    @classmethod
    def _safe_publication(cls, value: str) -> str:
        return _safe_publication_id(value)


class CreateDeltaPublicationArguments(DeltaPublicationScopeArguments):
    source_calculation_identity_digest: str = Field(alias="sourceCalculationIdentityDigest")
    source_numeric_result_identity_digest: str = Field(alias="sourceNumericResultIdentityDigest")
    source_coverage_witness_digest: str = Field(alias="sourceCoverageWitnessDigest")
    lifetime_seconds: StrictInt = Field(
        alias="lifetimeSeconds", ge=1, le=MAX_DELTA_LIFETIME_SECONDS
    )

    @field_validator(
        "source_calculation_identity_digest",
        "source_numeric_result_identity_digest",
        "source_coverage_witness_digest",
    )
    @classmethod
    def _safe_source_digest(cls, value: str) -> str:
        return _safe_digest(value)


class ReadDeltaPublicationBytesArguments(DeltaPublicationScopeArguments):
    offset: StrictInt = Field(ge=0)
    length: StrictInt = Field(ge=1, le=MAX_DELTA_SLICE_BYTES)


DeltaToolName = Literal[
    "ksi_create_delta_publication",
    "ksi_get_delta_publication",
    "ksi_read_delta_publication_bytes",
]

DELTA_TOOL_ARGUMENT_MODELS: dict[str, type[_ClosedModel]] = {
    "ksi_create_delta_publication": CreateDeltaPublicationArguments,
    "ksi_get_delta_publication": DeltaPublicationScopeArguments,
    "ksi_read_delta_publication_bytes": ReadDeltaPublicationBytesArguments,
}

DELTA_TOOL_RESULT_MODELS: dict[str, type[BaseModel]] = {
    "ksi_create_delta_publication": DeltaPublicationIntentViewV1,
    "ksi_get_delta_publication": DeltaPublicationViewV1,
    "ksi_read_delta_publication_bytes": DeltaPublicationBytesV1,
}


def _segment(value: str) -> str:
    """Quote each already validated segment; no caller controls a raw URL."""
    return quote(value, safe="")


def create_delta_publication_path(site_id: str, work_area_id: str) -> str:
    return f"/v1/sites/{_segment(site_id)}/work-areas/{_segment(work_area_id)}/delta-publications"


def delta_publication_path(site_id: str, work_area_id: str, publication_id: str) -> str:
    return f"{create_delta_publication_path(site_id, work_area_id)}/{_segment(publication_id)}"


def delta_publication_bytes_path(
    site_id: str, work_area_id: str, publication_id: str, offset: int, length: int
) -> str:
    if type(offset) is not int or type(length) is not int:
        raise DeltaPublicationError("INVALID_TOOL_ARGUMENTS")
    if offset < 0 or length < 1 or length > MAX_DELTA_SLICE_BYTES:
        raise DeltaPublicationError("INVALID_TOOL_ARGUMENTS")
    base = delta_publication_path(site_id, work_area_id, publication_id) + "/bytes"
    return base + "?" + urlencode({"offset": str(offset), "length": str(length)})


def create_delta_publication_body(arguments: CreateDeltaPublicationArguments) -> dict[str, Any]:
    """Return the source-only Core request body; Core resolves all grid facts."""
    try:
        request = CreateDeltaPublicationV1(
            publication_id=arguments.publication_id,
            source_calculation_identity_digest=arguments.source_calculation_identity_digest,
            source_numeric_result_identity_digest=(arguments.source_numeric_result_identity_digest),
            source_coverage_witness_digest=arguments.source_coverage_witness_digest,
            lifetime_seconds=arguments.lifetime_seconds,
        )
    except ValueError as exc:
        raise DeltaPublicationError("INVALID_TOOL_ARGUMENTS") from exc
    return request.model_dump(by_alias=True, mode="json")


def _model_or_invalid(model: type[BaseModel], payload: Any) -> BaseModel:
    try:
        return model.model_validate(payload)
    except ValueError as exc:
        raise DeltaPublicationError("INVALID_CORE_RESPONSE") from exc


def validate_intent_response(
    payload: Any,
    *,
    site_id: str,
    work_area_id: str,
    publication_id: str,
    source_calculation_identity_digest: str,
    source_numeric_result_identity_digest: str,
    source_coverage_witness_digest: str,
) -> dict[str, Any]:
    """Validate the intent view and bind all requested source digests.

    Scope alone is not enough: a Core reply that echoes the right scope but a
    different numeric result or coverage witness must never appear valid.
    """
    validated = _model_or_invalid(DeltaPublicationIntentViewV1, payload)
    assert isinstance(validated, DeltaPublicationIntentViewV1)
    if (
        validated.site_id != site_id
        or validated.work_area_id != work_area_id
        or validated.publication_id != publication_id
        or validated.source_calculation_identity_digest != source_calculation_identity_digest
        or validated.source_numeric_result_identity_digest != source_numeric_result_identity_digest
        or validated.source_coverage_witness_digest != source_coverage_witness_digest
    ):
        raise DeltaPublicationError("INVALID_CORE_RESPONSE")
    return validated.model_dump(by_alias=True, mode="json")


def validate_view_response(
    payload: Any, *, site_id: str, work_area_id: str, publication_id: str
) -> dict[str, Any]:
    """Validate the publication view and bind its embedded descriptor.

    The closed view model does not cross-bind the nested descriptor yet, so
    this helper requires the descriptor's organization, site, work area,
    publication, output id, policy digest, and issued/expires interval to
    match the outer view exactly.
    """
    validated = _model_or_invalid(DeltaPublicationViewV1, payload)
    assert isinstance(validated, DeltaPublicationViewV1)
    descriptor = validated.descriptor
    if (
        validated.site_id != site_id
        or validated.work_area_id != work_area_id
        or validated.publication_id != publication_id
        or descriptor.publication_id != validated.publication_id
        or descriptor.organization_id != validated.organization_id
        or descriptor.site_id != validated.site_id
        or descriptor.work_area_id != validated.work_area_id
        or descriptor.output_id != validated.output_id
        or descriptor.publication_policy_digest != validated.policy_digest
        or descriptor.issued_at != validated.issued_at
        or descriptor.expires_at != validated.expires_at
    ):
        raise DeltaPublicationError("INVALID_CORE_RESPONSE")
    return validated.model_dump(by_alias=True, mode="json")


def validate_bytes_response(
    payload: Any, *, publication_id: str, offset: int, length: int
) -> dict[str, Any]:
    """Validate the opaque chunk echo without decoding TIFF structure."""
    validated = _model_or_invalid(DeltaPublicationBytesV1, payload)
    assert isinstance(validated, DeltaPublicationBytesV1)
    if validated.publication_id != publication_id or validated.offset != offset:
        raise DeltaPublicationError("INVALID_CORE_RESPONSE")
    try:
        raw = base64.b64decode(validated.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DeltaPublicationError("INVALID_CORE_RESPONSE") from exc
    # validate=True alone permits non-zero pad bits; require canonical encoding.
    if base64.b64encode(raw).decode("ascii") != validated.content_base64:
        raise DeltaPublicationError("INVALID_CORE_RESPONSE")
    if len(raw) > length or len(raw) > MAX_DELTA_SLICE_BYTES:
        raise DeltaPublicationError("INVALID_CORE_RESPONSE")
    return validated.model_dump(by_alias=True, mode="json")
