"""Authentic retained source admission is independent of catalog metadata and grant history."""

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import NoReturn

import pytest
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_domain.canonical_json import canonical_json_bytes
from spatial_data_source_fixture import source_identity, source_resolver, source_stores
from support.external_artifact_inspection_fixtures import NOW


def test_source_is_exact_sealed_retained_measurement_and_six_field_boundary(tmp_path: Path) -> None:
    """A metadata-only projection, inferred CRS or fabricated area revision cannot satisfy this."""
    stores = source_stores(tmp_path)
    resolver = source_resolver(stores)
    source = resolver.resolve(
        site_id="site-1",
        work_area_id=stores.area.work_area_id,
        asset_ref=source_identity(stores),
        principal=stores.principal,
    )
    assert source.sealed_subject == stores.subject
    assert source.inspection == stores.accepted_report.measurement_payload.outcomes[0]
    assert source.inspection_report_digest == stores.accepted_report.report_digest
    assert source.observed_sha256 == "sha256:" + "c" * 64
    assert source.observed_size_bytes == 12
    assert source.observed_crs_units == "metre"
    area = stores.area.model_dump(by_alias=True, mode="json")
    expected = {
        name: area[name]
        for name in ("workAreaId", "siteId", "crs", "polygon", "createdAt", "supersedes")
    }
    assert (
        source.work_area_boundary_digest
        == "sha256:" + hashlib.sha256(canonical_json_bytes(expected)).hexdigest()
    )
    assert source.source_digest == source.canonical_digest()
    assert not any(
        key in source.model_dump_json() for key in ("objectKey", "downloadUrl", "uploadUrl")
    )
    with stores.coordinator.guarded_read():
        assert (
            resolver.require_current(source=source, principal=stores.principal, now=NOW) == source
        )


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"sealed": False}, "SOURCE_UNSEALED"),
        ({"measured": False}, "SOURCE_NOT_MEASURED"),
        ({"rejected": True}, "SOURCE_NOT_MEASURED"),
    ],
)
def test_source_refuses_absent_unsealed_or_rejected_evidence(
    tmp_path: Path, kwargs: dict, reason: str
) -> None:
    """A declared GeoTIFF or public catalog status is not an accepted measurement report."""
    stores = source_stores(tmp_path, **kwargs)
    resolver = source_resolver(stores)
    with pytest.raises(SpatialDataDomainError) as error:
        resolver.resolve(
            site_id="site-1",
            work_area_id=stores.area.work_area_id,
            asset_ref=source_identity(stores),
            principal=stores.principal,
        )
    assert error.value.reason == reason


@pytest.mark.parametrize(
    "update",
    [
        {"organization_id": "other"},
        {"allowed_site_ids": frozenset({"other"})},
        {"allowed_work_area_ids": frozenset({"other"})},
    ],
)
def test_source_foreign_scope_is_indistinguishable_not_found(tmp_path: Path, update: dict) -> None:
    """Foreign scope must be refused before exposing whether source/inspection exists."""
    stores = source_stores(tmp_path)
    resolver = source_resolver(stores)
    principal = replace(stores.principal, **update)
    for asset in (source_identity(stores), "ksa-v1-" + "f" * 64):
        with pytest.raises(SpatialDataDomainError) as error:
            resolver.resolve(
                site_id="site-1",
                work_area_id=stores.area.work_area_id,
                asset_ref=asset,
                principal=principal,
            )
        assert (error.value.reason, error.value.status_code) == ("NOT_FOUND", 404)


def test_source_rechecks_withdrawal_without_rewriting_frozen_history(tmp_path: Path) -> None:
    """A retained valid source digest does not authorize preparation after policy withdrawal."""
    stores = source_stores(tmp_path)
    resolver = source_resolver(stores)
    source = resolver.resolve(
        site_id="site-1",
        work_area_id=stores.area.work_area_id,
        asset_ref=source_identity(stores),
        principal=stores.principal,
    )
    with stores.coordinator.mutation():
        stores.authority._records.clear()  # noqa: SLF001
    with pytest.raises(SpatialDataDomainError) as error:
        resolver.require_current(source=source, principal=stores.principal, now=NOW)
    assert error.value.reason == "CURRENTNESS_UNAVAILABLE"
    assert (
        stores.inspections.historical_report(
            stores.subject,
            report_digest=source.inspection_report_digest,
            policy_digest=stores.accepted_report.inspection_policy_digest,
        )
        == stores.accepted_report
    )


def test_source_requires_identical_coordinator_participants(tmp_path: Path) -> None:
    """Independently locked Core participants cannot make an atomic authority decision."""
    stores = source_stores(tmp_path)
    stores.work_areas._coordinator = ExternalAuthorityCurrentnessCoordinator()  # noqa: SLF001
    with pytest.raises(ValueError):
        source_resolver(stores)


