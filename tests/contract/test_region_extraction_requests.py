"""변화 영역 추출 **요청** 계약 (M4-E) — 생성 게이트·멱등·lease·전이·입력.

초점 넷:

**① RECORDED 된 설계 대비 잔량 리포트만 입력이다.** 없으면
``UNKNOWN_DESIGN_CONFORMANCE`` — 뽑을 diffRaster 자체가 없다.

**② 같은 designConformanceId 재요청은 멱등이다.** 재전송이 요청을 복제하지 않는다.

**③ 자동 트리거는 없다.** 설계 대비 잔량이 RECORDED 돼도 이 요청은 저절로
생기지 않는다 — 수동 POST 만 연다.

**④ /input 은 워커 전용이고, 원본 리포트의 diffRaster 를 그대로 옮긴다.**
``extractionPolicy`` 만 매 호출마다 새로 계산된 값이다(policy-owned).

픽스처는 ``test_design_conformance_reports.py`` 의 ``ReportFixture`` 를 그대로
쓴다 — 설계면·처리 작업·요청·리포트가 실제로 RECORDED 까지 진행된 상태다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import mount_auth
from ksi_core.design_conformance_reports import DesignConformanceVerdict
from ksi_core.durable_journal import DurableJournal
from ksi_core.processing_jobs import ProcessingJobStatus
from ksi_core.region_extraction_requests import (
    RegionExtractionRequestRecord,
    RegionExtractionRequestRecoveryError,
    RegionExtractionRequestStore,
    RegionExtractionRequestVerdict,
    build_region_extraction_request_id,
    change_region_set_id_of,
    mount_region_extraction_requests,
)

# tests/contract 는 rootdir 기반 수집이라 같은 디렉터리 모듈을 직접 import 한다
# (design_conformance 계열 파일들과 같은 관용구).
from test_comparison_requests import _CURRENT_MISSION_ID, _OTHER_MISSION_ID, _registry  # noqa: E402
from test_design_conformance_reports import ReportFixture, _report  # noqa: E402

_ADMIN_TOKEN = "cmp-admin-token"  # noqa: S105 -- test_comparison_requests._registry 가 등록한 값
_WORKER_TOKEN = "cmp-worker-token"  # noqa: S105
_VIEWER_TOKEN = "cmp-viewer-token"  # noqa: S105


class Fixture:
    """요청 원장 + 그 위에 실제 RECORDED 설계 대비 잔량 리포트를 만드는 헬퍼."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.report_fixture = ReportFixture(tmp_path)
        self.journal = DurableJournal(tmp_path / "region-extraction-requests.jsonl")
        self.requests = RegionExtractionRequestStore(
            self.journal,
            mission_store=self.report_fixture.base.missions,
            design_conformance_report_store=self.report_fixture.reports,
        )

    def recorded_design_conformance(self) -> str:
        """RECORDED 상태까지 만든다 — 반환값은 그 리포트의 designConformanceId."""
        record, verified_at = self.report_fixture.prepared()
        report = _report(record, verified_at)
        outcome = self.report_fixture.reports.record(
            _CURRENT_MISSION_ID, report, now=datetime.now(UTC), reported_by="worker-1"
        )
        assert outcome.verdict is DesignConformanceVerdict.RECORDED, outcome
        return record.design_conformance_id

    def create(self, **overrides: Any) -> Any:
        payload: dict[str, Any] = {"requested_by": "op-1", "now": datetime.now(UTC)}
        payload.update(overrides)
        mission_id = payload.pop("mission_id", _CURRENT_MISSION_ID)
        # ``dict.pop`` 의 기본값은 즉시(eager) 평가된다 — design_conformance_id 를
        # 이미 넘긴 호출에서도 매번 새 설계 대비 잔량을 하나 더 만들면(그리고 그
        # 내부 요청 픽스처가 멱등 게이트에 걸리면) 의도치 않은 부수효과가 생긴다.
        # 그래서 lazy 하게 필요할 때만 만든다.
        design_conformance_id = payload.pop("design_conformance_id", None)
        if design_conformance_id is None:
            design_conformance_id = self.recorded_design_conformance()
        return self.requests.create(
            mission_id, design_conformance_id=design_conformance_id, **payload
        )

    def created(self, **overrides: Any) -> RegionExtractionRequestRecord:
        result = self.create(**overrides)
        assert result.verdict is RegionExtractionRequestVerdict.CREATED, result
        assert result.record is not None
        return result.record

    def leased(self, request_id: str, *, worker_id: str = "worker-1") -> None:
        result = self.requests.acquire_lease(
            request_id, worker_id=worker_id, now=datetime.now(UTC)
        )
        assert result.verdict is RegionExtractionRequestVerdict.LEASED, result

    def running(self, request_id: str, *, worker_id: str = "worker-1") -> None:
        result = self.requests.transition(
            request_id,
            ProcessingJobStatus.RUNNING,
            detail=None,
            actor=worker_id,
            now=datetime.now(UTC),
        )
        assert result.verdict is RegionExtractionRequestVerdict.TRANSITIONED, result

    def app(self) -> FastAPI:
        app = FastAPI()
        mount_auth(app, _registry())
        mount_region_extraction_requests(
            app, self.requests, self.report_fixture.reports, self.report_fixture.base.storage
        )
        return app

    def close(self) -> None:
        self.journal.close()
        self.report_fixture.close()


