"""DurableJournal 계약 (ADR-KSI-008 §1).

``ksi_core.edge_sync`` 의 ``EdgeSyncStore`` 가 실증한 durable journal 6요소 —
짧은쓰기 루프, fsync(파일+신규생성 시 부모 디렉터리), flock 단일 writer,
torn-tail 격리, 예외 시 봉인, 기동 시 fail-closed 재생 — 가 도메인 비종속
재사용 형태(``DurableJournal``)로도 그대로 성립하는지를 반증한다.
"""

from __future__ import annotations

import gc
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from ksi_core.durable_journal import (
    DurableJournal,
    JournalRecoveryError,
    JournalSealedError,
)


@pytest.fixture
def journal_path(tmp_path: Path) -> Path:
    return tmp_path / "journal.jsonl"


def test_abandoned_writer_releases_its_lock_when_collected(journal_path: Path) -> None:
    """누락된 명시 close가 프로세스 수명 전체의 FD·flock 누수가 되면 안 된다."""

    abandoned = DurableJournal(journal_path)
    abandoned.append({"kind": "created"})
    del abandoned
    gc.collect()

    replacement = DurableJournal(journal_path)
    assert replacement.replay() == [{"kind": "created"}]
    replacement.close()


# ── 정상 append → 재기동 replay ────────────────────────────────────────────


def test_append_then_restart_replay_matches(journal_path: Path) -> None:
    first = DurableJournal(journal_path)
    first.append({"kind": "created", "id": 1})
    first.append({"kind": "updated", "id": 1, "value": "x"})
    assert first.replay() == [
        {"kind": "created", "id": 1},
        {"kind": "updated", "id": 1, "value": "x"},
    ]
    first.close()

    reborn = DurableJournal(journal_path)
    assert reborn.replay() == [
        {"kind": "created", "id": 1},
        {"kind": "updated", "id": 1, "value": "x"},
    ]
    reborn.close()


def test_replay_is_durable_before_return(journal_path: Path) -> None:
    journal = DurableJournal(journal_path)
    journal.append({"a": 1})
    assert journal_path.is_file(), "append 반환 시점에 디스크에 없다 — 유실 경로"
    line = journal_path.read_text(encoding="utf-8").strip()
    assert json.loads(line) == {"a": 1}
    journal.close()


def test_replay_reflects_appends_within_same_instance(journal_path: Path) -> None:
    journal = DurableJournal(journal_path)
    assert journal.replay() == []
    journal.append({"n": 1})
    assert journal.replay() == [{"n": 1}]
    journal.close()


# ── torn tail 격리 ───────────────────────────────────────────────────────


def test_torn_tail_is_truncated_not_fatal(journal_path: Path) -> None:
    first = DurableJournal(journal_path)
    first.append({"n": 0})
    first.close()
    with journal_path.open("ab") as handle:
        handle.write(b'{"n": "torn-partial-wri')  # 개행 없음

    reborn = DurableJournal(journal_path)
    assert reborn.replay() == [{"n": 0}], "완결 레코드가 소실됐다"
    raw = journal_path.read_bytes()
    assert raw.endswith(b"\n") and b"torn-partial" not in raw, "torn tail 이 잘리지 않았다"
    reborn.append({"n": 1})
    reborn.close()
    reread = DurableJournal(journal_path)
    assert reread.replay() == [{"n": 0}, {"n": 1}]
    reread.close()


# ── 오염 줄 fail-closed ─────────────────────────────────────────────────


def test_garbage_line_refuses_startup(journal_path: Path) -> None:
    journal_path.write_text("not json at all\n", encoding="utf-8")
    with pytest.raises(JournalRecoveryError, match="JSON"):
        DurableJournal(journal_path)


def test_recovery_failure_releases_writer_lock_for_retry(journal_path: Path) -> None:
    """__init__ 이 재생 실패로 죽어도 flock·fd 가 인스턴스와 함께 잔존하지 않는다.

    잔존하면 재시작 없이도 다음 시도가 "다른 프로세스가 소유 중"으로 영구히
    막히는데, 실제로는 같은 프로세스 안에서도 같은 경로로 재시도할 수 있어야
    한다(예: 오염 진단 후 파일을 고치고 바로 재구성).
    """
    journal_path.write_text("not json at all\n", encoding="utf-8")
    with pytest.raises(JournalRecoveryError, match="JSON"):
        DurableJournal(journal_path)

    # 잠금이 잔존했다면 아래에서 "단일 writer 위반"으로 실패했을 것이다 —
    # 대신 같은 오염 사유로 다시 거부돼야(잠금이 아니라) fd 해제가 증명된다.
    with pytest.raises(JournalRecoveryError, match="JSON"):
        DurableJournal(journal_path)

    # 오염을 제거하면 정상 기동도 가능해야 한다(잠금 잔존이 아니었음을 재확인).
    journal_path.write_text("", encoding="utf-8")
    journal = DurableJournal(journal_path)
    journal.close()


