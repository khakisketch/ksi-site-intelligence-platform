"""CAP-3 durable ProductCapabilityApproval authority and replay fixtures."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ksi_core.auth import Principal, PrincipalKind, Role
from ksi_core.capability.authority_store import (
    CAPABILITY_AUTHORITY_JOURNAL_NAME,
    ApprovalApplicabilityScopeV1,
    ApprovalLifecycleStatus,
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
    EquipmentComponentV1,
    EquipmentRole,
    EquipmentScopeV1,
    EvidenceApplicabilityScopeV1,
    ProductCapabilityApprovalRecordV1,
    ProductCapabilityApprovalRevocationV1,
    ProductSupportMatrixEntryV1,
    ProductSupportMatrixV1,
    QualificationReferenceV1,
    capability_evidence_record_digest,
    product_capability_approval_record_digest,
)
from ksi_core.durable_journal import DurableJournal
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_domain.capability_contract import (
    CanonicalTransportCapability,
    CapabilityGateVersion,
    CapabilityIntegrationPath,
    CapabilityMappingVersion,
    LegacyCapabilitySemantic,
    ProductCapabilityApproval,
    RouteEvidenceQualification,
    SourceCapabilityId,
    parse_legacy_core_capability_state,
    resolve_capability_mapping,
)

NOW = datetime(2026, 9, 3, 2, 0, tzinfo=UTC)
ACTIVE_NOW = NOW + timedelta(minutes=5)
POLICY = "ksi-capability-policy-v1"
BUILD = "sha256:" + "b" * 64

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


def _event_digest(raw: dict[str, Any]) -> str:
    content = dict(raw)
    content.pop("payloadSha256", None)
    return "sha256:" + hashlib.sha256(canonical_json_bytes(content)).hexdigest()


def _redigest(event: dict[str, Any]) -> None:
    event["payloadSha256"] = _event_digest(event)


def _read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]


def _write(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        encoding="ascii",
    )


def _open(path: Path) -> CapabilityAuthorityStore:
    return CapabilityAuthorityStore(DurableJournal(path))


def _admin(principal_id: str = "product-approver-1") -> Principal:
    return Principal(
        principal_id=principal_id,
        kind=PrincipalKind.OPERATOR,
        role=Role.ADMIN,
        device_id=None,
        organization_id="ksi-product",
    )


def _field_operator(principal_id: str = "field-operator-1") -> Principal:
    return Principal(
        principal_id=principal_id,
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id="ksi-product",
    )


def _equipment_scope(
    path: CapabilityIntegrationPath, *, firmware: str = "firmware-1.0"
) -> EquipmentScopeV1:
    return EquipmentScopeV1(
        components=tuple(
            EquipmentComponentV1(
                role=role,
                product_family="DJI-Matrice",
                hardware_model=f"model-{role.value.lower()}",
                hardware_revision="rev-a",
                firmware_or_image_version=firmware,
            )
            for role in _ROLES[path]
        )
    )


def _evidence(
    record_id: str,
    *,
    source: SourceCapabilityId,
    canonical: CanonicalTransportCapability,
    path: CapabilityIntegrationPath,
    equipment_scope: EquipmentScopeV1,
    build: str = BUILD,
    policy: str = POLICY,
    mapping_version: str = CapabilityMappingVersion.V1.value,
    performer: str | None = None,
    verifier: str | None = None,
    valid_until: datetime = NOW + timedelta(days=30),
    supersedes: str | None = None,
) -> CapabilityEvidenceRecordV1:
    suffix = source.value.lower().replace("-", "")
    return CapabilityEvidenceRecordV1(
        evidence_record_id=record_id,
        canonical_capability_id=canonical,
        source_capability_id=source,
        mapping_version=mapping_version,
        integration_path=path,
        equipment_scope=equipment_scope,
        equipment_scope_digest=equipment_scope.canonical_digest,
        test_build_digest=build,
        policy_scope_id=policy,
        evidence_type=CapabilityEvidenceType.HIL,
        evidence_artifact_ref=f"evidence://capability/{record_id}",
        evidence_digest=_digest("e"),
        procedure_ref="procedure://dji-route-v1",
        procedure_digest=_digest("d"),
        performer_principal_id=performer or f"field-{suffix}",
        verifier_principal_id=verifier or f"verifier-{suffix}",
        performed_at=NOW - timedelta(hours=1),
        verified_at=NOW,
        verification_result=RouteEvidenceQualification.QUALIFIED,
        valid_until=valid_until,
        supersedes_evidence_record_id=supersedes,
    )


def _seed(
    store: CapabilityAuthorityStore,
    *,
    canonical: CanonicalTransportCapability = CanonicalTransportCapability.EDGE_DOWNLINK,
    path: CapabilityIntegrationPath = CapabilityIntegrationPath.MSDK_FIELD,
    equipment_scope: EquipmentScopeV1 | None = None,
    build: str = BUILD,
    policy: str = POLICY,
    performer: str | None = None,
    verifier: str | None = None,
    valid_until: datetime = NOW + timedelta(days=30),
) -> tuple[CapabilityEvidenceRecordV1, ...]:
    scope = equipment_scope or _equipment_scope(path)
    requirement = resolve_capability_mapping(CapabilityMappingVersion.V1).requirement_for(
        canonical, path
    )
    records: list[CapabilityEvidenceRecordV1] = []
    for index, source in enumerate(requirement.required_sources, start=1):
        record = _evidence(
            f"evidence-{source.value.lower()}",
            source=source,
            canonical=canonical,
            path=path,
            equipment_scope=scope,
            build=build,
            policy=policy,
            performer=performer,
            verifier=verifier,
            valid_until=valid_until,
        )
        store.record_evidence(
            record,
            operation_id=f"evidence-operation-{index}",
            event_id=f"evidence-event-{index}",
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
    approver: str = "product-approver-1",
    canonical: CanonicalTransportCapability | None = None,
    path: CapabilityIntegrationPath | None = None,
    equipment_scope: EquipmentScopeV1 | None = None,
    build: str = BUILD,
    policy: str = POLICY,
    mapping_version: str = CapabilityMappingVersion.V1.value,
    gate_version: str = CapabilityGateVersion.V1.value,
    approved_at: datetime = NOW + timedelta(minutes=1),
    valid_until: datetime = NOW + timedelta(days=20),
    supersedes: str | None = None,
    reference_digest_overrides: dict[str, str] | None = None,
) -> ProductCapabilityApprovalRecordV1:
    first = records[0]
    approval_path = path or first.integration_path
    approval_scope = equipment_scope or first.equipment_scope
    references = tuple(
        sorted(
            (
                QualificationReferenceV1(
                    qualification_record_id=record.evidence_record_id,
                    qualification_record_digest=(reference_digest_overrides or {}).get(
                        record.evidence_record_id,
                        capability_evidence_record_digest(record),
                    ),
                )
                for record in records
            ),
            key=lambda item: item.qualification_record_id,
        )
    )
    matrix = ProductSupportMatrixV1(
        entries=(
            ProductSupportMatrixEntryV1(
                integration_path=approval_path,
                equipment_scope=approval_scope,
                equipment_scope_digest=approval_scope.canonical_digest,
                qualification_references=references,
            ),
        )
    )
    return ProductCapabilityApprovalRecordV1(
        approval_record_id=approval_id,
        operation_id=operation_id,
        canonical_capability_id=canonical or first.canonical_capability_id,
        mapping_version=mapping_version,
        gate_version=gate_version,
        support_matrix=matrix,
        support_matrix_digest=matrix.canonical_digest,
        evidence_set_digest=matrix.evidence_set_digest,
        product_build_digest=build,
        policy_scope_id=policy,
        approver_principal_id=approver,
        approved_at=approved_at,
        valid_until=valid_until,
        decision=ProductCapabilityApproval.APPROVED,
        supersedes_approval_record_id=supersedes,
    )


def _approve(
    store: CapabilityAuthorityStore,
    record: ProductCapabilityApprovalRecordV1,
    *,
    principal: Principal | None = None,
    event_id: str = "approval-event-1",
    occurred_at: datetime = NOW + timedelta(minutes=2),
) -> None:
    store.approve_product_capability(
        record,
        principal=principal or _admin(record.approver_principal_id),
        operation_id=record.operation_id,
        event_id=event_id,
        occurred_at=occurred_at,
    )


def _approval_scope(
    record: ProductCapabilityApprovalRecordV1,
) -> ApprovalApplicabilityScopeV1:
    return ApprovalApplicabilityScopeV1.from_record(record)


def _approval_revocation(
    record: ProductCapabilityApprovalRecordV1,
) -> ProductCapabilityApprovalRevocationV1:
    scope = _approval_scope(record)
    return ProductCapabilityApprovalRevocationV1(
        target_approval_record_id=record.approval_record_id,
        target_scope=scope,
        target_scope_digest=scope.canonical_digest,
        reason="product approval withdrawn",
    )


def _rewrite_approval_event(event: dict[str, Any]) -> None:
    raw = event["payload"]["approval"]
    matrix = ProductSupportMatrixV1.model_validate(raw["supportMatrix"])
    raw["supportMatrixDigest"] = matrix.canonical_digest
    raw["evidenceSetDigest"] = matrix.evidence_set_digest
    record = ProductCapabilityApprovalRecordV1.model_validate(raw)
    event["payload"]["approvalRecordDigest"] = product_capability_approval_record_digest(record)
    _redigest(event)


def test_valid_exact_evidence_set_creates_durable_non_operational_approval(
    tmp_path: Path,
) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    records = _seed(store)
    approval = _approval(records)
    _approve(store, approval)

    projection = store.get_approval_projection(approval.approval_record_id, now=ACTIVE_NOW)
    assert projection is not None and projection.is_currently_effective
    assert store.approval_count == 1
    raw = _read(path)[-1]
    assert raw["kind"] == "capability-product-approved"
    assert raw["actorPrincipalId"] == approval.approver_principal_id
    assert raw["payload"]["approvalRecordDigest"] == product_capability_approval_record_digest(
        approval
    )
    assert "activationAuthorizationId" not in json.dumps(raw)


def test_partial_required_source_set_is_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    records = _seed(store)
    with pytest.raises(CapabilityAuthorityValidationError):
        _approve(store, _approval(records[:1]))


@pytest.mark.parametrize("mismatch", ["path", "equipment", "build", "policy", "canonical"])
def test_wrong_evidence_scope_is_rejected(tmp_path: Path, mismatch: str) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    records = _seed(store)
    kwargs: dict[str, Any] = {}
    if mismatch == "path":
        kwargs["path"] = CapabilityIntegrationPath.MANIFOLD_DIRECT
    elif mismatch == "equipment":
        kwargs["equipment_scope"] = _equipment_scope(
            CapabilityIntegrationPath.MSDK_FIELD, firmware="firmware-2.0"
        )
    elif mismatch == "build":
        kwargs["build"] = _digest("c")
    elif mismatch == "policy":
        kwargs["policy"] = "ksi-capability-policy-v2"
    else:
        kwargs["canonical"] = CanonicalTransportCapability.MEDIA_PULL
    with pytest.raises(CapabilityAuthorityValidationError):
        _approve(store, _approval(records, **kwargs))


def test_psdk_wayline_requires_all_three_sources(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    records = _seed(
        store,
        canonical=CanonicalTransportCapability.WAYLINE_DELIVERY,
        path=CapabilityIntegrationPath.PSDK_MANIFOLD,
    )
    assert len(records) == 3
    _approve(store, _approval(records))
    assert store.approval_count == 1


@pytest.mark.parametrize(
    "principal",
    [
        _field_operator(),
        Principal(
            principal_id="gateway-1",
            kind=PrincipalKind.GATEWAY_DEVICE,
            role=None,
            device_id="gateway-1",
        ),
    ],
)
def test_only_admin_product_approver_is_authorized(tmp_path: Path, principal: Principal) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    approval = _approval(_seed(store), approver=principal.principal_id)
    with pytest.raises(CapabilityAuthorityAuthorizationError):
        _approve(store, approval, principal=principal)


def test_evidence_performer_is_not_product_approver(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    records = _seed(store, performer="product-approver-1")
    with pytest.raises(CapabilityAuthorityValidationError):
        _approve(store, _approval(records))


def test_evidence_verifier_is_not_product_approver(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    records = _seed(store, verifier="product-approver-1")
    with pytest.raises(CapabilityAuthorityValidationError):
        _approve(store, _approval(records))


def test_approval_exact_operation_retry_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    approval = _approval(_seed(store))
    first = store.approve_product_capability(
        approval,
        principal=_admin(),
        operation_id=approval.operation_id,
        event_id="approval-event-1",
        occurred_at=NOW + timedelta(minutes=2),
    )
    second = store.approve_product_capability(
        approval,
        principal=_admin(),
        operation_id=approval.operation_id,
        event_id="ignored-retry-event",
        occurred_at=NOW + timedelta(minutes=3),
    )
    assert second == first
    assert (
        len(_read(path))
        == len(
            resolve_capability_mapping(CapabilityMappingVersion.V1)
            .requirement_for(
                approval.canonical_capability_id,
                approval.support_matrix.entries[0].integration_path,
            )
            .required_sources
        )
        + 1
    )


def test_approval_operation_conflict_is_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    records = _seed(store)
    first = _approval(records)
    _approve(store, first)
    changed = _approval(records, valid_until=NOW + timedelta(days=19))
    with pytest.raises(CapabilityAuthorityIdempotencyConflict):
        _approve(store, changed, event_id="approval-event-conflict")


def test_approval_idempotency_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    approval = _approval(_seed(store))
    _approve(store, approval)
    store.close()
    before = path.read_bytes()
    replayed = _open(path)
    _approve(replayed, approval, event_id="ignored-after-restart")
    assert path.read_bytes() == before
    changed = _approval(
        _seed_reference_only(replayed, approval), valid_until=NOW + timedelta(days=19)
    )
    with pytest.raises(CapabilityAuthorityIdempotencyConflict):
        _approve(replayed, changed, event_id="conflict-after-restart")


def _seed_reference_only(
    store: CapabilityAuthorityStore, approval: ProductCapabilityApprovalRecordV1
) -> tuple[CapabilityEvidenceRecordV1, ...]:
    records = []
    for entry in approval.support_matrix.entries:
        for reference in entry.qualification_references:
            record = store.get_record(reference.qualification_record_id)
            assert record is not None
            records.append(record)
    return tuple(records)


@pytest.mark.parametrize("mode", ["before", "missing", "digest"])
def test_approval_predecessor_corruption_isolated(tmp_path: Path, mode: str) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    approval = _approval(_seed(store))
    _approve(store, approval)
    store.close()
    events = _read(path)
    if mode == "before":
        events = [events[-1], *events[:-1]]
    elif mode == "missing":
        events = [events[-1]]
    else:
        ref = events[-1]["payload"]["approval"]["supportMatrix"]["entries"][0][
            "qualificationReferences"
        ][0]
        ref["qualificationRecordDigest"] = _digest("f")
        _rewrite_approval_event(events[-1])
    _write(path, events)

    replayed = _open(path)
    assert replayed.get_approval_record(approval.approval_record_id) is None
    assert replayed.isolated_chain_count >= 1


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (timedelta(seconds=-1), ApprovalLifecycleStatus.CURRENT),
        (timedelta(), ApprovalLifecycleStatus.EXPIRED),
        (timedelta(seconds=1), ApprovalLifecycleStatus.EXPIRED),
    ],
)
def test_approval_expiry_boundary(
    tmp_path: Path, offset: timedelta, expected: ApprovalLifecycleStatus
) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    approval = _approval(_seed(store))
    _approve(store, approval)
    projection = store.get_approval_projection(
        approval.approval_record_id, now=approval.valid_until + offset
    )
    assert projection is not None and projection.lifecycle_status is expected


def test_exact_scope_approval_supersession_is_append_only(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    records = _seed(store)
    first = _approval(records)
    _approve(store, first)
    second = _approval(
        records,
        approval_id="approval-2",
        operation_id="approval-operation-2",
        approved_at=NOW + timedelta(minutes=3),
        valid_until=NOW + timedelta(days=25),
        supersedes=first.approval_record_id,
    )
    _approve(store, second, event_id="approval-event-2", occurred_at=NOW + timedelta(minutes=4))
    first_projection = store.get_approval_projection(first.approval_record_id, now=ACTIVE_NOW)
    second_projection = store.get_approval_projection(second.approval_record_id, now=ACTIVE_NOW)
    assert first_projection is not None
    assert first_projection.lifecycle_status is ApprovalLifecycleStatus.SUPERSEDED
    assert second_projection is not None and second_projection.is_currently_effective


def test_cross_scope_approval_supersession_is_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    records = _seed(store)
    first = _approval(records)
    _approve(store, first)
    different_scope = _approval(
        records,
        approval_id="approval-2",
        operation_id="approval-operation-2",
        build=_digest("c"),
        supersedes=first.approval_record_id,
    )
    with pytest.raises((CapabilityAuthorityConflict, CapabilityAuthorityValidationError)):
        _approve(store, different_scope, event_id="approval-event-2")


def test_approval_supersession_forward_reference_isolated(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    records = _seed(store)
    first = _approval(records)
    _approve(store, first)
    second = _approval(
        records,
        approval_id="approval-2",
        operation_id="approval-operation-2",
        approved_at=NOW + timedelta(minutes=3),
        valid_until=NOW + timedelta(days=25),
        supersedes=first.approval_record_id,
    )
    _approve(store, second, event_id="approval-event-2", occurred_at=NOW + timedelta(minutes=4))
    store.close()
    events = _read(path)
    events[-2], events[-1] = events[-1], events[-2]
    _write(path, events)
    replayed = _open(path)
    assert (
        replayed.approval_chain_status(_approval_scope(second))
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


def test_approval_revocation_is_exact_durable_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    approval = _approval(_seed(store))
    _approve(store, approval)
    revocation = _approval_revocation(approval)
    first = store.revoke_product_approval(
        revocation,
        principal=_admin(),
        operation_id="approval-revoke-operation-1",
        event_id="approval-revoke-event-1",
        occurred_at=NOW + timedelta(minutes=3),
    )
    second = store.revoke_product_approval(
        revocation,
        principal=_admin(),
        operation_id="approval-revoke-operation-1",
        event_id="ignored-revoke-retry",
        occurred_at=NOW + timedelta(minutes=4),
    )
    assert first == second
    projection = store.get_approval_projection(approval.approval_record_id, now=ACTIVE_NOW)
    assert projection is not None
    assert projection.lifecycle_status is ApprovalLifecycleStatus.REVOKED
    payload = _read(path)[-1]["payload"]
    assert payload["affectedActivationSuspensions"] == []
    assert "activationAuthorizationId" not in json.dumps(payload)


@pytest.mark.parametrize("mode", ["missing", "wrong-scope"])
def test_approval_revocation_target_must_be_exact(tmp_path: Path, mode: str) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    approval = _approval(_seed(store))
    _approve(store, approval)
    revocation = _approval_revocation(approval)
    if mode == "missing":
        raw = revocation.model_dump(mode="json", by_alias=True)
        raw["targetApprovalRecordId"] = "missing-approval"
    else:
        raw = revocation.model_dump(mode="json", by_alias=True)
        raw["targetScope"]["productBuildDigest"] = _digest("c")
        altered_scope = ApprovalApplicabilityScopeV1.model_validate(raw["targetScope"])
        raw["targetScopeDigest"] = altered_scope.canonical_digest
    with pytest.raises(CapabilityAuthorityConflict):
        store.revoke_product_approval(
            ProductCapabilityApprovalRevocationV1.model_validate(raw),
            principal=_admin(),
            operation_id="approval-revoke-operation-1",
            event_id="approval-revoke-event-1",
            occurred_at=NOW + timedelta(minutes=3),
        )


def test_approval_revocation_operation_conflict(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    approval = _approval(_seed(store))
    _approve(store, approval)
    first = _approval_revocation(approval)
    store.revoke_product_approval(
        first,
        principal=_admin(),
        operation_id="approval-revoke-operation-1",
        event_id="approval-revoke-event-1",
        occurred_at=NOW + timedelta(minutes=3),
    )
    changed = first.model_copy(update={"reason": "different durable reason"})
    with pytest.raises(CapabilityAuthorityIdempotencyConflict):
        store.revoke_product_approval(
            changed,
            principal=_admin(),
            operation_id="approval-revoke-operation-1",
            event_id="approval-revoke-event-2",
            occurred_at=NOW + timedelta(minutes=4),
        )


def test_approval_revocation_before_target_is_isolated(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    approval = _approval(_seed(store))
    _approve(store, approval)
    store.revoke_product_approval(
        _approval_revocation(approval),
        principal=_admin(),
        operation_id="approval-revoke-operation-1",
        event_id="approval-revoke-event-1",
        occurred_at=NOW + timedelta(minutes=3),
    )
    store.close()
    events = _read(path)
    events[-2], events[-1] = events[-1], events[-2]
    _write(path, events)
    replayed = _open(path)
    assert (
        replayed.approval_chain_status(_approval_scope(approval))
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


def test_evidence_revocation_makes_prior_approval_ineffective(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    records = _seed(store)
    approval = _approval(records)
    _approve(store, approval)
    evidence_scope = EvidenceApplicabilityScopeV1.from_record(records[0])
    store.revoke_evidence(
        CapabilityEvidenceRevocationV1(
            target_evidence_record_id=records[0].evidence_record_id,
            target_scope=evidence_scope,
            target_scope_digest=evidence_scope.canonical_digest,
            reason="HIL regression",
        ),
        operation_id="evidence-revoke-operation",
        event_id="evidence-revoke-event",
        actor_principal_id=records[0].verifier_principal_id,
        occurred_at=NOW + timedelta(minutes=3),
    )
    projection = store.get_approval_projection(approval.approval_record_id, now=ACTIVE_NOW)
    assert projection is not None
    assert projection.lifecycle_status is ApprovalLifecycleStatus.PREREQUISITE_INVALID


def test_evidence_supersession_makes_pinned_approval_ineffective(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    records = _seed(store)
    approval = _approval(records)
    _approve(store, approval)
    old = records[0]
    successor = _evidence(
        "evidence-successor",
        source=old.source_capability_id,
        canonical=old.canonical_capability_id,
        path=old.integration_path,
        equipment_scope=old.equipment_scope,
        supersedes=old.evidence_record_id,
    )
    store.record_evidence(
        successor,
        operation_id="evidence-successor-operation",
        event_id="evidence-successor-event",
        actor_principal_id=successor.verifier_principal_id,
        occurred_at=NOW + timedelta(minutes=3),
    )
    projection = store.get_approval_projection(approval.approval_record_id, now=ACTIVE_NOW)
    assert projection is not None
    assert projection.lifecycle_status is ApprovalLifecycleStatus.PREREQUISITE_INVALID


def test_evidence_expiry_makes_pinned_approval_ineffective(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    records = _seed(store, valid_until=NOW + timedelta(days=2))
    approval = _approval(records, valid_until=NOW + timedelta(days=10))
    _approve(store, approval)
    projection = store.get_approval_projection(
        approval.approval_record_id, now=NOW + timedelta(days=3)
    )
    assert projection is not None
    assert projection.lifecycle_status is ApprovalLifecycleStatus.PREREQUISITE_INVALID


def test_valid_approval_replays_identically_after_restart(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    approval = _approval(_seed(store))
    _approve(store, approval)
    before = store.get_approval_projection(approval.approval_record_id, now=ACTIVE_NOW)
    store.close()
    replayed = _open(path)
    assert replayed.get_approval_projection(approval.approval_record_id, now=ACTIVE_NOW) == before


@pytest.mark.parametrize("field", ["supportMatrixDigest", "approverPrincipalId"])
def test_identifiable_approval_payload_corruption_isolates_chain(
    tmp_path: Path, field: str
) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    approval = _approval(_seed(store))
    _approve(store, approval)
    store.close()
    events = _read(path)
    approval_event = events[-1]
    approval_event["payload"]["approval"][field] = (
        _digest("f") if field == "supportMatrixDigest" else "forged-approver"
    )
    if field == "approverPrincipalId":
        raw_record = ProductCapabilityApprovalRecordV1.model_validate(
            approval_event["payload"]["approval"]
        )
        approval_event["payload"]["approvalRecordDigest"] = (
            product_capability_approval_record_digest(raw_record)
        )
    _redigest(approval_event)
    _write(path, events)
    replayed = _open(path)
    assert replayed.get_approval_record(approval.approval_record_id) is None
    assert replayed.isolated_chain_count >= 1


@pytest.mark.parametrize("field", ["mappingVersion", "gateVersion"])
def test_unsupported_approval_version_isolated(tmp_path: Path, field: str) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    approval = _approval(_seed(store))
    _approve(store, approval)
    store.close()
    events = _read(path)
    approval_event = events[-1]
    approval_event["payload"]["approval"][field] = f"future-{field}-v9"
    raw_record = ProductCapabilityApprovalRecordV1.model_validate(
        approval_event["payload"]["approval"]
    )
    approval_event["payload"]["approvalRecordDigest"] = product_capability_approval_record_digest(
        raw_record
    )
    _redigest(approval_event)
    _write(path, events)
    replayed = _open(path)
    altered_scope = ApprovalApplicabilityScopeV1.from_record(raw_record)
    assert (
        replayed.approval_chain_status(altered_scope)
        is CapabilityAuthorityChainStatus.BLOCKED_UNSUPPORTED_VERSION
    )


def test_unattributable_approval_corruption_refuses_store_start(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    approval = _approval(_seed(store))
    _approve(store, approval)
    store.close()
    events = _read(path)
    del events[-1]["payload"]["approval"]["canonicalCapabilityId"]
    _redigest(events[-1])
    _write(path, events)
    with pytest.raises(CapabilityAuthorityRecoveryError):
        _open(path)


def test_route_query_is_exact_across_scope_dimensions(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    records = _seed(store)
    approval = _approval(records)
    _approve(store, approval)
    entry = approval.support_matrix.entries[0]
    exact = store.effective_approvals_for_route(
        canonical_capability_id=approval.canonical_capability_id,
        integration_path=entry.integration_path,
        equipment_scope_digest=entry.equipment_scope_digest,
        product_build_digest=approval.product_build_digest,
        policy_scope_id=approval.policy_scope_id,
        mapping_version=approval.mapping_version,
        gate_version=approval.gate_version,
        now=ACTIVE_NOW,
    )
    wrong_build = store.effective_approvals_for_route(
        canonical_capability_id=approval.canonical_capability_id,
        integration_path=entry.integration_path,
        equipment_scope_digest=entry.equipment_scope_digest,
        product_build_digest=_digest("c"),
        policy_scope_id=approval.policy_scope_id,
        mapping_version=approval.mapping_version,
        gate_version=approval.gate_version,
        now=ACTIVE_NOW,
    )
    assert len(exact) == 1
    assert wrong_build == ()


def test_legacy_verified_creates_no_approval_and_no_activation_surface(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    legacy = parse_legacy_core_capability_state("VERIFIED")
    assert legacy.semantic is LegacyCapabilitySemantic.LEGACY_UNATTESTED
    assert not legacy.has_approval_authority
    assert store.approval_count == 0
    assert not hasattr(store, "activate_capability")
    assert not hasattr(store, "operationally_usable")
