"""Concrete local user-namespace mapping and FD-only POSIX ACL controls.

Both adapters have required operator paths and no permissive fallback.  They
are usable only after Task 5 provisions the matching rootless namespace and
ACL-capable private filesystem.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ksi_domain.canonical_json import canonical_json_bytes

from ksi_processing_controller.external_inspector_staging import (
    MappedInspectorReaderV1,
)


class InspectorAccessUnavailable(RuntimeError):
    """The signed reader mapping or exact named-user ACL cannot be proven."""


@dataclass(frozen=True, slots=True)
class UserNamespaceMappingConfigV1:
    uid_map_path: Path
    gid_map_path: Path
    maximum_map_bytes: int

    def __post_init__(self) -> None:
        if not self.uid_map_path.is_absolute() or not self.gid_map_path.is_absolute():
            raise ValueError("user-namespace mapping paths must be absolute")
        if type(self.maximum_map_bytes) is not int or self.maximum_map_bytes <= 0:
            raise ValueError("user-namespace mapping read cap is required")


class ProcUserNamespaceReaderMapping:
    """Resolve the runtime's exact UID/GID only from two configured map files."""

    def __init__(self, config: UserNamespaceMappingConfigV1) -> None:
        self._config = config

    def resolve_exact(
        self,
        *,
        runtime_uid: int,
        runtime_gid: int,
        supplementary_groups: tuple[int, ...],
        deadline_monotonic: float,
    ) -> MappedInspectorReaderV1 | None:
        del deadline_monotonic
        if (
            type(runtime_uid) is not int
            or runtime_uid < 0
            or type(runtime_gid) is not int
            or runtime_gid < 0
            or supplementary_groups
        ):
            return None
        try:
            uid_bytes = _read_map(self._config.uid_map_path, self._config.maximum_map_bytes)
            gid_bytes = _read_map(self._config.gid_map_path, self._config.maximum_map_bytes)
            host_uid = _map_exact(uid_bytes, runtime_uid)
            host_gid = _map_exact(gid_bytes, runtime_gid)
        except InspectorAccessUnavailable:
            return None
        if host_uid is None or host_gid is None:
            return None
        witness = (
            "sha256:"
            + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "version": "external-inspector-reader-map.v1",
                        "runtimeUid": runtime_uid,
                        "runtimeGid": runtime_gid,
                        "hostUid": host_uid,
                        "hostGid": host_gid,
                        "uidMap": hashlib.sha256(uid_bytes).hexdigest(),
                        "gidMap": hashlib.sha256(gid_bytes).hexdigest(),
                    }
                )
            ).hexdigest()
        )
        return MappedInspectorReaderV1(
            container_uid=runtime_uid,
            container_gid=runtime_gid,
            host_uid=host_uid,
            host_gid=host_gid,
            mapping_witness=witness,
        )


