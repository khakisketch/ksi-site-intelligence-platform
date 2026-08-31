"""촬영 디렉터리 감시 → ingest 트리거 (ADR-KSI-019 G4).

이 파일이 검증하는 것은 업로드 자체가 아니다(그건 ``test_upload_source_bundle.py``
소관) — **언제 트리거되고, 두 번 트리거되지 않고, 하나가 실패해도 나머지가
계속되는가**다.

ADR-KSI-019 §4 의 G4 서술("사람이 사진을 손으로 올린다")은 2026-08-15 실측으로
좁혀졌다: ``tools/upload_source_bundle.py`` 가 이미 브라우저 없이 등록·업로드·봉인·
재구성 발행을 한다. 남아 있던 구멍은 **그 명령을 임무마다 치는 주체**였고, 이
도구가 그 주체를 사람에서 프로그램으로 옮긴다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import cast

import httpx
import pytest

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(_TOOLS) not in sys.path:
    # tools/ 는 패키지가 아니라 스크립트 디렉터리다 — upload_source_bundle 이
    # 형제 모듈(_digest)을 이렇게 부르는 관습을 그대로 따른다.
    sys.path.insert(0, str(_TOOLS))

from ingest_watch import (  # noqa: E402 -- sys.path 조작 이후에만 import 가능
    SkippedCapture,
    WatchReport,
    discover_pending,
    load_done,
    run_once,
    store_done,
)
from upload_source_bundle import SyncOutcome  # noqa: E402


def _make_capture(root: Path, mission_id: str, *, count: int = 2) -> Path:
    directory = root / mission_id
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (directory / f"DJI_{index:04d}.JPG").write_bytes(b"fake-jpeg-bytes")
    return directory


class _FakeUploader:
    """호출 기록을 남기는 업로더 대역 — 항상 성공."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, mission_id: str, directory: Path) -> SyncOutcome:
        del directory
        self.calls.append(mission_id)
        outcome = SyncOutcome()
        outcome.discovered = 2
        outcome.uploaded = 2
        outcome.sealed = True
        outcome.processing_job_id = f"{mission_id}-pj1"
        return outcome

    @property
    def call_count(self) -> int:
        return len(self.calls)


class _FailingUploader(_FakeUploader):
    """``m-bad`` 만 실패하는 대역."""

    def __call__(self, mission_id: str, directory: Path) -> SyncOutcome:
        outcome = super().__call__(mission_id, directory)
        if mission_id == "m-bad":
            outcome.failures.append("업로드 실패(테스트)")
            outcome.sealed = False
        return outcome


class _FlakyUploader(_FakeUploader):
    """첫 호출만 실패하고 그 다음부터 성공 — 재시도 경로 확인용."""

    def __call__(self, mission_id: str, directory: Path) -> SyncOutcome:
        outcome = super().__call__(mission_id, directory)
        if self.call_count == 1:
            outcome.failures.append("일시 실패(테스트)")
            outcome.sealed = False
        return outcome


class _RaisingUploader(_FakeUploader):
    """예외를 던지는 대역 — 임무 하나의 사고가 스캔을 멈추지 않는지 본다."""

    def __call__(self, mission_id: str, directory: Path) -> SyncOutcome:
        super().__call__(mission_id, directory)
        if mission_id == "m-boom":
            raise RuntimeError("네트워크 끊김(테스트)")
        outcome = SyncOutcome()
        outcome.sealed = True
        return outcome


# ── 발견 ──────────────────────────────────────────────────────────────


def test_discovers_mission_directories_by_name(tmp_path: Path) -> None:
    """디렉터리 이름이 곧 임무 id 다 — 사람이 명령마다 id 를 타이핑하지 않는다."""
    _make_capture(tmp_path, "m-alpha")
    _make_capture(tmp_path, "m-beta")
    (tmp_path / "not-a-mission.txt").write_text("x", encoding="utf-8")

    pending = discover_pending(tmp_path)

    assert {p.mission_id for p in pending} == {"m-alpha", "m-beta"}


def test_ignores_directories_without_images(tmp_path: Path) -> None:
    """빈 디렉터리를 임무로 착각해 빈 번들을 봉인하지 않는다."""
    (tmp_path / "m-empty").mkdir()
    (tmp_path / "m-docs").mkdir()
    (tmp_path / "m-docs" / "readme.txt").write_text("x", encoding="utf-8")
    _make_capture(tmp_path, "m-real")

    assert [p.mission_id for p in discover_pending(tmp_path)] == ["m-real"]


