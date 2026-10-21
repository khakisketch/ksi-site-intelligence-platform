"""Durable preparation jobs deny stale authority/fences without rewriting historical execution."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from typing import Any, get_args

import pytest
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.identity.auth import Role
from ksi_event_contracts.spatial_data import SpatialDataReasonV1
from ksi_event_contracts.spatial_data_authority import SpatialDataRevocationV1
from spatial_data_job_fixture import (
    issue,
    job_graph,
    job_store,
    lease,
    receipt_for,
    reserve_and_complete,
)
from support.external_artifact_inspection_fixtures import NOW


def test_changed_payload_conflicts(tmp_path: Path) -> None:
    """An idempotency retry must not silently substitute another requested rectangle."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    original = issue(store, graph)
    assert issue(store, graph).job_id == original.job_id
    with pytest.raises(SpatialDataDomainError) as error:
        issue(store, graph, requested_bounds=(0, 0, 2, 2))
    assert (error.value.reason, error.value.status_code) == ("IDEMPOTENCY_CONFLICT", 409)
    assert "one" not in (tmp_path / "jobs.jsonl").read_text()


def test_pending_revoked_job_cannot_suppress_independent_current_job(tmp_path: Path) -> None:
    """Exact grant withdrawal blocks that work, not an independently authorized successor."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    revoked = issue(store, graph, key="revoked")
    graph.grants.revoke(SpatialDataRevocationV1(
        grant_id=graph.grant.grant_id, revision=graph.grant.revision,
        organization_id=graph.grant.organization_id, grant_digest=graph.grant.grant_digest,
        revoked_at=NOW, reason="owner withdrew exact revision",
    ).sealed())
    graph.grants.provision(
        graph.grant.model_copy(update={"revision": 2, "grant_digest": None}).sealed()
    )
    current = issue(store, graph, key="current")
    try:
        assert [job.job_id for job in store.pending(worker=graph.worker, limit=1, now=NOW)] == [
            current.job_id
        ]
        history = store.get(job_id=revoked.job_id, principal=graph.principal, now=NOW)
        assert history.execution_state == "QUEUED" and history.availability == "ACCESS_REVOKED"
        with pytest.raises(SpatialDataDomainError) as error:
            lease(store, graph, revoked)
        assert error.value.reason == "ACCESS_REVOKED"
        assert lease(store, graph, current).job_id == current.job_id
    finally:
        store._journal.close()  # noqa: SLF001


@pytest.mark.parametrize(
    "reason,status",
    [
        ("CURRENTNESS_UNAVAILABLE", 503),
        ("INTEGRITY_MISMATCH", 503),
        ("SOURCE_MEASUREMENTS_MISMATCH", 409),
    ],
)
def test_pending_does_not_hide_unavailable_or_corrupt_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    status: int,
) -> None:
    """Omit explicit ineligible records, but close polling on unknown authority faults."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    issue(store, graph)

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise SpatialDataDomainError(reason, status)

    monkeypatch.setattr(graph.sources, "require_current", unavailable)
    try:
        with pytest.raises(SpatialDataDomainError) as error:
            store.pending(worker=graph.worker, limit=1, now=NOW)
        assert (error.value.reason, error.value.status_code) == (reason, status)
    finally:
        store._journal.close()  # noqa: SLF001


def test_quota_reservation_is_atomic(tmp_path: Path) -> None:
    """Concurrent admissions must not both consume the last organization preparation slot."""
    graph = job_graph(tmp_path, quota=1)
    store = job_store(graph)
    barrier = Barrier(2)

    def run(key: str) -> str:
        barrier.wait()
        try:
            return issue(store, graph, key=key).execution_state
        except SpatialDataDomainError as error:
            return error.reason

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ("a", "b")))
    assert sorted(results) == ["CONCURRENCY_LIMIT_EXCEEDED", "QUEUED"]


