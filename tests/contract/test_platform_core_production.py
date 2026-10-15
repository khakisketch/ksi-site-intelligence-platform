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
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
from fastapi.testclient import TestClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
# P3 Task 6: archived mission-package roots dropped from the probe path.
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "services/core/src",
    REPOSITORY_ROOT / "packages/event-contracts/src",
    REPOSITORY_ROOT / "packages/domain/src",
    REPOSITORY_ROOT / "packages/geo-core/src",
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


# ── 1. Staying helper relocation preserves function identity ──────────────────


def test_moved_helpers_keep_exact_function_identity() -> None:
    """The staying platform config still resolves to the very same function objects."""
    # P3 Task 5: the legacy production_config/assembly half of this comparison
    # retired to archive/acquisition-2026/ (archive-internal per the T3
    # precedent). The platform half keeps proving exact identity against the
    # neutral foundation owner.
    from ksi_core.composition import runtime_config as runtime_config_module
    from ksi_core.foundation import config_values as config_values_module

    assert runtime_config_module.cli_optional_positive is (
        config_values_module.cli_optional_positive
    )
    assert runtime_config_module._JOURNAL_SEGMENT_BYTES_DEFAULT == 64 * 1024 * 1024
    assert runtime_config_module._EDGE_SYNC_SNAPSHOT_EVERY_DEFAULT == 500


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


