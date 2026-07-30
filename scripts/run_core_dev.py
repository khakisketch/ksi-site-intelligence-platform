#!/usr/bin/env python3
"""KSI Core 로컬 개발 서버 — apps/dashboard 연동용.

프로덕션 조립이 아니다. durable 저장소를 로컬 디스크(--data-dir)에 열고, 고정
dev 토큰으로 AuthRegistry를 구성해 uvicorn으로 기동한다. 데이터는 재기동해도
보존된다(--reset으로 초기화). 서명키는 최초 기동 시 생성해 data-dir에 저장하고
이후 재사용한다.

Usage:
    uv run python scripts/run_core_dev.py [--host 127.0.0.1] [--port 8000] [--reset]
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.edge_sync import EdgeSyncStore
from ksi_core.events import EventStore
from ksi_core.mission_records import MissionStore
from ksi_core.sites import SiteStore

_KEY_ID = "core-dev-key-1"

_DEV_TOKENS: dict[Role, str] = {
    Role.ADMIN: "dev-admin-token",
    Role.SITE_MANAGER: "dev-site-manager-token",
    Role.SAFETY_MANAGER: "dev-safety-manager-token",
    Role.DRONE_OPERATOR: "dev-drone-operator-token",
    Role.VIEWER: "dev-viewer-token",
}
_DEV_EDGE_TOKEN = "dev-edge-device-token"  # noqa: S105 — 로컬 dev 전용 고정값
_DEV_EDGE_DEVICE_ID = "edge-dev-001"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    records = [
        PrincipalTokenRecord(
            token_sha256=_digest(token),
            principal=Principal(
                principal_id=f"dev-{role.value.lower()}",
                kind=PrincipalKind.OPERATOR,
                role=role,
                device_id=None,
            ),
        )
        for role, token in _DEV_TOKENS.items()
    ]
    records.append(
        PrincipalTokenRecord(
            token_sha256=_digest(_DEV_EDGE_TOKEN),
            principal=Principal(
                principal_id="dev-edge-principal",
                kind=PrincipalKind.EDGE_DEVICE,
                role=None,
                device_id=_DEV_EDGE_DEVICE_ID,
            ),
        )
    )
    return AuthRegistry(records)


def _load_or_create_signing_key(path: Path) -> Ed25519PrivateKey:
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise TypeError(f"{path} does not contain an Ed25519 private key")
        return key
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    return key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", default=".dev-data/core")
    parser.add_argument("--reset", action="store_true", help="기존 데이터 삭제 후 새로 시작")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if args.reset and data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    private_key = _load_or_create_signing_key(data_dir / "signing_key.pem")

    site_journal = DurableJournal(data_dir / "sites.jsonl")
    mission_journal = DurableJournal(data_dir / "missions.jsonl")
    event_journal = DurableJournal(data_dir / "events.jsonl")
    edge_sync_store = EdgeSyncStore(data_dir / "edge-sync.jsonl")

    app = create_app(
        auth_registry=_auth_registry(),
        site_store=SiteStore(site_journal),
        mission_store=MissionStore(mission_journal),
        event_store=EventStore(event_journal),
        edge_sync_store=edge_sync_store,
        mission_signing_key=private_key,
        mission_signing_key_id=_KEY_ID,
    )

    print("=" * 72)
    print(f"KSI Core dev server — data: {data_dir.resolve()}")
    print("Dev bearer tokens (Authorization: Bearer <token>):")
    for role, token in _DEV_TOKENS.items():
        print(f"  {role.value:16s} {token}")
    print(f"  EDGE_DEVICE({_DEV_EDGE_DEVICE_ID}) {_DEV_EDGE_TOKEN}")
    print("=" * 72)

    try:
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        site_journal.close()
        mission_journal.close()
        event_journal.close()
        edge_sync_store.close()


if __name__ == "__main__":
    main()
