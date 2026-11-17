"""단면 일꾼의 활성 instance와 현재 lease에 결속된 HTTP 전송."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from ksi_event_contracts.surface_profile_job import (
    SURFACE_PROFILE_ATTEMPT_DIGEST_HEADER,
    SURFACE_PROFILE_WORKER_INSTANCE_ID_HEADER,
    SurfaceProfileAttemptV1,
    SurfaceProfileCompleteRequestV1,
    SurfaceProfileFailureRequestV1,
    SurfaceProfileJobViewV1,
    SurfaceProfileLeaseRequestV1,
    SurfaceProfileLeaseViewV1,
    SurfaceProfileRenewRequestV1,
    SurfaceProfileWorkerInputResponseV1,
    SurfaceProfileWorkerPendingItemV1,
    SurfaceProfileWorkerPendingPageV1,
)
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from ksi_core.domains.external.delivery.api import model_response, request_schema
from ksi_core.domains.external.delivery.surface_profile_api import (
    ERROR_RESPONSES,
    SurfaceProfileHttpLimits,
    current_profile_operation,
    profile_error_response,
    read_profile_model,
)
from ksi_core.domains.external.delivery.surface_profile_jobs import (
    SurfaceProfileDomainError,
    SurfaceProfileJobStore,
)
from ksi_core.identity.auth import Permission, Principal, require_permission

INTERNAL_BASE = "/v1/internal/surface-profile-jobs"


def worker_schema(model: type[BaseModel] | None = None, *, fence: bool = True) -> dict[str, Any]:
    schema = request_schema(model) if model is not None else {}
    headers: list[dict[str, Any]] = [
        {
            "name": SURFACE_PROFILE_WORKER_INSTANCE_ID_HEADER,
            "in": "header",
            "required": True,
            "schema": {"type": "string", "minLength": 1, "maxLength": 255},
        }
    ]
    if fence:
        headers.append(
            {
                "name": SURFACE_PROFILE_ATTEMPT_DIGEST_HEADER,
                "in": "header",
                "required": True,
                "schema": {
                    "type": "string",
                    "minLength": 71,
                    "maxLength": 71,
                    "pattern": "^sha256:[0-9a-f]{64}$",
                },
            }
        )
    schema["parameters"] = headers
    return schema


def build_surface_profile_worker_router(
    *,
    jobs: SurfaceProfileJobStore,
    limits: SurfaceProfileHttpLimits,
    clock: Callable[[], datetime],
) -> APIRouter:
    limits.validate_for(jobs.policy)
    router = APIRouter(tags=["surface-profile-worker"], responses=ERROR_RESPONSES)

    def instance(request: Request) -> str:
        value = request.headers.get(SURFACE_PROFILE_WORKER_INSTANCE_ID_HEADER, "")
        if not value or len(value) > 255 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise SurfaceProfileDomainError("INVALID_REQUEST", 422)
        return value

    def fence(request: Request, attempt: SurfaceProfileAttemptV1) -> None:
        if (
            instance(request) != attempt.worker_instance_id
            or request.headers.get(SURFACE_PROFILE_ATTEMPT_DIGEST_HEADER) != attempt.attempt_digest
        ):
            raise SurfaceProfileDomainError("FENCE_CONFLICT", 409)

    async def body_for[Model: BaseModel](
        request: Request,
        principal: Principal,
        model: type[Model],
        *,
        complete: bool = False,
    ) -> Model:
        await run_in_threadpool(
            jobs.require_worker,
            worker=principal,
            instance_id=instance(request),
            now=clock(),
        )
        return await read_profile_model(request, model, limits=limits, complete=complete)

    @router.get(
        INTERNAL_BASE,
        response_model=SurfaceProfileWorkerPendingPageV1,
        openapi_extra=worker_schema(fence=False),
    )
    def pending(
        request: Request,
        limit: int = 1,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_WORK)),  # noqa: B008
    ) -> Response:
        try:
            worker_instance = instance(request)
            page = current_profile_operation(
                request,
                principal,
                clock,
                lambda current: SurfaceProfileWorkerPendingPageV1(
                    items=tuple(
                        SurfaceProfileWorkerPendingItemV1(job_id=job.job_id)
                        for job in jobs.pending(
                            worker=current, instance_id=worker_instance, limit=limit, now=clock()
                        )
                    )
                ),
            )
            return model_response(page)
        except SurfaceProfileDomainError as exc:
            return profile_error_response(exc)

    @router.post(
        INTERNAL_BASE + "/{job_id}/lease",
        response_model=SurfaceProfileLeaseViewV1,
        openapi_extra=worker_schema(SurfaceProfileLeaseRequestV1, fence=False),
    )
    async def lease(
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_WORK)),  # noqa: B008
    ) -> Response:
        try:
            body = await body_for(request, principal, SurfaceProfileLeaseRequestV1)
            if body.worker_instance_id != instance(request):
                raise SurfaceProfileDomainError("FENCE_CONFLICT", 409)
            attempt = await run_in_threadpool(
                current_profile_operation,
                request,
                principal,
                clock,
                lambda current: jobs.lease(
                    job_id=job_id, worker=current, request=body, now=clock()
                ),
            )
            return model_response(SurfaceProfileLeaseViewV1(job_id=job_id, attempt=attempt))
        except SurfaceProfileDomainError as exc:
            return profile_error_response(exc)

    @router.post(
        INTERNAL_BASE + "/{job_id}/renew",
        response_model=SurfaceProfileLeaseViewV1,
        openapi_extra=worker_schema(SurfaceProfileRenewRequestV1),
    )
    async def renew(
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_WORK)),  # noqa: B008
    ) -> Response:
        try:
            body = await body_for(request, principal, SurfaceProfileRenewRequestV1)
            fence(request, body.attempt)
            attempt = await run_in_threadpool(
                current_profile_operation,
                request,
                principal,
                clock,
                lambda current: jobs.renew(
                    job_id=job_id, worker=current, attempt=body.attempt, now=clock()
                ),
            )
            return model_response(SurfaceProfileLeaseViewV1(job_id=job_id, attempt=attempt))
        except SurfaceProfileDomainError as exc:
            return profile_error_response(exc)

    @router.get(
        INTERNAL_BASE + "/{job_id}/input",
        response_model=SurfaceProfileWorkerInputResponseV1,
        openapi_extra=worker_schema(),
    )
    def input(
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_WORK)),  # noqa: B008
    ) -> Response:
        try:
            worker_instance = instance(request)
            job = current_profile_operation(
                request,
                principal,
                clock,
                lambda current: jobs.worker_input_for_attempt_digest(
                    job_id=job_id,
                    worker=current,
                    instance_id=worker_instance,
                    attempt_digest=request.headers.get(SURFACE_PROFILE_ATTEMPT_DIGEST_HEADER, ""),
                    now=clock(),
                ),
            )
            return model_response(SurfaceProfileWorkerInputResponseV1(input=job))
        except SurfaceProfileDomainError as exc:
            return profile_error_response(exc)

    @router.post(
        INTERNAL_BASE + "/{job_id}/complete",
        response_model=SurfaceProfileJobViewV1,
        openapi_extra=worker_schema(SurfaceProfileCompleteRequestV1),
    )
    async def complete(
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_WORK)),  # noqa: B008
    ) -> Response:
        try:
            body = await body_for(
                request, principal, SurfaceProfileCompleteRequestV1, complete=True
            )
            fence(request, body.attempt)
            view = await run_in_threadpool(
                current_profile_operation,
                request,
                principal,
                clock,
                lambda current: jobs.complete(
                    job_id=job_id,
                    worker=current,
                    attempt=body.attempt,
                    result=body.result,
                    receipt=body.receipt,
                    now=clock(),
                ),
            )
            return model_response(view)
        except SurfaceProfileDomainError as exc:
            return profile_error_response(exc)

    @router.post(
        INTERNAL_BASE + "/{job_id}/failure",
        response_model=SurfaceProfileJobViewV1,
        openapi_extra=worker_schema(SurfaceProfileFailureRequestV1),
    )
    async def failure(
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_WORK)),  # noqa: B008
    ) -> Response:
        try:
            body = await body_for(request, principal, SurfaceProfileFailureRequestV1)
            fence(request, body.attempt)
            view = await run_in_threadpool(
                current_profile_operation,
                request,
                principal,
                clock,
                lambda current: jobs.fail(
                    job_id=job_id,
                    worker=current,
                    attempt=body.attempt,
                    reason=body.reason,
                    now=clock(),
                ),
            )
            return model_response(view)
        except SurfaceProfileDomainError as exc:
            return profile_error_response(exc)

    return router
