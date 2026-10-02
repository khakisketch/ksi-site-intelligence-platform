"""Owner-protected data configuration; fresh ephemeral keys are test material only."""

import base64
import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from spatial_data_fixture import DIGEST, NOW, make_activation, make_policy, make_runtime


def config_body(tmp_path: Path) -> dict[str, Any]:
    key = Ed25519PrivateKey.generate()
    activation = make_activation()
    return {
        "version": "spatial-data-worker-config.v1",
        "coreOrigin": "https://core.invalid",
        "maximumResponseBytes": 1048576,
        "requestTimeoutSeconds": 2.0,
        "pollIntervalSeconds": 1.0,
        "heartbeatIntervalMillis": 100,
        "workspaceRoot": str(tmp_path),
        "policy": make_policy().model_dump(by_alias=True, mode="json"),
        "runtime": make_runtime().model_dump(by_alias=True, mode="json"),
        "activation": activation.model_dump(by_alias=True, mode="json"),
        "activationSignature": base64.b64encode(key.sign(activation.signing_bytes())).decode(),
        "trustedPublicKey": base64.b64encode(key.public_key().public_bytes_raw()).decode(),
        "revokedActivationDigests": [],
        "objectTransport": {
            "endpoints": [{"origin": "https://store.invalid", "addresses": ["127.0.0.1"]}],
            "maxHeaderBytes": 4096,
            "maxObjectBytes": 8192,
            "maxChunkBytes": 512,
        },
        "sandbox": {
            "launcherPath": str(tmp_path / "launcher"),
            "launcherSha256": DIGEST,
            "containmentProofPath": str(tmp_path / "proof.json"),
            "containmentProofSha256": DIGEST,
        },
    }


def write_private(path: Path, body: Any) -> Path:
    path.write_bytes(json.dumps(body).encode())
    path.chmod(0o600)
    return path


def load(path: Path, *, now: Any = NOW) -> Any:
    from ksi_processing_controller.spatial_data_worker_config import load_spatial_data_worker_config

    return load_spatial_data_worker_config(path, now=now)


def test_config_verifies_domain_signature_and_exact_distinct_policy_runtime(tmp_path: Path) -> None:
    """Unsigned/digest-only authority must not enable the polling lane."""
    body = config_body(tmp_path)
    result = load(write_private(tmp_path / "config.json", body))
    assert result.activation.activation_id == "local-activation"
    assert result.policy.policy_digest == body["policy"]["policyDigest"]
    assert result.object_policy.max_chunk_bytes == 512
    assert result.worker_instance_id == "instance-local"
    assert "activationSignature" not in repr(result)


@pytest.mark.parametrize(
    "change",
    [
        "signature",
        "key",
        "policy",
        "runtime",
        "unsigned",
        "revoked",
        "expired",
        "origin",
        "budget",
        "heartbeat",
        "unknown",
        "credential",
        "relative-workspace",
    ],
)
def test_config_refuses_unproved_or_disconnected_authority(tmp_path: Path, change: str) -> None:
    """Removing any signature/binding/currentness/closed-field check makes this fail."""
    body = config_body(tmp_path)
    now = NOW
    if change == "signature":
        body["activationSignature"] = base64.b64encode(b"x" * 64).decode()
    elif change == "key":
        body["trustedPublicKey"] = base64.b64encode(b"x" * 32).decode()
    elif change == "policy":
        body["policy"] = make_policy(revision=2).model_dump(by_alias=True, mode="json")
    elif change == "runtime":
        body["runtime"] = make_runtime(build_digest="sha256:" + "f" * 64).model_dump(
            by_alias=True, mode="json"
        )
    elif change == "unsigned":
        body["activation"]["activationDigest"] = None
    elif change == "revoked":
        body["revokedActivationDigests"] = [body["activation"]["activationDigest"]]
    elif change == "expired":
        now += timedelta(hours=1)
    elif change == "origin":
        body["objectTransport"]["endpoints"][0]["origin"] = "https://foreign.invalid"
    elif change == "budget":
        body["maximumResponseBytes"] = 1048577
    elif change == "heartbeat":
        body["heartbeatIntervalMillis"] = 6000
    elif change == "unknown":
        body["factory"] = "caller.code"
    elif change == "credential":
        body["token"] = "not-config-material"
    elif change == "relative-workspace":
        body["workspaceRoot"] = "relative"
    from ksi_processing_controller.spatial_data_worker_config import SpatialDataWorkerConfigError

    with pytest.raises(SpatialDataWorkerConfigError):
        load(write_private(tmp_path / "config.json", body), now=now)


@pytest.mark.parametrize(
    "raw", [b'{"version":0,"version":1}', b'{"x":NaN}', b"\xff", b" " * 262145]
)
def test_config_rejects_hostile_json_before_assembly(tmp_path: Path, raw: bytes) -> None:
    from ksi_processing_controller.spatial_data_worker_config import SpatialDataWorkerConfigError

    path = tmp_path / "config.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    with pytest.raises(SpatialDataWorkerConfigError):
        load(path)


@pytest.mark.parametrize(
    "change", ["mode", "symlink", "hardlink", "ancestor-symlink", "ancestor-writable"]
)
def test_config_refuses_substitutable_private_file(tmp_path: Path, change: str) -> None:
    from ksi_processing_controller.spatial_data_worker_config import SpatialDataWorkerConfigError

    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    path = write_private(directory / "config.json", config_body(tmp_path))
    if change == "mode":
        path.chmod(0o644)
    elif change == "symlink":
        link = directory / "link"
        link.symlink_to(path)
        path = link
    elif change == "hardlink":
        os.link(path, directory / "alias")
    elif change == "ancestor-symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(directory, target_is_directory=True)
        path = alias / "config.json"
    elif change == "ancestor-writable":
        directory.chmod(0o777)
    with pytest.raises(SpatialDataWorkerConfigError):
        load(path)


