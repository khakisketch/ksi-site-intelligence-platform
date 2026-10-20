#!/usr/bin/env python3
"""Initialize disposable Phase 2 staging volumes without production credentials."""

from __future__ import annotations

import importlib.util
import json
import os
import secrets
import sys
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
ISSUER_TOOL = Path("/app/tools/run_local_oidc_issuer.py")
# 현장 등록 capability 를 받을 개발 계정. OIDC issuer 가 실제로 발급하는 subject
# 이름이어야 Core 의 subject registry 가 그 신원을 SITE_BOOTSTRAP 으로 본다.
BOOTSTRAP_ACCOUNTS = ("local-admin", "local-field-operator")


def _runtime_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, RUNTIME_UID, RUNTIME_GID)
    path.chmod(0o700)


def _secret(path: Path) -> None:
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    os.chown(path, RUNTIME_UID, RUNTIME_GID)
    path.chmod(0o400)


def _development_accounts() -> list[dict[str, str]]:
    """issuer 가 실제로 발급하는 개발 계정 목록을 그대로 읽는다.

    계정 목록을 두 곳에 적으면 안 된다 — issuer 가 발급하는 subject 와 Core 의
    subject registry 가 어긋나면 로그인 자체가 401 이 된다. 그래서 같은 파일에서
    읽는다(모듈 import 는 app 을 만들지 않는다 — app 은 main() 안에서 만들어진다).
    """
    spec = importlib.util.spec_from_file_location("ksi_local_oidc_issuer", ISSUER_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError("local OIDC issuer tool is not loadable")
    module = importlib.util.module_from_spec(spec)
    # dataclasses(slots=True)는 class 생성 시점에 sys.modules 의 모듈 dict를
    # 본다 — 등록 없이 exec 하면 NoneType.__dict__ 로 죽는다.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    accounts = getattr(module, "_DEVELOPMENT_ACCOUNTS", None)
    if not accounts:
        raise RuntimeError("local OIDC issuer exposes no development accounts")
    return [dict(account) for account in accounts]


def _subject_registry(path: Path, issuer: str) -> None:
    """Core 가 요구하는 보호 OIDC subject registry 를 만든다.

    2026-10-20: OIDC 모드 Core 는 subject registry 파일 없이는 기동하지 않는다
    (기본값으로 넘어가지 않는다). 그래서 이 스택은 이전처럼 "registry 없는" 상태로
    뜰 수 없다 — issuer 의 계정 목록에서 registry 를 만들어 낸다.
    """
    subjects = []
    for account in _development_accounts():
        principal_id = account["principal_id"]
        subjects.append(
            {
                "issuer": issuer,
                "subject": principal_id,
                "principalId": principal_id,
                "organizationId": account["organization_id"],
                "role": account["role"],
                "status": "ACTIVE",
                # null 은 "자기 조직 전체"(v2 명시 null). 빈 목록은 접근 없음이므로
                # 여기서 쓰지 않는다 — 개발 계정은 자기 조직 전체를 본다.
                "allowedSiteIds": None,
                "allowedWorkAreaIds": None,
                "capabilities": (["SITE_BOOTSTRAP"] if principal_id in BOOTSTRAP_ACCOUNTS else []),
            }
        )
    document = {"version": "oidc-subject-registry.v2", "subjects": subjects}
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    os.chown(path, RUNTIME_UID, RUNTIME_GID)
    # Core 의 보호 파일 규약: 파일은 euid 소유·egid 그룹이고 mode 는 정확히 0600
    # 이어야 한다(0400 은 "읽기 전용"이 아니라 규약 위반이다).
    path.chmod(0o600)


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
    host = os.environ.get("KSI_STAGING_HOST", "").strip()
    identity_port = os.environ.get("KSI_STAGING_IDENTITY_PORT", "").strip()
    if not host or not identity_port:
        raise RuntimeError(
            "KSI_STAGING_HOST 와 KSI_STAGING_IDENTITY_PORT 가 필요하다 — "
            "subject registry 의 issuer 를 정확히 적어야 한다"
        )
    _subject_registry(
        Path("/state/identity/oidc-subject-registry.json"),
        f"https://{host}:{identity_port}",
    )
    print("synthetic staging state ready")


if __name__ == "__main__":
    main()
