"""Operational, acquisition, workspace, and edge route mounting."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def mount_operations_routes(
    app: FastAPI,
    *,
    acquisition_connectivity_store: Any,
    acquisition_coordination_store: Any,
    observation_work_order_store: Any,
    mission_store: Any,
    coverage_report_store: Any,
    capture_quality_report_store: Any,
    source_media_store: Any,
    processing_job_store: Any,
    mission_execution_store: Any,
    copilot_service: Any,
    copilot_conversation_service: Any,
    site_workspace_projector: Any,
    site_briefing_service: Any,
    site_briefing_store: Any,
    civil_readiness_projector: Any,
    site_store: Any,
    edge_sync_store: Any,
    event_store: Any,
    edge_dispatch_store: Any,
    evidence_storage: Any,
    device_attestation_registry: Any,
) -> Any:
    if acquisition_connectivity_store is not None:
        from ksi_core.acquisition import mount_acquisition_connectivity

        mount_acquisition_connectivity(app, acquisition_connectivity_store)

    if acquisition_coordination_store is not None:
        from ksi_core.acquisition import (
            AcquisitionProgressProjector,
            AnalysisReadinessProjector,
            mount_acquisition_coordination,
        )

        assert acquisition_connectivity_store is not None  # noqa: S101 -- assembly table
        assert observation_work_order_store is not None  # noqa: S101 -- assembly table
        assert mission_store is not None  # noqa: S101 -- assembly table
        analysis_readiness_projector = None
        if (
            coverage_report_store is not None
            and capture_quality_report_store is not None
            and source_media_store is not None
            and processing_job_store is not None
        ):
            analysis_readiness_projector = AnalysisReadinessProjector(
                coverage_report_store=coverage_report_store,
                capture_quality_report_store=capture_quality_report_store,
                source_media_store=source_media_store,
                processing_job_store=processing_job_store,
            )
        mount_acquisition_coordination(
            app,
            coordination_store=acquisition_coordination_store,
            connectivity_store=acquisition_connectivity_store,
            work_order_store=observation_work_order_store,
            mission_store=mission_store,
            projector=AcquisitionProgressProjector(
                coordination_store=acquisition_coordination_store,
                connectivity_store=acquisition_connectivity_store,
                mission_execution_store=mission_execution_store,
                source_media_store=source_media_store,
                processing_job_store=processing_job_store,
                analysis_readiness_projector=analysis_readiness_projector,
            ),
        )

    if capture_quality_report_store is not None:
        from ksi_core.capture_quality_reports import mount_capture_quality_reports

        mount_capture_quality_reports(app, capture_quality_report_store)

    if copilot_service is not None:
        from ksi_core.copilot import mount_copilot

        mount_copilot(app, copilot_service)

    if copilot_conversation_service is not None:
        from ksi_core.copilot_conversations import mount_copilot_conversations

        mount_copilot_conversations(app, copilot_conversation_service)

    if site_workspace_projector is not None:
        from ksi_core.site_workspace import mount_site_workspace

        mount_site_workspace(
            app,
            projector=site_workspace_projector,
            briefing_service=site_briefing_service,
            briefing_store=site_briefing_store,
        )

    if civil_readiness_projector is not None:
        from ksi_core.civil_readiness import mount_civil_readiness

        mount_civil_readiness(app, civil_readiness_projector)

    # 현장 상태 자동 전진(ADR-KSI-019 G1) — 재구성 신호·임무 배포·노후 스윕 세
    # 진입점이 같은 인스턴스를 공유한다. 두 저장소 중 하나라도 없으면 전진시킬
    # 대상이 없으므로 None 이고, 그때는 예전과 같이 아무것도 전진시키지 않는다
    # (자동화가 없는 조립도 유효한 조립이다).
    site_lifecycle = None
    if site_store is not None:
        from ksi_core.spatial_model import SpatialModelLifecycle

        # processing_job_store 는 노후 스윕에만 필요하다 — 없어도 임무 배포·재구성
        # 신호 전진은 성립한다(그 조립에는 재구성 신호 자체가 없다).
        site_lifecycle = SpatialModelLifecycle(
            site_store=site_store, processing_job_store=processing_job_store
        )

    if edge_sync_store is not None:
        from ksi_core.edge_sync import mount_edge_sync

        # event_store 는 위에서 함께 주어졌음을 확인했다(None 이 아니다).
        assert event_store is not None  # noqa: S101 -- 위 결합 검증이 보장
        mount_edge_sync(app, edge_sync_store, event_store=event_store)

    if edge_dispatch_store is not None:
        from ksi_core.edge_dispatch import mount_edge_dispatch

        mount_edge_dispatch(
            app,
            edge_dispatch_store,
            event_store=event_store,
            evidence_storage=evidence_storage,
            # 장비의 임무 pull·activation 이 실행 상태를 옮긴다(ADR-KSI-019 G2).
            mission_execution_store=mission_execution_store,
            site_lifecycle=site_lifecycle,
            device_attestation_registry=device_attestation_registry,
        )

    return site_lifecycle
