"""Production parser and deploy example must describe the same Core boundary."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION = (_ROOT / "services" / "core" / "src" / "ksi_core" / "production.py").read_text(
    encoding="utf-8"
)
_ENV_EXAMPLE = (_ROOT / "deploy" / ".env.example").read_text(encoding="utf-8")
_COMPOSE = (_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")


def _core_env_names(text: str) -> set[str]:
    return set(re.findall(r"KSI_CORE_[A-Z0-9_]+", text))


def test_every_production_core_env_is_documented_in_deploy_example() -> None:
    production_names = _core_env_names(_PRODUCTION)
    example_names = _core_env_names(_ENV_EXAMPLE)
    assert production_names <= example_names, (
        "production.py에만 있고 deploy/.env.example에 없는 변수: "
        + ", ".join(sorted(production_names - example_names))
    )


def test_rc_first_safe_defaults_and_principal_kinds_are_explicit() -> None:
    assert "KSI_CORE_ACQUISITION_COORDINATION_ENABLED=true" in _ENV_EXAMPLE
    assert "KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED=false" in _ENV_EXAMPLE
    assert "KSI_CORE_MISSION_CONTRACT_WRITER_VERSION=1.2" in _ENV_EXAMPLE
    assert '"organizationId":"org-pilot-1"' in _ENV_EXAMPLE
    for kind in ("OPERATOR", "GATEWAY_DEVICE", "EDGE_DEVICE", "PROCESSING_WORKER"):
        assert f'"kind":"{kind}"' in _ENV_EXAMPLE


def test_attestation_manifest_is_required_and_mounted_read_only() -> None:
    assert (
        "KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE=/var/lib/ksi/device-attestation-keys.json"
        in _ENV_EXAMPLE
    )
    assert "./device-attestation-keys.json:/var/lib/ksi/device-attestation-keys.json:ro" in _COMPOSE
    example = _ROOT / "deploy" / "device-attestation-keys.example.json"
    assert example.read_text(encoding="utf-8").strip() == '{\n  "keys": []\n}'


def test_deploy_does_not_claim_an_unverified_gateway_runtime() -> None:
    assert "dji-gateway:" not in _COMPOSE
    assert "capability는 모두 NOT_VERIFIED" in _COMPOSE
