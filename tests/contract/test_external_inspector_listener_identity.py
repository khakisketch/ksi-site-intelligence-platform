"""Real Unix sockets prove pathname binding without comparing sockfs to disk inode."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from ksi_processing_controller.external_inspector_daemon import (
    InspectorDaemonUnavailable,
    SystemdActivatedListenerConfigV1,
    prove_activated_listener,
)
from ksi_processing_controller.external_listener_acl import ListenerAclUnavailable


def _worker_uid() -> int:
    return 65_534 if os.geteuid() != 65_534 else 65_533


def _other_uid(worker_uid: int) -> int:
    return 65_533 if worker_uid != 65_533 else 65_532


def _setfacl(path: Path, *arguments: str) -> None:
    subprocess.run(("setfacl", *arguments, os.fspath(path)), check=True, capture_output=True)


def _distinct_worker_listener(_tmp_path: Path) -> tuple[socket.socket, Path, int, Path]:
    """Create only this test's named-UID socket and private traversal parent."""
    worker_uid = _worker_uid()
    root = Path(tempfile.mkdtemp(prefix="lacl-distinct-", dir="/tmp"))
    root.chmod(0o700)
    _setfacl(root, "-b")
    _setfacl(root, "-k")
    _setfacl(root, "-m", f"u:{worker_uid}:x")
    parent = root / "p"
    parent.mkdir(mode=0o700)
    _setfacl(parent, "-b")
    _setfacl(parent, "-k")
    _setfacl(parent, "-m", f"u:{worker_uid}:x")
    path = parent / "listener"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    listener.listen(8)
    path.chmod(0o600)
    _setfacl(path, "-b")
    _setfacl(path, "-m", f"u:{worker_uid}:rw")
    return listener, path, worker_uid, root


def _short_distinct_listener_root(
    *, worker_uid: int, root_mode: int, acl_entry: str | None = None
) -> tuple[socket.socket, Path, Path]:
    """Use `/tmp` directly so every pre-boundary component is part of the proof."""
    root = Path(tempfile.mkdtemp(prefix="lacl-worker-", dir="/tmp"))
    root.chmod(root_mode)
    _setfacl(root, "-b")
    _setfacl(root, "-k")
    if acl_entry is not None:
        _setfacl(root, "-m", acl_entry)
    parent = root / "p"
    parent.mkdir(mode=0o700)
    _setfacl(parent, "-b")
    _setfacl(parent, "-k")
    _setfacl(parent, "-m", f"u:{worker_uid}:x")
    path = parent / "s"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    listener.listen(4)
    path.chmod(0o600)
    _setfacl(path, "-b")
    _setfacl(path, "-m", f"u:{worker_uid}:rw")
    return listener, path, root


@pytest.mark.parametrize(
    ("root_mode", "acl_entry", "mask_denies"),
    [
        (0o700, None, False),
        (0o777, None, False),
        (0o701, "u:{worker}:---", False),
        (0o701, "u:{worker}:x", True),
        (0o701, "g:65534:wx", False),
    ],
)
def test_actual_preboundary_acl_rejects_unreachable_or_mutable_worker_path(
    root_mode: int, acl_entry: str | None, mask_denies: bool
) -> None:
    worker_uid = _worker_uid()
    listener, path, root = _short_distinct_listener_root(
        worker_uid=worker_uid,
        root_mode=root_mode,
        acl_entry=None if acl_entry is None else acl_entry.format(worker=worker_uid),
    )
    try:
        if mask_denies:
            _setfacl(root, "-m", "m::---")
        if acl_entry == "g:65534:wx":
            from ksi_processing_controller import external_listener_acl

            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                assert not external_listener_acl._worker_cannot_write(
                    external_listener_acl._anchored_directory_acl(
                        descriptor, external_listener_acl._ACL_ACCESS
                    ),
                    os.fstat(descriptor),
                    worker_uid,
                )
            finally:
                os.close(descriptor)
        with pytest.raises(InspectorDaemonUnavailable):
            prove_activated_listener(
                listener,
                SystemdActivatedListenerConfigV1(path, os.geteuid()),
                required_worker_uid=worker_uid,
                deadline_monotonic=time.monotonic() + 0.5,
            )
    finally:
        listener.close()
        shutil.rmtree(root)


