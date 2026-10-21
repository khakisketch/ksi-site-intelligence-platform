"""SWX-1 observation/version/view-availability projection (read-only).

Server-owned answer to "what observations exist for this Site/WorkArea, which
asset versions each has, what is view-available, and which observation is the
ordinary-entry default". The client must not invent quality ranking, dates,
versions, or eligibility.

Reuse, not reimplementation (owner APIs called, never copied):

- enumeration/scope/identity/lifecycle/declared/observed facts:
  ``SpatialAssetCatalog.items`` / ``with_inspection`` in
  ``spatial_asset_catalog.py``;
- inspection outcome/raster facts: the catalog-attached
  ``SpatialAssetInspectionV1`` (owner store
  ``ExternalArtifactInspectionStore.public_snapshot_bounded``);
- display readiness: ``ExternalArtifactInspectionStore.public_display_state``
  (a ``SEALED`` sanitized-display receipt only; never quantitative
  eligibility, never a new "verified" boolean);
- chronological candidacy: the exact-interval predicate shape used by
  ``ExternalAnalysisFacade.observation_options``
  (``external_analysis_api.py``: capture interval required, UTC, positive).

No new eligibility computation, no policy reimplementation, no byte/URL/key
authority. Reading this projection grants nothing.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.site_spatial_workspace import (
    SiteSpatialWorkspacePageV1,
    WorkspaceAssetVersionViewV1,
    WorkspaceCaptureFactsV1,
    WorkspaceCapturePrecisionV1,
    WorkspaceChronologyReasonV1,
    WorkspaceDisplayStateV1,
    WorkspaceEntryDefaultReasonV1,
    WorkspaceEntryDefaultV1,
    WorkspaceObservationViewV1,
)

from ksi_core.domains.external.ingress.external_reconstruction import (
    ExternalReconstructionRevision,
    ExternalReconstructionStore,
)
from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog
from ksi_core.identity.auth import Permission, Principal, require_permission

_NOT_FOUND = "SITE_SPATIAL_ASSET_NOT_FOUND"
_MAX_PAGE_BYTES = 512 * 1024
_MAX_INSPECTION_RECORDS_PER_SUBJECT = 128
_MAX_RETAINED_POLICIES_PER_INSPECTION = 64
_CURSOR_RE = re.compile(r"^[A-Za-z0-9_-]{1,1024}$")


def _capture_of_submission(submission: Any) -> WorkspaceCaptureFactsV1:
    """Declared capture timing at its real precision; never synthesized.

    V3 carries an explicit ``captureBasis`` (exact interval / calendar date /
    unknown). V1/V2 carry only an optional exact pair, so a present pair is an
    exact interval and absence is unknown. Unknown never inherits
    registration/export time here or anywhere downstream.
    """
    declaration = submission.input_declaration
    basis = getattr(declaration, "capture_basis", None)
    if basis is None:
        started = declaration.capture_started_at
        ended = declaration.capture_ended_at
        if started is not None and ended is not None:
            return WorkspaceCaptureFactsV1(
                precision=WorkspaceCapturePrecisionV1.EXACT_INTERVAL,
                capture_started_at=started,
                capture_ended_at=ended,
            )
        return WorkspaceCaptureFactsV1(precision=WorkspaceCapturePrecisionV1.UNKNOWN)
    if basis == "EXACT_INTERVAL":
        return WorkspaceCaptureFactsV1(
            precision=WorkspaceCapturePrecisionV1.EXACT_INTERVAL,
            capture_started_at=declaration.capture_started_at,
            capture_ended_at=declaration.capture_ended_at,
        )
    if basis == "DATE_ONLY":
        return WorkspaceCaptureFactsV1(
            precision=WorkspaceCapturePrecisionV1.DATE_ONLY,
            capture_date=declaration.capture_date,
        )
    return WorkspaceCaptureFactsV1(precision=WorkspaceCapturePrecisionV1.UNKNOWN)


def _is_exact_utc_positive_interval(capture: WorkspaceCaptureFactsV1) -> bool:
    """Chronological candidacy predicate; mirrors the analysis option rule.

    Same shape as ``ExternalAnalysisFacade.observation_options``: an exact
    capture interval is required, it must be UTC, and it must be positive.
    Historic registrations that omit or invert a window are not valid
    selectable epoch facts here either. Date-only/unknown observations stay
    browsable but never enter the candidate set.
    """
    start = capture.capture_started_at
    end = capture.capture_ended_at
    return (
        capture.precision is WorkspaceCapturePrecisionV1.EXACT_INTERVAL
        and start is not None
        and end is not None
        and start.tzinfo is not None
        and end.tzinfo is not None
        and start.utcoffset() == UTC.utcoffset(start)
        and end.utcoffset() == UTC.utcoffset(end)
        and start < end
    )


def _sealed_subject(record: ExternalReconstructionRevision) -> SealedExternalSubjectV1 | None:
    """Exact sealed subject for display-state reads; None while unsealed.

    Same subject construction as the catalog inspection projection
    (``spatial_asset_catalog.py``); the state logic itself stays in the
    inspection owner store. Unsealed revisions have no subject by
    construction, so they can never read as display-ready.
    """
    manifest = record.manifest
    if manifest is None:
        return None
    submission = record.submission
    assert submission.submission_digest is not None
    assert manifest.manifest_digest is not None
    return SealedExternalSubjectV1(
        organization_id=submission.organization_id,
        site_id=submission.site_id,
        work_order_id=record.work_order_id,
        submission_id=submission.submission_id,
        revision=submission.revision,
        submission_digest=submission.submission_digest,
        manifest_digest=manifest.manifest_digest,
    )


class SiteSpatialWorkspace:
    """Project observation groups only from current scoped Core stores."""

    def __init__(
        self,
        *,
        reconstruction: ExternalReconstructionStore,
        work_orders: Any,
        sites: Any,
        work_areas: Any,
        inspections: Any | None,
    ) -> None:
        self._reconstruction = reconstruction
        self._catalog = SpatialAssetCatalog(
            reconstruction=reconstruction,
            work_orders=work_orders,
            sites=sites,
            work_areas=work_areas,
            inspections=inspections,
        )
        self._inspections = inspections

    def _display_of(self, record: ExternalReconstructionRevision) -> tuple[
        WorkspaceDisplayStateV1,
        bool,
        str,
    ]:
        """Current display disposition from the owner receipt state.

        Returns (state, ready, raw_state). ``ready`` is true only for a sealed
        sanitized-display receipt under current rules — a representation fact,
        never quantitative eligibility. No receipt reference or digest leaves
        this projection: those bind byte access.
        """
        if self._inspections is None:
            return WorkspaceDisplayStateV1.NOT_CONFIGURED, False, "DISPLAY_NOT_CONFIGURED"
        subject = _sealed_subject(record)
        if subject is None:
            return WorkspaceDisplayStateV1.NOT_SEALED, False, "UNSEALED"
        state, receipt = self._inspections.public_display_state(subject)
        raw = str(state)
        if raw == "SEALED" and receipt is not None:
            return WorkspaceDisplayStateV1.SEALED, True, raw
        return WorkspaceDisplayStateV1.NOT_SEALED, False, raw

    def _record_for(
        self,
        *,
        work_order_id: str,
        submission_ref: str,
        revision: int,
        principal: Principal,
        site_id: str,
    ) -> ExternalReconstructionRevision | None:
        submission_id = self._reconstruction.resolve_submission_ref(
            work_order_id,
            submission_ref,
            organization_id=principal.organization_id,
            site_id=site_id,
        )
        if submission_id is None:
            return None
        return self._reconstruction.get(
            work_order_id,
            submission_id,
            revision,
            organization_id=principal.organization_id,
            site_id=site_id,
        )

    def _version_view(
        self,
        *,
        item: Any,
        record: ExternalReconstructionRevision,
        inspected: Any,
        display: tuple[WorkspaceDisplayStateV1, bool, str],
        capture: WorkspaceCaptureFactsV1,
    ) -> WorkspaceAssetVersionViewV1:
        inspection = inspected.inspection
        display_state, display_ready, _raw_display = display
        chronology_candidate = _is_exact_utc_positive_interval(capture)
        if capture.precision is WorkspaceCapturePrecisionV1.EXACT_INTERVAL:
            chronology = (
                WorkspaceChronologyReasonV1.EXACT_INTERVAL_CANDIDATE
                if chronology_candidate
                else WorkspaceChronologyReasonV1.UNKNOWN_CAPTURE_NOT_ORDERABLE
            )
        elif capture.precision is WorkspaceCapturePrecisionV1.DATE_ONLY:
            chronology = WorkspaceChronologyReasonV1.DATE_ONLY_NOT_ORDERABLE
        else:
            chronology = WorkspaceChronologyReasonV1.UNKNOWN_CAPTURE_NOT_ORDERABLE
        observed = inspected.observed
        vertical = inspected.declared.vertical_reference
        return WorkspaceAssetVersionViewV1(
            asset_ref=inspected.asset_ref,
            submission_ref=inspected.submission_ref,
            revision=inspected.revision,
            artifact_id=inspected.artifact_id,
            kind=inspected.kind,
            lifecycle_state=inspected.lifecycle_state.value,
            capture=capture,
            declared_crs=inspected.declared.crs,
            declared_vertical_reference_present=vertical is not None,
            declared_gsd_m=inspected.declared.gsd_m,
            submitted_at=inspected.declared.submitted_at,
            observed_sha256=observed.sha256 if observed is not None else None,
            observed_size_bytes=observed.size_bytes if observed is not None else None,
            observed_at=observed.observed_at if observed is not None else None,
            inspection_state=inspection.state,
            inspection_outcome=inspection.outcome,
            inspection_reason=inspection.reason,
            inspected_raster_available=inspection.raster is not None,
            display_state=display_state,
            display_ready=display_ready,
            chronology=chronology,
            chronology_candidate=chronology_candidate,
        )

    def observations(
        self, site_id: str, work_area_id: str, principal: Principal
    ) -> tuple[WorkspaceObservationViewV1, ...]:
        """All in-scope observations grouped strictly by ``observationEpochId``.

        Grouping never merges distinct WorkOrders by matching dates, and a
        corrective revision of the same submission stays in its observation
        with the earlier revision still visible as SUPERSEDED.
        """
        items = self._catalog.items(site_id, work_area_id, principal)
        by_epoch: dict[str, list[Any]] = {}
        for item in items:
            by_epoch.setdefault(item.observation_epoch_id, []).append(item)
        observations: list[WorkspaceObservationViewV1] = []
        for epoch_id in sorted(by_epoch):
            group = sorted(
                by_epoch[epoch_id],
                key=lambda entry: (entry.submission_ref, entry.revision, entry.artifact_id),
            )
            versions: list[WorkspaceAssetVersionViewV1] = []
            captures: list[WorkspaceCaptureFactsV1] = []
            work_order_id = group[0].work_order_id
            for item in group:
                record = self._record_for(
                    work_order_id=item.work_order_id,
                    submission_ref=item.submission_ref,
                    revision=item.revision,
                    principal=principal,
                    site_id=site_id,
                )
                if record is None:
                    raise HTTPException(status_code=404, detail=_NOT_FOUND)
                inspected = self._catalog.with_inspection(item, principal)
                display = self._display_of(record)
                capture = _capture_of_submission(record.submission)
                captures.append(capture)
                versions.append(
                    self._version_view(
                        item=item,
                        record=record,
                        inspected=inspected,
                        display=display,
                        capture=capture,
                    )
                )
            first_capture = captures[0]
            agree = all(entry == first_capture for entry in captures[1:])
            observation_capture = first_capture
            if not agree:
                # Versions of one observation disagree about capture timing.
                # Keep every exact per-version fact, but the observation as a
                # whole cannot order chronologically.
                newest = max(
                    versions,
                    key=lambda entry: (entry.revision, entry.submission_ref, entry.artifact_id),
                )
                observation_capture = newest.capture
            chronology_candidate = agree and _is_exact_utc_positive_interval(observation_capture)
            display_ready_versions = [entry for entry in versions if entry.display_ready]
            if display_ready_versions:
                ortho = [
                    entry
                    for entry in display_ready_versions
                    if entry.kind is ProcessingArtifactKind.ORTHO
                ]
                pool = ortho or display_ready_versions
                view_version = max(
                    pool, key=lambda entry: (entry.revision, entry.asset_ref)
                )
                view_available = True
                view_reason: str | None = None
                view_ref: str | None = view_version.asset_ref
            else:
                view_available = False
                view_ref = None
                if self._inspections is None:
                    view_reason = "DISPLAY_NOT_CONFIGURED"
                else:
                    view_reason = "NO_DISPLAY_READY_VERSION"
            newest_overall = max(
                versions, key=lambda entry: (entry.revision, entry.submission_ref, entry.asset_ref)
            )
            pending = view_available and not newest_overall.display_ready
            pending_state: str | None = None
            if pending:
                pending_state = (
                    f"{newest_overall.lifecycle_state}/{newest_overall.inspection_state}"
                    f"/{newest_overall.display_state.value}"
                )
            observations.append(
                WorkspaceObservationViewV1(
                    observation_epoch_id=epoch_id,
                    work_order_id=work_order_id,
                    capture=observation_capture,
                    capture_sources_agree=agree,
                    versions=tuple(versions),
                    view_available=view_available,
                    view_unavailable_reason=view_reason,
                    view_asset_ref=view_ref,
                    newer_revision_pending=pending,
                    newer_revision_state=pending_state,
                    chronology_candidate=chronology_candidate,
                    has_sealed_version=any(
                        entry.lifecycle_state in ("SEALED", "SUPERSEDED") for entry in versions
                    ),
                )
            )
        return tuple(observations)

    @staticmethod
    def entry_default(
        observations: tuple[WorkspaceObservationViewV1, ...],
    ) -> WorkspaceEntryDefaultV1:
        """One deterministic ordinary-entry observation, or an explicit reason.

        Order by declared capture information at its real precision — never by
        ``submittedAt``/registration time, which versions keep only as a
        visible declared fact. Date-only stays a calendar date and unknown
        capture time never inherits registration time: neither enters the
        candidate set. Equal-date candidates report ambiguity instead of
        silently picking one. "View-available" is a display/representation
        fact, never quantitative eligibility. A newer UNSEALED or
        uninspected revision never displaces the currently displayable one —
        it stays visible on its observation as pending.
        """
        if not observations:
            return WorkspaceEntryDefaultV1(
                reason=WorkspaceEntryDefaultReasonV1.NO_OBSERVATIONS,
                detail="No observations are registered for this Site and WorkArea scope.",
            )
        if not any(entry.view_available for entry in observations):
            return WorkspaceEntryDefaultV1(
                reason=WorkspaceEntryDefaultReasonV1.NO_VIEW_AVAILABLE_OBSERVATION,
                detail=(
                    "Observations exist but none has a display-ready version under "
                    "current inspection and display rules."
                ),
            )
        candidates = [
            entry
            for entry in observations
            if entry.view_available and entry.chronology_candidate
        ]
        if not candidates:
            return WorkspaceEntryDefaultV1(
                reason=WorkspaceEntryDefaultReasonV1.NO_EXACT_CAPTURE_CANDIDATE,
                detail=(
                    "View-available observations exist but none carries an agreed "
                    "exact capture interval at real precision; date-only and "
                    "unknown-capture observations stay browsable but cannot "
                    "select a latest entry."
                ),
            )
        top = max(
            candidates,
            key=lambda entry: (
                entry.capture.capture_ended_at,
                entry.capture.capture_started_at,
            ),
        )
        tied = tuple(
            entry.observation_epoch_id
            for entry in candidates
            if entry.capture.capture_ended_at == top.capture.capture_ended_at
            and entry.capture.capture_started_at == top.capture.capture_started_at
        )
        if len(tied) > 1:
            return WorkspaceEntryDefaultV1(
                reason=WorkspaceEntryDefaultReasonV1.CAPTURE_TIE_AMBIGUOUS,
                detail=(
                    "Two or more view-available observations share the same "
                    "exact capture interval; no silent pick is made."
                ),
                tied_observation_epoch_ids=tied,
            )
        assert top.view_asset_ref is not None
        return WorkspaceEntryDefaultV1(
            observation_epoch_id=top.observation_epoch_id,
            view_asset_ref=top.view_asset_ref,
            reason=WorkspaceEntryDefaultReasonV1.LATEST_EXACT_VIEW_AVAILABLE,
            detail=(
                "Latest view-available observation by exact capture interval at "
                "real precision; registration order was not consulted."
            ),
        )


def _encode_cursor(*, site_id: str, work_area_id: str, after: str) -> str:
    payload = canonical_json_bytes(
        {"version": 1, "siteId": site_id, "workAreaId": work_area_id, "after": after}
    )
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, *, site_id: str, work_area_id: str) -> str:
    if _CURSOR_RE.fullmatch(cursor) is None:
        raise HTTPException(status_code=400, detail="INVALID_SPATIAL_WORKSPACE_CURSOR")
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="INVALID_SPATIAL_WORKSPACE_CURSOR") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "siteId", "workAreaId", "after"}
        or payload.get("version") != 1
        or payload.get("siteId") != site_id
        or payload.get("workAreaId") != work_area_id
        or not isinstance(payload.get("after"), str)
        or not 1 <= len(payload["after"]) <= 255
        or _encode_cursor(site_id=site_id, work_area_id=work_area_id, after=payload["after"])
        != cursor
    ):
        raise HTTPException(status_code=400, detail="INVALID_SPATIAL_WORKSPACE_CURSOR")
    return payload["after"]


def _page_wire(page: SiteSpatialWorkspacePageV1) -> dict[str, Any]:
    return page.model_dump(by_alias=True, mode="json")


def build_site_spatial_workspace_router(
    *,
    reconstruction: ExternalReconstructionStore,
    work_orders: Any,
    sites: Any,
    work_areas: Any,
    inspections: Any | None,
) -> APIRouter:
    workspace = SiteSpatialWorkspace(
        reconstruction=reconstruction,
        work_orders=work_orders,
        sites=sites,
        work_areas=work_areas,
        inspections=inspections,
    )
    router = APIRouter(tags=["spatial-asset-catalog"])
    read = require_permission(Permission.SITES_READ)

    @router.get(
        "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-workspace-observations",
        response_model=SiteSpatialWorkspacePageV1,
    )
    def list_observations(
        site_id: str,
        work_area_id: str,
        limit: int = Query(default=20, ge=1, le=50),
        cursor: str | None = Query(default=None, max_length=1024),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> SiteSpatialWorkspacePageV1:
        after = (
            _decode_cursor(cursor, site_id=site_id, work_area_id=work_area_id)
            if cursor is not None
            else None
        )
        # Scope is enforced inside the catalog enumeration (fail-closed 404
        # with no cross-scope leakage); the default below is computed over
        # the full in-scope set, never over one page slice.
        all_observations = workspace.observations(site_id, work_area_id, principal)
        default = SiteSpatialWorkspace.entry_default(all_observations)
        candidates = tuple(
            entry
            for entry in all_observations
            if after is None or entry.observation_epoch_id > after
        )
        page_entries: list[WorkspaceObservationViewV1] = []
        has_more = False
        for index, candidate in enumerate(candidates[:limit]):
            tentative_has_more = index < len(candidates) - 1
            tentative = SiteSpatialWorkspacePageV1(
                site_id=site_id,
                work_area_id=work_area_id,
                observations=tuple([*page_entries, candidate]),
                entry_default=default,
                next_cursor=(
                    _encode_cursor(
                        site_id=site_id,
                        work_area_id=work_area_id,
                        after=candidate.observation_epoch_id,
                    )
                    if tentative_has_more
                    else None
                ),
                has_more=tentative_has_more,
            )
            if len(canonical_json_bytes(_page_wire(tentative))) > _MAX_PAGE_BYTES:
                if not page_entries:
                    raise HTTPException(
                        status_code=503, detail="SPATIAL_WORKSPACE_EXCEEDS_RESPONSE_BUDGET"
                    )
                has_more = True
                break
            page_entries.append(candidate)
        has_more = has_more or len(page_entries) < len(candidates)
        next_cursor = (
            _encode_cursor(
                site_id=site_id,
                work_area_id=work_area_id,
                after=page_entries[-1].observation_epoch_id,
            )
            if has_more and page_entries
            else None
        )
        page = SiteSpatialWorkspacePageV1(
            site_id=site_id,
            work_area_id=work_area_id,
            observations=tuple(page_entries),
            entry_default=default,
            next_cursor=next_cursor,
            has_more=has_more,
        )
        if len(canonical_json_bytes(_page_wire(page))) > _MAX_PAGE_BYTES:
            raise HTTPException(
                status_code=503, detail="SPATIAL_WORKSPACE_PAGE_EXCEEDS_RESPONSE_BUDGET"
            )
        return page

    return router
