"""Core external-validation policy registry contract (synthetic local authority only)."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyConflictError,
    ExternalValidationPolicyRegistry,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
    PolicyReceiptStatus,
    PolicySelectionStatus,
    authorized_policy_body_digest,
)
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    PolicyStatus,
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)

NOW = datetime(2026, 9, 7, tzinfo=UTC)


def _digest(marker: str) -> str:
    return f"sha256:{marker * 64}"


def _subject(*, marker: str = "a") -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="organization-1",
        site_id="site-1",
        work_order_id="work-order-1",
        submission_id="submission-1",
        revision=1,
        submission_digest=_digest(marker),
        manifest_digest=_digest("b" if marker == "a" else "c"),
    )


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=1_024,
        max_streamed_bytes=1_024,
        max_tiff_directories=4,
        max_tiff_entries=32,
        max_pixels=1_000,
        max_bands=4,
        max_blocks=64,
        max_decompressed_bytes=8_192,
        max_sample_bytes=8_192,
        max_geometry_vertices=64,
        max_cpu_seconds=2.0,
        max_memory_bytes=16_384,
        max_workspace_bytes=16_384,
        max_output_bytes=16_384,
        max_tenant_concurrency=1,
        max_queue_depth=4,
        max_deadline_seconds=3.0,
        lease_duration_seconds=4.0,
        max_retry_attempts=2,
    ).sealed()


def _policy_template(
    *,
    authority_digest: str = _digest("f"),
    policy_id: str = "policy-1",
    version: int = 1,
    synthetic_test_only: bool = True,
    parser_build_digest: str = _digest("d"),
) -> ExternalValidationPolicyV1:
    envelope = _envelope()
    return ExternalValidationPolicyV1(
        policy_id=policy_id,
        version=version,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=parser_build_digest,
        grammar_digest=_digest("e"),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=authority_digest,
        inspection_rule_ids=("synthetic-test-rule",),
        evidence_rule_ids=("synthetic-test-rule",),
        compatibility_mapping_digests=(),
        synthetic_test_only=synthetic_test_only,
    ).sealed()


def _authority(
    policy: ExternalValidationPolicyV1,
    *,
    subjects: tuple[SealedExternalSubjectV1, ...] = (_subject(),),
    actor_ids: tuple[str, ...] = ("authority",),
    uses: tuple[str, ...] = ("INSPECTION", "DISPLAY"),
    active_from: datetime = NOW - timedelta(minutes=1),
    active_until: datetime = NOW + timedelta(minutes=1),
    synthetic_test_only: bool = True,
) -> PolicyAuthorityRecord:
    return PolicyAuthorityRecord(
        policy_id=policy.policy_id,
        policy_version=policy.version,
        authorized_policy_body_digest=authorized_policy_body_digest(policy),
        permitted_subjects=subjects,
        permitted_uses=uses,
        authorized_actor_ids=actor_ids,
        active_from=active_from,
        active_until=active_until,
        synthetic_test_only=synthetic_test_only,
    ).sealed()


def _bound_policy(
    *,
    policy_id: str = "policy-1",
    version: int = 1,
    subjects: tuple[SealedExternalSubjectV1, ...] = (_subject(),),
    actor_ids: tuple[str, ...] = ("authority",),
    uses: tuple[str, ...] = ("INSPECTION", "DISPLAY"),
    active_from: datetime = NOW - timedelta(minutes=1),
    active_until: datetime = NOW + timedelta(minutes=1),
    policy_synthetic_test_only: bool = True,
    authority_synthetic_test_only: bool | None = None,
    parser_build_digest: str = _digest("d"),
) -> tuple[ExternalValidationPolicyV1, PolicyAuthorityRecord]:
    template = _policy_template(
        policy_id=policy_id,
        version=version,
        synthetic_test_only=policy_synthetic_test_only,
        parser_build_digest=parser_build_digest,
    )
    authority = _authority(
        template,
        subjects=subjects,
        actor_ids=actor_ids,
        uses=uses,
        active_from=active_from,
        active_until=active_until,
        synthetic_test_only=(
            policy_synthetic_test_only
            if authority_synthetic_test_only is None
            else authority_synthetic_test_only
        ),
    )
    assert authority.digest is not None
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    assert authority.authorized_policy_body_digest == authorized_policy_body_digest(policy)
    return policy, authority


class FakePolicyAuthorityPort(PolicyAuthorityPort):
    """Synthetic test double for the explicit Core trust boundary."""

    def __init__(self, *records: PolicyAuthorityRecord) -> None:
        self._records: dict[str, PolicyAuthorityRecord] = {}
        for record in records:
            assert record.digest is not None
            self._records[record.digest] = record
        self.resolutions: list[tuple[str, datetime]] = []
        self._coordinator: ExternalAuthorityCurrentnessCoordinator | None = None

    def bind(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> FakePolicyAuthorityPort:
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        assert self._coordinator is not None
        return self._coordinator

    def resolve(self, authority_record_digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        self.resolutions.append((authority_record_digest, now))
        return self._records.get(authority_record_digest)

    def resolve_historical(
        self, authority_record_digest: str, at: datetime
    ) -> PolicyAuthorityRecord | None:
        record = self._records.get(authority_record_digest)
        return record if record is not None and record.is_active_at(at) else None

    def is_current(self, authority: PolicyAuthorityRecord, now: datetime) -> bool:
        return (
            authority.digest is not None
            and self._records.get(authority.digest) == authority
            and authority.is_active_at(now)
        )

    def replace_resolved(self, digest: str, record: PolicyAuthorityRecord) -> None:
        self._records[digest] = record


def _registry(
    tmp_path: Path, authority: FakePolicyAuthorityPort | None = None
) -> ExternalValidationPolicyRegistry:
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    return ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "external-validation-policy.jsonl"),
        authority_port=authority,
        authority_currentness_port=authority.bind(coordinator) if authority is not None else None,
        clock=lambda: NOW,
        coordinator=coordinator,
    )


def _registry_for_journal(
    journal: DurableJournal,
    authority: FakePolicyAuthorityPort,
    *,
    clock: Callable[[], datetime] = lambda: NOW,
) -> ExternalValidationPolicyRegistry:
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    return ExternalValidationPolicyRegistry(
        journal,
        authority_port=authority,
        authority_currentness_port=authority.bind(coordinator),
        clock=clock,
        coordinator=coordinator,
    )


def _event_digest(event: dict[str, object]) -> str:
    body = {key: value for key, value in event.items() if key != "eventDigest"}
    return "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def test_admission_rechecks_currentness_after_a_stale_preflight_before_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A policy record withdrawn after external resolution cannot reach the journal."""
    policy, authority = _bound_policy()
    assert authority.digest is not None
    port = FakePolicyAuthorityPort(authority)
    registry = _registry(tmp_path, port)
    entered = threading.Event()
    release = threading.Event()
    original_resolve = port.resolve

    def blocked_resolve(digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        resolved = original_resolve(digest, now)
        entered.set()
        assert release.wait(timeout=1)
        return resolved

    monkeypatch.setattr(port, "resolve", blocked_resolve)
    receipts = []
    admission = threading.Thread(
        target=lambda: receipts.append(registry.admit(policy, actor="authority", now=NOW))
    )
    admission.start()
    assert entered.wait(timeout=1)
    with registry.coordinator.mutation():
        port._records.pop(authority.digest)  # noqa: SLF001 - controlled external withdrawal.
    release.set()
    admission.join(timeout=1)

    assert not admission.is_alive()
    assert receipts[0].status is PolicyReceiptStatus.POLICY_AUTHORITY_UNRESOLVED
    assert list(registry._journal.replay()) == []  # noqa: SLF001 - no stale append.


def test_no_policy_is_visible_pending_not_a_job(tmp_path: Path) -> None:
    """Selecting an implicit active/default policy would fail this pending-state test."""
    selection = _registry(tmp_path).select_for_inspection(_subject())

    assert selection.status is PolicySelectionStatus.INSPECTION_PENDING_POLICY
    assert selection.policy is None
    assert selection.reason == "NO_ACTIVE_POLICY"


def test_local_current_use_permission_keeps_authority_interval_without_external_resolution(
    tmp_path: Path,
) -> None:
    first, second = _subject(marker="a"), _subject(marker="d")
    policy, authority = _bound_policy(
        subjects=(first, second),
        uses=("RELATIVE_VOLUME",),
        active_until=NOW + timedelta(seconds=1),
    )
    port = FakePolicyAuthorityPort(authority)
    registry = _registry(tmp_path, port)
    assert registry.admit(policy, actor="authority", now=NOW).status is PolicyReceiptStatus.ADMITTED
    resolutions_before = tuple(port.resolutions)

    assert registry.locally_current_use_permitted(
        policy.policy_digest or "",
        use="RELATIVE_VOLUME",
        subjects=(first, second),
        at=NOW,
    )
    assert not registry.locally_current_use_permitted(
        policy.policy_digest or "",
        use="RELATIVE_VOLUME",
        subjects=(first, second),
        at=NOW + timedelta(seconds=2),
    )
    assert tuple(port.resolutions) == resolutions_before


def test_admit_requires_resolved_authority_not_a_matching_hash(tmp_path: Path) -> None:
    """Treating an authority digest as proof without its trusted port would fail this test."""
    policy, _ = _bound_policy()
    journal = DurableJournal(tmp_path / "unresolved.jsonl")
    registry = ExternalValidationPolicyRegistry(journal, clock=lambda: NOW)

    receipt = registry.admit(policy, actor="authority", now=NOW)

    assert receipt.status is PolicyReceiptStatus.POLICY_AUTHORITY_UNRESOLVED
    assert journal.replay() == []


def test_admit_event_has_integer_version_and_self_excluding_canonical_digest(
    tmp_path: Path,
) -> None:
    """Changing lifecycle fields without changing eventDigest breaks durable replay integrity."""
    policy, authority = _bound_policy()
    registry = _registry(tmp_path, FakePolicyAuthorityPort(authority))

    registry.admit(policy, actor="authority", now=NOW)
    event = registry._journal.replay()[0]  # noqa: SLF001 - durable event is the public audit record.

    assert event["eventVersion"] == 1
    assert event["eventDigest"] == _event_digest(event)


def test_authority_body_digest_rejects_changed_policy_before_first_admission(
    tmp_path: Path,
) -> None:
    """An authority approval for one parser/rule/envelope body must not admit another body."""
    policy, authority = _bound_policy()
    changed_envelope = (
        _envelope()
        .model_copy(update={"max_input_bytes": 2_048, "resource_envelope_digest": None}, deep=True)
        .sealed()
    )
    changed_policies = (
        policy.model_copy(
            update={"parser_build_digest": _digest("9"), "policy_digest": None}, deep=True
        ).sealed(),
        policy.model_copy(
            update={"inspection_rule_ids": ("different-rule",), "policy_digest": None}, deep=True
        ).sealed(),
        policy.model_copy(
            update={
                "resource_envelope": changed_envelope,
                "resource_envelope_digest": changed_envelope.resource_envelope_digest,
                "policy_digest": None,
            },
            deep=True,
        ).sealed(),
    )
    journal = DurableJournal(tmp_path / "changed-body.jsonl")
    registry = _registry_for_journal(journal, FakePolicyAuthorityPort(authority))

    for changed in changed_policies:
        receipt = registry.admit(changed, actor="authority", now=NOW)
        assert receipt.status is PolicyReceiptStatus.POLICY_AUTHORITY_UNRESOLVED
    assert journal.replay() == []


def test_authority_record_rejects_bool_version_unknown_use_and_relaxed_wire_time() -> None:
    """Accepting Python bool versions, arbitrary uses, or relaxed UTC wire syntax is unsafe."""
    policy, authority = _bound_policy()
    with pytest.raises(ValueError):
        replace(authority, policy_version=True)
    with pytest.raises(ValueError):
        replace(authority, policy_version=cast(int, 1.0))
    with pytest.raises(ValueError):
        _authority(policy, uses=("UNKNOWN_USE",))
    malformed_wire = authority.event_payload()
    malformed_wire["activeFrom"] = "2026-09-06 23:59:00+00:00"
    with pytest.raises(ValueError):
        PolicyAuthorityRecord.from_event_payload(malformed_wire)


def test_admitted_policy_is_selected_only_for_authorized_exact_scope(tmp_path: Path) -> None:
    """Dropping actor, scope, use, or interval checks would fail this authority-bound selection."""
    policy, authority = _bound_policy()
    registry = _registry(tmp_path, FakePolicyAuthorityPort(authority))

    receipt = registry.admit(policy, actor="authority", now=NOW)
    inspection = registry.select_for_inspection(_subject())
    display = registry.select_for_use("DISPLAY", (_subject(),))
    wrong_subject = registry.select_for_inspection(_subject(marker="0"))

    assert receipt.status is PolicyReceiptStatus.ADMITTED
    assert inspection.status is PolicySelectionStatus.ACTIVE
    assert inspection.policy is not None
    assert inspection.policy.policy_digest == receipt.policy_digest
    assert display.status is PolicySelectionStatus.ACTIVE
    assert wrong_subject.status is PolicySelectionStatus.INSPECTION_PENDING_POLICY


def test_selection_rechecks_authority_expiry_after_admission(tmp_path: Path) -> None:
    """Caching admission-time authority beyond its active interval breaks selection."""
    policy, authority = _bound_policy(active_until=NOW + timedelta(seconds=1))
    clock = [NOW]
    registry = _registry_for_journal(
        DurableJournal(tmp_path / "expiry.jsonl"),
        FakePolicyAuthorityPort(authority),
        clock=lambda: clock[0],
    )
    registry.admit(policy, actor="authority", now=NOW)

    clock[0] = NOW + timedelta(seconds=2)

    assert (
        registry.select_for_inspection(_subject()).status
        is PolicySelectionStatus.INSPECTION_PENDING_POLICY
    )


def test_matching_active_policies_are_rejected_as_ambiguous(tmp_path: Path) -> None:
    """Picking a latest policy when two exact authority scopes match would fail this test."""
    first, first_authority = _bound_policy()
    second, second_authority = _bound_policy(policy_id="policy-2")
    registry = _registry(
        tmp_path,
        FakePolicyAuthorityPort(first_authority, second_authority),
    )
    registry.admit(first, actor="authority", now=NOW)
    registry.admit(second, actor="authority", now=NOW)

    selection = registry.select_for_inspection(_subject())

    assert selection.status is PolicySelectionStatus.POLICY_AMBIGUOUS
    assert selection.policy is None
    assert selection.reason == "AMBIGUOUS_POLICY_SELECTION"


def test_synthetic_record_cannot_authorize_non_synthetic_policy(tmp_path: Path) -> None:
    """Letting test-only authority activate a production-shaped policy would fail this boundary."""
    policy, authority = _bound_policy(
        policy_synthetic_test_only=False,
        authority_synthetic_test_only=True,
    )
    registry = _registry(tmp_path, FakePolicyAuthorityPort(authority))

    receipt = registry.admit(policy, actor="authority", now=NOW)

    assert receipt.status is PolicyReceiptStatus.POLICY_AUTHORITY_UNRESOLVED


def test_admission_is_idempotent_but_same_version_different_body_conflicts(tmp_path: Path) -> None:
    """Appending a duplicate or replacing an admitted version breaks immutable policy history."""
    policy, authority = _bound_policy()
    changed, changed_authority = _bound_policy(parser_build_digest=_digest("9"))
    authority_port = FakePolicyAuthorityPort(authority, changed_authority)
    registry = _registry(tmp_path, authority_port)

    first = registry.admit(policy, actor="authority", now=NOW)
    duplicate = registry.admit(policy, actor="authority", now=NOW)

    assert first.status is PolicyReceiptStatus.ADMITTED
    assert duplicate.status is PolicyReceiptStatus.IDEMPOTENT
    with pytest.raises(ExternalValidationPolicyConflictError):
        registry.admit(changed, actor="authority", now=NOW)


def test_concurrent_duplicate_admission_writes_one_durable_event(tmp_path: Path) -> None:
    """Publishing before the registry lock/append would allow duplicate lifecycle events."""
    policy, authority = _bound_policy()
    journal = DurableJournal(tmp_path / "concurrent.jsonl")
    registry = _registry_for_journal(journal, FakePolicyAuthorityPort(authority))

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(
            executor.map(
                lambda _: registry.admit(policy, actor="authority", now=NOW),
                range(2),
            )
        )

    assert {receipt.status for receipt in receipts} == {
        PolicyReceiptStatus.ADMITTED,
        PolicyReceiptStatus.IDEMPOTENT,
    }
    assert len(journal.replay()) == 1


def test_append_failure_does_not_publish_policy_before_durability(tmp_path: Path) -> None:
    """Publishing before a failed journal append would expose an unaudited active policy."""
    policy, authority = _bound_policy()
    journal = DurableJournal(tmp_path / "sealed.jsonl")
    registry = _registry_for_journal(journal, FakePolicyAuthorityPort(authority))
    journal.close()

    with pytest.raises(JournalSealedError):
        registry.admit(policy, actor="authority", now=NOW)

    assert (
        registry.resolve(policy.policy_digest or "").status
        is PolicySelectionStatus.POLICY_NOT_FOUND
    )
    assert (
        registry.select_for_inspection(_subject()).status
        is PolicySelectionStatus.INSPECTION_PENDING_POLICY
    )


def test_revocation_blocks_future_selection_not_history(tmp_path: Path) -> None:
    """Mutating the sealed policy snapshot instead of registry lifecycle would fail this test."""
    policy, authority = _bound_policy()
    registry = _registry(tmp_path, FakePolicyAuthorityPort(authority))
    receipt = registry.admit(policy, actor="authority", now=NOW)

    revoked = registry.revoke(receipt.policy_id, receipt.version, actor="authority", now=NOW)
    assert receipt.policy_digest is not None
    historical = registry.resolve(receipt.policy_digest)
    future = registry.select_for_inspection(_subject())

    assert revoked.status is PolicyReceiptStatus.REVOKED
    assert historical.status is PolicySelectionStatus.REVOKED
    assert historical.policy is not None
    assert historical.policy.status == "ACTIVE"
    assert future.status is PolicySelectionStatus.INSPECTION_PENDING_POLICY


def test_mutation_rejects_bool_policy_version_without_a_journal_event(tmp_path: Path) -> None:
    """Letting True alias policy version 1 would allow an unintended lifecycle transition."""
    policy, authority = _bound_policy()
    journal = DurableJournal(tmp_path / "bool-policy-version.jsonl")
    registry = _registry_for_journal(journal, FakePolicyAuthorityPort(authority))
    registry.admit(policy, actor="authority", now=NOW)

    for malformed_version in (True, 1.0):
        malformed_policy = policy.model_copy(
            update={"version": malformed_version, "policy_digest": None}, deep=True
        )
        with pytest.raises(ValueError):
            registry.admit(malformed_policy, actor="authority", now=NOW)
    with pytest.raises(ValueError):
        registry.revoke(policy.policy_id, True, actor="authority", now=NOW)
    with pytest.raises(ValueError):
        registry.supersede(
            policy.policy_id,
            policy.version,
            policy.policy_id,
            True,
            actor="authority",
            now=NOW,
        )

    assert len(journal.replay()) == 1
    assert registry.resolve(policy.policy_digest or "").status is PolicySelectionStatus.ACTIVE


def test_current_selection_rejects_trusted_record_mismatch(tmp_path: Path) -> None:
    """A port result that differs from the admitted immutable authority snapshot must not select."""
    policy, authority = _bound_policy()
    replacement = _authority(policy, subjects=(_subject(marker="0"),))
    assert authority.digest is not None
    object.__setattr__(replacement, "digest", authority.digest)
    port = FakePolicyAuthorityPort(authority)
    registry = _registry(tmp_path, port)
    registry.admit(policy, actor="authority", now=NOW)
    port.replace_resolved(authority.digest, replacement)

    selection = registry.select_for_inspection(_subject())

    assert selection.status is PolicySelectionStatus.INSPECTION_PENDING_POLICY


def test_selection_rejects_wrong_subject_arity_and_pair_order(tmp_path: Path) -> None:
    """Selecting ACTIVE for the wrong single/pair arity or reversed pair scope is forbidden."""
    first_subject = _subject()
    second_subject = _subject(marker="0")
    policy, authority = _bound_policy(
        subjects=(first_subject, second_subject),
        uses=("VISUAL_COMPARISON", "RELATIVE_VOLUME"),
    )
    registry = _registry(tmp_path, FakePolicyAuthorityPort(authority))
    registry.admit(policy, actor="authority", now=NOW)

    wrong_arity = registry.select_for_use("VISUAL_COMPARISON", (first_subject,))
    wrong_order = registry.select_for_use("VISUAL_COMPARISON", (second_subject, first_subject))
    duplicate_pair = registry.select_for_use("RELATIVE_VOLUME", (first_subject, first_subject))

    assert wrong_arity.status is PolicySelectionStatus.POLICY_UNAVAILABLE
    assert wrong_order.status is PolicySelectionStatus.POLICY_UNAVAILABLE
    assert duplicate_pair.status is PolicySelectionStatus.POLICY_UNAVAILABLE


def test_two_subject_allowlist_selects_each_single_and_its_ordered_pair(tmp_path: Path) -> None:
    """A pair scope remains ordered while either permitted subject remains singly selectable."""
    first_subject = _subject()
    second_subject = _subject(marker="0")
    policy, authority = _bound_policy(
        subjects=(first_subject, second_subject),
        uses=("INSPECTION", "VISUAL_COMPARISON"),
    )
    registry = _registry(tmp_path, FakePolicyAuthorityPort(authority))
    registry.admit(policy, actor="authority", now=NOW)

    first = registry.select_for_inspection(first_subject)
    second = registry.select_for_inspection(second_subject)
    pair = registry.select_for_use("VISUAL_COMPARISON", (first_subject, second_subject))

    assert first.status is PolicySelectionStatus.ACTIVE
    assert second.status is PolicySelectionStatus.ACTIVE
    assert pair.status is PolicySelectionStatus.ACTIVE


def test_evidence_selects_each_subject_in_a_two_subject_authority_allowlist(tmp_path: Path) -> None:
    """EVIDENCE has single-subject authority semantics even when approval lists two subjects."""
    first_subject = _subject()
    second_subject = _subject(marker="0")
    unlisted_subject = _subject(marker="9")
    policy, authority = _bound_policy(
        subjects=(first_subject, second_subject),
        uses=("EVIDENCE",),
    )
    registry = _registry(tmp_path, FakePolicyAuthorityPort(authority))
    registry.admit(policy, actor="authority", now=NOW)

    first = registry.select_for_use("EVIDENCE", (first_subject,))
    second = registry.select_for_use("EVIDENCE", (second_subject,))
    unlisted = registry.select_for_use("EVIDENCE", (unlisted_subject,))

    assert first.status is PolicySelectionStatus.ACTIVE
    assert second.status is PolicySelectionStatus.ACTIVE
    assert unlisted.status is PolicySelectionStatus.POLICY_UNAVAILABLE


def test_display_and_height_require_exactly_one_subject(tmp_path: Path) -> None:
    """DISPLAY and HEIGHT may never select a policy for a missing or paired subject scope."""
    first_subject = _subject()
    second_subject = _subject(marker="0")
    policy, authority = _bound_policy(
        subjects=(first_subject, second_subject),
        uses=("DISPLAY", "HEIGHT"),
    )
    registry = _registry(tmp_path, FakePolicyAuthorityPort(authority))
    registry.admit(policy, actor="authority", now=NOW)

    assert registry.select_for_use("DISPLAY", ()).status is PolicySelectionStatus.POLICY_UNAVAILABLE
    assert (
        registry.select_for_use("DISPLAY", (first_subject, second_subject)).status
        is PolicySelectionStatus.POLICY_UNAVAILABLE
    )
    assert registry.select_for_use("HEIGHT", ()).status is PolicySelectionStatus.POLICY_UNAVAILABLE
    assert (
        registry.select_for_use("HEIGHT", (first_subject, second_subject)).status
        is PolicySelectionStatus.POLICY_UNAVAILABLE
    )


def test_supersession_blocks_only_the_prior_lifecycle_entry(tmp_path: Path) -> None:
    """Mutating either admitted snapshot during supersession would fail retained-history lookup."""
    original, original_authority = _bound_policy()
    successor, successor_authority = _bound_policy(policy_id="policy-2")
    authority_port = FakePolicyAuthorityPort(original_authority, successor_authority)
    path = tmp_path / "superseded.jsonl"
    journal = DurableJournal(path)
    registry = _registry_for_journal(journal, authority_port)
    registry.admit(original, actor="authority", now=NOW)
    successor_receipt = registry.admit(successor, actor="authority", now=NOW)

    superseded = registry.supersede(
        original.policy_id,
        original.version,
        successor.policy_id,
        successor.version,
        actor="authority",
        now=NOW,
    )

    assert superseded.status is PolicyReceiptStatus.SUPERSEDED
    assert registry.resolve(original.policy_digest or "").status is PolicySelectionStatus.SUPERSEDED
    assert successor_receipt.policy_digest is not None
    assert registry.resolve(successor_receipt.policy_digest).status is PolicySelectionStatus.ACTIVE
    events = journal.replay()
    assert len(events) == 3
    assert all(
        event["eventVersion"] == 1 and event["eventDigest"] == _event_digest(event)
        for event in events
    )
    journal.close()

    restarted = _registry_for_journal(DurableJournal(path), authority_port)

    assert (
        restarted.resolve(original.policy_digest or "").status is PolicySelectionStatus.SUPERSEDED
    )
    assert restarted.resolve(successor_receipt.policy_digest).status is PolicySelectionStatus.ACTIVE


def test_admission_rejects_expired_or_unauthorized_authority_without_event(tmp_path: Path) -> None:
    """Accepting expired or unauthorized policy administration would fail this fail-closed test."""
    policy, expired = _bound_policy(active_until=NOW - timedelta(seconds=1))
    journal = DurableJournal(tmp_path / "expired.jsonl")
    registry = _registry_for_journal(journal, FakePolicyAuthorityPort(expired))

    receipt = registry.admit(policy, actor="not-authorized", now=NOW)

    assert receipt.status is PolicyReceiptStatus.POLICY_AUTHORITY_UNRESOLVED
    assert journal.replay() == []


def test_selection_releases_registry_lock_while_authority_resolution_waits(tmp_path: Path) -> None:
    """A retained policy read must not wait on an external authority callback."""
    policy, authority = _bound_policy(uses=("EVIDENCE",))
    port = FakePolicyAuthorityPort(authority)
    registry = _registry(tmp_path, port)
    assert registry.admit(policy, actor="authority", now=NOW).status is PolicyReceiptStatus.ADMITTED
    entered = threading.Event()
    release = threading.Event()
    retained_read_done = threading.Event()
    selected: list[PolicySelectionStatus] = []
    original_resolve = port.resolve

    def blocking_resolve(
        authority_record_digest: str, now: datetime
    ) -> PolicyAuthorityRecord | None:
        entered.set()
        release.wait(timeout=3)
        return original_resolve(authority_record_digest, now)

    port.resolve = blocking_resolve  # type: ignore[method-assign]
    selector = threading.Thread(
        target=lambda: selected.append(registry.select_for_use("EVIDENCE", (_subject(),)).status),
        daemon=True,
    )

    def read_retained() -> None:
        registry.resolve(policy.policy_digest or "")
        retained_read_done.set()

    retained_reader = threading.Thread(
        target=read_retained,
        daemon=True,
    )
    try:
        selector.start()
        assert entered.wait(timeout=1)
        retained_reader.start()
        assert retained_read_done.wait(timeout=0.2)
    finally:
        release.set()
        selector.join(timeout=2)
        retained_reader.join(timeout=2)

    assert not selector.is_alive()
    assert not retained_reader.is_alive()
    assert selected == [PolicySelectionStatus.ACTIVE]


def test_selection_fails_closed_when_registry_lifecycle_changes_during_authority_resolution(
    tmp_path: Path,
) -> None:
    """A policy revoked while its external resolution waits cannot become selectable."""
    policy, authority = _bound_policy(uses=("EVIDENCE",))
    port = FakePolicyAuthorityPort(authority)
    registry = _registry(tmp_path, port)
    assert registry.admit(policy, actor="authority", now=NOW).status is PolicyReceiptStatus.ADMITTED
    entered = threading.Event()
    release = threading.Event()
    revoked = threading.Event()
    selected: list[PolicySelectionStatus] = []
    resolution_count = 0
    resolution_lock = threading.Lock()
    original_resolve = port.resolve

    def block_only_selection(
        authority_record_digest: str, now: datetime
    ) -> PolicyAuthorityRecord | None:
        nonlocal resolution_count
        with resolution_lock:
            resolution_count += 1
            call = resolution_count
        if call == 1:
            entered.set()
            release.wait(timeout=3)
        return original_resolve(authority_record_digest, now)

    port.resolve = block_only_selection  # type: ignore[method-assign]
    selector = threading.Thread(
        target=lambda: selected.append(registry.select_for_use("EVIDENCE", (_subject(),)).status),
        daemon=True,
    )

    def revoke() -> None:
        receipt = registry.revoke(policy.policy_id, policy.version, actor="authority", now=NOW)
        assert receipt.status is PolicyReceiptStatus.REVOKED
        revoked.set()

    revoker = threading.Thread(target=revoke, daemon=True)
    try:
        selector.start()
        assert entered.wait(timeout=1)
        revoker.start()
        assert revoked.wait(timeout=0.2)
    finally:
        release.set()
        selector.join(timeout=2)
        revoker.join(timeout=2)

    assert not selector.is_alive()
    assert not revoker.is_alive()
    assert selected == [PolicySelectionStatus.POLICY_UNAVAILABLE]


def test_single_volume_is_a_single_subject_use(tmp_path: Path) -> None:
    """SINGLE_VOLUME is selected for exactly one sealed subject, never a pair."""
    subject = _subject(marker="a")
    policy, authority = _bound_policy(subjects=(subject,), uses=("SINGLE_VOLUME",))
    registry = _registry(tmp_path, FakePolicyAuthorityPort(authority))
    assert registry.admit(policy, actor="authority", now=NOW).status is PolicyReceiptStatus.ADMITTED

    selected = registry.select_for_use("SINGLE_VOLUME", (subject,))
    assert selected.status is PolicySelectionStatus.ACTIVE
    assert registry.locally_current_use_permitted(
        policy.policy_digest or "", use="SINGLE_VOLUME", subjects=(subject,), at=NOW
    )
    paired = registry.select_for_use("SINGLE_VOLUME", (subject, _subject(marker="d")))
    assert paired.status is PolicySelectionStatus.POLICY_UNAVAILABLE
    assert paired.reason == "SUBJECT_ARITY_INVALID"
