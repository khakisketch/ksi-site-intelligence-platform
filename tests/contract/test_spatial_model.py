"""현장 공간모델 판정 — 유무·나이·정책 미선언 (ADR-KSI-019 G1).

이 파일이 검증하는 것은 저장소 동작이 아니라 **판정 함수**다(발급·전이 게이트는
``test_processing_jobs.py`` 소관). 그래서 ``ProcessingJobRecord`` 를 저장소를 거치지
않고 직접 조립한다 — 판정이 원장 쓰기 경로와 독립적으로 성립해야 하기 때문이다.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ksi_core.processing_jobs import JobSpec, ProcessingJobRecord
from ksi_core.source_media import CaptureWindow, CaptureWindowStatus
from ksi_core.spatial_model import (
    SpatialModelState,
    evaluate_spatial_model,
    has_source_artifact,
    is_spatial_model_epoch,
)
from ksi_domain.enums import SiteStatus
from ksi_event_contracts.processing_artifact import (
    ArtifactLineage,
    LineageAuthority,
    ProcessingArtifact,
    ProcessingArtifactKind,
)
from ksi_event_contracts.processing_job import (
    DataResidency,
    ExecutionLocus,
    LicenseBasis,
    ProcessingInput,
    ProcessingJobStatus,
    ProcessingProvider,
)

_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
_SOURCE_DIGEST = "sha256:" + "a" * 64


def _artifact(
    job_id: str,
    *,
    authority: LineageAuthority,
    suffix: str,
) -> ProcessingArtifact:
    """산출물 1건 — 파생은 원본을 부모로 가리킨다(INV-051 계약 검증 통과용)."""
    return ProcessingArtifact(
        artifact_id=f"{job_id}-{suffix}",
        job_id=job_id,
        kind=(
            ProcessingArtifactKind.POINT_CLOUD
            if authority is LineageAuthority.SOURCE
            else ProcessingArtifactKind.MESH
        ),
        lineage=ArtifactLineage(
            authority=authority,
            source_digest=_SOURCE_DIGEST,
            derived_from=[] if authority is LineageAuthority.SOURCE else [f"{job_id}-pc"],
        ),
        digest="sha256:" + hashlib.sha256(f"{job_id}-{suffix}".encode()).hexdigest(),
        format="laz" if authority is LineageAuthority.SOURCE else "obj",
        crs="EPSG:5186",
    )


def _record(
    *,
    job_id: str = "mission-a-pj1",
    site_id: str = "site-a",
    status: ProcessingJobStatus = ProcessingJobStatus.SUCCEEDED,
    updated_at: datetime = _NOW,
    with_source: bool = False,
    with_derived: bool = False,
    capture_window: CaptureWindow | None = None,
) -> ProcessingJobRecord:
    artifacts: list[ProcessingArtifact] = []
    if with_source:
        artifacts.append(_artifact(job_id, authority=LineageAuthority.SOURCE, suffix="pc"))
    if with_derived:
        artifacts.append(_artifact(job_id, authority=LineageAuthority.DERIVED, suffix="mesh"))
    return ProcessingJobRecord(
        job_id=job_id,
        mission_id="mission-a",
        site_id=site_id,
        spec=JobSpec(
            provider=ProcessingProvider.ODM,
            engine_version="3.5.4",
            engine_digest="sha256:" + "b" * 64,
            execution_locus=ExecutionLocus.KSI_SERVER_GPU,
            license_basis=LicenseBasis(
                license_id="AGPL-3.0", tier="self-hosted", attribution_required=False
            ),
            processing_params={"quality": "high"},
        ),
        data_residency=DataResidency(egress_allowed=False, jurisdiction="KR"),
        input=ProcessingInput(
            image_count=120, total_megapixels=2400.0, source_bundle_digest=_SOURCE_DIGEST
        ),
        status=status,
        issued_at=updated_at,
        issued_by="op-1",
        updated_at=updated_at,
        artifacts=tuple(artifacts),
        capture_window=(
            capture_window
            if capture_window is not None
            else CaptureWindow(CaptureWindowStatus.COMPLETE, updated_at, updated_at)
        ),
    )


# --- 유무 판정 ----------------------------------------------------------------


def test_no_jobs_means_absent() -> None:
    status = evaluate_spatial_model([], now=_NOW, max_age_days=30)

    assert status.state is SpatialModelState.ABSENT
    assert status.epoch_job_id is None
    assert status.registered_at is None
    assert status.age_days is None
    assert status.succeeded_epoch_count == 0
    assert status.source_artifact_count == 0


def test_succeeded_job_without_source_artifact_is_not_a_model() -> None:
    """파생 산출물만 있는 성공은 '모델이 있다'로 세지 않는다(ADR-KSI-003).

    원본 없이 파생만 있는 상태를 모델로 읽으면 원본/파생 권위 구분이 조회
    표면에서 무너진다.
    """
    derived_only = _record(with_derived=True)

    status = evaluate_spatial_model([derived_only], now=_NOW, max_age_days=30)

    assert status.state is SpatialModelState.ABSENT
    assert status.source_artifact_count == 0
    assert not has_source_artifact(derived_only)
    assert not is_spatial_model_epoch(derived_only)


def test_succeeded_job_with_no_artifacts_at_all_is_not_a_model() -> None:
    status = evaluate_spatial_model([_record()], now=_NOW, max_age_days=30)

    assert status.state is SpatialModelState.ABSENT


@pytest.mark.parametrize(
    "status",
    [
        ProcessingJobStatus.QUEUED,
        ProcessingJobStatus.RUNNING,
        ProcessingJobStatus.FAILED,
        ProcessingJobStatus.CANCELLED,
    ],
)
def test_non_succeeded_jobs_are_not_models(status: ProcessingJobStatus) -> None:
    """성공하지 않은 작업은 산출물을 갖고 있어도 모델이 아니다."""
    record = _record(status=status, with_source=True)

    assert evaluate_spatial_model([record], now=_NOW, max_age_days=30).state is (
        SpatialModelState.ABSENT
    )


# --- 나이 판정 ----------------------------------------------------------------


def test_recent_source_backed_success_is_fresh() -> None:
    record = _record(updated_at=_NOW - timedelta(days=1), with_source=True, with_derived=True)

    status = evaluate_spatial_model([record], now=_NOW, max_age_days=30)

    assert status.state is SpatialModelState.FRESH
    assert status.epoch_job_id == record.job_id
    assert status.registered_at == record.updated_at
    assert status.age_days == pytest.approx(1.0)
    assert status.source_artifact_count == 1
    assert status.max_age_days == 30


def test_old_source_backed_success_is_stale() -> None:
    old = _record(updated_at=_NOW - timedelta(days=45), with_source=True)

    status = evaluate_spatial_model([old], now=_NOW, max_age_days=30)

    assert status.state is SpatialModelState.STALE
    assert status.age_days == pytest.approx(45.0)


def test_late_upload_uses_capture_time_not_registration_time() -> None:
    """오래된 사진을 오늘 처리해도 최신 모델로 세탁되지 않는다."""
    captured = _NOW - timedelta(days=45)
    uploaded_today = _record(
        updated_at=_NOW,
        with_source=True,
        capture_window=CaptureWindow(CaptureWindowStatus.COMPLETE, captured, captured),
    )

    status = evaluate_spatial_model([uploaded_today], now=_NOW, max_age_days=30)

    assert status.state is SpatialModelState.STALE
    assert status.age_days == pytest.approx(45.0)
    assert status.registered_at == _NOW
    assert status.captured_to == captured
    assert status.freshness_basis.value == "CAPTURED_TO"


@pytest.mark.parametrize(
    "window_status", [CaptureWindowStatus.INCOMPLETE, CaptureWindowStatus.CONFLICT]
)
def test_missing_or_conflicting_capture_time_never_falls_back_to_registration(
    window_status: CaptureWindowStatus,
) -> None:
    record = _record(
        updated_at=_NOW,
        with_source=True,
        capture_window=CaptureWindow(window_status),
    )

    status = evaluate_spatial_model([record], now=_NOW, max_age_days=30)

    assert status.state is SpatialModelState.CAPTURE_TIME_UNAVAILABLE
    assert status.age_days is None
    assert status.freshness_basis.value == "NONE"
    assert status.capture_time_status == window_status.value


def test_exactly_at_the_threshold_is_still_fresh() -> None:
    """경계는 포함이다 — '30일 기준'이 30일째에 끊기면 사용자 기대와 어긋난다."""
    at_edge = _record(updated_at=_NOW - timedelta(days=30), with_source=True)

    assert evaluate_spatial_model([at_edge], now=_NOW, max_age_days=30).state is (
        SpatialModelState.FRESH
    )


def test_undeclared_policy_is_not_reported_as_fresh() -> None:
    """[핵심] 나이 기준을 선언하지 않은 현장을 FRESH 로 뭉개지 않는다.

    '판정하지 않았다'와 '판정했더니 최신이다'는 다른 사실이다. 전자를 후자로
    표시하면 화면이 근거 없는 안심을 준다(INV-040 정신).
    """
    ancient = _record(updated_at=_NOW - timedelta(days=400), with_source=True)

    status = evaluate_spatial_model([ancient], now=_NOW, max_age_days=None)

    assert status.state is SpatialModelState.AGE_POLICY_UNDECLARED
    assert status.epoch_job_id == ancient.job_id
    assert status.max_age_days is None
    assert status.age_days == pytest.approx(400.0)


def test_undeclared_policy_with_no_epoch_is_still_absent() -> None:
    """모델 자체가 없으면 정책 미선언보다 '없음'이 먼저다 — 없는 모델은 나이가 없다."""
    assert evaluate_spatial_model([], now=_NOW, max_age_days=None).state is (
        SpatialModelState.ABSENT
    )


# --- 최신 epoch 선택 ----------------------------------------------------------


def test_newest_epoch_wins() -> None:
    old = _record(job_id="j-old", updated_at=_NOW - timedelta(days=40), with_source=True)
    new = _record(job_id="j-new", updated_at=_NOW - timedelta(days=2), with_source=True)

    status = evaluate_spatial_model([old, new], now=_NOW, max_age_days=30)

    assert status.state is SpatialModelState.FRESH
    assert status.epoch_job_id == "j-new"
    assert status.succeeded_epoch_count == 2


def test_input_order_does_not_change_the_verdict() -> None:
    """호출자의 정렬에 판정이 좌우되지 않는다 — 함수가 스스로 최신을 고른다."""
    old = _record(job_id="j-old", updated_at=_NOW - timedelta(days=40), with_source=True)
    new = _record(job_id="j-new", updated_at=_NOW - timedelta(days=2), with_source=True)

    forward = evaluate_spatial_model([old, new], now=_NOW, max_age_days=30)
    backward = evaluate_spatial_model([new, old], now=_NOW, max_age_days=30)

    assert forward == backward


def test_same_timestamp_is_broken_deterministically_by_job_id() -> None:
    """같은 시각이면 재생마다 다른 epoch 를 고르지 않는다."""
    a = _record(job_id="j-a", updated_at=_NOW, with_source=True)
    b = _record(job_id="j-b", updated_at=_NOW, with_source=True)

    assert evaluate_spatial_model([a, b], now=_NOW, max_age_days=30).epoch_job_id == "j-b"
    assert evaluate_spatial_model([b, a], now=_NOW, max_age_days=30).epoch_job_id == "j-b"


def test_failed_reruns_do_not_hide_an_older_success() -> None:
    """실패한 재처리가 있어도 그 전의 성공 epoch 는 여전히 모델이다."""
    success = _record(job_id="j-1", updated_at=_NOW - timedelta(days=5), with_source=True)
    failed_rerun = _record(job_id="j-2", status=ProcessingJobStatus.FAILED, updated_at=_NOW)

    status = evaluate_spatial_model([success, failed_rerun], now=_NOW, max_age_days=30)

    assert status.state is SpatialModelState.FRESH
    assert status.epoch_job_id == "j-1"
    assert status.succeeded_epoch_count == 1


# --- 경계 --------------------------------------------------------------------


def test_future_timestamp_does_not_produce_negative_age() -> None:
    """시계 어긋남으로 미래 시각이 들어와도 음수 나이를 내지 않는다(0 으로 절단)."""
    ahead = _record(updated_at=_NOW + timedelta(hours=3), with_source=True)

    status = evaluate_spatial_model([ahead], now=_NOW, max_age_days=30)

    assert status.age_days == 0.0
    assert status.state is SpatialModelState.FRESH


def test_naive_now_is_refused() -> None:
    with pytest.raises(ValueError, match="tz-aware"):
        evaluate_spatial_model([], now=datetime(2026, 8, 15, 12, 0), max_age_days=30)  # noqa: DTZ001


def test_evaluation_does_not_mutate_its_input() -> None:
    """순수 함수다 — 호출이 원장 레코드를 건드리지 않는다."""
    record = _record(with_source=True)
    before: dict[str, Any] = {"status": record.status, "updated_at": record.updated_at}

    evaluate_spatial_model([record], now=_NOW, max_age_days=30)

    assert record.status == before["status"]
    assert record.updated_at == before["updated_at"]


# --- 조회 표면 ----------------------------------------------------------------
#
# 여기서부터는 판정 함수가 아니라 **라우터**를 본다: 현장 조회·404·권한·상태 정합
# 플래그. FRESH/STALE 판정 자체는 위 순수 함수 테스트가 이미 고정했으므로 반복하지
# 않는다. 실제 ProcessingJobStore 와의 배선은 AOL-1 종단 테스트가 확인한다.


class _JobsStub:
    """``list_for_site`` 만 노출하는 최소 스텁.

    실제 ``ProcessingJobStore`` 로 성공 epoch 를 만들려면 봉인된 번들·lease·산출물
    등록까지 전 경로를 태워야 한다(그건 ``test_processing_jobs.py`` 소관이다).
    이 스텁은 **라우터가 site_id 로 그 현장의 작업만 읽는가**를 본다 — 다른
    현장의 작업을 섞어 넣어 그 사실을 실제로 검사한다.
    """

    def __init__(self, records: list[ProcessingJobRecord]) -> None:
        self._records = records

    def list_for_site(
        self, site_id: str, *, limit: int | None = None
    ) -> list[ProcessingJobRecord]:
        matched = [r for r in self._records if r.site_id == site_id]
        return matched if limit is None else matched[:limit]


def _spatial_model_client(
    tmp_path: Any, *, records: list[ProcessingJobRecord] | None = None
) -> Any:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ksi_core.auth import (
        AuthRegistry,
        Principal,
        PrincipalKind,
        PrincipalTokenRecord,
        Role,
        mount_auth,
    )
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.sites import SiteStore, mount_sites
    from ksi_core.spatial_model import mount_spatial_model
    from ksi_mission_contracts.models import SiteFrame

    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    site_store.register(
        "site-a",
        "테스트 현장",
        SiteFrame.model_validate(
            {
                "crs": "EPSG:5186",
                "verticalDatum": "KNGeoid2018",
                "unit": "meter",
                "transformVersion": "1.0.0",
            }
        ),
        actor="op-1",
        now=_NOW,
    )

    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest("sm-operator"),
                principal=Principal(
                    principal_id="op-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest("sm-device"),
                principal=Principal(
                    principal_id="edge-1",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id="dev-1",
                ),
            ),
        ]
    )

    app = FastAPI()
    mount_auth(app, registry)
    jobs = _JobsStub(records or [])
    mount_sites(app, site_store, jobs)
    mount_spatial_model(
        app, site_store=site_store, processing_job_store=jobs
    )
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer sm-operator"})
    return client, site_store


def test_spatial_model_endpoint_reports_absent_for_new_site(tmp_path: Any) -> None:
    client, _ = _spatial_model_client(tmp_path)

    body = client.get("/v1/sites/site-a/spatial-model").json()

    assert body["siteId"] == "site-a"
    assert body["state"] == "ABSENT"
    assert body["epochJobId"] is None
    assert body["siteStatus"] == "UNMAPPED"
    assert body["siteStatusMatchesModel"] is True


def test_spatial_model_endpoint_reads_only_this_site(tmp_path: Any) -> None:
    """다른 현장의 epoch 를 이 현장의 것으로 세지 않는다."""
    mine = _record(job_id="j-mine", site_id="site-a", with_source=True)
    theirs = _record(job_id="j-theirs", site_id="site-b", with_source=True)
    client, site_store = _spatial_model_client(tmp_path, records=[mine, theirs])
    site_store.set_model_age_policy("site-a", max_age_days=30, actor="op-1", now=_NOW)

    body = client.get("/v1/sites/site-a/spatial-model").json()

    assert body["epochJobId"] == "j-mine"
    assert body["succeededEpochCount"] == 1
    assert body["maxAgeDays"] == 30


def test_spatial_model_endpoint_reports_undeclared_policy(tmp_path: Any) -> None:
    client, _ = _spatial_model_client(
        tmp_path, records=[_record(site_id="site-a", with_source=True)]
    )

    body = client.get("/v1/sites/site-a/spatial-model").json()

    assert body["state"] == "AGE_POLICY_UNDECLARED"


def test_site_detail_nests_the_capture_time_spatial_summary(tmp_path: Any) -> None:
    captured = _NOW - timedelta(days=2)
    client, _ = _spatial_model_client(
        tmp_path,
        records=[
            _record(
                site_id="site-a",
                with_source=True,
                capture_window=CaptureWindow(
                    CaptureWindowStatus.COMPLETE, captured, captured
                ),
            )
        ],
    )

    body = client.get("/v1/sites/site-a").json()

    assert body["siteId"] == "site-a"
    assert body["spatialModel"]["capturedFrom"] == captured.isoformat()
    assert body["spatialModel"]["capturedTo"] == captured.isoformat()
    assert body["spatialModel"]["captureTimeStatus"] == "COMPLETE"
    assert body["spatialModel"]["freshnessBasis"] == "CAPTURED_TO"
    assert body["spatialModel"]["maxAgeDays"] is None


def test_spatial_model_endpoint_flags_status_model_mismatch(tmp_path: Any) -> None:
    """[핵심] 현장 상태가 PATROL_READY 인데 모델이 없으면 화면이 그 모순을 본다.

    자동 전진이 막혔거나 사람이 손으로 상태를 올린 경우다. 조용히 넘기면 화면이
    "모델 있는 현장"으로 읽는다. 조회는 판정만 하고 아무것도 고치지 않는다 —
    조회가 원장을 되돌리기 시작하면 상태가 조회 시점에 따라 달라진다.
    """
    client, site_store = _spatial_model_client(tmp_path)
    for target in (
        SiteStatus.BASELINE_MAPPING,
        SiteStatus.MODEL_PROCESSING,
        SiteStatus.MODEL_VALIDATION,
        SiteStatus.PROVISIONAL_AUTONOMY,
        SiteStatus.PATROL_READY,
    ):
        site_store.transition(
            "site-a", target, evidence="e", reason="r", actor="op-1", now=_NOW
        )

    body = client.get("/v1/sites/site-a/spatial-model").json()

    assert body["state"] == "ABSENT"
    assert body["siteStatus"] == "PATROL_READY"
    assert body["siteStatusMatchesModel"] is False
    # 조회가 상태를 되돌리지 않았다.
    assert site_store.get("site-a").status is SiteStatus.PATROL_READY


def test_stale_model_on_a_patrol_ready_site_is_not_a_mismatch(tmp_path: Any) -> None:
    """모델이 낡은 것과 모델이 없는 것은 다르다 — 낡음은 모순이 아니다."""
    client, site_store = _spatial_model_client(
        tmp_path,
        records=[
            _record(site_id="site-a", updated_at=_NOW - timedelta(days=400), with_source=True)
        ],
    )
    for target in (
        SiteStatus.BASELINE_MAPPING,
        SiteStatus.MODEL_PROCESSING,
        SiteStatus.MODEL_VALIDATION,
        SiteStatus.PROVISIONAL_AUTONOMY,
        SiteStatus.PATROL_READY,
    ):
        site_store.transition(
            "site-a", target, evidence="e", reason="r", actor="op-1", now=_NOW
        )
    site_store.set_model_age_policy("site-a", max_age_days=30, actor="op-1", now=_NOW)

    body = client.get("/v1/sites/site-a/spatial-model").json()

    assert body["state"] == "STALE"
    assert body["siteStatusMatchesModel"] is True


def test_spatial_model_endpoint_is_404_for_unknown_site(tmp_path: Any) -> None:
    client, _ = _spatial_model_client(tmp_path)

    assert client.get("/v1/sites/nope/spatial-model").status_code == 404


def test_spatial_model_endpoint_requires_sites_read(tmp_path: Any) -> None:
    client, _ = _spatial_model_client(tmp_path)

    response = client.get(
        "/v1/sites/site-a/spatial-model", headers={"Authorization": "Bearer sm-device"}
    )

    assert response.status_code == 403


# --- 자동 전진 ----------------------------------------------------------------


def _lifecycle_pair(tmp_path: Any, *, records: list[ProcessingJobRecord] | None = None) -> Any:
    """(lifecycle, site_store) — site-a 는 UNMAPPED 로 등록된 상태."""
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.sites import SiteStore
    from ksi_core.spatial_model import SpatialModelLifecycle
    from ksi_mission_contracts.models import SiteFrame

    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    site_store.register(
        "site-a",
        "테스트 현장",
        SiteFrame.model_validate(
            {
                "crs": "EPSG:5186",
                "verticalDatum": "KNGeoid2018",
                "unit": "meter",
                "transformVersion": "1.0.0",
            }
        ),
        actor="op-1",
        now=_NOW,
    )
    lifecycle = SpatialModelLifecycle(
        site_store=site_store, processing_job_store=_JobsStub(records or [])
    )
    return lifecycle, site_store


def _advance_site(site_store: Any, target: SiteStatus) -> None:
    """UNMAPPED 에서 목표 상태까지 합법 경로로 민다(테스트 준비 전용)."""
    path = {
        SiteStatus.BASELINE_MAPPING: (SiteStatus.BASELINE_MAPPING,),
        SiteStatus.MODEL_PROCESSING: (
            SiteStatus.BASELINE_MAPPING,
            SiteStatus.MODEL_PROCESSING,
        ),
        SiteStatus.MODEL_VALIDATION: (
            SiteStatus.BASELINE_MAPPING,
            SiteStatus.MODEL_PROCESSING,
            SiteStatus.MODEL_VALIDATION,
        ),
        SiteStatus.PATROL_READY: (
            SiteStatus.BASELINE_MAPPING,
            SiteStatus.MODEL_PROCESSING,
            SiteStatus.MODEL_VALIDATION,
            SiteStatus.PROVISIONAL_AUTONOMY,
            SiteStatus.PATROL_READY,
        ),
    }[target]
    for step in path:
        result = site_store.transition(
            "site-a", step, evidence="test", reason="test", actor="test", now=_NOW
        )
        assert result.verdict.value == "TRANSITIONED", result.detail


def test_job_issued_advances_baseline_mapping_to_model_processing(tmp_path: Any) -> None:
    from ksi_core.spatial_model import SiteAdvanceOutcome

    lifecycle, site_store = _lifecycle_pair(tmp_path)
    _advance_site(site_store, SiteStatus.BASELINE_MAPPING)

    outcome = lifecycle.advance_for_job_status(
        "site-a", ProcessingJobStatus.QUEUED, job_id="site-a-m1-pj1", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ADVANCED
    assert site_store.get("site-a").status is SiteStatus.MODEL_PROCESSING


def test_job_succeeded_advances_model_processing_to_model_validation(tmp_path: Any) -> None:
    from ksi_core.spatial_model import SiteAdvanceOutcome

    lifecycle, site_store = _lifecycle_pair(tmp_path)
    _advance_site(site_store, SiteStatus.MODEL_PROCESSING)

    outcome = lifecycle.advance_for_job_status(
        "site-a", ProcessingJobStatus.SUCCEEDED, job_id="site-a-m1-pj1", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ADVANCED
    assert site_store.get("site-a").status is SiteStatus.MODEL_VALIDATION


def test_auto_advance_never_crosses_the_autonomy_approval_edge(tmp_path: Any) -> None:
    """[핵심] 자동 전진이 사람의 승인 간선을 대신 밟지 않는다.

    MODEL_VALIDATION → PROVISIONAL_AUTONOMY 는 SITES_AUTONOMY_APPROVE 전용이다
    (ADR-KSI-015 D2). 재구성 성공 하나로 자율운영이 열리면 그 권한이 장식이 된다.
    """
    from ksi_core.spatial_model import SiteAdvanceOutcome

    lifecycle, site_store = _lifecycle_pair(tmp_path)
    _advance_site(site_store, SiteStatus.MODEL_VALIDATION)

    outcome = lifecycle.advance_for_job_status(
        "site-a", ProcessingJobStatus.SUCCEEDED, job_id="site-a-m1-pj2", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ALREADY_PAST
    assert site_store.get("site-a").status is SiteStatus.MODEL_VALIDATION


def test_no_advance_rule_targets_an_autonomy_approval_edge() -> None:
    """전진 규칙표 자체가 승인 간선을 담지 않는다는 구조적 보증.

    위 테스트는 한 경우를 반증하고, 이 테스트는 표 전체를 본다 — 나중에 규칙이
    추가돼도 승인 간선이 섞여 들어오면 여기서 즉시 드러난다.
    """
    from ksi_core.spatial_model import (  # noqa: PLC2701 -- 규칙표 전수 검사를 위한 의도적 내부 접근
        _JOB_STATUS_SITE_ADVANCE,
    )
    from ksi_domain.enums import requires_autonomy_approval

    for source, target in _JOB_STATUS_SITE_ADVANCE.values():
        assert not requires_autonomy_approval(source, target), (
            f"자동 전진 규칙이 승인 간선을 담고 있다: {source.value} → {target.value}"
        )


def test_advance_from_wrong_status_is_reported_not_raised(tmp_path: Any) -> None:
    """[핵심] UNMAPPED 현장에 재구성 성공이 들어와도 예외를 던지지 않는다.

    전진 실패가 원래 요청(워커의 성공 보고)을 깨뜨리면, 현장 상태가 어긋났다는
    이유로 되돌릴 수 없는 계산 결과가 유실된다.
    """
    from ksi_core.spatial_model import SiteAdvanceOutcome

    lifecycle, site_store = _lifecycle_pair(tmp_path)

    outcome = lifecycle.advance_for_job_status(
        "site-a", ProcessingJobStatus.SUCCEEDED, job_id="x-pj1", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ILLEGAL_FROM_CURRENT
    assert site_store.get("site-a").status is SiteStatus.UNMAPPED


@pytest.mark.parametrize(
    "status", [ProcessingJobStatus.FAILED, ProcessingJobStatus.CANCELLED]
)
def test_failed_and_cancelled_jobs_do_not_move_the_site(
    tmp_path: Any, status: ProcessingJobStatus
) -> None:
    from ksi_core.spatial_model import SiteAdvanceOutcome

    lifecycle, site_store = _lifecycle_pair(tmp_path)
    _advance_site(site_store, SiteStatus.MODEL_PROCESSING)

    assert (
        lifecycle.advance_for_job_status("site-a", status, job_id="x", now=_NOW)
        is SiteAdvanceOutcome.NO_RULE
    )
    assert site_store.get("site-a").status is SiteStatus.MODEL_PROCESSING


def test_unknown_site_is_reported_not_raised(tmp_path: Any) -> None:
    from ksi_core.spatial_model import SiteAdvanceOutcome

    lifecycle, _ = _lifecycle_pair(tmp_path)

    assert (
        lifecycle.advance_for_job_status(
            "ghost", ProcessingJobStatus.SUCCEEDED, job_id="x", now=_NOW
        )
        is SiteAdvanceOutcome.UNKNOWN_SITE
    )


def test_advance_writes_a_system_actor_into_the_site_journal(tmp_path: Any) -> None:
    """누가 옮겼는지가 원장에 남는다 — 자동 전이도 감사 대상이다."""
    import json

    lifecycle, site_store = _lifecycle_pair(tmp_path)
    _advance_site(site_store, SiteStatus.MODEL_PROCESSING)

    lifecycle.advance_for_job_status(
        "site-a", ProcessingJobStatus.SUCCEEDED, job_id="site-a-m1-pj1", now=_NOW
    )

    entries = [
        json.loads(line)
        for line in (tmp_path / "sites.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    last = entries[-1]
    assert last["kind"] == "site-transitioned"
    assert last["actor"] == "system:spatial-model-lifecycle"
    assert "site-a-m1-pj1" in last["evidence"]
    assert last["reason"]


def test_suspended_site_is_not_advanced(tmp_path: Any) -> None:
    """운영 중단된 현장을 자동화가 되살리지 않는다."""
    from ksi_core.spatial_model import SiteAdvanceOutcome

    lifecycle, site_store = _lifecycle_pair(tmp_path)
    _advance_site(site_store, SiteStatus.MODEL_PROCESSING)
    site_store.transition(
        "site-a", SiteStatus.SUSPENDED, evidence="e", reason="r", actor="admin", now=_NOW
    )

    outcome = lifecycle.advance_for_job_status(
        "site-a", ProcessingJobStatus.SUCCEEDED, job_id="x", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ILLEGAL_FROM_CURRENT
    assert site_store.get("site-a").status is SiteStatus.SUSPENDED


# --- 매핑 임무 배포 → 매핑 시작 ------------------------------------------------


def test_mapping_mission_dispatch_starts_baseline_mapping(tmp_path: Any) -> None:
    from ksi_core.spatial_model import SiteAdvanceOutcome
    from ksi_domain.enums import MissionType

    lifecycle, site_store = _lifecycle_pair(tmp_path)

    outcome = lifecycle.advance_for_mission_dispatched(
        "site-a", MissionType.BASELINE_MAPPING, mission_id="m-1", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ADVANCED
    assert site_store.get("site-a").status is SiteStatus.BASELINE_MAPPING


def test_remap_required_also_starts_baseline_mapping(tmp_path: Any) -> None:
    """재매핑 지시를 받은 현장에 매핑 임무가 배포되면 그것이 곧 재매핑 시작이다."""
    from ksi_core.spatial_model import SiteAdvanceOutcome
    from ksi_domain.enums import MissionType

    lifecycle, site_store = _lifecycle_pair(tmp_path)
    _advance_site(site_store, SiteStatus.MODEL_VALIDATION)
    site_store.transition(
        "site-a", SiteStatus.REMAP_REQUIRED, evidence="e", reason="r", actor="op", now=_NOW
    )

    outcome = lifecycle.advance_for_mission_dispatched(
        "site-a", MissionType.SURVEY_GRADE_MAPPING, mission_id="m-2", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ADVANCED
    assert site_store.get("site-a").status is SiteStatus.BASELINE_MAPPING


@pytest.mark.parametrize(
    "mission_type_value",
    ["AUTONOMOUS_PATROL", "SPATIAL_REFRESH", "ASSET_INSPECTION", "INCIDENT_SURVEY"],
)
def test_non_mapping_mission_dispatch_does_not_move_the_site(
    tmp_path: Any, mission_type_value: str
) -> None:
    """[핵심] 순찰·재관측·사고조사 배포가 현장을 매핑 시작으로 되돌리지 않는다.

    특히 INCIDENT_SURVEY 는 UNMAPPED 에서도 발급 가능하지만(INV-052 의 보수적 추론)
    지도를 만드는 임무가 아니다 — 사고조사 한 번이 현장을 전진시키면 그 추론이
    상태머신까지 번진다.
    """
    from ksi_core.spatial_model import SiteAdvanceOutcome
    from ksi_domain.enums import MissionType

    lifecycle, site_store = _lifecycle_pair(tmp_path)

    outcome = lifecycle.advance_for_mission_dispatched(
        "site-a", MissionType(mission_type_value), mission_id="m-3", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.NO_RULE
    assert site_store.get("site-a").status is SiteStatus.UNMAPPED


def test_mapping_dispatch_on_an_already_mapping_site_is_already_past(tmp_path: Any) -> None:
    """두 번째 매핑 임무 배포가 진행 중인 현장을 되돌리지 않는다."""
    from ksi_core.spatial_model import SiteAdvanceOutcome
    from ksi_domain.enums import MissionType

    lifecycle, site_store = _lifecycle_pair(tmp_path)
    _advance_site(site_store, SiteStatus.MODEL_PROCESSING)

    outcome = lifecycle.advance_for_mission_dispatched(
        "site-a", MissionType.BASELINE_MAPPING, mission_id="m-2", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ALREADY_PAST
    assert site_store.get("site-a").status is SiteStatus.MODEL_PROCESSING


# --- 노후 스윕 ---------------------------------------------------------------


def _aged_epoch(days: int = 400) -> ProcessingJobRecord:
    return _record(
        job_id="j-aged",
        site_id="site-a",
        updated_at=_NOW - timedelta(days=days),
        with_source=True,
    )


def test_staleness_sweep_moves_patrol_ready_to_model_stale(tmp_path: Any) -> None:
    from ksi_core.spatial_model import SiteAdvanceOutcome

    lifecycle, site_store = _lifecycle_pair(tmp_path, records=[_aged_epoch()])
    _advance_site(site_store, SiteStatus.PATROL_READY)
    site_store.set_model_age_policy("site-a", max_age_days=30, actor="op", now=_NOW)

    outcome = lifecycle.sweep_staleness("site-a", now=_NOW)

    assert outcome is SiteAdvanceOutcome.ADVANCED
    assert site_store.get("site-a").status is SiteStatus.MODEL_STALE


def test_staleness_sweep_does_nothing_without_a_declared_policy(tmp_path: Any) -> None:
    """[핵심] 노후 기준을 선언하지 않은 현장을 서버가 임의로 낡았다고 하지 않는다.

    기준을 지어내면 그 숫자가 근거 없이 현장의 자율운영을 끊는다.
    """
    from ksi_core.spatial_model import SiteAdvanceOutcome

    lifecycle, site_store = _lifecycle_pair(tmp_path, records=[_aged_epoch()])
    _advance_site(site_store, SiteStatus.PATROL_READY)

    outcome = lifecycle.sweep_staleness("site-a", now=_NOW)

    assert outcome is SiteAdvanceOutcome.NO_RULE
    assert site_store.get("site-a").status is SiteStatus.PATROL_READY


def test_staleness_sweep_leaves_a_fresh_model_alone(tmp_path: Any) -> None:
    from ksi_core.spatial_model import SiteAdvanceOutcome

    lifecycle, site_store = _lifecycle_pair(tmp_path, records=[_aged_epoch(days=2)])
    _advance_site(site_store, SiteStatus.PATROL_READY)
    site_store.set_model_age_policy("site-a", max_age_days=30, actor="op", now=_NOW)

    assert lifecycle.sweep_staleness("site-a", now=_NOW) is SiteAdvanceOutcome.NO_RULE
    assert site_store.get("site-a").status is SiteStatus.PATROL_READY


def test_staleness_sweep_does_not_touch_sites_outside_patrol(tmp_path: Any) -> None:
    """매핑·처리·검증 중인 현장은 건드리지 않는다 — 노후가 이미 진행 중 작업으로 표현돼 있다."""
    from ksi_core.spatial_model import SiteAdvanceOutcome

    lifecycle, site_store = _lifecycle_pair(tmp_path, records=[_aged_epoch()])
    site_store.set_model_age_policy("site-a", max_age_days=1, actor="op", now=_NOW)

    assert lifecycle.sweep_staleness("site-a", now=_NOW) is SiteAdvanceOutcome.NO_RULE
    assert site_store.get("site-a").status is SiteStatus.UNMAPPED


def test_staleness_sweep_records_the_age_evidence(tmp_path: Any) -> None:
    """왜 낡았다고 판정했는지가 원장에 남는다 — 자율운영을 끊는 전이다."""
    import json

    lifecycle, site_store = _lifecycle_pair(tmp_path, records=[_aged_epoch()])
    _advance_site(site_store, SiteStatus.PATROL_READY)
    site_store.set_model_age_policy("site-a", max_age_days=30, actor="op", now=_NOW)

    lifecycle.sweep_staleness("site-a", now=_NOW)

    entries = [
        json.loads(line)
        for line in (tmp_path / "sites.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    last = [e for e in entries if e["kind"] == "site-transitioned"][-1]
    assert last["after"] == "MODEL_STALE"
    assert "j-aged" in last["evidence"]
    assert "maxAge=30d" in last["evidence"]


# --- 노후 스윕 표면 -----------------------------------------------------------


def _sweep_client(tmp_path: Any, *, records: list[ProcessingJobRecord] | None = None) -> Any:
    """조회 + 스윕 표면을 함께 장착한 조립(lifecycle 주입)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ksi_core.auth import (
        AuthRegistry,
        Principal,
        PrincipalKind,
        PrincipalTokenRecord,
        Role,
        mount_auth,
    )
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.sites import SiteStore, mount_sites
    from ksi_core.spatial_model import SpatialModelLifecycle, mount_spatial_model
    from ksi_mission_contracts.models import SiteFrame

    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    site_store.register(
        "site-a",
        "테스트 현장",
        SiteFrame.model_validate(
            {
                "crs": "EPSG:5186",
                "verticalDatum": "KNGeoid2018",
                "unit": "meter",
                "transformVersion": "1.0.0",
            }
        ),
        actor="op-1",
        now=_NOW,
    )
    jobs = _JobsStub(records or [])
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"sweep-admin").hexdigest(),
                principal=Principal(
                    principal_id="admin-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"sweep-viewer").hexdigest(),
                principal=Principal(
                    principal_id="viewer-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                ),
            ),
        ]
    )
    app = FastAPI()
    mount_auth(app, registry)
    mount_sites(app, site_store)
    mount_spatial_model(
        app,
        site_store=site_store,
        processing_job_store=jobs,
        lifecycle=SpatialModelLifecycle(site_store=site_store, processing_job_store=jobs),
    )
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer sweep-admin"})
    return client, site_store


