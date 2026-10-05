"""External-result route mounting and exact mounted-graph checks."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def mount_external_routes(
    app: FastAPI,
    *,
    external_result_read_projector: Any,
    external_result_workflow_service: Any,
    observation_work_order_store: Any,
    site_store: Any,
    work_area_store: Any,
    external_relative_volume_store: Any,
    site_workspace_projector: Any,
    external_reconstruction_store: Any,
    evidence_storage: Any,
    external_evidence_store: Any,
    external_evidence_validation_store: Any,
    external_volume_input_capability_issuer: Any,
    external_volume_execution_activator: Any,
    external_use_evaluator: Any,
    external_single_volume: Any = None,
    spatial_data: Any = None,
    external_artifact_inspection_store: Any,
    external_display_artifact_store: Any,
    external_analysis_wiring: Any = None,
) -> Any:
    if spatial_data is not None:
        from ksi_core.composition.spatial_data_graph import (
            SpatialDataWiring,
            bind_spatial_data_openapi,
        )
        from ksi_core.domains.external.delivery.api import build_spatial_data_router
        from ksi_core.domains.external.delivery.worker_api import build_spatial_data_worker_router

        if not isinstance(spatial_data, SpatialDataWiring):
            raise ValueError("spatial data requires complete explicit wiring")
        spatial_data.verify_participants(
            reconstruction=external_reconstruction_store,
            inspections=external_artifact_inspection_store,
            sites=site_store,
            work_areas=work_area_store,
            work_orders=observation_work_order_store,
        )
        app.include_router(
            build_spatial_data_router(
                jobs=spatial_data.jobs,
                grants=spatial_data.authorizer,
                sources=spatial_data.sources,
                downloads=spatial_data.downloads,
                clock=spatial_data.config.clock,
            )
        )
        app.include_router(
            build_spatial_data_worker_router(
                jobs=spatial_data.jobs,
                storage=spatial_data.storage,
                activation=spatial_data.config.activation,
                clock=spatial_data.config.clock,
            )
        )
        app.state.spatial_data = spatial_data
        bind_spatial_data_openapi(app)
    external_result_projection = external_result_read_projector
    single_volume_store = (
        external_single_volume.store if external_single_volume is not None else None
    )
    if external_result_workflow_service is not None:
        from ksi_core.external_reobservation_proposals import verify_external_reobservation_graph
        from ksi_core.external_result_workflow_api import ExternalResultReadProjector

        service = external_result_workflow_service
        if (
            service.work_orders is not observation_work_order_store
            or service.sites is not site_store
            or service.work_areas is not work_area_store
        ):
            raise ValueError("external result workflow must use the mounted durable stores")
        assert external_relative_volume_store is not None
        verify_external_reobservation_graph(service=service)
        if external_result_projection is None:
            external_result_projection = ExternalResultReadProjector(
                volumes=external_relative_volume_store,
                workflow=service,
                single_volumes=single_volume_store,
            )
        elif not external_result_projection.uses_exact_graph(
            volumes=external_relative_volume_store,
            workflow=service,
            single_volumes=single_volume_store,
        ):
            raise ValueError("external result read projection must use the mounted durable graph")

    if external_result_workflow_service is not None and site_workspace_projector is not None:
        assert site_store is not None  # noqa: S101 -- external workflow assembly requirement
        assert observation_work_order_store is not None  # noqa: S101 -- workflow requirement
        if not site_workspace_projector.uses_exact_participants(
            site_store=site_store,
            work_order_store=observation_work_order_store,
            external_results=external_result_projection,
        ):
            raise ValueError("site workspace must use the mounted external result projection")

    if external_reconstruction_store is not None:
        from ksi_core.external_reconstruction import mount_external_reconstruction

        assert observation_work_order_store is not None  # noqa: S101 -- assembly requirement
        assert evidence_storage is not None  # noqa: S101 -- assembly requirement
        mount_external_reconstruction(
            app,
            external_reconstruction_store,
            work_orders=observation_work_order_store,
            storage=evidence_storage,
            external_results=external_result_projection,
        )

        if site_store is not None and work_area_store is not None:
            from ksi_core.domains.external.ingress.spatial_asset_catalog import (
                build_spatial_asset_catalog_router,
            )

            app.include_router(
                build_spatial_asset_catalog_router(
                    reconstruction=external_reconstruction_store,
                    work_orders=observation_work_order_store,
                    sites=site_store,
                    work_areas=work_area_store,
                    inspections=external_artifact_inspection_store,
                )
            )

    if external_evidence_store is not None:
        from ksi_core.external_evidence import mount_external_evidence

        assert external_reconstruction_store is not None  # noqa: S101 -- assembly guard
        assert observation_work_order_store is not None  # noqa: S101 -- assembly guard
        assert evidence_storage is not None  # noqa: S101 -- assembly guard
        mount_external_evidence(
            app,
            external_evidence_store,
            reconstruction=external_reconstruction_store,
            work_orders=observation_work_order_store,
            storage=evidence_storage,
            terminal_records=external_evidence_validation_store,
        )

    if external_evidence_validation_store is not None:
        from ksi_core.external_evidence_validations import mount_external_evidence_validations

        mount_external_evidence_validations(app, external_evidence_validation_store)

    if external_relative_volume_store is not None:
        from ksi_core.external_relative_volumes import build_external_relative_volume_router

        assert external_reconstruction_store is not None
        if (
            external_relative_volume_store.coordinator
            is not external_reconstruction_store.coordinator
        ):
            raise ValueError("external volume and reconstruction must share one coordinator")

        assert external_volume_input_capability_issuer is not None
        app.include_router(
            build_external_relative_volume_router(
                external_relative_volume_store,
                input_capability_issuer=external_volume_input_capability_issuer,
                execution_activator=external_volume_execution_activator,
                work_orders=observation_work_order_store,
            )
        )
        app.state.external_relative_volume_store = external_relative_volume_store

    if external_single_volume is not None:
        from ksi_core.domains.external.quantity.external_single_volumes import (
            build_external_single_volume_router,
        )

        single_store = external_single_volume.store
        assert external_reconstruction_store is not None
        if single_store.coordinator is not external_reconstruction_store.coordinator:
            raise ValueError("single volume and reconstruction must share one coordinator")
        app.include_router(
            build_external_single_volume_router(
                single_store,
                input_capability_issuer=external_single_volume.input_capability_issuer,
                execution_activator=external_single_volume.execution_activator,
                work_orders=observation_work_order_store,
            )
        )
        app.state.external_single_volume_store = single_store

    if external_result_workflow_service is not None:
        from ksi_core.external_reobservation_proposals import (
            build_external_reobservation_proposal_router,
        )
        from ksi_core.external_result_workflow_api import build_external_result_workflow_router

        service = external_result_workflow_service
        assert external_relative_volume_store is not None
        app.include_router(
            build_external_result_workflow_router(
                external_relative_volume_store, service, single_volumes=single_volume_store
            )
        )
        app.include_router(build_external_reobservation_proposal_router(service))
        app.state.external_result_workflow_service = service
        app.state.external_result_read_projector = external_result_projection

    if external_use_evaluator is not None:
        from ksi_core.external_use_evaluator import mount_external_use_evaluator

        assert external_reconstruction_store is not None  # noqa: S101 -- assembly table
        assert observation_work_order_store is not None  # noqa: S101 -- assembly table
        mount_external_use_evaluator(
            app,
            external_use_evaluator,
            reconstruction=external_reconstruction_store,
            work_orders=observation_work_order_store,
        )

    if external_artifact_inspection_store is not None:
        from ksi_core.external_artifact_inspections import mount_external_artifact_inspections

        assert external_display_artifact_store is not None  # noqa: S101 -- assembly table
        assert external_reconstruction_store is not None  # noqa: S101 -- assembly table
        assert observation_work_order_store is not None  # noqa: S101 -- assembly table
        mount_external_artifact_inspections(
            app,
            external_artifact_inspection_store,
            reconstruction=external_reconstruction_store,
            work_orders=observation_work_order_store,
            display_store=external_display_artifact_store,
        )

    if external_analysis_wiring is not None:
        from ksi_core.domains.external.quantity.external_analysis_api import (
            build_external_analysis_router,
        )
        from ksi_core.domains.external.quantity.external_analysis_worker_api import (
            build_external_analysis_worker_router,
        )

        wiring = external_analysis_wiring
        if any(
            value is None
            for value in (
                wiring.facade,
                wiring.intents,
                wiring.assessments,
                wiring.calculations,
                wiring.capability_issuer,
            )
        ):
            raise ValueError("external analysis wiring requires its complete local graph")
        app.include_router(
            build_external_analysis_router(wiring.facade, activation=wiring.activation)
        )
        app.include_router(
            build_external_analysis_worker_router(
                intents=wiring.intents,
                assessments=wiring.assessments,
                calculations=wiring.calculations,
                capability_issuer=wiring.capability_issuer,
                activation=wiring.activation,
            )
        )
        app.state.external_analysis_wiring = wiring
        if wiring.reviews is not None:
            from ksi_core.domains.external.quantity.external_analysis_reviews import (
                build_analysis_review_router,
            )

            app.include_router(build_analysis_review_router(wiring.reviews))

    return external_result_projection
