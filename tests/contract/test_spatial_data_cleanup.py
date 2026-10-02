"""Exact target cleanup with durable ownership; no evidence/source enumeration is allowed."""

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.storage_types import (
    SpatialDataObjectObservation,
    SpatialDataOutputTarget,
)
from spatial_data_download_fixture import delivery_graph
from spatial_data_job_fixture import NOW, job_store


class OwnedVersions:
    def __init__(self, observation: SpatialDataObjectObservation) -> None:
        self.versions = {observation.version_id: observation}
        self.deleted: list[tuple[SpatialDataOutputTarget, str]] = []
        self.listed: list[SpatialDataOutputTarget] = []
        self.fail = False

    def list_owned_versions(
        self, target: SpatialDataOutputTarget, *, limit: int
    ) -> tuple[SpatialDataObjectObservation, ...]:
        assert target.object_key.startswith("spatial-data/v1/")
        self.listed.append(target)
        if self.fail:
            raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503)
        if len(self.versions) > limit:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        return tuple(self.versions.values())

    def delete_owned_version(self, target: SpatialDataOutputTarget, version_id: str) -> None:
        assert version_id in self.versions
        assert self.versions[version_id].object_key == target.object_key
        self.deleted.append((target, version_id))
        del self.versions[version_id]


def run(graph: SimpleNamespace, storage: Any, now: datetime) -> Any:
    from ksi_core.domains.external.delivery.cleanup import run_spatial_data_cleanup_once

    return run_spatial_data_cleanup_once(
        jobs=graph.jobs, storage=storage, audit=graph.audit, now=now
    )


def test_cleanup_protects_accepted_live_output_then_retires_after_retention(tmp_path: Path) -> None:
    graph = delivery_graph(tmp_path)
    storage = OwnedVersions(graph.observation)
    assert run(graph, storage, NOW + timedelta(seconds=6)) == 0
    assert storage.deleted == storage.listed == []
    expired = NOW + timedelta(seconds=graph.graph.data_policy.retention_seconds)
    assert run(graph, storage, expired) == 1
    assert storage.deleted[0][1] == "pinned-v1"
    assert graph.jobs.cleanup_pending(limit=1, now=expired) == ()
    assert (
        graph.jobs.get(
            job_id=graph.issued.job_id, principal=graph.graph.principal, now=expired
        ).receipt
        is not None
    )
    graph.jobs._journal.close()
    graph.jobs = job_store(graph.graph)
    assert graph.jobs.cleanup_pending(limit=1, now=expired) == ()
    assert run(graph, storage, expired) == 0


def test_cleanup_failed_inventory_retries_after_restart_but_never_marks_deleted(
    tmp_path: Path,
) -> None:
    graph = delivery_graph(tmp_path)
    storage = OwnedVersions(graph.observation)
    storage.fail = True
    now = NOW + timedelta(seconds=graph.graph.data_policy.retention_seconds)
    assert run(graph, storage, now) == 0
    assert storage.deleted == []
    assert graph.jobs.cleanup_status(job_id=graph.issued.job_id)[0].state == "FAILED"
    graph.jobs._journal.close()
    graph.jobs = job_store(graph.graph)
    storage.fail = False
    assert (
        run(
            graph,
            storage,
            now + timedelta(seconds=graph.graph.data_policy.min_retry_backoff_seconds + 1),
        )
        == 1
    )
    assert graph.jobs.cleanup_status(job_id=graph.issued.job_id)[0].state == "COMPLETED"


def test_cleanup_exhaustion_is_durable_visible_and_does_not_free_slot(tmp_path: Path) -> None:
    graph = delivery_graph(tmp_path)
    storage = OwnedVersions(graph.observation)
    storage.fail = True
    now = NOW + timedelta(seconds=graph.graph.data_policy.retention_seconds)
    for index in range(graph.graph.data_policy.max_cleanup_attempts):
        assert (
            run(
                graph,
                storage,
                now
                + timedelta(
                    seconds=index * (graph.graph.data_policy.min_retry_backoff_seconds + 1)
                ),
            )
            == 0
        )
    status = graph.jobs.cleanup_status(job_id=graph.issued.job_id)[0]
    assert (
        status.state == "FAILED"
        and status.attempt_number == graph.graph.data_policy.max_cleanup_attempts
    )
    graph.jobs._journal.close()
    graph.jobs = job_store(graph.graph)
    assert run(graph, storage, now + timedelta(seconds=60)) == 0
    assert graph.jobs.cleanup_status(job_id=graph.issued.job_id)[0] == status
    assert storage.deleted == []


