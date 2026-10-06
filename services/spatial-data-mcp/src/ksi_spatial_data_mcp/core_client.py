"""Small, closed HTTP client for the six spatial-data AI operations.

Every call re-reads the separate token, counts actual request bytes against
the owner budget, streams identity-encoded JSON under finite bounds, accepts
only acknowledged Core-evidenced responses, and validates scope before any
MCP result or file reference is emitted.
"""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any, Literal

import httpx
from ksi_event_contracts.spatial_data import SpatialDataErrorV1, SpatialDataJobViewV1
from ksi_event_contracts.spatial_data_ai import (
    SpatialDataAiErrorV1,
    SpatialDataMcpErrorV1,
    SpatialDataMcpJobViewV1,
)
from pydantic import BaseModel, TypeAdapter, ValidationError

from .config import AdapterConfig, AdapterConfigurationError
from .tool_models import (
    TOOL_RESULT_MODELS,
    AssetArguments,
    CreateArguments,
    JobArguments,
    ListArguments,
    ScopeArguments,
    validate_tool_arguments,
)

_ACK_HEADER = "x-ksi-spatial-data-ai-egress"
_ACK_ALLOWED = "ALLOWED"
_MAX_JSON_DEPTH = 100

_RECOGNIZED_ERROR: TypeAdapter[SpatialDataMcpErrorV1] = TypeAdapter(SpatialDataMcpErrorV1)
_RECOGNIZED_AI_ERROR: TypeAdapter[SpatialDataAiErrorV1] = TypeAdapter(SpatialDataAiErrorV1)
_RECOGNIZED_ERROR_V1: TypeAdapter[SpatialDataErrorV1] = TypeAdapter(SpatialDataErrorV1)

# Closed remediation for adapter codes; recognized Core reasons reuse the
# existing AI remediation table values below.
_ADAPTER_REMEDIATION: dict[str, tuple[str, ...]] = {
    "UNKNOWN_TOOL": ("CONTACT_OPERATOR",),
    "INVALID_TOOL_ARGUMENTS": ("CONTACT_OPERATOR",),
    "CONFIGURATION_UNAVAILABLE": ("CHECK_AUTHENTICATION",),
    "CORE_UNAVAILABLE": ("CONTACT_OPERATOR",),
    "CORE_TIMEOUT": ("RETRY_REQUEST",),
    "CORE_RESPONSE_TOO_LARGE": ("REDUCE_REQUEST",),
    "INVALID_CORE_RESPONSE": ("CONTACT_OPERATOR",),
    "AI_EGRESS_UNACKNOWLEDGED": ("CHECK_AI_CONSENT",),
    "CONCURRENCY_LIMIT_EXCEEDED": ("RETRY_REQUEST",),
}
_AI_REASON_REMEDIATION: dict[str, tuple[str, ...]] = {
    "AI_EGRESS_DENIED": ("CHECK_AI_CONSENT",),
    "ACCESS_REVOKED": ("REQUEST_NEW_GRANT",),
    "ACCESS_EXPIRED": ("REQUEST_NEW_GRANT",),
    "GRANT_REQUIRED": ("REQUEST_NEW_GRANT",),
    "PROCESSING_LOCATION_DENIED": ("CHECK_PROCESSING_LOCATION",),
    "NOT_READY": ("WAIT_FOR_COMPLETION",),
    "SPATIAL_DATA_CURSOR_STALE": ("RETRY_REQUEST",),
    "IDEMPOTENCY_CONFLICT": ("REQUEST_NEW_JOB",),
    "RETENTION_EXPIRED": ("REQUEST_NEW_JOB",),
    "INVALID_REQUEST_BOUNDS": ("REDUCE_REQUEST",),
    "RESOURCE_LIMIT_EXCEEDED": ("REDUCE_REQUEST",),
    "OUTPUT_BYTE_LIMIT_EXCEEDED": ("REDUCE_REQUEST",),
    "OUTPUT_PIXEL_LIMIT_EXCEEDED": ("REDUCE_REQUEST",),
}


