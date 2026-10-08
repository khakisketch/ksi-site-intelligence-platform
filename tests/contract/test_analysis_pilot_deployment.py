from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PILOT_DIR = ROOT / "deploy" / "analysis-pilot"
COMPOSE_PATH = PILOT_DIR / "compose.yaml"
PREFLIGHT_PATH = PILOT_DIR / "preflight.py"

spec = importlib.util.spec_from_file_location("analysis_pilot_preflight", PREFLIGHT_PATH)
assert spec is not None and spec.loader is not None
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def _candidate(tmp_path: Path) -> tuple[dict[str, str], str]:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    authority = tmp_path / "authority"
    authority.mkdir(mode=0o700)
    (authority / "analysis").mkdir(mode=0o700)
    (authority / "external").mkdir(mode=0o700)
    signing_dir = authority / "signing-keys"
    signing_dir.mkdir(mode=0o700)
    (signing_dir / "keys.json").write_text(
        json.dumps({"active": "pilot-key", "keys": [{"keyId": "pilot-key"}]}),
        encoding="utf-8",
    )
    (signing_dir / "keys.json").chmod(0o600)
    for suffix in ("public.pem", "private.pem"):
        key_path = signing_dir / f"pilot-key.{suffix}"
        key_path.write_text("synthetic-key-material", encoding="utf-8")
        key_path.chmod(0o600)
    secret_dir = tmp_path / "dashboard-secrets"
    secret_dir.mkdir(mode=0o700)
    for relative, content in {
        "device-attestation-keys.json": "{}",
        "oidc-subject-registry.json": json.dumps(
            {
                "version": "oidc-subject-registry.v1",
                "subjects": [
                    {
                        "issuer": "https://login.example.com",
                        "subject": "pilot-user",
                        "principalId": "pilot-user",
                        "organizationId": "pilot-org",
                        "role": "OPERATOR",
                        "status": "ACTIVE",
                        "allowedSiteIds": ["pilot-site"],
                        "allowedWorkAreaIds": ["pilot-area"],
                    }
                ],
            }
        ),
        "analysis/runtime.json": "{}",
        "analysis/activation.json": "{}",
        "analysis/activation-keys.json": "{}",
        "external/workflow.json": "{}",
        "external/provider.json": "{}",
    }.items():
        path = authority / relative
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
    for name, content in {
        "dashboard-session.secret": "synthetic-session-secret-value-0123456789",
        "oidc-client.secret": "synthetic-oidc-client-secret-value-1234",
    }.items():
        path = secret_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)

    env = {
        "KSI_ANALYSIS_PILOT_CORE_IMAGE_ID": "registry.example/ksi-core@sha256:" + "a" * 64,
        "KSI_ANALYSIS_PILOT_DASHBOARD_IMAGE_ID": "registry.example/ksi-dashboard@sha256:"
        + "b" * 64,
        "KSI_ANALYSIS_PILOT_TAILNET_HOSTNAME": "pilot.example.ts.net",
        "KSI_ANALYSIS_PILOT_APP_ORIGIN": "https://pilot.example.ts.net",
        "KSI_ANALYSIS_PILOT_API_ORIGIN": "https://api-pilot.example.ts.net",
        "KSI_ANALYSIS_PILOT_OBJECTS_ORIGIN": "https://objects-pilot.example.ts.net",
        "KSI_ANALYSIS_PILOT_APP_PORT": "18443",
        "KSI_ANALYSIS_PILOT_API_PORT": "18444",
        "KSI_ANALYSIS_PILOT_OBJECTS_PORT": "19000",
        "KSI_ANALYSIS_PILOT_OIDC_ISSUER": "https://login.example.com",
        "KSI_ANALYSIS_PILOT_OIDC_AUDIENCE": "ksi-core",
        "KSI_ANALYSIS_PILOT_OIDC_JWKS_URL": "https://login.example.com/.well-known/jwks.json",
        "KSI_ANALYSIS_PILOT_OIDC_CLIENT_ID": "ksi-pilot-dashboard",
        "KSI_ANALYSIS_PILOT_MINIO_ROOT_USER": "synthetic-minio-user",
        "KSI_ANALYSIS_PILOT_MINIO_ROOT_PASSWORD": "synthetic-minio-password-long-enough",
        "KSI_ANALYSIS_PILOT_MINIO_CORE_ACCESS_KEY": "synthetic-core-access",
        "KSI_ANALYSIS_PILOT_MINIO_CORE_SECRET_KEY": "synthetic-core-secret-password-long-enough",
        "KSI_ANALYSIS_PILOT_CORE_PRINCIPAL_TOKENS_JSON": json.dumps(
            [
                {
                    "tokenSha256": "c" * 64,
                    "principalId": "pilot-analysis-worker",
                    "kind": "ANALYSIS_WORKER",
                    "status": "ACTIVE",
                    "organizationId": "pilot-org",
                }
            ]
        ),
        "KSI_ANALYSIS_PILOT_STATE_DIR": str(tmp_path / "core-state"),
        "KSI_ANALYSIS_PILOT_AUTHORITY_DIR": str(authority),
        "KSI_ANALYSIS_PILOT_SECRET_DIR": str(secret_dir),
    }
    state_dir = Path(env["KSI_ANALYSIS_PILOT_STATE_DIR"])
    state_dir.mkdir(mode=0o700)
    return env, COMPOSE_PATH.read_text(encoding="utf-8") if COMPOSE_PATH.exists() else ""


