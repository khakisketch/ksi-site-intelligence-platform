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
from ksi_core.mission_execution import MissionExecutionStore
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_domain.enums import MissionExecutionStatus
from ksi_event_contracts.coverage_report import CoverageReport

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "contracts" / "schemas" / "coverage-report.v1.1.json"

_DEVICE_TOKEN = "edge-device-token"  # noqa: S105 — 테스트 고정값
_OTHER_DEVICE_TOKEN = "edge-other-device-token"  # noqa: S105
_VIEWER_TOKEN = "viewer-token"  # noqa: S105
_MISSION_ID = "mission-cov-1"
_SITE_ID = "site-001"
_DEVICE_ID = "edge-001"
_OTHER_DEVICE_ID = "edge-002"
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
                    device_id=_DEVICE_ID,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OTHER_DEVICE_TOKEN),
                principal=Principal(
                    principal_id="edge-2",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id=_OTHER_DEVICE_ID,
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


def _mission_store(
    tmp_path: Path,
    *,
    site_id: str = _SITE_ID,
    assigned_device_id: str | None = None,
    journal_name: str = "missions.jsonl",
    planned_coverage_ratio: float | None = 1.0,
) -> MissionStore:
    store = MissionStore(DurableJournal(tmp_path / journal_name))
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
                planned_coverage_ratio=planned_coverage_ratio,
                issued_at=_NOW,
                issued_by="do-1",
                plan_request=plan_request,
                plan_request_digest=None,
                assigned_device_id=assigned_device_id,
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


# ── 장비-임무 대조 (INV-010 무결성 공백) ─────────────────────────────────────


def test_device_not_assigned_is_rejected(tmp_path: Path) -> None:
    """[핵심] 임무가 배정을 신고했는데 다른 장비가 올리면 거부한다."""
    mission_store = _mission_store(tmp_path, assigned_device_id=_DEVICE_ID)
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"), mission_store=mission_store
    )
    result = store.record(
        CoverageReport.model_validate(_report_payload()),
        now=_NOW,
        device_id=_OTHER_DEVICE_ID,
    )
    assert result.verdict is CoverageReportVerdict.DEVICE_NOT_ASSIGNED
    assert result.report is None  # 거부는 완료 판정 권위를 갖지 않는다


def test_assigned_device_is_accepted(tmp_path: Path) -> None:
    """배정된 바로 그 장비가 올리면 정상 접수된다."""
    mission_store = _mission_store(tmp_path, assigned_device_id=_DEVICE_ID)
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"), mission_store=mission_store
    )
    result = store.record(
        CoverageReport.model_validate(_report_payload()), now=_NOW, device_id=_DEVICE_ID
    )
    assert result.verdict is CoverageReportVerdict.RECORDED


def test_unassigned_mission_accepts_any_device(tmp_path: Path) -> None:
    """[핵심][회귀] 배정을 신고하지 않은 임무는 예전처럼 어느 장비든 받는다 —
    이 필드 도입이 기존 흐름(하드웨어 아직 없음)을 깨지 않는다."""
    mission_store = _mission_store(tmp_path)  # assigned_device_id 생략 = None
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"), mission_store=mission_store
    )
    result = store.record(
        CoverageReport.model_validate(_report_payload()), now=_NOW, device_id=_OTHER_DEVICE_ID
    )
    assert result.verdict is CoverageReportVerdict.RECORDED


def test_device_mismatch_rejection_is_journaled(tmp_path: Path) -> None:
    """거부 판정도 감사기록에 남는다 — 다른 rejection 들과 같은 원칙
    (risk coverage-report-rejection-not-auditable)."""
    mission_store = _mission_store(tmp_path, assigned_device_id=_DEVICE_ID)
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"), mission_store=mission_store
    )
    store.record(
        CoverageReport.model_validate(_report_payload()),
        now=_NOW,
        reported_by="edge-2",
        device_id=_OTHER_DEVICE_ID,
    )
    rejections = store.rejections(_MISSION_ID)
    assert len(rejections) == 1
    assert rejections[0].verdict is CoverageReportVerdict.DEVICE_NOT_ASSIGNED
    assert rejections[0].reported_by == "edge-2"


