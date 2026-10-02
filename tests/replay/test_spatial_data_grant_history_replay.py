"""Historical grant replay must verify bindings without applying today's expiry."""

import json
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest
from ksi_core.domains.external.delivery.grants import (
    SpatialDataGrantRecoveryError,
    SpatialDataGrantStore,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from spatial_data_fixture import NOW, make_grant, make_revocation


def test_history_and_revocation_survive_restart_without_new_append(tmp_path: Path) -> None:
    path = tmp_path / "authority.jsonl"
    grant = make_grant(valid_from=NOW - timedelta(days=10), valid_until=NOW - timedelta(days=9))
    revocation = make_revocation(grant_digest=grant.grant_digest)
    with closing(DurableJournal(path)) as journal:
        store = SpatialDataGrantStore(
            journal, coordinator=ExternalAuthorityCurrentnessCoordinator()
        )
        store.provision(grant)
        store.revoke(revocation)
    with closing(DurableJournal(path)) as journal:
        store = SpatialDataGrantStore(
            journal, coordinator=ExternalAuthorityCurrentnessCoordinator()
        )
        assert (
            store.historical_grant(organization_id="org-local", grant_id="local-grant", revision=1)
            == grant
        )
        assert store.is_revoked(organization_id="org-local", grant_id="local-grant", revision=1)
        store.provision(grant)
        store.revoke(revocation)
        assert len(journal.replay()) == 2


@pytest.mark.parametrize("mutation", ["digest", "unknown_event", "unexpected_field"])
def test_corrupt_grant_history_fails_closed(tmp_path: Path, mutation: str) -> None:
    path = tmp_path / "authority.jsonl"
    with closing(DurableJournal(path)) as journal:
        SpatialDataGrantStore(
            journal, coordinator=ExternalAuthorityCurrentnessCoordinator()
        ).provision(make_grant())
    event = json.loads(path.read_text())
    if mutation == "digest":
        event["grant"]["attribution"] = "modified without digest update"
    elif mutation == "unknown_event":
        event["recordType"] = "spatial-data-grant.unknown.v1"
    else:
        event["untrusted"] = True
    path.write_text(json.dumps(event) + "\n")
    with closing(DurableJournal(path)) as journal, pytest.raises(SpatialDataGrantRecoveryError):
        SpatialDataGrantStore(journal, coordinator=ExternalAuthorityCurrentnessCoordinator())


def test_revocation_before_its_grant_fails_closed_on_replay(tmp_path: Path) -> None:
    path = tmp_path / "authority.jsonl"
    with closing(DurableJournal(path)) as journal:
        store = SpatialDataGrantStore(
            journal, coordinator=ExternalAuthorityCurrentnessCoordinator()
        )
        store.provision(make_grant())
        store.revoke(make_revocation())
    rows = path.read_text().splitlines()
    path.write_text("\n".join(reversed(rows)) + "\n")
    with closing(DurableJournal(path)) as journal, pytest.raises(SpatialDataGrantRecoveryError):
        SpatialDataGrantStore(journal, coordinator=ExternalAuthorityCurrentnessCoordinator())
