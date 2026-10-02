"""Current rights gate using real Site and grant journals; not source-inspection proof."""

from contextlib import ExitStack, closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.grants import SpatialDataGrantStore
from ksi_core.domains.sites.sites import SiteStore
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import PrincipalKind, Role
from ksi_event_contracts.processing_job import DataResidency, ExecutionLocus
from ksi_geo_spatial.external_native_window_geometry import plan_external_native_window
from ksi_mission_contracts.models import SiteFrame
from spatial_data_fixture import (
    NOW,
    make_grant,
    make_policy,
    make_revocation,
    make_source,
)
from test_spatial_data_permissions import data_client


def graph(
    tmp_path: Path,
    *,
    consent: bool = False,
    egress: bool | None = None,
    location: ExecutionLocus = ExecutionLocus.SITE_ONPREM,
    register: bool = True,
) -> Any:
    from ksi_core.domains.external.delivery.grants import SpatialDataGrantAuthorizer

    stack = ExitStack()
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    journal = stack.enter_context(closing(DurableJournal(tmp_path / "grants.jsonl")))
    site_journal = stack.enter_context(closing(DurableJournal(tmp_path / "sites.jsonl")))
    sites = SiteStore(site_journal, coordinator=coordinator)
    if register:
        result = sites.register(
            "site-local",
            "Local",
            SiteFrame(
                crs="EPSG:7850", vertical_datum="UNKNOWN", unit="meter", transform_version="v1"
            ),
            data_residency=None
            if egress is None
            else DataResidency(egress_allowed=egress, jurisdiction="local"),
            ai_egress_allowed=consent,
            organization_id="org-local",
            actor="owner",
            now=NOW,
        )
        assert result.record is not None
    grants = SpatialDataGrantStore(journal, coordinator=coordinator)
    authorizer = SpatialDataGrantAuthorizer(
        grants=grants, sites=sites, processing_location=location
    )
    return stack, grants, authorizer, sites, site_journal


def arguments(**changes: Any) -> dict[str, Any]:
    source = make_source()
    assert source.inspection.measurements is not None
    bounds = (0.1, 8.1, 0.9, 8.9)
    geometry = plan_external_native_window(
        requested_bounds=bounds,
        measurements=source.inspection.measurements,
        requested_crs_digest=source.inspection.measurements.observed_crs_digest,
    )
    args = dict(
        grant_id="local-grant",
        revision=1,
        source=source,
        principal=data_client(),
        purpose="GENERAL_DATA_USE",
        requested_bounds=bounds,
        geometry=geometry,
        operation="PREPARE",
        policy=make_policy(),
        now=NOW,
    )
    args.update(changes)
    return args


def expect_denied(authorizer: Any, reason: str, status: int = 403, **changes: Any) -> None:
    with pytest.raises(SpatialDataDomainError) as error:
        authorizer.require_current(**arguments(**changes))
    assert (error.value.reason, error.value.status_code) == (reason, status)


def test_expanded_cells_need_explicit_rights_even_when_request_is_inside(tmp_path: Path) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        grants.provision(make_grant(allowed_bounds=(0.1, 8.1, 0.9, 8.9)))
        assert arguments()["geometry"].actual_bounds == (0, 8, 1, 9)
        expect_denied(authorizer, "OUTPUT_OUTSIDE_GRANT")


