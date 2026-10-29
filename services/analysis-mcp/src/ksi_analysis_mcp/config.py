"""Closed local configuration for the Analysis MCP stdio adapter."""

from __future__ import annotations

import ipaddress
import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

MAX_STRUCTURED_RESPONSE_BYTES = 512 * 1024
_MAX_TOKEN_BYTES = 4096
_MAX_TOKEN_FILE_BYTES = _MAX_TOKEN_BYTES + 2  # token plus one CRLF line ending


class AdapterConfigurationError(ValueError):
    """Raised before the adapter can make a network request."""


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    """One exact Core origin and one private local bearer-token file."""

    core_origin: str
    token_file: Path
    timeout_seconds: float = 10.0
    max_response_bytes: int = MAX_STRUCTURED_RESPONSE_BYTES
    console_origin: str | None = None

    @classmethod
    def from_values(
        cls, *, core_origin: str, token_file: str, console_origin: str | None = None
    ) -> AdapterConfig:
        if type(core_origin) is not str or not core_origin or len(core_origin) > 16_384:
            raise AdapterConfigurationError(
                "core origin must be one exact scheme://literal-ip[:port]"
            )
        parsed = urlsplit(core_origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or any(ord(character) <= 32 for character in core_origin)
        ):
            raise AdapterConfigurationError(
                "core origin must be one exact scheme://literal-ip[:port]"
            )
        try:
            _ = parsed.port
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError as exc:
            raise AdapterConfigurationError(
                "core origin host must be an unscoped literal IP"
            ) from exc
        if "%" in parsed.hostname or getattr(address, "scope_id", None) is not None:
            raise AdapterConfigurationError("core origin host must be an unscoped literal IP")
        if parsed.scheme == "http" and not address.is_loopback:
            raise AdapterConfigurationError("non-loopback Core origin requires HTTPS")
        path = Path(token_file)
        if not path.is_absolute():
            raise AdapterConfigurationError("token file path must be absolute")
        if console_origin is not None:
            if type(console_origin) is not str or not console_origin or len(console_origin) > 2048:
                raise AdapterConfigurationError("Console origin must be one bounded origin")
            # Presentation link only, never an outbound request or redirect target
            # supplied by a model. Keep Core and Console origins explicitly separate.
            try:
                console = urlsplit(console_origin)
                port = console.port
                del port
                loopback = console.hostname == "localhost"
                with suppress(ValueError):
                    loopback = ipaddress.ip_address(console.hostname or "").is_loopback
                if (
                    console.scheme not in {"http", "https"}
                    or not console.hostname
                    or console.username is not None
                    or console.password is not None
                    or console.path not in {"", "/"}
                    or console.query
                    or console.fragment
                    or any(ord(c) <= 32 or ord(c) >= 127 for c in console_origin)
                    or "\\" in console_origin
                    or (console.scheme == "http" and not loopback)
                ):
                    raise ValueError("invalid Console origin")
            except ValueError as exc:
                raise AdapterConfigurationError(
                    "Console origin requires HTTPS or loopback HTTP"
                ) from exc
        config = cls(
            core_origin=core_origin.rstrip("/"),
            token_file=path,
            console_origin=console_origin.rstrip("/") if console_origin else None,
        )
        config._check_token_file()
        return config

    @classmethod
    def from_environ(cls) -> AdapterConfig:
        try:
            origin = os.environ["KSI_ANALYSIS_MCP_CORE_ORIGIN"]
            token_file = os.environ["KSI_ANALYSIS_MCP_TOKEN_FILE"]
        except KeyError as exc:
            raise AdapterConfigurationError(
                "Core origin and token file environment are required"
            ) from exc
        return cls.from_values(
            core_origin=origin,
            token_file=token_file,
            console_origin=os.environ.get("KSI_ANALYSIS_MCP_CONSOLE_ORIGIN"),
        )

    def _check_token_file(self) -> None:
        try:
            metadata = self.token_file.lstat()
        except OSError as exc:
            raise AdapterConfigurationError("token file is unavailable") from exc
        self._validate_token_metadata(metadata)

    @staticmethod
    def _validate_token_metadata(metadata: os.stat_result) -> None:
        if not stat.S_ISREG(metadata.st_mode):
            raise AdapterConfigurationError("token file must be a regular non-symlink file")
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise AdapterConfigurationError("token file must be owner-protected (0600 or stricter)")

    def read_token(self) -> str:
        """Read a bounded opaque token without exposing it in configuration errors."""
        try:
            before = self.token_file.lstat()
            self._validate_token_metadata(before)
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self.token_file, flags)
            try:
                opened = os.fstat(descriptor)
                self._validate_token_metadata(opened)
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise AdapterConfigurationError("token file changed while opening")
                if opened.st_size > _MAX_TOKEN_FILE_BYTES:
                    raise AdapterConfigurationError("token file has an invalid opaque credential")
                raw = os.read(descriptor, _MAX_TOKEN_FILE_BYTES + 1)
                if len(raw) > _MAX_TOKEN_FILE_BYTES:
                    raise AdapterConfigurationError("token file has an invalid opaque credential")
            finally:
                os.close(descriptor)
            token = raw.decode("ascii")
        except (OSError, UnicodeError) as exc:
            raise AdapterConfigurationError("token file is unreadable") from exc
        if token.endswith("\r\n"):
            token = token[:-2]
        elif token.endswith("\n"):
            token = token[:-1]
        if not token or len(token) > _MAX_TOKEN_BYTES or any(char.isspace() for char in token):
            raise AdapterConfigurationError("token file has an invalid opaque credential")
        return token

    def http_client_kwargs(self) -> dict[str, object]:
        """Use no ambient proxy and no redirect path outside the configured origin."""
        return {
            "base_url": self.core_origin,
            "timeout": httpx.Timeout(self.timeout_seconds),
            "follow_redirects": False,
            "trust_env": False,
        }

    def new_http_client(self) -> httpx.AsyncClient:
        """Construct the closed client without widening its typed keyword surface."""
        return httpx.AsyncClient(
            base_url=self.core_origin,
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )
