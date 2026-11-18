"""단면 일꾼 설정: 운영자가 고정한 키의 분리 서명, 현재성, 유한 예산. 임시 키는 시험 재료다."""

from __future__ import annotations

import base64
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_event_contracts.surface_profile_job import SurfaceProfileActivationV1
from spatial_data_fixture import make_envelope
from surface_profile_job_fixture import NOW, ORG, profile_policy, profile_runtime


def policy(**overrides: Any) -> Any:
    envelope = make_envelope(
        max_input_bytes=1_000_000,
        max_streamed_bytes=1_000_000,
        max_output_bytes=2_000_000,
        max_workspace_bytes=4_000_000,
        max_pixels=100_000,
        max_geometry_vertices=64,
        max_tenant_concurrency=3,
        max_queue_depth=8,
        max_deadline_seconds=120.0,
    )
    return profile_policy(resource_envelope=envelope, **overrides)


def config_body(tmp_path: Path) -> dict[str, Any]:
    key = Ed25519PrivateKey.generate()
    chosen, runtime = policy(), profile_runtime()
    activation = SurfaceProfileActivationV1(
        activation_id="profile-config-test",
        organization_id=ORG,
        worker_principal_id="worker-local",
        worker_instance_id="instance-1",
        policy_digest=chosen.policy_digest or "",
        runtime_digest=runtime.runtime_digest or "",
        trusted_endpoint_origins=("https://store.invalid",),
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=30),
    ).sealed()
    return {
        "version": "surface-profile-worker-config.v1",
        "coreOrigin": "https://core.invalid",
        "maximumResponseBytes": 1_000_000,
        "maximumRequestBytes": 500_000,
        "requestTimeoutSeconds": 2.0,
        "pollIntervalSeconds": 1.0,
        "heartbeatIntervalMillis": 100,
        "workspaceRoot": str(tmp_path),
        "policy": chosen.model_dump(by_alias=True, mode="json"),
        "runtime": runtime.model_dump(by_alias=True, mode="json"),
        "activation": activation.model_dump(by_alias=True, mode="json"),
        "activationSignature": base64.b64encode(key.sign(activation.signing_bytes())).decode(),
        "trustedPublicKey": base64.b64encode(key.public_key().public_bytes_raw()).decode(),
        "revokedActivationDigests": [],
        "objectTransport": {
            "endpoints": [{"origin": "https://store.invalid", "addresses": ["127.0.0.1"]}],
            "maxHeaderBytes": 4096,
            "maxObjectBytes": 1_000_000,
            "maxChunkBytes": 65_536,
        },
    }


def write_private(path: Path, body: Any) -> Path:
    path.write_bytes(json.dumps(body).encode())
    path.chmod(0o600)
    return path


def load(path: Path, *, now: Any = NOW) -> Any:
    from ksi_processing_controller.surface_profile_worker_config import (
        load_surface_profile_worker_config,
    )

    return load_surface_profile_worker_config(path, now=now)


def test_config_verifies_domain_signature_and_exact_policy_runtime(tmp_path: Path) -> None:
    body = config_body(tmp_path)
    result = load(write_private(tmp_path / "config.json", body))
    assert result.activation.activation_id == "profile-config-test"
    assert result.policy.policy_digest == body["policy"]["policyDigest"]
    assert result.object_policy.max_chunk_bytes == 65_536
    assert result.worker_instance_id == "instance-1"
    assert "activationSignature" not in repr(result)