def test_finds_images_in_nested_directories(tmp_path: Path) -> None:
    """SD카드 구조(DCIM/100MEDIA/...)를 그대로 옮겨도 발견된다."""
    nested = tmp_path / "m-alpha" / "DCIM" / "100MEDIA"
    nested.mkdir(parents=True)
    (nested / "DJI_0001.JPG").write_bytes(b"x")

    assert [p.mission_id for p in discover_pending(tmp_path)] == ["m-alpha"]


def test_ignores_directory_still_being_written(tmp_path: Path) -> None:
    """[핵심] 복사가 진행 중인 디렉터리를 건드리지 않는다.

    SD카드 오프로드 중에 봉인하면 절반만 든 번들이 원본으로 굳고, **봉인은
    되돌릴 수 없다**. 마지막 수정 시각이 정지 유예를 넘긴 디렉터리만 대상이다.
    """
    directory = _make_capture(tmp_path, "m-alpha")
    written_at = max(p.stat().st_mtime for p in directory.rglob("*.JPG"))

    assert discover_pending(tmp_path, quiet_seconds=60, now=written_at + 5) == []
    assert len(discover_pending(tmp_path, quiet_seconds=60, now=written_at + 300)) == 1


def test_missing_root_is_not_an_error(tmp_path: Path) -> None:
    """아직 만들어지지 않은 회수 경로에서도 죽지 않는다(주기 실행 첫날)."""
    assert discover_pending(tmp_path / "nope") == []


def test_explicit_mission_uses_root_itself_without_renaming(tmp_path: Path) -> None:
    """현장에서 내려받은 폴더를 mission id 이름으로 다시 감싸지 않아도 된다."""
    source = tmp_path / "drone pictures"
    nested = source / "DCIM" / "100MEDIA"
    nested.mkdir(parents=True)
    (nested / "DJI_0001.JPG").write_bytes(b"fake-jpeg-bytes")
    uploader = _FakeUploader()

    report = run_once(
        source,
        uploader=uploader,
        state_dir=tmp_path / "state",
        mission_id="m-field-1",
    )

    assert report.succeeded == ["m-field-1"]
    assert uploader.calls == ["m-field-1"]


def test_explicit_mission_reports_missing_directory(tmp_path: Path) -> None:
    report = run_once(
        tmp_path / "not-connected",
        uploader=_FakeUploader(),
        mission_id="m-field-1",
    )

    assert report.succeeded == []
    assert report.skipped == [SkippedCapture(mission_id="m-field-1", reason="MISSING_DIRECTORY")]


def test_explicit_mission_reports_empty_folder(tmp_path: Path) -> None:
    source = tmp_path / "empty"
    source.mkdir()

    report = run_once(source, uploader=_FakeUploader(), mission_id="m-field-1")

    assert report.skipped == [SkippedCapture(mission_id="m-field-1", reason="NO_IMAGES")]


def test_explicit_mission_keeps_quiet_period_guard(tmp_path: Path) -> None:
    source = tmp_path / "copying"
    source.mkdir()
    image = source / "DJI_0001.JPG"
    image.write_bytes(b"fake-jpeg-bytes")
    written_at = image.stat().st_mtime

    report = run_once(
        source,
        uploader=_FakeUploader(),
        mission_id="m-field-1",
        quiet_seconds=60,
        now=written_at + 5,
    )

    assert report.skipped == [SkippedCapture(mission_id="m-field-1", reason="STILL_WRITING")]


def test_explicit_mission_is_not_reingested_after_success(tmp_path: Path) -> None:
    source = tmp_path / "drone pictures"
    source.mkdir()
    (source / "DJI_0001.JPG").write_bytes(b"fake-jpeg-bytes")
    uploader = _FakeUploader()
    state_dir = tmp_path / "state"

    first = run_once(
        source,
        uploader=uploader,
        state_dir=state_dir,
        mission_id="m-field-1",
    )
    second = run_once(
        source,
        uploader=uploader,
        state_dir=state_dir,
        mission_id="m-field-1",
    )

    assert first.succeeded == ["m-field-1"]
    assert second.succeeded == []
    assert second.skipped == [SkippedCapture(mission_id="m-field-1", reason="ALREADY_INGESTED")]
    assert uploader.calls == ["m-field-1"]


# ── 트리거 ────────────────────────────────────────────────────────────


