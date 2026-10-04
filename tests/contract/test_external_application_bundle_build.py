"""Contract tests for the frozen-source offline bundle builder.

Synthetic git checkouts, explicitly labeled fake toolchains and tiny generated
wheels only; never genuine release evidence, never the developer home or venv.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from support.external_application_bundle_fixture import build_wheel

ROOT = Path(__file__).resolve().parents[2]
BUILD_TOOL = ROOT / "tools/build_external_runtime_application_bundle.py"
TASK1_TOOL = ROOT / "tools/external_runtime_application_bundle.py"

REAL_UV = Path("/home/ksi/.local/bin/uv")
PLATFORM_TAG = "manylinux_2_39_aarch64"
LIBC_VERSION = "2.39"
SECRET_MARKER = b"SYNTHETIC-LEAK-PROBE-9f27c1"

FIXED_ENTRYPOINTS = {
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
}

ROOT_PYPROJECT = """\
[project]
name = "synthetic-bundle-source"
version = "0.0.1"
requires-python = ">=3.12,<3.13"

[tool.uv]
package = false

[tool.uv.workspace]
members = ["packages/*", "services/*"]
"""

MEMBER_PYPROJECT = """\
[project]
name = "@NAME@"
version = "0.0.1"
requires-python = ">=3.12,<3.13"
dependencies = [@DEPS@]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""

LOCK_TEMPLATE = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "ksi-processing-controller"
version = "0.0.1"
source = { editable = "services/ksi-processing-controller" }
dependencies = [
    { name = "ksi-domain" },
    { name = "demo-native" },
]

[package.metadata]
requires-dist = [
    { name = "ksi-domain", editable = "packages/ksi-domain" },
    { name = "demo-native", specifier = "==1.2.3" },
]

[[package]]
name = "ksi-domain"
version = "0.0.1"
source = { editable = "packages/ksi-domain" }

[[package]]
name = "demo-native"
version = "1.2.3"
source = { registry = "https://pypi.org/simple" }
dependencies = [@DEMO_DEPS@]
wheels = [
    { url = "https://example.invalid/@DEMO_FILE@", hash = "@DEMO_HASH@", size = @DEMO_SIZE@ },
]
@EXTRA_PACKAGES@"""

FAKE_UV = """\
#!/usr/bin/env python3
\"\"\"SYNTHETIC TEST SEAM - fake uv for builder contract tests, never a toolchain.\"\"\"
import base64
import csv
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

MODE = "@MODE@"
WHEEL_TAGS = ("py3", "none", "any")
FIXED_MAPPINGS = (
    ("ksi-external-inspector-daemon",
     "ksi_processing_controller.external_inspector_daemon", "main"),
    ("ksi-external-measurement-daemon",
     "ksi_processing_controller.external_measurement_daemon", "main"),
    ("ksi-external-validation-worker",
     "ksi_processing_controller.external_validation_worker", "main"),
)


def _record_digest(payload):
    raw = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
    return "sha256=" + raw.decode()


def _registry_rows():
    text = Path("uv.lock").read_text(encoding="utf-8")
    rows = []
    for block in text.split("[[package]]")[1:]:
        head = block.split("[package.metadata]")[0]
        if "registry" not in head:
            continue
        name = re.search(r'^name = "([^"]+)"', block, re.M).group(1)
        version = re.search(r'^version = "([^"]+)"', block, re.M).group(1)
        found = re.search(r'hash = "sha256:([0-9a-f]{64})"', block)
        rows.append((name, version, found.group(1) if found else "0" * 64))
    return rows


def _export():
    if MODE == "fail-export":
        print("demo-native==1.2.3 \\\\")
        print("    --hash=sha256:" + "0" * 64)
        return 1
    if MODE == "garbage-export":
        print("definitely not a requirements stanza")
        return 0
    if MODE == "check-staged" and not Path("packages/ksi-extra").is_dir():
        print("staged tree is missing the resolution-only member")
        return 1
    for name, version, digest in _registry_rows():
        print(f"{name}=={version} \\\\")
        print(f"    --hash=sha256:{digest}")
    return 0


def _member_dir(package):
    text = Path("uv.lock").read_text(encoding="utf-8")
    for block in text.split("[[package]]")[1:]:
        name = re.search(r'^name = "([^"]+)"', block, re.M).group(1)
        if name != package:
            continue
        editable = re.search(r'editable = "([^"]+)"', block)
        if not editable:
            return None
        return Path(editable.group(1))
    return None


def _make_wheel(distribution, version, entry_points):
    base = re.sub(r"[-_.]+", "_", distribution.lower())
    info = f"{base}-{version}.dist-info"
    entries = {f"{base}/__init__.py": b"# synthetic seam wheel\\n"}
    if entry_points:
        body = "[console_scripts]\\n"
        for name, module, function in entry_points:
            body += f"{name} = {module}:{function}\\n"
        entries[f"{info}/entry_points.txt"] = body.encode()
    entries[f"{info}/METADATA"] = (
        f"Metadata-Version: 2.1\\nName: {distribution}\\nVersion: {version}\\n"
    ).encode()
    entries[f"{info}/WHEEL"] = (
        "Wheel-Version: 1.0\\nGenerator: synthetic-seam\\n"
        "Root-Is-Purelib: true\\nTag: py3-none-any\\n"
    ).encode()
    rows = [(path, _record_digest(payload), str(len(payload)))
            for path, payload in sorted(entries.items())]
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\\n").writerows(
        [*rows, (f"{info}/RECORD", "", "")])
    entries[f"{info}/RECORD"] = buffer.getvalue().encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, payload in entries.items():
            node = zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0))
            node.create_system = 3
            node.external_attr = 0o100644 << 16
            archive.writestr(node, payload)
    return stream.getvalue()