class LibaclNamedReaderAcl:
    """Grant and reprove only a named mapped UID's read/execute traversal ACL."""

    _ACL_FIRST_ENTRY = 0
    _ACL_NEXT_ENTRY = 1
    _ACL_USER_OBJ = 0x01
    _ACL_USER = 0x02
    _ACL_GROUP_OBJ = 0x04
    _ACL_GROUP = 0x08
    _ACL_MASK = 0x10
    _ACL_OTHER = 0x20
    _ACL_READ = 0x04
    _ACL_WRITE = 0x02
    _ACL_EXECUTE = 0x01

    def __init__(self) -> None:
        try:
            self._lib = ctypes.CDLL("libacl.so.1")
        except OSError as exc:
            raise InspectorAccessUnavailable("libacl is unavailable") from exc
        self._configure()

    def grant_exact(
        self,
        *,
        source_fd: int,
        traversal_fds: tuple[int, int],
        reader: MappedInspectorReaderV1,
        deadline_monotonic: float,
    ) -> bool:
        del deadline_monotonic
        try:
            descriptors = (
                (source_fd, self._ACL_READ, False),
                *((descriptor, self._ACL_EXECUTE, True) for descriptor in traversal_fds),
            )
            if all(
                self._has_exact_reader_acl(descriptor, reader.host_uid, permission, is_directory)
                for descriptor, permission, is_directory in descriptors
            ):
                return True
            if not all(
                self._has_private_baseline(descriptor, reader.host_uid, is_directory)
                for descriptor, _permission, is_directory in descriptors
            ):
                return False
            granted: list[tuple[int, bool]] = []
            try:
                for descriptor, permission, is_directory in descriptors:
                    self._grant_fd(
                        descriptor, reader.host_uid, permission, is_directory=is_directory
                    )
                    granted.append((descriptor, is_directory))
                if self.verifies_exact(
                    source_fd=source_fd,
                    traversal_fds=traversal_fds,
                    reader=reader,
                    deadline_monotonic=0.0,
                ):
                    return True
            except (InspectorAccessUnavailable, OSError):
                pass
            for descriptor, is_directory in reversed(granted):
                try:
                    self._reset_private_fd(descriptor, is_directory=is_directory)
                except (InspectorAccessUnavailable, OSError):
                    return False
            return False
        except (InspectorAccessUnavailable, OSError):
            return False

    def grant_leaf_exact(
        self,
        *,
        source_fd: int,
        attempt_fd: int,
        reader: MappedInspectorReaderV1,
        deadline_monotonic: float,
    ) -> bool:
        """Grant a new sealed leaf while an identical reader owns the root ACL."""
        del deadline_monotonic
        descriptors = (
            (source_fd, self._ACL_READ, False),
            (attempt_fd, self._ACL_EXECUTE, True),
        )
        try:
            if not all(
                self._has_private_baseline(descriptor, reader.host_uid, is_directory)
                for descriptor, _permission, is_directory in descriptors
            ):
                return False
            granted: list[tuple[int, bool]] = []
            try:
                for descriptor, permission, is_directory in descriptors:
                    self._grant_fd(
                        descriptor, reader.host_uid, permission, is_directory=is_directory
                    )
                    granted.append((descriptor, is_directory))
                if all(
                    self._verify_fd(
                        descriptor, reader.host_uid, permission, is_directory=is_directory
                    )
                    for descriptor, permission, is_directory in descriptors
                ):
                    return True
            except (InspectorAccessUnavailable, OSError):
                pass
            for descriptor, is_directory in reversed(granted):
                try:
                    self._reset_private_fd(descriptor, is_directory=is_directory)
                except (InspectorAccessUnavailable, OSError):
                    return False
            return False
        except (InspectorAccessUnavailable, OSError):
            return False

    def revoke_exact(
        self,
        *,
        source_fd: int,
        traversal_fds: tuple[int, int],
        reader: MappedInspectorReaderV1,
        deadline_monotonic: float,
    ) -> bool:
        """Return all three FDs to their exact owner-only POSIX ACL baseline."""
        del deadline_monotonic
        try:
            descriptors = (
                (source_fd, self._ACL_READ, False),
                *((descriptor, self._ACL_EXECUTE, True) for descriptor in traversal_fds),
            )
            if not all(
                self._has_exact_reader_acl(descriptor, reader.host_uid, permission, is_directory)
                for descriptor, permission, is_directory in descriptors
            ):
                return False
            for descriptor, _permission, is_directory in descriptors:
                self._reset_private_fd(descriptor, is_directory=is_directory)
            return all(
                self._has_private_baseline(descriptor, reader.host_uid, is_directory)
                for descriptor, _permission, is_directory in descriptors
            )
        except (InspectorAccessUnavailable, OSError):
            return False

    def revoke_leaf_exact(
        self,
        *,
        source_fd: int,
        attempt_fd: int,
        reader: MappedInspectorReaderV1,
        deadline_monotonic: float,
    ) -> bool:
        """Retire one leaf while preserving the separately leased root ACL."""
        del deadline_monotonic
        descriptors = (
            (source_fd, self._ACL_READ, False),
            (attempt_fd, self._ACL_EXECUTE, True),
        )
        try:
            if not all(
                self._has_exact_reader_acl(descriptor, reader.host_uid, permission, is_directory)
                for descriptor, permission, is_directory in descriptors
            ):
                return False
            for descriptor, _permission, is_directory in descriptors:
                self._reset_private_fd(descriptor, is_directory=is_directory)
            return all(
                self._has_private_baseline(descriptor, reader.host_uid, is_directory)
                for descriptor, _permission, is_directory in descriptors
            )
        except (InspectorAccessUnavailable, OSError):
            return False

    def verifies_private_directory(self, *, directory_fd: int) -> bool:
        """Prove a root is owner-only or carries one exact traversal ACL mask.

        The kernel reflects a POSIX ACL mask as group execute (0710).  That bit
        is never treated as a group grant: the ACL itself must contain only one
        named user with execute and no group/default/other entries.
        """
        try:
            acl = self._get_acl(directory_fd)
            try:
                entries = self._entries(acl)
            finally:
                self._free(acl)
            return _private_acl_baseline(entries, -1, True, self) or _private_traversal_acl(
                entries, self
            )
        except (InspectorAccessUnavailable, OSError):
            return False

    def retire_private_directory(self, *, directory_fd: int) -> bool:
        """Return a proved single-reader traversal ACL to the 0700 baseline.

        Recovery calls this only after it has removed the exact recorded
        allocation.  It deliberately refuses an unrecognised ACL rather than
        resetting a directory that may grant another active reader access.
        """
        try:
            acl = self._get_acl(directory_fd)
            try:
                entries = self._entries(acl)
            finally:
                self._free(acl)
            if not _private_traversal_acl(entries, self):
                return False
            self._reset_private_fd(directory_fd, is_directory=True)
            return self._has_private_baseline(directory_fd, -1, is_directory=True)
        except (InspectorAccessUnavailable, OSError):
            return False

    def retire_recovered_leaf_acl(
        self,
        *,
        source_fd: int,
        attempt_fd: int,
    ) -> bool:
        """Retire one exact, common named-reader grant during crash recovery.

        The durable staging receipt does not retain a host UID.  Recovery may
        therefore reset these descriptors only when every descriptor proves the
        same single named user and the exact read/execute permissions that a
        sealed input lease created.  The shared root remains available until
        the startup sweep has processed every recorded allocation.
        """
        try:
            descriptors = (
                (source_fd, self._ACL_READ, False),
                (attempt_fd, self._ACL_EXECUTE, True),
            )
            reader_uids = [
                self._exact_reader_uid(descriptor, permission, is_directory)
                for descriptor, permission, is_directory in descriptors
            ]
            if any(uid is None for uid in reader_uids) or len(set(reader_uids)) != 1:
                return False
            for descriptor, _permission, is_directory in descriptors:
                self._reset_private_fd(descriptor, is_directory=is_directory)
            return all(
                self._has_private_baseline(descriptor, -1, is_directory)
                for descriptor, _permission, is_directory in descriptors
            )
        except (InspectorAccessUnavailable, OSError):
            return False

    def verifies_exact(
        self,
        *,
        source_fd: int,
        traversal_fds: tuple[int, int],
        reader: MappedInspectorReaderV1,
        deadline_monotonic: float,
    ) -> bool:
        del deadline_monotonic
        try:
            return self._verify_fd(
                source_fd, reader.host_uid, self._ACL_READ, is_directory=False
            ) and all(
                self._verify_fd(descriptor, reader.host_uid, self._ACL_EXECUTE, is_directory=True)
                for descriptor in traversal_fds
            )
        except (InspectorAccessUnavailable, OSError):
            return False

    def _grant_fd(self, descriptor: int, uid: int, permission: int, *, is_directory: bool) -> None:
        acl = self._get_acl(descriptor)
        try:
            entries = self._entries(acl)
            if not _private_acl_baseline(entries, uid, is_directory, self):
                raise InspectorAccessUnavailable("private ACL baseline is not exact")
            entry = ctypes.c_void_p()
            self._check(self._lib.acl_create_entry(ctypes.byref(acl), ctypes.byref(entry)))
            self._check(self._lib.acl_set_tag_type(entry, self._ACL_USER))
            raw_uid = ctypes.c_uint(uid)
            self._check(self._lib.acl_set_qualifier(entry, ctypes.byref(raw_uid)))
            permset = ctypes.c_void_p()
            self._check(self._lib.acl_get_permset(entry, ctypes.byref(permset)))
            self._check(self._lib.acl_clear_perms(permset))
            self._check(self._lib.acl_add_perm(permset, permission))
            self._check(self._lib.acl_calc_mask(ctypes.byref(acl)))
            self._check(self._lib.acl_set_fd(descriptor, acl))
        finally:
            self._free(acl)

    def _has_private_baseline(self, descriptor: int, uid: int, is_directory: bool) -> bool:
        acl = self._get_acl(descriptor)
        try:
            return _private_acl_baseline(self._entries(acl), uid, is_directory, self)
        finally:
            self._free(acl)

    def _has_exact_reader_acl(
        self, descriptor: int, uid: int, permission: int, is_directory: bool
    ) -> bool:
        acl = self._get_acl(descriptor)
        try:
            return self._entries(acl) == _expected_reader_acl(uid, permission, is_directory, self)
        finally:
            self._free(acl)

    def _exact_reader_uid(self, descriptor: int, permission: int, is_directory: bool) -> int | None:
        acl = self._get_acl(descriptor)
        try:
            entries = self._entries(acl)
        finally:
            self._free(acl)
        candidates = [
            uid
            for (tag, uid), observed_permission in entries.items()
            if tag == self._ACL_USER and uid is not None and observed_permission == permission
        ]
        if len(candidates) != 1:
            return None
        uid = candidates[0]
        return uid if entries == _expected_reader_acl(uid, permission, is_directory, self) else None

    def _reset_private_fd(self, descriptor: int, *, is_directory: bool) -> None:
        mode = 0o700 if is_directory else 0o600
        acl = ctypes.c_void_p(self._lib.acl_from_mode(mode))
        if not acl.value:
            raise InspectorAccessUnavailable("private ACL reset is unavailable")
        try:
            self._check(self._lib.acl_set_fd(descriptor, acl))
        finally:
            self._free(acl)

    def _verify_fd(self, descriptor: int, uid: int, permission: int, *, is_directory: bool) -> bool:
        acl = self._get_acl(descriptor)
        try:
            entries = self._entries(acl)
            required_owner = self._ACL_READ | self._ACL_WRITE
            if is_directory:
                required_owner |= self._ACL_EXECUTE
            expected = {
                (self._ACL_USER_OBJ, None): required_owner,
                (self._ACL_GROUP_OBJ, None): 0,
                (self._ACL_OTHER, None): 0,
                (self._ACL_MASK, None): permission,
                (self._ACL_USER, uid): permission,
            }
            return entries == expected
        finally:
            self._free(acl)

    def _get_acl(self, descriptor: int) -> ctypes.c_void_p:
        acl = ctypes.c_void_p(self._lib.acl_get_fd(descriptor))
        if not acl.value:
            raise InspectorAccessUnavailable("FD ACL is unavailable")
        return acl

    def _entries(self, acl: ctypes.c_void_p) -> dict[tuple[int, int | None], int]:
        entries: dict[tuple[int, int | None], int] = {}
        entry = ctypes.c_void_p()
        result = self._lib.acl_get_entry(acl, self._ACL_FIRST_ENTRY, ctypes.byref(entry))
        while result == 1:
            tag = ctypes.c_int()
            self._check(self._lib.acl_get_tag_type(entry, ctypes.byref(tag)))
            qualifier: int | None = None
            if tag.value in {self._ACL_USER, self._ACL_GROUP}:
                raw = ctypes.c_void_p(self._lib.acl_get_qualifier(entry))
                if not raw.value:
                    raise InspectorAccessUnavailable("ACL qualifier is unavailable")
                try:
                    qualifier = ctypes.cast(raw, ctypes.POINTER(ctypes.c_uint)).contents.value
                finally:
                    self._free(raw)
            permset = ctypes.c_void_p()
            self._check(self._lib.acl_get_permset(entry, ctypes.byref(permset)))
            permissions = 0
            for flag in (self._ACL_READ, self._ACL_WRITE, self._ACL_EXECUTE):
                present = self._lib.acl_get_perm(permset, flag)
                if present < 0:
                    raise InspectorAccessUnavailable("ACL permission is unavailable")
                if present == 1:
                    permissions |= flag
            key = (tag.value, qualifier)
            if key in entries:
                raise InspectorAccessUnavailable("ACL contains duplicate entry")
            entries[key] = permissions
            result = self._lib.acl_get_entry(acl, self._ACL_NEXT_ENTRY, ctypes.byref(entry))
        if result < 0:
            raise InspectorAccessUnavailable("ACL entry iteration is unavailable")
        return entries

    def _configure(self) -> None:
        for name in (
            "acl_create_entry",
            "acl_set_tag_type",
            "acl_set_qualifier",
            "acl_get_permset",
            "acl_clear_perms",
            "acl_add_perm",
            "acl_calc_mask",
            "acl_set_fd",
            "acl_get_tag_type",
            "acl_get_perm",
            "acl_get_entry",
        ):
            getattr(self._lib, name).restype = ctypes.c_int
        self._lib.acl_get_fd.restype = ctypes.c_void_p
        self._lib.acl_get_qualifier.restype = ctypes.c_void_p
        self._lib.acl_from_mode.restype = ctypes.c_void_p
        self._lib.acl_free.restype = ctypes.c_int

    @staticmethod
    def _check(result: int) -> None:
        if result < 0:
            raise InspectorAccessUnavailable("POSIX ACL operation failed")

    def _free(self, pointer: ctypes.c_void_p | None) -> None:
        if pointer is not None and pointer.value:
            self._lib.acl_free(pointer)


