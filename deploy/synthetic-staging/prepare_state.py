#!/usr/bin/env python3
"""Initialize disposable Phase 2 staging volumes without production credentials."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

RUNTIME_UID = 10001
RUNTIME_GID = 10001
STATE_ROOTS = (
    Path("/state/data"),
    Path("/state/identity"),
    Path("/state/secrets"),
    Path("/state/signing"),
)


def _runtime_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, RUNTIME_UID, RUNTIME_GID)
    path.chmod(0o700)


def _secret(path: Path) -> None:
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    os.chown(path, RUNTIME_UID, RUNTIME_GID)
    path.chmod(0o400)


def _signing_key_set(path: Path) -> None:
    key_id = "phase2-synthetic-key-1"
    manifest = path / "keys.json"
    private_path = path / f"{key_id}.private.pem"
    public_path = path / f"{key_id}.public.pem"
    existing = [item.exists() for item in (manifest, private_path, public_path)]
    if any(existing) and not all(existing):
        raise RuntimeError("synthetic signing key set is partial; refusing silent regeneration")
    if not all(existing):
        key = Ed25519PrivateKey.generate()
        private_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        public_path.write_bytes(
            key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        manifest.write_text(
            json.dumps(
                {
                    "active": key_id,
                    "keys": [{"keyId": key_id, "status": "ACTIVE"}],
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    for item in (manifest, private_path, public_path):
        os.chown(item, RUNTIME_UID, RUNTIME_GID)
    private_path.chmod(0o600)
    manifest.chmod(0o444)
    public_path.chmod(0o444)


def main() -> None:
    for path in STATE_ROOTS:
        _runtime_directory(path)
    _secret(Path("/state/secrets/dashboard-session.secret"))
    _secret(Path("/state/secrets/oidc-client.secret"))
    _secret(Path("/state/secrets/copilot-api-key.secret"))
    _signing_key_set(Path("/state/signing"))
    print("synthetic staging state ready")


if __name__ == "__main__":
    main()
