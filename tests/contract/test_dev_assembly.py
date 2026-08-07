"""dev 조립 지점(scripts/run_core_dev.py)의 CLI→생성자 변환 계약.

이 스크립트는 저장소에 존재하는 **유일한 조립 지점**이다 — 라이브러리 테스트가
전부 green 이어도 여기 배선이 틀리면 실제로 뜨는 서버만 잘못 조립된다. 독립
재검토가 "이 파일을 도는 테스트가 0건"으로 지적한 자리다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
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
from ksi_core.sites import SiteStore
from ksi_core.source_media import SourceMediaStore

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dev_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "run_core_dev", _REPO_ROOT / "scripts" / "run_core_dev.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # exec_module 전에 sys.modules 에 넣는 것이 importlib 표준 절차다 — 넣지 않으면
    # 모듈 안의 @dataclass 가 어노테이션을 해석할 때 sys.modules[cls.__module__] 를
    # 찾다 None 을 받아 AttributeError 로 죽는다(실측, 2026-08-08).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, None), (1, 1), (500, 500), (64 * 1024 * 1024, 64 * 1024 * 1024)],
)
def test_zero_means_disabled_positive_passes_through(value: int, expected: int | None) -> None:
    """CLI 의 '0 = 없음' 규약이 생성자의 None 으로 정확히 옮겨진다."""
    module = _load_dev_module()
    assert module.cli_optional_positive(value, name="--x") is expected


def test_negative_is_rejected_with_the_cli_flag_name() -> None:
    """음수는 argparse 를 통과한다 — 생성자까지 흘리면 실패 메시지가 인자명을 잃는다."""
    module = _load_dev_module()
    with pytest.raises(ValueError, match="--journal-segment-bytes"):
        module.cli_optional_positive(-1, name="--journal-segment-bytes")


def test_defaults_are_within_constructor_contracts() -> None:
    """기본값이 생성자 규약(양수 또는 None)을 만족한다 — 기본 조립이 즉시 죽지 않게."""
    module = _load_dev_module()
    for default in (64 * 1024 * 1024, 500):
        converted = module.cli_optional_positive(default, name="--x")
        assert converted is not None and converted > 0


# ── 조립 표면 대조 (2026-08-08 reviewer 지적 F1) ────────────────────────────
#
# create_app 의 배선이 정확해도 이 스크립트가 저장소를 안 넘기면 **띄울 수 있는
# 서버에서는 404 다.** 실제로 Phase 3/4 신설 API 4종이 그 상태였다 — 라이브러리를
# API 로 만든 작업이 다시 "아무도 못 쓰는 것"이 되는 자리라, 이 대조를 게이트로 둔다.


class _NullEvidenceStorage:
    """포트 계약만 만족하는 조립용 스텁 — 이 게이트는 경로 존재만 본다."""

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        raise NotImplementedError

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        raise NotImplementedError

    def delete(self, object_key: str) -> None:
        raise NotImplementedError


def _max_assembly_paths(tmp_path: Path) -> set[str]:
    """모든 조건부 라우터를 장착한 앱의 /v1 경로 집합."""
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    source_media_store = SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"), mission_store=mission_store
    )
    processing_job_store = ProcessingJobStore(
        DurableJournal(tmp_path / "processing-jobs.jsonl"),
        source_media_store=source_media_store,
        site_store=site_store,
    )
    app = create_app(
        evidence_storage=_NullEvidenceStorage(),
        auth_registry=AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(b"x").hexdigest(),
                    principal=Principal(
                        principal_id="op-1",
                        kind=PrincipalKind.OPERATOR,
                        role=Role.ADMIN,
                        device_id=None,
                    ),
                )
            ]
        ),
        edge_sync_store=EdgeSyncStore(tmp_path / "edge-sync.jsonl"),
        event_store=EventStore(DurableJournal(tmp_path / "events.jsonl")),
        site_store=site_store,
        mission_store=mission_store,
        coverage_report_store=CoverageReportStore(
            DurableJournal(tmp_path / "coverage.jsonl"), mission_store=mission_store
        ),
        source_media_store=source_media_store,
        processing_job_store=processing_job_store,
        defect_candidate_store=DefectCandidateStore(
            DurableJournal(tmp_path / "defects.jsonl"),
            mission_store=mission_store,
            source_media_store=source_media_store,
        ),
        change_detection_store=ChangeDetectionStore(
            DurableJournal(tmp_path / "change-detection.jsonl"),
            mission_store=mission_store,
            processing_job_store=processing_job_store,
        ),
        equipment_state_store=EquipmentStateStore(
            DurableJournal(tmp_path / "equipment-states.jsonl"), site_store=site_store
        ),
        equipment_support_store=EquipmentSupportStore(
            DurableJournal(tmp_path / "equipment-support.jsonl")
        ),
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="dev-assembly-test-key",
    )
    return {p for p in app.openapi()["paths"] if p.startswith("/v1/")}


def test_dev_assembly_mounts_every_v1_surface(tmp_path: Path) -> None:
    """dev 서버가 최대 조립의 /v1 경로를 하나도 빠뜨리지 않는다.

    빠뜨리면 그 기능은 "구현됐지만 띄운 서버에서는 404" 다 — 계약 테스트가 전부
    green 이어도 아무도 못 쓴다.
    """
    module = _load_dev_module()
    dev = module.build_dev_app(
        tmp_path / "dev",
        segment_bytes=None,
        edge_sync_snapshot_every=None,
        s3_endpoint="http://127.0.0.1:9000",
        s3_bucket="dev-evidence",
    )
    try:
        dev_paths = {p for p in dev.app.openapi()["paths"] if p.startswith("/v1/")}
    finally:
        dev.close()
    missing = _max_assembly_paths(tmp_path / "max") - dev_paths
    assert not missing, (
        f"dev 조립(scripts/run_core_dev.py)이 장착하지 않는 /v1 경로: {sorted(missing)} "
        "— create_app 배선만으로는 서버에서 도달할 수 없다"
    )


def test_dev_assembly_closes_every_journal_it_opened(tmp_path: Path) -> None:
    """열어둔 원장을 전부 닫는다 — 하나라도 새면 재기동이 flock 으로 막힌다."""
    module = _load_dev_module()
    dev_dir = tmp_path / "dev"
    dev_dir.mkdir(parents=True)
    first = module.build_dev_app(
        dev_dir, segment_bytes=None, edge_sync_snapshot_every=None
    )
    first.close()
    # 같은 디렉터리로 두 번째 조립이 되면 단일 writer 잠금이 전부 풀린 것이다.
    second = module.build_dev_app(
        dev_dir, segment_bytes=None, edge_sync_snapshot_every=None
    )
    second.close()
