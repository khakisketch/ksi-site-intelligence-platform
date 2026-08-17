"""변화 영역 추출 **리포트** 원장 + 재관찰 초안 핸드오프 계약 (M4-E).

초점 넷:

**① 판정은 순수 값 대조다** — 바이트 재해싱이 없다(``design_conformance_
reports.py`` 와 달리, 이미 확인된 diffRaster 를 다시 읽을 뿐이다). 요청 존재·
소속·designConformanceId 일치·crs/threshold 일치·정책 일치를 본다.

**② 정책 대조는 요청 시점 스냅샷이 아니라 지금 이 순간의 ``current_region_
extraction_policy()`` 다**(policy-owned 기반안).

**③ 멱등 + 중복 id 거부** — design_conformance_reports.py 와 같은 패턴.

**④ 재관찰 초안 핸드오프** — hull 이 있으면 실제 ``AreaOfInterest`` 를 만들어
돌려주고, 없으면 409 로 명시한다. "발급됨" 상태는 없다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import mount_auth
from ksi_core.durable_journal import DurableJournal
from ksi_core.region_extraction_reports import (
    RegionExtractionRecoveryError,
    RegionExtractionStore,
    RegionExtractionVerdict,
    mount_region_extraction,
)
from ksi_core.region_extraction_requests import mount_region_extraction_requests
from ksi_event_contracts.change_region_report import ChangeRegion, ChangeRegionSetReport
from ksi_event_contracts.region_extraction_policy import current_region_extraction_policy
from ksi_event_contracts.volume_change_report import ZoneVolumeDelta

# tests/contract 는 rootdir 기반 수집이라 같은 디렉터리 모듈을 직접 import 한다.
from test_comparison_requests import _CURRENT_MISSION_ID, _OTHER_MISSION_ID, _registry  # noqa: E402
from test_region_extraction_requests import Fixture as RequestFixture  # noqa: E402

_ADMIN_TOKEN = "cmp-admin-token"  # noqa: S105
_WORKER_TOKEN = "cmp-worker-token"  # noqa: S105
_VIEWER_TOKEN = "cmp-viewer-token"  # noqa: S105

# 유효한 소볼록 WGS84 사각형 — AreaOfInterest 가 받아들이는 범위(극지·10km 제한 안).
_HULL_WGS84 = {
    "type": "Polygon",
    "coordinates": [
        [
            [127.0000, 37.5000],
            [127.0010, 37.5000],
            [127.0010, 37.5010],
            [127.0000, 37.5010],
            [127.0000, 37.5000],
        ]
    ],
}
_HULL_NATIVE = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]],
}
# 동서로 약 44km(경도 0.5도 × 이 위도의 km/도) — AreaOfInterest 의 anchor 기준
# 10km 제한을 실제로 넘는 값. "볼록 껍질이 있으면 항상 유효한 AOI 가 나온다"는
# 암묵적 전제를 깨는 자리를 고정한다(2026-08-14 독립 검토가 스크래치 스크립트로
# 확인했던 것을 회귀 테스트로 옮김).
_HULL_WGS84_TOO_WIDE = {
    "type": "Polygon",
    "coordinates": [
        [
            [127.0000, 37.5000],
            [127.5000, 37.5000],
            [127.5000, 37.5010],
            [127.0000, 37.5010],
            [127.0000, 37.5000],
        ]
    ],
}
# 구조가 깨진 hull — "coordinates" 자체가 없다. 저장 시점엔 구조 검증이 없는
# dict[str, Any] 라 이런 값도 그대로 실릴 수 있다 — KeyError/IndexError/
# TypeError 가 새 500 이 아니라 다른 hull 결함과 같은 422 로 나와야 한다.
_HULL_WGS84_MALFORMED = {"type": "Polygon"}


def _volume(*, threshold_m: float, region_id: str = "r-1") -> ZoneVolumeDelta:
    return ZoneVolumeDelta(
        zone_id=region_id,
        cut_m3=3.0,
        fill_m3=1.0,
        net_m3=-2.0,
        area_m2=4.0,
        threshold_m=threshold_m,
        uncertainty_m3=None,
        uncertainty_note="설계 대비 잔량 diffRaster 에서 파생됐다 — 오차한계가 없다",
    )


def _region(
    *,
    threshold_m: float,
    region_id: str = "r-1",
    with_hull: bool = True,
    hull_wgs84: dict[str, Any] = _HULL_WGS84,
) -> ChangeRegion:
    return ChangeRegion(
        region_id=region_id,
        volume=_volume(threshold_m=threshold_m, region_id=region_id),
        pixel_count=4,
        polygon=_HULL_NATIVE,
        convex_hull_polygon=_HULL_NATIVE if with_hull else None,
        convex_hull_polygon_wgs84=hull_wgs84 if with_hull else None,
        hull_overcapture_ratio=1.0 if with_hull else None,
        aoi_draft_unavailable_reason=None if with_hull else "HULL_CONSISTENCY_CHECK_FAILED",
        unmeasurable_ratio=0.0,
    )


class Fixture:
    """요청 픽스처(RECORDED 설계 대비 잔량 + CREATED 요청) + 리포트 원장."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.request_fixture = RequestFixture(tmp_path)
        self.journal = DurableJournal(tmp_path / "region-extraction.jsonl")
        self.reports = RegionExtractionStore(
            self.journal,
            mission_store=self.request_fixture.report_fixture.base.missions,
            request_store=self.request_fixture.requests,
            design_conformance_report_store=self.request_fixture.report_fixture.reports,
        )

    def request(self, **overrides: Any) -> Any:
        """CREATED 상태의 변화 영역 추출 요청 — designConformanceId 는 실제 RECORDED."""
        return self.request_fixture.created(**overrides)

    def valid_report(
        self,
        request: Any,
        *,
        with_hull: bool = True,
        hull_wgs84: dict[str, Any] = _HULL_WGS84,
    ) -> ChangeRegionSetReport:
        entry = self.request_fixture.report_fixture.reports.get(
            request.mission_id, request.design_conformance_id
        )
        assert entry is not None
        threshold_m = entry.report.diff_raster.threshold_m
        return ChangeRegionSetReport(
            change_region_set_id=request.change_region_set_id,
            design_conformance_id=request.design_conformance_id,
            diff_raster_id=entry.report.diff_raster.diff_raster_id,
            crs=entry.report.crs,
            threshold_m=threshold_m,
            extraction_policy=current_region_extraction_policy(),
            regions=[
                _region(threshold_m=threshold_m, with_hull=with_hull, hull_wgs84=hull_wgs84)
            ],
            filtered_region_count=0,
            unmeasurable_cell_ratio=0.0,
            unmeasurable_area_m2=0.0,
            total_cell_count=100,
            computed_at=datetime.now(UTC),
        )

    def app(self) -> FastAPI:
        app = FastAPI()
        mount_auth(app, _registry())
        mount_region_extraction_requests(
            app,
            self.request_fixture.requests,
            self.request_fixture.report_fixture.reports,
            self.request_fixture.report_fixture.base.storage,
        )
        mount_region_extraction(app, self.reports)
        return app

    def close(self) -> None:
        self.journal.close()
        self.request_fixture.close()


