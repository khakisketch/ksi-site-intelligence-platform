"""Authenticated Core API for acquisition profile, gateway heartbeat, and readiness."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from ksi_core.acquisition.models import (
    AcquisitionDeploymentProfileV1,
    AcquisitionReadinessView,
    ConnectivitySnapshotV1,
)
from ksi_core.acquisition.store import AcquisitionConnectivityStore
from ksi_core.api_base import JOURNAL_SEALED_DETAIL
from ksi_core.auth import Permission, Principal, PrincipalKind, require_permission
from ksi_core.durable_journal import JournalSealedError

if TYPE_CHECKING:
    from fastapi import FastAPI


def _store_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, JournalSealedError):
        return HTTPException(
            status_code=503,
            detail=JOURNAL_SEALED_DETAIL,
            headers={"Retry-After": "30"},
        )
    return HTTPException(status_code=422, detail=str(exc))


def build_acquisition_connectivity_router(store: AcquisitionConnectivityStore) -> APIRouter:
    router = APIRouter(tags=["acquisition-connectivity"])

    @router.put(
        "/v1/sites/{site_id}/acquisition-profile",
        response_model=AcquisitionDeploymentProfileV1,
    )
    def put_profile(
        site_id: str,
        request: AcquisitionDeploymentProfileV1,
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> AcquisitionDeploymentProfileV1:
        if request.site_id != site_id:
            raise HTTPException(status_code=422, detail="path site_id와 body siteId가 다르다")
        try:
            return store.upsert_profile(
                request,
                organization_id=principal.organization_id,
                actor=principal.principal_id,
                now=datetime.now(UTC),
            )
        except (JournalSealedError, LookupError, ValueError) as exc:
            raise _store_error(exc) from exc

    @router.get(
        "/v1/sites/{site_id}/acquisition-profile",
        response_model=AcquisitionDeploymentProfileV1,
    )
    def get_profile(
        site_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> AcquisitionDeploymentProfileV1:
        profile = store.get_profile(site_id, organization_id=principal.organization_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="현장 acquisition profile을 찾을 수 없다")
        return profile

    @router.post(
        "/v1/gateway-sync/heartbeats",
        response_model=ConnectivitySnapshotV1,
        status_code=201,
    )
    def observe_gateway(
        request: ConnectivitySnapshotV1,
        principal: Principal = Depends(require_permission(Permission.GATEWAY_CONNECTIVITY_WRITE)),  # noqa: B008,E501
    ) -> ConnectivitySnapshotV1:
        if principal.kind is not PrincipalKind.GATEWAY_DEVICE:
            raise HTTPException(status_code=403, detail="Gateway device 신원만 보고할 수 있다")
        if principal.device_id != request.gateway_device_id:
            raise HTTPException(status_code=404, detail="acquisition profile을 찾을 수 없다")
        try:
            return store.observe(
                request,
                organization_id=principal.organization_id,
                actor=principal.principal_id,
                now=datetime.now(UTC),
            )
        except (JournalSealedError, LookupError, ValueError) as exc:
            raise _store_error(exc) from exc

    @router.get(
        "/v1/sites/{site_id}/acquisition-readiness",
        response_model=AcquisitionReadinessView,
    )
    def get_readiness(
        site_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> AcquisitionReadinessView:
        return store.readiness(
            site_id,
            organization_id=principal.organization_id,
            now=datetime.now(UTC),
        )

    return router


def mount_acquisition_connectivity(app: FastAPI, store: AcquisitionConnectivityStore) -> None:
    app.state.acquisition_connectivity_store = store
    app.include_router(build_acquisition_connectivity_router(store))


__all__ = ["build_acquisition_connectivity_router", "mount_acquisition_connectivity"]
