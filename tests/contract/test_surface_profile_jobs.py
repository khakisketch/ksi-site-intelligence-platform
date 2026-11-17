"""표면 단면 작업 — 동결 입력, lease/fence, 검증된 완료, 현재 권한 재확인, 재생.

합성 스냅샷과 실제 계산(합성 격자)만 쓴다. 이 시험은 상태 기계와 검증 경계의 증거이지
측량 정확도·고객 수락의 증거가 아니다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ksi_core.domains.external.delivery.surface_profile_jobs import (
    SurfaceProfileDomainError,
    SurfaceProfileJobRecoveryError,
    SurfaceProfileJobStore,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_event_contracts.surface_profile import SurfaceProfileResultV1
from ksi_event_contracts.surface_profile_job import SurfaceProfileLeaseRequestV1
from spatial_data_fixture import NOW
from surface_profile_job_fixture import (
    AREA,
    SITE,
    FakeAuthority,
    genuine_answer,
    issue_request,
    later,
    profile_policy,
    profile_runtime,
    receipt_for,
    requester,
    viewer,
    worker,
    write_raster,
)


class Lane:
    def __init__(self, tmp_path: Path, **policy: Any) -> None:
        self.tmp = tmp_path
        self.coordinator = ExternalAuthorityCurrentnessCoordinator()
        self.authority = FakeAuthority(coordinator=self.coordinator)
        self.policy = profile_policy(**policy)
        self.runtime = profile_runtime()
        self.raster = write_raster(tmp_path / "dsm.tif")
        self.store = self._open()

    def _open(self, **overrides: Any) -> SurfaceProfileJobStore:
        return SurfaceProfileJobStore(
            DurableJournal(self.tmp / "jobs.jsonl"),
            authority=overrides.get("authority", self.authority),
            policy=overrides.get("policy", self.policy),
            runtime=overrides.get("runtime", self.runtime),
            coordinator=self.coordinator,
        )

    def reopen(self, **overrides: Any) -> SurfaceProfileJobStore:
        self.store._journal.close()  # noqa: SLF001 - restart over the same journal
        self.store = self._open(**overrides)
        return self.store

    def issue(self, *, key: str = "k1", principal: Any = None, at: float = 0, **req: Any) -> Any:
        return self.store.issue(
            site_id=SITE,
            work_area_id=AREA,
            request=issue_request(**req),
            principal=principal or requester(),
            idempotency_key=key,
            now=NOW + later(at),
        )

    def lease(
        self, job_id: str, *, at: float = 1, acquisition: str = "a1", instance: str = "instance-1"
    ) -> Any:
        return self.store.lease(
            job_id=job_id,
            worker=worker(),
            request=SurfaceProfileLeaseRequestV1(
                worker_instance_id=instance, acquisition_id=acquisition
            ),
            now=NOW + later(at),
        )

    def running(self, *, at: float = 1) -> tuple[str, Any, Any]:
        job_id = self.issue().job_id
        attempt = self.lease(job_id, at=at)
        job = self.store.worker_input(
            job_id=job_id, worker=worker(), attempt=attempt, now=NOW + later(at)
        )
        return job_id, attempt, job

    def complete(
        self, job_id: str, attempt: Any, result: Any, receipt: Any, *, at: float = 2
    ) -> Any:
        return self.store.complete(
            job_id=job_id,
            worker=worker(),
            attempt=attempt,
            result=result,
            receipt=receipt,
            now=NOW + later(at),
        )

    def answer(self, job: Any, *, at: float = 2) -> tuple[Any, Any]:
        return genuine_answer(job, self.raster, NOW + later(at))


@pytest.fixture
def lane(tmp_path: Path) -> Lane:
    return Lane(tmp_path)


def _refusal(call: Any) -> SurfaceProfileDomainError:
    with pytest.raises(SurfaceProfileDomainError) as excinfo:
        call()
    return excinfo.value


# ── 발급: 무엇을 동결하고 무엇을 거부하는가 ────────────────────────────────────


def test_issue_freezes_the_saved_line_source_grant_and_read_window(lane: Lane) -> None:
    view = lane.issue()
    assert view.execution_state.value == "QUEUED" and view.availability.value == "NOT_READY"
    _, _, job = lane.running()
    assert job.job_digest == job.canonical_digest()
    assert job.profile_request.line == job.feature.line
    assert job.read_window is not None and job.read_window.cells > 0
    assert job.request.feature == job.feature.ref()
    assert (job.policy, job.runtime) == (lane.policy, lane.runtime)


def test_the_same_key_returns_the_same_job_and_never_a_second(lane: Lane) -> None:
    first, again = lane.issue(), lane.issue(at=3)
    assert again.job_id == first.job_id
    assert lane.authority.calls.count("admit") == 1  # 재시도는 새 판정을 쓰지 않는다
    assert lane.issue(key="other").job_id != first.job_id


def test_the_same_key_with_another_request_conflicts(lane: Lane) -> None:
    lane.issue()
    error = _refusal(lambda: lane.issue(sample_spacing_m=2.0))
    assert (error.reason, error.status_code) == ("IDEMPOTENCY_CONFLICT", 409)


def test_a_failed_admission_leaves_no_trace(lane: Lane) -> None:
    lane.authority.admit_error = "HEIGHT_NOT_ELIGIBLE"
    assert _refusal(lane.issue).reason == "HEIGHT_NOT_ELIGIBLE"
    journal = lane.tmp / "jobs.jsonl"
    assert not journal.exists() or journal.read_text() == ""
    lane.authority.admit_error = None
    assert lane.issue().execution_state.value == "QUEUED"


def test_only_a_human_requester_with_the_request_permission_may_issue(lane: Lane) -> None:
    assert _refusal(lambda: lane.issue(principal=viewer())).reason == "PERMISSION_DENIED"
    assert _refusal(lambda: lane.issue(principal=worker())).reason == "PERMISSION_DENIED"
    lane.authority.scope_error = True
    assert _refusal(lane.issue).reason == "NOT_FOUND"


@pytest.mark.parametrize("key", ["", "bad\nkey", "k" * 256])
def test_unusable_idempotency_keys_are_refused(lane: Lane, key: str) -> None:
    assert _refusal(lambda: lane.issue(key=key)).reason == "INVALID_REQUEST"


def test_organization_quota_is_enforced_atomically(lane: Lane) -> None:
    lane.issue(key="a"), lane.issue(key="b")
    error = _refusal(lambda: lane.issue(key="c"))
    assert (error.reason, error.status_code, error.retryable) == (
        "RESOURCE_LIMIT_EXCEEDED",
        429,
        True,
    )


def test_a_job_is_visible_only_to_its_requester(lane: Lane) -> None:
    job_id = lane.issue().job_id
    assert lane.store.get(job_id=job_id, principal=requester(), now=NOW).job_id == job_id
    for stranger in (requester("someone-else"), requester(org="org-other")):
        assert (
            _refusal(
                lambda who=stranger: lane.store.get(job_id=job_id, principal=who, now=NOW)
            ).reason
            == "NOT_FOUND"
        )
        assert (
            _refusal(
                lambda who=stranger: lane.store.result(job_id=job_id, principal=who, now=NOW)
            ).reason
            == "NOT_FOUND"
        )
    mine = lane.store.list(site_id=SITE, work_area_id=AREA, principal=requester(), limit=5, now=NOW)
    theirs = lane.store.list(
        site_id=SITE, work_area_id=AREA, principal=requester("someone-else"), limit=5, now=NOW
    )
    assert [v.job_id for v in mine] == [job_id] and theirs == ()


# ── lease / fence ───────────────────────────────────────────────────────────


def test_a_lease_is_idempotent_exclusive_and_fenced(lane: Lane) -> None:
    job_id = lane.issue().job_id
    first = lane.lease(job_id)
    assert lane.lease(job_id, acquisition="a1") == first  # 같은 획득의 재시도
    error = _refusal(lambda: lane.lease(job_id, acquisition="a2", instance="instance-2"))
    assert error.reason == "NOT_READY"
    assert first.fence == 1 and first.lease_until == NOW + later(1) + later(5)


def test_only_an_activated_worker_principal_may_lease(lane: Lane) -> None:
    job_id = lane.issue().job_id
    lane.authority.activated = False
    assert _refusal(lambda: lane.lease(job_id)).reason == "PERMISSION_DENIED"
    lane.authority.activated = True
    with pytest.raises(SurfaceProfileDomainError):
        lane.store.lease(
            job_id=job_id,
            worker=requester(),
            request=SurfaceProfileLeaseRequestV1(
                worker_instance_id="instance-1", acquisition_id="x"
            ),
            now=NOW + later(1),
        )


def test_renewal_extends_the_same_acquisition_but_never_past_the_deadline(lane: Lane) -> None:
    job_id, attempt, _ = lane.running()
    renewed = lane.store.renew(job_id=job_id, worker=worker(), attempt=attempt, now=NOW + later(4))
    assert renewed.fence_digest() == attempt.fence_digest()
    assert renewed.lease_until > attempt.lease_until
    stale = _refusal(
        lambda: lane.store.renew(
            job_id=job_id, worker=worker(), attempt=attempt, now=NOW + later(5)
        )
    )
    assert stale.reason == "FENCE_CONFLICT"  # 갱신 전 attempt 는 더 이상 현재가 아니다


def test_an_expired_lease_requeues_and_the_old_attempt_is_fenced_out(lane: Lane) -> None:
    job_id, first, job = lane.running()
    # 임대가 끝나면 백오프(1s) 동안은 다시 임대할 수 없다.
    assert (
        _refusal(lambda: lane.lease(job_id, at=7, acquisition="a2", instance="instance-2")).reason
        == "NOT_READY"
    )
    second = lane.lease(job_id, at=12, acquisition="a2", instance="instance-2")
    assert second.fence == 2 and second.attempt_number == 2
    result, receipt = lane.answer(job, at=13)
    assert _refusal(lambda: lane.complete(job_id, first, result, receipt, at=13)).reason == (
        "FENCE_CONFLICT"
    )
    assert lane.complete(job_id, second, result, receipt, at=13).execution_state.value == (
        "COMPLETED"
    )


def test_attempts_are_bounded_and_the_last_lost_lease_fails_the_job(lane: Lane) -> None:
    job_id = lane.issue().job_id
    lane.lease(job_id, at=1)
    # 일꾼의 polling 이 첫 임대의 만료를 알아채 대기열로 돌려보내고, 백오프(1s) 뒤에 다시 임대한다.
    assert [
        j.job_id for j in lane.store.pending(worker=worker(), limit=5, now=NOW + later(7))
    ] == []
    lane.lease(job_id, at=14, acquisition="a2", instance="instance-2")  # attempt 2 of 2
    view = lane.store.get(job_id=job_id, principal=requester(), now=NOW + later(25))
    assert (view.execution_state.value, view.reason) == ("FAILED", "LEASE_EXPIRED")


def test_the_deadline_ends_an_unfinished_job(lane: Lane) -> None:
    job_id = lane.issue().job_id
    view = lane.store.get(job_id=job_id, principal=requester(), now=NOW + later(61))
    assert (view.execution_state.value, view.reason) == ("EXPIRED", "DEADLINE_EXCEEDED")
    assert _refusal(lambda: lane.lease(job_id, at=62)).reason == "NOT_READY"


def test_cancel_stops_a_running_job_and_fences_the_worker(lane: Lane) -> None:
    job_id, attempt, job = lane.running()
    view = lane.store.cancel(job_id=job_id, principal=requester(), now=NOW + later(2))
    assert (view.execution_state.value, view.reason) == ("CANCELED", "CANCELED_BY_REQUESTER")
    result, receipt = lane.answer(job)
    assert _refusal(lambda: lane.complete(job_id, attempt, result, receipt)).reason == (
        "FENCE_CONFLICT"
    )
    assert (
        _refusal(
            lambda: lane.store.cancel(job_id=job_id, principal=requester("someone-else"), now=NOW)
        ).reason
        == "NOT_FOUND"
    )


# ── 완료: 일꾼의 답을 동결 입력과 대조한다 ──────────────────────────────────────


def test_a_genuine_answer_completes_and_the_numbers_need_a_fresh_read_proof(lane: Lane) -> None:
    job_id, attempt, job = lane.running()
    result, receipt = lane.answer(job)
    view = lane.complete(job_id, attempt, result, receipt)
    assert view.execution_state.value == "COMPLETED"
    assert view.availability.value == "AVAILABLE" and view.receipt == receipt
    assert "samples" not in json.dumps(view.model_dump(by_alias=True, mode="json"))

    released = lane.store.result(job_id=job_id, principal=requester(), now=NOW + later(3))
    assert released.result == result and released.job.job_id == job_id
    assert result.volume_computed is False and result.accuracy_assessed is False
    assert "reprove:READ" in lane.authority.calls


def test_a_retried_completion_is_acknowledged_only_if_identical(lane: Lane) -> None:
    job_id, attempt, job = lane.running()
    result, receipt = lane.answer(job)
    lane.complete(job_id, attempt, result, receipt)
    assert lane.complete(job_id, attempt, result, receipt, at=3).execution_state.value == (
        "COMPLETED"
    )
    other = receipt_for(job, result, NOW + later(2), limitations=("another text",))
    assert _refusal(lambda: lane.complete(job_id, attempt, result, other, at=3)).reason == (
        "REPORT_CONFLICT"
    )


def _tampered(result: SurfaceProfileResultV1, **changes: Any) -> SurfaceProfileResultV1:
    payload = result.model_dump(by_alias=True, mode="json")
    payload.update(changes)
    payload["resultDigest"] = None
    return SurfaceProfileResultV1.model_validate(payload).sealed()


def _edit_samples(
    result: SurfaceProfileResultV1, index: int, **cells: Any
) -> SurfaceProfileResultV1:
    samples = result.model_dump(by_alias=True, mode="json")["samples"]
    samples[index].update(cells)
    known = [s["elevationM"] for s in samples if s["elevationM"] is not None]
    return _tampered(
        result,
        samples=samples,
        validCount=len(known),
        unknownCount=len(samples) - len(known),
        minimumM=min(known) if known else None,
        maximumM=max(known) if known else None,
    )


def test_a_result_for_another_line_asset_or_plan_is_refused(lane: Lane) -> None:
    job_id, attempt, job = lane.running()
    result, _ = lane.answer(job)
    moved = _edit_samples(result, 3, x=result.samples[3].x + 1.0)
    other_asset = _tampered(result, assetRef="ksa-v1-" + "9" * 64)
    other_line = _tampered(result, lineDigest="sha256:" + "9" * 64, feature=None)
    dropped = result.model_dump(by_alias=True, mode="json")["samples"][:-1]
    kept = [row["elevationM"] for row in dropped if row["elevationM"] is not None]
    shorter = _tampered(
        result,
        samples=dropped,
        validCount=len(kept),
        unknownCount=len(dropped) - len(kept),
        minimumM=min(kept),
        maximumM=max(kept),
        lineLengthM=result.samples[-2].distance_m,
    )
    respaced = _tampered(result, sampleSpacingM=2.0)
    for bad in (moved, other_asset, other_line, shorter, respaced):
        receipt = receipt_for(job, bad, NOW + later(2))
        assert _refusal(lambda b=bad, r=receipt: lane.complete(job_id, attempt, b, r)).reason == (
            "INTEGRITY_MISMATCH"
        )
    assert (
        lane.store.get(
            job_id=job_id, principal=requester(), now=NOW + later(2)
        ).execution_state.value
        == "RUNNING"
    )


def test_a_number_where_geometry_says_outside_is_refused(tmp_path: Path) -> None:
    lane = Lane(tmp_path)
    # 선의 한쪽 끝이 격자 밖: 시작점이 (−3, 3) 셀이다.
    from surface_profile_job_fixture import feature_revision, line

    lane.authority.feature = feature_revision(line((-3.0, 3.0), (6.0, 3.0)))
    request = issue_request(feature=lane.authority.feature.ref())
    job_id = lane.store.issue(
        site_id=SITE,
        work_area_id=AREA,
        request=request,
        principal=requester(),
        idempotency_key="k",
        now=NOW,
    ).job_id
    attempt = lane.lease(job_id)
    job = lane.store.worker_input(
        job_id=job_id, worker=worker(), attempt=attempt, now=NOW + later(1)
    )
    result, receipt = lane.answer(job)
    outside = [i for i, s in enumerate(result.samples) if s.invalid_reason == "OUTSIDE_SURFACE"]
    assert outside, "the synthetic line must leave the grid"
    invented = _edit_samples(result, outside[0], elevationM=123.0, invalidReason=None)
    assert (
        _refusal(
            lambda: lane.complete(
                job_id, attempt, invented, receipt_for(job, invented, NOW + later(2))
            )
        ).reason
        == "INTEGRITY_MISMATCH"
    )
    # 반대로, 읽을 수 있는 표본을 "표면 밖"이라고 지워도 거부한다.
    readable = next(i for i, s in enumerate(result.samples) if s.elevation_m is not None)
    erased = _edit_samples(result, readable, elevationM=None, invalidReason="OUTSIDE_SURFACE")
    assert (
        _refusal(
            lambda: lane.complete(job_id, attempt, erased, receipt_for(job, erased, NOW + later(2)))
        ).reason
        == "INTEGRITY_MISMATCH"
    )
    assert lane.complete(job_id, attempt, result, receipt).execution_state.value == "COMPLETED"


@pytest.mark.parametrize(
    "change",
    [
        dict(job_digest="sha256:" + "1" * 64),
        dict(source_digest="sha256:" + "1" * 64),
        dict(request_digest="sha256:" + "1" * 64),
        dict(grant_digest="sha256:" + "1" * 64),
        dict(data_policy_digest="sha256:" + "1" * 64),
        dict(policy_digest="sha256:" + "1" * 64),
        dict(runtime_digest="sha256:" + "1" * 64),
        dict(artifact_id="another-artifact"),
        dict(source_sha256="sha256:" + "1" * 64),
        dict(source_size_bytes=1),
        dict(observed_crs_identifier="EPSG:5185"),
        dict(observed_crs_digest="sha256:" + "1" * 64),
        dict(window_cells_read=10**6),
        dict(read_window=None),
        dict(accuracy_assessed=True),
        dict(prepared_at=NOW + later(500)),
        dict(prepared_at=NOW),
    ],
)
def test_a_receipt_that_does_not_attest_this_job_is_refused(
    lane: Lane, change: dict[str, Any]
) -> None:
    job_id, attempt, job = lane.running()
    result, _ = lane.answer(job)
    bad = receipt_for(job, result, NOW + later(2), **change)
    error = _refusal(lambda: lane.complete(job_id, attempt, result, bad))
    assert error.reason in {"INTEGRITY_MISMATCH", "INVALID_REQUEST"} or error.status_code == 409


def test_a_wider_read_window_or_oversize_result_is_refused(tmp_path: Path) -> None:
    lane = Lane(tmp_path, max_result_bytes=2000)
    job_id, attempt, job = lane.running()
    result, receipt = lane.answer(job)
    error = _refusal(lambda: lane.complete(job_id, attempt, result, receipt))
    assert (error.reason, error.status_code) == ("RESOURCE_LIMIT_EXCEEDED", 413)


# ── 현재 권한은 매번 다시 증명한다 ───────────────────────────────────────────────


def test_a_revoked_grant_stops_the_worker_at_every_step(lane: Lane) -> None:
    job_id, attempt, job = lane.running()
    result, receipt = lane.answer(job)
    lane.authority.deny["PREPARE"] = "ACCESS_REVOKED"
    for call in (
        lambda: lane.store.renew(
            job_id=job_id, worker=worker(), attempt=attempt, now=NOW + later(4)
        ),
        lambda: lane.store.worker_input(
            job_id=job_id, worker=worker(), attempt=attempt, now=NOW + later(2)
        ),
        lambda: lane.complete(job_id, attempt, result, receipt),
    ):
        assert _refusal(call).reason == "ACCESS_REVOKED"


def test_a_revoked_read_hides_the_numbers_but_not_the_receipt(lane: Lane) -> None:
    job_id, attempt, job = lane.running()
    result, receipt = lane.answer(job)
    lane.complete(job_id, attempt, result, receipt)
    lane.authority.deny["READ"] = "ACCESS_REVOKED"

    view = lane.store.get(job_id=job_id, principal=requester(), now=NOW + later(3))
    assert (view.availability.value, view.reason) == ("ACCESS_REVOKED", "ACCESS_REVOKED")
    assert (
        _refusal(
            lambda: lane.store.result(job_id=job_id, principal=requester(), now=NOW + later(3))
        ).reason
        == "ACCESS_REVOKED"
    )
    lane.authority.deny.clear()
    assert (
        lane.store.result(job_id=job_id, principal=requester(), now=NOW + later(4)).result == result
    )


def test_a_result_expires_with_retention(lane: Lane) -> None:
    job_id, attempt, job = lane.running()
    result, receipt = lane.answer(job)
    lane.complete(job_id, attempt, result, receipt)
    late = NOW + later(2 + 3600)
    view = lane.store.get(job_id=job_id, principal=requester(), now=late)
    assert view.availability.value == "RETENTION_EXPIRED"
    assert _refusal(
        lambda: lane.store.result(job_id=job_id, principal=requester(), now=late)
    ).reason == ("RETENTION_EXPIRED")


def test_the_numbers_are_not_available_before_completion(lane: Lane) -> None:
    job_id = lane.issue().job_id
    assert (
        _refusal(lambda: lane.store.result(job_id=job_id, principal=requester(), now=NOW)).reason
        == "NOT_READY"
    )


# ── 실패 ────────────────────────────────────────────────────────────────────


def test_a_calculation_refusal_is_final_and_a_storage_failure_is_retried(lane: Lane) -> None:
    job_id, attempt, _ = lane.running()
    failed = lane.store.fail(
        job_id=job_id,
        worker=worker(),
        attempt=attempt,
        reason="WINDOW_TOO_LARGE",
        now=NOW + later(2),
    )
    assert (failed.execution_state.value, failed.reason) == ("FAILED", "WINDOW_TOO_LARGE")

    (lane.tmp / "b").mkdir()
    other = Lane(lane.tmp / "b")
    job_id, attempt, _ = other.running()
    requeued = other.store.fail(
        job_id=job_id,
        worker=worker(),
        attempt=attempt,
        reason="STORAGE_UNAVAILABLE",
        now=NOW + later(2),
    )
    assert requeued.execution_state.value == "QUEUED"
    assert _refusal(lambda: other.lease(job_id, at=2.5, acquisition="a2")).reason == "NOT_READY"
    attempt2 = other.lease(job_id, at=4, acquisition="a2", instance="instance-2")
    final = other.store.fail(
        job_id=job_id,
        worker=worker(),
        attempt=attempt2,
        reason="STORAGE_UNAVAILABLE",
        now=NOW + later(5),
    )
    assert final.execution_state.value == "FAILED"  # 시도가 소진됐다


def test_an_unknown_failure_reason_is_refused(lane: Lane) -> None:
    job_id, attempt, _ = lane.running()
    with pytest.raises(ValueError):
        lane.store.fail(
            job_id=job_id,
            worker=worker(),
            attempt=attempt,
            reason="/etc/passwd",
            now=NOW + later(2),
        )


# ── 재시작과 원장 ────────────────────────────────────────────────────────────


def test_restart_replays_every_state_and_keeps_idempotency(lane: Lane) -> None:
    job_id, attempt, job = lane.running()
    result, receipt = lane.answer(job)
    lane.complete(job_id, attempt, result, receipt)
    store = lane.reopen()

    view = store.get(job_id=job_id, principal=requester(), now=NOW + later(3))
    assert view.execution_state.value == "COMPLETED" and view.receipt == receipt
    assert store.result(job_id=job_id, principal=requester(), now=NOW + later(3)).result == result
    assert lane.issue(at=3).job_id == job_id  # 같은 키는 같은 작업으로 수렴


def test_the_raw_idempotency_key_is_never_journaled(lane: Lane) -> None:
    lane.issue(key="secret-client-key-12345")
    assert "secret-client-key-12345" not in (lane.tmp / "jobs.jsonl").read_text()


def _records(lane: Lane) -> list[dict[str, Any]]:
    text = (lane.tmp / "jobs.jsonl").read_text(encoding="utf-8")
    return [json.loads(row) for row in text.splitlines() if row]


def _rewrite(lane: Lane, records: list[dict[str, Any]]) -> None:
    lane.store._journal.close()  # noqa: SLF001
    (lane.tmp / "jobs.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8"
    )


def test_replay_refuses_a_job_whose_frozen_content_was_edited(lane: Lane) -> None:
    lane.issue()
    records = _records(lane)
    records[0]["job"]["featureRevision"] = 0
    records[0]["job"]["profileRequest"]["sampleSpacingM"] = 9.0
    _rewrite(lane, records)
    with pytest.raises(SurfaceProfileJobRecoveryError):
        lane._open()  # noqa: SLF001


def test_replay_refuses_a_skipped_or_forged_event(lane: Lane) -> None:
    job_id, attempt, job = lane.running()
    lane.store.renew(job_id=job_id, worker=worker(), attempt=attempt, now=NOW + later(4))
    records = _records(lane)
    assert len(records) == 3
    _rewrite(lane, [records[0], records[2]])  # 임대 이벤트(seq 2) 없이 갱신/상태만
    with pytest.raises(SurfaceProfileJobRecoveryError):
        lane._open()  # noqa: SLF001


def test_replay_refuses_history_frozen_under_another_policy(lane: Lane) -> None:
    lane.issue()
    lane.store._journal.close()  # noqa: SLF001
    with pytest.raises(SurfaceProfileJobRecoveryError):
        lane._open(policy=profile_policy(max_attempts=1))  # noqa: SLF001


def test_a_completed_event_cannot_be_forged_from_a_queued_job(lane: Lane) -> None:
    job_id, attempt, job = lane.running()
    result, receipt = lane.answer(job)
    lane.complete(job_id, attempt, result, receipt)
    records = _records(lane)
    # 임대·갱신 이벤트를 지우고 완료만 남긴 위조 원장
    forged = [r for r in records if not r["recordType"].endswith("leased.v1")]
    _rewrite(lane, forged)
    with pytest.raises(SurfaceProfileJobRecoveryError):
        lane._open()  # noqa: SLF001


def test_a_sealed_journal_refuses_new_work_instead_of_pretending(lane: Lane) -> None:
    lane.store._journal.close()  # noqa: SLF001
    assert _refusal(lane.issue).reason == "CURRENTNESS_UNAVAILABLE"
    assert isinstance(datetime.now(), datetime) and timedelta(0) == later(0)


def test_a_result_that_read_more_than_the_frozen_window_is_refused(lane: Lane) -> None:
    job_id, attempt, job = lane.running()
    result, _ = lane.answer(job)
    greedy = _tampered(result, windowCellsRead=job.read_window.cells + 1)
    receipt = receipt_for(job, greedy, NOW + later(2))
    assert _refusal(lambda: lane.complete(job_id, attempt, greedy, receipt)).reason == (
        "INTEGRITY_MISMATCH"
    )
    assert (
        lane.store.get(
            job_id=job_id, principal=requester(), now=NOW + later(2)
        ).execution_state.value
        == "RUNNING"
    )
