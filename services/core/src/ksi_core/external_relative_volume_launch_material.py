"""Exact policy/evidence material for one external relative-volume worker launch.

The preflight methods deliberately run before the shared currentness guard: they
may select policy and evidence through authority-backed ports.  The final method
uses retained local projections only and is called while Core holds that guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    PolicyStatus,
)
from ksi_event_contracts.external_evidence import ExternalEvidenceRecordV1
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeRequestV1,
    ExternalVolumeInputBindingV1,
)

from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_evidence_validations import ExternalEvidenceValidationStore
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicySelectionStatus,
)

if TYPE_CHECKING:
    from ksi_core.external_relative_volumes import ExternalRelativeVolumeExecutionAuthority


@dataclass(frozen=True, slots=True)
class VolumeWorkerLaunchMaterial:
    """Complete, sealed, ordered V2 volume launch authority material."""

    validation_policy: ExternalValidationPolicyV1
    evidence_records: tuple[ExternalEvidenceRecordV1, ExternalEvidenceRecordV1]


class VolumeWorkerLaunchMaterialResolver:
    """Resolve and locally recheck exact material without inventing authority."""

    def __init__(
        self,
        *,
        policy_registry: ExternalValidationPolicyRegistry,
        evidence_validations: ExternalEvidenceValidationStore,
        currentness_coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        if policy_registry.coordinator is not currentness_coordinator:
            raise ValueError("policy registry must share currentness coordinator")
        if evidence_validations.coordinator is not currentness_coordinator:
            raise ValueError("evidence validations must share currentness coordinator")
        self._policy_registry = policy_registry
        self._evidence_validations = evidence_validations
        self._coordinator = currentness_coordinator

    @property
    def currentness_coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def preflight(
        self,
        request: ExternalRelativeVolumeRequestV1,
        authority: ExternalRelativeVolumeExecutionAuthority,
        *,
        now: datetime,
    ) -> VolumeWorkerLaunchMaterial | None:
        """Resolve live policy/evidence before capability issuance and final guard."""
        if not _request_matches_authority(request, authority):
            return None
        selection = self._policy_registry.select_for_use(
            "RELATIVE_VOLUME", (request.baseline.subject, request.current.subject)
        )
        policy = selection.policy
        if policy is None or not _policy_matches(request, authority, selection.status, policy):
            return None
        records: list[ExternalEvidenceRecordV1] = []
        for digest, binding in zip(
            request.evidence_record_digests, (request.baseline, request.current), strict=True
        ):
            resolved = self._evidence_validations.record_for_current_use(
                digest,
                subject=binding.subject,
                policy_digest=request.validation_policy_digest,
            )
            if resolved is None:
                return None
            record, context = resolved
            if not _record_matches_binding(record, context, digest, binding, policy):
                return None
            records.append(record.model_copy(deep=True))
        if len(records) != 2:
            return None
        return VolumeWorkerLaunchMaterial(
            validation_policy=policy.model_copy(deep=True),
            evidence_records=(records[0], records[1]),
        )

    def material_remains_current(
        self,
        request: ExternalRelativeVolumeRequestV1,
        authority: ExternalRelativeVolumeExecutionAuthority,
        material: VolumeWorkerLaunchMaterial,
        *,
        now: datetime,
    ) -> bool:
        """Perform the final local-only check while the coordinator is held.

        This method intentionally calls neither authority ports nor storage.  The
        registry/evidence accessors it uses are retained-projection rechecks.
        """
        if not _request_matches_authority(request, authority):
            return False
        if not self._policy_registry.locally_current_use_permitted(
            request.validation_policy_digest,
            use="RELATIVE_VOLUME",
            subjects=(request.baseline.subject, request.current.subject),
            at=now,
        ):
            return False
        policy_result = self._policy_registry.resolve(request.validation_policy_digest)
        policy = policy_result.policy
        if (
            policy_result.status is not PolicySelectionStatus.ACTIVE
            or policy is None
            or policy != material.validation_policy
            or not _policy_matches(request, authority, policy_result.status, policy)
        ):
            return False
        if len(material.evidence_records) != 2:
            return False
        for expected, digest, binding in zip(
            material.evidence_records,
            request.evidence_record_digests,
            (request.baseline, request.current),
            strict=True,
        ):
            resolved = self._evidence_validations.record_for_locally_current_use(
                digest,
                subject=binding.subject,
                policy_digest=request.validation_policy_digest,
            )
            if resolved is None:
                return False
            record, context = resolved
            if record != expected or not _record_matches_binding(
                record, context, digest, binding, policy
            ):
                return False
        return True


def _request_matches_authority(
    request: ExternalRelativeVolumeRequestV1,
    authority: ExternalRelativeVolumeExecutionAuthority,
) -> bool:
    return (
        request.request_digest is not None
        and request.baseline == authority.baseline
        and request.current == authority.current
        and request.evidence_record_digests == authority.evidence_record_digests
        and request.validation_policy_digest == authority.validation_policy_digest
        and request.execution_policy_digest == authority.execution_policy.canonical_digest()
    )


def _policy_matches(
    request: ExternalRelativeVolumeRequestV1,
    authority: ExternalRelativeVolumeExecutionAuthority,
    status: PolicySelectionStatus,
    policy: ExternalValidationPolicyV1 | None,
) -> bool:
    return (
        status is PolicySelectionStatus.ACTIVE
        and policy is not None
        and policy.status is PolicyStatus.ACTIVE
        and policy.policy_digest == request.validation_policy_digest
        and policy.policy_digest == authority.validation_policy_digest
        and policy.resource_envelope is not None
        and policy.resource_envelope_digest is not None
        and policy.resource_envelope_digest == authority.execution_policy.resource_envelope_digest
    )


def _record_matches_binding(
    record: ExternalEvidenceRecordV1,
    context: ExternalEvidenceMeasurementContextV1,
    digest: str,
    binding: ExternalVolumeInputBindingV1,
    policy: ExternalValidationPolicyV1,
) -> bool:
    """Keep data crossing this adapter exact without widening its dependencies."""
    subject = binding.subject
    observed_sha256 = binding.observed_sha256
    target_dsm_artifact_id = binding.dsm_artifact_id
    context_digest = context.context_digest
    return (
        record.evidence_record_digest == digest
        and record.evidence_record_digest == record.canonical_digest()
        and record.subject_digest == subject.canonical_digest()
        and record.target_dsm_observed_sha256 == observed_sha256
        and record.policy_digest == policy.policy_digest
        and context_digest is not None
        and context_digest == context.canonical_digest()
        and context.subject == subject
        and context.policy_digest == policy.policy_digest
        and context.target_dsm_artifact_id == target_dsm_artifact_id
        and context.target_dsm_observed_sha256 == observed_sha256
    )


__all__ = ["VolumeWorkerLaunchMaterial", "VolumeWorkerLaunchMaterialResolver"]
