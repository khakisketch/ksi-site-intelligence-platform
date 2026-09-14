"""Replay hardening for Core's external-validation policy registry."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRecoveryError,
    ExternalValidationPolicyRegistry,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
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


def _subject() -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="organization-1",
        site_id="site-1",
        work_order_id="work-order-1",
        submission_id="submission-1",
        revision=1,
        submission_digest=_digest("a"),
        manifest_digest=_digest("b"),
    )


def _policy_template(
    *, policy_id: str = "policy-1", version: int = 1
) -> ExternalValidationPolicyV1:
    envelope = ResourceEnvelopeV1(
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
    return ExternalValidationPolicyV1(
        policy_id=policy_id,
        version=version,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=_digest("d"),
        grammar_digest=_digest("e"),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=_digest("f"),
        inspection_rule_ids=("synthetic-test-rule",),
        evidence_rule_ids=("synthetic-test-rule",),
        compatibility_mapping_digests=(),
        synthetic_test_only=True,
    ).sealed()


def _authority(
    policy: ExternalValidationPolicyV1,
    *,
    actor_ids: tuple[str, ...] = ("authority",),
) -> PolicyAuthorityRecord:
    return PolicyAuthorityRecord(
        policy_id=policy.policy_id,
        policy_version=policy.version,
        authorized_policy_body_digest=authorized_policy_body_digest(policy),
        permitted_subjects=(_subject(),),
        permitted_uses=("INSPECTION", "DISPLAY"),
        authorized_actor_ids=actor_ids,
        active_from=NOW - timedelta(minutes=1),
        active_until=NOW + timedelta(minutes=1),
        synthetic_test_only=True,
    ).sealed()


def _bound_policy(
    *,
    policy_id: str = "policy-1",
    version: int = 1,
    actor_ids: tuple[str, ...] = ("authority",),
) -> tuple[ExternalValidationPolicyV1, PolicyAuthorityRecord]:
    template = _policy_template(policy_id=policy_id, version=version)
    authority = _authority(template, actor_ids=actor_ids)
    assert authority.digest is not None
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    assert authority.authorized_policy_body_digest == authorized_policy_body_digest(policy)
    return policy, authority


class FakePolicyAuthorityPort(PolicyAuthorityPort):
    """Test-only injected authority; production has no equivalent record source yet."""

    def __init__(self, *records: PolicyAuthorityRecord) -> None:
        self._records: dict[str, PolicyAuthorityRecord] = {}
        self._coordinator: ExternalAuthorityCurrentnessCoordinator | None = None
        for record in records:
            assert record.digest is not None
            self._records[record.digest] = record

    def resolve(self, authority_record_digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        return self._records.get(authority_record_digest)

    def resolve_historical(
        self, authority_record_digest: str, at: datetime
    ) -> PolicyAuthorityRecord | None:
        record = self._records.get(authority_record_digest)
        return record if record is not None and record.is_active_at(at) else None

    def bind(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> FakePolicyAuthorityPort:
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        assert self._coordinator is not None
        return self._coordinator

    def is_current(self, authority: PolicyAuthorityRecord, now: datetime) -> bool:
        return (
            authority.digest is not None
            and self._records.get(authority.digest) == authority
            and authority.is_active_at(now)
        )


def _registry(
    journal: DurableJournal, authority: FakePolicyAuthorityPort
) -> ExternalValidationPolicyRegistry:
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    return ExternalValidationPolicyRegistry(
        journal,
        authority_port=authority,
        authority_currentness_port=authority.bind(coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )


def _event_digest(event: dict[str, object]) -> str:
    body = {key: value for key, value in event.items() if key != "eventDigest"}
    return "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _seal_event(event: dict[str, object]) -> dict[str, object]:
    event["eventDigest"] = _event_digest(event)
    return event


def _authority_wire(record: PolicyAuthorityRecord) -> dict[str, object]:
    return record.event_payload()


def _admitted_event(
    policy: ExternalValidationPolicyV1,
    authority: PolicyAuthorityRecord,
    *,
    actor: str = "authority",
) -> dict[str, object]:
    return _seal_event({
        "kind": "external-validation-policy-admitted",
        "eventVersion": 1,
        "policy": policy.model_dump(by_alias=True, mode="json"),
        "policyDigest": policy.policy_digest,
        "policyId": policy.policy_id,
        "policyVersion": policy.version,
        "authorityRecordDigest": policy.authority_record_digest,
        "authority": _authority_wire(authority),
        "actor": actor,
        "occurredAt": "2026-09-07T00:00:00Z",
    })


def test_restart_retains_revocation_and_immutable_snapshot(tmp_path: Path) -> None:
    """Losing lifecycle state or rewriting a historical snapshot on restart would fail this test."""
    path = tmp_path / "policy.jsonl"
    policy, authority = _bound_policy()
    first_journal = DurableJournal(path)
    first = _registry(first_journal, FakePolicyAuthorityPort(authority))
    receipt = first.admit(policy, actor="authority", now=NOW)
    first.revoke(receipt.policy_id, receipt.version, actor="authority", now=NOW)
    first_journal.close()

    restarted = _registry(DurableJournal(path), FakePolicyAuthorityPort(authority))
    assert receipt.policy_digest is not None
    historical = restarted.resolve(receipt.policy_digest)

    assert historical.status is PolicySelectionStatus.REVOKED
    assert historical.policy is not None
    assert historical.policy.status == "ACTIVE"
    assert (
        restarted.select_for_inspection(_subject()).status
        is PolicySelectionStatus.INSPECTION_PENDING_POLICY
    )


def test_replay_refuses_active_policy_with_unlimited_envelope(tmp_path: Path) -> None:
    """Accepting an Infinity resource limit from a forged journal would fail this recovery gate."""
    policy, authority = _bound_policy()
    raw = _admitted_event(policy, authority)
    policy_wire = raw["policy"]
    assert isinstance(policy_wire, dict)
    envelope = policy_wire["resourceEnvelope"]
    assert isinstance(envelope, dict)
    envelope["maxCpuSeconds"] = 0.0
    envelope_digest_payload = {
        key: value for key, value in envelope.items() if key != "resourceEnvelopeDigest"
    }
    envelope["resourceEnvelopeDigest"] = "sha256:" + hashlib.sha256(
        canonical_json_bytes(envelope_digest_payload)
    ).hexdigest()
    policy_wire["resourceEnvelopeDigest"] = envelope["resourceEnvelopeDigest"]
    policy_digest_payload = {
        key: value for key, value in policy_wire.items() if key != "policyDigest"
    }
    policy_wire["policyDigest"] = "sha256:" + hashlib.sha256(
        canonical_json_bytes(policy_digest_payload)
    ).hexdigest()
    raw["policyDigest"] = policy_wire["policyDigest"]
    raw["eventDigest"] = _event_digest(raw)
    (tmp_path / "forged.jsonl").write_text(json.dumps(raw, allow_nan=True) + "\n", encoding="ascii")

    with pytest.raises(ExternalValidationPolicyRecoveryError):
        _registry(DurableJournal(tmp_path / "forged.jsonl"), FakePolicyAuthorityPort(authority))


def test_replay_refuses_recomputed_authority_not_in_trusted_history(tmp_path: Path) -> None:
    """A self-consistent forged mallory approval is not trusted merely because it hashes."""
    policy, trusted_authority = _bound_policy()
    forged_policy, forged_authority = _bound_policy(actor_ids=("mallory",))
    assert forged_policy.policy_digest != policy.policy_digest
    event = _admitted_event(forged_policy, forged_authority, actor="mallory")
    path = tmp_path / "forged-authority.jsonl"
    path.write_text(json.dumps(event) + "\n", encoding="ascii")
    journal = DurableJournal(path)

    with pytest.raises(ExternalValidationPolicyRecoveryError):
        _registry(journal, FakePolicyAuthorityPort(trusted_authority))

    assert journal.sealed_reason == "closed"


def test_replay_refuses_revoke_before_its_admission(tmp_path: Path) -> None:
    """Accepting an out-of-order lifecycle event would fail append-only replay ordering."""
    policy, authority = _bound_policy()
    event = _seal_event(
        {
            "kind": "external-validation-policy-revoked",
            "eventVersion": 1,
            "policyId": policy.policy_id,
            "policyVersion": policy.version,
            "policyDigest": policy.policy_digest,
            "actor": "authority",
            "occurredAt": "2026-09-07T00:00:00Z",
        }
    )
    (tmp_path / "unordered.jsonl").write_text(
        json.dumps(event) + "\n",
        encoding="ascii",
    )

    with pytest.raises(ExternalValidationPolicyRecoveryError):
        _registry(
            DurableJournal(tmp_path / "unordered.jsonl"),
            FakePolicyAuthorityPort(authority),
        )


def test_replay_refuses_extra_admission_field(tmp_path: Path) -> None:
    """Ignoring undeclared journal fields would fail exact-field replay validation."""
    policy, authority = _bound_policy()
    event = _admitted_event(policy, authority)
    event["unreviewedOverride"] = True
    (tmp_path / "extra.jsonl").write_text(json.dumps(event) + "\n", encoding="ascii")

    with pytest.raises(ExternalValidationPolicyRecoveryError):
        _registry(
            DurableJournal(tmp_path / "extra.jsonl"),
            FakePolicyAuthorityPort(authority),
        )


def test_replay_refuses_mutated_event_with_stale_canonical_digest(tmp_path: Path) -> None:
    """Ignoring eventDigest would permit an append-only admission field to be rewritten."""
    policy, authority = _bound_policy()
    event = _admitted_event(policy, authority)
    event["actor"] = "another-authority"
    path = tmp_path / "stale-digest.jsonl"
    path.write_text(json.dumps(event) + "\n", encoding="ascii")
    journal = DurableJournal(path)

    with pytest.raises(ExternalValidationPolicyRecoveryError):
        _registry(journal, FakePolicyAuthorityPort(authority))

    assert journal.sealed_reason == "closed"


def test_replay_refuses_unknown_event_kind_even_with_recomputed_digest(tmp_path: Path) -> None:
    """Skipping an unknown record would turn a dedicated policy journal into a fail-open stream."""
    policy, authority = _bound_policy()
    event = _admitted_event(policy, authority)
    event["kind"] = "external-validation-policy-unknown"
    event["eventDigest"] = _event_digest(event)
    (tmp_path / "unknown-kind.jsonl").write_text(json.dumps(event) + "\n", encoding="ascii")

    with pytest.raises(ExternalValidationPolicyRecoveryError):
        _registry(
            DurableJournal(tmp_path / "unknown-kind.jsonl"),
            FakePolicyAuthorityPort(authority),
        )


def test_replay_refuses_bool_event_version_even_with_recomputed_digest(tmp_path: Path) -> None:
    """Treating Python True as lifecycle version 1 would weaken exact event-version replay."""
    policy, authority = _bound_policy()
    event = _admitted_event(policy, authority)
    event["eventVersion"] = True
    event["eventDigest"] = _event_digest(event)
    (tmp_path / "bool-version.jsonl").write_text(json.dumps(event) + "\n", encoding="ascii")

    with pytest.raises(ExternalValidationPolicyRecoveryError):
        _registry(
            DurableJournal(tmp_path / "bool-version.jsonl"),
            FakePolicyAuthorityPort(authority),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (("policyVersion", True), ("authority.policyVersion", 1.0)),
)
def test_replay_refuses_non_integer_policy_versions_even_with_recomputed_digest(
    tmp_path: Path, field: str, value: bool | float
) -> None:
    """Every admission identity version is strict even when its event digest is rebuilt."""
    policy, authority = _bound_policy()
    event = _admitted_event(policy, authority)
    if field == "policyVersion":
        event["policyVersion"] = value
    else:
        authority_wire = event["authority"]
        assert isinstance(authority_wire, dict)
        authority_wire["policyVersion"] = value
    event["eventDigest"] = _event_digest(event)
    path = tmp_path / f"invalid-{field}.jsonl"
    path.write_text(json.dumps(event) + "\n", encoding="ascii")

    with pytest.raises(ExternalValidationPolicyRecoveryError):
        _registry(DurableJournal(path), FakePolicyAuthorityPort(authority))


def test_replay_refuses_bool_successor_policy_version_with_recomputed_digest(
    tmp_path: Path,
) -> None:
    """True cannot alias successor version 1 in an otherwise ordered supersession journal."""
    original, original_authority = _bound_policy()
    successor, successor_authority = _bound_policy(policy_id="policy-2")
    supersession = _seal_event(
        {
            "kind": "external-validation-policy-superseded",
            "eventVersion": 1,
            "policyId": original.policy_id,
            "policyVersion": original.version,
            "policyDigest": original.policy_digest,
            "successorPolicyId": successor.policy_id,
            "successorPolicyVersion": True,
            "successorPolicyDigest": successor.policy_digest,
            "actor": "authority",
            "occurredAt": "2026-09-07T00:00:00Z",
        }
    )
    path = tmp_path / "bool-successor-version.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                _admitted_event(original, original_authority),
                _admitted_event(successor, successor_authority),
                supersession,
            )
        )
        + "\n",
        encoding="ascii",
    )

    with pytest.raises(ExternalValidationPolicyRecoveryError):
        _registry(
            DurableJournal(path),
            FakePolicyAuthorityPort(original_authority, successor_authority),
        )
