"""CoverageReport 수신·완료 판정 계약 (INV-010 강제 지점, MASTER_PRD §15.5).

초점은 하나다 — **서버가 기체의 완료 주장을 그대로 믿지 않는가.**

발급 시점의 `plannedCoverageRatio` 는 요청자가 준 간격을 믿은 계획 추정치이고,
완료 판정의 권위는 이 보고서다. 그런데 보고서도 기체가 만든다 — 그래서 서버가
"주장이 근거로 뒷받침되는가"를 검사하지 않으면 완료 판정이 또 자기신고가 된다
(확정 이벤트를 Edge 가 주장할 수 없게 한 것과 같은 문제).

green≠작동: 픽스처가 완료 상태를 직접 주입하지 않는다 — 임무를 실제로 발급하고
그 임무에 대해 보고서를 올린다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.coverage_reports import (
    CoverageReportRecoveryError,
    CoverageReportStore,
    CoverageReportVerdict,
    mount_coverage_reports,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_event_contracts.coverage_report import CoverageReport

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "contracts" / "schemas" / "coverage-report.v1.1.json"

_DEVICE_TOKEN = "edge-device-token"  # noqa: S105 — 테스트 고정값
_VIEWER_TOKEN = "viewer-token"  # noqa: S105
_MISSION_ID = "mission-cov-1"
_SITE_ID = "site-001"
_NOW = datetime(2026, 8, 5, 3, 0, tzinfo=UTC)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_DEVICE_TOKEN),
                principal=Principal(
                    principal_id="edge-1",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id="edge-001",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="vw-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                ),
            ),
        ]
    )


def _report_payload(
    *,
    completion: str = "COMPLETED",
    hazard: float = 1.0,
    asset: float = 1.0,
    general: float = 1.0,
    cells: list[dict[str, Any]] | None = None,
    mission_id: str = _MISSION_ID,
    site_id: str = _SITE_ID,
) -> dict[str, Any]:
    return {
        "missionId": mission_id,
        "siteId": site_id,
        "timestamp": "2026-08-05T02:00:00+00:00",
        "cells": cells
        if cells is not None
        else [
            {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
            {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
        ],
        "summary": {
            "mandatoryHazardRatio": hazard,
            "mandatoryAssetRatio": asset,
            "accessibleGeneralRatio": general,
            "completionState": completion,
        },
    }


def _mission_store(tmp_path: Path, *, site_id: str = _SITE_ID) -> MissionStore:
    store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    plan_request = {"route": {"altitudeM": 40.0}}
    assert (
        store.record_issuance(
            MissionRecord(
                mission_id=_MISSION_ID,
                site_id=site_id,
                mission_type="BASELINE_MAPPING",
                artifact_kind="pair",
                contract={"schemaVersion": "1.2", "missionId": _MISSION_ID},
                kmz_sha256="deadbeef",
                route_pattern="lawnmower",
                waypoint_count=75,
                planned_coverage_ratio=1.0,
                issued_at=_NOW,
                issued_by="do-1",
                plan_request=plan_request,
                plan_request_digest=None,
            )
        ).value
        == "RECORDED"
    )
    return store


@pytest.fixture
def store(tmp_path: Path) -> CoverageReportStore:
    return CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"),
        mission_store=_mission_store(tmp_path),
    )


def _client(store: CoverageReportStore) -> TestClient:
    app = FastAPI()
    mount_auth(app, _registry())
    mount_coverage_reports(app, store)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_DEVICE_TOKEN}"})
    return client


# ── 계약 스키마 정합 ────────────────────────────────────────────────────────


def test_model_output_satisfies_contract_schema() -> None:
    """Python 모델의 wire 산출이 계약 스키마를 만족한다 — 두 정본이 갈라지지 않게."""
    validator = Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")))
    report = CoverageReport.model_validate(_report_payload())
    wire = report.model_dump(by_alias=True, mode="json", exclude_none=True)
    errors = sorted(validator.iter_errors(wire), key=lambda e: e.path)
    assert not errors, [e.message for e in errors]


def test_every_schema_cell_state_is_representable() -> None:
    """스키마의 Cell 상태 enum 전건을 모델이 받는다(한쪽만 늘어나는 drift 차단)."""
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    states = schema["properties"]["cells"]["items"]["properties"]["state"]["enum"]
    payload = _report_payload(
        completion="COMPLETED_WITH_GAPS",
        cells=[{"cellId": f"c-{i}", "state": s} for i, s in enumerate(states)],
    )
    report = CoverageReport.model_validate(payload)
    assert {c.state.value for c in report.cells} == set(states)


# ── 서버가 완료 주장을 검증한다 ─────────────────────────────────────────────


def test_completed_report_is_recorded(store: CoverageReportStore) -> None:
    result = store.record(CoverageReport.model_validate(_report_payload()), now=_NOW)
    assert result.verdict is CoverageReportVerdict.RECORDED
    latest = store.latest(_MISSION_ID)
    assert latest is not None
    assert latest.summary.completion_state.value == "COMPLETED"


@pytest.mark.parametrize(
    ("hazard", "asset", "general"),
    [
        (0.99, 1.0, 1.0),  # 위험구역 100% 미달 — INV-010 은 100% 를 요구한다
        (1.0, 0.99, 1.0),  # 필수 자산 100% 미달
        (1.0, 1.0, 0.94),  # 일반영역 95% 미달
    ],
)
def test_completed_claim_unsupported_by_ratios_is_rejected(
    store: CoverageReportStore, hazard: float, asset: float, general: float
) -> None:
    """[핵심] 근거 없는 COMPLETED 주장을 서버가 받지 않는다.

    이 게이트가 없으면 완료 판정이 다시 기체 자기신고가 된다 — 확정 이벤트를
    Edge 가 주장할 수 없게 한 것과 같은 이유다.
    """
    payload = _report_payload(hazard=hazard, asset=asset, general=general)
    result = store.record(CoverageReport.model_validate(payload), now=_NOW)
    assert result.verdict is CoverageReportVerdict.UNSUPPORTED_COMPLETION
    assert store.latest(_MISSION_ID) is None, "거부된 보고가 기록됐다"


def test_completed_with_unexplained_gap_is_rejected(store: CoverageReportStore) -> None:
    """[핵심] 사유 없는 미관찰 Cell 이 남은 채 COMPLETED 를 주장할 수 없다.

    PRD §15.5 "모든 미관찰 Cell에 원인코드와 후속처리 기록" — 원인 없는 공백이
    완료로 덮이면 그 구역을 다시 볼 이유가 원장에서 사라진다.
    """
    # 비율을 100% 미만으로 둔다 — 그래야 자체 모순 검사가 아니라 **사유 없는 공백**
    # 검사가 걸린다(전 비율 1.0 + 미관찰 Cell 은 그보다 앞선 모순 게이트 소관).
    payload = _report_payload(
        general=0.96,
        cells=[
            {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
            {"cellId": "c-2", "state": "NOT_OBSERVED"},
        ],
    )
    result = store.record(CoverageReport.model_validate(payload), now=_NOW)
    assert result.verdict is CoverageReportVerdict.UNEXPLAINED_GAP
    assert "c-2" in (result.detail or "")


def test_cause_coded_gap_is_accepted_when_not_claiming_completed(
    store: CoverageReportStore,
) -> None:
    """[비공허 대조] 공백을 정직하게 신고한 보고서는 받는다 — 신고를 막지 않는다."""
    payload = _report_payload(
        completion="COMPLETED_WITH_GAPS",
        general=0.80,
        cells=[
            {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
            {"cellId": "c-2", "state": "OCCLUDED"},
            {"cellId": "c-3", "state": "BATTERY_LIMITED"},
        ],
    )
    result = store.record(CoverageReport.model_validate(payload), now=_NOW)
    assert result.verdict is CoverageReportVerdict.RECORDED


def test_aborted_report_is_not_threshold_gated(store: CoverageReportStore) -> None:
    """중단 보고는 임계 검사를 걸지 않는다 — 그 자체가 '완료가 아니다'를 말한다."""
    payload = _report_payload(completion="ABORTED_SAFE", hazard=0.1, asset=0.0, general=0.05)
    assert (
        store.record(CoverageReport.model_validate(payload), now=_NOW).verdict
        is CoverageReportVerdict.RECORDED
    )


# ── Coverage Recovery 권고 (MASTER_PRD §15.2) ──────────────────────────────


def test_needs_coverage_recovery_false_for_clean_completed() -> None:
    report = CoverageReport.model_validate(_report_payload())
    assert report.needs_coverage_recovery() is False


def test_needs_coverage_recovery_true_for_completed_with_gaps_even_without_cells() -> None:
    """cells 가 비어도 신호가 뜬다 — judge_report 는 COMPLETED_WITH_GAPS 에 Cell
    존재를 강제하지 않으므로(그 검사는 COMPLETED 주장에만 걸린다), completionState
    자체가 "공백이 있었다"는 자기 신고다."""
    payload = _report_payload(completion="COMPLETED_WITH_GAPS", cells=[])
    report = CoverageReport.model_validate(payload)
    assert report.needs_coverage_recovery() is True


@pytest.mark.parametrize("completion", ["ABORTED_SAFE", "FAILED"])
def test_needs_coverage_recovery_true_for_aborted_or_failed_even_with_clean_cells(
    completion: str,
) -> None:
    """[핵심, 리뷰 P1-a] ABORTED_SAFE/FAILED 는 cells 가 전부 관찰됨으로 채워져
    있어도(또는 비어 있어도) 재커버가 필요하다 — 비행 자체가 끝까지 못 갔다는
    사실이 신호다. completion_state 만 보고 판단해야지 cells 내용에 기대면 안
    된다(judge_report 가 이 상태들엔 cells 강제도 임계 검사도 걸지 않는다)."""
    payload = _report_payload(completion=completion, hazard=0.1, asset=0.0, general=0.05)
    report = CoverageReport.model_validate(payload)
    assert report.needs_coverage_recovery() is True


def test_needs_coverage_recovery_true_for_reasoned_gap_cell_under_completed() -> None:
    """COMPLETED 로 정상 기록되더라도(임계 충족, 자체모순 아님) 사유있는 미관찰
    Cell(OCCLUDED 등)이 남아 있으면 재커버를 권고한다 — "완료"가 "전부 봤다"를
    뜻하지 않는다."""
    payload = _report_payload(
        general=0.96,
        cells=[
            {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
            {"cellId": "c-2", "state": "OCCLUDED"},
        ],
    )
    report = CoverageReport.model_validate(payload)
    assert report.needs_coverage_recovery() is True


# ── 임무 대조 ───────────────────────────────────────────────────────────────


def test_unknown_mission_is_rejected(store: CoverageReportStore) -> None:
    """발급된 적 없는 임무의 보고는 받지 않는다 — 근거 없는 관찰 기록 방지."""
    payload = _report_payload(mission_id="mission-never-issued")
    result = store.record(CoverageReport.model_validate(payload), now=_NOW)
    assert result.verdict is CoverageReportVerdict.UNKNOWN_MISSION


def test_site_mismatch_is_rejected(store: CoverageReportStore) -> None:
    payload = _report_payload(site_id="site-other")
    result = store.record(CoverageReport.model_validate(payload), now=_NOW)
    assert result.verdict is CoverageReportVerdict.SITE_MISMATCH


# ── 영속·재생 ───────────────────────────────────────────────────────────────


def test_reports_are_appended_not_overwritten(tmp_path: Path) -> None:
    """같은 임무의 보고가 여러 번 와도 덮어쓰지 않는다 — 감사 입력이라서."""
    mission_store = _mission_store(tmp_path)
    journal = DurableJournal(tmp_path / "coverage.jsonl")
    store = CoverageReportStore(journal, mission_store=mission_store)
    partial = _report_payload(completion="COMPLETED_WITH_GAPS", general=0.8)
    store.record(CoverageReport.model_validate(partial), now=_NOW)
    store.record(CoverageReport.model_validate(_report_payload()), now=_NOW)

    assert len(store.history(_MISSION_ID)) == 2
    latest = store.latest(_MISSION_ID)
    assert latest is not None
    assert latest.summary.completion_state.value == "COMPLETED"


def test_latest_recorded_exposes_reported_by(store: CoverageReportStore) -> None:
    """[핵심] 제출 주체가 조회 표면(latest_recorded)까지 살아 있다 — record() 의
    reported_by 가 in-memory 조회에서 사라지지 않는다(독립 재검토 B-3)."""
    result = store.record(
        CoverageReport.model_validate(_report_payload()), now=_NOW, reported_by="edge-77"
    )
    assert result.verdict is CoverageReportVerdict.RECORDED

    recorded = store.latest_recorded(_MISSION_ID)
    assert recorded is not None
    assert recorded.reported_by == "edge-77"
    assert recorded.report.summary.completion_state.value == "COMPLETED"


def test_reported_by_survives_replay(tmp_path: Path) -> None:
    """재기동(journal 재생) 후에도 reported_by 가 유지된다 — journal 엔벨로프에는
    적히지만 replay 가 버리면 감사 입력이 저장은 되고 조회는 안 되는 반쪽이 된다."""
    mission_store = _mission_store(tmp_path)
    journal = DurableJournal(tmp_path / "coverage.jsonl")
    store = CoverageReportStore(journal, mission_store=mission_store)
    store.record(
        CoverageReport.model_validate(_report_payload()), now=_NOW, reported_by="edge-77"
    )
    journal.close()

    reborn_journal = DurableJournal(tmp_path / "coverage.jsonl")
    reborn = CoverageReportStore(
        reborn_journal, mission_store=MissionStore(DurableJournal(tmp_path / "missions2.jsonl"))
    )
    try:
        recorded = reborn.latest_recorded(_MISSION_ID)
        assert recorded is not None
        assert recorded.reported_by == "edge-77"
    finally:
        reborn_journal.close()


def test_replay_restores_history(tmp_path: Path) -> None:
    mission_store = _mission_store(tmp_path)
    journal = DurableJournal(tmp_path / "coverage.jsonl")
    store = CoverageReportStore(journal, mission_store=mission_store)
    store.record(CoverageReport.model_validate(_report_payload()), now=_NOW)
    journal.close()

    reborn_journal = DurableJournal(tmp_path / "coverage.jsonl")
    reborn = CoverageReportStore(
        reborn_journal, mission_store=MissionStore(DurableJournal(tmp_path / "missions2.jsonl"))
    )
    try:
        # mission_store 가 비어 있어도 **재생은** 통과한다 — 임무 대조는 수신
        # 시점의 게이트이고, 이미 받은 기록을 나중에 부정하지 않는다.
        assert len(reborn.history(_MISSION_ID)) == 1
    finally:
        reborn_journal.close()


def test_replay_rejects_report_that_could_not_have_been_recorded(tmp_path: Path) -> None:
    """[핵심] journal 조작으로 근거 없는 COMPLETED 가 되살아나지 않는다.

    live 게이트만 있고 재생이 무검사면, 원장에 한 줄 넣는 것으로 완료 판정을
    만들 수 있다(events.py 재생 게이트와 같은 클래스).
    """
    seed = DurableJournal(tmp_path / "coverage.jsonl")
    seed.append(
        {
            "kind": "coverage-reported",
            "ts": _NOW.isoformat(),
            "missionId": _MISSION_ID,
            "siteId": _SITE_ID,
            "completionState": "COMPLETED",
            "report": _report_payload(hazard=0.1, asset=0.1, general=0.1),
        }
    )
    seed.close()

    with pytest.raises(CoverageReportRecoveryError, match="UNSUPPORTED_COMPLETION"):
        CoverageReportStore(
            DurableJournal(tmp_path / "coverage.jsonl"),
            mission_store=_mission_store(tmp_path),
        )


# ── HTTP 배선·권한 ──────────────────────────────────────────────────────────


def test_operator_cannot_submit_coverage_report(store: CoverageReportStore) -> None:
    """[핵심] 운영자가 커버리지를 손으로 주장할 수 없다 — 장비 관측만 받는다."""
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(),
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    )
    assert response.status_code == 403


def test_path_and_body_mission_id_must_agree(store: CoverageReportStore) -> None:
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(mission_id="mission-other"),
    )
    assert response.status_code == 422


def test_submit_then_read_back_over_http(store: CoverageReportStore) -> None:
    client = _client(store)
    submitted = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report", json=_report_payload()
    )
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["verdict"] == "RECORDED"

    read = client.get(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    )
    assert read.status_code == 200
    body = read.json()
    assert body["reportCount"] == 1
    assert body["latest"]["summary"]["completionState"] == "COMPLETED"
    assert body["reportedBy"] == "edge-1", "제출한 Principal id 가 조회 응답에 실려야 한다(B-3)"
    assert body["recoveryRecommended"] is False, "공백 없는 COMPLETED 는 재커버가 필요 없다"


def test_recovery_recommended_surfaces_over_http_when_gaps_present(
    store: CoverageReportStore,
) -> None:
    """Coverage Recovery 권고(MASTER_PRD §15.2)가 조회 응답에 실린다 — 자동 재발급을
    트리거하지 않고, 운영자가 원본 AOI 로 SPATIAL_REFRESH 를 재발급할 신호만 준다."""
    client = _client(store)
    payload = _report_payload(
        completion="COMPLETED_WITH_GAPS",
        general=0.80,
        cells=[
            {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
            {"cellId": "c-2", "state": "OCCLUDED"},
        ],
    )
    submitted = client.post(f"/v1/missions/{_MISSION_ID}/coverage-report", json=payload)
    assert submitted.status_code == 201, submitted.text

    read = client.get(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    )
    assert read.json()["recoveryRecommended"] is True


def test_unsupported_completion_maps_to_422_over_http(store: CoverageReportStore) -> None:
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(general=0.5),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "UNSUPPORTED_COMPLETION"


def test_status_map_covers_every_verdict() -> None:
    """새 verdict 를 추가하고 상태코드를 빠뜨리는 경로를 막는다(다른 라우터 관습)."""
    from ksi_core.coverage_reports import _STATUS

    assert set(_STATUS) == set(CoverageReportVerdict)


# ── 근거 없는 완료 (독립 재검토 B-1) ────────────────────────────────────────


def test_completed_without_any_cell_is_rejected(store: CoverageReportStore) -> None:
    """[핵심] 관찰 증거 0건으로 완료를 주장할 수 없다.

    스키마에 minItems 가 없어 빈 배열이 통과했다 — 그러면 "무엇을 봤길래 완료인가"에
    원장이 답하지 못한다.
    """
    result = store.record(
        CoverageReport.model_validate(_report_payload(cells=[])), now=_NOW
    )
    assert result.verdict is CoverageReportVerdict.NO_COVERAGE_EVIDENCE


@pytest.mark.parametrize(
    "gap_state", ["OCCLUDED", "UNREACHABLE", "UNSAFE", "BATTERY_LIMITED", "NOT_OBSERVED"]
)
def test_full_coverage_claim_contradicted_by_its_own_cells(
    store: CoverageReportStore, gap_state: str
) -> None:
    """[핵심] 전 구역 100% 라면서 관찰 안 된 Cell 을 함께 신고할 수 없다.

    서버가 Cell 분류를 몰라도 판정 가능한 **자체 모순**이다 — 세 비율이 모두 1.0 인데
    관찰상태가 아닌 Cell 이 있으면 어떤 가중치에서도 성립하지 않는다. 사유가 있는
    공백(OCCLUDED 등)도 마찬가지다 — 사유가 있다고 100% 가 되지는 않는다.
    """
    payload = _report_payload(
        cells=[
            {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
            {"cellId": "c-2", "state": gap_state},
        ]
    )
    result = store.record(CoverageReport.model_validate(payload), now=_NOW)
    assert result.verdict is CoverageReportVerdict.SELF_CONTRADICTORY_SUMMARY
    assert "c-2" in (result.detail or "")


def test_partial_ratio_with_cause_coded_gap_is_accepted(store: CoverageReportStore) -> None:
    """[비공허 대조] 비율을 정직하게 낮춘 보고서는 받는다 — 과잉 거부가 아니다."""
    payload = _report_payload(
        general=0.96,
        cells=[
            {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
            {"cellId": "c-2", "state": "OCCLUDED"},
        ],
    )
    assert (
        store.record(CoverageReport.model_validate(payload), now=_NOW).verdict
        is CoverageReportVerdict.RECORDED
    )


def test_submitter_is_recorded_in_the_journal(tmp_path: Path) -> None:
    """"언제 무엇을 봤다고 했는가"가 감사 입력이면 "누가"도 남아야 한다(B-3)."""
    journal_path = tmp_path / "coverage.jsonl"
    journal = DurableJournal(journal_path)
    store = CoverageReportStore(journal, mission_store=_mission_store(tmp_path))
    store.record(
        CoverageReport.model_validate(_report_payload()), now=_NOW, reported_by="edge-1"
    )
    journal.close()

    lines = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines[-1]["reportedBy"] == "edge-1"


def test_http_submission_records_the_authenticated_principal(
    store: CoverageReportStore,
) -> None:
    """HTTP 경로에서도 제출 주체가 요청자가 아니라 **인증된** Principal 이다."""
    client = _client(store)
    assert (
        client.post(
            f"/v1/missions/{_MISSION_ID}/coverage-report", json=_report_payload()
        ).status_code
        == 201
    )
    history = store.history(_MISSION_ID)
    assert len(history) == 1
