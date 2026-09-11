"""Candidate startup must consume owner-supplied credentials, never invent them."""

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest


def _module() -> ModuleType:
    source = (
        Path(__file__).resolve().parents[2] / "deploy/external-runtime/prepare_candidate_state.py"
    )
    spec = importlib.util.spec_from_file_location("candidate_state", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The fixture uses this process's UID; main() retains fixed service UID 10001.
    module.RUNTIME_UID = os.geteuid()
    module.RUNTIME_GID = os.getegid()
    return module


def test_missing_secret_stays_missing(tmp_path: Path) -> None:
    target = tmp_path / "session.secret"
    with pytest.raises(RuntimeError):
        _module()._secret(target)
    assert not target.exists()


def test_missing_signing_keys_are_not_generated(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        _module()._signing_key_set(tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mode", [0o644, 0o660, 0o777])
def test_open_secret_permissions_are_rejected_not_repaired(tmp_path: Path, mode: int) -> None:
    target = tmp_path / "session.secret"
    target.write_text("test-owned-credential-" * 3)
    target.chmod(mode)
    before = target.stat()
    with pytest.raises(RuntimeError):
        _module()._secret(target)
    assert target.stat() == before


def test_private_secret_is_not_rotated_or_reowned(tmp_path: Path) -> None:
    target = tmp_path / "session.secret"
    target.write_text("test-owned-credential-" * 3)
    target.chmod(0o600)
    before = target.stat()
    _module()._secret(target)
    after = target.stat()
    assert (after.st_ino, after.st_mode, after.st_uid, after.st_gid, after.st_mtime_ns) == (
        before.st_ino, before.st_mode, before.st_uid, before.st_gid, before.st_mtime_ns
    )
    assert target.read_text() == "test-owned-credential-" * 3


def test_symlink_secret_is_rejected_without_changing_target(tmp_path: Path) -> None:
    target = tmp_path / "real.secret"
    target.write_text("test-owned-credential-" * 3)
    target.chmod(0o600)
    link = tmp_path / "session.secret"
    link.symlink_to(target)
    with pytest.raises(RuntimeError):
        _module()._secret(link)
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "raw", [b"", b"short", b" " * 64, b"x" * 16_385, b"x" * 64 + b"\x00", b"\xff" * 64]
)
def test_malformed_secret_is_rejected(tmp_path: Path, raw: bytes) -> None:
    target = tmp_path / "session.secret"
    target.write_bytes(raw)
    target.chmod(0o600)
    with pytest.raises(RuntimeError):
        _module()._secret(target)
    assert target.read_bytes() == raw


def test_existing_signing_set_is_validated_without_changes(tmp_path: Path) -> None:
    from test_production_assembly import _write_signing_keys

    _write_signing_keys(tmp_path)
    for path in tmp_path.iterdir():
        path.chmod(0o600 if ".private." in path.name else 0o644)
    before = {p.name: (p.read_bytes(), p.stat().st_mode) for p in tmp_path.iterdir()}
    _module()._signing_key_set(tmp_path)
    assert {p.name: (p.read_bytes(), p.stat().st_mode) for p in tmp_path.iterdir()} == before


def test_init_reader_cannot_bless_credentials_for_another_runtime_uid(tmp_path: Path) -> None:
    path = tmp_path / "session.secret"
    path.write_text("test-owned-credential-" * 3)
    path.chmod(0o600)
    module = _module()
    module.RUNTIME_UID = os.geteuid() + 1
    with pytest.raises(RuntimeError):
        module._secret(path)


def test_missing_owner_read_bit_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "session.secret"
    path.write_text("test-owned-credential-" * 3)
    path.chmod(0o000)
    try:
        with pytest.raises(RuntimeError):
            _module()._secret(path)
    finally:
        path.chmod(0o600)


@pytest.mark.parametrize(
    "filename", ["keys.json", "core-prod-test-key.public.pem", "core-prod-test-key.private.pem"]
)
def test_credential_replaced_before_semantic_load_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    from test_production_assembly import _write_signing_keys

    keys = tmp_path / "keys"
    _write_signing_keys(keys)
    for path in keys.iterdir():
        path.chmod(0o600 if ".private." in path.name else 0o644)
    target = keys / filename
    replacement = tmp_path / "replacement"
    replacement.write_bytes(target.read_bytes())
    replacement.chmod(target.stat().st_mode & 0o777)
    module = _module()
    original = module.load_signing_keys

    def substitute(path: Path, **kwargs: object) -> object:
        target.unlink()
        target.symlink_to(replacement)
        return original(path, **kwargs)

    monkeypatch.setattr(module, "load_signing_keys", substitute)
    with pytest.raises(RuntimeError):
        module._signing_key_set(keys)


def test_semantic_snapshot_loader_never_reopens_files(tmp_path: Path) -> None:
    from ksi_core.signing_keys import load_signing_keys
    from test_production_assembly import _write_signing_keys

    _write_signing_keys(tmp_path)
    snapshot = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    # Only the test-created files are removed; validation must consume captured bytes.
    for path in tmp_path.iterdir():
        path.unlink()
    loaded = load_signing_keys(tmp_path, verified_files=snapshot)
    assert loaded.active_key_id == "core-prod-test-key"


@pytest.mark.parametrize(
    "filename", ["keys.json", "core-prod-test-key.public.pem", "core-prod-test-key.private.pem"]
)
@pytest.mark.parametrize("invalid", [None, "not-bytes", bytearray(b"not-bytes")])
def test_invalid_snapshot_values_never_reopen_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str, invalid: object
) -> None:
    from typing import cast

    from ksi_core.signing_keys import SigningKeyError, load_signing_keys
    from test_production_assembly import _write_signing_keys

    _write_signing_keys(tmp_path)
    snapshot: dict[str, object] = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    snapshot[filename] = invalid

    def forbidden_read(path: Path) -> bytes:
        raise AssertionError("verified snapshot reopened a path")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read)
    with pytest.raises(SigningKeyError):
        load_signing_keys(tmp_path, verified_files=cast(dict[str, bytes], snapshot))


