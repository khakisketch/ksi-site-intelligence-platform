from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Literal

import ksi_core.durable_journal as durable_journal
import pytest
from ksi_core.auth import Principal, PrincipalKind, Role
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.external_use_decisions import (
    ExternalDecisionIntent,
    ExternalUseDecisionConflictError,
    ExternalUseDecisionRecoveryError,
    ExternalUseDecisionStore,
    WriteStatus,
)
from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    ExternalPairUseDecisionV1,
    ExternalUseDecisionV1,
    SealedExternalSubjectV1,
)

NOW = datetime(2026, 9, 8, 1, 2, 3, tzinfo=UTC)


def _digest(marker: str) -> str:
    return f"sha256:{marker * 64}"


def _principal(*, organization_id: str = "org-a", principal_id: str = "operator-a") -> Principal:
    return Principal(principal_id, PrincipalKind.OPERATOR, Role.ADMIN, None, organization_id)


def _subject(
    *, marker: str, site_id: str = "site-a", organization_id: str = "org-a"
) -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id=organization_id,
        site_id=site_id,
        work_order_id="work-order-a",
        submission_id=f"submission-{marker}",
        revision=1,
        submission_digest=_digest(marker),
        manifest_digest=_digest("b" if marker == "a" else "c"),
    )


def _single(
    *,
    decision_id: str = "decision-single",
    use: Literal["DISPLAY", "HEIGHT"] = "DISPLAY",
    organization_id: str = "org-a",
) -> ExternalUseDecisionV1:
    subject = _subject(marker="a", organization_id=organization_id)
    return ExternalUseDecisionV1(
        decision_id=decision_id,
        subject=subject,
        subject_digest=subject.canonical_digest(),
        use=use,
        evidence_record_digests=(_digest("d"), _digest("e")),
        verdict=DecisionVerdict.BLOCKED,
        reasons=("POLICY_UNAVAILABLE",),
        remediations=("AUTHORIZE_POLICY",),
        decided_at=NOW,
    ).sealed()


def _pair(
    *,
    decision_id: str = "decision-pair",
    use: Literal["VISUAL_COMPARISON", "RELATIVE_VOLUME"] = "VISUAL_COMPARISON",
) -> ExternalPairUseDecisionV1:
    baseline, current = _subject(marker="a"), _subject(marker="b")
    return ExternalPairUseDecisionV1(
        decision_id=decision_id,
        baseline_subject=baseline,
        baseline_subject_digest=baseline.canonical_digest(),
        current_subject=current,
        current_subject_digest=current.canonical_digest(),
        use=use,
        evidence_record_digests=(_digest("d"), _digest("e")),
        verdict=DecisionVerdict.BLOCKED,
        reasons=("POLICY_UNAVAILABLE",),
        remediations=("AUTHORIZE_POLICY",),
        decided_at=NOW,
    ).sealed()


class _SyntheticHistoryVerifier:
    def verify(self, candidate: object) -> bool:
        del candidate
        return True


def _eligible_single() -> ExternalUseDecisionV1:
    candidate = _single(decision_id="decision-eligible")
    return candidate.model_copy(
        update={
            "policy_digest": _digest("1"),
            "inspection_report_digest": _digest("2"),
            "evidence_record_digests": (),
            "sanitized_display_receipt_digest": _digest("3"),
            "verdict": DecisionVerdict.ELIGIBLE,
            "reasons": ("DISPLAY_ELIGIBLE",),
            "remediations": ("DISPLAY_RECEIPT_RETAINED",),
            "decision_digest": None,
        },
        deep=True,
    ).sealed()


def _store(tmp_path: Path) -> ExternalUseDecisionStore:
    return ExternalUseDecisionStore(DurableJournal(tmp_path / "external-use.jsonl"))


def _intent(candidate: ExternalUseDecisionV1 | ExternalPairUseDecisionV1) -> ExternalDecisionIntent:
    return ExternalDecisionIntent.from_candidate(candidate)


