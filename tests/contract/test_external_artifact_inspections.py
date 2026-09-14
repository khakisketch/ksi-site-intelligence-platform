"""Contract tests for Core's durable external-artifact inspection queue."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import EvidenceStorageError, ObjectStorageObservation
from ksi_core.external_artifact_inspections import (
    ExternalArtifactInspectionRecoveryError,
    ExternalArtifactInspectionStore,
    ExternalInspectionFailureV1,
    InspectionPhase,
    SealedExternalReconstructionSnapshotPort,
)
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_display_artifacts import (
    DisplayArtifactVerdict,
    DisplayPhase,
    ExternalDisplayArtifactStore,
)
from ksi_core.external_reconstruction import (
    ExternalReconstructionRevision,
    ExternalReconstructionStore,
)
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from ksi_core.leasing import LeaseFence
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalArtifactInspectionReportV1,
    ExternalArtifactInspectionRequestV1,
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_display_artifact import SanitizedDisplayDeclarationV1
from ksi_event_contracts.external_reconstruction import (
    ExternalReconstructionManifestEntryV1,
    ExternalReconstructionManifestV1,
    ExternalReconstructionSubmissionV1,
)
from ksi_mission_contracts.models import SiteFrame
from support.external_artifact_inspection_fixtures import (
    ACQUISITION,
    ACQUISITION_B,
    ACQUISITION_C,
    NOW,
    WORKER_A,
    WORKER_B,
    SyntheticObservation,
    SyntheticStorage,
    digest,
    policy_template,
    report,
    sealed_manifest,
    sealed_submission,
    subject,
)


class _FixtureIngress(SealedExternalReconstructionSnapshotPort):
    """A typed public ingress snapshot; no synthetic-only record shape leaks in."""

    def __init__(self, *, include_dsm: bool = False) -> None:
        self._include_dsm = include_dsm

    def sealed_revisions_snapshot(self) -> tuple[ExternalReconstructionRevision, ...]:
        submission = sealed_submission(include_dsm=self._include_dsm)
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
                manifest=sealed_manifest(include_dsm=self._include_dsm),
            ),
        )


class _Authority(PolicyAuthorityPort):
    def __init__(self, *records: PolicyAuthorityRecord) -> None:
        assert all(record.digest is not None for record in records)
        self._records = {record.digest: record for record in records}
        self._coordinator: ExternalAuthorityCurrentnessCoordinator | None = None

    def bind(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> _Authority:
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        assert self._coordinator is not None
        return self._coordinator

    def resolve(self, authority_record_digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        del now
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


class _FailOnceDisplayStore(ExternalDisplayArtifactStore):
    """Models the independent display journal being unavailable after report fsync."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        policy_registry: ExternalValidationPolicyRegistry,
        storage: SyntheticStorage,
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(journal, policy_registry=policy_registry, storage=storage, clock=clock)
        self._fail_once = True

    def ensure_after_report(
        self,
        report: ExternalArtifactInspectionReportV1,
        *,
        display_permitted: bool,
        measured_ortho: bool,
        max_retry_attempts: int,
        max_output_bytes: int,
        now: datetime,
    ) -> DisplayPhase:
        if self._fail_once:
            self._fail_once = False
            raise RuntimeError("synthetic display journal interruption")
        return super().ensure_after_report(
            report,
            display_permitted=display_permitted,
            measured_ortho=measured_ortho,
            max_retry_attempts=max_retry_attempts,
            max_output_bytes=max_output_bytes,
            now=now,
        )


def _bound_policy(
    *,
    permitted_subject: SealedExternalSubjectV1 | None = None,
    max_deadline_seconds: float | None = None,
) -> tuple[ExternalValidationPolicyV1, _Authority]:
    template = policy_template()
    if max_deadline_seconds is not None:
        assert template.resource_envelope is not None
        envelope = template.resource_envelope.model_copy(
            update={"max_deadline_seconds": max_deadline_seconds, "resource_envelope_digest": None},
            deep=True,
        ).sealed()
        template = template.model_copy(
            update={
                "resource_envelope": envelope,
                "resource_envelope_digest": envelope.resource_envelope_digest,
                "policy_digest": None,
            },
            deep=True,
        ).sealed()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(permitted_subject or subject(),),
        permitted_uses=("INSPECTION", "DISPLAY"),
        authorized_actor_ids=("authority",),
        active_from=NOW - timedelta(minutes=1),
        active_until=NOW + timedelta(minutes=1),
        synthetic_test_only=True,
    ).sealed()
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    return policy, _Authority(authority)


def _sealed_digest(value: str | None) -> str:
    assert value is not None
    return value


def _policy_registry(
    journal: DurableJournal, authority: _Authority, *, clock: Callable[[], datetime]
) -> ExternalValidationPolicyRegistry:
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    return ExternalValidationPolicyRegistry(
        journal,
        authority_port=authority,
        authority_currentness_port=authority.bind(coordinator),
        clock=clock,
        coordinator=coordinator,
    )


def _stores(
    tmp_path: Path,
    *,
    active: bool,
    permitted_subject: SealedExternalSubjectV1 | None = None,
    ingress: SealedExternalReconstructionSnapshotPort | None = None,
    max_deadline_seconds: float | None = None,
) -> tuple[ExternalArtifactInspectionStore, ExternalValidationPolicyV1]:
    policy, authority = _bound_policy(
        permitted_subject=permitted_subject, max_deadline_seconds=max_deadline_seconds
    )
    registry = _policy_registry(
        DurableJournal(tmp_path / "policy.jsonl"), authority, clock=lambda: NOW
    )
    if active:
        registry.admit(policy, actor="authority", now=NOW)
    store = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "inspection.jsonl"),
        policy_registry=registry,
        external_reconstruction=ingress or _FixtureIngress(),
        clock=lambda: NOW,
    )
    return store, policy


def test_reconcile_issues_once_after_policy_arrives(tmp_path: Path) -> None:
    """Selecting a default policy or duplicate issue event would fail this test."""
    store, policy = _stores(tmp_path, active=False)
    assert store.issue_after_seal(subject(), now=NOW).verdict == "INSPECTION_PENDING_POLICY"
    store._policy_registry.admit(policy, actor="authority", now=NOW)  # noqa: SLF001
    assert (store.reconcile_sealed(now=NOW), store.reconcile_sealed(now=NOW)) == (1, 0)


def test_stale_fence_cannot_finalize_but_successor_can(tmp_path: Path) -> None:
    """Accepting an expired worker report would let stale work rewrite the queue."""
    store, policy = _stores(tmp_path, active=True)
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    old_intent = LeaseFence(WORKER_A, ACQUISITION, 0)
    claimed = store.claim(issued.request.request_id, old_intent, now=NOW)
    assert claimed.verdict == "LEASED"
    assert claimed.fence is not None
    old = claimed.fence
    successor_claim = store.claim(
        issued.request.request_id,
        LeaseFence(WORKER_B, ACQUISITION_B, 0),
        now=NOW + timedelta(seconds=5),
    )
    assert successor_claim.verdict == "LEASED"
    assert successor_claim.fence is not None
    successor = successor_claim.fence
    assert (
        store.record_report(
            issued.request.request_id,
            old,
            report(request_id=issued.request.request_id, policy=policy),
            now=NOW + timedelta(seconds=5),
        ).verdict
        == "LEASE_FENCE_REJECTED"
    )
    assert (
        store.record_report(
            issued.request.request_id,
            successor,
            report(
                request_id=issued.request.request_id,
                policy=policy,
                worker=WORKER_B,
                acquisition=ACQUISITION_B,
                generation=2,
            ),
            now=NOW + timedelta(seconds=5),
        ).verdict
        == "REPORTED"
    )


def test_exact_report_retry_deduplicates_but_changed_payload_is_rejected(tmp_path: Path) -> None:
    """Replacing accepted measurement evidence on a lost transport response must fail."""
    store, policy = _stores(tmp_path, active=True)
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    claimed = store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert claimed.fence is not None
    fence = claimed.fence
    accepted = report(request_id=issued.request.request_id, policy=policy, marker="a")
    changed = report(request_id=issued.request.request_id, policy=policy, marker="b")
    assert (
        store.record_report(issued.request.request_id, fence, accepted, now=NOW).verdict
        == "REPORTED"
    )
    assert (
        store.record_report(issued.request.request_id, fence, accepted, now=NOW).verdict
        == "REPORTED"
    )
    assert (
        store.record_report(issued.request.request_id, fence, changed, now=NOW).verdict
        == "PAYLOAD_DIVERGENCE"
    )


