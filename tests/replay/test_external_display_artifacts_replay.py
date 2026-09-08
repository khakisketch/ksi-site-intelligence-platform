"""Replay hardening for the durable sanitized-display artifact journal."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_display_artifacts import (
    DisplayArtifactResult,
    DisplayArtifactVerdict,
    DisplayPhase,
    ExternalDisplayArtifactRecoveryError,
    ExternalDisplayArtifactStore,
)
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from ksi_core.leasing import LeaseFence
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ExternalValidationPolicyV1
from ksi_event_contracts.external_display_artifact import SanitizedDisplayDeclarationV1
from support.external_artifact_inspection_fixtures import (
    ACQUISITION,
    NOW,
    WORKER_A,
    SyntheticStorage,
    digest,
    policy_template,
    report,
    subject,
)


class _Authority(PolicyAuthorityPort):
    def __init__(self, record: PolicyAuthorityRecord) -> None:
        self._record = record

    def resolve(self, authority_record_digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        del now
        return self._record if authority_record_digest == self._record.digest else None


def _registry(
    tmp_path: Path,
) -> tuple[ExternalValidationPolicyRegistry, ExternalValidationPolicyV1]:
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
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority_port=_Authority(authority),
        clock=lambda: NOW,
    )
    registry.admit(policy, actor="authority", now=NOW)
    return registry, policy


def _sealed_digest(value: str | None) -> str:
    assert value is not None
    return value


def _bind_test_guard(
    store: ExternalDisplayArtifactStore,
    registry: ExternalValidationPolicyRegistry,
    fence: LeaseFence,
) -> None:
    def guard(
        _request_id: str,
        candidate: LeaseFence,
        _report_digest: str,
        commit: Callable[[datetime, int, ExternalValidationPolicyV1], DisplayArtifactResult],
    ) -> DisplayArtifactResult | None:
        if candidate != fence:
            return None
        selected = registry.select_for_use("DISPLAY", (subject(),))
        assert selected.policy is not None
        return commit(NOW, candidate.lease_generation, selected.policy)

    store.bind_mutation_guard(guard)


def test_display_restart_restores_declaration_and_rejects_reordered_events(tmp_path: Path) -> None:
    """The durable display history must not allow a declaration before its report queue."""
    registry, policy = _registry(tmp_path)
    journal_path = tmp_path / "display.jsonl"
    storage = SyntheticStorage()
    store = ExternalDisplayArtifactStore(
        DurableJournal(journal_path), policy_registry=registry, storage=storage, clock=lambda: NOW
    )
    fence = LeaseFence(WORKER_A, ACQUISITION, 1)
    _bind_test_guard(store, registry, fence)
    accepted = report(request_id="request-1", policy=policy)
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
        store.ensure_after_report(
            accepted,
            display_permitted=True,
            measured_ortho=True,
            max_retry_attempts=2,
            max_output_bytes=16384,
            now=NOW,
        )
        is DisplayPhase.QUEUED
    )
    assert (
        store.grant(accepted.request_id, declaration, fence, now=NOW).verdict
        is DisplayArtifactVerdict.DECLARATION_RECORDED
    )

    store._journal.close()  # noqa: SLF001 - process-boundary simulation.
    restarted = ExternalDisplayArtifactStore(
        DurableJournal(journal_path), policy_registry=registry, storage=storage, clock=lambda: NOW
    )
    assert restarted.phase_for(accepted.request_id) is DisplayPhase.RUNNING

    restarted._journal.close()  # noqa: SLF001 - close before deliberate on-disk tamper.
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    journal_path.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
    with pytest.raises(ExternalDisplayArtifactRecoveryError):
        ExternalDisplayArtifactStore(
            DurableJournal(journal_path),
            policy_registry=registry,
            storage=storage,
            clock=lambda: NOW,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("observedDerivativeSizeBytes", 124),
        ("sealedAt", "2026-09-07T00:00:01Z"),
    ),
)
def test_display_replay_rejects_contradictory_seal_top_level_fields(
    tmp_path: Path, field: str, value: object
) -> None:
    """No event may disagree with its sealed receipt or source declaration."""
    registry, policy = _registry(tmp_path)
    journal_path = tmp_path / "display.jsonl"
    storage = SyntheticStorage()
    store = ExternalDisplayArtifactStore(
        DurableJournal(journal_path), policy_registry=registry, storage=storage, clock=lambda: NOW
    )
    fence = LeaseFence(WORKER_A, ACQUISITION, 1)
    _bind_test_guard(store, registry, fence)
    accepted = report(request_id="request-1", policy=policy)
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
    store.ensure_after_report(
        accepted,
        display_permitted=True,
        measured_ortho=True,
        max_retry_attempts=2,
        max_output_bytes=16384,
        now=NOW,
    )
    assert store.grant(accepted.request_id, declaration, fence, now=NOW).grant is not None
    assert storage.last_put_key is not None
    storage.objects[storage.last_put_key] = type(storage.observe_object(storage.last_put_key))(
        storage.last_put_key, True, 123, digest("9"), "image/tiff"
    )
    assert store.seal(accepted.request_id, fence, now=NOW).verdict is DisplayArtifactVerdict.SEALED

    store._journal.close()  # noqa: SLF001 - close before on-disk replay corruption.
    events = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    events[-1][field] = value
    events[-1]["eventDigest"] = "sha256:" + hashlib.sha256(
        canonical_json_bytes(
            {key: item for key, item in events[-1].items() if key != "eventDigest"}
        )
    ).hexdigest()
    journal_path.write_text(
        "\n".join(
            json.dumps(event, separators=(",", ":"), sort_keys=True) for event in events
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ExternalDisplayArtifactRecoveryError):
        ExternalDisplayArtifactStore(
            DurableJournal(journal_path),
            policy_registry=registry,
            storage=storage,
            clock=lambda: NOW,
        )


def test_display_replay_rejects_digest_valid_terminal_failure_then_seal(tmp_path: Path) -> None:
    """A terminal failure is a final predecessor even if a later seal digest is valid."""
    registry, policy = _registry(tmp_path)
    storage = SyntheticStorage()
    fence = LeaseFence(WORKER_A, ACQUISITION, 1)
    accepted = report(request_id="request-1", policy=policy)
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

    sealed_path = tmp_path / "sealed.jsonl"
    sealed_store = ExternalDisplayArtifactStore(
        DurableJournal(sealed_path),
        policy_registry=registry,
        storage=storage,
        clock=lambda: NOW,
    )
    _bind_test_guard(sealed_store, registry, fence)
    sealed_store.ensure_after_report(
        accepted,
        display_permitted=True,
        measured_ortho=True,
        max_retry_attempts=2,
        max_output_bytes=16384,
        now=NOW,
    )
    assert sealed_store.grant(accepted.request_id, declaration, fence, now=NOW).grant is not None
    assert storage.last_put_key is not None
    storage.objects[storage.last_put_key] = type(storage.observe_object(storage.last_put_key))(
        storage.last_put_key, True, 123, digest("9"), "image/tiff"
    )
    assert (
        sealed_store.seal(accepted.request_id, fence, now=NOW).verdict
        is DisplayArtifactVerdict.SEALED
    )
    sealed_store._journal.close()  # noqa: SLF001 - extract real immutable event wire.
    sealed_events = [
        json.loads(line) for line in sealed_path.read_text(encoding="utf-8").splitlines()
    ]

    failed_path = tmp_path / "failed.jsonl"
    failed_store = ExternalDisplayArtifactStore(
        DurableJournal(failed_path),
        policy_registry=registry,
        storage=storage,
        clock=lambda: NOW,
    )
    _bind_test_guard(failed_store, registry, fence)
    failed_store.ensure_after_report(
        accepted,
        display_permitted=True,
        measured_ortho=True,
        max_retry_attempts=2,
        max_output_bytes=16384,
        now=NOW,
    )
    assert failed_store.grant(accepted.request_id, declaration, fence, now=NOW).grant is not None
    assert (
        failed_store.record_failure(accepted.request_id, fence, "PARSER_REJECTED", now=NOW).verdict
        is DisplayArtifactVerdict.RETRY_EXHAUSTED
    )
    failed_store._journal.close()  # noqa: SLF001 - extract real immutable terminal event wire.
    failed_events = [
        json.loads(line) for line in failed_path.read_text(encoding="utf-8").splitlines()
    ]

    journal_path = tmp_path / "terminal-then-seal.jsonl"
    journal_path.write_text(
        "\n".join(
            json.dumps(event, separators=(",", ":"), sort_keys=True)
            for event in (*sealed_events[:2], failed_events[-1], sealed_events[-1])
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ExternalDisplayArtifactRecoveryError):
        ExternalDisplayArtifactStore(
            DurableJournal(journal_path),
            policy_registry=registry,
            storage=storage,
            clock=lambda: NOW,
        )
