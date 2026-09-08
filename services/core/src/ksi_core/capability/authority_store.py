"""Durable CAP-2 evidence, CAP-3 approval, and CAP-4 activation authority journal.

This module persists ``RouteEvidenceQualification`` and the explicit
``ProductCapabilityApproval`` and ``OperationalCapabilityActivation`` layers
above it.  CAP-4 persists an operations authorization and durable authority
suspension only.  It deliberately has no live route observation, public
operational projection, Mission, or device-runtime wiring (REQ-ACQ-103,
REQ-SEC-101; INV-040/041/060).

The journal is causally ordered by append order.  Live mutation and replay use
the same mapping, scope, predecessor, and digest validation.  Corruption that
can be attributed to one exact evidence chain isolates that chain; malformed
top-level data that cannot be attributed seals the whole capability-authority
subsystem by refusing store construction.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, cast

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_domain.capability_contract import (
    CanonicalTransportCapability,
    CapabilityContractError,
    CapabilityIntegrationPath,
    OperationalCapabilityActivation,
    ProductCapabilityApproval,
    RouteEvidenceQualification,
    SourceCapabilityId,
    UnsupportedCapabilityGateVersionError,
    UnsupportedCapabilityMappingVersionError,
    resolve_capability_gate,
    resolve_capability_mapping,
)
from pydantic import Field, ValidationError, field_validator, model_validator

from ksi_core.api_base import CamelModel, iso_utc
from ksi_core.auth import Permission, Principal, PrincipalKind, Role, principal_permissions
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identifiers import is_path_safe_identifier

CAPABILITY_AUTHORITY_JOURNAL_NAME = "capability-authority.jsonl"
CAPABILITY_AUTHORITY_EVENT_SCHEMA_VERSION = "1.0"

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_SCOPE_VALUES = frozenset({"*", "ANY", "LEGACY_UNSCOPED"})
_CAPABILITY_POLICY_ACTOR = "system.capability-authority"


class CapabilityAuthorityError(Exception):
    """Base class for typed CAP-2 authority failures."""


class CapabilityAuthorityValidationError(CapabilityAuthorityError):
    """A live command does not satisfy the evidence contract."""


class CapabilityAuthorityAuthorizationError(CapabilityAuthorityError):
    """An authenticated actor lacks explicit product-approval authority."""


class CapabilityAuthorityIdempotencyConflict(CapabilityAuthorityError):
    """An operation ID was reused for a different canonical command."""


class CapabilityAuthorityConflict(CapabilityAuthorityError):
    """A live record ID, predecessor, event ID, or revocation conflicts."""


class CapabilityAuthorityUnavailableError(CapabilityAuthorityError):
    """The journal or the command's exact evidence chain is unavailable."""


class CapabilityAuthorityRecoveryError(CapabilityAuthorityError):
    """Unattributable journal corruption prevents safe subsystem startup."""


class UnsupportedCapabilityFreshnessPolicyError(ValueError):
    """No exact CAP-4 freshness-policy identity is configured."""


class CapabilityAuthorityEventKind(StrEnum):
    EVIDENCE_RECORDED = "capability-evidence-recorded"
    EVIDENCE_REVOKED = "capability-evidence-revoked"
    PRODUCT_APPROVED = "capability-product-approved"
    PRODUCT_APPROVAL_REVOKED = "capability-product-approval-revoked"
    ACTIVATION_AUTHORIZED = "capability-activation-authorized"
    ACTIVATION_SUSPENDED = "capability-activation-suspended"
    ACTIVATION_REVOKED = "capability-activation-revoked"


class CapabilityAuthorityChainStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    BLOCKED_CORRUPT = "BLOCKED_CORRUPT"
    BLOCKED_UNSUPPORTED_VERSION = "BLOCKED_UNSUPPORTED_VERSION"