def test_cleanup_inventory_of_foreign_or_duplicate_versions_fails_closed(tmp_path: Path) -> None:
    from dataclasses import replace

    graph = delivery_graph(tmp_path)
    storage = OwnedVersions(graph.observation)
    storage.versions["foreign"] = replace(
        graph.observation, object_key="external-source/customer/original.tif", version_id="foreign"
    )
    now = NOW + timedelta(seconds=graph.graph.data_policy.retention_seconds)
    assert run(graph, storage, now) == 0
    assert storage.deleted == []
    assert graph.jobs.cleanup_status(job_id=graph.issued.job_id)[0].reason == "INTEGRITY_MISMATCH"


def test_cleanup_requires_current_exact_reserved_handle_for_every_delete(tmp_path: Path) -> None:
    graph = delivery_graph(tmp_path)
    now = NOW + timedelta(seconds=graph.graph.data_policy.retention_seconds)
    candidate = graph.jobs.cleanup_pending(limit=1, now=now)[0]
    handle = graph.jobs.reserve_cleanup(candidate=candidate, now=now)
    assert graph.jobs.reserve_cleanup(candidate=candidate, now=now) is None
    graph.jobs.require_cleanup(handle=handle, now=now)
    with pytest.raises(SpatialDataDomainError, match="LEASE_EXPIRED"):
        graph.jobs.require_cleanup(
            handle=handle,
            now=now + timedelta(seconds=graph.graph.data_policy.cleanup_deadline_seconds),
        )
    replacement = graph.jobs.reserve_cleanup(
        candidate=candidate,
        now=now + timedelta(seconds=graph.graph.data_policy.cleanup_deadline_seconds),
    )
    assert replacement.cleanup_id != handle.cleanup_id
    with pytest.raises(SpatialDataDomainError, match="FENCE_CONFLICT"):
        graph.jobs.require_cleanup(handle=handle, now=replacement.started_at)


def test_cleanup_expired_reservation_never_audits_success_even_if_inventory_was_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = delivery_graph(tmp_path)
    storage = OwnedVersions(graph.observation)

    def lost(*, handle: Any, now: datetime, reason: str | None = None) -> None:
        if reason is None:
            raise SpatialDataDomainError("LEASE_EXPIRED", 409)
        original(handle=handle, now=now, reason=reason)

    original = graph.jobs.finish_cleanup
    monkeypatch.setattr(graph.jobs, "finish_cleanup", lost)
    now = NOW + timedelta(seconds=graph.graph.data_policy.retention_seconds)
    assert run(graph, storage, now) == 0
    status = graph.jobs.cleanup_status(job_id=graph.issued.job_id)[0]
    history = graph.audit.events(
        organization_id=graph.graph.principal.organization_id, session_id=status.cleanup_id, limit=4
    )
    assert all(item.action != "CLEANUP_COMPLETED" for item in history)
    assert status.state == "FAILED"


def test_cleanup_delete_failure_retains_remaining_versions_and_retries_exact_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    graph = delivery_graph(tmp_path)
    storage = OwnedVersions(graph.observation)
    storage.versions["late-upload"] = replace(graph.observation, version_id="late-upload")
    normal = storage.delete_owned_version

    def interrupted(target: SpatialDataOutputTarget, version_id: str) -> None:
        if version_id == "late-upload":
            raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503)
        normal(target, version_id)

    monkeypatch.setattr(storage, "delete_owned_version", interrupted)
    now = NOW + timedelta(seconds=graph.graph.data_policy.retention_seconds)
    assert run(graph, storage, now) == 0
    assert list(storage.versions) == ["late-upload"]
    graph.jobs._journal.close()
    graph.jobs = job_store(graph.graph)
    monkeypatch.setattr(storage, "delete_owned_version", normal)
    assert run(graph, storage, now + timedelta(seconds=2)) == 1
    assert [version for target, version in storage.deleted] == ["pinned-v1", "late-upload"]


