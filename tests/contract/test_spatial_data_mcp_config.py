"""Config contract tests for the spatial-data MCP stdio adapter (RED first)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import spatial_data_mcp_fixture as fixture

fixture.ensure_source_path()


def _valid_config_path(origin: str, token: Path, **overrides: object) -> Path:
    return fixture.write_adapter_config(
        f"config-{token.name}.json",
        origin=origin,
        token_path=token,
        overrides=dict(overrides),
    )


def test_from_file_accepts_private_loopback_config_and_rereads_rotated_token() -> None:
    from ksi_spatial_data_mcp.config import AdapterConfig

    token = fixture.write_token("config-basic-token", "first-opaque-token")
    config = AdapterConfig.from_file(
        _valid_config_path("http://127.0.0.1:9", token),
    )
    assert config.core_origin == "http://127.0.0.1:9"
    assert config.max_request_bytes == 8192
    assert config.max_structured_response_bytes == 131072
    assert config.max_concurrent_calls == 2
    assert config.read_token() == "first-opaque-token"
    # Legitimate replacement between calls re-reads safely.
    token.write_text("second-opaque-token\n", encoding="ascii")
    token.chmod(0o600)
    assert config.read_token() == "second-opaque-token"


def test_from_file_rejects_absent_unknown_and_nonfinite_limits() -> None:
    from ksi_spatial_data_mcp.config import (
        AdapterConfig,
        AdapterConfigurationError,
    )

    token = fixture.write_token("config-limits-token")
    base = {"coreOrigin": "http://127.0.0.1:9", "tokenFile": os.fspath(token)}
    base.update(fixture.FIXTURE_LIMITS)

    def write(payload: dict[str, Any]) -> Path:
        case = abs(hash(json.dumps(payload, sort_keys=True, default=str))) % 10_000_000
        return fixture.write_private_bytes(
            f"config-case-{len(payload)}-{case}.json",
            json.dumps(payload).encode(),
        )

    missing = dict(base)
    del missing["maxRequestBytes"]
    with pytest.raises(AdapterConfigurationError):
        AdapterConfig.from_file(write(missing))
    with pytest.raises(AdapterConfigurationError):
        AdapterConfig.from_file(write({**base, "unexpectedField": 1}))
    for bad in (0, -5, True, False, "8192", float("nan"), float("inf"), 8.5):
        with pytest.raises(AdapterConfigurationError):
            AdapterConfig.from_file(write({**base, "maxRequestBytes": bad}))
    for bad_timeout in (0, -1.0, True, float("nan"), "2.0"):
        with pytest.raises(AdapterConfigurationError):
            AdapterConfig.from_file(write({**base, "readTimeoutSeconds": bad_timeout}))
    # Duplicate JSON keys are rejected, not last-wins.
    raw = (
        b'{"coreOrigin":"http://127.0.0.1:9","tokenFile":"'
        + os.fspath(token).encode()
        + b'","maxRequestBytes":8192,"maxRequestBytes":8192}'
    )
    with pytest.raises(AdapterConfigurationError):
        AdapterConfig.from_file(fixture.write_private_bytes("config-duplicate.json", raw))
    # Bearer material never lives in config values.
    sneaky = dict(base)
    sneaky["tokenFile"] = os.fspath(token)
    sneaky["coreOrigin"] = "http://127.0.0.1:9"
    with pytest.raises(AdapterConfigurationError):
        AdapterConfig.from_file(write({**base, "cursorSeed": "Bearer abc"}))
    # Control characters in parsed strings are rejected.
    with pytest.raises(AdapterConfigurationError):
        AdapterConfig.from_file(write({**base, "coreOrigin": "http://127.0.0.1:9\u0000"}))


def test_from_file_rejects_unsafe_files_and_parents() -> None:
    from ksi_spatial_data_mcp.config import (
        AdapterConfig,
        AdapterConfigurationError,
    )

    token = fixture.write_token("config-unsafe-token")
    good = _valid_config_path("http://127.0.0.1:9", token)
    # World-writable parent is unsafe even for an otherwise private file.
    exposed_dir = fixture.private_dir() / "exposed-parent"
    exposed_dir.mkdir(exist_ok=True)
    exposed = exposed_dir / "config.json"
    exposed.write_bytes(good.read_bytes())
    exposed.chmod(0o600)
    exposed_dir.chmod(0o777)
    try:
        with pytest.raises(AdapterConfigurationError):
            AdapterConfig.from_file(exposed)
    finally:
        exposed_dir.chmod(0o700)
    # Symlinked file, symlinked ancestor, and hardlinks are rejected.
    link = fixture.private_dir() / "config-link.json"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(good)
    with pytest.raises(AdapterConfigurationError):
        AdapterConfig.from_file(link)
    link.unlink()
    hard = fixture.private_dir() / "config-hard.json"
    if hard.exists():
        hard.unlink()
    os.link(good, hard)
    try:
        with pytest.raises(AdapterConfigurationError):
            AdapterConfig.from_file(hard)
    finally:
        hard.unlink()
    loose = fixture.write_private_bytes("config-loose.json", good.read_bytes())
    loose.chmod(0o640)
    with pytest.raises(AdapterConfigurationError):
        AdapterConfig.from_file(loose)
    relative = Path("relative-config.json")
    with pytest.raises(AdapterConfigurationError):
        AdapterConfig.from_file(relative)


def test_token_file_rules_reject_loose_oversized_and_missing() -> None:
    from ksi_spatial_data_mcp.config import (
        AdapterConfig,
        AdapterConfigurationError,
    )

    token = fixture.write_token("config-token-rules")
    config = AdapterConfig.from_file(_valid_config_path("http://127.0.0.1:9", token))
    assert config.read_token() == "fixture-opaque-token"
    token.chmod(0o644)
    with pytest.raises(AdapterConfigurationError):
        AdapterConfig.from_file(_valid_config_path("http://127.0.0.1:9", token))
    token.chmod(0o600)
    token.write_bytes(b"x" * 4097 + b"\n")
    token.chmod(0o600)
    with pytest.raises(AdapterConfigurationError):
        config.read_token()
    token.write_text("has whitespace\nsecond\n", encoding="ascii")
    token.chmod(0o600)
    with pytest.raises(AdapterConfigurationError):
        config.read_token()
    token.unlink()
    with pytest.raises(AdapterConfigurationError):
        config.read_token()


def test_origin_rules_and_no_proxy_or_redirect() -> None:
    from ksi_spatial_data_mcp.config import (
        AdapterConfig,
        AdapterConfigurationError,
    )

    token = fixture.write_token("config-origin-token")
    AdapterConfig.from_file(_valid_config_path("http://127.0.0.1:9", token))
    AdapterConfig.from_file(_valid_config_path("https://192.0.2.10:8443", token))
    AdapterConfig.from_file(_valid_config_path("http://[::1]:9", token))
    AdapterConfig.from_file(_valid_config_path("https://core.internal", token))
    for bad in (
        "http://core.internal",
        "http://192.0.2.10",
        "http://127.0.0.1:9/base",
        "http://127.0.0.1:9?x=1",
        "http://127.0.0.1:9#frag",
        "http://user@127.0.0.1:9",
        "http://127.0.0.1:9 ",
        "ftp://127.0.0.1:9",
    ):
        with pytest.raises(AdapterConfigurationError):
            AdapterConfig.from_file(_origin_config(token, bad))
    config = AdapterConfig.from_file(_valid_config_path("http://127.0.0.1:9", token))
    kwargs = config.http_client_kwargs()
    assert kwargs["trust_env"] is False
    assert kwargs["follow_redirects"] is False
    assert kwargs["verify"] is True


def _origin_config(token: Path, origin: str) -> Path:
    return fixture.write_adapter_config(
        f"origin-{abs(hash(origin)) % 10_000_000}.json",
        origin="http://127.0.0.1:9",
        token_path=token,
        overrides={"coreOrigin": origin},
    )


def test_tmp_parent_configs_are_rejected(tmp_path: Path) -> None:
    """The world-writable /tmp ancestry must fail; scratch is the owned path."""
    from ksi_spatial_data_mcp.config import (
        AdapterConfig,
        AdapterConfigurationError,
    )

    token = tmp_path / "token"
    token.write_text("tmp-token\n", encoding="ascii")
    token.chmod(0o600)
    config = tmp_path / "config.json"
    payload = {
        "coreOrigin": "http://127.0.0.1:9",
        "tokenFile": os.fspath(token),
        **fixture.FIXTURE_LIMITS,
    }
    config.write_text(json.dumps(payload), encoding="utf-8")
    config.chmod(0o600)
    with pytest.raises(AdapterConfigurationError):
        AdapterConfig.from_file(config)


def test_group_writable_ancestor_rejected() -> None:
    """A group-writable parent is unsafe even when owned by the caller."""
    from ksi_spatial_data_mcp.config import (
        AdapterConfig,
        AdapterConfigurationError,
    )

    token = fixture.write_token("config-group-token")
    good = _valid_config_path("http://127.0.0.1:9", token)
    group_dir = fixture.private_dir() / "group-parent"
    group_dir.mkdir(exist_ok=True)
    exposed = group_dir / "config.json"
    exposed.write_bytes(good.read_bytes())
    exposed.chmod(0o600)
    group_dir.chmod(0o770)
    try:
        with pytest.raises(AdapterConfigurationError):
            AdapterConfig.from_file(exposed)
    finally:
        group_dir.chmod(0o700)


def test_post_read_mutation_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A file swapped during the read must fail, not be accepted on lstat alone."""
    import os as _os

    from ksi_spatial_data_mcp.config import (
        AdapterConfig,
        AdapterConfigurationError,
    )

    token = fixture.write_token("config-race-token")
    path = _valid_config_path("http://127.0.0.1:9", token)
    real_read = _os.read

    def mutating_read(descriptor: int, size: int) -> bytes:
        data = real_read(descriptor, size)
        with open(os.fspath(path), "ab") as handle:
            handle.write(b" ")
        return data

    monkeypatch.setattr(_os, "read", mutating_read)
    with pytest.raises(AdapterConfigurationError):
        AdapterConfig.from_file(path)


