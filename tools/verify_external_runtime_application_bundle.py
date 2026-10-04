#!/usr/bin/env python3
"""Protected Python binding verification and private installation preparation.

Static verification of an independently supplied
``external-runtime-python-binding.v1`` record never executes anything: it
rechecks operator ownership, exact keys, the allowed runtime root prefix,
root-owned non-writable ancestors, full file inventories and the actual
interpreter bytes before any probe. Only ``prepare_application_installation``
may create processes, and only after revalidating every actual-use identity:
a new private destination is staged from verified wheel bytes, a fresh
non-editable environment is created with the verified explicit interpreter
(never a copied venv), staged wheels are installed offline with hashes, and
a fixed probe with a clean isolated environment gates the receipt. Any
failure retains the owned destination path with a typed blocker; nothing is
deleted broadly and nothing is installed globally.

Stdlib only. Safe typed errors only: no paths, digests or file contents in
diagnostics.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import math
import os
import posixpath
import re
import shutil
import signal
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn


def _load_task1() -> Any:
    existing = sys.modules.get("external_runtime_application_bundle")
    if existing is not None:
        return existing
    path = Path(__file__).resolve().parent / "external_runtime_application_bundle.py"
    spec = importlib.util.spec_from_file_location(
        "external_runtime_application_bundle", path
    )
    if spec is None or spec.loader is None or not path.is_file():
        raise RuntimeError("task1 bundle tool is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_task1 = _load_task1()
BundleEvidenceError = _task1.BundleEvidenceError
BundleTarget = _task1.BundleTarget
VerifiedApplicationBundle = _task1.VerifiedApplicationBundle
verify_application_bundle = _task1.verify_application_bundle

# Ownership seam: production requires root-owned runtime files and ancestors.
# Tests monkeypatch this to the current user with synthetic trees. The CLI
# never accepts a uid/root override flag.
_REQUIRED_RUNTIME_UID = 0
# Root seam: only these protected prefixes are accepted. Tests monkeypatch
# this to synthetic tmp prefixes. The CLI never accepts a root override flag.
_ALLOWED_RUNTIME_ROOTS = (
    "/usr/local/lib/ksi-external-runtime/python",
    "/opt/ksi-external-runtime/python",
)

_SCHEMA_VERSION = "external-runtime-python-binding.v1"
_PREPARATION_SCHEMA = "external-runtime-preparation.v1"
_IMPLEMENTATION = "CPython"
_PYTHON_VERSION = "3.12.15"
_TARGET_OS = "linux"
_ARCHITECTURE = "arm64"
_LIBC_FAMILY = "glibc"
_UV_VERSION = "0.11.15"

_MAX_BINDING_BYTES = 8 * 1024**2
_MAX_RUNTIME_FILES = 8192
_MAX_RUNTIME_BYTES = 1024**3
_MAX_NATIVE_ENTRIES = 512
_MAX_ANCESTOR_STEPS = 16
_MAX_EXPANDED_BYTES = 4 * 1024**3
_MAX_REQUEST_READ_BYTES = 1024**3 + 32 * 1024**2
_READ_CHUNK_BYTES = 1024**2
_PROBE_TIMEOUT_S = 15
_MAX_PROBE_BYTES = 64 * 1024
_VENV_TIMEOUT_S = 180
_INSTALL_TIMEOUT_S = 300
_TOOL_TIMEOUT_S = 30
_MAX_TOOL_OUTPUT = 1024**2
_PLANNED_BIN_PREFIX = "/usr/local/lib/ksi-external-runtime/bin/"

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

_TOOL_FILES = (
    "external_runtime_application_bundle.py",
    "build_external_runtime_application_bundle.py",
    "verify_external_runtime_application_bundle.py",
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_.+~-]+\Z")

_ROOT_KEYS = frozenset({
    "schemaVersion",
    "interpreter",
    "target",
    "runtimeRoot",
    "inventorySha256",
    "inventory",
    "nativeInventorySha256",
    "nativeInventory",
})
_INTERPRETER_KEYS = frozenset({"path", "sha256", "bytes", "version", "implementation"})
_TARGET_KEYS = frozenset({
    "implementation",
    "pythonVersion",
    "os",
    "architecture",
    "libcFamily",
    "libcVersion",
    "platformTag",
})
_ENTRY_KEYS = frozenset({"path", "sha256", "bytes"})
_PROBE_KEYS = frozenset({
    "implementation",
    "version",
    "os",
    "architecture",
    "libcFamily",
    "libcVersion",
    "entrypointsOk",
})

_FIXED_PROBE_SOURCE = (
    "import json,platform,sys\n"
    "_mods=['ksi_processing_controller.external_inspector_daemon',"
    "'ksi_processing_controller.external_measurement_daemon',"
    "'ksi_processing_controller.external_validation_worker']\n"
    "_ok=True\n"
    "for _m in _mods:\n"
    " try:\n"
    "  __import__(_m)\n"
    " except Exception:\n"
    "  _ok=False\n"
    "_fam,_ver=platform.libc_ver()\n"
    "_machine=platform.machine()\n"
    "_impl=sys.implementation.name\n"
    "_impl='CPython' if _impl=='cpython' else _impl\n"
    "print(json.dumps({'implementation':_impl,"
    "'version':platform.python_version(),"
    "'os':'linux' if sys.platform.startswith('linux') else sys.platform,"
    "'architecture':{'aarch64':'arm64','arm64':'arm64'}.get(_machine,_machine),"
    "'libcFamily':_fam,'libcVersion':_ver,'entrypointsOk':_ok},"
    "separators=(',',':')))\n"
)

_UNSET_WRAPPER_VARS = (
    "PYTHONPATH PYTHONHOME PYTHONUSERBASE PYTHONSTARTUP VIRTUAL_ENV "
    "UV_INDEX_URL UV_EXTRA_INDEX_URL UV_INDEX UV_OFFLINE UV_PYTHON_DOWNLOADS "
    "PIP_INDEX_URL PIP_EXTRA_INDEX_URL PIP_NO_INDEX "
    "CONDA_PREFIX CONDA_DEFAULT_ENV VIRTUALENV_OVERRIDE_APP_DATA "
    "PYTHONBREAKPOINT PYTHONSAFEPATH"
)


@dataclass(frozen=True)
class ToolFileDigest:
    relative_path: str
    sha256: str


@dataclass(frozen=True)
class VerificationCodeSnapshot:
    commit_sha: str
    files: tuple[ToolFileDigest, ...]


@dataclass(frozen=True)
class VerifiedPythonRuntime:
    interpreter: Path
    runtime_root: Path
    interpreter_sha256: str
    inventory_sha256: str
    native_inventory_sha256: str
    target: Any


@dataclass(frozen=True)
class _RuntimeEntry:
    """One declared runtime-root inventory row: a file or a resolved symlink."""

    path: str
    kind: str  # "file" or "symlink"
    sha256: str  # "" for symlinks: links contribute no hash
    size: int  # 0 for symlinks
    target: str  # "" for files: normalized path relative to the link's parent

@dataclass(frozen=True)
class PreparationReceipt:
    bundle_sha256: str
    source_commit: str
    python_binding_sha256: str
    prepared_inventory_sha256: str
    status: str
    verification_code: VerificationCodeSnapshot


class _Budget:
    """Whole-request counters enforced before unbounded work."""

    def __init__(self) -> None:
        self.files = 0
        self.dirs = 0
        self.total_bytes = 0
        self.read_bytes = 0


def _fail(code: str) -> NoReturn:
    raise BundleEvidenceError(code)


def _identity(node: os.stat_result) -> tuple[int, ...]:
    return (node.st_dev, node.st_ino, node.st_size, node.st_mtime_ns, node.st_ctime_ns)


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _lstat(path: str, code: str) -> os.stat_result:
    try:
        return os.lstat(path)
    except OSError as error:
        raise BundleEvidenceError(code) from error


def _canonical_absolute(text: Any, code: str) -> str:
    if not isinstance(text, str) or not text or "\0" in text:
        _fail(code)
    assert isinstance(text, str)
    if not text.startswith("/") or ".." in text.split("/"):
        _fail(code)
    if posixpath.normpath(text) != text:
        _fail(code)
    return text


def _match_prefix(root: str) -> str:
    for prefix in _ALLOWED_RUNTIME_ROOTS:
        if root == prefix or root.startswith(prefix + "/"):
            return prefix
    _fail("ROOT_PREFIX")
    raise AssertionError("unreachable")


def _under(path: str, root: str) -> bool:
    return path.startswith(root + "/")


def _check_dir_chain(start: str, stop: str) -> None:
    """Check start dir and every ancestor up to and including stop."""
    current = start
    steps = 0
    while True:
        steps += 1
        if steps > _MAX_ANCESTOR_STEPS:
            _fail("ANCESTOR_DEPTH")
        node = _lstat(current, "ANCESTOR_STAT")
        if stat.S_ISLNK(node.st_mode):
            _fail("ANCESTOR_SYMLINK")
        if not stat.S_ISDIR(node.st_mode):
            _fail("ANCESTOR_TYPE")
        if node.st_uid != _REQUIRED_RUNTIME_UID:
            _fail("ANCESTOR_OWNER")
        if node.st_mode & 0o022:
            _fail("ANCESTOR_WRITABLE")
        if current == stop:
            return
        parent = posixpath.dirname(current)
        if parent == current:
            _fail("ANCESTOR_SCOPE")
        current = parent


def _check_chain(path: str, stop: str) -> None:
    parent = posixpath.dirname(path)
    if not parent:
        _fail("ANCESTOR_SCOPE")
    _check_dir_chain(parent, stop)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            _fail("BINDING_DUPLICATE")
        result[key] = value
    return result


def _checked_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        _fail("BINDING_NONFINITE")
    return result


def _reject_constant(value: str) -> NoReturn:
    _fail("BINDING_NONFINITE")


def _parse_binding(payload: bytes) -> dict[str, Any]:
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
        raise BundleEvidenceError("BINDING_JSON") from error
    if not isinstance(value, dict):
        _fail("BINDING_JSON")
    return value


def _exact_keys(value: Any, keys: frozenset[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value.keys()) != set(keys):
        _fail(code)
    return value


def _inventory_hash(entries: list[tuple[str, str, int]]) -> str:
    lines = [f"{path}\x00{value}\x00{size}" for path, value, size in sorted(entries)]
    return "sha256:" + hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _runtime_inventory_hash(entries: list[_RuntimeEntry]) -> str:
    """Canonical inventory hash covering file bytes and symlink kind/target."""
    lines: list[str] = []
    for entry in entries:
        if entry.kind == "file":
            lines.append(f"{entry.path}\x00{entry.sha256}\x00{entry.size}")
        else:
            lines.append(f"{entry.path}\x00symlink\x00{entry.target}")
    return "sha256:" + hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def _check_link_target_shape(target: Any) -> str:
    """Declared symlink targets stay relative, normalized and inside the root."""
    if not isinstance(target, str) or not target or "\0" in target:
        _fail("LINK_TARGET")
    assert isinstance(target, str)
    if posixpath.isabs(target):
        _fail("LINK_TARGET")
    if posixpath.normpath(target) != target:
        _fail("LINK_TARGET")
    if ".." in target.split("/"):
        _fail("LINK_TARGET")
    return target


def _resolve_link_target(link_path: str, target: str, root: str) -> str:
    """Resolve a declared target against the link's parent; never escapes root."""
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(link_path), target))
    if resolved != root and not _under(resolved, root):
        _fail("LINK_TARGET")
    return resolved


