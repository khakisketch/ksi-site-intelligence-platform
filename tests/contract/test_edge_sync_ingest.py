"""Edge→Core EventBundle 멱등 수신·영속 계약 (core-ingest).

offline_sync 의 SyncLedger 규칙이 서버 배선(EdgeSyncStore + FastAPI 라우터)을
통과해도 그대로 성립하는지, 그리고 서버가 더한 두 경계 — **durable 후 ACK**
(PRD §19.3)와 **EventBundle v1.2 사전 검증**(INV-031) — 를 반증한다.

멱등 규칙 자체의 단위 반증(4중 신원·순번·digest)은 offline_sync 계약 테스트
소유이고, 여기서는 배선이 그 규칙을 우회·약화하지 않는지가 초점이다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.edge_sync import EdgeSyncStore, ServerVerdict, StoreRecoveryError
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


def _client(tmp_path: Path) -> tuple[TestClient, EdgeSyncStore]:
    store = EdgeSyncStore(tmp_path / "journal.jsonl")
    app = create_app(edge_sync_store=store)
    return TestClient(app), store


def _post(client: TestClient, entry: JournalEntry) -> Any:
    return client.post(
        "/v1/edge-sync/event-bundles",
        content=entry.model_dump_json(by_alias=True),
        headers={"Content-Type": "application/json"},
    )


def test_http_status_mapping_and_real_store_effect(tmp_path: Path) -> None:
    """[공허 방지] 라우터가 실제 store 를 호출하고 상태코드가 verdict 를 따른다."""
    client, store = _client(tmp_path)
    entry = _entry(sequence=0)

    created = _post(client, entry)
    assert created.status_code == 201
    assert created.json()["verdict"] == "ACCEPTED"
    assert store.accepted_count() == 1, "API 가 store 를 실제로 호출하지 않았다"

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