def test_report_with_non_rgb_ortho_measurements_is_not_retained(tmp_path: Path) -> None:
    """Core rechecks retained measured shape; the worker cannot widen declared ORTHO."""
    store, policy = _stores(tmp_path, active=True)
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    claimed = store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert claimed.fence is not None
    accepted = report(request_id=issued.request.request_id, policy=policy)
    outcome = accepted.measurement_payload.outcomes[0]
    assert outcome.measurements is not None
    non_rgb = accepted.model_copy(
        update={
            "measurement_payload": accepted.measurement_payload.model_copy(
                update={
                    "outcomes": (
                        outcome.model_copy(
                            update={
                                "measurements": outcome.measurements.model_copy(
                                    update={"band_count": 1}
                                )
                            }
                        ),
                    )
                }
            ),
            "measurement_payload_digest": None,
            "report_digest": None,
        },
        deep=True,
    ).sealed()

    result = store.record_report(issued.request.request_id, claimed.fence, non_rgb, now=NOW)

    assert result.verdict == "REPORT_BINDING_REJECTED"
    assert store.input_for(issued.request.request_id, claimed.fence).accepted_report is None


def test_rejected_dsm_does_not_block_a_displayable_rgb_ortho(tmp_path: Path) -> None:
    """The typed unsupported DSM outcome is retained without suppressing ORTHO display work."""
    sealed_subject = subject(include_dsm=True)
    store, policy = _stores(
        tmp_path,
        active=True,
        permitted_subject=sealed_subject,
        ingress=_FixtureIngress(include_dsm=True),
    )
    issued = store.issue_after_seal(sealed_subject, now=NOW)
    assert issued.request is not None
    claimed = store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert claimed.fence is not None

    result = store.record_report(
        issued.request.request_id,
        claimed.fence,
        report(request_id=issued.request.request_id, policy=policy, include_dsm=True),
        now=NOW,
    )

    assert result.verdict == "REPORTED"
    assert result.phase is InspectionPhase.DISPLAY


def test_reported_inspection_cannot_append_an_incomplete_failure(tmp_path: Path) -> None:
    """A delayed inspection failure must not make an accepted report unreplayable."""
    store, policy = _stores(tmp_path, active=True)
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    claimed = store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert claimed.fence is not None
    assert (
        store.record_report(
            issued.request.request_id,
            claimed.fence,
            report(request_id=issued.request.request_id, policy=policy),
            now=NOW,
        ).verdict
        == "REPORTED"
    )
    prior_events = tuple(store._journal.replay())  # noqa: SLF001 - durable boundary assertion.

    rejected = store.record_incomplete_failure(
        issued.request.request_id,
        claimed.fence,
        ExternalInspectionFailureV1("TRANSIENT_STORAGE_UNAVAILABLE"),
        NOW,
    )

    assert rejected.verdict == "REPORT_BINDING_REJECTED"
    assert tuple(store._journal.replay()) == prior_events  # noqa: SLF001


def test_replay_rejects_report_without_a_live_predecessor_lease(tmp_path: Path) -> None:
    """An event stream cannot skip CLAIM and manufacture accepted measurements."""
    store, policy = _stores(tmp_path, active=True)
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    forged = report(request_id=issued.request.request_id, policy=policy)
    event = {
        "kind": "external-artifact-inspection-reported",
        "version": 1,
        "requestId": issued.request.request_id,
        "subjectDigest": forged.subject_digest,
        "policyDigest": forged.inspection_policy_digest,
        "reportDigest": forged.report_digest,
        "measurementPayloadDigest": forged.measurement_payload_digest,
        "displayRequired": False,
        "workerInstanceId": WORKER_A,
        "leaseAcquisitionId": ACQUISITION,
        "leaseGeneration": 1,
        "recordedAt": "2026-09-07T00:00:00Z",
        "report": forged.model_dump(by_alias=True, mode="json"),
    }
    event["eventDigest"] = "sha256:" + hashlib.sha256(canonical_json_bytes(event)).hexdigest()

    with pytest.raises(ExternalArtifactInspectionRecoveryError):
        store._apply(event)  # noqa: SLF001 - malformed journal transition is the contract.


def test_expired_acquisition_ids_are_one_shot_but_live_claim_is_idempotent(
    tmp_path: Path,
) -> None:
    """A delayed A cannot reclaim after B; C needs a fresh acquisition UUID."""
    store, _policy = _stores(tmp_path, active=True)
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    first = store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert first.fence is not None
    assert (
        store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW).fence
        == first.fence
    )
    second = store.claim(
        issued.request.request_id,
        LeaseFence(WORKER_B, ACQUISITION_B, 0),
        now=NOW + timedelta(seconds=5),
    )
    assert second.fence is not None and second.fence.lease_generation == 2
    assert (
        store.claim(
            issued.request.request_id,
            LeaseFence(WORKER_A, ACQUISITION, 0),
            now=NOW + timedelta(seconds=9),
        ).verdict
        == "LEASE_FENCE_REJECTED"
    )
    third = store.claim(
        issued.request.request_id,
        LeaseFence(WORKER_A, ACQUISITION_C, 0),
        now=NOW + timedelta(seconds=9),
    )
    assert third.fence is not None and third.fence.lease_generation == 3


def test_revoked_policy_refuses_leased_writes_but_keeps_history(tmp_path: Path) -> None:
    """A historical policy resolution must not extend or finalize an active lease."""
    store, policy = _stores(tmp_path, active=True)
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    claimed = store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert claimed.verdict == "LEASED"
    assert claimed.fence is not None
    fence = claimed.fence

    store._policy_registry.revoke(policy.policy_id, policy.version, actor="authority", now=NOW)  # noqa: SLF001

    assert (
        store.heartbeat(issued.request.request_id, fence, now=NOW).verdict == "POLICY_UNAVAILABLE"
    )
    assert (
        store.record_report(
            issued.request.request_id,
            fence,
            report(request_id=issued.request.request_id, policy=policy),
            now=NOW,
        ).verdict
        == "POLICY_UNAVAILABLE"
    )
    assert store.list_pending(1) == ()


def test_only_explicitly_transient_incomplete_failures_reenter_queue(tmp_path: Path) -> None:
    """Identity, scope, and sealed-byte failure codes are terminal at first occurrence."""
    terminal_store, _policy = _stores(tmp_path / "terminal", active=True)
    issued = terminal_store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    terminal_claim = terminal_store.claim(
        issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW
    )
    assert terminal_claim.fence is not None
    assert (
        terminal_store.record_incomplete_failure(
            issued.request.request_id,
            terminal_claim.fence,
            ExternalInspectionFailureV1("SEALED_BYTE_IDENTITY_MISMATCH"),
            NOW,
        ).verdict
        == "INSPECTION_FAILED_INCOMPLETE"
    )
    assert terminal_store.list_pending(1) == ()

    retry_store, _policy = _stores(tmp_path / "transient", active=True)
    retry_issued = retry_store.issue_after_seal(subject(), now=NOW)
    assert retry_issued.request is not None
    retry_claim = retry_store.claim(
        retry_issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW
    )
    assert retry_claim.fence is not None
    assert (
        retry_store.record_incomplete_failure(
            retry_issued.request.request_id,
            retry_claim.fence,
            ExternalInspectionFailureV1("TRANSIENT_STORAGE_UNAVAILABLE"),
            NOW,
        ).verdict
        == "QUEUED"
    )
    assert retry_store.list_pending(1)[0].request_id == retry_issued.request.request_id


