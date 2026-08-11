#!/usr/bin/env python3
"""보관 정책 주기 실행 진입점 (ADR-KSI-010 §3).

``tools/enforce_retention.py`` 는 사람이 부를 때만 도는 1회성 CLI 다 —
아무도 주기적으로 부르지 않으면 만료 대상이 쌓여도 아무도 모른다. 이
스크립트는 그것을 간격을 두고 반복 호출해 "지금 몇 건이 만료 대상인지"를
구조화 로그로 계속 드러낸다.

## 이 스크립트가 절대 하지 않는 것

**폐기(tombstone+객체 삭제)를 스스로 집행하지 않는다.** 매 주기마다
``plan_expiry``(순수 판정)만 부르고 ``execute_expiry`` 는 이 파일 어디에서도
import 하지 않는다 — 실제 삭제는 여전히 사람이 ``tools/enforce_retention.py
--execute`` 를 직접 실행해야 한다.

ADR-KSI-010 §3: "집행은 명시적 실행이다(자동 스케줄러를 Core 안에 두지
않는다)." ``ksi_core.retention`` 모듈 docstring도 같은 이유를 말한다 —
"잘못된 정책값이 배포되면 스케줄러는 그걸 즉시 집행하지만 수동 실행은 사람이
한 번 본다." 보관 기간 기본값(candidateDays·confirmedEventDays)의 법적
적정성은 아직 대표자 판단 대기 중이다(원장 risk
``retention-defaults-legal-review``) — 이 스크립트가 그 기본값으로 자동
삭제를 시작하면 그 미해결 리스크를 코드가 임의로 해소해버리는 셈이 된다.

그래서 이 스크립트가 여는 것은 **"보이게 하는" 주기**이지 **"지우는" 주기가
아니다**. ``tools/enforce_retention.py`` 의 docstring이 요구하는 전제
("cron 에 걸어야 한다면 dry-run 결과를 사람이 받는 경로를 먼저 만들어라")를
정확히 이 형태로 채운다 — 구조화 로그가 그 알림 경로다(수집기·모니터링이
그 로그를 본다).

Usage:
    uv run python tools/retention_scheduler.py --data-dir /data \\
        --policy contracts/schemas/retention-policy.defaults.json \\
        --interval-seconds 86400
    # 테스트/1회성 확인: --iterations 1 --interval-seconds 0
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType

from ksi_core.durable_journal import DurableJournal
from ksi_core.events import EventStore
from ksi_core.observability import configure_structured_logging
from ksi_core.retention import RetentionPolicy, load_policy, plan_expiry

logger = logging.getLogger("ksi_core.retention_scheduler")

_shutdown_requested = False


def _handle_shutdown(signum: int, frame: FrameType | None) -> None:
    del signum, frame
    global _shutdown_requested  # noqa: PLW0603 -- 시그널 핸들러 관용구
    _shutdown_requested = True


def _scan_once(*, data_dir: Path, policy: RetentionPolicy) -> None:
    """한 주기 — dry-run 판정만 하고 구조화 로그 한 줄을 남긴다.

    매 호출마다 journal 을 **새로 연다** — ``DurableJournal.open_read_only`` 는
    생성 시점 스냅샷만 읽으므로, 인스턴스를 재사용하면 그 사이 새로 들어온
    이벤트가 영원히 안 보인다.
    """
    journal_path = data_dir / "events.jsonl"
    if not journal_path.exists():
        logger.warning("이벤트 원장이 없다(%s) — 이번 주기는 건너뛴다", journal_path)
        return
    journal = DurableJournal.open_read_only(journal_path)
    try:
        store = EventStore(journal)
        now = datetime.now(UTC)
        actions = plan_expiry(store, policy, now=now)
        logger.info(
            "retention scan: %d건 만료 대상 (집행 필드=%s) — 실제 폐기는 "
            "tools/enforce_retention.py --execute 를 사람이 직접 실행해야 한다",
            len(actions),
            ",".join(policy.enforced_fields),
        )
    finally:
        journal.close()


def _sleep_interruptibly(seconds: int) -> None:
    """``_shutdown_requested`` 를 1초 간격으로 살피며 잔다 — SIGTERM 즉시 반응."""
    remaining = seconds
    while remaining > 0 and not _shutdown_requested:
        step = min(1, remaining)
        time.sleep(step)
        remaining -= step


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, help="Core durable 저장소 디렉터리")
    parser.add_argument("--policy", required=True, help="retention-policy.v1 JSON 경로")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=86400,
        help="주기 간격(초, 기본 하루). 0 이면 대기 없이 곧바로 다음 주기.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="N 회 실행 후 종료(기본 무한 루프) — 테스트·1회성 확인용.",
    )
    args = parser.parse_args(argv)

    if args.interval_seconds < 0:
        parser.error("--interval-seconds 는 0 이상이어야 한다")
    if args.iterations is not None and args.iterations <= 0:
        parser.error("--iterations 는 양의 정수여야 한다")

    configure_structured_logging(level="INFO", json_format=True)
    policy = load_policy(Path(args.policy))
    data_dir = Path(args.data_dir)

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    logger.info(
        "retention scheduler 시작 — data_dir=%s interval=%ds", data_dir, args.interval_seconds
    )
    count = 0
    while not _shutdown_requested:
        _scan_once(data_dir=data_dir, policy=policy)
        count += 1
        if args.iterations is not None and count >= args.iterations:
            break
        _sleep_interruptibly(args.interval_seconds)

    logger.info("retention scheduler 종료(%d 회 주기 실행)", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