@pytest.fixture
def fixture(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── 정상 제출 + 멱등 ───────────────────────────────────────────────────────


def test_a_valid_report_is_recorded(fixture: Fixture) -> None:
    request = fixture.request()
    report = fixture.valid_report(request)
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert outcome.verdict is RegionExtractionVerdict.RECORDED, outcome

    entry = fixture.reports.get(_CURRENT_MISSION_ID, request.change_region_set_id)
    assert entry is not None
    assert entry.report.regions[0].region_id == "r-1"


def test_resubmitting_the_same_report_is_idempotent(fixture: Fixture) -> None:
    request = fixture.request()
    report = fixture.valid_report(request)
    fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    again = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert again.verdict is RegionExtractionVerdict.RECORDED
    assert again.detail is not None and "멱등" in again.detail
    assert len(fixture.reports.list_for_mission(_CURRENT_MISSION_ID)) == 1


def test_same_id_with_different_content_is_a_duplicate(fixture: Fixture) -> None:
    request = fixture.request()
    first = fixture.valid_report(request)
    fixture.reports.record(_CURRENT_MISSION_ID, first, now=datetime.now(UTC))
    second = first.model_copy(update={"computed_at": datetime.now(UTC) + timedelta(hours=1)})
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, second, now=datetime.now(UTC))
    assert outcome.verdict is RegionExtractionVerdict.DUPLICATE_REPORT_ID


