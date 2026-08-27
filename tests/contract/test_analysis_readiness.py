"""Contract tests for immutable capture-quality intake and Analysis Readiness.

These deliberately use a small read-model fixture for the evidence joins, but
exercise the durable CaptureQualityReportStore against the real Mission,
WorkOrder, and AcquisitionRun ledgers.  Readiness is allowed only when each
authoritative evidence source is present and internally consistent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from ksi_core.acquisition.analysis_readiness import AnalysisReadinessProjector
from ksi_core.acquisition.coordination import AcquisitionCoordinationStore
from ksi_core.acquisition.models import AnalysisReadinessStatus
from ksi_core.capture_quality_reports import (
    CaptureQualityReportStore,
    CaptureQualityReportVerdict,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionRecord, MissionRecordVerdict, MissionStore
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.source_media import (
    CaptureTime,
    CaptureTimeSource,
    CaptureTimeStatus,
    SourceMediaBundle,
    SourceMediaRecord,
)
from ksi_event_contracts.capture_quality import CaptureQualityReport, CaptureQualityStatus
from ksi_event_contracts.observation_work_order import (
    ObservationWorkOrder,
    TemporalCoherencePolicy,
)

_NOW = datetime(2026, 8, 27, 1, 0, tzinfo=UTC)
_ORG = "org-readiness"
_SITE = "site-readiness"
_WORK_ORDER = "obs-work-00000001"
_MISSION = "mission-readiness-1"
_DEVICE = "manifold-readiness-1"


def _work_order(*, temporal_policy: TemporalCoherencePolicy | None) -> ObservationWorkOrder:
    return ObservationWorkOrder.model_validate(
        {
            "schemaVersion": "1.0",
            "workOrderId": _WORK_ORDER,
            "organizationId": _ORG,
            "siteId": _SITE,
            "purpose": "PROGRESS_QUANTITY",
            "name": "분석 준비 검증",
            "workAreaIds": ["wa-readiness-1"],
            "scheduleId": None,
            "temporalPolicy": (
                temporal_policy.model_dump(by_alias=True) if temporal_policy is not None else None
            ),
            "cycleNumber": 1,
            "status": "APPROVED",
            "statusReason": None,
            "missionIds": [],
            "processingJobIds": [],
            "reportRefs": [],
            "version": 2,
            "createdAt": _NOW.isoformat(),
            "updatedAt": _NOW.isoformat(),
            "createdBy": "operator-readiness",
            "approvedAt": _NOW.isoformat(),
            "approvedBy": "operator-readiness",
        }
    )


def _mission_record() -> MissionRecord:
    return MissionRecord(
        mission_id=_MISSION,
        site_id=_SITE,
        mission_type="BASELINE_MAPPING",
        artifact_kind="pair",
        contract={"schemaVersion": "1.2", "missionId": _MISSION},
        kmz_sha256="sha256:" + "a" * 64,
        route_pattern="lawnmower",
        waypoint_count=4,
        planned_coverage_ratio=1.0,
        issued_at=_NOW,
        issued_by="operator-readiness",
        organization_id=_ORG,
        plan_request={"workOrderId": _WORK_ORDER},
        plan_request_digest="sha256:" + "b" * 64,
        assigned_device_id=_DEVICE,
    )


def _report(
    *,
    report_id: str = "capture-quality-readiness-1",
    work_order_id: str = _WORK_ORDER,
    device_id: str = _DEVICE,
    status: CaptureQualityStatus = CaptureQualityStatus.ACCEPTED,
) -> CaptureQualityReport:
    measurement: dict[str, object] = {
        "artifactId": "artifact-readiness-1",
        "capturedAt": _NOW.isoformat(),
        "blurScore": 0.1,
        "exposureOk": True,
        "gsdCmPerPx": 1.5,
        "overlapRatio": 0.8,
        "occlusionRatio": 0.1,
        "status": status.value,
    }
    if status is CaptureQualityStatus.GAP:
        measurement["gapReasons"] = ["BLUR"]
    return CaptureQualityReport.model_validate(
        {
            "schemaVersion": "1.0",
            "reportId": report_id,
            "organizationId": _ORG,
            "siteId": _SITE,
            "workOrderId": work_order_id,
            "missionId": _MISSION,
            "deviceId": device_id,
            "capturePolicyId": "capture-policy-readiness-1",
            "measurements": [measurement],
            "startedAt": _NOW.isoformat(),
            "completedAt": (_NOW + timedelta(seconds=30)).isoformat(),
        }
    )


def _bound_capture_quality_store(
    tmp_path: Path,
) -> tuple[
    CaptureQualityReportStore,
    CaptureQualityReport,
    MissionStore,
    ObservationWorkOrderStore,
    AcquisitionCoordinationStore,
]:
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    assert mission_store.record_issuance(_mission_record()) is MissionRecordVerdict.RECORDED
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: site_id == _SITE and organization_id == _ORG,
    )
    created = work_orders.create_work_order(
        organization_id=_ORG,
        site_id=_SITE,
        name="분석 준비 검증",
        work_area_ids=["wa-readiness-1"],
        schedule_id=None,
        temporal_policy=TemporalCoherencePolicy(max_capture_span_seconds=600),
        actor="operator-readiness",
        now=_NOW,
    )
    order = work_orders.approve(
        created.work_order_id,
        organization_id=_ORG,
        expected_version=created.version,
        actor="operator-readiness",
        now=_NOW,
    )
    assert order.work_order_id == _WORK_ORDER
    coordination = AcquisitionCoordinationStore(DurableJournal(tmp_path / "acquisition-runs.jsonl"))
    coordination.ensure_run(order, actor="operator-readiness", now=_NOW)
    coordination.link_mission(order, _MISSION, actor="operator-readiness", now=_NOW)
    store = CaptureQualityReportStore(
        DurableJournal(tmp_path / "capture-quality.jsonl"),
        mission_store=mission_store,
        work_order_store=work_orders,
        coordination_store=coordination,
    )
    return store, _report(), mission_store, work_orders, coordination


def test_capture_quality_report_is_immutable_idempotent_and_bound_to_authoritative_lineage(
    tmp_path: Path,
) -> None:
    store, report, mission_store, work_orders, coordination = _bound_capture_quality_store(tmp_path)

    # Binding is evaluated before any final report becomes durable.
    wrong_order = store.record(
        _report(report_id="capture-quality-wrong-order", work_order_id="obs-work-00000002"),
        organization_id=_ORG,
        reported_by="edge-readiness",
        caller_device_id=_DEVICE,
        now=_NOW,
    )
    assert wrong_order.verdict is CaptureQualityReportVerdict.WORK_ORDER_MISMATCH
    wrong_device = store.record(
        _report(report_id="capture-quality-wrong-device", device_id="manifold-other-1"),
        organization_id=_ORG,
        reported_by="edge-readiness",
        caller_device_id=_DEVICE,
        now=_NOW,
    )
    assert wrong_device.verdict is CaptureQualityReportVerdict.DEVICE_MISMATCH

    first = store.record(
        report,
        organization_id=_ORG,
        reported_by="edge-readiness",
        caller_device_id=_DEVICE,
        now=_NOW,
    )
    assert first.verdict is CaptureQualityReportVerdict.RECORDED
    assert first.record is not None and first.record.cycle_number == 1
    assert (
        store.record(
            report,
            organization_id=_ORG,
            reported_by="edge-readiness",
            caller_device_id=_DEVICE,
            now=_NOW + timedelta(seconds=1),
        ).verdict
        is CaptureQualityReportVerdict.DUPLICATE
    )
    assert (
        store.record(
            report.model_copy(update={"capture_policy_id": "capture-policy-mutated"}),
            organization_id=_ORG,
            reported_by="edge-readiness",
            caller_device_id=_DEVICE,
            now=_NOW + timedelta(seconds=2),
        ).verdict
        is CaptureQualityReportVerdict.REPORT_ID_CONFLICT
    )
    assert (
        store.record(
            _report(report_id="capture-quality-second-final"),
            organization_id=_ORG,
            reported_by="edge-readiness",
            caller_device_id=_DEVICE,
            now=_NOW + timedelta(seconds=3),
        ).verdict
        is CaptureQualityReportVerdict.MISSION_ALREADY_REPORTED
    )

    store._journal.close()  # noqa: SLF001 -- journal replay is the immutability check
    replayed = CaptureQualityReportStore(
        DurableJournal(tmp_path / "capture-quality.jsonl"),
        mission_store=mission_store,
        work_order_store=work_orders,
        coordination_store=coordination,
    )
    persisted = replayed.for_mission(_MISSION, organization_id=_ORG)
    assert persisted is not None
    assert persisted.report == report
    assert persisted.cycle_number == 1


class _CoverageStore:
    def __init__(self, completion_state: str = "COMPLETED") -> None:
        self._record = SimpleNamespace(
            report=SimpleNamespace(
                summary=SimpleNamespace(completion_state=SimpleNamespace(value=completion_state))
            )
        )

    def latest_recorded(self, mission_id: str) -> SimpleNamespace:
        assert mission_id == _MISSION
        return self._record


class _QualityStore:
    def __init__(self, report: CaptureQualityReport) -> None:
        self._record = SimpleNamespace(report=report)

    def for_mission(self, mission_id: str, *, organization_id: str) -> SimpleNamespace:
        assert (mission_id, organization_id) == (_MISSION, _ORG)
        return self._record


class _SourceMediaStore:
    def __init__(self, bundle: SourceMediaBundle) -> None:
        self._bundle = bundle

    def get(self, mission_id: str) -> SourceMediaBundle:
        assert mission_id == _MISSION
        return self._bundle


class _ProcessingStore:
    def __init__(self, *, status: str, capture_window: object) -> None:
        self._jobs = [
            SimpleNamespace(
                job_id="processing-readiness-1",
                status=SimpleNamespace(value=status),
                capture_window=capture_window,
            )
        ]

    def list_for_mission(self, mission_id: str) -> list[SimpleNamespace]:
        assert mission_id == _MISSION
        return self._jobs


def _verified_bundle(*, mismatch: bool = False) -> SourceMediaBundle:
    captured_from = _NOW
    captured_to = _NOW + timedelta(seconds=300)
    media = (
        SourceMediaRecord(
            media_id="readiness-1.jpg",
            sha256="a" * 64,
            size_bytes=100,
            width=100,
            height=100,
            content_type="image/jpeg",
            object_key="sites/site-readiness/missions/mission-readiness-1/source/readiness-1.jpg",
            registered_at=_NOW,
            registered_by="edge-readiness",
            capture_time=CaptureTime(
                captured_from, CaptureTimeSource.EXIF_GPS_UTC, CaptureTimeStatus.VERIFIED
            ),
        ),
        SourceMediaRecord(
            media_id="readiness-2.jpg",
            sha256="b" * 64,
            size_bytes=100,
            width=100,
            height=100,
            content_type="image/jpeg",
            object_key="sites/site-readiness/missions/mission-readiness-1/source/readiness-2.jpg",
            registered_at=_NOW,
            registered_by="edge-readiness",
            capture_time=CaptureTime(
                captured_to, CaptureTimeSource.EXIF_GPS_UTC, CaptureTimeStatus.VERIFIED
            ),
        ),
    )
    return SourceMediaBundle(
        mission_id=_MISSION,
        site_id=_SITE,
        media=media,
        sealed_at=_NOW,
        sealed_by="edge-readiness",
        source_bundle_digest="sha256:" + "c" * 64,
        verified_at=None if mismatch else _NOW,
        verified_by=None if mismatch else "worker-readiness",
        last_mismatch_at=_NOW if mismatch else None,
    )


def _project(
    *,
    work_order: ObservationWorkOrder,
    report: CaptureQualityReport,
    bundle: SourceMediaBundle,
    processing_status: str = "SUCCEEDED",
) -> AnalysisReadinessStatus:
    projector = AnalysisReadinessProjector(
        coverage_report_store=_CoverageStore(),  # type: ignore[arg-type]
        capture_quality_report_store=_QualityStore(report),  # type: ignore[arg-type]
        source_media_store=_SourceMediaStore(bundle),  # type: ignore[arg-type]
        processing_job_store=_ProcessingStore(
            status=processing_status, capture_window=bundle.capture_window
        ),  # type: ignore[arg-type]
    )
    return projector.project(work_order, mission_id=_MISSION, now=_NOW).status


def test_analysis_readiness_requires_every_final_evidence_gate() -> None:
    policy = TemporalCoherencePolicy(max_capture_span_seconds=600)
    complete_bundle = _verified_bundle()
    ready = AnalysisReadinessProjector(
        coverage_report_store=_CoverageStore(),  # type: ignore[arg-type]
        capture_quality_report_store=_QualityStore(_report()),  # type: ignore[arg-type]
        source_media_store=_SourceMediaStore(complete_bundle),  # type: ignore[arg-type]
        processing_job_store=_ProcessingStore(
            status="SUCCEEDED", capture_window=complete_bundle.capture_window
        ),  # type: ignore[arg-type]
    ).project(_work_order(temporal_policy=policy), mission_id=_MISSION, now=_NOW)
    assert ready.status is AnalysisReadinessStatus.READY
    assert ready.ready
    assert ready.epoch.sortie_count == 1
    assert ready.epoch.temporal_policy_schema_version == "1.0"

    assert (
        _project(
            work_order=_work_order(temporal_policy=None),
            report=_report(),
            bundle=complete_bundle,
        )
        is AnalysisReadinessStatus.TEMPORAL_POLICY_UNDECLARED
    )
    assert (
        _project(
            work_order=_work_order(temporal_policy=policy),
            report=_report(status=CaptureQualityStatus.GAP),
            bundle=complete_bundle,
        )
        is AnalysisReadinessStatus.CAPTURE_QUALITY_GAP
    )
    assert (
        _project(
            work_order=_work_order(temporal_policy=policy),
            report=_report(),
            bundle=_verified_bundle(mismatch=True),
        )
        is AnalysisReadinessStatus.INTEGRITY_GAP
    )
    assert (
        _project(
            work_order=_work_order(temporal_policy=policy),
            report=_report(),
            bundle=complete_bundle,
            processing_status="FAILED",
        )
        is AnalysisReadinessStatus.PROCESSING_FAILED
    )
