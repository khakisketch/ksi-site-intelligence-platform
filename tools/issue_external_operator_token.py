#!/usr/bin/env python3
"""Issue one opaque OPERATOR token and extend a principal-tokens JSON document.

Deployment scope only (external-runtime candidate step 4): the Core registry
stores ``sha256(token)`` digests, never token plaintext
(``services/core/src/ksi_core/identity/auth.py``).  This tool generates a
strong token, appends exactly one digest row, and proves the resulting
document with the REAL Core loader
(``ksi_core.composition.production_config._parse_principal_tokens`` +
``ksi_core.identity.auth.AuthRegistry.resolve``) before anything is placed.

Scope grants (``allowedSiteIds``/``allowedWorkAreaIds``) are accepted ONLY for
``ANALYSIS_MCP_CLIENT`` by the loader, so an OPERATOR row carries no scope
fields; OPERATOR request scoping (if any) comes from the OIDC subject
registry, which opaque tokens never touch.  In ``KSI_CORE_HUMAN_AUTH_MODE=OIDC``
an opaque OPERATOR token is NOT accepted (see ``resolve_bearer_principal``);
the candidate must run ``DUAL`` for this credential to authenticate.

Secrets are written only to the explicit ``--out-dir`` (0600 files); nothing
secret is printed (only the digest).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import sys
from pathlib import Path


def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(os.fspath(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def issue_operator_token(
    *,
    principal_id: str,
    organization_id: str,
    role: str,
    existing_json: str,
) -> tuple[str, str]:
    """Return ``(raw_token, updated_json)``; raises on any malformed input."""
    entries = json.loads(existing_json)
    if not isinstance(entries, list) or not entries:
        raise ValueError("existing principal-tokens JSON must be a non-empty array")
    raw_token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    if any(entry.get("tokenSha256") == digest for entry in entries if isinstance(entry, dict)):
        raise ValueError("token digest collision — regenerate")
    updated = [
        *entries,
        {
            "tokenSha256": digest,
            "principalId": principal_id,
            "kind": "OPERATOR",
            "organizationId": organization_id,
            "role": role,
        },
    ]
    return raw_token, json.dumps(updated, separators=(",", ":"))


def prove_with_core_loader(*, raw_token: str, updated_json: str) -> dict[str, str]:
    """Parse via the REAL Core loader and resolve the token; return whoami facts."""
    from ksi_core.composition.production_config import _parse_principal_tokens
    from ksi_core.identity.auth import AuthRegistry

    records = _parse_principal_tokens(updated_json)
    registry = AuthRegistry(records)
    principal = registry.resolve(raw_token)
    if principal is None:
        raise ValueError("Core loader proof failed: token does not resolve")
    return {
        "principalId": principal.principal_id,
        "kind": principal.kind.value,
        "role": principal.role.value if principal.role is not None else "",
        "organizationId": principal.organization_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--role", default="ADMIN")
    parser.add_argument("--existing-json-file", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    existing_json = Path(args.existing_json_file).read_text(encoding="utf-8")
    raw_token, updated_json = issue_operator_token(
        principal_id=args.principal_id,
        organization_id=args.organization_id,
        role=args.role,
        existing_json=existing_json,
    )
    facts = prove_with_core_loader(raw_token=raw_token, updated_json=updated_json)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    token_path = out_dir / f"{args.principal_id}.token"
    json_path = out_dir / "principal-tokens.json"
    _write_private(token_path, (raw_token + "\n").encode("ascii"))
    _write_private(json_path, (updated_json + "\n").encode("utf-8"))
    for path in (token_path, json_path):
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode != 0o600:
            raise ValueError(f"refusing to leave {path} at mode {oct(mode)}")
    print(json.dumps({"proved": facts, "tokenFile": str(token_path)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
