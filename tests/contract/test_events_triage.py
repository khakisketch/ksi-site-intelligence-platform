"""Event projection·트리아지·감사 계약 (ADR-KSI-008 §3/§4).

green≠작동 초점: 픽스처로 완제품 상태(``status=CONFIRMED_EVENT`` 등)를 직접
주입하지 않는다 — FINDING 사건은 실제 projection 전이(CANDIDATE→
EVIDENCE_COLLECTION→FINDING)를 밟아 만든다. HTTP 배선은 수동 조립
(``FastAPI()`` + ``mount_auth`` + ``mount_events``)으로 검증한다.
"""

from __future__ import annotations

from dataclasses import replace
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
from ksi_core.events import (
    EventStore,
    EventStoreRecoveryError,
    EventVerdict,
    make_event_key,
    mount_events,
)
from ksi_domain.enums import EventStatus, TriageStatus
from ksi_event_contracts.offline_sync import payload_digest

_FPR = "a" * 64
_FIELD_OPERATOR_TOKEN = "field-operator-plaintext-token"  # noqa: S105 -- 테스트 고정값
_VIEWER_TOKEN = "viewer-plaintext-token"  # noqa: S105
_OTHER_ORG_FIELD_OPERATOR_TOKEN = "other-org-field-operator-plaintext-token"  # noqa: S105
_OTHER_ORG_VIEWER_TOKEN = "other-org-viewer-plaintext-token"  # noqa: S105


# ── 픽스처 빌더 ──────────────────────────────────────────────────────────


def _bundle_payload(
    event_id: str = "evt-001",
    *,
    status: str = "CANDIDATE",
    severity: str | None = None,
    evidence: dict[str, Any] | None = None,
    site_id: str = "site-1",
    mission_id: str = "mission-1",
    occurred_at: str = "2026-07-27T06:00:00Z",
    spatial_context: dict[str, Any] | None = None,
    event_type: str = "PERSON_PRESENT",
) -> dict[str, Any]:
    """유효한 EventBundle v1.2 payload(lineage.classification 포함)."""
    body: dict[str, Any] = {
        "schemaVersion": "1.2",
        "eventId": event_id,
        "missionId": mission_id,
        "siteId": site_id,
        "eventType": event_type,
        "occurredAt": occurred_at,
        "status": status,
        "entities": ["ent-trk-001"],
        "spatialContext": spatial_context if spatial_context is not None else {"zone": "A"},
        "reasoning": {},
        "evidence": evidence if evidence is not None else {},
        "lineage": {
            "edgeVersion": "triage-test-edge-1.0",
            "modelVersions": {"detector": "stub"},
            "policyVersion": "triage-test-policy-1",
            "calibrationProfileId": "triage-test-cal-1",
            "classification": {
                "ent-trk-001": {
                    "entityClass": "Person",
                    "ontologyVersion": "ksi-ontology-v1",
                    "source": {
                        "taxonomy": "COCO-2017",
                        "sourceClassIds": [0],
                        "sourceClassNames": ["person"],
                    },
                    "entityFingerprint": _FPR,
                }
            },
        },
    }
    if severity is not None:
        body["severity"] = severity
    return body


def _key(event_id: str, *, edge_device_id: str = "edge-001") -> str:
    """서버 정본 사건 신원 — 장비 스코프 event_key(구현과 같은 규칙)."""
    return make_event_key(edge_device_id, event_id)


def _project(
    store: EventStore,
    payload: dict[str, Any],
    *,
    edge_device_id: str = "edge-001",
    received_at: datetime | None = None,
    organization_id: str = "legacy",
) -> EventVerdict:
    return store.project_bundle(
        payload,
        edge_device_id=edge_device_id,
        received_at=received_at or datetime.now(UTC),
        organization_id=organization_id,
    )


def _project_to_finding(
    store: EventStore,
    event_id: str,
    *,
    severity: str | None = None,
    evidence: dict[str, Any] | None = None,
    site_id: str = "site-1",
    mission_id: str = "mission-1",
    occurred_at: str = "2026-07-27T06:00:00Z",
) -> None:
    """실제 상태전이(CANDIDATE→EVIDENCE_COLLECTION→FINDING)로 FINDING 사건을 만든다."""

    def payload(status: str) -> dict[str, Any]:
        return _bundle_payload(
            event_id,
            status=status,
            severity=severity,
            evidence=evidence,
            site_id=site_id,
            mission_id=mission_id,
            occurred_at=occurred_at,
        )

    assert _project(store, payload("CANDIDATE")) is EventVerdict.PROJECTED
    assert _project(store, payload("EVIDENCE_COLLECTION")) is EventVerdict.EVENT_UPDATED
    assert _project(store, payload("FINDING")) is EventVerdict.EVENT_UPDATED


def _actor(principal_id: str = "op-1", role: Role = Role.FIELD_OPERATOR) -> Principal:
    return Principal(
        principal_id=principal_id, kind=PrincipalKind.OPERATOR, role=role, device_id=None
    )


@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    return EventStore(DurableJournal(tmp_path / "events" / "journal.jsonl"))


# ── projection 4분기 ─────────────────────────────────────────────────────


def test_project_bundle_new_event_is_projected(store: EventStore) -> None:
    verdict = _project(store, _bundle_payload("evt-new"))
    assert verdict is EventVerdict.PROJECTED
    record = store.get(_key("evt-new"))
    assert record is not None
    assert record.status is EventStatus.CANDIDATE
    assert record.triage is TriageStatus.NONE
    assert record.assignee is None
    assert len(record.transitions) == 1


def test_project_bundle_duplicate_digest_is_noop(store: EventStore) -> None:
    payload = _bundle_payload("evt-dup")
    now = datetime.now(UTC)
    assert _project(store, payload, received_at=now) is EventVerdict.PROJECTED
    assert _project(store, payload, received_at=now) is EventVerdict.DUPLICATE_PROJECTION
    record = store.get(_key("evt-dup"))
    assert record is not None
    assert len(record.transitions) == 1, "재전송(no-op)이 이력에 잘못 반영됐다"


def test_project_bundle_legal_update_replaces_bundle(store: EventStore) -> None:
    _project(store, _bundle_payload("evt-upd", status="CANDIDATE"))
    verdict = _project(store, _bundle_payload("evt-upd", status="EVIDENCE_COLLECTION"))
    assert verdict is EventVerdict.EVENT_UPDATED
    record = store.get(_key("evt-upd"))
    assert record is not None
    assert record.status is EventStatus.EVIDENCE_COLLECTION
    assert len(record.transitions) == 2


