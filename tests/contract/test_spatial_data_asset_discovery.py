"""Task3 RED: grant-filtered AI asset discovery with snapshot pagination.

Behavioral scenarios over real generated Core sources/grants (no TIFF SDK,
no customer evidence): filtering precedes pagination, strict snapshot cursors,
READ-only/subpixel PREPARE suppression, ambiguity non-union, superseded exact
addressability, budget-failure surfacing, exact-graph mounting, and send-time
rechecks with the AI egress acknowledgment.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.durable_journal import DurableJournal
from ksi_core.identity.auth import (
    AuthRegistry,
    PrincipalTokenRecord,
    mount_auth,
)
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    NodataRepresentation,
    RasterMeasurementsV1,
)
from pyproj import CRS
from spatial_data_fixture import make_grant
from spatial_data_job_fixture import NOW, job_store
from spatial_data_source_fixture import source_resolver, source_stores
from starlette.types import Message
from test_spatial_data_ai_egress import (
    AiAuthority,
    ai_credentials,
    ai_lane,
    ai_principal,
)


def _wkt_5186() -> str:
    return CRS.from_epsg(5186).to_wkt(version="WKT2_2019", pretty=False, output_axis_rule=True)


def _two_asset_measurements(_policy):
    """Two MEASURED outcomes (ortho + dsm) bound to the sealed two-artifact submission."""
    wkt = _wkt_5186()
    crs_digest = "sha256:" + hashlib.sha256(wkt.encode()).hexdigest()

    def measured(artifact_id: str, observed: str, dtype: str, bands: int):
        return ArtifactInspectionOutcomeV1(
            artifact_id=artifact_id,
            observed_sha256="sha256:" + observed,
            outcome=ArtifactOutcome.MEASURED,
            measurements=RasterMeasurementsV1(
                observed_crs_identifier="EPSG:5186",
                observed_crs_wkt=wkt,
                observed_crs_digest=crs_digest,
                transform=(1.0, 0.0, 0.0, 0.0, -1.0, 2.0),
                footprint_wkt="POLYGON((0 0,2 0,2 2,0 2,0 0))",
                footprint_digest="sha256:" + "e" * 64,
                width=2,
                height=2,
                band_count=bands,
                dtype=dtype,
                layout="GEOTIFF_STRIPED_V1",
                nodata_representation=NodataRepresentation.NONE,
                valid_pixel_count=4,
            ),
        )

    return (
        measured("ortho", "c" * 64, "uint8", 3),
        measured("dsm", "d" * 64, "float32", 1),
    )


def two_asset_lane(tmp_path: Path) -> SimpleNamespace:
    """AI lane over one sealed submission declaring ortho + dsm (two permitted assets)."""
    from ksi_core.domains.external.delivery.ai_egress import SpatialDataAiEgress
    from ksi_core.domains.external.delivery.asset_discovery import SpatialDataAssetDiscovery
    from ksi_core.domains.external.delivery.grants import (
        SpatialDataGrantAuthorizer,
        SpatialDataGrantStore,
    )
    from ksi_core.domains.external.delivery.metadata_audit import (
        SpatialDataMetadataAuditStore,
    )
    from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog
    from ksi_event_contracts.processing_job import ExecutionLocus
    from spatial_data_fixture import make_activation, make_policy, make_runtime
    from support.external_artifact_inspection_fixtures import sealed_submission

    declarations = sealed_submission(include_dsm=True).artifacts
    graph = source_stores(
        tmp_path,
        artifact_declarations=declarations,
        measurement_factory=_two_asset_measurements,
    )
    graph.path = tmp_path
    record = graph.sites._sites["site-1"]  # noqa: SLF001
    graph.sites._sites["site-1"] = replace(record, ai_egress_allowed=True)  # noqa: SLF001
    graph.data_policy = make_policy()
    graph.runtime = make_runtime()
    graph.activation = make_activation(
        organization_id=graph.principal.organization_id,
        worker_principal_id="data-worker-1",
        worker_instance_id="instance-1",
        policy_digest=graph.data_policy.policy_digest,
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(hours=1),
    )
    graph.sources = source_resolver(graph)
    catalog = SpatialAssetCatalog(
        reconstruction=graph.reconstruction,
        work_orders=graph.work_orders,
        sites=graph.sites,
        work_areas=graph.work_areas,
        inspections=graph.inspections,
    )
    items = catalog.items("site-1", graph.area.work_area_id, graph.principal)
    assert {item.artifact_id for item in items} == {"ortho", "dsm"}
    graph.catalog_refs = {item.artifact_id: item.asset_ref for item in items}
    resolved = {}
    for item in items:
        resolved[item.artifact_id] = graph.sources.resolve(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            asset_ref=item.asset_ref,
            principal=graph.principal,
        )
    graph.asset_sources = resolved
    graph.grants = SpatialDataGrantStore(
        DurableJournal(tmp_path / "grants.jsonl"), coordinator=graph.coordinator
    )
    graph.authorizer = SpatialDataGrantAuthorizer(
        grants=graph.grants, sites=graph.sites, processing_location=ExecutionLocus.SITE_ONPREM
    )
    ai = ai_principal(graph.area.work_area_id)
    graph.authority = AiAuthority(graph, ai)
    graph.ai = ai
    store = job_store(graph)
    graph.ai_store = store
    measurements = next(iter(resolved.values())).inspection.measurements
    assert measurements is not None
    graph.ai_grants = {}
    for artifact_id, asset_ref in graph.catalog_refs.items():
        grant = make_grant(
            grant_id=f"local-ai-grant-{artifact_id}",
            organization_id=ai.organization_id,
            beneficiary_principal_id=ai.principal_id,
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            asset_ref=asset_ref,
            observed_crs_digest=measurements.observed_crs_digest,
            allowed_bounds=(0, 0, 2, 2),
            operations=("PREPARE", "READ"),
            purposes=("EXTERNAL_AI",),
            processing_location="site_onprem",
            policy_digest=graph.data_policy.policy_digest,
            valid_from=NOW - timedelta(minutes=1),
            valid_until=NOW + timedelta(hours=1),
        )
        graph.grants.provision(grant)
        graph.ai_grants[artifact_id] = grant
    audit = SpatialDataMetadataAuditStore(
        DurableJournal(tmp_path / "metadata-audit.jsonl"), policy=graph.data_policy
    )
    graph.ai_audit = audit
    discovery = SpatialDataAssetDiscovery(
        sources=graph.sources,
        grants=graph.authorizer,
        jobs=store,
        clock=lambda: NOW,
    )
    graph.discovery = discovery
    graph.ai_egress = SpatialDataAiEgress(
        store, graph.sources, graph.authorizer, audit, clock=lambda: NOW, discovery=discovery
    )
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=principal
                )
                for token, principal in (("ai-token", ai), ("operator-token", graph.principal))
            ]
        ),
    )
    graph.ai_app = app
    return graph


def asset_app(graph: SimpleNamespace) -> TestClient:
    from ksi_core.domains.external.delivery.asset_api import build_spatial_data_asset_router

    app = graph.ai_app
    app.include_router(
        build_spatial_data_asset_router(
            discovery=graph.discovery,
            egress=graph.ai_egress,
            clock=lambda: NOW,
        )
    )
    return TestClient(app)


def asset_url(graph: SimpleNamespace, suffix: str = "") -> str:
    return f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}/spatial-data-assets{suffix}"


def ai_headers() -> dict[str, str]:
    return {"Authorization": "Bearer ai-token"}


def _revoke_one(graph: SimpleNamespace, name: str):
    """Withdraw one named test AI grant; returns the revoked grant."""
    from ksi_event_contracts.spatial_data_authority import SpatialDataRevocationV1

    grant = graph.ai_grants[name]
    graph.grants.revoke(
        SpatialDataRevocationV1(
            grant_id=grant.grant_id,
            revision=grant.revision,
            organization_id=grant.organization_id,
            grant_digest=grant.grant_digest,
            revoked_at=NOW,
            reason="test rights withdrawn",
        ).sealed()
    )
    return grant


def _revoke_all(graph: SimpleNamespace) -> None:
    """Withdraw every test AI grant benefiting this lane's AI principal."""
    from ksi_event_contracts.spatial_data_authority import SpatialDataRevocationV1

    grants = getattr(graph, "ai_grants", None)
    grants = {"single": graph.ai_grant} if grants is None else dict(graph.ai_grants)
    for grant in grants.values():
        graph.grants.revoke(
            SpatialDataRevocationV1(
                grant_id=grant.grant_id,
                revision=grant.revision,
                organization_id=grant.organization_id,
                grant_digest=grant.grant_digest,
                revoked_at=NOW,
                reason="test rights withdrawn",
            ).sealed()
        )


# ---- 1. filter before page; no denied counts ---------------------------------


def test_discovery_filters_before_page_and_does_not_leak_counts(tmp_path: Path) -> None:
    graph = two_asset_lane(tmp_path)
    page = graph.discovery.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        limit=1,
        cursor=None,
        now=NOW,
    )
    assert [item.asset_ref for item in page.items] == sorted(graph.catalog_refs.values())[:1]
    assert page.next_cursor is not None
    second = graph.discovery.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        limit=1,
        cursor=page.next_cursor,
        now=NOW,
    )
    assert [item.asset_ref for item in second.items] == sorted(graph.catalog_refs.values())[1:]
    assert second.next_cursor is None
    # Revoking one grant filters before pagination: the denied asset never
    # consumes a page slot and no denied count leaks onto the wire.
    _revoke_one(graph, "dsm")
    filtered = graph.discovery.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        limit=1,
        cursor=None,
        now=NOW,
    )
    assert [item.asset_ref for item in filtered.items] == [graph.catalog_refs["ortho"]]
    assert filtered.next_cursor is None
    wire = filtered.model_dump(by_alias=True, mode="json")
    assert set(wire) == {"items", "nextCursor"}
    assert "total" not in wire and "denied" not in str(wire)


