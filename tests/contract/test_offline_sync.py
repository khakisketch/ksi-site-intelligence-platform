"""Store-and-Forward 멱등 재동기화 계약 검증 (P1-3, EDGE-004·INV-012).

green≠작동 초점: "동기화가 실행된다"가 아니라 **재전송이 중복을 만들지 않고, 순서가
보존되며, 같은 키에 다른 내용이 오면 거부되는지**를 확인한다. 이벤트 수가 부풀려지면
안전 판단 자체가 왜곡되므로 멱등성은 성능 문제가 아니라 정확성 문제다.
"""

from __future__ import annotations

from typing import Any

import pytest
from ksi_event_contracts.offline_sync import (
    IngestVerdict,
    JournalEntry,
    SyncLedger,
    payload_digest,
)
from pydantic import ValidationError

_DEVICE = "manifold-001"


def _entry(
    key: str,
    sequence: int,
    payload: dict[str, Any] | None = None,
    *,
    device: str = _DEVICE,
    digest: str | None = None,
) -> JournalEntry:
    body = payload if payload is not None else {"eventId": key, "severity": "HIGH"}
    return JournalEntry(
        idempotency_key=key,
        device_sequence=sequence,
        edge_device_id=device,
        payload_digest=digest if digest is not None else payload_digest(body),
        payload=body,
    )


# ── 멱등성 (핵심) ─────────────────────────────────────────────────────────────


def test_first_ingest_is_accepted() -> None:
    ledger = SyncLedger()
    result = ledger.ingest(_entry("evt-1", 0))
    assert result.verdict is IngestVerdict.ACCEPTED
    assert result.accepted
    assert ledger.accepted_count() == 1


def test_resend_of_same_entry_does_not_duplicate() -> None:
    """[EDGE-004] ACK 유실 후 재전송 — 결과가 한 번 보낸 것과 같아야 한다."""
    ledger = SyncLedger()
    entry = _entry("evt-1", 0)

    first = ledger.ingest(entry)
    second = ledger.ingest(entry)
    third = ledger.ingest(entry)

    assert first.verdict is IngestVerdict.ACCEPTED
    assert second.verdict is IngestVerdict.DUPLICATE_IGNORED
    assert third.verdict is IngestVerdict.DUPLICATE_IGNORED
    assert not second.accepted, "멱등 무시는 '새로 반영됨'이 아니다"
    assert ledger.accepted_count() == 1, "재전송이 이벤트 수를 부풀렸다"


def test_many_resends_still_single_entry() -> None:
    """연결 불안정으로 10회 재전송돼도 1건이다."""
    ledger = SyncLedger()
    entry = _entry("evt-1", 0)
    for _ in range(10):
        ledger.ingest(entry)
    assert ledger.accepted_count() == 1


def test_reconstructed_equivalent_entry_is_still_idempotent() -> None:
    """Edge가 재시작해 객체를 새로 만들어도 키·내용이 같으면 멱등이어야 한다.

    같은 객체 인스턴스인지가 아니라 **키와 digest**가 판정 기준임을 확인한다.
    """
    ledger = SyncLedger()
    ledger.ingest(_entry("evt-1", 0, {"eventId": "evt-1", "severity": "HIGH"}))
    result = ledger.ingest(_entry("evt-1", 0, {"eventId": "evt-1", "severity": "HIGH"}))

    assert result.verdict is IngestVerdict.DUPLICATE_IGNORED
    assert ledger.accepted_count() == 1


def test_payload_key_order_does_not_break_idempotency() -> None:
    """dict 삽입 순서가 달라도 정규화 digest가 같아 멱등이 유지된다."""
    ledger = SyncLedger()
    ledger.ingest(_entry("evt-1", 0, {"eventId": "evt-1", "severity": "HIGH"}))
    reordered = _entry("evt-1", 0, {"severity": "HIGH", "eventId": "evt-1"})

    assert ledger.ingest(reordered).verdict is IngestVerdict.DUPLICATE_IGNORED
    assert ledger.accepted_count() == 1


# ── 같은 키 다른 내용 = 충돌 ──────────────────────────────────────────────────


