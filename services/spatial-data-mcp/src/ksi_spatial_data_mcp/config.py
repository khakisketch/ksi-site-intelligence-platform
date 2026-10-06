"""Owner-protected explicit configuration for the spatial-data MCP adapter.

One exact Core origin plus one separate absolute token file. No bearer
material in environment, command arguments, config values, or tool inputs.
All limits are required, strict, positive, and finite owner-supplied values;
the fixed representation ceilings below are parsing guards, not runtime
quotas or production defaults.
"""

from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

# Fixed parsing representation ceilings (not runtime quotas): the config byte
# limit itself is unknown until the file is parsed, so the first read is
# bounded by this constant before the owner-supplied maxConfigBytes is known.
_CONFIG_PARSE_CEILING_BYTES = 65536

# Fixed token representation ceiling (4096B plus one CRLF line ending),
# independent of the owner-supplied maxTokenBytes quota: no caller may widen
# how many bytes the adapter will ever pull from a credential file.
_TOKEN_PARSE_CEILING_BYTES = 4096 + 2

_CONFIG_FIELDS = (
    "coreOrigin",
    "tokenFile",
    "maxRequestBytes",
    "maxStructuredResponseBytes",
    "maxConcurrentCalls",
    "maxIdentifierBytes",
    "maxCursorBytes",
    "maxTokenBytes",
    "maxConfigBytes",
    "connectTimeoutSeconds",
    "readTimeoutSeconds",
    "poolTimeoutSeconds",
    "callDeadlineSeconds",
)
_BYTE_LIMIT_FIELDS = (
    "maxRequestBytes",
    "maxStructuredResponseBytes",
    "maxConcurrentCalls",
    "maxIdentifierBytes",
    "maxCursorBytes",
    "maxTokenBytes",
    "maxConfigBytes",
)
_TIMEOUT_FIELDS = (
    "connectTimeoutSeconds",
    "readTimeoutSeconds",
    "poolTimeoutSeconds",
    "callDeadlineSeconds",
)


