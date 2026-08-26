#!/usr/bin/env python3
"""Create owner-only non-production Compose inputs for Phase 2 staging."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shlex
from pathlib import Path


def _line(name: str, value: str) -> str:
    if any(character in value for character in "\r\n"):
        raise ValueError(f"{name} contains a newline")
    return f"{name}={shlex.quote(value)}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host", required=True)
    args = parser.parse_args()
    if not args.host.endswith(".ts.net"):
        parser.error("synthetic staging host must be a Tailnet MagicDNS name")
    output = args.output.resolve()
    if output.exists():
        print(output)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    minio_user = f"ksi-phase2-{secrets.token_hex(6)}"
    minio_password = secrets.token_urlsafe(36)
    unused_opaque = secrets.token_urlsafe(32)
    principal_tokens = json.dumps(
        [
            {
                "tokenSha256": hashlib.sha256(unused_opaque.encode()).hexdigest(),
                "principalId": "phase2-unused-opaque-viewer",
                "organizationId": "org-local-pilot",
                "kind": "OPERATOR",
                "role": "VIEWER",
            }
        ],
        separators=(",", ":"),
    )
    values = {
        "KSI_STAGING_PROJECT_NAME": "ksi-phase2-staging",
        "KSI_STAGING_HOST": args.host,
        "KSI_STAGING_APP_PORT": "10000",
        "KSI_STAGING_IDENTITY_PORT": "10001",
        "KSI_STAGING_API_PORT": "10002",
        "KSI_STAGING_OBJECTS_PORT": "10003",
        "KSI_STAGING_MINIO_CONSOLE_PORT": "10004",
        "KSI_STAGING_PRINCIPAL_TOKENS_JSON": principal_tokens,
        "MINIO_ROOT_USER": minio_user,
        "MINIO_ROOT_PASSWORD": minio_password,
        "AWS_ACCESS_KEY_ID": minio_user,
        "AWS_SECRET_ACCESS_KEY": minio_password,
    }
    output.write_text(
        "\n".join(_line(name, value) for name, value in values.items()) + "\n",
        encoding="utf-8",
    )
    output.chmod(0o600)
    print(output)


if __name__ == "__main__":
    main()