def test_sweep_endpoint_moves_a_stale_patrol_ready_site(tmp_path: Any) -> None:
    client, site_store = _sweep_client(tmp_path, records=[_aged_epoch()])
    _advance_site(site_store, SiteStatus.PATROL_READY)
    site_store.set_model_age_policy("site-a", max_age_days=30, actor="op", now=_NOW)

    body = client.post("/v1/sites/site-a/spatial-model/staleness-sweep").json()

    assert body["state"] == "STALE"
    assert body["siteStatus"] == "MODEL_STALE"
    assert site_store.get("site-a").status is SiteStatus.MODEL_STALE


def test_sweep_endpoint_is_a_no_op_without_a_policy(tmp_path: Any) -> None:
    client, site_store = _sweep_client(tmp_path, records=[_aged_epoch()])
    _advance_site(site_store, SiteStatus.PATROL_READY)

    body = client.post("/v1/sites/site-a/spatial-model/staleness-sweep").json()

    assert body["state"] == "AGE_POLICY_UNDECLARED"
    assert site_store.get("site-a").status is SiteStatus.PATROL_READY


def test_read_endpoint_never_moves_the_site(tmp_path: Any) -> None:
    """[핵심] 조회는 원장을 바꾸지 않는다 — 스윕만 바꾼다.

    조회가 상태를 옮기면 현장 상태가 "누가 언제 화면을 열었는가"에 좌우된다.
    """
    client, site_store = _sweep_client(tmp_path, records=[_aged_epoch()])
    _advance_site(site_store, SiteStatus.PATROL_READY)
    site_store.set_model_age_policy("site-a", max_age_days=30, actor="op", now=_NOW)

    body = client.get("/v1/sites/site-a/spatial-model").json()

    assert body["state"] == "STALE"
    assert site_store.get("site-a").status is SiteStatus.PATROL_READY


def test_sweep_endpoint_requires_sites_write(tmp_path: Any) -> None:
    client, _ = _sweep_client(tmp_path)

    response = client.post(
        "/v1/sites/site-a/spatial-model/staleness-sweep",
        headers={"Authorization": "Bearer sweep-viewer"},
    )

    assert response.status_code == 403


def test_sweep_endpoint_is_404_for_unknown_site(tmp_path: Any) -> None:
    client, _ = _sweep_client(tmp_path)

    assert (
        client.post("/v1/sites/nope/spatial-model/staleness-sweep").status_code == 404
    )


def test_sweep_surface_is_absent_without_a_lifecycle(tmp_path: Any) -> None:
    """lifecycle 없이 장착하면 스윕 표면 자체가 없다 — 조용히 no-op 하지 않는다."""
    client, _ = _spatial_model_client(tmp_path)

    assert (
        client.post("/v1/sites/site-a/spatial-model/staleness-sweep").status_code == 405
        or client.post("/v1/sites/site-a/spatial-model/staleness-sweep").status_code == 404
    )
