"""API 계약 문서 ↔ 실구현 대조 게이트 (감사 #25·#34·#35, 재검토 V2 P3/P5).

권위 체인 4위(contracts/)가 구현보다 낡아도 CI 가 침묵하던 사각지대를 닫는다:
openapi-core.yaml 의 **비-planned 경로는 실제 FastAPI 앱에 존재해야 하고**,
asyncapi 의 $ref 는 존재하는 최신 세대 스키마 파일을 가리켜야 한다.

경로 키만 대조하면 놓치는 사각지대(재검토 P3)를 추가로 닫는다:
① 문서가 선언한 메서드가 그 경로에 실제로 존재하는지, ② 구현에 있는 ``/v1/*``
경로가 문서에서 아예 빠지지 않았는지(경로 신설 후 문서 누락 방지), ③ 공개
allowlist(``/health``·``/capabilities``) 밖의 문서화된 경로가 전부
``security`` 를 선언하는지.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from ksi_core.acquisition import AcquisitionConnectivityStore, AcquisitionCoordinationStore
from ksi_core.app import create_app
from ksi_core.app_assembly import assemble_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.capability.authority_store import CapabilityAuthorityStore
from ksi_core.capability.runtime_projection import (
    RuntimeCapabilityProjector,
    RuntimeRouteObservationStore,
    TrustedRuntimeRouteConfigurationRegistry,
)
from ksi_core.capture_quality_reports import CaptureQualityReportStore
from ksi_core.change_detection import ChangeDetectionStore
from ksi_core.checkpoint_validations import CheckpointValidationStore
from ksi_core.civil_readiness import CivilReadinessProjector
from ksi_core.comparison_requests import ComparisonRequestStore
from ksi_core.composition.external_graph import (
    ExternalAnalysisLocalGraphConfig,
    ExternalSingleVolumeWiring,
    build_external_analysis_wiring,
)
from ksi_core.copilot import CopilotService, ModelTurn, ToolResult
from ksi_core.copilot_conversations import (
    CopilotConversationService,
    CopilotConversationStore,
)
from ksi_core.coverage_reports import CoverageReportStore
from ksi_core.defect_candidates import DefectCandidateStore
from ksi_core.design_conformance_reports import DesignConformanceStore
from ksi_core.design_conformance_requests import DesignConformanceRequestStore
from ksi_core.design_surfaces import DesignSurfaceStore
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    AnalysisRuntimeIdentityV2,
)
from ksi_core.domains.external.quantity.external_single_volumes import (
    DefaultClosedExternalSingleVolumeExecutionPort,
    ExternalSingleVolumeStore,
)
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
from ksi_core.evidence import EvidenceStorageError
from ksi_core.external_artifact_inspections import ExternalArtifactInspectionStore
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_display_artifacts import ExternalDisplayArtifactStore
from ksi_core.external_evidence import ExternalEvidenceStore
from ksi_core.external_evidence_validations import (
    CoreEvidenceValidationInputCapabilities,
    ExternalEvidenceValidationStore,
)
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.external_relative_volume_authorities import (
    DefaultClosedExternalRelativeVolumeAuthorityPort,
)
from ksi_core.external_relative_volume_use_history import ClosedExternalRelativeVolumeUseHistory
from ksi_core.external_relative_volumes import (
    ExternalRelativeVolumeQueuePolicy,
    ExternalRelativeVolumeStore,
)
from ksi_core.external_reobservation_proposals import (
    CoreExternalReobservationProposalAuthorityPort,
    ExternalReobservationProposalService,
    ExternalReobservationProposalStore,
)
from ksi_core.external_result_review_sources import CoreExternalResultReviewSourceAdapter
from ksi_core.external_result_reviews import ExternalResultReviewStore
from ksi_core.external_result_workflow_api import ExternalResultReadProjector
from ksi_core.external_use_decisions import ExternalUseDecisionStore
from ksi_core.external_use_evaluator import ExternalUseEvaluator
from ksi_core.external_validation_policy import ExternalValidationPolicyRegistry
from ksi_core.flight_artifacts import FlightArtifactStore
from ksi_core.identity import auth as canonical_auth
from ksi_core.mission_execution import MissionExecutionStore
from ksi_core.mission_records import MissionStore
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.organization_work_roster import OrganizationWorkRosterStore
from ksi_core.processing_jobs import ProcessingJobStore
from ksi_core.report_exports import ReportExportStore
from ksi_core.site_workspace import (
    SiteBriefingService,
    SiteBriefingStore,
    SiteWorkspaceProjector,
    build_workspace_copilot_handlers,
)
from ksi_core.sites import SiteStore
from ksi_core.source_media import SourceMediaStore
from ksi_core.volume_reports import VolumeChangeStore
from ksi_core.work_areas import WorkAreaStore
from ksi_core.work_inbox import WorkInboxStore
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_relative_volume_analysis import AnalysisPolicyV2
from ksi_mission_contracts.models import SiteFrame
from ksi_mission_contracts.risk_policy import RiskPolicyPackV1

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OPENAPI = _REPO_ROOT / "contracts" / "api" / "openapi-core.yaml"
_ASYNCAPI = _REPO_ROOT / "contracts" / "api" / "asyncapi-edge.yaml"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest("contract-sync-test-token"),
                principal=Principal(
                    principal_id="op-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )


_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "trace"})
_PUBLIC_PATHS = frozenset({"/health", "/capabilities"})


class _NullEvidenceStorage:
    _blobs: dict[str, bytes] = {}  # noqa: RUF012 -- 테스트 스텁

    """포트 계약만 만족하는 조립용 스텁 — 이 게이트는 경로 존재만 본다.

    ``evidence_storage`` 를 주지 않으면 증거 라우터가 장착되지 않아(ADR-KSI-010 §1)
    "최대 조립"이라는 이름이 거짓이 된다 — 실제로 2026-08-04 에 증거 경로 2개가
    문서 대조 없이 통과했다.
    """

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        raise NotImplementedError

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        raise NotImplementedError

    def presigned_put_bound_digest(
        self, object_key: str, *, content_type: str, content_digest: str, ttl: Any
    ) -> Any:
        raise NotImplementedError

    def observe_object(self, object_key: str) -> Any:
        raise NotImplementedError

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        """포트가 요구하는 서버측 직접 쓰기 — 이 스텁은 메모리에만 담는다."""
        del content_type
        self._blobs[object_key] = data

    def get_bytes(self, object_key: str) -> bytes:
        """부재도 오류다(포트 계약) — 조용히 빈 바이트를 돌려주지 않는다."""
        blob = self._blobs.get(object_key)
        if blob is None:
            raise EvidenceStorageError(f"없다: {object_key}")
        return blob

    def delete(self, object_key: str) -> None:
        raise NotImplementedError


class _ContractSyncCopilotModel:
    external = False

    def complete(self, **_kwargs: Any) -> ModelTurn:
        return ModelTurn(answer="contract-only")


class _ContractSyncCopilotBackend:
    def site_exists(self, _organization_id: str, _site_id: str) -> bool:
        return False

    def ai_egress_allowed(self, _organization_id: str, _site_id: str) -> bool:
        return False

    def query(self, **_kwargs: Any) -> ToolResult:
        return ToolResult(data={}, citations=())

    def create_reobservation_draft(self, **_kwargs: Any) -> ToolResult:
        return ToolResult(data={}, citations=())


def _max_assembly(
    tmp_path: Path, *, volume_coordinator: ExternalAuthorityCurrentnessCoordinator | None = None
) -> Any:
    """최대 조립(모든 조건부 라우터 장착) 앱 — 문서는 구현 가능한 전체 표면을
    기술하므로, 부분 조립과 비교하면 조건부 라우터가 가짜 미구현이 된다."""
    external_authority_currentness = ExternalAuthorityCurrentnessCoordinator()
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    signing_key = Ed25519PrivateKey.generate()
    risk_policy_pack = RiskPolicyPackV1.model_validate(
        {
            "schemaVersion": "1.0",
            "riskPolicyPackId": "contract-sync-risk-pack",
            "validity": {
                "notBefore": "2026-01-01T00:00:00Z",
                "notAfter": "2027-01-01T00:00:00Z",
            },
            "calibrationProfileId": "contract-sync-calibration",
            "equipmentPolicies": [
                {
                    "equipmentClass": "Excavator",
                    "riskFieldPolicyId": "contract-sync-excavator",
                    "footprint": {"lengthM": 9.0, "widthM": 3.0, "heightM": 4.0},
                    "prediction": {"horizonSeconds": 5.0, "samplePeriodSeconds": 0.25},
                    "covarianceSigmaMultiplier": 3.0,
                    "occlusionExpansionM": 1.0,
                    "severity": 0.8,
                }
            ],
        }
    )
    edge_dispatch_store = EdgeDispatchStore(
        DurableJournal(tmp_path / "edge-dispatch.jsonl"),
        mission_store=mission_store,
        risk_policy_packs=RiskPolicyPackRegistry([risk_policy_pack]),
        edge_runtime_profiles=EdgeRuntimeProfileRegistry(()),
        private_key=signing_key,
        key_id="contract-sync-test-key",
    )
    site_store = SiteStore(
        DurableJournal(tmp_path / "sites.jsonl"), coordinator=external_authority_currentness
    )
    source_media_store = SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"), mission_store=mission_store
    )
    processing_job_store = ProcessingJobStore(
        DurableJournal(tmp_path / "processing-jobs.jsonl"),
        source_media_store=source_media_store,
        site_store=site_store,
    )
    checkpoint_validation_store = CheckpointValidationStore(
        DurableJournal(tmp_path / "checkpoint-validations.jsonl"),
        mission_store=mission_store,
        processing_jobs=processing_job_store,
    )
    design_surface_store = DesignSurfaceStore(
        DurableJournal(tmp_path / "design-surfaces.jsonl"), site_store=site_store
    )
    storage = _NullEvidenceStorage()
    flight_artifact_store = FlightArtifactStore(
        DurableJournal(tmp_path / "flight-artifacts.jsonl"),
        mission_store=mission_store,
        storage=storage,
    )
    work_area_store = WorkAreaStore(
        DurableJournal(tmp_path / "work-areas.jsonl"),
        coordinator=external_authority_currentness,
        site_exists=lambda site_id: site_store.get(site_id) is not None,
    )
    external_use_decision_store = ExternalUseDecisionStore(
        DurableJournal(tmp_path / "external-use-decisions.jsonl"),
        coordinator=external_authority_currentness,
    )
    external_relative_volume_store = ExternalRelativeVolumeStore(
        DurableJournal(tmp_path / "external-relative-volumes.jsonl"),
        authority_port=DefaultClosedExternalRelativeVolumeAuthorityPort(
            currentness_coordinator=volume_coordinator or external_authority_currentness
        ),
        currentness_coordinator=volume_coordinator or external_authority_currentness,
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(seconds=5),
            deadline_after_issue=timedelta(seconds=30),
            max_attempts=1,
            max_active_requests_per_organization=2,
        ),
    )

    reviews = ExternalResultReviewStore(
        DurableJournal(tmp_path / "external-result-reviews.jsonl"),
        source_port=CoreExternalResultReviewSourceAdapter(
            volume_store=external_relative_volume_store,
            decisions=external_use_decision_store,
            historical_use_authority=ClosedExternalRelativeVolumeUseHistory(),
            coordinator=external_authority_currentness,
        ),
        coordinator=external_authority_currentness,
    )
    proposals = ExternalReobservationProposalStore(
        DurableJournal(tmp_path / "external-reobservation-proposals.jsonl"),
        coordinator=external_authority_currentness,
    )
    proposal_authority = CoreExternalReobservationProposalAuthorityPort(
        reviews=reviews,
        proposals=proposals,
        sites=site_store,
        work_areas=work_area_store,
        coordinator=external_authority_currentness,
    )
    organization_work_roster_store = OrganizationWorkRosterStore(
        DurableJournal(tmp_path / "organization-work-roster.jsonl"),
        coordinator=external_authority_currentness,
    )
    observation_work_order_store = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "observation-work-orders.jsonl"),
        external_reobservation_authority_port=proposal_authority,
        operations_coordinator=external_authority_currentness,
        assignment_member_is_active=organization_work_roster_store.is_assignable_member,
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    external_result_workflow_service = ExternalReobservationProposalService(
        reviews=reviews,
        proposals=proposals,
        sites=site_store,
        work_areas=work_area_store,
        work_orders=observation_work_order_store,
        authority_port=proposal_authority,
        coordinator=external_authority_currentness,
    )
    external_single_volume_store = ExternalSingleVolumeStore(
        DurableJournal(tmp_path / "external-single-volumes.jsonl"),
        authority_port=DefaultClosedExternalSingleVolumeExecutionPort(
            currentness_coordinator=volume_coordinator or external_authority_currentness
        ),
        currentness_coordinator=volume_coordinator or external_authority_currentness,
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(seconds=5),
            deadline_after_issue=timedelta(seconds=30),
            max_attempts=1,
            max_active_requests_per_organization=2,
        ),
    )
    external_result_read_projector = ExternalResultReadProjector(
        volumes=external_relative_volume_store,
        workflow=external_result_workflow_service,
        single_volumes=external_single_volume_store,
    )
    work_inbox_store = WorkInboxStore(
        DurableJournal(tmp_path / "work-inbox.jsonl"),
        work_orders=observation_work_order_store,
        roster=organization_work_roster_store,
        report_resolver=external_relative_volume_store,
        coordinator=external_authority_currentness,
    )
    acquisition_connectivity_store = AcquisitionConnectivityStore(
        DurableJournal(tmp_path / "acquisition-connectivity.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    acquisition_coordination_store = AcquisitionCoordinationStore(
        DurableJournal(tmp_path / "acquisition-runs.jsonl")
    )
    coverage_report_store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"), mission_store=mission_store
    )
    capture_quality_report_store = CaptureQualityReportStore(
        DurableJournal(tmp_path / "capture-quality-reports.jsonl"),
        mission_store=mission_store,
        work_order_store=observation_work_order_store,
        coordination_store=acquisition_coordination_store,
    )
    copilot_service = CopilotService(
        model=_ContractSyncCopilotModel(),
        backend=_ContractSyncCopilotBackend(),
        planner_version="contract-sync",
    )
    event_store = EventStore(DurableJournal(tmp_path / "events" / "journal.jsonl"))
    site_workspace_projector = SiteWorkspaceProjector(
        site_store=site_store,
        work_order_store=observation_work_order_store,
        processing_job_store=processing_job_store,
        event_store=event_store,
        external_results=external_result_read_projector,
    )
    civil_readiness_projector = CivilReadinessProjector(
        site_store=site_store,
        processing_job_store=processing_job_store,
        design_surface_store=design_surface_store,
        analysis_readiness=None,
    )
    conversation_service = CopilotConversationService(
        store=CopilotConversationStore(
            DurableJournal(tmp_path / "copilot-conversations.jsonl"),
            site_exists=lambda site_id, organization_id: (
                site_store.get_scoped(site_id, organization_id) is not None
            ),
            work_order_matches=lambda work_order_id, organization_id, site_id: (
                (
                    order := observation_work_order_store.get(
                        work_order_id, organization_id=organization_id
                    )
                )
                is not None
                and order.site_id == site_id
            ),
        ),
        copilot=copilot_service,
        provider="contract-sync",
        model="contract-sync",
        planner_version="contract-sync",
    )
    briefing_service = SiteBriefingService(
        store=SiteBriefingStore(
            DurableJournal(tmp_path / "site-briefings.jsonl"), site_store=site_store
        ),
        copilot=copilot_service,
        workspace=site_workspace_projector,
    )
    design_conformance_request_store = DesignConformanceRequestStore(
        DurableJournal(tmp_path / "design-conformance-requests.jsonl"),
        mission_store=mission_store,
        processing_job_store=processing_job_store,
        design_surface_store=design_surface_store,
        work_area_store=work_area_store,
    )
    design_conformance_report_store = DesignConformanceStore(
        DurableJournal(tmp_path / "design-conformance.jsonl"),
        mission_store=mission_store,
        processing_job_store=processing_job_store,
        request_store=design_conformance_request_store,
        storage=storage,
    )
    runtime_projector = RuntimeCapabilityProjector(
        authority_store=CapabilityAuthorityStore(
            DurableJournal(tmp_path / "capability-authority.jsonl")
        ),
        configuration_registry=TrustedRuntimeRouteConfigurationRegistry(),
        observation_store=RuntimeRouteObservationStore(
            DurableJournal(tmp_path / "capability-runtime-observations.jsonl")
        ),
        supported_freshness_policies={},
    )
    external_reconstruction_store = ExternalReconstructionStore(
        DurableJournal(tmp_path / "external-reconstruction.jsonl"),
        coordinator=external_authority_currentness,
    )
    external_validation_policy_registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "external-validation-policy.jsonl"),
        coordinator=external_authority_currentness,
    )
    external_display_artifact_store = ExternalDisplayArtifactStore(
        DurableJournal(tmp_path / "external-display-artifacts.jsonl"),
        policy_registry=external_validation_policy_registry,
        storage=storage,
        coordinator=external_authority_currentness,
    )
    external_artifact_inspection_store = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "external-artifact-inspections.jsonl"),
        policy_registry=external_validation_policy_registry,
        external_reconstruction=external_reconstruction_store,
        storage=storage,
        display_store=external_display_artifact_store,
        coordinator=external_authority_currentness,
    )
    external_evidence_store = ExternalEvidenceStore(
        DurableJournal(tmp_path / "external-evidence.jsonl"),
        coordinator=external_authority_currentness,
    )
    external_evidence_validation_store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "external-evidence-validations.jsonl"),
        evidence=external_evidence_store,
        policy_registry=external_validation_policy_registry,
        input_capabilities=CoreEvidenceValidationInputCapabilities(
            reconstruction=external_reconstruction_store,
            storage=storage,
        ),
        coordinator=external_authority_currentness,
    )
    external_use_evaluator = ExternalUseEvaluator(
        decisions=external_use_decision_store,
        reconstruction=external_reconstruction_store,
        inspections=external_artifact_inspection_store,
        policy_registry=external_validation_policy_registry,
        evidence_validations=external_evidence_validation_store,
        coordinator=external_authority_currentness,
    )

    def closed_volume_capabilities(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("closed contract fixture must never issue a byte capability")

    analysis_local_config = ExternalAnalysisLocalGraphConfig(
        policy=AnalysisPolicyV2(
            policy_id="contract-sync-analysis-policy",
            version=1,
            profile_id="KSI-GIS-RELATIVE-VOLUME-V2",
            profile_digest="sha256:" + _digest("contract-sync-analysis-profile"),
            algorithm_digest="sha256:" + _digest("contract-sync-analysis-algorithm"),
            config_digest="sha256:" + _digest("contract-sync-analysis-config"),
            baseline_grid_rule="BASELINE_NATIVE_NORTH_UP_AFFINE_V1",
            current_elevation_resampling="BILINEAR",
            current_mask_resampling="NEAREST",
            work_area_rasterization="CELL_CENTER",
            minimum_common_valid_fraction=1.0,
            threshold_m=0.0,
            cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
            delta_rule="CURRENT_MINUS_BASELINE",
            uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
        ).sealed(),
        runtime=AnalysisRuntimeIdentityV2(
            worker_executable_digest="sha256:" + _digest("contract-sync-analysis-worker"),
            worker_build_digest="sha256:" + _digest("contract-sync-analysis-build"),
            runtime_image_version="contract-sync-analysis-local-v1",
            runtime_image_oci_digest="sha256:" + _digest("contract-sync-analysis-oci"),
            dependency_lock_digest="sha256:" + _digest("contract-sync-analysis-lock"),
        ),
        resource_envelope=ResourceEnvelopeV1(
            max_input_bytes=10_000_000,
            max_streamed_bytes=20_000_000,
            max_tiff_directories=16,
            max_tiff_entries=10_000,
            max_pixels=1_000_000,
            max_bands=4,
            max_blocks=10_000,
            max_decompressed_bytes=40_000_000,
            max_sample_bytes=1_000_000,
            max_geometry_vertices=10_000,
            max_cpu_seconds=30.0,
            max_memory_bytes=128_000_000,
            max_workspace_bytes=128_000_000,
            max_output_bytes=4_000_000,
            max_tenant_concurrency=2,
            max_queue_depth=10,
            max_deadline_seconds=60.0,
            lease_duration_seconds=10.0,
            max_retry_attempts=2,
        ).sealed(),
    )

    return create_app(
        evidence_storage=storage,
        flight_artifact_store=flight_artifact_store,
        auth_registry=_auth_registry(),
        edge_sync_store=EdgeSyncStore(tmp_path / "journal.jsonl"),
        edge_dispatch_store=edge_dispatch_store,
        event_store=event_store,
        site_store=site_store,
        mission_store=mission_store,
        coverage_report_store=coverage_report_store,
        mission_execution_store=MissionExecutionStore(
            DurableJournal(tmp_path / "mission-execution.jsonl"), mission_store=mission_store
        ),
        source_media_store=source_media_store,
        design_surface_store=design_surface_store,
        processing_job_store=processing_job_store,
        checkpoint_validation_store=checkpoint_validation_store,
        defect_candidate_store=DefectCandidateStore(
            DurableJournal(tmp_path / "defect-candidates.jsonl"),
            mission_store=mission_store,
            source_media_store=source_media_store,
        ),
        change_detection_store=ChangeDetectionStore(
            DurableJournal(tmp_path / "change-detection.jsonl"),
            mission_store=mission_store,
            processing_job_store=processing_job_store,
        ),
        volume_change_store=VolumeChangeStore(
            DurableJournal(tmp_path / "volume-changes.jsonl"),
            mission_store=mission_store,
            processing_job_store=processing_job_store,
        ),
        comparison_request_store=ComparisonRequestStore(
            DurableJournal(tmp_path / "comparison-requests.jsonl"),
            mission_store=mission_store,
            processing_job_store=processing_job_store,
        ),
        design_conformance_request_store=design_conformance_request_store,
        design_conformance_report_store=design_conformance_report_store,
        report_export_store=ReportExportStore(
            DurableJournal(tmp_path / "report-exports.jsonl"),
            site_store=site_store,
            design_conformance_store=design_conformance_report_store,
            coverage_report_store=coverage_report_store,
        ),
        work_area_store=work_area_store,
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
        external_volume_input_capability_issuer=closed_volume_capabilities,
        external_single_volume=ExternalSingleVolumeWiring(
            store=external_single_volume_store,
            input_capability_issuer=closed_volume_capabilities,
            execution_activator=None,
        ),
        external_display_artifact_store=external_display_artifact_store,
        external_artifact_inspection_store=external_artifact_inspection_store,
        external_analysis_wiring=build_external_analysis_wiring(
            journal=lambda name: DurableJournal(tmp_path / name),
            config=analysis_local_config,
            reconstruction=external_reconstruction_store,
            inspections=external_artifact_inspection_store,
            work_areas=work_area_store,
            evidence=external_evidence_store,
            validations=external_evidence_validation_store,
            storage=storage,
            sites=site_store,
            work_orders=observation_work_order_store,
            coordinator=external_authority_currentness,
        ),
        acquisition_connectivity_store=acquisition_connectivity_store,
        acquisition_coordination_store=acquisition_coordination_store,
        capture_quality_report_store=capture_quality_report_store,
        copilot_service=copilot_service,
        copilot_conversation_service=conversation_service,
        site_workspace_projector=site_workspace_projector,
        site_briefing_service=briefing_service,
        civil_readiness_projector=civil_readiness_projector,
        equipment_state_store=EquipmentStateStore(
            DurableJournal(tmp_path / "equipment-states.jsonl"), site_store=site_store
        ),
        equipment_support_store=EquipmentSupportStore(
            DurableJournal(tmp_path / "equipment-support.jsonl")
        ),
        runtime_capability_projector=runtime_projector,
        mission_signing_key=signing_key,
        mission_signing_key_id="contract-sync-test-key",
    )


_MAX_ASSEMBLY_NOW = datetime(2026, 9, 9, 0, 0, tzinfo=UTC)


def _max_assembly_arguments(tmp_path: Path) -> dict[str, Any]:
    """Capture the complete maximal assembly as ``create_app`` inputs.

    The public API fixture has one canonical durable graph. Capturing its inputs
    lets the tests below exercise ``create_app``'s composition guard with each
    deliberate mismatch, without reimplementing that graph in a second fixture.
    """
    with patch(f"{__name__}.create_app", side_effect=lambda **kwargs: kwargs):
        arguments = _max_assembly(tmp_path)
    assert isinstance(arguments, dict)
    return arguments


def _seed_max_assembly_site_and_work_order(arguments: dict[str, Any]) -> str:
    site_store = arguments["site_store"]
    work_orders = arguments["observation_work_order_store"]
    assert (
        site_store.register(
            "shared-projector-site",
            "Shared projector site",
            SiteFrame(
                crs="EPSG:5186",
                vertical_datum="LOCAL",
                unit="meter",
                transform_version="v1",
            ),
            organization_id="legacy",
            actor="contract-sync",
            now=_MAX_ASSEMBLY_NOW,
        ).record
        is not None
    )
    return work_orders.create_work_order(
        organization_id="legacy",
        site_id="shared-projector-site",
        name="Shared projector work order",
        work_area_ids=["shared-projector-work-area"],
        schedule_id=None,
        actor="contract-sync",
        now=_MAX_ASSEMBLY_NOW,
    ).work_order_id


@pytest.mark.parametrize(
    "mismatch",
    ("missing-results", "different-results", "different-sites", "different-work-orders"),
)
def test_create_app_rejects_disconnected_external_result_workspace_participants(
    tmp_path: Path, mismatch: str
) -> None:
    """The workspace must read the exact graph mounted on context routes."""
    arguments = _max_assembly_arguments(tmp_path)
    site_store = arguments["site_store"]
    work_orders = arguments["observation_work_order_store"]
    external_results = arguments["external_result_read_projector"]

    if mismatch == "missing-results":
        external_results = None
    elif mismatch == "different-results":
        external_results = ExternalResultReadProjector(
            volumes=arguments["external_relative_volume_store"],
            workflow=arguments["external_result_workflow_service"],
            single_volumes=arguments["external_single_volume"].store,
        )
    elif mismatch == "different-sites":
        site_store = SiteStore(DurableJournal(tmp_path / "different-sites.jsonl"))
    else:
        work_orders = ObservationWorkOrderStore(
            DurableJournal(tmp_path / "different-work-orders.jsonl"),
            site_exists=lambda _site_id, _organization_id: True,
        )

    arguments["site_workspace_projector"] = SiteWorkspaceProjector(
        site_store=site_store,
        work_order_store=work_orders,
        processing_job_store=arguments["processing_job_store"],
        event_store=arguments["event_store"],
        external_results=external_results,
    )

    with pytest.raises(
        ValueError, match="site workspace must use the mounted external result projection"
    ):
        create_app(**arguments)


def test_max_assembly_shares_external_result_projection_with_context_workspace_and_copilot(
    tmp_path: Path,
) -> None:
    """One projection gives every mounted read surface the same NO_RESULT view."""
    arguments = _max_assembly_arguments(tmp_path)
    projector = arguments["external_result_read_projector"]
    workspace = arguments["site_workspace_projector"]
    assert workspace.uses_exact_participants(
        site_store=arguments["site_store"],
        work_order_store=arguments["observation_work_order_store"],
        external_results=projector,
    )
    work_order_id = _seed_max_assembly_site_and_work_order(arguments)

    app = create_app(**arguments)
    assert app.state.external_result_read_projector is projector
    assert projector.single_volumes is app.state.external_single_volume_store
    assert app.state.site_workspace_projector is workspace

    headers = {"Authorization": "Bearer contract-sync-test-token"}
    with TestClient(app) as client:
        context = client.get(
            f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-context",
            headers=headers,
        )
        workspace_response = client.get(
            "/v1/sites/shared-projector-site/workspace", headers=headers
        )
    assert context.status_code == workspace_response.status_code == 200
    assert context.json()["externalResult"]["state"] == "NO_RESULT"
    assert context.json()["externalResult"] == workspace_response.json()["externalResult"]

    latest_progress = build_workspace_copilot_handlers(
        app.state.site_workspace_projector,
        arguments["observation_work_order_store"],
    )["latest_progress"]("legacy", "shared-projector-site", None, {})
    assert latest_progress.data["externalResult"] == workspace_response.json()["externalResult"]


def _implemented_operations(tmp_path: Path) -> dict[str, set[str]]:
    """경로 → 실구현 HTTP 메서드 집합(최대 조립 기준)."""
    paths = _max_assembly(tmp_path).openapi()["paths"]
    data_dir = tmp_path / "data-lane"
    data_dir.mkdir(exist_ok=True)
    from test_spatial_data_assembly import maximal_data_arguments

    paths.update(create_app(**maximal_data_arguments(data_dir)).openapi()["paths"])
    return {path: {m for m in item if m in _HTTP_METHODS} for path, item in paths.items()}


def _implemented_paths(tmp_path: Path) -> set[str]:
    return set(_implemented_operations(tmp_path))


def test_non_planned_openapi_paths_exist_in_implementation(tmp_path: Path) -> None:
    doc: dict[str, Any] = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))
    implemented = _implemented_paths(tmp_path)
    documented = {path for path, spec in doc["paths"].items() if spec.get("x-status") != "planned"}
    missing = documented - implemented
    assert not missing, (
        f"openapi-core.yaml 이 구현에 없는 경로를 '구현된 계약'으로 문서화한다: {missing} "
        "— 미구현 설계는 x-status: planned 로 표기하라"
    )


def test_edge_sync_path_is_documented_as_implemented(tmp_path: Path) -> None:
    """역방향 — 핵심 구현 경로가 문서에서 빠지거나 planned 로 강등되면 실패."""
    doc: dict[str, Any] = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))
    spec = doc["paths"].get("/v1/edge-sync/event-bundles")
    assert spec is not None and spec.get("x-status") != "planned"
    assert "/v1/edge-sync/event-bundles" in _implemented_paths(tmp_path)


@pytest.mark.parametrize(
    "path",
    [
        "/v1/sites/{site_id}",
        "/v1/events/{event_key}",
        "/v1/missions/{mission_id}",
    ],
)
def test_query_paths_are_documented_as_implemented(path: str, tmp_path: Path) -> None:
    """역방향 anchor — 사이트·이벤트·미션 조회 경로가 문서에서 빠지거나 planned 로
    강등되면 실패(감사 #25·#35 사각지대: ADR-KSI-008 신규 조회 표면도 동일 게이트).

    ``event_key`` = ``{edgeDeviceId}::{eventId}`` — event_key 도입(P1 파급)으로
    구경로 ``{event_id}`` 는 더 이상 존재하지 않는다(events.py)."""
    doc: dict[str, Any] = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))
    spec = doc["paths"].get(path)
    assert spec is not None and spec.get("x-status") != "planned"
    assert path in _implemented_paths(tmp_path)


def test_documented_methods_exist_in_implementation(tmp_path: Path) -> None:
    """① 메서드 집합 대조 — 문서가 어떤 경로에 선언한 메서드는 실구현에도 있어야
    한다. 경로 키만 대조하면, 문서가 ``GET`` 뿐인 경로에 실구현에 없는 ``POST``
    를 얹어도 기존 게이트가 침묵했다(재검토 P3)."""
    doc: dict[str, Any] = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))
    implemented = _implemented_operations(tmp_path)

    missing: list[str] = []
    for path, spec in doc["paths"].items():
        if spec.get("x-status") == "planned":
            continue
        doc_methods = {method for method in spec if method in _HTTP_METHODS}
        impl_methods = implemented.get(path, set())
        missing.extend(
            f"{method.upper()} {path}" for method in doc_methods if method not in impl_methods
        )

    assert not missing, f"openapi-core.yaml 이 실구현에 없는 메서드를 문서화한다: {missing}"


def test_implemented_v1_paths_are_documented(tmp_path: Path) -> None:
    """② 역방향 대조(전수) — 실구현의 ``/v1/*`` 경로가 문서에서 통째로 빠지면
    실패한다. 개별 anchor 테스트(위)는 알려진 경로만 지키므로, 신규 라우터가
    문서화 없이 조립되는 사각지대는 이 전수 검사만 잡는다(재검토 P3). FastAPI
    기본 문서 라우트(/openapi.json 등)는 OpenAPI ``paths`` 스키마 자체에 나타나지
    않으므로 allowlist가 불필요하다."""
    doc: dict[str, Any] = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))
    documented = set(doc["paths"])
    implemented = _implemented_operations(tmp_path)

    undocumented = {
        path for path in implemented if path.startswith("/v1/") and path not in documented
    }
    assert not undocumented, f"실구현에 있는 /v1/* 경로가 openapi-core.yaml 에 없다: {undocumented}"


def test_protected_paths_declare_security_in_doc() -> None:
    """③ 보호 경로의 security 선언 검사(문서 측) — 공개 allowlist(/health·
    /capabilities) 밖의 non-planned 경로는 전부 ``security`` 를 선언해야 한다.
    실구현은 FastAPI 보안 유틸을 쓰지 않아(수동 Authorization 헤더 파싱) 앱
    OpenAPI 출력에 security 가 자동으로 실리지 않으므로, 이 검사는 문서 자체의
    자기일관성만 본다(재검토 P3)."""
    doc: dict[str, Any] = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))

    violations: list[str] = []
    for path, spec in doc["paths"].items():
        if spec.get("x-status") == "planned" or path in _PUBLIC_PATHS:
            continue
        for method, operation in spec.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            if "security" not in operation:
                violations.append(f"{method.upper()} {path}")

    assert not violations, f"보호 경로인데 security 선언이 없다: {violations}"


def test_spatial_data_contract_has_every_opt_in_operation_and_exact_models(tmp_path: Path) -> None:
    """Documentation must cover the real lane, not just ordinary default-closed assembly."""
    from test_spatial_data_assembly import maximal_data_arguments

    impl = create_app(**maximal_data_arguments(tmp_path)).openapi()
    doc = _doc()
    selected = {
        path: operations for path, operations in impl["paths"].items() if "spatial-data" in path
    }
    assert len(selected) == 11  # Four public paths, seven internal paths.
    for path, operations in selected.items():
        assert path in doc["paths"], path
        for method, operation in operations.items():
            recorded = doc["paths"][path][method]
            assert recorded["security"] == [{"bearerAuth": []}]
            for code, response in operation["responses"].items():
                if code.startswith("2") and "content" in response:
                    assert _json_schema(recorded["responses"][code]) == _json_schema(response)


def test_spatial_data_worker_headers_document_the_same_fence_the_handler_requires(
    tmp_path: Path,
) -> None:
    """Undocumented instance/fence prerequisites must not create an unusable client contract."""
    from test_spatial_data_assembly import maximal_data_arguments

    impl = create_app(**maximal_data_arguments(tmp_path)).openapi()
    for path, operations in impl["paths"].items():
        if not path.startswith("/v1/internal/spatial-data-jobs"):
            continue
        for operation in operations.values():
            headers = {p["name"]: p for p in operation.get("parameters", []) if p["in"] == "header"}
            assert headers["X-Spatial-Data-Worker-Instance-Id"]["required"] is True
            if path.endswith(("/input", "/renew", "/output-upload", "/complete", "/failure")):
                assert headers["X-Spatial-Data-Attempt-Digest"]["required"] is True


def _expanded_schema(node: Any, document: Any) -> Any:
    if isinstance(node, list):
        return [_expanded_schema(item, document) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        ref = node["$ref"]
        if ref.startswith("../"):
            target, root = _external_schema(ref)
        else:
            assert ref.startswith("#/")
            target, root = document, document
            for part in ref[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
        return {
            **_expanded_schema(target, root),
            **_expanded_schema(
                {key: value for key, value in node.items() if key != "$ref"}, document
            ),
        }
    return {
        key: _expanded_schema(value, document)
        for key, value in node.items()
        if key not in {"title", "description", "default"}
    }


def test_spatial_data_external_schemas_match_nested_body_and_response_constraints(
    tmp_path: Path,
) -> None:
    """An existing file alone is insufficient: every referenced nested constraint must match."""
    from test_spatial_data_assembly import maximal_data_arguments

    doc = _doc()
    impl = create_app(**maximal_data_arguments(tmp_path)).openapi()
    for path, operations in impl["paths"].items():
        if "spatial-data" not in path:
            continue
        for method, operation in operations.items():
            recorded = doc["paths"][path][method]
            if "requestBody" in operation:
                actual = operation["requestBody"]["content"]["application/json"]["schema"]
                expected = recorded["requestBody"]["content"]["application/json"]["schema"]
                assert _expanded_schema(actual, impl) == _expanded_schema(expected, doc)
            for code, response in operation["responses"].items():
                if code.startswith("2") and _json_schema(response):
                    assert _expanded_schema(_json_schema(response), impl) == _expanded_schema(
                        _json_schema(recorded["responses"][code]), doc
                    )


def test_external_schema_reference_verifier_rejects_missing_or_foreign_pointer() -> None:
    """The verifier must not accept a present file with a missing fragment or an external path."""
    for reference in (
        "../schemas/spatial-data.v1.json#/$defs/Nonexistent",
        "../../pyproject.toml",
        "https://example.invalid/schema.json#/$defs/Model",
    ):
        with pytest.raises((AssertionError, KeyError)):
            _external_schema(reference)


def test_asyncapi_refs_point_to_existing_latest_schemas() -> None:
    text = _ASYNCAPI.read_text(encoding="utf-8")
    doc: dict[str, Any] = yaml.safe_load(text)
    refs: list[str] = []

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str):
                    refs.append(value)
                else:
                    collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    collect(doc)
    assert refs, "asyncapi 에 스키마 $ref 가 없다"
    for ref in refs:
        target = (_ASYNCAPI.parent / ref).resolve()
        assert target.is_file(), f"asyncapi $ref 가 존재하지 않는 파일을 가리킨다: {ref}"
    # 최초 세대(v1)로의 회귀 방지 — 서명(INV-011)·분류 계보(INV-031)가 없는
    # 페이로드를 와이어 계약으로 안내하던 drift(감사 #34).
    assert "mission-contract.v1.json" not in text
    assert "event-bundle.v1.json" not in text and "event-bundle.v1.1.json" not in text


def test_openapi_refs_resolve_to_defined_targets() -> None:
    """openapi-core.yaml 전수 $ref 해소 검사 (risk openapi-dangling-ref-ungated).

    ④·⑤(아래)는 문서에 이미 적힌 모델 **이름**끼리만 대조한다 — 그 이름이
    애초에 ``components/schemas`` 에 정의돼 있는지는 어느 기존 게이트도 보지
    않는다. 실측(2026-08-07): M1 에서 두 경로에 ``ArtifactUploadUrlResponse``·
    ``ArtifactDownloadResponse`` 를 $ref 로 걸어 놓고 정의를 빠뜨렸는데도 이
    파일의 검사 14건이 전부 통과했다.

    문서 전체를 순회해 모든 $ref 를 모으고, 두 갈래 스타일을 각각 해소한다:
      - 내부 참조(``#/components/schemas/X`` 등) — 문서 자신의 트리에서 그
        JSON 포인터 경로가 실제로 존재하는가.
      - 상대 파일 참조(``../schemas/X.json``) — 그 경로의 파일이 실제로
        존재하는가.
    그 외 형태(원격 ``https://`` URL 등)는 이 저장소 안에서 해소할 수 없으므로
    그 자체로 실패다.
    """
    doc: dict[str, Any] = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))
    refs: list[tuple[str, str]] = []

    def collect(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str):
                    refs.append((path, value))
                else:
                    collect(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                collect(item, f"{path}[{index}]")

    collect(doc, "$")
    assert refs, "openapi-core.yaml 에 $ref 가 없다"

    dangling: list[str] = []
    for pointer_path, ref in refs:
        if ref.startswith("#/"):
            target: Any = doc
            for part in ref[2:].split("/"):
                if isinstance(target, dict) and part in target:
                    target = target[part]
                else:
                    dangling.append(f"{pointer_path} -> {ref} (문서 안에 정의가 없다)")
                    break
        elif ref.startswith("../"):
            try:
                _external_schema(ref)
            except (AssertionError, KeyError, OSError, ValueError) as exc:
                dangling.append(f"{pointer_path} -> {ref} ({type(exc).__name__})")
        else:
            dangling.append(f"{pointer_path} -> {ref} (저장소 안에서 해소할 수 없는 참조 형태)")

    assert not dangling, f"openapi-core.yaml 의 $ref 가 정의되지 않은 대상을 가리킨다: {dangling}"


def test_runtime_observation_producer_kind_is_a_closed_least_privilege_enum(
    tmp_path: Path,
) -> None:
    document = yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))
    assert document["info"]["version"] == "1.35.0"
    documented_producer_kind = document["components"]["schemas"]["RuntimeRouteObservationV1"][
        "properties"
    ]["producerPrincipalKind"]
    implemented_producer_kind = _implemented_spec(tmp_path)["components"]["schemas"][
        "RuntimeRouteObservationV1"
    ]["properties"]["producerPrincipalKind"]
    expected = ["GATEWAY_DEVICE", "EDGE_DEVICE", "EDGE_ROUTE_OBSERVER"]

    assert documented_producer_kind["enum"] == expected
    assert implemented_producer_kind["enum"] == expected


# ── ④·⑤ 응답 본문 대조 (risk api-contract-response-schema-void) ─────────────
#
# 위 검사들은 경로·메서드·security 존재만 본다. 그래서 Core 가
# EventSummaryResponse 에 ``eventType`` 을 추가했을 때(2026-08-04) 게이트가
# 침묵했다 — 문서가 응답을 자유 문자열 description 으로만 적어 **대조할 정본
# 자체가 없었기** 때문이다. 소비자(apps/dashboard 의 types.ts)는 이 계약의 수동
# 복제본이라, 서버가 필드를 바꿔도 프런트 타입체크는 green 이고 런타임에서만
# 깨진다. 아래 둘이 그 구멍을 닫는다.


def _doc() -> dict[str, Any]:
    return yaml.safe_load(_OPENAPI.read_text(encoding="utf-8"))


def _external_schema(ref: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve a repository-local file and exact JSON pointer; do not drop fragments."""
    assert ref.startswith("../")
    filename, _, fragment = ref.partition("#")
    path = (_OPENAPI.parent / filename).resolve()
    assert path.is_relative_to(_OPENAPI.parent.parent.resolve()) and path.is_file()
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    node = document
    if fragment:
        assert fragment.startswith("/")
        for part in fragment[1:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
    assert isinstance(node, dict)
    return node, document


def _implemented_spec(tmp_path: Path) -> dict[str, Any]:
    result = _max_assembly(tmp_path).openapi()
    from test_spatial_data_assembly import maximal_data_arguments

    data_dir = tmp_path / "data-spec"
    data_dir.mkdir(exist_ok=True)
    data = create_app(**maximal_data_arguments(data_dir)).openapi()
    result["paths"].update(data["paths"])
    result["components"]["schemas"].update(data["components"]["schemas"])
    # Bounded manual body ingestion documents the exact model inline, not via Depends/Body.
    for path, operations in data["paths"].items():
        if "spatial-data" not in path:
            continue
        for operation in operations.values():
            schema = (
                operation.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            if schema.get("title", "").startswith("SpatialData"):
                result["components"]["schemas"][schema["title"]] = schema
    return result


def _ref_name(node: Any) -> str | None:
    """스키마 노드가 named 모델(또는 그 배열)을 가리키면 모델 이름을 준다.

    자유 형태 dict 응답(``/health``·서명된 MissionContract 등)은 None — 대조
    대상이 아니다. 그 응답들의 구조 정본은 ``contracts/schemas/*.json`` 이다.
    """
    if not isinstance(node, dict):
        return None
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        return ref.rsplit("/", 1)[-1]
    if node.get("type") == "array":
        return _ref_name(node.get("items"))
    return None


def _json_schema(response: Any) -> Any:
    if not isinstance(response, dict):
        return None
    return ((response.get("content") or {}).get("application/json") or {}).get("schema")


def test_documented_response_schemas_match_implementation_fields(tmp_path: Path) -> None:
    """④ 필드 집합 대조 — 문서 ``components/schemas`` 의 각 모델은 실구현과
    **필드 이름·필수 여부가 정확히 일치**해야 한다.

    타입까지는 보지 않는다(문서는 구현의 정밀도를 복제하지 않는다) — 잡으려는
    실패는 "한쪽에만 필드가 생기거나 사라지는 것"이다.
    """
    doc_schemas = (_doc().get("components") or {}).get("schemas") or {}
    assert doc_schemas, (
        "openapi-core.yaml 에 components/schemas 가 없다 — 응답 본문을 자유 문자열 "
        "description 으로만 적으면 대조할 정본이 사라진다(risk "
        "api-contract-response-schema-void 가 정확히 그 상태였다)"
    )
    impl_schemas = (_implemented_spec(tmp_path).get("components") or {}).get("schemas") or {}

    mismatches: list[str] = []
    for name, spec in doc_schemas.items():
        if spec.get("x-status") == "planned":
            continue
        if spec.get("$ref", "").startswith("../"):
            spec, _ = _external_schema(spec["$ref"])
        impl = impl_schemas.get(name)
        if impl is None:
            mismatches.append(f"{name}: 문서에만 있는 모델(구현에 없음)")
            continue
        doc_fields = set(spec.get("properties") or {})
        impl_fields = set(impl.get("properties") or {})
        if doc_fields != impl_fields:
            mismatches.append(
                f"{name}: 문서에만 {sorted(doc_fields - impl_fields)} / "
                f"구현에만 {sorted(impl_fields - doc_fields)}"
            )
        doc_required = set(spec.get("required") or [])
        impl_required = set(impl.get("required") or [])
        if doc_required != impl_required:
            mismatches.append(
                f"{name}.required: 문서에만 {sorted(doc_required - impl_required)} / "
                f"구현에만 {sorted(impl_required - doc_required)}"
            )

    assert not mismatches, (
        "openapi-core.yaml 의 응답 스키마가 실구현과 갈라졌다 — 구현을 바꿨으면 "
        f"계약도 같이 바꿔라: {mismatches}"
    )


_EXTERNAL_INSPECTION_RESPONSE_ROOTS = frozenset(
    {
        "ExternalInspectionPendingListView",
        "ExternalInspectionLeaseView",
        "ExternalInspectionInputView",
        "ExternalInspectionReportView",
        "ExternalDisplayArtifactGrantView",
        "ExternalDisplayArtifactSealView",
        "ExternalArtifactInspectionPublicView",
        "ExternalSanitizedDisplayDownloadView",
    }
)


def _schema_component_closure(spec: dict[str, Any], roots: frozenset[str]) -> set[str]:
    """Return named-schema references reachable from the Core response roots."""
    schemas = (spec.get("components") or {}).get("schemas") or {}
    pending = list(roots)
    discovered: set[str] = set()
    while pending:
        name = pending.pop()
        if name in discovered:
            continue
        assert name in schemas, f"response schema {name} is undefined"
        discovered.add(name)
        nodes = [schemas[name]]
        while nodes:
            node = nodes.pop()
            if isinstance(node, dict):
                ref = node.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                    pending.append(ref.rsplit("/", 1)[-1])
                nodes.extend(node.values())
            elif isinstance(node, list):
                nodes.extend(node)
    return discovered


def _without_presentation_metadata(value: Any) -> Any:
    """Titles and descriptions do not change validation semantics."""
    if isinstance(value, dict):
        return {
            key: _without_presentation_metadata(item)
            for key, item in value.items()
            if key not in {"title", "description"}
        }
    if isinstance(value, list):
        return [_without_presentation_metadata(item) for item in value]
    return value


def test_external_inspection_response_schemas_match_implementation_recursively(
    tmp_path: Path,
) -> None:
    """Nested inspection DTO constraints must be as precise as FastAPI's models."""
    doc = _doc()
    impl = _implemented_spec(tmp_path)
    documented = _schema_component_closure(doc, _EXTERNAL_INSPECTION_RESPONSE_ROOTS)
    implemented = _schema_component_closure(impl, _EXTERNAL_INSPECTION_RESPONSE_ROOTS)
    assert documented == implemented
    doc_schemas = doc["components"]["schemas"]
    impl_schemas = impl["components"]["schemas"]
    mismatches = [
        name
        for name in sorted(documented)
        if _without_presentation_metadata(doc_schemas[name])
        != _without_presentation_metadata(impl_schemas[name])
    ]
    assert not mismatches, f"nested response schemas drifted: {mismatches}"


@pytest.mark.parametrize(
    ("schema_name", "payload"),
    (
        (
            "ExternalInspectionLeaseView",
            {
                "verdict": "NOT_A_CORE_VERDICT",
                "request": None,
                "leaseExpiresAt": None,
                "phase": None,
                "fence": None,
            },
        ),
        (
            "ExternalInspectionInputView",
            {
                "verdict": "LEASED",
                "request": {},
                "policy": None,
                "artifacts": [],
                "phase": None,
                "nextAction": None,
                "acceptedReport": None,
            },
        ),
        (
            "ExternalArtifactInputView",
            {
                "entryId": "ortho",
                "kind": "NOT_A_PROCESSING_ARTIFACT",
                "observedSha256": "sha256:" + "a" * 64,
                "observedSizeBytes": 1,
                "contentType": "image/tiff",
                "downloadUrl": None,
                "requiredHeaders": {},
            },
        ),
        (
            "ExternalDisplayArtifactGrantView",
            {
                "verdict": "DECLARATION_RECORDED",
                "phase": "RUNNING",
                "declaration": {"declaredDerivativeSizeBytes": 0},
                "uploadUrl": None,
                "requiredHeaders": {},
            },
        ),
        (
            "ExternalDisplayArtifactSealView",
            {"verdict": "SEALED", "phase": "SEALED", "receipt": {}},
        ),
        (
            "PublicInspectionDetailView",
            {
                "state": "INSPECTION_REPORTED",
                "request": {"requestId": ""},
                "phase": None,
                "outcome": None,
                "report": None,
            },
        ),
    ),
)
def test_external_inspection_response_schemas_reject_malformed_nested_values(
    schema_name: str, payload: dict[str, Any]
) -> None:
    """Generic nested objects/enums would silently admit impossible worker/public DTOs."""
    doc = _doc()
    validator = Draft202012Validator(
        {
            "$ref": f"#/components/schemas/{schema_name}",
            "components": doc["components"],
        }
    )
    assert list(validator.iter_errors(payload)), schema_name


def test_external_reconstruction_contract_uses_opaque_submission_refs() -> None:
    """A raw customer submission ID is domain data, never a path address."""
    paths = _doc()["paths"]
    base = "/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    revision_paths = (
        base + "/{submission_ref}/revisions/{revision}",
        base + "/{submission_ref}/revisions/{revision}/upload-grants",
        base + "/{submission_ref}/revisions/{revision}/seal",
    )
    assert all(path in paths for path in revision_paths)
    assert not any("{submission_id}" in path for path in paths if path.startswith(base))
    for path in revision_paths:
        operation = next(item for name, item in paths[path].items() if name in _HTTP_METHODS)
        submission_ref = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["in"] == "path" and parameter["name"] == "submission_ref"
        )
        assert submission_ref["schema"] == {
            "type": "string",
            "pattern": "^ers-v1-[0-9a-f]{64}$",
        }
    view = _doc()["components"]["schemas"]["ExternalReconstructionRevisionView"]
    assert "submissionRef" in view["required"]
    assert view["properties"]["submissionRef"] == {
        "type": "string",
        "pattern": "^ers-v1-[0-9a-f]{64}$",
    }


def test_external_evidence_idempotency_header_constraints_match_runtime(tmp_path: Path) -> None:
    base = (
        "/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
        "{submission_ref}/revisions/{revision}/evidence"
    )
    paths = (base, base + "/{evidence_ref}/upload-grant", base + "/{evidence_ref}/seal")
    expected = {
        "type": "string",
        "minLength": 1,
        "maxLength": 255,
        "pattern": ".*\\S.*",
    }
    doc = _doc()["paths"]
    implementation = _implemented_spec(tmp_path)["paths"]
    for path in paths:
        doc_header = next(
            parameter
            for parameter in doc[path]["post"]["parameters"]
            if parameter["in"] == "header" and parameter["name"] == "Idempotency-Key"
        )
        impl_header = next(
            parameter
            for parameter in implementation[path]["post"]["parameters"]
            if parameter["in"] == "header" and parameter["name"] == "Idempotency-Key"
        )
        assert {key: doc_header["schema"][key] for key in expected} == expected
        assert {key: impl_header["schema"][key] for key in expected} == expected


def test_named_response_models_are_bound_in_doc(tmp_path: Path) -> None:
    """⑤ 바인딩 검사 — 실구현이 named 모델을 반환하는 operation 은 문서의 2xx
    응답 중 하나가 **같은 이름을 ``$ref``** 해야 한다.

    이게 없으면 ④는 이미 적힌 스키마만 지킬 뿐, 새 엔드포인트가 자유 문자열
    description 만 달고 들어오는 경로(원래의 실패 모드)를 막지 못한다.

    **상태코드까지 묶어서 본다.** 원래는 operation 의 2xx 집합만 비교했는데, 그건
    FastAPI 가 ``Response(status_code=...)`` 동적 지정을 OpenAPI 에 200 으로 남겨
    구현 선언이 실제 런타임과 달랐기 때문이다(POST /v1/sites 는 런타임 201·선언
    200). 그 원인을 라우터 쪽에서 고쳤으므로(``status_code=201`` 명시) 이제 코드
    단위 대조가 성립한다 — 문서와 구현이 서로 다른 코드를 말하면 실패한다.
    """
    doc = _doc()
    impl_paths = _implemented_spec(tmp_path)["paths"]

    violations: list[str] = []
    for path, spec in doc["paths"].items():
        if spec.get("x-status") == "planned":
            continue
        for method, operation in spec.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            impl_op = (impl_paths.get(path) or {}).get(method) or {}
            impl_bindings = {
                (code, model)
                for code, response in (impl_op.get("responses") or {}).items()
                if code.startswith("2")
                for model in [_ref_name(_json_schema(response))]
                if model is not None
            }
            if not impl_bindings:
                continue
            doc_bindings = {
                (str(code), model)
                for code, response in (operation.get("responses") or {}).items()
                if str(code).startswith("2")
                for model in [_ref_name(_json_schema(response))]
                if model is not None
            }
            unbound = impl_bindings - doc_bindings
            if unbound:
                violations.append(
                    f"{method.upper()} {path}: {sorted(f'{c} {m}' for c, m in unbound)}"
                )

    assert not violations, (
        "실구현이 반환하는 응답 모델을 문서가 $ref 로 묶지 않았다 — 자유 문자열 "
        f"description 은 대조되지 않는다: {violations}"
    )


def test_flight_artifact_candidate_contract_stays_unbound() -> None:
    """Pilot export 후보가 실행 계약으로 오인될 여지를 명세에서 차단한다.

    일반 경로·응답 모델 대조는 "필드가 존재한다"까지만 보장한다. 이 경계에서는
    값의 의미가 더 중요하다: candidate 보관 API가 상태를 EXECUTABLE로 바꾸거나
    validator 세대를 누락해도 앱은 여전히 경로 검사만 통과할 수 있다. ADR-KSI-028의
    후보-권한 분리를 계약 레벨에서 고정한다.
    """
    doc = _doc()
    paths = doc["paths"]
    ingest = paths["/v1/missions/{mission_id}/flight-artifacts/pilot-export"]["post"]
    assert {
        code for code in ingest["responses"] if code in {"200", "201", "404", "422", "503"}
    } == {"200", "201", "404", "422", "503"}
    for code in ("200", "201"):
        assert _ref_name(_json_schema(ingest["responses"][code])) == "FlightArtifactIngestResponse"

    candidate = doc["components"]["schemas"]["FlightArtifactCandidateResponse"]
    properties = candidate["properties"]
    assert properties["source"] == {"const": "DJI_PILOT_EXPORT"}
    assert properties["status"] == {"const": "VALIDATED_CANDIDATE_UNBOUND"}
    assert properties["validatorVersion"]["const"] == "1.0"
    assert properties["executable"]["const"] is False
    assert properties["envelopeCheck"]["enum"] == ["COMPATIBLE", "NOT_COMPARABLE"]
    assert "executable" not in set(candidate.get("required") or [])

    download = paths["/v1/missions/{mission_id}/flight-artifacts/{candidate_id}/download"]["get"]
    headers = download["responses"]["200"]["headers"]
    assert headers["X-KSI-FlightArtifact-Status"]["schema"]["const"] == (
        "VALIDATED_CANDIDATE_UNBOUND"
    )
    assert headers["X-KSI-Executable"]["schema"]["const"] == "false"


# ── ⑥ 소비자(대시보드) 대조 ────────────────────────────────────────────────
#
# ④·⑤ 는 Core ↔ 계약만 닫는다. 실제로 깨지는 자리는 하나 더 있다:
# ``apps/dashboard/src/lib/core-api/types.ts`` 는 이 계약의 **수동 복제본**이라,
# 서버가 필드를 바꿔도 프런트의 tsc 는 계속 green 이고 런타임에서만 undefined 가
# 흐른다. 계약과 이름이 같은 interface 는 필드 집합도 같아야 한다.

_DASHBOARD_TYPES = _REPO_ROOT / "apps" / "dashboard" / "src" / "lib" / "core-api" / "types.ts"

# 계약에 있지만 대시보드가 소비하지 않는 모델은 대조 대상이 아니다 —
# types.ts 에 같은 이름의 interface 가 있을 때만 본다(없는 것은 "아직 안 쓴다"는
# 정상 상태이지 drift 가 아니다).


def _parse_ts_interfaces(source: str) -> dict[str, tuple[set[str], str | None]]:
    """``export interface X extends Y { ... }`` → {X: (필드집합, 부모 or None)}.

    한 단계 중첩까지만 본다 — 이 파일의 모델은 전부 평면이고, 중첩이 생기면
    그 자체가 계약 형태를 벗어난 신호라 여기서 실패하는 편이 낫다.
    """
    result: dict[str, tuple[set[str], str | None]] = {}
    header = re.compile(r"^export interface (\w+)(?: extends (\w+))?\s*\{")
    field = re.compile(r"^\s{2}(\w+)\??:")
    lines = source.splitlines()
    index = 0
    while index < len(lines):
        match = header.match(lines[index])
        if match is None:
            index += 1
            continue
        name, parent = match.group(1), match.group(2)
        fields: set[str] = set()
        depth = 1
        index += 1
        while index < len(lines) and depth > 0:
            line = lines[index]
            depth += line.count("{") - line.count("}")
            if depth > 0:
                found = field.match(line)
                if found is not None:
                    fields.add(found.group(1))
            index += 1
        result[name] = (fields, parent)
    return result


def test_dashboard_types_match_contract_schemas() -> None:
    """⑥ 소비자 대조 — types.ts 의 interface 가 계약 모델과 같은 이름이면 필드
    집합도 같아야 한다(상속은 펼쳐서 비교)."""
    doc_schemas = (_doc().get("components") or {}).get("schemas") or {}
    interfaces = _parse_ts_interfaces(_DASHBOARD_TYPES.read_text(encoding="utf-8"))
    assert interfaces, "types.ts 에서 interface 를 하나도 못 읽었다 — 파서가 깨졌다"

    def resolved(name: str, seen: frozenset[str] = frozenset()) -> set[str]:
        fields, parent = interfaces[name]
        if parent is None or parent in seen or parent not in interfaces:
            return set(fields)
        return set(fields) | resolved(parent, seen | {name})

    compared: list[str] = []
    mismatches: list[str] = []
    for name, spec in doc_schemas.items():
        if name not in interfaces:
            continue
        compared.append(name)
        contract_fields = set(spec.get("properties") or {})
        ts_fields = resolved(name)
        if contract_fields != ts_fields:
            mismatches.append(
                f"{name}: 계약에만 {sorted(contract_fields - ts_fields)} / "
                f"types.ts 에만 {sorted(ts_fields - contract_fields)}"
            )

    assert compared, (
        "계약 모델과 이름이 같은 interface 가 types.ts 에 하나도 없다 — 이름 규약이 "
        "바뀌었다면 이 게이트는 아무것도 지키지 못한다"
    )
    assert not mismatches, (
        "대시보드가 소비하는 타입이 계약과 갈라졌다 — 서버 필드가 바뀌면 프런트 "
        f"tsc 는 green 인 채 런타임에서만 깨진다: {mismatches}"
    )


# ── ⑥ 요청 본문 깊은 대조 (s2-residual-hardening #4) ────────────────────────
#
# ④/⑤가 닫은 것은 **응답** 쪽이다. 요청 본문은 문서에 인라인 object 로 적혀 있어
# 어떤 게이트도 실구현 요청 모델과 대조하지 않았다 — 서버가 새 필수 입력을
# 요구하기 시작해도(예: lawnmower 의 captureIntervalM) 계약은 조용히 낡는다.
# 클라이언트는 문서를 보고 만들므로, 이 방향의 drift 는 곧 통합 실패다.


def _resolve_ref(spec: dict[str, Any], node: Any) -> Any:
    """``$ref`` 를 실제 스키마로 펼친다(구현 spec 은 named 모델을 참조한다)."""
    seen = 0
    while isinstance(node, dict) and "$ref" in node:
        seen += 1
        if seen > 32:  # 순환 참조 방어 — 무한 루프 대신 그대로 돌려준다
            return node
        pointer = node["$ref"]
        if not pointer.startswith("#/"):
            return node
        target: Any = spec
        for part in pointer[2:].split("/"):
            if not isinstance(target, dict) or part not in target:
                return node
            target = target[part]
        node = target
    return node


def _json_request_schema(spec: dict[str, Any], operation: dict[str, Any]) -> Any:
    body = operation.get("requestBody") or {}
    schema = ((body.get("content") or {}).get("application/json") or {}).get("schema")
    return _resolve_ref(spec, schema) if schema is not None else None


def _compare_object_fields(
    *,
    doc_spec: dict[str, Any],
    impl_spec: dict[str, Any],
    doc_node: Any,
    impl_node: Any,
    trail: str,
    mismatches: list[str],
    compared_objects: list[str],
) -> None:
    """두 스키마 트리의 object 계층을 필드 이름·필수 여부로 재귀 대조한다.

    타입까지는 보지 않는다 — ④와 같은 규약이다. 잡으려는 실패는 "한쪽에만
    필드가 생기거나 사라지는 것"과 "한쪽만 필수로 요구하는 것"이다.
    """
    doc_node = _resolve_ref(doc_spec, doc_node)
    impl_node = _resolve_ref(impl_spec, impl_node)
    if not isinstance(doc_node, dict) or not isinstance(impl_node, dict):
        return
    # anyOf/allOf(Optional 필드가 만드는 형태)는 object 분기 하나만 골라 내려간다.
    for combinator in ("anyOf", "allOf", "oneOf"):
        if combinator in impl_node and "properties" not in impl_node:
            for branch in impl_node[combinator]:
                resolved = _resolve_ref(impl_spec, branch)
                if isinstance(resolved, dict) and "properties" in resolved:
                    impl_node = resolved
                    break
    doc_props = doc_node.get("properties")
    impl_props = impl_node.get("properties")
    if not isinstance(doc_props, dict) or not isinstance(impl_props, dict):
        return
    # 실제로 필드 집합을 맞대본 횟수 — 호출자의 공허 방지 검사가 이걸 센다
    # (독립 재검토 P2-4: operation 수만 세면 문서 body 를 description 만 남기고
    # 비워도 카운터가 유지돼 "대조했다"가 거짓이 된다).
    compared_objects.append(trail)

    doc_fields, impl_fields = set(doc_props), set(impl_props)
    if doc_fields != impl_fields:
        mismatches.append(
            f"{trail}: 문서에만 {sorted(doc_fields - impl_fields)} / "
            f"구현에만 {sorted(impl_fields - doc_fields)}"
        )
    doc_required = set(doc_node.get("required") or [])
    impl_required = set(impl_node.get("required") or [])
    if doc_required != impl_required:
        mismatches.append(
            f"{trail}.required: 문서에만 {sorted(doc_required - impl_required)} / "
            f"구현에만 {sorted(impl_required - doc_required)}"
        )
    for field in sorted(doc_fields & impl_fields):
        _compare_object_fields(
            doc_spec=doc_spec,
            impl_spec=impl_spec,
            doc_node=doc_props[field],
            impl_node=impl_props[field],
            trail=f"{trail}.{field}",
            mismatches=mismatches,
            compared_objects=compared_objects,
        )


def test_documented_request_bodies_match_implementation_fields(tmp_path: Path) -> None:
    """[핵심] 문서의 요청 본문 필드 집합·필수 여부가 실구현 요청 모델과 같아야 한다."""
    doc = _doc()
    impl = _implemented_spec(tmp_path)
    impl_paths = impl["paths"]

    mismatches: list[str] = []
    compared_objects: list[str] = []
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            doc_schema = _json_request_schema(doc, operation)
            if doc_schema is None:
                continue
            impl_operation = (impl_paths.get(path) or {}).get(method)
            if not isinstance(impl_operation, dict):
                continue  # 경로·메서드 존재는 ①②가 이미 본다
            impl_schema = _json_request_schema(impl, impl_operation)
            if impl_schema is None:
                mismatches.append(f"{method.upper()} {path}: 구현에 JSON 요청 본문이 없다")
                continue
            _compare_object_fields(
                doc_spec=doc,
                impl_spec=impl,
                doc_node=doc_schema,
                impl_node=impl_schema,
                trail=f"{method.upper()} {path}",
                mismatches=mismatches,
                compared_objects=compared_objects,
            )

    # 중첩까지 실제로 맞대본 object 수를 센다 — POST /v1/missions/plans 하나만도
    # contract·siteFrame·flightEnvelope·aoi·route·drone·wayline 로 여러 층이다.
    assert len(compared_objects) >= 10, (
        f"실제로 대조된 object 가 너무 적다({compared_objects}) — 게이트가 공허하다"
    )
    assert not mismatches, (
        "openapi-core.yaml 의 요청 본문이 실구현과 갈라졌다 — 구현이 새 입력을 "
        f"요구하기 시작했으면 계약도 같이 바꿔라: {mismatches}"
    )


# ── ⑦ 무인증 표면을 **코드로** 열거 (독립 재검토 P2-9) ─────────────────────
#
# ③은 문서의 자기일관성만 본다. 실구현은 FastAPI 보안 유틸 대신 수동 헤더 파싱을
# 쓰므로 앱 OpenAPI 에 security 가 실리지 않고, 그래서 "새 라우트가 인증 없이
# 추가됐다"를 잡는 게이트가 없었다 — 공개 allowlist 를 산문으로만 관리하던 상태다.
# 여기서는 라우트의 의존성 그래프를 훑어 ksi_core.auth 의 게이트를 실제로 타는지
# 본다(무엇이 열려 있나를 코드가 답하게 한다).

# 인증 없이 열려도 되는 표면 — 문서 allowlist(_PUBLIC_PATHS)와 FastAPI 기본 문서
# 라우트. 이 집합을 늘리는 변경은 곧 "새 무인증 표면"이므로 눈에 띄어야 한다.
_UNAUTHENTICATED_ALLOWLIST = _PUBLIC_PATHS | {
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}


def _walk_routes(container: Any) -> list[Any]:
    """앱의 모든 실제 라우트 — 포함된 라우터를 재귀로 펼친다.

    이 FastAPI 버전은 ``include_router`` 결과를 ``_IncludedRouter`` 로 감싸 두고 실제
    라우트는 ``original_router`` 안에 있다 — ``app.routes`` 만 훑으면 조건부 라우터가
    통째로 보이지 않는다(이 게이트를 처음 붙였을 때 보호 라우트가 0건으로 잡혔다).
    """
    found: list[Any] = []
    for route in getattr(container, "routes", None) or []:
        if getattr(route, "methods", None) and getattr(route, "path", None):
            found.append(route)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            found.extend(_walk_routes(inner))
    return found


def _has_auth_dependency(route: Any) -> bool:
    """라우트가 ``ksi_core.auth`` 의 게이트를 의존성으로 타는가."""
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False
    pending = list(dependant.dependencies)
    while pending:
        dependency = pending.pop()
        call = getattr(dependency, "call", None)
        module = getattr(call, "__module__", "")
        if module == canonical_auth.__name__ or getattr(call, "__qualname__", "").startswith(
            ("require_permission", "require_principal", "_require_device_sequence_access")
        ):
            return True
        pending.extend(dependency.dependencies)
    return False


def test_auth_dependency_guard_recognizes_canonical_auth_but_not_an_ordinary_dependency() -> None:
    app = FastAPI()

    def ordinary_dependency() -> None:
        return None

    def endpoint() -> dict[str, bool]:
        return {"ok": True}

    app.add_api_route(
        "/protected", endpoint, dependencies=[Depends(canonical_auth.require_principal())]
    )
    app.add_api_route("/ordinary", endpoint, dependencies=[Depends(ordinary_dependency)])
    routes = {route.path: route for route in _walk_routes(app)}
    assert _has_auth_dependency(routes["/protected"])
    assert not _has_auth_dependency(routes["/ordinary"])
    assert not _has_auth_dependency(routes["/openapi.json"])


def test_no_unauthenticated_route_outside_allowlist(tmp_path: Path) -> None:
    """[핵심] 최대 조립에서 인증 게이트 없는 라우트는 allowlist 뿐이다."""
    app = _max_assembly(tmp_path)

    routes = _walk_routes(app)
    assert len(routes) >= 15, f"라우트를 제대로 못 폈다({len(routes)}) — 게이트가 공허하다"
    unauthenticated = {r.path for r in routes if not _has_auth_dependency(r)}
    unexpected = unauthenticated - _UNAUTHENTICATED_ALLOWLIST

    assert not unexpected, (
        "인증 없이 열린 라우트가 allowlist 밖에 있다 — 새 표면을 열었다면 "
        f"create_app docstring 과 이 목록을 함께 갱신하라: {sorted(unexpected)}"
    )
    # 공허 방지 — 보호 라우트가 실제로 여럿 감지돼야 위 차집합에 의미가 있다.
    protected = {r.path for r in routes if _has_auth_dependency(r)}
    assert len(protected) >= 8, f"인증 게이트를 감지한 라우트가 너무 적다: {sorted(protected)}"


# ``_max_assembly`` 는 ``create_app`` 을 직접 불러 문서(openapi-core.yaml) 대조용
# "최대 조립"을 만든다 — dev(scripts/run_core_dev.py)·production(ksi_core.production)
# 두 실행 가능 조립이 실제로 타는 ``ksi_core.app_assembly.assemble_app`` 이 그 위에
# 얹는 라우트(``/ready``)는 구조적으로 위 게이트의 시야 밖이었다(독립 재검토 지적 —
# "무인증 표면은 allowlist 뿐"이라는 위 게이트가 조립 지점이 추가하는 라우트에
# 대해서는 공허했다). 여기서 실행 가능한 두 조립이 공유하는 assemble_app 도 같은
# 방식으로 훑어, "나중에 assemble_app 이 인증 없이 열어선 안 되는 라우트를 추가해도
# 이 파일의 게이트가 못 본다"는 사각지대를 닫는다.
_ASSEMBLE_APP_UNAUTHENTICATED_ALLOWLIST = frozenset({"/ready", "/metrics"})
# /metrics 는 /ready 와 같은 이유로 의도적 무인증이다 — Prometheus 스크레이퍼는
# 인증 헤더를 안 보내는 것이 표준 배치이고, 표면 자체가 집계된 카운트·지연
# 분포뿐 민감한 요청 내용을 담지 않는다(app_assembly.py 의 /metrics 라우트
# docstring 참조).


def test_no_unauthenticated_route_outside_allowlist_via_assemble_app(tmp_path: Path) -> None:
    """[핵심] ``assemble_app``(dev·production 공용 조립)이 얹는 라우트도 같은 게이트를 탄다.

    ``/ready`` 는 의도적으로 무인증이다(오케스트레이터 헬스체크는 인증 헤더를 안
    보낸다) — 그래서 별도의 작은 allowlist 에 명시적으로 올려 둔다. 이 allowlist 밖의
    무인증 라우트가 하나라도 나오면 실패한다.
    """
    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(tmp_path / name)
        opened.append(journal)
        return journal

    try:
        app = assemble_app(
            tmp_path,
            journal=_journal,
            opened=opened,
            edge_sync_snapshot_every=None,
            auth_registry=_auth_registry(),
            evidence_storage=_NullEvidenceStorage(),
            mission_signing_key=Ed25519PrivateKey.generate(),
            mission_signing_key_id="assemble-app-unauth-gate-test-key",
        )
        routes = _walk_routes(app)
        assert len(routes) >= 15, f"라우트를 제대로 못 폈다({len(routes)}) — 게이트가 공허하다"
        unauthenticated = {r.path for r in routes if not _has_auth_dependency(r)}
        allowed = _UNAUTHENTICATED_ALLOWLIST | _ASSEMBLE_APP_UNAUTHENTICATED_ALLOWLIST
        unexpected = unauthenticated - allowed
        assert not unexpected, (
            "assemble_app 이 얹은 라우트 중 인증 없이 열린 것이 allowlist 밖에 있다: "
            f"{sorted(unexpected)} — 의도한 것이면 "
            "_ASSEMBLE_APP_UNAUTHENTICATED_ALLOWLIST 를 갱신하라"
        )
        # /ready 자체가 정말 assemble_app 이 얹은 무인증 라우트라는 것도 확인한다 —
        # 그래야 위 대조가 "우연히 아무것도 안 걸렸다"가 아니라는 근거가 된다.
        assert "/ready" in unauthenticated
    finally:
        for journal in opened:
            journal.close()


def test_vertical_datum_enum_matches_the_python_ssot() -> None:
    """openapi-core.yaml 의 datum enum 이 VerticalDatum SSOT 와 어긋나지 않는다.

    **이 게이트가 없어서 실제로 드리프트가 났다**(2026-08-12): 정표고 설계면을
    잇는 작업이 ``VerticalDatum.ORTHOMETRIC_KNGEOID2024`` 를 추가하고
    ``processing-artifact.v1.2.json``·``design-surface.v1.json`` 은 갱신했는데
    openapi 만 3값으로 남았다 — 산출물 스키마는 새 값을 허용하는데 그 산출물을
    등록하는 API 계약은 금지하는 상태였다. 기존 검사들은 경로·메서드·$ref 해소·
    응답 필드 이름만 보고 **enum 값은 보지 않아** 아무것도 잡지 못했다.

    이 저장소에서 ``contracts/`` 는 코드보다 상위 권위다(00_READ_FIRST). 그러니
    권위가 코드보다 **좁은** 상태를 조용히 두지 않는다.
    """
    from ksi_event_contracts.vertical_reference import VerticalDatum

    text = _OPENAPI.read_text(encoding="utf-8")
    expected = {datum.value for datum in VerticalDatum}

    # `datum:` 바로 아래 오는 `enum: [...]` 만 본다 — 다른 enum(source 등)과 섞이지
    # 않게. openapi 는 이 자리를 flow 시퀀스 한 줄로 쓴다(파일 관례).
    found = re.findall(r"datum:\s*\n\s*type: string\s*\n\s*enum: \[([^\]]+)\]", text)
    assert found, "openapi-core.yaml 에서 datum enum 을 못 찾았다 — 게이트가 공허하다"

    for index, raw in enumerate(found):
        values = {token.strip() for token in raw.split(",")}
        assert values == expected, (
            f"openapi-core.yaml 의 datum enum #{index} 가 VerticalDatum 과 다르다.\n"
            f"  openapi: {sorted(values)}\n"
            f"  python : {sorted(expected)}\n"
            "VerticalDatum 에 값을 추가했으면 openapi 와 관련 JSON 스키마도 함께 넓힌다."
        )


# ── ⑥ 수치 제약 드리프트 — 새로 생기는 것만 잡는다 ──────────────────────────
#
# 위 ④⑤는 필드 이름·필수 여부만 대조하고 minimum/pattern 류는 의도적으로 안 본다.
# 그 사각지대에서 실제로 드리프트가 났었다(2026-08-18: openapi 는 checkpointRmseM 에
# minimum:0 을 적었는데 요청 모델에는 ge=0 이 없어 음수가 통과했다 — 그 건은 요청
# 모델을 계약 모델로 교체해 해소).
#
# **왜 전수 강제가 아니라 baseline 인가**: 현재 어긋난 24건을 전수 확인한 결과
# **실제로 뚫리는 것은 0건**이었다. 문서에만 있는 제약(maxAltitudeM 150, wayline
# 속도·높이 범위 등)은 전부 계약 모델 validator 나 생성기가 강제하고 그 실패는
# 핸들러가 422 로 잡는다(mission_plans.py 의 `except (RouteGenerationError,
# KmzBuildError)`). 즉 위치가 다를 뿐 약속이 깨진 것이 아니다. 그 24건을 전부
# 실패로 만드는 게이트는 거짓 경보만 늘리고, 진짜 신호를 그 안에 묻는다.
#
# 그래서 이 게이트는 **알려진 목록 밖의 새 드리프트**만 잡는다. 새 필드에 문서와
# 코드가 다른 제약을 달면 여기서 걸린다.

_CONSTRAINT_KEYS = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
)

#: 2026-08-18 전수 확인 — 전부 "문서와 코드의 표현 위치가 다를 뿐 약속은 지켜진다".
#: 각 항목은 실제로 그 제약이 어디서 강제되는지 확인한 뒤 등재한 것이다.
#: 새 항목을 넣으려면 **먼저 실제로 뚫리는지 확인**해야 한다 — 뚫리면 등재가 아니라 수정이다.
_KNOWN_CONSTRAINT_DRIFT: frozenset[str] = frozenset(
    {
        # 계약 모델 validator 가 강제(FlightEnvelope._envelope_is_coherent 의 규제 상한).
        "POST /v1/missions/contracts(body).flightEnvelope.maxAltitudeM.maximum",
        "POST /v1/missions/plans(body).contract.flightEnvelope.maxAltitudeM.maximum",
        # WaylineMissionConfig.__post_init__ 이 강제, 핸들러가 KmzBuildError → 422.
        "POST /v1/missions/plans(body).wayline.autoFlightSpeedMs.exclusiveMinimum",
        "POST /v1/missions/plans(body).wayline.globalTransitionalSpeedMs.exclusiveMinimum",
        "POST /v1/missions/plans(body).wayline.globalTransitionalSpeedMs.maximum",
        "POST /v1/missions/plans(body).wayline.takeoffSecurityHeightM.maximum",
        "POST /v1/missions/plans(body).wayline.takeoffSecurityHeightM.minimum",
        "POST /v1/missions/plans(body).route.captureIntervalM.minimum",
        # 구현에만 있는 제약(문서가 덜 엄격) — 코드가 더 조이는 방향이라 약속 위반이 아니다.
        "POST /v1/missions/plans(body).aoi.vertices.maxItems",
        "PUT /v1/sites/{site_id}/aoi(body).aoi.vertices.maxItems",
        "POST /v1/design-surfaces/{design_surface_id}/observations(body)"
        ".verticalCrsEpsg.exclusiveMinimum",
        "POST /v1/design-surfaces/{design_surface_id}/observations(body).verticalCrsEpsg.minimum",
        "POST /v1/edge-sync/missions/{dispatch_id}/activation-receipts(body).dispatchId.pattern",
        "POST /v1/edge-sync/missions/{dispatch_id}/activation-receipts(body).edgeDeviceId.pattern",
        "POST /v1/edge-sync/missions/{dispatch_id}/activation-receipts(body).missionId.minLength",
        "POST /v1/edge-sync/missions/{dispatch_id}/activation-receipts(body)"
        ".runtimeVersion.minLength",
        "POST /v1/edge-sync/missions/{dispatch_id}/flight-start-receipts(body)"
        ".actionReturnCode.minLength",
        "POST /v1/edge-sync/missions/{dispatch_id}/flight-start-receipts(body).dispatchId.pattern",
        "POST /v1/edge-sync/missions/{dispatch_id}/flight-start-receipts(body)"
        ".edgeDeviceId.pattern",
        "POST /v1/edge-sync/missions/{dispatch_id}/flight-start-receipts(body).missionId.minLength",
        "POST /v1/edge-sync/missions/{dispatch_id}/flight-start-receipts(body)"
        ".runtimeVersion.minLength",
        # 스토어·핸들러가 강제.
        "POST /v1/events/{event_key}/evidence(body).artifactId.minLength",
        "POST /v1/missions/{mission_id}/comparison-requests(body).zoneCrs.minLength",
        "PUT /v1/sites/{site_id}/model-age-policy(body).maxAgeDays.minimum",
    }
)


def _unwrap_optional(spec: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """``anyOf: [T, null]``(Optional 필드의 형태)에서 실제 타입 분기를 꺼낸다."""
    for branch in node.get("anyOf", ()):
        resolved = _resolve_ref(spec, branch)
        if isinstance(resolved, dict) and resolved.get("type") != "null":
            return resolved
    return node


def _collect_constraint_drift(
    *,
    doc_spec: dict[str, Any],
    impl_spec: dict[str, Any],
    doc_node: Any,
    impl_node: Any,
    trail: str,
    drift: list[str],
    seen: set[str],
) -> None:
    doc_node = _resolve_ref(doc_spec, doc_node)
    impl_node = _resolve_ref(impl_spec, impl_node)
    if not isinstance(doc_node, dict) or not isinstance(impl_node, dict):
        return
    if trail in seen or len(seen) > 4000:  # 순환 $ref·폭주 방어
        return
    seen.add(trail)
    for combinator in ("anyOf", "allOf", "oneOf"):
        if combinator in impl_node and "properties" not in impl_node:
            for branch in impl_node[combinator]:
                resolved = _resolve_ref(impl_spec, branch)
                if isinstance(resolved, dict) and "properties" in resolved:
                    _collect_constraint_drift(
                        doc_spec=doc_spec,
                        impl_spec=impl_spec,
                        doc_node=doc_node,
                        impl_node=resolved,
                        trail=trail,
                        drift=drift,
                        seen=seen,
                    )
            return
    doc_props = doc_node.get("properties") or {}
    impl_props = impl_node.get("properties") or {}
    for name in sorted(set(doc_props) & set(impl_props)):
        doc_field = _resolve_ref(doc_spec, doc_props[name])
        impl_field = _resolve_ref(impl_spec, impl_props[name])
        if not isinstance(doc_field, dict) or not isinstance(impl_field, dict):
            continue
        doc_flat = _unwrap_optional(doc_spec, doc_field)
        impl_flat = _unwrap_optional(impl_spec, impl_field)
        for key in _CONSTRAINT_KEYS:
            if doc_flat.get(key) != impl_flat.get(key):
                drift.append(f"{trail}.{name}.{key}")
        _collect_constraint_drift(
            doc_spec=doc_spec,
            impl_spec=impl_spec,
            doc_node=doc_field,
            impl_node=impl_field,
            trail=f"{trail}.{name}",
            drift=drift,
            seen=seen,
        )


def test_no_new_numeric_constraint_drift_between_doc_and_implementation(tmp_path: Path) -> None:
    """[게이트] 문서와 구현의 수치 제약이 **새로** 갈라지지 않는다.

    알려진 24건(전부 "표현 위치가 다를 뿐 약속은 지켜진다"로 실측 확인)은 위
    허용 목록에 근거와 함께 등재돼 있다. 그 밖의 항목이 나오면 **먼저 실제로
    뚫리는지 확인**해야 한다 — 뚫리면 목록 등재가 아니라 수정이다.
    """
    doc = _doc()
    impl = _implemented_spec(tmp_path)
    drift: list[str] = []
    seen: set[str] = set()

    for path, operations in (doc.get("paths") or {}).items():
        impl_path = (impl.get("paths") or {}).get(path)
        if not isinstance(operations, dict) or not isinstance(impl_path, dict):
            continue
        for method, operation in operations.items():
            impl_operation = impl_path.get(method)
            if not isinstance(operation, dict) or not isinstance(impl_operation, dict):
                continue
            doc_body = _json_request_schema(doc, operation)
            impl_body = _json_request_schema(impl, impl_operation)
            if doc_body is None or impl_body is None:
                continue
            _collect_constraint_drift(
                doc_spec=doc,
                impl_spec=impl,
                doc_node=doc_body,
                impl_node=impl_body,
                trail=f"{method.upper()} {path}(body)",
                drift=drift,
                seen=seen,
            )

    assert seen, "요청 본문을 하나도 순회하지 못했다면 이 게이트는 공허하다"
    unknown = sorted(set(drift) - _KNOWN_CONSTRAINT_DRIFT)
    assert not unknown, (
        "문서와 구현의 수치 제약이 새로 갈라졌다 — 먼저 그 제약이 실제로 뚫리는지 "
        f"확인하라(뚫리면 목록 등재가 아니라 수정이다): {unknown}"
    )


def test_the_constraint_drift_allowlist_is_not_stale(tmp_path: Path) -> None:
    """[공허 방지] 허용 목록에 **이미 해소된 항목**이 남아 있지 않다.

    해소된 항목이 목록에 남으면 그 자리에 새 드리프트가 생겨도 조용히 통과한다.
    """
    doc = _doc()
    impl = _implemented_spec(tmp_path)
    drift: list[str] = []
    seen: set[str] = set()
    for path, operations in (doc.get("paths") or {}).items():
        impl_path = (impl.get("paths") or {}).get(path)
        if not isinstance(operations, dict) or not isinstance(impl_path, dict):
            continue
        for method, operation in operations.items():
            impl_operation = impl_path.get(method)
            if not isinstance(operation, dict) or not isinstance(impl_operation, dict):
                continue
            doc_body = _json_request_schema(doc, operation)
            impl_body = _json_request_schema(impl, impl_operation)
            if doc_body is None or impl_body is None:
                continue
            _collect_constraint_drift(
                doc_spec=doc,
                impl_spec=impl,
                doc_node=doc_body,
                impl_node=impl_body,
                trail=f"{method.upper()} {path}(body)",
                drift=drift,
                seen=seen,
            )
    stale = sorted(_KNOWN_CONSTRAINT_DRIFT - set(drift))
    assert not stale, f"허용 목록에 이미 해소된 항목이 남아 있다 — 지워라: {stale}"