def test_project_bundle_illegal_update_is_diverged(store: EventStore) -> None:
    """CANDIDATE 는 EVIDENCE_COLLECTION/DISMISSED 만 허용 — FINDING 직행은 diverged."""
    _project(store, _bundle_payload("evt-div", status="CANDIDATE"))
    verdict = _project(store, _bundle_payload("evt-div", status="FINDING"))
    assert verdict is EventVerdict.UPDATE_DIVERGED
    record = store.get(_key("evt-div"))
    assert record is not None
    assert record.status is EventStatus.CANDIDATE, "diverged 는 저장 상태를 바꾸지 않는다"
    assert record.last_conflict_at is not None


# ── 확정 실통과 ──────────────────────────────────────────────────────────


def test_confirm_assign_progress_full_path(store: EventStore) -> None:
    _project_to_finding(store, "evt-happy")
    now = datetime.now(UTC)

    confirm = store.triage_transition(
        _key("evt-happy"),
        target=EventStatus.CONFIRMED_EVENT,
        triage_target=None,
        reason="현장 확인 완료",
        assignee=None,
        actor=_actor(),
        now=now,
    )
    assert confirm.verdict is EventVerdict.TRANSITIONED
    assert confirm.record is not None
    assert confirm.record.status is EventStatus.CONFIRMED_EVENT
    assert confirm.record.transitions[-1]["evidenceSnapshot"] == {
        "spatialContext": {"zone": "A"}
    }

    assign = store.triage_transition(
        _key("evt-happy"),
        target=None,
        triage_target=TriageStatus.ASSIGNED,
        reason=None,
        assignee="operator-9",
        actor=_actor(),
        now=now,
    )
    assert assign.verdict is EventVerdict.TRANSITIONED
    assert assign.record is not None
    assert assign.record.triage is TriageStatus.ASSIGNED
    assert assign.record.assignee == "operator-9"

    progress = store.triage_transition(
        _key("evt-happy"),
        target=None,
        triage_target=TriageStatus.ACTION_IN_PROGRESS,
        reason=None,
        assignee=None,
        actor=_actor(),
        now=now,
    )
    assert progress.verdict is EventVerdict.TRANSITIONED
    assert progress.record is not None
    assert progress.record.triage is TriageStatus.ACTION_IN_PROGRESS
    assert progress.record.assignee == "operator-9", "재지정 없는 후속 전이는 배정자를 유지한다"


def test_candidate_direct_confirm_is_illegal(store: EventStore) -> None:
    _project(store, _bundle_payload("evt-skip", status="CANDIDATE"))
    result = store.triage_transition(
        _key("evt-skip"),
        target=EventStatus.CONFIRMED_EVENT,
        triage_target=None,
        reason="사유",
        assignee=None,
        actor=_actor(),
        now=datetime.now(UTC),
    )
    assert result.verdict is EventVerdict.ILLEGAL_TRANSITION


def test_assign_without_confirmed_status_is_illegal(store: EventStore) -> None:
    _project_to_finding(store, "evt-notconfirmed")
    result = store.triage_transition(
        _key("evt-notconfirmed"),
        target=None,
        triage_target=TriageStatus.ASSIGNED,
        reason=None,
        assignee="operator-1",
        actor=_actor(),
        now=datetime.now(UTC),
    )
    assert result.verdict is EventVerdict.ILLEGAL_TRANSITION


# ── EVIDENCE_INCOMPLETE ──────────────────────────────────────────────────


def test_confirm_high_without_clips_is_evidence_incomplete(store: EventStore) -> None:
    _project_to_finding(store, "evt-high-noclips", severity="HIGH", evidence={})
    result = store.triage_transition(
        _key("evt-high-noclips"),
        target=EventStatus.CONFIRMED_EVENT,
        triage_target=None,
        reason="사유",
        assignee=None,
        actor=_actor(),
        now=datetime.now(UTC),
    )
    assert result.verdict is EventVerdict.EVIDENCE_INCOMPLETE
    assert store.get(_key("evt-high-noclips")).status is EventStatus.FINDING  # type: ignore[union-attr]


def test_confirm_critical_missing_artifacts_is_evidence_incomplete(store: EventStore) -> None:
    _project_to_finding(
        store,
        "evt-critical-missing",
        severity="CRITICAL",
        evidence={"clips": ["clip-1.mp4"]},  # riskField/trajectory/viewpoint 누락
    )
    result = store.triage_transition(
        _key("evt-critical-missing"),
        target=EventStatus.CONFIRMED_EVENT,
        triage_target=None,
        reason="사유",
        assignee=None,
        actor=_actor(),
        now=datetime.now(UTC),
    )
    assert result.verdict is EventVerdict.EVIDENCE_INCOMPLETE


def test_confirm_critical_with_only_string_references_is_evidence_incomplete(
    store: EventStore,
) -> None:
    _project_to_finding(
        store,
        "evt-critical-full",
        severity="CRITICAL",
        evidence={
            "clips": ["clip-1.mp4"],
            "riskFieldArtifact": "risk-1",
            "trajectoryArtifact": "traj-1",
            "viewpointHistoryArtifact": "vph-1",
        },
    )
    result = store.triage_transition(
        _key("evt-critical-full"),
        target=EventStatus.CONFIRMED_EVENT,
        triage_target=None,
        reason="사유",
        assignee=None,
        actor=_actor(),
        now=datetime.now(UTC),
    )
    assert result.verdict is EventVerdict.EVIDENCE_INCOMPLETE
    assert result.detail is not None and "검증 스토리지" in result.detail


# ── DISMISSED reason 필수 ────────────────────────────────────────────────


def test_dismissed_requires_reason(store: EventStore) -> None:
    _project_to_finding(store, "evt-dismiss")
    missing = store.triage_transition(
        _key("evt-dismiss"),
        target=EventStatus.DISMISSED,
        triage_target=None,
        reason=None,
        assignee=None,
        actor=_actor(),
        now=datetime.now(UTC),
    )
    assert missing.verdict is EventVerdict.INVALID_REQUEST

    blank = store.triage_transition(
        _key("evt-dismiss"),
        target=EventStatus.DISMISSED,
        triage_target=None,
        reason="   ",
        assignee=None,
        actor=_actor(),
        now=datetime.now(UTC),
    )
    assert blank.verdict is EventVerdict.INVALID_REQUEST

    ok = store.triage_transition(
        _key("evt-dismiss"),
        target=EventStatus.DISMISSED,
        triage_target=None,
        reason="오탐 확인",
        assignee=None,
        actor=_actor(),
        now=datetime.now(UTC),
    )
    assert ok.verdict is EventVerdict.TRANSITIONED
    assert ok.record is not None
    assert ok.record.status is EventStatus.DISMISSED


# ── 확정 후 edge update 격리 ─────────────────────────────────────────────


