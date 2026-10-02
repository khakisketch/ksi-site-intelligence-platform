"""Real fsynced job replay keeps scoped idempotency, quota and accepted output history."""

import json
from pathlib import Path

import pytest
from spatial_data_job_fixture import issue, job_graph, job_store, lease, reserve_and_complete
from support.external_artifact_inspection_fixtures import NOW


def test_same_scoped_key_survives_restart(tmp_path: Path) -> None:
    """Memory-only idempotency would allocate another persistent preparation after restart."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    issued = issue(store, graph)
    before = (tmp_path / "jobs.jsonl").read_bytes()
    store._journal.close()  # noqa: SLF001
    restarted = job_store(graph)
    replayed = issue(restarted, graph)
    assert replayed.job_id == issued.job_id
    assert (tmp_path / "jobs.jsonl").read_bytes() == before


def test_completed_receipt_and_owned_version_survive_restart(tmp_path: Path) -> None:
    """Publication reconstructed without its version/receipt would permit wrong-byte downloads."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    issued = issue(store, graph)
    accepted = reserve_and_complete(store, graph, issued, lease(store, graph, issued))
    store._journal.close()  # noqa: SLF001
    restarted = job_store(graph)
    assert (
        restarted.get(job_id=issued.job_id, principal=graph.principal, now=NOW)
        == accepted.completed
    )


@pytest.mark.parametrize(
    "mutation", ["unsealed", "sequence", "duplicate", "impossible-completion", "outside-grant"]
)
def test_corrupt_snapshot_or_transition_refuses_whole_replay(tmp_path: Path, mutation: str) -> None:
    """Skipped or weakly validated corrupt records must not yield a partial authorizing store."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    issue(store, graph)
    store._journal.close()  # noqa: SLF001
    path = tmp_path / "jobs.jsonl"
    event = json.loads(path.read_text())
    if mutation == "unsealed":
        event["job"]["jobDigest"] = None
    elif mutation == "sequence":
        event["sequence"] = 2
    elif mutation == "duplicate":
        path.write_text(json.dumps(event) + "\n" + json.dumps(event) + "\n")
    elif mutation == "impossible-completion":
        event["recordType"] = "spatial-data-job.completed.v1"
    elif mutation == "outside-grant":
        from ksi_event_contracts.spatial_data import SpatialDataFrozenJobV1

        frozen = SpatialDataFrozenJobV1.model_validate(event["job"])
        request = frozen.request.model_copy(update={"requested_bounds": (0, 0, 2, 2)})
        grant = frozen.grant.model_copy(
            update={"allowed_bounds": (0, 0, 1, 1), "grant_digest": None}
        ).sealed()
        frozen = frozen.model_copy(
            update={
                "request": request,
                "request_fingerprint": request.canonical_digest(),
                "grant": grant,
                "job_digest": None,
            }
        ).sealed()
        event["job"] = frozen.model_dump(by_alias=True, mode="json")
    if mutation != "duplicate":
        path.write_text(json.dumps(event) + "\n")
    from ksi_core.domains.external.delivery.jobs import SpatialDataJobRecoveryError

    with pytest.raises(SpatialDataJobRecoveryError):
        job_store(graph)


def test_quota_reservation_survives_restart(tmp_path: Path) -> None:
    """Reopening the job journal must not reset the sole pending organization reservation."""
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = job_graph(tmp_path, quota=1)
    store = job_store(graph)
    issue(store, graph)
    store._journal.close()  # noqa: SLF001
    restarted = job_store(graph)
    with pytest.raises(SpatialDataDomainError) as error:
        issue(restarted, graph, key="different")
    assert (error.value.reason, error.value.status_code) == ("CONCURRENCY_LIMIT_EXCEEDED", 429)


@pytest.mark.parametrize(
    "field", ["fence", "attemptNumber", "acquisitionKeyHash", "frozenJobDigest"]
)
def test_resealed_attempt_substitution_is_refused_on_replay(tmp_path: Path, field: str) -> None:
    """Rehashing a substituted attempt does not make an impossible durable fence authentic."""
    from ksi_core.domains.external.delivery.jobs import SpatialDataJobRecoveryError
    from ksi_event_contracts.spatial_data import SpatialDataAttemptV1

    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    lease(store, graph, job)
    store._journal.close()  # noqa: SLF001
    path = tmp_path / "jobs.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    wire = events[-1]["attempt"]
    if field == "acquisitionKeyHash":
        # Reuse the same acquisition across the *next* lease instead of claiming a
        # different unobservable original raw key, which the journal intentionally lacks.
        attempt = SpatialDataAttemptV1.model_validate(wire)
        from datetime import timedelta

        next_attempt = attempt.model_copy(
            update={
                "attempt_number": 2,
                "fence": 2,
                "acquired_at": attempt.lease_until,
                "lease_until": attempt.lease_until + timedelta(seconds=5),
                "attempt_digest": None,
            }
        ).sealed()
        events.append(
            {
                **events[-1],
                "sequence": 3,
                "at": next_attempt.acquired_at.isoformat(),
                "attempt": next_attempt.model_dump(by_alias=True, mode="json"),
            }
        )
    else:
        wire[field] = 2 if field in ("fence", "attemptNumber") else "sha256:" + "f" * 64
        wire["attemptDigest"] = None
        attempt = SpatialDataAttemptV1.model_validate(wire).sealed()
        events[-1]["attempt"] = attempt.model_dump(by_alias=True, mode="json")
    path.write_text("".join(json.dumps(event) + "\n" for event in events))
    with pytest.raises(SpatialDataJobRecoveryError):
        job_store(graph)


def test_worker_failure_replay_requires_exact_live_attempt(tmp_path: Path) -> None:
    """A terminal failure cannot be manufactured from an expired or missing worker fence."""
    from ksi_core.domains.external.delivery.jobs import SpatialDataJobRecoveryError

    graph = job_graph(tmp_path)
    store = job_store(graph)
    job = issue(store, graph)
    first = lease(store, graph, job)
    store._journal.close()  # noqa: SLF001
    path = tmp_path / "jobs.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    events.append(
        {
            "recordType": "spatial-data-job.state.v1",
            "jobId": job.job_id,
            "sequence": 3,
            "at": first.lease_until.isoformat(),
            "state": "FAILED",
            "reason": "SOURCE_BYTES_MISMATCH",
            "nextAvailableAt": None,
        }
    )
    path.write_text("".join(json.dumps(event) + "\n" for event in events))
    with pytest.raises(SpatialDataJobRecoveryError):
        job_store(graph)