def test_fresh_load_observes_owner_revocation_and_expiry(tmp_path: Path) -> None:
    from ksi_processing_controller.spatial_data_worker_config import SpatialDataWorkerConfigError

    body = config_body(tmp_path)
    path = write_private(tmp_path / "config.json", body)
    assert load(path).activation.is_current_at(NOW)
    body["revokedActivationDigests"] = [body["activation"]["activationDigest"]]
    write_private(path, body)
    with pytest.raises(SpatialDataWorkerConfigError):
        load(path)


@pytest.mark.parametrize("raw", [b"", b"bearer\r\n", b"bearer\nextra", b" b", b"\xff", b"x" * 4097])
def test_separate_token_is_bounded_not_reflected_or_environment_sourced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: bytes
) -> None:
    from ksi_processing_controller.spatial_data_worker_config import (
        SpatialDataWorkerConfigError,
        read_spatial_data_core_token,
    )

    monkeypatch.setenv("CORE_TOKEN", "must-not-be-used")
    path = tmp_path / "token"
    path.write_bytes(raw)
    path.chmod(0o600)
    with pytest.raises(SpatialDataWorkerConfigError) as error:
        read_spatial_data_core_token(path)
    assert "must-not-be-used" not in str(error.value)
    assert str(path) not in str(error.value)


def test_separate_token_refreshes_from_explicit_0600_file(tmp_path: Path) -> None:
    from ksi_processing_controller.spatial_data_worker_config import read_spatial_data_core_token

    path = tmp_path / "token"
    path.write_bytes(b"one\n")
    path.chmod(0o600)
    assert read_spatial_data_core_token(path) == "one"
    path.write_bytes(b"two\n")
    assert read_spatial_data_core_token(path) == "two"


def test_runner_missing_containment_material_blocks_before_core_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from ksi_processing_controller import spatial_data_runner
    from ksi_processing_controller.spatial_data_worker import SpatialDataWorkerError

    path = write_private(tmp_path / "config.json", config_body(tmp_path))
    token = tmp_path / "token"
    token.write_bytes(b"private-bearer")
    token.chmod(0o600)

    def unexpected(**kwargs: Any) -> None:
        pytest.fail("Core was contacted before containment material verification")

    monkeypatch.setattr(spatial_data_runner, "SpatialDataCoreClient", unexpected)
    with pytest.raises(SpatialDataWorkerError, match="ACTIVATION_UNAVAILABLE"):
        spatial_data_runner.run_worker(
            config_path=path, token_path=token, stop=threading.Event(), clock=lambda: NOW, once=True
        )


@pytest.mark.parametrize("turns", [1, 2])
def test_runner_polls_exact_lane_with_fresh_config_and_closes_real_http_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, turns: int
) -> None:
    import threading

    import httpx
    from ksi_processing_controller import spatial_data_runner
    from ksi_processing_controller.spatial_data_core_client import SpatialDataCoreClient

    path = write_private(tmp_path / "config.json", config_body(tmp_path))
    token = tmp_path / "token"
    token.write_bytes(b"explicit-bearer")
    token.chmod(0o600)
    requests, clients = [], []
    stop = threading.Event()

    def transport(request: Any) -> Any:
        requests.append(request)
        if len(requests) == turns:
            stop.set()
        return httpx.Response(200, json={"items": []})

    def factory(**kwargs: Any) -> Any:
        client = SpatialDataCoreClient(**kwargs, transport=httpx.MockTransport(transport))
        clients.append(client)
        return client

    # Only the external host-proof boundary is synthetic, never a production fallback.
    monkeypatch.setattr(
        spatial_data_runner.PinnedSpatialDataLauncher,
        "verify_material",
        lambda self, **kwargs: None,
    )
    monkeypatch.setattr(spatial_data_runner, "SpatialDataCoreClient", factory)
    assert (
        spatial_data_runner.run_worker(
            config_path=path, token_path=token, stop=stop, clock=lambda: NOW, once=turns == 1
        )
        == 0
    )
    assert len(requests) == turns and requests[0].url.path == "/v1/internal/spatial-data-jobs"
    assert requests[0].headers["authorization"] == "Bearer explicit-bearer"
    assert len(clients) == 1 and clients[0]._client.is_closed


def test_runner_cli_rejects_environment_only_configuration(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from ksi_processing_controller.spatial_data_runner import main

    monkeypatch.setenv("CORE_TOKEN", "environment-bearer-must-not-be-used")
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2
    assert "environment-bearer-must-not-be-used" not in capsys.readouterr().err


@pytest.mark.parametrize("change", ["public-mode", "ancestor-symlink", "absent"])
def test_config_requires_existing_non_substitutable_workspace_before_polling(
    tmp_path: Path, change: str
) -> None:
    from ksi_processing_controller.spatial_data_worker_config import SpatialDataWorkerConfigError

    body = config_body(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    if change == "public-mode":
        workspace.chmod(0o755)
    elif change == "ancestor-symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        workspace = alias / "workspace"
    else:
        workspace = tmp_path / "absent"
    body["workspaceRoot"] = str(workspace)
    with pytest.raises(SpatialDataWorkerConfigError):
        load(write_private(tmp_path / "config.json", body))
