"""External evidence/workflow graph around the exact WorkOrder instance."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from ksi_core.evidence import DigestBoundEvidenceStorage, ObjectStorageObservationPort
from ksi_core.external_artifact_inspections import ExternalArtifactInspectionStore
from ksi_core.external_display_artifacts import ExternalDisplayArtifactStore
from ksi_core.external_evidence import ExternalEvidenceStore
from ksi_core.external_evidence_validations import (
    CoreEvidenceValidationInputCapabilities,
    ExternalEvidenceValidationStore,
)
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.external_relative_volume_authorities import ExternalRelativeVolumeAuthorityPort
from ksi_core.external_relative_volume_launch_material import VolumeWorkerLaunchMaterialResolver
from ksi_core.external_relative_volumes import ExternalRelativeVolumeStore
from ksi_core.external_reobservation_proposals import (
    CoreExternalReobservationProposalAuthorityPort,
    ExternalReobservationProposalService,
    ExternalReobservationProposalStore,
    verify_external_reobservation_graph,
)
from ksi_core.external_result_review_sources import CoreExternalResultReviewSourceAdapter
from ksi_core.external_result_reviews import ExternalResultReviewStore
from ksi_core.external_result_workflow_api import ExternalResultReadProjector
from ksi_core.external_use_decisions import ExternalUseDecisionStore
from ksi_core.external_use_evaluator import (
    CoreExternalUseDecisionHistoryVerifier,
    ExternalUseEvaluator,
)
from ksi_core.external_validation_policy import ExternalValidationPolicyRegistry


@dataclass(frozen=True)
class ExternalSingleVolumeWiring:
    """The single-epoch volume ledger and its two execution seams, mounted together."""

    store: Any
    input_capability_issuer: Any
    execution_activator: Any


@dataclass(frozen=True)
class ExternalPreWorkOrderGraph:
    """External graph components built before its WorkOrder participant exists."""

    reconstruction_store: Any
    evidence_store: Any
    validation_policy_registry: Any
    evidence_validation_store: Any
    display_artifact_store: Any
    artifact_inspection_store: Any
    volume_mapping: Any
    use_decision_store: Any
    use_evaluator: Any
    relative_volume_store: Any
    volume_execution_activator: Any
    volume_input_capability_issuer: Any
    reviews: Any
    proposals: Any
    proposal_authority: Any
    single_volume: ExternalSingleVolumeWiring | None = None


@dataclass(frozen=True)
class ExternalCompletedGraph:
    """External workflow services that require the exact constructed WorkOrder."""

    result_workflow_service: Any
    result_read_projector: Any


def build_external_pre_work_order_graph(
    *,
    journal: Callable[[str], Any],
    evidence_storage: Any,
    external_result_workflow: Any,
    work_area_store: Any,
    site_store: Any,
    coordinator: Any,
    policy_authority_currentness: Any,
    evidence_context_authority: Any,
) -> ExternalPreWorkOrderGraph:
    reviews = None
    proposals = None
    # ADR-KSI-036 byte ingress is a separate external declaration journal.  It
    # is absent from storage-less dev assembly rather than exposing a route
    # that can never issue a constrained PUT grant or verify an observation.
    external_reconstruction_store = (
        ExternalReconstructionStore(
            journal("external-reconstruction.jsonl"), coordinator=coordinator
        )
        if evidence_storage is not None
        else None
    )
    external_evidence_store = (
        ExternalEvidenceStore(journal("external-evidence.jsonl"), coordinator=coordinator)
        if external_reconstruction_store is not None
        else None
    )
    # D5 policy starts deliberately empty: an ingress seal is retained, while
    # inspection remains visibly pending until an independently authorized
    # policy exists. These stores add no worker API in this task.
    external_validation_policy_registry = (
        ExternalValidationPolicyRegistry(
            journal("external-validation-policy.jsonl"),
            authority_port=(
                external_result_workflow.policy_authority_port
                if external_result_workflow is not None
                else None
            ),
            authority_currentness_port=policy_authority_currentness,
            coordinator=coordinator,
        )
        if external_reconstruction_store is not None
        else None
    )
    external_evidence_validation_store = (
        ExternalEvidenceValidationStore(
            journal("external-evidence-validations.jsonl"),
            evidence=external_evidence_store,
            policy_registry=external_validation_policy_registry,
            input_capabilities=CoreEvidenceValidationInputCapabilities(
                reconstruction=external_reconstruction_store,
                storage=evidence_storage,
            ),
            context_authority=evidence_context_authority,
            coordinator=coordinator,
        )
        if external_evidence_store is not None
        and external_reconstruction_store is not None
        and external_validation_policy_registry is not None
        and evidence_storage is not None
        else None
    )
    external_display_artifact_store: ExternalDisplayArtifactStore | None = None
    if (
        external_validation_policy_registry is not None
        and isinstance(evidence_storage, DigestBoundEvidenceStorage)
        and isinstance(evidence_storage, ObjectStorageObservationPort)
    ):
        external_display_artifact_store = ExternalDisplayArtifactStore(
            journal("external-sanitized-display-artifacts.jsonl"),
            policy_registry=external_validation_policy_registry,
            storage=cast(DigestBoundEvidenceStorage, evidence_storage),
            coordinator=coordinator,
        )
    external_artifact_inspection_store: ExternalArtifactInspectionStore | None = None
    if (
        external_validation_policy_registry is not None
        and external_display_artifact_store is not None
        and external_reconstruction_store is not None
    ):
        external_artifact_inspection_store = ExternalArtifactInspectionStore(
            journal("external-artifact-inspections.jsonl"),
            policy_registry=external_validation_policy_registry,
            external_reconstruction=external_reconstruction_store,
            storage=evidence_storage,
            display_store=external_display_artifact_store,
            coordinator=coordinator,
        )
    if external_reconstruction_store is not None and external_artifact_inspection_store is not None:
        from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1

        def _issue_external_inspection_after_seal(revision: Any, now: datetime) -> None:
            manifest = revision.manifest
            if manifest is None:
                return
            subject = SealedExternalSubjectV1(
                organization_id=revision.submission.organization_id,
                site_id=revision.submission.site_id,
                work_order_id=revision.work_order_id,
                submission_id=revision.submission.submission_id,
                revision=revision.submission.revision,
                submission_digest=revision.submission.submission_digest,
                manifest_digest=manifest.manifest_digest,
            )
            external_artifact_inspection_store.issue_after_seal(subject, now)

        external_reconstruction_store.bind_seal_listener(_issue_external_inspection_after_seal)
        external_artifact_inspection_store.reconcile_sealed(datetime.now(UTC))
    if external_evidence_store is not None and external_evidence_validation_store is not None:

        def _issue_evidence_validation_after_seal(item: Any, now: datetime) -> None:
            external_evidence_validation_store.issue_after_seal(item.evidence_ref, now=now)

        external_evidence_store.bind_seal_listener(_issue_evidence_validation_after_seal)
        for item in external_evidence_store.sealed_items_snapshot():
            external_evidence_validation_store.issue_after_seal(
                item.evidence_ref, now=datetime.now(UTC)
            )
    external_volume_mapping: ExternalRelativeVolumeAuthorityPort | None = None
    external_volume_input_capability_issuer = None
    if external_result_workflow is not None:
        if (
            external_reconstruction_store is None
            or external_artifact_inspection_store is None
            or external_validation_policy_registry is None
            or external_evidence_validation_store is None
            or evidence_storage is None
        ):
            raise ValueError(
                "external result workflow requires the complete external storage graph"
            )
        external_volume_input_capability_issuer = external_result_workflow.input_capability_issuer
        if external_result_workflow.build_input_capability_issuer is not None:
            external_volume_input_capability_issuer = (
                external_result_workflow.build_input_capability_issuer(
                    reconstruction=external_reconstruction_store,
                    storage=evidence_storage,
                )
            )
        if not callable(external_volume_input_capability_issuer):
            raise ValueError("external result workflow byte issuer factory returned no issuer")
        external_volume_mapping = external_result_workflow.build_mapping(
            coordinator=coordinator,
            reconstruction=external_reconstruction_store,
            inspections=external_artifact_inspection_store,
            policy_registry=external_validation_policy_registry,
            evidence_validations=external_evidence_validation_store,
            work_areas=work_area_store,
            open_authority_journal=lambda path: journal(str(path)),
        )
        if (
            external_volume_mapping is None
            or external_volume_mapping.currentness_coordinator is not coordinator
        ):
            raise ValueError("external result workflow mapping must share the Core coordinator")
    external_single_volume_mapping = getattr(external_volume_mapping, "single_mapping_port", None)
    external_use_decision_store = (
        ExternalUseDecisionStore(
            journal("external-use-decisions.jsonl"),
            coordinator=coordinator,
            history_verifier=CoreExternalUseDecisionHistoryVerifier(
                reconstruction=external_reconstruction_store,
                inspections=external_artifact_inspection_store,
                policy_registry=external_validation_policy_registry,
                evidence_validations=external_evidence_validation_store,
                relative_volume_authority=external_volume_mapping,
                single_volume_authority=external_single_volume_mapping,
            ),
        )
        if external_reconstruction_store is not None
        and external_evidence_validation_store is not None
        and external_artifact_inspection_store is not None
        and external_validation_policy_registry is not None
        else None
    )
    external_use_evaluator = (
        ExternalUseEvaluator(
            decisions=external_use_decision_store,
            reconstruction=external_reconstruction_store,
            inspections=external_artifact_inspection_store,
            policy_registry=external_validation_policy_registry,
            evidence_validations=external_evidence_validation_store,
            coordinator=coordinator,
            relative_volume_authority=external_volume_mapping,
            single_volume_authority=external_single_volume_mapping,
        )
        if external_use_decision_store is not None
        and external_reconstruction_store is not None
        and external_evidence_validation_store is not None
        and external_artifact_inspection_store is not None
        and external_validation_policy_registry is not None
        else None
    )
    external_relative_volume_store: ExternalRelativeVolumeStore | None = None
    external_single_volume: ExternalSingleVolumeWiring | None = None
    external_volume_execution_activator = None
    external_proposal_authority: CoreExternalReobservationProposalAuthorityPort | None = None
    if external_result_workflow is not None:
        assert external_use_decision_store is not None
        assert external_volume_mapping is not None
        assert external_reconstruction_store is not None
        assert external_artifact_inspection_store is not None
        assert external_validation_policy_registry is not None
        assert external_evidence_validation_store is not None
        runtime = external_result_workflow.build_runtime(
            coordinator=coordinator,
            decisions=external_use_decision_store,
            mapping=external_volume_mapping,
            reconstruction=external_reconstruction_store,
            inspections=external_artifact_inspection_store,
            policy_registry=external_validation_policy_registry,
            evidence_validations=external_evidence_validation_store,
        )
        if runtime is None or runtime.execution.currentness_coordinator is not coordinator:
            raise ValueError("external result workflow execution must share the Core coordinator")
        if runtime.historical_use is None:
            raise ValueError("external result workflow requires independent use history")
        external_volume_execution_activator = runtime.activate_execution
        external_relative_volume_store = ExternalRelativeVolumeStore(
            journal("external-relative-volumes.jsonl"),
            authority_port=runtime.execution,
            currentness_coordinator=coordinator,
            queue_policy=external_result_workflow.queue_policy,
            launch_material_resolver=VolumeWorkerLaunchMaterialResolver(
                policy_registry=external_validation_policy_registry,
                evidence_validations=external_evidence_validation_store,
                currentness_coordinator=coordinator,
            ),
        )
        if runtime.single_execution is not None:
            external_single_volume = _single_volume_wiring(
                runtime=runtime,
                journal=journal,
                coordinator=coordinator,
                workflow=external_result_workflow,
                reconstruction=external_reconstruction_store,
                policy_registry=external_validation_policy_registry,
                evidence_validations=external_evidence_validation_store,
                evidence_storage=evidence_storage,
            )
        reviews = ExternalResultReviewStore(
            journal("external-result-reviews.jsonl"),
            source_port=CoreExternalResultReviewSourceAdapter(
                volume_store=external_relative_volume_store,
                decisions=external_use_decision_store,
                historical_use_authority=runtime.historical_use,
                coordinator=coordinator,
            ),
            coordinator=coordinator,
        )
        proposals = ExternalReobservationProposalStore(
            journal("external-reobservation-proposals.jsonl"),
            coordinator=coordinator,
        )
        external_proposal_authority = CoreExternalReobservationProposalAuthorityPort(
            reviews=reviews,
            proposals=proposals,
            sites=site_store,
            work_areas=work_area_store,
            coordinator=coordinator,
        )
    return ExternalPreWorkOrderGraph(
        reconstruction_store=external_reconstruction_store,
        evidence_store=external_evidence_store,
        validation_policy_registry=external_validation_policy_registry,
        evidence_validation_store=external_evidence_validation_store,
        display_artifact_store=external_display_artifact_store,
        artifact_inspection_store=external_artifact_inspection_store,
        volume_mapping=external_volume_mapping,
        use_decision_store=external_use_decision_store,
        use_evaluator=external_use_evaluator,
        relative_volume_store=external_relative_volume_store,
        volume_execution_activator=external_volume_execution_activator,
        volume_input_capability_issuer=external_volume_input_capability_issuer,
        reviews=reviews,
        proposals=proposals,
        proposal_authority=external_proposal_authority,
        single_volume=external_single_volume,
    )


def _single_volume_wiring(
    *,
    runtime: Any,
    journal: Callable[[str], Any],
    coordinator: Any,
    workflow: Any,
    reconstruction: ExternalReconstructionStore,
    policy_registry: ExternalValidationPolicyRegistry,
    evidence_validations: ExternalEvidenceValidationStore,
    evidence_storage: Any,
) -> ExternalSingleVolumeWiring:
    from ksi_core.domains.external.quantity.external_single_volume_s3_capabilities import (
        ExternalSingleVolumeS3InputCapabilityIssuer,
    )
    from ksi_core.domains.external.quantity.external_single_volumes import (
        ExternalSingleVolumeStore,
        SingleVolumeWorkerLaunchMaterialResolver,
    )

    if runtime.single_execution.currentness_coordinator is not coordinator:
        raise ValueError("single-volume execution must share the Core coordinator")
    issuer = workflow.single_input_capability_issuer
    if issuer is None and evidence_storage is not None:
        issuer = ExternalSingleVolumeS3InputCapabilityIssuer(
            reconstruction=reconstruction,
            evidence_validations=evidence_validations,
            storage=evidence_storage,
        )
    if not callable(issuer):
        raise ValueError("single-volume execution requires worker byte capabilities")
    store = ExternalSingleVolumeStore(
        journal("external-single-volumes.jsonl"),
        authority_port=runtime.single_execution,
        currentness_coordinator=coordinator,
        queue_policy=workflow.queue_policy,
        launch_material_resolver=SingleVolumeWorkerLaunchMaterialResolver(
            policy_registry=policy_registry,
            evidence_validations=evidence_validations,
            currentness_coordinator=coordinator,
        ),
    )
    return ExternalSingleVolumeWiring(
        store=store,
        input_capability_issuer=issuer,
        execution_activator=runtime.activate_single_execution,
    )


def complete_external_graph(
    *,
    pre_work_order: ExternalPreWorkOrderGraph,
    observation_work_order_store: Any,
    site_store: Any,
    work_area_store: Any,
    coordinator: Any,
) -> ExternalCompletedGraph:
    """Finish the proposal service only after preserving its WorkOrder identity."""
    result_workflow_service = None
    result_read_projector = None
    if pre_work_order.proposal_authority is not None:
        result_workflow_service = ExternalReobservationProposalService(
            reviews=pre_work_order.reviews,
            proposals=pre_work_order.proposals,
            sites=site_store,
            work_areas=work_area_store,
            work_orders=observation_work_order_store,
            authority_port=pre_work_order.proposal_authority,
            coordinator=coordinator,
        )
        verify_external_reobservation_graph(service=result_workflow_service)
        assert pre_work_order.relative_volume_store is not None
        result_read_projector = ExternalResultReadProjector(
            volumes=pre_work_order.relative_volume_store,
            workflow=result_workflow_service,
        )
    return ExternalCompletedGraph(
        result_workflow_service=result_workflow_service,
        result_read_projector=result_read_projector,
    )
