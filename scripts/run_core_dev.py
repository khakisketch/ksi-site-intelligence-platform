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
import json
import shutil
from pathlib import Path

import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.coverage_reports import CoverageReportStore
from ksi_core.durable_journal import DurableJournal
from ksi_core.edge_sync import EdgeSyncStore
from ksi_core.events import EventStore
from ksi_core.mission_records import MissionStore
from ksi_core.signing_keys import SigningKeySet, load_signing_keys
from ksi_core.sites import SiteStore

_DEV_TOKENS: dict[Role, str] = {
    Role.ADMIN: "dev-admin-token",
    Role.FIELD_OPERATOR: "dev-field-operator-token",
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


def _bootstrap_key_set(signing_dir: Path) -> SigningKeySet:
    """dev 키 세트를 준비한다 — 없으면 만들고, 있으면 **검증해서** 읽는다.

    부트스트랩만 dev 편의이고 로드는 운영과 같은 경로(:func:`load_signing_keys`)를
    탄다 — 개인키 권한·공개키 불일치·활성 키 REVOKED 를 여기서도 똑같이 거부한다.
    dev 조립이 느슨한 경로를 따로 가지면 그 검사들이 운영에서 처음 실행된다.

    회전은 이 함수가 하지 않는다(docs/security/SIGNING_KEY_LIFECYCLE.md 절차) —
    keys.json 이 이미 있으면 손대지 않는다.
    """
    manifest = signing_dir / "keys.json"
    if not manifest.exists():
        signing_dir.mkdir(parents=True, exist_ok=True)
        key_id = "core-dev-key-1"
        key = Ed25519PrivateKey.generate()
        private_path = signing_dir / f"{key_id}.private.pem"
        private_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        # 0600 — load_signing_keys 가 이 권한을 강제한다(운영과 같은 규칙).
        private_path.chmod(0o600)
        (signing_dir / f"{key_id}.public.pem").write_bytes(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        manifest.write_text(
            json.dumps({"active": key_id, "keys": [{"keyId": key_id, "status": "ACTIVE"}]}),
            encoding="utf-8",
        )
    return load_signing_keys(signing_dir)


def cli_optional_positive(value: int, *, name: str) -> int | None:
    """CLI 의 "0 = 없음" 규약을 생성자의 ``None`` 으로 옮긴다.

    생성자들은 0·음수를 거부하고 "없음"은 ``None`` 으로만 표현한다(조용히
    0 으로 뭉개지 않기 위해서다). CLI 쪽에서 0 을 그 뜻으로 받는 규약은 여기
    한 곳에만 둔다 — 이 저장소의 **유일한 조립 지점**이라 여기 배선이 틀리면
    라이브러리 테스트가 전부 green 인 채로 통과한다(독립 재검토 지적).

    음수는 argparse 를 통과하므로 여기서 typed 로 막는다 — 생성자까지 흘려보내면
    실패 메시지가 CLI 인자 이름을 잃는다.
    """
    if value < 0:
        raise ValueError(f"{name} 는 0(없음) 이거나 양수여야 한다: {value}")
    return value or None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", default=".dev-data/core")
    parser.add_argument("--reset", action="store_true", help="기존 데이터 삭제 후 새로 시작")
    parser.add_argument(
        "--journal-segment-bytes",
        type=int,
        default=64 * 1024 * 1024,
        help="journal 세그먼트 회전 임계(바이트, 기본 64MiB). 0 이면 회전하지 않는다.",
    )
    parser.add_argument(
        "--edge-sync-snapshot-every",
        type=int,
        default=500,
        help=(
            "edge-sync 원장 스냅샷 주기(수락 건수, 기본 500). 0 이면 스냅샷을 쓰지 않는다 "
            "— 재기동이 전 항목의 본문 정규화·digest 재계산을 다시 치른다."
        ),
    )
    # Evidence 스토리지(ADR-KSI-010 §1) — **주지 않으면 증거 경로가 장착되지 않는다**(404).
    # 조립되지 않은 기능이 2xx 로 보이는 것보다 없는 편이 정직하다.
    parser.add_argument(
        "--s3-endpoint",
        default=None,
        help="S3 호환 엔드포인트(예: http://127.0.0.1:9000). --s3-bucket 과 함께 준다.",
    )
    parser.add_argument("--s3-bucket", default=None, help="증거 버킷 이름")
    args = parser.parse_args()

    if bool(args.s3_endpoint) != bool(args.s3_bucket):
        parser.error("--s3-endpoint 와 --s3-bucket 은 함께 주어야 한다")

    data_dir = Path(args.data_dir)
    if args.reset and data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    key_set = _bootstrap_key_set(data_dir / "signing")

    # 세그먼트 회전(S4) — 활성 파일이 이 크기를 넘으면 봉인 세그먼트로 넘긴다.
    # 회전 임계는 **조립 지점의 결정**이다(DurableJournal 기본값은 회전 없음) —
    # 한 파일이 무한히 커지면 재기동 재생이 선형으로 느려지고 백업 단위도 사라진다.
    # 여기 값은 dev 조립 기준이고, 운영 조립은 디스크·백업 주기에 맞춰 자기 값을 준다.
    # CLI 는 0 을 "회전 없음"으로 받는다(생성자는 None). 음수는 argparse 를 통과하지만
    # 생성자가 ValueError 로 거부한다 — 조용히 0 으로 뭉개지 않는다.
    segment_bytes = cli_optional_positive(
        args.journal_segment_bytes, name="--journal-segment-bytes"
    )
    site_journal = DurableJournal(data_dir / "sites.jsonl", max_segment_bytes=segment_bytes)
    mission_journal = DurableJournal(data_dir / "missions.jsonl", max_segment_bytes=segment_bytes)
    event_journal = DurableJournal(data_dir / "events.jsonl", max_segment_bytes=segment_bytes)
    # edge-sync 는 회전이 아니라 스냅샷으로 재기동 비용을 잡는다 — 이 원장의
    # 재기동 비용은 파일 크기가 아니라 항목당 payload 정규화+sha256 이기 때문이다.
    edge_sync_store = EdgeSyncStore(
        data_dir / "edge-sync.jsonl",
        snapshot_every=cli_optional_positive(
            args.edge_sync_snapshot_every, name="--edge-sync-snapshot-every"
        ),
    )

    evidence_storage = None
    if args.s3_endpoint:
        from ksi_core.evidence_s3 import S3EvidenceStorage

        evidence_storage = S3EvidenceStorage(
            bucket=args.s3_bucket, endpoint_url=args.s3_endpoint
        )

    mission_store = MissionStore(mission_journal)
    # 커버리지 보고는 임무 발급 기록과 대조해서만 받는다(INV-010) — 발급된 적
    # 없는 임무의 관찰 결과는 "무슨 근거로 날았나"에 답할 수 없다.
    coverage_journal = DurableJournal(
        data_dir / "coverage-reports.jsonl", max_segment_bytes=segment_bytes
    )
    app = create_app(
        auth_registry=_auth_registry(),
        site_store=SiteStore(site_journal),
        mission_store=mission_store,
        event_store=EventStore(event_journal),
        edge_sync_store=edge_sync_store,
        evidence_storage=evidence_storage,
        coverage_report_store=CoverageReportStore(
            coverage_journal, mission_store=mission_store
        ),
        mission_signing_key=key_set.active_private_key,
        mission_signing_key_id=key_set.active_key_id,
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
        coverage_journal.close()
        edge_sync_store.close()


if __name__ == "__main__":
    main()