def test_token_fixed_ceiling_ignores_owner_quota() -> None:
    """The 4096B+CRLF token representation ceiling holds for any owner quota."""
    from ksi_spatial_data_mcp.config import (
        AdapterConfig,
        AdapterConfigurationError,
    )

    token = fixture.write_token("config-big-quota-token", "x" * 5000)
    path = fixture.write_adapter_config(
        "config-big-quota.json",
        origin="http://127.0.0.1:9",
        token_path=token,
        overrides={"maxTokenBytes": 100000},
    )
    with pytest.raises(AdapterConfigurationError):
        AdapterConfig.from_file(path)


def test_token_rejects_controls_and_whitespace() -> None:
    from ksi_spatial_data_mcp.config import (
        AdapterConfig,
        AdapterConfigurationError,
    )

    token = fixture.write_token("config-token-chars")
    config = AdapterConfig.from_file(_valid_config_path("http://127.0.0.1:9", token))
    assert config.read_token() == "fixture-opaque-token"
    # Whitespace, controls, and DEL are never valid token bytes.
    for bad in ("bearer opaque", "tok\x7fen", "tok\x00en", " tok"):
        token.write_bytes((bad + "\n").encode("ascii"))
        token.chmod(0o600)
        with pytest.raises(AdapterConfigurationError):
            config.read_token()
    # A bare opaque word prefix without scheme whitespace is legitimate.
    token.write_bytes(b"Bearerabc\n")
    token.chmod(0o600)
    assert config.read_token() == "Bearerabc"


