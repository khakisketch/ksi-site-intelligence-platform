"""보관 정책 집행 계약 (ADR-KSI-010 §3).

데이터를 지우는 코드다 — 여기서 반증할 것은 세 가지다:

1. **판정은 아무것도 바꾸지 않는다.** dry-run 이 "실행하고 롤백"이면 dry-run 이 아니다.
2. **원장이 먼저다.** 객체 삭제가 실패해도 "폐기하기로 했다"는 사실은 남아야 한다.
3. **정책은 조용히 기본값으로 채워지지 않는다.** 보관 기간은 법적 의무와 얽힌
   값이라 "파일에 없어서 30일로 봤다"가 설명 가능한 사유가 되지 않는다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ksi_core.auth import Principal, PrincipalKind, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.events import EventStore, EventVerdict
from ksi_core.evidence import EvidenceStorageError
from ksi_core.retention import (
    RetentionPolicy,
    execute_expiry,
    load_policy,
    plan_expiry,
)
from ksi_domain.enums import EventStatus

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_DEFAULTS = _REPO_ROOT / "contracts" / "schemas" / "retention-policy.v1.json"


class FakeStorage:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.fail_with: Exception | None = None

    def presigned_put(self, object_key: str, *, content_type: str, ttl: timedelta) -> str:
        return f"put://{object_key}"

    def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
        return f"get://{object_key}"

    def delete(self, object_key: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.deleted.append(object_key)


def _bundle(event_id: str, *, occurred_at: str, status: str = "CANDIDATE") -> dict[str, Any]:
    return {
        "schemaVersion": "1.2",
        "eventId": event_id,
        "siteId": "site-1",
        "missionId": "mission-1",
        "eventType": "PERSON_PRESENT",
        "status": status,
        "occurredAt": occurred_at,
        "entities": ["ent-trk-001"],
        "spatialContext": {"zone": "A"},
        "reasoning": {},
        "evidence": {},
        "lineage": {
            "edgeVersion": "retention-test-edge-1.0",
            "modelVersions": {"detector": "stub"},
            "policyVersion": "retention-test-policy-1",
            "calibrationProfileId": "retention-test-cal-1",
            "classification": {
                "ent-trk-001": {
                    "entityClass": "Person",
                    "ontologyVersion": "ksi-ontology-v1",
                    "source": {
                        "taxonomy": "COCO-2017",
                        "sourceClassIds": [0],
                        "sourceClassNames": ["person"],
                    },
                    "entityFingerprint": "a" * 64,
                }
            },
        },
    }


_POLICY = RetentionPolicy(
    candidate_days=30,
    patrol_raw_days=90,
    confirmed_event_days=1095,
    telemetry_mission_days=365,
    audit_action_days=1095,
    spatial_artifact_after_contract_days=90,
)

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    return EventStore(DurableJournal(tmp_path / "events.jsonl"))


_TRIAGE_ACTOR = Principal(
    principal_id="op-admin",
    kind=PrincipalKind.OPERATOR,
    role=Role.ADMIN,
    device_id=None,
)


def _seed(store: EventStore, *, event_id: str, days_ago: int, confirmed: bool = False) -> str:
    """이벤트 1건 + 증거 1건.

    ``confirmed`` 는 **전이로** 만든다 — Edge 는 CONFIRMED_EVENT 를 직접 주장할
    수 없다(INV-021 확정 게이트). 처음엔 bundle 의 status 를 그냥 바꿔 픽스처를
    만들었는데, projection 이 그 번들을 통째로 거부해 확정 이벤트가 **하나도
    없는 상태**에서 테스트가 통과하고 있었다(변이 테스트로 적발 — 확정/후보
    구분 로직을 죽여도 초록불이었다).
    """
    occurred = (_NOW - timedelta(days=days_ago)).isoformat()
    store.project_bundle(
        _bundle(event_id, occurred_at=occurred),
        edge_device_id="dev-1",
        received_at=_NOW,
    )
    event_key = f"dev-1::{event_id}"
    if confirmed:
        # CANDIDATE → CONFIRMED_EVENT 직행은 없다(enums.py 전이표, INV-031) —
        # 단일 프레임으로 사건을 확정하지 않겠다는 규칙이라 증거수집·판정을 거친다.
        for target in (
            EventStatus.EVIDENCE_COLLECTION,
            EventStatus.FINDING,
            EventStatus.CONFIRMED_EVENT,
        ):
            result = store.triage_transition(
                event_key,
                target=target,
                triage_target=None,
                reason="테스트 픽스처 — 운영자 확정 경로",
                assignee=None,
                actor=_TRIAGE_ACTOR,
                now=_NOW,
            )
            assert result.verdict is EventVerdict.TRANSITIONED, (target, result.verdict)
        confirmed_record = store.get(event_key)
        assert confirmed_record is not None
        assert confirmed_record.status is EventStatus.CONFIRMED_EVENT
    store.register_evidence(
        event_key=event_key,
        artifact_id="clip-01",
        content_type="video/mp4",
        registered_by="op-admin",
        now=_NOW,
    )
    return event_key


# ── 정책 로드 ───────────────────────────────────────────────────────────────


def test_schema_defaults_load(tmp_path: Path) -> None:
    """스키마의 default 값들이 그대로 유효한 정책이어야 한다."""
    schema = json.loads(_SCHEMA_DEFAULTS.read_text(encoding="utf-8"))
    payload = {
        key: spec["default"]
        for key, spec in schema["properties"].items()
        if "default" in spec
    }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    policy = load_policy(path)
    assert policy.candidate_days == 30
    assert policy.confirmed_event_days == 1095


def test_missing_field_refuses_load(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"candidateDays": 30}), encoding="utf-8")
    with pytest.raises(ValueError, match="필수 보관 기간 누락"):
        load_policy(path)


@pytest.mark.parametrize("bad", [-1, "30", 3.5, True, None])
def test_non_integer_or_negative_days_refused(tmp_path: Path, bad: object) -> None:
    """bool 도 거부한다 — int 서브클래스라 True 가 1일로 통과하는 경로가 있다."""
    payload = {
        "candidateDays": 30,
        "patrolRawDays": 90,
        "confirmedEventDays": 1095,
        "telemetryMissionDays": 365,
        "auditActionDays": 1095,
        "spatialArtifactAfterContractDays": 90,
    }
    payload["candidateDays"] = bad  # type: ignore[assignment]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="0 이상의 정수"):
        load_policy(path)


def test_enforced_fields_are_declared() -> None:
    """집행하지 않는 정책 필드를 '집행 중'으로 오해하지 않게 한다."""
    assert _POLICY.enforced_fields == ("candidateDays", "confirmedEventDays")


# ── 판정(순수) ─────────────────────────────────────────────────────────────


def test_plan_does_not_mutate_anything(store: EventStore) -> None:
    event_key = _seed(store, event_id="evt-old", days_ago=100)
    actions = plan_expiry(store, _POLICY, now=_NOW)
    assert len(actions) == 1
    # 판정만 했을 뿐 폐기되지 않았다.
    artifact = store.get_evidence(event_key, "clip-01")
    assert artifact is not None and not artifact.is_tombstoned


def test_fresh_evidence_is_not_expired(store: EventStore) -> None:
    _seed(store, event_id="evt-new", days_ago=1)
    assert plan_expiry(store, _POLICY, now=_NOW) == []


def test_confirmed_events_use_longer_retention(store: EventStore) -> None:
    """확정 이벤트는 사고와 직결돼 후행 조사 기간이 훨씬 길다."""
    _seed(store, event_id="evt-confirmed", days_ago=100, confirmed=True)
    _seed(store, event_id="evt-candidate", days_ago=100)
    actions = plan_expiry(store, _POLICY, now=_NOW)
    assert [a.event_key for a in actions] == ["dev-1::evt-candidate"]


def test_expiry_is_measured_from_occurrence_not_upload(store: EventStore) -> None:
    """보관 의무는 '언제 일어난 일인가'에 걸린다 — 업로드 시각이 아니다.

    등록 시각을 기준으로 삼으면 뒤늦게 올라온 증거가 같은 사건의 다른 증거보다
    오래 남아, 한 사건의 증거가 서로 다른 시점에 사라진다.
    """
    _seed(store, event_id="evt-old", days_ago=100)  # 등록은 _NOW(방금)
    assert len(plan_expiry(store, _POLICY, now=_NOW)) == 1


def test_already_tombstoned_is_not_replanned(store: EventStore) -> None:
    event_key = _seed(store, event_id="evt-old", days_ago=100)
    store.tombstone_evidence(
        event_key=event_key, artifact_id="clip-01", reason="수동 폐기", now=_NOW
    )
    assert plan_expiry(store, _POLICY, now=_NOW) == []


def test_naive_now_is_refused(store: EventStore) -> None:
    with pytest.raises(ValueError, match="tz-aware"):
        plan_expiry(store, _POLICY, now=datetime(2026, 8, 4))  # noqa: DTZ001 -- 의도적


def test_reason_records_which_policy_field_and_how_long(store: EventStore) -> None:
    """'이건 왜 지워졌나'에 답할 수 있어야 tombstone 이 기록으로서 값어치를 갖는다."""
    _seed(store, event_id="evt-old", days_ago=100)
    action = plan_expiry(store, _POLICY, now=_NOW)[0]
    assert "candidateDays" in action.reason
    assert "30일 경과" in action.reason
    assert "occurredAt" in action.reason


# ── 집행(부수효과) ──────────────────────────────────────────────────────────


def test_execute_tombstones_and_deletes(store: EventStore) -> None:
    event_key = _seed(store, event_id="evt-old", days_ago=100)
    storage = FakeStorage()
    report = execute_expiry(store, storage, plan_expiry(store, _POLICY, now=_NOW), now=_NOW)

    assert len(report.tombstoned) == 1
    assert storage.deleted == ["sites/site-1/events/dev-1/evt-old/clip-01"]
    artifact = store.get_evidence(event_key, "clip-01")
    assert artifact is not None
    assert artifact.is_tombstoned
    assert "candidateDays" in (artifact.tombstone_reason or "")


def test_storage_failure_keeps_tombstone(store: EventStore) -> None:
    """원장이 먼저다 — 삭제가 실패해도 '폐기하기로 했다'는 사실은 남는다."""
    event_key = _seed(store, event_id="evt-old", days_ago=100)
    storage = FakeStorage()
    storage.fail_with = EvidenceStorageError("연결 실패")
    report = execute_expiry(store, storage, plan_expiry(store, _POLICY, now=_NOW), now=_NOW)

    assert len(report.storage_failures) == 1
    artifact = store.get_evidence(event_key, "clip-01")
    assert artifact is not None and artifact.is_tombstoned


def test_second_run_is_a_noop(store: EventStore) -> None:
    """재실행이 같은 대상을 다시 지우려 들지 않는다(집행은 수동 반복될 수 있다)."""
    _seed(store, event_id="evt-old", days_ago=100)
    storage = FakeStorage()
    execute_expiry(store, storage, plan_expiry(store, _POLICY, now=_NOW), now=_NOW)
    second = plan_expiry(store, _POLICY, now=_NOW)
    assert second == []
    assert len(storage.deleted) == 1


def test_record_tombstoned_between_plan_and_execute_is_skipped(store: EventStore) -> None:
    """판정과 집행 사이에 상태가 바뀌면 조용히 성공으로 치지 않는다."""
    event_key = _seed(store, event_id="evt-old", days_ago=100)
    actions = plan_expiry(store, _POLICY, now=_NOW)
    store.tombstone_evidence(
        event_key=event_key, artifact_id="clip-01", reason="경합 폐기", now=_NOW
    )
    storage = FakeStorage()
    report = execute_expiry(store, storage, actions, now=_NOW)

    assert report.tombstoned == ()
    assert len(report.skipped) == 1
    assert storage.deleted == [], "이미 폐기된 대상의 객체를 다시 지우려 했다"


# ── 규모 회귀 (독립 재검토 2026-08-04 F1) ──────────────────────────────────


def test_expiry_survives_beyond_one_page(store: EventStore) -> None:
    """이벤트가 목록 한 페이지(500건)를 넘어도 만료 대상을 찾는다.

    `store.list(limit=500)` 한 번으로 끝내면 그 창은 occurred_at **내림차순**의
    최신 500건이고, 만료 대상은 정의상 **가장 오래된** 것들이다 — 500건을 넘는
    순간 후보가 구조적으로 창 밖으로 밀려나 **영영 돌아오지 않고**, 도구는
    "만료된 증거 없음"이라는 거짓 clean 리포트를 낸다. 실제로 그 상태였다
    (501건 시드로 재현: 만료 판정 0건).
    """
    event_key = _seed(store, event_id="evt-ancient", days_ago=100)
    for i in range(500):
        occurred = (_NOW - timedelta(minutes=i)).isoformat()
        store.project_bundle(
            _bundle(f"evt-new-{i:04d}", occurred_at=occurred),
            edge_device_id="dev-1",
            received_at=_NOW,
        )

    actions = plan_expiry(store, _POLICY, now=_NOW)
    assert [a.event_key for a in actions] == [event_key], (
        "한 페이지를 넘어가면 오래된 증거가 만료 판정에서 사라진다"
    )
