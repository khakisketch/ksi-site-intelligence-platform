"""CAP-4 durable OperationalCapabilityActivation authority fixtures."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ksi_core.auth import Permission, Principal, PrincipalKind, Role, principal_permissions
from ksi_core.capability.authority_store import (
    CAPABILITY_AUTHORITY_JOURNAL_NAME,
    ActivationApplicabilityScopeV1,
    ActivationAuthorityCause,
    ActivationLifecycleStatus,
    CapabilityActivationRevokedV1,
    CapabilityActivationSuspendedV1,
    CapabilityAuthorityAuthorizationError,
    CapabilityAuthorityChainStatus,
    CapabilityAuthorityConflict,
    CapabilityAuthorityIdempotencyConflict,
    CapabilityAuthorityRecoveryError,
    CapabilityAuthorityStore,
    CapabilityAuthorityValidationError,
    CapabilityEvidenceRecordV1,
    CapabilityEvidenceRevocationV1,
    CapabilityEvidenceType,
    ConfiguredDeploymentSnapshotV1,
    EquipmentComponentV1,
    EquipmentRole,
    EquipmentScopeV1,
    EvidenceApplicabilityScopeV1,
    EvidenceLifecycleStatus,
    OperationalCapabilityActivationRecordV1,
    ProductCapabilityApprovalRecordV1,
    ProductCapabilityApprovalRevocationV1,
    ProductSupportMatrixEntryV1,
    ProductSupportMatrixV1,
    QualificationReferenceV1,
    capability_evidence_record_digest,
    operational_capability_activation_record_digest,
    product_capability_approval_record_digest,
)
from ksi_core.durable_journal import DurableJournal
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_domain.capability_contract import (
    CanonicalTransportCapability,
    CapabilityGateVersion,
    CapabilityIntegrationPath,
    CapabilityMappingVersion,
    OperationalCapabilityActivation,
    ProductCapabilityApproval,
    RouteEvidenceQualification,
    SourceCapabilityId,
    resolve_capability_mapping,
)

NOW = datetime(2026, 9, 3, 4, 0, tzinfo=UTC)
ACTIVE_NOW = NOW + timedelta(minutes=5)
BUILD = "sha256:" + "b" * 64
POLICY = "ksi-capability-policy-v1"
FRESHNESS_POLICY_ID = "ksi-route-observation-freshness-v1"
FRESHNESS_POLICY_DIGEST = "sha256:" + hashlib.sha256(
    canonical_json_bytes(
        {
            "schemaVersion": "1.0",
            "freshnessPolicyId": FRESHNESS_POLICY_ID,
            "observationTtlSeconds": 300,
            "minimumRefreshMarginSeconds": 30.0,
        }
    )
).hexdigest()
FRESHNESS_POLICIES = {FRESHNESS_POLICY_ID: FRESHNESS_POLICY_DIGEST}

_ROLES: dict[CapabilityIntegrationPath, tuple[EquipmentRole, ...]] = {
    CapabilityIntegrationPath.DJI_CLOUD: (
        EquipmentRole.AIRCRAFT,
        EquipmentRole.GATEWAY,
    ),
    CapabilityIntegrationPath.PSDK_MANIFOLD: (
        EquipmentRole.AIRCRAFT,
        EquipmentRole.EDGE,
        EquipmentRole.GATEWAY,
    ),
    CapabilityIntegrationPath.MANIFOLD_DIRECT: (
        EquipmentRole.AIRCRAFT,
        EquipmentRole.EDGE,
    ),
    CapabilityIntegrationPath.MSDK_FIELD: (
        EquipmentRole.AIRCRAFT,
        EquipmentRole.EDGE,
        EquipmentRole.GATEWAY,
    ),
    CapabilityIntegrationPath.DJI_DOCK: (
        EquipmentRole.AIRCRAFT,
        EquipmentRole.DOCK,
    ),
}


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _canonical_digest(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(raw: dict[str, Any]) -> str:
    content = dict(raw)
    content.pop("payloadSha256", None)
    return _canonical_digest(content)


def _redigest(event: dict[str, Any]) -> None:
    event["payloadSha256"] = _event_digest(event)


def _read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]


def _write(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        encoding="ascii",
    )


def _open(
    path: Path,
    *,
    policies: dict[str, str] | None = None,
) -> CapabilityAuthorityStore:
    return CapabilityAuthorityStore(
        DurableJournal(path),
        supported_freshness_policies=FRESHNESS_POLICIES if policies is None else policies,
    )


def _admin(
    principal_id: str = "ops-activator-1",
    *,
    organization_id: str = "org-1",
) -> Principal:
    return Principal(
        principal_id=principal_id,
        kind=PrincipalKind.OPERATOR,
        role=Role.ADMIN,
        device_id=None,
        organization_id=organization_id,
    )


def _field(principal_id: str = "field-operator-1") -> Principal:
    return Principal(
        principal_id=principal_id,
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id="org-1",
    )


def _equipment(path: CapabilityIntegrationPath) -> EquipmentScopeV1:
    return EquipmentScopeV1(
        components=tuple(
            EquipmentComponentV1(
                role=role,
                product_family="DJI-Matrice",
                hardware_model=f"model-{role.value.lower()}",
                hardware_revision="rev-a",
                firmware_or_image_version="firmware-1.0",
            )
            for role in _ROLES[path]
        )
    )


def _evidence(
    record_id: str,
    *,
    source: SourceCapabilityId,
    equipment: EquipmentScopeV1,
    supersedes: str | None = None,
) -> CapabilityEvidenceRecordV1:
    return CapabilityEvidenceRecordV1(
        evidence_record_id=record_id,
        canonical_capability_id=CanonicalTransportCapability.EDGE_DOWNLINK,
        source_capability_id=source,
        mapping_version=CapabilityMappingVersion.V1.value,
        integration_path=CapabilityIntegrationPath.MSDK_FIELD,
        equipment_scope=equipment,
        equipment_scope_digest=equipment.canonical_digest,
        test_build_digest=BUILD,
        policy_scope_id=POLICY,
        evidence_type=CapabilityEvidenceType.HIL,
        evidence_artifact_ref=f"evidence://capability/{record_id}",
        evidence_digest=_digest("e"),
        procedure_ref="procedure://dji-route-v1",
        procedure_digest=_digest("d"),
        performer_principal_id=f"performer-{source.value.lower()}",
        verifier_principal_id=f"verifier-{source.value.lower()}",
        performed_at=NOW - timedelta(hours=1),
        verified_at=NOW,
        verification_result=RouteEvidenceQualification.QUALIFIED,
        valid_until=NOW + timedelta(days=30),
        supersedes_evidence_record_id=supersedes,
    )


def _seed_evidence(
    store: CapabilityAuthorityStore,
    *,
    suffix: str = "",
    supersedes: tuple[CapabilityEvidenceRecordV1, ...] | None = None,
) -> tuple[CapabilityEvidenceRecordV1, ...]:
    equipment = _equipment(CapabilityIntegrationPath.MSDK_FIELD)
    requirement = resolve_capability_mapping(CapabilityMappingVersion.V1).requirement_for(
        CanonicalTransportCapability.EDGE_DOWNLINK,
        CapabilityIntegrationPath.MSDK_FIELD,
    )
    records = []
    for index, source in enumerate(requirement.required_sources, start=1):
        predecessor = supersedes[index - 1].evidence_record_id if supersedes else None
        record = _evidence(
            f"evidence-{source.value.lower()}{suffix}",
            source=source,
            equipment=equipment,
            supersedes=predecessor,
        )
        store.record_evidence(
            record,
            operation_id=f"evidence-operation-{index}{suffix}",
            event_id=f"evidence-event-{index}{suffix}",
            actor_principal_id=record.verifier_principal_id,
            occurred_at=NOW + timedelta(seconds=index),
        )
        records.append(record)
    return tuple(records)


def _approval(
    records: tuple[CapabilityEvidenceRecordV1, ...],
    *,
    approval_id: str = "approval-1",
    operation_id: str = "approval-operation-1",
    supersedes: str | None = None,
    approved_at: datetime = NOW + timedelta(minutes=1),
    valid_until: datetime = NOW + timedelta(days=20),
) -> ProductCapabilityApprovalRecordV1:
    references = tuple(
        sorted(
            (
                QualificationReferenceV1(
                    qualification_record_id=record.evidence_record_id,
                    qualification_record_digest=capability_evidence_record_digest(record),
                )
                for record in records
            ),
            key=lambda item: item.qualification_record_id,
        )
    )
    equipment = records[0].equipment_scope
    matrix = ProductSupportMatrixV1(
        entries=(
            ProductSupportMatrixEntryV1(
                integration_path=CapabilityIntegrationPath.MSDK_FIELD,
                equipment_scope=equipment,
                equipment_scope_digest=equipment.canonical_digest,
                qualification_references=references,
            ),
        )
    )
    return ProductCapabilityApprovalRecordV1(
        approval_record_id=approval_id,
        operation_id=operation_id,
        canonical_capability_id=CanonicalTransportCapability.EDGE_DOWNLINK,
        mapping_version=CapabilityMappingVersion.V1.value,
        gate_version=CapabilityGateVersion.V1.value,
        support_matrix=matrix,
        support_matrix_digest=matrix.canonical_digest,
        evidence_set_digest=matrix.evidence_set_digest,
        product_build_digest=BUILD,
        policy_scope_id=POLICY,
        approver_principal_id="product-approver-1",
        approved_at=approved_at,
        valid_until=valid_until,
        decision=ProductCapabilityApproval.APPROVED,
        supersedes_approval_record_id=supersedes,
    )


def _approve(store: CapabilityAuthorityStore, approval: ProductCapabilityApprovalRecordV1) -> None:
    store.approve_product_capability(
        approval,
        principal=_admin("product-approver-1", organization_id="ksi-product"),
        operation_id=approval.operation_id,
        event_id=f"event-{approval.operation_id}",
        occurred_at=approval.approved_at + timedelta(minutes=1),
    )


def _seed_approval(
    store: CapabilityAuthorityStore,
) -> tuple[tuple[CapabilityEvidenceRecordV1, ...], ProductCapabilityApprovalRecordV1]:
    evidence = _seed_evidence(store)
    approval = _approval(evidence)
    _approve(store, approval)
    return evidence, approval


def _activation(
    approval: ProductCapabilityApprovalRecordV1,
    *,
    activation_id: str = "activation-1",
    operation_id: str = "activation-operation-1",
    supersedes: str | None = None,
    activated_at: datetime = NOW + timedelta(minutes=3),
    valid_until: datetime = NOW + timedelta(days=10),
    freshness_policy_id: str = FRESHNESS_POLICY_ID,
    freshness_policy_digest: str = FRESHNESS_POLICY_DIGEST,
    canonical: CanonicalTransportCapability = CanonicalTransportCapability.EDGE_DOWNLINK,
    path: CapabilityIntegrationPath = CapabilityIntegrationPath.MSDK_FIELD,
    runtime_build_digest: str = BUILD,
    equipment: EquipmentScopeV1 | None = None,
) -> OperationalCapabilityActivationRecordV1:
    selected_equipment = equipment or approval.support_matrix.entries[0].equipment_scope
    scope = ActivationApplicabilityScopeV1(
        organization_id="org-1",
        site_id="site-1",
        gateway_device_id="gateway-1",
        edge_device_id="edge-1",
        integration_path=path,
        canonical_capability_id=canonical,
        equipment_scope_digest=selected_equipment.canonical_digest,
        runtime_build_digest=runtime_build_digest,
        policy_scope_id=POLICY,
        mapping_version=CapabilityMappingVersion.V1.value,
        gate_version=CapabilityGateVersion.V1.value,
    )
    configured = ConfiguredDeploymentSnapshotV1(
        configuration_record_id="deployment-config-1",
        configuration_revision=1,
        organization_id=scope.organization_id,
        site_id=scope.site_id,
        gateway_device_id=scope.gateway_device_id,
        edge_device_id=scope.edge_device_id,
        integration_path=scope.integration_path,
        canonical_capability_id=scope.canonical_capability_id,
        equipment_scope=selected_equipment,
        equipment_scope_digest=scope.equipment_scope_digest,
        runtime_build_digest=scope.runtime_build_digest,
        policy_scope_id=scope.policy_scope_id,
        mapping_version=scope.mapping_version,
        gate_version=scope.gate_version,
    )
    references = approval.support_matrix.entries[0].qualification_references
    prerequisite_payload = {
        "activationScope": scope.model_dump(mode="json", by_alias=True),
        "activationScopeDigest": scope.canonical_digest,
        "approvalRecordId": approval.approval_record_id,
        "approvalRecordDigest": product_capability_approval_record_digest(approval),
        "supportMatrixDigest": approval.support_matrix_digest,
        "evidenceSetDigest": approval.evidence_set_digest,
        "qualificationReferences": [
            item.model_dump(mode="json", by_alias=True) for item in references
        ],
        "configuredDeploymentDigest": configured.canonical_digest,
        "freshnessPolicyId": freshness_policy_id,
        "freshnessPolicyDigest": freshness_policy_digest,
    }
    return OperationalCapabilityActivationRecordV1(
        activation_authorization_id=activation_id,
        operation_id=operation_id,
        activation_scope=scope,
        activation_scope_digest=scope.canonical_digest,
        approval_record_id=approval.approval_record_id,
        approval_record_digest=product_capability_approval_record_digest(approval),
        support_matrix_digest=approval.support_matrix_digest,
        evidence_set_digest=approval.evidence_set_digest,
        qualification_references=references,
        configured_deployment=configured,
        configured_deployment_digest=configured.canonical_digest,
        freshness_policy_id=freshness_policy_id,
        freshness_policy_digest=freshness_policy_digest,
        prerequisite_set_digest=_canonical_digest(prerequisite_payload),
        activating_principal_id="ops-activator-1",
        activated_at=activated_at,
        valid_until=valid_until,
        effective_state=OperationalCapabilityActivation.ACTIVE,
        supersedes_activation_authorization_id=supersedes,
    )


def _authorize(
    store: CapabilityAuthorityStore,
    activation: OperationalCapabilityActivationRecordV1,
    *,
    principal: Principal | None = None,
    event_id: str | None = None,
) -> None:
    store.authorize_operational_capability(
        activation,
        principal=principal or _admin(activation.activating_principal_id),
        operation_id=activation.operation_id,
        event_id=event_id or f"event-{activation.operation_id}",
        occurred_at=activation.activated_at,
    )


def _suspension(
    activation: OperationalCapabilityActivationRecordV1,
    *,
    operation_id: str = "activation-suspend-operation-1",
    cause: ActivationAuthorityCause = ActivationAuthorityCause.EXPLICIT_OPERATION,
    cause_record_id: str | None = None,
    cause_record_digest: str | None = None,
) -> CapabilityActivationSuspendedV1:
    return CapabilityActivationSuspendedV1(
        operation_id=operation_id,
        target_activation_authorization_id=activation.activation_authorization_id,
        target_activation_record_digest=operational_capability_activation_record_digest(
            activation
        ),
        target_scope=activation.activation_scope,
        target_scope_digest=activation.activation_scope_digest,
        reason="operations authority suspended",
        cause=cause,
        cause_record_id=cause_record_id,
        cause_record_digest=cause_record_digest,
        suspending_principal_id="ops-activator-1",
        suspended_at=NOW + timedelta(minutes=6),
    )


def _activation_revocation(
    activation: OperationalCapabilityActivationRecordV1,
    *,
    operation_id: str = "activation-revoke-operation-1",
) -> CapabilityActivationRevokedV1:
    return CapabilityActivationRevokedV1(
        operation_id=operation_id,
        target_activation_authorization_id=activation.activation_authorization_id,
        target_activation_record_digest=operational_capability_activation_record_digest(
            activation
        ),
        target_scope=activation.activation_scope,
        target_scope_digest=activation.activation_scope_digest,
        reason="operations authority revoked",
        revoking_principal_id="ops-activator-1",
        revoked_at=NOW + timedelta(minutes=6),
    )


def _evidence_revocation(record: CapabilityEvidenceRecordV1) -> CapabilityEvidenceRevocationV1:
    scope = EvidenceApplicabilityScopeV1.from_record(record)
    return CapabilityEvidenceRevocationV1(
        target_evidence_record_id=record.evidence_record_id,
        target_scope=scope,
        target_scope_digest=scope.canonical_digest,
        reason="qualification withdrawn",
    )


def _approval_revocation(
    approval: ProductCapabilityApprovalRecordV1,
) -> ProductCapabilityApprovalRevocationV1:
    from ksi_core.capability.authority_store import ApprovalApplicabilityScopeV1

    scope = ApprovalApplicabilityScopeV1.from_record(approval)
    return ProductCapabilityApprovalRevocationV1(
        target_approval_record_id=approval.approval_record_id,
        target_scope=scope,
        target_scope_digest=scope.canonical_digest,
        reason="product approval withdrawn",
    )


def _seed_activation(
    store: CapabilityAuthorityStore,
) -> tuple[
    tuple[CapabilityEvidenceRecordV1, ...],
    ProductCapabilityApprovalRecordV1,
    OperationalCapabilityActivationRecordV1,
]:
    evidence, approval = _seed_approval(store)
    activation = _activation(approval)
    _authorize(store, activation)
    return evidence, approval, activation


def _activation_event(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(event for event in events if event["kind"] == "capability-activation-authorized")


def _activation_prerequisite_payload(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "activationScope": raw["activationScope"],
        "activationScopeDigest": raw["activationScopeDigest"],
        "approvalRecordId": raw["approvalRecordId"],
        "approvalRecordDigest": raw["approvalRecordDigest"],
        "supportMatrixDigest": raw["supportMatrixDigest"],
        "evidenceSetDigest": raw["evidenceSetDigest"],
        "qualificationReferences": raw["qualificationReferences"],
        "configuredDeploymentDigest": raw["configuredDeploymentDigest"],
        "freshnessPolicyId": raw["freshnessPolicyId"],
        "freshnessPolicyDigest": raw["freshnessPolicyDigest"],
    }


def _redigest_activation_event(event: dict[str, Any]) -> OperationalCapabilityActivationRecordV1:
    activation_raw = event["payload"]["activation"]
    activation_raw["prerequisiteSetDigest"] = _canonical_digest(
        _activation_prerequisite_payload(activation_raw)
    )
    activation = OperationalCapabilityActivationRecordV1.model_validate(activation_raw)
    event["payload"]["activationRecordDigest"] = (
        operational_capability_activation_record_digest(activation)
    )
    _redigest(event)
    return activation


def _nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_nested_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_nested_keys(item) for item in value))
    return set()


def test_valid_activation_is_durable_authority_only(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, _, activation = _seed_activation(store)
    projection = store.get_activation_projection(
        activation.activation_authorization_id, now=ACTIVE_NOW
    )
    assert projection is not None
    assert projection.lifecycle_status is ActivationLifecycleStatus.ACTIVE
    assert projection.is_current_durable_authority is True
    raw = _read(path)[-1]
    assert raw["kind"] == "capability-activation-authorized"
    activation_raw = raw["payload"]["activation"]
    assert activation_raw["freshnessPolicyId"] == FRESHNESS_POLICY_ID
    assert activation_raw["freshnessPolicyDigest"] == FRESHNESS_POLICY_DIGEST
    assert set(activation_raw) == {
        "activationAuthorizationId",
        "operationId",
        "activationScope",
        "activationScopeDigest",
        "approvalRecordId",
        "approvalRecordDigest",
        "supportMatrixDigest",
        "evidenceSetDigest",
        "qualificationReferences",
        "configuredDeployment",
        "configuredDeploymentDigest",
        "freshnessPolicyId",
        "freshnessPolicyDigest",
        "prerequisiteSetDigest",
        "activatingPrincipalId",
        "activatedAt",
        "validUntil",
        "effectiveState",
        "supersedesActivationAuthorizationId",
    }
    assert _nested_keys(activation_raw).isdisjoint(
        {
            "runtimeRouteObservation",
            "observationId",
            "observedAt",
            "expiresAt",
            "availability",
            "subjectKind",
            "subjectPortId",
            "sourceObservationRef",
            "currentRuntimeReady",
            "liveRouteReady",
            "operationallyUsable",
        }
    )
    assert not hasattr(store, "operationally_usable")


def test_activation_requires_exact_current_approval(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    records = _seed_evidence(store)
    approval = _approval(records)
    with pytest.raises(CapabilityAuthorityValidationError, match="missing approvalRecordId"):
        _authorize(store, _activation(approval))


@pytest.mark.parametrize("mismatch", ["canonical", "path", "equipment", "build"])
def test_activation_scope_must_match_approval(tmp_path: Path, mismatch: str) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, approval = _seed_approval(store)
    kwargs: dict[str, Any] = {}
    if mismatch == "canonical":
        kwargs["canonical"] = CanonicalTransportCapability.MEDIA_PULL
    elif mismatch == "path":
        kwargs["path"] = CapabilityIntegrationPath.PSDK_MANIFOLD
        kwargs["equipment"] = _equipment(CapabilityIntegrationPath.PSDK_MANIFOLD)
    elif mismatch == "equipment":
        equipment = _equipment(CapabilityIntegrationPath.MSDK_FIELD).model_copy(deep=True)
        raw = equipment.model_dump(mode="json", by_alias=True)
        raw["components"][0]["hardwareRevision"] = "rev-b"
        kwargs["equipment"] = EquipmentScopeV1.model_validate(raw)
    else:
        kwargs["runtime_build_digest"] = _digest("c")
    with pytest.raises(CapabilityAuthorityValidationError):
        _authorize(store, _activation(approval, **kwargs))


def test_activation_approval_digest_must_match(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, approval = _seed_approval(store)
    valid = _activation(approval)
    raw = valid.model_dump(mode="json", by_alias=True)
    raw["approvalRecordDigest"] = _digest("a")
    raw["prerequisiteSetDigest"] = _canonical_digest(
        valid.prerequisite_payload | {"approvalRecordDigest": _digest("a")}
    )
    wrong = OperationalCapabilityActivationRecordV1.model_validate(raw)
    with pytest.raises(CapabilityAuthorityValidationError, match="approval record digest mismatch"):
        _authorize(store, wrong)


@pytest.mark.parametrize("field", ["prerequisiteSetDigest", "configuredDeploymentDigest"])
def test_activation_structural_digest_mismatch_rejected(tmp_path: Path, field: str) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, approval = _seed_approval(store)
    valid = _activation(approval)
    malformed = valid.model_construct(**(valid.__dict__ | {field: _digest("0")}))
    with pytest.raises(CapabilityAuthorityValidationError):
        _authorize(store, malformed)


@pytest.mark.parametrize("version", ["mapping", "gate"])
def test_unknown_activation_version_fails_closed(tmp_path: Path, version: str) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, approval = _seed_approval(store)
    valid = _activation(approval)
    raw = valid.model_dump(mode="json", by_alias=True)
    key = "mappingVersion" if version == "mapping" else "gateVersion"
    raw["activationScope"][key] = "future-version"
    raw["configuredDeployment"][key] = "future-version"
    scope = ActivationApplicabilityScopeV1.model_validate(raw["activationScope"])
    configured = ConfiguredDeploymentSnapshotV1.model_validate(raw["configuredDeployment"])
    raw["activationScopeDigest"] = scope.canonical_digest
    raw["configuredDeploymentDigest"] = configured.canonical_digest
    prerequisite = valid.prerequisite_payload | {
        "activationScope": raw["activationScope"],
        "activationScopeDigest": scope.canonical_digest,
        "configuredDeploymentDigest": configured.canonical_digest,
    }
    raw["prerequisiteSetDigest"] = _canonical_digest(prerequisite)
    changed = OperationalCapabilityActivationRecordV1.model_validate(raw)
    with pytest.raises(CapabilityAuthorityValidationError, match="unsupported"):
        _authorize(store, changed)


def test_unknown_or_wrong_freshness_policy_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, approval = _seed_approval(store)
    with pytest.raises(CapabilityAuthorityValidationError, match="unsupported freshness"):
        _authorize(
            store,
            _activation(
                approval,
                freshness_policy_id="unknown-policy",
                freshness_policy_digest=_digest("9"),
            ),
        )
    with pytest.raises(CapabilityAuthorityValidationError, match="does not match"):
        _authorize(
            store,
            _activation(approval, freshness_policy_digest=_digest("8")),
        )


def test_activation_exact_retry_and_conflict(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, approval = _seed_approval(store)
    activation = _activation(approval)
    first = store.authorize_operational_capability(
        activation,
        principal=_admin(),
        operation_id=activation.operation_id,
        event_id="activation-event-1",
        occurred_at=activation.activated_at,
    )
    second = store.authorize_operational_capability(
        activation,
        principal=_admin(),
        operation_id=activation.operation_id,
        event_id="ignored-retry-event",
        occurred_at=activation.activated_at + timedelta(minutes=1),
    )
    assert first == second
    assert len(_read(path)) == 4
    changed = _activation(
        approval,
        activation_id="activation-other",
        operation_id=activation.operation_id,
    )
    with pytest.raises(CapabilityAuthorityIdempotencyConflict):
        _authorize(store, changed)


def test_activation_idempotency_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, approval = _seed_approval(store)
    activation = _activation(approval)
    _authorize(store, activation)
    store.close()
    replayed = _open(path)
    _authorize(replayed, activation, event_id="ignored-after-restart")
    assert len(_read(path)) == 4


def test_cross_kind_operation_id_is_one_namespace(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, approval = _seed_approval(store)
    activation = _activation(approval, operation_id="approval-operation-1")
    with pytest.raises(CapabilityAuthorityIdempotencyConflict):
        _authorize(store, activation)


@pytest.mark.parametrize("principal", [_field(), _admin(organization_id="wrong-org")])
def test_activation_requires_authorized_matching_organization_principal(
    tmp_path: Path, principal: Principal
) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, approval = _seed_approval(store)
    with pytest.raises(CapabilityAuthorityAuthorizationError):
        _authorize(store, _activation(approval), principal=principal)


def test_activation_permission_is_distinct_from_product_approval() -> None:
    admin_permissions = principal_permissions(_admin())
    assert Permission.CAPABILITY_ACTIVATE in admin_permissions
    assert Permission.CAPABILITY_PRODUCT_APPROVE in admin_permissions
    assert Permission.CAPABILITY_ACTIVATE is not Permission.CAPABILITY_PRODUCT_APPROVE
    assert Permission.CAPABILITY_ACTIVATE not in principal_permissions(_field())


def test_activation_rejects_revoked_or_expired_approval(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, approval = _seed_approval(store)
    store.revoke_product_approval(
        _approval_revocation(approval),
        principal=_admin("product-revoker-1"),
        operation_id="approval-revoke-operation-1",
        event_id="approval-revoke-event-1",
        occurred_at=NOW + timedelta(minutes=3),
    )
    with pytest.raises(CapabilityAuthorityValidationError, match="approval not current=REVOKED"):
        _authorize(store, _activation(approval, activated_at=NOW + timedelta(minutes=4)))

    other = _open(tmp_path / "expired-authority.jsonl")
    evidence = _seed_evidence(other)
    expired = _approval(
        evidence,
        approval_id="approval-expired",
        operation_id="approval-expired-operation",
        valid_until=NOW + timedelta(minutes=3),
    )
    _approve(other, expired)
    with pytest.raises(CapabilityAuthorityValidationError, match="approval not current=EXPIRED"):
        _authorize(
            other,
            _activation(
                expired,
                activation_id="activation-expired-approval",
                operation_id="activation-expired-approval-operation",
                activated_at=NOW + timedelta(minutes=4),
                valid_until=NOW + timedelta(minutes=5),
            ),
        )


def test_prerequisite_set_digest_is_deterministic_and_binds_every_authority_dimension(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    _, approval = _seed_approval(store)
    first = _activation(approval)
    second = _activation(
        approval,
        activation_id="activation-2",
        operation_id="activation-operation-2",
        activated_at=NOW + timedelta(minutes=4),
    )
    assert first.prerequisite_payload == second.prerequisite_payload
    assert first.prerequisite_set_digest == second.prerequisite_set_digest
    assert first.prerequisite_set_digest == _canonical_digest(first.prerequisite_payload)
    assert set(first.prerequisite_payload) == {
        "activationScope",
        "activationScopeDigest",
        "approvalRecordId",
        "approvalRecordDigest",
        "supportMatrixDigest",
        "evidenceSetDigest",
        "qualificationReferences",
        "configuredDeploymentDigest",
        "freshnessPolicyId",
        "freshnessPolicyDigest",
    }

    mutations: tuple[tuple[str, str | None, Any], ...] = (
        ("approvalRecordId", None, "approval-other"),
        ("approvalRecordDigest", None, _digest("1")),
        ("supportMatrixDigest", None, _digest("2")),
        ("evidenceSetDigest", None, _digest("3")),
        ("qualificationReferences", None, []),
        ("activationScope", "canonicalCapabilityId", "media_pull"),
        ("activationScope", "integrationPath", "psdk_manifold"),
        ("activationScope", "equipmentScopeDigest", _digest("4")),
        ("activationScope", "runtimeBuildDigest", _digest("5")),
        ("activationScope", "policyScopeId", "policy-other"),
        ("activationScope", "mappingVersion", "mapping-other"),
        ("activationScope", "gateVersion", "gate-other"),
        ("configuredDeploymentDigest", None, _digest("6")),
        ("freshnessPolicyId", None, "freshness-other"),
        ("freshnessPolicyDigest", None, _digest("7")),
    )
    for top_level, nested, value in mutations:
        changed = json.loads(json.dumps(first.prerequisite_payload))
        if nested is None:
            changed[top_level] = value
        else:
            changed[top_level][nested] = value
        assert _canonical_digest(changed) != first.prerequisite_set_digest
    assert "observedAt" not in _nested_keys(first.prerequisite_payload)


def test_explicit_suspension_is_exact_idempotent_and_replays(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, _, activation = _seed_activation(store)
    suspension = _suspension(activation)
    first = store.suspend_operational_capability(
        suspension,
        principal=_admin(),
        operation_id=suspension.operation_id,
        event_id="activation-suspend-event-1",
        occurred_at=suspension.suspended_at,
    )
    second = store.suspend_operational_capability(
        suspension,
        principal=_admin(),
        operation_id=suspension.operation_id,
        event_id="ignored-suspension-retry",
        occurred_at=suspension.suspended_at,
    )
    assert first == second
    assert len(_read(path)) == 5
    before = store.get_activation_projection(activation.activation_authorization_id, now=ACTIVE_NOW)
    assert before is not None
    assert before.lifecycle_status is ActivationLifecycleStatus.SUSPENDED
    assert before.is_current_durable_authority is False
    assert before.suspended_by_event_id == "activation-suspend-event-1"
    store.close()
    replayed = _open(path)
    assert replayed.get_activation_projection(
        activation.activation_authorization_id, now=ACTIVE_NOW
    ) == before


@pytest.mark.parametrize("organization_id", ["org-other", "legacy"])
def test_lifecycle_mutations_require_matching_nonlegacy_organization(
    tmp_path: Path, organization_id: str
) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    _, _, activation = _seed_activation(store)
    suspension = _suspension(activation)
    with pytest.raises(CapabilityAuthorityAuthorizationError, match="matching organization"):
        store.suspend_operational_capability(
            suspension,
            principal=_admin(organization_id=organization_id),
            operation_id=suspension.operation_id,
            event_id="cross-org-suspend",
            occurred_at=suspension.suspended_at,
        )
    revocation = _activation_revocation(activation)
    with pytest.raises(CapabilityAuthorityAuthorizationError, match="matching organization"):
        store.revoke_operational_capability(
            revocation,
            principal=_admin(organization_id=organization_id),
            operation_id=revocation.operation_id,
            event_id="cross-org-revoke",
            occurred_at=revocation.revoked_at,
        )


@pytest.mark.parametrize("mode", ["missing", "wrong-digest", "wrong-scope"])
def test_explicit_suspension_target_must_be_exact(tmp_path: Path, mode: str) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    _, _, activation = _seed_activation(store)
    raw = _suspension(activation).model_dump(mode="json", by_alias=True)
    if mode == "missing":
        raw["targetActivationAuthorizationId"] = "activation-missing"
    elif mode == "wrong-digest":
        raw["targetActivationRecordDigest"] = _digest("0")
    else:
        raw["targetScope"]["siteId"] = "site-other"
        altered = ActivationApplicabilityScopeV1.model_validate(raw["targetScope"])
        raw["targetScopeDigest"] = altered.canonical_digest
    suspension = CapabilityActivationSuspendedV1.model_validate(raw)
    with pytest.raises(CapabilityAuthorityConflict):
        store.suspend_operational_capability(
            suspension,
            principal=_admin(),
            operation_id=suspension.operation_id,
            event_id=f"suspension-{mode}-event",
            occurred_at=suspension.suspended_at,
        )


def test_explicit_suspension_operation_conflict(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    _, _, activation = _seed_activation(store)
    suspension = _suspension(activation)
    store.suspend_operational_capability(
        suspension,
        principal=_admin(),
        operation_id=suspension.operation_id,
        event_id="activation-suspend-event-1",
        occurred_at=suspension.suspended_at,
    )
    changed = suspension.model_copy(update={"reason": "different durable suspension reason"})
    with pytest.raises(CapabilityAuthorityIdempotencyConflict):
        store.suspend_operational_capability(
            changed,
            principal=_admin(),
            operation_id=changed.operation_id,
            event_id="activation-suspend-event-2",
            occurred_at=changed.suspended_at,
        )


def test_suspension_before_activation_replay_isolates_activation_chain(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, _, activation = _seed_activation(store)
    suspension = _suspension(activation)
    store.suspend_operational_capability(
        suspension,
        principal=_admin(),
        operation_id=suspension.operation_id,
        event_id="activation-suspend-event-1",
        occurred_at=suspension.suspended_at,
    )
    store.close()
    events = _read(path)
    events[-2], events[-1] = events[-1], events[-2]
    _write(path, events)
    replayed = _open(path)
    assert (
        replayed.activation_chain_status(activation.activation_scope)
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


def test_evidence_revocation_compound_suspends_activation_and_replays(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    evidence, _, activation = _seed_activation(store)
    revoked = evidence[0]
    store.revoke_evidence(
        _evidence_revocation(revoked),
        operation_id="evidence-revoke-operation-1",
        event_id="evidence-revoke-event-1",
        actor_principal_id=revoked.verifier_principal_id,
        occurred_at=NOW + timedelta(minutes=6),
    )
    raw = _read(path)[-1]
    suspensions = raw["payload"]["affectedActivationSuspensions"]
    assert len(suspensions) == 1
    assert suspensions[0]["targetActivationAuthorizationId"] == (
        activation.activation_authorization_id
    )
    assert suspensions[0]["cause"] == ActivationAuthorityCause.EVIDENCE_REVOKED.value
    activation_projection = store.get_activation_projection(
        activation.activation_authorization_id, now=NOW + timedelta(minutes=7)
    )
    assert activation_projection is not None
    assert activation_projection.lifecycle_status is ActivationLifecycleStatus.SUSPENDED
    assert store.current_durable_activations(
        activation.activation_scope, now=NOW + timedelta(minutes=7)
    ) == ()
    store.close()

    replayed = _open(path)
    evidence_projection = replayed.get_projection(
        revoked.evidence_record_id, now=NOW + timedelta(minutes=7)
    )
    replayed_activation = replayed.get_activation_projection(
        activation.activation_authorization_id, now=NOW + timedelta(minutes=7)
    )
    assert evidence_projection is not None
    assert evidence_projection.lifecycle_status is EvidenceLifecycleStatus.REVOKED
    assert replayed_activation is not None
    assert replayed_activation.lifecycle_status is ActivationLifecycleStatus.SUSPENDED


def test_approval_revocation_compound_suspends_activation_and_replays(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, approval, activation = _seed_activation(store)
    store.revoke_product_approval(
        _approval_revocation(approval),
        principal=_admin("product-revoker-1"),
        operation_id="approval-revoke-operation-1",
        event_id="approval-revoke-event-1",
        occurred_at=NOW + timedelta(minutes=6),
    )
    raw = _read(path)[-1]
    suspension = raw["payload"]["affectedActivationSuspensions"][0]
    assert suspension["cause"] == ActivationAuthorityCause.APPROVAL_REVOKED.value
    projection = store.get_activation_projection(
        activation.activation_authorization_id, now=NOW + timedelta(minutes=7)
    )
    assert projection is not None
    assert projection.lifecycle_status is ActivationLifecycleStatus.SUSPENDED
    store.close()
    replayed = _open(path)
    replayed_projection = replayed.get_activation_projection(
        activation.activation_authorization_id, now=NOW + timedelta(minutes=7)
    )
    assert replayed_projection is not None
    assert replayed_projection.lifecycle_status is ActivationLifecycleStatus.SUSPENDED


def test_prerequisite_restoration_requires_new_activation_id(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    evidence, _, first_activation = _seed_activation(store)
    revoked = evidence[0]
    store.revoke_evidence(
        _evidence_revocation(revoked),
        operation_id="evidence-revoke-operation-1",
        event_id="evidence-revoke-event-1",
        actor_principal_id=revoked.verifier_principal_id,
        occurred_at=NOW + timedelta(minutes=6),
    )
    restored = _seed_evidence(store, suffix="-restored", supersedes=evidence)
    restored_approval = _approval(
        restored,
        approval_id="approval-2",
        operation_id="approval-operation-2",
        approved_at=NOW + timedelta(minutes=7),
    )
    _approve(store, restored_approval)

    old_projection = store.get_activation_projection(
        first_activation.activation_authorization_id, now=NOW + timedelta(minutes=9)
    )
    assert old_projection is not None
    assert old_projection.lifecycle_status is ActivationLifecycleStatus.SUSPENDED
    assert store.current_durable_activations(
        first_activation.activation_scope, now=NOW + timedelta(minutes=9)
    ) == ()

    second_activation = _activation(
        restored_approval,
        activation_id="activation-2",
        operation_id="activation-operation-2",
        supersedes=first_activation.activation_authorization_id,
        activated_at=NOW + timedelta(minutes=9),
    )
    _authorize(store, second_activation)
    current = store.current_durable_activations(
        second_activation.activation_scope, now=NOW + timedelta(minutes=10)
    )
    assert tuple(item.record.activation_authorization_id for item in current) == (
        "activation-2",
    )
    historical = store.get_activation_projection(
        first_activation.activation_authorization_id, now=NOW + timedelta(minutes=10)
    )
    assert historical is not None
    assert historical.lifecycle_status is ActivationLifecycleStatus.SUSPENDED


def test_explicit_activation_revocation_is_idempotent_and_replays(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, _, activation = _seed_activation(store)
    revocation = _activation_revocation(activation)
    first = store.revoke_operational_capability(
        revocation,
        principal=_admin(),
        operation_id=revocation.operation_id,
        event_id="activation-revoke-event-1",
        occurred_at=revocation.revoked_at,
    )
    second = store.revoke_operational_capability(
        revocation,
        principal=_admin(),
        operation_id=revocation.operation_id,
        event_id="ignored-revocation-retry",
        occurred_at=revocation.revoked_at,
    )
    assert first == second
    projection = store.get_activation_projection(
        activation.activation_authorization_id, now=NOW + timedelta(minutes=7)
    )
    assert projection is not None
    assert projection.lifecycle_status is ActivationLifecycleStatus.REVOKED
    store.close()
    replayed = _open(path)
    assert replayed.get_activation_projection(
        activation.activation_authorization_id, now=NOW + timedelta(minutes=7)
    ) == projection


@pytest.mark.parametrize("mode", ["before-approval", "missing-approval", "blocked-approval"])
def test_activation_replay_requires_causally_prior_valid_approval(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, approval, activation = _seed_activation(store)
    store.close()
    events = _read(path)
    approval_index = next(
        index
        for index, event in enumerate(events)
        if event["kind"] == "capability-product-approved"
    )
    activation_index = next(
        index
        for index, event in enumerate(events)
        if event["kind"] == "capability-activation-authorized"
    )
    if mode == "before-approval":
        events[approval_index], events[activation_index] = (
            events[activation_index],
            events[approval_index],
        )
    elif mode == "missing-approval":
        events.pop(approval_index)
    else:
        approval_event = events[approval_index]
        approval_event["payload"]["approval"]["supportMatrixDigest"] = _digest("0")
        _redigest(approval_event)
    _write(path, events)

    replayed = _open(path)
    assert (
        replayed.activation_chain_status(activation.activation_scope)
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )
    assert replayed.current_durable_activations(
        activation.activation_scope, now=ACTIVE_NOW
    ) == ()
    if mode == "blocked-approval":
        assert replayed.get_approval_record(approval.approval_record_id) is None


def test_activation_replay_wrong_approval_digest_isolated(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, _, activation = _seed_activation(store)
    store.close()
    events = _read(path)
    event = _activation_event(events)
    event["payload"]["activation"]["approvalRecordDigest"] = _digest("0")
    altered = _redigest_activation_event(event)
    _write(path, events)
    replayed = _open(path)
    assert (
        replayed.activation_chain_status(altered.activation_scope)
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


@pytest.mark.parametrize(
    "field", ["prerequisiteSetDigest", "configuredDeploymentDigest"]
)
def test_activation_replay_structural_digest_corruption_isolated(
    tmp_path: Path, field: str
) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, _, activation = _seed_activation(store)
    store.close()
    events = _read(path)
    event = _activation_event(events)
    event["payload"]["activation"][field] = _digest("0")
    _redigest(event)
    _write(path, events)
    replayed = _open(path)
    assert (
        replayed.activation_chain_status(activation.activation_scope)
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


def test_activation_replay_freshness_policy_digest_corruption_isolated(
    tmp_path: Path,
) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, _, _ = _seed_activation(store)
    store.close()
    events = _read(path)
    event = _activation_event(events)
    event["payload"]["activation"]["freshnessPolicyDigest"] = _digest("0")
    altered = _redigest_activation_event(event)
    _write(path, events)
    replayed = _open(path)
    assert (
        replayed.activation_chain_status(altered.activation_scope)
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


@pytest.mark.parametrize("field", ["mappingVersion", "gateVersion"])
def test_activation_replay_unsupported_version_isolated(tmp_path: Path, field: str) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, _, _ = _seed_activation(store)
    store.close()
    events = _read(path)
    event = _activation_event(events)
    raw = event["payload"]["activation"]
    raw["activationScope"][field] = f"future-{field}"
    raw["configuredDeployment"][field] = f"future-{field}"
    scope = ActivationApplicabilityScopeV1.model_validate(raw["activationScope"])
    configured = ConfiguredDeploymentSnapshotV1.model_validate(raw["configuredDeployment"])
    raw["activationScopeDigest"] = scope.canonical_digest
    raw["configuredDeploymentDigest"] = configured.canonical_digest
    _redigest_activation_event(event)
    _write(path, events)
    replayed = _open(path)
    assert (
        replayed.activation_chain_status(scope)
        is CapabilityAuthorityChainStatus.BLOCKED_UNSUPPORTED_VERSION
    )


def test_activation_replay_suspension_target_mismatch_isolated(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, _, activation = _seed_activation(store)
    suspension = _suspension(activation)
    store.suspend_operational_capability(
        suspension,
        principal=_admin(),
        operation_id=suspension.operation_id,
        event_id="activation-suspend-event-1",
        occurred_at=suspension.suspended_at,
    )
    store.close()
    events = _read(path)
    events[-1]["payload"]["activationSuspension"][
        "targetActivationAuthorizationId"
    ] = "activation-missing"
    _redigest(events[-1])
    _write(path, events)
    replayed = _open(path)
    assert (
        replayed.activation_chain_status(activation.activation_scope)
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


@pytest.mark.parametrize("collision", ["event", "operation"])
def test_activation_replay_cross_kind_identity_collision_isolated(
    tmp_path: Path, collision: str
) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _, _, activation = _seed_activation(store)
    store.close()
    events = _read(path)
    event = _activation_event(events)
    approval_event = next(
        item for item in events if item["kind"] == "capability-product-approved"
    )
    if collision == "event":
        event["eventId"] = approval_event["eventId"]
    else:
        event["operationId"] = approval_event["operationId"]
        event["payload"]["activation"]["operationId"] = approval_event["operationId"]
        _redigest_activation_event(event)
    _redigest(event)
    _write(path, events)
    replayed = _open(path)
    assert (
        replayed.activation_chain_status(activation.activation_scope)
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


def test_unattributable_activation_corruption_refuses_store_start(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _seed_activation(store)
    store.close()
    events = _read(path)
    event = _activation_event(events)
    del event["payload"]["activation"]["activationScope"]
    _redigest(event)
    _write(path, events)
    with pytest.raises(CapabilityAuthorityRecoveryError):
        _open(path)