def _parse_runtime_entries(value: Any) -> list[_RuntimeEntry]:
    """Parse the runtime-root inventory: files plus explicitly declared symlinks."""
    if not isinstance(value, list) or not value:
        _fail("INVENTORY_ENTRY")
    entries: list[_RuntimeEntry] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            _fail("INVENTORY_ENTRY")
        assert isinstance(item, dict)
        keys = set(item.keys())
        if keys == {"path", "sha256", "bytes"}:
            path = item["path"]
            digest_value = item["sha256"]
            size = item["bytes"]
            if not isinstance(path, str):
                _fail("INVENTORY_ENTRY")
            _canonical_absolute(path, "INVENTORY_ENTRY")
            if not isinstance(digest_value, str) or not _DIGEST.fullmatch(digest_value):
                _fail("INVENTORY_ENTRY")
            if type(size) is not int or size < 0:
                _fail("INVENTORY_ENTRY")
            row = _RuntimeEntry(
                path=path, kind="file", sha256=digest_value, size=size, target=""
            )
        elif keys == {"path", "kind", "target"}:
            path = item["path"]
            kind = item["kind"]
            if not isinstance(path, str):
                _fail("INVENTORY_ENTRY")
            _canonical_absolute(path, "INVENTORY_ENTRY")
            if kind != "symlink":
                _fail("INVENTORY_ENTRY")
            row = _RuntimeEntry(
                path=path,
                kind="symlink",
                sha256="",
                size=0,
                target=_check_link_target_shape(item["target"]),
            )
        else:
            _fail("INVENTORY_ENTRY")
        if row.path in seen:
            _fail("INVENTORY_DUPLICATE")
        seen.add(row.path)
        entries.append(row)
    return entries