def test_device_mismatch_is_rejected_over_http(tmp_path: Path) -> None:
    """[핵심] 실제 HTTP 경로로 — 인증된 장비 자신의 device_id 가 배정과 다르면
    403 DEVICE_NOT_ASSIGNED. 인증(EDGE_DEVICE 인가) 통과 이후의 자원 단위
    거부이므로 401 이 아니라 403 이다(edge_sync.py DEVICE_MISMATCH 와 동형)."""
    mission_store = _mission_store(tmp_path, assigned_device_id=_DEVICE_ID)
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"), mission_store=mission_store
    )
    app = FastAPI()
    mount_auth(app, _registry())
    mount_coverage_reports(app, store)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_OTHER_DEVICE_TOKEN}"})

    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report", json=_report_payload()
    )
    assert response.status_code == 403
    body = response.json()
    assert body["verdict"] == "DEVICE_NOT_ASSIGNED"
    assert store.latest(_MISSION_ID) is None  # 수용되지 않았다


def test_assigned_device_submits_successfully_over_http(tmp_path: Path) -> None:
    """배정된 장비 본인은 그대로 통과한다 — 이 필드가 정상 경로를 막지 않는다."""
    mission_store = _mission_store(tmp_path, assigned_device_id=_DEVICE_ID)
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"), mission_store=mission_store
    )
    client = _client(store)  # 기본 _DEVICE_TOKEN → device_id=_DEVICE_ID

    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report", json=_report_payload()
    )
    assert response.status_code == 201
    assert response.json()["verdict"] == "RECORDED"


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


def test_replay_does_not_reject_on_site_mismatch_against_current_mission_store(
    tmp_path: Path,
) -> None:
    """[핵심][회귀] 재생은 site 대조(⑤)를 하지 않는다 — 수신 시점 게이트다(INV-010,
    독립 재검토 B-2).

    재생 시점의 mission_store 에 **같은 missionId 로 다른 siteId** 의 임무가 있어도
    (임무 원장이 이 원장과 따로 회전·보관되는 시나리오를 흉내) 이미 접수된 보고는
    부정되지 않는다 — live 였다면 SITE_MISMATCH 로 거부됐을 조합이다.
    """
    mission_store = _mission_store(tmp_path)  # site_id=_SITE_ID
    journal = DurableJournal(tmp_path / "coverage.jsonl")
    store = CoverageReportStore(journal, mission_store=mission_store)
    store.record(CoverageReport.model_validate(_report_payload()), now=_NOW)
    journal.close()

    drifted_missions = _mission_store(
        tmp_path, site_id="site-drifted", journal_name="missions-drifted.jsonl"
    )
    reborn_journal = DurableJournal(tmp_path / "coverage.jsonl")
    reborn = CoverageReportStore(reborn_journal, mission_store=drifted_missions)
    try:
        assert len(reborn.history(_MISSION_ID)) == 1
        latest = reborn.latest(_MISSION_ID)
        assert latest is not None
        assert latest.site_id == _SITE_ID, "접수 당시 보고서의 siteId 가 그대로 유지된다"
    finally:
        reborn_journal.close()


def test_replay_does_not_reject_on_device_mismatch_against_current_mission_store(
    tmp_path: Path,
) -> None:
    """[핵심][회귀] 재생은 device 배정 대조도 하지 않는다 — ⑤(임무 대조)와 같은
    이유(수신 시점 게이트, 임무 원장의 별도 회전·보관)로 receive-time 전용이다.

    재생 시점의 mission_store 에 **같은 missionId 가 다른 장비에 배정**돼 있어도
    이미 접수된 보고는 부정되지 않는다 — live 였다면 DEVICE_NOT_ASSIGNED 로 거부됐을
    조합이다.
    """
    mission_store = _mission_store(tmp_path, assigned_device_id=_DEVICE_ID)
    journal = DurableJournal(tmp_path / "coverage.jsonl")
    store = CoverageReportStore(journal, mission_store=mission_store)
    store.record(
        CoverageReport.model_validate(_report_payload()), now=_NOW, device_id=_DEVICE_ID
    )
    journal.close()

    drifted_missions = _mission_store(
        tmp_path, assigned_device_id=_OTHER_DEVICE_ID, journal_name="missions-drifted.jsonl"
    )
    reborn_journal = DurableJournal(tmp_path / "coverage.jsonl")
    reborn = CoverageReportStore(reborn_journal, mission_store=drifted_missions)
    try:
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


