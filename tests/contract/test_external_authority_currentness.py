"""Single-process serialization for external authority mutation and use checks."""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path

import pytest
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_artifact_inspections import ExternalArtifactInspectionStore
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_display_artifacts import ExternalDisplayArtifactStore
from ksi_core.external_reconstruction import ExternalReconstructionRevision
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from support.external_artifact_inspection_fixtures import (
    NOW,
    SyntheticStorage,
    policy_template,
    report,
    sealed_manifest,
    sealed_submission,
    subject,
)


class _PolicyAuthority(PolicyAuthorityPort):
    def __init__(self, record: PolicyAuthorityRecord) -> None:
        assert record.digest is not None
        self._record = record
        self._coordinator: ExternalAuthorityCurrentnessCoordinator | None = None

    def bind(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> _PolicyAuthority:
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        assert self._coordinator is not None
        return self._coordinator

    def resolve(self, authority_record_digest: str, now: object) -> PolicyAuthorityRecord | None:
        del now
        return self._record if authority_record_digest == self._record.digest else None

    def resolve_historical(
        self, authority_record_digest: str, at: object
    ) -> PolicyAuthorityRecord | None:
        del at
        return self._record if authority_record_digest == self._record.digest else None

    def is_current(self, authority: PolicyAuthorityRecord, now: object) -> bool:
        del now
        return authority == self._record


class _SealedIngress:
    def sealed_revisions_snapshot(self) -> tuple[ExternalReconstructionRevision, ...]:
        submission = sealed_submission()
        return (
            ExternalReconstructionRevision(
                work_order_id="work-order-1",
                work_order_version=1,
                cycle_number=1,
                observation_epoch_id=submission.observation_epoch_id,
                submission=submission,
                registered_at=NOW,
                registered_by="operator-1",
                bindings=(("ortho", "external-reconstruction/v1/synthetic-ortho"),),
                manifest=sealed_manifest(),
            ),
        )


def test_guarded_read_keeps_later_mutation_outside_the_authority_snapshot() -> None:
    """Removing the shared lock would let revocation interleave before a guarded append."""
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    entered = threading.Event()
    mutation_finished = threading.Event()

    def mutate() -> None:
        entered.wait()
        with coordinator.mutation():
            mutation_finished.set()

    thread = threading.Thread(target=mutate)
    thread.start()
    with coordinator.guarded_read():
        entered.set()
        assert not mutation_finished.wait(timeout=0.05)
    assert mutation_finished.wait(timeout=1)
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_actual_inspection_issue_waits_for_the_shared_guard(tmp_path: Path) -> None:
    """Removing the coordinated issue commit would append while a use snapshot is open."""
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    template = policy_template()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(subject(),),
        permitted_uses=("INSPECTION", "DISPLAY"),
        authorized_actor_ids=("authority",),
        active_from=NOW - timedelta(minutes=1),
        active_until=NOW + timedelta(minutes=1),
        synthetic_test_only=True,
    ).sealed()
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    authority_port = _PolicyAuthority(authority)
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority_port=authority_port,
        authority_currentness_port=authority_port.bind(coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    registry.admit(policy, actor="authority", now=NOW)
    store = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "inspection.jsonl"),
        policy_registry=registry,
        external_reconstruction=_SealedIngress(),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    finished = threading.Event()
    verdicts: list[str] = []

    def issue() -> None:
        try:
            verdicts.append(store.issue_after_seal(subject(), now=NOW).verdict.value)
        finally:
            finished.set()

    with coordinator.guarded_read():
        thread = threading.Thread(target=issue)
        thread.start()
        assert not finished.wait(timeout=0.1)
    thread.join(timeout=1)
    assert finished.is_set()
    assert not thread.is_alive()
    assert verdicts == ["ISSUED"]


def test_actual_display_queue_append_waits_for_the_shared_guard(tmp_path: Path) -> None:
    """A display queue append must not cross a coherent use snapshot boundary."""
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    template = policy_template()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(subject(),),
        permitted_uses=("INSPECTION", "DISPLAY"),
        authorized_actor_ids=("authority",),
        active_from=NOW - timedelta(minutes=1),
        active_until=NOW + timedelta(minutes=1),
        synthetic_test_only=True,
    ).sealed()
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    authority_port = _PolicyAuthority(authority)
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority_port=authority_port,
        authority_currentness_port=authority_port.bind(coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    registry.admit(policy, actor="authority", now=NOW)
    display = ExternalDisplayArtifactStore(
        DurableJournal(tmp_path / "display.jsonl"),
        policy_registry=registry,
        storage=SyntheticStorage(),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    accepted = report(request_id="request-1", policy=policy)
    finished = threading.Event()
    phases: list[str] = []

    def enqueue() -> None:
        try:
            phases.append(
                display.ensure_after_report(
                    accepted,
                    display_permitted=True,
                    measured_ortho=True,
                    max_retry_attempts=1,
                    max_output_bytes=1024,
                    now=NOW,
                ).value
            )
        finally:
            finished.set()

    with coordinator.guarded_read():
        thread = threading.Thread(target=enqueue)
        thread.start()
        assert not finished.wait(timeout=0.1)
    thread.join(timeout=1)
    assert finished.is_set()
    assert not thread.is_alive()
    assert phases == ["QUEUED"]


def test_display_store_rejects_a_mismatched_policy_coordinator(tmp_path: Path) -> None:
    """A direct display queue must not sit outside the assembled authority graph."""
    template = policy_template()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(subject(),),
        permitted_uses=("INSPECTION", "DISPLAY"),
        authorized_actor_ids=("authority",),
        active_from=NOW - timedelta(minutes=1),
        active_until=NOW + timedelta(minutes=1),
        synthetic_test_only=True,
    ).sealed()
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    authority_port = _PolicyAuthority(authority)
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority_port=authority_port,
        authority_currentness_port=authority_port.bind(coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    registry.admit(policy, actor="authority", now=NOW)

    with pytest.raises(ValueError, match="display policy registry must share"):
        ExternalDisplayArtifactStore(
            DurableJournal(tmp_path / "display.jsonl"),
            policy_registry=registry,
            storage=SyntheticStorage(),
            clock=lambda: NOW,
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )
