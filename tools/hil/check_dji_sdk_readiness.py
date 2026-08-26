#!/usr/bin/env python3
"""Inspect external MSDK/Dock build inputs without reading credential values.

SDK projects and provider contracts remain external or gitignored until their
licenses permit otherwise.  This preflight records only structural facts and
SHA-256 digests of non-secret build inputs.  Credential files are checked only
for owner-only permissions; their paths, values, and digests are not emitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

_DYNAMIC_VERSION = re.compile(r"(?:com\.dji|dji-sdk)[^\n\r]*?(?:\+|latest)", re.IGNORECASE)
_DJI_DEPENDENCY = re.compile(r"(?:com\.dji|dji-sdk)", re.IGNORECASE)


@dataclass(frozen=True)
class CredentialReadiness:
    configured: bool
    owner_only_regular_file: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ProviderReadiness:
    status: str
    reason_codes: tuple[str, ...]
    artifact_sha256: dict[str, str]
    credential: CredentialReadiness


@dataclass(frozen=True)
class DjiSdkReadiness:
    msdk_field: ProviderReadiness
    dji_dock: ProviderReadiness
    credential_values_recorded: bool = False
    flight_action_started: bool = False
    camera_write: bool = False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _is_git_ignored(path: Path, repo_root: Path) -> bool:
    completed = subprocess.run(
        ["git", "check-ignore", "--quiet", str(path)],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def _external_or_ignored(path: Path, repo_root: Path) -> bool:
    return not _inside(path, repo_root) or _is_git_ignored(path, repo_root)


def check_credential(path: Path | None, *, repo_root: Path) -> CredentialReadiness:
    if path is None:
        return CredentialReadiness(False, False, ("CREDENTIAL_NOT_CONFIGURED",))
    if path.is_symlink() or path.parent.is_symlink():
        return CredentialReadiness(True, False, ("CREDENTIAL_SYMLINK_FORBIDDEN",))
    try:
        info = path.stat()
    except OSError:
        return CredentialReadiness(True, False, ("CREDENTIAL_FILE_UNAVAILABLE",))
    reasons: list[str] = []
    if not stat.S_ISREG(info.st_mode):
        reasons.append("CREDENTIAL_NOT_REGULAR_FILE")
    if info.st_uid != os.geteuid():
        reasons.append("CREDENTIAL_NOT_CURRENT_USER_OWNED")
    if info.st_mode & 0o077:
        reasons.append("CREDENTIAL_NOT_0600")
    if not _external_or_ignored(path, repo_root):
        reasons.append("CREDENTIAL_INSIDE_REPO_NOT_IGNORED")
    return CredentialReadiness(True, not reasons, tuple(reasons))


def _safe_license(path: Path | None, *, repo_root: Path) -> tuple[dict[str, str], list[str]]:
    if path is None:
        return {}, ["LICENSE_NOT_CONFIGURED"]
    if path.is_symlink() or not path.is_file():
        return {}, ["LICENSE_UNAVAILABLE_OR_SYMLINK"]
    if not _external_or_ignored(path, repo_root):
        return {}, ["LICENSE_INSIDE_REPO_NOT_IGNORED"]
    return {"license": _sha256(path)}, []


def check_msdk(
    *,
    project_root: Path | None,
    license_path: Path | None,
    credential_path: Path | None,
    repo_root: Path,
) -> ProviderReadiness:
    credential = check_credential(credential_path, repo_root=repo_root)
    if project_root is None:
        return ProviderReadiness("NOT_CONFIGURED", ("MSDK_PROJECT_NOT_CONFIGURED",), {}, credential)
    reasons: list[str] = []
    artifacts, license_reasons = _safe_license(license_path, repo_root=repo_root)
    reasons.extend(license_reasons)
    if project_root.is_symlink() or not project_root.is_dir():
        reasons.append("MSDK_PROJECT_UNAVAILABLE_OR_SYMLINK")
        return ProviderReadiness("BLOCKED", tuple(reasons), artifacts, credential)
    if not _external_or_ignored(project_root, repo_root):
        reasons.append("MSDK_PROJECT_INSIDE_REPO_NOT_IGNORED")

    settings = sorted(project_root.glob("settings.gradle*"))
    builds = sorted(project_root.glob("build.gradle*")) + sorted(
        project_root.glob("*/build.gradle*")
    )
    if not settings:
        reasons.append("MSDK_GRADLE_SETTINGS_MISSING")
    if not builds:
        reasons.append("MSDK_GRADLE_BUILD_MISSING")
    dji_dependency_seen = False
    dynamic_dependency_seen = False
    for index, build_file in enumerate(builds):
        if build_file.is_symlink() or not build_file.is_file():
            reasons.append("MSDK_BUILD_FILE_SYMLINK_OR_INVALID")
            continue
        text = build_file.read_text(encoding="utf-8")
        dji_dependency_seen = dji_dependency_seen or bool(_DJI_DEPENDENCY.search(text))
        dynamic_dependency_seen = dynamic_dependency_seen or bool(_DYNAMIC_VERSION.search(text))
        artifacts[f"gradle_build_{index}"] = _sha256(build_file)
    for index, settings_file in enumerate(settings):
        if settings_file.is_symlink() or not settings_file.is_file():
            reasons.append("MSDK_SETTINGS_FILE_SYMLINK_OR_INVALID")
            continue
        artifacts[f"gradle_settings_{index}"] = _sha256(settings_file)
    local_sdk = sorted(project_root.rglob("*.aar"))
    for index, sdk_file in enumerate(local_sdk):
        if not sdk_file.is_symlink() and sdk_file.is_file():
            artifacts[f"local_aar_{index}"] = _sha256(sdk_file)
    if not dji_dependency_seen and not local_sdk:
        reasons.append("PINNED_MSDK_DEPENDENCY_OR_AAR_MISSING")
    if dynamic_dependency_seen:
        reasons.append("DYNAMIC_MSDK_VERSION_FORBIDDEN")
    return ProviderReadiness(
        "READY_FOR_BUILD" if not reasons else "BLOCKED",
        tuple(reasons),
        artifacts,
        credential,
    )


def check_dock(
    *,
    openapi_path: Path | None,
    license_path: Path | None,
    credential_path: Path | None,
    repo_root: Path,
) -> ProviderReadiness:
    credential = check_credential(credential_path, repo_root=repo_root)
    if openapi_path is None:
        return ProviderReadiness("NOT_CONFIGURED", ("DOCK_OPENAPI_NOT_CONFIGURED",), {}, credential)
    artifacts, reasons = _safe_license(license_path, repo_root=repo_root)
    if openapi_path.is_symlink() or not openapi_path.is_file():
        reasons.append("DOCK_OPENAPI_UNAVAILABLE_OR_SYMLINK")
        return ProviderReadiness("BLOCKED", tuple(reasons), artifacts, credential)
    if not _external_or_ignored(openapi_path, repo_root):
        reasons.append("DOCK_OPENAPI_INSIDE_REPO_NOT_IGNORED")
    try:
        text = openapi_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        reasons.append("DOCK_OPENAPI_NOT_UTF8")
    else:
        is_openapi = False
        if openapi_path.suffix.lower() == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                reasons.append("DOCK_OPENAPI_JSON_INVALID")
            else:
                is_openapi = isinstance(payload, dict) and isinstance(payload.get("openapi"), str)
        elif openapi_path.suffix.lower() in {".yaml", ".yml"}:
            is_openapi = bool(re.search(r"^openapi:\s*['\"]?3\.", text, re.MULTILINE))
        if not is_openapi:
            reasons.append("DOCK_OPENAPI_V3_MARKER_MISSING")
        artifacts["openapi"] = _sha256(openapi_path)
    return ProviderReadiness(
        "READY_FOR_BUILD" if not reasons else "BLOCKED",
        tuple(reasons),
        artifacts,
        credential,
    )


def inspect_readiness(
    *,
    repo_root: Path,
    msdk_root: Path | None,
    msdk_license: Path | None,
    msdk_credential: Path | None,
    dock_openapi: Path | None,
    dock_license: Path | None,
    dock_credential: Path | None,
) -> DjiSdkReadiness:
    return DjiSdkReadiness(
        msdk_field=check_msdk(
            project_root=msdk_root,
            license_path=msdk_license,
            credential_path=msdk_credential,
            repo_root=repo_root,
        ),
        dji_dock=check_dock(
            openapi_path=dock_openapi,
            license_path=dock_license,
            credential_path=dock_credential,
            repo_root=repo_root,
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--msdk-root", type=Path)
    parser.add_argument("--msdk-license", type=Path)
    parser.add_argument("--msdk-credential-file", type=Path)
    parser.add_argument("--dock-openapi", type=Path)
    parser.add_argument("--dock-license", type=Path)
    parser.add_argument("--dock-credential-file", type=Path)
    args = parser.parse_args(argv)
    readiness = inspect_readiness(
        repo_root=args.repo_root,
        msdk_root=args.msdk_root,
        msdk_license=args.msdk_license,
        msdk_credential=args.msdk_credential_file,
        dock_openapi=args.dock_openapi,
        dock_license=args.dock_license,
        dock_credential=args.dock_credential_file,
    )
    print(json.dumps(asdict(readiness), sort_keys=True, separators=(",", ":")))
    statuses = {readiness.msdk_field.status, readiness.dji_dock.status}
    return 0 if statuses == {"READY_FOR_BUILD"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
