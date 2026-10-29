"""Combined V3 chain through the real new stores (synthetic bytes only).

Ingress (real byte store + real narrow mask inspection + real ingress
store) -> admission (ingress-backed evidence, no V2 numeric required) ->
real dispatch over actual generated GeoTIFF bytes -> fenced accepted
report -> resolve_completed_source.  All fixtures are synthetic and
labelled as such; signing/host/data gates remain extrinsic and unverified.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import rasterio
from ksi_core.domains.external.ingress.external_mask_input_bytes import (
    ExternalMaskInputByteStore,
)
from ksi_core.domains.external.ingress.external_mask_input_store import (
    BaselineDsmAnchor,
    ExternalMaskInputStore,
)
from ksi_core.domains.external.quantity.external_masked_calculation_store import (
    ExternalMaskedCalculationStore,
    MaskedAdmissionEvidencePort,
    MaskedAdmissionWitnessV3,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal, PrincipalKind, Role
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_mask_input import (
    MaskChildDeclarationV1,
    MaskInspectionProfileV1,
)
from ksi_event_contracts.external_masked_execution import (
    MaskedAdmissionDispositionV3,
    MaskedAdmissionV3,
)
from ksi_event_contracts.external_masked_volume import (
    ExclusionMaskBindingV1,
    MaskedCalculationIdentityV3,
    MaskedRelativeVolumeProfileV3,
)
from ksi_event_contracts.external_relative_volume_analysis import (
    AnalysisPolicyV2,
    CalculationIdentityV2,
)
from ksi_processing_controller.external_mask_input_inspection import (
    inspect_mask_bytes_v1,
)
from ksi_processing_controller.external_masked_execution_dispatch import (
    MaskedDispatchInputsV3,
    dispatch_masked_execution_v3,
)
from ksi_processing_controller.external_measurement_algorithms import (
    MeasurementWatchdogV2,
)
from pyproj import CRS
from rasterio.transform import from_origin

NOW = datetime(2026, 10, 26, tzinfo=UTC)
ORIGIN_X = 200000.0
ORIGIN_Y = 550000.0
NATIVE_TRANSFORM = (1.0, 0.0, ORIGIN_X, 0.0, -1.0, ORIGIN_Y)
COMPOUND_CRS = CRS.from_user_input("EPSG:5186+5773")


def _digest(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical_digest(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _subject(label: str) -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="order-" + label,
        submission_id="submission-" + label,
        revision=1,
        submission_digest=_digest("submission-" + label),
        manifest_digest=_digest("manifest-" + label),
    )


def _polygon() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [ORIGIN_X, ORIGIN_Y],
                [ORIGIN_X, ORIGIN_Y - 4.0],
                [ORIGIN_X + 4.0, ORIGIN_Y - 4.0],
                [ORIGIN_X + 4.0, ORIGIN_Y],
                [ORIGIN_X, ORIGIN_Y],
            ]
        ],
    }


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=4000000,
        max_streamed_bytes=4000000,
        max_tiff_directories=8,
        max_tiff_entries=128,
        max_pixels=1000000,
        max_bands=4,
        max_blocks=512,
        max_decompressed_bytes=20000000,
        max_sample_bytes=4000000,
        max_geometry_vertices=64,
        max_cpu_seconds=30.0,
        max_memory_bytes=50000000,
        max_workspace_bytes=50000000,
        max_output_bytes=1000000,
        max_tenant_concurrency=2,
        max_queue_depth=4,
        max_deadline_seconds=3600.0,
        lease_duration_seconds=600.0,
        max_retry_attempts=2,
    ).sealed()


def _operator() -> Principal:
    return Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-a")


def _worker() -> Principal:
    return Principal("analysis-worker-1", PrincipalKind.ANALYSIS_WORKER, None, None, "org-a")


def _write_geotiffs(tmp_path: Path) -> tuple[Path, Path, Path]:
    transform = from_origin(ORIGIN_X, ORIGIN_Y, 1.0, 1.0)
    baseline_values = np.full((4, 4), 100.0)
    diff = np.zeros((4, 4), dtype=np.float64)
    diff[0, 1] = 1.0
    diff[1, 0] = 1.0
    diff[1, 1] = 1.0
    diff[2, 2] = -2.0
    current_values = baseline_values + diff
    mask = np.zeros((4, 4), dtype=np.uint8)
    mask[0, 1] = 1
    baseline_path = tmp_path / "baseline.tif"
    current_path = tmp_path / "current.tif"
    mask_path = tmp_path / "mask.tif"
    with rasterio.open(
        baseline_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float64",
        crs=COMPOUND_CRS,
        transform=transform,
    ) as dataset:
        dataset.write(baseline_values, 1)
    with rasterio.open(
        current_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float64",
        crs=COMPOUND_CRS,
        transform=transform,
    ) as dataset:
        dataset.write(current_values, 1)
    with rasterio.open(
        mask_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint8",
        crs="EPSG:5186",
        transform=transform,
    ) as dataset:
        dataset.write(mask, 1)
    return baseline_path, current_path, mask_path


class _Authority:
    label = "synthetic-not-field"

    _baseline_bytes: bytes | None = None

    def __init__(self) -> None:
        self.live = True

    def is_subject_current(
        self,
        *,
        subject: SealedExternalSubjectV1,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        now: datetime,
    ) -> bool:
        if not self.live:
            return False
        return subject in (_subject("parent"), _subject("baseline"))

    def fetch_baseline_anchor(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        baseline_subject: SealedExternalSubjectV1,
        dsm_artifact_id: str,
    ) -> BaselineDsmAnchor | None:
        if not self.live or dsm_artifact_id != "dsm-baseline":
            return None
        if baseline_subject != _subject("baseline"):
            return None
        baseline_bytes = self._baseline_bytes
        if baseline_bytes is None:
            return None
        return BaselineDsmAnchor(
            baseline_subject_digest=_subject("baseline").canonical_digest(),
            dsm_artifact_id="dsm-baseline",
            rows=4,
            columns=4,
            observed_sha256=_digest(baseline_bytes),
            observed_size_bytes=len(baseline_bytes),
            transform=NATIVE_TRANSFORM,
            transform_digest=_canonical_digest({"transform": list(NATIVE_TRANSFORM)}),
            crs_identifier="EPSG:5186",
            crs_digest=_digest(
                CRS.from_epsg(5186).to_wkt(version="WKT2_2019", pretty=False, output_axis_rule=True)
            ),
        )


class _Activation:
    label = "synthetic-not-field"

    def __init__(self, profile: MaskInspectionProfileV1) -> None:
        self._digest = profile.canonical_digest()
        self.live = True

    def is_profile_active(
        self,
        *,
        profile_digest: str,
        resource_envelope_digest: str,
        contained_runtime_digest: str,
        inspector_build_digest: str,
        now: datetime,
    ) -> bool:
        return self.live and profile_digest == self._digest


class _IngressBackedEvidence(MaskedAdmissionEvidencePort):
    """Test evidence: fresh witness from the real ingress store (synthetic V2 source)."""

    label = "synthetic-not-field"

    def __init__(
        self,
        ingress: ExternalMaskInputStore,
        identity: MaskedCalculationIdentityV3,
        envelope: ResourceEnvelopeV1,
        reader: Principal,
    ) -> None:
        self._ingress = ingress
        self._identity = identity
        self._envelope = envelope
        self._reader = reader
        self.live = True

    def _admission(self, now: datetime) -> MaskedAdmissionV3:
        identity = self._identity
        return MaskedAdmissionV3(
            admission_id="admission-1",
            organization_id="org-a",
            site_id="site-a",
            work_area_id="work-area-a",
            masked_calculation_identity_digest=identity.canonical_digest(),
            source_calculation_identity_digest=identity.source_calculation_identity_digest,
            mask_binding_digest=identity.mask_binding_digest,
            masked_profile_digest=identity.masked_profile_digest,
            area_definition_digest=_digest("area"),
            policy_digest=_digest("policy"),
            runtime_digest=_digest("runtime"),
            resource_envelope_digest=self._envelope.canonical_digest(),
            activation_digest=_digest("activation"),
            scope_digest=_digest("scope"),
            ai_egress_digest=_digest("egress"),
            disposition=MaskedAdmissionDispositionV3.ADMIT_EVALUATED,
            reason_codes=("MASK_ADMITTED",),
            assessed_at=now - timedelta(seconds=1),
        ).sealed()

    def prepare_witness(
        self,
        *,
        masked_calculation_identity_digest: str,
        organization_id: str,
        now: datetime,
        expected_admission: MaskedAdmissionV3 | None = None,
    ) -> MaskedAdmissionWitnessV3 | None:
        if not self.live or organization_id != "org-a":
            return None
        if masked_calculation_identity_digest != self._identity.canonical_digest():
            return None
        record = self._ingress.get(
            organization_id="org-a",
            mask_child_id="mask-child-1",
            principal=self._reader,
            now=now,
        )
        if record is None or record.manifest is None:
            return None
        admission = self._admission(now)
        if expected_admission is not None and expected_admission != admission:
            if (
                expected_admission.masked_calculation_identity_digest
                != admission.masked_calculation_identity_digest
            ):
                return None
            admission = expected_admission
        return MaskedAdmissionWitnessV3(
            admission=admission,
            source_identity=self._identity,
            mask_manifest=record.manifest,
        )

    def witness_is_current(
        self, *, witness: MaskedAdmissionWitnessV3, now: datetime
    ) -> MaskedAdmissionWitnessV3 | None:
        if witness is None or not self.live:
            return None
        if witness.source_identity.canonical_digest() != self._identity.canonical_digest():
            return None
        record = self._ingress.get(
            organization_id="org-a",
            mask_child_id="mask-child-1",
            principal=self._reader,
            now=now,
        )
        if record is None or record.manifest is None:
            return None
        if record.manifest.canonical_digest() != witness.mask_manifest.canonical_digest():
            return None
        if now - witness.admission.assessed_at > timedelta(seconds=3600):
            return None
        return witness


def _v2_source(baseline_path: Path, current_path: Path) -> CalculationIdentityV2:
    from ksi_event_contracts.external_artifact_validation import ObservedVerticalReferenceV1

    vertical = ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")
    horizontal_wkt = CRS.from_epsg(5186).to_wkt(
        version="WKT2_2019", pretty=False, output_axis_rule=True
    )
    horizontal_digest = _digest(horizontal_wkt)
    return CalculationIdentityV2(
        calculation_id="calculation-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        work_area_polygon=_polygon(),
        work_area_crs="EPSG:5186",
        work_area_definition_digest=_canonical_digest(
            {"workAreaId": "work-area-a", "crs": "EPSG:5186", "polygon": _polygon()}
        ),
        baseline_subject=_subject("baseline"),
        current_subject=_subject("current"),
        baseline_capture_started_at=datetime(2026, 9, 19, tzinfo=UTC),
        baseline_capture_ended_at=datetime(2026, 9, 19, 1, tzinfo=UTC),
        current_capture_started_at=datetime(2026, 9, 20, tzinfo=UTC),
        current_capture_ended_at=datetime(2026, 9, 20, 1, tzinfo=UTC),
        baseline_dsm_artifact_id="dsm-baseline",
        current_dsm_artifact_id="dsm-current",
        baseline_input_digest=_digest("baseline-input"),
        current_input_digest=_digest("current-input"),
        baseline_dsm_observed_sha256=_digest(baseline_path.read_bytes()),
        current_dsm_observed_sha256=_digest(current_path.read_bytes()),
        baseline_dsm_observed_size_bytes=baseline_path.stat().st_size,
        current_dsm_observed_size_bytes=current_path.stat().st_size,
        baseline_observed_crs_identifier="EPSG:5186",
        current_observed_crs_identifier="EPSG:5186",
        baseline_observed_crs_digest=horizontal_digest,
        current_observed_crs_digest=horizontal_digest,
        baseline_projected_unit="metre",
        current_projected_unit="metre",
        baseline_vertical_reference=vertical,
        current_vertical_reference=vertical,
        baseline_vertical_reference_digest=vertical.canonical_digest(),
        current_vertical_reference_digest=vertical.canonical_digest(),
        baseline_vertical_unit="metre",
        current_vertical_unit="metre",
        baseline_vertical_unit_provenance="OBSERVED_VERTICAL_CRS_AXIS",
        current_vertical_unit_provenance="OBSERVED_VERTICAL_CRS_AXIS",
        baseline_inspection_report_digest=_digest("baseline-report"),
        current_inspection_report_digest=_digest("current-report"),
        baseline_inspection_policy_digest=_digest("baseline-policy"),
        current_inspection_policy_digest=_digest("current-policy"),
        baseline_inspector_build_digest=_digest("baseline-inspector"),
        current_inspector_build_digest=_digest("current-inspector"),
        baseline_transform_digest=_canonical_digest({"transform": list(NATIVE_TRANSFORM)}),
        current_transform_digest=_canonical_digest({"transform": list(NATIVE_TRANSFORM)}),
        baseline_transform=NATIVE_TRANSFORM,
        current_transform=NATIVE_TRANSFORM,
        horizontal_crs_digest=horizontal_digest,
        vertical_reference_digest=vertical.canonical_digest(),
        policy=AnalysisPolicyV2(
            policy_id="relative-volume-v2",
            version=2,
            profile_id="KSI-GIS-RELATIVE-VOLUME-V2",
            profile_digest=_digest("profile"),
            algorithm_digest=_digest("algorithm"),
            config_digest=_digest("config"),
            baseline_grid_rule="BASELINE_NATIVE_NORTH_UP_AFFINE_V1",
            current_elevation_resampling="BILINEAR",
            current_mask_resampling="NEAREST",
            work_area_rasterization="CELL_CENTER",
            minimum_common_valid_fraction=1.0,
            threshold_m=0.0,
            cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
            delta_rule="CURRENT_MINUS_BASELINE",
            uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
        ).sealed(),
        worker_executable_digest=_digest("worker"),
        worker_build_digest=_digest("build"),
        runtime_image_version="2.0.0",
        runtime_image_oci_digest=_digest("oci"),
        dependency_lock_digest=_digest("lock"),
    ).sealed()


def test_combined_ingress_admission_dispatch_report(tmp_path: Path) -> None:
    """Full chain: grant, bytes, narrow inspection, seal, issue, lease, dispatch, report."""
    baseline_path, current_path, mask_path = _write_geotiffs(tmp_path)
    envelope = _envelope()
    profile = MaskInspectionProfileV1(
        profile_id="KSI-MASK-INSPECTION-V1",
        version=1,
        contained_protocol="CONTAINED_MASK_INSPECTION_V1",
        runtime_image_version="9.9.9",
        runtime_image_oci_digest=_digest("oci"),
        worker_executable_digest=_digest("exe"),
        worker_build_digest=_digest("build"),
        dependency_lock_digest=_digest("lock"),
        mask_grammar_digest=_digest("mask-grammar-v1"),
        mask_convention="UINT8_SINGLE_BAND_BINARY_0_KEEP_1_EXCLUDE_V1",
        mask_nodata_rule="NO_NODATA",
        resource_envelope_digest=envelope.canonical_digest(),
    ).sealed()
    authority = _Authority()
    authority._baseline_bytes = baseline_path.read_bytes()
    activation = _Activation(profile)
    byte_store = ExternalMaskInputByteStore(
        DurableJournal(tmp_path / "mask-bytes.journal"),
        tmp_path / "mask-bytes",
        resource_envelope=envelope,
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    ingress = ExternalMaskInputStore(
        DurableJournal(tmp_path / "mask-child.journal"),
        resource_envelope=envelope,
        reconstruction_authority=authority,
        profile_activation=activation,
        sealed_bytes=byte_store,
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    mask_bytes = mask_path.read_bytes()
    declaration = MaskChildDeclarationV1(
        declaration_id="decl-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        child_kind="MASK_CHILD",
        mask_child_id="mask-child-1",
        mask_artifact_id="mask-artifact-1",
        parent_subject=_subject("parent"),
        target_baseline_subject=_subject("baseline"),
        target_baseline_dsm_artifact_id="dsm-baseline",
        declared_sha256=_digest(mask_bytes),
        declared_size_bytes=len(mask_bytes),
    ).sealed()
    ingress.declare(principal=_operator(), declaration=declaration, now=NOW)
    grant = byte_store.issue_grant(
        principal=_operator(),
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        mask_child_id="mask-child-1",
        mask_artifact_id="mask-artifact-1",
        subject_digest=_subject("parent").canonical_digest(),
        declared_sha256=_digest(mask_bytes),
        declared_size_bytes=len(mask_bytes),
        now=NOW,
    )
    assert grant.object_key.startswith("mask/org-a/site-a/")
    byte_store.complete_upload(
        grant_id=grant.grant_id, data=mask_bytes, principal=_operator(), now=NOW
    )
    # Narrow contained mask inspection against the exact baseline anchor grid.
    anchor = authority.fetch_baseline_anchor(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        baseline_subject=_subject("baseline"),
        dsm_artifact_id="dsm-baseline",
    )
    assert anchor is not None
    narrow_report = inspect_mask_bytes_v1(
        path=mask_path,
        envelope=envelope,
        watchdog=MeasurementWatchdogV2.from_envelope(envelope),
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        mask_child_id="mask-child-1",
        mask_artifact_id="mask-artifact-1",
        subject=_subject("parent"),
        inspection_profile=profile,
        contained_runtime_digest=_digest("contained-runtime"),
        inspector_build_digest=_digest("inspector-build"),
        expected_crs_identifier=anchor.crs_identifier,
        expected_crs_digest=anchor.crs_digest,
        expected_transform=anchor.transform,
        expected_transform_digest=anchor.transform_digest,
        report_id="narrow-report-1",
        reported_at=NOW,
    )
    manifest = ingress.seal_observed(
        principal=_operator(),
        organization_id="org-a",
        mask_child_id="mask-child-1",
        report=narrow_report,
        inspection_profile=profile,
        now=NOW,
    )
    assert manifest.observed_sha256 == _digest(mask_bytes)
    assert manifest.observed_inspection_report_digest == narrow_report.canonical_digest()
    # Bridge the Core manifest into the V3 binding (test assembly; parent owns
    # the real admission assembly).
    source = _v2_source(baseline_path, current_path)
    binding = ExclusionMaskBindingV1(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        subject=manifest.subject,
        mask_artifact_id=manifest.mask_artifact_id,
        observed_sha256=manifest.observed_sha256,
        observed_size_bytes=manifest.observed_size_bytes,
        observed_inspection_report_digest=manifest.observed_inspection_report_digest,
        rows=manifest.rows,
        columns=manifest.columns,
        transform=manifest.transform,
        transform_digest=manifest.transform_digest,
        observed_crs_identifier=manifest.observed_crs_identifier,
        observed_crs_digest=manifest.observed_crs_digest,
        dtype="UINT8",
        band_count=1,
        retain_value=0,
        exclude_value=1,
        nodata_representation="NONE",
        bounds=manifest.bounds,
    ).sealed()
    masked_profile = MaskedRelativeVolumeProfileV3(
        policy_id="masked-relative-volume-v3",
        version=3,
        profile_id="KSI-GIS-MASKED-RELATIVE-VOLUME-V3",
        profile_digest=_digest("masked-profile"),
        algorithm_digest=_digest("masked-algorithm"),
        config_digest=_digest("masked-config"),
        baseline_grid_rule="EXACT_BASELINE_GRID",
        current_elevation_resampling="BILINEAR",
        current_mask_resampling="NEAREST",
        work_area_rasterization="CELL_CENTER",
        exclusion_precedence="WORKAREA_HOLES_THEN_MASK",
        mask_convention="UINT8_SINGLE_BAND_BINARY_0_KEEP_1_EXCLUDE_V1",
        mask_nodata_rule="NO_NODATA",
        minimum_common_valid_fraction=1.0,
        threshold_m=0.0,
        cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
        delta_rule="CURRENT_MINUS_BASELINE",
        uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
    ).sealed()
    identity = MaskedCalculationIdentityV3(
        masked_calculation_id="masked-calculation-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        source_calculation_identity=source,
        source_calculation_identity_digest=source.canonical_digest(),
        mask_binding=binding,
        mask_binding_digest=binding.canonical_digest(),
        profile=masked_profile,
        masked_profile_digest=masked_profile.canonical_digest(),
        grid_rows=manifest.rows,
        grid_columns=manifest.columns,
        horizontal_crs_digest=binding.observed_crs_digest,
    ).sealed()
    evidence = _IngressBackedEvidence(ingress, identity, envelope, _operator())
    calc = ExternalMaskedCalculationStore(
        DurableJournal(tmp_path / "masked-calc.journal"),
        evidence=evidence,
        resource_envelope=envelope,
        designated_worker=_worker(),
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    calc.bind_constructed_identity(principal=_operator(), identity=identity, now=NOW)
    issued = calc.issue(
        principal=_operator(),
        request_id="request-1",
        masked_calculation_identity_digest=identity.canonical_digest(),
        idempotency_key="idem-1",
        now=NOW,
    )
    assert issued.admission.masked_calculation_identity_digest == identity.canonical_digest()
    attempt = calc.acquire_lease(
        request_id="request-1",
        worker_principal=_worker(),
        worker_instance_id="masked-worker-instance-1",
        lease_acquisition_id="lease-1",
        now=NOW,
    )
    assert attempt is not None
    worker_input = calc.input_for_worker(
        request_id="request-1", worker_principal=_worker(), attempt=attempt, now=NOW
    )
    assert worker_input is not None
    assert [item.role for item in worker_input.inputs] == [
        "BASELINE_DSM",
        "CURRENT_DSM",
        "EXCLUSION_MASK",
    ]
    staged_mask = byte_store.sealed_object_path(
        organization_id="org-a",
        site_id="site-a",
        mask_child_id="mask-child-1",
        mask_artifact_id="mask-artifact-1",
    )
    outcome = dispatch_masked_execution_v3(
        worker_input=worker_input,
        files=MaskedDispatchInputsV3(
            baseline_path=baseline_path,
            current_path=current_path,
            mask_path=staged_mask,
        ),
        envelope=envelope,
        watchdog=MeasurementWatchdogV2.from_envelope(envelope),
        lease_expires_at=attempt.lease_expires_at,
        report_id="report-1",
        computed_at=NOW + timedelta(seconds=60),
        reported_at=NOW + timedelta(seconds=120),
    )
    assert outcome.report is not None and outcome.failure is None
    numeric = outcome.report.numeric_result
    assert (numeric.metrics.fill_m3, numeric.metrics.cut_m3, numeric.metrics.net_m3) == (
        2.0,
        2.0,
        0.0,
    )
    assert numeric.impact.unmasked_impact_known is True
    stored = calc.record_report(
        request_id="request-1",
        worker_principal=_worker(),
        report=outcome.report,
        attempt=attempt,
        now=NOW + timedelta(seconds=180),
    )
    assert stored is not None and stored.report is not None
    current = calc.get_current(
        request_id="request-1", principal=_operator(), now=NOW + timedelta(seconds=180)
    )
    assert current is not None and current.disposition.value == "AVAILABLE"
    assert current.report is not None
    resolved = calc.resolve_completed_source(
        organization_id="org-a",
        masked_calculation_identity_digest=identity.canonical_digest(),
        numeric_result_identity_digest=numeric.canonical_digest(),
        coverage_witness_digest=numeric.coverage.canonical_digest(),
        now=NOW + timedelta(seconds=180),
    )
    assert resolved is not None
    assert resolved[0].report is not None