# ---- 2. cursor scope + snapshot staleness --------------------------------------


def test_cursor_scope_and_current_projection_staleness(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import (
        SpatialDataAiDomainError,
        SpatialDataDomainError,
    )

    graph = two_asset_lane(tmp_path)
    page = graph.discovery.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        limit=1,
        cursor=None,
        now=NOW,
    )
    assert page.next_cursor is not None
    cursor = page.next_cursor
    assert "sdj-v1" not in cursor and "ksa-v1" not in cursor
    # Malformed, foreign-scope and tampered-last cursors are 422, never 404/409.
    for bad in (
        "not-a-cursor!!!",
        "e30",
        page.next_cursor[:-2] + ("AA" if not page.next_cursor.endswith("AA") else "BB"),
    ):
        with pytest.raises(SpatialDataDomainError) as failure:
            graph.discovery.list(
                site_id="site-1",
                work_area_id=graph.area.work_area_id,
                principal=graph.ai,
                limit=1,
                cursor=bad,
                now=NOW,
            )
        assert (failure.value.reason, failure.value.status_code) == (
            "INVALID_REQUEST_BOUNDS",
            422,
        )
    # A changed current projection (replacement grant, new bounds) stales the cursor.
    revoked = _revoke_one(graph, "dsm")
    replacement = revoked.model_copy(
        update={"revision": 2, "grant_digest": None, "allowed_bounds": (0, 0, 1, 1)}
    ).sealed()
    graph.grants.provision(replacement)
    with pytest.raises(SpatialDataAiDomainError) as stale:
        graph.discovery.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=graph.ai,
            limit=1,
            cursor=cursor,
            now=NOW,
        )
    assert (stale.value.reason, stale.value.status_code) == ("SPATIAL_DATA_CURSOR_STALE", 409)
    # Restarting without the cursor succeeds under the new projection.
    restarted = graph.discovery.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        limit=8,
        cursor=None,
        now=NOW,
    )
    assert {item.asset_ref for item in restarted.items} == set(graph.catalog_refs.values())


def test_discovery_cursor_input_bounds_and_scope_negatives(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.asset_discovery import encode_snapshot_cursor
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = two_asset_lane(tmp_path)
    call = dict(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        now=NOW,
    )
    for limit in (0, -1, 201, 9, "1"):
        with pytest.raises(SpatialDataDomainError) as failure:
            graph.discovery.list(limit=limit, cursor=None, **call)
        assert (failure.value.reason, failure.value.status_code) == (
            "RESOURCE_LIMIT_EXCEEDED",
            422,
        )
    # A well-formed cursor bound to another scope is rejected before any paging.
    foreign = encode_snapshot_cursor(scope="deadbeef", snapshot="0" * 64, last="x" * 8)
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.discovery.list(limit=1, cursor=foreign, **call)
    assert (failure.value.reason, failure.value.status_code) == ("INVALID_REQUEST_BOUNDS", 422)
    # Unknown asset detail and malformed refs are non-disclosing 404s.
    for ref in ("ksa-v1-" + "f" * 64, "not-an-asset-ref", ""):
        with pytest.raises(SpatialDataDomainError) as failure:
            graph.discovery.get(
                site_id="site-1",
                work_area_id=graph.area.work_area_id,
                asset_ref=ref,
                principal=graph.ai,
                now=NOW,
            )
        assert (failure.value.reason, failure.value.status_code) == ("NOT_FOUND", 404)


# ---- 3. READ-only / subpixel: no PREPARE advertisement -------------------------


def test_read_only_grant_and_subpixel_bounds_do_not_advertise_prepare(
    tmp_path: Path,
) -> None:
    graph = ai_lane(tmp_path, issue_job=False)
    measurements = graph.source.inspection.measurements
    assert measurements is not None
    read_only = make_grant(
        grant_id="local-ai-read-only",
        organization_id=graph.ai.organization_id,
        beneficiary_principal_id=graph.ai.principal_id,
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        asset_ref=graph.source.asset_ref,
        observed_crs_digest=measurements.observed_crs_digest,
        allowed_bounds=(0, 0, 2, 2),
        operations=("READ",),
        purposes=("EXTERNAL_AI",),
        processing_location="site_onprem",
        policy_digest=graph.data_policy.policy_digest,
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(hours=1),
    )
    graph.grants.provision(read_only)
    from ksi_core.domains.external.delivery.asset_discovery import SpatialDataAssetDiscovery

    discovery = SpatialDataAssetDiscovery(
        sources=graph.sources, grants=graph.authorizer, jobs=graph.ai_store, clock=lambda: NOW
    )
    view = discovery.get(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        asset_ref=graph.source.asset_ref,
        principal=graph.ai,
        now=NOW,
    )
    assert view.permitted_operations == ("READ",)
    assert view.permitted_bounds == (0, 0, 2, 2)
    # A subpixel grant still lists metadata (no whole-pixel gate on READ) but
    # can never advertise preparation of a whole native cell.
    from ksi_event_contracts.spatial_data_authority import SpatialDataRevocationV1

    graph.grants.revoke(
        SpatialDataRevocationV1(
            grant_id=read_only.grant_id,
            revision=read_only.revision,
            organization_id=read_only.organization_id,
            grant_digest=read_only.grant_digest,
            revoked_at=NOW,
            reason="test rights withdrawn",
        ).sealed()
    )
    subpixel = read_only.model_copy(
        update={"revision": 2, "grant_digest": None, "allowed_bounds": (0, 0, 0.5, 0.5)}
    ).sealed()
    graph.grants.provision(subpixel)
    listed = discovery.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        limit=8,
        cursor=None,
        now=NOW,
    )
    assert [item.asset_ref for item in listed.items] == [graph.source.asset_ref]
    assert listed.items[0].permitted_operations == ("READ",)
    assert listed.items[0].permitted_bounds == (0, 0, 0.5, 0.5)


# ---- 4. ambiguous grants are omitted, never unioned ------------------------------


def test_ambiguous_grants_are_not_unioned(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.asset_discovery import SpatialDataAssetDiscovery
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path, issue_job=False)
    graph.grants.provision(graph.ai_grant)
    graph.grants.provision(
        graph.ai_grant.model_copy(update={"revision": 2, "grant_digest": None}).sealed()
    )
    discovery = SpatialDataAssetDiscovery(
        sources=graph.sources, grants=graph.authorizer, jobs=graph.ai_store, clock=lambda: NOW
    )
    omitted = discovery.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        limit=8,
        cursor=None,
        now=NOW,
    )
    assert omitted.items == () and omitted.next_cursor is None
    with pytest.raises(SpatialDataDomainError) as failure:
        discovery.get(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            asset_ref=graph.source.asset_ref,
            principal=graph.ai,
            now=NOW,
        )
    assert (failure.value.reason, failure.value.status_code) == ("AMBIGUOUS_GRANT", 403)


# ---- 5. unknown vertical + superseded exact asset ----------------------------------


def test_ortho_unknown_vertical_and_superseded_exact_asset(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.asset_discovery import SpatialDataAssetDiscovery

    graph = ai_lane(tmp_path, issue_job=False)
    graph.grants.provision(graph.ai_grant)
    newer = graph.record.submission.model_copy(
        update={"revision": 2, "submission_digest": None}
    ).sealed()
    assert (
        graph.reconstruction.register(
            newer, work_order=graph.order, registered_by="operator-1", now=NOW
        ).revision.submission.revision
        == 2
    )
    discovery = SpatialDataAssetDiscovery(
        sources=graph.sources, grants=graph.authorizer, jobs=graph.ai_store, clock=lambda: NOW
    )
    page = discovery.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        limit=8,
        cursor=None,
        now=NOW,
    )
    # The unsealed latest revision is omitted; the granted sealed revision stays
    # addressable under its own lifecycle, never substituted by the latest.
    assert [item.asset_ref for item in page.items] == [graph.source.asset_ref]
    assert page.items[0].lifecycle_state == "SUPERSEDED"
    view = discovery.get(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        asset_ref=graph.source.asset_ref,
        principal=graph.ai,
        now=NOW,
    )
    assert view.revision == 1
    assert view.lifecycle_state == "SUPERSEDED"
    assert view.observed_sha256 == graph.source.observed_sha256
    assert view.artifact_kind == "ortho"
    assert view.observed_vertical_reference is None
    assert view.accuracy_assessed is False
    assert view.analysis_status == "NOT_EVALUATED"
    assert view.timestamp_provenance == "SUBMISSION_DECLARATION"
    assert view.permitted_operations == ("READ", "PREPARE")
    wire = view.model_dump(by_alias=True, mode="json")
    for forbidden in ("fileName", "submissionId", "objectKey", "token", "tags"):
        assert forbidden not in wire


# ---- 6. budget failure is an explicit refusal --------------------------------------