def test_cancel_and_takeover_reject_late_completion(tmp_path: Path) -> None:
    """Expired/canceled worker fences cannot publish output, including after a new lease."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    first = lease(store, graph, job)
    assert lease(store, graph, job) == first
    takeover = lease(store, graph, job, acquisition="acquisition-2", now=first.lease_until)
    assert takeover.attempt_number == first.attempt_number + 1
    assert takeover.fence_digest() != first.fence_digest()
    with pytest.raises(SpatialDataDomainError) as error:
        store.worker_input(
            job_id=job.job_id, worker=graph.worker, attempt=first, now=first.lease_until
        )
    assert error.value.reason == "FENCE_CONFLICT"
    canceled = store.cancel(job_id=job.job_id, principal=graph.principal, now=first.lease_until)
    assert canceled.execution_state == "CANCELED"
    assert (
        store.cancel(job_id=job.job_id, principal=graph.principal, now=first.lease_until)
        == canceled
    )
    with pytest.raises(SpatialDataDomainError):
        store.worker_input(
            job_id=job.job_id, worker=graph.worker, attempt=takeover, now=first.lease_until
        )


def test_revoked_grant_preserves_history_not_bytes(tmp_path: Path) -> None:
    """Completed execution remains historical fact when its exact grant loses byte authority."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    attempt = lease(store, graph, job)
    accepted = reserve_and_complete(store, graph, job, attempt)
    assert accepted.completed.availability == "AVAILABLE"
    graph.grants.revoke(
        SpatialDataRevocationV1(
            grant_id=graph.grant.grant_id,
            revision=1,
            organization_id=graph.principal.organization_id,
            grant_digest=graph.grant.grant_digest,
            revoked_at=NOW,
            reason="owner withdrew rights",
        ).sealed()
    )
    revoked = store.get(job_id=job.job_id, principal=graph.principal, now=NOW)
    assert revoked.execution_state == "COMPLETED" and revoked.availability == "ACCESS_REVOKED"
    assert revoked.receipt == accepted.receipt
    with pytest.raises(SpatialDataDomainError):
        issue(store, graph)


def test_completion_retries_are_exact_and_terminal_cancel_is_not_deletion(tmp_path: Path) -> None:
    """One accepted report is durable; a retry may neither replace it nor cancel its history."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    attempt = lease(store, graph, job)
    accepted = reserve_and_complete(store, graph, job, attempt)
    assert (
        store.complete(
            job_id=job.job_id,
            worker=graph.worker,
            attempt=attempt,
            upload_digest=accepted.declaration.upload_digest,
            observation=accepted.observation,
            now=NOW,
        )
        == accepted.completed
    )
    with pytest.raises(SpatialDataDomainError) as error:
        store.complete(
            job_id=job.job_id,
            worker=graph.worker,
            attempt=attempt,
            upload_digest=accepted.declaration.upload_digest,
            observation=replace(accepted.observation, version_id="version-2"),
            now=NOW,
        )
    assert error.value.reason == "REPORT_CONFLICT"
    with pytest.raises(SpatialDataDomainError) as error:
        store.cancel(job_id=job.job_id, principal=graph.principal, now=NOW)
    assert error.value.status_code == 409


def test_requester_withdrawal_closes_worker_lane(tmp_path: Path) -> None:
    """A frozen requester's Principal must not authorize processing after its identity is gone."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    with graph.coordinator.mutation():
        graph.authority.principal = None
    with pytest.raises(SpatialDataDomainError) as error:
        lease(store, graph, job)
    assert error.value.reason == "CURRENTNESS_UNAVAILABLE"


def test_renewal_keeps_acquisition_fence_and_refuses_forged_extension(tmp_path: Path) -> None:
    """Renewal must not invalidate issued receipt fences or trust caller-written lease expiry."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    attempt = lease(store, graph, job)
    later = NOW + timedelta(seconds=1)
    renewed = store.renew(job_id=job.job_id, worker=graph.worker, attempt=attempt, now=later)
    assert renewed.fence_digest() == attempt.fence_digest()
    assert renewed.lease_until > attempt.lease_until
    forged = renewed.model_copy(
        update={"lease_until": NOW + timedelta(seconds=20), "attempt_digest": None}
    ).sealed()
    with pytest.raises(SpatialDataDomainError) as error:
        store.worker_input(job_id=job.job_id, worker=graph.worker, attempt=forged, now=later)
    assert error.value.reason == "FENCE_CONFLICT"


def test_admission_rechecks_requester_port_before_durable_commit(tmp_path: Path) -> None:
    """A supplied principal cannot bypass withdrawal in the canonical identity port."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    with graph.coordinator.mutation():
        graph.authority.principal = None
    with pytest.raises(SpatialDataDomainError) as error:
        issue(store, graph)
    assert error.value.reason == "CURRENTNESS_UNAVAILABLE"
    assert not (tmp_path / "jobs.jsonl").exists()


