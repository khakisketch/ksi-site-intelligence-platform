"""Synthetic protected-runtime/preparation fixtures for Task 3 contract tests.

Tiny labeled trees, binding records and stub wheels only; never genuine
deployment runtime evidence, never the developer home or checkout venv.
Helpers build operator-owned synthetic runtimes under ``tmp_path``; tests
monkeypatch the tool's ``_REQUIRED_RUNTIME_UID``/``_ALLOWED_RUNTIME_ROOTS``
seams to the current user and synthetic prefixes.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from support.external_application_bundle_fixture import build_wheel, make_bundle

TARGET: dict[str, str] = {
    "implementation": "CPython",
    "pythonVersion": "3.12.15",
    "os": "linux",
    "architecture": "arm64",
    "libcFamily": "glibc",
    "libcVersion": "2.39",
    "platformTag": "manylinux_2_39_aarch64",
}

FIXED_PROGRAMS: tuple[tuple[str, str, str], ...] = (
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

SOURCE = "a" * 40


def digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def inventory_hash(entries: list[tuple[str, str, int]]) -> str:
    lines = [f"{path}\x00{value}\x00{size}" for path, value, size in sorted(entries)]
    return "sha256:" + hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def write_bundle_dir(
    base: Path, *, wheel_overrides: dict[str, bytes] | None = None
) -> tuple[Path, str, str, str]:
    """Write a synthetic fixture bundle; returns (dir, manifest_sha, source, lock)."""
    fixture = make_bundle(wheel_overrides=wheel_overrides)
    root = base / "bundle"
    (root / "wheels").mkdir(parents=True)
    manifest_payload = json.dumps(
        fixture.manifest, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    (root / "manifest.json").write_bytes(manifest_payload)
    for name, payload in fixture.payloads.items():
        (root / name).write_bytes(payload)
    manifest_sha = digest(manifest_payload)
    lock_sha = str(fixture.manifest["source"]["uvLockSha256"])
    return (root, manifest_sha, SOURCE, lock_sha)


_STUB_MAIN = """\
import json as _json
import os as _os
import sys as _sys


def main():
    try:
        _fd = _os.read(3, 65536).decode("utf-8", "replace")
    except OSError:
        _fd = None
    _report = {
        "marker": "SYNTHETIC-PREPARATION-STUB",
        "pid": _os.getpid(),
        "argv": _sys.argv[1:],
        "pythonpath": _os.environ.get("PYTHONPATH"),
        "virtualEnv": _os.environ.get("VIRTUAL_ENV"),
        "uvIndex": _os.environ.get("UV_INDEX_URL"),
        "listenPid": _os.environ.get("LISTEN_PID"),
        "listenFds": _os.environ.get("LISTEN_FDS"),
        "fd3": _fd,
    }
    _sys.stdout.write(_json.dumps(_report) + "\\n")
    _sys.stdout.flush()
"""


def stub_controller_wheel() -> bytes:
    """Controller wheel whose stub mains report PID/env/FDs as labeled JSON."""
    return build_wheel(
        "ksi-processing-controller",
        "0.0.1",
        tags=("py3", "none", "any"),
        entry_points=FIXED_PROGRAMS,
        extra_entries={
            "ksi_processing_controller/__init__.py": b"# synthetic stub\n",
            "ksi_processing_controller/external_inspector_daemon.py": _STUB_MAIN.encode(),
            "ksi_processing_controller/external_measurement_daemon.py": (
                _STUB_MAIN.encode()
            ),
            "ksi_processing_controller/external_validation_worker.py": (
                _STUB_MAIN.encode()
            ),
        },
    )


def build_runtime_tree(
    base: Path, *, interpreter: bytes | None = None, mode: int = 0o755
) -> dict[str, Any]:
    """Create a synthetic runtime root; returns paths and byte identities."""
    root = base / "synth-python" / "3.12.15"
    (root / "bin").mkdir(parents=True)
    (root / "lib" / "python3.12").mkdir(parents=True)
    interp_bytes = (
        interpreter
        if interpreter is not None
        else b"SYNTHETIC-INTERPRETER-BLOB-7f3a\n" * 64
    )
    interp = root / "bin" / "python3.12"
    interp.write_bytes(interp_bytes)
    os.chmod(interp, mode)
    stdlib = root / "lib" / "python3.12" / "os.py"
    stdlib.write_bytes(b"# synthetic stdlib stub\n")
    os.chmod(stdlib, 0o644)
    native = root / "lib" / "libsynth-native.so"
    native.write_bytes(b"\x7fSYNTHETIC-NATIVE-LIB\n" * 32)
    os.chmod(native, 0o644)
    second = root / "lib" / "libsynth-crypto.so"
    second.write_bytes(b"\x7fSYNTHETIC-NATIVE-LIB2\n" * 32)
    os.chmod(second, 0o644)
    for directory in (root, root / "bin", root / "lib", root / "lib" / "python3.12"):
        os.chmod(directory, 0o755)
    return {
        "root": root,
        "interpreter": interp,
        "files": [interp, stdlib, native, second],
        "native": [native, second],
    }


def build_binding_record(
    tree: dict[str, Any],
    *,
    version: str = "3.12.15",
    implementation: str = "CPython",
    libc_version: str = "2.39",
    platform_tag: str = "manylinux_2_39_aarch64",
) -> dict[str, Any]:
    entries = []
    for path in tree["files"]:
        payload = Path(path).read_bytes()
        entries.append((str(path), digest(payload), len(payload)))
    native_entries = []
    for path in tree["native"]:
        payload = Path(path).read_bytes()
        native_entries.append((str(path), digest(payload), len(payload)))
    interp_payload = Path(tree["interpreter"]).read_bytes()
    return {
        "schemaVersion": "external-runtime-python-binding.v1",
        "interpreter": {
            "path": str(tree["interpreter"]),
            "sha256": digest(interp_payload),
            "bytes": len(interp_payload),
            "version": version,
            "implementation": implementation,
        },
        "target": {
            "implementation": "CPython",
            "pythonVersion": "3.12.15",
            "os": "linux",
            "architecture": "arm64",
            "libcFamily": "glibc",
            "libcVersion": libc_version,
            "platformTag": platform_tag,
        },
        "runtimeRoot": str(tree["root"]),
        "inventorySha256": inventory_hash(entries),
        "inventory": [
            {"path": path, "sha256": value, "bytes": size}
            for path, value, size in sorted(entries)
        ],
        "nativeInventorySha256": inventory_hash(native_entries),
        "nativeInventory": [
            {"path": path, "sha256": value, "bytes": size}
            for path, value, size in sorted(native_entries)
        ],
    }


def write_binding_file(path: Path, record: dict[str, Any]) -> str:
    payload = json.dumps(record, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if path.exists() and not path.is_symlink():
        os.chmod(path, 0o600)
    path.write_bytes(payload)
    os.chmod(path, 0o400)
    return digest(payload)