class EvidenceLifecycleStatus(StrEnum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    BLOCKED_CORRUPT = "BLOCKED_CORRUPT"
    BLOCKED_UNSUPPORTED_VERSION = "BLOCKED_UNSUPPORTED_VERSION"


class ApprovalLifecycleStatus(StrEnum):
    NOT_YET_EFFECTIVE = "NOT_YET_EFFECTIVE"
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    PREREQUISITE_INVALID = "PREREQUISITE_INVALID"
    BLOCKED_CORRUPT = "BLOCKED_CORRUPT"
    BLOCKED_UNSUPPORTED_VERSION = "BLOCKED_UNSUPPORTED_VERSION"


class ActivationLifecycleStatus(StrEnum):
    NOT_YET_EFFECTIVE = "NOT_YET_EFFECTIVE"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    PREREQUISITE_INVALID = "PREREQUISITE_INVALID"
    BLOCKED_CORRUPT = "BLOCKED_CORRUPT"
    BLOCKED_UNSUPPORTED_VERSION = "BLOCKED_UNSUPPORTED_VERSION"


class ActivationAuthorityCause(StrEnum):
    EVIDENCE_REVOKED = "EVIDENCE_REVOKED"
    APPROVAL_REVOKED = "APPROVAL_REVOKED"
    CONFIGURED_SCOPE_INVALIDATED = "CONFIGURED_SCOPE_INVALIDATED"
    MAPPING_GATE_INVALIDATED = "MAPPING_GATE_INVALIDATED"
    EXPLICIT_OPERATION = "EXPLICIT_OPERATION"


class CapabilityEvidenceType(StrEnum):
    FIELD = "FIELD"
    HIL = "HIL"
    REGRESSION = "REGRESSION"
    VENDOR_DECLARATION = "VENDOR_DECLARATION"


class EquipmentRole(StrEnum):
    AIRCRAFT = "AIRCRAFT"
    GATEWAY = "GATEWAY"
    EDGE = "EDGE"
    DOCK = "DOCK"


_REQUIRED_EQUIPMENT_ROLES: dict[CapabilityIntegrationPath, frozenset[EquipmentRole]] = {
    CapabilityIntegrationPath.DJI_CLOUD: frozenset({EquipmentRole.AIRCRAFT, EquipmentRole.GATEWAY}),
    CapabilityIntegrationPath.PSDK_MANIFOLD: frozenset(
        {EquipmentRole.AIRCRAFT, EquipmentRole.GATEWAY, EquipmentRole.EDGE}
    ),
    CapabilityIntegrationPath.MANIFOLD_DIRECT: frozenset(
        {EquipmentRole.AIRCRAFT, EquipmentRole.EDGE}
    ),
    CapabilityIntegrationPath.MSDK_FIELD: frozenset(
        {EquipmentRole.AIRCRAFT, EquipmentRole.GATEWAY, EquipmentRole.EDGE}
    ),
    CapabilityIntegrationPath.DJI_DOCK: frozenset({EquipmentRole.AIRCRAFT, EquipmentRole.DOCK}),
}


def _sha256_prefixed(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _validate_digest(value: str, field: str) -> str:
    if _DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be lowercase sha256:<64hex>")
    return value


def _validate_exact_utc(value: datetime, field: str) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None:
        raise ValueError(f"{field} must be timezone-aware UTC")
    if offset.total_seconds() != 0:
        raise ValueError(f"{field} must use UTC")
    return value.astimezone(UTC)


def _validate_nonblank_exact(value: str, field: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field} must be non-blank without surrounding whitespace")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} must be valid UTF-8") from exc
    return value


def _validate_scope_component(value: str, field: str) -> str:
    value = _validate_nonblank_exact(value, field)
    if value.upper() in _FORBIDDEN_SCOPE_VALUES:
        raise ValueError(f"{field} may not be wildcard or LEGACY_UNSCOPED")
    return value


class EquipmentComponentV1(CamelModel):
    role: EquipmentRole
    product_family: Annotated[str, Field(max_length=200)]
    hardware_model: Annotated[str, Field(max_length=200)]
    hardware_revision: Annotated[str, Field(max_length=200)]
    firmware_or_image_version: Annotated[str, Field(max_length=300)]

    @field_validator(
        "product_family",
        "hardware_model",
        "hardware_revision",
        "firmware_or_image_version",
    )
    @classmethod
    def _scope_values_are_exact(cls, value: str, info: Any) -> str:
        return _validate_scope_component(value, info.field_name)


class EquipmentScopeV1(CamelModel):
    components: tuple[EquipmentComponentV1, ...]

    @model_validator(mode="after")
    def _roles_are_unique_and_sorted(self) -> EquipmentScopeV1:
        roles = tuple(component.role.value for component in self.components)
        if not roles:
            raise ValueError("equipmentScope.components may not be empty")
        if len(set(roles)) != len(roles):
            raise ValueError("equipmentScope role may appear only once")
        if roles != tuple(sorted(roles)):
            raise ValueError("equipmentScope.components must be sorted by role")
        return self

    @property
    def canonical_digest(self) -> str:
        return _sha256_prefixed(self.model_dump(mode="json", by_alias=True))


class TestedDeploymentRefV1(CamelModel):
    organization_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    site_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    gateway_device_id: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")] = None
    edge_device_id: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")] = None


class CapabilityEvidenceRecordV1(CamelModel):
    evidence_record_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    canonical_capability_id: CanonicalTransportCapability
    source_capability_id: SourceCapabilityId
    mapping_version: Annotated[str, Field(min_length=1, max_length=100)]
    integration_path: CapabilityIntegrationPath
    equipment_scope: EquipmentScopeV1
    equipment_scope_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    test_build_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    policy_scope_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    evidence_type: CapabilityEvidenceType
    evidence_artifact_ref: Annotated[str, Field(min_length=1, max_length=2048)]
    evidence_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    procedure_ref: Annotated[str, Field(min_length=1, max_length=2048)]
    procedure_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    performer_principal_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    verifier_principal_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    performed_at: datetime
    verified_at: datetime
    verification_result: RouteEvidenceQualification
    valid_until: datetime
    tested_deployment_ref: TestedDeploymentRefV1 | None = None
    supersedes_evidence_record_id: Annotated[
        str | None, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    ] = None

    @field_validator("evidence_artifact_ref", "procedure_ref")
    @classmethod
    def _refs_are_stable_text(cls, value: str, info: Any) -> str:
        value = _validate_nonblank_exact(value, info.field_name)
        if any(ord(character) < 0x20 for character in value):
            raise ValueError(f"{info.field_name} may not contain control characters")
        return value

    @field_validator("performed_at", "verified_at", "valid_until")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _validate_exact_utc(value, info.field_name)

    @model_validator(mode="after")
    def _record_is_self_consistent(self) -> CapabilityEvidenceRecordV1:
        if self.equipment_scope_digest != self.equipment_scope.canonical_digest:
            raise ValueError("equipmentScopeDigest does not match canonical equipmentScope")
        if self.performer_principal_id == self.verifier_principal_id:
            raise ValueError("performerPrincipalId and verifierPrincipalId must be independent")
        if self.performed_at > self.verified_at:
            raise ValueError("performedAt must not be later than verifiedAt")
        if self.valid_until <= self.verified_at:
            raise ValueError("validUntil must be later than verifiedAt")
        if self.verification_result is RouteEvidenceQualification.REVOKED:
            raise ValueError("REVOKED is represented by a separate evidence-revoked event")
        if self.evidence_type is CapabilityEvidenceType.VENDOR_DECLARATION:
            raise ValueError("VENDOR_DECLARATION has no RouteEvidenceQualification authority")
        if self.supersedes_evidence_record_id == self.evidence_record_id:
            raise ValueError("an evidence record may not supersede itself")
        return self


class EvidenceApplicabilityScopeV1(CamelModel):
    canonical_capability_id: CanonicalTransportCapability
    source_capability_id: SourceCapabilityId
    integration_path: CapabilityIntegrationPath
    equipment_scope_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    test_build_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    policy_scope_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    mapping_version: Annotated[str, Field(min_length=1, max_length=100)]

    @classmethod
    def from_record(cls, record: CapabilityEvidenceRecordV1) -> EvidenceApplicabilityScopeV1:
        return cls(
            canonical_capability_id=record.canonical_capability_id,
            source_capability_id=record.source_capability_id,
            integration_path=record.integration_path,
            equipment_scope_digest=record.equipment_scope_digest,
            test_build_digest=record.test_build_digest,
            policy_scope_id=record.policy_scope_id,
            mapping_version=record.mapping_version,
        )

    @property
    def canonical_digest(self) -> str:
        return _sha256_prefixed(self.model_dump(mode="json", by_alias=True))


class CapabilityEvidenceRevocationV1(CamelModel):
    target_evidence_record_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    target_scope: EvidenceApplicabilityScopeV1
    target_scope_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("reason")
    @classmethod
    def _reason_is_exact_text(cls, value: str) -> str:
        return _validate_nonblank_exact(value, "reason")

    @model_validator(mode="after")
    def _scope_digest_matches(self) -> CapabilityEvidenceRevocationV1:
        if self.target_scope_digest != self.target_scope.canonical_digest:
            raise ValueError("targetScopeDigest does not match canonical targetScope")
        return self


class QualificationReferenceV1(CamelModel):
    """Exact immutable CAP-2 record consumed by one product approval."""

    qualification_record_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    qualification_record_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class ProductSupportMatrixEntryV1(CamelModel):
    """One exact mapped route/equipment row and its complete AND evidence set."""

    integration_path: CapabilityIntegrationPath
    equipment_scope: EquipmentScopeV1
    equipment_scope_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    qualification_references: tuple[QualificationReferenceV1, ...]

    @model_validator(mode="after")
    def _entry_is_canonical(self) -> ProductSupportMatrixEntryV1:
        if self.equipment_scope_digest != self.equipment_scope.canonical_digest:
            raise ValueError("equipmentScopeDigest does not match canonical equipmentScope")
        if not self.qualification_references:
            raise ValueError("qualificationReferences may not be empty")
        ids = tuple(
            reference.qualification_record_id for reference in self.qualification_references
        )
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("qualificationReferences must be unique and sorted by record ID")
        return self


class ProductSupportMatrixV1(CamelModel):
    """Immutable canonical support matrix snapshot pinned by an approval."""

    entries: tuple[ProductSupportMatrixEntryV1, ...]

    @model_validator(mode="after")
    def _matrix_is_canonical(self) -> ProductSupportMatrixV1:
        if not self.entries:
            raise ValueError("supportMatrix.entries may not be empty")
        keys = tuple(
            (entry.integration_path.value, entry.equipment_scope_digest) for entry in self.entries
        )
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError(
                "supportMatrix.entries must be unique and sorted by path/equipment scope"
            )
        reference_ids = tuple(
            reference.qualification_record_id
            for entry in self.entries
            for reference in entry.qualification_references
        )
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("one qualification record may appear only once in a support matrix")
        return self

    @property
    def canonical_digest(self) -> str:
        return _sha256_prefixed(self.model_dump(mode="json", by_alias=True))

    @property
    def evidence_set_digest(self) -> str:
        references = sorted(
            (
                reference.model_dump(mode="json", by_alias=True)
                for entry in self.entries
                for reference in entry.qualification_references
            ),
            key=lambda item: cast(str, item["qualificationRecordId"]),
        )
        return _sha256_prefixed({"qualificationReferences": references})


class ProductCapabilityApprovalRecordV1(CamelModel):
    """Durable CAP-3 approval; never an operational activation."""

    approval_record_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    operation_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    canonical_capability_id: CanonicalTransportCapability
    mapping_version: Annotated[str, Field(min_length=1, max_length=100)]
    gate_version: Annotated[str, Field(min_length=1, max_length=100)]
    support_matrix: ProductSupportMatrixV1
    support_matrix_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    evidence_set_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    product_build_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    policy_scope_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    approver_principal_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    approved_at: datetime
    valid_until: datetime
    decision: ProductCapabilityApproval
    supersedes_approval_record_id: Annotated[
        str | None, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    ] = None

    @field_validator("approved_at", "valid_until")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _validate_exact_utc(value, info.field_name)

    @model_validator(mode="after")
    def _record_is_self_consistent(self) -> ProductCapabilityApprovalRecordV1:
        if self.support_matrix_digest != self.support_matrix.canonical_digest:
            raise ValueError("supportMatrixDigest does not match canonical supportMatrix")
        if self.evidence_set_digest != self.support_matrix.evidence_set_digest:
            raise ValueError("evidenceSetDigest does not match exact qualification references")
        if self.valid_until <= self.approved_at:
            raise ValueError("validUntil must be later than approvedAt")
        if self.decision is not ProductCapabilityApproval.APPROVED:
            raise ValueError("CAP-3 approval record decision must be APPROVED")
        if self.supersedes_approval_record_id == self.approval_record_id:
            raise ValueError("an approval record may not supersede itself")
        return self


class ApprovalApplicabilityScopeV1(CamelModel):
    canonical_capability_id: CanonicalTransportCapability
    support_matrix_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    product_build_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    policy_scope_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    mapping_version: Annotated[str, Field(min_length=1, max_length=100)]
    gate_version: Annotated[str, Field(min_length=1, max_length=100)]

    @classmethod
    def from_record(cls, record: ProductCapabilityApprovalRecordV1) -> ApprovalApplicabilityScopeV1:
        return cls(
            canonical_capability_id=record.canonical_capability_id,
            support_matrix_digest=record.support_matrix_digest,
            product_build_digest=record.product_build_digest,
            policy_scope_id=record.policy_scope_id,
            mapping_version=record.mapping_version,
            gate_version=record.gate_version,
        )

    @property
    def canonical_digest(self) -> str:
        return _sha256_prefixed(self.model_dump(mode="json", by_alias=True))


class ProductCapabilityApprovalRevocationV1(CamelModel):
    target_approval_record_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    target_scope: ApprovalApplicabilityScopeV1
    target_scope_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("reason")
    @classmethod
    def _reason_is_exact_text(cls, value: str) -> str:
        return _validate_nonblank_exact(value, "reason")

    @model_validator(mode="after")
    def _scope_digest_matches(self) -> ProductCapabilityApprovalRevocationV1:
        if self.target_scope_digest != self.target_scope.canonical_digest:
            raise ValueError("targetScopeDigest does not match canonical targetScope")
        return self


class ConfiguredDeploymentSnapshotV1(CamelModel):
    """Trusted Core/operator configuration pinned by one CAP-4 authorization."""

    configuration_record_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    configuration_revision: Annotated[int, Field(ge=1)]
    organization_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    site_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    gateway_device_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    edge_device_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    integration_path: CapabilityIntegrationPath
    canonical_capability_id: CanonicalTransportCapability
    equipment_scope: EquipmentScopeV1
    equipment_scope_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    runtime_build_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    policy_scope_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    mapping_version: Annotated[str, Field(min_length=1, max_length=100)]
    gate_version: Annotated[str, Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def _snapshot_is_exact(self) -> ConfiguredDeploymentSnapshotV1:
        if self.gateway_device_id == self.edge_device_id:
            raise ValueError("gatewayDeviceId and edgeDeviceId must be distinct")
        if self.equipment_scope_digest != self.equipment_scope.canonical_digest:
            raise ValueError("equipmentScopeDigest does not match configured equipmentScope")
        return self

    @property
    def canonical_digest(self) -> str:
        return _sha256_prefixed(self.model_dump(mode="json", by_alias=True))


class ActivationApplicabilityScopeV1(CamelModel):
    organization_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    site_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    gateway_device_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    edge_device_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    integration_path: CapabilityIntegrationPath
    canonical_capability_id: CanonicalTransportCapability
    equipment_scope_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    runtime_build_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    policy_scope_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    mapping_version: Annotated[str, Field(min_length=1, max_length=100)]
    gate_version: Annotated[str, Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def _device_identities_are_distinct(self) -> ActivationApplicabilityScopeV1:
        if self.gateway_device_id == self.edge_device_id:
            raise ValueError("gatewayDeviceId and edgeDeviceId must be distinct")
        return self

    @property
    def canonical_digest(self) -> str:
        return _sha256_prefixed(self.model_dump(mode="json", by_alias=True))


class OperationalCapabilityActivationRecordV1(CamelModel):
    """Durable CAP-4 authority only; it contains no live route observation."""

    activation_authorization_id: Annotated[
        str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    ]
    operation_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    activation_scope: ActivationApplicabilityScopeV1
    activation_scope_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    approval_record_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    approval_record_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    support_matrix_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    evidence_set_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    qualification_references: tuple[QualificationReferenceV1, ...]
    configured_deployment: ConfiguredDeploymentSnapshotV1
    configured_deployment_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    freshness_policy_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    freshness_policy_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    prerequisite_set_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    activating_principal_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    activated_at: datetime
    valid_until: datetime
    effective_state: OperationalCapabilityActivation
    supersedes_activation_authorization_id: Annotated[
        str | None, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    ] = None

    @field_validator("activated_at", "valid_until")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _validate_exact_utc(value, info.field_name)

    @property
    def prerequisite_payload(self) -> dict[str, Any]:
        return {
            "activationScope": self.activation_scope.model_dump(mode="json", by_alias=True),
            "activationScopeDigest": self.activation_scope_digest,
            "approvalRecordId": self.approval_record_id,
            "approvalRecordDigest": self.approval_record_digest,
            "supportMatrixDigest": self.support_matrix_digest,
            "evidenceSetDigest": self.evidence_set_digest,
            "qualificationReferences": [
                item.model_dump(mode="json", by_alias=True)
                for item in self.qualification_references
            ],
            "configuredDeploymentDigest": self.configured_deployment_digest,
            "freshnessPolicyId": self.freshness_policy_id,
            "freshnessPolicyDigest": self.freshness_policy_digest,
        }

    @model_validator(mode="after")
    def _record_is_self_consistent(self) -> OperationalCapabilityActivationRecordV1:
        if self.activation_scope_digest != self.activation_scope.canonical_digest:
            raise ValueError("activationScopeDigest does not match canonical activationScope")
        if self.configured_deployment_digest != self.configured_deployment.canonical_digest:
            raise ValueError(
                "configuredDeploymentDigest does not match canonical configuredDeployment"
            )
        scope = self.activation_scope
        configured = self.configured_deployment
        exact_pairs = (
            (scope.organization_id, configured.organization_id),
            (scope.site_id, configured.site_id),
            (scope.gateway_device_id, configured.gateway_device_id),
            (scope.edge_device_id, configured.edge_device_id),
            (scope.integration_path, configured.integration_path),
            (scope.canonical_capability_id, configured.canonical_capability_id),
            (scope.equipment_scope_digest, configured.equipment_scope_digest),
            (scope.runtime_build_digest, configured.runtime_build_digest),
            (scope.policy_scope_id, configured.policy_scope_id),
            (scope.mapping_version, configured.mapping_version),
            (scope.gate_version, configured.gate_version),
        )
        if any(left != right for left, right in exact_pairs):
            raise ValueError("configuredDeployment does not exactly match activationScope")
        ids = tuple(item.qualification_record_id for item in self.qualification_references)
        if not ids or ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("qualificationReferences must be non-empty, unique, and sorted")
        if self.prerequisite_set_digest != _sha256_prefixed(self.prerequisite_payload):
            raise ValueError("prerequisiteSetDigest does not match canonical prerequisite set")
        if self.valid_until <= self.activated_at:
            raise ValueError("validUntil must be later than activatedAt")
        if self.effective_state is not OperationalCapabilityActivation.ACTIVE:
            raise ValueError("new CAP-4 activation record state must be ACTIVE")
        if self.supersedes_activation_authorization_id == self.activation_authorization_id:
            raise ValueError("an activation authorization may not supersede itself")
        return self


class CapabilityActivationSuspendedV1(CamelModel):
    operation_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    target_activation_authorization_id: Annotated[
        str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    ]
    target_activation_record_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    target_scope: ActivationApplicabilityScopeV1
    target_scope_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    cause: ActivationAuthorityCause
    cause_record_id: Annotated[
        str | None, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    ] = None
    cause_record_digest: Annotated[str | None, Field(pattern=r"^sha256:[0-9a-f]{64}$")] = None
    suspending_principal_id: Annotated[
        str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    ]
    suspended_at: datetime

    @field_validator("reason")
    @classmethod
    def _reason_is_exact_text(cls, value: str) -> str:
        return _validate_nonblank_exact(value, "reason")

    @field_validator("suspended_at")
    @classmethod
    def _time_is_utc(cls, value: datetime) -> datetime:
        return _validate_exact_utc(value, "suspendedAt")

    @model_validator(mode="after")
    def _target_and_cause_are_exact(self) -> CapabilityActivationSuspendedV1:
        if self.target_scope_digest != self.target_scope.canonical_digest:
            raise ValueError("targetScopeDigest does not match canonical targetScope")
        if (self.cause_record_id is None) != (self.cause_record_digest is None):
            raise ValueError("causeRecordId and causeRecordDigest must be supplied together")
        return self


class CapabilityActivationRevokedV1(CamelModel):
    operation_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    target_activation_authorization_id: Annotated[
        str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    ]
    target_activation_record_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    target_scope: ActivationApplicabilityScopeV1
    target_scope_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    revoking_principal_id: Annotated[
        str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    ]
    revoked_at: datetime

    @field_validator("reason")
    @classmethod
    def _reason_is_exact_text(cls, value: str) -> str:
        return _validate_nonblank_exact(value, "reason")

    @field_validator("revoked_at")
    @classmethod
    def _time_is_utc(cls, value: datetime) -> datetime:
        return _validate_exact_utc(value, "revokedAt")

    @model_validator(mode="after")
    def _target_is_exact(self) -> CapabilityActivationRevokedV1:
        if self.target_scope_digest != self.target_scope.canonical_digest:
            raise ValueError("targetScopeDigest does not match canonical targetScope")
        return self


class CapabilityAuthorityEventV1(CamelModel):
    """Structurally parsed envelope; semantic validation is replay-policy aware."""

    schema_version: str
    event_id: str
    operation_id: str
    kind: str
    occurred_at: str
    actor_principal_id: str
    actor_principal_kind: str
    payload: dict[str, Any]
    payload_sha256: str


@dataclass(frozen=True, slots=True, order=True)
class EvidenceChainIdentity:
    canonical_capability_id: str
    source_capability_id: str
    integration_path: str
    equipment_scope_digest: str
    test_build_digest: str
    policy_scope_id: str
    mapping_version: str

    @classmethod
    def from_scope(cls, scope: EvidenceApplicabilityScopeV1) -> EvidenceChainIdentity:
        return cls(
            canonical_capability_id=scope.canonical_capability_id.value,
            source_capability_id=scope.source_capability_id.value,
            integration_path=scope.integration_path.value,
            equipment_scope_digest=scope.equipment_scope_digest,
            test_build_digest=scope.test_build_digest,
            policy_scope_id=scope.policy_scope_id,
            mapping_version=scope.mapping_version,
        )


@dataclass(frozen=True, slots=True, order=True)
class ApprovalChainIdentity:
    canonical_capability_id: str
    support_matrix_digest: str
    product_build_digest: str
    policy_scope_id: str
    mapping_version: str
    gate_version: str

    @classmethod
    def from_scope(cls, scope: ApprovalApplicabilityScopeV1) -> ApprovalChainIdentity:
        return cls(
            canonical_capability_id=scope.canonical_capability_id.value,
            support_matrix_digest=scope.support_matrix_digest,
            product_build_digest=scope.product_build_digest,
            policy_scope_id=scope.policy_scope_id,
            mapping_version=scope.mapping_version,
            gate_version=scope.gate_version,
        )


@dataclass(frozen=True, slots=True, order=True)
class ActivationChainIdentity:
    organization_id: str
    site_id: str
    gateway_device_id: str
    edge_device_id: str
    integration_path: str
    canonical_capability_id: str
    equipment_scope_digest: str
    runtime_build_digest: str
    policy_scope_id: str
    mapping_version: str
    gate_version: str

    @classmethod
    def from_scope(cls, scope: ActivationApplicabilityScopeV1) -> ActivationChainIdentity:
        return cls(
            organization_id=scope.organization_id,
            site_id=scope.site_id,
            gateway_device_id=scope.gateway_device_id,
            edge_device_id=scope.edge_device_id,
            integration_path=scope.integration_path.value,
            canonical_capability_id=scope.canonical_capability_id.value,
            equipment_scope_digest=scope.equipment_scope_digest,
            runtime_build_digest=scope.runtime_build_digest,
            policy_scope_id=scope.policy_scope_id,
            mapping_version=scope.mapping_version,
            gate_version=scope.gate_version,
        )


AuthorityChainIdentity = EvidenceChainIdentity | ApprovalChainIdentity | ActivationChainIdentity


@dataclass(frozen=True, slots=True)
class CapabilityEvidenceProjection:
    record: CapabilityEvidenceRecordV1
    record_digest: str
    event_id: str
    operation_id: str
    lifecycle_status: EvidenceLifecycleStatus
    superseded_by_record_id: str | None = None
    revoked_by_event_id: str | None = None

    @property
    def is_currently_effective_qualification(self) -> bool:
        return (
            self.lifecycle_status is EvidenceLifecycleStatus.CURRENT
            and self.record.verification_result is RouteEvidenceQualification.QUALIFIED
        )


@dataclass(frozen=True, slots=True)
class CapabilityEvidenceMutationResult:
    event_id: str
    operation_id: str
    record: CapabilityEvidenceRecordV1
    record_digest: str


@dataclass(frozen=True, slots=True)
class ProductCapabilityApprovalProjection:
    record: ProductCapabilityApprovalRecordV1
    record_digest: str
    event_id: str
    operation_id: str
    lifecycle_status: ApprovalLifecycleStatus
    prerequisites_valid: bool
    prerequisite_issues: tuple[str, ...] = ()
    superseded_by_record_id: str | None = None
    revoked_by_event_id: str | None = None

    @property
    def is_currently_effective(self) -> bool:
        return self.lifecycle_status is ApprovalLifecycleStatus.CURRENT and self.prerequisites_valid


@dataclass(frozen=True, slots=True)
class ProductCapabilityApprovalMutationResult:
    event_id: str
    operation_id: str
    record: ProductCapabilityApprovalRecordV1
    record_digest: str


@dataclass(frozen=True, slots=True)
class OperationalCapabilityActivationProjection:
    record: OperationalCapabilityActivationRecordV1
    record_digest: str
    event_id: str
    operation_id: str
    lifecycle_status: ActivationLifecycleStatus
    prerequisites_valid: bool
    prerequisite_issues: tuple[str, ...] = ()
    superseded_by_authorization_id: str | None = None
    suspended_by_event_id: str | None = None
    revoked_by_event_id: str | None = None

    @property
    def is_current_durable_authority(self) -> bool:
        return (
            self.lifecycle_status is ActivationLifecycleStatus.ACTIVE
            and self.prerequisites_valid
        )


@dataclass(frozen=True, slots=True)
class OperationalCapabilityActivationMutationResult:
    event_id: str
    operation_id: str
    record: OperationalCapabilityActivationRecordV1
    record_digest: str


@dataclass(frozen=True, slots=True)
class _StoredOperation:
    command_digest: str
    event_id: str
    kind: CapabilityAuthorityEventKind
    result_record_id: str
    chain: AuthorityChainIdentity


class _ReplaySemanticError(Exception):
    def __init__(self, message: str, *, unsupported_version: bool = False) -> None:
        super().__init__(message)
        self.unsupported_version = unsupported_version


def capability_evidence_record_digest(record: CapabilityEvidenceRecordV1) -> str:
    return _sha256_prefixed(record.model_dump(mode="json", by_alias=True))


def product_capability_approval_record_digest(
    record: ProductCapabilityApprovalRecordV1,
) -> str:
    return _sha256_prefixed(record.model_dump(mode="json", by_alias=True))


def operational_capability_activation_record_digest(
    record: OperationalCapabilityActivationRecordV1,
) -> str:
    return _sha256_prefixed(record.model_dump(mode="json", by_alias=True))


def _scope_for_record(record: CapabilityEvidenceRecordV1) -> EvidenceApplicabilityScopeV1:
    return EvidenceApplicabilityScopeV1.from_record(record)


def _approval_scope_for_record(
    record: ProductCapabilityApprovalRecordV1,
) -> ApprovalApplicabilityScopeV1:
    return ApprovalApplicabilityScopeV1.from_record(record)


def _activation_scope_for_record(
    record: OperationalCapabilityActivationRecordV1,
) -> ActivationApplicabilityScopeV1:
    return record.activation_scope


def _event_content_digest(raw: dict[str, Any]) -> str:
    content = dict(raw)
    content.pop("payloadSha256", None)
    return _sha256_prefixed(content)


def _command_digest(
    *, kind: CapabilityAuthorityEventKind, actor_principal_id: str, payload: dict[str, Any]
) -> str:
    command_payload = payload
    if kind is CapabilityAuthorityEventKind.EVIDENCE_REVOKED:
        command_payload = {"revocation": payload.get("revocation")}
    elif kind is CapabilityAuthorityEventKind.PRODUCT_APPROVAL_REVOKED:
        command_payload = {"approvalRevocation": payload.get("approvalRevocation")}
    return _sha256_prefixed(
        {
            "kind": kind.value,
            "actorPrincipalId": actor_principal_id,
            "actorPrincipalKind": PrincipalKind.OPERATOR.value,
            "payload": command_payload,
        }
    )


def _chain_hint(raw: dict[str, Any]) -> AuthorityChainIdentity | None:
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        return None
    body: Any
    if isinstance(payload.get("evidence"), dict):
        body = payload["evidence"]
    elif isinstance(payload.get("revocation"), dict):
        revocation = payload["revocation"]
        body = revocation.get("targetScope")
    elif isinstance(payload.get("approval"), dict):
        body = payload["approval"]
        approval_names = (
            "canonicalCapabilityId",
            "supportMatrixDigest",
            "productBuildDigest",
            "policyScopeId",
            "mappingVersion",
            "gateVersion",
        )
        approval_values = tuple(body.get(name) for name in approval_names)
        if not all(isinstance(value, str) and value for value in approval_values):
            return None
        return ApprovalChainIdentity(*cast(tuple[str, ...], approval_values))
    elif isinstance(payload.get("approvalRevocation"), dict):
        approval_revocation = payload["approvalRevocation"]
        body = approval_revocation.get("targetScope")
        if not isinstance(body, dict):
            return None
        approval_names = (
            "canonicalCapabilityId",
            "supportMatrixDigest",
            "productBuildDigest",
            "policyScopeId",
            "mappingVersion",
            "gateVersion",
        )
        approval_values = tuple(body.get(name) for name in approval_names)
        if not all(isinstance(value, str) and value for value in approval_values):
            return None
        return ApprovalChainIdentity(*cast(tuple[str, ...], approval_values))
    elif isinstance(payload.get("activation"), dict):
        body = payload["activation"].get("activationScope")
        if not isinstance(body, dict):
            return None
        activation_names = (
            "organizationId",
            "siteId",
            "gatewayDeviceId",
            "edgeDeviceId",
            "integrationPath",
            "canonicalCapabilityId",
            "equipmentScopeDigest",
            "runtimeBuildDigest",
            "policyScopeId",
            "mappingVersion",
            "gateVersion",
        )
        activation_values = tuple(body.get(name) for name in activation_names)
        if not all(isinstance(value, str) and value for value in activation_values):
            return None
        return ActivationChainIdentity(*cast(tuple[str, ...], activation_values))
    elif isinstance(payload.get("activationSuspension"), dict):
        body = payload["activationSuspension"].get("targetScope")
        if not isinstance(body, dict):
            return None
        activation_names = (
            "organizationId",
            "siteId",
            "gatewayDeviceId",
            "edgeDeviceId",
            "integrationPath",
            "canonicalCapabilityId",
            "equipmentScopeDigest",
            "runtimeBuildDigest",
            "policyScopeId",
            "mappingVersion",
            "gateVersion",
        )
        activation_values = tuple(body.get(name) for name in activation_names)
        if not all(isinstance(value, str) and value for value in activation_values):
            return None
        return ActivationChainIdentity(*cast(tuple[str, ...], activation_values))
    elif isinstance(payload.get("activationRevocation"), dict):
        body = payload["activationRevocation"].get("targetScope")
        if not isinstance(body, dict):
            return None
        activation_names = (
            "organizationId",
            "siteId",
            "gatewayDeviceId",
            "edgeDeviceId",
            "integrationPath",
            "canonicalCapabilityId",
            "equipmentScopeDigest",
            "runtimeBuildDigest",
            "policyScopeId",
            "mappingVersion",
            "gateVersion",
        )
        activation_values = tuple(body.get(name) for name in activation_names)
        if not all(isinstance(value, str) and value for value in activation_values):
            return None
        return ActivationChainIdentity(*cast(tuple[str, ...], activation_values))
    else:
        return None
    if not isinstance(body, dict):
        return None
    evidence_names = (
        "canonicalCapabilityId",
        "sourceCapabilityId",
        "integrationPath",
        "equipmentScopeDigest",
        "testBuildDigest",
        "policyScopeId",
        "mappingVersion",
    )
    evidence_values = tuple(body.get(name) for name in evidence_names)
    if not all(isinstance(value, str) and value for value in evidence_values):
        return None
    return EvidenceChainIdentity(*cast(tuple[str, ...], evidence_values))


class CapabilityAuthorityStore:
    """Core-owned append-only CAP-2/3/4 authority store."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        supported_freshness_policies: Mapping[str, str] | None = None,
    ) -> None:
        self._journal = journal
        self._lock = threading.RLock()
        self._supported_freshness_policies = dict(supported_freshness_policies or {})
        for policy_id, policy_digest in self._supported_freshness_policies.items():
            if not is_path_safe_identifier(policy_id):
                raise CapabilityAuthorityValidationError(
                    "freshness policy IDs must be path-safe identifiers"
                )
            try:
                _validate_digest(policy_digest, "freshnessPolicyDigest")
            except ValueError as exc:
                raise CapabilityAuthorityValidationError(str(exc)) from exc
        self._records: dict[str, CapabilityEvidenceRecordV1] = {}
        self._record_events: dict[str, str] = {}
        self._record_operations: dict[str, str] = {}
        self._events: dict[str, tuple[str, AuthorityChainIdentity]] = {}
        self._operations: dict[str, _StoredOperation] = {}
        self._reserved_corrupt_operations: dict[str, str] = {}
        self._superseded_by: dict[str, str] = {}
        self._revoked_by: dict[str, str] = {}
        self._approval_records: dict[str, ProductCapabilityApprovalRecordV1] = {}
        self._approval_record_events: dict[str, str] = {}
        self._approval_record_operations: dict[str, str] = {}
        self._approval_superseded_by: dict[str, str] = {}
        self._approval_revoked_by: dict[str, str] = {}
        self._activation_records: dict[str, OperationalCapabilityActivationRecordV1] = {}
        self._activation_record_events: dict[str, str] = {}
        self._activation_record_operations: dict[str, str] = {}
        self._activation_superseded_by: dict[str, str] = {}
        self._activation_suspended_by: dict[str, CapabilityActivationSuspendedV1] = {}
        self._activation_suspension_events: dict[str, str] = {}
        self._activation_revoked_by: dict[str, CapabilityActivationRevokedV1] = {}
        self._activation_revocation_events: dict[str, str] = {}
        self._chain_status: dict[
            AuthorityChainIdentity, tuple[CapabilityAuthorityChainStatus, str]
        ] = {}
        try:
            self._replay(journal)
        except CapabilityAuthorityRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise CapabilityAuthorityRecoveryError(
                f"capability-authority journal replay failed: {exc}"
            ) from exc

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    @property
    def record_count(self) -> int:
        with self._lock:
            return len(self._records)

    @property
    def operation_count(self) -> int:
        with self._lock:
            return len(self._operations)

    @property
    def approval_count(self) -> int:
        with self._lock:
            return len(self._approval_records)

    @property
    def activation_count(self) -> int:
        with self._lock:
            return len(self._activation_records)

    @property
    def isolated_chain_count(self) -> int:
        with self._lock:
            return len(self._chain_status)

    def close(self) -> None:
        self._journal.close()

    def chain_status(self, scope: EvidenceApplicabilityScopeV1) -> CapabilityAuthorityChainStatus:
        with self._lock:
            return self._chain_status.get(
                EvidenceChainIdentity.from_scope(scope),
                (CapabilityAuthorityChainStatus.AVAILABLE, ""),
            )[0]

    def chain_block_reason(self, scope: EvidenceApplicabilityScopeV1) -> str | None:
        with self._lock:
            blocked = self._chain_status.get(EvidenceChainIdentity.from_scope(scope))
            return blocked[1] if blocked is not None else None

    def get_record(self, evidence_record_id: str) -> CapabilityEvidenceRecordV1 | None:
        with self._lock:
            record = self._records.get(evidence_record_id)
            return record.model_copy(deep=True) if record is not None else None

    def get_projection(
        self, evidence_record_id: str, *, now: datetime
    ) -> CapabilityEvidenceProjection | None:
        _validate_exact_utc(now, "now")
        with self._lock:
            record = self._records.get(evidence_record_id)
            if record is None:
                return None
            scope = _scope_for_record(record)
            chain = EvidenceChainIdentity.from_scope(scope)
            blocked = self._chain_status.get(chain)
            if blocked is not None:
                lifecycle = (
                    EvidenceLifecycleStatus.BLOCKED_UNSUPPORTED_VERSION
                    if blocked[0] is CapabilityAuthorityChainStatus.BLOCKED_UNSUPPORTED_VERSION
                    else EvidenceLifecycleStatus.BLOCKED_CORRUPT
                )
            elif evidence_record_id in self._superseded_by:
                lifecycle = EvidenceLifecycleStatus.SUPERSEDED
            elif evidence_record_id in self._revoked_by:
                lifecycle = EvidenceLifecycleStatus.REVOKED
            elif record.valid_until <= now:
                lifecycle = EvidenceLifecycleStatus.EXPIRED
            else:
                lifecycle = EvidenceLifecycleStatus.CURRENT
            return CapabilityEvidenceProjection(
                record=record.model_copy(deep=True),
                record_digest=capability_evidence_record_digest(record),
                event_id=self._record_events[evidence_record_id],
                operation_id=self._record_operations[evidence_record_id],
                lifecycle_status=lifecycle,
                superseded_by_record_id=self._superseded_by.get(evidence_record_id),
                revoked_by_event_id=self._revoked_by.get(evidence_record_id),
            )

    def current_evidence(
        self, scope: EvidenceApplicabilityScopeV1, *, now: datetime
    ) -> tuple[CapabilityEvidenceProjection, ...]:
        _validate_exact_utc(now, "now")
        with self._lock:
            chain = EvidenceChainIdentity.from_scope(scope)
            if self._chain_status.get(chain) is not None:
                return ()
            projections = (
                self.get_projection(record_id, now=now)
                for record_id, record in self._records.items()
                if _scope_for_record(record) == scope
            )
            current = [
                projection
                for projection in projections
                if projection is not None
                and projection.lifecycle_status is EvidenceLifecycleStatus.CURRENT
            ]
            return tuple(sorted(current, key=lambda item: item.record.evidence_record_id))

    def effective_qualifications(
        self, scope: EvidenceApplicabilityScopeV1, *, now: datetime
    ) -> tuple[CapabilityEvidenceProjection, ...]:
        _validate_exact_utc(now, "now")
        with self._lock:
            # A negative or revoked record is an unresolved blocker until a
            # later record explicitly supersedes that exact record.  Expiry
            # alone must not turn failure evidence into a qualification.
            unresolved_blocker = any(
                record_id not in self._superseded_by
                and (
                    record.verification_result
                    in {
                        RouteEvidenceQualification.NOT_QUALIFIED,
                        RouteEvidenceQualification.BLOCKED,
                    }
                    or record_id in self._revoked_by
                )
                for record_id, record in self._records.items()
                if _scope_for_record(record) == scope
            )
            if unresolved_blocker:
                return ()
            return tuple(
                projection
                for projection in self.current_evidence(scope, now=now)
                if projection.is_currently_effective_qualification
            )

    def get_approval_record(
        self, approval_record_id: str
    ) -> ProductCapabilityApprovalRecordV1 | None:
        with self._lock:
            record = self._approval_records.get(approval_record_id)
            return record.model_copy(deep=True) if record is not None else None

    def approval_chain_status(
        self, scope: ApprovalApplicabilityScopeV1
    ) -> CapabilityAuthorityChainStatus:
        with self._lock:
            return self._chain_status.get(
                ApprovalChainIdentity.from_scope(scope),
                (CapabilityAuthorityChainStatus.AVAILABLE, ""),
            )[0]

    def get_approval_projection(
        self, approval_record_id: str, *, now: datetime
    ) -> ProductCapabilityApprovalProjection | None:
        _validate_exact_utc(now, "now")
        with self._lock:
            record = self._approval_records.get(approval_record_id)
            if record is None:
                return None
            scope = _approval_scope_for_record(record)
            blocked = self._chain_status.get(ApprovalChainIdentity.from_scope(scope))
            prerequisite_issues = self._approval_prerequisite_issues_locked(record, now=now)
            if blocked is not None:
                lifecycle = (
                    ApprovalLifecycleStatus.BLOCKED_UNSUPPORTED_VERSION
                    if blocked[0] is CapabilityAuthorityChainStatus.BLOCKED_UNSUPPORTED_VERSION
                    else ApprovalLifecycleStatus.BLOCKED_CORRUPT
                )
            elif approval_record_id in self._approval_superseded_by:
                lifecycle = ApprovalLifecycleStatus.SUPERSEDED
            elif approval_record_id in self._approval_revoked_by:
                lifecycle = ApprovalLifecycleStatus.REVOKED
            elif now < record.approved_at:
                lifecycle = ApprovalLifecycleStatus.NOT_YET_EFFECTIVE
            elif record.valid_until <= now:
                lifecycle = ApprovalLifecycleStatus.EXPIRED
            elif prerequisite_issues:
                lifecycle = ApprovalLifecycleStatus.PREREQUISITE_INVALID
            else:
                lifecycle = ApprovalLifecycleStatus.CURRENT
            return ProductCapabilityApprovalProjection(
                record=record.model_copy(deep=True),
                record_digest=product_capability_approval_record_digest(record),
                event_id=self._approval_record_events[approval_record_id],
                operation_id=self._approval_record_operations[approval_record_id],
                lifecycle_status=lifecycle,
                prerequisites_valid=not prerequisite_issues,
                prerequisite_issues=prerequisite_issues,
                superseded_by_record_id=self._approval_superseded_by.get(approval_record_id),
                revoked_by_event_id=self._approval_revoked_by.get(approval_record_id),
            )

    def effective_approvals(
        self, scope: ApprovalApplicabilityScopeV1, *, now: datetime
    ) -> tuple[ProductCapabilityApprovalProjection, ...]:
        """Return only current CAP-3 approvals for one exact applicability key."""

        _validate_exact_utc(now, "now")
        with self._lock:
            chain = ApprovalChainIdentity.from_scope(scope)
            if self._chain_status.get(chain) is not None:
                return ()
            unresolved_revocation = any(
                approval_id not in self._approval_superseded_by
                and approval_id in self._approval_revoked_by
                for approval_id, record in self._approval_records.items()
                if _approval_scope_for_record(record) == scope
            )
            if unresolved_revocation:
                return ()
            projections = (
                self.get_approval_projection(approval_id, now=now)
                for approval_id, record in self._approval_records.items()
                if _approval_scope_for_record(record) == scope
            )
            return tuple(
                sorted(
                    (
                        projection
                        for projection in projections
                        if projection is not None and projection.is_currently_effective
                    ),
                    key=lambda item: item.record.approval_record_id,
                )
            )

    def effective_approvals_for_route(
        self,
        *,
        canonical_capability_id: CanonicalTransportCapability,
        integration_path: CapabilityIntegrationPath,
        equipment_scope_digest: str,
        product_build_digest: str,
        policy_scope_id: str,
        mapping_version: str,
        gate_version: str,
        now: datetime,
    ) -> tuple[ProductCapabilityApprovalProjection, ...]:
        """Internal exact-route query; it does not project operational usability."""

        _validate_exact_utc(now, "now")
        with self._lock:
            matches: list[ProductCapabilityApprovalProjection] = []
            for approval_id, record in self._approval_records.items():
                if (
                    record.canonical_capability_id is not canonical_capability_id
                    or record.product_build_digest != product_build_digest
                    or record.policy_scope_id != policy_scope_id
                    or record.mapping_version != mapping_version
                    or record.gate_version != gate_version
                    or not any(
                        entry.integration_path is integration_path
                        and entry.equipment_scope_digest == equipment_scope_digest
                        for entry in record.support_matrix.entries
                    )
                ):
                    continue
                projection = self.get_approval_projection(approval_id, now=now)
                if projection is not None and projection.is_currently_effective:
                    matches.append(projection)
            return tuple(sorted(matches, key=lambda item: item.record.approval_record_id))

    def get_activation_record(
        self, activation_authorization_id: str
    ) -> OperationalCapabilityActivationRecordV1 | None:
        with self._lock:
            record = self._activation_records.get(activation_authorization_id)
            return record.model_copy(deep=True) if record is not None else None

    def activation_chain_status(
        self, scope: ActivationApplicabilityScopeV1
    ) -> CapabilityAuthorityChainStatus:
        with self._lock:
            return self._chain_status.get(
                ActivationChainIdentity.from_scope(scope),
                (CapabilityAuthorityChainStatus.AVAILABLE, ""),
            )[0]

    def get_activation_projection(
        self, activation_authorization_id: str, *, now: datetime
    ) -> OperationalCapabilityActivationProjection | None:
        """Project durable CAP-4 authority without any CAP-5 runtime state."""

        _validate_exact_utc(now, "now")
        with self._lock:
            record = self._activation_records.get(activation_authorization_id)
            if record is None:
                return None
            chain = ActivationChainIdentity.from_scope(record.activation_scope)
            blocked = self._chain_status.get(chain)
            prerequisite_issues = self._activation_prerequisite_issues_locked(record, now=now)
            if blocked is not None:
                lifecycle = (
                    ActivationLifecycleStatus.BLOCKED_UNSUPPORTED_VERSION
                    if blocked[0] is CapabilityAuthorityChainStatus.BLOCKED_UNSUPPORTED_VERSION
                    else ActivationLifecycleStatus.BLOCKED_CORRUPT
                )
            elif activation_authorization_id in self._activation_revoked_by:
                lifecycle = ActivationLifecycleStatus.REVOKED
            elif activation_authorization_id in self._activation_suspended_by:
                lifecycle = ActivationLifecycleStatus.SUSPENDED
            elif activation_authorization_id in self._activation_superseded_by:
                lifecycle = ActivationLifecycleStatus.SUPERSEDED
            elif now < record.activated_at:
                lifecycle = ActivationLifecycleStatus.NOT_YET_EFFECTIVE
            elif record.valid_until <= now:
                lifecycle = ActivationLifecycleStatus.EXPIRED
            elif prerequisite_issues:
                lifecycle = ActivationLifecycleStatus.PREREQUISITE_INVALID
            else:
                lifecycle = ActivationLifecycleStatus.ACTIVE
            return OperationalCapabilityActivationProjection(
                record=record.model_copy(deep=True),
                record_digest=operational_capability_activation_record_digest(record),
                event_id=self._activation_record_events[activation_authorization_id],
                operation_id=self._activation_record_operations[activation_authorization_id],
                lifecycle_status=lifecycle,
                prerequisites_valid=not prerequisite_issues,
                prerequisite_issues=prerequisite_issues,
                superseded_by_authorization_id=self._activation_superseded_by.get(
                    activation_authorization_id
                ),
                suspended_by_event_id=self._activation_suspension_events.get(
                    activation_authorization_id
                ),
                revoked_by_event_id=self._activation_revocation_events.get(
                    activation_authorization_id
                ),
            )

    def current_durable_activations(
        self, scope: ActivationApplicabilityScopeV1, *, now: datetime
    ) -> tuple[OperationalCapabilityActivationProjection, ...]:
        """Return durable authority only; this is not OperationallyUsable."""

        _validate_exact_utc(now, "now")
        with self._lock:
            chain = ActivationChainIdentity.from_scope(scope)
            if self._chain_status.get(chain) is not None:
                return ()
            projections = (
                self.get_activation_projection(activation_id, now=now)
                for activation_id, record in self._activation_records.items()
                if record.activation_scope == scope
            )
            return tuple(
                sorted(
                    (
                        projection
                        for projection in projections
                        if projection is not None
                        and projection.is_current_durable_authority
                    ),
                    key=lambda item: item.record.activation_authorization_id,
                )
            )

    def record_evidence(
        self,
        record: CapabilityEvidenceRecordV1,
        *,
        operation_id: str,
        event_id: str,
        actor_principal_id: str,
        occurred_at: datetime,
    ) -> CapabilityEvidenceMutationResult:
        normalized = self._validate_evidence_payload(record.model_dump(mode="json", by_alias=True))
        occurred_at = _validate_exact_utc(occurred_at, "occurredAt")
        if occurred_at < normalized.verified_at:
            raise CapabilityAuthorityValidationError(
                "occurredAt must not be earlier than verifiedAt"
            )
        if actor_principal_id != normalized.verifier_principal_id:
            raise CapabilityAuthorityValidationError(
                "actorPrincipalId must equal verifierPrincipalId for evidence recording"
            )
        payload = {"evidence": normalized.model_dump(mode="json", by_alias=True)}
        kind = CapabilityAuthorityEventKind.EVIDENCE_RECORDED
        command_digest = _command_digest(
            kind=kind, actor_principal_id=actor_principal_id, payload=payload
        )
        with self._lock:
            existing = self._resolve_operation_locked(operation_id, command_digest)
            if existing is not None:
                return self._mutation_result_locked(operation_id)
            self._validate_live_envelope_ids(operation_id, event_id, actor_principal_id)
            self._ensure_writable_chain_locked(_scope_for_record(normalized))
            self._preflight_record_locked(normalized)
            raw = self._build_event(
                kind=kind,
                event_id=event_id,
                operation_id=operation_id,
                actor_principal_id=actor_principal_id,
                occurred_at=occurred_at,
                payload=payload,
            )
            self._append_and_project_locked(raw, normalized, None)
            return self._mutation_result_locked(operation_id)

    def revoke_evidence(
        self,
        revocation: CapabilityEvidenceRevocationV1,
        *,
        operation_id: str,
        event_id: str,
        actor_principal_id: str,
        occurred_at: datetime,
    ) -> CapabilityEvidenceMutationResult:
        normalized = self._validate_revocation_payload(
            revocation.model_dump(mode="json", by_alias=True)
        )
        occurred_at = _validate_exact_utc(occurred_at, "occurredAt")
        command_payload = {"revocation": normalized.model_dump(mode="json", by_alias=True)}
        kind = CapabilityAuthorityEventKind.EVIDENCE_REVOKED
        command_digest = _command_digest(
            kind=kind, actor_principal_id=actor_principal_id, payload=command_payload
        )
        with self._lock:
            existing = self._resolve_operation_locked(operation_id, command_digest)
            if existing is not None:
                return self._mutation_result_locked(operation_id)
            self._validate_live_envelope_ids(operation_id, event_id, actor_principal_id)
            self._ensure_writable_chain_locked(normalized.target_scope)
            target = self._preflight_revocation_locked(normalized, occurred_at=occurred_at)
            suspensions = self._cascade_suspensions_for_evidence_locked(
                target,
                operation_id=operation_id,
                occurred_at=occurred_at,
            )
            payload = command_payload | {
                "affectedActivationSuspensions": [
                    item.model_dump(mode="json", by_alias=True) for item in suspensions
                ]
            }
            raw = self._build_event(
                kind=kind,
                event_id=event_id,
                operation_id=operation_id,
                actor_principal_id=actor_principal_id,
                occurred_at=occurred_at,
                payload=payload,
            )
            self._append_and_project_locked(raw, target, normalized, suspensions=suspensions)
            return self._mutation_result_locked(operation_id)

    def approve_product_capability(
        self,
        record: ProductCapabilityApprovalRecordV1,
        *,
        principal: Principal,
        operation_id: str,
        event_id: str,
        occurred_at: datetime,
    ) -> ProductCapabilityApprovalMutationResult:
        """Append one explicit ADMIN product approval over exact CAP-2 records."""

        self._authorize_product_approver(principal)
        normalized = self._validate_approval_payload(record.model_dump(mode="json", by_alias=True))
        occurred_at = _validate_exact_utc(occurred_at, "occurredAt")
        if normalized.operation_id != operation_id:
            raise CapabilityAuthorityValidationError(
                "approval operationId must equal the authority command operationId"
            )
        if principal.principal_id != normalized.approver_principal_id:
            raise CapabilityAuthorityAuthorizationError(
                "authenticated approver must equal approverPrincipalId"
            )
        if occurred_at < normalized.approved_at:
            raise CapabilityAuthorityValidationError(
                "occurredAt must not be earlier than approvedAt"
            )
        approval_digest = product_capability_approval_record_digest(normalized)
        payload = {
            "approval": normalized.model_dump(mode="json", by_alias=True),
            "approvalRecordDigest": approval_digest,
        }
        kind = CapabilityAuthorityEventKind.PRODUCT_APPROVED
        command_digest = _command_digest(
            kind=kind, actor_principal_id=principal.principal_id, payload=payload
        )
        with self._lock:
            prior = self._resolve_operation_locked(operation_id, command_digest)
            if prior is not None:
                return self._approval_mutation_result_locked(operation_id)
            self._validate_live_envelope_ids(operation_id, event_id, principal.principal_id)
            self._ensure_writable_approval_chain_locked(_approval_scope_for_record(normalized))
            self._preflight_approval_locked(normalized, now=normalized.approved_at)
            raw = self._build_event(
                kind=kind,
                event_id=event_id,
                operation_id=operation_id,
                actor_principal_id=principal.principal_id,
                occurred_at=occurred_at,
                payload=payload,
            )
            self._append_and_project_approval_locked(raw, normalized, None)
            return self._approval_mutation_result_locked(operation_id)

    def revoke_product_approval(
        self,
        revocation: ProductCapabilityApprovalRevocationV1,
        *,
        principal: Principal,
        operation_id: str,
        event_id: str,
        occurred_at: datetime,
    ) -> ProductCapabilityApprovalMutationResult:
        """Revoke one exact approval and atomically fence affected CAP-4 authority."""

        self._authorize_product_approver(principal)
        normalized = self._validate_approval_revocation_payload(
            revocation.model_dump(mode="json", by_alias=True)
        )
        occurred_at = _validate_exact_utc(occurred_at, "occurredAt")
        command_payload = {
            "approvalRevocation": normalized.model_dump(mode="json", by_alias=True)
        }
        kind = CapabilityAuthorityEventKind.PRODUCT_APPROVAL_REVOKED
        command_digest = _command_digest(
            kind=kind, actor_principal_id=principal.principal_id, payload=command_payload
        )
        with self._lock:
            prior = self._resolve_operation_locked(operation_id, command_digest)
            if prior is not None:
                return self._approval_mutation_result_locked(operation_id)
            self._validate_live_envelope_ids(operation_id, event_id, principal.principal_id)
            self._ensure_writable_approval_chain_locked(normalized.target_scope)
            target = self._preflight_approval_revocation_locked(normalized, occurred_at=occurred_at)
            suspensions = self._cascade_suspensions_for_approval_locked(
                target,
                operation_id=operation_id,
                occurred_at=occurred_at,
            )
            payload = command_payload | {
                "affectedActivationSuspensions": [
                    item.model_dump(mode="json", by_alias=True) for item in suspensions
                ]
            }
            raw = self._build_event(
                kind=kind,
                event_id=event_id,
                operation_id=operation_id,
                actor_principal_id=principal.principal_id,
                occurred_at=occurred_at,
                payload=payload,
            )
            self._append_and_project_approval_locked(
                raw,
                target,
                normalized,
                suspensions=suspensions,
            )
            return self._approval_mutation_result_locked(operation_id)

    def authorize_operational_capability(
        self,
        record: OperationalCapabilityActivationRecordV1,
        *,
        principal: Principal,
        operation_id: str,
        event_id: str,
        occurred_at: datetime,
    ) -> OperationalCapabilityActivationMutationResult:
        """Append CAP-4 durable authority without evaluating CAP-5 liveness."""

        self._authorize_capability_activator(principal)
        normalized = self._validate_activation_payload(
            record.model_dump(mode="json", by_alias=True)
        )
        occurred_at = _validate_exact_utc(occurred_at, "occurredAt")
        if normalized.operation_id != operation_id:
            raise CapabilityAuthorityValidationError(
                "activation operationId must equal the authority command operationId"
            )
        if principal.principal_id != normalized.activating_principal_id:
            raise CapabilityAuthorityAuthorizationError(
                "authenticated activator must equal activatingPrincipalId"
            )
        if (
            principal.organization_id == "legacy"
            or principal.organization_id != normalized.activation_scope.organization_id
        ):
            raise CapabilityAuthorityAuthorizationError(
                "activation requires an explicit matching organization principal"
            )
        if occurred_at < normalized.activated_at:
            raise CapabilityAuthorityValidationError(
                "occurredAt must not be earlier than activatedAt"
            )
        payload = {
            "activation": normalized.model_dump(mode="json", by_alias=True),
            "activationRecordDigest": operational_capability_activation_record_digest(
                normalized
            ),
        }
        kind = CapabilityAuthorityEventKind.ACTIVATION_AUTHORIZED
        command_digest = _command_digest(
            kind=kind,
            actor_principal_id=principal.principal_id,
            payload=payload,
        )
        with self._lock:
            prior = self._resolve_operation_locked(operation_id, command_digest)
            if prior is not None:
                return self._activation_mutation_result_locked(operation_id)
            self._validate_live_envelope_ids(operation_id, event_id, principal.principal_id)
            self._ensure_writable_activation_chain_locked(normalized.activation_scope)
            self._preflight_activation_locked(normalized, now=normalized.activated_at)
            raw = self._build_event(
                kind=kind,
                event_id=event_id,
                operation_id=operation_id,
                actor_principal_id=principal.principal_id,
                occurred_at=occurred_at,
                payload=payload,
            )
            self._append_and_project_activation_locked(raw, normalized, None, None)
            return self._activation_mutation_result_locked(operation_id)

    def suspend_operational_capability(
        self,
        suspension: CapabilityActivationSuspendedV1,
        *,
        principal: Principal,
        operation_id: str,
        event_id: str,
        occurred_at: datetime,
    ) -> OperationalCapabilityActivationMutationResult:
        self._authorize_capability_activator(principal)
        normalized = self._validate_activation_suspension_payload(
            suspension.model_dump(mode="json", by_alias=True)
        )
        occurred_at = _validate_exact_utc(occurred_at, "occurredAt")
        if normalized.operation_id != operation_id:
            raise CapabilityAuthorityValidationError(
                "suspension operationId must equal the authority command operationId"
            )
        if normalized.suspending_principal_id != principal.principal_id:
            raise CapabilityAuthorityAuthorizationError(
                "authenticated actor must equal suspendingPrincipalId"
            )
        if (
            principal.organization_id == "legacy"
            or principal.organization_id != normalized.target_scope.organization_id
        ):
            raise CapabilityAuthorityAuthorizationError(
                "lifecycle mutation requires an explicit matching organization principal"
            )
        if normalized.cause not in {
            ActivationAuthorityCause.EXPLICIT_OPERATION,
            ActivationAuthorityCause.CONFIGURED_SCOPE_INVALIDATED,
            ActivationAuthorityCause.MAPPING_GATE_INVALIDATED,
        }:
            raise CapabilityAuthorityValidationError(
                "direct suspension cannot impersonate evidence/approval revocation cascade"
            )
        if (
            normalized.cause is not ActivationAuthorityCause.EXPLICIT_OPERATION
            and normalized.cause_record_id is None
        ):
            raise CapabilityAuthorityValidationError(
                "configured/mapping invalidation requires an exact cause record"
            )
        if normalized.suspended_at != occurred_at:
            raise CapabilityAuthorityValidationError(
                "suspendedAt must equal event occurredAt"
            )
        payload = {"activationSuspension": normalized.model_dump(mode="json", by_alias=True)}
        kind = CapabilityAuthorityEventKind.ACTIVATION_SUSPENDED
        command_digest = _command_digest(
            kind=kind,
            actor_principal_id=principal.principal_id,
            payload=payload,
        )
        with self._lock:
            prior = self._resolve_operation_locked(operation_id, command_digest)
            if prior is not None:
                return self._activation_mutation_result_locked(operation_id)
            self._validate_live_envelope_ids(operation_id, event_id, principal.principal_id)
            self._ensure_writable_activation_chain_locked(normalized.target_scope)
            target = self._preflight_activation_suspension_locked(normalized)
            raw = self._build_event(
                kind=kind,
                event_id=event_id,
                operation_id=operation_id,
                actor_principal_id=principal.principal_id,
                occurred_at=occurred_at,
                payload=payload,
            )
            self._append_and_project_activation_locked(raw, target, normalized, None)
            return self._activation_mutation_result_locked(operation_id)

    def revoke_operational_capability(
        self,
        revocation: CapabilityActivationRevokedV1,
        *,
        principal: Principal,
        operation_id: str,
        event_id: str,
        occurred_at: datetime,
    ) -> OperationalCapabilityActivationMutationResult:
        self._authorize_capability_activator(principal)
        normalized = self._validate_activation_revocation_payload(
            revocation.model_dump(mode="json", by_alias=True)
        )
        occurred_at = _validate_exact_utc(occurred_at, "occurredAt")
        if normalized.operation_id != operation_id:
            raise CapabilityAuthorityValidationError(
                "activation revocation operationId must equal command operationId"
            )
        if normalized.revoking_principal_id != principal.principal_id:
            raise CapabilityAuthorityAuthorizationError(
                "authenticated actor must equal revokingPrincipalId"
            )
        if (
            principal.organization_id == "legacy"
            or principal.organization_id != normalized.target_scope.organization_id
        ):
            raise CapabilityAuthorityAuthorizationError(
                "lifecycle mutation requires an explicit matching organization principal"
            )
        if normalized.revoked_at != occurred_at:
            raise CapabilityAuthorityValidationError("revokedAt must equal event occurredAt")
        payload = {"activationRevocation": normalized.model_dump(mode="json", by_alias=True)}
        kind = CapabilityAuthorityEventKind.ACTIVATION_REVOKED
        command_digest = _command_digest(
            kind=kind,
            actor_principal_id=principal.principal_id,
            payload=payload,
        )
        with self._lock:
            prior = self._resolve_operation_locked(operation_id, command_digest)
            if prior is not None:
                return self._activation_mutation_result_locked(operation_id)
            self._validate_live_envelope_ids(operation_id, event_id, principal.principal_id)
            self._ensure_writable_activation_chain_locked(normalized.target_scope)
            target = self._preflight_activation_revocation_locked(normalized)
            raw = self._build_event(
                kind=kind,
                event_id=event_id,
                operation_id=operation_id,
                actor_principal_id=principal.principal_id,
                occurred_at=occurred_at,
                payload=payload,
            )
            self._append_and_project_activation_locked(raw, target, None, normalized)
            return self._activation_mutation_result_locked(operation_id)

    @staticmethod
    def _authorize_product_approver(principal: Principal) -> None:
        if (
            principal.kind is not PrincipalKind.OPERATOR
            or principal.role is not Role.ADMIN
            or Permission.CAPABILITY_PRODUCT_APPROVE not in principal_permissions(principal)
        ):
            raise CapabilityAuthorityAuthorizationError(
                "product approval requires an authenticated ADMIN operator"
            )

    @staticmethod
    def _authorize_capability_activator(principal: Principal) -> None:
        if (
            principal.kind is not PrincipalKind.OPERATOR
            or principal.role is not Role.ADMIN
            or Permission.CAPABILITY_ACTIVATE not in principal_permissions(principal)
        ):
            raise CapabilityAuthorityAuthorizationError(
                "capability activation requires an authenticated ADMIN operator"
            )

    def _validate_evidence_payload(self, raw: dict[str, Any]) -> CapabilityEvidenceRecordV1:
        try:
            record = CapabilityEvidenceRecordV1.model_validate(raw)
        except ValidationError as exc:
            raise CapabilityAuthorityValidationError(f"invalid evidence record: {exc}") from exc
        try:
            mapping = resolve_capability_mapping(record.mapping_version)
            requirement = mapping.requirement_for(
                record.canonical_capability_id, record.integration_path
            )
        except UnsupportedCapabilityMappingVersionError as exc:
            raise CapabilityAuthorityValidationError(str(exc)) from exc
        except CapabilityContractError as exc:
            raise CapabilityAuthorityValidationError(str(exc)) from exc
        if record.source_capability_id not in requirement.required_sources:
            raise CapabilityAuthorityValidationError(
                "source/path/canonical combination is not represented by the pinned mapping"
            )
        actual_roles = frozenset(component.role for component in record.equipment_scope.components)
        expected_roles = _REQUIRED_EQUIPMENT_ROLES[record.integration_path]
        if actual_roles != expected_roles:
            raise CapabilityAuthorityValidationError(
                "equipmentScope roles do not exactly match integrationPath requirements: "
                f"expected={sorted(role.value for role in expected_roles)!r}, "
                f"actual={sorted(role.value for role in actual_roles)!r}"
            )
        return record

    def _validate_revocation_payload(self, raw: dict[str, Any]) -> CapabilityEvidenceRevocationV1:
        try:
            revocation = CapabilityEvidenceRevocationV1.model_validate(raw)
        except ValidationError as exc:
            raise CapabilityAuthorityValidationError(f"invalid revocation record: {exc}") from exc
        try:
            mapping = resolve_capability_mapping(revocation.target_scope.mapping_version)
            requirement = mapping.requirement_for(
                revocation.target_scope.canonical_capability_id,
                revocation.target_scope.integration_path,
            )
        except CapabilityContractError as exc:
            raise CapabilityAuthorityValidationError(str(exc)) from exc
        if revocation.target_scope.source_capability_id not in requirement.required_sources:
            raise CapabilityAuthorityValidationError(
                "revocation target source/path/canonical combination is not mapped"
            )
        return revocation

    def _validate_approval_payload(self, raw: dict[str, Any]) -> ProductCapabilityApprovalRecordV1:
        try:
            record = ProductCapabilityApprovalRecordV1.model_validate(raw)
        except ValidationError as exc:
            raise CapabilityAuthorityValidationError(f"invalid approval record: {exc}") from exc
        try:
            mapping = resolve_capability_mapping(record.mapping_version)
            resolve_capability_gate(record.gate_version)
            for entry in record.support_matrix.entries:
                requirement = mapping.requirement_for(
                    record.canonical_capability_id, entry.integration_path
                )
                actual_roles = frozenset(
                    component.role for component in entry.equipment_scope.components
                )
                expected_roles = _REQUIRED_EQUIPMENT_ROLES[entry.integration_path]
                if actual_roles != expected_roles:
                    raise CapabilityAuthorityValidationError(
                        "supportMatrix equipment roles do not exactly match integrationPath"
                    )
                if len(entry.qualification_references) != len(requirement.required_sources):
                    raise CapabilityAuthorityValidationError(
                        "supportMatrix qualification count does not satisfy the pinned AND set"
                    )
        except (
            UnsupportedCapabilityMappingVersionError,
            UnsupportedCapabilityGateVersionError,
        ) as exc:
            raise CapabilityAuthorityValidationError(str(exc)) from exc
        except CapabilityContractError as exc:
            raise CapabilityAuthorityValidationError(str(exc)) from exc
        return record

    def _validate_approval_revocation_payload(
        self, raw: dict[str, Any]
    ) -> ProductCapabilityApprovalRevocationV1:
        try:
            revocation = ProductCapabilityApprovalRevocationV1.model_validate(raw)
        except ValidationError as exc:
            raise CapabilityAuthorityValidationError(f"invalid approval revocation: {exc}") from exc
        try:
            resolve_capability_mapping(revocation.target_scope.mapping_version)
            resolve_capability_gate(revocation.target_scope.gate_version)
        except (
            UnsupportedCapabilityMappingVersionError,
            UnsupportedCapabilityGateVersionError,
        ) as exc:
            raise CapabilityAuthorityValidationError(str(exc)) from exc
        return revocation

    def _validate_activation_payload(
        self, raw: dict[str, Any]
    ) -> OperationalCapabilityActivationRecordV1:
        try:
            record = OperationalCapabilityActivationRecordV1.model_validate(raw)
        except ValidationError as exc:
            raise CapabilityAuthorityValidationError(f"invalid activation record: {exc}") from exc
        try:
            mapping = resolve_capability_mapping(record.activation_scope.mapping_version)
            resolve_capability_gate(record.activation_scope.gate_version)
            mapping.requirement_for(
                record.activation_scope.canonical_capability_id,
                record.activation_scope.integration_path,
            )
        except (
            UnsupportedCapabilityMappingVersionError,
            UnsupportedCapabilityGateVersionError,
        ) as exc:
            raise CapabilityAuthorityValidationError(str(exc)) from exc
        except CapabilityContractError as exc:
            raise CapabilityAuthorityValidationError(str(exc)) from exc
        roles = frozenset(
            component.role for component in record.configured_deployment.equipment_scope.components
        )
        required_roles = _REQUIRED_EQUIPMENT_ROLES[record.activation_scope.integration_path]
        if roles != required_roles:
            raise CapabilityAuthorityValidationError(
                "configured deployment equipment roles do not match integrationPath"
            )
        expected_policy_digest = self._supported_freshness_policies.get(
            record.freshness_policy_id
        )
        if expected_policy_digest is None:
            error = UnsupportedCapabilityFreshnessPolicyError(
                f"unsupported freshnessPolicyId: {record.freshness_policy_id}"
            )
            raise CapabilityAuthorityValidationError(str(error)) from error
        if expected_policy_digest != record.freshness_policy_digest:
            raise CapabilityAuthorityValidationError(
                "freshnessPolicyDigest does not match the exact supported policy"
            )
        return record

    def _validate_activation_suspension_payload(
        self, raw: dict[str, Any]
    ) -> CapabilityActivationSuspendedV1:
        try:
            suspension = CapabilityActivationSuspendedV1.model_validate(raw)
        except ValidationError as exc:
            raise CapabilityAuthorityValidationError(
                f"invalid activation suspension: {exc}"
            ) from exc
        try:
            resolve_capability_mapping(suspension.target_scope.mapping_version)
            resolve_capability_gate(suspension.target_scope.gate_version)
        except (
            UnsupportedCapabilityMappingVersionError,
            UnsupportedCapabilityGateVersionError,
        ) as exc:
            raise CapabilityAuthorityValidationError(str(exc)) from exc
        return suspension

    def _validate_activation_revocation_payload(
        self, raw: dict[str, Any]
    ) -> CapabilityActivationRevokedV1:
        try:
            revocation = CapabilityActivationRevokedV1.model_validate(raw)
        except ValidationError as exc:
            raise CapabilityAuthorityValidationError(
                f"invalid activation revocation: {exc}"
            ) from exc
        try:
            resolve_capability_mapping(revocation.target_scope.mapping_version)
            resolve_capability_gate(revocation.target_scope.gate_version)
        except (
            UnsupportedCapabilityMappingVersionError,
            UnsupportedCapabilityGateVersionError,
        ) as exc:
            raise CapabilityAuthorityValidationError(str(exc)) from exc
        return revocation

    def _validate_live_envelope_ids(
        self, operation_id: str, event_id: str, actor_principal_id: str
    ) -> None:
        for name, value in (
            ("operationId", operation_id),
            ("eventId", event_id),
            ("actorPrincipalId", actor_principal_id),
        ):
            if not is_path_safe_identifier(value):
                raise CapabilityAuthorityValidationError(f"{name} must be a path-safe identifier")
        if event_id in self._events:
            raise CapabilityAuthorityConflict(f"eventId already exists: {event_id}")

    def _ensure_writable_chain_locked(self, scope: EvidenceApplicabilityScopeV1) -> None:
        chain = EvidenceChainIdentity.from_scope(scope)
        blocked = self._chain_status.get(chain)
        if blocked is not None:
            raise CapabilityAuthorityUnavailableError(
                f"evidence chain is {blocked[0].value}: {blocked[1]}"
            )
        if self._journal.sealed_reason is not None:
            raise CapabilityAuthorityUnavailableError(
                f"capability authority journal is sealed: {self._journal.sealed_reason}"
            )

    def _ensure_writable_approval_chain_locked(self, scope: ApprovalApplicabilityScopeV1) -> None:
        chain = ApprovalChainIdentity.from_scope(scope)
        blocked = self._chain_status.get(chain)
        if blocked is not None:
            raise CapabilityAuthorityUnavailableError(
                f"approval chain is {blocked[0].value}: {blocked[1]}"
            )
        if self._journal.sealed_reason is not None:
            raise CapabilityAuthorityUnavailableError(
                f"capability authority journal is sealed: {self._journal.sealed_reason}"
            )

    def _ensure_writable_activation_chain_locked(
        self, scope: ActivationApplicabilityScopeV1
    ) -> None:
        chain = ActivationChainIdentity.from_scope(scope)
        blocked = self._chain_status.get(chain)
        if blocked is not None:
            raise CapabilityAuthorityUnavailableError(
                f"activation chain is {blocked[0].value}: {blocked[1]}"
            )
        if self._journal.sealed_reason is not None:
            raise CapabilityAuthorityUnavailableError(
                f"capability authority journal is sealed: {self._journal.sealed_reason}"
            )

    def _preflight_record_locked(self, record: CapabilityEvidenceRecordV1) -> None:
        if record.evidence_record_id in self._records:
            raise CapabilityAuthorityConflict(
                f"evidenceRecordId already exists: {record.evidence_record_id}"
            )
        predecessor_id = record.supersedes_evidence_record_id
        if predecessor_id is None:
            return
        predecessor = self._records.get(predecessor_id)
        if predecessor is None:
            raise CapabilityAuthorityConflict(
                f"supersession target does not exist: {predecessor_id}"
            )
        if _scope_for_record(predecessor) != _scope_for_record(record):
            raise CapabilityAuthorityConflict(
                "supersession target must have the exact same evidence applicability scope"
            )
        if predecessor_id in self._superseded_by:
            raise CapabilityAuthorityConflict(
                f"supersession target already has a successor: {predecessor_id}"
            )

    def _preflight_revocation_locked(
        self, revocation: CapabilityEvidenceRevocationV1, *, occurred_at: datetime
    ) -> CapabilityEvidenceRecordV1:
        target = self._records.get(revocation.target_evidence_record_id)
        if target is None:
            raise CapabilityAuthorityConflict(
                f"revocation target does not exist: {revocation.target_evidence_record_id}"
            )
        if _scope_for_record(target) != revocation.target_scope:
            raise CapabilityAuthorityConflict("revocation target scope is not exact")
        if revocation.target_scope_digest != revocation.target_scope.canonical_digest:
            raise CapabilityAuthorityConflict("revocation target scope digest is not exact")
        if revocation.target_evidence_record_id in self._revoked_by:
            raise CapabilityAuthorityConflict(
                f"evidence is already revoked: {revocation.target_evidence_record_id}"
            )
        if occurred_at < target.verified_at:
            raise CapabilityAuthorityValidationError(
                "revocation occurredAt must not be earlier than target verifiedAt"
            )
        return target

    def _preflight_approval_locked(
        self, record: ProductCapabilityApprovalRecordV1, *, now: datetime
    ) -> None:
        if record.approval_record_id in self._approval_records:
            raise CapabilityAuthorityConflict(
                f"approvalRecordId already exists: {record.approval_record_id}"
            )
        predecessor_id = record.supersedes_approval_record_id
        if predecessor_id is not None:
            predecessor = self._approval_records.get(predecessor_id)
            if predecessor is None:
                raise CapabilityAuthorityConflict(
                    f"approval supersession target does not exist: {predecessor_id}"
                )
            if _approval_scope_for_record(predecessor) != _approval_scope_for_record(record):
                raise CapabilityAuthorityConflict(
                    "approval supersession target must have the exact same applicability scope"
                )
            if predecessor_id in self._approval_superseded_by:
                raise CapabilityAuthorityConflict(
                    f"approval target already has a successor: {predecessor_id}"
                )
            if record.approved_at < predecessor.approved_at:
                raise CapabilityAuthorityValidationError(
                    "successor approvedAt must not precede its approval predecessor"
                )

        issues = self._approval_prerequisite_issues_locked(record, now=now)
        if issues:
            raise CapabilityAuthorityValidationError(
                "approval evidence prerequisites are not exact/current: " + "; ".join(issues)
            )

    def _approval_prerequisite_issues_locked(
        self, record: ProductCapabilityApprovalRecordV1, *, now: datetime
    ) -> tuple[str, ...]:
        issues: list[str] = []
        mapping = resolve_capability_mapping(record.mapping_version)
        for entry in record.support_matrix.entries:
            requirement = mapping.requirement_for(
                record.canonical_capability_id, entry.integration_path
            )
            sources: list[SourceCapabilityId] = []
            for reference in entry.qualification_references:
                evidence = self._records.get(reference.qualification_record_id)
                if evidence is None:
                    issues.append(
                        f"missing qualificationRecordId={reference.qualification_record_id}"
                    )
                    continue
                actual_digest = capability_evidence_record_digest(evidence)
                if actual_digest != reference.qualification_record_digest:
                    issues.append(
                        f"qualification digest mismatch={reference.qualification_record_id}"
                    )
                    continue
                projection = self.get_projection(evidence.evidence_record_id, now=now)
                if projection is None or not projection.is_currently_effective_qualification:
                    lifecycle = (
                        projection.lifecycle_status.value if projection is not None else "MISSING"
                    )
                    issues.append(
                        f"qualification not current={evidence.evidence_record_id}:{lifecycle}"
                    )
                if evidence.canonical_capability_id is not record.canonical_capability_id:
                    issues.append(f"canonical mismatch={evidence.evidence_record_id}")
                if evidence.integration_path is not entry.integration_path:
                    issues.append(f"integration path mismatch={evidence.evidence_record_id}")
                if evidence.equipment_scope != entry.equipment_scope:
                    issues.append(f"equipment scope mismatch={evidence.evidence_record_id}")
                if evidence.equipment_scope_digest != entry.equipment_scope_digest:
                    issues.append(f"equipment digest mismatch={evidence.evidence_record_id}")
                if evidence.test_build_digest != record.product_build_digest:
                    issues.append(f"build mismatch={evidence.evidence_record_id}")
                if evidence.policy_scope_id != record.policy_scope_id:
                    issues.append(f"policy mismatch={evidence.evidence_record_id}")
                if evidence.mapping_version != record.mapping_version:
                    issues.append(f"mapping mismatch={evidence.evidence_record_id}")
                if evidence.performer_principal_id == record.approver_principal_id:
                    issues.append(f"approver is evidence performer={evidence.evidence_record_id}")
                if evidence.verifier_principal_id == record.approver_principal_id:
                    issues.append(f"approver is evidence verifier={evidence.evidence_record_id}")
                sources.append(evidence.source_capability_id)
            if tuple(sorted(sources, key=lambda item: item.value)) != requirement.required_sources:
                issues.append(
                    "required source set mismatch="
                    f"{record.canonical_capability_id.value}/{entry.integration_path.value}"
                )
        return tuple(sorted(set(issues)))

    def _preflight_approval_revocation_locked(
        self,
        revocation: ProductCapabilityApprovalRevocationV1,
        *,
        occurred_at: datetime,
    ) -> ProductCapabilityApprovalRecordV1:
        target = self._approval_records.get(revocation.target_approval_record_id)
        if target is None:
            raise CapabilityAuthorityConflict(
                f"approval revocation target does not exist: {revocation.target_approval_record_id}"
            )
        if _approval_scope_for_record(target) != revocation.target_scope:
            raise CapabilityAuthorityConflict("approval revocation target scope is not exact")
        if revocation.target_scope_digest != revocation.target_scope.canonical_digest:
            raise CapabilityAuthorityConflict(
                "approval revocation target scope digest is not exact"
            )
        if revocation.target_approval_record_id in self._approval_revoked_by:
            raise CapabilityAuthorityConflict(
                f"approval is already revoked: {revocation.target_approval_record_id}"
            )
        if occurred_at < target.approved_at:
            raise CapabilityAuthorityValidationError(
                "approval revocation occurredAt must not be earlier than target approvedAt"
            )
        return target

    def _preflight_activation_locked(
        self,
        record: OperationalCapabilityActivationRecordV1,
        *,
        now: datetime,
    ) -> None:
        activation_id = record.activation_authorization_id
        if activation_id in self._activation_records:
            raise CapabilityAuthorityConflict(
                f"activationAuthorizationId already exists: {activation_id}"
            )
        scope = record.activation_scope
        current_leaves = sorted(
            existing_id
            for existing_id, existing in self._activation_records.items()
            if existing.activation_scope == scope
            and existing_id not in self._activation_superseded_by
        )
        predecessor_id = record.supersedes_activation_authorization_id
        if predecessor_id is None:
            if current_leaves:
                raise CapabilityAuthorityConflict(
                    "existing activation authority requires exact "
                    "supersedesActivationAuthorizationId"
                )
        else:
            predecessor = self._activation_records.get(predecessor_id)
            if predecessor is None:
                raise CapabilityAuthorityConflict(
                    f"activation supersession target does not exist: {predecessor_id}"
                )
            if predecessor.activation_scope != scope:
                raise CapabilityAuthorityConflict(
                    "activation supersession target must have the exact same scope"
                )
            if predecessor_id in self._activation_superseded_by:
                raise CapabilityAuthorityConflict(
                    f"activation target already has a successor: {predecessor_id}"
                )
            if current_leaves != [predecessor_id]:
                raise CapabilityAuthorityConflict(
                    "activation supersession target must be the sole current scope leaf"
                )
            if record.activated_at < predecessor.activated_at:
                raise CapabilityAuthorityValidationError(
                    "successor activatedAt must not precede its activation predecessor"
                )

        issues = self._activation_prerequisite_issues_locked(record, now=now)
        if issues:
            raise CapabilityAuthorityValidationError(
                "activation prerequisites are not exact/current: " + "; ".join(issues)
            )

    def _activation_prerequisite_issues_locked(
        self,
        record: OperationalCapabilityActivationRecordV1,
        *,
        now: datetime,
    ) -> tuple[str, ...]:
        issues: list[str] = []
        scope = record.activation_scope
        expected_policy_digest = self._supported_freshness_policies.get(
            record.freshness_policy_id
        )
        if expected_policy_digest is None:
            issues.append(f"unsupported freshness policy={record.freshness_policy_id}")
        elif expected_policy_digest != record.freshness_policy_digest:
            issues.append("freshness policy digest mismatch")

        approval = self._approval_records.get(record.approval_record_id)
        if approval is None:
            issues.append(f"missing approvalRecordId={record.approval_record_id}")
            return tuple(sorted(set(issues)))
        if product_capability_approval_record_digest(approval) != record.approval_record_digest:
            issues.append("approval record digest mismatch")
        approval_projection = self.get_approval_projection(approval.approval_record_id, now=now)
        if approval_projection is None or not approval_projection.is_currently_effective:
            lifecycle = (
                approval_projection.lifecycle_status.value
                if approval_projection is not None
                else "MISSING"
            )
            issues.append(f"approval not current={lifecycle}")
        if approval.canonical_capability_id is not scope.canonical_capability_id:
            issues.append("approval canonical capability mismatch")
        if approval.product_build_digest != scope.runtime_build_digest:
            issues.append("approval/runtime build mismatch")
        if approval.policy_scope_id != scope.policy_scope_id:
            issues.append("approval policy scope mismatch")
        if approval.mapping_version != scope.mapping_version:
            issues.append("approval mapping version mismatch")
        if approval.gate_version != scope.gate_version:
            issues.append("approval gate version mismatch")
        if approval.support_matrix_digest != record.support_matrix_digest:
            issues.append("support matrix digest mismatch")
        if approval.evidence_set_digest != record.evidence_set_digest:
            issues.append("evidence set digest mismatch")
        if record.valid_until > approval.valid_until:
            issues.append("activation validity exceeds approval validity")

        matching_entries = tuple(
            entry
            for entry in approval.support_matrix.entries
            if entry.integration_path is scope.integration_path
            and entry.equipment_scope_digest == scope.equipment_scope_digest
        )
        if len(matching_entries) != 1:
            issues.append("approval has no exact route/equipment support-matrix entry")
        else:
            entry = matching_entries[0]
            if entry.equipment_scope != record.configured_deployment.equipment_scope:
                issues.append("configured equipment scope differs from approval")
            if entry.qualification_references != record.qualification_references:
                issues.append("selected qualification references differ from approval")
        return tuple(sorted(set(issues)))

    def _preflight_activation_suspension_locked(
        self, suspension: CapabilityActivationSuspendedV1
    ) -> OperationalCapabilityActivationRecordV1:
        target_id = suspension.target_activation_authorization_id
        target = self._activation_records.get(target_id)
        if target is None:
            raise CapabilityAuthorityConflict(
                f"activation suspension target does not exist: {target_id}"
            )
        if suspension.target_activation_record_digest != (
            operational_capability_activation_record_digest(target)
        ):
            raise CapabilityAuthorityConflict("activation suspension target digest is not exact")
        if target.activation_scope != suspension.target_scope:
            raise CapabilityAuthorityConflict("activation suspension target scope is not exact")
        if suspension.target_scope_digest != suspension.target_scope.canonical_digest:
            raise CapabilityAuthorityConflict(
                "activation suspension target scope digest is not exact"
            )
        if target_id in self._activation_superseded_by:
            raise CapabilityAuthorityConflict("superseded activation cannot be suspended")
        if target_id in self._activation_revoked_by:
            raise CapabilityAuthorityConflict("revoked activation cannot be suspended")
        if target_id in self._activation_suspended_by:
            raise CapabilityAuthorityConflict("activation is already suspended")
        if suspension.suspended_at < target.activated_at:
            raise CapabilityAuthorityValidationError(
                "suspendedAt must not be earlier than activatedAt"
            )
        return target

    def _preflight_activation_revocation_locked(
        self, revocation: CapabilityActivationRevokedV1
    ) -> OperationalCapabilityActivationRecordV1:
        target_id = revocation.target_activation_authorization_id
        target = self._activation_records.get(target_id)
        if target is None:
            raise CapabilityAuthorityConflict(
                f"activation revocation target does not exist: {target_id}"
            )
        if revocation.target_activation_record_digest != (
            operational_capability_activation_record_digest(target)
        ):
            raise CapabilityAuthorityConflict("activation revocation target digest is not exact")
        if target.activation_scope != revocation.target_scope:
            raise CapabilityAuthorityConflict("activation revocation target scope is not exact")
        if revocation.target_scope_digest != revocation.target_scope.canonical_digest:
            raise CapabilityAuthorityConflict(
                "activation revocation target scope digest is not exact"
            )
        if target_id in self._activation_superseded_by:
            raise CapabilityAuthorityConflict("superseded activation cannot be revoked")
        if target_id in self._activation_revoked_by:
            raise CapabilityAuthorityConflict("activation is already revoked")
        if revocation.revoked_at < target.activated_at:
            raise CapabilityAuthorityValidationError(
                "revokedAt must not be earlier than activatedAt"
            )
        return target

    def _cascade_suspensions_for_evidence_locked(
        self,
        evidence: CapabilityEvidenceRecordV1,
        *,
        operation_id: str,
        occurred_at: datetime,
    ) -> tuple[CapabilityActivationSuspendedV1, ...]:
        target_digest = capability_evidence_record_digest(evidence)
        affected = []
        for activation_id, activation in self._activation_records.items():
            if not any(
                reference.qualification_record_id == evidence.evidence_record_id
                for reference in activation.qualification_references
            ):
                continue
            projection = self.get_activation_projection(activation_id, now=occurred_at)
            if projection is None or not projection.is_current_durable_authority:
                continue
            affected.append(
                CapabilityActivationSuspendedV1(
                    operation_id=operation_id,
                    target_activation_authorization_id=activation_id,
                    target_activation_record_digest=(
                        operational_capability_activation_record_digest(activation)
                    ),
                    target_scope=activation.activation_scope,
                    target_scope_digest=activation.activation_scope_digest,
                    reason=f"required evidence revoked: {evidence.evidence_record_id}",
                    cause=ActivationAuthorityCause.EVIDENCE_REVOKED,
                    cause_record_id=evidence.evidence_record_id,
                    cause_record_digest=target_digest,
                    suspending_principal_id=_CAPABILITY_POLICY_ACTOR,
                    suspended_at=occurred_at,
                )
            )
        return tuple(
            sorted(affected, key=lambda item: item.target_activation_authorization_id)
        )

    def _cascade_suspensions_for_approval_locked(
        self,
        approval: ProductCapabilityApprovalRecordV1,
        *,
        operation_id: str,
        occurred_at: datetime,
    ) -> tuple[CapabilityActivationSuspendedV1, ...]:
        target_digest = product_capability_approval_record_digest(approval)
        affected = []
        for activation_id, activation in self._activation_records.items():
            if activation.approval_record_id != approval.approval_record_id:
                continue
            projection = self.get_activation_projection(activation_id, now=occurred_at)
            if projection is None or not projection.is_current_durable_authority:
                continue
            affected.append(
                CapabilityActivationSuspendedV1(
                    operation_id=operation_id,
                    target_activation_authorization_id=activation_id,
                    target_activation_record_digest=(
                        operational_capability_activation_record_digest(activation)
                    ),
                    target_scope=activation.activation_scope,
                    target_scope_digest=activation.activation_scope_digest,
                    reason=f"product approval revoked: {approval.approval_record_id}",
                    cause=ActivationAuthorityCause.APPROVAL_REVOKED,
                    cause_record_id=approval.approval_record_id,
                    cause_record_digest=target_digest,
                    suspending_principal_id=_CAPABILITY_POLICY_ACTOR,
                    suspended_at=occurred_at,
                )
            )
        return tuple(
            sorted(affected, key=lambda item: item.target_activation_authorization_id)
        )

    def _resolve_operation_locked(
        self, operation_id: str, command_digest: str
    ) -> _StoredOperation | None:
        blocked_digest = self._reserved_corrupt_operations.get(operation_id)
        if blocked_digest is not None:
            if blocked_digest != command_digest:
                raise CapabilityAuthorityIdempotencyConflict(
                    f"operationId payload conflict: {operation_id}"
                )
            raise CapabilityAuthorityUnavailableError(
                f"operationId belongs to an isolated corrupt chain: {operation_id}"
            )
        prior = self._operations.get(operation_id)
        if prior is None:
            return None
        if prior.command_digest != command_digest:
            raise CapabilityAuthorityIdempotencyConflict(
                f"operationId payload conflict: {operation_id}"
            )
        return prior

    def _mutation_result_locked(self, operation_id: str) -> CapabilityEvidenceMutationResult:
        operation = self._operations[operation_id]
        record = self._records[operation.result_record_id]
        return CapabilityEvidenceMutationResult(
            event_id=operation.event_id,
            operation_id=operation_id,
            record=record.model_copy(deep=True),
            record_digest=capability_evidence_record_digest(record),
        )

    def _approval_mutation_result_locked(
        self, operation_id: str
    ) -> ProductCapabilityApprovalMutationResult:
        operation = self._operations[operation_id]
        record = self._approval_records[operation.result_record_id]
        return ProductCapabilityApprovalMutationResult(
            event_id=operation.event_id,
            operation_id=operation_id,
            record=record.model_copy(deep=True),
            record_digest=product_capability_approval_record_digest(record),
        )

    def _activation_mutation_result_locked(
        self, operation_id: str
    ) -> OperationalCapabilityActivationMutationResult:
        operation = self._operations[operation_id]
        record = self._activation_records[operation.result_record_id]
        return OperationalCapabilityActivationMutationResult(
            event_id=operation.event_id,
            operation_id=operation_id,
            record=record.model_copy(deep=True),
            record_digest=operational_capability_activation_record_digest(record),
        )

    def _build_event(
        self,
        *,
        kind: CapabilityAuthorityEventKind,
        event_id: str,
        operation_id: str,
        actor_principal_id: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "schemaVersion": CAPABILITY_AUTHORITY_EVENT_SCHEMA_VERSION,
            "eventId": event_id,
            "operationId": operation_id,
            "kind": kind.value,
            "occurredAt": iso_utc(occurred_at),
            "actorPrincipalId": actor_principal_id,
            "actorPrincipalKind": PrincipalKind.OPERATOR.value,
            "payload": payload,
        }
        raw["payloadSha256"] = _event_content_digest(raw)
        return raw

    def _append_and_project_locked(
        self,
        raw: dict[str, Any],
        result_record: CapabilityEvidenceRecordV1,
        revocation: CapabilityEvidenceRevocationV1 | None,
        *,
        suspensions: tuple[CapabilityActivationSuspendedV1, ...] = (),
    ) -> None:
        try:
            self._journal.append(raw)
            self._project_valid_event(
                raw,
                result_record=result_record,
                revocation=revocation,
                suspensions=suspensions,
            )
        except JournalSealedError as exc:
            raise CapabilityAuthorityUnavailableError(
                "capability authority append failed and journal is sealed"
            ) from exc
        except BaseException:
            self._journal.close()
            raise

    def _project_valid_event(
        self,
        raw: dict[str, Any],
        *,
        result_record: CapabilityEvidenceRecordV1,
        revocation: CapabilityEvidenceRevocationV1 | None,
        suspensions: tuple[CapabilityActivationSuspendedV1, ...] = (),
    ) -> None:
        kind = CapabilityAuthorityEventKind(raw["kind"])
        operation_id = raw["operationId"]
        event_id = raw["eventId"]
        command_digest = _command_digest(
            kind=kind,
            actor_principal_id=raw["actorPrincipalId"],
            payload=raw["payload"],
        )
        if kind is CapabilityAuthorityEventKind.EVIDENCE_RECORDED:
            record = result_record
            self._records[record.evidence_record_id] = record
            self._record_events[record.evidence_record_id] = event_id
            self._record_operations[record.evidence_record_id] = operation_id
            if record.supersedes_evidence_record_id is not None:
                self._superseded_by[record.supersedes_evidence_record_id] = (
                    record.evidence_record_id
                )
        else:
            if revocation is None:
                raise RuntimeError("revocation projection requires revocation payload")
            record = result_record
            self._revoked_by[record.evidence_record_id] = event_id
            self._project_compound_activation_suspensions(event_id, suspensions)
        chain = EvidenceChainIdentity.from_scope(_scope_for_record(record))
        self._events[event_id] = (raw["payloadSha256"], chain)
        self._operations[operation_id] = _StoredOperation(
            command_digest=command_digest,
            event_id=event_id,
            kind=kind,
            result_record_id=record.evidence_record_id,
            chain=chain,
        )

    def _append_and_project_approval_locked(
        self,
        raw: dict[str, Any],
        result_record: ProductCapabilityApprovalRecordV1,
        revocation: ProductCapabilityApprovalRevocationV1 | None,
        *,
        suspensions: tuple[CapabilityActivationSuspendedV1, ...] = (),
    ) -> None:
        try:
            self._journal.append(raw)
            self._project_valid_approval_event(
                raw,
                result_record=result_record,
                revocation=revocation,
                suspensions=suspensions,
            )
        except JournalSealedError as exc:
            raise CapabilityAuthorityUnavailableError(
                "capability authority append failed and journal is sealed"
            ) from exc
        except BaseException:
            self._journal.close()
            raise

    def _project_valid_approval_event(
        self,
        raw: dict[str, Any],
        *,
        result_record: ProductCapabilityApprovalRecordV1,
        revocation: ProductCapabilityApprovalRevocationV1 | None,
        suspensions: tuple[CapabilityActivationSuspendedV1, ...] = (),
    ) -> None:
        kind = CapabilityAuthorityEventKind(raw["kind"])
        operation_id = raw["operationId"]
        event_id = raw["eventId"]
        command_digest = _command_digest(
            kind=kind,
            actor_principal_id=raw["actorPrincipalId"],
            payload=raw["payload"],
        )
        if kind is CapabilityAuthorityEventKind.PRODUCT_APPROVED:
            record = result_record
            self._approval_records[record.approval_record_id] = record
            self._approval_record_events[record.approval_record_id] = event_id
            self._approval_record_operations[record.approval_record_id] = operation_id
            if record.supersedes_approval_record_id is not None:
                self._approval_superseded_by[record.supersedes_approval_record_id] = (
                    record.approval_record_id
                )
        else:
            if revocation is None:
                raise RuntimeError("approval revocation projection requires revocation payload")
            record = result_record
            self._approval_revoked_by[record.approval_record_id] = event_id
            self._project_compound_activation_suspensions(event_id, suspensions)
        chain = ApprovalChainIdentity.from_scope(_approval_scope_for_record(record))
        self._events[event_id] = (raw["payloadSha256"], chain)
        self._operations[operation_id] = _StoredOperation(
            command_digest=command_digest,
            event_id=event_id,
            kind=kind,
            result_record_id=record.approval_record_id,
            chain=chain,
        )

    def _append_and_project_activation_locked(
        self,
        raw: dict[str, Any],
        result_record: OperationalCapabilityActivationRecordV1,
        suspension: CapabilityActivationSuspendedV1 | None,
        revocation: CapabilityActivationRevokedV1 | None,
    ) -> None:
        try:
            self._journal.append(raw)
            self._project_valid_activation_event(
                raw,
                result_record=result_record,
                suspension=suspension,
                revocation=revocation,
            )
        except JournalSealedError as exc:
            raise CapabilityAuthorityUnavailableError(
                "capability authority append failed and journal is sealed"
            ) from exc
        except BaseException:
            self._journal.close()
            raise

    def _project_valid_activation_event(
        self,
        raw: dict[str, Any],
        *,
        result_record: OperationalCapabilityActivationRecordV1,
        suspension: CapabilityActivationSuspendedV1 | None,
        revocation: CapabilityActivationRevokedV1 | None,
    ) -> None:
        kind = CapabilityAuthorityEventKind(raw["kind"])
        operation_id = raw["operationId"]
        event_id = raw["eventId"]
        command_digest = _command_digest(
            kind=kind,
            actor_principal_id=raw["actorPrincipalId"],
            payload=raw["payload"],
        )
        record = result_record
        activation_id = record.activation_authorization_id
        if kind is CapabilityAuthorityEventKind.ACTIVATION_AUTHORIZED:
            self._activation_records[activation_id] = record
            self._activation_record_events[activation_id] = event_id
            self._activation_record_operations[activation_id] = operation_id
            predecessor_id = record.supersedes_activation_authorization_id
            if predecessor_id is not None:
                self._activation_superseded_by[predecessor_id] = activation_id
        elif kind is CapabilityAuthorityEventKind.ACTIVATION_SUSPENDED:
            if suspension is None:
                raise RuntimeError("activation suspension projection requires payload")
            self._activation_suspended_by[activation_id] = suspension
            self._activation_suspension_events[activation_id] = event_id
        elif kind is CapabilityAuthorityEventKind.ACTIVATION_REVOKED:
            if revocation is None:
                raise RuntimeError("activation revocation projection requires payload")
            self._activation_revoked_by[activation_id] = revocation
            self._activation_revocation_events[activation_id] = event_id
        else:
            raise RuntimeError(f"not an activation event kind: {kind.value}")
        chain = ActivationChainIdentity.from_scope(record.activation_scope)
        self._events[event_id] = (raw["payloadSha256"], chain)
        self._operations[operation_id] = _StoredOperation(
            command_digest=command_digest,
            event_id=event_id,
            kind=kind,
            result_record_id=activation_id,
            chain=chain,
        )

    def _project_compound_activation_suspensions(
        self,
        event_id: str,
        suspensions: tuple[CapabilityActivationSuspendedV1, ...],
    ) -> None:
        for suspension in suspensions:
            activation_id = suspension.target_activation_authorization_id
            self._activation_suspended_by[activation_id] = suspension
            self._activation_suspension_events[activation_id] = event_id

    def _replay(self, journal: DurableJournal) -> None:
        for index, raw in enumerate(journal.replay(), start=1):
            self._replay_event(raw, index=index)

    def _replay_event(self, raw: dict[str, Any], *, index: int) -> None:
        chain_hint = _chain_hint(raw)
        try:
            envelope = CapabilityAuthorityEventV1.model_validate(raw)
        except ValidationError as exc:
            raise CapabilityAuthorityRecoveryError(
                f"event {index}: malformed top-level capability authority envelope: {exc}"
            ) from exc

        try:
            kind = self._validate_replay_envelope(envelope, raw)
            chain_hint = _chain_hint(raw)
            if chain_hint is None:
                raise CapabilityAuthorityRecoveryError(
                    f"event {index}: authority payload has no attributable evidence scope"
                )
            event_digest = raw["payloadSha256"]
            duplicate_event = self._events.get(envelope.event_id)
            if duplicate_event is not None:
                self._isolate_chain(duplicate_event[1], "duplicate eventId in journal")
                raise _ReplaySemanticError("duplicate eventId in journal")
            command_digest = _command_digest(
                kind=kind,
                actor_principal_id=envelope.actor_principal_id,
                payload=envelope.payload,
            )
            prior_operation = self._operations.get(envelope.operation_id)
            if prior_operation is not None:
                self._isolate_chain(
                    prior_operation.chain,
                    "operationId was physically appended more than once",
                )
                raise _ReplaySemanticError(
                    "operationId was physically appended more than once"
                    if prior_operation.command_digest == command_digest
                    else "same operationId has a different canonical command digest"
                )
            if envelope.operation_id in self._reserved_corrupt_operations:
                raise _ReplaySemanticError("operationId reused after a corrupt authority event")

            occurred_at = _validate_exact_utc(
                datetime.fromisoformat(envelope.occurred_at), "occurredAt"
            )
            if kind is CapabilityAuthorityEventKind.EVIDENCE_RECORDED:
                evidence_raw = envelope.payload.get("evidence")
                if not isinstance(evidence_raw, dict) or set(envelope.payload) != {"evidence"}:
                    raise _ReplaySemanticError("malformed evidence event payload")
                record = self._validate_evidence_payload_for_replay(evidence_raw)
                if envelope.actor_principal_id != record.verifier_principal_id:
                    raise _ReplaySemanticError(
                        "actorPrincipalId does not equal verifierPrincipalId"
                    )
                if occurred_at < record.verified_at:
                    raise _ReplaySemanticError("occurredAt is earlier than verifiedAt")
                self._preflight_record_for_replay(record)
                self._project_valid_event(raw, result_record=record, revocation=None)
            elif kind is CapabilityAuthorityEventKind.EVIDENCE_REVOKED:
                revocation_raw = envelope.payload.get("revocation")
                payload_keys = set(envelope.payload)
                if not isinstance(revocation_raw, dict) or payload_keys not in (
                    {"revocation"},
                    {"revocation", "affectedActivationSuspensions"},
                ):
                    raise _ReplaySemanticError("malformed revocation event payload")
                revocation = self._validate_revocation_payload_for_replay(revocation_raw)
                target = self._preflight_revocation_for_replay(revocation, occurred_at=occurred_at)
                suspensions = self._compound_suspensions_for_replay(
                    envelope.payload.get("affectedActivationSuspensions", []),
                    operation_id=envelope.operation_id,
                    occurred_at=occurred_at,
                )
                expected = self._cascade_suspensions_for_evidence_locked(
                    target,
                    operation_id=envelope.operation_id,
                    occurred_at=occurred_at,
                )
                if suspensions != expected:
                    raise _ReplaySemanticError(
                        "evidence revocation affected activation suspension set is not exact"
                    )
                self._project_valid_event(
                    raw,
                    result_record=target,
                    revocation=revocation,
                    suspensions=suspensions,
                )
            elif kind is CapabilityAuthorityEventKind.PRODUCT_APPROVED:
                approval_raw = envelope.payload.get("approval")
                approval_digest = envelope.payload.get("approvalRecordDigest")
                if (
                    not isinstance(approval_raw, dict)
                    or not isinstance(approval_digest, str)
                    or set(envelope.payload) != {"approval", "approvalRecordDigest"}
                ):
                    raise _ReplaySemanticError("malformed product approval event payload")
                approval = self._validate_approval_payload_for_replay(approval_raw)
                if approval.operation_id != envelope.operation_id:
                    raise _ReplaySemanticError(
                        "approval operationId does not equal envelope operationId"
                    )
                if envelope.actor_principal_id != approval.approver_principal_id:
                    raise _ReplaySemanticError(
                        "actorPrincipalId does not equal approverPrincipalId"
                    )
                if occurred_at < approval.approved_at:
                    raise _ReplaySemanticError("occurredAt is earlier than approvedAt")
                if approval_digest != product_capability_approval_record_digest(approval):
                    raise _ReplaySemanticError("approvalRecordDigest does not match approval")
                self._preflight_approval_for_replay(approval, now=approval.approved_at)
                self._project_valid_approval_event(raw, result_record=approval, revocation=None)
            elif kind is CapabilityAuthorityEventKind.PRODUCT_APPROVAL_REVOKED:
                revocation_raw = envelope.payload.get("approvalRevocation")
                payload_keys = set(envelope.payload)
                if not isinstance(revocation_raw, dict) or payload_keys not in (
                    {"approvalRevocation"},
                    {"approvalRevocation", "affectedActivationSuspensions"},
                ):
                    raise _ReplaySemanticError("malformed product approval revocation payload")
                approval_revocation = self._validate_approval_revocation_payload_for_replay(
                    revocation_raw
                )
                approval_target = self._preflight_approval_revocation_for_replay(
                    approval_revocation, occurred_at=occurred_at
                )
                suspensions = self._compound_suspensions_for_replay(
                    envelope.payload.get("affectedActivationSuspensions", []),
                    operation_id=envelope.operation_id,
                    occurred_at=occurred_at,
                )
                expected = self._cascade_suspensions_for_approval_locked(
                    approval_target,
                    operation_id=envelope.operation_id,
                    occurred_at=occurred_at,
                )
                if suspensions != expected:
                    raise _ReplaySemanticError(
                        "approval revocation affected activation suspension set is not exact"
                    )
                self._project_valid_approval_event(
                    raw,
                    result_record=approval_target,
                    revocation=approval_revocation,
                    suspensions=suspensions,
                )
            elif kind is CapabilityAuthorityEventKind.ACTIVATION_AUTHORIZED:
                activation_raw = envelope.payload.get("activation")
                activation_digest = envelope.payload.get("activationRecordDigest")
                if (
                    not isinstance(activation_raw, dict)
                    or not isinstance(activation_digest, str)
                    or set(envelope.payload) != {"activation", "activationRecordDigest"}
                ):
                    raise _ReplaySemanticError("malformed activation event payload")
                activation = self._validate_activation_payload_for_replay(activation_raw)
                if activation.operation_id != envelope.operation_id:
                    raise _ReplaySemanticError(
                        "activation operationId does not equal envelope operationId"
                    )
                if envelope.actor_principal_id != activation.activating_principal_id:
                    raise _ReplaySemanticError(
                        "actorPrincipalId does not equal activatingPrincipalId"
                    )
                if occurred_at < activation.activated_at:
                    raise _ReplaySemanticError("occurredAt is earlier than activatedAt")
                if activation_digest != operational_capability_activation_record_digest(
                    activation
                ):
                    raise _ReplaySemanticError(
                        "activationRecordDigest does not match activation"
                    )
                self._preflight_activation_for_replay(
                    activation,
                    now=activation.activated_at,
                )
                self._project_valid_activation_event(
                    raw,
                    result_record=activation,
                    suspension=None,
                    revocation=None,
                )
            elif kind is CapabilityAuthorityEventKind.ACTIVATION_SUSPENDED:
                suspension_raw = envelope.payload.get("activationSuspension")
                if not isinstance(suspension_raw, dict) or set(envelope.payload) != {
                    "activationSuspension"
                }:
                    raise _ReplaySemanticError("malformed activation suspension payload")
                suspension = self._validate_activation_suspension_payload_for_replay(
                    suspension_raw
                )
                if suspension.operation_id != envelope.operation_id:
                    raise _ReplaySemanticError(
                        "suspension operationId does not equal envelope operationId"
                    )
                if suspension.suspending_principal_id != envelope.actor_principal_id:
                    raise _ReplaySemanticError(
                        "actorPrincipalId does not equal suspendingPrincipalId"
                    )
                if suspension.cause not in {
                    ActivationAuthorityCause.EXPLICIT_OPERATION,
                    ActivationAuthorityCause.CONFIGURED_SCOPE_INVALIDATED,
                    ActivationAuthorityCause.MAPPING_GATE_INVALIDATED,
                }:
                    raise _ReplaySemanticError(
                        "top-level suspension cannot impersonate a prerequisite revocation"
                    )
                if (
                    suspension.cause is not ActivationAuthorityCause.EXPLICIT_OPERATION
                    and suspension.cause_record_id is None
                ):
                    raise _ReplaySemanticError(
                        "configured/mapping suspension requires an exact cause record"
                    )
                if suspension.suspended_at != occurred_at:
                    raise _ReplaySemanticError("suspendedAt does not equal occurredAt")
                activation_target = self._preflight_activation_suspension_for_replay(
                    suspension
                )
                self._project_valid_activation_event(
                    raw,
                    result_record=activation_target,
                    suspension=suspension,
                    revocation=None,
                )
            elif kind is CapabilityAuthorityEventKind.ACTIVATION_REVOKED:
                activation_revocation_raw = envelope.payload.get("activationRevocation")
                if not isinstance(activation_revocation_raw, dict) or set(envelope.payload) != {
                    "activationRevocation"
                }:
                    raise _ReplaySemanticError("malformed activation revocation payload")
                activation_revocation = self._validate_activation_revocation_payload_for_replay(
                    activation_revocation_raw
                )
                if activation_revocation.operation_id != envelope.operation_id:
                    raise _ReplaySemanticError(
                        "activation revocation operationId does not equal envelope operationId"
                    )
                if activation_revocation.revoking_principal_id != envelope.actor_principal_id:
                    raise _ReplaySemanticError(
                        "actorPrincipalId does not equal revokingPrincipalId"
                    )
                if activation_revocation.revoked_at != occurred_at:
                    raise _ReplaySemanticError("revokedAt does not equal occurredAt")
                activation_target = self._preflight_activation_revocation_for_replay(
                    activation_revocation
                )
                self._project_valid_activation_event(
                    raw,
                    result_record=activation_target,
                    suspension=None,
                    revocation=activation_revocation,
                )
            else:  # pragma: no cover - enum exhaustiveness guard
                raise _ReplaySemanticError(f"unsupported event kind: {kind.value}")
            self._events[envelope.event_id] = (event_digest, chain_hint)
        except CapabilityAuthorityRecoveryError:
            raise
        except _ReplaySemanticError as exc:
            if chain_hint is None:
                raise CapabilityAuthorityRecoveryError(
                    f"event {index}: unattributable authority corruption: {exc}"
                ) from exc
            status = (
                CapabilityAuthorityChainStatus.BLOCKED_UNSUPPORTED_VERSION
                if exc.unsupported_version
                else CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
            )
            self._isolate_chain(chain_hint, f"event {index}: {exc}", status=status)
            operation_id = raw.get("operationId")
            if isinstance(operation_id, str) and operation_id:
                self._reserved_corrupt_operations[operation_id] = self._raw_command_digest(raw)
            event_id = raw.get("eventId")
            payload_digest = raw.get("payloadSha256")
            if isinstance(event_id, str) and isinstance(payload_digest, str):
                self._events.setdefault(event_id, (payload_digest, chain_hint))
        except (CapabilityAuthorityValidationError, CapabilityAuthorityConflict, ValueError) as exc:
            if chain_hint is None:
                raise CapabilityAuthorityRecoveryError(
                    f"event {index}: unattributable authority corruption: {exc}"
                ) from exc
            unsupported = isinstance(
                exc.__cause__,
                (
                    UnsupportedCapabilityMappingVersionError,
                    UnsupportedCapabilityGateVersionError,
                    UnsupportedCapabilityFreshnessPolicyError,
                ),
            )
            status = (
                CapabilityAuthorityChainStatus.BLOCKED_UNSUPPORTED_VERSION
                if unsupported
                else CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
            )
            self._isolate_chain(chain_hint, f"event {index}: {exc}", status=status)
            operation_id = raw.get("operationId")
            if isinstance(operation_id, str) and operation_id:
                self._reserved_corrupt_operations[operation_id] = self._raw_command_digest(raw)
            event_id = raw.get("eventId")
            payload_digest = raw.get("payloadSha256")
            if isinstance(event_id, str) and isinstance(payload_digest, str):
                self._events.setdefault(event_id, (payload_digest, chain_hint))

    def _validate_replay_envelope(
        self, envelope: CapabilityAuthorityEventV1, raw: dict[str, Any]
    ) -> CapabilityAuthorityEventKind:
        chain = _chain_hint(raw)
        if envelope.schema_version != CAPABILITY_AUTHORITY_EVENT_SCHEMA_VERSION:
            raise _ReplaySemanticError(
                f"unsupported event schemaVersion: {envelope.schema_version!r}",
                unsupported_version=True,
            )
        try:
            kind = CapabilityAuthorityEventKind(envelope.kind)
        except ValueError as exc:
            raise _ReplaySemanticError(
                f"unsupported capability authority event kind: {envelope.kind!r}",
                unsupported_version=True,
            ) from exc
        for name, value in (
            ("eventId", envelope.event_id),
            ("operationId", envelope.operation_id),
            ("actorPrincipalId", envelope.actor_principal_id),
        ):
            if not is_path_safe_identifier(value):
                raise _ReplaySemanticError(f"{name} is not path-safe")
        if envelope.actor_principal_kind != PrincipalKind.OPERATOR.value:
            raise _ReplaySemanticError("capability authority actorPrincipalKind must be OPERATOR")
        try:
            _validate_digest(envelope.payload_sha256, "payloadSha256")
        except ValueError as exc:
            raise _ReplaySemanticError(str(exc)) from exc
        if envelope.payload_sha256 != _event_content_digest(raw):
            if chain is None:
                raise CapabilityAuthorityRecoveryError(
                    "payload digest mismatch has no attributable evidence scope"
                )
            raise _ReplaySemanticError("payloadSha256 does not match authority event content")
        try:
            _validate_exact_utc(datetime.fromisoformat(envelope.occurred_at), "occurredAt")
        except (ValueError, TypeError) as exc:
            raise _ReplaySemanticError(f"invalid occurredAt: {exc}") from exc
        return kind

    def _validate_evidence_payload_for_replay(
        self, raw: dict[str, Any]
    ) -> CapabilityEvidenceRecordV1:
        try:
            return self._validate_evidence_payload(raw)
        except CapabilityAuthorityValidationError as exc:
            unsupported = isinstance(exc.__cause__, UnsupportedCapabilityMappingVersionError)
            raise _ReplaySemanticError(str(exc), unsupported_version=unsupported) from exc

    def _validate_revocation_payload_for_replay(
        self, raw: dict[str, Any]
    ) -> CapabilityEvidenceRevocationV1:
        try:
            return self._validate_revocation_payload(raw)
        except CapabilityAuthorityValidationError as exc:
            unsupported = isinstance(exc.__cause__, UnsupportedCapabilityMappingVersionError)
            raise _ReplaySemanticError(str(exc), unsupported_version=unsupported) from exc

    def _validate_approval_payload_for_replay(
        self, raw: dict[str, Any]
    ) -> ProductCapabilityApprovalRecordV1:
        try:
            return self._validate_approval_payload(raw)
        except CapabilityAuthorityValidationError as exc:
            unsupported = isinstance(
                exc.__cause__,
                (UnsupportedCapabilityMappingVersionError, UnsupportedCapabilityGateVersionError),
            )
            raise _ReplaySemanticError(str(exc), unsupported_version=unsupported) from exc

    def _validate_approval_revocation_payload_for_replay(
        self, raw: dict[str, Any]
    ) -> ProductCapabilityApprovalRevocationV1:
        try:
            return self._validate_approval_revocation_payload(raw)
        except CapabilityAuthorityValidationError as exc:
            unsupported = isinstance(
                exc.__cause__,
                (UnsupportedCapabilityMappingVersionError, UnsupportedCapabilityGateVersionError),
            )
            raise _ReplaySemanticError(str(exc), unsupported_version=unsupported) from exc

    def _validate_activation_payload_for_replay(
        self, raw: dict[str, Any]
    ) -> OperationalCapabilityActivationRecordV1:
        try:
            return self._validate_activation_payload(raw)
        except CapabilityAuthorityValidationError as exc:
            unsupported = isinstance(
                exc.__cause__,
                (
                    UnsupportedCapabilityMappingVersionError,
                    UnsupportedCapabilityGateVersionError,
                    UnsupportedCapabilityFreshnessPolicyError,
                ),
            )
            raise _ReplaySemanticError(str(exc), unsupported_version=unsupported) from exc

    def _validate_activation_suspension_payload_for_replay(
        self, raw: dict[str, Any]
    ) -> CapabilityActivationSuspendedV1:
        try:
            return self._validate_activation_suspension_payload(raw)
        except CapabilityAuthorityValidationError as exc:
            unsupported = isinstance(
                exc.__cause__,
                (UnsupportedCapabilityMappingVersionError, UnsupportedCapabilityGateVersionError),
            )
            raise _ReplaySemanticError(str(exc), unsupported_version=unsupported) from exc

    def _validate_activation_revocation_payload_for_replay(
        self, raw: dict[str, Any]
    ) -> CapabilityActivationRevokedV1:
        try:
            return self._validate_activation_revocation_payload(raw)
        except CapabilityAuthorityValidationError as exc:
            unsupported = isinstance(
                exc.__cause__,
                (UnsupportedCapabilityMappingVersionError, UnsupportedCapabilityGateVersionError),
            )
            raise _ReplaySemanticError(str(exc), unsupported_version=unsupported) from exc

    def _compound_suspensions_for_replay(
        self,
        raw: Any,
        *,
        operation_id: str,
        occurred_at: datetime,
    ) -> tuple[CapabilityActivationSuspendedV1, ...]:
        if not isinstance(raw, list):
            raise _ReplaySemanticError("affectedActivationSuspensions must be an array")
        suspensions = tuple(
            self._validate_activation_suspension_payload_for_replay(item)
            if isinstance(item, dict)
            else self._raise_malformed_compound_suspension()
            for item in raw
        )
        ids = tuple(item.target_activation_authorization_id for item in suspensions)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise _ReplaySemanticError(
                "affected activation suspensions must be unique and sorted"
            )
        if any(
            item.operation_id != operation_id
            or item.suspended_at != occurred_at
            or item.suspending_principal_id != _CAPABILITY_POLICY_ACTOR
            for item in suspensions
        ):
            raise _ReplaySemanticError(
                "compound suspension operation/time/policy actor is not exact"
            )
        return suspensions

    @staticmethod
    def _raise_malformed_compound_suspension() -> CapabilityActivationSuspendedV1:
        raise _ReplaySemanticError("malformed affected activation suspension")

    def _preflight_record_for_replay(self, record: CapabilityEvidenceRecordV1) -> None:
        try:
            self._preflight_record_locked(record)
        except CapabilityAuthorityConflict as exc:
            target_id = record.supersedes_evidence_record_id
            if target_id is not None and (target := self._records.get(target_id)) is not None:
                self._isolate_chain(
                    EvidenceChainIdentity.from_scope(_scope_for_record(target)), str(exc)
                )
            raise _ReplaySemanticError(str(exc)) from exc

    def _preflight_revocation_for_replay(
        self, revocation: CapabilityEvidenceRevocationV1, *, occurred_at: datetime
    ) -> CapabilityEvidenceRecordV1:
        try:
            return self._preflight_revocation_locked(revocation, occurred_at=occurred_at)
        except (CapabilityAuthorityConflict, CapabilityAuthorityValidationError) as exc:
            target = self._records.get(revocation.target_evidence_record_id)
            if target is not None:
                self._isolate_chain(
                    EvidenceChainIdentity.from_scope(_scope_for_record(target)), str(exc)
                )
            raise _ReplaySemanticError(str(exc)) from exc

    def _preflight_approval_for_replay(
        self, record: ProductCapabilityApprovalRecordV1, *, now: datetime
    ) -> None:
        try:
            self._preflight_approval_locked(record, now=now)
        except (CapabilityAuthorityConflict, CapabilityAuthorityValidationError) as exc:
            target_id = record.supersedes_approval_record_id
            if (
                target_id is not None
                and (target := self._approval_records.get(target_id)) is not None
            ):
                self._isolate_chain(
                    ApprovalChainIdentity.from_scope(_approval_scope_for_record(target)),
                    str(exc),
                )
            raise _ReplaySemanticError(str(exc)) from exc

    def _preflight_approval_revocation_for_replay(
        self,
        revocation: ProductCapabilityApprovalRevocationV1,
        *,
        occurred_at: datetime,
    ) -> ProductCapabilityApprovalRecordV1:
        try:
            return self._preflight_approval_revocation_locked(revocation, occurred_at=occurred_at)
        except (CapabilityAuthorityConflict, CapabilityAuthorityValidationError) as exc:
            target = self._approval_records.get(revocation.target_approval_record_id)
            if target is not None:
                self._isolate_chain(
                    ApprovalChainIdentity.from_scope(_approval_scope_for_record(target)),
                    str(exc),
                )
            raise _ReplaySemanticError(str(exc)) from exc

    def _preflight_activation_for_replay(
        self,
        record: OperationalCapabilityActivationRecordV1,
        *,
        now: datetime,
    ) -> None:
        try:
            self._preflight_activation_locked(record, now=now)
        except (CapabilityAuthorityConflict, CapabilityAuthorityValidationError) as exc:
            predecessor_id = record.supersedes_activation_authorization_id
            if (
                predecessor_id is not None
                and (target := self._activation_records.get(predecessor_id)) is not None
            ):
                self._isolate_chain(
                    ActivationChainIdentity.from_scope(target.activation_scope),
                    str(exc),
                )
            raise _ReplaySemanticError(str(exc)) from exc

    def _preflight_activation_suspension_for_replay(
        self, suspension: CapabilityActivationSuspendedV1
    ) -> OperationalCapabilityActivationRecordV1:
        try:
            return self._preflight_activation_suspension_locked(suspension)
        except (CapabilityAuthorityConflict, CapabilityAuthorityValidationError) as exc:
            target = self._activation_records.get(
                suspension.target_activation_authorization_id
            )
            if target is not None:
                self._isolate_chain(
                    ActivationChainIdentity.from_scope(target.activation_scope),
                    str(exc),
                )
            raise _ReplaySemanticError(str(exc)) from exc

    def _preflight_activation_revocation_for_replay(
        self, revocation: CapabilityActivationRevokedV1
    ) -> OperationalCapabilityActivationRecordV1:
        try:
            return self._preflight_activation_revocation_locked(revocation)
        except (CapabilityAuthorityConflict, CapabilityAuthorityValidationError) as exc:
            target = self._activation_records.get(
                revocation.target_activation_authorization_id
            )
            if target is not None:
                self._isolate_chain(
                    ActivationChainIdentity.from_scope(target.activation_scope),
                    str(exc),
                )
            raise _ReplaySemanticError(str(exc)) from exc

    def _raw_command_digest(self, raw: dict[str, Any]) -> str:
        kind = raw.get("kind")
        actor = raw.get("actorPrincipalId")
        payload = raw.get("payload")
        if isinstance(kind, str) and isinstance(actor, str) and isinstance(payload, dict):
            try:
                event_kind = CapabilityAuthorityEventKind(kind)
            except ValueError:
                pass
            else:
                return _command_digest(
                    kind=event_kind,
                    actor_principal_id=actor,
                    payload=payload,
                )
        return _sha256_prefixed({"raw": raw})

    def _isolate_chain(
        self,
        chain: AuthorityChainIdentity,
        reason: str,
        *,
        status: CapabilityAuthorityChainStatus = CapabilityAuthorityChainStatus.BLOCKED_CORRUPT,
    ) -> None:
        current = self._chain_status.get(chain)
        if current is None or (
            current[0] is CapabilityAuthorityChainStatus.BLOCKED_UNSUPPORTED_VERSION
            and status is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
        ):
            self._chain_status[chain] = (status, reason)


__all__ = [
    "CAPABILITY_AUTHORITY_EVENT_SCHEMA_VERSION",
    "CAPABILITY_AUTHORITY_JOURNAL_NAME",
    "ActivationApplicabilityScopeV1",
    "ActivationAuthorityCause",
    "ActivationLifecycleStatus",
    "CapabilityAuthorityChainStatus",
    "CapabilityAuthorityConflict",
    "CapabilityAuthorityError",
    "CapabilityAuthorityEventKind",
    "CapabilityAuthorityAuthorizationError",
    "CapabilityAuthorityIdempotencyConflict",
    "CapabilityAuthorityRecoveryError",
    "CapabilityAuthorityStore",
    "CapabilityAuthorityUnavailableError",
    "CapabilityAuthorityValidationError",
    "CapabilityEvidenceMutationResult",
    "CapabilityEvidenceProjection",
    "CapabilityEvidenceRecordV1",
    "CapabilityEvidenceRevocationV1",
    "CapabilityEvidenceType",
    "CapabilityActivationRevokedV1",
    "CapabilityActivationSuspendedV1",
    "ConfiguredDeploymentSnapshotV1",
    "ApprovalApplicabilityScopeV1",
    "ApprovalLifecycleStatus",
    "EquipmentComponentV1",
    "EquipmentRole",
    "EquipmentScopeV1",
    "EvidenceApplicabilityScopeV1",
    "EvidenceLifecycleStatus",
    "OperationalCapabilityActivationMutationResult",
    "OperationalCapabilityActivationProjection",
    "OperationalCapabilityActivationRecordV1",
    "ProductCapabilityApprovalMutationResult",
    "ProductCapabilityApprovalProjection",
    "ProductCapabilityApprovalRecordV1",
    "ProductCapabilityApprovalRevocationV1",
    "ProductSupportMatrixEntryV1",
    "ProductSupportMatrixV1",
    "QualificationReferenceV1",
    "TestedDeploymentRefV1",
    "capability_evidence_record_digest",
    "operational_capability_activation_record_digest",
    "product_capability_approval_record_digest",
]
