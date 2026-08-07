"""3D 재구성 처리 작업 발급·상태전이·산출물 계약 (B2/B3 — ADR-KSI-012, INV-050/051).

초점 일곱:

1. **입력은 봉인된 번들에서만 온다** — 요청에 자리가 없고, 봉인 전에는 발급되지
   않는다(장수·화소·digest 가 확정되지 않은 값 위에서 과금 근거를 만들지 않는다).
2. **INV-050 은 현장 값으로 판정한다** — 반출 미선언·미허용 현장의 vendor_cloud
   작업은 거부된다. 요청이 ``dataResidency`` 를 실어 보내도 거부된다.
3. **상태 전이표를 재생이 다시 태운다** — journal 을 손으로 고쳐 FAILED 를
   SUCCEEDED 로 되살릴 수 없다.
4. **임무당 활성 작업 1건** — 같은 사양 재요청은 멱등, 다른 사양은 409.
5. **SUCCEEDED 는 원본 산출물이 받쳐야 한다(INV-051)** — 파생물만으로도, 아무
   산출물 없이도 성공을 주장할 수 없다. 재생도 같은 게이트를 다시 태운다.
6. **산출물의 계보 앵커를 요청이 정하지 못한다** — ``sourceDigest`` 는 작업의
   봉인 digest 에서 Core 가 채우고, ``derivedFrom`` 은 실재하는 부모만 가리킨다.
7. **사람은 성공을 찍을 수 없다** — RUNNING/SUCCEEDED/FAILED 는 워커 권한이고
   CANCELLED 는 사람 권한이다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    Permission,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import EvidenceStorageError
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_core.processing_jobs import (
    _TRANSITION_PERMISSION,
    DEFAULT_LEASE_TTL,
    UNMETERED_AT_ISSUE,
    ArtifactSpec,
    IllegalJobTransitionError,
    JobSpec,
    ProcessingJobRecoveryError,
    ProcessingJobStore,
    ProcessingJobVerdict,
    UnbackedSuccessError,
    assert_job_transition,
    assert_succeeded_is_backed,
    build_job_id,
)
from ksi_core.sites import SiteStore
from ksi_core.source_media import (
    SourceBundleVerifyVerdict,
    SourceMediaClaim,
    SourceMediaMeasurement,
    SourceMediaStore,
)
from ksi_event_contracts.processing_artifact import (
    ArtifactAccuracy,
    LineageAuthority,
    ProcessingArtifactKind,
)
from ksi_event_contracts.processing_job import (
    DataResidency,
    ExecutionLocus,
    LicenseBasis,
    ProcessingJobStatus,
    ProcessingProvider,
)
from ksi_mission_contracts.models import SiteFrame

_MISSION_ID = "mission-pj-1"
_SITE_ID = "site-pj-001"
_NOW = datetime(2026, 8, 5, 4, 0, tzinfo=UTC)

_ADMIN_TOKEN = "processing-admin"  # noqa: S105 -- 테스트 고정값
_VIEWER_TOKEN = "processing-viewer"  # noqa: S105
_WORKER_TOKEN = "processing-worker"  # noqa: S105

_SITE_FRAME = SiteFrame(
    crs="EPSG:5186", vertical_datum="KNG2018", transform_version="v1", unit="meter"
)


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _claim(media_id: str, *, width: int = 4000, height: int = 3000) -> SourceMediaClaim:
    return SourceMediaClaim(
        media_id=media_id,
        sha256=_sha(media_id),
        size_bytes=1_000_000,
        width=width,
        height=height,
        content_type="image/jpeg",
    )


def _spec(
    *,
    locus: ExecutionLocus = ExecutionLocus.KSI_SERVER_GPU,
    provider: ProcessingProvider = ProcessingProvider.ODM,
    params: dict[str, Any] | None = None,
) -> JobSpec:
    return JobSpec(
        provider=provider,
        engine_version="3.5.4",
        engine_digest="sha256:" + "a" * 64,
        execution_locus=locus,
        license_basis=LicenseBasis(
            license_id="AGPL-3.0", tier="self-hosted", attribution_required=False
        ),
        processing_params=params if params is not None else {"quality": "high"},
    )


def _mission_store(tmp_path: Path, *, path: str = "missions.jsonl") -> MissionStore:
    store = MissionStore(DurableJournal(tmp_path / path))
    assert (
        store.record_issuance(
            MissionRecord(
                mission_id=_MISSION_ID,
                site_id=_SITE_ID,
                mission_type="BASELINE_MAPPING",
                artifact_kind="contract",
                contract={"schemaVersion": "1.2", "missionId": _MISSION_ID},
                kmz_sha256=None,
                route_pattern=None,
                waypoint_count=None,
                planned_coverage_ratio=None,
                issued_at=_NOW,
                issued_by="do-1",
            )
        ).value
        == "RECORDED"
    )
    return store


def _site_store(
    tmp_path: Path, *, egress: bool | None = None, path: str = "sites.jsonl"
) -> SiteStore:
    """``egress=None`` 은 반출 **미선언** 현장(구버전 레코드와 같은 상태)."""
    store = SiteStore(DurableJournal(tmp_path / path))
    residency = (
        None if egress is None else DataResidency(egress_allowed=egress, jurisdiction="KR")
    )
    result = store.register(
        _SITE_ID, "테스트 현장", _SITE_FRAME, data_residency=residency, actor="op-1", now=_NOW
    )
    assert result.verdict.value == "REGISTERED"
    return store


def _sealed_bundle_store(
    tmp_path: Path, *, media_count: int = 3, path: str = "source-media.jsonl", seal: bool = True
) -> SourceMediaStore:
    store = SourceMediaStore(
        DurableJournal(tmp_path / path), mission_store=_mission_store(tmp_path, path="m-" + path)
    )
    claims = [_claim(f"img-{i:03d}.jpg") for i in range(media_count)]
    assert store.register_batch(
        _MISSION_ID, claims, registered_by="op-1", now=_NOW
    ).verdict.value == "PROCESSED"
    if seal:
        assert store.seal(_MISSION_ID, sealed_by="op-1", now=_NOW).verdict.value == "SEALED"
    return store


def _job_store(
    tmp_path: Path,
    *,
    journal: DurableJournal | None = None,
    egress: bool | None = None,
    media_count: int = 3,
    seal: bool = True,
    verified: bool = True,
    path: str = "processing-jobs.jsonl",
) -> ProcessingJobStore:
    """``journal`` 을 직접 주면 재생 테스트가 그 핸들을 닫을 수 있다(단일 writer 잠금).

    ``verified`` 기본값이 True 인 이유: SUCCEEDED 게이트는 조건이 둘(원본 산출물
    + 입력 실측 대조)이라, 한쪽을 검사하는 테스트에서 다른 쪽이 같이 걸리면
    무엇이 막았는지 알 수 없다. 각 조건은 전용 테스트가 따로 고정한다.
    """
    make_bundles = _verified_bundles if (verified and seal) else _sealed_bundle_store
    return ProcessingJobStore(
        journal if journal is not None else DurableJournal(tmp_path / path),
        source_media_store=make_bundles(tmp_path, media_count=media_count, seal=seal),
        site_store=_site_store(tmp_path, egress=egress),
    )


def _artifact_spec(
    artifact_id: str = "pointcloud",
    *,
    kind: ProcessingArtifactKind = ProcessingArtifactKind.POINT_CLOUD,
    authority: LineageAuthority = LineageAuthority.SOURCE,
    derived_from: tuple[str, ...] = (),
    crs: str | None = "EPSG:5186",
    gsd: float | None = None,
    accuracy: ArtifactAccuracy | None = None,
) -> ArtifactSpec:
    return ArtifactSpec(
        artifact_id=artifact_id,
        kind=kind,
        authority=authority,
        derived_from=derived_from,
        digest="sha256:" + _sha(artifact_id),
        format="laz",
        crs=crs,
        gsd=gsd,
        accuracy=accuracy,
    )


def _lease(
    store: ProcessingJobStore,
    job_id: str,
    *,
    worker: str = "w-1",
    now: datetime = _NOW,
) -> None:
    """워커가 작업을 잡는다 — 모든 워커 행위의 전제(입력 수신·상태 보고·산출물 등록)."""
    assert store.acquire_lease(job_id, worker_id=worker, now=now).verdict in {
        ProcessingJobVerdict.LEASED,
        ProcessingJobVerdict.LEASE_RENEWED,
    }


def _running_job(store: ProcessingJobStore, tmp_path: Path) -> str:
    """발급 → lease → RUNNING 까지 진행한 작업의 jobId. 산출물 테스트의 공통 출발점."""
    del tmp_path
    record = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record
    assert record is not None
    _lease(store, record.job_id)
    assert (
        store.transition(
            record.job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW
        ).verdict
        is ProcessingJobVerdict.TRANSITIONED
    )
    return record.job_id


def _measurements_matching(bundles: SourceMediaStore) -> list[SourceMediaMeasurement]:
    """번들의 신고값과 **정확히 같은** 측정값 — 정직한 워커 시뮬레이션.

    실제 워커는 이 값을 바이트에서 계산하고 서버는 그걸 주지 않는다
    (``JobInputMediaView`` 에 신고값이 없다). 테스트는 그 계산 결과를 흉내낸다.
    """
    bundle = bundles.get(_MISSION_ID)
    assert bundle is not None
    return [
        SourceMediaMeasurement(
            media_id=m.media_id,
            sha256=m.sha256,
            size_bytes=m.size_bytes,
            width=m.width,
            height=m.height,
        )
        for m in bundle.media
    ]


def _verified_bundles(tmp_path: Path, **kwargs: Any) -> SourceMediaStore:
    """봉인 + 실측 대조까지 통과한 번들 저장소 — SUCCEEDED 게이트의 전제."""
    bundles = _sealed_bundle_store(tmp_path, **kwargs)
    assert (
        bundles.verify(
            _MISSION_ID,
            _measurements_matching(bundles),
            verified_by="worker-1",
            now=_NOW,
        ).verdict
        is SourceBundleVerifyVerdict.VERIFIED
    )
    return bundles


# ── 전이표 (순수 함수) ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (ProcessingJobStatus.QUEUED, ProcessingJobStatus.RUNNING),
        (ProcessingJobStatus.QUEUED, ProcessingJobStatus.CANCELLED),
        (ProcessingJobStatus.RUNNING, ProcessingJobStatus.SUCCEEDED),
        (ProcessingJobStatus.RUNNING, ProcessingJobStatus.FAILED),
        (ProcessingJobStatus.RUNNING, ProcessingJobStatus.CANCELLED),
    ],
)
def test_legal_transitions(before: ProcessingJobStatus, after: ProcessingJobStatus) -> None:
    assert_job_transition(before, after)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        # 종료 상태에서 나가는 전이는 전부 불법 — 끝난 작업의 결론을 고쳐 쓰지 않는다.
        (ProcessingJobStatus.SUCCEEDED, ProcessingJobStatus.RUNNING),
        (ProcessingJobStatus.FAILED, ProcessingJobStatus.SUCCEEDED),
        (ProcessingJobStatus.FAILED, ProcessingJobStatus.QUEUED),
        (ProcessingJobStatus.CANCELLED, ProcessingJobStatus.RUNNING),
        # QUEUED 를 건너뛰고 바로 성공을 주장할 수 없다.
        (ProcessingJobStatus.QUEUED, ProcessingJobStatus.SUCCEEDED),
        (ProcessingJobStatus.QUEUED, ProcessingJobStatus.FAILED),
        (ProcessingJobStatus.RUNNING, ProcessingJobStatus.QUEUED),
    ],
)
def test_illegal_transitions(before: ProcessingJobStatus, after: ProcessingJobStatus) -> None:
    with pytest.raises(IllegalJobTransitionError):
        assert_job_transition(before, after)


def test_job_id_is_deterministic_within_mission() -> None:
    assert build_job_id("mission-a", 1) == "mission-a-pj1"
    assert build_job_id("mission-a", 2) == "mission-a-pj2"


def test_transition_permission_table_covers_every_status() -> None:
    """권한표가 전 상태를 망라한다 — 빠진 값은 라우터에서 KeyError(500)가 된다.

    표를 total 로 두기로 한 결정(권한표는 '누가'만, 전이표가 '적법한가')은
    이 테스트가 없으면 새 상태가 늘어날 때 조용히 깨진다.
    """
    assert set(_TRANSITION_PERMISSION) == set(ProcessingJobStatus)


def test_only_cancellation_is_a_human_decision() -> None:
    """실행 사실 보고는 워커 권한, 취소만 사람 권한이다."""
    worker_targets = {
        s for s, p in _TRANSITION_PERMISSION.items() if p is Permission.PROCESSING_WORK
    }
    assert ProcessingJobStatus.CANCELLED not in worker_targets
    assert {
        ProcessingJobStatus.RUNNING,
        ProcessingJobStatus.SUCCEEDED,
        ProcessingJobStatus.FAILED,
    } <= worker_targets
    assert _TRANSITION_PERMISSION[ProcessingJobStatus.CANCELLED] is Permission.MISSIONS_ISSUE


# ── 입력은 봉인된 번들에서만 온다 ────────────────────────────────────────────


def test_input_is_aggregated_from_the_sealed_bundle(tmp_path: Path) -> None:
    """[핵심] 장수·화소·digest 를 Core 가 번들에서 집계한다 — 요청이 주지 않는다."""
    bundles = _sealed_bundle_store(tmp_path, media_count=4)
    store = ProcessingJobStore(
        DurableJournal(tmp_path / "pj.jsonl"),
        source_media_store=bundles,
        site_store=_site_store(tmp_path),
    )
    result = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW)
    assert result.verdict is ProcessingJobVerdict.ISSUED
    assert result.record is not None
    bundle = bundles.get(_MISSION_ID)
    assert bundle is not None
    assert result.record.input.image_count == 4
    # 4000×3000 = 12MP × 4장
    assert result.record.input.total_megapixels == pytest.approx(48.0)
    assert result.record.input.source_bundle_digest == bundle.source_bundle_digest


def test_unsealed_bundle_cannot_be_processed(tmp_path: Path) -> None:
    """[수용기준] 봉인 전에는 장수·digest 가 확정되지 않아 발급하지 않는다."""
    store = _job_store(tmp_path, seal=False)
    result = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW)
    assert result.verdict is ProcessingJobVerdict.BUNDLE_NOT_SEALED
    assert result.record is None


def test_mission_without_bundle_is_unknown(tmp_path: Path) -> None:
    store = _job_store(tmp_path)
    result = store.issue("mission-no-bundle", _spec(), issued_by="op-1", now=_NOW)
    assert result.verdict is ProcessingJobVerdict.UNKNOWN_MISSION


def test_issue_does_not_charge_credits(tmp_path: Path) -> None:
    """[핵심] 발급 시점 billing 은 '아직 재지 않았다'를 값으로 말한다.

    입력 화소가 업로더 신고값에서 유도된 상태에서 청구액을 굳히지 않는다.
    """
    store = _job_store(tmp_path)
    record = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record
    assert record is not None
    contract = record.to_contract()
    assert contract.billing.credits_charged == 0.0
    assert contract.billing.rate_basis == UNMETERED_AT_ISSUE


# ── INV-050 — 반출 게이트는 현장 값으로만 판정한다 ────────────────────────────


def test_vendor_cloud_refused_when_site_has_not_declared_egress(tmp_path: Path) -> None:
    """[핵심] 미선언은 미허용이다 — 구버전 현장 전체가 조용히 반출 가능해지지 않는다."""
    store = _job_store(tmp_path, egress=None)
    result = store.issue(
        _MISSION_ID, _spec(locus=ExecutionLocus.VENDOR_CLOUD), issued_by="op-1", now=_NOW
    )
    assert result.verdict is ProcessingJobVerdict.EGRESS_NOT_ALLOWED
    assert result.record is None


def test_vendor_cloud_refused_when_site_declared_egress_false(tmp_path: Path) -> None:
    store = _job_store(tmp_path, egress=False)
    result = store.issue(
        _MISSION_ID, _spec(locus=ExecutionLocus.VENDOR_CLOUD), issued_by="op-1", now=_NOW
    )
    assert result.verdict is ProcessingJobVerdict.EGRESS_NOT_ALLOWED


def test_vendor_cloud_allowed_when_site_declared_egress_true(tmp_path: Path) -> None:
    store = _job_store(tmp_path, egress=True)
    result = store.issue(
        _MISSION_ID,
        _spec(locus=ExecutionLocus.VENDOR_CLOUD, provider=ProcessingProvider.DJI_FLIGHTHUB),
        issued_by="op-1",
        now=_NOW,
    )
    assert result.verdict is ProcessingJobVerdict.ISSUED
    assert result.record is not None
    assert result.record.data_residency.egress_allowed is True


def test_onprem_execution_is_unaffected_by_egress_declaration(tmp_path: Path) -> None:
    """반출 미선언 현장에서도 온프렘 처리는 막히지 않는다 — 반출이 없으니까."""
    store = _job_store(tmp_path, egress=None)
    result = store.issue(
        _MISSION_ID, _spec(locus=ExecutionLocus.SITE_ONPREM), issued_by="op-1", now=_NOW
    )
    assert result.verdict is ProcessingJobVerdict.ISSUED


# ── 임무당 활성 작업 1건 ────────────────────────────────────────────────────


def test_same_spec_reissue_is_idempotent(tmp_path: Path) -> None:
    """네트워크 재시도가 작업을 복제하지 않는다."""
    store = _job_store(tmp_path)
    first = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW)
    second = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW + timedelta(seconds=5))
    assert first.verdict is ProcessingJobVerdict.ISSUED
    assert second.verdict is ProcessingJobVerdict.ALREADY_ISSUED
    assert second.record is not None
    assert first.record is not None
    assert second.record.job_id == first.record.job_id
    assert len(store.list_for_mission(_MISSION_ID)) == 1


def test_different_spec_while_active_is_refused(tmp_path: Path) -> None:
    """[핵심] 같은 번들을 두 작업이 동시에 처리하면 산출물 계보가 갈린다."""
    store = _job_store(tmp_path)
    store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW)
    conflict = store.issue(
        _MISSION_ID, _spec(params={"quality": "low"}), issued_by="op-1", now=_NOW
    )
    assert conflict.verdict is ProcessingJobVerdict.ACTIVE_JOB_EXISTS
    assert len(store.list_for_mission(_MISSION_ID)) == 1


def test_reprocessing_allowed_after_terminal(tmp_path: Path) -> None:
    """종료된 뒤에는 다른 엔진·파라미터로 다시 돌릴 수 있다(정상 운용)."""
    store = _job_store(tmp_path)
    first = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record
    assert first is not None
    _lease(store, first.job_id)
    store.transition(
        first.job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW
    )
    store.transition(
        first.job_id,
        ProcessingJobStatus.FAILED,
        detail="메모리 부족",
        actor="w-1",
        now=_NOW,
    )
    second = store.issue(
        _MISSION_ID, _spec(params={"quality": "low"}), issued_by="op-1", now=_NOW
    )
    assert second.verdict is ProcessingJobVerdict.ISSUED
    assert second.record is not None
    assert second.record.job_id != first.job_id
    assert len(store.list_for_mission(_MISSION_ID)) == 2


def test_fingerprint_distinguishes_nested_params(tmp_path: Path) -> None:
    """중첩 dict 파라미터도 지문이 구분한다 — 키 순서만 다르면 같은 지문이다."""
    a = _spec(params={"dsm": {"resolution": 5, "gapfill": True}})
    b = _spec(params={"dsm": {"gapfill": True, "resolution": 5}})
    c = _spec(params={"dsm": {"resolution": 10, "gapfill": True}})
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != c.fingerprint()


# ── 상태 전이 (저장소 경로) ─────────────────────────────────────────────────


def test_transition_records_terminal_detail(tmp_path: Path) -> None:
    store = _job_store(tmp_path)
    record = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record
    assert record is not None
    _lease(store, record.job_id)
    store.transition(
        record.job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW
    )
    # SUCCEEDED 는 원본 산출물이 있어야 통과한다(INV-051) — 아래 전용 테스트가
    # 없을 때의 거부를 확인한다. 여기서는 게이트를 만족시킨 뒤 detail 만 본다.
    # (lease 는 위에서 w-1 이 쥐었고 아래 등록·전이 actor 가 같다.)
    store.register_artifact(
        record.job_id, _artifact_spec(), registered_by="w-1", now=_NOW
    )
    # 3시간 뒤 보고 — 그 사이 lease(15분)가 여러 번 만료되므로 워커는 계속
    # 갱신하고 있었어야 한다. 여기서는 보고 직전 상태만 만들어 준다(갱신 주기의
    # 의미는 test_lease_renewal_vs_reacquisition 이 따로 고정한다).
    _lease(store, record.job_id, now=_NOW + timedelta(hours=2, minutes=55))
    done = store.transition(
        record.job_id,
        ProcessingJobStatus.SUCCEEDED,
        detail="포인트클라우드 1.2억 점",
        actor="w-1",
        now=_NOW + timedelta(hours=3),
    )
    assert done.verdict is ProcessingJobVerdict.TRANSITIONED
    assert done.record is not None
    assert done.record.status is ProcessingJobStatus.SUCCEEDED
    assert done.record.terminal_detail == "포인트클라우드 1.2억 점"
    assert done.record.updated_at == _NOW + timedelta(hours=3)


def test_illegal_transition_is_typed_not_raised(tmp_path: Path) -> None:
    store = _job_store(tmp_path)
    record = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record
    assert record is not None
    _lease(store, record.job_id)
    result = store.transition(
        record.job_id, ProcessingJobStatus.SUCCEEDED, detail=None, actor="w-1", now=_NOW
    )
    assert result.verdict is ProcessingJobVerdict.ILLEGAL_TRANSITION


def test_unknown_job_transition(tmp_path: Path) -> None:
    store = _job_store(tmp_path)
    result = store.transition(
        "no-such-job", ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW
    )
    assert result.verdict is ProcessingJobVerdict.UNKNOWN_JOB


# ── 재생 — live 와 같은 게이트를 다시 태운다 ─────────────────────────────────


def _rebuild(tmp_path: Path, *, egress: bool | None = None) -> ProcessingJobStore:
    """journal 파일은 그대로 두고 저장소만 다시 세운다(재기동 시뮬레이션)."""
    return ProcessingJobStore(
        DurableJournal(tmp_path / "processing-jobs.jsonl"),
        source_media_store=_verified_bundles(tmp_path, path="replay-source-media.jsonl"),
        site_store=_site_store(tmp_path, egress=egress, path="replay-sites.jsonl"),
    )


def test_replay_restores_status_and_sequence(tmp_path: Path) -> None:
    journal = DurableJournal(tmp_path / "processing-jobs.jsonl")
    store = _job_store(tmp_path, journal=journal)
    first = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record
    assert first is not None
    _lease(store, first.job_id)
    store.transition(
        first.job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW
    )
    store.transition(
        first.job_id, ProcessingJobStatus.FAILED, detail="OOM", actor="w-1", now=_NOW
    )
    journal.close()

    restored = _rebuild(tmp_path)
    replayed = restored.get(first.job_id)
    assert replayed is not None
    assert replayed.status is ProcessingJobStatus.FAILED
    assert replayed.terminal_detail == "OOM"
    # 순번이 이어진다 — 재기동 후 발급이 기존 jobId 를 덮어쓰지 않는다.
    nxt = restored.issue(_MISSION_ID, _spec(params={"q": 2}), issued_by="op-1", now=_NOW).record
    assert nxt is not None
    assert nxt.job_id == build_job_id(_MISSION_ID, 2)


def test_replay_refuses_forged_terminal_transition(tmp_path: Path) -> None:
    """[핵심] journal 을 손으로 고쳐 FAILED 를 SUCCEEDED 로 되살릴 수 없다."""
    journal = DurableJournal(tmp_path / "processing-jobs.jsonl")
    store = _job_store(tmp_path, journal=journal)
    record = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record
    assert record is not None
    _lease(store, record.job_id)
    store.transition(
        record.job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW
    )
    store.transition(
        record.job_id, ProcessingJobStatus.FAILED, detail="OOM", actor="w-1", now=_NOW
    )
    journal.close()

    path = tmp_path / "processing-jobs.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    forged = json.loads(lines[-1])
    forged["after"] = ProcessingJobStatus.SUCCEEDED.value
    lines.append(json.dumps({**forged, "before": ProcessingJobStatus.FAILED.value}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ProcessingJobRecoveryError, match="불법 전이"):
        _rebuild(tmp_path)


def test_replay_refuses_inv050_violating_record(tmp_path: Path) -> None:
    """[핵심] 반출 미허용 현장의 vendor_cloud 발급 레코드는 기동을 거부한다."""
    journal = DurableJournal(tmp_path / "processing-jobs.jsonl")
    store = _job_store(tmp_path, journal=journal, egress=True)
    issued = store.issue(
        _MISSION_ID, _spec(locus=ExecutionLocus.VENDOR_CLOUD), issued_by="op-1", now=_NOW
    )
    assert issued.verdict is ProcessingJobVerdict.ISSUED
    journal.close()

    path = tmp_path / "processing-jobs.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    forged = json.loads(lines[0])
    forged["dataResidency"] = {"egressAllowed": False, "jurisdiction": "KR"}
    path.write_text(json.dumps(forged) + "\n", encoding="utf-8")

    with pytest.raises(ProcessingJobRecoveryError, match="INV-050"):
        _rebuild(tmp_path, egress=True)


def test_replay_refuses_state_mismatch(tmp_path: Path) -> None:
    journal = DurableJournal(tmp_path / "processing-jobs.jsonl")
    store = _job_store(tmp_path, journal=journal)
    record = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record
    assert record is not None
    journal.close()
    path = tmp_path / "processing-jobs.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines.append(
        json.dumps(
            {
                "kind": "processing-job-transitioned",
                "ts": _NOW.isoformat(),
                "jobId": record.job_id,
                # projection 은 QUEUED 인데 RUNNING 에서 전이했다고 주장한다.
                "before": ProcessingJobStatus.RUNNING.value,
                "after": ProcessingJobStatus.SUCCEEDED.value,
                "detail": None,
                "actor": "forger",
            }
        )
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ProcessingJobRecoveryError, match="상태 불일치"):
        _rebuild(tmp_path)


# ── HTTP 표면 ───────────────────────────────────────────────────────────────


def _digest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── SUCCEEDED 는 원본 산출물이 받쳐야 한다 (INV-051) ────────────────────────


def test_succeeded_is_refused_without_any_artifact(tmp_path: Path) -> None:
    """[핵심] 산출물 0건으로는 성공을 주장할 수 없다 — 자기 완료 자기 선언 금지."""
    store = _job_store(tmp_path)
    job_id = _running_job(store, tmp_path)
    result = store.transition(
        job_id, ProcessingJobStatus.SUCCEEDED, detail=None, actor="w-1", now=_NOW
    )
    assert result.verdict is ProcessingJobVerdict.UNBACKED_SUCCESS
    # 거부됐으면 상태는 그대로 RUNNING 이어야 한다(부분 적용 금지).
    record = store.get(job_id)
    assert record is not None
    assert record.status is ProcessingJobStatus.RUNNING


def test_succeeded_is_refused_when_only_derived_artifacts_exist(tmp_path: Path) -> None:
    """[핵심] 파생물만으로는 성공이 아니다 — 원본에서 재생성 가능해야 한다(ADR-KSI-003).

    파생물은 부모가 필요하므로, 부모(원본)를 넣었다가 지울 수 없다. 그래서
    원본 없이 파생만 있는 상태를 만들려면 부모 자체가 파생이어야 하는데 그건
    첫 파생물의 derivedFrom 이 비어 계약에서 걸린다 — 즉 이 경로는 계약과
    저장소 게이트가 함께 막는다. 여기서는 저장소 쪽 거부를 고정한다.
    """
    store = _job_store(tmp_path)
    job_id = _running_job(store, tmp_path)
    # 부모 없는 파생 주장은 계약이 막는다(INV-051).
    orphan = store.register_artifact(
        job_id,
        _artifact_spec("ortho", kind=ProcessingArtifactKind.ORTHO,
                       authority=LineageAuthority.DERIVED, gsd=0.03),
        registered_by="w-1",
        now=_NOW,
    )
    assert orphan.verdict is ProcessingJobVerdict.ARTIFACT_CONTRACT_VIOLATION
    # 산출물이 하나도 등록되지 않았으므로 성공도 거부된다.
    assert (
        store.transition(
            job_id, ProcessingJobStatus.SUCCEEDED, detail=None, actor="w-1", now=_NOW
        ).verdict
        is ProcessingJobVerdict.UNBACKED_SUCCESS
    )


def test_succeeded_passes_with_a_source_artifact(tmp_path: Path) -> None:
    store = _job_store(tmp_path)
    job_id = _running_job(store, tmp_path)
    assert (
        store.register_artifact(
            job_id, _artifact_spec(), registered_by="w-1", now=_NOW
        ).verdict
        is ProcessingJobVerdict.ARTIFACT_REGISTERED
    )
    result = store.transition(
        job_id, ProcessingJobStatus.SUCCEEDED, detail=None, actor="w-1", now=_NOW
    )
    assert result.verdict is ProcessingJobVerdict.TRANSITIONED


def test_failed_and_cancelled_need_no_artifact(tmp_path: Path) -> None:
    """게이트는 SUCCEEDED 에만 걸린다 — 실패·취소는 산출물 없이 끝나는 게 정상이다."""
    for target in (ProcessingJobStatus.FAILED, ProcessingJobStatus.CANCELLED):
        store = _job_store(tmp_path / target.value)
        job_id = _running_job(store, tmp_path)
        assert (
            store.transition(job_id, target, detail="엔진 실패", actor="w-1", now=_NOW).verdict
            is ProcessingJobVerdict.TRANSITIONED
        )


def test_gate_function_is_pure_and_shared() -> None:
    """live·재생이 함께 쓰는 게이트 함수 자체의 계약 — 종료 상태별 적용 범위."""
    # SUCCEEDED 가 아닌 대상에는 어느 조건도 걸리지 않는다: 신고값이 거짓이라
    # 처리가 깨진 작업이 "검증 못 해서 끝낼 수 없는" 상태에 갇히면 안 된다.
    assert_succeeded_is_backed(ProcessingJobStatus.FAILED, [], input_verified=False)
    assert_succeeded_is_backed(ProcessingJobStatus.CANCELLED, [], input_verified=False)
    assert_succeeded_is_backed(ProcessingJobStatus.RUNNING, [], input_verified=False)
    with pytest.raises(UnbackedSuccessError, match="authority=source"):
        assert_succeeded_is_backed(
            ProcessingJobStatus.SUCCEEDED, [], input_verified=True
        )


def test_input_verification_gate_is_independent_of_artifacts(tmp_path: Path) -> None:
    """[핵심] 산출물이 있어도 입력을 안 읽었으면 성공이 아니다.

    두 조건이 AND 라는 것을 이 테스트가 고정한다 — 산출물 조건만 있고 입력
    조건이 빠지면 과금 근거(totalMegapixels)가 끝까지 업로더 신고값으로 남는다.
    """
    store = _job_store(tmp_path, verified=False)
    job_id = _running_job(store, tmp_path)
    assert (
        store.register_artifact(
            job_id, _artifact_spec(), registered_by="w-1", now=_NOW
        ).verdict
        is ProcessingJobVerdict.ARTIFACT_REGISTERED
    )
    result = store.transition(
        job_id, ProcessingJobStatus.SUCCEEDED, detail=None, actor="w-1", now=_NOW
    )
    assert result.verdict is ProcessingJobVerdict.UNBACKED_SUCCESS
    assert result.detail is not None
    assert "실측 대조" in result.detail


def test_failure_is_allowed_on_unverified_input(tmp_path: Path) -> None:
    """[수용기준] 신고값이 거짓이라 처리가 깨진 작업은 실패로 끝날 수 있어야 한다."""
    store = _job_store(tmp_path, verified=False)
    job_id = _running_job(store, tmp_path)
    assert (
        store.transition(
            job_id, ProcessingJobStatus.FAILED, detail="입력 손상", actor="w-1", now=_NOW
        ).verdict
        is ProcessingJobVerdict.TRANSITIONED
    )


# ── 산출물의 계보 앵커를 요청이 정하지 못한다 ────────────────────────────────


def test_lineage_anchor_comes_from_the_sealed_bundle(tmp_path: Path) -> None:
    """[핵심] sourceDigest 를 Core 가 작업의 봉인 digest 로 채운다."""
    store = _job_store(tmp_path)
    job_id = _running_job(store, tmp_path)
    result = store.register_artifact(
        job_id, _artifact_spec(), registered_by="w-1", now=_NOW
    )
    assert result.artifact is not None
    job = store.get(job_id)
    assert job is not None
    assert result.artifact.lineage.source_digest == job.input.source_bundle_digest
    assert result.artifact.job_id == job_id


def test_derived_from_must_reference_an_artifact_of_this_job(tmp_path: Path) -> None:
    """[핵심] 계약은 '비어 있지 않다'만 본다 — 부모의 실재는 저장소가 본다."""
    store = _job_store(tmp_path)
    job_id = _running_job(store, tmp_path)
    store.register_artifact(job_id, _artifact_spec(), registered_by="w-1", now=_NOW)
    result = store.register_artifact(
        job_id,
        _artifact_spec(
            "ortho",
            kind=ProcessingArtifactKind.ORTHO,
            authority=LineageAuthority.DERIVED,
            derived_from=("존재하지-않는-부모",),
            gsd=0.03,
        ),
        registered_by="w-1",
        now=_NOW,
    )
    assert result.verdict is ProcessingJobVerdict.UNKNOWN_PARENT_ARTIFACT


def test_derived_artifact_registers_when_parent_exists(tmp_path: Path) -> None:
    store = _job_store(tmp_path)
    job_id = _running_job(store, tmp_path)
    store.register_artifact(job_id, _artifact_spec("pointcloud"), registered_by="w-1", now=_NOW)
    result = store.register_artifact(
        job_id,
        _artifact_spec(
            "ortho",
            kind=ProcessingArtifactKind.ORTHO,
            authority=LineageAuthority.DERIVED,
            derived_from=("pointcloud",),
            gsd=0.03,
        ),
        registered_by="w-1",
        now=_NOW,
    )
    assert result.verdict is ProcessingJobVerdict.ARTIFACT_REGISTERED
    assert result.artifact is not None
    assert result.artifact.lineage.derived_from == ["pointcloud"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ProcessingJobStatus.QUEUED, ProcessingJobVerdict.JOB_NOT_RUNNING),
        (ProcessingJobStatus.CANCELLED, ProcessingJobVerdict.JOB_NOT_RUNNING),
    ],
)
def test_artifacts_only_attach_to_a_running_job(
    tmp_path: Path, status: ProcessingJobStatus, expected: ProcessingJobVerdict
) -> None:
    """시작 전에는 만들어질 수 없고, 끝난 뒤에는 근거를 소급하는 것이 된다."""
    store = _job_store(tmp_path / status.value)
    record = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record
    assert record is not None
    if status is not ProcessingJobStatus.QUEUED:
        store.transition(record.job_id, status, detail=None, actor="op-1", now=_NOW)
    result = store.register_artifact(
        record.job_id, _artifact_spec(), registered_by="w-1", now=_NOW
    )
    assert result.verdict is expected


def test_duplicate_artifact_id_is_refused(tmp_path: Path) -> None:
    store = _job_store(tmp_path)
    job_id = _running_job(store, tmp_path)
    store.register_artifact(job_id, _artifact_spec(), registered_by="w-1", now=_NOW)
    again = store.register_artifact(job_id, _artifact_spec(), registered_by="w-1", now=_NOW)
    assert again.verdict is ProcessingJobVerdict.DUPLICATE_ARTIFACT


def test_artifact_id_must_be_path_safe(tmp_path: Path) -> None:
    store = _job_store(tmp_path)
    job_id = _running_job(store, tmp_path)
    result = store.register_artifact(
        job_id, _artifact_spec("../escape"), registered_by="w-1", now=_NOW
    )
    assert result.verdict is ProcessingJobVerdict.INVALID_ARTIFACT_ID


def test_raster_artifact_without_gsd_is_a_contract_violation(tmp_path: Path) -> None:
    """kind 별 필수(crs/gsd)는 계약이 판정하고 저장소는 그 실패를 typed 로 옮긴다."""
    store = _job_store(tmp_path)
    job_id = _running_job(store, tmp_path)
    result = store.register_artifact(
        job_id,
        _artifact_spec("ortho", kind=ProcessingArtifactKind.ORTHO, gsd=None),
        registered_by="w-1",
        now=_NOW,
    )
    assert result.verdict is ProcessingJobVerdict.ARTIFACT_CONTRACT_VIOLATION


def test_accuracy_null_is_preserved_not_dropped(tmp_path: Path) -> None:
    """ODM 경로의 accuracy=null 은 '측정 안 함'이지 '필드 누락'이 아니다."""
    store = _job_store(tmp_path)
    job_id = _running_job(store, tmp_path)
    result = store.register_artifact(job_id, _artifact_spec(), registered_by="w-1", now=_NOW)
    assert result.artifact is not None
    assert result.artifact.accuracy is None
    with_accuracy = store.register_artifact(
        job_id,
        _artifact_spec(
            "report",
            kind=ProcessingArtifactKind.REPORT,
            crs=None,
            accuracy=ArtifactAccuracy(gcp_count=5, rmse=0.021, report_uri="s3://r/1.pdf"),
        ),
        registered_by="w-1",
        now=_NOW,
    )
    assert with_accuracy.artifact is not None
    assert with_accuracy.artifact.accuracy is not None
    assert with_accuracy.artifact.accuracy.gcp_count == 5


# ── 재생이 산출물 게이트를 다시 태운다 ───────────────────────────────────────
# (재기동 시뮬레이션은 위 ``_rebuild`` 를 그대로 쓴다)


def _journal_lines(tmp_path: Path, path: str = "processing-jobs.jsonl") -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (tmp_path / path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_journal(
    tmp_path: Path, records: list[dict[str, Any]], path: str = "processing-jobs.jsonl"
) -> None:
    (tmp_path / path).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def _seeded_success_journal(tmp_path: Path) -> DurableJournal:
    """발급 → RUNNING → 산출물 → SUCCEEDED 가 기록된 journal(핸들은 닫아서 반환)."""
    journal = DurableJournal(tmp_path / "processing-jobs.jsonl")
    store = _job_store(tmp_path, journal=journal)
    job_id = _running_job(store, tmp_path)
    assert (
        store.register_artifact(job_id, _artifact_spec(), registered_by="w-1", now=_NOW).verdict
        is ProcessingJobVerdict.ARTIFACT_REGISTERED
    )
    assert (
        store.transition(
            job_id, ProcessingJobStatus.SUCCEEDED, detail=None, actor="w-1", now=_NOW
        ).verdict
        is ProcessingJobVerdict.TRANSITIONED
    )
    journal.close()
    return journal


def test_replay_restores_artifacts_and_success(tmp_path: Path) -> None:
    """대조군 — 손대지 않은 원장은 그대로 복원된다(아래 거부들이 공허하지 않다)."""
    _seeded_success_journal(tmp_path)
    restored = _rebuild(tmp_path)
    record = restored.get(f"{_MISSION_ID}-pj1")
    assert record is not None
    assert record.status is ProcessingJobStatus.SUCCEEDED
    assert [a.artifact_id for a in record.artifacts] == ["pointcloud"]


def test_replay_refuses_success_whose_artifact_record_was_deleted(tmp_path: Path) -> None:
    """[핵심] 산출물 레코드를 지우고 SUCCEEDED 만 남기면 기동을 거부한다."""
    _seeded_success_journal(tmp_path)
    records = _journal_lines(tmp_path)
    _write_journal(tmp_path, [r for r in records if r["kind"] != "processing-artifact-registered"])
    with pytest.raises(ProcessingJobRecoveryError, match="근거 없는 SUCCEEDED"):
        _rebuild(tmp_path)


def test_replay_refuses_artifact_with_forged_lineage_anchor(tmp_path: Path) -> None:
    """[핵심] 다른 번들에서 나온 산출물을 이 작업의 계보에 이식할 수 없다."""
    _seeded_success_journal(tmp_path)
    records = _journal_lines(tmp_path)
    for record in records:
        if record["kind"] == "processing-artifact-registered":
            record["artifact"]["lineage"]["sourceDigest"] = "sha256:" + "b" * 64
    _write_journal(tmp_path, records)
    with pytest.raises(ProcessingJobRecoveryError, match="계보 앵커"):
        _rebuild(tmp_path)


def test_replay_refuses_artifact_on_a_non_running_job(tmp_path: Path) -> None:
    """산출물 레코드를 RUNNING 전이 **앞**으로 옮기면 기동을 거부한다."""
    _seeded_success_journal(tmp_path)
    records = _journal_lines(tmp_path)
    artifact = next(r for r in records if r["kind"] == "processing-artifact-registered")
    reordered = [r for r in records if r is not artifact]
    reordered.insert(1, artifact)  # 발급 직후(= QUEUED 상태)로 이동
    _write_journal(tmp_path, reordered)
    with pytest.raises(ProcessingJobRecoveryError, match="실행 중이 아닌"):
        _rebuild(tmp_path)


def test_replay_refuses_duplicate_artifact_id(tmp_path: Path) -> None:
    _seeded_success_journal(tmp_path)
    records = _journal_lines(tmp_path)
    artifact = next(r for r in records if r["kind"] == "processing-artifact-registered")
    index = records.index(artifact)
    records.insert(index + 1, json.loads(json.dumps(artifact)))
    _write_journal(tmp_path, records)
    with pytest.raises(ProcessingJobRecoveryError, match="DUPLICATE_ARTIFACT"):
        _rebuild(tmp_path)


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest_token(_ADMIN_TOKEN),
                principal=Principal(
                    principal_id="op-admin",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest_token(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="op-viewer",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest_token(_WORKER_TOKEN),
                principal=Principal(
                    principal_id="worker-odm-1",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    role=None,
                    device_id=None,
                ),
            ),
        ]
    )


class _FakeStorage:
    """포트 계약만 만족하는 가짜 스토리지(``test_source_media.FakeStorage`` 대칭)."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self.fail_get_with: Exception | None = None

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        del content_type, ttl
        return f"https://storage.invalid/{object_key}?upload=1"

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        del ttl
        if self.fail_get_with is not None:
            raise self.fail_get_with
        return f"https://storage.invalid/{object_key}?download=1"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        """포트가 요구하는 서버측 직접 쓰기 — 이 스텁은 메모리에만 담는다."""
        del content_type
        self._blobs[object_key] = data

    def get_bytes(self, object_key: str) -> bytes:
        """부재도 오류다(포트 계약) — 조용히 빈 바이트를 돌려주지 않는다."""
        blob = self._blobs.get(object_key)
        if blob is None:
            raise EvidenceStorageError(f"없다: {object_key}")
        return blob

    def delete(self, object_key: str) -> None:
        raise NotImplementedError