def _private_acl_baseline(
    entries: dict[tuple[int, int | None], int],
    uid: int,
    is_directory: bool,
    acl: LibaclNamedReaderAcl,
) -> bool:
    owner = acl._ACL_READ | acl._ACL_WRITE
    if is_directory:
        owner |= acl._ACL_EXECUTE
    return (
        entries
        == {
            (acl._ACL_USER_OBJ, None): owner,
            (acl._ACL_GROUP_OBJ, None): 0,
            (acl._ACL_OTHER, None): 0,
        }
        and uid != os.geteuid()
    )


def _expected_reader_acl(
    uid: int, permission: int, is_directory: bool, acl: LibaclNamedReaderAcl
) -> dict[tuple[int, int | None], int]:
    owner = acl._ACL_READ | acl._ACL_WRITE
    if is_directory:
        owner |= acl._ACL_EXECUTE
    return {
        (acl._ACL_USER_OBJ, None): owner,
        (acl._ACL_GROUP_OBJ, None): 0,
        (acl._ACL_OTHER, None): 0,
        (acl._ACL_MASK, None): permission,
        (acl._ACL_USER, uid): permission,
    }


def _private_traversal_acl(
    entries: dict[tuple[int, int | None], int], acl: LibaclNamedReaderAcl
) -> bool:
    expected = {
        (acl._ACL_USER_OBJ, None): acl._ACL_READ | acl._ACL_WRITE | acl._ACL_EXECUTE,
        (acl._ACL_GROUP_OBJ, None): 0,
        (acl._ACL_OTHER, None): 0,
        (acl._ACL_MASK, None): acl._ACL_EXECUTE,
    }
    named = [
        (key, permissions)
        for key, permissions in entries.items()
        if key[0] == acl._ACL_USER and key[1] != os.geteuid()
    ]
    return (
        len(named) == 1
        and named[0][1] == acl._ACL_EXECUTE
        and {key: permissions for key, permissions in entries.items() if key[0] != acl._ACL_USER}
        == expected
    )


