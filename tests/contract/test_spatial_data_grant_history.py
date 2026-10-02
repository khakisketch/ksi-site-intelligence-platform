"""Trusted-only durable authority history, not permission to read artifact bytes."""

from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.grants import SpatialDataGrantStore
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from pydantic import ValidationError
from spatial_data_fixture import NOW, make_grant, make_revocation


def test_exact_provision_retry_is_durable_and_changed_body_conflicts(tmp_path: Path) -> None:
    with closing(DurableJournal(tmp_path / "authority.jsonl")) as journal:
        store = SpatialDataGrantStore(
            journal, coordinator=ExternalAuthorityCurrentnessCoordinator()
        )
        grant = make_grant()
        store.provision(grant)
        store.provision(grant)
        assert len(journal.replay()) == 1
        assert (
            store.historical_grant(organization_id="org-local", grant_id="local-grant", revision=1)
            == grant
        )
        with pytest.raises(SpatialDataDomainError) as error:
            store.provision(make_grant(attribution="changed license evidence"))
        assert error.value.status_code == 409
        assert len(journal.replay()) == 1


def test_exact_revisions_are_contiguous_and_old_revocation_never_carries_forward(
    tmp_path: Path,
) -> None:
    with closing(DurableJournal(tmp_path / "authority.jsonl")) as journal:
        store = SpatialDataGrantStore(
            journal, coordinator=ExternalAuthorityCurrentnessCoordinator()
        )
        with pytest.raises(SpatialDataDomainError):
            store.provision(make_grant(revision=2))
        store.provision(make_grant())
        with pytest.raises(SpatialDataDomainError):
            store.provision(make_grant(revision=3))
        store.revoke(make_revocation())
        store.provision(make_grant(revision=2))
        assert store.is_revoked(organization_id="org-local", grant_id="local-grant", revision=1)
        assert not store.is_revoked(organization_id="org-local", grant_id="local-grant", revision=2)


def test_unknown_and_wrong_digest_revocation_cannot_create_authority(tmp_path: Path) -> None:
    with closing(DurableJournal(tmp_path / "authority.jsonl")) as journal:
        store = SpatialDataGrantStore(
            journal, coordinator=ExternalAuthorityCurrentnessCoordinator()
        )
        with pytest.raises(SpatialDataDomainError) as error:
            store.revoke(make_revocation())
        assert error.value.status_code == 404
        store.provision(make_grant())
        with pytest.raises(SpatialDataDomainError) as error:
            store.revoke(make_revocation(grant_digest="sha256:" + "0" * 64))
        assert error.value.status_code == 409
        assert not store.is_revoked(organization_id="org-local", grant_id="local-grant", revision=1)


def test_revocation_is_monotonic_and_identical_retry_does_not_append(tmp_path: Path) -> None:
    with closing(DurableJournal(tmp_path / "authority.jsonl")) as journal:
        store = SpatialDataGrantStore(
            journal, coordinator=ExternalAuthorityCurrentnessCoordinator()
        )
        grant, revocation = make_grant(), make_revocation()
        store.provision(grant)
        store.revoke(revocation)
        store.revoke(revocation)
        store.provision(grant)
        assert len(journal.replay()) == 2
        assert store.is_revoked(organization_id="org-local", grant_id="local-grant", revision=1)
        with pytest.raises(SpatialDataDomainError):
            store.revoke(make_revocation(revoked_at=NOW + timedelta(seconds=1)))


def test_history_is_organization_scoped_and_not_a_currentness_decision(tmp_path: Path) -> None:
    with closing(DurableJournal(tmp_path / "authority.jsonl")) as journal:
        store = SpatialDataGrantStore(
            journal, coordinator=ExternalAuthorityCurrentnessCoordinator()
        )
        store.provision(make_grant())
        assert (
            store.historical_grant(organization_id="foreign", grant_id="local-grant", revision=1)
            is None
        )
        with pytest.raises(SpatialDataDomainError) as error:
            store.revoke(make_revocation(organization_id="foreign"))
        assert error.value.status_code == 404


def test_unsealed_or_copy_tampered_grants_never_reach_journal(tmp_path: Path) -> None:
    with closing(DurableJournal(tmp_path / "authority.jsonl")) as journal:
        store = SpatialDataGrantStore(
            journal, coordinator=ExternalAuthorityCurrentnessCoordinator()
        )
        with pytest.raises(ValueError):
            store.provision(make_grant().model_copy(update={"grant_digest": None}))
        with pytest.raises(ValidationError):
            store.provision(make_grant().model_copy(update={"attribution": "changed"}))
        assert journal.replay() == []


def test_append_failure_does_not_publish_projection(tmp_path: Path) -> None:
    with closing(DurableJournal(tmp_path / "authority.jsonl")) as journal:
        store = SpatialDataGrantStore(
            journal, coordinator=ExternalAuthorityCurrentnessCoordinator()
        )
        journal.close()
        with pytest.raises(JournalSealedError):
            store.provision(make_grant())
        assert (
            store.historical_grant(organization_id="org-local", grant_id="local-grant", revision=1)
            is None
        )


def test_concurrent_identical_provision_has_one_durable_record(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    with closing(DurableJournal(tmp_path / "authority.jsonl")) as journal:
        store = SpatialDataGrantStore(
            journal, coordinator=ExternalAuthorityCurrentnessCoordinator()
        )
        grant = make_grant()
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(store.provision, (grant,) * 16))
        assert len(journal.replay()) == 1


def test_same_grant_id_in_other_organization_has_separate_revision_history(tmp_path: Path) -> None:
    with closing(DurableJournal(tmp_path / "authority.jsonl")) as journal:
        store = SpatialDataGrantStore(
            journal, coordinator=ExternalAuthorityCurrentnessCoordinator()
        )
        first, other = make_grant(), make_grant(organization_id="other")
        store.provision(first)
        store.provision(other)
        store.revoke(make_revocation())
        assert (
            store.historical_grant(organization_id="other", grant_id="local-grant", revision=1)
            == other
        )
        assert not store.is_revoked(organization_id="other", grant_id="local-grant", revision=1)