def test_exact_pixel_edges_are_authorized_without_a_neighbor_or_tolerance(tmp_path: Path) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        grant = make_grant(allowed_bounds=(0, 8, 1, 9))
        grants.provision(grant)
        assert authorizer.require_current(**arguments()) == grant
        measurements = make_source().inspection.measurements
        assert measurements is not None
        expect_denied(
            authorizer,
            "OUTPUT_OUTSIDE_GRANT",
            requested_bounds=(0.1, 7.9, 0.9, 8.9),
            geometry=plan_external_native_window(
                requested_bounds=(0.1, 7.9, 0.9, 8.9),
                measurements=measurements,
                requested_crs_digest=measurements.observed_crs_digest,
            ),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"organization_id": "foreign"},
        {"allowed_site_ids": frozenset()},
        {"allowed_work_area_ids": frozenset({"other"})},
        {"principal_id": "different-beneficiary"},
    ],
)
def test_unavailable_scope_and_foreign_beneficiary_match_unknown_grant(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        grants.provision(make_grant())
        expect_denied(authorizer, "NOT_FOUND", 404, principal=replace(data_client(), **changes))
        expect_denied(authorizer, "NOT_FOUND", 404, grant_id="unknown")


def test_scoped_admin_cannot_self_grant_or_act_for_the_beneficiary(tmp_path: Path) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        grants.provision(make_grant())
        admin = replace(
            data_client(), principal_id="admin", kind=PrincipalKind.OPERATOR, role=Role.ADMIN
        )
        expect_denied(authorizer, "NOT_FOUND", 404, principal=admin)


@pytest.mark.parametrize("operation", ["PREPARE", "READ"])
def test_revocation_closes_every_operation_but_keeps_history(
    tmp_path: Path, operation: str
) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        grants.provision(make_grant())
        grants.revoke(make_revocation())
        grants.provision(make_grant(revision=2))
        expect_denied(authorizer, "ACCESS_REVOKED", operation=operation)
        assert (
            grants.historical_grant(organization_id="org-local", grant_id="local-grant", revision=1)
            == make_grant()
        )
        assert (
            authorizer.require_current(**arguments(revision=2, operation=operation)).revision == 2
        )


@pytest.mark.parametrize("time", [NOW - timedelta(microseconds=1), NOW + timedelta(hours=1)])
def test_grant_interval_is_half_open(tmp_path: Path, time: Any) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        grants.provision(make_grant())
        expect_denied(authorizer, "ACCESS_EXPIRED", now=time)


@pytest.mark.parametrize(
    "consent,egress,allowed", [(False, True, False), (True, False, True), (True, None, True)]
)
def test_ai_consent_is_separate_from_generic_egress(
    tmp_path: Path, consent: bool, egress: bool | None, allowed: bool
) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path, consent=consent, egress=egress)
    with stack:
        grants.provision(make_grant(purposes=("GENERAL_DATA_USE", "EXTERNAL_AI")))
        if allowed:
            assert (
                authorizer.require_current(**arguments(purpose="EXTERNAL_AI")).grant_id
                == "local-grant"
            )
        else:
            expect_denied(authorizer, "AI_EGRESS_DENIED", purpose="EXTERNAL_AI")
        assert authorizer.require_current(**arguments()).grant_id == "local-grant"


@pytest.mark.parametrize("location", [ExecutionLocus.VENDOR_CLOUD, ExecutionLocus.KSI_SERVER_GPU])
@pytest.mark.parametrize("egress", [None, False, True])
def test_offsite_preparation_requires_explicit_site_egress(
    tmp_path: Path, location: ExecutionLocus, egress: bool | None
) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path, location=location, egress=egress)
    with stack:
        grants.provision(make_grant(processing_location=location))
        if egress:
            assert authorizer.require_current(**arguments()).processing_location == location
        else:
            expect_denied(authorizer, "PROCESSING_LOCATION_DENIED")


def test_grant_location_cannot_override_configured_worker_location(tmp_path: Path) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path, egress=True)
    with stack:
        grants.provision(make_grant(processing_location=ExecutionLocus.VENDOR_CLOUD))
        expect_denied(authorizer, "PROCESSING_LOCATION_DENIED")


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("operations", ("READ",), "PERMISSION_DENIED"),
        ("purposes", ("EXTERNAL_AI",), "PERMISSION_DENIED"),
        ("policy_digest", "sha256:" + "0" * 64, "POLICY_UNAVAILABLE"),
        ("observed_crs_digest", "sha256:" + "0" * 64, "CRS_MISMATCH"),
    ],
)
def test_rights_policy_and_crs_are_independent_checks(
    tmp_path: Path, field: str, value: Any, reason: str
) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        grants.provision(make_grant(**{field: value}))
        expect_denied(authorizer, reason, 503 if reason == "POLICY_UNAVAILABLE" else 403)


def test_geometry_is_recomputed_not_trusted_as_a_small_authorized_bbox(tmp_path: Path) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        grants.provision(make_grant())
        geometry = replace(arguments()["geometry"], actual_bounds=(0.1, 8.1, 0.9, 8.9))
        expect_denied(authorizer, "SOURCE_MEASUREMENTS_MISMATCH", 409, geometry=geometry)


def test_viewer_can_read_but_cannot_prepare_even_with_explicit_grant(tmp_path: Path) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        grants.provision(make_grant())
        viewer = replace(data_client(), kind=PrincipalKind.OPERATOR, role=Role.VIEWER)
        expect_denied(authorizer, "PERMISSION_DENIED", principal=viewer)
        assert (
            authorizer.require_current(**arguments(principal=viewer, operation="READ"))
            == make_grant()
        )


def test_missing_or_unavailable_site_dependency_never_authorizes(tmp_path: Path) -> None:
    stack, grants, authorizer, sites, site_journal = graph(tmp_path, register=False)
    with stack:
        grants.provision(make_grant())
        expect_denied(authorizer, "NOT_FOUND", 404)
        site_journal.close()
        expect_denied(authorizer, "CURRENTNESS_UNAVAILABLE", 503)


