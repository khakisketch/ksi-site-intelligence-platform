"""Optional, closed, bounded HTTP seam for separate observed delta publications.

No route mounts by default. Public Analysis contracts and old worker transports
remain unchanged. Dedicated MCP identities retain scope/consent requirements;
humans cannot impersonate AI purpose through a caller-controlled header.
"""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from ksi_event_contracts.external_delta_publication_api import (
    CreateDeltaPublicationV1,
    DeltaOutputObservationWireV1,
    DeltaPublicationBytesV1,
    DeltaPublicationIntentViewV1,
    DeltaPublicationPendingJobsV1,
    DeltaPublicationViewV1,
)
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError
from pydantic.alias_generators import to_camel
from starlette.concurrency import run_in_threadpool

from ksi_core.domains.external.quantity.external_delta_output_observations import (
    CoreDeltaOutputObservationStore,
)
from ksi_core.domains.external.quantity.external_delta_publications import (
    DeltaOutputObservation,
    DeltaPublicationView,
    ExternalDeltaPublicationStore,
)
from ksi_core.identity.auth import (
    Permission,
    Principal,
    PrincipalKind,
    require_permission,
    require_permission_any,
)

_MAX_JSON = 65536
_MAX_SLICE = 1024 * 1024


def _json_body(model: type[BaseModel]) -> dict[str, object]:
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": model.model_json_schema(by_alias=True)},
            },
        }
    }


