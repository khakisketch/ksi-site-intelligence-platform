"""Frame–Telemetry 시간차 실측 도구 (HARDWARE_SESSION_PLAYBOOK.md 7단계).

MASTER_PRD §21.1 "Sensor Timestamp alignment: p95 50ms 이하 목표"의 실측 도구다.
이 실측은 `docs/product/DOMAIN_INVARIANTS.md` INV-025의 전제조건이기도 하다 —
``WorldEntity.uncertainty.localization_state = CONFIRMED``는 ``CALIBRATED_POSE``
시점 증거를 요구하는데, 그 시점 증거의 정확도는 결국 Frame과 Telemetry가 실제로
얼마나 시간적으로 정렬돼 있는지에 달려 있다. 여기서 나온 p50/p95/max 없이는
"시간동기가 맞다"는 주장 자체가 근거가 없다(`docs/hil/CAPABILITY_ACCEPTANCE.md` 참고).

## 이 파일에서 완전히 구현된 것 / 아닌 것

- **완전 구현 + 순수 함수(단위테스트 가능)**: :func:`percentile`, :func:`summarize_deltas`,
  :func:`compute_delta_ms`, JSONL 직렬화/역직렬화, ``summarize`` CLI 서브커맨드.
  이미 수집된 JSONL 파일이 있다면 실기 없이도 오늘 바로 돌릴 수 있다.
- **미구현(실기 세션에서 채움)**: :func:`read_next_frame_telemetry_timestamps` —
  DJI PSDK 콜백 연동 자리. 지금은 항상 ``NotImplementedError``를 낸다. 가짜 값으로
  채우면 "실기 미검증"을 숨기게 되므로(INV-040 정신), 절대 임시 return 값을 넣지 않는다.

## 사용법

```bash
# 실기 세션 중 수집(현재는 PSDK 미연동이라 NotImplementedError로 즉시 중단됨 — 의도된 동작)
uv run python tools/hil/capture_frame_telemetry_timing.py collect \\
    --session-id SESS-20260728T060000Z-<기체SN> \\
    --aircraft-sn <기체SN> \\
    --out hil_raw_logs/SESS-.../07_frame_telemetry_timing/<UTC_ts>__frame_telemetry.jsonl \\
    --num-samples 200

# 이미 수집된 JSONL로부터 p50/p95/max 요약(오늘 바로 실행 가능)
uv run python tools/hil/capture_frame_telemetry_timing.py summarize \\
    --in hil_raw_logs/SESS-.../07_frame_telemetry_timing/<UTC_ts>__frame_telemetry.jsonl \\
    --out hil_raw_logs/SESS-.../07_frame_telemetry_timing/<UTC_ts>__frame_telemetry_summary.json
```
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

# PRD §21.1 목표값. 판정 기준이 아니라 "무엇과 비교하는가"의 참고값 — 실측이 이
# 값을 넘겨도 스크립트는 실패하지 않는다(그건 PASS/BLOCKED 판단이고, 그 판단은
# docs/hil/CAPABILITY_ACCEPTANCE.md 절차에 따라 사람이 근거와 함께 기록한다).
DEFAULT_TARGET_P95_MS = 50.0


# --------------------------------------------------------------------------- #
# 스키마
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FrameTelemetrySample:
    """Frame 수신 시각과 그에 대응하는 Telemetry 수신 시각 1쌍 (JSONL 1줄).

    Attributes:
        sample_index: 세션 내 순번(0부터 시작).
        session_id: ``docs/hil/RAW_LOG_CONVENTIONS.md`` 형식의 세션 ID.
        aircraft_sn: 기체 시리얼넘버.
        frame_timestamp_utc: 카메라 Frame 캡처/수신 시각(UTC, ISO 8601, ``Z`` 서픽스).
        telemetry_timestamp_utc: 그 Frame에 대응시킨 Telemetry 샘플의 시각
            (UTC, ISO 8601, ``Z`` 서픽스).
        delta_ms: ``frame_timestamp_utc - telemetry_timestamp_utc`` (밀리초). 부호가
            있다 — 양수면 Frame이 Telemetry보다 늦게 도착했다는 뜻이다.
    """

    sample_index: int
    session_id: str
    aircraft_sn: str
    frame_timestamp_utc: str
    telemetry_timestamp_utc: str
    delta_ms: float


@dataclass(frozen=True, slots=True)
class TimingSummary:
    """:class:`FrameTelemetrySample` 모음의 시간차 통계 요약.

    Attributes:
        sample_count: 요약에 쓰인 표본 수. 0이면 :func:`summarize_deltas`가
            먼저 예외를 낸다 — ``sample_count=0``인 ``TimingSummary``는 존재하지 않는다
            (표본 수 없는 p50/p95/max 주장을 코드로 막는다).
        p50_ms: 중앙값(50th percentile), 절대값 기준.
        p95_ms: 95th percentile, 절대값 기준.
        max_ms: 최대값, 절대값 기준.
        mean_ms: 산술평균, 절대값 기준.
        target_p95_ms: 비교 대상 목표값(PRD §21.1, 기본 50.0).
        meets_target: ``p95_ms <= target_p95_ms``.
    """

    sample_count: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    mean_ms: float
    target_p95_ms: float
    meets_target: bool


# --------------------------------------------------------------------------- #
# 순수 함수 — 단위테스트 대상
# --------------------------------------------------------------------------- #


def compute_delta_ms(frame_ts: datetime, telemetry_ts: datetime) -> float:
    """``frame_ts - telemetry_ts``를 밀리초로 반환한다 (부호 보존).

    Raises:
        ValueError: 둘 중 하나라도 tz-aware가 아닐 때(암묵적 UTC 가정을 막는다 —
            ``SpikeEvidence.observed_at``과 동일한 원칙).
    """
    if frame_ts.tzinfo is None or telemetry_ts.tzinfo is None:
        raise ValueError("frame_ts, telemetry_ts 모두 tz-aware(UTC)여야 한다")
    delta = frame_ts - telemetry_ts
    return delta.total_seconds() * 1000.0


def percentile(values: Sequence[float], pct: float) -> float:
    """``values``의 ``pct`` 백분위수를 선형보간(linear interpolation)으로 계산한다.

    NumPy 기본 방식(``method="linear"``, Excel ``PERCENTILE.INC``와 동일)과 같은
    정의를 쓴다 — 재현 가능성을 위해 방식을 명시한다: 정렬된 배열에서 순위
    ``r = pct/100 * (n-1)`` 위치를 인접한 두 값 사이에서 선형보간한다.

    Args:
        values: 백분위수를 계산할 값들(빈 시퀀스 불가).
        pct: 0~100 사이의 백분위(예: 50, 95).

    Raises:
        ValueError: ``values``가 비었거나 ``pct``가 [0, 100] 범위 밖일 때.
    """
    if not values:
        raise ValueError("percentile: 빈 표본으로는 계산할 수 없다")
    if not (0.0 <= pct <= 100.0):
        raise ValueError(f"percentile: pct는 0~100 범위여야 한다 (받음: {pct})")

    sorted_values = sorted(values)
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]

    rank = (pct / 100.0) * (n - 1)
    lower_idx = int(rank)
    upper_idx = min(lower_idx + 1, n - 1)
    frac = rank - lower_idx
    return sorted_values[lower_idx] + frac * (sorted_values[upper_idx] - sorted_values[lower_idx])


def summarize_deltas(
    deltas_ms: Sequence[float],
    *,
    target_p95_ms: float = DEFAULT_TARGET_P95_MS,
) -> TimingSummary:
    """시간차 표본들로부터 :class:`TimingSummary`를 만든다.

    p50/p95/max/mean은 절대값(``abs``) 기준으로 계산한다 — Frame이 Telemetry보다
    먼저 오든 나중에 오든 "시간이 얼마나 어긋났는가"가 정렬 품질의 척도이지, 부호
    자체가 정렬 품질을 뜻하지 않는다. 부호 정보(어느 쪽이 체계적으로 앞서는가)는
    원본 JSONL의 ``delta_ms``에 그대로 남아 있으므로 손실되지 않는다.

    Raises:
        ValueError: ``deltas_ms``가 비어 있을 때 — "표본 수 0"으로 VERIFIED를
            주장하는 것을 막는다(``docs/hil/CAPABILITY_ACCEPTANCE.md`` 시간동기 기준).
    """
    if not deltas_ms:
        raise ValueError(
            "summarize_deltas: 표본이 0건이다 — 시간동기 VERIFIED에는 실측 표본이 "
            "필수다('미측정 + 이유'는 이 함수가 아니라 사람이 별도로 기록하는 문장이다)"
        )
    abs_values = [abs(v) for v in deltas_ms]
    p50 = percentile(abs_values, 50.0)
    p95 = percentile(abs_values, 95.0)
    max_v = max(abs_values)
    mean_v = sum(abs_values) / len(abs_values)
    return TimingSummary(
        sample_count=len(deltas_ms),
        p50_ms=p50,
        p95_ms=p95,
        max_ms=max_v,
        mean_ms=mean_v,
        target_p95_ms=target_p95_ms,
        meets_target=p95 <= target_p95_ms,
    )


# --------------------------------------------------------------------------- #
# JSONL I/O
# --------------------------------------------------------------------------- #


def sample_to_json_line(sample: FrameTelemetrySample) -> str:
    """``sample``을 JSONL 한 줄(개행 없음)로 직렬화한다."""
    return json.dumps(asdict(sample), ensure_ascii=False, sort_keys=True)


def iter_samples_from_jsonl(path: Path) -> Iterator[FrameTelemetrySample]:
    """JSONL 파일을 한 줄씩 읽어 :class:`FrameTelemetrySample`로 파싱한다.

    빈 줄은 건너뛴다. 파싱 실패 줄은 어느 줄(1-based)인지 포함해 예외를 낸다 —
    조용히 건너뛰면 표본 수가 은근슬쩍 줄어들 수 있다.
    """
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                yield FrameTelemetrySample(**payload)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(f"{path}:{line_no}: JSONL 파싱 실패 — {exc}") from exc


def append_sample_jsonl(path: Path, sample: FrameTelemetrySample) -> None:
    """``sample``을 ``path``에 한 줄 추가한다(append). 부모 디렉터리는 미리 만든다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(sample_to_json_line(sample))
        f.write("\n")


