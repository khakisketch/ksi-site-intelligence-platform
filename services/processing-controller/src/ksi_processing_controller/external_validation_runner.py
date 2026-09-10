"""Bounded, fair scheduling for three independently fenced external worker lanes.

Lane adapters own Core transport, launch, adjudication and byte cleanup. This
scheduler neither interprets measurements nor manufactures terminal receipts.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from threading import Event, Lock
from time import monotonic
from typing import Protocol
from uuid import uuid4

from ksi_processing_controller.external_inspector_protocol import LocalLeaseFenceV1


@contextmanager
def _cleanup_on_exit(cleanup: Callable[[], None]) -> Iterator[None]:
    try:
        yield
    except BaseException:
        # Cleanup must run without hiding the original execution/cancellation.
        with suppress(BaseException):
            cleanup()
        raise
    else:
        cleanup()


class ExternalLane(StrEnum):
    INSPECTION = "inspection"
    CHECKPOINT = "checkpoint"
    RELATIVE_VOLUME = "relative-volume"


class TurnOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    IDLE = "IDLE"
    DEFERRED = "DEFERRED"
    RETRY_PENDING = "RETRY_PENDING"
    STOPPED = "STOPPED"


class ExternalLaneUnavailable(RuntimeError):
    """A bounded transport/availability failure; never a rejected measurement."""


@dataclass(frozen=True, slots=True)
class ExternalWorkLease:
    request_id: str
    fence: LocalLeaseFenceV1


class ExternalLanePort(Protocol):
    lane: ExternalLane

    def poll(self, *, deadline_monotonic: float) -> str | None: ...

    def claim(
        self, request_id: str, acquisition_id: str, *, deadline_monotonic: float
    ) -> ExternalWorkLease | None: ...

    def execute(
        self, lease: ExternalWorkLease, *, deadline_monotonic: float, stop: Event
    ) -> TurnOutcome: ...

    def release(self, lease: ExternalWorkLease) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RunnerPolicy:
    turn_budget_seconds: float
    claim_retry_seconds: float
    idle_backoff_seconds: float
    failure_backoff_seconds: float = 0.2

    def __post_init__(self) -> None:
        for value in (
            self.turn_budget_seconds,
            self.claim_retry_seconds,
            self.idle_backoff_seconds,
            self.failure_backoff_seconds,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value <= 0
            ):
                raise ValueError("runner budgets must be finite positive seconds")


@dataclass(frozen=True, slots=True)
class _PendingClaim:
    request_id: str
    acquisition_id: str
    expires_at: float


class ExternalValidationRunner:
    def __init__(
        self,
        *,
        lanes: tuple[ExternalLanePort, ...],
        policy: RunnerPolicy,
        monotonic: Callable[[], float] = monotonic,
    ) -> None:
        if len(lanes) != len(ExternalLane) or {lane.lane for lane in lanes} != set(ExternalLane):
            raise ValueError("runner requires exactly one adapter for each external lane")
        self._lanes = tuple(sorted(lanes, key=lambda lane: list(ExternalLane).index(lane.lane)))
        self._policy = policy
        self._monotonic = monotonic
        self._stop = Event()
        self._lock = Lock()
        self._active = False
        self._closed = False
        self._next = 0
        self._pending: dict[ExternalLane, _PendingClaim] = {}

    def request_stop(self) -> None:
        self._stop.set()

    def _now(self) -> float:
        now = self._monotonic()
        if isinstance(now, bool) or not isfinite(now):
            raise ValueError("runner monotonic clock is invalid")
        return now

    def run_once(self) -> TurnOutcome:
        with self._lock:
            if self._closed or self._stop.is_set():
                return TurnOutcome.STOPPED
            if self._active:
                raise RuntimeError("external runner already has an active turn")
            self._active = True
            lane = self._lanes[self._next]
            self._next = (self._next + 1) % len(self._lanes)
        with _cleanup_on_exit(self._finish_turn):
            return self._turn(lane)

    def _finish_turn(self) -> None:
        with self._lock:
            self._active = False
        if self._stop.is_set():
            self.close()

    def _turn(self, lane: ExternalLanePort) -> TurnOutcome:
        now = self._now()
        deadline = now + self._policy.turn_budget_seconds
        pending = self._pending.get(lane.lane)
        if pending is not None and now >= pending.expires_at:
            self._pending.pop(lane.lane, None)
            # Core owns any uncertain lease. Do not immediately change its ID.
            return TurnOutcome.DEFERRED
        if pending is None:
            try:
                request_id = lane.poll(deadline_monotonic=deadline)
            except ExternalLaneUnavailable:
                return TurnOutcome.DEFERRED
            if self._stop.is_set():
                return TurnOutcome.STOPPED
            if self._now() >= deadline:
                return TurnOutcome.DEFERRED
            if request_id is None:
                return TurnOutcome.IDLE
            if not isinstance(request_id, str) or not request_id or len(request_id) > 255:
                raise ValueError("external lane returned an invalid request identity")
            pending = _PendingClaim(
                request_id, str(uuid4()), self._now() + self._policy.claim_retry_seconds
            )
            self._pending[lane.lane] = pending
        if self._stop.is_set():
            return TurnOutcome.STOPPED
        try:
            lease = lane.claim(
                pending.request_id,
                pending.acquisition_id,
                deadline_monotonic=min(deadline, pending.expires_at),
            )
        except ExternalLaneUnavailable:
            return TurnOutcome.RETRY_PENDING
        self._pending.pop(lane.lane, None)
        if lease is None:
            return TurnOutcome.DEFERRED
        with _cleanup_on_exit(lambda: lane.release(lease)):
            # An adapter cannot substitute another request or Core acquisition.
            fence = LocalLeaseFenceV1.model_validate(lease.fence.__dict__)
            if (
                lease.request_id != pending.request_id
                or fence.lease_acquisition_id != pending.acquisition_id
            ):
                raise ValueError("external lane substituted its claimed lease")
            if self._stop.is_set():
                return TurnOutcome.STOPPED
            if self._now() >= deadline:
                return TurnOutcome.DEFERRED
            try:
                outcome = lane.execute(lease, deadline_monotonic=deadline, stop=self._stop)
            except ExternalLaneUnavailable:
                return TurnOutcome.DEFERRED
            if outcome not in (TurnOutcome.COMPLETED, TurnOutcome.DEFERRED, TurnOutcome.STOPPED):
                raise ValueError("external lane returned an invalid execution outcome")
            return outcome

    def run_forever(self) -> None:
        with _cleanup_on_exit(self.close):
            while not self._stop.is_set():
                progressed = False
                all_idle = True
                for _ in self._lanes:
                    if self._stop.is_set():
                        break
                    outcome = self.run_once()
                    progressed |= outcome is TurnOutcome.COMPLETED
                    all_idle &= outcome is TurnOutcome.IDLE
                if not progressed:
                    self._stop.wait(
                        self._policy.idle_backoff_seconds
                        if all_idle
                        else self._policy.failure_backoff_seconds
                    )

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            if self._closed or self._active:
                return
            self._closed = True
            self._pending.clear()
        first_error: BaseException | None = None
        for lane in self._lanes:
            try:
                lane.close()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error
