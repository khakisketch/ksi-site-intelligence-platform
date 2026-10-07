"""Explicit external-only platform Core app factory (platform Core assembly plan, Task 2).

Consumes the completed :class:`PlatformGraph` and calls the existing route
builders — no second domain computation or permission implementation. Mount
order mirrors the legacy factory (identity/auth → sites/areas/work → external)
minus every surface this profile does not own: no managed processing, raw
source, Mission/flight/Edge, device/capability, Copilot or plan compiler
routes, and no ``/capabilities`` catalog projection.

Process runtime surfaces (``/ready``, ``/metrics``, middleware) are mounted by
``assemble_platform_app`` after this factory returns — the same split the
legacy assembly uses, because only the assembly owns the ``opened`` list the
readiness surface reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from ksi_core.api_base import mount_validation_error_handler
from ksi_core.auth import HumanAuthMode
from ksi_core.composition.platform_graph import PlatformGraph

if TYPE_CHECKING:
    from ksi_core.auth import AuthRegistry, OidcVerifier


def create_platform_app(
    *,
    graph: PlatformGraph,
    auth_registry: AuthRegistry | None = None,
    human_auth_mode: HumanAuthMode = HumanAuthMode.OPAQUE,
    oidc_verifier: OidcVerifier | None = None,
    expose_docs: bool = False,
) -> FastAPI:
    """Mount the external-only surface over an already-built platform graph."""
    if auth_registry is None:
        raise ValueError(
            "platform Core mounts no unauthenticated protected surface — auth_registry is required"
        )
    app = FastAPI(
        title="KSI Core",
        version="0.0.1",
        summary="KSI Site Intelligence Core — 외부 등록·조회·운영 전용 (비행·관리형 없음)",
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
    )
    mount_validation_error_handler(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        """liveness — 의존 서비스 상태를 확인하지 않는 순수 프로세스 생존 신호."""
        return {"status": "ok"}

    from ksi_core.auth import mount_auth

    mount_auth(
        app,
        auth_registry,
        human_auth_mode=human_auth_mode,
        oidc_verifier=oidc_verifier,
    )

    from ksi_core.sites import mount_sites

    mount_sites(app, graph.sites, None)

    from ksi_core.work_areas import mount_work_areas

    mount_work_areas(app, graph.work_areas, site_store=graph.sites)

    from ksi_core.domains.sites.observation_work_orders import (
        build_observation_work_order_router,
    )

    app.state.observation_work_order_store = graph.work_orders
    app.include_router(build_observation_work_order_router(graph.work_orders, external_only=True))

    from ksi_core.organization_work_roster import build_organization_work_roster_router

    app.include_router(build_organization_work_roster_router(graph.roster))
    app.state.organization_work_roster_store = graph.roster

    from ksi_core.work_inbox import build_work_inbox_router

    single_report_resolver = (
        graph.external.single_volume.store if graph.external.single_volume is not None else None
    )
    if not graph.inbox.uses_exact_dependencies(
        work_orders=graph.work_orders,
        roster=graph.roster,
        report_resolver=graph.external.relative_volume_store,
        single_report_resolver=single_report_resolver,
    ):
        raise ValueError(
            "work inbox must use the mounted durable roster, WorkOrder and report graph"
        )
    app.include_router(build_work_inbox_router(graph.inbox))
    app.state.work_inbox_store = graph.inbox

    from ksi_core.composition.routes.external import mount_external_routes

    mount_external_routes(
        app,
        external_result_read_projector=graph.workflow.result_read_projector,
        external_result_workflow_service=graph.workflow.result_workflow_service,
        observation_work_order_store=graph.work_orders,
        site_store=graph.sites,
        work_area_store=graph.work_areas,
        external_relative_volume_store=graph.external.relative_volume_store,
        site_workspace_projector=None,
        external_reconstruction_store=graph.external.reconstruction_store,
        evidence_storage=graph.storage,
        external_evidence_store=graph.external.evidence_store,
        external_evidence_validation_store=graph.external.evidence_validation_store,
        external_volume_input_capability_issuer=(graph.external.volume_input_capability_issuer),
        external_volume_execution_activator=graph.external.volume_execution_activator,
        external_single_volume=graph.external.single_volume,
        external_use_evaluator=graph.external.use_evaluator,
        spatial_data=graph.data,
        external_artifact_inspection_store=graph.external.artifact_inspection_store,
        external_display_artifact_store=graph.external.display_artifact_store,
        external_analysis_wiring=graph.analysis,
    )
    return app


__all__ = ["create_platform_app"]
