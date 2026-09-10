"""Focused tests for the fixed FD-only inspector byte-I/O helper."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from ksi_processing_controller.external_inspector_file_io import BoundedFileIo
from ksi_processing_controller.external_inspector_protocol import (
    ProtocolDeadline,
    ProtocolViolation,
)


def test_fd_helper_writes_and_seals_exact_bytes(tmp_path: Path) -> None:
    """Only a valid helper ACK advances the caller-visible byte state."""
    artifact = tmp_path / "artifact"
    descriptor = os.open(artifact, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        io = BoundedFileIo(descriptor=descriptor, maximum_bytes=64)
        deadline = ProtocolDeadline(500, time.monotonic)

        io.write_chunk(
            b"sealed-bytes",
            deadline=deadline,
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )
        receipt = io.seal(
            deadline=deadline,
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )

        assert io.written_bytes == len(b"sealed-bytes")
        assert io.is_quarantined is False
        assert receipt.size_bytes == len(b"sealed-bytes")
        assert receipt.sha256 == (
            "sha256:4bbfb55b2ea78a344d49e48cda2ea377d8f270eff2346c91df1e26e3525c79f5"
        )
        assert artifact.read_bytes() == b"sealed-bytes"
    finally:
        os.close(descriptor)


def test_fd_helper_rejects_authority_loss_without_a_write(tmp_path: Path) -> None:
    """Cancellation is checked while waiting and leaves no acknowledged bytes behind."""
    artifact = tmp_path / "artifact"
    descriptor = os.open(artifact, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        io = BoundedFileIo(descriptor=descriptor, maximum_bytes=64)
        with pytest.raises(ProtocolViolation, match="authority lost"):
            io.write_chunk(
                b"x",
                deadline=ProtocolDeadline(1, lambda: 2.0),
                wait_is_current=lambda: False,
                heartbeat_interval_millis=1,
            )
        assert io.written_bytes == 0
        assert artifact.read_bytes() == b""
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("corruption", ("sequence", "offset", "count", "malformed"))
def test_invalid_helper_ack_never_advances_or_seals_caller_state(
    corruption: str,
) -> None:
    """A write may reach the child, but no invalid receipt can publish it to the caller."""
    script = textwrap.dedent(
        f"""
        import json
        import os
        import shutil
        import tempfile
        import time
        from pathlib import Path

        import ksi_processing_controller.external_inspector_file_io as file_io
        from ksi_processing_controller.external_inspector_file_io import BoundedFileIo
        from ksi_processing_controller.external_inspector_protocol import ProtocolDeadline

        artifact = Path(tempfile.mkdtemp()) / "artifact"
        descriptor = os.open(artifact, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        io = BoundedFileIo(descriptor=descriptor, maximum_bytes=8)
        original_receive = io._receive_frame
        state = {{"replies": 0}}

        def corrupted_receive(*args, **kwargs):
            reply = original_receive(*args, **kwargs)
            state["replies"] += 1
            if state["replies"] == 1:
                return reply
            if {corruption!r} == "malformed":
                return b""
            nonce, sequence, operation, offset, count = file_io._FRAME_HEADER.unpack(
                reply[: file_io._FRAME_HEADER.size]
            )
            if {corruption!r} == "sequence":
                sequence += 1
            elif {corruption!r} == "offset":
                offset += 1
            else:
                count += 1
            return file_io._FRAME_HEADER.pack(nonce, sequence, operation, offset, count)

        io._receive_frame = corrupted_receive
        file_io._waitid_pidfd_nonblocking = lambda _pidfd: False
        try:
            io.write_chunk(
                b"x",
                deadline=ProtocolDeadline(500, time.monotonic),
                wait_is_current=lambda: True,
                heartbeat_interval_millis=10,
            )
        except Exception as exc:
            write_error = type(exc).__name__
        else:
            write_error = None
        try:
            io.seal(
                deadline=ProtocolDeadline(500, time.monotonic),
                wait_is_current=lambda: True,
                heartbeat_interval_millis=10,
            )
        except Exception as exc:
            seal_error = type(exc).__name__
        else:
            seal_error = None
        result = {{
            "write_error": write_error,
            "seal_error": seal_error,
            "written": io.written_bytes,
            "artifact": artifact.read_bytes().hex(),
            "quarantined": len(file_io.quarantined_file_io()),
        }}
        shutil.rmtree(artifact.parent)
        print(json.dumps(result))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        cwd=Path.cwd(),
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result == {
        "write_error": "InspectorFileIoUnavailable",
        "seal_error": "InspectorFileIoUnavailable",
        "written": 0,
        "artifact": "78",
        "quarantined": 1,
    }


@pytest.mark.parametrize(
    ("deadline_millis", "lose_authority", "expected_error"),
    [(20, False, "ProtocolDeadlineExceeded"), (500, True, "ProtocolViolation")],
)
def test_actual_input_staging_bounds_a_stopped_helper_and_quarantines_unreaped_ownership(
    deadline_millis: int, lose_authority: bool, expected_error: str
) -> None:
    """The production wrapper retains unreaped ownership instead of overrunning or reusing it."""
    script = textwrap.dedent(
        f"""
        import json
        import os
        import shutil
        import signal
        import tempfile
        import time
        from pathlib import Path

        import ksi_processing_controller.external_inspector_file_io as file_io
        from ksi_processing_controller.external_inspector_file_io import BoundedFileIo
        from ksi_processing_controller.external_inspector_protocol import ProtocolDeadline
        from ksi_processing_controller.external_inspector_staging import FileSystemInputStaging

        original_spawn = file_io.os.posix_spawn

        def spawn_stopped(*args, **kwargs):
            child = original_spawn(*args, **kwargs)
            os.kill(child, signal.SIGSTOP)
            return child

        file_io.os.posix_spawn = spawn_stopped
        file_io._waitid_pidfd_nonblocking = lambda _pidfd: False
        root = Path(tempfile.mkdtemp()) / "private"
        staging = FileSystemInputStaging(
            private_root=root, reader_mapping=object(), acl=object()
        )
        mutable = staging.begin(maximum_bytes=8, deadline_monotonic=time.monotonic() + 1.0)
        checks = 0

        def current():
            nonlocal_state["checks"] += 1
            return not {lose_authority} or nonlocal_state["checks"] < 3

        nonlocal_state = {{"checks": checks}}
        started = time.monotonic()
        try:
            mutable.write_chunk(
                b"x",
                deadline=ProtocolDeadline({deadline_millis}, time.monotonic),
                wait_is_current=current,
                heartbeat_interval_millis=5,
            )
        except Exception as exc:
            error = type(exc).__name__
        else:
            error = None
        artifact = next(root.glob("*/artifact"))
        try:
            BoundedFileIo(descriptor=0, maximum_bytes=1)
        except Exception as exc:
            admission_error = type(exc).__name__
        else:
            admission_error = None
        result = {{
            "elapsed": time.monotonic() - started,
            "error": error,
            "checks": nonlocal_state["checks"],
            "written": mutable._written,
            "artifact_size": artifact.stat().st_size,
            "quarantined": len(file_io.quarantined_file_io()),
            "admission_error": admission_error,
        }}
        shutil.rmtree(root.parent)
        print(json.dumps(result))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        cwd=Path.cwd(),
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result["elapsed"] < 0.150
    assert result["error"] == expected_error
    assert result["checks"] >= 3
    assert result["written"] == 0
    assert result["artifact_size"] == 0
    assert result["quarantined"] == 1
    assert result["admission_error"] == "InspectorFileIoUnavailable"


def test_borrowed_runtime_readback_quarantines_the_retained_source_owner() -> None:
    """A stopped runtime readback helper retains the sealed owner's exact FD."""
    script = textwrap.dedent(
        """
        import json
        import os
        import signal
        import tempfile
        import time
        from hashlib import sha256
        from pathlib import Path

        import ksi_processing_controller.external_inspector_file_io as file_io
        from ksi_processing_controller.external_inspector_protocol import ProtocolDeadlineExceeded
        from ksi_processing_controller.external_inspector_staging import FileSystemInputStaging

        class Reader:
            container_uid = 10001
            container_gid = 10001
            host_uid = os.geteuid()
            host_gid = os.getegid()
            mapping_witness = "runtime-readback-owner"

        reader = Reader()

        class Mapping:
            def resolve_exact(self, **kwargs):
                del kwargs
                return reader

        class Acl:
            def grant_exact(self, **kwargs):
                del kwargs
                return True
            def verifies_exact(self, **kwargs):
                del kwargs
                return True
            def revoke_exact(self, **kwargs):
                del kwargs
                return True

        with tempfile.TemporaryDirectory() as directory:
            payload = b"runtime-owner"
            staging = FileSystemInputStaging(
                private_root=Path(directory) / "private", reader_mapping=Mapping(), acl=Acl()
            )
            mutable = staging.begin(
                maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0
            )
            mutable.write(payload)
            sealed = mutable.seal_for_reader(
                expected_sha256="sha256:" + sha256(payload).hexdigest(),
                expected_size_bytes=len(payload),
                reader=reader,
                supplementary_groups=(),
                deadline_monotonic=time.monotonic() + 1.0,
            )
            source = sealed.prepare_read_only_bind(
                deadline_monotonic=time.monotonic() + 1.0
            ).source
            original_spawn = file_io.os.posix_spawn
            def spawn_stopped(*args, **kwargs):
                child = original_spawn(*args, **kwargs)
                os.kill(child, signal.SIGSTOP)
                return child
            file_io.os.posix_spawn = spawn_stopped
            file_io._waitid_pidfd_nonblocking = lambda _pidfd: False
            started = time.monotonic()
            try:
                source.verify_readback(deadline_monotonic=started + 0.020)
            except ProtocolDeadlineExceeded as exc:
                error = type(exc).__name__
            else:
                error = None
            entries = file_io.quarantined_file_io()
            owner = source._owner
            print(json.dumps({
                "elapsed": time.monotonic() - started,
                "error": error,
                "owner_quarantined": owner._read_io.is_quarantined,
                "quarantined": len(entries),
                "same_descriptor": (
                    len(entries) == 1 and entries[0].descriptor == owner._readonly_fd
                ),
            }))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        cwd=Path.cwd(),
        text=True,
        timeout=5,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result["elapsed"] < 0.150
    assert result["error"] == "ProtocolDeadlineExceeded"
    assert result["owner_quarantined"] is True
    assert result["quarantined"] == 1
    assert result["same_descriptor"] is True


@pytest.mark.parametrize(
    "corruption",
    ["zero_count_full_body", "smaller_count_full_body", "larger_count_short_body", "valid_eof"],
)
def test_read_ack_requires_exact_body_count_before_cursor_advances(corruption: str) -> None:
    script = textwrap.dedent(f"""
        import json, os, tempfile, time
        from pathlib import Path
        import ksi_processing_controller.external_inspector_file_io as module
        from ksi_processing_controller.external_inspector_protocol import ProtocolDeadline
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact"
            path.write_bytes(b"" if {corruption!r} == "valid_eof" else b"abc")
            fd = os.open(path, os.O_RDONLY)
            io = module.BoundedFileIo(descriptor=fd, maximum_bytes=8)
            original = io._receive_frame
            def receive(*args, **kwargs):
                reply = original(*args, **kwargs)
                fields = list(module._FRAME_HEADER.unpack(reply[:module._FRAME_HEADER.size]))
                if fields[2] != int(module._Operation.READ): return reply
                body = reply[module._FRAME_HEADER.size:]
                if {corruption!r} == "zero_count_full_body": fields[4] = 0
                elif {corruption!r} == "smaller_count_full_body": fields[4] = 1
                elif {corruption!r} == "larger_count_short_body": body = body[:1]
                return module._FRAME_HEADER.pack(*fields) + body
            io._receive_frame = receive
            error = None
            try:
                result = io.read_chunk(
                    3, deadline=ProtocolDeadline(1000, time.monotonic),
                    wait_is_current=lambda: True, heartbeat_interval_millis=10,
                )
            except module.InspectorFileIoUnavailable as exc:
                error = type(exc).__name__
            io.close()
            for entry in module.quarantined_file_io():
                os.waitpid(entry.pid, 0)
                if entry.pidfd is not None: os.close(entry.pidfd)
            os.close(fd)
            print(json.dumps({{"error": error, "offset": io._offset}}))
    """)
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=5
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "error": None if corruption == "valid_eof" else "InspectorFileIoUnavailable",
        "offset": 0,
    }


def test_pidfd_open_failure_retains_spawned_child_and_closes_admission() -> None:
    script = textwrap.dedent("""
        import errno, json, os, tempfile, time
        from pathlib import Path
        import ksi_processing_controller.external_inspector_file_io as module
        from ksi_processing_controller.external_inspector_protocol import ProtocolDeadline
        original_waitpid = os.waitpid
        def unavailable(pid): raise OSError(errno.EMFILE, "fixture")
        module._pidfd_open = unavailable
        os.waitpid = lambda pid, flags: (0, 0)
        with tempfile.TemporaryDirectory() as directory:
            fd = os.open(Path(directory) / "artifact", os.O_RDWR | os.O_CREAT, 0o600)
            io = module.BoundedFileIo(descriptor=fd, maximum_bytes=8)
            try:
                io.write_chunk(
                    b"x", deadline=ProtocolDeadline(100, time.monotonic),
                    wait_is_current=lambda: True, heartbeat_interval_millis=5,
                )
            except module.InspectorFileIoUnavailable: pass
            entries = module.quarantined_file_io()
            assert len(entries) == 1, "spawned child ownership was lost"
            assert entries[0].pid > 0 and entries[0].pidfd is None
            assert entries[0].descriptor is None, "no file FD was sent before pidfd acquisition"
            assert io.is_quarantined and io.written_bytes == 0
            try:
                module.BoundedFileIo(descriptor=fd, maximum_bytes=8)
            except module.InspectorFileIoUnavailable: pass
            else: raise AssertionError("new admission stayed open")
            os.waitpid = original_waitpid
            # Test owner reaps the exact retained helper after control EOF; no PID signal.
            assert os.waitpid(entries[0].pid, 0)[0] == entries[0].pid
            os.close(fd)
            print("retained and reaped")
    """)
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=5
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "retained and reaped"
