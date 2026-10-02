"""Dedicated fenced worker routes; no client-selected storage keys, source URLs or versions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from ksi_event_contracts.spatial_data import SpatialDataAttemptV1, SpatialDataErrorV1
from ksi_event_contracts.spatial_data_authority import SpatialDataActivationV1
from ksi_event_contracts.spatial_data_worker import (
    SPATIAL_DATA_ATTEMPT_DIGEST_HEADER,
    SPATIAL_DATA_WORKER_INSTANCE_ID_HEADER,
    SpatialDataCompleteRequestV1,
    SpatialDataFailureRequestV1,
    SpatialDataLeaseRequestV1,
    SpatialDataLeaseViewV1,
    SpatialDataOutputUploadRequestV1,
    SpatialDataOutputUploadViewV1,
    SpatialDataRenewRequestV1,
    SpatialDataWorkerInputResponseV1,
    SpatialDataWorkerMutationViewV1,
    SpatialDataWorkerPendingPageV1,
)
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from ksi_core.domains.external.delivery.api import (
    error_response,
    model_response,
    read_model,
    request_credentials,
    request_schema,
)
from ksi_core.domains.external.delivery.capabilities import SpatialDataWorkerCapabilities
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.jobs import SpatialDataJobStore
from ksi_core.domains.external.delivery.storage import SpatialDataStoragePort
from ksi_core.identity.auth import Permission, Principal, require_permission

INTERNAL_BASE = "/v1/internal/spatial-data-jobs"


def worker_schema(model: type | None = None, *, fence: bool = True) -> dict:
    schema = request_schema(model) if model is not None else {}
    headers = [
        {
            "name": SPATIAL_DATA_WORKER_INSTANCE_ID_HEADER,
            "in": "header",
            "required": True,
            "schema": {"type": "string", "minLength": 1, "maxLength": 255},
        }
    ]
    if fence:
        headers.append(
            {
                "name": SPATIAL_DATA_ATTEMPT_DIGEST_HEADER,
                "in": "header",
                "required": True,
                "schema": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
            }
        )
    schema["parameters"] = headers
    return schema


def build_spatial_data_worker_router(
    *,
    jobs: SpatialDataJobStore,
    storage: SpatialDataStoragePort,
    activation: SpatialDataActivationV1,
    clock: Callable[[], datetime],
) -> APIRouter:
    capabilities = SpatialDataWorkerCapabilities(
        jobs=jobs, storage=storage, activation=activation, clock=clock
    )
    activation = capabilities.activation
    router = APIRouter(
        tags=["spatial-data-worker"],
        responses={
            code: {"model": SpatialDataErrorV1, "description": "Typed safe worker-lane refusal"}
            for code in (403, 404, 409, 422, 503)
        },
    )

    def instance(request: Request) -> str:
        identity = request.headers.get(SPATIAL_DATA_WORKER_INSTANCE_ID_HEADER, "")
        if identity != activation.worker_instance_id:
            raise SpatialDataDomainError("FENCE_CONFLICT", 409)
        return identity

    def fence(request: Request, attempt: SpatialDataAttemptV1) -> None:
        if (
            instance(request) != attempt.worker_instance_id
            or request.headers.get(SPATIAL_DATA_ATTEMPT_DIGEST_HEADER) != attempt.attempt_digest
        ):
            raise SpatialDataDomainError("FENCE_CONFLICT", 409)

    @router.get(
        INTERNAL_BASE,
        response_model=SpatialDataWorkerPendingPageV1,
        openapi_extra=worker_schema(fence=False),
    )
    def pending(
        request: Request,
        limit: int | None = None,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_WORK)),  # noqa: B008
    ) -> Response:
        try:
            instance(request)
            jobs_page = jobs.pending(
                worker=principal,
                limit=limit if limit is not None else min(200, jobs.policy.max_pending_records),
                now=clock(),
            )
            return model_response(SpatialDataWorkerPendingPageV1(items=jobs_page))
        except SpatialDataDomainError as exc:
            return error_response(exc)

    @router.post(
        INTERNAL_BASE + "/{job_id}/lease",
        response_model=SpatialDataLeaseViewV1,
        openapi_extra=worker_schema(SpatialDataLeaseRequestV1, fence=False),
    )
    async def lease(
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_WORK)),  # noqa: B008
    ) -> Response:
        try:
            worker_instance = instance(request)
            body = await read_model(request, SpatialDataLeaseRequestV1, jobs=jobs)
            if body.worker_instance_id != worker_instance:
                raise SpatialDataDomainError("FENCE_CONFLICT", 409)
            principal = await run_in_threadpool(
                request_credentials(request, principal).resolve, now=clock()
            )
            attempt = await run_in_threadpool(
                jobs.lease,
                job_id=job_id,
                worker=principal,
                instance_id=worker_instance,
                acquisition_id=body.acquisition_id,
                now=clock(),
            )
            return model_response(SpatialDataLeaseViewV1(job_id=job_id, attempt=attempt))
        except SpatialDataDomainError as exc:
            return error_response(exc)

    @router.post(
        INTERNAL_BASE + "/{job_id}/renew",
        response_model=SpatialDataLeaseViewV1,
        openapi_extra=worker_schema(SpatialDataRenewRequestV1),
    )
    async def renew(
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_WORK)),  # noqa: B008
    ) -> Response:
        try:
            body = await read_model(request, SpatialDataRenewRequestV1, jobs=jobs)
            fence(request, body.attempt)
            principal = await run_in_threadpool(
                request_credentials(request, principal).resolve, now=clock()
            )
            attempt = await run_in_threadpool(
                jobs.renew, job_id=job_id, worker=principal, attempt=body.attempt, now=clock()
            )
            return model_response(SpatialDataLeaseViewV1(job_id=job_id, attempt=attempt))
        except SpatialDataDomainError as exc:
            return error_response(exc)

    @router.get(
        INTERNAL_BASE + "/{job_id}/input",
        response_model=SpatialDataWorkerInputResponseV1,
        openapi_extra=worker_schema(),
    )
    def input(
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_WORK)),  # noqa: B008
    ) -> Response:
        try:
            attempt = jobs.resolve_worker_attempt(
                job_id=job_id,
                worker=principal,
                instance_id=instance(request),
                attempt_digest=request.headers.get(SPATIAL_DATA_ATTEMPT_DIGEST_HEADER, ""),
                now=clock(),
            )
            result = capabilities.input(
                job_id=job_id,
                worker=principal,
                attempt=attempt,
                credentials=request_credentials(request, principal),
            )
            return model_response(SpatialDataWorkerInputResponseV1(input=result))
        except SpatialDataDomainError as exc:
            return error_response(exc)

    @router.post(
        INTERNAL_BASE + "/{job_id}/output-upload",
        response_model=SpatialDataOutputUploadViewV1,
        openapi_extra=worker_schema(SpatialDataOutputUploadRequestV1),
    )
    async def upload(
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_WORK)),  # noqa: B008
    ) -> Response:
        try:
            body = await read_model(request, SpatialDataOutputUploadRequestV1, jobs=jobs)
            fence(request, body.declaration.attempt)
            credentials = request_credentials(request, principal)
            principal = await run_in_threadpool(credentials.resolve, now=clock())
            result = await run_in_threadpool(
                capabilities.upload,
                job_id=job_id,
                worker=principal,
                declaration=body.declaration,
                credentials=credentials,
            )
            return model_response(result)
        except SpatialDataDomainError as exc:
            return error_response(exc)

    @router.post(
        INTERNAL_BASE + "/{job_id}/complete",
        response_model=SpatialDataWorkerMutationViewV1,
        openapi_extra=worker_schema(SpatialDataCompleteRequestV1),
    )
    async def complete(
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_WORK)),  # noqa: B008
    ) -> Response:
        try:
            body = await read_model(request, SpatialDataCompleteRequestV1, jobs=jobs)
            fence(request, body.attempt)
            credentials = request_credentials(request, principal)
            principal = await run_in_threadpool(credentials.resolve, now=clock())
            result = await run_in_threadpool(
                capabilities.complete,
                job_id=job_id,
                worker=principal,
                attempt=body.attempt,
                upload_digest=body.upload_digest,
                credentials=credentials,
            )
            return model_response(SpatialDataWorkerMutationViewV1(job=result))
        except SpatialDataDomainError as exc:
            return error_response(exc)

    @router.post(
        INTERNAL_BASE + "/{job_id}/failure",
        response_model=SpatialDataWorkerMutationViewV1,
        openapi_extra=worker_schema(SpatialDataFailureRequestV1),
    )
    async def failure(
        job_id: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_WORK)),  # noqa: B008
    ) -> Response:
        try:
            body = await read_model(request, SpatialDataFailureRequestV1, jobs=jobs)
            fence(request, body.attempt)
            principal = await run_in_threadpool(
                request_credentials(request, principal).resolve, now=clock()
            )
            result = await run_in_threadpool(
                jobs.fail,
                job_id=job_id,
                worker=principal,
                attempt=body.attempt,
                reason=body.reason,
                now=clock(),
            )
            return model_response(SpatialDataWorkerMutationViewV1(job=result))
        except SpatialDataDomainError as exc:
            return error_response(exc)

    return router