def test_transient_retry_backoff_and_attempt_budget_survive_restart(tmp_path: Path) -> None:
    """Transport failures may retry finitely, without resetting the budget on a process restart."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    first = lease(store, graph, job)
    failed = store.fail(
        job_id=job.job_id, worker=graph.worker, attempt=first, reason="STORAGE_UNAVAILABLE", now=NOW
    )
    assert failed.execution_state == "QUEUED"
    assert store.pending(worker=graph.worker, limit=1, now=NOW) == ()
    store._journal.close()  # noqa: SLF001
    store = job_store(graph)
    later = NOW + timedelta(seconds=graph.data_policy.min_retry_backoff_seconds)
    second = lease(store, graph, job, acquisition="acquisition-2", now=later)
    assert second.attempt_number == 2
    failed = store.fail(
        job_id=job.job_id,
        worker=graph.worker,
        attempt=second,
        reason="STORAGE_UNAVAILABLE",
        now=later,
    )
    assert failed.execution_state == "QUEUED"
    later += timedelta(seconds=graph.data_policy.min_retry_backoff_seconds)
    third = lease(store, graph, job, acquisition="acquisition-3", now=later)
    assert third.attempt_number == 3
    failed = store.fail(
        job_id=job.job_id,
        worker=graph.worker,
        attempt=third,
        reason="STORAGE_UNAVAILABLE",
        now=later,
    )
    assert failed.execution_state == "FAILED"


@pytest.mark.parametrize(
    "reason",
    [
        "EMPTY_VALID_WINDOW",
        "INVALID_SOURCE_SAMPLE",
        "SOURCE_BYTES_MISMATCH",
        "OUTPUT_VERIFICATION_FAILED",
        "ACCESS_REVOKED",
        "RASTER_PREPARATION_FAILED",
    ],
)
def test_nontransport_failures_are_terminal_and_keep_exact_reason(
    tmp_path: Path, reason: str
) -> None:
    """Format/hash/right failures cannot be disguised as an unbounded retry queue."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    attempt = lease(store, graph, job)
    failed = store.fail(
        job_id=job.job_id, worker=graph.worker, attempt=attempt, reason=reason, now=NOW
    )
    assert (failed.execution_state, failed.reason) == ("FAILED", reason)
    assert store.pending(worker=graph.worker, limit=1, now=NOW) == ()


def test_deadline_expiry_releases_quota_durably(tmp_path: Path) -> None:
    """Dead workers must not keep preparation slots forever or revive after the job deadline."""
    graph = job_graph(tmp_path, quota=1)
    store = job_store(graph)
    job = issue(store, graph)
    lease(store, graph, job)
    later = NOW + timedelta(seconds=graph.data_policy.resource_envelope.max_deadline_seconds)
    assert (
        store.get(job_id=job.job_id, principal=graph.principal, now=later).execution_state
        == "EXPIRED"
    )
    assert issue(store, graph, key="next", now=later).execution_state == "QUEUED"
    store._journal.close()  # noqa: SLF001
    restarted = job_store(graph)
    assert (
        restarted.get(job_id=job.job_id, principal=graph.principal, now=later).execution_state
        == "EXPIRED"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_digest", "sha256:" + "f" * 64),
        ("source_digest", "sha256:" + "f" * 64),
        ("artifact_id", "other-artifact"),
        ("source_sha256", "sha256:" + "f" * 64),
        ("source_size_bytes", 13),
        ("attribution", "substituted license"),
    ],
)
def test_output_reservation_rejects_resealed_substituted_receipt(
    tmp_path: Path, field: str, value: object
) -> None:
    """A valid receipt model/digest cannot substitute the frozen source/job/license lineage."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    attempt = lease(store, graph, job)
    receipt = receipt_for(store, graph, job, attempt)
    forged = receipt.model_copy(update={field: value, "receipt_digest": None}).sealed()
    before = (tmp_path / "jobs.jsonl").read_bytes()
    with pytest.raises(SpatialDataDomainError) as error:
        store.reserve_output(
            job_id=job.job_id,
            worker=graph.worker,
            attempt=attempt,
            receipt=forged,
            expires_at=NOW + timedelta(seconds=1),
            now=NOW,
        )
    assert error.value.reason == "REPORT_CONFLICT"
    assert (tmp_path / "jobs.jsonl").read_bytes() == before


def test_journal_failure_publishes_no_job_and_closes_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed fsync must not leave a usable admission/quota/idempotency projection."""
    graph = job_graph(tmp_path)
    store = job_store(graph)

    def no_disk(*args: Any) -> None:
        raise OSError("simulated failed fsync")

    monkeypatch.setattr(store._journal, "_append_durable", no_disk)  # noqa: SLF001
    with pytest.raises(SpatialDataDomainError) as error:
        issue(store, graph)
    assert error.value.reason == "AUDIT_UNAVAILABLE"
    assert store._records == {}  # noqa: SLF001
    with pytest.raises(SpatialDataDomainError) as error:
        issue(store, graph)
    assert error.value.reason == "CURRENTNESS_UNAVAILABLE"


