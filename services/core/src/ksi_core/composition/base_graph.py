"""Base durable Core graph: sites, missions, storage, and work areas."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ksi_core.checkpoint_validations import CheckpointValidationStore
from ksi_core.coverage_reports import CoverageReportStore
from ksi_core.design_surfaces import DesignSurfaceStore
from ksi_core.edge_dispatch import (
    EdgeDispatchStore,
    EdgeRuntimeProfileRegistry,
    RiskPolicyPackRegistry,
)
from ksi_core.edge_sync import EdgeSyncStore
from ksi_core.flight_artifacts import FlightArtifactStore
from ksi_core.mission_execution import MissionExecutionStore
from ksi_core.mission_records import MissionIssuanceSequenceStore, MissionStore
from ksi_core.processing_jobs import ProcessingJobStore
from ksi_core.sites import SiteStore
from ksi_core.source_media import SourceMediaStore
from ksi_core.work_areas import WorkAreaStore


@dataclass(frozen=True)
class BaseGraph:
    """Exact base graph instances reused by all subsequent composition groups."""

    mission_store: Any
    mission_sequence_store: Any
    event_journal: Any
    edge_sync_store: Any
    flight_artifact_store: Any
    mission_execution_store: Any
    edge_dispatch_store: Any
    coverage_report_store: Any
    source_media_store: Any
    site_store: Any
    processing_job_store: Any
    checkpoint_validation_store: Any
    design_surface_store: Any
    work_area_store: Any
    defect_candidate_journal: Any
    change_detection_journal: Any
    volume_change_journal: Any
    comparison_request_journal: Any


def build_base_graph(
    *,
    data_dir: Path,
    journal: Callable[[str], Any],
    opened: list[Any],
    edge_sync_snapshot_every: int | None,
    evidence_storage: Any,
    mission_signing_key: Any,
    mission_signing_key_id: str,
    risk_policy_packs: tuple[dict[str, Any], ...],
    edge_runtime_profiles: tuple[dict[str, Any], ...],
    processing_profile_issuance_enabled: bool,
    coordinator: Any,
) -> BaseGraph:
    # 세그먼트 회전(S4) — 활성 파일이 이 크기를 넘으면 봉인 세그먼트로 넘긴다.
    # 회전 임계는 **조립 지점의 결정**이다(DurableJournal 기본값은 회전 없음) —
    # 한 파일이 무한히 커지면 재기동 재생이 선형으로 느려지고 백업 단위도 사라진다.
    site_journal = journal("sites.jsonl")
    mission_journal = journal("missions.jsonl")
    mission_sequence_journal = journal("mission-sequences.jsonl")
    event_journal = journal("events.jsonl")
    # edge-sync 는 회전이 아니라 스냅샷으로 재기동 비용을 잡는다 — 이 원장의
    # 재기동 비용은 파일 크기가 아니라 항목당 payload 정규화+sha256 이기 때문이다.
    edge_sync_store = EdgeSyncStore(
        data_dir / "edge-sync.jsonl",
        snapshot_every=edge_sync_snapshot_every,
    )
    opened.append(edge_sync_store)

    mission_store = MissionStore(mission_journal)
    mission_sequence_store = MissionIssuanceSequenceStore(mission_sequence_journal)
    # Pilot export는 발급 산출물/실행 경로에 편입하지 않는 별도 후보 원장이다.
    # exact-byte 보관소가 없는 축소 조립에서는 원장도 열지 않아 "후보가 있지만
    # 바이트는 없다"는 거짓 표면을 만들지 않는다.
    flight_artifact_store = (
        FlightArtifactStore(
            journal("flight-artifacts.jsonl"),
            mission_store=mission_store,
            storage=evidence_storage,
        )
        if evidence_storage is not None
        else None
    )
    # 임무 실행 생애주기(ADR-KSI-019 G2) — 발급 원장과 별도 원장이다. 발급 시점에
    # 이 원장에 쓰지 않으므로(레코드 부재 = ISSUED) 발급 경로의 201 계약을 건드리지
    # 않는다.
    mission_execution_store = MissionExecutionStore(
        journal("mission-execution.jsonl"), mission_store=mission_store
    )
    # Edge dispatch는 별도 journal에 envelope/activation receipt를 남긴다. policy
    # pack이 비어 있으면 endpoint는 204만 반환한다 — 임의 default pack으로 장비를
    # dispatch하지 않는 fail-closed 기본값이다.
    edge_dispatch_store = EdgeDispatchStore(
        journal("edge-dispatch.jsonl"),
        mission_store=mission_store,
        risk_policy_packs=RiskPolicyPackRegistry(risk_policy_packs),
        edge_runtime_profiles=EdgeRuntimeProfileRegistry(edge_runtime_profiles),
        private_key=mission_signing_key,
        key_id=mission_signing_key_id,
    )
    # 커버리지 보고는 임무 발급 기록과 대조해서만 받는다(INV-010) — 발급된 적
    # 없는 임무의 관찰 결과는 "무슨 근거로 날았나"에 답할 수 없다.
    coverage_journal = journal("coverage-reports.jsonl")
    coverage_report_store = CoverageReportStore(coverage_journal, mission_store=mission_store)
    # 원본 사진 번들(3D 파이프라인 입구) — evidence_storage 없이는 store 는 구성돼도
    # 라우트가 장착되지 않는다(evidence 라우트와 같은 관습, create_app 참조).
    source_media_journal = journal("source-media.jsonl")
    source_media_store = SourceMediaStore(source_media_journal, mission_store=mission_store)
    site_store = SiteStore(site_journal, coordinator=coordinator)
    # 처리 작업(ADR-KSI-012) — 봉인된 번들에서 입력을, 현장에서 반출 허용 여부를
    # 읽는다(INV-050). source_media 와 달리 오브젝트 스토리지를 요구하지 않는다.
    processing_job_journal = journal("processing-jobs.jsonl")
    # evidence_storage 없이 이 저장소를 넘기면 create_app 이 조립 자체를 거부한다
    # (ADR-KSI-012/INV-050 — 워커가 원본 바이트를 받아갈 URL 이 없으면 SUCCEEDED
    # 게이트가 영구히 닫힌 조립이 된다). 스토리지가 없으면 이 표면을 장착하지
    # 않는 편이 정직하다 — source_media 라우트가 같은 이유로 이미 그렇게 동작한다.
    processing_job_store = (
        ProcessingJobStore(
            processing_job_journal,
            source_media_store=source_media_store,
            site_store=site_store,
            processing_profile_issuance_enabled=processing_profile_issuance_enabled,
        )
        if evidence_storage is not None
        else None
    )
    # 독립 checkpoint 정확도 검증은 사용자가 제출한 RMSE를 받지 않는다. sealed CSV와
    # immutable DSM을 worker가 실제로 읽어 측정하므로, 두 사실 원장과 evidence storage가
    # 동시에 있는 조립에서만 만든다(INV-024/053).
    checkpoint_validation_store = (
        CheckpointValidationStore(
            journal("checkpoint-validations.jsonl"),
            processing_jobs=processing_job_store,
            mission_store=mission_store,
        )
        if processing_job_store is not None and evidence_storage is not None
        else None
    )
    # Phase 3/4 + M1 표면 — 이 다섯을 여기서 조립하지 않으면 create_app 배선이 정확해도
    # **띄울 수 있는 서버에서는 404 다**(2026-08-08 reviewer 지적 F1: 신설 API 4종이
    # 어떤 실행 가능한 조립에도 장착돼 있지 않았다). 라이브러리를 API 로 만든 작업이
    # 다시 "아무도 못 쓰는 것"이 되는 자리라, 배선과 조립을 같은 커밋에서 닫는다.
    # 설계 기준면(M4-A) — 현장에 매달린 자산이라 site_store 와 함께 조립한다.
    # evidence_storage 가 없으면 store 는 구성되지만 라우트가 장착되지 않는다
    # (create_app 참조) — source_media 와 같은 관습.
    design_surface_journal = journal("design-surfaces.jsonl")
    design_surface_store = DesignSurfaceStore(design_surface_journal, site_store=site_store)
    defect_candidate_journal = journal("defect-candidates.jsonl")
    change_detection_journal = journal("change-detection.jsonl")
    volume_change_journal = journal("volume-changes.jsonl")
    comparison_request_journal = journal("comparison-requests.jsonl")
    # M4-A 설계 대비 잔량 — 요청(지시)과 리포트(결과)를 두 원장으로 나눈다.
    # 리포트 원장은 요청 원장과 오브젝트 스토리지를 **둘 다** 필요로 한다: 리포트를
    # 받는 순간 차분 래스터 바이트를 직접 재해싱해 워커의 신고와 대조하기 때문이다
    # (design_conformance_reports.py 모듈 docstring). 그래서 두 store 는 재구성
    # 작업 원장·스토리지가 있는 조립에서만 만들어진다.
    # 작업구역(M4-C) — 현장에 매달린 자산이라 site_store 와 함께 조립한다.
    # 설계 대비 요청이 이 저장소에서 폴리곤을 **값으로** 복사해 가므로,
    # 요청 저장소보다 먼저 만들어져야 한다.
    work_area_journal = journal("work-areas.jsonl")
    work_area_store = WorkAreaStore(
        work_area_journal,
        site_exists=lambda site_id: site_store.get(site_id) is not None,
        coordinator=coordinator,
    )
    return BaseGraph(
        mission_store=mission_store,
        mission_sequence_store=mission_sequence_store,
        event_journal=event_journal,
        edge_sync_store=edge_sync_store,
        flight_artifact_store=flight_artifact_store,
        mission_execution_store=mission_execution_store,
        edge_dispatch_store=edge_dispatch_store,
        coverage_report_store=coverage_report_store,
        source_media_store=source_media_store,
        site_store=site_store,
        processing_job_store=processing_job_store,
        checkpoint_validation_store=checkpoint_validation_store,
        design_surface_store=design_surface_store,
        work_area_store=work_area_store,
        defect_candidate_journal=defect_candidate_journal,
        change_detection_journal=change_detection_journal,
        volume_change_journal=volume_change_journal,
        comparison_request_journal=comparison_request_journal,
    )