def test_catalog_budget_failure_is_not_empty_success(tmp_path: Path) -> None:
    from fastapi import HTTPException
    from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog

    graph = two_asset_lane(tmp_path)
    catalog = SpatialAssetCatalog(
        reconstruction=graph.reconstruction,
        work_orders=graph.work_orders,
        sites=graph.sites,
        work_areas=graph.work_areas,
        inspections=graph.inspections,
    )
    with pytest.raises(HTTPException) as failure:
        catalog.items("site-1", graph.area.work_area_id, graph.principal, max_items=1)
    assert failure.value.status_code == 503
    # Overage is refused rather than truncated: the full catalog still resolves.
    assert len(catalog.items("site-1", graph.area.work_area_id, graph.principal)) == 2
    # A sealed dependency surfaces 503 through discovery instead of empty success.
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph.sites._journal.close()  # noqa: SLF001
    with pytest.raises(SpatialDataDomainError) as denied:
        graph.discovery.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=graph.ai,
            limit=8,
            cursor=None,
            now=NOW,
        )
    assert denied.value.status_code == 503


# ---- 7. exact-graph mounting ----------------------------------------------------------


def test_discovery_mount_requires_exact_graph(tmp_path: Path) -> None:
    from ksi_core.composition.spatial_data_graph import (
        SpatialDataLocalGraphConfig,
        build_spatial_data_wiring,
    )
    from ksi_core.durable_journal import DurableJournal
    from ksi_event_contracts.processing_job import ExecutionLocus
    from spatial_data_job_fixture import job_graph
    from test_spatial_data_worker_api import LocalProvider

    graph = job_graph(tmp_path)
    lane = build_spatial_data_wiring(
        journal=lambda name: DurableJournal(graph.path / name),
        config=SpatialDataLocalGraphConfig(
            policy=graph.data_policy,
            runtime=graph.runtime,
            activation=graph.activation,
            processing_location=ExecutionLocus.SITE_ONPREM,
            clock=lambda: NOW,
        ),
        reconstruction=graph.reconstruction,
        inspections=graph.inspections,
        sites=graph.sites,
        work_areas=graph.work_areas,
        work_orders=graph.work_orders,
        coordinator=graph.coordinator,
        storage=LocalProvider(graph),
        currentness=graph.authority,
    )
    assert lane.discovery is not None and lane.ai_egress is not None
    assert lane.ai_egress.discovery is lane.discovery
    app = FastAPI()
    app.state.auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"ai-token").hexdigest(),
                principal=ai_principal(graph.area.work_area_id),
            )
        ]
    )
    from ksi_core.domains.external.delivery.asset_api import build_spatial_data_asset_router

    app.include_router(
        build_spatial_data_asset_router(
            discovery=lane.discovery, egress=lane.ai_egress, clock=lambda: NOW
        )
    )
    assert (
        TestClient(app)
        .get(
            f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}/spatial-data-assets",
            headers={"Authorization": "Bearer ai-token"},
        )
        .status_code
        == 403
    )
    assert (
        TestClient(app)
        .get(f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}/spatial-data-assets")
        .status_code
        == 401
    )
    # A mismatched discovery/egress pair is refused at router build, never mounted.
    other_path = tmp_path / "other"
    other_path.mkdir()
    other = job_graph(other_path)
    other_lane = build_spatial_data_wiring(
        journal=lambda name: DurableJournal(other.path / name),
        config=SpatialDataLocalGraphConfig(
            policy=other.data_policy,
            runtime=other.runtime,
            activation=other.activation,
            processing_location=ExecutionLocus.SITE_ONPREM,
            clock=lambda: NOW,
        ),
        reconstruction=other.reconstruction,
        inspections=other.inspections,
        sites=other.sites,
        work_areas=other.work_areas,
        work_orders=other.work_orders,
        coordinator=other.coordinator,
        storage=LocalProvider(other),
        currentness=other.authority,
    )
    with pytest.raises(ValueError, match="participant"):
        build_spatial_data_asset_router(
            discovery=other_lane.discovery, egress=lane.ai_egress, clock=lambda: NOW
        )
    # Without the data graph the asset routes are absent entirely.
    from ksi_core.app import create_app

    assert not any("spatial-data-assets" in path for path in create_app().openapi()["paths"])


# ---- 8. send-time recheck + ack ---------------------------------------------------------


def _framed(response) -> tuple[int, dict[bytes, bytes], bytes]:
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("receive unexpectedly returned")

    asyncio.run(response({"type": "http", "method": "GET", "headers": []}, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), body


def test_discovery_ack_rechecked_at_send(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ksi_core.domains.external.delivery.credential_currentness import (
        SpatialDataCredentialCurrentness,
    )
    from ksi_domain.canonical_json import canonical_json_bytes

    graph = two_asset_lane(tmp_path)
    view = graph.discovery.get(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        asset_ref=graph.catalog_refs["ortho"],
        principal=graph.ai,
        now=NOW,
    )
    response = graph.ai_egress.prepare_asset_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        operation="GET_ASSET",
    )
    status, headers, body = _framed(response)
    assert status == 200
    assert headers[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
    assert headers[b"content-length"] == str(len(body)).encode()
    assert body == canonical_json_bytes(view.model_dump(by_alias=True, mode="json"))
    assert graph.ai_audit.count == 1
    # Rights withdrawn after prepare are denied at send with no ack and no body.
    revoked_lane = two_asset_lane(tmp_path / "revoked")
    revoked_view = revoked_lane.discovery.get(
        site_id="site-1",
        work_area_id=revoked_lane.area.work_area_id,
        asset_ref=revoked_lane.catalog_refs["ortho"],
        principal=revoked_lane.ai,
        now=NOW,
    )
    prepared = revoked_lane.ai_egress.prepare_asset_response(
        credentials=ai_credentials(revoked_lane),
        site_id="site-1",
        work_area_id=revoked_lane.area.work_area_id,
        view=revoked_view,
        operation="GET_ASSET",
    )
    _revoke_all(revoked_lane)
    status, headers, body = _framed(prepared)
    assert status == 404
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    assert body == b"" or b"assetRef" not in body
    # A denial after the audit keeps the attempt event: revocation lands
    # between the second credential refresh and the header handoff.
    late_lane = two_asset_lane(tmp_path / "late")
    late_view = late_lane.discovery.get(
        site_id="site-1",
        work_area_id=late_lane.area.work_area_id,
        asset_ref=late_lane.catalog_refs["ortho"],
        principal=late_lane.ai,
        now=NOW,
    )
    late = late_lane.ai_egress.prepare_asset_response(
        credentials=ai_credentials(late_lane),
        site_id="site-1",
        work_area_id=late_lane.area.work_area_id,
        view=late_view,
        operation="GET_ASSET",
    )
    real_resolve = SpatialDataCredentialCurrentness.resolve
    calls = {"count": 0}

    def resolving_twice(self, *, now):
        calls["count"] += 1
        principal = real_resolve(self, now=now)
        if calls["count"] == 2:
            _revoke_all(late_lane)
        return principal

    monkeypatch.setattr(SpatialDataCredentialCurrentness, "resolve", resolving_twice)
    status, headers, _ = _framed(late)
    assert status == 404
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    assert late_lane.ai_audit.count == 1


# ---- HTTP parity: asset routes --------------------------------------------------------------


def test_asset_routes_serve_guarded_pages_over_http(tmp_path: Path) -> None:
    graph = two_asset_lane(tmp_path)
    client = asset_app(graph)
    response = client.get(asset_url(graph), headers=ai_headers())
    assert response.status_code == 200, response.text
    assert response.headers["x-ksi-spatial-data-ai-egress"] == "ALLOWED"
    body = response.json()
    assert [item["assetRef"] for item in body["items"]] == sorted(graph.catalog_refs.values())[:1]
    assert body["items"][0]["permittedOperations"] == ["READ", "PREPARE"]
    assert body["items"][0]["accuracyAssessed"] is False
    detail = client.get(asset_url(graph, "/" + graph.catalog_refs["dsm"]), headers=ai_headers())
    assert detail.status_code == 200, detail.text
    assert detail.headers["x-ksi-spatial-data-ai-egress"] == "ALLOWED"
    assert detail.json()["assetRef"] == graph.catalog_refs["dsm"]
    # Unknown asset, withdrawn grants and withdrawn consent fail closed.
    assert (
        client.get(asset_url(graph, "/ksa-v1-" + "f" * 64), headers=ai_headers()).status_code == 404
    )
    present = client.get(asset_url(graph), headers=ai_headers())
    assert present.status_code == 200
    _revoke_all(graph)
    emptied = client.get(asset_url(graph), headers=ai_headers())
    assert emptied.status_code == 200
    assert emptied.json()["items"] == []
    assert emptied.headers["x-ksi-spatial-data-ai-egress"] == "ALLOWED"
    missing_detail = client.get(
        asset_url(graph, "/" + graph.catalog_refs["ortho"]), headers=ai_headers()
    )
    assert missing_detail.status_code == 404
    assert "assetRef" not in missing_detail.json()
    record = graph.sites._sites["site-1"]  # noqa: SLF001
    graph.sites._sites["site-1"] = replace(record, ai_egress_allowed=False)  # noqa: SLF001
    refused = client.get(asset_url(graph), headers=ai_headers())
    assert refused.status_code == 403
    assert "x-ksi-spatial-data-ai-egress" not in {k.lower() for k in refused.headers}


# ---- FIXROUND1 RED: I2 / P1 / P2 / P3 (behavioral, current snapshot) ---------------


def test_fix1_list_evaluates_every_candidate_at_one_authority_time(tmp_path: Path) -> None:
    """I2: one list() evaluates all candidates at its own `now`, not the clock."""
    from ksi_core.domains.external.delivery.asset_discovery import SpatialDataAssetDiscovery

    graph = two_asset_lane(tmp_path)
    state = {"now": NOW}
    discovery = SpatialDataAssetDiscovery(
        sources=graph.sources,
        grants=graph.authorizer,
        jobs=graph.ai_store,
        clock=lambda: state["now"],
    )
    call = dict(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        limit=8,
        cursor=None,
    )
    sane = discovery.list(now=NOW, **call)
    assert len(sane.items) == 2
    # Grants expire one hour after NOW; the lane check still sees the passed
    # `now`, so drifting the shared clock must not re-evaluate candidates
    # under an expired grant generation inside the same page.
    state["now"] = NOW + timedelta(hours=2)
    drifted = discovery.list(now=NOW, **call)
    assert [item.asset_ref for item in drifted.items] == [item.asset_ref for item in sane.items]


def test_fix1_ai_job_list_refuses_withdrawn_consent_even_when_empty(tmp_path: Path) -> None:
    """P1: an empty AI job page still binds current consent; no 200 bypass."""
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
    from test_spatial_data_ai_egress import ai_lane

    graph = ai_lane(tmp_path, issue_job=False)
    call = dict(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        cursor=None,
        limit=8,
    )
    empty = graph.ai_store.list(now=NOW, **call)
    assert empty.items == () and empty.next_cursor is None
    record = graph.sites._sites["site-1"]  # noqa: SLF001
    graph.sites._sites["site-1"] = replace(record, ai_egress_allowed=False)  # noqa: SLF001
    with pytest.raises(SpatialDataDomainError) as denied:
        graph.ai_store.list(now=NOW, **call)
    assert (denied.value.reason, denied.value.status_code) == ("AI_EGRESS_DENIED", 403)


def test_fix1_ai_job_egress_page_refuses_withdrawn_consent_before_send(
    tmp_path: Path,
) -> None:
    """P1: a prepared empty AI job page withdrawn before send never gets an ack."""
    from ksi_event_contracts.spatial_data import SpatialDataPageV1
    from test_spatial_data_ai_egress import ai_lane

    graph = ai_lane(tmp_path, issue_job=False)
    response = graph.ai_egress.prepare_job_page_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        page=SpatialDataPageV1(items=(), next_cursor=None),
        cursor=None,
        limit=8,
    )
    record = graph.sites._sites["site-1"]  # noqa: SLF001
    graph.sites._sites["site-1"] = replace(record, ai_egress_allowed=False)  # noqa: SLF001
    status, headers, body = _framed(response)
    assert status == 403
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    assert body == b"" or b"jobId" not in body
    assert graph.ai_audit.count == 0


def test_fix1_ai_job_all_filtered_page_still_binds_consent(tmp_path: Path) -> None:
    """P1: all-filtered (revoked) jobs are legitimately empty only while consent holds."""
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
    from test_spatial_data_ai_egress import ai_lane, revoke

    graph = ai_lane(tmp_path)
    revoke(graph)
    call = dict(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        cursor=None,
        limit=8,
    )
    filtered = graph.ai_store.list(now=NOW, **call)
    assert filtered.items == () and filtered.next_cursor is None
    record = graph.sites._sites["site-1"]  # noqa: SLF001
    graph.sites._sites["site-1"] = replace(record, ai_egress_allowed=False)  # noqa: SLF001
    with pytest.raises(SpatialDataDomainError) as denied:
        graph.ai_store.list(now=NOW, **call)
    assert (denied.value.reason, denied.value.status_code) == ("AI_EGRESS_DENIED", 403)


def test_fix1_ai_job_empty_authorized_page_sends_with_ack(tmp_path: Path) -> None:
    """P1 guard: empty + consenting AI job page stays a legitimate 200 with ack."""
    from ksi_domain.canonical_json import canonical_json_bytes
    from test_spatial_data_ai_egress import ai_lane

    graph = ai_lane(tmp_path, issue_job=False)
    page = graph.ai_store.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        cursor=None,
        limit=8,
        now=NOW,
    )
    assert page.items == () and page.next_cursor is None
    response = graph.ai_egress.prepare_job_page_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        page=page,
        cursor=None,
        limit=8,
    )
    status, headers, body = _framed(response)
    assert status == 200
    assert headers[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
    assert body == canonical_json_bytes(page.model_dump(by_alias=True, mode="json"))


def test_fix1_ai_job_list_rejects_foreign_scope_before_enumeration(
    tmp_path: Path,
) -> None:
    """P1 guard: scope/authority failures precede AI job enumeration, never empty 200."""
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
    from test_spatial_data_ai_egress import ai_lane, ai_principal

    graph = ai_lane(tmp_path, issue_job=False)
    foreign = ai_principal("other-area")
    with pytest.raises(SpatialDataDomainError) as denied:
        graph.ai_store.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=foreign,
            cursor=None,
            limit=8,
            now=NOW,
        )
    assert (denied.value.reason, denied.value.status_code) == ("NOT_FOUND", 404)
    graph.sites._journal.close()  # noqa: SLF001
    with pytest.raises(SpatialDataDomainError) as unavailable:
        graph.ai_store.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=graph.ai,
            cursor=None,
            limit=8,
            now=NOW,
        )
    assert unavailable.value.status_code == 503