class _Control(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class _Reason(_Control):
    reason: str = Field(min_length=1, max_length=255)


class _Lease(_Control):
    worker_instance_id: str = Field(min_length=1, max_length=255)
    lease_acquisition_id: str = Field(min_length=1, max_length=255)


class _Failure(_Reason):
    worker_instance_id: str = Field(min_length=1, max_length=255)
    lease_generation: StrictInt = Field(ge=1)


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError("non-finite JSON value")


async def _bounded_json[Model: BaseModel](request: Request, model: type[Model]) -> Model:
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise HTTPException(status_code=415, detail="JSON_REQUIRED")
    payload = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(payload) + len(chunk) > _MAX_JSON:
                    raise HTTPException(status_code=413, detail="DELTA_REQUEST_TOO_LARGE")
                payload.extend(chunk)
        return model.model_validate(
            json.loads(
                payload,
                object_pairs_hook=_reject_duplicates,
                parse_constant=_reject_constant,
            )
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail="DELTA_REQUEST_TIMED_OUT") from exc
    except (ValueError, UnicodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="DELTA_REQUEST_INVALID") from exc


def _intent(view: Any) -> DeltaPublicationIntentViewV1:
    return DeltaPublicationIntentViewV1(
        **{name: getattr(view, name) for name in DeltaPublicationIntentViewV1.model_fields},
    )


def _public(view: Any) -> DeltaPublicationViewV1:
    return DeltaPublicationViewV1(
        **{name: getattr(view, name) for name in DeltaPublicationViewV1.model_fields},
    )


def build_external_delta_publication_router(
    *,
    store: ExternalDeltaPublicationStore,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    if not isinstance(store, ExternalDeltaPublicationStore):
        raise ValueError("delta router requires the concrete Core publication store")
    now = clock or (lambda: datetime.now(UTC))
    router = APIRouter(tags=["external-delta-publication"])
    read = require_permission_any(Permission.SITES_READ, Permission.ANALYSIS_API_READ)
    write = require_permission_any(Permission.SITES_WRITE, Permission.ANALYSIS_API_CREATE)
    worker = require_permission(Permission.ANALYSIS_WORK)

    def consumer(principal: Principal) -> None:
        if principal.kind not in {PrincipalKind.OPERATOR, PrincipalKind.ANALYSIS_MCP_CLIENT}:
            raise HTTPException(status_code=403, detail="DELTA_CONSUMER_REQUIRED")

    def worker_only(principal: Principal) -> None:
        if principal.kind is not PrincipalKind.ANALYSIS_WORKER:
            raise HTTPException(status_code=403, detail="DELTA_WORKER_REQUIRED")

    def consent(principal: Principal, site_id: str, work_area_id: str, response: Response) -> None:
        consumer(principal)
        response.headers["Cache-Control"] = "no-store"
        if principal.kind is not PrincipalKind.ANALYSIS_MCP_CLIENT:
            return
        if not store._egress.is_egress_allowed(
            organization_id=principal.organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            principal=principal,
            now=now(),
        ):
            raise HTTPException(status_code=403, detail="AI_EGRESS_NOT_ALLOWED")
        response.headers["X-KSI-External-AI-Egress"] = "ALLOWED"

    def target(principal: Principal, publication_id: str, site_id: str, work_area_id: str) -> None:
        if not store.intent_matches_scope(
            principal=principal,
            publication_id=publication_id,
            site_id=site_id,
            work_area_id=work_area_id,
        ):
            raise HTTPException(status_code=404, detail="DELTA_PUBLICATION_NOT_FOUND")

    @router.post(
        "/v1/sites/{site_id}/work-areas/{work_area_id}/delta-publications",
        response_model=DeltaPublicationIntentViewV1,
        openapi_extra=_json_body(CreateDeltaPublicationV1),
    )
    async def create(
        site_id: str,
        work_area_id: str,
        request: Request,
        response: Response,
        principal: Principal = Depends(write),  # noqa: B008
    ) -> DeltaPublicationIntentViewV1:
        consent(principal, site_id, work_area_id, response)
        body = await _bounded_json(request, CreateDeltaPublicationV1)
        try:
            return _intent(
                await run_in_threadpool(
                    store.request_publication,
                    principal=principal,
                    site_id=site_id,
                    work_area_id=work_area_id,
                    **body.model_dump(),
                )
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="DELTA_SCOPE_DENIED") from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=409, detail="DELTA_SOURCE_OR_AUTHORITY_UNAVAILABLE"
            ) from exc

    @router.get(
        "/v1/sites/{site_id}/work-areas/{work_area_id}/delta-publications/{publication_id}",
        response_model=DeltaPublicationViewV1,
    )
    def detail(
        site_id: str,
        work_area_id: str,
        publication_id: str,
        response: Response,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> DeltaPublicationViewV1:
        consent(principal, site_id, work_area_id, response)
        target(principal, publication_id, site_id, work_area_id)
        view, disposition = store.get_current_with_disposition(
            publication_id,
            principal=principal,
            now=now(),
        )
        if view is None:
            # Only a caller already authorized for this exact immutable scope
            # learns the bounded state code. Foreign/unknown ids remain absent.
            # No descriptor or bytes are returned on these unavailable states.
            raise HTTPException(status_code=404, detail=f"DELTA_PUBLICATION_{disposition.value}")
        return _public(view)

    @router.get(
        "/v1/sites/{site_id}/work-areas/{work_area_id}/delta-publications/{publication_id}/bytes",
        response_model=DeltaPublicationBytesV1,
    )
    def read_bytes(
        site_id: str,
        work_area_id: str,
        publication_id: str,
        response: Response,
        offset: int = Query(ge=0),
        length: int = Query(gt=0, le=_MAX_SLICE),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> DeltaPublicationBytesV1:
        consent(principal, site_id, work_area_id, response)
        target(principal, publication_id, site_id, work_area_id)
        try:
            payload = store.read_bytes(
                publication_id, principal=principal, offset=offset, length=length
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="DELTA_READ_RANGE_INVALID") from exc
        if payload is None:
            raise HTTPException(status_code=404, detail="DELTA_PUBLICATION_NOT_AVAILABLE")
        return DeltaPublicationBytesV1(
            publication_id=publication_id,
            offset=offset,
            content_base64=base64.b64encode(payload).decode("ascii"),
        )

    @router.post(
        "/v1/sites/{site_id}/work-areas/{work_area_id}/delta-publications/{publication_id}/revoke",
        response_model=DeltaPublicationViewV1,
        openapi_extra=_json_body(_Reason),
    )
    async def revoke(
        site_id: str,
        work_area_id: str,
        publication_id: str,
        request: Request,
        response: Response,
        principal: Principal = Depends(write),  # noqa: B008
    ) -> DeltaPublicationViewV1:
        consent(principal, site_id, work_area_id, response)
        target(principal, publication_id, site_id, work_area_id)
        body = await _bounded_json(request, _Reason)
        view = store.revoke(
            principal=principal, publication_id=publication_id, reason=body.reason, now=now()
        )
        if view is None:
            raise HTTPException(status_code=404, detail="DELTA_PUBLICATION_NOT_FOUND")
        return _public(view)

    @router.post(
        "/v1/sites/{site_id}/work-areas/{work_area_id}/delta-publications/{publication_id}/cancel",
        response_model=DeltaPublicationIntentViewV1,
        openapi_extra=_json_body(_Reason),
    )
    async def cancel(
        site_id: str,
        work_area_id: str,
        publication_id: str,
        request: Request,
        response: Response,
        principal: Principal = Depends(write),  # noqa: B008
    ) -> DeltaPublicationIntentViewV1:
        consent(principal, site_id, work_area_id, response)
        target(principal, publication_id, site_id, work_area_id)
        body = await _bounded_json(request, _Reason)
        view = store.cancel_intent(
            principal=principal, publication_id=publication_id, reason=body.reason, now=now()
        )
        if view is None:
            raise HTTPException(status_code=404, detail="DELTA_PUBLICATION_NOT_FOUND")
        return _intent(view)

    @router.get(
        "/v1/internal/delta-publication-uploads",
        response_model=DeltaPublicationPendingJobsV1,
    )
    def pending_jobs(
        limit: int = Query(default=50, ge=1, le=50),
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> DeltaPublicationPendingJobsV1:
        worker_only(principal)
        return DeltaPublicationPendingJobsV1(
            publication_ids=store.list_pending_for_worker(worker_principal=principal, limit=limit),
        )

    @router.post(
        "/v1/internal/delta-publication-uploads/{publication_id}/lease",
        response_model=DeltaPublicationIntentViewV1,
        openapi_extra=_json_body(_Lease),
    )
    async def acquire(
        publication_id: str,
        request: Request,
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> DeltaPublicationIntentViewV1:
        worker_only(principal)
        body = await _bounded_json(request, _Lease)
        view = store.acquire_upload_lease(
            worker_principal=principal,
            publication_id=publication_id,
            now=now(),
            **body.model_dump(),
        )
        if view is None:
            raise HTTPException(status_code=404, detail="DELTA_JOB_NOT_FOUND")
        return _intent(view)

    @router.get(
        "/v1/internal/delta-publication-uploads/{publication_id}",
        response_model=DeltaPublicationIntentViewV1,
    )
    def worker_intent(
        publication_id: str,
        worker_instance_id: str = Query(min_length=1, max_length=255),
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> DeltaPublicationIntentViewV1:
        worker_only(principal)
        view = store.intent_for_worker(
            publication_id, worker_principal=principal, worker_instance_id=worker_instance_id
        )
        if view is None:
            raise HTTPException(status_code=404, detail="DELTA_JOB_NOT_FOUND")
        return _intent(view)

    @router.post(
        "/v1/internal/delta-publication-uploads/{publication_id}/observation",
        response_model=DeltaOutputObservationWireV1,
        openapi_extra=_json_body(DeltaOutputObservationWireV1),
    )
    async def observe(
        publication_id: str,
        request: Request,
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> DeltaOutputObservationWireV1:
        worker_only(principal)
        body = await _bounded_json(request, DeltaOutputObservationWireV1)
        if body.publication_id != publication_id:
            raise HTTPException(status_code=404, detail="DELTA_JOB_NOT_FOUND")
        if not isinstance(store._observations, CoreDeltaOutputObservationStore):
            raise HTTPException(status_code=503, detail="DELTA_OUTPUT_ACCEPTANCE_UNAVAILABLE")
        try:
            receipt = await run_in_threadpool(
                store._observations.record_worker_result,
                publication_store=store,
                worker_principal=principal,
                observation=DeltaOutputObservation(**body.model_dump()),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409, detail="DELTA_OUTPUT_OBSERVATION_REJECTED"
            ) from exc
        if receipt is None:
            raise HTTPException(status_code=404, detail="DELTA_JOB_NOT_FOUND")
        return body

    @router.post(
        "/v1/internal/delta-publication-uploads/{publication_id}/bytes",
        response_model=DeltaPublicationViewV1,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
                },
            }
        },
    )
    async def upload(
        publication_id: str,
        request: Request,
        worker_instance_id: str = Query(min_length=1, max_length=255),
        lease_generation: int = Query(gt=0),
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> DeltaPublicationViewV1:
        worker_only(principal)
        lease = store.intent_for_worker(
            publication_id, worker_principal=principal, worker_instance_id=worker_instance_id
        )
        if lease is None or lease.lease_generation != lease_generation:
            raise HTTPException(status_code=404, detail="DELTA_JOB_NOT_FOUND")
        if request.headers.get("content-type") != "application/octet-stream":
            raise HTTPException(status_code=415, detail="DELTA_RAW_BYTES_REQUIRED")
        # Raw bounded streaming avoids an unbounded multipart spool occurring
        # before the endpoint's lease/resource check. Core never decodes TIFF.
        with tempfile.TemporaryFile(mode="w+b") as stream:
            total = 0
            try:
                async with asyncio.timeout(30):
                    async for chunk in request.stream():
                        total += len(chunk)
                        if total > store.policy.max_output_bytes:
                            raise HTTPException(status_code=413, detail="DELTA_OUTPUT_TOO_LARGE")
                        await run_in_threadpool(stream.write, chunk)
            except TimeoutError as exc:
                raise HTTPException(status_code=408, detail="DELTA_UPLOAD_TIMED_OUT") from exc
            stream.seek(0)
            try:
                view = await run_in_threadpool(
                    store.publish_output,
                    worker_principal=principal,
                    publication_id=publication_id,
                    worker_instance_id=worker_instance_id,
                    lease_generation=lease_generation,
                    byte_stream=stream,
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail="DELTA_OUTPUT_UPLOAD_REJECTED") from exc
        if view is None:
            raise HTTPException(status_code=404, detail="DELTA_JOB_NOT_FOUND")
        if not isinstance(view, DeltaPublicationView):
            raise HTTPException(status_code=409, detail="DELTA_OUTPUT_UPLOAD_REJECTED")
        return _public(view)

    @router.post(
        "/v1/internal/delta-publication-uploads/{publication_id}/failure",
        response_model=DeltaPublicationIntentViewV1,
        openapi_extra=_json_body(_Failure),
    )
    async def failed(
        publication_id: str,
        request: Request,
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> DeltaPublicationIntentViewV1:
        worker_only(principal)
        body = await _bounded_json(request, _Failure)
        view = store.record_upload_failure(
            worker_principal=principal,
            publication_id=publication_id,
            now=now(),
            **body.model_dump(),
        )
        if view is None:
            raise HTTPException(status_code=404, detail="DELTA_JOB_NOT_FOUND")
        return _intent(view)

    return router