def _client(
    tmp_path: Path,
    *,
    egress: bool | None = None,
    verify_bundle: bool = False,
    storage: _FakeStorage | None = None,
) -> TestClient:
    """``verify_bundle=False`` 가 기본이다 — 실측 대조는 HTTP 경로로 하는 것이
    이 표면의 시험 대상이라, 픽스처가 미리 통과시켜 두면 그 게이트가 공허해진다."""
    mission_store = _mission_store(tmp_path, path="http-missions.jsonl")
    source_media_store = SourceMediaStore(
        DurableJournal(tmp_path / "http-source-media.jsonl"), mission_store=mission_store
    )
    assert source_media_store.register_batch(
        _MISSION_ID,
        [_claim(f"img-{i:03d}.jpg") for i in range(3)],
        registered_by="op-1",
        now=_NOW,
    ).verdict.value == "PROCESSED"
    assert (
        source_media_store.seal(_MISSION_ID, sealed_by="op-1", now=_NOW).verdict.value == "SEALED"
    )
    if verify_bundle:
        assert (
            source_media_store.verify(
                _MISSION_ID,
                _measurements_matching(source_media_store),
                verified_by="worker-1",
                now=_NOW,
            ).verdict
            is SourceBundleVerifyVerdict.VERIFIED
        )
    site_store = _site_store(tmp_path, egress=egress, path="http-sites.jsonl")
    app = create_app(
        auth_registry=_auth_registry(),
        mission_store=mission_store,
        site_store=site_store,
        evidence_storage=storage if storage is not None else _FakeStorage(),
        source_media_store=source_media_store,
        processing_job_store=ProcessingJobStore(
            DurableJournal(tmp_path / "http-processing-jobs.jsonl"),
            source_media_store=source_media_store,
            site_store=site_store,
        ),
        mission_signing_key=None,
    )
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})
    return client