def test_deeply_nested_config_fails_closed_without_traceback() -> None:
    """C-level JSON recursion inside the parse ceiling must stay a safe error."""
    import subprocess
    import sys

    raw = ("[" * 10000 + "]" * 10000).encode("ascii")
    assert len(raw) < 65536
    path = fixture.write_private_bytes("config-deep.json", raw)
    probe = (
        "import sys; sys.path.insert(0, "
        + repr(os.fspath(fixture.PACKAGE_SRC))
        + "); from ksi_spatial_data_mcp.config import AdapterConfig, "
        + "AdapterConfigurationError; "
        + "try:\n"
        + f"    AdapterConfig.from_file({repr(os.fspath(path))})\n"
        + "except AdapterConfigurationError:\n"
        + "    raise SystemExit(2)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60
    )
    assert completed.returncode != 0
    assert "Traceback" not in completed.stderr
    assert "RecursionError" not in completed.stderr


def test_exact_dns_https_origin_accepted_without_network() -> None:
    """Approved exact DNS HTTPS origins parse; only HTTP must be literal-loopback."""
    from ksi_spatial_data_mcp.config import (
        AdapterConfig,
        AdapterConfigurationError,
    )

    token = fixture.write_token("config-dns-token")
    AdapterConfig.from_file(_origin_config(token, "https://core.example.com"))
    AdapterConfig.from_file(_origin_config(token, "https://core.example.com:8443"))
    for bad in (
        "http://core.example.com",
        "https://user@core.example.com",
        "https://core.example.com/base",
        "https://core.example.com?x=1",
        "https://core.example.com#frag",
        "https://core.example.com:99999",
        "https://core.ex ample.com",
        "https://[::1%lo]",
    ):
        with pytest.raises(AdapterConfigurationError):
            AdapterConfig.from_file(_origin_config(token, bad))


