"""Observed host proof for the dedicated rootless inspector boundary.

Operator configuration supplies expected identities only.  This adapter obtains
the actual process, user-namespace, cgroup, socket, and retained-FD facts at
startup and rechecks them on every container admission.  It deliberately does
not provision users, Docker, systemd units, sockets, images, or cgroups.
"""

from __future__ import annotations

import hashlib
import os
import re
import socket
import stat
import struct
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ksi_processing_controller.external_inspector_container_protocol import (
    FixedContainerConfigurationV1,
)
from ksi_processing_controller.external_inspector_docker import (
    DockerRuntimeUnavailable,
    RootlessDockerHostFactsPort,
)
from ksi_processing_controller.external_runtime_binding import ExactRuntimeBindingPort

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CGROUP = re.compile(r"^/(?:[A-Za-z0-9][A-Za-z0-9_.@:-]*/)*[A-Za-z0-9][A-Za-z0-9_.@:-]*$")
_SLICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,254}\.slice$")
_PID = re.compile(r"^[1-9][0-9]{0,9}\n?$")


class HostProofBlockedCode(StrEnum):
    """Non-secret reasons that keep inspector admission closed."""

    LAUNCHER_IDENTITY = "LAUNCHER_IDENTITY"
    DAEMON_PID = "DAEMON_PID"
    DAEMON_IDENTITY = "DAEMON_IDENTITY"
    USER_NAMESPACE = "USER_NAMESPACE"
    SOCKET_IDENTITY = "SOCKET_IDENTITY"
    CGROUP_IDENTITY = "CGROUP_IDENTITY"
    STARTUP_REPLACED = "STARTUP_REPLACED"
    PROC_FD = "PROC_FD"


class RootlessDockerHostProofUnavailable(DockerRuntimeUnavailable):
    """An observed host fact differs from the pinned operator configuration."""

    def __init__(self, code: HostProofBlockedCode) -> None:
        self.code = code
        super().__init__("rootless Docker host proof blocked: " + code.value)


@dataclass(frozen=True, slots=True)
class RootlessDockerHostProofConfigV1:
    """Exact non-secret expectations for one provisioned launcher host profile."""

    launcher_uid: int
    launcher_gid: int
    worker_uid: int
    rootless_daemon_pid_path: Path
    daemon_uid_map_sha256: str
    daemon_gid_map_sha256: str
    launcher_cgroup_path: str
    daemon_cgroup_path: str
    systemd_base_slice: str
    docker_socket_path: Path
    retained_input_mode: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (self.launcher_uid, self.launcher_gid, self.worker_uid)
        ):
            raise ValueError("dedicated launcher and worker identities are required")
        if self.worker_uid == self.launcher_uid:
            raise ValueError("dedicated launcher UID must differ from worker UID")
        if (
            not self.rootless_daemon_pid_path.is_absolute()
            or not self.docker_socket_path.is_absolute()
        ):
            raise ValueError("rootless daemon pid and socket paths must be absolute")
        if any(
            not isinstance(value, str) or _DIGEST.fullmatch(value) is None
            for value in (self.daemon_uid_map_sha256, self.daemon_gid_map_sha256)
        ):
            raise ValueError("rootless daemon user-namespace digests are required")
        if any(
            _CGROUP.fullmatch(value) is None
            for value in (self.launcher_cgroup_path, self.daemon_cgroup_path)
        ):
            raise ValueError("rootless launcher and daemon cgroups must be exact paths")
        if _SLICE.fullmatch(self.systemd_base_slice) is None:
            raise ValueError("rootless inspector base slice is invalid")
        if self.retained_input_mode not in {0o600, 0o640}:
            raise ValueError("retained inspector input mode must be exact and private")


@dataclass(frozen=True, slots=True)
class _ProcessObservation:
    pid: int
    start_time: int
    uids: tuple[int, int, int, int]
    gids: tuple[int, int, int, int]
    uid_map: bytes
    gid_map: bytes
    cgroup_path: str


@dataclass(frozen=True, slots=True)
class _SocketIdentity:
    device: int
    inode: int
    owner_uid: int
    owner_gid: int
    mode: int
    link_count: int


@dataclass(frozen=True, slots=True)
class _HostSnapshot:
    launcher: _ProcessObservation
    daemon: _ProcessObservation
    socket: _SocketIdentity


class HostProofObserverPort(Protocol):
    def observe_process(self, pid: int) -> _ProcessObservation: ...


