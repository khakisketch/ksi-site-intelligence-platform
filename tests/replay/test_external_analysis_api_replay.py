"""Replay gates for durable public Analysis API intent records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ksi_core.domains.external.quantity.external_analysis_intents import (
    AnalysisIntentRecoveryError,
    AnalysisIntentStore,
    PublicAnalysisIntent,
)
from ksi_core.durable_journal import DurableJournal
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_analysis_api import (
    AnalysisObservationSelectorV1,
    CreateAnalysisRequestV1,
)

_NOW = datetime(2026, 9, 22, tzinfo=UTC)


def _request() -> CreateAnalysisRequestV1:
    return CreateAnalysisRequestV1(
        baseline=AnalysisObservationSelectorV1(
            work_order_id="work-order-baseline",
            submission_ref="ers-v1-" + "a" * 64,
            revision=1,
        ),
        current=AnalysisObservationSelectorV1(
            work_order_id="work-order-current",
            submission_ref="ers-v1-" + "b" * 64,
            revision=1,
        ),
    )


def _event_digest(event: dict[str, object]) -> str:
    payload = {key: value for key, value in event.items() if key != "eventDigest"}
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _record(path: Path, *, link: bool = False) -> PublicAnalysisIntent:
    store = AnalysisIntentStore(DurableJournal(path))
    intent = store.record_intent(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        request=_request(),
        idempotency_key="replay-idempotency-key",
        now=_NOW,
    )
    if link:
        store.link_calculation(
            analysis_id=intent.analysis_id,
            organization_id="org-a",
            calculation_request_id="calculation-a",
        )
    store.close()
    return intent


def _write_events(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )


def _read_events(path: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        assert isinstance(value, dict)
        event: dict[str, object] = {}
        for key, item in value.items():
            assert isinstance(key, str)
            event[key] = item
        events.append(event)
    return events


def _set_boolean_version(event: dict[str, object]) -> None:
    event.update({"version": True})


def _set_invalid_analysis_id(event: dict[str, object]) -> None:
    event.update({"analysisId": 7})


def _set_invalid_idempotency_digest(event: dict[str, object]) -> None:
    event.update({"idempotencyDigest": "sha256:" + "A" * 64})


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            _set_boolean_version,
            "shape",
        ),
        (
            _set_invalid_analysis_id,
            "identity",
        ),
        (
            _set_invalid_idempotency_digest,
            "idempotency",
        ),
    ),
)
def test_intent_replay_rejects_noncanonical_primitives_and_digests(
    tmp_path: Path, mutate: Callable[[dict[str, object]], None], message: str
) -> None:
    """A digest-resealed event still needs exact journal primitive encodings."""
    path = tmp_path / "analysis-intents.jsonl"
    _record(path)
    events = _read_events(path)
    assert len(events) == 1
    mutate(events[0])
    events[0]["eventDigest"] = _event_digest(events[0])
    _write_events(path, events)

    with pytest.raises(AnalysisIntentRecoveryError, match=message):
        AnalysisIntentStore(DurableJournal(path))


@pytest.mark.parametrize(
    ("forged", "message"),
    (("scoped", "scoped"), ("rebound", "rebound"), ("boolean-version", "shape")),
)
def test_intent_replay_rejects_forged_or_rebound_calculation_links(
    tmp_path: Path, forged: str, message: str
) -> None:
    """A link event cannot substitute an organization or a different NX request."""
    path = tmp_path / "analysis-intents.jsonl"
    intent = _record(path, link=True)
    events = _read_events(path)
    link = dict(events[-1])
    if forged == "scoped":
        link["organizationId"] = "org-forged"
    elif forged == "rebound":
        link["calculationRequestId"] = "calculation-rebound"
    else:
        link["version"] = True
    link["eventDigest"] = _event_digest(link)
    events.append(link)
    _write_events(path, events)

    with pytest.raises(AnalysisIntentRecoveryError, match=message):
        AnalysisIntentStore(DurableJournal(path))
    assert intent.analysis_id.startswith("analysis-v1-")


def test_intent_replay_rejects_complete_interior_corruption(tmp_path: Path) -> None:
    """A malformed completed event is not treated as a recoverable torn tail."""
    path = tmp_path / "analysis-intents.jsonl"
    _record(path, link=True)
    events = _read_events(path)
    events[0]["siteId"] = "site-corrupted"
    _write_events(path, events)

    with pytest.raises(AnalysisIntentRecoveryError, match="digest"):
        AnalysisIntentStore(DurableJournal(path))


def test_intent_replay_discards_only_a_torn_final_record(tmp_path: Path) -> None:
    """The last unnewline-terminated partial write does not erase prior intent history."""
    path = tmp_path / "analysis-intents.jsonl"
    intent = _record(path)
    with path.open("ab") as handle:
        handle.write(b'{"kind":"external-analysis-intent-recorded"')

    recovered = AnalysisIntentStore(DurableJournal(path))
    assert recovered.get(intent.analysis_id, organization_id="org-a") == intent
    recovered.close()
    assert path.read_bytes().endswith(b"\n")
