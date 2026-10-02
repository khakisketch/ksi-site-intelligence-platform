"""Real durable audit lifecycle/recovery, never a public authority or credential log."""

from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from ksi_core.domains.external.delivery.audit import SpatialDataAuditEventV1, SpatialDataAuditStore
from ksi_core.durable_journal import DurableJournal
from spatial_data_fixture import DIGEST, JOB_ID, NOW, make_policy

SESSION = "00000000-0000-4000-8000-000000000007"


def event(action: str, *, sent: int = 0, **changes: Any) -> SpatialDataAuditEventV1:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditEventV1

    body: dict[str, Any] = dict(
        event_id=str(uuid4()),
        session_id=SESSION,
        organization_id="org-local",
        principal_id="reader-local",
        site_id="site-local",
        work_area_id="area-local",
        job_id=JOB_ID,
        at=NOW,
        action=action,
        expected_size_bytes=128,
        output_sha256=DIGEST,
        sent_bytes=sent,
    )
    if action in ("DENIED", "STREAM_INTERRUPTED"):
        body["reason"] = "ACCESS_REVOKED"
    body.update(changes)
    return SpatialDataAuditEventV1(**body).sealed()


def store(path: Path, **changes: Any) -> SpatialDataAuditStore:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditStore

    return SpatialDataAuditStore(DurableJournal(path), policy=make_policy(**changes))