class ProcfsHostProofObserver:
    """Bounded descriptor-relative reader for the actual Linux procfs by default."""

    _MAX_PROC_BYTES = 16 * 1024

    def __init__(self, *, proc_root: Path = Path("/proc")) -> None:
        if not proc_root.is_absolute():
            raise ValueError("proc root must be absolute")
        self._proc_root = proc_root

    def observe_process(self, pid: int) -> _ProcessObservation:
        if type(pid) is not int or pid <= 0:
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_PID)
        try:
            process_fd = os.open(
                self._proc_root / str(pid),
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except OSError as exc:
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_PID) from exc
        try:
            status = _read_proc_child(process_fd, "status", self._MAX_PROC_BYTES)
            proc_stat = _read_proc_child(process_fd, "stat", self._MAX_PROC_BYTES)
            uid_map = _read_proc_child(process_fd, "uid_map", self._MAX_PROC_BYTES)
            gid_map = _read_proc_child(process_fd, "gid_map", self._MAX_PROC_BYTES)
            cgroup = _read_proc_child(process_fd, "cgroup", self._MAX_PROC_BYTES)
        except OSError as exc:
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_PID) from exc
        finally:
            os.close(process_fd)
        uids, gids = _parse_status(status)
        return _ProcessObservation(
            pid=pid,
            start_time=_parse_start_time(proc_stat),
            uids=uids,
            gids=gids,
            uid_map=uid_map,
            gid_map=gid_map,
            cgroup_path=_parse_unified_cgroup(cgroup),
        )


class _RootlessDockerHostFactsV1(RootlessDockerHostFactsPort):
    """Admission-scoped facts whose verification always reobserves the host."""

    def __init__(self, proof: RootlessDockerHostProofV1, snapshot: _HostSnapshot) -> None:
        self._proof = proof
        self._snapshot = snapshot
        self.launcher_pid = snapshot.launcher.pid

    def verify_slice(self, *, binding: ExactRuntimeBindingPort) -> bool:
        try:
            return (
                self._proof._reobserve() == self._snapshot
                and binding.systemd_base_slice == self._proof.config.systemd_base_slice
            )
        except (AttributeError, RootlessDockerHostProofUnavailable):
            return False

    def verify_proc_fd(
        self, *, fd: int, candidate: str, configuration: FixedContainerConfigurationV1
    ) -> bool:
        try:
            if self._proof._reobserve() != self._snapshot:
                return False
            if type(fd) is not int or fd < 0:
                return False
            expected_candidate = f"/proc/{self.launcher_pid}/fd/{fd}"
            if candidate != expected_candidate:
                return False
            original = os.fstat(fd)
            if not _matches_fixed_input(original, configuration, self._proof.config):
                return False
            duplicate_fd = os.open(expected_candidate, os.O_RDONLY | os.O_CLOEXEC)
            try:
                duplicate = os.fstat(duplicate_fd)
            finally:
                os.close(duplicate_fd)
            current = os.fstat(fd)
            return _exact_file_identity(original, duplicate) and _exact_file_identity(
                original, current
            )
        except (OSError, RootlessDockerHostProofUnavailable):
            return False


