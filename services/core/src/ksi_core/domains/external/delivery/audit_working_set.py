"""Versioned opt-in for the private download-audit working set (ADR-KSI-041).

The legacy audit projection stays the default when no valid opt-in is
supplied. This configuration selects the indexed-history mode for one audit
journal only and binds it to the exact unchanged sealed data policy. It
carries no numeric cap increase, no preparation/TTL/grant/S3 change and no
new public surface. Invalid opt-in content fails closed at boot; it never
silently enables new semantics under an old policy.

Every field is explicit — there are no silent defaults beyond the fixed
version literal. Files are read through a pinned descriptor with bounded
size before any JSON parsing, and duplicate keys are refused.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Annotated, Literal, Self

from ksi_event_contracts._spatial_data import Digest
from pydantic import BaseModel, Field, StringConstraints, model_validator

AuditWorkingSetVersion = Literal["spatial-data-audit-working-set.v1"]
AuditOperationScope = Literal["download-only", "history-only"]

_CONFIG_VERSION: AuditWorkingSetVersion = "spatial-data-audit-working-set.v1"

ActivationId = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=128, pattern=r"^[0-9A-Za-z._-]+$")
]
AbsoluteName = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=4096, pattern=r"^[^/]+$")
]
PlainInt = Annotated[int, Field(strict=True, gt=0)]
PlainFloat = Annotated[float, Field(strict=True, gt=0)]

#: Hard upper bound for the active/unfinished working-set session count.
MAX_ACTIVE_SESSIONS = 512
#: Hard upper bound for the derived index file so index + rebuild temp +
#: worst-case spool stay inside the existing workspace envelope.
MAX_INDEX_DISK_BYTES = 32 * 1024 * 1024
#: The config file itself is tiny and bounded before parsing.
_MAX_CONFIG_BYTES = 65536


class SpatialDataAuditWorkingSetV1(BaseModel):
    """Owner-private opt-in binding the indexed-history audit mode."""

    model_config = {"frozen": True, "extra": "forbid"}

    version: AuditWorkingSetVersion
    policy_digest: Digest
    journal_file_name: AbsoluteName
    allowed_operation_scope: AuditOperationScope
    activation_id: ActivationId
    active_session_cap: PlainInt
    index_disk_bytes: PlainInt
    index_cache_allowance_bytes: PlainInt
    max_boot_scan_bytes: PlainInt
    max_boot_seconds: PlainFloat
    max_tail_records: PlainInt
    max_tail_bytes: PlainInt

    @model_validator(mode="after")
    def _bounded_explicit(self) -> Self:
        if self.version != _CONFIG_VERSION:
            raise ValueError("unknown audit working-set version")
        if self.allowed_operation_scope not in ("download-only", "history-only"):
            raise ValueError("only the download-only or history-only scopes are approved")
        if "\x00" in self.journal_file_name or "/" in self.journal_file_name:
            raise ValueError("journal file name must be a plain file name")
        if not 1 <= self.active_session_cap <= MAX_ACTIVE_SESSIONS:
            raise ValueError("active session cap must be within 1..512")
        if not 1024 * 1024 <= self.index_disk_bytes <= MAX_INDEX_DISK_BYTES:
            raise ValueError("index disk budget must be within 1MiB..32MiB")
        if self.index_cache_allowance_bytes > self.index_disk_bytes:
            raise ValueError("index cache allowance cannot exceed the index disk budget")
        if not self.max_boot_seconds <= 600.0:
            raise ValueError("boot deadline must stay within the 600s envelope ceiling")
        return self

    def config_digest(self) -> str:
        """Canonical digest of this exact versioned binding (change detection)."""
        from ksi_domain.canonical_json import canonical_json_bytes  # noqa: PLC0415

        return (
            "sha256:"
            + hashlib.sha256(
                canonical_json_bytes(self.model_dump(by_alias=True, mode="json"))
            ).hexdigest()
        )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _private_ancestors_ok(path: Path) -> None:
    """소유자-전용 파일의 조상 체인을 고정한다 — 별칭·치환 가능 조상 거부.

    파생 인덱스 게이트(:mod:`audit_history_index`)와 동일한 규칙이다:
    절대경로, ``..`` 없음, 각 컴포넌트는 NOFOLLOW 로 열고, 루트가 아닌
    조상이 umask 초과 쓰기 가능이면 스티키+호출자 소유 자식일 때만 허용,
    리프 디렉터리는 호출자 소유 0700. 쓰기 전 별칭 고정이 목적이라
    실패는 조용히 넘기지 않는다.
    """
    descriptors: list[int] = []
    try:
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError(f"{path}: owner-private path must be absolute")
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        descriptors.append(parent)
        for part in path.parent.parts[1:]:
            previous = os.fstat(parent)
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
            )
            descriptors.append(child)
            current = os.fstat(child)
            if current.st_uid not in (0, os.geteuid()) or (
                previous.st_mode & 0o022
                and not (previous.st_mode & stat.S_ISVTX and current.st_uid == os.geteuid())
            ):
                raise ValueError(f"{path}: substitutable config ancestor")
            parent = child
        root = os.fstat(parent)
        if (
            root.st_uid != os.geteuid()
            or root.st_gid != os.getegid()
            or stat.S_IMODE(root.st_mode) != 0o700
        ):
            raise ValueError(f"{path}: config directory must be owner-private 0700")
    except OSError as exc:
        raise ValueError(f"{path}: cannot validate config directory: {exc}") from exc
    finally:
        for fd in reversed(descriptors):
            with contextlib.suppress(OSError):
                os.close(fd)


def _read_private_json(path: Path, *, maximum_bytes: int) -> object:
    """Read a bounded owner-private file through a pinned descriptor.

    The descriptor is opened with NOFOLLOW|CLOEXEC before any read, so a
    swapped-in symlink or an unbounded file cannot reach the parser. Size is
    enforced from fstat, not from a racing stat-then-open pair. Ancestors are
    pinned first; a hard-linked file is refused — the binding must live on
    exactly one path before any byte is parsed.
    """
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{path}: owner-private path must be absolute")
    _private_ancestors_ok(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise ValueError(f"{path}: cannot open owner-private file: {exc}") from exc
    try:
        try:
            entry = os.fstat(fd)
        except OSError as exc:
            raise ValueError(f"{path}: cannot inspect owner-private file: {exc}") from exc
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode):
            raise ValueError(f"{path}: owner-private file must be a regular file")
        if entry.st_uid != os.geteuid() or stat.S_IMODE(entry.st_mode) != 0o600:
            raise ValueError(f"{path}: owner-private file must be 0600 owned by the caller")
        if entry.st_nlink != 1:
            raise ValueError(f"{path}: owner-private file must not be hard-linked")
        if entry.st_size > maximum_bytes:
            raise ValueError(f"{path}: owner-private file exceeds size budget")
        chunks: list[bytes] = []
        remaining = entry.st_size
        while remaining > 0:
            piece = os.read(fd, min(65536, remaining))
            if not piece:
                raise ValueError(f"{path}: owner-private file changed during read")
            chunks.append(piece)
            remaining -= len(piece)
        raw = b"".join(chunks)
    finally:
        os.close(fd)
    try:
        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_forbidden
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError(f"{path}: invalid audit working-set JSON: {exc}") from exc


def _forbidden(_: str) -> None:
    raise ValueError("non-finite JSON constant forbidden")


def load_spatial_data_audit_working_set(path: Path) -> SpatialDataAuditWorkingSetV1:
    """Load and validate the owner-private opt-in; no side effects.

    The file must be owner-private (0600, owned by the caller, never an
    alias). Any schema, version, bound or duplicate-key violation fails
    closed here, before any journal or composition change. Policy-digest,
    journal-identity and full-config-digest binding against the live sealed
    policy/journal happen at store construction, not here.
    """
    try:
        raw = _read_private_json(path, maximum_bytes=_MAX_CONFIG_BYTES)
    except ValueError as exc:
        raise ValueError(f"{path}: invalid audit working-set config: {exc}") from exc
    try:
        return SpatialDataAuditWorkingSetV1.model_validate(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{path}: invalid audit working-set config: {exc}") from exc