@pytest.mark.parametrize(
    "change",
    [
        "signature",
        "key",
        "native_domain_signature",
        "policy",
        "runtime",
        "unsigned",
        "revoked",
        "expired",
        "origin",
        "response_budget",
        "request_budget",
        "request_not_above_result",
        "heartbeat",
        "timeout",
        "object_budget",
        "unknown",
        "credential",
        "relative_workspace",
        "insecure_core",
    ],
)
def test_config_refuses_unproved_or_disconnected_authority(tmp_path: Path, change: str) -> None:
    """서명·결속·현재성·닫힌 필드·유한 예산 중 하나라도 빼면 이 시험이 실패한다."""
    body = config_body(tmp_path)
    now = NOW
    if change == "signature":
        body["activationSignature"] = base64.b64encode(b"x" * 64).decode()
    elif change == "key":
        body["trustedPublicKey"] = base64.b64encode(b"x" * 32).decode()
    elif change == "native_domain_signature":
        from ksi_domain.canonical_json import canonical_json_bytes

        key = Ed25519PrivateKey.generate()
        payload = body["activation"]
        body["trustedPublicKey"] = base64.b64encode(key.public_key().public_bytes_raw()).decode()
        body["activationSignature"] = base64.b64encode(
            key.sign(
                canonical_json_bytes(
                    {"domain": "ksi-spatial-data-activation.v1", "payload": payload}
                )
            )
        ).decode()
    elif change == "policy":
        body["policy"] = policy(revision=2).model_dump(by_alias=True, mode="json")
    elif change == "runtime":
        body["runtime"] = (
            profile_runtime()
            .model_copy(update={"build_digest": "sha256:" + "f" * 64, "runtime_digest": None})
            .sealed()
            .model_dump(by_alias=True, mode="json")
        )
    elif change == "unsigned":
        body["activation"]["activationDigest"] = None
    elif change == "revoked":
        body["revokedActivationDigests"] = [body["activation"]["activationDigest"]]
    elif change == "expired":
        now += timedelta(hours=1)
    elif change == "origin":
        body["objectTransport"]["endpoints"][0]["origin"] = "https://foreign.invalid"
    elif change == "response_budget":
        body["maximumResponseBytes"] = 1_000_001
    elif change == "request_budget":
        body["maximumRequestBytes"] = 1_000_001
    elif change == "request_not_above_result":
        body["maximumRequestBytes"] = body["policy"]["maxResultBytes"]
    elif change == "heartbeat":
        body["heartbeatIntervalMillis"] = 2000
    elif change == "timeout":
        body["requestTimeoutSeconds"] = 3.0
    elif change == "object_budget":
        body["objectTransport"]["maxObjectBytes"] = 1_000_001
    elif change == "unknown":
        body["factory"] = "caller.code"
    elif change == "credential":
        body["token"] = "not-config-material"
    elif change == "relative_workspace":
        body["workspaceRoot"] = "relative"
    elif change == "insecure_core":
        body["coreOrigin"] = "http://core.invalid"
    from ksi_processing_controller.surface_profile_worker_config import (
        SurfaceProfileWorkerConfigError,
    )

    with pytest.raises(SurfaceProfileWorkerConfigError):
        load(write_private(tmp_path / "config.json", body), now=now)


def test_fresh_load_observes_owner_revocation(tmp_path: Path) -> None:
    from ksi_processing_controller.surface_profile_worker_config import (
        SurfaceProfileWorkerConfigError,
    )

    body = config_body(tmp_path)
    path = write_private(tmp_path / "config.json", body)
    assert load(path).activation.is_current_at(NOW)
    body["revokedActivationDigests"] = [body["activation"]["activationDigest"]]
    write_private(path, body)
    with pytest.raises(SurfaceProfileWorkerConfigError):
        load(path)


def test_config_requires_an_owner_private_workspace(tmp_path: Path) -> None:
    from ksi_processing_controller.surface_profile_worker_config import (
        SurfaceProfileWorkerConfigError,
    )

    open_workspace = tmp_path / "open"
    open_workspace.mkdir(mode=0o755)
    open_workspace.chmod(0o755)
    body = config_body(tmp_path)
    body["workspaceRoot"] = str(open_workspace)
    with pytest.raises(SurfaceProfileWorkerConfigError):
        load(write_private(tmp_path / "config.json", body))