class RootlessDockerHostProofV1:
    """Concrete proof required before a rootless Docker runtime can create a container."""

    def __init__(
        self,
        config: RootlessDockerHostProofConfigV1,
        *,
        startup_timeout_millis: int,
        observer: HostProofObserverPort | None = None,
    ) -> None:
        if type(startup_timeout_millis) is not int or startup_timeout_millis <= 0:
            raise ValueError("host proof startup timeout must be explicit and positive")
        self._startup_timeout_millis = startup_timeout_millis
        self._config = config
        self._observer = ProcfsHostProofObserver() if observer is None else observer
        self._startup_snapshot: _HostSnapshot | None = None

    @property
    def config(self) -> RootlessDockerHostProofConfigV1:
        return self._config

    def verify_startup(self) -> None:
        deadline = time.monotonic() + self._startup_timeout_millis / 1000
        snapshot = self._reobserve()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                connection.settimeout(remaining)
                connection.connect(os.fspath(self._config.docker_socket_path))
                self._verify_connected_snapshot(connection, snapshot, deadline)
        except (OSError, TimeoutError) as exc:
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.SOCKET_IDENTITY) from exc
        if self._startup_snapshot is None:
            self._startup_snapshot = snapshot
            return
        if snapshot != self._startup_snapshot:
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.STARTUP_REPLACED)

    def verify_connected(
        self,
        connection: socket.socket,
        *,
        deadline_monotonic: float,
    ) -> None:
        snapshot = self._startup_snapshot
        if snapshot is None:
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.STARTUP_REPLACED)
        self._verify_connected_snapshot(connection, snapshot, deadline_monotonic)

    def _verify_connected_snapshot(
        self,
        connection: socket.socket,
        snapshot: _HostSnapshot,
        deadline: float,
    ) -> None:
        try:
            credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            peer = struct.unpack("3i", credentials)
            if (
                time.monotonic() >= deadline
                or peer
                != (snapshot.daemon.pid, self._config.launcher_uid, self._config.launcher_gid)
                or self._reobserve() != snapshot
                or time.monotonic() >= deadline
            ):
                raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.SOCKET_IDENTITY)
        except (OSError, AttributeError, struct.error) as exc:
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.SOCKET_IDENTITY) from exc

    def prove(self, *, configuration: FixedContainerConfigurationV1) -> _RootlessDockerHostFactsV1:
        self.verify_startup()
        _validate_fixed_configuration(configuration)
        snapshot = self._startup_snapshot
        if snapshot is None:  # defensive: verify_startup always assigns or raises
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.STARTUP_REPLACED)
        return _RootlessDockerHostFactsV1(self, snapshot)

    def _reobserve(self) -> _HostSnapshot:
        if (
            os.getuid() != self._config.launcher_uid
            or os.geteuid() != self._config.launcher_uid
            or os.getgid() != self._config.launcher_gid
            or os.getegid() != self._config.launcher_gid
        ):
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.LAUNCHER_IDENTITY)
        daemon_pid = _read_daemon_pid(self._config)
        launcher = self._observer.observe_process(os.getpid())
        daemon = self._observer.observe_process(daemon_pid)
        if (
            launcher.uids != (self._config.launcher_uid,) * 4
            or launcher.gids != (self._config.launcher_gid,) * 4
            or daemon.uids != (self._config.launcher_uid,) * 4
            or daemon.gids != (self._config.launcher_gid,) * 4
        ):
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_IDENTITY)
        _verify_rootless_maps(daemon, self._config)
        if (
            launcher.cgroup_path != self._config.launcher_cgroup_path
            or daemon.cgroup_path != self._config.daemon_cgroup_path
        ):
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.CGROUP_IDENTITY)
        return _HostSnapshot(
            launcher=launcher,
            daemon=daemon,
            socket=_observe_socket(self._config),
        )


def _read_daemon_pid(config: RootlessDockerHostProofConfigV1) -> int:
    try:
        descriptor = os.open(
            config.rootless_daemon_pid_path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError as exc:
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_PID) from exc
    try:
        node = os.fstat(descriptor)
        contents = _read_descriptor(descriptor, 64)
    except OSError as exc:
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_PID) from exc
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(node.st_mode)
        or node.st_uid != config.launcher_uid
        or node.st_gid != config.launcher_gid
        or (node.st_mode & 0o777) != 0o600
        or node.st_nlink != 1
    ):
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_PID)
    try:
        raw = contents.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_PID) from exc
    if _PID.fullmatch(raw) is None:
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_PID)
    return int(raw)


def _verify_rootless_maps(
    daemon: _ProcessObservation, config: RootlessDockerHostProofConfigV1
) -> None:
    if (
        _digest(daemon.uid_map) != config.daemon_uid_map_sha256
        or _digest(daemon.gid_map) != config.daemon_gid_map_sha256
    ):
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.USER_NAMESPACE)
    for mapping, expected_outside in (
        (daemon.uid_map, config.launcher_uid),
        (daemon.gid_map, config.launcher_gid),
    ):
        rows = _parse_user_namespace_map(mapping)
        if not any(
            inside == 0 and outside == expected_outside for inside, outside, _ in rows
        ):
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.USER_NAMESPACE)
        if any(outside == 0 for _inside, outside, _length in rows):
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.USER_NAMESPACE)


def _observe_socket(config: RootlessDockerHostProofConfigV1) -> _SocketIdentity:
    try:
        node = os.lstat(config.docker_socket_path)
    except OSError as exc:
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.SOCKET_IDENTITY) from exc
    if (
        not stat.S_ISSOCK(node.st_mode)
        or node.st_uid != config.launcher_uid
        or node.st_gid != config.launcher_gid
        or (node.st_mode & 0o777) != 0o600
        or node.st_nlink != 1
    ):
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.SOCKET_IDENTITY)
    return _SocketIdentity(
        device=node.st_dev,
        inode=node.st_ino,
        owner_uid=node.st_uid,
        owner_gid=node.st_gid,
        mode=node.st_mode & 0o777,
        link_count=node.st_nlink,
    )


def _validate_fixed_configuration(configuration: FixedContainerConfigurationV1) -> None:
    if (
        configuration.runtime_uid <= 0
        or configuration.runtime_gid <= 0
        or configuration.supplementary_groups
        or configuration.input_mount.target_path != "/input/artifact.tif"
        or configuration.input_mount.read_only is not True
    ):
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.PROC_FD)


