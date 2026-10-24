"""Indexed-history audit working set: bounded live sessions, retained history.

Generated fixtures only. The private 1531-record live copy is exercised by a
local scratch verification (counts/idempotent replay), never committed here.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from ksi_core.domains.external.delivery.audit import (
    SpatialDataAuditEventV1,
    SpatialDataAuditRecoveryError,
    SpatialDataAuditStore,
    _Record,
)
from ksi_core.domains.external.delivery.audit_history_index import (
    AuditHistoryIndex,
    AuditIndexCorruption,
    AuditIndexError,
    AuditIndexFull,
)
from ksi_core.domains.external.delivery.audit_working_set import (
    SpatialDataAuditWorkingSetV1,
    load_spatial_data_audit_working_set,
)
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.storage_s3 import SpatialDataS3Storage
from ksi_core.durable_journal import DurableJournal
from ksi_core.foundation.durable_journal import JournalError, JournalRecoveryError
from ksi_event_contracts.spatial_data_authority import SpatialDataPolicyV1
from spatial_data_fixture import NOW, make_policy

ORG = "org-test"
OTHER_ORG = "org-foreign"


def _job(i: int) -> str:
    return f"sdj-v1-{i:08x}-0000-4000-8000-{i:012x}"


def _event(
    session_id: str,
    action: str,
    *,
    at: datetime,
    sent: int = 0,
    reason: str | None = None,
    organization_id: str = ORG,
    job_index: int = 1,
    size: int = 1024,
) -> SpatialDataAuditEventV1:
    return SpatialDataAuditEventV1(
        event_id=str(uuid4()),
        session_id=session_id,
        organization_id=organization_id,
        principal_id="reader-test",
        site_id="site-test",
        work_area_id="area-test",
        job_id=_job(job_index),
        at=at,
        action=action,  # type: ignore[arg-type]
        expected_size_bytes=size,
        output_sha256="sha256:" + "ab" * 32,
        sent_bytes=sent,
        reason=reason,  # type: ignore[arg-type]
    ).sealed()


def _policy(**overrides: Any) -> Any:
    from spatial_data_fixture import make_envelope

    envelope = make_envelope(
        max_workspace_bytes=64 * 1024 * 1024,
        max_output_bytes=8 * 1024 * 1024,
        max_streamed_bytes=8 * 1024 * 1024,
    )
    payload: dict[str, Any] = dict(
        resource_envelope=envelope,
        max_output_bytes=8 * 1024 * 1024,
        max_stream_bytes=8 * 1024 * 1024,
        max_active_downloads_per_organization=4,
        max_snapshot_bytes=1024 * 1024,
        max_pending_records=8,
        max_list_records=64,
        max_json_bytes=65536,
    )
    payload.update(overrides)
    return make_policy(**payload)


def _ws(policy: Any, **overrides: Any) -> SpatialDataAuditWorkingSetV1:
    payload: dict[str, Any] = dict(
        version="spatial-data-audit-working-set.v1",
        policy_digest=policy.policy_digest,
        journal_file_name="spatial-data-audit.jsonl",
        allowed_operation_scope="download-only",
        activation_id="test-activation-01",
        active_session_cap=512,
        index_disk_bytes=8 * 1024 * 1024,
        index_cache_allowance_bytes=128 * 1024,
        max_boot_scan_bytes=64 * 1024 * 1024,
        max_boot_seconds=60.0,
        max_tail_records=4096,
        max_tail_bytes=16 * 1024 * 1024,
    )
    payload.update(overrides)
    return SpatialDataAuditWorkingSetV1(**payload)


def _store(
    path: Path,
    *,
    policy: Any | None = None,
    working_set: SpatialDataAuditWorkingSetV1 | None = None,
    name: str = "spatial-data-audit.jsonl",
) -> SpatialDataAuditStore:
    policy = policy or _policy()
    if working_set is None:
        working_set = _ws(policy)
    journal = DurableJournal(path / name, max_segment_bytes=None)
    return SpatialDataAuditStore(journal, policy=policy, working_set=working_set)


def _cycle(store: SpatialDataAuditStore, index: int, *, at: datetime) -> str:
    session = str(uuid4())
    store.append(_event(session, "DOWNLOAD_ADMITTED", at=at, job_index=index))
    store.append(_event(session, "STREAM_STARTED", at=at, job_index=index))
    store.append(_event(session, "STREAM_COMPLETED", at=at, sent=1024, job_index=index))
    return session


# -- Working-set config validation -------------------------------------------


def test_working_set_config_loads_from_owner_private_file(tmp_path: Path) -> None:
    policy = _policy()
    config = _ws(policy)
    target = tmp_path / "audit-ws.json"
    target.write_bytes(json.dumps(config.model_dump(mode="json")).encode())
    os.chmod(target, 0o600)
    loaded = load_spatial_data_audit_working_set(target)
    assert loaded == config


@pytest.mark.parametrize(
    "change",
    [
        {"version": "spatial-data-audit-working-set.v9"},
        {"allowed_operation_scope": "full"},
        {"active_session_cap": 513},
        {"index_disk_bytes": 64 * 1024 * 1024},
        {"policy_digest": "not-a-digest"},
    ],
)
def test_working_set_config_rejects_bad_values(tmp_path: Path, change: dict[str, Any]) -> None:
    policy = _policy()
    base = dict(
        version="spatial-data-audit-working-set.v1",
        policy_digest=policy.policy_digest,
        journal_file_name="spatial-data-audit.jsonl",
        allowed_operation_scope="download-only",
        activation_id="test-activation-01",
        active_session_cap=512,
        index_disk_bytes=8 * 1024 * 1024,
        index_cache_allowance_bytes=128 * 1024,
        max_boot_scan_bytes=64 * 1024 * 1024,
        max_boot_seconds=60.0,
        max_tail_records=4096,
        max_tail_bytes=16 * 1024 * 1024,
    )
    base.update(change)
    with pytest.raises(ValueError):
        SpatialDataAuditWorkingSetV1(**base)


def test_working_set_config_rejects_shared_file(tmp_path: Path) -> None:
    policy = _policy()
    target = tmp_path / "audit-ws.json"
    target.write_bytes(json.dumps(_ws(policy).model_dump(mode="json")).encode())
    os.chmod(target, 0o644)
    with pytest.raises(ValueError):
        load_spatial_data_audit_working_set(target)


def test_working_set_boot_rejects_policy_digest_mismatch(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    other = _policy(max_snapshot_bytes=2 * 1024 * 1024)
    assert other.policy_digest != policy.policy_digest
    bad = _ws(other)
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    with pytest.raises(SpatialDataAuditRecoveryError):
        SpatialDataAuditStore(journal, policy=policy, working_set=bad)


def test_working_set_boot_rejects_journal_name_mismatch(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    bad = _ws(policy, journal_file_name="other-audit.jsonl")
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    with pytest.raises(SpatialDataAuditRecoveryError):
        SpatialDataAuditStore(journal, policy=policy, working_set=bad)


# -- Legacy behavior unchanged -------------------------------------------------


def test_legacy_session_bound_still_refuses_new_history(tmp_path: Path) -> None:
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy)
    assert store.operation_scope == "full"
    base = NOW
    for index in range(8 * 64):
        _cycle(store, index, at=base + timedelta(seconds=index))
    assert len(store._sessions) == 8 * 64  # noqa: SLF001
    with pytest.raises(SpatialDataDomainError, match="RESOURCE_LIMIT_EXCEEDED"):
        store.append(_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=base, job_index=10**6))


def test_legacy_duplicate_exact_noop_and_conflict(tmp_path: Path) -> None:
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=_policy())
    session = str(uuid4())
    first = _event(session, "DOWNLOAD_ADMITTED", at=NOW, job_index=1)
    store.append(first)
    before = journal.record_count
    store.append(first.model_copy(deep=True))
    assert journal.record_count == before
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        store.append(first.model_copy(update={"at": NOW + timedelta(seconds=1)}))


# -- New mode: bounded working set over large terminal history -----------------


def test_working_set_admits_beyond_legacy_session_bound(tmp_path: Path) -> None:
    policy = _policy()
    store = _store(tmp_path, policy=policy)
    assert store.operation_scope == "download-only"
    base = NOW
    for index in range(600):
        _cycle(store, index, at=base + timedelta(seconds=index))
    assert len(store._sessions) == 0  # noqa: SLF001 -- terminal history evicted
    assert store._bytes == 0  # noqa: SLF001
    assert store._reserved_slots == 0  # noqa: SLF001
    latest = _cycle(store, 10**6, at=base + timedelta(seconds=10**6))
    assert store.events(organization_id=ORG, session_id=latest, limit=64)[-1].action == (
        "STREAM_COMPLETED"
    )


def test_working_set_ram_stays_bounded_over_thousands_of_sessions(tmp_path: Path) -> None:
    policy = _policy()
    store = _store(tmp_path, policy=policy)
    base = NOW
    for index in range(2000):
        _cycle(store, index, at=base + timedelta(seconds=index))
    assert len(store._sessions) == 0  # noqa: SLF001
    assert len(store._events) == 0  # noqa: SLF001
    assert store._bytes == 0  # noqa: SLF001
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    assert index_path.exists()
    assert index_path.stat().st_size <= 8 * 1024 * 1024


def test_working_set_no_full_history_replay(tmp_path: Path, monkeypatch: Any) -> None:
    policy = _policy()
    store = _store(tmp_path, policy=policy)
    for index in range(5):
        _cycle(store, index, at=NOW + timedelta(seconds=index))
    store.close()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    monkeypatch.setattr(journal, "replay", lambda: (_ for _ in ()).throw(AssertionError()))
    reopened = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    assert len(reopened.events(organization_id=ORG, session_id="nope", limit=1)) == 0
    reopened.close()


def test_working_set_serves_evicted_terminal_history(tmp_path: Path) -> None:
    policy = _policy()
    store = _store(tmp_path, policy=policy)
    first = _cycle(store, 1, at=NOW)
    _cycle(store, 2, at=NOW + timedelta(seconds=1))
    items = store.events(organization_id=ORG, session_id=first, limit=64)
    assert [item.action for item in items] == [
        "DOWNLOAD_ADMITTED",
        "STREAM_STARTED",
        "STREAM_COMPLETED",
    ]
    assert all(item.organization_id == ORG for item in items)
    assert store.events(organization_id=OTHER_ORG, session_id=first, limit=64) == ()
    assert store.events(organization_id=ORG, session_id=str(uuid4()), limit=64) == ()


def test_working_set_exact_retry_noop_and_conflict_after_eviction(tmp_path: Path) -> None:
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    session = str(uuid4())
    admitted = _event(session, "DOWNLOAD_ADMITTED", at=NOW, job_index=7)
    store.append(admitted)
    store.append(_event(session, "STREAM_STARTED", at=NOW, job_index=7))
    store.append(_event(session, "STREAM_COMPLETED", at=NOW, sent=1024, job_index=7))
    before = journal.record_count
    store.append(admitted.model_copy(deep=True))
    assert journal.record_count == before
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        store.append(admitted.model_copy(update={"at": NOW + timedelta(seconds=5)}))
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        store.append(_event(session, "STREAM_STARTED", at=NOW, job_index=7))


def test_working_set_denied_and_interrupted_are_terminal_and_queryable(
    tmp_path: Path,
) -> None:
    policy = _policy()
    store = _store(tmp_path, policy=policy)
    denied = str(uuid4())
    store.append(_event(denied, "DENIED", at=NOW, reason="GRANT_REQUIRED", job_index=11))
    interrupted = str(uuid4())
    store.append(_event(interrupted, "DOWNLOAD_ADMITTED", at=NOW, job_index=12))
    store.append(_event(interrupted, "STREAM_STARTED", at=NOW, job_index=12))
    store.append(_event(interrupted, "STREAM_INTERRUPTED", at=NOW, reason="CANCELED", job_index=12))
    assert len(store._sessions) == 0  # noqa: SLF001
    assert [i.action for i in store.events(organization_id=ORG, session_id=denied, limit=8)] == [
        "DENIED"
    ]
    assert [i.action for i in store.events(organization_id=ORG, session_id=interrupted, limit=8)][
        -1
    ] == "STREAM_INTERRUPTED"
    assert store.unfinished(organization_id=ORG, limit=8) == ()


def test_working_set_unfinished_restart_restores_reservations(tmp_path: Path) -> None:
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    open_one = str(uuid4())
    store.append(_event(open_one, "DOWNLOAD_ADMITTED", at=NOW, job_index=21))
    open_two = str(uuid4())
    store.append(_event(open_two, "DOWNLOAD_ADMITTED", at=NOW, job_index=22))
    store.append(_event(open_two, "STREAM_STARTED", at=NOW, job_index=22))
    _cycle(store, 23, at=NOW)
    reserved_before = store._reserved_slots  # noqa: SLF001
    assert reserved_before == 2 + 1
    store.close()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    reopened = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    assert reopened._reserved_slots == reserved_before  # noqa: SLF001
    pending = reopened.unfinished(organization_id=ORG, limit=8)
    assert {item.session_id for item in pending} == {open_one, open_two}
    reopened.append(_event(open_one, "STREAM_STARTED", at=NOW, job_index=21))
    reopened.append(_event(open_one, "STREAM_COMPLETED", at=NOW, sent=1024, job_index=21))
    assert reopened.unfinished(organization_id=ORG, limit=8)[0].session_id == open_two
    reopened.close()


def test_working_set_index_missing_rebuilds_within_bounds(tmp_path: Path) -> None:
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    _cycle(store, 2, at=NOW + timedelta(seconds=1))
    count_before = journal.record_count
    store.close()
    (tmp_path / "spatial-data-audit.ws.sqlite3").unlink()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    rebuilt = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    assert journal2.record_count == count_before
    assert [i.action for i in rebuilt.events(organization_id=ORG, session_id=first, limit=8)] == [
        "DOWNLOAD_ADMITTED",
        "STREAM_STARTED",
        "STREAM_COMPLETED",
    ]
    rebuilt.close()


def test_working_set_index_corrupt_rebuilds_or_refuses(tmp_path: Path) -> None:
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    store.close()
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    with index_path.open("r+b") as handle:
        handle.seek(100)
        handle.write(b"\x00\xff\x00\xff corrupted")
        handle.flush()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    try:
        rebuilt = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    except SpatialDataAuditRecoveryError:
        journal2.close()
        journal3 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
        with pytest.raises(SpatialDataAuditRecoveryError):
            SpatialDataAuditStore(
                journal3,
                policy=policy,
                working_set=_ws(policy, max_boot_scan_bytes=10),
            )
        journal3.close()
        return
    assert [i.action for i in rebuilt.events(organization_id=ORG, session_id=first, limit=8)][
        0
    ] == "DOWNLOAD_ADMITTED"
    rebuilt.close()


def test_working_set_crash_between_journal_and_index_recovers(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import _Record

    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    _cycle(store, 1, at=NOW)
    store.close()
    # Simulate a crash after journal fsync but before the index commit: append
    # a valid record straight to the journal with the next sequence.
    manual_session = str(uuid4())
    manual = _event(manual_session, "DOWNLOAD_ADMITTED", at=NOW, job_index=99)
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    journal2.append(_Record(sequence=4, event=manual).model_dump(by_alias=True, mode="json"))
    journal2.close()
    journal3 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    recovered = SpatialDataAuditStore(journal3, policy=policy, working_set=_ws(policy))
    items = recovered.events(organization_id=ORG, session_id=manual_session, limit=8)
    assert [item.action for item in items] == ["DOWNLOAD_ADMITTED"]
    assert recovered.unfinished(organization_id=ORG, limit=8)[0].session_id == manual_session
    recovered.close()


def test_working_set_corrupt_journal_still_refuses(tmp_path: Path) -> None:
    from ksi_core.foundation.durable_journal import JournalRecoveryError

    policy = _policy()
    store = _store(tmp_path, policy=policy)
    _cycle(store, 1, at=NOW)
    store.close()
    with (tmp_path / "spatial-data-audit.jsonl").open("ab") as handle:
        handle.write(b"{not json}\n")
        handle.flush()
    with pytest.raises(JournalRecoveryError):
        DurableJournal(tmp_path / "spatial-data-audit.jsonl")


def test_working_set_rebuild_budget_exhaustion_refuses(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    for index in range(3):
        _cycle(store, index, at=NOW + timedelta(seconds=index))
    store.close()
    (tmp_path / "spatial-data-audit.ws.sqlite3").unlink()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    with pytest.raises(SpatialDataAuditRecoveryError):
        SpatialDataAuditStore(
            journal2, policy=policy, working_set=_ws(policy, max_boot_scan_bytes=10)
        )


def test_working_set_boot_deadline_refuses(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    _cycle(store, 1, at=NOW)
    store.close()
    (tmp_path / "spatial-data-audit.ws.sqlite3").unlink()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    with pytest.raises(SpatialDataAuditRecoveryError):
        SpatialDataAuditStore(
            journal2, policy=policy, working_set=_ws(policy, max_boot_seconds=0.0 + 1e-9)
        )


def test_working_set_journal_replaced_under_index_refuses(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    _cycle(store, 1, at=NOW)
    store.close()
    # Same path, replaced file (new inode): the index must not silently
    # re-index over swapped evidence — boot refuses instead.
    (tmp_path / "spatial-data-audit.jsonl").unlink()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    with pytest.raises(SpatialDataAuditRecoveryError):
        SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    journal2.close()


def test_working_set_audit_append_failure_seals_before_headers(tmp_path: Path) -> None:
    import ksi_core.foundation.durable_journal as journal_module

    policy = _policy()
    store = _store(tmp_path, policy=policy)
    real_write = journal_module._WRITE

    def _fail(*args: Any, **kwargs: Any) -> int:
        raise OSError("injected storage failure")

    journal_module._WRITE = _fail
    try:
        with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
            store.append(_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=NOW, job_index=31))
        with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
            store.append(_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=NOW, job_index=32))
    finally:
        journal_module._WRITE = real_write


def test_working_set_sealed_store_refuses_history_queries(tmp_path: Path) -> None:
    policy = _policy()
    store = _store(tmp_path, policy=policy)
    first = _cycle(store, 1, at=NOW)
    store._sealed = True  # noqa: SLF001 -- simulate index-failure seal
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        store.append(_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=NOW, job_index=41))
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        store.events(organization_id=ORG, session_id=first, limit=8)
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        store.unfinished(organization_id=ORG, limit=8)


def test_working_set_query_limit_bound_unchanged(tmp_path: Path) -> None:
    policy = _policy()
    store = _store(tmp_path, policy=policy)
    with pytest.raises(SpatialDataDomainError, match="RESOURCE_LIMIT_EXCEEDED"):
        store.events(organization_id=ORG, session_id=str(uuid4()), limit=65)
    with pytest.raises(SpatialDataDomainError, match="RESOURCE_LIMIT_EXCEEDED"):
        store.unfinished(organization_id=ORG, limit=0)


def test_working_set_cleanup_history_preserved_and_unfinished_kept(
    tmp_path: Path,
) -> None:
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    cleanup_open = str(uuid4())
    store.append(_event(cleanup_open, "CLEANUP_STARTED", at=NOW, job_index=51))
    cleanup_done = str(uuid4())
    store.append(_event(cleanup_done, "CLEANUP_STARTED", at=NOW, job_index=52))
    store.append(_event(cleanup_done, "CLEANUP_COMPLETED", at=NOW, job_index=52))
    journal_records = journal.record_count
    store.close()
    reopened = SpatialDataAuditStore(
        DurableJournal(tmp_path / "spatial-data-audit.jsonl"),
        policy=policy,
        working_set=_ws(policy),
    )
    pending = reopened.unfinished(organization_id=ORG, limit=8)
    assert [item.session_id for item in pending] == [cleanup_open]
    done_items = reopened.events(organization_id=ORG, session_id=cleanup_done, limit=8)
    assert [i.action for i in done_items] == [
        "CLEANUP_STARTED",
        "CLEANUP_COMPLETED",
    ]
    assert reopened._journal.record_count == journal_records  # noqa: SLF001 -- no new writes
    reopened.close()


# -- History-only recovery mode (post-activation rollback) ------------------------


def _history_only(policy: Any, **overrides: Any) -> SpatialDataAuditWorkingSetV1:
    return _ws(policy, allowed_operation_scope="history-only", **overrides)


def test_history_only_boots_over_post_legacy_history_and_denies_admissions(
    tmp_path: Path,
) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    live = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(live, 1, at=NOW)
    for index in range(2, 515):
        _cycle(live, index, at=NOW + timedelta(seconds=index))
    live_count = journal.record_count
    live.close()
    # Naive rollback bricks boot: the legacy constructor replays the extended
    # history and refuses once the lifetime session bound is exceeded.
    legacy_journal = DurableJournal(journal_path)
    with pytest.raises(SpatialDataAuditRecoveryError):
        SpatialDataAuditStore(legacy_journal, policy=policy)
    legacy_journal.close()
    # Scope switch keeps the existing closed index: the recovery activation
    # reuses the same derived file, rebuilding it from the retained journal
    # within explicit bounds (the journal itself is never rewritten).
    before_switch = journal_path.read_bytes()
    # Recovery mode boots over the same retained history.
    recovery_journal = DurableJournal(journal_path)
    recovery = SpatialDataAuditStore(
        recovery_journal, policy=policy, working_set=_history_only(policy)
    )
    assert recovery.operation_scope == "history-only"
    assert journal_path.read_bytes() == before_switch
    assert recovery._history.get_meta("prev_config_digest") == _ws(policy).config_digest()  # noqa: SLF001
    recorded_binding = json.loads(recovery._history.get_meta("audit_working_set_json"))  # noqa: SLF001
    assert recorded_binding["allowed_operation_scope"] == "history-only"
    assert recorded_binding["activation_id"] == "test-activation-01"
    assert recovery.unfinished(organization_id=ORG, limit=8) == ()
    items = recovery.events(organization_id=ORG, session_id=first, limit=64)
    assert [item.action for item in items] == [
        "DOWNLOAD_ADMITTED",
        "STREAM_STARTED",
        "STREAM_COMPLETED",
    ]
    # Every genuinely new admission is denied before any side effect;
    # exact retries of retained events stay silent no-ops (no new write).
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        recovery.append(_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=NOW, job_index=10**6))
    before_noop = recovery_journal.record_count
    recovery.append(items[0].model_copy(deep=True))
    assert recovery_journal.record_count == before_noop
    assert recovery_journal.record_count == live_count
    assert [i.action for i in recovery.events(organization_id=ORG, session_id=first, limit=8)][
        -1
    ] == "STREAM_COMPLETED"
    recovery.close()
    # Restart in the same mode: no fabrication, no loss.
    journal2 = DurableJournal(journal_path)
    again = SpatialDataAuditStore(journal2, policy=policy, working_set=_history_only(policy))
    assert again.unfinished(organization_id=ORG, limit=8) == ()
    assert len(again.events(organization_id=ORG, session_id=first, limit=64)) == 3
    assert journal2.record_count == live_count
    again.close()


def test_history_only_preserves_unfinished_without_completion(
    tmp_path: Path,
) -> None:
    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    live = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    open_session = str(uuid4())
    live.append(_event(open_session, "DOWNLOAD_ADMITTED", at=NOW, job_index=61))
    _cycle(live, 62, at=NOW)
    live_count = journal.record_count
    live.close()
    recovery = SpatialDataAuditStore(
        DurableJournal(journal_path), policy=policy, working_set=_history_only(policy)
    )
    pending = recovery.unfinished(organization_id=ORG, limit=8)
    assert [item.session_id for item in pending] == [open_session]
    open_items = recovery.events(organization_id=ORG, session_id=open_session, limit=8)
    assert [i.action for i in open_items] == ["DOWNLOAD_ADMITTED"]
    # Continuations are denied too: unfinished evidence is preserved, never
    # auto-completed, and the denial writes nothing.
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        recovery.append(_event(open_session, "STREAM_STARTED", at=NOW, job_index=61))
    assert recovery._journal.record_count == live_count  # noqa: SLF001
    recovery.close()
    again = SpatialDataAuditStore(
        DurableJournal(journal_path), policy=policy, working_set=_history_only(policy)
    )
    assert [item.session_id for item in again.unfinished(organization_id=ORG, limit=8)] == [
        open_session
    ]
    again.close()


def test_history_only_serves_cleanup_history_and_refuses_cleanup(
    tmp_path: Path,
) -> None:
    from ksi_core.domains.external.delivery.cleanup import run_spatial_data_cleanup_once

    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    live = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    cleanup_open = str(uuid4())
    live.append(_event(cleanup_open, "CLEANUP_STARTED", at=NOW, job_index=71))
    cleanup_done = str(uuid4())
    live.append(_event(cleanup_done, "CLEANUP_STARTED", at=NOW, job_index=72))
    live.append(_event(cleanup_done, "CLEANUP_COMPLETED", at=NOW, job_index=72))
    live_count = journal.record_count
    live.close()
    recovery = SpatialDataAuditStore(
        DurableJournal(journal_path), policy=policy, working_set=_history_only(policy)
    )
    assert [i.session_id for i in recovery.unfinished(organization_id=ORG, limit=8)] == [
        cleanup_open
    ]
    kept = recovery.events(organization_id=ORG, session_id=cleanup_done, limit=8)
    assert [i.action for i in kept] == [
        "CLEANUP_STARTED",
        "CLEANUP_COMPLETED",
    ]
    calls: list[str] = []
    with pytest.raises(SpatialDataDomainError, match="PERMISSION_DENIED"):
        run_spatial_data_cleanup_once(
            jobs=_raising_proxy(calls, "jobs"),
            storage=_raising_proxy(calls, "storage"),
            audit=recovery,
            now=NOW,
        )
    assert calls == []
    assert recovery._journal.record_count == live_count  # noqa: SLF001
    recovery.close()


def test_history_only_config_loads_and_binds_policy(tmp_path: Path) -> None:
    policy = _policy()
    config = _history_only(policy)
    target = tmp_path / "audit-ws-history.json"
    target.write_bytes(json.dumps(config.model_dump(mode="json")).encode())
    os.chmod(target, 0o600)
    loaded = load_spatial_data_audit_working_set(target)
    assert loaded.allowed_operation_scope == "history-only"
    assert loaded.policy_digest == policy.policy_digest
    assert loaded.config_digest() == config.config_digest()


def test_working_set_config_change_refuses_reinterpretation(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    store = _store(tmp_path, policy=policy)
    _cycle(store, 1, at=NOW)
    store.close()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    with pytest.raises(
        SpatialDataAuditRecoveryError, match="configuration changed under retained index"
    ):
        SpatialDataAuditStore(
            journal, policy=policy, working_set=_history_only(policy, activation_id="other-id")
        )
    journal.close()


def test_working_set_config_rejects_missing_fields_and_coercions() -> None:
    import pydantic

    policy = _policy()
    base = dict(
        version="spatial-data-audit-working-set.v1",
        policy_digest=policy.policy_digest,
        journal_file_name="spatial-data-audit.jsonl",
        allowed_operation_scope="download-only",
        activation_id="test-activation-01",
        active_session_cap=512,
        index_disk_bytes=8 * 1024 * 1024,
        index_cache_allowance_bytes=128 * 1024,
        max_boot_scan_bytes=64 * 1024 * 1024,
        max_boot_seconds=60.0,
        max_tail_records=4096,
        max_tail_bytes=16 * 1024 * 1024,
    )
    dropped = dict(base)
    del dropped["max_tail_bytes"]
    with pytest.raises(pydantic.ValidationError):
        SpatialDataAuditWorkingSetV1(**dropped)
    for field, bad in [
        ("active_session_cap", True),
        ("active_session_cap", "512"),
        ("active_session_cap", 512.0),
        ("max_boot_seconds", "60.0"),
        ("max_boot_seconds", True),
        ("index_disk_bytes", "8388608"),
    ]:
        coerced = dict(base)
        coerced[field] = bad
        with pytest.raises(pydantic.ValidationError):
            SpatialDataAuditWorkingSetV1(**coerced)


def test_working_set_loader_rejects_duplicates_symlink_oversize(tmp_path: Path) -> None:
    policy = _policy()
    good = json.dumps(_ws(policy).model_dump(mode="json"))
    dup = good.replace(
        '"activation_id": "test-activation-01"',
        '"activation_id": "test-activation-01", "activation_id": "test-activation-02"',
        1,
    )
    assert dup != good
    dup_path = tmp_path / "dup.json"
    dup_path.write_bytes(dup.encode())
    os.chmod(dup_path, 0o600)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_spatial_data_audit_working_set(dup_path)
    real = tmp_path / "real.json"
    real.write_bytes(good.encode())
    os.chmod(real, 0o600)
    link = tmp_path / "link.json"
    link.symlink_to(real)
    with pytest.raises(ValueError):
        load_spatial_data_audit_working_set(link)
    big = tmp_path / "big.json"
    big.write_bytes(b" " * (64 * 1024 + 1))
    os.chmod(big, 0o600)
    with pytest.raises(ValueError, match="size budget"):
        load_spatial_data_audit_working_set(big)


# -- Download-only operation scope ----------------------------------------------


def _spy_storage(base: Any) -> SimpleNamespace:
    calls: dict[str, int] = {
        "delete_owned_version": 0,
        "list_owned_versions": 0,
        "observe_owned_output": 0,
        "open_version": 0,
        "issue_output_put": 0,
    }
    from contextlib import contextmanager

    class Spy:
        def delete_owned_version(self, *args: Any, **kwargs: Any) -> None:
            calls["delete_owned_version"] += 1
            raise AssertionError("cleanup storage mutation under read-only scope")

        def list_owned_versions(self, *args: Any, **kwargs: Any) -> Any:
            calls["list_owned_versions"] += 1
            raise AssertionError("cleanup inventory under read-only scope")

        def observe_owned_output(self, *args: Any, **kwargs: Any) -> Any:
            calls["observe_owned_output"] += 1
            return base.observe_owned_output(*args, **kwargs)

        @contextmanager
        def open_version(self, *args: Any, **kwargs: Any) -> Any:
            calls["open_version"] += 1
            with base.open_version(*args, **kwargs) as chunks:
                yield chunks

        def issue_source_get(self, *args: Any, **kwargs: Any) -> Any:
            return base.issue_source_get(*args, **kwargs)

        def issue_output_put(self, *args: Any, **kwargs: Any) -> Any:
            calls["issue_output_put"] += 1
            raise AssertionError("upload capability under read-only scope")

    return SimpleNamespace(storage=Spy(), calls=calls)


def _raising_proxy(calls: list[str], label: str) -> Any:
    class _Refuse:
        def __getattr__(self, name: str) -> Any:
            def _refused(*args: Any, **kwargs: Any) -> Any:
                calls.append(f"{label}.{name}")
                raise AssertionError(f"{label} call under disabled cleanup: {name}")

            return _refused

    return _Refuse()


def test_cleanup_once_refuses_before_any_jobs_or_storage(tmp_path: Path) -> None:
    from datetime import datetime

    from ksi_core.domains.external.delivery.cleanup import run_spatial_data_cleanup_once

    calls: list[str] = []
    policy = _policy()
    audit = SpatialDataAuditStore(
        DurableJournal(tmp_path / "guard-audit.jsonl"),
        policy=policy,
        working_set=_ws(policy, journal_file_name="guard-audit.jsonl"),
    )
    assert audit.operation_scope == "download-only"
    with pytest.raises(SpatialDataDomainError, match="PERMISSION_DENIED"):
        run_spatial_data_cleanup_once(
            jobs=_raising_proxy(calls, "jobs"),
            storage=_raising_proxy(calls, "storage"),
            audit=audit,
            now=datetime.now(UTC),
        )
    assert calls == []
    audit.close()


def _wiring_graph(tmp_path: Path) -> Any:
    """job_graph equivalent with a workspace envelope that fits a working set."""
    from datetime import timedelta

    from ksi_core.domains.external.delivery.grants import (
        SpatialDataGrantAuthorizer,
        SpatialDataGrantStore,
    )
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.identity.auth import Principal, PrincipalKind
    from ksi_event_contracts.processing_job import ExecutionLocus
    from spatial_data_fixture import make_activation, make_grant, make_runtime
    from spatial_data_job_fixture import NOW as AUTH_NOW
    from spatial_data_job_fixture import LocalJobAuthority
    from spatial_data_source_fixture import source_identity, source_resolver, source_stores

    graph = source_stores(tmp_path)
    graph.data_policy = _policy()
    graph.runtime = make_runtime()
    graph.activation = make_activation(
        organization_id=graph.principal.organization_id,
        worker_principal_id="data-worker-1",
        worker_instance_id="instance-1",
        policy_digest=graph.data_policy.policy_digest,
        valid_from=AUTH_NOW - timedelta(minutes=1),
        valid_until=AUTH_NOW + timedelta(minutes=1),
    )
    graph.sources = source_resolver(graph)
    source = graph.sources.resolve(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        asset_ref=source_identity(graph),
        principal=graph.principal,
    )
    graph.grants = SpatialDataGrantStore(
        DurableJournal(tmp_path / "grants.jsonl"), coordinator=graph.coordinator
    )
    graph.grant = make_grant(
        organization_id=graph.principal.organization_id,
        beneficiary_principal_id=graph.principal.principal_id,
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        asset_ref=source.asset_ref,
        observed_crs_digest=source.inspection.measurements.observed_crs_digest,
        allowed_bounds=(0, 0, 2, 2),
        policy_digest=graph.data_policy.policy_digest,
        valid_from=AUTH_NOW - timedelta(minutes=1),
        valid_until=AUTH_NOW + timedelta(minutes=1),
    )
    graph.grants.provision(graph.grant)
    graph.authorizer = SpatialDataGrantAuthorizer(
        grants=graph.grants, sites=graph.sites, processing_location=ExecutionLocus.SITE_ONPREM
    )
    graph.authority = LocalJobAuthority(graph)
    graph.worker = Principal(
        principal_id="data-worker-1",
        organization_id=graph.principal.organization_id,
        kind=PrincipalKind.SPATIAL_DATA_WORKER,
        role=None,
        device_id=None,
    )
    graph.source = source
    graph.path = tmp_path
    return graph


def _full_wiring(tmp_path: Path, graph: Any, *, working_set: Any) -> Any:
    from ksi_core.composition.spatial_data_graph import (
        SpatialDataLocalGraphConfig,
        build_spatial_data_wiring,
    )
    from ksi_event_contracts.processing_job import ExecutionLocus
    from test_spatial_data_storage import sdk_storage

    storage, _supervisor = sdk_storage(tmp_path)

    def journal(name: str, **kwargs: Any) -> DurableJournal:
        return DurableJournal(tmp_path / name, max_segment_bytes=None, **kwargs)

    spool = tmp_path / "spool"
    spool.mkdir(mode=0o700)
    return build_spatial_data_wiring(
        journal=journal,
        config=SpatialDataLocalGraphConfig(
            graph.data_policy,
            graph.runtime,
            graph.activation,
            ExecutionLocus.SITE_ONPREM,
            lambda: NOW,
        ),
        reconstruction=graph.reconstruction,
        inspections=graph.inspections,
        sites=graph.sites,
        work_areas=graph.work_areas,
        work_orders=graph.work_orders,
        coordinator=graph.coordinator,
        storage=storage,
        currentness=graph.authority,
        spool_root=spool,
        audit_working_set=working_set,
    )


def test_start_cleanup_refuses_download_only_wiring(tmp_path: Path) -> None:
    from ksi_core.composition.spatial_data_production import (
        SpatialDataCleanupDisabledError,
        start_spatial_data_cleanup,
    )

    graph = _wiring_graph(tmp_path)
    wiring = _full_wiring(tmp_path, graph, working_set=_ws(graph.data_policy))
    assert wiring.downloads.audit_store.operation_scope == "download-only"
    with pytest.raises(SpatialDataCleanupDisabledError):
        start_spatial_data_cleanup(wiring, interval_seconds=300)


def test_start_cleanup_starts_legacy_wiring(tmp_path: Path) -> None:
    from ksi_core.composition.spatial_data_production import start_spatial_data_cleanup

    graph = _wiring_graph(tmp_path)
    wiring = _full_wiring(tmp_path, graph, working_set=None)
    assert wiring.downloads.audit_store.operation_scope == "full"
    loop = start_spatial_data_cleanup(wiring, interval_seconds=300)
    try:
        assert loop.running
    finally:
        loop.stop(timeout_seconds=10)


def test_read_flows_do_zero_storage_writes_or_deletes(tmp_path: Path) -> None:
    from spatial_data_download_fixture import FreshCredentials, delivery_graph
    from spatial_data_job_fixture import NOW as FIXTURE_NOW

    graph = delivery_graph(tmp_path)
    spy = _spy_storage(graph.storage)
    service = graph.service
    service.storage = spy.storage
    for _ in range(3):
        prepared = service.prepare(
            job_id=graph.issued.job_id,
            principal=graph.graph.principal,
            credentials=FreshCredentials(graph.graph.principal),
            now=FIXTURE_NOW,
        )
        assert b"".join(prepared.iter_chunks()) == graph.payload
        prepared.close()
    assert spy.calls["delete_owned_version"] == 0
    assert spy.calls["list_owned_versions"] == 0
    assert spy.calls["issue_output_put"] == 0
    assert spy.calls["open_version"] == 3


# -- Stream cursor exactness + torn-tail + line caps (Foundation) ---------------


def _raw_journal(path: Path, lines: list[bytes]) -> DurableJournal:
    with open(path, "wb") as handle:
        for line in lines:
            handle.write(line + b"\n")
    return DurableJournal(path, max_segment_bytes=None)


def _raw_record(payload: dict, seq: int) -> bytes:
    return json.dumps(
        {"recordType": "spatial-data-audit.v1", "sequence": seq, "event": payload},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode()


def _valid_event_dict(session: str, action: str, **overrides: object) -> dict:
    base: dict[str, object] = {
        "event_id": str(uuid4()),
        "session_id": session,
        "organization_id": ORG,
        "principal_id": "reader-test",
        "site_id": "site-test",
        "work_area_id": "area-test",
        "job_id": _job(1),
        "at": datetime.now(UTC).isoformat(),
        "action": action,
        "expected_size_bytes": 1024,
        "output_sha256": "sha256:" + "ab" * 32,
        "sent_bytes": 0,
        "reason": None,
        "event_digest": None,
    }
    if "sent" in overrides:
        sent_override = overrides.pop("sent")
        overrides = {**overrides, "sent_bytes": sent_override}
    base.update(overrides)
    event = SpatialDataAuditEventV1.model_validate(base).sealed()
    return event.model_dump(by_alias=True, mode="json")


def test_stream_exact_cursor_never_loses_rows(tmp_path: Path) -> None:
    rows = [
        b'{"n":1}',
        b'{"n":22}',
        b'{"n":333}',
    ]
    journal = _raw_journal(tmp_path / "s.jsonl", rows)
    first, cursor, eof = journal.stream_records(
        (0, 0), limit_records=1, limit_bytes=65536, max_line_bytes=65536
    )
    assert not eof
    assert [item[3] for item in first] == [{"n": 1}]
    assert cursor == (0, len(rows[0]) + 1)
    second, cursor, eof = journal.stream_records(
        cursor, limit_records=1, limit_bytes=65536, max_line_bytes=65536
    )
    assert not eof
    assert [item[3] for item in second] == [{"n": 22}]
    assert cursor == (0, len(rows[0]) + 1 + len(rows[1]) + 1)
    third, cursor, eof = journal.stream_records(
        cursor, limit_records=10, limit_bytes=65536, max_line_bytes=65536
    )
    assert eof
    assert [item[3] for item in third] == [{"n": 333}]
    assert cursor == (1, 0)
    journal.close()


def test_stream_torn_tail_neither_lost_nor_accepted(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    with open(path, "wb") as handle:
        handle.write(b'{"a": 1}\n{"b": 2}\n{"c": 3')
    journal = DurableJournal.open_read_only(path)
    items, cursor, eof = journal.stream_records(
        (0, 0), limit_records=10, limit_bytes=65536, max_line_bytes=65536
    )
    assert [item[3] for item in items] == [{"a": 1}, {"b": 2}]
    assert eof is False
    assert cursor == (0, len(b'{"a": 1}\n{"b": 2}\n'))
    again, cursor2, eof2 = journal.stream_records(
        cursor, limit_records=10, limit_bytes=65536, max_line_bytes=65536
    )
    assert again == [] and eof2 is False and cursor2 == cursor
    journal.close()


def test_stream_line_cap_and_missing_file_and_budget_shape(tmp_path: Path) -> None:
    journal = _raw_journal(tmp_path / "s.jsonl", [b'{"n":1}'])
    with pytest.raises(JournalRecoveryError, match="줄 상한"):
        journal.stream_records((0, 0), limit_records=10, limit_bytes=65536, max_line_bytes=4)
    with pytest.raises(ValueError, match="max_line_bytes"):
        journal.stream_records((0, 0), limit_records=10, limit_bytes=64, max_line_bytes=65)
    with pytest.raises(ValueError, match="stream limits"):
        journal.stream_records((0, 0), limit_records=0, limit_bytes=64, max_line_bytes=64)
    with pytest.raises(ValueError, match="stream cursor"):
        journal.stream_records((-1, 0), limit_records=1, limit_bytes=64, max_line_bytes=64)
    missing = DurableJournal(tmp_path / "absent.jsonl")
    items, cursor, eof = missing.stream_records(
        (0, 0), limit_records=10, limit_bytes=65536, max_line_bytes=65536
    )
    assert items == [] and eof is True and cursor == (1, 0)
    missing.close()
    journal.close()


def test_stream_progression_across_small_chunks(tmp_path: Path) -> None:
    rows = [
        json.dumps({"n": i, "pad": "x" * 40}, ensure_ascii=True, separators=(",", ":")).encode()
        for i in range(9)
    ]
    journal = _raw_journal(tmp_path / "s.jsonl", rows)
    got: list[dict] = []
    cursor: tuple[int, int] = (0, 0)
    eof = False
    guards = 0
    while not eof:
        guards += 1
        assert guards < 50
        items, cursor, eof = journal.stream_records(
            cursor, limit_records=2, limit_bytes=150, max_line_bytes=150
        )
        got.extend(item[3] for item in items)
    assert [item["n"] for item in got] == list(range(9))
    journal.close()


# -- Canonical history validation on rebuild + tail ----------------------------


def _corrupt_variants(session: str) -> dict[str, list[dict]]:
    admitted = _valid_event_dict(session, "DOWNLOAD_ADMITTED")
    started = _valid_event_dict(session, "STREAM_STARTED")
    completed = _valid_event_dict(session, "STREAM_COMPLETED", sent=1024)
    denied = _valid_event_dict(session, "DENIED", reason="GRANT_REQUIRED")
    foreign = _valid_event_dict(session, "STREAM_STARTED", organization_id=OTHER_ORG)
    return {
        "skipped_transition": [admitted, completed],
        "identity_change": [admitted, foreign],
        "uncompleted_first": [started],
        "uncompleted_only_denied_ok": [denied],
    }


def _write_raw_journal(path: Path, events: list[dict]) -> None:
    with open(path, "wb") as handle:
        for seq, event in enumerate(events, start=1):
            handle.write(_raw_record(event, seq) + b"\n")
    # The indexed boot pins the journal file (0600, single link); raw
    # fixtures must look like a real journal so the corruption tests below
    # exercise record validation, not file-identity refusal.
    os.chmod(path, 0o600)


def test_rebuild_refuses_every_canonical_corruption(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    session = str(uuid4())
    variants = _corrupt_variants(session)
    bad_sent = _valid_event_dict(session, "STREAM_COMPLETED", sent=3)
    variants["bad_sent_bytes"] = [
        _valid_event_dict(session, "DOWNLOAD_ADMITTED"),
        _valid_event_dict(session, "STREAM_STARTED"),
        bad_sent,
    ]
    unsealed = _valid_event_dict(session, "DOWNLOAD_ADMITTED")
    unsealed.pop("eventDigest", None)
    variants["unsealed"] = [unsealed]
    early = _valid_event_dict(session, "STREAM_STARTED", at="2020-01-01T00:00:00Z")
    variants["time_travel"] = [
        _valid_event_dict(session, "DOWNLOAD_ADMITTED"),
        early,
    ]
    gap_first = _valid_event_dict(session, "DOWNLOAD_ADMITTED")
    gap_second = _valid_event_dict(session, "STREAM_STARTED")
    variants["sequence_gap"] = [gap_first, gap_second]
    for name, events in variants.items():
        if name == "uncompleted_only_denied_ok":
            continue
        path = tmp_path / f"corrupt-{name}.jsonl"
        ws = _ws(policy, journal_file_name=path.name)
        if name == "sequence_gap":
            with open(path, "wb") as handle:
                handle.write(_raw_record(events[0], 1) + b"\n")
                handle.write(_raw_record(events[1], 3) + b"\n")
            os.chmod(path, 0o600)
        else:
            _write_raw_journal(path, events)
        before = path.read_bytes()
        journal = DurableJournal(path, max_segment_bytes=None)
        with pytest.raises(SpatialDataAuditRecoveryError):
            SpatialDataAuditStore(journal, policy=policy, working_set=ws)
        journal.close()
        assert path.read_bytes() == before


def test_rebuild_accepts_denied_singleton(tmp_path: Path) -> None:
    policy = _policy()
    session = str(uuid4())
    events = _corrupt_variants(session)["uncompleted_only_denied_ok"]
    _write_raw_journal(tmp_path / "ok.jsonl", events)
    journal = DurableJournal(tmp_path / "ok.jsonl")
    store = SpatialDataAuditStore(
        journal, policy=policy, working_set=_ws(policy, journal_file_name="ok.jsonl")
    )
    assert [i.action for i in store.events(organization_id=ORG, session_id=session, limit=8)] == [
        "DENIED"
    ]
    store.close()


def test_tail_refuses_post_terminal_admission_and_preserves_journal(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    session = _cycle(store, 1, at=NOW)
    store.close()
    before = (tmp_path / "spatial-data-audit.jsonl").read_bytes()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    journal2.append(
        _Record(
            sequence=4, event=_event(session, "DOWNLOAD_ADMITTED", at=NOW, job_index=1)
        ).model_dump(by_alias=True, mode="json")
    )
    journal2.close()
    assert (tmp_path / "spatial-data-audit.jsonl").read_bytes() != before
    after_injected = (tmp_path / "spatial-data-audit.jsonl").read_bytes()
    journal3 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    with pytest.raises(SpatialDataAuditRecoveryError):
        SpatialDataAuditStore(journal3, policy=policy, working_set=_ws(policy))
    journal3.close()
    assert (tmp_path / "spatial-data-audit.jsonl").read_bytes() == after_injected


def test_tail_refuses_invalid_transition_and_preserves_journal(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    session = str(uuid4())
    store.append(_event(session, "DOWNLOAD_ADMITTED", at=NOW, job_index=5))
    store.append(_event(session, "STREAM_STARTED", at=NOW, job_index=5))
    store.close()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    journal2.append(
        _Record(
            sequence=3,
            event=_event(session, "STREAM_COMPLETED", at=NOW, sent=7, job_index=5),
        ).model_dump(by_alias=True, mode="json")
    )
    journal2.close()
    after_injected = (tmp_path / "spatial-data-audit.jsonl").read_bytes()
    journal3 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    with pytest.raises(SpatialDataAuditRecoveryError):
        SpatialDataAuditStore(journal3, policy=policy, working_set=_ws(policy))
    journal3.close()
    assert (tmp_path / "spatial-data-audit.jsonl").read_bytes() == after_injected


# -- Index correspondence: deletion / wrong addresses / stale checkpoints -----


def _open_sqlite(path: Path):  # type: ignore[no-untyped-def]
    import sqlite3

    connection = sqlite3.connect(str(path))
    connection.isolation_level = None
    return connection


def test_index_logical_deletion_triggers_rebuild_not_silence(tmp_path: Path) -> None:
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    second = _cycle(store, 2, at=NOW + timedelta(seconds=1))
    store.close()
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    connection = _open_sqlite(index_path)
    connection.execute("DELETE FROM events")
    connection.execute("DELETE FROM session_order")
    connection.execute("DELETE FROM sessions")
    connection.commit()
    connection.close()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    rebuilt = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    assert [i.action for i in rebuilt.events(organization_id=ORG, session_id=first, limit=8)] == [
        "DOWNLOAD_ADMITTED",
        "STREAM_STARTED",
        "STREAM_COMPLETED",
    ]
    assert [i.action for i in rebuilt.events(organization_id=ORG, session_id=second, limit=8)][
        -1
    ] == ("STREAM_COMPLETED")
    assert rebuilt._history is not None
    stats = rebuilt._history.stats()  # noqa: SLF001
    assert stats == (2, 6, 6)
    rebuilt.close()


def test_index_wrong_address_seals_instead_of_serving(tmp_path: Path) -> None:
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    store.close()
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    connection = _open_sqlite(index_path)
    connection.execute("UPDATE events SET offset = offset + 3")
    connection.commit()
    connection.close()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    reopened = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        reopened.events(organization_id=ORG, session_id=first, limit=8)
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        reopened.append(_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=NOW, job_index=9))
    reopened.close()


def test_index_wrong_session_binding_seals(tmp_path: Path) -> None:
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    other = _cycle(store, 2, at=NOW + timedelta(seconds=1))
    store.close()
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    connection = _open_sqlite(index_path)
    connection.execute(
        "UPDATE events SET session_id = ? WHERE session_id = ?",
        (other, first),
    )
    connection.commit()
    connection.close()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    reopened = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        reopened.events(organization_id=ORG, session_id=first, limit=8)
    reopened.close()


def test_stale_checkpoint_rebuilds_without_duplication(tmp_path: Path) -> None:
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    _cycle(store, 2, at=NOW + timedelta(seconds=1))
    store.close()
    before = (tmp_path / "spatial-data-audit.jsonl").read_bytes()
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    connection = _open_sqlite(index_path)
    connection.execute("UPDATE meta SET value = '1' WHERE key = 'max_seq'")
    connection.commit()
    connection.close()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    rebuilt = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    assert [i.action for i in rebuilt.events(organization_id=ORG, session_id=first, limit=8)] == [
        "DOWNLOAD_ADMITTED",
        "STREAM_STARTED",
        "STREAM_COMPLETED",
    ]
    assert rebuilt._history is not None
    stats = rebuilt._history.stats()  # noqa: SLF001
    assert stats == (2, 6, 6)
    assert (tmp_path / "spatial-data-audit.jsonl").read_bytes() == before
    rebuilt.close()


def test_hot_deletion_blocks_retry_without_journal_growth(tmp_path: Path) -> None:
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    before = journal.record_count
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    connection = _open_sqlite(index_path)
    connection.execute("DELETE FROM events WHERE session_id = ?", (first,))
    connection.execute("DELETE FROM session_order WHERE session_id = ?", (first,))
    connection.execute("DELETE FROM sessions WHERE session_id = ?", (first,))
    connection.commit()
    connection.close()
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        store.append(_event(first, "STREAM_COMPLETED", at=NOW, sent=1024, job_index=1))
    assert journal.record_count == before
    store.close()


def test_wrong_page_size_rebuilds_fresh(tmp_path: Path) -> None:
    import sqlite3

    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    store.close()
    foreign = tmp_path / "foreign.sqlite3"
    connection = sqlite3.connect(str(foreign))
    connection.execute("PRAGMA page_size = 8192")
    connection.execute("VACUUM")
    connection.execute("CREATE TABLE t(x)")
    connection.commit()
    assert connection.execute("PRAGMA page_size").fetchone()[0] == 8192
    connection.close()
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    index_path.unlink()
    foreign.rename(index_path)
    os.chmod(index_path, 0o600)
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    rebuilt = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    assert [i.action for i in rebuilt.events(organization_id=ORG, session_id=first, limit=8)][
        0
    ] == ("DOWNLOAD_ADMITTED")
    rebuilt.close()


def test_unfinished_query_uses_bounded_plan(tmp_path: Path) -> None:
    import sqlite3

    policy = _policy()
    store = _store(tmp_path, policy=policy)
    for index in range(3):
        session = str(uuid4())
        store.append(_event(session, "DOWNLOAD_ADMITTED", at=NOW, job_index=index))
    store.close()
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    connection = sqlite3.connect(str(index_path))
    plan = "\n".join(
        str(row)
        for row in connection.execute(
            "EXPLAIN QUERY PLAN SELECT session_id, organization_id, last_seq FROM sessions"
            " WHERE terminal_action IS NULL ORDER BY created_seq LIMIT 8"
        ).fetchall()
    )
    connection.close()
    assert "TEMP B-TREE" not in plan
    assert "USING INDEX" in plan or "USING COVERING INDEX" in plan


# -- Factory wiring: bounded journal, shared workspace, index budgets ---------


def test_factory_audit_journal_retains_no_history(tmp_path: Path) -> None:

    graph = _wiring_graph(tmp_path)
    wiring = _full_wiring(tmp_path, graph, working_set=_ws(graph.data_policy))
    audit = wiring.downloads.audit_store
    assert audit.operation_scope == "download-only"
    assert audit._journal.retains_records is False  # noqa: SLF001
    assert audit._journal._records == []  # noqa: SLF001
    with pytest.raises(JournalError):
        audit._journal.replay()  # noqa: SLF001
    base = NOW
    for index in range(600):
        session = str(uuid4())
        audit.append(_event(session, "DOWNLOAD_ADMITTED", at=base, job_index=index))
        audit.append(_event(session, "STREAM_STARTED", at=base, job_index=index))
        audit.append(_event(session, "STREAM_COMPLETED", at=base, sent=1024, job_index=index))
    assert audit._journal._records == []  # noqa: SLF001
    assert audit._journal.record_count == 1800
    assert len(audit._sessions) == 0  # noqa: SLF001
    audit.append(_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=base, job_index=10**6))


def test_cross_org_global_workspace_counts_audit_disk(tmp_path: Path) -> None:
    from threading import RLock

    policy = _policy()
    store = _store(tmp_path, policy=policy)
    for index in range(5):
        _cycle(store, index, at=NOW + timedelta(seconds=index))
    service = SimpleNamespace(
        _lock=RLock(),
        _counts={},
        _reserved=0,
        policy=policy,
        audit_store=store,
    )
    from ksi_core.domains.external.delivery.downloads import SpatialDataDownloadService

    bound_reserve = SpatialDataDownloadService._reserve.__get__(service, SimpleNamespace)
    disk = store.disk_reserved_bytes()
    assert disk > 0
    workspace = policy.resource_envelope.max_workspace_bytes
    service._counts["org-a"] = 4
    service._counts["org-b"] = 3
    service._counts["org-c"] = 1
    service._reserved = 0
    with pytest.raises(SpatialDataDomainError, match="CONCURRENCY_LIMIT_EXCEEDED"):
        bound_reserve("org-d", 1)
    service._counts = {}
    with pytest.raises(SpatialDataDomainError, match="WORKSPACE_LIMIT_EXCEEDED"):
        bound_reserve("org-a", workspace - disk + 1)
    bound_reserve("org-a", workspace - disk)
    assert service._reserved == workspace - disk


def test_index_page_budget_refuses_growth(tmp_path: Path) -> None:
    index_path = tmp_path / "tiny.ws.sqlite3"
    index = AuditHistoryIndex(index_path, max_pages=32, create=True)
    with pytest.raises(AuditIndexFull):
        for seq in range(1, 5000):
            index.commit_event(
                seq=seq,
                event_id=str(uuid4()),
                session_id=str(uuid4()),
                organization_id=ORG,
                terminal_action="DENIED",
                file_index=0,
                offset=seq * 64,
                length=64,
                session_position=0,
                checkpoint_meta={"max_seq": str(seq)},
            )
    index.close()


def test_store_maps_index_full_to_resource_limit_and_seals(tmp_path: Path) -> None:
    policy = _policy()
    store = _store(tmp_path, policy=policy)
    before = store._journal.record_count  # noqa: SLF001
    assert store._history is not None
    real_commit = store._history.commit_event_in_write_txn  # noqa: SLF001

    def _full(*args: object, **kwargs: object) -> None:
        raise AuditIndexFull("test page budget exhausted")

    assert store._history is not None
    store._history.commit_event_in_write_txn = _full  # type: ignore[method-assign]
    try:
        with pytest.raises(SpatialDataDomainError, match="RESOURCE_LIMIT_EXCEEDED"):
            store.append(_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=NOW, job_index=77))
        with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
            store.append(_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=NOW, job_index=78))
    finally:
        assert store._history is not None
        store._history.commit_event_in_write_txn = real_commit  # type: ignore[method-assign]
    assert store._journal.record_count == before + 1  # noqa: SLF001 -- durable first
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    assert index_path.exists()


def test_existing_oversize_index_refuses_boot(tmp_path: Path) -> None:
    index_path = tmp_path / "small.ws.sqlite3"
    index = AuditHistoryIndex(index_path, max_pages=100, create=True)
    for seq in range(1, 40):
        index.commit_event(
            seq=seq,
            event_id=str(uuid4()),
            session_id=str(uuid4()),
            organization_id=ORG,
            terminal_action="DENIED",
            file_index=0,
            offset=seq * 64,
            length=64,
            session_position=0,
            checkpoint_meta={"max_seq": str(seq)},
        )
    assert index.page_count() > 1
    index.close()
    with pytest.raises(AuditIndexCorruption):
        AuditHistoryIndex(index_path, max_pages=1, create=False)


def test_private_dir_rejects_substitutable_ancestors(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    outer.mkdir(mode=0o700)
    loose = outer / "loose"
    loose.mkdir(mode=0o777)
    leaf = loose / "leaf"
    leaf.mkdir(mode=0o700)
    target = leaf / "idx.ws.sqlite3"
    with pytest.raises(AuditIndexError):
        AuditHistoryIndex(target, max_pages=8, create=True)


def test_tail_over_budget_falls_back_to_bounded_rebuild(tmp_path: Path) -> None:
    working_set = _ws(_policy(), max_tail_records=2)
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=working_set)
    first = _cycle(store, 1, at=NOW)
    store.close()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    extra_sessions = []
    for index in range(2, 7):
        session = str(uuid4())
        extra_sessions.append(session)
        base_seq = 3 + (index - 2) * 3
        journal2.append(
            _Record(
                sequence=base_seq + 1,
                event=_event(session, "DOWNLOAD_ADMITTED", at=NOW, job_index=index),
            ).model_dump(by_alias=True, mode="json")
        )
        journal2.append(
            _Record(
                sequence=base_seq + 2,
                event=_event(session, "STREAM_STARTED", at=NOW, job_index=index),
            ).model_dump(by_alias=True, mode="json")
        )
        journal2.append(
            _Record(
                sequence=base_seq + 3,
                event=_event(session, "STREAM_COMPLETED", at=NOW, sent=1024, job_index=index),
            ).model_dump(by_alias=True, mode="json")
        )
    journal2.close()
    before = (tmp_path / "spatial-data-audit.jsonl").read_bytes()
    journal3 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    rebuilt = SpatialDataAuditStore(journal3, policy=policy, working_set=working_set)
    assert [i.action for i in rebuilt.events(organization_id=ORG, session_id=first, limit=8)][
        -1
    ] == "STREAM_COMPLETED"
    for session in extra_sessions:
        assert [
            i.action for i in rebuilt.events(organization_id=ORG, session_id=session, limit=8)
        ] == ["DOWNLOAD_ADMITTED", "STREAM_STARTED", "STREAM_COMPLETED"]
    assert rebuilt._history is not None
    stats = rebuilt._history.stats()  # noqa: SLF001
    assert stats == (6, 18, 18)
    assert (tmp_path / "spatial-data-audit.jsonl").read_bytes() == before
    rebuilt.close()


def test_tail_and_rebuild_budgets_refuse_together(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    _cycle(store, 1, at=NOW)
    store.close()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    journal2.append(
        _Record(
            sequence=4, event=_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=NOW, job_index=3)
        ).model_dump(by_alias=True, mode="json")
    )
    journal2.close()
    journal3 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    with pytest.raises(SpatialDataAuditRecoveryError):
        SpatialDataAuditStore(
            journal3,
            policy=policy,
            working_set=_ws(policy, max_tail_records=1, max_boot_scan_bytes=10),
        )
    journal3.close()


# -- History-only download path: denied before any side effect ----------------

PAYLOAD_1K = bytes(33 + (i % 90) for i in range(1024))


def _stub_storage(
    tmp_path: Path, policy: SpatialDataPolicyV1, payload: bytes, monkeypatch: pytest.MonkeyPatch
) -> SpatialDataS3Storage:
    from ksi_core.domains.external.delivery.storage_supervisor import (
        SpatialDataStorageSupervisor,
    )
    from spatial_data_sdk_stub import SDKStub

    tests_dir = str(Path("tests/contract").resolve())
    monkeypatch.setenv("KSI_CORE_S3_CLIENT_FACTORY", "spatial_data_sdk_stub:client_factory")
    current = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv("PYTHONPATH", tests_dir + os.pathsep + current if current else tests_dir)

    def factory() -> SDKStub:
        return SDKStub(
            tmp_path / "sdk-test.jsonl", body=payload, response_changes={}, behavior=None
        )

    return SpatialDataS3Storage(
        client_factory=factory,
        bucket="local-store",
        source_key_resolver=lambda source: "external-reconstruction/v1/exact-source",
        clock=lambda: (
            __import__("support.external_artifact_inspection_fixtures", fromlist=["NOW"]).NOW
        ),
        policy=policy,
        supervisor=SpatialDataStorageSupervisor(max_concurrency=8),
        operation_timeout_seconds=5.0,
        child_sdk_settings={
            "logPath": str(tmp_path / "sdk-test.jsonl"),
            "body": payload.decode("latin-1"),
            "changes": {},
            "behavior": "",
            "configChanges": {},
            "clientFactoryPath": tests_dir,
        },
    )


def test_history_only_download_denied_before_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    from ksi_core.domains.external.delivery.downloads import SpatialDataDownloadService
    from ksi_core.durable_journal import DurableJournal
    from ksi_event_contracts.spatial_data_worker import SpatialDataUploadDeclarationV1
    from spatial_data_download_fixture import FreshCredentials
    from spatial_data_job_fixture import issue, job_store, lease, receipt_for

    digest = "sha256:" + hashlib.sha256(PAYLOAD_1K).hexdigest()
    graph = _wiring_graph(tmp_path)
    # Job-layer fixtures and the graph activation/grant windows run on the
    # support NOW; audit event timestamps only need per-session monotonicity.
    from spatial_data_job_fixture import NOW as JOB_NOW

    jobs = job_store(graph)
    job = issue(jobs, graph, now=JOB_NOW)
    attempt = lease(jobs, graph, job, now=JOB_NOW)

    storage = _stub_storage(tmp_path, graph.data_policy, PAYLOAD_1K, monkeypatch)
    receipt = receipt_for(jobs, graph, job, attempt, output_hash=digest, now=JOB_NOW)
    receipt = receipt.model_copy(
        update={"output_size_bytes": len(PAYLOAD_1K), "receipt_digest": None}
    ).sealed()
    target = jobs.reserve_output(
        job_id=job.job_id,
        worker=graph.worker,
        attempt=attempt,
        receipt=receipt,
        expires_at=attempt.lease_until,
        now=JOB_NOW,
    )
    observed = storage.observe_owned_output(target)
    assert observed.version_id == "version-1"
    declaration = SpatialDataUploadDeclarationV1(
        attempt=attempt,
        receipt=receipt,
        sha256=receipt.output_sha256,
        size_bytes=len(PAYLOAD_1K),
        content_type="image/tiff",
    ).sealed()
    assert declaration.upload_digest is not None
    jobs.complete(
        job_id=job.job_id,
        worker=graph.worker,
        attempt=attempt,
        upload_digest=declaration.upload_digest,
        observation=observed,
        now=JOB_NOW,
    )

    # Phase A (download-only): 600 terminal filler sessions + one unfinished.
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditStore

    audit_path = tmp_path / "spatial-data-audit.jsonl"
    audit_journal = DurableJournal(audit_path)
    live = SpatialDataAuditStore(
        audit_journal, policy=graph.data_policy, working_set=_ws(graph.data_policy)
    )
    open_session = str(uuid4())
    live.append(_event(open_session, "DOWNLOAD_ADMITTED", at=NOW, job_index=9000))
    for index in range(600):
        session = str(uuid4())
        live.append(_event(session, "DOWNLOAD_ADMITTED", at=NOW, job_index=index))
        live.append(_event(session, "STREAM_STARTED", at=NOW, job_index=index))
        live.append(_event(session, "STREAM_COMPLETED", at=NOW, sent=1024, job_index=index))
    live_count = audit_journal.record_count
    live.close()

    # Phase B (history-only): metadata works, byte reads denied with zero effects.
    history_journal = DurableJournal(audit_path)
    history = SpatialDataAuditStore(
        history_journal, policy=graph.data_policy, working_set=_history_only(graph.data_policy)
    )
    assert history.operation_scope == "history-only"
    assert [item.session_id for item in history.unfinished(organization_id=ORG, limit=8)] == [
        open_session
    ]

    view = jobs.get(job_id=job.job_id, principal=graph.principal, now=JOB_NOW)
    assert view.receipt is not None
    assert view.execution_state is not None

    calls: dict[str, int] = {"open": 0, "observe": 0, "delete": 0, "reserve": 0}

    class StorageSpy:
        def __init__(self, inner: object) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> object:
            if name in {
                "open_version",
                "observe_owned_output",
                "delete_owned_version",
                "list_owned_versions",
                "issue_output_put",
                "issue_source_get",
            }:

                def _refused(*args: object, **kwargs: object) -> object:
                    calls["open"] += 1
                    raise AssertionError(f"storage {name} under history-only read")

                return _refused
            return getattr(self._inner, name)

    class JobsSpy:
        def __init__(self, inner: object) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> object:
            if name in {"reserve_cleanup", "cleanup_pending", "finish_cleanup", "require_cleanup"}:

                def _refused(*args: object, **kwargs: object) -> object:
                    calls["reserve"] += 1
                    raise AssertionError(f"jobs {name} under history-only read")

                return _refused
            return getattr(self._inner, name)

    spool = tmp_path / "spool"
    spool.mkdir(mode=0o700)
    jobs_count = jobs._journal.record_count  # noqa: SLF001
    download_service = SpatialDataDownloadService(
        jobs=cast(Any, JobsSpy(jobs)),
        storage=cast(Any, StorageSpy(storage)),
        audit=history,
        policy=graph.data_policy,
        spool_root=spool,
        clock=lambda: JOB_NOW,
    )
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        download_service.prepare(
            job_id=job.job_id,
            principal=graph.principal,
            credentials=cast(Any, FreshCredentials(graph.principal)),
            now=JOB_NOW,
        )
    assert calls == {"open": 0, "observe": 0, "delete": 0, "reserve": 0}
    assert list(spool.iterdir()) == []
    assert download_service.active_downloads == 0
    assert download_service.reserved_bytes == 0
    assert jobs._journal.record_count == jobs_count  # noqa: SLF001
    assert history._journal.record_count == live_count  # noqa: SLF001
    # Exact retry of a retained event stays a no-op in history-only mode.
    retained = history.events(organization_id=ORG, session_id=open_session, limit=8)
    assert [i.action for i in retained] == ["DOWNLOAD_ADMITTED"]
    history.append(retained[0].model_copy(deep=True))
    assert history._journal.record_count == live_count  # noqa: SLF001
    history.close()


def test_hot_wipe_is_healed_by_rebuild_not_silenced(tmp_path: Path) -> None:
    import sqlite3

    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    _cycle(store, 2, at=NOW)
    store.close()
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    connection = sqlite3.connect(str(index_path))
    connection.execute("DELETE FROM events WHERE session_id = ?", (first,))
    connection.execute("DELETE FROM session_order WHERE session_id = ?", (first,))
    connection.execute("DELETE FROM sessions WHERE session_id = ?", (first,))
    connection.commit()
    connection.close()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    hot = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    # The correspondence check rebuilt the wiped rows from the journal:
    # no silent absence, no duplicate, terminal reopen still refused.
    assert [i.action for i in hot.events(organization_id=ORG, session_id=first, limit=8)] == [
        "DOWNLOAD_ADMITTED",
        "STREAM_STARTED",
        "STREAM_COMPLETED",
    ]
    before = journal2.record_count
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        hot.append(_event(first, "DOWNLOAD_ADMITTED", at=NOW, job_index=10**6))
    assert journal2.record_count == before
    assert hot._history is not None
    stats = hot._history.stats()  # noqa: SLF001
    assert stats == (2, 6, 6)
    hot.close()


def test_journal_fork_refuses_loudly_with_history_preserved(tmp_path: Path) -> None:
    import sqlite3

    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    store.close()
    # External tampering with the authoritative journal itself: append a
    # second admission for the terminal session behind the store's back.
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    journal2.append(
        _Record(
            sequence=4, event=_event(first, "DOWNLOAD_ADMITTED", at=NOW, job_index=9)
        ).model_dump(by_alias=True, mode="json")
    )
    journal2.close()
    preserved = (tmp_path / "spatial-data-audit.jsonl").read_bytes()
    journal3 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    with pytest.raises(SpatialDataAuditRecoveryError, match="retained history invalid"):
        SpatialDataAuditStore(journal3, policy=policy, working_set=_ws(policy))
    journal3.close()
    assert (tmp_path / "spatial-data-audit.jsonl").read_bytes() == preserved
    connection = sqlite3.connect(str(tmp_path / "spatial-data-audit.ws.sqlite3"))
    count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    connection.close()
    assert count == 3


def test_stream_513_records_with_single_record_chunks(tmp_path: Path) -> None:
    rows = [_raw_record({"n": i}, i) for i in range(1, 514)]
    journal = _raw_journal(tmp_path / "s.jsonl", rows)
    got: list[dict] = []
    cursor: tuple[int, int] = (0, 0)
    eof = False
    guards = 0
    while not eof:
        guards += 1
        assert guards < 600
        items, cursor, eof = journal.stream_records(
            cursor, limit_records=1, limit_bytes=65536, max_line_bytes=65536
        )
        got.extend(item[3] for item in items)
    assert len(got) == 513
    assert [item["sequence"] for item in got] == list(range(1, 514))
    assert cursor == (1, 0)
    journal.close()


# -- Strict open, run binding, linkage, envelope, reserve (blocker closure) ---


def test_strict_nonretain_ctor_refuses_before_io(tmp_path: Path) -> None:
    from time import monotonic

    from ksi_core.foundation.durable_journal import JournalError

    raw = b'{"n":1}\n{"partial"'
    path = tmp_path / "strict.jsonl"
    path.write_bytes(raw)
    os.chmod(path, 0o600)
    # Legacy-shaped opens without an explicit mode are refused before any read.
    with pytest.raises(ValueError, match="explicit max_line_bytes"):
        DurableJournal(path, retain_records=False)
    assert path.read_bytes() == raw
    # Budgets without the explicit no-repair flag are refused as well.
    with pytest.raises(ValueError, match="tolerate_torn_tail=False"):
        DurableJournal(
            path,
            retain_records=False,
            max_line_bytes=65537,
            max_recover_bytes=1 << 20,
            recover_deadline=monotonic() + 5,
        )
    assert path.read_bytes() == raw
    # The strict open refuses the torn tail byte-identical — nothing is cut.
    with pytest.raises(JournalRecoveryError, match="완결되지 않은 줄"):
        DurableJournal(
            path,
            retain_records=False,
            max_line_bytes=65537,
            max_recover_bytes=1 << 20,
            recover_deadline=monotonic() + 5,
            tolerate_torn_tail=False,
        )
    assert path.read_bytes() == raw
    with pytest.raises(JournalError):
        DurableJournal(
            path,
            retain_records=False,
            max_line_bytes=65537,
            max_recover_bytes=1 << 20,
            recover_deadline=monotonic() + 5,
            tolerate_torn_tail=False,
        ).replay()


def test_partial_line_bounded_across_chunks(tmp_path: Path) -> None:
    from time import monotonic

    # One newline-free 2000-byte fragment must refuse on a 64-byte cap
    # without ever accumulating the whole input — checked per chunk.
    raw = b"y" * 2000
    path = tmp_path / "carry.jsonl"
    path.write_bytes(raw)
    os.chmod(path, 0o600)
    with pytest.raises(JournalRecoveryError, match="부분 줄"):
        DurableJournal(
            path,
            retain_records=False,
            max_line_bytes=64,
            max_recover_bytes=1 << 20,
            recover_deadline=monotonic() + 5,
            tolerate_torn_tail=False,
        )
    assert path.read_bytes() == raw
    # A complete over-cap line refuses the same way, also byte-identical.
    path2 = tmp_path / "long.jsonl"
    path2.write_bytes(b'{"k":"' + b"z" * 200 + b'"}\n')
    os.chmod(path2, 0o600)
    with pytest.raises(JournalRecoveryError, match="줄 상한"):
        DurableJournal(
            path2,
            retain_records=False,
            max_line_bytes=64,
            max_recover_bytes=1 << 20,
            recover_deadline=monotonic() + 5,
            tolerate_torn_tail=False,
        )
    assert path2.read_bytes() == b'{"k":"' + b"z" * 200 + b'"}\n'


def test_factory_torn_journal_refuses_byte_identical(tmp_path: Path) -> None:
    graph = _wiring_graph(tmp_path)
    audit_path = tmp_path / "spatial-data-audit.jsonl"
    raw = b'{"n":1}\n{"partial"'
    audit_path.write_bytes(raw)
    os.chmod(audit_path, 0o600)
    with pytest.raises(JournalRecoveryError):
        _full_wiring(tmp_path, graph, working_set=_ws(graph.data_policy))
    assert audit_path.read_bytes() == raw


def test_index_sessions_row_deletion_heals_terminal_reopen_refused(tmp_path: Path) -> None:
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    before = (tmp_path / "spatial-data-audit.jsonl").read_bytes()
    store.close()
    # Drop only the parent session row: events, order rows and checkpoint
    # meta stay. Reopen must heal from the journal (never accept the
    # orphan), so the terminal session stays terminal afterwards.
    connection = _open_sqlite(tmp_path / "spatial-data-audit.ws.sqlite3")
    deleted = connection.execute(
        "DELETE FROM sessions WHERE session_id = ?", (first,)
    ).rowcount
    connection.commit()
    connection.close()
    assert deleted == 1
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    reopened = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    assert [i.action for i in reopened.events(organization_id=ORG, session_id=first, limit=8)] == [
        "DOWNLOAD_ADMITTED",
        "STREAM_STARTED",
        "STREAM_COMPLETED",
    ]
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        reopened.append(_event(first, "DOWNLOAD_ADMITTED", at=NOW, job_index=10**6))
    assert journal2.record_count == 3
    assert (tmp_path / "spatial-data-audit.jsonl").read_bytes() == before
    assert reopened._history is not None
    assert reopened._history.stats() == (1, 3, 3)  # noqa: SLF001
    reopened.close()


def test_hot_event_deletion_seals_history_query(tmp_path: Path) -> None:
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    before = journal.record_count
    connection = _open_sqlite(tmp_path / "spatial-data-audit.ws.sqlite3")
    connection.execute("DELETE FROM events WHERE session_id = ?", (first,))
    connection.execute("DELETE FROM session_order WHERE session_id = ?", (first,))
    connection.execute("DELETE FROM sessions WHERE session_id = ?", (first,))
    connection.commit()
    connection.close()
    # The run binding moved under the live store: the retained session must
    # seal on query instead of reporting a forged absence, and the journal
    # must not grow.
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        store.events(organization_id=ORG, session_id=first, limit=8)
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        store.append(_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=NOW, job_index=99))
    assert journal.record_count == before
    store.close()


def test_hardlinked_index_journal_config_refused(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError
    from ksi_core.domains.external.delivery.audit_history_index import AuditIndexError

    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    _cycle(store, 1, at=NOW)
    store.close()
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    before = journal_path.read_bytes()
    # A hard-linked derived index must not open writable.
    os.link(index_path, tmp_path / "alias-index.ws.sqlite3")
    try:
        with pytest.raises(AuditIndexError, match="hard-linked"):
            AuditHistoryIndex(index_path, max_pages=2048, create=True)
        with pytest.raises(SpatialDataAuditRecoveryError):
            SpatialDataAuditStore(
                DurableJournal(journal_path), policy=policy, working_set=_ws(policy)
            )
    finally:
        os.unlink(tmp_path / "alias-index.ws.sqlite3")
    # A hard-linked journal must not boot the indexed mode either.
    os.link(journal_path, tmp_path / "alias-journal.jsonl")
    try:
        with pytest.raises(SpatialDataAuditRecoveryError):
            SpatialDataAuditStore(
                DurableJournal(journal_path), policy=policy, working_set=_ws(policy)
            )
    finally:
        os.unlink(tmp_path / "alias-journal.jsonl")
    assert journal_path.read_bytes() == before
    # A hard-linked working-set config must not load.
    config_path = tmp_path / "ws.json"
    config_path.write_bytes(json.dumps(_ws(policy).model_dump(mode="json")).encode())
    os.chmod(config_path, 0o600)
    os.link(config_path, tmp_path / "alias-ws.json")
    try:
        with pytest.raises(ValueError, match="hard-linked"):
            load_spatial_data_audit_working_set(config_path)
    finally:
        os.unlink(tmp_path / "alias-ws.json")


def test_envelope_bound_admits_near_cap_record(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import audit_journal_max_line_bytes

    policy = _policy()
    bound = audit_journal_max_line_bytes(policy)
    assert bound == policy.max_json_bytes + 256
    # A raw line between the old (+1) bound and the envelope bound streams
    # only under the queryable envelope bound — a max-size event inside its
    # record framing is larger than one byte of framing.
    line = b'{"k":"' + b"x" * (policy.max_json_bytes + 100) + b'"}'
    assert policy.max_json_bytes + 1 < len(line) <= bound
    journal = _raw_journal(tmp_path / "wide.jsonl", [line])
    items, _cursor, eof = journal.stream_records(
        (0, 0), limit_records=1, limit_bytes=2 * bound, max_line_bytes=bound
    )
    assert len(items) == 1 and eof
    journal.close()
    journal2 = _raw_journal(tmp_path / "wide2.jsonl", [line])
    with pytest.raises(JournalRecoveryError, match="줄 상한"):
        journal2.stream_records(
            (0, 0),
            limit_records=1,
            limit_bytes=2 * bound,
            max_line_bytes=policy.max_json_bytes + 1,
        )
    journal2.close()


def test_working_set_boot_cap_bounds_refused(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    narrow = _policy(max_pending_records=2, max_list_records=2)
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    with pytest.raises(
        SpatialDataAuditRecoveryError, match="session cap exceeds the sealed policy"
    ):
        SpatialDataAuditStore(
            journal, policy=narrow, working_set=_ws(narrow, active_session_cap=8)
        )
    journal.close()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit2.jsonl")
    with pytest.raises(SpatialDataAuditRecoveryError, match="cache allowance"):
        SpatialDataAuditStore(
            journal2,
            policy=policy,
            working_set=_ws(
                policy,
                journal_file_name="spatial-data-audit2.jsonl",
                index_cache_allowance_bytes=policy.max_snapshot_bytes,
            ),
        )
    journal2.close()


def test_working_set_boot_and_reserve_bounded_over_volume(tmp_path: Path) -> None:
    import tracemalloc

    # The real factory journal (non-retained, strict, no torn repair) over a
    # large terminal history: only the unfinished session stays live.
    graph = _wiring_graph(tmp_path)
    wiring = _full_wiring(tmp_path, graph, working_set=_ws(graph.data_policy))
    audit = wiring.downloads.audit_store
    open_session = str(uuid4())
    audit.append(_event(open_session, "DOWNLOAD_ADMITTED", at=NOW, job_index=10**6))
    for index in range(600):
        _cycle(audit, index, at=NOW + timedelta(seconds=index))
    assert [item.session_id for item in audit.unfinished(organization_id=ORG, limit=8)] == [
        open_session
    ]
    assert len(audit._sessions) == 1  # noqa: SLF001
    assert len(audit._events) == 1  # noqa: SLF001
    assert audit._journal.retains_records is False  # noqa: SLF001
    assert audit._journal._records == []  # noqa: SLF001 -- no history list in RAM
    audit.close()
    # Rebooting over ~1800 retained records stays far below any history-sized
    # resident set: one small batch in flight, constant-size probes.
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    tracemalloc.start()
    try:
        again = SpatialDataAuditStore(
            journal2, policy=graph.data_policy, working_set=_ws(graph.data_policy)
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 16 * 1024 * 1024
    assert [item.session_id for item in again.unfinished(organization_id=ORG, limit=8)] == [
        open_session
    ]
    assert journal2.record_count == 1 + 600 * 3
    # The workspace reservation is the configured peak, not the current file
    # size — spool admissions share the remainder by actual size.
    assert again.disk_reserved_bytes() == 2 * 8 * 1024 * 1024
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    assert 0 < index_path.stat().st_size <= 8 * 1024 * 1024
    again.close()


def test_digest_only_legacy_binding_cannot_prove_scope_switch(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    _cycle(store, 1, at=NOW)
    store.close()
    # Simulate a digest-only binding from a previous implementation: the
    # full canonical JSON is absent, so a changed digest cannot prove a
    # scope-only switch and must refuse.
    connection = _open_sqlite(tmp_path / "spatial-data-audit.ws.sqlite3")
    connection.execute("DELETE FROM meta WHERE key = 'audit_working_set_json'")
    connection.commit()
    connection.close()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    with pytest.raises(SpatialDataAuditRecoveryError, match="changed under retained index"):
        SpatialDataAuditStore(
            journal2, policy=policy, working_set=_history_only(policy, activation_id="other-id")
        )
    journal2.close()
    # The identical binding still boots over the digest-only record.
    journal3 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    same = SpatialDataAuditStore(journal3, policy=policy, working_set=_ws(policy))
    assert same.unfinished(organization_id=ORG, limit=8) == ()
    assert same._history is not None
    assert same._history.stats() == (1, 3, 3)  # noqa: SLF001
    same.close()


# -- Blocker 1: ADMITTED->DENIED counts one session, not two -----------------


def _cycle_ad(store: Any, session: str, *, at: Any, job_index: int) -> None:
    store.append(_event(session, "DOWNLOAD_ADMITTED", at=at, job_index=job_index))
    store.append(
        _event(session, "DENIED", at=at, reason="GRANT_REQUIRED", job_index=job_index)
    )


def test_admitted_denied_counts_one_session_everywhere(tmp_path: Path) -> None:
    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    session = str(uuid4())
    _cycle_ad(store, session, at=NOW, job_index=11)
    denied_only = str(uuid4())
    store.append(_event(denied_only, "DENIED", at=NOW, reason="GRANT_REQUIRED", job_index=12))
    assert [i.action for i in store.events(organization_id=ORG, session_id=session, limit=8)] == [
        "DOWNLOAD_ADMITTED",
        "DENIED",
    ]
    denied = store.events(organization_id=ORG, session_id=denied_only, limit=8)
    assert [i.action for i in denied] == ["DENIED"]
    live_count = journal.record_count
    assert live_count == 3
    store.close()
    # Warm boot over the retained ADMITTED->DENIED history counts one session.
    journal2 = DurableJournal(journal_path)
    warm = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    assert [i.action for i in warm.events(organization_id=ORG, session_id=session, limit=8)] == [
        "DOWNLOAD_ADMITTED",
        "DENIED",
    ]
    assert warm._history is not None
    assert warm._history.stats() == (2, 3, 3)  # noqa: SLF001
    warm.close()
    # Missing-index rebuild counts one session too — never two.
    (tmp_path / "spatial-data-audit.ws.sqlite3").unlink()
    journal3 = DurableJournal(journal_path)
    rebuilt = SpatialDataAuditStore(journal3, policy=policy, working_set=_ws(policy))
    assert [i.action for i in rebuilt.events(organization_id=ORG, session_id=session, limit=8)] == [
        "DOWNLOAD_ADMITTED",
        "DENIED",
    ]
    assert rebuilt._history is not None
    assert rebuilt._history.stats() == (2, 3, 3)  # noqa: SLF001
    assert journal3.record_count == live_count
    rebuilt.close()
    # History-only switch and restart keep the single-session accounting.
    journal4 = DurableJournal(journal_path)
    recovery = SpatialDataAuditStore(
        journal4, policy=policy, working_set=_history_only(policy)
    )
    got = recovery.events(organization_id=ORG, session_id=session, limit=8)
    assert [i.action for i in got] == ["DOWNLOAD_ADMITTED", "DENIED"]
    assert recovery._history is not None
    assert recovery._history.stats() == (2, 3, 3)  # noqa: SLF001
    recovery.close()
    journal5 = DurableJournal(journal_path)
    again = SpatialDataAuditStore(
        journal5, policy=policy, working_set=_history_only(policy)
    )
    got2 = again.events(organization_id=ORG, session_id=denied_only, limit=8)
    assert [i.action for i in got2] == ["DENIED"]
    assert again._history is not None
    assert again._history.stats() == (2, 3, 3)  # noqa: SLF001
    assert journal5.record_count == live_count
    again.close()


# -- Blocker 2: session summary forgery heals, reservations survive -----------


def _forge_session_field(tmp_path: Path, session_id: str, field: str, value: object) -> None:
    connection = _open_sqlite(tmp_path / "spatial-data-audit.ws.sqlite3")
    assert field in ("terminal_action", "last_seq", "event_count", "created_seq")
    connection.execute(f"UPDATE sessions SET {field} = ? WHERE session_id = ?", (value, session_id))
    assert connection.total_changes == 1
    connection.commit()
    connection.close()


def test_session_summary_forgery_heals_without_reservation_loss(tmp_path: Path) -> None:
    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    done = _cycle(store, 1, at=NOW)
    open_session = str(uuid4())
    store.append(_event(open_session, "DOWNLOAD_ADMITTED", at=NOW, job_index=77))
    before = journal_path.read_bytes()
    store.close()

    def _reopen_healed() -> Any:
        journal2 = DurableJournal(journal_path)
        healed = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
        assert [i.session_id for i in healed.unfinished(organization_id=ORG, limit=8)] == [
            open_session
        ]
        assert [i.action for i in healed.events(organization_id=ORG, session_id=done, limit=8)][
            -1
        ] == "STREAM_COMPLETED"
        assert healed._history is not None
        assert healed._history.stats() == (2, 4, 4)  # noqa: SLF001
        assert journal_path.read_bytes() == before
        healed.close()

    # Flip the unfinished session to look terminal: reservations must survive.
    _forge_session_field(tmp_path, open_session, "terminal_action", "STREAM_COMPLETED")
    _reopen_healed()
    # Forge each aggregate field in turn: every one heals from the journal.
    _forge_session_field(tmp_path, open_session, "last_seq", 9999)
    _reopen_healed()
    _forge_session_field(tmp_path, open_session, "event_count", 99)
    _reopen_healed()
    _forge_session_field(tmp_path, open_session, "created_seq", 9999)
    _reopen_healed()
    # Flip a terminal session to look active: it must not resurface as
    # unfinished, and the terminal history stays exact.
    _forge_session_field(tmp_path, done, "terminal_action", None)
    journal2 = DurableJournal(journal_path)
    healed = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    try:
        assert [i.session_id for i in healed.unfinished(organization_id=ORG, limit=8)] == [
            open_session
        ]
        assert [i.action for i in healed.events(organization_id=ORG, session_id=done, limit=8)] == [
            "DOWNLOAD_ADMITTED",
            "STREAM_STARTED",
            "STREAM_COMPLETED",
        ]
        with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
            healed.append(_event(done, "STREAM_STARTED", at=NOW, job_index=1))
        assert journal_path.read_bytes() == before
    finally:
        healed.close()


# -- Blocker 3: hot external commits block/fail before the journal ----------


def _hot_index(path: Path, **kwargs: Any) -> Any:
    import sqlite3

    return sqlite3.connect(str(path), isolation_level=None, timeout=0, **kwargs)


def test_hot_forged_insert_blocked_before_journal_write(tmp_path: Path, monkeypatch: Any) -> None:
    import sqlite3

    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    before = journal.record_count
    before_bytes = journal_path.read_bytes()
    ext = _hot_index(tmp_path / "spatial-data-audit.ws.sqlite3")
    calls: list[str] = []
    real_append = journal.append
    forged_id = str(uuid4())

    def _racing(record: object) -> None:
        # Injected after the guard/version check, before the journal fsync:
        # a hot external writer forges a conflicting row for the event we
        # are about to commit. The held writer boundary must block it.
        try:
            ext.execute(
                "INSERT INTO events(event_id, seq, session_id, file_index, offset, length)"
                " VALUES(?, ?, ?, ?, ?, ?)",
                (forged_id, 9999, first, 0, 0, 8),
            )
        except sqlite3.Error as exc:
            calls.append(f"blocked:{type(exc).__name__}")
        else:
            calls.append("committed")
        return real_append(record)  # type: ignore[operator]

    monkeypatch.setattr(journal, "append", _racing)
    try:
        fresh_event = _event(str(uuid4()), "DOWNLOAD_ADMITTED", at=NOW, job_index=21)
        fresh_event = fresh_event.model_copy(
            update={"event_id": forged_id, "event_digest": None}
        ).sealed()
        store.append(fresh_event)
    finally:
        ext.close()
    # The append succeeded exactly once with no fork: the forgery never
    # landed, the journal holds one genuine record, the index verifies clean.
    assert calls == ["blocked:OperationalError"]
    assert journal.record_count == before + 1
    assert journal_path.read_bytes() != before_bytes
    assert [i.action for i in store.events(organization_id=ORG, session_id=first, limit=8)] == [
        "DOWNLOAD_ADMITTED",
        "STREAM_STARTED",
        "STREAM_COMPLETED",
    ]
    store.close()
    journal2 = DurableJournal(journal_path)
    try:
        again = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
        assert again._history is not None
        assert again._history.stats() == (2, 4, 4)  # noqa: SLF001
    finally:
        journal2.close()


def test_hot_open_writer_refuses_before_journal_write(tmp_path: Path) -> None:
    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    _cycle(store, 1, at=NOW)
    before = journal.record_count
    before_bytes = journal_path.read_bytes()
    ext = _hot_index(tmp_path / "spatial-data-audit.ws.sqlite3")
    ext.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
            store.append(_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=NOW, job_index=22))
    finally:
        ext.execute("ROLLBACK")
        ext.close()
    # Refused before any journal effect; the store sealed on lost exclusivity.
    assert journal.record_count == before
    assert journal_path.read_bytes() == before_bytes
    store.close()
    # A fresh store over the untouched journal and index admits normally.
    journal2 = DurableJournal(journal_path)
    try:
        reopened = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
        reopened.append(_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=NOW, job_index=23))
        assert journal2.record_count == before + 1
        reopened.close()
    finally:
        journal2.close()


def test_hot_delete_race_keeps_noop_and_serves_history(tmp_path: Path, monkeypatch: Any) -> None:
    import sqlite3

    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    retained = store.events(organization_id=ORG, session_id=first, limit=8)
    before = journal.record_count
    before_bytes = journal_path.read_bytes()
    ext = _hot_index(tmp_path / "spatial-data-audit.ws.sqlite3")
    calls: list[str] = []
    real_find = store._find_indexed_event  # noqa: SLF001

    def _racing_find(event_id: str) -> Any:
        found = real_find(event_id)
        try:
            ext.execute("DELETE FROM events WHERE session_id = ?", (first,))
            ext.execute("DELETE FROM session_order WHERE session_id = ?", (first,))
            ext.execute("DELETE FROM sessions WHERE session_id = ?", (first,))
        except sqlite3.Error as exc:
            calls.append(f"blocked:{type(exc).__name__}")
        else:
            calls.append("committed")
        return found

    monkeypatch.setattr(store, "_find_indexed_event", _racing_find)
    try:
        # Exact retry of a retained event stays a silent no-op: the hot
        # delete never landed, so there is nothing to re-admit or fork.
        store.append(retained[0].model_copy(deep=True))
    finally:
        ext.close()
    assert calls == ["blocked:OperationalError"]
    assert journal.record_count == before
    assert journal_path.read_bytes() == before_bytes
    assert [i.action for i in store.events(organization_id=ORG, session_id=first, limit=8)] == [
        "DOWNLOAD_ADMITTED",
        "STREAM_STARTED",
        "STREAM_COMPLETED",
    ]
    store.close()


# -- Blocker 4: cold-boot disk peak accounting --------------------------------


def test_cold_peak_refuses_unsafe_index_budget(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import (
        SpatialDataAuditRecoveryError,
        audit_index_cold_peak_bytes,
    )

    # The cold peak is the retained index, the fresh rebuild target and its
    # transient rollback journal plus bounded headers — no active spools.
    assert audit_index_cold_peak_bytes(8 * 1024 * 1024) == 3 * 8 * 1024 * 1024 + 16 * 4096
    assert audit_index_cold_peak_bytes(32 * 1024 * 1024) > 64 * 1024 * 1024
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    try:
        with pytest.raises(SpatialDataAuditRecoveryError, match="cold-boot peak"):
            SpatialDataAuditStore(
                journal,
                policy=policy,
                working_set=_ws(policy, index_disk_bytes=32 * 1024 * 1024),
            )
    finally:
        journal.close()
    # The 8M working set fits the same envelope with room for actual spools.
    assert audit_index_cold_peak_bytes(8 * 1024 * 1024) <= 64 * 1024 * 1024


def test_rebuild_failure_cleans_scratch_and_preserves_source(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError
    from ksi_core.domains.external.delivery.audit_history_index import (
        AuditHistoryIndex,
        AuditIndexFull,
    )

    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    first = _cycle(store, 1, at=NOW)
    before = journal_path.read_bytes()
    store.close()
    # Wipe the derived rows so boot must rebuild, then fail every rebuild
    # commit as if the disk were full.
    connection = _open_sqlite(tmp_path / "spatial-data-audit.ws.sqlite3")
    connection.execute("DELETE FROM events")
    connection.execute("DELETE FROM session_order")
    connection.execute("DELETE FROM sessions")
    connection.commit()
    connection.close()

    real_commit = AuditHistoryIndex.commit_event

    def _full(*args: object, **kwargs: object) -> None:
        raise AuditIndexFull("test disk full")

    AuditHistoryIndex.commit_event = _full  # type: ignore[method-assign]
    try:
        journal2 = DurableJournal(journal_path)
        try:
            with pytest.raises(SpatialDataAuditRecoveryError):
                SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
        finally:
            journal2.close()
    finally:
        AuditHistoryIndex.commit_event = real_commit  # type: ignore[method-assign]
    # No rebuild litter, no source rewrite, the retained index file stands.
    assert journal_path.read_bytes() == before
    assert not (tmp_path / "spatial-data-audit.ws.rebuild.sqlite3").exists()
    assert (tmp_path / "spatial-data-audit.ws.sqlite3").exists()
    journal3 = DurableJournal(journal_path)
    try:
        recovered = SpatialDataAuditStore(journal3, policy=policy, working_set=_ws(policy))
        assert [i.action for i in recovered.events(organization_id=ORG, session_id=first, limit=8)][
            -1
        ] == "STREAM_COMPLETED"
        recovered.close()
    finally:
        journal3.close()


# -- Blocker 5: indexed plans, native memory accounting ----------------------


def _explain_queries(session_id: str) -> list[tuple[str, tuple]]:
    return [
        (
            "SELECT e.seq, e.session_id, e.file_index, e.offset, e.length"
            " FROM session_order o JOIN events e ON e.seq = o.seq"
            " WHERE o.session_id = ? ORDER BY o.session_seq LIMIT ?",
            (session_id, 9),
        ),
        (
            "SELECT session_id, organization_id, last_seq FROM sessions"
            " WHERE terminal_action IS NULL ORDER BY created_seq LIMIT ?",
            (8,),
        ),
        (
            "SELECT 1 FROM events e WHERE NOT EXISTS"
            " (SELECT 1 FROM sessions s WHERE s.session_id = e.session_id) LIMIT 1",
            (),
        ),
        (
            "SELECT 1 FROM session_order o WHERE NOT EXISTS"
            " (SELECT 1 FROM sessions s WHERE s.session_id = o.session_id) LIMIT 1",
            (),
        ),
        (
            "SELECT 1 FROM session_order o WHERE NOT EXISTS"
            " (SELECT 1 FROM events e WHERE e.seq = o.seq"
            " AND e.session_id = o.session_id) LIMIT 1",
            (),
        ),
        (
            "SELECT 1 FROM events e WHERE NOT EXISTS"
            " (SELECT 1 FROM session_order o WHERE o.seq = e.seq"
            " AND o.session_id = e.session_id) LIMIT 1",
            (),
        ),
        (
            "SELECT seq FROM session_order GROUP BY seq HAVING COUNT(*) > 1 LIMIT 1",
            (),
        ),
        (
            "SELECT session_id, organization_id, terminal_action,"
            " last_seq, event_count, created_seq FROM sessions"
            " ORDER BY created_seq LIMIT ? OFFSET ?",
            (16, 0),
        ),
        (
            "SELECT e.event_id FROM session_order o JOIN events e ON e.seq = o.seq"
            " WHERE o.session_id = ? AND o.session_seq = ?",
            (session_id, 0),
        ),
        (
            "SELECT seq, session_id, file_index, offset, length FROM events WHERE event_id = ?",
            ("00000000-0000-0000-0000-000000000000",),
        ),
    ]


def test_history_queries_use_indexed_plans_without_temp_sort(tmp_path: Path) -> None:
    policy = _policy()
    store = _store(tmp_path, policy=policy)
    first = _cycle(store, 1, at=NOW + timedelta(seconds=1))
    open_session = str(uuid4())
    store.append(_event(open_session, "DOWNLOAD_ADMITTED", at=NOW, job_index=55))
    assert store._history is not None
    history = store._history
    for query, params in _explain_queries(first):
        assert not history.explain_has_temp_sort(query, params), query[:60]
    # Native memory accounting is structural, not asserted: fixed 32 KiB
    # page cache, memory-mapped I/O off, in-RAM temp that the plans above
    # never spill into, a hard page budget, and a zero-wait lock mode.
    connection = history._connection  # noqa: SLF001
    assert connection.execute("PRAGMA page_size").fetchone()[0] == 4096
    assert connection.execute("PRAGMA cache_size").fetchone()[0] == -32
    assert connection.execute("PRAGMA mmap_size").fetchone()[0] == 0
    assert connection.execute("PRAGMA temp_store").fetchone()[0] == 2
    assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
    assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 0
    assert connection.execute("PRAGMA max_page_count").fetchone()[0] == 2048
    pages = history.page_count()
    assert 0 < pages <= 2048
    # SQLite-native bytes plus the bounded Python stage stay far below 1M:
    # page-capped file, 32K cache, one 256K stream batch in flight.
    assert pages * 4096 + 32 * 1024 <= 8 * 1024 * 1024
    store.close()


def test_volume_boot_native_and_python_bounded(tmp_path: Path) -> None:
    import tracemalloc

    policy = _policy()
    store = _store(tmp_path, policy=policy)
    open_session = str(uuid4())
    store.append(_event(open_session, "DOWNLOAD_ADMITTED", at=NOW, job_index=10**6))
    for index in range(120):
        _cycle(store, index, at=NOW + timedelta(seconds=index))
    assert store._history is not None
    native_file_bytes = store._history.file_bytes()
    native_pages = store._history.page_count()
    assert 0 < native_pages * 4096 <= 8 * 1024 * 1024
    store.close()
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    tracemalloc.start()
    try:
        again = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # Python stage (one batch + ≤2 predecessors per record, no history map)
    # plus the native file/cache/allowance budget stay within 1M combined.
    assert peak < 1 * 1024 * 1024
    assert native_file_bytes + 32 * 1024 + 128 * 1024 < 1 * 1024 * 1024
    assert again._history is not None
    assert again._history.stats() == (121, 361, 361)  # noqa: SLF001
    assert [item.session_id for item in again.unfinished(organization_id=ORG, limit=8)] == [
        open_session
    ]
    # No rollback-journal sidecar lingers between bounded transactions.
    assert not (tmp_path / "spatial-data-audit.ws.sqlite3-journal").exists()
    again.close()


def test_progress_watch_aborts_long_sql(tmp_path: Path) -> None:
    import sqlite3

    policy = _policy()
    store = _store(tmp_path, policy=policy)
    _cycle(store, 1, at=NOW)
    assert store._history is not None
    history = store._history
    history.watch_deadline(lambda: True)
    try:
        with pytest.raises(sqlite3.OperationalError, match="interrupted"):
            history._connection.execute(  # noqa: SLF001
                "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c LIMIT 100000)"
                " SELECT COUNT(*) FROM c"
            ).fetchall()
    finally:
        history.unwatch_deadline()
    # The interrupted connection still serves bounded reads afterwards.
    assert history.stats() == (1, 3, 3)
    store.close()


# -- Blocker 6: one absolute boot wall + CPU budget ---------------------------


def test_constructor_phase_burn_refuses_before_trust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from time import monotonic as real_monotonic

    from ksi_core.foundation.durable_journal import JournalRecoveryError

    ticks = [1000.0]

    def _burning() -> float:
        ticks[0] += 1.0
        return ticks[0]

    monkeypatch.setattr(
        "ksi_core.foundation.durable_journal.monotonic", _burning
    )
    path = tmp_path / "burn.jsonl"
    raw = b'{"n":1}\n{"n":2}\n'
    path.write_bytes(raw)
    os.chmod(path, 0o600)
    # The clock burns past the explicit budget during recovery: the strict
    # open refuses before trusting or repairing anything.
    with pytest.raises(JournalRecoveryError, match="기한"):
        DurableJournal(
            path,
            retain_records=False,
            max_line_bytes=65537,
            max_recover_bytes=1 << 20,
            recover_deadline=1000.5,
            tolerate_torn_tail=False,
        )
    assert path.read_bytes() == raw
    assert real_monotonic() > 0


def test_audit_phase_wall_burn_refuses_with_source_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.domains.external.delivery import audit as audit_module
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    calls = [0]

    def _burning() -> float:
        calls[0] += 100.0
        return 1000.0 + calls[0]

    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    _cycle(store, 1, at=NOW)
    before = journal_path.read_bytes()
    store.close()
    # Arm the burning clock only for the failing boot: the journal open
    # records the first fake tick as the shared window start, so the first
    # audit budget check deterministically fires past the shared deadline.
    # Both clocks share one burner because the window starts BEFORE the
    # journal open (journal recovery CPU/wall already counts).
    import ksi_core.foundation.durable_journal as journal_module

    monkeypatch.setattr(audit_module, "monotonic", _burning)
    monkeypatch.setattr(journal_module, "monotonic", _burning)
    # The wall clock burns past the single shared deadline mid-boot: every
    # I/O and SQL point validates it, so boot fails closed with the source
    # and the retained derived file untouched and no rebuild litter.
    (tmp_path / "spatial-data-audit.ws.sqlite3").unlink()
    journal2 = DurableJournal(journal_path)
    try:
        with pytest.raises(SpatialDataAuditRecoveryError, match="deadline"):
            SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    finally:
        journal2.close()
    assert journal_path.read_bytes() == before
    assert not (tmp_path / "spatial-data-audit.ws.rebuild.sqlite3").exists()
    assert (tmp_path / "spatial-data-audit.ws.sqlite3").exists()


def test_audit_phase_cpu_burn_refuses_with_source_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.domains.external.delivery import audit as audit_module
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    ticks = iter([1000.0, 1000.0 + 10000.0])

    def _burning_cpu() -> float:
        try:
            return next(ticks)
        except StopIteration:
            return 1000.0 + 10000.0

    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    _cycle(store, 1, at=NOW)
    before = journal_path.read_bytes()
    store.close()
    # Arm the burning CPU clock only for the failing boot: the journal open
    # records the first fake tick as the shared CPU start, and the first
    # audit budget check fires past the sealed-envelope budget. Both clocks
    # share one burner because the window starts BEFORE the journal open.
    import ksi_core.foundation.durable_journal as journal_module

    monkeypatch.setattr(audit_module, "process_time", _burning_cpu)
    monkeypatch.setattr(journal_module, "process_time", _burning_cpu)
    # Process CPU burns past the sealed-envelope CPU budget mid-boot: the
    # CPU check is independent of wall time and fails closed the same way.
    (tmp_path / "spatial-data-audit.ws.sqlite3").unlink()
    journal2 = DurableJournal(journal_path)
    try:
        with pytest.raises(SpatialDataAuditRecoveryError, match="CPU budget"):
            SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    finally:
        journal2.close()
    assert journal_path.read_bytes() == before
    assert not (tmp_path / "spatial-data-audit.ws.rebuild.sqlite3").exists()


# -- Shared window + post-fsync binding adversarial -------------------------


def test_shared_boot_window_starts_before_journal_open(tmp_path: Path) -> None:
    """The audit boot reuses the journal's window, never a fresh post-open one.

    Wall deadline and CPU start/budget are shared from BEFORE the journal
    open through index verify/rebuild, inside the existing envelope (no
    bound increase: earlier start is strictly tighter).
    """
    from time import monotonic as real_monotonic
    from time import process_time as real_process_time

    policy = _policy()
    working_set = _ws(policy)
    cpu_budget = min(
        float(policy.resource_envelope.max_cpu_seconds),
        float(working_set.max_boot_seconds),
    )
    open_wall = real_monotonic()
    open_cpu = real_process_time()
    journal = DurableJournal(
        tmp_path / "spatial-data-audit.jsonl",
        retain_records=False,
        max_line_bytes=65537,
        max_recover_bytes=1 << 20,
        recover_deadline=open_wall + float(working_set.max_boot_seconds),
        recover_cpu_budget=cpu_budget,
        recover_cpu_start=open_cpu,
        tolerate_torn_tail=False,
    )
    store = SpatialDataAuditStore(journal, policy=policy, working_set=working_set)
    try:
        # Shared, not fresh: the exact journal deadline/start flow through.
        assert store._boot_wall_deadline == journal.recover_deadline  # noqa: SLF001
        assert store._boot_cpu_start == journal.recover_cpu_start == open_cpu  # noqa: SLF001
        assert store._boot_cpu_budget == cpu_budget  # noqa: SLF001
        assert journal.open_monotonic >= open_wall
        assert journal.open_cpu_start >= open_cpu
    finally:
        store.close()


def test_journal_cpu_budget_refuses_during_recovery(tmp_path: Path) -> None:
    """Journal read phase enforces the shared CPU budget, not just the wall."""
    from time import monotonic as real_monotonic

    from ksi_core.foundation.durable_journal import JournalRecoveryError

    path = tmp_path / "audit.jsonl"
    raw = b'{"a":1}\n{"a":2}\n'
    path.write_bytes(raw)
    os.chmod(path, 0o600)
    with pytest.raises(JournalRecoveryError, match="CPU"):
        DurableJournal(
            path,
            retain_records=False,
            max_line_bytes=65537,
            max_recover_bytes=1 << 20,
            recover_deadline=real_monotonic() + 60.0,
            recover_cpu_budget=1e-9,
            recover_cpu_start=0.0,
            tolerate_torn_tail=False,
        )
    # Fail-closed before trusting or repairing anything.
    assert path.read_bytes() == raw


def test_boot_releases_sqlite_progress_watch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Boot arms its SQLite progress watch exactly once and always releases it."""
    from ksi_core.domains.external.delivery import audit_history_index as index_module

    calls = {"watch": 0, "unwatch": 0}
    real_watch = index_module.AuditHistoryIndex.watch_deadline
    real_unwatch = index_module.AuditHistoryIndex.unwatch_deadline

    def _watch(self: object, pred: object) -> None:
        calls["watch"] += 1
        real_watch(self, pred)  # type: ignore[arg-type]

    def _unwatch(self: object) -> None:
        calls["unwatch"] += 1
        real_unwatch(self)  # type: ignore[arg-type]

    monkeypatch.setattr(index_module.AuditHistoryIndex, "watch_deadline", _watch)
    monkeypatch.setattr(index_module.AuditHistoryIndex, "unwatch_deadline", _unwatch)
    policy = _policy()
    journal = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    _cycle(store, 1, at=NOW)
    store.close()
    # Warm boot over retained history: one arm, one release, then a long
    # statement runs to completion with no lingering abort.
    journal2 = DurableJournal(tmp_path / "spatial-data-audit.jsonl")
    calls["watch"] = calls["unwatch"] = 0
    warm = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    try:
        assert calls["watch"] == 1 and calls["unwatch"] == 1
        assert warm._history is not None  # noqa: SLF001
        warm._history._connection.execute(  # noqa: SLF001
            "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c LIMIT 100000)"
            " SELECT COUNT(*) FROM c"
        ).fetchall()
    finally:
        warm.close()