# ── 판정 게이트 ───────────────────────────────────────────────────────────


def test_unknown_mission_is_refused(fixture: Fixture) -> None:
    request = fixture.request()
    report = fixture.valid_report(request)
    outcome = fixture.reports.record("mission-does-not-exist", report, now=datetime.now(UTC))
    assert outcome.verdict is RegionExtractionVerdict.UNKNOWN_MISSION


def test_a_report_without_a_backing_request_is_refused(fixture: Fixture) -> None:
    request = fixture.request()
    report = fixture.valid_report(request).model_copy(
        update={"change_region_set_id": "no-such-request-rex1"}
    )
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert outcome.verdict is RegionExtractionVerdict.UNKNOWN_REQUEST


def test_a_report_submitted_to_another_mission_is_refused(fixture: Fixture) -> None:
    request = fixture.request()
    report = fixture.valid_report(request)
    outcome = fixture.reports.record(_OTHER_MISSION_ID, report, now=datetime.now(UTC))
    assert outcome.verdict is RegionExtractionVerdict.REQUEST_MISMATCH


def test_a_report_pointing_at_another_design_conformance_is_refused(fixture: Fixture) -> None:
    request = fixture.request()
    report = fixture.valid_report(request).model_copy(
        update={"design_conformance_id": "some-other-dcf"}
    )
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert outcome.verdict is RegionExtractionVerdict.DESIGN_CONFORMANCE_MISMATCH


def test_a_report_with_a_different_crs_is_refused(fixture: Fixture) -> None:
    request = fixture.request()
    report = fixture.valid_report(request).model_copy(update={"crs": "EPSG:5179"})
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert outcome.verdict is RegionExtractionVerdict.CRS_MISMATCH


def test_a_report_with_a_different_threshold_is_refused(fixture: Fixture) -> None:
    request = fixture.request()
    entry = fixture.request_fixture.report_fixture.reports.get(
        request.mission_id, request.design_conformance_id
    )
    assert entry is not None
    other_threshold = entry.report.diff_raster.threshold_m + 0.5
    report = fixture.valid_report(request).model_copy(
        update={
            "threshold_m": other_threshold,
            "regions": [_region(threshold_m=other_threshold)],
        }
    )
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert outcome.verdict is RegionExtractionVerdict.THRESHOLD_MISMATCH


def test_a_report_computed_with_another_extraction_policy_is_refused(fixture: Fixture) -> None:
    """정책 대조는 요청 시점 스냅샷이 아니라 지금 이 순간의 값이다(policy-owned)."""
    request = fixture.request()
    other_policy = current_region_extraction_policy().model_copy(
        update={"min_region_area_m2": current_region_extraction_policy().min_region_area_m2 + 5}
    )
    report = fixture.valid_report(request).model_copy(update={"extraction_policy": other_policy})
    outcome = fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    assert outcome.verdict is RegionExtractionVerdict.EXTRACTION_POLICY_MISMATCH


# ── HTTP 조회 표면 ────────────────────────────────────────────────────────


def test_missing_history_is_404_not_an_empty_list(fixture: Fixture) -> None:
    client = TestClient(fixture.app())
    response = client.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction", headers=_auth(_VIEWER_TOKEN)
    )
    assert response.status_code == 404


def test_http_submit_and_list(fixture: Fixture) -> None:
    request = fixture.request()
    report = fixture.valid_report(request)
    client = TestClient(fixture.app())

    submitted = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction",
        json=report.model_dump(by_alias=True, mode="json"),
        headers=_auth(_WORKER_TOKEN),
    )
    assert submitted.status_code == 201, submitted.json()
    assert submitted.json()["verdict"] == "RECORDED"

    listed = client.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction", headers=_auth(_VIEWER_TOKEN)
    )
    assert listed.status_code == 200
    assert listed.json()["reportCount"] == 1

    got = client.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction/{request.change_region_set_id}",
        headers=_auth(_VIEWER_TOKEN),
    )
    assert got.status_code == 200
    assert got.json()["report"]["changeRegionSetId"] == request.change_region_set_id