def _hash_open_fd(fd: int, size: int, budget: _Budget) -> str:
    if budget.read_bytes + size > _MAX_REQUEST_READ_BYTES:
        _fail("REQUEST_BUDGET")
    digest = hashlib.sha256()
    remaining = size
    while remaining > 0:
        chunk = os.read(fd, min(remaining, _READ_CHUNK_BYTES))
        if not chunk:
            _fail("INPUT_SHORT_READ")
        digest.update(chunk)
        remaining -= len(chunk)
    budget.read_bytes += size
    return "sha256:" + digest.hexdigest()


def _open_regular(path: str, code: str) -> int:
    try:
        return os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as error:
        raise BundleEvidenceError(code) from error


def _charge_new_file(node: os.stat_result, budget: _Budget) -> None:
    budget.files += 1
    if budget.files > _MAX_RUNTIME_FILES:
        _fail("RUNTIME_FILES")
    if node.st_size < 0 or budget.total_bytes + node.st_size > _MAX_RUNTIME_BYTES:
        _fail("RUNTIME_SIZE")
    budget.total_bytes += node.st_size


def _hash_runtime_file(path: str, node: os.stat_result, budget: _Budget) -> str:
    """Hash an already lstat'ed regular file through a fresh no-follow fd."""
    _charge_new_file(node, budget)
    fd = _open_regular(path, "ENTRY_OPEN")
    try:
        fresh = os.fstat(fd)
        if not stat.S_ISREG(fresh.st_mode):
            _fail("ENTRY_TYPE")
        if (fresh.st_dev, fresh.st_ino) != (node.st_dev, node.st_ino):
            _fail("ENTRY_CHANGED")
        if fresh.st_uid != _REQUIRED_RUNTIME_UID:
            _fail("ENTRY_OWNER")
        if fresh.st_mode & 0o022:
            _fail("ENTRY_WRITABLE")
        return _hash_open_fd(fd, fresh.st_size, budget)
    finally:
        os.close(fd)


def _parse_entries(value: Any, code: str) -> list[tuple[str, str, int]]:
    if not isinstance(value, list) or not value:
        _fail(code)
    entries: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    for item in value:
        row = _exact_keys(item, _ENTRY_KEYS, code)
        path = row["path"]
        digest_value = row["sha256"]
        size = row["bytes"]
        if not isinstance(path, str):
            _fail(code)
        _canonical_absolute(path, code)
        if not isinstance(digest_value, str) or not _DIGEST.fullmatch(digest_value):
            _fail(code)
        if type(size) is not int or size < 0:
            _fail(code)
        if path in seen:
            _fail("INVENTORY_DUPLICATE")
        seen.add(path)
        entries.append((path, digest_value, size))
    return entries


def _check_target_shape(value: Any) -> dict[str, Any]:
    target = _exact_keys(value, _TARGET_KEYS, "TARGET_FIELD")
    for key in _TARGET_KEYS:
        if not isinstance(target[key], str):
            _fail("TARGET_FIELD")
    if (
        target["implementation"] != _IMPLEMENTATION
        or target["pythonVersion"] != _PYTHON_VERSION
        or target["os"] != _TARGET_OS
        or target["architecture"] != _ARCHITECTURE
        or target["libcFamily"] != _LIBC_FAMILY
    ):
        _fail("TARGET_FIELD")
    if not _TOKEN.fullmatch(target["libcVersion"]):
        _fail("TARGET_FIELD")
    if not _TOKEN.fullmatch(target["platformTag"]):
        _fail("TARGET_FIELD")
    return target


