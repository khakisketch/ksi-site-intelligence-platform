"""Actual SDK-child supervision, including launch, framed receive, and retained late cleanup."""

import os
import time
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError


def test_worker_stall_is_killed_within_total_deadline(tmp_path: Path) -> None:
    """An SDK operation that never returns must not hold the request or an untracked child."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    pid_path = tmp_path / "child.pid"

    def stalled(channel: Any) -> None:
        pid_path.write_text(str(os.getpid()))
        Event().wait(10)

    supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
    start = time.monotonic()
    with (
        pytest.raises(SpatialDataDomainError) as error,
        supervisor.session(stalled, timeout_seconds=0.15, max_frame_bytes=4096) as session,
    ):
        session.receive()
    assert error.value.reason == "STORAGE_UNAVAILABLE"
    assert time.monotonic() - start < 0.6
    assert pid_path.exists()


def test_delayed_launch_returns_on_time_and_never_leaves_late_child(tmp_path: Path) -> None:
    """The clock must include launch; a late child stays owned after timeout."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    entered, release, launched = Event(), Event(), Event()
    pid_path = tmp_path / "late-child.pid"

    def delayed_start(process: Any) -> None:
        entered.set()
        release.wait(2)
        process.start()
        launched.set()

    def work(channel: Any) -> None:
        pid_path.write_text(str(os.getpid()))
        channel.send_json({"ok": True})

    supervisor = SpatialDataStorageSupervisor(max_concurrency=1, launcher=delayed_start)
    start = time.monotonic()
    with (
        pytest.raises(SpatialDataDomainError),
        supervisor.session(work, timeout_seconds=0.1, max_frame_bytes=4096) as session,
    ):
        session.receive()
    assert entered.is_set() and time.monotonic() - start < 0.5
    # Capacity remains reserved while the still-running launcher can create a process.
    with (
        pytest.raises(SpatialDataDomainError) as error,
        supervisor.session(work, timeout_seconds=0.1, max_frame_bytes=4096),
    ):
        pytest.fail("untracked late-launch capacity was released early")
    assert error.value.reason == "CONCURRENCY_LIMIT_EXCEEDED"
    release.set()
    assert launched.wait(2)
    assert supervisor.wait_for_idle(timeout_seconds=2)
    if pid_path.exists():
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_path.read_text()), 0)


def test_success_uses_bounded_frames_and_releases_capacity() -> None:
    """A correct SDK result must be delivered without leaking reserved process capacity."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    def work(channel: Any) -> None:
        channel.send_json({"result": "exact"})

    supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
    for _ in range(2):
        with supervisor.session(work, timeout_seconds=1, max_frame_bytes=4096) as session:
            assert session.receive() == ("JSON", {"result": "exact"})
            assert session.receive() == ("END", None)
        assert supervisor.wait_for_idle(timeout_seconds=1)


def test_partial_frame_stall_is_bounded_too() -> None:
    """Socket readability of a length header must not permit an unbounded payload receive."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    def work(channel: Any) -> None:
        channel._socket.sendall(b"\x00\x00\x00\x64J{")  # noqa: SLF001
        Event().wait(10)

    supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
    start = time.monotonic()
    with (
        pytest.raises(SpatialDataDomainError),
        supervisor.session(work, timeout_seconds=0.1, max_frame_bytes=4096) as session,
    ):
        session.receive()
    assert time.monotonic() - start < 0.5
    assert supervisor.wait_for_idle(timeout_seconds=1)


def test_oversized_frame_is_refused_before_payload_allocation() -> None:
    """An untrusted announced length cannot allocate the entire SDK response in the parent."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    def work(channel: Any) -> None:
        channel._socket.sendall(b"\xff\xff\xff\xff")  # noqa: SLF001
        Event().wait(10)

    supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
    with (
        pytest.raises(SpatialDataDomainError) as error,
        supervisor.session(work, timeout_seconds=1, max_frame_bytes=4096) as session,
    ):
        session.receive()
    assert error.value.reason == "RESOURCE_LIMIT_EXCEEDED"
    assert supervisor.wait_for_idle(timeout_seconds=1)


def test_watchdog_expires_even_when_caller_is_not_reading() -> None:
    """A leaked/idle stream context must not leave a waiting SDK child alive beyond its deadline."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    def work(channel: Any) -> None:
        Event().wait(10)

    supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
    with supervisor.session(work, timeout_seconds=0.1, max_frame_bytes=4096):
        assert supervisor.wait_for_idle(timeout_seconds=1)


def test_failed_reap_retains_slot_until_actual_process_cleanup(tmp_path: Path) -> None:
    """Operational kill/reap failure must not drop the ownership record and admit another child."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    failed, allow_cleanup = Event(), Event()
    owned = []

    def launcher(process: Any) -> None:
        original = process.kill_and_reap
        owned.append(original)

        def blocked_reap() -> None:
            if not allow_cleanup.is_set():
                failed.set()
                raise OSError("local simulated unavailable reap syscall")
            original()

        process.kill_and_reap = blocked_reap
        process.start()

    def work(channel: Any) -> None:
        (tmp_path / "owned.pid").write_text(str(os.getpid()))
        Event().wait(10)

    supervisor = SpatialDataStorageSupervisor(max_concurrency=1, launcher=launcher)
    try:
        with (
            pytest.raises(SpatialDataDomainError),
            supervisor.session(work, timeout_seconds=0.1, max_frame_bytes=4096) as session,
        ):
            session.receive()
        assert failed.wait(1)
        assert not supervisor.wait_for_idle(timeout_seconds=0.1)
        with (
            pytest.raises(SpatialDataDomainError) as error,
            supervisor.session(work, timeout_seconds=0.1, max_frame_bytes=4096),
        ):
            pytest.fail("capacity was released before the owned PID was reaped")
        assert error.value.reason == "CONCURRENCY_LIMIT_EXCEEDED"
    finally:
        allow_cleanup.set()
        try:
            assert supervisor.wait_for_idle(timeout_seconds=2)
            with pytest.raises(ProcessLookupError):
                os.kill(int((tmp_path / "owned.pid").read_text()), 0)
        finally:
            # Keep RED executions leak-free too; solely a test utility.
            from contextlib import suppress

            with suppress(ChildProcessError):
                owned[0]()
