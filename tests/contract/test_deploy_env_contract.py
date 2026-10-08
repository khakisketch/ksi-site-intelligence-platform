"""Platform factory env and deploy example must describe the same Core boundary."""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
# P3 Task 5: the legacy managed factory retired to archive/acquisition-2026/ —
# deploy env is now contracted against the platform factory sources only.
_PLATFORM = (
    _ROOT / "services" / "core" / "src" / "ksi_core" / "composition" / "platform_production.py"
).read_text(encoding="utf-8")
_RUNTIME_CONFIG = (
    _ROOT / "services" / "core" / "src" / "ksi_core" / "composition" / "runtime_config.py"
).read_text(encoding="utf-8")
_ENV_EXAMPLE = (_ROOT / "deploy" / ".env.example").read_text(encoding="utf-8")
_COMPOSE = (_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
_GATEWAY_CONFIG_EXAMPLE = _ROOT / "deploy" / "gateway.config.example.json"

# P3 Task 4: the normal boot profile's ACTUAL env (platform_production.py +
# runtime_config.py). Required always: data dir, S3 endpoint/bucket, principal
# digest list. Conditional: OIDC set (DUAL/OIDC mode). Optional: signed-Analysis
# trio (all-or-none), external-authority pair (both-or-none), plus defaulted
# knobs. NO Mission key dir / device-attestation — those are legacy-only.
_PLATFORM_REQUIRED = {
    "KSI_CORE_DATA_DIR",
    "KSI_CORE_S3_ENDPOINT",
    "KSI_CORE_S3_BUCKET",
    "KSI_CORE_PRINCIPAL_TOKENS_JSON",
}
_PLATFORM_OIDC = {
    "KSI_CORE_HUMAN_AUTH_MODE",
    "KSI_CORE_OIDC_ISSUER",
    "KSI_CORE_OIDC_AUDIENCE",
    "KSI_CORE_OIDC_JWKS_URL",
    "KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE",
    "KSI_CORE_OIDC_ALLOWED_ALGORITHMS",
    "KSI_CORE_OIDC_JWKS_TTL_SECONDS",
}
_PLATFORM_OPTIONAL = {
    "KSI_CORE_LOG_LEVEL",
    "KSI_CORE_S3_PUBLIC_ENDPOINT",
    "KSI_CORE_JOURNAL_SEGMENT_BYTES",
    "KSI_CORE_EXPOSE_DOCS",
    "KSI_CORE_ANALYSIS_RUNTIME_CONFIG_FILE",
    "KSI_CORE_ANALYSIS_ACTIVATION_FILE",
    "KSI_CORE_ANALYSIS_ACTIVATION_KEYS_FILE",
    "KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG",
    "KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG",
}
_PLATFORM_DENIED = {
    "KSI_CORE_SIGNING_KEYS_DIR",
    "KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE",
}


def _core_env_names(text: str) -> set[str]:
    return set(re.findall(r"KSI_CORE_[A-Z0-9_]+", text))


def test_platform_required_env_is_documented_in_deploy_example() -> None:
    example_names = _core_env_names(_ENV_EXAMPLE)
    assert example_names >= _PLATFORM_REQUIRED, (
        "platform 필수 변수인데 deploy/.env.example에 없는 변수: "
        + ", ".join(sorted(_PLATFORM_REQUIRED - example_names))
    )


def test_platform_optional_env_sets_are_code_ssot() -> None:
    # Fail-closed on factory env drift: every platform env name must be read
    # from exactly one of the two platform sources.
    platform_names = _core_env_names(_PLATFORM) | _core_env_names(_RUNTIME_CONFIG)
    for name in _PLATFORM_REQUIRED | _PLATFORM_OIDC | _PLATFORM_OPTIONAL:
        assert name in platform_names, f"{name} 를 읽는 플랫폼 팩토리 코드가 없다"


def test_platform_never_requires_signing_or_attestation_inputs() -> None:
    for name in _PLATFORM_DENIED:
        assert f'_require_env("{name}")' not in _PLATFORM
        assert f'_require_dir("{name}")' not in _PLATFORM
        assert name not in _RUNTIME_CONFIG, f"platform runtime_config 가 {name} 를 읽는다"


def test_rc_first_safe_defaults_and_principal_kinds_are_explicit() -> None:
    assert "KSI_CORE_ACQUISITION_COORDINATION_ENABLED=true" in _ENV_EXAMPLE
    assert "KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED=false" in _ENV_EXAMPLE
    assert "KSI_CORE_MISSION_CONTRACT_WRITER_VERSION=1.2" in _ENV_EXAMPLE
    assert '"organizationId":"org-pilot-1"' in _ENV_EXAMPLE
    for kind in (
        "OPERATOR",
        "GATEWAY_DEVICE",
        "EDGE_DEVICE",
        "EDGE_ROUTE_OBSERVER",
        "PROCESSING_WORKER",
    ):
        assert f'"kind":"{kind}"' in _ENV_EXAMPLE


def test_platform_compose_mounts_no_signing_or_attestation_inputs() -> None:
    assert "./signing-keys:/var/lib/ksi/signing-keys:ro" not in _COMPOSE
    assert (
        "./device-attestation-keys.json:/var/lib/ksi/device-attestation-keys.json:ro"
        not in _COMPOSE
    )
    assert "ksi-data:/var/lib/ksi/data" in _COMPOSE
    # Legacy factory note (retires in Task 5): the attestation example file
    # stays until the legacy factory is removed; the platform boot just does
    # not mount it.
    example = _ROOT / "deploy" / "device-attestation-keys.example.json"
    assert example.read_text(encoding="utf-8").strip() == '{\n  "keys": []\n}'


def test_deploy_does_not_claim_an_unverified_gateway_runtime() -> None:
    assert "dji-gateway:" not in _COMPOSE
    assert "capability는 모두 NOT_VERIFIED" in _COMPOSE


def test_gateway_example_uses_a_distinct_edge_route_observer_credential() -> None:
    # P3 Task 6: the gateway runner example moved blob-identical to
    # archive/acquisition-2026/deploy/gateway.config.example.json with its
    # subject (the archived dji-gateway service). The credential-separation
    # shape stays pinned against the archived copy — an active-tree test
    # reading a historical example only to prove the archived bytes did not
    # rot (RB-08 explicit record; the live deploy contract no longer covers
    # any gateway runtime).
    archived = _ROOT / "archive" / "acquisition-2026" / "deploy" / "gateway.config.example.json"
    config = json.loads(archived.read_text(encoding="utf-8"))
    core = config["core"]
    assert core["observationTokenFile"] == "/run/secrets/ksi-edge-route-observer-token"
    assert core["observationTokenFile"] != core["preflightTokenFile"]
    assert config["observation"]["producerPrincipalId"] == (
        "replace-with-edge-route-observer-principal"
    )


def test_route_observer_provisioning_is_an_explicit_core_first_activation() -> None:
    principal_records = re.search(r"(?m)^KSI_CORE_PRINCIPAL_TOKENS_JSON=(.+)$", _ENV_EXAMPLE)
    assert principal_records is not None
    default_principals = json.loads(principal_records.group(1))
    assert all(item["kind"] != "EDGE_ROUTE_OBSERVER" for item in default_principals)
    assert "activation-only record" in _ENV_EXAMPLE