def test_valid_customer_tailnet_and_oidc_candidate_passes_without_echoing_secrets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env, compose = _candidate(tmp_path)
    env_path = tmp_path / "pilot.env"
    env_path.write_text("".join(f"{key}={value}\n" for key, value in env.items()), encoding="utf-8")
    env_path.chmod(0o600)
    monkeypatch.setattr(preflight, "_SERVICE_UID", __import__("os").geteuid())

    assert preflight.main(["--env-file", str(env_path)]) == 0
    output = capsys.readouterr().out

    assert "PASS" in output
    assert env["KSI_ANALYSIS_PILOT_MINIO_ROOT_PASSWORD"] not in output
    assert "synthetic-oidc-client-secret-value-1234" not in output


def test_owned_candidate_is_private_under_a_group_writable_host_umask(tmp_path: Path) -> None:
    """Fixture setup must not accidentally violate the real directory admission policy."""
    previous = os.umask(0o002)
    try:
        env, compose = _candidate(tmp_path)
        preflight.validate_candidate(env, compose_text=compose, expected_uid=os.geteuid())
    finally:
        os.umask(previous)


@pytest.mark.parametrize(
    "key",
    [
        "KSI_ANALYSIS_PILOT_AUTHORITY_DIR",
        "KSI_ANALYSIS_PILOT_SECRET_DIR",
        "KSI_ANALYSIS_PILOT_STATE_DIR",
    ],
)
def test_group_writable_candidate_directory_is_still_rejected(tmp_path: Path, key: str) -> None:
    """Making fixtures safe must never relax production admission for an unsafe directory."""
    env, compose = _candidate(tmp_path)
    Path(env[key]).chmod(0o770)
    with pytest.raises(preflight.PreflightBlocked, match="UNSAFE_DIRECTORY"):
        preflight.validate_candidate(env, compose_text=compose, expected_uid=os.geteuid())


@pytest.mark.parametrize("name", ["dashboard-session.secret", "oidc-client.secret"])
@pytest.mark.parametrize(("length", "accepted"), [(31, False), (32, True)])
def test_dashboard_secrets_match_runtime_minimum_length(
    tmp_path: Path, name: str, length: int, accepted: bool
) -> None:
    env, compose = _candidate(tmp_path)
    secret = Path(env["KSI_ANALYSIS_PILOT_SECRET_DIR"]) / name
    secret.write_text("s" * length, encoding="utf-8")
    secret.chmod(0o600)

    if accepted:
        preflight.validate_candidate(
            env, compose_text=compose, expected_uid=__import__("os").geteuid()
        )
    else:
        with pytest.raises(preflight.PreflightBlocked):
            preflight.validate_candidate(
                env, compose_text=compose, expected_uid=__import__("os").geteuid()
            )