def test_history_foreign_scope_owner_and_bounded_cursor(tmp_path: Path) -> None:
    """Paged history must not reveal another requester or silently ignore scope-bound cursors."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    first, second = issue(store, graph, key="a"), issue(store, graph, key="b")
    for other in (
        replace(graph.principal, organization_id="other"),
        replace(graph.principal, principal_id="other"),
        replace(graph.principal, allowed_site_ids=frozenset({"other"})),
    ):
        for job_id in (first.job_id, "sdj-v1-00000000-0000-0000-0000-000000000000"):
            with pytest.raises(SpatialDataDomainError) as error:
                store.get(job_id=job_id, principal=other, now=NOW)
            assert (error.value.reason, error.value.status_code) == ("NOT_FOUND", 404)
    page = store.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.principal,
        cursor=None,
        limit=1,
        now=NOW,
    )
    assert page.next_cursor is not None and len(page.items) == 1
    next_page = store.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.principal,
        cursor=page.next_cursor,
        limit=1,
        now=NOW,
    )
    assert next_page.next_cursor is None
    assert {item.job_id for item in (*page.items, *next_page.items)} == {
        first.job_id,
        second.job_id,
    }


def test_reserved_orphan_is_owned_before_signing_and_waits_for_expiry(tmp_path: Path) -> None:
    """A canceled upload target must survive restart and cannot be deleted while it can write."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    attempt = lease(store, graph, job)
    receipt = receipt_for(store, graph, job, attempt)
    target = store.reserve_output(
        job_id=job.job_id,
        worker=graph.worker,
        attempt=attempt,
        receipt=receipt,
        expires_at=NOW + timedelta(seconds=1),
        now=NOW,
    )
    assert target.object_key in (tmp_path / "jobs.jsonl").read_text()
    store.cancel(job_id=job.job_id, principal=graph.principal, now=NOW)
    method = getattr(store, "cleanup_pending", None)
    assert callable(method), "durable orphan ownership projection missing"
    assert method(limit=8, now=NOW) == ()
    store._journal.close()  # noqa: SLF001
    replayed = job_store(graph)
    pending = replayed.cleanup_pending(limit=8, now=target.expires_at)
    assert len(pending) == 1 and pending[0].target == target and pending[0].observation is None


def test_live_accepted_output_cannot_become_cleanup_candidate_before_retention(
    tmp_path: Path,
) -> None:
    """Capability expiry alone must never authorize deletion of an accepted live output version."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    accepted = reserve_and_complete(store, graph, job, lease(store, graph, job))
    method = getattr(store, "cleanup_pending", None)
    assert callable(method), "durable retention ownership projection missing"
    assert method(limit=8, now=accepted.target.expires_at) == ()
    later = NOW + timedelta(seconds=graph.data_policy.retention_seconds)
    (obligation,) = method(limit=8, now=later)
    assert obligation.observation == accepted.observation and obligation.target == accepted.target


def test_expired_reservation_retry_does_not_reissue_output_target(tmp_path: Path) -> None:
    """Cleanup-ready upload targets cannot acquire a new ability to write on a retry."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    attempt = lease(store, graph, job)
    receipt = receipt_for(store, graph, job, attempt)
    expiry = NOW + timedelta(seconds=1)
    target = store.reserve_output(
        job_id=job.job_id,
        worker=graph.worker,
        attempt=attempt,
        receipt=receipt,
        expires_at=expiry,
        now=NOW,
    )
    assert (
        store.reserve_output(
            job_id=job.job_id,
            worker=graph.worker,
            attempt=attempt,
            receipt=receipt,
            expires_at=expiry,
            now=NOW,
        )
        == target
    )
    with pytest.raises(SpatialDataDomainError) as error:
        store.reserve_output(
            job_id=job.job_id,
            worker=graph.worker,
            attempt=attempt,
            receipt=receipt,
            expires_at=expiry,
            now=expiry,
        )
    assert error.value.reason == "LEASE_EXPIRED"


