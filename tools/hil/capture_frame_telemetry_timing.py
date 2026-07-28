"""Frame–Telemetry 시간차 실측 도구 (HARDWARE_SESSION_PLAYBOOK.md 7단계).

MASTER_PRD §21.1 "Sensor Timestamp alignment: p95 50ms 이하 목표"의 실측 도구다.
이 실측은 `docs/product/DOMAIN_INVARIANTS.md` INV-025의 전제조건이기도 하다 —
``WorldEntity.uncertainty.localization_state = CONFIRMED``는 ``CALIBRATED_POSE``
시점 증거를 요구하는데, 그 시점 증거의 정확도는 결국 Frame과 Telemetry가 실제로
얼마나 시간적으로 정렬돼 있는지에 달려 있다. 여기서 나온 p50/p95/max 없이는
"시간동기가 맞다"는 주장 자체가 근거가 없다(`docs/hil/CAPABILITY_ACCEPTANCE.md` 참고).

## P0-1: 측정(measurement_status) ≠ 목표달성(acceptance_status)

"측정을 성공적으로 수행했다"와 "요구사항(p95 ≤ 50ms)을 만족했다"는 다른 질문이다.
이 도구는 둘을 분리한 2축으로 판정을 출력한다(``judge_acceptance``) —
``docs/hil/CAPABILITY_ACCEPTANCE.md`` "시간동기" 행이 이 2축의 SSOT다. 어느 쪽이든
사람이 임의로 PASS/VERIFIED를 선언할 근거로 이 스크립트의 출력을 오독해서는 안 된다.

## 입력 JSONL은 신뢰하지 않는다 (증거 판정 도구 수준)

이 도구가 다루는 JSONL은 실기에서 수집된 원본 증거다 — 저장된 ``delta_ms``를 그대로
믿고 요약하면, 임의로 조작된(또는 손상된) 파일로 좋은 p95를 위조할 수 있다. 그래서
``load_frame_telemetry_jsonl``은 각 줄을 다음 기준으로 재검증하고, 위반 줄은 사유와
함께 거부한다(전체 로드를 막지 않되 조용히 사라지지도 않는다):

- JSON 파싱 자체가 NaN/Infinity/-Infinity 같은 비표준 상수를 거부한다.
- ``frame_timestamp_utc``/``telemetry_timestamp_utc``는 UTC(offset ``+00:00``,
  ``Z`` 서픽스 허용)가 아니면 거부한다.
- 저장된 ``delta_ms``는 두 timestamp로부터 재계산한 값과 tolerance(기본 0.5ms) 내에서
  일치해야 한다 — 벗어나면 위조/오기로 간주해 거부한다.
- ``session_id``/``aircraft_sn``은 공백일 수 없다.
- ``sample_index``는 음수 불가·중복 거부. 불연속은 거부하지 않되 경고로 남긴다.

## 이 파일에서 완전히 구현된 것 / 아닌 것

- **완전 구현 + 순수 함수(단위테스트 가능)**: :func:`percentile`, :func:`summarize_deltas`,
  :func:`compute_delta_ms`, :func:`parse_utc_timestamp`, :func:`judge_acceptance`,
  JSONL 직렬화/역직렬화·검증, ``summarize`` CLI 서브커맨드. 이미 수집된 JSONL 파일이
  있다면 실기 없이도 오늘 바로 돌릴 수 있다.
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

# 이미 수집된 JSONL로부터 p50/p95/max + measurement_status/acceptance_status 요약
# (오늘 바로 실행 가능)
uv run python tools/hil/capture_frame_telemetry_timing.py summarize \\
    --in hil_raw_logs/SESS-.../07_frame_telemetry_timing/<UTC_ts>__frame_telemetry.jsonl \\
    --out hil_raw_logs/SESS-.../07_frame_telemetry_timing/<UTC_ts>__frame_telemetry_summary.json
```
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

# PRD §21.1 목표값. 판정 기준이 아니라 "무엇과 비교하는가"의 참고값 — 실측이 이
# 값을 넘겨도 스크립트는 실패(예외)하지 않는다. 대신 acceptance_status=FAIL로
# 정직하게 기록한다(P0-1) — VERIFIED 승격 여부는
# docs/hil/CAPABILITY_ACCEPTANCE.md 절차에 따라 사람이 근거와 함께 기록한다.
DEFAULT_TARGET_P95_MS = 50.0

# docs/hil/CAPABILITY_ACCEPTANCE.md "시간동기" 행의 권장 최소 표본 수.
DEFAULT_MIN_SAMPLE_COUNT = 100

# 저장된 delta_ms와 두 timestamp로부터 재계산한 delta_ms 사이 허용 오차(ms).
DEFAULT_DELTA_TOLERANCE_MS = 0.5

_REQUIRED_FIELDS = (
    "sample_index",
    "session_id",
    "aircraft_sn",
    "frame_timestamp_utc",
    "telemetry_timestamp_utc",
    "delta_ms",
)


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
            있다 — 양수면 Frame이 Telemetry보다 늦게 도착했다는 뜻이다. JSONL에서
            읽어들인 값은 두 timestamp로부터 재계산한 값이다(저장값을 그대로
            신뢰하지 않는다 — 모듈 docstring 참고).
    """

    sample_index: int
    session_id: str
    aircraft_sn: str
    frame_timestamp_utc: str
    telemetry_timestamp_utc: str
    delta_ms: float


