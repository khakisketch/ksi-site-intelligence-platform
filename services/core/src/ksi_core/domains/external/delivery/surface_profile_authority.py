"""Core's answer to "may this profile be read, and may it still be?", from existing authority.

Nothing here is new authority.  It asks the components that already own each fact:

- the **source** (sealed subject, MEASURED inspection, current report):
  ``SpatialDataSourceResolver``;
- the **grant** (beneficiary, asset, purpose, operation, bounds, location):
  ``SpatialDataGrantAuthorizer``;
- the **saved line**: ``MeasurementFeatureStore``;
- the **HEIGHT verdict**: ``ExternalUseEvaluator.height_blocker_now``, because a recorded decision
  is history and must be re-proved before anything acts on it;
- the **engine's support range**: ``profile_support_blocker``, since HEIGHT allows grids this
  engine does not read.

The read window is computed here with the very function the worker's sampler uses, then the grant is
asked about *exactly those cells* — never the line's bounding box and never the whole raster.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from ksi_event_contracts.external_artifact_validation import ExternalUseDecisionV1
from ksi_event_contracts.measurement_feature import MeasurementFeatureRevisionV1
from ksi_event_contracts.spatial_data import (
    SpatialDataPurposeV1,
    SpatialDataSourceV1,
)
from ksi_event_contracts.spatial_data_authority import SpatialDataGrantV1, SpatialDataPolicyV1
from ksi_event_contracts.surface_profile_job import (
    CreateSurfaceProfileJobV1,
    SurfaceProfileActivationV1,
    SurfaceProfileFrozenJobV1,
    SurfaceProfilePolicyV1,
    SurfaceProfileReadWindowV1,
)
from ksi_geo_spatial.crs import normalise_crs
from ksi_geo_spatial.external_native_window_geometry import NativeWindowGeometryV1
from ksi_geo_spatial.surface_profile import (
    SurfaceProfileError,
    SurfaceProfilePlan,
    SurfaceProfilePolicy,
    locate_profile_samples,
    neighbour_window,
    plan_surface_profile,
    profile_support_blocker,
)

from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.jobs import SpatialDataJobCurrentnessPort
from ksi_core.domains.external.delivery.surface_profile_jobs import (
    SurfaceProfileAdmission,
    SurfaceProfileDomainError,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identity.auth import Permission, Principal, principal_permissions


class _Sources(Protocol):
    def require_history_scope(
        self, site_id: str, work_area_id: str, principal: Principal
    ) -> Any: ...

    def resolve(
        self, *, site_id: str, work_area_id: str, asset_ref: str, principal: Principal
    ) -> SpatialDataSourceV1: ...

    def require_current(
        self, *, source: SpatialDataSourceV1, principal: Principal, now: datetime
    ) -> SpatialDataSourceV1: ...


class _Grants(Protocol):
    def select_current(self, **kwargs: Any) -> SpatialDataGrantV1: ...

    def require_current(self, **kwargs: Any) -> SpatialDataGrantV1: ...


class _Features(Protocol):
    def get(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        feature_id: str,
        revision: int | None = None,
    ) -> MeasurementFeatureRevisionV1 | None: ...


class _Decisions(Protocol):
    def get_scoped(self, decision_id: str, *, principal: Principal, site_id: str) -> Any: ...

    def height_blocker_now(
        self, decision: ExternalUseDecisionV1, *, now: datetime
    ) -> str | None: ...


# A refusal from an owning component keeps its meaning when this lane knows the word; otherwise it
# is folded by status so no foreign vocabulary or detail leaks into this lane's closed reasons.
_KNOWN = frozenset(
    {
        "PERMISSION_DENIED",
        "NOT_FOUND",
        "ACCESS_REVOKED",
        "ACCESS_EXPIRED",
        "OUTPUT_OUTSIDE_GRANT",
        "PROCESSING_LOCATION_DENIED",
        "POLICY_UNAVAILABLE",
        "CURRENTNESS_UNAVAILABLE",
        "RESOURCE_LIMIT_EXCEEDED",
        "SOURCE_NOT_MEASURED",
        "SOURCE_MEASUREMENTS_MISMATCH",
        "GRANT_REQUIRED",
        "AMBIGUOUS_GRANT",
        "SOURCE_UNAVAILABLE",
    }
)


def _translated(error: SpatialDataDomainError) -> SurfaceProfileDomainError:
    if error.reason in _KNOWN:
        return SurfaceProfileDomainError(error.reason, error.status_code, error.retryable)
    if error.status_code == 404:
        return SurfaceProfileDomainError("NOT_FOUND", 404)
    if error.status_code == 403:
        return SurfaceProfileDomainError("PERMISSION_DENIED", 403)
    if error.status_code >= 500:
        return SurfaceProfileDomainError("CURRENTNESS_UNAVAILABLE", 503)
    return SurfaceProfileDomainError("SOURCE_UNAVAILABLE", 409)


def _geometry(
    source: SpatialDataSourceV1, window: SurfaceProfileReadWindowV1
) -> NativeWindowGeometryV1:
    measured = source.inspection.measurements
    assert measured is not None
    a, _, c, _, e, f = measured.transform
    col0, col1, row0, row1 = window.pixel_window
    left, right = c + a * col0, c + a * col1
    top, bottom = f + e * row0, f + e * row1
    return NativeWindowGeometryV1(
        window.pixel_window, (left, bottom, right, top), (a, 0.0, left, 0.0, e, top)
    )


def read_window_for(
    source: SpatialDataSourceV1, plan: SurfaceProfilePlan
) -> SurfaceProfileReadWindowV1 | None:
    """The cells the sampler will read for this plan on this source, or ``None`` if none."""
    measured = source.inspection.measurements
    assert measured is not None
    a, _, c, _, e, f = measured.transform
    located = locate_profile_samples(
        plan,
        left=c,
        top=f,
        cell_size_x=a,
        cell_size_y=-e,
        width=measured.width,
        height=measured.height,
    )
    span = neighbour_window(located)
    if span is None:
        return None
    col0, col1, row0, row1 = span
    return SurfaceProfileReadWindowV1(
        pixel_window=span,
        actual_bounds=(c + a * col0, f + e * row1, c + a * col1, f + e * row0),
    )


class SurfaceProfileCoreAuthority:
    """Implements ``SurfaceProfileAuthorityPort`` over the participants that own each fact."""

    def __init__(
        self,
        *,
        sources: _Sources,
        grants: _Grants,
        features: _Features,
        decisions: _Decisions,
        currentness: SpatialDataJobCurrentnessPort,
        data_policy: SpatialDataPolicyV1,
        activation: SurfaceProfileActivationV1,
        profile_policy_digest: str,
        runtime_digest: str,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        for snapshot in (data_policy, activation):
            sealed = type(snapshot).model_validate(snapshot.model_dump())
            if getattr(sealed, sealed._digest_field) != sealed.canonical_digest():
                raise ValueError("profile authority requires sealed explicit snapshots")
        if (
            activation.policy_digest != profile_policy_digest
            or activation.runtime_digest != runtime_digest
        ):
            raise ValueError("the activation must bind the explicit profile policy and runtime")
        if currentness.coordinator is not coordinator:
            raise ValueError("profile authority needs one shared Core coordinator")
        self.coordinator = coordinator
        self._sources = sources
        self._grants = grants
        self._features = features
        self._decisions = decisions
        self._currentness = currentness
        self._data_policy = data_policy.model_copy(deep=True)
        self._activation = activation.model_copy(deep=True)

    # ── scope ────────────────────────────────────────────────────────────
    def require_scope(self, site_id: str, work_area_id: str, principal: Principal) -> None:
        try:
            self._sources.require_history_scope(site_id, work_area_id, principal)
        except SpatialDataDomainError as exc:
            raise _translated(exc) from exc

    # ── admission ────────────────────────────────────────────────────────
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
        feature = self._features.get(
            organization_id=principal.organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            feature_id=request.feature.feature_id,
            revision=request.feature.revision,
        )
        if feature is None or feature.ref() != request.feature:
            raise SurfaceProfileDomainError("FEATURE_UNAVAILABLE", 404)
        try:
            source = self._sources.resolve(
                site_id=site_id,
                work_area_id=work_area_id,
                asset_ref=request.asset_ref,
                principal=principal,
            )
        except SpatialDataDomainError as exc:
            raise _translated(exc) from exc
        measured = source.inspection.measurements
        if source.artifact_kind != "dsm" or measured is None:
            raise SurfaceProfileDomainError("UNSUPPORTED_RASTER", 422)
        blocker = profile_support_blocker(measured)
        if blocker is not None:
            raise SurfaceProfileDomainError(blocker.value, 422)

        decision = self._decisions.get_scoped(
            request.height_decision_id, principal=principal, site_id=site_id
        )
        if (
            not isinstance(decision, ExternalUseDecisionV1)
            or decision.subject != source.sealed_subject
            or decision.decision_digest is None
            or self._decisions.height_blocker_now(decision, now=now) is not None
        ):
            raise SurfaceProfileDomainError("HEIGHT_NOT_ELIGIBLE", 409)

        a, _, _, _, e, _ = measured.transform
        try:
            plan = plan_surface_profile(
                feature.line.vertices,
                vertices_crs=feature.line.crs,
                horizontal_crs=normalise_crs(measured.observed_crs_identifier),
                sample_spacing_m=request.sample_spacing_m or max(a, -e),
                policy=SurfaceProfilePolicy(
                    maximum_vertices=policy.maximum_vertices,
                    maximum_samples=policy.maximum_samples,
                    maximum_line_length_m=policy.maximum_line_length_m,
                    maximum_window_cells=policy.maximum_window_cells,
                    maximum_source_block_cells=policy.maximum_source_block_cells,
                ),
            )
        except SurfaceProfileError as exc:
            raise SurfaceProfileDomainError(exc.reason.value, 422) from exc
        window = read_window_for(source, plan)
        if window is None:
            raise SurfaceProfileDomainError("LINE_OUTSIDE_SURFACE", 422)
        if window.cells > policy.maximum_window_cells:
            raise SurfaceProfileDomainError("WINDOW_TOO_LARGE", 422)

        geometry = _geometry(source, window)
        try:
            grants = [
                self._grants.select_current(
                    source=source,
                    principal=principal,
                    purpose=SpatialDataPurposeV1.GENERAL_DATA_USE,
                    requested_bounds=window.actual_bounds,
                    geometry=geometry,
                    operation=operation,
                    policy=self._data_policy,
                    now=now,
                )
                for operation in ("PREPARE", "READ")
            ]
        except SpatialDataDomainError as exc:
            raise _translated(exc) from exc
        if grants[0] != grants[1]:
            raise SurfaceProfileDomainError("AMBIGUOUS_GRANT", 403)
        return SurfaceProfileAdmission(
            feature=feature,
            source=source,
            grant=grants[0],
            data_policy_digest=self._data_policy.policy_digest or "",
            height_decision_digest=decision.decision_digest,
            read_window=window,
        )

    # ── every later transition ───────────────────────────────────────────
    def reprove(
        self,
        job: SurfaceProfileFrozenJobV1,
        *,
        operation: Literal["PREPARE", "READ"],
        now: datetime,
    ) -> None:
        try:
            requester = self._currentness.resolve_requester(
                principal_id=job.requester_principal_id,
                organization_id=job.organization_id,
                now=now,
            )
        except Exception as exc:
            raise SurfaceProfileDomainError("CURRENTNESS_UNAVAILABLE", 503) from exc
        if not isinstance(requester, Principal) or (
            requester.principal_id,
            requester.organization_id,
        ) != (job.requester_principal_id, job.organization_id):
            raise SurfaceProfileDomainError("ACCESS_REVOKED", 403)
        needed = (
            Permission.SPATIAL_DATA_REQUEST
            if operation == "PREPARE"
            else Permission.SPATIAL_DATA_READ
        )
        if needed not in principal_permissions(requester):
            raise SurfaceProfileDomainError("PERMISSION_DENIED", 403)
        try:
            source = self._sources.require_current(source=job.source, principal=requester, now=now)
        except SpatialDataDomainError as exc:
            raise _translated(exc) from exc
        if source != job.source:
            raise SurfaceProfileDomainError("SOURCE_MEASUREMENTS_MISMATCH", 409)

        decision = self._decisions.get_scoped(
            job.request.height_decision_id, principal=requester, site_id=job.site_id
        )
        if (
            not isinstance(decision, ExternalUseDecisionV1)
            or decision.decision_digest != job.height_decision_digest
            or self._decisions.height_blocker_now(decision, now=now) is not None
        ):
            raise SurfaceProfileDomainError("HEIGHT_NOT_ELIGIBLE", 409)

        window = job.read_window
        if window is None:
            return
        try:
            grant = self._grants.require_current(
                grant_id=job.grant.grant_id,
                revision=job.grant.revision,
                source=source,
                principal=requester,
                purpose=SpatialDataPurposeV1.GENERAL_DATA_USE,
                requested_bounds=window.actual_bounds,
                geometry=_geometry(source, window),
                operation=operation,
                policy=self._data_policy,
                now=now,
            )
        except SpatialDataDomainError as exc:
            raise _translated(exc) from exc
        if grant != job.grant:
            raise SurfaceProfileDomainError("ACCESS_REVOKED", 403)

    def worker_is_activated(self, worker: Principal, instance_id: str, now: datetime) -> bool:
        activation = self._activation
        return (
            activation.is_current_at(now)
            and worker.organization_id == activation.organization_id
            and worker.principal_id == activation.worker_principal_id
            and instance_id == activation.worker_instance_id
        )


__all__ = ["SurfaceProfileCoreAuthority", "read_window_for"]
