#!/usr/bin/env python3
"""Bounded static verification for offline application bundles.

Inspects a directory containing ``manifest.json``, ``uv.lock``,
``requirements.txt`` and ``wheels/*.whl`` against caller-supplied pins.
Static only: never launches a process, never imports or extracts wheel code,
and never decompresses non-metadata payloads. All evidence failures raise
:class:`BundleEvidenceError` with a safe code; paths and file contents never
appear in diagnostics.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import copy
import csv
import hashlib
import io
import json
import math
import os
import re
import stat
import struct
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

_MAX_BUNDLE_BYTES = 1024**3
_MAX_WHEELS = 256
_MAX_WHEEL_BYTES = 256 * 1024**2
_MAX_JSON_BYTES = 1024**2
_MAX_TOTAL_READ_BYTES = _MAX_BUNDLE_BYTES + _MAX_JSON_BYTES
_MAX_METADATA_BYTES = 1024**2
_MAX_ZIP_CENTRAL_BYTES = 16 * 1024**2
_MAX_ZIP_ENTRIES = 65536
_MAX_ZIP_TOTAL_ENTRIES = 262144
_MAX_EXPANDED_BYTES = 4 * 1024**3
_READ_CHUNK_BYTES = 1024**2

_SCHEMA_VERSION = "external-runtime-application-bundle.v1"
_IMPLEMENTATION = "CPython"
_PYTHON_VERSION = "3.12.15"
_TARGET_OS = "linux"
_ARCHITECTURE = "arm64"
_LIBC_FAMILY = "glibc"
_UV_VERSION = "0.11.15"
_BUILD_PYTHON_PREFIX = "3.12"
_CONTROLLER_NORMALIZED = "ksi_processing_controller"

_FIXED_ENTRYPOINTS: tuple[tuple[str, str, str], ...] = (
    (
        "ksi-external-inspector-daemon",
        "ksi_processing_controller.external_inspector_daemon",
        "main",
    ),
    (
        "ksi-external-measurement-daemon",
        "ksi_processing_controller.external_measurement_daemon",
        "main",
    ),
    (
        "ksi-external-validation-worker",
        "ksi_processing_controller.external_validation_worker",
        "main",
    ),
)
_FIXED_ENTRYPOINT_SET = frozenset(_FIXED_ENTRYPOINTS)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_.+~-]+\Z")
_NORMALIZE_RUNS = re.compile(r"[-_.]+")
_RECORD_HASH = re.compile(r"sha256=[A-Za-z0-9_-]{43}\Z")
_RECORD_SIZE = re.compile(r"[0-9]+\Z")
_ABI3_FLOOR = re.compile(r"cp3([0-9]+)\Z")

_ROOT_NAMES = frozenset({"manifest.json", "uv.lock", "requirements.txt", "wheels"})
_FILE_WHEEL_KINDS = frozenset({"workspace-wheel", "external-wheel"})
_ROOT_KEYS = frozenset(
    {"schemaVersion", "source", "target", "buildToolchain", "files", "distributions", "entrypoints"}
)
_SOURCE_KEYS = frozenset(
    {"gitCommitSha", "uvLockSha256", "uvLockBytes", "buildInputInventorySha256"}
)
_TARGET_KEYS = frozenset(
    {
        "implementation",
        "pythonVersion",
        "os",
        "architecture",
        "libcFamily",
        "libcVersion",
        "platformTag",
    }
)
_TOOLCHAIN_KEYS = frozenset(
    {"uvVersion", "uvSha256", "buildPythonVersion", "buildPythonSha256", "backendInventorySha256"}
)
_FILE_KEYS = frozenset({"relativePath", "sha256", "bytes", "kind"})
_DISTRIBUTION_KEYS = frozenset(
    {"name", "version", "kind", "wheel", "pythonTag", "abiTag", "platformTag"}
)
_ENTRYPOINT_KEYS = frozenset({"name", "module", "function"})


class BundleEvidenceError(ValueError):
    """Safe codes only; paths, digests and embedded content are not diagnostics."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("APPLICATION_BUNDLE_BLOCKED: " + code)


def _fail(code: str) -> NoReturn:
    raise BundleEvidenceError(code)


@dataclass(frozen=True)
class BundleTarget:
    implementation: str
    python_version: str
    os: str
    architecture: str
    libc_family: str
    libc_version: str
    platform_tag: str


@dataclass(frozen=True)
class BoundBundleFile:
    relative_path: str
    sha256: str
    bytes: int
    kind: str


@dataclass(frozen=True)
class FixedEntryPoint:
    name: str
    module: str
    function: str