def test_platform_v2_registry_boot_and_site_bootstrap_cap_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-01 배선: v2 registry 로드, 상한 환경변수 fail-closed, 부수효과 순서."""
    from ksi_core.composition.platform_production import build_platform_production_app

    env = _platform_env(tmp_path)
    subject_path = tmp_path / "oidc-subjects-v2.json"
    valid_row = {
        "issuer": "https://issuer.example.test",
        "subject": "provider-subject-2",
        "principalId": "pilot-oidc-admin",
        "organizationId": "org-pilot",
        "role": "ADMIN",
        "status": "ACTIVE",
        "capabilities": ["SITE_BOOTSTRAP"],
        "allowedSiteIds": None,
        "allowedWorkAreaIds": None,
    }
    subject_path.write_text(
        json.dumps(
            {
                "version": "oidc-subject-registry.v2",
                "subjects": [
                    {key: value for key, value in valid_row.items() if key != "capabilities"}
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

    # v2 필수 필드(capabilities) 누락은 로드 실패이고, 무거운 부수효과
    # (S3 client·journal open) 전에 끝난다.
    with pytest.raises(RuntimeError, match="OIDC subject registry is invalid"):
        build_platform_production_app()
    assert list(Path(env["KSI_CORE_DATA_DIR"]).iterdir()) == []

    subject_path.write_text(
        json.dumps({"version": "oidc-subject-registry.v2", "subjects": [valid_row]}),
        encoding="utf-8",
    )
    subject_path.chmod(0o600)

    # 상한 환경변수: 0·음수·비정수는 부팅 실패다(조용한 기본값 금지).
    for invalid in ("0", "-1", "many"):
        monkeypatch.setenv("KSI_CORE_SITE_BOOTSTRAP_MAX_SITES_PER_ORG", invalid)
        with pytest.raises(
            RuntimeError, match="KSI_CORE_SITE_BOOTSTRAP_MAX_SITES_PER_ORG"
        ):
            build_platform_production_app()
    monkeypatch.delenv("KSI_CORE_SITE_BOOTSTRAP_MAX_SITES_PER_ORG", raising=False)

    app = build_platform_production_app()
    assert app.state.oidc_verifier is not None
    assert app.state.site_store._max_bootstrap_sites_per_org == 1000


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
    """The platform factory's ``allow_out_of_window`` reuse never becomes fail-open:
    an expired snapshot loads for historical reads but reports BLOCKED."""
    from ksi_core.external_authority_provider import load_external_authority_provider

    # P3 Task 5: inlined from test_external_authority_provider_contract
    # (archived with the legacy assembly it is built on). Produces the exact
    # default snapshot/config files that helper wrote.
    expired = load_external_authority_provider(
        _expired_snapshot_config(tmp_path),
        clock=lambda: _EXPIRED_NOW + timedelta(hours=2),
        allow_out_of_window=True,
    )
    status = expired.status()
    assert status["status"] == "BLOCKED"
    assert status.get("businessEligible", False) is False
    assert expired.participants is not None


def test_not_yet_effective_authority_snapshot_stays_blocked_not_activated(
    tmp_path: Path,
) -> None:
    """A staged snapshot signed ahead of its window loads blocked, never activated:

    the symmetric partner of the expired direction at the provider-loader level
    - the signed history and the workflow graph stay available, and in the
    attached production graph every live port stays closed until a current
    signed snapshot is explicitly reloaded (the window opening alone does not
    clear the block). A fully staged future snapshot boots the whole production
    factory the same way; see
    test_factory_boots_blocked_for_a_staged_future_authority_snapshot."""
    from ksi_core.external_authority_provider import load_external_authority_provider

    provider = load_external_authority_provider(
        _expired_snapshot_config(
            tmp_path,
            issued_at="2026-09-11T05:00:00Z",
            valid_until="2026-09-11T06:00:00Z",
        ),
        clock=lambda: _EXPIRED_NOW,
        allow_out_of_window=True,
    )
    status = provider.status()
    assert status["status"] == "BLOCKED"
    assert status.get("businessEligible", False) is False
    assert provider.participants is not None


def test_staged_snapshot_authorizes_its_catalog_binding_for_the_degraded_boot(
    tmp_path: Path,
) -> None:
    """Both out-of-window directions authorize the catalog binding structurally.

    A not-yet-effective staged snapshot (and, unchanged, an expired one) answers
    the workflow-configuration binding check from its signed record while every
    live port stays blocked; an in-window snapshot defers to the live
    resolution path instead."""
    from datetime import UTC, datetime, timedelta

    from ksi_core.external_authority_provider import load_external_authority_provider
    from ksi_core.external_quantitative_authority import (
        ExternalQuantitativeCatalogAuthorityRecord,
    )

    body_digest = "sha256:" + "4" * 64
    record = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id="org-a",
        catalog_body_digest=body_digest,
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=datetime(2026, 9, 10, 0, 0, tzinfo=UTC),
        active_until=datetime(2026, 9, 12, 0, 0, tzinfo=UTC),
        synthetic_test_only=False,
    ).sealed()
    assert record.digest is not None
    config = _expired_snapshot_config(
        tmp_path,
        issued_at="2026-09-11T05:00:00Z",
        valid_until="2026-09-11T06:00:00Z",
        catalog_authority=record,
    )
    provider = load_external_authority_provider(
        config, clock=lambda: _EXPIRED_NOW, allow_out_of_window=True
    )
    assert (
        provider.catalog_configuration_was_authorized(
            authority_record_digest=record.digest,
            catalog_body_digest=body_digest,
            organization_id="org-a",
            administration_actor_id="catalog-admin",
        )
        is True
    )
    # The same snapshot inside its window defers to the live resolution path.
    inside = load_external_authority_provider(
        config,
        clock=lambda: _EXPIRED_NOW + timedelta(hours=5, minutes=30),
        allow_out_of_window=True,
    )
    assert (
        inside.catalog_configuration_was_authorized(
            authority_record_digest=record.digest,
            catalog_body_digest=body_digest,
            organization_id="org-a",
            administration_actor_id="catalog-admin",
        )
        is False
    )
    # A digest the snapshot does not carry stays unauthorised in every direction.
    assert (
        provider.catalog_configuration_was_authorized(
            authority_record_digest="sha256:" + "9" * 64,
            catalog_body_digest=body_digest,
            organization_id="org-a",
            administration_actor_id="catalog-admin",
        )
        is False
    )


def test_factory_boots_blocked_for_an_expired_authority_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A signed-but-expired snapshot no longer stops the production boot.

    The whole factory boots with the workflow graph intact, the provider reports
    BLOCKED with exactly one named startup log line, no receipt is appended, and
    reloading a current signed snapshot (same key) restores PROVIDER_CONFIGURED
    without a restart - the operator recovery path exercised live on 2026-10-15,
    pinned end to end here.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ksi_core.composition.platform_production import build_platform_production_app

    now = datetime.now(UTC).replace(microsecond=0)
    key_not_after = (now + timedelta(days=30)).isoformat().replace("+00:00", "Z")
    workflow_path, record = _approved_workflow_files(
        tmp_path,
        active_from=datetime(2026, 9, 10, tzinfo=UTC),
        active_until=datetime(2026, 9, 12, tzinfo=UTC),
    )
    signer = Ed25519PrivateKey.generate()
    provider_path = _expired_snapshot_config(
        tmp_path, catalog_authority=record, key_not_after=key_not_after, signer=signer
    )
    env = _platform_env(tmp_path)
    env["KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG"] = str(workflow_path)
    env["KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG"] = str(provider_path)
    _apply_env(monkeypatch, env)

    gate_logs = _GateLogs()
    gate_logger = logging.getLogger(
        "ksi_core.domains.external.authority.external_authority_provider"
    )
    gate_logger.addHandler(gate_logs)
    try:
        app = build_platform_production_app()
    finally:
        gate_logger.removeHandler(gate_logs)

    provider = app.state.external_authority_provider
    assert provider.status()["status"] == "BLOCKED"
    blocked = [message for message in gate_logs.messages if "blocked: EXPIRED" in message]
    assert blocked == ["external authority provider blocked: EXPIRED"]
    client = TestClient(app)
    assert client.get("/ready/external-authority").status_code == 503
    receipts_path = tmp_path / "data" / "external-authority-provider-receipts.jsonl"
    assert (receipts_path.read_text() if receipts_path.exists() else "") == ""

    # The operator reissues a current snapshot with the same key and reloads.
    _expired_snapshot_config(
        tmp_path,
        issued_at=(now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        valid_until=(now + timedelta(days=7)).isoformat().replace("+00:00", "Z"),
        catalog_authority=record,
        key_not_after=key_not_after,
        signer=signer,
    )
    result = provider.reload_and_reconcile(now=now)
    assert result["status"] == "PROVIDER_CONFIGURED"
    assert provider.status()["status"] == "PROVIDER_CONFIGURED"
    assert client.get("/ready/external-authority").status_code == 200
    lines = receipts_path.read_text().splitlines() if receipts_path.exists() else []
    assert len(lines) == 1


def test_factory_boots_blocked_for_a_staged_future_authority_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A signed-ahead snapshot with a fully staged workflow boots BLOCKED.

    The workflow-config catalog binding accepts the out-of-window snapshot
    structurally (586d6b0) so the whole factory assembles, while the provider
    stays blocked with exactly one named log line, no receipt and no
    reconciliation.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ksi_core.composition.platform_production import build_platform_production_app

    now = datetime.now(UTC).replace(microsecond=0)
    workflow_path, record = _approved_workflow_files(
        tmp_path,
        active_from=now - timedelta(days=1),
        active_until=now + timedelta(days=10),
    )
    provider_path = _expired_snapshot_config(
        tmp_path,
        issued_at=(now + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
        valid_until=(now + timedelta(days=5)).isoformat().replace("+00:00", "Z"),
        catalog_authority=record,
        key_not_before=(now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
        key_not_after=(now + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        signer=Ed25519PrivateKey.generate(),
    )
    env = _platform_env(tmp_path)
    env["KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG"] = str(workflow_path)
    env["KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG"] = str(provider_path)
    _apply_env(monkeypatch, env)

    gate_logs = _GateLogs()
    gate_logger = logging.getLogger(
        "ksi_core.domains.external.authority.external_authority_provider"
    )
    gate_logger.addHandler(gate_logs)
    try:
        app = build_platform_production_app()
    finally:
        gate_logger.removeHandler(gate_logs)

    provider = app.state.external_authority_provider
    assert provider.status()["status"] == "BLOCKED"
    captured_lines = [
        message for message in gate_logs.messages if "blocked: NOT_YET_EFFECTIVE" in message
    ]
    assert captured_lines == [
        "external authority provider blocked: NOT_YET_EFFECTIVE"
    ]
    assert TestClient(app).get("/ready/external-authority").status_code == 503
    receipts_path = tmp_path / "data" / "external-authority-provider-receipts.jsonl"
    assert (receipts_path.read_text() if receipts_path.exists() else "") == ""


def test_factory_refuses_a_tampered_authority_snapshot_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Signature tamper stays fatal for the whole boot (structure gate)."""
    import base64

    from ksi_core.composition.platform_production import build_platform_production_app
    from ksi_core.external_authority_provider import (
        ExternalAuthorityProviderError,
        load_external_authority_provider,
    )

    workflow_path, record = _approved_workflow_files(
        tmp_path,
        active_from=datetime(2026, 9, 10, tzinfo=UTC),
        active_until=datetime(2026, 9, 12, tzinfo=UTC),
    )
    provider_path = _expired_snapshot_config(tmp_path, catalog_authority=record)
    snapshot_path = tmp_path / "authority-snapshot.json"
    payload = json.loads(snapshot_path.read_text())
    signature = bytearray(base64.b64decode(payload["signature"]))
    signature[0] ^= 0x01
    payload["signature"] = base64.b64encode(bytes(signature)).decode("ascii")
    _write_provider_file(snapshot_path, payload)

    env = _platform_env(tmp_path)
    env["KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG"] = str(workflow_path)
    env["KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG"] = str(provider_path)
    _apply_env(monkeypatch, env)

    with pytest.raises(
        ExternalAuthorityProviderError, match="external authority provider is blocked"
    ):
        build_platform_production_app()
    with pytest.raises(ExternalAuthorityProviderError) as captured:
        load_external_authority_provider(
            provider_path, clock=lambda: datetime.now(UTC), allow_out_of_window=True
        )
    assert isinstance(captured.value.__cause__, ValueError)
    assert "signature is invalid" in str(captured.value.__cause__)