def test_rejected_report_is_journaled_not_silently_dropped(tmp_path: Path) -> None:
    """[핵심] 거부 판정(RECORDED 아닌 모든 verdict)도 journal 에 남는다 —
    risk coverage-report-rejection-not-auditable."""
    journal_path = tmp_path / "coverage.jsonl"
    journal = DurableJournal(journal_path)
    store = CoverageReportStore(journal, mission_store=_mission_store(tmp_path))

    result = store.record(CoverageReport.model_validate(_report_payload(cells=[])), now=_NOW)
    assert result.verdict is CoverageReportVerdict.NO_COVERAGE_EVIDENCE
    journal.close()

    lines = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["kind"] == "coverage-report-rejected"
    assert lines[0]["verdict"] == "NO_COVERAGE_EVIDENCE"
    assert lines[0]["missionId"] == _MISSION_ID


def test_unknown_mission_rejection_is_journaled(tmp_path: Path) -> None:
    """존재하지 않는 missionId 로의 제출 시도도 감사기록에 남는다(위조/오작동 탐지)."""
    journal_path = tmp_path / "coverage.jsonl"
    journal = DurableJournal(journal_path)
    store = CoverageReportStore(journal, mission_store=_mission_store(tmp_path))

    result = store.record(
        CoverageReport.model_validate(_report_payload(mission_id="mission-ghost")), now=_NOW
    )
    assert result.verdict is CoverageReportVerdict.UNKNOWN_MISSION
    journal.close()

    lines = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines[0]["kind"] == "coverage-report-rejected"
    assert lines[0]["verdict"] == "UNKNOWN_MISSION"


def test_rejected_entries_do_not_resurrect_on_replay(tmp_path: Path) -> None:
    """거부 기록은 재생 시 건너뛴다 — RECORDED 만 완료 판정 권위를 갖는다."""
    mission_store = _mission_store(tmp_path)
    journal = DurableJournal(tmp_path / "coverage.jsonl")
    store = CoverageReportStore(journal, mission_store=mission_store)
    store.record(CoverageReport.model_validate(_report_payload(cells=[])), now=_NOW)
    journal.close()

    reborn_journal = DurableJournal(tmp_path / "coverage.jsonl")
    reborn = CoverageReportStore(
        reborn_journal, mission_store=MissionStore(DurableJournal(tmp_path / "missions2.jsonl"))
    )
    try:
        assert reborn.history(_MISSION_ID) == []
        assert reborn.latest(_MISSION_ID) is None
    finally:
        reborn_journal.close()


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


# ── 거부가 조회로 도달하는가 (risk coverage-report-rejection-not-auditable) ──
#
# 거부 판정의 journal append 는 이미 있었다. 없던 것은 **읽는 경로**다 — 저장만 하고
# 어떤 GET 으로도 못 보면 "서버가 근거 없는 완료를 막았다"는 사실이 운영자·감사자
# 에게 끝내 도달하지 않는다. 장비가 반복적으로 허위 완료를 주장해도 사람은 모른다.


def test_rejection_is_visible_through_the_api(store: CoverageReportStore) -> None:
    client = _client(store)
    unsupported = _report_payload(completion="COMPLETED", hazard=0.5)
    posted = client.post(f"/v1/missions/{_MISSION_ID}/coverage-report", json=unsupported)
    assert posted.status_code == 422

    listed = client.get(
        f"/v1/missions/{_MISSION_ID}/coverage-report/rejections",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["rejectionCount"] == 1
    entry = body["rejections"][0]
    assert entry["verdict"] == CoverageReportVerdict.UNSUPPORTED_COMPLETION.value
    assert entry["reportedBy"] == "edge-1"
    assert entry["detail"] is not None


def test_rejection_list_does_not_carry_the_claimed_numbers(store: CoverageReportStore) -> None:
    """거부된 주장의 본문은 싣지 않는다 — 조회 표면에 실으면 화면에서 사실처럼 읽힌다."""
    client = _client(store)
    client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(completion="COMPLETED", hazard=0.5),
    )
    entry = client.get(
        f"/v1/missions/{_MISSION_ID}/coverage-report/rejections",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    ).json()["rejections"][0]
    assert set(entry) == {"verdict", "detail", "reportedBy", "rejectedAt"}


