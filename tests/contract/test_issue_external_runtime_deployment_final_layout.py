"""Contract: final-layout issuance overrides for the Step-3 issuance tool.

The tool (``tools/issue_external_runtime_deployment.py``) defaults to a fully
self-contained staging layout.  For host placement it must also support
explicit final-layout path overrides (artifact dirs, staging roots, journal
paths, worker core URL/object origin) while preserving default behavior.
A final-layout issuance references absolute host paths that only exist after
placement, so ``--defer-validation`` skips the in-tool self-verify; this
module then places the issued bytes at the referenced locations and proves
the placed set is ACCEPTED by the real loaders/validators.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "tools" / "issue_external_runtime_deployment.py"


def _final_args(out: Path, final: Path) -> list[str]:
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
        "--core-base-url",
        "https://core-final.invalid:10102",
        "--staging-root",
        os.fspath(out / "staging"),
        "--inspector-artifact-dir",
        os.fspath(final / "etc" / "inspector"),
        "--measurement-artifact-dir",
        os.fspath(final / "etc" / "measurement"),
        "--operator-dir",
        os.fspath(final / "etc" / "operator"),
        "--inspector-map-dir",
        os.fspath(final / "etc" / "inspector"),
        "--measurement-map-dir",
        os.fspath(final / "etc" / "measurement"),
        "--inspector-input-root",
        os.fspath(final / "varlib" / "inspector-input"),
        "--inspector-output-root",
        os.fspath(final / "varlib" / "inspector-output"),
        "--inspector-journal-path",
        os.fspath(final / "varlib" / "inspector-attempts.jsonl"),
        "--measurement-input-root",
        os.fspath(final / "varlib" / "measurement-input"),
        "--measurement-journal-path",
        os.fspath(final / "varlib" / "measurement-attempts.jsonl"),
        "--inspector-cgroup-root",
        os.fspath(final / "varlib" / "inspector-cgroup"),
        "--measurement-cgroup-root",
        os.fspath(final / "varlib" / "measurement-cgroup"),
        "--worker-private-output-root",
        os.fspath(final / "varlib" / "worker-output"),
        "--object-endpoint-origin",
        "https://objects-final.invalid:10103",
        "--object-endpoint-addresses",
        "127.0.0.1",
        "--defer-validation",
    ]


def _issue_final(out: Path, final: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, os.fspath(TOOL), *_final_args(out, final)],
        cwd=os.fspath(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _place_lane(out: Path, final_etc_lane: Path, lane: str) -> None:
    lane_dir = out / lane
    final_etc_lane.mkdir(parents=True, exist_ok=True)
    for name in (
        "manifest.json",
        "revocations.json",
        "oci-pairs.json",
        "trust-public-keys.json",
        "operator-config.json",
    ):
        target = final_etc_lane / name
        target.write_bytes((lane_dir / name).read_bytes())
        os.chmod(target, 0o600)


def test_final_layout_issuance_passes_real_validators_after_placement(
    tmp_path: Path,
) -> None:
    out = tmp_path / "deployment"
    final = tmp_path / "final"
    completed = _issue_final(out, final)
    assert completed.returncode == 0, completed.stderr

    inspector_config = json.loads((out / "inspector" / "operator-config.json").read_text())
    assert inspector_config["production"]["inputRoot"] == os.fspath(
        final / "varlib" / "inspector-input"
    )
    assert inspector_config["production"]["journalPath"] == os.fspath(
        final / "varlib" / "inspector-attempts.jsonl"
    )
    assert inspector_config["production"]["catalog"]["manifestPath"] == os.fspath(
        final / "etc" / "inspector" / "manifest.json"
    )
    worker_config = json.loads((out / "worker" / "config.json").read_text())
    assert worker_config["core"]["baseUrl"] == "https://core-final.invalid:10102"
    assert worker_config["objectTransport"]["endpoints"] == [
        {"origin": "https://objects-final.invalid:10103", "addresses": ["127.0.0.1"]}
    ]
    assert worker_config["measurement"]["manifest"]["path"] == os.fspath(
        final / "etc" / "measurement" / "manifest.json"
    )
    provider = json.loads((out / "core" / "operator" / "provider.json").read_text())
    assert provider["keyRegistryPath"] == os.fspath(
        final / "etc" / "operator" / "authority-key-registry.json"
    )

    # Private staging issuance only: place the bytes, then prove acceptance.
    for lane in ("inspector", "measurement"):
        _place_lane(out, final / "etc" / lane, lane)
    operator_final = final / "etc" / "operator"
    operator_final.mkdir(parents=True, exist_ok=True)
    for name in (
        "authority-key-registry.json",
        "authority-snapshot.json",
        "provider.json",
        "workflow.json",
        "quantitative-catalog.json",
    ):
        target = operator_final / name
        target.write_bytes((out / "core" / "operator" / name).read_bytes())
        os.chmod(target, 0o600)

    from ksi_processing_controller.external_inspector_operator_config import (
        load_external_inspector_operator_config,
        validate_operator_startup_artifacts,
    )
    from ksi_processing_controller.external_measurement_operator_config import (
        load_external_measurement_operator_config,
        validate_measurement_operator_startup_artifacts,
    )
    from ksi_processing_controller.external_validation_worker_config import (
        load_external_validation_worker_config,
        load_pinned_measurement_manifest,
        read_external_validation_core_token,
    )

    validate_operator_startup_artifacts(
        load_external_inspector_operator_config(
            final / "etc" / "inspector" / "operator-config.json"
        )
    )
    validate_measurement_operator_startup_artifacts(
        load_external_measurement_operator_config(
            final / "etc" / "measurement" / "operator-config.json"
        )
    )
    worker = load_external_validation_worker_config(out / "worker" / "config.json")
    read_external_validation_core_token(out / "worker" / "core.token")
    load_pinned_measurement_manifest(worker.measurement)

    receipt = json.loads((out / "step3a-receipt.json").read_text(encoding="utf-8"))
    assert receipt["validation"]["status"] == "DEFERRED"
    for name in ("manifest.json", "revocations.json", "operator-config.json"):
        for lane in ("inspector", "measurement"):
            node = (out / lane / name).stat()
            assert stat.S_ISREG(node.st_mode)
            assert (node.st_mode & 0o777) == 0o600
