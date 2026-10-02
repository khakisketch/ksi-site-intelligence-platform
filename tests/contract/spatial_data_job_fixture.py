"""Genuine journals/source/grants; explicit local authority, never production fallback."""

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ksi_core.auth import Principal, PrincipalKind
from ksi_core.domains.external.delivery.grants import (
    SpatialDataGrantAuthorizer,
    SpatialDataGrantStore,
)
from ksi_core.domains.external.delivery.jobs import SpatialDataJobStore
from ksi_core.durable_journal import DurableJournal
from ksi_event_contracts.processing_job import ExecutionLocus
from ksi_event_contracts.spatial_data import (
    SpatialDataAttemptV1,
    SpatialDataJobViewV1,
    SpatialDataPurposeV1,
    SpatialDataReceiptV1,
)
from ksi_geo_spatial.external_native_window_geometry import plan_external_native_window
from spatial_data_fixture import (
    make_activation,
    make_grant,
    make_policy,
    make_receipt,
    make_runtime,
)
from spatial_data_source_fixture import source_identity, source_resolver, source_stores
from support.external_artifact_inspection_fixtures import NOW


class LocalJobAuthority:
    """Explicit test-only mutable authority under the graph's actual coordinator."""

    def __init__(self, graph: SimpleNamespace) -> None:
        self.coordinator = graph.coordinator
        self.principal = graph.principal
        self.enabled = True

    def resolve_requester(
        self, *, principal_id: str, organization_id: str, now: datetime
    ) -> Principal | None:
        if self.principal and (principal_id, organization_id) == (
            self.principal.principal_id,
            self.principal.organization_id,
        ):
            return self.principal
        return None

    def is_current(self, *, policy: Any, runtime: Any, activation: Any, now: datetime) -> bool:
        return self.enabled and activation.is_current_at(now)


def job_graph(path: Path, *, quota: int = 2) -> SimpleNamespace:
    graph = source_stores(path)
    graph.data_policy = make_policy(max_active_jobs_per_organization=quota)
    graph.runtime = make_runtime()
    graph.activation = make_activation(
        organization_id=graph.principal.organization_id,
        worker_principal_id="data-worker-1",
        worker_instance_id="instance-1",
        policy_digest=graph.data_policy.policy_digest,
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=1),
    )
    graph.sources = source_resolver(graph)
    source = graph.sources.resolve(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        asset_ref=source_identity(graph),
        principal=graph.principal,
    )
    graph.grants = SpatialDataGrantStore(
        DurableJournal(path / "grants.jsonl"), coordinator=graph.coordinator
    )
    graph.grant = make_grant(
        organization_id=graph.principal.organization_id,
        beneficiary_principal_id=graph.principal.principal_id,
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        asset_ref=source.asset_ref,
        observed_crs_digest=source.inspection.measurements.observed_crs_digest,
        allowed_bounds=(0, 0, 2, 2),
        policy_digest=graph.data_policy.policy_digest,
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=1),
    )
    graph.grants.provision(graph.grant)
    graph.authorizer = SpatialDataGrantAuthorizer(
        grants=graph.grants, sites=graph.sites, processing_location=ExecutionLocus.SITE_ONPREM
    )
    graph.authority = LocalJobAuthority(graph)
    graph.worker = Principal(
        principal_id="data-worker-1",
        organization_id=graph.principal.organization_id,
        kind=PrincipalKind.SPATIAL_DATA_WORKER,
        role=None,
        device_id=None,
    )
    graph.source = source
    graph.path = path
    return graph


def job_store(graph: SimpleNamespace) -> SpatialDataJobStore:
    from ksi_core.domains.external.delivery.jobs import SpatialDataJobStore

    journal = DurableJournal(graph.path / "jobs.jsonl")
    return SpatialDataJobStore(
        journal,
        grants=graph.authorizer,
        sources=graph.sources,
        policy=graph.data_policy,
        runtime=graph.runtime,
        activation=graph.activation,
        coordinator=graph.coordinator,
        currentness=graph.authority,
    )


def issue(
    store: SpatialDataJobStore,
    graph: SimpleNamespace,
    *,
    key: str = "one",
    now: datetime = NOW,
    **changes: Any,
) -> SpatialDataJobViewV1:
    from ksi_event_contracts.spatial_data import SpatialDataRequestV1

    request = SpatialDataRequestV1(
        asset_ref=graph.source.asset_ref,
        requested_bounds=(0, 0, 1, 1),
        observed_crs_digest=graph.source.inspection.measurements.observed_crs_digest,
        resolution_mode="NATIVE",
        purpose=SpatialDataPurposeV1.GENERAL_DATA_USE,
    ).model_copy(update=changes)
    return store.issue(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        request=request,
        principal=graph.principal,
        idempotency_key=key,
        now=now,
    )