def test_fix1_catalog_budgets_refuse_before_accumulation(tmp_path: Path) -> None:
    """P2: optional item/byte budgets refuse overage before accumulation, never truncate."""
    from fastapi import HTTPException
    from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog
    from ksi_domain.canonical_json import canonical_json_bytes

    graph = two_asset_lane(tmp_path)
    catalog = SpatialAssetCatalog(
        reconstruction=graph.reconstruction,
        work_orders=graph.work_orders,
        sites=graph.sites,
        work_areas=graph.work_areas,
        inspections=graph.inspections,
    )
    call = dict(site_id="site-1", work_area_id=graph.area.work_area_id, principal=graph.principal)
    full = catalog.items(**call)
    assert len(full) == 2
    with pytest.raises(HTTPException) as over_items:
        catalog.items(max_items=1, **call)
    assert over_items.value.status_code == 503
    # Overage is refused rather than truncated: omitting budgets keeps behavior.
    assert len(catalog.items(**call)) == 2
    # A singleton item larger than the byte budget is an explicit refusal.
    first_bytes = len(canonical_json_bytes(full[0].model_dump(by_alias=True, mode="json")))
    with pytest.raises(HTTPException) as over_bytes:
        catalog.items(max_bytes=first_bytes - 1, **call)
    assert over_bytes.value.status_code == 503
    # An exact-fit byte budget still succeeds with every item.
    total = sum(
        len(canonical_json_bytes(item.model_dump(by_alias=True, mode="json"))) for item in full
    )
    assert len(catalog.items(max_bytes=total, **call)) == 2


def _counting_policy_port(graph: SimpleNamespace):
    """Wrap the real inspection authority port with a counting delegate (genuine behavior)."""
    registry = graph.inspections._policy_registry  # noqa: SLF001
    inner = registry._authority_port  # noqa: SLF001
    calls = {"resolve": 0, "resolve_historical": 0}

    class CountingPort:
        def resolve(self, digest, now):
            calls["resolve"] += 1
            return inner.resolve(digest, now)

        def resolve_historical(self, digest, at):
            calls["resolve_historical"] += 1
            return inner.resolve_historical(digest, at)

    registry._authority_port = CountingPort()  # noqa: SLF001
    return calls, registry, inner


def test_fix1_asset_grant_change_between_prepare_and_send_refuses(tmp_path: Path) -> None:
    """P3 guard: grant/bounds drift between prepare and send refuses with no stale bytes."""
    graph = two_asset_lane(tmp_path)
    view = graph.discovery.get(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        asset_ref=graph.catalog_refs["ortho"],
        principal=graph.ai,
        now=NOW,
    )
    response = graph.ai_egress.prepare_asset_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        operation="GET_ASSET",
    )
    revoked = _revoke_one(graph, "ortho")
    replacement = revoked.model_copy(
        update={"revision": 2, "grant_digest": None, "allowed_bounds": (0, 0, 1, 1)}
    ).sealed()
    graph.grants.provision(replacement)
    status, headers, body = _framed(response)
    assert status == 409
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    assert body == b"" or b"assetRef" not in body


# ---- FIXROUND2: P4 / M1 / P5 (behavioral RED on fix1 snapshot) ---------------------


def _committed_ai_error() -> dict:
    import json as jsonlib

    root = Path(__file__).resolve().parents[2]
    committed = jsonlib.loads(
        (root / "contracts" / "schemas" / "spatial-data-ai.v1.json").read_text(encoding="utf-8")
    )
    return committed["$defs"]["SpatialDataAiErrorV1"]


def _reason_literals(schema: object, *, key: str = "reason") -> set[str]:
    """Collect every string literal bound to an error reason, const or enum form."""
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            const = node.get("const")
            if type(const) is str:
                found.add(const)
            for name, value in node.items():
                if name == "enum" and isinstance(value, list):
                    found.update(v for v in value if type(v) is str)
                elif name != "const":
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    assert isinstance(schema, dict)
    walk(schema.get("properties", {}).get(key, {}))
    return found


