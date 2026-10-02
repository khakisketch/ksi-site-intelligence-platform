"""Total-deadline SDK child sessions with private bounded framing and tracked late launches.

This is Linux local software supervision, not a container/host isolation attestation.
Only trusted fixed SDK workers and a trusted launcher may be injected by assembly.
"""

from __future__ import annotations

import json
import math
import os
import signal
import socket
import struct
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from threading import Condition, Event, Thread
from typing import Any

from ksi_domain.canonical_json import canonical_json_bytes

from ksi_core.domains.external.delivery.errors import SpatialDataDomainError


def _positive_seconds(value: float) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("explicit positive finite storage deadline required")


class StorageChildChannel:
    def __init__(self, connection: socket.socket, max_frame_bytes: int) -> None:
        self._socket = connection
        self._max_frame_bytes = max_frame_bytes

    def _send(self, frame: bytes) -> None:
        if not 1 <= len(frame) <= self._max_frame_bytes:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        self._socket.sendall(struct.pack("!I", len(frame)) + frame)

    def send_json(self, value: dict[str, Any]) -> None:
        self._send(b"J" + canonical_json_bytes(value))

    def send_bytes(self, value: bytes) -> None:
        if type(value) is not bytes:
            raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
        self._send(b"B" + value)

    def command(self) -> str:
        command = self._socket.recv(1)
        if command == b"N":
            return "NEXT"
        if command in (b"C", b""):
            return "CLOSE"
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)


def _child_main(
    connection: socket.socket, worker: Callable[[StorageChildChannel], None], max_frame_bytes: int
) -> None:
    os.setsid()
    # Never inherit journal locks, parent sockets, stdio tokens or a live pooled SDK
    # connection into a fresh client factory. /proc is the explicit Linux boundary.
    keep = connection.fileno()
    for entry in os.listdir("/proc/self/fd"):
        fd = int(entry)
        if fd > 2 and fd != keep:
            with suppress(OSError):
                os.close(fd)
    null = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null, fd)
    if null > 2 and null != keep:
        os.close(null)
    channel = StorageChildChannel(connection, max_frame_bytes)
    try:
        worker(channel)
        channel._send(b"E")
    except SpatialDataDomainError as exc:
        with suppress(OSError, ValueError):
            channel._send(
                b"X"
                + canonical_json_bytes(
                    {"reason": exc.reason, "status": exc.status_code, "retryable": exc.retryable}
                )
            )
    except BaseException:
        with suppress(OSError, ValueError):
            channel._send(
                b"X"
                + canonical_json_bytes(
                    {"reason": "STORAGE_UNAVAILABLE", "status": 503, "retryable": True}
                )
            )
    finally:
        connection.close()


class StorageOwnedProcess:
    """A single owned PID/group; only the launch/watch thread kills then reaps it."""

    def __init__(self, target: Callable[[], None]) -> None:
        self._target = target
        self.pid: int | None = None

    def start(self) -> None:
        pid = os.fork()
        if pid == 0:
            try:
                self._target()
            finally:
                os._exit(0)
        self.pid = pid

    def kill_and_reap(self) -> None:
        pid = self.pid
        if pid is None:
            return
        # The PID is still ours (unreaped). Group kill also closes SDK descendants;
        # when setsid has not run yet, kill exactly the owned leader instead.
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        while True:
            try:
                os.waitpid(pid, 0)
                self.pid = None
                return
            except InterruptedError:
                continue


def _launch(process: StorageOwnedProcess) -> None:
    process.start()