def _read_map(path: Path, maximum_bytes: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise InspectorAccessUnavailable("user namespace map is unavailable") from exc
    try:
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(descriptor, min(4096, maximum_bytes - observed + 1))
            if not chunk:
                break
            observed += len(chunk)
            if observed > maximum_bytes:
                raise InspectorAccessUnavailable("user namespace map exceeds its bound")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _map_exact(contents: bytes, inside: int) -> int | None:
    try:
        text = contents.decode("ascii")
    except UnicodeDecodeError as exc:
        raise InspectorAccessUnavailable("user namespace map is not ASCII") from exc
    result: int | None = None
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 3 or any(re.fullmatch(r"[0-9]+", field) is None for field in fields):
            raise InspectorAccessUnavailable("user namespace map is malformed")
        start_inside, start_outside, length = (int(field) for field in fields)
        if length <= 0 or inside < start_inside or inside >= start_inside + length:
            continue
        candidate = start_outside + inside - start_inside
        if result is not None:
            raise InspectorAccessUnavailable("user namespace map overlaps the runtime ID")
        result = candidate
    return result


__all__ = [
    "InspectorAccessUnavailable",
    "LibaclNamedReaderAcl",
    "ProcUserNamespaceReaderMapping",
    "UserNamespaceMappingConfigV1",
]
