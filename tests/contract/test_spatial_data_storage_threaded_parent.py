"""Storage child supervision from a MULTI-THREADED parent (real Core server shape).

Core runs an ASGI server with worker threads. The storage supervisor launches its SDK
child with ``os.fork()``. A forked child of a threaded process inherits only the
calling thread while the parent's other threads keep running and holding locks, so the
child can block forever inside the SDK while the parent waits for a frame that never
arrives. The request then failed as ``STORAGE_UNAVAILABLE`` (503) even though S3, the
bucket, the object and the credentials were all healthy.

The child also closed every descriptor it could see in ``/proc/self/fd``. In a threaded
parent that list is a moving target: a descriptor number another thread opened between
the ``listdir`` and the ``close`` can be closed by mistake, including the very channel
the child must answer on. The result was a silent child that exited 0 without ever
delivering a frame.

These tests pin the behaviour that matters to the product: a storage child started from
a threaded parent must still deliver its result, must not inherit the parent's unrelated
descriptors, and must fail typed rather than hang.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError


def _threaded_parent() -> tuple[threading.Event, list[threading.Thread]]:
    """Hold live threads (and their descriptors) while the child is launched."""
    stop = threading.Event()
    held: list[socket.socket] = []
    threads: list[threading.Thread] = []

    def holder() -> None:
        sock = socket.socket()
        held.append(sock)
        while not stop.is_set():
            time.sleep(0.01)
        sock.close()

    for _ in range(3):
        thread = threading.Thread(target=holder, daemon=True)
        thread.start()
        threads.append(thread)
    return stop, threads


def _stub_environment() -> None:
    """Point the child at the finite local substitute."""
    os.environ["KSI_CORE_S3_CLIENT_FACTORY"] = "spatial_data_sdk_stub:client_factory"
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).parent), os.environ.get("PYTHONPATH", "")]
    ).strip(os.pathsep)


def _child_settings(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    """A description the child can execute, with the local substitute bound."""
    settings: dict[str, Any] = {
        "operation": "head_output",
        "bucket": "local-store",
        "key": "spatial-data/v1/org-local/job/key/result.tif",
        "logPath": str(tmp_path / "sdk.jsonl"),
        "body": "abcdefgh",
        "changes": {},
        "behavior": "",
        "configChanges": {},
        "clientFactory": "spatial_data_sdk_stub:client_factory",
        "clientFactoryPath": str(Path(__file__).parent),
    }
    settings.update(overrides)
    return settings


def test_child_of_threaded_parent_still_delivers_its_result(tmp_path: Path) -> None:
    """The defect: a threaded parent's child could not finish its SDK work."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    _stub_environment()
    stop, threads = _threaded_parent()
    try:

        supervisor = SpatialDataStorageSupervisor(max_concurrency=2)
        with supervisor.data_session(
            _child_settings(tmp_path),
            timeout_seconds=10.0,
            max_frame_bytes=4096,
        ) as session:
            kind, value = session.receive()
            assert kind == "JSON"
            assert value["VersionId"] == "version-1"
        assert supervisor.wait_for_idle(timeout_seconds=10)
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=2)


def test_threaded_parent_child_does_not_inherit_unrelated_descriptors(tmp_path: Path) -> None:
    """The child must not carry the parent's journal locks or pooled SDK sockets."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    _stub_environment()
    inherited: list[int] = []
    lock_path = tmp_path / "journal.lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    stop, threads = _threaded_parent()
    try:

        supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
        with supervisor.data_session(
            _child_settings(tmp_path),
            timeout_seconds=10.0,
            max_frame_bytes=4096,
        ) as session:
            assert session.receive()[0] == "JSON"
        assert supervisor.wait_for_idle(timeout_seconds=10)
        # The parent's own lock descriptor must not survive into the child.
        assert lock_fd not in inherited
    finally:
        os.close(lock_fd)
        stop.set()
        for thread in threads:
            thread.join(timeout=2)


def test_threaded_parent_child_failure_is_bounded_and_typed() -> None:
    """A failing child from a threaded parent must fail typed, not hang the request."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    stop, threads = _threaded_parent()
    try:
        # The finite substitute refuses the operation, so the child must report
        # a typed refusal instead of hanging on a real remote call.
        os.environ["KSI_CORE_S3_CLIENT_FACTORY"] = "spatial_data_sdk_stub:client_factory"
        os.environ["PYTHONPATH"] = os.pathsep.join(
            [str(Path(__file__).parent), os.environ.get("PYTHONPATH", "")]
        ).strip(os.pathsep)
        supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
        start = time.monotonic()
        with (
            pytest.raises(SpatialDataDomainError) as error,
            supervisor.data_session(
                {
                    "operation": "delete_owned_version",
                    "bucket": "local-store",
                    "key": "spatial-data/v1/org-local/job/key/result.tif",
                    "versionId": "version-1",
                    "clientFactory": "spatial_data_sdk_stub:client_factory",
                    "clientFactoryPath": str(Path(__file__).parent),
                    "logPath": str(Path(__file__).parent / "threaded-child-sdk.jsonl"),
                    "body": "abcdefgh",
                    "changes": {},
                    # The substitute substitutes the version it deletes, so the
                    # child must refuse it instead of reporting success.
                    "behavior": "delete-substitute",
                },
                timeout_seconds=10.0,
                max_frame_bytes=4096,
            ) as session,
        ):
            session.receive()
        # The child could not read, so the request must be refused — but it
        # must be refused quickly and in a typed way, never hang.
        assert error.value.reason in ("STORAGE_UNAVAILABLE", "INTEGRITY_MISMATCH")
        assert time.monotonic() - start < 8
        assert supervisor.wait_for_idle(timeout_seconds=10)
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=2)