def test_factory_boots_blocked_when_the_signing_key_window_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The signing-key window is a time gate, not a structure failure.

    A snapshot still inside its own window whose declared key interval has
    ended loads for the degraded boot (the declared signing time is inside the
    key interval) and the provider reports BLOCKED naming EXPIRED, exactly
    like the expired-snapshot direction. Without ``allow_out_of_window`` (the
    reload path) the same inputs stay fatal, so a running Core never reconciles
    or receipts key-ended authority.
    """
    from ksi_core.composition.platform_production import build_platform_production_app
    from ksi_core.external_authority_provider import (
        ExternalAuthorityProviderError,
        load_external_authority_provider,
    )

    now = datetime.now(UTC).replace(microsecond=0)

    def iso(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    workflow_path, record = _approved_workflow_files(
        tmp_path,
        active_from=now - timedelta(days=3),
        active_until=now + timedelta(days=30),
    )
    provider_path = _expired_snapshot_config(
        tmp_path,
        issued_at=iso(now - timedelta(hours=2)),
        valid_until=iso(now + timedelta(days=5)),
        catalog_authority=record,
        key_not_before=iso(now - timedelta(days=3)),
        key_not_after=iso(now - timedelta(hours=1)),
    )
    env = _platform_env(tmp_path)
    env["KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG"] = str(workflow_path)
    env["KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG"] = str(provider_path)
    _apply_env(monkeypatch, env)

    gate_logs = _GateLogs()
    gate_logger = logging.getLogger(
        "ksi_core.domains.external.authority.external_authority_provider"
    )
    gate_logger.addHandler(gate_logs)
    try:
        app = build_platform_production_app()
    finally:
        gate_logger.removeHandler(gate_logs)

    provider = app.state.external_authority_provider
    assert provider.status()["status"] == "BLOCKED"
    blocked = [message for message in gate_logs.messages if "blocked: EXPIRED" in message]
    assert blocked == ["external authority provider blocked: EXPIRED"]
    assert TestClient(app).get("/ready/external-authority").status_code == 503
    receipts_path = tmp_path / "data" / "external-authority-provider-receipts.jsonl"
    assert (receipts_path.read_text() if receipts_path.exists() else "") == ""

    with pytest.raises(
        ExternalAuthorityProviderError, match="external authority provider is blocked"
    ):
        load_external_authority_provider(
            provider_path, clock=lambda: datetime.now(UTC), allow_out_of_window=False
        )


def test_loader_rejects_a_snapshot_signed_before_its_key_window(tmp_path: Path) -> None:
    """A declared signing time before the key's own interval is impossible.

    This is deliberately fatal in every mode (structure gate): no window
    direction can admit a signature that the declared key facts say could not
    have been produced.
    """
    from ksi_core.external_authority_provider import (
        ExternalAuthorityProviderError,
        load_external_authority_provider,
    )

    now = datetime.now(UTC).replace(microsecond=0)

    def iso(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    provider_path = _expired_snapshot_config(
        tmp_path,
        issued_at=iso(now - timedelta(hours=2)),
        valid_until=iso(now + timedelta(days=5)),
        key_not_before=iso(now - timedelta(hours=1)),
        key_not_after=iso(now + timedelta(days=5)),
    )
    with pytest.raises(ExternalAuthorityProviderError) as captured:
        load_external_authority_provider(
            provider_path, clock=lambda: datetime.now(UTC), allow_out_of_window=True
        )
    assert isinstance(captured.value.__cause__, ValueError)
    assert "key is outside its validity interval" in str(captured.value.__cause__)


def test_platform_expired_activation_keeps_history_but_denies_new_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from ksi_core.composition.platform_production import build_platform_production_app

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


# ── 4b. Retired-helper inlines (P3 Task 5 ownership) ─────────────────────────
# The two tests below previously imported helpers from test files that retired
# to archive/acquisition-2026/ with the legacy assembly they are built on
# (test_external_authority_provider_contract,
# test_production_assembly::_enable_analysis_activation). The helpers are
# inlined here verbatim against staying modules so the platform-factory gates
# keep proving the same behavior with no archived dependency.

_EXPIRED_NOW = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)


class _GateLogs(logging.Handler):
    """Collects gate-log messages on one logger.

    ``build_platform_production_app`` installs structured logging on the root
    logger and removes existing root handlers, so caplog cannot observe these
    startup lines; a handler attached to the emitting logger survives that
    reconfiguration and pins the "exactly one named line" contract.
    """

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _write_provider_file(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.chmod(path, 0o600)


def _expired_snapshot_config(
    tmp_path: Path,
    *,
    issued_at: str = "2026-09-11T00:00:00Z",
    valid_until: str = "2026-09-11T01:00:00Z",
    catalog_authority: Any = None,
    key_not_before: str = "2026-09-10T00:00:00Z",
    key_not_after: str = "2026-09-12T00:00:00Z",
    signer: Any = None,
) -> Path:
    """Default authority snapshot/config files (verbatim retired-helper behavior).

    The window and signing-key interval are configurable so the same signed
    fixture can exercise the expired, not-yet-effective and recovered
    generations (a current snapshot needs a key interval covering "now");
    passing the same ``signer`` re-issues with unchanged key material.
    """
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ksi_domain.canonical_json import canonical_json_bytes

    if signer is None:
        signer = Ed25519PrivateKey.generate()
    public_key = tmp_path / "authority-bundle.pem"
    public_key.write_bytes(
        signer.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    os.chmod(public_key, 0o600)
    _write_provider_file(
        tmp_path / "authority-keys.json",
        {
            "version": "external-authority-key-registry.v1",
            "keys": [
                {
                    "keyId": "authority-key-1",
                    "role": "AUTHORITY_BUNDLE",
                    "algorithm": "Ed25519",
                    "status": "ACTIVE",
                    "publicKeyFile": public_key.name,
                    "notBefore": key_not_before,
                    "notAfter": key_not_after,
                }
            ],
        },
    )
    unsigned = {
        "version": "external-authority-provider-snapshot.v1",
        "organizationId": "org-a",
        "sequence": 1,
        "previousSnapshotDigest": None,
        "issuedAt": issued_at,
        "validUntil": valid_until,
        "keyId": "authority-key-1",
        "catalogAuthorities": (
            {
                "records": [catalog_authority.event_payload()],
                "currentDigests": [catalog_authority.digest],
            }
            if catalog_authority is not None
            else {"records": [], "currentDigests": []}
        ),
        "policyAuthorities": {"records": [], "currentDigests": []},
        "evidenceContexts": {"records": [], "currentDigests": []},
        "quantitativeAdministration": {"actions": []},
    }
    signature = signer.sign(
        canonical_json_bytes(
            {
                "domain": "ksi.external-authority-provider-snapshot.v1",
                "snapshot": unsigned,
            }
        )
    )
    _write_provider_file(
        tmp_path / "authority-snapshot.json",
        {**unsigned, "signature": base64.b64encode(signature).decode("ascii")},
    )
    config = tmp_path / "external-authority-provider.json"
    _write_provider_file(
        config,
        {
            "version": "external-authority-provider-config.v1",
            "organizationId": "org-a",
            "keyRegistryPath": str(tmp_path / "authority-keys.json"),
            "snapshotPath": str(tmp_path / "authority-snapshot.json"),
            "catalogAdministrationActorId": "catalog-admin",
            "leaseTtlSeconds": 60,
            "deadlineAfterIssueSeconds": 120,
            "maxAttempts": 3,
            "maxActiveRequestsPerOrganization": 2,
        },
    )
    return config


def _approved_workflow_files(
    tmp_path: Path, *, active_from: datetime, active_until: datetime
) -> tuple[Path, Any]:
    """Approved catalog/workflow pair bound to one synthetic catalog authority.

    Reuses the workflow-loader fixture builders so the catalog admission digest,
    the authority record digest and the workflow's ``authorityRecordDigest`` are
    exactly consistent; the provider snapshot embeds the same record.
    """
    from ksi_core.external_quantitative_authority import (
        ExternalQuantitativeCatalogAuthorityRecord,
    )
    from test_external_result_workflow_config import _catalog_body, _catalog_digest

    admission_body = _catalog_body()
    record = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id="org-a",
        catalog_body_digest=_catalog_digest(admission_body),
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=active_from,
        active_until=active_until,
        synthetic_test_only=False,
    ).sealed()
    assert record.digest is not None
    catalog_path = tmp_path / "catalog.json"
    _write_provider_file(
        catalog_path,
        {
            "version": "external-quantitative-catalog.v1",
            "authorityRecordDigest": record.digest,
            "body": _catalog_body(record.digest),
        },
    )
    workflow_path = tmp_path / "workflow.json"
    _write_provider_file(
        workflow_path,
        {
            "version": "external-result-workflow-config.v1",
            "authorityJournalPath": str(tmp_path / "authority.jsonl"),
            "catalogPath": str(catalog_path),
        },
    )
    return workflow_path, record


def _enable_analysis_activation(
    tmp_path: Path,
    env: dict[str, str],
    *,
    activation_fields: dict[str, object] | None = None,
    add_ambiguous_worker: bool = False,
) -> tuple[Any, Any]:
    """Retired-helper inline (verbatim behavior, staying modules only)."""
    from datetime import UTC, datetime, timedelta

    from test_external_analysis_activation import _bindings, _write_activation

    bindings = _bindings()
    tokens = json.loads(env["KSI_CORE_PRINCIPAL_TOKENS_JSON"])
    tokens.append(
        {
            "tokenSha256": hashlib.sha256(b"analysis-worker-test-token").hexdigest(),
            "principalId": bindings["worker_principal"].principal_id,
            "kind": "ANALYSIS_WORKER",
            "role": None,
            "deviceId": None,
            "organizationId": bindings["organization_id"],
        }
    )
    if add_ambiguous_worker:
        tokens.append(
            {
                "tokenSha256": hashlib.sha256(b"analysis-worker-test-token-b").hexdigest(),
                "principalId": "analysis-worker-b",
                "kind": "ANALYSIS_WORKER",
                "role": None,
                "deviceId": None,
                "organizationId": bindings["organization_id"],
            }
        )
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(tokens)

    runtime = bindings["runtime"]
    policy = bindings["policy"]
    envelope = bindings["resource_envelope"]
    runtime_config = tmp_path / "local-analysis-runtime.json"
    runtime_config.write_text(
        json.dumps(
            {
                "version": "local-analysis-runtime.v1",
                "policy": policy.model_dump(by_alias=True, mode="json"),
                "runtime": {
                    "workerExecutableDigest": runtime.worker_executable_digest,
                    "workerBuildDigest": runtime.worker_build_digest,
                    "runtimeImageVersion": runtime.runtime_image_version,
                    "runtimeImageOciDigest": runtime.runtime_image_oci_digest,
                    "dependencyLockDigest": runtime.dependency_lock_digest,
                },
                "resourceEnvelope": envelope.model_dump(by_alias=True, mode="json"),
            }
        ),
        encoding="utf-8",
    )
    runtime_config.chmod(0o600)
    activation_dir = tmp_path / "activation"
    activation_dir.mkdir(mode=0o700)
    fields = activation_fields or {
        "issuedAt": (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace(
            "+00:00", "Z"
        ),
        "validUntil": (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z"
        ),
    }
    activation_path, keys_path, activation = _write_activation(
        activation_dir, bindings=bindings, activation_fields=fields
    )
    env["KSI_CORE_ANALYSIS_RUNTIME_CONFIG_FILE"] = str(runtime_config)
    env["KSI_CORE_ANALYSIS_ACTIVATION_FILE"] = str(activation_path)
    env["KSI_CORE_ANALYSIS_ACTIVATION_KEYS_FILE"] = str(keys_path)
    return activation, bindings


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
