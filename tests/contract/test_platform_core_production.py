"""Fail-closed platform Core production boot (Task 3).

``build_platform_production_app`` is the explicit production entrypoint for the
external-only platform profile: it boots from environment configuration with an
existing data directory, S3 endpoint/bucket and principal digest/OIDC
configuration — but never a Mission signing key directory or a device
attestation file. Every required fact is validated before any S3 client is
created or any journal is opened; opened journals are closed on every failure
path.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
from fastapi.testclient import TestClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "services/core/src",
    REPOSITORY_ROOT / "packages/event-contracts/src",
    REPOSITORY_ROOT / "packages/domain/src",
    REPOSITORY_ROOT / "packages/geo-core/src",
    REPOSITORY_ROOT / "packages/mission-contracts/src",
    REPOSITORY_ROOT / "packages/mission-planning/src",
)

_DENIED_PREFIXES = (
    "ksi_core.acquisition",
    "ksi_mission_contracts",
    "ksi_mission_planning",
    "ksi_core.capability",
    "ksi_core.device_attestation",
    "ksi_core.copilot",
    "ksi_core.copilot_conversations",
    "ksi_core.copilot_openai",
    "ksi_core.composition.assembly",
    "ksi_core.composition.base_graph",
)

_MOVED_HELPERS = (
    "_require_env",
    "_require_dir",
    "_optional_positive_env",
    "_human_auth_config_env",
    "_parse_principal_tokens",
    "_expose_docs_env",
    "_external_authority_paths_env",
    "_analysis_activation_paths_env",
)

_PLATFORM_REQUIRED_ENV = (
    "KSI_CORE_DATA_DIR",
    "KSI_CORE_S3_ENDPOINT",
    "KSI_CORE_S3_BUCKET",
    "KSI_CORE_PRINCIPAL_TOKENS_JSON",
)


def _platform_env(tmp_path: Path) -> dict[str, str]:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    tokens = [
        {
            "tokenSha256": hashlib.sha256(b"platform-prod-admin-token").hexdigest(),
            "principalId": "platform-prod-admin",
            "kind": "OPERATOR",
            "role": "ADMIN",
            "deviceId": None,
        }
    ]
    return {
        "KSI_CORE_DATA_DIR": str(data_dir),
        "KSI_CORE_S3_ENDPOINT": "http://127.0.0.1:9000",
        "KSI_CORE_S3_BUCKET": "platform-prod-evidence",
        "KSI_CORE_PRINCIPAL_TOKENS_JSON": json.dumps(tokens),
    }


def _apply_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def _run_python(script: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(root) for root in SOURCE_ROOTS] + ([existing] if existing else [])
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=180,
    )


def _blocker_prelude(denied: tuple[str, ...]) -> str:
    return dedent(
        """
            import sys

            _DENIED_PREFIXES = %r

            class _DenyPrefixes:
                def find_module(self, name, path=None):
                    if name in _DENIED_PREFIXES or any(
                        name.startswith(prefix + ".") for prefix in _DENIED_PREFIXES
                    ):
                        raise ImportError(f"platform isolation probe denies {name}")
                    return None

            sys.meta_path.insert(0, _DenyPrefixes())
            for _module in list(sys.modules):
                assert _module not in _DENIED_PREFIXES and not any(
                    _module.startswith(prefix + ".") for prefix in _DENIED_PREFIXES
                ), _module
            """
    ) % (denied,)


# ── 1. Exact helper relocation preserves function identity ───────────────────


def test_moved_helpers_keep_exact_function_identity() -> None:
    """Old import paths still resolve to the very same function objects."""
    from ksi_core.composition import assembly as assembly_module
    from ksi_core.composition import production_config as production_config_module
    from ksi_core.composition import runtime_config as runtime_config_module
    from ksi_core.foundation import config_values as config_values_module

    for name in _MOVED_HELPERS:
        relocated = getattr(runtime_config_module, name)
        legacy = getattr(production_config_module, name)
        assert legacy is relocated, name
    assert assembly_module.cli_optional_positive is config_values_module.cli_optional_positive
    assert production_config_module._JOURNAL_SEGMENT_BYTES_DEFAULT == (
        runtime_config_module._JOURNAL_SEGMENT_BYTES_DEFAULT
    )
    assert production_config_module._EDGE_SYNC_SNAPSHOT_EVERY_DEFAULT == (
        runtime_config_module._EDGE_SYNC_SNAPSHOT_EVERY_DEFAULT
    )


def test_cli_optional_positive_keeps_exact_contract() -> None:
    from ksi_core.foundation.config_values import cli_optional_positive

    assert cli_optional_positive(0, name="--x") is None
    assert cli_optional_positive(7, name="--x") == 7
    with pytest.raises(ValueError, match="--x"):
        cli_optional_positive(-1, name="--x")


# ── 2. Missing/malformed required facts fail closed before side effects ──────


@pytest.mark.parametrize("missing", _PLATFORM_REQUIRED_ENV)
def test_platform_missing_required_env_raises_runtime_error(
    missing: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    env = _platform_env(tmp_path)
    del env[missing]
    _apply_env(monkeypatch, env)
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(RuntimeError, match=missing):
        build_platform_production_app()


def test_platform_missing_env_fails_before_clients_and_journals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validation precedes S3 client creation and journal opens alike."""
    import ksi_core.evidence_s3 as evidence_s3_module
    from ksi_core.composition.platform_production import build_platform_production_app

    created: list[str] = []
    original = evidence_s3_module.S3EvidenceStorage

    def _spy(*args: Any, **kwargs: Any) -> Any:
        created.append("S3EvidenceStorage")
        return original(*args, **kwargs)

    env = _platform_env(tmp_path)
    del env["KSI_CORE_S3_BUCKET"]
    _apply_env(monkeypatch, env)
    monkeypatch.delenv("KSI_CORE_S3_BUCKET", raising=False)
    monkeypatch.setattr(evidence_s3_module, "S3EvidenceStorage", _spy)

    with pytest.raises(RuntimeError, match="KSI_CORE_S3_BUCKET"):
        build_platform_production_app()
    assert created == []
    assert list(Path(env["KSI_CORE_DATA_DIR"]).iterdir()) == []


