"""AI-only grant-filtered asset discovery routes; no generic catalog widening.

Only ``SPATIAL_DATA_MCP_CLIENT`` may enumerate: any other authenticated
identity receives a typed refusal. Every successful response carries the AI
egress acknowledgment only after the send-time recheck in the guarded
metadata response.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from ksi_event_contracts.spatial_data_ai import (
    SpatialDataAiErrorV1,
    SpatialDataAssetPageV1,
    SpatialDataAssetViewV1,
)
from starlette.responses import Response

from ksi_core.domains.external.delivery.ai_egress import SpatialDataAiEgress
from ksi_core.domains.external.delivery.api import error_response, request_credentials
from ksi_core.domains.external.delivery.asset_discovery import SpatialDataAssetDiscovery
from ksi_core.domains.external.delivery.errors import (
    SpatialDataAiDomainError,
    SpatialDataDomainError,
)
from ksi_core.domains.external.delivery.metadata_response import ai_error_response
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, require_permission

ASSET_BASE = "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-assets"


def build_spatial_data_asset_router(
    *,
    discovery: SpatialDataAssetDiscovery,
    egress: SpatialDataAiEgress,
    clock: Callable[[], datetime],
) -> APIRouter:
    """Mount the two scoped AI discovery GETs over bound Core participants.

    Refuses mismatched discovery/egress pairs at build time; a missing graph
    mounts nothing because the caller has no participants to pass.
    """
    if not isinstance(discovery, SpatialDataAssetDiscovery) or not isinstance(
        egress, SpatialDataAiEgress
    ):
        raise ValueError("asset routes require genuine discovery and egress participants")
    if egress.discovery is not discovery:
        raise ValueError("asset routes require the bound discovery/egress participants")
    if not egress.uses_exact_participants(
        jobs=discovery.jobs,
        sources=discovery.sources,
        grants=discovery.grants,
        audit=egress.audit,
    ):
        raise ValueError("asset egress must bind the same mounted Core participants")
    if not callable(clock):
        raise ValueError("asset routes require a clock")
    router = APIRouter(
        tags=["spatial-data"],
        responses={
            code: {"model": SpatialDataAiErrorV1, "description": "Typed safe AI refusal"}
            for code in (403, 404, 409, 422, 503)
        },
    )

    @router.get(ASSET_BASE, response_model=SpatialDataAssetPageV1)
    def list_assets(
        site_id: str,
        work_area_id: str,
        request: Request,
        cursor: str | None = None,
        limit: int = 1,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_READ)),  # noqa: B008
    ) -> Response:
        if principal.kind is not PrincipalKind.SPATIAL_DATA_MCP_CLIENT:
            return error_response(SpatialDataDomainError("PERMISSION_DENIED", 403))
        try:
            page = discovery.list(
                site_id=site_id,
                work_area_id=work_area_id,
                principal=principal,
                limit=limit,
                cursor=cursor,
                now=clock(),
            )
            return egress.prepare_asset_page_response(
                credentials=request_credentials(request, principal),
                site_id=site_id,
                work_area_id=work_area_id,
                page=page,
                cursor=cursor,
                limit=limit,
            )
        except (SpatialDataDomainError, SpatialDataAiDomainError) as exc:
            return ai_error_response(exc)
        except HTTPException as exc:
            return ai_error_response(exc)

    @router.get(ASSET_BASE + "/{asset_ref}", response_model=SpatialDataAssetViewV1)
    def get_asset(
        site_id: str,
        work_area_id: str,
        asset_ref: str,
        request: Request,
        principal: Principal = Depends(require_permission(Permission.SPATIAL_DATA_READ)),  # noqa: B008
    ) -> Response:
        if principal.kind is not PrincipalKind.SPATIAL_DATA_MCP_CLIENT:
            return error_response(SpatialDataDomainError("PERMISSION_DENIED", 403))
        try:
            view = discovery.get(
                site_id=site_id,
                work_area_id=work_area_id,
                asset_ref=asset_ref,
                principal=principal,
                now=clock(),
            )
            return egress.prepare_asset_response(
                credentials=request_credentials(request, principal),
                site_id=site_id,
                work_area_id=work_area_id,
                view=view,
            )
        except (SpatialDataDomainError, SpatialDataAiDomainError) as exc:
            return ai_error_response(exc)
        except HTTPException as exc:
            return ai_error_response(exc)

    return router
