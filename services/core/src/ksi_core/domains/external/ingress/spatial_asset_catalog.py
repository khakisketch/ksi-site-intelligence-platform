"""Read-only projection of scoped external reconstruction artifact metadata."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.spatial_asset_catalog import (
    SpatialAssetCatalogDetailV1,
    SpatialAssetCatalogItemV1,
    SpatialAssetCatalogPageV1,
    SpatialAssetDeclaredFactsV1,
    SpatialAssetInspectedRasterFactsV1,
    SpatialAssetInspectionV1,
    SpatialAssetLifecycleStateV1,
    SpatialAssetObservedFactsV1,
    SpatialAssetObservedVerticalReferenceV1,
)

from ksi_core.domains.external.ingress.external_artifact_inspections import (
    ExternalArtifactInspectionSnapshotBudgetExceeded,
    ExternalArtifactInspectionStore,
)
from ksi_core.domains.external.ingress.external_reconstruction import (
    ExternalReconstructionListBudgetExceeded,
    ExternalReconstructionRevision,
    ExternalReconstructionStore,
    build_external_reconstruction_submission_ref,
)
from ksi_core.domains.sites.observation_work_orders import SiteWorkOrderListBudgetExceeded
from ksi_core.identity.auth import Permission, Principal, require_permission

_NOT_FOUND = "SITE_SPATIAL_ASSET_NOT_FOUND"
_MAX_PAGE_BYTES = 512 * 1024
_MAX_SITE_WORK_ORDERS = 256
_MAX_SITE_REVISIONS = 2048
_MAX_SUBMISSIONS_PER_WORK_ORDER = 256
_MAX_INSPECTION_RECORDS_PER_SUBJECT = 128
_MAX_RETAINED_POLICIES_PER_INSPECTION = 64
_ASSET_REF_RE = re.compile(r"^ksa-v1-[0-9a-f]{64}$")
_CURSOR_RE = re.compile(r"^[A-Za-z0-9_-]{1,1024}$")


class SpatialAssetCatalog:
    """Build catalog views only from current scoped Core stores."""

    def __init__(
        self,
        *,
        reconstruction: ExternalReconstructionStore,
        work_orders: Any,
        sites: Any,
        work_areas: Any,
        inspections: ExternalArtifactInspectionStore | None,
    ) -> None:
        self._reconstruction = reconstruction
        self._work_orders = work_orders
        self._sites = sites
        self._work_areas = work_areas
        self._inspections = inspections

    def _require_scope(self, site_id: str, work_area_id: str, principal: Principal) -> None:
        if (
            principal.allowed_site_ids is not None and site_id not in principal.allowed_site_ids
        ) or (
            principal.allowed_work_area_ids is not None
            and work_area_id not in principal.allowed_work_area_ids
        ):
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        site = self._sites.get_scoped(site_id, principal.organization_id)
        area = self._work_areas.get(work_area_id)
        if site is None or area is None or area.site_id != site_id:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)

    @staticmethod
    def _submission_ref(record: ExternalReconstructionRevision) -> str:
        return build_external_reconstruction_submission_ref(
            organization_id=record.submission.organization_id,
            work_order_id=record.work_order_id,
            submission_id=record.submission.submission_id,
        )

    @staticmethod
    def _asset_ref(submission_ref: str, revision: int, artifact_id: str) -> str:
        identity = {
            "version": "spatial-asset-ref.v1",
            "submissionRef": submission_ref,
            "revision": revision,
            "artifactId": artifact_id,
        }
        return "ksa-v1-" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()

    def _inspection(
        self, record: ExternalReconstructionRevision, artifact_id: str
    ) -> SpatialAssetInspectionV1:
        manifest = record.manifest
        if manifest is None:
            return SpatialAssetInspectionV1(state="PENDING_SEAL")
        if self._inspections is None:
            return SpatialAssetInspectionV1(state="INSPECTION_NOT_CONFIGURED")
        # Only admitted sealed records enter this projection; missing digests are not inferred.
        assert record.submission.submission_digest is not None
        assert manifest.manifest_digest is not None
        subject = SealedExternalSubjectV1(
            organization_id=record.submission.organization_id,
            site_id=record.submission.site_id,
            work_order_id=record.work_order_id,
            submission_id=record.submission.submission_id,
            revision=record.submission.revision,
            submission_digest=record.submission.submission_digest,
            manifest_digest=manifest.manifest_digest,
        )
        try:
            snapshot = self._inspections.public_snapshot_bounded(
                subject,
                max_records=_MAX_INSPECTION_RECORDS_PER_SUBJECT,
                max_policy_records=_MAX_RETAINED_POLICIES_PER_INSPECTION,
            )
        except ExternalArtifactInspectionSnapshotBudgetExceeded as exc:
            raise HTTPException(
                status_code=503, detail="SPATIAL_ASSET_SOURCE_BUDGET_EXCEEDED"
            ) from exc
        report = snapshot.report
        assert report is None or report.report_digest is not None
        report_digest = report.report_digest if report is not None else None
        outcome = (
            next(
                (
                    item
                    for item in report.measurement_payload.outcomes
                    if item.artifact_id == artifact_id
                ),
                None,
            )
            if report is not None
            else None
        )
        return SpatialAssetInspectionV1(
            state=snapshot.state,
            report_digest=report.report_digest if report is not None else None,
            outcome=outcome.outcome.value if outcome is not None else None,
            reason=outcome.reason if outcome is not None else None,
            inspector_build_digest=report.inspector_build_digest if report is not None else None,
            raster=(
                SpatialAssetInspectedRasterFactsV1(
                    source_report_digest=report_digest,
                    inspector_build_digest=report.inspector_build_digest,
                    observed_crs_identifier=outcome.measurements.observed_crs_identifier,
                    observed_crs_wkt=outcome.measurements.observed_crs_wkt,
                    observed_crs_digest=outcome.measurements.observed_crs_digest,
                    observed_vertical_reference=(
                        SpatialAssetObservedVerticalReferenceV1(
                            identifier=outcome.measurements.observed_vertical_reference.identifier,
                            basis=outcome.measurements.observed_vertical_reference.basis,
                        )
                        if outcome.measurements.observed_vertical_reference is not None
                        else None
                    ),
                    transform=outcome.measurements.transform,
                    footprint_wkt=outcome.measurements.footprint_wkt,
                    footprint_digest=outcome.measurements.footprint_digest,
                    width=outcome.measurements.width,
                    height=outcome.measurements.height,
                )
                if outcome is not None
                and outcome.outcome.value == "MEASURED"
                and outcome.measurements is not None
                and report is not None
                and report_digest is not None
                else None
            ),
        )

    def _iter_revision_items(
        self,
        *,
        site_id: str,
        work_area_id: str,
        record: ExternalReconstructionRevision,
        latest_revision: int,
    ) -> Iterator[SpatialAssetCatalogItemV1]:
        """Yield one projected catalog item at a time; budgets bind before accumulation.

        The caller checks its remaining item/byte budgets before appending each
        yielded item, so an over-budget revision never materializes a full
        tuple first. Callers omitting budgets consume the identical sequence.
        """
        submission = record.submission
        submission_ref = self._submission_ref(record)
        lifecycle = (
            SpatialAssetLifecycleStateV1.SUPERSEDED
            if submission.revision < latest_revision
            else SpatialAssetLifecycleStateV1.SEALED
            if record.manifest is not None
            else SpatialAssetLifecycleStateV1.UNSEALED
        )
        observed = (
            {entry.artifact_id: entry for entry in record.manifest.entries}
            if record.manifest is not None
            else {}
        )
        if record.manifest is not None:
            assert record.manifest.manifest_digest is not None
        manifest_digest = record.manifest.manifest_digest if record.manifest is not None else None
        for declared in submission.artifacts:
            entry = observed.get(declared.artifact_id)
            observed_facts = (
                SpatialAssetObservedFactsV1(
                    manifest_digest=manifest_digest,
                    observed_at=record.manifest.observed_at,
                    sha256=entry.observed_sha256,
                    size_bytes=entry.observed_size_bytes,
                    content_type=entry.observed_content_type,
                )
                if record.manifest is not None and entry is not None and manifest_digest is not None
                else None
            )
            yield SpatialAssetCatalogItemV1(
                asset_ref=self._asset_ref(
                    submission_ref, submission.revision, declared.artifact_id
                ),
                site_id=site_id,
                work_area_id=work_area_id,
                work_order_id=record.work_order_id,
                observation_epoch_id=record.observation_epoch_id,
                submission_ref=submission_ref,
                revision=submission.revision,
                artifact_id=declared.artifact_id,
                kind=declared.kind,
                lifecycle_state=lifecycle,
                declared=SpatialAssetDeclaredFactsV1(
                    file_name=declared.file_name,
                    format=declared.format,
                    content_type=declared.content_type,
                    sha256=declared.declared_sha256,
                    size_bytes=declared.declared_size_bytes,
                    crs=declared.declared_crs,
                    vertical_reference=declared.declared_vertical_reference,
                    gsd_m=declared.declared_gsd_m,
                    submitted_at=submission.submitted_at,
                    producer_completed_at=(submission.producer_declaration.completed_at),
                    capture_started_at=submission.input_declaration.capture_started_at,
                    capture_ended_at=submission.input_declaration.capture_ended_at,
                    capture_date=getattr(submission.input_declaration, "capture_date", None),
                ),
                observed=observed_facts,
                inspection=SpatialAssetInspectionV1(state="INSPECTION_NOT_QUERIED"),
            )

    def items(
        self,
        site_id: str,
        work_area_id: str,
        principal: Principal,
        *,
        max_items: int | None = None,
        max_bytes: int | None = None,
    ) -> tuple[SpatialAssetCatalogItemV1, ...]:
        """Scoped catalog candidates; optional budgets refuse overage, never truncate.

        Callers omitting the new optional budgets retain existing behavior.
        The AI discovery lane passes its explicit data-policy budgets so
        candidate work stays finite before materialization.
        """
        if max_items is not None and (type(max_items) is not int or max_items < 0):
            raise ValueError("catalog item budget must be a nonnegative integer or null")
        if max_bytes is not None and (type(max_bytes) is not int or max_bytes < 0):
            raise ValueError("catalog byte budget must be a nonnegative integer or null")
        self._require_scope(site_id, work_area_id, principal)
        try:
            orders = self._work_orders.list_for_site_bounded(
                site_id,
                organization_id=principal.organization_id,
                max_records=_MAX_SITE_WORK_ORDERS,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=_NOT_FOUND) from exc
        except SiteWorkOrderListBudgetExceeded as exc:
            raise HTTPException(
                status_code=503, detail="SPATIAL_ASSET_SOURCE_BUDGET_EXCEEDED"
            ) from exc

        all_items: list[SpatialAssetCatalogItemV1] = []
        remaining_revisions = _MAX_SITE_REVISIONS
        remaining_items = max_items
        remaining_bytes = max_bytes
        for order in orders:
            # There is no per-artifact footprint in the ingress contract. A multi-area
            # WorkOrder cannot safely bind its exports to one WorkArea.
            if order.work_area_ids != [work_area_id]:
                continue
            try:
                records = self._reconstruction.list_bounded_for_work_order(
                    order.work_order_id,
                    organization_id=principal.organization_id,
                    site_id=site_id,
                    max_submissions=_MAX_SUBMISSIONS_PER_WORK_ORDER,
                    max_revisions=remaining_revisions,
                )
            except ExternalReconstructionListBudgetExceeded as exc:
                raise HTTPException(
                    status_code=503, detail="SPATIAL_ASSET_SOURCE_BUDGET_EXCEEDED"
                ) from exc
            remaining_revisions -= len(records)
            latest_by_submission: dict[str, int] = {}
            for record in records:
                ref = self._submission_ref(record)
                latest_by_submission[ref] = max(
                    latest_by_submission.get(ref, 0), record.submission.revision
                )
            for record in records:
                ref = self._submission_ref(record)
                for item in self._iter_revision_items(
                    site_id=site_id,
                    work_area_id=work_area_id,
                    record=record,
                    latest_revision=latest_by_submission[ref],
                ):
                    # Remaining optional budgets bind per item before any
                    # accumulation: overage is an explicit refusal, never a
                    # truncated success. Omitted budgets keep existing callers.
                    if remaining_items is not None:
                        if remaining_items <= 0:
                            raise HTTPException(
                                status_code=503,
                                detail="SPATIAL_ASSET_SOURCE_BUDGET_EXCEEDED",
                            )
                        remaining_items -= 1
                    if remaining_bytes is not None:
                        item_bytes = len(
                            canonical_json_bytes(item.model_dump(by_alias=True, mode="json"))
                        )
                        if item_bytes > remaining_bytes:
                            raise HTTPException(
                                status_code=503,
                                detail="SPATIAL_ASSET_SOURCE_BUDGET_EXCEEDED",
                            )
                        remaining_bytes -= item_bytes
                    all_items.append(item)
        return tuple(sorted(all_items, key=lambda item: item.asset_ref))

    def with_inspection(
        self, item: SpatialAssetCatalogItemV1, principal: Principal
    ) -> SpatialAssetCatalogItemV1:
        """Attach current inspection only after an item is selected for response."""
        self._require_scope(item.site_id, item.work_area_id, principal)
        submission_id = self._reconstruction.resolve_submission_ref(
            item.work_order_id,
            item.submission_ref,
            organization_id=principal.organization_id,
            site_id=item.site_id,
        )
        if submission_id is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        record = self._reconstruction.get(
            item.work_order_id,
            submission_id,
            item.revision,
            organization_id=principal.organization_id,
            site_id=item.site_id,
        )
        if record is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        return item.model_copy(update={"inspection": self._inspection(record, item.artifact_id)})


def _encode_cursor(*, site_id: str, work_area_id: str, after: str) -> str:
    payload = canonical_json_bytes(
        {"version": 1, "siteId": site_id, "workAreaId": work_area_id, "after": after}
    )
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, *, site_id: str, work_area_id: str) -> str:
    if _CURSOR_RE.fullmatch(cursor) is None:
        raise HTTPException(status_code=400, detail="INVALID_SPATIAL_ASSET_CURSOR")
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="INVALID_SPATIAL_ASSET_CURSOR") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "siteId", "workAreaId", "after"}
        or payload.get("version") != 1
        or payload.get("siteId") != site_id
        or payload.get("workAreaId") != work_area_id
        or not isinstance(payload.get("after"), str)
        or _ASSET_REF_RE.fullmatch(payload["after"]) is None
        or _encode_cursor(site_id=site_id, work_area_id=work_area_id, after=payload["after"])
        != cursor
    ):
        raise HTTPException(status_code=400, detail="INVALID_SPATIAL_ASSET_CURSOR")
    return payload["after"]


def _page_wire(page: SpatialAssetCatalogPageV1) -> dict[str, Any]:
    return page.model_dump(by_alias=True, mode="json")


def build_spatial_asset_catalog_router(
    *,
    reconstruction: ExternalReconstructionStore,
    work_orders: Any,
    sites: Any,
    work_areas: Any,
    inspections: ExternalArtifactInspectionStore | None,
) -> APIRouter:
    catalog = SpatialAssetCatalog(
        reconstruction=reconstruction,
        work_orders=work_orders,
        sites=sites,
        work_areas=work_areas,
        inspections=inspections,
    )
    router = APIRouter(tags=["spatial-asset-catalog"])
    read = require_permission(Permission.SITES_READ)

    @router.get(
        "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-assets",
        response_model=SpatialAssetCatalogPageV1,
    )
    def list_assets(
        site_id: str,
        work_area_id: str,
        limit: int = Query(default=20, ge=1, le=50),
        cursor: str | None = Query(default=None, max_length=1024),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> SpatialAssetCatalogPageV1:
        catalog._require_scope(site_id, work_area_id, principal)
        after = (
            _decode_cursor(cursor, site_id=site_id, work_area_id=work_area_id)
            if cursor is not None
            else None
        )
        items = catalog.items(site_id, work_area_id, principal)
        candidates = tuple(item for item in items if after is None or item.asset_ref > after)
        page_items: list[SpatialAssetCatalogItemV1] = []
        has_more = False
        for index, candidate in enumerate(candidates[:limit]):
            item = catalog.with_inspection(candidate, principal)
            tentative_has_more = index < len(candidates) - 1
            tentative = SpatialAssetCatalogPageV1(
                site_id=site_id,
                work_area_id=work_area_id,
                assets=tuple([*page_items, item]),
                next_cursor=(
                    _encode_cursor(
                        site_id=site_id,
                        work_area_id=work_area_id,
                        after=item.asset_ref,
                    )
                    if tentative_has_more
                    else None
                ),
                has_more=tentative_has_more,
            )
            if len(canonical_json_bytes(_page_wire(tentative))) > _MAX_PAGE_BYTES:
                if not page_items:
                    raise HTTPException(
                        status_code=503, detail="SPATIAL_ASSET_EXCEEDS_RESPONSE_BUDGET"
                    )
                has_more = True
                break
            page_items.append(item)
        has_more = has_more or len(page_items) < len(candidates)
        next_cursor = (
            _encode_cursor(
                site_id=site_id, work_area_id=work_area_id, after=page_items[-1].asset_ref
            )
            if has_more and page_items
            else None
        )
        page = SpatialAssetCatalogPageV1(
            site_id=site_id,
            work_area_id=work_area_id,
            assets=tuple(page_items),
            next_cursor=next_cursor,
            has_more=has_more,
        )
        if len(canonical_json_bytes(_page_wire(page))) > _MAX_PAGE_BYTES:
            raise HTTPException(
                status_code=503, detail="SPATIAL_ASSET_PAGE_EXCEEDS_RESPONSE_BUDGET"
            )
        return page

    @router.get(
        "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-assets/{asset_ref}",
        response_model=SpatialAssetCatalogDetailV1,
    )
    def get_asset(
        site_id: str,
        work_area_id: str,
        asset_ref: str,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> SpatialAssetCatalogDetailV1:
        if _ASSET_REF_RE.fullmatch(asset_ref) is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        candidate = next(
            (
                candidate
                for candidate in catalog.items(site_id, work_area_id, principal)
                if candidate.asset_ref == asset_ref
            ),
            None,
        )
        if candidate is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        item = catalog.with_inspection(candidate, principal)
        detail = SpatialAssetCatalogDetailV1.model_validate(item.model_dump())
        if (
            len(canonical_json_bytes(detail.model_dump(by_alias=True, mode="json")))
            > _MAX_PAGE_BYTES
        ):
            raise HTTPException(status_code=503, detail="SPATIAL_ASSET_EXCEEDS_RESPONSE_BUDGET")
        return detail

    return router