def test_append_external_index_commit_seals_without_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An index fork landing during the journal fsync seals; the journal heals.

    The writer boundary is held from the pre-append checks through the
    fsync, so a real external commit blocks. This forges one anyway to prove
    the post-fsync re-pin seals instead of manufacturing absence or
    reopening a terminal session — and the next boot replays the fsynced
    record from the authoritative journal.
    """
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    session = str(uuid4())
    store.append(_event(session, "DOWNLOAD_ADMITTED", at=NOW, job_index=41))
    history = store._history
    assert history is not None
    real_version = history.data_version()
    real_version_fn = history.data_version
    real_append = journal.append
    state = {"forked": False}

    def _version() -> int:
        if state["forked"]:
            return int(real_version) + 1
        return int(real_version_fn())

    def _append_and_fork(record: object) -> None:
        state["forked"] = True
        real_append(record)  # type: ignore[arg-type]

    monkeypatch.setattr(history, "data_version", _version)
    monkeypatch.setattr(journal, "append", _append_and_fork)
    with pytest.raises(SpatialDataDomainError):
        store.append(_event(session, "STREAM_STARTED", at=NOW, job_index=41))
    assert store._sealed  # noqa: SLF001
    journal_bytes_after = journal_path.read_bytes()
    store.close()
    # The fsynced record survived in the authority; a fresh boot heals the
    # derived index from it instead of reporting a forged absence.
    journal2 = DurableJournal(journal_path)
    healed = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    try:
        got = healed.events(organization_id=ORG, session_id=session, limit=8)
        assert [i.action for i in got] == ["DOWNLOAD_ADMITTED", "STREAM_STARTED"]
    finally:
        healed.close()
    assert journal_path.read_bytes() == journal_bytes_after


def test_append_journal_swap_seals_without_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A journal identity move during the fsync seals; the journal heals."""
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    session = str(uuid4())
    store.append(_event(session, "DOWNLOAD_ADMITTED", at=NOW, job_index=42))
    real_ident_fn = store._journal_identity  # noqa: SLF001
    real_append = journal.append
    state = {"forked": False}

    def _ident() -> tuple[int, int] | None:
        live = real_ident_fn()
        if state["forked"] and live is not None:
            return (live[0], live[1] + 1)
        return live

    def _append_and_swap(record: object) -> None:
        state["forked"] = True
        real_append(record)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "_journal_identity", _ident)
    monkeypatch.setattr(journal, "append", _append_and_swap)
    with pytest.raises(SpatialDataDomainError):
        store.append(_event(session, "STREAM_STARTED", at=NOW, job_index=42))
    assert store._sealed  # noqa: SLF001
    journal_bytes_after = journal_path.read_bytes()
    store.close()
    journal2 = DurableJournal(journal_path)
    healed = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    try:
        got = healed.events(organization_id=ORG, session_id=session, limit=8)
        assert [i.action for i in got] == ["DOWNLOAD_ADMITTED", "STREAM_STARTED"]
    finally:
        healed.close()
    assert journal_path.read_bytes() == journal_bytes_after


