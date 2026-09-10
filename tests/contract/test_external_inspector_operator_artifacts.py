"""Operator artifact admission rejects unsafe nodes before parsing trusted data."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ksi_processing_controller.external_inspector_operator_artifacts import (
    BoundedOperatorArtifact,
    OperatorArtifactUnavailable,
)
from test_external_inspector_host_proof import _close_live_proof_listeners  # noqa: F401


def test_artifact_rechecks_exact_identity_across_consumers(tmp_path: Path) -> None:
    path = tmp_path / "proof.json"
    path.write_bytes(b"sealed")
    path.chmod(0o600)
    artifact = BoundedOperatorArtifact(path, maximum_bytes=64)
    assert artifact.read() == b"sealed"
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"sealed")
    replacement.chmod(0o600)
    replacement.replace(path)
    with pytest.raises(OperatorArtifactUnavailable):
        artifact.read()


@pytest.mark.parametrize(
    "kind", ["symlink", "parent_symlink", "fifo", "directory", "hardlink", "writable", "oversized"]
)
def test_artifact_rejects_unsafe_nodes(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "proof"
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    elif kind == "parent_symlink":
        directory = tmp_path / "real"
        directory.mkdir()
        (directory / "proof").write_bytes(b"ok")
        (directory / "proof").chmod(0o600)
        (tmp_path / "linked").symlink_to(directory, target_is_directory=True)
        path = tmp_path / "linked" / "proof"
    else:
        path.write_bytes(b"x" * (65 if kind == "oversized" else 2))
        path.chmod(0o600)
        if kind == "symlink":
            target = tmp_path / "target"
            path.rename(target)
            path.symlink_to(target)
        elif kind == "hardlink":
            os.link(path, tmp_path / "other")
        elif kind == "writable":
            path.chmod(0o666)
    with pytest.raises(OperatorArtifactUnavailable):
        BoundedOperatorArtifact(path, maximum_bytes=64).read()


def test_artifact_rejects_in_place_change_even_same_size(tmp_path: Path) -> None:
    path = tmp_path / "proof"
    path.write_bytes(b"old")
    path.chmod(0o600)
    artifact = BoundedOperatorArtifact(path, maximum_bytes=64)
    assert artifact.read() == b"old"
    path.write_bytes(b"new")
    with pytest.raises(OperatorArtifactUnavailable):
        artifact.read()


@pytest.mark.parametrize("name", ["manifest.json", "revocations.json", "oci-pairs.json"])
@pytest.mark.parametrize("mutation", ["symlink", "oversized", "replacement"])
def test_real_adapters_preserve_preflight_file_identity(
    tmp_path: Path,
    name: str,
    mutation: str,
) -> None:
    from ksi_processing_controller.external_inspector_operator_config import (
        OperatorConfigUnavailable,
        load_external_inspector_operator_config,
        validate_operator_startup_artifacts,
    )
    from test_external_inspector_host_proof import _proof_fixture, _signed_operator_config

    proof, _ = _proof_fixture(tmp_path / "host")
    config_path = _signed_operator_config(
        tmp_path,
        proof=proof,
        listener_path=tmp_path / "listener.sock",
    )
    for filename in ("manifest.json", "revocations.json", "oci-pairs.json"):
        (tmp_path / filename).chmod(0o600)
    config = load_external_inspector_operator_config(config_path)
    validate_operator_startup_artifacts(config)
    path = tmp_path / name
    raw = path.read_bytes()
    replacement = tmp_path / "replacement"
    replacement.write_bytes(raw)
    replacement.chmod(0o600)
    if mutation == "symlink":
        path.unlink()
        path.symlink_to(replacement)
    elif mutation == "oversized":
        path.write_bytes(b" " * (1024 * 1024 + 1))
    else:
        replacement.replace(path)
    with pytest.raises(OperatorConfigUnavailable):
        validate_operator_startup_artifacts(config)
