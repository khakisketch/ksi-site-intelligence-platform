"""Small, closed HTTP client for the six KSI Analysis API operations."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal
from urllib.parse import quote, urlencode

import httpx
from ksi_event_contracts.external_analysis_api import (
    AnalysisObservationOptionsV1,
    AnalysisObservationSelectorV1,
    AnalysisReadinessViewV1,
    CreateAnalysisRequestV1,
)
from ksi_event_contracts.external_analysis_api_v2 import (
    AnalysisEvidencePageV2,
    AnalysisListPageV2,
    AnalysisViewV2,
)
from ksi_event_contracts.external_delta_publication_api import (
    DeltaPublicationBytesV1,
    DeltaPublicationIntentViewV1,
    DeltaPublicationViewV1,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .config import (
    MAX_STRUCTURED_RESPONSE_BYTES,
    AdapterConfig,
    AdapterConfigurationError,
)
from .delta_publications import (
    MAX_DELTA_BYTES_RESPONSE_BYTES,
    CreateDeltaPublicationArguments,
    DeltaPublicationError,
    DeltaPublicationScopeArguments,
    ReadDeltaPublicationBytesArguments,
    create_delta_publication_body,
    create_delta_publication_path,
    delta_publication_bytes_path,
    delta_publication_path,
    validate_bytes_response,
    validate_intent_response,
    validate_view_response,
)

_ACK_HEADER = "X-KSI-External-AI-Egress"
_V2_READ_CONFLICT_CODES = frozenset(
    {
        "ANALYSIS_CURSOR_STALE",
        "ANALYSIS_EVIDENCE_CURSOR_STALE",
        "ANALYSIS_SNAPSHOT_CHANGED",
    }
)
_MAX_IDENTIFIER_LENGTH = 255
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}\Z")


class CoreAdapterError(RuntimeError):
    """A safe typed error that never carries a raw Core response body."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SiteArguments(_ClosedModel):
    site_id: str = Field(alias="siteId", min_length=1, max_length=_MAX_IDENTIFIER_LENGTH)

    @field_validator("site_id")
    @classmethod
    def _safe_site_id(cls, value: str) -> str:
        return _safe_identifier(value)


class AnalysisArguments(SiteArguments):
    analysis_id: str = Field(alias="analysisId", min_length=1, max_length=_MAX_IDENTIFIER_LENGTH)

    @field_validator("analysis_id")
    @classmethod
    def _safe_analysis_id(cls, value: str) -> str:
        return _safe_identifier(value)


class AnalysisListArguments(SiteArguments):
    limit: int = Field(default=50, ge=1, le=50)
    cursor: str | None = Field(default=None, min_length=1, max_length=512)


class AnalysisEvidenceArguments(AnalysisArguments):
    limit: int = Field(default=32, ge=1, le=32)
    cursor: str | None = Field(default=None, min_length=1, max_length=512)


class CreateAnalysisArguments(SiteArguments):
    work_area_id: str = Field(alias="workAreaId", min_length=1, max_length=_MAX_IDENTIFIER_LENGTH)
    baseline: AnalysisObservationSelectorV1
    current: AnalysisObservationSelectorV1
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=255)

    @field_validator("work_area_id")
    @classmethod
    def _safe_work_area_id(cls, value: str) -> str:
        return _safe_identifier(value)

    @field_validator("idempotency_key")
    @classmethod
    def _safe_idempotency_key(cls, value: str) -> str:
        """Keep the caller's key unchanged, but only if it is one safe HTTP header value."""
        if (
            value != value.strip(" ")
            or not value.strip()
            or any(ord(character) < 0x20 or ord(character) > 0x7E for character in value)
        ):
            raise ValueError("idempotency key must be printable ASCII without edge whitespace")
        return value