def remediation_for(code: str) -> tuple[str, ...]:
    """Closed safe remediation for one adapter code or recognized Core reason."""
    remediation = _ADAPTER_REMEDIATION.get(code)
    if remediation is not None:
        return remediation
    remediation = _AI_REASON_REMEDIATION.get(code)
    if remediation is not None:
        return remediation
    if code in ("CONCURRENCY_LIMIT_EXCEEDED", "WORKSPACE_LIMIT_EXCEEDED"):
        return ("RETRY_REQUEST",)
    return ("CONTACT_OPERATOR",)


class CoreAdapterError(RuntimeError):
    """A safe typed error carrying a closed code, never raw Core content.

    When Core itself returned a validated closed error model, its received
    remediation facts ride along (validated against the same closed
    envelope); otherwise the adapter default for the code applies.
    """

    def __init__(self, code: str, remediation: tuple[str, ...] | None = None) -> None:
        if remediation is None:
            remediation = remediation_for(code)
        try:
            _RECOGNIZED_ERROR.validate_python({"code": code, "remediation": list(remediation)})
        except ValidationError:
            remediation = remediation_for(code)
            _RECOGNIZED_ERROR.validate_python({"code": code, "remediation": list(remediation)})
        self.code = code
        self.remediation = tuple(remediation)
        super().__init__(code)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def _walk_finite(value: Any, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise ValueError("JSON exceeds finite nesting depth")
    if isinstance(value, dict):
        for item in value.values():
            _walk_finite(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _walk_finite(item, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number")


def _checked_loads(body: bytes) -> dict[str, Any]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CoreAdapterError("INVALID_CORE_RESPONSE") from exc
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        _walk_finite(parsed)
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise CoreAdapterError("INVALID_CORE_RESPONSE") from exc
    if type(parsed) is not dict:
        raise CoreAdapterError("INVALID_CORE_RESPONSE")
    return parsed


class CoreSpatialDataClient:
    """Calls one configured Core origin and accepts only acknowledged evidence."""

    def __init__(self, config: AdapterConfig) -> None:
        self._config = config
        self._semaphore = asyncio.Semaphore(config.max_concurrent_calls)

    @property
    def config(self) -> AdapterConfig:
        return self._config

    async def invoke(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        # The overall owner deadline starts at invoke entry and covers every
        # stage below — argument/schema work, token refresh, queuing,
        # transport, validation, and output projection. Synchronous bounded
        # CPU work cannot be hard-preempted, so the budget is re-checked
        # after each stage instead.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._config.call_deadline_seconds

        def check_budget() -> None:
            if loop.time() >= deadline:
                raise CoreAdapterError("CORE_TIMEOUT")

        parsed = validate_tool_arguments(name, arguments)
        assert isinstance(parsed, ScopeArguments)
        self._check_argument_budgets(parsed)
        check_budget()
        try:
            token = await asyncio.to_thread(self._config.read_token)
        except AdapterConfigurationError as exc:
            raise CoreAdapterError("CONFIGURATION_UNAVAILABLE") from exc
        check_budget()
        if name == "ksi_list_spatial_data_assets":
            assert isinstance(parsed, ListArguments)
            return await self._list_assets(parsed, token=token, deadline=deadline)
        if name == "ksi_get_spatial_data_asset":
            assert isinstance(parsed, AssetArguments)
            return await self._get_asset(parsed, token=token, deadline=deadline)
        if name == "ksi_create_spatial_data_request":
            assert isinstance(parsed, CreateArguments)
            return await self._create_request(parsed, token=token, deadline=deadline)
        if name == "ksi_list_spatial_data_requests":
            assert isinstance(parsed, ListArguments)
            return await self._list_requests(parsed, token=token, deadline=deadline)
        if name == "ksi_get_spatial_data_request":
            assert isinstance(parsed, JobArguments)
            return await self._get_request(parsed, token=token, deadline=deadline)
        if name == "ksi_cancel_spatial_data_request":
            assert isinstance(parsed, JobArguments)
            return await self._cancel_request(parsed, token=token, deadline=deadline)
        raise CoreAdapterError("UNKNOWN_TOOL")

    def _check_argument_budgets(self, parsed: ScopeArguments) -> None:
        """Enforce the owner identifier/cursor byte budgets before transport."""
        for value in (parsed.site_id, parsed.work_area_id):
            if len(value.encode("utf-8")) > self._config.max_identifier_bytes:
                raise CoreAdapterError("INVALID_TOOL_ARGUMENTS")
        cursor = getattr(parsed, "cursor", None)
        if cursor is not None and len(cursor.encode("utf-8")) > self._config.max_cursor_bytes:
            raise CoreAdapterError("INVALID_TOOL_ARGUMENTS")
        asset_ref = getattr(parsed, "asset_ref", None)
        if asset_ref is not None and (
            len(asset_ref.encode("utf-8")) > self._config.max_identifier_bytes
        ):
            raise CoreAdapterError("INVALID_TOOL_ARGUMENTS")
        job_id = getattr(parsed, "job_id", None)
        if job_id is not None and len(job_id.encode("utf-8")) > self._config.max_identifier_bytes:
            raise CoreAdapterError("INVALID_TOOL_ARGUMENTS")
        idempotency_key = getattr(parsed, "idempotency_key", None)
        if idempotency_key is not None and (
            len(idempotency_key.encode("utf-8")) > self._config.max_identifier_bytes
        ):
            raise CoreAdapterError("INVALID_TOOL_ARGUMENTS")

    def _check_returned_budgets(self, *values: object) -> None:
        """Returned scope/id values must also fit the owner identifier budget."""
        for value in values:
            if type(value) is not str:
                raise CoreAdapterError("INVALID_CORE_RESPONSE")
            if len(value.encode("utf-8")) > self._config.max_identifier_bytes:
                raise CoreAdapterError("INVALID_CORE_RESPONSE")

    async def _list_assets(
        self, parsed: ListArguments, *, token: str, deadline: float
    ) -> dict[str, Any]:
        result = await self._request_validated(
            "GET",
            self._page_path(self._assets_path(parsed.site_id, parsed.work_area_id), parsed),
            TOOL_RESULT_MODELS["ksi_list_spatial_data_assets"],
            token=token,
            deadline=deadline,
        )
        self._check_asset_page(result, parsed)
        return result

    async def _get_asset(
        self, parsed: AssetArguments, *, token: str, deadline: float
    ) -> dict[str, Any]:
        result = await self._request_validated(
            "GET",
            self._asset_detail_path(parsed.site_id, parsed.work_area_id, parsed.asset_ref),
            TOOL_RESULT_MODELS["ksi_get_spatial_data_asset"],
            token=token,
            deadline=deadline,
        )
        self._check_returned_budgets(
            result.get("siteId"), result.get("workAreaId"), result.get("assetRef")
        )
        if (
            result.get("siteId") != parsed.site_id
            or result.get("workAreaId") != parsed.work_area_id
            or result.get("assetRef") != parsed.asset_ref
        ):
            raise CoreAdapterError("INVALID_CORE_RESPONSE")
        return result

    async def _create_request(
        self, parsed: CreateArguments, *, token: str, deadline: float
    ) -> dict[str, Any]:
        try:
            body = {
                "assetRef": parsed.asset_ref,
                "requestedBounds": list(parsed.requested_bounds),
                "observedCrsDigest": parsed.observed_crs_digest,
                "resolutionMode": "NATIVE",
                "purpose": "EXTERNAL_AI",
            }
        except (TypeError, ValueError) as exc:
            raise CoreAdapterError("INVALID_TOOL_ARGUMENTS") from exc
        result = await self._request_validated(
            "POST",
            self._requests_path(parsed.site_id, parsed.work_area_id),
            TOOL_RESULT_MODELS["ksi_create_spatial_data_request"],
            token=token,
            deadline=deadline,
            json_body=body,
            idempotency_key=parsed.idempotency_key,
        )
        self._check_returned_budgets(
            result.get("siteId"), result.get("workAreaId"), result.get("assetRef")
        )
        if (
            result.get("siteId") != parsed.site_id
            or result.get("workAreaId") != parsed.work_area_id
            or result.get("assetRef") != parsed.asset_ref
        ):
            raise CoreAdapterError("INVALID_CORE_RESPONSE")
        return result

    async def _list_requests(
        self, parsed: ListArguments, *, token: str, deadline: float
    ) -> dict[str, Any]:
        result = await self._request_validated(
            "GET",
            self._page_path(self._requests_path(parsed.site_id, parsed.work_area_id), parsed),
            TOOL_RESULT_MODELS["ksi_list_spatial_data_requests"],
            token=token,
            deadline=deadline,
        )
        self._check_job_page(result, parsed)
        return result

    async def _get_request(
        self, parsed: JobArguments, *, token: str, deadline: float
    ) -> dict[str, Any]:
        job = await self._request_validated(
            "GET",
            self._request_detail_path(parsed.site_id, parsed.work_area_id, parsed.job_id),
            SpatialDataJobViewV1,
            token=token,
            deadline=deadline,
        )
        self._check_returned_budgets(job.get("siteId"), job.get("workAreaId"), job.get("jobId"))
        if (
            job.get("siteId") != parsed.site_id
            or job.get("workAreaId") != parsed.work_area_id
            or job.get("jobId") != parsed.job_id
        ):
            raise CoreAdapterError("INVALID_CORE_RESPONSE")
        wrapper = {"job": job, "fileReference": self._file_reference(job, parsed)}
        try:
            validated = SpatialDataMcpJobViewV1.model_validate(wrapper)
        except ValidationError as exc:
            raise CoreAdapterError("INVALID_CORE_RESPONSE") from exc
        return validated.model_dump(by_alias=True, mode="json")

    async def _cancel_request(
        self, parsed: JobArguments, *, token: str, deadline: float
    ) -> dict[str, Any]:
        # No automatic recreate and no replacement key: one scoped cancel only.
        result = await self._request_validated(
            "POST",
            self._cancel_path(parsed.site_id, parsed.work_area_id, parsed.job_id),
            TOOL_RESULT_MODELS["ksi_cancel_spatial_data_request"],
            token=token,
            deadline=deadline,
        )
        self._check_returned_budgets(
            result.get("siteId"), result.get("workAreaId"), result.get("jobId")
        )
        if (
            result.get("siteId") != parsed.site_id
            or result.get("workAreaId") != parsed.work_area_id
            or result.get("jobId") != parsed.job_id
        ):
            raise CoreAdapterError("INVALID_CORE_RESPONSE")
        return result

    @staticmethod
    def _file_reference(job: dict[str, Any], parsed: JobArguments) -> dict[str, Any] | None:
        """Derive the descriptor deterministically from the authorized receipt only.

        Only a COMPLETED+AVAILABLE receipt yields a reference. Any other
        retained history (queued without receipt, canceled, expired, revoked
        availability) validates as a job with a null reference — metadata is
        kept, bytes are never promised.
        """
        receipt = job.get("receipt")
        if receipt is None:
            return None
        if (
            job.get("executionState") != "COMPLETED"
            or job.get("availability") != "AVAILABLE"
            or type(receipt) is not dict
        ):
            return None
        output_sha256 = receipt.get("outputSha256")
        output_size = receipt.get("outputSizeBytes")
        if type(output_sha256) is not str or type(output_size) is not int:
            raise CoreAdapterError("INVALID_CORE_RESPONSE")
        return {
            "referenceVersion": "spatial-data-file-reference.v1",
            "siteId": parsed.site_id,
            "workAreaId": parsed.work_area_id,
            "jobId": parsed.job_id,
            "method": "GET",
            "relativePath": (
                f"/v1/sites/{parsed.site_id}/work-areas/{parsed.work_area_id}"
                f"/spatial-data-requests/{parsed.job_id}/file"
            ),
            "outputSha256": output_sha256,
            "outputSizeBytes": output_size,
            "authenticationRequired": True,
            "rangeSupported": False,
        }

    def _check_asset_page(self, result: dict[str, Any], parsed: ListArguments) -> None:
        items = result.get("items")
        if type(items) is not list or len(items) > parsed.limit:
            raise CoreAdapterError("INVALID_CORE_RESPONSE")
        for item in items:
            if (
                type(item) is not dict
                or item.get("siteId") != parsed.site_id
                or item.get("workAreaId") != parsed.work_area_id
            ):
                raise CoreAdapterError("INVALID_CORE_RESPONSE")
        self._check_cursor(result.get("nextCursor"))

    def _check_job_page(self, result: dict[str, Any], parsed: ListArguments) -> None:
        items = result.get("items")
        if type(items) is not list or len(items) > parsed.limit:
            raise CoreAdapterError("INVALID_CORE_RESPONSE")
        for item in items:
            if (
                type(item) is not dict
                or item.get("siteId") != parsed.site_id
                or item.get("workAreaId") != parsed.work_area_id
            ):
                raise CoreAdapterError("INVALID_CORE_RESPONSE")
        self._check_cursor(result.get("nextCursor"))

    def _check_cursor(self, cursor: Any) -> None:
        if cursor is None:
            return
        if type(cursor) is not str or not cursor:
            raise CoreAdapterError("INVALID_CORE_RESPONSE")
        if len(cursor.encode("utf-8")) > self._config.max_cursor_bytes:
            raise CoreAdapterError("INVALID_CORE_RESPONSE")

    async def _request_validated(
        self,
        method: Literal["GET", "POST"],
        path: str,
        model: type[BaseModel],
        *,
        token: str,
        deadline: float,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload = await self._request(
            method,
            path,
            token=token,
            deadline=deadline,
            json_body=json_body,
            idempotency_key=idempotency_key,
        )
        try:
            validated = model.model_validate(payload)
        except ValidationError as exc:
            raise CoreAdapterError("INVALID_CORE_RESPONSE") from exc
        if asyncio.get_running_loop().time() >= deadline:
            raise CoreAdapterError("CORE_TIMEOUT")
        result = validated.model_dump(by_alias=True, mode="json")
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > self._config.max_structured_response_bytes:
            raise CoreAdapterError("CORE_RESPONSE_TOO_LARGE")
        return result

    async def _request(
        self,
        method: Literal["GET", "POST"],
        path: str,
        *,
        token: str,
        deadline: float,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        # The token was refreshed at invoke entry; the entry deadline governs
        # everything below, including time already spent queuing or reading it.
        headers = {
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        body_bytes = b""
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if json_body is not None:
            try:
                body_bytes = json.dumps(
                    json_body, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise CoreAdapterError("INVALID_TOOL_ARGUMENTS") from exc
        try:
            request_bytes = (
                len(method.encode("ascii"))
                + len(path.encode("utf-8"))
                + len(body_bytes)
                + sum(
                    len(key.encode("latin-1")) + len(value.encode("latin-1"))
                    for key, value in headers.items()
                )
            )
        except (UnicodeError, ValueError) as exc:
            raise CoreAdapterError("INVALID_TOOL_ARGUMENTS") from exc
        if request_bytes > self._config.max_request_bytes:
            raise CoreAdapterError("INVALID_TOOL_ARGUMENTS")
        try:
            loop = asyncio.get_running_loop()
            acquired = False
            try:
                remaining = max(0.0, deadline - loop.time())
                await asyncio.wait_for(self._semaphore.acquire(), timeout=remaining)
                acquired = True
                async with asyncio.timeout(max(0.0, deadline - loop.time())):
                    return await self._exchange(method, path, headers, body_bytes or None)
            finally:
                if acquired:
                    self._semaphore.release()
        except CoreAdapterError:
            raise
        except TimeoutError:
            # Queue-timeout (slot never acquired) stays distinct from exchange
            # timeout; external cancellation still propagates as CancelledError.
            if acquired:
                raise CoreAdapterError("CORE_TIMEOUT") from None
            raise CoreAdapterError("CONCURRENCY_LIMIT_EXCEEDED") from None

    async def _exchange(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> dict[str, Any]:
        try:
            async with self._config.new_http_client() as client:
                if body is not None:
                    stream = client.stream(method, path, headers=headers, content=body)
                else:
                    stream = client.stream(method, path, headers=headers)
                async with stream as response:
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise CoreAdapterError("INVALID_CORE_RESPONSE")
                    status = response.status_code
                    if 300 <= status < 400:
                        raise CoreAdapterError("CORE_UNAVAILABLE")
                    raw = await self._bounded_body(response)
                    if status < 200 or status >= 300:
                        code, received = self._status_info(status, raw, method)
                        raise CoreAdapterError(code, received)
                    content_type = response.headers.get("content-type")
                    if (
                        content_type is None
                        or content_type.split(";")[0].strip().lower() != "application/json"
                    ):
                        raise CoreAdapterError("INVALID_CORE_RESPONSE")
                    ack = response.headers.get(_ACK_HEADER)
        except CoreAdapterError:
            raise
        except TimeoutError:
            raise CoreAdapterError("CORE_TIMEOUT") from None
        except (httpx.HTTPError, OSError):
            raise CoreAdapterError("CORE_UNAVAILABLE") from None
        except Exception as exc:
            # Any unexpected transport failure stays a closed code; the raw
            # exception text is never reflected.
            raise CoreAdapterError("CORE_UNAVAILABLE") from exc
        if ack != _ACK_ALLOWED:
            raise CoreAdapterError("AI_EGRESS_UNACKNOWLEDGED")
        return _checked_loads(raw)

    async def _bounded_body(self, response: httpx.Response) -> bytes:
        body = bytearray()
        limit = self._config.max_structured_response_bytes
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > limit:
                raise CoreAdapterError("CORE_RESPONSE_TOO_LARGE")
            body.extend(chunk)
        return bytes(body)

    @staticmethod
    def _status_info(status: int, body: bytes, method: str) -> tuple[str, tuple[str, ...] | None]:
        """Preserve a validated closed reason with its received remediation.

        Only a fully validated closed error model contributes facts; anything
        else falls back to closed codes with adapter defaults and no body echo.
        """
        try:
            decoded = _checked_loads(body)
        except CoreAdapterError:
            decoded = None
        if isinstance(decoded, dict):
            for adapter in (_RECOGNIZED_AI_ERROR, _RECOGNIZED_ERROR_V1):
                try:
                    error = adapter.validate_python(decoded)
                except ValidationError:
                    continue
                return str(error.reason), tuple(error.remediation)
        if status == 401:
            return "CORE_UNAVAILABLE", None
        if status == 403:
            return "AI_EGRESS_DENIED", None
        if status == 404:
            return "NOT_FOUND", None
        if status == 409:
            if method == "POST":
                return "IDEMPOTENCY_CONFLICT", None
            return "SPATIAL_DATA_CURSOR_STALE", None
        if status in (400, 422):
            return "INVALID_TOOL_ARGUMENTS", None
        if status in (408, 429):
            return "CONCURRENCY_LIMIT_EXCEEDED", None
        if status == 503:
            return "UNAVAILABLE", None
        return "CORE_UNAVAILABLE", None

    @staticmethod
    def _segment(value: str) -> str:
        """Quote each already validated segment; no caller controls a raw URL."""
        from urllib.parse import quote

        return quote(value, safe="")

    @staticmethod
    def _page_path(base: str, parsed: ListArguments) -> str:
        from urllib.parse import urlencode

        params = {"limit": str(parsed.limit)}
        if parsed.cursor is not None:
            params["cursor"] = parsed.cursor
        return base + "?" + urlencode(params)

    def _assets_path(self, site_id: str, work_area_id: str) -> str:
        return (
            f"/v1/sites/{self._segment(site_id)}/work-areas/"
            f"{self._segment(work_area_id)}/spatial-data-assets"
        )

    def _requests_path(self, site_id: str, work_area_id: str) -> str:
        return (
            f"/v1/sites/{self._segment(site_id)}/work-areas/"
            f"{self._segment(work_area_id)}/spatial-data-requests"
        )

    def _asset_detail_path(self, site_id: str, work_area_id: str, asset_ref: str) -> str:
        return f"{self._assets_path(site_id, work_area_id)}/{self._segment(asset_ref)}"

    def _request_detail_path(self, site_id: str, work_area_id: str, job_id: str) -> str:
        return f"{self._requests_path(site_id, work_area_id)}/{self._segment(job_id)}"

    def _cancel_path(self, site_id: str, work_area_id: str, job_id: str) -> str:
        return f"{self._request_detail_path(site_id, work_area_id, job_id)}/cancel"