@pytest.mark.parametrize("snapshot_mode", [False, True])
def test_signing_manifest_requires_utf8(tmp_path: Path, snapshot_mode: bool) -> None:
    from ksi_core.signing_keys import SigningKeyError, load_signing_keys
    from test_production_assembly import _write_signing_keys

    _write_signing_keys(tmp_path)
    manifest = tmp_path / "keys.json"
    manifest.write_bytes(manifest.read_text(encoding="utf-8").encode("utf-16"))
    snapshot = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(SigningKeyError):
        load_signing_keys(tmp_path, verified_files=snapshot if snapshot_mode else None)


def test_validate_only_checks_exact_material_without_state_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    observed: list[Path] = []
    monkeypatch.setattr(module, "_secret", observed.append)
    monkeypatch.setattr(module, "_signing_key_set", observed.append)

    def forbidden_write(path: Path) -> None:
        raise AssertionError(f"validation attempted state write: {path}")

    monkeypatch.setattr(module, "_runtime_directory", forbidden_write)
    module.main(["--validate-only"])
    assert observed == [
        Path("/state/secrets/dashboard-session.secret"),
        Path("/state/secrets/oidc-client.secret"),
        Path("/state/signing"),
    ]


def test_validate_only_propagates_failed_credentials_before_any_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    def invalid_secret(path: Path) -> None:
        raise RuntimeError("missing supplied material")

    def forbidden_write(path: Path) -> None:
        raise AssertionError("invalid material caused state write")

    monkeypatch.setattr(module, "_secret", invalid_secret)
    monkeypatch.setattr(module, "_runtime_directory", forbidden_write)
    with pytest.raises(RuntimeError, match="missing supplied material"):
        module.main(["--validate-only"])


def test_unknown_validation_option_fails_before_any_material_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    def forbidden_access(path: Path) -> None:
        raise AssertionError("unknown option reached material validation")

    monkeypatch.setattr(module, "_secret", forbidden_access)
    with pytest.raises(SystemExit) as exc:
        module.main(["--unapproved-path", "/elsewhere"])
    assert exc.value.code == 2