def _check_target_equal(record_target: dict[str, Any], target: Any) -> None:
    for field, key in (
        ("implementation", "implementation"),
        ("python_version", "pythonVersion"),
        ("os", "os"),
        ("architecture", "architecture"),
        ("libc_family", "libcFamily"),
        ("libc_version", "libcVersion"),
        ("platform_tag", "platformTag"),
    ):
        if getattr(target, field, None) != record_target[key]:
            _fail("TARGET_MISMATCH")


def verify_python_binding(
    path: Path, *, expected_sha256: str, target: Any
) -> VerifiedPythonRuntime:
    """Statically verify a protected Python binding; never executes anything."""
    if (
        not isinstance(expected_sha256, str)
        or not _DIGEST.fullmatch(expected_sha256)
        or not isinstance(path, Path)
    ):
        _fail("EXPECTED_BINDING")
    for field in (
        "implementation",
        "python_version",
        "os",
        "architecture",
        "libc_family",
        "libc_version",
        "platform_tag",
    ):
        if not isinstance(getattr(target, field, None), str):
            _fail("EXPECTED_BINDING")
    budget = _Budget()
    record_fd: int | None = None
    try:
        record_fd = _open_regular(str(path), "RECORD_OPEN")
        node = os.fstat(record_fd)
        if not stat.S_ISREG(node.st_mode):
            _fail("RECORD_TYPE")
        if node.st_nlink != 1:
            _fail("RECORD_LINKS")
        if node.st_uid != os.geteuid():
            _fail("RECORD_OWNER")
        if stat.S_IMODE(node.st_mode) not in (0o400, 0o600):
            _fail("RECORD_MODE")
        if node.st_size <= 0 or node.st_size > _MAX_BINDING_BYTES:
            _fail("BINDING_SIZE")
        payload = _hash_open_fd(record_fd, node.st_size, budget)
        after = os.fstat(record_fd)
        if _identity(after) != _identity(node):
            _fail("RECORD_CHANGED")
        named = _lstat(str(path), "RECORD_OPEN")
        if _identity(named) != _identity(node):
            _fail("RECORD_CHANGED")
        if payload != expected_sha256:
            _fail("BINDING_HASH")
        record = _parse_binding(_reread_record(str(path), node, budget))
    finally:
        if record_fd is not None:
            os.close(record_fd)
    if set(record.keys()) != _ROOT_KEYS:
        _fail("BINDING_SCHEMA")
    if record["schemaVersion"] != _SCHEMA_VERSION:
        _fail("BINDING_SCHEMA")
    interpreter = _exact_keys(record["interpreter"], _INTERPRETER_KEYS, "BINDING_SCHEMA")
    record_target = _check_target_shape(record["target"])
    _check_target_equal(record_target, target)
    interp_path = _canonical_absolute(interpreter["path"], "INTERPRETER_PATH")
    if (
        not isinstance(interpreter["sha256"], str)
        or not _DIGEST.fullmatch(interpreter["sha256"])
    ):
        _fail("INTERPRETER_FIELD")
    if type(interpreter["bytes"]) is not int or interpreter["bytes"] <= 0:
        _fail("INTERPRETER_FIELD")
    if (
        interpreter["version"] != _PYTHON_VERSION
        or interpreter["implementation"] != _IMPLEMENTATION
    ):
        _fail("INTERPRETER_VERSION")
    root = _canonical_absolute(record["runtimeRoot"], "RUNTIME_ROOT")
    prefix = _match_prefix(root)
    if not _under(interp_path, root):
        _fail("INTERPRETER_PATH")
    if (
        not isinstance(record["inventorySha256"], str)
        or not _DIGEST.fullmatch(record["inventorySha256"])
        or not isinstance(record["nativeInventorySha256"], str)
        or not _DIGEST.fullmatch(record["nativeInventorySha256"])
    ):
        _fail("BINDING_SCHEMA")
    entries = _parse_runtime_entries(record["inventory"])
    file_entries = [entry for entry in entries if entry.kind == "file"]
    link_entries = [entry for entry in entries if entry.kind == "symlink"]
    native_entries = _parse_entries(record["nativeInventory"], "NATIVE_ENTRY")
    if len(native_entries) > _MAX_NATIVE_ENTRIES:
        _fail("NATIVE_LIMIT")
    for entry in entries:
        if not _under(entry.path, root):
            _fail("INVENTORY_SCOPE")
        _check_chain(entry.path, root)
    if _runtime_inventory_hash(entries) != record["inventorySha256"]:
        _fail("INVENTORY_HASH")
    if _inventory_hash(native_entries) != record["nativeInventorySha256"]:
        _fail("NATIVE_HASH")
    _check_dir_chain(root, prefix)
    actual, actual_links = _walk_runtime(root, budget)
    if set(actual.keys()) != {entry.path for entry in file_entries}:
        _fail("INVENTORY_COVERAGE")
    if set(actual_links.keys()) != {entry.path for entry in link_entries}:
        _fail("INVENTORY_COVERAGE")
    for entry in file_entries:
        observed_digest, observed_size = actual[entry.path]
        if observed_digest != entry.sha256 or observed_size != entry.size:
            _fail("INVENTORY_MATCH")
    file_paths = {entry.path for entry in file_entries}
    for entry in link_entries:
        declared = _resolve_link_target(entry.path, entry.target, root)
        if declared not in file_paths:
            _fail("LINK_TARGET")
        raw = actual_links[entry.path]
        if not raw or "\0" in raw or posixpath.isabs(raw):
            _fail("LINK_TARGET")
        observed_target = posixpath.normpath(posixpath.join(posixpath.dirname(entry.path), raw))
        if observed_target != declared:
            _fail("LINK_TARGET")
    for entry_path, digest_value, size in native_entries:
        observed = _hash_native_file(entry_path, root, budget)
        if observed != (digest_value, size):
            _fail("NATIVE_MATCH")
    interp_node = _lstat(interp_path, "INTERPRETER_STAT")
    if not stat.S_ISREG(interp_node.st_mode):
        _fail("INTERPRETER_FILE")
    if interp_node.st_nlink != 1:
        _fail("INTERPRETER_LINKS")
    if interp_node.st_uid != _REQUIRED_RUNTIME_UID:
        _fail("INTERPRETER_OWNER")
    if interp_node.st_mode & 0o022:
        _fail("INTERPRETER_WRITABLE")
    if not interp_node.st_mode & 0o111:
        _fail("INTERPRETER_EXEC")
    if interp_node.st_size != interpreter["bytes"]:
        _fail("INTERPRETER_SIZE")
    _check_chain(interp_path, root)
    observed_interp = _hash_runtime_file(interp_path, interp_node, budget)
    if observed_interp != interpreter["sha256"]:
        _fail("INTERPRETER_HASH")
    return VerifiedPythonRuntime(
        interpreter=Path(interp_path),
        runtime_root=Path(root),
        interpreter_sha256=interpreter["sha256"],
        inventory_sha256=record["inventorySha256"],
        native_inventory_sha256=record["nativeInventorySha256"],
        target=target,
    )


