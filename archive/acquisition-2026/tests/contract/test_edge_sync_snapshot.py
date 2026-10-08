"""edge-sync 원장 스냅샷 계약 (S4 — ops-serving-hardening).

스냅샷은 **최적화**지 두 번째 정본이 아니다. 그래서 이 파일이 반증하는 것은
"빨라졌나"가 아니라 다음 두 가지다:

1. **동등성** — 스냅샷으로 복원한 원장이 전량 재생한 원장과 구별되지 않는다.
   구별되면 스냅샷은 조용히 틀린 상태를 만드는 장치가 된다.
2. **신뢰 방향** — 스냅샷이 깨지면 버리고 전량 재생한다(상태는 정확해진다).
   반대로 journal 쪽이 스냅샷과 어긋나면(짧아졌다·교체됐다) 기동을 거부한다.
   append-only 원장이 줄어드는 것은 설명되지 않는 상태이기 때문이다.

그리고 스냅샷이 **실제로 재계산을 건너뛰는지**를 payload_digest 를 폭파시켜
증명한다 — 건너뛰지 않는다면 스냅샷은 아무 값도 없이 복잡도만 더한 것이다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from ksi_core.edge_sync import EdgeSyncStore, StoreRecoveryError
from ksi_event_contracts import offline_sync
from ksi_event_contracts.offline_sync import (
    IngestVerdict,
    JournalEntry,
    LedgerStateError,
    SyncLedger,
    payload_digest,
)

_FPR = "b" * 64


def _bundle_payload(event_id: str) -> dict[str, Any]:
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
            "edgeVersion": "snapshot-test-edge-1.0",
            "modelVersions": {"detector": "stub"},
            "policyVersion": "snapshot-test-policy-1",
            "calibrationProfileId": "snapshot-test-cal-1",
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


def _entry(sequence: int, *, device: str = "edge-001") -> JournalEntry:
    body = _bundle_payload(f"evt-{device}-{sequence}")
    return JournalEntry(
        idempotency_key=f"{device}:{sequence}",
        device_sequence=sequence,
        edge_device_id=device,
        payload_digest=payload_digest(body),
        payload=body,
    )


def _fill(store: EdgeSyncStore, count: int, *, device: str = "edge-001") -> None:
    for sequence in range(count):
        result = store.ingest_event_bundle(_entry(sequence, device=device))
        assert result.verdict is IngestVerdict.ACCEPTED, result.detail


def _ledger_view(store: EdgeSyncStore, devices: tuple[str, ...]) -> dict[str, Any]:
    """원장을 밖에서 관측 가능한 형태로 굳힌다 — 두 재생 경로 비교용."""
    return {
        "count": store.accepted_count(),
        "sequences": {d: store.accepted_sequences(d) for d in devices},
        "missing": {d: store.missing_sequences(d) for d in devices},
    }


def _snapshot_path(journal: Path) -> Path:
    return journal.with_suffix(journal.suffix + ".snapshot.json")


def _rewrite_snapshot(path: Path, mutate: Any) -> None:
    """스냅샷을 변조하고 digest 를 **다시 맞춰** 준다 — digest 검사에 걸리지
    않는 변조만 남겨, 그 다음 방어선이 실제로 작동하는지 본다."""
    payload = json.loads(path.read_text(encoding="ascii"))
    mutate(payload)
    payload.pop("digest", None)
    body = json.dumps(
        payload, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    )
    import hashlib

    payload["digest"] = f"sha256:{hashlib.sha256(body.encode('ascii')).hexdigest()}"
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding="ascii")


# ── 동등성 — 스냅샷 재생과 전량 재생이 구별되지 않는다 ────────────────────


def test_snapshot_replay_equals_full_replay(tmp_path: Path) -> None:
    """[핵심] 같은 journal 을 두 경로로 열면 원장이 동일하다."""
    devices = ("edge-001", "edge-002")
    snapped = tmp_path / "snap" / "journal.jsonl"
    plain = tmp_path / "plain" / "journal.jsonl"

    for path, every in ((snapped, 3), (plain, None)):
        writer = EdgeSyncStore(path, snapshot_every=every)
        _fill(writer, 7, device="edge-001")
        _fill(writer, 4, device="edge-002")
        writer.close()

    assert _snapshot_path(snapped).is_file(), "스냅샷이 기록되지 않았다"
    assert not _snapshot_path(plain).exists()

    from_snapshot = EdgeSyncStore(snapped, snapshot_every=3)
    from_full = EdgeSyncStore(plain)
    try:
        assert _ledger_view(from_snapshot, devices) == _ledger_view(from_full, devices)
    finally:
        from_snapshot.close()
        from_full.close()


def test_entries_after_snapshot_are_replayed(tmp_path: Path) -> None:
    """스냅샷 이후 구간(꼬리)이 빠지면 그 항목의 재전송이 새 항목이 된다."""
    path = tmp_path / "journal.jsonl"
    writer = EdgeSyncStore(path, snapshot_every=2)
    _fill(writer, 5)  # 스냅샷 경계는 4건째, 5건째는 꼬리에 남는다
    writer.close()

    reborn = EdgeSyncStore(path, snapshot_every=2)
    try:
        assert reborn.accepted_count() == 5
        # 꼬리 항목의 재전송은 멱등 무시여야 한다 — 새 항목이 되면 유실 아닌 중복이다.
        assert reborn.ingest_event_bundle(_entry(4)).verdict is IngestVerdict.DUPLICATE_IGNORED
    finally:
        reborn.close()


def test_snapshot_skips_payload_recanonicalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[게이트 유효성] 스냅샷 복원 구간은 payload_digest 를 다시 부르지 않는다.

    부른다면 스냅샷은 재기동 비용을 전혀 줄이지 못한 것이다 — 이 테스트가
    없으면 "스냅샷을 넣었다"는 사실만 남고 목적이 달성됐는지는 알 수 없다.
    """
    path = tmp_path / "journal.jsonl"
    writer = EdgeSyncStore(path, snapshot_every=4)
    _fill(writer, 4)  # 4건 전부 스냅샷 경계 안쪽
    writer.close()

    def _explode(_payload: Any) -> str:
        raise AssertionError("스냅샷 구간에서 payload_digest 가 재계산됐다")

    monkeypatch.setattr(offline_sync, "payload_digest", _explode)
    reborn = EdgeSyncStore(path, snapshot_every=4)
    try:
        assert reborn.accepted_count() == 4
    finally:
        reborn.close()