@pytest.fixture
def fixture(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── 생성 게이트 ───────────────────────────────────────────────────────────


def test_created_request_id_is_derived_from_the_design_conformance_id(
    fixture: Fixture,
) -> None:
    design_conformance_id = fixture.recorded_design_conformance()
    record = fixture.created(design_conformance_id=design_conformance_id)
    assert record.request_id == build_region_extraction_request_id(design_conformance_id, 1)
    assert record.status is ProcessingJobStatus.QUEUED
    assert record.change_region_set_id == change_region_set_id_of(record.request_id)


def test_unknown_mission_is_refused(fixture: Fixture) -> None:
    design_conformance_id = fixture.recorded_design_conformance()
    result = fixture.create(
        mission_id="mission-does-not-exist", design_conformance_id=design_conformance_id
    )
    assert result.verdict is RegionExtractionRequestVerdict.UNKNOWN_MISSION


def test_a_design_conformance_id_that_was_never_recorded_is_refused(fixture: Fixture) -> None:
    """뽑을 diffRaster 자체가 없다 — UNKNOWN_DESIGN_CONFORMANCE."""
    result = fixture.create(design_conformance_id="dcf-999-never-recorded")
    assert result.verdict is RegionExtractionRequestVerdict.UNKNOWN_DESIGN_CONFORMANCE
    assert fixture.requests.list_for_mission(_CURRENT_MISSION_ID) == []


def test_a_report_recorded_under_another_mission_does_not_satisfy_the_gate(
    fixture: Fixture,
) -> None:
    """존재하는 designConformanceId 라도 **이 임무 소속**이 아니면 여전히 UNKNOWN."""
    design_conformance_id = fixture.recorded_design_conformance()
    result = fixture.create(
        mission_id=_OTHER_MISSION_ID, design_conformance_id=design_conformance_id
    )
    assert result.verdict is RegionExtractionRequestVerdict.UNKNOWN_DESIGN_CONFORMANCE


# ── 멱등 ─────────────────────────────────────────────────────────────────


def test_same_design_conformance_id_resubmission_is_idempotent(fixture: Fixture) -> None:
    design_conformance_id = fixture.recorded_design_conformance()
    first = fixture.created(design_conformance_id=design_conformance_id)
    again = fixture.create(design_conformance_id=design_conformance_id)
    assert again.verdict is RegionExtractionRequestVerdict.ALREADY_REQUESTED
    assert again.record is not None and again.record.request_id == first.request_id
    assert len(fixture.requests.list_for_mission(_CURRENT_MISSION_ID)) == 1


# ── lease ────────────────────────────────────────────────────────────────


def test_a_second_worker_cannot_steal_an_active_lease(fixture: Fixture) -> None:
    record = fixture.created()
    fixture.leased(record.request_id, worker_id="worker-1")
    result = fixture.requests.acquire_lease(
        record.request_id, worker_id="worker-2", now=datetime.now(UTC)
    )
    assert result.verdict is RegionExtractionRequestVerdict.LEASE_HELD_BY_ANOTHER


def test_same_worker_re_acquiring_is_a_renewal(fixture: Fixture) -> None:
    record = fixture.created()
    fixture.leased(record.request_id, worker_id="worker-1")
    result = fixture.requests.acquire_lease(
        record.request_id, worker_id="worker-1", now=datetime.now(UTC)
    )
    assert result.verdict is RegionExtractionRequestVerdict.LEASE_RENEWED


def test_pending_list_drops_a_request_only_once_it_is_running_with_a_live_lease(
    fixture: Fixture,
) -> None:
    """QUEUED 는 lease 와 무관하게 늘 후보다(``leasing.is_claimable``) — RUNNING +
    살아있는 lease 여야 후보에서 빠진다(``design_conformance_requests`` 와 동일 근거)."""
    record = fixture.created()
    assert [r.request_id for r in fixture.requests.list_pending(now=datetime.now(UTC))] == [
        record.request_id
    ]
    fixture.leased(record.request_id)
    assert [r.request_id for r in fixture.requests.list_pending(now=datetime.now(UTC))] == [
        record.request_id
    ]
    fixture.running(record.request_id)
    assert fixture.requests.list_pending(now=datetime.now(UTC)) == []


# ── 전이 ─────────────────────────────────────────────────────────────────


def test_illegal_transition_from_queued_to_succeeded_is_refused(fixture: Fixture) -> None:
    record = fixture.created()
    fixture.leased(record.request_id)
    result = fixture.requests.transition(
        record.request_id,
        ProcessingJobStatus.SUCCEEDED,
        detail=None,
        actor="worker-1",
        now=datetime.now(UTC),
    )
    assert result.verdict is RegionExtractionRequestVerdict.ILLEGAL_TRANSITION


def test_a_terminal_request_cannot_transition_again(fixture: Fixture) -> None:
    record = fixture.created()
    fixture.leased(record.request_id)
    fixture.running(record.request_id)
    succeeded = fixture.requests.transition(
        record.request_id,
        ProcessingJobStatus.SUCCEEDED,
        detail="ok",
        actor="worker-1",
        now=datetime.now(UTC),
    )
    assert succeeded.verdict is RegionExtractionRequestVerdict.TRANSITIONED
    again = fixture.requests.transition(
        record.request_id,
        ProcessingJobStatus.FAILED,
        detail=None,
        actor="worker-1",
        now=datetime.now(UTC),
    )
    assert again.verdict is RegionExtractionRequestVerdict.ILLEGAL_TRANSITION


# ── HTTP /input ──────────────────────────────────────────────────────────


def test_http_input_carries_the_original_diff_raster_reference(fixture: Fixture) -> None:
    record = fixture.created()
    fixture.leased(record.request_id)
    client = TestClient(fixture.app())

    response = client.get(
        f"/v1/region-extraction-requests/{record.request_id}/input",
        headers=_auth(_WORKER_TOKEN),
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["verdict"] == "INPUT_READY"
    payload = body["input"]
    assert payload["requestId"] == record.request_id
    assert payload["missionId"] == _CURRENT_MISSION_ID
    assert payload["designConformanceId"] == record.design_conformance_id
    assert payload["changeRegionSetId"] == record.change_region_set_id
    assert payload["diffRasterId"]
    assert payload["diffRaster"]["diffRasterId"] == payload["diffRasterId"]
    assert payload["thresholdM"] > 0
    assert payload["crs"] == "EPSG:5186"
    assert payload["extractionPolicy"]["minRegionAreaM2"] > 0
    assert payload["extractionPolicy"]["connectivity"] in (4, 8)
    assert "diffRasterUrl" in payload


def test_http_input_without_a_lease_is_denied(fixture: Fixture) -> None:
    record = fixture.created()
    client = TestClient(fixture.app())
    response = client.get(
        f"/v1/region-extraction-requests/{record.request_id}/input",
        headers=_auth(_WORKER_TOKEN),
    )
    assert response.status_code == 409
    assert response.json()["verdict"] == "LEASE_REQUIRED"


def test_operator_cannot_call_the_worker_only_input_endpoint(fixture: Fixture) -> None:
    """MISSIONS_ISSUE 권한자는 PROCESSING_WORK 표면을 부를 수 없다."""
    record = fixture.created()
    fixture.leased(record.request_id)
    client = TestClient(fixture.app())
    response = client.get(
        f"/v1/region-extraction-requests/{record.request_id}/input",
        headers=_auth(_ADMIN_TOKEN),
    )
    assert response.status_code == 403


# ── HTTP 생성·조회 표면 ───────────────────────────────────────────────────


def test_http_create_list_and_lease_round_trip(fixture: Fixture) -> None:
    design_conformance_id = fixture.recorded_design_conformance()
    client = TestClient(fixture.app())

    created = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance/{design_conformance_id}"
        "/region-extraction-requests",
        headers=_auth(_ADMIN_TOKEN),
    )
    assert created.status_code == 201, created.json()
    request_id = created.json()["request"]["requestId"]

    listed = client.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction-requests",
        headers=_auth(_VIEWER_TOKEN),
    )
    assert listed.status_code == 200
    assert [r["requestId"] for r in listed.json()["requests"]] == [request_id]

    pending = client.get(
        "/v1/region-extraction-requests", headers=_auth(_WORKER_TOKEN)
    )
    assert pending.status_code == 200
    assert [r["requestId"] for r in pending.json()["requests"]] == [request_id]

    leased = client.post(
        f"/v1/region-extraction-requests/{request_id}/lease", headers=_auth(_WORKER_TOKEN)
    )
    assert leased.status_code == 201
    assert leased.json()["verdict"] == "LEASED"


