"""단면 일꾼의 활성 instance와 현재 lease에 결속된 HTTP 전송."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from ksi_event_contracts.spatial_data import SpatialDataAttemptV1
from ksi_event_contracts.surface_profile_job import (
    SURFACE_PROFILE_ATTEMPT_DIGEST_HEADER,
    SURFACE_PROFILE_WORKER_INSTANCE_ID_HEADER,
    SurfaceProfileActivationV1,
    SurfaceProfileAttemptV1,
    SurfaceProfileCompleteRequestV1,
    SurfaceProfileFailureRequestV1,
    SurfaceProfileJobViewV1,
    SurfaceProfileLeaseRequestV1,
    SurfaceProfileLeaseViewV1,
    SurfaceProfileRenewRequestV1,
    SurfaceProfileWorkerInputResponseV1,
    SurfaceProfileWorkerInputV1,
    SurfaceProfileWorkerPendingItemV1,
    SurfaceProfileWorkerPendingPageV1,
)
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from ksi_core.domains.external.delivery.api import (
    model_response,
    request_credentials,
    request_schema,
)
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


def storage_lease_bound(attempt: SurfaceProfileAttemptV1) -> SpatialDataAttemptV1:
    """저장소 포트가 서명 만료 상한으로만 쓰는 lease 운반체.

    포트는 native 작업의 attempt 형식을 요구한다. 단면 작업 ID의 32자리 16진수를 같은
    자리 배치로 옮기고 봉인만 새로 하며, 저장하거나 응답에 싣지 않는다.
    """
    hex_id = attempt.job_id.removeprefix("spj-")
    native_id = f"sdj-v1-{hex_id[:8]}-{hex_id[8:12]}-{hex_id[12:16]}-{hex_id[16:20]}-{hex_id[20:]}"
    payload = attempt.model_dump(by_alias=True, exclude={"attempt_digest"})
    payload["jobId"] = native_id
    return SpatialDataAttemptV1.model_validate(payload).sealed()


def build_surface_profile_worker_router(
    *,
    jobs: SurfaceProfileJobStore,
    limits: SurfaceProfileHttpLimits,
    clock: Callable[[], datetime],
    storage: Any,
    activation: SurfaceProfileActivationV1,
) -> APIRouter:
    limits.validate_for(jobs.policy)
    activation = SurfaceProfileActivationV1.model_validate(activation.__dict__)
    if (
        activation.activation_digest != activation.canonical_digest()
        or activation.policy_digest != jobs.policy.policy_digest
        or not callable(getattr(storage, "issue_source_get", None))
    ):
        raise ValueError("worker routes require the exact sealed activation and a storage port")
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
            digest = request.headers.get(SURFACE_PROFILE_ATTEMPT_DIGEST_HEADER, "")

            def prove(current: Principal) -> tuple[Any, SurfaceProfileAttemptV1]:
                return jobs.worker_input_for_attempt_digest(
                    job_id=job_id,
                    worker=current,
                    instance_id=worker_instance,
                    attempt_digest=digest,
                    now=clock(),
                )

            def issue(current: Principal) -> SurfaceProfileWorkerInputV1:
                job, attempt = prove(current)
                expires = min(
                    attempt.lease_until, job.deadline, job.grant.valid_until, activation.valid_until
                )
                # 저장소 호출은 원격일 수 있으므로 잠금 밖에서 수행하고, 끝난 뒤 다시 증명한다.
                capability = storage.issue_source_get(
                    job.source,
                    storage_lease_bound(attempt),
                    expires_at=expires,
                )
                refreshed = request_credentials(request, principal).resolve(now=clock())
                job_again, attempt_again = prove(refreshed)
                if (job_again, attempt_again) != (job, attempt) or capability.expires_at > expires:
                    raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 503)
                try:
                    if capability.expires_at <= clock():
                        raise ValueError("expired capability")
                    return SurfaceProfileWorkerInputV1(
                        job=job,
                        attempt=attempt,
                        activation=activation,
                        source_capability=capability,
                    )
                except (ValueError, ValidationError) as exc:
                    raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 503) from exc

            return model_response(
                SurfaceProfileWorkerInputResponseV1(
                    input=current_profile_operation(request, principal, clock, issue)
                )
            )
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