# -- Plan blockers: post-commit adoption, structural RAM, SQL CPU ----------


def test_post_commit_foreign_delete_seals_without_false_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No adoption of an unvalidated foreign change during binding refresh.

    Completed session A is retained; an external transaction deletes A's
    index rows AFTER the real commit of another event's append, with the
    checkpoint untouched. The binding was adopted under the boundary before
    the release, so the very next run check seals instead of reporting A's
    retained history as absent — and the sealed store refuses the old
    admission as a conflict instead of duplicating/reopening the terminal.
    A fresh boot heals both sessions from the authoritative journal.
    """
    import sqlite3

    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    done = _cycle(store, 1, at=NOW)
    other = str(uuid4())
    store.append(_event(other, "DOWNLOAD_ADMITTED", at=NOW, job_index=99))
    assert store._history is not None
    index_path = tmp_path / "spatial-data-audit.ws.sqlite3"
    history = store._history
    real_commit = history.commit_write

    def _commit_then_fork() -> None:
        real_commit()
        foreign = sqlite3.connect(str(index_path), timeout=0)
        try:
            foreign.execute("DELETE FROM events WHERE session_id = ?", (done,))
            foreign.execute("DELETE FROM session_order WHERE session_id = ?", (done,))
            foreign.execute("DELETE FROM sessions WHERE session_id = ?", (done,))
            foreign.commit()
        finally:
            foreign.close()

    monkeypatch.setattr(history, "commit_write", _commit_then_fork)
    store.append(_event(other, "STREAM_STARTED", at=NOW, job_index=99))
    # The append's own commit succeeded before the fork; the adopted binding
    # is exactly ours, so the next run check seals on the foreign version.
    assert not store._sealed  # noqa: SLF001
    before = journal_path.read_bytes()
    with pytest.raises(SpatialDataDomainError):
        store.events(organization_id=ORG, session_id=done, limit=8)
    assert store._sealed  # noqa: SLF001
    assert journal_path.read_bytes() == before
    # No duplicate/reopen: the sealed store refuses the old admission retry.
    with pytest.raises(SpatialDataDomainError):
        store.append(_event(done, "DOWNLOAD_ADMITTED", at=NOW, job_index=1))
    store.close()
    journal2 = DurableJournal(journal_path)
    healed = SpatialDataAuditStore(journal2, policy=policy, working_set=_ws(policy))
    try:
        assert [
            i.action for i in healed.events(organization_id=ORG, session_id=done, limit=8)
        ] == ["DOWNLOAD_ADMITTED", "STREAM_STARTED", "STREAM_COMPLETED"]
        assert [
            i.action for i in healed.events(organization_id=ORG, session_id=other, limit=8)
        ] == ["DOWNLOAD_ADMITTED", "STREAM_STARTED"]
    finally:
        healed.close()


def test_line_shape_gate_keeps_valid_structures() -> None:
    """The structural pre-gate rejects only shapes no valid record has."""
    from ksi_core.domains.external.delivery.audit import _reject_unbounded_line_shape

    _reject_unbounded_line_shape(
        b'{"recordType":"spatial-data-audit.v1","sequence":1,'
        b'"event":{"a":"[brackets] inside {strings} are data"}}'
    )
    _reject_unbounded_line_shape(b'{"a":null,"b":true,"c":-1.5,"d":"e\\"f"}')
    with pytest.raises(ValueError, match="array"):
        _reject_unbounded_line_shape(b'{"junk":[0,1,2]}')
    with pytest.raises(ValueError, match="nest"):
        _reject_unbounded_line_shape(b'{"a":' + b'{"b":1,' * 10 + b'1' + b'}' * 10 + b'}')
    with pytest.raises(ValueError, match="fields"):
        _reject_unbounded_line_shape(b'{' + b'"k0":0,' * 200 + b'"k1":0}')
    with pytest.raises(ValueError, match="incomplete"):
        _reject_unbounded_line_shape(b'{"a":1')


def test_structural_junk_refused_within_combined_budget(tmp_path: Path) -> None:
    """Malicious structural shapes are refused before any parsed buildup.

    Four ~65KiB lines of ``{"junk":[...]}`` fit the line cap but would
    inflate past 1MiB as parsed objects (plus the legacy deep copy). The
    delivery-mode stream gates each raw line first, so boot refuses on the
    opening bracket with the combined native/Python/active budget intact.
    """
    import tracemalloc
    from time import monotonic as real_monotonic

    from ksi_core.domains.external.delivery.audit import (
        SpatialDataAuditRecoveryError,
        audit_journal_max_line_bytes,
    )

    junk = b'{"junk":[' + b'0,' * 32699 + b'0]}'
    assert len(junk) <= 65536 + 256
    path = tmp_path / "spatial-data-audit.jsonl"
    path.write_bytes((junk + b"\n") * 4)
    os.chmod(path, 0o600)
    policy = _policy()
    working_set = _ws(policy)
    tracemalloc.start()
    try:
        journal = DurableJournal(
            path,
            retain_records=False,
            max_line_bytes=audit_journal_max_line_bytes(policy),
            max_recover_bytes=working_set.max_boot_scan_bytes,
            recover_deadline=real_monotonic() + 60.0,
            tolerate_torn_tail=False,
        )
        try:
            with pytest.raises(
                SpatialDataAuditRecoveryError, match="array shape|invalid record"
            ):
                SpatialDataAuditStore(journal, policy=policy, working_set=working_set)
        finally:
            journal.close()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1 * 1024 * 1024
    assert path.read_bytes() == (junk + b"\n") * 4


def test_progress_watch_aborts_cpu_burn_during_sql(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SQL-time CPU exhaustion aborts promptly while wall time is unexpired.

    The shared boot predicate covers wall OR CPU, and it is installed on the
    index connection before any costly SQL — so a statement that burns CPU
    is interrupted by the progress handler instead of merely failing a later
    between-operations check.
    """
    import sqlite3
    from time import monotonic as real_monotonic

    from ksi_core.domains.external.delivery import audit as audit_module

    policy = _policy()
    store = _store(tmp_path, policy=policy)
    _cycle(store, 1, at=NOW)
    assert store._history is not None
    history = store._history
    assert real_monotonic() < store._boot_wall_deadline  # noqa: SLF001
    monkeypatch.setattr(audit_module, "process_time", lambda: 1e9)
    history.watch_deadline(store._past_boot_deadline)  # noqa: SLF001
    try:
        with pytest.raises(sqlite3.OperationalError, match="interrupted"):
            history._connection.execute(  # noqa: SLF001
                "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c LIMIT 100000)"
                " SELECT COUNT(*) FROM c"
            ).fetchall()
    finally:
        history.unwatch_deadline()
    store.close()


