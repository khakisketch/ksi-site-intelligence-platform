"""Small explicit surface-profile authority: synthetic snapshots, a real raster, a switchable port.

Never production defaults.  The numbers come from the genuine calculation over a synthetic grid so
the completion check is exercised against a result a real worker would produce.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import rasterio
from ksi_core.domains.external.delivery.surface_profile_jobs import (
    SurfaceProfileAdmission,
    SurfaceProfileDomainError,
    SurfaceProfileJobStore,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identity.auth import Principal, PrincipalKind, Role
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    ObservedVerticalReferenceV1,
)
from ksi_event_contracts.measurement_feature import MeasurementFeatureRevisionV1, MeasurementLineV1
from ksi_event_contracts.surface_profile import CreateSurfaceProfileV1, SurfaceProfileResultV1
from ksi_event_contracts.surface_profile_job import (
    CreateSurfaceProfileJobV1,
    SurfaceProfileFrozenJobV1,
    SurfaceProfilePolicyV1,
    SurfaceProfileReadWindowV1,
    SurfaceProfileReceiptV1,
    SurfaceProfileRuntimeV1,
)
from ksi_geo_spatial.surface_profile import (
    SurfaceProfilePolicy,
    locate_profile_samples,
    neighbour_window,
    plan_surface_profile,
)
from ksi_processing_controller.surface_profile_worker import read_surface_profile
from rasterio.transform import from_origin
from spatial_data_fixture import (
    ASSET,
    DIGEST,
    NOW,
    make_envelope,
    make_grant,
    make_measurements,
    make_policy,
    make_source,
)

ORG = "org-local"
SITE = "site-local"
AREA = "area-local"
ORIGIN_X, ORIGIN_Y = 200_000.0, 500_000.0
WIDTH, HEIGHT = 30, 20
FEATURE_ID = "mf-" + "1" * 32
DECISION_ID = "external-use-decision-" + "a" * 32


def centre(col: float, row: float) -> tuple[float, float]:
    return (ORIGIN_X + col + 0.5, ORIGIN_Y - row - 0.5)


def line(*cells: tuple[float, float]) -> MeasurementLineV1:
    return MeasurementLineV1(crs="EPSG:5186", vertices=tuple(centre(c, r) for c, r in cells))


def plane() -> np.ndarray:
    """z = 100 + 0.5·col + 0.25·row — bilinear interpolation reproduces it exactly."""
    row_index, col_index = np.mgrid[0:HEIGHT, 0:WIDTH]
    return 100.0 + 0.5 * col_index + 0.25 * row_index


def write_raster(path: Path, values: np.ndarray | None = None) -> Path:
    data = plane() if values is None else values
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=HEIGHT,
        width=WIDTH,
        count=1,
        dtype="float32",
        crs="EPSG:5186",
        nodata=-9999.0,
        transform=from_origin(ORIGIN_X, ORIGIN_Y, 1.0, 1.0),
    ) as dataset:
        dataset.write(data.astype("float32"), 1)
    return path


def profile_policy(**overrides: Any) -> SurfaceProfilePolicyV1:
    payload: dict[str, Any] = dict(
        policy_id="surface-profile-local-test-only",
        revision=1,
        resource_envelope=make_envelope(
            max_pixels=100_000,
            max_geometry_vertices=64,
            max_output_bytes=2_000_000,
            max_workspace_bytes=4_000_000,
            max_tenant_concurrency=3,
            max_queue_depth=8,
            max_deadline_seconds=120.0,
        ),
        maximum_vertices=32,
        maximum_samples=500,
        maximum_line_length_m=2000.0,
        maximum_window_cells=5000,
        maximum_source_block_cells=100_000,
        max_result_bytes=400_000,
        max_active_jobs_per_organization=2,
        max_pending_records=8,
        max_list_records=8,
        max_idempotency_key_bytes=255,
        lease_seconds=5.0,
        deadline_seconds=60.0,
        max_attempts=2,
        min_retry_backoff_seconds=1.0,
        max_retry_backoff_seconds=5.0,
        retention_seconds=3600.0,
    )
    payload.update(overrides)
    return SurfaceProfilePolicyV1(**payload).sealed()


def profile_runtime() -> SurfaceProfileRuntimeV1:
    return SurfaceProfileRuntimeV1(
        executable_digest=DIGEST,
        build_digest=DIGEST,
        runtime_image="registry.invalid/ksi-surface-profile:local-test",
        runtime_image_version="local-test",
        runtime_image_digest=DIGEST,
        dependency_lock_digest=DIGEST,
    ).sealed()


def feature_revision(
    saved: MeasurementLineV1 | None = None, *, revision: int = 1
) -> MeasurementFeatureRevisionV1:
    chosen = saved or line((2.0, 3.0), (12.0, 3.0), (12.0, 9.0))
    return MeasurementFeatureRevisionV1(
        feature_id=FEATURE_ID,
        site_id=SITE,
        work_area_id=AREA,
        revision=revision,
        name="북쪽 경사면",
        line=chosen,
        line_digest=chosen.digest(),
        created_at=NOW,
    ).sealed()


def measured_source() -> Any:
    measurements = make_measurements(
        observed_crs_identifier="EPSG:5186",
        observed_vertical_reference=ObservedVerticalReferenceV1(
            identifier="EPSG:5773", basis="EGM96 height"
        ),
        transform=(1.0, 0.0, ORIGIN_X, 0.0, -1.0, ORIGIN_Y),
        width=WIDTH,
        height=HEIGHT,
        footprint_wkt="POLYGON ((0 0, 30 0, 30 20, 0 20, 0 0))",
    )
    return make_source(
        inspection=ArtifactInspectionOutcomeV1(
            artifact_id="artifact-local",
            observed_sha256=DIGEST,
            outcome=ArtifactOutcome.MEASURED,
            measurements=measurements,
        ),
        observed_crs_units="metre",
    )


def sdp(policy: SurfaceProfilePolicyV1) -> SurfaceProfilePolicy:
    return SurfaceProfilePolicy(
        maximum_vertices=policy.maximum_vertices,
        maximum_samples=policy.maximum_samples,
        maximum_line_length_m=policy.maximum_line_length_m,
        maximum_window_cells=policy.maximum_window_cells,
        maximum_source_block_cells=policy.maximum_source_block_cells,
    )


@dataclass
class FakeAuthority:
    """The port, with a switch for every proof the real one makes."""

    coordinator: ExternalAuthorityCurrentnessCoordinator
    feature: MeasurementFeatureRevisionV1 = field(default_factory=feature_revision)
    source: Any = field(default_factory=measured_source)
    grant: Any = field(
        default_factory=lambda: make_grant(
            allowed_bounds=(ORIGIN_X, ORIGIN_Y - HEIGHT, ORIGIN_X + WIDTH, ORIGIN_Y),
            observed_crs_digest=DIGEST,
        )
    )
    deny: dict[str, str] = field(default_factory=dict)  # operation -> reason
    admit_error: str | None = None
    activated: bool = True
    scope_error: bool = False
    calls: list[str] = field(default_factory=list)

    def require_scope(self, site_id: str, work_area_id: str, principal: Principal) -> None:
        self.calls.append("scope")
        if (
            self.scope_error
            or principal.organization_id != ORG
            or (site_id, work_area_id) != (SITE, AREA)
        ):
            raise SurfaceProfileDomainError("NOT_FOUND", 404)

    def admit(
        self,
        *,
        site_id: str,
        work_area_id: str,
        request: CreateSurfaceProfileJobV1,
        principal: Principal,
        policy: SurfaceProfilePolicyV1,
        now: datetime,
    ) -> SurfaceProfileAdmission:
        self.calls.append("admit")
        if self.admit_error is not None:
            raise SurfaceProfileDomainError(self.admit_error, 409)
        measured = self.source.inspection.measurements
        plan = plan_surface_profile(
            self.feature.line.vertices,
            vertices_crs=self.feature.line.crs,
            horizontal_crs="EPSG:5186",
            sample_spacing_m=request.sample_spacing_m or 1.0,
            policy=sdp(policy),
        )
        located = locate_profile_samples(
            plan,
            left=measured.transform[2],
            top=measured.transform[5],
            cell_size_x=1.0,
            cell_size_y=1.0,
            width=measured.width,
            height=measured.height,
        )
        span = neighbour_window(located)
        window = None
        if span is not None:
            col0, col1, row0, row1 = span
            window = SurfaceProfileReadWindowV1(
                pixel_window=span,
                actual_bounds=(
                    ORIGIN_X + col0,
                    ORIGIN_Y - row1,
                    ORIGIN_X + col1,
                    ORIGIN_Y - row0,
                ),
            )
        return SurfaceProfileAdmission(
            feature=self.feature,
            source=self.source,
            grant=self.grant,
            data_policy_digest=make_policy().policy_digest or "",
            height_decision_digest=DIGEST,
            read_window=window,
        )

    def reprove(
        self,
        job: SurfaceProfileFrozenJobV1,
        *,
        operation: Literal["PREPARE", "READ"],
        now: datetime,
    ) -> None:
        self.calls.append(f"reprove:{operation}")
        reason = self.deny.get(operation) or self.deny.get("*")
        if reason is not None:
            raise SurfaceProfileDomainError(reason, 403)

    def worker_is_activated(self, worker: Principal, instance_id: str, now: datetime) -> bool:
        return self.activated and instance_id.startswith("instance-")


def requester(name: str = "reader-local", org: str = ORG) -> Principal:
    return Principal(
        principal_id=name,
        kind=PrincipalKind.OPERATOR,
        role=Role.ADMIN,
        device_id=None,
        organization_id=org,
    )


def viewer(name: str = "viewer-local") -> Principal:
    return Principal(
        principal_id=name,
        kind=PrincipalKind.OPERATOR,
        role=Role.VIEWER,
        device_id=None,
        organization_id=ORG,
    )


def worker(name: str = "worker-local", org: str = ORG) -> Principal:
    return Principal(
        principal_id=name,
        kind=PrincipalKind.SPATIAL_DATA_WORKER,
        role=None,
        device_id=None,
        organization_id=org,
    )


def issue_request(**overrides: Any) -> CreateSurfaceProfileJobV1:
    payload: dict[str, Any] = dict(
        asset_ref=ASSET,
        feature=feature_revision().ref(),
        height_decision_id=DECISION_ID,
    )
    payload.update(overrides)
    return CreateSurfaceProfileJobV1(**payload)


def genuine_answer(
    job: SurfaceProfileFrozenJobV1, raster: Path, now: datetime
) -> tuple[SurfaceProfileResultV1, SurfaceProfileReceiptV1]:
    """What a real worker would send: the engine's own result over the synthetic grid."""
    request = CreateSurfaceProfileV1(
        asset_ref=job.profile_request.asset_ref,
        line=job.profile_request.line,
        feature=job.profile_request.feature,
        sample_spacing_m=job.profile_request.sample_spacing_m,
    )
    outcome = read_surface_profile(request, raster, policy=sdp(job.policy))
    assert isinstance(outcome, SurfaceProfileResultV1), outcome
    return outcome, receipt_for(job, outcome, now)


