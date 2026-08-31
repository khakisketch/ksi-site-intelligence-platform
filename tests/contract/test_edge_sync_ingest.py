"""Edge→Core EventBundle 멱등 수신·영속 계약 (core-ingest).

offline_sync 의 SyncLedger 규칙이 서버 배선(EdgeSyncStore + FastAPI 라우터)을
통과해도 그대로 성립하는지, 그리고 서버가 더한 두 경계 — **durable 후 ACK**
(PRD §19.3)와 **EventBundle v1.2 사전 검증**(INV-031) — 를 반증한다.

멱등 규칙 자체의 단위 반증(4중 신원·순번·digest)은 offline_sync 계약 테스트
소유이고, 여기서는 배선이 그 규칙을 우회·약화하지 않는지가 초점이다.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.edge_sync import EdgeSyncStore, ServerVerdict, StoreRecoveryError
from ksi_core.events import EventStore, EventVerdict, make_event_key
from ksi_event_contracts.offline_sync import (
    IngestVerdict,
    JournalEntry,
    payload_digest,
)

_FPR = "a" * 64


def _bundle_payload(event_id: str = "evt-ent-trk-001") -> dict[str, Any]:
    """유효한 EventBundle v1.2 payload — lineage.classification 포함."""
    return {
        "schemaVersion": "1.2",
        "eventId": event_id,
        "missionId": "mission-1",
        "siteId": "site-1",
        "eventType": "PERSON_PRESENT",
        "occurredAt": "2026-07-27T06:00:00Z",
        "status": "CANDIDATE",
        "entities": ["ent-trk-001"],
        "spatialContext": {},
        "reasoning": {},
        "evidence": {},
        "lineage": {
            "edgeVersion": "ingest-test-edge-1.0",
            "modelVersions": {"detector": "stub"},
            "policyVersion": "ingest-test-policy-1",
            "calibrationProfileId": "ingest-test-cal-1",
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


def _entry(
    *,
    sequence: int = 0,
    key: str | None = None,
    device: str = "edge-001",
    payload: dict[str, Any] | None = None,
) -> JournalEntry:
    body = payload if payload is not None else _bundle_payload(f"evt-{sequence}")
    return JournalEntry(
        idempotency_key=key if key is not None else f"{device}:{sequence}",
        device_sequence=sequence,
        edge_device_id=device,
        payload_digest=payload_digest(body),
        payload=body,
    )


@pytest.fixture
def store(tmp_path: Path) -> EdgeSyncStore:
    return EdgeSyncStore(tmp_path / "edge-sync" / "journal.jsonl")


# ── durable 후 ACK · 재시작 복원 ─────────────────────────────────────────────


def test_accepted_entry_is_durable_before_ack(store: EdgeSyncStore, tmp_path: Path) -> None:
    result = store.ingest_event_bundle(_entry(sequence=0))
    assert result.verdict is IngestVerdict.ACCEPTED
    journal = tmp_path / "edge-sync" / "journal.jsonl"
    assert journal.is_file(), "ACK 시점에 디스크에 없다 — ACK 후 유실 경로"
    revived = JournalEntry.model_validate_json(journal.read_text(encoding="utf-8").strip())
    assert revived.device_sequence == 0


def test_restart_preserves_idempotency_and_order(tmp_path: Path) -> None:
    """[핵심] 재시작 후에도 같은 항목의 재전송은 새 항목이 되지 않는다."""
    path = tmp_path / "journal.jsonl"
    first = EdgeSyncStore(path)
    entry0, entry1 = _entry(sequence=0), _entry(sequence=1)
    assert first.ingest_event_bundle(entry0).verdict is IngestVerdict.ACCEPTED
    assert first.ingest_event_bundle(entry1).verdict is IngestVerdict.ACCEPTED

    first.close()  # 프로세스 종료 재현(flock 해제)
    reborn = EdgeSyncStore(path)  # 프로세스 재시작 재현
    assert reborn.accepted_count() == 2
    assert reborn.accepted_sequences("edge-001") == [0, 1], "순서 보존이 재시작을 넘지 못했다"
    assert reborn.ingest_event_bundle(entry0).verdict is IngestVerdict.DUPLICATE_IGNORED
    # 복원된 순번 원장 위에서 다음 항목은 정상 진행된다.
    assert reborn.ingest_event_bundle(_entry(sequence=2)).verdict is IngestVerdict.ACCEPTED


def test_ack_lost_retransmission_has_single_effect(store: EdgeSyncStore) -> None:
    """ACK 유실 재현 — 같은 항목 2회 전송 = 원장 1건."""
    entry = _entry(sequence=0)
    assert store.ingest_event_bundle(entry).verdict is IngestVerdict.ACCEPTED
    assert store.ingest_event_bundle(entry).verdict is IngestVerdict.DUPLICATE_IGNORED
    assert store.accepted_count() == 1, "재전송이 이벤트 수를 부풀렸다 — 안전 판단 왜곡"


def test_corrupted_journal_refuses_startup(tmp_path: Path) -> None:
    """오염된 원장(중복 기록) 위에서 조용히 기동하지 않는다."""
    path = tmp_path / "journal.jsonl"
    entry = _entry(sequence=0)
    line = entry.model_dump_json(by_alias=True)
    path.write_text(line + "\n" + line + "\n", encoding="utf-8")  # 같은 항목 2줄
    with pytest.raises(StoreRecoveryError, match="재적재 거부"):
        EdgeSyncStore(path)


def test_garbage_journal_line_refuses_startup(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    path.write_text('{"not": "a journal entry"}\n', encoding="utf-8")
    with pytest.raises(StoreRecoveryError, match="JournalEntry"):
        EdgeSyncStore(path)


def test_append_failure_returns_no_ack_and_seals(
    store: EdgeSyncStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[fail-closed 핵심] durable 실패 시 ACCEPTED 를 반환하지 않고 봉인된다.

    봉인하지 않으면: 메모리 원장에는 반영된 상태라 Edge 의 재전송이
    DUPLICATE_IGNORED(ACK)로 응답되고, Edge 는 로컬을 지운다 — 디스크에 없는
    항목이 세상에서 사라진다.
    """
    entry = _entry(sequence=0)

    def broken_append(_entry: JournalEntry) -> None:
        raise OSError("disk full (주입 실패)")

    monkeypatch.setattr(store, "_append_durable", broken_append)
    result = store.ingest_event_bundle(entry)
    assert result.verdict is ServerVerdict.STORE_UNAVAILABLE, "durable 실패가 ACK 로 둔갑했다"
    assert store.sealed

    monkeypatch.undo()
    retry = store.ingest_event_bundle(entry)
    assert retry.verdict is ServerVerdict.STORE_UNAVAILABLE, (
        "봉인 후 재전송이 DUPLICATE_IGNORED(ACK)로 응답되면 유실이 확정된다"
    )