class AdapterConfigurationError(ValueError):
    """Raised before the adapter can use a protected file or the network."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _walk_finite(value: object, depth: int = 0) -> None:
    if depth > 100:
        raise ValueError("JSON exceeds finite nesting depth")
    if isinstance(value, dict):
        for item in value.values():
            _walk_finite(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _walk_finite(item, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number")


def _strict_json_loads(raw: bytes) -> object:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdapterConfigurationError("protected file is not UTF-8 JSON") from exc
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError) as exc:
        raise AdapterConfigurationError("protected file is not strict JSON") from exc
    try:
        _walk_finite(parsed)
    except (ValueError, RecursionError) as exc:
        raise AdapterConfigurationError("protected file is not finite JSON") from exc
    return parsed


_DIR_FD_FLAGS = (
    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NONBLOCK", 0)
)


def _check_directory_metadata(metadata: os.stat_result, *, what: str) -> None:
    """One ancestry directory: real dir, caller- or root-owned, no group/other write."""
    owner = os.geteuid()
    if not stat.S_ISDIR(metadata.st_mode):
        raise AdapterConfigurationError(f"protected {what} must be a real directory")
    if metadata.st_uid not in (owner, 0):
        raise AdapterConfigurationError(f"protected {what} has an untrusted owner")
    if metadata.st_mode & 0o022:
        raise AdapterConfigurationError(f"protected {what} is group- or world-writable")


def _check_file_metadata(metadata: os.stat_result) -> None:
    """One credential file: exact-owner 0600-or-stricter regular file, no hardlinks."""
    if not stat.S_ISREG(metadata.st_mode):
        raise AdapterConfigurationError("protected file must be a regular non-symlink file")
    if metadata.st_uid != os.geteuid():
        raise AdapterConfigurationError("protected file must be owned by the caller")
    if metadata.st_mode & 0o077:
        raise AdapterConfigurationError("protected file must be owner-protected (0600 or stricter)")
    if metadata.st_nlink != 1:
        raise AdapterConfigurationError("protected file must not be hard-linked")


def _same_identity(first: os.stat_result, second: os.stat_result) -> bool:
    """Full observed continuity: identity, protection, links, and times."""
    return (
        first.st_dev,
        first.st_ino,
        first.st_mode,
        first.st_uid,
        first.st_nlink,
        first.st_size,
        first.st_mtime_ns,
        first.st_ctime_ns,
    ) == (
        second.st_dev,
        second.st_ino,
        second.st_mode,
        second.st_uid,
        second.st_nlink,
        second.st_size,
        second.st_mtime_ns,
        second.st_ctime_ns,
    )


def _read_protected_bytes(path: Path, *, ceiling_bytes: int) -> bytes:
    """Read bounded bytes through a descriptor-relative no-follow walk.

    Every ancestor directory is opened (never followed) and verified before
    descending; the file is opened relative to its verified parent directory,
    and pre-open, at-open, post-read, and by-path stats must agree. A swap at
    any point fails closed. Local-filesystem races cannot be eliminated
    entirely — this is best-effort continuity, not atomicity — but any
    observed change is a refusal, never a read.
    """
    if not path.is_absolute():
        raise AdapterConfigurationError("protected file path must be absolute")
    text = os.fspath(path)
    if any(ord(character) < 0x20 for character in text):
        raise AdapterConfigurationError("protected file path carries control characters")
    parts = path.parts
    if len(parts) < 2 or any(component in ("", ".", "..") for component in parts[1:]):
        raise AdapterConfigurationError("protected file path must name one real file")
    try:
        parent = os.open("/", _DIR_FD_FLAGS)
    except (OSError, ValueError) as exc:
        raise AdapterConfigurationError("protected ancestry is unavailable") from exc
    descriptor: int | None = None
    try:
        try:
            _check_directory_metadata(os.fstat(parent), what="ancestry")
            for component in parts[1:-1]:
                child = os.open(component, _DIR_FD_FLAGS, dir_fd=parent)
                os.close(parent)
                parent = child
                _check_directory_metadata(os.fstat(parent), what="ancestry")
            try:
                before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            except (OSError, ValueError) as exc:
                raise AdapterConfigurationError("protected file is unavailable") from exc
            try:
                descriptor = os.open(parts[-1], _FILE_FLAGS, dir_fd=parent)
            except (OSError, ValueError) as exc:
                raise AdapterConfigurationError("protected file is unavailable") from exc
            opened = os.fstat(descriptor)
            _check_file_metadata(opened)
            if not _same_identity(opened, before):
                raise AdapterConfigurationError("protected file changed while opening")
            if opened.st_size > ceiling_bytes:
                raise AdapterConfigurationError("protected file exceeds its representation ceiling")
            raw = os.read(descriptor, ceiling_bytes + 1)
            if len(raw) > ceiling_bytes:
                raise AdapterConfigurationError("protected file exceeds its representation ceiling")
            after = os.fstat(descriptor)
            try:
                current = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            except (OSError, ValueError) as exc:
                raise AdapterConfigurationError("protected file changed during read") from exc
            if not _same_identity(after, before) or not _same_identity(current, before):
                raise AdapterConfigurationError("protected file changed during read")
            return raw
        except OSError as exc:
            raise AdapterConfigurationError("protected file is unreadable") from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        with suppress(OSError):
            os.close(parent)


_BEARER_SCHEME_RE = re.compile(r"bearer(?:\s|\Z)", re.IGNORECASE)


def _check_no_bearer(value: object) -> None:
    # Same scheme-only rule as tool arguments: only the credential-scheme
    # form is refused, never a safe path that merely contains the word.
    if isinstance(value, str):
        if _BEARER_SCHEME_RE.match(value) is not None:
            raise AdapterConfigurationError("bearer material is never a config value")
        if any(ord(character) < 0x20 for character in value):
            raise AdapterConfigurationError("config value carries control characters")
    elif isinstance(value, dict):
        for item in value.values():
            _check_no_bearer(item)
    elif isinstance(value, list):
        for item in value:
            _check_no_bearer(item)


_DNS_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_DNS_NAME_RE = re.compile(rf"(?:{_DNS_LABEL}\.)*{_DNS_LABEL}\Z")


def _normalize_dns_host(host: str) -> str:
    """Validate an exact DNS HTTPS host without resolving or contacting it."""
    name = host[:-1] if host.endswith(".") else host
    if not name or len(name) > 253 or "%" in name:
        raise AdapterConfigurationError("core origin host must be an exact DNS name")
    if _DNS_NAME_RE.fullmatch(name) is None:
        raise AdapterConfigurationError("core origin host must be an exact DNS name")
    return name.lower()


def _normalize_origin(origin: object) -> str:
    if type(origin) is not str or not origin:
        raise AdapterConfigurationError("core origin must be one exact origin string")
    if any(ord(character) <= 32 or ord(character) == 127 for character in origin):
        raise AdapterConfigurationError("core origin carries control characters")
    try:
        parsed = urlsplit(origin)
        port: int | None = parsed.port
    except ValueError as exc:
        raise AdapterConfigurationError("core origin has an invalid authority") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise AdapterConfigurationError("core origin must be one exact origin")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None:
        if "%" in parsed.hostname or getattr(address, "scope_id", None) is not None:
            raise AdapterConfigurationError("core origin host must be an unscoped literal IP")
        if parsed.scheme == "http" and not address.is_loopback:
            raise AdapterConfigurationError("non-loopback Core origin requires HTTPS")
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
    else:
        # Approved exact DNS origins are HTTPS only; plain HTTP stays
        # literal-loopback. The name is validated purely by parsing —
        # never resolved or contacted here.
        if parsed.scheme != "https":
            raise AdapterConfigurationError("non-loopback Core origin requires HTTPS")
        host = _normalize_dns_host(parsed.hostname)
    normalized = f"{parsed.scheme}://{host}"
    if port is not None:
        normalized += f":{port}"
    return normalized


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    """One exact Core origin, one private token file, and finite owner limits."""

    core_origin: str
    token_file: Path
    max_request_bytes: int
    max_structured_response_bytes: int
    max_concurrent_calls: int
    max_identifier_bytes: int
    max_cursor_bytes: int
    max_token_bytes: int
    max_config_bytes: int
    connect_timeout_seconds: float
    read_timeout_seconds: float
    pool_timeout_seconds: float
    call_deadline_seconds: float

    @classmethod
    def from_file(cls, path: Path | str) -> AdapterConfig:
        candidate = Path(path)
        raw = _read_protected_bytes(candidate, ceiling_bytes=_CONFIG_PARSE_CEILING_BYTES)
        parsed = _strict_json_loads(raw)
        if type(parsed) is not dict:
            raise AdapterConfigurationError("config must be one JSON object")
        keys = set(parsed)
        if keys != set(_CONFIG_FIELDS):
            raise AdapterConfigurationError("config fields must be exactly the closed set")
        _check_no_bearer(parsed)
        limits: dict[str, int | float] = {}
        for field in _BYTE_LIMIT_FIELDS:
            value = parsed[field]
            if type(value) is bool or type(value) is not int or value < 1:
                raise AdapterConfigurationError(f"config {field} must be a positive integer")
            limits[field] = value
        for field in _TIMEOUT_FIELDS:
            value = parsed[field]
            if (
                type(value) is bool
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise AdapterConfigurationError(f"config {field} must be positive finite seconds")
            limits[field] = float(value)
        if len(raw) > int(limits["maxConfigBytes"]):
            raise AdapterConfigurationError("config exceeds its owner byte limit")
        token_path = parsed["tokenFile"]
        if type(token_path) is not str or not token_path:
            raise AdapterConfigurationError("token file path must be absolute")
        config = cls(
            core_origin=_normalize_origin(parsed["coreOrigin"]),
            token_file=Path(token_path),
            max_request_bytes=int(limits["maxRequestBytes"]),
            max_structured_response_bytes=int(limits["maxStructuredResponseBytes"]),
            max_concurrent_calls=int(limits["maxConcurrentCalls"]),
            max_identifier_bytes=int(limits["maxIdentifierBytes"]),
            max_cursor_bytes=int(limits["maxCursorBytes"]),
            max_token_bytes=int(limits["maxTokenBytes"]),
            max_config_bytes=int(limits["maxConfigBytes"]),
            connect_timeout_seconds=float(limits["connectTimeoutSeconds"]),
            read_timeout_seconds=float(limits["readTimeoutSeconds"]),
            pool_timeout_seconds=float(limits["poolTimeoutSeconds"]),
            call_deadline_seconds=float(limits["callDeadlineSeconds"]),
        )
        config._check_token_file()
        return config

    def _check_token_file(self) -> None:
        _read_protected_bytes(self.token_file, ceiling_bytes=_TOKEN_PARSE_CEILING_BYTES)

    def read_token(self) -> str:
        """Re-read the separate token file before each HTTP call."""
        try:
            raw = _read_protected_bytes(self.token_file, ceiling_bytes=_TOKEN_PARSE_CEILING_BYTES)
            token = raw.decode("ascii")
        except (AdapterConfigurationError, UnicodeError) as exc:
            raise AdapterConfigurationError("token file is unreadable") from exc
        if token.endswith("\r\n"):
            token = token[:-2]
        elif token.endswith("\n"):
            token = token[:-1]
        if not token or len(token) > self.max_token_bytes:
            raise AdapterConfigurationError("token file has an invalid opaque credential")
        if any(ord(character) < 0x21 or ord(character) > 0x7E for character in token):
            # Printable ASCII only: no whitespace, NUL/DEL, controls, or
            # header-injecting bytes. An opaque word prefix (e.g. bearerX)
            # is legitimate credential material and stays accepted.
            raise AdapterConfigurationError("token file has an invalid opaque credential")
        return token

    def http_client_kwargs(self) -> dict[str, object]:
        """Use no ambient proxy, no redirects, and verified TLS."""
        return {
            "base_url": self.core_origin,
            "timeout": httpx.Timeout(
                connect=self.connect_timeout_seconds,
                read=self.read_timeout_seconds,
                write=self.read_timeout_seconds,
                pool=self.pool_timeout_seconds,
            ),
            "follow_redirects": False,
            "trust_env": False,
            "verify": True,
        }

    def new_http_client(self) -> httpx.AsyncClient:
        """Construct the closed client without widening its typed keyword surface."""
        return httpx.AsyncClient(
            base_url=self.core_origin,
            timeout=httpx.Timeout(
                connect=self.connect_timeout_seconds,
                read=self.read_timeout_seconds,
                write=self.read_timeout_seconds,
                pool=self.pool_timeout_seconds,
            ),
            follow_redirects=False,
            trust_env=False,
            verify=True,
        )
