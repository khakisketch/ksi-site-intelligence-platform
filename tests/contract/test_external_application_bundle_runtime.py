"""Contract tests for the protected Python binding and private preparation.

Covers ``tools/verify_external_runtime_application_bundle.py``: static
binding proof without execution, fixed-probe gating, private preparation
orchestration, exec-preserving wrappers and CLI stage reporting.

All runtimes, records, wheels and programs are tiny labeled synthetics;
tests monkeypatch the tool's ``_REQUIRED_RUNTIME_UID``/``_ALLOWED_RUNTIME_ROOTS``
seams to the current user and synthetic prefixes. Genuine deployment
CPython binding/bundle inputs for a genuine installation are not supplied
to this suite. Genuine INSTALLATION_PREPARED stays NOT_RUN by an explicit
skip test regardless of host folders or the suite interpreter, never a fake pass.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from support.external_runtime_preparation_fixture import (
    FIXED_PROGRAMS,
    build_binding_record,
    build_runtime_tree,
    digest,
    stub_controller_wheel,
    write_binding_file,
    write_bundle_dir,
)

ROOT = Path(__file__).resolve().parents[2]
VERIFY_TOOL = ROOT / "tools/verify_external_runtime_application_bundle.py"
BINDING_SCHEMA = ROOT / "contracts/schemas/external-runtime-python-binding.v1.json"

REAL_UV_DIR = Path("/home/ksi/.local/bin")
SYNTHETIC_SEAM = (
    "SYNTHETIC-SEAM: probe identity substituted; "
    "all staging/venv/install/wrapper steps remain real"
)


def _verifier() -> Any:
    spec = importlib.util.spec_from_file_location(
        "verify_external_runtime_application_bundle", VERIFY_TOOL
    )
    if spec is None or spec.loader is None or not VERIFY_TOOL.is_file():
        raise RuntimeError("task3 verifier tool is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _target(tool: Any, **overrides: str) -> Any:
    fields = {
        "implementation": "CPython",
        "python_version": "3.12.15",
        "os": "linux",
        "architecture": "arm64",
        "libc_family": "glibc",
        "libc_version": "2.39",
        "platform_tag": "manylinux_2_39_aarch64",
    }
    fields.update(overrides)
    return tool.BundleTarget(**fields)


def _seams(tool: Any, monkeypatch: pytest.MonkeyPatch, allowed: Path) -> str:
    """Point ownership/root seams at the current user and a synthetic prefix."""
    monkeypatch.setattr(tool, "_REQUIRED_RUNTIME_UID", os.getuid())
    os.chmod(allowed, 0o755)
    monkeypatch.setattr(tool, "_ALLOWED_RUNTIME_ROOTS", (str(allowed),))
    return str(allowed)


def _tree_and_binding(
    tmp_path: Path, name: str = "case"
) -> tuple[dict[str, Any], dict[str, Any], Path, Path, Path]:
    base = tmp_path / name
    allowed = base / "allowed"
    allowed.mkdir(parents=True)
    os.chmod(allowed, 0o755)
    tree = build_runtime_tree(allowed)
    record = build_binding_record(tree)
    record_path = base / "binding.json"
    write_binding_file(record_path, record)
    return (tree, record, record_path, base, allowed)


def _make_guard(calls: list[str]) -> Any:
    class _Guard:
        def __getattr__(self, item: str) -> Any:
            def _boom(*args: Any, **kwargs: Any) -> Any:
                calls.append(item)
                raise AssertionError(f"static verification executed {item}")

            return _boom

    return _Guard()


def test_static_bundle_verification_succeeds_without_runtime_and_executes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _verifier()
    calls: list[str] = []
    monkeypatch.setattr(tool, "subprocess", _make_guard(calls))
    bundle_dir, manifest_sha, source, lock_sha = write_bundle_dir(tmp_path)
    result = tool.verify_application_bundle(
        bundle_dir,
        expected_manifest_sha256=manifest_sha,
        expected_source_commit=source,
        expected_lock_sha256=lock_sha,
    )
    assert result.source_commit == source
    assert [ (p.name, p.module, p.function) for p in result.entrypoints ] == [
        (n, m, f) for n, m, f in FIXED_PROGRAMS
    ]
    assert calls == []


def test_cli_static_reports_bundle_bytes_verified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tool = _verifier()
    bundle_dir, manifest_sha, source, lock_sha = write_bundle_dir(tmp_path)
    code = tool.main([
        "--bundle", str(bundle_dir),
        "--manifest-sha256", manifest_sha,
        "--source-commit", source,
        "--lock-sha256", lock_sha,
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    payload = json.loads(out)
    assert payload == {
        "status": "BUNDLE_BYTES_VERIFIED",
        "sourceCommit": source,
        "manifestSha256": manifest_sha,
    }


def test_binding_accepts_synthetic_root_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _verifier()
    calls: list[str] = []
    monkeypatch.setattr(tool, "subprocess", _make_guard(calls))
    tree, record, record_path, _base, allowed = _tree_and_binding(tmp_path)
    _seams(tool, monkeypatch, allowed)
    expected = digest(record_path.read_bytes())
    result = tool.verify_python_binding(
        record_path, expected_sha256=expected, target=_target(tool)
    )
    assert result.interpreter == tree["interpreter"]
    assert result.runtime_root == tree["root"]
    assert result.interpreter_sha256 == record["interpreter"]["sha256"]
    assert result.inventory_sha256 == record["inventorySha256"]
    assert result.native_inventory_sha256 == record["nativeInventorySha256"]
    assert result.target.python_version == "3.12.15"
    assert calls == []


def test_cli_binding_only_reports_runtime_binding_verified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _verifier()
    bundle_dir, manifest_sha, source, lock_sha = write_bundle_dir(tmp_path)
    _tree, _record, record_path, _base, allowed = _tree_and_binding(tmp_path)
    _seams(tool, monkeypatch, allowed)
    binding_sha = digest(record_path.read_bytes())
    code = tool.main([
        "--bundle", str(bundle_dir),
        "--manifest-sha256", manifest_sha,
        "--source-commit", source,
        "--lock-sha256", lock_sha,
        "--python-binding", str(record_path),
        "--python-binding-sha256", binding_sha,
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    payload = json.loads(out)
    assert payload == {
        "status": "RUNTIME_BINDING_VERIFIED",
        "sourceCommit": source,
        "manifestSha256": manifest_sha,
        "pythonBindingSha256": binding_sha,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-hash",
        "wrong-version",
        "wrong-implementation",
        "wrong-root",
        "bogus-runtime-uid",
        "record-mode",
        "record-hardlink",
        "record-is-dir",
        "record-owner",
        "writable-file",
        "symlink-file",
        "fifo-file",
        "ancestor-symlink",
        "writable-ancestor",
        "deep-ancestors",
        "inventory-tamper",
        "inventory-sha",
        "native-removed",
        "native-sha",
        "libc-mismatch",
        "platform-mismatch",
        "extra-key",
        "missing-key",
        "file-budget",
        "bytes-budget",
        "read-budget",
        "binding-size-budget",
        "native-limit",
        "no-exec-bit",
        "empty-interpreter",
        "duplicate-entry",
        "relative-entry",
        "dotdot-entry",
    ],
)
def test_missing_or_wrong_runtime_binding_blocks_before_any_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    tool = _verifier()
    calls: list[str] = []
    monkeypatch.setattr(tool, "subprocess", _make_guard(calls))
    tree, record, record_path, _base, allowed = _tree_and_binding(
        tmp_path, name=f"m-{mutation}"
    )
    _seams(tool, monkeypatch, allowed)
    expected = digest(record_path.read_bytes())

    def _rewrite() -> str:
        return write_binding_file(record_path, record)

    if mutation == "wrong-hash":
        expected = "sha256:" + "0" * 64
    elif mutation == "wrong-version":
        record["interpreter"]["version"] = "3.12.14"
        expected = _rewrite()
    elif mutation == "wrong-implementation":
        record["interpreter"]["implementation"] = "PyPy"
        expected = _rewrite()
    elif mutation == "wrong-root":
        record["runtimeRoot"] = "/usr"
        record["interpreter"]["path"] = sys.executable
        expected = _rewrite()
    elif mutation == "bogus-runtime-uid":
        monkeypatch.setattr(tool, "_REQUIRED_RUNTIME_UID", os.getuid() + 1)
    elif mutation == "record-mode":
        os.chmod(record_path, 0o644)
    elif mutation == "record-hardlink":
        os.link(record_path, record_path.with_suffix(".link"))
    elif mutation == "record-is-dir":
        record_path.unlink()
        record_path.mkdir()
        expected = "sha256:" + "0" * 64
    elif mutation == "record-owner":
        monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    elif mutation == "writable-file":
        target = tree["files"][1]
        os.chmod(target, 0o664)
    elif mutation == "symlink-file":
        target = tree["native"][0]
        payload = target.read_bytes()
        target.unlink()
        target.symlink_to(tree["files"][1])
        assert payload
    elif mutation == "fifo-file":
        extra = tree["root"] / "lib" / "extra.fifo"
        os.mkfifo(extra)
    elif mutation == "ancestor-symlink":
        real_bin = tree["root"] / "bin-real"
        (tree["root"] / "bin").rename(real_bin)
        (tree["root"] / "bin").symlink_to(real_bin)
    elif mutation == "writable-ancestor":
        os.chmod(tree["root"] / "lib", 0o775)
    elif mutation == "deep-ancestors":
        deep = tree["root"]
        for index in range(20):
            deep = deep / f"level{index:02d}"
            deep.mkdir()
            os.chmod(deep, 0o755)
        leaf = deep / "leaf.so"
        leaf.write_bytes(b"SYNTHETIC-DEEP\n")
        os.chmod(leaf, 0o644)
        tree["files"].append(leaf)
        record = build_binding_record(tree)
        expected = _rewrite()
    elif mutation == "inventory-tamper":
        with open(tree["files"][1], "ab") as handle:
            handle.write(b"tampered")
    elif mutation == "inventory-sha":
        record["inventorySha256"] = "sha256:" + "0" * 64
        expected = _rewrite()
    elif mutation == "native-removed":
        tree["native"][0].unlink()
    elif mutation == "native-sha":
        record["nativeInventorySha256"] = "sha256:" + "0" * 64
        expected = _rewrite()
    elif mutation == "libc-mismatch":
        record["target"]["libcVersion"] = "9.99"
        expected = _rewrite()
    elif mutation == "platform-mismatch":
        record["target"]["platformTag"] = "manylinux_2_99_aarch64"
        expected = _rewrite()
    elif mutation == "extra-key":
        record["extraField"] = True
        expected = _rewrite()
    elif mutation == "missing-key":
        del record["nativeInventory"]
        expected = _rewrite()
    elif mutation == "file-budget":
        monkeypatch.setattr(tool, "_MAX_RUNTIME_FILES", 2)
    elif mutation == "bytes-budget":
        monkeypatch.setattr(tool, "_MAX_RUNTIME_BYTES", 10)
    elif mutation == "read-budget":
        monkeypatch.setattr(tool, "_MAX_REQUEST_READ_BYTES", 10)
    elif mutation == "binding-size-budget":
        monkeypatch.setattr(tool, "_MAX_BINDING_BYTES", 10)
    elif mutation == "native-limit":
        monkeypatch.setattr(tool, "_MAX_NATIVE_ENTRIES", 1)
    elif mutation == "no-exec-bit":
        os.chmod(tree["interpreter"], 0o644)
    elif mutation == "empty-interpreter":
        tree["interpreter"].write_bytes(b"")
    elif mutation == "duplicate-entry":
        record["inventory"].append(dict(record["inventory"][0]))
        expected = _rewrite()
    elif mutation == "relative-entry":
        record["inventory"][0]["path"] = "relative/path.so"
        expected = _rewrite()
    elif mutation == "dotdot-entry":
        record["inventory"][0]["path"] = str(tree["root"]) + "/../escape.so"
        expected = _rewrite()
    else:
        raise AssertionError(f"unknown mutation {mutation}")

    with pytest.raises(tool.BundleEvidenceError):
        tool.verify_python_binding(
            record_path, expected_sha256=expected, target=_target(tool)
        )
    assert calls == []


def _tree_and_symlink_binding(
    tmp_path: Path,
    name: str,
    *,
    link_name: str = "python3",
    target: str = "python3.12",
    declare: bool = True,
    extra_links: list[tuple[str, str]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], Path, Path, Path, Path]:
    base = tmp_path / name
    allowed = base / "allowed"
    allowed.mkdir(parents=True)
    os.chmod(allowed, 0o755)
    tree = build_runtime_tree(allowed)
    link = tree["root"] / "bin" / link_name
    link.symlink_to(target)
    declared = [(str(link), target)] if declare else []
    declared.extend(extra_links or [])
    record = build_binding_record(tree, symlinks=declared or None)
    record_path = base / "binding.json"
    write_binding_file(record_path, record)
    return (tree, record, record_path, base, allowed, link)


def test_declared_runtime_symlink_inside_root_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    tool = _verifier()
    calls: list[str] = []
    monkeypatch.setattr(tool, "subprocess", _make_guard(calls))
    tree, record, record_path, _base, allowed, link = _tree_and_symlink_binding(
        tmp_path, "sym-ok"
    )
    _seams(tool, monkeypatch, allowed)
    validator = jsonschema.Draft202012Validator(
        json.loads(BINDING_SCHEMA.read_bytes())
    )
    validator.validate(record)
    expected = digest(record_path.read_bytes())
    result = tool.verify_python_binding(
        record_path, expected_sha256=expected, target=_target(tool)
    )
    assert result.interpreter == tree["interpreter"]
    assert not tree["interpreter"].is_symlink()
    assert link.is_symlink()
    assert os.readlink(link) == "python3.12"
    assert calls == []


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("undeclared", "INVENTORY_COVERAGE"),
        ("dangling", "LINK_TARGET"),
        ("escaping", "LINK_TARGET"),
        ("absolute", "LINK_TARGET"),
        ("chain", "LINK_TARGET"),
    ],
)
def test_runtime_symlink_misuse_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, code: str
) -> None:
    tool = _verifier()
    calls: list[str] = []
    monkeypatch.setattr(tool, "subprocess", _make_guard(calls))
    if case == "undeclared":
        tree, _record, record_path, _base, allowed, _link = _tree_and_symlink_binding(
            tmp_path, f"sym-{case}", declare=False
        )
    elif case == "dangling":
        tree, _record, record_path, _base, allowed, _link = _tree_and_symlink_binding(
            tmp_path, f"sym-{case}", link_name="dangling", target="missing.so"
        )
    elif case == "escaping":
        tree, _record, record_path, _base, allowed, _link = _tree_and_symlink_binding(
            tmp_path, f"sym-{case}", link_name="escape", target="../escape.so"
        )
    elif case == "absolute":
        tree, _record, record_path, _base, allowed, _link = _tree_and_symlink_binding(
            tmp_path, f"sym-{case}", link_name="absl", target="/etc/hostname"
        )
    elif case == "chain":
        base = tmp_path / f"sym-{case}"
        allowed = base / "allowed"
        allowed.mkdir(parents=True)
        os.chmod(allowed, 0o755)
        tree = build_runtime_tree(allowed)
        first = tree["root"] / "lib" / "link1"
        first.symlink_to("libsynth-native.so")
        second = tree["root"] / "lib" / "link2"
        second.symlink_to("link1")
        record = build_binding_record(
            tree,
            symlinks=[(str(first), "libsynth-native.so"), (str(second), "link1")],
        )
        record_path = base / "binding.json"
        write_binding_file(record_path, record)
    else:
        raise AssertionError(f"unknown case {case}")
    assert tree
    _seams(tool, monkeypatch, allowed)
    expected = digest(record_path.read_bytes())
    with pytest.raises(tool.BundleEvidenceError) as excinfo:
        tool.verify_python_binding(
            record_path, expected_sha256=expected, target=_target(tool)
        )
    assert excinfo.value.code == code
    assert calls == []


def test_home_or_path_candidate_runtime_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _verifier()
    tree, record, record_path, _base, allowed = _tree_and_binding(tmp_path)
    _seams(tool, monkeypatch, allowed)
    record["runtimeRoot"] = str(Path(sys.executable).parent)
    record["interpreter"]["path"] = sys.executable
    expected = write_binding_file(record_path, record)
    with pytest.raises(tool.BundleEvidenceError):
        tool.verify_python_binding(
            record_path, expected_sha256=expected, target=_target(tool)
        )


def _fake_script(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    os.chmod(path, 0o755)
    return path


_GOOD_PROBE = (
    '{"implementation":"CPython","version":"3.12.15","os":"linux",'
    '"architecture":"arm64","libcFamily":"glibc","libcVersion":"2.39",'
    '"entrypointsOk":true}'
)


def test_probe_good_output_passes(tmp_path: Path) -> None:
    tool = _verifier()
    script = _fake_script(
        tmp_path / "good-python", "#!/bin/sh\nprintf '%s' '" + _GOOD_PROBE + "'\n"
    )
    facts = tool._run_fixed_probe(script, _target(tool))
    assert facts["version"] == "3.12.15"
    assert facts["entrypointsOk"] is True


def test_probe_wrong_facts_block(tmp_path: Path) -> None:
    tool = _verifier()
    bad = _GOOD_PROBE.replace("3.12.15", "3.12.14")
    script = _fake_script(
        tmp_path / "old-python", "#!/bin/sh\nprintf '%s' '" + bad + "'\n"
    )
    with pytest.raises(tool.BundleEvidenceError):
        tool._run_fixed_probe(script, _target(tool))


def test_probe_malformed_output_blocks(tmp_path: Path) -> None:
    tool = _verifier()
    script = _fake_script(
        tmp_path / "garbage-python", "#!/bin/sh\nprintf 'not json{{{\n'\n"
    )
    with pytest.raises(tool.BundleEvidenceError):
        tool._run_fixed_probe(script, _target(tool))


def test_probe_nonzero_with_plausible_stdout_never_grants(tmp_path: Path) -> None:
    tool = _verifier()
    script = _fake_script(
        tmp_path / "failing-python",
        "#!/bin/sh\nprintf '%s' '" + _GOOD_PROBE + "'\nexit 3\n",
    )
    with pytest.raises(tool.BundleEvidenceError):
        tool._run_fixed_probe(script, _target(tool))


def test_probe_oversize_output_blocks(tmp_path: Path) -> None:
    tool = _verifier()
    script = _fake_script(
        tmp_path / "chatty-python",
        "#!/bin/sh\nhead -c 70000 /dev/zero | tr '\\0' 'x'\n",
    )
    with pytest.raises(tool.BundleEvidenceError):
        tool._run_fixed_probe(script, _target(tool))


def test_probe_timeout_reaps_owned_process_group(tmp_path: Path) -> None:
    tool = _verifier()
    marker = "SYNTHETIC-SLEEPER-TASK3-PROBE"
    script = _fake_script(
        tmp_path / "sleepy-python",
        "#!/bin/sh\n# " + marker + "\nexec sleep 60\n",
    )
    with pytest.raises(tool.BundleEvidenceError) as excinfo:
        tool._run_fixed_probe(script, _target(tool), timeout_s=1)
    assert excinfo.value.code == "PROBE_TIMEOUT"
    completed = subprocess.run(
        ["pgrep", "-f", marker], capture_output=True, text=True, timeout=10
    )
    assert completed.returncode != 0


def _prepare_paths(tmp_path: Path) -> tuple[Path, str, str, str]:
    return write_bundle_dir(
        tmp_path,
        wheel_overrides={
            "ksi_processing_controller-0.0.1-py3-none-any.whl": stub_controller_wheel()
        },
    )


def _verified_bundle(tool: Any, tmp_path: Path) -> Any:
    bundle_dir, manifest_sha, source, lock_sha = _prepare_paths(tmp_path)
    return tool.verify_application_bundle(
        bundle_dir,
        expected_manifest_sha256=manifest_sha,
        expected_source_commit=source,
        expected_lock_sha256=lock_sha,
    )


def _prepare_env(
    tool: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[dict[str, Any], dict[str, Any], Path, str, Any]:
    bundle = _verified_bundle(tool, tmp_path)
    tree, record, record_path, _base, allowed = _tree_and_binding(tmp_path, name="prep")
    _seams(tool, monkeypatch, allowed)
    binding_sha = digest(record_path.read_bytes())
    return (tree, record, record_path, binding_sha, bundle)


def _stub_probe_seam(tool: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_probe(
        python_exe: Path, target: Any, timeout_s: int = 15
    ) -> dict[str, Any]:
        assert SYNTHETIC_SEAM
        return {
            "implementation": "CPython",
            "version": "3.12.15",
            "os": "linux",
            "architecture": "arm64",
            "libcFamily": "glibc",
            "libcVersion": "2.39",
            "entrypointsOk": True,
        }

    monkeypatch.setattr(tool, "_run_fixed_probe", _fake_probe)


def test_prepare_rejects_existing_or_symlinked_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _verifier()
    tree, _record, record_path, binding_sha, bundle = _prepare_env(
        tool, monkeypatch, tmp_path
    )
    assert tree
    existing = tmp_path / "dest-exists"
    existing.mkdir()
    with pytest.raises(tool.BundleEvidenceError):
        tool.prepare_application_installation(
            bundle,
            python_binding=record_path,
            expected_python_binding_sha256=binding_sha,
            destination=existing,
        )
    link = tmp_path / "dest-link"
    link.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(tool.BundleEvidenceError):
        tool.prepare_application_installation(
            bundle,
            python_binding=record_path,
            expected_python_binding_sha256=binding_sha,
            destination=link,
        )


def test_prepare_respects_expanded_and_walk_budgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _verifier()
    _tree, _record, record_path, binding_sha, bundle = _prepare_env(
        tool, monkeypatch, tmp_path
    )
    monkeypatch.setattr(tool, "_MAX_EXPANDED_BYTES", 10)
    with pytest.raises(tool.BundleEvidenceError):
        tool.prepare_application_installation(
            bundle,
            python_binding=record_path,
            expected_python_binding_sha256=binding_sha,
            destination=tmp_path / "dest-small",
        )


def test_prepare_revalidates_walk_budget_at_use_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _verifier()
    _tree, _record, record_path, binding_sha, bundle = _prepare_env(
        tool, monkeypatch, tmp_path
    )
    monkeypatch.setattr(tool, "_MAX_RUNTIME_FILES", 1)
    with pytest.raises(tool.BundleEvidenceError):
        tool.prepare_application_installation(
            bundle,
            python_binding=record_path,
            expected_python_binding_sha256=binding_sha,
            destination=tmp_path / "dest-walk",
        )


@pytest.mark.parametrize("swap", ["wheel", "manifest", "binding"])
def test_verified_inputs_swapped_before_prepare_are_not_cached_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap: str
) -> None:
    tool = _verifier()
    _stub_probe_seam(tool, monkeypatch)
    tree, _record, record_path, binding_sha, bundle = _prepare_env(
        tool, monkeypatch, tmp_path
    )
    assert tree
    bundle_dir = bundle.bundle_root
    if swap == "wheel":
        wheels = sorted((bundle_dir / "wheels").glob("*.whl"))
        with open(wheels[0], "ab") as handle:
            handle.write(b"swapped")
    elif swap == "manifest":
        manifest = bundle_dir / "manifest.json"
        payload = bytearray(manifest.read_bytes())
        payload[-16] ^= 0x01
        manifest.write_bytes(bytes(payload))
    elif swap == "binding":
        os.chmod(record_path, 0o600)
        with open(record_path, "ab") as handle:
            handle.write(b" ")
    else:
        raise AssertionError(f"unknown swap {swap}")
    with pytest.raises(tool.BundleEvidenceError):
        tool.prepare_application_installation(
            bundle,
            python_binding=record_path,
            expected_python_binding_sha256=binding_sha,
            destination=tmp_path / f"dest-{swap}",
        )


def test_prepare_probe_failure_retains_owned_path_without_broad_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _verifier()
    tree, _record, record_path, binding_sha, bundle = _prepare_env(
        tool, monkeypatch, tmp_path
    )
    sentinel = tmp_path / "outside-sentinel.txt"
    sentinel.write_text("untouched", encoding="utf-8")

    def _boom(python_exe: Path, target: Any, timeout_s: int = 15) -> dict[str, Any]:
        raise tool.BundleEvidenceError("PROBE_EXIT")

    monkeypatch.setattr(tool, "_run_fixed_probe", _boom)
    destination = tmp_path / "dest-failed-probe"
    with pytest.raises(tool.BundleEvidenceError):
        tool.prepare_application_installation(
            bundle,
            python_binding=record_path,
            expected_python_binding_sha256=binding_sha,
            destination=destination,
        )
    assert destination.is_dir()
    assert (destination / "staged").is_dir()
    assert sentinel.read_text(encoding="utf-8") == "untouched"
    assert tree["root"].parent.is_dir()


def _require_real_uv(monkeypatch: pytest.MonkeyPatch) -> str:
    uv = REAL_UV_DIR / "uv"
    if not uv.is_file():
        pytest.skip("prepared uv binary absent: real install path NOT_RUN")
    monkeypatch.setenv(
        "PATH", str(REAL_UV_DIR) + os.pathsep + os.environ.get("PATH", "")
    )
    return str(uv)


def _exec_shim(path: Path, real_python: str) -> None:
    path.write_text(f"#!/bin/sh\nexec {real_python} \"$@\"\n", encoding="utf-8")
    os.chmod(path, 0o755)


def test_real_offline_venv_install_reaches_probe_version_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Genuine venv + genuine offline hashed uv install; probe must block.

    The environment Python is 3.12.x, not deployment 3.12.15, so the fixed
    probe genuinely refuses with PROBE_VERSION. That refusal, plus the
    retained staged/venv state, is the honest evidence — not a fake grant.
    """
    tool = _verifier()
    _require_real_uv(monkeypatch)
    bundle = _verified_bundle(tool, tmp_path)
    base = tmp_path / "real"
    (base / "allowed").mkdir(parents=True)
    tree = build_runtime_tree(base / "allowed")
    _seams(tool, monkeypatch, base / "allowed")
    _exec_shim(tree["interpreter"], sys.executable)
    record = build_binding_record(tree)
    record_path = base / "binding.json"
    binding_sha = write_binding_file(record_path, record)
    destination = tmp_path / "dest-real"
    with pytest.raises(tool.BundleEvidenceError) as excinfo:
        tool.prepare_application_installation(
            bundle,
            python_binding=record_path,
            expected_python_binding_sha256=binding_sha,
            destination=destination,
        )
    assert excinfo.value.code == "PROBE_VERSION"
    assert destination.is_dir()
    assert (destination / "staged").is_dir()
    assert (destination / "venv" / "bin" / "python").exists()