def test_actual_named_group_mask_denial_keeps_unknown_worker_membership_safe() -> None:
    worker_uid = _worker_uid()
    listener, path, root = _short_distinct_listener_root(
        worker_uid=worker_uid,
        root_mode=0o701,
    )
    receipt = None
    try:
        _setfacl(root, "-m", "g::x")
        _setfacl(root, "-m", "g:65534:wx")
        _setfacl(root, "-m", "m::x")
        receipt = prove_activated_listener(
            listener,
            SystemdActivatedListenerConfigV1(path, os.geteuid()),
            required_worker_uid=worker_uid,
            deadline_monotonic=time.monotonic() + 0.5,
        )
        assert receipt.access_receipt is not None
    finally:
        if receipt is not None:
            receipt.close()
        listener.close()
        shutil.rmtree(root)


@pytest.mark.parametrize(
    ("root_mode", "acl_entry"),
    [
        (0o755, None),
        (0o700, "u:{worker}:x"),
    ],
)
def test_actual_safe_system_or_sticky_preboundary_allows_exact_distinct_listener(
    root_mode: int, acl_entry: str | None
) -> None:
    """The first fixture is /run-shaped; the second is a sticky-/tmp child."""
    worker_uid = _worker_uid()
    listener, path, root = _short_distinct_listener_root(
        worker_uid=worker_uid,
        root_mode=root_mode,
        acl_entry=None if acl_entry is None else acl_entry.format(worker=worker_uid),
    )
    receipt = None
    try:
        receipt = prove_activated_listener(
            listener,
            SystemdActivatedListenerConfigV1(path, os.geteuid()),
            required_worker_uid=worker_uid,
            deadline_monotonic=time.monotonic() + 0.5,
        )
        assert receipt.access_receipt is not None
    finally:
        if receipt is not None:
            receipt.close()
        listener.close()
        shutil.rmtree(root)


def test_directory_chain_closes_root_fd_when_initial_acl_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A root ACL read failure cannot strand the just-opened chain descriptor."""
    from ksi_processing_controller import external_listener_acl

    original_open = os.open
    original_fstat = os.fstat
    opened: list[int] = []

    def tracked_open(*args: object, **kwargs: object) -> int:
        descriptor = original_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def initial_acl_failure(*_args: object, **_kwargs: object) -> object:
        raise ListenerAclUnavailable("injected initial ACL failure")

    before = len(os.listdir("/proc/self/fd"))
    with monkeypatch.context() as patch:
        patch.setattr(external_listener_acl.os, "open", tracked_open)
        patch.setattr(external_listener_acl, "_anchored_directory_acl", initial_acl_failure)
        for _ in range(4):
            with pytest.raises(ListenerAclUnavailable, match="injected initial ACL failure"):
                external_listener_acl._open_safe_directory_chain(
                    Path("/tmp"), worker_uid=_worker_uid(), same_uid_fixture=False
                )
    retained = []
    for descriptor in set(opened):
        try:
            original_fstat(descriptor)
        except OSError:
            continue
        retained.append(descriptor)
    assert retained == []
    assert len(os.listdir("/proc/self/fd")) == before


def test_directory_chain_closes_child_fd_when_child_fstat_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child identity failure cannot strand either side of a chain handoff."""
    from ksi_processing_controller import external_listener_acl

    original_open = os.open
    original_fstat = os.fstat
    opened: list[int] = []

    def tracked_open(*args: object, **kwargs: object) -> int:
        descriptor = original_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def child_fstat_failure(descriptor: int) -> os.stat_result:
        if len(opened) >= 2 and descriptor == opened[-1]:
            raise OSError("injected child fstat failure")
        return original_fstat(descriptor)

    before = len(os.listdir("/proc/self/fd"))
    with monkeypatch.context() as patch:
        patch.setattr(external_listener_acl.os, "open", tracked_open)
        patch.setattr(external_listener_acl.os, "fstat", child_fstat_failure)
        for _ in range(4):
            with pytest.raises(OSError, match="injected child fstat failure"):
                external_listener_acl._open_safe_directory_chain(
                    Path("/tmp"), worker_uid=_worker_uid(), same_uid_fixture=False
                )
    retained = []
    for descriptor in set(opened):
        try:
            original_fstat(descriptor)
        except OSError:
            continue
        retained.append(descriptor)
    assert retained == []
    assert len(os.listdir("/proc/self/fd")) == before


