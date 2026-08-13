"""작업구역(M4-C)이 설계 대비 잔량 요청의 zones 를 실제로 대체하는지 — 종단 배선.

이 파일이 지키는 문장: :meth:`WorkAreaStore.resolve_zones` 를 통과한 뒤로는
``DesignConformanceRequestStore`` 가 폴리곤 **값**만 보고, 요청 레코드의
``zones``/``zoneCrs`` 는 즉석으로 그린 것과 완전히 같은 모양이 된다 — 그래야
기존 워커·계약이 한 줄도 안 바뀐다는 M4-C 방향 결정이 실제로 성립한다.

``test_design_conformance_requests.py`` 의 :class:`Fixture`(VERIFIED 설계면 +
SUCCEEDED DSM 작업 + site/mission store)를 그대로 재사용하고, 요청 저장소만
``work_area_store`` 를 아는 것으로 다시 만든다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import mount_auth
from ksi_core.design_conformance_requests import (
    DesignConformanceRequestStore,
    DesignConformanceRequestVerdict,
    mount_design_conformance_requests,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.work_areas import WorkAreaStore, WorkAreaVerdict

# tests/contract 는 rootdir 기반 수집이라 같은 디렉터리 모듈을 직접 import 한다
# (test_design_conformance_requests.py 가 test_comparison_requests 를 쓰는 것과 같은 관용구).
from test_comparison_requests import (  # noqa: E402
    _ADMIN_TOKEN,
    _CURRENT_MISSION_ID,
    _NOW,
    _OTHER_SITE_ID,
    _SITE_ID,
    _WORKER_TOKEN,
    _registry,
)
from test_design_conformance_requests import Fixture, _auth  # noqa: E402


def _polygon(x: float = 0.0) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [[[x, 0.0], [x + 1.0, 0.0], [x + 1.0, 1.0], [x, 1.0], [x, 0.0]]],
    }


class WorkAreaFixture(Fixture):
    """``Fixture`` 를 그대로 쓰되, 요청 저장소만 ``work_area_store`` 를 아는 것으로 얹는다."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path)
        self.work_areas = WorkAreaStore(
            DurableJournal(tmp_path / "work-areas.jsonl"),
            site_exists=lambda site_id: self.sites.get(site_id) is not None,
        )
        # 부모가 이미 연 요청 저널은 work_area_store 를 모른다 — 닫고 새로 연다
        # (설계면·작업 저장소는 그대로 재사용, 이 파일이 시험하는 것은 요청
        # 저장소의 구역 해석 로직 하나뿐이다).
        self.journal.close()
        self.journal = DurableJournal(tmp_path / "design-conformance-requests-wa.jsonl")
        self.requests = DesignConformanceRequestStore(
            self.journal,
            mission_store=self.missions,
            processing_job_store=self.jobs,
            design_surface_store=self.surfaces,
            work_area_store=self.work_areas,
        )

    def register_work_area(self, *, site_id: str = _SITE_ID, x: float = 0.0) -> str:
        result = self.work_areas.register(
            site_id,
            name="A공구",
            polygon=_polygon(x),
            crs="EPSG:4326",
            supersedes=None,
            now=_NOW,
            actor="admin",
        )
        assert result.verdict is WorkAreaVerdict.REGISTERED, result
        assert result.work_area is not None
        return result.work_area.work_area_id


@pytest.fixture
def wa_fixture(tmp_path: Path) -> WorkAreaFixture:
    return WorkAreaFixture(tmp_path)


def test_work_area_ids_are_resolved_into_zone_values(wa_fixture: WorkAreaFixture) -> None:
    """resolve_zones 를 통과한 뒤로는 즉석 폴리곤과 완전히 같은 모양이 된다."""
    work_area_id = wa_fixture.register_work_area()
    result = wa_fixture.create(zones=None, zone_crs=None, work_area_ids=[work_area_id])
    assert result.verdict is DesignConformanceRequestVerdict.CREATED, result
    assert result.record is not None
    assert result.record.zones == {work_area_id: _polygon()}
    assert result.record.zone_crs == "EPSG:4326"


def test_zones_and_work_area_ids_together_are_refused(wa_fixture: WorkAreaFixture) -> None:
    """어느 쪽이 진짜 지시인지 서버가 골라 주면 화면이 보낸 것과 계산에 쓴 것이 갈릴 수 있다."""
    work_area_id = wa_fixture.register_work_area()
    result = wa_fixture.create(
        zones={"zone-a": _polygon()}, zone_crs="EPSG:4326", work_area_ids=[work_area_id]
    )
    assert result.verdict is DesignConformanceRequestVerdict.WORK_AREA_UNUSABLE
    assert result.detail is not None
    assert "동시에" in result.detail


def test_work_area_from_another_site_is_refused(wa_fixture: WorkAreaFixture) -> None:
    """다른 현장의 구역으로는 잴 수 없다 — _resolve 가 현장을 확정한 뒤 대조한다."""
    other_area_id = wa_fixture.register_work_area(site_id=_OTHER_SITE_ID)
    result = wa_fixture.create(zones=None, zone_crs=None, work_area_ids=[other_area_id])
    assert result.verdict is DesignConformanceRequestVerdict.WORK_AREA_UNUSABLE
    assert result.detail is not None
    assert "다른 현장" in result.detail


def test_unusable_work_area_still_prefers_the_more_specific_unknown_job(
    wa_fixture: WorkAreaFixture,
) -> None:
    """작업이 없다는 실패는 WORK_AREA_UNUSABLE 이 아니라 원래 이름(UNKNOWN_JOB)으로 나온다."""
    work_area_id = wa_fixture.register_work_area()
    result = wa_fixture.create(
        zones=None,
        zone_crs=None,
        work_area_ids=[work_area_id],
        current_job_id="job-없음",
    )
    assert result.verdict is DesignConformanceRequestVerdict.UNKNOWN_JOB


def test_http_route_accepts_work_area_ids(wa_fixture: WorkAreaFixture) -> None:
    """대시보드가 실제로 보내는 것과 같은 모양(workAreaIds)이 라우터를 통과한다."""
    work_area_id = wa_fixture.register_work_area()
    app = FastAPI()
    mount_auth(app, _registry())
    mount_design_conformance_requests(app, wa_fixture.requests, wa_fixture.storage)
    client = TestClient(app)

    response = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance-requests",
        json={
            "designSurfaceId": wa_fixture.design_surface_id,
            "currentJobId": wa_fixture.current_job_id,
            "workAreaIds": [work_area_id],
        },
        headers=_auth(_ADMIN_TOKEN),
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["request"]["zones"] == {work_area_id: _polygon()}


def test_worker_token_cannot_create_a_request_via_work_areas(
    wa_fixture: WorkAreaFixture,
) -> None:
    """작업구역 경로도 일반 경로와 같은 권한 게이트를 통과한다 — 우회로가 아니다."""
    work_area_id = wa_fixture.register_work_area()
    app = FastAPI()
    mount_auth(app, _registry())
    mount_design_conformance_requests(app, wa_fixture.requests, wa_fixture.storage)
    client = TestClient(app)

    response = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance-requests",
        json={
            "designSurfaceId": wa_fixture.design_surface_id,
            "currentJobId": wa_fixture.current_job_id,
            "workAreaIds": [work_area_id],
        },
        headers=_auth(_WORKER_TOKEN),
    )
    assert response.status_code == 403