def test_fix2_asset_routes_document_ai_error_family(tmp_path: Path) -> None:
    """P4: new routes declare the strict AI error family, not the old V1 enum."""
    graph = two_asset_lane(tmp_path)
    asset_app(graph)
    spec = graph.ai_app.openapi()
    committed = _committed_ai_error()
    assert sorted(committed["properties"]) == ["message", "reason", "remediation", "retryable"]
    committed_reasons = _reason_literals(committed)
    assert "SPATIAL_DATA_CURSOR_STALE" in committed_reasons
    routes = (
        "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-assets",
        "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-assets/{asset_ref}",
    )
    for path in routes:
        responses = spec["paths"][path]["get"]["responses"]
        assert {"403", "404", "409", "422", "503"} <= set(responses)
        for code in ("403", "404", "409", "422", "503"):
            schema = responses[code]["content"]["application/json"]["schema"]
            assert schema.get("$ref", "").endswith("/SpatialDataAiErrorV1"), (path, code)
            assert "SpatialDataErrorV1" not in json.dumps(responses[code]), (path, code)
        assert "401" not in responses or "content" not in responses["401"]
    mounted = spec["components"]["schemas"]["SpatialDataAiErrorV1"]
    assert sorted(mounted["properties"]) == sorted(committed["properties"])
    assert _reason_literals(mounted) == committed_reasons
    # A live refusal carries a reason inside the mounted AI family.
    client = asset_app(graph)
    denied = client.get(asset_url(graph, "/ksa-v1-" + "f" * 64), headers=ai_headers())
    assert denied.status_code == 404
    assert denied.json()["reason"] in _reason_literals(mounted)


def test_fix2_asset_send_gate_phases_make_zero_port_calls(tmp_path: Path) -> None:
    """M1: phase-attributed — header/body local gates add zero authority-port calls."""
    graph = two_asset_lane(tmp_path)
    calls, registry, inner = _counting_policy_port(graph)
    gates = {"runs": 0, "resolve": 0, "historical": 0}
    real_recheck = graph.discovery.recheck_view

    def wrapped(*, view, principal, now):
        gates["runs"] += 1
        before = (calls["resolve"], calls["resolve_historical"])
        try:
            return real_recheck(view=view, principal=principal, now=now)
        finally:
            gates["resolve"] += calls["resolve"] - before[0]
            gates["historical"] += calls["resolve_historical"] - before[1]

    graph.discovery.recheck_view = wrapped  # noqa: SLF001
    try:
        view = graph.discovery.get(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            asset_ref=graph.catalog_refs["ortho"],
            principal=graph.ai,
            now=NOW,
        )
        assert calls["resolve"] >= 1  # validity: the spy observes real preflight traffic
        response = graph.ai_egress.prepare_asset_response(
            credentials=ai_credentials(graph),
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            view=view,
            operation="GET_ASSET",
        )
        status, headers, _ = _framed(response)
        assert status == 200
        assert headers[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
        assert gates["runs"] == 2  # header gate + body gate both ran locally
        assert (gates["resolve"], gates["historical"]) == (0, 0)
    finally:
        registry._authority_port = inner  # noqa: SLF001
        del graph.discovery.recheck_view  # noqa: SLF001


def test_fix2_asset_page_send_gate_phases_make_zero_port_calls(tmp_path: Path) -> None:
    """M1: phase-attributed — page header/body gates add zero authority-port calls."""
    graph = two_asset_lane(tmp_path)
    calls, registry, inner = _counting_policy_port(graph)
    gates = {"runs": 0, "resolve": 0, "historical": 0}
    real_recheck = graph.discovery.recheck_page

    def wrapped(*, site_id, work_area_id, principal, limit, cursor, gate, now):
        gates["runs"] += 1
        before = (calls["resolve"], calls["resolve_historical"])
        try:
            return real_recheck(
                site_id=site_id,
                work_area_id=work_area_id,
                principal=principal,
                limit=limit,
                cursor=cursor,
                gate=gate,
                now=now,
            )
        finally:
            gates["resolve"] += calls["resolve"] - before[0]
            gates["historical"] += calls["resolve_historical"] - before[1]

    graph.discovery.recheck_page = wrapped  # noqa: SLF001
    try:
        page = graph.discovery.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=graph.ai,
            limit=8,
            cursor=None,
            now=NOW,
        )
        assert len(page.items) == 2
        assert calls["resolve"] >= 2  # validity: preflight traffic observed
        response = graph.ai_egress.prepare_asset_page_response(
            credentials=ai_credentials(graph),
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            page=page,
            cursor=None,
            limit=8,
        )
        status, headers, _ = _framed(response)
        assert status == 200
        assert headers[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
        assert gates["runs"] == 2
        assert (gates["resolve"], gates["historical"]) == (0, 0)
    finally:
        registry._authority_port = inner  # noqa: SLF001
        del graph.discovery.recheck_page  # noqa: SLF001


def test_fix2_local_gates_succeed_with_raising_port(tmp_path: Path) -> None:
    """M1: gates stay local — a raising authority port never fires inside them."""
    from ksi_domain.canonical_json import canonical_json_bytes

    graph = two_asset_lane(tmp_path)
    call = dict(site_id="site-1", work_area_id=graph.area.work_area_id, principal=graph.ai)
    view = graph.discovery.get(asset_ref=graph.catalog_refs["ortho"], now=NOW, **call)
    page, context = graph.discovery.list_projection(limit=8, cursor=None, now=NOW, **call)
    registry = graph.inspections._policy_registry  # noqa: SLF001
    inner = registry._authority_port  # noqa: SLF001

    class RaisingPort:
        def resolve(self, digest, now):
            raise AssertionError("final gate must not resolve the authority port")

        def resolve_historical(self, digest, at):
            raise AssertionError("final gate must not resolve the authority port historically")

    registry._authority_port = RaisingPort()  # noqa: SLF001
    try:
        assert graph.discovery.recheck_view(
            view=view, principal=graph.ai, now=NOW
        ) == canonical_json_bytes(view.model_dump(by_alias=True, mode="json"))
        assert graph.discovery.recheck_page(
            limit=8, cursor=None, gate=dict(context), now=NOW, **call
        ) == canonical_json_bytes(page.model_dump(by_alias=True, mode="json"))
    finally:
        registry._authority_port = inner  # noqa: SLF001


def _grant_for_ref(graph: SimpleNamespace, asset_ref: str, grant_id: str):
    """Provision a genuine current AI grant for one catalog asset ref (test setup)."""
    from spatial_data_fixture import make_grant

    measurements = next(iter(graph.asset_sources.values())).inspection.measurements
    assert measurements is not None
    grant = make_grant(
        grant_id=grant_id,
        organization_id=graph.ai.organization_id,
        beneficiary_principal_id=graph.ai.principal_id,
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        asset_ref=asset_ref,
        observed_crs_digest=measurements.observed_crs_digest,
        allowed_bounds=(0, 0, 2, 2),
        operations=("PREPARE", "READ"),
        purposes=("EXTERNAL_AI",),
        processing_location="site_onprem",
        policy_digest=graph.data_policy.policy_digest,
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(hours=1),
    )
    graph.grants.provision(grant)
    return grant


def _register_second_submission(graph: SimpleNamespace, submission_id: str):
    """Register a genuinely unsealed second submission via the owner API."""
    from ksi_core.acquisition import observation_epoch_id
    from support.external_artifact_inspection_fixtures import sealed_submission

    submission = (
        sealed_submission()
        .model_copy(
            update={
                "submission_id": submission_id,
                "submission_digest": None,
                "observation_epoch_id": observation_epoch_id(graph.order),
            }
        )
        .sealed()
    )
    result = graph.reconstruction.register(
        submission, work_order=graph.order, registered_by="operator-1", now=NOW
    )
    assert result.revision is not None
    return submission, result.revision


def _admit_policy_for_subject(graph: SimpleNamespace, subject):
    """Admit a genuine inspection policy permitting one sealed subject (owner APIs)."""
    from ksi_core.external_validation_policy import (
        PolicyAuthorityRecord,
        authorized_policy_body_digest,
    )
    from support.external_artifact_inspection_fixtures import policy_template

    registry = graph.inspections._policy_registry  # noqa: SLF001
    from support.external_artifact_inspection_fixtures import envelope as _envelope

    widened = (
        _envelope()
        .model_copy(update={"max_tenant_concurrency": 2, "resource_envelope_digest": None})
        .sealed()
    )
    template = policy_template().model_copy(
        update={
            "policy_id": f"policy-{subject.submission_id}",
            "resource_envelope": widened,
            "resource_envelope_digest": widened.resource_envelope_digest,
            "policy_digest": None,
        }
    )
    record = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(subject,),
        permitted_uses=("INSPECTION", "DISPLAY"),
        authorized_actor_ids=("authority",),
        active_from=NOW - timedelta(minutes=1),
        active_until=NOW + timedelta(hours=1),
        synthetic_test_only=True,
    ).sealed()
    registry._authority_port._records[record.digest] = record  # noqa: SLF001
    policy = template.model_copy(
        update={"authority_record_digest": record.digest, "policy_digest": None}
    ).sealed()
    registry.admit(policy, actor="authority", now=NOW)
    return policy


