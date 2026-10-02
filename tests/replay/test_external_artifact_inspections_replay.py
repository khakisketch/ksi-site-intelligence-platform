"""Replay hardening for the durable external-artifact inspection queue."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_artifact_inspections import (
    ExternalArtifactInspectionRecoveryError,
    ExternalArtifactInspectionStore,
    InspectionPhase,
    SealedExternalReconstructionSnapshotPort,
)
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_reconstruction import ExternalReconstructionRevision
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from ksi_core.leasing import LeaseFence
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ExternalValidationPolicyV1
from support.external_artifact_inspection_fixtures import (
    ACQUISITION,
    ACQUISITION_B,
    NOW,
    WORKER_A,
    WORKER_B,
    policy_template,
    report,
    sealed_manifest,
    sealed_submission,
    subject,
)


class _Authority(PolicyAuthorityPort):
    def __init__(self, record: PolicyAuthorityRecord) -> None:
        self._record = record
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
        return self._record if authority_record_digest == self._record.digest else None

    def resolve_historical(
        self, authority_record_digest: str, at: datetime
    ) -> PolicyAuthorityRecord | None:
        return (
            self._record
            if authority_record_digest == self._record.digest and self._record.is_active_at(at)
            else None
        )

    def is_current(self, authority: PolicyAuthorityRecord, now: datetime) -> bool:
        return authority == self._record and self._record.is_active_at(now)


class _Ingress(SealedExternalReconstructionSnapshotPort):
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


class _MissingIngress(SealedExternalReconstructionSnapshotPort):
    """Models an unavailable backing sealed revision during journal recovery."""

    def sealed_revisions_snapshot(self) -> tuple[ExternalReconstructionRevision, ...]:
        return ()


def _registry(
    tmp_path: Path, *, permitted_uses: tuple[str, ...] = ("INSPECTION", "DISPLAY")
) -> tuple[ExternalValidationPolicyRegistry, ExternalValidationPolicyV1]:
    template = policy_template()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(subject(),),
        permitted_uses=permitted_uses,
        authorized_actor_ids=("authority",),
        active_from=NOW - timedelta(minutes=1),
        active_until=NOW + timedelta(minutes=1),
        synthetic_test_only=True,
    ).sealed()
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    policy_authority = _Authority(authority)
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority_port=policy_authority,
        authority_currentness_port=policy_authority.bind(coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    registry.admit(policy, actor="authority", now=NOW)
    return registry, policy


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("objectKey", "external-reconstruction/v1/other-tenant-ortho"),
        ("observedSha256", "sha256:" + "d" * 64),
        ("kind", "dsm"),
        ("observedSizeBytes", 13),
        ("contentType", "image/tiff"),
    ),
)
def test_replay_rejects_issue_artifact_not_backed_by_sealed_ingress(
    tmp_path: Path, field: str, replacement: object
) -> None:
    """A digest-valid issue cannot substitute any sealed ingress artifact binding."""
    registry, _policy = _registry(tmp_path)
    journal_path = tmp_path / "inspection.jsonl"
    store = ExternalArtifactInspectionStore(
        DurableJournal(journal_path),
        policy_registry=registry,
        external_reconstruction=_Ingress(),
        clock=lambda: NOW,
    )
    assert store.issue_after_seal(subject(), now=NOW).verdict == "ISSUED"

    store._journal.close()  # noqa: SLF001 - close before deliberate replay corruption.
    events = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    events[0]["artifacts"][0][field] = replacement
    events[0]["eventDigest"] = "sha256:" + hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in events[0].items() if key != "eventDigest"}
        )
    ).hexdigest()
    journal_path.write_text(
        "\n".join(json.dumps(event, separators=(",", ":"), sort_keys=True) for event in events)
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ExternalArtifactInspectionRecoveryError):
        ExternalArtifactInspectionStore(
            DurableJournal(journal_path),
            policy_registry=registry,
            external_reconstruction=_Ingress(),
            clock=lambda: NOW,
        )


def test_replay_rejects_issue_without_its_backing_sealed_revision(tmp_path: Path) -> None:
    """Recovery must fail closed if an issued subject is no longer in the public snapshot."""
    registry, _policy = _registry(tmp_path)
    journal_path = tmp_path / "inspection.jsonl"
    store = ExternalArtifactInspectionStore(
        DurableJournal(journal_path),
        policy_registry=registry,
        external_reconstruction=_Ingress(),
        clock=lambda: NOW,
    )
    assert store.issue_after_seal(subject(), now=NOW).verdict == "ISSUED"
    store._journal.close()  # noqa: SLF001 - process-boundary recovery assertion.

    with pytest.raises(ExternalArtifactInspectionRecoveryError):
        ExternalArtifactInspectionStore(
            DurableJournal(journal_path),
            policy_registry=registry,
            external_reconstruction=_MissingIngress(),
            clock=lambda: NOW,
        )


def test_inspection_restart_restores_lease_and_rejects_reordered_events(tmp_path: Path) -> None:
    """A real journal must retain a lease but reject a syntactically valid bad order."""
    registry, _policy = _registry(tmp_path)
    journal_path = tmp_path / "inspection.jsonl"
    store = ExternalArtifactInspectionStore(
        DurableJournal(journal_path),
        policy_registry=registry,
        external_reconstruction=_Ingress(),
        clock=lambda: NOW,
    )
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    claim = store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert claim.fence is not None

    store._journal.close()  # noqa: SLF001 - process-boundary simulation.
    restarted = ExternalArtifactInspectionStore(
        DurableJournal(journal_path),
        policy_registry=registry,
        external_reconstruction=_Ingress(),
        clock=lambda: NOW,
    )
    assert (
        restarted.claim(
            issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW
        ).fence
        == claim.fence
    )
    assert (
        restarted.claim(
            issued.request.request_id,
            LeaseFence(WORKER_A, ACQUISITION, 0),
            now=NOW + timedelta(seconds=5),
        ).verdict
        == "LEASE_FENCE_REJECTED"
    )
    assert (
        restarted.claim(
            issued.request.request_id,
            LeaseFence(WORKER_B, ACQUISITION_B, 0),
            now=NOW + timedelta(seconds=5),
        ).fence
        is not None
    )

    restarted._journal.close()  # noqa: SLF001 - close before deliberate on-disk tamper.
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    journal_path.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
    with pytest.raises(ExternalArtifactInspectionRecoveryError):
        ExternalArtifactInspectionStore(
            DurableJournal(journal_path),
            policy_registry=registry,
            external_reconstruction=_Ingress(),
            clock=lambda: NOW,
        )


@pytest.mark.parametrize("renew", [False, True], ids=["claim", "heartbeat"])
def test_replay_rejects_digest_valid_lease_beyond_absolute_deadline(
    tmp_path: Path, renew: bool
) -> None:
    registry, _policy = _registry(tmp_path)
    journal_path = tmp_path / "inspection.jsonl"
    store = ExternalArtifactInspectionStore(
        DurableJournal(journal_path),
        policy_registry=registry,
        external_reconstruction=_Ingress(),
        clock=lambda: NOW,
    )
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    claim = store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert claim.fence is not None
    if renew:
        assert store.heartbeat(
            issued.request.request_id, claim.fence, now=NOW + timedelta(seconds=1)
        ).verdict == "LEASED"
    store._journal.close()  # noqa: SLF001 - process boundary before deliberate corruption.
    events = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    events[-1]["leaseExpiresAt"] = (NOW + timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    events[-1]["eventDigest"] = "sha256:" + hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in events[-1].items() if key != "eventDigest"}
        )
    ).hexdigest()
    journal_path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ExternalArtifactInspectionRecoveryError):
        ExternalArtifactInspectionStore(
            DurableJournal(journal_path),
            policy_registry=registry,
            external_reconstruction=_Ingress(),
            clock=lambda: NOW,
        )


@pytest.mark.parametrize(
    ("permitted_uses", "tampered_display_required"),
    (
        (("INSPECTION", "DISPLAY"), False),
        (("INSPECTION",), True),
    ),
)
def test_inspection_replay_rejects_tampered_historical_display_obligation(
    tmp_path: Path, permitted_uses: tuple[str, ...], tampered_display_required: bool
) -> None:
    """A report event cannot replace its pinned historical display capability."""
    registry, policy = _registry(tmp_path, permitted_uses=permitted_uses)
    journal_path = tmp_path / "inspection.jsonl"
    store = ExternalArtifactInspectionStore(
        DurableJournal(journal_path),
        policy_registry=registry,
        external_reconstruction=_Ingress(),
        clock=lambda: NOW,
    )
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    claim = store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert claim.fence is not None
    assert store.record_report(
        issued.request.request_id,
        claim.fence,
        report(request_id=issued.request.request_id, policy=policy),
        now=NOW,
    ).verdict == "REPORTED"

    store._journal.close()  # noqa: SLF001 - close before deliberate replay corruption.
    events = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    events[-1]["displayRequired"] = tampered_display_required
    events[-1]["eventDigest"] = "sha256:" + hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in events[-1].items() if key != "eventDigest"}
        )
    ).hexdigest()
    journal_path.write_text(
        "\n".join(
            json.dumps(event, separators=(",", ":"), sort_keys=True) for event in events
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ExternalArtifactInspectionRecoveryError):
        ExternalArtifactInspectionStore(
            DurableJournal(journal_path),
            policy_registry=registry,
            external_reconstruction=_Ingress(),
            clock=lambda: NOW,
        )


def test_replay_preserves_report_time_display_obligation_after_same_time_revocation(
    tmp_path: Path,
) -> None:
    """A later lifecycle state cannot rewrite a valid report's historical obligation."""
    registry, policy = _registry(tmp_path)
    journal_path = tmp_path / "inspection.jsonl"
    store = ExternalArtifactInspectionStore(
        DurableJournal(journal_path),
        policy_registry=registry,
        external_reconstruction=_Ingress(),
        clock=lambda: NOW,
    )
    issued = store.issue_after_seal(subject(), now=NOW)
    assert issued.request is not None
    claim = store.claim(issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW)
    assert claim.fence is not None
    assert store.record_report(
        issued.request.request_id,
        claim.fence,
        report(request_id=issued.request.request_id, policy=policy),
        now=NOW,
    ).phase is InspectionPhase.DISPLAY
    revoked = registry.revoke(policy.policy_id, policy.version, actor="authority", now=NOW)
    assert revoked.status.value == "REVOKED"

    store._journal.close()  # noqa: SLF001 - process-boundary replay assertion.
    restarted = ExternalArtifactInspectionStore(
        DurableJournal(journal_path),
        policy_registry=registry,
        external_reconstruction=_Ingress(),
        clock=lambda: NOW,
    )
    snapshot = restarted.public_snapshot_bounded(
        subject(), max_records=128, max_policy_records=64
    )
    assert snapshot.report is not None
    assert snapshot.report.report_digest == report(
        request_id=issued.request.request_id, policy=policy
    ).report_digest
    assert restarted._records[issued.request.request_id].display_required  # noqa: SLF001