@dataclass(frozen=True)
class VerifiedApplicationBundle:
    bundle_root: Path
    manifest_sha256: str
    source_commit: str
    lock_sha256: str
    target: BundleTarget
    files: tuple[BoundBundleFile, ...]
    entrypoints: tuple[FixedEntryPoint, ...]


@dataclass(frozen=True)
class _Distribution:
    name: str
    version: str
    kind: str
    wheel: str
    python_tag: str
    abi_tag: str
    platform_tag: str


class _Budgets:
    """Whole-bundle aggregate counters enforced before unbounded work."""

    def __init__(self) -> None:
        self.zip_entries = 0
        self.expanded_bytes = 0
        self.metadata_bytes = 0


def _identity(node: os.stat_result) -> tuple[int, ...]:
    return (node.st_dev, node.st_ino, node.st_size, node.st_mtime_ns, node.st_ctime_ns)


def _open_parent(path: Path) -> int:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts or not path.name:
        _fail("INPUT_PATH")
    if "\0" in str(path):
        _fail("INPUT_PATH")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_exact(fd: int, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = os.read(fd, min(remaining, _READ_CHUNK_BYTES))
        if not chunk:
            _fail("INPUT_SHORT_READ")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_file(dir_fd: int, name: str, ident: tuple[int, ...], limit: int, code: str) -> bytes:
    """Hash and read the same opened descriptor; detect rename-replacement."""
    try:
        fd = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=dir_fd
        )
    except OSError as error:
        raise BundleEvidenceError("INPUT_OPEN") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            _fail("INPUT_FILE")
        if _identity(before) != ident:
            _fail("INPUT_CHANGED")
        size = before.st_size
        if not 0 < size <= limit:
            _fail(code)
        data = _read_exact(fd, size)
        after = os.fstat(fd)
        named = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if _identity(after) != ident or _identity(named) != ident:
            _fail("INPUT_CHANGED")
        return data
    finally:
        os.close(fd)


def _sweep(dir_fd: int, snapshot: dict[str, tuple[int, ...]]) -> None:
    for name, ident in snapshot.items():
        try:
            node = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except OSError as error:
            raise BundleEvidenceError("INPUT_CHANGED") from error
        if _identity(node) != ident:
            _fail("INPUT_CHANGED")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            _fail("JSON_DUPLICATE")
        result[key] = value
    return result


def _checked_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        _fail("JSON_NONFINITE")
    return result


def _reject_constant(value: str) -> NoReturn:
    _fail("JSON_NONFINITE")


def _parse_manifest(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
            parse_float=_checked_float,
        )
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, BundleEvidenceError):
            raise
        raise BundleEvidenceError("JSON_SYNTAX") from error
    if not isinstance(value, dict):
        _fail("JSON_ROOT")
    return value