def _seal_revision(graph: SimpleNamespace, submission, revision):
    """Seal one registered revision via the owner API; returns sealed record + subject."""
    from ksi_core.evidence import ObjectStorageObservation
    from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
    from support.external_artifact_inspection_fixtures import SyntheticStorage

    storage = SyntheticStorage()
    for artifact_id, key in revision.bindings:
        declared = next(a for a in submission.artifacts if a.artifact_id == artifact_id)
        storage.objects[key] = ObjectStorageObservation(
            object_key=key,
            exists=True,
            sha256="sha256:" + declared.declared_sha256,
            size_bytes=declared.declared_size_bytes,
            content_type=declared.content_type,
        )
    sealed = graph.reconstruction.seal(
        graph.order.work_order_id,
        submission.submission_id,
        submission.revision,
        organization_id="organization-1",
        site_id="site-1",
        storage=storage,
        now=NOW,
    )
    record = sealed.revision
    assert record is not None and record.manifest is not None
    subject = SealedExternalSubjectV1(
        organization_id="organization-1",
        site_id="site-1",
        work_order_id=graph.order.work_order_id,
        submission_id=submission.submission_id,
        revision=submission.revision,
        submission_digest=submission.submission_digest,
        manifest_digest=record.manifest.manifest_digest,
    )
    return record, subject


def _record_measurement(graph: SimpleNamespace, subject, policy):
    """Record a genuine MEASURED ortho report for one sealed subject (owner APIs)."""
    from ksi_core.leasing import LeaseFence
    from ksi_event_contracts.external_artifact_validation import SealedArtifactBindingV1
    from support.external_artifact_inspection_fixtures import ACQUISITION, WORKER_A

    issued = graph.inspections.issue_after_seal(subject, now=NOW)
    assert issued.request is not None
    fence = graph.inspections.claim(
        issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW
    ).fence
    base = graph.accepted_report
    ortho = next(o for o in base.measurement_payload.outcomes if o.artifact_id == "ortho")
    assert ortho.measurements is not None
    payload = base.measurement_payload.model_copy(
        update={
            "subject_digest": subject.canonical_digest(),
            "sealed_manifest_digest": subject.manifest_digest,
            "inspection_policy_digest": policy.policy_digest,
            "inspector_build_digest": policy.parser_build_digest,
            "outcomes": (ortho,),
            "artifact_bindings": (
                SealedArtifactBindingV1(artifact_id="ortho", observed_sha256=ortho.observed_sha256),
            ),
        }
    )
    accepted = base.model_copy(
        update={
            "request_id": issued.request.request_id,
            "subject": subject,
            "subject_digest": subject.canonical_digest(),
            "sealed_manifest_digest": subject.manifest_digest,
            "inspection_policy_digest": policy.policy_digest,
            "inspector_build_digest": policy.parser_build_digest,
            "measurement_payload": payload,
            "measurement_payload_digest": None,
            "report_digest": None,
        }
    ).sealed()
    assert (
        graph.inspections.record_report(issued.request.request_id, fence, accepted, now=NOW).verdict
        == "REPORTED"
    )
    return subject


def _seal_and_measure(graph: SimpleNamespace, submission, revision, policy):
    """Seal one revision then record its MEASURED ortho report (owner APIs)."""
    _, subject = _seal_revision(graph, submission, revision)
    return _record_measurement(graph, subject, policy)


def _unready_ref(graph: SimpleNamespace, submission_id: str) -> str:
    """The UNSEALED ortho asset ref of one registered submission (test validity)."""
    del submission_id
    items = graph.sources.candidates(
        site_id="site-1", work_area_id=graph.area.work_area_id, principal=graph.principal
    )
    known = set(graph.catalog_refs.values())
    matches = [
        item for item in items if item.artifact_id == "ortho" and item.asset_ref not in known
    ]
    assert len(matches) == 1, "exactly the second submission must be pending"
    from ksi_event_contracts.spatial_asset_catalog import SpatialAssetLifecycleStateV1

    assert matches[0].lifecycle_state is SpatialAssetLifecycleStateV1.UNSEALED
    return matches[0].asset_ref


def test_fix2_newly_ready_granted_candidate_stales_send(tmp_path: Path) -> None:
    """P5: a granted candidate turning ready after preflight must stale/refuse, not omit."""
    graph = two_asset_lane(tmp_path)
    submission, revision = _register_second_submission(graph, "submission-2")
    sub2_ref = _unready_ref(graph, "submission-2")
    _grant_for_ref(graph, sub2_ref, "local-ai-grant-sub2")
    page = graph.discovery.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        limit=8,
        cursor=None,
        now=NOW,
    )
    assert sub2_ref not in [item.asset_ref for item in page.items]
    response = graph.ai_egress.prepare_asset_page_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        page=page,
        cursor=None,
        limit=8,
    )
    real_append = graph.ai_audit.append
    sealed = {"done": False}

    def append_then_ready(*args, **kwargs):
        # Deterministic barrier: readiness lands after the bounded preflight
        # (which runs before the audit) and before the header/body gates, via
        # genuine owner APIs only.
        if not sealed["done"]:
            sealed["done"] = True
            _, subject = _seal_revision(graph, submission, revision)
            policy = _admit_policy_for_subject(graph, subject)
            _record_measurement(graph, subject, policy)
        return real_append(*args, **kwargs)

    graph.ai_audit.append = append_then_ready  # noqa: SLF001
    try:
        status, headers, body = _framed(response)
    finally:
        graph.ai_audit.append = real_append  # noqa: SLF001
    assert sealed["done"]
    assert status == 409
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    assert body == b"" or b"assetRef" not in body


def test_fix2_unrelated_ungranted_readiness_keeps_page_stable(tmp_path: Path) -> None:
    """P5 control: unrelated ungranted readiness authorizes nothing and disturbs nothing."""
    from ksi_domain.canonical_json import canonical_json_bytes

    graph = two_asset_lane(tmp_path)
    submission, revision = _register_second_submission(graph, "submission-3")
    sub3_ref = _unready_ref(graph, "submission-3")
    page = graph.discovery.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        limit=8,
        cursor=None,
        now=NOW,
    )
    assert sub3_ref not in [item.asset_ref for item in page.items]
    prepared = canonical_json_bytes(page.model_dump(by_alias=True, mode="json"))
    response = graph.ai_egress.prepare_asset_page_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        page=page,
        cursor=None,
        limit=8,
    )
    real_append = graph.ai_audit.append
    sealed = {"done": False}

    def append_then_ready(*args, **kwargs):
        if not sealed["done"]:
            sealed["done"] = True
            _, subject = _seal_revision(graph, submission, revision)
            policy = _admit_policy_for_subject(graph, subject)
            _record_measurement(graph, subject, policy)
        return real_append(*args, **kwargs)

    graph.ai_audit.append = append_then_ready  # noqa: SLF001
    try:
        status, headers, body = _framed(response)
    finally:
        graph.ai_audit.append = real_append  # noqa: SLF001
    assert sealed["done"]
    assert status == 200
    assert headers[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
    assert body == prepared
    assert sub3_ref not in body.decode()


# ---- FIXROUND3: pure report-arrival P5 (behavioral RED on fix2 tree) -----------------


def _subject_for(graph: SimpleNamespace, submission):
    """Current sealed subject for one submission from the genuine record."""
    from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1

    items = graph.sources.candidates(
        site_id="site-1", work_area_id=graph.area.work_area_id, principal=graph.principal
    )
    known = set(graph.catalog_refs.values())
    candidates = [i for i in items if i.artifact_id == "ortho" and i.asset_ref not in known]
    assert len(candidates) == 1
    item = candidates[0]
    submission_id = graph.reconstruction.resolve_submission_ref(
        item.work_order_id,
        item.submission_ref,
        organization_id="organization-1",
        site_id="site-1",
    )
    record = graph.reconstruction.get(
        item.work_order_id,
        submission_id,
        item.revision,
        organization_id="organization-1",
        site_id="site-1",
    )
    assert record is not None and record.manifest is not None
    return SealedExternalSubjectV1(
        organization_id="organization-1",
        site_id="site-1",
        work_order_id=graph.order.work_order_id,
        submission_id=record.submission.submission_id,
        revision=record.submission.revision,
        submission_digest=record.submission.submission_digest,
        manifest_digest=record.manifest.manifest_digest,
    )


def _sealed_unmeasured_ref(graph: SimpleNamespace) -> tuple[str, object, object]:
    """Register+seal (no report) a second submission; returns ref/submission/revision."""
    submission, revision = _register_second_submission(graph, "submission-4")
    _seal_revision(graph, submission, revision)
    from ksi_event_contracts.spatial_asset_catalog import SpatialAssetLifecycleStateV1

    items = graph.sources.candidates(
        site_id="site-1", work_area_id=graph.area.work_area_id, principal=graph.principal
    )
    known = set(graph.catalog_refs.values())
    matches = [
        item for item in items if item.artifact_id == "ortho" and item.asset_ref not in known
    ]
    assert len(matches) == 1
    assert matches[0].lifecycle_state is SpatialAssetLifecycleStateV1.SEALED
    return matches[0].asset_ref, submission, revision


def test_fix3_pure_report_arrival_stales_send(tmp_path: Path) -> None:
    """P5-report: a granted sealed candidate turning measured after preflight must refuse."""
    graph = two_asset_lane(tmp_path)
    sub4_ref, submission, revision = _sealed_unmeasured_ref(graph)
    _grant_for_ref(graph, sub4_ref, "local-ai-grant-sub4")
    call = dict(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        limit=8,
        cursor=None,
    )
    page = graph.discovery.list(now=NOW, **call)
    assert sub4_ref not in [item.asset_ref for item in page.items]
    response = graph.ai_egress.prepare_asset_page_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        page=page,
        cursor=None,
        limit=8,
    )
    real_append = graph.ai_audit.append
    reported = {"done": False}

    def append_then_report(*args, **kwargs):
        # Deterministic barrier: only the measurement report lands after the
        # bounded preflight (which runs before the audit) and before the
        # header/body gates, via genuine owner APIs. The seal predates the
        # preflight, so only pure report-state changes.
        if not reported["done"]:
            reported["done"] = True
            subject = _subject_for(graph, submission)
            policy = _admit_policy_for_subject(graph, subject)
            _record_measurement(graph, subject, policy)
        return real_append(*args, **kwargs)

    graph.ai_audit.append = append_then_report  # noqa: SLF001
    try:
        status, headers, body = _framed(response)
    finally:
        graph.ai_audit.append = real_append  # noqa: SLF001
    assert reported["done"]
    assert status == 409
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    assert body == b"" or b"assetRef" not in body
    # Validity: the report genuinely arrived — a fresh listing admits it.
    fresh = graph.discovery.list(now=NOW, **call)
    assert sub4_ref in [item.asset_ref for item in fresh.items]


