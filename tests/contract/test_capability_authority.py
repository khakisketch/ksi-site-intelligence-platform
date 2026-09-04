"""CAP-2 durable route-evidence authority contract and golden replay fixtures."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ksi_core.capability.authority_store import (
    CAPABILITY_AUTHORITY_JOURNAL_NAME,
    CapabilityAuthorityChainStatus,
    CapabilityAuthorityConflict,
    CapabilityAuthorityIdempotencyConflict,
    CapabilityAuthorityRecoveryError,
    CapabilityAuthorityStore,
    CapabilityAuthorityValidationError,
    CapabilityEvidenceMutationResult,
    CapabilityEvidenceRecordV1,
    CapabilityEvidenceRevocationV1,
    CapabilityEvidenceType,
    EquipmentComponentV1,
    EquipmentRole,
    EquipmentScopeV1,
    EvidenceApplicabilityScopeV1,
    EvidenceLifecycleStatus,
)
from ksi_core.durable_journal import DurableJournal, JournalRecoveryError
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_domain.capability_contract import (
    CanonicalTransportCapability,
    CapabilityIntegrationPath,
    CapabilityMappingVersion,
    LegacyCapabilitySemantic,
    RouteEvidenceQualification,
    SourceCapabilityId,
    parse_legacy_core_capability_state,
)

NOW = datetime(2026, 9, 2, 3, 0, tzinfo=UTC)

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


def _scope(
    path: CapabilityIntegrationPath = CapabilityIntegrationPath.MANIFOLD_DIRECT,
    *,
    firmware: str = "firmware-1.0",
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


def _record(
    record_id: str = "evidence-1",
    *,
    canonical: CanonicalTransportCapability = CanonicalTransportCapability.EDGE_DOWNLINK,
    source: SourceCapabilityId = SourceCapabilityId.SPIKE_DJI_07,
    path: CapabilityIntegrationPath = CapabilityIntegrationPath.MANIFOLD_DIRECT,
    firmware: str = "firmware-1.0",
    build_digest: str = _digest("b"),
    evidence_digest: str = _digest("e"),
    mapping_version: str = CapabilityMappingVersion.V1.value,
    result: RouteEvidenceQualification = RouteEvidenceQualification.QUALIFIED,
    valid_until: datetime = NOW + timedelta(days=30),
    supersedes: str | None = None,
) -> CapabilityEvidenceRecordV1:
    equipment_scope = _scope(path, firmware=firmware)
    return CapabilityEvidenceRecordV1(
        evidence_record_id=record_id,
        canonical_capability_id=canonical,
        source_capability_id=source,
        mapping_version=mapping_version,
        integration_path=path,
        equipment_scope=equipment_scope,
        equipment_scope_digest=equipment_scope.canonical_digest,
        test_build_digest=build_digest,
        policy_scope_id="ksi-capability-policy-v1",
        evidence_type=CapabilityEvidenceType.HIL,
        evidence_artifact_ref=f"evidence://capability/{record_id}",
        evidence_digest=evidence_digest,
        procedure_ref="procedure://dji-route-v1",
        procedure_digest=_digest("d"),
        performer_principal_id="field-operator-1",
        verifier_principal_id="capability-verifier-1",
        performed_at=NOW - timedelta(hours=1),
        verified_at=NOW,
        verification_result=result,
        valid_until=valid_until,
        supersedes_evidence_record_id=supersedes,
    )


def _applicability(record: CapabilityEvidenceRecordV1) -> EvidenceApplicabilityScopeV1:
    return EvidenceApplicabilityScopeV1.from_record(record)


def _revocation(
    record: CapabilityEvidenceRecordV1, *, reason: str = "procedure regression"
) -> CapabilityEvidenceRevocationV1:
    scope = _applicability(record)
    return CapabilityEvidenceRevocationV1(
        target_evidence_record_id=record.evidence_record_id,
        target_scope=scope,
        target_scope_digest=scope.canonical_digest,
        reason=reason,
    )


def _open(path: Path) -> CapabilityAuthorityStore:
    return CapabilityAuthorityStore(DurableJournal(path))


def _append(
    store: CapabilityAuthorityStore,
    record: CapabilityEvidenceRecordV1,
    *,
    operation_id: str = "operation-1",
    event_id: str = "event-1",
    occurred_at: datetime = NOW + timedelta(minutes=1),
) -> CapabilityEvidenceMutationResult:
    return store.record_evidence(
        record,
        operation_id=operation_id,
        event_id=event_id,
        actor_principal_id=record.verifier_principal_id,
        occurred_at=occurred_at,
    )


def _read_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]


def _write_events(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        encoding="ascii",
    )


def _redigest(event: dict[str, Any]) -> None:
    event["payloadSha256"] = _event_digest(event)


def test_first_append_has_exact_envelope_and_durable_evidence(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    record = _record()

    result = _append(store, record)

    assert result.record == record
    assert result.operation_id == "operation-1"
    assert store.record_count == 1
    raw = _read_events(path)[0]
    assert set(raw) == {
        "schemaVersion",
        "eventId",
        "operationId",
        "kind",
        "occurredAt",
        "actorPrincipalId",
        "actorPrincipalKind",
        "payload",
        "payloadSha256",
    }
    assert raw["schemaVersion"] == "1.0"
    assert raw["kind"] == "capability-evidence-recorded"
    assert raw["payload"]["evidence"]["mappingVersion"] == CapabilityMappingVersion.V1
    assert "gateVersion" not in raw["payload"]["evidence"]
    assert raw["payloadSha256"] == _event_digest(raw)


def test_exact_operation_retry_is_idempotent_even_with_new_event_metadata(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    record = _record()
    first = _append(store, record)

    retry = _append(
        store,
        record,
        event_id="event-response-retry",
        occurred_at=NOW + timedelta(hours=2),
    )

    assert retry == first
    assert len(_read_events(path)) == 1
    assert store.operation_count == 1


def test_same_operation_different_payload_is_idempotency_conflict(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    _append(store, _record())

    with pytest.raises(CapabilityAuthorityIdempotencyConflict):
        _append(store, _record(evidence_digest=_digest("f")), event_id="event-2")


def test_response_loss_restart_exact_retry_returns_durable_result(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    first_store = _open(path)
    first = _append(first_store, _record())
    first_store.close()

    replayed = _open(path)
    retry = _append(replayed, _record(), event_id="new-event-after-restart")

    assert retry == first
    assert len(_read_events(path)) == 1


def test_response_loss_restart_conflicting_retry_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    first_store = _open(path)
    _append(first_store, _record())
    first_store.close()

    replayed = _open(path)
    with pytest.raises(CapabilityAuthorityIdempotencyConflict):
        _append(
            replayed,
            _record(evidence_digest=_digest("f")),
            event_id="new-event-after-restart",
        )


@pytest.mark.parametrize(
    "source",
    [
        SourceCapabilityId.SPIKE_DJI_01,
        SourceCapabilityId.SPIKE_DJI_03,
        SourceCapabilityId.SPIKE_DJI_05,
        SourceCapabilityId.SPIKE_DJI_09,
    ],
)
def test_unmapped_sources_cannot_create_route_qualification(
    tmp_path: Path, source: SourceCapabilityId
) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    with pytest.raises(CapabilityAuthorityValidationError, match="not represented"):
        _append(store, _record(source=source))


def test_unknown_mapping_version_rejected_live(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    with pytest.raises(CapabilityAuthorityValidationError, match="unsupported"):
        _append(store, _record(mapping_version="future-map-v9"))


def test_independent_verifier_and_operator_actor_are_mandatory(tmp_path: Path) -> None:
    raw = _record().model_dump(mode="json", by_alias=True)
    raw["verifierPrincipalId"] = raw["performerPrincipalId"]
    with pytest.raises(ValueError, match="must be independent"):
        CapabilityEvidenceRecordV1.model_validate(raw)

    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    with pytest.raises(CapabilityAuthorityValidationError, match="must equal verifier"):
        store.record_evidence(
            _record(),
            operation_id="operation-1",
            event_id="event-1",
            actor_principal_id="another-operator",
            occurred_at=NOW + timedelta(minutes=1),
        )


def test_vendor_declaration_cannot_become_route_qualification() -> None:
    raw = _record().model_dump(mode="json", by_alias=True)
    raw["evidenceType"] = CapabilityEvidenceType.VENDOR_DECLARATION.value
    with pytest.raises(ValueError, match="no RouteEvidenceQualification authority"):
        CapabilityEvidenceRecordV1.model_validate(raw)


def test_wrong_equipment_roles_rejected_live(tmp_path: Path) -> None:
    record = _record()
    wrong = record.model_copy(
        update={
            "equipment_scope": _scope(CapabilityIntegrationPath.DJI_CLOUD),
            "equipment_scope_digest": _scope(CapabilityIntegrationPath.DJI_CLOUD).canonical_digest,
        }
    )
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)

    with pytest.raises(CapabilityAuthorityValidationError, match="equipmentScope roles"):
        _append(store, wrong)


def test_exact_source_path_scope_does_not_substitute_across_paths(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    direct = _record("direct", path=CapabilityIntegrationPath.MANIFOLD_DIRECT)
    msdk = _record("msdk", path=CapabilityIntegrationPath.MSDK_FIELD)
    _append(store, direct, operation_id="op-direct", event_id="event-direct")
    _append(store, msdk, operation_id="op-msdk", event_id="event-msdk")

    assert [
        projection.record.evidence_record_id
        for projection in store.effective_qualifications(_applicability(direct), now=NOW)
    ] == ["direct"]
    assert [
        projection.record.evidence_record_id
        for projection in store.effective_qualifications(_applicability(msdk), now=NOW)
    ] == ["msdk"]


def test_equipment_and_build_scopes_remain_distinct(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    base = _record("base")
    firmware = _record("firmware", firmware="firmware-2.0")
    build = _record("build", build_digest=_digest("c"))
    for index, record in enumerate((base, firmware, build), start=1):
        _append(store, record, operation_id=f"op-{index}", event_id=f"event-{index}")

    assert all(
        len(store.effective_qualifications(_applicability(record), now=NOW)) == 1
        for record in (base, firmware, build)
    )
    assert len({_applicability(record).canonical_digest for record in (base, firmware, build)}) == 3


def test_valid_supersession_preserves_history_and_changes_effective_record(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    first = _record("evidence-1")
    second = _record("evidence-2", evidence_digest=_digest("f"), supersedes="evidence-1")
    _append(store, first, operation_id="op-1", event_id="event-1")
    _append(store, second, operation_id="op-2", event_id="event-2")

    first_projection = store.get_projection("evidence-1", now=NOW)
    second_projection = store.get_projection("evidence-2", now=NOW)
    assert first_projection is not None
    assert first_projection.lifecycle_status is EvidenceLifecycleStatus.SUPERSEDED
    assert first_projection.superseded_by_record_id == "evidence-2"
    assert second_projection is not None
    assert second_projection.lifecycle_status is EvidenceLifecycleStatus.CURRENT
    assert store.get_record("evidence-1") == first


def test_unresolved_negative_evidence_blocks_positive_qualification(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    qualified = _record("qualified")
    blocked = _record(
        "blocked",
        result=RouteEvidenceQualification.BLOCKED,
        evidence_digest=_digest("f"),
    )
    _append(store, qualified, operation_id="op-qualified", event_id="event-qualified")
    _append(store, blocked, operation_id="op-blocked", event_id="event-blocked")

    assert store.effective_qualifications(_applicability(qualified), now=NOW) == ()


def test_revoked_blocker_requires_explicit_supersession_before_requalification(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    original = _record("original")
    _append(store, original, operation_id="op-original", event_id="event-original")
    store.revoke_evidence(
        _revocation(original),
        operation_id="op-revoke",
        event_id="event-revoke",
        actor_principal_id="capability-verifier-2",
        occurred_at=NOW + timedelta(hours=1),
    )
    independent = _record("independent", evidence_digest=_digest("f"))
    _append(
        store,
        independent,
        operation_id="op-independent",
        event_id="event-independent",
        occurred_at=NOW + timedelta(hours=2),
    )
    assert store.effective_qualifications(_applicability(original), now=NOW) == ()

    successor = _record(
        "successor",
        evidence_digest=_digest("a"),
        supersedes="original",
    )
    _append(
        store,
        successor,
        operation_id="op-successor",
        event_id="event-successor",
        occurred_at=NOW + timedelta(hours=3),
    )
    effective_ids = {
        item.record.evidence_record_id
        for item in store.effective_qualifications(_applicability(original), now=NOW)
    }
    assert effective_ids == {"independent", "successor"}
    original_projection = store.get_projection("original", now=NOW)
    assert original_projection is not None
    assert original_projection.lifecycle_status is EvidenceLifecycleStatus.SUPERSEDED
    assert original_projection.revoked_by_event_id == "event-revoke"


def test_new_operation_cannot_reuse_record_or_event_identity(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    first = _record()
    _append(store, first)

    with pytest.raises(CapabilityAuthorityConflict, match="evidenceRecordId"):
        _append(store, first, operation_id="operation-2", event_id="event-2")
    with pytest.raises(CapabilityAuthorityConflict, match="eventId"):
        _append(
            store,
            _record("evidence-2"),
            operation_id="operation-3",
            event_id="event-1",
        )


def test_unrelated_scope_supersession_is_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    _append(store, _record("evidence-1"), operation_id="op-1", event_id="event-1")
    unrelated = _record(
        "evidence-2",
        path=CapabilityIntegrationPath.MSDK_FIELD,
        supersedes="evidence-1",
    )

    with pytest.raises(CapabilityAuthorityConflict, match="exact same"):
        _append(store, unrelated, operation_id="op-2", event_id="event-2")


def test_revocation_is_append_only_historical_but_ineffective(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    record = _record()
    _append(store, record)

    result = store.revoke_evidence(
        _revocation(record),
        operation_id="revoke-1",
        event_id="revoke-event-1",
        actor_principal_id="capability-verifier-2",
        occurred_at=NOW + timedelta(hours=1),
    )

    projection = store.get_projection(record.evidence_record_id, now=NOW)
    assert result.record == record
    assert projection is not None
    assert projection.lifecycle_status is EvidenceLifecycleStatus.REVOKED
    assert not projection.is_currently_effective_qualification
    assert store.get_record(record.evidence_record_id) == record
    assert len(_read_events(path)) == 2


def test_revocation_missing_target_rejected_live(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    record = _record()
    with pytest.raises(CapabilityAuthorityConflict, match="does not exist"):
        store.revoke_evidence(
            _revocation(record),
            operation_id="revoke-1",
            event_id="revoke-event-1",
            actor_principal_id="capability-verifier-2",
            occurred_at=NOW + timedelta(hours=1),
        )


def test_revocation_wrong_scope_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    record = _record()
    _append(store, record)
    wrong_record = _record("other", build_digest=_digest("c"))
    wrong_scope = _applicability(wrong_record)
    revocation = CapabilityEvidenceRevocationV1(
        target_evidence_record_id=record.evidence_record_id,
        target_scope=wrong_scope,
        target_scope_digest=wrong_scope.canonical_digest,
        reason="wrong scope test",
    )

    with pytest.raises(CapabilityAuthorityConflict, match="not exact"):
        store.revoke_evidence(
            revocation,
            operation_id="revoke-1",
            event_id="revoke-event-1",
            actor_principal_id="capability-verifier-2",
            occurred_at=NOW + timedelta(hours=1),
        )


def test_revocation_exact_retry_is_idempotent_and_changed_payload_conflicts(
    tmp_path: Path,
) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    record = _record()
    _append(store, record)
    first = store.revoke_evidence(
        _revocation(record),
        operation_id="revoke-1",
        event_id="revoke-event-1",
        actor_principal_id="capability-verifier-2",
        occurred_at=NOW + timedelta(hours=1),
    )
    retry = store.revoke_evidence(
        _revocation(record),
        operation_id="revoke-1",
        event_id="revoke-event-response-retry",
        actor_principal_id="capability-verifier-2",
        occurred_at=NOW + timedelta(hours=2),
    )
    assert retry == first
    assert len(_read_events(path)) == 2

    with pytest.raises(CapabilityAuthorityIdempotencyConflict):
        store.revoke_evidence(
            _revocation(record, reason="changed reason"),
            operation_id="revoke-1",
            event_id="revoke-event-conflict",
            actor_principal_id="capability-verifier-2",
            occurred_at=NOW + timedelta(hours=2),
        )


def test_revocation_response_loss_restart_retry_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    record = _record()
    _append(store, record)
    first = store.revoke_evidence(
        _revocation(record),
        operation_id="revoke-1",
        event_id="revoke-event-1",
        actor_principal_id="capability-verifier-2",
        occurred_at=NOW + timedelta(hours=1),
    )
    store.close()

    replayed = _open(path)
    retry = replayed.revoke_evidence(
        _revocation(record),
        operation_id="revoke-1",
        event_id="revoke-event-after-restart",
        actor_principal_id="capability-verifier-2",
        occurred_at=NOW + timedelta(hours=2),
    )
    assert retry == first
    assert len(_read_events(path)) == 2


def test_expired_evidence_remains_historical_but_is_not_effective(tmp_path: Path) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)
    record = _record(valid_until=NOW + timedelta(minutes=1))
    _append(store, record)

    current = store.get_projection(record.evidence_record_id, now=NOW)
    expired = store.get_projection(record.evidence_record_id, now=NOW + timedelta(minutes=2))
    assert current is not None and current.lifecycle_status is EvidenceLifecycleStatus.CURRENT
    assert expired is not None and expired.lifecycle_status is EvidenceLifecycleStatus.EXPIRED
    assert store.get_record(record.evidence_record_id) == record


def test_multiple_independent_records_replay_deterministically(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    first = _record("direct")
    second = _record("msdk", path=CapabilityIntegrationPath.MSDK_FIELD)
    _append(store, first, operation_id="op-1", event_id="event-1")
    _append(store, second, operation_id="op-2", event_id="event-2")
    before = (
        store.get_projection("direct", now=NOW),
        store.get_projection("msdk", now=NOW),
    )
    bytes_before = path.read_bytes()
    store.close()

    replayed = _open(path)
    after = (
        replayed.get_projection("direct", now=NOW),
        replayed.get_projection("msdk", now=NOW),
    )
    assert after == before
    assert path.read_bytes() == bytes_before


def test_revocation_before_target_isolated_on_replay(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    record = _record()
    _append(store, record)
    store.revoke_evidence(
        _revocation(record),
        operation_id="revoke-1",
        event_id="revoke-event-1",
        actor_principal_id="capability-verifier-2",
        occurred_at=NOW + timedelta(hours=1),
    )
    store.close()
    events = _read_events(path)
    _write_events(path, [events[1], events[0]])

    replayed = _open(path)
    assert (
        replayed.chain_status(_applicability(record))
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )
    assert replayed.effective_qualifications(_applicability(record), now=NOW) == ()


def test_supersession_before_target_isolated_on_replay(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    first = _record("evidence-1")
    second = _record("evidence-2", supersedes="evidence-1")
    _append(store, first, operation_id="op-1", event_id="event-1")
    _append(store, second, operation_id="op-2", event_id="event-2")
    store.close()
    events = _read_events(path)
    _write_events(path, [events[1], events[0]])

    replayed = _open(path)
    assert (
        replayed.chain_status(_applicability(first))
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


def test_unsupported_mapping_version_isolates_only_its_chain(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    good = _record("good", path=CapabilityIntegrationPath.MSDK_FIELD)
    bad = _record("bad")
    _append(store, good, operation_id="op-good", event_id="event-good")
    _append(store, bad, operation_id="op-bad", event_id="event-bad")
    store.close()
    events = _read_events(path)
    events[1]["payload"]["evidence"]["mappingVersion"] = "future-map-v9"
    _redigest(events[1])
    _write_events(path, events)

    replayed = _open(path)
    future_scope = _applicability(bad).model_copy(update={"mapping_version": "future-map-v9"})
    assert (
        replayed.chain_status(future_scope)
        is CapabilityAuthorityChainStatus.BLOCKED_UNSUPPORTED_VERSION
    )
    assert len(replayed.effective_qualifications(_applicability(good), now=NOW)) == 1


def test_source_path_mismatch_isolates_attributable_chain(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    record = _record()
    _append(store, record)
    store.close()
    events = _read_events(path)
    events[0]["payload"]["evidence"]["sourceCapabilityId"] = "SPIKE-DJI-01"
    _redigest(events[0])
    _write_events(path, events)

    replayed = _open(path)
    bad_scope = _applicability(record).model_copy(
        update={"source_capability_id": SourceCapabilityId.SPIKE_DJI_01}
    )
    assert replayed.chain_status(bad_scope) is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("canonicalCapabilityId", "FUTURE_CAPABILITY"),
        ("sourceCapabilityId", "SPIKE-DJI-99"),
        ("integrationPath", "FUTURE_PATH"),
    ],
)
def test_unknown_capability_source_or_path_isolates_attributable_chain(
    tmp_path: Path, field: str, value: str
) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    _append(store, _record())
    store.close()
    events = _read_events(path)
    events[0]["payload"]["evidence"][field] = value
    _redigest(events[0])
    _write_events(path, events)

    replayed = _open(path)
    assert replayed.record_count == 0
    assert replayed.isolated_chain_count == 1


def test_payload_digest_corruption_isolates_attributable_chain(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    record = _record()
    _append(store, record)
    store.close()
    events = _read_events(path)
    events[0]["payload"]["evidence"]["procedureRef"] = "procedure://tampered"
    _write_events(path, events)

    replayed = _open(path)
    assert (
        replayed.chain_status(_applicability(record))
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


def test_malformed_provenance_isolates_attributable_chain(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    record = _record()
    _append(store, record)
    store.close()
    events = _read_events(path)
    del events[0]["payload"]["evidence"]["performerPrincipalId"]
    _redigest(events[0])
    _write_events(path, events)

    replayed = _open(path)
    assert (
        replayed.chain_status(_applicability(record))
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


def test_unsupported_event_schema_isolates_attributable_chain(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    record = _record()
    _append(store, record)
    store.close()
    events = _read_events(path)
    events[0]["schemaVersion"] = "2.0"
    _redigest(events[0])
    _write_events(path, events)

    replayed = _open(path)
    assert (
        replayed.chain_status(_applicability(record))
        is CapabilityAuthorityChainStatus.BLOCKED_UNSUPPORTED_VERSION
    )


def test_gate_version_is_forbidden_on_cap2_evidence_and_blocks_chain(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    record = _record()
    _append(store, record)
    store.close()
    events = _read_events(path)
    events[0]["payload"]["evidence"]["gateVersion"] = "future-gate-v9"
    _redigest(events[0])
    _write_events(path, events)

    replayed = _open(path)
    assert (
        replayed.chain_status(_applicability(record))
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


@pytest.mark.parametrize(
    "future_kind",
    ["capability-runtime-route-observed"],
)
def test_unknown_future_authority_kind_fails_closed_without_implementing_it(
    tmp_path: Path, future_kind: str
) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    record = _record()
    _append(store, record)
    store.close()
    events = _read_events(path)
    events[0]["kind"] = future_kind
    _redigest(events[0])
    _write_events(path, events)

    replayed = _open(path)
    assert (
        replayed.chain_status(_applicability(record))
        is CapabilityAuthorityChainStatus.BLOCKED_UNSUPPORTED_VERSION
    )


def test_duplicate_event_id_conflict_isolates_both_affected_chains(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    first = _record("direct")
    second = _record("msdk", path=CapabilityIntegrationPath.MSDK_FIELD)
    _append(store, first, operation_id="op-1", event_id="event-1")
    _append(store, second, operation_id="op-2", event_id="event-2")
    store.close()
    events = _read_events(path)
    events[1]["eventId"] = "event-1"
    _redigest(events[1])
    _write_events(path, events)

    replayed = _open(path)
    assert (
        replayed.chain_status(_applicability(first))
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )
    assert (
        replayed.chain_status(_applicability(second))
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


def test_same_operation_different_payload_in_journal_isolates_both_chains(
    tmp_path: Path,
) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    first = _record("direct")
    second = _record("msdk", path=CapabilityIntegrationPath.MSDK_FIELD)
    _append(store, first, operation_id="op-1", event_id="event-1")
    _append(store, second, operation_id="op-2", event_id="event-2")
    store.close()
    events = _read_events(path)
    events[1]["operationId"] = "op-1"
    _redigest(events[1])
    _write_events(path, events)

    replayed = _open(path)
    assert (
        replayed.chain_status(_applicability(first))
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )
    assert (
        replayed.chain_status(_applicability(second))
        is CapabilityAuthorityChainStatus.BLOCKED_CORRUPT
    )


def test_unattributable_top_level_corruption_seals_subsystem(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    _write_events(path, [{"kind": "capability-evidence-recorded"}])
    journal = DurableJournal(path)

    with pytest.raises(CapabilityAuthorityRecoveryError, match="malformed top-level"):
        CapabilityAuthorityStore(journal)
    assert journal.sealed_reason == "closed"


def test_capability_authority_journal_enforces_single_writer(tmp_path: Path) -> None:
    path = tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME
    store = _open(path)
    try:
        with pytest.raises(JournalRecoveryError, match="single writer|단일 writer"):
            DurableJournal(path)
    finally:
        store.close()


def test_legacy_verified_creates_no_evidence_or_authority(tmp_path: Path) -> None:
    legacy = parse_legacy_core_capability_state("VERIFIED")
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)

    assert legacy.semantic is LegacyCapabilitySemantic.LEGACY_UNATTESTED
    assert not legacy.has_evidence_authority
    assert store.record_count == 0
    assert store.operation_count == 0


def test_cap2_store_exposes_no_approval_activation_or_runtime_mutation_methods(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path / CAPABILITY_AUTHORITY_JOURNAL_NAME)

    assert not hasattr(store, "approve_capability")
    assert not hasattr(store, "activate_capability")
    assert not hasattr(store, "promote_capability")
    assert not hasattr(store, "issue_mission")