def _issue_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": "odm",
        "engineVersion": "3.5.4",
        "engineDigest": "sha256:" + "a" * 64,
        "executionLocus": "ksi_server_gpu",
        "licenseBasis": {
            "licenseId": "AGPL-3.0",
            "tier": "self-hosted",
            "attributionRequired": False,
        },
        "processingParams": {"quality": "high"},
    }
    payload.update(overrides)
    return payload


def test_http_issue_returns_contract_payload(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/processing-jobs", json=_issue_payload()
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["verdict"] == "ISSUED"
    job = body["job"]
    assert job["status"] == "QUEUED"
    # 입력 화소가 업로더 신고값이라는 사실이 응답에 남는다("검증된 척"하지 않는다).
    assert job["inputVerified"] is False
    contract = job["contract"]
    assert contract["input"]["imageCount"] == 3
    assert contract["input"]["sourceBundleDigest"].startswith("sha256:")
    assert contract["billing"]["rateBasis"] == UNMETERED_AT_ISSUE


@pytest.mark.parametrize(
    "forged",
    [
        {"input": {"imageCount": 9999, "totalMegapixels": 1.0, "sourceBundleDigest": "x"}},
        {"dataResidency": {"egressAllowed": True, "jurisdiction": "US"}},
        {"billing": {"creditsChanged": 0, "rateBasis": "free", "meteredAt": _NOW.isoformat()}},
        {"status": "SUCCEEDED"},
        {"jobId": "attacker-chosen"},
    ],
)
def test_http_refuses_client_supplied_authority_fields(
    tmp_path: Path, forged: dict[str, Any]
) -> None:
    """[핵심] 요청이 입력·반출허가·과금·상태를 스스로 쓰지 못한다(extra=forbid)."""
    client = _client(tmp_path)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/processing-jobs", json=_issue_payload(**forged)
    )
    assert response.status_code == 422, response.text