def test_edge_update_after_confirmation_is_diverged(store: EventStore) -> None:
    _project_to_finding(store, "evt-post-confirm")
    confirm = store.triage_transition(
        _key("evt-post-confirm"),
        target=EventStatus.CONFIRMED_EVENT,
        triage_target=None,
        reason="확인",
        assignee=None,
        actor=_actor(),
        now=datetime.now(UTC),
    )
    assert confirm.verdict is EventVerdict.TRANSITIONED

    # 같은 eventId, 다른 내용(reasoning 변경) — 여전히 FINDING 상태를 보고해도
    # 서버가 이미 확정했으므로 무조건 diverged.
    payload = _bundle_payload("evt-post-confirm", status="FINDING")
    payload["reasoning"] = {"note": "edge 재전송(뒤늦은 갱신)"}
    verdict = _project(store, payload)
    assert verdict is EventVerdict.UPDATE_DIVERGED
    record = store.get(_key("evt-post-confirm"))
    assert record is not None
    assert record.status is EventStatus.CONFIRMED_EVENT, "확정이 edge update 로 뒤집혔다"


# ── 재기동 복구 ──────────────────────────────────────────────────────────


def test_restart_preserves_status_triage_assignee(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    first = EventStore(DurableJournal(path))
    _project_to_finding(first, "evt-restart")
    now = datetime.now(UTC)
    first.triage_transition(
        _key("evt-restart"),
        target=EventStatus.CONFIRMED_EVENT,
        triage_target=None,
        reason="확인",
        assignee=None,
        actor=_actor(),
        now=now,
    )
    first.triage_transition(
        _key("evt-restart"),
        target=None,
        triage_target=TriageStatus.ASSIGNED,
        reason=None,
        assignee="operator-7",
        actor=_actor(),
        now=now,
    )
    first._journal.close()  # noqa: SLF001 -- 프로세스 종료 재현(flock 해제)

    reborn = EventStore(DurableJournal(path))
    record = reborn.get(_key("evt-restart"))
    assert record is not None
    assert record.status is EventStatus.CONFIRMED_EVENT
    assert record.triage is TriageStatus.ASSIGNED
    assert record.assignee == "operator-7"
    assert len(record.transitions) == 5  # CANDIDATE + 2 updates + confirm + assign


# ── 필터·페이지네이션 결정성 ─────────────────────────────────────────────


def test_list_filters_and_sorts_deterministically(store: EventStore) -> None:
    _project(store, _bundle_payload("evt-a", site_id="site-1", occurred_at="2026-07-27T06:00:00Z"))
    _project(store, _bundle_payload("evt-b", site_id="site-1", occurred_at="2026-07-27T07:00:00Z"))
    _project(store, _bundle_payload("evt-c", site_id="site-2", occurred_at="2026-07-27T08:00:00Z"))
    # evt-d 는 evt-a 와 동시각 — event_id 오름차순 tie-break 확인용.
    _project(store, _bundle_payload("evt-d", site_id="site-1", occurred_at="2026-07-27T06:00:00Z"))

    site1 = store.list(site_id="site-1")
    assert [r.event_id for r in site1] == ["evt-b", "evt-a", "evt-d"]

    site2 = store.list(site_id="site-2")
    assert [r.event_id for r in site2] == ["evt-c"]

    page1 = store.list(limit=2, offset=0)
    page2 = store.list(limit=2, offset=2)
    assert [r.event_id for r in page1] == ["evt-c", "evt-b"]
    assert [r.event_id for r in page2] == ["evt-a", "evt-d"]

    with pytest.raises(ValueError, match="limit"):
        store.list(limit=0)
    with pytest.raises(ValueError, match="offset"):
        store.list(offset=-1)


def test_list_filters_by_status_severity_triage(store: EventStore) -> None:
    _project(store, _bundle_payload("evt-cand", status="CANDIDATE", severity="MEDIUM"))
    _project_to_finding(store, "evt-find", severity="HIGH", evidence={"clips": ["c1"]})

    only_finding = store.list(status=EventStatus.FINDING)
    assert [r.event_id for r in only_finding] == ["evt-find"]

    only_high = store.list(severity=None)  # severity 필터 미지정은 전체 반환
    assert {r.event_id for r in only_high} == {"evt-cand", "evt-find"}

    only_triage_none = store.list(triage=TriageStatus.NONE)
    assert {r.event_id for r in only_triage_none} == {"evt-cand", "evt-find"}


# ── HTTP 배선: 401/403 ───────────────────────────────────────────────────


def _registry() -> AuthRegistry:
    import hashlib

    def digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=digest(_FIELD_OPERATOR_TOKEN),
                principal=Principal(
                    principal_id="field-op-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=digest(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="viewer-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=digest(_OTHER_ORG_FIELD_OPERATOR_TOKEN),
                principal=Principal(
                    principal_id="other-org-field-op-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                    organization_id="org-2",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=digest(_OTHER_ORG_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="other-org-viewer-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                    organization_id="org-2",
                ),
            ),
        ]
    )


def _app(store: EventStore) -> FastAPI:
    app = FastAPI()
    mount_auth(app, _registry())
    mount_events(app, store)
    return app


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_unauthenticated_request_is_401(store: EventStore) -> None:
    client = TestClient(_app(store))
    response = client.get("/v1/events")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


def test_viewer_can_read_but_not_triage(store: EventStore) -> None:
    _project(store, _bundle_payload("evt-http-1"))
    client = TestClient(_app(store))

    read = client.get("/v1/events", headers=_auth(_VIEWER_TOKEN))
    assert read.status_code == 200

    forbidden = client.post(
        f"/v1/events/{_key('evt-http-1')}/transitions",
        json={"reason": "x", "targetStatus": "DISMISSED"},
        headers=_auth(_VIEWER_TOKEN),
    )
    assert forbidden.status_code == 403


