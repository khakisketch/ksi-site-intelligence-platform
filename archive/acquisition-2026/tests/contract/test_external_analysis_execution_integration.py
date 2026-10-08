"""Connected local proof for AP, Core execution, and real GeoTIFF measurement."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Lock

import numpy as np
import pytest
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    AnalysisAssessmentRecord,
    AnalysisAssessmentRequestV2,
    AnalysisEpochSelectionV2,
    AnalysisRuntimeIdentityV2,
    ExternalRelativeVolumeAnalysisStore,
    _PreparedExecutionWitness,
)
from ksi_core.domains.external.quantity.external_relative_volume_calculations import (
    CalculationCurrentDispositionV2,
    CalculationExecutionStatusV2,
    ExternalRelativeVolumeCalculationStore,
)
from ksi_core.durable_journal import DurableJournal
from ksi_event_contracts.external_artifact_validation import ObservedVerticalReferenceV1
from ksi_event_contracts.external_relative_volume_analysis import AdmissionV2, AnalysisPolicyV2
from ksi_event_contracts.external_relative_volume_calculation import (
    RelativeVolumeCalculationFailureV2,
    RelativeVolumeCalculationReportV2,
)
from ksi_processing_controller.external_analysis_measurement import (
    measure_external_relative_volume_v2,
)
from pyproj import CRS
from rasterio.io import MemoryFile
from rasterio.transform import Affine, from_origin
from test_external_quantitative_production_flow import (
    _admit_policy,
    _analysis_worker_principal,
    _assemble,
    _digest,
    _inspect,
    _LocalObjectStorage,
    _principal,
    _RetainedEvidenceContextAuthority,
    _RetainedPolicyAuthority,
    _sealed_revision,
    _validate_evidence,
    _workflow,
)

_ORIGIN_X = 200_000.0
_ORIGIN_Y = 550_000.0


def _geotiff_bytes(values: np.ndarray, *, transform: Affine | None = None) -> bytes:
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=values.shape[0],
            width=values.shape[1],
            count=1,
            dtype="float64",
            crs=CRS.from_user_input("EPSG:5186+5773"),
            transform=transform or from_origin(_ORIGIN_X, _ORIGIN_Y, 1.0, 1.0),
        ) as dataset:
            dataset.write(values, 1)
        return memory.read()


def _policy() -> AnalysisPolicyV2:
    return AnalysisPolicyV2(
        policy_id="connected-relative-volume-v2",
        version=2,
        profile_id="KSI-GIS-RELATIVE-VOLUME-V2",
        profile_digest=_digest("connected-profile"),
        algorithm_digest=_digest("connected-algorithm"),
        config_digest=_digest("connected-config"),
        baseline_grid_rule="BASELINE_NATIVE_NORTH_UP_AFFINE_V1",
        current_elevation_resampling="BILINEAR",
        current_mask_resampling="NEAREST",
        work_area_rasterization="CELL_CENTER",
        minimum_common_valid_fraction=1.0,
        threshold_m=0.0,
        cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
        delta_rule="CURRENT_MINUS_BASELINE",
        uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
    ).sealed()


def test_core_issued_attempt_measures_and_persists_real_geotiff_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact Core attempt and AP identity travel through the real worker once."""
    now = datetime.now(UTC).replace(microsecond=0)
    storage = _LocalObjectStorage()
    policy_authority = _RetainedPolicyAuthority()
    context_authority = _RetainedEvidenceContextAuthority(now)
    workflow, _catalog, envelope, _catalog_authority = _workflow(
        tmp_path,
        now=now,
        policy_authority=policy_authority,
        context_authority=context_authority,
    )
    app, opened = _assemble(tmp_path, workflow, storage)
    try:
        assert (
            app.state.site_store.register(
                "site-a",
                "Connected local execution site",
                __import__("ksi_mission_contracts.models", fromlist=["SiteFrame"]).SiteFrame(
                    crs="EPSG:5186",
                    vertical_datum="EGM96 height",
                    unit="meter",
                    transform_version="1.0.0",
                ),
                organization_id="org-a",
                actor="operator-a",
                now=now - timedelta(minutes=30),
            ).record
            is not None
        )
        fractional_transform = from_origin(_ORIGIN_X, _ORIGIN_Y, 0.1, 0.1)
        polygon = {
            "type": "Polygon",
            "coordinates": [
                [
                    [_ORIGIN_X - 0.01, _ORIGIN_Y + 0.01],
                    [_ORIGIN_X - 0.01, _ORIGIN_Y - 0.2],
                    [_ORIGIN_X + 0.2, _ORIGIN_Y - 0.2],
                    [_ORIGIN_X + 0.2, _ORIGIN_Y + 0.01],
                    [_ORIGIN_X - 0.01, _ORIGIN_Y + 0.01],
                ]
            ],
        }
        positive_offset_polygon = {
            "type": "Polygon",
            "coordinates": [
                [
                    [_ORIGIN_X + 0.11, _ORIGIN_Y - 0.11],
                    [_ORIGIN_X + 0.11, _ORIGIN_Y - 0.21],
                    [_ORIGIN_X + 0.21, _ORIGIN_Y - 0.21],
                    [_ORIGIN_X + 0.21, _ORIGIN_Y - 0.11],
                    [_ORIGIN_X + 0.11, _ORIGIN_Y - 0.11],
                ]
            ],
        }
        area_result = app.state.work_area_store.register(
            "site-a",
            name="Connected two-cell GeoTIFF area",
            polygon=polygon,
            crs="EPSG:5186",
            supersedes=None,
            actor="operator-a",
            now=now - timedelta(minutes=29),
        )
        assert area_result.work_area is not None
        area = area_result.work_area
        orders = app.state.observation_work_order_store
        baseline_order = orders.create_work_order(
            organization_id="org-a",
            site_id="site-a",
            name="Connected baseline",
            work_area_ids=[area.work_area_id],
            schedule_id=None,
            actor="operator-a",
            now=now - timedelta(minutes=28),
        )
        current_order = orders.create_work_order(
            organization_id="org-a",
            site_id="site-a",
            name="Connected current",
            work_area_ids=[area.work_area_id],
            schedule_id=None,
            actor="operator-a",
            now=now - timedelta(minutes=27),
        )
        baseline_bytes = _geotiff_bytes(np.full((2, 2), 100.0), transform=fractional_transform)
        current_bytes = _geotiff_bytes(
            np.array([[101.0, 99.0], [100.0, 100.0]]),
            transform=fractional_transform,
        )
        baseline_path = tmp_path / "connected-baseline.tif"
        current_path = tmp_path / "connected-current.tif"
        baseline_path.write_bytes(baseline_bytes)
        current_path.write_bytes(current_bytes)
        baseline_revision, baseline_subject = _sealed_revision(
            app,
            baseline_order,
            "connected-baseline",
            start=now - timedelta(minutes=20),
            end=now - timedelta(minutes=15),
            storage=storage,
            dsm_bytes=baseline_bytes,
        )
        current_revision, current_subject = _sealed_revision(
            app,
            current_order,
            "connected-current",
            start=now - timedelta(minutes=10),
            end=now - timedelta(minutes=5),
            storage=storage,
            dsm_bytes=current_bytes,
        )
        inspection_policy = _admit_policy(
            app,
            subjects=(baseline_subject, current_subject),
            envelope=envelope,
            authority=policy_authority,
            now=now,
        )
        horizontal_wkt = CRS.from_epsg(5186).to_wkt(
            version="WKT2_2019", pretty=False, output_axis_rule=True
        )
        horizontal_digest = _digest(horizontal_wkt)
        transform = tuple(fractional_transform)[:6]
        vertical = ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")
        for revision, subject in (
            (baseline_revision, baseline_subject),
            (current_revision, current_subject),
        ):
            _inspect(
                app,
                revision=revision,
                subject=subject,
                policy=inspection_policy,
                now=now,
                transform=transform,
                vertical_reference=vertical,
                observed_crs_digest=horizontal_digest,
            )
            _validate_evidence(
                app,
                revision=revision,
                subject=subject,
                policy=inspection_policy,
                context_authority=context_authority,
                now=now,
                storage=storage,
                label="connected-" + subject.submission_id,
            )
        assessments = ExternalRelativeVolumeAnalysisStore(
            DurableJournal(tmp_path / "connected-assessments.jsonl"),
            reconstruction=app.state.external_reconstruction_store,
            inspections=app.state.external_artifact_inspection_store,
            work_areas=app.state.work_area_store,
            evidence=app.state.external_evidence_store,
            validations=app.state.external_evidence_validation_store,
            policy=_policy(),
            runtime=AnalysisRuntimeIdentityV2(
                worker_executable_digest=_digest("connected-worker"),
                worker_build_digest=_digest("connected-build"),
                runtime_image_version="2.0.0",
                runtime_image_oci_digest=_digest("connected-oci"),
                dependency_lock_digest=_digest("connected-lock"),
            ),
            clock=lambda: now,
        )
        assessed = assessments.assess_and_record(
            principal=_principal(),
            request=AnalysisAssessmentRequestV2(
                request_id="connected-assessment",
                work_area_id=area.work_area_id,
                baseline=AnalysisEpochSelectionV2(subject=baseline_subject),
                current=AnalysisEpochSelectionV2(subject=current_subject),
                idempotency_key="connected-assessment-key",
            ),
            now=now,
        )
        identity = assessed.admission.calculation_identity
        assert identity is not None
        # The public facade has SITES_READ on GET.  Its currentness probe must
        # remain a side-effect-free read and may not manufacture SITES_WRITE.
        assert (
            assessments.get_current_for_read(
                "connected-assessment", principal=_principal(), now=now
            )
            == assessed
        )
        queue_area_result = app.state.work_area_store.register(
            "site-a",
            name="Connected second GeoTIFF area",
            polygon=positive_offset_polygon,
            crs="EPSG:5186",
            supersedes=None,
            actor="operator-a",
            now=now - timedelta(minutes=29),
        )
        assert queue_area_result.work_area is not None
        queue_assessed = assessments.assess_and_record(
            principal=_principal(),
            request=AnalysisAssessmentRequestV2(
                request_id="connected-queue-assessment",
                work_area_id=queue_area_result.work_area.work_area_id,
                baseline=AnalysisEpochSelectionV2(subject=baseline_subject),
                current=AnalysisEpochSelectionV2(subject=current_subject),
                idempotency_key="connected-queue-assessment-key",
            ),
            now=now,
        )
        queue_identity = queue_assessed.admission.calculation_identity
        assert queue_identity is not None
        concurrent_issues = ExternalRelativeVolumeCalculationStore(
            DurableJournal(tmp_path / "connected-concurrent-issues.jsonl"),
            assessments=assessments,
            resource_envelope=envelope,
        )
        issue_preflight_barrier = Barrier(2)
        original_prepare_witness = assessments.prepare_execution_witness
        currentness_barrier = Barrier(2)
        currentness_lock = Lock()
        currentness_calls = 0
        original_witness_is_current = assessments.execution_witness_is_current

        def synchronized_prepare_witness(
            *,
            calculation_identity_digest: str,
            organization_id: str,
            now: datetime,
            expected_admission: AdmissionV2 | None = None,
        ) -> _PreparedExecutionWitness | None:
            witness = original_prepare_witness(
                calculation_identity_digest=calculation_identity_digest,
                organization_id=organization_id,
                now=now,
                expected_admission=expected_admission,
            )
            issue_preflight_barrier.wait(timeout=5)
            return witness

        def synchronized_witness_is_current(
            *, witness: _PreparedExecutionWitness | None, now: datetime
        ) -> AnalysisAssessmentRecord | None:
            nonlocal currentness_calls
            result = original_witness_is_current(witness=witness, now=now)
            with currentness_lock:
                currentness_calls += 1
                must_wait = currentness_calls <= 2
            if must_wait:
                currentness_barrier.wait(timeout=5)
            return result

        with monkeypatch.context() as scoped_patch:
            scoped_patch.setattr(
                assessments, "prepare_execution_witness", synchronized_prepare_witness
            )
            scoped_patch.setattr(
                assessments, "execution_witness_is_current", synchronized_witness_is_current
            )
            with ThreadPoolExecutor(max_workers=2) as executor:
                raced_issues = tuple(
                    executor.map(
                        lambda index: concurrent_issues.issue(
                            principal=_principal(),
                            request_id=f"connected-race-{index}",
                            calculation_identity_digest=identity.canonical_digest(),
                            idempotency_key=f"connected-race-key-{index}",
                            now=now,
                        ),
                        (1, 2),
                    )
                )
        assert {item.request_id for item in raced_issues} in (
            {"connected-race-1"},
            {"connected-race-2"},
        )
        executions = ExternalRelativeVolumeCalculationStore(
            DurableJournal(tmp_path / "connected-executions.jsonl"),
            assessments=assessments,
            resource_envelope=envelope,
        )
        issued = executions.issue(
            principal=_principal(),
            request_id="connected-execution",
            calculation_identity_digest=identity.canonical_digest(),
            idempotency_key="connected-execution-key",
            now=now,
        )
        assert issued.status is CalculationExecutionStatusV2.QUEUED
        queue_envelope = envelope.model_copy(
            update={"max_queue_depth": 1, "resource_envelope_digest": None}
        ).sealed()
        queue_limited = ExternalRelativeVolumeCalculationStore(
            DurableJournal(tmp_path / "connected-queue-limited.jsonl"),
            assessments=assessments,
            resource_envelope=queue_envelope,
        )
        queue_limited.issue(
            principal=_principal(),
            request_id="connected-queue-first",
            calculation_identity_digest=identity.canonical_digest(),
            idempotency_key="connected-queue-first-key",
            now=now,
        )
        with pytest.raises(RuntimeError, match="queue capacity"):
            queue_limited.issue(
                principal=_principal(),
                request_id="connected-queue-second",
                calculation_identity_digest=queue_identity.canonical_digest(),
                idempotency_key="connected-queue-second-key",
                now=now,
            )
        concurrency_envelope = envelope.model_copy(
            update={"max_tenant_concurrency": 1, "resource_envelope_digest": None}
        ).sealed()
        concurrency_limited = ExternalRelativeVolumeCalculationStore(
            DurableJournal(tmp_path / "connected-concurrency-limited.jsonl"),
            assessments=assessments,
            resource_envelope=concurrency_envelope,
        )
        concurrency_limited.issue(
            principal=_principal(),
            request_id="connected-concurrency-first",
            calculation_identity_digest=identity.canonical_digest(),
            idempotency_key="connected-concurrency-first-key",
            now=now,
        )
        concurrency_limited.issue(
            principal=_principal(),
            request_id="connected-concurrency-second",
            calculation_identity_digest=queue_identity.canonical_digest(),
            idempotency_key="connected-concurrency-second-key",
            now=now,
        )
        concurrency_first = concurrency_limited.acquire_lease(
            request_id="connected-concurrency-first",
            worker_principal=_analysis_worker_principal(),
            worker_instance_id="connected-concurrency-worker-1",
            lease_acquisition_id="connected-concurrency-lease-1",
            now=now,
        )
        assert concurrency_first is not None
        assert (
            concurrency_limited.acquire_lease(
                request_id="connected-concurrency-second",
                worker_principal=_analysis_worker_principal(),
                worker_instance_id="connected-concurrency-worker-2",
                lease_acquisition_id="connected-concurrency-lease-2",
                now=now,
            )
            is None
        )
        assert (
            concurrency_limited.acquire_lease(
                request_id="connected-concurrency-second",
                worker_principal=_analysis_worker_principal(),
                worker_instance_id="connected-concurrency-worker-2",
                lease_acquisition_id="connected-concurrency-lease-2",
                now=concurrency_first.lease_expires_at + timedelta(microseconds=1),
            )
            is not None
        )
        attempt = executions.acquire_lease(
            request_id="connected-execution",
            worker_principal=_analysis_worker_principal(),
            worker_instance_id="connected-worker-1",
            lease_acquisition_id="connected-lease-1",
            now=now,
        )
        assert attempt is not None
        renewal_at = now + timedelta(seconds=1)
        renewed = executions.renew_lease(
            request_id="connected-execution",
            worker_principal=_analysis_worker_principal(),
            attempt=attempt,
            now=renewal_at,
        )
        assert renewed is not None
        assert renewed.execution_attempt_digest != attempt.execution_attempt_digest
        assert (
            executions.renew_lease(
                request_id="connected-execution",
                worker_principal=_analysis_worker_principal(),
                attempt=attempt,
                now=renewal_at,
            )
            is None
        )
        stale_report = measure_external_relative_volume_v2(
            attempt=attempt,
            calculation_identity=identity,
            baseline_path=baseline_path,
            current_path=current_path,
            report_id="connected-stale-report",
            computed_at=renewal_at,
            reported_at=renewal_at,
        )
        assert isinstance(stale_report, RelativeVolumeCalculationReportV2)
        assert (
            executions.record_report(
                request_id="connected-execution",
                worker_principal=_analysis_worker_principal(),
                report=stale_report,
                now=renewal_at,
            )
            is None
        )
        assert (
            executions.input_for_worker(
                request_id="connected-execution",
                worker_principal=_analysis_worker_principal(),
                attempt=attempt,
                now=renewal_at,
            )
            is None
        )
        worker_input = executions.input_for_worker(
            request_id="connected-execution",
            worker_principal=_analysis_worker_principal(),
            attempt=renewed,
            now=renewal_at,
        )
        assert worker_input is not None and worker_input.active_attempt == renewed
        measured = measure_external_relative_volume_v2(
            attempt=renewed,
            calculation_identity=identity,
            baseline_path=baseline_path,
            current_path=current_path,
            report_id="connected-report",
            computed_at=renewal_at,
            reported_at=renewal_at,
        )
        assert isinstance(measured, RelativeVolumeCalculationReportV2)
        assert measured.numeric_result.metrics.fill_m3 == pytest.approx(0.01)
        assert measured.numeric_result.metrics.cut_m3 == pytest.approx(0.01)
        assert measured.numeric_result.coverage.row_offset == -1
        assert measured.numeric_result.coverage.column_offset == -1
        assert measured.numeric_result.coverage.selected_mask_b64 == "BmA="
        persisted = executions.record_report(
            request_id="connected-execution",
            worker_principal=_analysis_worker_principal(),
            report=measured,
            now=renewal_at,
        )
        assert persisted is not None and persisted.report == measured
        assert (
            executions.record_report(
                request_id="connected-execution",
                worker_principal=_analysis_worker_principal(),
                report=measured,
                now=renewal_at,
            )
            == persisted
        )
        positive_executions = ExternalRelativeVolumeCalculationStore(
            DurableJournal(tmp_path / "connected-positive-offset-executions.jsonl"),
            assessments=assessments,
            resource_envelope=envelope,
        )
        positive_executions.issue(
            principal=_principal(),
            request_id="connected-positive-offset-execution",
            calculation_identity_digest=queue_identity.canonical_digest(),
            idempotency_key="connected-positive-offset-execution-key",
            now=renewal_at,
        )
        positive_attempt = positive_executions.acquire_lease(
            request_id="connected-positive-offset-execution",
            worker_principal=_analysis_worker_principal(),
            worker_instance_id="connected-positive-offset-worker",
            lease_acquisition_id="connected-positive-offset-lease",
            now=renewal_at,
        )
        assert positive_attempt is not None
        positive_report = measure_external_relative_volume_v2(
            attempt=positive_attempt,
            calculation_identity=queue_identity,
            baseline_path=baseline_path,
            current_path=current_path,
            report_id="connected-positive-offset-report",
            computed_at=renewal_at,
            reported_at=renewal_at,
        )
        assert isinstance(positive_report, RelativeVolumeCalculationReportV2), (
            positive_report.reason_code
        )
        positive_coverage = positive_report.numeric_result.coverage
        assert positive_coverage.row_offset == 1
        assert positive_coverage.column_offset == 1
        assert positive_coverage.bounds[2] == 200000.30000000002
        assert positive_coverage.bounds[2] != 200000.3
        positive_persisted = positive_executions.record_report(
            request_id="connected-positive-offset-execution",
            worker_principal=_analysis_worker_principal(),
            report=positive_report,
            now=renewal_at,
        )
        assert positive_persisted is not None and positive_persisted.report == positive_report
        positive_executions._journal.close()  # noqa: SLF001
        positive_replayed = ExternalRelativeVolumeCalculationStore(
            DurableJournal(tmp_path / "connected-positive-offset-executions.jsonl"),
            assessments=assessments,
            resource_envelope=envelope,
        )
        assert (
            positive_replayed.get_history_for_principal(
                "connected-positive-offset-execution", principal=_principal()
            )
            == positive_persisted
        )
        assert (
            executions.get_history_for_principal("connected-execution", principal=_principal())
            == persisted
        )
        assert (
            executions.get_history_for_principal(
                "connected-execution", principal=_principal("org-b")
            )
            is None
        )
        executions._journal.close()  # noqa: SLF001 - prove the actual renewed event replays.
        replayed_executions = ExternalRelativeVolumeCalculationStore(
            DurableJournal(tmp_path / "connected-executions.jsonl"),
            assessments=assessments,
            resource_envelope=envelope,
        )
        assert (
            replayed_executions.get_history_for_principal(
                "connected-execution", principal=_principal()
            )
            == persisted
        )
        current = executions.get_current(
            request_id="connected-execution", principal=_principal(), now=renewal_at
        )
        assert current is not None
        assert current.disposition is CalculationCurrentDispositionV2.AVAILABLE
        assert current.report == measured
        failures = ExternalRelativeVolumeCalculationStore(
            DurableJournal(tmp_path / "connected-failures.jsonl"),
            assessments=assessments,
            resource_envelope=envelope,
        )
        failures.issue(
            principal=_principal(),
            request_id="connected-failure",
            calculation_identity_digest=identity.canonical_digest(),
            idempotency_key="connected-failure-key",
            now=renewal_at,
        )
        failing_attempt = failures.acquire_lease(
            request_id="connected-failure",
            worker_principal=_analysis_worker_principal(),
            worker_instance_id="connected-worker-2",
            lease_acquisition_id="connected-lease-2",
            now=renewal_at,
        )
        assert failing_attempt is not None
        corrupt_current_path = tmp_path / "connected-current-corrupt.tif"
        corrupt_current_path.write_bytes(b"not the sealed GeoTIFF")
        failed_measurement = measure_external_relative_volume_v2(
            attempt=failing_attempt,
            calculation_identity=identity,
            baseline_path=baseline_path,
            current_path=corrupt_current_path,
            report_id="connected-failure-report",
            computed_at=renewal_at,
            reported_at=renewal_at,
        )
        assert isinstance(failed_measurement, RelativeVolumeCalculationFailureV2)
        failure_record = failures.record_failure(
            request_id="connected-failure",
            worker_principal=_analysis_worker_principal(),
            failure=failed_measurement,
            now=renewal_at,
        )
        assert failure_record is not None and failure_record.failure == failed_measurement
        assert (
            failures.record_failure(
                request_id="connected-failure",
                worker_principal=_analysis_worker_principal(),
                failure=failed_measurement,
                now=renewal_at,
            )
            == failure_record
        )
        failure_view = failures.get_current(
            request_id="connected-failure", principal=_principal(), now=renewal_at
        )
        assert failure_view is not None
        assert failure_view.disposition is CalculationCurrentDispositionV2.FAILED
        retry_envelope = envelope.model_copy(
            update={
                "lease_duration_seconds": 1.0,
                "max_deadline_seconds": 5.0,
                "max_retry_attempts": 2,
                "resource_envelope_digest": None,
            }
        ).sealed()
        retries = ExternalRelativeVolumeCalculationStore(
            DurableJournal(tmp_path / "connected-retries.jsonl"),
            assessments=assessments,
            resource_envelope=retry_envelope,
        )
        retries.issue(
            principal=_principal(),
            request_id="connected-retry",
            calculation_identity_digest=identity.canonical_digest(),
            idempotency_key="connected-retry-key",
            now=renewal_at,
        )
        retry_first = retries.acquire_lease(
            request_id="connected-retry",
            worker_principal=_analysis_worker_principal(),
            worker_instance_id="connected-retry-worker-1",
            lease_acquisition_id="connected-retry-lease-1",
            now=renewal_at,
        )
        assert retry_first is not None
        retry_second = retries.acquire_lease(
            request_id="connected-retry",
            worker_principal=_analysis_worker_principal(),
            worker_instance_id="connected-retry-worker-2",
            lease_acquisition_id="connected-retry-lease-2",
            now=retry_first.lease_expires_at + timedelta(microseconds=1),
        )
        assert retry_second is not None and retry_second.lease_generation == 2
        active_final_retry = retries.get_current(
            request_id="connected-retry",
            principal=_principal(),
            now=retry_second.issued_at,
        )
        assert active_final_retry is not None
        assert active_final_retry.disposition is CalculationCurrentDispositionV2.PENDING
        assert (
            retries.acquire_lease(
                request_id="connected-retry",
                worker_principal=_analysis_worker_principal(),
                worker_instance_id="connected-retry-worker-3",
                lease_acquisition_id="connected-retry-lease-3",
                now=retry_second.lease_expires_at + timedelta(microseconds=1),
            )
            is None
        )
        retry_current = retries.get_current(
            request_id="connected-retry",
            principal=_principal(),
            now=retry_second.lease_expires_at + timedelta(microseconds=1),
        )
        assert retry_current is not None
        assert (
            retry_current.disposition is CalculationCurrentDispositionV2.EXECUTION_RETRY_EXHAUSTED
        )
        deadline_envelope = envelope.model_copy(
            update={
                "max_deadline_seconds": 0.5,
                "resource_envelope_digest": None,
            }
        ).sealed()
        deadlines = ExternalRelativeVolumeCalculationStore(
            DurableJournal(tmp_path / "connected-deadlines.jsonl"),
            assessments=assessments,
            resource_envelope=deadline_envelope,
        )
        deadlines.issue(
            principal=_principal(),
            request_id="connected-deadline",
            calculation_identity_digest=identity.canonical_digest(),
            idempotency_key="connected-deadline-key",
            now=renewal_at,
        )
        assert (
            deadlines.acquire_lease(
                request_id="connected-deadline",
                worker_principal=_analysis_worker_principal(),
                worker_instance_id="connected-deadline-worker",
                lease_acquisition_id="connected-deadline-lease",
                now=renewal_at + timedelta(seconds=1),
            )
            is None
        )
        deadline_current = deadlines.get_current(
            request_id="connected-deadline",
            principal=_principal(),
            now=renewal_at + timedelta(seconds=1),
        )
        assert deadline_current is not None
        assert (
            deadline_current.disposition
            is CalculationCurrentDispositionV2.EXECUTION_DEADLINE_EXPIRED
        )
        completed_after_deadline = ExternalRelativeVolumeCalculationStore(
            DurableJournal(tmp_path / "connected-completed-deadline.jsonl"),
            assessments=assessments,
            resource_envelope=deadline_envelope,
        )
        completed_after_deadline.issue(
            principal=_principal(),
            request_id="connected-completed-deadline",
            calculation_identity_digest=identity.canonical_digest(),
            idempotency_key="connected-completed-deadline-key",
            now=renewal_at,
        )
        completed_attempt = completed_after_deadline.acquire_lease(
            request_id="connected-completed-deadline",
            worker_principal=_analysis_worker_principal(),
            worker_instance_id="connected-completed-deadline-worker",
            lease_acquisition_id="connected-completed-deadline-lease",
            now=renewal_at,
        )
        assert completed_attempt is not None
        completed_report = measure_external_relative_volume_v2(
            attempt=completed_attempt,
            calculation_identity=identity,
            baseline_path=baseline_path,
            current_path=current_path,
            report_id="connected-completed-deadline-report",
            computed_at=renewal_at,
            reported_at=renewal_at,
        )
        assert isinstance(completed_report, RelativeVolumeCalculationReportV2)
        assert (
            completed_after_deadline.record_report(
                request_id="connected-completed-deadline",
                worker_principal=_analysis_worker_principal(),
                report=completed_report,
                now=renewal_at,
            )
            is not None
        )
        completed_current = completed_after_deadline.get_current(
            request_id="connected-completed-deadline",
            principal=_principal(),
            now=renewal_at + timedelta(seconds=1),
        )
        assert completed_current is not None
        assert completed_current.disposition is CalculationCurrentDispositionV2.AVAILABLE
    finally:
        for journal in (
            locals().get("assessments"),
            locals().get("executions"),
            locals().get("failures"),
            locals().get("queue_limited"),
            locals().get("concurrency_limited"),
            locals().get("retries"),
            locals().get("deadlines"),
            locals().get("completed_after_deadline"),
            locals().get("concurrent_issues"),
            locals().get("replayed_executions"),
        ):
            if journal is not None:
                journal._journal.close()  # noqa: SLF001
        for journal in reversed(opened):
            journal.close()