@pytest.mark.parametrize(
    ("secret_value", "accepted"),
    [
        ("\ufeff" + "s" * 31, False),
        ("\ufeff \ufeff" + "s" * 32 + "\ufeff \n", True),
    ],
)
def test_dashboard_secret_length_uses_ecmascript_trim_set(
    tmp_path: Path, secret_value: str, accepted: bool
) -> None:
    env, compose = _candidate(tmp_path)
    secret = Path(env["KSI_ANALYSIS_PILOT_SECRET_DIR"]) / "oidc-client.secret"
    secret.write_text(secret_value, encoding="utf-8")
    secret.chmod(0o600)

    if accepted:
        preflight.validate_candidate(
            env, compose_text=compose, expected_uid=__import__("os").geteuid()
        )
    else:
        with pytest.raises(preflight.PreflightBlocked):
            preflight.validate_candidate(
                env, compose_text=compose, expected_uid=__import__("os").geteuid()
            )


def test_protected_json_parses_bytes_from_the_checked_file_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checked_dir = tmp_path / "checked"
    checked_dir.mkdir(mode=0o700)
    protected = checked_dir / "protected.json"
    protected.write_text('{"source":"checked"}', encoding="utf-8")
    protected.chmod(0o600)
    outside = tmp_path / "outside.json"
    outside.write_text('{"source":"substituted"}', encoding="utf-8")
    outside.chmod(0o600)
    original_read = preflight.os.read
    substituted = False

    def substitute_after_open(fd: int, count: int) -> bytes:
        nonlocal substituted
        if not substituted:
            backup = tmp_path / "checked-inode"
            checked_dir.rename(backup)
            checked_dir.symlink_to(tmp_path)
            substituted = True
        return original_read(fd, count)

    monkeypatch.setattr(preflight.os, "read", substitute_after_open)

    result = preflight._protected_json(protected, expected_uid=__import__("os").geteuid())

    assert result == {"source": "checked"}
    assert checked_dir.is_symlink()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("KSI_ANALYSIS_PILOT_OIDC_ISSUER", ""),
        ("KSI_ANALYSIS_PILOT_OIDC_AUDIENCE", ""),
        ("KSI_ANALYSIS_PILOT_OIDC_JWKS_URL", ""),
        ("KSI_ANALYSIS_PILOT_OIDC_CLIENT_ID", ""),
        ("KSI_ANALYSIS_PILOT_TAILNET_HOSTNAME", ""),
        ("KSI_ANALYSIS_PILOT_APP_ORIGIN", "https://pilot.example.com"),
    ],
)
def test_missing_or_non_tailnet_customer_inputs_fail_closed(
    tmp_path: Path, key: str, value: str
) -> None:
    env, compose = _candidate(tmp_path)
    env[key] = value

    with pytest.raises(preflight.PreflightBlocked):
        preflight.validate_candidate(
            env, compose_text=compose, expected_uid=__import__("os").geteuid()
        )


@pytest.mark.parametrize(
    "issuer",
    [
        "http://login.example.com",
        "https://localhost:8080",
        "https://127.0.0.1:8080",
        "https://identity.local",
        "http://identity:8080",
    ],
)
def test_development_or_insecure_oidc_issuer_is_rejected(tmp_path: Path, issuer: str) -> None:
    env, compose = _candidate(tmp_path)
    env["KSI_ANALYSIS_PILOT_OIDC_ISSUER"] = issuer
    registry_path = Path(env["KSI_ANALYSIS_PILOT_AUTHORITY_DIR"]) / "oidc-subject-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["subjects"][0]["issuer"] = issuer
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    registry_path.chmod(0o600)

    with pytest.raises(preflight.PreflightBlocked):
        preflight.validate_candidate(
            env, compose_text=compose, expected_uid=__import__("os").geteuid()
        )


def test_public_bind_and_development_identity_service_are_rejected(tmp_path: Path) -> None:
    env, compose = _candidate(tmp_path)

    with pytest.raises(preflight.PreflightBlocked):
        preflight.validate_candidate(
            env,
            compose_text=compose.replace("127.0.0.1:", "0.0.0.0:", 1),
            expected_uid=__import__("os").geteuid(),
        )
    with pytest.raises(preflight.PreflightBlocked):
        preflight.validate_candidate(
            env,
            compose_text=compose + "\n  identity:\n    image: local-issuer\n",
            expected_uid=__import__("os").geteuid(),
        )


