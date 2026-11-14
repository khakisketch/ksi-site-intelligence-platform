"""Exercise the real Core Docker ignore rules using only synthetic local files."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PRIVATE_INPUTS = (
    ".env",
    "deploy/.env",
    "deploy/.env.customer",
    "deploy/secrets/dashboard-session.secret",
    "deploy/signing-keys/key.private.pem",
    "operator/oidc-subject-registry.json",
    "operator/provider.private.pem",
    ".dev-data/session.json",
)


def test_core_build_context_excludes_operator_inputs(tmp_path: Path) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker is required for the real build-context check")
    try:
        probe = subprocess.run(
            [docker, "info", "--format", "{{.OSType}}"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("Docker daemon is unavailable")
    if probe.returncode != 0 or probe.stdout.strip() != "linux":
        pytest.skip("A Linux Docker daemon is required")

    context = tmp_path / "context"
    context.mkdir()
    shutil.copyfile(_ROOT / ".dockerignore", context / ".dockerignore")
    (context / "Dockerfile").write_text("FROM scratch\nCOPY . /context/\n", encoding="utf-8")
    for name in (*_PRIVATE_INPUTS, "services/core/public.py"):
        path = context / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic-build-context-fixture\n", encoding="utf-8")
    exported = tmp_path / "export"
    result = subprocess.run(
        [docker, "build", "--network=none", "--output",
         f"type=local,dest={exported}", str(context)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (exported / "context/services/core/public.py").is_file()
    leaked = [name for name in _PRIVATE_INPUTS if (exported / "context" / name).exists()]
    assert leaked == [], f"Operator material included in Core image context: {leaked}"