def test_renewed_attempt_cannot_change_existing_upload_declaration(tmp_path: Path) -> None:
    """A stable fence must not hide substitution of the sealed lease-bound upload declaration."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    attempt = lease(store, graph, job)
    receipt = receipt_for(store, graph, job, attempt)
    expiry = NOW + timedelta(seconds=4)
    store.reserve_output(
        job_id=job.job_id,
        worker=graph.worker,
        attempt=attempt,
        receipt=receipt,
        expires_at=expiry,
        now=NOW,
    )
    later = NOW + timedelta(seconds=1)
    renewed = store.renew(job_id=job.job_id, worker=graph.worker, attempt=attempt, now=later)
    with pytest.raises(SpatialDataDomainError) as error:
        store.reserve_output(
            job_id=job.job_id,
            worker=graph.worker,
            attempt=renewed,
            receipt=receipt,
            expires_at=expiry,
            now=later,
        )
    assert error.value.reason == "REPORT_CONFLICT"


@pytest.mark.parametrize(
    "field,value",
    [
        ("object_key", "external-reconstruction/v1/source.tif"),
        ("sha256", "sha256:" + "f" * 64),
        ("size_bytes", 65),
    ],
)
def test_completion_refuses_substituted_observed_output(
    tmp_path: Path, field: str, value: object
) -> None:
    """Matching an upload ID must not suffice to publish another key/hash/size."""
    from ksi_core.domains.external.delivery.storage_types import SpatialDataObjectObservation
    from ksi_event_contracts.spatial_data_worker import SpatialDataUploadDeclarationV1

    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    attempt = lease(store, graph, job)
    receipt = receipt_for(store, graph, job, attempt)
    target = store.reserve_output(
        job_id=job.job_id,
        worker=graph.worker,
        attempt=attempt,
        receipt=receipt,
        expires_at=NOW + timedelta(seconds=1),
        now=NOW,
    )
    declaration = SpatialDataUploadDeclarationV1(
        attempt=attempt,
        receipt=receipt,
        sha256=receipt.output_sha256,
        size_bytes=receipt.output_size_bytes,
        content_type="image/tiff",
    ).sealed()
    observation_payload: dict[str, Any] = {
            "object_key": target.object_key,
            "version_id": "version-1",
            "size_bytes": receipt.output_size_bytes,
            "sha256": receipt.output_sha256,
            "content_type": "image/tiff",
            field: value,
        }
    observation = SpatialDataObjectObservation(**observation_payload)
    assert declaration.upload_digest is not None
    with pytest.raises(SpatialDataDomainError) as error:
        store.complete(
            job_id=job.job_id,
            worker=graph.worker,
            attempt=attempt,
            upload_digest=declaration.upload_digest,
            observation=observation,
            now=NOW,
        )
    assert error.value.reason == "INTEGRITY_MISMATCH"
    assert (
        store.get(job_id=job.job_id, principal=graph.principal, now=NOW).execution_state
        == "RUNNING"
    )


@pytest.mark.parametrize(
    "reason",
    [reason for reason in get_args(SpatialDataReasonV1) if reason != "STORAGE_UNAVAILABLE"],
)
def test_full_typed_terminal_failure_matrix_is_finite(tmp_path: Path, reason: str) -> None:
    """Any nonallowlisted typed failure is terminal, not an inferred retryable exception."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    attempt = lease(store, graph, job)
    failed = store.fail(
        job_id=job.job_id, worker=graph.worker, attempt=attempt, reason=reason, now=NOW
    )
    assert failed.execution_state == "FAILED" and failed.reason == reason
    with pytest.raises(SpatialDataDomainError):
        lease(store, graph, job, acquisition="cannot-retry")


