"""Static deployment boundary for the external-reconstruction staging candidate.

These checks intentionally test the versioned host and Compose assets instead
of starting containers or changing the host.  The candidate may be prepared
only after a separate owner operation has supplied real image, SBOM, signature,
and authority inputs.  A repository checkout must therefore fail closed rather
than acquiring ambient Docker access or silently targeting Phase 2 staging.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import socket
import subprocess

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_DEPLOY = _ROOT / "deploy"
_RUNTIME = _DEPLOY / "external-runtime"
_BIN = _DEPLOY / "bin"
_BOOTSTRAP = _BIN / "external-runtime-host-bootstrap.sh"

_REQUIRED_ASSETS = (
    _DEPLOY / "compose.external-reconstruction.yaml",
    _DEPLOY / ".env.external-reconstruction.example",
    _RUNTIME / "README.md",
    _RUNTIME / "systemd" / "ksi-external-validation-worker.service",
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
    assert ".externalRuntimeImages | length > 0" in stage

    assert "network_mode: host" not in compose
    assert "KSI_EXTERNAL_RC_CORE_IMAGE" in compose
    assert "KSI_EXTERNAL_RC_DASHBOARD_IMAGE" in compose
    assert "ksi-external-rc-core:local" not in compose
    assert "ksi-external-rc-dashboard:local" not in compose
    assert '"127.0.0.1:${KSI_EXTERNAL_RC_IDENTITY_PORT:?set KSI_EXTERNAL_RC_IDENTITY_PORT}:8080"' in compose


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
        ["bash", "-c", shell, "bash", str(stage), reference, "sha256:" + "c" * 64, canonical_digest, image_id],
        text=True,
        capture_output=True,
        check=False,
    )
    assert mismatch.returncode != 0


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
        "ksi-external-validation-worker.service",
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


def test_private_bus_rejects_hard_link_and_detects_substitution(tmp_path: Path) -> None:
    env = _bootstrap_library_env(tmp_path)
    bus = tmp_path / "bus.sock"
    linked = tmp_path / "bus-linked.sock"
    first = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    first.bind(str(bus))
    bus.chmod(0o600)
    os.link(bus, linked)
    try:
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
    required = (
        "dbus.socket.private.conf",
        "docker.service.private.conf",
        "ksi-external-runtime-directories.service",
        "ksi-external-validation-worker.service",
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
    """A path alone must not activate the external quantitative workflow.

    Production receives no retained catalog, policy, evidence-currentness, or
    input-capability participant from this candidate.  Keeping its assembly
    absent is the safe state until those independently owned authorities have
    an approved production source.
    """
    from ksi_core.production import build_production_app
    from test_production_assembly import _apply_env, _valid_env

    _apply_env(monkeypatch, _valid_env(tmp_path))
    monkeypatch.setenv(
        "KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG",
        str(tmp_path / "mounted-but-untrusted-workflow.json"),
    )

    app = build_production_app()

    assert app.state.external_relative_volume_mapping_authority is None
    assert "external_relative_volume_store" not in vars(app.state)
    assert "external_result_workflow_service" not in vars(app.state)