def test_actual_distinct_worker_acl_proves_exact_socket_and_parent_rights(tmp_path: Path) -> None:
    """Removing the named reader grant must reject a real owner-created socket."""
    listener, path, worker_uid, root = _distinct_worker_listener(tmp_path)
    try:
        receipt = prove_activated_listener(
            listener,
            SystemdActivatedListenerConfigV1(path, os.geteuid()),
            required_worker_uid=worker_uid,
            deadline_monotonic=time.monotonic() + 1,
        )
        try:
            assert receipt.listener is listener
            assert not receipt.preaccepted
        finally:
            receipt.close()
    finally:
        listener.close()
        shutil.rmtree(root)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-worker",
        "extra-user",
        "extra-group",
        "group",
        "other",
        "mask",
        "parent-default",
        "missing-traversal",
        "parent-write",
    ],
)
def test_actual_distinct_worker_acl_rejects_nonexact_socket_or_parent(
    tmp_path: Path, mutation: str
) -> None:
    listener, path, worker_uid, root = _distinct_worker_listener(tmp_path)
    parent = path.parent
    try:
        if mutation == "missing-worker":
            _setfacl(path, "-x", f"u:{worker_uid}")
        elif mutation == "extra-user":
            _setfacl(path, "-m", f"u:{_other_uid(worker_uid)}:r")
        elif mutation == "extra-group":
            _setfacl(path, "-m", "g:65534:---")
        elif mutation == "group":
            _setfacl(path, "-m", "g::r")
        elif mutation == "other":
            _setfacl(path, "-m", "o::r")
        elif mutation == "mask":
            _setfacl(path, "-m", "m::r")
        elif mutation == "parent-default":
            _setfacl(parent, "-d", "-m", "u::rwx")
        elif mutation == "missing-traversal":
            _setfacl(parent, "-x", f"u:{worker_uid}")
        else:
            _setfacl(parent, "-m", f"u:{worker_uid}:wx")
        with pytest.raises(InspectorDaemonUnavailable):
            prove_activated_listener(
                listener,
                SystemdActivatedListenerConfigV1(path, os.geteuid()),
                required_worker_uid=worker_uid,
                deadline_monotonic=time.monotonic() + 0.5,
            )
    finally:
        listener.close()
        shutil.rmtree(root)


def test_actual_listener_rejects_expected_owner_or_gid_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    listener, path, worker_uid, root = _distinct_worker_listener(tmp_path)
    try:
        with pytest.raises(InspectorDaemonUnavailable):
            prove_activated_listener(
                listener,
                SystemdActivatedListenerConfigV1(path, os.geteuid() + 1),
                required_worker_uid=worker_uid,
                deadline_monotonic=time.monotonic() + 0.5,
            )
        from ksi_processing_controller import external_listener_acl

        monkeypatch.setattr(external_listener_acl.os, "getegid", lambda: os.getgid() + 1)
        with pytest.raises(InspectorDaemonUnavailable):
            prove_activated_listener(
                listener,
                SystemdActivatedListenerConfigV1(path, os.geteuid()),
                required_worker_uid=worker_uid,
                deadline_monotonic=time.monotonic() + 0.5,
            )
    finally:
        listener.close()
        shutil.rmtree(root)


def test_actual_listener_rejects_inode_replacement_and_acl_drift(tmp_path: Path) -> None:
    listener, path, worker_uid, root = _distinct_worker_listener(tmp_path)
    replacement: socket.socket | None = None
    receipt = None
    try:
        receipt = prove_activated_listener(
            listener,
            SystemdActivatedListenerConfigV1(path, os.geteuid()),
            required_worker_uid=worker_uid,
            deadline_monotonic=time.monotonic() + 0.5,
        )
        _setfacl(path, "-m", "o::r")
        with pytest.raises(ListenerAclUnavailable):
            assert receipt.access_receipt is not None
            receipt.access_receipt.reprove(
                listener,
                deadline_monotonic=time.monotonic() + 0.5,
                pending=receipt.preaccepted,
            )
        _setfacl(path, "-m", "o::---")
        path.unlink()
        replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        replacement.bind(os.fspath(path))
        replacement.listen(4)
        path.chmod(0o600)
        _setfacl(path, "-b")
        _setfacl(path, "-m", f"u:{worker_uid}:rw")
        with pytest.raises(ListenerAclUnavailable):
            assert receipt.access_receipt is not None
            receipt.access_receipt.reprove(
                listener,
                deadline_monotonic=time.monotonic() + 0.5,
                pending=receipt.preaccepted,
            )
    finally:
        if receipt is not None:
            receipt.close()
        listener.close()
        if replacement is not None:
            replacement.close()
        shutil.rmtree(root)