# --------------------------------------------------------------------------- #
# PSDK 연동 자리 — 실기 세션에서 채움
# --------------------------------------------------------------------------- #


def read_next_frame_telemetry_timestamps() -> tuple[datetime, datetime]:
    """PSDK에서 다음 Frame·Telemetry 시각 쌍을 읽는다.

    TODO(실기 세션, HARDWARE_SESSION_PLAYBOOK.md 7단계): DJI Payload SDK 콜백 연동
    필요. 예상 형태 — 카메라 프레임 콜백이 프레임 수신 시각을 주고, 그 프레임과
    가장 가까운 Telemetry(비행 상태) 콜백의 시각을 짝짓는다. 정확한 콜백 함수명·
    시그니처는 이 문서 작성 시점에 확정하지 않는다(불확실한 API 이름을 단정하지
    말 것) — 2단계 "DJI 공식 샘플 빌드"에서 실제로 확인한 API로 이 함수 본문을
    교체할 것.

    Raises:
        NotImplementedError: PSDK 연동 전까지 항상 발생한다. 가짜 timestamp를
            반환하도록 절대 고치지 말 것 — 그러면 이 도구가 "측정했다"는 거짓
            신호를 내게 된다(INV-040: mock/placeholder로 실패를 가리지 않는다).
    """
    raise NotImplementedError(
        "PSDK 카메라 프레임 콜백 + Telemetry 콜백 미연동. "
        "docs/hil/HARDWARE_SESSION_PLAYBOOK.md 2·7단계를 실기에서 완료한 뒤 "
        "이 함수를 실제 PSDK API 호출로 교체할 것."
    )


