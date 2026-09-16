"""Design, report, region-extraction, and comparison graph composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ksi_core.comparison_requests import ComparisonRequestStore
from ksi_core.design_conformance_reports import DesignConformanceStore
from ksi_core.design_conformance_requests import DesignConformanceRequestStore
from ksi_core.region_extraction_reports import RegionExtractionStore
from ksi_core.region_extraction_requests import RegionExtractionRequestStore
from ksi_core.report_exports import ReportExportStore


@dataclass(frozen=True)
class AnalysisGraph:
    """Stores whose construction order establishes their backward bindings."""

    design_conformance_request_store: Any
    design_conformance_report_store: Any
    report_export_store: Any
    region_extraction_request_store: Any
    region_extraction_report_store: Any
    comparison_request_store: Any


def build_analysis_graph(
    *,
    journal: Callable[[str], Any],
    site_store: Any,
    mission_store: Any,
    processing_job_store: Any,
    design_surface_store: Any,
    work_area_store: Any,
    evidence_storage: Any,
    analysis_readiness_check: Any,
    coverage_report_store: Any,
    checkpoint_validation_store: Any,
    comparison_request_journal: Any,
) -> AnalysisGraph:
    design_conformance_request_journal = journal("design-conformance-requests.jsonl")
    design_conformance_report_journal = journal("design-conformance.jsonl")
    design_conformance_request_store = (
        DesignConformanceRequestStore(
            design_conformance_request_journal,
            mission_store=mission_store,
            processing_job_store=processing_job_store,
            design_surface_store=design_surface_store,
            work_area_store=work_area_store,
            analysis_readiness=analysis_readiness_check,
        )
        if processing_job_store is not None and evidence_storage is not None
        else None
    )
    design_conformance_report_store = (
        DesignConformanceStore(
            design_conformance_report_journal,
            mission_store=mission_store,
            processing_job_store=processing_job_store,
            request_store=design_conformance_request_store,
            storage=evidence_storage,
        )
        if design_conformance_request_store is not None
        and processing_job_store is not None
        and evidence_storage is not None
        else None
    )
    # Browser PDF/CSV bytes remain local to the Console.  Core records only the
    # organization/site-scoped, re-verified report identity used for that export.
    report_export_store = (
        ReportExportStore(
            journal("report-exports.jsonl"),
            site_store=site_store,
            design_conformance_store=design_conformance_report_store,
            coverage_report_store=coverage_report_store,
        )
        if design_conformance_report_store is not None
        else None
    )
    # 리포트 원장은 요청 원장을 **참조해서** 만들어지므로(request_store=...) 반대
    # 방향을 생성자 인자로 넣으면 순환이다. 그래서 조립이 끝난 뒤 술어 하나만
    # 뒤로 걸어준다 — 이게 없으면 요청 원장의 두 게이트(리포트 없는 SUCCEEDED ·
    # 리포트 기록 후 래스터 재작성)가 조용히 열린 채로 뜬다.
    if design_conformance_request_store is not None and design_conformance_report_store is not None:
        design_conformance_request_store.bind_report_existence(
            design_conformance_report_store.has_report_for
        )
    # 변화 영역 자동 추출(M4-E) — 설계 대비 잔량 리포트가 이미 기록된 뒤에만
    # 만들 수 있는 후속 요청이라, design_conformance_report_store 조립 직후 둔다.
    # 두 store 모두 evidence_storage 를 직접 쓰지 않는다(요청 store 는 diffRaster
    # 를 design_conformance_report_store 경유로 읽고, 리포트 store 는 바이트
    # 재해싱이 없다 — 모듈 docstring) — 그래도 design_conformance_report_store
    # 자체가 evidence_storage 없이는 조립되지 않으므로 조건은 그대로 물려받는다.
    region_extraction_request_journal = journal("region-extraction-requests.jsonl")
    region_extraction_report_journal = journal("region-extraction.jsonl")
    region_extraction_request_store = (
        RegionExtractionRequestStore(
            region_extraction_request_journal,
            mission_store=mission_store,
            design_conformance_report_store=design_conformance_report_store,
        )
        if design_conformance_report_store is not None
        else None
    )
    region_extraction_report_store = (
        RegionExtractionStore(
            region_extraction_report_journal,
            mission_store=mission_store,
            request_store=region_extraction_request_store,
            design_conformance_report_store=design_conformance_report_store,
        )
        if region_extraction_request_store is not None
        and design_conformance_report_store is not None
        else None
    )
    # W2 비교 요청은 KSI가 검증한 checkpoint RMSE를 우선 사용한다. 과거 artifact
    # producer-claim fallback은 ComparisonRequestStore 안에만 남긴다.
    comparison_request_store = (
        ComparisonRequestStore(
            comparison_request_journal,
            mission_store=mission_store,
            processing_job_store=processing_job_store,
            analysis_readiness=analysis_readiness_check,
            checkpoint_rmse_lookup=checkpoint_validation_store.validated_rmse_for,
        )
        if processing_job_store is not None
        and evidence_storage is not None
        and checkpoint_validation_store is not None
        else None
    )
    return AnalysisGraph(
        design_conformance_request_store=design_conformance_request_store,
        design_conformance_report_store=design_conformance_report_store,
        report_export_store=report_export_store,
        region_extraction_request_store=region_extraction_request_store,
        region_extraction_report_store=region_extraction_report_store,
        comparison_request_store=comparison_request_store,
    )
