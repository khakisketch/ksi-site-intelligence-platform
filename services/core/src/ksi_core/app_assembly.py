"""KSI Core 조립 공용부 — dev/production 두 조립 지점이 공유하는 단 하나의 배선.

``scripts/run_core_dev.py`` 가 오래도록 저장소의 **유일한** 실행 가능 조립
지점이었다(그 스크립트 자체 docstring이 "프로덕션 조립이 아니다"라고 명시).
프로덕션 조립을 새로 만들면서 그 배선을 복제하면, 조립 로직이 두 곳으로
갈라져 한쪽만 고치고 다른 쪽을 잊는 사고가 반복된다 — 이 파일은 "store 를
어떻게 엮어 ``create_app`` 을 부르는가"를 한 곳에만 두기 위해 dev 조립의
본문을 그대로 옮긴 것이다(store 배선 자체는 로직 변경 없이 옮겼다).

단, ``/ready``·``/metrics`` 라우트와 correlation-id·metrics 미들웨어(아래)는
이 파일이 **새로** 추가한 것이다 — dev 조립에 원래 없었다(``git diff`` 로 확인:
옛 ``_build_dev_app_locked`` 는 ``create_app`` 호출로 곧장 끝났다). 그래서
"순수 추출"은 store 배선에 한정된 말이고, dev 서버 동작 자체는 이 라우트들
만큼 바뀌었다 — dev·production 양쪽에 동시에. 둘 다 의도적으로 무인증이다
(``/ready`` 는 오케스트레이터 헬스체크가, ``/metrics`` 는 Prometheus
스크레이퍼가 인증 헤더를 안 보내는 것이 표준 배치다) — 다만
``tests/contract/test_api_contract_sync.py`` 의 "무인증 표면 allowlist" 게이트는
``create_app`` 을 직접 불러 조립하므로 이 파일이 얹는 라우트를 구조적으로 보지
못한다; 그 게이트는 이 파일이 만든 조립도 따로 훑도록 확장돼 있다(같은 파일의
관련 테스트 참조).

``cli_optional_positive`` 도 여기 둔다 — "0 = 없음, 음수 = 거부"라는 CLI→생성자
변환 규약이 dev 전용이 아니라 production.py 의 환경변수 파싱에도 그대로
필요하기 때문이다(둘 다 같은 :class:`DurableJournal`/``EdgeSyncStore`` 생성자
계약을 상대한다).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from ksi_event_contracts.work_area import WorkAreaStatus

from ksi_core.acquisition import AcquisitionConnectivityStore, AcquisitionCoordinationStore
from ksi_core.app import create_app
from ksi_core.auth import HumanAuthMode, Principal, PrincipalKind, Role
from ksi_core.change_detection import ChangeDetectionStore
from ksi_core.comparison_requests import ComparisonRequestStore
from ksi_core.coverage_reports import CoverageReportStore
from ksi_core.defect_candidates import DefectCandidateStore
from ksi_core.design_conformance_reports import DesignConformanceStore
from ksi_core.design_conformance_requests import DesignConformanceRequestStore
from ksi_core.design_surfaces import DesignSurfaceStore
from ksi_core.durable_journal import DurableJournal
from ksi_core.edge_dispatch import (
    EdgeDispatchStore,
    EdgeRuntimeProfileRegistry,
    RiskPolicyPackRegistry,
)
from ksi_core.edge_sync import EdgeSyncStore
from ksi_core.equipment_states import EquipmentStateStore
from ksi_core.equipment_support import EquipmentSupportStore
from ksi_core.events import EventStore
from ksi_core.metrics import HttpMetricsMiddleware, render_prometheus_text
from ksi_core.mission_execution import MissionExecutionStore
from ksi_core.mission_records import MissionIssuanceSequenceStore, MissionStore
from ksi_core.observability import CorrelationIdMiddleware
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.processing_jobs import ProcessingJobStore
from ksi_core.region_extraction_reports import RegionExtractionStore
from ksi_core.region_extraction_requests import RegionExtractionRequestStore
from ksi_core.sites import SiteStore
from ksi_core.source_media import SourceMediaStore
from ksi_core.volume_reports import VolumeChangeStore
from ksi_core.work_areas import WorkAreaStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from ksi_core.auth import AuthRegistry, OidcVerifier
    from ksi_core.copilot_openai import CopilotRuntimeConfig
    from ksi_core.device_attestation import DeviceAttestationRegistry
    from ksi_core.evidence import EvidenceStorage


def cli_optional_positive(value: int, *, name: str) -> int | None:
    """CLI 의 "0 = 없음" 규약을 생성자의 ``None`` 으로 옮긴다.

    생성자들은 0·음수를 거부하고 "없음"은 ``None`` 으로만 표현한다(조용히
    0 으로 뭉개지 않기 위해서다). CLI 쪽에서 0 을 그 뜻으로 받는 규약은 여기
    한 곳에만 둔다 — dev·production 두 조립 지점이 공유한다.

    음수는 argparse/환경변수를 통과하므로 여기서 typed 로 막는다 — 생성자까지
    흘려보내면 실패 메시지가 인자 이름을 잃는다.
    """
    if value < 0:
        raise ValueError(f"{name} 는 0(없음) 이거나 양수여야 한다: {value}")
    return value or None


def assemble_app(
    data_dir: Path,
    *,
    journal: Callable[[str], DurableJournal],
    opened: list[Any],
    edge_sync_snapshot_every: int | None,
    auth_registry: AuthRegistry,
    human_auth_mode: HumanAuthMode = HumanAuthMode.OPAQUE,
    oidc_verifier: OidcVerifier | None = None,
    evidence_storage: EvidenceStorage | None,
    mission_signing_key: Ed25519PrivateKey,
    mission_signing_key_id: str,
    mission_contract_writer_version: Literal["1.2", "1.3"] = "1.2",
    mission_contract_issuer_id: str | None = None,
    risk_policy_packs: tuple[dict[str, Any], ...] = (),
    edge_runtime_profiles: tuple[dict[str, Any], ...] = (),
    device_attestation_registry: DeviceAttestationRegistry | None = None,
    acquisition_coordination_enabled: bool = True,
    acquisition_issue_gate_enabled: bool = False,
    copilot_runtime_config: CopilotRuntimeConfig | None = None,
    expose_docs: bool = True,
) -> FastAPI:
    """모든 store 를 조립하고 ``create_app`` 을 호출한다 — dev/production 공용.

    ``data_dir`` 은 호출자가 이미 만들어 뒀다고 가정한다(``run_core_dev.py`` 의
    ``build_dev_app`` 관습과 동일). 원장을 여는 것은 ``journal`` 클로저의 몫이고,
    호출자는 조립 실패 시 ``opened`` 에 누적된 원장을 전부 닫을 책임을 진다
    (``build_dev_app``/``production.build_production_app`` 양쪽이 이 관습을 따른다).
    """
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
    # 원본 사진 번들(3D 파이프라인 입구) — evidence_storage 없이는 store 는 구성돼도
    # 라우트가 장착되지 않는다(evidence 라우트와 같은 관습, create_app 참조).
    source_media_journal = journal("source-media.jsonl")
    source_media_store = SourceMediaStore(source_media_journal, mission_store=mission_store)
    site_store = SiteStore(site_journal)
    # 처리 작업(ADR-KSI-012) — 봉인된 번들에서 입력을, 현장에서 반출 허용 여부를
    # 읽는다(INV-050). source_media 와 달리 오브젝트 스토리지를 요구하지 않는다.
    processing_job_journal = journal("processing-jobs.jsonl")
    # evidence_storage 없이 이 저장소를 넘기면 create_app 이 조립 자체를 거부한다
    # (ADR-KSI-012/INV-050 — 워커가 원본 바이트를 받아갈 URL 이 없으면 SUCCEEDED
    # 게이트가 영구히 닫힌 조립이 된다). 스토리지가 없으면 이 표면을 장착하지
    # 않는 편이 정직하다 — source_media 라우트가 같은 이유로 이미 그렇게 동작한다.
    processing_job_store = (
        ProcessingJobStore(
            processing_job_journal, source_media_store=source_media_store, site_store=site_store
        )
        if evidence_storage is not None
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
    )
    observation_work_order_journal = journal("observation-work-orders.jsonl")
    observation_work_order_store = ObservationWorkOrderStore(
        observation_work_order_journal,
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
        work_areas_exist=lambda site_id, work_area_ids: all(
            (area := work_area_store.get(work_area_id)) is not None
            and area.site_id == site_id
            and area.status is WorkAreaStatus.ACTIVE
            for work_area_id in work_area_ids
        ),
    )
    acquisition_connectivity_store = AcquisitionConnectivityStore(
        journal("acquisition-connectivity.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    acquisition_coordination_store = (
        AcquisitionCoordinationStore(journal("acquisition-runs.jsonl"))
        if acquisition_coordination_enabled
        else None
    )
    # Site workspace reuses the exact EventStore instance mounted on the public API;
    # opening a second writer for the same journal would violate DurableJournal locking.
    event_store = EventStore(event_journal)
    from ksi_core.site_workspace import (
        SiteWorkspaceProjector,
        build_workspace_copilot_handlers,
    )

    site_workspace_projector = SiteWorkspaceProjector(
        site_store=site_store,
        work_order_store=observation_work_order_store,
        processing_job_store=processing_job_store,
        event_store=event_store,
    )
    copilot_service = None
    copilot_conversation_service = None
    site_briefing_service = None
    if copilot_runtime_config is not None:
        from ksi_core.copilot import CopilotService, CoreCopilotToolBackend
        from ksi_core.copilot_conversations import (
            CopilotConversationService,
            CopilotConversationStore,
        )
        from ksi_core.copilot_openai import OpenAiCompatibleModelAdapter
        from ksi_core.site_workspace import SiteBriefingService, SiteBriefingStore

        def _capture_policy_for_work_order(
            organization_id: str, work_order_id: str
        ) -> str | None:
            order = observation_work_order_store.get(
                work_order_id, organization_id=organization_id
            )
            if order is None or order.schedule_id is None:
                return None
            schedules = observation_work_order_store.list_schedules(
                order.site_id, organization_id=organization_id
            )
            schedule = next(
                (item for item in schedules if item.schedule_id == order.schedule_id),
                None,
            )
            return schedule.approved_policy_version if schedule is not None else None

        backend = CoreCopilotToolBackend(
            site_store=site_store,
            observation_work_order_store=observation_work_order_store,
            query_handlers=build_workspace_copilot_handlers(
                site_workspace_projector, observation_work_order_store
            ),
            ai_egress_policy=lambda organization_id, site_id: bool(
                (site := site_store.get_scoped(site_id, organization_id)) is not None
                and site.ai_egress_allowed
            ),
            capture_policy_for_work_order=_capture_policy_for_work_order,
        )
        copilot_service = CopilotService(
            model=OpenAiCompatibleModelAdapter(
                base_url=copilot_runtime_config.base_url,
                model=copilot_runtime_config.model,
                api_key_file=copilot_runtime_config.api_key_file,
                timeout_seconds=copilot_runtime_config.timeout_seconds,
            ),
            backend=backend,
            planner_version=copilot_runtime_config.planner_version,
        )
        conversation_store = CopilotConversationStore(
            journal("copilot-conversations.jsonl"),
            site_exists=lambda site_id, organization_id: (
                site_store.get_scoped(site_id, organization_id) is not None
            ),
            work_order_matches=lambda work_order_id, organization_id, site_id: (
                (order := observation_work_order_store.get(
                    work_order_id, organization_id=organization_id
                ))
                is not None
                and order.site_id == site_id
            ),
        )
        copilot_conversation_service = CopilotConversationService(
            store=conversation_store,
            copilot=copilot_service,
            provider=copilot_runtime_config.provider_name,
            model=copilot_runtime_config.model,
            planner_version=copilot_runtime_config.planner_version,
        )
        site_briefing_service = SiteBriefingService(
            store=SiteBriefingStore(
                journal("site-briefings.jsonl"), site_store=site_store
            ),
            copilot=copilot_service,
            workspace=site_workspace_projector,
        )

        def _create_review_ready_briefing(order: Any) -> None:
            from ksi_event_contracts.observation_work_order import ObservationWorkOrderStatus

            if order.status is not ObservationWorkOrderStatus.REVIEW_READY:
                return
            site_briefing_service.refresh(
                order.site_id,
                principal=Principal(
                    principal_id="system-site-briefing",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                    organization_id=order.organization_id,
                ),
            )

        observation_work_order_store.bind_status_listener(_create_review_ready_briefing)
    design_conformance_request_journal = journal("design-conformance-requests.jsonl")
    design_conformance_report_journal = journal("design-conformance.jsonl")
    design_conformance_request_store = (
        DesignConformanceRequestStore(
            design_conformance_request_journal,
            mission_store=mission_store,
            processing_job_store=processing_job_store,
            design_surface_store=design_surface_store,
            work_area_store=work_area_store,
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
    equipment_state_journal = journal("equipment-states.jsonl")
    equipment_support_journal = journal("equipment-support.jsonl")
    app = create_app(
        auth_registry=auth_registry,
        human_auth_mode=human_auth_mode,
        oidc_verifier=oidc_verifier,
        site_store=site_store,
        observation_work_order_store=observation_work_order_store,
        acquisition_connectivity_store=acquisition_connectivity_store,
        acquisition_coordination_store=acquisition_coordination_store,
        acquisition_issue_gate_enabled=acquisition_issue_gate_enabled,
        copilot_service=copilot_service,
        copilot_conversation_service=copilot_conversation_service,
        site_workspace_projector=site_workspace_projector,
        site_briefing_service=site_briefing_service,
        mission_store=mission_store,
        event_store=event_store,
        edge_sync_store=edge_sync_store,
        edge_dispatch_store=edge_dispatch_store,
        evidence_storage=evidence_storage,
        coverage_report_store=CoverageReportStore(coverage_journal, mission_store=mission_store),
        mission_execution_store=mission_execution_store,
        source_media_store=source_media_store,
        design_surface_store=design_surface_store,
        work_area_store=work_area_store,
        processing_job_store=processing_job_store,
        defect_candidate_store=DefectCandidateStore(
            defect_candidate_journal,
            mission_store=mission_store,
            source_media_store=source_media_store,
        ),
        # 변화 탐지 결과는 point_cloud 산출물을 지목해야 해석된다 — 작업 원장이
        # 없는 조립에서는 그 대조가 불가능하므로 표면도 열지 않는다.
        change_detection_store=(
            ChangeDetectionStore(
                change_detection_journal,
                mission_store=mission_store,
                processing_job_store=processing_job_store,
            )
            if processing_job_store is not None
            else None
        ),
        # 체적 리포트도 같다 — 어느 두 DSM 을 비교했는지 대조할 작업 원장이
        # 없으면 "이만큼 깎였다"가 재현 불가능한 주장이 된다.
        volume_change_store=(
            VolumeChangeStore(
                volume_change_journal,
                mission_store=mission_store,
                processing_job_store=processing_job_store,
            )
            if processing_job_store is not None
            else None
        ),
        # W2 비교 요청(comparison_requests.py) — evidence_storage 까지 필요한
        # 것은 워커가 baseline/current 원본을 읽어갈 presigned URL 을 이 표면이
        # 직접 발급하기 때문이다(processing_job_store 와 동일 근거).
        comparison_request_store=(
            ComparisonRequestStore(
                comparison_request_journal,
                mission_store=mission_store,
                processing_job_store=processing_job_store,
            )
            if processing_job_store is not None and evidence_storage is not None
            else None
        ),
        design_conformance_request_store=design_conformance_request_store,
        design_conformance_report_store=design_conformance_report_store,
        region_extraction_request_store=region_extraction_request_store,
        region_extraction_report_store=region_extraction_report_store,
        equipment_state_store=EquipmentStateStore(equipment_state_journal, site_store=site_store),
        equipment_support_store=EquipmentSupportStore(equipment_support_journal),
        device_attestation_registry=device_attestation_registry,
        mission_signing_key=mission_signing_key,
        mission_signing_key_id=mission_signing_key_id,
        mission_contract_writer_version=mission_contract_writer_version,
        mission_contract_issuer_id=mission_contract_issuer_id,
        mission_sequence_store=mission_sequence_store,
        expose_docs=expose_docs,
    )

    # 미들웨어는 마지막 등록이 가장 바깥이다(Starlette 관례) — CorrelationId 를
    # 가장 바깥에 두어 그 안의 HttpMetrics·라우팅·인증 전부의 로그가 같은
    # correlation id 를 갖게 한다. 순서를 반대로 하면 미들웨어 자신의 로그(있다면)
    # 는 id 가 없는 채로 찍힌다.
    app.add_middleware(HttpMetricsMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/metrics")
    def metrics() -> PlainTextResponse:
        """Prometheus 스크레이프 표면 — ``/ready`` 와 같은 이유로 무인증이다.

        스크레이퍼는 인증 헤더를 보내지 않는 것이 표준 배치이고(네트워크
        경계로 접근을 제한하는 것이 일반적 운영 관례), 이 표면 자체가 민감한
        요청 내용을 담지 않는다(집계된 카운트·지연 분포뿐, 요청 본문 없음).
        ``tests/contract/test_api_contract_sync.py`` 의
        ``_ASSEMBLE_APP_UNAUTHENTICATED_ALLOWLIST`` 에 명시적으로 올라 있다.
        """
        return PlainTextResponse(render_prometheus_text(), media_type="text/plain; version=0.0.4")

    @app.get("/ready")
    def ready() -> JSONResponse:
        """readiness — opened 원장 중 하나라도 봉인(sealed)됐으면 503.

        ``/health`` 는 프로세스 생존만 본다. 오케스트레이터가 ``/health`` 만 보면
        journal 이 봉인돼 모든 쓰기가 503 인 서버를 건강하다고 오판한다.

        ``opened`` 에는 ``DurableJournal`` 과 ``EdgeSyncStore`` 가 함께 들어온다 —
        둘 다 ``sealed_reason`` property 를 노출하므로(P0-1) ``getattr`` 은 순수
        방어적 접근일 뿐, 어느 쪽도 봉인 판정에서 빠지지 않는다.
        """
        sealed = [j for j in opened if getattr(j, "sealed_reason", None) is not None]
        if sealed:
            return JSONResponse(
                status_code=503, content={"ready": False, "sealedCount": len(sealed)}
            )
        return JSONResponse(status_code=200, content={"ready": True})

    return app


__all__ = ["assemble_app", "cli_optional_positive"]