def collect_session(
    *,
    session_id: str,
    aircraft_sn: str,
    out_path: Path,
    num_samples: int,
) -> None:
    """``num_samples``개의 Frame–Telemetry 쌍을 수집해 ``out_path``에 JSONL로 쓴다.

    :func:`read_next_frame_telemetry_timestamps`가 미구현인 동안은 첫 호출에서
    바로 ``NotImplementedError``가 전파된다 — 의도된 fail-closed 동작이다.
    """
    for i in range(num_samples):
        frame_ts, telemetry_ts = read_next_frame_telemetry_timestamps()
        sample = FrameTelemetrySample(
            sample_index=i,
            session_id=session_id,
            aircraft_sn=aircraft_sn,
            frame_timestamp_utc=frame_ts.isoformat(),
            telemetry_timestamp_utc=telemetry_ts.isoformat(),
            delta_ms=compute_delta_ms(frame_ts, telemetry_ts),
        )
        append_sample_jsonl(out_path, sample)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _cmd_collect(args: argparse.Namespace) -> int:
    collect_session(
        session_id=args.session_id,
        aircraft_sn=args.aircraft_sn,
        out_path=Path(args.out),
        num_samples=args.num_samples,
    )
    print(f"수집 완료: {args.out}")
    return 0


def _cmd_summarize(args: argparse.Namespace) -> int:
    in_path = Path(args.inp)
    samples = list(iter_samples_from_jsonl(in_path))
    deltas = [s.delta_ms for s in samples]
    summary = summarize_deltas(deltas, target_p95_ms=args.target_p95_ms)

    result = {
        "input": str(in_path),
        "summarized_at_utc": datetime.now(UTC).isoformat(),
        **asdict(summary),
    }
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"요약 기록: {out_path}", file=sys.stderr)

    if not summary.meets_target:
        print(
            f"주의: p95={summary.p95_ms:.2f}ms > 목표 {summary.target_p95_ms:.2f}ms — "
            "PASS/BLOCKED 판정은 docs/hil/CAPABILITY_ACCEPTANCE.md 절차를 따를 것 "
            "(이 스크립트는 판정을 내리지 않는다)",
            file=sys.stderr,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Frame–Telemetry 시간차 수집·요약 (PRD §21.1, INV-025 전제조건).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser(
        "collect", help="실기에서 Frame/Telemetry 쌍을 수집한다 (PSDK 미연동 — 현재 항상 실패)."
    )
    p_collect.add_argument(
        "--session-id", required=True, help="docs/hil/RAW_LOG_CONVENTIONS.md 형식의 세션 ID"
    )
    p_collect.add_argument("--aircraft-sn", required=True, help="기체 시리얼넘버")
    p_collect.add_argument("--out", required=True, help="출력 JSONL 경로")
    p_collect.add_argument("--num-samples", type=int, default=200, help="수집할 표본 수 (기본 200)")
    p_collect.set_defaults(func=_cmd_collect)

    p_summarize = sub.add_parser(
        "summarize", help="이미 수집된 JSONL로 p50/p95/max를 계산한다 (실기 없이 실행 가능)."
    )
    p_summarize.add_argument("--in", dest="inp", required=True, help="입력 JSONL 경로")
    p_summarize.add_argument("--out", default=None, help="요약 JSON 출력 경로(선택)")
    p_summarize.add_argument(
        "--target-p95-ms",
        type=float,
        default=DEFAULT_TARGET_P95_MS,
        help=f"비교 대상 p95 목표값 ms (기본 {DEFAULT_TARGET_P95_MS}, PRD §21.1)",
    )
    p_summarize.set_defaults(func=_cmd_summarize)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
