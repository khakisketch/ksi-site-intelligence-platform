"""External-result route mounting and exact mounted-graph checks."""

from __future__ import annotations

from collections.abc import AsyncIterator
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
    external_delta_wiring: Any = None,
    external_masked_wiring: Any = None,
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
                egress=spatial_data.ai_egress,
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
        if spatial_data.discovery is not None or spatial_data.ai_egress is not None:
            from ksi_core.domains.external.delivery.asset_api import (
                build_spatial_data_asset_router,
            )

            if spatial_data.discovery is None or spatial_data.ai_egress is None:
                raise ValueError("spatial data discovery requires complete AI participants")
            app.include_router(
                build_spatial_data_asset_router(
                    discovery=spatial_data.discovery,
                    egress=spatial_data.ai_egress,
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

            from ksi_core.domains.external.ingress.site_spatial_workspace import (
                build_site_spatial_workspace_router,
            )

            app.include_router(
                build_site_spatial_workspace_router(
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

    if external_masked_wiring is not None:
        from contextlib import asynccontextmanager

        from ksi_core.composition.masked_quantitative_graph import MaskedQuantitativeWiring
        from ksi_core.domains.external.ingress.external_mask_input_api import (
            build_external_mask_input_router,
        )
        from ksi_core.domains.external.quantity.external_masked_calculation_api import (
            build_external_masked_calculation_router,
        )
        from ksi_core.domains.external.quantity.external_masked_input_capabilities import (
            build_external_masked_dsm_capability_router,
        )

        if (
            not isinstance(external_masked_wiring, MaskedQuantitativeWiring)
            or external_analysis_wiring is None
        ):
            raise ValueError("masked quantitative requires complete explicit common wiring")
        external_masked_wiring.verify_participants(
            assessments=external_analysis_wiring.assessments,
            sites=site_store,
            reconstruction=external_reconstruction_store,
            inspections=external_artifact_inspection_store,
            work_areas=work_area_store,
            coordinator=external_reconstruction_store.coordinator,
        )
        app.include_router(
            build_external_mask_input_router(
                ingress=external_masked_wiring.ingress,
                byte_store=external_masked_wiring.byte_store,
                inspection_journal=external_masked_wiring.inspection_journal,
                resource_envelope=external_masked_wiring.config.resource_envelope,
                designated_worker=external_masked_wiring.config.worker_principal,
                lane_source=external_masked_wiring.source_context,
                clock=external_masked_wiring.config.clock,
            )
        )
        app.include_router(
            build_external_masked_calculation_router(
                calculations=external_masked_wiring.calculations,
                evidence=external_masked_wiring.evidence,
                mask_bytes=external_masked_wiring.mask_bytes,
                resource_envelope=external_masked_wiring.config.resource_envelope,
                designated_worker=external_masked_wiring.config.worker_principal,
                dsm_byte_reader=external_masked_wiring.dsm_byte_reader,
                queued=external_masked_wiring.calculations,
                clock=external_masked_wiring.config.clock,
            )
        )
        app.state.external_masked_wiring = external_masked_wiring
        app.include_router(
            build_external_masked_dsm_capability_router(
                wiring=external_masked_wiring,
                reconstruction=external_reconstruction_store,
                storage=evidence_storage,
                designated_worker=external_masked_wiring.config.worker_principal,
                clock=external_masked_wiring.config.clock,
            )
        )
        previous_masked_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def masked_lifespan(application: FastAPI) -> AsyncIterator[Any]:
            try:
                async with previous_masked_lifespan(application) as state:
                    yield state
            finally:
                external_masked_wiring.close()

        app.router.lifespan_context = masked_lifespan

    if external_delta_wiring is not None:
        from contextlib import asynccontextmanager

        from ksi_core.composition.quantitative_extension_graph import DeltaPublicationWiring
        from ksi_core.domains.external.quantity.external_delta_publication_api import (
            build_external_delta_publication_router,
        )
        from ksi_core.domains.external.quantity.external_delta_publication_inputs import (
            DeltaPublicationS3InputCapabilityIssuer,
            build_external_delta_publication_input_router,
            build_external_delta_publication_masked_input_router,
        )

        if (
            not isinstance(external_delta_wiring, DeltaPublicationWiring)
            or external_analysis_wiring is None
        ):
            raise ValueError("delta publication requires complete explicit common wiring")
        external_delta_wiring.verify_participants(
            analysis=external_analysis_wiring,
            sites=site_store,
            coordinator=external_reconstruction_store.coordinator,
        )
        app.include_router(
            build_external_delta_publication_router(
                store=external_delta_wiring.store,
                clock=external_delta_wiring.config.clock,
            )
        )
        app.state.external_delta_wiring = external_delta_wiring
        app.include_router(
            build_external_delta_publication_input_router(
                store=external_delta_wiring.store,
                material_resolver=external_delta_wiring.source,
                capability_issuer=DeltaPublicationS3InputCapabilityIssuer(
                    reconstruction=external_reconstruction_store,
                    storage=evidence_storage,
                    signing_clock=external_delta_wiring.config.clock,
                ),
                clock=external_delta_wiring.config.clock,
            )
        )
        if external_delta_wiring.masked_source is not None:
            from ksi_core.domains.external.quantity.external_delta_mask_inputs import (
                build_external_delta_mask_input_router,
            )

            if (
                external_masked_wiring is None
                or external_delta_wiring.config.mask_core_origin is None
            ):
                raise ValueError("masked delta inputs require exact masked wiring and Core origin")
            if (
                external_delta_wiring.masked_source.calculations
                is not external_masked_wiring.calculations
            ):
                raise ValueError("masked delta inputs cannot use another calculation store")
            app.include_router(
                build_external_delta_publication_masked_input_router(
                    store=external_delta_wiring.store,
                    material_resolver=external_delta_wiring.masked_source,
                    capability_issuer=DeltaPublicationS3InputCapabilityIssuer(
                        reconstruction=external_reconstruction_store,
                        storage=evidence_storage,
                        signing_clock=external_delta_wiring.config.clock,
                    ),
                    mask_base_url=external_delta_wiring.config.mask_core_origin,
                    clock=external_delta_wiring.config.clock,
                )
            )
            app.include_router(
                build_external_delta_mask_input_router(
                    store=external_delta_wiring.store,
                    material_resolver=external_delta_wiring.masked_source,
                    mask_manifests=external_masked_wiring.ingress,
                    mask_bytes=external_masked_wiring.byte_store,
                    max_mask_bytes=min(
                        external_masked_wiring.config.resource_envelope.max_input_bytes,
                        external_masked_wiring.config.resource_envelope.max_streamed_bytes,
                    ),
                    clock=external_delta_wiring.config.clock,
                )
            )
        # Preserve the incumbent lifespan and any subsequently registered
        # production shutdown handlers; release only these new pinned byte fds.
        incumbent_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def delta_lifespan(application: FastAPI) -> AsyncIterator[Any]:
            try:
                async with incumbent_lifespan(application) as state:
                    yield state
            finally:
                external_delta_wiring.close()

        app.router.lifespan_context = delta_lifespan

    return external_result_projection
