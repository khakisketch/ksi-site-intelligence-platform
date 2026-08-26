from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tools" / "hil"))

from check_dji_sdk_readiness import (  # noqa: E402
    check_credential,
    inspect_readiness,
)


def _msdk_project(root: Path, *, version: str = "5.15.0") -> Path:
    root.mkdir()
    (root / "settings.gradle.kts").write_text('rootProject.name = "fixture"\n')
    (root / "build.gradle.kts").write_text(
        f'dependencies {{ implementation("com.dji:dji-sdk-v5-aircraft:{version}") }}\n'
    )
    return root


def _license(path: Path) -> Path:
    path.write_text("fixture license accepted for local test inputs\n", encoding="utf-8")
    return path


def _dock_spec(path: Path) -> Path:
    path.write_text(
        json.dumps({"openapi": "3.0.3", "info": {"title": "fixture", "version": "1"}}),
        encoding="utf-8",
    )
    return path


def test_unconfigured_inputs_are_not_ready(tmp_path: Path) -> None:
    readiness = inspect_readiness(
        repo_root=tmp_path,
        msdk_root=None,
        msdk_license=None,
        msdk_credential=None,
        dock_openapi=None,
        dock_license=None,
        dock_credential=None,
    )
    assert readiness.msdk_field.status == "NOT_CONFIGURED"
    assert readiness.dji_dock.status == "NOT_CONFIGURED"
    assert readiness.credential_values_recorded is False
    assert readiness.flight_action_started is False
    assert readiness.camera_write is False


def test_external_pinned_msdk_and_dock_inputs_are_build_ready(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    msdk = _msdk_project(external / "msdk")
    msdk_license = _license(external / "MSDK-EULA.txt")
    dock_spec = _dock_spec(external / "dock-openapi.json")
    dock_license = _license(external / "DOCK-EULA.txt")
    readiness = inspect_readiness(
        repo_root=repo,
        msdk_root=msdk,
        msdk_license=msdk_license,
        msdk_credential=None,
        dock_openapi=dock_spec,
        dock_license=dock_license,
        dock_credential=None,
    )
    assert readiness.msdk_field.status == "READY_FOR_BUILD"
    assert readiness.dji_dock.status == "READY_FOR_BUILD"
    assert readiness.msdk_field.artifact_sha256["license"]
    assert readiness.dji_dock.artifact_sha256["openapi"]
    assert readiness.msdk_field.credential.configured is False


def test_dynamic_msdk_dependency_is_blocked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    msdk = _msdk_project(external / "msdk", version="+")
    readiness = inspect_readiness(
        repo_root=repo,
        msdk_root=msdk,
        msdk_license=_license(external / "MSDK-EULA.txt"),
        msdk_credential=None,
        dock_openapi=None,
        dock_license=None,
        dock_credential=None,
    )
    assert readiness.msdk_field.status == "BLOCKED"
    assert "DYNAMIC_MSDK_VERSION_FORBIDDEN" in readiness.msdk_field.reason_codes


def test_credentials_are_permission_checked_without_value_or_digest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    credential = tmp_path / "provider.secret"
    credential.write_text("TOP-SECRET-VALUE", encoding="utf-8")
    credential.chmod(stat.S_IRUSR | stat.S_IWUSR)
    result = check_credential(credential, repo_root=repo)
    encoded = json.dumps(result.__dict__)
    assert result.owner_only_regular_file is True
    assert "TOP-SECRET-VALUE" not in encoded
    assert str(credential) not in encoded


def test_group_readable_credential_is_blocked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    credential = tmp_path / "provider.secret"
    credential.write_text("secret", encoding="utf-8")
    credential.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
    result = check_credential(credential, repo_root=repo)
    assert result.owner_only_regular_file is False
    assert result.reason_codes == ("CREDENTIAL_NOT_0600",)


def test_symlinked_credential_is_rejected(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        return
    repo = tmp_path / "repo"
    repo.mkdir()
    target = tmp_path / "target.secret"
    target.write_text("secret", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "link.secret"
    link.symlink_to(target)
    result = check_credential(link, repo_root=repo)
    assert result.reason_codes == ("CREDENTIAL_SYMLINK_FORBIDDEN",)
