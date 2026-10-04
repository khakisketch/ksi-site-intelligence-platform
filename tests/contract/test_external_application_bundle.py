"""Behavioral checks for the bounded offline application bundle; never release evidence."""

from __future__ import annotations

import copy
import csv
import importlib.util
import io
import json
import os
import struct
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from support.external_application_bundle_fixture import (
    ENTRYPOINTS,
    LOCK,
    SOURCE,
    TARGET,
    BundleFixture,
    build_wheel,
    canonical_wheel_name,
    digest,
    make_bundle,
    record_digest,
    sync_file_records,
)

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/external_runtime_application_bundle.py"
SCHEMA = ROOT / "contracts/schemas/external-runtime-application-bundle.v1.json"
LOCK_ID = digest(LOCK)


def _tool() -> Any:
    assert TOOL.is_file(), "reviewed application-bundle tool is not implemented"
    tools_dir = str(TOOL.parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    spec = importlib.util.spec_from_file_location("external_runtime_application_bundle", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _materialize(tmp_path: Path, fixture: BundleFixture) -> tuple[Path, str]:
    root = tmp_path / "bundle"
    root.mkdir()
    for relative, payload in fixture.payloads.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    manifest = json.dumps(fixture.manifest, separators=(",", ":")).encode()
    (root / "manifest.json").write_bytes(manifest)
    return root, digest(manifest)


def _verify(tool: Any, root: Path, manifest_sha256: str, **overrides: Any) -> Any:
    options: dict[str, Any] = {
        "expected_manifest_sha256": manifest_sha256,
        "expected_source_commit": SOURCE,
        "expected_lock_sha256": LOCK_ID,
    }
    options.update(overrides)
    return tool.verify_application_bundle(root, **options)


def test_static_bundle_verification_accepts_three_fixed_entrypoints_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _tool()
    fixture = make_bundle()
    root, manifest_sha = _materialize(tmp_path, fixture)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("static verification attempted to launch a process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = _verify(tool, root, manifest_sha)
    assert result.source_commit == SOURCE
    assert result.lock_sha256 == LOCK_ID
    assert result.target.python_version == "3.12.15"
    assert result.target.platform_tag == TARGET["platformTag"]
    observed = {(point.name, point.module, point.function) for point in result.entrypoints}
    assert observed == {(row["name"], row["module"], row["function"]) for row in ENTRYPOINTS}
    by_path = {row.relative_path: row for row in result.files}
    assert set(by_path) == set(fixture.payloads)
    assert by_path["uv.lock"].sha256 == LOCK_ID
    assert by_path["uv.lock"].kind == "lock"
    assert by_path["requirements.txt"].kind == "requirements"
    after = {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize("override", [
    {"expected_manifest_sha256": "sha256:" + "0" * 64},
    {"expected_source_commit": "b" * 40},
    {"expected_source_commit": ""},
    {"expected_lock_sha256": "sha256:" + "0" * 64},
    {"expected_manifest_sha256": "sha256:" + "A" * 64},
    {"expected_lock_sha256": "not-a-digest"},
])
def test_wrong_expected_binding_blocks(
    tmp_path: Path, override: dict[str, Any],
) -> None:
    tool = _tool()
    fixture = make_bundle()
    root, manifest_sha = _materialize(tmp_path, fixture)
    with pytest.raises(tool.BundleEvidenceError):
        _verify(tool, root, manifest_sha, **override)


def _mutated_fixture(mutation: str) -> BundleFixture:
    fixture = make_bundle()
    manifest = fixture.manifest
    payloads = fixture.payloads
    if mutation == "schema":
        manifest["schemaVersion"] = "external-runtime-application-bundle.v2"
    elif mutation == "unknown_root":
        manifest["extra"] = 1
    elif mutation == "source_field":
        manifest["source"]["gitCommitSha"] = "b" * 40
    elif mutation == "source_missing":
        del manifest["source"]["uvLockBytes"]
    elif mutation == "lock_field":
        manifest["source"]["uvLockSha256"] = "sha256:" + "0" * 64
    elif mutation == "target_python":
        manifest["target"]["pythonVersion"] = "3.12.14"
    elif mutation == "target_extra":
        manifest["target"]["variant"] = "v8"
    elif mutation == "toolchain_version":
        manifest["buildToolchain"]["uvVersion"] = "0.11.14"
    elif mutation == "toolchain_hash":
        manifest["buildToolchain"]["uvSha256"] = "sha256:" + "Z" * 64
    elif mutation == "entrypoints_short":
        manifest["entrypoints"] = manifest["entrypoints"][:2]
    elif mutation == "entrypoints_swap":
        manifest["entrypoints"][0]["module"] = "ksi_processing_controller.other_module"
    elif mutation == "entrypoints_function":
        manifest["entrypoints"][0]["function"] = "start"
    elif mutation == "files_missing":
        manifest["files"] = manifest["files"][1:]
    elif mutation == "files_extra":
        manifest["files"].append(
            {"relativePath": "notes.txt", "sha256": "sha256:" + "5" * 64, "bytes": 1,
             "kind": "external-wheel"}
        )
    elif mutation == "files_hash":
        manifest["files"][0]["sha256"] = "sha256:" + "0" * 64
    elif mutation == "files_bool":
        manifest["files"][0]["bytes"] = True
    elif mutation == "files_float":
        manifest["files"][0]["bytes"] = 1.5
    elif mutation == "files_kind":
        manifest["files"][0]["kind"] = "other"
    elif mutation == "files_path_absolute":
        manifest["files"][0]["relativePath"] = "/etc/passwd"
    elif mutation == "files_path_traversal":
        manifest["files"][0]["relativePath"] = "../outside.bin"
    elif mutation == "distribution_version":
        manifest["distributions"][0]["version"] = "9.9.9"
    elif mutation == "distribution_name":
        manifest["distributions"][0]["name"] = "other-package"
    elif mutation == "distribution_tags":
        manifest["distributions"][0]["platformTag"] = "linux_armv7l"
    elif mutation == "distribution_duplicate":
        manifest["distributions"].append(dict(manifest["distributions"][1]))
    elif mutation == "distribution_kind":
        manifest["distributions"][2]["kind"] = "workspace"
    elif mutation == "distribution_missing":
        manifest["distributions"] = manifest["distributions"][1:]
    elif mutation == "requirements_missing":
        del payloads["requirements.txt"]
        sync_file_records(manifest, payloads)
    elif mutation == "wheel_missing":
        del payloads[manifest["distributions"][0]["wheel"]]
        sync_file_records(manifest, payloads)
    elif mutation == "unknown_extra_file":
        payloads["notes.txt"] = b"not part of the bundle contract"
        sync_file_records(manifest, payloads)
    elif mutation == "wheel_extra":
        name = "wheels/extra-1.0-py3-none-any.whl"
        payloads[name] = build_wheel("extra", "1.0")
        sync_file_records(manifest, payloads)
    else:
        raise AssertionError(f"unknown mutation {mutation}")
    return fixture


@pytest.mark.parametrize("mutation", [
    "schema", "unknown_root", "source_field", "source_missing", "lock_field",
    "target_python", "target_extra", "toolchain_version", "toolchain_hash",
    "entrypoints_short", "entrypoints_swap", "entrypoints_function",
    "files_missing", "files_extra", "files_hash", "files_bool", "files_float",
    "files_kind", "files_path_absolute", "files_path_traversal",
    "distribution_version", "distribution_name", "distribution_tags",
    "distribution_duplicate", "distribution_kind", "distribution_missing",
    "requirements_missing", "wheel_missing", "unknown_extra_file", "wheel_extra",
])
def test_manifest_mutations_block(tmp_path: Path, mutation: str) -> None:
    tool = _tool()
    fixture = _mutated_fixture(mutation)
    root, manifest_sha = _materialize(tmp_path, fixture)
    with pytest.raises(tool.BundleEvidenceError):
        _verify(tool, root, manifest_sha)


@pytest.mark.parametrize("kwargs", [
    {"metadata_name": "other-package"},
    {"metadata_version": "9.9.9"},
    {"record_mode": "omit"},
    {"record_mode": "bad-hash"},
    {"record_mode": "bad-size"},
    {"record_mode": "unknown-row"},
    {"record_mode": "traversal-row"},
    {"symlink_entry": "ksi_domain/link.py"},
    {"duplicate_entry": "ksi_domain/__init__.py"},
])
def test_dependency_wheel_payload_mutations_block(
    tmp_path: Path, kwargs: dict[str, Any],
) -> None:
    tool = _tool()
    name = canonical_wheel_name("ksi-domain", "0.0.1", ("py3", "none", "any"))
    bad = build_wheel("ksi-domain", "0.0.1", **kwargs)
    fixture = make_bundle(wheel_overrides={name: bad})
    root, manifest_sha = _materialize(tmp_path, fixture)
    with pytest.raises(tool.BundleEvidenceError):
        _verify(tool, root, manifest_sha)


@pytest.mark.parametrize("entry_points", [
    (("ksi-external-inspector-daemon",
      "ksi_processing_controller.external_inspector_daemon", "main"),),
    (("ksi-external-validation-worker",
      "ksi_processing_controller.external_validation_worker", "start"),),
])
def test_controller_wheel_must_carry_exact_fixed_mappings(
    tmp_path: Path, entry_points: tuple[tuple[str, str, str], ...],
) -> None:
    tool = _tool()
    name = canonical_wheel_name("ksi-processing-controller", "0.0.1", ("py3", "none", "any"))
    bad = build_wheel("ksi-processing-controller", "0.0.1", entry_points=entry_points)
    fixture = make_bundle(wheel_overrides={name: bad})
    root, manifest_sha = _materialize(tmp_path, fixture)
    with pytest.raises(tool.BundleEvidenceError):
        _verify(tool, root, manifest_sha)


def test_not_a_zip_wheel_blocks(tmp_path: Path) -> None:
    tool = _tool()
    name = canonical_wheel_name(
        "demo-native", "1.2.3", ("cp312", "cp312", "manylinux_2_39_aarch64"),
    )
    fixture = make_bundle(wheel_overrides={name: b"this is not a zip archive"})
    root, manifest_sha = _materialize(tmp_path, fixture)
    with pytest.raises(tool.BundleEvidenceError):
        _verify(tool, root, manifest_sha)


@pytest.mark.parametrize("constant,value", [
    ("_MAX_BUNDLE_BYTES", 8),
    ("_MAX_WHEELS", 1),
    ("_MAX_WHEEL_BYTES", 8),
    ("_MAX_JSON_BYTES", 1),
    ("_MAX_METADATA_BYTES", 1),
    ("_MAX_ZIP_CENTRAL_BYTES", 8),
    ("_MAX_ZIP_ENTRIES", 2),
    ("_MAX_ZIP_TOTAL_ENTRIES", 4),
    ("_MAX_EXPANDED_BYTES", 8),
])
def test_resource_budgets_block_before_unbounded_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, constant: str, value: int,
) -> None:
    tool = _tool()
    fixture = make_bundle()
    root, manifest_sha = _materialize(tmp_path, fixture)
    monkeypatch.setattr(tool, constant, value)
    with pytest.raises(tool.BundleEvidenceError):
        _verify(tool, root, manifest_sha)


def test_unlisted_or_special_root_entries_block(tmp_path: Path) -> None:
    tool = _tool()
    fixture = make_bundle()
    root, manifest_sha = _materialize(tmp_path, fixture)
    (root / "unlisted.txt").write_bytes(b"extra")
    with pytest.raises(tool.BundleEvidenceError):
        _verify(tool, root, manifest_sha)


def test_directory_inside_wheels_blocks(tmp_path: Path) -> None:
    tool = _tool()
    fixture = make_bundle()
    root, manifest_sha = _materialize(tmp_path, fixture)
    (root / "wheels" / "nested").mkdir()
    with pytest.raises(tool.BundleEvidenceError):
        _verify(tool, root, manifest_sha)


@pytest.mark.parametrize(
    "kind", ["manifest_symlink", "manifest_fifo", "manifest_directory", "wheels_symlink"],
)
def test_special_or_symlinked_bundle_inputs_block(tmp_path: Path, kind: str) -> None:
    tool = _tool()
    fixture = make_bundle()
    root, manifest_sha = _materialize(tmp_path, fixture)
    if kind == "manifest_symlink":
        (root / "manifest.json").unlink()
        (root / "manifest.json").symlink_to(root / "uv.lock")
    elif kind == "manifest_fifo":
        (root / "manifest.json").unlink()
        os.mkfifo(root / "manifest.json")
    elif kind == "manifest_directory":
        (root / "manifest.json").unlink()
        (root / "manifest.json").mkdir()
    else:
        target = tmp_path / "elsewhere"
        (root / "wheels").rename(target)
        (root / "wheels").symlink_to(target, target_is_directory=True)
    with pytest.raises(tool.BundleEvidenceError):
        _verify(tool, root, manifest_sha)


@pytest.mark.parametrize("change", ["truncate", "grow", "replace"])
def test_bundle_change_observed_during_read_blocks(
    tmp_path: Path, change: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _tool()
    fixture = make_bundle()
    root, manifest_sha = _materialize(tmp_path, fixture)
    payload = (root / "uv.lock").read_bytes()
    read = os.read
    altered = False

    def changing_read(fd: int, size: int) -> bytes:
        nonlocal altered
        data = read(fd, size)
        if not altered:
            altered = True
            if change == "replace":
                replacement = tmp_path / "replacement.lock"
                replacement.write_bytes(payload)
                replacement.replace(root / "uv.lock")
            else:
                (root / "uv.lock").write_bytes(
                    payload[: max(1, len(payload) - 3)] if change == "truncate" else payload + b"\0"
                )
        return data

    monkeypatch.setattr(tool.os, "read", changing_read)
    with pytest.raises(tool.BundleEvidenceError):
        _verify(tool, root, manifest_sha)


def test_cli_emits_only_safe_status_or_blocker(tmp_path: Path) -> None:
    _tool()
    fixture = make_bundle()
    root, manifest_sha = _materialize(tmp_path, fixture)
    args = [
        sys.executable, str(TOOL), "--bundle", str(root), "--manifest-sha256", manifest_sha,
        "--source-commit", SOURCE, "--lock-sha256", LOCK_ID,
    ]
    good = subprocess.run(args, text=True, capture_output=True, check=False)
    assert good.returncode == 0, good.stderr
    data = json.loads(good.stdout)
    assert data["status"] == "BUNDLE_BYTES_VERIFIED"
    assert data["sourceCommit"] == SOURCE
    assert str(root) not in good.stderr
    args[-1] = "sha256:" + "0" * 64
    bad = subprocess.run(args, text=True, capture_output=True, check=False)
    assert bad.returncode == 1 and bad.stdout == ""
    assert "APPLICATION_BUNDLE_BLOCKED:" in bad.stderr
    assert str(root) not in bad.stderr


def test_bundle_schema_matches_verifier_fixture() -> None:
    assert SCHEMA.is_file(), "v1 bundle schema is not implemented"
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    fixture = make_bundle()
    assert list(validator.iter_errors(fixture.manifest)) == []
    bad = copy.deepcopy(fixture.manifest)
    bad["files"][0]["bytes"] = True
    assert list(validator.iter_errors(bad))
    bad = copy.deepcopy(fixture.manifest)
    bad["entrypoints"] = bad["entrypoints"][:2]
    assert list(validator.iter_errors(bad))
    bad = copy.deepcopy(fixture.manifest)
    bad["target"]["pythonVersion"] = "3.12.14"
    assert list(validator.iter_errors(bad))


def test_bundle_schema_kind_enum_is_exact() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    kind = schema["properties"]["files"]["items"]["properties"]["kind"]
    assert kind["enum"] == ["lock", "requirements", "workspace-wheel", "external-wheel"]


def test_cumulative_read_budget_blocks_before_unbounded_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _tool()
    fixture = make_bundle()
    root, manifest_sha = _materialize(tmp_path, fixture)
    manifest_len = (root / "manifest.json").stat().st_size
    # Declared manifest sizes stay small while the actual lock bytes are larger.
    with open(root / "uv.lock", "ab") as handle:
        handle.write(b"# synthetic padding beyond the declared manifest size\n" * 64)
    monkeypatch.setattr(tool, "_MAX_TOTAL_READ_BYTES", manifest_len + 8, raising=False)
    with pytest.raises(tool.BundleEvidenceError) as excinfo:
        _verify(tool, root, manifest_sha)
    assert excinfo.value.code == "READ_TOTAL"


def _patch_central_uncompressed_size(wheel: bytes, filename: str, lied: int) -> bytes:
    """Rewrite one central-directory uncompressed-size field; data untouched."""
    data = bytearray(wheel)
    cursor = 0
    while True:
        index = data.find(b"PK\x01\x02", cursor)
        assert index >= 0, "central-directory entry is not implemented"
        name_len = struct.unpack_from("<H", data, index + 28)[0]
        extra_len = struct.unpack_from("<H", data, index + 30)[0]
        comment_len = struct.unpack_from("<H", data, index + 32)[0]
        name = bytes(data[index + 46 : index + 46 + name_len]).decode("utf-8")
        if name == filename:
            struct.pack_into("<I", data, index + 24, lied)
            return bytes(data)
        cursor = index + 46 + name_len + extra_len + comment_len


def test_metadata_decompression_does_not_trust_header_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _tool()
    domain_tags = ("py3", "none", "any")
    native_tags = ("cp312", "cp312", "manylinux_2_39_aarch64")
    name = canonical_wheel_name("ksi-domain", "0.0.1", domain_tags)
    mappings = tuple((row["name"], row["module"], row["function"]) for row in ENTRYPOINTS)
    honest = {
        canonical_wheel_name("ksi-processing-controller", "0.0.1", domain_tags):
            build_wheel("ksi-processing-controller", "0.0.1", entry_points=mappings),
        name: build_wheel("ksi-domain", "0.0.1"),
        canonical_wheel_name("demo-native", "1.2.3", native_tags):
            build_wheel("demo-native", "1.2.3", tags=native_tags, root_is_purelib=False),
    }
    padded = _pad_metadata_entry(
        honest[name], "ksi_domain-0.0.1.dist-info/METADATA", pad_lines=64,
    )
    with zipfile.ZipFile(io.BytesIO(padded)) as archive:
        actual = len(archive.read("ksi_domain-0.0.1.dist-info/METADATA"))
    others = dict(honest)
    others[name] = padded
    cap = 0
    for wheel in others.values():
        with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
            for info in archive.infolist():
                if wheel is padded and info.filename.endswith("/METADATA"):
                    continue
                cap = max(cap, info.file_size)
    assert actual > cap >= 8
    patched = _patch_central_uncompressed_size(
        padded, "ksi_domain-0.0.1.dist-info/METADATA", 8,
    )
    monkeypatch.setattr(tool, "_MAX_METADATA_BYTES", cap)
    fixture = make_bundle(wheel_overrides={name: patched})
    root, manifest_sha = _materialize(tmp_path, fixture)
    with pytest.raises(tool.BundleEvidenceError) as excinfo:
        _verify(tool, root, manifest_sha)
    assert excinfo.value.code == "METADATA_SIZE"


def _pad_metadata_entry(wheel: bytes, filename: str, pad_lines: int) -> bytes:
    """Append ignored header lines so actual bytes exceed every honest entry."""
    with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
        saved = [(info, archive.read(info.filename)) for info in archive.infolist()]
    payloads = {info.filename: payload for info, payload in saved}
    text = payloads[filename].decode("utf-8")
    text += "".join(f"X-Synthetic-Pad-{index}: {'p' * 32}\n" for index in range(pad_lines))
    payloads[filename] = text.encode("utf-8")
    record_name = next(name for name in payloads if name.endswith("/RECORD"))
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(
        [
            (path, record_digest(payloads[path]), str(len(payloads[path])))
            for path in sorted(payloads)
            if path != record_name
        ]
        + [(record_name, "", "")]
    )
    payloads[record_name] = buffer.getvalue().encode("utf-8")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for info, _payload in saved:
            node = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            node.create_system = info.create_system
            node.external_attr = info.external_attr
            node.compress_type = info.compress_type
            archive.writestr(node, payloads[info.filename])
    return stream.getvalue()


def test_zero_length_wheel_entry_passes_with_exact_record_binding(
    tmp_path: Path,
) -> None:
    tool = _tool()
    name = canonical_wheel_name("ksi-domain", "0.0.1", ("py3", "none", "any"))
    wheel = build_wheel("ksi-domain", "0.0.1", extra_entries={"ksi_domain/py.typed": b""})
    fixture = make_bundle(wheel_overrides={name: wheel})
    root, manifest_sha = _materialize(tmp_path, fixture)
    result = _verify(tool, root, manifest_sha)
    assert result.source_commit == SOURCE


def _rewrite_record_row(
    wheel: bytes, target: str, *, new_hash: str | None, new_size: str | None,
) -> bytes:
    with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
        saved = [(info, archive.read(info.filename)) for info in archive.infolist()]
    rebuilt: list[tuple[zipfile.ZipInfo, bytes]] = []
    for info, payload in saved:
        if info.filename.endswith("/RECORD"):
            rows = list(csv.reader(io.StringIO(payload.decode("utf-8"))))
            patched_rows = [
                (new_hash or row_hash, new_size or row_size)
                if row_path == target else (row_hash, row_size)
                for row_path, row_hash, row_size in (row[:3] for row in rows)
            ]
            buffer = io.StringIO()
            csv.writer(buffer, lineterminator="\n").writerows(
                [(row_path, row_hash, row_size) for row_path, (row_hash, row_size) in
                 zip([row[0] for row in rows], patched_rows, strict=True)]
            )
            payload = buffer.getvalue().encode("utf-8")
        rebuilt.append((info, payload))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for info, payload in rebuilt:
            node = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            node.create_system = info.create_system
            node.external_attr = info.external_attr
            node.compress_type = info.compress_type
            archive.writestr(node, payload)
    return stream.getvalue()


@pytest.mark.parametrize("field", ["hash", "size"])
def test_zero_length_wheel_entry_record_mismatch_blocks(
    tmp_path: Path, field: str,
) -> None:
    tool = _tool()
    name = canonical_wheel_name("ksi-domain", "0.0.1", ("py3", "none", "any"))
    wheel = build_wheel("ksi-domain", "0.0.1", extra_entries={"ksi_domain/py.typed": b""})
    if field == "hash":
        wheel = _rewrite_record_row(
            wheel, "ksi_domain/py.typed", new_hash="sha256=" + "A" * 43, new_size=None,
        )
    else:
        wheel = _rewrite_record_row(
            wheel, "ksi_domain/py.typed", new_hash=None, new_size="1",
        )
    fixture = make_bundle(wheel_overrides={name: wheel})
    root, manifest_sha = _materialize(tmp_path, fixture)
    with pytest.raises(tool.BundleEvidenceError) as excinfo:
        _verify(tool, root, manifest_sha)
    assert excinfo.value.code == ("RECORD_HASH" if field == "hash" else "RECORD_SIZE")