def test_triggers_the_uploader_once_per_mission(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    _make_capture(root, "m-alpha")
    _make_capture(root, "m-beta")
    uploader = _FakeUploader()

    report = run_once(root, uploader=uploader, state_dir=tmp_path / "state")

    assert sorted(report.succeeded) == ["m-alpha", "m-beta"]
    assert sorted(uploader.calls) == ["m-alpha", "m-beta"]


def test_marks_done_and_does_not_retrigger(tmp_path: Path) -> None:
    """성공한 임무를 다시 올리지 않는다 — 서버 멱등성에 매번 기대지 않는다."""
    root = tmp_path / "captures"
    _make_capture(root, "m-alpha")
    uploader = _FakeUploader()

    first = run_once(root, uploader=uploader, state_dir=tmp_path / "state")
    second = run_once(root, uploader=uploader, state_dir=tmp_path / "state")

    assert first.succeeded == ["m-alpha"]
    assert second.succeeded == []
    assert uploader.call_count == 1
    assert [s.reason for s in second.skipped] == ["ALREADY_INGESTED"]


def test_losing_the_state_file_only_costs_a_rescan(tmp_path: Path) -> None:
    """완료 표시는 정합성 장치가 아니라 속도 장치다 — 잃어도 결과는 같다."""
    root = tmp_path / "captures"
    state_dir = tmp_path / "state"
    _make_capture(root, "m-alpha")
    uploader = _FakeUploader()
    run_once(root, uploader=uploader, state_dir=state_dir)
    (state_dir / "ingested-missions.json").unlink()

    report = run_once(root, uploader=uploader, state_dir=state_dir)

    assert report.succeeded == ["m-alpha"]
    assert uploader.call_count == 2


def test_corrupt_state_file_is_treated_as_empty(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "ingested-missions.json").write_text("{not json", encoding="utf-8")

    assert load_done(state_dir) == set()


def test_store_done_is_atomic_and_roundtrips(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    store_done(state_dir, {"m-b", "m-a"})

    assert json.loads((state_dir / "ingested-missions.json").read_text(encoding="utf-8")) == [
        "m-a",
        "m-b",
    ]
    assert load_done(state_dir) == {"m-a", "m-b"}
    assert not list(state_dir.glob("*.tmp")), "부분 기록 임시 파일이 남았다"


def test_no_state_dir_means_no_memory(tmp_path: Path) -> None:
    """``--state-dir`` 없이도 동작한다 — 매번 전량 확인할 뿐이다."""
    root = tmp_path / "captures"
    _make_capture(root, "m-alpha")
    uploader = _FakeUploader()

    run_once(root, uploader=uploader, state_dir=None)
    run_once(root, uploader=uploader, state_dir=None)

    assert uploader.call_count == 2


# ── 실패 격리 ─────────────────────────────────────────────────────────


def test_one_failure_does_not_stop_the_others(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    _make_capture(root, "m-bad")
    _make_capture(root, "m-good")

    report = run_once(root, uploader=_FailingUploader(), state_dir=tmp_path / "state")

    assert report.succeeded == ["m-good"]
    assert [f.mission_id for f in report.failed] == ["m-bad"]
    assert report.ok is False


def test_an_exception_is_isolated_too(tmp_path: Path) -> None:
    """[핵심] 임무 하나의 예외가 그날의 회수를 통째로 멈추지 않는다."""
    root = tmp_path / "captures"
    _make_capture(root, "m-boom")
    _make_capture(root, "m-ok")

    report = run_once(root, uploader=_RaisingUploader(), state_dir=tmp_path / "state")

    assert report.succeeded == ["m-ok"]
    assert [f.mission_id for f in report.failed] == ["m-boom"]
    assert "RuntimeError" in report.failed[0].detail


def test_failed_mission_is_retried_next_run(tmp_path: Path) -> None:
    """[핵심] 실패는 완료로 기록하지 않는다 — 기록하면 재시도 경로가 사라진다."""
    root = tmp_path / "captures"
    _make_capture(root, "m-alpha")
    uploader = _FlakyUploader()

    first = run_once(root, uploader=uploader, state_dir=tmp_path / "state")
    second = run_once(root, uploader=uploader, state_dir=tmp_path / "state")

    assert first.succeeded == []
    assert second.succeeded == ["m-alpha"]


# ── 보고 ──────────────────────────────────────────────────────────────


def test_report_lists_skipped_reasons(tmp_path: Path) -> None:
    """[핵심] 건너뛴 것을 조용히 지우지 않는다 — 무엇을 왜 안 했는지 보고한다."""
    root = tmp_path / "captures"
    (root / "m-empty").mkdir(parents=True)
    _make_capture(root, "m-alpha")

    report = run_once(root, uploader=_FakeUploader(), state_dir=tmp_path / "state")

    assert report.succeeded == ["m-alpha"]
    assert SkippedCapture(mission_id="m-empty", reason="NO_IMAGES") in report.skipped


def test_still_writing_directory_is_reported_not_dropped(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    directory = _make_capture(root, "m-copying")
    written_at = max(p.stat().st_mtime for p in directory.rglob("*.JPG"))

    report = run_once(
        root,
        uploader=_FakeUploader(),
        state_dir=tmp_path / "state",
        quiet_seconds=60,
        now=written_at + 5,
    )

    assert report.succeeded == []
    assert [s.reason for s in report.skipped] == ["STILL_WRITING"]


def test_empty_report_is_ok(tmp_path: Path) -> None:
    """회수할 게 없는 날은 실패가 아니다 — 주기 실행이 매번 오류로 뜨면 안 된다."""
    report = run_once(tmp_path / "captures", uploader=_FakeUploader(), state_dir=None)

    assert report == WatchReport()
    assert report.ok is True


# ── CLI 표면 ──────────────────────────────────────────────────────────


def test_cli_help_does_not_crash() -> None:
    """테스트는 통과하는데 CLI 는 import 에서 죽는 경우를 잡는다."""
    import subprocess

    result = subprocess.run(  # noqa: S603 -- 저장소 자체 스크립트 실행
        [sys.executable, str(_TOOLS / "ingest_watch.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(_TOOLS)},
    )

    assert result.returncode == 0, result.stderr
    assert "--quiet-seconds" in result.stdout


def test_uploader_adapter_always_seals_and_issues(tmp_path: Path) -> None:
    """[핵심] 어댑터가 봉인·재구성 발행을 끄지 않는다.

    이 도구의 계약은 "디렉터리가 채워지면 그 뒤는 사람 손 없이 서버까지 간다"이다.
    봉인만 하고 멈추면 그 계약이 반만 지켜지고, 사람이 다시 버튼을 눌러야 한다.
    """
    import ingest_watch

    captured: dict[str, object] = {}

    def _fake_run_sync(_client: httpx.Client, **kwargs: object) -> SyncOutcome:
        captured.update(kwargs)
        return SyncOutcome()

    original = ingest_watch.run_sync
    # run_sync 는 키워드 전용 인자를 갖지만 이 대역은 **kwargs 로 받는다 —
    # mypy 가 시그니처 불일치로 보므로 setattr 로 대체한다(monkeypatch 관용구).
    ingest_watch.run_sync = _fake_run_sync  # type: ignore[assignment]
    try:
        uploader = ingest_watch.build_uploader(
            cast("httpx.Client", None),  # 대역이 client 를 쓰지 않는다
            state_dir=tmp_path / "state",
            timeout=30.0,
            batch_size=50,
        )
        uploader("m-alpha", tmp_path / "captures" / "m-alpha")
    finally:
        ingest_watch.run_sync = original

    assert captured["seal"] is True
    assert captured["start_reconstruction"] is True
    assert captured["mission_id"] == "m-alpha"


def test_upload_cache_is_partitioned_per_mission(tmp_path: Path) -> None:
    """임무별로 확인 캐시를 나눈다 — 한 파일에 섞으면 같은 파일명이 서로를 덮는다."""
    import ingest_watch

    captured: dict[str, object] = {}

    def _fake_run_sync(_client: httpx.Client, **kwargs: object) -> SyncOutcome:
        captured.update(kwargs)
        return SyncOutcome()

    original = ingest_watch.run_sync
    # run_sync 는 키워드 전용 인자를 갖지만 이 대역은 **kwargs 로 받는다 —
    # mypy 가 시그니처 불일치로 보므로 setattr 로 대체한다(monkeypatch 관용구).
    ingest_watch.run_sync = _fake_run_sync  # type: ignore[assignment]
    try:
        uploader = ingest_watch.build_uploader(
            cast("httpx.Client", None),
            state_dir=tmp_path / "state",
            timeout=30.0,
            batch_size=50,
        )
        uploader("m-alpha", tmp_path / "captures" / "m-alpha")
    finally:
        ingest_watch.run_sync = original

    assert captured["state_dir"] == tmp_path / "state" / "uploads" / "m-alpha"


@pytest.mark.parametrize("suffix", [".JPG", ".jpg", ".jpeg", ".PNG", ".webp"])
def test_image_suffixes_are_case_insensitive(tmp_path: Path, suffix: str) -> None:
    directory = tmp_path / "m-alpha"
    directory.mkdir()
    (directory / f"DJI_0001{suffix}").write_bytes(b"x")

    assert [p.mission_id for p in discover_pending(tmp_path)] == ["m-alpha"]


@pytest.mark.parametrize("suffix", [".DNG", ".dng", ".mp4"])
def test_watcher_does_not_claim_media_the_uploader_cannot_register(
    tmp_path: Path, suffix: str
) -> None:
    directory = tmp_path / "m-alpha"
    directory.mkdir()
    (directory / f"DJI_0001{suffix}").write_bytes(b"x")

    assert discover_pending(tmp_path) == []
