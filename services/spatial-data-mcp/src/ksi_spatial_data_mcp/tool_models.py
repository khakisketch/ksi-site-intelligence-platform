"""Closed typed arguments and result maps for the six spatial-data MCP tools.

Models are validated before any transport is formed. Unknown fields,
caller-supplied purpose/organization/URL/header values, and bearer-looking
text fail here; only create supplies purpose=EXTERNAL_AI and
resolutionMode=NATIVE in the existing V1 body.
"""

from __future__ import annotations

import re
from typing import Any

from ksi_event_contracts._spatial_data import Bounds
from ksi_event_contracts.spatial_data import SpatialDataJobViewV1, SpatialDataPageV1
from ksi_event_contracts.spatial_data_ai import (
    SpatialDataAssetPageV1,
    SpatialDataAssetViewV1,
    SpatialDataMcpErrorV1,
    SpatialDataMcpJobViewV1,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}\Z")
_BEARER_SCHEME_RE = re.compile(r"[Bb][Ee][Aa][Rr][Ee][Rr](?:\s|\Z)")
_SHA256_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_IDENTIFIER_LENGTH = 255
_MAX_CURSOR_LENGTH = 2048
_MAX_LIST_LIMIT = 200


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _safe_identifier(value: str) -> str:
    if _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError("identifier must be a path-safe resource identifier")
    return value


def _reject_bearer_text(value: object) -> object:
    # Only the credential-scheme form is refused ("Bearer <material>"): a safe
    # route identifier that merely contains the word (e.g. site-bearer-a)
    # stays routable. There are no credential/purpose/URL/header fields for
    # material to live in — extras are forbidden — so this is a backstop,
    # not the boundary.
    if isinstance(value, str) and _BEARER_SCHEME_RE.match(value) is not None:
        raise ValueError("bearer credential material is never a tool argument")
    return value


class _NoBearerModel(_ClosedModel):
    @model_validator(mode="before")
    @classmethod
    def _no_bearer_material(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for item in data.values():
                _reject_bearer_text(item)
        return data


class ScopeArguments(_NoBearerModel):
    site_id: str = Field(alias="siteId", min_length=1, max_length=_MAX_IDENTIFIER_LENGTH)
    work_area_id: str = Field(alias="workAreaId", min_length=1, max_length=_MAX_IDENTIFIER_LENGTH)

    @field_validator("site_id", "work_area_id")
    @classmethod
    def _safe_scope(cls, value: str) -> str:
        return _safe_identifier(value)


class ListArguments(ScopeArguments):
    limit: int = Field(default=1, ge=1, le=_MAX_LIST_LIMIT)
    cursor: str | None = Field(default=None, min_length=1, max_length=_MAX_CURSOR_LENGTH)

    @field_validator("cursor")
    @classmethod
    def _bounded_cursor(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
            raise ValueError("cursor carries control characters")
        return value


class AssetArguments(ScopeArguments):
    asset_ref: str = Field(alias="assetRef", min_length=1, max_length=_MAX_IDENTIFIER_LENGTH)

    @field_validator("asset_ref")
    @classmethod
    def _safe_asset_ref(cls, value: str) -> str:
        return _safe_identifier(value)


class JobArguments(ScopeArguments):
    job_id: str = Field(alias="jobId", min_length=1, max_length=_MAX_IDENTIFIER_LENGTH)

    @field_validator("job_id")
    @classmethod
    def _safe_job_id(cls, value: str) -> str:
        return _safe_identifier(value)


class CreateArguments(ScopeArguments):
    asset_ref: str = Field(alias="assetRef", min_length=1, max_length=_MAX_IDENTIFIER_LENGTH)
    requested_bounds: Bounds = Field(alias="requestedBounds")
    observed_crs_digest: str = Field(alias="observedCrsDigest", min_length=71, max_length=71)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=255)

    @field_validator("asset_ref")
    @classmethod
    def _safe_create_asset_ref(cls, value: str) -> str:
        return _safe_identifier(value)

    @field_validator("observed_crs_digest")
    @classmethod
    def _safe_digest(cls, value: str) -> str:
        # Exact wire representation, matching the event-contract Digest shape.
        if _SHA256_DIGEST_RE.fullmatch(value) is None:
            raise ValueError("digest must use the closed sha256 representation")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def _safe_idempotency_key(cls, value: str) -> str:
        """Keep the caller's key unchanged, but only as one safe header value."""
        if (
            value != value.strip(" ")
            or not value.strip()
            or any(ord(character) < 0x20 or ord(character) > 0x7E for character in value)
        ):
            raise ValueError("idempotency key must be printable ASCII without edge whitespace")
        return value


ToolName = str

TOOL_ARGUMENT_MODELS: dict[str, type[_NoBearerModel]] = {
    "ksi_list_spatial_data_assets": ListArguments,
    "ksi_get_spatial_data_asset": AssetArguments,
    "ksi_create_spatial_data_request": CreateArguments,
    "ksi_list_spatial_data_requests": ListArguments,
    "ksi_get_spatial_data_request": JobArguments,
    "ksi_cancel_spatial_data_request": JobArguments,
}

# Core responses are never treated as arbitrary JSON. This same map backs
# transport validation and the MCP output schemas advertised to a client.
TOOL_RESULT_MODELS: dict[str, type[BaseModel]] = {
    "ksi_list_spatial_data_assets": SpatialDataAssetPageV1,
    "ksi_get_spatial_data_asset": SpatialDataAssetViewV1,
    "ksi_create_spatial_data_request": SpatialDataJobViewV1,
    "ksi_list_spatial_data_requests": SpatialDataPageV1,
    "ksi_get_spatial_data_request": SpatialDataMcpJobViewV1,
    "ksi_cancel_spatial_data_request": SpatialDataJobViewV1,
}

TOOL_ERROR_MODEL: type[BaseModel] = SpatialDataMcpErrorV1


def validate_tool_arguments(name: str, arguments: dict[str, Any] | None) -> _NoBearerModel:
    """Parse only the documented JSON shape before a path or request is formed."""
    from .core_client import CoreAdapterError

    model = TOOL_ARGUMENT_MODELS.get(name)
    if model is None:
        raise CoreAdapterError("UNKNOWN_TOOL")
    from pydantic import ValidationError

    try:
        return model.model_validate(arguments or {})
    except ValidationError as exc:
        raise CoreAdapterError("INVALID_TOOL_ARGUMENTS") from exc