def _matches_fixed_input(
    node: os.stat_result,
    configuration: FixedContainerConfigurationV1,
    config: RootlessDockerHostProofConfigV1,
) -> bool:
    mount = configuration.input_mount
    return (
        stat.S_ISREG(node.st_mode)
        and node.st_dev == mount.source_device
        and node.st_ino == mount.source_inode
        and node.st_size == mount.observed_size_bytes
        and node.st_uid == config.launcher_uid
        and node.st_gid == config.launcher_gid
        and (node.st_mode & 0o777) == config.retained_input_mode
        and node.st_nlink == 1
    )


def _exact_file_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        first.st_dev,
        first.st_ino,
        first.st_mode,
        first.st_uid,
        first.st_gid,
        first.st_nlink,
        first.st_size,
    ) == (
        second.st_dev,
        second.st_ino,
        second.st_mode,
        second.st_uid,
        second.st_gid,
        second.st_nlink,
        second.st_size,
    )


def _read_proc_child(directory_fd: int, name: str, maximum_bytes: int) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
    try:
        node = os.fstat(descriptor)
        if not stat.S_ISREG(node.st_mode):
            raise OSError("proc entry is not regular")
        return _read_descriptor(descriptor, maximum_bytes)
    finally:
        os.close(descriptor)


def _read_descriptor(descriptor: int, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    while True:
        chunk = os.read(descriptor, min(4096, maximum_bytes - observed + 1))
        if not chunk:
            return b"".join(chunks)
        observed += len(chunk)
        if observed > maximum_bytes:
            raise OSError("bounded descriptor read exceeded")
        chunks.append(chunk)


def _parse_status(raw: bytes) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_IDENTITY) from exc
    values: dict[str, tuple[int, int, int, int]] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key not in {"Uid", "Gid"}:
            continue
        if key in values:
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_IDENTITY)
        fields = value.split()
        if len(fields) != 4 or any(not item.isdecimal() for item in fields):
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_IDENTITY)
        values[key] = tuple(int(item) for item in fields)  # type: ignore[assignment]
    try:
        return values["Uid"], values["Gid"]
    except KeyError as exc:
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_IDENTITY) from exc


def _parse_start_time(raw: bytes) -> int:
    try:
        text = raw.decode("ascii").strip()
        before, after = text.rsplit(")", 1)
        if "(" not in before:
            raise ValueError
        fields = after.split()
        value = fields[19]
        if not value.isdecimal() or int(value) <= 0:
            raise ValueError
        return int(value)
    except (UnicodeDecodeError, IndexError, ValueError) as exc:
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.DAEMON_IDENTITY) from exc


def _parse_user_namespace_map(raw: bytes) -> tuple[tuple[int, int, int], ...]:
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.USER_NAMESPACE) from exc
    if not lines:
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.USER_NAMESPACE)
    rows: list[tuple[int, int, int]] = []
    for line in lines:
        fields = line.split()
        if len(fields) != 3 or any(not value.isdecimal() for value in fields):
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.USER_NAMESPACE)
        row = (int(fields[0]), int(fields[1]), int(fields[2]))
        if row[2] <= 0 or any(value > 2**32 - 1 for value in row):
            raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.USER_NAMESPACE)
        rows.append(row)
    if len(rows) > 8 or len({(inside, outside) for inside, outside, _ in rows}) != len(rows):
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.USER_NAMESPACE)
    for index, (inside, outside, length) in enumerate(rows):
        for other_inside, other_outside, other_length in rows[index + 1 :]:
            if max(inside, other_inside) < min(inside + length, other_inside + other_length) or max(
                outside, other_outside
            ) < min(outside + length, other_outside + other_length):
                raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.USER_NAMESPACE)
    return tuple(rows)


def _parse_unified_cgroup(raw: bytes) -> str:
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.CGROUP_IDENTITY) from exc
    if len(lines) != 1:
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.CGROUP_IDENTITY)
    fields = lines[0].split(":", 2)
    if len(fields) != 3 or fields[:2] != ["0", ""] or _CGROUP.fullmatch(fields[2]) is None:
        raise RootlessDockerHostProofUnavailable(HostProofBlockedCode.CGROUP_IDENTITY)
    return fields[2]


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


__all__ = [
    "HostProofBlockedCode",
    "HostProofObserverPort",
    "ProcfsHostProofObserver",
    "RootlessDockerHostProofConfigV1",
    "RootlessDockerHostProofUnavailable",
    "RootlessDockerHostProofV1",
]
