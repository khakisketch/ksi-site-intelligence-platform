#!/usr/bin/env python3
"""Frozen-source offline builder for external-runtime application bundles.

Builds ``manifest.json``, ``uv.lock``, ``requirements.txt`` and
``wheels/*.whl`` for the three fixed ``ksi-processing-controller`` programs
from an exact clean Git checkout, using only an explicitly hash-pinned
prepared toolchain (uv 0.11.15, an explicit build Python, a prepared backend
inventory) and a curated external wheelhouse. No network, no installation,
no host mutation: packages are never installed, the source repository and
its lock are never modified, and the destination must be newly created.

Stdlib only. The only executed helpers are read-only ``git`` inspections of
the source checkout, the pinned ``uv`` binary and the pinned build-Python
``--version`` probe, all through fixed argument vectors (no shell).

Canonical build-input inventory ordering (``source.buildInputInventorySha256``):
every frozen input file is identified by its repository-relative POSIX path;
entries of the form ``"<rel>\\x00<sha256hex>\\x00<size>"`` are sorted by
byte-wise path order, joined with a single ``"\\n"`` separator (no trailing
newline), UTF-8 encoded and hashed with SHA-256, rendered as
``"sha256:<hex>"``. The manifest itself is excluded from its own inventory.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
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
verify_application_bundle = _task1.verify_application_bundle


@dataclass(frozen=True)
class ToolFileDigest:
    relative_path: str
    sha256: str


@dataclass(frozen=True)
class VerificationCodeSnapshot:
    commit_sha: str
    files: tuple[ToolFileDigest, ...]


@dataclass(frozen=True)
class BuildToolchainPins:
    uv_path: Path
    uv_sha256: str
    build_python: Path
    build_python_sha256: str
    backend_inventory_path: Path
    backend_inventory_sha256: str


@dataclass(frozen=True)
class BundleCreationReceipt:
    manifest_sha256: str
    source_commit: str
    lock_sha256: str
    verification_code: VerificationCodeSnapshot
    resolution_backends: dict[str, str]


@dataclass(frozen=True)
class _LockPackage:
    name: str
    version: str
    editable: str | None
    deps: tuple[str, ...]
    wheels: tuple[tuple[str, str, int | None], ...]


_CONTROLLER = "ksi-processing-controller"
_UV_VERSION = "0.11.15"
_IMPLEMENTATION = "CPython"
_PYTHON_VERSION = "3.12.15"
_TARGET_OS = "linux"
_ARCHITECTURE = "arm64"
_LIBC_FAMILY = "glibc"

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

_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_.+~-]+\Z")
_LIBC_VERSION = re.compile(r"[0-9]+\.[0-9]+(\.[0-9]+)?\Z")
_NORMALIZE_RUNS = re.compile(r"[-_.]+")
_HASH_LINE = re.compile(r"--hash=sha256:([0-9a-f]{64})\b")
_REQUIREMENT = re.compile(r"[A-Za-z0-9_.\-]+==[^ \t\\;#]+")
_MANYLINUX = re.compile(r"manylinux_([0-9]+)_([0-9]+)_([A-Za-z0-9]+)\Z")
_ABI3_FLOOR = re.compile(r"cp3([0-9]+)\Z")
_UV_VERSION_LINE = re.compile(r"^Python (3\.12\.[0-9]+)")

_UV_TIMEOUT_S = 120
_PROBE_TIMEOUT_S = 30
_MAX_TOOL_OUTPUT = 4 * 1024**2
_MAX_FREEZE_FILES = 4096
_MAX_FREEZE_BYTES = 64 * 1024**2
_MAX_COPY_BYTES = 8 * 1024**2


def _fail(code: str) -> NoReturn:
    raise BundleEvidenceError(code)


def _normalized(name: str) -> str:
    return _NORMALIZE_RUNS.sub("_", name.lower())


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024**2)
            if not chunk:
                break
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _read_nofollow(path: Path, limit: int, code: str) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as error:
        raise BundleEvidenceError(code) from error
    try:
        node = os.fstat(fd)
        if not stat.S_ISREG(node.st_mode):
            _fail(code)
        if node.st_size > limit or node.st_size < 0:
            _fail(code)
        chunks: list[bytes] = []
        remaining = node.st_size
        while remaining > 0:
            chunk = os.read(fd, min(remaining, 1024**2))
            if not chunk:
                _fail(code)
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _git_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def _child_env(home: Path, cache: Path) -> dict[str, str]:
    """Allowlisted clean environment for toolchain subprocesses.

    Only PATH/locale/TZ survive from the ambient process; every VIRTUAL_ENV,
    PYTHON*, UV_*, CONDA*, PIP* and VIRTUALENV control is dropped. HOME and
    cache locations point at task-private directories.
    """
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


def _run_capture(
    argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, code: str
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            text=True,
            errors="strict",
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise BundleEvidenceError(code) from error
    except UnicodeError as error:
        raise BundleEvidenceError(code) from error
    if len(completed.stdout) > _MAX_TOOL_OUTPUT or len(completed.stderr) > _MAX_TOOL_OUTPUT:
        _fail(code)
    return completed


def _git(repo: Path, *args: str) -> str:
    binary = shutil.which("git")
    if binary is None:
        _fail("GIT_UNAVAILABLE")
    assert binary is not None
    completed = _run_capture(
        [binary, "-C", str(repo), *args],
        cwd=repo,
        env=_git_env(),
        timeout=_PROBE_TIMEOUT_S,
        code="GIT_FAILED",
    )
    if completed.returncode != 0:
        _fail("GIT_FAILED")
    return completed.stdout.strip()


def _check_clean_checkout(repo: Path, source_commit: str) -> None:
    if not isinstance(source_commit, str) or not _COMMIT.fullmatch(source_commit):
        _fail("SOURCE_COMMIT_FORMAT")
    if not repo.is_dir() or not (repo / ".git").exists():
        _fail("GIT_REPO")
    head = _git(repo, "rev-parse", "HEAD")
    if not _COMMIT.fullmatch(head):
        _fail("GIT_FAILED")
    if head != source_commit:
        _fail("SOURCE_COMMIT_MISMATCH")
    if _git(repo, "status", "--porcelain") != "":
        _fail("GIT_DIRTY")


def _check_target(target: Any) -> tuple[tuple[int, ...], str]:
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
            _fail("TARGET_FIELD")
    if (
        target.implementation != _IMPLEMENTATION
        or target.python_version != _PYTHON_VERSION
        or target.os != _TARGET_OS
        or target.architecture != _ARCHITECTURE
        or target.libc_family != _LIBC_FAMILY
    ):
        _fail("TARGET_UNSUPPORTED")
    if not _LIBC_VERSION.fullmatch(target.libc_version):
        _fail("TARGET_UNSUPPORTED")
    if not _TOKEN.fullmatch(target.platform_tag):
        _fail("TARGET_UNSUPPORTED")
    lowered = target.platform_tag.lower()
    if (
        "aarch64" not in lowered
        or ("linux" not in lowered and "manylinux" not in lowered)
        or any(bad in lowered for bad in ("x86_64", "amd64", "armv7", "musl", "win", "macos"))
    ):
        _fail("TARGET_UNSUPPORTED")
    parts = tuple(int(piece) for piece in target.libc_version.split("."))
    return (parts, target.platform_tag)


def _check_toolchain(toolchain: BuildToolchainPins, work: Path) -> tuple[str, str]:
    for path, pin in (
        (toolchain.uv_path, toolchain.uv_sha256),
        (toolchain.build_python, toolchain.build_python_sha256),
        (toolchain.backend_inventory_path, toolchain.backend_inventory_sha256),
    ):
        if not isinstance(path, Path) or not isinstance(pin, str) or not _DIGEST.fullmatch(pin):
            _fail("TOOLCHAIN_BINDING")
        if not path.is_file() or os.path.islink(path):
            _fail("TOOLCHAIN_FILE")
        if _sha_file(path) != pin:
            _fail("TOOLCHAIN_HASH")
    home = work / "home"
    cache = work / "cache"
    home.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    env = _child_env(home, cache)
    uv_version = _run_capture(
        [str(toolchain.uv_path), "--version"],
        cwd=work,
        env=env,
        timeout=_PROBE_TIMEOUT_S,
        code="TOOLCHAIN_PROBE",
    )
    if uv_version.returncode != 0 or f"uv {_UV_VERSION}" not in uv_version.stdout:
        _fail("TOOLCHAIN_VERSION")
    build_version = _run_capture(
        [str(toolchain.build_python), "--version"],
        cwd=work,
        env=env,
        timeout=_PROBE_TIMEOUT_S,
        code="TOOLCHAIN_PROBE",
    )
    if build_version.returncode != 0:
        _fail("TOOLCHAIN_PROBE")
    matched = _UV_VERSION_LINE.search((build_version.stdout + build_version.stderr).strip())
    if matched is None:
        _fail("TOOLCHAIN_VERSION")
    return (env["HOME"], matched.group(1))


def _load_backend_inventory(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise BundleEvidenceError("BACKEND_INVENTORY") from error
    allowed: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not _TOKEN.fullmatch(line):
            _fail("BACKEND_INVENTORY")
        allowed.add(_normalized(line))
    if not allowed:
        _fail("BACKEND_INVENTORY")
    return allowed


def _parse_lock(payload: bytes) -> tuple[dict[str, tuple[_LockPackage, ...]], bytes]:
    try:
        data = tomllib.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError) as error:
        raise BundleEvidenceError("LOCK_PARSE") from error
    raw_packages = data.get("package")
    if not isinstance(raw_packages, list) or not raw_packages:
        _fail("LOCK_PARSE")
    grouped: dict[str, list[_LockPackage]] = {}
    for entry in raw_packages:
        if not isinstance(entry, dict):
            _fail("LOCK_PARSE")
        name = entry.get("name")
        version = entry.get("version")
        source = entry.get("source")
        if not isinstance(name, str) or not isinstance(version, str):
            _fail("LOCK_PARSE")
        if not _TOKEN.fullmatch(name) or not _TOKEN.fullmatch(version):
            _fail("LOCK_PARSE")
        editable: str | None = None
        if isinstance(source, dict):
            raw_editable = source.get("editable")
            if raw_editable is not None:
                if not isinstance(raw_editable, str):
                    _fail("LOCK_PARSE")
                editable = raw_editable
        deps: list[str] = []
        raw_deps = entry.get("dependencies", [])
        if not isinstance(raw_deps, list):
            _fail("LOCK_PARSE")
        for dep in raw_deps:
            if not isinstance(dep, dict) or not isinstance(dep.get("name"), str):
                _fail("LOCK_PARSE")
            assert isinstance(dep["name"], str)
            deps.append(dep["name"])
        wheels: list[tuple[str, str, int | None]] = []
        raw_wheels = entry.get("wheels", [])
        if not isinstance(raw_wheels, list):
            _fail("LOCK_PARSE")
        for wheel in raw_wheels:
            if not isinstance(wheel, dict):
                _fail("LOCK_PARSE")
            url = wheel.get("url")
            digest = wheel.get("hash")
            size = wheel.get("size")
            if not isinstance(url, str) or not isinstance(digest, str):
                _fail("LOCK_PARSE")
            if not _DIGEST.fullmatch(digest):
                _fail("LOCK_PARSE")
            if size is not None and (type(size) is not int or size <= 0):
                _fail("LOCK_PARSE")
            wheels.append((url, digest, size))
        key = _normalized(name)
        # uv resolution forks (e.g. torch/torchvision with resolution-markers)
        # legitimately repeat a normalized name. Keep every entry in document
        # order; _closure resolves names reached by the traversal deterministically.
        grouped.setdefault(key, []).append(
            _LockPackage(
                name=name,
                version=version,
                editable=editable,
                deps=tuple(deps),
                wheels=tuple(wheels),
            )
        )
    packages = {key: tuple(entries) for key, entries in grouped.items()}
    return (packages, payload)


def _has_compatible_wheel(
    entry: _LockPackage, target_tag: str, libc: tuple[int, ...]
) -> bool:
    try:
        _select_external_wheel(entry, target_tag, libc)
    except BundleEvidenceError:
        return False
    return True


def _resolve_lock_entry(
    candidates: tuple[_LockPackage, ...], target_tag: str, libc: tuple[int, ...]
) -> _LockPackage:
    if len(candidates) == 1:
        return candidates[0]
    editable = tuple(entry for entry in candidates if entry.editable is not None)
    external = tuple(entry for entry in candidates if entry.editable is None)
    if editable and external:
        _fail("LOCK_FORK_AMBIGUOUS")
    if editable:
        if len(editable) != 1:
            _fail("LOCK_FORK_AMBIGUOUS")
        return editable[0]
    compatible = tuple(
        entry for entry in external if _has_compatible_wheel(entry, target_tag, libc)
    )
    if len(compatible) != 1:
        _fail("LOCK_FORK_AMBIGUOUS")
    return compatible[0]


def _closure(
    packages: dict[str, tuple[_LockPackage, ...]],
    target_tag: str,
    libc: tuple[int, ...],
) -> tuple[dict[str, str], dict[str, _LockPackage], dict[str, _LockPackage]]:
    root = _normalized(_CONTROLLER)
    if root not in packages:
        _fail("LOCK_CLOSURE")
    workspace: dict[str, str] = {}
    external: dict[str, _LockPackage] = {}
    resolved: dict[str, _LockPackage] = {}
    queue: list[str] = [root]
    seen: set[str] = set()
    while queue:
        key = queue.pop()
        if key in seen:
            continue
        seen.add(key)
        candidates = packages.get(key)
        if candidates is None:
            _fail("LOCK_CLOSURE")
        entry = _resolve_lock_entry(candidates, target_tag, libc)
        resolved[key] = entry
        if entry.editable is not None:
            workspace[key] = entry.editable
        else:
            external[key] = entry
        queue.extend(_normalized(dep) for dep in entry.deps)
    if resolved[root].editable is None:
        _fail("LOCK_CLOSURE")
    return (workspace, external, resolved)


def _safe_repo_relative(value: str) -> Path:
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "\0" in value
        or ".." in value.split("/")
    ):
        _fail("MEMBER_PATH")
    return Path(*value.split("/"))


def _copy_frozen_file(
    source: Path, staged: Path, rel: str, budget: list[int]
) -> tuple[str, str, int]:
    payload = _read_nofollow(source, _MAX_COPY_BYTES, "FROZEN_READ")
    budget[0] += 1
    budget[1] += len(payload)
    if budget[0] > _MAX_FREEZE_FILES or budget[1] > _MAX_FREEZE_BYTES:
        _fail("FROZEN_BOUNDS")
    staged.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(staged, "xb") as handle:
            handle.write(payload)
    except OSError as error:
        raise BundleEvidenceError("FROZEN_WRITE") from error
    digest = hashlib.sha256(payload).hexdigest()
    return (rel, digest, len(payload))


def _freeze_member(
    repo: Path, staged_root: Path, member_rel: str, budget: list[int]
) -> list[tuple[str, str, int]]:
    member_path = _safe_repo_relative(member_rel)
    source_dir = repo / member_path
    if os.path.islink(source_dir) or not source_dir.is_dir():
        _fail("MEMBER_PATH")
    try:
        candidate = source_dir.resolve()
        candidate.relative_to(repo.resolve())
    except (OSError, ValueError) as error:
        raise BundleEvidenceError("MEMBER_PATH") from error
    records: list[tuple[str, str, int]] = []
    manifest = source_dir / "pyproject.toml"
    staged_manifest = staged_root / member_path / "pyproject.toml"
    records.append(
        _copy_frozen_file(manifest, staged_manifest, f"{member_rel}/pyproject.toml", budget)
    )
    src_dir = source_dir / "src"
    if os.path.islink(src_dir) or not src_dir.is_dir():
        _fail("MEMBER_MANIFEST")
    staged_src = staged_root / member_path / "src"
    stack: list[tuple[Path, Path, str]] = [(src_dir, staged_src, f"{member_rel}/src")]
    while stack:
        origin, target, prefix = stack.pop()
        try:
            with os.scandir(origin) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError as error:
            raise BundleEvidenceError("FROZEN_READ") from error
        for item in entries:
            if item.is_symlink():
                _fail("FROZEN_SYMLINK")
            if item.is_dir(follow_symlinks=False):
                stack.append((
                    Path(item.path),
                    target / item.name,
                    f"{prefix}/{item.name}",
                ))
            elif item.is_file(follow_symlinks=False):
                records.append(
                    _copy_frozen_file(
                        Path(item.path),
                        target / item.name,
                        f"{prefix}/{item.name}",
                        budget,
                    )
                )
            else:
                _fail("FROZEN_SPECIAL")
    if len(records) < 2:
        _fail("MEMBER_MANIFEST")
    return records


def _check_member_manifest(
    staged_root: Path, name: str, member_rel: str, backends: set[str], lock_version: str
) -> str:
    payload = _read_nofollow(
        staged_root / _safe_repo_relative(member_rel) / "pyproject.toml",
        _MAX_COPY_BYTES,
        "MEMBER_MANIFEST",
    )
    try:
        data = tomllib.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError) as error:
        raise BundleEvidenceError("MEMBER_MANIFEST") from error
    project = data.get("project")
    build_system = data.get("build-system")
    if not isinstance(project, dict) or not isinstance(build_system, dict):
        _fail("MEMBER_MANIFEST")
    assert isinstance(project, dict) and isinstance(build_system, dict)
    raw_name = project.get("name")
    raw_version = project.get("version")
    backend = build_system.get("build-backend")
    if (
        not isinstance(raw_name, str)
        or not isinstance(raw_version, str)
        or not isinstance(backend, str)
    ):
        _fail("MEMBER_MANIFEST")
    if _normalized(raw_name) != _normalized(name) or raw_version != lock_version:
        _fail("MEMBER_MANIFEST")
    top = _normalized(backend.split(".")[0])
    if top not in backends:
        _fail("BACKEND_UNPINNED")
    return raw_version


def _record_resolution_backend(staged_root: Path, member_rel: str, name: str) -> str:
    """Parse a resolution-only member manifest and return its build backend.

    Resolution-only members are frozen so uv can resolve the workspace, but
    their wheels are never built here: the backend is recorded, never gated
    against the backend allowlist. `uv export --locked` remains the consistency
    backstop between these manifests and the lock.
    """
    payload = _read_nofollow(
        staged_root / _safe_repo_relative(member_rel) / "pyproject.toml",
        _MAX_COPY_BYTES,
        "MEMBER_MANIFEST",
    )
    try:
        data = tomllib.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError) as error:
        raise BundleEvidenceError("MEMBER_MANIFEST") from error
    project = data.get("project")
    build_system = data.get("build-system")
    if not isinstance(project, dict) or not isinstance(build_system, dict):
        _fail("MEMBER_MANIFEST")
    assert isinstance(project, dict) and isinstance(build_system, dict)
    raw_name = project.get("name")
    backend = build_system.get("build-backend")
    if not isinstance(raw_name, str) or not isinstance(backend, str) or not backend:
        _fail("MEMBER_MANIFEST")
    if _normalized(raw_name) != _normalized(name):
        _fail("MEMBER_MANIFEST")
    return backend


def _inventory_hash(records: list[tuple[str, str, int]]) -> str:
    lines = [f"{rel}\x00{digest}\x00{size}" for rel, digest, size in sorted(records)]
    return "sha256:" + hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _run_uv(
    uv_path: Path, args: list[str], *, cwd: Path, env: dict[str, str], code: str
) -> str:
    completed = _run_capture(
        [str(uv_path), *args],
        cwd=cwd,
        env=env,
        timeout=_UV_TIMEOUT_S,
        code=code,
    )
    if completed.returncode != 0:
        _fail(code)
    try:
        completed.stdout.encode("utf-8")
    except UnicodeError as error:
        raise BundleEvidenceError(code) from error
    return completed.stdout


def _parse_exported_requirements(text: str, external: dict[str, _LockPackage]) -> str:
    stanzas: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        if not raw.strip():
            current = None
            continue
        if raw.startswith("#"):
            continue
        if raw[0] in (" ", "\t"):
            if current is None:
                _fail("EXPORT_MALFORMED")
            assert current is not None
            stanzas[current].append(raw.strip())
            continue
        matched = _REQUIREMENT.match(raw.strip())
        if matched is None:
            _fail("EXPORT_MALFORMED")
        current = _normalized(raw.strip().split("==")[0])
        if current in stanzas:
            _fail("EXPORT_MALFORMED")
        stanzas[current] = []
    for key in external:
        if key not in stanzas:
            _fail("EXPORT_COVERAGE")
        joined = "\n".join(stanzas[key])
        if not _HASH_LINE.search(joined):
            _fail("EXPORT_MALFORMED")
    return text if text.endswith("\n") else text + "\n"


def _parse_wheel_filename(filename: str, code: str) -> tuple[str, str, str, str, str]:
    if not filename.endswith(".whl"):
        _fail(code)
    parts = filename[:-4].split("-")
    if len(parts) != 5 or any(not part for part in parts):
        _fail(code)
    return (parts[0], parts[1], parts[2], parts[3], parts[4])


def _wheel_platform_ok(platform_field: str, target_tag: str, libc: tuple[int, ...]) -> bool:
    for component in platform_field.split("."):
        if component == "any" or component == target_tag or component == "linux_aarch64":
            return True
        matched = _MANYLINUX.fullmatch(component)
        if (
            matched is not None
            and matched.group(3) == "aarch64"
            and (int(matched.group(1)), int(matched.group(2))) <= tuple(libc[:2])
        ):
            return True
    return False


def _abi3_python_ok(python_tag: str) -> bool:
    # Stable-ABI (abi3) wheels built against an older CPython 3.x floor run on
    # the fixed 3.12 target: accept cp3<minor> with minor <= 12, reject newer
    # floors such as cp313 whose ABI the target cannot satisfy.
    for part in python_tag.split("."):
        matched = _ABI3_FLOOR.fullmatch(part)
        if matched is not None and int(matched.group(1)) <= 12:
            return True
    return False


def _exact_cp312(python_tag: str) -> int:
    return 1 if any(part.startswith("cp312") for part in python_tag.split(".")) else 0


def _abi3_floor(python_tag: str, abi_tag: str) -> int:
    if "abi3" not in abi_tag.split("."):
        return -1
    floors = []
    for part in python_tag.split("."):
        matched = _ABI3_FLOOR.fullmatch(part)
        if matched is not None:
            floors.append(int(matched.group(1)))
    return max(floors) if floors else -1


def _wheel_tags_ok(python_tag: str, abi_tag: str, code: str) -> None:
    python_parts = python_tag.split(".")
    abi_parts = abi_tag.split(".")
    if not any(part == "py3" or part.startswith("cp312") for part in python_parts) and (
        "abi3" not in abi_parts or not _abi3_python_ok(python_tag)
    ):
        _fail(code)
    if not any(part in ("none", "abi3") or part.startswith("cp312") for part in abi_parts):
        _fail(code)


def _select_external_wheel(
    entry: _LockPackage, target_tag: str, libc: tuple[int, ...]
) -> tuple[str, str]:
    candidates: list[tuple[tuple[int, ...], int, int, str, str]] = []
    for url, digest, _size in entry.wheels:
        filename = url.rsplit("/", 1)[-1]
        try:
            dist, version, python_tag, abi_tag, platform_tag = _parse_wheel_filename(
                filename, "WHEEL_TAG"
            )
        except BundleEvidenceError:
            continue
        if _normalized(dist) != _normalized(entry.name) or version != entry.version:
            continue
        try:
            _wheel_tags_ok(python_tag, abi_tag, "WHEEL_TAG")
        except BundleEvidenceError:
            continue
        if not _wheel_platform_ok(platform_tag, target_tag, libc):
            continue
        rank = (1, 0, 0)
        for component in platform_tag.split("."):
            if component == target_tag:
                rank = (3, 0, 0)
            elif component == "any":
                rank = max(rank, (0, 0, 0))
            elif component == "linux_aarch64":
                rank = max(rank, (1, 0, 0))
            else:
                matched = _MANYLINUX.fullmatch(component)
                if matched is not None:
                    rank = max(rank, (2, int(matched.group(1)), int(matched.group(2))))
        candidates.append((
            rank,
            _exact_cp312(python_tag),
            _abi3_floor(python_tag, abi_tag),
            filename,
            digest,
        ))
    if not candidates:
        _fail("WHEEL_TAG")
    assert candidates
    best = max(candidates, key=lambda row: (row[0], row[1], row[2]))
    best_key = (best[0], best[1], best[2])
    tied = [
        row
        for row in candidates
        if (row[0], row[1], row[2]) == best_key and row[3] != best[3]
    ]
    if tied:
        _fail("WHEEL_AMBIGUOUS")
    return (best[3], best[4])


def _copy_wheelhouse(
    wheelhouse: Path,
    selected: dict[str, tuple[str, str]],
    wheels_dir: Path,
) -> list[tuple[str, int, str]]:
    if not wheelhouse.is_dir() or os.path.islink(wheelhouse):
        _fail("WHEELHOUSE")
    try:
        names = sorted(os.listdir(wheelhouse))
    except OSError as error:
        raise BundleEvidenceError("WHEELHOUSE") from error
    wanted = {filename for filename, _digest in selected.values()}
    observed = {name for name in names if name.endswith(".whl")}
    if observed != wanted:
        _fail("WHEEL_EXTRA" if observed - wanted else "WHEEL_MISSING")
    copied: list[tuple[str, int, str]] = []
    for _key, (filename, digest) in sorted(selected.items()):
        source = wheelhouse / filename
        payload = _read_nofollow(source, 256 * 1024**2, "WHEEL_FILE")
        if "sha256:" + hashlib.sha256(payload).hexdigest() != digest:
            _fail("WHEEL_HASH")
        destination = wheels_dir / filename
        try:
            with open(destination, "xb") as handle:
                handle.write(payload)
        except OSError as error:
            raise BundleEvidenceError("FROZEN_WRITE") from error
        copied.append((filename, len(payload), digest))
    return copied


def _prove_target_closure(
    *,
    uv_path: Path,
    build_python: Path,
    requirements: Path,
    wheels_dir: Path,
    scratch: Path,
    platform_tag: str,
    env: dict[str, str],
) -> None:
    if not requirements.is_file() or not wheels_dir.is_dir() or not scratch.is_dir():
        _fail("INPUT_PATH")
    _run_uv(
        uv_path,
        [
            "pip",
            "install",
            "--dry-run",
            "--require-hashes",
            "--no-index",
            "--find-links",
            str(wheels_dir),
            "--only-binary",
            ":all:",
            "--python",
            str(build_python),
            "--python-version",
            _PYTHON_VERSION,
            "--python-platform",
            platform_tag,
            "--target",
            str(scratch),
            "--no-config",
            "-r",
            str(requirements),
        ],
        cwd=wheels_dir,
        env=env,
        code="UV_DRYRUN_FAILED",
    )


def _tool_snapshot() -> tuple[ToolFileDigest, ...]:
    tools_dir = Path(__file__).resolve().parent
    snapshots: list[ToolFileDigest] = []
    for basename in _TOOL_FILES:
        path = tools_dir / basename
        if not path.is_file() or os.path.islink(path):
            if basename == "verify_external_runtime_application_bundle.py":
                continue
            _fail("TOOL_SNAPSHOT")
        snapshots.append(
            ToolFileDigest(relative_path=f"tools/{basename}", sha256=_sha_file(path))
        )
    return tuple(snapshots)


def build_application_bundle(
    repo: Path,
    *,
    source_commit: str,
    wheelhouse: Path,
    toolchain: BuildToolchainPins,
    target: Any,
    destination: Path,
) -> BundleCreationReceipt:
    """Freeze the named source and build a verified offline wheel bundle."""
    if not isinstance(repo, Path) or not isinstance(destination, Path):
        _fail("INPUT_PATH")
    if not isinstance(wheelhouse, Path) or not isinstance(toolchain, BuildToolchainPins):
        _fail("INPUT_PATH")
    if os.path.lexists(destination):
        _fail("DESTINATION_EXISTS")
    libc, platform_tag = _check_target(target)
    _check_clean_checkout(repo, source_commit)

    work = Path(tempfile.mkdtemp(prefix="ksi-bundle-build-"))
    try:
        _home, build_python_version = _check_toolchain(toolchain, work)
        backends = _load_backend_inventory(toolchain.backend_inventory_path)
        lock_payload = _read_nofollow(repo / "uv.lock", 64 * 1024**2, "LOCK_READ")
        root_payload = _read_nofollow(repo / "pyproject.toml", 8 * 1024**2, "LOCK_READ")
        try:
            root_data = tomllib.loads(root_payload.decode("utf-8"))
        except (ValueError, UnicodeError) as error:
            raise BundleEvidenceError("LOCK_PARSE") from error
        if not isinstance(root_data.get("tool"), dict):
            _fail("LOCK_PARSE")
        packages, _raw = _parse_lock(lock_payload)
        workspace, external, resolved = _closure(packages, platform_tag, libc)

        staged = work / "frozen"
        staged.mkdir(parents=True, exist_ok=False)
        budget: list[int] = [0, 0]
        root_manifest = _copy_frozen_file(
            repo / "pyproject.toml", staged / "pyproject.toml", "pyproject.toml", budget
        )
        root_lock = _copy_frozen_file(
            repo / "uv.lock", staged / "uv.lock", "uv.lock", budget
        )
        records = [root_manifest, root_lock]
        # Freeze every lock workspace member so uv can resolve the workspace
        # (root groups/sources may reference non-closure members); build only
        # closure members' wheels. External-only names need no source freeze;
        # a non-closure name with competing member sources fails closed.
        freeze_plan: dict[str, tuple[str, str, str]] = {}
        for key in sorted(workspace):
            entry = resolved[key]
            assert entry.editable is not None
            freeze_plan[key] = (entry.editable, "build", entry.name)
        for key in sorted(packages):
            if key in freeze_plan:
                continue
            rels = {item.editable for item in packages[key] if item.editable is not None}
            if not rels:
                continue
            if len(rels) != 1:
                _fail("LOCK_FORK_AMBIGUOUS")
            freeze_plan[key] = (next(iter(rels)), "resolution", packages[key][0].name)
        resolution_backends: dict[str, str] = {}
        for key in sorted(freeze_plan):
            member_rel, role, display_name = freeze_plan[key]
            records.extend(_freeze_member(repo, staged, member_rel, budget))
            if role == "build":
                entry = resolved[key]
                _check_member_manifest(staged, entry.name, member_rel, backends, entry.version)
            else:
                backend = _record_resolution_backend(staged, member_rel, display_name)
                resolution_backends[display_name] = backend
        lock_before = _sha_file(staged / "uv.lock")

        env = _child_env(work / "home", work / "cache")
        exported = _run_uv(
            toolchain.uv_path,
            [
                "export",
                "--locked",
                "--no-dev",
                "--package",
                _CONTROLLER,
                "--no-editable",
                "--no-emit-workspace",
                "--format",
                "requirements-txt",
                "--no-config",
                "--offline",
                "--no-python-downloads",
            ],
            cwd=staged,
            env=env,
            code="UV_EXPORT_FAILED",
        )
        requirements_text = _parse_exported_requirements(exported, external)

        built_wheels = work / "built"
        built_wheels.mkdir(parents=True, exist_ok=False)
        workspace_wheels: list[tuple[str, str, str, int, str]] = []
        for key in sorted(workspace):
            entry = resolved[key]
            out_dir = work / "out" / key
            out_dir.mkdir(parents=True, exist_ok=False)
            _run_uv(
                toolchain.uv_path,
                [
                    "build",
                    "--python",
                    str(toolchain.build_python),
                    "--no-build-isolation",
                    "--wheel",
                    "--package",
                    entry.name,
                    "--out-dir",
                    str(out_dir),
                    "--no-config",
                    "--offline",
                    "--no-python-downloads",
                ],
                cwd=staged,
                env=env,
                code="UV_BUILD_FAILED",
            )
            produced = sorted(p.name for p in out_dir.iterdir() if p.name.endswith(".whl"))
            if len(produced) != 1:
                _fail("UV_BUILD_FAILED")
            dist, version, python_tag, abi_tag, platform_tag_wheel = _parse_wheel_filename(
                produced[0], "WHEEL_NAME"
            )
            if _normalized(dist) != key or version != entry.version:
                _fail("WHEEL_NAME")
            if (python_tag, abi_tag, platform_tag_wheel) != ("py3", "none", "any"):
                _fail("WHEEL_PROFILE")
            payload = _read_nofollow(out_dir / produced[0], 256 * 1024**2, "WHEEL_FILE")
            digest = "sha256:" + hashlib.sha256(payload).hexdigest()
            (built_wheels / produced[0]).write_bytes(payload)
            workspace_wheels.append((entry.name, version, produced[0], len(payload), digest))
        if _sha_file(staged / "uv.lock") != lock_before:
            _fail("UV_LOCK_CHANGED")

        selected: dict[str, tuple[str, str]] = {}
        for key in sorted(external):
            selected[key] = _select_external_wheel(external[key], platform_tag, libc)
        wheels_dir = work / "wheels"
        wheels_dir.mkdir(parents=True, exist_ok=False)
        for _name, _version, filename, _size, _digest in workspace_wheels:
            wheels_dir.joinpath(filename).write_bytes((built_wheels / filename).read_bytes())
        external_copied = _copy_wheelhouse(wheelhouse, selected, wheels_dir)

        for name, version, _filename, _size, digest in workspace_wheels:
            requirements_text += f"{name}=={version} --hash={digest}\n"
        combined = work / "requirements.txt"
        combined.write_text(requirements_text, encoding="utf-8")

        scratch = work / "scratch"
        scratch.mkdir(parents=True, exist_ok=False)
        _prove_target_closure(
            uv_path=toolchain.uv_path,
            build_python=toolchain.build_python,
            requirements=combined,
            wheels_dir=wheels_dir,
            scratch=scratch,
            platform_tag=platform_tag,
            env=env,
        )

        try:
            destination.mkdir(parents=False, exist_ok=False)
        except OSError as error:
            raise BundleEvidenceError("DESTINATION_CREATE") from error
        if os.path.islink(destination) or not destination.is_dir():
            _fail("DESTINATION_CREATE")
        (destination / "uv.lock").write_bytes(lock_payload)
        (destination / "requirements.txt").write_text(requirements_text, encoding="utf-8")
        (destination / "wheels").mkdir(parents=False, exist_ok=False)
        for filename in sorted(p.name for p in wheels_dir.iterdir()):
            (destination / "wheels" / filename).write_bytes((wheels_dir / filename).read_bytes())

        lock_digest = "sha256:" + hashlib.sha256(lock_payload).hexdigest()
        inventory = _inventory_hash(records)
        files: list[dict[str, Any]] = [
            {
                "relativePath": "uv.lock",
                "sha256": lock_digest,
                "bytes": len(lock_payload),
                "kind": "lock",
            },
            {
                "relativePath": "requirements.txt",
                "sha256": "sha256:" + hashlib.sha256(
                    requirements_text.encode("utf-8")
                ).hexdigest(),
                "bytes": len(requirements_text.encode("utf-8")),
                "kind": "requirements",
            },
        ]
        distributions: list[dict[str, Any]] = []
        for name, version, filename, size, digest in sorted(
            workspace_wheels, key=lambda row: row[2]
        ):
            files.append({
                "relativePath": f"wheels/{filename}",
                "sha256": digest,
                "bytes": size,
                "kind": "workspace-wheel",
            })
            distributions.append({
                "name": name,
                "version": version,
                "kind": "workspace",
                "wheel": f"wheels/{filename}",
                "pythonTag": "py3",
                "abiTag": "none",
                "platformTag": "any",
            })
        for key in sorted(selected):
            entry = external[key]
            filename, digest = selected[key]
            size = next(size for name, size, item in external_copied if name == filename)
            _dist, version, python_tag, abi_tag, platform_tag_part = _parse_wheel_filename(
                filename, "WHEEL_NAME"
            )
            files.append({
                "relativePath": f"wheels/{filename}",
                "sha256": digest,
                "bytes": size,
                "kind": "external-wheel",
            })
            distributions.append({
                "name": entry.name,
                "version": version,
                "kind": "external",
                "wheel": f"wheels/{filename}",
                "pythonTag": python_tag,
                "abiTag": abi_tag,
                "platformTag": platform_tag_part,
            })
        files.sort(key=lambda row: row["relativePath"])
        distributions.sort(key=lambda row: row["wheel"])
        manifest: dict[str, Any] = {
            "schemaVersion": "external-runtime-application-bundle.v1",
            "source": {
                "gitCommitSha": source_commit,
                "uvLockSha256": lock_digest,
                "uvLockBytes": len(lock_payload),
                "buildInputInventorySha256": inventory,
            },
            "target": {
                "implementation": _IMPLEMENTATION,
                "pythonVersion": _PYTHON_VERSION,
                "os": _TARGET_OS,
                "architecture": _ARCHITECTURE,
                "libcFamily": _LIBC_FAMILY,
                "libcVersion": target.libc_version,
                "platformTag": target.platform_tag,
            },
            "buildToolchain": {
                "uvVersion": _UV_VERSION,
                "uvSha256": toolchain.uv_sha256,
                "buildPythonVersion": build_python_version,
                "buildPythonSha256": toolchain.build_python_sha256,
                "backendInventorySha256": toolchain.backend_inventory_sha256,
            },
            "files": files,
            "distributions": distributions,
            "entrypoints": [
                {"name": name, "module": module, "function": function}
                for name, module, function in _FIXED_ENTRYPOINTS
            ],
        }
        manifest_payload = json.dumps(
            manifest, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        (destination / "manifest.json").write_bytes(manifest_payload)
        manifest_sha = "sha256:" + hashlib.sha256(manifest_payload).hexdigest()
        try:
            verify_application_bundle(
                destination,
                expected_manifest_sha256=manifest_sha,
                expected_source_commit=source_commit,
                expected_lock_sha256=lock_digest,
            )
        except BundleEvidenceError as error:
            raise BundleEvidenceError("VERIFY_FAILED") from error
        receipt = BundleCreationReceipt(
            manifest_sha256=manifest_sha,
            source_commit=source_commit,
            lock_sha256=lock_digest,
            verification_code=VerificationCodeSnapshot(
                commit_sha=source_commit, files=_tool_snapshot()
            ),
            resolution_backends=resolution_backends,
        )
        return receipt
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    os.umask(0o022)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--uv-sha256", required=True)
    parser.add_argument("--build-python", type=Path, required=True)
    parser.add_argument("--build-python-sha256", required=True)
    parser.add_argument("--backend-inventory", type=Path, required=True)
    parser.add_argument("--backend-inventory-sha256", required=True)
    parser.add_argument("--libc-version", required=True)
    parser.add_argument("--platform-tag", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        target = BundleTarget(
            implementation=_IMPLEMENTATION,
            python_version=_PYTHON_VERSION,
            os=_TARGET_OS,
            architecture=_ARCHITECTURE,
            libc_family=_LIBC_FAMILY,
            libc_version=args.libc_version,
            platform_tag=args.platform_tag,
        )
        toolchain = BuildToolchainPins(
            uv_path=args.uv,
            uv_sha256=args.uv_sha256,
            build_python=args.build_python,
            build_python_sha256=args.build_python_sha256,
            backend_inventory_path=args.backend_inventory,
            backend_inventory_sha256=args.backend_inventory_sha256,
        )
        receipt = build_application_bundle(
            args.repo,
            source_commit=args.source_commit,
            wheelhouse=args.wheelhouse,
            toolchain=toolchain,
            target=target,
            destination=args.destination,
        )
    except BundleEvidenceError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:  # fail closed; never leak paths or contents
        raise BundleEvidenceError("INTERNAL") from error
    payload = {
        "status": "BUNDLE_CREATED",
        "manifestSha256": receipt.manifest_sha256,
        "sourceCommit": receipt.source_commit,
        "resolutionBackends": receipt.resolution_backends,
    }
    print(json.dumps(payload, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