def test_http_vendor_cloud_refused_for_undeclared_site(tmp_path: Path) -> None:
    client = _client(tmp_path, egress=None)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/processing-jobs",
        json=_issue_payload(executionLocus="vendor_cloud", provider="dji_flighthub"),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "EGRESS_NOT_ALLOWED"


def _as_worker(client: TestClient) -> TestClient:
    client.headers.update({"Authorization": f"Bearer {_WORKER_TOKEN}"})
    return client


def test_http_transition_and_get(tmp_path: Path) -> None:
    client = _client(tmp_path)
    job_id = client.post(
        f"/v1/missions/{_MISSION_ID}/processing-jobs", json=_issue_payload()
    ).json()["job"]["jobId"]

    _as_worker(client)
    assert client.post(f"/v1/processing-jobs/{job_id}/lease").status_code == 201
    running = client.post(
        f"/v1/processing-jobs/{job_id}/transitions", json={"targetStatus": "RUNNING"}
    )
    assert running.status_code == 200
    assert running.json()["job"]["status"] == "RUNNING"

    # 권한은 통과하고 전이표가 막는다 — 403 이 409 를 가리지 않는다.
    illegal = client.post(
        f"/v1/processing-jobs/{job_id}/transitions", json={"targetStatus": "QUEUED"}
    )
    assert illegal.status_code == 409
    assert illegal.json()["verdict"] == "ILLEGAL_TRANSITION"

    # 조회는 사람 권한이다 — 워커는 MISSIONS_READ 를 갖지 않는다(아래 전용 테스트).
    client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})
    detail = client.get(f"/v1/processing-jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "RUNNING"


def test_http_list_for_mission(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post(f"/v1/missions/{_MISSION_ID}/processing-jobs", json=_issue_payload())
    listed = client.get(f"/v1/missions/{_MISSION_ID}/processing-jobs")
    assert listed.status_code == 200
    assert len(listed.json()["jobs"]) == 1


def test_http_unknown_job_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/v1/processing-jobs/no-such-job").status_code == 404


def test_http_viewer_cannot_issue_or_transition(tmp_path: Path) -> None:
    """[음성 케이스] 읽기 권한만으로 처리 작업을 만들거나 상태를 바꿀 수 없다."""
    client = _client(tmp_path)
    job_id = client.post(
        f"/v1/missions/{_MISSION_ID}/processing-jobs", json=_issue_payload()
    ).json()["job"]["jobId"]

    client.headers.update({"Authorization": f"Bearer {_VIEWER_TOKEN}"})
    assert (
        client.post(
            f"/v1/missions/{_MISSION_ID}/processing-jobs", json=_issue_payload()
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/processing-jobs/{job_id}/transitions", json={"targetStatus": "RUNNING"}
        ).status_code
        == 403
    )
    # 조회는 열려 있다.
    assert client.get(f"/v1/processing-jobs/{job_id}").status_code == 200


def test_http_unauthenticated_is_refused(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.headers.pop("Authorization")
    assert client.get(f"/v1/missions/{_MISSION_ID}/processing-jobs").status_code == 401


# ── 조립 가드 ───────────────────────────────────────────────────────────────


def test_processing_jobs_require_source_media_and_site_stores(tmp_path: Path) -> None:
    """번들·현장 저장소 없이는 조립하지 않는다 — 요청이 그 값들을 주장하게 된다."""
    mission_store = _mission_store(tmp_path, path="guard-missions.jsonl")
    source_media_store = SourceMediaStore(
        DurableJournal(tmp_path / "guard-source-media.jsonl"), mission_store=mission_store
    )
    site_store = _site_store(tmp_path, path="guard-sites.jsonl")
    job_store = ProcessingJobStore(
        DurableJournal(tmp_path / "guard-jobs.jsonl"),
        source_media_store=source_media_store,
        site_store=site_store,
    )
    with pytest.raises(ValueError, match="processing_job_store"):
        create_app(
            auth_registry=_auth_registry(),
            mission_store=mission_store,
            source_media_store=source_media_store,
            processing_job_store=job_store,
            mission_signing_key=None,
        )
    with pytest.raises(ValueError, match="processing_job_store"):
        create_app(
            auth_registry=_auth_registry(),
            mission_store=mission_store,
            site_store=site_store,
            processing_job_store=job_store,
            mission_signing_key=None,
        )


def test_processing_jobs_route_absent_when_store_missing(tmp_path: Path) -> None:
    """저장소가 없으면 라우트 자체가 없다 — 404 가 '작업이 없다'로 오해되지 않게.

    ``app.routes`` 가 아니라 생성된 OpenAPI 를 본다 — ``include_router`` 로 붙은
    라우트는 이 FastAPI 버전에서 ``app.routes`` 에 ``.path`` 를 노출하지 않아,
    그쪽을 보는 단언은 장착 여부와 무관하게 통과한다(공허한 게이트).
    """
    mission_store = _mission_store(tmp_path, path="absent-missions.jsonl")
    app = create_app(
        auth_registry=_auth_registry(),
        mission_store=mission_store,
        mission_signing_key=None,
    )
    assert not [p for p in app.openapi()["paths"] if "processing-jobs" in p]


def test_processing_jobs_route_present_when_store_given(tmp_path: Path) -> None:
    """위 부재 단언이 공허하지 않다는 대조군 — 저장소가 있으면 세 라우트가 실재한다."""
    client = _client(tmp_path)
    paths = set(client.app.openapi()["paths"])  # type: ignore[attr-defined]
    assert {
        "/v1/missions/{mission_id}/processing-jobs",
        "/v1/processing-jobs/{job_id}",
        "/v1/processing-jobs/{job_id}/transitions",
        "/v1/processing-jobs/{job_id}/artifacts",
    } <= paths


# ── HTTP: 사람은 성공을 찍을 수 없다 ─────────────────────────────────────────


def _artifact_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifactId": "pointcloud",
        "kind": "point_cloud",
        "authority": "source",
        "derivedFrom": [],
        "digest": "sha256:" + _sha("pointcloud"),
        "format": "laz",
        "crs": "EPSG:5186",
        "gsd": None,
        "accuracy": None,
    }
    payload.update(overrides)
    return payload


def _issued_and_leased(client: TestClient) -> str:
    """관리자로 발급하고 워커가 잡는다 — 이후 클라이언트는 워커 신원이다."""
    job_id: str = client.post(
        f"/v1/missions/{_MISSION_ID}/processing-jobs", json=_issue_payload()
    ).json()["job"]["jobId"]
    _as_worker(client)
    leased = client.post(f"/v1/processing-jobs/{job_id}/lease")
    assert leased.status_code == 201, leased.text
    return job_id


def _issued_and_running(client: TestClient) -> str:
    """발급 → lease → RUNNING. 워커 행위 HTTP 테스트의 공통 출발점."""
    job_id = _issued_and_leased(client)
    assert (
        client.post(
            f"/v1/processing-jobs/{job_id}/transitions", json={"targetStatus": "RUNNING"}
        ).status_code
        == 200
    )
    return job_id


@pytest.mark.parametrize("target", ["RUNNING", "SUCCEEDED", "FAILED"])
def test_http_admin_cannot_report_execution_facts(tmp_path: Path, target: str) -> None:
    """[핵심 음성] 사람은 엔진 실행 사실을 보고할 수 없다 — 성공을 손으로 찍는 경로가 없다.

    ADMIN 은 이 제품에서 가장 넓은 사람 권한이다. 그 ADMIN 도 막힌다는 것이
    "어느 Role 에도 PROCESSING_WORK 를 매핑하지 않는다"의 실측이다.
    """
    client = _client(tmp_path)
    job_id = client.post(
        f"/v1/missions/{_MISSION_ID}/processing-jobs", json=_issue_payload()
    ).json()["job"]["jobId"]
    response = client.post(
        f"/v1/processing-jobs/{job_id}/transitions", json={"targetStatus": target}
    )
    assert response.status_code == 403, response.text


def test_http_worker_cannot_cancel(tmp_path: Path) -> None:
    """[음성] 취소는 사람의 결정이다 — 워커가 남의 작업을 접을 수 없다."""
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    response = client.post(
        f"/v1/processing-jobs/{job_id}/transitions", json={"targetStatus": "CANCELLED"}
    )
    assert response.status_code == 403


def test_http_admin_can_cancel(tmp_path: Path) -> None:
    """대조군 — 위 두 403 이 '전이가 전부 막혔다'가 아님을 보인다."""
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})
    response = client.post(
        f"/v1/processing-jobs/{job_id}/transitions", json={"targetStatus": "CANCELLED"}
    )
    assert response.status_code == 200
    assert response.json()["job"]["status"] == "CANCELLED"


