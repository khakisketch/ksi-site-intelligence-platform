"""Scanner compatibility never fabricates authority or changes original report bytes."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_TOOL = Path(__file__).resolve().parents[2] / "tools/verify_external_scanner_evidence.py"
_IMAGE = "sha256:" + "a" * 64


def _tool() -> Any:
    assert _TOOL.is_file(), "native scanner verifier has not been implemented"
    spec = importlib.util.spec_from_file_location("verify_external_scanner_evidence", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _native() -> dict[str, Any]:
    # Labeled fixture using observed Grype 0.120.0 shape, never release evidence.
    return {
        "descriptor": {
            "name": "grype",
            "version": "0.120.0",
            "timestamp": "2026-10-03T20:04:35+09:00",
            "configuration": {},
            "db": {
                "status": {"valid": True, "schemaVersion": "v6.1.10", "built": "2026-10-03"},
                "providers": {},
            },
        },
        "source": {
            "type": "image",
            "target": {
                "imageID": _IMAGE,
                "manifestDigest": "sha256:" + "b" * 64,
                "repoDigests": [],
                "architecture": "arm64",
                "os": "linux",
            },
        },
        "distro": {"name": "debian", "version": "13"},
        "matches": [{"vulnerability": {"id": "CVE-FIXTURE", "severity": "High"},
                     "artifact": {"name": "fixture-package", "version": "1.0"}}],
    }


def _write(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "scanner.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _verify(tool: Any, path: Path, image_id: str | None = _IMAGE) -> str:
    payload = path.read_bytes()
    return tool.verify_scanner_evidence(
        path,
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_bytes=len(payload),
        expected_image_id=image_id,
    )


@pytest.mark.parametrize("native", [False, True])
def test_legacy_and_native_reports_are_disjoint_and_byte_bound(
    tmp_path: Path, native: bool,
) -> None:
    tool = _tool()
    value = _native() if native else {"scanner": {"name": "test", "schemaVersion": "1.0"}}
    path = _write(tmp_path, value)
    before = path.read_bytes()
    assert _verify(tool, path) == ("grype-0.120.0" if native else "legacy")
    assert path.read_bytes() == before
    with pytest.raises(tool.ScannerEvidenceError):
        tool.verify_scanner_evidence(
            path, expected_sha256="sha256:" + "0" * 64,
            expected_bytes=len(before), expected_image_id=_IMAGE,
        )


@pytest.mark.parametrize("image_id", [None, "sha256:" + "b" * 64, "invalid"])
def test_native_requires_exact_expected_config_image(tmp_path: Path, image_id: str | None) -> None:
    tool = _tool()
    with pytest.raises(tool.ScannerEvidenceError):
        _verify(tool, _write(tmp_path, _native()), image_id)


@pytest.mark.parametrize("keypath,value", [
    (("descriptor", "name"), "other"),
    (("descriptor", "version"), "0.121.0"),
    (("descriptor", "timestamp"), ""),
    (("descriptor", "configuration"), []),
    (("descriptor", "db", "providers"), []),
    (("descriptor", "db", "status", "valid"), False),
    (("descriptor", "db", "status", "valid"), 1),
    (("descriptor", "db", "status", "schemaVersion"), "v7.0.0"),
    (("descriptor", "db", "status", "built"), ""),
    (("source", "type"), "directory"),
    (("source", "target", "imageID"), "sha256:" + "B" * 64),
    (("matches",), None),
    (("matches",), [None]),
    (("matches",), [{"vulnerability": {}, "artifact": {}}]),
    (("ignoredMatches",), "not-an-array"),
])
def test_native_profile_rejects_malformed_fields(
    tmp_path: Path, keypath: tuple[str, ...], value: object,
) -> None:
    tool = _tool()
    report = _native()
    target = report
    for key in keypath[:-1]:
        target = target[key]
    target[keypath[-1]] = value
    with pytest.raises(tool.ScannerEvidenceError):
        _verify(tool, _write(tmp_path, report))


@pytest.mark.parametrize("remove", ["descriptor", "source", "matches"])
def test_missing_native_fields_never_fall_back(tmp_path: Path, remove: str) -> None:
    tool = _tool()
    report = _native()
    report.pop(remove)
    with pytest.raises(tool.ScannerEvidenceError):
        _verify(tool, _write(tmp_path, report))


def test_mixed_families_and_empty_scanner_rejected(tmp_path: Path) -> None:
    tool = _tool()
    mixed = _native()
    mixed["scanner"] = {"name": "test", "schemaVersion": "1.0"}
    for value in [mixed, {}, {"scanner": {}}, {"scanner": {"name": "grype"}}]:
        with pytest.raises(tool.ScannerEvidenceError):
            _verify(tool, _write(tmp_path, value))


def test_zero_matches_and_ignored_findings_are_preserved_without_policy(tmp_path: Path) -> None:
    tool = _tool()
    report = _native()
    report["ignoredMatches"] = copy.deepcopy(report["matches"])
    report["matches"] = []
    path = _write(tmp_path, report)
    original = path.read_bytes()
    assert _verify(tool, path) == "grype-0.120.0"
    assert path.read_bytes() == original
    assert json.loads(original)["ignoredMatches"][0]["vulnerability"]["severity"] == "High"


@pytest.mark.parametrize("key,value", [
    ("os", "windows"), ("architecture", "amd64"), ("os", None), ("architecture", None),
])
def test_native_scanner_platform_is_required_only_when_requested(
    tmp_path: Path, key: str, value: object,
) -> None:
    tool = _tool()
    report = _native()
    if value is None:
        del report["source"]["target"][key]
    else:
        report["source"]["target"][key] = value
    path = _write(tmp_path, report)
    assert _verify(tool, path) == "grype-0.120.0"
    payload = path.read_bytes()
    with pytest.raises(tool.ScannerEvidenceError):
        tool.verify_scanner_evidence(
            path, expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
            expected_bytes=len(payload), expected_image_id=_IMAGE, require_linux_arm64=True,
        )


@pytest.mark.parametrize("native", [False, True])
def test_platform_flag_preserves_valid_native_and_legacy_bytes(
    tmp_path: Path, native: bool,
) -> None:
    tool = _tool()
    report = _native() if native else {
        "scanner": {"name": "legacy", "schemaVersion": "1.0"}, "source": {"note": "metadata"},
    }
    path = _write(tmp_path, report)
    payload = path.read_bytes()
    assert tool.verify_scanner_evidence(
        path, expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_bytes=len(payload), expected_image_id=_IMAGE, require_linux_arm64=True,
    ) == ("grype-0.120.0" if native else "legacy")
    assert path.read_bytes() == payload


def test_legacy_incidental_source_metadata_is_not_misclassified_as_native(tmp_path: Path) -> None:
    tool = _tool()
    report = {
        "scanner": {"name": "legacy", "schemaVersion": "1.0"},
        "source": {"note": "original producer metadata"},
        "matches": [],
    }
    path = _write(tmp_path, report)
    payload = path.read_bytes()
    assert _verify(tool, path) == "legacy"
    assert path.read_bytes() == payload


@pytest.mark.parametrize("payload", [
    b'{"scanner":{"name":"a","name":"b","schemaVersion":"1.0"}}',
    b'{"scanner":{"name":"test","schemaVersion":"1.0"},"x":NaN}',
    b'{"scanner":{"name":"test","schemaVersion":"1.0"},"x":1e999}',
    b'\xff', b'[]', b'{', b'',
])
def test_unsafe_json_rejected(tmp_path: Path, payload: bytes) -> None:
    tool = _tool()
    path = tmp_path / "unsafe.json"
    path.write_bytes(payload)
    with pytest.raises(tool.ScannerEvidenceError):
        _verify(tool, path)


def test_wrong_size_and_oversize_rejected(tmp_path: Path) -> None:
    tool = _tool()
    path = _write(tmp_path, _native())
    with pytest.raises(tool.ScannerEvidenceError):
        tool.verify_scanner_evidence(
            path, expected_sha256="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            expected_bytes=path.stat().st_size + 1, expected_image_id=_IMAGE,
        )
    with path.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    with pytest.raises(tool.ScannerEvidenceError):
        _verify(tool, path)


def test_symlink_parent_leaf_and_nonregular_rejected(tmp_path: Path) -> None:
    tool = _tool()
    path = _write(tmp_path, _native())
    leaf = tmp_path / "link.json"
    leaf.symlink_to(path)
    parent = tmp_path / "linked"
    parent.symlink_to(tmp_path, target_is_directory=True)
    for alias in [leaf, parent / path.name]:
        with pytest.raises(tool.ScannerEvidenceError):
            _verify(tool, alias)
    for special in [tmp_path, tmp_path / "fifo"]:
        if special.name == "fifo":
            os.mkfifo(special)
        with pytest.raises(tool.ScannerEvidenceError):
            tool.verify_scanner_evidence(
                special, expected_sha256="sha256:" + "a" * 64,
                expected_bytes=1, expected_image_id=_IMAGE,
            )


@pytest.mark.parametrize("replace", [False, True])
def test_observed_change_or_replacement_during_read_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replace: bool,
) -> None:
    tool = _tool()
    path = _write(tmp_path, _native())
    payload = path.read_bytes()
    original_read = tool.os.read
    changed = False

    def changing_read(fd: int, length: int) -> bytes:
        nonlocal changed
        data = original_read(fd, length)
        if not changed:
            changed = True
            if replace:
                other = tmp_path / "other.json"
                other.write_bytes(payload)
                other.replace(path)
            else:
                with path.open("ab") as stream:
                    stream.write(b" ")
        return data

    monkeypatch.setattr(tool.os, "read", changing_read)
    with pytest.raises(tool.ScannerEvidenceError):
        tool.verify_scanner_evidence(
            path, expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
            expected_bytes=len(payload), expected_image_id=_IMAGE,
        )


def test_cli_validates_without_exposing_report_or_rewriting(tmp_path: Path) -> None:
    _tool()
    report = _native()
    report["descriptor"]["configuration"] = {"fixtureSecret": "do-not-log-this"}
    path = _write(tmp_path, report)
    payload = path.read_bytes()
    args = [sys.executable, str(_TOOL), "--path", str(path),
            "--sha256", "sha256:" + hashlib.sha256(payload).hexdigest(),
            "--bytes", str(len(payload)), "--image-id", _IMAGE]
    good = subprocess.run(args, capture_output=True, text=True, check=False)
    assert good.returncode == 0, good.stderr
    bad = subprocess.run(
        [*args[:-1], "sha256:" + "b" * 64], capture_output=True, text=True, check=False,
    )
    assert bad.returncode != 0
    assert "do-not-log-this" not in good.stdout + good.stderr + bad.stdout + bad.stderr
    assert path.read_bytes() == payload