def test_fix3_retained_state_fingerprint_unit(tmp_path: Path) -> None:
    """Owner fingerprint: deterministic, bounded, sealed-aware, never near the port."""
    graph = two_asset_lane(tmp_path)
    subject = graph.subject
    assert subject is not None
    store = graph.inspections
    first = store.locally_retained_state_digest_bounded(subject, max_records=8)
    assert type(first) is str and first.startswith("sha256:")
    assert store.locally_retained_state_digest_bounded(subject, max_records=8) == first
    with pytest.raises(ValueError):
        store.locally_retained_state_digest_bounded(subject, max_records=0)
    registry = store._policy_registry  # noqa: SLF001
    inner = registry._authority_port  # noqa: SLF001

    class RaisingPort:
        def resolve(self, digest, now):
            raise AssertionError("fingerprint must not resolve the authority port")

        def resolve_historical(self, digest, at):
            raise AssertionError("fingerprint must not resolve the authority port")

    registry._authority_port = RaisingPort()  # noqa: SLF001
    try:
        assert store.locally_retained_state_digest_bounded(subject, max_records=8) == first
    finally:
        registry._authority_port = inner  # noqa: SLF001
    sealed_lane = two_asset_lane(tmp_path / "sealed")
    assert sealed_lane.subject is not None
    sealed_lane.inspections._journal.close()  # noqa: SLF001
    assert (
        sealed_lane.inspections.locally_retained_state_digest_bounded(
            sealed_lane.subject, max_records=8
        )
        is None
    )


# ---- FIXROUND4: strict cursor digest shapes + AI job negative matrix ----------------


def _b64_raw(payload: bytes) -> str:
    import base64 as _base64

    return _base64.urlsafe_b64encode(payload).decode("ascii")


def _real_scope(graph: SimpleNamespace) -> str:
    from ksi_core.domains.external.delivery.asset_discovery import scope_hash

    return scope_hash(
        organization_id=graph.ai.organization_id,
        principal_id=graph.ai.principal_id,
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
    )


def test_fix4_lexical_fake_snapshot_is_malformed(tmp_path: Path) -> None:
    """Cursor snapshot/scope must be exact SHA256 shapes; lexical fakes are 422, not 409."""
    from ksi_core.domains.external.delivery.asset_discovery import encode_snapshot_cursor
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
    from test_spatial_data_ai_egress import ai_lane

    graph = two_asset_lane(tmp_path)
    scope = _real_scope(graph)
    last_asset = sorted(graph.catalog_refs.values())[0]
    fake = encode_snapshot_cursor(scope=scope, snapshot="x", last=last_asset)
    with pytest.raises(SpatialDataDomainError) as malformed:
        graph.discovery.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=graph.ai,
            limit=1,
            cursor=fake,
            now=NOW,
        )
    assert (malformed.value.reason, malformed.value.status_code) == (
        "INVALID_REQUEST_BOUNDS",
        422,
    )
    lane = ai_lane(tmp_path / "jobs", issue_job=True)
    assert lane.ai_view is not None
    job_scope = _real_scope(lane)
    fake_job = encode_snapshot_cursor(
        scope=job_scope, snapshot="not-a-digest", last=lane.ai_view.job_id
    )
    with pytest.raises(SpatialDataDomainError) as malformed_job:
        lane.ai_store.list(
            site_id="site-1",
            work_area_id=lane.area.work_area_id,
            principal=lane.ai,
            cursor=fake_job,
            limit=8,
            now=NOW,
        )
    assert (malformed_job.value.reason, malformed_job.value.status_code) == (
        "INVALID_REQUEST_BOUNDS",
        422,
    )


