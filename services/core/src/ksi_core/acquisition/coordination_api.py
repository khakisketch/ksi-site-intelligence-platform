"""Authenticated AcquisitionRun progress and Gateway operation receipt API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_event_contracts.observation_work_order import ObservationWorkOrderStatus

from ksi_core.acquisition.coordination import (
    AcquisitionCoordinationConflictError,
    AcquisitionCoordinationStore,
    AcquisitionProgressProjector,
)
from ksi_core.acquisition.models import (
    AcquisitionProgressView,
    GatewayOperationReceiptRequest,
    GatewayOperationReceiptV1,
)
from ksi_core.acquisition.store import AcquisitionConnectivityStore
from ksi_core.api_base import JOURNAL_SEALED_DETAIL
from ksi_core.auth import Permission, Principal, PrincipalKind, require_permission
from ksi_core.durable_journal import JournalSealedError
from ksi_core.mission_records import MissionStore
from ksi_core.observation_work_orders import (
    ExternalReobservationExecutionDenied,
    ObservationWorkOrderStore,
)

if TYPE_CHECKING:
    from fastapi import FastAPI


def _coordination_error(exc: Exception) -> HTTPException:
    if isinstance(exc, JournalSealedError):
        return HTTPException(
            status_code=503,
            detail=JOURNAL_SEALED_DETAIL,
            headers={"Retry-After": "30"},
        )
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AcquisitionCoordinationConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ExternalReobservationExecutionDenied):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


_GATEWAY_RECEIPT_PERMISSION = require_permission(Permission.GATEWAY_CONNECTIVITY_WRITE)


def build_acquisition_coordination_router(
    *,
    coordination_store: AcquisitionCoordinationStore,
    connectivity_store: AcquisitionConnectivityStore,
    work_order_store: ObservationWorkOrderStore,
    mission_store: MissionStore,
    projector: AcquisitionProgressProjector,
) -> APIRouter:
    router = APIRouter(tags=["acquisition-coordination"])

    @router.get(
        "/v1/observation-work-orders/{work_order_id}/acquisition-progress",
        response_model=AcquisitionProgressView,
    )
    def get_acquisition_progress(
        work_order_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> AcquisitionProgressView:
        work_order = work_order_store.get(work_order_id, organization_id=principal.organization_id)
        if work_order is None:
            raise HTTPException(status_code=404, detail="관측 작업을 찾을 수 없다")
        now = datetime.now(UTC)
        # Approval remains authoritative even if this append fails. The GET is a
        # reconciliation point, so a transient coordinator failure can recover
        # without asking a person to approve the WorkOrder again.
        if work_order.status not in {
            ObservationWorkOrderStatus.AWAITING_APPROVAL,
            ObservationWorkOrderStatus.CANCELLED,
        }:
            try:
                coordination_store.ensure_run(
                    work_order,
                    actor=principal.principal_id,
                    now=now,
                )
            except (ExternalReobservationExecutionDenied, JournalSealedError, ValueError) as exc:
                raise _coordination_error(exc) from exc
        return projector.project(work_order, now=now)

    @router.post(
        "/v1/gateway-sync/operation-receipts",
        response_model=GatewayOperationReceiptV1,
        status_code=201,
    )
    def record_operation_receipt(
        request: GatewayOperationReceiptRequest,
        response: Response,
        principal: Principal = Depends(_GATEWAY_RECEIPT_PERMISSION),  # noqa: B008
    ) -> GatewayOperationReceiptV1:
        if principal.kind is not PrincipalKind.GATEWAY_DEVICE or principal.device_id is None:
            raise HTTPException(status_code=403, detail="Gateway device 신원만 보고할 수 있다")
        profile = connectivity_store.get_profile(
            request.site_id, organization_id=principal.organization_id
        )
        if profile is None or profile.gateway_device_id != principal.device_id:
            # Device/site binding mismatch is folded into 404 to avoid a site and
            # mission existence oracle for a compromised Gateway credential.
            raise HTTPException(status_code=404, detail="acquisition profile을 찾을 수 없다")
        if request.transport not in profile.gateway_transports:
            raise HTTPException(
                status_code=422,
                detail="operation receipt transport가 Site profile에 허용되지 않았다",
            )
        mission = mission_store.get(request.mission_id)
        run = coordination_store.run_for_mission(
            request.mission_id, organization_id=principal.organization_id
        )
        if (
            mission is None
            or mission.site_id != request.site_id
            or run is None
            or run.site_id != request.site_id
        ):
            raise HTTPException(status_code=404, detail="AcquisitionRun Mission을 찾을 수 없다")
        try:
            receipt, created = coordination_store.record_receipt(
                request,
                organization_id=principal.organization_id,
                gateway_device_id=principal.device_id,
                actor=principal.principal_id,
                now=datetime.now(UTC),
            )
        except (JournalSealedError, LookupError, ValueError) as exc:
            raise _coordination_error(exc) from exc
        if not created:
            response.status_code = 200
        return receipt

    return router


def mount_acquisition_coordination(
    app: FastAPI,
    *,
    coordination_store: AcquisitionCoordinationStore,
    connectivity_store: AcquisitionConnectivityStore,
    work_order_store: ObservationWorkOrderStore,
    mission_store: MissionStore,
    projector: AcquisitionProgressProjector,
) -> None:
    app.state.acquisition_coordination_store = coordination_store
    app.include_router(
        build_acquisition_coordination_router(
            coordination_store=coordination_store,
            connectivity_store=connectivity_store,
            work_order_store=work_order_store,
            mission_store=mission_store,
            projector=projector,
        )
    )


__all__ = ["build_acquisition_coordination_router", "mount_acquisition_coordination"]