def test_same_key_different_payload_is_conflict_not_silent_overwrite() -> None:
    """같은 idempotency_key에 다른 내용 — 조용히 덮어쓰면 증거가 조작된다."""
    ledger = SyncLedger()
    ledger.ingest(_entry("evt-1", 0, {"eventId": "evt-1", "severity": "HIGH"}))

    tampered = _entry("evt-1", 0, {"eventId": "evt-1", "severity": "LOW"})
    result = ledger.ingest(tampered)

    assert result.verdict is IngestVerdict.DIGEST_CONFLICT
    assert not result.accepted
    assert ledger.accepted_count() == 1, "충돌 항목이 반영되면 안 된다"


def test_declared_digest_must_match_actual_payload() -> None:
    """선언한 digest와 실제 본문이 다르면 거부 — 전송 중 변조·버그 탐지."""
    ledger = SyncLedger()
    wrong = _entry("evt-1", 0, digest="sha256:" + "0" * 64)

    result = ledger.ingest(wrong)

    assert result.verdict is IngestVerdict.DIGEST_MISMATCH
    assert ledger.accepted_count() == 0


# ── 순서·계보 보존 ────────────────────────────────────────────────────────────


def test_sequential_entries_preserve_order() -> None:
    """[PRD §21.2] Edge 관측 순서가 서버에서도 유지돼야 한다."""
    ledger = SyncLedger()
    for i in range(5):
        assert ledger.ingest(_entry(f"evt-{i}", i)).accepted

    assert ledger.accepted_sequences(_DEVICE) == [0, 1, 2, 3, 4]


def test_sequence_regression_rejected() -> None:
    """새 항목의 순번이 과거로 역행하면 순서 보존이 깨진다 — 거부."""
    ledger = SyncLedger()
    ledger.ingest(_entry("evt-5", 5))

    result = ledger.ingest(_entry("evt-3", 3))

    assert result.verdict is IngestVerdict.SEQUENCE_REGRESSION
    assert ledger.accepted_count() == 1


def test_same_sequence_different_key_rejected() -> None:
    """같은 순번을 다른 키가 재사용하면 어느 쪽이 그 순번인지 알 수 없다 — 거부."""
    ledger = SyncLedger()
    ledger.ingest(_entry("evt-a", 7))

    result = ledger.ingest(_entry("evt-b", 7))

    assert result.verdict is IngestVerdict.SEQUENCE_DUPLICATE
    assert ledger.accepted_count() == 1


def test_resend_is_checked_before_sequence_rules() -> None:
    """재전송은 당연히 순번이 역행하므로, 멱등 판정이 순번 규칙보다 먼저여야 한다.

    이 순서가 뒤바뀌면 정상 재전송이 SEQUENCE_REGRESSION으로 오판되어 Edge가
    영원히 로컬 데이터를 지울 수 없게 된다(ACK를 못 받으므로).
    """
    ledger = SyncLedger()
    old = _entry("evt-0", 0)
    ledger.ingest(old)
    ledger.ingest(_entry("evt-1", 1))
    ledger.ingest(_entry("evt-2", 2))

    # 순번 0의 재전송 — 현재 최종 순번은 2다.
    result = ledger.ingest(old)

    assert result.verdict is IngestVerdict.DUPLICATE_IGNORED, (
        "정상 재전송이 순번 역행으로 오판되면 Edge가 ACK를 못 받아 journal이 무한 증가한다"
    )


def test_gap_detection_reports_missing_sequences() -> None:
    """빈 구간을 보고해 서버가 무엇을 더 기다려야 하는지 알 수 있다."""
    ledger = SyncLedger()
    for sequence in (0, 1, 4, 5):
        ledger.ingest(_entry(f"evt-{sequence}", sequence))

    assert ledger.missing_sequences(_DEVICE) == [2, 3]


def test_no_gap_reported_when_contiguous() -> None:
    ledger = SyncLedger()
    for sequence in range(4):
        ledger.ingest(_entry(f"evt-{sequence}", sequence))
    assert ledger.missing_sequences(_DEVICE) == []