def test_post_read_chmod_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mode change during the read must not authorize stale file bytes."""
    import os as _os

    from ksi_spatial_data_mcp.config import (
        AdapterConfig,
        AdapterConfigurationError,
    )

    token = fixture.write_token("config-chmod-token")
    path = _valid_config_path("http://127.0.0.1:9", token)
    real_read = _os.read

    def chmod_during_read(descriptor: int, size: int) -> bytes:
        data = real_read(descriptor, size)
        _os.chmod(os.fspath(path), 0o644)
        return data

    monkeypatch.setattr(_os, "read", chmod_during_read)
    try:
        with pytest.raises(AdapterConfigurationError):
            AdapterConfig.from_file(path)
    finally:
        _os.chmod(os.fspath(path), 0o600)


def test_post_read_hardlink_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A link-count change during the read must fail the identity check."""
    import os as _os

    from ksi_spatial_data_mcp.config import (
        AdapterConfig,
        AdapterConfigurationError,
    )

    token = fixture.write_token("config-link-race-token")
    path = _valid_config_path("http://127.0.0.1:9", token)
    alias = fixture.private_dir() / f"{path.name}.alias"
    real_read = _os.read

    def link_during_read(descriptor: int, size: int) -> bytes:
        data = real_read(descriptor, size)
        with suppress_unlink():
            _os.unlink(alias)
        _os.link(os.fspath(path), alias)
        return data

    monkeypatch.setattr(_os, "read", link_during_read)
    try:
        with pytest.raises(AdapterConfigurationError):
            AdapterConfig.from_file(path)
    finally:
        with suppress_unlink():
            _os.unlink(alias)


def suppress_unlink() -> Any:
    import contextlib

    return contextlib.suppress(OSError)


def test_bearerx_opaque_token_accepted() -> None:
    """A legitimate opaque token is not refused for its word prefix."""
    from ksi_spatial_data_mcp.config import AdapterConfig

    token = fixture.write_token("config-bearerx-token", "bearerX-token-9")
    config = AdapterConfig.from_file(_valid_config_path("http://127.0.0.1:9", token))
    assert config.read_token() == "bearerX-token-9"


def test_private_dir_is_unique_owned_scratch() -> None:
    """Generated configs live in a unique mkdtemp dir, never a fixed namespace."""
    import os as _os

    cache = Path.home() / ".cache"
    before = _os.lstat(cache)
    first = fixture.private_dir()
    assert fixture.private_dir() == first
    assert first.parent.parent == cache
    assert first.parent.name.startswith("ksi-spatial-data-mcp-task4-")
    assert first.name == "private"
    assert oct(first.stat().st_mode & 0o777) == "0o700"
    assert oct(first.parent.stat().st_mode & 0o777) == "0o700"
    assert "ksi-spatial-data-mcp-task4/private" not in os.fspath(first)
    after = _os.lstat(cache)
    assert (after.st_mode, after.st_uid) == (before.st_mode, before.st_uid)
