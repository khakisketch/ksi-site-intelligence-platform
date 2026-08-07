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
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.change_detection import ChangeDetectionStore
from ksi_core.coverage_reports import CoverageReportStore
from ksi_core.defect_candidates import DefectCandidateStore
from ksi_core.durable_journal import DurableJournal
from ksi_core.edge_sync import EdgeSyncStore
from ksi_core.equipment_states import EquipmentStateStore
from ksi_core.equipment_support import EquipmentSupportStore
from ksi_core.events import EventStore
from ksi_core.mission_records import MissionStore
from ksi_core.processing_jobs import ProcessingJobStore
from ksi_core.signing_keys import SigningKeySet, load_signing_keys
from ksi_core.sites import SiteStore
from ksi_core.source_media import SourceMediaStore
from ksi_core.volume_reports import VolumeChangeStore

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
    """실제 조립 — 열린 원장은 ``opened`` 에 누적돼 실패 시 호출자가 닫는다."""
    key_set = _bootstrap_key_set(data_dir / "signing")

    # 세그먼트 회전(S4) — 활성 파일이 이 크기를 넘으면 봉인 세그먼트로 넘긴다.
    # 회전 임계는 **조립 지점의 결정**이다(DurableJournal 기본값은 회전 없음) —
    # 한 파일이 무한히 커지면 재기동 재생이 선형으로 느려지고 백업 단위도 사라진다.
    # 여기 값은 dev 조립 기준이고, 운영 조립은 디스크·백업 주기에 맞춰 자기 값을 준다.
    # CLI 는 0 을 "회전 없음"으로 받는다(생성자는 None). 음수는 argparse 를 통과하지만
    # 생성자가 ValueError 로 거부한다 — 조용히 0 으로 뭉개지 않는다.
    site_journal = journal("sites.jsonl")
    mission_journal = journal("missions.jsonl")
    event_journal = journal("events.jsonl")
    # edge-sync 는 회전이 아니라 스냅샷으로 재기동 비용을 잡는다 — 이 원장의
    # 재기동 비용은 파일 크기가 아니라 항목당 payload 정규화+sha256 이기 때문이다.
    edge_sync_store = EdgeSyncStore(
        data_dir / "edge-sync.jsonl",
        snapshot_every=edge_sync_snapshot_every,
    )
    opened.append(edge_sync_store)

    evidence_storage = None
    if s3_endpoint is not None and s3_bucket is not None:
        # 둘 다 있을 때만 만든다 — CLI 는 이미 "함께 주어야 한다"를 강제하지만,
        # 이 함수는 CLI 밖(테스트·다른 조립)에서도 불리므로 여기서 다시 본다.
        from ksi_core.evidence_s3 import S3EvidenceStorage

        evidence_storage = S3EvidenceStorage(bucket=s3_bucket, endpoint_url=s3_endpoint)

    mission_store = MissionStore(mission_journal)
    # 커버리지 보고는 임무 발급 기록과 대조해서만 받는다(INV-010) — 발급된 적
    # 없는 임무의 관찰 결과는 "무슨 근거로 날았나"에 답할 수 없다.
    coverage_journal = journal("coverage-reports.jsonl")
    # 원본 사진 번들(3D 파이프라인 입구) — --s3-endpoint 없이는 store 는 구성돼도
    # 라우트가 장착되지 않는다(evidence 라우트와 같은 관습, create_app 참조).
    source_media_journal = journal("source-media.jsonl")
    source_media_store = SourceMediaStore(source_media_journal, mission_store=mission_store)
    site_store = SiteStore(site_journal)
    # 처리 작업(ADR-KSI-012) — 봉인된 번들에서 입력을, 현장에서 반출 허용 여부를
    # 읽는다(INV-050). source_media 와 달리 오브젝트 스토리지를 요구하지 않는다.
    processing_job_journal = journal("processing-jobs.jsonl")
    # evidence_storage 없이 이 저장소를 넘기면 create_app 이 조립 자체를 거부한다
    # (ADR-KSI-012/INV-050 — 워커가 원본 바이트를 받아갈 URL 이 없으면 SUCCEEDED
    # 게이트가 영구히 닫힌 조립이 된다). 예전 코드는 무조건 넘겨서 **--s3-endpoint
    # 없이는 dev 서버가 아예 뜨지 않았다**(2026-08-08 test_dev_assembly 신설 게이트가
    # 실측으로 잡음). 스토리지가 없으면 이 표면을 장착하지 않는 편이 정직하다 —
    # source_media 라우트가 같은 이유로 이미 그렇게 동작한다.
    processing_job_store = (
        ProcessingJobStore(
            processing_job_journal, source_media_store=source_media_store, site_store=site_store
        )
        if evidence_storage is not None
        else None
    )
    # Phase 3/4 + M1 표면 — 이 다섯을 여기서 조립하지 않으면 create_app 배선이 정확해도
    # **띄울 수 있는 서버에서는 404 다**(2026-08-08 reviewer 지적 F1: 신설 API 4종이
    # 어떤 실행 가능한 조립에도 장착돼 있지 않았다). 라이브러리를 API 로 만든 작업이
    # 다시 "아무도 못 쓰는 것"이 되는 자리라, 배선과 조립을 같은 커밋에서 닫는다.
    defect_candidate_journal = journal("defect-candidates.jsonl")
    change_detection_journal = journal("change-detection.jsonl")
    volume_change_journal = journal("volume-changes.jsonl")
    equipment_state_journal = journal("equipment-states.jsonl")
    equipment_support_journal = journal("equipment-support.jsonl")
    app = create_app(
        auth_registry=_auth_registry(),
        site_store=site_store,
        mission_store=mission_store,
        event_store=EventStore(event_journal),
        edge_sync_store=edge_sync_store,
        evidence_storage=evidence_storage,
        coverage_report_store=CoverageReportStore(
            coverage_journal, mission_store=mission_store
        ),
        source_media_store=source_media_store,
        processing_job_store=processing_job_store,
        defect_candidate_store=DefectCandidateStore(
            defect_candidate_journal,
            mission_store=mission_store,
            source_media_store=source_media_store,
        ),
        # 변화 탐지 결과는 point_cloud 산출물을 지목해야 해석된다 — 작업 원장이
        # 없는 조립에서는 그 대조가 불가능하므로 표면도 열지 않는다.
        change_detection_store=(
            ChangeDetectionStore(
                change_detection_journal,
                mission_store=mission_store,
                processing_job_store=processing_job_store,
            )
            if processing_job_store is not None
            else None
        ),
        # 체적 리포트도 같다 — 어느 두 DSM 을 비교했는지 대조할 작업 원장이
        # 없으면 "이만큼 깎였다"가 재현 불가능한 주장이 된다.
        volume_change_store=(
            VolumeChangeStore(
                volume_change_journal,
                mission_store=mission_store,
                processing_job_store=processing_job_store,
            )
            if processing_job_store is not None
            else None
        ),
        equipment_state_store=EquipmentStateStore(
            equipment_state_journal, site_store=site_store
        ),
        equipment_support_store=EquipmentSupportStore(equipment_support_journal),
        mission_signing_key=key_set.active_private_key,
        mission_signing_key_id=key_set.active_key_id,
    )

    # 열린 순서 그대로 닫는다 — 목록을 손으로 유지하면 새 원장을 추가하면서
    # 빠뜨리기 쉽고, 그 누락은 "재기동이 flock 으로 막힌다"로만 드러난다.
    return DevAssembly(app=app, journals=tuple(opened))


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
