"""단면 전용 요청자 HTTP. 파일·수치 접근 권한은 기존 소유자에게 다시 확인한다."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from ksi_event_contracts._spatial_data import MAX_COUNTER
from ksi_event_contracts.surface_profile_job import (
    CreateSurfaceProfileJobV1,
    SurfaceProfileErrorV1,
    SurfaceProfileJobPageV1,
    SurfaceProfileJobViewV1,
    SurfaceProfilePolicyV1,
    SurfaceProfileResultViewV1,
)
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from ksi_core.domains.external.delivery.api import (
    bounded_json,
    model_response,
    request_credentials,
    request_schema,
)
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.surface_profile_jobs import (
    SurfaceProfileDomainError,
    SurfaceProfileJobStore,
)
from ksi_core.identity.auth import Permission, Principal, require_permission

PUBLIC_BASE = "/v1/sites/{site_id}/work-areas/{work_area_id}/surface-profile-jobs"
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": SurfaceProfileErrorV1, "description": "현재 권한과 단면 계약에 따른 거부"}
    for code in (403, 404, 409, 410, 413, 422, 429, 503)
}


@dataclass(frozen=True, slots=True)
class SurfaceProfileHttpLimits:
    request_max_bytes: int
    complete_max_bytes: int
    timeout_seconds: float

    def validate_for(self, policy: SurfaceProfilePolicyV1) -> None:
        if (
            type(self.request_max_bytes) is not int
            or type(self.complete_max_bytes) is not int
            or not 0 < self.request_max_bytes <= self.complete_max_bytes <= MAX_COUNTER
            or self.complete_max_bytes > policy.resource_envelope.max_input_bytes
            or self.complete_max_bytes <= policy.max_result_bytes
            or type(self.timeout_seconds) not in (float, int)
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= policy.resource_envelope.max_deadline_seconds
        ):
            raise ValueError("단면 HTTP 한도는 명시적 정책 envelope 안에 있어야 한다")


def profile_error_response(error: SurfaceProfileDomainError) -> JSONResponse:
    model = SurfaceProfileErrorV1(
        reason=error.reason,
        message="단면 작업을 사용할 수 없습니다.",
        retryable=error.retryable,
        remediation=("CONTACT_OPERATOR",),
    )
    return model_response(model, status=error.status_code)


def translated_transport_error(error: SpatialDataDomainError) -> SurfaceProfileDomainError:
    try:
        return SurfaceProfileDomainError(error.reason, error.status_code, error.retryable)
    except ValidationError:
        reason = {403: "PERMISSION_DENIED", 404: "NOT_FOUND", 503: "CURRENTNESS_UNAVAILABLE"}.get(
            error.status_code, "INVALID_REQUEST"
        )
        return SurfaceProfileDomainError(reason, error.status_code, error.retryable)


async def read_profile_model[Model: BaseModel](
    request: Request,
    model: type[Model],
    *,
    limits: SurfaceProfileHttpLimits,
    complete: bool = False,
) -> Model:
    try:
        value = await bounded_json(
            request,
            limit=limits.complete_max_bytes if complete else limits.request_max_bytes,
            timeout_seconds=limits.timeout_seconds,
        )
        return model.model_validate(value)
    except (SpatialDataDomainError, ValidationError) as exc:
        raise SurfaceProfileDomainError("INVALID_REQUEST", 422) from exc


def current_profile_operation[Model](
    request: Request,
    principal: Principal,
    clock: Callable[[], datetime],
    operation: Callable[[Principal], Model],
) -> Model:
    try:
        current = request_credentials(request, principal).resolve(now=clock())
        return operation(current)
    except SpatialDataDomainError as exc:
        raise translated_transport_error(exc) from exc


def build_surface_profile_router(
    *,
    jobs: SurfaceProfileJobStore,
    limits: SurfaceProfileHttpLimits,
    clock: Callable[[], datetime],
) -> APIRouter:
    limits.validate_for(jobs.policy)
    router = APIRouter(tags=["surface-profile"], responses=ERROR_RESPONSES)
    create_schema = request_schema(CreateSurfaceProfileJobV1)
    create_schema["parameters"] = [
        {
            "name": "Idempotency-Key",
            "in": "header",
            "required": True,
            "schema": {
                "type": "string",
                "minLength": 1,
                "maxLength": jobs.policy.max_idempotency_key_bytes,
            },
        }
    ]

    @router.post(PUBLIC_BASE, response_model=SurfaceProfileJobViewV1, openapi_extra=create_schema)
    async def issue(
        site_id: str,
        work_area_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_REQUEST)),  # noqa: B008
    ) -> Response:
        try:
            await run_in_threadpool(
                jobs.require_requester_scope,
                site_id=site_id,
                work_area_id=work_area_id,
                principal=principal,
                permission=Permission.SPATIAL_DATA_REQUEST,
            )
            body = await read_profile_model(request, CreateSurfaceProfileJobV1, limits=limits)
            view = await run_in_threadpool(
                current_profile_operation,
                request,
                principal,
                clock,
                lambda current: jobs.issue(
                    site_id=site_id,
                    work_area_id=work_area_id,
                    request=body,
                    principal=current,
                    idempotency_key=request.headers.get("idempotency-key", ""),
                    now=clock(),
                ),
            )
            return model_response(view)
        except SurfaceProfileDomainError as exc:
            return profile_error_response(exc)

    @router.get(PUBLIC_BASE, response_model=SurfaceProfileJobPageV1)
    def list_jobs(
        site_id: str,
        work_area_id: str,
        request: Request,
        limit: int = 1,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_READ)),  # noqa: B008
    ) -> Response:
        try:
            page = current_profile_operation(
                request,
                principal,
                clock,
                lambda current: SurfaceProfileJobPageV1(
                    items=jobs.list(
                        site_id=site_id,
                        work_area_id=work_area_id,
                        principal=current,
                        limit=limit,
                        now=clock(),
                    )
                ),
            )
            return model_response(page)
        except SurfaceProfileDomainError as exc:
            return profile_error_response(exc)

    @router.get(PUBLIC_BASE + "/{job_id}", response_model=SurfaceProfileJobViewV1)
    def get_job(
        site_id: str,
        work_area_id: str,
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_READ)),  # noqa: B008
    ) -> Response:
        try:
            return model_response(
                current_profile_operation(
                    request,
                    principal,
                    clock,
                    lambda current: jobs.get(
                        job_id=job_id,
                        principal=current,
                        now=clock(),
                        expected_scope=(site_id, work_area_id),
                    ),
                )
            )
        except SurfaceProfileDomainError as exc:
            return profile_error_response(exc)

    @router.get(PUBLIC_BASE + "/{job_id}/result", response_model=SurfaceProfileResultViewV1)
    def result(
        site_id: str,
        work_area_id: str,
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_READ)),  # noqa: B008
    ) -> Response:
        try:
            return model_response(
                current_profile_operation(
                    request,
                    principal,
                    clock,
                    lambda current: jobs.result(
                        job_id=job_id,
                        principal=current,
                        now=clock(),
                        expected_scope=(site_id, work_area_id),
                    ),
                )
            )
        except SurfaceProfileDomainError as exc:
            return profile_error_response(exc)

    @router.post(PUBLIC_BASE + "/{job_id}/cancel", response_model=SurfaceProfileJobViewV1)
    def cancel(
        site_id: str,
        work_area_id: str,
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_REQUEST)),  # noqa: B008
    ) -> Response:
        try:
            return model_response(
                current_profile_operation(
                    request,
                    principal,
                    clock,
                    lambda current: jobs.cancel(
                        job_id=job_id,
                        principal=current,
                        now=clock(),
                        expected_scope=(site_id, work_area_id),
                    ),
                )
            )
        except SurfaceProfileDomainError as exc:
            return profile_error_response(exc)

    return router