def test_stage_then_reconcile_persists_exact_sealed_single_candidate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    staged = store.stage_evaluated(
        _single(),
        intent=_intent(_single()),
        principal=_principal(),
        idempotency_key="request-1",
    )
    assert staged.status is WriteStatus.PENDING
    assert store.get_scoped("decision-single", principal=_principal(), site_id="site-a") is None

    recorded = store.reconcile_pending()

    assert recorded[0].status is WriteStatus.RECORDED
    decision = store.get_scoped("decision-single", principal=_principal(), site_id="site-a")
    assert decision == _single()
    assert decision is not None and decision.decision_digest == _single().decision_digest


def test_current_pair_for_issue_is_exactly_scoped_without_a_site_hint(tmp_path: Path) -> None:
    """A numeric issue resolves the recorded pair before choosing its mapping."""
    store = _store(tmp_path)
    pair = _pair()
    store.stage_evaluated(
        pair,
        intent=_intent(pair),
        principal=_principal(),
        idempotency_key="pair-for-issue",
    )
    store.reconcile_pending()

    assert (
        store.resolve_current_pair_for_issue(
            "decision-pair", principal=_principal(), current_work_order_id="work-order-a"
        )
        == pair
    )
    assert (
        store.resolve_current_pair_for_issue(
            "decision-pair",
            principal=_principal(organization_id="org-b"),
            current_work_order_id="work-order-a",
        )
        is None
    )
    assert (
        store.resolve_current_pair_for_issue(
            "decision-pair", principal=_principal(), current_work_order_id="work-order-other"
        )
        is None
    )

    single = _single()
    store.stage_evaluated(
        single,
        intent=_intent(single),
        principal=_principal(),
        idempotency_key="single-for-issue",
    )
    store.reconcile_pending()
    assert (
        store.resolve_current_pair_for_issue(
            "decision-single", principal=_principal(), current_work_order_id="work-order-a"
        )
        is None
    )


