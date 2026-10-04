"""Static deployment boundary for the external-reconstruction staging candidate.

These checks intentionally test the versioned host and Compose assets instead
of starting containers or changing the host.  The candidate may be prepared
only after a separate owner operation has supplied real image, SBOM, signature,
and authority inputs.  A repository checkout must therefore fail closed rather
than acquiring ambient Docker access or silently targeting Phase 2 staging.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from support.external_oci_archive_fixture import make_oci_fixture

_ROOT = Path(__file__).resolve().parents[2]
_DEPLOY = _ROOT / "deploy"
_RUNTIME = _DEPLOY / "external-runtime"
_BIN = _DEPLOY / "bin"
_BOOTSTRAP = _BIN / "external-runtime-host-bootstrap.sh"
_STAGE = _BIN / "external-runtime-stage.sh"
_RUNTIME_IMAGE_PINS = _ROOT / "tools" / "check_runtime_image_pins.py"
_RUNTIME_UID = 10001
_RUNTIME_GID = 10001
_FIXTURE_TOOL_TIMEOUT_SECONDS = 15

_REQUIRED_ASSETS = (
    _DEPLOY / "compose.external-reconstruction.yaml",
    _DEPLOY / ".env.external-reconstruction.example",
    _RUNTIME / "README.md",
    _RUNTIME / "systemd" / "ksi-external-runtime-directories.service",
    _RUNTIME / "systemd" / "ksi-external-runtime-socket-acl.service",
    _RUNTIME / "systemd" / "ksi-external-validation-worker.service",
    _RUNTIME / "systemd" / "bin" / "ksi-external-runtime-socket-acl",
    _RUNTIME / "systemd" / "user" / "ksi-external-inspector.socket",
    _RUNTIME / "systemd" / "user" / "ksi-external-inspector.service",
    _RUNTIME / "systemd" / "user" / "ksi-external-measurement.socket",
    _RUNTIME / "systemd" / "user" / "ksi-external-measurement.service",
    _RUNTIME / "systemd" / "dbus.socket.private.conf",
    _RUNTIME / "systemd" / "docker.service.private.conf",
    _RUNTIME / "systemd" / "manifest.sha256",
    _RUNTIME / "systemd" / "user" / "ksi-inspector.slice",
    _RUNTIME / "systemd" / "user" / "ksi-measurement.slice",
    _BIN / "external-runtime-host-preflight.sh",
    _BIN / "external-runtime-host-bootstrap.sh",
    _BIN / "external-runtime-stage.sh",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _runtime_image_reference_sets() -> tuple[list[str], list[str]]:
    result = subprocess.run(
        [sys.executable, str(_RUNTIME_IMAGE_PINS), "--root", str(_ROOT), "--references-json"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    canonical = sorted({entry["reference"] for entry in entries})
    candidate = sorted(
        {
            entry["reference"]
            for entry in entries
            if entry["path"] == "deploy/compose.external-reconstruction.yaml"
        }
    )
    assert len(candidate) == 3
    assert set(candidate).issubset(canonical)
    return canonical, candidate


def _candidate_credential_validation_service() -> dict[str, Any]:
    compose = yaml.safe_load(_text(_DEPLOY / "compose.external-reconstruction.yaml"))
    service = compose["services"]["candidate-credential-validation"]
    assert isinstance(service, dict)
    return service


def _required_fixture_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        pytest.skip(f"NOT_VERIFIED: required isolated-fixture tool is unavailable: {name}")
    return path


def _run_fixture_tool(
    command: list[str], *, description: str, timeout: int = _FIXTURE_TOOL_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        pytest.skip(f"NOT_VERIFIED: required isolated-fixture tool is unavailable: {exc.filename}")
    except subprocess.TimeoutExpired:
        pytest.fail(f"NOT_VERIFIED: {description} exceeded {timeout} seconds")


def _root_owned_snapshot(path: Path) -> dict[str, tuple[int, int, int, int, str]]:
    """Capture only test-owned fixture metadata and content through sudo."""
    snapshot = r'''
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
observed = {}
for item in sorted(root.rglob("*")):
    node = item.stat()
    key = str(item.relative_to(root))
    digest = hashlib.sha256(item.read_bytes()).hexdigest() if stat.S_ISREG(node.st_mode) else ""
    observed[key] = [node.st_uid, node.st_gid, stat.S_IMODE(node.st_mode), node.st_ino, digest]
print(json.dumps(observed, sort_keys=True))
'''
    sudo = _required_fixture_tool("sudo")
    result = _run_fixture_tool(
        [sudo, "-n", sys.executable, "-c", snapshot, str(path)],
        description="test-owned credential snapshot",
    )
    if result.returncode != 0:
        pytest.skip(f"NOT_VERIFIED: cannot snapshot test-owned UID fixture: {result.stderr}")
    return {
        name: tuple(value)
        for name, value in json.loads(result.stdout).items()
    }


def _run_validator_as_configured_user(
    fixture: Path, service: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    """Run the real validator with the Compose identity in a no-network sandbox."""
    user = service["user"]
    assert isinstance(user, str) and user.count(":") == 1
    uid, gid = user.split(":", maxsplit=1)
    sudo = _required_fixture_tool("sudo")
    bwrap = _required_fixture_tool("bwrap")
    setpriv = _required_fixture_tool("setpriv")
    shell = _required_fixture_tool("sh")
    python = Path(sys.executable).resolve()
    python_root = python.parent.parent
    package_paths = ":".join(
        f"/app/{path.relative_to(_ROOT)}" for path in sorted((_ROOT / "packages").glob("*/src"))
    )
    python_root_directories = [
        argument
        for parent in reversed(python_root.parents)
        if str(parent) != "/"
        for argument in ("--dir", str(parent))
    ]
    command = [
        sudo,
        "-n",
        "env",
        f"PYTHONPATH=/app/services/core/src:{package_paths}:/app/.venv/lib/python3.12/site-packages",
        "PYTHONDONTWRITEBYTECODE=1",
        bwrap,
        "--tmpfs",
        "/",
        *python_root_directories,
        "--ro-bind",
        str(python_root),
        str(python_root),
        "--dir",
        "/state",
        "--ro-bind",
        str(fixture),
        "/state",
        "--ro-bind",
        str(_ROOT),
        "/app",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib",
        "/lib64",
        "--ro-bind",
        "/etc",
        "/etc",
        "--ro-bind",
        "/dev",
        "/dev",
        "--proc",
        "/proc",
        "--unshare-net",
        "--",
        setpriv,
        f"--reuid={uid}",
        f"--regid={gid}",
        "--clear-groups",
        "--bounding-set=-all",
        "--nnp",
        shell,
        "-c",
        "id -u; id -g; awk '/^(CapBnd|NoNewPrivs):/ { print }' /proc/self/status; exec \"$@\"",
        "sh",
        str(python),
        "/app/deploy/external-runtime/prepare_candidate_state.py",
        "--validate-only",
    ]
    result = _run_fixture_tool(command, description="no-network credential validator")
    if result.returncode != 0 and "a password is required" in result.stderr:
        pytest.skip("NOT_VERIFIED: passwordless sudo is unavailable")
    return result


@contextmanager
def _candidate_credential_fixture(tmp_path: Path, *, defect: str | None = None) -> Iterator[Path]:
    from test_production_assembly import _write_signing_keys

    fixture = tmp_path / "test-owned-credentials"
    secrets = fixture / "secrets"
    signing = fixture / "signing"
    secrets.mkdir(parents=True)
    (secrets / "dashboard-session.secret").write_text("s" * 64, encoding="utf-8")
    if defect != "missing":
        (secrets / "oidc-client.secret").write_text(
            "short" if defect == "malformed" else "o" * 64,
            encoding="utf-8",
        )
    _write_signing_keys(signing)
    for item in (fixture, secrets, signing):
        item.chmod(0o700)
    for item in fixture.rglob("*"):
        if item.is_file():
            item.chmod(0o600)
    sudo = _required_fixture_tool("sudo")
    original_identity = f"{os.geteuid()}:{os.getegid()}"
    sudo_ready = _run_fixture_tool(
        [sudo, "-n", "true"], description="test-owned credential fixture sudo availability"
    )
    if sudo_ready.returncode != 0:
        pytest.skip("NOT_VERIFIED: passwordless sudo is unavailable for test-owned fixture")
    ownership_attempted = False
    try:
        ownership_attempted = True
        ownership = _run_fixture_tool(
            [sudo, "-n", "chown", "-R", f"{_RUNTIME_UID}:{_RUNTIME_GID}", str(fixture)],
            description="test-owned credential fixture ownership setup",
        )
        if ownership.returncode != 0:
            pytest.skip(
                "NOT_VERIFIED: cannot provision test-owned UID fixture: " f"{ownership.stderr}"
            )
        yield fixture
    finally:
        if ownership_attempted:
            restoration = _run_fixture_tool(
                [sudo, "-n", "chown", "-R", original_identity, str(fixture)],
                description="test-owned credential fixture ownership restoration",
            )
            assert restoration.returncode == 0, (
                "NOT_VERIFIED: cannot restore test-owned fixture ownership: "
                f"{restoration.stderr}"
            )


def test_external_runtime_candidate_assets_are_versioned_and_complete() -> None:
    """The isolated candidate cannot be assembled from undocumented host state."""
    assert [path for path in _REQUIRED_ASSETS if not path.is_file()] == []


def test_candidate_never_uses_ambient_docker_or_phase2_project_identity() -> None:
    """A candidate has a distinct project and rejects control of another stack."""
    compose = _text(_DEPLOY / "compose.external-reconstruction.yaml")
    stage = _text(_BIN / "external-runtime-stage.sh")

    assert "${KSI_EXTERNAL_RC_PROJECT_NAME:-ksi-external-rc}" in compose
    assert "ksi-phase2-staging" not in compose
    assert "/var/run/docker.sock" not in compose
    assert "docker.sock" not in compose
    assert "DOCKER_HOST" not in compose
    assert "docker compose down" not in stage
    assert "ksi-phase2-staging" in stage
    assert "KSI_EXTERNAL_RC_PROJECT_NAME" in stage
    assert "@sha256:" in stage
    assert "source \"$env_file\"" not in stage
    assert "tailscale serve" not in stage
    assert "status --porcelain --untracked-files=all" in stage
    assert "docker image inspect" in stage
    assert "sha256sum" in stage
    assert "KSI_EXTERNAL_RC_HOST_BINDING" in stage
    assert "validate_canonical_release_evidence" in stage
    assert "validate_host_binding" in stage
    assert "KSI_EXTERNAL_RC_OPERATOR_DIR" in stage
    assert "--untrusted-user nobody" in stage
    assert "OBSERVED_SERVER_PEER_CREDENTIAL" in stage
    assert "--profile candidate-preflight run --rm --no-deps --no-build --pull never" in stage
    assert "KSI_EXTERNAL_RC_CORE_IMAGE_ID" in stage
    assert "verify_started_compose_images" in stage
    assert "docker container inspect" in stage
    assert "compose up -d --no-build --pull never --wait" in stage
    assert "/ready/external-authority" in stage
    assert "PROVIDER_CONFIGURED" in stage

    assert "network_mode: host" not in compose
    assert "image: ${KSI_EXTERNAL_RC_CORE_IMAGE_ID:?verified Core image ID is required}" in compose
    assert (
        "image: ${KSI_EXTERNAL_RC_DASHBOARD_IMAGE_ID:?verified Dashboard image ID is required}"
        in compose
    )
    assert "image: ksi-external-rc-core:local" not in compose
    assert "image: ksi-external-rc-dashboard:local" not in compose
    assert "KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG: /run/ksi-operator/workflow.json" in compose
    assert "KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG: /run/ksi-operator/provider.json" in compose
    assert "${KSI_EXTERNAL_RC_OPERATOR_DIR:?set KSI_EXTERNAL_RC_OPERATOR_DIR}/secrets" in compose
    assert "${KSI_EXTERNAL_RC_OPERATOR_DIR:?set KSI_EXTERNAL_RC_OPERATOR_DIR}/signing" in compose
    assert "external-rc-secrets:" not in compose
    assert "external-rc-signing:" not in compose
    assert compose.count('user: "10001:10001"') >= 2
    assert "verify_product_image_binding" in stage
    assert "candidate-credential-validation:" in compose
    assert "candidate-authority-preflight:" in compose
    assert "profiles: [candidate-preflight]" in compose
    assert "network_mode: none" in compose
    assert "read_only: true" in compose
    assert "cap_drop: [ALL]" in compose
    assert "no-new-privileges:true" in compose
    assert "user: root" in compose
    assert 'user: "10001:10001"' in compose
    assert "prepare_candidate_state.py" in compose
    assert '"--validate-only"]' in compose
    assert "/state/secrets:ro" in compose
    assert "/state/signing:ro" in compose
    assert (
        "/var/lib/ksi/data:rw,noexec,nosuid,nodev,size=67108864,uid=10001,"
        "gid=10001,mode=0700"
    ) in compose
    assert "KSI_EXTERNAL_RC_MINIO_IMAGE_ID" not in compose
    assert "KSI_EXTERNAL_RC_MC_IMAGE_ID" not in compose
    assert "KSI_EXTERNAL_RC_CADDY_IMAGE_ID" not in compose
    for image_variable in (
        "KSI_EXTERNAL_RC_MINIO_IMAGE_ID",
        "KSI_EXTERNAL_RC_MC_IMAGE_ID",
        "KSI_EXTERNAL_RC_CADDY_IMAGE_ID",
    ):
        assert image_variable in stage
    identity_port = (
        '"127.0.0.1:'
        '${KSI_EXTERNAL_RC_IDENTITY_PORT:?set KSI_EXTERNAL_RC_IDENTITY_PORT}:8080"'
    )
    assert identity_port in compose


def test_candidate_credential_validation_executes_as_hardened_runtime_user_without_mutation(
    tmp_path: Path,
) -> None:
    """Changing the preflight user back to root must fail this real validator probe."""
    service = _candidate_credential_validation_service()
    with _candidate_credential_fixture(tmp_path) as fixture:
        before = _root_owned_snapshot(fixture)

        result = _run_validator_as_configured_user(fixture, service)

        assert _root_owned_snapshot(fixture) == before
        assert service["read_only"] is True
        assert service["network_mode"] == "none"
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            str(_RUNTIME_UID),
            str(_RUNTIME_GID),
            "CapBnd:\t0000000000000000",
            "NoNewPrivs:\t1",
            "external reconstruction candidate supplied credentials verified (read-only)",
        ]
    assert fixture.stat().st_uid == os.geteuid()
    assert fixture.stat().st_gid == os.getegid()


@pytest.mark.parametrize("defect", ["missing", "malformed"])
def test_candidate_credential_validation_rejects_bad_input_without_mutation(
    tmp_path: Path, defect: str
) -> None:
    """Missing or malformed test-owned credentials fail without privilege or file repair."""
    service = _candidate_credential_validation_service()
    with _candidate_credential_fixture(tmp_path, defect=defect) as fixture:
        before = _root_owned_snapshot(fixture)

        result = _run_validator_as_configured_user(fixture, service)

        assert _root_owned_snapshot(fixture) == before
        assert result.stdout.splitlines() == [
            str(_RUNTIME_UID),
            str(_RUNTIME_GID),
            "CapBnd:\t0000000000000000",
            "NoNewPrivs:\t1",
        ]
        assert result.returncode != 0
        assert "credential" in result.stderr
    assert fixture.stat().st_uid == os.geteuid()
    assert fixture.stat().st_gid == os.getegid()


def test_start_with_missing_operator_input_never_reaches_compose(tmp_path: Path) -> None:
    """An incomplete candidate file must stop before it can start a service."""
    env_file = tmp_path / "candidate.env"
    env_file.write_text(
        "\n".join(
            (
                "KSI_EXTERNAL_RC_PROJECT_NAME=ksi-external-rc",
                "KSI_EXTERNAL_RC_STATE_DIR=/var/lib/ksi-external-runtime/candidate",
                "KSI_EXTERNAL_RC_RELEASE_EVIDENCE=/etc/ksi-external-runtime/release.json",
                "KSI_EXTERNAL_RC_HOST_BINDING=/etc/ksi-external-runtime/host.json",
                "KSI_EXTERNAL_RC_HOST=candidate.ts.net",
                "KSI_EXTERNAL_RC_APP_PORT=10100",
                "KSI_EXTERNAL_RC_IDENTITY_PORT=10101",
                "KSI_EXTERNAL_RC_API_PORT=10102",
                "KSI_EXTERNAL_RC_OBJECTS_PORT=10103",
                "KSI_EXTERNAL_RC_MINIO_CONSOLE_PORT=10104",
                "KSI_EXTERNAL_RC_MINIO_ROOT_USER=operator",
                "KSI_EXTERNAL_RC_MINIO_ROOT_PASSWORD=not-a-secret-fixture",
                "KSI_EXTERNAL_RC_PRINCIPAL_TOKENS_JSON=[]",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    docker_log = tmp_path / "docker-called"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(f"#!/bin/sh\nprintf called > {docker_log}\n", encoding="utf-8")
    fake_docker.chmod(0o700)

    result = subprocess.run(
        [str(_STAGE), "start", "--env-file", str(env_file)],
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "candidate env omits KSI_EXTERNAL_RC_OPERATOR_DIR" in result.stderr
    assert not docker_log.exists()


def test_start_orders_real_guards_before_its_single_compose_up(tmp_path: Path) -> None:
    """A candidate start validates its real inputs before the only ordinary start."""
    calls = tmp_path / "compose-calls"
    shell = r'''source "$1"
calls_path="$2"
record() { printf '%s\n' "$1" >> "$calls_path"; }
require_release_evidence() { record release-evidence; }
validate_operator_directory() { record operator-directory; }
verify_socket_acl_proof() { record socket-acl; }
preflight_authority_in_exact_core_image() { record authority-preflight; }
verify_started_compose_images() { record started-images; }
verify_live_provider() { record live-provider; }
compose() {
  case "$*" in
    *candidate-credential-validation) record credential-validate-only ;;
    config) record compose-config ;;
    'up -d --no-build --pull never --wait') record compose-up ;;
    *) exit 97 ;;
  esac
}
start
'''

    result = subprocess.run(
        ["bash", "-c", shell, "bash", str(_STAGE), str(calls)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "release-evidence",
        "operator-directory",
        "credential-validate-only",
        "socket-acl",
        "authority-preflight",
        "compose-config",
        "compose-up",
        "started-images",
        "live-provider",
    ]


def test_credential_failure_prevents_all_ordinary_service_starts(tmp_path: Path) -> None:
    """A failed exact-image credential check reaches no Compose config or service start."""
    calls = tmp_path / "compose-calls"
    shell = r'''source "$1"
calls_path="$2"
record() { printf '%s\n' "$1" >> "$calls_path"; }
require_release_evidence() { record release-evidence; }
validate_operator_directory() { record operator-directory; }
verify_socket_acl_proof() { record socket-acl; }
preflight_authority_in_exact_core_image() { record authority-preflight; }
compose() {
  case "$*" in
    *candidate-credential-validation) record credential-validate-only; return 1 ;;
    *) record "unexpected:$*"; return 97 ;;
  esac
}
if start; then exit 96; fi
'''

    result = subprocess.run(
        ["bash", "-c", shell, "bash", str(_STAGE), str(calls)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "release-evidence",
        "operator-directory",
        "credential-validate-only",
    ]
    assert "BLOCKED_EXTERNAL_CREDENTIALS" in result.stderr


def test_status_and_stop_bypass_release_evidence_but_target_only_candidate_label(
    tmp_path: Path,
) -> None:
    """A broken proof cannot block a label-scoped emergency candidate stop."""
    calls = tmp_path / "docker-calls"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$DOCKER_CALLS"
case "$*" in
  *'container ls -a'*'--format {{.ID}}') printf '%s\\n' 0123456789ab ;;
  *'container inspect --format {{index .Config.Labels "com.docker.compose.project"}} 0123456789ab')
    printf '%s\\n' ksi-external-rc ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o700)
    environment = {
        **os.environ,
        "DOCKER_CALLS": str(calls),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    status = subprocess.run(
        [str(_STAGE), "status"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    stop = subprocess.run(
        [str(_STAGE), "stop"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert status.returncode == 0, status.stderr
    assert stop.returncode == 0, stop.stderr
    observed = calls.read_text(encoding="utf-8").splitlines()
    candidate_lists = [call for call in observed if call.startswith("container ls -a")]
    assert len(candidate_lists) == 2
    expected_label = "label=com.docker.compose.project=ksi-external-rc"
    assert all(expected_label in call for call in candidate_lists)
    expected_inspection = (
        'container inspect --format {{index .Config.Labels "com.docker.compose.project"}} '
        "0123456789ab"
    )
    assert observed.count(
        expected_inspection
    ) == 1
    assert observed.count("container stop -- 0123456789ab") == 1
    assert not any("ksi-phase2-staging" in call for call in observed)


def test_verify_reports_not_attached_only_before_live_provider_attachment(tmp_path: Path) -> None:
    """A live provider status is not reported as the detached preflight state."""
    shell = r'''source "$1"
live="$2"
activation_preflight() { :; }
compose() {
  case "$1" in
    config) return 0 ;;
    ps) [[ "$live" == true ]] && printf '%s\n' core ;;
    exec) printf '%s\n' '{"status":"PROVIDER_CONFIGURED"}' ;;
    *) return 97 ;;
  esac
}
verify_started_compose_images() { :; }
verify
'''

    detached = subprocess.run(
        ["bash", "-c", shell, "bash", str(_STAGE), "false"],
        text=True,
        capture_output=True,
        check=False,
    )
    live = subprocess.run(
        ["bash", "-c", shell, "bash", str(_STAGE), "true"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert detached.returncode == 0, detached.stderr
    assert "not attached" in detached.stdout
    assert live.returncode == 0, live.stderr
    assert "PROVIDER_CONFIGURED" in live.stdout
    assert "not attached" not in live.stdout
    assert "quantitativeEligible" not in live.stdout


@pytest.mark.parametrize("failure", ["images", "provider"])
def test_verify_live_failures_remain_fail_closed_when_called_conditionally(
    failure: str,
) -> None:
    """A live-image or provider failure cannot print readiness through disabled errexit."""
    shell = r'''source "$1"
failure="$2"
activation_preflight() { :; }
compose() {
  case "$1" in
    config) return 0 ;;
    ps) printf '%s\n' core ;;
    *) return 97 ;;
  esac
}
verify_started_compose_images() {
  printf 'IMAGE_CHECK_REACHED\n'
  [[ "$failure" == images ]] && return 41
  return 0
}
verify_live_provider() {
  printf 'PROVIDER_CHECK_REACHED\n'
  [[ "$failure" == provider ]] && return 42
  return 0
}
if verify; then
  printf 'FALSE_SUCCESS\n'
  exit 96
else
  printf 'FAILED:%s\n' "$?"
fi
'''

    result = subprocess.run(
        ["bash", "-c", shell, "bash", str(_STAGE), failure],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "FALSE_SUCCESS" not in result.stdout
    assert "PROVIDER_CONFIGURED" not in result.stdout
    assert "FAILED:1" in result.stdout
    expected = ["IMAGE_CHECK_REACHED"]
    if failure == "provider":
        expected.append("PROVIDER_CHECK_REACHED")
    assert result.stdout.splitlines() == [*expected, "FAILED:1"]


def test_stop_returns_failure_without_stopping_a_second_candidate_container(tmp_path: Path) -> None:
    """A failed first candidate stop cannot continue and turn into a false success."""
    calls = tmp_path / "docker-calls"
    shell = r'''source "$1"
calls_path="$2"
docker() {
  case "$1 $2" in
    'container ls') printf '%s\n%s\n' aaaaaaaaaaaa bbbbbbbbbbbb ;;
    'container inspect') printf '%s\n' ksi-external-rc ;;
    'container stop')
      printf 'stop:%s\n' "$4" >> "$calls_path"
      [[ "$4" == aaaaaaaaaaaa ]] && return 43
      return 0
      ;;
    *) return 97 ;;
  esac
}
if stop; then
  printf 'FALSE_SUCCESS\n'
  exit 96
else
  printf 'FAILED:%s\n' "$?"
fi
'''

    result = subprocess.run(
        ["bash", "-c", shell, "bash", str(_STAGE), str(calls)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "FALSE_SUCCESS" not in result.stdout
    assert "FAILED:43" in result.stdout
    assert calls.read_text(encoding="utf-8").splitlines() == ["stop:aaaaaaaaaaaa"]


@pytest.mark.parametrize("mode", ["malformed", "stale", "wrong-label"])
def test_stop_refuses_unverified_candidate_ids_without_any_stop(
    tmp_path: Path, mode: str
) -> None:
    """Malformed, stale, or differently labeled Docker observations never stop a container."""
    calls = tmp_path / "docker-calls"
    shell = r'''source "$1"
mode="$2"
calls_path="$3"
docker() {
  case "$1 $2" in
    'container ls')
      if [[ "$mode" == malformed ]]; then
        printf '%s\n' not-a-container-id
      else
        printf '%s\n' aaaaaaaaaaaa
      fi
      ;;
    'container inspect')
      [[ "$mode" == stale ]] && return 44
      if [[ "$mode" == wrong-label ]]; then
        printf '%s\n' ksi-phase2-staging
      else
        printf '%s\n' ksi-external-rc
      fi
      ;;
    'container stop') printf 'stop:%s\n' "$4" >> "$calls_path" ;;
    *) return 97 ;;
  esac
}
if stop; then
  printf 'FALSE_SUCCESS\n'
  exit 96
fi
'''

    result = subprocess.run(
        ["bash", "-c", shell, "bash", str(_STAGE), mode, str(calls)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "FALSE_SUCCESS" not in result.stdout
    assert not calls.exists()


@pytest.mark.parametrize(
    ("metadata", "accepted"),
    [
        ("0:0:711:directory", True),
        ("0:0:755:directory", True),
        ("0:0:750:directory", True),
        ("0:0:777:directory", False),
        ("0:0:770:directory", False),
        ("10001:10001:700:directory", False),
    ],
)
def test_operator_shared_parent_is_protected_without_changing_account_traversal(
    tmp_path: Path, metadata: str, accepted: bool
) -> None:
    parent = tmp_path / "runtime-root"
    parent.mkdir()
    shell = r'''source "$1"
fixture_metadata="$3"
stat() { printf '%s\n' "$fixture_metadata"; }
protected_operator_parent "$2"
'''
    result = subprocess.run(
        ["bash", "-c", shell, "bash", str(_STAGE), str(parent), metadata],
        text=True, capture_output=True, check=False,
    )
    assert (result.returncode == 0) is accepted, result.stderr


@pytest.mark.parametrize(
    ("metadata", "reaches_probe"),
    [
        ("0:0:755:regular file", True),
        ("0:0:750:regular file", True),
        ("0:0:775:regular file", False),
        ("0:0:777:regular file", False),
        ("0:0:644:regular file", False),
        ("10001:10001:755:regular file", False),
    ],
)
def test_public_root_helper_permissions_reach_only_the_real_peer_proof_gate(
    tmp_path: Path, metadata: str, reaches_probe: bool
) -> None:
    helper = tmp_path / "helper"
    helper.write_text("unused test fixture", encoding="utf-8")
    fixture_stage = tmp_path / "stage.sh"
    source = _text(_STAGE)
    original = (
        'readonly socket_acl_helper="/usr/local/lib/ksi-external-runtime/bin/'
        'ksi-external-runtime-socket-acl"'
    )
    assert source.count(original) == 1
    fixture_stage.write_text(
        source.replace(original, f'readonly socket_acl_helper="{helper}"'), encoding="utf-8"
    )
    calls = tmp_path / "probe-called"
    shell = r'''source "$1"
fixture_metadata="$2"
calls="$3"
stat() { printf '%s\n' "$fixture_metadata"; }
# No forged successful ACL receipt: reaching the probe still fails closed here.
sudo() { printf 'PROBE_CALLED\n' > "$calls"; return 42; }
verify_socket_acl_proof
'''
    result = subprocess.run(
        ["bash", "-c", shell, "bash", str(fixture_stage), metadata, str(calls)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode != 0
    assert calls.exists() is reaches_probe, result.stderr


@pytest.mark.parametrize(("mode", "accepted"), [("700", True), ("755", False), ("711", False)])
def test_shared_parent_traversal_does_not_relax_private_operator_child(
    tmp_path: Path, mode: str, accepted: bool
) -> None:
    child = tmp_path / "operator"
    child.mkdir()
    shell = r'''source "$1"
fixture_mode="$3"
stat() { printf '10001:10001:%s:directory\n' "$fixture_mode"; }
private_owner_mode "$2" directory
'''
    result = subprocess.run(
        ["bash", "-c", shell, "bash", str(_STAGE), str(child), mode],
        text=True, capture_output=True, check=False,
    )
    assert (result.returncode == 0) is accepted, result.stderr


def test_live_provider_check_requires_the_running_core_status_only(tmp_path: Path) -> None:
    """A healthy process alone cannot replace the provider-readiness response."""
    calls = tmp_path / "compose-calls"
    shell = r'''source "$1"
calls_path="$2"
compose() {
  printf '%s\n' "$1" >> "$calls_path"
  [[ "$1" == exec ]] && printf '%s\n' '{"status":"PROVIDER_CONFIGURED"}'
}
verify_live_provider
'''

    result = subprocess.run(
        ["bash", "-c", shell, "bash", str(_STAGE), str(calls)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == ["exec"]


def test_started_compose_containers_must_keep_the_verified_image_ids() -> None:
    """A post-evidence retag cannot become readiness success through Compose."""
    shell = r'''source "$1"
KSI_EXTERNAL_RC_CORE_IMAGE_ID="sha256:$(printf '1%.0s' {1..64})"
KSI_EXTERNAL_RC_DASHBOARD_IMAGE_ID="sha256:$(printf '2%.0s' {1..64})"
KSI_EXTERNAL_RC_MINIO_IMAGE_ID="sha256:$(printf '3%.0s' {1..64})"
KSI_EXTERNAL_RC_MC_IMAGE_ID="sha256:$(printf '4%.0s' {1..64})"
KSI_EXTERNAL_RC_CADDY_IMAGE_ID="sha256:$(printf '5%.0s' {1..64})"
swapped_service="${2:-}"
compose() {
  [[ "$1" == ps ]] || return 97
  service="${@: -1}"
  printf '%s-container\n' "$service"
}
docker() {
  [[ "$1" == container && "$2" == inspect && "$3" == --format \
    && "$4" == '{{.Image}}' ]] || return 98
  service="${5%-container}"
  case "$service" in
    init-state|identity|core) image="$KSI_EXTERNAL_RC_CORE_IMAGE_ID" ;;
    dashboard) image="$KSI_EXTERNAL_RC_DASHBOARD_IMAGE_ID" ;;
    minio) image="$KSI_EXTERNAL_RC_MINIO_IMAGE_ID" ;;
    bucket-init) image="$KSI_EXTERNAL_RC_MC_IMAGE_ID" ;;
    caddy) image="$KSI_EXTERNAL_RC_CADDY_IMAGE_ID" ;;
    *) return 99 ;;
  esac
  if [[ "$service" == "$swapped_service" ]]; then image="sha256:$(printf 'f%.0s' {1..64})"; fi
  printf '%s\n' "$image"
}
verify_started_compose_images
'''

    valid = subprocess.run(
        ["bash", "-c", shell, "bash", str(_STAGE)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert valid.returncode == 0, valid.stderr

    swapped = subprocess.run(
        ["bash", "-c", shell, "bash", str(_STAGE), "dashboard"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert swapped.returncode != 0
    assert "dashboard container image differs from the verified image ID" in swapped.stderr


def test_host_assets_keep_validator_and_launcher_privileges_separate() -> None:
    """The worker can use only the two named UDS endpoints, never Docker or D-Bus."""
    worker = _text(_RUNTIME / "systemd" / "ksi-external-validation-worker.service")
    inspector_socket = _text(_RUNTIME / "systemd" / "user" / "ksi-external-inspector.socket")
    measurement_socket = _text(_RUNTIME / "systemd" / "user" / "ksi-external-measurement.socket")
    inspector_service = _text(_RUNTIME / "systemd" / "user" / "ksi-external-inspector.service")
    measurement_service = _text(_RUNTIME / "systemd" / "user" / "ksi-external-measurement.service")
    dbus_dropin = _text(_RUNTIME / "systemd" / "dbus.socket.private.conf")
    docker_dropin = _text(_RUNTIME / "systemd" / "docker.service.private.conf")

    assert "User=ksi-validator" in worker
    assert "Group=ksi-validator" in worker
    assert "NoNewPrivileges=yes" in worker
    assert "PrivateNetwork=yes" not in worker
    assert "PrivateNetwork=no" in worker
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in worker
    assert "InaccessiblePaths=/var/run/docker.sock /run/docker.sock /run/user" in worker
    assert "/run/ksi-external-runtime/launcher/inspection.sock" in worker
    assert "/run/ksi-external-runtime/launcher/measurement.sock" in worker
    assert worker.count("/var/run/docker.sock") == 1
    assert "/run/user/" not in worker
    assert "ListenStream=/run/ksi-external-runtime/launcher/inspection.sock" in inspector_socket
    assert "ListenStream=/run/ksi-external-runtime/launcher/measurement.sock" in measurement_socket
    assert "User=ksi-inspector" not in inspector_service
    assert "User=ksi-inspector" not in measurement_service
    assert "StandardInput=socket" not in inspector_service
    assert "StandardInput=socket" not in measurement_service
    assert "--ignore-environment" not in inspector_service
    assert "--ignore-environment" not in measurement_service
    assert "Environment=XDG_RUNTIME_DIR=%t" in inspector_service
    assert "Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus" in inspector_service
    assert "BindReadOnlyPaths=%t/docker.sock %t/bus" in inspector_service
    assert "Environment=XDG_RUNTIME_DIR=%t" in measurement_service
    assert "BindReadOnlyPaths=%t/docker.sock %t/bus" in measurement_service
    assert "SocketMode=0600" in dbus_dropin
    assert "UMask=0077" in docker_dropin
    assert "chmod 0600 %t/docker.sock" in docker_dropin


def test_socket_acl_activation_is_a_root_owned_manual_systemd_boundary() -> None:
    """The named ACL is installed only after the two private sockets exist."""
    activation = _text(_RUNTIME / "systemd" / "ksi-external-runtime-socket-acl.service")
    helper = _text(_RUNTIME / "systemd" / "bin" / "ksi-external-runtime-socket-acl")

    assert "Requires=ksi-external-runtime-directories.service" in activation
    assert "WantedBy=" not in activation
    assert "ProtectSystem=strict" in activation
    assert "PrivateNetwork=yes" in activation
    assert "PrivateDevices=yes" in activation
    assert "RestrictAddressFamilies=AF_UNIX" in activation
    assert "CapabilityBoundingSet=CAP_DAC_OVERRIDE CAP_FOWNER CAP_SETGID CAP_SETUID" in activation
    assert (
        "ExecStart=/usr/local/lib/ksi-external-runtime/bin/"
        "ksi-external-runtime-socket-acl activate"
    ) in activation
    assert "measurement socket changed during ACL activation" in helper
    assert "--untrusted-user" in helper
    assert "s.connect(sys.argv[1])" in helper
    assert "OBSERVED_SERVER_PEER_CREDENTIAL" in helper
    assert "require_peer_receipt INSPECTION" in helper
    assert "require_peer_receipt MEASUREMENT" in helper
    assert "SO_PEERCRED" in helper


def test_bootstrap_refuses_drift_and_preflight_remains_read_only() -> None:
    """Host mutation is gated by a fresh ledger and preserves the existing stack."""
    preflight = _text(_BIN / "external-runtime-host-preflight.sh")
    bootstrap = _text(_BIN / "external-runtime-host-bootstrap.sh")

    assert "useradd" not in preflight
    assert "usermod" not in preflight
    assert "systemctl start" not in preflight
    assert "PREPARED, NOT APPLIED" in preflight
    assert "external-runtime-preflight.v1" in preflight
    assert "external-runtime-preflight.v1" in bootstrap
    assert "ksi-validator" in bootstrap
    assert "ksi-inspector" in bootstrap
    assert "ksi-phase2-staging" in bootstrap
    assert "/var/run/docker.sock" in bootstrap
    assert "dockerd-rootless-setuptool.sh install" in bootstrap
    assert "--force" not in bootstrap
    assert "--skip-iptables" not in bootstrap
    assert "XDG_RUNTIME_DIR" in bootstrap
    assert "DBUS_SESSION_BUS_ADDRESS" in bootstrap
    assert "systemctl --user daemon-reload" in bootstrap
    assert "/etc/systemd/system/ksi-inspector.slice" not in bootstrap
    assert "flock" in bootstrap
    assert "sha256sum" in preflight
    assert "$(id -u)/bus" not in preflight
    assert '"/run/user/${inspector_uid}/bus"' in preflight


def test_release_image_binding_normalizes_tagged_repository_digest() -> None:
    """A tag@digest reference is compared to Docker's canonical repo@digest."""
    stage = _BIN / "external-runtime-stage.sh"
    reference = "registry.example/ksi/core:2026.09@sha256:" + "a" * 64
    image_id = "sha256:" + "b" * 64
    canonical_digest = "registry.example/ksi/core@sha256:" + "a" * 64
    shell = r'''source "$1"
expected_image_id="$3"
canonical_digest="$4"
actual_image_id="$5"
docker() {
  if [[ "$4" == '{{.Id}}' ]]; then
    printf '%s\n' "$actual_image_id"
  else
    printf '%s\n' "$canonical_digest"
  fi
}
verify_image_binding "$2" "$3"
'''
    valid = subprocess.run(
        ["bash", "-c", shell, "bash", str(stage), reference, image_id, canonical_digest, image_id],
        text=True,
        capture_output=True,
        check=False,
    )
    assert valid.returncode == 0, valid.stderr

    mismatch = subprocess.run(
        [
            "bash",
            "-c",
            shell,
            "bash",
            str(stage),
            reference,
            "sha256:" + "c" * 64,
            canonical_digest,
            image_id,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert mismatch.returncode != 0


def test_release_image_binding_accepts_the_canonical_nodeodm_digest_only_exception() -> None:
    """The stage accepts the same pinned NodeODM exception as release evidence v1."""
    stage = _BIN / "external-runtime-stage.sh"
    reference = "opendronemap/nodeodm@sha256:" + (
        "cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2"
    )
    image_id = "sha256:" + "b" * 64
    shell = r'''source "$1"
expected_reference="$2"
actual_image_id="$3"
docker() {
  if [[ "$4" == '{{.Id}}' ]]; then
    printf '%s\n' "$actual_image_id"
  else
    printf '%s\n' "$expected_reference"
  fi
}
verify_image_binding "$2" "$3"
'''

    result = subprocess.run(
        ["bash", "-c", shell, "bash", str(stage), reference, image_id],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_product_binding_requires_canonical_digest_in_record_and_local_observation() -> None:
    """A mutable local tag cannot replace its immutable product release digest."""
    stage = _BIN / "external-runtime-stage.sh"
    reference = "registry.example/ksi-core:2026.09.10@sha256:" + "a" * 64
    image_id = "sha256:" + "b" * 64
    canonical_digest = "registry.example/ksi-core@sha256:" + "a" * 64
    wrong_digest = "registry.example/ksi-core@sha256:" + "c" * 64
    shell = r'''source "$1"
expected_image_id="$3"
actual_repo_digest="$5"
docker() {
  if [[ "$4" == '{{.Id}}' ]]; then
    printf '%s\n' "$expected_image_id"
  else
    printf '%s\n' "$actual_repo_digest"
  fi
}
verify_product_image_binding core "$2" "$3" "$4"
'''
    valid = subprocess.run(
        [
            "bash",
            "-c",
            shell,
            "bash",
            str(stage),
            reference,
            image_id,
            json.dumps([canonical_digest]),
            canonical_digest,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert valid.returncode == 0, valid.stderr

    substituted_record = subprocess.run(
        [
            "bash",
            "-c",
            shell,
            "bash",
            str(stage),
            reference,
            image_id,
            json.dumps([wrong_digest]),
            canonical_digest,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert substituted_record.returncode != 0

    substituted_local = subprocess.run(
        [
            "bash",
            "-c",
            shell,
            "bash",
            str(stage),
            reference,
            image_id,
            json.dumps([canonical_digest]),
            wrong_digest,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert substituted_local.returncode != 0


def test_canonical_inventory_and_candidate_host_binding_use_distinct_exact_source_sets(
    tmp_path: Path,
) -> None:
    """The full supply-chain inventory is distinct from the three Compose dependencies."""
    source_commit = "a" * 40
    canonical_images, candidate_images = _runtime_image_reference_sets()
    assert len(canonical_images) > len(candidate_images) == 3
    artifact = {
        "name": "proof.json",
        "type": "cyclonedx-json",
        "bytes": 1,
        "sha256": "sha256:" + "b" * 64,
    }
    scanner = {**artifact, "name": "scanner.json", "type": "scanner-json"}

    def validate(images: list[str]) -> subprocess.CompletedProcess[str]:
        evidence = {
            "schemaVersion": "1.0",
            "generatedAtUtc": "2026-09-11T12:34:56Z",
            "source": {"gitCommitSha": source_commit},
            "productImages": [
                {
                    "reference": "registry.example/ksi-core:2026.09.11@sha256:" + "c" * 64,
                    "sbom": artifact,
                    "scanner": scanner,
                },
                {
                    "reference": "registry.example/ksi-dashboard:2026.09.11@sha256:"
                    + "d" * 64,
                    "sbom": artifact,
                    "scanner": scanner,
                },
            ],
            "externalRuntimeImages": images,
        }
        path = tmp_path / "release-evidence.json"
        path.write_text(json.dumps(evidence), encoding="utf-8")
        return subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; validate_canonical_release_evidence "$2" "$3" "$4"',
                "bash",
                str(_STAGE),
                str(path),
                source_commit,
                json.dumps(canonical_images),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    assert validate(canonical_images).returncode == 0
    assert validate(canonical_images[:-1]).returncode != 0
    assert validate(
        [*canonical_images, "registry.example/extra:1.0@sha256:" + "e" * 64]
    ).returncode != 0
    substituted = [
        "caddy:2.10.1-alpine@sha256:"
        "4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d"
        if image == candidate_images[0]
        else image
        for image in canonical_images
    ]
    assert validate(
        substituted
    ).returncode != 0


def _native_grype_report(image_id: str) -> bytes:
    """A labeled compatibility fixture, not image/release/security evidence."""
    return json.dumps({
        "descriptor": {
            "name": "grype", "version": "0.120.0", "timestamp": "2026-10-04",
            "configuration": {}, "db": {
                "status": {"valid": True, "schemaVersion": "v6.1.10", "built": "2026-10-03"},
                "providers": {},
            },
        },
        "source": {"type": "image", "target": {
            "imageID": image_id, "os": "linux", "architecture": "arm64",
        }},
        "matches": [],
    }).encode()


def test_runtime_scanner_accepts_native_grype_only_with_exact_image_binding(tmp_path: Path) -> None:
    image_id = "sha256:" + "a" * 64
    path = tmp_path / "native.json"

    def validate(payload: bytes, expected_id: str) -> subprocess.CompletedProcess[str]:
        path.write_bytes(payload)
        return subprocess.run([
            "bash", "-c", 'source "$1"; verify_artifact_binding "$2" "$3" "$4" scanner-json 1 "$5"',
            "bash", str(_STAGE), str(path), "sha256:" + hashlib.sha256(payload).hexdigest(),
            str(len(payload)), expected_id,
        ], capture_output=True, text=True, check=False)

    original = _native_grype_report(image_id)
    good = validate(original, image_id)
    assert good.returncode == 0, good.stderr
    assert path.read_bytes() == original
    for expected_id in ["", "sha256:" + "b" * 64]:
        assert validate(original, expected_id).returncode != 0
    invalid_version = original.replace(b"0.120.0", b"0.121.0")
    assert validate(invalid_version, image_id).returncode != 0
    mixed = json.loads(original)
    mixed["scanner"] = {"name": "test", "schemaVersion": "1.0"}
    assert validate(json.dumps(mixed).encode(), image_id).returncode != 0
    assert validate(b'{"scanner":{"name":"test","schemaVersion":"1.0"}}', "").returncode == 0


@pytest.mark.parametrize("native_scanner", [False, True])
@pytest.mark.parametrize("host_version", ["v1", "v2"])
def test_stage_accepts_a_canonical_release_evidence_manifest_only_with_its_exact_host_binding(
    tmp_path: Path, native_scanner: bool, host_version: str,
) -> None:
    """The v1 producer shape is not reinterpreted as host-local provenance.

    Breaking change caught: a stage gate that expects the former ad-hoc
    ``sourceCommit``/``images``/top-level-artifact shape rejects the canonical
    release-evidence producer.  The host observation is separate, so a mutable
    ``:local`` tag is only a Docker lookup handle and never a provenance field.
    """
    source_commit = "a" * 40
    core_reference = "registry.example/ksi-core:2026.09.10@sha256:" + "b" * 64
    dashboard_reference = "registry.example/ksi-dashboard:2026.09.10@sha256:" + "c" * 64
    inspector_reference = "registry.example/ksi-inspector:2026.09.10@sha256:" + "d" * 64
    measurement_reference = "registry.example/ksi-measurement:2026.09.10@sha256:" + "e" * 64
    core_image_id = "sha256:" + "1" * 64
    dashboard_image_id = "sha256:" + "2" * 64
    inspector_image_id = "sha256:" + "3" * 64
    measurement_image_id = "sha256:" + "4" * 64
    inspector_scan_id, measurement_scan_id = inspector_image_id, measurement_image_id
    oci_fixtures = {}
    if host_version == "v2":
        oci_fixtures = {role: make_oci_fixture(role, source_commit)
                        for role in ("inspector", "measurement")}
        inspector_image_id = oci_fixtures["inspector"].index_id
        measurement_image_id = oci_fixtures["measurement"].index_id
        inspector_scan_id = oci_fixtures["inspector"].config_id
        measurement_scan_id = oci_fixtures["measurement"].config_id
    canonical_images, candidate_images = _runtime_image_reference_sets()

    artifacts: dict[str, dict[str, object]] = {}
    artifact_contents = {
        "core.sbom": b'{"bomFormat":"CycloneDX","specVersion":"1.5"}',
        "core.scanner": b'{"scanner":{"name":"test","schemaVersion":"1.0"},"results":[]}',
        "dashboard.sbom": b'{"bomFormat":"CycloneDX","specVersion":"1.5","components":[]}',
        "dashboard.scanner": b'{"scanner":{"name":"test","schemaVersion":"1.0"},"results":[{}]}',
        "inspector.sbom": b'{"bomFormat":"CycloneDX","specVersion":"1.5","metadata":{}}',
        "inspector.scanner": b'{"scanner":{"name":"test","schemaVersion":"1.0"},"matches":[]}',
        "measurement.sbom": b'{"bomFormat":"CycloneDX","specVersion":"1.5","components":[{}]}',
        "measurement.scanner": b'{"scanner":{"name":"test","schemaVersion":"1.0"},"findings":[]}',
    }
    if native_scanner:
        artifact_contents["inspector.scanner"] = _native_grype_report(inspector_scan_id)
        artifact_contents["measurement.scanner"] = _native_grype_report(measurement_scan_id)
    for role, fixture in oci_fixtures.items():
        artifact_contents[role + ".tar"] = fixture.payload
    for name, contents in artifact_contents.items():
        path = tmp_path / name
        path.write_bytes(contents)
        artifacts[name] = {
            "path": str(path),
            "sha256": "sha256:" + hashlib.sha256(contents).hexdigest(),
            "bytes": len(contents),
        }

    def release_artifact(name: str, kind: str) -> dict[str, object]:
        artifact = artifacts[name]
        return {
            "name": Path(name).name,
            "type": kind,
            "bytes": artifact["bytes"],
            "sha256": artifact["sha256"],
        }

    release_evidence = {
        "schemaVersion": "1.0",
        "generatedAtUtc": "2026-09-10T12:34:56Z",
        "source": {"gitCommitSha": source_commit},
        "productImages": [
            {
                "reference": core_reference,
                "sbom": release_artifact("core.sbom", "cyclonedx-json"),
                "scanner": release_artifact("core.scanner", "scanner-json"),
            },
            {
                "reference": dashboard_reference,
                "sbom": release_artifact("dashboard.sbom", "cyclonedx-json"),
                "scanner": release_artifact("dashboard.scanner", "scanner-json"),
            },
        ],
        "externalRuntimeImages": canonical_images,
    }
    evidence_path = tmp_path / "release-evidence.json"
    evidence_bytes = json.dumps(release_evidence, separators=(",", ":")).encode("utf-8")
    evidence_path.write_bytes(evidence_bytes)
    evidence_path.chmod(0o600)
    evidence_digest = "sha256:" + hashlib.sha256(evidence_bytes).hexdigest()

    def observed_artifact(name: str, artifact_type: str) -> dict[str, object]:
        artifact = artifacts[name]
        return {
            "path": artifact["path"],
            "sha256": artifact["sha256"],
            "bytes": artifact["bytes"],
            "type": artifact_type,
        }

    host_binding: dict[str, Any] = {
        "schemaVersion": "external-runtime-host-binding." + host_version,
        "releaseEvidence": {"sha256": evidence_digest},
        "source": {"gitCommitSha": source_commit},
        "productImages": [
            {
                "component": "core",
                "releaseReference": core_reference,
                "dockerImageId": core_image_id,
                "repoDigests": ["registry.example/ksi-core@sha256:" + "b" * 64],
                "sbom": observed_artifact("core.sbom", "cyclonedx-json"),
                "scanner": observed_artifact("core.scanner", "scanner-json"),
            },
            {
                "component": "dashboard",
                "releaseReference": dashboard_reference,
                "dockerImageId": dashboard_image_id,
                "repoDigests": ["registry.example/ksi-dashboard@sha256:" + "c" * 64],
                "sbom": observed_artifact("dashboard.sbom", "cyclonedx-json"),
                "scanner": observed_artifact("dashboard.scanner", "scanner-json"),
            },
        ],
        "runtimeProducts": [
            {
                "role": "inspector",
                "releaseReference": inspector_reference,
                "dockerImageId": inspector_image_id,
                "repoDigests": ["registry.example/ksi-inspector@sha256:" + "d" * 64],
                "sbom": observed_artifact("inspector.sbom", "cyclonedx-json"),
                "scanner": observed_artifact("inspector.scanner", "scanner-json"),
            },
            {
                "role": "measurement",
                "releaseReference": measurement_reference,
                "dockerImageId": measurement_image_id,
                "repoDigests": ["registry.example/ksi-measurement@sha256:" + "e" * 64],
                "sbom": observed_artifact("measurement.sbom", "cyclonedx-json"),
                "scanner": observed_artifact("measurement.scanner", "scanner-json"),
            },
        ],
        "externalRuntimeImages": [
            {
                "releaseReference": "caddy:2.10.2-alpine@sha256:"
                "4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d",
                "dockerImageId": "sha256:" + "5" * 64,
                "repoDigests": [
                    "caddy@sha256:"
                    "4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d"
                ],
            },
            {
                "releaseReference": "minio/mc:RELEASE.2025-08-13T08-35-41Z@sha256:"
                "a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727",
                "dockerImageId": "sha256:" + "6" * 64,
                "repoDigests": [
                    "minio/mc@sha256:"
                    "a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727"
                ],
            },
            {
                "releaseReference": "minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:"
                "14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e",
                "dockerImageId": "sha256:" + "7" * 64,
                "repoDigests": [
                    "minio/minio@sha256:"
                    "14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e"
                ],
            },
        ],
    }
    if host_version == "v2":
        for runtime in host_binding["runtimeProducts"]:
            runtime["ociArchive"] = observed_artifact(runtime["role"] + ".tar", "oci-archive")
    binding_path = tmp_path / "host-binding.json"
    binding_path.write_text(json.dumps(host_binding, separators=(",", ":")), encoding="utf-8")
    binding_path.chmod(0o600)
    expected_external_bindings = list(host_binding["externalRuntimeImages"])
    assert sorted(
        binding["releaseReference"] for binding in expected_external_bindings
    ) == candidate_images

    shell = r'''source "$1"
repo_dir="$2"
KSI_EXTERNAL_RC_RELEASE_EVIDENCE="$3"
KSI_EXTERNAL_RC_HOST_BINDING="$4"
expected_commit="$5"
core_id="$6"
dashboard_id="$7"
inspector_id="$8"
    measurement_id="$9"
python3() {
  if [[ "$1" == */verify_external_oci_archive.py && -n "${KSI_TEST_OCI_CLI:-}" ]]; then
    printf 'sha256:%s\n' "$(printf 'f%.0s' {1..64})"
    [[ "$KSI_TEST_OCI_CLI" != nonzero ]] || return 1
    printf 'malformed extra output\n'
    return 0
  fi
  command python3 "$@"
}
git() {
  if [[ "$1" == "-C" && "$3" == "status" ]]; then
    if [[ "${KSI_TEST_DIRTY_SOURCE:-0}" == 1 ]]; then printf ' M fixture-dirty-source\n'; fi
    return 0
  fi
  if [[ "$1" == "-C" && "$3" == "rev-parse" && "$4" == "HEAD" ]]; then
    printf '%s\n' "$expected_commit"
    return 0
  fi
  command git "$@"
}
docker() {
  [[ "$1" == "image" && "$2" == "inspect" && "$3" == "--format" ]] || return 97
  local format="$4" reference="$5" image_id repo_digest
  case "$reference" in
    ksi-external-rc-core:local)
      image_id="$core_id"
      repo_digest="registry.example/ksi-core@sha256:"$(printf 'b%.0s' {1..64})
      ;;
    ksi-external-rc-dashboard:local)
      image_id="$dashboard_id"
      repo_digest="registry.example/ksi-dashboard@sha256:"$(printf 'c%.0s' {1..64})
      ;;
    ksi-external-rc-inspector:local)
      image_id="$inspector_id"
      repo_digest="registry.example/ksi-inspector@sha256:"$(printf 'd%.0s' {1..64})
      ;;
    ksi-external-rc-measurement:local)
      image_id="$measurement_id"
      repo_digest="registry.example/ksi-measurement@sha256:"$(printf 'e%.0s' {1..64})
      ;;
    caddy:2.10.2-alpine@sha256:*)
      image_id="sha256:"$(printf '5%.0s' {1..64})
      repo_digest="caddy@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d"
      ;;
    minio/mc:RELEASE.2025-08-13T08-35-41Z@sha256:*)
      image_id="sha256:"$(printf '6%.0s' {1..64})
      repo_digest="minio/mc@sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727"
      ;;
    minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:*)
      image_id="sha256:"$(printf '7%.0s' {1..64})
      repo_digest="minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e"
      ;;
    *) return 98 ;;
  esac
  if [[ "$format" == '{{.Id}}' ]]; then
    printf '%s\n' "$image_id"
  else
    printf '%s\n' "$repo_digest"
  fi
}
KSI_EXTERNAL_RC_CORE_IMAGE_ID="sha256:$(printf 'f%.0s' {1..64})"
KSI_EXTERNAL_RC_DASHBOARD_IMAGE_ID="sha256:$(printf 'f%.0s' {1..64})"
KSI_EXTERNAL_RC_MINIO_IMAGE_ID="sha256:$(printf 'f%.0s' {1..64})"
KSI_EXTERNAL_RC_MC_IMAGE_ID="sha256:$(printf 'f%.0s' {1..64})"
KSI_EXTERNAL_RC_CADDY_IMAGE_ID="sha256:$(printf 'f%.0s' {1..64})"
require_release_evidence
[[ "$KSI_EXTERNAL_RC_CORE_IMAGE_ID" == "$core_id" ]]
[[ "$KSI_EXTERNAL_RC_DASHBOARD_IMAGE_ID" == "$dashboard_id" ]]
[[ "$KSI_EXTERNAL_RC_CADDY_IMAGE_ID" == "sha256:$(printf '5%.0s' {1..64})" ]]
[[ "$KSI_EXTERNAL_RC_MC_IMAGE_ID" == "sha256:$(printf '6%.0s' {1..64})" ]]
[[ "$KSI_EXTERNAL_RC_MINIO_IMAGE_ID" == "sha256:$(printf '7%.0s' {1..64})" ]]
'''
    result = subprocess.run(
        [
            "bash",
            "-c",
            shell,
            "bash",
            str(_STAGE),
            str(_ROOT),
            str(evidence_path),
            str(binding_path),
source_commit,
            core_image_id,
            dashboard_image_id,
            inspector_image_id,
            measurement_image_id,
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    dirty_source = subprocess.run(
        result.args, text=True, capture_output=True, check=False,
        env={**os.environ, "KSI_TEST_DIRTY_SOURCE": "1"},
    )
    assert dirty_source.returncode != 0
    assert "exact source checkout must be clean" in dirty_source.stderr

    if host_version == "v2":
        for failure in ("nonzero", "malformed"):
            bad_cli = subprocess.run(
                result.args, text=True, capture_output=True, check=False,
                env={**os.environ, "KSI_TEST_OCI_CLI": failure},
            )
            assert bad_cli.returncode != 0
            assert "OCI archive" in bad_cli.stderr
        for role_index in (0, 1):
            runtime = host_binding["runtimeProducts"][role_index]
            original = dict(runtime["ociArchive"])
            runtime["ociArchive"]["sha256"] = "sha256:" + "0" * 64
            binding_path.write_text(json.dumps(host_binding), encoding="utf-8")
            bad_archive = subprocess.run(result.args, text=True, capture_output=True, check=False)
            assert bad_archive.returncode != 0
            assert runtime["role"] + " OCI archive" in bad_archive.stderr
            runtime["ociArchive"] = original
        binding_path.write_text(json.dumps(host_binding), encoding="utf-8")
        assert all((tmp_path / (role + ".tar")).read_bytes() == fixture.payload
                   for role, fixture in oci_fixtures.items())

    if native_scanner:
        # An actual store reporting an OCI index instead of the config must block,
        # not reinterpret the report's config ID as that index or use a role alias.
        wrong_image = _native_grype_report(measurement_scan_id)
        (tmp_path / "inspector.scanner").write_bytes(wrong_image)
        host_binding["runtimeProducts"][0]["scanner"] = {
            "path": str(tmp_path / "inspector.scanner"),
            "sha256": "sha256:" + hashlib.sha256(wrong_image).hexdigest(),
            "bytes": len(wrong_image), "type": "scanner-json",
        }
        binding_path.write_text(json.dumps(host_binding), encoding="utf-8")
        different_config = subprocess.run(result.args, text=True, capture_output=True, check=False)
        assert different_config.returncode != 0
        assert "inspector scanner artifact differs" in different_config.stderr
        (tmp_path / "inspector.scanner").write_bytes(artifact_contents["inspector.scanner"])
        host_binding["runtimeProducts"][0]["scanner"] = observed_artifact(
            "inspector.scanner", "scanner-json",
        )
        if host_version == "v2":
            bad_platform = json.loads(artifact_contents["inspector.scanner"])
            bad_platform["source"]["target"]["architecture"] = "amd64"
            payload = json.dumps(bad_platform).encode()
            (tmp_path / "inspector.scanner").write_bytes(payload)
            host_binding["runtimeProducts"][0]["scanner"] = {
                "path": str(tmp_path / "inspector.scanner"), "type": "scanner-json",
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
            }
            binding_path.write_text(json.dumps(host_binding), encoding="utf-8")
            mismatched_platform = subprocess.run(
                result.args, text=True, capture_output=True, check=False,
            )
            assert mismatched_platform.returncode != 0
            assert "NATIVE_PLATFORM" in mismatched_platform.stderr
            (tmp_path / "inspector.scanner").write_bytes(artifact_contents["inspector.scanner"])
            host_binding["runtimeProducts"][0]["scanner"] = observed_artifact(
                "inspector.scanner", "scanner-json",
            )

    host_binding["runtimeProducts"][0]["repoDigests"] = [
        "registry.example/ksi-inspector@sha256:" + "9" * 64,
    ]
    binding_path.write_text(json.dumps(host_binding), encoding="utf-8")
    wrong_repo_digest = subprocess.run(result.args, text=True, capture_output=True, check=False)
    assert wrong_repo_digest.returncode != 0
    assert "inspector local image observation differs" in wrong_repo_digest.stderr
    host_binding["runtimeProducts"][0]["repoDigests"] = [
        "registry.example/ksi-inspector@sha256:" + "d" * 64,
    ]

    host_binding["externalRuntimeImages"] = expected_external_bindings[:-1]
    binding_path.write_text(json.dumps(host_binding, separators=(",", ":")), encoding="utf-8")
    missing_candidate_binding = subprocess.run(
        result.args, text=True, capture_output=True, check=False
    )
    assert missing_candidate_binding.returncode != 0
    assert "host image binding is incomplete" in missing_candidate_binding.stderr

    extra_reference = next(
        reference for reference in canonical_images if reference not in candidate_images
    )
    extra_name_and_tag, extra_digest = extra_reference.rsplit("@", maxsplit=1)
    host_binding["externalRuntimeImages"] = [
        *expected_external_bindings,
        {
            "releaseReference": extra_reference,
            "dockerImageId": "sha256:" + "8" * 64,
            "repoDigests": [extra_name_and_tag.rsplit(":", maxsplit=1)[0] + "@" + extra_digest],
        },
    ]
    binding_path.write_text(json.dumps(host_binding, separators=(",", ":")), encoding="utf-8")
    extra_candidate_binding = subprocess.run(
        result.args, text=True, capture_output=True, check=False
    )
    assert extra_candidate_binding.returncode != 0
    assert "host image binding is incomplete" in extra_candidate_binding.stderr

    substituted_binding = [dict(binding) for binding in expected_external_bindings]
    substituted_binding[0]["releaseReference"] = (
        "caddy:2.10.1-alpine@sha256:"
        "4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d"
    )
    host_binding["externalRuntimeImages"] = substituted_binding
    binding_path.write_text(json.dumps(host_binding, separators=(",", ":")), encoding="utf-8")
    substituted_candidate_binding = subprocess.run(
        result.args, text=True, capture_output=True, check=False
    )
    assert substituted_candidate_binding.returncode != 0
    assert "host image binding is incomplete" in substituted_candidate_binding.stderr

    host_binding["externalRuntimeImages"] = expected_external_bindings

    host_binding["releaseEvidence"] = {"sha256": "sha256:" + "f" * 64}
    binding_path.write_text(json.dumps(host_binding, separators=(",", ":")), encoding="utf-8")
    substituted = subprocess.run(
        result.args,
        text=True,
        capture_output=True,
        check=False,
    )

    assert substituted.returncode != 0
    assert "does not bind this evidence" in substituted.stderr

    host_binding["releaseEvidence"] = {"sha256": evidence_digest}
    host_binding["productImages"][0]["dockerImageId"] = "sha256:" + "9" * 64
    binding_path.write_text(json.dumps(host_binding, separators=(",", ":")), encoding="utf-8")
    image_substituted = subprocess.run(
        result.args,
        text=True,
        capture_output=True,
        check=False,
    )

    assert image_substituted.returncode != 0
    assert "core local image observation differs" in image_substituted.stderr

    host_binding["productImages"][0]["dockerImageId"] = core_image_id
    host_binding["productImages"][0]["releaseReference"] = dashboard_reference
    host_binding["productImages"][1]["releaseReference"] = core_reference
    binding_path.write_text(json.dumps(host_binding, separators=(",", ":")), encoding="utf-8")
    component_substituted = subprocess.run(
        result.args,
        text=True,
        capture_output=True,
        check=False,
    )

    assert component_substituted.returncode != 0
    assert (
        "core release reference does not identify the core product image"
        in component_substituted.stderr
    )

    host_binding["productImages"][0]["releaseReference"] = core_reference
    host_binding["productImages"][1]["releaseReference"] = dashboard_reference
    host_binding["productImages"][0]["repoDigests"] = []
    binding_path.write_text(json.dumps(host_binding, separators=(",", ":")), encoding="utf-8")
    empty_digest_list = subprocess.run(result.args, text=True, capture_output=True, check=False)

    assert empty_digest_list.returncode != 0
    assert "host image binding is incomplete" in empty_digest_list.stderr

    host_binding["productImages"][0]["repoDigests"] = [
        "registry.example/ksi-core@sha256:" + "b" * 64
    ]
    for contents, label in (
        (b"not JSON", "plaintext"),
        (b'{"unterminated":', "malformed"),
        (b'{"scanner":{"name":"test","schemaVersion":"1.0"},"results":[]}', "wrong type"),
        (b"{}", "empty object"),
    ):
        (tmp_path / "inspector.sbom").write_bytes(contents)
        host_binding["runtimeProducts"][0]["sbom"] = {
            "path": str(tmp_path / "inspector.sbom"),
            "sha256": "sha256:" + hashlib.sha256(contents).hexdigest(),
            "bytes": len(contents),
            "type": "cyclonedx-json",
        }
        binding_path.write_text(json.dumps(host_binding, separators=(",", ":")), encoding="utf-8")
        invalid_runtime_artifact = subprocess.run(
            result.args, text=True, capture_output=True, check=False
        )

        assert invalid_runtime_artifact.returncode != 0, label
        assert "inspector SBOM artifact differs" in invalid_runtime_artifact.stderr, label

    restored_inspector_sbom = b'{"bomFormat":"CycloneDX","specVersion":"1.5","metadata":{}}'
    (tmp_path / "inspector.sbom").write_bytes(restored_inspector_sbom)
    host_binding["runtimeProducts"][0]["sbom"] = {
        "path": str(tmp_path / "inspector.sbom"),
        "sha256": "sha256:" + hashlib.sha256(restored_inspector_sbom).hexdigest(),
        "bytes": len(restored_inspector_sbom),
        "type": "cyclonedx-json",
    }
    missing_scanner_schema = b'{"scanner":{"name":"test"},"matches":[]}'
    (tmp_path / "inspector.scanner").write_bytes(missing_scanner_schema)
    host_binding["runtimeProducts"][0]["scanner"] = {
        "path": str(tmp_path / "inspector.scanner"),
        "sha256": "sha256:" + hashlib.sha256(missing_scanner_schema).hexdigest(),
        "bytes": len(missing_scanner_schema),
        "type": "scanner-json",
    }
    binding_path.write_text(json.dumps(host_binding, separators=(",", ":")), encoding="utf-8")
    missing_scanner_identity = subprocess.run(
        result.args, text=True, capture_output=True, check=False
    )

    assert missing_scanner_identity.returncode != 0
    assert "inspector scanner artifact differs" in missing_scanner_identity.stderr


def test_host_binding_schema_accepts_separate_runtime_products_and_dependencies() -> None:
    """KSI runtime roles are distinct from canonical external dependencies."""
    schema = json.loads(
        (_ROOT / "contracts" / "schemas" / "external-runtime-host-binding.v1.json").read_text(
            encoding="utf-8"
        )
    )
    digest = "sha256:" + "a" * 64
    artifact = {
        "path": "/var/lib/ksi-external-runtime/evidence/artifact.json",
        "sha256": digest,
        "bytes": 20,
        "type": "cyclonedx-json",
    }
    scanner_artifact = {**artifact, "type": "scanner-json"}
    image = {
        "releaseReference": "registry.example/ksi-component:2026.09.10@" + digest,
        "dockerImageId": digest,
        "repoDigests": ["registry.example/ksi-component@" + digest],
        "sbom": artifact,
        "scanner": scanner_artifact,
    }
    binding = {
        "schemaVersion": "external-runtime-host-binding.v1",
        "releaseEvidence": {"sha256": digest},
        "source": {"gitCommitSha": "b" * 40},
        "productImages": [
            {**image, "component": "core"},
            {**image, "component": "dashboard"},
        ],
        "runtimeProducts": [
            {**image, "role": "inspector"},
            {**image, "role": "measurement"},
        ],
        "externalRuntimeImages": [
            {
                "releaseReference": "registry.example/dependency:2026.09.10@" + digest,
                "dockerImageId": digest,
                "repoDigests": ["registry.example/dependency@" + digest],
            },
            {
                "releaseReference": "registry.example/dependency-two:2026.09.10@" + digest,
                "dockerImageId": digest,
                "repoDigests": ["registry.example/dependency-two@" + digest],
            },
        ],
    }

    Draft202012Validator.check_schema(schema)

    assert list(Draft202012Validator(schema).iter_errors(binding)) == []


def test_v2_host_schema_and_stage_are_strict_without_extending_v1(tmp_path: Path) -> None:
    """A renamed/mixed v1 envelope cannot bypass required v2 archive evidence."""
    sha = "sha256:" + "a" * 64
    source = "b" * 40
    artifact = {"path": str(tmp_path / "artifact.json"), "bytes": 20,
                "sha256": sha, "type": "cyclonedx-json"}

    def image(name: str) -> dict[str, Any]:
        return {"releaseReference": f"registry.example/ksi-{name}:2026.10.04@" + sha,
                "dockerImageId": sha, "repoDigests": [f"registry.example/ksi-{name}@" + sha],
                "sbom": artifact, "scanner": {**artifact, "type": "scanner-json"}}

    archive = {**artifact, "type": "oci-archive", "path": str(tmp_path / "image.tar")}
    external = [{"releaseReference": f"registry.example/dep{i}:2026.10.04@" + sha,
                 "dockerImageId": sha, "repoDigests": [f"registry.example/dep{i}@" + sha]}
                for i in (1, 2)]
    binding = {
        "schemaVersion": "external-runtime-host-binding.v2", "releaseEvidence": {"sha256": sha},
        "source": {"gitCommitSha": source},
        "productImages": [{**image(name), "component": name} for name in ("core", "dashboard")],
        "runtimeProducts": [{**image(role), "role": role, "ociArchive": dict(archive)}
                            for role in ("inspector", "measurement")],
        "externalRuntimeImages": external,
    }
    schema_path = _ROOT / "contracts/schemas/external-runtime-host-binding.v2.json"
    assert schema_path.is_file(), "v2 host contract is not implemented"
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    binding_path = tmp_path / "binding.json"

    def stage(value: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        binding_path.write_text(json.dumps(value), encoding="utf-8")
        return subprocess.run([
            "bash", "-c", 'source "$1"; validate_host_binding "$2" "$3" "$4" "$5"',
            "bash", str(_STAGE), str(binding_path), source, sha,
            json.dumps(sorted(row["releaseReference"] for row in external)),
        ], capture_output=True, text=True, check=False)

    assert list(validator.iter_errors(binding)) == []
    good = stage(binding)
    assert good.returncode == 0, good.stderr
    for field, value in [("path", "relative.tar"), ("path", "/a/../image.tar"),
                         ("bytes", True), ("bytes", 1.5), ("bytes", 0), ("bytes", 1073741825),
                         ("type", "scanner-json"), ("sha256", "invalid"), ("extra", "unknown")]:
        bad = json.loads(json.dumps(binding))
        bad["runtimeProducts"][0]["ociArchive"][field] = value
        assert list(validator.iter_errors(bad))
        assert stage(bad).returncode != 0
    for change in ("missing", "unknown_version", "mixed", "declared_config", "duplicate_digest",
                   "duplicate_product_digest", "duplicate_external_digest"):
        bad = json.loads(json.dumps(binding))
        if change == "missing":
            del bad["runtimeProducts"][1]["ociArchive"]
        elif change == "unknown_version":
            bad["schemaVersion"] = "external-runtime-host-binding.v3"
        elif change == "mixed":
            bad["schemaVersion"] = "external-runtime-host-binding.v1"
        elif change == "declared_config":
            bad["runtimeProducts"][0]["configDigest"] = sha
        elif change == "duplicate_digest":
            bad["runtimeProducts"][0]["repoDigests"] *= 2
        elif change == "duplicate_product_digest":
            bad["productImages"][0]["repoDigests"] *= 2
        else:
            bad["externalRuntimeImages"][0]["repoDigests"] *= 2
        if change != "mixed":
            assert list(validator.iter_errors(bad))
        assert stage(bad).returncode != 0
    v1 = json.loads(json.dumps(binding))
    v1["schemaVersion"] = "external-runtime-host-binding.v1"
    for runtime in v1["runtimeProducts"]:
        del runtime["ociArchive"]
    assert stage(v1).returncode == 0
    v1_validator = Draft202012Validator(json.loads(
        (_ROOT / "contracts/schemas/external-runtime-host-binding.v1.json").read_text(),
    ))
    assert list(v1_validator.iter_errors(v1)) == []
    assert list(v1_validator.iter_errors(binding))


def test_bootstrap_binds_templates_and_markers_to_private_exact_inputs() -> None:
    """Bootstrap has no ambient template or partial-marker trust path."""
    bootstrap = _text(_BIN / "external-runtime-host-bootstrap.sh")
    preflight = _text(_BIN / "external-runtime-host-preflight.sh")

    assert "--template-manifest-sha256" in bootstrap
    assert "validate_template_manifest" in bootstrap
    assert "sha256sum" in bootstrap
    assert "ln -- \"$temporary\" \"$marker\"" in bootstrap
    assert "validate_existing_marker" in bootstrap
    assert "is_marker_temporary" in bootstrap
    assert "rm -f -- \"$temporary\"" in bootstrap
    assert "private_socket_identity" in bootstrap
    assert '"$links" == 1' in bootstrap
    assert '"$bus_identity_after" == "$bus_identity_before"' in bootstrap
    assert "-S \"$socket_path\" && ! -L \"$socket_path\"" in bootstrap
    assert "stat --format='%d:%i:%u:%g:%a:%h:%F'" in bootstrap
    assert "interval_overlaps_other_allocation" in bootstrap
    assert "ksi-external-runtime-socket-acl.service" in bootstrap
    assert "bin/ksi-external-runtime-socket-acl" in bootstrap
    assert "/usr/local/lib/ksi-external-runtime/bin" in bootstrap
    assert "/var/lib/ksi-external-runtime-preflight" in preflight
    assert "/var/lib/ksi-external-runtime-preflight" in bootstrap


def test_systemd_template_manifest_binds_each_installed_asset() -> None:
    """The committed manifest has one exact SHA256 for every bootstrap template."""
    manifest = _RUNTIME / "systemd" / "manifest.sha256"
    entries = {
        relative: digest
        for digest, relative in (
            line.split("  ", maxsplit=1)
            for line in manifest.read_text(encoding="utf-8").splitlines()
        )
    }
    required = {
        "dbus.socket.private.conf",
        "docker.service.private.conf",
        "ksi-external-runtime-directories.service",
        "ksi-external-runtime-socket-acl.service",
        "ksi-external-validation-worker.service",
        "bin/ksi-external-runtime-socket-acl",
        "user/ksi-external-inspector.socket",
        "user/ksi-external-inspector.service",
        "user/ksi-external-measurement.socket",
        "user/ksi-external-measurement.service",
        "user/ksi-inspector.slice",
        "user/ksi-measurement.slice",
    }
    assert set(entries) == required
    for relative, expected in entries.items():
        actual = hashlib.sha256((_RUNTIME / "systemd" / relative).read_bytes()).hexdigest()
        assert actual == expected


def _bootstrap_library_env(tmp_path: Path) -> dict[str, str]:
    runtime = tmp_path / "runtime"
    preflight = tmp_path / "preflight"
    runtime.mkdir(exist_ok=True)
    preflight.mkdir(exist_ok=True)
    subuid = tmp_path / "subuid"
    subgid = tmp_path / "subgid"
    subuid.touch(exist_ok=True)
    subgid.touch(exist_ok=True)
    return {
        **os.environ,
        "KSI_EXTERNAL_RUNTIME_BOOTSTRAP_LIBRARY_ONLY": "1",
        "KSI_EXTERNAL_RUNTIME_BASE": str(runtime),
        "KSI_EXTERNAL_RUNTIME_PREFLIGHT_DIR": str(preflight),
        "KSI_EXTERNAL_RUNTIME_SUBUID_FILE": str(subuid),
        "KSI_EXTERNAL_RUNTIME_SUBGID_FILE": str(subgid),
        "KSI_EXTERNAL_RUNTIME_TRUSTED_OWNER_UID": str(os.getuid()),
    }


def _run_bootstrap_helper(
    tmp_path: Path, shell: str, *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; shift; ' + shell, "bash", str(_BOOTSTRAP)],
        env=env or _bootstrap_library_env(tmp_path),
        text=True,
        capture_output=True,
        check=False,
    )


def test_bootstrap_direct_execution_cannot_enable_test_library_mode(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [str(_BOOTSTRAP)],
        env=_bootstrap_library_env(tmp_path),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "test-library mode is unavailable" in result.stderr


def test_marker_write_is_atomic_exact_and_leaves_no_temporary(tmp_path: Path) -> None:
    result = _run_bootstrap_helper(
        tmp_path,
        r'''
marker="$runtime_base/marker.json"
exact='{"schema":"marker.v1","value":1}'
conflict='{"schema":"marker.v1","value":2}'
write_marker "$marker" marker.v1 "$exact"
write_marker "$marker" marker.v1 "$exact"
if write_marker "$marker" marker.v1 "$conflict"; then exit 21; fi
[[ "$(find "$runtime_base" -name '.external-runtime-bootstrap.marker.*' -print -quit)" == "" ]]
''',
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("existing_side", ["subuid", "subgid"])
def test_partial_subordinate_range_rejects_overlap_in_other_map(
    tmp_path: Path, existing_side: str
) -> None:
    env = _bootstrap_library_env(tmp_path)
    subuid = Path(env["KSI_EXTERNAL_RUNTIME_SUBUID_FILE"])
    subgid = Path(env["KSI_EXTERNAL_RUNTIME_SUBGID_FILE"])
    inspector_map = subuid if existing_side == "subuid" else subgid
    other_map = subgid if existing_side == "subuid" else subuid
    inspector_map.write_text("ksi-inspector:196608:65536\n", encoding="utf-8")
    other_map.write_text("another-user:196608:65536\n", encoding="utf-8")

    result = _run_bootstrap_helper(tmp_path, "ensure_subordinate_maps", env=env)

    assert result.returncode != 0
    assert "overlaps another-user" in result.stderr
    assert "ksi-inspector" not in other_map.read_text(encoding="utf-8")


@pytest.mark.parametrize("locale", ["C", "ko_KR.utf8"])
def test_private_bus_rejects_hard_link_and_detects_substitution(
    tmp_path: Path, locale: str
) -> None:
    # A translated stat file type must not reject an otherwise valid private bus.
    # Both locales must still reject hard links and reveal socket substitution.
    env = {**_bootstrap_library_env(tmp_path), "LC_ALL": locale}
    bus = tmp_path / "bus.sock"
    linked = tmp_path / "bus-linked.sock"
    first = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    first.bind(str(bus))
    bus.chmod(0o600)
    try:
        if locale != "C":
            translated_type = subprocess.run(
                ["stat", "--format=%F", "--", str(bus)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            assert translated_type.returncode == 0, translated_type.stderr
            if translated_type.stdout.strip() != "소켓":
                pytest.skip("NOT_VERIFIED: Korean stat translation is unavailable")
        os.link(bus, linked)
        linked_result = _run_bootstrap_helper(
            tmp_path, f'private_socket_identity "{bus}" "{os.getuid()}"', env=env
        )
        assert linked_result.returncode != 0
        linked.unlink()
        before = _run_bootstrap_helper(
            tmp_path, f'private_socket_identity "{bus}" "{os.getuid()}"', env=env
        )
        assert before.returncode == 0, before.stderr
        bus.unlink()
        second = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            second.bind(str(bus))
            bus.chmod(0o600)
            after = _run_bootstrap_helper(
                tmp_path, f'private_socket_identity "{bus}" "{os.getuid()}"', env=env
            )
            assert after.returncode == 0, after.stderr
            assert after.stdout != before.stdout
        finally:
            second.close()
    finally:
        first.close()


def test_template_manifest_rejects_tamper_and_symlink(tmp_path: Path) -> None:
    env = _bootstrap_library_env(tmp_path)
    template_root = tmp_path / "templates"
    (template_root / "user").mkdir(parents=True)
    (template_root / "bin").mkdir()
    required = (
        "dbus.socket.private.conf",
        "docker.service.private.conf",
        "ksi-external-runtime-directories.service",
        "ksi-external-runtime-socket-acl.service",
        "ksi-external-validation-worker.service",
        "bin/ksi-external-runtime-socket-acl",
        "user/ksi-external-inspector.socket",
        "user/ksi-external-inspector.service",
        "user/ksi-external-measurement.socket",
        "user/ksi-external-measurement.service",
        "user/ksi-inspector.slice",
        "user/ksi-measurement.slice",
    )
    lines = []
    for relative in required:
        file = template_root / relative
        file.write_text(relative + "\n", encoding="utf-8")
        file.chmod(0o600)
        lines.append(f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {relative}")
    template_root.chmod(0o700)
    (template_root / "user").chmod(0o700)
    (template_root / "bin").chmod(0o700)
    manifest = tmp_path / "manifest.sha256"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest.chmod(0o600)
    digest = "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
    command = (
        f'template_root="{template_root}"; template_manifest="{manifest}"; '
        f'template_manifest_sha256="{digest}"; validate_template_manifest'
    )
    valid = _run_bootstrap_helper(tmp_path, command, env=env)
    assert valid.returncode == 0, valid.stderr

    target = template_root / required[0]
    original = target.read_bytes()
    target.write_text("tampered\n", encoding="utf-8")
    tampered = _run_bootstrap_helper(tmp_path, command, env=env)
    assert tampered.returncode != 0

    target.write_bytes(original)
    target.unlink()
    target.symlink_to(template_root / required[1])
    symlinked = _run_bootstrap_helper(tmp_path, command, env=env)
    assert symlinked.returncode != 0


def test_production_config_mount_cannot_create_quantitative_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Partial authority configuration rejects startup before opening journals."""
    from ksi_core.production import build_production_app
    from test_production_assembly import _apply_env, _valid_env

    _apply_env(monkeypatch, _valid_env(tmp_path))
    monkeypatch.setenv(
        "KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG",
        str(tmp_path / "mounted-but-untrusted-workflow.json"),
    )

    monkeypatch.delenv("KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG", raising=False)
    assert not list(tmp_path.rglob("*.jsonl"))
    with pytest.raises(RuntimeError, match="must be configured together"):
        build_production_app()
    assert not list(tmp_path.rglob("*.jsonl"))
