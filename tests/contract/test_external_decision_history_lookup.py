"""Private actor-neutral history lookup preserves scoped recorded pair identity."""

from pathlib import Path

from ksi_core.durable_journal import DurableJournal
from ksi_core.external_use_decisions import ExternalUseDecisionStore
from test_external_use_decisions import _digest, _intent, _pair, _principal, _single, _store


def test_pair_history_is_recorded_scoped_exact_and_copied(tmp_path: Path) -> None:
    journal = DurableJournal(tmp_path / "external-use.jsonl")
    store = ExternalUseDecisionStore(journal)
    pair = _pair()
    assert pair.decision_digest is not None
    args = dict(
        organization_id="org-a",
        site_id="site-a",
        decision_id=pair.decision_id,
        decision_digest=pair.decision_digest,
    )
    store.stage_evaluated(
        pair, intent=_intent(pair), principal=_principal(), idempotency_key="pair"
    )
    assert store.resolve_historical_pair(**args) is None
    store.reconcile_pending()
    before = (tmp_path / "external-use.jsonl").read_bytes()
    retained = store.resolve_historical_pair(**args)
    assert retained == pair and retained is not pair
    assert retained is not None
    object.__setattr__(retained, "reasons", ("CALLER_MUTATION",))
    assert store.resolve_historical_pair(**args) == pair
    for field, value in [
        ("organization_id", "other"),
        ("site_id", "other"),
        ("decision_id", "missing"),
        ("decision_digest", _digest("f")),
    ]:
        assert store.resolve_historical_pair(**{**args, field: value}) is None
    journal.close()
    restarted = ExternalUseDecisionStore(DurableJournal(tmp_path / "external-use.jsonl"))
    assert restarted.resolve_historical_pair(**args) == pair
    assert (tmp_path / "external-use.jsonl").read_bytes() == before


def test_pair_history_does_not_promote_single_decision(tmp_path: Path) -> None:
    store = _store(tmp_path)
    single = _single()
    assert single.decision_digest is not None
    store.stage_evaluated(
        single, intent=_intent(single), principal=_principal(), idempotency_key="single"
    )
    store.reconcile_pending()
    assert (
        store.resolve_historical_pair(
            organization_id="org-a",
            site_id="site-a",
            decision_id=single.decision_id,
            decision_digest=single.decision_digest,
        )
        is None
    )
