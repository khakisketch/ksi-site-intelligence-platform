"""Exact external source admission; catalog metadata never establishes byte/inspection authority."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import HTTPException
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ArtifactOutcome,
    ExternalArtifactInspectionReportV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.spatial_data import SpatialDataSourceV1
from ksi_event_contracts.spatial_data_authority import SpatialDataPolicyV1
from ksi_event_contracts.work_area import WorkArea
from pydantic import ValidationError
from pyproj import CRS
from pyproj.exceptions import CRSError

from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.ingress.external_artifact_inspections import (
    ExternalArtifactInspectionSnapshotBudgetExceeded,
    ExternalArtifactInspectionStore,
)
from ksi_core.domains.external.ingress.external_reconstruction import (
    ExternalReconstructionRevision,
    ExternalReconstructionStore,
)
from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog
from ksi_core.domains.sites.observation_work_orders import ObservationWorkOrderStore
from ksi_core.domains.sites.sites import SiteStore
from ksi_core.domains.sites.work_areas import WorkAreaStore
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, principal_permissions


def work_area_boundary_digest(area: WorkArea) -> str:
    """Immutable ID/boundary revision; mutable display name/status do not change history."""
    validated = WorkArea.model_validate(area.model_dump())
    wire = validated.model_dump(by_alias=True, mode="json")
    body = {
        key: wire[key]
        for key in ("workAreaId", "siteId", "crs", "polygon", "createdAt", "supersedes")
    }
    return "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()


class SpatialDataSourceResolver:
    def __init__(
        self,
        *,
        reconstruction: ExternalReconstructionStore,
        inspections: ExternalArtifactInspectionStore,
        sites: SiteStore,
        work_areas: WorkAreaStore,
        work_orders: ObservationWorkOrderStore,
        policy: SpatialDataPolicyV1,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        clock: Callable[[], datetime],
    ) -> None:
        participants = (
            (reconstruction, ExternalReconstructionStore),
            (inspections, ExternalArtifactInspectionStore),
            (sites, SiteStore),
            (work_areas, WorkAreaStore),
            (work_orders, ObservationWorkOrderStore),
        )
        if any(not isinstance(participant, expected) for participant, expected in participants):
            raise ValueError("source resolution requires genuine Core participants")
        if (
            reconstruction.coordinator is not coordinator
            or inspections.coordinator is not coordinator
            or sites.coordinator is not coordinator
            or work_areas.coordinator is not coordinator
            or work_orders.operations_coordinator is not coordinator
        ):
            raise ValueError("source authority participants must share one coordinator")
        validated = SpatialDataPolicyV1.model_validate(policy)
        if validated.policy_digest != validated.canonical_digest():
            raise ValueError("source resolution requires a sealed explicit data policy")
        if not callable(clock):
            raise ValueError("source resolution requires a clock")
        self._reconstruction = reconstruction
        self._inspections = inspections
        self._sites = sites
        self._work_areas = work_areas
        self._work_orders = work_orders
        self._policy = validated.model_copy(deep=True)
        self._coordinator = coordinator
        self._clock = clock
        self._catalog = SpatialAssetCatalog(
            reconstruction=reconstruction,
            work_orders=work_orders,
            sites=sites,
            work_areas=work_areas,
            inspections=inspections,
        )

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def uses_exact_participants(
        self,
        *,
        reconstruction: ExternalReconstructionStore,
        inspections: ExternalArtifactInspectionStore,
        sites: SiteStore,
        work_areas: WorkAreaStore,
        work_orders: ObservationWorkOrderStore,
    ) -> bool:
        return (
            reconstruction is self._reconstruction
            and inspections is self._inspections
            and sites is self._sites
            and work_areas is self._work_areas
            and work_orders is self._work_orders
        )

    def require_history_scope(
        self, site_id: str, work_area_id: str, principal: Principal
    ) -> WorkArea:
        """Visible scoped history only; no report/grant/preparation/byte authorization."""
        for scopes, identity in (
            (principal.allowed_site_ids, site_id),
            (principal.allowed_work_area_ids, work_area_id),
        ):
            if (principal.kind is PrincipalKind.SPATIAL_DATA_CLIENT and scopes is None) or (
                scopes is not None and (type(scopes) is not frozenset or identity not in scopes)
            ):
                raise SpatialDataDomainError("NOT_FOUND", 404)
        site = self._sites.get_scoped(site_id, principal.organization_id)
        area = self._work_areas.get(work_area_id)
        if site is None or area is None or area.site_id != site_id:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        if (
            principal.kind not in (PrincipalKind.OPERATOR, PrincipalKind.SPATIAL_DATA_CLIENT)
            or principal.device_id is not None
            or Permission.SPATIAL_DATA_READ not in principal_permissions(principal)
        ):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        if self._sites.sealed_reason is not None or self._work_areas.sealed_reason is not None:
            raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503)
        return area.model_copy(deep=True)

    def _scope(self, site_id: str, work_area_id: str, principal: Principal) -> WorkArea:
        area = self.require_history_scope(site_id, work_area_id, principal)
        if any(
            participant.sealed_reason is not None
            for participant in (
                self._sites,
                self._work_areas,
                self._work_orders,
                self._reconstruction,
                self._inspections,
            )
        ):
            raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503)
        return area.model_copy(deep=True)

    @staticmethod
    def _subject(record: ExternalReconstructionRevision) -> SealedExternalSubjectV1:
        if record.manifest is None:
            raise SpatialDataDomainError("SOURCE_UNSEALED", 403)
        if record.submission.submission_digest is None or record.manifest.manifest_digest is None:
            raise SpatialDataDomainError("SOURCE_UNAVAILABLE", 503)
        return SealedExternalSubjectV1(
            organization_id=record.submission.organization_id,
            site_id=record.submission.site_id,
            work_order_id=record.work_order_id,
            submission_id=record.submission.submission_id,
            revision=record.submission.revision,
            submission_digest=record.submission.submission_digest,
            manifest_digest=record.manifest.manifest_digest,
        )

    def _build(
        self,
        record: ExternalReconstructionRevision,
        area: WorkArea,
        artifact_id: str,
        report: ExternalArtifactInspectionReportV1,
    ) -> SpatialDataSourceV1:
        subject = self._subject(record)
        if (
            report.subject != subject
            or report.subject_digest != subject.canonical_digest()
            or report.sealed_manifest_digest != subject.manifest_digest
        ):
            raise SpatialDataDomainError("SOURCE_MEASUREMENTS_MISMATCH", 409)
        report = ExternalArtifactInspectionReportV1.model_validate(report.model_dump())
        if report.report_digest != report.canonical_digest():
            raise SpatialDataDomainError("SOURCE_MEASUREMENTS_MISMATCH", 409)
        manifest = record.manifest
        assert manifest is not None
        declared = next(
            (item for item in record.submission.artifacts if item.artifact_id == artifact_id), None
        )
        entry = next((item for item in manifest.entries if item.artifact_id == artifact_id), None)
        outcome = next(
            (
                item
                for item in report.measurement_payload.outcomes
                if item.artifact_id == artifact_id
            ),
            None,
        )
        if declared is None or entry is None:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        if declared.kind not in (ProcessingArtifactKind.DSM, ProcessingArtifactKind.ORTHO):
            raise SpatialDataDomainError("UNSUPPORTED_ARTIFACT_KIND", 422)
        if (
            outcome is None
            or outcome.outcome is not ArtifactOutcome.MEASURED
            or outcome.measurements is None
        ):
            raise SpatialDataDomainError("SOURCE_NOT_MEASURED", 403)
        if (
            outcome.observed_sha256 != "sha256:" + entry.observed_sha256
            or entry.kind != declared.kind
        ):
            raise SpatialDataDomainError("SOURCE_MEASUREMENTS_MISMATCH", 409)
        measured = outcome.measurements
        if measured.observed_crs_wkt is None or measured.observed_crs_digest != (
            "sha256:" + hashlib.sha256(measured.observed_crs_wkt.encode()).hexdigest()
        ):
            raise SpatialDataDomainError("CRS_MISMATCH", 422)
        try:
            crs = CRS.from_wkt(measured.observed_crs_wkt)
            if (
                len(crs.axis_info) != 2
                or crs.is_compound
                or crs.is_geocentric
                or not (crs.is_projected or crs.is_geographic)
                or not crs.equals(CRS.from_user_input(measured.observed_crs_identifier))
                or len({axis.unit_name for axis in crs.axis_info}) != 1
            ):
                raise SpatialDataDomainError("CRS_MISMATCH", 422)
            units = crs.axis_info[0].unit_name
        except CRSError as exc:
            raise SpatialDataDomainError("CRS_MISMATCH", 422) from exc
        if entry.observed_size_bytes > self._policy.resource_envelope.max_input_bytes:
            raise SpatialDataDomainError("INPUT_BYTE_LIMIT_EXCEEDED", 422)
        if measured.width * measured.height > self._policy.resource_envelope.max_pixels:
            raise SpatialDataDomainError("INPUT_PIXEL_LIMIT_EXCEEDED", 422)
        if measured.band_count > self._policy.resource_envelope.max_bands:
            raise SpatialDataDomainError("INPUT_BAND_LIMIT_EXCEEDED", 422)
        try:
            return SpatialDataSourceV1(
                asset_ref=self._catalog._asset_ref(
                    self._catalog._submission_ref(record), record.submission.revision, artifact_id
                ),
                site_id=record.submission.site_id,
                work_area_id=area.work_area_id,
                work_order_id=record.work_order_id,
                epoch_id=record.observation_epoch_id,
                submission_ref=self._catalog._submission_ref(record),
                revision=record.submission.revision,
                artifact_id=artifact_id,
                artifact_kind="dsm" if declared.kind is ProcessingArtifactKind.DSM else "ortho",
                sealed_subject=subject,
                observed_sha256=outcome.observed_sha256,
                observed_size_bytes=entry.observed_size_bytes,
                inspection=outcome,
                inspection_report_digest=report.report_digest,
                inspector_build_digest=report.inspector_build_digest,
                work_area_boundary_digest=work_area_boundary_digest(area),
                observed_crs_units=units,
                capture_started_at=record.submission.input_declaration.capture_started_at,
                capture_ended_at=record.submission.input_declaration.capture_ended_at,
                producer_processed_at=record.submission.producer_declaration.completed_at,
                declaration_recorded_at=record.registered_at,
            ).sealed()
        except ValidationError as exc:
            raise SpatialDataDomainError("UNSUPPORTED_SOURCE_PROFILE", 422) from exc

    def resolve(
        self, *, site_id: str, work_area_id: str, asset_ref: str, principal: Principal
    ) -> SpatialDataSourceV1:
        """Preflight (may resolve policy authority); use require_current during check-and-commit."""
        with self._coordinator.guarded_read():
            area = self._scope(site_id, work_area_id, principal)
            try:
                matches = [
                    item
                    for item in self._catalog.items(site_id, work_area_id, principal)
                    if item.asset_ref == asset_ref
                ]
            except HTTPException as exc:
                raise SpatialDataDomainError(
                    "NOT_FOUND" if exc.status_code == 404 else "RESOURCE_LIMIT_EXCEEDED",
                    exc.status_code,
                ) from exc
            if len(matches) != 1:
                raise SpatialDataDomainError("NOT_FOUND", 404)
            item = matches[0]
            submission_id = self._reconstruction.resolve_submission_ref(
                item.work_order_id,
                item.submission_ref,
                organization_id=principal.organization_id,
                site_id=site_id,
            )
            record = (
                self._reconstruction.get(
                    item.work_order_id,
                    submission_id,
                    item.revision,
                    organization_id=principal.organization_id,
                    site_id=site_id,
                )
                if submission_id
                else None
            )
            if record is None:
                raise SpatialDataDomainError("NOT_FOUND", 404)
            subject = self._subject(record)
        try:
            snapshot = self._inspections.public_snapshot_bounded(
                subject,
                max_records=self._policy.max_pending_records,
                max_retained_policies=self._policy.max_pending_records,
            )
        except ExternalArtifactInspectionSnapshotBudgetExceeded as exc:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503) from exc
        except Exception as exc:
            raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503) from exc
        if snapshot.report is None:
            raise SpatialDataDomainError("SOURCE_NOT_MEASURED", 403)
        source = self._build(record, area, item.artifact_id, snapshot.report)
        if (
            len(canonical_json_bytes(source.model_dump(by_alias=True, mode="json")))
            > self._policy.max_snapshot_bytes
        ):
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        return self.require_current(source=source, principal=principal, now=self._clock())

    def require_current(
        self, *, source: SpatialDataSourceV1, principal: Principal, now: datetime
    ) -> SpatialDataSourceV1:
        """Local authentic recheck only; caller holds the same coordinator through append/send."""
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("source currentness time must be UTC-aware")
        try:
            source = SpatialDataSourceV1.model_validate(source)
            if source.source_digest != source.canonical_digest():
                raise ValueError("source must be sealed")
        except (ValidationError, ValueError) as exc:
            raise SpatialDataDomainError("SOURCE_UNAVAILABLE", 503) from exc
        with self._coordinator.guarded_read():
            area = self._scope(source.site_id, source.work_area_id, principal)
            if source.sealed_subject.organization_id != principal.organization_id:
                raise SpatialDataDomainError("NOT_FOUND", 404)
            if (
                len(canonical_json_bytes(source.model_dump(by_alias=True, mode="json")))
                > self._policy.max_snapshot_bytes
            ):
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
            order = self._work_orders.get(
                source.work_order_id, organization_id=principal.organization_id
            )
            if (
                order is None
                or order.site_id != source.site_id
                or order.work_area_ids != [source.work_area_id]
            ):
                raise SpatialDataDomainError("NOT_FOUND", 404)
            record = self._reconstruction.resolve_sealed_subject(source.sealed_subject)
            if record is None:
                raise SpatialDataDomainError("SOURCE_UNAVAILABLE", 503)
            try:
                expected = self._inspections.retained_report_bounded(
                    source.sealed_subject,
                    report_digest=source.inspection_report_digest,
                    max_records=self._policy.max_pending_records,
                )
                report = (
                    self._inspections.data_report_for_locally_current_use(
                        source.sealed_subject, expected, now=now
                    )
                    if expected
                    else None
                )
            except ExternalArtifactInspectionSnapshotBudgetExceeded as exc:
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503) from exc
            except Exception as exc:
                raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503) from exc
            if report is None:
                raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503)
            if self._build(record, area, source.artifact_id, report) != source:
                raise SpatialDataDomainError("SOURCE_MEASUREMENTS_MISMATCH", 409)
            return source.model_copy(deep=True)
