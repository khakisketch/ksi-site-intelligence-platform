"""Frame–Telemetry 시간동기 실측 도구 검증 (P0-1 2축 판정 + P1 증거 판정 강화).

green≠작동 방지 핵심: "요약 함수가 숫자를 뱉는다"가 아니라 "위조/오기된 입력을
실제로 거부하는가"·"목표 미달을 VERIFIED 승격 근거로 위장할 수 없는가"를 검증한다.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "hil"))

from capture_frame_telemetry_timing import (  # noqa: E402
    AcceptanceStatus,
    FrameTelemetrySample,
    MeasurementStatus,
    _parse_sample_line,
    _validate_sample_indices,
    append_sample_jsonl,
    compute_delta_ms,
    judge_acceptance,
    load_frame_telemetry_jsonl,
    parse_utc_timestamp,
    percentile,
    summarize_deltas,
)

FROZEN_UTC = datetime(2026, 7, 27, 5, 0, 0, tzinfo=UTC)


def _sample(
    *,
    sample_index: int = 0,
    session_id: str = "SESS-1",
    aircraft_sn: str = "SN-1",
    frame_ts: datetime = FROZEN_UTC,
    telemetry_ts: datetime | None = None,
    delta_ms: float | None = None,
) -> dict:
    telemetry_ts = telemetry_ts or (frame_ts - timedelta(milliseconds=10))
    computed_delta = (frame_ts - telemetry_ts).total_seconds() * 1000.0
    return {
        "sample_index": sample_index,
        "session_id": session_id,
        "aircraft_sn": aircraft_sn,
        "frame_timestamp_utc": frame_ts.isoformat().replace("+00:00", "Z"),
        "telemetry_timestamp_utc": telemetry_ts.isoformat().replace("+00:00", "Z"),
        "delta_ms": delta_ms if delta_ms is not None else computed_delta,
    }


# ── percentile / summarize_deltas ────────────────────────────────────────────


def test_percentile_matches_numpy_linear_method() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(values, 50.0) == pytest.approx(30.0)
    assert percentile(values, 0.0) == pytest.approx(10.0)
    assert percentile(values, 100.0) == pytest.approx(50.0)


def test_percentile_rejects_empty_sequence() -> None:
    with pytest.raises(ValueError, match="빈 표본"):
        percentile([], 50.0)


def test_summarize_deltas_rejects_zero_samples() -> None:
    with pytest.raises(ValueError, match="0건"):
        summarize_deltas([])


def test_summarize_deltas_rejects_non_finite_target() -> None:
    with pytest.raises(ValueError, match="target_p95_ms"):
        summarize_deltas([1.0, 2.0], target_p95_ms=float("nan"))
    with pytest.raises(ValueError, match="target_p95_ms"):
        summarize_deltas([1.0, 2.0], target_p95_ms=-5.0)
    with pytest.raises(ValueError, match="target_p95_ms"):
        summarize_deltas([1.0, 2.0], target_p95_ms=0.0)


def test_summarize_deltas_uses_absolute_values() -> None:
    summary = summarize_deltas([-40.0, 40.0], target_p95_ms=50.0)
    assert summary.p50_ms == pytest.approx(40.0)
    assert summary.meets_target is True


# ── compute_delta_ms / parse_utc_timestamp — UTC 강제 ───────────────────────


def test_compute_delta_ms_rejects_naive_datetime() -> None:
    naive = datetime(2026, 7, 27, 5, 0, 0)
    with pytest.raises(ValueError, match="tz-aware"):
        compute_delta_ms(FROZEN_UTC, naive)


def test_compute_delta_ms_rejects_non_utc_offset() -> None:
    kst = datetime(2026, 7, 27, 14, 0, 0, tzinfo=timezone(timedelta(hours=9)))
    with pytest.raises(ValueError, match="UTC"):
        compute_delta_ms(kst, FROZEN_UTC)


def test_compute_delta_ms_sign_and_magnitude() -> None:
    later = FROZEN_UTC + timedelta(milliseconds=42)
    assert compute_delta_ms(later, FROZEN_UTC) == pytest.approx(42.0)
    assert compute_delta_ms(FROZEN_UTC, later) == pytest.approx(-42.0)


def test_parse_utc_timestamp_accepts_z_suffix() -> None:
    parsed = parse_utc_timestamp("2026-07-27T05:00:00Z", field_name="x")
    assert parsed.utcoffset() == timedelta(0)


def test_parse_utc_timestamp_accepts_explicit_zero_offset() -> None:
    parsed = parse_utc_timestamp("2026-07-27T05:00:00+00:00", field_name="x")
    assert parsed.utcoffset() == timedelta(0)


def test_parse_utc_timestamp_rejects_non_utc_offset() -> None:
    with pytest.raises(ValueError, match="UTC"):
        parse_utc_timestamp("2026-07-27T14:00:00+09:00", field_name="x")


def test_parse_utc_timestamp_rejects_naive() -> None:
    with pytest.raises(ValueError, match="tz-aware"):
        parse_utc_timestamp("2026-07-27T05:00:00", field_name="x")


def test_parse_utc_timestamp_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="파싱 실패"):
        parse_utc_timestamp("not-a-timestamp", field_name="x")


# ── _parse_sample_line — 증거 판정 도구 수준 검증 ────────────────────────────


def test_parse_sample_line_accepts_valid_line() -> None:
    payload = _sample()
    sample = _parse_sample_line(json.dumps(payload), delta_tolerance_ms=0.5)
    assert isinstance(sample, FrameTelemetrySample)
    assert sample.sample_index == 0
    assert sample.delta_ms == pytest.approx(10.0)


def test_parse_sample_line_rejects_nan_json_constant() -> None:
    line = json.dumps(_sample()).replace(
        f'"delta_ms": {_sample()["delta_ms"]}', '"delta_ms": NaN'
    )
    with pytest.raises(ValueError, match="NaN|Infinity"):
        _parse_sample_line(line, delta_tolerance_ms=0.5)


def test_parse_sample_line_rejects_infinity_json_constant() -> None:
    raw = '{"sample_index": 0, "session_id": "S", "aircraft_sn": "A", ' \
        '"frame_timestamp_utc": "2026-07-27T05:00:00Z", ' \
        '"telemetry_timestamp_utc": "2026-07-27T04:59:59.990Z", "delta_ms": Infinity}'
    with pytest.raises(ValueError, match="NaN|Infinity"):
        _parse_sample_line(raw, delta_tolerance_ms=0.5)


def test_parse_sample_line_rejects_non_utc_timestamp() -> None:
    payload = _sample()
    payload["frame_timestamp_utc"] = "2026-07-27T14:00:00+09:00"
    with pytest.raises(ValueError, match="UTC"):
        _parse_sample_line(json.dumps(payload), delta_tolerance_ms=0.5)


def test_parse_sample_line_rejects_forged_zero_delta() -> None:
    """[핵심 반증 케이스] delta_ms=0을 임의 주입해 좋은 p95를 위조하는 것을 막는다."""
    payload = _sample(
        frame_ts=FROZEN_UTC,
        telemetry_ts=FROZEN_UTC - timedelta(milliseconds=500),  # 실제로는 500ms 어긋남
        delta_ms=0.0,  # 위조 — 저장값만 0으로 거짓 기입
    )
    with pytest.raises(ValueError, match="tolerance"):
        _parse_sample_line(json.dumps(payload), delta_tolerance_ms=0.5)


def test_parse_sample_line_accepts_delta_within_tolerance() -> None:
    frame_ts = FROZEN_UTC
    telemetry_ts = FROZEN_UTC - timedelta(milliseconds=10)
    payload = _sample(frame_ts=frame_ts, telemetry_ts=telemetry_ts, delta_ms=10.3)
    sample = _parse_sample_line(json.dumps(payload), delta_tolerance_ms=0.5)
    # delta_ms는 저장값이 아니라 재계산값을 신뢰한다.
    assert sample.delta_ms == pytest.approx(10.0)


def test_parse_sample_line_rejects_blank_session_id() -> None:
    payload = _sample(session_id="   ")
    with pytest.raises(ValueError, match="session_id"):
        _parse_sample_line(json.dumps(payload), delta_tolerance_ms=0.5)


def test_parse_sample_line_rejects_blank_aircraft_sn() -> None:
    payload = _sample(aircraft_sn="")
    with pytest.raises(ValueError, match="aircraft_sn"):
        _parse_sample_line(json.dumps(payload), delta_tolerance_ms=0.5)


def test_parse_sample_line_rejects_negative_sample_index() -> None:
    payload = _sample(sample_index=-1)
    with pytest.raises(ValueError, match="음수"):
        _parse_sample_line(json.dumps(payload), delta_tolerance_ms=0.5)


def test_parse_sample_line_rejects_missing_field() -> None:
    payload = _sample()
    del payload["aircraft_sn"]
    with pytest.raises(ValueError, match="필수 필드 누락"):
        _parse_sample_line(json.dumps(payload), delta_tolerance_ms=0.5)


def test_parse_sample_line_rejects_malformed_json() -> None:
    with pytest.raises(ValueError, match="JSON 파싱 실패"):
        _parse_sample_line("{not valid json", delta_tolerance_ms=0.5)


# ── _validate_sample_indices — 중복 거부·불연속 경고 ────────────────────────


def test_validate_sample_indices_rejects_duplicate() -> None:
    s0 = FrameTelemetrySample(0, "S", "A", "t0", "t0b", 1.0)
    s0_dup = FrameTelemetrySample(0, "S", "A", "t0", "t0b", 1.5)
    valid, rejected, warnings = _validate_sample_indices([(1, s0), (2, s0_dup)])
    assert valid == [s0]
    assert len(rejected) == 1
    assert "중복 sample_index=0" in rejected[0].reason
    assert rejected[0].line_no == 2


def test_validate_sample_indices_warns_on_gap() -> None:
    s0 = FrameTelemetrySample(0, "S", "A", "t0", "t0b", 1.0)
    s2 = FrameTelemetrySample(2, "S", "A", "t2", "t2b", 1.0)
    valid, rejected, warnings = _validate_sample_indices([(1, s0), (2, s2)])
    assert valid == [s0, s2]
    assert rejected == []
    assert any("불연속" in w for w in warnings)


def test_validate_sample_indices_no_warning_when_contiguous() -> None:
    s0 = FrameTelemetrySample(0, "S", "A", "t0", "t0b", 1.0)
    s1 = FrameTelemetrySample(1, "S", "A", "t1", "t1b", 1.0)
    _valid, _rejected, warnings = _validate_sample_indices([(1, s0), (2, s1)])
    assert warnings == []


# ── load_frame_telemetry_jsonl — 파일 단위 통합 ─────────────────────────────


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_frame_telemetry_jsonl_reports_sha256(tmp_path: Path) -> None:
    path = tmp_path / "in.jsonl"
    payload = _sample()
    _write_jsonl(path, [json.dumps(payload)])

    result = load_frame_telemetry_jsonl(path)

    expected_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.sha256 == expected_sha256
    assert len(result.samples) == 1
    assert result.rejected == ()


def test_load_frame_telemetry_jsonl_collects_rejected_lines_with_reasons(
    tmp_path: Path,
) -> None:
    path = tmp_path / "in.jsonl"
    good = json.dumps(_sample(sample_index=0))
    bad_json = "{not valid"
    bad_forged = json.dumps(
        _sample(
            sample_index=1,
            frame_ts=FROZEN_UTC,
            telemetry_ts=FROZEN_UTC - timedelta(milliseconds=500),
            delta_ms=0.0,
        )
    )
    _write_jsonl(path, [good, bad_json, bad_forged])

    result = load_frame_telemetry_jsonl(path)

    assert len(result.samples) == 1
    assert len(result.rejected) == 2
    assert result.rejected[0].line_no == 2
    assert result.rejected[1].line_no == 3
    assert "JSON 파싱 실패" in result.rejected[0].reason
    assert "tolerance" in result.rejected[1].reason


def test_load_frame_telemetry_jsonl_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "in.jsonl"
    _write_jsonl(path, [json.dumps(_sample()), "", "   "])

    result = load_frame_telemetry_jsonl(path)

    assert len(result.samples) == 1
    assert result.rejected == ()


def test_append_sample_jsonl_roundtrips_through_load(tmp_path: Path) -> None:
    path = tmp_path / "roundtrip.jsonl"
    frame_ts = FROZEN_UTC
    telemetry_ts = FROZEN_UTC - timedelta(milliseconds=12)
    sample = FrameTelemetrySample(
        sample_index=0,
        session_id="SESS-RT",
        aircraft_sn="SN-RT",
        frame_timestamp_utc=frame_ts.isoformat(),
        telemetry_timestamp_utc=telemetry_ts.isoformat(),
        delta_ms=compute_delta_ms(frame_ts, telemetry_ts),
    )
    append_sample_jsonl(path, sample)

    result = load_frame_telemetry_jsonl(path)

    assert len(result.samples) == 1
    assert result.samples[0].session_id == "SESS-RT"
    assert result.samples[0].delta_ms == pytest.approx(12.0)


# ── judge_acceptance — P0-1 2축 판정 ────────────────────────────────────────


def test_judge_acceptance_not_measured_when_no_summary() -> None:
    acceptance = judge_acceptance(None)
    assert acceptance.measurement_status is MeasurementStatus.NOT_MEASURED
    assert acceptance.acceptance_status is None


def test_judge_acceptance_insufficient_samples_below_minimum() -> None:
    summary = summarize_deltas([10.0] * 5, target_p95_ms=50.0)
    acceptance = judge_acceptance(summary, min_sample_count=100)
    assert acceptance.measurement_status is MeasurementStatus.MEASURED
    assert acceptance.acceptance_status is AcceptanceStatus.INSUFFICIENT_SAMPLES


def test_judge_acceptance_pass_when_within_target_and_enough_samples() -> None:
    summary = summarize_deltas([10.0] * 100, target_p95_ms=50.0)
    acceptance = judge_acceptance(summary, min_sample_count=100)
    assert acceptance.measurement_status is MeasurementStatus.MEASURED
    assert acceptance.acceptance_status is AcceptanceStatus.PASS


def test_judge_acceptance_fail_when_over_target_even_with_enough_samples() -> None:
    """[P0-1 핵심] 표본이 충분해도 p95>target이면 FAIL — VERIFIED 승격 근거 아님."""
    summary = summarize_deltas([80.0] * 100, target_p95_ms=50.0)
    acceptance = judge_acceptance(summary, min_sample_count=100)
    assert acceptance.measurement_status is MeasurementStatus.MEASURED
    assert acceptance.acceptance_status is AcceptanceStatus.FAIL


def test_judge_acceptance_zero_sample_count_summary_is_not_measured() -> None:
    # summarize_deltas는 빈 리스트를 거부하므로, sample_count=0 케이스는
    # summary=None 경로로만 도달 가능함을 별도로 확인한다(방어적 분기 커버).
    acceptance = judge_acceptance(None, min_sample_count=100)
    assert acceptance.measurement_status is MeasurementStatus.NOT_MEASURED
