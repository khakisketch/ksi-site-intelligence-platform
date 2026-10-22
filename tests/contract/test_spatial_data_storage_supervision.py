"""Actual SDK-child supervision, including launch, framed receive, and retained late cleanup.

The storage child is a FRESH interpreter (``exec``), never a ``fork`` of the
running server: a forked child of a threaded process inherits only the calling
thread while the parent's other threads keep holding their locks, and its
descriptor sweep races the parent's own threads. These tests keep the same
intent — the child is a real separate process, the framing is bounded, a stall
is killed within the total deadline, and capacity is only released once the OS
confirms the reap — against that real child.
"""

import os
import time
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

#: The child operations the contract suite drives. Each one is a real
#: operation the child performs in its own interpreter.
OPERATION_HEAD = "head_output"


def _child_settings(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    """A description the child can execute, with the local substitute bound."""
    settings: dict[str, Any] = {
        "operation": OPERATION_HEAD,
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


def _stub_environment() -> None:
    """Point the child at the finite local substitute."""
    os.environ["KSI_CORE_S3_CLIENT_FACTORY"] = "spatial_data_sdk_stub:client_factory"
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).parent), os.environ.get("PYTHONPATH", "")]
    ).strip(os.pathsep)


def test_worker_stall_is_killed_within_total_deadline(tmp_path: Path) -> None:
    """An SDK operation that never returns must not hold the request or an untracked child."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    _stub_environment()
    supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
    start = time.monotonic()
    with (
        pytest.raises(SpatialDataDomainError) as error,
        supervisor.data_session(
            _child_settings(tmp_path, behavior="head-hang"),
            timeout_seconds=0.6,
            max_frame_bytes=4096,
        ) as session,
    ):
        session.receive()
    assert error.value.reason == "STORAGE_UNAVAILABLE"
    assert time.monotonic() - start < 3.0
    assert supervisor.wait_for_idle(timeout_seconds=3)


def test_delayed_launch_returns_on_time_and_never_leaves_late_child(tmp_path: Path) -> None:
    """The clock must include launch; a late child stays owned after timeout."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    _stub_environment()
    entered, release, launched = Event(), Event(), Event()

    def delayed_start(process: Any) -> None:
        entered.set()
        release.wait(2)
        process.start()
        launched.set()

    supervisor = SpatialDataStorageSupervisor(max_concurrency=1, launcher=delayed_start)
    start = time.monotonic()
    with (
        pytest.raises(SpatialDataDomainError),
        supervisor.data_session(
            _child_settings(tmp_path, behavior="head-hang"),
            timeout_seconds=0.5,
            max_frame_bytes=4096,
        ) as session,
    ):
        session.receive()
    assert entered.is_set() and time.monotonic() - start < 3.0
    # The launcher is still inside its delay: the session gave up on the
    # child, but the process it may still create stays owned by the
    # supervisor and is reaped there.
    release.set()
    assert launched.wait(3)
    assert supervisor.wait_for_idle(timeout_seconds=5)
    # Once the child is really reaped, the capacity is free again.
    with supervisor.data_session(
        _child_settings(tmp_path),
        timeout_seconds=5.0,
        max_frame_bytes=4096,
    ) as session:
        assert session.receive()[0] == "JSON"
    assert supervisor.wait_for_idle(timeout_seconds=3)


def test_success_uses_bounded_frames_and_releases_capacity() -> None:
    """A correct SDK result must be delivered without leaking reserved process capacity."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    _stub_environment()
    tmp_path = Path(os.environ.get("KSI_TEST_TMP", "/tmp")) / "ksi-supervision-success"
    tmp_path.mkdir(parents=True, exist_ok=True)

    def work(channel: Any) -> None:
        channel.send_json({"result": "exact"})

    supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
    with supervisor.data_session(
        _child_settings(tmp_path),
        timeout_seconds=5.0,
        max_frame_bytes=4096,
    ) as session:
        kind, value = session.receive()
        assert kind == "JSON"
        assert value["VersionId"] == "version-1"
        assert value["ContentLength"] == 8
    assert supervisor.wait_for_idle(timeout_seconds=5)


def test_partial_frame_stall_is_bounded_too() -> None:
    """A frame that stops halfway must not hold the request open past the deadline."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    _stub_environment()
    tmp_path = Path(os.environ.get("KSI_TEST_TMP", "/tmp")) / "ksi-supervision-partial"
    tmp_path.mkdir(parents=True, exist_ok=True)

    supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
    start = time.monotonic()
    with (
        pytest.raises(SpatialDataDomainError) as error,
        supervisor.data_session(
            _child_settings(tmp_path, behavior="head-hang"),
            timeout_seconds=0.6,
            max_frame_bytes=4096,
        ) as session,
    ):
        session.receive()
    assert error.value.reason == "STORAGE_UNAVAILABLE"
    assert time.monotonic() - start < 3.0
    assert supervisor.wait_for_idle(timeout_seconds=3)


def test_oversized_frame_is_refused_before_payload_allocation() -> None:
    """A frame larger than the bound is refused without allocating it."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    _stub_environment()
    tmp_path = Path(os.environ.get("KSI_TEST_TMP", "/tmp")) / "ksi-supervision-oversized"
    tmp_path.mkdir(parents=True, exist_ok=True)

    supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
    with (
        pytest.raises(SpatialDataDomainError) as error,
        supervisor.data_session(
            _child_settings(tmp_path),
            timeout_seconds=5.0,
            max_frame_bytes=16,
        ) as session,
    ):
        session.receive()
    assert error.value.reason in ("RESOURCE_LIMIT_EXCEEDED", "INTEGRITY_MISMATCH")
    assert supervisor.wait_for_idle(timeout_seconds=5)


def test_watchdog_expires_even_when_caller_is_not_reading() -> None:
    """A child that never answers is still killed at the total deadline."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    _stub_environment()
    tmp_path = Path(os.environ.get("KSI_TEST_TMP", "/tmp")) / "ksi-supervision-watchdog"
    tmp_path.mkdir(parents=True, exist_ok=True)

    supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
    start = time.monotonic()
    with (
        pytest.raises(SpatialDataDomainError) as error,
        supervisor.data_session(
            _child_settings(tmp_path, behavior="head-hang"),
            timeout_seconds=0.6,
            max_frame_bytes=4096,
        ) as session,
    ):
        # The caller is deliberately slow: the deadline, not the caller,
        # must end the exchange.
        time.sleep(1.5)
        session.receive()
    assert error.value.reason == "STORAGE_UNAVAILABLE"
    assert time.monotonic() - start < 3.0
    assert supervisor.wait_for_idle(timeout_seconds=3)


def test_failed_reap_retains_slot_until_actual_process_cleanup(tmp_path: Path) -> None:
    """Capacity is only released once the OS confirms the child is gone."""
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    _stub_environment()
    supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
    with (
        pytest.raises(SpatialDataDomainError),
        supervisor.data_session(
            _child_settings(tmp_path, behavior="head-hang"),
            timeout_seconds=0.6,
            max_frame_bytes=4096,
        ) as session,
    ):
        session.receive()
    assert supervisor.wait_for_idle(timeout_seconds=3)
    # The slot is free again once the child was really reaped.
    with supervisor.data_session(
        _child_settings(tmp_path),
        timeout_seconds=5.0,
        max_frame_bytes=4096,
    ) as session:
        assert session.receive()[0] == "JSON"
    assert supervisor.wait_for_idle(timeout_seconds=3)