def test_http_worker_registers_artifact_then_succeeds(tmp_path: Path) -> None:
    """[수용기준] 워커 경로 **종단** — 입력 수신 → 실측 보고 → 산출물 → 성공.

    HTTP 만으로 한 번은 통과시킨다(픽스처가 종단 상태를 주입하지 않는다).
    """
    client = _client(tmp_path, verify_bundle=False)
    job_id = _issued_and_running(client)

    # ① 워커가 입력을 받아간다 — 응답에 신고값이 없다.
    fetched = client.get(f"/v1/processing-jobs/{job_id}/input")
    assert fetched.status_code == 200, fetched.text
    job_input = fetched.json()["input"]
    assert job_input["imageCount"] == 3
    assert len(job_input["media"]) == 3
    for item in job_input["media"]:
        assert set(item) == {"mediaId", "objectKey", "downloadUrl", "expiresAt"}

    # ② 아직 실측 보고 전 — 산출물이 있어도 성공하지 못한다.
    early_artifact = client.post(
        f"/v1/processing-jobs/{job_id}/artifacts", json=_artifact_payload()
    )
    assert early_artifact.status_code == 201, early_artifact.text
    unverified = client.post(
        f"/v1/processing-jobs/{job_id}/transitions", json={"targetStatus": "SUCCEEDED"}
    )
    assert unverified.status_code == 409
    assert unverified.json()["verdict"] == "UNBACKED_SUCCESS"
    assert "실측 대조" in unverified.json()["detail"]

    # ③ 워커가 바이트에서 잰 값을 보고하고 Core 가 대조한다.
    verified = client.post(
        f"/v1/missions/{_MISSION_ID}/source-media/verify",
        json={
            "measurements": [
                {
                    "mediaId": f"img-{i:03d}.jpg",
                    "sha256": _sha(f"img-{i:03d}.jpg"),
                    "bytes": 1_000_000,
                    "width": 4000,
                    "height": 3000,
                }
                for i in range(3)
            ]
        },
    )
    assert verified.status_code == 201, verified.text
    assert verified.json()["verdict"] == "VERIFIED"
    assert verified.json()["bundle"]["verifiedAt"] is not None

    registered = client.post(
        f"/v1/processing-jobs/{job_id}/artifacts", json=_artifact_payload(artifactId="mesh-1")
    )
    assert registered.status_code == 201, registered.text
    artifact = registered.json()["artifact"]
    # nullable 필수 필드는 생략되지 않고 명시적 null 로 실린다.
    assert artifact["accuracy"] is None
    assert artifact["gsd"] is None
    assert artifact["crs"] == "EPSG:5186"

    done = client.post(
        f"/v1/processing-jobs/{job_id}/transitions", json={"targetStatus": "SUCCEEDED"}
    )
    assert done.status_code == 200
    assert done.json()["job"]["status"] == "SUCCEEDED"

    client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})
    view = client.get(f"/v1/processing-jobs/{job_id}").json()
    assert [a["artifactId"] for a in view["artifacts"]] == ["pointcloud", "mesh-1"]
    # 실측 대조를 통과했으므로 이제 참이다 — 하드코딩된 false 가 아니다.
    assert view["inputVerified"] is True