def lease(
    store: SpatialDataJobStore,
    graph: SimpleNamespace,
    job: SpatialDataJobViewV1,
    *,
    acquisition: str = "acquisition-1",
    now: datetime = NOW,
) -> SpatialDataAttemptV1:
    return store.lease(
        job_id=job.job_id,
        worker=graph.worker,
        instance_id="instance-1",
        acquisition_id=acquisition,
        now=now,
    )


def receipt_for(
    store: SpatialDataJobStore,
    graph: SimpleNamespace,
    job: SpatialDataJobViewV1,
    attempt: SpatialDataAttemptV1,
    *,
    output_hash: str | None = None,
    now: datetime = NOW,
) -> SpatialDataReceiptV1:
    frozen = store.worker_input(job_id=job.job_id, worker=graph.worker, attempt=attempt, now=now)
    source = frozen.source
    measurements = source.inspection.measurements
    assert measurements is not None
    geometry = plan_external_native_window(
        requested_bounds=frozen.request.requested_bounds,
        measurements=measurements,
        requested_crs_digest=frozen.request.observed_crs_digest,
    )
    c0, c1, r0, r1 = geometry.pixel_window
    arguments = dict(
        job_id=job.job_id,
        job_digest=frozen.job_digest,
        request_digest=frozen.request.canonical_digest(),
        artifact_id=source.artifact_id,
        source_digest=source.source_digest,
        policy_digest=frozen.policy.policy_digest,
        grant_digest=frozen.grant.grant_digest,
        runtime_digest=frozen.runtime.runtime_digest,
        source_sha256=source.observed_sha256,
        source_size_bytes=source.observed_size_bytes,
        requested_bounds=frozen.request.requested_bounds,
        requested_crs_digest=frozen.request.observed_crs_digest,
        actual_bounds=geometry.actual_bounds,
        pixel_window=geometry.pixel_window,
        width=c1 - c0,
        height=r1 - r0,
        transform=geometry.transform,
        source_transform=measurements.transform,
        source_resolution=(measurements.transform[0], -measurements.transform[4]),
        observed_crs_identifier=measurements.observed_crs_identifier,
        observed_crs_digest=measurements.observed_crs_digest,
        band_count=measurements.band_count,
        dtype=measurements.dtype,
        nodata_representation=measurements.nodata_representation,
        nodata_value=measurements.nodata_value,
        valid_pixel_count=(c1 - c0) * (r1 - r0),
        artifact_kind=source.artifact_kind,
        attribution=frozen.grant.attribution,
        prepared_at=now,
        declaration_recorded_at=source.declaration_recorded_at,
    )
    if output_hash is not None:
        arguments["output_sha256"] = output_hash
    return make_receipt(**arguments)


def reserve_and_complete(
    store: SpatialDataJobStore,
    graph: SimpleNamespace,
    job: SpatialDataJobViewV1,
    attempt: SpatialDataAttemptV1,
    *,
    now: datetime = NOW,
) -> SimpleNamespace:
    from ksi_core.domains.external.delivery.storage_types import SpatialDataObjectObservation
    from ksi_event_contracts.spatial_data_worker import SpatialDataUploadDeclarationV1

    receipt = receipt_for(store, graph, job, attempt, now=now)
    target = store.reserve_output(
        job_id=job.job_id,
        worker=graph.worker,
        attempt=attempt,
        receipt=receipt,
        expires_at=now + timedelta(seconds=1),
        now=now,
    )
    declaration = SpatialDataUploadDeclarationV1(
        attempt=attempt,
        receipt=receipt,
        sha256=receipt.output_sha256,
        size_bytes=receipt.output_size_bytes,
        content_type="image/tiff",
    ).sealed()
    observation = SpatialDataObjectObservation(
        target.object_key,
        "version-1",
        receipt.output_size_bytes,
        receipt.output_sha256,
        "image/tiff",
    )
    assert declaration.upload_digest is not None
    completed = store.complete(
        job_id=job.job_id,
        worker=graph.worker,
        attempt=attempt,
        upload_digest=declaration.upload_digest,
        observation=observation,
        now=now,
    )
    return SimpleNamespace(
        completed=completed,
        target=target,
        receipt=receipt,
        declaration=declaration,
        observation=observation,
    )
