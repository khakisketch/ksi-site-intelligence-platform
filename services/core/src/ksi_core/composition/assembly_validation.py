"""Fail-closed application assembly validation.

The requirement table remains ordered because its order is an observable error
contract when more than one invalid dependency is supplied.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
        "organization_work_roster_store",
        (),
        "",
    ),
    (
        "work_inbox_store",
        (("organization_work_roster_store", "observation_work_order_store"),),
        "work_inbox_store requires the durable roster and WorkOrder journals",
    ),
    (
        "external_reconstruction_store",
        (("site_store", "observation_work_order_store", "evidence_storage"),),
        "external_reconstruction_store 는 site_store·observation_work_order_store·"
        "evidence_storage 와 함께 주어져야 한다(INV-051/053/060) — 외부 결과는 "
        "managed job·source authority와 분리된 scoped declaration으로만 존재한다",
    ),
    (
        "external_evidence_store",
        (("external_reconstruction_store", "observation_work_order_store", "evidence_storage"),),
        "external_evidence_store 는 external_reconstruction_store·"
        "observation_work_order_store·evidence_storage 를 모두 요구한다",
    ),
    (
        "external_evidence_validation_store",
        (
            (
                "external_evidence_store",
                "external_reconstruction_store",
                "observation_work_order_store",
                "evidence_storage",
            ),
        ),
        "external_evidence_validation_store 는 sealed evidence·reconstruction·"
        "work-order scope·worker byte storage를 함께 요구한다",
    ),
    (
        "external_use_evaluator",
        (
            (
                "external_reconstruction_store",
                "external_evidence_validation_store",
                "external_artifact_inspection_store",
                "observation_work_order_store",
            ),
        ),
        "external_use_evaluator 는 sealed reconstruction·validated evidence·"
        "inspection·work-order scope를 함께 요구한다",
    ),
    (
        "external_relative_volume_store",
        (
            (
                "external_use_evaluator",
                "observation_work_order_store",
                "external_volume_input_capability_issuer",
            ),
        ),
        "external_relative_volume_store requires scoped external use authority "
        "and byte capabilities",
    ),
    (
        "external_result_workflow_service",
        (
            (
                "external_relative_volume_store",
                "observation_work_order_store",
                "site_store",
                "work_area_store",
            ),
        ),
        "external result workflow requires its durable volume, work-order, site and area graph",
    ),
    (
        "external_result_read_projector",
        (("external_result_workflow_service", "external_relative_volume_store"),),
        "external result read projection requires the exact durable workflow graph",
    ),
    (
        "external_volume_input_capability_issuer",
        (("external_relative_volume_store",),),
        "external relative volume byte capabilities require the durable request store",
    ),
    (
        "external_display_artifact_store",
        (
            (
                "external_reconstruction_store",
                "observation_work_order_store",
                "external_artifact_inspection_store",
                "evidence_storage",
            ),
        ),
        "external_display_artifact_store 는 external_reconstruction_store·"
        "observation_work_order_store·external_artifact_inspection_store·"
        "evidence_storage와 함께만 조립된다",
    ),
    (
        "external_artifact_inspection_store",
        (
            (
                "external_reconstruction_store",
                "observation_work_order_store",
                "external_display_artifact_store",
                "evidence_storage",
            ),
        ),
        "external_artifact_inspection_store 는 external_reconstruction_store·"
        "observation_work_order_store·external_display_artifact_store·"
        "evidence_storage와 함께만 조립된다",
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
        "site_briefing_store",
        (("site_store",),),
        "site_briefing_store는 site_store와 함께 주어져야 한다"
        " — 브리핑은 조직-scoped Site에만 귀속된다",
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


def validate_assembly_requirements(
    *,
    provided: Mapping[str, Any],
    mission_signing_key: Any,
    mission_signing_key_id: str | None,
    mission_contract_writer_version: str,
    mission_contract_issuer_id: str | None,
    mission_sequence_store: Any,
    acquisition_issue_gate_enabled: bool,
    auth_registry: Any,
) -> None:
    """Reject invalid assembly dependency combinations in legacy order."""
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
    if acquisition_issue_gate_enabled and provided["acquisition_connectivity_store"] is None:
        raise ValueError(
            "acquisition_issue_gate_enabled에는 acquisition_connectivity_store가 필요하다"
        )

    for store_name, requirement_groups, reason in _ASSEMBLY_REQUIREMENTS:
        if provided[store_name] is None:
            continue
        if requirement_groups and not any(
            all(provided[dependency] is not None for dependency in group)
            for group in requirement_groups
        ):
            raise ValueError(reason)

    external_reconstruction_store = provided["external_reconstruction_store"]
    evidence_storage = provided["evidence_storage"]
    if external_reconstruction_store is not None:
        from ksi_core.evidence import DigestBoundEvidenceStorage, ObjectStorageObservationPort

        if not isinstance(evidence_storage, DigestBoundEvidenceStorage) or not isinstance(
            evidence_storage, ObjectStorageObservationPort
        ):
            raise ValueError(
                "external_reconstruction_store 는 digest-bound PUT와 trusted object observation "
                "storage ports를 모두 요구한다"
            )

    if any(value is not None for value in provided.values()) and auth_registry is None:
        raise ValueError(
            "보호 표면(edge_sync_store·edge_dispatch_store·event_store·site_store·"
            "mission_store·서명키·"
            "커버리지 보고·Copilot)을 하나라도 주입하려면 auth_registry 가 필수다"
            "(ADR-KSI-008 §3)"
            " — 인증 없는"
            " 보호 표면은 존재할 수 없다"
        )