def receipt_for(
    job: SurfaceProfileFrozenJobV1, result: SurfaceProfileResultV1, now: datetime, **overrides: Any
) -> SurfaceProfileReceiptV1:
    measured = job.source.inspection.measurements
    assert measured is not None and measured.observed_vertical_reference is not None
    payload: dict[str, Any] = dict(
        job_id=job.job_id,
        job_digest=job.job_digest,
        source_digest=job.source.source_digest,
        request_digest=job.request_fingerprint,
        grant_digest=job.grant.grant_digest,
        data_policy_digest=job.data_policy_digest,
        policy_digest=job.policy.policy_digest,
        runtime_digest=job.runtime.runtime_digest,
        artifact_id=job.source.artifact_id,
        source_sha256=job.source.observed_sha256,
        source_size_bytes=job.source.observed_size_bytes,
        observed_crs_identifier=measured.observed_crs_identifier,
        observed_crs_digest=measured.observed_crs_digest,
        observed_vertical_reference=measured.observed_vertical_reference,
        result_digest=result.result_digest,
        read_window=job.read_window,
        window_cells_read=result.window_cells_read,
        accuracy_assessed=False,
        prepared_at=now,
        attribution="Synthetic local fixture; no accuracy claim",
        limitations=("Heights are the registered grid read along the line; not a survey.",),
    )
    payload.update(overrides)
    return SurfaceProfileReceiptV1(**payload).sealed()


def later(seconds: float) -> timedelta:
    return timedelta(seconds=seconds)


__all__ = [
    "AREA",
    "ORG",
    "SITE",
    "FakeAuthority",
    "SurfaceProfileJobStore",
    "centre",
    "feature_revision",
    "genuine_answer",
    "issue_request",
    "later",
    "line",
    "plane",
    "profile_policy",
    "profile_runtime",
    "receipt_for",
    "requester",
    "viewer",
    "worker",
    "write_raster",
]