def test_nonretaining_journal_rejects_dict_array_junk_before_parse(
    tmp_path: Path,
) -> None:
    """Plan blocker 1: bounded structural validation before the first parse.

    A ~60KiB line of 20,000 empty dicts fits the line cap but inflates past
    1MiB as parsed objects. The owner-supplied gate runs on raw bytes first,
    so the non-retaining open refuses with the source byte-identical and the
    combined budget intact.
    """
    import tracemalloc
    from time import monotonic as real_monotonic

    from ksi_core.domains.external.delivery.audit import _reject_unbounded_line_shape
    from ksi_core.foundation.durable_journal import JournalRecoveryError

    junk = b'{"junk":[' + b"{}," * 19999 + b"{}]}"
    assert len(junk) < 65536 + 256
    path = tmp_path / "spatial-data-audit.jsonl"
    path.write_bytes(junk + b"\n")
    os.chmod(path, 0o600)
    tracemalloc.start()
    try:
        with pytest.raises(JournalRecoveryError, match="구조"):
            DurableJournal(
                path,
                retain_records=False,
                max_line_bytes=65537,
                max_recover_bytes=1 << 20,
                recover_deadline=real_monotonic() + 60.0,
                tolerate_torn_tail=False,
                line_validator=_reject_unbounded_line_shape,
            )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1 * 1024 * 1024
    assert path.read_bytes() == junk + b"\n"


