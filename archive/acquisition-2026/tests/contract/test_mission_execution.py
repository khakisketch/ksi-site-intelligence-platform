"""임무 실행 생애주기 — 전이표 (ADR-KSI-019 G2).

``MissionRecord`` 는 **발급 기록**이라 "이 임무가 실제로 날았는가"에 답하지 못했다.
이 파일은 그 축의 전이 규칙을 고정한다 — 저장소·API·훅은 같은 파일 뒤쪽에서 이어
검증한다.
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
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_execution import (
    MissionExecutionRecoveryError,
    MissionExecutionStore,
    MissionExecutionVerdict,
    mount_mission_execution,
)
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_domain.enums import (
    _ALLOWED_MISSION_EXECUTION_TRANSITIONS,  # noqa: PLC2701 -- 전이표 전수 검사를 위한 의도적 내부 접근
    IllegalMissionExecutionTransitionError,
    MissionExecutionStatus,
    assert_mission_execution_transition,
    can_mission_execution_transition,
)

_ME = MissionExecutionStatus


@pytest.mark.parametrize(
    ("cur", "nxt"),
    [
        (_ME.ISSUED, _ME.DISPATCHED),
        (_ME.DISPATCHED, _ME.ACTIVATED),
        (_ME.ACTIVATED, _ME.COMPLETED),
        (_ME.ACTIVATED, _ME.ENDED_INCOMPLETE),
    ],
)
def test_forward_path_is_allowed(
    cur: MissionExecutionStatus, nxt: MissionExecutionStatus
) -> None:
    assert_mission_execution_transition(cur, nxt)
    assert can_mission_execution_transition(cur, nxt) is True


def test_skipping_forward_is_allowed() -> None:
    """[핵심] 중간 단계를 건너뛴 완료 보고를 거부하지 않는다.

    운영자가 KMZ 를 손으로 옮겨 날린 임무는 DISPATCHED·ACTIVATED 신호가 아예 없다
    (ADR-KSI-019 G3 — 실기 확인 전까지 수동 이관이 공식 경로). 그 임무의 커버리지
    보고를 실행 상태 때문에 거부하면 INV-010 의 완료 판정 권위가 이 필드로 넘어간다.
    """
    assert_mission_execution_transition(_ME.ISSUED, _ME.COMPLETED)
    assert_mission_execution_transition(_ME.ISSUED, _ME.ENDED_INCOMPLETE)
    assert_mission_execution_transition(_ME.ISSUED, _ME.ACTIVATED)
    assert_mission_execution_transition(_ME.DISPATCHED, _ME.COMPLETED)


@pytest.mark.parametrize(
    ("cur", "nxt"),
    [
        (_ME.ACTIVATED, _ME.DISPATCHED),
        (_ME.DISPATCHED, _ME.ISSUED),
        (_ME.COMPLETED, _ME.ACTIVATED),
        (_ME.COMPLETED, _ME.DISPATCHED),
        (_ME.ENDED_INCOMPLETE, _ME.ISSUED),
    ],
)
def test_backward_transition_is_refused(
    cur: MissionExecutionStatus, nxt: MissionExecutionStatus
) -> None:
    """뒤로 가는 전이는 없다 — 관측된 사실을 되돌리지 않는다."""
    with pytest.raises(IllegalMissionExecutionTransitionError):
        assert_mission_execution_transition(cur, nxt)
    assert can_mission_execution_transition(cur, nxt) is False


def test_completion_states_may_correct_each_other() -> None:
    """[핵심] COMPLETED ↔ ENDED_INCOMPLETE 는 양방향이다.

    완료 판정의 권위는 CoverageReport 원장이고(INV-010) 이 필드는 그 원장의
    **투영**이다. 나중에 접수된 보고가 결론을 바꾸면 투영도 따라가야 한다 —
    따라가지 않으면 두 표면이 서로 다른 완료를 말한다.
    """
    assert_mission_execution_transition(_ME.COMPLETED, _ME.ENDED_INCOMPLETE)
    assert_mission_execution_transition(_ME.ENDED_INCOMPLETE, _ME.COMPLETED)


def test_cancelled_is_terminal() -> None:
    """사람이 접은 임무를 시스템 신호가 되살리지 않는다."""
    for nxt in MissionExecutionStatus:
        assert can_mission_execution_transition(_ME.CANCELLED, nxt) is False


def test_completion_states_cannot_be_cancelled() -> None:
    """이미 끝난 비행을 취소할 수 없다 — 취소는 아직 안 끝난 임무에만 뜻이 있다."""
    for cur in (_ME.COMPLETED, _ME.ENDED_INCOMPLETE):
        assert can_mission_execution_transition(cur, _ME.CANCELLED) is False


def test_self_transition_is_refused() -> None:
    """같은 상태로의 전이는 없다 — 중복 신호가 원장에 빈 레코드를 쌓지 않는다."""
    for status in MissionExecutionStatus:
        assert can_mission_execution_transition(status, status) is False


def test_transition_table_covers_every_member() -> None:
    """표 완전성 — 새 멤버가 추가됐는데 표를 안 고치면 여기서 드러난다."""
    assert set(_ALLOWED_MISSION_EXECUTION_TRANSITIONS) == set(MissionExecutionStatus)


def test_in_flight_status_does_not_exist() -> None:
    """[핵심] 서버가 모르는 사실을 상태로 만들지 않는다.

    KSI 는 비행 중 텔레메트리를 받지 않는다(INV-001). "지금 날고 있다"는 서버가
    아는 사실이 아니므로 그 이름의 상태를 두지 않는다 — 두면 화면이 그 값을
    사실처럼 보여줄 자리가 생긴다.
    """
    assert not any("FLIGHT" in member.value for member in MissionExecutionStatus)
    assert not any("FLYING" in member.value for member in MissionExecutionStatus)


# ADR-KSI-021 §9 — packages/domain/src/ksi_domain/enums.py 무변경 고정.
_DOMAIN_ENUMS_PATH = (
    Path(__file__).resolve().parents[2] / "packages" / "domain" / "src" / "ksi_domain" / "enums.py"
)
_DOMAIN_ENUMS_SHA256 = "cc744a627b1328e921f48049c6e2f9308717e9604d9287920a8ef4c4c6f07932"


def test_domain_enums_file_is_unchanged_by_flight_start_receipts_work() -> None:
    """[핵심] ADR-KSI-021 §9 — 이 파일은 flight-start-receipts 접수 작업으로 1바이트도 안 바뀐다.

    ``MissionExecutionStatus`` 에 ``IN_FLIGHT`` 류 멤버를 추가하고 싶은 유혹은 그
    접수 작업 내내 존재한다(§9: "'기체가 날고 있다'는 상태가 아니다 — IN_FLIGHT를
    만들지 않는다"). ``test_in_flight_status_does_not_exist`` 처럼 멤버 이름만
    대조하면 그 유혹을 다 못 잡는다 — 문서·주석만 슬쩍 바뀌는 것도 놓친다. 그래서
    파일 전체를 해시로 고정한다.

    이 시험이 실패하면 두 경우뿐이다: (1) ADR-KSI-021 범위의 작업이 이 파일을
    건드렸다 — 되돌려라. (2) 이 파일이 **이 ADR 과 무관한** 이유로 정당하게
    바뀌었다 — 그렇다면 사람이 새 내용을 검토해 ``MissionExecutionStatus`` 멤버
    집합이 그대로인지 확인한 뒤 아래 해시 상수를 갱신한다(이 시험 자체를 지우지
    않는다).
    """
    digest = hashlib.sha256(_DOMAIN_ENUMS_PATH.read_bytes()).hexdigest()
    assert digest == _DOMAIN_ENUMS_SHA256, (
        "packages/domain/src/ksi_domain/enums.py 가 변경됐다 — "
        "ADR-KSI-021 §9는 MissionExecutionStatus 에 멤버를 추가하지 않는다"
    )


# ── 원장 (MissionExecutionStore) ────────────────────────────────────────


_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
_SITE_FRAME: dict[str, str] = {
    "crs": "EPSG:5186",
    "verticalDatum": "KNGeoid2018",
    "unit": "meter",
    "transformVersion": "1.0.0",
}


def _mission_store(
    tmp_path: Path,
    *,
    mission_ids: tuple[str, ...] = ("m-1",),
    journal: DurableJournal | None = None,
) -> MissionStore:
    """``journal`` 을 직접 주면 재생 테스트가 그 핸들을 닫을 수 있다(단일 writer 잠금)."""
    store = MissionStore(
        journal if journal is not None else DurableJournal(tmp_path / "missions.jsonl")
    )
    for mission_id in mission_ids:
        assert (
            store.record_issuance(
                MissionRecord(
                    mission_id=mission_id,
                    site_id="site-a",
                    mission_type="BASELINE_MAPPING",
                    artifact_kind="contract",
                    contract={"missionId": mission_id, "siteFrame": _SITE_FRAME},
                    kmz_sha256=None,
                    route_pattern=None,
                    waypoint_count=None,
                    planned_coverage_ratio=None,
                    issued_at=_NOW,
                    issued_by="op-1",
                )
            ).value
            == "RECORDED"
        )
    return store


def _execution_store(
    tmp_path: Path, *, journal: DurableJournal | None = None
) -> MissionExecutionStore:
    return MissionExecutionStore(
        journal if journal is not None else DurableJournal(tmp_path / "mission-execution.jsonl"),
        mission_store=_mission_store(tmp_path),
    )


def test_mission_with_no_record_reads_as_issued(tmp_path: Path) -> None:
    """[핵심] 레코드 부재가 ISSUED 다 — 발급 경로를 건드리지 않는다.

    발급 시점에 실행 레코드를 함께 쓰면 ADR-KSI-008 §3 의 "durable 기록 전 201
    금지" 경로에 두 번째 원장 쓰기가 끼어들고, 그 쓰기가 실패할 때 이미 성립한
    계약 발급이 실패한다.
    """
    store = _execution_store(tmp_path)

    assert store.status_of("m-1") is None
    assert store.effective_status("m-1") is _ME.ISSUED
    assert store.history("m-1") == []


def test_transition_records_and_projects(tmp_path: Path) -> None:
    store = _execution_store(tmp_path)

    result = store.transition(
        "m-1", _ME.DISPATCHED, detail="RC 로 이관", actor="op-1", now=_NOW
    )

    assert result.verdict is MissionExecutionVerdict.TRANSITIONED
    assert store.effective_status("m-1") is _ME.DISPATCHED
    assert store.status_of("m-1") is _ME.DISPATCHED
    history = store.history("m-1")
    assert len(history) == 1
    assert history[0].before is _ME.ISSUED
    assert history[0].after is _ME.DISPATCHED
    assert history[0].updated_by == "op-1"
    assert history[0].detail == "RC 로 이관"


def test_unknown_mission_is_refused(tmp_path: Path) -> None:
    """발급된 적 없는 임무의 실행 상태는 받지 않는다(coverage_reports 와 같은 원칙)."""
    store = _execution_store(tmp_path)

    result = store.transition("nope", _ME.DISPATCHED, detail=None, actor="op-1", now=_NOW)

    assert result.verdict is MissionExecutionVerdict.UNKNOWN_MISSION
    assert store.history("nope") == []


def test_illegal_transition_is_typed_not_raised(tmp_path: Path) -> None:
    store = _execution_store(tmp_path)
    store.transition("m-1", _ME.CANCELLED, detail=None, actor="op-1", now=_NOW)

    result = store.transition("m-1", _ME.COMPLETED, detail=None, actor="sys", now=_NOW)

    assert result.verdict is MissionExecutionVerdict.ILLEGAL_TRANSITION
    assert store.effective_status("m-1") is _ME.CANCELLED


def test_naive_now_is_refused(tmp_path: Path) -> None:
    store = _execution_store(tmp_path)

    with pytest.raises(ValueError, match="tz-aware"):
        store.transition(
            "m-1",
            _ME.DISPATCHED,
            detail=None,
            actor="op-1",
            now=datetime(2026, 8, 15, 12, 0),  # noqa: DTZ001
        )


def test_replay_reconstructs_status_and_history(tmp_path: Path) -> None:
    mission_journal = DurableJournal(tmp_path / "missions.jsonl")
    journal = DurableJournal(tmp_path / "mission-execution.jsonl")
    store = MissionExecutionStore(
        journal, mission_store=_mission_store(tmp_path, journal=mission_journal)
    )
    store.transition("m-1", _ME.DISPATCHED, detail=None, actor="o", now=_NOW)
    store.transition("m-1", _ME.ACTIVATED, detail=None, actor="o", now=_NOW)
    journal.close()
    mission_journal.close()

    reopened = MissionExecutionStore(
        DurableJournal(tmp_path / "mission-execution.jsonl"),
        mission_store=MissionStore(DurableJournal(tmp_path / "missions.jsonl")),
    )

    assert reopened.effective_status("m-1") is _ME.ACTIVATED
    assert len(reopened.history("m-1")) == 2


def _write_raw_journal(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def test_replay_refuses_an_illegal_sequence(tmp_path: Path) -> None:
    """[핵심] 손으로 고친 원장이 불법 전이를 되살릴 수 없다.

    sites._apply_transitioned·processing_jobs._replay_transition 과 같은 원칙 —
    재생도 live 와 같은 전이표를 다시 태운다.
    """
    ts = _NOW.isoformat()
    _write_raw_journal(
        tmp_path / "mission-execution.jsonl",
        [
            {"kind": "mission-execution-transitioned", "missionId": "m-1",
             "before": "ISSUED", "after": "CANCELLED", "ts": ts, "actor": "o", "detail": None},
            {"kind": "mission-execution-transitioned", "missionId": "m-1",
             "before": "CANCELLED", "after": "COMPLETED", "ts": ts, "actor": "o", "detail": None},
        ],
    )

    with pytest.raises(MissionExecutionRecoveryError):
        MissionExecutionStore(
            DurableJournal(tmp_path / "mission-execution.jsonl"),
            mission_store=_mission_store(tmp_path),
        )


def test_replay_refuses_a_forged_before_value(tmp_path: Path) -> None:
    """원장이 스스로 모순이면 조용히 덮어쓰지 않는다."""
    ts = _NOW.isoformat()
    _write_raw_journal(
        tmp_path / "mission-execution.jsonl",
        [
            {"kind": "mission-execution-transitioned", "missionId": "m-1",
             "before": "ISSUED", "after": "DISPATCHED", "ts": ts, "actor": "o", "detail": None},
            # before 가 실제 현재 상태(DISPATCHED)와 다르다.
            {"kind": "mission-execution-transitioned", "missionId": "m-1",
             "before": "ISSUED", "after": "COMPLETED", "ts": ts, "actor": "o", "detail": None},
        ],
    )

    with pytest.raises(MissionExecutionRecoveryError):
        MissionExecutionStore(
            DurableJournal(tmp_path / "mission-execution.jsonl"),
            mission_store=_mission_store(tmp_path),
        )


def test_replay_refuses_naive_timestamp(tmp_path: Path) -> None:
    _write_raw_journal(
        tmp_path / "mission-execution.jsonl",
        [
            {"kind": "mission-execution-transitioned", "missionId": "m-1",
             "before": "ISSUED", "after": "DISPATCHED",
             "ts": "2026-08-15T12:00:00", "actor": "o", "detail": None},
        ],
    )

    with pytest.raises(MissionExecutionRecoveryError):
        MissionExecutionStore(
            DurableJournal(tmp_path / "mission-execution.jsonl"),
            mission_store=_mission_store(tmp_path),
        )


def test_replay_refuses_unknown_kind(tmp_path: Path) -> None:
    _write_raw_journal(
        tmp_path / "mission-execution.jsonl",
        [{"kind": "something-else", "missionId": "m-1", "ts": _NOW.isoformat()}],
    )

    with pytest.raises(MissionExecutionRecoveryError):
        MissionExecutionStore(
            DurableJournal(tmp_path / "mission-execution.jsonl"),
            mission_store=_mission_store(tmp_path),
        )


# ── API 표면 ────────────────────────────────────────────────────────────


_OPERATOR_TOKEN = "me-operator"  # noqa: S105 -- 테스트 고정 토큰
_VIEWER_TOKEN = "me-viewer"  # noqa: S105
_DEVICE_TOKEN = "me-device"  # noqa: S105


def _api_client(tmp_path: Path) -> TestClient:
    """mount_auth + mount_mission_execution 최소 조립 — 이 표면만 본다."""

    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_OPERATOR_TOKEN),
                principal=Principal(
                    principal_id="op-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="viewer-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_DEVICE_TOKEN),
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
    mount_mission_execution(app, _execution_store(tmp_path))
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_OPERATOR_TOKEN}"})
    return client


def _declare(
    client: TestClient, mission_id: str, target: str, *, token: str = _OPERATOR_TOKEN, **body: Any
) -> Any:
    return client.post(
        f"/v1/missions/{mission_id}/execution-transitions",
        json={"targetStatus": target, **body},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_operator_can_declare_dispatched(tmp_path: Path) -> None:
    """운영자가 KMZ 를 손으로 옮겼다는 사실을 서버가 기록할 수 있어야 한다.

    실기 확인 전까지 수동 이관이 공식 경로다(ADR-KSI-019 G3). 그 경로를 서버가
    기록하지 못하면 임무 원장에 "날았는지 모른다"만 남는다.
    """
    client = _api_client(tmp_path)

    response = _declare(client, "m-1", "DISPATCHED", detail="RC Plus 2 로 KMZ 이관")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "DISPATCHED"
    assert client.get("/v1/missions/m-1/execution").json()["status"] == "DISPATCHED"


def test_operator_can_cancel(tmp_path: Path) -> None:
    client = _api_client(tmp_path)

    assert _declare(client, "m-1", "CANCELLED").status_code == 200
    assert client.get("/v1/missions/m-1/execution").json()["status"] == "CANCELLED"


@pytest.mark.parametrize("target", ["ACTIVATED", "COMPLETED", "ENDED_INCOMPLETE", "ISSUED"])
def test_operator_cannot_declare_machine_reported_states(tmp_path: Path, target: str) -> None:
    """[핵심] 사람이 장비·커버리지가 만드는 사실을 손으로 찍을 수 없다.

    COMPLETED 는 CoverageReport 접수가 만드는 사실이고(INV-010), ACTIVATED 는
    Edge 의 서명 receipt 가 만든다. 사람이 찍을 수 있으면 그 상태는 근거가 아니라
    주장이 된다 — processing_jobs 의 "PROCESSING_WORK 는 어느 Role 에도 없다"와
    같은 원칙이다.
    """
    client = _api_client(tmp_path)

    response = _declare(client, "m-1", target)

    assert response.status_code == 403
    assert client.get("/v1/missions/m-1/execution").json()["status"] == "ISSUED"


def test_viewer_cannot_declare_transitions(tmp_path: Path) -> None:
    client = _api_client(tmp_path)

    assert _declare(client, "m-1", "DISPATCHED", token=_VIEWER_TOKEN).status_code == 403


def test_get_execution_returns_issued_for_untouched_mission(tmp_path: Path) -> None:
    client = _api_client(tmp_path)

    body = client.get("/v1/missions/m-1/execution").json()

    assert body["status"] == "ISSUED"
    assert body["history"] == []
    assert body["updatedAt"] is None


def test_get_execution_is_404_for_unknown_mission(tmp_path: Path) -> None:
    client = _api_client(tmp_path)

    assert client.get("/v1/missions/nope/execution").status_code == 404


def test_declare_on_unknown_mission_is_404(tmp_path: Path) -> None:
    client = _api_client(tmp_path)

    assert _declare(client, "nope", "DISPATCHED").status_code == 404


def test_illegal_declaration_is_409(tmp_path: Path) -> None:
    client = _api_client(tmp_path)
    _declare(client, "m-1", "CANCELLED")

    assert _declare(client, "m-1", "DISPATCHED").status_code == 409


def test_history_is_exposed_in_order(tmp_path: Path) -> None:
    client = _api_client(tmp_path)
    _declare(client, "m-1", "DISPATCHED", detail="1차 이관")

    body = client.get("/v1/missions/m-1/execution").json()

    assert [e["after"] for e in body["history"]] == ["DISPATCHED"]
    assert body["history"][0]["updatedBy"] == "op-1"
    assert body["history"][0]["detail"] == "1차 이관"


def test_device_cannot_read_execution(tmp_path: Path) -> None:
    """EDGE_DEVICE 는 MISSIONS_READ 를 갖지 않는다 — 임무 원장 열람 표면이 아니다."""
    client = _api_client(tmp_path)

    response = client.get(
        "/v1/missions/m-1/execution", headers={"Authorization": f"Bearer {_DEVICE_TOKEN}"}
    )

    assert response.status_code == 403


# ── lone surrogate — durable 원장 영구 오염 (2026-08-18 전수 조사 Class D) ────


def test_lone_surrogate_detail_is_rejected_before_the_journal_is_written(
    tmp_path: Path,
) -> None:
    """[high-risk regression] ``detail`` 의 lone surrogate 는 **기록 전에** 거부된다.

    ``detail`` 은 제약이 없어 요청 검증을 통과한다. 그대로 두면 순서가 이렇게 된다 —
    ①journal 에 기록 성공(``ensure_ascii=True`` 라 ASCII 이스케이프로 들어간다)
    ②projection 전이 완료 ③**그 뒤** 응답 모델 직렬화에서 ``UnicodeEncodeError``.
    즉 500 이 나가지만 전이는 이미 일어났고, 그 임무의 조회·후속 전이가 **영원히**
    500 이 된다. 재시작해도 replay 가 성공해 그대로 재현된다 — 원장을 손으로 고쳐야
    복구된다. FIELD_OPERATOR 토큰이면 누구나 쏠 수 있다.

    그래서 단언이 3단이다: ①422 ②원장 미기록 ③그 뒤 정상 흐름이 살아 있다.
    """
    client = _api_client(tmp_path)
    # 500 을 예외로 튀우지 않고 응답으로 관측한다 — 기본 클라이언트면 "에러"로만
    # 보이고 "422 가 아니다"로는 안 보인다.
    probe = TestClient(client.app, raise_server_exceptions=False)
    probe.headers.update(dict(client.headers))

    hostile = probe.post(
        "/v1/missions/m-1/execution-transitions",
        content=json.dumps(
            {"targetStatus": "DISPATCHED", "detail": "a\ud800b"}, ensure_ascii=True
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert hostile.status_code == 422, f"{hostile.status_code} {hostile.text[:200]}"

    # ② 원장에 아무것도 안 쓰였다 — 거부가 기록보다 앞이어야 한다.
    journal_path = tmp_path / "mission-execution.jsonl"
    if journal_path.exists():
        assert "\\ud800" not in journal_path.read_text(encoding="utf-8")

    # ③ 그 뒤 정상 흐름이 살아 있다 — 오염됐다면 여기가 500 이 된다.
    ok = _declare(probe, "m-1", "DISPATCHED", detail="정상 이관")
    assert ok.status_code == 200, f"{ok.status_code} {ok.text[:200]}"
    read_back = probe.get("/v1/missions/m-1/execution")
    assert read_back.status_code == 200, f"{read_back.status_code} {read_back.text[:200]}"