def test_people_cannot_submit_and_workers_cannot_read(fixture: Fixture) -> None:
    request = fixture.request()
    report = fixture.valid_report(request)
    client = TestClient(fixture.app())
    assert (
        client.post(
            f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction",
            json=report.model_dump(by_alias=True, mode="json"),
            headers=_auth(_VIEWER_TOKEN),
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction", headers=_auth(_WORKER_TOKEN)
        ).status_code
        == 403
    )


# ── 재관찰 초안 핸드오프 ──────────────────────────────────────────────────


def test_spatial_refresh_draft_returns_a_real_area_of_interest(fixture: Fixture) -> None:
    request = fixture.request()
    report = fixture.valid_report(request)
    fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    client = TestClient(fixture.app())

    response = client.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction/"
        f"{request.change_region_set_id}/regions/r-1/spatial-refresh-draft",
        headers=_auth(_VIEWER_TOKEN),
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["verdict"] == "DRAFT_READY"
    assert len(body["aoi"]["vertices"]) == 4
    assert body["hullOvercaptureRatio"] == pytest.approx(1.0)
    assert body["regionAreaM2"] == pytest.approx(4.0)
    assert body["netM3"] == pytest.approx(-2.0)
    assert body["cutM3"] == pytest.approx(3.0)
    assert body["fillM3"] == pytest.approx(1.0)
    assert body["unmeasurableRatio"] == pytest.approx(0.0)
    assert body["siteUnmeasurableCellRatio"] == pytest.approx(0.0)
    # "발급됨" 상태가 아니다 — 임무 발급 관련 필드가 없다.
    assert "missionId" not in body


def test_spatial_refresh_draft_without_a_baseline_says_why_instead_of_guessing(
    fixture: Fixture,
) -> None:
    """[핵심] 직전 촬영 조건을 모르면 지어내지 않는다(ADR-KSI-019 G5).

    이 fixture 의 임무(``_CURRENT_MISSION_ID``)는 계약 단독 발급
    (``artifactKind="contract"``)이라 ``planRequest`` 가 없어 고도·중복도·카메라를
    알 수 없다. 그때 기본값을 꽂으면 그 값이 어디서 왔는지 아무도 모르는 채로
    비행 계획이 된다 — ``ChangeRegion.aoi_draft_unavailable_reason`` 이 hull 실패를
    다루는 방식과 같은 관용구로 사유를 낸다.
    """
    request = fixture.request()
    report = fixture.valid_report(request)
    fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    client = TestClient(fixture.app())

    response = client.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction/"
        f"{request.change_region_set_id}/regions/r-1/spatial-refresh-draft",
        headers=_auth(_VIEWER_TOKEN),
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["verdict"] == "DRAFT_READY"
    assert body["aoi"] is not None  # AOI 는 여전히 나온다 — 촬영 계획만 모른다
    assert body["captureGrade"] is None
    assert body["captureAltitudeM"] is None
    assert body["captureUnavailableReason"] == "BASELINE_CAPTURE_UNKNOWN"
    assert body["captureRationale"] == []


def test_spatial_refresh_draft_is_explicit_when_the_hull_is_unavailable(
    fixture: Fixture,
) -> None:
    request = fixture.request()
    report = fixture.valid_report(request, with_hull=False)
    fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    client = TestClient(fixture.app())

    response = client.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction/"
        f"{request.change_region_set_id}/regions/r-1/spatial-refresh-draft",
        headers=_auth(_VIEWER_TOKEN),
    )
    assert response.status_code == 409
    assert "초안을 만들 수 없다" in response.json()["detail"]


