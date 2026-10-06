"""Lightweight loopback fixture for the spatial-data MCP adapter tests.

Only Task5 will add the real Core TIFF/worker path. This module provides a
plain loopback HTTP Core double, private generated configs/tokens under an
owned clean-ancestry scratch (never ``/tmp`` parents, which the adapter's
secure-file policy rejects as world-writable, and never the plan tree,
whose repository ancestors are group-writable and therefore rejected too),
and an explicit new-source path prepend for subprocesses. It touches no
real credentials, customer data, or network.
"""

from __future__ import annotations

import atexit as _atexit
import json
import os
import stat
import sys
import tempfile
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SRC = REPO_ROOT / "services" / "spatial-data-mcp" / "src"
# Owned generated-test namespace only: one unique 0700 directory per test
# process, created directly under the already-secure caller cache. Existing
# fixed namespaces (including earlier task runs) are never chmodded,
# scanned, or deleted; only this unique directory is test-owned and only it
# may be cleaned up.
_FIXTURE_NAMESPACE_PREFIX = "ksi-spatial-data-mcp-task4-"
_PRIVATE_ROOT: Path | None = None

# Required, strict, finite tests-only limits (not production quotas).
FIXTURE_LIMITS: dict[str, Any] = {
    "maxRequestBytes": 8192,
    "maxStructuredResponseBytes": 131072,
    "maxConcurrentCalls": 2,
    "maxIdentifierBytes": 255,
    "maxCursorBytes": 2048,
    "maxTokenBytes": 4096,
    "maxConfigBytes": 16384,
    "connectTimeoutSeconds": 2.0,
    "readTimeoutSeconds": 2.0,
    "poolTimeoutSeconds": 1.0,
    "callDeadlineSeconds": 5.0,
}


def ensure_source_path() -> None:
    """Prepend the explicit new-source path; never an editable install/shared sync."""
    explicit = os.fspath(PACKAGE_SRC)
    if explicit not in sys.path:
        sys.path.insert(0, explicit)


def _caller_cache() -> Path:
    """The already-secure caller cache; never created, moved, or re-permissioned."""
    cache = Path.home() / ".cache"
    metadata = os.lstat(cache)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        raise RuntimeError("caller cache is not a secure owned directory")
    return cache


def private_root() -> Path:
    """One unique test-owned namespace per process (mkdtemp is 0700)."""
    global _PRIVATE_ROOT
    if _PRIVATE_ROOT is None:
        _PRIVATE_ROOT = Path(
            tempfile.mkdtemp(prefix=_FIXTURE_NAMESPACE_PREFIX, dir=_caller_cache())
        )
    return _PRIVATE_ROOT


def _cleanup_private_root() -> None:
    """Best-effort removal of exactly the unique directory this process made."""
    import shutil

    root = _PRIVATE_ROOT
    if root is not None and root.name.startswith(_FIXTURE_NAMESPACE_PREFIX):
        shutil.rmtree(root, ignore_errors=True)


_atexit.register(_cleanup_private_root)


def private_dir() -> Path:
    path = private_root() / "private"
    path.mkdir(parents=True, exist_ok=True)
    # Harden only the directory this fixture owns; the ambient umask must
    # not leave it group-writable.
    path.chmod(0o700)
    return path


def write_private_bytes(name: str, data: bytes) -> Path:
    directory = private_dir()
    path = directory / name
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def write_token(name: str, token: str = "fixture-opaque-token") -> Path:
    return write_private_bytes(name, (token + "\n").encode("ascii"))


def write_adapter_config(
    name: str,
    *,
    origin: str,
    token_path: Path,
    overrides: dict[str, Any] | None = None,
) -> Path:
    payload: dict[str, Any] = {
        "coreOrigin": origin,
        "tokenFile": os.fspath(token_path),
        **FIXTURE_LIMITS,
    }
    if overrides:
        payload.update(overrides)
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return write_private_bytes(name, raw)


Responder = Callable[[str, str, dict[str, str], bytes], tuple[int, dict[str, str], bytes]]


class LoopbackCore:
    """One owned loopback HTTP listener recording actual requests."""

    def __init__(self, responder: Responder) -> None:
        self._responder = responder
        self.requests: list[dict[str, Any]] = []
        handler = self._build_handler()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                status, headers, response_body = outer._responder(
                    self.command, self.path, dict(self.headers), body
                )
                outer.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": body,
                    }
                )
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(response_body)

            do_GET = _handle
            do_POST = _handle
            do_HEAD = _handle

            def log_message(self, _format: str, *_args: object) -> None:
                return

        return Handler

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def start(self) -> LoopbackCore:
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def json_response(
    payload: Any, *, status: int = 200, ack: bool = True
) -> tuple[int, dict[str, str], bytes]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if ack:
        headers["X-KSI-Spatial-Data-AI-Egress"] = "ALLOWED"
    return status, headers, body
