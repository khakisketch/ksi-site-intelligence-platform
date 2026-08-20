#!/usr/bin/env python3
"""촬영 디렉터리를 훑어 임무별 ingest 를 한 번씩 트리거한다 (ADR-KSI-019 G4).

## 이 도구가 닫는 구멍 — 그리고 닫지 않는 것

``upload_source_bundle.py`` 가 이미 "디렉터리 하나를 서버까지 보내는" 일을 사람 손
없이 한다(등록 → 업로드 → 봉인 → 재구성 발행, ADR-KSI-018 P1). 남은 사람 손은
**그 명령을 임무마다 치는 것**이다. 이 도구가 그 한 겹을 걷어낸다 — 업로드 로직은
한 줄도 다시 쓰지 않고 :func:`~upload_source_bundle.run_sync` 를 그대로 부른다.

닫지 않는 것은 그 앞이다: 기체에서 지상으로 사진을 내리는 경로. ADR-KSI-013 D1/D2
가 확정한 대로 실기 검증 전까지 SD카드 회수·수동 오프로드가 정상 경로이며, 이
도구의 입력은 그 절차가 채운 디렉터리다.

## 기본 무인 모드에서는 임무 id 가 디렉터리 이름이다

주기 실행의 기본 규약은 ``<root>/<missionId>/`` 다. 단일 폴더 반입은 명시적
``--mission-id`` 를 사용한다. 어느 모드에서도 파일 EXIF 에서 임무를 추론하지 않는다 —
추론이 틀리면 다른 임무의 원본이 섞이고, 그건 계보(``jobId = f(missionId, seq)``)가
조용히 거짓이 되는 사고다. ID가 틀리면 서버가 ``UNKNOWN_MISSION``으로 거부하고,
이 도구는 그 실패를 보고에 남긴다.

## 복사 중인 디렉터리를 건드리지 않는다

디렉터리 안 최신 수정 시각이 ``--quiet-seconds`` 를 넘겨야 대상이 된다. 오프로드
중에 봉인하면 절반만 든 번들이 원본으로 굳고, **봉인은 되돌릴 수 없다**.

## 완료 표시는 속도 장치이지 정합성 장치가 아니다

``--state-dir`` 에 성공한 임무 id 를 남겨 다시 훑지 않는다. 이 파일을 잃어도 결과는
같다(서버가 멱등하다) — 다시 전량 확인할 뿐이다. **실패는 기록하지 않는다**:
실패를 완료로 남기면 재시도 경로가 사라진다.

## 하나가 실패해도 나머지를 계속한다

임무 하나의 실패가 그날의 전체 회수를 멈추면, 사고 하나가 다른 현장의 데이터까지
지연시킨다. 실패는 모아서 보고하고 종료 코드로만 알린다.

## 한 번 실행이 기본이다

기본 동작은 1회 스캔 후 종료다. systemd timer·cron 이 주기를 소유하는 편이 이
프로세스가 데몬으로 사는 것보다 운영에서 관측 가능하다(노후 스윕 표면과 같은
원칙, ``ksi_core.spatial_model``). ``--interval-seconds`` 를 주면 그 간격으로
반복하지만, 그건 개발 편의용이지 권장 배치가 아니다.

Usage::

    uv run python tools/ingest_watch.py \\
        --core-url http://127.0.0.1:8010 \\
        --token dev-admin-token \\
        --root /var/spool/ksi/captures \\
        --state-dir /var/lib/ksi/ingest-state \\
        --quiet-seconds 120

이미 한 임무의 사진이 한 폴더에 모여 있다면 폴더명을 임무 ID로 바꾸거나 한 단계
더 감쌀 필요가 없다. ``--mission-id`` 로 그 폴더 자체를 명시한다::

    uv run python tools/ingest_watch.py \\
        --core-url http://127.0.0.1:8010 \\
        --token dev-admin-token \\
        --root "/path/to/drone pictures" \\
        --mission-id mission-123 \\
        --state-dir /var/lib/ksi/ingest-state \\
        --quiet-seconds 120

이 모드에서도 하위 ``DCIM/100MEDIA`` 구조를 재귀적으로 찾으며 원본 파일을
이동·수정·삭제하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from upload_source_bundle import SyncOutcome, run_sync

#: 사진으로 셀 확장자 — ``upload_source_bundle`` 이 실제로 업로드하는 집합과 같아야
#: 한다. 여기가 더 넓으면 "사진이 있다"고 판단해 놓고 업로더가 0장을 올리는 어긋난
#: 상태가 생긴다.
_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".dng"})

#: 완료 표시 파일 이름 — ``--state-dir`` 안에 둔다.
_DONE_FILE = "ingested-missions.json"


@dataclass(frozen=True, slots=True)
class PendingCapture:
    """트리거 대상 1건 — 임무 id 와 그 사진이 든 디렉터리."""

    mission_id: str
    directory: Path


@dataclass(frozen=True, slots=True)
class SkippedCapture:
    """건너뛴 디렉터리와 그 사유 — 조용히 지우지 않는다."""

    mission_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class FailedCapture:
    mission_id: str
    detail: str


@dataclass
class WatchReport:
    """스캔 1회의 결과 — 성공·실패·건너뜀을 전부 들고 다닌다."""

    succeeded: list[str] = field(default_factory=list)
    failed: list[FailedCapture] = field(default_factory=list)
    skipped: list[SkippedCapture] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def _image_files(directory: Path) -> list[Path]:
    """그 디렉터리(하위 포함)의 사진 파일 — 이름 순."""
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
    )


def _latest_mtime(paths: Iterable[Path]) -> float:
    return max((path.stat().st_mtime for path in paths), default=0.0)


def discover_pending(
    root: Path, *, quiet_seconds: float = 0.0, now: float | None = None
) -> list[PendingCapture]:
    """``<root>/<missionId>/`` 중 사진이 있고 정지 유예를 넘긴 디렉터리.

    Args:
        root: 임무별 디렉터리를 담은 상위 경로.
        quiet_seconds: 마지막 수정 이후 이만큼 조용해야 대상으로 삼는다. 0 이면
            유예 없음(테스트·즉시 처리용).
        now: 판정 시각(epoch 초). ``None`` 이면 현재 시각.
    """
    if not root.is_dir():
        return []
    reference = time.time() if now is None else now
    pending: list[PendingCapture] = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        images = _image_files(directory)
        if not images:
            continue
        if reference - _latest_mtime(images) < quiet_seconds:
            continue
        pending.append(PendingCapture(mission_id=directory.name, directory=directory))
    return pending


def _skipped_reasons(
    root: Path, *, pending: list[PendingCapture], quiet_seconds: float, now: float | None
) -> list[SkippedCapture]:
    """대상이 되지 못한 디렉터리와 그 사유 — 보고에만 쓴다."""
    if not root.is_dir():
        return []
    reference = time.time() if now is None else now
    chosen = {capture.mission_id for capture in pending}
    skipped: list[SkippedCapture] = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        if directory.name in chosen:
            continue
        images = _image_files(directory)
        reason = (
            "NO_IMAGES"
            if not images
            else ("STILL_WRITING" if reference - _latest_mtime(images) < quiet_seconds else "")
        )
        if reason:
            skipped.append(SkippedCapture(mission_id=directory.name, reason=reason))
    return skipped


def _discover_explicit_capture(
    directory: Path,
    *,
    mission_id: str,
    quiet_seconds: float,
    now: float | None,
) -> tuple[list[PendingCapture], list[SkippedCapture]]:
    """사용자가 명시한 한 폴더를 한 임무의 촬영 원본으로 판정한다.

    ``discover_pending`` 의 ``<root>/<missionId>`` 규약은 무인 주기 실행에 적합하지만,
    현장에서 이미 내려받은 폴더 하나를 올릴 때는 불필요한 이름 변경과 디렉터리
    생성을 강요한다. 이 경로는 추론 대신 사용자가 준 mission id 를 쓰므로 계보를
    약화하지 않으면서 그 마찰만 없앤다.
    """
    if not directory.is_dir():
        return [], [SkippedCapture(mission_id=mission_id, reason="MISSING_DIRECTORY")]
    images = _image_files(directory)
    if not images:
        return [], [SkippedCapture(mission_id=mission_id, reason="NO_IMAGES")]
    reference = time.time() if now is None else now
    if reference - _latest_mtime(images) < quiet_seconds:
        return [], [SkippedCapture(mission_id=mission_id, reason="STILL_WRITING")]
    return [PendingCapture(mission_id=mission_id, directory=directory)], []


def load_done(state_dir: Path | None) -> set[str]:
    """이미 성공한 임무 id 집합 — 없거나 깨졌으면 빈 집합(전량 재확인)."""
    if state_dir is None:
        return set()
    path = state_dir / _DONE_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 정합성 장치가 아니라 속도 장치다 — 잃으면 전량 재확인하고 결과는 같다.
        return set()
    return set(raw) if isinstance(raw, list) else set()


def store_done(state_dir: Path | None, done: set[str]) -> None:
    """완료 표시를 원자적으로 쓴다 — 부분 기록된 파일이 남지 않게."""
    if state_dir is None:
        return
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / _DONE_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(done), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


#: 업로더 어댑터 — (mission_id, directory) 를 받아 ``SyncOutcome`` 을 낸다.
#: 테스트가 실제 HTTP 없이 이 지점을 대체한다.
Uploader = Callable[[str, Path], SyncOutcome]


def run_once(
    root: Path,
    *,
    uploader: Uploader,
    state_dir: Path | None = None,
    quiet_seconds: float = 0.0,
    now: float | None = None,
    mission_id: str | None = None,
) -> WatchReport:
    """대상 임무를 하나씩 처리한다 — 하나가 실패해도 나머지를 계속한다.

    ``mission_id`` 가 있으면 ``root`` 자체를 그 임무의 촬영 폴더로 사용한다. 없으면
    기존의 ``<root>/<missionId>`` 다중 임무 규약을 그대로 사용한다.
    """
    report = WatchReport()
    if mission_id is None:
        pending = discover_pending(root, quiet_seconds=quiet_seconds, now=now)
        report.skipped.extend(
            _skipped_reasons(root, pending=pending, quiet_seconds=quiet_seconds, now=now)
        )
    else:
        pending, skipped = _discover_explicit_capture(
            root,
            mission_id=mission_id,
            quiet_seconds=quiet_seconds,
            now=now,
        )
        report.skipped.extend(skipped)

    done = load_done(state_dir)
    changed = False
    for capture in pending:
        if capture.mission_id in done:
            report.skipped.append(
                SkippedCapture(mission_id=capture.mission_id, reason="ALREADY_INGESTED")
            )
            continue
        try:
            outcome = uploader(capture.mission_id, capture.directory)
        except Exception as exc:  # noqa: BLE001 -- 임무 하나의 실패가 스캔을 멈추지 않는다
            report.failed.append(
                FailedCapture(mission_id=capture.mission_id, detail=f"{type(exc).__name__}: {exc}")
            )
            continue
        if outcome.ok:
            report.succeeded.append(capture.mission_id)
            done.add(capture.mission_id)
            changed = True
        else:
            # 실패는 완료로 기록하지 않는다 — 기록하면 재시도 경로가 사라진다.
            report.failed.append(
                FailedCapture(mission_id=capture.mission_id, detail="; ".join(outcome.failures))
            )
    if changed:
        store_done(state_dir, done)
    return report


def build_uploader(
    client: httpx.Client, *, state_dir: Path | None, timeout: float, batch_size: int
) -> Uploader:
    """``run_sync`` 를 (mission_id, directory) 시그니처로 감싼다.

    봉인·재구성 발행을 **항상 켠다** — 이 도구의 계약은 "디렉터리가 채워지면 그
    뒤는 사람 손 없이 서버까지 간다"이고, 봉인만 하고 멈추면 그 계약이 반만
    지켜진다. ``run_sync`` 자체가 fail-closed 순서(업로드 실패 시 봉인 안 함)를
    이미 지킨다.
    """

    def _upload(mission_id: str, directory: Path) -> SyncOutcome:
        return run_sync(
            client,
            mission_id=mission_id,
            source_dir=directory,
            batch_size=batch_size,
            timeout=timeout,
            # 업로드 확인 캐시는 임무별로 나눈다 — 한 파일에 섞으면 서로 다른
            # 임무의 같은 파일명이 상대의 캐시를 덮는다.
            state_dir=(state_dir / "uploads" / mission_id) if state_dir else None,
            seal=True,
            start_reconstruction=True,
        )

    return _upload


def _print_report(report: WatchReport) -> None:
    for mission_id in report.succeeded:
        print(f"OK   {mission_id}")
    for skipped in report.skipped:
        print(f"SKIP {skipped.mission_id}: {skipped.reason}")
    for failed in report.failed:
        print(f"FAIL {failed.mission_id}: {failed.detail}", file=sys.stderr)
    print(
        f"— 성공 {len(report.succeeded)} · 실패 {len(report.failed)} · 건너뜀 {len(report.skipped)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--core-url", default="http://127.0.0.1:8000", help="Core API 베이스 URL")
    parser.add_argument("--token", default=os.environ.get("KSI_CORE_TOKEN", ""), help="Bearer 토큰")
    parser.add_argument(
        "--root", required=True, help="임무별 디렉터리(<root>/<missionId>/)를 담은 상위 경로"
    )
    parser.add_argument(
        "--mission-id",
        default=None,
        help=(
            "지정하면 --root 자체를 이 임무의 사진 폴더로 사용"
            "(폴더명 변경 없이 단일 임무를 가져올 때)"
        ),
    )
    parser.add_argument(
        "--state-dir", default=None, help="완료 표시·업로드 확인 캐시를 둘 경로(선택)"
    )
    parser.add_argument(
        "--quiet-seconds",
        type=float,
        default=120.0,
        help="마지막 수정 이후 이만큼 조용해야 대상으로 삼는다(복사 중 봉인 방지)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=0.0,
        help="0(기본)이면 1회 스캔 후 종료. 양수면 그 간격으로 반복(개발 편의용)",
    )
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    root = Path(args.root)
    state_dir = Path(args.state_dir) if args.state_dir else None
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}

    with httpx.Client(base_url=args.core_url, headers=headers, timeout=args.timeout) as client:
        uploader = build_uploader(
            client, state_dir=state_dir, timeout=args.timeout, batch_size=args.batch_size
        )
        while True:
            report = run_once(
                root,
                uploader=uploader,
                state_dir=state_dir,
                quiet_seconds=args.quiet_seconds,
                mission_id=args.mission_id,
            )
            _print_report(report)
            if args.interval_seconds <= 0:
                return 0 if report.ok else 1
            time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
