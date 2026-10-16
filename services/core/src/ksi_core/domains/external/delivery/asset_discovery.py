"""Grant-filtered AI asset discovery with snapshot-bound pagination.

``SpatialDataAssetDiscovery`` projects only the metadata the single current
EXTERNAL_AI+READ grant authorizes for its exact asset: the grant rectangle
intersected with the inspected source extent. Candidates are hints from the
bounded authentic catalog; every projection re-resolves the exact scoped
revision/manifest/report from genuine stores. Cursors bind organization,
principal, scope, the permitted projection and the relevant grant/consent
bindings; a cursor never grants access.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts._spatial_data import require_utc
from ksi_event_contracts.external_artifact_validation import RasterMeasurementsV1
from ksi_event_contracts.spatial_asset_catalog import (
    SpatialAssetCatalogItemV1,
    SpatialAssetLifecycleStateV1,
)
from ksi_event_contracts.spatial_data import SpatialDataSourceV1
from ksi_event_contracts.spatial_data_ai import (
    SpatialDataAssetPageV1,
    SpatialDataAssetViewV1,
)
from ksi_event_contracts.spatial_data_authority import SpatialDataGrantV1, SpatialDataPolicyV1
from pydantic import ValidationError

from ksi_core.domains.external.delivery.errors import (
    SpatialDataAiDomainError,
    SpatialDataDomainError,
)
from ksi_core.identity.auth import Permission as _Permission
from ksi_core.identity.auth import Principal, PrincipalKind, principal_permissions

if TYPE_CHECKING:
    from datetime import datetime

    from ksi_core.domains.external.delivery.grants import SpatialDataGrantAuthorizer
    from ksi_core.domains.external.delivery.jobs import SpatialDataJobStore
    from ksi_core.domains.external.delivery.source import SpatialDataSourceResolver

_CURSOR_MAX_BYTES = 2048
_SNAPSHOT_MAX_BYTES = 256
_LAST_MAX_BYTES = 512
_ASSET_REF_RE = re.compile(r"^ksa-v1-[0-9a-f]{64}$")

_MODIFICATION_NOTICE = "Native rectangular crop"

#: Denials that suppress one asset candidate from AI listing. Dependency,
#: authority and representation failures propagate instead of empty success.
_LIST_SUPPRESSED = frozenset(
    {
        "NOT_FOUND",
        "PERMISSION_DENIED",
        "AI_EGRESS_DENIED",
        "GRANT_REQUIRED",
        "AMBIGUOUS_GRANT",
        "ACCESS_REVOKED",
        "ACCESS_EXPIRED",
        "OUTPUT_OUTSIDE_GRANT",
        "PROCESSING_LOCATION_DENIED",
        "SOURCE_NOT_MEASURED",
        "SOURCE_UNSEALED",
        "CRS_MISMATCH",
        "UNSUPPORTED_ARTIFACT_KIND",
        "UNSUPPORTED_SOURCE_PROFILE",
        "SOURCE_MEASUREMENTS_MISMATCH",
    }
)

#: Source-shape denials that make exact-asset detail a non-disclosing 404.
_DETAIL_MISSING = frozenset(
    {
        "NOT_FOUND",
        "GRANT_REQUIRED",
        "SOURCE_NOT_MEASURED",
        "SOURCE_UNSEALED",
        "CRS_MISMATCH",
        "UNSUPPORTED_ARTIFACT_KIND",
        "UNSUPPORTED_SOURCE_PROFILE",
    }
)


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(_: str) -> None:
    raise ValueError("nonfinite JSON forbidden")


def scope_hash(*, organization_id: str, principal_id: str, site_id: str, work_area_id: str) -> str:
    """Opaque scope binding for snapshot cursors; hashes, never raw identifiers."""
    return (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {
                    "organization": organization_id,
                    "principal": principal_id,
                    "site": site_id,
                    "area": work_area_id,
                }
            )
        ).hexdigest()
    )


def snapshot_digest(payload: dict[str, Any]) -> str:
    """Opaque projection binding; sorted permitted IDs/digests, never denied counts."""
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def encode_snapshot_cursor(*, scope: str, snapshot: str, last: str) -> str:
    """Opaque canonical cursor; carries hashes and the ordered last ID only."""
    if (
        type(scope) is not str
        or not scope
        or type(snapshot) is not str
        or not snapshot
        or type(last) is not str
        or not last
    ):
        raise ValueError("snapshot cursor requires explicit scope/snapshot/last")
    return base64.urlsafe_b64encode(
        canonical_json_bytes({"last": last, "scope": scope, "snapshot": snapshot})
    ).decode("ascii")


def decode_snapshot_cursor(cursor: str, *, scope: str) -> tuple[str, str]:
    """Strictly parse one snapshot cursor; malformed shape/scope is 422, never access."""
    if type(cursor) is not str or not 1 <= len(cursor) <= _CURSOR_MAX_BYTES:
        raise SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422)
    if type(scope) is not str or not scope:
        raise ValueError("snapshot cursor scope must be explicit")
    try:
        raw = base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True)
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_nonfinite
        )
    except (ValueError, UnicodeError) as exc:
        raise SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422) from exc
    if (
        type(payload) is not dict
        or set(payload) != {"scope", "snapshot", "last"}
        or type(payload["scope"]) is not str
        or _DIGEST_RE.fullmatch(payload["scope"]) is None
        or type(payload["snapshot"]) is not str
        or _DIGEST_RE.fullmatch(payload["snapshot"]) is None
        or type(payload["last"]) is not str
        or not 1 <= len(payload["last"]) <= _LAST_MAX_BYTES
        or payload["scope"] != scope
    ):
        raise SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422)
    canonical = encode_snapshot_cursor(
        scope=scope, snapshot=payload["snapshot"], last=payload["last"]
    )
    if canonical != cursor:
        raise SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422)
    return payload["snapshot"], payload["last"]


def _check_ai_reader(principal: Principal) -> None:
    if (
        principal.kind is not PrincipalKind.SPATIAL_DATA_MCP_CLIENT
        or principal.device_id is not None
        or principal.role is not None
        or _Permission.SPATIAL_DATA_READ not in principal_permissions(principal)
    ):
        raise SpatialDataDomainError("PERMISSION_DENIED", 403)


class SpatialDataAssetDiscovery:
    """Current grant-filtered asset projection over exact mounted Core participants."""

    def __init__(
        self,
        *,
        sources: SpatialDataSourceResolver,
        grants: SpatialDataGrantAuthorizer,
        jobs: SpatialDataJobStore,
        clock: Callable[[], datetime],
    ) -> None:
        if sources is None or grants is None or jobs is None:
            raise ValueError("asset discovery requires genuine Core participants")
        coordinators = {sources.coordinator, grants.coordinator, jobs.coordinator}
        if len({id(coordinator) for coordinator in coordinators}) != 1:
            raise ValueError("asset discovery participants must share one coordinator")
        if not jobs.uses_exact_participants(grants=grants, sources=sources):
            raise ValueError("asset discovery requires the same mounted Core participants")
        if not callable(clock):
            raise ValueError("asset discovery requires a clock")
        self._sources = sources
        self._grants = grants
        self._jobs = jobs
        self._clock = clock
        self._policy = jobs.policy

    @property
    def sources(self) -> SpatialDataSourceResolver:
        return self._sources

    @property
    def grants(self) -> SpatialDataGrantAuthorizer:
        return self._grants

    @property
    def jobs(self) -> SpatialDataJobStore:
        return self._jobs

    @property
    def policy(self) -> SpatialDataPolicyV1:
        return self._policy.model_copy(deep=True)

    def uses_exact_participants(
        self,
        *,
        sources: SpatialDataSourceResolver,
        grants: SpatialDataGrantAuthorizer,
        jobs: SpatialDataJobStore,
    ) -> bool:
        return sources is self._sources and grants is self._grants and jobs is self._jobs

    @staticmethod
    def _extent(measurements: RasterMeasurementsV1) -> tuple[float, float, float, float]:
        """Inspected source footprint from the native affine; north-up only, never TIFF parsing."""
        transform = measurements.transform
        a, b, _c, d, e, f = transform
        if b != 0.0 or d != 0.0 or not (a > 0.0) or not (e < 0.0):
            raise SpatialDataDomainError("UNSUPPORTED_SOURCE_PROFILE", 422)
        c = transform[2]
        left, right = c, c + a * measurements.width
        bottom, top = f + e * measurements.height, f
        if not all(math.isfinite(value) for value in (left, right, bottom, top)):
            raise SpatialDataDomainError("UNSUPPORTED_SOURCE_PROFILE", 422)
        return (left, bottom, right, top)

    @staticmethod
    def _intersect(
        granted: tuple[float, float, float, float],
        extent: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float] | None:
        """Exact grant rectangle intersected with inspected extent; empty means ungranted."""
        left = max(granted[0], extent[0])
        bottom = max(granted[1], extent[1])
        right = min(granted[2], extent[2])
        top = min(granted[3], extent[3])
        if not all(math.isfinite(value) for value in (left, bottom, right, top)) or not (
            left < right and bottom < top
        ):
            return None
        return (left, bottom, right, top)

    @staticmethod
    def _contains_whole_cell(
        permitted: tuple[float, float, float, float], measurements: RasterMeasurementsV1
    ) -> bool:
        """At least one whole native cell inside the permitted rectangle.

        PREPARE advertisement never expands rights to a partial pixel: a
        subpixel grant stays READ-only. Float comparisons stay conservative:
        only representably interior cells count, so no partial pixel is ever
        advertised as preparable.
        """
        a, b, c, d, e, f = measurements.transform
        if b != 0.0 or d != 0.0 or not (a > 0.0) or not (e < 0.0):
            return False
        ixmin, iymin, ixmax, iymax = permitted
        step_y = -e
        first_column = math.ceil((ixmin - c) / a)
        last_column = math.floor((ixmax - c) / a) - 1
        first_row = math.ceil((f - iymax) / step_y)
        last_row = math.floor((f - iymin) / step_y) - 1
        return first_column <= last_column and first_row <= last_row

    def _project(
        self,
        *,
        source: SpatialDataSourceV1,
        grant: SpatialDataGrantV1,
        candidate: SpatialAssetCatalogItemV1,
        now: datetime,
    ) -> SpatialDataAssetViewV1 | None:
        """One grant-filtered asset view; None when the grant authorizes zero pixels."""
        measurements = source.inspection.measurements
        if measurements is None:
            raise SpatialDataDomainError("SOURCE_NOT_MEASURED", 403)
        permitted = self._intersect(grant.allowed_bounds, self._extent(measurements))
        if permitted is None:
            return None
        lifecycle = candidate.lifecycle_state
        if lifecycle not in (
            SpatialAssetLifecycleStateV1.SEALED,
            SpatialAssetLifecycleStateV1.SUPERSEDED,
        ):
            raise SpatialDataDomainError("SOURCE_UNSEALED", 403)
        lifecycle_state = cast(Literal["SEALED", "SUPERSEDED"], lifecycle.value)
        operations: list[Literal["READ", "PREPARE"]] = ["READ"]
        if "PREPARE" in grant.operations and self._contains_whole_cell(permitted, measurements):
            # Fresh lane/policy/runtime where V1 requires it; a stale lane
            # surfaces here instead of a fake preparable crop.
            self._jobs.check_ai_prepare_lane(now=now)
            operations.append("PREPARE")
        raw_transform = measurements.transform
        transform: tuple[float, float, float, float, float, float] = (
            float(raw_transform[0]),
            float(raw_transform[1]),
            float(raw_transform[2]),
            float(raw_transform[3]),
            float(raw_transform[4]),
            float(raw_transform[5]),
        )
        resolution = (transform[0], -transform[4])
        dtype = measurements.dtype
        if dtype not in ("float32", "float64", "uint8"):
            raise SpatialDataDomainError("UNSUPPORTED_SOURCE_PROFILE", 422)
        try:
            return SpatialDataAssetViewV1(
                asset_ref=source.asset_ref,
                site_id=source.site_id,
                work_area_id=source.work_area_id,
                work_order_id=source.work_order_id,
                epoch_id=source.epoch_id,
                submission_ref=source.submission_ref,
                revision=source.revision,
                artifact_kind=source.artifact_kind,
                lifecycle_state=lifecycle_state,
                observed_sha256=source.observed_sha256,
                observed_size_bytes=source.observed_size_bytes,
                inspection_report_digest=source.inspection_report_digest,
                inspector_build_digest=source.inspector_build_digest,
                observed_crs_identifier=measurements.observed_crs_identifier,
                observed_crs_digest=measurements.observed_crs_digest,
                observed_crs_units=source.observed_crs_units,
                observed_vertical_reference=measurements.observed_vertical_reference,
                transform=transform,
                resolution=resolution,
                band_count=measurements.band_count,
                dtype=cast(Literal["float32", "float64", "uint8"], dtype),
                permitted_bounds=permitted,
                capture_started_at=source.capture_started_at,
                capture_ended_at=source.capture_ended_at,
                producer_processed_at=source.producer_processed_at,
                declaration_recorded_at=source.declaration_recorded_at,
                timestamp_provenance="SUBMISSION_DECLARATION",
                permitted_operations=tuple(operations),
                restrictions=(),
                attribution=grant.attribution,
                modification_notice=_MODIFICATION_NOTICE,
                accuracy_assessed=False,
                analysis_status="NOT_EVALUATED",
            )
        except ValidationError as exc:
            raise SpatialDataDomainError("UNSUPPORTED_SOURCE_PROFILE", 422) from exc

    def _resolve_for_list_local(
        self,
        *,
        item: SpatialAssetCatalogItemV1,
        principal: Principal,
        report_digest: str,
        now: datetime,
    ) -> tuple[SpatialDataSourceV1, SpatialDataGrantV1]:
        """Local-only candidate resolution for final send gates; never a remote preflight."""
        source = self._sources.resolve_local_current(
            candidate=item, principal=principal, report_digest=report_digest, now=now
        )
        grant = self._grants.select_metadata_current(
            source=source, principal=principal, policy=self._policy, now=now
        )
        return source, grant

    def get(
        self,
        *,
        site_id: str,
        work_area_id: str,
        asset_ref: str,
        principal: Principal,
        now: datetime,
    ) -> SpatialDataAssetViewV1:
        """Exact granted asset projection; unknown/foreign/ungranted is the same 404."""
        require_utc(now)
        _check_ai_reader(principal)
        if type(asset_ref) is not str or _ASSET_REF_RE.fullmatch(asset_ref) is None:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        self._sources.require_ai_scope(site_id, work_area_id, principal)
        matches = [
            item
            for item in self._sources.candidates(
                site_id=site_id, work_area_id=work_area_id, principal=principal
            )
            if item.asset_ref == asset_ref
        ]
        if len(matches) != 1:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        try:
            source = self._sources.resolve_candidate(candidate=matches[0], principal=principal)
        except SpatialDataDomainError as exc:
            if exc.reason in _DETAIL_MISSING:
                raise SpatialDataDomainError("NOT_FOUND", 404) from exc
            raise
        try:
            grant = self._grants.select_metadata_current(
                source=source, principal=principal, policy=self._policy, now=now
            )
        except SpatialDataDomainError as exc:
            # Ambiguity stays an explicit 403 with no payload; absent or
            # unusable rights are the same non-disclosing 404 as unknown.
            if exc.reason == "GRANT_REQUIRED":
                raise SpatialDataDomainError("NOT_FOUND", 404) from exc
            raise
        view = self._project(source=source, grant=grant, candidate=matches[0], now=now)
        if view is None:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        return view

    def _snapshot(
        self,
        entries: Sequence[tuple[str, SpatialDataAssetViewV1, str]],
        *,
        omitted: Sequence[str] = (),
        complete: bool = True,
    ) -> str:
        """Bind the current permitted projection plus relevant grant/consent bindings.

        ``omitted`` carries the sorted asset refs suppressed only for
        over-budget retained history (granted candidates that could not be
        projected within the listing budget); ``complete`` is False exactly
        when that set is non-empty. Both bind the snapshot so a cursor stays
        valid only while the admitted set and the omission set match. Never
        includes denied counts or ungranted identities: never-granted and
        unresolvable candidates stay invisible here as in the page.
        """
        views: list[str] = []
        size = 0
        for _, view, _ in entries:
            body = canonical_json_bytes(view.model_dump(by_alias=True, mode="json"))
            if len(body) > self._policy.max_json_bytes:
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
            size += len(body)
            views.append("sha256:" + hashlib.sha256(body).hexdigest())
        if size > self._policy.max_snapshot_bytes:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        activation = self._jobs.activation
        omitted_refs = sorted(omitted)
        if type(complete) is not bool or complete == (len(omitted_refs) > 0):
            raise ValueError("snapshot completeness must match the omission set")
        return snapshot_digest(
            {
                "refs": sorted(ref for ref, _, _ in entries),
                "views": sorted(views),
                "grants": sorted(grant for _, _, grant in entries),
                "omitted": omitted_refs,
                "complete": complete,
                "consent": True,
                "policy": self._policy.policy_digest,
                "activation": activation.activation_digest,
            }
        )

    def list(
        self,
        *,
        site_id: str,
        work_area_id: str,
        principal: Principal,
        limit: int,
        cursor: str | None,
        now: datetime,
    ) -> SpatialDataAssetPageV1:
        """Grant-filtered page in stable assetRef order; filter precedes pagination."""
        return self._page(
            site_id=site_id,
            work_area_id=work_area_id,
            principal=principal,
            limit=limit,
            cursor=cursor,
            now=now,
            gate=None,
        )

    @staticmethod
    def _classify_candidate(
        item: SpatialAssetCatalogItemV1,
    ) -> tuple[str, int, str | None]:
        """Bounded local readiness class: lifecycle, revision, observed facts.

        Seal/manifest arrival flips the class without any report resolution,
        so the final gate notices readiness drift through owner catalog reads
        only. Pure report arrival on an already-sealed candidate keeps its
        class; that residual omission (never a disclosure) needs a new local
        report-existence path, which is out of scope.
        """
        observed = item.observed.sha256 if item.observed is not None else None
        return (item.lifecycle_state.value, item.revision, observed)

    def _collect_entries(
        self,
        *,
        items: tuple[SpatialAssetCatalogItemV1, ...],
        principal: Principal,
        now: datetime,
        gate: dict[str, object] | None,
    ) -> tuple[Sequence[tuple[str, SpatialDataAssetViewV1, str]], dict[str, object]]:
        """Project permitted views for candidates; filter precedes pagination.

        ``gate`` is None on the preflight path (remote inspection snapshot
        allowed) and carries the preflight gate context on the final local
        gate path (no remote resolution): ``{"digests": {assetRef: retained
        report digest}, "unready": {assetRef: readiness class},
        "states": {assetRef: retained-state digest or null},
        "omitted": {assetRef: readiness class},
        "classes": {assetRef: readiness class},
        "candidates": frozenset(...)}``. Digests are recorded for every
        source-resolved candidate, admitted or suppressed, so grant/bounds
        drift re-admits nothing silently. Readiness classes bind
        lifecycle/revision/observed facts per tracked candidate, so a granted
        candidate turning seal-ready between preflight and gate fails closed
        instead of serving an incomplete cursor. ``omitted`` holds only
        granted candidates suppressed for over-budget retained history (no
        counts or identities leave the page or cursor beyond the opaque
        snapshot binding); a granted candidate turning projectable between
        preflight and gate fails closed instead of silent admission.
        A candidate the preflight never classified is snapshot drift, never
        admitted. Never-granted unresolvable candidates stay invisible without
        admission, payload, or cursor cost.
        """
        digests: dict[str, str] = {}
        unready: dict[str, tuple[str, int, str | None]] = {}
        states: dict[str, str | None] = {}
        omitted: dict[str, tuple[str, int, str | None]] = {}
        if gate is not None:
            pre_digests = gate.get("digests")
            pre_unready = gate.get("unready")
            pre_states = gate.get("states")
            pre_omitted = gate.get("omitted")
            pre_classes = gate.get("classes")
            pre_candidates = gate.get("candidates")
            if (
                type(pre_digests) is not dict
                or type(pre_unready) is not dict
                or type(pre_states) is not dict
                or type(pre_omitted) is not dict
                or type(pre_classes) is not dict
                or not isinstance(pre_candidates, frozenset)
            ):
                raise ValueError("asset page gate requires the preflight gate context")
        else:
            pre_digests = {}
            pre_unready = {}
            pre_states = {}
            pre_omitted = {}
            pre_classes = {}
            pre_candidates = frozenset()
        entries: list[tuple[str, SpatialDataAssetViewV1, str]] = []
        for item in items:
            ref = item.asset_ref
            digest: str | None = None
            if gate is not None:
                assert (
                    isinstance(pre_digests, dict)
                    and isinstance(pre_unready, dict)
                    and isinstance(pre_omitted, dict)
                    and isinstance(pre_classes, dict)
                    and isinstance(pre_candidates, frozenset)
                )
                if ref not in pre_candidates:
                    raise SpatialDataAiDomainError("SPATIAL_DATA_CURSOR_STALE", 409)
                if ref not in pre_classes:
                    # Never-granted and unresolvable at preflight: stays
                    # invisible without admission, payload, or cursor cost.
                    continue
                if pre_classes[ref] != self._classify_candidate(item):
                    raise SpatialDataAiDomainError("SPATIAL_DATA_CURSOR_STALE", 409)
                if ref in pre_omitted:
                    if item.lifecycle_state is SpatialAssetLifecycleStateV1.UNSEALED:
                        omitted[ref] = self._classify_candidate(item)
                        continue
                    try:
                        self._sources.local_retained_state(candidate=item, principal=principal)
                    except SpatialDataDomainError as exc:
                        if exc.reason == "NOT_FOUND":
                            raise SpatialDataAiDomainError(
                                "SPATIAL_DATA_CURSOR_STALE", 409
                            ) from exc
                        if exc.reason == "RETAINED_HISTORY_LIMIT_EXCEEDED":
                            omitted[ref] = self._classify_candidate(item)
                            continue
                        raise
                    raise SpatialDataAiDomainError("SPATIAL_DATA_CURSOR_STALE", 409)
                if ref in pre_unready:
                    if item.lifecycle_state is SpatialAssetLifecycleStateV1.UNSEALED:
                        continue
                    try:
                        current_state = self._sources.local_retained_state(
                            candidate=item, principal=principal
                        )
                    except SpatialDataDomainError as exc:
                        if exc.reason == "NOT_FOUND":
                            raise SpatialDataAiDomainError(
                                "SPATIAL_DATA_CURSOR_STALE", 409
                            ) from exc
                        if exc.reason == "RETAINED_HISTORY_LIMIT_EXCEEDED":
                            omitted[ref] = self._classify_candidate(item)
                            continue
                        raise
                    if current_state is None or current_state != pre_states.get(ref):
                        raise SpatialDataAiDomainError("SPATIAL_DATA_CURSOR_STALE", 409)
                    continue
                raw = pre_digests.get(ref)
                if type(raw) is not str or not raw:
                    raise SpatialDataAiDomainError("SPATIAL_DATA_CURSOR_STALE", 409)
                digest = raw
            try:
                if digest is None:
                    source = self._sources.resolve_candidate(candidate=item, principal=principal)
                else:
                    source = self._sources.resolve_local_current(
                        candidate=item,
                        principal=principal,
                        report_digest=digest,
                        now=now,
                    )
            except SpatialDataDomainError as exc:
                if exc.reason == "RETAINED_HISTORY_LIMIT_EXCEEDED":
                    # Granted but unprojectable within the listing budget:
                    # suppress the candidate and mark the page incomplete.
                    # Without a beneficiary grant it stays invisible (no flag
                    # leak, no disclosure).
                    if self._grants.has_beneficiary_grants(
                        site_id=item.site_id,
                        work_area_id=item.work_area_id,
                        asset_ref=ref,
                        principal=principal,
                    ):
                        omitted[ref] = self._classify_candidate(item)
                    continue
                if exc.reason in _LIST_SUPPRESSED:
                    if self._grants.has_beneficiary_grants(
                        site_id=item.site_id,
                        work_area_id=item.work_area_id,
                        asset_ref=ref,
                        principal=principal,
                    ):
                        unready[ref] = self._classify_candidate(item)
                        try:
                            states[ref] = self._sources.local_retained_state(
                                candidate=item, principal=principal
                            )
                        except SpatialDataDomainError as state_exc:
                            if state_exc.reason == "RETAINED_HISTORY_LIMIT_EXCEEDED":
                                del unready[ref]
                                states.pop(ref, None)
                                omitted[ref] = self._classify_candidate(item)
                            elif state_exc.reason not in _LIST_SUPPRESSED:
                                raise
                            else:
                                states[ref] = None
                    continue
                raise
            digests[ref] = source.inspection_report_digest
            try:
                grant = self._grants.select_metadata_current(
                    source=source, principal=principal, policy=self._policy, now=now
                )
                view = self._project(source=source, grant=grant, candidate=item, now=now)
            except SpatialDataDomainError as exc:
                if exc.reason == "RETAINED_HISTORY_LIMIT_EXCEEDED":
                    digests.pop(ref, None)
                    if self._grants.has_beneficiary_grants(
                        site_id=item.site_id,
                        work_area_id=item.work_area_id,
                        asset_ref=ref,
                        principal=principal,
                    ):
                        omitted[ref] = self._classify_candidate(item)
                    continue
                if exc.reason in _LIST_SUPPRESSED:
                    continue
                raise
            if view is None:
                continue
            entries.append((ref, view, grant.grant_digest or ""))
        by_ref = {item.asset_ref: item for item in items}
        classes = {
            ref: self._classify_candidate(by_ref[ref])
            for ref in list(digests)
            + [ref for ref in unready if ref not in digests]
            + [ref for ref in omitted if ref not in digests and ref not in unready]
            if ref in by_ref
        }
        context: dict[str, object] = {
            "digests": digests,
            "unready": unready,
            "states": states,
            "omitted": omitted,
            "classes": classes,
            "candidates": frozenset(by_ref),
        }
        return entries, context

    def _page(
        self,
        *,
        site_id: str,
        work_area_id: str,
        principal: Principal,
        limit: int,
        cursor: str | None,
        now: datetime,
        gate: dict[str, object] | None,
    ) -> SpatialDataAssetPageV1:
        """Grant-filtered page in stable assetRef order; filter precedes pagination."""
        page, _ = self._project_paged(
            site_id=site_id,
            work_area_id=work_area_id,
            principal=principal,
            limit=limit,
            cursor=cursor,
            now=now,
            gate=gate,
        )
        return page

    def _project_paged(
        self,
        *,
        site_id: str,
        work_area_id: str,
        principal: Principal,
        limit: int,
        cursor: str | None,
        now: datetime,
        gate: dict[str, object] | None,
    ) -> tuple[SpatialDataAssetPageV1, dict[str, object]]:
        """Project one page plus the gate context for its send-time gate.

        The gate context carries every source-resolved candidate digest plus
        the source-unresolvable set, including candidates beyond the page
        slice: the final local gate re-projects the whole set, never a slice.
        Over-budget retained history suppresses only its granted candidates
        and marks the page incomplete (no counts or identities in the page or
        cursor beyond the opaque snapshot binding); nothing projectable means
        the typed operator-actionable refusal instead of an empty page. The
        catalog over-budget stays a whole-page refusal.
        """
        require_utc(now)
        if type(limit) is not int or not 1 <= limit <= min(200, self._policy.max_list_records):
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 422)
        if cursor is not None and type(cursor) is not str:
            raise SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422)
        _check_ai_reader(principal)
        self._sources.require_ai_scope(site_id, work_area_id, principal)
        items = self._sources.candidates(
            site_id=site_id, work_area_id=work_area_id, principal=principal
        )
        if len(items) > self._policy.max_list_records:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        entries, gate_context = self._collect_entries(
            items=items, principal=principal, now=now, gate=gate
        )
        raw_omitted = gate_context.get("omitted", {})
        if not isinstance(raw_omitted, dict):
            raise ValueError("asset page gate context carries an omission mapping")
        omitted_refs = sorted(raw_omitted)
        if not entries and omitted_refs:
            raise SpatialDataDomainError("RETAINED_HISTORY_LIMIT_EXCEEDED", 503)
        complete = not omitted_refs
        snapshot = self._snapshot(entries, omitted=tuple(omitted_refs), complete=complete)
        scope = scope_hash(
            organization_id=principal.organization_id,
            principal_id=principal.principal_id,
            site_id=site_id,
            work_area_id=work_area_id,
        )
        refs = [ref for ref, _, _ in entries]
        if cursor is None:
            start = 0
        else:
            presented, last = decode_snapshot_cursor(cursor, scope=scope)
            if presented != snapshot:
                raise SpatialDataAiDomainError("SPATIAL_DATA_CURSOR_STALE", 409)
            try:
                start = refs.index(last) + 1
            except ValueError as exc:
                raise SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422) from exc
        selected = entries[start : start + limit]
        more = start + len(selected) < len(entries)
        next_cursor = (
            encode_snapshot_cursor(scope=scope, snapshot=snapshot, last=selected[-1][0])
            if more
            else None
        )
        return SpatialDataAssetPageV1(
            items=tuple(view for _, view, _ in selected),
            next_cursor=next_cursor,
            page_complete=complete,
        ), gate_context

    def list_projection(
        self,
        *,
        site_id: str,
        work_area_id: str,
        principal: Principal,
        limit: int,
        cursor: str | None,
        now: datetime,
    ) -> tuple[SpatialDataAssetPageV1, dict[str, object]]:
        """Preflight page projection with its gate context for the send-time gate."""
        return self._project_paged(
            site_id=site_id,
            work_area_id=work_area_id,
            principal=principal,
            limit=limit,
            cursor=cursor,
            now=now,
            gate=None,
        )

    def recheck_view(
        self, *, view: SpatialDataAssetViewV1, principal: Principal, now: datetime
    ) -> bytes:
        """Local-only final gate for one prepared asset view; never a remote preflight.

        Re-establishes the exact prepared projection from genuine local owner
        currentness (scope, candidate, retained/current report, unique grant,
        lifecycle, bounds) and returns its canonical bytes. Any drift or denial
        raises instead of authorizing stale bytes; the caller compares digests
        for the typed stale conflict.
        """
        require_utc(now)
        if not isinstance(view, SpatialDataAssetViewV1):
            raise ValueError("asset recheck publishes typed asset views only")
        _check_ai_reader(principal)
        self._sources.require_ai_scope(view.site_id, view.work_area_id, principal)
        matches = [
            item
            for item in self._sources.candidates(
                site_id=view.site_id, work_area_id=view.work_area_id, principal=principal
            )
            if item.asset_ref == view.asset_ref
        ]
        if len(matches) != 1:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        try:
            source, grant = self._resolve_for_list_local(
                item=matches[0],
                principal=principal,
                report_digest=view.inspection_report_digest,
                now=now,
            )
        except SpatialDataDomainError as exc:
            # Absent or unusable rights stay the same non-disclosing 404 as
            # the detail path; live denials (revocation, consent, ambiguity)
            # propagate with their typed reasons.
            if exc.reason in _DETAIL_MISSING or exc.reason == "GRANT_REQUIRED":
                raise SpatialDataDomainError("NOT_FOUND", 404) from exc
            raise
        fresh = self._project(source=source, grant=grant, candidate=matches[0], now=now)
        if fresh is None:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        return canonical_json_bytes(fresh.model_dump(by_alias=True, mode="json"))

    def recheck_page(
        self,
        *,
        site_id: str,
        work_area_id: str,
        principal: Principal,
        limit: int,
        cursor: str | None,
        gate: dict[str, object],
        now: datetime,
    ) -> bytes:
        """Local-only final gate for one preflight page; never a remote preflight.

        ``gate`` is the preflight projection's gate context covering every
        source-resolved candidate digest plus the source-unresolvable set,
        including entries beyond the page slice. Unclassified candidates are
        snapshot drift, refused rather than admitted; the caller compares
        digests for the typed stale conflict.
        """
        fresh, _ = self._project_paged(
            site_id=site_id,
            work_area_id=work_area_id,
            principal=principal,
            limit=limit,
            cursor=cursor,
            now=now,
            gate=gate,
        )
        return canonical_json_bytes(fresh.model_dump(by_alias=True, mode="json"))