def test_authorizer_refuses_different_participant_coordinators(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.grants import SpatialDataGrantAuthorizer

    stack, grants, _, _, _ = graph(tmp_path)
    with (
        stack,
        closing(DurableJournal(tmp_path / "other-sites.jsonl")) as journal,
        pytest.raises(ValueError),
    ):
        SpatialDataGrantAuthorizer(
            grants=grants, sites=SiteStore(journal), processing_location=ExecutionLocus.SITE_ONPREM
        )


def test_first_admission_requires_one_applicable_grant_and_never_picks_latest(
    tmp_path: Path,
) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        args = arguments()
        del args["grant_id"], args["revision"]
        with pytest.raises(SpatialDataDomainError) as error:
            authorizer.select_current(**args)
        assert error.value.reason == "GRANT_REQUIRED"
        grants.provision(make_grant())
        assert authorizer.select_current(**args) == make_grant()
        grants.provision(make_grant(revision=2))
        with pytest.raises(SpatialDataDomainError) as error:
            authorizer.select_current(**args)
        assert error.value.reason == "AMBIGUOUS_GRANT"
        grants.revoke(make_revocation())
        assert authorizer.select_current(**args).revision == 2


def test_current_grant_selection_refuses_an_over_budget_history(tmp_path: Path) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        for revision in range(1, 10):
            grants.provision(make_grant(revision=revision))
        args = arguments()
        del args["grant_id"], args["revision"]
        with pytest.raises(SpatialDataDomainError) as error:
            authorizer.select_current(**args)
        assert (error.value.reason, error.value.status_code) == ("RESOURCE_LIMIT_EXCEEDED", 503)


def test_closed_grant_journal_cannot_authorize_from_cached_projection(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.grants import SpatialDataGrantAuthorizer

    stack, _, _, sites, _ = graph(tmp_path)
    with stack, closing(DurableJournal(tmp_path / "separate-grants.jsonl")) as journal:
        grants = SpatialDataGrantStore(journal, coordinator=sites.coordinator)
        authorizer = SpatialDataGrantAuthorizer(
            grants=grants, sites=sites, processing_location=ExecutionLocus.SITE_ONPREM
        )
        grants.provision(make_grant())
        journal.close()
        expect_denied(authorizer, "CURRENTNESS_UNAVAILABLE", 503)


@pytest.mark.parametrize("revision", [True, "1", 1.0])
def test_coerced_grant_revision_cannot_select_an_exact_revision(
    tmp_path: Path, revision: Any
) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        grants.provision(make_grant())
        expect_denied(authorizer, "NOT_FOUND", 404, revision=revision)


@pytest.mark.parametrize(
    "field,value",
    [
        ("asset_ref", "ksa-v1-" + "0" * 64),
        ("site_id", "other-site"),
        ("work_area_id", "other-area"),
    ],
)
def test_grant_names_and_asset_identity_cannot_be_substituted(
    tmp_path: Path, field: str, value: Any
) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        grants.provision(make_grant(**{field: value}))
        expect_denied(authorizer, "NOT_FOUND", 404)


@pytest.mark.parametrize(
    "snapshot,reason", [("source", "SOURCE_UNAVAILABLE"), ("policy", "POLICY_UNAVAILABLE")]
)
@pytest.mark.parametrize("tamper", [False, True])
def test_unsealed_or_copy_tampered_snapshots_fail_closed(
    tmp_path: Path, snapshot: str, reason: str, tamper: Any
) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        grants.provision(make_grant())
        record = make_source() if snapshot == "source" else make_policy()
        field = "declaration_recorded_at" if snapshot == "source" else "max_attempts"
        value = NOW + timedelta(seconds=1) if snapshot == "source" else 2
        update = {field: value} if tamper else {snapshot + "_digest": None}
        expect_denied(authorizer, reason, 503, **{snapshot: record.model_copy(update=update)})


def test_reopened_authority_keeps_revoked_exact_identity_and_expired_history(
    tmp_path: Path,
) -> None:
    stack, grants, authorizer, _, _ = graph(tmp_path)
    with stack:
        grants.provision(make_grant())
        assert authorizer.require_current(**arguments()) == make_grant()
        grants.revoke(make_revocation())
        grants.provision(make_grant(revision=2))
    stack, grants, authorizer, _, _ = graph(tmp_path, register=False)
    with stack:
        expect_denied(authorizer, "ACCESS_REVOKED")
        expect_denied(authorizer, "ACCESS_EXPIRED", revision=2, now=NOW + timedelta(hours=1))
        assert (
            grants.historical_grant(organization_id="org-local", grant_id="local-grant", revision=1)
            == make_grant()
        )