def _build(argv):
    if MODE == "fail-build":
        print("Successfully built synthetic wheel")
        return 1
    package = argv[argv.index("--package") + 1]
    out_dir = Path(argv[argv.index("--out-dir") + 1])
    member = _member_dir(package)
    if member is None:
        print(f"unknown package {package}")
        return 1
    text = (member / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', text, re.M).group(1)
    mappings = FIXED_MAPPINGS if package == "ksi-processing-controller" else ()
    wheel = _make_wheel(package, version, mappings)
    base = re.sub(r"[-_.]+", "_", package.lower())
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{base}-{version}-py3-none-any.whl").write_bytes(wheel)
    print(f"Successfully built {package}-{version}")
    return 0


def _dry_run():
    if MODE == "fail-dryrun":
        print("Would make no changes")
        return 1
    print("Would make no changes")
    return 0


def main(argv):
    if argv[1:2] == ["--version"]:
        if MODE == "bad-version":
            print("uv 0.11.14 (SYNTHETIC-TEST-SEAM)")
        else:
            print("uv 0.11.15 (SYNTHETIC-TEST-SEAM)")
        return 0
    if argv[1:2] == ["export"]:
        return _export()
    if argv[1:2] == ["build"]:
        return _build(argv)
    if argv[1:3] == ["pip", "install"]:
        return _dry_run()
    print("synthetic seam cannot serve this argv")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
"""

FAKE_PYTHON = """\
#!/bin/sh
echo "Python @VERSION@ (SYNTHETIC-TEST-SEAM)"
"""


def _builder() -> Any:
    assert BUILD_TOOL.is_file(), "frozen-source bundle builder is not implemented"
    tools_dir = str(BUILD_TOOL.parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    spec = importlib.util.spec_from_file_location(
        "build_external_runtime_application_bundle", BUILD_TOOL
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _task1() -> Any:
    existing = sys.modules.get("external_runtime_application_bundle")
    if existing is not None:
        return existing
    assert TASK1_TOOL.is_file(), "reviewed application-bundle tool is missing"
    tools_dir = str(TASK1_TOOL.parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    spec = importlib.util.spec_from_file_location(
        "external_runtime_application_bundle", TASK1_TOOL
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def _demo_wheel(tags: tuple[str, str, str] = ("cp312", "cp312", PLATFORM_TAG)) -> bytes:
    return build_wheel("demo-native", "1.2.3", tags=tags, root_is_purelib=False)


def _demo_filename(tags: tuple[str, str, str] = ("cp312", "cp312", PLATFORM_TAG)) -> str:
    return f"demo_native-1.2.3-{'-'.join(tags)}.whl"


def _lock_text(
    demo_payload: bytes,
    demo_tags: tuple[str, str, str] = ("cp312", "cp312", PLATFORM_TAG),
    demo_deps: str = "",
    extra_packages: str = "",
) -> str:
    filename = _demo_filename(demo_tags)
    text = LOCK_TEMPLATE.replace("@DEMO_FILE@", filename)
    text = text.replace("@DEMO_HASH@", "sha256:" + hashlib.sha256(demo_payload).hexdigest())
    text = text.replace("@DEMO_SIZE@", str(len(demo_payload)))
    text = text.replace("@DEMO_DEPS@", demo_deps)
    text = text.replace("@EXTRA_PACKAGES@", extra_packages)
    return text


def _member_pyproject(name: str, deps: str = "", backend: str = "hatchling.build") -> str:
    text = MEMBER_PYPROJECT.replace("@NAME@", name).replace("@DEPS@", deps)
    return text.replace('build-backend = "hatchling.build"', f'build-backend = "{backend}"')


def _make_repo(
    tmp_path: Path,
    *,
    name: str = "repo",
    lock_text: str | None = None,
    extra_tracked: dict[str, bytes] | None = None,
    skip_commit: bool = False,
) -> tuple[Path, str]:
    demo_payload = _demo_wheel()
    lock = lock_text if lock_text is not None else _lock_text(demo_payload)
    repo = tmp_path / name
    files: dict[str, bytes] = {
        "pyproject.toml": ROOT_PYPROJECT.encode(),
        "uv.lock": lock.encode(),
        ".gitignore": b"hostile.txt\nleaked.env\nsecret/\n",
        "hostile.txt": b"ignored hostile extra\n",
        "leaked.env": SECRET_MARKER + b"\n",
        "secret/key.pem": b"synthetic fake key\n",
        "packages/ksi-domain/pyproject.toml": _member_pyproject("ksi-domain").encode(),
        "packages/ksi-domain/src/ksi_domain/__init__.py": b"# synthetic\n",
        "packages/ksi-unrelated/pyproject.toml": _member_pyproject("ksi-unrelated").encode(),
        "packages/ksi-unrelated/src/ksi_unrelated/__init__.py": b"# synthetic\n",
        "services/ksi-processing-controller/pyproject.toml": _member_pyproject(
            "ksi-processing-controller", '"ksi-domain", "demo-native==1.2.3"'
        ).encode(),
        "services/ksi-processing-controller/src/ksi_processing_controller/__init__.py": (
            b"# synthetic\n"
        ),
        "services/ksi-processing-controller/src/ksi_processing_controller/"
        "external_inspector_daemon.py": b"def main():\n    raise SystemExit(0)\n",
        "services/ksi-processing-controller/src/ksi_processing_controller/"
        "external_measurement_daemon.py": b"def main():\n    raise SystemExit(0)\n",
        "services/ksi-processing-controller/src/ksi_processing_controller/"
        "external_validation_worker.py": b"def main():\n    raise SystemExit(0)\n",
    }
    files.update(extra_tracked or {})
    for relative, payload in files.items():
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    _git(repo, "init", "-q")
    _git(repo, "add", "pyproject.toml", "uv.lock", ".gitignore")
    _git(repo, "add", "packages/ksi-domain", "packages/ksi-unrelated")
    _git(repo, "add", "services/ksi-processing-controller")
    for relative in extra_tracked or {}:
        if not relative.startswith(("hostile", "leaked", "secret/")):
            _git(repo, "add", relative)
    if not skip_commit:
        _git(
            repo,
            "-c",
            "user.name=synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "synthetic source",
        )
    return repo, _git(repo, "rev-parse", "HEAD")


def _write_executable(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


def _toolchain(
    builder: Any, tmp_path: Path, *, uv_mode: str = "ok", python_version: str = "3.12.15"
) -> Any:
    uv = _write_executable(tmp_path / f"fake-uv-{uv_mode}", FAKE_UV.replace("@MODE@", uv_mode))
    python = _write_executable(
        tmp_path / "fake-python", FAKE_PYTHON.replace("@VERSION@", python_version)
    )
    inventory = tmp_path / "backend-inventory.txt"
    inventory.write_text("# synthetic backend inventory\nhatchling\n", encoding="utf-8")
    return builder.BuildToolchainPins(
        uv_path=uv,
        uv_sha256=_sha(uv),
        build_python=python,
        build_python_sha256=_sha(python),
        backend_inventory_path=inventory,
        backend_inventory_sha256=_sha(inventory),
    )


def _target(task1: Any, **overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "implementation": "CPython",
        "python_version": "3.12.15",
        "os": "linux",
        "architecture": "arm64",
        "libc_family": "glibc",
        "libc_version": LIBC_VERSION,
        "platform_tag": PLATFORM_TAG,
    }
    fields.update(overrides)
    return task1.BundleTarget(**fields)


def _wheelhouse(tmp_path: Path, payloads: dict[str, bytes]) -> Path:
    house = tmp_path / "wheelhouse"
    house.mkdir(parents=True)
    for filename, payload in payloads.items():
        (house / filename).write_bytes(payload)
    return house


def _build(
    builder: Any,
    task1: Any,
    repo: Path,
    commit: str,
    house: Path,
    pins: Any,
    destination: Path,
    **overrides: Any,
) -> Any:
    return builder.build_application_bundle(
        repo,
        source_commit=commit,
        wheelhouse=house,
        toolchain=pins,
        target=_target(task1, **overrides),
        destination=destination,
    )


def test_builder_freezes_named_source_without_mutating_lock_or_old_output(
    tmp_path: Path,
) -> None:
    builder = _builder()
    task1 = _task1()
    assert builder.BundleEvidenceError is task1.BundleEvidenceError
    demo_payload = _demo_wheel()
    lock_text = _lock_text(demo_payload, extra_packages=UNRELATED_PACKAGE)
    repo, commit = _make_repo(tmp_path, lock_text=lock_text)
    lock_before = (repo / "uv.lock").read_bytes()
    pins = _toolchain(builder, tmp_path)
    house = _wheelhouse(tmp_path, {_demo_filename(): demo_payload})
    destination = tmp_path / "bundle"

    receipt = _build(builder, task1, repo, commit, house, pins, destination)

    assert receipt.source_commit == commit
    assert receipt.lock_sha256 == "sha256:" + hashlib.sha256(lock_before).hexdigest()
    assert (repo / "uv.lock").read_bytes() == lock_before
    assert _git(repo, "status", "--porcelain") == ""
    assert sorted(p.name for p in (destination / "wheels").iterdir()) == [
        _demo_filename(),
        "ksi_domain-0.0.1-py3-none-any.whl",
        "ksi_processing_controller-0.0.1-py3-none-any.whl",
    ]
    assert (destination / "ksi-unrelated-0.0.1-py3-none-any.whl").exists() is False
    assert {p.name for p in destination.iterdir()} == {
        "manifest.json",
        "uv.lock",
        "requirements.txt",
        "wheels",
    }
    requirements = (destination / "requirements.txt").read_text(encoding="utf-8")
    assert "demo-native==1.2.3" in requirements
    assert "--hash=sha256:" in requirements
    assert "ksi-processing-controller==0.0.1" in requirements
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            assert SECRET_MARKER not in path.read_bytes()
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schemaVersion"] == "external-runtime-application-bundle.v1"
    assert {row["kind"] for row in manifest["files"]} == {
        "lock",
        "requirements",
        "workspace-wheel",
        "external-wheel",
    }
    assert receipt.manifest_sha256 == _sha(destination / "manifest.json")
    assert receipt.resolution_backends == {"ksi-unrelated": "hatchling.build"}
    checked = task1.verify_application_bundle(
        destination,
        expected_manifest_sha256=receipt.manifest_sha256,
        expected_source_commit=commit,
        expected_lock_sha256=receipt.lock_sha256,
    )
    assert {(p.name, p.module, p.function) for p in checked.entrypoints} == FIXED_ENTRYPOINTS
    assert receipt.verification_code.commit_sha == commit
    by_path = {row.relative_path: row.sha256 for row in receipt.verification_code.files}
    assert by_path["tools/external_runtime_application_bundle.py"] == _sha(TASK1_TOOL)
    with pytest.raises(builder.BundleEvidenceError):
        _build(builder, task1, repo, commit, house, pins, destination)


TRANSITIVE_WHEEL_URL = "https://example.invalid/demo_transitive-0.0.4-py3-none-any.whl"
TRANSITIVE_PACKAGE = """
[[package]]
name = "demo-transitive"
version = "0.0.4"
source = { registry = "https://pypi.org/simple" }
wheels = [
    { url = "TRANSITIVE_URL", hash = "sha256:TRANSITIVE_HASH", size = TRANSITIVE_SIZE },
]
"""

UNRELATED_PACKAGE = """
[[package]]
name = "ksi-unrelated"
version = "0.0.1"
source = { editable = "packages/ksi-unrelated" }
"""

KSI_EXTRA_PACKAGE = """
[[package]]
name = "ksi-extra"
version = "0.0.1"
source = { editable = "packages/ksi-extra" }
"""


def _blocking_variant(tmp_path: Path, variant: str) -> tuple[Any, Any, dict[str, Any]]:
    builder = _builder()
    task1 = _task1()
    demo_payload = _demo_wheel()
    uv_mode = "ok"
    python_version = "3.12.15"
    lock_text: str | None = None
    house_payloads = {_demo_filename(): demo_payload}
    pins_kwargs: dict[str, Any] = {}
    target_overrides: dict[str, Any] = {}
    commit_override: str | None = None
    mutate: str | None = None
    precreate_destination = False

    if variant == "missing-transitive":
        transitive = build_wheel("demo-transitive", "0.0.4")
        extra = TRANSITIVE_PACKAGE.replace("TRANSITIVE_URL", TRANSITIVE_WHEEL_URL)
        extra = extra.replace("TRANSITIVE_HASH", hashlib.sha256(transitive).hexdigest())
        extra = extra.replace("TRANSITIVE_SIZE", str(len(transitive)))
        lock_text = _lock_text(
            demo_payload, demo_deps='{ name = "demo-transitive" },', extra_packages=extra
        )
    elif variant == "wrong-arch":
        arch_tags = ("cp312", "cp312", "manylinux_2_39_x86_64")
        arch_payload = _demo_wheel(arch_tags)
        lock_text = _lock_text(arch_payload, demo_tags=arch_tags)
        house_payloads = {_demo_filename(arch_tags): arch_payload}
    elif variant == "hash-mismatch":
        house_payloads = {_demo_filename(): b"not the pinned wheel bytes"}
    elif variant == "extra-wheelhouse":
        house_payloads[_demo_filename()] = demo_payload
        house_payloads["extra_pkg-9.9.9-py3-none-any.whl"] = build_wheel("extra-pkg", "9.9.9")
    elif variant == "swapped-source-commit":
        commit_override = "b" * 40
    elif variant == "dirty-checkout":
        mutate = "dirty"
    elif variant == "untracked-checkout":
        mutate = "untracked"
    elif variant == "swapped-lock-version":
        lock_text = _lock_text(demo_payload).replace(
            'name = "demo-native"\nversion = "1.2.3"', 'name = "demo-native"\nversion = "9.9.9"'
        )
    elif variant == "nonzero-export":
        uv_mode = "fail-export"
    elif variant == "nonzero-build":
        uv_mode = "fail-build"
    elif variant == "nonzero-dryrun":
        uv_mode = "fail-dryrun"
    elif variant == "garbage-export":
        uv_mode = "garbage-export"
    elif variant == "destination-exists":
        precreate_destination = True
    elif variant == "unsupported-platform":
        target_overrides = {"platform_tag": "win_amd64"}
    elif variant == "unsupported-arch":
        target_overrides = {"platform_tag": "manylinux_2_39_x86_64"}
    elif variant == "swapped-uv-python-pins":
        pins_kwargs = {"swap_uv_python": True}
    elif variant == "wrong-uv-hash":
        pins_kwargs = {"wrong": "uv"}
    elif variant == "wrong-python-hash":
        pins_kwargs = {"wrong": "python"}
    elif variant == "wrong-backend-hash":
        pins_kwargs = {"wrong": "backend"}
    elif variant == "wrong-python-version":
        python_version = "3.11.9"
    elif variant == "wrong-uv-version":
        uv_mode = "bad-version"
    else:
        raise AssertionError(f"unknown variant {variant}")

    repo, commit = _make_repo(tmp_path, name=f"repo-{variant}", lock_text=lock_text)
    if mutate == "dirty":
        (repo / "packages/ksi-domain/src/ksi_domain/__init__.py").write_bytes(b"# dirty\n")
    elif mutate == "untracked":
        (repo / "uncommitted-notes.txt").write_bytes(b"uncommitted\n")
    pins = _toolchain(builder, tmp_path, uv_mode=uv_mode, python_version=python_version)
    if pins_kwargs.get("swap_uv_python"):
        pins = builder.BuildToolchainPins(
            uv_path=pins.uv_path,
            uv_sha256=pins.build_python_sha256,
            build_python=pins.build_python,
            build_python_sha256=pins.uv_sha256,
            backend_inventory_path=pins.backend_inventory_path,
            backend_inventory_sha256=pins.backend_inventory_sha256,
        )
    if pins_kwargs.get("wrong"):
        field = {"uv": "uv_sha256", "python": "build_python_sha256"}.get(
            pins_kwargs["wrong"], "backend_inventory_sha256"
        )
        pins = builder.BuildToolchainPins(
            uv_path=pins.uv_path,
            uv_sha256="sha256:" + "0" * 64 if field == "uv_sha256" else pins.uv_sha256,
            build_python=pins.build_python,
            build_python_sha256=(
                "sha256:" + "0" * 64
                if field == "build_python_sha256"
                else pins.build_python_sha256
            ),
            backend_inventory_path=pins.backend_inventory_path,
            backend_inventory_sha256=(
                "sha256:" + "0" * 64
                if field == "backend_inventory_sha256"
                else pins.backend_inventory_sha256
            ),
        )
    house = _wheelhouse(tmp_path / f"house-{variant}", house_payloads)
    destination = tmp_path / f"bundle-{variant}"
    if precreate_destination:
        destination.mkdir()
    options: dict[str, Any] = {
        "repo": repo,
        "commit": commit_override or commit,
        "house": house,
        "pins": pins,
        "destination": destination,
        "target_overrides": target_overrides,
    }
    return builder, task1, options


@pytest.mark.parametrize(
    "variant",
    [
        "missing-transitive",
        "wrong-arch",
        "hash-mismatch",
        "extra-wheelhouse",
        "swapped-source-commit",
        "dirty-checkout",
        "untracked-checkout",
        "swapped-lock-version",
        "nonzero-export",
        "nonzero-build",
        "nonzero-dryrun",
        "garbage-export",
        "destination-exists",
        "unsupported-platform",
        "unsupported-arch",
        "swapped-uv-python-pins",
        "wrong-uv-hash",
        "wrong-python-hash",
        "wrong-backend-hash",
        "wrong-python-version",
        "wrong-uv-version",
    ],
)
def test_incomplete_or_rehashed_target_closure_cannot_become_bundle(
    tmp_path: Path, variant: str
) -> None:
    builder, task1, options = _blocking_variant(tmp_path, variant)
    with pytest.raises(builder.BundleEvidenceError):
        _build(
            builder,
            task1,
            options["repo"],
            options["commit"],
            options["house"],
            options["pins"],
            options["destination"],
            **options["target_overrides"],
        )


def test_ignored_secret_cannot_leak_into_bundle(tmp_path: Path) -> None:
    builder = _builder()
    task1 = _task1()
    demo_payload = _demo_wheel()
    repo, commit = _make_repo(tmp_path, name="repo-leak")
    pins = _toolchain(builder, tmp_path)
    house = _wheelhouse(tmp_path / "house-leak", {_demo_filename(): demo_payload})
    destination = tmp_path / "bundle-leak"
    _build(builder, task1, repo, commit, house, pins, destination)
    assert (repo / "leaked.env").read_bytes().find(SECRET_MARKER) >= 0
    observed: list[Path] = []
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            observed.append(path.relative_to(destination))
            assert SECRET_MARKER not in path.read_bytes()
            assert "leaked" not in path.name and "hostile" not in path.name
    assert {str(p) for p in observed} == {
        "manifest.json",
        "uv.lock",
        "requirements.txt",
        f"wheels/{_demo_filename()}",
        "wheels/ksi_domain-0.0.1-py3-none-any.whl",
        "wheels/ksi_processing_controller-0.0.1-py3-none-any.whl",
    }


def test_builder_rejects_ambient_environment_or_unpinned_toolchain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _builder()
    task1 = _task1()
    monkeypatch.setenv("VIRTUAL_ENV", "/evil/venv")
    monkeypatch.setenv("PYTHONPATH", "/evil/site")
    monkeypatch.setenv("PYTHONHOME", "/evil/home")
    monkeypatch.setenv("UV_INDEX_URL", "http://evil.invalid/simple")
    monkeypatch.setenv("UV_OFFLINE", "0")
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "always")
    monkeypatch.setenv("CONDA_PREFIX", "/evil/conda")
    monkeypatch.setenv("PIP_INDEX_URL", "http://evil.invalid/simple")
    home = tmp_path / "private-home"
    cache = tmp_path / "private-cache"
    home.mkdir()
    cache.mkdir()
    child = builder._child_env(home, cache)
    for key in child:
        assert not key.startswith("PYTHON"), key
        if key.startswith("UV_"):
            assert key == "UV_CACHE_DIR", key
    for banned in (
        "UV_INDEX_URL",
        "UV_OFFLINE",
        "UV_PYTHON_DOWNLOADS",
        "VIRTUAL_ENV",
        "PYTHONPATH",
        "PYTHONHOME",
        "CONDA_PREFIX",
        "PIP_INDEX_URL",
        "VIRTUAL_ENV_PROMPT",
    ):
        assert banned not in child
    assert child["HOME"] == str(home)
    assert child["UV_CACHE_DIR"].startswith(str(cache))

    demo_payload = _demo_wheel()
    repo, commit = _make_repo(tmp_path, name="repo-ambient")
    pins = _toolchain(builder, tmp_path)
    house = _wheelhouse(tmp_path / "house-ambient", {_demo_filename(): demo_payload})
    receipt = _build(builder, task1, repo, commit, house, pins, tmp_path / "bundle-ambient")
    assert receipt.source_commit == commit

    for field in ("uv_sha256", "build_python_sha256", "backend_inventory_sha256"):
        values: dict[str, Any] = {
            "uv_path": pins.uv_path,
            "uv_sha256": pins.uv_sha256,
            "build_python": pins.build_python,
            "build_python_sha256": pins.build_python_sha256,
            "backend_inventory_path": pins.backend_inventory_path,
            "backend_inventory_sha256": pins.backend_inventory_sha256,
        }
        values[field] = "sha256:" + "0" * 64
        bad = builder.BuildToolchainPins(**values)
        with pytest.raises(builder.BundleEvidenceError):
            _build(
                builder,
                task1,
                repo,
                commit,
                house,
                bad,
                tmp_path / f"bundle-ambient-{field}",
            )


def _cli_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(UV_NO_SYNC="1", UV_OFFLINE="1", UV_PYTHON_DOWNLOADS="never")
    return env


def _cli_args(
    repo: Path, commit: str, house: Path, pins: Any, destination: Path
) -> list[str]:
    return [
        sys.executable,
        str(BUILD_TOOL),
        "--repo",
        str(repo),
        "--source-commit",
        commit,
        "--wheelhouse",
        str(house),
        "--uv",
        str(pins.uv_path),
        "--uv-sha256",
        pins.uv_sha256,
        "--build-python",
        str(pins.build_python),
        "--build-python-sha256",
        pins.build_python_sha256,
        "--backend-inventory",
        str(pins.backend_inventory_path),
        "--backend-inventory-sha256",
        pins.backend_inventory_sha256,
        "--libc-version",
        LIBC_VERSION,
        "--platform-tag",
        PLATFORM_TAG,
        "--destination",
        str(destination),
    ]


def test_builder_cli_creates_bundle_with_safe_json(tmp_path: Path) -> None:
    builder = _builder()
    demo_payload = _demo_wheel()
    repo, commit = _make_repo(tmp_path, name="repo-cli")
    pins = _toolchain(builder, tmp_path)
    house = _wheelhouse(tmp_path / "house-cli", {_demo_filename(): demo_payload})
    destination = tmp_path / "bundle-cli"
    good = subprocess.run(
        _cli_args(repo, commit, house, pins, destination),
        text=True,
        capture_output=True,
        check=False,
        env=_cli_env(),
    )
    assert good.returncode == 0, good.stderr
    assert good.stdout.count("\n") == 1
    data = json.loads(good.stdout)
    assert data["status"] == "BUNDLE_CREATED"
    assert data["sourceCommit"] == commit
    assert data["manifestSha256"] == _sha(destination / "manifest.json")
    assert str(destination) not in good.stderr

    rerun = subprocess.run(
        _cli_args(repo, commit, house, pins, destination),
        text=True,
        capture_output=True,
        check=False,
        env=_cli_env(),
    )
    assert rerun.returncode == 1
    assert rerun.stdout == ""
    assert "APPLICATION_BUNDLE_BLOCKED:" in rerun.stderr
    assert str(destination) not in rerun.stderr
    assert str(repo) not in rerun.stderr


def test_builder_cli_misuse_exits_two(tmp_path: Path) -> None:
    missing = subprocess.run(
        [sys.executable, str(BUILD_TOOL), "--repo", str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=_cli_env(),
    )
    assert missing.returncode == 2


def test_real_uv_dry_run_boundary(tmp_path: Path) -> None:
    builder = _builder()
    if not REAL_UV.is_file():
        pytest.skip("prepared uv binary is absent offline; no genuine boundary ran")
    probed = subprocess.run(
        [str(REAL_UV), "--version"], text=True, capture_output=True, check=False
    )
    if "0.11.15" not in probed.stdout:
        pytest.skip("real uv is not the prepared 0.11.15; refusing a foreign toolchain")
    requirements = tmp_path / "empty-requirements.txt"
    requirements.write_text("# synthetic empty requirements\n", encoding="utf-8")
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    home = tmp_path / "real-home"
    cache = tmp_path / "real-cache"
    home.mkdir()
    cache.mkdir()
    builder._prove_target_closure(
        uv_path=REAL_UV,
        build_python=Path(sys.executable),
        requirements=requirements,
        wheels_dir=wheels,
        scratch=scratch,
        platform_tag=PLATFORM_TAG,
        env=builder._child_env(home, cache),
    )
    assert [p for p in scratch.iterdir() if p.is_dir()] == []


FORK_LIBC: tuple[int, ...] = (2, 39)

FORK_LOCK_TEMPLATE = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "ksi-processing-controller"
version = "0.0.1"
source = { editable = "services/ksi-processing-controller" }
dependencies = [
    { name = "demo-native" },
]

@ENTRIES@"""

FORK_ENTRY_TEMPLATE = """\
[[package]]
name = "@NAME@"
version = "@VERSION@"
source = { registry = "https://pypi.org/simple" }
wheels = [
    { url = "https://example.invalid/@FILE@", hash = "sha256:@HASH@", size = @SIZE@ },
]
"""


def _fork_entry(name: str, version: str, filename: str) -> str:
    block = FORK_ENTRY_TEMPLATE.replace("@NAME@", name)
    block = block.replace("@VERSION@", version)
    block = block.replace("@FILE@", filename)
    block = block.replace("@HASH@", "a" * 64)
    return block.replace("@SIZE@", "12345")


def _fork_lock(entries: list[tuple[str, str, str]]) -> bytes:
    blocks = "\n".join(
        _fork_entry(name, version, filename) for name, version, filename in entries
    )
    return FORK_LOCK_TEMPLATE.replace("@ENTRIES@", blocks).encode("utf-8")


def _aarch64_filename(version: str) -> str:
    return f"demo_native-{version}-cp312-cp312-manylinux_2_28_aarch64.whl"


def _x86_64_filename(version: str) -> str:
    return f"demo_native-{version}-cp312-cp312-manylinux_2_28_x86_64.whl"


def test_lock_fork_unused_duplicate_parses_and_closure_ignores_it() -> None:
    builder = _builder()
    payload = _fork_lock([
        ("demo-native", "1.2.3", _aarch64_filename("1.2.3")),
        ("demo-unused", "1.0.0", "demo_unused-1.0.0-py3-none-any.whl"),
        ("demo-unused", "2.0.0", "demo_unused-2.0.0-py3-none-any.whl"),
    ])
    packages, _ = builder._parse_lock(payload)
    assert len(packages[builder._normalized("demo-unused")]) == 2
    workspace, external, _ = builder._closure(packages, PLATFORM_TAG, FORK_LIBC)
    assert workspace == {"ksi_processing_controller": "services/ksi-processing-controller"}
    assert external["demo_native"].version == "1.2.3"
    assert "demo_unused" not in external


def test_lock_fork_needed_name_selects_unique_compatible_candidate() -> None:
    builder = _builder()
    payload = _fork_lock([
        ("demo-native", "1.2.3", _x86_64_filename("1.2.3")),
        ("demo-native", "1.2.4", _aarch64_filename("1.2.4")),
    ])
    packages, _ = builder._parse_lock(payload)
    _, external, _ = builder._closure(packages, PLATFORM_TAG, FORK_LIBC)
    assert external["demo_native"].version == "1.2.4"
    filename, _ = builder._select_external_wheel(
        external["demo_native"], PLATFORM_TAG, FORK_LIBC
    )
    assert filename == _aarch64_filename("1.2.4")


def test_lock_fork_two_compatible_candidates_blocks() -> None:
    builder = _builder()
    payload = _fork_lock([
        ("demo-native", "1.2.3", _aarch64_filename("1.2.3")),
        ("demo-native", "1.2.4", _aarch64_filename("1.2.4")),
    ])
    packages, _ = builder._parse_lock(payload)
    with pytest.raises(builder.BundleEvidenceError, match="LOCK_FORK_AMBIGUOUS"):
        builder._closure(packages, PLATFORM_TAG, FORK_LIBC)


def test_lock_fork_zero_compatible_candidates_blocks() -> None:
    builder = _builder()
    payload = _fork_lock([
        ("demo-native", "1.2.3", _x86_64_filename("1.2.3")),
        ("demo-native", "1.2.4", _x86_64_filename("1.2.4")),
    ])
    packages, _ = builder._parse_lock(payload)
    with pytest.raises(builder.BundleEvidenceError, match="LOCK_FORK_AMBIGUOUS"):
        builder._closure(packages, PLATFORM_TAG, FORK_LIBC)


def test_builder_selects_cp311_abi3_wheel_for_target() -> None:
    builder = _builder()
    filename = "demo_native-1.2.3-cp311-abi3-manylinux_2_28_aarch64.whl"
    payload = _fork_lock([("demo-native", "1.2.3", filename)])
    packages, _ = builder._parse_lock(payload)
    _, external, _ = builder._closure(packages, PLATFORM_TAG, FORK_LIBC)
    selected, _ = builder._select_external_wheel(
        external["demo_native"], PLATFORM_TAG, FORK_LIBC
    )
    assert selected == filename


def test_builder_rejects_cp313_abi3_wheel_for_target() -> None:
    builder = _builder()
    filename = "demo_native-1.2.3-cp313-abi3-manylinux_2_28_aarch64.whl"
    payload = _fork_lock([("demo-native", "1.2.3", filename)])
    packages, _ = builder._parse_lock(payload)
    _, external, _ = builder._closure(packages, PLATFORM_TAG, FORK_LIBC)
    with pytest.raises(builder.BundleEvidenceError, match="WHEEL_TAG"):
        builder._select_external_wheel(external["demo_native"], PLATFORM_TAG, FORK_LIBC)


ABI3_LOCK_TEMPLATE = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "ksi-processing-controller"
version = "0.0.1"
source = { editable = "services/ksi-processing-controller" }
dependencies = [
    { name = "demo-native" },
]

[[package]]
name = "demo-native"
version = "1.2.3"
source = { registry = "https://pypi.org/simple" }
wheels = [
@ROWS@
]
"""


def _abi3_lock(filenames: list[str]) -> bytes:
    rows = []
    for name in filenames:
        rows.append(
            f'    {{ url = "https://example.invalid/{name}",'
            f' hash = "sha256:{"b" * 64}", size = 23456 }},'
        )
    return ABI3_LOCK_TEMPLATE.replace("@ROWS@", "\n".join(rows)).encode("utf-8")


def test_resolution_only_member_frozen_before_export_and_backend_recorded(
    tmp_path: Path,
) -> None:
    builder = _builder()
    task1 = _task1()
    demo_payload = _demo_wheel()
    extra_member = {
        "packages/ksi-extra/pyproject.toml": _member_pyproject(
            "ksi-extra", backend="setuptools.build_meta"
        ).encode(),
        "packages/ksi-extra/src/ksi_extra/__init__.py": b"# synthetic\n",
    }
    lock_text = _lock_text(demo_payload, extra_packages=KSI_EXTRA_PACKAGE)
    repo, commit = _make_repo(
        tmp_path, name="repo-resolution", lock_text=lock_text, extra_tracked=extra_member
    )
    pins = _toolchain(builder, tmp_path, uv_mode="check-staged")
    house = _wheelhouse(tmp_path / "house-resolution", {_demo_filename(): demo_payload})
    destination = tmp_path / "bundle-resolution"
    receipt = _build(builder, task1, repo, commit, house, pins, destination)
    assert sorted(p.name for p in (destination / "wheels").iterdir()) == [
        _demo_filename(),
        "ksi_domain-0.0.1-py3-none-any.whl",
        "ksi_processing_controller-0.0.1-py3-none-any.whl",
    ]
    assert receipt.resolution_backends == {"ksi-extra": "setuptools.build_meta"}


def test_builder_prefers_highest_abi3_floor_on_same_platform_tie() -> None:
    builder = _builder()
    payload = _abi3_lock([
        "demo_native-1.2.3-cp39-abi3-manylinux_2_34_aarch64.whl",
        "demo_native-1.2.3-cp311-abi3-manylinux_2_34_aarch64.whl",
    ])
    packages, _ = builder._parse_lock(payload)
    _, external, _ = builder._closure(packages, PLATFORM_TAG, FORK_LIBC)
    selected, _ = builder._select_external_wheel(
        external["demo_native"], PLATFORM_TAG, FORK_LIBC
    )
    assert selected == "demo_native-1.2.3-cp311-abi3-manylinux_2_34_aarch64.whl"


def test_builder_exact_cp312_still_wins_over_abi3() -> None:
    builder = _builder()
    payload = _abi3_lock([
        "demo_native-1.2.3-cp311-abi3-manylinux_2_34_aarch64.whl",
        "demo_native-1.2.3-cp312-cp312-manylinux_2_34_aarch64.whl",
    ])
    packages, _ = builder._parse_lock(payload)
    _, external, _ = builder._closure(packages, PLATFORM_TAG, FORK_LIBC)
    selected, _ = builder._select_external_wheel(
        external["demo_native"], PLATFORM_TAG, FORK_LIBC
    )
    assert selected == "demo_native-1.2.3-cp312-cp312-manylinux_2_34_aarch64.whl"


def test_verifier_accepts_dotted_py3_external_tags() -> None:
    task1 = _task1()
    assert task1._check_external_tags("py2.py3", "none", "any") is None


def test_verifier_ignores_description_body_after_blank_line() -> None:
    task1 = _task1()
    text = (
        "Metadata-Version: 2.1\n"
        "Name: demo-native\n"
        "Version: 1.2.3\n"
        "License: synthetic license text\n"
        "    continued on the next line\n"
        "\n"
        "# Demo\n"
        "body line without any colon\n"
    )
    distribution = task1._Distribution(
        name="demo-native",
        version="1.2.3",
        kind="external",
        wheel="wheels/demo_native-1.2.3-py3-none-any.whl",
        python_tag="py3",
        abi_tag="none",
        platform_tag="any",
    )
    assert (
        task1._check_dist_info_metadata(text, distribution, "demo_native") is None
    )


def test_verifier_rejects_continuation_of_name_or_version() -> None:
    task1 = _task1()
    text = (
        "Metadata-Version: 2.1\n"
        "Name: demo-native\n"
        "    smuggled-suffix\n"
        "Version: 1.2.3\n"
    )
    distribution = task1._Distribution(
        name="demo-native",
        version="1.2.3",
        kind="external",
        wheel="wheels/demo_native-1.2.3-py3-none-any.whl",
        python_tag="py3",
        abi_tag="none",
        platform_tag="any",
    )
    with pytest.raises(task1.BundleEvidenceError, match="METADATA_FIELD"):
        task1._check_dist_info_metadata(text, distribution, "demo_native")


def test_verifier_accepts_compressed_wheel_tags() -> None:
    task1 = _task1()
    distribution = task1._Distribution(
        name="demo-native",
        version="1.2.3",
        kind="external",
        wheel="wheels/demo_native-1.2.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.whl",
        python_tag="cp312",
        abi_tag="cp312",
        platform_tag="manylinux2014_aarch64.manylinux_2_17_aarch64",
    )
    text = (
        "Wheel-Version: 1.0\n"
        "Generator: synthetic\n"
        "Root-Is-Purelib: false\n"
        "Tag: cp312-cp312-manylinux2014_aarch64\n"
        "Tag: cp312-cp312-manylinux_2_17_aarch64\n"
    )
    assert task1._check_wheel_metadata(text, distribution) is None


def test_verifier_rejects_wheel_tag_outside_filename_tags() -> None:
    task1 = _task1()
    distribution = task1._Distribution(
        name="demo-native",
        version="1.2.3",
        kind="external",
        wheel="wheels/demo_native-1.2.3-cp312-cp312-manylinux_2_17_aarch64.whl",
        python_tag="cp312",
        abi_tag="cp312",
        platform_tag="manylinux_2_17_aarch64",
    )
    text = (
        "Wheel-Version: 1.0\n"
        "Generator: synthetic\n"
        "Root-Is-Purelib: false\n"
        "Tag: cp312-cp312-manylinux_2_28_x86_64\n"
    )
    with pytest.raises(task1.BundleEvidenceError, match="WHEEL_TAG"):
        task1._check_wheel_metadata(text, distribution)


def _wheel_with_directory_entry(payload: bytes, directory: str) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(payload))
    try:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for info in source.infolist():
                archive.writestr(info, source.read(info.filename))
            node = zipfile.ZipInfo(directory, date_time=(2026, 1, 1, 0, 0, 0))
            node.create_system = 3
            node.external_attr = 0o40755 << 16
            archive.writestr(node, b"")
        return buffer.getvalue()
    finally:
        source.close()


def test_verifier_ignores_directory_entries_in_record_coverage() -> None:
    task1 = _task1()
    wheel = build_wheel(
        "demo-native",
        "1.2.3",
        tags=("cp312", "cp312", "manylinux_2_28_aarch64"),
        root_is_purelib=False,
    )
    payload = _wheel_with_directory_entry(wheel, "demo_native/")
    distribution = task1._Distribution(
        name="demo-native",
        version="1.2.3",
        kind="external",
        wheel="wheels/demo_native-1.2.3-cp312-cp312-manylinux_2_28_aarch64.whl",
        python_tag="cp312",
        abi_tag="cp312",
        platform_tag="manylinux_2_28_aarch64",
    )
    assert task1._inspect_wheel(payload, distribution, task1._Budgets()) is None
