#!/usr/bin/env python3
"""Read-only fail-closed validation for the local Analysis pilot Compose profile."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit

_MAX_ENV_BYTES = 64 * 1024
_SERVICE_UID = 10001
_ECMASCRIPT_TRIM_CHARS = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_SAFE_KEY = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_DIGEST_IMAGE = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}\Z")
_PORT = re.compile(r"[0-9]{1,5}\Z")
_REQUIRED = frozenset(
    {
        "KSI_ANALYSIS_PILOT_CORE_IMAGE_ID",
        "KSI_ANALYSIS_PILOT_DASHBOARD_IMAGE_ID",
        "KSI_ANALYSIS_PILOT_TAILNET_HOSTNAME",
        "KSI_ANALYSIS_PILOT_APP_ORIGIN",
        "KSI_ANALYSIS_PILOT_API_ORIGIN",
        "KSI_ANALYSIS_PILOT_OBJECTS_ORIGIN",
        "KSI_ANALYSIS_PILOT_APP_PORT",
        "KSI_ANALYSIS_PILOT_API_PORT",
        "KSI_ANALYSIS_PILOT_OBJECTS_PORT",
        "KSI_ANALYSIS_PILOT_OIDC_ISSUER",
        "KSI_ANALYSIS_PILOT_OIDC_AUDIENCE",
        "KSI_ANALYSIS_PILOT_OIDC_JWKS_URL",
        "KSI_ANALYSIS_PILOT_OIDC_CLIENT_ID",
        "KSI_ANALYSIS_PILOT_MINIO_ROOT_USER",
        "KSI_ANALYSIS_PILOT_MINIO_ROOT_PASSWORD",
        "KSI_ANALYSIS_PILOT_MINIO_CORE_ACCESS_KEY",
        "KSI_ANALYSIS_PILOT_MINIO_CORE_SECRET_KEY",
        "KSI_ANALYSIS_PILOT_CORE_PRINCIPAL_TOKENS_JSON",
        "KSI_ANALYSIS_PILOT_STATE_DIR",
        "KSI_ANALYSIS_PILOT_AUTHORITY_DIR",
        "KSI_ANALYSIS_PILOT_SECRET_DIR",
    }
)
_SERVICE_NAMES = frozenset({"core", "dashboard", "minio", "bucket-init"})
_FORBIDDEN_SERVICE_NAMES = frozenset(
    {"identity", "nodeodm", "processing-worker", "worker", "caddy", "dji-gateway"}
)
_AUTHORITY_FILES = (
    "device-attestation-keys.json",
    "oidc-subject-registry.json",
    "analysis/runtime.json",
    "analysis/activation.json",
    "analysis/activation-keys.json",
    "external/workflow.json",
    "external/provider.json",
)


class PreflightBlocked(ValueError):
    """Candidate is incomplete or unsafe; message contains only a fixed code."""


def _blocked(code: str) -> PreflightBlocked:
    return PreflightBlocked(code)


def _safe_absolute_path(raw: str, *, expected_uid: int | None = None) -> Path:
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts or "\x00" in raw:
        raise _blocked("UNSAFE_PATH")
    flags_dir = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path.anchor, flags_dir)
    try:
        for component in path.parts[1:-1]:
            next_fd = os.open(component, flags_dir, dir_fd=fd)
            child = os.fstat(next_fd)
            safe_sticky_tmp = child.st_uid == 0 and bool(child.st_mode & stat.S_ISVTX)
            if not stat.S_ISDIR(child.st_mode) or (child.st_mode & 0o022 and not safe_sticky_tmp):
                os.close(next_fd)
                raise _blocked("UNSAFE_PATH")
            os.close(fd)
            fd = next_fd
        file_fd = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=fd,
        )
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise _blocked("UNSAFE_FILE")
            if expected_uid is not None and info.st_uid != expected_uid:
                raise _blocked("UNSAFE_FILE_OWNER")
            return path
        finally:
            os.close(file_fd)
    except FileNotFoundError as exc:
        raise _blocked("MISSING_PATH") from exc
    except OSError as exc:
        raise _blocked("UNSAFE_PATH") from exc
    finally:
        os.close(fd)


def _safe_dir(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts or "\x00" in raw:
        raise _blocked("UNSAFE_PATH")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=fd)
            info = os.fstat(next_fd)
            safe_sticky_tmp = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            if not stat.S_ISDIR(info.st_mode) or (info.st_mode & 0o022 and not safe_sticky_tmp):
                os.close(next_fd)
                raise _blocked("UNSAFE_DIRECTORY")
            os.close(fd)
            fd = next_fd
        return path
    except FileNotFoundError as exc:
        raise _blocked("MISSING_PATH") from exc
    except OSError as exc:
        raise _blocked("UNSAFE_PATH") from exc
    finally:
        os.close(fd)


def read_protected_env(path: str) -> dict[str, str]:
    """Read a bounded owner-private dotenv subset without symlink traversal."""
    absolute = Path(path)
    if not absolute.is_absolute() or ".." in absolute.parts:
        raise _blocked("ENV_PATH")
    fd = -1
    parent_fd = -1
    try:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        parent_fd = os.open(absolute.anchor, directory_flags)
        for component in absolute.parts[1:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=parent_fd)
            info = os.fstat(next_fd)
            safe_sticky_tmp = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            if not stat.S_ISDIR(info.st_mode) or (info.st_mode & 0o022 and not safe_sticky_tmp):
                os.close(next_fd)
                raise _blocked("ENV_PATH")
            os.close(parent_fd)
            parent_fd = next_fd
        fd = os.open(
            absolute.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or not 0 < before.st_size <= _MAX_ENV_BYTES
        ):
            raise _blocked("ENV_FILE")
        content = bytearray()
        while len(content) <= _MAX_ENV_BYTES:
            chunk = os.read(fd, min(8192, _MAX_ENV_BYTES + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(fd)
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if len(content) > _MAX_ENV_BYTES or before_identity != after_identity:
            raise _blocked("ENV_FILE")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _blocked("ENV_SYNTAX") from exc
        values: dict[str, str] = {}
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or not _SAFE_KEY.fullmatch(key) or not value or value != value.strip():
                raise _blocked("ENV_SYNTAX")
            if "$" in value or re.search(r"\s#", value):
                raise _blocked("ENV_VALUE")
            if key in values:
                raise _blocked("ENV_DUPLICATE")
            values[key] = value
        return values
    except FileNotFoundError as exc:
        raise _blocked("ENV_FILE") from exc
    except OSError as exc:
        raise _blocked("ENV_FILE") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if parent_fd >= 0:
            os.close(parent_fd)


def compose_service_names(compose_text: str) -> set[str]:
    names: set[str] = set()
    in_services = False
    for line in compose_text.splitlines():
        if line == "services:":
            in_services = True
            continue
        if in_services and line and not line.startswith(" ") and not line.startswith("\t"):
            break
        if in_services and line.startswith("  ") and not line.startswith("    "):
            name = line.strip().removesuffix(":")
            if re.fullmatch(r"[a-z][a-z0-9-]*", name):
                names.add(name)
    return names


def _origin(value: str, *, tailnet: bool, allow_path: bool = False) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise _blocked("ORIGIN") from exc
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or (not allow_path and parsed.path not in {"", "/"})
        or (
            allow_path
            and parsed.path
            and (not parsed.path.startswith("/") or parsed.path.startswith("//"))
        )
        or parsed.query
        or parsed.fragment
        or (tailnet and not host.endswith(".ts.net"))
        or host in {"localhost", "identity", "core", "minio"}
        or host.endswith((".local", ".localhost", ".test", ".internal"))
    ):
        raise _blocked("ORIGIN")
    try:
        parsed_ip = ipaddress.ip_address(host)
    except ValueError:
        parsed_ip = None
    if parsed_ip is not None and any(
        (
            parsed_ip.is_private,
            parsed_ip.is_loopback,
            parsed_ip.is_link_local,
            parsed_ip.is_unspecified,
        )
    ):
        raise _blocked("ORIGIN")
    if port is not None and not 1 <= port <= 65535:
        raise _blocked("ORIGIN")
    return host


def _read_protected_bytes(path: Path, *, expected_uid: int | None) -> bytes:
    raw_path = str(path)
    if not path.is_absolute() or ".." in path.parts or "\x00" in raw_path:
        raise _blocked("UNSAFE_PATH")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory_fd = -1
    file_fd = -1
    try:
        directory_fd = os.open(path.anchor, directory_flags)
        for component in path.parts[1:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            directory = os.fstat(next_fd)
            safe_sticky_tmp = directory.st_uid == 0 and bool(directory.st_mode & stat.S_ISVTX)
            if not stat.S_ISDIR(directory.st_mode) or (
                directory.st_mode & 0o022 and not safe_sticky_tmp
            ):
                os.close(next_fd)
                raise _blocked("UNSAFE_PATH")
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or (expected_uid is not None and before.st_uid != expected_uid)
        ):
            raise _blocked("UNSAFE_FILE")
        if stat.S_IMODE(before.st_mode) != 0o600:
            raise _blocked("UNSAFE_FILE_MODE")
        if not 0 < before.st_size <= _MAX_ENV_BYTES:
            raise _blocked("PROTECTED_FILE_SIZE")
        content = bytearray()
        while len(content) <= _MAX_ENV_BYTES:
            chunk = os.read(file_fd, min(8192, _MAX_ENV_BYTES + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(file_fd)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_uid,
            before.st_gid,
            stat.S_IMODE(before.st_mode),
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_uid,
            after.st_gid,
            stat.S_IMODE(after.st_mode),
        )
        if len(content) != before.st_size or before_identity != after_identity:
            raise _blocked("PROTECTED_FILE_CONTENT")
        return bytes(content)
    except FileNotFoundError as exc:
        raise _blocked("MISSING_PATH") from exc
    except OSError as exc:
        raise _blocked("UNSAFE_PATH") from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _protected_json(path: Path, *, expected_uid: int | None) -> object:
    content = _read_protected_bytes(path, expected_uid=expected_uid)
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise _blocked("PROTECTED_FILE_CONTENT") from exc


def _check_protected_material(env: dict[str, str], *, expected_uid: int) -> None:
    state_dir = _safe_dir(env["KSI_ANALYSIS_PILOT_STATE_DIR"])
    state_info = state_dir.stat(follow_symlinks=False)
    if state_info.st_uid != expected_uid or stat.S_IMODE(state_info.st_mode) & 0o077:
        raise _blocked("CORE_STATE_DIRECTORY")
    authority = _safe_dir(env["KSI_ANALYSIS_PILOT_AUTHORITY_DIR"])
    secret_dir = _safe_dir(env["KSI_ANALYSIS_PILOT_SECRET_DIR"])
    for relative in _AUTHORITY_FILES:
        _protected_json(authority / relative, expected_uid=expected_uid)
    signing_dir = _safe_dir(str(authority / "signing-keys"))
    key_manifest = _protected_json(signing_dir / "keys.json", expected_uid=expected_uid)
    if (
        not isinstance(key_manifest, dict)
        or not isinstance(key_manifest.get("active"), str)
        or not isinstance(key_manifest.get("keys"), list)
        or not key_manifest["keys"]
    ):
        raise _blocked("SIGNING_KEY_MANIFEST")
    for entry in key_manifest["keys"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("keyId"), str):
            raise _blocked("SIGNING_KEY_MANIFEST")
        key_id = entry["keyId"]
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", key_id)
            or len(key_id.encode("ascii")) + len(".private.pem") > 255
        ):
            raise _blocked("SIGNING_KEY_MANIFEST")
        for suffix in ("public.pem", "private.pem"):
            key_path = signing_dir / f"{key_id}.{suffix}"
            _safe_absolute_path(str(key_path), expected_uid=expected_uid)
            if stat.S_IMODE(key_path.stat(follow_symlinks=False).st_mode) != 0o600:
                raise _blocked("SIGNING_KEY_FILE")
    registry = _protected_json(authority / "oidc-subject-registry.json", expected_uid=expected_uid)
    if not isinstance(registry, dict):
        raise _blocked("OIDC_REGISTRY")
    version = registry.get("version")
    mappings = registry.get("subjects")
    if not isinstance(mappings, list) or not mappings:
        raise _blocked("OIDC_REGISTRY")
    # F-01: v2 는 capabilities 필수 + scope 필수(null = 조직 전체). 이 preflight 는
    # 배포 전 빠른 형식 게이트이고, semantics 는 Core 로더(load_oidc_subject_registry)
    # 가 부팅 시 동일하게 다시 강제한다.
    if version == "oidc-subject-registry.v1":
        subject_fields = frozenset(
            {
                "issuer",
                "subject",
                "principalId",
                "organizationId",
                "role",
                "status",
                "allowedSiteIds",
                "allowedWorkAreaIds",
            }
        )
    elif version == "oidc-subject-registry.v2":
        subject_fields = frozenset(
            {
                "issuer",
                "subject",
                "principalId",
                "organizationId",
                "role",
                "status",
                "allowedSiteIds",
                "allowedWorkAreaIds",
                "capabilities",
            }
        )
    else:
        raise _blocked("OIDC_REGISTRY")
    issuer = env["KSI_ANALYSIS_PILOT_OIDC_ISSUER"]
    for row in mappings:
        if not isinstance(row, dict) or frozenset(row) != subject_fields:
            raise _blocked("OIDC_REGISTRY")
        if row.get("issuer") != issuer:
            raise _blocked("OIDC_REGISTRY_ISSUER")
        if version == "oidc-subject-registry.v2":
            if not isinstance(row.get("capabilities"), list):
                raise _blocked("OIDC_REGISTRY")
            for field in ("allowedSiteIds", "allowedWorkAreaIds"):
                value = row.get(field)
                if value is not None and not isinstance(value, list):
                    raise _blocked("OIDC_REGISTRY")
    for name in ("dashboard-session.secret", "oidc-client.secret"):
        secret_path = secret_dir / name
        secret = _read_protected_bytes(secret_path, expected_uid=expected_uid)
        try:
            dashboard_value = secret.decode("utf-8").strip(_ECMASCRIPT_TRIM_CHARS)
        except UnicodeDecodeError as exc:
            raise _blocked("DASHBOARD_SECRET") from exc
        dashboard_length = len(dashboard_value.encode("utf-16-le")) // 2
        if dashboard_length < 32 or len(secret) > 4096:
            raise _blocked("DASHBOARD_SECRET")


def _check_worker_principals(raw: str) -> None:
    try:
        rows = json.loads(raw)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise _blocked("PRINCIPALS") from exc
    if not isinstance(rows, list) or not rows:
        raise _blocked("PRINCIPALS")
    permitted_kinds = {"ANALYSIS_WORKER", "ANALYSIS_MCP_CLIENT"}
    if any(not isinstance(row, dict) or row.get("kind") not in permitted_kinds for row in rows):
        raise _blocked("PRINCIPAL_KIND")
    workers = [
        row for row in rows if isinstance(row, dict) and row.get("kind") == "ANALYSIS_WORKER"
    ]
    if len(workers) != 1 or workers[0].get("status", "ACTIVE") != "ACTIVE":
        raise _blocked("ANALYSIS_WORKER_PRINCIPAL")
    mcp_clients = [row for row in rows if row.get("kind") == "ANALYSIS_MCP_CLIENT"]
    if len(mcp_clients) > 1:
        raise _blocked("PRINCIPALS")
    for row in rows:
        token_digest = row.get("tokenSha256")
        if not isinstance(token_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", token_digest):
            raise _blocked("PRINCIPALS")
        if not isinstance(row.get("principalId"), str) or not row["principalId"].strip():
            raise _blocked("PRINCIPALS")
        if row.get("kind") == "ANALYSIS_MCP_CLIENT":
            for field in ("allowedSiteIds", "allowedWorkAreaIds"):
                grants = row.get(field)
                if (
                    not isinstance(grants, list)
                    or not grants
                    or any(
                        not isinstance(grant, str)
                        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", grant)
                        for grant in grants
                    )
                    or len(grants) != len(set(grants))
                ):
                    raise _blocked("MCP_CLIENT_SCOPE")


def validate_candidate(env: dict[str, str], *, compose_text: str, expected_uid: int) -> None:
    """Validate host-provided inputs and the Compose security envelope."""
    if set(env) != _REQUIRED:
        raise _blocked("ENV_KEYS")
    for name in ("KSI_ANALYSIS_PILOT_CORE_IMAGE_ID", "KSI_ANALYSIS_PILOT_DASHBOARD_IMAGE_ID"):
        if not _DIGEST_IMAGE.fullmatch(env[name]):
            raise _blocked("IMAGE_DIGEST")
    tailnet_name = env["KSI_ANALYSIS_PILOT_TAILNET_HOSTNAME"].lower()
    tailnet_pattern = r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+ts\.net"
    if not re.fullmatch(tailnet_pattern, tailnet_name):
        raise _blocked("TAILNET_HOSTNAME")
    for name in (
        "KSI_ANALYSIS_PILOT_APP_ORIGIN",
        "KSI_ANALYSIS_PILOT_API_ORIGIN",
        "KSI_ANALYSIS_PILOT_OBJECTS_ORIGIN",
    ):
        _origin(env[name], tailnet=True)
    if urlsplit(env["KSI_ANALYSIS_PILOT_APP_ORIGIN"]).hostname != tailnet_name:
        raise _blocked("TAILNET_ORIGIN_MISMATCH")
    oidc_issuer_host = _origin(
        env["KSI_ANALYSIS_PILOT_OIDC_ISSUER"], tailnet=False, allow_path=True
    )
    jwks_host = _origin(env["KSI_ANALYSIS_PILOT_OIDC_JWKS_URL"], tailnet=False, allow_path=True)
    for host in (oidc_issuer_host, jwks_host):
        if host in {"localhost", "identity", "core", "minio"} or host.endswith(
            (".local", ".localhost", ".test", ".internal")
        ):
            raise _blocked("OIDC_ISSUER")
    if (
        not env["KSI_ANALYSIS_PILOT_OIDC_AUDIENCE"].strip()
        or not env["KSI_ANALYSIS_PILOT_OIDC_CLIENT_ID"].strip()
    ):
        raise _blocked("OIDC_REQUIRED")
    ports = []
    for name in (
        "KSI_ANALYSIS_PILOT_APP_PORT",
        "KSI_ANALYSIS_PILOT_API_PORT",
        "KSI_ANALYSIS_PILOT_OBJECTS_PORT",
    ):
        raw = env[name]
        if not _PORT.fullmatch(raw) or not 1024 <= int(raw) <= 65535:
            raise _blocked("PORT")
        ports.append(raw)
    if len(set(ports)) != len(ports):
        raise _blocked("PORT_COLLISION")
    object_credentials = (
        env["KSI_ANALYSIS_PILOT_MINIO_ROOT_USER"],
        env["KSI_ANALYSIS_PILOT_MINIO_ROOT_PASSWORD"],
        env["KSI_ANALYSIS_PILOT_MINIO_CORE_ACCESS_KEY"],
        env["KSI_ANALYSIS_PILOT_MINIO_CORE_SECRET_KEY"],
    )
    if (
        any(not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", value) for value in object_credentials)
        or object_credentials[0] == object_credentials[2]
        or object_credentials[1] == object_credentials[3]
    ):
        raise _blocked("OBJECT_STORE_CREDENTIAL")
    _check_worker_principals(env["KSI_ANALYSIS_PILOT_CORE_PRINCIPAL_TOKENS_JSON"])
    _check_protected_material(env, expected_uid=expected_uid)

    services = compose_service_names(compose_text)
    if services != _SERVICE_NAMES or services & _FORBIDDEN_SERVICE_NAMES:
        raise _blocked("COMPOSE_SERVICE_SET")
    lowered = compose_text.lower()
    if "build:" in lowered or "identity:" in lowered or "nodeodm" in lowered:
        raise _blocked("COMPOSE_UNSAFE_SERVICE")
    if re.search(
        r"(?m)^\s*(?:network_mode:\s*host|privileged:\s*true|pid:\s*host|ipc:\s*host)\s*$",
        lowered,
    ):
        raise _blocked("COMPOSE_HOST_ACCESS")
    published_lines: list[str] = []
    in_ports = False
    ports_indent = -1
    for line in compose_text.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped == "ports:":
            in_ports = True
            ports_indent = indent
            continue
        if in_ports and stripped and indent <= ports_indent:
            in_ports = False
        if in_ports and stripped.startswith("-"):
            published_lines.append(stripped[1:].strip().strip("\"'"))
    if not published_lines or any(not line.startswith("127.0.0.1:") for line in published_lines):
        raise _blocked("COMPOSE_PUBLIC_BIND")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, help="protected, absolute key=value input")
    args = parser.parse_args(argv)
    try:
        env = read_protected_env(args.env_file)
        compose_path = Path(__file__).with_name("compose.yaml")
        compose = compose_path.read_text(encoding="utf-8")
        validate_candidate(env, compose_text=compose, expected_uid=_SERVICE_UID)
    except (PreflightBlocked, OSError, UnicodeDecodeError):
        print("BLOCKED: Analysis pilot preflight requirements are not satisfied.", file=sys.stderr)
        return 2
    print("PASS: Analysis pilot inputs and local Compose boundary validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
