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
from ksi_event_contracts.work_area import WorkAreaStatus

from ksi_core.auth import HumanAuthMode
from ksi_core.capability.runtime_projection import (
    RuntimeRouteFreshnessPolicyV1,
    TrustedRuntimeRouteConfigurationV1,
)
from ksi_core.change_detection import ChangeDetectionStore
from ksi_core.composition.analysis_graph import build_analysis_graph
from ksi_core.composition.app_factory import create_app
from ksi_core.composition.base_graph import build_base_graph
from ksi_core.composition.capability_graph import build_capability_graph
from ksi_core.composition.external_graph import (
    build_external_pre_work_order_graph,
    complete_external_graph,
)
from ksi_core.composition.runtime_surfaces import mount_runtime_surfaces
from ksi_core.composition.workspace_graph import build_workspace_graph
from ksi_core.defect_candidates import DefectCandidateStore
from ksi_core.durable_journal import DurableJournal
from ksi_core.equipment_states import EquipmentStateStore
from ksi_core.equipment_support import EquipmentSupportStore
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_result_workflow_assembly import ExternalResultWorkflowAssemblyConfig
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.organization_work_roster import OrganizationWorkRosterStore
from ksi_core.volume_reports import VolumeChangeStore

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

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
    processing_profile_issuance_enabled: bool = True,
    landxml_ingress_enabled: bool = False,
    checkpoint_validation_registration_enabled: bool = False,
    capability_freshness_policies: Mapping[str, RuntimeRouteFreshnessPolicyV1] | None = None,
    runtime_route_configurations: tuple[TrustedRuntimeRouteConfigurationV1, ...] = (),
    copilot_runtime_config: CopilotRuntimeConfig | None = None,
    external_result_workflow: ExternalResultWorkflowAssemblyConfig | None = None,
    expose_docs: bool = True,
) -> FastAPI:
    """모든 store 를 조립하고 ``create_app`` 을 호출한다 — dev/production 공용.

    ``data_dir`` 은 호출자가 이미 만들어 뒀다고 가정한다(``run_core_dev.py`` 의
    ``build_dev_app`` 관습과 동일). 원장을 여는 것은 ``journal`` 클로저의 몫이고,
    호출자는 조립 실패 시 ``opened`` 에 누적된 원장을 전부 닫을 책임을 진다
    (``build_dev_app``/``production.build_production_app`` 양쪽이 이 관습을 따른다).
    """
    external_authority_currentness = ExternalAuthorityCurrentnessCoordinator()
    evidence_context_authority = None
    policy_authority_currentness = None
    if external_result_workflow is not None:
        build_policy_currentness = external_result_workflow.build_policy_authority_currentness
        if build_policy_currentness is not None:
            policy_authority_currentness = build_policy_currentness(external_authority_currentness)
            if (
                policy_authority_currentness is None
                or policy_authority_currentness.coordinator is not external_authority_currentness
            ):
                raise ValueError(
                    "external result workflow policy currentness must share the Core coordinator"
                )
        build_context_authority = external_result_workflow.build_evidence_context_authority
        if build_context_authority is not None:
            evidence_context_authority = build_context_authority(external_authority_currentness)
            if (
                evidence_context_authority is None
                or evidence_context_authority.coordinator is not external_authority_currentness
            ):
                raise ValueError(
                    "external result workflow context authority must share the Core coordinator"
                )
    base = build_base_graph(
        data_dir=data_dir,
        journal=journal,
        opened=opened,
        edge_sync_snapshot_every=edge_sync_snapshot_every,
        evidence_storage=evidence_storage,
        mission_signing_key=mission_signing_key,
        mission_signing_key_id=mission_signing_key_id,
        risk_policy_packs=risk_policy_packs,
        edge_runtime_profiles=edge_runtime_profiles,
        processing_profile_issuance_enabled=processing_profile_issuance_enabled,
        coordinator=external_authority_currentness,
    )
    mission_store = base.mission_store
    mission_sequence_store = base.mission_sequence_store
    event_journal = base.event_journal
    edge_sync_store = base.edge_sync_store
    flight_artifact_store = base.flight_artifact_store
    mission_execution_store = base.mission_execution_store
    edge_dispatch_store = base.edge_dispatch_store
    coverage_report_store = base.coverage_report_store
    source_media_store = base.source_media_store
    site_store = base.site_store
    processing_job_store = base.processing_job_store
    checkpoint_validation_store = base.checkpoint_validation_store
    design_surface_store = base.design_surface_store
    work_area_store = base.work_area_store
    defect_candidate_journal = base.defect_candidate_journal
    change_detection_journal = base.change_detection_journal
    volume_change_journal = base.volume_change_journal
    comparison_request_journal = base.comparison_request_journal

    external_pre_work_order = build_external_pre_work_order_graph(
        journal=journal,
        evidence_storage=evidence_storage,
        external_result_workflow=external_result_workflow,
        work_area_store=work_area_store,
        site_store=site_store,
        coordinator=external_authority_currentness,
        policy_authority_currentness=policy_authority_currentness,
        evidence_context_authority=evidence_context_authority,
    )
    external_reconstruction_store = external_pre_work_order.reconstruction_store
    external_evidence_store = external_pre_work_order.evidence_store
    external_validation_policy_registry = external_pre_work_order.validation_policy_registry
    external_evidence_validation_store = external_pre_work_order.evidence_validation_store
    external_display_artifact_store = external_pre_work_order.display_artifact_store
    external_artifact_inspection_store = external_pre_work_order.artifact_inspection_store
    external_volume_mapping = external_pre_work_order.volume_mapping
    external_use_decision_store = external_pre_work_order.use_decision_store
    external_use_evaluator = external_pre_work_order.use_evaluator
    external_relative_volume_store = external_pre_work_order.relative_volume_store
    external_volume_execution_activator = external_pre_work_order.volume_execution_activator
    external_volume_input_capability_issuer = external_pre_work_order.volume_input_capability_issuer

    organization_work_roster_store = OrganizationWorkRosterStore(
        journal("organization-work-roster.jsonl"), coordinator=external_authority_currentness
    )
    observation_work_order_journal = journal("observation-work-orders.jsonl")
    observation_work_order_store = ObservationWorkOrderStore(
        observation_work_order_journal,
        external_reobservation_authority_port=external_pre_work_order.proposal_authority,
        operations_coordinator=external_authority_currentness,
        assignment_member_is_active=organization_work_roster_store.is_assignable_member,
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
    external_completed = complete_external_graph(
        pre_work_order=external_pre_work_order,
        observation_work_order_store=observation_work_order_store,
        site_store=site_store,
        work_area_store=work_area_store,
        coordinator=external_authority_currentness,
    )
    external_result_workflow_service = external_completed.result_workflow_service
    external_result_read_projector = external_completed.result_read_projector

    workspace = build_workspace_graph(
        journal=journal,
        coordinator=external_authority_currentness,
        observation_work_order_store=observation_work_order_store,
        organization_work_roster_store=organization_work_roster_store,
        site_store=site_store,
        mission_store=mission_store,
        coverage_report_store=coverage_report_store,
        source_media_store=source_media_store,
        processing_job_store=processing_job_store,
        design_surface_store=design_surface_store,
        external_result_read_projector=external_result_read_projector,
        external_relative_volume_store=external_relative_volume_store,
        acquisition_coordination_enabled=acquisition_coordination_enabled,
        copilot_runtime_config=copilot_runtime_config,
        event_journal=event_journal,
    )
    work_inbox_store = workspace.work_inbox_store
    acquisition_connectivity_store = workspace.acquisition_connectivity_store
    acquisition_coordination_store = workspace.acquisition_coordination_store
    capture_quality_report_store = workspace.capture_quality_report_store
    event_store = workspace.event_store
    site_workspace_projector = workspace.site_workspace_projector
    civil_readiness_projector = workspace.civil_readiness_projector
    copilot_service = workspace.copilot_service
    copilot_conversation_service = workspace.copilot_conversation_service
    site_briefing_service = workspace.site_briefing_service

    analysis = build_analysis_graph(
        journal=journal,
        site_store=site_store,
        mission_store=mission_store,
        processing_job_store=processing_job_store,
        design_surface_store=design_surface_store,
        work_area_store=work_area_store,
        evidence_storage=evidence_storage,
        analysis_readiness_check=workspace.analysis_readiness_check,
        coverage_report_store=coverage_report_store,
        checkpoint_validation_store=checkpoint_validation_store,
        comparison_request_journal=comparison_request_journal,
    )
    design_conformance_request_store = analysis.design_conformance_request_store
    design_conformance_report_store = analysis.design_conformance_report_store
    report_export_store = analysis.report_export_store
    region_extraction_request_store = analysis.region_extraction_request_store
    region_extraction_report_store = analysis.region_extraction_report_store
    comparison_request_store = analysis.comparison_request_store

    equipment_state_journal = journal("equipment-states.jsonl")
    equipment_support_journal = journal("equipment-support.jsonl")

    capability = build_capability_graph(
        journal=journal,
        capability_freshness_policies=capability_freshness_policies,
        runtime_route_configurations=runtime_route_configurations,
        acquisition_connectivity_store=acquisition_connectivity_store,
    )
    capability_authority_store = capability.authority_store
    runtime_configuration_registry = capability.configuration_registry
    runtime_observation_store = capability.observation_store
    runtime_capability_projector = capability.projector

    app = create_app(
        auth_registry=auth_registry,
        human_auth_mode=human_auth_mode,
        oidc_verifier=oidc_verifier,
        site_store=site_store,
        observation_work_order_store=observation_work_order_store,
        organization_work_roster_store=organization_work_roster_store,
        work_inbox_store=work_inbox_store,
        external_reconstruction_store=external_reconstruction_store,
        external_evidence_store=external_evidence_store,
        external_evidence_validation_store=external_evidence_validation_store,
        external_use_evaluator=external_use_evaluator,
        external_relative_volume_store=external_relative_volume_store,
        external_result_workflow_service=external_result_workflow_service,
        external_result_read_projector=external_result_read_projector,
        external_volume_input_capability_issuer=external_volume_input_capability_issuer,
        external_volume_execution_activator=external_volume_execution_activator,
        external_display_artifact_store=external_display_artifact_store,
        external_artifact_inspection_store=external_artifact_inspection_store,
        acquisition_connectivity_store=acquisition_connectivity_store,
        acquisition_coordination_store=acquisition_coordination_store,
        capture_quality_report_store=capture_quality_report_store,
        acquisition_issue_gate_enabled=acquisition_issue_gate_enabled,
        landxml_ingress_enabled=landxml_ingress_enabled,
        checkpoint_validation_registration_enabled=checkpoint_validation_registration_enabled,
        copilot_service=copilot_service,
        copilot_conversation_service=copilot_conversation_service,
        site_workspace_projector=site_workspace_projector,
        site_briefing_service=site_briefing_service,
        civil_readiness_projector=civil_readiness_projector,
        mission_store=mission_store,
        event_store=event_store,
        edge_sync_store=edge_sync_store,
        edge_dispatch_store=edge_dispatch_store,
        evidence_storage=evidence_storage,
        flight_artifact_store=flight_artifact_store,
        coverage_report_store=coverage_report_store,
        mission_execution_store=mission_execution_store,
        source_media_store=source_media_store,
        design_surface_store=design_surface_store,
        work_area_store=work_area_store,
        processing_job_store=processing_job_store,
        checkpoint_validation_store=checkpoint_validation_store,
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
                comparison_request_store=comparison_request_store,
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
                comparison_request_store=comparison_request_store,
            )
            if processing_job_store is not None
            else None
        ),
        # W2 비교 요청(comparison_requests.py) — evidence_storage 까지 필요한
        # 것은 워커가 baseline/current 원본을 읽어갈 presigned URL 을 이 표면이
        # 직접 발급하기 때문이다(processing_job_store 와 동일 근거).
        comparison_request_store=comparison_request_store,
        design_conformance_request_store=design_conformance_request_store,
        design_conformance_report_store=design_conformance_report_store,
        report_export_store=report_export_store,
        region_extraction_request_store=region_extraction_request_store,
        region_extraction_report_store=region_extraction_report_store,
        equipment_state_store=EquipmentStateStore(equipment_state_journal, site_store=site_store),
        equipment_support_store=EquipmentSupportStore(equipment_support_journal),
        runtime_capability_projector=runtime_capability_projector,
        device_attestation_registry=device_attestation_registry,
        mission_signing_key=mission_signing_key,
        mission_signing_key_id=mission_signing_key_id,
        mission_contract_writer_version=mission_contract_writer_version,
        mission_contract_issuer_id=mission_contract_issuer_id,
        mission_sequence_store=mission_sequence_store,
        expose_docs=expose_docs,
    )
    mount_runtime_surfaces(
        app,
        opened=opened,
        capability_authority_store=capability_authority_store,
        runtime_route_configuration_registry=runtime_configuration_registry,
        runtime_route_observation_store=runtime_observation_store,
        external_validation_policy_registry=external_validation_policy_registry,
        external_artifact_inspection_store=external_artifact_inspection_store,
        external_display_artifact_store=external_display_artifact_store,
        external_evidence_store=external_evidence_store,
        external_evidence_validation_store=external_evidence_validation_store,
        external_relative_volume_mapping_authority=external_volume_mapping,
        external_use_decision_store=external_use_decision_store,
        external_use_evaluator=external_use_evaluator,
        external_authority_currentness=external_authority_currentness,
    )

    return app


__all__ = ["assemble_app", "cli_optional_positive"]