def test_spatial_refresh_draft_rejects_an_aoi_wider_than_the_10km_gate(
    fixture: Fixture,
) -> None:
    """[회귀] hull 이 있어도 AreaOfInterest 자체의 게이트(10km)에 걸리면 422 다.

    hull 이 볼록이라 자기교차는 원천적으로 못 내지만, anchor 기준 10km 제한은
    큰 부지에서 실제로 도달 가능하다 — "hull 이 있으면 항상 초안이 나온다"고
    조용히 믿으면 안 된다는 것을 회귀로 고정한다(2026-08-14 독립 검토 발견).
    """
    request = fixture.request()
    report = fixture.valid_report(request, hull_wgs84=_HULL_WGS84_TOO_WIDE)
    fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    client = TestClient(fixture.app())

    response = client.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction/"
        f"{request.change_region_set_id}/regions/r-1/spatial-refresh-draft",
        headers=_auth(_VIEWER_TOKEN),
    )
    assert response.status_code == 422, response.json()


def test_spatial_refresh_draft_422s_for_a_structurally_malformed_hull(
    fixture: Fixture,
) -> None:
    """[회귀] hull 이 있어도 구조가 깨졌으면(coordinates 없음 등) 422 다, 500 이 아니다.

    ``convex_hull_polygon_wgs84`` 는 구조 검증 없는 ``dict[str, Any]`` 라
    기록 시점에 이런 값도 그대로 저장될 수 있다 — ``_aoi_from_hull_wgs84`` 가
    ``KeyError``/``IndexError``/``TypeError`` 를 그대로 새게 두면 다른 hull
    결함(10km 초과 등)과 달리 unhandled 500 이 된다.
    """
    request = fixture.request()
    report = fixture.valid_report(request, hull_wgs84=_HULL_WGS84_MALFORMED)
    fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    client = TestClient(fixture.app())

    response = client.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction/"
        f"{request.change_region_set_id}/regions/r-1/spatial-refresh-draft",
        headers=_auth(_VIEWER_TOKEN),
    )
    assert response.status_code == 422, response.json()


def test_spatial_refresh_draft_404s_for_an_unknown_region(fixture: Fixture) -> None:
    request = fixture.request()
    report = fixture.valid_report(request)
    fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    client = TestClient(fixture.app())

    response = client.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction/"
        f"{request.change_region_set_id}/regions/no-such-region/spatial-refresh-draft",
        headers=_auth(_VIEWER_TOKEN),
    )
    assert response.status_code == 404


def test_spatial_refresh_draft_404s_for_an_unknown_report(fixture: Fixture) -> None:
    client = TestClient(fixture.app())
    response = client.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction/"
        "no-such-set/regions/r-1/spatial-refresh-draft",
        headers=_auth(_VIEWER_TOKEN),
    )
    assert response.status_code == 404


# ── 재생 ──────────────────────────────────────────────────────────────────


def _reopen(fixture: Fixture) -> RegionExtractionStore:
    fixture.journal.close()
    return RegionExtractionStore(
        DurableJournal(fixture.tmp_path / "region-extraction.jsonl"),
        mission_store=fixture.request_fixture.report_fixture.base.missions,
        request_store=fixture.request_fixture.requests,
        design_conformance_report_store=fixture.request_fixture.report_fixture.reports,
    )


def test_replay_restores_recorded_reports_and_skips_rejections(fixture: Fixture) -> None:
    request = fixture.request()
    good = fixture.valid_report(request)
    fixture.reports.record(
        _CURRENT_MISSION_ID,
        good.model_copy(update={"crs": "EPSG:5179"}),
        now=datetime.now(UTC),
    )
    fixture.reports.record(_CURRENT_MISSION_ID, good, now=datetime.now(UTC))

    replayed = _reopen(fixture)
    entries = replayed.list_for_mission(_CURRENT_MISSION_ID)
    assert [e.report.change_region_set_id for e in entries] == [request.change_region_set_id]


def test_replay_refuses_unknown_record_kinds(fixture: Fixture) -> None:
    request = fixture.request()
    report = fixture.valid_report(request)
    fixture.reports.record(_CURRENT_MISSION_ID, report, now=datetime.now(UTC))
    path = fixture.tmp_path / "region-extraction.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "made-up", "missionId": "x"}\n')
    with pytest.raises(RegionExtractionRecoveryError, match="알 수 없는 journal"):
        _reopen(fixture)
