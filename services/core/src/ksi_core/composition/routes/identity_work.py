"""Identity and work-entry route mounting, kept in app-factory order."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def mount_identity_work_routes(
    app: FastAPI,
    *,
    auth_registry: Any,
    human_auth_mode: Any,
    oidc_verifier: Any,
    runtime_capability_projector: Any,
    mission_store: Any,
    mission_execution_store: Any,
    site_store: Any,
    processing_job_store: Any,
    observation_work_order_store: Any,
    acquisition_coordination_store: Any,
    organization_work_roster_store: Any,
    work_inbox_store: Any,
    external_relative_volume_store: Any,
) -> None:
    if auth_registry is not None:
        from ksi_core.auth import mount_auth

        mount_auth(
            app,
            auth_registry,
            human_auth_mode=human_auth_mode,
            oidc_verifier=oidc_verifier,
        )

    if runtime_capability_projector is not None:
        from ksi_core.capability.runtime_api import mount_runtime_capability

        mount_runtime_capability(
            app,
            runtime_capability_projector,
            mission_store=mission_store,
            mission_execution_store=mission_execution_store,
        )

    if site_store is not None:
        from ksi_core.sites import mount_sites

        mount_sites(app, site_store, processing_job_store)

    if observation_work_order_store is not None:
        from ksi_core.observation_work_orders import mount_observation_work_orders

        def _on_work_order_approved(order: Any, actor: str, now: Any) -> None:
            if acquisition_coordination_store is not None:
                acquisition_coordination_store.ensure_run(order, actor=actor, now=now)

        mount_observation_work_orders(
            app,
            observation_work_order_store,
            on_approved=(
                _on_work_order_approved if acquisition_coordination_store is not None else None
            ),
        )

    if organization_work_roster_store is not None:
        from ksi_core.organization_work_roster import build_organization_work_roster_router

        app.include_router(build_organization_work_roster_router(organization_work_roster_store))
        app.state.organization_work_roster_store = organization_work_roster_store

    if work_inbox_store is not None:
        from ksi_core.work_inbox import build_work_inbox_router

        assert observation_work_order_store is not None  # checked by assembly requirements
        assert organization_work_roster_store is not None  # checked by assembly requirements
        if not work_inbox_store.uses_exact_dependencies(
            work_orders=observation_work_order_store,
            roster=organization_work_roster_store,
            report_resolver=external_relative_volume_store,
        ):
            raise ValueError(
                "work inbox must use the mounted durable roster, WorkOrder and report graph"
            )

        app.include_router(build_work_inbox_router(work_inbox_store))
        app.state.work_inbox_store = work_inbox_store