class ReadinessArguments(SiteArguments):
    """Pure preflight selectors; no idempotency key is accepted or journaled."""

    work_area_id: str = Field(alias="workAreaId", min_length=1, max_length=_MAX_IDENTIFIER_LENGTH)
    baseline: AnalysisObservationSelectorV1
    current: AnalysisObservationSelectorV1

    @field_validator("work_area_id")
    @classmethod
    def _safe_work_area_id(cls, value: str) -> str:
        return _safe_identifier(value)


def _safe_identifier(value: str) -> str:
    if _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError("identifier must be a path-safe resource identifier")
    return value


ToolArguments = (
    SiteArguments
    | AnalysisArguments
    | AnalysisListArguments
    | AnalysisEvidenceArguments
    | CreateAnalysisArguments
    | ReadinessArguments
    | CreateDeltaPublicationArguments
    | DeltaPublicationScopeArguments
    | ReadDeltaPublicationBytesArguments
)
ToolName = Literal[
    "ksi_list_analysis_observations",
    "ksi_list_analyses",
    "ksi_create_analysis",
    "ksi_check_analysis_readiness",
    "ksi_get_analysis",
    "ksi_get_analysis_result",
    "ksi_get_analysis_evidence",
    "ksi_create_delta_publication",
    "ksi_get_delta_publication",
    "ksi_read_delta_publication_bytes",
]

TOOL_ARGUMENT_MODELS: dict[str, type[ToolArguments]] = {
    "ksi_list_analysis_observations": SiteArguments,
    "ksi_list_analyses": AnalysisListArguments,
    "ksi_create_analysis": CreateAnalysisArguments,
    "ksi_check_analysis_readiness": ReadinessArguments,
    "ksi_get_analysis": AnalysisArguments,
    "ksi_get_analysis_result": AnalysisArguments,
    "ksi_get_analysis_evidence": AnalysisEvidenceArguments,
    "ksi_create_delta_publication": CreateDeltaPublicationArguments,
    "ksi_get_delta_publication": DeltaPublicationScopeArguments,
    "ksi_read_delta_publication_bytes": ReadDeltaPublicationBytesArguments,
}

# Core responses are never treated as arbitrary JSON.  This same map backs
# transport validation and the MCP output schemas advertised to a client.
TOOL_RESULT_MODELS: dict[str, type[BaseModel]] = {
    "ksi_list_analysis_observations": AnalysisObservationOptionsV1,
    "ksi_list_analyses": AnalysisListPageV2,
    "ksi_create_analysis": AnalysisViewV2,
    "ksi_check_analysis_readiness": AnalysisReadinessViewV1,
    "ksi_get_analysis": AnalysisViewV2,
    "ksi_get_analysis_result": AnalysisViewV2,
    "ksi_get_analysis_evidence": AnalysisEvidencePageV2,
    "ksi_create_delta_publication": DeltaPublicationIntentViewV1,
    "ksi_get_delta_publication": DeltaPublicationViewV1,
    "ksi_read_delta_publication_bytes": DeltaPublicationBytesV1,
}


def validate_tool_arguments(name: str, arguments: dict[str, Any] | None) -> ToolArguments:
    """Parse only the documented JSON shape before a path or request is formed."""
    model = TOOL_ARGUMENT_MODELS.get(name)
    if model is None:
        raise CoreAdapterError("UNKNOWN_TOOL")
    try:
        return model.model_validate(arguments or {})
    except ValidationError as exc:
        raise CoreAdapterError("INVALID_TOOL_ARGUMENTS") from exc