# ── 스냅샷이 깨지면 버리고 전량 재생 (상태는 정확해진다) ──────────────────


def test_corrupt_snapshot_falls_back_to_full_replay(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    writer = EdgeSyncStore(path, snapshot_every=2)
    _fill(writer, 4)
    writer.close()

    _snapshot_path(path).write_text("{ not json", encoding="ascii")
    reborn = EdgeSyncStore(path, snapshot_every=2)
    try:
        assert reborn.accepted_count() == 4, "전량 재생으로 같은 상태에 도달해야 한다"
    finally:
        reborn.close()


def test_snapshot_digest_mismatch_falls_back(tmp_path: Path) -> None:
    """digest 를 맞추지 않은 변조는 스냅샷을 통째로 무효화한다."""
    path = tmp_path / "journal.jsonl"
    writer = EdgeSyncStore(path, snapshot_every=2)
    _fill(writer, 4)
    writer.close()

    snapshot = _snapshot_path(path)
    payload = json.loads(snapshot.read_text(encoding="ascii"))
    payload["ledger"]["accepted"] = payload["ledger"]["accepted"][:1]  # digest 는 그대로
    snapshot.write_text(json.dumps(payload, ensure_ascii=True), encoding="ascii")

    reborn = EdgeSyncStore(path, snapshot_every=2)
    try:
        assert reborn.accepted_count() == 4
    finally:
        reborn.close()


def test_rule_violating_snapshot_falls_back(tmp_path: Path) -> None:
    """digest 를 다시 맞춘 변조라도 원장 규칙을 어기면 복원하지 않는다."""
    path = tmp_path / "journal.jsonl"
    writer = EdgeSyncStore(path, snapshot_every=4)
    _fill(writer, 4)
    writer.close()

    def _regress(payload: dict[str, Any]) -> None:
        # 순번 역행을 심는다 — ingest 였다면 SEQUENCE_REGRESSION 으로 막혔을 상태.
        payload["ledger"]["accepted"][-1]["deviceSequence"] = 0
        payload["ledger"]["accepted"][-1]["idempotencyKey"] = "edge-001:injected"

    _rewrite_snapshot(_snapshot_path(path), _regress)

    reborn = EdgeSyncStore(path, snapshot_every=4)
    try:
        assert reborn.accepted_count() == 4, "규칙 위반 스냅샷은 버리고 전량 재생한다"
    finally:
        reborn.close()


def test_unknown_snapshot_version_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    writer = EdgeSyncStore(path, snapshot_every=2)
    _fill(writer, 4)
    writer.close()

    _rewrite_snapshot(_snapshot_path(path), lambda payload: payload.update(version=99))
    reborn = EdgeSyncStore(path, snapshot_every=2)
    try:
        assert reborn.accepted_count() == 4
    finally:
        reborn.close()


# ── journal 쪽이 어긋나면 기동 거부 ───────────────────────────────────────


def test_journal_shorter_than_snapshot_refuses_boot(tmp_path: Path) -> None:
    """[핵심] append-only 파일이 짧아진 상태로는 기동하지 않는다.

    그대로 재생하면 스냅샷이 담은 과거는 남고 journal 이 잃은 구간은 사라져,
    두 정본이 조용히 갈라진 원장으로 서비스가 뜬다.
    """
    path = tmp_path / "journal.jsonl"
    writer = EdgeSyncStore(path, snapshot_every=2)
    _fill(writer, 4)
    writer.close()

    lines = path.read_bytes().split(b"\n")
    path.write_bytes(b"\n".join(lines[:1]) + b"\n")  # 과거 구간을 잘라낸다

    with pytest.raises(StoreRecoveryError, match="스냅샷 경계보다 짧다"):
        EdgeSyncStore(path, snapshot_every=2)


@pytest.mark.parametrize("where", ["boundary_line", "earlier_line"])
def test_journal_replaced_before_boundary_refuses_boot(tmp_path: Path, where: str) -> None:
    """[핵심] 길이는 같지만 내용이 바뀐 원장 — 경계 **이전** 구간까지 잡는다.

    경계 줄 하나만 검사하면, 그 앞 줄의 크기보존 손상이 조용히 통과한다
    (독립 재검토 P1-B). 스냅샷 없는 경로는 모든 줄을 ingest 에 태워 어떤 손상도
    기동 거부이므로, 그 성질이 스냅샷 경로에서만 사라지면 fail-closed 회귀다.
    """
    path = tmp_path / "journal.jsonl"
    writer = EdgeSyncStore(path, snapshot_every=4)
    _fill(writer, 4)
    writer.close()

    raw = bytearray(path.read_bytes())
    boundary = json.loads(_snapshot_path(path).read_text(encoding="ascii"))["throughBytes"]
    # 경계 줄 안 / 첫 줄 안의 한 바이트만 뒤집는다(길이 불변 → 크기 검사 통과).
    target = boundary - 5 if where == "boundary_line" else raw.index(b"\n") - 5
    raw[target] = raw[target] ^ 0x01
    path.write_bytes(bytes(raw))

    with pytest.raises(StoreRecoveryError, match="교체·손상된 흔적"):
        EdgeSyncStore(path, snapshot_every=4)


def test_snapshot_claiming_fewer_entries_refuses_boot(tmp_path: Path) -> None:
    """[핵심] 스냅샷이 경계 구간의 항목을 **덜 주장**하면 기동을 거부한다.

    덜 주장하면 그 구간은 ``resume_at`` 때문에 영영 재생되지 않는다. 그러면
    ``_last_sequence`` 가 내려가 이미 ACK 된 항목의 재전송이 ACCEPTED 로
    되살아나고, journal 에 중복 줄이 생겨 **스냅샷 없이 재기동할 때 영구 기동
    불가**가 된다(독립 재검토 P1-A).
    """
    path = tmp_path / "journal.jsonl"
    writer = EdgeSyncStore(path, snapshot_every=4)
    _fill(writer, 4)
    writer.close()

    _rewrite_snapshot(_snapshot_path(path), lambda s: s["ledger"]["accepted"].pop())

    with pytest.raises(StoreRecoveryError, match="실제 줄 수"):
        EdgeSyncStore(path, snapshot_every=4)


def test_snapshot_without_journal_refuses_boot(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    writer = EdgeSyncStore(path, snapshot_every=2)
    _fill(writer, 4)
    writer.close()
    path.unlink()

    with pytest.raises(StoreRecoveryError, match="journal.*이 없다"):
        EdgeSyncStore(path, snapshot_every=2)


def test_torn_tail_after_snapshot_is_isolated(tmp_path: Path) -> None:
    """스냅샷 오프셋 재생에서도 torn tail 격리 지점이 파일 전체 기준이어야 한다."""
    path = tmp_path / "journal.jsonl"
    writer = EdgeSyncStore(path, snapshot_every=2)
    _fill(writer, 4)
    writer.close()

    intact = path.stat().st_size
    with path.open("ab") as handle:
        handle.write(b'{"idempotencyKey":"edge-001:9","devi')  # 개행 없는 부분 줄

    reborn = EdgeSyncStore(path, snapshot_every=2)
    try:
        assert reborn.accepted_count() == 4
        assert path.stat().st_size == intact, "torn tail 이 정확히 잘려야 한다"
    finally:
        reborn.close()


# ── 조립 인자 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", [0, -1])
def test_non_positive_snapshot_every_rejected(tmp_path: Path, value: int) -> None:
    """0 을 '스냅샷 없음'으로 조용히 해석하지 않는다."""
    with pytest.raises(ValueError, match="snapshot_every"):
        EdgeSyncStore(tmp_path / "journal.jsonl", snapshot_every=value)


def test_no_snapshot_by_default(tmp_path: Path) -> None:
    """기본 조립은 그대로다 — 스냅샷 파일을 만들지 않는다."""
    path = tmp_path / "journal.jsonl"
    store = EdgeSyncStore(path)
    try:
        _fill(store, 3)
    finally:
        store.close()
    assert not _snapshot_path(path).exists()


# ── SyncLedger 상태 표현 자체 ─────────────────────────────────────────────


def test_ledger_state_roundtrip_preserves_order() -> None:
    ledger = SyncLedger()
    for sequence in (0, 1, 2):
        assert ledger.ingest(_entry(sequence)).accepted
    for sequence in (5, 7):
        assert ledger.ingest(_entry(sequence, device="edge-002")).accepted

    restored = SyncLedger.from_state(ledger.export_state())
    assert restored.accepted_count() == ledger.accepted_count()
    assert restored.accepted_sequences("edge-001") == [0, 1, 2]
    assert restored.accepted_sequences("edge-002") == [5, 7]
    assert restored.missing_sequences("edge-002") == ledger.missing_sequences("edge-002")
    # 복원된 원장이 멱등 판정도 그대로 한다.
    assert restored.ingest(_entry(1)).verdict is IngestVerdict.DUPLICATE_IGNORED


def test_ledger_state_never_carries_payload() -> None:
    """본문의 SSOT 는 journal 이다 — 스냅샷이 payload 사본을 들면 두 정본이 된다."""
    ledger = SyncLedger()
    assert ledger.ingest(_entry(0)).accepted
    serialized = json.dumps(ledger.export_state())
    assert "PERSON_PRESENT" not in serialized
    assert "schemaVersion" not in serialized


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda s: s.update(version=2), "version"),
        (lambda s: s.update(accepted="nope"), "accepted 가 배열이 아니다"),
        (lambda s: s["accepted"].append(s["accepted"][0]), "중복"),
        (
            lambda s: s["accepted"][0].update(deviceSequence=True),
            "음이 아닌 정수",
        ),
        (lambda s: s["accepted"][0].update(idempotencyKey=""), "비공백"),
        (lambda s: s["accepted"][0].update(payloadDigest="not-a-digest"), "형식이 아니다"),
    ],
)
def test_ledger_state_rejects_malformed(mutate: Any, match: str) -> None:
    ledger = SyncLedger()
    assert ledger.ingest(_entry(0)).accepted
    assert ledger.ingest(_entry(1)).accepted
    state = ledger.export_state()
    mutate(state)
    with pytest.raises(LedgerStateError, match=match):
        SyncLedger.from_state(state)