def test_audit_replay_retains_exact_admission_start_and_partial_interruption(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "audit.jsonl"
    audit = store(journal)
    admitted, started, stopped = (
        event("DOWNLOAD_ADMITTED"),
        event("STREAM_STARTED"),
        event("STREAM_INTERRUPTED", sent=64),
    )
    for item in (admitted, started, stopped):
        audit.append(item)
    audit.close()
    recovered = store(journal)
    assert recovered.events(organization_id="org-local", session_id=SESSION, limit=4) == (
        admitted,
        started,
        stopped,
    )
    assert recovered.events(organization_id="foreign-org", session_id=SESSION, limit=4) == ()
    assert recovered.unfinished(organization_id="org-local", limit=4) == ()
    recovered.close()
    text = journal.read_text()
    assert "ACCESS_REVOKED" in text and 'sentBytes":64' in text.replace(" ", "")
    assert "authorization" not in text.lower() and "https://" not in text


def test_audit_retry_is_exact_and_cannot_rewrite_recorded_bytes(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    audit = store(tmp_path / "audit.jsonl")
    admitted = event("DOWNLOAD_ADMITTED")
    audit.append(admitted)
    audit.append(admitted)
    assert audit.events(organization_id="org-local", session_id=SESSION, limit=4) == (admitted,)
    changed = admitted.model_copy(
        update={"at": NOW + timedelta(seconds=1), "event_digest": None}
    ).sealed()
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        audit.append(changed)
    audit.close()


@pytest.mark.parametrize(
    "change", ["no-start", "partial-success", "oversent", "scope", "hash", "backwards", "twice"]
)
def test_audit_rejects_invalid_terminal_transition_without_committing_it(
    tmp_path: Path, change: str
) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    audit = store(tmp_path / "audit.jsonl")
    admitted = event("DOWNLOAD_ADMITTED")
    audit.append(admitted)
    if change != "no-start":
        audit.append(event("STREAM_STARTED"))
    body: dict[str, Any] = dict(sent=128)
    if change == "partial-success":
        body["sent"] = 127
    elif change == "oversent":
        body["sent"] = 129
    elif change == "scope":
        body["organization_id"] = "foreign-org"
    elif change == "hash":
        body["output_sha256"] = "sha256:" + "b" * 64
    elif change == "backwards":
        body["at"] = NOW - timedelta(seconds=1)
    elif change == "twice":
        audit.append(event("STREAM_COMPLETED", sent=128))
    before = audit.events(organization_id="org-local", session_id=SESSION, limit=4)
    with pytest.raises((SpatialDataDomainError, ValueError)):
        audit.append(event("STREAM_COMPLETED", **body))
    assert audit.events(organization_id="org-local", session_id=SESSION, limit=4) == before
    audit.close()


def test_audit_start_fsync_failure_seals_lane_without_projecting_a_started_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_core.foundation.durable_journal as durable
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    audit = store(tmp_path / "audit.jsonl")
    admitted = event("DOWNLOAD_ADMITTED")
    audit.append(admitted)

    def failed_write(fd: int, payload: bytes) -> None:
        raise OSError("private-disk-details")

    monkeypatch.setattr(durable, "_WRITE", failed_write)
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE") as caught:
        audit.append(event("STREAM_STARTED"))
    assert "private-disk-details" not in str(caught.value)
    assert audit.events(organization_id="org-local", session_id=SESSION, limit=4) == (admitted,)
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        audit.append(admitted)
    audit.close()


def test_restart_does_not_invent_success_or_delivered_count_for_unfinished_stream(
    tmp_path: Path,
) -> None:
    path = tmp_path / "audit.jsonl"
    audit = store(path)
    audit.append(event("DOWNLOAD_ADMITTED"))
    started = event("STREAM_STARTED")
    audit.append(started)
    audit.close()
    audit = store(path)
    assert audit.unfinished(organization_id="org-local", limit=4) == (started,)
    assert all(
        item.action != "STREAM_COMPLETED"
        for item in audit.events(organization_id="org-local", session_id=SESSION, limit=4)
    )
    audit.close()


@pytest.mark.parametrize("change", ["sequence", "digest", "scope", "secret"])
def test_corrupt_complete_audit_record_blocks_recovery(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    import json

    from ksi_core.domains.external.delivery.audit import SpatialDataAuditRecoveryError

    path = tmp_path / "audit.jsonl"
    audit = store(path)
    audit.append(event("DOWNLOAD_ADMITTED"))
    audit.append(event("STREAM_STARTED"))
    audit.close()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    if change == "sequence":
        records[1]["sequence"] = 3
    elif change == "digest":
        records[1]["event"]["eventDigest"] = "sha256:" + "f" * 64
    elif change == "scope":
        records[1]["event"]["organizationId"] = "foreign-org"
    else:
        records[1]["event"]["token"] = "must-not-become-an-audit-field"
    path.write_text("".join(json.dumps(item) + "\n" for item in records))
    journal = DurableJournal(path)
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditStore

    try:
        with pytest.raises(SpatialDataAuditRecoveryError):
            SpatialDataAuditStore(journal, policy=make_policy())
    finally:
        journal.close()


def test_audit_event_and_query_budgets_fail_explicitly(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    audit = store(tmp_path / "audit.jsonl", max_json_bytes=256)
    with pytest.raises(SpatialDataDomainError, match="RESOURCE_LIMIT_EXCEEDED"):
        audit.append(event("DOWNLOAD_ADMITTED"))
    with pytest.raises(SpatialDataDomainError, match="RESOURCE_LIMIT_EXCEEDED"):
        audit.events(organization_id="org-local", session_id=SESSION, limit=9)
    audit.close()


def test_audit_reserves_terminal_capacity_before_admitting_other_streams(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    audit = store(tmp_path / "audit.jsonl", max_snapshot_bytes=4096, max_json_bytes=1024)
    audit.append(event("DOWNLOAD_ADMITTED"))
    with pytest.raises(SpatialDataDomainError, match="RESOURCE_LIMIT_EXCEEDED"):
        audit.append(event("DOWNLOAD_ADMITTED", session_id=str(uuid4())))
    audit.append(event("STREAM_STARTED"))
    audit.append(event("STREAM_INTERRUPTED", sent=128))
    audit.close()


def test_audit_actual_fsync_failure_never_projects_started_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_core.foundation.durable_journal as durable
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    audit = store(tmp_path / "audit.jsonl")
    audit.append(event("DOWNLOAD_ADMITTED"))

    def failed_fsync(fd: int) -> None:
        raise OSError("private fsync failure")

    monkeypatch.setattr(durable.os, "fsync", failed_fsync)
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        audit.append(event("STREAM_STARTED"))
    assert len(audit.events(organization_id="org-local", session_id=SESSION, limit=4)) == 1
    audit.close()
