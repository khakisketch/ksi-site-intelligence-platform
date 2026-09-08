"""Phase 2 synthetic staging stays isolated, fail-closed, and device-free."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DEPLOY = _ROOT / "deploy"
_COMPOSE = (_DEPLOY / "compose.synthetic-staging.yaml").read_text(encoding="utf-8")
_LIFECYCLE = (_DEPLOY / "bin" / "phase2-staging.sh").read_text(encoding="utf-8")
_PROVIDER = (_DEPLOY / "synthetic-staging" / "provider.py").read_text(encoding="utf-8")
_STATE = (_DEPLOY / "synthetic-staging" / "prepare_state.py").read_text(encoding="utf-8")


def test_synthetic_staging_resolves_with_loopback_only_host_ports(tmp_path: Path) -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker compose가 없는 환경")
    env_file = tmp_path / "staging.env"
    subprocess.run(
        [
            "uv",
            "run",
            "--locked",
            "python",
            str(_DEPLOY / "synthetic-staging" / "prepare_env.py"),
            "--output",
            str(env_file),
            "--host",
            "phase2.example.ts.net",
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(_DEPLOY / "compose.synthetic-staging.yaml"),
            "config",
            "--format",
            "json",
        ],
        cwd=_ROOT,
        env=os.environ,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    config = json.loads(result.stdout)
    published = {
        (port["host_ip"], str(port["published"]))
        for service in config["services"].values()
        for port in service.get("ports", [])
    }
    assert published == {
        ("127.0.0.1", "10000"),
        ("127.0.0.1", "10002"),
        ("127.0.0.1", "10003"),
        ("127.0.0.1", "10004"),
    }
    assert env_file.stat().st_mode & 0o777 == 0o600
    for name in ("identity", "synthetic-copilot", "core", "dashboard"):
        service = config["services"][name]
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert "/tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777" in service["tmpfs"]
    assert (
        "/app/.next/cache:rw,noexec,nosuid,nodev,size=268435456,uid=10001,gid=10001,mode=0700"
        in config["services"]["dashboard"]["tmpfs"]
    )


def test_staging_reuses_production_auth_storage_and_copilot_boundaries() -> None:
    assert "KSI_CORE_HUMAN_AUTH_MODE: OIDC" in _COMPOSE
    assert "KSI_DASHBOARD_DEPLOYMENT_PROFILE: EXTERNAL_VM" in _COMPOSE
    assert "KSI_CORE_S3_PUBLIC_ENDPOINT: https://" in _COMPOSE
    assert "KSI_COPILOT_ENABLED: \"true\"" in _COMPOSE
    assert "--enable-synthetic-ai-egress" in _COMPOSE
    assert "--s3-endpoint http://minio:9000" in _COMPOSE
    assert "staging-secrets:/run/ksi-secrets:ro" in _COMPOSE
    assert "ksi-phase2-staging-data" in _COMPOSE
    assert "ksi-phase2-staging-objects" in _COMPOSE
    dockerignore = (_ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "!apps/dashboard/e2e/fixtures/seed_operations_console.py" in dockerignore


def test_staging_cannot_claim_or_start_real_device_and_processing_services() -> None:
    for forbidden_service in ("dji-gateway:", "worker:", "nodeodm:", "manifold:"):
        assert forbidden_service not in _COMPOSE
    assert "KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED: \"false\"" in _COMPOSE
    assert "No customer data, DJI service, device key, or flight action" in _COMPOSE
    assert "deviceBound=False" not in _COMPOSE  # no fabricated device evidence knobs


def test_synthetic_provider_has_no_outbound_client_or_prompt_logging() -> None:
    for outbound_client in ("import requests", "import httpx", "import urllib"):
        assert outbound_client not in _PROVIDER
    assert "synthetic-no-external-egress" in _PROVIDER
    assert "[fixture:provider-500]" in _PROVIDER
    assert "[fixture:unknown-citation]" in _PROVIDER
    assert "Never log prompts" in _PROVIDER


def test_secret_and_signing_state_fail_closed() -> None:
    assert "partial; refusing silent regeneration" in _STATE
    assert "path.chmod(0o400)" in _STATE
    assert "private_path.chmod(0o600)" in _STATE
    assert "phase2-synthetic-key-1" in _STATE


def test_lifecycle_only_changes_the_four_dedicated_serve_ports() -> None:
    assert "tailscale serve reset" not in _LIFECYCLE
    assert 'tailscale serve --https="$port" off' in _LIFECYCLE
    for port_variable in (
        "KSI_STAGING_APP_PORT",
        "KSI_STAGING_IDENTITY_PORT",
        "KSI_STAGING_API_PORT",
        "KSI_STAGING_OBJECTS_PORT",
    ):
        assert port_variable in _LIFECYCLE


@pytest.mark.parametrize("script", ["phase2-staging.sh", "smoke-synthetic-staging.sh"])
def test_synthetic_staging_scripts_are_valid_bash(script: str) -> None:
    subprocess.run(
        ["bash", "-n", str(_DEPLOY / "bin" / script)],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