def test_initial_claim_near_deadline_caps_durable_lease_expiry(tmp_path: Path) -> None:
    store, _policy = _stores(tmp_path, active=True)
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    lease = store.claim(
        issued.request.request_id,
        LeaseFence(WORKER_A, ACQUISITION, 0),
        now=NOW + timedelta(seconds=9),
    )
    assert lease.verdict == "LEASED"
    assert lease.lease_expires_at == NOW + timedelta(seconds=10)
    event = tuple(store._journal.replay())[-1]  # noqa: SLF001 - durable expiry contract.
    expected_expiry = (NOW + timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
    assert event["leaseExpiresAt"] == expected_expiry


def test_retry_attempts_are_policy_bound_and_deadline_does_not_reset(tmp_path: Path) -> None:
    """The initial lease plus only two fresh retries fit this synthetic policy."""
    store, _policy = _stores(tmp_path, active=True)
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    attempts = (
        (WORKER_A, ACQUISITION, NOW),
        (WORKER_B, ACQUISITION_B, NOW + timedelta(seconds=5)),
        (WORKER_A, ACQUISITION_C, NOW + timedelta(seconds=9)),
    )
    for index, (worker, acquisition, attempt_now) in enumerate(attempts, start=1):
        lease = store.claim(
            issued.request.request_id,
            LeaseFence(worker, acquisition, 0),
            now=attempt_now,
        )
        assert lease.fence is not None
        result = store.record_incomplete_failure(
            issued.request.request_id,
            lease.fence,
            ExternalInspectionFailureV1("TRANSIENT_STORAGE_UNAVAILABLE"),
            attempt_now,
        )
        assert result.verdict == ("INSPECTION_FAILED_INCOMPLETE" if index == 3 else "QUEUED")
    event = tuple(store._journal.replay())[-1]  # noqa: SLF001 - exact durable event contract.
    assert event["attemptCount"] == 3
    assert event["retryRuleId"] == "TRANSIENT_IMMEDIATE_RETRY_V1"
    assert event["nextEligibleAt"] == event["recordedAt"]
    deadline_store, _policy = _stores(tmp_path / "deadline", active=True)
    deadline_issued = deadline_store.issue_after_seal(subject(), now=NOW)
    assert deadline_issued.request is not None
    assert (
        deadline_store.claim(
            deadline_issued.request.request_id,
            LeaseFence(WORKER_B, "123e4567-e89b-42d3-a456-426614174005", 0),
            now=NOW + timedelta(seconds=11),
        ).verdict
        == "DEADLINE_EXCEEDED"
    )
    exhausted_event = tuple(deadline_store._journal.replay())[-1]  # noqa: SLF001
    assert exhausted_event["kind"] == "external-artifact-inspection-exhausted"
    assert deadline_store.list_pending(1) == ()

    count_store, _policy = _stores(
        tmp_path / "count", active=True, max_deadline_seconds=20.0
    )
    count_issued = count_store.issue_after_seal(subject(), now=NOW)
    assert count_issued.request is not None
    for worker, acquisition, claimed_at in (
        (WORKER_A, ACQUISITION, NOW),
        (WORKER_B, ACQUISITION_B, NOW + timedelta(seconds=5)),
        (WORKER_A, ACQUISITION_C, NOW + timedelta(seconds=9)),
    ):
        assert count_store.claim(
            count_issued.request.request_id,
            LeaseFence(worker, acquisition, 0),
            now=claimed_at,
        ).verdict == "LEASED"
    assert count_store.claim(
        count_issued.request.request_id,
        LeaseFence(WORKER_B, "123e4567-e89b-42d3-a456-426614174006", 0),
        now=NOW + timedelta(seconds=14),
    ).verdict == "RETRY_EXHAUSTED"
    count_event = tuple(count_store._journal.replay())[-1]  # noqa: SLF001
    assert count_event["reason"] == "RETRY_EXHAUSTED"
    assert count_store.list_pending(1) == ()


def test_heartbeat_cannot_extend_a_lease_past_the_absolute_deadline(tmp_path: Path) -> None:
    """A live-claim retry cannot hide a deadline behind repeated heartbeats."""
    policy, authority = _bound_policy()
    current_time = [NOW]
    registry = _policy_registry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority,
        clock=lambda: current_time[0],
    )
    registry.admit(policy, actor="authority", now=NOW)
    journal_path = tmp_path / "inspection.jsonl"
    store = ExternalArtifactInspectionStore(
        DurableJournal(journal_path),
        policy_registry=registry,
        external_reconstruction=_FixtureIngress(),
        clock=lambda: current_time[0],
    )
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    claimed = store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert claimed.fence is not None
    fence = claimed.fence

    current_time[0] = NOW + timedelta(seconds=3)
    first_heartbeat = store.heartbeat(issued.request.request_id, fence, now=current_time[0])
    assert first_heartbeat.lease_expires_at == NOW + timedelta(seconds=7)
    current_time[0] = NOW + timedelta(seconds=6)
    second_heartbeat = store.heartbeat(issued.request.request_id, fence, now=current_time[0])
    assert second_heartbeat.lease_expires_at == NOW + timedelta(seconds=10)
    current_time[0] = NOW + timedelta(seconds=9)
    third_heartbeat = store.heartbeat(issued.request.request_id, fence, now=current_time[0])
    assert third_heartbeat.lease_expires_at == NOW + timedelta(seconds=10)

    current_time[0] = NOW + timedelta(seconds=11)
    assert (
        store.claim(issued.request.request_id, fence, now=current_time[0]).verdict
        == "DEADLINE_EXCEEDED"
    )
    assert store.input_for(issued.request.request_id, fence).verdict == "DEADLINE_EXCEEDED"
    assert store.list_pending(1) == ()
    assert tuple(store._journal.replay())[-1]["kind"] == "external-artifact-inspection-exhausted"  # noqa: SLF001

    store._journal.close()  # noqa: SLF001 - process-boundary replay assertion.
    restarted = ExternalArtifactInspectionStore(
        DurableJournal(journal_path),
        policy_registry=registry,
        external_reconstruction=_FixtureIngress(),
        clock=lambda: current_time[0],
    )
    assert restarted.list_pending(1) == ()


def test_historical_display_obligation_survives_revocation_without_a_display_store(
    tmp_path: Path,
) -> None:
    """A report-time display obligation is not a current execution permission."""
    policy, authority = _bound_policy()
    current_time = [NOW]
    registry = _policy_registry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority,
        clock=lambda: current_time[0],
    )
    registry.admit(policy, actor="authority", now=NOW)
    store = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "inspection.jsonl"),
        policy_registry=registry,
        external_reconstruction=_FixtureIngress(),
        clock=lambda: current_time[0],
    )
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    claimed = store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert claimed.fence is not None

    accepted = store.record_report(
        issued.request.request_id,
        claimed.fence,
        report(request_id=issued.request.request_id, policy=policy),
        now=NOW,
    )

    assert accepted.phase is not None and accepted.phase.value == "DISPLAY"
    registry.revoke(policy.policy_id, policy.version, actor="authority", now=NOW)
    assert registry.historical_use_permitted(
        _sealed_digest(policy.policy_digest),
        use="DISPLAY",
        subjects=(subject(),),
        at=NOW,
    )
    assert registry.select_for_use("DISPLAY", (subject(),)).status.value == "POLICY_UNAVAILABLE"
    current_time[0] = NOW + timedelta(seconds=5)
    assert store.list_pending(1)[0].phase.value == "DISPLAY"
    assert (
        store.claim(
            issued.request.request_id,
            LeaseFence(WORKER_B, ACQUISITION_B, 0),
            now=current_time[0],
        ).verdict
        == "POLICY_UNAVAILABLE"
    )