def test_fix4_snapshot_cursor_negative_matrix(tmp_path: Path) -> None:
    """Direct negative matrix over the shared cursor parser on the asset path."""
    import json as jsonlib

    from ksi_core.domains.external.delivery.asset_discovery import (
        decode_snapshot_cursor,
        encode_snapshot_cursor,
    )
    from ksi_core.domains.external.delivery.errors import (
        SpatialDataAiDomainError,
        SpatialDataDomainError,
    )

    graph = two_asset_lane(tmp_path)
    scope = _real_scope(graph)
    last_asset = sorted(graph.catalog_refs.values())[0]
    good_snapshot = "sha256:" + "0" * 64
    good = encode_snapshot_cursor(scope=scope, snapshot=good_snapshot, last=last_asset)

    def raw(payload: bytes) -> str:
        return _b64_raw(payload)

    def obj(**fields) -> str:
        return raw(jsonlib.dumps(fields, sort_keys=True, separators=(",", ":")).encode())

    foreign = "sha256:" + "f" * 64
    assert foreign != scope
    cases = {
        "duplicate-key": raw(
            b'{"scope":"'
            + scope.encode()
            + b'","snapshot":"x","snapshot":"y","last":"'
            + last_asset.encode()
            + b'"}'
        ),
        "extra-field": obj(scope=scope, snapshot=good_snapshot, last=last_asset, extra=1),
        "nonfinite": raw(
            b'{"scope":"'
            + scope.encode()
            + b'","snapshot":"'
            + good_snapshot.encode()
            + b'","last":NaN}'
        ),
        "bool-last": obj(scope=scope, snapshot=good_snapshot, last=True),
        "int-last": obj(scope=scope, snapshot=good_snapshot, last=5),
        "empty-last": obj(scope=scope, snapshot=good_snapshot, last=""),
        "empty-snapshot": obj(scope=scope, snapshot="", last=last_asset),
        "oversized-cursor": "A" * 2049,
        "oversized-snapshot": obj(scope=scope, snapshot="s" * 257, last=last_asset),
        "oversized-last": obj(scope=scope, snapshot=good_snapshot, last="l" * 513),
        "bad-padding": good[:-2] + ("##" if not good.endswith("##") else "@@"),
        "noncanonical-spacing": raw(
            jsonlib.dumps(
                {"scope": scope, "snapshot": good_snapshot, "last": last_asset},
                sort_keys=True,
                separators=(", ", ": "),
            ).encode()
        ),
        "noncanonical-order": raw(
            b'{"snapshot":"'
            + good_snapshot.encode()
            + b'","scope":"'
            + scope.encode()
            + b'","last":"'
            + last_asset.encode()
            + b'"}'
        ),
        "foreign-scope": obj(scope=foreign, snapshot=good_snapshot, last=last_asset),
        "lexical-snapshot": obj(scope=scope, snapshot="x", last=last_asset),
        "short-hex-snapshot": obj(scope=scope, snapshot="sha256:" + "0" * 63, last=last_asset),
        "long-hex-snapshot": obj(scope=scope, snapshot="sha256:" + "0" * 65, last=last_asset),
        "upper-hex-snapshot": obj(scope=scope, snapshot="sha256:" + "A" * 64, last=last_asset),
        "bare-hex-snapshot": obj(scope=scope, snapshot="0" * 64, last=last_asset),
        "lexical-scope": obj(scope="x", snapshot=good_snapshot, last=last_asset),
        "empty-string": "",
        "not-b64": "not-a-cursor!!!",
    }
    for name, bad in cases.items():
        with pytest.raises(SpatialDataDomainError) as failure:
            decode_snapshot_cursor(bad, scope=scope)
        assert (failure.value.reason, failure.value.status_code) == (
            "INVALID_REQUEST_BOUNDS",
            422,
        ), name
    # A well-formed but different digest is stale (409), never malformed.
    with pytest.raises(SpatialDataAiDomainError) as stale:
        graph.discovery.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=graph.ai,
            limit=1,
            cursor=obj(scope=scope, snapshot=good_snapshot, last=last_asset),
            now=NOW,
        )
    assert (stale.value.reason, stale.value.status_code) == ("SPATIAL_DATA_CURSOR_STALE", 409)
    # A canonical cursor naming an unknown ordered last is rejected by
    # membership: the live snapshot still matches, so the unknown last is 422.
    import base64 as _base64

    page = graph.discovery.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        limit=1,
        cursor=None,
        now=NOW,
    )
    assert page.next_cursor is not None
    live = jsonlib.loads(
        _base64.b64decode(page.next_cursor.encode("ascii"), altchars=b"-_", validate=True)
    )
    live["last"] = "ksa-v1-" + "9" * 64
    smuggled = _b64_raw(jsonlib.dumps(live, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(SpatialDataDomainError) as unknown:
        graph.discovery.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=graph.ai,
            limit=1,
            cursor=smuggled,
            now=NOW,
        )
    assert (unknown.value.reason, unknown.value.status_code) == (
        "INVALID_REQUEST_BOUNDS",
        422,
    )


def _journal_sizes(path: Path) -> dict[str, int]:
    return {p.name: p.stat().st_size for p in sorted(path.glob("*.jsonl"))}


def test_fix4_ai_job_pages_filter_stable_and_invalidate(tmp_path: Path) -> None:
    """AI job list: GENERAL filtered, 2-page stable IDs, mutations invalidate cursors."""
    from ksi_core.domains.external.delivery.errors import (
        SpatialDataAiDomainError,
        SpatialDataDomainError,
    )
    from ksi_event_contracts.spatial_data import SpatialDataRequestV1
    from test_spatial_data_ai_egress import ai_lane

    lane = ai_lane(tmp_path)
    assert lane.ai_view is not None
    measurements = lane.source.inspection.measurements
    assert measurements is not None
    second = lane.ai_store.issue(
        site_id="site-1",
        work_area_id=lane.area.work_area_id,
        request=SpatialDataRequestV1(
            asset_ref=lane.source.asset_ref,
            requested_bounds=(0, 0, 1, 1),
            observed_crs_digest=measurements.observed_crs_digest,
            resolution_mode="NATIVE",
            purpose="EXTERNAL_AI",
        ),
        principal=lane.ai,
        idempotency_key="ai-two",
        now=NOW,
    )
    call = dict(
        site_id="site-1",
        work_area_id=lane.area.work_area_id,
        principal=lane.ai,
        limit=8,
        cursor=None,
    )
    full = lane.ai_store.list(now=NOW, **call)
    assert [item.job_id for item in full.items] == sorted([lane.ai_view.job_id, second.job_id])
    assert lane.ai_store.list(now=NOW, **call).model_dump() == full.model_dump()
    # Stable two-page traversal in job-ID order.
    first = lane.ai_store.list(now=NOW, **{**call, "limit": 1})
    assert len(first.items) == 1 and first.next_cursor is not None
    rest = lane.ai_store.list(now=NOW, **{**call, "limit": 1, "cursor": first.next_cursor})
    assert [item.job_id for item in rest.items] == sorted([lane.ai_view.job_id, second.job_id])[1:]
    assert rest.next_cursor is None
    assert [item.job_id for item in lane.ai_store.list(now=NOW, **{**call, "limit": 1}).items] == [
        item.job_id for item in first.items
    ]
    cursor = first.next_cursor
    # Cancelling one job stales outstanding cursors; the canceled job stays
    # visible under its new state (history preserved, snapshot binds state).
    lane.ai_store.cancel(job_id=second.job_id, principal=lane.ai, now=NOW)
    with pytest.raises(SpatialDataAiDomainError) as cancelled:
        lane.ai_store.list(now=NOW, **{**call, "limit": 1, "cursor": cursor})
    assert (cancelled.value.reason, cancelled.value.status_code) == (
        "SPATIAL_DATA_CURSOR_STALE",
        409,
    )
    survived = lane.ai_store.list(now=NOW, **call)
    assert [item.job_id for item in survived.items] == sorted([lane.ai_view.job_id, second.job_id])
    assert survived.model_dump() != full.model_dump()
    # Revoking the single shared grant filters every job it authorized.
    from test_spatial_data_ai_egress import revoke

    revoke(lane)
    with pytest.raises(SpatialDataAiDomainError) as stale:
        lane.ai_store.list(now=NOW, **{**call, "limit": 1, "cursor": cursor})
    assert (stale.value.reason, stale.value.status_code) == ("SPATIAL_DATA_CURSOR_STALE", 409)
    assert lane.ai_store.list(now=NOW, **call).items == ()
    # A replacement grant cannot resurrect the revoked jobs.
    revoked = lane.ai_grant
    replacement = revoked.model_copy(
        update={"revision": 2, "grant_digest": None, "allowed_bounds": (0, 0, 1, 1)}
    ).sealed()
    lane.grants.provision(replacement)
    with pytest.raises(SpatialDataDomainError) as buried:
        lane.ai_store.get(job_id=lane.ai_view.job_id, principal=lane.ai, now=NOW)
    assert (buried.value.reason, buried.value.status_code) == ("ACCESS_REVOKED", 403)
    assert lane.ai_store.list(now=NOW, **call).items == ()
    with pytest.raises(SpatialDataAiDomainError) as still_stale:
        lane.ai_store.list(now=NOW, **{**call, "limit": 1, "cursor": cursor})
    assert still_stale.value.status_code == 409


def test_fix4_ai_job_cursor_negatives_and_quiescence(tmp_path: Path) -> None:
    """AI job cursor matrix + error paths mutate no journals."""
    import json as jsonlib

    from ksi_core.domains.external.delivery.errors import (
        SpatialDataAiDomainError,
        SpatialDataDomainError,
    )
    from test_spatial_data_ai_egress import ai_lane

    lane = ai_lane(tmp_path)
    assert lane.ai_view is not None
    scope = _real_scope(lane)
    job_id = lane.ai_view.job_id
    call = dict(
        site_id="site-1",
        work_area_id=lane.area.work_area_id,
        principal=lane.ai,
        limit=8,
    )
    good_snapshot = "sha256:" + "0" * 64

    def obj(**fields) -> str:
        return _b64_raw(jsonlib.dumps(fields, sort_keys=True, separators=(",", ":")).encode())

    for name, bad in {
        "lexical-snapshot": obj(scope=scope, snapshot="x", last=job_id),
        "short-hex": obj(scope=scope, snapshot="sha256:" + "0" * 63, last=job_id),
        "bare-hex": obj(scope=scope, snapshot="0" * 64, last=job_id),
        "bool-last": obj(scope=scope, snapshot=good_snapshot, last=True),
        "empty-last": obj(scope=scope, snapshot=good_snapshot, last=""),
        "oversized-last": obj(scope=scope, snapshot=good_snapshot, last="l" * 513),
        "bad-padding": "!!!not-b64!!!",
        "noncanonical": _b64_raw(b'{"last":"x","scope":"y","snapshot":"z"}'),
        "foreign-scope": obj(scope="sha256:" + "f" * 64, snapshot=good_snapshot, last=job_id),
    }.items():
        with pytest.raises(SpatialDataDomainError) as failure:
            lane.ai_store.list(cursor=bad, now=NOW, **call)
        assert (failure.value.reason, failure.value.status_code) == (
            "INVALID_REQUEST_BOUNDS",
            422,
        ), name
    for bad_limit in (0, -1, 201):
        with pytest.raises(SpatialDataDomainError) as failure:
            lane.ai_store.list(
                cursor=None,
                limit=bad_limit,
                now=NOW,
                **{k: v for k, v in call.items() if k != "limit"},
            )
        assert failure.value.status_code == 422
    with pytest.raises(SpatialDataDomainError) as unknown:
        lane.ai_store.get(job_id="no-such-job", principal=lane.ai, now=NOW)
    assert (unknown.value.reason, unknown.value.status_code) == ("NOT_FOUND", 404)
    with pytest.raises(SpatialDataAiDomainError) as stale:
        lane.ai_store.list(
            cursor=obj(scope=scope, snapshot=good_snapshot, last=job_id),
            now=NOW,
            **call,
        )
    assert (stale.value.reason, stale.value.status_code) == ("SPATIAL_DATA_CURSOR_STALE", 409)
    # Error and denied paths mutate no journals and no audit attempts.
    before_sizes = _journal_sizes(tmp_path)
    before_audit = lane.ai_audit.count
    for probe in (
        lambda: lane.ai_store.list(cursor="junk!!!", now=NOW, **call),
        lambda: lane.ai_store.list(
            cursor=obj(scope=scope, snapshot="bogus", last=job_id), now=NOW, **call
        ),
        lambda: lane.ai_store.list(
            cursor=None, limit=0, now=NOW, **{k: v for k, v in call.items() if k != "limit"}
        ),
        lambda: lane.ai_store.get(job_id="no-such-job", principal=lane.ai, now=NOW),
    ):
        with pytest.raises((SpatialDataDomainError, SpatialDataAiDomainError)):
            probe()
    assert _journal_sizes(tmp_path) == before_sizes
    assert lane.ai_audit.count == before_audit
    assert [
        item.job_id
        for item in lane.ai_store.list(
            cursor=None, now=NOW, **{k: v for k, v in call.items()}
        ).items
    ] == [job_id]


def test_fix4_ai_job_general_never_leaks_onto_ai_page(tmp_path: Path) -> None:
    """A GENERAL job in the same scope is filtered before AI pagination, never leaked."""
    from spatial_data_job_fixture import issue
    from test_spatial_data_ai_egress import ai_lane

    lane = ai_lane(tmp_path)
    assert lane.ai_view is not None
    call = dict(
        site_id="site-1",
        work_area_id=lane.area.work_area_id,
        principal=lane.ai,
        limit=8,
        cursor=None,
    )
    generic = issue(lane.ai_store, lane, key="generic-fix4")
    page = lane.ai_store.list(now=NOW, **call)
    assert [item.job_id for item in page.items] == [lane.ai_view.job_id]
    assert generic.job_id not in {item.job_id for item in page.items}
    # The generic job remains history for its own requester, not AI metadata.
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    with pytest.raises(SpatialDataDomainError) as denied:
        lane.ai_store.get(job_id=generic.job_id, principal=lane.ai, now=NOW)
    assert (denied.value.reason, denied.value.status_code) == ("NOT_FOUND", 404)
    survived = lane.ai_store.get(job_id=generic.job_id, principal=lane.principal, now=NOW)
    assert survived.job_id == generic.job_id