@dataclass(frozen=True, slots=True)
class RejectedLine:
    """검증에 실패해 유효 표본에서 제외된 JSONL 줄 1건."""

    line_no: int
    reason: str


@dataclass(frozen=True, slots=True)
class FrameTelemetryLoadResult:
    """JSONL 파일 1개를 검증하며 읽은 결과 (증거 판정에 필요한 전체 맥락).

    Attributes:
        samples: 검증을 통과한 표본(파일 등장 순서).
        rejected: 검증에 실패해 제외된 줄(line_no 오름차순).
        warnings: 거부까지는 아니지만 기록해 둘 사항(예: sample_index 불연속).
        sha256: 입력 파일 원본 바이트의 SHA-256 hexdigest — 어떤 파일을 근거로
            판정했는지 증거로 고정한다.
    """

    samples: tuple[FrameTelemetrySample, ...]
    rejected: tuple[RejectedLine, ...]
    warnings: tuple[str, ...]
    sha256: str


class MeasurementStatus(StrEnum):
    """측정을 성공적으로 수행했는가 (P0-1 2축 중 1축)."""

    MEASURED = "MEASURED"
    NOT_MEASURED = "NOT_MEASURED"


class AcceptanceStatus(StrEnum):
    """요구사항(p95 ≤ target)을 만족했는가 (P0-1 2축 중 1축).

    ``measurement_status=NOT_MEASURED``면 판정 대상 자체가 없으므로 이 값은 쓰이지
    않는다(``Acceptance.acceptance_status``가 ``None``이 된다).
    """

    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"


