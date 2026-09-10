"""V2 daemon preflight keeps malformed configuration outside the runtime graph."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any, cast

import pytest
from test_external_measurement_operator_config import measurement_operator_config


class _HostProof:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self._fail = fail

    def verify_startup(self) -> None:
        self.calls += 1
        if self._fail:
            raise RuntimeError("host proof rejected")


class _GraphAssemblyInterrupted(BaseException):
    pass


class _GraphBoundaryPorts:
    """Explicit no-host ports: the concrete graph must not contact host services here."""

    def __init__(self) -> None:
        self.cgroups = object()
        self.systemd_manager = object()
        self.engine_client = object()
        self.proc_cgroups = object()


class _RecordingJournal:
    def __init__(self, path: Path) -> None:
        from ksi_processing_controller.external_measurement_attempts import (
            MeasurementAttemptJournalV2,
        )

        self._journal = MeasurementAttemptJournalV2(path)
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        self._journal.close()

    def __getattr__(self, name: str) -> object:
        return getattr(self._journal, name)


class _JournalFactory:
    def __init__(self) -> None:
        self.created: _RecordingJournal | None = None

    def __call__(self, path: Path) -> _RecordingJournal:
        self.created = _RecordingJournal(path)
        return self.created


class _GraphHostProof:
    def verify_startup(self) -> None:
        return None

    def verify_connected(self, *_args: object, **_kwargs: object) -> None:
        return None

    def prove(self, **_kwargs: object) -> object:
        raise AssertionError("a constructor test must not execute a runtime")


def _owned_listener(path: Path) -> socket.socket:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    listener.listen(4)
    path.chmod(0o600)
    return listener


def _activated_distinct_worker_listener(
    _tmp_path: Path, name: str, worker_uid: int
) -> tuple[socket.socket, Path, Path]:
    """Create an owned path that has the production distinct-UID ACL shape."""
    del name  # AF_UNIX pathname limit is part of the real listener boundary.
    root = Path(tempfile.mkdtemp(prefix="lacl-measure-", dir="/tmp"))
    root.chmod(0o700)
    subprocess.run(("setfacl", "-b", os.fspath(root)), check=True, capture_output=True)
    subprocess.run(("setfacl", "-k", os.fspath(root)), check=True, capture_output=True)
    subprocess.run(
        ("setfacl", "-m", f"u:{worker_uid}:x", os.fspath(root)),
        check=True,
        capture_output=True,
    )
    parent = root / "p"
    parent.mkdir(mode=0o700)
    subprocess.run(("setfacl", "-b", os.fspath(parent)), check=True, capture_output=True)
    subprocess.run(("setfacl", "-k", os.fspath(parent)), check=True, capture_output=True)
    subprocess.run(
        ("setfacl", "-m", f"u:{worker_uid}:x", os.fspath(parent)),
        check=True,
        capture_output=True,
    )
    path = parent / "s"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    listener.listen(4)
    path.chmod(0o600)
    subprocess.run(("setfacl", "-b", os.fspath(path)), check=True, capture_output=True)
    subprocess.run(
        ("setfacl", "-m", f"u:{worker_uid}:rw", os.fspath(path)),
        check=True,
        capture_output=True,
    )
    return listener, path, root


def test_production_graph_uses_real_backend_empty_recovery_and_one_primary_accounting(
    tmp_path: Path,
) -> None:
    from ksi_processing_controller.external_inspector_daemon import ActivatedListenerReceipt
    from ksi_processing_controller.external_measurement_daemon import (
        MeasurementDaemonBoundaryPorts,
        build_production_measurement_daemon,
    )
    from ksi_processing_controller.external_measurement_docker_backend import (
        DockerMeasurementBackend,
    )
    from ksi_processing_controller.external_measurement_operator_config import (
        load_external_measurement_operator_config,
    )

    config = load_external_measurement_operator_config(measurement_operator_config(tmp_path))
    listener = _owned_listener(tmp_path / "graph.sock")
    journals = _JournalFactory()
    ports = _GraphBoundaryPorts()
    try:
        daemon = build_production_measurement_daemon(
            config=config.production,
            host_proof=cast(Any, _GraphHostProof()),
            activated_listener=ActivatedListenerReceipt(listener=listener, preaccepted=deque()),
            boundary_ports=MeasurementDaemonBoundaryPorts(
                cgroups=ports.cgroups,
                systemd_manager=ports.systemd_manager,
                engine_client=ports.engine_client,
                proc_cgroups=ports.proc_cgroups,
                journal_factory=cast(Any, journals),
            ),
        )
        assert isinstance(daemon._launcher._backend, DockerMeasurementBackend)
        assert config.production.primary_root.is_dir()
        assert journals.created is not None
        assert journals.created.close_calls == 0
        accounting = daemon._launcher._accounting
        reservation = accounting.reserve(
            request_units=1,
            concurrency_units=1,
            spool_bytes=1_024,
            deadline_monotonic=1.0,
        )
        assert reservation is not None
        assert (
            accounting.reserve(
                request_units=1,
                concurrency_units=1,
                spool_bytes=1,
                deadline_monotonic=1.0,
            )
            is None
        )
        reservation.release()
        daemon.close()
        daemon.close()
    finally:
        listener.close()

    assert journals.created is not None
    assert journals.created.close_calls == 1
    assert listener.fileno() == -1


def test_graph_baseexception_after_assembly_closes_owned_journal_and_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_processing_controller import external_measurement_daemon
    from ksi_processing_controller.external_inspector_daemon import ActivatedListenerReceipt
    from ksi_processing_controller.external_measurement_daemon import (
        MeasurementDaemonBoundaryPorts,
        build_production_measurement_daemon,
    )
    from ksi_processing_controller.external_measurement_operator_config import (
        load_external_measurement_operator_config,
    )

    config = load_external_measurement_operator_config(measurement_operator_config(tmp_path))
    listener = _owned_listener(tmp_path / "graph-failure.sock")
    journals = _JournalFactory()
    ports = _GraphBoundaryPorts()

    def interrupted(**_kwargs: object) -> object:
        raise _GraphAssemblyInterrupted("graph construction interrupted")

    monkeypatch.setattr(
        external_measurement_daemon.ExternalMeasurementSystemdDaemon,
        "from_systemd_activation",
        classmethod(lambda _cls, **kwargs: interrupted(**kwargs)),
    )
    with pytest.raises(_GraphAssemblyInterrupted, match="graph construction interrupted"):
        build_production_measurement_daemon(
            config=config.production,
            host_proof=cast(Any, _GraphHostProof()),
            activated_listener=ActivatedListenerReceipt(listener=listener, preaccepted=deque()),
            boundary_ports=MeasurementDaemonBoundaryPorts(
                cgroups=ports.cgroups,
                systemd_manager=ports.systemd_manager,
                engine_client=ports.engine_client,
                proc_cgroups=ports.proc_cgroups,
                journal_factory=cast(Any, journals),
            ),
        )

    assert journals.created is not None
    assert journals.created.close_calls == 1
    assert listener.fileno() == -1


def test_daemon_serves_retained_uds_connection_and_closes_once(tmp_path: Path) -> None:
    from ksi_processing_controller.external_inspector_daemon import (
        SystemdActivatedListenerConfigV1,
        prove_activated_listener,
    )
    from ksi_processing_controller.external_listener_acl import ListenerAclUnavailable
    from ksi_processing_controller.external_measurement_daemon import (
        ExternalMeasurementSystemdDaemon,
        MeasurementDaemonUnavailable,
    )

    listener = _owned_listener(tmp_path / "serve.sock")
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(os.fspath(tmp_path / "serve.sock"))
    received: list[socket.socket] = []

    class Launcher:
        def handle_connection(self, value: socket.socket) -> None:
            received.append(value)
            value.close()

    receipt = prove_activated_listener(
        listener,
        SystemdActivatedListenerConfigV1(tmp_path / "serve.sock", os.geteuid()),
        required_worker_uid=os.geteuid(),
        deadline_monotonic=time.monotonic() + 0.5,
    )
    daemon = ExternalMeasurementSystemdDaemon(
        listener=receipt.listener,
        launcher=cast(Any, Launcher()),
        preaccepted=receipt.preaccepted,
        activated_listener=receipt,
        proof_timeout_millis=500,
    )
    try:
        daemon.serve_once()
        assert len(received) == 1
        assert client.recv(1) == b""
        client.close()
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(os.fspath(tmp_path / "serve.sock"))
        (tmp_path / "serve.sock").chmod(0o606)
        with pytest.raises(ListenerAclUnavailable):
            daemon.serve_once()
        assert len(received) == 1
        assert client.recv(1) == b""
        daemon.close()
        daemon.close()
        with pytest.raises(MeasurementDaemonUnavailable):
            daemon.serve_once()
    finally:
        client.close()
        listener.close()


def test_measurement_daemon_closes_queued_startup_connections_on_listener_drift(
    tmp_path: Path,
) -> None:
    from ksi_processing_controller.external_inspector_daemon import (
        SystemdActivatedListenerConfigV1,
        prove_activated_listener,
    )
    from ksi_processing_controller.external_listener_acl import ListenerAclUnavailable
    from ksi_processing_controller.external_measurement_daemon import (
        ExternalMeasurementSystemdDaemon,
    )

    path = tmp_path / "queued-drift.sock"
    listener = _owned_listener(path)
    clients = [socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) for _ in range(2)]
    receipt = None
    daemon = None

    class Launcher:
        def handle_connection(self, connection: socket.socket) -> None:
            raise AssertionError("listener drift must reject before measurement dispatch")

    try:
        for client in clients:
            client.connect(os.fspath(path))
            client.settimeout(0.5)
        receipt = prove_activated_listener(
            listener,
            SystemdActivatedListenerConfigV1(path, os.geteuid()),
            required_worker_uid=os.geteuid(),
            deadline_monotonic=time.monotonic() + 0.5,
        )
        assert len(receipt.preaccepted) == 2
        daemon = ExternalMeasurementSystemdDaemon(
            listener=receipt.listener,
            launcher=cast(Any, Launcher()),
            preaccepted=receipt.preaccepted,
            activated_listener=receipt,
            proof_timeout_millis=500,
        )
        path.chmod(0o606)
        with pytest.raises(ListenerAclUnavailable):
            daemon.serve_once()
        assert all(client.recv(1) == b"" for client in clients)
        assert listener.fileno() == -1
    finally:
        if daemon is not None:
            daemon.close()
        elif receipt is not None:
            receipt.close()
        listener.close()
        for client in clients:
            client.close()


def test_cli_closes_assembled_daemon_when_serve_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_processing_controller import external_inspector_host_proof, external_measurement_daemon

    config_path = measurement_operator_config(tmp_path)
    events: list[str] = []

    class HostProof:
        pass

    class Daemon:
        def serve_forever(self) -> None:
            events.append("serve")
            raise KeyboardInterrupt("shutdown")

        def close(self) -> None:
            events.append("close")

    monkeypatch.setattr(
        external_inspector_host_proof,
        "RootlessDockerHostProofV1",
        lambda *_args, **_kwargs: HostProof(),
    )
    monkeypatch.setattr(
        external_measurement_daemon,
        "build_daemon_from_measurement_operator_config",
        lambda _config, **_kwargs: Daemon(),
    )

    with pytest.raises(KeyboardInterrupt, match="shutdown"):
        external_measurement_daemon.main(["--config", os.fspath(config_path)])
    assert events == ["serve", "close"]


def test_bad_host_proof_prevents_artifact_listener_and_runtime_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_processing_controller import (
        external_measurement_daemon,
        external_measurement_operator_config,
    )
    from ksi_processing_controller.external_measurement_daemon import (
        MeasurementDaemonUnavailable,
        build_daemon_from_measurement_operator_config,
    )
    from ksi_processing_controller.external_measurement_operator_config import (
        load_external_measurement_operator_config,
    )

    config = load_external_measurement_operator_config(measurement_operator_config(tmp_path))
    host_proof = _HostProof(fail=True)
    artifacts: list[object] = []
    listener_calls: list[dict[str, object]] = []
    builders: list[object] = []

    def artifact_validation(value: object) -> None:
        artifacts.append(value)

    def builder(**kwargs: object) -> object:
        builders.append(kwargs)
        raise AssertionError("bad host proof must not build a runtime graph")

    def listener(**_kwargs: object) -> object:
        listener_calls.append(_kwargs)
        raise AssertionError("bad host proof must not acquire a listener")

    monkeypatch.setattr(
        external_measurement_operator_config,
        "validate_measurement_operator_startup_artifacts",
        artifact_validation,
    )
    monkeypatch.setattr(external_measurement_daemon, "verify_systemd_activated_listener", listener)

    with pytest.raises(MeasurementDaemonUnavailable):
        build_daemon_from_measurement_operator_config(
            config,
            host_proof=cast(Any, host_proof),
            daemon_builder=cast(Any, builder),
            environment={},
        )
    assert host_proof.calls == 1
    assert artifacts == []
    assert listener_calls == []
    assert builders == []


@pytest.mark.parametrize(
    ("artifact_name", "replacement"),
    [
        ("measurement-manifest.json", b"not a manifest"),
        ("measurement-oci-pairs.json", b"not OCI evidence"),
    ],
)
def test_bad_catalog_or_oci_after_host_proof_does_not_open_listener_or_runtime_graph(
    tmp_path: Path,
    artifact_name: str,
    replacement: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ksi_processing_controller import external_measurement_daemon
    from ksi_processing_controller.external_measurement_daemon import (
        MeasurementDaemonUnavailable,
        build_daemon_from_measurement_operator_config,
    )
    from ksi_processing_controller.external_measurement_operator_config import (
        load_external_measurement_operator_config,
    )

    config_path = measurement_operator_config(tmp_path)
    config = load_external_measurement_operator_config(config_path)
    artifact_path = tmp_path / artifact_name
    artifact_path.write_bytes(replacement)
    artifact_path.chmod(0o600)
    host_proof = _HostProof()
    listener_calls: list[dict[str, object]] = []
    builders: list[object] = []

    def listener(**kwargs: object) -> object:
        listener_calls.append(kwargs)
        raise AssertionError("bad catalog or OCI evidence must not acquire a listener")

    def builder(**kwargs: object) -> object:
        builders.append(kwargs)
        raise AssertionError("bad catalog or OCI evidence must not build a runtime graph")

    monkeypatch.setattr(external_measurement_daemon, "verify_systemd_activated_listener", listener)

    with pytest.raises(MeasurementDaemonUnavailable):
        build_daemon_from_measurement_operator_config(
            config,
            host_proof=cast(Any, host_proof),
            daemon_builder=cast(Any, builder),
            environment={},
        )
    assert host_proof.calls == 1
    assert listener_calls == []
    assert builders == []


def test_preflight_retains_real_activated_listener_until_graph_takes_ownership(
    tmp_path: Path,
) -> None:
    from ksi_processing_controller.external_measurement_daemon import (
        build_daemon_from_measurement_operator_config,
    )
    from ksi_processing_controller.external_measurement_operator_config import (
        load_external_measurement_operator_config,
    )

    listener, listener_path, root = _activated_distinct_worker_listener(
        tmp_path, "measurement.sock", os.geteuid() + 10_000
    )
    config = load_external_measurement_operator_config(
        measurement_operator_config(tmp_path, listener_path=listener_path)
    )
    host_proof = _HostProof()
    received: list[dict[str, Any]] = []
    sentinel = object()

    def builder(**kwargs: object) -> object:
        received.append(kwargs)
        receipt = cast(Any, kwargs["activated_listener"])
        assert receipt.listener.getsockname() == os.fspath(listener_path)
        receipt.close()
        return sentinel

    try:
        try:
            original_fd3 = os.dup(3)
        except OSError:
            original_fd3 = -1
        try:
            os.dup2(listener.fileno(), 3)
            assembled = build_daemon_from_measurement_operator_config(
                config,
                host_proof=cast(Any, host_proof),
                daemon_builder=cast(Any, builder),
                environment={"LISTEN_PID": str(os.getpid()), "LISTEN_FDS": "1"},
            )
        finally:
            if original_fd3 >= 0:
                os.dup2(original_fd3, 3)
                os.close(original_fd3)
            else:
                os.close(3)
    finally:
        listener.close()
        shutil.rmtree(root)

    assert assembled is sentinel
    assert host_proof.calls == 1
    assert len(received) == 1


@pytest.mark.parametrize(
    "failure_type", [RuntimeError, _GraphAssemblyInterrupted, KeyboardInterrupt]
)
def test_graph_failure_closes_owned_activated_listener_receipt(
    tmp_path: Path, failure_type: type[BaseException]
) -> None:
    from ksi_processing_controller.external_measurement_daemon import (
        build_daemon_from_measurement_operator_config,
    )
    from ksi_processing_controller.external_measurement_operator_config import (
        load_external_measurement_operator_config,
    )

    listener, listener_path, root = _activated_distinct_worker_listener(
        tmp_path, "measurement-failure.sock", os.geteuid() + 10_000
    )
    config = load_external_measurement_operator_config(
        measurement_operator_config(tmp_path, listener_path=listener_path)
    )
    receipts: list[Any] = []

    def builder(**kwargs: object) -> object:
        receipts.append(kwargs["activated_listener"])
        raise failure_type("graph construction failed")

    try:
        try:
            original_fd3 = os.dup(3)
        except OSError:
            original_fd3 = -1
        try:
            os.dup2(listener.fileno(), 3)
            with pytest.raises(failure_type, match="graph construction failed"):
                build_daemon_from_measurement_operator_config(
                    config,
                    host_proof=cast(Any, _HostProof()),
                    daemon_builder=cast(Any, builder),
                    environment={"LISTEN_PID": str(os.getpid()), "LISTEN_FDS": "1"},
                )
        finally:
            if original_fd3 >= 0:
                os.dup2(original_fd3, 3)
                os.close(original_fd3)
            else:
                os.close(3)
    finally:
        listener.close()
        shutil.rmtree(root)

    assert len(receipts) == 1
    assert receipts[0].listener.fileno() == -1


def test_cli_rejects_relative_config_path_before_constructing_host_proof() -> None:
    from ksi_processing_controller.external_measurement_daemon import (
        MeasurementDaemonUnavailable,
        main,
    )

    with pytest.raises(MeasurementDaemonUnavailable):
        main(["--config", "relative-config.json"])
