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
from ksi_core.spatial_model import (
    SpatialModelState,
    evaluate_spatial_model,
    has_source_artifact,
    is_spatial_model_epoch,
)
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
        artifactId=f"{job_id}-{suffix}",
        jobId=job_id,
        kind=(
            ProcessingArtifactKind.POINT_CLOUD
            if authority is LineageAuthority.SOURCE
            else ProcessingArtifactKind.MESH
        ),
        lineage=ArtifactLineage(
            authority=authority,
            sourceDigest=_SOURCE_DIGEST,
            derivedFrom=[] if authority is LineageAuthority.SOURCE else [f"{job_id}-pc"],
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
