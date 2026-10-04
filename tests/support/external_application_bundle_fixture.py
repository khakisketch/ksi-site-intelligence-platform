"""Tiny synthetic wheel/bundle fixtures; never genuine release or runtime evidence."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import warnings
import zipfile
from dataclasses import dataclass
from typing import Any

SOURCE = "a" * 40
LOCK = b"version = 1\n# synthetic frozen lock; not a real uv.lock\n"
TARGET: dict[str, str] = {
    "implementation": "CPython",
    "pythonVersion": "3.12.15",
    "os": "linux",
    "architecture": "arm64",
    "libcFamily": "glibc",
    "libcVersion": "2.39",
    "platformTag": "manylinux_2_39_aarch64",
}
TOOLCHAIN: dict[str, str] = {
    "uvVersion": "0.11.15",
    "uvSha256": "sha256:" + "1" * 64,
    "buildPythonVersion": "3.12.13",
    "buildPythonSha256": "sha256:" + "2" * 64,
    "backendInventorySha256": "sha256:" + "3" * 64,
}
ENTRYPOINTS: tuple[dict[str, str], ...] = (
    {
        "name": "ksi-external-inspector-daemon",
        "module": "ksi_processing_controller.external_inspector_daemon",
        "function": "main",
    },
    {
        "name": "ksi-external-measurement-daemon",
        "module": "ksi_processing_controller.external_measurement_daemon",
        "function": "main",
    },
    {
        "name": "ksi-external-validation-worker",
        "module": "ksi_processing_controller.external_validation_worker",
        "function": "main",
    },
)


def digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def record_digest(payload: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
    return "sha256=" + encoded.decode()


def canonical_name(distribution: str) -> str:
    return distribution.lower().replace("-", "_").replace(".", "_")


def canonical_wheel_name(distribution: str, version: str, tags: tuple[str, str, str]) -> str:
    return f"{canonical_name(distribution)}-{version}-{'-'.join(tags)}.whl"


def build_wheel(
    distribution: str,
    version: str,
    *,
    tags: tuple[str, str, str] = ("py3", "none", "any"),
    entry_points: tuple[tuple[str, str, str], ...] = (),
    extra_entries: dict[str, bytes] | None = None,
    metadata_name: str | None = None,
    metadata_version: str | None = None,
    root_is_purelib: bool = True,
    record_mode: str = "correct",
    symlink_entry: str | None = None,
    duplicate_entry: str | None = None,
) -> bytes:
    base = canonical_name(distribution)
    info_dir = f"{base}-{version}.dist-info"
    entries: dict[str, bytes] = {f"{base}/__init__.py": b"# synthetic\n"}
    if entry_points:
        body = "[console_scripts]\n" + "".join(f"{n} = {m}:{f}\n" for n, m, f in entry_points)
        entries[f"{info_dir}/entry_points.txt"] = body.encode()
    entries[f"{info_dir}/METADATA"] = (
        f"Metadata-Version: 2.1\nName: {metadata_name or distribution}\n"
        f"Version: {metadata_version or version}\n"
    ).encode()
    entries[f"{info_dir}/WHEEL"] = (
        "Wheel-Version: 1.0\nGenerator: synthetic\n"
        f"Root-Is-Purelib: {'true' if root_is_purelib else 'false'}\nTag: {'-'.join(tags)}\n"
    ).encode()
    if extra_entries:
        entries.update(extra_entries)
    rows = [
        (path, record_digest(payload), str(len(payload)))
        for path, payload in sorted(entries.items())
    ]
    if record_mode == "bad-hash":
        rows = [
            (path, "sha256=" + "A" * 43 if path == f"{info_dir}/METADATA" else sha, size)
            for path, sha, size in rows
        ]
    elif record_mode == "bad-size":
        rows = [
            (path, sha, str(int(size) + 5) if path == f"{info_dir}/METADATA" else size)
            for path, sha, size in rows
        ]
    elif record_mode == "unknown-row":
        rows = [*rows, ("unexpected/thing.py", "sha256=" + "A" * 43, "3")]
    elif record_mode == "traversal-row":
        rows = [*rows, ("../escape.py", "sha256=" + "A" * 43, "3")]
    if record_mode != "omit":
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\n").writerows([*rows, (f"{info_dir}/RECORD", "", "")])
        entries[f"{info_dir}/RECORD"] = buffer.getvalue().encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, payload in entries.items():
            node = zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0))
            node.create_system = 3
            node.external_attr = 0o100644 << 16
            archive.writestr(node, payload)
        if symlink_entry is not None:
            node = zipfile.ZipInfo(symlink_entry, date_time=(2026, 1, 1, 0, 0, 0))
            node.create_system = 3
            node.external_attr = 0o120777 << 16
            archive.writestr(node, "target")
        if duplicate_entry is not None:
            node = zipfile.ZipInfo(duplicate_entry, date_time=(2026, 1, 1, 0, 0, 0))
            node.create_system = 3
            node.external_attr = 0o100644 << 16
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                archive.writestr(node, b"duplicate")
    return stream.getvalue()


@dataclass(frozen=True)
class BundleFixture:
    payloads: dict[str, bytes]
    manifest: dict[str, Any]


def make_bundle(
    *,
    source: str = SOURCE,
    target: dict[str, str] | None = None,
    toolchain: dict[str, str] | None = None,
    entry_points: tuple[dict[str, str], ...] = ENTRYPOINTS,
    wheel_overrides: dict[str, bytes] | None = None,
    extra_payloads: dict[str, bytes] | None = None,
) -> BundleFixture:
    target = dict(target or TARGET)
    toolchain = dict(toolchain or TOOLCHAIN)
    specs: list[tuple[str, str, str, tuple[str, str, str]]] = [
        ("ksi-processing-controller", "0.0.1", "workspace", ("py3", "none", "any")),
        ("ksi-domain", "0.0.1", "workspace", ("py3", "none", "any")),
        ("demo-native", "1.2.3", "external", ("cp312", "cp312", "manylinux_2_39_aarch64")),
    ]
    mappings = tuple((row["name"], row["module"], row["function"]) for row in entry_points)
    wheels: dict[str, bytes] = {}
    for distribution, version, kind, tags in specs:
        name = canonical_wheel_name(distribution, version, tags)
        if distribution == "ksi-processing-controller":
            wheels[name] = build_wheel(distribution, version, tags=tags, entry_points=mappings)
        elif kind == "external":
            wheels[name] = build_wheel(distribution, version, tags=tags, root_is_purelib=False)
        else:
            wheels[name] = build_wheel(distribution, version, tags=tags)
    wheels.update(wheel_overrides or {})
    distributions = [
        {
            "name": distribution,
            "version": version,
            "kind": kind,
            "wheel": "wheels/" + canonical_wheel_name(distribution, version, tags),
            "pythonTag": tags[0],
            "abiTag": tags[1],
            "platformTag": tags[2],
        }
        for distribution, version, kind, tags in specs
        if canonical_wheel_name(distribution, version, tags) in wheels
    ]
    requirements = (
        "\n".join(
            f"{canonical_name(distribution)}=={version}"
            for distribution, version, _, _ in specs
        )
        + "\n"
    ).encode()
    payloads: dict[str, bytes] = {
        "uv.lock": LOCK,
        "requirements.txt": requirements,
        **{"wheels/" + name: payload for name, payload in wheels.items()},
    }
    payloads.update(extra_payloads or {})
    wheel_kinds = {
        "wheels/" + canonical_wheel_name(distribution, version, tags): kind
        for distribution, version, kind, tags in specs
    }
    manifest: dict[str, Any] = {
        "schemaVersion": "external-runtime-application-bundle.v1",
        "source": {
            "gitCommitSha": source,
            "uvLockSha256": digest(LOCK),
            "uvLockBytes": len(LOCK),
            "buildInputInventorySha256": "sha256:" + "4" * 64,
        },
        "target": target,
        "buildToolchain": toolchain,
        "files": [],
        "distributions": distributions,
        "entrypoints": [dict(row) for row in entry_points],
    }
    manifest["files"] = _file_records(payloads, wheel_kinds)
    return BundleFixture(payloads=payloads, manifest=manifest)


def _file_records(payloads: dict[str, bytes], wheel_kinds: dict[str, str]) -> list[dict[str, Any]]:
    records = []
    for path, payload in payloads.items():
        if path == "uv.lock":
            kind = "lock"
        elif path == "requirements.txt":
            kind = "requirements"
        else:
            base_kind = wheel_kinds.get(path)
            kind = f"{base_kind}-wheel" if base_kind else "external-wheel"
        records.append(
            {"relativePath": path, "sha256": digest(payload), "bytes": len(payload), "kind": kind}
        )
    return sorted(records, key=lambda row: row["relativePath"])


def sync_file_records(manifest: dict[str, Any], payloads: dict[str, bytes]) -> None:
    """Recompute file records after a test mutation so inner checks are exercised."""
    wheel_kinds = {row["wheel"]: row["kind"] for row in manifest["distributions"]}
    manifest["files"] = _file_records(payloads, wheel_kinds)
