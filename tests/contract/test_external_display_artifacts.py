"""Contract tests for sanitized external display artifacts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import ObjectStorageObservation
from ksi_core.external_display_artifacts import (
    DisplayArtifactResult,
    DisplayArtifactVerdict,
    DisplayPhase,
    ExternalDisplayArtifactStore,
)
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from ksi_core.leasing import LeaseFence
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
)
from ksi_event_contracts.external_display_artifact import SanitizedDisplayDeclarationV1
from support.external_artifact_inspection_fixtures import (
    ACQUISITION,
    NOW,
    WORKER_A,
    WORKER_B,
    SyntheticStorage,
    digest,
    policy_template,
    report,
    subject,
)


class _FenceChangingStorage(SyntheticStorage):
    """Models a lease takeover completing while Core observes uploaded bytes."""

    def __init__(self, active: list[bool]) -> None:
        super().__init__()
        self._active = active

    def observe_object(self, object_key: str) -> ObjectStorageObservation:
        observed = super().observe_object(object_key)
        self._active[0] = False
        return observed


class _FailureDuringObservationStorage(SyntheticStorage):
    """Injects a durable terminal display failure while seal is between HEAD and commit."""

    def __init__(self) -> None:
        super().__init__()
        self.on_observe: Callable[[], object] | None = None

    def observe_object(self, object_key: str) -> ObjectStorageObservation:
        observed = super().observe_object(object_key)
        if self.on_observe is not None:
            callback, self.on_observe = self.on_observe, None
            callback()
        return observed


class _Authority(PolicyAuthorityPort):
    def __init__(self, record: PolicyAuthorityRecord) -> None:
        assert record.digest is not None
        self._record = record

    def resolve(self, authority_record_digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        del now
        return self._record if authority_record_digest == self._record.digest else None


def _policy_registry(
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
    authorizes: Callable[[LeaseFence], bool],
) -> None:
    """Isolated-store tests supply an explicit coordinator, never a fallback path."""

    def guard(
        _request_id: str,
        candidate: LeaseFence,
        _report_digest: str,
        commit: Callable[[datetime, int, ExternalValidationPolicyV1], DisplayArtifactResult],
    ) -> DisplayArtifactResult | None:
        if not authorizes(candidate):
            return None
        selected = registry.select_for_use("DISPLAY", (subject(),))
        assert selected.policy is not None
        return commit(NOW, candidate.lease_generation, selected.policy)

    store.bind_mutation_guard(guard)


def test_display_work_is_report_first_and_can_resume_after_crash(tmp_path: Path) -> None:
    """Granting before report or losing a post-upload seal must not create new evidence."""
    registry, policy = _policy_registry(tmp_path)
    storage = SyntheticStorage()
    journal_path = tmp_path / "display.jsonl"
    store = ExternalDisplayArtifactStore(
        DurableJournal(journal_path), policy_registry=registry, storage=storage, clock=lambda: NOW
    )
    first = LeaseFence(WORKER_A, ACQUISITION, 1)
    successor = LeaseFence(WORKER_B, ACQUISITION, 2)
    _bind_test_guard(store, registry, lambda candidate: candidate == first)
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
        store.grant(accepted.request_id, declaration, first, now=NOW).verdict
        is DisplayArtifactVerdict.DISPLAY_NOT_REQUIRED
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
    granted = store.grant(accepted.request_id, declaration, first, now=NOW)
    assert granted.verdict is DisplayArtifactVerdict.DECLARATION_RECORDED
    assert storage.last_put_key is not None

    store._journal.close()  # noqa: SLF001 - simulate process shutdown before DurableJournal restart.
    restarted = ExternalDisplayArtifactStore(
        DurableJournal(journal_path), policy_registry=registry, storage=storage, clock=lambda: NOW
    )
    _bind_test_guard(restarted, registry, lambda candidate: candidate == successor)
    storage.objects[storage.last_put_key] = type(storage.observe_object(storage.last_put_key))(
        object_key=storage.last_put_key,
        exists=True,
        size_bytes=123,
        sha256=digest("9"),
        content_type="image/tiff",
    )

    assert (
        restarted.seal(accepted.request_id, first, now=NOW).verdict
        is DisplayArtifactVerdict.LEASE_FENCE_REJECTED
    )
    sealed = restarted.seal(accepted.request_id, successor, now=NOW)
    assert sealed.verdict is DisplayArtifactVerdict.SEALED
    assert sealed.receipt is not None


def test_display_seal_rechecks_fence_after_storage_observation(tmp_path: Path) -> None:
    """Pre-I/O fence approval must not publish a receipt after a takeover."""
    registry, policy = _policy_registry(tmp_path)
    active = [True]
    storage = _FenceChangingStorage(active)
    store = ExternalDisplayArtifactStore(
        DurableJournal(tmp_path / "display.jsonl"),
        policy_registry=registry,
        storage=storage,
        clock=lambda: NOW,
    )
    fence = LeaseFence(WORKER_A, ACQUISITION, 1)
    _bind_test_guard(store, registry, lambda candidate: active[0] and candidate == fence)
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
        object_key=storage.last_put_key,
        exists=True,
        size_bytes=123,
        sha256=digest("9"),
        content_type="image/tiff",
    )
    active[0] = True
    assert (
        store.seal(accepted.request_id, fence, now=NOW).verdict
        is DisplayArtifactVerdict.LEASE_FENCE_REJECTED
    )


def test_display_seal_requires_the_exact_declared_object_key(tmp_path: Path) -> None:
    """Matching bytes at a different private key cannot satisfy a declaration."""
    registry, policy = _policy_registry(tmp_path)
    storage = SyntheticStorage()
    store = ExternalDisplayArtifactStore(
        DurableJournal(tmp_path / "display.jsonl"),
        policy_registry=registry,
        storage=storage,
        clock=lambda: NOW,
    )
    fence = LeaseFence(WORKER_A, ACQUISITION, 1)
    _bind_test_guard(store, registry, lambda candidate: candidate == fence)
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
        object_key="external-sanitized-display/v1/wrong-key",
        exists=True,
        size_bytes=123,
        sha256=digest("9"),
        content_type="image/tiff",
    )

    assert (
        store.seal(accepted.request_id, fence, now=NOW).verdict
        is DisplayArtifactVerdict.OBSERVATION_MISMATCH
    )


def test_display_retry_exhaustion_rejects_a_late_seal(tmp_path: Path) -> None:
    """A terminal display failure cannot later receive an immutable seal receipt."""
    registry, policy = _policy_registry(tmp_path)
    storage = SyntheticStorage()
    store = ExternalDisplayArtifactStore(
        DurableJournal(tmp_path / "display.jsonl"),
        policy_registry=registry,
        storage=storage,
        clock=lambda: NOW,
    )
    fence = LeaseFence(WORKER_A, ACQUISITION, 1)
    _bind_test_guard(store, registry, lambda candidate: candidate == fence)
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
    assert (
        store.record_failure(accepted.request_id, fence, "PARSER_REJECTED", now=NOW).verdict
        is DisplayArtifactVerdict.RETRY_EXHAUSTED
    )

    rejected = store.seal(accepted.request_id, fence, now=NOW)
    assert rejected.verdict is DisplayArtifactVerdict.RETRY_EXHAUSTED
    assert rejected.receipt is None
    assert store.phase_for(accepted.request_id) is DisplayPhase.RETRY_EXHAUSTED


def test_display_seal_rechecks_terminal_failure_after_storage_observation(tmp_path: Path) -> None:
    """A parser rejection during HEAD wins over the stale seal continuation."""
    registry, policy = _policy_registry(tmp_path)
    storage = _FailureDuringObservationStorage()
    store = ExternalDisplayArtifactStore(
        DurableJournal(tmp_path / "display.jsonl"),
        policy_registry=registry,
        storage=storage,
        clock=lambda: NOW,
    )
    fence = LeaseFence(WORKER_A, ACQUISITION, 1)
    _bind_test_guard(store, registry, lambda candidate: candidate == fence)
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
    storage.on_observe = lambda: store.record_failure(
        accepted.request_id, fence, "PARSER_REJECTED", now=NOW
    )

    rejected = store.seal(accepted.request_id, fence, now=NOW)
    assert rejected.verdict is DisplayArtifactVerdict.RETRY_EXHAUSTED
    assert rejected.receipt is None
    assert store.phase_for(accepted.request_id) is DisplayPhase.RETRY_EXHAUSTED
