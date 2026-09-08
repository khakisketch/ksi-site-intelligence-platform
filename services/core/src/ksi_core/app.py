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
    from ksi_core.external_evidence import ExternalEvidenceStore
    from ksi_core.external_reconstruction import ExternalReconstructionStore
    from ksi_core.flight_artifacts import FlightArtifactStore
    from ksi_core.mission_execution import MissionExecutionStore
    from ksi_core.mission_records import MissionIssuanceSequenceStore, MissionStore
    from ksi_core.observation_work_orders import ObservationWorkOrderStore
    from ksi_core.processing_jobs import ProcessingJobStore
    from ksi_core.region_extraction_reports import RegionExtractionStore
    from ksi_core.region_extraction_requests import RegionExtractionRequestStore
    from ksi_core.report_exports import ReportExportStore
    from ksi_core.site_workspace import SiteBriefingService, SiteWorkspaceProjector
    from ksi_core.sites import SiteStore
    from ksi_core.source_media import SourceMediaStore
    from ksi_core.volume_reports import VolumeChangeStore
    from ksi_core.work_areas import WorkAreaStore


# 결합 규칙 표 — (store 인자명, 필수 동반 인자 그룹들, 거부 사유 문장).
#
# 각 행의 두 번째 요소는 "그룹의 튜플"이다. 그룹 하나는 "이 그룹 안 인자가 전부
# 주어지면 충족"(AND)을 뜻하고, 그룹이 둘 이상이면 그중 하나만 충족해도 된다
# (OR of AND) — evidence_storage 처럼 소비자가 여럿인 결합에 쓴다. 그룹이 빈
# 튜플인 행(예: event_store)은 결합 검증이 없고 protected_surface 판정에만
# 참여한다.
#
# 이 표의 키 집합이 곧 protected_surface 다(손으로 나열하지 않는다) — 아래
# create_app 안에서 그대로 도출한다.
#
# 항목 순서 = 리팩터링 전 if 문 순서 그대로다(여러 결합 위반이 동시에 있는
# 조립에서 어떤 오류 메시지가 먼저 뜨는지가 이 순서로 정해진다 — 바꾸지 않는다).
# 각 문장은 INV 번호·ADR 번호·사고 이력을 담고 있으므로 한 글자도 바꾸지 않고
# 옮겼다.
_ASSEMBLY_REQUIREMENTS: tuple[tuple[str, tuple[tuple[str, ...], ...], str], ...] = (
    (
        "mission_signing_key",
        (("mission_store", "site_store"),),
        "mission_signing_key 가 주어지면 mission_store 와 site_store 가 모두"
        " 필수다(ADR-KSI-008 §3) — 발급 레코드가 durable 기록되기 전에는 201 을"
        " 반환하지 않는다(고아 발급 금지)",
    ),
    (
        "evidence_storage",
        (
            ("event_store",),
            ("source_media_store",),
            ("mission_signing_key",),
            ("design_surface_store",),
            ("flight_artifact_store",),
            ("checkpoint_validation_store",),
            ("external_reconstruction_store",),
        ),
        "evidence_storage 는 소비자 저장소(event_store·source_media_store·"
        "design_surface_store·flight_artifact_store·checkpoint_validation_store 또는"
        " 임무 서명키)와 함께 주어져야 한다(ADR-KSI-010 §1) — 아무도 쓰지 않는"
        " 오브젝트 스토리지를 매단 채 기동하지 않는다."
        "\n"
        " 원래 이 가드는 event_store 만 요구했다(증거는 사건에 매달리는 것이라 사건"
        " 원장 없이는 등록할 곳이 없다). 3D 파이프라인 입구(source_media)가 같은"
        " 스토리지 포트를 두 번째 소비자로 쓰면서 그 전제가 좁아졌고, 이제 임무"
        " 발급이 KMZ 바이트 보관으로 세 번째 소비자가 됐다(risk"
        " kmz-regeneration-determinism-timebomb) — 가드를 푼 것이 아니라 소비자"
        " 집합을 실제에 맞춘 것이고, 소비자가 하나도 없으면 여전히 거부한다."
        "\n"
        " 설계 기준면(design_surface_store, M4-A)이 네 번째 소비자다 — 등록 시"
        " presigned PUT, 검증 대기 목록에 presigned GET 을 이 포트로 낸다.",
    ),
    (
        "edge_sync_store",
        (("event_store",),),
        "edge_sync_store 는 event_store 와 함께 주어져야 한다(ADR-KSI-008 §3)"
        " — 수신은 ACK 했는데 트리아지에 보이지 않는 유실 표면으로 조립하지 않는다",
    ),
    (
        "edge_dispatch_store",
        (("mission_store",),),
        "edge_dispatch_store 는 mission_store 와 함께 주어져야 한다(REQ-MSN-101)"
        " — 배정되지 않았거나 발급 기록이 없는 임무를 Edge에 dispatch하지 않는다",
    ),
    (
        "coverage_report_store",
        (("mission_store",),),
        "coverage_report_store 는 mission_store 와 함께 주어져야 한다(INV-010)"
        " — 발급된 적 없는 임무의 커버리지 보고는 '무슨 근거로 날았나'에 답할 수"
        " 없다. 보고서는 임무 발급 기록과 대조해서만 받는다",
    ),
    (
        "mission_execution_store",
        (("mission_store",),),
        "mission_execution_store 는 mission_store 와 함께 주어져야 한다"
        " (ADR-KSI-019 G2) — 발급된 적 없는 임무의 실행 사실만 원장에 남으면"
        " '무슨 근거로 날았나'에 답할 수 없다. coverage_report_store 와 동일 원칙이고,"
        " 이 원장은 그 원장의 투영이므로 같은 전제를 공유해야 한다",
    ),
    (
        "source_media_store",
        (("mission_store",),),
        "source_media_store 는 mission_store 와 함께 주어져야 한다"
        " — 발급된 적 없는 임무의 원본 미디어 번들은 '어느 site 소속인지'조차"
        " 알 수 없다(객체 키가 siteId 를 필요로 한다). coverage_report_store 와"
        " 동일 원칙",
    ),
    (
        "flight_artifact_store",
        (("mission_store", "evidence_storage"),),
        "flight_artifact_store는 Mission 원장·EvidenceStorage와 함께 주어져야 한다"
        "(REQ-MSN-104, INV-011/012) — Pilot export 후보는 기존 계약/실행 경로와"
        "분리된 원장과 exact-byte 보관소가 모두 있어야만 받는다",
    ),
    (
        "work_area_store",
        (("site_store",),),
        "work_area_store 는 site_store 와 함께 주어져야 한다"
        " — 작업구역은 '어느 현장의 어디인가'로만 의미를 갖고, 등록된 적 없는"
        " 현장의 구역은 어느 비교에도 쓰이지 못한 채 원장에만 쌓인다"
        " (design_surface_store 와 동일 원칙)",
    ),
    (
        "observation_work_order_store",
        (("site_store",),),
        "observation_work_order_store 는 site_store 와 함께 주어져야 한다(INV-060)",
    ),
    (
        "external_reconstruction_store",
        (("site_store", "observation_work_order_store", "evidence_storage"),),
        "external_reconstruction_store 는 site_store·observation_work_order_store·"
        "evidence_storage 와 함께 주어져야 한다(INV-051/053/060) — 외부 결과는 "
        "managed job·source authority와 분리된 scoped declaration으로만 존재한다",
    ),
    (
        "acquisition_connectivity_store",
        (("site_store",),),
        "acquisition_connectivity_store 는 site_store 와 함께 주어져야 한다"
        "(REQ-ACQ-101, INV-060) — profile과 heartbeat는 등록된 조직-scoped Site에만"
        " 바인딩한다",
    ),
    (
        "acquisition_coordination_store",
        (
            (
                "acquisition_connectivity_store",
                "observation_work_order_store",
                "mission_store",
            ),
        ),
        "acquisition_coordination_store는 connectivity, WorkOrder, Mission 원장과 함께 "
        "주어져야 한다(REQ-WRK-101, REQ-MSN-101) — 조정 원장은 기존 사실 원장을 "
        "복제하거나 미확인 장비 상태를 만들지 않는다",
    ),
    (
        "capture_quality_report_store",
        (("mission_store", "observation_work_order_store", "acquisition_coordination_store"),),
        "capture_quality_report_store는 Mission·WorkOrder·AcquisitionRun 원장과 함께 "
        "주어져야 한다(REQ-ACQ-102, INV-017) — Edge의 품질 측정을 어느 회차/임무에 "
        "귀속하는지 대조하지 못하는 조립은 허용하지 않는다",
    ),
    ("copilot_service", (), ""),
    (
        "copilot_conversation_service",
        (("copilot_service", "site_store"),),
        "copilot_conversation_service는 Copilot과 조직-scoped Site 원장과 함께 "
        "주어져야 한다(INV-060/061)",
    ),
    (
        "site_workspace_projector",
        (("site_store", "observation_work_order_store"),),
        "site_workspace_projector는 Site·WorkOrder 사실 원장과 함께 주어져야 한다",
    ),
    (
        "civil_readiness_projector",
        (("site_store", "processing_job_store", "design_surface_store"),),
        "civil_readiness_projector는 Site·ProcessingJob·DesignSurface 원장과 함께 주어져야 한다"
        "(REQ-INT-104, INV-053) — 읽기 모델이 임의의 비교 가능 상태를 만들면 안 된다",
    ),
    (
        "site_briefing_service",
        (("copilot_service", "site_workspace_projector"),),
        "site_briefing_service는 grounded Copilot과 SiteWorkspace projection이 필요하다",
    ),
    (
        "design_surface_store",
        (("site_store",),),
        "design_surface_store 는 site_store 와 함께 주어져야 한다"
        " — 설계 기준면은 '어느 현장의 계획고인가'로만 의미를 갖고, 객체 키도"
        " siteId 를 필요로 한다. 등록된 적 없는 현장의 설계면을 받으면 그"
        " 파일은 어느 비교에도 쓰이지 못한 채 원장에만 쌓인다"
        " (source_media_store 와 동일 원칙)",
    ),
    (
        "processing_job_store",
        (("source_media_store", "site_store", "evidence_storage"),),
        "processing_job_store 는 source_media_store·site_store·evidence_storage 와"
        " 함께 주어져야 한다(ADR-KSI-012, INV-050) — 처리 작업의 입력(장수·화소·"
        "digest)은 봉인된 번들이 정하고 반출 허용 여부는 현장이 정한다. 하나라도"
        " 없으면 그 값들을 요청이 스스로 주장하는 구성이 되므로 조립하지 않는다."
        " evidence_storage 는 워커가 원본을 받아갈 다운로드 URL 발급에 필요하다"
        " — 없으면 워커가 바이트를 읽을 수 없어 실측 대조가 성립하지 않고,"
        " 그러면 SUCCEEDED 게이트가 영구히 닫힌 조립이 된다",
    ),
    (
        "checkpoint_validation_store",
        (("mission_store", "processing_job_store", "evidence_storage"),),
        "checkpoint_validation_store 는 mission_store·processing_job_store·"
        "evidence_storage 와 함께 주어져야 한다(INV-024/053) — 봉인 checkpoint와 "
        "immutable DSM 산출물을 대조할 원장·객체 저장소 없이 검증 표면을 열지 않는다",
    ),
    (
        "defect_candidate_store",
        (("mission_store", "source_media_store"),),
        "defect_candidate_store 는 mission_store·source_media_store 와 함께 주어져야"
        " 한다 — 결함 후보는 '어느 임무의 어느 사진 위 좌표인가'로만 의미를 갖는다."
        " 참조 대상을 대조할 저장소가 없으면 서버는 그릴 수 없는 도형을 원장에"
        " 쌓게 되고, 그건 조회 시점에 정상으로 보인다(defect_candidates.py"
        " '서버는 후보를 그대로 받아 적지 않는다')",
    ),
    (
        "change_detection_store",
        (("mission_store", "processing_job_store"),),
        "change_detection_store 는 mission_store·processing_job_store 와 함께"
        " 주어져야 한다 — 변화 탐지 결과는 '어느 두 point cloud 산출물을"
        " 비교했나'로만 해석 가능하다. 그 참조를 대조할 작업 원장이 없으면"
        " '변화가 있었다'가 아무도 재현할 수 없는 주장이 된다"
        " (change_detection.py '서버가 검증하는 것')",
    ),
    (
        "volume_change_store",
        (("mission_store", "processing_job_store"),),
        "volume_change_store 는 mission_store·processing_job_store 와 함께"
        " 주어져야 한다 — 체적 리포트는 '어느 두 DSM 산출물을 비교했나'로만"
        " 해석 가능하다. 그 참조를 대조할 작업 원장이 없으면 '이만큼 깎였다'가"
        " 아무도 재현할 수 없는 주장이 되고, 그 숫자는 정산·분쟁의 근거로"
        " 쓰인다 (volume_reports.py '사람은 체적을 주장할 수 없다')",
    ),
    (
        "comparison_request_store",
        (("mission_store", "processing_job_store", "evidence_storage"),),
        "comparison_request_store 는 mission_store·processing_job_store·"
        "evidence_storage 와 함께 주어져야 한다 — 비교 요청은 '어느 두 처리"
        " 작업을 비교하는가'로만 해석 가능하고, 워커가 그 산출물을 읽어갈"
        " presigned URL 을 발급할 스토리지가 없으면 워커가 원본에 닿을 수"
        " 없다(comparison_requests.py 모듈 docstring)",
    ),
    (
        "design_conformance_request_store",
        (
            (
                "mission_store",
                "processing_job_store",
                "design_surface_store",
                "evidence_storage",
            ),
        ),
        "design_conformance_request_store 는 mission_store·processing_job_store·"
        "design_surface_store·evidence_storage 와 함께 주어져야 한다 — 설계 대비"
        " 요청은 '검증된 어느 설계면을, 어느 처리 작업의 지형과' 로만 해석 가능하다."
        " 설계면 원장이 없으면 VERIFIED 여부를 대조할 수 없어 미검증 자산으로"
        " 계산이 시작되고, 스토리지가 없으면 워커가 두 입력 바이트를 읽을 수도"
        " 차분 래스터를 올릴 수도 없다(comparison_request_store 와 동일 원칙)",
    ),
    (
        "design_conformance_report_store",
        (
            (
                "mission_store",
                "processing_job_store",
                "design_conformance_request_store",
                "evidence_storage",
            ),
        ),
        "design_conformance_report_store 는 mission_store·processing_job_store·"
        "design_conformance_request_store·evidence_storage 와 함께 주어져야 한다"
        " — 이 원장은 리포트를 받을 때 **차분 래스터 바이트를 직접 다시 해싱해**"
        " 워커의 신고와 대조하고(design_conformance_reports.py 모듈 docstring),"
        " 그 대조에 요청 원장(무엇을 지시했나)과 오브젝트 스토리지(실제 바이트)가"
        " 둘 다 필요하다. 하나라도 없으면 워커의 자기보고가 그대로 원장이 되고,"
        " 그러면 '유효한 리포트가 있는데 그 지도는 다른 파일'이 성립한다",
    ),
    (
        "report_export_store",
        (("site_store", "design_conformance_report_store"),),
        "report_export_store 는 site_store·design_conformance_report_store 와 함께 "
        "주어져야 한다(INV-053/060, ADR-KSI-008) — export audit 는 인증 조직의 "
        "현장과 Core가 확인한 설계 대비 report snapshot을 다시 대조해야 하며, "
        "둘 중 하나가 없으면 브라우저의 자기신고를 durable 원장에 적게 된다",
    ),
    (
        "region_extraction_request_store",
        (
            (
                "mission_store",
                "design_conformance_report_store",
                "evidence_storage",
            ),
        ),
        "region_extraction_request_store 는 mission_store·design_conformance_report_"
        "store·evidence_storage 와 함께 주어져야 한다 — 변화 영역 추출 요청은 'RECORDED"
        " 된 어느 설계 대비 잔량 리포트에서 뽑으라는 지시인가'로만 해석 가능하고,"
        " 워커가 그 diffRaster 를 읽어갈 presigned URL 을 발급할 스토리지가 없으면 이"
        " 표면 자체가 성립하지 않는다(design_conformance_request_store 와 동일한"
        " fail-closed 조립 원칙)",
    ),
    (
        "region_extraction_report_store",
        (
            (
                "mission_store",
                "design_conformance_report_store",
                "region_extraction_request_store",
            ),
        ),
        "region_extraction_report_store 는 mission_store·design_conformance_report_"
        "store·region_extraction_request_store 와 함께 주어져야 한다 — 이 원장은"
        " 리포트를 받을 때 요청 원장과 원본 설계 대비 잔량 리포트를 대조해서만"
        " 기록한다(region_extraction_reports.py 모듈 docstring). 하나라도 없으면 그"
        " 대조가 성립하지 않는다",
    ),
    (
        "equipment_state_store",
        (("site_store",),),
        "equipment_state_store 는 site_store 와 함께 주어져야 한다 — 위치·속도는"
        " 좌표계 없이는 숫자일 뿐이고, 현장 등록 좌표계와 대조할 저장소가 없으면"
        " 서로 다른 기준계의 점 사이 거리를 재는 CPA/TTC 가 성립해 버린다"
        " (equipment_states.py EquipmentStateStore._judge)",
    ),
    # 아래 넷은 결합 검증이 없다(다른 store 를 요구하지 않는다) — protected_surface
    # 판정에만 참여한다.
    ("event_store", (), ""),
    ("site_store", (), ""),
    ("mission_store", (), ""),
    ("mission_sequence_store", (), ""),
    ("equipment_support_store", (), ""),
    ("runtime_capability_projector", (), ""),
)


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
    external_reconstruction_store: ExternalReconstructionStore | None = None,
    external_evidence_store: ExternalEvidenceStore | None = None,
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

    if (mission_signing_key is not None or mission_signing_key_id is not None) and (
        mission_signing_key is None or mission_signing_key_id is None
    ):
        raise ValueError(
            "mission_signing_key와 mission_signing_key_id는 함께 주어져야 한다"
            " — 절반만 있는 서명 설정으로 조립하지 않는다"
        )
    if mission_contract_writer_version not in ("1.2", "1.3"):
        raise ValueError("mission_contract_writer_version은 '1.2' 또는 '1.3'이어야 한다")
    if mission_contract_writer_version == "1.3" and (
        mission_signing_key is None
        or mission_contract_issuer_id is None
        or mission_sequence_store is None
    ):
        raise ValueError(
            "Mission Contract v1.3 writer는 서명키·Core issuerId·durable sequence store가 "
            "모두 필요하다"
        )
    if acquisition_issue_gate_enabled and acquisition_connectivity_store is None:
        raise ValueError(
            "acquisition_issue_gate_enabled에는 acquisition_connectivity_store가 필요하다"
        )

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
        "external_reconstruction_store": external_reconstruction_store,
        "external_evidence_store": external_evidence_store,
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

    for _store_name, _requirement_groups, _reason in _ASSEMBLY_REQUIREMENTS:
        if _provided[_store_name] is None:
            continue
        if _requirement_groups and not any(
            all(_provided[_dep] is not None for _dep in _group) for _group in _requirement_groups
        ):
            raise ValueError(_reason)

    if external_reconstruction_store is not None:
        from ksi_core.evidence import DigestBoundEvidenceStorage, ObjectStorageObservationPort

        if not isinstance(evidence_storage, DigestBoundEvidenceStorage) or not isinstance(
            evidence_storage, ObjectStorageObservationPort
        ):
            raise ValueError(
                "external_reconstruction_store 는 digest-bound PUT와 trusted object observation "
                "storage ports를 모두 요구한다"
            )

    if external_evidence_store is not None and (
        external_reconstruction_store is None
        or observation_work_order_store is None
        or evidence_storage is None
    ):
        raise ValueError(
            "external_evidence_store 는 external_reconstruction_store·"
            "observation_work_order_store·evidence_storage 를 모두 요구한다"
        )

    protected_surface = any(value is not None for value in _provided.values())
    if protected_surface and auth_registry is None:
        raise ValueError(
            "보호 표면(edge_sync_store·edge_dispatch_store·event_store·site_store·"
            "mission_store·서명키·"
            "커버리지 보고·Copilot)을 하나라도 주입하려면 auth_registry 가 필수다"
            "(ADR-KSI-008 §3)"
            " — 인증 없는"
            " 보호 표면은 존재할 수 없다"
        )

    # ── 장착(순서: 인증 → site → edge-sync/events → mission 발급 → mission 조회) ──

    if auth_registry is not None:
        from ksi_core.auth import mount_auth

        mount_auth(
            app,
            auth_registry,
            human_auth_mode=human_auth_mode,
            oidc_verifier=oidc_verifier,
        )

    if runtime_capability_projector is not None:
        from ksi_core.capability.runtime_api import mount_runtime_capability

        mount_runtime_capability(
            app,
            runtime_capability_projector,
            mission_store=mission_store,
            mission_execution_store=mission_execution_store,
        )

    if site_store is not None:
        from ksi_core.sites import mount_sites

        mount_sites(app, site_store, processing_job_store)

    if observation_work_order_store is not None:
        from ksi_core.observation_work_orders import mount_observation_work_orders

        def _on_work_order_approved(order: Any, actor: str, now: Any) -> None:
            if acquisition_coordination_store is not None:
                acquisition_coordination_store.ensure_run(order, actor=actor, now=now)

        mount_observation_work_orders(
            app,
            observation_work_order_store,
            on_approved=(
                _on_work_order_approved if acquisition_coordination_store is not None else None
            ),
        )

    if external_reconstruction_store is not None:
        from ksi_core.external_reconstruction import mount_external_reconstruction

        assert observation_work_order_store is not None  # noqa: S101 -- assembly requirement
        assert evidence_storage is not None  # noqa: S101 -- assembly requirement
        mount_external_reconstruction(
            app,
            external_reconstruction_store,
            work_orders=observation_work_order_store,
            storage=evidence_storage,
        )

    if external_evidence_store is not None:
        from ksi_core.external_evidence import mount_external_evidence

        assert external_reconstruction_store is not None  # noqa: S101 -- assembly guard
        assert observation_work_order_store is not None  # noqa: S101 -- assembly guard
        assert evidence_storage is not None  # noqa: S101 -- assembly guard
        mount_external_evidence(
            app,
            external_evidence_store,
            reconstruction=external_reconstruction_store,
            work_orders=observation_work_order_store,
            storage=evidence_storage,
        )

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

    if event_store is not None:
        from ksi_core.events import mount_events

        # edge_sync_store 유무와 무관하게 /v1/events 조회·트리아지 표면은 event_store
        # 가 있으면 항상 장착된다 — edge 수신이 있는 배포에서도 트리아지 화면이
        # 필요하다(mount_edge_sync 는 ingest 라우터만 소유한다).
        # evidence_storage 가 없으면 증거 경로는 장착되지 않는다(404) — 스토리지
        # 없이 라우트만 살려두면 "업로드했는데 어디에도 없다"가 2xx 로 보인다
        # (ADR-KSI-010 §1).
        mount_events(app, event_store, evidence_storage=evidence_storage)

    if mission_signing_key is not None:
        # 위 결합 검증이 mission_signing_key_id·mission_store·site_store 를
        # 전부 non-None 으로 보장한다.
        assert mission_signing_key_id is not None  # noqa: S101
        assert mission_store is not None  # noqa: S101
        assert site_store is not None  # noqa: S101

        from ksi_core.mission_atomicity import MissionIssuanceCommitter
        from ksi_core.mission_issuance import mount_mission_issuance
        from ksi_core.mission_plans import mount_mission_plans

        _mission_store = mission_store
        issuance_committer = MissionIssuanceCommitter(
            site_store=site_store,
            mission_store=_mission_store,
            work_order_store=observation_work_order_store,
            acquisition_store=acquisition_connectivity_store,
            acquisition_issue_gate_enabled=acquisition_issue_gate_enabled,
        )

        mount_mission_issuance(
            app,
            private_key=mission_signing_key,
            key_id=mission_signing_key_id,
            mission_store=_mission_store,
            issuance_committer=issuance_committer,
            writer_version=mission_contract_writer_version,
            issuer_id=mission_contract_issuer_id,
            sequence_store=mission_sequence_store,
        )
        mount_mission_plans(
            app,
            private_key=mission_signing_key,
            key_id=mission_signing_key_id,
            mission_store=_mission_store,
            issuance_committer=issuance_committer,
            # 스토리지가 있으면 발급 KMZ 바이트를 보관한다 — 서버 안전상수 한 줄이
            # 바뀌면 그 이전 발급분 전량이 영구 409 가 되던 경로를 닫는다(risk
            # kmz-regeneration-determinism-timebomb). 없으면 재생성에만 의존한다.
            kmz_storage=evidence_storage,
            writer_version=mission_contract_writer_version,
            issuer_id=mission_contract_issuer_id,
            sequence_store=mission_sequence_store,
            observation_work_order_store=observation_work_order_store,
            acquisition_coordination_store=acquisition_coordination_store,
        )

    if mission_store is not None:
        from ksi_core.mission_records import mount_mission_records

        # coverage_report_store 는 mission_store 보다 늦게(279행) 조건부 장착되지만,
        # 이 시점에 이미 함수 인자로 들어와 있다(결합 검증이 mission_store 동반을
        # 보장) — 목록/상세 응답에 파생 커버리지 필드를 싣기 위해 여기서 넘긴다.
        mount_mission_records(
            app, mission_store=mission_store, coverage_report_store=coverage_report_store
        )

    if flight_artifact_store is not None:
        from ksi_core.flight_artifacts import mount_flight_artifacts

        mount_flight_artifacts(app, flight_artifact_store)

    if coverage_report_store is not None:
        from ksi_core.coverage_reports import mount_coverage_reports

        mount_coverage_reports(app, coverage_report_store, mission_execution_store)

    if mission_execution_store is not None:
        # 임무 실행 생애주기(ADR-KSI-019 G2) — 발급 기록만으로는 "이 임무가 실제로
        # 날았는가"에 답할 수 없다. 이 표면이 그 축을 연다.
        from ksi_core.mission_execution import mount_mission_execution

        mount_mission_execution(
            app,
            mission_execution_store,
            mission_store=mission_store,
            # 운영자의 "기체로 넘겼다" 선언이 매핑 계열이면 현장도 함께 전진한다.
            site_lifecycle=site_lifecycle,
        )

    if source_media_store is not None and evidence_storage is not None:
        # evidence_storage 없이는 라우트를 장착하지 않는다(evidence 라우트와 같은
        # 관습) — presigned URL 을 낼 스토리지가 없으면 "업로드했는데 어디에도
        # 없다"가 2xx 로 보이는 경로를 만들지 않는다. store 자체(journal)는
        # evidence_storage 없이도 구성될 수 있지만(위 결합 검증은 mission_store만
        # 요구), 그 경우 이 표면은 존재하지 않는다.
        from ksi_core.source_media import mount_source_media

        mount_source_media(app, source_media_store, evidence_storage)

    if design_surface_store is not None and evidence_storage is not None:
        # source_media 와 같은 관습 — presigned URL 을 낼 스토리지가 없으면 이
        # 표면 자체가 존재하지 않는다(등록만 받고 올릴 곳이 없는 구성을 만들지
        # 않는다). store 자체는 evidence_storage 없이도 구성될 수 있다.
        from ksi_core.design_surfaces import mount_design_surfaces

        mount_design_surfaces(
            app,
            design_surface_store,
            evidence_storage,
            landxml_ingress_enabled=landxml_ingress_enabled,
        )

    if processing_job_store is not None:
        # evidence_storage 는 위 결합 검증이 이미 보장한다(워커가 원본을 받아갈
        # 다운로드 URL 발급에 필요 — GET .../input).
        assert evidence_storage is not None  # noqa: S101 -- 위 결합 검증의 사후조건
        from ksi_core.processing_jobs import mount_processing_jobs

        mount_processing_jobs(app, processing_job_store, evidence_storage, site_lifecycle)
    elif auth_registry is not None:
        # 처리 실행 표면은 evidence storage 없이는 계속 404다. 다만 Resource Policy는
        # tenant 데이터나 실행 상태가 아닌 Core 전역의 고정 admission envelope다.
        # 인증된 축소 조립(dev/E2E 포함)에서도 이를 조회할 수 있어야 Dashboard가
        # "정책을 모름"과 "실행 인프라가 없음"을 혼동하지 않는다. 수정 API는 없고,
        # processing_job_store가 있는 조립은 위에서 같은 store registry를 노출한다.
        from ksi_core.processing_jobs import build_processing_resource_policies_router
        from ksi_core.processing_resource_policy import ProcessingResourcePolicyRegistry

        app.include_router(
            build_processing_resource_policies_router(ProcessingResourcePolicyRegistry())
        )

    if checkpoint_validation_store is not None:
        # evidence_storage 는 위 결합 검증이 보장한다. 등록 flag가 false여도 sealed
        # 증거의 조회·worker 검증 표면은 유지한다; 신규 operator 등록만 닫는다.
        assert evidence_storage is not None  # noqa: S101 -- assembly postcondition
        from ksi_core.checkpoint_validations import mount_checkpoint_validations

        mount_checkpoint_validations(
            app,
            checkpoint_validation_store,
            evidence_storage,
            registration_enabled=checkpoint_validation_registration_enabled,
        )

    if site_store is not None and processing_job_store is not None:
        # 공간모델 조회(ADR-KSI-019 G1)는 **두 저장소가 모두 있을 때만** 장착한다 —
        # 재구성 원장이 없는 조립에서 이 표면을 열면 모든 현장이 영원히 ABSENT 라고
        # 답하는 거짓 표면이 된다. 없는 편이 정직하다(source_media·evidence 라우트가
        # 같은 이유로 이미 그렇게 동작한다).
        from ksi_core.spatial_model import mount_spatial_model

        mount_spatial_model(
            app,
            site_store=site_store,
            processing_job_store=processing_job_store,
            # 노후 스윕 표면도 함께 장착한다 — 주기 실행은 배포 운영이 소유한다.
            lifecycle=site_lifecycle,
        )

    if defect_candidate_store is not None:
        from ksi_core.defect_candidates import mount_defect_candidates

        mount_defect_candidates(app, defect_candidate_store)

    if change_detection_store is not None:
        from ksi_core.change_detection import mount_change_detection

        mount_change_detection(app, change_detection_store)

    if volume_change_store is not None:
        from ksi_core.volume_reports import mount_volume_reports

        mount_volume_reports(app, volume_change_store)

    if comparison_request_store is not None:
        # evidence_storage 는 위 결합 검증이 이미 보장한다(워커가 원본을 받아갈
        # presigned URL 발급에 필요 — GET .../input, processing_job_store 와 동일 근거).
        assert evidence_storage is not None  # noqa: S101 -- 위 결합 검증의 사후조건
        from ksi_core.comparison_requests import mount_comparison_requests

        mount_comparison_requests(app, comparison_request_store, evidence_storage)

    if design_conformance_request_store is not None:
        # evidence_storage 는 위 결합 검증이 이미 보장한다(워커가 설계면·DSM 을
        # 읽어갈 presigned GET 과 차분 래스터 업로드 PUT 을 이 표면이 발급한다).
        assert evidence_storage is not None  # noqa: S101 -- 위 결합 검증의 사후조건
        from ksi_core.design_conformance_requests import mount_design_conformance_requests

        # region_extraction_request_store 는 design_conformance_report_store 뒤에만
        # 만들어지므로(아래 참조) 이 시점엔 아직 None 일 수 있다 — 그래도 안전하다,
        # mount_design_conformance_requests 의 자동 연동은 optional 이라 나중에
        # 다시 장착하지 않는다(성공 전이마다 그 값을 다시 읽지 않고 라우터 생성
        # 시점에 한 번 닫힌다는 뜻 — 그래서 이 아래에서 순서를 보장한다: region
        # extraction 관련 store 조립은 app_assembly.py 에서 이미 design_conformance
        # 계열보다 먼저 끝나 있고, create_app 은 그 결과를 인자로 받을 뿐이다).
        mount_design_conformance_requests(
            app,
            design_conformance_request_store,
            evidence_storage,
            region_extraction_store=region_extraction_request_store,
        )

    if design_conformance_report_store is not None:
        # 같은 사후조건 — 이 표면은 리포트를 받을 때 스토리지 바이트를 직접 읽는다.
        assert evidence_storage is not None  # noqa: S101 -- 위 결합 검증의 사후조건
        from ksi_core.design_conformance_reports import mount_design_conformance_reports

        mount_design_conformance_reports(app, design_conformance_report_store, evidence_storage)
        # 진척(M4-C)은 같은 원장을 읽는 파생 조회다 — 별도 store 를 만들지 않고
        # 리포트 저장소 위에 라우터만 얹는다. 작업구역 저장소는 구역 이름을 붙이는
        # 데만 쓰이므로 없어도 표는 나온다(zoneId 만 보인다).
        from ksi_core.design_progress import mount_design_progress

        mount_design_progress(app, design_conformance_report_store, work_area_store)

    if report_export_store is not None:
        from ksi_core.report_exports import mount_report_exports

        mount_report_exports(app, report_export_store)

    if region_extraction_request_store is not None:
        # evidence_storage 는 위 결합 검증이 이미 보장한다(워커가 diffRaster 를
        # 읽어갈 presigned GET 을 이 표면이 발급한다).
        assert evidence_storage is not None  # noqa: S101 -- 위 결합 검증의 사후조건
        assert design_conformance_report_store is not None  # noqa: S101 -- 위 결합 검증의 사후조건
        from ksi_core.region_extraction_requests import mount_region_extraction_requests

        mount_region_extraction_requests(
            app, region_extraction_request_store, design_conformance_report_store, evidence_storage
        )

    if region_extraction_report_store is not None:
        from ksi_core.region_extraction_reports import mount_region_extraction

        mount_region_extraction(app, region_extraction_report_store)

    if work_area_store is not None:
        from ksi_core.work_areas import mount_work_areas

        mount_work_areas(app, work_area_store)

    if equipment_state_store is not None:
        from ksi_core.equipment_states import mount_equipment_states

        mount_equipment_states(app, equipment_state_store)

    if equipment_support_store is not None:
        from ksi_core.equipment_support import mount_equipment_support

        mount_equipment_support(app, equipment_support_store)

    return app