def test_installation_prepared_success_with_labeled_probe_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _verifier()
    _require_real_uv(monkeypatch)
    _stub_probe_seam(tool, monkeypatch)
    bundle = _verified_bundle(tool, tmp_path)
    base = tmp_path / "synth-ok"
    (base / "allowed").mkdir(parents=True)
    tree = build_runtime_tree(base / "allowed")
    _seams(tool, monkeypatch, base / "allowed")
    _exec_shim(tree["interpreter"], sys.executable)
    record = build_binding_record(tree)
    record_path = base / "binding.json"
    binding_sha = write_binding_file(record_path, record)
    destination = tmp_path / "dest-ok"
    receipt = tool.prepare_application_installation(
        bundle,
        python_binding=record_path,
        expected_python_binding_sha256=binding_sha,
        destination=destination,
    )
    assert receipt.status == "INSTALLATION_PREPARED"
    assert receipt.source_commit == bundle.source_commit
    assert receipt.bundle_sha256 == bundle.manifest_sha256
    assert receipt.python_binding_sha256 == binding_sha
    assert receipt.verification_code.commit_sha == bundle.source_commit
    assert len(receipt.verification_code.files) == 3
    for digest_row in receipt.verification_code.files:
        candidate = ROOT / digest_row.relative_path
        assert candidate.is_file()
        assert digest_row.sha256 == digest(candidate.read_bytes())
    preparation = json.loads((destination / "preparation.json").read_bytes())
    assert preparation["status"] == "INSTALLATION_PREPARED"
    assert preparation["preparedInventorySha256"] == receipt.prepared_inventory_sha256
    planned = json.loads(
        (destination / "planned-install-inventory.json").read_bytes()
    )
    assert [row["path"] for row in planned] == sorted(row["path"] for row in planned)
    assert {row["path"] for row in planned} == {
        f"/usr/local/lib/ksi-external-runtime/bin/{name}" for name, _, _ in FIXED_PROGRAMS
    }
    for name, _module, _function in FIXED_PROGRAMS:
        wrapper = destination / "bin" / name
        assert wrapper.is_file()
        assert os.access(wrapper, os.X_OK)
        assert not wrapper.is_symlink()
    venv_python = destination / "venv" / "bin" / "python"
    completed = subprocess.run(
        [str(venv_python), "-c", "import ksi_processing_controller"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0


def _run_wrapper(
    path: Path, args: list[str], env: dict[str, str], fd_payload: bytes
) -> tuple[int, bytes, int]:
    pipe_r, pipe_w = os.pipe()
    out_r, out_w = os.pipe()
    os.write(pipe_w, fd_payload)
    os.close(pipe_w)
    os.set_inheritable(out_r, False)
    os.set_inheritable(pipe_r, False)
    pid = os.fork()
    if pid == 0:
        try:
            if pipe_r != 3:
                os.dup2(pipe_r, 3)
                os.close(pipe_r)
            os.dup2(out_w, 1)
            os.close(out_w)
            os.close(out_r)
            os.execve(str(path), [path.name, *args], env)
        except BaseException:
            os._exit(127)
    os.close(out_w)
    os.close(pipe_r)
    chunks: list[bytes] = []
    while True:
        piece = os.read(out_r, 65536)
        if not piece:
            break
        chunks.append(piece)
    os.close(out_r)
    _child, status = os.waitpid(pid, 0)
    return (pid, b"".join(chunks), status)


def test_private_wrappers_preserve_exec_pid_fds_and_clean_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _verifier()
    _require_real_uv(monkeypatch)
    _stub_probe_seam(tool, monkeypatch)
    bundle = _verified_bundle(tool, tmp_path)
    base = tmp_path / "synth-wrap"
    (base / "allowed").mkdir(parents=True)
    tree = build_runtime_tree(base / "allowed")
    _seams(tool, monkeypatch, base / "allowed")
    _exec_shim(tree["interpreter"], sys.executable)
    record = build_binding_record(tree)
    record_path = base / "binding.json"
    binding_sha = write_binding_file(record_path, record)
    destination = tmp_path / "dest-wrap"
    tool.prepare_application_installation(
        bundle,
        python_binding=record_path,
        expected_python_binding_sha256=binding_sha,
        destination=destination,
    )
    payload = b"SYNTHETIC-FD3-PAYLOAD-4d21"
    for name, _module, _function in FIXED_PROGRAMS:
        wrapper = destination / "bin" / name
        env = {
            "PYTHONPATH": "/evil/synthetic-path",
            "VIRTUAL_ENV": "/evil/synthetic-venv",
            "UV_INDEX_URL": "http://evil.invalid/simple",
            "LISTEN_PID": "424242",
            "LISTEN_FDS": "1",
        }
        pid, out, status = _run_wrapper(
            wrapper, ["--synthetic-arg"], env, payload
        )
        assert status == 0
        report = json.loads(out.decode("utf-8").strip().splitlines()[-1])
        assert report["marker"] == "SYNTHETIC-PREPARATION-STUB"
        assert report["pid"] == pid
        assert report["argv"] == ["--synthetic-arg"]
        assert report["listenPid"] == "424242"
        assert report["listenFds"] == "1"
        assert report["fd3"] == payload.decode("utf-8")
        assert report["pythonpath"] is None
        assert report["virtualEnv"] is None
        assert report["uvIndex"] is None


def test_old_success_receipt_is_not_reused_after_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _verifier()
    _require_real_uv(monkeypatch)
    _stub_probe_seam(tool, monkeypatch)
    bundle = _verified_bundle(tool, tmp_path)
    base = tmp_path / "synth-receipt"
    (base / "allowed").mkdir(parents=True)
    tree = build_runtime_tree(base / "allowed")
    _seams(tool, monkeypatch, base / "allowed")
    _exec_shim(tree["interpreter"], sys.executable)
    record = build_binding_record(tree)
    record_path = base / "binding.json"
    binding_sha = write_binding_file(record_path, record)
    first = tmp_path / "dest-first"
    receipt = tool.prepare_application_installation(
        bundle,
        python_binding=record_path,
        expected_python_binding_sha256=binding_sha,
        destination=first,
    )
    assert receipt.status == "INSTALLATION_PREPARED"
    wheels = sorted((bundle.bundle_root / "wheels").glob("*.whl"))
    with open(wheels[0], "ab") as handle:
        handle.write(b"late-swap")
    with pytest.raises(tool.BundleEvidenceError):
        tool.prepare_application_installation(
            bundle,
            python_binding=record_path,
            expected_python_binding_sha256=binding_sha,
            destination=tmp_path / "dest-second",
        )


def test_cli_prepare_root_without_binding_flags_rejects(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tool = _verifier()
    bundle_dir, manifest_sha, source, lock_sha = write_bundle_dir(tmp_path)
    code = tool.main([
        "--bundle", str(bundle_dir),
        "--manifest-sha256", manifest_sha,
        "--source-commit", source,
        "--lock-sha256", lock_sha,
        "--prepare-root", str(tmp_path / "dest-cli"),
    ])
    assert code == 1
    streams = capsys.readouterr()
    assert streams.out == ""
    assert "APPLICATION_BUNDLE_BLOCKED" in streams.err


def test_cli_partial_binding_flags_reject(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _verifier()
    bundle_dir, manifest_sha, source, lock_sha = write_bundle_dir(tmp_path)
    _tree, _record, record_path, _base, allowed = _tree_and_binding(tmp_path)
    _seams(tool, monkeypatch, allowed)
    binding_sha = digest(record_path.read_bytes())
    code = tool.main([
        "--bundle", str(bundle_dir),
        "--manifest-sha256", manifest_sha,
        "--source-commit", source,
        "--lock-sha256", lock_sha,
        "--python-binding", str(record_path),
    ])
    assert code == 1
    streams = capsys.readouterr()
    assert streams.out == ""
    assert "APPLICATION_BUNDLE_BLOCKED" in streams.err
    assert str(record_path) not in streams.err
    code = tool.main([
        "--bundle", str(bundle_dir),
        "--manifest-sha256", manifest_sha,
        "--source-commit", source,
        "--lock-sha256", lock_sha,
        "--python-binding-sha256", binding_sha,
    ])
    assert code == 1
    assert capsys.readouterr().out == ""


def test_cli_block_emits_safe_stderr_without_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tool = _verifier()
    bundle_dir, manifest_sha, _source, lock_sha = write_bundle_dir(tmp_path)
    code = tool.main([
        "--bundle", str(bundle_dir),
        "--manifest-sha256", "sha256:" + "0" * 64,
        "--source-commit", "a" * 40,
        "--lock-sha256", lock_sha,
    ])
    assert code == 1
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err.startswith("APPLICATION_BUNDLE_BLOCKED: ")
    assert str(tmp_path) not in streams.err
    assert str(bundle_dir) not in streams.err


def test_cli_missing_required_flags_may_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tool = _verifier()
    with pytest.raises(SystemExit) as excinfo:
        tool.main(["--bundle", str(tmp_path)])
    assert excinfo.value.code == 2


def test_cli_prepare_reports_installation_prepared(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _verifier()
    _require_real_uv(monkeypatch)
    _stub_probe_seam(tool, monkeypatch)
    bundle = _verified_bundle(tool, tmp_path)
    base = tmp_path / "synth-cli"
    (base / "allowed").mkdir(parents=True)
    tree = build_runtime_tree(base / "allowed")
    _seams(tool, monkeypatch, base / "allowed")
    _exec_shim(tree["interpreter"], sys.executable)
    record = build_binding_record(tree)
    record_path = base / "binding.json"
    binding_sha = write_binding_file(record_path, record)
    destination = tmp_path / "dest-cli-ok"
    code = tool.main([
        "--bundle", str(bundle.bundle_root),
        "--manifest-sha256", bundle.manifest_sha256,
        "--source-commit", bundle.source_commit,
        "--lock-sha256", bundle.lock_sha256,
        "--python-binding", str(record_path),
        "--python-binding-sha256", binding_sha,
        "--prepare-root", str(destination),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    payload = json.loads(out)
    assert payload["status"] == "INSTALLATION_PREPARED"
    assert payload["pythonBindingSha256"] == binding_sha
    assert (destination / "preparation.json").is_file()


def test_binding_schema_mirrors_static_gates(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(BINDING_SCHEMA.read_bytes())
    assert BINDING_SCHEMA.is_file()
    validator_class = jsonschema.Draft202012Validator
    validator_class.check_schema(schema)
    validator = validator_class(schema)
    _tree, record, _path, _base, _allowed = _tree_and_binding(tmp_path, name="schema")
    validator.validate(record)

    def _mutated(kind: str) -> dict[str, Any]:
        clone = json.loads(json.dumps(record))
        if kind == "version":
            clone["interpreter"]["version"] = "3.12.14"
        elif kind == "extra":
            clone["extra"] = True
        elif kind == "missing":
            del clone["nativeInventory"]
        elif kind == "digest":
            clone["inventorySha256"] = "nope"
        elif kind == "schema":
            clone["schemaVersion"] = "external-runtime-python-binding.v0"
        elif kind == "mode":
            clone["interpreter"]["bytes"] = -3
        return clone

    for kind in ("version", "extra", "missing", "digest", "schema", "mode"):
        assert not validator.is_valid(_mutated(kind)), kind


def test_genuine_installation_prepared_is_separate_operational_gate() -> None:
    # A folder and the test runner's version prove neither the target interpreter's
    # binding nor wheelhouse/source/lock pins. Only the separately supplied genuine
    # bundle + protected binding can exercise the verifier's preparation stage.
    pytest.skip(
        "genuine pinned bundle/binding inputs not supplied to this synthetic suite: "
        "INSTALLATION_PREPARED against genuine inputs NOT_RUN"
    )