def test_archived_area_and_superseded_exact_revision_keep_original_source(tmp_path: Path) -> None:
    """Archive/latest status is not permission to substitute another geometry or input revision."""
    stores = source_stores(tmp_path)
    resolver = source_resolver(stores)
    asset = source_identity(stores)
    source = resolver.resolve(
        site_id="site-1",
        work_area_id=stores.area.work_area_id,
        asset_ref=asset,
        principal=stores.principal,
    )
    archived = stores.work_areas.archive(
        stores.area.work_area_id, site_id="site-1", actor="operator-1", now=NOW
    )
    assert archived.work_area.status == "ARCHIVED"
    newer = stores.record.submission.model_copy(
        update={"revision": 2, "submission_digest": None}
    ).sealed()
    assert (
        stores.reconstruction.register(
            newer, work_order=stores.order, registered_by="operator-1", now=NOW
        ).revision.submission.revision
        == 2
    )
    assert (
        resolver.resolve(
            site_id="site-1",
            work_area_id=stores.area.work_area_id,
            asset_ref=asset,
            principal=stores.principal,
        )
        == source
    )
    from ksi_core.domains.external.delivery.source import work_area_boundary_digest

    renamed = stores.area.model_copy(update={"name": "new label"})
    assert work_area_boundary_digest(renamed) == source.work_area_boundary_digest
    assert work_area_boundary_digest(archived.work_area) == source.work_area_boundary_digest


@pytest.mark.parametrize(
    "field,value",
    [
        ("observed_size_bytes", 13),
        ("inspector_build_digest", "sha256:" + "f" * 64),
        ("work_area_boundary_digest", "sha256:" + "f" * 64),
        ("observed_crs_units", "degree"),
        ("epoch_id", "other-epoch"),
        ("submission_ref", "other-ref"),
    ],
)
def test_resealed_fabricated_source_cannot_replace_core_snapshot(
    tmp_path: Path, field: str, value: object
) -> None:
    """Model/digest validity alone must not authenticate caller-created source facts."""
    stores = source_stores(tmp_path)
    resolver = source_resolver(stores)
    source = resolver.resolve(
        site_id="site-1",
        work_area_id=stores.area.work_area_id,
        asset_ref=source_identity(stores),
        principal=stores.principal,
    )
    forged = source.model_copy(update={field: value, "source_digest": None}).sealed()
    with pytest.raises(SpatialDataDomainError) as error:
        resolver.require_current(source=forged, principal=stores.principal, now=NOW)
    assert error.value.reason == "SOURCE_MEASUREMENTS_MISMATCH"


def test_exact_sealed_subject_resolution_does_not_iterate_revision_history(tmp_path: Path) -> None:
    """Final check-and-commit cannot walk unbounded historical revisions under the coordinator."""
    stores = source_stores(tmp_path)

    class NoIteration(list):
        def __iter__(self) -> NoReturn:
            pytest.fail("exact subject resolution traversed revision history")

    key = (stores.subject.work_order_id, stores.subject.submission_id)
    stores.reconstruction._streams[key] = NoIteration(stores.reconstruction._streams[key])  # noqa: SLF001
    assert stores.reconstruction.resolve_sealed_subject(stores.subject) == stores.record


def test_current_source_recheck_enforces_snapshot_budget_too(tmp_path: Path) -> None:
    """A supplied frozen source cannot bypass the current resolver's representation budget."""
    stores = source_stores(tmp_path)
    source = source_resolver(stores).resolve(
        site_id="site-1",
        work_area_id=stores.area.work_area_id,
        asset_ref=source_identity(stores),
        principal=stores.principal,
    )
    from spatial_data_fixture import make_policy

    stores.data_policy = make_policy(max_snapshot_bytes=512, max_json_bytes=512)
    restricted = source_resolver(stores)
    with pytest.raises(SpatialDataDomainError) as error:
        restricted.require_current(source=source, principal=stores.principal, now=NOW)
    assert error.value.reason == "RESOURCE_LIMIT_EXCEEDED"


def test_foreign_source_recheck_is_not_found_before_budget_details(tmp_path: Path) -> None:
    """Representation limits must not disclose details of a foreign valid frozen source."""
    stores = source_stores(tmp_path)
    source = source_resolver(stores).resolve(
        site_id="site-1",
        work_area_id=stores.area.work_area_id,
        asset_ref=source_identity(stores),
        principal=stores.principal,
    )
    from spatial_data_fixture import make_policy

    stores.data_policy = make_policy(max_snapshot_bytes=512, max_json_bytes=512)
    with pytest.raises(SpatialDataDomainError) as error:
        source_resolver(stores).require_current(
            source=source, principal=replace(stores.principal, organization_id="other"), now=NOW
        )
    assert (error.value.reason, error.value.status_code) == ("NOT_FOUND", 404)


def test_source_resolution_replays_every_real_participant_without_new_events(
    tmp_path: Path,
) -> None:
    """An absent replay index must not authorize a different input after restart."""
    from spatial_data_source_fixture import restart_source_stores

    stores = source_stores(tmp_path)
    source = source_resolver(stores).resolve(
        site_id="site-1",
        work_area_id=stores.area.work_area_id,
        asset_ref=source_identity(stores),
        principal=stores.principal,
    )
    before = {path.name: path.read_bytes() for path in tmp_path.glob("*.jsonl")}
    replayed = restart_source_stores(stores, tmp_path)
    assert (
        source_resolver(replayed).resolve(
            site_id="site-1",
            work_area_id=stores.area.work_area_id,
            asset_ref=source.asset_ref,
            principal=stores.principal,
        )
        == source
    )
    assert {path.name: path.read_bytes() for path in tmp_path.glob("*.jsonl")} == before
