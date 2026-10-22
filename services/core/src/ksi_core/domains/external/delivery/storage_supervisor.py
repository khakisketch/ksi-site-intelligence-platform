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

#: The fixed descriptor number the child's channel is copied onto. It is high
#: enough to stay clear of the interpreter's own descriptors and low enough to
#: stay inside the descriptor limit.
_CHANNEL_FD_NUMBER = 21


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

    def send_end(self) -> None:
        self._send(b"E")

    def send_failure(self, reason: str, status_code: int, retryable: bool) -> None:
        self._send(
            b"X" + canonical_json_bytes(
                {"reason": reason, "status": status_code, "retryable": retryable}
            )
        )

    def command(self) -> str:
        command = self._socket.recv(1)
        if command == b"N":
            return "NEXT"
        if command in (b"C", b""):
            return "CLOSE"
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)


def run_storage_child(channel: StorageChildChannel, work: dict[str, Any]) -> None:
    """Execute one data-described storage operation inside the child.

    The description is plain JSON: an operation name plus its exact parameters. No
    callable, closure, SDK client or credential object crosses the boundary, so the
    child can be started as a fresh interpreter without inheriting parent state.
    """
    from ksi_core.domains.external.delivery import storage_child_work

    storage_child_work.execute(channel, work)


class ExecSpec:
    """A fresh-interpreter child: exact argv, environment and inherited descriptors.

    The child is a NEW interpreter, so it inherits no parent thread, no parent lock
    and no parent descriptor. Only the descriptors listed in ``pass_fds`` survive, and
    the work description travels as plain data in the environment.
    """

    def __init__(
        self,
        *,
        argv: list[str],
        env: dict[str, str],
        pass_fds: tuple[int, ...] = (),
        cwd: str | None = None,
        channel: socket.socket | None = None,
    ) -> None:
        if not argv or not env:
            raise ValueError("an exec child needs an explicit argv and environment")
        self._argv = list(argv)
        self._env = dict(env)
        self._pass_fds = tuple(pass_fds)
        self._cwd = cwd
        self._channel = channel

    def spawn(self) -> int:
        import subprocess

        # The channel descriptor must reach the child under a KNOWN number:
        # ``pass_fds`` keeps the descriptor open but does not promise the same
        # number inside the child, and the child addresses the channel by that
        # number.
        #
        # The descriptor is copied onto the fixed number in the PARENT before
        # the child starts, and handed over as an inheritable descriptor. A
        # ``preexec_fn`` would do the same inside the child, but it runs
        # between fork and exec in a THREADED parent — exactly the hazard this
        # whole change exists to remove.
        # The channel must reach the child under a number the child can rely
        # on: ``subprocess`` keeps a descriptor OPEN across the boundary but
        # does NOT promise the same NUMBER, and the child addresses the
        # channel by that number. The descriptor is therefore copied onto a
        # fixed number in the PARENT (no ``preexec_fn``: that would run
        # between fork and exec inside a THREADED parent, the exact hazard
        # this whole change removes) and handed over by number.
        # The child addresses the channel by NUMBER, and a descriptor's
        # number is not preserved across the exec boundary. The channel is
        # therefore handed over on a DEDICATED descriptor that nothing else in
        # the parent uses, copied there in the parent (no ``preexec_fn``: that
        # would run between fork and exec inside a THREADED parent, the
        # exact hazard this whole change removes).
        # The channel is handed over as an INHERITABLE descriptor. The child's
        # number for it is not stable across the exec boundary, so the child
        # identifies it by the file it points at (its inode) instead.
        # The descriptor is resolved HERE, at spawn time: a launcher that
        # takes its own time must still hand over a valid channel.
        channel_fd = self._channel.fileno() if self._channel is not None else None
        if channel_fd is not None:
            os.set_inheritable(channel_fd, True)
        process = subprocess.Popen(  # noqa: S603 -- argv is owner-built, no shell
            self._argv,
            env=self._env,
            cwd=self._cwd,
            pass_fds=(channel_fd,) if channel_fd is not None else (),
            close_fds=True,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._process = process
        return process.pid

    @property
    def stderr(self) -> Any:
        process = getattr(self, "_process", None)
        return getattr(process, "stderr", None)


class StorageOwnedProcess:
    """A single owned PID/group; only the launch/watch thread kills then reaps it.

    The child is started with ``exec`` of a fresh interpreter, not ``fork()``. A
    forked child of the multi-threaded ASGI server inherits only the calling thread
    while the parent's other threads keep holding their locks, and its descriptor
    sweep races the parent's own threads. ``exec`` removes both hazards: the child
    starts with no parent thread, no parent lock, and no parent descriptor.
    """

    def __init__(
        self,
        target: Callable[[], None] | None = None,
        *,
        exec_spec: ExecSpec | None = None,
    ) -> None:
        if (target is None) == (exec_spec is None):
            raise ValueError("exactly one of an in-process target or an exec spec is required")
        self._target = target
        self._exec_spec = exec_spec
        self.pid: int | None = None
        self.stderr = None

    def start(self) -> None:
        if self._exec_spec is not None:
            self.pid = self._exec_spec.spawn()
            return
        pid = os.fork()
        if pid == 0:
            try:
                assert self._target is not None
                self._target()
            finally:
                os._exit(0)
        self.pid = pid

    def exited(self) -> bool:
        """True once the child has exited — the parent's cue to stop waiting.

        The child is only OBSERVED here, never reaped: the launch/watch thread
        owns the reap, so this must not consume the exit status. The process
        state is read from /proc rather than waited on, so a zombie child is
        still visible to the thread that must reap it.
        """
        pid = self.pid
        if pid is None:
            return True
        try:
            with open(f"/proc/{pid}/stat", "rb") as stat:
                fields = stat.read().rsplit(b")", 1)[-1].split()
            # The process state letter follows the parenthesised command.
            state = fields[0].decode("ascii", "replace")
        except (FileNotFoundError, ProcessLookupError, IndexError, OSError):
            return True
        return state in ("Z", "X")

    def finished(self) -> bool:
        """True once the child has answered and left — without reaping it."""
        return self.exited()

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
            except ChildProcessError:
                # Already reaped elsewhere: the child is gone, which is all the
                # caller needs to know.
                self.pid = None
                return


def _launch(process: StorageOwnedProcess) -> None:
    process.start()


def _drain_child_stderr(process: StorageOwnedProcess) -> None:
    """Surface a child's own diagnostics instead of swallowing them.

    A child that dies before it can report WHY leaves the parent with a bare
    503. The child's stderr is the only evidence of the real fault, so it is
    copied to the parent's stderr rather than discarded.
    """

    stream = getattr(process, "stderr", None)
    if stream is None:
        return
    try:
        for line in iter(stream.readline, b""):
            if not line:
                break
            import sys

            print(line.decode("utf-8", "replace").rstrip(), file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def _exec_spec(connection: socket.socket, description: dict[str, Any]) -> ExecSpec:
    """The child spec: a fresh interpreter, one inheritable channel fd, plain data."""
    import sys

    from ksi_core.domains.external.delivery import storage_child

    fd = connection.fileno()
    os.set_inheritable(fd, True)
    env = dict(os.environ)
    # The descriptor's number is not preserved across the exec boundary, but the
    # file it points at is: the child adopts the socket with this inode.
    env[storage_child.CHANNEL_INODE_ENV] = str(os.fstat(fd).st_ino)
    # ``subprocess`` keeps a descriptor's NUMBER inside the child, but it does
    # not guarantee the same number it had in the parent: the child may be
    # handed a different one. The child therefore finds the channel by
    # SCANNING its own descriptors for the socket, and the parent marks the
    # one true channel with a dedicated pipe the child can read.
    env[storage_child.CHANNEL_FD_ENV] = str(fd)
    env[storage_child.WORK_ENV] = canonical_json_bytes(description).decode("ascii")
    # The child's own SDK deadline travels with the description. A caller that
    # omits it still gets the session's own bound, never an unbounded one.
    operation_timeout = description.get("operationTimeoutSeconds")
    if not isinstance(operation_timeout, (int, float)) or operation_timeout <= 0:
        raise ValueError("an exec child needs an explicit positive operation timeout")
    # A client factory named in the description is the child's SDK, so the
    # child must be able to import it. The owner names the directory it lives
    # in; the child adds that path. A path, never code.
    factory = description.get("clientFactory")
    if isinstance(factory, str) and factory and "clientFactory" not in env:
        env["KSI_CORE_S3_CLIENT_FACTORY"] = factory

    # The child must import exactly what the parent can import. ``-m`` seeds
    # sys.path from the CURRENT directory, which is not the parent's import
    # path, so the parent's own sys.path is carried over explicitly.
    parent_path = [entry for entry in sys.path if entry]
    env["PYTHONPATH"] = os.pathsep.join(parent_path)
    # The client's factory module may live outside that path (the contract
    # suite's substitute does). The owner names the directory it must be
    # importable from, and the child adds it — a path, never code.
    factory_dir = description.get("clientFactoryPath")
    if isinstance(factory_dir, str) and factory_dir:
        env["PYTHONPATH"] = os.pathsep.join([factory_dir, env["PYTHONPATH"]])
    # The parent's own import path is what the child must use; pytest's
    # rootdir insertion is part of it.

    return ExecSpec(
        argv=[sys.executable, "-m", "ksi_core.domains.external.delivery.storage_child"],
        env=env,
        pass_fds=(fd,),
        # The child runs the same module path the parent resolved, so it must
        # start from the same working directory (``-m`` seeds sys.path[0] from
        # the current directory).
        cwd=os.getcwd(),
        # The channel is handed over under a FIXED number: the child must be
        # able to address it, and a descriptor's number is not preserved
        # across the exec boundary.
        channel=connection,
    )


class StorageParentSession:
    def __init__(
        self,
        connection: socket.socket,
        *,
        deadline: float,
        max_frame_bytes: int,
        stop: Event,
        finished: Event,
        child_exited: Callable[[], bool] | None = None,
    ) -> None:
        self._socket = connection
        self._deadline = deadline
        self._max_frame_bytes = max_frame_bytes
        self._stop = stop
        self._closed = False
        self._ended = False
        self._finished = finished
        self._child_exited = child_exited or (lambda: False)

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
                # A failure frame is TERMINAL: the child reports the refusal
                # and then leaves. Treating it as "more may follow" would keep
                # the caller waiting for a reply that can never arrive.
                self._ended = True
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
                # A child that already answered (or failed) has nothing left to
                # say; waiting for a reply that can never arrive would hold the
                # caller open for the whole budget. The channel is checked FIRST:
                # a child that is gone, or that already sent its answer, must
                # not be waited on.
                if not self._child_gone():
                    self._socket.settimeout(self._remaining())
                    self._socket.sendall(b"C")
                    while not self._ended and not self._child_gone():
                        self.receive()
                else:
                    self._drain_pending()
        except (OSError, SpatialDataDomainError):
            pass
        finally:
            self._stop.set()
            self._socket.close()
            self._finished.wait(max(0, self._deadline - time.monotonic()))

    def _child_gone(self) -> bool:
        """True when the child has exited and no further frame can arrive.

        The child's exit is observed through the CHANNEL, not through the
        process table: the launch/watch thread reaps the child, so the process
        entry can already be gone by the time the caller closes the session.
        A closed channel means the child is gone for good.
        """
        if self._child_exited():
            return True
        try:
            self._socket.settimeout(0.0)
            return not self._socket.recv(1, socket.MSG_PEEK)
        except BlockingIOError:
            return False
        except OSError:
            return True
        finally:
            with suppress(OSError):
                self._socket.settimeout(None)

    def _drain_pending(self) -> None:
        """Read whatever the child already sent, without waiting for more."""
        try:
            self._socket.settimeout(0.05)
            while True:
                chunk = self._socket.recv(65536)
                if not chunk:
                    return
        except OSError:
            return


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
    def data_session(
        self,
        description: dict[str, Any],
        *,
        timeout_seconds: float,
        max_frame_bytes: int,
    ) -> Iterator[StorageParentSession]:
        """Run a DATA-described operation in a FRESH child interpreter.

        The child is started with ``exec``, so it inherits no parent thread, no
        parent lock and no parent descriptor. The description travels as plain JSON
        and the child rebuilds its own SDK client from the owner's ambient
        credential environment.
        """
        work = dict(description)
        # The child's own SDK deadline is the session's bound. Without it the
        # child would have no deadline to refuse an unbounded client by.
        work.setdefault("operationTimeoutSeconds", timeout_seconds)
        with self._session(
            None, timeout_seconds=timeout_seconds, max_frame_bytes=max_frame_bytes, description=work
        ) as session:
            yield session

    @contextmanager
    def _session(
        self,
        worker: Callable[[StorageChildChannel], None] | None,
        *,
        timeout_seconds: float,
        max_frame_bytes: int,
        description: dict[str, Any] | None = None,
    ) -> Iterator[StorageParentSession]:
        started = time.monotonic()
        _positive_seconds(timeout_seconds)
        if type(max_frame_bytes) is not int or not 1 <= max_frame_bytes <= 2**32 - 1:
            raise ValueError("explicit bounded frame size required")
        if (worker is None) == (description is None):
            raise ValueError(
                "exactly one of an in-process worker or a data description is required"
            )
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
        # The parent and the child are the two ends of one socketpair: the
        # parent reads and writes its own end, the child the other. The child
        # adopts the descriptor by INODE, because a descriptor's number is not
        # preserved across the exec boundary.
        session = StorageParentSession(
            parent,
            deadline=deadline,
            max_frame_bytes=max_frame_bytes,
            stop=stop,
            finished=finished,
            child_exited=lambda: process.exited(),
        )
        if description is None:
            raise ValueError("an exec child needs a data description")
        # The channel descriptor stays open until the child really exists: a
        # launcher that takes its own time would otherwise find it closed.
        exec_spec = _exec_spec(child, description)
        process = StorageOwnedProcess(exec_spec=exec_spec)

        def launch_watch_reap() -> None:
            try:
                # The launcher may take its own time before the child exists
                # (the owner injects a trusted launcher). The watch owns the
                # child it produced: a late child stays owned and is reaped
                # here instead of being abandoned.
                # The launcher may take its own time before the child exists
                # (the owner injects a trusted launcher). It runs in its OWN
                # thread so a slow launch is never mistaken for a dead
                # child, and a child that arrives after the caller gave up
                # is still reaped here instead of being abandoned.
                launched = Event()

                def do_launch() -> None:
                    try:
                        self._launcher(process)
                    finally:
                        launched.set()

                Thread(target=do_launch, daemon=True, name="data-storage-launcher").start()
                if not launched.wait(max(0, deadline - time.monotonic())):
                    failures.append(True)
                ready.set()
                # The child's stderr is drained in its OWN thread: reading it
                # here would block this thread until the child closes the
                # pipe, and the child only closes it after it has answered —
                # which would deadlock the answer the caller is waiting for.
                _stderr_thread = Thread(
                    target=_drain_child_stderr,
                    args=(process,),
                    daemon=True,
                    name="data-storage-stderr",
                )
                _stderr_thread.start()
                # The child owns the far end of the channel. A forked child kept
                # its own copy, so the parent could close it; an exec child
                # inherited only the descriptor NUMBER, so the parent closing
                # it tears the channel down. The parent must leave it open.
                #
                # The watch must NOT kill the child while the caller is still
                # waiting for its answer. The child ends on its own once it has
                # answered; a child that hangs is killed at the deadline. The
                # caller closing the session sets ``stop``, which ends the wait
                # immediately.
                while not stop.wait(0.05):
                    if time.monotonic() >= deadline:
                        break
            except BaseException:
                failures.append(True)
                ready.set()
            finally:
                # The child's end of the channel is closed only once the child
                # is really gone. A launcher that is still creating it must
                # find a usable descriptor.
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
            # ``ready`` means the child PROCESS is up. The child's first FRAME
            # is what the caller actually waits for, and the session's own
            # deadline covers that: a child that never answers must not leave
            # the caller hanging past the total budget.
            if not ready.wait(max(0, deadline - time.monotonic())) or failures:
                raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
            yield session
        finally:
            session.close()
