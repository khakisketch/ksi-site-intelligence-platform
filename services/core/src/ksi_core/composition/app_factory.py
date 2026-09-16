"""KSI Core FastAPI 앱 팩토리 (ADR-KSI-001, ADR-KSI-008).

Core는 지리공간·워크플로 control plane이다 — 비행 중 실시간 판단은 Manifold Edge가,
저수준 비행 안전은 DJI Flight Controller가 소유한다(INV-001). 이 앱은 그 경계를
코드로 지킨다:

- **프레임별 비행제어 엔드포인트를 두지 않는다.** Core가 노출하는 것은 계약·정책·
  상태 조회이지 조종 명령이 아니다(INV-001, 00_READ_FIRST "구현 금지").
- **Capability catalog는 VERIFIED만 노출한다.** ``/capabilities``는
  :meth:`~ksi_core.capability.registry.CapabilityRegistry.list_operational` 만
  호출하는 legacy compatibility projection이다. 조직/현장 scope가 없으므로
  CAP-5 runtime 또는 Mission 실행 권한을 표현하지 않는다(INV-041).

## fail-closed 조립 (ADR-KSI-008 §3) — "인증 없는 보호 표면은 존재할 수 없다"

``create_app`` 은 다음 결합 위반을 :class:`ValueError` 로 즉시 거부한다(오염된
조립으로 기동하지 않는다):

1. 보호 표면(``edge_sync_store``·``event_store``·``site_store``·``mission_store``·
   서명키) 을 하나라도 주입하면 ``auth_registry`` 가 필수다.
2. 서명키(``mission_signing_key``/``mission_signing_key_id``) 가 주어지면
   ``mission_store``·``site_store`` 가 모두 필수다 — 발급 레코드가 durable
   기록되기 전에는 201 을 반환하지 않는다(고아 발급 금지).
3. ``edge_sync_store`` 가 주어지면 ``event_store`` 가 필수다 — 수신은 ACK 했는데
   트리아지에 보이지 않는 조용한 유실 표면을 막는다.
4. 서명키·edge_sync_store 는 각각 절반만 주어질 수 없다(기존 규칙 유지).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from fastapi import FastAPI

from ksi_core.api_base import mount_validation_error_handler
from ksi_core.auth import HumanAuthMode
from ksi_core.capability.registry import CapabilityRegistry, seed_prd_spikes
from ksi_core.composition.assembly_validation import (
    _ASSEMBLY_REQUIREMENTS,  # noqa: F401 -- legacy app module re-exports exact tuple identity
    validate_assembly_requirements,
)
from ksi_core.composition.routes.external import mount_external_routes
from ksi_core.composition.routes.identity_work import mount_identity_work_routes
from ksi_core.composition.routes.missions import mount_mission_routes
from ksi_core.composition.routes.operations import mount_operations_routes
from ksi_core.composition.routes.processing import mount_processing_routes

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from ksi_core.acquisition import AcquisitionConnectivityStore, AcquisitionCoordinationStore
    from ksi_core.auth import AuthRegistry, OidcVerifier
    from ksi_core.capability.runtime_projection import RuntimeCapabilityProjector
    from ksi_core.capture_quality_reports import CaptureQualityReportStore
    from ksi_core.change_detection import ChangeDetectionStore
    from ksi_core.checkpoint_validations import CheckpointValidationStore
    from ksi_core.civil_readiness import CivilReadinessProjector
    from ksi_core.comparison_requests import ComparisonRequestStore
    from ksi_core.copilot import CopilotService
    from ksi_core.copilot_conversations import CopilotConversationService
    from ksi_core.coverage_reports import CoverageReportStore
    from ksi_core.defect_candidates import DefectCandidateStore
    from ksi_core.design_conformance_reports import DesignConformanceStore
    from ksi_core.design_conformance_requests import DesignConformanceRequestStore
    from ksi_core.design_surfaces import DesignSurfaceStore
    from ksi_core.device_attestation import DeviceAttestationRegistry
    from ksi_core.edge_dispatch import EdgeDispatchStore
    from ksi_core.edge_sync import EdgeSyncStore
    from ksi_core.equipment_states import EquipmentStateStore
    from ksi_core.equipment_support import EquipmentSupportStore
    from ksi_core.events import EventStore
    from ksi_core.evidence import EvidenceStorage
    from ksi_core.external_artifact_inspections import ExternalArtifactInspectionStore
    from ksi_core.external_display_artifacts import ExternalDisplayArtifactStore
    from ksi_core.external_evidence import ExternalEvidenceStore
    from ksi_core.external_evidence_validations import ExternalEvidenceValidationStore
    from ksi_core.external_reconstruction import ExternalReconstructionStore
    from ksi_core.external_relative_volumes import (
        ExternalRelativeVolumeExecutionActivator,
        ExternalRelativeVolumeInputCapabilityIssuer,
        ExternalRelativeVolumeStore,
    )
    from ksi_core.external_reobservation_proposals import ExternalReobservationProposalService
    from ksi_core.external_result_workflow_api import ExternalResultReadProjector
    from ksi_core.external_use_evaluator import ExternalUseEvaluator
    from ksi_core.flight_artifacts import FlightArtifactStore
    from ksi_core.mission_execution import MissionExecutionStore
    from ksi_core.mission_records import MissionIssuanceSequenceStore, MissionStore
    from ksi_core.observation_work_orders import ObservationWorkOrderStore
    from ksi_core.organization_work_roster import OrganizationWorkRosterStore
    from ksi_core.processing_jobs import ProcessingJobStore
    from ksi_core.region_extraction_reports import RegionExtractionStore
    from ksi_core.region_extraction_requests import RegionExtractionRequestStore
    from ksi_core.report_exports import ReportExportStore
    from ksi_core.site_workspace import SiteBriefingService, SiteWorkspaceProjector
    from ksi_core.sites import SiteStore
    from ksi_core.source_media import SourceMediaStore
    from ksi_core.volume_reports import VolumeChangeStore
    from ksi_core.work_areas import WorkAreaStore
    from ksi_core.work_inbox import WorkInboxStore
def create_app(
    *,
    registry: CapabilityRegistry | None = None,
    auth_registry: AuthRegistry | None = None,
    human_auth_mode: HumanAuthMode = HumanAuthMode.OPAQUE,
    oidc_verifier: OidcVerifier | None = None,
    edge_sync_store: EdgeSyncStore | None = None,
    edge_dispatch_store: EdgeDispatchStore | None = None,
    event_store: EventStore | None = None,
    site_store: SiteStore | None = None,
    mission_store: MissionStore | None = None,
    mission_signing_key: Ed25519PrivateKey | None = None,
    mission_signing_key_id: str | None = None,
    mission_contract_writer_version: Literal["1.2", "1.3"] = "1.2",
    mission_contract_issuer_id: str | None = None,
    mission_sequence_store: MissionIssuanceSequenceStore | None = None,
    evidence_storage: EvidenceStorage | None = None,
    flight_artifact_store: FlightArtifactStore | None = None,
    coverage_report_store: CoverageReportStore | None = None,
    mission_execution_store: MissionExecutionStore | None = None,
    source_media_store: SourceMediaStore | None = None,
    design_surface_store: DesignSurfaceStore | None = None,
    processing_job_store: ProcessingJobStore | None = None,
    checkpoint_validation_store: CheckpointValidationStore | None = None,
    defect_candidate_store: DefectCandidateStore | None = None,
    change_detection_store: ChangeDetectionStore | None = None,
    volume_change_store: VolumeChangeStore | None = None,
    comparison_request_store: ComparisonRequestStore | None = None,
    design_conformance_request_store: DesignConformanceRequestStore | None = None,
    design_conformance_report_store: DesignConformanceStore | None = None,
    report_export_store: ReportExportStore | None = None,
    region_extraction_request_store: RegionExtractionRequestStore | None = None,
    region_extraction_report_store: RegionExtractionStore | None = None,
    work_area_store: WorkAreaStore | None = None,
    observation_work_order_store: ObservationWorkOrderStore | None = None,
    organization_work_roster_store: OrganizationWorkRosterStore | None = None,
    work_inbox_store: WorkInboxStore | None = None,
    external_reconstruction_store: ExternalReconstructionStore | None = None,
    external_evidence_store: ExternalEvidenceStore | None = None,
    external_evidence_validation_store: ExternalEvidenceValidationStore | None = None,
    external_use_evaluator: ExternalUseEvaluator | None = None,
    external_relative_volume_store: ExternalRelativeVolumeStore | None = None,
    external_result_workflow_service: ExternalReobservationProposalService | None = None,
    external_result_read_projector: ExternalResultReadProjector | None = None,
    external_volume_input_capability_issuer: ExternalRelativeVolumeInputCapabilityIssuer
    | None = None,
    external_volume_execution_activator: ExternalRelativeVolumeExecutionActivator | None = None,
    external_display_artifact_store: ExternalDisplayArtifactStore | None = None,
    external_artifact_inspection_store: ExternalArtifactInspectionStore | None = None,
    acquisition_connectivity_store: AcquisitionConnectivityStore | None = None,
    acquisition_coordination_store: AcquisitionCoordinationStore | None = None,
    capture_quality_report_store: CaptureQualityReportStore | None = None,
    acquisition_issue_gate_enabled: bool = False,
    landxml_ingress_enabled: bool = False,
    checkpoint_validation_registration_enabled: bool = False,
    copilot_service: CopilotService | None = None,
    copilot_conversation_service: CopilotConversationService | None = None,
    site_workspace_projector: SiteWorkspaceProjector | None = None,
    site_briefing_service: SiteBriefingService | None = None,
    civil_readiness_projector: CivilReadinessProjector | None = None,
    equipment_state_store: EquipmentStateStore | None = None,
    equipment_support_store: EquipmentSupportStore | None = None,
    runtime_capability_projector: RuntimeCapabilityProjector | None = None,
    device_attestation_registry: DeviceAttestationRegistry | None = None,
    expose_docs: bool = True,
) -> FastAPI:
    """Core 앱을 만든다.

    Args:
        registry: 주입할 Capability Registry. ``None``이면 PRD §20.3 SPIKE 9종을
            시드한 새 레지스트리를 만든다 — 시드 직후 노출 가능한 capability는
            0건이다(실기 검증 증거가 없으므로, INV-041).
        expose_docs: ``True``(기본)면 FastAPI 기본 문서 라우트(``/openapi.json``·
            ``/docs``·``/docs/oauth2-redirect``·``/redoc``)가 무인증으로 열린다 —
            이 **넷**은 ``/health``·``/capabilities`` 와 함께 공개 allowlist 다
            (계약 서술 자체가 민감 정보는 아니다). ``/docs/oauth2-redirect`` 는
            ``/docs`` 를 켜면 FastAPI 가 함께 다는 라우트라 서술에서 빠져 있었다
            (s2-residual-hardening #5 — 서술이 실제 표면보다 좁으면 "무엇이
            공개인가"를 문서로 감사할 수 없다). 운영 배포에서 계약 표면을 외부에
            노출하고 싶지 않으면 ``False`` 로 꺼서 네 라우트를 전부 존재하지 않게
            만든다(감사 #25·#35 재검토 — "문서 라우트만 공개" 주장이 스위치 부재로
            반증됐던 사각지대).
        auth_registry: bearer 토큰 → Principal 매핑(ADR-KSI-008 §2). 보호 표면
            (아래 5개 인자 중 하나라도)을 주입하려면 이것도 함께 줘야 한다 —
            인증 없는 보호 표면은 조립 자체가 거부된다. 단독으로 주면
            ``/v1/auth/whoami`` 만 장착된다.
        edge_sync_store: Edge→Core EventBundle 멱등 수신 저장소. ``None``이면
            edge-sync 엔드포인트가 **존재하지 않는다** — durable 저장 없이 수신
            API 만 열리는 구성(ACK 후 유실 경로)을 타입이 아니라 조립에서 막는다.
        event_store: Event projection·트리아지 저장소. ``edge_sync_store``가
            주어지면 **함께 주어져야 한다**(ADR-KSI-008 §3) — 수신은 ACK 했는데
            트리아지에 보이지 않는 조용한 유실 표면을 조립에서 막는다. edge-sync
            없이 단독으로 주어지면 ``/v1/events`` 조회·트리아지 엔드포인트만
            장착된다(예: Site/Mission 만 있고 Edge 수신은 아직 없는 배포).
        site_store: Site 상태머신 영속·조회·전이 저장소. 주어지면 ``/v1/sites``
            표면이 장착되고, 서명키 발급 경로의 site 등록 대조(존재+siteFrame
            일치)도 이 저장소로
            배선된다(``site_store.get``).
        mission_store: Mission 발급 이력 영속·조회 저장소. 주어지면 ``/v1/missions``
            조회 표면(``mount_mission_records``)이 장착된다. 서명키가 주어지면
            ``site_store`` 와 함께 필수다(위 조립 규칙 2).
        mission_signing_key: Mission Contract 발급 서명키. ``mission_signing_key_id``와
            둘 다 주어져야 발급 엔드포인트가 장착된다(ADR-KSI-007) — 서명키 없이는
            엔드포인트가 존재하지 않는다(edge_sync_store와 동일한 fail-closed 조립).
            주어지면 ``mission_store``·``site_store`` 가 모두 필수다(ADR-KSI-008 §3
            — 발급 레코드가 durable 기록되기 전에는 201 을 반환하지 않는다).
        mission_signing_key_id: 서명 블록에 실릴 keyId — 검증 측 KeyRegistry에
            등록된 것과 일치해야 한다.
        source_media_store: 원본 사진 번들(3D 파이프라인 입구) 등록·봉인 저장소.
            주어지면 ``mission_store`` 가 필수다(발급된 적 없는 임무의 번들은
            받지 않는다, coverage_report_store 와 동일 원칙). 라우트 장착은 그와
            별개로 ``evidence_storage`` 유무를 따른다 — presigned URL 을 발급할
            스토리지가 없으면 이 표면 자체가 장착되지 않는다(evidence 라우트와
            같은 관습).
        design_surface_store: 설계 기준면(계획고 DEM) 등록·봉인·검증 저장소.
            ``site_store`` 가 필수다 — 설계면은 현장에 매달린 자산이고 객체 키가
            siteId 를 필요로 한다. 라우트 장착은 그와 별개로 ``evidence_storage``
            유무를 따른다(source_media 와 같은 관습) — 업로드·다운로드 URL 을
            낼 스토리지가 없으면 등록해도 파일을 올릴 곳이 없고, 워커가 바이트를
            읽을 수 없어 VERIFIED 게이트가 영구히 닫힌 조립이 된다.
        processing_job_store: 3D 재구성 처리 작업(ADR-KSI-012) 발급·상태전이
            저장소. ``source_media_store`` 와 ``site_store`` 가 모두 필수다 —
            입력은 봉인된 번들에서, 반출 허용 여부는 현장에서 읽는다(INV-050).
            둘 중 하나라도 없으면 요청이 그 값들을 스스로 주장하는 구성이 되므로
            조립에서 거부한다.
        civil_readiness_projector: 현장별 토목 준비도 읽기 모델. ``site_store``·
            ``processing_job_store``·``design_surface_store`` 가 모두 있어야
            장착된다. 이 모델은 기존 ``preflight_epoch_pair`` 결과와 설계면
            inventory를 읽기만 하며, 실제 비교 요청은 각 입력으로 다시 preflight를
            수행한다(INV-053). 현장 수용·측량 정확도·비행·장비 상태를 판정하지
            않는다.
        checkpoint_validation_store: 독립 checkpoint CSV와 immutable DSM의 서버 측
            측정 원장. ``mission_store``·``processing_job_store``·``evidence_storage``가
            모두 필요하다(INV-024/053). 이를 통해 검증된 RMSE만 비교 불확실성에
            쓸 수 있고, 작업자 RMSE 자기신고는 이 표면으로 들어오지 않는다.
        checkpoint_validation_registration_enabled: 신규 checkpoint 등록 rollout gate.
            기본 ``False``다. 꺼도 기존 검증 결과 조회·worker 처리 표면은 유지하며,
            신규 운영자 등록만 403으로 닫는다.
        defect_candidate_store: Phase 4 결함 후보(균열) 수신·조회 저장소.
            ``mission_store`` 와 ``source_media_store`` 가 모두 필수다 — 후보는
            "어느 임무의 어느 사진 위 픽셀 좌표인가"로만 의미를 가지므로, 그
            참조를 대조할 저장소 없이는 검증 불가능한 도형을 그대로 받게 된다.
        change_detection_store: Phase 4 시계열 변화 탐지 결과 수신·조회 저장소.
        volume_change_store: M1 구역 체적 변화 리포트 수신·조회 저장소.
            ``mission_store`` 와 ``processing_job_store`` 가 모두 필수다 — 결과는
            "어느 두 point cloud 산출물을 비교했나"로만 해석 가능하고, 그 참조를
            대조할 작업 원장이 없으면 "변화가 있었다"가 검증 불가능한 주장이 된다.
        comparison_request_store: W2 "이 두 작업을 비교하라"는 요청의 수신·발견·
            lease·전이 저장소. ``mission_store``·``processing_job_store``·
            ``evidence_storage`` 가 모두 필수다 — baseline/current 참조를 대조할
            작업 원장, 그리고 워커가 그 산출물을 읽어갈 presigned URL 을 발급할
            스토리지가 없으면 이 표면 자체가 성립하지 않는다(processing_job_store
            와 동일한 fail-closed 조립 원칙).
        design_conformance_request_store: M4-A "이 설계면과 이 지형을 비교하라"는
            요청의 수신·발견·lease·전이 저장소. ``mission_store``·
            ``processing_job_store``·``design_surface_store``·``evidence_storage``
            가 모두 필수다 — VERIFIED 설계면만 입력이 되는지 대조하려면 설계면
            원장이, 워커가 두 입력을 읽고 차분 래스터를 올리려면 스토리지가
            필요하다(comparison_request_store 와 동일한 fail-closed 조립 원칙).
        design_conformance_report_store: M4-A 설계 대비 잔량 리포트 원장.
            위 요청 저장소와 ``evidence_storage`` 가 필수다 — 이 원장은 리포트를
            받는 순간 **차분 래스터 바이트를 직접 다시 해싱해** 워커의 신고와
            대조하고, 다르면 리포트를 기록하지 않고 요청을 FAILED 로 보낸다.
            그 대조 없이 조립하면 "유효한 리포트가 있는데 지도는 다른 파일"이
            성립한다(design_conformance_reports.py 모듈 docstring).
        report_export_store: 브라우저 PDF/CSV 내보내기 감사 원장. ``site_store``와
            ``design_conformance_report_store``가 모두 있어야 한다. 파일 bytes를
            받거나 서버 생성 산출물로 표시하지 않고, 인증 Principal·조직-scoped
            Site·Core-verified report snapshot만 durable하게 남긴다.
        region_extraction_request_store: M4-E "이 설계 대비 잔량 리포트에서 변화
            영역을 뽑아라"는 요청의 수신·발견·lease·전이 저장소.
            ``mission_store``·``design_conformance_report_store``·
            ``evidence_storage`` 가 모두 필수다 — RECORDED 된 설계 대비 잔량
            리포트만 입력이 되는지 대조하려면 그 원장이, 워커가 diffRaster 를
            읽으려면 스토리지가 필요하다.
        region_extraction_report_store: M4-E 변화 영역 추출 리포트 원장. 위 요청
            저장소와 ``design_conformance_report_store`` 가 필수다 — 이 원장은
            리포트를 받을 때 요청과 원본 설계 대비 잔량 리포트를 대조해서만
            기록한다(바이트 재해싱은 없다 — region_extraction_reports.py 모듈
            docstring).
        equipment_state_store: Phase 3 장비 운동상태 수신·위험 평가 저장소.
            ``site_store`` 가 필수다 — 위치·속도는 좌표계 없이는 숫자일 뿐이고,
            현장 등록 좌표계와 대조하지 않으면 서로 다른 기준계의 점 사이 거리를
            재는 CPA/TTC 가 성립해 버린다(``cpa_ttc`` 의 site_frame 검사는 두
            상태끼리만 보므로 둘 다 같은 잘못된 좌표계면 통과한다).
        equipment_support_store: 장비 클래스 지원단계(INV-041, MASTER_PRD §23.3)
            등록·전이 저장소. 다른 저장소를 요구하지 않는다 — 이 원장은 현장·임무와
            무관한 **제품 전역** 사실(어느 장비 클래스를 어디까지 검증했나)이라
            대조할 상대가 없다. 주어지면 ``/v1/equipment-support`` 표면이 장착되고,
            그때 비로소 ``assert_support_level_transition`` 이 런타임에서 강제된다.
    """
    capability_registry = registry if registry is not None else CapabilityRegistry()
    if registry is None:
        seed_prd_spikes(capability_registry)

    app = FastAPI(
        title="KSI Core",
        version="0.0.1",
        summary="KSI Site Intelligence Core — 계약·정책·상태 control plane (비행제어 없음)",
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
    )
    app.state.capability_registry = capability_registry

    # 요청 검증 422 를 항상 JSON 으로 그린다 — 기본 핸들러는 오류 상세에 문제의 값을
    # 되싣는데, 그 값이 비유한 실수나 lone surrogate 면 422 를 그리다 터져 500 +
    # text/plain 이 나간다(2026-08-18 실측, api_base 참조). 장착은 여기 한 곳이면
    # 충분하다 — dev·production 조립 모두 create_app 을 거친다.
    mount_validation_error_handler(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        """liveness — 의존 서비스 상태를 확인하지 않는 순수 프로세스 생존 신호."""
        return {"status": "ok"}

    @app.get("/capabilities")
    def list_capabilities() -> dict[str, Any]:
        """Product catalog에서 승인된 VERIFIED compatibility 항목만 반환한다.

        SPIKE_REQUIRED/BLOCKED 항목은 이 응답에 절대 포함되지 않는다 — 미검증 기능이
        제품 catalog에 노출되는 것을 막는 게이트다. 다만 scope 없는 public 응답이므로
        CurrentRuntimeReady, Mission permission 또는 OperationallyUsable을 뜻하지 않는다.
        감사용 전체 목록은 이 공개 API가 아니라 내부 경로로 제공한다.
        """
        catalog_visible = capability_registry.list_operational()
        # 공개 응답은 식별·상태만(감사 #49) — firmware/PSDK 버전은 배치 기체의
        # 취약점 표적화에 쓰이는 정보라 인증된 내부·감사 경로에서만 제공한다.
        return {
            "capabilities": [
                {
                    "capabilityId": record.capability_id,
                    "title": record.title,
                    "state": record.state.value,
                }
                for record in catalog_visible
            ],
            "count": len(catalog_visible),
        }

    # ── fail-closed 결합 검증(장착 전에 전부 확인 — 절반 조립으로 기동하지 않는다) ──

    # 표(_ASSEMBLY_REQUIREMENTS)에 있는 각 인자의 실제 값 — 결합 검증 루프와
    # protected_surface 판정이 여기서 이름으로 값을 찾는다.
    _provided: dict[str, Any] = {
        "mission_signing_key": mission_signing_key,
        "evidence_storage": evidence_storage,
        "flight_artifact_store": flight_artifact_store,
        "edge_sync_store": edge_sync_store,
        "edge_dispatch_store": edge_dispatch_store,
        "coverage_report_store": coverage_report_store,
        "mission_execution_store": mission_execution_store,
        "source_media_store": source_media_store,
        "design_surface_store": design_surface_store,
        "processing_job_store": processing_job_store,
        "checkpoint_validation_store": checkpoint_validation_store,
        "defect_candidate_store": defect_candidate_store,
        "change_detection_store": change_detection_store,
        "volume_change_store": volume_change_store,
        "comparison_request_store": comparison_request_store,
        "design_conformance_request_store": design_conformance_request_store,
        "report_export_store": report_export_store,
        "work_area_store": work_area_store,
        "observation_work_order_store": observation_work_order_store,
        "organization_work_roster_store": organization_work_roster_store,
        "work_inbox_store": work_inbox_store,
        "external_reconstruction_store": external_reconstruction_store,
        "external_evidence_store": external_evidence_store,
        "external_evidence_validation_store": external_evidence_validation_store,
        "external_use_evaluator": external_use_evaluator,
        "external_relative_volume_store": external_relative_volume_store,
        "external_result_workflow_service": external_result_workflow_service,
        "external_result_read_projector": external_result_read_projector,
        "external_volume_input_capability_issuer": external_volume_input_capability_issuer,
        "external_display_artifact_store": external_display_artifact_store,
        "external_artifact_inspection_store": external_artifact_inspection_store,
        "acquisition_connectivity_store": acquisition_connectivity_store,
        "acquisition_coordination_store": acquisition_coordination_store,
        "capture_quality_report_store": capture_quality_report_store,
        "copilot_service": copilot_service,
        "copilot_conversation_service": copilot_conversation_service,
        "site_workspace_projector": site_workspace_projector,
        "site_briefing_service": site_briefing_service,
        "civil_readiness_projector": civil_readiness_projector,
        "design_conformance_report_store": design_conformance_report_store,
        "region_extraction_request_store": region_extraction_request_store,
        "region_extraction_report_store": region_extraction_report_store,
        "equipment_state_store": equipment_state_store,
        "event_store": event_store,
        "site_store": site_store,
        "mission_store": mission_store,
        "mission_sequence_store": mission_sequence_store,
        "equipment_support_store": equipment_support_store,
        "runtime_capability_projector": runtime_capability_projector,
    }

    validate_assembly_requirements(
        provided=_provided,
        mission_signing_key=mission_signing_key,
        mission_signing_key_id=mission_signing_key_id,
        mission_contract_writer_version=mission_contract_writer_version,
        mission_contract_issuer_id=mission_contract_issuer_id,
        mission_sequence_store=mission_sequence_store,
        acquisition_issue_gate_enabled=acquisition_issue_gate_enabled,
        auth_registry=auth_registry,
    )

    # ── 장착(순서: 인증 → site → edge-sync/events → mission 발급 → mission 조회) ──

    mount_identity_work_routes(
        app,
        auth_registry=auth_registry,
        human_auth_mode=human_auth_mode,
        oidc_verifier=oidc_verifier,
        runtime_capability_projector=runtime_capability_projector,
        mission_store=mission_store,
        mission_execution_store=mission_execution_store,
        site_store=site_store,
        processing_job_store=processing_job_store,
        observation_work_order_store=observation_work_order_store,
        acquisition_coordination_store=acquisition_coordination_store,
        organization_work_roster_store=organization_work_roster_store,
        work_inbox_store=work_inbox_store,
        external_relative_volume_store=external_relative_volume_store,
    )
    mount_external_routes(
        app,
        external_result_read_projector=external_result_read_projector,
        external_result_workflow_service=external_result_workflow_service,
        observation_work_order_store=observation_work_order_store,
        site_store=site_store,
        work_area_store=work_area_store,
        external_relative_volume_store=external_relative_volume_store,
        site_workspace_projector=site_workspace_projector,
        external_reconstruction_store=external_reconstruction_store,
        evidence_storage=evidence_storage,
        external_evidence_store=external_evidence_store,
        external_evidence_validation_store=external_evidence_validation_store,
        external_volume_input_capability_issuer=external_volume_input_capability_issuer,
        external_volume_execution_activator=external_volume_execution_activator,
        external_use_evaluator=external_use_evaluator,
        external_artifact_inspection_store=external_artifact_inspection_store,
        external_display_artifact_store=external_display_artifact_store,
    )
    site_lifecycle = mount_operations_routes(
        app,
        acquisition_connectivity_store=acquisition_connectivity_store,
        acquisition_coordination_store=acquisition_coordination_store,
        observation_work_order_store=observation_work_order_store,
        mission_store=mission_store,
        coverage_report_store=coverage_report_store,
        capture_quality_report_store=capture_quality_report_store,
        source_media_store=source_media_store,
        processing_job_store=processing_job_store,
        mission_execution_store=mission_execution_store,
        copilot_service=copilot_service,
        copilot_conversation_service=copilot_conversation_service,
        site_workspace_projector=site_workspace_projector,
        site_briefing_service=site_briefing_service,
        civil_readiness_projector=civil_readiness_projector,
        site_store=site_store,
        edge_sync_store=edge_sync_store,
        event_store=event_store,
        edge_dispatch_store=edge_dispatch_store,
        evidence_storage=evidence_storage,
        device_attestation_registry=device_attestation_registry,
    )
    mount_mission_routes(
        app,
        event_store=event_store,
        evidence_storage=evidence_storage,
        mission_signing_key=mission_signing_key,
        mission_signing_key_id=mission_signing_key_id,
        mission_store=mission_store,
        site_store=site_store,
        observation_work_order_store=observation_work_order_store,
        acquisition_connectivity_store=acquisition_connectivity_store,
        acquisition_issue_gate_enabled=acquisition_issue_gate_enabled,
        mission_contract_writer_version=mission_contract_writer_version,
        mission_contract_issuer_id=mission_contract_issuer_id,
        mission_sequence_store=mission_sequence_store,
        acquisition_coordination_store=acquisition_coordination_store,
        flight_artifact_store=flight_artifact_store,
        coverage_report_store=coverage_report_store,
        mission_execution_store=mission_execution_store,
        site_lifecycle=site_lifecycle,
        source_media_store=source_media_store,
        design_surface_store=design_surface_store,
        landxml_ingress_enabled=landxml_ingress_enabled,
    )
    mount_processing_routes(
        app,
        processing_job_store=processing_job_store,
        evidence_storage=evidence_storage,
        site_lifecycle=site_lifecycle,
        auth_registry=auth_registry,
        checkpoint_validation_store=checkpoint_validation_store,
        checkpoint_validation_registration_enabled=checkpoint_validation_registration_enabled,
        site_store=site_store,
        defect_candidate_store=defect_candidate_store,
        change_detection_store=change_detection_store,
        volume_change_store=volume_change_store,
        comparison_request_store=comparison_request_store,
        design_conformance_request_store=design_conformance_request_store,
        region_extraction_request_store=region_extraction_request_store,
        design_conformance_report_store=design_conformance_report_store,
        report_export_store=report_export_store,
        work_area_store=work_area_store,
        region_extraction_report_store=region_extraction_report_store,
        equipment_state_store=equipment_state_store,
        equipment_support_store=equipment_support_store,
    )

    return app