def _reread_record(path: str, node: os.stat_result, budget: _Budget) -> bytes:
    """Re-read the already-hashed record descriptor content for parsing."""
    fd = _open_regular(path, "RECORD_OPEN")
    try:
        fresh = os.fstat(fd)
        if _identity(fresh) != _identity(node):
            _fail("RECORD_CHANGED")
        if budget.read_bytes + fresh.st_size > _MAX_REQUEST_READ_BYTES:
            _fail("REQUEST_BUDGET")
        chunks: list[bytes] = []
        remaining = fresh.st_size
        while remaining > 0:
            chunk = os.read(fd, min(remaining, _READ_CHUNK_BYTES))
            if not chunk:
                _fail("RECORD_CHANGED")
            chunks.append(chunk)
            remaining -= len(chunk)
        budget.read_bytes += fresh.st_size
        return b"".join(chunks)
    finally:
        os.close(fd)


def _walk_runtime(root: str, budget: _Budget) -> tuple[dict[str, tuple[str, int]], dict[str, str]]:
    actual: dict[str, tuple[str, int]] = {}
    links: dict[str, str] = {}
    stack: list[str] = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                names = sorted(iterator, key=lambda entry: entry.name)
        except OSError as error:
            raise BundleEvidenceError("RUNTIME_SCAN") from error
        for entry in names:
            try:
                is_link = entry.is_symlink()
            except OSError as error:
                raise BundleEvidenceError("RUNTIME_SCAN") from error
            try:
                node = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise BundleEvidenceError("ENTRY_STAT") from error
            full = entry.path
            if is_link:
                try:
                    raw = os.readlink(full)
                except OSError as error:
                    raise BundleEvidenceError("ENTRY_STAT") from error
                if full in links:
                    _fail("INVENTORY_DUPLICATE")
                links[full] = raw
                continue
            if stat.S_ISDIR(node.st_mode):
                if node.st_uid != _REQUIRED_RUNTIME_UID:
                    _fail("ENTRY_OWNER")
                if node.st_mode & 0o022:
                    _fail("ENTRY_WRITABLE")
                budget.dirs += 1
                if budget.dirs > _MAX_RUNTIME_FILES:
                    _fail("RUNTIME_FILES")
                stack.append(full)
            elif stat.S_ISREG(node.st_mode):
                digest_value = _hash_runtime_file(full, node, budget)
                if full in actual:
                    _fail("INVENTORY_DUPLICATE")
                actual[full] = (digest_value, node.st_size)
            else:
                _fail("ENTRY_TYPE")
    return (actual, links)


def _hash_native_file(path: str, root: str, budget: _Budget) -> tuple[str, int]:
    entry_path = _canonical_absolute(path, "NATIVE_ENTRY")
    node = _lstat(entry_path, "NATIVE_STAT")
    if stat.S_ISLNK(node.st_mode):
        _fail("NATIVE_SYMLINK")
    if not stat.S_ISREG(node.st_mode):
        _fail("NATIVE_TYPE")
    stop = root if _under(entry_path, root) else "/"
    _check_chain(entry_path, stop)
    digest_value = _hash_runtime_file(entry_path, node, budget)
    return (digest_value, node.st_size)


def _child_env(home: Path, cache: Path) -> dict[str, str]:
    """Allowlisted clean environment for preparation subprocesses."""
    env: dict[str, str] = {}
    for key in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ"):
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    env["HOME"] = str(home)
    env["UV_CACHE_DIR"] = str(cache / "uv")
    env["XDG_CACHE_HOME"] = str(cache)
    env["TMPDIR"] = str(cache / "tmp")
    return env