class StorageParentSession:
    def __init__(
        self,
        connection: socket.socket,
        *,
        deadline: float,
        max_frame_bytes: int,
        stop: Event,
        finished: Event,
    ) -> None:
        self._socket = connection
        self._deadline = deadline
        self._max_frame_bytes = max_frame_bytes
        self._stop = stop
        self._closed = False
        self._ended = False
        self._finished = finished

    def _remaining(self) -> float:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
        return remaining

    def _exact(self, size: int) -> bytes:
        parts = []
        received = 0
        while received < size:
            self._socket.settimeout(self._remaining())
            chunk = self._socket.recv(min(size - received, 65536))
            if not chunk:
                raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
            parts.append(chunk)
            received += len(chunk)
        return b"".join(parts)

    def receive(self) -> tuple[str, Any]:
        try:
            (length,) = struct.unpack("!I", self._exact(4))
            if not 1 <= length <= self._max_frame_bytes:
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
            frame = self._exact(length)
            if frame[:1] == b"B":
                return "BYTES", frame[1:]
            if frame == b"E":
                self._ended = True
                return "END", None
            if frame[:1] not in (b"J", b"X"):
                raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
            body = json.loads(frame[1:])
            if type(body) is not dict:
                raise ValueError("SDK frame must be a JSON object")
            if frame[:1] == b"X":
                if set(body) != {"reason", "status", "retryable"}:
                    raise ValueError("invalid failure frame")
                raise SpatialDataDomainError(body["reason"], body["status"], body["retryable"])
            return "JSON", body
        except SpatialDataDomainError:
            raise
        except (OSError, ValueError, RecursionError, KeyError, TypeError) as exc:
            raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True) from exc

    def next_chunk(self) -> tuple[str, Any]:
        try:
            self._socket.settimeout(self._remaining())
            self._socket.sendall(b"N")
            return self.receive()
        except OSError as exc:
            raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True) from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if not self._ended and time.monotonic() < self._deadline:
                self._socket.settimeout(self._remaining())
                self._socket.sendall(b"C")
                while not self._ended:
                    self.receive()
        except (OSError, SpatialDataDomainError):
            pass
        finally:
            self._stop.set()
            self._socket.close()
            self._finished.wait(max(0, self._deadline - time.monotonic()))


class SpatialDataStorageSupervisor:
    def __init__(
        self, *, max_concurrency: int, launcher: Callable[[StorageOwnedProcess], None] = _launch
    ) -> None:
        if type(max_concurrency) is not int or max_concurrency < 1 or not callable(launcher):
            raise ValueError("explicit bounded storage capacity and trusted launcher required")
        self._max_concurrency = max_concurrency
        self._launcher = launcher
        self._condition = Condition()
        self._active = 0

    def wait_for_idle(self, *, timeout_seconds: float) -> bool:
        """Bounded operational shutdown/readiness wait; stuck cleanup never loses its slot."""
        _positive_seconds(timeout_seconds)
        with self._condition:
            return self._condition.wait_for(lambda: self._active == 0, timeout_seconds)

    @contextmanager
    def session(
        self,
        worker: Callable[[StorageChildChannel], None],
        *,
        timeout_seconds: float,
        max_frame_bytes: int,
    ) -> Iterator[StorageParentSession]:
        started = time.monotonic()
        _positive_seconds(timeout_seconds)
        if type(max_frame_bytes) is not int or not 1 <= max_frame_bytes <= 2**32 - 1:
            raise ValueError("explicit bounded frame size required")
        with self._condition:
            if self._active >= self._max_concurrency:
                raise SpatialDataDomainError("CONCURRENCY_LIMIT_EXCEEDED", 429, True)
            self._active += 1
        deadline = started + timeout_seconds
        stop, ready, finished = Event(), Event(), Event()
        failures = []
        try:
            parent, child = socket.socketpair()
        except BaseException:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()
            raise
        session = StorageParentSession(
            parent, deadline=deadline, max_frame_bytes=max_frame_bytes, stop=stop, finished=finished
        )
        process = StorageOwnedProcess(lambda: _child_main(child, worker, max_frame_bytes))

        def launch_watch_reap() -> None:
            try:
                self._launcher(process)
                ready.set()
                child.close()
                stop.wait(max(0, deadline - time.monotonic()))
            except BaseException:
                failures.append(True)
                ready.set()
            finally:
                child.close()
                # Failed reap is not cleanup. Retain the exact process and capacity
                # until the OS confirms reaping, without holding the caller open.
                retry_wait = Event()
                while True:
                    try:
                        process.kill_and_reap()
                        break
                    except OSError:
                        retry_wait.wait(0.1)
                with self._condition:
                    self._active -= 1
                    self._condition.notify_all()
                finished.set()

        try:
            Thread(target=launch_watch_reap, daemon=True, name="data-storage-owner").start()
        except BaseException:
            child.close()
            session.close()
            with self._condition:
                self._active -= 1
                self._condition.notify_all()
            raise
        try:
            if not ready.wait(max(0, deadline - time.monotonic())) or failures:
                raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
            yield session
        finally:
            session.close()