def test_after_seal_restart_recovers_and_accepts_retransmission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """봉인 → 재시작 → 디스크 기준 복원 → 문제 항목 재전송이 정상 수락(유실 없음)."""
    path = tmp_path / "journal.jsonl"
    first = EdgeSyncStore(path)
    assert first.ingest_event_bundle(_entry(sequence=0)).verdict is IngestVerdict.ACCEPTED

    entry1 = _entry(sequence=1)
    monkeypatch.setattr(
        first, "_append_durable", lambda _e: (_ for _ in ()).throw(OSError("주입"))
    )
    assert first.ingest_event_bundle(entry1).verdict is ServerVerdict.STORE_UNAVAILABLE

    first.close()
    reborn = EdgeSyncStore(path)
    assert reborn.accepted_count() == 1  # 디스크 진실: entry1 은 없다
    assert reborn.ingest_event_bundle(entry1).verdict is IngestVerdict.ACCEPTED


# ── SyncLedger 규칙이 배선을 통과해도 성립 ───────────────────────────────────


def test_conflict_and_sequence_rules_survive_wiring(store: EdgeSyncStore) -> None:
    assert store.ingest_event_bundle(_entry(sequence=0)).verdict is IngestVerdict.ACCEPTED
    assert store.ingest_event_bundle(_entry(sequence=2)).verdict is IngestVerdict.ACCEPTED

    # 같은 키, 다른 내용 — 충돌
    other = _entry(sequence=5, key="edge-001:0")
    assert (
        store.ingest_event_bundle(other).verdict is IngestVerdict.IDEMPOTENCY_CONFLICT
    )
    # 이미 사용된 순번에 새 키 — 순번 중복(역행 판정보다 먼저 잡힌다)
    assert (
        store.ingest_event_bundle(_entry(sequence=0, key="dup-key")).verdict
        is IngestVerdict.SEQUENCE_DUPLICATE
    )
    # 미사용 과거 순번(1 < 최종 2)에 새 키 — 순번 역행
    assert (
        store.ingest_event_bundle(_entry(sequence=1, key="new-key")).verdict
        is IngestVerdict.SEQUENCE_REGRESSION
    )
    # digest 불일치
    tampered = JournalEntry(
        idempotency_key="edge-001:9",
        device_sequence=9,
        edge_device_id="edge-001",
        payload_digest="sha256:" + "0" * 64,
        payload=_bundle_payload(),
    )
    assert store.ingest_event_bundle(tampered).verdict is IngestVerdict.DIGEST_MISMATCH
    # 거부들은 durable 원장에 반영되지 않았다
    assert store.accepted_count() == 2


# ── EventBundle v1.2 사전 검증 (INV-031) ─────────────────────────────────────


