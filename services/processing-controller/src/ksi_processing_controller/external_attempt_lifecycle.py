"""Exact owned-runtime cleanup and ambiguous-create reconciliation shared by V1/V2.

This module knows only durable ownership facts and exact runtime ports. It never
parses input, constructs a Docker payload, or selects an operation protocol.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol

from ksi_processing_controller.external_inspector_attempts import RuntimeParentReceiptV1
from ksi_processing_controller.external_runtime_binding import ExactRuntimeBindingPort


class InspectorSandboxUnavailable(RuntimeError):
    """Exact runtime ownership, admission, or cleanup could not be established."""


class AttemptLifecycleJournalPort(Protocol):
    def runtime_parent_bound(self, attempt_nonce: str, receipt: RuntimeParentReceiptV1) -> None: ...
    def container_bound(self, attempt_nonce: str, runtime_id: str) -> None: ...
    def cleanup_required(self, attempt_nonce: str, *, disposition: str) -> None: ...
    def cleanup_failed(self, attempt_nonce: str, *, reason: str) -> None: ...
    def cleaned(self, attempt_nonce: str) -> None: ...


class AttemptLifecycleParentPort[BindingT: ExactRuntimeBindingPort](Protocol):
    def adopt_if_prebound(self, *, binding: BindingT) -> RuntimeParentReceiptV1 | None: ...
    def stop_exact(self, *, binding: BindingT, receipt: RuntimeParentReceiptV1) -> bool: ...
    def verify_before_quiesce(
        self, *, binding: BindingT, receipt: RuntimeParentReceiptV1, runtime_id: str
    ) -> bool: ...
    def verify_final_before_remove(
        self, *, binding: BindingT, receipt: RuntimeParentReceiptV1, runtime_id: str
    ) -> bool: ...


class AttemptLifecycleRuntimePort[BindingT: ExactRuntimeBindingPort](Protocol):
    def resolve_exact(self, binding: BindingT) -> str | None: ...
    def quiesce_exact(
        self, *, attempt: BindingT, runtime_id: str, deadline_monotonic: float
    ) -> bool: ...
    def remove_exact(
        self, *, attempt: BindingT, runtime_id: str, deadline_monotonic: float
    ) -> bool: ...


class AttemptRuntimeCleanupCoordinator[BindingT: ExactRuntimeBindingPort]:
    """The only launcher-owned mutation path shared by monitor and foreground cleanup."""

    _MONITOR_REASONS = {"CPU_LIMIT_EXCEEDED", "DEADLINE_EXCEEDED", "CANCELLED"}

    def __init__(
        self,
        *,
        journal: AttemptLifecycleJournalPort,
        runtime_parent: AttemptLifecycleParentPort[BindingT],
        runtime_cleanup: AttemptLifecycleRuntimePort[BindingT],
        latch_admission_closed: Callable[[], None],
        attempt: BindingT,
        receipt: RuntimeParentReceiptV1,
        runtime_id: str,
        cleanup_deadline_monotonic: float,
    ) -> None:
        self._journal = journal
        self._runtime_parent = runtime_parent
        self._runtime_cleanup = runtime_cleanup
        self._latch_admission_closed = latch_admission_closed
        self._attempt = attempt
        self._receipt = receipt
        self._runtime_id = runtime_id
        self._cleanup_deadline_monotonic = cleanup_deadline_monotonic
        self._lock = threading.RLock()
        self._cleanup_required_recorded = False
        self._quiesced = False
        self._removed = False
        self._failed = False
        self._failure_recorded = False

    @property
    def cleanup_required_recorded(self) -> bool:
        with self._lock:
            return self._cleanup_required_recorded

    @property
    def failure_recorded(self) -> bool:
        with self._lock:
            return self._failure_recorded

    @property
    def cleanup_complete(self) -> bool:
        with self._lock:
            return self._removed

    def terminate_from_monitor(self, reason: str) -> float:
        if reason not in self._MONITOR_REASONS:
            self._failure("runtime monitor reason is invalid")
        started = time.monotonic()
        self.quiesce(disposition="MONITOR_" + reason)
        return time.monotonic() - started

    def quiesce(self, *, disposition: str) -> None:
        with self._lock:
            if self._failed:
                raise InspectorSandboxUnavailable("exact runtime cleanup is unavailable")
            try:
                if not self._cleanup_required_recorded:
                    self._journal.cleanup_required(
                        self._attempt.attempt_nonce, disposition=disposition
                    )
                    self._cleanup_required_recorded = True
                if self._quiesced:
                    return
                if not self._runtime_parent.verify_before_quiesce(
                    binding=self._attempt,
                    receipt=self._receipt,
                    runtime_id=self._runtime_id,
                ):
                    raise InspectorSandboxUnavailable("exact runtime parent proof is unavailable")
                if not self._runtime_cleanup.quiesce_exact(
                    attempt=self._attempt,
                    runtime_id=self._runtime_id,
                    deadline_monotonic=self._cleanup_deadline_monotonic,
                ):
                    raise InspectorSandboxUnavailable("exact runtime quiesce is unavailable")
                if not self._runtime_parent.verify_final_before_remove(
                    binding=self._attempt,
                    receipt=self._receipt,
                    runtime_id=self._runtime_id,
                ):
                    raise InspectorSandboxUnavailable(
                        "exact runtime final measurement is unavailable"
                    )
                self._quiesced = True
            except Exception as exc:
                self._failure("exact runtime cleanup is unavailable")
                raise InspectorSandboxUnavailable("exact runtime cleanup is unavailable") from exc

    def remove_after_quiesce(self) -> None:
        with self._lock:
            if self._failed:
                raise InspectorSandboxUnavailable("exact runtime cleanup is unavailable")
            try:
                if not self._quiesced:
                    raise InspectorSandboxUnavailable("exact runtime is not quiesced")
                if self._removed:
                    return
                if not self._runtime_cleanup.remove_exact(
                    attempt=self._attempt,
                    runtime_id=self._runtime_id,
                    deadline_monotonic=self._cleanup_deadline_monotonic,
                ):
                    raise InspectorSandboxUnavailable("exact runtime cleanup is unavailable")
                self._removed = True
            except Exception as exc:
                self._failure("exact runtime cleanup is unavailable")
                raise InspectorSandboxUnavailable("exact runtime cleanup is unavailable") from exc

    def quiesce_and_remove(self, *, disposition: str) -> None:
        self.quiesce(disposition=disposition)
        self.remove_after_quiesce()

    def _failure(self, message: str) -> None:
        self._failed = True
        self._latch_admission_closed()
        if self._cleanup_required_recorded and not self._failure_recorded:
            self._failure_recorded = True
            with suppress(Exception):
                self._journal.cleanup_failed(
                    self._attempt.attempt_nonce, reason="EXACT_RUNTIME_CLEANUP_UNAVAILABLE"
                )
        del message


def reconcile_inflight_creation[BindingT: ExactRuntimeBindingPort](
    *,
    attempt: BindingT,
    journal: AttemptLifecycleJournalPort,
    runtime_parent_port: AttemptLifecycleParentPort[BindingT],
    runtime_cleanup: AttemptLifecycleRuntimePort[BindingT],
    latch_admission_closed: Callable[[], None],
    retain_for_recovery: Callable[[], None],
    runtime_id: str | None,
    runtime_parent: RuntimeParentReceiptV1 | None,
    parent_creating: bool,
    container_creating: bool,
) -> tuple[bool, str | None, RuntimeParentReceiptV1 | None]:
    """Journal exact observed create outcome, or retain unknown ownership for recovery."""

    def retain_ambiguity(*, disposition: str) -> tuple[bool, None, None]:
        try:
            journal.cleanup_required(attempt.attempt_nonce, disposition=disposition)
            journal.cleanup_failed(attempt.attempt_nonce, reason="EXACT_CREATE_OUTCOME_UNAVAILABLE")
        finally:
            try:
                retain_for_recovery()
            finally:
                latch_admission_closed()
        return True, None, None

    if parent_creating:
        try:
            observed_parent = runtime_parent_port.adopt_if_prebound(binding=attempt)
        except Exception:
            return retain_ambiguity(
                disposition="RUNTIME_PARENT_CREATE_AMBIGUOUS",
            )
        if observed_parent is None:
            return retain_ambiguity(
                disposition="RUNTIME_PARENT_CREATE_AMBIGUOUS",
            )
        try:
            journal.runtime_parent_bound(attempt.attempt_nonce, observed_parent)
        except Exception:
            return retain_ambiguity(
                disposition="RUNTIME_PARENT_CREATE_AMBIGUOUS",
            )
        runtime_parent = observed_parent
    if container_creating:
        try:
            observed_runtime_id = runtime_cleanup.resolve_exact(attempt)
        except Exception:
            return retain_ambiguity(
                disposition="CONTAINER_CREATE_AMBIGUOUS",
            )
        if observed_runtime_id is None:
            return retain_ambiguity(
                disposition="CONTAINER_CREATE_AMBIGUOUS",
            )
        try:
            journal.container_bound(attempt.attempt_nonce, observed_runtime_id)
        except Exception:
            return retain_ambiguity(
                disposition="CONTAINER_CREATE_AMBIGUOUS",
            )
        runtime_id = observed_runtime_id
    return False, runtime_id, runtime_parent
