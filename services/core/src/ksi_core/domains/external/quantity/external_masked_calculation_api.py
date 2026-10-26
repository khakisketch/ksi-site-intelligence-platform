"""Optional, closed, bounded HTTP seam for masked (V3) execution.

Human OPERATOR-only creation/read/cancel over Core-constructed identities;
worker-only fenced lease, three-input fetch, bounded raw-bytes transport,
renew, report, and failure.  No route mounts by default: the parent
composition mounts this router explicitly and owns the auth allowlists.  MCP
identities are denied here (the new mask tools are not approved).

Trust boundaries, read carefully:

- Identities are Core-constructed only.  Creation resolves the exact sealed
  AP source assessment plus the exact sealed mask manifest through
  ``CoreMaskedAdmissionEvidence.bind_identity`` and durably binds the V3
  identity with ``bind_constructed_identity``.  No caller digest fetch, no
  arbitrary V2 completed numeric, no V2 runtime reuse: admission requires
  the current AP assessment alone, and a completed V2 numeric result is
  never required.
- A missing or foreign identity answers uniform 404.  A revoked source,
  expired activation, or stale fence answers 409 with no journal mutation.
- Worker capability transport carries opaque artifact ids plus observed
  SHA/size and expiry (``MaskedWorkerInputV3``); the three bounded raw
  windows below resolve bytes through Core ports only.  The EXCLUSION_MASK
  window authorizes the current live masked attempt through the shared
  sealed-byte port.  It never borrows a completed attempt: ``input_for_worker``
  re-verifies the live fence on every call, and the late delta publication
  lane must bind its own new publication lease behind its own parent-owned
  route (this module exposes no delta route and no presigned URL).
- Provision stays honest: disposition and reason codes come from a fresh
  witness on every read; ADMIT_PROVISIONAL never promotes, and numeric
  content appears only under AVAILABLE.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_masked_api import (
    MASKED_ATTEMPT_DIGEST_HEADER,
    MASKED_WORKER_INSTANCE_ID_HEADER,
    MaskedBytesSliceViewV1,
    MaskedCalculationCreatedViewV1,
    MaskedCalculationCreateRequestV1,
    MaskedCalculationDetailViewV1,
    MaskedCalculationMutationViewV1,
    MaskedCalculationPendingItemV1,
    MaskedCalculationPendingListV1,
    MaskedFailureRequestV1,
    MaskedLeaseRequestV1,
    MaskedRenewRequestV1,
    MaskedReportRequestV1,
)
from ksi_event_contracts.external_masked_execution import MaskedWorkerInputV3
from ksi_event_contracts.external_masked_volume_result import MaskedVolumeCalculationFailureV3
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from starlette.concurrency import run_in_threadpool

from ksi_core.domains.external.quantity.external_masked_calculation_store import (
    ExternalMaskedCalculationStore,
    MaskedExecutionStatusV3,
)
from ksi_core.identity.auth import (
    Permission,
    Principal,
    PrincipalKind,
    require_permission,
)

_MAX_JSON = 65536
_MAX_SLICE = 1024 * 1024


class MaskedEvidencePort(Protocol):
    """Structural port over the genuine masked-evidence adapter (no fake)."""

    def bind_identity(
        self,
        *,
        calculations: ExternalMaskedCalculationStore,
        principal: Principal,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        mask_child_id: str,
        masked_calculation_id: str,
        source_calculation_identity_digest: str,
        now: datetime,
    ) -> Any: ...


class MaskedBytePort(Protocol):
    """Narrow sealed-mask byte port shared with the late delta lane.

    The late delta publication route resolves its third mask input through
    this same port behind its own new publication lease: caller sends source
    identity plus mask child only, Core resolves everything else.
    """

    def fetch_manifest(self, *, organization_id: str, mask_child_id: str) -> Any | None: ...

    def read_slice(
        self, *, organization_id: str, mask_child_id: str, offset: int, length: int
    ) -> bytes: ...

    def read_slice_by_binding(
        self,
        *,
        organization_id: str,
        mask_artifact_id: str,
        observed_sha256: str,
        observed_size_bytes: int,
        offset: int,
        length: int,
    ) -> bytes:
        """Serve one bounded window for a Core-bound mask capability.

        Resolves the unique sealed child for the exact artifact+SHA through
        Core-bound ingress state (never caller identity), re-verifies the
        sealed byte proof, then serves the window.  Ambiguity, missing
        manifests, or mismatched bytes fail closed with ValueError.
        """
        ...


class MaskedDsmByteReader(Protocol):
    """Parent-wired DSM byte resolution (test or production storage).

    Returns the exact sealed window or None when unknown.  Core never
    invents bytes: a missing reader answers 409, never synthetic content.
    """

    def read_slice(
        self,
        *,
        organization_id: str,
        site_id: str,
        artifact_id: str,
        observed_sha256: str,
        observed_size_bytes: int,
        offset: int,
        length: int,
    ) -> bytes | None: ...


class MaskedQueuedListingPort(Protocol):
    """Public owner-provided queued listing over the real masked journal.

    Precise hook for the store owner (no duplicate queue factory, no private
    scan in this seam):

    - Method name: ``list_queued_calculations``; keyword-only params
      ``organization_id: str``, ``limit: int`` (1..50), ``now: datetime``.
    - Returns up to ``limit`` ``MaskedCalculationPendingItemV1``, oldest
      first, for calculations the caller org owns that a worker may take:
      ``QUEUED``, plus ``RUNNING`` only when the active lease has expired
      and generations remain under the sealed envelope's retry cap.
    - Each item must be backed by a fresh masked witness at ``now`` (source,
      mask, area, policy, runtime, activation current); stale or
      foreign records are omitted, never listed.  ``COMPLETED`` / ``FAILED``
      / ``CANCELED`` / deadline-passed records are never listed.
    - No unbounded private scan: the implementation must bound its journal
      walk (e.g. stop after the first ``limit`` eligible plus a small
      constant rejection budget) and must not replay the whole journal per
      call.
    """

    def list_queued_calculations(
        self, *, organization_id: str, limit: int, now: datetime
    ) -> tuple[Any, ...]: ...


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
                    raise HTTPException(status_code=413, detail="MASKED_REQUEST_TOO_LARGE")
                payload.extend(chunk)
        return model.model_validate(
            json.loads(
                payload,
                object_pairs_hook=_reject_duplicates,
                parse_constant=_reject_constant,
            )
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail="MASKED_REQUEST_TIMED_OUT") from exc
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(status_code=422, detail="MASKED_REQUEST_INVALID") from exc


def masked_operator_scope_allows(principal: Principal, site_id: str, work_area_id: str) -> bool:
    """Pure operator allowlist check: both site and area when granted."""
    if principal.kind is not PrincipalKind.OPERATOR:
        return False
    if principal.allowed_site_ids is not None and site_id not in principal.allowed_site_ids:
        return False
    return not (
        principal.allowed_work_area_ids is not None
        and work_area_id not in principal.allowed_work_area_ids
    )


def build_external_masked_calculation_router(
    *,
    calculations: ExternalMaskedCalculationStore,
    evidence: MaskedEvidencePort,
    mask_bytes: MaskedBytePort,
    resource_envelope: ResourceEnvelopeV1,
    designated_worker: Principal,
    dsm_byte_reader: MaskedDsmByteReader | None = None,
    queued: MaskedQueuedListingPort | None = None,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    """Build the closed V3 execution HTTP seam over the genuine Core stores."""
    if not isinstance(calculations, ExternalMaskedCalculationStore):
        raise ValueError("masked router requires the concrete Core calculation store")
    if not callable(getattr(evidence, "bind_identity", None)):
        raise ValueError("masked router requires the genuine masked-evidence adapter")
    if not (
        callable(getattr(mask_bytes, "fetch_manifest", None))
        and callable(getattr(mask_bytes, "read_slice", None))
    ):
        raise ValueError("masked router requires the sealed mask byte port")
    if queued is not None and not callable(getattr(queued, "list_queued_calculations", None)):
        raise ValueError("masked queued listing must expose list_queued_calculations")
    envelope = ResourceEnvelopeV1.model_validate(resource_envelope.model_dump())
    if envelope.resource_envelope_digest != envelope.canonical_digest():
        raise ValueError("masked router requires a sealed resource envelope")
    if (
        designated_worker.kind is not PrincipalKind.ANALYSIS_WORKER
        or not designated_worker.organization_id
    ):
        raise ValueError("masked router requires the designated organization worker")
    if dsm_byte_reader is not None and not callable(getattr(dsm_byte_reader, "read_slice", None)):
        raise ValueError("masked DSM reader must expose read_slice")
    now = clock or (lambda: datetime.now(UTC))
    router = APIRouter(tags=["external-masked-calculation"])
    write = require_permission(Permission.SITES_WRITE)
    read = require_permission(Permission.SITES_READ)
    work = require_permission(Permission.ANALYSIS_WORK)

    def require_operator(principal: Principal) -> None:
        if principal.kind is not PrincipalKind.OPERATOR:
            raise HTTPException(status_code=403, detail="MASKED_OPERATOR_REQUIRED")

    def require_operator_scope(principal: Principal, site_id: str, work_area_id: str) -> None:
        """Optional operator allowlists bind both site and area before mutation.

        A scoped operator outside its grants sees uniform 404 (never a
        foreign record); legacy unscoped operators pass.  MCP identities never
        reach here (they lack site permissions).
        """
        if not masked_operator_scope_allows(principal, site_id, work_area_id):
            raise HTTPException(status_code=404, detail="MASKED_CALCULATION_NOT_FOUND")

    def require_designated_worker(principal: Principal) -> None:
        if principal.kind is not PrincipalKind.ANALYSIS_WORKER:
            raise HTTPException(status_code=403, detail="MASKED_WORKER_REQUIRED")
        if (
            principal.principal_id != designated_worker.principal_id
            or principal.organization_id != designated_worker.organization_id
        ):
            raise HTTPException(status_code=403, detail="MASKED_WORKER_MISMATCH")

    def detail_of(view: Any) -> MaskedCalculationDetailViewV1:
        record = view.record
        return MaskedCalculationDetailViewV1(
            request_id=record.request_id,
            organization_id=record.organization_id,
            site_id=record.admission.site_id,
            work_area_id=record.admission.work_area_id,
            masked_calculation_identity_digest=record.masked_calculation_identity_digest,
            status=record.status.value,
            disposition=view.disposition.value,
            admission=view.consulted_admission,
            report=view.report,
        )

    @router.post(
        "/v3/sites/{site_id}/work-areas/{work_area_id}/masked-calculations",
        response_model=MaskedCalculationCreatedViewV1,
        openapi_extra=_json_body(MaskedCalculationCreateRequestV1),
    )
    async def create_calculation(
        site_id: str,
        work_area_id: str,
        request: Request,
        principal: Principal = Depends(write),  # noqa: B008
    ) -> MaskedCalculationCreatedViewV1:
        require_operator(principal)
        require_operator_scope(principal, site_id, work_area_id)
        body = await _bounded_json(request, MaskedCalculationCreateRequestV1)
        checked_at = now()
        try:
            identity = await run_in_threadpool(
                evidence.bind_identity,
                calculations=calculations,
                principal=principal,
                organization_id=principal.organization_id,
                site_id=site_id,
                work_area_id=work_area_id,
                mask_child_id=body.mask_child_id,
                masked_calculation_id=body.masked_calculation_id,
                source_calculation_identity_digest=body.source_calculation_identity_digest,
                now=checked_at,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="MASKED_SCOPE_DENIED") from exc
        except (ValueError, RuntimeError) as exc:
            # Unknown, foreign, or revoked source/mask: uniform non-disclosing
            # 404; nothing is mutated by a failed bind.
            raise HTTPException(status_code=404, detail="MASKED_SOURCE_NOT_FOUND") from exc
        if (
            identity.organization_id != principal.organization_id
            or identity.site_id != site_id
            or identity.work_area_id != work_area_id
        ):
            raise HTTPException(status_code=404, detail="MASKED_SOURCE_NOT_FOUND")
        try:
            record = await run_in_threadpool(
                calculations.issue,
                principal=principal,
                request_id=body.request_id,
                masked_calculation_identity_digest=identity.canonical_digest(),
                idempotency_key=body.idempotency_key,
                now=checked_at,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="MASKED_SCOPE_DENIED") from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail="MASKED_ADMISSION_UNAVAILABLE") from exc
        return MaskedCalculationCreatedViewV1(
            request_id=record.request_id,
            masked_calculation_identity_digest=record.masked_calculation_identity_digest,
            status=record.status.value,
            admission=record.admission,
        )

    @router.get(
        "/v3/sites/{site_id}/work-areas/{work_area_id}/masked-calculations/{request_id}",
        response_model=MaskedCalculationDetailViewV1,
    )
    def read_calculation(
        site_id: str,
        work_area_id: str,
        request_id: str,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> MaskedCalculationDetailViewV1:
        require_operator(principal)
        require_operator_scope(principal, site_id, work_area_id)
        try:
            view = calculations.get_current(request_id=request_id, principal=principal, now=now())
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="MASKED_SCOPE_DENIED") from exc
        if view is None:
            raise HTTPException(status_code=404, detail="MASKED_CALCULATION_NOT_FOUND")
        detail = detail_of(view)
        if detail.site_id != site_id or detail.work_area_id != work_area_id:
            raise HTTPException(status_code=404, detail="MASKED_CALCULATION_NOT_FOUND")
        return detail

    @router.get(
        "/v3/sites/{site_id}/work-areas/{work_area_id}/masked-calculations/{request_id}/failure",
        response_model=MaskedVolumeCalculationFailureV3,
    )
    def read_calculation_failure(
        site_id: str,
        work_area_id: str,
        request_id: str,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> MaskedVolumeCalculationFailureV3:
        """Return the sealed V3 numeric failure, if the worker recorded one.

        Read-only: creates no record.  A completed or never-failed request
        answers uniform 404.
        """
        require_operator(principal)
        require_operator_scope(principal, site_id, work_area_id)
        try:
            record = calculations.get_history_for_principal(request_id, principal=principal)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="MASKED_SCOPE_DENIED") from exc
        if record is None or record.failure is None:
            raise HTTPException(status_code=404, detail="MASKED_CALCULATION_NOT_FOUND")
        if record.admission.site_id != site_id or record.admission.work_area_id != work_area_id:
            raise HTTPException(status_code=404, detail="MASKED_CALCULATION_NOT_FOUND")
        return record.failure

    @router.post(
        "/v3/sites/{site_id}/work-areas/{work_area_id}/masked-calculations/{request_id}/cancel",
        response_model=MaskedCalculationMutationViewV1,
    )
    def cancel_calculation(
        site_id: str,
        work_area_id: str,
        request_id: str,
        principal: Principal = Depends(write),  # noqa: B008
    ) -> MaskedCalculationMutationViewV1:
        require_operator(principal)
        require_operator_scope(principal, site_id, work_area_id)
        record = calculations.get_history(request_id, organization_id=principal.organization_id)
        if record is None:
            raise HTTPException(status_code=404, detail="MASKED_CALCULATION_NOT_FOUND")
        if record.admission.site_id != site_id or record.admission.work_area_id != work_area_id:
            raise HTTPException(status_code=404, detail="MASKED_CALCULATION_NOT_FOUND")
        try:
            settled = calculations.cancel(principal=principal, request_id=request_id, now=now())
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="MASKED_SCOPE_DENIED") from exc
        if settled is None:
            raise HTTPException(status_code=404, detail="MASKED_CALCULATION_NOT_FOUND")
        return MaskedCalculationMutationViewV1(
            request_id=settled.request_id,
            status=settled.status.value,
            attempt=settled.active_attempt,
        )

    @router.get(
        "/v1/internal/masked-calculations/pending",
        response_model=MaskedCalculationPendingListV1,
    )
    def pending_calculations(
        limit: int = Query(default=50, ge=1, le=50),
        principal: Principal = Depends(work),  # noqa: B008
    ) -> MaskedCalculationPendingListV1:
        """Bounded worker-only discovery of takeable V3 calculations.

        Served by the owner-provided queued listing over the real masked
        journal (fresh witness per item, bounded walk).  Until the store
        owner adds ``list_queued_calculations``, this answers 503 with the
        precise hook requirement instead of inventing a duplicate queue.
        """
        require_designated_worker(principal)
        if queued is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "MASKED_DISCOVERY_UNAVAILABLE: the masked store owner must add "
                    "list_queued_calculations(organization_id, limit, now) with a "
                    "fresh masked witness per item and a bounded journal walk; "
                    "see MaskedQueuedListingPort"
                ),
            )
        raw_items = queued.list_queued_calculations(
            organization_id=principal.organization_id, limit=limit, now=now()
        )
        # Owner port is org-scoped by design; narrow worker grants filter here
        # so a designated worker never sees foreign site/area queue metadata.
        # The worker pin is not an OPERATOR scope, so the check is inline.
        items: list[MaskedCalculationPendingItemV1] = []
        for raw in raw_items:
            item = MaskedCalculationPendingItemV1.model_validate(
                raw.model_dump(by_alias=True) if hasattr(raw, "model_dump") else raw
            )
            record = calculations.get_history(
                item.request_id, organization_id=principal.organization_id
            )
            if record is None:
                continue
            if (
                principal.allowed_site_ids is not None
                and record.admission.site_id not in principal.allowed_site_ids
            ):
                continue
            if (
                principal.allowed_work_area_ids is not None
                and record.admission.work_area_id not in principal.allowed_work_area_ids
            ):
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return MaskedCalculationPendingListV1(items=tuple(items))

    def active_for(
        principal: Principal, request_id: str, attempt_digest: str | None, instance: str | None
    ) -> Any:
        if not attempt_digest or not instance:
            raise HTTPException(status_code=409, detail="MASKED_INPUT_FENCE_REQUIRED")
        record = calculations.get_history(request_id, organization_id=principal.organization_id)
        if record is None:
            raise HTTPException(status_code=404, detail="MASKED_JOB_NOT_FOUND")
        attempt = record.active_attempt
        if (
            attempt is None
            or attempt.execution_attempt_digest != attempt_digest
            or attempt.worker_instance_id != instance
        ):
            raise HTTPException(status_code=409, detail="MASKED_INPUT_FENCE_REJECTED")
        return attempt

    @router.post(
        "/v1/internal/masked-calculations/{request_id}:lease",
        response_model=MaskedCalculationMutationViewV1,
        openapi_extra=_json_body(MaskedLeaseRequestV1),
    )
    async def lease_job(
        request_id: str,
        request: Request,
        principal: Principal = Depends(work),  # noqa: B008
    ) -> MaskedCalculationMutationViewV1:
        require_designated_worker(principal)
        body = await _bounded_json(request, MaskedLeaseRequestV1)
        attempt = await run_in_threadpool(
            calculations.acquire_lease,
            request_id=request_id,
            worker_principal=principal,
            worker_instance_id=body.worker_instance_id,
            lease_acquisition_id=body.lease_acquisition_id,
            now=now(),
        )
        if attempt is None:
            raise HTTPException(status_code=409, detail="MASKED_LEASE_UNAVAILABLE")
        return MaskedCalculationMutationViewV1(
            request_id=request_id,
            status=MaskedExecutionStatusV3.RUNNING.value,
            attempt=attempt,
        )

    @router.post(
        "/v1/internal/masked-calculations/{request_id}:renew",
        response_model=MaskedCalculationMutationViewV1,
        openapi_extra=_json_body(MaskedRenewRequestV1),
    )
    async def renew_job(
        request_id: str,
        request: Request,
        principal: Principal = Depends(work),  # noqa: B008
    ) -> MaskedCalculationMutationViewV1:
        require_designated_worker(principal)
        body = await _bounded_json(request, MaskedRenewRequestV1)
        attempt = await run_in_threadpool(
            calculations.renew_lease,
            request_id=request_id,
            worker_principal=principal,
            attempt=body.attempt,
            now=now(),
        )
        if attempt is None:
            raise HTTPException(status_code=409, detail="MASKED_LEASE_RENEWAL_REJECTED")
        return MaskedCalculationMutationViewV1(
            request_id=request_id,
            status=MaskedExecutionStatusV3.RUNNING.value,
            attempt=attempt,
        )

    @router.get(
        "/v1/internal/masked-calculations/{request_id}/input",
    )
    def job_input(
        request_id: str,
        attempt_digest: str | None = Header(default=None, alias=MASKED_ATTEMPT_DIGEST_HEADER),
        worker_instance_id: str | None = Header(
            default=None, alias=MASKED_WORKER_INSTANCE_ID_HEADER
        ),
        principal: Principal = Depends(work),  # noqa: B008
    ) -> dict[str, Any]:
        require_designated_worker(principal)
        checked_at = now()
        attempt = active_for(principal, request_id, attempt_digest, worker_instance_id)
        worker_input = calculations.input_for_worker(
            request_id=request_id,
            worker_principal=principal,
            attempt=attempt,
            now=checked_at,
        )
        if worker_input is None:
            raise HTTPException(status_code=409, detail="MASKED_INPUT_FENCE_REJECTED")
        return MaskedWorkerInputV3.model_validate(
            worker_input.model_dump(by_alias=True)
        ).model_dump(by_alias=True, mode="json")

    @router.get(
        "/v1/internal/masked-calculations/{request_id}/inputs/{role}/bytes",
        response_model=MaskedBytesSliceViewV1,
    )
    def job_input_bytes(
        request_id: str,
        role: str,
        offset: int = Query(ge=0),
        length: int = Query(gt=0, le=_MAX_SLICE),
        attempt_digest: str | None = Header(default=None, alias=MASKED_ATTEMPT_DIGEST_HEADER),
        worker_instance_id: str | None = Header(
            default=None, alias=MASKED_WORKER_INSTANCE_ID_HEADER
        ),
        principal: Principal = Depends(work),  # noqa: B008
    ) -> MaskedBytesSliceViewV1:
        require_designated_worker(principal)
        if role not in ("BASELINE_DSM", "CURRENT_DSM", "EXCLUSION_MASK"):
            raise HTTPException(status_code=404, detail="MASKED_INPUT_ROLE_NOT_FOUND")
        checked_at = now()
        attempt = active_for(principal, request_id, attempt_digest, worker_instance_id)
        # Re-verify the live fence on every byte window: a completed or
        # stale attempt never authorizes raw bytes (no borrowing).
        worker_input = calculations.input_for_worker(
            request_id=request_id,
            worker_principal=principal,
            attempt=attempt,
            now=checked_at,
        )
        if worker_input is None:
            raise HTTPException(status_code=409, detail="MASKED_INPUT_FENCE_REJECTED")
        capability = next(item for item in worker_input.inputs if item.role == role)
        if capability.expires_at > attempt.lease_expires_at:
            raise HTTPException(status_code=409, detail="MASKED_INPUT_FENCE_REJECTED")
        try:
            if role == "EXCLUSION_MASK":
                # The fenced worker input carries the Core-bound mask
                # capability (artifact+SHA+size).  The port resolves the
                # unique sealed child for that exact binding itself and
                # re-verifies the sealed byte proof: no caller child id is
                # trusted here.
                window = mask_bytes.read_slice_by_binding(
                    organization_id=principal.organization_id,
                    mask_artifact_id=capability.artifact_id,
                    observed_sha256=capability.observed_sha256,
                    observed_size_bytes=capability.observed_size_bytes,
                    offset=offset,
                    length=length,
                )
                artifact_id = capability.artifact_id
            else:
                if dsm_byte_reader is None:
                    raise HTTPException(status_code=409, detail="MASKED_DSM_BYTES_UNAVAILABLE")
                dsm_window = dsm_byte_reader.read_slice(
                    organization_id=principal.organization_id,
                    site_id=worker_input.masked_calculation_identity.site_id,
                    artifact_id=capability.artifact_id,
                    observed_sha256=capability.observed_sha256,
                    observed_size_bytes=capability.observed_size_bytes,
                    offset=offset,
                    length=length,
                )
                if dsm_window is None:
                    raise HTTPException(status_code=404, detail="MASKED_SEALED_BYTES_NOT_FOUND")
                window = dsm_window
                artifact_id = capability.artifact_id
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="MASKED_SEALED_BYTES_NOT_FOUND") from exc
        if len(window) != length:
            raise HTTPException(status_code=404, detail="MASKED_SEALED_BYTES_NOT_FOUND")
        # Final fresh fence guard: no window leaves Core on an expired lease.
        # The window itself stays genuine sealed bytes either way.
        if (
            calculations.input_for_worker(
                request_id=request_id,
                worker_principal=principal,
                attempt=attempt,
                now=now(),
            )
            is None
        ):
            raise HTTPException(status_code=409, detail="MASKED_INPUT_FENCE_REJECTED")
        return MaskedBytesSliceViewV1(
            artifact_id=artifact_id,
            offset=offset,
            content_base64=base64.b64encode(window).decode("ascii"),
        )

    @router.post(
        "/v1/internal/masked-calculations/{request_id}:report",
        response_model=MaskedCalculationMutationViewV1,
        openapi_extra=_json_body(MaskedReportRequestV1),
    )
    async def report_job(
        request_id: str,
        request: Request,
        principal: Principal = Depends(work),  # noqa: B008
    ) -> MaskedCalculationMutationViewV1:
        require_designated_worker(principal)
        body = await _bounded_json(request, MaskedReportRequestV1)
        record = await run_in_threadpool(
            calculations.record_report,
            request_id=request_id,
            worker_principal=principal,
            report=body.report,
            attempt=body.attempt,
            now=now(),
        )
        if record is None:
            raise HTTPException(status_code=409, detail="MASKED_REPORT_FENCE_REJECTED")
        return MaskedCalculationMutationViewV1(
            request_id=record.request_id,
            status=record.status.value,
            attempt=record.active_attempt,
        )

    @router.post(
        "/v1/internal/masked-calculations/{request_id}:failure",
        response_model=MaskedCalculationMutationViewV1,
        openapi_extra=_json_body(MaskedFailureRequestV1),
    )
    async def fail_job(
        request_id: str,
        request: Request,
        principal: Principal = Depends(work),  # noqa: B008
    ) -> MaskedCalculationMutationViewV1:
        require_designated_worker(principal)
        body = await _bounded_json(request, MaskedFailureRequestV1)
        record = await run_in_threadpool(
            calculations.record_failure,
            request_id=request_id,
            worker_principal=principal,
            failure=body.failure,
            attempt=body.attempt,
            now=now(),
        )
        if record is None:
            raise HTTPException(status_code=409, detail="MASKED_FAILURE_FENCE_REJECTED")
        return MaskedCalculationMutationViewV1(
            request_id=record.request_id,
            status=record.status.value,
            attempt=record.active_attempt,
        )

    return router


__all__ = [
    "MaskedBytePort",
    "MaskedDsmByteReader",
    "MaskedEvidencePort",
    "MaskedQueuedListingPort",
    "build_external_masked_calculation_router",
    "masked_operator_scope_allows",
]