def test_takeover_and_cancel_refuse_actual_late_publication(tmp_path: Path) -> None:
    """A stale full report, not just stale input lookup, must fail after takeover/cancel."""
    from ksi_core.domains.external.delivery.storage_types import SpatialDataObjectObservation
    from ksi_event_contracts.spatial_data_worker import SpatialDataUploadDeclarationV1

    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    first = lease(store, graph, job)
    receipt = receipt_for(store, graph, job, first)
    target = store.reserve_output(
        job_id=job.job_id,
        worker=graph.worker,
        attempt=first,
        receipt=receipt,
        expires_at=NOW + timedelta(seconds=1),
        now=NOW,
    )
    declaration = SpatialDataUploadDeclarationV1(
        attempt=first,
        receipt=receipt,
        sha256=receipt.output_sha256,
        size_bytes=receipt.output_size_bytes,
        content_type="image/tiff",
    ).sealed()
    observation = SpatialDataObjectObservation(
        target.object_key,
        "version-late",
        receipt.output_size_bytes,
        receipt.output_sha256,
        "image/tiff",
    )
    takeover = lease(store, graph, job, acquisition="takeover", now=first.lease_until)
    assert declaration.upload_digest is not None
    for state in ("RUNNING", "CANCELED"):
        if state == "CANCELED":
            store.cancel(job_id=job.job_id, principal=graph.principal, now=first.lease_until)
        with pytest.raises(SpatialDataDomainError):
            store.complete(
                job_id=job.job_id,
                worker=graph.worker,
                attempt=first,
                upload_digest=declaration.upload_digest,
                observation=observation,
                now=first.lease_until,
            )
        assert (
            store.get(
                job_id=job.job_id, principal=graph.principal, now=first.lease_until
            ).execution_state
            == state
        )
    assert takeover.fence == first.fence + 1


def test_foreign_history_is_404_before_sealed_job_journal_details(tmp_path: Path) -> None:
    """A failed local journal must not reveal availability details to foreign/unknown jobs."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    store._journal._sealed_reason = "simulated unavailable disk"  # noqa: SLF001
    for job_id in (job.job_id, "sdj-v1-00000000-0000-0000-0000-000000000000"):
        with pytest.raises(SpatialDataDomainError) as error:
            store.get(
                job_id=job_id, principal=replace(graph.principal, organization_id="other"), now=NOW
            )
        assert (error.value.reason, error.value.status_code) == ("NOT_FOUND", 404)
    own = store.get(job_id=job.job_id, principal=graph.principal, now=NOW)
    assert own.availability == "UNAVAILABLE" and own.reason == "CURRENTNESS_UNAVAILABLE"


def test_inspection_outage_closes_bytes_without_hiding_completed_history(tmp_path: Path) -> None:
    """Unavailable report currentness must not erase a scoped completed preparation receipt."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    accepted = reserve_and_complete(store, graph, job, lease(store, graph, job))
    graph.inspections._journal._sealed_reason = "simulated report journal outage"  # noqa: SLF001
    current = store.get(job_id=job.job_id, principal=graph.principal, now=NOW)
    assert current.execution_state == "COMPLETED" and current.receipt == accepted.receipt
    assert current.availability == "UNAVAILABLE" and current.reason == "CURRENTNESS_UNAVAILABLE"