def test_historical_obligation_ignores_later_display_competition_but_execution_does_not(
    tmp_path: Path,
) -> None:
    """A later DISPLAY-only policy cannot rewrite history or authorize resume."""
    template = policy_template()

    def bind(
        policy_id: str, uses: tuple[str, ...]
    ) -> tuple[ExternalValidationPolicyV1, PolicyAuthorityRecord]:
        unbound = template.model_copy(
            update={"policy_id": policy_id, "policy_digest": None}, deep=True
        )
        authority = PolicyAuthorityRecord(
            policy_id=policy_id,
            policy_version=unbound.version,
            authorized_policy_body_digest=authorized_policy_body_digest(unbound),
            permitted_subjects=(subject(),),
            permitted_uses=uses,
            authorized_actor_ids=("authority",),
            active_from=NOW - timedelta(minutes=1),
            active_until=NOW + timedelta(minutes=1),
            synthetic_test_only=True,
        ).sealed()
        policy = unbound.model_copy(
            update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
        ).sealed()
        return policy, authority

    primary, primary_authority = bind("policy-primary", ("INSPECTION", "DISPLAY"))
    competing, competing_authority = bind("policy-competing", ("DISPLAY",))

    current_time = [NOW]
    registry = _policy_registry(
        DurableJournal(tmp_path / "policy.jsonl"),
        _Authority(primary_authority, competing_authority),
        clock=lambda: current_time[0],
    )
    registry.admit(primary, actor="authority", now=NOW)
    store = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "inspection.jsonl"),
        policy_registry=registry,
        external_reconstruction=_FixtureIngress(),
        clock=lambda: current_time[0],
    )
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    first = store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert first.fence is not None
    assert store.record_report(
        issued.request.request_id,
        first.fence,
        report(request_id=issued.request.request_id, policy=primary),
        now=NOW,
    ).phase is InspectionPhase.DISPLAY
    assert registry.historical_use_permitted(
        _sealed_digest(primary.policy_digest),
        use="DISPLAY",
        subjects=(subject(),),
        at=NOW,
    )
    assert not registry.historical_use_permitted(
        _sealed_digest(primary.policy_digest),
        use="DISPLAY",
        subjects=(subject(), subject()),
        at=NOW,
    )

    registry.admit(competing, actor="authority", now=NOW + timedelta(seconds=1))
    current_time[0] = NOW + timedelta(seconds=5)
    assert registry.select_for_inspection(subject()).policy is not None
    assert registry.select_for_use("DISPLAY", (subject(),)).status.value == "POLICY_AMBIGUOUS"
    assert registry.historical_use_permitted(
        _sealed_digest(primary.policy_digest),
        use="DISPLAY",
        subjects=(subject(),),
        at=NOW,
    )
    assert (
        store.claim(
            issued.request.request_id,
            LeaseFence(WORKER_B, ACQUISITION_B, 0),
            now=current_time[0],
        ).verdict
        == "POLICY_UNAVAILABLE"
    )
    assert store.input_for(issued.request.request_id, first.fence).verdict == "POLICY_UNAVAILABLE"
    assert store.heartbeat(
        issued.request.request_id, first.fence, now=current_time[0]
    ).verdict == "POLICY_UNAVAILABLE"


def test_revoked_policy_repairs_missing_display_journal_but_blocks_execution(
    tmp_path: Path,
) -> None:
    """Historical queue repair is distinct from current display-worker authority."""
    policy, authority = _bound_policy()
    current_time = [NOW]
    registry = _policy_registry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority,
        clock=lambda: current_time[0],
    )
    registry.admit(policy, actor="authority", now=NOW)
    display = _FailOnceDisplayStore(
        DurableJournal(tmp_path / "display.jsonl"),
        policy_registry=registry,
        storage=SyntheticStorage(),
        clock=lambda: current_time[0],
    )
    queue = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "inspection.jsonl"),
        policy_registry=registry,
        external_reconstruction=_FixtureIngress(),
        display_store=display,
        clock=lambda: current_time[0],
    )
    issued = queue.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    initial = queue.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert initial.fence is not None
    assert queue.record_report(
        issued.request.request_id,
        initial.fence,
        report(request_id=issued.request.request_id, policy=policy),
        now=NOW,
    ).phase is InspectionPhase.DISPLAY
    assert display.phase_for(issued.request.request_id) is DisplayPhase.NOT_REQUIRED

    registry.revoke(policy.policy_id, policy.version, actor="authority", now=NOW)
    current_time[0] = NOW + timedelta(seconds=5)
    queue.reconcile_sealed(now=current_time[0])

    assert display.phase_for(issued.request.request_id) is DisplayPhase.QUEUED
    assert (
        queue.claim(
            issued.request.request_id,
            LeaseFence(WORKER_B, ACQUISITION_B, 0),
            now=current_time[0],
        ).verdict
        == "POLICY_UNAVAILABLE"
    )


def test_report_first_display_resumes_under_a_successor_fence(tmp_path: Path) -> None:
    """A crashed display worker resumes an accepted report without recomputing it."""

    class _NonceStorage(SyntheticStorage):
        def __init__(self) -> None:
            super().__init__()
            self.presigned_keys: list[str] = []

        def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
            del ttl
            self.presigned_keys.append(object_key)
            return f"https://storage.invalid/get/{len(self.presigned_keys)}/{object_key}"

    policy, authority = _bound_policy()
    current_time = [NOW]
    registry = _policy_registry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority,
        clock=lambda: current_time[0],
    )
    registry.admit(policy, actor="authority", now=NOW)
    storage = _NonceStorage()
    display = ExternalDisplayArtifactStore(
        DurableJournal(tmp_path / "display.jsonl"),
        policy_registry=registry,
        storage=storage,
        clock=lambda: current_time[0],
    )
    queue = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "inspection.jsonl"),
        policy_registry=registry,
        external_reconstruction=_FixtureIngress(),
        storage=storage,
        display_store=display,
        clock=lambda: current_time[0],
    )
    issued = queue.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    first = queue.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert first.fence is not None
    inspection_input = queue.input_for(issued.request.request_id, first.fence)
    assert inspection_input.phase is InspectionPhase.INSPECTION
    assert len(inspection_input.artifacts) == 1
    inspection_artifact = inspection_input.artifacts[0]
    assert inspection_artifact.download_url is not None
    assert storage.presigned_keys == ["external-reconstruction/v1/synthetic-ortho"]
    accepted = report(
        request_id=issued.request.request_id,
        policy=policy,
        worker=WORKER_A,
        generation=first.fence.lease_generation,
    )
    reported = queue.record_report(issued.request.request_id, first.fence, accepted, now=NOW)

    assert reported.phase is not None and reported.phase.value == "DISPLAY"
    assert display.phase_for(issued.request.request_id) is DisplayPhase.QUEUED
    current_time[0] = NOW + timedelta(seconds=5)
    assert queue.list_pending(1)[0].phase.value == "DISPLAY"
    resumed = queue.claim(
        issued.request.request_id,
        LeaseFence(WORKER_B, ACQUISITION_B, 0),
        now=NOW + timedelta(seconds=5),
    )
    assert resumed.phase is not None and resumed.phase.value == "DISPLAY"
    assert resumed.fence is not None and resumed.fence.lease_generation == 2
    history_before_input = tuple(queue._journal.replay())  # noqa: SLF001 - durable-history guard.
    display_input = queue.input_for(issued.request.request_id, resumed.fence)
    assert display_input.phase is not None and display_input.phase.value == "DISPLAY"
    assert display_input.accepted_report == accepted
    assert len(display_input.artifacts) == 1
    display_artifact = display_input.artifacts[0]
    assert (
        display_artifact.entry_id,
        display_artifact.kind,
        display_artifact.observed_sha256,
        display_artifact.observed_size_bytes,
        display_artifact.content_type,
        display_artifact.required_headers,
    ) == (
        inspection_artifact.entry_id,
        inspection_artifact.kind,
        inspection_artifact.observed_sha256,
        inspection_artifact.observed_size_bytes,
        inspection_artifact.content_type,
        inspection_artifact.required_headers,
    )
    assert storage.presigned_keys == [
        "external-reconstruction/v1/synthetic-ortho",
        "external-reconstruction/v1/synthetic-ortho",
    ]
    assert display_artifact.download_url is not None
    assert display_artifact.download_url != inspection_artifact.download_url
    assert tuple(queue._journal.replay()) == history_before_input  # noqa: SLF001

    declaration = SanitizedDisplayDeclarationV1(
        display_id="display-1",
        request_id=accepted.request_id,
        source_subject_digest=accepted.subject_digest,
        source_report_digest=_sealed_digest(accepted.report_digest),
        policy_digest=accepted.inspection_policy_digest,
        inspector_build_digest=accepted.inspector_build_digest,
        declared_derivative_sha256=digest("9"),
        declared_derivative_size_bytes=123,
        declared_derivative_content_type="image/tiff",
    )
    assert (
        display.grant(
            accepted.request_id, declaration, resumed.fence, now=NOW + timedelta(seconds=5)
        ).verdict
        is DisplayArtifactVerdict.DECLARATION_RECORDED
    )