def test_field_operator_can_triage(store: EventStore) -> None:
    _project(store, _bundle_payload("evt-http-2"))
    client = TestClient(_app(store))
    response = client.post(
        f"/v1/events/{_key('evt-http-2')}/transitions",
        json={"reason": "오탐", "targetStatus": "DISMISSED"},
        headers=_auth(_FIELD_OPERATOR_TOKEN),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "TRANSITIONED"
    assert body["event"]["status"] == "DISMISSED"


def test_http_other_organization_cannot_read_or_mutate_foreign_event(store: EventStore) -> None:
    """목록·상세·트리아지 모두 foreign event를 같은 404로 접는다(INV-060)."""
    event_key = _key("evt-org-isolated")
    assert (
        _project(store, _bundle_payload("evt-org-isolated"), organization_id="org-2")
        is EventVerdict.PROJECTED
    )
    client = TestClient(_app(store))

    foreign_list = client.get("/v1/events", headers=_auth(_VIEWER_TOKEN))
    assert foreign_list.status_code == 200
    assert foreign_list.json()["events"] == []

    foreign_detail = client.get(f"/v1/events/{event_key}", headers=_auth(_VIEWER_TOKEN))
    assert foreign_detail.status_code == 404
    assert foreign_detail.json()["detail"] == "이벤트를 찾을 수 없다"

    foreign_transition = client.post(
        f"/v1/events/{event_key}/transitions",
        json={"reason": "다른 조직이면 안 된다", "targetStatus": "DISMISSED"},
        headers=_auth(_FIELD_OPERATOR_TOKEN),
    )
    assert foreign_transition.status_code == 404
    assert foreign_transition.json()["verdict"] == "UNKNOWN_EVENT"

    owner_detail = client.get(f"/v1/events/{event_key}", headers=_auth(_OTHER_ORG_VIEWER_TOKEN))
    assert owner_detail.status_code == 200
    assert owner_detail.json()["eventKey"] == event_key


def test_list_can_apply_explicit_organization_scope_without_request_context(
    store: EventStore,
) -> None:
    _project(store, _bundle_payload("evt-org-1"), organization_id="org-1")
    _project(store, _bundle_payload("evt-org-2"), organization_id="org-2")

    assert [event.event_id for event in store.list(organization_id="org-1")] == ["evt-org-1"]
    assert [event.event_id for event in store.list(organization_id="org-2")] == ["evt-org-2"]


# ── HTTP 배선: 조회·검증 오류 ────────────────────────────────────────────


def test_get_unknown_event_is_404_generic(store: EventStore) -> None:
    client = TestClient(_app(store))
    response = client.get("/v1/events/does-not-exist", headers=_auth(_FIELD_OPERATOR_TOKEN))
    assert response.status_code == 404
    assert response.json()["detail"] == "이벤트를 찾을 수 없다"


def test_transition_unknown_event_is_404(store: EventStore) -> None:
    client = TestClient(_app(store))
    response = client.post(
        "/v1/events/does-not-exist/transitions",
        json={"reason": "x", "targetStatus": "DISMISSED"},
        headers=_auth(_FIELD_OPERATOR_TOKEN),
    )
    assert response.status_code == 404
    assert response.json()["verdict"] == "UNKNOWN_EVENT"


def test_transition_both_targets_is_422(store: EventStore) -> None:
    _project(store, _bundle_payload("evt-http-3"))
    client = TestClient(_app(store))
    response = client.post(
        f"/v1/events/{_key('evt-http-3')}/transitions",
        json={"targetStatus": "DISMISSED", "triageTarget": "ASSIGNED", "reason": "x"},
        headers=_auth(_FIELD_OPERATOR_TOKEN),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "INVALID_REQUEST"


def test_transition_neither_target_is_422(store: EventStore) -> None:
    _project(store, _bundle_payload("evt-http-4"))
    client = TestClient(_app(store))
    response = client.post(
        f"/v1/events/{_key('evt-http-4')}/transitions",
        json={"reason": "x"},
        headers=_auth(_FIELD_OPERATOR_TOKEN),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "INVALID_REQUEST"


def test_illegal_transition_over_http_is_409(store: EventStore) -> None:
    _project(store, _bundle_payload("evt-http-5", status="CANDIDATE"))
    client = TestClient(_app(store))
    response = client.post(
        f"/v1/events/{_key('evt-http-5')}/transitions",
        json={"targetStatus": "CONFIRMED_EVENT", "reason": "x"},
        headers=_auth(_FIELD_OPERATOR_TOKEN),
    )
    assert response.status_code == 409
    assert response.json()["verdict"] == "ILLEGAL_TRANSITION"


# ── journal 예외 주입 503 ────────────────────────────────────────────────


def test_project_bundle_seals_on_append_failure(
    store: EventStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_record: dict[str, Any]) -> None:
        raise OSError("disk full (주입 실패)")

    monkeypatch.setattr(store._journal, "_append_durable", broken)  # noqa: SLF001
    verdict = _project(store, _bundle_payload("evt-sealed"))
    assert verdict is EventVerdict.STORE_UNAVAILABLE
    assert store.get(_key("evt-sealed")) is None, "봉인 실패가 메모리에 반영되면 안 된다"

    monkeypatch.undo()
    retry = _project(store, _bundle_payload("evt-sealed"))
    assert retry is EventVerdict.STORE_UNAVAILABLE, "봉인 후에는 재시도도 거부돼야 한다"


def test_triage_transition_over_http_returns_503_when_sealed(
    store: EventStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project_to_finding(store, "evt-http-sealed")

    def broken(_record: dict[str, Any]) -> None:
        raise OSError("disk full (주입 실패)")

    monkeypatch.setattr(store._journal, "_append_durable", broken)  # noqa: SLF001
    client = TestClient(_app(store))
    response = client.post(
        f"/v1/events/{_key('evt-http-sealed')}/transitions",
        json={"targetStatus": "CONFIRMED_EVENT", "reason": "확인"},
        headers=_auth(_FIELD_OPERATOR_TOKEN),
    )
    assert response.status_code == 503
    assert response.json()["verdict"] == "STORE_UNAVAILABLE"
    assert response.headers.get("retry-after") == "30"


# ── 완전성(edge_sync.py:321 관습) ────────────────────────────────────────


def test_status_map_covers_every_verdict() -> None:
    from ksi_core.events import _STATUS  # noqa: PLC0415 -- 내부 상수 완전성 검사 전용

    for verdict in EventVerdict:
        assert verdict in _STATUS, f"{verdict} 의 HTTP 매핑 누락"


# ── 독립 재검토 P1 회귀 — Edge 는 확정/기각을 주장할 수 없다 ─────────────


def test_edge_cannot_project_confirmed_event_directly(store: EventStore) -> None:
    """[P1] 신규 projection 으로 CONFIRMED_EVENT 직접 주입 → 거부(INV-021 우회 차단).

    evidence 가 텅 빈 CRITICAL 이 서버 확정 게이트(clips·riskField 등)를 건너뛰고
    종단 상태로 박히던 경로다 — 종단은 outgoing 전이가 공집합이라 운영자가
    되돌릴 수도 없었다.
    """
    verdict = _project(
        store,
        _bundle_payload("evt-edge-confirm", status="CONFIRMED_EVENT", severity="CRITICAL"),
    )

    assert verdict is EventVerdict.STATUS_NOT_EDGE_ASSERTABLE
    assert store.get(_key("evt-edge-confirm")) is None


def test_edge_cannot_walk_up_to_confirmed_event(store: EventStore) -> None:
    """[P1] 적법 전이 사슬(CANDIDATE→…→FINDING) 끝에서도 CONFIRMED_EVENT 는 거부."""
    _project_to_finding(store, "evt-walk", severity="CRITICAL", evidence={})

    verdict = _project(
        store,
        _bundle_payload("evt-walk", status="CONFIRMED_EVENT", severity="CRITICAL", evidence={}),
    )

    assert verdict is EventVerdict.STATUS_NOT_EDGE_ASSERTABLE
    assert store.get(_key("evt-walk")).status is EventStatus.FINDING  # type: ignore[union-attr]


def test_edge_cannot_project_dismissed(store: EventStore) -> None:
    """[P1] 기각(DISMISSED)도 서버 트리아지 전용 — 안전 findings 영구 매장 차단."""
    _project_to_finding(store, "evt-edge-dismiss")

    verdict = _project(store, _bundle_payload("evt-edge-dismiss", status="DISMISSED"))

    assert verdict is EventVerdict.STATUS_NOT_EDGE_ASSERTABLE
    assert store.get(_key("evt-edge-dismiss")).status is EventStatus.FINDING  # type: ignore[union-attr]


def test_edge_assertable_set_excludes_exactly_the_terminal_states() -> None:
    """전이표 전수 대조 — 허용 집합이 종단 2종만 제외함을 못박는다(표 drift 방지)."""
    from ksi_core.events import _EDGE_ASSERTABLE_STATUSES  # noqa: PLC0415 -- 완전성 검사

    assert set(EventStatus) - _EDGE_ASSERTABLE_STATUSES == {
        EventStatus.CONFIRMED_EVENT,
        EventStatus.DISMISSED,
    }


# ── 독립 재검토 P1 회귀 — 사건 신원은 장비별로 스코프된다 ────────────────


def test_same_event_id_from_two_devices_are_separate_events(store: EventStore) -> None:
    """[P1] 장비 로컬 id 충돌(evt-ent-1 류)이 서로를 덮어쓰지 않는다.

    실제 생성 규칙이 장비 로컬 track 번호 기반이라 악의 없이도 충돌한다 —
    각 장비의 사건이 독립 레코드로 트리아지 표면에 나타나야 한다.
    """
    assert (
        _project(store, _bundle_payload("evt-ent-1", site_id="site-A"), edge_device_id="edge-001")
        is EventVerdict.PROJECTED
    )
    assert (
        _project(store, _bundle_payload("evt-ent-1", site_id="site-B"), edge_device_id="edge-002")
        is EventVerdict.PROJECTED
    )

    first = store.get(_key("evt-ent-1", edge_device_id="edge-001"))
    second = store.get(_key("evt-ent-1", edge_device_id="edge-002"))
    assert first is not None and second is not None
    assert (first.site_id, second.site_id) == ("site-A", "site-B")
    assert first.edge_device_id == "edge-001"
    assert second.edge_device_id == "edge-002"
    assert len(store.list()) == 2


def test_other_device_cannot_overwrite_or_bury_foreign_event(store: EventStore) -> None:
    """[P1] 타 장비가 남의 사건을 진행시키거나 기각으로 묻을 수 없다."""
    _project_to_finding(store, "evt-ent-9")  # edge-001 소유

    # edge-002 가 같은 id 로 EVIDENCE_COLLECTION 을 보내도 edge-001 사건은 불변이고,
    # edge-002 의 사건은 자기 키에 신규 생성된다(가려지지 않는다).
    verdict = _project(
        store,
        _bundle_payload("evt-ent-9", status="EVIDENCE_COLLECTION"),
        edge_device_id="edge-002",
    )

    assert verdict is EventVerdict.PROJECTED
    owner = store.get(_key("evt-ent-9"))
    intruder = store.get(_key("evt-ent-9", edge_device_id="edge-002"))
    assert owner is not None and owner.status is EventStatus.FINDING
    assert intruder is not None and intruder.status is EventStatus.EVIDENCE_COLLECTION


def test_reserved_separator_in_event_id_is_rejected(store: EventStore) -> None:
    """[P1] event_key 를 모호하게 만드는 식별자는 typed 거부(키 위조 차단)."""
    verdict = _project(store, _bundle_payload("evt::spoofed"))

    assert verdict is EventVerdict.INVALID_EVENT_IDENTITY
    assert store.list() == []


def test_event_list_and_detail_expose_scoped_key(store: EventStore) -> None:
    """조회 응답이 정본 신원(eventKey)과 장비 로컬 id 를 함께 노출한다."""
    _project(store, _bundle_payload("evt-keyed"))
    client = TestClient(_app(store))

    listing = client.get("/v1/events", headers=_auth(_VIEWER_TOKEN))
    assert listing.status_code == 200
    entry = listing.json()["events"][0]
    assert entry["eventKey"] == "edge-001::evt-keyed"
    assert entry["eventId"] == "evt-keyed"

    detail = client.get(f"/v1/events/{entry['eventKey']}", headers=_auth(_VIEWER_TOKEN))
    assert detail.status_code == 200
    assert detail.json()["eventKey"] == "edge-001::evt-keyed"


# ── 2차 독립 재검토 P1/P2 회귀 — event_key 경로-안전 + 시각 게이트 ────────


def test_slash_in_event_id_is_rejected_not_trapped(store: EventStore) -> None:
    """[P1] '/' 포함 eventId 는 durable 기록 자체를 거부한다(영구 404 트랩 차단).

    이전엔 PROJECTED 까지 성공해 목록에는 뜨지만 상세/전이 라우트(경로
    세그먼트에 '/' 를 실을 수 없다)에는 영구히 도달 못 하는 사건이 만들어졌다.
    """
    verdict = _project(store, _bundle_payload("evt/1"))

    assert verdict is EventVerdict.INVALID_EVENT_IDENTITY
    assert store.list() == []


def test_slash_in_edge_device_id_is_rejected(store: EventStore) -> None:
    """[P1 대칭] edgeDeviceId 쪽 '/' 도 동일하게 거부된다."""
    verdict = _project(store, _bundle_payload("evt-ok"), edge_device_id="edge/1")

    assert verdict is EventVerdict.INVALID_EVENT_IDENTITY


def test_naive_occurred_at_is_rejected(store: EventStore) -> None:
    """[P2] offset 없는 occurredAt 은 서버 로컬 tz 로 오염되지 않고 거부된다."""
    verdict = _project(store, _bundle_payload("evt-naive", occurred_at="2026-07-27T06:00:00"))

    assert verdict is EventVerdict.INVALID_EVENT_TIMESTAMP
    assert store.get(_key("evt-naive")) is None


def test_classify_edge_bundle_matches_project_bundle_gates() -> None:
    """사전 게이트(classify_edge_bundle)와 실제 projection 게이트가 정합한다."""
    from ksi_core.events import classify_edge_bundle  # noqa: PLC0415 -- 완전성 검사

    assert (
        classify_edge_bundle(_bundle_payload("evt/1"), edge_device_id="edge-001")
        is EventVerdict.INVALID_EVENT_IDENTITY
    )
    assert (
        classify_edge_bundle(
            _bundle_payload("evt-x", occurred_at="2026-07-27T06:00:00"), edge_device_id="edge-001"
        )
        is EventVerdict.INVALID_EVENT_TIMESTAMP
    )
    assert (
        classify_edge_bundle(_bundle_payload("evt-x"), edge_device_id="edge-001") is None
    )


# ── 2차 독립 재검토 P2 회귀 — 재생 실패 시 flock 해제 ─────────────────────


def test_replay_failure_releases_journal_lock(tmp_path: Path) -> None:
    """[P2] EventStore 기동이 재생 오염으로 실패하면 journal flock 이 해제된다.

    해제하지 않으면 재시도 재조립조차 "다른 프로세스가 소유 중" 으로
    오도한다(프로세스 수명 내내 잔존).
    """
    path = tmp_path / "events" / "journal.jsonl"
    seed = DurableJournal(path)
    seed.append({"kind": "not-a-real-kind", "eventKey": "x"})
    seed.close()

    with pytest.raises(EventStoreRecoveryError):
        EventStore(DurableJournal(path))

    # 잠금이 해제됐다면 재조립이 flock 경합 없이 다시 같은 예외로 실패한다
    # (JournalRecoveryError/flock 거부가 아니라 재생 실패여야 해제 증명).
    with pytest.raises(EventStoreRecoveryError):
        EventStore(DurableJournal(path))


def test_trailing_newline_in_event_id_is_rejected(store: EventStore) -> None:
    """[3차 최종검토 P3] 끝 개행 1개도 거부한다(re.match+`$` 관용 vs fullmatch).

    Python 정규식의 `$` 는 문자열 끝 개행 직전에도 매치해, match() 기반
    검증은 "site-1\\n" 을 통과시켰다 — fullmatch 로 강화해 닫는다.
    """
    verdict = _project(store, _bundle_payload("evt-trap\n"))

    assert verdict is EventVerdict.INVALID_EVENT_IDENTITY
    assert store.list() == []


def test_event_type_is_exposed_in_list_and_detail(store: EventStore) -> None:
    """목록 응답이 ``eventType`` 을 싣는다 — 대기열에서 '무슨 일인지'를 읽는 근거.

    이게 없으면 운영자는 목록에서 사건 종류를 알 수 없어 매 건마다 상세를 열어야 한다.
    필드를 추가만 해두고 직렬화에서 빠뜨리면 조용히 ``null`` 이 나가므로(추가형 변경의
    전형적 사각지대) 값이 bundle 원문과 같은지까지 대조한다.
    """
    _project(store, _bundle_payload("evt-fall", event_type="FALL_RISK"))
    client = TestClient(_app(store))

    listed = client.get("/v1/events", headers=_auth(_VIEWER_TOKEN)).json()["events"]
    assert [e["eventType"] for e in listed] == ["FALL_RISK"]
    assert [e["evidenceCount"] for e in listed] == [0]

    key = make_event_key("edge-001", "evt-fall")
    detail = client.get(f"/v1/events/{key}", headers=_auth(_VIEWER_TOKEN)).json()
    assert detail["eventType"] == "FALL_RISK"
    # 상세는 bundle 도 통째로 주므로 두 자리의 값이 갈리지 않아야 한다.
    assert detail["bundle"]["eventType"] == "FALL_RISK"


def test_event_type_missing_from_bundle_degrades_to_null(store: EventStore) -> None:
    """bundle 이 ``eventType`` 을 잃어도 목록 **전체**가 죽지 않는다.

    트리아지 대기열은 안전 경로다 — 레코드 한 건의 결손이 목록 조회를 500 으로 만들면
    나머지 미조치 사건까지 함께 보이지 않게 된다. 결손 건만 ``null`` 로 떨어뜨린다.
    """
    _project(store, _bundle_payload("evt-ok"))
    record = store.get(make_event_key("edge-001", "evt-ok"))
    assert record is not None
    assert record.event_type == "PERSON_PRESENT"

    stripped = replace(record, bundle={k: v for k, v in record.bundle.items() if k != "eventType"})
    assert stripped.event_type is None

    # 빈 문자열도 '분류 없음'으로 본다(표시 계층이 빈 라벨을 그리지 않게).
    blanked = replace(record, bundle={**record.bundle, "eventType": ""})
    assert blanked.event_type is None


# ── 낙관적 동시성 토큰 (s2-residual-hardening #7) ──────────────────────────


def _principal() -> Principal:
    return Principal(
        principal_id="op-1", kind=PrincipalKind.OPERATOR, role=Role.FIELD_OPERATOR, device_id=None
    )


def test_transition_without_token_is_unaffected(store: EventStore) -> None:
    """[비회귀] 토큰을 안 보내면 예전과 똑같이 동작한다."""
    _project_to_finding(store, "evt-tok-0")
    result = store.triage_transition(
        _key("evt-tok-0"),
        target=EventStatus.DISMISSED,
        triage_target=None,
        reason="오탐",
        assignee=None,
        actor=_principal(),
        now=datetime.now(UTC),
    )
    assert result.verdict is EventVerdict.TRANSITIONED


def test_matching_token_allows_transition(store: EventStore) -> None:
    _project_to_finding(store, "evt-tok-1")
    record = store.get(_key("evt-tok-1"))
    assert record is not None

    result = store.triage_transition(
        _key("evt-tok-1"),
        target=EventStatus.DISMISSED,
        triage_target=None,
        reason="오탐",
        assignee=None,
        actor=_principal(),
        now=datetime.now(UTC),
        expected_bundle_digest=payload_digest(record.bundle),
    )
    assert result.verdict is EventVerdict.TRANSITIONED


def test_stale_token_blocks_transition_and_leaves_state_untouched(store: EventStore) -> None:
    """[핵심] 운영자가 본 이후 bundle 이 바뀌었으면 전이하지 않는다.

    확정 전이는 **그 시점의 bundle** 로 INV-021 게이트를 통과시키고
    evidenceSnapshot 을 굳힌다 — 운영자가 본 증거와 실제로 굳는 증거가 다르면
    감사 기록이 사람이 내린 판단을 대표하지 않는다.
    """
    # EVIDENCE_COLLECTION 시점의 bundle 을 운영자가 봤다고 하자.
    assert _project(store, _bundle_payload("evt-tok-2")) is EventVerdict.PROJECTED
    assert (
        _project(store, _bundle_payload("evt-tok-2", status="EVIDENCE_COLLECTION"))
        is EventVerdict.EVENT_UPDATED
    )
    before = store.get(_key("evt-tok-2"))
    assert before is not None
    stale_digest = payload_digest(before.bundle)

    # 그 사이 Edge 의 후행 update 가 도착해 bundle 이 바뀐다(적법 전이).
    assert (
        _project(store, _bundle_payload("evt-tok-2", status="FINDING"))
        is EventVerdict.EVENT_UPDATED
    )

    result = store.triage_transition(
        _key("evt-tok-2"),
        target=EventStatus.DISMISSED,
        triage_target=None,
        reason="오탐",
        assignee=None,
        actor=_principal(),
        now=datetime.now(UTC),
        expected_bundle_digest=stale_digest,
    )
    assert result.verdict is EventVerdict.STALE_EVENT_VIEW
    after = store.get(_key("evt-tok-2"))
    assert after is not None
    assert after.status is EventStatus.FINDING, "거부됐는데 상태가 바뀌었다"


def test_stale_token_maps_to_409(store: EventStore) -> None:
    client = TestClient(_app(store))
    assert _project(store, _bundle_payload("evt-tok-3")) is EventVerdict.PROJECTED
    assert (
        _project(store, _bundle_payload("evt-tok-3", status="EVIDENCE_COLLECTION"))
        is EventVerdict.EVENT_UPDATED
    )
    before = store.get(_key("evt-tok-3"))
    assert before is not None
    stale_digest = payload_digest(before.bundle)
    assert (
        _project(store, _bundle_payload("evt-tok-3", status="FINDING"))
        is EventVerdict.EVENT_UPDATED
    )

    response = client.post(
        f"/v1/events/{_key('evt-tok-3')}/transitions",
        json={
            "targetStatus": "DISMISSED",
            "reason": "오탐",
            "expectedBundleDigest": stale_digest,
        },
        headers={"Authorization": f"Bearer {_FIELD_OPERATOR_TOKEN}"},
    )
    assert response.status_code == 409
    assert response.json()["verdict"] == "STALE_EVENT_VIEW"


# ── 재생 게이트 (독립 재검토 P1-1·P2-5 — transitioned 외 kind 가 무검사였다) ──


def _seed(path: Path, records: list[dict[str, Any]]) -> None:
    journal = DurableJournal(path)
    for record in records:
        journal.append(record)
    journal.close()


def _projected_record(*, status: str = "CANDIDATE", event_id: str = "evt-r") -> dict[str, Any]:
    payload = _bundle_payload(event_id, status=status)
    return {
        "kind": "event-projected",
        "ts": "2026-07-27T06:00:00+00:00",
        "actor": "edge-001",
        "eventKey": _key(event_id),
        "eventId": event_id,
        "siteId": "site-1",
        "missionId": "mission-1",
        "edgeDeviceId": "edge-001",
        "occurredAt": "2026-07-27T06:00:00+00:00",
        "receivedAt": "2026-07-27T06:00:01+00:00",
        "before": None,
        "after": {
            "status": status,
            "triage": "NONE",
            "assignee": None,
            "bundle": payload,
        },
        "reason": None,
        "evidenceSnapshot": None,
    }


def _updated_record(*, status: str, event_id: str = "evt-r") -> dict[str, Any]:
    payload = _bundle_payload(event_id, status="CANDIDATE")
    return {
        "kind": "event-updated",
        "ts": "2026-07-27T06:00:02+00:00",
        "actor": "edge-001",
        "eventKey": _key(event_id),
        "eventId": event_id,
        "siteId": "site-1",
        "missionId": "mission-1",
        "before": {"status": "CANDIDATE", "bundleDigest": "sha256:" + "0" * 64},
        "after": {"status": status, "bundle": payload, "bundleDigest": "sha256:" + "1" * 64},
        "reason": "edge bundle update",
        "evidenceSnapshot": None,
    }


def test_replay_rejects_edge_asserted_finalized_projection(tmp_path: Path) -> None:
    """[핵심] projection 레코드 한 줄로 확정 사건을 만들 수 없다.

    live 는 STATUS_NOT_EDGE_ASSERTABLE 로 막는데 재생만 무검사면, evidence 없는
    CONFIRMED_EVENT 가 journal 한 줄로 되살아나 INV-021 을 우회한다.
    """
    path = tmp_path / "events" / "journal.jsonl"
    _seed(path, [_projected_record(status="CONFIRMED_EVENT")])

    with pytest.raises(EventStoreRecoveryError, match="주장할 수 없는 상태"):
        EventStore(DurableJournal(path))


def test_replay_rejects_illegal_update_transition(tmp_path: Path) -> None:
    """전이표에 없는 update 는 거부한다 — CANDIDATE→FINDING 직행(둘 다 Edge 주장 가능).

    종단 상태 케이스는 그보다 앞선 게이트가 잡으므로
    (:func:`test_replay_rejects_edge_asserted_finalized_update`), 여기서는 전이표
    검사 자체가 살아 있는지를 본다.
    """
    path = tmp_path / "events" / "journal.jsonl"
    _seed(path, [_projected_record(), _updated_record(status="FINDING")])

    with pytest.raises(EventStoreRecoveryError, match="불법 update 전이"):
        EventStore(DurableJournal(path))


def test_replay_rejects_update_after_finalized(tmp_path: Path) -> None:
    """확정된 사건에 update 레코드가 적용되는 원장은 기동 거부다."""
    path = tmp_path / "events" / "journal.jsonl"
    records = [_projected_record()]
    transitioned = {
        "kind": "event-transitioned",
        "ts": "2026-07-27T06:00:03+00:00",
        "actor": "op-1",
        "eventKey": _key("evt-r"),
        "eventId": "evt-r",
        "before": {"status": "CANDIDATE", "triage": "NONE", "assignee": None},
        "after": {"status": "DISMISSED", "triage": "NONE", "assignee": None},
        "reason": "오탐",
        "evidenceSnapshot": None,
    }
    records.extend([transitioned, _updated_record(status="EVIDENCE_COLLECTION")])
    _seed(path, records)

    with pytest.raises(EventStoreRecoveryError, match="확정/기각된 사건"):
        EventStore(DurableJournal(path))


def test_replay_rejects_naive_occurred_at(tmp_path: Path) -> None:
    """naive 시각 하나가 재생되면 이후 목록 조회가 통째로 500 이 된다 — 기동에서 막는다."""
    path = tmp_path / "events" / "journal.jsonl"
    record = _projected_record()
    record["occurredAt"] = "2026-07-27T06:00:00"
    _seed(path, [record])

    with pytest.raises(EventStoreRecoveryError, match="naive"):
        EventStore(DurableJournal(path))


def test_replay_accepts_intact_projection_and_update(tmp_path: Path) -> None:
    """[비공허 대조] 정상 원장은 그대로 재생된다 — 위 게이트들이 과잉이 아니다."""
    path = tmp_path / "events" / "journal.jsonl"
    _seed(path, [_projected_record(), _updated_record(status="EVIDENCE_COLLECTION")])

    journal = DurableJournal(path)
    store = EventStore(journal)
    try:
        record = store.get(_key("evt-r"))
        assert record is not None
        assert record.status is EventStatus.EVIDENCE_COLLECTION
    finally:
        journal.close()


def test_update_does_not_move_occurred_at(store: EventStore) -> None:
    """[핵심] Edge 의 후행 update 가 보관 정책 시계를 옮기지 못한다.

    occurredAt 은 retention 만료 기준이라(plan_expiry), Edge 입력으로 움직이면
    후행 update 한 번으로 증거가 즉시 삭제되거나 보관이 무한 연장된다.
    """
    assert _project(store, _bundle_payload("evt-clock")) is EventVerdict.PROJECTED
    first = store.get(_key("evt-clock"))
    assert first is not None

    moved = _bundle_payload(
        "evt-clock", status="EVIDENCE_COLLECTION", occurred_at="2020-01-01T00:00:00Z"
    )
    assert _project(store, moved) is EventVerdict.EVENT_UPDATED

    after = store.get(_key("evt-clock"))
    assert after is not None
    assert after.occurred_at == first.occurred_at, "Edge update 가 보관 시계를 옮겼다"


def test_update_syncs_site_and_mission_meta(store: EventStore) -> None:
    """목록(레코드 메타)과 상세(bundle)가 다른 현장을 가리키지 않는다."""
    assert _project(store, _bundle_payload("evt-meta")) is EventVerdict.PROJECTED
    moved = _bundle_payload("evt-meta", status="EVIDENCE_COLLECTION", site_id="site-2")
    assert _project(store, moved) is EventVerdict.EVENT_UPDATED

    record = store.get(_key("evt-meta"))
    assert record is not None
    assert record.site_id == "site-2"
    assert record.bundle["siteId"] == "site-2"


def test_replay_rejects_edge_asserted_finalized_update(tmp_path: Path) -> None:
    """[핵심] FINDING projection + CONFIRMED_EVENT update 두 줄로 확정할 수 없다.

    전이표상 FINDING→CONFIRMED_EVENT 는 적법하므로 전이 검사만으로는 통과한다 —
    live 가 가장 먼저 거는 "Edge 가 주장할 수 있는 상태인가" 게이트가 재생의
    update 분기에만 빠져 있어, evidence 게이트도 reason 요구도 없이 확정 사건이
    만들어졌다(2차 독립 재검토 P1-4, 실측 재현).
    """
    path = tmp_path / "events" / "journal.jsonl"
    projected = _projected_record(status="FINDING")
    projected["after"]["bundle"] = _bundle_payload("evt-r", status="FINDING", severity="CRITICAL")
    _seed(path, [projected, _updated_record(status="CONFIRMED_EVENT")])

    with pytest.raises(EventStoreRecoveryError, match="주장할 수 없는 상태로 update"):
        EventStore(DurableJournal(path))


def test_replay_rejects_projection_claiming_triage(tmp_path: Path) -> None:
    """projection 한 줄로 트리아지 상태를 주장할 수 없다(전이는 확정 사건 전용)."""
    path = tmp_path / "events" / "journal.jsonl"
    record = _projected_record()
    record["after"]["triage"] = "ASSIGNED"
    record["after"]["assignee"] = "op-1"
    _seed(path, [record])

    with pytest.raises(EventStoreRecoveryError, match="트리아지 상태를 주장"):
        EventStore(DurableJournal(path))


def _transitioned_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "kind": "event-transitioned",
        "ts": "2026-07-27T06:00:05+00:00",
        "actor": "op-1",
        "eventKey": _key("evt-r"),
        "eventId": "evt-r",
        "before": {"status": "FINDING", "triage": "NONE", "assignee": None},
        "after": {"status": "CONFIRMED_EVENT", "triage": "NONE", "assignee": None},
        "reason": "현장 확인",
        "evidenceSnapshot": None,
    }
    record.update(overrides)
    return record


def _finding_journal() -> list[dict[str, Any]]:
    """FINDING 까지 적법하게 올라간 원장(증거 포함) — 확정 직전 상태."""
    evidence = {"clips": ["clip-1"]}
    projected = _projected_record()
    projected["after"]["bundle"] = _bundle_payload("evt-r", severity="HIGH", evidence=evidence)
    updates = []
    for status in ("EVIDENCE_COLLECTION", "FINDING"):
        record = _updated_record(status=status)
        record["after"]["bundle"] = _bundle_payload(
            "evt-r", status=status, severity="HIGH", evidence=evidence
        )
        updates.append(record)
    return [projected, *updates]


def test_replay_rejects_confirmation_without_reason(tmp_path: Path) -> None:
    """[핵심] 사유 없는 확정은 재생에서도 거부된다.

    live 는 전이표·비공백 reason·evidence 셋을 요구하는데 재생이 둘만 태우면,
    사유 없는 확정 사건이 원장 한 줄로 되살아난다(3차 독립 재검토).
    """
    path = tmp_path / "events" / "journal.jsonl"
    _seed(path, [*_finding_journal(), _transitioned_record(reason=None)])

    with pytest.raises(EventStoreRecoveryError, match="비공백 reason"):
        EventStore(DurableJournal(path))


def test_replay_accepts_confirmation_with_reason(tmp_path: Path) -> None:
    """[비공허 대조] 사유가 있으면 그대로 재생된다 — 과잉 거부가 아니다."""
    path = tmp_path / "events" / "journal.jsonl"
    _seed(path, [*_finding_journal(), _transitioned_record()])

    journal = DurableJournal(path)
    store = EventStore(journal)
    try:
        record = store.get(_key("evt-r"))
        assert record is not None
        assert record.status is EventStatus.CONFIRMED_EVENT
    finally:
        journal.close()


def test_replay_rejects_assignment_without_assignee(tmp_path: Path) -> None:
    """ASSIGNED 인데 담당자가 없는 레코드는 live 가 만들 수 없는 형상이다."""
    path = tmp_path / "events" / "journal.jsonl"
    assigned = _transitioned_record(
        before={"status": "CONFIRMED_EVENT", "triage": "NONE", "assignee": None},
        after={"status": "CONFIRMED_EVENT", "triage": "ASSIGNED", "assignee": None},
        reason=None,
    )
    _seed(path, [*_finding_journal(), _transitioned_record(), assigned])

    with pytest.raises(EventStoreRecoveryError, match="assignee 가 없다"):
        EventStore(DurableJournal(path))


def test_replay_rejects_assignee_rewrite_without_transition(tmp_path: Path) -> None:
    """트리아지 전이 없이 담당자만 갈아끼우는 레코드도 거부한다."""
    path = tmp_path / "events" / "journal.jsonl"
    rewrite = _transitioned_record(
        before={"status": "CONFIRMED_EVENT", "triage": "NONE", "assignee": None},
        after={"status": "CONFIRMED_EVENT", "triage": "NONE", "assignee": "op-9"},
        reason=None,
    )
    _seed(path, [*_finding_journal(), _transitioned_record(), rewrite])

    with pytest.raises(EventStoreRecoveryError, match="assignee 가 바뀐다"):
        EventStore(DurableJournal(path))