def _run_group(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_s: int,
    code: str,
    out_limit: int,
) -> tuple[int, str, str]:
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            text=True,
            errors="strict",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except (OSError, ValueError) as error:
        raise BundleEvidenceError(code) from error
    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as error:
        with contextlib.suppress(OSError, ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        raise BundleEvidenceError(code) from error
    except (OSError, ValueError, UnicodeError) as error:
        raise BundleEvidenceError(code) from error
    if len(out) + len(err) > out_limit:
        with contextlib.suppress(OSError, ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        _fail(code)
    return (proc.returncode, out, err)


def _run_fixed_probe(
    python_exe: Path, target: Any, timeout_s: int = _PROBE_TIMEOUT_S
) -> dict[str, Any]:
    """Run the fixed local probe with a clean isolated env and finite budget."""
    env = {"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONNOUSERSITE": "1"}
    try:
        status, out, _err = _run_group(
            [str(python_exe), "-I", "-c", _FIXED_PROBE_SOURCE],
            cwd=Path(str(python_exe)).parent,
            env=env,
            timeout_s=timeout_s,
            code="PROBE_TIMEOUT",
            out_limit=_MAX_PROBE_BYTES,
        )
    except BundleEvidenceError as error:
        if error.code == "PROBE_TIMEOUT":
            raise
        raise BundleEvidenceError("PROBE_SPAWN") from error
    if len(out) + len(_err) > _MAX_PROBE_BYTES:
        _fail("PROBE_OUTPUT")
    if status != 0:
        _fail("PROBE_EXIT")
    try:
        facts = json.loads(out.strip())
    except (ValueError, UnicodeError) as error:
        raise BundleEvidenceError("PROBE_JSON") from error
    if not isinstance(facts, dict) or set(facts.keys()) != _PROBE_KEYS:
        _fail("PROBE_JSON")
    for field, key in (
        ("implementation", "implementation"),
        ("python_version", "version"),
        ("os", "os"),
        ("architecture", "architecture"),
        ("libc_family", "libcFamily"),
        ("libc_version", "libcVersion"),
    ):
        if facts[key] != getattr(target, field, None):
            if key == "version":
                _fail("PROBE_VERSION")
            _fail("PROBE_FACTS")
    if not isinstance(facts["libcFamily"], str) or not facts["libcFamily"]:
        _fail("PROBE_FACTS")
    if facts["entrypointsOk"] is not True:
        _fail("PROBE_ENTRYPOINTS")
    return facts


def _find_prepared_uv() -> Path:
    found = shutil.which("uv")
    if not found:
        _fail("UV_UNAVAILABLE")
    assert found is not None
    return Path(found)


def _check_uv_version(uv_path: Path, work: Path, env: dict[str, str]) -> None:
    status, out, _err = _run_group(
        [str(uv_path), "--version"],
        cwd=work,
        env=env,
        timeout_s=_TOOL_TIMEOUT_S,
        code="UV_PROBE",
        out_limit=_MAX_TOOL_OUTPUT,
    )
    if status != 0 or f"uv {_UV_VERSION}" not in out:
        _fail("UV_VERSION")


def _create_private_env(
    interpreter: Path, venv_dir: Path, *, home: Path, cache: Path
) -> None:
    env = _child_env(home, cache)
    status, _out, _err = _run_group(
        [str(interpreter), "-m", "venv", str(venv_dir)],
        cwd=venv_dir.parent,
        env=env,
        timeout_s=_VENV_TIMEOUT_S,
        code="VENV_FAILED",
        out_limit=_MAX_TOOL_OUTPUT,
    )
    if status != 0:
        _fail("VENV_FAILED")


def _install_staged_wheels(
    uv_path: Path,
    venv_python: Path,
    staged_dir: Path,
    requirements_path: Path,
    *,
    home: Path,
    cache: Path,
    destination: Path,
) -> None:
    env = _child_env(home, cache)
    status, _out, _err = _run_group(
        [
            str(uv_path),
            "pip",
            "install",
            "--python",
            str(venv_python),
            "--no-index",
            "--find-links",
            str(staged_dir),
            "--require-hashes",
            "--offline",
            "--no-python-downloads",
            "--no-config",
            "-r",
            str(requirements_path),
        ],
        cwd=destination,
        env=env,
        timeout_s=_INSTALL_TIMEOUT_S,
        code="INSTALL_FAILED",
        out_limit=_MAX_TOOL_OUTPUT,
    )
    if status != 0:
        _fail("INSTALL_FAILED")


def _quote_shell(text: str) -> str:
    return '"' + text.replace('"', '\\"') + '"'


def _write_wrappers(venv_bin: Path, bin_dir: Path) -> None:
    bin_dir.mkdir(parents=False, exist_ok=False)
    for name, module, function in _FIXED_ENTRYPOINTS:
        planned = _PLANNED_BIN_PREFIX + name
        body = (
            "#!/bin/sh\n"
            f"# KSI prepared launcher for {name}; planned path {planned}.\n"
            f"# Fixed mapping {module}:{function}. Absolute paths only.\n"
            f"unset {_UNSET_WRAPPER_VARS}\n"
            f'exec {_quote_shell(str(venv_bin / name))} "$@"\n'
        )
        wrapper = bin_dir / name
        try:
            with open(wrapper, "xb") as handle:
                handle.write(body.encode("utf-8"))
        except OSError as error:
            raise BundleEvidenceError("WRAPPER_WRITE") from error
        os.chmod(wrapper, 0o555)


def _tool_snapshot() -> tuple[ToolFileDigest, ...]:
    tools_dir = Path(__file__).resolve().parent
    snapshots: list[ToolFileDigest] = []
    for basename in _TOOL_FILES:
        path = tools_dir / basename
        if not path.is_file() or os.path.islink(path):
            _fail("TOOL_SNAPSHOT")
        snapshots.append(
            ToolFileDigest(relative_path=f"tools/{basename}", sha256=_sha_file(path))
        )
    return tuple(snapshots)


def _stage_verified_wheels(
    bundle: Any, staged_dir: Path, budget_files: list[tuple[str, int, str]]
) -> None:
    staged_dir.mkdir(parents=False, exist_ok=False)
    bundle_root = bundle.bundle_root
    if not isinstance(bundle_root, Path):
        _fail("INPUT_TYPE")
    for row in bundle.files:
        if not row.relative_path.startswith("wheels/"):
            continue
        source = bundle_root / row.relative_path
        fd = _open_regular(str(source), "STAGE_OPEN")
        try:
            node = os.fstat(fd)
            if not stat.S_ISREG(node.st_mode):
                _fail("STAGE_FILE")
            if node.st_size != row.bytes:
                _fail("STAGE_CHANGED")
            digest = hashlib.sha256()
            remaining = node.st_size
            while remaining > 0:
                chunk = os.read(fd, min(remaining, _READ_CHUNK_BYTES))
                if not chunk:
                    _fail("STAGE_CHANGED")
                digest.update(chunk)
                remaining -= len(chunk)
            if "sha256:" + digest.hexdigest() != row.sha256:
                _fail("STAGE_HASH")
            named = _lstat(str(source), "STAGE_OPEN")
            if (named.st_dev, named.st_ino) != (node.st_dev, node.st_ino):
                _fail("STAGE_CHANGED")
        finally:
            os.close(fd)
        target = staged_dir / row.relative_path[7:]
        try:
            with open(target, "xb") as handle, open(source, "rb") as origin:
                while True:
                    piece = origin.read(_READ_CHUNK_BYTES)
                    if not piece:
                        break
                    handle.write(piece)
        except OSError as error:
            raise BundleEvidenceError("STAGE_WRITE") from error
        os.chmod(target, 0o444)
        budget_files.append((row.relative_path[7:], row.sha256, row.bytes))


def _hash_prepared_tree(
    destination: Path, relpaths: list[str]
) -> tuple[str, list[tuple[str, str, int]]]:
    entries: list[tuple[str, str, int]] = []
    for rel in relpaths:
        payload = _reread_prepared_file(destination / rel)
        entries.append((rel, "sha256:" + hashlib.sha256(payload).hexdigest(), len(payload)))
    return (_inventory_hash(entries), entries)


def _reread_prepared_file(path: Path) -> bytes:
    fd = _open_regular(str(path), "PREPARED_READ")
    try:
        node = os.fstat(fd)
        if not stat.S_ISREG(node.st_mode):
            _fail("PREPARED_READ")
        chunks: list[bytes] = []
        remaining = node.st_size
        while remaining > 0:
            chunk = os.read(fd, min(remaining, _READ_CHUNK_BYTES))
            if not chunk:
                _fail("PREPARED_READ")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def prepare_application_installation(
    bundle: Any,
    *,
    python_binding: Path,
    expected_python_binding_sha256: str,
    destination: Path,
) -> PreparationReceipt:
    """Prepare a new private installation tree; never installs globally."""
    if not isinstance(bundle, VerifiedApplicationBundle):
        _fail("INPUT_TYPE")
    if not isinstance(python_binding, Path) or not isinstance(destination, Path):
        _fail("INPUT_TYPE")
    if (
        not isinstance(expected_python_binding_sha256, str)
        or not _DIGEST.fullmatch(expected_python_binding_sha256)
    ):
        _fail("EXPECTED_BINDING")
    if os.path.lexists(destination):
        _fail("DESTINATION_EXISTS")
    fresh = verify_application_bundle(
        bundle.bundle_root,
        expected_manifest_sha256=bundle.manifest_sha256,
        expected_source_commit=bundle.source_commit,
        expected_lock_sha256=bundle.lock_sha256,
    )
    runtime = verify_python_binding(
        python_binding,
        expected_sha256=expected_python_binding_sha256,
        target=fresh.target,
    )
    declared = sum(row.bytes for row in fresh.files)
    if declared > _MAX_EXPANDED_BYTES:
        _fail("EXPANDED_SIZE")
    try:
        os.mkdir(destination, 0o700)
    except OSError as error:
        raise BundleEvidenceError("DESTINATION_CREATE") from error
    if os.path.islink(destination) or not destination.is_dir():
        _fail("DESTINATION_CREATE")
    staged: list[tuple[str, int, str]] = []
    _stage_verified_wheels(fresh, destination / "staged", staged)
    work = destination / "_work"
    home = work / "home"
    cache = work / "cache"
    home.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    _check_uv_version(_find_prepared_uv(), destination, _child_env(home, cache))
    venv_dir = destination / "venv"
    _create_private_env(runtime.interpreter, venv_dir, home=home, cache=cache)
    venv_python = venv_dir / "bin" / "python"
    if not venv_python.exists() or not os.access(venv_python, os.X_OK):
        _fail("VENV_FAILED")
    requirements_path = destination / "requirements.pinned.txt"
    lines = sorted(
        f"{destination / 'staged' / name} --hash={value}\n" for name, value, _ in staged
    )
    try:
        with open(requirements_path, "xb") as handle:
            handle.write("".join(lines).encode("utf-8"))
    except OSError as error:
        raise BundleEvidenceError("STAGE_WRITE") from error
    _install_staged_wheels(
        _find_prepared_uv(),
        venv_python,
        destination / "staged",
        requirements_path,
        home=home,
        cache=cache,
        destination=destination,
    )
    _run_fixed_probe(venv_python, fresh.target)
    _write_wrappers(venv_dir / "bin", destination / "bin")
    planned = sorted(_PLANNED_BIN_PREFIX + name for name, _, _ in _FIXED_ENTRYPOINTS)
    planned_records = [
        {
            "path": future,
            "entrypoint": name,
            "module": module,
            "function": function,
            "launcher": f"bin/{name}",
        }
        for future, (name, module, function) in zip(
            planned, _FIXED_ENTRYPOINTS, strict=True
        )
    ]
    planned_path = destination / "planned-install-inventory.json"
    try:
        with open(planned_path, "xb") as handle:
            handle.write(
                (json.dumps(planned_records, separators=(",", ":"), sort_keys=True) + "\n").encode(
                    "utf-8"
                )
            )
    except OSError as error:
        raise BundleEvidenceError("RECEIPT_WRITE") from error
    # Post-staging rehash: re-prove staged bytes and the binding before receipt.
    verify_python_binding(
        python_binding,
        expected_sha256=expected_python_binding_sha256,
        target=fresh.target,
    )
    controlled = (
        [f"staged/{name}" for name, _, _ in staged]
        + [f"bin/{name}" for name, _, _ in _FIXED_ENTRYPOINTS]
        + ["planned-install-inventory.json"]
    )
    prepared_inventory_sha256, _ = _hash_prepared_tree(destination, controlled)
    for name, value, size in staged:
        payload = _reread_prepared_file(destination / "staged" / name)
        if "sha256:" + hashlib.sha256(payload).hexdigest() != value or len(payload) != size:
            _fail("STAGE_CHANGED")
    preparation = {
        "schemaVersion": _PREPARATION_SCHEMA,
        "status": "INSTALLATION_PREPARED",
        "bundleSha256": fresh.manifest_sha256,
        "sourceCommit": fresh.source_commit,
        "pythonBindingSha256": expected_python_binding_sha256,
        "preparedInventorySha256": prepared_inventory_sha256,
        "target": {
            "implementation": fresh.target.implementation,
            "pythonVersion": fresh.target.python_version,
            "os": fresh.target.os,
            "architecture": fresh.target.architecture,
            "libcFamily": fresh.target.libc_family,
            "libcVersion": fresh.target.libc_version,
            "platformTag": fresh.target.platform_tag,
        },
        "plannedExecutables": planned,
        "verificationCode": {
            "commitSha": fresh.source_commit,
            "files": [
                {"relativePath": row.relative_path, "sha256": row.sha256}
                for row in _tool_snapshot()
            ],
        },
    }
    try:
        with open(destination / "preparation.json", "xb") as handle:
            handle.write(
                (json.dumps(preparation, separators=(",", ":"), sort_keys=True) + "\n").encode(
                    "utf-8"
                )
            )
    except OSError as error:
        raise BundleEvidenceError("RECEIPT_WRITE") from error
    return PreparationReceipt(
        bundle_sha256=fresh.manifest_sha256,
        source_commit=fresh.source_commit,
        python_binding_sha256=expected_python_binding_sha256,
        prepared_inventory_sha256=prepared_inventory_sha256,
        status="INSTALLATION_PREPARED",
        verification_code=VerificationCodeSnapshot(
            commit_sha=fresh.source_commit, files=_tool_snapshot()
        ),
    )


def main(argv: list[str] | None = None) -> int:
    os.umask(0o022)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--lock-sha256", required=True)
    parser.add_argument("--python-binding", type=Path, default=None)
    parser.add_argument("--python-binding-sha256", default=None)
    parser.add_argument("--prepare-root", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        verified = verify_application_bundle(
            args.bundle,
            expected_manifest_sha256=args.manifest_sha256,
            expected_source_commit=args.source_commit,
            expected_lock_sha256=args.lock_sha256,
        )
        binding = args.python_binding
        binding_sha = args.python_binding_sha256
        prepare_root = args.prepare_root
        if prepare_root is not None and (binding is None or binding_sha is None):
            _fail("PREPARE_FLAGS")
        if (binding is None) != (binding_sha is None):
            _fail("BINDING_FLAGS")
        if binding is None or binding_sha is None:
            print(
                json.dumps(
                    {
                        "status": "BUNDLE_BYTES_VERIFIED",
                        "sourceCommit": verified.source_commit,
                        "manifestSha256": verified.manifest_sha256,
                    },
                    separators=(",", ":"),
                )
            )
            return 0
        verify_python_binding(
            binding, expected_sha256=binding_sha, target=verified.target
        )
        if prepare_root is None:
            print(
                json.dumps(
                    {
                        "status": "RUNTIME_BINDING_VERIFIED",
                        "sourceCommit": verified.source_commit,
                        "manifestSha256": verified.manifest_sha256,
                        "pythonBindingSha256": binding_sha,
                    },
                    separators=(",", ":"),
                )
            )
            return 0
        receipt = prepare_application_installation(
            verified,
            python_binding=binding,
            expected_python_binding_sha256=binding_sha,
            destination=prepare_root,
        )
    except BundleEvidenceError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:  # fail closed; never leak paths or contents
        raise BundleEvidenceError("INTERNAL") from error
    payload = {
        "status": "INSTALLATION_PREPARED",
        "sourceCommit": receipt.source_commit,
        "manifestSha256": receipt.bundle_sha256,
        "pythonBindingSha256": receipt.python_binding_sha256,
        "preparedInventorySha256": receipt.prepared_inventory_sha256,
    }
    print(json.dumps(payload, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
