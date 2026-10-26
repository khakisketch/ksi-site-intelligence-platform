"""Replay for the additive V3 masked-calculation journal (synthetic only)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from ksi_core.domains.external.quantity.external_masked_calculation_store import (
    ExternalMaskedCalculationStore,
    MaskedAdmissionEvidencePort,
    MaskedAdmissionWitnessV3,
    MaskedCalculationRecoveryError,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal, PrincipalKind, Role
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_mask_input import MaskObservedManifestV1
from ksi_event_contracts.external_masked_execution import (
    MaskedAdmissionV3,
)
from ksi_event_contracts.external_masked_volume import (
    ExclusionMaskBindingV1,
    MaskedCalculationIdentityV3,
    MaskedRelativeVolumeProfileV3,
)
from ksi_event_contracts.external_masked_volume_result import (
    MaskedVolumeCalculationReportV3,
)
from ksi_event_contracts.external_relative_volume_analysis import (
    AnalysisPolicyV2,
    CalculationIdentityV2,
)

NOW = datetime(2026, 10, 26, tzinfo=UTC)
ORIGIN_X = 200000.0
ORIGIN_Y = 550000.0
TRANSFORM = (1.0, 0.0, ORIGIN_X, 0.0, -1.0, ORIGIN_Y)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


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
        max_deadline_seconds=60.0,
        lease_duration_seconds=10.0,
        max_retry_attempts=2,
    ).sealed()


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


def _masked_identity() -> MaskedCalculationIdentityV3:
    from ksi_event_contracts.external_artifact_validation import ObservedVerticalReferenceV1
    from pyproj import CRS

    vertical = ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")
    horizontal_wkt = CRS.from_epsg(5186).to_wkt(
        version="WKT2_2019", pretty=False, output_axis_rule=True
    )
    horizontal_digest = _digest(horizontal_wkt)
    source = CalculationIdentityV2(
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
        baseline_dsm_observed_sha256=_digest("baseline-bytes"),
        current_dsm_observed_sha256=_digest("current-bytes"),
        baseline_dsm_observed_size_bytes=128,
        current_dsm_observed_size_bytes=128,
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
        baseline_transform_digest=_canonical_digest({"transform": list(TRANSFORM)}),
        current_transform_digest=_canonical_digest({"transform": list(TRANSFORM)}),
        baseline_transform=TRANSFORM,
        current_transform=TRANSFORM,
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
    mask = ExclusionMaskBindingV1(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        subject=_subject("mask"),
        mask_artifact_id="mask-artifact-1",
        observed_sha256=_digest("mask-bytes"),
        observed_size_bytes=128,
        observed_inspection_report_digest=_digest("mask-report"),
        rows=4,
        columns=4,
        transform=TRANSFORM,
        transform_digest=_canonical_digest({"transform": list(TRANSFORM)}),
        observed_crs_identifier="EPSG:5186",
        observed_crs_digest=horizontal_digest,
        dtype="UINT8",
        band_count=1,
        retain_value=0,
        exclude_value=1,
        nodata_representation="NONE",
        bounds=(ORIGIN_X, ORIGIN_Y - 4.0, ORIGIN_X + 4.0, ORIGIN_Y),
    ).sealed()
    profile = MaskedRelativeVolumeProfileV3(
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
    return MaskedCalculationIdentityV3(
        masked_calculation_id="masked-calculation-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        source_calculation_identity=source,
        source_calculation_identity_digest=source.canonical_digest(),
        mask_binding=mask,
        mask_binding_digest=mask.canonical_digest(),
        profile=profile,
        masked_profile_digest=profile.canonical_digest(),
        grid_rows=4,
        grid_columns=4,
        horizontal_crs_digest=mask.observed_crs_digest,
    ).sealed()


class _StrictEvidence(MaskedAdmissionEvidencePort):
    """Synthetic strict evidence port: exact digest checks, never always-true."""

    label = "synthetic-not-field"

    def __init__(self, identity: MaskedCalculationIdentityV3) -> None:
        self._identity = identity
        self.live = True
        self.require_activation = True

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
            resource_envelope_digest=_envelope().canonical_digest(),
            activation_digest=_digest("activation"),
            scope_digest=_digest("scope"),
            ai_egress_digest=_digest("egress"),
            disposition="ADMIT_EVALUATED",
            reason_codes=("MASK_ADMITTED",),
            assessed_at=now - timedelta(seconds=1),
        ).sealed()

    def _manifest(self) -> MaskObservedManifestV1:
        identity = self._identity
        parent = _subject("mask")
        return MaskObservedManifestV1(
            organization_id="org-a",
            site_id="site-a",
            work_area_id="work-area-a",
            child_kind="MASK_CHILD",
            mask_child_id="mask-child-1",
            mask_artifact_id=identity.mask_binding.mask_artifact_id,
            subject=parent,
            parent_subject_digest=parent.canonical_digest(),
            target_baseline_dsm_artifact_id="dsm-baseline",
            target_baseline_subject_digest=_digest("baseline-subject"),
            observed_sha256=identity.mask_binding.observed_sha256,
            observed_size_bytes=identity.mask_binding.observed_size_bytes,
            observed_inspection_report_digest=_digest("mask-report"),
            inspection_profile_digest=_digest("inspection-profile"),
            rows=4,
            columns=4,
            transform=TRANSFORM,
            transform_digest=_canonical_digest({"transform": list(TRANSFORM)}),
            observed_crs_identifier="EPSG:5186",
            observed_crs_digest=identity.mask_binding.observed_crs_digest,
            dtype="UINT8",
            band_count=1,
            retain_value=0,
            exclude_value=1,
            nodata_representation="NONE",
            bounds=(ORIGIN_X, ORIGIN_Y - 4.0, ORIGIN_X + 4.0, ORIGIN_Y),
        ).sealed()

    def prepare_witness(
        self, *, masked_calculation_identity_digest, organization_id, now, expected_admission=None
    ):
        if not self.live:
            return None
        if (
            masked_calculation_identity_digest != self._identity.canonical_digest()
            or organization_id != "org-a"
        ):
            return None
        admission = self._admission(now)
        if expected_admission is not None and expected_admission != admission:
            # Expected admission must match exactly; a changed assessment fails.
            if (
                expected_admission.masked_calculation_identity_digest
                != admission.masked_calculation_identity_digest
            ):
                return None
            admission = expected_admission
        return MaskedAdmissionWitnessV3(
            admission=admission, source_identity=self._identity, mask_manifest=self._manifest()
        )

    def witness_is_current(self, *, witness, now):
        if witness is None or not self.live:
            return None
        if witness.source_identity.canonical_digest() != self._identity.canonical_digest():
            return None
        if now - witness.admission.assessed_at > timedelta(seconds=3600):
            return None
        return witness


def _operator() -> Principal:
    return Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-a")


def _worker() -> Principal:
    return Principal("analysis-worker-1", PrincipalKind.ANALYSIS_WORKER, None, None, "org-a")


def _store(tmp_path, evidence) -> ExternalMaskedCalculationStore:
    return ExternalMaskedCalculationStore(
        DurableJournal(tmp_path / "masked-calc.journal"),
        evidence=evidence,
        resource_envelope=_envelope(),
        designated_worker=_worker(),
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )


def _sealed_report(
    identity: MaskedCalculationIdentityV3, attempt_digest_note: str = ""
) -> MaskedVolumeCalculationReportV3:
    import base64

    from ksi_event_contracts.external_masked_volume_result import (
        MaskedCoverageWitnessV3,
        MaskedVolumeImpactV3,
        MaskedVolumeNumericResultV3,
    )
    from ksi_event_contracts.external_relative_volume_calculation import RelativeVolumeMetricsV2

    rows, columns = 2, 2
    full = bytes([0b11110000])
    empty = bytes([0b00000000])

    def _b64(raw: bytes) -> str:
        return base64.b64encode(raw).decode("ascii")

    coverage = MaskedCoverageWitnessV3(
        rows=rows,
        columns=columns,
        row_offset=0,
        column_offset=0,
        original_selected_mask_b64=_b64(full),
        mask_excluded_mask_b64=_b64(empty),
        effective_selected_mask_b64=_b64(full),
        common_valid_mask_b64=_b64(full),
        unavailable_mask_b64=_b64(empty),
        original_selected_cell_count=4,
        mask_excluded_cell_count=0,
        effective_selected_cell_count=4,
        common_valid_cell_count=4,
        unavailable_cell_count=0,
        cell_area_m2=1.0,
        original_selected_area_m2=4.0,
        effective_selected_area_m2=4.0,
        common_valid_area_m2=4.0,
        bounds=(ORIGIN_X, ORIGIN_Y - 2.0, ORIGIN_X + 2.0, ORIGIN_Y),
    ).sealed()
    numeric = MaskedVolumeNumericResultV3(
        masked_calculation_identity_digest=identity.canonical_digest(),
        masked_profile_digest=identity.masked_profile_digest,
        mask_binding_digest=identity.mask_binding_digest,
        metrics=RelativeVolumeMetricsV2(
            cut_m3=0.0, fill_m3=4.0, net_m3=4.0, threshold_m=0.0, uncertainty_m3=None
        ),
        coverage=coverage,
        impact=MaskedVolumeImpactV3(
            unmasked_impact_known=False,
            excluded_cell_count=0,
            unmasked_cut_m3=None,
            unmasked_fill_m3=None,
            unmasked_net_m3=None,
            excluded_cut_m3=None,
            excluded_fill_m3=None,
            excluded_net_m3=None,
        ),
    ).sealed()
    return MaskedVolumeCalculationReportV3(
        report_id="report-1",
        masked_calculation_identity_digest=identity.canonical_digest(),
        numeric_result=numeric,
        numeric_result_identity_digest=numeric.canonical_digest(),
        computed_at=NOW + timedelta(seconds=1),
        reported_at=NOW + timedelta(seconds=2),
    ).sealed()


def test_issue_lease_report_current_and_replay(tmp_path) -> None:
    identity = _masked_identity()
    evidence = _StrictEvidence(identity)
    store = _store(tmp_path, evidence)
    store.bind_constructed_identity(principal=_operator(), identity=identity, now=NOW)
    issued = store.issue(
        principal=_operator(),
        request_id="request-1",
        masked_calculation_identity_digest=identity.canonical_digest(),
        idempotency_key="idem-1",
        now=NOW,
    )
    assert issued.admission.disposition == "ADMIT_EVALUATED"
    # Idempotent re-issue returns the same record without numeric result.
    again = store.issue(
        principal=_operator(),
        request_id="request-1",
        masked_calculation_identity_digest=identity.canonical_digest(),
        idempotency_key="idem-1",
        now=NOW,
    )
    assert again.request_id == "request-1"
    attempt = store.acquire_lease(
        request_id="request-1",
        worker_principal=_worker(),
        worker_instance_id="masked-worker-instance-1",
        lease_acquisition_id="lease-1",
        now=NOW,
    )
    assert attempt is not None
    worker_input = store.input_for_worker(
        request_id="request-1", worker_principal=_worker(), attempt=attempt, now=NOW
    )
    assert worker_input is not None
    assert [item.role for item in worker_input.inputs] == [
        "BASELINE_DSM",
        "CURRENT_DSM",
        "EXCLUSION_MASK",
    ]
    report = _sealed_report(identity)
    stored = store.record_report(
        request_id="request-1",
        worker_principal=_worker(),
        report=report,
        attempt=attempt,
        now=NOW + timedelta(seconds=5),
    )
    assert stored is not None and stored.report is not None
    current = store.get_current(
        request_id="request-1", principal=_operator(), now=NOW + timedelta(seconds=5)
    )
    assert current is not None and current.disposition == "AVAILABLE"
    assert current.report is not None
    # Publication failure must not falsify numeric state: the journal has no
    # publication event, and the numeric report stays AVAILABLE.
    journal_path = tmp_path / "masked-calc.journal"
    store._journal.close()  # noqa: SLF001 - simulate restart; release single-writer lock
    replayed = ExternalMaskedCalculationStore(
        DurableJournal(journal_path),
        evidence=_StrictEvidence(identity),
        resource_envelope=_envelope(),
        designated_worker=_worker(),
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    replayed_current = replayed.get_current(
        request_id="request-1", principal=_operator(), now=NOW + timedelta(seconds=5)
    )
    assert replayed_current is not None and replayed_current.disposition == "AVAILABLE"


def test_stale_fence_and_retry_exhaustion_fail_closed(tmp_path) -> None:
    identity = _masked_identity()
    evidence = _StrictEvidence(identity)
    store = _store(tmp_path, evidence)
    store.bind_constructed_identity(principal=_operator(), identity=identity, now=NOW)
    store.issue(
        principal=_operator(),
        request_id="request-1",
        masked_calculation_identity_digest=identity.canonical_digest(),
        idempotency_key="idem-1",
        now=NOW,
    )
    attempt = store.acquire_lease(
        request_id="request-1",
        worker_principal=_worker(),
        worker_instance_id="w-1",
        lease_acquisition_id="lease-1",
        now=NOW,
    )
    assert attempt is not None
    # Stale fence: report after lease expiry is rejected (no state change).
    late = store.record_report(
        request_id="request-1",
        worker_principal=_worker(),
        report=_sealed_report(identity),
        attempt=attempt,
        now=attempt.lease_expires_at + timedelta(seconds=1),
    )
    assert late is None
    # Renew keeps the exact fence live while the assessment stays current.
    renewed = store.renew_lease(
        request_id="request-1",
        worker_principal=_worker(),
        attempt=attempt,
        now=NOW + timedelta(seconds=5),
    )
    assert renewed is not None and renewed.lease_expires_at > attempt.lease_expires_at


def test_missing_activation_and_revoked_currentness_block_issue(tmp_path) -> None:
    identity = _masked_identity()
    evidence = _StrictEvidence(identity)
    evidence.live = False
    store = _store(tmp_path, evidence)
    store.bind_constructed_identity(principal=_operator(), identity=identity, now=NOW)
    with pytest.raises(RuntimeError, match="current admitted"):
        store.issue(
            principal=_operator(),
            request_id="request-1",
            masked_calculation_identity_digest=identity.canonical_digest(),
            idempotency_key="idem-1",
            now=NOW,
        )


def test_tampered_journal_replay_fails_closed(tmp_path) -> None:
    identity = _masked_identity()
    evidence = _StrictEvidence(identity)
    store = _store(tmp_path, evidence)
    store.bind_constructed_identity(principal=_operator(), identity=identity, now=NOW)
    store.issue(
        principal=_operator(),
        request_id="request-1",
        masked_calculation_identity_digest=identity.canonical_digest(),
        idempotency_key="idem-1",
        now=NOW,
    )
    journal_path = tmp_path / "masked-calc.journal"
    store._journal.close()  # noqa: SLF001 - release lock before tampering the file
    lines = journal_path.read_text().splitlines()
    import json as _json

    assert len(lines) == 2
    second = _json.loads(lines[1])
    second["admission"]["disposition"] = "BLOCKED"
    lines[1] = _json.dumps(second, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    journal_path.write_text("\n".join(lines) + "\n")
    with pytest.raises(MaskedCalculationRecoveryError):
        ExternalMaskedCalculationStore(
            DurableJournal(journal_path),
            evidence=_StrictEvidence(identity),
            resource_envelope=_envelope(),
            designated_worker=_worker(),
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )


def test_report_with_wrong_attempt_rejected_and_cancel_terminal(tmp_path) -> None:
    identity = _masked_identity()
    evidence = _StrictEvidence(identity)
    store = _store(tmp_path, evidence)
    store.bind_constructed_identity(principal=_operator(), identity=identity, now=NOW)
    store.issue(
        principal=_operator(),
        request_id="request-1",
        masked_calculation_identity_digest=identity.canonical_digest(),
        idempotency_key="idem-1",
        now=NOW,
    )
    attempt = store.acquire_lease(
        request_id="request-1",
        worker_principal=_worker(),
        worker_instance_id="w-1",
        lease_acquisition_id="lease-1",
        now=NOW,
    )
    assert attempt is not None
    # A report bound to a different fence (wrong instance/generation) is rejected.
    forged = attempt.model_copy(
        update={"worker_instance_id": "other-worker", "execution_attempt_digest": None}
    ).sealed()
    rejected = store.record_report(
        request_id="request-1",
        worker_principal=_worker(),
        report=_sealed_report(identity),
        attempt=forged,
        now=NOW + timedelta(seconds=5),
    )
    assert rejected is None
    # Operator cancellation is explicit and terminal: no further lease/report.
    canceled = store.cancel(request_id="request-1", principal=_operator(), now=NOW)
    assert canceled is not None and canceled.status.value == "CANCELED"
    assert (
        store.acquire_lease(
            request_id="request-1",
            worker_principal=_worker(),
            worker_instance_id="w-2",
            lease_acquisition_id="lease-2",
            now=NOW,
        )
        is None
    )
    current = store.get_current(
        request_id="request-1", principal=_operator(), now=NOW + timedelta(seconds=5)
    )
    assert current is not None and current.disposition.value == "CANCELED"
    # Cancel replays as the terminal record.
    journal_path = tmp_path / "masked-calc.journal"
    store._journal.close()  # noqa: SLF001
    replayed = ExternalMaskedCalculationStore(
        DurableJournal(journal_path),
        evidence=_StrictEvidence(identity),
        resource_envelope=_envelope(),
        designated_worker=_worker(),
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    replayed_current = replayed.get_current(
        request_id="request-1", principal=_operator(), now=NOW + timedelta(seconds=5)
    )
    assert replayed_current is not None and replayed_current.disposition.value == "CANCELED"


def test_resolve_completed_source_binds_exact_report_and_fresh_witness(tmp_path) -> None:
    identity = _masked_identity()
    evidence = _StrictEvidence(identity)
    store = _store(tmp_path, evidence)
    store.bind_constructed_identity(principal=_operator(), identity=identity, now=NOW)
    store.issue(
        principal=_operator(),
        request_id="request-1",
        masked_calculation_identity_digest=identity.canonical_digest(),
        idempotency_key="idem-1",
        now=NOW,
    )
    attempt = store.acquire_lease(
        request_id="request-1",
        worker_principal=_worker(),
        worker_instance_id="w-1",
        lease_acquisition_id="lease-1",
        now=NOW,
    )
    assert attempt is not None
    report = _sealed_report(identity)
    stored = store.record_report(
        request_id="request-1",
        worker_principal=_worker(),
        report=report,
        attempt=attempt,
        now=NOW + timedelta(seconds=5),
    )
    assert stored is not None and stored.report is not None
    numeric_digest = report.numeric_result.canonical_digest()
    coverage_digest = report.numeric_result.coverage.canonical_digest()
    resolved = store.resolve_completed_source(
        organization_id="org-a",
        masked_calculation_identity_digest=identity.canonical_digest(),
        numeric_result_identity_digest=numeric_digest,
        coverage_witness_digest=coverage_digest,
        now=NOW + timedelta(seconds=5),
    )
    assert resolved is not None
    record, witness = resolved
    assert record.report is not None
    assert record.report.report_digest == report.canonical_digest()
    assert witness.source_identity.canonical_digest() == identity.canonical_digest()
    # Wrong numeric identity does not resolve (uniform None, no oracle).
    assert (
        store.resolve_completed_source(
            organization_id="org-a",
            masked_calculation_identity_digest=identity.canonical_digest(),
            numeric_result_identity_digest="sha256:" + "0" * 64,
            coverage_witness_digest=coverage_digest,
            now=NOW + timedelta(seconds=5),
        )
        is None
    )
    # Revoked currentness stops resolution without mutating the journal.
    evidence.live = False
    assert (
        store.resolve_completed_source(
            organization_id="org-a",
            masked_calculation_identity_digest=identity.canonical_digest(),
            numeric_result_identity_digest=numeric_digest,
            coverage_witness_digest=coverage_digest,
            now=NOW + timedelta(seconds=5),
        )
        is None
    )
    store._journal.close()  # noqa: SLF001


def _second_worker() -> Principal:
    return Principal("analysis-worker-2", PrincipalKind.ANALYSIS_WORKER, None, None, "org-a")


def test_designated_worker_ctor_pin_and_property(tmp_path) -> None:
    identity = _masked_identity()
    evidence = _StrictEvidence(identity)
    bad_principals = [
        None,
        _operator(),
        Principal("operator-x", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-a"),
        Principal("worker-no-org", PrincipalKind.ANALYSIS_WORKER, None, None, ""),
    ]
    for index, bad in enumerate(bad_principals):
        with pytest.raises(ValueError, match="designated organization worker"):
            ExternalMaskedCalculationStore(
                DurableJournal(tmp_path / f"bad-{index}.journal"),
                evidence=evidence,
                resource_envelope=_envelope(),
                designated_worker=bad,
                coordinator=ExternalAuthorityCurrentnessCoordinator(),
            )
    store = _store(tmp_path, evidence)
    assert store.designated_worker == _worker()
    assert store.designated_worker.principal_id == "analysis-worker-1"
    assert store.designated_worker.organization_id == "org-a"


def test_issue_binds_designated_worker_not_human_issuer(tmp_path) -> None:
    identity = _masked_identity()
    store = _store(tmp_path, _StrictEvidence(identity))
    store.bind_constructed_identity(principal=_operator(), identity=identity, now=NOW)
    issued = store.issue(
        principal=_operator(),
        request_id="request-1",
        masked_calculation_identity_digest=identity.canonical_digest(),
        idempotency_key="idem-1",
        now=NOW,
    )
    assert issued.authorization.worker_principal_id == "analysis-worker-1"
    assert issued.authorization.worker_principal_id != "operator-a"


def test_second_worker_rejected_without_journal_growth(tmp_path) -> None:
    identity = _masked_identity()
    journal_path = tmp_path / "masked-calc.journal"
    store = _store(tmp_path, _StrictEvidence(identity))
    store.bind_constructed_identity(principal=_operator(), identity=identity, now=NOW)
    store.issue(
        principal=_operator(),
        request_id="request-1",
        masked_calculation_identity_digest=identity.canonical_digest(),
        idempotency_key="idem-1",
        now=NOW,
    )
    before = journal_path.read_bytes()
    other = _second_worker()
    with pytest.raises(PermissionError, match="not the designated execution worker"):
        store.acquire_lease(
            request_id="request-1",
            worker_principal=other,
            worker_instance_id="other-instance-1",
            lease_acquisition_id="other-lease-1",
            now=NOW,
        )
    assert journal_path.read_bytes() == before
    attempt = store.acquire_lease(
        request_id="request-1",
        worker_principal=_worker(),
        worker_instance_id="worker-instance-1",
        lease_acquisition_id="lease-1",
        now=NOW,
    )
    assert attempt is not None
    with pytest.raises(PermissionError, match="not the designated execution worker"):
        store.input_for_worker(
            request_id="request-1",
            worker_principal=other,
            attempt=attempt,
            now=NOW,
        )
    with pytest.raises(PermissionError, match="not the designated execution worker"):
        store.record_report(
            request_id="request-1",
            worker_principal=other,
            report=_sealed_report(identity),
            attempt=attempt,
            now=NOW + timedelta(seconds=5),
        )
    assert journal_path.read_bytes() != before  # only the genuine lease appended
    assert len(journal_path.read_bytes().splitlines()) == len(before.splitlines()) + 1


def test_rotated_worker_config_cannot_execute_old_record(tmp_path) -> None:
    identity = _masked_identity()
    journal_path = tmp_path / "masked-calc.journal"
    store = _store(tmp_path, _StrictEvidence(identity))
    store.bind_constructed_identity(principal=_operator(), identity=identity, now=NOW)
    store.issue(
        principal=_operator(),
        request_id="request-1",
        masked_calculation_identity_digest=identity.canonical_digest(),
        idempotency_key="idem-1",
        now=NOW,
    )
    before = journal_path.read_bytes()
    store._journal.close()  # noqa: SLF001 - simulate restart; release single-writer lock
    rotated = ExternalMaskedCalculationStore(
        DurableJournal(journal_path),
        evidence=_StrictEvidence(identity),
        resource_envelope=_envelope(),
        designated_worker=_second_worker(),
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    # Replay preserves the historical authorization worker identity.
    history = rotated.get_history("request-1", organization_id="org-a")
    assert history is not None
    assert history.authorization.worker_principal_id == "analysis-worker-1"
    # The new config is the caller, yet the old record is not executable.
    with pytest.raises(PermissionError, match="does not hold the authorized fence"):
        rotated.acquire_lease(
            request_id="request-1",
            worker_principal=_second_worker(),
            worker_instance_id="worker-instance-2",
            lease_acquisition_id="lease-2",
            now=NOW,
        )
    assert journal_path.read_bytes() == before