def test_indexed_boot_rejects_dict_array_junk_with_source_unchanged(
    tmp_path: Path,
) -> None:
    """Plan blocker 1 end to end: the whole indexed boot refuses the junk."""
    from time import monotonic as real_monotonic

    from ksi_core.domains.external.delivery.audit import (
        _reject_unbounded_line_shape,
        audit_journal_max_line_bytes,
    )

    junk = b'{"junk":[' + b"{}," * 19999 + b"{}]}"
    path = tmp_path / "spatial-data-audit.jsonl"
    path.write_bytes((junk + b"\n") * 2)
    os.chmod(path, 0o600)
    policy = _policy()
    working_set = _ws(policy)
    from ksi_core.foundation.durable_journal import JournalRecoveryError

    # The gate runs at the journal open itself — before the first parse, let
    # alone the first object batch — so the whole indexed boot never starts.
    with pytest.raises(JournalRecoveryError, match="구조"):
        DurableJournal(
            path,
            retain_records=False,
            max_line_bytes=audit_journal_max_line_bytes(policy),
            max_recover_bytes=working_set.max_boot_scan_bytes,
            recover_deadline=real_monotonic() + 60.0,
            tolerate_torn_tail=False,
            line_validator=_reject_unbounded_line_shape,
        )
    assert path.read_bytes() == (junk + b"\n") * 2
    assert not (tmp_path / "spatial-data-audit.ws.sqlite3").exists()
    assert not (tmp_path / "spatial-data-audit.ws.rebuild.sqlite3").exists()


