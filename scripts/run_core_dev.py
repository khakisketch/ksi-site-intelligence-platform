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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.app_assembly import assemble_app, cli_optional_positive  # noqa: F401 -- re-export
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.observability import configure_structured_logging
from ksi_core.signing_keys import SigningKeySet, load_signing_keys

_DEV_TOKENS: dict[Role, str] = {
    Role.ADMIN: "dev-admin-token",
    Role.FIELD_OPERATOR: "dev-field-operator-token",
    Role.VIEWER: "dev-viewer-token",
}
_DEV_EDGE_TOKEN = "dev-edge-device-token"  # noqa: S105 — 로컬 dev 전용 고정값
_DEV_EDGE_DEVICE_ID = "edge-dev-001"
# 처리 워커 토큰이 따로 있는 이유 — 사람 토큰으로는 처리 작업의 RUNNING·
# SUCCEEDED·FAILED 를 보고할 수 없다(PROCESSING_WORK 는 어느 Role 에도 없다).
# 이 토큰 없이는 재구성 경로를 dev 에서 끝까지 돌려볼 수 없다.
_DEV_WORKER_TOKEN = "dev-processing-worker-token"  # noqa: S105


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
    records.append(
        PrincipalTokenRecord(
            token_sha256=_digest(_DEV_WORKER_TOKEN),
            principal=Principal(
                principal_id="dev-processing-worker",
                kind=PrincipalKind.PROCESSING_WORKER,
                role=None,
                device_id=None,
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


@dataclass(frozen=True, slots=True)
class DevAssembly:
    """조립된 앱 + 종료 시 닫아야 할 원장들.

    ``main`` 만 쓰던 조립을 함수로 뽑은 이유: 이 스크립트가 저장소의 **유일한 실행
    가능한 조립 지점**인데, 여기 무엇이 장착되는지를 검증하는 테스트가 없었다.
    실제로 2026-08-08 reviewer 지적 F1 이 그 사각지대를 짚었다 — Phase 3/4 신설 API
    4종이 ``create_app`` 배선은 정확한데 이 스크립트가 저장소를 넘기지 않아, 띄울 수
    있는 서버에서는 전부 404 였다. 라이브러리를 API 로 만든 작업이 다시 "아무도 못
    쓰는 것"이 되는 자리라, 조립을 테스트 가능한 표면으로 만든다.
    """

    app: Any
    journals: tuple[Any, ...]

    def close(self) -> None:
        for journal in self.journals:
            journal.close()


def build_dev_app(
    data_dir: Path,
    *,
    segment_bytes: int | None,
    edge_sync_snapshot_every: int | None,
    s3_endpoint: str | None = None,
    s3_bucket: str | None = None,
) -> DevAssembly:
    """dev 조립 — 디렉터리는 호출자가 이미 만들어 뒀다고 가정한다.

    조립 도중 실패하면 **이미 연 원장을 전부 닫고** 예외를 올린다. 안 닫으면 같은
    프로세스에서 같은 data-dir 로 재시도할 때 flock 에 막혀, 진짜 실패 원인이
    "다른 프로세스가 journal 을 소유 중"으로 덮인다(reviewer 재검증 지적 N5 —
    ``DurableJournal.__init__`` 이 정확히 이 이유로 자기 fd 를 닫는 관습과 대칭).
    """
    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(data_dir / name, max_segment_bytes=segment_bytes)
        opened.append(journal)
        return journal

    try:
        return _build_dev_app_locked(
            data_dir,
            journal=_journal,
            opened=opened,
            edge_sync_snapshot_every=edge_sync_snapshot_every,
            s3_endpoint=s3_endpoint,
            s3_bucket=s3_bucket,
        )
    except BaseException:
        for journal in opened:
            journal.close()
        raise


def _build_dev_app_locked(
    data_dir: Path,
    *,
    journal: Any,
    opened: list[Any],
    edge_sync_snapshot_every: int | None,
    s3_endpoint: str | None,
    s3_bucket: str | None,
) -> DevAssembly:
    """실제 조립 — 열린 원장은 ``opened`` 에 누적돼 실패 시 호출자가 닫는다.

    store 조립 본문은 ``ksi_core.app_assembly.assemble_app`` 으로 옮겼다
    (dev·production 두 조립 지점의 공용부, 모듈 docstring 참조). 여기 남는 것은
    dev 만의 관심사(키 부트스트랩, CLI 의 --s3-* 조건부 evidence storage)뿐이다.
    """
    key_set = _bootstrap_key_set(data_dir / "signing")

    evidence_storage = None
    if s3_endpoint is not None and s3_bucket is not None:
        # 둘 다 있을 때만 만든다 — CLI 는 이미 "함께 주어야 한다"를 강제하지만,
        # 이 함수는 CLI 밖(테스트·다른 조립)에서도 불리므로 여기서 다시 본다.
        from ksi_core.evidence_s3 import S3EvidenceStorage

        evidence_storage = S3EvidenceStorage(bucket=s3_bucket, endpoint_url=s3_endpoint)

    app = assemble_app(
        data_dir,
        journal=journal,
        opened=opened,
        edge_sync_snapshot_every=edge_sync_snapshot_every,
        auth_registry=_auth_registry(),
        evidence_storage=evidence_storage,
        mission_signing_key=key_set.active_private_key,
        mission_signing_key_id=key_set.active_key_id,
    )

    # 열린 순서 그대로 닫는다 — 목록을 손으로 유지하면 새 원장을 추가하면서
    # 빠뜨리기 쉽고, 그 누락은 "재기동이 flock 으로 막힌다"로만 드러난다.
    return DevAssembly(app=app, journals=tuple(opened))


def main() -> None:
    # 사람이 터미널에서 읽는 스크립트라 JSON 이 아니라 한 줄 텍스트로 —
    # production.py 는 반대(json_format=True, 로그 수집기가 읽는다). 형식만
    # 다르고 correlation id 필터는 dev 도 그대로 받는다(같은 함수).
    configure_structured_logging(json_format=False)
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

    assembly = build_dev_app(
        data_dir,
        segment_bytes=cli_optional_positive(
            args.journal_segment_bytes, name="--journal-segment-bytes"
        ),
        edge_sync_snapshot_every=cli_optional_positive(
            args.edge_sync_snapshot_every, name="--edge-sync-snapshot-every"
        ),
        s3_endpoint=args.s3_endpoint,
        s3_bucket=args.s3_bucket,
    )

    print("=" * 72)
    print(f"KSI Core dev server — data: {data_dir.resolve()}")
    print("Dev bearer tokens (Authorization: Bearer <token>):")
    for role, token in _DEV_TOKENS.items():
        print(f"  {role.value:16s} {token}")
    print(f"  EDGE_DEVICE({_DEV_EDGE_DEVICE_ID}) {_DEV_EDGE_TOKEN}")
    print(f"  {'PROCESSING_WORKER':16s} {_DEV_WORKER_TOKEN}")
    print("=" * 72)

    try:
        uvicorn.run(assembly.app, host=args.host, port=args.port)
    finally:
        assembly.close()


if __name__ == "__main__":
    main()