def test_list_read_download_coherence_is_requester_owned(tmp_path: Path) -> None:
    """LIST, READ, cancel and bytes agree: only the requesting principal sees its jobs.

    An organization ADMIN sees neither foreign metadata in the list nor the
    single-job view, so a window that exists but belongs to another principal
    is reported as missing (never as a preparation FAILURE), and the byte
    path stays requester-bound. Revocation/expiry, cross-tenant denial and
    the list budget/cursor semantics are unchanged.
    """
    graph = job_graph(tmp_path)
    store = job_store(graph)
    first = issue(store, graph, key="a")
    second = issue(store, graph, key="b")
    other = replace(graph.principal, principal_id="other-operator")
    admin = replace(graph.principal, principal_id="admin-a", role=Role.ADMIN)
    foreign_tenant = replace(graph.principal, organization_id="other-org")

    def list_ids(principal: object) -> tuple[str, ...]:
        page = store.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=principal,  # type: ignore[arg-type]
            cursor=None,
            limit=1,
            now=NOW,
        )
        return tuple(item.job_id for item in page.items), page.next_cursor  # type: ignore[return-value]

    # Coherence before completion: same-org foreigners see nothing, owner sees both.
    for foreign in (other, admin):
        for job_id in (first.job_id, second.job_id):
            with pytest.raises(SpatialDataDomainError) as error:
                store.get(job_id=job_id, principal=foreign, now=NOW)
            assert (error.value.reason, error.value.status_code) == ("NOT_FOUND", 404)
            with pytest.raises(SpatialDataDomainError) as error:
                store.cancel(job_id=job_id, principal=foreign, now=NOW)
            assert (error.value.reason, error.value.status_code) == ("NOT_FOUND", 404)
            with pytest.raises(SpatialDataDomainError) as error:
                store.require_download(job_id=job_id, principal=foreign, now=NOW)
            assert (error.value.reason, error.value.status_code) == ("NOT_FOUND", 404)
        items, cursor = list_ids(foreign)
        assert items == () and cursor is None
    # Cross-tenant stays denied at the scope gate (typed 404, never an empty leak).
    for job_id in (first.job_id, second.job_id):
        with pytest.raises(SpatialDataDomainError) as error:
            store.get(job_id=job_id, principal=foreign_tenant, now=NOW)
        assert (error.value.reason, error.value.status_code) == ("NOT_FOUND", 404)
    with pytest.raises(SpatialDataDomainError) as error:
        store.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=foreign_tenant,
            cursor=None,
            limit=1,
            now=NOW,
        )
    assert (error.value.reason, error.value.status_code) == ("NOT_FOUND", 404)
    assert store.get(job_id=first.job_id, principal=graph.principal, now=NOW) == first
    owner_ids, owner_cursor = list_ids(graph.principal)
    assert len(owner_ids) == 1 and owner_ids[0] in (first.job_id, second.job_id)
    assert owner_cursor is not None
    owner_page2 = store.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.principal,
        cursor=owner_cursor,
        limit=1,
        now=NOW,
    )
    assert {owner_ids[0], owner_page2.items[0].job_id} == {first.job_id, second.job_id}
    assert owner_page2.next_cursor is None

    # Byte path stays requester-bound after completion.
    accepted = reserve_and_complete(store, graph, first, lease(store, graph, first))
    assert accepted.completed.availability == "AVAILABLE"
    assert (
        store.require_download(job_id=first.job_id, principal=graph.principal, now=NOW).observation
        == accepted.observation
    )
    for foreign in (other, admin, foreign_tenant):
        with pytest.raises(SpatialDataDomainError) as error:
            store.require_download(job_id=first.job_id, principal=foreign, now=NOW)
        assert (error.value.reason, error.value.status_code) == ("NOT_FOUND", 404)
        with pytest.raises(SpatialDataDomainError) as error:
            store.get(job_id=first.job_id, principal=foreign, now=NOW)
        assert (error.value.reason, error.value.status_code) == ("NOT_FOUND", 404)

    # Revocation/expiry currentness is still honoured for the owner and never
    # discloses a foreign job as revoked/expired.
    graph.grants.revoke(
        SpatialDataRevocationV1(
            grant_id=graph.grant.grant_id,
            revision=graph.grant.revision,
            organization_id=graph.principal.organization_id,
            grant_digest=graph.grant.grant_digest,
            revoked_at=NOW,
            reason="owner withdrew rights",
        ).sealed()
    )
    revoked = store.get(job_id=first.job_id, principal=graph.principal, now=NOW)
    assert revoked.execution_state == "COMPLETED" and revoked.availability == "ACCESS_REVOKED"
    for foreign in (other, admin):
        with pytest.raises(SpatialDataDomainError) as error:
            store.get(job_id=first.job_id, principal=foreign, now=NOW)
        assert (error.value.reason, error.value.status_code) == ("NOT_FOUND", 404)

    # List budget enforcement is unchanged.
    with pytest.raises(SpatialDataDomainError) as error:
        store.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=graph.principal,
            cursor=None,
            limit=200,
            now=NOW,
        )
    assert (error.value.reason, error.value.status_code) == ("RESOURCE_LIMIT_EXCEEDED", 422)
