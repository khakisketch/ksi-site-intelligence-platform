"""3D 재구성 처리 작업 발급·상태전이 계약 (B2 — ADR-KSI-012, INV-050).

초점 넷:

1. **입력은 봉인된 번들에서만 온다** — 요청에 자리가 없고, 봉인 전에는 발급되지
   않는다(장수·화소·digest 가 확정되지 않은 값 위에서 과금 근거를 만들지 않는다).
2. **INV-050 은 현장 값으로 판정한다** — 반출 미선언·미허용 현장의 vendor_cloud
   작업은 거부된다. 요청이 ``dataResidency`` 를 실어 보내도 거부된다.
3. **상태 전이표를 재생이 다시 태운다** — journal 을 손으로 고쳐 FAILED 를
   SUCCEEDED 로 되살릴 수 없다.
4. **임무당 활성 작업 1건** — 같은 사양 재요청은 멱등, 다른 사양은 409.
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
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_core.processing_jobs import (
    UNMETERED_AT_ISSUE,
    IllegalJobTransitionError,
    JobSpec,
    ProcessingJobRecoveryError,
    ProcessingJobStore,
    ProcessingJobVerdict,
    assert_job_transition,
    build_job_id,
)
from ksi_core.sites import SiteStore
from ksi_core.source_media import SourceMediaClaim, SourceMediaStore
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
    path: str = "processing-jobs.jsonl",
) -> ProcessingJobStore:
    """``journal`` 을 직접 주면 재생 테스트가 그 핸들을 닫을 수 있다(단일 writer 잠금)."""
    return ProcessingJobStore(
        journal if journal is not None else DurableJournal(tmp_path / path),
        source_media_store=_sealed_bundle_store(tmp_path, media_count=media_count, seal=seal),
        site_store=_site_store(tmp_path, egress=egress),
    )


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
    store.transition(
        record.job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW
    )
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
        source_media_store=_sealed_bundle_store(tmp_path, path="replay-source-media.jsonl"),
        site_store=_site_store(tmp_path, egress=egress, path="replay-sites.jsonl"),
    )


def test_replay_restores_status_and_sequence(tmp_path: Path) -> None:
    journal = DurableJournal(tmp_path / "processing-jobs.jsonl")
    store = _job_store(tmp_path, journal=journal)
    first = store.issue(_MISSION_ID, _spec(), issued_by="op-1", now=_NOW).record
    assert first is not None
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
        ]
    )


def _client(tmp_path: Path, *, egress: bool | None = None) -> TestClient:
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
    site_store = _site_store(tmp_path, egress=egress, path="http-sites.jsonl")
    app = create_app(
        auth_registry=_auth_registry(),
        mission_store=mission_store,
        site_store=site_store,
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


def test_http_transition_and_get(tmp_path: Path) -> None:
    client = _client(tmp_path)
    job_id = client.post(
        f"/v1/missions/{_MISSION_ID}/processing-jobs", json=_issue_payload()
    ).json()["job"]["jobId"]

    running = client.post(
        f"/v1/processing-jobs/{job_id}/transitions", json={"targetStatus": "RUNNING"}
    )
    assert running.status_code == 200
    assert running.json()["job"]["status"] == "RUNNING"

    illegal = client.post(
        f"/v1/processing-jobs/{job_id}/transitions", json={"targetStatus": "QUEUED"}
    )
    assert illegal.status_code == 409
    assert illegal.json()["verdict"] == "ILLEGAL_TRANSITION"

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
    } <= paths
