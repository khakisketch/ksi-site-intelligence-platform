"""Worker-result receipt auth/replay; synthetic ports are not deployment proof."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from ksi_core.domains.external.quantity.external_delta_output_observations import (
    CoreDeltaOutputObservationStore,
    DeltaOutputObservationRecoveryError,
    observation_from_record,
)
from ksi_core.domains.external.quantity.external_delta_publications import (
    ExternalDeltaPublicationStore,
    FilesystemDeltaByteStore,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from test_external_delta_publications import (
    _Clock,
    _FakeAuthority,
    _FakeEgress,
    _FakeSource,
    _intent_kwargs,
    _leased,
    _observation,
    _operator,
    _policy,
    _worker,
)


@pytest.fixture
def graph(tmp_path: Path) -> Iterator[tuple[Any, Any, Any, Any, Any, Any]]:
    clock, source, authority = _Clock(), _FakeSource(), _FakeAuthority()
    coor = ExternalAuthorityCurrentnessCoordinator()
    obs_journal = DurableJournal(tmp_path / "observations.jsonl")
    publication_journal = DurableJournal(tmp_path / "publications.jsonl")
    receipts = CoreDeltaOutputObservationStore(obs_journal, coordinator=coor, clock=clock)
    byte_store = FilesystemDeltaByteStore(tmp_path / "bytes")
    store = ExternalDeltaPublicationStore(
        publication_journal,
        source_witness=source,
        authority=authority,
        egress=_FakeEgress(),
        byte_store=byte_store,
        observations=receipts,
        policy=_policy(),
        clock=clock,
        coordinator=coor,
    )
    store.create_intent(principal=_operator(), **_intent_kwargs())
    yield store, receipts, clock, source, authority, obs_journal
    obs_journal.close()
    publication_journal.close()
    byte_store.close()


def test_no_receipt_can_be_accepted_without_the_current_worker_lease(graph: Any) -> None:
    store, receipts, clock, _, _, journal = graph
    observation = _observation(b"unit-only-not-real-tiff")
    assert (
        receipts.record_worker_result(
            publication_store=store,
            worker_principal=_worker(),
            observation=observation,
        )
        is None
    )
    assert list(journal.replay()) == []
    lease = _leased(store, _worker(), clock)
    assert lease is not None
    assert (
        receipts.record_worker_result(
            publication_store=store,
            worker_principal=_worker(),
            observation=observation,
        )
        == observation
    )
    assert (
        receipts.record_worker_result(
            publication_store=store,
            worker_principal=_worker(),
            observation=observation,
        )
        == observation
    )
    assert len(list(journal.replay())) == 1
    clock.now += timedelta(hours=1)
    assert (
        receipts.record_worker_result(
            publication_store=store,
            worker_principal=_worker(),
            observation=observation,
        )
        is None
    )


@pytest.mark.parametrize(
    "change",
    [
        {"worker_principal_id": "another"},
        {"worker_instance_id": "another"},
        {"lease_generation": 2},
        {"organization_id": "another"},
        {"site_id": "another"},
        {"work_area_id": "another"},
        {"grid_rows": 8},
        {"source_contract_version": "external-relative-volume-calculation-report.v2"},
    ],
)
def test_worker_observation_cannot_borrow_another_scope_source_or_fence(
    graph: Any, change: dict[str, object]
) -> None:
    store, receipts, clock, _, _, journal = graph
    assert _leased(store, _worker(), clock) is not None
    observation = replace(_observation(b"unit-bytes"), **change, observation_digest=None).sealed()
    assert (
        receipts.record_worker_result(
            publication_store=store,
            worker_principal=_worker(),
            observation=observation,
        )
        is None
    )
    assert list(journal.replay()) == []


@pytest.mark.parametrize("revoked", ["source", "policy", "runtime"])
def test_current_authority_loss_prevents_accepting_even_a_valid_worker_receipt(
    graph: Any, revoked: str
) -> None:
    store, receipts, clock, source, authority, journal = graph
    assert _leased(store, _worker(), clock) is not None
    if revoked == "source":
        source.live = False
    elif revoked == "policy":
        authority.policy_current = False
    else:
        authority.runtime_current = False
    assert (
        receipts.record_worker_result(
            publication_store=store,
            worker_principal=_worker(),
            observation=_observation(b"unit"),
        )
        is None
    )
    assert list(journal.replay()) == []


def test_human_cannot_create_worker_receipt_even_when_allowed_to_request_publication(
    graph: Any,
) -> None:
    store, receipts, _, _, _, journal = graph
    with pytest.raises(PermissionError, match="designated Analysis worker"):
        receipts.record_worker_result(
            publication_store=store,
            worker_principal=_operator(),
            observation=_observation(b"unit"),
        )
    assert list(journal.replay()) == []


def test_receipt_shape_and_journal_corruption_are_rejected(
    tmp_path: Path, graph: Any
) -> None:
    store, receipts, clock, _, _, journal = graph
    assert _leased(store, _worker(), clock) is not None
    observed = _observation(b"unit-bytes")
    assert (
        receipts.record_worker_result(
            publication_store=store,
            worker_principal=_worker(),
            observation=observed,
        )
        == observed
    )
    with pytest.raises(ValueError, match="unknown"):
        observation_from_record({**asdict(observed), "download_url": "https://attacker.invalid"})
    event = list(journal.replay())[0]
    event["observation"]["output_size_bytes"] += 1
    broken_path = tmp_path / "broken.jsonl"
    broken = DurableJournal(broken_path)
    try:
        broken.append(event)
    finally:
        broken.close()
    with pytest.raises(DeltaOutputObservationRecoveryError):
        CoreDeltaOutputObservationStore(
            DurableJournal(broken_path),
            coordinator=receipts.coordinator,
            clock=clock,
        )