def test_host_network_service_is_rejected(tmp_path: Path) -> None:
    env, compose = _candidate(tmp_path)
    unsafe = compose.replace(
        "    restart: unless-stopped\n    networks: [pilot-private]",
        "    network_mode: host\n    restart: unless-stopped\n    networks: [pilot-private]",
        1,
    )

    with pytest.raises(preflight.PreflightBlocked):
        preflight.validate_candidate(
            env, compose_text=unsafe, expected_uid=__import__("os").geteuid()
        )


def test_missing_protected_authority_material_and_mutable_image_are_rejected(
    tmp_path: Path,
) -> None:
    env, compose = _candidate(tmp_path)
    (Path(env["KSI_ANALYSIS_PILOT_AUTHORITY_DIR"]) / "analysis" / "activation.json").unlink()
    with pytest.raises(preflight.PreflightBlocked):
        preflight.validate_candidate(
            env, compose_text=compose, expected_uid=__import__("os").geteuid()
        )

    env, compose = _candidate(tmp_path / "second")
    env["KSI_ANALYSIS_PILOT_CORE_IMAGE_ID"] = "registry.example/ksi-core:latest"
    with pytest.raises(preflight.PreflightBlocked):
        preflight.validate_candidate(
            env, compose_text=compose, expected_uid=__import__("os").geteuid()
        )


def test_pilot_core_token_set_rejects_generic_processing_principal(tmp_path: Path) -> None:
    env, compose = _candidate(tmp_path)
    token_rows = json.loads(env["KSI_ANALYSIS_PILOT_CORE_PRINCIPAL_TOKENS_JSON"])
    token_rows.append(
        {
            "tokenSha256": "d" * 64,
            "principalId": "generic-processing",
            "kind": "PROCESSING_WORKER",
            "status": "ACTIVE",
            "organizationId": "pilot-org",
        }
    )
    env["KSI_ANALYSIS_PILOT_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(token_rows)

    with pytest.raises(preflight.PreflightBlocked):
        preflight.validate_candidate(
            env,
            compose_text=compose,
            expected_uid=__import__("os").geteuid(),
        )


def test_compose_has_only_pilot_services_loopback_ports_and_no_build_or_general_worker() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    services = preflight.compose_service_names(compose)

    assert services == {"core", "dashboard", "minio", "bucket-init"}
    assert "build:" not in compose
    assert "nodeodm" not in compose.lower()
    assert "worker:" not in compose.lower()
    assert "127.0.0.1:${KSI_ANALYSIS_PILOT_" in compose
    assert "0.0.0.0:" not in compose
    assert '"[::]:' not in compose
    assert "read_only: true" in compose
    assert "cap_drop: [ALL]" in compose
    assert "no-new-privileges:true" in compose


def test_core_uses_bucket_scoped_object_credentials_not_minio_root() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    core_section = compose.split("  core:\n", maxsplit=1)[1].split("  dashboard:\n", maxsplit=1)[0]

    assert "AWS_ACCESS_KEY_ID: ${KSI_ANALYSIS_PILOT_MINIO_CORE_ACCESS_KEY" in core_section
    assert "AWS_SECRET_ACCESS_KEY: ${KSI_ANALYSIS_PILOT_MINIO_CORE_SECRET_KEY" in core_section
    assert "MINIO_ROOT_PASSWORD" not in core_section
    assert "condition: service_started" in compose
    assert "mc --config-dir /tmp/mc-config ready pilot" in compose
    bucket_init = compose.split("  bucket-init:\n", maxsplit=1)[1].split("  core:\n", maxsplit=1)[0]
    assert "mb --ignore-existing pilot/ksi-analysis-evidence" in bucket_init
    assert "admin policy" not in bucket_init
    assert "admin user" not in bucket_init
    assert "KSI_ANALYSIS_PILOT_MINIO_CORE_SECRET_KEY:" not in bucket_init


def test_minio_iam_is_an_explicit_operator_gate_not_silent_compose_reconciliation() -> None:
    readme = (PILOT_DIR / "README.md").read_text(encoding="utf-8")

    assert "Compose creates or changes no" in readme
    assert "MinIO user, secret, group, or policy" in readme
    assert "MemberOf is empty" in readme
    assert "only direct policy must be the bucket-scoped" in readme
    assert "repeat the verification" in readme and "before restarting Core" in readme