def test_indexed_boot_gates_junk_stream_even_without_open_validator(
    tmp_path: Path,
) -> None:
    """Plan blocker 1, second layer: the delivery stream gates every line.

    Even if a journal opens without the owner-supplied gate (legacy
    default), the indexed boot still refuses the inflated shape before any
    parsed object accumulates — raw bytes stream in, the structural gate
    runs first, and only then does one record validate.
    """
    from time import monotonic as real_monotonic

    from ksi_core.domains.external.delivery.audit import (
        SpatialDataAuditRecoveryError,
        audit_journal_max_line_bytes,
    )

    junk = b'{"junk":[' + b"{}," * 19999 + b"{}]}"
    path = tmp_path / "spatial-data-audit.jsonl"
    path.write_bytes((junk + b"\n") * 2)
    os.chmod(path, 0o600)
    policy = _policy()
    working_set = _ws(policy)
    journal = DurableJournal(
        path,
        retain_records=False,
        max_line_bytes=audit_journal_max_line_bytes(policy),
        max_recover_bytes=working_set.max_boot_scan_bytes,
        recover_deadline=real_monotonic() + 60.0,
        tolerate_torn_tail=False,
    )
    try:
        with pytest.raises(SpatialDataAuditRecoveryError, match="array shape|invalid"):
            SpatialDataAuditStore(journal, policy=policy, working_set=working_set)
    finally:
        journal.close()
    assert path.read_bytes() == (junk + b"\n") * 2
    assert not (tmp_path / "spatial-data-audit.ws.rebuild.sqlite3").exists()


