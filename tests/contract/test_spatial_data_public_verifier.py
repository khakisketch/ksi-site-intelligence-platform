"""Explicit public-file verifier preflight must fail BEFORE transport without evidence."""

import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def invoke(tmp_path: Path, manifest: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    file = tmp_path / "manifest.json"
    file.write_text(json.dumps(manifest))
    return subprocess.run(
        [
            sys.executable,
            "tools/verify_spatial_data_public_sample.py",
            "--manifest",
            str(file),
            "--core-url",
            "https://no-transport.invalid",
            "--token-file",
            str(tmp_path / "absent-token"),
            "--policy-file",
            str(tmp_path / "absent-policy"),
            "--output-dir",
            str(tmp_path / "output"),
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )


def test_public_verifier_missing_original_is_typed_blocked_without_creating_output(
    tmp_path: Path,
) -> None:
    result = invoke(
        tmp_path,
        {
            "version": "spatial-data-public-sample.v1",
            "kind": "dsm",
            "sourceFile": str(tmp_path / "missing.tif"),
        },
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["reason"] == "PUBLIC_ORIGINAL_UNAVAILABLE"
    assert not (tmp_path / "output").exists()


def test_public_verifier_never_accepts_replacement_small_tiff_as_pinned_floreat(
    tmp_path: Path,
) -> None:
    source = tmp_path / "replacement.tif"
    source.write_bytes(b"synthetic replacement")
    result = invoke(
        tmp_path,
        {"version": "spatial-data-public-sample.v1", "kind": "ortho", "sourceFile": str(source)},
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["reason"] == "PUBLIC_ORIGINAL_IDENTITY_MISMATCH"
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "manifest", [{}, {"version": "spatial-data-public-sample.v1", "kind": "mesh"}]
)
def test_public_verifier_unknown_profile_is_not_silently_replaced(
    tmp_path: Path, manifest: dict[str, Any]
) -> None:
    result = invoke(tmp_path, manifest)
    assert (
        result.returncode == 2 and json.loads(result.stdout)["reason"] == "INVALID_SAMPLE_MANIFEST"
    )


def test_public_verifier_malformed_json_is_safe_nonzero(tmp_path: Path) -> None:
    file = tmp_path / "manifest.json"
    file.write_text('{"kind":"dsm","kind":"ortho"}')
    result = subprocess.run(
        [
            sys.executable,
            "tools/verify_spatial_data_public_sample.py",
            "--manifest",
            str(file),
            "--core-url",
            "https://no-transport.invalid",
            "--token-file",
            "/private/missing-token",
            "--policy-file",
            "/private/missing-policy",
            "--output-dir",
            str(tmp_path / "output"),
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["reason"] == "INVALID_SAMPLE_MANIFEST"
    assert "/private/" not in result.stdout and not result.stderr


def tool_module() -> ModuleType:
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location(
        "public_verifier",
        Path(__file__).resolve().parents[2] / "tools/verify_spatial_data_public_sample.py",
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "change,expected",
    [
        ("source-snapshot", "INSPECTION_UNAVAILABLE"),
        ("isolation", "ISOLATION_UNVERIFIED"),
        ("hash", "PUBLIC_ORIGINAL_IDENTITY_MISMATCH"),
    ],
)
def test_verifier_generated_test_only_pins_cannot_replace_inspection_or_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str, expected: str
) -> None:
    """Tests preflight with tiny actual bytes; production Floreat pins are never changed."""
    import hashlib

    from spatial_data_http_fixture import http_lane
    from spatial_data_job_fixture import NOW

    module = tool_module()
    with http_lane(tmp_path) as lane:
        monkeypatch.setitem(
            module.PINS,
            "dsm",
            (len(lane.source_bytes), hashlib.sha256(lane.source_bytes).hexdigest()),
        )
        manifest = {
            "version": "spatial-data-public-sample.v1",
            "kind": "dsm",
            "sourceFile": str(lane.source_path),
        }
        if change == "hash":
            lane.source_path.write_bytes(b"x" * len(lane.source_bytes))
        if change == "isolation":
            source = tmp_path / "source-snapshot.json"
            source.write_text(lane.graph.source.model_dump_json(by_alias=True))
            policy = tmp_path / "policy-snapshot.json"
            policy.write_text(lane.graph.data_policy.model_dump_json(by_alias=True))
            manifest["sourceSnapshotFile"] = str(source)
        else:
            policy = tmp_path / "no-policy"
        with pytest.raises(module.Blocked, match=expected):
            module.preflight(manifest, policy_file=policy, core_url="https://core.invalid", now=NOW)


def test_verifier_metadata_fifo_never_waits_for_writer(tmp_path: Path) -> None:
    import os

    fifo = tmp_path / "manifest.fifo"
    os.mkfifo(fifo)
    # Running the CLI has a strict process watchdog, without creating a FIFO writer.
    result = subprocess.run(
        [
            sys.executable,
            "tools/verify_spatial_data_public_sample.py",
            "--manifest",
            str(fifo),
            "--core-url",
            "https://no-transport.invalid",
            "--token-file",
            str(tmp_path / "missing-token"),
            "--policy-file",
            str(tmp_path / "missing-policy"),
            "--output-dir",
            str(tmp_path / "output"),
        ],
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert (
        result.returncode == 2 and json.loads(result.stdout)["reason"] == "INVALID_SAMPLE_MANIFEST"
    )


def generated_prerequisites(
    lane: Any, module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], Path, Path]:
    """Operator material is synthetic test-only; no actual kernel/container assertion."""
    import base64
    import hashlib
    from datetime import timedelta

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ksi_processing_controller.spatial_data_sandbox import SpatialDataContainmentProofV1
    from spatial_data_job_fixture import NOW
    from test_spatial_data_worker_config import config_body, write_private

    root, graph = lane.root, lane.graph
    monkeypatch.setitem(
        module.PINS, "dsm", (len(lane.source_bytes), hashlib.sha256(lane.source_bytes).hexdigest())
    )
    source = write_private(
        root / "source-snapshot.json", graph.source.model_dump(by_alias=True, mode="json")
    )
    policy = write_private(
        root / "policy-snapshot.json", graph.data_policy.model_dump(by_alias=True, mode="json")
    )
    launcher = root / "launcher"
    launcher.write_bytes(b"test-only non-executable launcher bytes")
    launcher.chmod(0o500)
    launcher_digest = "sha256:" + hashlib.sha256(launcher.read_bytes()).hexdigest()
    proof = SpatialDataContainmentProofV1(
        version="spatial-data-containment-proof.v1",
        runtime_digest=graph.runtime.runtime_digest,
        policy_digest=graph.data_policy.policy_digest,
        launcher_sha256=launcher_digest,
        resource_envelope=graph.data_policy.resource_envelope,
        max_output_bytes=graph.data_policy.max_output_bytes,
        network_namespace_inode=1,
        mount_namespace_inode=2,
        user_namespace_inode=3,
        mountinfo_sha256="sha256:" + "a" * 64,
        child_uid=1000,
        child_gid=1000,
        valid_until=NOW + timedelta(minutes=1),
    )
    proof_file = write_private(root / "proof.json", proof.model_dump(by_alias=True, mode="json"))
    key = Ed25519PrivateKey.generate()
    body = config_body(root)
    body.update(
        policy=graph.data_policy.model_dump(by_alias=True, mode="json"),
        runtime=graph.runtime.model_dump(by_alias=True, mode="json"),
        activation=graph.activation.model_dump(by_alias=True, mode="json"),
        workspaceRoot=str(lane.workspace),
        activationSignature=base64.b64encode(key.sign(graph.activation.signing_bytes())).decode(),
        trustedPublicKey=base64.b64encode(key.public_key().public_bytes_raw()).decode(),
    )
    body["objectTransport"].update(
        endpoints=[{"origin": lane.provider.origin, "addresses": ["127.0.0.1"]}],
        maxObjectBytes=1_000_000,
    )
    body["sandbox"].update(
        launcherPath=str(launcher),
        launcherSha256=launcher_digest,
        containmentProofPath=str(proof_file),
        containmentProofSha256="sha256:" + hashlib.sha256(proof_file.read_bytes()).hexdigest(),
    )
    config = write_private(root / "worker-config.json", body)
    manifest = dict(
        version="spatial-data-public-sample.v1",
        kind="dsm",
        sourceFile=str(lane.source_path),
        sourceSnapshotFile=str(source),
        workerConfigFile=str(config),
        requestedBounds=lane.request["requestedBounds"],
        idempotencyKey="integration-1",
    )
    return manifest, policy, proof_file


@pytest.mark.parametrize(
    "mutation", ["none", "proof", "proof-launcher", "launcher", "source", "policy", "bounds"]
)
def test_verifier_preflight_binds_existing_generated_only_inspection_policy_and_signed_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    from spatial_data_http_fixture import http_lane
    from spatial_data_job_fixture import NOW

    module = tool_module()
    with http_lane(tmp_path) as lane:
        manifest, policy, proof_file = generated_prerequisites(lane, module, monkeypatch)
        if mutation == "proof":
            proof_file.write_text("{}")
        elif mutation == "proof-launcher":
            import hashlib

            from test_spatial_data_worker_config import write_private

            proof = json.loads(proof_file.read_text())
            proof["launcherSha256"] = "sha256:" + "f" * 64
            write_private(proof_file, proof)
            configuration_path = Path(manifest["workerConfigFile"])
            configuration = json.loads(configuration_path.read_text())
            configuration["sandbox"]["containmentProofSha256"] = (
                "sha256:" + hashlib.sha256(proof_file.read_bytes()).hexdigest()
            )
            write_private(configuration_path, configuration)
        elif mutation == "launcher":
            (tmp_path / "launcher").chmod(0o700)
            (tmp_path / "launcher").write_bytes(b"substituted")
        elif mutation == "source":
            Path(manifest["sourceSnapshotFile"]).write_text("{}")
        elif mutation == "policy":
            policy.write_text("{}")
        elif mutation == "bounds":
            manifest["requestedBounds"] = [0, 0, 0, 0]
        if mutation == "none":
            source, selected_policy, config = module.preflight(
                manifest, policy_file=policy, core_url="https://core.invalid", now=NOW
            )
            assert source == lane.graph.source and selected_policy == lane.graph.data_policy
            assert config.worker_instance_id == "instance-1"
        else:
            with pytest.raises(module.Blocked):
                module.preflight(
                    manifest, policy_file=policy, core_url="https://core.invalid", now=NOW
                )


def test_generated_only_verifier_http_bytes_never_claim_public_pixels_or_host_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from types import SimpleNamespace

    from spatial_data_http_fixture import client_module, http_lane, mounted_transport
    from spatial_data_job_fixture import NOW

    module = tool_module()
    with http_lane(tmp_path) as lane:
        status = lane.request_and_run()
        manifest, policy, _ = generated_prerequisites(lane, module, monkeypatch)
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(manifest))
        token = tmp_path / "local-token"
        token.write_text("local")
        token.chmod(0o600)
        client = client_module()
        monkeypatch.setattr(
            module,
            "_client_module",
            lambda: SimpleNamespace(
                private_token=client.private_token,
                NativeWindowClient=lambda **kwargs: client.NativeWindowClient(
                    **kwargs, transport=mounted_transport(lane.http)
                ),
            ),
        )
        monkeypatch.setattr(module, "datetime", SimpleNamespace(now=lambda _: NOW))
        monkeypatch.setattr(module, "ATTRIBUTION", "Generated raster; local test only")
        output_dir = tmp_path / "verified-output"
        result = module.main(
            [
                "--manifest",
                str(manifest_file),
                "--policy-file",
                str(policy),
                "--token-file",
                str(token),
                "--core-url",
                "https://core.invalid",
                "--output-dir",
                str(output_dir),
            ]
        )
        observed = json.loads(capsys.readouterr().out)
        assert result == 0, observed
        assert (
            observed["status"] == "byte_receipt_verified" and observed["jobId"] == status["jobId"]
        )
        assert observed["hostContainmentVerified"] is observed["customerAcceptance"] is False
        assert observed["publicPixelMaskComparison"].startswith("NOT_RUN")
        assert observed["workerPeakRssCpuWorkspace"].startswith("NOT_MEASURED")
        assert (output_dir / observed["outputFile"]).read_bytes() == lane.provider.payload
