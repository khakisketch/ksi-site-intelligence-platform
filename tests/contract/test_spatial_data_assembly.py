"""Opt-in graph must bind exact live Core participants, never default/frozen authority."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.composition.spatial_data_graph import SpatialDataLocalGraphConfig, SpatialDataWiring
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_event_contracts.processing_job import ExecutionLocus
from spatial_data_job_fixture import NOW, job_graph
from test_api_contract_sync import _max_assembly_arguments
from test_spatial_data_worker_api import LocalProvider


def config(graph: SimpleNamespace) -> SpatialDataLocalGraphConfig:
    from ksi_core.composition.spatial_data_graph import SpatialDataLocalGraphConfig

    return SpatialDataLocalGraphConfig(
        policy=graph.data_policy,
        runtime=graph.runtime,
        activation=graph.activation,
        processing_location=ExecutionLocus.SITE_ONPREM,
        clock=lambda: NOW,
    )


def wiring(graph: SimpleNamespace, **changes: Any) -> SpatialDataWiring:
    from ksi_core.composition.spatial_data_graph import build_spatial_data_wiring

    args = dict(
        journal=lambda name: DurableJournal(graph.path / name),
        config=config(graph),
        reconstruction=graph.reconstruction,
        inspections=graph.inspections,
        sites=graph.sites,
        work_areas=graph.work_areas,
        work_orders=graph.work_orders,
        coordinator=graph.coordinator,
        storage=LocalProvider(graph),
        currentness=graph.authority,
    )
    return build_spatial_data_wiring(**{**args, **changes})


def test_guarded_download_wiring_requires_explicit_existing_private_spool(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.downloads import SpatialDataDownloadService

    graph = job_graph(tmp_path)
    root = tmp_path / "spool"
    root.mkdir(mode=0o700)
    lane = wiring(graph, spool_root=root)
    assert isinstance(lane.downloads, SpatialDataDownloadService)
    assert lane.downloads.jobs is lane.jobs and lane.downloads.storage is lane.storage
    assert lane.downloads.audit_store.policy == lane.config.policy


def test_download_wiring_cannot_mount_different_jobs_or_storage(tmp_path: Path) -> None:
    graph = job_graph(tmp_path)
    root = tmp_path / "spool"
    root.mkdir(mode=0o700)
    lane = wiring(graph, spool_root=root)
    with pytest.raises(ValueError, match="exact"):
        replace(lane, storage=LocalProvider(graph)).verify_participants(
            reconstruction=graph.reconstruction,
            inspections=graph.inspections,
            sites=graph.sites,
            work_areas=graph.work_areas,
            work_orders=graph.work_orders,
        )


def test_omitted_wiring_exposes_neither_public_nor_worker_data_routes() -> None:
    """Adding config defaults must never open data transport in ordinary composition."""
    app = create_app()
    assert not any("spatial-data" in path for path in app.openapi()["paths"])
    client = TestClient(app)
    assert client.get("/v1/internal/spatial-data-jobs").status_code == 404


@pytest.mark.parametrize(
    "participant",
    [
        "reconstruction",
        "inspections",
        "sites",
        "work_areas",
        "work_orders",
        "currentness",
        "storage",
    ],
)
def test_missing_participant_is_an_explicit_graph_error_before_journal_open(
    tmp_path: Path, participant: str
) -> None:
    """Partial injection must not become an unavailable but mounted usable graph."""
    graph = job_graph(tmp_path)
    with pytest.raises(ValueError):
        wiring(graph, **{participant: None})
    assert not (tmp_path / "spatial-data-jobs.jsonl").exists()


def test_same_coordinator_cannot_substitute_another_site_instance_at_mount(tmp_path: Path) -> None:
    """Matching locks are insufficient: mount must reject a disconnected actual authority store."""
    from ksi_core.sites import SiteStore

    graph = job_graph(tmp_path)
    lane = wiring(graph)
    impostor = SiteStore(
        DurableJournal(tmp_path / "other-sites.jsonl"), coordinator=graph.coordinator
    )
    with pytest.raises(ValueError, match="exact"):
        lane.verify_participants(
            reconstruction=graph.reconstruction,
            inspections=graph.inspections,
            sites=impostor,
            work_areas=graph.work_areas,
            work_orders=graph.work_orders,
        )


def test_incompatible_currentness_or_policy_rejected_before_opening_jobs(tmp_path: Path) -> None:
    """A different lane coordinator or unsigned policy cannot authorize a graph."""
    graph = job_graph(tmp_path)
    with pytest.raises(ValueError):
        wiring(
            graph,
            currentness=SimpleNamespace(coordinator=ExternalAuthorityCurrentnessCoordinator()),
        )
    with pytest.raises(ValueError):
        wiring(
            graph,
            config=replace(
                config(graph),
                policy=graph.data_policy.model_copy(update={"max_active_jobs_per_organization": 9}),
            ),
        )
    assert not (tmp_path / "spatial-data-jobs.jsonl").exists()


def test_forged_wiring_cannot_replace_the_grant_authorizer(tmp_path: Path) -> None:
    """Mount must reject an unrelated authorizer even if it shares the same site/coordinator."""
    from ksi_core.domains.external.delivery.grants import SpatialDataGrantAuthorizer

    graph = job_graph(tmp_path)
    lane = wiring(graph)
    impostor = SpatialDataGrantAuthorizer(
        grants=lane.grants, sites=graph.sites, processing_location=ExecutionLocus.SITE_ONPREM
    )
    with pytest.raises(ValueError):
        replace(lane, authorizer=impostor).verify_participants(
            reconstruction=graph.reconstruction,
            inspections=graph.inspections,
            sites=graph.sites,
            work_areas=graph.work_areas,
            work_orders=graph.work_orders,
        )


def maximal_data_arguments(path: Path) -> dict[str, Any]:
    from ksi_core.composition.spatial_data_graph import build_spatial_data_wiring
    from spatial_data_fixture import make_activation, make_policy, make_runtime
    from spatial_data_job_fixture import LocalJobAuthority

    args = _max_assembly_arguments(path)
    # This graph verifies genuine but empty mounted stores; byte preparation is not inferred.
    graph = SimpleNamespace(coordinator=args["site_store"].coordinator, principal=None)
    graph.data_policy, graph.runtime = make_policy(), make_runtime()
    graph.activation = make_activation(policy_digest=graph.data_policy.policy_digest)
    graph.authority = LocalJobAuthority(graph)
    args["spatial_data"] = build_spatial_data_wiring(
        journal=lambda name: DurableJournal(path / name),
        config=config(graph),
        reconstruction=args["external_reconstruction_store"],
        inspections=args["external_artifact_inspection_store"],
        sites=args["site_store"],
        work_areas=args["work_area_store"],
        work_orders=args["observation_work_order_store"],
        coordinator=graph.coordinator,
        storage=LocalProvider(graph),
        currentness=graph.authority,
    )
    return args


def test_full_factory_mounts_only_explicit_data_wiring_with_auth(tmp_path: Path) -> None:
    """The real app factory, not manual include_router, owns the opt-in protected surface."""
    args = maximal_data_arguments(tmp_path)
    app = create_app(**args)
    client = TestClient(app)
    assert client.get("/v1/internal/spatial-data-jobs").status_code == 401
    paths = app.openapi()["paths"]
    assert "get" in paths["/v1/internal/spatial-data-jobs"]
    base = "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests"
    assert "post" in paths[base] and "get" in paths[base]
    assert paths[base + "/{request_id}/file"].keys() >= {"get", "head"}
    args["auth_registry"] = None
    with pytest.raises(ValueError):
        create_app(**args)


def test_factory_rejects_disconnected_lane_even_with_shared_coordinator(tmp_path: Path) -> None:
    """A valid standalone graph cannot be quietly mounted onto different Core store objects."""
    from ksi_core.sites import SiteStore

    args = maximal_data_arguments(tmp_path)
    args["site_store"] = SiteStore(
        DurableJournal(tmp_path / "other-site.jsonl"), coordinator=args["site_store"].coordinator
    )
    with pytest.raises(ValueError, match="exact"):
        create_app(**args)


def test_wiring_cannot_substitute_currentness_with_same_coordinator(tmp_path: Path) -> None:
    """Swapping the authority wrapper must not leave jobs consulting an older, enabled port."""
    from spatial_data_job_fixture import LocalJobAuthority

    graph = job_graph(tmp_path)
    lane = wiring(graph)
    different = LocalJobAuthority(graph)
    different.enabled = False
    with pytest.raises(ValueError):
        replace(lane, currentness=different).verify_participants(
            reconstruction=graph.reconstruction,
            inspections=graph.inspections,
            sites=graph.sites,
            work_areas=graph.work_areas,
            work_orders=graph.work_orders,
        )


def assemble_arguments(path: Path) -> dict[str, Any]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from test_api_contract_sync import _auth_registry, _NullEvidenceStorage

    return dict(
        data_dir=path,
        journal=lambda name: DurableJournal(path / name),
        opened=[],
        edge_sync_snapshot_every=None,
        auth_registry=_auth_registry(),
        evidence_storage=_NullEvidenceStorage(),
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="local-test",
    )


def test_shared_assembler_requires_explicit_factories_and_binds_its_actual_stores(
    tmp_path: Path,
) -> None:
    """Shared assembly must use its newly constructed Core stores, not an unrelated saved graph."""
    from ksi_core.composition.assembly import assemble_app
    from ksi_core.composition.spatial_data_graph import SpatialDataLocalAssemblyConfig
    from spatial_data_job_fixture import LocalJobAuthority

    graph = job_graph(tmp_path)
    local = SpatialDataLocalAssemblyConfig(
        config=config(graph),
        build_storage=lambda reconstruction: LocalProvider(
            SimpleNamespace(reconstruction=reconstruction)
        ),
        build_currentness=lambda coordinator: LocalJobAuthority(
            SimpleNamespace(coordinator=coordinator, principal=None)
        ),
    )
    target = tmp_path / "assembly"
    target.mkdir()
    app = assemble_app(**assemble_arguments(target), spatial_data=local)
    assert TestClient(app).get("/v1/internal/spatial-data-jobs").status_code == 401
    lane = app.state.spatial_data
    assert lane.jobs.coordinator is app.state.external_authority_currentness
    assert lane.currentness.coordinator is lane.jobs.coordinator


def test_shared_assembler_rejects_missing_inspection_and_partial_configuration(
    tmp_path: Path,
) -> None:
    """Storage-less assembly cannot mount data even if local activation material exists."""
    from ksi_core.composition.assembly import assemble_app
    from ksi_core.composition.spatial_data_graph import SpatialDataLocalAssemblyConfig
    from spatial_data_job_fixture import LocalJobAuthority

    graph = job_graph(tmp_path)
    for absent in ("build_storage", "build_currentness"):
        partial: dict[str, Any] = dict(
            config=config(graph),
            build_storage=lambda reconstruction: LocalProvider(graph),
            build_currentness=lambda coordinator: LocalJobAuthority(graph),
        )
        partial[absent] = None
        with pytest.raises(ValueError):
            SpatialDataLocalAssemblyConfig(**partial)
    target = tmp_path / "missing"
    target.mkdir()
    args = assemble_arguments(target)
    args["evidence_storage"] = None
    builds = []

    def build_storage(reconstruction: Any) -> LocalProvider:
        builds.append(reconstruction)
        return LocalProvider(graph)

    local = SpatialDataLocalAssemblyConfig(
        config=config(graph),
        build_storage=build_storage,
        build_currentness=lambda coordinator: LocalJobAuthority(
            SimpleNamespace(coordinator=coordinator, principal=None)
        ),
    )
    with pytest.raises(ValueError):
        assemble_app(**args, spatial_data=local)
    assert not (target / "spatial-data-jobs.jsonl").exists()
    assert builds == []


@pytest.mark.parametrize("field", ["jobs", "sources", "authorizer", "currentness", "storage"])
def test_partial_wiring_is_a_typed_assembly_error(tmp_path: Path, field: str) -> None:
    """Partial frozen wiring must be an explicit ValueError, not a raw attribute exception."""
    graph = job_graph(tmp_path)
    lane = wiring(graph)
    partial: dict[str, Any] = {field: None}
    with pytest.raises(ValueError):
        broken = replace(lane, **partial)
        broken.verify_participants(
            reconstruction=graph.reconstruction,
            inspections=graph.inspections,
            sites=graph.sites,
            work_areas=graph.work_areas,
            work_orders=graph.work_orders,
        )