def test_platform_rejects_missing_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    env = _platform_env(tmp_path)
    env["KSI_CORE_DATA_DIR"] = str(tmp_path / "absent-data-dir")
    _apply_env(monkeypatch, env)

    with pytest.raises(RuntimeError, match="KSI_CORE_DATA_DIR"):
        build_platform_production_app()


def test_platform_rejects_malformed_principal_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    env = _platform_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = "not-json"
    _apply_env(monkeypatch, env)
    with pytest.raises(RuntimeError, match="KSI_CORE_PRINCIPAL_TOKENS_JSON"):
        build_platform_production_app()

    env = _platform_env(tmp_path / "plaintext")
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(
        [
            {
                "tokenSha256": "platform-prod-admin-token",
                "principalId": "p1",
                "kind": "OPERATOR",
                "role": "ADMIN",
                "deviceId": None,
            }
        ]
    )
    _apply_env(monkeypatch, env)
    with pytest.raises(RuntimeError, match="KSI_CORE_PRINCIPAL_TOKENS_JSON"):
        build_platform_production_app()


def test_platform_rejects_unknown_principal_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    env = _platform_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(
        [
            {
                "tokenSha256": hashlib.sha256(b"x").hexdigest(),
                "principalId": "p1",
                "kind": "NOT_A_KIND",
                "role": None,
                "deviceId": None,
            }
        ]
    )
    _apply_env(monkeypatch, env)

    with pytest.raises(RuntimeError):
        build_platform_production_app()


# ── 3. OIDC trust vectors ─────────────────────────────────────────────────────


def test_platform_oidc_rejects_unknown_mode_and_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ksi_core.composition.runtime_config import _human_auth_config_env

    monkeypatch.setenv("KSI_CORE_HUMAN_AUTH_MODE", "MAYBE")
    with pytest.raises(RuntimeError, match="OPAQUE, DUAL, OIDC"):
        _human_auth_config_env()

    monkeypatch.setenv("KSI_CORE_HUMAN_AUTH_MODE", "OIDC")
    monkeypatch.setenv("KSI_CORE_OIDC_ISSUER", "https://issuer.example.test")
    monkeypatch.setenv("KSI_CORE_OIDC_AUDIENCE", "ksi-core")
    monkeypatch.setenv("KSI_CORE_OIDC_JWKS_URL", "https://issuer.example.test/jwks.json")
    monkeypatch.setenv("KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE", "/tmp/subjects.json")
    monkeypatch.setenv("KSI_CORE_OIDC_ALLOWED_ALGORITHMS", "none")
    with pytest.raises(RuntimeError, match="RS256, ES256"):
        _human_auth_config_env()


