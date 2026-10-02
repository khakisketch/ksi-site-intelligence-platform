"""Authenticated bounded public data requests; no public key/capability/byte fallback."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Request
from ksi_event_contracts.spatial_data import (
    SpatialDataErrorV1,
    SpatialDataJobViewV1,
    SpatialDataPageV1,
    SpatialDataRequestV1,
)
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from ksi_core.domains.external.delivery.credential_currentness import (
    SpatialDataCredentialCurrentness,
)
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.grants import SpatialDataGrantAuthorizer
from ksi_core.domains.external.delivery.jobs import SpatialDataJobStore
from ksi_core.domains.external.delivery.source import SpatialDataSourceResolver
from ksi_core.identity.auth import Permission, Principal, require_permission

PUBLIC_BASE = "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests"


def error_response(error: SpatialDataDomainError) -> JSONResponse:
    envelope = SpatialDataErrorV1(
        reason=error.reason,
        message="Spatial data request unavailable.",
        retryable=error.retryable,
        remediation=("CONTACT_OPERATOR",),
    )
    return JSONResponse(
        envelope.model_dump(by_alias=True, mode="json"),
        status_code=error.status_code,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


def model_response(model: BaseModel, *, status: int = 200) -> JSONResponse:
    return JSONResponse(
        model.model_dump(by_alias=True, mode="json"),
        status_code=status,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


def request_credentials(request: Request, principal: Principal) -> SpatialDataCredentialCurrentness:
    _, _, token = request.headers.get("authorization", "").partition(" ")
    return SpatialDataCredentialCurrentness(
        request=request,
        token=token,
        expected_principal_id=principal.principal_id,
        expected_organization_id=principal.organization_id,
    )


def request_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Expand this acyclic contract's local definitions; no broken document-root $defs refs."""
    schema = model.model_json_schema(by_alias=True)
    definitions = schema.pop("$defs", {})

    def expand(value: Any) -> Any:
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, dict):
            if "$ref" in value:
                name = value["$ref"].removeprefix("#/$defs/")
                return {
                    **expand(definitions[name]),
                    **expand({key: item for key, item in value.items() if key != "$ref"}),
                }
            return {key: expand(item) for key, item in value.items()}
        return value

    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": expand(schema)}},
        }
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


async def bounded_json(
    request: Request, *, limit: int, timeout_seconds: float, allow_empty: bool = False
) -> Any:
    try:
        if request.headers.get("content-encoding", "identity").lower() != "identity":
            raise ValueError("no encoded request bodies")
        length = request.headers.get("content-length")
        if length is not None and (
            not length.isascii() or not length.isdecimal() or int(length) > limit
        ):
            raise ValueError("body exceeds finite budget")
        raw = bytearray()
        async with asyncio.timeout(timeout_seconds):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > limit:
                    raise ValueError("body exceeds finite budget")
                raw.extend(chunk)
        if not raw and allow_empty:
            return None
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            raise ValueError("JSON required")

        def nonfinite(_: str) -> None:
            raise ValueError("nonfinite JSON forbidden")

        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=nonfinite
        )
    except (ValueError, UnicodeError, TimeoutError, RecursionError) as exc:
        raise SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422) from exc


async def read_model[Model: BaseModel](
    request: Request, model: type[Model], *, jobs: SpatialDataJobStore
) -> Model:
    policy = jobs.policy
    value = await bounded_json(
        request,
        limit=policy.max_json_bytes,
        timeout_seconds=policy.resource_envelope.max_deadline_seconds,
    )
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        # Never return Pydantic's raw input/context or tokens/paths supplied in hostile JSON.
        raise SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422) from exc


class SpatialDataDownloadPort(Protocol):
    def response(
        self,
        *,
        job_id: str,
        principal: Principal,
        credentials: SpatialDataCredentialCurrentness,
        now: datetime,
        head_only: bool,
    ) -> Response: ...