def test_non_bundle_payload_rejected_without_ledger_effect(store: EdgeSyncStore) -> None:
    """계보 없는 payload 는 원장을 선점하지 못한다 — 수정본 재전송이 수락돼야 한다."""
    bad = _bundle_payload()
    del bad["lineage"]["classification"]  # v1.1 형태(계보 단절) 재현
    entry = _entry(sequence=0, payload=bad)
    result = store.ingest_event_bundle(entry)
    assert result.verdict is ServerVerdict.INVALID_EVENT_BUNDLE
    assert store.accepted_count() == 0

    # 같은 키로 수정본을 보내면 — 원장이 선점되지 않았으므로 정상 수락된다.
    fixed = _entry(sequence=0, key=entry.idempotency_key)
    assert store.ingest_event_bundle(fixed).verdict is IngestVerdict.ACCEPTED


def test_arbitrary_dict_payload_rejected(store: EdgeSyncStore) -> None:
    entry = _entry(sequence=0, payload={"free": "form", "not": "an event bundle"})
    assert (
        store.ingest_event_bundle(entry).verdict is ServerVerdict.INVALID_EVENT_BUNDLE
    )


# ── HTTP 배선 ────────────────────────────────────────────────────────────────


_EDGE_TOKEN = "edge-device-token"  # noqa: S105 — 테스트 고정 토큰
_VIEWER_TOKEN = "viewer-token"  # noqa: S105 — EVENTS_READ 보유(사용자 조회 테스트)
_SAME_ORG_VIEWER_TOKEN = "same-org-viewer-token"  # noqa: S105 — test fixed token
_EDGE_DEVICE_ID = "edge-001"  # _entry() 기본 edge_device_id 와 일치해야 한다
_EDGE_ORGANIZATION_ID = "org-edge"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_EDGE_TOKEN),
                principal=Principal(
                    principal_id="edge-principal-1",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id=_EDGE_DEVICE_ID,
                    organization_id=_EDGE_ORGANIZATION_ID,
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
            PrincipalTokenRecord(
                token_sha256=_digest(_SAME_ORG_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="same-org-vw-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                    organization_id=_EDGE_ORGANIZATION_ID,
                ),
            ),
        ]
    )


def _client_with_event_store(tmp_path: Path) -> tuple[TestClient, EdgeSyncStore, EventStore]:
    store = EdgeSyncStore(tmp_path / "journal.jsonl")
    event_store = EventStore(DurableJournal(tmp_path / "events" / "journal.jsonl"))
    app = create_app(
        edge_sync_store=store, event_store=event_store, auth_registry=_auth_registry()
    )
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_EDGE_TOKEN}"})
    return client, store, event_store


def _client(tmp_path: Path) -> tuple[TestClient, EdgeSyncStore]:
    client, store, _event_store = _client_with_event_store(tmp_path)
    return client, store


def _post(client: TestClient, entry: JournalEntry) -> Any:
    return client.post(
        "/v1/edge-sync/event-bundles",
        content=entry.model_dump_json(by_alias=True),
        headers={"Content-Type": "application/json"},
    )


def test_http_status_mapping_and_real_store_effect(tmp_path: Path) -> None:
    """[공허 방지] 라우터가 실제 store 를 호출하고 상태코드가 verdict 를 따른다."""
    client, store, event_store = _client_with_event_store(tmp_path)
    entry = _entry(sequence=0)

    created = _post(client, entry)
    assert created.status_code == 201
    assert created.json()["verdict"] == "ACCEPTED"
    assert store.accepted_count() == 1, "API 가 store 를 실제로 호출하지 않았다"
    projected = event_store.get(make_event_key(_EDGE_DEVICE_ID, "evt-0"))
    assert projected is not None
    assert projected.organization_id == _EDGE_ORGANIZATION_ID

    duplicate = _post(client, entry)
    assert duplicate.status_code == 200
    assert duplicate.json()["verdict"] == "DUPLICATE_IGNORED"

    conflict = _post(client, _entry(sequence=7, key=entry.idempotency_key))
    assert conflict.status_code == 409
    assert conflict.json()["verdict"] == "IDEMPOTENCY_CONFLICT"

    bad = _bundle_payload()
    del bad["lineage"]["classification"]
    invalid = _post(client, _entry(sequence=1, payload=bad))
    assert invalid.status_code == 422
    assert invalid.json()["verdict"] == "INVALID_EVENT_BUNDLE"


def test_sealed_store_returns_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, store = _client(tmp_path)
    monkeypatch.setattr(
        store, "_append_durable", lambda _e: (_ for _ in ()).throw(OSError("주입"))
    )
    response = _post(client, _entry(sequence=0))
    assert response.status_code == 503
    assert response.json()["verdict"] == "STORE_UNAVAILABLE"