def test_exact_retry_is_idempotent_but_changed_normalized_intent_or_use_conflicts(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    first = store.stage_evaluated(
        _single(),
        intent=_intent(_single()),
        principal=_principal(),
        idempotency_key="request-1",
    )
    retry = store.stage_evaluated(
        _single(),
        intent=_intent(_single()),
        principal=_principal(),
        idempotency_key="request-1",
    )
    assert retry == first
    with pytest.raises(ExternalUseDecisionConflictError):
        store.stage_evaluated(
            _single(decision_id="decision-height", use="HEIGHT"),
            intent=_intent(_single(decision_id="decision-height", use="HEIGHT")),
            principal=_principal(),
            idempotency_key="request-1",
        )


def test_existing_intent_is_read_before_a_fresh_evaluator_timestamp_is_allocated(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    candidate = _single()
    intent = _intent(candidate)
    store.stage_evaluated(
        candidate,
        intent=intent,
        principal=_principal(),
        idempotency_key="request-1",
    )

    assert (
        store.existing_for_intent(
            intent=intent, principal=_principal(), idempotency_key="request-1"
        )
        == candidate
    )
    with pytest.raises(ExternalUseDecisionConflictError):
        store.existing_for_intent(
            intent=ExternalDecisionIntent(requested_use="HEIGHT", subject=_subject(marker="a")),
            principal=_principal(),
            idempotency_key="request-1",
        )


def test_blocked_relative_volume_retains_selected_zone_in_idempotency_intent(
    tmp_path: Path,
) -> None:
    """A failed authority lookup must not turn all zone selections into one retry."""
    store = _store(tmp_path)
    candidate = _pair(use="RELATIVE_VOLUME")
    selected = ExternalDecisionIntent(
        requested_use="RELATIVE_VOLUME",
        baseline_subject=candidate.baseline_subject,
        current_subject=candidate.current_subject,
        requested_zone_id="zone-a",
    )
    store.stage_evaluated(
        candidate,
        intent=selected,
        principal=_principal(),
        idempotency_key="volume-1",
    )

    assert (
        store.existing_for_intent(
            intent=selected, principal=_principal(), idempotency_key="volume-1"
        )
        == candidate
    )
    with pytest.raises(ExternalUseDecisionConflictError):
        store.existing_for_intent(
            intent=ExternalDecisionIntent(
                requested_use="RELATIVE_VOLUME",
                baseline_subject=candidate.baseline_subject,
                current_subject=candidate.current_subject,
                requested_zone_id="zone-b",
            ),
            principal=_principal(),
            idempotency_key="volume-1",
        )


def test_recovery_refuses_eligible_history_without_source_resolver(tmp_path: Path) -> None:
    path = tmp_path / "eligible-history.jsonl"
    candidate = _eligible_single()
    store = ExternalUseDecisionStore(
        DurableJournal(path), history_verifier=_SyntheticHistoryVerifier()
    )
    store.stage_evaluated(
        candidate,
        intent=ExternalDecisionIntent.from_candidate(candidate),
        principal=_principal(),
        idempotency_key="eligible-1",
    )
    store._journal.close()  # noqa: SLF001 - reopen must fail closed.

    with pytest.raises(ExternalUseDecisionRecoveryError, match="eligible decision source history"):
        ExternalUseDecisionStore(DurableJournal(path))


def test_independently_supplied_intent_must_match_the_sealed_candidate(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="intent does not match"):
        store.stage_evaluated(
            _single(),
            intent=ExternalDecisionIntent(requested_use="DISPLAY", subject=_subject(marker="b")),
            principal=_principal(),
            idempotency_key="request-1",
        )

    assert store.reconcile_pending() == ()


def test_same_literal_key_is_independent_across_principal_and_organization(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.stage_evaluated(
        _single(),
        intent=_intent(_single()),
        principal=_principal(),
        idempotency_key="request-1",
    )

    independent = store.stage_evaluated(
        _single(decision_id="decision-org-b", organization_id="org-b"),
        intent=_intent(_single(decision_id="decision-org-b", organization_id="org-b")),
        principal=_principal(organization_id="org-b", principal_id="operator-b"),
        idempotency_key="request-1",
    )
    assert independent.status is WriteStatus.PENDING
    store._journal.close()  # noqa: SLF001 - exercise restart namespace replay.

    reopened = _store(tmp_path)
    assert (
        reopened.stage_evaluated(
            _single(),
            intent=_intent(_single()),
            principal=_principal(),
            idempotency_key="request-1",
        ).status
        is WriteStatus.PENDING
    )
    org_b = _single(decision_id="decision-org-b", organization_id="org-b")
    assert (
        reopened.stage_evaluated(
            org_b,
            intent=_intent(org_b),
            principal=_principal(organization_id="org-b", principal_id="operator-b"),
            idempotency_key="request-1",
        ).status
        is WriteStatus.PENDING
    )


def test_raw_idempotency_key_is_absent_from_the_durable_journal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sentinel = "raw-key-must-never-enter-journal"
    store.stage_evaluated(
        _single(),
        intent=_intent(_single()),
        principal=_principal(),
        idempotency_key=sentinel,
    )

    persisted = (tmp_path / "external-use.jsonl").read_text()
    assert sentinel not in persisted
    assert '"idempotencyKey"' not in persisted
    assert '"namespace"' in persisted


def test_threaded_exact_conflicting_and_independent_tenant_retries(tmp_path: Path) -> None:
    store = _store(tmp_path)

    def run_together(calls: tuple[Callable[[], object], ...]) -> list[object]:
        barrier = Barrier(len(calls))

        def run(call: Callable[[], object]) -> object:
            barrier.wait()
            return call()

        with ThreadPoolExecutor(max_workers=len(calls)) as executor:
            return list(executor.map(run, calls))

    exact = _single()
    exact_results = run_together(
        (
            lambda: store.stage_evaluated(
                exact, intent=_intent(exact), principal=_principal(), idempotency_key="exact"
            ),
            lambda: store.stage_evaluated(
                exact, intent=_intent(exact), principal=_principal(), idempotency_key="exact"
            ),
        )
    )
    assert all(getattr(result, "status", None) is WriteStatus.PENDING for result in exact_results)

    conflict = _single(decision_id="decision-conflict", use="HEIGHT")

    def conflicting(candidate: ExternalUseDecisionV1) -> object:
        try:
            return store.stage_evaluated(
                candidate,
                intent=_intent(candidate),
                principal=_principal(),
                idempotency_key="conflict",
            )
        except ExternalUseDecisionConflictError as exc:
            return exc

    conflict_results = run_together(
        (
            lambda: conflicting(_single(decision_id="decision-conflict-display")),
            lambda: conflicting(conflict),
        )
    )
    assert (
        sum(isinstance(result, ExternalUseDecisionConflictError) for result in conflict_results)
        == 1
    )
    assert (
        sum(getattr(result, "status", None) is WriteStatus.PENDING for result in conflict_results)
        == 1
    )

    tenant_a = _single(decision_id="decision-tenant-a")
    tenant_b = _single(decision_id="decision-tenant-b", organization_id="org-b")
    tenant_results = run_together(
        (
            lambda: store.stage_evaluated(
                tenant_a, intent=_intent(tenant_a), principal=_principal(), idempotency_key="shared"
            ),
            lambda: store.stage_evaluated(
                tenant_b,
                intent=_intent(tenant_b),
                principal=_principal(organization_id="org-b", principal_id="operator-b"),
                idempotency_key="shared",
            ),
        )
    )
    assert all(getattr(result, "status", None) is WriteStatus.PENDING for result in tenant_results)
    assert len(store._journal.replay()) == 4  # noqa: SLF001 - inspect durable append count.


def test_append_failure_seals_without_an_in_memory_partial_and_recovers_requested_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed_stage_path = tmp_path / "failed-stage.jsonl"
    failed_stage = ExternalUseDecisionStore(DurableJournal(failed_stage_path))

    def fail_write(_fd: int, _data: object) -> int:
        raise OSError("injected write failure")

    with monkeypatch.context() as patch:
        patch.setattr(durable_journal, "_WRITE", fail_write)
        with pytest.raises(JournalSealedError):
            failed_stage.stage_evaluated(
                _single(),
                intent=_intent(_single()),
                principal=_principal(),
                idempotency_key="failed-stage",
            )
    assert failed_stage.sealed_reason == "OSError"
    assert failed_stage.reconcile_pending() == ()
    failed_stage._journal.close()  # noqa: SLF001 - release the sealed writer before restart.
    assert ExternalUseDecisionStore(DurableJournal(failed_stage_path)).reconcile_pending() == ()

    path = tmp_path / "external-use.jsonl"
    store = ExternalUseDecisionStore(DurableJournal(path))
    candidate = _single()
    store.stage_evaluated(
        candidate,
        intent=_intent(candidate),
        principal=_principal(),
        idempotency_key="failure",
    )

    with monkeypatch.context() as patch:
        patch.setattr(durable_journal, "_WRITE", fail_write)
        with pytest.raises(JournalSealedError):
            store.reconcile_pending()
    assert store.sealed_reason == "OSError"
    assert store.get_scoped(candidate.decision_id, principal=_principal(), site_id="site-a") is None
    assert len(path.read_text().splitlines()) == 1

    store._journal.close()  # noqa: SLF001 - release the sealed writer before restart.
    recovered = ExternalUseDecisionStore(DurableJournal(path))
    assert (
        recovered.get_scoped(candidate.decision_id, principal=_principal(), site_id="site-a")
        is None
    )
    receipts = recovered.reconcile_pending()
    assert len(receipts) == 1
    assert receipts[0].candidate == candidate
    assert len(path.read_text().splitlines()) == 2


def test_pair_keeps_baseline_current_and_evidence_order_without_evaluation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    candidate = _pair()
    store.stage_evaluated(
        candidate,
        intent=_intent(candidate),
        principal=_principal(),
        idempotency_key="pair-1",
    )
    store.reconcile_pending()

    recorded = store.get_scoped("decision-pair", principal=_principal(), site_id="site-a")
    assert recorded == candidate
    assert isinstance(recorded, ExternalPairUseDecisionV1)
    assert recorded.baseline_subject_digest == candidate.baseline_subject_digest
    assert recorded.current_subject_digest == candidate.current_subject_digest
    assert recorded.evidence_record_digests == (_digest("d"), _digest("e"))


def test_foreign_or_pending_read_is_absent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.stage_evaluated(
        _single(),
        intent=_intent(_single()),
        principal=_principal(),
        idempotency_key="request-1",
    )
    assert store.list_scoped(principal=_principal(organization_id="org-b"), site_id="site-a") == ()
    store.reconcile_pending()
    assert (
        store.get_scoped(
            "decision-single", principal=_principal(organization_id="org-b"), site_id="site-a"
        )
        is None
    )
    assert store.get_scoped("decision-single", principal=_principal(), site_id="site-b") is None