def test_no_rejection_is_empty_list_not_404(store: CoverageReportStore) -> None:
    """'이 임무엔 거부가 없었다'는 그 자체로 답이다 — 404 면 '임무가 없다'와 섞인다."""
    client = _client(store)
    accepted = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report", json=_report_payload()
    )
    assert accepted.status_code == 201
    response = client.get(
        f"/v1/missions/{_MISSION_ID}/coverage-report/rejections",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    )
    assert response.status_code == 200
    assert response.json()["rejectionCount"] == 0


def test_rejections_survive_restart(tmp_path: Path) -> None:
    """재기동해도 남는다 — 감사 기록이 프로세스 수명에 묶이면 감사가 아니다."""
    missions = _mission_store(tmp_path)
    journal_path = tmp_path / "coverage.jsonl"
    journal = DurableJournal(journal_path)
    first = CoverageReportStore(journal, mission_store=missions)
    assert (
        first.record(
            CoverageReport.model_validate(_report_payload(completion="COMPLETED", hazard=0.5)),
            now=_NOW,
            reported_by="edge-1",
        ).verdict
        is CoverageReportVerdict.UNSUPPORTED_COMPLETION
    )
    journal.close()

    reborn = DurableJournal(journal_path)
    try:
        reopened = CoverageReportStore(reborn, mission_store=missions)
        rejections = reopened.rejections(_MISSION_ID)
    finally:
        reborn.close()
    assert len(rejections) == 1
    assert rejections[0].verdict is CoverageReportVerdict.UNSUPPORTED_COMPLETION
    assert rejections[0].reported_by == "edge-1"


# ── 임무 실행 생애주기 결선 (ADR-KSI-019 G2) ──────────────────────────


def _client_with_execution(
    tmp_path: Path,
) -> tuple[TestClient, MissionExecutionStore]:
    """커버리지 접수 + 실행 상태 투영 조립.

    두 원장이 **같은 발급 원장**을 공유해야 한다 — 서로 다른 MissionStore 를 쓰면
    한쪽이 임무를 모르는 조립이 되어 검증이 공허해진다.
    """
    mission_store = _mission_store(tmp_path, assigned_device_id=_DEVICE_ID)
    coverage_store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"), mission_store=mission_store
    )
    execution_store = MissionExecutionStore(
        DurableJournal(tmp_path / "mission-execution.jsonl"), mission_store=mission_store
    )
    app = FastAPI()
    mount_auth(app, _registry())
    mount_coverage_reports(app, coverage_store, execution_store)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_DEVICE_TOKEN}"})
    return client, execution_store


def test_completed_report_marks_the_mission_completed(tmp_path: Path) -> None:
    client, execution = _client_with_execution(tmp_path)

    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report", json=_report_payload()
    )

    assert response.status_code == 201, response.text
    assert execution.effective_status(_MISSION_ID) is MissionExecutionStatus.COMPLETED


@pytest.mark.parametrize("completion", ["ABORTED_SAFE", "FAILED", "COMPLETED_WITH_GAPS"])
def test_non_completed_report_marks_the_mission_ended_incomplete(
    tmp_path: Path, completion: str
) -> None:
    client, execution = _client_with_execution(tmp_path)

    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(completion=completion),
    )

    assert response.status_code == 201, response.text
    assert (
        execution.effective_status(_MISSION_ID) is MissionExecutionStatus.ENDED_INCOMPLETE
    )


def test_rejected_report_does_not_move_the_execution_status(tmp_path: Path) -> None:
    """[핵심] 거부된 보고는 실행 상태를 옮기지 않는다.

    RECORDED 만 완료 판정 권위를 가진다(``CoverageReportStore._reject``). 거부된
    주장이 실행 상태를 옮기면 그 값이 화면에서 사실처럼 읽힌다.
    """
    client, execution = _client_with_execution(tmp_path)

    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(cells=[]),  # 관찰 증거 0건 → NO_COVERAGE_EVIDENCE
    )

    assert response.status_code == 422
    assert execution.effective_status(_MISSION_ID) is MissionExecutionStatus.ISSUED