def test_endpoint_absent_without_store() -> None:
    """store 없는 조립에는 엔드포인트 자체가 없다 — 유실 경로 구성 불가."""
    client = TestClient(create_app())
    response = client.post("/v1/edge-sync/event-bundles", json={})
    assert response.status_code == 404


def test_edge_sync_store_requires_event_store(tmp_path: Path) -> None:
    """[ADR-KSI-008 §3] edge_sync_store 만 있고 event_store 가 없으면 조립 거부.

    수신은 ACK 했는데 트리아지에 안 보이는 조용한 유실 표면을 절반짜리 조립으로
    만들지 않는다(mission_signing_key/key_id 짝 강제와 동형).
    """
    store = EdgeSyncStore(tmp_path / "journal.jsonl")
    with pytest.raises(ValueError, match="event_store"):
        create_app(edge_sync_store=store)


def test_malformed_journal_entry_body_is_422(tmp_path: Path) -> None:
    """JournalEntry 계약 위반(잘못된 digest 형식 등)은 pydantic 경계에서 422."""
    client, _ = _client(tmp_path)
    body = _entry(sequence=0).model_dump(by_alias=True)
    body["payloadDigest"] = "md5:abc"
    response = client.post("/v1/edge-sync/event-bundles", json=body)
    assert response.status_code == 422


# ── 반증 리뷰(2026-07-29) 폐쇄 — durable 경계 강화 ───────────────────────────


def test_unicode_line_separator_payload_survives_restart(tmp_path: Path) -> None:
    """[P1-2 실측 폐쇄] U+2028/2029/0085 payload 가 ACK 후 재시작을 깨지 않는다.

    ensure_ascii 없이 쓰면 pydantic 직렬화가 이 문자들을 raw 로 내보내
    splitlines() 재적재가 한 줄을 두 줄로 쪼갰다 — ACK 된 원장이 영구 기동
    불가가 되는 실측 결함이었다.
    """
    path = tmp_path / "journal.jsonl"
    first = EdgeSyncStore(path)
    payload = _bundle_payload()
    payload["reasoning"] = {"note": "a\u2028b\u2029c\u0085d"}
    entry = _entry(sequence=0, payload=payload)
    assert first.ingest_event_bundle(entry).verdict is IngestVerdict.ACCEPTED
    first.close()

    reborn = EdgeSyncStore(path)  # 기동 거부되면 여기서 StoreRecoveryError
    assert reborn.accepted_count() == 1
    assert reborn.ingest_event_bundle(entry).verdict is IngestVerdict.DUPLICATE_IGNORED
    reborn.close()


def test_torn_tail_is_quarantined_not_fatal(tmp_path: Path) -> None:
    """[P1-3 폐쇄] 개행 없는 마지막 부분 줄(부분 쓰기 흔적)은 기동을 막지 않는다.

    torn tail 은 완결 write+fsync 전이라 ACK 된 적이 없다 — Edge 가 들고 있으므로
    재전송으로 복구된다. 기동 거부하면 봉인의 가장 흔한 원인(ENOSPC 부분 쓰기)
    뒤에 재전송할 서버 자체가 사라진다.
    """
    path = tmp_path / "journal.jsonl"
    first = EdgeSyncStore(path)
    assert first.ingest_event_bundle(_entry(sequence=0)).verdict is IngestVerdict.ACCEPTED
    first.close()
    with path.open("ab") as handle:
        handle.write(b'{"idempotencyKey": "torn-partial-wri')  # 개행 없음

    reborn = EdgeSyncStore(path)
    assert reborn.accepted_count() == 1, "완결 줄이 소실됐다"
    raw = path.read_bytes()
    assert raw.endswith(b"\n") and b"torn-partial" not in raw, "torn tail 이 잘리지 않았다"
    # 잘린 자리에 다음 append 가 깨끗하게 이어진다 + 그 항목 재전송은 정상 수락
    assert reborn.ingest_event_bundle(_entry(sequence=1)).verdict is IngestVerdict.ACCEPTED
    reborn.close()
    reread = EdgeSyncStore(path)
    assert reread.accepted_count() == 2
    reread.close()


def test_torn_middle_line_still_refuses_startup(tmp_path: Path) -> None:
    """중간 줄 손상은 torn tail 이 아니라 진짜 오염 — fail-closed 유지."""
    path = tmp_path / "journal.jsonl"
    first = EdgeSyncStore(path)
    assert first.ingest_event_bundle(_entry(sequence=0)).verdict is IngestVerdict.ACCEPTED
    first.close()
    content = path.read_bytes()
    path.write_bytes(b'{"broken": true}\n' + content)  # 중간(첫) 줄 오염, 개행 완결
    with pytest.raises(StoreRecoveryError, match="JournalEntry"):
        EdgeSyncStore(path)