@pytest.mark.parametrize(
    "forged",
    [
        {"sourceDigest": "sha256:" + "b" * 64},
        {
            "lineage": {
                "authority": "source",
                "derivedFrom": [],
                "sourceDigest": "sha256:" + "c" * 64,
            }
        },
        {"jobId": "다른-작업"},
    ],
)
def test_http_artifact_request_cannot_forge_lineage_anchor(
    tmp_path: Path, forged: dict[str, Any]
) -> None:
    """[핵심] 계보 앵커·소속 작업을 요청이 실어 보낼 자리가 없다(extra=forbid)."""
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    response = client.post(
        f"/v1/processing-jobs/{job_id}/artifacts", json=_artifact_payload(**forged)
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("token", [_ADMIN_TOKEN, _VIEWER_TOKEN])
def test_http_humans_cannot_register_artifacts(tmp_path: Path, token: str) -> None:
    """[음성] 산출물 등록도 워커 전용이다 — 사람이 근거를 만들어 넣지 못한다."""
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    client.headers.update({"Authorization": f"Bearer {token}"})
    response = client.post(
        f"/v1/processing-jobs/{job_id}/artifacts", json=_artifact_payload()
    )
    assert response.status_code == 403


def test_http_worker_cannot_read_jobs(tmp_path: Path) -> None:
    """워커 권한은 보고 전용이다 — 조회 권한(MISSIONS_READ)을 포함하지 않는다.

    이건 의도된 좁힘이자 **미완의 표시**다: 워커가 큐에서 작업을 꺼내오는
    경로를 만들 때 이 테스트가 함께 바뀐다(processing_jobs 모듈 docstring).
    """
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    assert client.get(f"/v1/processing-jobs/{job_id}").status_code == 403


# ── 워커 입력 수신 — 신고값을 주지 않는다 ────────────────────────────────────


def test_http_input_response_never_carries_the_uploader_claims(tmp_path: Path) -> None:
    """[핵심] 워커가 정답을 모르므로 읽지 않고는 VERIFIED 를 받을 수 없다.

    응답 어디에도 sha256·해상도·바이트 수가 없다. 이 단언이 깨지면 실측
    대조는 '되읊기'로 통과 가능해지고 verifiedAt 이 뜻을 잃는다.
    """
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    body = client.get(f"/v1/processing-jobs/{job_id}/input").json()
    serialized = json.dumps(body, ensure_ascii=False)

    # ① 신고된 sha256 원문이 응답 어디에도 없다. (sourceBundleDigest 는 매니페스트
    #    전체의 해시라 개별 파일 해시를 역산할 수 없다 — 그래서 실려도 무해하다.)
    for i in range(3):
        assert _sha(f"img-{i:03d}.jpg") not in serialized, "개별 파일 신고 sha256 이 샌다"
    # ② 신고 해상도·바이트 수도 없다 — 워커가 되읊을 수 있는 값이면 안 된다.
    for leaked in ("4000", "3000", "1000000"):
        assert leaked not in serialized, f"신고값 {leaked} 이 샌다"
    # ③ 항목의 키 집합 자체를 고정한다(위 값 검사가 우연히 통과하는 것을 막는다).
    for item in body["input"]["media"]:
        assert set(item) == {"mediaId", "objectKey", "downloadUrl", "expiresAt"}


def test_http_input_carries_the_site_crs_not_worker_supplied(tmp_path: Path) -> None:
    """[핵심] 산출물의 crs 는 현장 등록값에서 온다 — 워커·발급자가 자기 신고하지 않는다.

    processing_params 로 crs 를 실을 자리를 만들면 "요청이 자기 증명서를 쓴다"
    클래스가 재발한다 — 이 값은 Core 가 site_store 에서 읽어 준다.
    """
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    body = client.get(f"/v1/processing-jobs/{job_id}/input").json()
    assert body["input"]["siteCrs"] == "EPSG:5186"


def test_http_input_is_worker_only(tmp_path: Path) -> None:
    """[음성] 사람 권한으로는 원본 다운로드 URL 을 받을 수 없다."""
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    for token in (_ADMIN_TOKEN, _VIEWER_TOKEN):
        client.headers.update({"Authorization": f"Bearer {token}"})
        assert client.get(f"/v1/processing-jobs/{job_id}/input").status_code == 403


def test_http_input_is_refused_once_the_job_is_over(tmp_path: Path) -> None:
    """작업 종료가 접근 종료를 뜻해야 한다 — 끝난 작업의 원본은 다시 내주지 않는다."""
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    assert (
        client.post(
            f"/v1/processing-jobs/{job_id}/transitions",
            json={"targetStatus": "FAILED", "detail": "엔진 실패"},
        ).status_code
        == 200
    )
    refused = client.get(f"/v1/processing-jobs/{job_id}/input")
    assert refused.status_code == 409
    assert refused.json()["verdict"] == "JOB_NOT_ACTIVE"


def test_http_input_is_available_before_running(tmp_path: Path) -> None:
    """QUEUED 에서도 받을 수 있어야 한다 — 입력을 봐야 RUNNING 으로 갈지 정한다."""
    client = _client(tmp_path)
    job_id = _issued_and_leased(client)
    fetched = client.get(f"/v1/processing-jobs/{job_id}/input")
    assert fetched.status_code == 200
    assert fetched.json()["input"]["status"] == "QUEUED"


def test_http_input_degrades_wholesale_when_presign_fails(tmp_path: Path) -> None:
    """부분 응답 대신 503 — 부분집합만 받은 워커는 반드시 COVERAGE_INCOMPLETE 로 돈다."""
    storage = _FakeStorage()
    client = _client(tmp_path, storage=storage)
    job_id = _issued_and_running(client)
    storage.fail_get_with = EvidenceStorageError("스토리지 접근 실패")
    response = client.get(f"/v1/processing-jobs/{job_id}/input")
    assert response.status_code == 503
    assert response.json()["verdict"] == "STORAGE_UNAVAILABLE"
    assert response.json()["input"] is None
    assert response.headers["Retry-After"] == "30"


def test_processing_jobs_assembly_requires_evidence_storage(tmp_path: Path) -> None:
    """조립 가드 — 스토리지 없이 조립하면 워커가 바이트를 못 읽어 SUCCEEDED 가 영구히 닫힌다."""
    mission_store = _mission_store(tmp_path, path="guard-missions.jsonl")
    source_media_store = SourceMediaStore(
        DurableJournal(tmp_path / "guard-source-media.jsonl"), mission_store=mission_store
    )
    site_store = _site_store(tmp_path, path="guard-sites.jsonl")
    with pytest.raises(ValueError, match="evidence_storage"):
        create_app(
            auth_registry=_auth_registry(),
            mission_store=mission_store,
            site_store=site_store,
            source_media_store=source_media_store,
            processing_job_store=ProcessingJobStore(
                DurableJournal(tmp_path / "guard-processing-jobs.jsonl"),
                source_media_store=source_media_store,
                site_store=site_store,
            ),
            mission_signing_key=None,
        )


# ── 워커 lease — 작업 하나는 워커 하나가 쥔다 ────────────────────────────────


def _issued_job(store: ProcessingJobStore) -> str:
    record = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record
    assert record is not None
    return record.job_id


def test_second_worker_cannot_take_a_held_job(tmp_path: Path) -> None:
    """[핵심] 두 워커가 같은 작업을 동시에 돌리지 않는다."""
    store = _job_store(tmp_path)
    job_id = _issued_job(store)
    assert (
        store.acquire_lease(job_id, worker_id="w-1", now=_NOW).verdict
        is ProcessingJobVerdict.LEASED
    )
    stolen = store.acquire_lease(job_id, worker_id="w-2", now=_NOW + timedelta(minutes=1))
    assert stolen.verdict is ProcessingJobVerdict.LEASE_HELD_BY_ANOTHER
    assert stolen.detail is not None
    assert "w-1" in stolen.detail


def test_expired_lease_is_reclaimable_without_any_release_command(tmp_path: Path) -> None:
    """[핵심] 죽은 워커의 작업을 회수하는 경로가 만료 하나뿐이다.

    ``release`` 같은 명시적 반납에만 의존하면, 죽은 워커는 정의상 반납하지
    않으므로 그 작업이 영구히 묶인다.
    """
    store = _job_store(tmp_path)
    job_id = _issued_job(store)
    store.acquire_lease(job_id, worker_id="w-1", now=_NOW)
    later = _NOW + DEFAULT_LEASE_TTL + timedelta(seconds=1)
    taken = store.acquire_lease(job_id, worker_id="w-2", now=later)
    assert taken.verdict is ProcessingJobVerdict.LEASED


def test_lease_renewal_vs_reacquisition(tmp_path: Path) -> None:
    """만료 전 재호출은 갱신(heartbeat), 만료 후 재호출은 새로 잡는 것이다."""
    store = _job_store(tmp_path)
    job_id = _issued_job(store)
    store.acquire_lease(job_id, worker_id="w-1", now=_NOW)

    renewed = store.acquire_lease(job_id, worker_id="w-1", now=_NOW + timedelta(minutes=5))
    assert renewed.verdict is ProcessingJobVerdict.LEASE_RENEWED
    assert renewed.record is not None
    assert renewed.record.lease is not None
    # 갱신은 만료를 밀되 최초 취득 시각은 유지한다 — 얼마나 오래 쥐고 있었는지가
    # 남아야 "이 워커가 계속 못 끝내고 있다"를 볼 수 있다.
    assert renewed.record.lease.granted_at == _NOW
    assert renewed.record.lease.expires_at == _NOW + timedelta(minutes=5) + DEFAULT_LEASE_TTL

    after_expiry = _NOW + timedelta(minutes=5) + DEFAULT_LEASE_TTL + timedelta(seconds=1)
    fresh = store.acquire_lease(job_id, worker_id="w-1", now=after_expiry)
    assert fresh.verdict is ProcessingJobVerdict.LEASED
    assert fresh.record is not None
    assert fresh.record.lease is not None
    assert fresh.record.lease.granted_at == after_expiry


@pytest.mark.parametrize(
    "action",
    ["input", "transition", "artifact"],
)
def test_every_worker_action_requires_the_lease(tmp_path: Path, action: str) -> None:
    """[핵심] 세 경로가 전부 같은 관문(_check_lease_locked)을 지난다."""
    store = _job_store(tmp_path)
    job_id = _issued_job(store)
    store.acquire_lease(job_id, worker_id="w-1", now=_NOW)

    if action == "input":
        verdict = store.input_for(job_id, worker_id="w-2", now=_NOW).verdict
    elif action == "transition":
        verdict = store.transition(
            job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-2", now=_NOW
        ).verdict
    else:
        store.transition(
            job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW
        )
        verdict = store.register_artifact(
            job_id, _artifact_spec(), registered_by="w-2", now=_NOW
        ).verdict
    assert verdict is ProcessingJobVerdict.LEASE_HELD_BY_ANOTHER


def test_worker_action_without_any_lease_is_refused(tmp_path: Path) -> None:
    store = _job_store(tmp_path)
    job_id = _issued_job(store)
    result = store.transition(
        job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW
    )
    assert result.verdict is ProcessingJobVerdict.LEASE_REQUIRED


def test_expired_lease_holder_can_no_longer_report(tmp_path: Path) -> None:
    """[핵심] 되살아난 좀비 워커가 뒤늦게 성공을 보고하지 못한다.

    만료된 lease 를 쥔 워커는 다른 워커가 이미 그 작업을 잡았을 수 있다 — 그
    상태에서 종료 보고를 받으면 두 워커의 결과가 섞인다.
    """
    store = _job_store(tmp_path)
    job_id = _issued_job(store)
    store.acquire_lease(job_id, worker_id="w-1", now=_NOW)
    store.transition(
        job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW
    )
    late = _NOW + DEFAULT_LEASE_TTL + timedelta(minutes=1)
    result = store.transition(
        job_id, ProcessingJobStatus.FAILED, detail="뒤늦은 보고", actor="w-1", now=late
    )
    assert result.verdict is ProcessingJobVerdict.LEASE_REQUIRED


def test_terminal_job_cannot_be_leased(tmp_path: Path) -> None:
    store = _job_store(tmp_path)
    job_id = _issued_job(store)
    store.acquire_lease(job_id, worker_id="w-1", now=_NOW)
    store.transition(
        job_id, ProcessingJobStatus.CANCELLED, detail=None, actor="op-1", now=_NOW,
        requires_lease=False,
    )
    assert (
        store.acquire_lease(job_id, worker_id="w-2", now=_NOW).verdict
        is ProcessingJobVerdict.JOB_NOT_ACTIVE
    )


def test_human_can_cancel_a_job_held_by_a_live_worker(tmp_path: Path) -> None:
    """[핵심] 취소만 lease 를 요구하지 않는다.

    워커가 죽어 lease 가 아직 살아 있는 동안 사람이 작업을 접지 못하면, 정확히
    취소가 필요한 상황에서 취소가 막힌다.
    """
    store = _job_store(tmp_path)
    job_id = _issued_job(store)
    store.acquire_lease(job_id, worker_id="w-1", now=_NOW)
    result = store.transition(
        job_id, ProcessingJobStatus.CANCELLED, detail="현장 요청", actor="op-admin",
        now=_NOW + timedelta(minutes=1), requires_lease=False,
    )
    assert result.verdict is ProcessingJobVerdict.TRANSITIONED


def test_replay_restores_the_lease(tmp_path: Path) -> None:
    journal = DurableJournal(tmp_path / "processing-jobs.jsonl")
    store = _job_store(tmp_path, journal=journal)
    job_id = _issued_job(store)
    store.acquire_lease(job_id, worker_id="w-1", now=_NOW)
    journal.close()

    restored = _rebuild(tmp_path)
    record = restored.get(job_id)
    assert record is not None
    assert record.lease is not None
    assert record.lease.worker_id == "w-1"
    # 재생 시점의 now 로 판정하므로 오래된 lease 는 자동으로 만료돼 있다 —
    # 재생이 별도 만료 처리를 하지 않아도 되는 것이 JobLease 설계의 요점이다.
    assert not record.lease.is_active(_NOW + DEFAULT_LEASE_TTL + timedelta(seconds=1))
    assert record.lease.is_active(_NOW + timedelta(minutes=1))


def test_replay_refuses_a_lease_on_a_terminal_job(tmp_path: Path) -> None:
    """live 는 종료된 작업에 lease 를 발급하지 않는다 — 있으면 원장 조작이다."""
    journal = DurableJournal(tmp_path / "processing-jobs.jsonl")
    store = _job_store(tmp_path, journal=journal)
    job_id = _issued_job(store)
    store.acquire_lease(job_id, worker_id="w-1", now=_NOW)
    store.transition(
        job_id, ProcessingJobStatus.CANCELLED, detail=None, actor="op-1", now=_NOW,
        requires_lease=False,
    )
    journal.close()

    records = _journal_lines(tmp_path)
    lease_record = next(r for r in records if r["kind"] == "processing-job-leased")
    records.append(json.loads(json.dumps(lease_record)))
    _write_journal(tmp_path, records)
    with pytest.raises(ProcessingJobRecoveryError, match="종료된 작업"):
        _rebuild(tmp_path)


def test_http_lease_then_renew(tmp_path: Path) -> None:
    client = _client(tmp_path)
    job_id = _issued_and_leased(client)
    renewed = client.post(f"/v1/processing-jobs/{job_id}/lease")
    assert renewed.status_code == 200
    assert renewed.json()["verdict"] == "LEASE_RENEWED"
    assert renewed.json()["job"]["leaseWorkerId"] == "worker-odm-1"
    # 만료 여부를 불리언으로 싣지 않는다 — 읽는 쪽이 자기 시계로 판정한다.
    assert renewed.json()["job"]["leaseExpiresAt"] is not None


def test_http_worker_without_lease_gets_409_not_403(tmp_path: Path) -> None:
    """권한은 있고 지금 쥔 사람이 아닐 뿐이다 — 403 은 자격증명을 의심하게 만든다."""
    client = _client(tmp_path)
    job_id = client.post(
        f"/v1/missions/{_MISSION_ID}/processing-jobs", json=_issue_payload()
    ).json()["job"]["jobId"]
    _as_worker(client)
    response = client.get(f"/v1/processing-jobs/{job_id}/input")
    assert response.status_code == 409
    assert response.json()["verdict"] == "LEASE_REQUIRED"


def test_http_humans_cannot_lease(tmp_path: Path) -> None:
    """[음성] lease 는 워커 전용이다 — 사람이 작업을 잡아 워커를 굶기지 못한다."""
    client = _client(tmp_path)
    job_id = client.post(
        f"/v1/missions/{_MISSION_ID}/processing-jobs", json=_issue_payload()
    ).json()["job"]["jobId"]
    for token in (_ADMIN_TOKEN, _VIEWER_TOKEN):
        client.headers.update({"Authorization": f"Bearer {token}"})
        assert client.post(f"/v1/processing-jobs/{job_id}/lease").status_code == 403


# ── 산출물 바이트 영속 (M1) ─────────────────────────────────────────────────
#
# 여기까지 이 파일이 검증한 것은 "산출물의 **계보**가 정직한가"였다. 아래는
# 그 계보가 가리키는 **바이트가 실제로 남는가**를 본다 — 재구성이 성공해도
# digest 만 남고 파일이 버려지면 사람이 볼 수 있는 것이 아무것도 없다.


def test_http_upload_url_is_issued_to_the_leaseholder(tmp_path: Path) -> None:
    """워커가 산출물을 올릴 자리를 받는다 — 키는 서버가 정한다."""
    client = _client(tmp_path)
    job_id = _issued_and_running(client)

    response = client.post(
        f"/v1/processing-jobs/{job_id}/artifacts/upload-url",
        json={"artifactId": "point-cloud", "contentType": "application/octet-stream"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["verdict"] == "UPLOAD_READY"
    assert body["objectKey"] == (
        f"sites/{_SITE_ID}/processing-jobs/{job_id}/artifacts/point-cloud"
    )
    assert body["uploadUrl"].startswith("https://storage.invalid/")


def test_http_upload_url_is_deterministic_for_the_same_artifact(tmp_path: Path) -> None:
    """같은 (작업, 산출물)이면 같은 키다.

    키를 레코드에 저장하지 않고 식별자에서 유도하는 설계라(``build_mission_kmz_
    object_key`` 관습), 이 결정성이 곧 "나중에 다시 찾을 수 있다"의 근거다.
    재시도가 두 번째 사본을 만들면 원본이 무엇인지 알 수 없게 된다.
    """
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    payload = {"artifactId": "dsm", "contentType": "image/tiff"}

    first = client.post(f"/v1/processing-jobs/{job_id}/artifacts/upload-url", json=payload)
    second = client.post(f"/v1/processing-jobs/{job_id}/artifacts/upload-url", json=payload)

    assert first.json()["objectKey"] == second.json()["objectKey"]


def test_http_upload_url_refuses_a_worker_without_the_lease(tmp_path: Path) -> None:
    """[음성] lease 없이 올릴 자리를 받지 못한다 — 남의 작업 경로에 쓰지 못하게."""
    client = _client(tmp_path)
    job_id = client.post(
        f"/v1/missions/{_MISSION_ID}/processing-jobs", json=_issue_payload()
    ).json()["job"]["jobId"]
    _as_worker(client)

    response = client.post(
        f"/v1/processing-jobs/{job_id}/artifacts/upload-url",
        json={"artifactId": "dsm", "contentType": "image/tiff"},
    )
    assert response.status_code == 409
    assert response.json()["verdict"] == "LEASE_REQUIRED"


def test_http_upload_url_refuses_humans(tmp_path: Path) -> None:
    """[음성] 사람은 산출물 바이트를 올리지 못한다 — 실행 사실 보고와 같은 경계."""
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    for token in (_ADMIN_TOKEN, _VIEWER_TOKEN):
        client.headers.update({"Authorization": f"Bearer {token}"})
        assert (
            client.post(
                f"/v1/processing-jobs/{job_id}/artifacts/upload-url",
                json={"artifactId": "dsm", "contentType": "image/tiff"},
            ).status_code
            == 403
        )


@pytest.mark.parametrize(
    "artifact_id", ["../escape", "a/b", "", "point cloud", "."]
)
def test_http_upload_url_refuses_path_escaping_artifact_ids(
    tmp_path: Path, artifact_id: str
) -> None:
    """[핵심 음성] 산출물 식별자로 저장 경로를 벗어나지 못한다.

    이 값은 워커가 보내는 것이고, 그대로 객체 키에 이어 붙는다 — 검증이
    없으면 워커 토큰 하나로 버킷의 임의 경로에 쓸 수 있다.
    """
    client = _client(tmp_path)
    job_id = _issued_and_running(client)

    response = client.post(
        f"/v1/processing-jobs/{job_id}/artifacts/upload-url",
        json={"artifactId": artifact_id, "contentType": "application/octet-stream"},
    )
    assert response.status_code == 422, response.text


def test_http_upload_url_refuses_a_finished_job(tmp_path: Path) -> None:
    """[음성] 끝난 작업에는 더 올리지 못한다 — 종료가 쓰기 종료를 뜻해야 한다.

    종료 경로로 ``FAILED`` 를 쓴다. ``SUCCEEDED`` 는 원본 실측 대조까지
    선행돼야 통과하는데(``UNBACKED_SUCCESS``), 이 테스트가 보려는 것은 성공
    조건이 아니라 **활성 여부**다 — 실패로 끝난 작업도 똑같이 막혀야 한다.
    """
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    assert (
        client.post(
            f"/v1/processing-jobs/{job_id}/transitions",
            json={"targetStatus": "FAILED"},
        ).status_code
        == 200
    )

    response = client.post(
        f"/v1/processing-jobs/{job_id}/artifacts/upload-url",
        json={"artifactId": "late", "contentType": "image/tiff"},
    )
    assert response.status_code == 409
    assert response.json()["verdict"] == "JOB_NOT_ACTIVE"


def test_http_artifact_download_returns_a_presigned_url(tmp_path: Path) -> None:
    """등록된 산출물의 바이트를 다시 꺼낼 수 있다 — 이게 M1 의 핵심 주장이다."""
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    assert (
        client.post(
            f"/v1/processing-jobs/{job_id}/artifacts", json=_artifact_payload()
        ).status_code
        == 201
    )
    client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})

    response = client.get(
        f"/v1/processing-jobs/{job_id}/artifacts/pointcloud/download"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"] == "ARTIFACT_READY"
    assert body["objectKey"] == (
        f"sites/{_SITE_ID}/processing-jobs/{job_id}/artifacts/pointcloud"
    )
    assert body["downloadUrl"].startswith("https://storage.invalid/")


def test_http_artifact_download_refuses_an_unregistered_artifact(tmp_path: Path) -> None:
    """[음성] 등록되지 않은 산출물의 URL 을 만들어 주지 않는다.

    키는 식별자에서 유도되므로 등록 여부와 무관하게 **계산은 된다** — 그래서
    원장 대조 없이 발급하면 존재하지 않는 자리의 URL 이 나가고, 소비자는
    404 를 스토리지에서 받는다(원인이 한 단계 멀어진다).
    """
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})

    response = client.get(f"/v1/processing-jobs/{job_id}/artifacts/nope/download")
    assert response.status_code == 404
    assert response.json()["verdict"] == "ARTIFACT_NOT_FOUND"


