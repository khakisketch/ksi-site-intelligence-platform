"""Site-level civil readiness is a read-only explanation of existing gates.

The tests intentionally reuse real succeeded ProcessingJob fixtures.  A list
of job IDs or a UI-only count would be too weak here: REQ-INT-104 requires the
same preflight that protects an actual quantitative request.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import mount_auth
from ksi_core.civil_preflight import CivilPreflightReason
from ksi_core.civil_readiness import (
    CivilDesignSurfaceStatus,
    CivilReadinessProjector,
    CivilReadinessReason,
    CivilReadinessStatus,
    mount_civil_readiness,
)
from ksi_event_contracts.design_surface import DesignSurfaceStatus
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

# Keep real ProcessingJob issue/lease/artifact/verified-source-media/SUCCEEDED
# construction in one place.  This is the same fixture used by the request
# store which ultimately repeats this preflight.
from test_comparison_requests import (  # noqa: E402
    _CURRENT_MISSION_ID,
    _OTHER_ORG_VIEWER_TOKEN,
    _SITE_ID,
    _VIEWER_TOKEN,
    _Fixture,
    _registry,
)


@dataclass(frozen=True)
class _Surface:
    status: DesignSurfaceStatus


class _SurfaceStore:
    def __init__(self, surfaces: list[Any] | None = None) -> None:
        self._surfaces = list(surfaces or [])

    def list_for_site(self, _site_id: str) -> list[Any]:
        return list(self._surfaces)


class _SingleJobStore:
    def __init__(self, job: object) -> None:
        self._job = job

    def list_for_site(
        self, _site_id: str, *, organization_id: str, limit: int | None = None
    ) -> list[object]:
        del organization_id, limit
        return [self._job]


class _JobListStore:
    def __init__(self, jobs: list[object]) -> None:
        self._jobs = jobs

    def list_for_site(
        self, _site_id: str, *, organization_id: str, limit: int | None = None
    ) -> list[object]:
        del organization_id
        return self._jobs if limit is None else self._jobs[:limit]


class _UnavailableJobStore:
    def list_for_site(
        self, _site_id: str, *, organization_id: str, limit: int | None = None
    ) -> list[object]:
        del organization_id, limit
        raise RuntimeError("test-only store outage")


def _ready(_mission_id: str) -> tuple[bool, str | None]:
    return True, None


def _projector(
    fixture: _Fixture,
    *,
    jobs: Any | None = None,
    surfaces: list[Any] | None = None,
    readiness: Any = _ready,
) -> CivilReadinessProjector:
    return CivilReadinessProjector(
        site_store=fixture.sites,
        processing_job_store=fixture.jobs if jobs is None else jobs,
        design_surface_store=_SurfaceStore(surfaces),
        analysis_readiness=readiness,
    )


def test_latest_real_pair_reuses_quantitative_preflight_and_keeps_field_acceptance_out(
    tmp_path: Any,
) -> None:
    fixture = _Fixture(tmp_path)

    view = _projector(fixture).project(_SITE_ID, organization_id="legacy")

    assert view.status is CivilReadinessStatus.PAIR_COMPATIBLE
    assert view.succeeded_epoch_count == 2
    assert view.pair.compatible is True
    assert view.pair.reason is None
    assert view.pair.baseline_job_id == fixture.baseline_job_id
    assert view.pair.current_job_id == fixture.current_job_id
    assert view.design_surface.status is CivilDesignSurfaceStatus.NOT_REGISTERED
    assert view.next_action.href == f"/sites/{_SITE_ID}/design"
    assert view.limitations == (
        "OPERATIONAL_RELATIVE_QUANTITY_ONLY",
        "FIELD_ACCEPTANCE_NOT_INCLUDED",
    )
    assert "fieldAcceptance" not in view.model_dump(by_alias=True)


def test_readiness_blocker_is_the_same_typed_reason_as_a_real_comparison_request(
    tmp_path: Any,
) -> None:
    fixture = _Fixture(tmp_path)
    projector = _projector(
        fixture,
        readiness=lambda _mission_id: (False, "capture quality evidence is missing"),
    )

    view = projector.project(_SITE_ID, organization_id="legacy")

    assert view.status is CivilReadinessStatus.PAIR_BLOCKED
    assert view.pair.compatible is False
    assert view.pair.reason is CivilPreflightReason.ANALYSIS_NOT_READY
    assert view.next_action.href == f"/missions/{_CURRENT_MISSION_ID}"


def test_disjoint_succeeded_epochs_never_report_pair_compatible(tmp_path: Any) -> None:
    fixture = _Fixture(tmp_path)
    baseline = fixture.jobs.get(fixture.baseline_job_id)
    current = fixture.jobs.get(fixture.current_job_id)
    assert baseline is not None and current is not None
    baseline_point_cloud = next(
        artifact
        for artifact in baseline.artifacts
        if artifact.kind is ProcessingArtifactKind.POINT_CLOUD
    )
    current_dsm = next(
        artifact
        for artifact in current.artifacts
        if artifact.kind is ProcessingArtifactKind.DSM
    )
    jobs = _JobListStore(
        [
            replace(baseline, artifacts=(baseline_point_cloud,)),
            replace(current, artifacts=(current_dsm,)),
        ]
    )

    view = _projector(fixture, jobs=jobs).project(_SITE_ID, organization_id="legacy")

    assert view.status is CivilReadinessStatus.PAIR_BLOCKED
    assert view.pair.compatible is False
    assert view.pair.reason is CivilPreflightReason.NO_COMMON_ARTIFACT_FAMILY


def test_one_completed_epoch_is_not_silently_promoted_to_a_temporal_comparison(
    tmp_path: Any,
) -> None:
    fixture = _Fixture(tmp_path)
    current = fixture.jobs.get(fixture.current_job_id)
    assert current is not None
    projector = _projector(fixture, jobs=_SingleJobStore(current))

    view = projector.project(_SITE_ID, organization_id="legacy")

    assert view.status is CivilReadinessStatus.SECOND_EPOCH_REQUIRED
    assert view.pair.reason is CivilReadinessReason.SECOND_EPOCH_REQUIRED
    assert view.pair.current_job_id == fixture.current_job_id
    assert view.pair.compatible is False


def test_design_inventory_never_treats_sealed_as_verified_or_chooses_a_revision(
    tmp_path: Any,
) -> None:
    fixture = _Fixture(tmp_path)
    projector = _projector(fixture, surfaces=[_Surface(DesignSurfaceStatus.SEALED)])

    view = projector.project(_SITE_ID, organization_id="legacy")

    assert view.status is CivilReadinessStatus.PAIR_COMPATIBLE
    assert view.design_surface.status is CivilDesignSurfaceStatus.VERIFICATION_REQUIRED
    assert view.design_surface.verified_surface_count == 0
    assert view.next_action.href == f"/sites/{_SITE_ID}/design"


def test_unavailable_processing_history_is_a_typed_fail_closed_state(tmp_path: Any) -> None:
    fixture = _Fixture(tmp_path)
    projector = _projector(fixture, jobs=_UnavailableJobStore())

    view = projector.project(_SITE_ID, organization_id="legacy")

    assert view.status is CivilReadinessStatus.SYSTEM_UNAVAILABLE
    assert view.pair.reason is CivilReadinessReason.SYSTEM_UNAVAILABLE
    assert view.pair.compatible is False


def test_http_route_is_read_only_and_hides_foreign_site_existence(tmp_path: Any) -> None:
    fixture = _Fixture(tmp_path)
    app = FastAPI()
    mount_auth(app, _registry())
    mount_civil_readiness(app, _projector(fixture))
    client = TestClient(app)

    own = client.get(
        f"/v1/sites/{_SITE_ID}/civil-readiness",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    )
    foreign = client.get(
        f"/v1/sites/{_SITE_ID}/civil-readiness",
        headers={"Authorization": f"Bearer {_OTHER_ORG_VIEWER_TOKEN}"},
    )
    unknown = client.get(
        "/v1/sites/site-does-not-exist/civil-readiness",
        headers={"Authorization": f"Bearer {_OTHER_ORG_VIEWER_TOKEN}"},
    )

    assert own.status_code == 200
    assert own.json()["status"] == "PAIR_COMPATIBLE"
    assert own.json()["pair"]["compatible"] is True
    assert own.json()["limitations"] == [
        "OPERATIONAL_RELATIVE_QUANTITY_ONLY",
        "FIELD_ACCEPTANCE_NOT_INCLUDED",
    ]
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json() == {"detail": "현장을 찾을 수 없다"}