def test_non_oserror_append_failure_also_seals(
    store: EdgeSyncStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[P1-1 폐쇄] OSError 밖의 예외도 봉인한다 — 안 하면 재전송이 ACK 로 둔갑."""

    def broken_append(_entry: JournalEntry) -> None:
        raise MemoryError("주입")

    entry = _entry(sequence=0)
    monkeypatch.setattr(store, "_append_durable", broken_append)
    with pytest.raises(MemoryError):
        store.ingest_event_bundle(entry)  # 삼키지 않고 전파하되
    assert store.sealed, "비-OSError 실패가 봉인 없이 지나갔다 — 유실 예비 상태"
    monkeypatch.undo()
    assert (
        store.ingest_event_bundle(entry).verdict is ServerVerdict.STORE_UNAVAILABLE
    ), "봉인 후 재전송이 DUPLICATE_IGNORED(ACK)면 유실 확정"


def test_new_journal_file_fsyncs_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[P0-1 폐쇄] 새 파일 첫 append 는 부모 디렉터리도 fsync 한다.

    머신 크래시 재현은 불가하므로, POSIX 요구(디렉터리 엔트리 durability)의
    이행 여부를 fsync 대상 fd 로 검증한다.
    """
    import os as os_module
    import stat

    synced_dirs: list[bool] = []
    real_fsync = os_module.fsync

    def spy_fsync(fd: int) -> None:
        synced_dirs.append(stat.S_ISDIR(os_module.fstat(fd).st_mode))
        real_fsync(fd)

    from ksi_core import edge_sync as edge_sync_module

    monkeypatch.setattr(edge_sync_module.os, "fsync", spy_fsync)
    store = EdgeSyncStore(tmp_path / "fresh" / "journal.jsonl")
    assert store.ingest_event_bundle(_entry(sequence=0)).verdict is IngestVerdict.ACCEPTED
    assert True in synced_dirs, "디렉터리 fsync 없음 — ACK 후 머신 크래시에 파일째 소실 가능"
    # 두 번째 append 는 파일이 이미 존재 — 디렉터리 fsync 불요(파일 fsync 만)
    synced_dirs.clear()
    assert store.ingest_event_bundle(_entry(sequence=1)).verdict is IngestVerdict.ACCEPTED
    assert True not in synced_dirs
    store.close()


def test_second_process_writer_is_refused(tmp_path: Path) -> None:
    """[P2-3 폐쇄] 같은 journal 에 두 번째 writer — 기동 거부(단일 writer 강제)."""
    path = tmp_path / "journal.jsonl"
    first = EdgeSyncStore(path)
    with pytest.raises(StoreRecoveryError, match="단일 writer"):
        EdgeSyncStore(path)
    first.close()
    # 정상 종료 후에는 새 writer 가 잡을 수 있다
    second = EdgeSyncStore(path)
    second.close()


def test_lone_surrogate_payload_is_typed_malformed(store: EdgeSyncStore) -> None:
    """[P2-5 실측 폐쇄] 짝 없는 surrogate 는 500 이 아니라 typed MALFORMED_PAYLOAD.

    stdlib json.loads 는 "\\ud800" 을 거부하지 않고 str 에 담지만 UTF-8 encode 가
    불가능하다 — encode 가 try 밖에 있어 UnicodeEncodeError 가 "예외를 던지지
    않는다" 계약을 뚫던 경로.
    """
    import json as json_module

    payload = json_module.loads('{"a": "\\ud800"}')
    entry = JournalEntry(
        idempotency_key="k-surrogate",
        device_sequence=0,
        edge_device_id="edge-001",
        payload_digest="sha256:" + "0" * 64,  # digest 계산 자체가 불가한 본문
        payload=payload,
    )
    # EventBundle 검증이 먼저 거부하므로 라우터 경로에선 INVALID_EVENT_BUNDLE 이고,
    # SyncLedger 계약 수준에서는 MALFORMED_PAYLOAD 다 — 둘 다 예외 누출이 아니다.
    from ksi_event_contracts.offline_sync import SyncLedger

    verdict = SyncLedger().ingest(entry).verdict
    assert verdict is IngestVerdict.MALFORMED_PAYLOAD
    server = store.ingest_event_bundle(entry)
    assert server.verdict is ServerVerdict.INVALID_EVENT_BUNDLE


def test_status_map_covers_every_verdict() -> None:
    """[P3 폐쇄] verdict enum 이 늘었는데 상태코드 매핑이 빠지면 500 — 전 멤버 강제."""
    from ksi_core.edge_sync import _STATUS

    for verdict in list(IngestVerdict) + list(ServerVerdict):
        assert verdict in _STATUS, f"{verdict} 의 HTTP 매핑 누락"


def test_store_unavailable_detail_does_not_leak_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[P3 폐쇄] 봉인 응답 detail 에 서버 파일 경로가 노출되지 않는다."""
    client, store = _client(tmp_path)

    def broken(_e: JournalEntry) -> None:
        raise OSError(28, "No space left on device", str(tmp_path / "journal.jsonl"))

    monkeypatch.setattr(store, "_append_durable", broken)
    response = _post(client, _entry(sequence=0))
    assert response.status_code == 503
    assert str(tmp_path) not in (response.json()["detail"] or "")
    assert response.headers.get("Retry-After") == "30"


def test_short_write_is_not_acked_and_seals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[감사 #1 폐쇄, HIGH] POSIX short write(무예외 부분 기록)가 ACK 로 둔갑하지 않는다.

    수정 전: os.write 반환값을 버려 부분 줄이 기록된 채 fsync 성공 → 201 ACCEPTED
    → 재시작 시 torn tail 로 잘려 그 이벤트가 영구 유실(모듈의 P0 불변식 자체가
    자기 구현으로 깨짐 — reviewer adversarial 검증이 적발).
    """
    from ksi_core import edge_sync as edge_sync_module

    path = tmp_path / "journal.jsonl"
    store = EdgeSyncStore(path)
    entry = _entry(sequence=0)

    real_write = edge_sync_module._WRITE
    calls: list[int] = []

    def short_write(fd: int, data: bytes | memoryview) -> int:
        calls.append(len(bytes(data)))
        if len(calls) == 1:
            return real_write(fd, bytes(data)[: len(bytes(data)) // 2])  # 절반만
        return 0  # 이후 진전 없음(ENOSPC 재현)

    monkeypatch.setattr(edge_sync_module, "_WRITE", short_write)
    result = store.ingest_event_bundle(entry)
    assert result.verdict is ServerVerdict.STORE_UNAVAILABLE, (
        "short write 가 ACCEPTED(ACK)로 둔갑했다 — ACK 후 영구 유실 경로"
    )
    assert store.sealed
    assert len(calls) >= 2, "전량 기록 루프가 재시도하지 않았다"

    monkeypatch.undo()
    store.close()
    # 재시작: 부분 줄은 torn tail 로 격리되고, ACK 못 받은 항목의 재전송이 수락된다.
    reborn = EdgeSyncStore(path)
    assert reborn.accepted_count() == 0
    assert reborn.ingest_event_bundle(entry).verdict is IngestVerdict.ACCEPTED
    reborn.close()


def test_rejection_detail_does_not_leak_ledger_identities(tmp_path: Path) -> None:
    """[감사 #8] 409 응답이 원장 측 기존 신원(다른 항목의 키)을 노출하지 않는다."""
    client, _store = _client(tmp_path)
    first = _entry(sequence=0, key="secret-key-alpha")
    assert _post(client, first).status_code == 201
    conflict = _post(client, _entry(sequence=7, key="secret-key-alpha"))
    assert conflict.status_code == 409
    # (충돌 자체의 detail 은 자기 요청 키를 담을 수 있다 — 클라이언트가 이미 아는 값)
    # 다른 항목의 신원이 새는 대표 케이스: 순번 중복 응답에 기존 키가 실리면 안 된다
    dup = _post(client, _entry(sequence=0, key="probe-key"))
    assert dup.status_code == 409
    dup_detail = dup.json()["detail"] or ""
    assert "secret-key-alpha" not in dup_detail, "원장 측 기존 키가 응답으로 열거된다"


def test_closed_store_refuses_ingest(tmp_path: Path) -> None:
    """[감사 #51] close 후 수신은 STORE_UNAVAILABLE — 잠금 없는 기록 창 제거."""
    store = EdgeSyncStore(tmp_path / "journal.jsonl")
    assert store.ingest_event_bundle(_entry(sequence=0)).verdict is IngestVerdict.ACCEPTED
    store.close()
    store.close()  # 멱등
    assert (
        store.ingest_event_bundle(_entry(sequence=1)).verdict
        is ServerVerdict.STORE_UNAVAILABLE
    )


# ── 인증 장비 신원 바인딩 (ADR-KSI-008 §2) — 사전인증 순번 봉쇄 해소 ─────────────


def test_ingest_requires_authentication_401(tmp_path: Path) -> None:
    client, _store = _client(tmp_path)
    client.headers.pop("Authorization")

    response = _post(client, _entry(sequence=0))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_ingest_rejects_operator_token_403(tmp_path: Path) -> None:
    """OPERATOR 는 EDGE_SYNC_INGEST 권한이 없다(사람은 edge ingest 불가, auth.py 관습)."""
    client, _store = _client(tmp_path)
    client.headers.update({"Authorization": f"Bearer {_VIEWER_TOKEN}"})

    response = _post(client, _entry(sequence=0))

    assert response.status_code == 403


def test_device_mismatch_rejected_before_ledger_effect(tmp_path: Path) -> None:
    """[P1-4 해소] 인증 장비와 다른 edgeDeviceId 를 자칭한 수신은 원장에 반영되지 않는다."""
    client, store = _client(tmp_path)

    response = _post(client, _entry(sequence=0, device="impostor-device"))

    assert response.status_code == 403
    assert response.json()["verdict"] == "DEVICE_MISMATCH"
    assert store.accepted_count() == 0, "신원 불일치 수신이 원장에 반영됐다"


def test_device_sequence_self_query(tmp_path: Path) -> None:
    client, _store = _client(tmp_path)
    assert _post(client, _entry(sequence=0)).status_code == 201
    assert _post(client, _entry(sequence=1)).status_code == 201

    response = client.get(f"/v1/edge-sync/devices/{_EDGE_DEVICE_ID}/sequence")

    assert response.status_code == 200
    assert response.json() == {"deviceId": _EDGE_DEVICE_ID, "lastSequence": 1}


def test_device_sequence_unknown_device_returns_null(tmp_path: Path) -> None:
    """수락 이력이 없으면 null — 미지 장비와 구분하지 않는다(존재 여부 힌트 금지)."""
    client, _store = _client(tmp_path)

    response = client.get(f"/v1/edge-sync/devices/{_EDGE_DEVICE_ID}/sequence")

    assert response.status_code == 200
    assert response.json() == {"deviceId": _EDGE_DEVICE_ID, "lastSequence": None}


def test_device_sequence_cross_device_query_forbidden(tmp_path: Path) -> None:
    """EDGE_DEVICE 는 자기 자신의 순번만 조회할 수 있다."""
    client, _store = _client(tmp_path)

    response = client.get("/v1/edge-sync/devices/other-device/sequence")

    assert response.status_code == 403


def test_device_sequence_operator_can_query_visible_same_organization_device(
    tmp_path: Path,
) -> None:
    """OPERATOR는 자기 조직에서 projection된 장비의 순번만 읽는다."""
    client, _store = _client(tmp_path)
    assert _post(client, _entry(sequence=0)).status_code == 201
    client.headers.update({"Authorization": f"Bearer {_SAME_ORG_VIEWER_TOKEN}"})

    response = client.get(f"/v1/edge-sync/devices/{_EDGE_DEVICE_ID}/sequence")

    assert response.status_code == 200
    assert response.json()["lastSequence"] == 0


def test_device_sequence_hides_foreign_organization_state_as_unknown(tmp_path: Path) -> None:
    """다른 조직 operator에게는 실제 장비와 미지 장비가 모두 null이다(INV-060)."""
    client, _store = _client(tmp_path)
    assert _post(client, _entry(sequence=0)).status_code == 201
    client.headers.update({"Authorization": f"Bearer {_VIEWER_TOKEN}"})

    response = client.get(f"/v1/edge-sync/devices/{_EDGE_DEVICE_ID}/sequence")
    assert response.status_code == 200
    assert response.json() == {"deviceId": _EDGE_DEVICE_ID, "lastSequence": None}


# ── ADR-KSI-008 §3 핵심 주장 — event projection 실패가 ACK 를 뒤집는다 ──────────
#
# 지금까지 어떤 테스트도 이 경로(edge-sync ACCEPTED → event projection 실패 →
# 503 으로 역전)를 실행한 적이 없었다 — mount_edge_sync 배선의 핵심 주장이
# 코드로 실행된 적이 없는 채였다.


def test_event_projection_failure_reverses_acceptance_and_withholds_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[ADR-KSI-008 §3 실행 검증] edge-sync 자체는 ACCEPTED 였어도 event projection
    이 실패하면 ACK 를 내주지 않고 503 STORE_UNAVAILABLE 로 뒤집는다.

    edge-sync journal 은 이미 durable(``store.accepted_count() == 1``)이지만
    event_store 에는 projection 이 반영되지 않는다(``_apply`` 전에 journal append
    가 실패했으므로) — "수신은 durable 인데 트리아지에 안 보이는 조용한 유실"을
    막는 게이트가 실제로 작동함을 고정한다.
    """
    client, store, event_store = _client_with_event_store(tmp_path)

    def broken_journal_append(_record: dict[str, Any]) -> None:
        raise OSError("event journal append 실패(주입)")

    monkeypatch.setattr(event_store._journal, "append", broken_journal_append)  # noqa: SLF001

    entry = _entry(sequence=0)
    response = _post(client, entry)

    assert response.status_code == 503
    assert response.json()["verdict"] == "STORE_UNAVAILABLE"
    assert store.accepted_count() == 1, "edge-sync 자체의 durable 수락은 뒤집히지 않는다"
    assert event_store.get(make_event_key(_EDGE_DEVICE_ID, "evt-0")) is None, (
        "projection 실패인데 event_store 에 반영됐다 — 조용한 오반영"
    )


# ── 수신 전 게이트가 원장·순번축을 오염시키지 않는다 ────────────────────────────


def test_status_not_edge_assertable_rejection_does_not_block_device_queue(
    tmp_path: Path,
) -> None:
    """STATUS_NOT_EDGE_ASSERTABLE 거부는 SyncLedger 원장·순번을 선점하지 않는다 —
    거부 후 같은 순번의 정상 항목이 정상 수락되고(store-and-forward 큐 봉쇄 없음),
    거부된 항목은 edge-sync journal replay 에 남지 않는다."""
    client, store = _client(tmp_path)

    blocked_payload = _bundle_payload("evt-status-blocked")
    blocked_payload["status"] = "CONFIRMED_EVENT"
    blocked = _post(client, _entry(sequence=0, payload=blocked_payload))
    assert blocked.status_code == 422
    assert blocked.json()["verdict"] == "STATUS_NOT_EDGE_ASSERTABLE"
    assert store.accepted_count() == 0, "정책 거부가 SyncLedger 원장을 선점했다"

    # 같은 순번(0)의 정상 항목이 정상 수락된다 — 영구 422 로 큐가 막히지 않는다.
    good = _post(client, _entry(sequence=0))
    assert good.status_code == 201
    assert good.json()["verdict"] == "ACCEPTED"
    assert store.accepted_count() == 1

    # 재시작 재생에서도 거부된 항목의 흔적이 없다 — 원문이 journal 에 없었다는
    # 증거(있었다면 재생이 그 항목을 반영하거나 오염으로 기동을 거부했을 것).
    store.close()
    reborn = EdgeSyncStore(tmp_path / "journal.jsonl")
    assert reborn.accepted_count() == 1
    assert reborn.accepted_sequences(_EDGE_DEVICE_ID) == [0]
    reborn.close()


def test_invalid_event_identity_rejection_does_not_block_device_queue(
    tmp_path: Path,
) -> None:
    """INVALID_EVENT_IDENTITY 거부도 마찬가지로 SyncLedger 원장·순번을 선점하지
    않는다(위 STATUS_NOT_EDGE_ASSERTABLE 테스트와 대칭)."""
    client, store = _client(tmp_path)

    spoofed_payload = _bundle_payload("evt::spoofed")
    blocked = _post(client, _entry(sequence=0, payload=spoofed_payload))
    assert blocked.status_code == 422
    assert blocked.json()["verdict"] == "INVALID_EVENT_IDENTITY"
    assert store.accepted_count() == 0, "정책 거부가 SyncLedger 원장을 선점했다"

    good = _post(client, _entry(sequence=0))
    assert good.status_code == 201
    assert good.json()["verdict"] == "ACCEPTED"
    assert store.accepted_count() == 1

    store.close()
    reborn = EdgeSyncStore(tmp_path / "journal.jsonl")
    assert reborn.accepted_count() == 1
    assert reborn.accepted_sequences(_EDGE_DEVICE_ID) == [0]
    reborn.close()


@pytest.mark.parametrize(
    "reasoning",
    [
        {"productionEvidence": False},
        {"executionClass": "OFFLINE_REPLAY_EVALUATION"},
        {"rule": "vertical-slice-demo"},
    ],
)
def test_non_production_evidence_does_not_reserve_journal_or_projection(
    tmp_path: Path, reasoning: dict[str, Any]
) -> None:
    """Explicit and legacy replay markers fail before the durable sequence boundary."""

    client, store, event_store = _client_with_event_store(tmp_path)
    replay_payload = _bundle_payload("evt-offline-replay")
    replay_payload["reasoning"] = reasoning

    blocked = _post(client, _entry(sequence=0, payload=replay_payload))
    assert blocked.status_code == 422
    assert blocked.json()["verdict"] == "NON_PRODUCTION_EVIDENCE"
    assert store.accepted_count() == 0
    assert event_store.get(make_event_key(_EDGE_DEVICE_ID, "evt-offline-replay")) is None

    # EventStore의 direct projection 방어도 같은 판정을 낸다. 라우터 사전 게이트만
    # 믿으면 내부 호출자가 우회할 수 있다.
    direct = event_store.project_bundle(
        replay_payload,
        edge_device_id=_EDGE_DEVICE_ID,
        received_at=datetime.now(UTC),
        organization_id=_EDGE_ORGANIZATION_ID,
    )
    assert direct is EventVerdict.NON_PRODUCTION_EVIDENCE

    # 정책 거부가 순번 0을 선점하지 않았으므로 정상 native-style bundle은 진행한다.
    good = _post(client, _entry(sequence=0))
    assert good.status_code == 201
    assert good.json()["verdict"] == "ACCEPTED"
    assert store.accepted_sequences(_EDGE_DEVICE_ID) == [0]
