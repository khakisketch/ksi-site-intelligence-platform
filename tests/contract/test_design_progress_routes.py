"""계획 대비 진척(M4-C) — 두 리포트를 실제로 원장에 기록하고 라우터로 이어 뺀다.

``derive_progress`` 의 뺄셈 규칙 자체는 ``test_design_progress.py`` 가 순수
함수로 이미 고정했다. 이 파일은 그 규칙이 **실제 요청→lease→래스터 업로드→
Core 재해싱→리포트 기록** 전 구간을 거친 두 리포트에도 그대로 성립하는지,
그리고 원지형 기준 지정·진척 조회 HTTP 표면이 그 결과를 정확히 옮기는지를
본다(green≠작동 — `test_design_conformance_reports.py` 와 같은 규율).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import mount_auth
from ksi_core.design_conformance_reports import (
    DesignConformanceStore,
    DesignConformanceVerdict,
    mount_design_conformance_reports,
)
from ksi_core.design_conformance_requests import (
    DesignConformanceRequestVerdict,
    mount_design_conformance_requests,
    recompute_diff_raster_digest,
)
from ksi_core.design_progress import mount_design_progress
from ksi_core.durable_journal import DurableJournal
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.design_conformance_report import (
    DesignConformanceReport,
    DesignSurfaceRef,
    DiffRasterRef,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from ksi_event_contracts.volume_change_report import ZoneVolumeDelta

# tests/contract 는 rootdir 기반 수집이라 같은 디렉터리 모듈을 직접 import 한다.
from test_comparison_requests import (  # noqa: E402
    _ADMIN_TOKEN,
    _CURRENT_MISSION_ID,
    _SITE_ID,
    _artifact_spec,
    _registry,
    _succeeded_job,
)
from test_design_conformance_requests import _ZONE_CRS, Fixture  # noqa: E402

_PIPELINE_VERTICAL = VerticalReference(
    datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
    basis="현재 DSM 과 설계면의 표고차 격자 — 실측된 현재 DSM 의 기준을 승계한다",
    source=VerticalReferenceSource.PIPELINE_DECLARED,
)
_DSM_VERTICAL = VerticalReference(
    datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
    basis="ODM 이 RTK 타원체고를 변환 없이 그대로 출력",
    source=VerticalReferenceSource.PIPELINE_DECLARED,
)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class ProgressFixture:
    """작업구역과 같은 zoneId("zone-a")로 낸 두 개의 실제 리포트 — 기준·최신."""

    def __init__(self, tmp_path: Path) -> None:
        self.base = Fixture(tmp_path)
        self.report_journal = DurableJournal(tmp_path / "design-conformance.jsonl")
        self.reports = DesignConformanceStore(
            self.report_journal,
            mission_store=self.base.missions,
            processing_job_store=self.base.jobs,
            request_store=self.base.requests,
            storage=self.base.storage,
        )
        # 최신 epoch 을 낼 두 번째 DSM 작업 — 같은 임무, 다른 jobId.
        self.latest_job_id = _succeeded_job(
            self.base.jobs,
            self.base.source_media,
            _CURRENT_MISSION_ID,
            _artifact_spec("point-cloud-2"),
            _artifact_spec(
                "dsm-2", kind=ProcessingArtifactKind.DSM, vertical_reference=_DSM_VERTICAL
            ),
        )
        # 세 번째 epoch — "기록 순서 vs 계산 시각이 갈리는" 시나리오 전용.
        self.third_job_id = _succeeded_job(
            self.base.jobs,
            self.base.source_media,
            _CURRENT_MISSION_ID,
            _artifact_spec("point-cloud-3"),
            _artifact_spec(
                "dsm-3", kind=ProcessingArtifactKind.DSM, vertical_reference=_DSM_VERTICAL
            ),
        )

    def submit(
        self,
        *,
        current_job_id: str,
        cut_m3: float,
        fill_m3: float,
        raster: bytes,
        computed_at: datetime | None = None,
        area_m2: float = 400.0,
    ) -> DesignConformanceReport:
        """요청 생성 → lease → RUNNING → 래스터 업로드 → Core 재해싱 확인 → 리포트 기록."""
        created = self.base.create(
            current_job_id=current_job_id, zones={"zone-a": _POLYGON}, zone_crs=_ZONE_CRS
        )
        assert created.verdict is DesignConformanceRequestVerdict.CREATED, created
        record = created.record
        assert record is not None
        self.base.leased(record.request_id)
        self.base.running(record.request_id)
        object_key = self.base.upload_raster(record, raster)
        digest, size = recompute_diff_raster_digest(self.base.storage, object_key)
        artifact_id = {self.latest_job_id: "dsm-2", self.third_job_id: "dsm-3"}.get(
            current_job_id, "dsm"
        )
        verified = self.base.requests.record_diff_raster_verification(
            record.request_id,
            digest=digest,
            size_bytes=size,
            worker_id="worker-1",
            now=datetime.now(UTC),
        )
        assert verified.verdict is DesignConformanceRequestVerdict.DIFF_RASTER_VERIFIED
        assert verified.record is not None and verified.record.diff_raster is not None
        diff_raster = verified.record.diff_raster
        report = DesignConformanceReport(
            design_conformance_id=record.design_conformance_id,
            design_surface_ref=DesignSurfaceRef(
                design_surface_id=record.design_surface_id,
                sha256=record.design_surface_sha256,
            ),
            current=ArtifactRef(job_id=current_job_id, artifact_id=artifact_id),
            crs="EPSG:5186",
            vertical_reference=_PIPELINE_VERTICAL,
            zones=[
                ZoneVolumeDelta(
                    zone_id="zone-a",
                    cut_m3=cut_m3,
                    fill_m3=fill_m3,
                    net_m3=fill_m3 - cut_m3,
                    area_m2=area_m2,
                    threshold_m=record.policy.volume_threshold_m,
                    uncertainty_m3=None,
                    uncertainty_note="설계면은 측정물이 아니라 검사점 RMSE 가 없다",
                )
            ],
            policy=record.policy,
            diff_raster=DiffRasterRef(
                diff_raster_id=record.diff_raster_id,
                digest=diff_raster.digest,
                crs="EPSG:5186",
                vertical_reference=_PIPELINE_VERTICAL,
                width=20,
                height=20,
                pixel_size_x_m=1.0,
                pixel_size_y_m=1.0,
                transform=(1.0, 0.0, 200000.0, 0.0, -1.0, 550000.0),
                threshold_m=record.policy.volume_threshold_m,
                size_bytes=diff_raster.size_bytes,
                core_verified_digest_at=diff_raster.verified_at,
            ),
            computed_at=computed_at or datetime.now(UTC),
        )
        outcome = self.reports.record(
            _CURRENT_MISSION_ID, report, now=datetime.now(UTC), reported_by="worker-1"
        )
        assert outcome.verdict is DesignConformanceVerdict.RECORDED, outcome
        return report

    def app(self) -> FastAPI:
        app = FastAPI()
        mount_auth(app, _registry())
        mount_design_conformance_requests(app, self.base.requests, self.base.storage)
        mount_design_conformance_reports(app, self.reports, self.base.storage)
        mount_design_progress(app, self.reports)
        return app

    def close(self) -> None:
        self.report_journal.close()
        self.base.close()


_POLYGON = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


@pytest.fixture
def progress(tmp_path: Path) -> ProgressFixture:
    return ProgressFixture(tmp_path)


def test_progress_is_unavailable_before_a_baseline_is_set(progress: ProgressFixture) -> None:
    baseline = progress.submit(
        current_job_id=progress.base.current_job_id, cut_m3=5000.0, fill_m3=0.0, raster=b"a"
    )
    del baseline
    client = TestClient(progress.app())
    response = client.get(
        f"/v1/sites/{_SITE_ID}/design-progress",
        params={"design_surface_id": progress.base.design_surface_id},
        headers=_auth(_ADMIN_TOKEN),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["progress"] is None
    assert "기준" in body["detail"]


def test_setting_the_baseline_then_reading_progress_matches_hand_calculation(
    progress: ProgressFixture,
) -> None:
    """계획 5000 절토 / 잔여 1240 → 완료 3760 · 75.2% — HTTP 종단으로 재확인."""
    baseline = progress.submit(
        current_job_id=progress.base.current_job_id, cut_m3=5000.0, fill_m3=0.0, raster=b"raster-a"
    )
    latest = progress.submit(
        current_job_id=progress.latest_job_id, cut_m3=1240.0, fill_m3=0.0, raster=b"raster-b"
    )
    client = TestClient(progress.app())

    baseline_set = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance/{baseline.design_conformance_id}/progress-baseline",
        json={"designSurfaceId": progress.base.design_surface_id},
        headers=_auth(_ADMIN_TOKEN),
    )
    assert baseline_set.status_code == 201, baseline_set.json()

    response = client.get(
        f"/v1/sites/{_SITE_ID}/design-progress",
        params={"design_surface_id": progress.base.design_surface_id},
        headers=_auth(_ADMIN_TOKEN),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["detail"] is None
    zone = body["progress"]["zones"][0]
    assert zone["plannedCutM3"] == pytest.approx(5000.0)
    assert zone["remainingCutM3"] == pytest.approx(1240.0)
    assert zone["doneCutM3"] == pytest.approx(3760.0)
    assert zone["cutProgressRatio"] == pytest.approx(0.752)
    assert body["latestMissionId"] == _CURRENT_MISSION_ID
    assert body["progress"]["latestDesignConformanceId"] == latest.design_conformance_id


def test_design_revision_mismatch_blocks_quantitative_progress(
    progress: ProgressFixture,
) -> None:
    baseline = progress.submit(
        current_job_id=progress.base.current_job_id,
        cut_m3=5000.0,
        fill_m3=0.0,
        raster=b"baseline",
    )
    latest = progress.submit(
        current_job_id=progress.latest_job_id,
        cut_m3=1240.0,
        fill_m3=0.0,
        raster=b"latest",
    )
    latest_request = progress.base.requests.get_by_design_conformance_id(
        latest.design_conformance_id
    )
    assert latest_request is not None
    # Deliberate in-memory corruption of the projection: the route must still
    # refuse to derive a number when the two immutable design anchors differ.
    progress.base.requests._requests[latest_request.request_id] = replace(  # noqa: SLF001
        latest_request,
        design_surface_revision="Rev.changed",
    )

    client = TestClient(progress.app())
    baseline_set = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance/"
        f"{baseline.design_conformance_id}/progress-baseline",
        json={"designSurfaceId": progress.base.design_surface_id},
        headers=_auth(_ADMIN_TOKEN),
    )
    assert baseline_set.status_code == 201

    response = client.get(
        f"/v1/sites/{_SITE_ID}/design-progress",
        params={"design_surface_id": progress.base.design_surface_id},
        headers=_auth(_ADMIN_TOKEN),
    )

    assert response.status_code == 200
    assert response.json()["progress"] is None
    assert response.json()["reason"] == "DESIGN_NORMALIZATION_MISMATCH"


def test_area_mismatch_is_serialized_over_http_not_just_the_pure_function(
    progress: ProgressFixture,
) -> None:
    """areaMismatchZoneIds 가 요청→lease→래스터→Core 재해싱을 실제로 거친 뒤에도 살아남는다.

    ``test_design_progress.py`` 가 순수 함수로 이미 고정한 규칙(2026-08-13 프로젝트
    두뇌 재감사 확정 발견의 회귀 방지)이 라우터 직렬화까지 그대로 옮겨지는지 —
    필드 이름 하나만 틀려도 화면은 빈 배열을 받고 아무 경고도 못 낸다.
    """
    baseline = progress.submit(
        current_job_id=progress.base.current_job_id,
        cut_m3=5000.0,
        fill_m3=0.0,
        raster=b"raster-a",
        area_m2=400.0,
    )
    progress.submit(
        current_job_id=progress.latest_job_id,
        cut_m3=1000.0,
        fill_m3=0.0,
        raster=b"raster-b",
        area_m2=100.0,  # 기준의 25% — 10% 문턱을 크게 넘는다
    )
    client = TestClient(progress.app())

    baseline_set = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance/{baseline.design_conformance_id}/progress-baseline",
        json={"designSurfaceId": progress.base.design_surface_id},
        headers=_auth(_ADMIN_TOKEN),
    )
    assert baseline_set.status_code == 201, baseline_set.json()

    response = client.get(
        f"/v1/sites/{_SITE_ID}/design-progress",
        params={"design_surface_id": progress.base.design_surface_id},
        headers=_auth(_ADMIN_TOKEN),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["progress"] is None
    assert body["areaMismatchZoneIds"] == ["zone-a"]
    assert body["detail"] is not None and "측정 면적" in body["detail"]


def test_baseline_from_a_different_design_surface_is_rejected(
    progress: ProgressFixture,
) -> None:
    baseline = progress.submit(
        current_job_id=progress.base.current_job_id, cut_m3=5000.0, fill_m3=0.0, raster=b"c"
    )
    client = TestClient(progress.app())
    response = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance/{baseline.design_conformance_id}/progress-baseline",
        json={"designSurfaceId": "다른-설계면"},
        headers=_auth(_ADMIN_TOKEN),
    )
    assert response.status_code == 409
    assert "다른 설계면" in response.json()["detail"]


def test_unknown_report_cannot_be_set_as_baseline(progress: ProgressFixture) -> None:
    client = TestClient(progress.app())
    response = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance/dc-없음/progress-baseline",
        json={"designSurfaceId": progress.base.design_surface_id},
        headers=_auth(_ADMIN_TOKEN),
    )
    assert response.status_code == 404


# ── "최신"은 기록 순서가 아니라 계산 시각으로 고른다 (독립 검토 2026-08-13 지적) ──


def test_latest_report_is_chosen_by_computed_time_not_recording_order(
    progress: ProgressFixture,
) -> None:
    """기록은 T2(3번째 job)가 T3(2번째 job)보다 나중이지만, 계산 시각은 반대다.

    사람이 지난 epoch 를 다시 계산해 나중에 제출하면(1주차 재검산을 3주차 제출
    이후에 하는 식) 원장에 쌓이는 순서와 계산 시각 순서가 갈린다. 원장 append
    순서로 "최신"을 고르면 이 재검산이 조용히 최신으로 뽑힌다 — 계산 시각으로
    골라야 실제로 더 나중 지형을 가리킨다.
    """
    t1 = datetime(2026, 8, 1, tzinfo=UTC)
    t2 = datetime(2026, 8, 10, tzinfo=UTC)  # 계산은 나중(진짜 최신이어야 함)
    t3 = datetime(2026, 8, 5, tzinfo=UTC)  # 계산은 더 이르지만 원장엔 나중에 기록됨

    baseline = progress.submit(
        current_job_id=progress.base.current_job_id,
        cut_m3=5000.0,
        fill_m3=0.0,
        raster=b"t1",
        computed_at=t1,
    )
    really_latest = progress.submit(
        current_job_id=progress.latest_job_id,
        cut_m3=2000.0,
        fill_m3=0.0,
        raster=b"t2",
        computed_at=t2,
    )
    recorded_after_but_computed_earlier = progress.submit(
        current_job_id=progress.third_job_id,
        cut_m3=4000.0,
        fill_m3=0.0,
        raster=b"t3",
        computed_at=t3,
    )
    del recorded_after_but_computed_earlier

    client = TestClient(progress.app())
    baseline_set = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance/{baseline.design_conformance_id}/progress-baseline",
        json={"designSurfaceId": progress.base.design_surface_id},
        headers=_auth(_ADMIN_TOKEN),
    )
    assert baseline_set.status_code == 201, baseline_set.json()

    response = client.get(
        f"/v1/sites/{_SITE_ID}/design-progress",
        params={"design_surface_id": progress.base.design_surface_id},
        headers=_auth(_ADMIN_TOKEN),
    )
    body = response.json()
    assert body["detail"] is None, body
    assert (
        body["progress"]["latestDesignConformanceId"] == really_latest.design_conformance_id
    )
    assert body["progress"]["zones"][0]["remainingCutM3"] == pytest.approx(2000.0)


def test_a_report_computed_before_the_baseline_is_refused_as_latest(
    progress: ProgressFixture,
) -> None:
    """진척은 기준 이후 시점에 대해서만 말이 된다 — 시간이 거꾸로면 typed 거부."""
    baseline = progress.submit(
        current_job_id=progress.base.current_job_id,
        cut_m3=5000.0,
        fill_m3=0.0,
        raster=b"later",
        computed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    progress.submit(
        current_job_id=progress.latest_job_id,
        cut_m3=4000.0,
        fill_m3=0.0,
        raster=b"earlier",
        computed_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    client = TestClient(progress.app())
    baseline_set = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance/{baseline.design_conformance_id}/progress-baseline",
        json={"designSurfaceId": progress.base.design_surface_id},
        headers=_auth(_ADMIN_TOKEN),
    )
    assert baseline_set.status_code == 201, baseline_set.json()

    response = client.get(
        f"/v1/sites/{_SITE_ID}/design-progress",
        params={"design_surface_id": progress.base.design_surface_id},
        headers=_auth(_ADMIN_TOKEN),
    )
    body = response.json()
    assert body["progress"] is None
    assert "앞서거나 같다" in body["detail"]