@dataclass(frozen=True, slots=True)
class Acceptance:
    """P0-1 2축 판정 결과 (``docs/hil/CAPABILITY_ACCEPTANCE.md`` "시간동기" 행 SSOT)."""

    measurement_status: MeasurementStatus
    acceptance_status: AcceptanceStatus | None


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
        meets_target: ``p95_ms <= target_p95_ms``. **VERIFIED 승격 근거가 아니다** —
            판정은 :func:`judge_acceptance`의 ``acceptance_status``를 따른다(P0-1).
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
        ValueError: 둘 중 하나라도 tz-aware가 아니거나, UTC(offset ``+00:00``)가
            아닐 때. tz-aware이기만 하면 통과시키지 않는다 — 다른 타임존이 섞여
            들어오면 delta_ms가 시간 단위로 틀어질 수 있다(``SpikeEvidence.observed_at``과
            동일한 UTC 강제 원칙).
    """
    for name, ts in (("frame_ts", frame_ts), ("telemetry_ts", telemetry_ts)):
        if ts.tzinfo is None:
            raise ValueError(f"{name}는 tz-aware(UTC)여야 한다")
        offset = ts.utcoffset()
        if offset is None or offset != timedelta(0):
            raise ValueError(f"{name}는 UTC(offset +00:00)여야 한다 (받은 offset: {offset})")
    delta = frame_ts - telemetry_ts
    return delta.total_seconds() * 1000.0


def parse_utc_timestamp(value: str, *, field_name: str) -> datetime:
    """ISO 8601 timestamp 문자열을 UTC(offset ``+00:00``) tz-aware ``datetime``으로
    엄격 파싱한다.

    ``Z`` 서픽스는 UTC로 허용한다. 그 외 offset은 어떤 것이든(비어있는 naive 포함)
    전부 거부한다 — "tz-aware이기만 하면 됨"이 아니라 **UTC 강제**다.

    Raises:
        ValueError: ISO8601 파싱 실패, naive datetime, 또는 offset이 ``+00:00``이
            아닐 때.
    """
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name}: ISO8601 파싱 실패 — {value!r} ({exc})") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name}: tz-aware(UTC)여야 한다 (받음: {value!r})")
    offset = parsed.utcoffset()
    if offset is None or offset != timedelta(0):
        raise ValueError(
            f"{field_name}: UTC(offset +00:00, 'Z' 허용)여야 한다 "
            f"(받음: {value!r}, offset: {offset})"
        )
    return parsed


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
        ValueError: ``deltas_ms``가 비어 있거나, ``target_p95_ms``가 유한한 양수가
            아닐 때 — "표본 수 0"으로 VERIFIED를 주장하는 것을 막는다
            (``docs/hil/CAPABILITY_ACCEPTANCE.md`` 시간동기 기준).
    """
    if not deltas_ms:
        raise ValueError(
            "summarize_deltas: 표본이 0건이다 — 시간동기 VERIFIED에는 실측 표본이 "
            "필수다('미측정 + 이유'는 이 함수가 아니라 사람이 별도로 기록하는 문장이다)"
        )
    if not math.isfinite(target_p95_ms) or target_p95_ms <= 0:
        raise ValueError(
            f"summarize_deltas: target_p95_ms는 유한한 양수여야 한다 (받음: {target_p95_ms})"
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


def judge_acceptance(
    summary: TimingSummary | None,
    *,
    min_sample_count: int = DEFAULT_MIN_SAMPLE_COUNT,
) -> Acceptance:
    """``docs/hil/CAPABILITY_ACCEPTANCE.md`` "시간동기" 행의 2축 판정 규칙을 코드로
    강제한다 (P0-1).

    - ``summary is None``(표본 0건) → ``NOT_MEASURED`` / 판정 없음.
    - 표본 수 < ``min_sample_count`` → ``MEASURED`` / ``INSUFFICIENT_SAMPLES``.
    - p95 ≤ target → ``MEASURED`` / ``PASS``.
    - p95 > target → ``MEASURED`` / ``FAIL`` (표본 수가 충분해도 VERIFIED 승격 금지).

    사람이 이 판정을 임의로 뒤집어 VERIFIED를 선언하는 경로는 이 함수 밖에 있다 —
    이 함수는 그 뒤집기가 "실측 절차를 따랐다"는 근거가 되지 않는다는 점만 코드로
    확정한다.
    """
    if summary is None or summary.sample_count == 0:
        return Acceptance(measurement_status=MeasurementStatus.NOT_MEASURED, acceptance_status=None)
    if summary.sample_count < min_sample_count:
        return Acceptance(
            measurement_status=MeasurementStatus.MEASURED,
            acceptance_status=AcceptanceStatus.INSUFFICIENT_SAMPLES,
        )
    status = (
        AcceptanceStatus.PASS if summary.p95_ms <= summary.target_p95_ms else AcceptanceStatus.FAIL
    )
    return Acceptance(measurement_status=MeasurementStatus.MEASURED, acceptance_status=status)


# --------------------------------------------------------------------------- #
# JSONL I/O + 검증 — 입력을 신뢰하지 않는다(모듈 docstring 참고)
# --------------------------------------------------------------------------- #


def _reject_json_constant(constant: str) -> float:
    """``json.loads(parse_constant=...)`` 훅 — NaN/Infinity/-Infinity를 거부한다.

    표준 JSON에는 없는 비표준 토큰이다. 기본 ``json`` 모듈은 이를 조용히
    ``float("nan")``/``float("inf")``로 받아들이는데, 그 값이 ``delta_ms``에 섞이면
    percentile 계산이 오염되거나(NaN 비교는 항상 False) 비현실적인 좋은 p95를
    만들 수 있다 — 그래서 파싱 단계에서 즉시 거부한다.
    """
    raise ValueError(f"허용되지 않는 JSON 상수: {constant} (NaN/Infinity/-Infinity 금지)")


def _parse_sample_line(
    line: str,
    *,
    delta_tolerance_ms: float,
) -> FrameTelemetrySample:
    """JSONL 한 줄을 검증하며 :class:`FrameTelemetrySample`로 파싱한다.

    Raises:
        ValueError: 아래 중 하나라도 위반 시 구체적 사유와 함께.
            - JSON 파싱 실패(NaN/Infinity 포함) 또는 최상위가 객체(dict)가 아님
            - 필수 필드 누락
            - ``session_id``/``aircraft_sn``이 공백
            - ``sample_index``가 정수가 아니거나 음수
            - timestamp가 UTC(offset ``+00:00``) tz-aware ISO8601이 아님
            - 저장된 ``delta_ms``가 두 timestamp로부터 재계산한 값과
              ``delta_tolerance_ms`` 이내로 일치하지 않음(위조/오기 의심)
    """
    try:
        payload: Any = json.loads(line, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 파싱 실패 — {exc}") from exc
    except ValueError as exc:
        # _reject_json_constant가 던진 ValueError — 그대로 전파(사유가 이미 구체적).
        raise ValueError(str(exc)) from exc

    if not isinstance(payload, dict):
        raise ValueError(f"JSON 객체가 아님 (받음 타입: {type(payload).__name__})")

    missing = [f for f in _REQUIRED_FIELDS if f not in payload]
    if missing:
        raise ValueError(f"필수 필드 누락: {', '.join(missing)}")

    sample_index = payload["sample_index"]
    if not isinstance(sample_index, int) or isinstance(sample_index, bool):
        raise ValueError(f"sample_index는 정수여야 한다 (받음: {sample_index!r})")
    if sample_index < 0:
        raise ValueError(f"sample_index는 음수일 수 없다 (받음: {sample_index})")

    session_id = payload["session_id"]
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError(f"session_id는 공백이 아닌 문자열이어야 한다 (받음: {session_id!r})")

    aircraft_sn = payload["aircraft_sn"]
    if not isinstance(aircraft_sn, str) or not aircraft_sn.strip():
        raise ValueError(f"aircraft_sn은 공백이 아닌 문자열이어야 한다 (받음: {aircraft_sn!r})")

    frame_ts_raw = payload["frame_timestamp_utc"]
    telemetry_ts_raw = payload["telemetry_timestamp_utc"]
    if not isinstance(frame_ts_raw, str) or not isinstance(telemetry_ts_raw, str):
        raise ValueError("frame_timestamp_utc/telemetry_timestamp_utc는 문자열이어야 한다")

    frame_ts = parse_utc_timestamp(frame_ts_raw, field_name="frame_timestamp_utc")
    telemetry_ts = parse_utc_timestamp(telemetry_ts_raw, field_name="telemetry_timestamp_utc")

    stored_delta_raw = payload["delta_ms"]
    if isinstance(stored_delta_raw, bool) or not isinstance(stored_delta_raw, int | float):
        raise ValueError(f"delta_ms는 숫자여야 한다 (받음: {stored_delta_raw!r})")
    stored_delta = float(stored_delta_raw)
    if not math.isfinite(stored_delta):
        raise ValueError(f"delta_ms는 유한한 값이어야 한다 (받음: {stored_delta})")

    recomputed_delta = compute_delta_ms(frame_ts, telemetry_ts)
    if abs(recomputed_delta - stored_delta) > delta_tolerance_ms:
        raise ValueError(
            f"저장된 delta_ms={stored_delta:.3f}가 timestamp 재계산값="
            f"{recomputed_delta:.3f}과 tolerance({delta_tolerance_ms}ms)를 벗어난다 "
            "— 임의 조작/오기 의심(가짜 delta_ms=0 주입 등)"
        )

    return FrameTelemetrySample(
        sample_index=sample_index,
        session_id=session_id,
        aircraft_sn=aircraft_sn,
        frame_timestamp_utc=frame_ts_raw,
        telemetry_timestamp_utc=telemetry_ts_raw,
        delta_ms=recomputed_delta,
    )


def _validate_sample_indices(
    parsed: Sequence[tuple[int, FrameTelemetrySample]],
) -> tuple[list[FrameTelemetrySample], list[RejectedLine], list[str]]:
    """파싱된 ``(line_no, sample)`` 목록에서 ``sample_index`` 중복을 거부하고
    불연속을 경고한다.

    음수 ``sample_index``는 이미 :func:`_parse_sample_line`에서 걸러지므로 여기서는
    다루지 않는다. 순수 함수 — 입력만으로 결과가 결정된다.
    """
    valid: list[FrameTelemetrySample] = []
    rejected: list[RejectedLine] = []
    seen_at: dict[int, int] = {}

    for line_no, sample in parsed:
        first_line_no = seen_at.get(sample.sample_index)
        if first_line_no is not None:
            rejected.append(
                RejectedLine(
                    line_no=line_no,
                    reason=(
                        f"중복 sample_index={sample.sample_index} "
                        f"(최초 등장: line {first_line_no})"
                    ),
                )
            )
            continue
        seen_at[sample.sample_index] = line_no
        valid.append(sample)

    warnings: list[str] = []
    sorted_indices = sorted(s.sample_index for s in valid)
    # pairwise 순회 — sorted_indices[1:]는 정의상 원본보다 정확히 1개 짧다(정상 형태).
    for prev_idx, cur_idx in zip(sorted_indices, sorted_indices[1:], strict=False):
        gap = cur_idx - prev_idx
        if gap > 1:
            warnings.append(f"sample_index 불연속: {prev_idx} 다음이 {cur_idx} (간격 {gap})")

    return valid, rejected, warnings


def load_frame_telemetry_jsonl(
    path: Path,
    *,
    delta_tolerance_ms: float = DEFAULT_DELTA_TOLERANCE_MS,
) -> FrameTelemetryLoadResult:
    """JSONL 파일을 검증하며 읽어 :class:`FrameTelemetryLoadResult`를 만든다.

    한 줄이라도 검증에 실패하면(JSON 파싱·필수 필드·UTC·delta 재계산 불일치·
    음수/중복 index 등) 그 줄은 유효 표본에서 제외되고 사유와 함께 ``rejected``에
    남는다 — 한 줄의 결함이 전체 파일 로드를 막지 않되, 조용히 사라지지도 않는다.
    빈 줄은 건너뛴다(거부로 집계하지 않는다).
    """
    raw_bytes = path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    text = raw_bytes.decode("utf-8")

    parsed: list[tuple[int, FrameTelemetrySample]] = []
    rejected: list[RejectedLine] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            sample = _parse_sample_line(line, delta_tolerance_ms=delta_tolerance_ms)
        except ValueError as exc:
            rejected.append(RejectedLine(line_no=line_no, reason=str(exc)))
            continue
        parsed.append((line_no, sample))

    valid_samples, dup_rejected, warnings = _validate_sample_indices(parsed)
    rejected.extend(dup_rejected)
    rejected.sort(key=lambda r: r.line_no)

    return FrameTelemetryLoadResult(
        samples=tuple(valid_samples),
        rejected=tuple(rejected),
        warnings=tuple(warnings),
        sha256=sha256,
    )


def sample_to_json_line(sample: FrameTelemetrySample) -> str:
    """``sample``을 JSONL 한 줄(개행 없음)로 직렬화한다."""
    return json.dumps(asdict(sample), ensure_ascii=False, sort_keys=True)


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
    load_result = load_frame_telemetry_jsonl(
        in_path, delta_tolerance_ms=args.delta_tolerance_ms
    )

    deltas = [s.delta_ms for s in load_result.samples]
    summary: TimingSummary | None = None
    if deltas:
        summary = summarize_deltas(deltas, target_p95_ms=args.target_p95_ms)
    acceptance = judge_acceptance(summary, min_sample_count=args.min_sample_count)

    sample_indices = [s.sample_index for s in load_result.samples]
    result = {
        "input": str(in_path),
        "input_sha256": load_result.sha256,
        "summarized_at_utc": datetime.now(UTC).isoformat(),
        "session_ids": sorted({s.session_id for s in load_result.samples}),
        "aircraft_sns": sorted({s.aircraft_sn for s in load_result.samples}),
        "sample_index_range": (
            {"min": min(sample_indices), "max": max(sample_indices)}
            if sample_indices
            else None
        ),
        "rejected_line_count": len(load_result.rejected),
        "rejected_lines": [asdict(r) for r in load_result.rejected],
        "warnings": list(load_result.warnings),
        "summary": asdict(summary) if summary is not None else None,
        "measurement_status": acceptance.measurement_status.value,
        "acceptance_status": (
            acceptance.acceptance_status.value if acceptance.acceptance_status else None
        ),
    }
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"요약 기록: {out_path}", file=sys.stderr)

    if load_result.rejected:
        print(
            f"주의: {len(load_result.rejected)}개 줄이 검증에 실패해 제외됐다 — "
            "rejected_lines 참고",
            file=sys.stderr,
        )
    if acceptance.acceptance_status is AcceptanceStatus.FAIL:
        assert summary is not None
        print(
            f"주의: acceptance_status=FAIL — p95={summary.p95_ms:.2f}ms > 목표 "
            f"{summary.target_p95_ms:.2f}ms. 이 결과로 VERIFIED 승격 금지 "
            "(docs/hil/CAPABILITY_ACCEPTANCE.md 절차를 따를 것 — 이 스크립트는 "
            "승격 판정을 내리지 않는다)",
            file=sys.stderr,
        )
    elif acceptance.measurement_status is MeasurementStatus.NOT_MEASURED:
        print(
            "주의: measurement_status=NOT_MEASURED(표본 0건) — VERIFIED 승격 근거 없음",
            file=sys.stderr,
        )
    elif acceptance.acceptance_status is AcceptanceStatus.INSUFFICIENT_SAMPLES:
        assert summary is not None
        print(
            f"주의: acceptance_status=INSUFFICIENT_SAMPLES — 표본 {summary.sample_count}건 "
            f"< 권장 최소 {args.min_sample_count}건. PASS/FAIL 어느 쪽도 아직 주장하지 않는다",
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
        "summarize",
        help=(
            "이미 수집된 JSONL을 검증하며 읽어 p50/p95/max + 2축 판정을 낸다 "
            "(실기 없이 실행 가능)."
        ),
    )
    p_summarize.add_argument("--in", dest="inp", required=True, help="입력 JSONL 경로")
    p_summarize.add_argument("--out", default=None, help="요약 JSON 출력 경로(선택)")
    p_summarize.add_argument(
        "--target-p95-ms",
        type=float,
        default=DEFAULT_TARGET_P95_MS,
        help=f"비교 대상 p95 목표값 ms (기본 {DEFAULT_TARGET_P95_MS}, PRD §21.1)",
    )
    p_summarize.add_argument(
        "--min-sample-count",
        type=int,
        default=DEFAULT_MIN_SAMPLE_COUNT,
        help=(
            "acceptance_status=PASS/FAIL 판정에 필요한 최소 표본 수 "
            f"(기본 {DEFAULT_MIN_SAMPLE_COUNT})"
        ),
    )
    p_summarize.add_argument(
        "--delta-tolerance-ms",
        type=float,
        default=DEFAULT_DELTA_TOLERANCE_MS,
        help=(
            "저장된 delta_ms와 timestamp 재계산값 사이 허용 오차 ms "
            f"(기본 {DEFAULT_DELTA_TOLERANCE_MS})"
        ),
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
