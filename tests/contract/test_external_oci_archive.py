"""Behavioral OCI link checks against synthetic archives, never release acceptance."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest
from support.external_oci_archive_fixture import (
    CONFIG,
    INDEX,
    OciFixture,
    digest,
    make_oci_fixture,
    tar_payload,
)

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/verify_external_oci_archive.py"
SOURCE = "a" * 40


def _tool() -> Any:
    assert TOOL.is_file(), "reviewed OCI verifier is not implemented"
    spec = importlib.util.spec_from_file_location("oci_link_tool", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verify(tool: Any, path: Path, fixture: OciFixture, **overrides: Any) -> str:
    options = {
        "expected_sha256": digest(path.read_bytes()), "expected_bytes": path.stat().st_size,
        "expected_index_id": fixture.index_id, "expected_source_commit": SOURCE,
        "role": "inspector",
    }
    options.update(overrides)
    return tool.verify_oci_archive(path, **options)


@pytest.mark.parametrize("role", ["inspector", "measurement"])
def test_actual_index_to_config_link_is_derived_not_declared(tmp_path: Path, role: str) -> None:
    tool = _tool()
    fixture = make_oci_fixture(role, SOURCE)
    path = tmp_path / "image.tar"
    path.write_bytes(fixture.payload)
    assert fixture.index_id != fixture.config_id
    assert _verify(tool, path, fixture, role=role) == fixture.config_id
    assert path.read_bytes() == fixture.payload


@pytest.mark.parametrize("override", [
    {"expected_sha256": "sha256:" + "0" * 64}, {"expected_bytes": 1},
    {"expected_bytes": True}, {"expected_bytes": 1073741825},
    {"expected_index_id": "sha256:" + "0" * 64}, {"expected_index_id": "sha256:" + "A" * 64},
    {"expected_source_commit": "b" * 40}, {"expected_source_commit": ""},
    {"role": "measurement"}, {"role": "core"},
])
def test_wrong_expected_binding_blocks(tmp_path: Path, override: dict[str, Any]) -> None:
    tool = _tool()
    fixture = make_oci_fixture("inspector", SOURCE)
    path = tmp_path / "image.tar"
    path.write_bytes(fixture.payload)
    with pytest.raises(tool.OciArchiveEvidenceError):
        _verify(tool, path, fixture, **override)


@pytest.mark.parametrize("mutation", [
    "source", "user", "cmd", "entrypoint", "os", "architecture", "diffids", "rootfs",
    "variant", "no_platform", "two_runtimes", "foreign_url", "size", "bool_size", "missing",
    "unknown_media", "conflicting_shared", "too_many_layers", "layout", "schema", "two_roots",
    "duplicate_json", "nonfinite", "deep_json", "oversize_json", "shared_valid", "variant_v8",
])
def test_graph_proves_exact_runtime_metadata(tmp_path: Path, mutation: str) -> None:
    def mutate(stage: str, value: dict[str, Any]) -> bytes | None:
        if stage == "config":
            config = value["config"]
            if mutation == "source":
                config["Labels"]["org.opencontainers.image.revision"] = "b" * 40
            if mutation == "user":
                config["User"] = "root"
            if mutation == "cmd":
                config["Cmd"] = ["/bin/sh"]
            if mutation == "entrypoint":
                config["Entrypoint"] = ["/bin/sh", "-c"]
            if mutation in {"os", "architecture"}:
                value[mutation] = "different"
            if mutation == "diffids":
                value["rootfs"]["diff_ids"] = []
            if mutation == "rootfs":
                value["rootfs"]["type"] = "invalid"
            if mutation == "duplicate_json":
                return b'{"os":"linux","os":"other"}'
            if mutation == "nonfinite":
                value["invalid"] = float("inf")
            if mutation == "deep_json":
                return b'{"x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}'
            if mutation == "oversize_json":
                value["oversize"] = "x" * 1048576
        if stage == "manifest":
            layer = value["layers"][0]
            if mutation == "foreign_url":
                layer["urls"] = ["https://fixture.invalid/not-accessed"]
            if mutation == "size":
                layer["size"] += 1
            if mutation == "bool_size":
                layer["size"] = True
            if mutation == "missing":
                layer["digest"] = "sha256:" + "0" * 64
            if mutation == "unknown_media":
                layer["mediaType"] = "application/unreviewed"
            if mutation == "conflicting_shared":
                value["layers"].append({**layer, "mediaType": CONFIG})
            if mutation == "too_many_layers":
                value["layers"] *= 65
            if mutation == "shared_valid":
                value["layers"].append(dict(layer))
        if stage == "config" and mutation == "shared_valid":
            value["rootfs"]["diff_ids"] *= 2
        if stage == "nested_index":
            runtime = value["manifests"][0]
            if mutation in {"variant", "variant_v8"}:
                runtime["platform"]["variant"] = "v8" if mutation == "variant_v8" else "v7"
            if mutation == "no_platform":
                del runtime["platform"]
            if mutation == "two_runtimes":
                value["manifests"].append(dict(runtime))
        if stage == "layout" and mutation == "layout":
            value["imageLayoutVersion"] = "2.0.0"
        if stage == "index":
            if mutation == "schema":
                value["schemaVersion"] = True
            if mutation == "two_roots":
                value["manifests"] *= 2
        return None

    tool = _tool()
    fixture = make_oci_fixture("inspector", SOURCE, mutate=mutate)
    path = tmp_path / "image.tar"
    path.write_bytes(fixture.payload)
    if mutation in {"shared_valid", "variant_v8"}:
        assert _verify(tool, path, fixture) == fixture.config_id
    else:
        with pytest.raises(tool.OciArchiveEvidenceError):
            _verify(tool, path, fixture)


@pytest.mark.parametrize("change", ["selected", "attestation", "extra", "extra_valid"])
def test_all_archived_blobs_are_verified_not_only_selected(tmp_path: Path, change: str) -> None:
    tool = _tool()
    fixture = make_oci_fixture("inspector", SOURCE)
    members = list(fixture.members)
    if change in {"selected", "attestation"}:
        index = 0 if change == "selected" else 4
        name, payload = members[index]
        members[index] = (name, payload + b"corrupted")
    else:
        members.append(("blobs/sha256/" + digest(b"extra")[7:],
                        b"extra" if change == "extra_valid" else b"wrong"))
    path = tmp_path / "image.tar"
    path.write_bytes(tar_payload(members))
    if change == "extra_valid":
        assert _verify(tool, path, fixture) == fixture.config_id
    else:
        with pytest.raises(tool.OciArchiveEvidenceError):
            _verify(tool, path, fixture)


@pytest.mark.parametrize("typeflag", [b"x", b"g", b"L", b"K", b"S", b"1", b"2", b"3", b"6"])
def test_tar_headers_reject_before_extension_payload_read(
    tmp_path: Path, typeflag: bytes, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _tool()
    fixture = make_oci_fixture("inspector", SOURCE)
    node = tarfile.TarInfo("index.json")
    node.type = typeflag
    node.size = 2**32
    path = tmp_path / "bad.tar"
    path.write_bytes(node.tobuf(format=tarfile.USTAR_FORMAT) + b"\0" * 1024)
    read = os.read

    def bounded_read(fd: int, size: int) -> bytes:
        assert size <= 1048576, "TAR advertised size reached allocation/read"
        return read(fd, size)

    monkeypatch.setattr(tool.os, "read", bounded_read)
    with pytest.raises(tool.OciArchiveEvidenceError):
        _verify(tool, path, fixture)


@pytest.mark.parametrize("change", [
    "duplicate", "traversal", "absolute", "unknown", "checksum", "oversize_member",
    "directory_payload", "truncate", "single_end", "garbage", "member_limit",
])
def test_malformed_tar_structure_blocks(tmp_path: Path, change: str) -> None:
    tool = _tool()
    fixture = make_oci_fixture("inspector", SOURCE)
    members = list(fixture.members)
    payload = fixture.payload
    if change in {"duplicate", "traversal", "absolute", "unknown", "member_limit"}:
        if change == "member_limit":
            members.extend(("blobs/sha256/" + digest(str(i).encode())[7:], str(i).encode())
                           for i in range(4097))
        else:
            name = {"duplicate": members[0][0], "traversal": "blobs/../index.json",
                    "absolute": "/index.json", "unknown": "unexpected.json"}[change]
            members.append((name, b"unexpected"))
        payload = tar_payload(members)
    if change == "checksum":
        payload = b"X" + payload[1:]
    if change in {"oversize_member", "directory_payload"}:
        node = tarfile.TarInfo("index.json")
        node.size = 2**32 if change == "oversize_member" else 1
        if change == "directory_payload":
            node.type = tarfile.DIRTYPE
        payload = node.tobuf(format=tarfile.USTAR_FORMAT) + b"\0" * 1024
    if change == "truncate":
        payload = payload[:600]
    if change == "single_end":
        payload = payload.rstrip(b"\0") + b"\0" * 512
    if change == "garbage":
        payload += b"not-padding"
    path = tmp_path / "bad.tar"
    path.write_bytes(payload)
    with pytest.raises(tool.OciArchiveEvidenceError):
        _verify(tool, path, fixture)


def test_graph_depth_and_descriptor_limits(tmp_path: Path) -> None:
    tool = _tool()
    fixture = make_oci_fixture("inspector", SOURCE)
    for limit in ["depth", "descriptors"]:
        members = dict(fixture.members)
        value = json.loads(members["blobs/sha256/" + fixture.index_id[7:]])
        descriptor = dict(value["manifests"][1])
        if limit == "depth":
            for _ in range(9):
                raw = json.dumps({"schemaVersion": 2, "mediaType": INDEX,
                                  "manifests": [descriptor]}).encode()
                sha = digest(raw)
                members["blobs/sha256/" + sha[7:]] = raw
                descriptor = {"mediaType": INDEX, "digest": sha, "size": len(raw)}
            value["manifests"].append(descriptor)
        else:
            value["manifests"] += [descriptor] * 64
        raw = json.dumps(value).encode()
        sha = digest(raw)
        members["blobs/sha256/" + sha[7:]] = raw
        members["index.json"] = json.dumps({"schemaVersion": 2, "mediaType": INDEX,
                                            "manifests": [{"mediaType": INDEX, "digest": sha,
                                                           "size": len(raw)}]}).encode()
        path = tmp_path / (limit + ".tar")
        path.write_bytes(tar_payload(list(members.items())))
        with pytest.raises(tool.OciArchiveEvidenceError):
            _verify(tool, path, fixture, expected_index_id=sha)


def _shared_index_graph(
    fixture: OciFixture, *, wrappers: int, fanout: int,
) -> tuple[bytes, str, set[str]]:
    """A shallow-first DAG; cached descendants still count on the later deep path."""
    members = dict(fixture.members)
    index = json.loads(members["blobs/sha256/" + fixture.index_id[7:]])
    descriptor = dict(index["manifests"][1])
    shared_names = {"blobs/sha256/" + descriptor["digest"][7:]}
    for _ in range(wrappers):
        raw = json.dumps({"schemaVersion": 2, "mediaType": INDEX,
                          "manifests": [descriptor] * fanout}).encode()
        sha = digest(raw)
        name = "blobs/sha256/" + sha[7:]
        members[name] = raw
        shared_names.add(name)
        descriptor = {"mediaType": INDEX, "digest": sha, "size": len(raw)}
    index["manifests"].append(descriptor)
    raw = json.dumps(index).encode()
    sha = digest(raw)
    members["blobs/sha256/" + sha[7:]] = raw
    members["index.json"] = json.dumps({"schemaVersion": 2, "mediaType": INDEX,
                                        "manifests": [{"mediaType": INDEX, "digest": sha,
                                                       "size": len(raw)}]}).encode()
    return tar_payload(list(members.items())), sha, shared_names


@pytest.mark.parametrize("wrappers", [5, 6])
def test_shared_cached_subgraph_cannot_hide_longest_path_depth(
    tmp_path: Path, wrappers: int,
) -> None:
    # Root1 + wrappers + attestation manifest1 + config/layer1 = depth8 or9.
    tool = _tool()
    fixture = make_oci_fixture("inspector", SOURCE)
    payload, index_id, _ = _shared_index_graph(fixture, wrappers=wrappers, fanout=2)
    path = tmp_path / "shared.tar"
    path.write_bytes(payload)
    if wrappers == 5:
        assert _verify(tool, path, fixture, expected_index_id=index_id) == fixture.config_id
    else:
        with pytest.raises(tool.OciArchiveEvidenceError) as caught:
            _verify(tool, path, fixture, expected_index_id=index_id)
        assert caught.value.code == "OCI_DEPTH"


def test_shared_fanout_reuses_verified_subgraphs_without_exponential_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _tool()
    fixture = make_oci_fixture("inspector", SOURCE)
    payload, index_id, shared_names = _shared_index_graph(fixture, wrappers=5, fanout=64)
    path = tmp_path / "shared.tar"
    path.write_bytes(payload)
    reads: set[str] = set()
    original = tool._Archive._json

    def guarded_json(archive: Any, name: str) -> dict[str, Any]:
        if name in shared_names:
            assert name not in reads, "shared graph was parsed again for another incoming path"
            reads.add(name)
        return original(archive, name)

    monkeypatch.setattr(tool._Archive, "_json", guarded_json)
    assert _verify(tool, path, fixture, expected_index_id=index_id) == fixture.config_id
    assert reads == shared_names


@pytest.mark.parametrize("budget", [8, 7])
def test_whole_graph_descriptor_budget_blocks_before_unbounded_work(
    tmp_path: Path, budget: int, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Original tiny graph: root descriptor2, runtime/config/layer3, attestation/config/layer3.
    tool = _tool()
    fixture = make_oci_fixture("inspector", SOURCE)
    path = tmp_path / "budget.tar"
    path.write_bytes(fixture.payload)
    monkeypatch.setattr(tool, "_MAX_GRAPH_DESCRIPTORS", budget, raising=False)
    if budget == 8:
        assert _verify(tool, path, fixture) == fixture.config_id
    else:
        with pytest.raises(tool.OciArchiveEvidenceError) as caught:
            _verify(tool, path, fixture)
        assert caught.value.code == "OCI_WORK_LIMIT"


@pytest.mark.parametrize("kind", ["leaf_symlink", "parent_symlink", "directory", "fifo"])
def test_special_or_symlinked_archive_blocks(tmp_path: Path, kind: str) -> None:
    tool = _tool()
    fixture = make_oci_fixture("inspector", SOURCE)
    target = tmp_path / "real.tar"
    target.write_bytes(fixture.payload)
    path = tmp_path / "unsafe"
    if kind == "leaf_symlink":
        path.symlink_to(target)
    elif kind == "parent_symlink":
        path.symlink_to(tmp_path, target_is_directory=True)
        path = path / "real.tar"
    elif kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    with pytest.raises(tool.OciArchiveEvidenceError):
        tool.verify_oci_archive(path, expected_sha256=digest(fixture.payload),
                                expected_bytes=len(fixture.payload),
                                expected_index_id=fixture.index_id,
                                expected_source_commit=SOURCE, role="inspector")


@pytest.mark.parametrize("change", ["replace", "truncate", "grow"])
def test_archive_change_observed_during_read_blocks(
    tmp_path: Path, change: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _tool()
    fixture = make_oci_fixture("inspector", SOURCE)
    path = tmp_path / "image.tar"
    path.write_bytes(fixture.payload)
    read = os.read
    altered = False

    def changing_read(fd: int, size: int) -> bytes:
        nonlocal altered
        data = read(fd, size)
        if not altered:
            altered = True
            if change == "replace":
                replacement = tmp_path / "replacement.tar"
                replacement.write_bytes(fixture.payload)
                replacement.replace(path)
            else:
                path.write_bytes(fixture.payload[:512] if change == "truncate"
                                 else fixture.payload + b"\0" * 512)
        return data

    monkeypatch.setattr(tool.os, "read", changing_read)
    with pytest.raises(tool.OciArchiveEvidenceError):
        _verify(tool, path, fixture)


def test_cli_output_is_only_config_digest_or_safe_blocker(tmp_path: Path) -> None:
    _tool()
    fixture = make_oci_fixture("inspector", SOURCE)
    path = tmp_path / "private-image.tar"
    path.write_bytes(fixture.payload)
    args = [sys.executable, str(TOOL), "--path", str(path), "--sha256", digest(fixture.payload),
            "--bytes", str(len(fixture.payload)), "--index-id", fixture.index_id,
            "--source-commit", SOURCE, "--role", "inspector"]
    good = subprocess.run(args, text=True, capture_output=True, check=False)
    assert good.returncode == 0 and good.stdout == fixture.config_id + "\n" and good.stderr == ""
    args[-1] = "measurement"
    bad = subprocess.run(args, text=True, capture_output=True, check=False)
    assert bad.returncode == 1 and bad.stdout == ""
    assert "OCI_ARCHIVE_BLOCKED:" in bad.stderr and str(path) not in bad.stderr