def test_cleanup_cancelled_orphan_waits_until_capability_expiry_and_cannot_delete_source(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from ksi_core.domains.external.delivery.audit import SpatialDataAuditStore
    from ksi_core.domains.external.delivery.storage_types import SpatialDataObjectObservation
    from ksi_core.durable_journal import DurableJournal
    from spatial_data_job_fixture import issue, job_graph, lease, receipt_for

    graph = job_graph(tmp_path)
    jobs = job_store(graph)
    job = issue(jobs, graph)
    attempt = lease(jobs, graph, job)
    receipt = receipt_for(jobs, graph, job, attempt)
    target = jobs.reserve_output(
        job_id=job.job_id,
        worker=graph.worker,
        attempt=attempt,
        receipt=receipt,
        expires_at=attempt.lease_until,
        now=NOW,
    )
    jobs.cancel(job_id=job.job_id, principal=graph.principal, now=NOW)
    observation = SpatialDataObjectObservation(
        target.object_key,
        "orphan-upload",
        receipt.output_size_bytes,
        receipt.output_sha256,
        "image/tiff",
    )
    storage = OwnedVersions(observation)
    adapter = SimpleNamespace(
        jobs=jobs,
        audit=SpatialDataAuditStore(
            DurableJournal(tmp_path / "audit.jsonl"), policy=graph.data_policy
        ),
    )
    assert run(adapter, storage, attempt.lease_until - timedelta(microseconds=1)) == 0
    assert run(adapter, storage, attempt.lease_until) == 1
    assert storage.deleted == [(target, "orphan-upload")]
    assert (
        jobs.get(
            job_id=job.job_id, principal=graph.principal, now=attempt.lease_until
        ).execution_state.value
        == "CANCELED"
    )


@pytest.mark.parametrize("mutation", ["foreign-fence", "early", "skip-attempt", "false-retirement"])
def test_cleanup_corrupt_reservation_or_unproved_retirement_blocks_replay(
    tmp_path: Path, mutation: str
) -> None:
    import json

    from ksi_core.domains.external.delivery.jobs import SpatialDataJobRecoveryError

    graph = delivery_graph(tmp_path)
    now = NOW + timedelta(seconds=graph.graph.data_policy.retention_seconds)
    candidate = graph.jobs.cleanup_pending(limit=1, now=now)[0]
    graph.jobs.reserve_cleanup(candidate=candidate, now=now)
    graph.jobs._journal.close()
    path = tmp_path / "jobs.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    if mutation == "foreign-fence":
        records[-1]["fenceDigest"] = "sha256:" + "f" * 64
    elif mutation == "early":
        records[-1]["at"] = NOW.isoformat()
    elif mutation == "skip-attempt":
        records[-1]["attemptNumber"] = 2
    else:
        records[-1]["state"] = "COMPLETED"
    path.write_text("".join(json.dumps(item) + "\n" for item in records))
    with pytest.raises(SpatialDataJobRecoveryError):
        job_store(graph.graph)


@pytest.mark.parametrize("mutation", ["duplicate", "over-limit", "invalid-type"])
def test_cleanup_incomplete_or_untrusted_inventory_never_deletes_any_version(
    tmp_path: Path, mutation: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = delivery_graph(tmp_path)
    storage = OwnedVersions(graph.observation)

    def listing(target: SpatialDataOutputTarget, *, limit: int) -> tuple[object, ...]:
        if mutation == "duplicate":
            return (graph.observation, graph.observation)
        if mutation == "over-limit":
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        return (object(),)

    monkeypatch.setattr(storage, "list_owned_versions", listing)
    now = NOW + timedelta(seconds=graph.graph.data_policy.retention_seconds)
    assert run(graph, storage, now) == 0
    assert storage.deleted == []
    expected = "RESOURCE_LIMIT_EXCEEDED" if mutation == "over-limit" else "INTEGRITY_MISMATCH"
    assert graph.jobs.cleanup_status(job_id=graph.issued.job_id)[0].reason == expected


def test_cleanup_last_crashed_attempt_recovers_as_visible_exhausted_failure(tmp_path: Path) -> None:
    graph = delivery_graph(tmp_path)
    storage = OwnedVersions(graph.observation)
    now = NOW + timedelta(seconds=graph.graph.data_policy.retention_seconds)
    for _ in range(graph.graph.data_policy.max_cleanup_attempts):
        candidate = graph.jobs.cleanup_pending(limit=1, now=now)[0]
        graph.jobs.reserve_cleanup(candidate=candidate, now=now)
        now += timedelta(seconds=graph.graph.data_policy.cleanup_deadline_seconds)
    graph.jobs._journal.close()
    graph.jobs = job_store(graph.graph)
    assert run(graph, storage, now) == 0
    status = graph.jobs.cleanup_status(job_id=graph.issued.job_id)[0]
    assert status.state == "FAILED" and status.reason == "DEADLINE_EXCEEDED"
    assert storage.deleted == []
