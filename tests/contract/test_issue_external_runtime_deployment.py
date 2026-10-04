"""Contract: the Step-3a issuance tool emits validator-accepted deployment sets.

The tool (``tools/issue_external_runtime_deployment.py``) builds a synthetic
inspector + measurement deployment into an output directory.  This module
proves the produced artifacts are ACCEPTED by the real loaders/validators
used at daemon startup -- unmodified -- and that mutated
signature/revocation/pair material is rejected with the same blocked codes a
real operator would observe.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "tools" / "issue_external_runtime_deployment.py"


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _synthetic_args(out: Path) -> list[str]:
    launcher_uid = os.geteuid()
    launcher_gid = os.getegid()
    worker_uid = launcher_uid + 10_000
    assert worker_uid != launcher_uid
    return [
        "--out",
        os.fspath(out),
        "--launcher-uid",
        str(launcher_uid),
        "--launcher-gid",
        str(launcher_gid),
        "--worker-uid",
        str(worker_uid),
        "--docker-socket-path",
        os.fspath(out / "docker.sock"),
        "--systemd-bus-socket-path",
        os.fspath(out / "bus.sock"),
        "--daemon-pid-path",
        os.fspath(out / "docker.pid"),
        "--daemon-uid-map-sha256",
        "sha256:" + "a" * 64,
        "--daemon-gid-map-sha256",
        "sha256:" + "b" * 64,
        "--daemon-cgroup-path",
        "/synthetic.slice/daemon.scope",
        "--inspector-launcher-cgroup-path",
        "/synthetic.slice/ksi-inspector.slice/ksi-external-inspector.service",
        "--measurement-launcher-cgroup-path",
        "/synthetic.slice/ksi-measurement.slice/ksi-external-measurement.service",
        "--inspector-listener-socket-path",
        os.fspath(out / "inspection.sock"),
        "--measurement-listener-socket-path",
        os.fspath(out / "measurement.sock"),
        "--inspector-oci-manifest-digest",
        "sha256:" + "c" * 64,
        "--inspector-oci-config-digest",
        "sha256:" + "d" * 64,
        "--measurement-oci-manifest-digest",
        "sha256:" + "e" * 64,
        "--measurement-oci-config-digest",
        "sha256:" + "f" * 64,
    ]


def _issue(out: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, os.fspath(TOOL), *_synthetic_args(out)],
        cwd=os.fspath(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _load_lane(out: Path, lane: str) -> object:
    if lane == "inspector":
        from ksi_processing_controller.external_inspector_operator_config import (
            load_external_inspector_operator_config,
        )

        return load_external_inspector_operator_config(out / lane / "operator-config.json")
    from ksi_processing_controller.external_measurement_operator_config import (
        load_external_measurement_operator_config,
    )

    return load_external_measurement_operator_config(out / lane / "operator-config.json")


def _validate_lane(config: object) -> None:
    if type(config).__name__ == "ExternalInspectorOperatorConfigV1":
        from ksi_processing_controller.external_inspector_operator_config import (
            validate_operator_startup_artifacts,
        )

        validate_operator_startup_artifacts(config)  # type: ignore[arg-type]
        return
    from ksi_processing_controller.external_measurement_operator_config import (
        validate_measurement_operator_startup_artifacts,
    )

    validate_measurement_operator_startup_artifacts(config)  # type: ignore[arg-type]


def _blocked_code(exc: Exception) -> str:
    return type(exc).__name__ + ":" + exc.code.value  # type: ignore[attr-defined]


def _rewrite_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _tamper_manifest_body(manifest_path: Path) -> None:
    wire = json.loads(manifest_path.read_text(encoding="utf-8"))
    body = wire["body"]
    original = body["sourceTreeDigest"]
    replacement = original[:-1] + ("0" if original[-1] != "0" else "1")
    assert replacement != original
    body["sourceTreeDigest"] = replacement
    _rewrite_json(manifest_path, wire)


def _revoke_manifest(out: Path, lane: str) -> None:
    from ksi_event_contracts.inspector_execution_manifest import (
        parse_inspector_execution_manifest_wire,
    )

    manifest_path = out / lane / "manifest.json"
    manifest = parse_inspector_execution_manifest_wire(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    revocation_path = out / lane / "revocations.json"
    payload = json.loads(revocation_path.read_text(encoding="utf-8"))
    payload["revokedManifestDigests"] = sorted(
        {*payload["revokedManifestDigests"], manifest.canonical_body_digest()}
    )
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    revocation_path.write_bytes(raw)
    config_path = out / lane / "operator-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["production"]["catalog"]["expectedRevocationSha256"] = _digest(raw)
    _rewrite_json(config_path, config)


def _break_oci_pair(out: Path, lane: str) -> None:
    pairs_path = out / lane / "oci-pairs.json"
    payload = json.loads(pairs_path.read_text(encoding="utf-8"))
    assert len(payload["pairs"]) == 1
    payload["pairs"][0]["dockerImageId"] = "sha256:" + "0" * 64
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    pairs_path.write_bytes(raw)
    config_path = out / lane / "operator-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["production"]["ociPairs"]["expectedSha256"] = _digest(raw)
    _rewrite_json(config_path, config)


def test_issued_synthetic_deployment_is_accepted_by_real_validators(tmp_path: Path) -> None:
    out = tmp_path / "deployment"
    completed = _issue(out)
    assert completed.returncode == 0, completed.stderr

    for lane in ("inspector", "measurement"):
        lane_dir = out / lane
        for name in ("manifest.json", "revocations.json", "operator-config.json"):
            node = (lane_dir / name).stat()
            assert stat.S_ISREG(node.st_mode)
            assert node.st_nlink == 1
            assert (node.st_mode & 0o777) == 0o600
        assert (lane_dir / "oci-pairs.json").exists()
        assert (lane_dir / "trust-public-keys.json").exists()
        _validate_lane(_load_lane(out, lane))

    receipt = json.loads((out / "step3a-receipt.json").read_text(encoding="utf-8"))
    assert receipt["validation"]["inspector"] == "ACCEPTED"
    assert receipt["validation"]["measurement"] == "ACCEPTED"
    private_material = b"".join(
        path.read_bytes() for path in sorted((out / "keys").glob("*.private"))
    )
    assert private_material
    assert private_material not in (out / "step3a-receipt.json").read_bytes()
    assert receipt["inspectorKeyId"] != receipt["measurementKeyId"]


@pytest.mark.parametrize("lane", ["inspector", "measurement"])
def test_issued_deployment_rejects_mutated_signature(tmp_path: Path, lane: str) -> None:
    out = tmp_path / "deployment"
    assert _issue(out).returncode == 0
    _tamper_manifest_body(out / lane / "manifest.json")
    with pytest.raises(Exception) as blocked:
        _validate_lane(_load_lane(out, lane))
    assert _blocked_code(blocked.value).endswith("CATALOG")


@pytest.mark.parametrize("lane", ["inspector", "measurement"])
def test_issued_deployment_rejects_revoked_manifest(tmp_path: Path, lane: str) -> None:
    out = tmp_path / "deployment"
    assert _issue(out).returncode == 0
    _revoke_manifest(out, lane)
    with pytest.raises(Exception) as blocked:
        _validate_lane(_load_lane(out, lane))
    assert _blocked_code(blocked.value).endswith("CATALOG")


@pytest.mark.parametrize("lane", ["inspector", "measurement"])
def test_issued_deployment_rejects_broken_oci_pair(tmp_path: Path, lane: str) -> None:
    out = tmp_path / "deployment"
    assert _issue(out).returncode == 0
    _break_oci_pair(out, lane)
    with pytest.raises(Exception) as blocked:
        _validate_lane(_load_lane(out, lane))
    assert _blocked_code(blocked.value).endswith("OCI_EVIDENCE")