def test_display_input_rechecks_source_capability_after_presigning(tmp_path: Path) -> None:
    """A capability minted before an expiry, takeover, or revocation never escapes."""

    class _MutatingPresignStorage(SyntheticStorage):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0
            self.mutate: Callable[[], object] | None = None

        def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
            self.calls += 1
            result = super().presigned_get(object_key, ttl=ttl)
            if self.mutate is not None:
                assert callable(self.mutate)
                self.mutate()
            return result

    expected_verdict = {
        "expiry": "LEASE_FENCE_REJECTED",
        "takeover": "LEASE_FENCE_REJECTED",
        "revocation": "POLICY_UNAVAILABLE",
        "supersession": "POLICY_UNAVAILABLE",
        "completion": "NOT_FOUND",
    }
    for scenario in expected_verdict:
        case_path = tmp_path / scenario
        case_path.mkdir()
        current_time = [NOW]
        policy, authority = _bound_policy()
        successor_template = policy_template().model_copy(
            update={"policy_id": "policy-2", "version": 2, "policy_digest": None}, deep=True
        )
        successor_authority = PolicyAuthorityRecord(
            policy_id=successor_template.policy_id,
            policy_version=successor_template.version,
            authorized_policy_body_digest=authorized_policy_body_digest(successor_template),
            permitted_subjects=(subject(),),
            permitted_uses=("INSPECTION", "DISPLAY"),
            authorized_actor_ids=("authority",),
            active_from=NOW - timedelta(minutes=1),
            active_until=NOW + timedelta(minutes=1),
            synthetic_test_only=True,
        ).sealed()
        successor = successor_template.model_copy(
            update={"authority_record_digest": successor_authority.digest, "policy_digest": None},
            deep=True,
        ).sealed()

        def clock(current_time: list[datetime] = current_time) -> datetime:
            return current_time[0]

        registry = _policy_registry(
            DurableJournal(case_path / "policy.jsonl"),
            _Authority(*authority._records.values(), successor_authority),  # noqa: SLF001
            clock=clock,
        )
        registry.admit(policy, actor="authority", now=NOW)
        storage = _MutatingPresignStorage()
        display = ExternalDisplayArtifactStore(
            DurableJournal(case_path / "display.jsonl"),
            policy_registry=registry,
            storage=storage,
            clock=clock,
        )
        queue = ExternalArtifactInspectionStore(
            DurableJournal(case_path / "inspection.jsonl"),
            policy_registry=registry,
            external_reconstruction=_FixtureIngress(),
            storage=storage,
            display_store=display,
            clock=clock,
        )
        issued = queue.issue_after_seal(subject(), now=NOW)
        assert issued.request is not None
        first = queue.claim(
            issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW
        )
        assert first.fence is not None
        accepted = report(request_id=issued.request.request_id, policy=policy)
        assert (
            queue.record_report(issued.request.request_id, first.fence, accepted, now=NOW).verdict
            == "REPORTED"
        )
        current_time[0] = NOW + timedelta(seconds=5)
        resumed = queue.claim(
            issued.request.request_id,
            LeaseFence(WORKER_B, ACQUISITION_B, 0),
            now=current_time[0],
        )
        assert resumed.fence is not None

        if scenario == "expiry":
            storage.mutate = (
                lambda current_time=current_time: current_time.__setitem__(
                    0, NOW + timedelta(seconds=10)
                )
            )
        elif scenario == "takeover":

            def _takeover(
                current_time: list[datetime] = current_time,
                queue: ExternalArtifactInspectionStore = queue,
                request_id: str = issued.request.request_id,
            ) -> None:
                current_time[0] = NOW + timedelta(seconds=9)
                successor = queue.claim(
                    request_id,
                    LeaseFence(WORKER_A, ACQUISITION_C, 0),
                    now=current_time[0],
                )
                assert successor.fence is not None and successor.fence.lease_generation == 3

            storage.mutate = _takeover
        elif scenario == "revocation":
            def _revoke(
                registry: ExternalValidationPolicyRegistry = registry,
                policy: ExternalValidationPolicyV1 = policy,
                current_time: list[datetime] = current_time,
            ) -> None:
                registry.revoke(
                    policy.policy_id, policy.version, actor="authority", now=current_time[0]
                )

            storage.mutate = _revoke
        elif scenario == "supersession":

            def _supersede(
                registry: ExternalValidationPolicyRegistry = registry,
                successor: ExternalValidationPolicyV1 = successor,
                policy: ExternalValidationPolicyV1 = policy,
                current_time: list[datetime] = current_time,
            ) -> None:
                assert registry.admit(successor, actor="authority", now=current_time[0]).status == (
                    "ADMITTED"
                )
                assert (
                    registry.supersede(
                        policy.policy_id,
                        policy.version,
                        successor.policy_id,
                        successor.version,
                        actor="authority",
                        now=current_time[0],
                    ).status
                    == "SUPERSEDED"
                )

            storage.mutate = _supersede
        else:

            def _complete_display(
                display: ExternalDisplayArtifactStore = display,
                request_id: str = issued.request.request_id,
                fence: LeaseFence = resumed.fence,
                current_time: list[datetime] = current_time,
            ) -> None:
                assert (
                    display.record_failure(
                        request_id,
                        fence,
                        "TRANSIENT_UNRECOGNIZED_BY_POLICY",
                        now=current_time[0],
                    ).verdict
                    is DisplayArtifactVerdict.RETRY_EXHAUSTED
                )

            storage.mutate = _complete_display

        result = queue.input_for(issued.request.request_id, resumed.fence)

        assert storage.calls == 1
        assert result.verdict == expected_verdict[scenario]
        assert result.artifacts == ()
        assert result.accepted_report is None


def test_display_input_rejects_before_mint_and_storage_failure_hides_source(
    tmp_path: Path,
) -> None:
    """Stale, revoked, finished, and storage-failed display work yields no source capability."""

    class _CountingStorage(SyntheticStorage):
        def __init__(self, *, unavailable: bool = False) -> None:
            super().__init__()
            self.calls = 0
            self.unavailable = unavailable

        def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
            self.calls += 1
            if self.unavailable:
                raise EvidenceStorageError("synthetic presign outage")
            return super().presigned_get(object_key, ttl=ttl)

    current_time = [NOW]
    policy, authority = _bound_policy()
    registry = _policy_registry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority,
        clock=lambda: current_time[0],
    )
    registry.admit(policy, actor="authority", now=NOW)
    storage = _CountingStorage()
    display = ExternalDisplayArtifactStore(
        DurableJournal(tmp_path / "display.jsonl"),
        policy_registry=registry,
        storage=storage,
        clock=lambda: current_time[0],
    )
    queue = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "inspection.jsonl"),
        policy_registry=registry,
        external_reconstruction=_FixtureIngress(),
        storage=storage,
        display_store=display,
        clock=lambda: current_time[0],
    )
    issued = queue.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    first = queue.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert first.fence is not None
    accepted = report(request_id=issued.request.request_id, policy=policy)
    assert (
        queue.record_report(issued.request.request_id, first.fence, accepted, now=NOW).verdict
        == "REPORTED"
    )
    current_time[0] = NOW + timedelta(seconds=5)
    resumed = queue.claim(
        issued.request.request_id,
        LeaseFence(WORKER_B, ACQUISITION_B, 0),
        now=current_time[0],
    )
    assert resumed.fence is not None

    stale = queue.input_for(issued.request.request_id, first.fence)
    assert stale.verdict == "LEASE_FENCE_REJECTED"
    assert stale.artifacts == ()
    assert storage.calls == 0

    storage.unavailable = True
    unavailable = queue.input_for(issued.request.request_id, resumed.fence)
    assert unavailable.verdict == "STORAGE_UNAVAILABLE"
    assert unavailable.artifacts == ()
    assert unavailable.accepted_report is None
    assert storage.calls == 1

    storage.unavailable = False
    assert (
        display.record_failure(
            issued.request.request_id,
            resumed.fence,
            "TRANSIENT_UNRECOGNIZED_BY_POLICY",
            now=current_time[0],
        ).verdict
        is DisplayArtifactVerdict.RETRY_EXHAUSTED
    )
    finished = queue.input_for(issued.request.request_id, resumed.fence)
    assert finished.verdict == "NOT_FOUND"
    assert finished.artifacts == ()
    assert storage.calls == 1

    registry.revoke(policy.policy_id, policy.version, actor="authority", now=current_time[0])
    revoked = queue.input_for(issued.request.request_id, resumed.fence)
    assert revoked.verdict == "POLICY_UNAVAILABLE"
    assert revoked.artifacts == ()
    assert storage.calls == 1


