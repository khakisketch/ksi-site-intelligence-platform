"""Queued worker discovery over the real masked journal (additive, read-only).

Every test drives the real ``ExternalMaskedCalculationStore``; strict
evidence fakes are reused from the sibling replay module (same directory,
per repo precedent) and extended only to fan out over many identities.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest
from ksi_core.domains.external.quantity.external_masked_calculation_store import (
    ExternalMaskedCalculationStore,
    MaskedAdmissionEvidencePort,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_masked_api import MaskedCalculationPendingItemV1
from ksi_event_contracts.external_masked_volume_result import (
    MaskedVolumeCalculationFailureV3,
)
from test_external_masked_calculation_replay import (
    NOW,
    _masked_identity,
    _operator,
    _sealed_report,
    _StrictEvidence,
    _worker,
)


def _deep_envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=4000000,
        max_streamed_bytes=4000000,
        max_tiff_directories=8,
        max_tiff_entries=128,
        max_pixels=1000000,
        max_bands=4,
        max_blocks=512,
        max_decompressed_bytes=20000000,
        max_sample_bytes=4000000,
        max_geometry_vertices=64,
        max_cpu_seconds=30.0,
        max_memory_bytes=50000000,
        max_workspace_bytes=50000000,
        max_output_bytes=1000000,
        max_tenant_concurrency=8,
        max_queue_depth=64,
        max_deadline_seconds=60.0,
        lease_duration_seconds=10.0,
        max_retry_attempts=2,
    ).sealed()


class _MapEvidence(MaskedAdmissionEvidencePort):
    """Strict per-identity evidence fan-out with a witness-call counter."""

    def __init__(self, identities) -> None:
        self._ports = {
            identity.canonical_digest(): _StrictEvidence(identity) for identity in identities
        }
        self.live = True
        self.calls = 0

    def kill(self, identity) -> None:
        self._ports[identity.canonical_digest()].live = False

    def revive(self, identity) -> None:
        self._ports[identity.canonical_digest()].live = True

    def prepare_witness(
        self, *, masked_calculation_identity_digest, organization_id, now, expected_admission=None
    ):
        self.calls += 1
        if not self.live:
            return None
        port = self._ports.get(masked_calculation_identity_digest)
        if port is None:
            return None
        return port.prepare_witness(
            masked_calculation_identity_digest=masked_calculation_identity_digest,
            organization_id=organization_id,
            now=now,
            expected_admission=expected_admission,
        )

    def witness_is_current(self, *, witness, now):
        if not self.live or witness is None:
            return None
        port = self._ports.get(witness.source_identity.canonical_digest())
        if port is None:
            return None
        return port.witness_is_current(witness=witness, now=now)


def _identity(tag: str):
    base = _masked_identity()
    return base.model_copy(
        update={
            "masked_calculation_id": f"masked-calculation-{tag}",
            "masked_calculation_identity_digest": None,
        }
    ).sealed()


def _make_store(tmp_path, evidence, *, name="masked-calc.journal", envelope=None):
    journal = DurableJournal(tmp_path / name)
    store = ExternalMaskedCalculationStore(
        journal,
        evidence=evidence,
        resource_envelope=envelope or _deep_envelope(),
        designated_worker=_worker(),
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    return journal, store


def _issue(store, identity, request_id: str, at: datetime):
    store.bind_constructed_identity(principal=_operator(), identity=identity, now=at)
    return store.issue(
        principal=_operator(),
        request_id=request_id,
        masked_calculation_identity_digest=identity.canonical_digest(),
        idempotency_key="idem-" + request_id,
        now=at,
    )


def _lease(store, request_id: str, at: datetime, *, acquisition: str, instance="worker-inst-1"):
    attempt = store.acquire_lease(
        request_id=request_id,
        worker_principal=_worker(),
        worker_instance_id=instance,
        lease_acquisition_id=acquisition,
        now=at,
    )
    assert attempt is not None
    return attempt


def test_queued_ordering_oldest_first_and_shape(tmp_path) -> None:
    identities = [_identity("a"), _identity("b"), _identity("c")]
    journal, store = _make_store(tmp_path, _MapEvidence(identities))
    stamps = (NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=2))
    for tag, identity, at in zip(("a", "b", "c"), identities, stamps, strict=True):
        _issue(store, identity, "req-" + tag, at)
    items = store.list_queued_calculations(
        organization_id="org-a", limit=50, now=NOW + timedelta(seconds=3)
    )
    assert [item.request_id for item in items] == ["req-a", "req-b", "req-c"]
    assert all(isinstance(item, MaskedCalculationPendingItemV1) for item in items)
    assert [item.execution_state for item in items] == ["QUEUED"] * 3
    assert items[0].masked_calculation_identity_digest == identities[0].canonical_digest()
    assert items[0].issued_at == NOW


def test_limit_validation_and_cap(tmp_path) -> None:
    identities = [_identity("a")]
    _, store = _make_store(tmp_path, _MapEvidence(identities))
    _issue(store, identities[0], "req-a", NOW)
    for bad in (0, 51, -1, True, False, "10", 2.0, None):
        with pytest.raises(ValueError, match="limit must be an integer"):
            store.list_queued_calculations(organization_id="org-a", limit=bad, now=NOW)
    for bad_org in ("", "   ", None, 42):
        with pytest.raises(ValueError, match="requires an organization"):
            store.list_queued_calculations(organization_id=bad_org, limit=10, now=NOW)
    with pytest.raises(ValueError, match="must be UTC"):
        store.list_queued_calculations(
            organization_id="org-a", limit=10, now=datetime(2026, 10, 26)
        )
    assert len(store.list_queued_calculations(organization_id="org-a", limit=1, now=NOW)) == 1


def test_expired_lease_reclaimable_live_lease_hidden(tmp_path) -> None:
    identities = [_identity("a"), _identity("b")]
    _, store = _make_store(tmp_path, _MapEvidence(identities))
    _issue(store, identities[0], "req-a", NOW)
    _issue(store, identities[1], "req-b", NOW)
    _lease(store, "req-a", NOW, acquisition="acq-1")
    live = store.list_queued_calculations(
        organization_id="org-a", limit=10, now=NOW + timedelta(seconds=1)
    )
    assert [item.request_id for item in live] == ["req-b"]
    reclaim = store.list_queued_calculations(
        organization_id="org-a", limit=10, now=NOW + timedelta(seconds=11)
    )
    assert [(item.request_id, item.execution_state) for item in reclaim] == [
        ("req-a", "RUNNING"),
        ("req-b", "QUEUED"),
    ]


def test_retry_exhaustion_excluded(tmp_path) -> None:
    identities = [_identity("a")]
    _, store = _make_store(tmp_path, _MapEvidence(identities))
    _issue(store, identities[0], "req-a", NOW)
    _lease(store, "req-a", NOW, acquisition="acq-1")
    _lease(store, "req-a", NOW + timedelta(seconds=11), acquisition="acq-2")
    assert (
        store.list_queued_calculations(
            organization_id="org-a", limit=10, now=NOW + timedelta(seconds=22)
        )
        == ()
    )
    # The record itself is untouched; only discovery omits it.
    assert store.get_history("req-a", organization_id="org-a") is not None


def test_deadline_past_excluded(tmp_path) -> None:
    identities = [_identity("a")]
    _, store = _make_store(tmp_path, _MapEvidence(identities))
    _issue(store, identities[0], "req-a", NOW)
    assert (
        store.list_queued_calculations(
            organization_id="org-a", limit=10, now=NOW + timedelta(seconds=61)
        )
        == ()
    )
    assert "req-a" not in store._pending  # noqa: SLF001 - owned index hygiene


def test_terminal_report_failure_cancel_excluded_and_popped(tmp_path) -> None:
    identities = [_identity("a"), _identity("b"), _identity("c")]
    _, store = _make_store(tmp_path, _MapEvidence(identities))
    _issue(store, identities[0], "req-a", NOW)
    _issue(store, identities[1], "req-b", NOW)
    _issue(store, identities[2], "req-c", NOW)
    attempt_a = _lease(store, "req-a", NOW, acquisition="acq-a")
    report = _sealed_report(identities[0])
    assert (
        store.record_report(
            request_id="req-a",
            worker_principal=_worker(),
            report=report,
            attempt=attempt_a,
            now=NOW + timedelta(seconds=5),
        )
        is not None
    )
    attempt_b = _lease(store, "req-b", NOW, acquisition="acq-b")
    failure = MaskedVolumeCalculationFailureV3(
        failure_id="failure-1",
        masked_calculation_identity_digest=identities[1].canonical_digest(),
        reason_code="WORKER_FAILED",
        failed_at=NOW + timedelta(seconds=5),
    ).sealed()
    assert (
        store.record_failure(
            request_id="req-b",
            worker_principal=_worker(),
            failure=failure,
            attempt=attempt_b,
            now=NOW + timedelta(seconds=5),
        )
        is not None
    )
    assert (
        store.cancel(principal=_operator(), request_id="req-c", now=NOW + timedelta(seconds=5))
        is not None
    )
    assert (
        store.list_queued_calculations(
            organization_id="org-a", limit=10, now=NOW + timedelta(seconds=6)
        )
        == ()
    )
    assert store._pending == {}  # noqa: SLF001 - owned index hygiene


def test_stale_witness_omitted(tmp_path) -> None:
    identities = [_identity("a"), _identity("b")]
    evidence = _MapEvidence(identities)
    _, store = _make_store(tmp_path, evidence)
    _issue(store, identities[0], "req-a", NOW)
    _issue(store, identities[1], "req-b", NOW)
    evidence.kill(identities[0])
    items = store.list_queued_calculations(
        organization_id="org-a", limit=10, now=NOW + timedelta(seconds=1)
    )
    assert [item.request_id for item in items] == ["req-b"]
    evidence.live = False
    assert (
        store.list_queued_calculations(
            organization_id="org-a", limit=10, now=NOW + timedelta(seconds=1)
        )
        == ()
    )
    evidence.live = True
    evidence.revive(identities[0])
    assert (
        len(
            store.list_queued_calculations(
                organization_id="org-a", limit=10, now=NOW + timedelta(seconds=1)
            )
        )
        == 2
    )


def test_foreign_org_omitted(tmp_path) -> None:
    identities = [_identity("a")]
    _, store = _make_store(tmp_path, _MapEvidence(identities))
    _issue(store, identities[0], "req-a", NOW)
    assert store.list_queued_calculations(organization_id="org-b", limit=10, now=NOW) == ()


def test_no_journal_append(tmp_path) -> None:
    identities = [_identity("a")]
    journal, store = _make_store(tmp_path, _MapEvidence(identities))
    _issue(store, identities[0], "req-a", NOW)
    size_before = os.path.getsize(tmp_path / "masked-calc.journal")
    for at in (NOW + timedelta(seconds=i) for i in range(1, 6)):
        store.list_queued_calculations(organization_id="org-a", limit=10, now=at)
    assert os.path.getsize(tmp_path / "masked-calc.journal") == size_before
    assert len(journal.replay()) == 2  # bind + issue only


def test_rotation_defeats_stale_head_starvation(tmp_path) -> None:
    identities = [_identity(f"n{i:02d}") for i in range(32)]
    evidence = _MapEvidence(identities)
    _, store = _make_store(tmp_path, evidence)
    for index, identity in enumerate(identities):
        _issue(store, identity, f"req-{index:02d}", NOW)
        if index < 30:
            evidence.kill(identity)
    evidence.calls = 0  # issue-time witness resolutions are not poll examinations
    first = store.list_queued_calculations(
        organization_id="org-a", limit=2, now=NOW + timedelta(seconds=1)
    )
    # Bounded scan: 2 sought + 25 rejection budget = 27 examinations, all stale.
    assert first == ()
    assert evidence.calls == 27
    second = store.list_queued_calculations(
        organization_id="org-a", limit=2, now=NOW + timedelta(seconds=1)
    )
    assert [item.request_id for item in second] == ["req-30", "req-31"]
    assert evidence.calls == 27 + 5


def test_replay_restores_pending_index(tmp_path) -> None:
    identities = [_identity("a"), _identity("b")]
    journal, store = _make_store(tmp_path, _MapEvidence(identities), name="restart.journal")
    _issue(store, identities[0], "req-a", NOW)
    _issue(store, identities[1], "req-b", NOW)
    _lease(store, "req-a", NOW, acquisition="acq-1")
    journal.close()
    reopened = ExternalMaskedCalculationStore(
        DurableJournal(tmp_path / "restart.journal"),
        evidence=_MapEvidence(identities),
        resource_envelope=_deep_envelope(),
        designated_worker=_worker(),
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    items = reopened.list_queued_calculations(
        organization_id="org-a", limit=10, now=NOW + timedelta(seconds=11)
    )
    assert [(item.request_id, item.execution_state) for item in items] == [
        ("req-a", "RUNNING"),
        ("req-b", "QUEUED"),
    ]


def test_pending_flow_binds_designated_worker_not_issuer(tmp_path) -> None:
    from ksi_core.identity.auth import Principal, PrincipalKind

    identities = [_identity("a")]
    journal, store = _make_store(tmp_path, _MapEvidence(identities))
    _issue(store, identities[0], "req-a", NOW)
    record = store.get_history("req-a", organization_id="org-a")
    assert record is not None
    assert record.authorization.worker_principal_id == _worker().principal_id
    assert record.authorization.worker_principal_id != "operator-a"
    second = Principal("analysis-worker-2", PrincipalKind.ANALYSIS_WORKER, None, None, "org-a")
    size_before = os.path.getsize(tmp_path / "masked-calc.journal")
    with pytest.raises(PermissionError, match="not the designated execution worker"):
        store.acquire_lease(
            request_id="req-a",
            worker_principal=second,
            worker_instance_id="other-instance-1",
            lease_acquisition_id="other-lease-1",
            now=NOW,
        )
    assert os.path.getsize(tmp_path / "masked-calc.journal") == size_before
    listed = store.list_queued_calculations(organization_id="org-a", limit=10, now=NOW)
    assert [item.request_id for item in listed] == ["req-a"]