def test_a_later_report_corrects_the_projection(tmp_path: Path) -> None:
    """나중에 접수된 보고가 결론을 바꾸면 투영도 따라간다(COMPLETED ↔ ENDED_INCOMPLETE)."""
    client, execution = _client_with_execution(tmp_path)
    client.post(f"/v1/missions/{_MISSION_ID}/coverage-report", json=_report_payload())
    assert execution.effective_status(_MISSION_ID) is MissionExecutionStatus.COMPLETED

    client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(completion="ABORTED_SAFE"),
    )

    assert (
        execution.effective_status(_MISSION_ID) is MissionExecutionStatus.ENDED_INCOMPLETE
    )


def test_coverage_acceptance_survives_a_sealed_execution_journal(tmp_path: Path) -> None:
    """[핵심] 실행 상태 원장이 봉인돼도 커버리지 접수는 201 이다.

    완료 판정의 권위는 CoverageReport 원장이다(INV-010). 그 접수가 투영 원장의
    가용성에 좌우되면 권위가 뒤집힌다.
    """
    client, execution = _client_with_execution(tmp_path)
    # 투영 원장을 닫아 봉인 상태로 만든다 — 이후 모든 전이가 STORE_UNAVAILABLE 이
    # 된다(DurableJournal.close 가 sealed_reason 을 "closed" 로 세운다).
    execution._journal.close()  # noqa: SLF001

    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report", json=_report_payload()
    )

    assert response.status_code == 201, response.text
    assert execution.effective_status(_MISSION_ID) is MissionExecutionStatus.ISSUED


# ── 대사(reconciliation) — 검사 1: 산술적으로 불가능한 비율 ──────────────────


def test_a_single_cell_cannot_support_a_fractional_ratio(store: CoverageReportStore) -> None:
    """[핵심] 재현한 그 결함 — 칸 1개 + 비율 0.96 은 산술적으로 불가능하다.

    관찰 칸이 1개뿐이면 그 카테고리의 분모가 몇이든 1 이하다 — 분수로 만들 수
    있는 값은 0.0과 1.0뿐이다. 카테고리별 칸 수를 몰라도(서버는 위험구역/자산/
    일반 분류를 갖고 있지 않다) 이 논증은 성립한다.
    """
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=0.96,
            cells=[{"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"}],
        ),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "INSUFFICIENT_CELLS_FOR_RATIO"


def test_a_single_fully_observed_cell_is_not_flagged(store: CoverageReportStore) -> None:
    """칸 1개여도 비율이 정확히 1.0 이면 이 검사에 안 걸린다(정상 케이스 보존).

    이 사례는 waypoint_count=75·planned_coverage_ratio=1.0 인 기본 _mission_store
    픽스처를 그대로 쓰므로 검사 2(계획 초과)도 걸리지 않는다 — 순수하게 검사 1만
    분리해서 확인한다.
    """
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=1.0,
            cells=[{"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"}],
        ),
    )
    assert response.status_code == 201
    assert response.json()["verdict"] == "RECORDED"


def test_two_cells_with_a_fractional_ratio_is_not_flagged(store: CoverageReportStore) -> None:
    """칸이 2개면 이 검사가 안 걸린다 — 0.5 같은 값이 산술적으로 가능해진다."""
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=1.0,
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ],
        ),
    )
    assert response.status_code == 201


# ── 대사(reconciliation) — 검사 2: 계획 커버 추정치 초과 ──────────────────────


def test_reported_general_ratio_cannot_exceed_the_planned_estimate(tmp_path: Path) -> None:
    """[핵심] 계획 커버 추정치(0.85)를 초과한 일반영역 관찰(0.96)은 불가능하다.

    plannedCoverageRatio 는 이상적 촬영 조건을 가정한 상한이다(mission_plans.py
    가 발급 시점에 이미 이 값을 accessibleGeneralCoverage 요구치와 대조한다).
    계획된 경로만 날았다는 전제 하에, 실제 관찰이 그 상한을 넘을 수 없다.
    """
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"),
        mission_store=_mission_store(tmp_path, planned_coverage_ratio=0.85),
    )
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=0.96,
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ],
        ),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "EXCEEDS_PLANNED_COVERAGE"