def test_display_input_rejects_superseded_policy_before_presigning(tmp_path: Path) -> None:
    """A replaced DISPLAY policy cannot mint even one source GET capability."""

    class _CountingStorage(SyntheticStorage):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
            self.calls += 1
            return super().presigned_get(object_key, ttl=ttl)

    current_time = [NOW]
    policy, authority = _bound_policy()
    successor_template = policy_template().model_copy(
        update={"policy_id": "policy-2", "version": 2, "policy_digest": None}, deep=True
    )
    successor_authority = PolicyAuthorityRecord(
        policy_id=successor_template.policy_id,
        policy_version=successor_template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(successor_template),
        permitted_subjects=(subject(),),
        permitted_uses=("INSPECTION", "DISPLAY"),
        authorized_actor_ids=("authority",),
        active_from=NOW - timedelta(minutes=1),
        active_until=NOW + timedelta(minutes=1),
        synthetic_test_only=True,
    ).sealed()
    successor = successor_template.model_copy(
        update={"authority_record_digest": successor_authority.digest, "policy_digest": None},
        deep=True,
    ).sealed()
    registry = _policy_registry(
        DurableJournal(tmp_path / "policy.jsonl"),
        _Authority(*authority._records.values(), successor_authority),  # noqa: SLF001
        clock=lambda: current_time[0],
    )
    registry.admit(policy, actor="authority", now=NOW)
    storage = _CountingStorage()
    display = ExternalDisplayArtifactStore(
        DurableJournal(tmp_path / "display.jsonl"),
        policy_registry=registry,
        storage=storage,
        clock=lambda: current_time[0],
    )
    queue = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "inspection.jsonl"),
        policy_registry=registry,
        external_reconstruction=_FixtureIngress(),
        storage=storage,
        display_store=display,
        clock=lambda: current_time[0],
    )
    issued = queue.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    initial = queue.claim(
        issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW
    )
    assert initial.fence is not None
    assert (
        queue.record_report(
            issued.request.request_id,
            initial.fence,
            report(request_id=issued.request.request_id, policy=policy),
            now=NOW,
        ).verdict
        == "REPORTED"
    )
    current_time[0] = NOW + timedelta(seconds=5)
    resumed = queue.claim(
        issued.request.request_id,
        LeaseFence(WORKER_B, ACQUISITION_B, 0),
        now=current_time[0],
    )
    assert resumed.fence is not None
    assert registry.admit(successor, actor="authority", now=current_time[0]).status == "ADMITTED"
    assert (
        registry.supersede(
            policy.policy_id,
            policy.version,
            successor.policy_id,
            successor.version,
            actor="authority",
            now=current_time[0],
        ).status
        == "SUPERSEDED"
    )

    result = queue.input_for(issued.request.request_id, resumed.fence)

    assert result.verdict == "POLICY_UNAVAILABLE"
    assert result.artifacts == ()
    assert result.accepted_report is None
    assert storage.calls == 0


def test_reported_display_remains_discoverable_when_enqueue_crashes(tmp_path: Path) -> None:
    """A failed second-journal enqueue cannot relabel an immutable report COMPLETE."""
    policy, authority = _bound_policy()
    registry = _policy_registry(
        DurableJournal(tmp_path / "policy.jsonl"), authority, clock=lambda: NOW
    )
    registry.admit(policy, actor="authority", now=NOW)
    display = _FailOnceDisplayStore(
        DurableJournal(tmp_path / "display.jsonl"),
        policy_registry=registry,
        storage=SyntheticStorage(),
        clock=lambda: NOW,
    )
    queue = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "inspection.jsonl"),
        policy_registry=registry,
        external_reconstruction=_FixtureIngress(),
        display_store=display,
        clock=lambda: NOW + timedelta(seconds=5),
    )
    issued = queue.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    initial = queue.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert initial.fence is not None
    accepted = report(request_id=issued.request.request_id, policy=policy)

    recorded = queue.record_report(issued.request.request_id, initial.fence, accepted, now=NOW)

    assert recorded.phase is not None and recorded.phase.value == "DISPLAY"
    assert queue.list_pending(1)[0].phase.value == "DISPLAY"
    successor = queue.claim(
        issued.request.request_id,
        LeaseFence(WORKER_B, ACQUISITION_B, 0),
        now=NOW + timedelta(seconds=5),
    )
    assert successor.verdict == "LEASED" and successor.phase is not None
    assert successor.phase is InspectionPhase.DISPLAY
    assert successor.fence is not None
    display_input = queue.input_for(issued.request.request_id, successor.fence)
    assert display_input.phase is not None and display_input.phase.value == "DISPLAY"
    assert display_input.accepted_report == accepted
    assert (
        queue.heartbeat(
            issued.request.request_id, successor.fence, now=NOW + timedelta(seconds=5)
        ).phase
        is not None
    )
    assert (
        queue.heartbeat(
            issued.request.request_id, successor.fence, now=NOW + timedelta(seconds=5)
        )
        .phase
        is InspectionPhase.DISPLAY
    )
    assert (
        queue.record_report(
            issued.request.request_id,
            successor.fence,
            accepted,
            now=NOW + timedelta(seconds=5),
        )
        .phase
        is InspectionPhase.DISPLAY
    )
    queue.reconcile_sealed(now=NOW + timedelta(seconds=5))
    assert display.phase_for(issued.request.request_id) is DisplayPhase.QUEUED


def test_display_failure_uses_the_aggregate_fenced_retry_budget(tmp_path: Path) -> None:
    """Display retry facts are closed, durable, and idempotent for one live lease."""
    policy, authority = _bound_policy()
    registry = _policy_registry(
        DurableJournal(tmp_path / "policy.jsonl"), authority, clock=lambda: NOW
    )
    registry.admit(policy, actor="authority", now=NOW)
    display = ExternalDisplayArtifactStore(
        DurableJournal(tmp_path / "display.jsonl"),
        policy_registry=registry,
        storage=SyntheticStorage(),
        clock=lambda: NOW + timedelta(seconds=5),
    )
    queue = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "inspection.jsonl"),
        policy_registry=registry,
        external_reconstruction=_FixtureIngress(),
        display_store=display,
        clock=lambda: NOW + timedelta(seconds=5),
    )
    issued = queue.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    initial = queue.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert initial.fence is not None
    assert (
        queue.record_report(
            issued.request.request_id,
            initial.fence,
            report(request_id=issued.request.request_id, policy=policy),
            now=NOW,
        ).phase
        is not None
    )
    display_lease = queue.claim(
        issued.request.request_id,
        LeaseFence(WORKER_B, ACQUISITION_B, 0),
        now=NOW + timedelta(seconds=5),
    )
    assert display_lease.fence is not None

    first = display.record_failure(
        issued.request.request_id,
        display_lease.fence,
        "TRANSIENT_STORAGE_UNAVAILABLE",
        now=NOW + timedelta(seconds=5),
    )
    event_count = len(tuple(display._journal.replay()))  # noqa: SLF001
    duplicate = display.record_failure(
        issued.request.request_id,
        display_lease.fence,
        "TRANSIENT_STORAGE_UNAVAILABLE",
        now=NOW + timedelta(seconds=5),
    )

    assert first.verdict is DisplayArtifactVerdict.QUEUED
    assert duplicate.verdict is DisplayArtifactVerdict.QUEUED
    assert len(tuple(display._journal.replay())) == event_count  # noqa: SLF001
    failure = tuple(display._journal.replay())[-1]  # noqa: SLF001
    assert failure["attemptCount"] == 2
    assert failure["retryRuleId"] == "TRANSIENT_IMMEDIATE_RETRY_V1"
    assert failure["nextEligibleAt"] == failure["recordedAt"]
    terminal = display.record_failure(
        issued.request.request_id,
        display_lease.fence,
        "TRANSIENT_UNRECOGNIZED_BY_POLICY",
        now=NOW + timedelta(seconds=5),
    )
    terminal_event = tuple(display._journal.replay())[-1]  # noqa: SLF001
    assert terminal.verdict is DisplayArtifactVerdict.RETRY_EXHAUSTED
    assert terminal_event["retryRuleId"] is None
    assert terminal_event["attemptCount"] == 2