class CoreAnalysisClient:
    """Calls one configured Core origin and accepts only Core-evidenced AI egress."""

    def __init__(self, config: AdapterConfig) -> None:
        self._config = config

    async def invoke(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        parsed = validate_tool_arguments(name, arguments)
        if name == "ksi_list_analysis_observations":
            assert isinstance(parsed, SiteArguments)
            return await self._read(
                self._observations_path(parsed.site_id), TOOL_RESULT_MODELS[name]
            )
        if name == "ksi_list_analyses":
            assert isinstance(parsed, AnalysisListArguments)
            return await self._read(
                self._page_path(self._analyses_path(parsed.site_id), parsed.limit, parsed.cursor),
                TOOL_RESULT_MODELS[name],
            )
        if name == "ksi_create_analysis":
            assert isinstance(parsed, CreateAnalysisArguments)
            # The same scoped, acknowledged observation read establishes the
            # current egress decision before a mutation is even attempted.
            await self._read(self._observations_path(parsed.site_id), AnalysisObservationOptionsV1)
            try:
                request = CreateAnalysisRequestV1(
                    baseline=parsed.baseline,
                    current=parsed.current,
                )
            except ValidationError as exc:
                raise CoreAdapterError("INVALID_TOOL_ARGUMENTS") from exc
            return await self._request_validated(
                "POST",
                self._create_path_v2(parsed.site_id, parsed.work_area_id),
                TOOL_RESULT_MODELS[name],
                json_body=request.model_dump(by_alias=True, mode="json"),
                idempotency_key=parsed.idempotency_key,
            )
        if name == "ksi_check_analysis_readiness":
            assert isinstance(parsed, ReadinessArguments)
            try:
                request = CreateAnalysisRequestV1(
                    baseline=parsed.baseline,
                    current=parsed.current,
                )
            except ValidationError as exc:
                raise CoreAdapterError("INVALID_TOOL_ARGUMENTS") from exc
            return await self._request_validated(
                "POST",
                self._readiness_path_v2(parsed.site_id, parsed.work_area_id),
                TOOL_RESULT_MODELS[name],
                json_body=request.model_dump(by_alias=True, mode="json"),
            )
        if name == "ksi_create_delta_publication":
            assert isinstance(parsed, CreateDeltaPublicationArguments)
            # Source-only intent: Core resolves all grid facts. The POST response
            # itself must carry the machine-channel egress acknowledgment.
            try:
                body = create_delta_publication_body(parsed)
            except DeltaPublicationError as exc:
                raise CoreAdapterError(exc.code) from exc
            payload = await self._request_validated(
                "POST",
                create_delta_publication_path(parsed.site_id, parsed.work_area_id),
                TOOL_RESULT_MODELS[name],
                json_body=body,
            )
            try:
                return validate_intent_response(
                    payload,
                    site_id=parsed.site_id,
                    work_area_id=parsed.work_area_id,
                    publication_id=parsed.publication_id,
                    source_calculation_identity_digest=(
                        parsed.source_calculation_identity_digest
                    ),
                    source_numeric_result_identity_digest=(
                        parsed.source_numeric_result_identity_digest
                    ),
                    source_coverage_witness_digest=(
                        parsed.source_coverage_witness_digest
                    ),
                )
            except DeltaPublicationError as exc:
                raise CoreAdapterError(exc.code) from exc
        if name == "ksi_get_delta_publication":
            assert isinstance(parsed, DeltaPublicationScopeArguments)
            payload = await self._request_validated(
                "GET",
                delta_publication_path(
                    parsed.site_id, parsed.work_area_id, parsed.publication_id
                ),
                TOOL_RESULT_MODELS[name],
            )
            try:
                return validate_view_response(
                    payload,
                    site_id=parsed.site_id,
                    work_area_id=parsed.work_area_id,
                    publication_id=parsed.publication_id,
                )
            except DeltaPublicationError as exc:
                raise CoreAdapterError(exc.code) from exc
        if name == "ksi_read_delta_publication_bytes":
            assert isinstance(parsed, ReadDeltaPublicationBytesArguments)
            # Byte chunks are opaque worker output: bounded base64 passthrough,
            # never recomputed or parsed as TIFF by this adapter.
            try:
                path = delta_publication_bytes_path(
                    parsed.site_id,
                    parsed.work_area_id,
                    parsed.publication_id,
                    parsed.offset,
                    parsed.length,
                )
            except DeltaPublicationError as exc:
                raise CoreAdapterError(exc.code) from exc
            payload = await self._request_validated(
                "GET",
                path,
                TOOL_RESULT_MODELS[name],
                response_limit=MAX_DELTA_BYTES_RESPONSE_BYTES,
                structured_limit=MAX_DELTA_BYTES_RESPONSE_BYTES,
            )
            try:
                return validate_bytes_response(
                    payload,
                    publication_id=parsed.publication_id,
                    offset=parsed.offset,
                    length=parsed.length,
                )
            except DeltaPublicationError as exc:
                raise CoreAdapterError(exc.code) from exc
        assert isinstance(parsed, AnalysisArguments)
        if name == "ksi_get_analysis_evidence":
            assert isinstance(parsed, AnalysisEvidenceArguments)
            path = self._page_path(
                self._analysis_path(parsed.site_id, parsed.analysis_id) + "/evidence",
                parsed.limit,
                parsed.cursor,
            )
            model = TOOL_RESULT_MODELS[name]
        elif name in {"ksi_get_analysis", "ksi_get_analysis_result"}:
            path = self._analysis_path(parsed.site_id, parsed.analysis_id)
            model = TOOL_RESULT_MODELS[name]
        else:
            raise CoreAdapterError("UNKNOWN_TOOL")
        return await self._read(path, model)

    @staticmethod
    def _page_path(path: str, limit: int, cursor: str | None) -> str:
        params = {"limit": str(limit)}
        if cursor is not None:
            params["cursor"] = cursor
        return path + "?" + urlencode(params)

    async def _read(self, path: str, model: type[BaseModel]) -> dict[str, Any]:
        return await self._request_validated("GET", path, model)

    async def _request_validated(
        self,
        method: Literal["GET", "POST"],
        path: str,
        model: type[BaseModel],
        *,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        response_limit: int | None = None,
        structured_limit: int | None = None,
    ) -> dict[str, Any]:
        payload = await self._request(
            method,
            path,
            json_body=json_body,
            idempotency_key=idempotency_key,
            response_limit=response_limit,
        )
        try:
            validated = model.model_validate(payload)
        except ValidationError as exc:
            raise CoreAdapterError("INVALID_CORE_RESPONSE") from exc
        result = validated.model_dump(by_alias=True, mode="json")
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ceiling = (
            min(structured_limit, MAX_DELTA_BYTES_RESPONSE_BYTES)
            if structured_limit is not None
            else MAX_STRUCTURED_RESPONSE_BYTES
        )
        if len(encoded) > ceiling:
            raise CoreAdapterError("CORE_RESPONSE_TOO_LARGE")
        return result

    async def _request(
        self,
        method: Literal["GET", "POST"],
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        response_limit: int | None = None,
    ) -> dict[str, Any]:
        try:
            token = self._config.read_token()
        except AdapterConfigurationError as exc:
            raise CoreAdapterError("CORE_CREDENTIAL_UNAVAILABLE") from exc
        headers = {
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                async with (
                    self._config.new_http_client() as client,
                    client.stream(method, path, headers=headers, json=json_body) as response,
                ):
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise CoreAdapterError("ENCODED_CORE_RESPONSE")
                    body = await self._bounded_body(response, response_limit)
        except CoreAdapterError:
            raise
        except TimeoutError:
            raise CoreAdapterError("CORE_TIMEOUT") from None
        except (httpx.HTTPError, OSError):
            raise CoreAdapterError("CORE_UNAVAILABLE") from None
        if 300 <= response.status_code < 400:
            raise CoreAdapterError("CORE_REDIRECT_REJECTED")
        if response.status_code < 200 or response.status_code >= 300:
            raise CoreAdapterError(self._status_code(response.status_code, body, method, path))
        if response.headers.get(_ACK_HEADER) != "ALLOWED":
            raise CoreAdapterError("CORE_EGRESS_ACKNOWLEDGMENT_MISSING")
        try:
            parsed = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise CoreAdapterError("INVALID_CORE_RESPONSE") from exc
        if not isinstance(parsed, dict):
            raise CoreAdapterError("INVALID_CORE_RESPONSE")
        return parsed

    async def _bounded_body(
        self, response: httpx.Response, response_limit: int | None = None
    ) -> bytes:
        body = bytearray()
        # The opaque byte-chunk lane passes its own fixed bounded ceiling that
        # fits one maximum contract slice; every other tool keeps the
        # structured ceiling. No lane is unbounded: an explicit limit is still
        # clamped to the absolute byte-lane ceiling.
        if response_limit is None:
            ceiling = min(self._config.max_response_bytes, MAX_STRUCTURED_RESPONSE_BYTES)
        else:
            ceiling = min(response_limit, MAX_DELTA_BYTES_RESPONSE_BYTES)
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > ceiling:
                raise CoreAdapterError("CORE_RESPONSE_TOO_LARGE")
        return bytes(body)

    @staticmethod
    def _status_code(
        status: int, body: bytes, method: Literal["GET", "POST"], path: str
    ) -> str:
        detail = None
        try:
            decoded = json.loads(body)
            if isinstance(decoded, dict) and isinstance(decoded.get("detail"), str):
                detail = decoded["detail"]
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            pass
        if "/delta-publications" in path:
            # The delta lane reports honest typed errors; a missing mount,
            # expired intent, or revoked publication is never a fake export.
            if status == 404:
                return "DELTA_PUBLICATION_NOT_AVAILABLE"
            if status == 422:
                if isinstance(detail, str) and detail.startswith("DELTA_"):
                    return detail
                return "DELTA_REQUEST_INVALID"
            if status == 409:
                if isinstance(detail, str) and detail.startswith("DELTA_"):
                    return detail
                return "CORE_CONFLICT"
            if status == 403:
                return (
                    "AI_EGRESS_NOT_ALLOWED"
                    if detail == "AI_EGRESS_NOT_ALLOWED"
                    else "CORE_PERMISSION_DENIED"
                )
            if status == 401:
                return "CORE_AUTHENTICATION_FAILED"
            if status == 400:
                return "CORE_REQUEST_REJECTED"
            return "CORE_UNAVAILABLE"
        if status == 403:
            return (
                "AI_EGRESS_NOT_ALLOWED"
                if detail == "AI_EGRESS_NOT_ALLOWED"
                else "CORE_PERMISSION_DENIED"
            )
        if status == 409:
            if method == "POST" and detail == "ANALYSIS_IDEMPOTENCY_CONFLICT":
                return detail
            if method == "GET" and path.startswith("/v2/sites/") and detail in (
                _V2_READ_CONFLICT_CODES
            ):
                return detail
            return "CORE_CONFLICT"
        return {
            400: "CORE_REQUEST_REJECTED",
            401: "CORE_AUTHENTICATION_FAILED",
            404: "ANALYSIS_RESOURCE_NOT_FOUND",
            422: "INVALID_ANALYSIS_ARGUMENTS",
        }.get(status, "CORE_UNAVAILABLE")

    @staticmethod
    def _segment(value: str) -> str:
        """Quote each already validated segment; no caller controls a raw URL."""
        return quote(value, safe="")

    def _observations_path(self, site_id: str) -> str:
        return f"/v1/sites/{self._segment(site_id)}/analysis-observations"

    def _analyses_path(self, site_id: str) -> str:
        return f"/v2/sites/{self._segment(site_id)}/analyses"

    def _create_path_v2(self, site_id: str, work_area_id: str) -> str:
        return (
            f"/v2/sites/{self._segment(site_id)}/work-areas/"
            f"{self._segment(work_area_id)}/analyses"
        )

    def _readiness_path_v2(self, site_id: str, work_area_id: str) -> str:
        return (
            f"/v2/sites/{self._segment(site_id)}/work-areas/"
            f"{self._segment(work_area_id)}/analysis-readiness"
        )

    def _analysis_path(self, site_id: str, analysis_id: str) -> str:
        return f"{self._analyses_path(site_id)}/{self._segment(analysis_id)}"