def build_spatial_data_router(
    *,
    jobs: SpatialDataJobStore,
    grants: SpatialDataGrantAuthorizer,
    sources: SpatialDataSourceResolver,
    downloads: SpatialDataDownloadPort | None,
    clock: Callable[[], datetime],
) -> APIRouter:
    if not jobs.uses_exact_participants(grants=grants, sources=sources) or not callable(clock):
        raise ValueError("public data routes require the exact authority participants and clock")
    router = APIRouter(
        tags=["spatial-data"],
        responses={
            code: {"model": SpatialDataErrorV1, "description": "Typed safe data-lane refusal"}
            for code in (403, 404, 409, 416, 422, 429, 503)
        },
    )

    def scoped(
        job_id: str, site_id: str, work_area_id: str, principal: Principal
    ) -> SpatialDataJobViewV1:
        sources.require_history_scope(site_id, work_area_id, principal)
        view = jobs.get(job_id=job_id, principal=principal, now=clock())
        if (view.site_id, view.work_area_id) != (site_id, work_area_id):
            raise SpatialDataDomainError("NOT_FOUND", 404)
        return view

    @router.post(
        PUBLIC_BASE,
        response_model=SpatialDataJobViewV1,
        openapi_extra=request_schema(SpatialDataRequestV1),
    )
    async def issue(
        site_id: str,
        work_area_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_REQUEST)),  # noqa: B008
    ) -> Response:
        try:
            sources.require_history_scope(site_id, work_area_id, principal)
            body = await read_model(request, SpatialDataRequestV1, jobs=jobs)
            principal = await run_in_threadpool(
                request_credentials(request, principal).resolve, now=clock()
            )
            view, created = await run_in_threadpool(
                jobs.issue_with_outcome,
                site_id=site_id,
                work_area_id=work_area_id,
                request=body,
                principal=principal,
                idempotency_key=request.headers.get("idempotency-key", ""),
                now=clock(),
            )
            return model_response(view, status=201 if created else 200)
        except SpatialDataDomainError as exc:
            return error_response(exc)

    @router.get(PUBLIC_BASE, response_model=SpatialDataPageV1)
    def list_requests(
        site_id: str,
        work_area_id: str,
        cursor: str | None = None,
        limit: int = 1,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_READ)),  # noqa: B008
    ) -> Response:
        try:
            return model_response(
                jobs.list(
                    site_id=site_id,
                    work_area_id=work_area_id,
                    principal=principal,
                    cursor=cursor,
                    limit=limit,
                    now=clock(),
                )
            )
        except SpatialDataDomainError as exc:
            return error_response(exc)

    @router.get(PUBLIC_BASE + "/{request_id}", response_model=SpatialDataJobViewV1)
    def get_request(
        site_id: str,
        work_area_id: str,
        request_id: str,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_READ)),  # noqa: B008
    ) -> Response:
        try:
            return model_response(scoped(request_id, site_id, work_area_id, principal))
        except SpatialDataDomainError as exc:
            return error_response(exc)

    @router.post(
        PUBLIC_BASE + "/{request_id}/cancel",
        response_model=SpatialDataJobViewV1,
        openapi_extra={
            "requestBody": {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {"type": "object", "additionalProperties": False}
                    }
                },
            }
        },
    )
    async def cancel(
        site_id: str,
        work_area_id: str,
        request_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_REQUEST)),  # noqa: B008
    ) -> Response:
        try:
            await run_in_threadpool(scoped, request_id, site_id, work_area_id, principal)
            policy = jobs.policy
            value = await bounded_json(
                request,
                limit=policy.max_json_bytes,
                timeout_seconds=policy.resource_envelope.max_deadline_seconds,
                allow_empty=True,
            )
            if value is not None and (type(value) is not dict or value):
                raise SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422)
            principal = await run_in_threadpool(
                request_credentials(request, principal).resolve, now=clock()
            )
            return model_response(
                await run_in_threadpool(
                    jobs.cancel, job_id=request_id, principal=principal, now=clock()
                )
            )
        except SpatialDataDomainError as exc:
            return error_response(exc)

    @router.get(
        PUBLIC_BASE + "/{request_id}/file",
        response_class=Response,
        responses={
            200: {
                "description": "Exact authorized output bytes",
                "content": {"image/tiff": {"schema": {"type": "string", "format": "binary"}}},
            }
        },
    )
    @router.head(PUBLIC_BASE + "/{request_id}/file", response_class=Response)
    def file(
        site_id: str,
        work_area_id: str,
        request_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_READ)),  # noqa: B008
    ) -> Response:
        try:
            scoped(request_id, site_id, work_area_id, principal)
            if request.headers.get("range") is not None:
                raise SpatialDataDomainError("RANGE_NOT_SUPPORTED", 416)
            if downloads is None:
                raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
            credentials = request_credentials(request, principal)
            return downloads.response(
                job_id=request_id,
                principal=principal,
                credentials=credentials,
                now=clock(),
                head_only=request.method == "HEAD",
            )
        except SpatialDataDomainError as exc:
            return error_response(exc)

    return router
