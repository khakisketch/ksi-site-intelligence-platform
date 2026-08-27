"""Derived ObservationEpoch and Analysis Readiness projection.

This module deliberately does not invent an ``IN_FLIGHT`` state and does not
mutate a WorkOrder. It joins already-authoritative facts: CoverageReport,
CaptureQualityReport, verified SourceMedia, capture window, and ProcessingJob.
The result is an additive read model for REQ-INT-102/103 and INV-017/018.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING

from ksi_event_contracts.observation_work_order import ObservationWorkOrder

from ksi_core.acquisition.models import (
    AnalysisReadinessStatus,
    AnalysisReadinessView,
    ObservationEpochView,
)

if TYPE_CHECKING:
    from ksi_core.capture_quality_reports import CaptureQualityReportStore
    from ksi_core.coverage_reports import CoverageReportStore
    from ksi_core.processing_jobs import ProcessingJobStore
    from ksi_core.source_media import SourceMediaStore


def observation_epoch_id(work_order: ObservationWorkOrder) -> str:
    """A deterministic v1 epoch identity; no mutable Epoch journal is introduced."""

    raw = (
        f"{work_order.organization_id}\0{work_order.work_order_id}\0{work_order.cycle_number}"
    ).encode()
    return f"obs-epoch-{hashlib.sha256(raw).hexdigest()[:24]}"


class AnalysisReadinessProjector:
    """Fail-closed readiness projection from final evidence sources only."""

    def __init__(
        self,
        *,
        coverage_report_store: CoverageReportStore,
        capture_quality_report_store: CaptureQualityReportStore,
        source_media_store: SourceMediaStore,
        processing_job_store: ProcessingJobStore,
    ) -> None:
        self._coverage = coverage_report_store
        self._capture_quality = capture_quality_report_store
        self._source_media = source_media_store
        self._processing = processing_job_store

    @staticmethod
    def not_assembled(
        work_order: ObservationWorkOrder, *, mission_id: str | None, now: datetime
    ) -> AnalysisReadinessView:
        return AnalysisReadinessProjector._view(
            work_order,
            mission_id=mission_id,
            status=AnalysisReadinessStatus.EVIDENCE_NOT_ASSEMBLED,
            detail="Analysis Readiness 증거 projection이 이 Core 조립에 장착되지 않았습니다.",
            evidence_refs=(),
            now=now,
        )

    def project(
        self,
        work_order: ObservationWorkOrder,
        *,
        mission_id: str | None,
        now: datetime,
    ) -> AnalysisReadinessView:
        if mission_id is None:
            return self._view(
                work_order,
                mission_id=None,
                status=AnalysisReadinessStatus.WAITING_MISSION,
                detail="이 WorkOrder 회차에 연결된 Mission이 아직 없습니다.",
                evidence_refs=(),
                now=now,
            )

        coverage = self._coverage.latest_recorded(mission_id)
        if coverage is None:
            return self._view(
                work_order,
                mission_id=mission_id,
                status=AnalysisReadinessStatus.WAITING_COVERAGE,
                detail=(
                    "CoverageReport가 아직 접수되지 않았습니다. "
                    "경로 완료만으로 분석 준비를 주장하지 않습니다."
                ),
                evidence_refs=(),
                now=now,
            )
        coverage_ref = f"coverage-report:{mission_id}"
        if coverage.report.summary.completion_state.value != "COMPLETED":
            return self._view(
                work_order,
                mission_id=mission_id,
                status=AnalysisReadinessStatus.COVERAGE_GAP,
                detail="CoverageReport가 완료 기준을 충족하지 않았습니다.",
                evidence_refs=(coverage_ref,),
                now=now,
            )

        quality = self._capture_quality.for_mission(
            mission_id, organization_id=work_order.organization_id
        )
        if quality is None:
            return self._view(
                work_order,
                mission_id=mission_id,
                status=AnalysisReadinessStatus.WAITING_CAPTURE_QUALITY,
                detail="CaptureQualityReport가 아직 접수되지 않았습니다.",
                evidence_refs=(coverage_ref,),
                now=now,
            )
        quality_ref = f"capture-quality:{quality.report.report_id}"
        from ksi_core.capture_quality_reports import is_capture_quality_acceptable

        if not is_capture_quality_acceptable(quality.report):
            return self._view(
                work_order,
                mission_id=mission_id,
                status=AnalysisReadinessStatus.CAPTURE_QUALITY_GAP,
                detail="CaptureQualityReport에 해소되지 않은 촬영 품질 공백이 있습니다.",
                evidence_refs=(coverage_ref, quality_ref),
                now=now,
            )

        bundle = self._source_media.get(mission_id)
        if bundle is None or not bundle.is_sealed:
            return self._view(
                work_order,
                mission_id=mission_id,
                status=AnalysisReadinessStatus.WAITING_MEDIA,
                detail="원본 미디어 번들이 아직 봉인되지 않았습니다.",
                evidence_refs=(coverage_ref, quality_ref),
                now=now,
            )
        media_ref = f"source-media:{mission_id}:{bundle.source_bundle_digest or 'unsealed'}"
        if not bundle.is_verified:
            if bundle.last_mismatch_at is not None:
                return self._view(
                    work_order,
                    mission_id=mission_id,
                    status=AnalysisReadinessStatus.INTEGRITY_GAP,
                    detail=(
                        "원본 미디어 실측값이 신고값과 일치하지 않아 "
                        "무결성 검증이 실패했습니다."
                    ),
                    evidence_refs=(coverage_ref, quality_ref, media_ref),
                    now=now,
                )
            return self._view(
                work_order,
                mission_id=mission_id,
                status=AnalysisReadinessStatus.WAITING_MEDIA,
                detail="원본 미디어 번들이 봉인됐지만 아직 바이트 실측 검증을 통과하지 않았습니다.",
                evidence_refs=(coverage_ref, quality_ref, media_ref),
                now=now,
            )

        window = bundle.capture_window
        if window.status.value != "COMPLETE":
            return self._view(
                work_order,
                mission_id=mission_id,
                status=AnalysisReadinessStatus.CAPTURE_TIME_INCOMPLETE,
                detail="원본의 capture-time window가 완전하고 일관되게 확인되지 않았습니다.",
                evidence_refs=(coverage_ref, quality_ref, media_ref),
                now=now,
                capture_window_status=window.status.value,
                captured_from=window.captured_from,
                captured_to=window.captured_to,
            )

        policy = work_order.temporal_policy
        if policy is None:
            return self._view(
                work_order,
                mission_id=mission_id,
                status=AnalysisReadinessStatus.TEMPORAL_POLICY_UNDECLARED,
                detail=(
                    "WorkOrder에 Observation Epoch의 최대 촬영 시간 범위 정책이 "
                    "선언되지 않았습니다."
                ),
                evidence_refs=(coverage_ref, quality_ref, media_ref),
                now=now,
                capture_window_status=window.status.value,
                captured_from=window.captured_from,
                captured_to=window.captured_to,
            )
        assert window.captured_from is not None and window.captured_to is not None  # noqa: S101
        span_seconds = (window.captured_to - window.captured_from).total_seconds()
        if span_seconds > policy.max_capture_span_seconds:
            return self._view(
                work_order,
                mission_id=mission_id,
                status=AnalysisReadinessStatus.TEMPORAL_COHERENCE_GAP,
                detail=(
                    "원본 촬영 시간 범위가 WorkOrder temporal policy를 초과했습니다 "
                    f"({span_seconds:.0f}s > {policy.max_capture_span_seconds}s)."
                ),
                evidence_refs=(coverage_ref, quality_ref, media_ref),
                now=now,
                capture_window_status=window.status.value,
                captured_from=window.captured_from,
                captured_to=window.captured_to,
            )

        jobs = self._processing.list_for_mission(mission_id)
        if not jobs:
            return self._view(
                work_order,
                mission_id=mission_id,
                status=AnalysisReadinessStatus.WAITING_PROCESSING,
                detail="검증된 원본을 처리할 ProcessingJob이 아직 발행되지 않았습니다.",
                evidence_refs=(coverage_ref, quality_ref, media_ref),
                now=now,
                capture_window_status=window.status.value,
                captured_from=window.captured_from,
                captured_to=window.captured_to,
            )
        job = jobs[-1]
        job_ref = f"processing-job:{job.job_id}"
        if job.status.value in {"FAILED", "CANCELLED"}:
            return self._view(
                work_order,
                mission_id=mission_id,
                status=AnalysisReadinessStatus.PROCESSING_FAILED,
                detail="가장 최근 ProcessingJob이 성공하지 못했습니다.",
                evidence_refs=(coverage_ref, quality_ref, media_ref, job_ref),
                now=now,
                capture_window_status=window.status.value,
                captured_from=window.captured_from,
                captured_to=window.captured_to,
            )
        if job.status.value != "SUCCEEDED":
            return self._view(
                work_order,
                mission_id=mission_id,
                status=AnalysisReadinessStatus.WAITING_PROCESSING,
                detail="ProcessingJob이 아직 성공 상태가 아닙니다.",
                evidence_refs=(coverage_ref, quality_ref, media_ref, job_ref),
                now=now,
                capture_window_status=window.status.value,
                captured_from=window.captured_from,
                captured_to=window.captured_to,
            )
        if job.capture_window != window:
            return self._view(
                work_order,
                mission_id=mission_id,
                status=AnalysisReadinessStatus.INTEGRITY_GAP,
                detail=(
                    "성공한 ProcessingJob의 고정 capture-time window가 "
                    "원본 번들과 일치하지 않습니다."
                ),
                evidence_refs=(coverage_ref, quality_ref, media_ref, job_ref),
                now=now,
                capture_window_status=window.status.value,
                captured_from=window.captured_from,
                captured_to=window.captured_to,
            )
        return self._view(
            work_order,
            mission_id=mission_id,
            status=AnalysisReadinessStatus.READY,
            detail=(
                "Coverage, 촬영 품질, 원본 무결성, capture-time, temporal policy, "
                "처리 근거가 모두 확인됐습니다."
            ),
            evidence_refs=(coverage_ref, quality_ref, media_ref, job_ref),
            now=now,
            capture_window_status=window.status.value,
            captured_from=window.captured_from,
            captured_to=window.captured_to,
        )

    @staticmethod
    def _view(
        work_order: ObservationWorkOrder,
        *,
        mission_id: str | None,
        status: AnalysisReadinessStatus,
        detail: str,
        evidence_refs: tuple[str, ...],
        now: datetime,
        capture_window_status: str = "INCOMPLETE",
        captured_from: datetime | None = None,
        captured_to: datetime | None = None,
    ) -> AnalysisReadinessView:
        policy = work_order.temporal_policy
        return AnalysisReadinessView(
            status=status,
            ready=status is AnalysisReadinessStatus.READY,
            detail=detail,
            epoch=ObservationEpochView(
                epoch_id=observation_epoch_id(work_order),
                work_order_id=work_order.work_order_id,
                cycle_number=work_order.cycle_number,
                mission_id=mission_id,
                max_capture_span_seconds=(
                    policy.max_capture_span_seconds if policy is not None else None
                ),
                temporal_policy_schema_version=(
                    policy.schema_version if policy is not None else None
                ),
                capture_window_status=capture_window_status,
                captured_from=captured_from,
                captured_to=captured_to,
            ),
            evidence_refs=evidence_refs,
            evaluated_at=now,
        )


__all__ = ["AnalysisReadinessProjector", "observation_epoch_id"]