def test_inspector_daemon_reproves_queued_connection_and_closes_on_acl_drift(
    tmp_path: Path,
) -> None:
    from ksi_processing_controller.external_inspector_daemon import ExternalInspectorSystemdDaemon

    listener, path, worker_uid, root = _distinct_worker_listener(tmp_path)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    received: list[socket.socket] = []

    class Launcher:
        def handle_connection(self, connection: socket.socket) -> None:
            received.append(connection)
            connection.close()

    receipt = None
    daemon = None
    try:
        client.connect(os.fspath(path))
        receipt = prove_activated_listener(
            listener,
            SystemdActivatedListenerConfigV1(path, os.geteuid()),
            required_worker_uid=worker_uid,
            deadline_monotonic=time.monotonic() + 0.5,
        )
        daemon = ExternalInspectorSystemdDaemon(
            listener=receipt.listener,
            launcher=Launcher(),
            preaccepted=receipt.preaccepted,
            activated_listener=receipt,
            proof_timeout_millis=500,
        )
        daemon.serve_once()
        assert len(received) == 1
        assert client.recv(1) == b""
        client.close()

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(os.fspath(path))
        _setfacl(path, "-m", "o::r")
        with pytest.raises(ListenerAclUnavailable):
            daemon.serve_once()
        assert len(received) == 1
        assert client.recv(1) == b""
    finally:
        if daemon is not None:
            daemon.close()
        elif receipt is not None:
            receipt.close()
        listener.close()
        client.close()
        shutil.rmtree(root)


def test_inspector_daemon_drift_closes_every_retained_startup_connection(tmp_path: Path) -> None:
    from ksi_processing_controller.external_inspector_daemon import ExternalInspectorSystemdDaemon

    listener, path, worker_uid, root = _distinct_worker_listener(tmp_path)
    clients = [socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) for _ in range(2)]
    receipt = None
    daemon = None

    class Launcher:
        def handle_connection(self, connection: socket.socket) -> None:
            raise AssertionError("ACL drift must reject before launcher dispatch")

    try:
        for client in clients:
            client.connect(os.fspath(path))
            client.settimeout(0.5)
        receipt = prove_activated_listener(
            listener,
            SystemdActivatedListenerConfigV1(path, os.geteuid()),
            required_worker_uid=worker_uid,
            deadline_monotonic=time.monotonic() + 0.5,
        )
        assert len(receipt.preaccepted) == 2
        daemon = ExternalInspectorSystemdDaemon(
            listener=receipt.listener,
            launcher=Launcher(),
            preaccepted=receipt.preaccepted,
            activated_listener=receipt,
            proof_timeout_millis=500,
        )
        _setfacl(path, "-m", "o::r")
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
        shutil.rmtree(root)


@pytest.mark.parametrize("mutation", ["valid", "replacement", "datagram", "unlistening", "mode"])
def test_actual_listener_binding(tmp_path: Path, mutation: str) -> None:
    path = tmp_path / "listener"
    kind = socket.SOCK_DGRAM if mutation == "datagram" else socket.SOCK_STREAM
    listener = socket.socket(socket.AF_UNIX, kind)
    replacement = None
    try:
        listener.bind(str(path))
        path.chmod(0o600)
        if mutation not in {"datagram", "unlistening"}:
            listener.listen(8)
        if mutation == "replacement":
            path.unlink()
            replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            replacement.bind(str(path))
            replacement.listen(8)
            path.chmod(0o600)
        elif mutation == "mode":
            path.chmod(0o666)
        started = time.monotonic()
        if mutation == "valid":
            # On Linux these differ for a correctly bound listener.
            assert (os.fstat(listener.fileno()).st_dev, os.fstat(listener.fileno()).st_ino) != (
                path.stat().st_dev,
                path.stat().st_ino,
            )
            receipt = prove_activated_listener(
                listener,
                SystemdActivatedListenerConfigV1(path, os.geteuid()),
                deadline_monotonic=started + 0.1,
            )
            assert not receipt.preaccepted
            receipt.close()
        else:
            with pytest.raises(InspectorDaemonUnavailable):
                prove_activated_listener(
                    listener,
                    SystemdActivatedListenerConfigV1(path, os.geteuid()),
                    deadline_monotonic=started + 0.1,
                )
        assert time.monotonic() - started < 0.5
    finally:
        listener.close()
        if replacement is not None:
            replacement.close()


def test_probe_retains_already_queued_worker_connection(tmp_path: Path) -> None:
    path = tmp_path / "listener"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        listener.listen(8)
        path.chmod(0o600)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as worker:
            worker.connect(str(path))
            worker.sendall(b"real worker bytes")
            receipt = prove_activated_listener(
                listener,
                SystemdActivatedListenerConfigV1(path, os.geteuid()),
                deadline_monotonic=time.monotonic() + 0.1,
            )
            assert len(receipt.preaccepted) == 1
            with receipt.preaccepted.popleft() as connection:
                connection.settimeout(0.1)
                assert connection.recv(64) == b"real worker bytes"
            receipt.close()
