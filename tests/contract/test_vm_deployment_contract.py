"""Additive VM compose, TLS ingress, secret, backup/restore release contract."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DEPLOY = _ROOT / "deploy"
_VM_COMPOSE = (_DEPLOY / "compose.vm.yaml").read_text(encoding="utf-8")
_CADDY = (_DEPLOY / "Caddyfile").read_text(encoding="utf-8")
_ENV = (_DEPLOY / ".env.example").read_text(encoding="utf-8")


def test_vm_compose_resolves_with_only_caddy_80_443_published() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker compose가 없는 환경")
    env = {**os.environ, "KSI_DEPLOY_ENV_FILE": ".env.example"}
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "compose.yaml",
            "-f",
            "compose.vm.yaml",
            "--env-file",
            ".env.example",
            "config",
            "--format",
            "json",
        ],
        cwd=_DEPLOY,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    config = json.loads(result.stdout)
    published = {
        service_name: [str(port["published"]) for port in service.get("ports", [])]
        for service_name, service in config["services"].items()
        if service.get("ports")
    }
    assert published == {"caddy": ["80", "443"]}
    # P3 Task 5: the managed worker service retired to archive/acquisition-2026/
    # (T3 split); no worker service exists to attach to the private network.
    for name in ("core", "dashboard", "minio", "nodeodm", "caddy"):
        assert "ksi-private" in config["services"][name]["networks"]


def test_vm_profile_separates_oidc_humans_secrets_and_public_object_origin() -> None:
    assert "KSI_CORE_HUMAN_AUTH_MODE: OIDC" in _VM_COMPOSE
    assert "KSI_DASHBOARD_HUMAN_AUTH_MODE: OIDC" in _VM_COMPOSE
    assert "KSI_DASHBOARD_SESSION_SECRET_FILE: /run/secrets/dashboard-session" in _VM_COMPOSE
    assert "KSI_DASHBOARD_OIDC_CLIENT_SECRET_FILE: /run/secrets/oidc-client" in _VM_COMPOSE
    assert "KSI_CORE_S3_PUBLIC_ENDPOINT: https://objects." in _VM_COMPOSE
    assert "dji-gateway:" not in _VM_COMPOSE
    assert "AUTH_SECRET=" not in _ENV
    assert "OIDC_CLIENT_SECRET=" not in _ENV


def test_caddy_routes_only_app_api_and_object_api_not_minio_console() -> None:
    assert "app.{$KSI_CLOUD_DOMAIN}" in _CADDY
    assert "api.{$KSI_CLOUD_DOMAIN}" in _CADDY
    assert "objects.{$KSI_CLOUD_DOMAIN}" in _CADDY
    assert "reverse_proxy dashboard:3000" in _CADDY
    assert "reverse_proxy core:8000" in _CADDY
    assert "reverse_proxy minio:9000" in _CADDY
    assert "9001" not in _CADDY


def test_dashboard_image_refuses_external_vm_before_starting_next() -> None:
    dockerfile = (_ROOT / "apps" / "dashboard" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    launcher = (
        _ROOT / "apps" / "dashboard" / "scripts" / "start-production.mjs"
    ).read_text(encoding="utf-8")
    assert "USER ksi-dashboard" in dockerfile
    assert 'CMD ["node", "scripts/start-production.mjs"]' in dockerfile
    assert "validateExternalVm" in launcher
    assert "KSI_DASHBOARD_SESSION_SECRET_FILE" in launcher
    assert 'await import("../server.js")' in launcher

    if shutil.which("node") is None:
        pytest.skip("node가 없는 환경")
    result = subprocess.run(
        ["node", "scripts/start-production.mjs"],
        cwd=_ROOT / "apps" / "dashboard",
        env={
            **os.environ,
            "KSI_DASHBOARD_DEPLOYMENT_PROFILE": "EXTERNAL_VM",
            "KSI_DASHBOARD_HUMAN_AUTH_MODE": "OIDC",
            "KSI_DASHBOARD_PUBLIC_APP_ORIGIN": "https://app.example.test",
            "KSI_DASHBOARD_PUBLIC_API_ORIGIN": "https://api.example.test",
            "KSI_DASHBOARD_OIDC_ISSUER": "https://id.example.test",
            "KSI_DASHBOARD_OIDC_CLIENT_ID": "test-dashboard",
            "KSI_DASHBOARD_SESSION_SECRET_FILE": "/missing/session-secret",
            "KSI_DASHBOARD_OIDC_CLIENT_SECRET_FILE": "/missing/client-secret",
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "session-secret" in result.stderr


def test_development_oidc_issuer_is_outside_production_vm_artifacts() -> None:
    """The loopback fixture is never a fallback IdP for the external VM profile."""
    production_sources = (
        _VM_COMPOSE,
        (_ROOT / "apps" / "dashboard" / "Dockerfile").read_text(encoding="utf-8"),
        (_ROOT / "apps" / "dashboard" / "scripts" / "start-production.mjs").read_text(
            encoding="utf-8"
        ),
    )
    for source in production_sources:
        assert "run_local_oidc_issuer" not in source
        assert "run-local-oidc-stack" not in source
        assert "local-identity" not in source


@pytest.mark.parametrize(
    "script",
    [
        "backup-vm.sh",
        "restore-check-vm.sh",
        "smoke-backup-restore.sh",
        "smoke-vm.sh",
    ],
)
def test_vm_operations_scripts_are_valid_bash(script: str) -> None:
    subprocess.run(
        ["bash", "-n", str(_DEPLOY / "bin" / script)],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )


def test_cloud_due_diligence_stays_open_before_customer_data_release() -> None:
    checklist = (
        _ROOT / "docs" / "security" / "CLOUD_PROVIDER_DUE_DILIGENCE.md"
    ).read_text(encoding="utf-8")
    assert "NOT APPROVED" in checklist
    assert "DEVELOPMENT AND SYNTHETIC DATA ONLY" in checklist
    assert "| OPEN |" in checklist
