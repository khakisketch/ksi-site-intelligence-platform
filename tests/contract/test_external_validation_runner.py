"""Fair external-only queue scheduling and bounded acquisition retry."""

import threading

import pytest
from ksi_processing_controller.external_validation_runner import (
    ExternalLane,
    ExternalLaneUnavailable,
    ExternalValidationRunner,
    ExternalWorkLease,
    RunnerPolicy,
    TurnOutcome,
)
from test_external_artifact_inspection_worker import _fence


class Lane:
    def __init__(self, name, calls):
        self.lane = name
        self.calls = calls
        self.claim_ids = []
        self.fail_claim_once = False
        self.fail_poll = False
        self.empty = False
        self.closed = 0
        self.stop_on_claim = None

    def poll(self, *, deadline_monotonic):
        self.calls.append((self.lane, "poll"))
        if self.fail_poll:
            raise ExternalLaneUnavailable("poll unavailable")
        return None if self.empty else self.lane.value + "-request"

    def claim(self, request_id, acquisition_id, *, deadline_monotonic):
        self.calls.append((self.lane, "claim"))
        self.claim_ids.append(acquisition_id)
        if self.fail_claim_once:
            self.fail_claim_once = False
            raise ExternalLaneUnavailable("uncertain claim")
        if self.stop_on_claim:
            self.stop_on_claim()
        return ExternalWorkLease(
            request_id=request_id,
            fence=_fence().model_copy(update={"lease_acquisition_id": acquisition_id}),
        )

    def execute(self, lease, *, deadline_monotonic, stop):
        assert not stop.is_set()
        self.calls.append((self.lane, "execute"))
        return TurnOutcome.COMPLETED

    def release(self, lease):
        self.calls.append((self.lane, "release"))

    def close(self):
        self.closed += 1


def fixture_runner(**kwargs):
    calls = []
    lanes = tuple(Lane(name, calls) for name in ExternalLane)
    runner = ExternalValidationRunner(
        lanes=lanes,
        policy=RunnerPolicy(turn_budget_seconds=3, claim_retry_seconds=2, idle_backoff_seconds=0.1),
        **kwargs,
    )
    return runner, lanes, calls


def test_hot_inspection_queue_cannot_starve_evidence_or_volume():
    runner, lanes, calls = fixture_runner()
    try:
        assert [runner.run_once() for _ in range(6)] == [TurnOutcome.COMPLETED] * 6
        assert [lane for lane, action in calls if action == "execute"] == list(ExternalLane) * 2
    finally:
        runner.close()
    assert [lane.closed for lane in lanes] == [1, 1, 1]


def test_uncertain_claim_retries_same_identity_without_blocking_other_lanes():
    runner, lanes, calls = fixture_runner()
    lanes[0].fail_claim_once = True
    try:
        assert runner.run_once() is TurnOutcome.RETRY_PENDING
        assert runner.run_once() is TurnOutcome.COMPLETED
        assert runner.run_once() is TurnOutcome.COMPLETED
        assert runner.run_once() is TurnOutcome.COMPLETED
        assert len(lanes[0].claim_ids) == 2
        assert lanes[0].claim_ids[0] == lanes[0].claim_ids[1]
        assert sum(action == "poll" and lane == lanes[0].lane for lane, action in calls) == 1
    finally:
        runner.close()


def test_expired_uncertain_acquisition_is_not_reissued_with_a_new_identity():
    clock = [10.0]
    runner, lanes, calls = fixture_runner(monotonic=lambda: clock[0])
    lanes[0].fail_claim_once = True
    try:
        assert runner.run_once() is TurnOutcome.RETRY_PENDING
        runner.run_once()
        runner.run_once()
        clock[0] += 3
        assert runner.run_once() is TurnOutcome.DEFERRED
        assert len(lanes[0].claim_ids) == 1
    finally:
        runner.close()


def test_stop_after_claim_releases_without_execution_and_closes_once():
    runner, lanes, calls = fixture_runner()
    lanes[0].stop_on_claim = runner.request_stop
    assert runner.run_once() is TurnOutcome.STOPPED
    assert not any(action == "execute" for _, action in calls)
    assert (lanes[0].lane, "release") in calls
    runner.close()
    runner.close()
    assert [lane.closed for lane in lanes] == [1, 1, 1]
    assert runner.run_once() is TurnOutcome.STOPPED


def test_idle_wait_is_interruptible_and_duplicate_lanes_are_rejected():
    runner, lanes, calls = fixture_runner()
    for lane in lanes:
        lane.empty = True
    thread = threading.Thread(target=runner.run_forever)
    thread.start()
    runner.request_stop()
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert all(lane.closed == 1 for lane in lanes)
    with pytest.raises(ValueError, match="each external lane"):
        ExternalValidationRunner(
            lanes=(lanes[0], lanes[0], lanes[2]),
            policy=RunnerPolicy(
                turn_budget_seconds=1, claim_retry_seconds=1, idle_backoff_seconds=0.1
            ),
        )


def test_close_during_active_execution_cancels_then_closes_every_lane_once():
    runner, lanes, calls = fixture_runner()
    entered = threading.Event()
    results = []

    def execute(lease, *, deadline_monotonic, stop):
        entered.set()
        assert stop.wait(1)
        return TurnOutcome.STOPPED

    lanes[0].execute = execute
    thread = threading.Thread(target=lambda: results.append(runner.run_once()))
    thread.start()
    assert entered.wait(1)
    runner.close()
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert results == [TurnOutcome.STOPPED]
    assert (lanes[0].lane, "release") in calls
    assert [lane.closed for lane in lanes] == [1, 1, 1]


def test_cleanup_failure_does_not_replace_primary_execution_failure():
    runner, lanes, calls = fixture_runner()

    def execute(*args, **kwargs):
        raise ValueError("primary execution failure")

    def release(*args):
        raise RuntimeError("secondary cleanup failure")

    lanes[0].execute = execute
    lanes[0].release = release
    try:
        with pytest.raises(ValueError, match="primary execution failure"):
            runner.run_once()
    finally:
        runner.close()


def test_base_exception_during_one_lane_close_still_closes_every_owned_lane_once():
    runner, lanes, _calls = fixture_runner()

    def interrupt() -> None:
        raise KeyboardInterrupt

    lanes[0].close = interrupt

    with pytest.raises(KeyboardInterrupt):
        runner.close()

    assert lanes[1].closed == 1
    assert lanes[2].closed == 1
    assert runner.run_once() is TurnOutcome.STOPPED


class _RecordingStop:
    def __init__(self) -> None:
        self.stopped = False
        self.waits: list[float] = []

    def is_set(self) -> bool:
        return self.stopped

    def set(self) -> None:
        self.stopped = True

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        self.stopped = True
        return True


def test_forever_uses_explicit_bounded_failure_backoff_separately_from_idle_backoff():
    runner, lanes, _calls = fixture_runner()
    idle_stop = _RecordingStop()
    for lane in lanes:
        lane.empty = True
    runner._stop = idle_stop
    runner.run_forever()
    assert idle_stop.waits == [0.1]

    runner, lanes, _calls = fixture_runner()
    failure_stop = _RecordingStop()
    for lane in lanes:
        lane.fail_poll = True
    runner._stop = failure_stop
    runner.run_forever()
    assert failure_stop.waits == [0.2]