@pytest.mark.parametrize("missing", ["KSI_CORE_OIDC_ISSUER", "KSI_CORE_OIDC_AUDIENCE"])
def test_platform_oidc_requires_all_verification_inputs(
    missing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.composition.runtime_config import _human_auth_config_env

    monkeypatch.setenv("KSI_CORE_HUMAN_AUTH_MODE", "OIDC")
    monkeypatch.setenv("KSI_CORE_OIDC_ISSUER", "https://issuer.example.test")
    monkeypatch.setenv("KSI_CORE_OIDC_AUDIENCE", "ksi-core")
    monkeypatch.setenv("KSI_CORE_OIDC_JWKS_URL", "https://issuer.example.test/jwks.json")
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(RuntimeError, match=missing):
        _human_auth_config_env()


def test_platform_dual_rejects_oidc_subject_collision_with_opaque(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    env = _platform_env(tmp_path)
    subject_path = tmp_path / "oidc-subjects.json"
    subject_path.write_text(
        json.dumps(
            {
                "version": "oidc-subject-registry.v1",
                "subjects": [
                    {
                        "issuer": "https://issuer.example.test",
                        "subject": "provider-subject-1",
                        "principalId": "platform-prod-admin",
                        "organizationId": "org-collision",
                        "role": "ADMIN",
                        "status": "ACTIVE",
                        "allowedSiteIds": [],
                        "allowedWorkAreaIds": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    subject_path.chmod(0o600)
    env.update(
        {
            "KSI_CORE_HUMAN_AUTH_MODE": "DUAL",
            "KSI_CORE_OIDC_ISSUER": "https://issuer.example.test",
            "KSI_CORE_OIDC_AUDIENCE": "ksi-core",
            "KSI_CORE_OIDC_JWKS_URL": "https://issuer.example.test/jwks.json",
            "KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE": str(subject_path),
        }
    )
    _apply_env(monkeypatch, env)

    with pytest.raises(RuntimeError, match="OIDC.*opaque.*principalId"):
        build_platform_production_app()
    assert list(Path(env["KSI_CORE_DATA_DIR"]).iterdir()) == []


# ── 4. Signed Analysis trio and external authority pair semantics ─────────────


def test_platform_rejects_partial_analysis_activation_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    env = _platform_env(tmp_path)
    env["KSI_CORE_ANALYSIS_ACTIVATION_FILE"] = str(tmp_path / "activation.json")
    _apply_env(monkeypatch, env)

    with pytest.raises(RuntimeError, match="requires all three explicit file paths"):
        build_platform_production_app()


def test_platform_rejects_partial_external_authority_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    env = _platform_env(tmp_path)
    env["KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG"] = str(tmp_path / "workflow.json")
    _apply_env(monkeypatch, env)
    monkeypatch.delenv("KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG", raising=False)

    with pytest.raises(RuntimeError, match="configured together"):
        build_platform_production_app()


def test_platform_rejects_relative_external_authority_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    env = _platform_env(tmp_path)
    env["KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG"] = "relative/workflow.json"
    env["KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG"] = str(tmp_path / "provider.json")
    _apply_env(monkeypatch, env)

    with pytest.raises(RuntimeError, match="absolute protected"):
        build_platform_production_app()


def test_expired_authority_snapshot_stays_blocked_not_activated(
    tmp_path: Path,
) -> None:
    """The platform factory's ``allow_expired`` reuse never becomes fail-open:
    an expired snapshot loads for historical reads but reports BLOCKED."""
    from ksi_core.external_authority_provider import load_external_authority_provider
    from test_external_authority_provider_contract import NOW, _provider_config

    expired = load_external_authority_provider(
        _provider_config(tmp_path),
        clock=lambda: NOW + timedelta(hours=2),
        allow_expired=True,
    )
    status = expired.status()
    assert status["status"] == "BLOCKED"
    assert status.get("businessEligible", False) is False
    assert expired.participants is not None


def test_platform_expired_activation_keeps_history_but_denies_new_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from ksi_core.composition.platform_production import build_platform_production_app
    from test_production_assembly import _enable_analysis_activation

    env = _platform_env(tmp_path)
    _enable_analysis_activation(
        tmp_path,
        env,
        activation_fields={
            "issuedAt": (datetime.now(UTC) - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            "validUntil": (datetime.now(UTC) - timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z"),
        },
    )
    _apply_env(monkeypatch, env)

    app = build_platform_production_app()
    paths = set(app.openapi()["paths"])
    assert "/v1/sites/{site_id}/analyses/{analysis_id}/result" in paths
    client = TestClient(app)
    read = client.get(
        "/v1/sites/site-a/analyses/historical-result-id/result",
        headers={"Authorization": "Bearer platform-prod-admin-token"},
    )
    create = client.post(
        "/v1/sites/site-a/work-areas/area-a/analyses",
        headers={
            "Authorization": "Bearer platform-prod-admin-token",
            "Idempotency-Key": "platform-expired-create",
        },
        json={
            "baseline": {
                "workOrderId": "work-order-a",
                "submissionRef": "ers-v1-" + "a" * 64,
                "revision": 1,
            },
            "current": {
                "workOrderId": "work-order-b",
                "submissionRef": "ers-v1-" + "b" * 64,
                "revision": 1,
            },
        },
    )
    assert read.status_code == 404  # The historical read route remains available.
    assert create.status_code == 503
    assert create.json()["detail"] == "ANALYSIS_ACTIVATION_EXPIRED"


# ── 5. Failure paths release every opened journal ────────────────────────────


def test_platform_failure_after_journal_open_closes_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raise inside graph assembly must not leave journals locked."""
    from ksi_core.composition import platform_production as platform_production_module
    from ksi_core.composition.platform_production import build_platform_production_app
    from ksi_core.durable_journal import DurableJournal

    _apply_env(monkeypatch, _platform_env(tmp_path))

    def _flaky_assemble(*args: Any, **kwargs: Any) -> Any:
        kwargs["journal"]("sites.jsonl")
        raise RuntimeError("injected assembly failure after journal open")

    monkeypatch.setattr(platform_production_module, "assemble_platform_app", _flaky_assemble)
    with pytest.raises(RuntimeError, match="injected assembly failure"):
        build_platform_production_app()

    check = DurableJournal(tmp_path / "data" / "sites.jsonl")
    try:
        check.append({"probe": "lock-released"})
    finally:
        check.close()


# ── 6. Boot without flight credentials; no flight surface ────────────────────


def test_platform_boot_needs_no_mission_key_or_device_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    _apply_env(monkeypatch, _platform_env(tmp_path))
    monkeypatch.delenv("KSI_CORE_SIGNING_KEYS_DIR", raising=False)
    monkeypatch.delenv("KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE", raising=False)

    app = build_platform_production_app()
    client = TestClient(app)
    response = client.get(
        "/v1/auth/whoami",
        headers={"Authorization": "Bearer platform-prod-admin-token"},
    )
    assert response.status_code == 200
    assert response.json()["principalId"] == "platform-prod-admin"
    paths = set(app.openapi()["paths"])
    assert "/v1/sites/{site_id}/observation-work-orders" in paths
    assert not any(path.startswith("/v1/missions") for path in paths)
    assert "/capabilities" not in paths


def test_platform_expose_docs_defaults_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    _apply_env(monkeypatch, _platform_env(tmp_path))
    monkeypatch.delenv("KSI_CORE_EXPOSE_DOCS", raising=False)
    app = build_platform_production_app()
    assert TestClient(app).get("/docs").status_code == 404


def test_platform_boot_imports_no_flight_or_legacy_assembly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fresh-process proof: env-only boot with owner-protected generated config."""
    env = _platform_env(tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("KSI_CORE_SIGNING_KEYS_DIR", raising=False)
    monkeypatch.delenv("KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE", raising=False)
    monkeypatch.delenv("KSI_CORE_HUMAN_AUTH_MODE", raising=False)

    script = _blocker_prelude(_DENIED_PREFIXES) + dedent(
        """
        import sys

        from ksi_core.composition.platform_production import (
            build_platform_production_app,
        )

        denied = %r

        def _walk_routes(container):
            found = []
            for route in getattr(container, "routes", None) or []:
                if getattr(route, "methods", None) and getattr(route, "path", None):
                    found.append(route)
                inner = getattr(route, "original_router", None)
                if inner is not None:
                    found.extend(_walk_routes(inner))
            return found

        app = build_platform_production_app()
        paths = sorted({route.path for route in _walk_routes(app)})
        assert "/v1/sites/{site_id}/observation-work-orders" in paths
        assert "/capabilities" not in paths
        assert not any(path.startswith("/v1/missions") for path in paths)
        assert not any("flight" in path for path in paths)
        for name in denied:
            assert name not in sys.modules, name
            assert not any(
                module == name or module.startswith(name + ".") for module in sys.modules
            ), name
        """
    ) % (_DENIED_PREFIXES,)
    completed = _run_python(script)
    assert completed.returncode == 0, completed.stdout + completed.stderr
