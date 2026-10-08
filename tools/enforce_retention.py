#!/usr/bin/env python3
"""보관 정책 집행 진입점 (ADR-KSI-010 §3).

집행 엔진(``ksi_core.retention``)은 있는데 **아무도 부르지 않는 상태**였다 —
정책이 코드로만 존재하고 실행할 방법이 없었다.

**기본은 dry-run 이다.** 데이터를 지우는 도구가 인자 없이 실행됐을 때 지우기
시작하면, 잘못된 정책 파일을 배포한 사고와 조작 실수가 같은 결과를 낸다.
실제 삭제는 ``--execute`` 를 명시해야 한다.

자동 스케줄러로 돌리지 않는다(ADR-KSI-010 §3) — 사람이 dry-run 을 한 번 보고
실행하는 것이 이 도구의 설계다. cron 에 걸어야 한다면 dry-run 결과를 사람이
받는 경로(알림)를 먼저 만들어라.

Usage:
    uv run python tools/enforce_retention.py --data-dir .dev-data/core \\
        --policy contracts/schemas/retention-policy.defaults.json
    uv run python tools/enforce_retention.py ... --execute
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ksi_core.durable_journal import DurableJournal
from ksi_core.retention import ExpiryAction, execute_expiry, load_policy, plan_expiry

# P3 Task 5: ksi_core.events retired to archive/acquisition-2026/ — no import
# attempt here, not even guarded (an import attempt is still a reference to
# the archive). Explicit absence; the events-journal path below fails closed.
EventStore = None


def _s3_storage(*, endpoint_url: str, bucket: str) -> Any:
    """실제 어댑터 — --execute 에서만 만든다(dry-run 은 boto3 를 부르지 않는다)."""
    from ksi_core.evidence_s3 import S3EvidenceStorage  # noqa: PLC0415 -- 지연 import

    return S3EvidenceStorage(bucket=bucket, endpoint_url=endpoint_url)


def _render(actions: list[ExpiryAction]) -> str:
    if not actions:
        return "만료된 증거 없음"
    lines = [f"만료 대상 {len(actions)}건:"]
    lines.extend(
        f"  {a.event_key} / {a.artifact_id}\n    객체: {a.object_key}\n    사유: {a.reason}"
        for a in actions
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, help="Core durable 저장소 디렉터리")
    parser.add_argument("--policy", required=True, help="retention-policy.v1 JSON 경로")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제로 폐기한다(기본은 dry-run — 무엇이 지워질지만 출력)",
    )
    parser.add_argument("--s3-endpoint", default=None, help="--execute 시 필수")
    parser.add_argument("--s3-bucket", default=None, help="--execute 시 필수")
    parser.add_argument("--json", action="store_true", help="결과를 JSON 으로 출력")
    args = parser.parse_args()

    if args.execute and (not args.s3_endpoint or not args.s3_bucket):
        parser.error("--execute 에는 --s3-endpoint 와 --s3-bucket 이 필요하다")

    policy = load_policy(Path(args.policy))
    journal_path = Path(args.data_dir) / "events.jsonl"
    if not journal_path.exists():
        print(f"{journal_path}: 이벤트 원장이 없다", file=sys.stderr)
        return 1
    if EventStore is None:
        # P3 Task 5: events 저널은 관리형(managed)이라 아카이브 경계 너머로
        # 옮겼다 — 플랫폼 프로파일에서는 처리하지 않는다(fail-closed).
        print(
            f"{journal_path}: 이벤트 원장은 관리형 저널이라 "
            "archive/acquisition-2026/ 으로 옮겼다 — 플랫폼 프로파일에서는 "
            "처리하지 않는다",
            file=sys.stderr,
        )
        return 2

    # dry-run 은 **잠금 없이** 읽는다 — 서버가 도는 중에도 확인할 수 있어야 한다.
    # --execute 는 단일 writer 를 잡는다(집행 중 동시 쓰기를 막아야 하므로 Core 정지 필요).
    journal = (
        DurableJournal(journal_path)
        if args.execute
        else DurableJournal.open_read_only(journal_path)
    )
    try:
        store = EventStore(journal)
        now = datetime.now(UTC)
        actions = plan_expiry(store, policy, now=now)

        if not args.execute:
            # 무엇을 집행하는지도 함께 말한다 — 정책 6개 필드 중 둘만 집행하므로,
            # "정책에 있으니 집행되고 있겠지"를 여기서 끊는다.
            payload = {
                "mode": "dry-run",
                "enforcedFields": list(policy.enforced_fields),
                "expiring": [
                    {
                        "eventKey": a.event_key,
                        "artifactId": a.artifact_id,
                        "objectKey": a.object_key,
                        "reason": a.reason,
                    }
                    for a in actions
                ],
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(_render(actions))
            print(
                f"\n[dry-run] 아무것도 지우지 않았다. 집행 필드: "
                f"{', '.join(policy.enforced_fields)}. 실제 폐기는 --execute.",
                file=sys.stderr,
            )
            return 0

        storage = _s3_storage(endpoint_url=args.s3_endpoint, bucket=args.s3_bucket)
        report = execute_expiry(store, storage, actions, now=now)
        result = {
            "mode": "execute",
            "tombstoned": len(report.tombstoned),
            "storageFailures": [
                {"objectKey": a.object_key, "error": err} for a, err in report.storage_failures
            ],
            "skipped": [
                {"artifactId": a.artifact_id, "verdict": verdict} for a, verdict in report.skipped
            ],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        # 삭제 실패가 있으면 0 을 반환하지 않는다 — 원장에는 폐기가 기록됐는데
        # 객체가 남아 있는 상태이므로, 호출자가 재시도할 수 있어야 한다.
        return 0 if not report.storage_failures else 2
    finally:
        journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