def test_reported_ratio_within_the_planned_estimate_is_recorded(tmp_path: Path) -> None:
    """계획값 이하의 신고는 이 검사에 안 걸린다(정상 케이스 보존).

    general 은 기존 INV-010 임계(≥0.95)도 만족해야 하므로 planned_coverage_ratio
    를 0.95 이상으로 잡는다 — 0.85 처럼 낮은 계획값은 유효한 COMPLETED 보고 자체가
    성립할 수 없다(어떤 general 값도 0.95 미만이면 기존 임계에 걸리고, 0.95 이상이면
    항상 0.85 를 넘어 이 검사에 걸린다 — 두 제약이 동시에 만족 가능한 구간이 없다).
    """
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"),
        mission_store=_mission_store(tmp_path, planned_coverage_ratio=0.97),
    )
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=0.96,
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ],
        ),
    )
    assert response.status_code == 201


def test_missing_planned_ratio_skips_the_check_instead_of_rejecting(tmp_path: Path) -> None:
    """계획 추정치가 없는 임무(예: perimeter 패턴)는 이 검사를 건너뛴다 — 거부하지
    않는다(설계 결정: null이면 대사 불가로 표시할 뿐 막지 않는다)."""
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"),
        mission_store=_mission_store(tmp_path, planned_coverage_ratio=None),
    )
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=1.0,
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ],
        ),
    )
    assert response.status_code == 201


def test_the_check_does_not_apply_to_hazard_or_asset_ratios(tmp_path: Path) -> None:
    """검사 2는 accessibleGeneralRatio 하나에만 걸린다 — 위험구역·자산 비율은
    plannedCoverageRatio 와 다른 계산 기반이라 대상이 아니다(설계 결정).

    hazard·asset 은 INV-010 이 항상 정확히 1.0 을 요구하므로(그 아래는 이미
    UNSUPPORTED_COMPLETION 으로 거부된다) planned_coverage_ratio=0.97 보다 큰
    값(1.0)을 항상 갖는다 — 검사 2 가 실수로 이 둘에도 적용된다면 이 보고는
    거부돼야 하는데, 실제로는 general(0.96)만 대조되므로 통과해야 한다.
    """
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"),
        mission_store=_mission_store(tmp_path, planned_coverage_ratio=0.97),
    )
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=0.96,
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ],
        ),
    )
    assert response.status_code == 201


# ── 조회 응답 — 귀속·대사 ──────────────────────────────────────────────────


def test_view_always_carries_the_attribution_note(store: CoverageReportStore) -> None:
    """[핵심] 귀속 캡션은 대사 가능 여부와 무관하게 항상 채워진다."""
    client = _client(store)
    client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ]
        ),
    )
    response = client.get(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    )
    body = response.json()
    assert body["ratioAttributionNote"]
    assert "기체" in body["ratioAttributionNote"]


def test_view_carries_the_planned_ratio_when_available(store: CoverageReportStore) -> None:
    """기본 픽스처는 planned_coverage_ratio=1.0 이므로 그 값이 그대로 나온다."""
    client = _client(store)
    client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ]
        ),
    )
    response = client.get(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    )
    body = response.json()
    assert body["plannedGeneralCoverageRatio"] == pytest.approx(1.0)
    assert body["plannedGeneralCoverageUnavailableReason"] is None


def test_view_explains_when_the_planned_ratio_is_unavailable(tmp_path: Path) -> None:
    """계획 추정치가 없는 임무는 null + 이름 붙인 사유를 낸다("—" 가 아니다)."""
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"),
        mission_store=_mission_store(tmp_path, planned_coverage_ratio=None),
    )
    client = _client(store)
    client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ]
        ),
    )
    response = client.get(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    )
    body = response.json()
    assert body["plannedGeneralCoverageRatio"] is None
    assert body["plannedGeneralCoverageUnavailableReason"]