def test_gap_filled_later_clears_missing_report() -> None:
    """빈 구간이 나중에 채워지면 누락 보고에서 사라진다.

    단, 채워 넣는 항목의 순번은 현재 최종보다 과거이므로 SEQUENCE_REGRESSION으로
    거부된다 — 이는 의도된 보수적 동작이다. 순서 보존을 유지하면서 지연 도착을
    허용하려면 별도의 재정렬 창(reorder window) 정책이 필요하며, 그것은 이후
    단계다. 이 테스트는 현재 계약이 그렇게 동작함을 **명시적으로 고정**한다.
    """
    ledger = SyncLedger()
    ledger.ingest(_entry("evt-0", 0))
    ledger.ingest(_entry("evt-2", 2))
    assert ledger.missing_sequences(_DEVICE) == [1]

    late = ledger.ingest(_entry("evt-1", 1))

    assert late.verdict is IngestVerdict.SEQUENCE_REGRESSION
    assert ledger.missing_sequences(_DEVICE) == [1], "거부된 항목은 구간을 채우지 않는다"


# ── 다중 장비 독립성 ──────────────────────────────────────────────────────────


def test_sequences_are_per_device_independent() -> None:
    """장비별 순번은 서로 독립 — 한 장비의 순번이 다른 장비를 막지 않는다."""
    ledger = SyncLedger()
    ledger.ingest(_entry("a-5", 5, device="manifold-A"))

    result = ledger.ingest(_entry("b-0", 0, device="manifold-B"))

    assert result.accepted, "다른 장비의 순번 0이 거부되면 안 된다"
    assert ledger.accepted_sequences("manifold-A") == [5]
    assert ledger.accepted_sequences("manifold-B") == [0]


def test_idempotency_key_is_global_not_per_device() -> None:
    """키는 전역 유일해야 한다 — 다른 장비가 같은 키를 쓰면 충돌로 잡힌다."""
    ledger = SyncLedger()
    body = {"eventId": "shared", "severity": "HIGH"}
    ledger.ingest(_entry("dup-key", 0, body, device="manifold-A"))

    same_content = ledger.ingest(_entry("dup-key", 0, body, device="manifold-B"))
    assert same_content.verdict is IngestVerdict.DUPLICATE_IGNORED

    different = ledger.ingest(
        _entry("dup-key", 1, {"eventId": "other", "severity": "LOW"}, device="manifold-B")
    )
    assert different.verdict is IngestVerdict.DIGEST_CONFLICT


# ── 계약 모델 검증 ────────────────────────────────────────────────────────────


def test_digest_format_enforced() -> None:
    with pytest.raises(ValidationError):
        JournalEntry(
            idempotency_key="k",
            device_sequence=0,
            edge_device_id=_DEVICE,
            payload_digest="not-a-digest",
            payload={},
        )


def test_negative_sequence_rejected() -> None:
    with pytest.raises(ValidationError):
        JournalEntry(
            idempotency_key="k",
            device_sequence=-1,
            edge_device_id=_DEVICE,
            payload_digest=payload_digest({}),
            payload={},
        )


@pytest.mark.parametrize("blank_field", ["idempotency_key", "edge_device_id"])
def test_blank_required_identifiers_rejected(blank_field: str) -> None:
    kwargs: dict[str, Any] = {
        "idempotency_key": "k",
        "device_sequence": 0,
        "edge_device_id": _DEVICE,
        "payload_digest": payload_digest({}),
        "payload": {},
    }
    kwargs[blank_field] = ""
    with pytest.raises(ValidationError):
        JournalEntry(**kwargs)


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        JournalEntry(
            idempotency_key="k",
            device_sequence=0,
            edge_device_id=_DEVICE,
            payload_digest=payload_digest({}),
            payload={},
            unexpectedField="reject",  # type: ignore[call-arg]
        )


def test_payload_digest_is_stable_and_content_sensitive() -> None:
    assert payload_digest({"a": 1, "b": 2}) == payload_digest({"b": 2, "a": 1})
    assert payload_digest({"a": 1}) != payload_digest({"a": 2})
    assert payload_digest({}).startswith("sha256:")


def test_payload_digest_handles_non_ascii() -> None:
    """한글 등 비ASCII 본문도 안정적으로 digest된다(ensure_ascii=False 규약)."""
    body = {"description": "굴착기 선회 반경 침입"}
    assert payload_digest(body) == payload_digest(dict(body))