def test_display_seal_rechecks_real_lease_and_policy_after_head(tmp_path: Path) -> None:
    """The nested commit guard rejects expiry or revocation that occurs during HEAD."""
    policy, authority = _bound_policy()
    current_time = [NOW]
    registry = _policy_registry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority,
        clock=lambda: current_time[0],
    )
    registry.admit(policy, actor="authority", now=NOW)
    run_number = [0]

    class _MutatingHeadStorage(SyntheticStorage):
        def __init__(self, mutate: Callable[[], object]) -> None:
            super().__init__()
            self._mutate = mutate

        def observe_object(self, object_key: str) -> ObjectStorageObservation:
            observed = super().observe_object(object_key)
            self._mutate()
            return observed

    def make_display(storage: SyntheticStorage) -> ExternalDisplayArtifactStore:
        run_number[0] += 1
        return ExternalDisplayArtifactStore(
            DurableJournal(tmp_path / f"display-{run_number[0]}.jsonl"),
            policy_registry=registry,
            storage=storage,
            clock=lambda: current_time[0],
        )

    def issue_and_resume(
        display: ExternalDisplayArtifactStore,
    ) -> tuple[ExternalArtifactInspectionStore, ExternalArtifactInspectionRequestV1, LeaseFence]:
        queue = ExternalArtifactInspectionStore(
            DurableJournal(tmp_path / f"inspection-{run_number[0]}.jsonl"),
            policy_registry=registry,
            external_reconstruction=_FixtureIngress(),
            display_store=display,
            clock=lambda: current_time[0],
        )
        issued = queue.issue_after_seal(subject(), now=NOW)
        assert issued.request is not None
        first = queue.claim(
            issued.request.request_id,
            LeaseFence(WORKER_A, ACQUISITION, 0),
            now=NOW,
        )
        assert first.fence is not None
        assert queue.record_report(
            issued.request.request_id,
            first.fence,
            report(request_id=issued.request.request_id, policy=policy),
            now=NOW,
        ).verdict == "REPORTED"
        current_time[0] = NOW + timedelta(seconds=5)
        resumed = queue.claim(
            issued.request.request_id,
            LeaseFence(WORKER_B, ACQUISITION_B, 0),
            now=current_time[0],
        )
        assert resumed.fence is not None
        return queue, issued.request, resumed.fence

    expiry_storage = _MutatingHeadStorage(
        lambda: current_time.__setitem__(0, NOW + timedelta(seconds=10))
    )
    expiry_display = make_display(expiry_storage)
    _expiry_queue, expiry_request, expiry_fence = issue_and_resume(expiry_display)
    expiry_declaration = SanitizedDisplayDeclarationV1(
        display_id="expiry-display",
        request_id=expiry_request.request_id,
        source_subject_digest=subject().canonical_digest(),
        source_report_digest=_sealed_digest(
            report(request_id=expiry_request.request_id, policy=policy).report_digest
        ),
        policy_digest=_sealed_digest(policy.policy_digest),
        inspector_build_digest=policy.parser_build_digest,
        declared_derivative_sha256=digest("9"),
        declared_derivative_size_bytes=123,
        declared_derivative_content_type="image/tiff",
    )
    assert expiry_display.grant(
        expiry_request.request_id, expiry_declaration, expiry_fence, now=NOW + timedelta(seconds=5)
    ).grant is not None
    assert expiry_storage.last_put_key is not None
    expiry_storage.objects[expiry_storage.last_put_key] = SyntheticObservation(
        expiry_storage.last_put_key, True, 123, digest("9"), "image/tiff"
    )
    assert expiry_display.seal(
        expiry_request.request_id, expiry_fence, now=NOW + timedelta(seconds=5)
    ).verdict is DisplayArtifactVerdict.LEASE_FENCE_REJECTED

    # A real successor claim while HEAD is in flight fences the prior worker.
    current_time[0] = NOW
    takeover_storage = _MutatingHeadStorage(lambda: None)
    takeover_display = make_display(takeover_storage)
    takeover_queue, takeover_request, takeover_fence = issue_and_resume(takeover_display)
    takeover_declaration = expiry_declaration.model_copy(
        update={
            "display_id": "takeover-display",
            "request_id": takeover_request.request_id,
            "source_report_digest": report(
                request_id=takeover_request.request_id, policy=policy
            ).report_digest,
            "declaration_digest": None,
        }
    )
    assert takeover_display.grant(
        takeover_request.request_id,
        takeover_declaration,
        takeover_fence,
        now=NOW + timedelta(seconds=5),
    ).grant is not None
    assert takeover_storage.last_put_key is not None
    takeover_storage.objects[takeover_storage.last_put_key] = SyntheticObservation(
        takeover_storage.last_put_key, True, 123, digest("9"), "image/tiff"
    )

    def claim_successor_during_head() -> None:
        current_time[0] = NOW + timedelta(seconds=9)
        successor = takeover_queue.claim(
            takeover_request.request_id,
            LeaseFence(WORKER_A, ACQUISITION_C, 0),
            now=current_time[0],
        )
        assert successor.fence is not None and successor.fence.lease_generation == 3

    takeover_storage._mutate = claim_successor_during_head  # noqa: SLF001 - I/O race seam.
    assert takeover_display.seal(
        takeover_request.request_id,
        takeover_fence,
        now=NOW + timedelta(seconds=5),
    ).verdict is DisplayArtifactVerdict.LEASE_FENCE_REJECTED

    # A fresh report/lease pair isolates policy revocation from expiry/takeover.
    current_time[0] = NOW
    def revoke_policy_during_head() -> object:
        return registry.revoke(
            policy.policy_id,
            policy.version,
            actor="authority",
            now=current_time[0],
        )

    revoke_storage = _MutatingHeadStorage(revoke_policy_during_head)
    revoke_display = make_display(revoke_storage)
    _revoke_queue, revoke_request, revoke_fence = issue_and_resume(revoke_display)
    revoke_declaration = expiry_declaration.model_copy(
        update={
            "display_id": "revoke-display",
            "request_id": revoke_request.request_id,
            "source_report_digest": report(
                request_id=revoke_request.request_id, policy=policy
            ).report_digest,
            "declaration_digest": None,
        }
    )
    assert revoke_display.grant(
        revoke_request.request_id, revoke_declaration, revoke_fence, now=NOW + timedelta(seconds=5)
    ).grant is not None
    assert revoke_storage.last_put_key is not None
    revoke_storage.objects[revoke_storage.last_put_key] = SyntheticObservation(
        revoke_storage.last_put_key, True, 123, digest("9"), "image/tiff"
    )
    assert revoke_display.seal(
        revoke_request.request_id, revoke_fence, now=NOW + timedelta(seconds=5)
    ).verdict is DisplayArtifactVerdict.LEASE_FENCE_REJECTED


