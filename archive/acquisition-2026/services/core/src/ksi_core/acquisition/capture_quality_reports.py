"""Durable Edge CaptureQualityReport intake and scoped read model.

The Edge may measure blur, exposure, overlap, and recovery attempts, but it may
not mark a WorkOrder analysis-ready. This store accepts one immutable final
report for one WorkOrder cycle/Mission, binds it to the reporting Edge device,
and leaves the final readiness decision to ``AnalysisReadinessProjector``.

This enforces REQ-ACQ-102, REQ-INT-102, INV-017, and INV-060 without claiming
that an unverified DJI capability is operational.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response
from ksi_event_contracts.capture_quality import CaptureQualityReport, CaptureQualityStatus

from ksi_core.acquisition.coordination import AcquisitionCoordinationStore
from ksi_core.domains.missions.mission_records import MissionStore
from ksi_core.domains.sites.observation_work_orders import ObservationWorkOrderStore
from ksi_core.foundation.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, require_permission


class CaptureQualityReportVerdict(StrEnum):
    RECORDED = "RECORDED"
    DUPLICATE = "DUPLICATE"
    REPORT_ID_CONFLICT = "REPORT_ID_CONFLICT"
    MISSION_ALREADY_REPORTED = "MISSION_ALREADY_REPORTED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    WORK_ORDER_MISMATCH = "WORK_ORDER_MISMATCH"
    DEVICE_MISMATCH = "DEVICE_MISMATCH"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


class CaptureQualityReportStoreRecoveryError(RuntimeError):
    """The capture-quality journal cannot be replayed without guessing."""


@dataclass(frozen=True, slots=True)
class RecordedCaptureQualityReport:
    report: CaptureQualityReport
    cycle_number: int
    received_at: datetime
    received_by: str


@dataclass(frozen=True, slots=True)
class CaptureQualityReportResult:
    verdict: CaptureQualityReportVerdict
    record: RecordedCaptureQualityReport | None = None
    detail: str | None = None


def is_capture_quality_acceptable(report: CaptureQualityReport) -> bool:
    """Only final accepted/recovered measurements may support Analysis Readiness.

    ``GAP`` and ``UNRECOVERABLE`` remain visible evidence of missing capture.
    Treating a later unrelated ``RECOVERED`` measurement as permission to hide a
    gap would require a recovery lineage not present in the v1 contract, so v1
    stays conservative and fail-closed.
    """

    return all(
        measurement.status in {CaptureQualityStatus.ACCEPTED, CaptureQualityStatus.RECOVERED}
        for measurement in report.measurements
    )


def _report_payload(report: CaptureQualityReport) -> str:
    return json.dumps(
        report.model_dump(by_alias=True, mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _require_aware(value: datetime, *, field: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field}은 tz-aware여야 한다")


def _safe_identifier(value: str, *, field: str) -> None:
    if not is_path_safe_identifier(value):
        raise ValueError(f"{field}은 경로-안전 식별자여야 한다")


class CaptureQualityReportStore:
    """Append-only immutable CaptureQualityReport store scoped by organization."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        mission_store: MissionStore,
        work_order_store: ObservationWorkOrderStore,
        coordination_store: AcquisitionCoordinationStore,
    ) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._work_orders = work_order_store
        self._coordination = coordination_store
        self._lock = threading.RLock()
        self._by_report_id: dict[tuple[str, str], RecordedCaptureQualityReport] = {}
        self._by_mission: dict[tuple[str, str], RecordedCaptureQualityReport] = {}
        try:
            self._replay(journal.replay())
        except BaseException as exc:
            journal.close()
            if isinstance(exc, CaptureQualityReportStoreRecoveryError):
                raise
            raise CaptureQualityReportStoreRecoveryError(
                f"capture-quality journal 재생 실패: {exc}"
            ) from exc

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def _replay(self, records: list[dict[str, Any]]) -> None:
        for raw in records:
            try:
                if raw["kind"] != "capture-quality-report-recorded":
                    raise ValueError(f"unknown kind={raw['kind']!r}")
                report = CaptureQualityReport.model_validate(raw["report"])
                cycle_number = int(raw["cycleNumber"])
                received_at = datetime.fromisoformat(str(raw["receivedAt"]))
                received_by = str(raw["receivedBy"])
                _require_aware(received_at, field="receivedAt")
                if cycle_number < 1:
                    raise ValueError("cycleNumber must be >= 1")
                for field, value in (
                    ("organizationId", report.organization_id),
                    ("siteId", report.site_id),
                    ("workOrderId", report.work_order_id),
                    ("missionId", report.mission_id),
                    ("deviceId", report.device_id),
                    ("reportId", report.report_id),
                ):
                    _safe_identifier(value, field=field)
                record = RecordedCaptureQualityReport(
                    report=report,
                    cycle_number=cycle_number,
                    received_at=received_at,
                    received_by=received_by,
                )
                report_key = (report.organization_id, report.report_id)
                mission_key = (report.organization_id, report.mission_id)
                if report_key in self._by_report_id or mission_key in self._by_mission:
                    raise ValueError("duplicate reportId or Mission report")
                self._by_report_id[report_key] = record
                self._by_mission[mission_key] = record
            except (KeyError, TypeError, ValueError) as exc:
                raise CaptureQualityReportStoreRecoveryError(
                    f"capture-quality journal 재생 실패: {exc}"
                ) from exc

    def record(
        self,
        report: CaptureQualityReport,
        *,
        organization_id: str,
        reported_by: str,
        caller_device_id: str,
        now: datetime,
    ) -> CaptureQualityReportResult:
        """Record a final Edge report after mission/work-order/device binding checks."""

        _require_aware(now, field="now")
        for field, value in (
            ("organizationId", organization_id),
            ("report.organizationId", report.organization_id),
            ("reportId", report.report_id),
            ("siteId", report.site_id),
            ("workOrderId", report.work_order_id),
            ("missionId", report.mission_id),
            ("deviceId", report.device_id),
            ("callerDeviceId", caller_device_id),
        ):
            _safe_identifier(value, field=field)
        if report.organization_id != organization_id:
            return CaptureQualityReportResult(
                CaptureQualityReportVerdict.UNKNOWN_MISSION,
                detail="report organizationId가 인증된 조직과 일치하지 않는다",
            )
        if report.device_id != caller_device_id:
            return CaptureQualityReportResult(
                CaptureQualityReportVerdict.DEVICE_MISMATCH,
                detail="report deviceId가 인증된 Edge device와 일치하지 않는다",
            )
        with self._lock:
            if self._journal.sealed_reason is not None:
                return CaptureQualityReportResult(
                    CaptureQualityReportVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            report_key = (organization_id, report.report_id)
            existing = self._by_report_id.get(report_key)
            if existing is not None:
                if _report_payload(existing.report) == _report_payload(report):
                    return CaptureQualityReportResult(
                        CaptureQualityReportVerdict.DUPLICATE, record=existing
                    )
                return CaptureQualityReportResult(
                    CaptureQualityReportVerdict.REPORT_ID_CONFLICT,
                    detail="reportId를 다른 CaptureQualityReport에 재사용할 수 없다",
                )
            if (organization_id, report.mission_id) in self._by_mission:
                return CaptureQualityReportResult(
                    CaptureQualityReportVerdict.MISSION_ALREADY_REPORTED,
                    detail="Mission에는 변경 불가능한 최종 CaptureQualityReport 하나만 허용한다",
                )

            mission = self._mission_store.get_scoped(
                report.mission_id, organization_id=organization_id
            )
            if mission is None or mission.site_id != report.site_id:
                return CaptureQualityReportResult(
                    CaptureQualityReportVerdict.UNKNOWN_MISSION,
                    detail="조직·현장 범위에 맞는 Mission을 찾을 수 없다",
                )
            if (
                mission.assigned_device_id is not None
                and mission.assigned_device_id != caller_device_id
            ):
                return CaptureQualityReportResult(
                    CaptureQualityReportVerdict.DEVICE_MISMATCH,
                    detail="이 Mission은 다른 Edge device에 배정됐다",
                )
            work_order = self._work_orders.get(
                report.work_order_id, organization_id=organization_id
            )
            run = self._coordination.run_for_mission(
                report.mission_id, organization_id=organization_id
            )
            if (
                work_order is None
                or work_order.site_id != report.site_id
                or run is None
                or run.work_order_id != report.work_order_id
                or run.site_id != report.site_id
                or run.cycle_number != work_order.cycle_number
            ):
                return CaptureQualityReportResult(
                    CaptureQualityReportVerdict.WORK_ORDER_MISMATCH,
                    detail=(
                        "CaptureQualityReport가 현재 WorkOrder 회차/Mission binding과 "
                        "일치하지 않는다"
                    ),
                )
            record = RecordedCaptureQualityReport(
                report=report,
                cycle_number=run.cycle_number,
                received_at=now,
                received_by=reported_by,
            )
            try:
                self._journal.append(
                    {
                        "kind": "capture-quality-report-recorded",
                        "ts": iso_utc(now),
                        "report": report.model_dump(by_alias=True, mode="json"),
                        "cycleNumber": run.cycle_number,
                        "receivedAt": iso_utc(now),
                        "receivedBy": reported_by,
                    }
                )
            except JournalSealedError:
                return CaptureQualityReportResult(
                    CaptureQualityReportVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            self._by_report_id[report_key] = record
            self._by_mission[(organization_id, report.mission_id)] = record
            return CaptureQualityReportResult(CaptureQualityReportVerdict.RECORDED, record=record)

    def for_mission(
        self, mission_id: str, *, organization_id: str
    ) -> RecordedCaptureQualityReport | None:
        with self._lock:
            return self._by_mission.get((organization_id, mission_id))


class CaptureQualityReportResponse(CamelModel):
    verdict: CaptureQualityReportVerdict
    detail: str | None = None
    report: CaptureQualityReport | None = None
    cycle_number: int | None = None
    received_at: datetime | None = None
    received_by: str | None = None


_EDGE_CAPTURE_QUALITY_WRITE = require_permission(Permission.EDGE_SYNC_INGEST)


def _require_edge_device(
    principal: Principal = Depends(_EDGE_CAPTURE_QUALITY_WRITE),  # noqa: B008
) -> Principal:
    if principal.kind is not PrincipalKind.EDGE_DEVICE or principal.device_id is None:
        raise HTTPException(
            status_code=403,
            detail="Edge device 신원만 CaptureQualityReport를 기록할 수 있다",
        )
    return principal


_HTTP_STATUS = {
    CaptureQualityReportVerdict.RECORDED: 201,
    CaptureQualityReportVerdict.DUPLICATE: 200,
    CaptureQualityReportVerdict.REPORT_ID_CONFLICT: 409,
    CaptureQualityReportVerdict.MISSION_ALREADY_REPORTED: 409,
    CaptureQualityReportVerdict.UNKNOWN_MISSION: 404,
    CaptureQualityReportVerdict.WORK_ORDER_MISMATCH: 404,
    CaptureQualityReportVerdict.DEVICE_MISMATCH: 404,
    CaptureQualityReportVerdict.STORE_UNAVAILABLE: 503,
}


def _response(result: CaptureQualityReportResult) -> CaptureQualityReportResponse:
    record = result.record
    return CaptureQualityReportResponse(
        verdict=result.verdict,
        detail=result.detail,
        report=record.report if record is not None else None,
        cycle_number=record.cycle_number if record is not None else None,
        received_at=record.received_at if record is not None else None,
        received_by=record.received_by if record is not None else None,
    )


def build_capture_quality_reports_router(store: CaptureQualityReportStore) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["capture-quality"])

    @router.post(
        "/{mission_id}/capture-quality-report", response_model=CaptureQualityReportResponse
    )
    def submit_capture_quality_report(
        mission_id: str,
        report: CaptureQualityReport,
        response: Response,
        principal: Principal = Depends(_require_edge_device),  # noqa: B008
    ) -> CaptureQualityReportResponse:
        if report.mission_id != mission_id:
            raise HTTPException(
                status_code=422, detail="경로의 missionId와 본문의 missionId가 다르다"
            )
        assert principal.device_id is not None  # noqa: S101 -- dependency guarantees it
        result = store.record(
            report,
            organization_id=principal.organization_id,
            reported_by=principal.principal_id,
            caller_device_id=principal.device_id,
            now=datetime.now(UTC),
        )
        response.status_code = _HTTP_STATUS[result.verdict]
        if result.verdict is CaptureQualityReportVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return _response(result)

    @router.get("/{mission_id}/capture-quality-report", response_model=CaptureQualityReportResponse)
    def get_capture_quality_report(
        mission_id: str,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> CaptureQualityReportResponse:
        record = store.for_mission(mission_id, organization_id=principal.organization_id)
        if record is None:
            raise HTTPException(status_code=404, detail="CaptureQualityReport를 찾을 수 없다")
        return _response(CaptureQualityReportResult(CaptureQualityReportVerdict.RECORDED, record))

    return router


def mount_capture_quality_reports(app: FastAPI, store: CaptureQualityReportStore) -> None:
    app.state.capture_quality_report_store = store
    app.include_router(build_capture_quality_reports_router(store))


__all__ = [
    "CaptureQualityReportResult",
    "CaptureQualityReportStore",
    "CaptureQualityReportStoreRecoveryError",
    "CaptureQualityReportVerdict",
    "RecordedCaptureQualityReport",
    "build_capture_quality_reports_router",
    "is_capture_quality_acceptable",
    "mount_capture_quality_reports",
]
