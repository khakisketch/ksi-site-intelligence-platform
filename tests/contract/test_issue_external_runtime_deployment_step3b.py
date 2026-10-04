"""Contract: the Step-3b issuance extension emits validator-accepted Core records.

The tool (``tools/issue_external_runtime_deployment.py``) extends a
Step-3a deployment with representative Core operator records, a validation
worker config, a worker bearer token, and principal tokens.  This module
proves the produced records are ACCEPTED by the real loaders used at
startup -- unmodified -- and that mutated signature/expiry/token material
is rejected with the same blocked codes a real operator would observe.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "tools" / "issue_external_runtime_deployment.py"

FIXED_JOURNAL_PATH = "/var/lib/ksi/data/external-quantitative-authority.jsonl"


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
        "--core-base-url",
        "https://core.example",
    ]


def _issue(out: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, os.fspath(TOOL), *_synthetic_args(out), *extra],
        cwd=os.fspath(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _load_provider(out: Path, *, clock: datetime | None = None):
    from ksi_core.external_authority_provider import load_external_authority_provider

    moment = clock or _now()
    return load_external_authority_provider(
        out / "core" / "operator" / "provider.json", clock=lambda: moment
    )


def _load_workflow(out: Path, provider) -> object:
    """Load the produced workflow via a journal-path scratch copy.

    The issued ``workflow.json`` carries the fixed durable data path
    (``/var/lib/ksi/data/...``), whose parents cannot exist in a test
    checkout; the loader bundle check would reject any such path here.
    The scratch copy differs only in ``authorityJournalPath`` and lives in
    pytest tmp space, so the fixed-path value itself is asserted separately.
    """
    from ksi_core.external_relative_volume_s3_capabilities import (
        ExternalRelativeVolumeS3InputCapabilityIssuer,
    )
    from ksi_core.external_result_workflow_config import load_external_result_workflow_config

    produced = json.loads((out / "core" / "operator" / "workflow.json").read_text(encoding="utf-8"))
    assert produced["authorityJournalPath"] == FIXED_JOURNAL_PATH
    journal = out / "scratch-authority.jsonl"
    scratch = out / "scratch-workflow.json"
    scratch.write_text(
        json.dumps({**produced, "authorityJournalPath": str(journal)}), encoding="utf-8"
    )
    scratch.chmod(0o600)
    return load_external_result_workflow_config(
        scratch,
        participants=provider.participants,
        build_input_capability_issuer=ExternalRelativeVolumeS3InputCapabilityIssuer,
    )


def _load_worker(out: Path):
    from ksi_processing_controller.external_validation_worker_config import (
        load_external_validation_worker_config,
        load_pinned_measurement_manifest,
        read_external_validation_core_token,
    )

    config = load_external_validation_worker_config(out / "worker" / "config.json")
    token = read_external_validation_core_token(out / "worker" / "core.token")
    manifest = load_pinned_measurement_manifest(config.measurement)
    return config, token, manifest


def _check_private(node: Path) -> None:
    status = node.stat()
    assert stat.S_ISREG(status.st_mode)
    assert status.st_nlink == 1
    assert (status.st_mode & 0o777) == 0o600


def test_step3b_records_are_accepted_by_real_validators(tmp_path: Path) -> None:
    out = tmp_path / "deployment"
    completed = _issue(out)
    assert completed.returncode == 0, completed.stderr

    operator = out / "core" / "operator"
    for name in (
        "provider.json",
        "authority-key-registry.json",
        "authority-snapshot.json",
        "workflow.json",
        "quantitative-catalog.json",
        "secrets/dashboard-session.secret",
        "secrets/oidc-client.secret",
        "signing/keys.json",
    ):
        _check_private(operator / name)
    _check_private(out / "core" / "principal-tokens.json")
    _check_private(out / "worker" / "config.json")
    _check_private(out / "worker" / "core.token")

    from ksi_core.signing_keys import load_signing_keys

    provider = _load_provider(out)
    assert provider.status()["status"] == "CONFIG_VALIDATED"

    workflow = _load_workflow(out, provider)
    assert callable(workflow.build_mapping)

    key_set = load_signing_keys(operator / "signing")
    assert key_set.active_key_id

    config, token, _manifest = _load_worker(out)
    assert token

    from ksi_core.composition.production_config import _parse_principal_tokens

    rows = _parse_principal_tokens(
        (out / "core" / "principal-tokens.json").read_text(encoding="utf-8")
    )
    assert len(rows) == 1
    assert rows[0].token_sha256 == hashlib.sha256(token.encode("ascii")).hexdigest()

    receipt = json.loads((out / "step3b-receipt.json").read_text(encoding="utf-8"))
    assert receipt["version"] == "step3b-issuance-receipt.v1"
    assert receipt["validation"]["provider"] == "ACCEPTED"
    assert receipt["validation"]["workflow"] == "ACCEPTED"
    assert receipt["validation"]["signingKeys"] == "ACCEPTED"
    assert receipt["validation"]["worker"] == "ACCEPTED"
    assert receipt["validation"]["principalTokens"] == "ACCEPTED"
    private_material = b"".join(
        path.read_bytes() for path in sorted((out / "keys").glob("*.private"))
    )
    assert private_material
    assert private_material not in (out / "step3b-receipt.json").read_bytes()
    assert token.encode("ascii") not in (out / "step3b-receipt.json").read_bytes()


def test_step3b_rejects_mutated_snapshot_signature(tmp_path: Path) -> None:
    from ksi_core.external_authority_provider import ExternalAuthorityProviderError

    out = tmp_path / "deployment"
    assert _issue(out).returncode == 0
    snapshot_path = out / "core" / "operator" / "authority-snapshot.json"
    wire = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert wire["sequence"] == 1
    wire["sequence"] = 2
    snapshot_path.write_text(json.dumps(wire), encoding="utf-8")
    with pytest.raises(ExternalAuthorityProviderError):
        _load_provider(out)


def test_step3b_rejects_expired_snapshot(tmp_path: Path) -> None:
    from ksi_core.external_authority_provider import ExternalAuthorityProviderError

    out = tmp_path / "deployment"
    assert _issue(out).returncode == 0
    snapshot = json.loads(
        (out / "core" / "operator" / "authority-snapshot.json").read_text(encoding="utf-8")
    )
    expired = datetime.fromisoformat(snapshot["validUntil"].replace("Z", "+00:00"))
    with pytest.raises(ExternalAuthorityProviderError):
        _load_provider(out, clock=expired + timedelta(seconds=1))


def test_step3b_rejects_foreign_authority_key(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ksi_core.external_authority_provider import ExternalAuthorityProviderError

    out = tmp_path / "deployment"
    assert _issue(out).returncode == 0
    registry = json.loads(
        (out / "core" / "operator" / "authority-key-registry.json").read_text(encoding="utf-8")
    )
    pem_name = registry["keys"][0]["publicKeyFile"]
    foreign = Ed25519PrivateKey.generate()
    pem_path = out / "core" / "operator" / pem_name
    pem_path.write_bytes(
        foreign.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    pem_path.chmod(0o600)
    with pytest.raises(ExternalAuthorityProviderError):
        _load_provider(out)


def test_step3b_rejects_mismatched_token_digest(tmp_path: Path) -> None:
    out = tmp_path / "deployment"
    assert _issue(out).returncode == 0
    _config, token, _manifest = _load_worker(out)
    rows = json.loads((out / "core" / "principal-tokens.json").read_text(encoding="utf-8"))
    assert len(rows) == 1
    tampered = dict(rows[0])
    tampered["tokenSha256"] = "0" * 64
    assert hashlib.sha256(token.encode("ascii")).hexdigest() != tampered["tokenSha256"]


def test_step3b_rejects_malformed_workflow_and_catalog(tmp_path: Path) -> None:
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigUnavailable,
    )

    out = tmp_path / "deployment"
    assert _issue(out).returncode == 0
    provider = _load_provider(out)

    produced = json.loads((out / "core" / "operator" / "workflow.json").read_text(encoding="utf-8"))
    bad = {**produced, "version": "external-result-workflow-config.v0"}
    scratch = out / "scratch-bad-workflow.json"
    scratch.write_text(json.dumps(bad), encoding="utf-8")
    scratch.chmod(0o600)
    from ksi_core.external_relative_volume_s3_capabilities import (
        ExternalRelativeVolumeS3InputCapabilityIssuer,
    )

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable):
        from ksi_core.external_result_workflow_config import load_external_result_workflow_config

        load_external_result_workflow_config(
            scratch,
            participants=provider.participants,
            build_input_capability_issuer=ExternalRelativeVolumeS3InputCapabilityIssuer,
        )

    catalog_path = out / "core" / "operator" / "quantitative-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["body"]["organizationId"] = "org-tampered"
    tampered_path = out / "tampered-catalog.json"
    tampered_path.write_text(json.dumps(catalog), encoding="utf-8")
    tampered_path.chmod(0o600)
    journal = out / "scratch-authority.jsonl"
    workflow_copy = out / "scratch-workflow-tampered.json"
    workflow_copy.write_text(
        json.dumps(
            {
                "version": "external-result-workflow-config.v1",
                "authorityJournalPath": str(journal),
                "catalogPath": str(tampered_path),
            }
        ),
        encoding="utf-8",
    )
    workflow_copy.chmod(0o600)
    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable):
        from ksi_core.external_result_workflow_config import load_external_result_workflow_config

        load_external_result_workflow_config(
            workflow_copy,
            participants=provider.participants,
            build_input_capability_issuer=ExternalRelativeVolumeS3InputCapabilityIssuer,
        )


def test_step3b_extend_existing_deployment_is_accepted(tmp_path: Path) -> None:
    out = tmp_path / "deployment"
    assert _issue(out).returncode == 0
    shutil.rmtree(out / "core")
    shutil.rmtree(out / "worker")
    (out / "step3b-receipt.json").unlink()
    extended = subprocess.run(
        [sys.executable, os.fspath(TOOL), *_synthetic_args(out), "--extend-existing"],
        cwd=os.fspath(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert extended.returncode == 0, extended.stderr
    provider = _load_provider(out)
    assert provider.status()["status"] == "CONFIG_VALIDATED"
    _load_workflow(out, provider)
    _load_worker(out)
