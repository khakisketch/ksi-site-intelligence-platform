from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from ksi_core.auth import Principal, PrincipalKind, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_use_decisions import (
    ExternalDecisionIntent,
    ExternalUseDecisionRecoveryError,
    ExternalUseDecisionStore,
)
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    ExternalUseDecisionV1,
    SealedExternalSubjectV1,
)

NOW = datetime(2026, 9, 8, 1, 2, 3, tzinfo=UTC)


def _digest(marker: str) -> str:
    return f"sha256:{marker * 64}"


def _principal() -> Principal:
    return Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-a")


def _candidate() -> ExternalUseDecisionV1:
    subject = SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="work-order-a",
        submission_id="submission-a",
        revision=1,
        submission_digest=_digest("a"),
        manifest_digest=_digest("b"),
    )
    return ExternalUseDecisionV1(
        decision_id="decision-single",
        subject=subject,
        subject_digest=subject.canonical_digest(),
        use="DISPLAY",
        evidence_record_digests=(),
        verdict=DecisionVerdict.BLOCKED,
        reasons=("POLICY_UNAVAILABLE",),
        remediations=("AUTHORIZE_POLICY",),
        decided_at=NOW,
    ).sealed()


def _journal(tmp_path: Path) -> Path:
    return tmp_path / "external-use.jsonl"


def _intent(candidate: ExternalUseDecisionV1) -> ExternalDecisionIntent:
    return ExternalDecisionIntent.from_candidate(candidate)


def _stage(path: Path) -> None:
    store = ExternalUseDecisionStore(DurableJournal(path))
    store.stage_evaluated(
        _candidate(),
        intent=_intent(_candidate()),
        principal=_principal(),
        idempotency_key="request-1",
    )
    store._journal.close()  # noqa: SLF001 - test simulates a crash after requested fsync.


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _write(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records))


def _reseal_event(event: dict[str, object]) -> None:
    payload = {key: value for key, value in event.items() if key != "eventDigest"}
    event["eventDigest"] = "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def test_reopen_then_explicit_reconcile_records_original_candidate_time_and_digest(
    tmp_path: Path,
) -> None:
    path = _journal(tmp_path)
    _stage(path)
    before = _records(path)[0]
    reopened = ExternalUseDecisionStore(DurableJournal(path))
    receipts = reopened.reconcile_pending()

    assert len(receipts) == 1
    recorded = _records(path)[1]
    assert recorded["candidateDigest"] == before["candidateDigest"]
    assert recorded["recordedAt"] == before["requestedAt"]
    assert (
        reopened.get_scoped("decision-single", principal=_principal(), site_id="site-a")
        == _candidate()
    )


@pytest.mark.parametrize(
    "mutation", ["candidate-digest", "fingerprint", "bool-version", "unknown-field"]
)
def test_replay_rejects_mutated_requested_event_and_seals_journal(
    tmp_path: Path, mutation: str
) -> None:
    path = _journal(tmp_path)
    _stage(path)
    records = _records(path)
    event = records[0]
    if mutation == "candidate-digest":
        event["candidateDigest"] = _digest("f")
    elif mutation == "fingerprint":
        idempotency = cast(dict[str, object], event["idempotency"])
        idempotency["fingerprint"] = _digest("f")
    elif mutation == "bool-version":
        event["version"] = True
    else:
        event["unexpected"] = "value"
    _write(path, records)

    journal = DurableJournal(path)
    with pytest.raises(ExternalUseDecisionRecoveryError):
        ExternalUseDecisionStore(journal)
    assert journal.sealed_reason == "closed"


def test_replay_recomputes_fingerprint_after_a_digest_valid_forgery(tmp_path: Path) -> None:
    path = _journal(tmp_path)
    _stage(path)
    records = _records(path)
    idempotency = cast(dict[str, object], records[0]["idempotency"])
    idempotency["fingerprint"] = _digest("f")
    _reseal_event(records[0])
    _write(path, records)

    with pytest.raises(ExternalUseDecisionRecoveryError):
        ExternalUseDecisionStore(DurableJournal(path))


def test_replay_rejects_duplicate_or_out_of_order_recorded_event(tmp_path: Path) -> None:
    path = _journal(tmp_path)
    _stage(path)
    store = ExternalUseDecisionStore(DurableJournal(path))
    store.reconcile_pending()
    store._journal.close()  # noqa: SLF001
    records = _records(path)
    _write(path, [records[1], records[0]])

    with pytest.raises(ExternalUseDecisionRecoveryError):
        ExternalUseDecisionStore(DurableJournal(path))