def test_corrupted_middle_line_refuses_startup(journal_path: Path) -> None:
    first = DurableJournal(journal_path)
    first.append({"n": 0})
    first.close()
    content = journal_path.read_bytes()
    journal_path.write_bytes(b"not json\n" + content)
    with pytest.raises(JournalRecoveryError, match="JSON"):
        DurableJournal(journal_path)


def test_non_dict_json_line_is_contamination(journal_path: Path) -> None:
    """완결 줄이 유효 JSON 이라도 최상위가 배열이면 오염으로 거부한다."""
    journal_path.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(JournalRecoveryError, match="object"):
        DurableJournal(journal_path)


def test_torn_tail_truncate_failure_wrapped_as_recovery_error(
    journal_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """torn tail 격리(truncate) 중 발생한 raw OSError 를 그대로 누출하지 않는다 —
    다른 재생 실패와 동일하게 JournalRecoveryError 로 감싸 fail-closed 를 유지한다."""
    first = DurableJournal(journal_path)
    first.append({"n": 0})
    first.close()
    with journal_path.open("ab") as handle:
        handle.write(b'{"n": "torn-partial-wri')  # 개행 없음

    real_open = Path.open

    def broken_open(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if mode == "r+b":
            raise OSError("simulated truncate-path open failure(주입)")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", broken_open)
    with pytest.raises(JournalRecoveryError, match="torn tail"):
        DurableJournal(journal_path)


# ── _WRITE 예외 주입 → 봉인 + 이후 거부 ─────────────────────────────────


def test_write_failure_seals_and_rejects_subsequent_appends(
    journal_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = DurableJournal(journal_path)

    def broken_write(_fd: int, _data: Any) -> int:
        raise OSError("disk full (주입 실패)")

    from ksi_core import durable_journal as durable_journal_module

    monkeypatch.setattr(durable_journal_module, "_WRITE", broken_write)

    with pytest.raises(JournalSealedError):
        journal.append({"n": 0})
    assert journal.sealed_reason is not None

    with pytest.raises(JournalSealedError):
        journal.append({"n": 1})

    monkeypatch.undo()
    with pytest.raises(JournalSealedError):
        journal.append({"n": 2})  # 봉인은 재시작 없이는 풀리지 않는다


def test_short_write_is_not_silently_accepted(
    journal_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POSIX short write(무예외 부분 기록)가 완결로 둔갑하지 않는다."""
    from ksi_core import durable_journal as durable_journal_module

    journal = DurableJournal(journal_path)
    real_write = durable_journal_module._WRITE
    calls: list[int] = []

    def short_write(fd: int, data: Any) -> int:
        calls.append(len(bytes(data)))
        if len(calls) == 1:
            return real_write(fd, bytes(data)[: len(bytes(data)) // 2])
        return 0  # 이후 진전 없음(ENOSPC 재현)

    monkeypatch.setattr(durable_journal_module, "_WRITE", short_write)
    with pytest.raises(JournalSealedError):
        journal.append({"n": 0})
    assert journal.sealed_reason is not None
    assert len(calls) >= 2, "전량 기록 루프가 재시도하지 않았다"

    monkeypatch.undo()
    journal.close()
    reborn = DurableJournal(journal_path)
    assert reborn.replay() == [], "torn 부분 줄이 완결로 오인됐다"
    reborn.append({"n": 0})
    reborn.close()


# ── 이중 인스턴스 flock 거부 ────────────────────────────────────────────


def test_second_instance_is_refused_while_first_open(journal_path: Path) -> None:
    first = DurableJournal(journal_path)
    with pytest.raises(JournalRecoveryError, match="단일 writer"):
        DurableJournal(journal_path)
    first.close()
    second = DurableJournal(journal_path)  # 정상 종료 후에는 새 writer 가 잡을 수 있다
    second.close()


# ── close 후 거부 ────────────────────────────────────────────────────────


def test_close_is_idempotent_and_seals_future_appends(journal_path: Path) -> None:
    journal = DurableJournal(journal_path)
    journal.append({"n": 0})
    journal.close()
    journal.close()  # 멱등
    assert journal.sealed_reason == "closed"
    with pytest.raises(JournalSealedError):
        journal.append({"n": 1})


# ── allow_nan 거부 ───────────────────────────────────────────────────────


def test_nan_record_is_rejected_and_seals(journal_path: Path) -> None:
    """allow_nan=False — NaN 이 섞인 레코드는 직렬화 단계에서 거부되고 봉인된다."""
    journal = DurableJournal(journal_path)
    with pytest.raises(JournalSealedError):
        journal.append({"value": float("nan")})
    assert journal.sealed_reason is not None
    # 봉인됐으므로 정상 레코드도 이후에는 거부된다.
    with pytest.raises(JournalSealedError):
        journal.append({"value": 1})
    # 디스크에는 아무것도 남지 않았다(직렬화 실패는 write 이전 단계).
    assert not journal_path.exists() or journal_path.read_bytes() == b""


# ── 부모 디렉터리 미존재 처리 ────────────────────────────────────────────


def test_missing_parent_directory_is_created(tmp_path: Path) -> None:
    nested = tmp_path / "does" / "not" / "exist" / "journal.jsonl"
    assert not nested.parent.exists()
    journal = DurableJournal(nested)  # 명시 생성 — edge_sync.py 관습 대칭
    assert nested.parent.is_dir()
    journal.append({"n": 0})
    assert nested.is_file()
    journal.close()


def test_new_journal_file_fsyncs_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced_dirs: list[bool] = []
    real_fsync = os.fsync

    def spy_fsync(fd: int) -> None:
        synced_dirs.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real_fsync(fd)

    from ksi_core import durable_journal as durable_journal_module

    monkeypatch.setattr(durable_journal_module.os, "fsync", spy_fsync)
    journal = DurableJournal(tmp_path / "fresh" / "journal.jsonl")
    journal.append({"n": 0})
    assert True in synced_dirs, "디렉터리 fsync 없음 — 성공 반환 후 크래시에 파일째 소실 가능"

    synced_dirs.clear()
    journal.append({"n": 1})  # 두 번째부터는 파일이 이미 존재 — 디렉터리 fsync 불요
    assert True not in synced_dirs
    journal.close()


# ── 유니코드 개행 후보 ────────────────────────────────────────────────────


def test_unicode_line_separator_payload_survives_restart(journal_path: Path) -> None:
    """ensure_ascii=True — U+2028/2029/0085 가 재적재의 줄 분리를 깨지 않는다."""
    first = DurableJournal(journal_path)
    first.append({"note": "a b cd"})
    first.close()

    reborn = DurableJournal(journal_path)  # 기동 거부되면 여기서 JournalRecoveryError
    assert reborn.replay() == [{"note": "a b cd"}]
    reborn.close()


# ── 방어적 복사(deepcopy) — 감사 원장이 가변 내부 객체로 노출되지 않는다 ────


def test_replay_result_mutation_does_not_corrupt_internal_state(journal_path: Path) -> None:
    """replay() 반환값의 중첩 dict 를 호출자가 변형해도 내부 저장 레코드는 불변이다."""
    journal = DurableJournal(journal_path)
    journal.append({"kind": "x", "nested": {"a": 1}})

    first_view = journal.replay()
    first_view[0]["nested"]["a"] = 999  # 호출자가 반환값의 중첩 dict 를 변형
    first_view.append({"kind": "injected"})  # top-level 리스트도 변형

    second_view = journal.replay()
    assert second_view == [{"kind": "x", "nested": {"a": 1}}], "replay 얕은 복사가 내부를 노출했다"
    journal.close()


def test_append_input_mutation_after_call_does_not_corrupt_journal(journal_path: Path) -> None:
    """append() 호출 후 호출자가 넘겼던 원본 dict 의 중첩 값을 바꿔도 journal 은 불변이다."""
    journal = DurableJournal(journal_path)
    record: dict[str, Any] = {"kind": "x", "nested": {"a": 1}}

    journal.append(record)
    record["nested"]["a"] = 999  # 호출자가 넘겼던 원본을 append 후 변형

    assert journal.replay() == [{"kind": "x", "nested": {"a": 1}}], (
        "append 얕은 복사가 호출자의 원본과 내부 상태를 공유했다"
    )
    journal.close()


# ── 세그먼트 회전 (S4 ops-serving-hardening) ────────────────────────────────
#
# 회전의 계약은 하나다: **재생 결과가 회전 전후로 동일해야 한다.** 순서가 곧
# 원장의 의미이므로(멱등 판정·상태 전이가 순서에 의존한다), 세그먼트를 잘못된
# 순서로 잇거나 하나라도 빠뜨리면 조용히 다른 세계가 재생된다.


def _rotating(path: Path, limit: int = 200) -> DurableJournal:
    return DurableJournal(path, max_segment_bytes=limit)


def test_rotation_preserves_replay_order_across_restart(journal_path: Path) -> None:
    journal = _rotating(journal_path)
    written = [{"seq": i, "payload": "x" * 50} for i in range(20)]
    for record in written:
        journal.append(record)
    assert journal.replay() == written
    journal.close()

    # 회전이 실제로 일어났는가 — 안 일어났으면 이 테스트는 아무것도 증명하지 않는다.
    segments = sorted(journal_path.parent.glob("journal.[0-9]*.jsonl"))
    assert segments, "임계를 훨씬 넘겼는데 세그먼트가 하나도 생기지 않았다"

    reopened = _rotating(journal_path)
    try:
        assert reopened.replay() == written
    finally:
        reopened.close()


def test_rotation_is_off_by_default(journal_path: Path) -> None:
    journal = DurableJournal(journal_path)
    try:
        for i in range(50):
            journal.append({"seq": i, "payload": "y" * 100})
    finally:
        journal.close()
    assert not list(journal_path.parent.glob("journal.[0-9]*.jsonl"))


def test_segment_numbering_continues_after_restart(journal_path: Path) -> None:
    """재기동해도 세그먼트 번호를 1 부터 다시 세지 않는다 — 덮어쓰면 원장이 사라진다."""
    first = _rotating(journal_path)
    for i in range(10):
        first.append({"seq": i, "payload": "z" * 50})
    first.close()
    before = {p.name for p in journal_path.parent.glob("journal.[0-9]*.jsonl")}

    second = _rotating(journal_path)
    try:
        for i in range(10, 20):
            second.append({"seq": i, "payload": "z" * 50})
    finally:
        second.close()
    after = {p.name for p in journal_path.parent.glob("journal.[0-9]*.jsonl")}

    assert before < after, "재기동 후 새 세그먼트가 기존 번호를 덮어썼다"
    reopened = _rotating(journal_path)
    try:
        assert [r["seq"] for r in reopened.replay()] == list(range(20))
    finally:
        reopened.close()


def test_record_larger_than_limit_stays_in_one_segment(journal_path: Path) -> None:
    """한 레코드가 임계보다 커도 쪼개지지 않는다 — 임계는 레코드 경계 뒤에서만 본다."""
    journal = _rotating(journal_path, limit=10)
    big = {"payload": "q" * 500}
    journal.append(big)
    journal.append({"payload": "small"})
    journal.close()

    reopened = _rotating(journal_path, limit=10)
    try:
        assert reopened.replay() == [big, {"payload": "small"}]
    finally:
        reopened.close()


def test_unrelated_sibling_file_is_not_replayed(journal_path: Path) -> None:
    """세그먼트 이름 규칙(숫자)에 맞지 않는 동명 파일은 원장이 아니다."""
    journal = _rotating(journal_path)
    journal.append({"seq": 0})
    journal.close()
    # 사람이 만든 백업 — 숫자 자리가 아니므로 재생 대상이 아니어야 한다.
    (journal_path.parent / "journal.backup.jsonl").write_text(
        json.dumps({"seq": 999}) + "\n", encoding="ascii"
    )

    reopened = _rotating(journal_path)
    try:
        assert [r["seq"] for r in reopened.replay()] == [0]
    finally:
        reopened.close()


def test_torn_tail_in_sealed_segment_refuses_startup(journal_path: Path) -> None:
    """봉인 세그먼트의 부분 줄은 격리가 아니라 거부다 — 발생할 수 없는 상태다.

    활성 파일의 torn tail 은 "기록된 적 없다"로 설명되지만(fsync 전 중단),
    세그먼트는 fsync 완결 후 rename 된 것이라 같은 설명이 성립하지 않는다.
    조용히 잘라내면 설명 못 하는 손실을 정상 기동으로 덮게 된다.
    """
    journal = _rotating(journal_path)
    for i in range(20):
        journal.append({"seq": i, "payload": "w" * 50})
    journal.close()

    segments = sorted(journal_path.parent.glob("journal.[0-9]*.jsonl"))
    assert segments
    with segments[0].open("ab") as handle:
        handle.write(b'{"seq": 99, "partial"')

    with pytest.raises(JournalRecoveryError, match="완결되지 않은 줄"):
        _rotating(journal_path)


def test_rotation_failure_does_not_seal(
    journal_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rename 이 실패해도 수신은 멈추지 않는다 — 기록된 데이터는 이미 durable 하다."""
    journal = _rotating(journal_path, limit=10)
    monkeypatch.setattr(
        "ksi_core.durable_journal.os.rename",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("rename 불가")),
    )
    try:
        journal.append({"seq": 0, "payload": "a" * 50})
        journal.append({"seq": 1, "payload": "b" * 50})
        assert journal.sealed_reason is None
        assert [r["seq"] for r in journal.replay()] == [0, 1]
    finally:
        journal.close()


@pytest.mark.parametrize("bad", [0, -1])
def test_non_positive_segment_limit_is_rejected(journal_path: Path, bad: int) -> None:
    """0/음수는 '회전 없음'이 아니다 — 조용히 해석하면 세그먼트를 무한히 만든다."""
    with pytest.raises(ValueError, match="양수"):
        DurableJournal(journal_path, max_segment_bytes=bad)


# ── 읽기 전용 재생 (보관 정책 dry-run 경로) ─────────────────────────────────
#
# "지우기 전에 무엇을 지울지 보여준다"가 **서버 정지를 요구하면** 아무도 보지
# 않게 된다 — dry-run 이 있으나 마나가 된다. 그래서 잠금 없이 읽는 경로를 둔다.
# 대신 그 인스턴스는 절대 쓰지 못해야 한다(단일 writer 불변식).


def test_read_only_coexists_with_writer(journal_path: Path) -> None:
    writer = DurableJournal(journal_path)
    try:
        writer.append({"seq": 0})
        writer.append({"seq": 1})
        # 쓰기 소유자가 살아 있는 상태에서 열린다 — 여기서 실패하면 dry-run 이
        # Core 를 멈춰야만 가능해진다.
        reader = DurableJournal.open_read_only(journal_path)
        assert [r["seq"] for r in reader.replay()] == [0, 1]
        reader.close()
    finally:
        writer.close()


def test_read_only_refuses_append(journal_path: Path) -> None:
    """잠금을 안 잡으므로 쓰기가 허용되면 단일 writer 가 조용히 깨진다."""
    DurableJournal(journal_path).close()
    reader = DurableJournal.open_read_only(journal_path)
    try:
        with pytest.raises(JournalSealedError):
            reader.append({"seq": 99})
    finally:
        reader.close()


def test_read_only_does_not_truncate_torn_tail(journal_path: Path) -> None:
    """truncate 는 쓰기다 — 읽기 전용은 완결 줄까지만 보고 파일을 건드리지 않는다."""
    writer = DurableJournal(journal_path)
    writer.append({"seq": 0})
    writer.close()
    with journal_path.open("ab") as handle:
        handle.write(b'{"seq": 1, "partial"')
    size_before = journal_path.stat().st_size

    reader = DurableJournal.open_read_only(journal_path)
    try:
        assert [r["seq"] for r in reader.replay()] == [0]
    finally:
        reader.close()
    assert journal_path.stat().st_size == size_before, "읽기 전용이 파일을 잘라냈다"


def test_read_only_sees_rotated_segments(journal_path: Path) -> None:
    writer = _rotating(journal_path)
    for i in range(20):
        writer.append({"seq": i, "payload": "x" * 50})
    writer.close()

    reader = DurableJournal.open_read_only(journal_path)
    try:
        assert [r["seq"] for r in reader.replay()] == list(range(20))
    finally:
        reader.close()


def test_read_only_close_is_idempotent(journal_path: Path) -> None:
    """잡은 잠금이 없으므로 close 가 남의 잠금을 풀어서는 안 된다."""
    writer = DurableJournal(journal_path)
    try:
        writer.append({"seq": 0})
        reader = DurableJournal.open_read_only(journal_path)
        reader.close()
        reader.close()
        # 쓰기 소유자는 여전히 살아 있어야 한다.
        writer.append({"seq": 1})
        assert [r["seq"] for r in writer.replay()] == [0, 1]
    finally:
        writer.close()