def _digest_text(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _record_digest(payload: bytes) -> str:
    raw = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
    return "sha256=" + raw.decode("ascii")


_EMPTY_RECORD_DIGEST = _record_digest(b"")


def _normalized(name: str) -> str:
    return _NORMALIZE_RUNS.sub("_", name.lower())


def _check_safe_name(name: str) -> bool:
    if not name or "\0" in name or "\\" in name or name.startswith("/"):
        return False
    parts = PurePosixPath(name).parts
    return bool(parts) and ".." not in parts


def _parse_wheel_filename(filename: str, code: str) -> tuple[str, str, str, str, str]:
    if not filename.endswith(".whl"):
        _fail(code)
    parts = filename[:-4].split("-")
    if len(parts) != 5 or any(not part for part in parts):
        _fail(code)
    return (parts[0], parts[1], parts[2], parts[3], parts[4])


def _exact_keys(value: Any, keys: frozenset[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value.keys()) != set(keys):
        _fail(code)
    return value


def _check_source(
    value: Any, expected_source_commit: str, expected_lock_sha256: str
) -> tuple[str, str, int]:
    source = _exact_keys(value, _SOURCE_KEYS, "SOURCE_FIELD")
    commit = source["gitCommitSha"]
    if not isinstance(commit, str) or commit != expected_source_commit:
        _fail("SOURCE_COMMIT")
    lock_digest = source["uvLockSha256"]
    if not isinstance(lock_digest, str) or not _DIGEST.fullmatch(lock_digest):
        _fail("SOURCE_FIELD")
    if lock_digest != expected_lock_sha256:
        _fail("SOURCE_LOCK")
    lock_bytes = source["uvLockBytes"]
    if type(lock_bytes) is not int or lock_bytes <= 0:
        _fail("SOURCE_FIELD")
    inventory = source["buildInputInventorySha256"]
    if not isinstance(inventory, str) or not _DIGEST.fullmatch(inventory):
        _fail("SOURCE_FIELD")
    return (commit, lock_digest, lock_bytes)


def _check_target(value: Any) -> BundleTarget:
    target = _exact_keys(value, _TARGET_KEYS, "TARGET_FIELD")
    if (
        target["implementation"] != _IMPLEMENTATION
        or target["pythonVersion"] != _PYTHON_VERSION
        or target["os"] != _TARGET_OS
        or target["architecture"] != _ARCHITECTURE
        or target["libcFamily"] != _LIBC_FAMILY
    ):
        _fail("TARGET_FIELD")
    libc_version = target["libcVersion"]
    platform_tag = target["platformTag"]
    if (
        not isinstance(libc_version, str)
        or not _TOKEN.fullmatch(libc_version)
        or not isinstance(platform_tag, str)
        or not _TOKEN.fullmatch(platform_tag)
    ):
        _fail("TARGET_FIELD")
    return BundleTarget(
        implementation=_IMPLEMENTATION,
        python_version=_PYTHON_VERSION,
        os=_TARGET_OS,
        architecture=_ARCHITECTURE,
        libc_family=_LIBC_FAMILY,
        libc_version=libc_version,
        platform_tag=platform_tag,
    )


def _check_toolchain(value: Any) -> None:
    toolchain = _exact_keys(value, _TOOLCHAIN_KEYS, "TOOLCHAIN_FIELD")
    if toolchain["uvVersion"] != _UV_VERSION:
        _fail("TOOLCHAIN_FIELD")
    for key in ("uvSha256", "buildPythonSha256", "backendInventorySha256"):
        digest = toolchain[key]
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            _fail("TOOLCHAIN_FIELD")
    build_python = toolchain["buildPythonVersion"]
    if not isinstance(build_python, str) or not build_python.startswith(_BUILD_PYTHON_PREFIX):
        _fail("TOOLCHAIN_FIELD")


def _check_files(value: Any) -> tuple[BoundBundleFile, ...]:
    if not isinstance(value, list) or not value:
        _fail("FILES_ENTRY")
    records: list[BoundBundleFile] = []
    seen: set[str] = set()
    lock_count = 0
    requirements_count = 0
    wheel_count = 0
    declared_total = 0
    for item in value:
        row = _exact_keys(item, _FILE_KEYS, "FILES_ENTRY")
        relative = row["relativePath"]
        digest = row["sha256"]
        size = row["bytes"]
        kind = row["kind"]
        if not isinstance(relative, str) or not _check_safe_name(relative):
            _fail("FILES_PATH")
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            _fail("FILES_DIGEST")
        if type(size) is not int or size <= 0:
            _fail("FILES_ENTRY")
        if not isinstance(kind, str):
            _fail("FILES_ENTRY")
        if kind == "lock":
            if relative != "uv.lock":
                _fail("FILES_PATH")
            lock_count += 1
        elif kind == "requirements":
            if relative != "requirements.txt":
                _fail("FILES_PATH")
            requirements_count += 1
        elif kind in _FILE_WHEEL_KINDS:
            if not relative.startswith("wheels/") or "/" in relative[7:] or not relative[7:]:
                _fail("FILES_PATH")
            _parse_wheel_filename(relative[7:], "FILES_PATH")
            if size > _MAX_WHEEL_BYTES:
                _fail("FILES_SIZE")
            wheel_count += 1
        else:
            _fail("FILES_KIND")
        if relative in seen:
            _fail("FILES_ENTRY")
        seen.add(relative)
        declared_total += size
        records.append(
            BoundBundleFile(relative_path=relative, sha256=digest, bytes=size, kind=kind)
        )
    if lock_count != 1 or requirements_count != 1 or wheel_count < 1:
        _fail("FILES_INVENTORY")
    if wheel_count > _MAX_WHEELS:
        _fail("WHEELS_LIMIT")
    if declared_total > _MAX_BUNDLE_BYTES:
        _fail("BUNDLE_SIZE")
    return tuple(records)


def _abi3_python_ok(python_tag: str) -> bool:
    # Stable-ABI (abi3) wheels built against an older CPython 3.x floor run on
    # the fixed 3.12 target: accept cp3<minor> with minor <= 12, reject newer
    # floors such as cp313 whose ABI the target cannot satisfy.
    for part in python_tag.split("."):
        matched = _ABI3_FLOOR.fullmatch(part)
        if matched is not None and int(matched.group(1)) <= 12:
            return True
    return False


def _check_external_tags(python_tag: str, abi_tag: str, platform_tag: str) -> None:
    python_parts = python_tag.split(".")
    if not any(part == "py3" or part.startswith("cp312") for part in python_parts) and (
        abi_tag != "abi3" or not _abi3_python_ok(python_tag)
    ):
        _fail("DISTRIBUTION_TAGS")
    if abi_tag not in ("none", "abi3") and not abi_tag.startswith("cp312"):
        _fail("DISTRIBUTION_TAGS")
    if (
        platform_tag != "any"
        and "linux" not in platform_tag
        and "manylinux" not in platform_tag
        and "aarch64" not in platform_tag
    ):
        _fail("DISTRIBUTION_TAGS")


def _check_distributions(
    value: Any, files: tuple[BoundBundleFile, ...]
) -> tuple[_Distribution, ...]:
    if not isinstance(value, list) or not value:
        _fail("DISTRIBUTION_FIELD")
    by_path = {row.relative_path: row for row in files}
    seen: set[str] = set()
    distributions: list[_Distribution] = []
    for item in value:
        row = _exact_keys(item, _DISTRIBUTION_KEYS, "DISTRIBUTION_FIELD")
        name = row["name"]
        version = row["version"]
        kind = row["kind"]
        wheel = row["wheel"]
        python_tag = row["pythonTag"]
        abi_tag = row["abiTag"]
        platform_tag = row["platformTag"]
        for field in (name, version, python_tag, abi_tag, platform_tag):
            if not isinstance(field, str) or not _TOKEN.fullmatch(field):
                _fail("DISTRIBUTION_FIELD")
        if kind not in ("workspace", "external"):
            _fail("DISTRIBUTION_FIELD")
        normalized = _normalized(name)
        if normalized in seen:
            _fail("DISTRIBUTION_DUPLICATE")
        seen.add(normalized)
        if not isinstance(wheel, str) or wheel not in by_path:
            _fail("DISTRIBUTION_WHEEL")
        record = by_path[wheel]
        expected_file_kind = "workspace-wheel" if kind == "workspace" else "external-wheel"
        if record.kind != expected_file_kind:
            _fail("DISTRIBUTION_WHEEL")
        if not wheel.startswith("wheels/"):
            _fail("DISTRIBUTION_WHEEL")
        parsed = _parse_wheel_filename(wheel[7:], "DISTRIBUTION_WHEEL")
        if _normalized(parsed[0]) != normalized:
            _fail("DISTRIBUTION_NAME")
        if parsed[1] != version:
            _fail("DISTRIBUTION_VERSION")
        if (parsed[2], parsed[3], parsed[4]) != (python_tag, abi_tag, platform_tag):
            _fail("DISTRIBUTION_TAGS")
        if kind == "workspace":
            if not (python_tag == "py3" and abi_tag == "none" and platform_tag == "any"):
                _fail("DISTRIBUTION_TAGS")
        else:
            _check_external_tags(python_tag, abi_tag, platform_tag)
        distributions.append(
            _Distribution(
                name=name,
                version=version,
                kind=kind,
                wheel=wheel,
                python_tag=python_tag,
                abi_tag=abi_tag,
                platform_tag=platform_tag,
            )
        )
    file_wheels = {row.relative_path for row in files if row.kind in _FILE_WHEEL_KINDS}
    dist_wheels = {row.wheel for row in distributions}
    if file_wheels != dist_wheels:
        _fail("DISTRIBUTION_FILES")
    return tuple(distributions)


def _check_entrypoints(value: Any) -> tuple[FixedEntryPoint, ...]:
    if not isinstance(value, list):
        _fail("ENTRYPOINTS")
    observed: set[tuple[str, str, str]] = set()
    points: list[FixedEntryPoint] = []
    for item in value:
        row = _exact_keys(item, _ENTRYPOINT_KEYS, "ENTRYPOINTS")
        name = row["name"]
        module = row["module"]
        function = row["function"]
        if (
            not isinstance(name, str)
            or not isinstance(module, str)
            or not isinstance(function, str)
        ):
            _fail("ENTRYPOINTS")
        observed.add((name, module, function))
        points.append(FixedEntryPoint(name=name, module=module, function=function))
    if observed != _FIXED_ENTRYPOINT_SET:
        _fail("ENTRYPOINTS")
    return tuple(points)


def _parse_eocd(data: bytes) -> tuple[int, int, int]:
    """Return (entry count, central-directory size, central-directory offset)."""
    signature = b"PK\x05\x06"
    start = max(0, len(data) - 65535 - 22)
    cursor = len(data)
    while True:
        index = data.rfind(signature, start, cursor)
        if index < 0:
            _fail("WHEEL_NOT_ZIP")
        tail = data[index:]
        if len(tail) >= 22 and len(tail) == 22 + int(struct.unpack_from("<H", tail, 20)[0]):
            disk = int(struct.unpack_from("<H", tail, 4)[0])
            start_disk = int(struct.unpack_from("<H", tail, 6)[0])
            this_disk = int(struct.unpack_from("<H", tail, 8)[0])
            total = int(struct.unpack_from("<H", tail, 10)[0])
            size = int(struct.unpack_from("<I", tail, 12)[0])
            offset = int(struct.unpack_from("<I", tail, 16)[0])
            if disk == 0 and start_disk == 0 and this_disk == total:
                return (total, size, offset)
            _fail("WHEEL_EOCD")
        cursor = index


def _check_zip_entries(
    infos: list[zipfile.ZipInfo], budgets: _Budgets
) -> dict[str, zipfile.ZipInfo]:
    by_name: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        name = info.filename
        if not _check_safe_name(name):
            _fail("WHEEL_NAME")
        if name in by_name:
            _fail("WHEEL_DUPLICATE")
        by_name[name] = info
        if info.flag_bits & 0x1:
            _fail("WHEEL_ENCRYPTED")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            _fail("WHEEL_SYMLINK")
        if info.is_dir():
            if info.file_size != 0 or mode not in (0, 0o040000):
                _fail("WHEEL_ENTRY")
        else:
            if mode not in (0, 0o100000):
                _fail("WHEEL_ENTRY")
            if info.file_size < 0:
                _fail("WHEEL_ENTRY")
        if info.file_size > _MAX_EXPANDED_BYTES:
            _fail("EXPANDED_SIZE")
        if budgets.expanded_bytes + info.file_size > _MAX_EXPANDED_BYTES:
            _fail("EXPANDED_TOTAL")
        budgets.expanded_bytes += info.file_size
    return by_name


def _read_metadata(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, budgets: _Budgets
) -> bytes:
    if info.file_size > _MAX_METADATA_BYTES:
        _fail("METADATA_SIZE")
    if budgets.metadata_bytes + info.file_size > _MAX_METADATA_BYTES * _MAX_WHEELS:
        _fail("METADATA_BUDGET")
    # Never trust the central-directory size for the actual stream: the
    # decompressor truncates output to ZipInfo.file_size, so cap a copy of the
    # entry one byte past the limit and count real decompressed bytes instead.
    # CRC is disabled on the copy because the stdlib checks it against the
    # truncated prefix; integrity is bound downstream by the RECORD digest.
    bounded = copy.copy(info)
    bounded.file_size = _MAX_METADATA_BYTES + 1
    bounded.CRC = None  # type: ignore[assignment]
    chunks: list[bytes] = []
    total = 0
    try:
        with archive.open(bounded) as handle:
            while True:
                try:
                    chunk = handle.read(_READ_CHUNK_BYTES)
                except (
                    zipfile.BadZipFile,
                    RuntimeError,
                    OSError,
                    struct.error,
                    ValueError,
                ) as error:
                    raise BundleEvidenceError("METADATA_READ") from error
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_METADATA_BYTES:
                    _fail("METADATA_SIZE")
                if budgets.metadata_bytes + total > _MAX_METADATA_BYTES * _MAX_WHEELS:
                    _fail("METADATA_BUDGET")
                chunks.append(chunk)
    except BundleEvidenceError:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError, struct.error, ValueError) as error:
        raise BundleEvidenceError("METADATA_READ") from error
    budgets.metadata_bytes += total
    return b"".join(chunks)


def _check_metadata_text(payload: bytes, code: str) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeError as error:
        raise BundleEvidenceError(code) from error


def _check_dist_info_metadata(
    text: str, distribution: _Distribution, normalized: str
) -> None:
    name_value: str | None = None
    version_value: str | None = None
    last_key: str | None = None
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            break
        if ":" not in line:
            if last_key in (None, "name", "version") or raw[:1] not in (" ", "\t"):
                _fail("METADATA_FIELD")
            continue
        key, _, field = line.partition(":")
        key = key.strip().lower()
        field = field.strip()
        last_key = key
        if key == "name":
            if name_value is not None:
                _fail("METADATA_FIELD")
            name_value = field
        elif key == "version":
            if version_value is not None:
                _fail("METADATA_FIELD")
            version_value = field
    if name_value is None or version_value is None:
        _fail("METADATA_FIELD")
    assert name_value is not None and version_value is not None
    if _normalized(name_value) != normalized:
        _fail("METADATA_NAME")
    if version_value != distribution.version:
        _fail("METADATA_VERSION")


def _check_wheel_metadata(text: str, distribution: _Distribution) -> None:
    purelib: str | None = None
    tags: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            _fail("WHEEL_FIELD")
        key, _, field = line.partition(":")
        key = key.strip().lower()
        field = field.strip()
        if key == "root-is-purelib":
            if purelib is not None:
                _fail("WHEEL_FIELD")
            purelib = field.lower()
        elif key == "tag":
            tags.append(field)
    if purelib not in ("true", "false"):
        _fail("WHEEL_FIELD")
    if distribution.kind == "workspace" and purelib != "true":
        _fail("WHEEL_PURELIB")
    if not tags:
        _fail("WHEEL_TAG")
    python_set = set(distribution.python_tag.split("."))
    abi_set = set(distribution.abi_tag.split("."))
    platform_set = set(distribution.platform_tag.split("."))
    for tag in tags:
        parts = tag.split("-")
        if len(parts) != 3:
            _fail("WHEEL_TAG")
        if (
            not set(parts[0].split(".")) <= python_set
            or not set(parts[1].split(".")) <= abi_set
            or not set(parts[2].split(".")) <= platform_set
        ):
            _fail("WHEEL_TAG")


def _parse_entry_points(text: str) -> dict[str, str]:
    section: str | None = None
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if section != "console_scripts":
            continue
        if "=" not in line:
            _fail("ENTRYPOINT_SYNTAX")
        entry, _, target = line.partition("=")
        entry = entry.strip()
        target = target.strip()
        if not entry or ":" not in target:
            _fail("ENTRYPOINT_SYNTAX")
        module, _, function = target.partition(":")
        module = module.strip()
        function = function.strip()
        if not module or not function or ":" in function:
            _fail("ENTRYPOINT_SYNTAX")
        result[entry] = module + ":" + function
    return result


def _check_record(
    text: str,
    record_name: str,
    by_name: dict[str, zipfile.ZipInfo],
    read_payloads: dict[str, bytes],
    archive: zipfile.ZipFile,
) -> None:
    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as error:
        raise BundleEvidenceError("RECORD_ROW") from error
    entries: dict[str, tuple[str, str]] = {}
    for row in rows:
        if len(row) != 3:
            _fail("RECORD_ROW")
        row_path, row_hash, row_size = row
        if not _check_safe_name(row_path):
            _fail("RECORD_PATH")
        if row_path in entries:
            _fail("RECORD_DUPLICATE")
        entries[row_path] = (row_hash, row_size)
    own = entries.get(record_name)
    if own is None or own != ("", ""):
        _fail("RECORD_SELF")
    file_names = {name for name, info in by_name.items() if not info.is_dir()}
    if set(entries.keys()) != file_names:
        _fail("RECORD_COVERAGE")
    for row_path, (row_hash, row_size) in entries.items():
        if row_path == record_name:
            continue
        if row_path in read_payloads:
            payload = read_payloads[row_path]
            if _record_digest(payload) != row_hash:
                _fail("RECORD_HASH")
            if row_size != str(len(payload)):
                _fail("RECORD_SIZE")
        else:
            if not _RECORD_HASH.fullmatch(row_hash):
                _fail("RECORD_HASH")
            if not _RECORD_SIZE.fullmatch(row_size):
                _fail("RECORD_SIZE")
            if int(row_size) != by_name[row_path].file_size:
                _fail("RECORD_SIZE")
            if row_size == "0":
                _require_empty_entry(archive, by_name[row_path], row_hash)
            elif row_hash == _EMPTY_RECORD_DIGEST:
                _fail("RECORD_SIZE")


def _require_empty_entry(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, row_hash: str
) -> None:
    """Prove a RECORD-claimed empty file is really empty with a 1-byte probe."""
    if row_hash != _EMPTY_RECORD_DIGEST:
        _fail("RECORD_HASH")
    probe = copy.copy(info)
    probe.file_size = 1
    try:
        handle = archive.open(probe)
    except (zipfile.BadZipFile, RuntimeError, OSError, struct.error, ValueError) as error:
        raise BundleEvidenceError("RECORD_READ") from error
    try:
        try:
            chunk = handle.read(1)
        except (
            zipfile.BadZipFile,
            RuntimeError,
            OSError,
            struct.error,
            ValueError,
        ) as error:
            raise BundleEvidenceError("RECORD_READ") from error
        if chunk:
            _fail("RECORD_SIZE")
    finally:
        with contextlib.suppress(
            zipfile.BadZipFile, RuntimeError, OSError, struct.error, ValueError
        ):
            handle.close()


def _inspect_wheel(payload: bytes, distribution: _Distribution, budgets: _Budgets) -> None:
    count, central_size, central_offset = _parse_eocd(payload)
    if count > _MAX_ZIP_ENTRIES:
        _fail("ZIP_ENTRIES")
    if central_size > _MAX_ZIP_CENTRAL_BYTES:
        _fail("ZIP_CENTRAL")
    if central_offset + central_size > len(payload):
        _fail("WHEEL_OFFSET")
    if count < 1:
        _fail("WHEEL_ENTRIES")
    if budgets.zip_entries + count > _MAX_ZIP_TOTAL_ENTRIES:
        _fail("ZIP_TOTAL_ENTRIES")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
        infos = archive.infolist()
    except (zipfile.BadZipFile, struct.error, ValueError, RuntimeError) as error:
        raise BundleEvidenceError("WHEEL_CORRUPT") from error
    if len(infos) != count:
        _fail("WHEEL_COUNT")
    budgets.zip_entries += len(infos)
    by_name = _check_zip_entries(infos, budgets)
    normalized = _normalized(distribution.name)
    info_dir = normalized + "-" + distribution.version + ".dist-info"
    metadata_name = info_dir + "/METADATA"
    wheel_name = info_dir + "/WHEEL"
    record_name = info_dir + "/RECORD"
    entry_name = info_dir + "/entry_points.txt"
    for required, code in (
        (metadata_name, "METADATA_MISSING"),
        (wheel_name, "METADATA_MISSING"),
        (record_name, "RECORD_MISSING"),
    ):
        if required not in by_name:
            _fail(code)
    is_controller = normalized == _CONTROLLER_NORMALIZED
    if is_controller and entry_name not in by_name:
        _fail("ENTRYPOINT_MISSING")
    read_payloads: dict[str, bytes] = {}
    read_payloads[metadata_name] = _read_metadata(archive, by_name[metadata_name], budgets)
    read_payloads[wheel_name] = _read_metadata(archive, by_name[wheel_name], budgets)
    if entry_name in by_name:
        read_payloads[entry_name] = _read_metadata(archive, by_name[entry_name], budgets)
    _check_dist_info_metadata(
        _check_metadata_text(read_payloads[metadata_name], "METADATA_FIELD"),
        distribution,
        normalized,
    )
    _check_wheel_metadata(
        _check_metadata_text(read_payloads[wheel_name], "WHEEL_FIELD"), distribution
    )
    if entry_name in by_name:
        parsed = _parse_entry_points(
            _check_metadata_text(read_payloads[entry_name], "ENTRYPOINT_SYNTAX")
        )
        if is_controller:
            for fixed_name, fixed_module, fixed_function in _FIXED_ENTRYPOINTS:
                if parsed.get(fixed_name) != fixed_module + ":" + fixed_function:
                    _fail("ENTRYPOINT_MISMATCH")
    record_payload = _read_metadata(archive, by_name[record_name], budgets)
    _check_record(
        _check_metadata_text(record_payload, "RECORD_ROW"),
        record_name,
        by_name,
        read_payloads,
        archive,
    )


def verify_application_bundle(
    path: Path,
    *,
    expected_manifest_sha256: str,
    expected_source_commit: str,
    expected_lock_sha256: str,
) -> VerifiedApplicationBundle:
    """Statically verify an offline application bundle; never execute it."""
    if (
        not isinstance(expected_manifest_sha256, str)
        or not _DIGEST.fullmatch(expected_manifest_sha256)
        or not isinstance(expected_source_commit, str)
        or not _COMMIT.fullmatch(expected_source_commit)
        or not isinstance(expected_lock_sha256, str)
        or not _DIGEST.fullmatch(expected_lock_sha256)
    ):
        _fail("EXPECTED_BINDING")
    parent_fd: int | None = None
    root_fd: int | None = None
    wheels_fd: int | None = None
    try:
        parent_fd = _open_parent(path)
        root_fd = os.open(
            path.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        if set(os.listdir(root_fd)) != _ROOT_NAMES:
            _fail("INVENTORY")
        root_snapshot: dict[str, tuple[int, ...]] = {}
        for name in ("manifest.json", "uv.lock", "requirements.txt", "wheels"):
            node = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            if name == "wheels":
                if not stat.S_ISDIR(node.st_mode):
                    _fail("INPUT_FILE")
            elif not stat.S_ISREG(node.st_mode):
                _fail("INPUT_FILE")
            root_snapshot[name] = _identity(node)
        wheels_fd = os.open(
            "wheels",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=root_fd,
        )
        wheel_snapshot: dict[str, tuple[int, ...]] = {}
        for name in os.listdir(wheels_fd):
            node = os.stat(name, dir_fd=wheels_fd, follow_symlinks=False)
            if not stat.S_ISREG(node.st_mode):
                _fail("INPUT_FILE")
            wheel_snapshot[name] = _identity(node)
        total_read = 0

        def _read_bounded(
            dir_fd: int, name: str, ident: tuple[int, ...], limit: int, code: str
        ) -> bytes:
            """Read one bundle file while enforcing the whole-request READ budget."""
            nonlocal total_read
            try:
                node = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            except OSError as error:
                raise BundleEvidenceError("INPUT_OPEN") from error
            if node.st_size < 0 or total_read + node.st_size > _MAX_TOTAL_READ_BYTES:
                _fail("READ_TOTAL")
            data = _read_file(dir_fd, name, ident, limit, code)
            total_read += len(data)
            if total_read > _MAX_TOTAL_READ_BYTES:
                _fail("READ_TOTAL")
            return data

        manifest_payload = _read_bounded(
            root_fd, "manifest.json", root_snapshot["manifest.json"], _MAX_JSON_BYTES, "JSON_SIZE"
        )
        if _digest_text(manifest_payload) != expected_manifest_sha256:
            _fail("MANIFEST_HASH")
        manifest = _parse_manifest(manifest_payload)
        if set(manifest.keys()) != _ROOT_KEYS:
            _fail("MANIFEST_SCHEMA")
        if manifest["schemaVersion"] != _SCHEMA_VERSION:
            _fail("MANIFEST_SCHEMA")
        source_commit, lock_digest, lock_bytes = _check_source(
            manifest["source"], expected_source_commit, expected_lock_sha256
        )
        target = _check_target(manifest["target"])
        _check_toolchain(manifest["buildToolchain"])
        files = _check_files(manifest["files"])
        distributions = _check_distributions(manifest["distributions"], files)
        entrypoints = _check_entrypoints(manifest["entrypoints"])
        wheel_basenames = {
            row.relative_path[7:] for row in files if row.kind in _FILE_WHEEL_KINDS
        }
        if set(wheel_snapshot.keys()) != wheel_basenames:
            _fail("INVENTORY")
        by_path = {row.relative_path: row for row in files}
        if by_path["uv.lock"].sha256 != lock_digest or by_path["uv.lock"].bytes != lock_bytes:
            _fail("SOURCE_LOCK")
        requirements_record = by_path["requirements.txt"]
        lock_payload = _read_bounded(
            root_fd, "uv.lock", root_snapshot["uv.lock"], _MAX_BUNDLE_BYTES, "FILE_SIZE"
        )
        requirements_payload = _read_bounded(
            root_fd,
            "requirements.txt",
            root_snapshot["requirements.txt"],
            _MAX_BUNDLE_BYTES,
            "FILE_SIZE",
        )
        if _digest_text(lock_payload) != lock_digest or len(lock_payload) != lock_bytes:
            _fail("SOURCE_LOCK")
        if (
            _digest_text(requirements_payload) != requirements_record.sha256
            or len(requirements_payload) != requirements_record.bytes
        ):
            _fail("FILE_HASH")
        budgets = _Budgets()
        for distribution in distributions:
            record = by_path[distribution.wheel]
            wheel_payload = _read_bounded(
                wheels_fd,
                distribution.wheel[7:],
                wheel_snapshot[distribution.wheel[7:]],
                _MAX_WHEEL_BYTES,
                "WHEEL_SIZE",
            )
            if (
                _digest_text(wheel_payload) != record.sha256
                or len(wheel_payload) != record.bytes
            ):
                _fail("FILE_HASH")
            _inspect_wheel(wheel_payload, distribution, budgets)
        _sweep(root_fd, root_snapshot)
        _sweep(wheels_fd, wheel_snapshot)
        return VerifiedApplicationBundle(
            bundle_root=path,
            manifest_sha256=expected_manifest_sha256,
            source_commit=source_commit,
            lock_sha256=lock_digest,
            target=target,
            files=files,
            entrypoints=entrypoints,
        )
    except BundleEvidenceError:
        raise
    except (OSError, ValueError, RecursionError, struct.error, zipfile.BadZipFile,
            csv.Error) as error:
        raise BundleEvidenceError("INPUT_INVALID") from error
    finally:
        if wheels_fd is not None:
            os.close(wheels_fd)
        if root_fd is not None:
            os.close(root_fd)
        if parent_fd is not None:
            os.close(parent_fd)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--lock-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_application_bundle(
            args.bundle,
            expected_manifest_sha256=args.manifest_sha256,
            expected_source_commit=args.source_commit,
            expected_lock_sha256=args.lock_sha256,
        )
    except BundleEvidenceError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:  # fail closed; never leak paths or contents
        raise BundleEvidenceError("INTERNAL") from error
    payload = {
        "status": "BUNDLE_BYTES_VERIFIED",
        "sourceCommit": result.source_commit,
        "manifestSha256": result.manifest_sha256,
    }
    print(json.dumps(payload, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