def test_sealed_display_retry_rechecks_current_fence_after_restart(tmp_path: Path) -> None:
    """A receipt retry remains read-idempotent but never outlives its exact lease fence."""
    policy, authority = _bound_policy()
    current_time = [NOW]
    registry = _policy_registry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority,
        clock=lambda: current_time[0],
    )
    registry.admit(policy, actor="authority", now=NOW)
    inspection_path = tmp_path / "inspection.jsonl"
    display_path = tmp_path / "display.jsonl"
    storage = SyntheticStorage()
    display = ExternalDisplayArtifactStore(
        DurableJournal(display_path),
        policy_registry=registry,
        storage=storage,
        clock=lambda: current_time[0],
    )
    queue = ExternalArtifactInspectionStore(
        DurableJournal(inspection_path),
        policy_registry=registry,
        external_reconstruction=_FixtureIngress(),
        display_store=display,
        clock=lambda: current_time[0],
    )
    issued = queue.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    claimed = queue.claim(
        issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW
    )
    assert claimed.fence is not None
    retained = report(request_id=issued.request.request_id, policy=policy)
    assert queue.record_report(
        issued.request.request_id, claimed.fence, retained, now=NOW
    ).verdict == "REPORTED"
    declaration = SanitizedDisplayDeclarationV1(
        display_id="sealed-retry-display",
        request_id=issued.request.request_id,
        source_subject_digest=retained.subject_digest,
        source_report_digest=_sealed_digest(retained.report_digest),
        policy_digest=_sealed_digest(policy.policy_digest),
        inspector_build_digest=policy.parser_build_digest,
        declared_derivative_sha256=digest("9"),
        declared_derivative_size_bytes=123,
        declared_derivative_content_type="image/tiff",
    )
    assert display.grant(
        issued.request.request_id, declaration, claimed.fence, now=NOW
    ).grant is not None
    assert storage.last_put_key is not None
    storage.objects[storage.last_put_key] = SyntheticObservation(
        storage.last_put_key, True, 123, digest("9"), "image/tiff"
    )
    assert display.seal(issued.request.request_id, claimed.fence, now=NOW).verdict is (
        DisplayArtifactVerdict.SEALED
    )
    sealed_events = tuple(display._journal.replay())  # noqa: SLF001 - durable retry boundary.

    stale_generation = LeaseFence(WORKER_A, ACQUISITION, 999)
    assert display.seal(  # A forged/superseded generation cannot read a receipt as work success.
        issued.request.request_id, stale_generation, now=NOW
    ).verdict is DisplayArtifactVerdict.LEASE_FENCE_REJECTED
    current_time[0] = NOW + timedelta(seconds=5)
    assert display.seal(  # The formerly exact fence expires after the receipt is sealed.
        issued.request.request_id, claimed.fence, now=current_time[0]
    ).verdict is DisplayArtifactVerdict.LEASE_FENCE_REJECTED
    assert tuple(display._journal.replay()) == sealed_events  # noqa: SLF001

    queue._journal.close()  # noqa: SLF001 - process-boundary replay assertion.
    display._journal.close()  # noqa: SLF001 - process-boundary replay assertion.
    restarted_display = ExternalDisplayArtifactStore(
        DurableJournal(display_path),
        policy_registry=registry,
        storage=storage,
        clock=lambda: current_time[0],
    )
    restarted_queue = ExternalArtifactInspectionStore(
        DurableJournal(inspection_path),
        policy_registry=registry,
        external_reconstruction=_FixtureIngress(),
        display_store=restarted_display,
        clock=lambda: current_time[0],
    )
    assert restarted_display.seal(
        issued.request.request_id, stale_generation, now=current_time[0]
    ).verdict is DisplayArtifactVerdict.LEASE_FENCE_REJECTED
    assert restarted_display.seal(
        issued.request.request_id, claimed.fence, now=current_time[0]
    ).verdict is DisplayArtifactVerdict.LEASE_FENCE_REJECTED
    assert tuple(restarted_display._journal.replay()) == sealed_events  # noqa: SLF001
    assert restarted_queue.public_snapshot(subject()).phase is InspectionPhase.COMPLETE


def test_actual_ingress_seal_exposes_snapshot_and_post_commit_callback(tmp_path: Path) -> None:
    """A synthetic ingress shape must not substitute for the real register/seal boundary."""
    sites = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    frame = SiteFrame(
        crs="EPSG:5186", vertical_datum="KNGeoid2018", unit="meter", transform_version="1.0.0"
    )
    sites.register(
        "site-1", "Site", frame, organization_id="organization-1", actor="fixture", now=NOW
    )
    orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            sites.get_scoped(site_id, organization_id) is not None
        ),
    )
    order = orders.create_work_order(
        organization_id="organization-1",
        site_id="site-1",
        name="External",
        work_area_ids=["wa"],
        schedule_id=None,
        actor="fixture",
        now=NOW,
    )
    ingress = ExternalReconstructionStore(DurableJournal(tmp_path / "ingress.jsonl"))
    payload = {
        "submissionId": "submission-1",
        "revision": 1,
        "organizationId": "organization-1",
        "siteId": "site-1",
        "observationEpochId": "obs-epoch-"
        + hashlib.sha256(
            f"organization-1\0{order.work_order_id}\0{order.cycle_number}".encode()
        ).hexdigest()[:24],
        "submittedAt": "2026-09-07T00:00:00Z",
        "submittedBy": "operator-1",
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "softwareName": "Mapper",
            "softwareVersion": "1",
            "buildIdentifier": None,
            "producerRunIdentifier": None,
            "configurationDigest": None,
            "completedAt": None,
        },
        "inputDeclaration": {
            "rawMediaStoredByKsi": False,
            "originalRetentionLocus": "customer_workstation",
            "localInputManifestDigest": None,
            "imageCount": None,
            "captureStartedAt": None,
            "captureEndedAt": None,
        },
        "artifacts": [
            {
                "artifactId": "ortho",
                "kind": "ortho",
                "fileName": "ortho.tif",
                "format": "GeoTIFF",
                "contentType": "application/octet-stream",
                "declaredSha256": "c" * 64,
                "declaredSizeBytes": 12,
                "declaredCrs": None,
                "declaredVerticalReference": None,
                "declaredGsdM": None,
            }
        ],
    }
    payload["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(payload)
    registered = ingress.register(
        ExternalReconstructionSubmissionV1.model_validate(payload),
        work_order=order,
        registered_by="operator-1",
        now=NOW,
    )
    assert registered.revision is not None
    storage = SyntheticStorage()
    for _artifact_id, object_key in registered.revision.bindings:
        storage.objects[object_key] = SyntheticObservation(
            object_key, True, 12, "sha256:" + "c" * 64, "application/octet-stream"
        )
    expected_manifest = ExternalReconstructionManifestV1.from_submission(
        registered.revision.submission,
        manifest_id="external-manifest-"
        + hashlib.sha256(f"{order.work_order_id}:submission-1:1".encode()).hexdigest()[:32],
        observed_at=NOW,
        observed_by_service="ksi-core",
        organization_id="organization-1",
        site_id="site-1",
        observation_epoch_id=registered.revision.observation_epoch_id,
        entries=tuple(
            ExternalReconstructionManifestEntryV1(
                artifact_id=artifact_id,
                kind=next(
                    artifact.kind
                    for artifact in registered.revision.submission.artifacts
                    if artifact.artifact_id == artifact_id
                ),
                object_key=object_key,
                observed_sha256="c" * 64,
                observed_size_bytes=12,
                observed_content_type="application/octet-stream",
            )
            for artifact_id, object_key in registered.revision.bindings
        ),
    )
    assert registered.revision.submission.submission_digest is not None
    assert expected_manifest.manifest_digest is not None
    real_subject = SealedExternalSubjectV1(
        organization_id=registered.revision.submission.organization_id,
        site_id=registered.revision.submission.site_id,
        work_order_id=registered.revision.work_order_id,
        submission_id=registered.revision.submission.submission_id,
        revision=registered.revision.submission.revision,
        submission_digest=registered.revision.submission.submission_digest,
        manifest_digest=expected_manifest.manifest_digest,
    )
    queue, _policy = _stores(
        tmp_path / "queue", active=True, permitted_subject=real_subject, ingress=ingress
    )
    calls: list[object] = []
    ingress.bind_seal_listener(lambda revision, _now: calls.append(revision))
    ingress.bind_seal_listener(lambda _revision, callback_now: queue.reconcile_sealed(callback_now))

    def _failed_listener(_revision: object, _callback_now: object) -> None:
        raise RuntimeError("listener failure is reconciled, not relabelled")

    ingress.bind_seal_listener(_failed_listener)

    sealed = ingress.seal(
        order.work_order_id,
        "submission-1",
        1,
        organization_id="organization-1",
        site_id="site-1",
        storage=storage,
        now=NOW,
    )
    assert sealed.verdict == "SEALED"
    snapshot = ingress.sealed_revisions_snapshot()
    assert len(snapshot) == len(calls) == 1
    assert queue.issue_after_seal(real_subject, now=NOW).verdict == "IDEMPOTENT"
    assert queue.reconcile_sealed(now=NOW) == 0
