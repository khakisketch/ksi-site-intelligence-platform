"""Explicit two-stage operator injection for the external result workflow.

Factories receive final Core dependencies at their construction stage. No
production mapping, historical membership, or execution limits are fabricated.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ksi_core.domains.artifacts.evidence import EvidenceStorage
from ksi_core.domains.external.ingress.external_artifact_inspections import (
    ExternalArtifactInspectionStore,
)
from ksi_core.domains.external.ingress.external_evidence_validations import (
    EvidenceMeasurementContextAuthorityPort,
    ExternalEvidenceValidationStore,
)
from ksi_core.domains.external.ingress.external_reconstruction import ExternalReconstructionStore
from ksi_core.domains.external.ingress.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityCurrentnessPort,
    PolicyAuthorityPort,
)
from ksi_core.domains.external.quantity.external_relative_volume_authorities import (
    ExternalRelativeVolumeAuthorityPort,
)
from ksi_core.domains.external.quantity.external_relative_volume_use_history import (
    ExternalRelativeVolumeHistoricalUseAuthorityPort,
)
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeExecutionActivator,
    ExternalRelativeVolumeExecutionAuthorityPort,
    ExternalRelativeVolumeInputCapabilityIssuer,
    ExternalRelativeVolumeQueuePolicy,
)
from ksi_core.domains.external.quantity.external_use_decisions import ExternalUseDecisionStore
from ksi_core.domains.sites.work_areas import WorkAreaStore
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal


class ExternalRelativeVolumeMappingFactory(Protocol):
    def __call__(
        self,
        *,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        reconstruction: ExternalReconstructionStore,
        inspections: ExternalArtifactInspectionStore,
        policy_registry: ExternalValidationPolicyRegistry,
        evidence_validations: ExternalEvidenceValidationStore,
        work_areas: WorkAreaStore,
        open_authority_journal: Callable[[Path], DurableJournal],
    ) -> ExternalRelativeVolumeAuthorityPort: ...


@dataclass(frozen=True, slots=True)
class ExternalRelativeVolumeRuntimeAuthorities:
    execution: ExternalRelativeVolumeExecutionAuthorityPort
    historical_use: ExternalRelativeVolumeHistoricalUseAuthorityPort
    activate_execution: ExternalRelativeVolumeExecutionActivator | None = None

    def __post_init__(self) -> None:
        if self.execution is None or self.historical_use is None:
            raise ValueError("external result workflow requires explicit execution and use history")
        if self.activate_execution is not None and not callable(self.activate_execution):
            raise ValueError("external result workflow execution activator must be callable")


class ExternalRelativeVolumeRuntimeFactory(Protocol):
    def __call__(
        self,
        *,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        decisions: ExternalUseDecisionStore,
        mapping: ExternalRelativeVolumeAuthorityPort,
        reconstruction: ExternalReconstructionStore,
        inspections: ExternalArtifactInspectionStore,
        policy_registry: ExternalValidationPolicyRegistry,
        evidence_validations: ExternalEvidenceValidationStore,
    ) -> ExternalRelativeVolumeRuntimeAuthorities: ...


class ExternalRelativeVolumeInputCapabilityFactory(Protocol):
    def __call__(
        self,
        *,
        reconstruction: ExternalReconstructionStore,
        storage: EvidenceStorage,
    ) -> ExternalRelativeVolumeInputCapabilityIssuer: ...


@dataclass(frozen=True, slots=True)
class ExternalResultWorkflowAssemblyConfig:
    build_mapping: ExternalRelativeVolumeMappingFactory
    build_runtime: ExternalRelativeVolumeRuntimeFactory
    queue_policy: ExternalRelativeVolumeQueuePolicy
    input_capability_issuer: ExternalRelativeVolumeInputCapabilityIssuer | None = None
    policy_authority_port: PolicyAuthorityPort | None = None
    build_policy_authority_currentness: (
        Callable[[ExternalAuthorityCurrentnessCoordinator], PolicyAuthorityCurrentnessPort] | None
    ) = None
    build_evidence_context_authority: (
        Callable[[ExternalAuthorityCurrentnessCoordinator], EvidenceMeasurementContextAuthorityPort]
        | None
    ) = None
    build_input_capability_issuer: ExternalRelativeVolumeInputCapabilityFactory | None = None

    def __post_init__(self) -> None:
        if not all(
            callable(value)
            for value in (self.build_mapping, self.build_runtime)
        ):
            raise ValueError("external result workflow requires explicit factories and byte issuer")
        if (self.input_capability_issuer is None) == (self.build_input_capability_issuer is None):
            raise ValueError("external result workflow requires exactly one byte issuer source")
        if not callable(
            self.input_capability_issuer
            if self.input_capability_issuer is not None
            else self.build_input_capability_issuer
        ):
            raise ValueError("external result workflow byte issuer source must be callable")
        if not isinstance(self.queue_policy, ExternalRelativeVolumeQueuePolicy):
            raise ValueError("external result workflow requires an explicit queue policy")
        if self.policy_authority_port is not None and not callable(
            getattr(self.policy_authority_port, "resolve", None)
        ):
            raise ValueError("external result workflow policy authority port is invalid")
        if self.policy_authority_port is not None and not callable(
            getattr(self.policy_authority_port, "resolve_historical", None)
        ):
            raise ValueError("external result workflow policy authority history is invalid")
        if (
            self.policy_authority_port is None
            and self.build_policy_authority_currentness is not None
        ):
            raise ValueError(
                "external result workflow policy currentness requires an authority port"
            )
        if self.policy_authority_port is not None and (
            self.build_policy_authority_currentness is None
            or not callable(self.build_policy_authority_currentness)
        ):
            raise ValueError("external result workflow requires policy currentness")
        if self.build_evidence_context_authority is not None and not callable(
            self.build_evidence_context_authority
        ):
            raise ValueError(
                "external result workflow evidence context authority factory is invalid"
            )