def test_viewer_cannot_issue_a_region_extraction_request(fixture: Fixture) -> None:
    design_conformance_id = fixture.recorded_design_conformance()
    client = TestClient(fixture.app())
    response = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance/{design_conformance_id}"
        "/region-extraction-requests",
        headers=_auth(_VIEWER_TOKEN),
    )
    assert response.status_code == 403


# ── 재생 ──────────────────────────────────────────────────────────────────


def _reopen(fixture: Fixture) -> RegionExtractionRequestStore:
    fixture.journal.close()
    return RegionExtractionRequestStore(
        DurableJournal(fixture.tmp_path / "region-extraction-requests.jsonl"),
        mission_store=fixture.report_fixture.base.missions,
        design_conformance_report_store=fixture.report_fixture.reports,
    )


def test_replay_restores_the_request_and_its_lease(fixture: Fixture) -> None:
    record = fixture.created()
    fixture.leased(record.request_id)

    replayed = _reopen(fixture)
    restored = replayed.get(record.request_id)
    assert restored is not None
    assert restored.design_conformance_id == record.design_conformance_id
    assert restored.lease is not None and restored.lease.worker_id == "worker-1"


def test_replay_refuses_unknown_record_kinds(fixture: Fixture) -> None:
    fixture.created()
    path = fixture.tmp_path / "region-extraction-requests.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "made-up", "requestId": "x"}\n')
    with pytest.raises(RegionExtractionRequestRecoveryError, match="알 수 없는 journal"):
        _reopen(fixture)