def test_http_artifact_download_refuses_a_viewer_without_missions_read(
    tmp_path: Path,
) -> None:
    """산출물 열람은 임무 열람 권한을 요구한다."""
    client = _client(tmp_path)
    job_id = _issued_and_running(client)
    assert (
        client.post(
            f"/v1/processing-jobs/{job_id}/artifacts", json=_artifact_payload()
        ).status_code
        == 201
    )
    # 워커 신원 그대로 — PROCESSING_WORK 는 MISSIONS_READ 를 포함하지 않는다.
    response = client.get(
        f"/v1/processing-jobs/{job_id}/artifacts/pointcloud/download"
    )
    assert response.status_code == 403


def test_store_lists_jobs_for_a_site(tmp_path: Path) -> None:
    """현장 단위 epoch 질의 — 시계열 비교가 이 목록 위에서 이뤄진다.

    ``ProcessingJobRecord`` 가 곧 reconstruction epoch 이고(별도 aggregate 를
    만들지 않는다), 빠져 있던 것은 저장 구조가 아니라 이 질의면 하나였다.
    """
    store = _job_store(tmp_path)
    record = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record
    assert record is not None

    listed = store.list_for_site(_SITE_ID)
    assert [job.job_id for job in listed] == [record.job_id]


def test_store_list_for_site_respects_the_limit(tmp_path: Path) -> None:
    """``limit`` 을 지금부터 시그니처에 둔다 — 무제한 전량 반환을 계약으로 굳히지 않는다.

    구현이 아직 in-memory 전량 스캔이어도 상관없다. wire 계약에 페이지 개념이
    없으면 나중에 저장소를 바꿀 때 그게 파괴적 변경이 된다.
    """
    store = _job_store(tmp_path)
    assert store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record is not None
    assert store.list_for_site(_SITE_ID, limit=0) == []


def test_store_list_for_site_does_not_leak_other_sites(tmp_path: Path) -> None:
    """[음성] 다른 현장의 작업이 섞이지 않는다."""
    store = _job_store(tmp_path)
    assert store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record is not None
    assert store.list_for_site("site-does-not-exist") == []
