"""Platform boot switch (P3 Task 4): normal Core boot uses the platform profile.

Config-as-data, fail-closed on re-introduction: the Docker image CMD, the CI
smoke import and the composed core service must all reference the platform
production factory — never the legacy Mission-coupled factory. Archive inputs
stay excluded from the image and the linter. The legacy
``ksi_core.production.build_production_app`` stays importable until Task 5.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
_CI = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
_DOCKERIGNORE = (_ROOT / ".dockerignore").read_text(encoding="utf-8")
_COMPOSE = (_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")

_EXPECTED_CMD = [
    "/app/.venv/bin/uvicorn",
    "ksi_core.composition.platform_production:build_platform_production_app",
    "--factory",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
]


def _docker_cmd() -> list[str]:
    for line in _DOCKERFILE.splitlines():
        if line.startswith("CMD "):
            return json.loads(line[len("CMD ") :].strip())
    raise AssertionError("Dockerfile has no CMD line")


def test_docker_cmd_is_the_exact_platform_factory_invocation() -> None:
    assert _docker_cmd() == _EXPECTED_CMD


def test_ci_smoke_imports_the_platform_module() -> None:
    assert "import ksi_core.composition.platform_production" in _CI
    assert "import ksi_core.production" not in _CI


def test_archive_is_excluded_from_image_and_lint() -> None:
    assert any(line.strip() == "archive/" for line in _DOCKERIGNORE.splitlines()), (
        ".dockerignore must exclude archive/"
    )
    with (_ROOT / "pyproject.toml").open("rb") as handle:
        extend_exclude = tomllib.load(handle)["tool"]["ruff"]["extend-exclude"]
    assert "archive/**" in extend_exclude


def test_compose_core_mounts_no_mission_or_attestation_inputs() -> None:
    assert "./signing-keys:/var/lib/ksi/signing-keys:ro" not in _COMPOSE
    assert (
        "./device-attestation-keys.json:/var/lib/ksi/device-attestation-keys.json:ro"
        not in _COMPOSE
    )
    assert "KSI_CORE_SIGNING_KEYS_DIR" not in _COMPOSE
    assert "device-attestation-keys" not in _COMPOSE
    # The platform boot still needs its ledger, env file, healthcheck and ports.
    assert "ksi-data:/var/lib/ksi/data" in _COMPOSE
    assert "env_file: ${KSI_DEPLOY_ENV_FILE:-.env}" in _COMPOSE
    assert "127.0.0.1:8000:8000" in _COMPOSE
    assert "/ready" in _COMPOSE


def test_platform_factory_exists_and_legacy_stays_importable() -> None:
    """P3 Task 5: the legacy managed factory retired to the archive boundary."""
    import importlib.util

    from ksi_core.composition import platform_production

    assert callable(platform_production.build_platform_production_app)
    assert importlib.util.find_spec("ksi_core.production") is None
    try:
        importlib.import_module("ksi_core.production")
    except ModuleNotFoundError:
        pass
    else:
        raise AssertionError("ksi_core.production still imports from the active tree")