# ── 스냅샷 복원 구간의 판정 동등성 (독립 재검토 P2-I) ──────────────────────


def _conflicting_entry(entry: JournalEntry) -> JournalEntry:
    """같은 키·같은 순번인데 **본문이 다른** 항목 — digest 는 정합하게 맞춘다.

    digest 를 깨면 DIGEST_MISMATCH 가 먼저 걸려 멱등 판정에 닿지 못한다.
    """
    other = _bundle_payload("evt-conflict")
    return entry.model_copy(
        update={"payload": other, "payload_digest": payload_digest(other)}
    )


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda e: e, IngestVerdict.DUPLICATE_IGNORED),
        (_conflicting_entry, IngestVerdict.IDEMPOTENCY_CONFLICT),
        (
            lambda e: e.model_copy(update={"idempotency_key": "edge-001:other"}),
            IngestVerdict.SEQUENCE_DUPLICATE,
        ),
    ],
)
def test_snapshot_covered_entries_keep_their_verdicts(
    tmp_path: Path, mutate: Any, expected: IngestVerdict
) -> None:
    """스냅샷 경계 **안쪽** 항목도 전량 재생과 같은 판정을 낸다.

    기존 테스트가 단언하던 항목은 경계 밖(꼬리 재생분)이라, 정작 스냅샷이
    복원한 구간의 멱등·순번 판정은 검증되지 않고 있었다.
    """
    path = tmp_path / "journal.jsonl"
    writer = EdgeSyncStore(path, snapshot_every=4)
    _fill(writer, 4)  # 4건 전부 경계 안쪽
    writer.close()

    reborn = EdgeSyncStore(path, snapshot_every=4)
    try:
        assert reborn.ingest_event_bundle(mutate(_entry(1))).verdict is expected
    finally:
        reborn.close()


def test_snapshot_covered_sequence_regression_is_rejected(tmp_path: Path) -> None:
    """복원 구간의 순번 축도 살아 있다 — 과거 순번의 새 항목은 거부된다."""
    path = tmp_path / "journal.jsonl"
    writer = EdgeSyncStore(path, snapshot_every=4)
    _fill(writer, 4)
    writer.close()

    reborn = EdgeSyncStore(path, snapshot_every=4)
    try:
        stale = _entry(1).model_copy(update={"idempotency_key": "edge-001:late"})
        assert reborn.ingest_event_bundle(stale).verdict is IngestVerdict.SEQUENCE_DUPLICATE
        fresh_regression = _entry(0).model_copy(
            update={"idempotency_key": "edge-001:regress", "device_sequence": 0}
        )
        assert reborn.ingest_event_bundle(fresh_regression).verdict is (
            IngestVerdict.SEQUENCE_DUPLICATE
        )
    finally:
        reborn.close()
