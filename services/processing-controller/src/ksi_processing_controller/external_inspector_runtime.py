"""Pure fixed-runtime resource accounting; host controller evidence is injected later."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol

_RUNTIME_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")


class RuntimeControlUnavailable(RuntimeError):
    """No proven controller/counter fact exists for the requested fixed runtime."""


class CpuAccountingError(RuntimeError):
    """A controller counter ceased to be a monotonic aggregate process-tree fact."""


class CpuCounterUnitV1(StrEnum):
    CPU_USEC = "CPU_USEC"


class RuntimeControlDispositionV1(StrEnum):
    COMPLETED = "COMPLETED"
    CPU_LIMIT_EXCEEDED = "CPU_LIMIT_EXCEEDED"


class AggregateCpuCounterPort(Protocol):
    """A real adapter must report the complete process tree in one proven unit."""

    def read_aggregate_cpu(self) -> AggregateCpuCounterV1: ...


class ExactRuntimeTerminatorPort(Protocol):
    """Terminate only the one runtime ID already bound into the local attempt."""

    def terminate_exact(self, runtime_id: str) -> float: ...


@dataclass(frozen=True, slots=True)
class AggregateCpuCounterV1:
    value: int
    unit: CpuCounterUnitV1
    complete_process_tree: bool

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 0:
            raise RuntimeControlUnavailable("aggregate CPU counter must be non-negative integer")
        if self.unit is not CpuCounterUnitV1.CPU_USEC:
            raise RuntimeControlUnavailable("aggregate CPU counter unit is unknown")
        if not self.complete_process_tree:
            raise RuntimeControlUnavailable(
                "aggregate CPU counter must include the complete process tree"
            )


@dataclass(frozen=True, slots=True)
class CpuObservationV1:
    baseline: int
    current: int
    consumed: int
    budget: int
    exceeded: bool


@dataclass(frozen=True, slots=True)
class CpuFinalUsageV1:
    baseline: int
    final: int
    consumed: int
    budget: int
    within_budget: bool


@dataclass(frozen=True, slots=True)
class RuntimeCpuMonitorV1:
    baseline_counter: int
    current_counter: int
    consumed: int
    budget_counter: int
    exceeded: bool
    kill_latency_seconds: float | None


@dataclass(frozen=True, slots=True)
class FixedRuntimeMeasurementV1:
    """One controller-backed result; no tolerance or host-acceptance claim is inferred."""

    runtime_id: str
    counter_unit: CpuCounterUnitV1
    baseline_counter: int
    final_counter: int
    consumed_counter: int
    budget_counter: int
    threshold_exceeded: bool
    disposition: RuntimeControlDispositionV1
    kill_latency_seconds: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.runtime_id, str) or _RUNTIME_ID.fullmatch(self.runtime_id) is None:
            raise RuntimeControlUnavailable("runtime ID is unavailable")
        if self.counter_unit is not CpuCounterUnitV1.CPU_USEC:
            raise RuntimeControlUnavailable("runtime CPU unit is unavailable")
        for value in (
            self.baseline_counter,
            self.final_counter,
            self.consumed_counter,
            self.budget_counter,
        ):
            if type(value) is not int or value < 0:
                raise RuntimeControlUnavailable("runtime CPU facts must be non-negative integers")
        if self.final_counter < self.baseline_counter:
            raise CpuAccountingError("runtime CPU final counter rolled back below its baseline")
        if self.consumed_counter != self.final_counter - self.baseline_counter:
            raise CpuAccountingError("runtime CPU consumption does not use its recorded baseline")
        if self.budget_counter <= 0 or self.threshold_exceeded != (
            self.consumed_counter > self.budget_counter
        ):
            raise RuntimeControlUnavailable("runtime CPU threshold fact is inconsistent")
        if self.threshold_exceeded != (
            self.disposition is RuntimeControlDispositionV1.CPU_LIMIT_EXCEEDED
        ):
            raise RuntimeControlUnavailable("runtime CPU disposition is inconsistent")
        if self.kill_latency_seconds is not None and (
            type(self.kill_latency_seconds) is not float
            or not math.isfinite(self.kill_latency_seconds)
            or self.kill_latency_seconds < 0.0
        ):
            raise RuntimeControlUnavailable("runtime kill latency is unavailable")
        if self.threshold_exceeded and self.kill_latency_seconds is None:
            raise RuntimeControlUnavailable("runtime CPU termination lacks measured kill latency")


def cpu_seconds_to_counter_budget(seconds: float, unit: CpuCounterUnitV1) -> int:
    """Convert policy seconds only where one exact integer counter threshold exists."""
    if type(seconds) is not float or not math.isfinite(seconds) or seconds <= 0.0:
        raise RuntimeControlUnavailable("CPU budget must be a positive finite value")
    if unit is not CpuCounterUnitV1.CPU_USEC:
        raise RuntimeControlUnavailable("CPU counter unit is unavailable")
    try:
        converted = Decimal(str(seconds)) * Decimal(1_000_000)
    except (InvalidOperation, ValueError) as exc:
        raise RuntimeControlUnavailable("CPU budget conversion is unavailable") from exc
    if converted != converted.to_integral_value():
        raise RuntimeControlUnavailable("CPU budget cannot form an exact integer counter threshold")
    result = int(converted)
    if result <= 0:
        raise RuntimeControlUnavailable("CPU budget must form a positive counter threshold")
    return result


class CpuAccountingSession:
    """One controller baseline used unchanged by monitor and post-exit final accounting."""

    def __init__(self, baseline: AggregateCpuCounterV1, budget: int) -> None:
        if type(budget) is not int or budget <= 0:
            raise RuntimeControlUnavailable("CPU counter budget must be a positive integer")
        self._baseline = baseline
        self._budget = budget

    @classmethod
    def start(cls, baseline: AggregateCpuCounterV1, *, budget: int) -> CpuAccountingSession:
        return cls(baseline, budget)

    def monitor(self, current: AggregateCpuCounterV1) -> CpuObservationV1:
        consumed = self._consumed(current)
        return CpuObservationV1(
            baseline=self._baseline.value,
            current=current.value,
            consumed=consumed,
            budget=self._budget,
            exceeded=consumed > self._budget,
        )

    def final(self, current: AggregateCpuCounterV1) -> CpuFinalUsageV1:
        consumed = self._consumed(current)
        return CpuFinalUsageV1(
            baseline=self._baseline.value,
            final=current.value,
            consumed=consumed,
            budget=self._budget,
            within_budget=consumed <= self._budget,
        )

    def _consumed(self, current: AggregateCpuCounterV1) -> int:
        if current.unit is not self._baseline.unit:
            raise RuntimeControlUnavailable("CPU counter unit changed during an attempt")
        if current.value < self._baseline.value:
            raise CpuAccountingError("aggregate CPU counter rolled back below its baseline")
        return current.value - self._baseline.value


class FixedRuntimeControlSession:
    """Controller-facing accounting seam; host cgroup implementation remains injected."""

    def __init__(
        self,
        *,
        runtime_id: str,
        accounting: CpuAccountingSession,
        counter: AggregateCpuCounterPort,
        terminator: ExactRuntimeTerminatorPort,
    ) -> None:
        if not isinstance(runtime_id, str) or _RUNTIME_ID.fullmatch(runtime_id) is None:
            raise RuntimeControlUnavailable("runtime ID is unavailable")
        self._runtime_id = runtime_id
        self._accounting = accounting
        self._counter = counter
        self._terminator = terminator
        self._kill_latency_seconds: float | None = None

    @classmethod
    def start(
        cls,
        *,
        runtime_id: str,
        counter: AggregateCpuCounterPort,
        terminator: ExactRuntimeTerminatorPort,
        budget: int,
    ) -> FixedRuntimeControlSession:
        return cls(
            runtime_id=runtime_id,
            accounting=CpuAccountingSession.start(counter.read_aggregate_cpu(), budget=budget),
            counter=counter,
            terminator=terminator,
        )

    def monitor(self) -> RuntimeCpuMonitorV1:
        observation = self._accounting.monitor(self._counter.read_aggregate_cpu())
        if observation.exceeded and self._kill_latency_seconds is None:
            latency = self._terminator.terminate_exact(self._runtime_id)
            if type(latency) is not float or not math.isfinite(latency) or latency < 0.0:
                raise RuntimeControlUnavailable("runtime terminator did not measure kill latency")
            self._kill_latency_seconds = latency
        return RuntimeCpuMonitorV1(
            baseline_counter=observation.baseline,
            current_counter=observation.current,
            consumed=observation.consumed,
            budget_counter=observation.budget,
            exceeded=observation.exceeded,
            kill_latency_seconds=self._kill_latency_seconds,
        )

    def final(self, disposition: RuntimeControlDispositionV1) -> FixedRuntimeMeasurementV1:
        usage = self._accounting.final(self._counter.read_aggregate_cpu())
        return FixedRuntimeMeasurementV1(
            runtime_id=self._runtime_id,
            counter_unit=CpuCounterUnitV1.CPU_USEC,
            baseline_counter=usage.baseline,
            final_counter=usage.final,
            consumed_counter=usage.consumed,
            budget_counter=usage.budget,
            threshold_exceeded=not usage.within_budget,
            disposition=disposition,
            kill_latency_seconds=self._kill_latency_seconds,
        )


__all__ = [
    "AggregateCpuCounterV1",
    "AggregateCpuCounterPort",
    "CpuAccountingError",
    "CpuAccountingSession",
    "CpuCounterUnitV1",
    "CpuFinalUsageV1",
    "CpuObservationV1",
    "RuntimeControlUnavailable",
    "ExactRuntimeTerminatorPort",
    "FixedRuntimeControlSession",
    "FixedRuntimeMeasurementV1",
    "RuntimeControlDispositionV1",
    "RuntimeCpuMonitorV1",
    "cpu_seconds_to_counter_budget",
]