def test_late_source_replacement_seals_without_adopting_empty_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan blocker 2: bind adoption to the validated proof token, not a re-read.

    After the real index commit returns but before binding adoption, the
    journal is renamed aside and an empty owner-private file is installed at
    the canonical path. Adoption must seal on the pinned values instead of
    adopting the empty replacement — the next admission and any historical
    read refuse, and no sequence extends into the replacement. Attack
    fixture evidence is preserved, never repaired or truncated.
    """
    import stat as stat_module

    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    policy = _policy()
    journal_path = tmp_path / "spatial-data-audit.jsonl"
    journal = DurableJournal(journal_path)
    store = SpatialDataAuditStore(journal, policy=policy, working_set=_ws(policy))
    done = _cycle(store, 1, at=NOW)
    other = str(uuid4())
    store.append(_event(other, "DOWNLOAD_ADMITTED", at=NOW, job_index=99))
    assert store._history is not None
    history = store._history
    real_commit_event = history.commit_event_in_write_txn
    aside = tmp_path / "spatial-data-audit.jsonl.aside"

    def _commit_then_replace(**kwargs: object) -> None:
        real_commit_event(**kwargs)  # type: ignore[arg-type]
        os.rename(journal_path, aside)
        replacement = journal_path
        replacement.write_bytes(b"")
        os.chmod(replacement, 0o600)
        entry = os.stat(replacement)
        assert entry.st_uid == os.geteuid()
        assert stat_module.S_IMODE(entry.st_mode) == 0o600

    monkeypatch.setattr(history, "commit_event_in_write_txn", _commit_then_replace)
    with pytest.raises(SpatialDataDomainError):
        store.append(_event(other, "STREAM_STARTED", at=NOW, job_index=99))
    assert store._sealed  # noqa: SLF001
    # Attack fixture evidence is preserved: the original journal sits aside
    # byte-identical, the canonical path holds the empty replacement, and
    # nothing was repaired or truncated by the store.
    assert aside.read_bytes() != b""
    assert journal_path.read_bytes() == b""
    # No sequence extends into the replacement: admissions and history read
    # refuse instead of continuing from the empty file.
    with pytest.raises(SpatialDataDomainError):
        store.append(_event(str(uuid4()), "DOWNLOAD_ADMITTED", at=NOW, job_index=100))
    with pytest.raises(SpatialDataDomainError):
        store.events(organization_id=ORG, session_id=done, limit=8)
    store.close()


def test_record_disables_pydantic_string_cache_without_model_changes() -> None:
    """The private audit record opts out of the global string cache.

    Only ``_Record`` carries ``cache_strings=False``; the public event/model
    configs, caps, formats, and legacy behavior are untouched.
    """
    from ksi_core.domains.external.delivery.audit import (
        SpatialDataAuditEventV1,
        _Record,
    )

    assert _Record.model_config.get("cache_strings") is False
    assert SpatialDataAuditEventV1.model_config.get("cache_strings") is not False


def test_distinct_records_retain_no_history_sized_cache(tmp_path: Path) -> None:
    """1531 distinct retained-shape records leave no history-sized residue.

    Same validation/serialization/digest/strictness as the default path —
    invalid input is still refused and digests still verify — but nothing
    accumulates per distinct record.
    """
    import tracemalloc
    from datetime import timedelta

    from ksi_core.domains.external.delivery.audit import _Record

    tracemalloc.start()
    try:
        start_current = tracemalloc.get_traced_memory()[0]
        for i in range(1531):
            at = NOW + timedelta(seconds=i)
            ev = _event(str(uuid4()), "DOWNLOAD_ADMITTED", at=at, job_index=i)
            raw = _Record(sequence=i + 1, event=ev).model_dump_json(by_alias=True)
            parsed = _Record.model_validate_json(raw.encode("utf-8"))
            assert parsed.event.event_digest == parsed.event.canonical_digest()
        retained = tracemalloc.get_traced_memory()[0] - start_current
    finally:
        tracemalloc.stop()
    assert retained < 64 * 1024
    # Strict negative parity: malformed input is still refused, not skipped.
    with pytest.raises((ValueError, TypeError), match="Extra inputs"):
        _Record.model_validate_json(b'{"junk":[' + b"{}," * 9 + b"{}]}")
