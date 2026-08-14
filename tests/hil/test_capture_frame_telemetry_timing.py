"""Frame–Telemetry 시간동기 실측 도구 검증.

P0-1(측정≠수용 2축 판정) + P0-2(공식 Acceptance Profile 고정·증거 무결성 게이트) 검증.

green≠작동 방지 핵심: "요약 함수가 숫자를 뱉는다"가 아니라 "위조/오기된 입력을
실제로 거부하는가"·"목표 미달·증거 무효를 VERIFIED 승격 근거로 위장할 수 없는가"·
"공식 판정 기준을 CLI로 완화할 수 없는가"를 검증한다.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "hil"))

from capture_frame_telemetry_timing import (  # noqa: E402
    DEFAULT_DELTA_TOLERANCE_MS,
    EXPLORATORY_PROFILE_ID,
    OFFICIAL_PROFILE,
    AcceptanceProfile,
    AcceptanceReasonCode,
    AcceptanceStatus,
    EvidenceStatus,
    FrameTelemetryLoadResult,
    FrameTelemetrySample,
    MeasurementStatus,
    _parse_sample_line,
    _validate_sample_indices,
    append_sample_jsonl,
    build_parser,
    compute_delta_ms,
    convert_tap_log_to_samples,
    evaluate_evidence,
    judge_acceptance,
    judge_exploratory,
    judge_official,
    load_exploratory_evidence,
    load_frame_telemetry_jsonl,
    load_official_evidence,
    main,
    parse_utc_timestamp,
    percentile,
    summarize_deltas,
    validate_finite_nonnegative,
    validate_finite_positive,
    validate_nonblank_str,
    validate_positive_int,
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


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _lines_for_session(
    *,
    n: int,
    session_id: str,
    aircraft_sn: str,
    start_index: int = 0,
    delta_ms: float = 10.0,
) -> list[str]:
    """``n``개의 정상(유효) 표본 JSONL 줄을 만든다 — 서로 다른 세션/기체 조합을
    섞은 시나리오(B5/B6)에서 재사용하기 위한 헬퍼."""
    lines = []
    for i in range(n):
        frame_ts = FROZEN_UTC + timedelta(seconds=i)
        telemetry_ts = frame_ts - timedelta(milliseconds=delta_ms)
        payload = _sample(
            sample_index=start_index + i,
            session_id=session_id,
            aircraft_sn=aircraft_sn,
            frame_ts=frame_ts,
            telemetry_ts=telemetry_ts,
        )
        lines.append(json.dumps(payload))
    return lines


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


def test_load_frame_telemetry_jsonl_rejects_undecodable_bytes_without_crashing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bad_encoding.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00\x01not-utf8")

    result = load_frame_telemetry_jsonl(path)

    assert result.samples == ()
    assert len(result.rejected) == 1
    assert result.rejected[0].line_no == 0
    assert "decode" in result.rejected[0].reason


def test_load_frame_telemetry_jsonl_rejects_non_finite_tolerance() -> None:
    with pytest.raises(ValueError, match="delta_tolerance_ms"):
        load_frame_telemetry_jsonl(Path("unused"), delta_tolerance_ms=float("nan"))


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


def test_append_sample_jsonl_rejects_mixed_session_in_same_file(tmp_path: Path) -> None:
    path = tmp_path / "mixed.jsonl"
    frame_ts = FROZEN_UTC
    telemetry_ts = frame_ts - timedelta(milliseconds=10)
    first = FrameTelemetrySample(
        sample_index=0,
        session_id="SESS-A",
        aircraft_sn="SN-A",
        frame_timestamp_utc=frame_ts.isoformat(),
        telemetry_timestamp_utc=telemetry_ts.isoformat(),
        delta_ms=compute_delta_ms(frame_ts, telemetry_ts),
    )
    append_sample_jsonl(path, first)

    second = FrameTelemetrySample(
        sample_index=1,
        session_id="SESS-B",  # 다른 세션
        aircraft_sn="SN-A",
        frame_timestamp_utc=frame_ts.isoformat(),
        telemetry_timestamp_utc=telemetry_ts.isoformat(),
        delta_ms=compute_delta_ms(frame_ts, telemetry_ts),
    )
    with pytest.raises(ValueError, match="정책 위반"):
        append_sample_jsonl(path, second)

    # 거부됐으므로 파일에는 여전히 첫 표본 1건만 있어야 한다.
    result = load_frame_telemetry_jsonl(path)
    assert len(result.samples) == 1


def test_append_sample_jsonl_rejects_mixed_aircraft_in_same_file(tmp_path: Path) -> None:
    path = tmp_path / "mixed_aircraft.jsonl"
    frame_ts = FROZEN_UTC
    telemetry_ts = frame_ts - timedelta(milliseconds=10)
    first = FrameTelemetrySample(
        sample_index=0,
        session_id="SESS-A",
        aircraft_sn="SN-A",
        frame_timestamp_utc=frame_ts.isoformat(),
        telemetry_timestamp_utc=telemetry_ts.isoformat(),
        delta_ms=compute_delta_ms(frame_ts, telemetry_ts),
    )
    append_sample_jsonl(path, first)

    second = FrameTelemetrySample(
        sample_index=1,
        session_id="SESS-A",
        aircraft_sn="SN-B",  # 다른 기체
        frame_timestamp_utc=frame_ts.isoformat(),
        telemetry_timestamp_utc=telemetry_ts.isoformat(),
        delta_ms=compute_delta_ms(frame_ts, telemetry_ts),
    )
    with pytest.raises(ValueError, match="정책 위반"):
        append_sample_jsonl(path, second)


# ── judge_acceptance — P0-1 2축 판정(순수 통계, 증거 무결성 미반영) ─────────


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


def test_judge_acceptance_rejects_bad_min_sample_count() -> None:
    with pytest.raises(ValueError, match="min_sample_count"):
        judge_acceptance(None, min_sample_count=0)
    with pytest.raises(ValueError, match="min_sample_count"):
        judge_acceptance(None, min_sample_count=True)


# ── 인자 검증 헬퍼 (요구 7 / B10) ─────────────────────────────────────────


@pytest.mark.parametrize("bad", [True, False, 0, -1, -100])
def test_validate_positive_int_rejects_bool_and_nonpositive(bad: object) -> None:
    with pytest.raises(ValueError):
        validate_positive_int(bad, name="x")


def test_validate_positive_int_accepts_positive() -> None:
    assert validate_positive_int(5, name="x") == 5


@pytest.mark.parametrize("bad", [True, False, 0.0, -1.0, float("nan"), float("inf"), float("-inf")])
def test_validate_finite_positive_rejects_bad_values(bad: object) -> None:
    with pytest.raises(ValueError):
        validate_finite_positive(bad, name="x")


@pytest.mark.parametrize("bad", [True, False, -1.0, float("nan"), float("inf"), float("-inf")])
def test_validate_finite_nonnegative_rejects_bad_values(bad: object) -> None:
    with pytest.raises(ValueError):
        validate_finite_nonnegative(bad, name="x")


def test_validate_finite_nonnegative_accepts_zero() -> None:
    assert validate_finite_nonnegative(0.0, name="x") == 0.0


def test_validate_nonblank_str_rejects_blank_and_non_str() -> None:
    with pytest.raises(ValueError):
        validate_nonblank_str("   ", name="x")
    with pytest.raises(ValueError):
        validate_nonblank_str(None, name="x")


# ── AcceptanceProfile / OFFICIAL_PROFILE ────────────────────────────────────


def test_official_profile_is_frozen_with_expected_values() -> None:
    assert OFFICIAL_PROFILE.profile_id == "ksi-frame-telemetry-alignment-v1"
    assert OFFICIAL_PROFILE.target_p95_ms == 50.0
    assert OFFICIAL_PROFILE.min_sample_count == 100
    assert OFFICIAL_PROFILE.delta_tolerance_ms == 0.5
    with pytest.raises(Exception):  # noqa: B017 — frozen dataclass는 FrozenInstanceError
        OFFICIAL_PROFILE.target_p95_ms = 999.0  # type: ignore[misc]


@pytest.mark.parametrize(
    "field,value",
    [
        ("target_p95_ms", True),
        ("target_p95_ms", 0.0),
        ("target_p95_ms", -1.0),
        ("target_p95_ms", float("nan")),
        ("min_sample_count", True),
        ("min_sample_count", 0),
        ("min_sample_count", -5),
        ("delta_tolerance_ms", True),
        ("delta_tolerance_ms", -0.1),
        ("delta_tolerance_ms", float("nan")),
        ("delta_tolerance_ms", float("inf")),
        ("profile_id", ""),
        ("profile_id", "   "),
    ],
)
def test_acceptance_profile_rejects_invalid_fields(field: str, value: object) -> None:
    kwargs = {
        "profile_id": "exploratory-adhoc",
        "target_p95_ms": 50.0,
        "min_sample_count": 100,
        "delta_tolerance_ms": 0.5,
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        AcceptanceProfile(**kwargs)  # type: ignore[arg-type]


def test_exploratory_profile_id_differs_from_official() -> None:
    assert OFFICIAL_PROFILE.profile_id != EXPLORATORY_PROFILE_ID


# ── evaluate_evidence — 증거 무결성 게이트 (P0-2) ───────────────────────────


def _valid_single_session_result(n: int = 100) -> FrameTelemetryLoadResult:
    lines = _lines_for_session(n=n, session_id="SESS-1", aircraft_sn="SN-1")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "in.jsonl"
        _write_jsonl(path, lines)
        return load_frame_telemetry_jsonl(path)


def test_evaluate_evidence_valid_for_clean_single_session() -> None:
    status, reasons = evaluate_evidence(_valid_single_session_result())
    assert status is EvidenceStatus.VALID
    assert reasons == ()


def test_evaluate_evidence_invalid_when_zero_samples() -> None:
    status, reasons = evaluate_evidence(_valid_single_session_result(n=0))
    assert status is EvidenceStatus.INVALID
    assert any("표본이 0건" in r for r in reasons)


# ── B1~B3: 공식 profile CLI 완화 불가 ────────────────────────────────────────


def _official_pass_file(tmp_path: Path) -> Path:
    path = tmp_path / "official_pass.jsonl"
    lines = _lines_for_session(n=100, session_id="SESS-OK", aircraft_sn="SN-OK", delta_ms=10.0)
    _write_jsonl(path, lines)
    return path


def test_B1_official_target_override_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _official_pass_file(tmp_path)
    rc = main(["summarize", "--in", str(path), "--target-p95-ms", "100000"])
    captured = capsys.readouterr()
    assert rc != 0
    assert "완화할 수 없다" in captured.err
    assert '"acceptance_status": "PASS"' not in captured.out


def test_B2_official_min_sample_count_override_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _official_pass_file(tmp_path)
    for bad_value in ("1", "0"):
        rc = main(["summarize", "--in", str(path), "--min-sample-count", bad_value])
        captured = capsys.readouterr()
        assert rc != 0
        assert "완화할 수 없다" in captured.err


def test_B3_official_delta_tolerance_override_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _official_pass_file(tmp_path)
    for bad_value in ("inf", "nan"):
        rc = main(["summarize", "--in", str(path), "--delta-tolerance-ms", bad_value])
        captured = capsys.readouterr()
        assert rc != 0
        assert "완화할 수 없다" in captured.err


# ── B4: rejected 줄 존재 시 잔여 유효표본만으로 PASS 불가 ───────────────────


def test_B4_rejected_line_blocks_official_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "forged.jsonl"
    lines = _lines_for_session(n=100, session_id="SESS-F", aircraft_sn="SN-F", delta_ms=10.0)
    forged = json.dumps(
        _sample(
            sample_index=100,
            session_id="SESS-F",
            aircraft_sn="SN-F",
            frame_ts=FROZEN_UTC,
            telemetry_ts=FROZEN_UTC - timedelta(milliseconds=500),
            delta_ms=0.0,  # 위조
        )
    )
    _write_jsonl(path, [*lines, forged])

    rc = main(["summarize", "--in", str(path)])
    captured = capsys.readouterr()
    assert rc == 0
    result = json.loads(captured.out)
    assert result["rejected_line_count"] == 1
    assert result["evidence_status"] == "INVALID"
    assert result["acceptance_status"] != "PASS"
    assert result["reason_code"] == "EVIDENCE_INVALID"


# ── B5/B6: 세션/기체 혼합 → EVIDENCE INVALID ────────────────────────────────


def test_B5_mixed_session_id_marks_evidence_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "mixed_session.jsonl"
    lines_a = _lines_for_session(
        n=100, session_id="SESS-A", aircraft_sn="SN-SAME", start_index=0
    )
    lines_b = _lines_for_session(
        n=100, session_id="SESS-B", aircraft_sn="SN-SAME", start_index=100
    )
    _write_jsonl(path, [*lines_a, *lines_b])

    rc = main(["summarize", "--in", str(path)])
    captured = capsys.readouterr()
    assert rc == 0
    result = json.loads(captured.out)
    assert result["rejected_line_count"] == 0  # 줄 자체는 모두 유효 파싱됨
    assert result["evidence_status"] == "INVALID"
    assert result["acceptance_status"] != "PASS"
    assert sorted(result["session_ids_observed"]) == ["SESS-A", "SESS-B"]


def test_B6_mixed_aircraft_sn_marks_evidence_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "mixed_aircraft.jsonl"
    lines_a = _lines_for_session(
        n=100, session_id="SESS-SAME", aircraft_sn="SN-A", start_index=0
    )
    lines_b = _lines_for_session(
        n=100, session_id="SESS-SAME", aircraft_sn="SN-B", start_index=100
    )
    _write_jsonl(path, [*lines_a, *lines_b])

    rc = main(["summarize", "--in", str(path)])
    captured = capsys.readouterr()
    assert rc == 0
    result = json.loads(captured.out)
    assert result["evidence_status"] == "INVALID"
    assert result["acceptance_status"] != "PASS"
    assert sorted(result["aircraft_sns_observed"]) == ["SN-A", "SN-B"]


# ── B7/B8/B9: sample_index 규칙 위반 → 공식 PASS 불가 ───────────────────────


def test_B7_index_gap_blocks_official_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "gap.jsonl"
    lines = []
    for idx in (0, 1, 3):
        frame_ts = FROZEN_UTC + timedelta(seconds=idx)
        telemetry_ts = frame_ts - timedelta(milliseconds=10)
        lines.append(
            json.dumps(
                _sample(
                    sample_index=idx,
                    session_id="SESS-GAP",
                    aircraft_sn="SN-GAP",
                    frame_ts=frame_ts,
                    telemetry_ts=telemetry_ts,
                )
            )
        )
    _write_jsonl(path, lines)

    rc = main(["summarize", "--in", str(path)])
    result = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert result["evidence_status"] == "INVALID"
    assert result["acceptance_status"] != "PASS"
    assert any("gap" in r for r in result["evidence_reasons"])


def test_B8_index_not_starting_at_zero_blocks_official_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "start1.jsonl"
    lines = _lines_for_session(
        n=100, session_id="SESS-START1", aircraft_sn="SN-START1", start_index=1
    )
    _write_jsonl(path, lines)

    rc = main(["summarize", "--in", str(path)])
    result = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert result["evidence_status"] == "INVALID"
    assert result["acceptance_status"] != "PASS"
    assert any("0부터 시작하지 않는다" in r for r in result["evidence_reasons"])


def test_B9_duplicate_index_blocks_official_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "dup.jsonl"
    lines = _lines_for_session(n=100, session_id="SESS-DUP", aircraft_sn="SN-DUP")
    dup = json.dumps(
        _sample(
            sample_index=0,  # 중복
            session_id="SESS-DUP",
            aircraft_sn="SN-DUP",
            frame_ts=FROZEN_UTC + timedelta(seconds=999),
        )
    )
    _write_jsonl(path, [*lines, dup])

    rc = main(["summarize", "--in", str(path)])
    result = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert result["rejected_line_count"] == 1
    assert result["evidence_status"] == "INVALID"
    assert result["acceptance_status"] != "PASS"


# ── B10: target/min/tolerance 인자 검증 (bool·음수·0·NaN·Inf 거부) ──────────


def test_B10_exploratory_cli_rejects_invalid_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _official_pass_file(tmp_path)
    for bad in ("0", "-5", "nan"):
        rc = main(
            ["summarize", "--in", str(path), "--mode", "exploratory", "--target-p95-ms", bad]
        )
        assert rc != 0
        assert "오류" in capsys.readouterr().err


def test_B10_exploratory_cli_rejects_invalid_min_sample_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _official_pass_file(tmp_path)
    for bad in ("0", "-1"):
        rc = main(
            ["summarize", "--in", str(path), "--mode", "exploratory", "--min-sample-count", bad]
        )
        assert rc != 0
        assert "오류" in capsys.readouterr().err


def test_B10_exploratory_cli_rejects_invalid_delta_tolerance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _official_pass_file(tmp_path)
    for bad in ("-1", "nan", "inf"):
        rc = main(
            ["summarize", "--in", str(path), "--mode", "exploratory", "--delta-tolerance-ms", bad]
        )
        assert rc != 0
        assert "오류" in capsys.readouterr().err


def test_B10_validate_helpers_reject_bool_directly() -> None:
    with pytest.raises(ValueError):
        validate_positive_int(True, name="min_sample_count")
    with pytest.raises(ValueError):
        validate_finite_positive(True, name="target_p95_ms")
    with pytest.raises(ValueError):
        validate_finite_nonnegative(True, name="delta_tolerance_ms")


# ── B11: exploratory 모드는 어떤 값에도 PASS/VERIFIED 근거 미출력 ───────────


def test_B11_exploratory_never_emits_pass_even_when_target_met(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _official_pass_file(tmp_path)  # p95=10ms <= 50ms, 통계상으론 "통과"할 데이터

    rc = main(["summarize", "--in", str(path), "--mode", "exploratory"])
    result = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert result["acceptance_status"] is None
    assert result["exploratory_meets_target"] is True  # 통계는 통과했지만
    assert "PASS" not in json.dumps(result["acceptance_status"])
    assert result["acceptance_profile_id"] == EXPLORATORY_PROFILE_ID
    assert result["acceptance_profile_id"] != OFFICIAL_PROFILE.profile_id
    assert "VERIFIED" in result["notice"]
    assert "근거" in result["notice"]


def test_B11_judge_exploratory_has_no_acceptance_status_concept() -> None:
    result = _valid_single_session_result(n=100)
    profile = AcceptanceProfile(
        profile_id=EXPLORATORY_PROFILE_ID,
        target_p95_ms=50.0,
        min_sample_count=100,
        delta_tolerance_ms=0.5,
    )
    judgement = judge_exploratory(result, profile=profile)
    assert not hasattr(judgement, "acceptance_status")
    assert judgement.meets_target is True


# ── B12~B15: 정상 official 판정 (evidence VALID 경로) ───────────────────────


def test_B12_official_pass_with_100_valid_samples_under_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "pass.jsonl"
    _write_jsonl(
        path,
        _lines_for_session(n=100, session_id="SESS-PASS", aircraft_sn="SN-PASS", delta_ms=10.0),
    )
    rc = main(["summarize", "--in", str(path)])
    result = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert result["evidence_status"] == "VALID"
    assert result["measurement_status"] == "MEASURED"
    assert result["acceptance_status"] == "PASS"
    assert result["reason_code"] == "OK"


def test_B13_official_fail_with_100_valid_samples_over_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "fail.jsonl"
    _write_jsonl(
        path,
        _lines_for_session(n=100, session_id="SESS-FAIL", aircraft_sn="SN-FAIL", delta_ms=80.0),
    )
    rc = main(["summarize", "--in", str(path)])
    result = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert result["evidence_status"] == "VALID"
    assert result["measurement_status"] == "MEASURED"
    assert result["acceptance_status"] == "FAIL"
    assert result["reason_code"] == "REQUIREMENT_NOT_MET"


def test_B14_official_insufficient_samples_between_1_and_99(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "insufficient.jsonl"
    _write_jsonl(
        path,
        _lines_for_session(n=50, session_id="SESS-FEW", aircraft_sn="SN-FEW", delta_ms=10.0),
    )
    rc = main(["summarize", "--in", str(path)])
    result = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert result["evidence_status"] == "VALID"
    assert result["measurement_status"] == "MEASURED"
    assert result["acceptance_status"] == "INSUFFICIENT_SAMPLES"
    assert result["reason_code"] == "INSUFFICIENT_SAMPLES"


def test_B15_official_not_measured_with_zero_samples(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    rc = main(["summarize", "--in", str(path)])
    result = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert result["measurement_status"] == "NOT_MEASURED"
    assert result["acceptance_status"] is None
    assert result["reason_code"] == "NOT_MEASURED"


# ── B16: Summary digest·profile·session 메타가 실제 입력과 일치 ────────────


def test_B16_summary_metadata_matches_actual_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "meta.jsonl"
    _write_jsonl(
        path,
        _lines_for_session(n=100, session_id="SESS-META", aircraft_sn="SN-META", delta_ms=10.0),
    )
    expected_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    rc = main(["summarize", "--in", str(path)])
    result = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert result["input_sha256"] == expected_sha256
    assert result["acceptance_profile_id"] == OFFICIAL_PROFILE.profile_id
    assert result["profile_target_p95_ms"] == OFFICIAL_PROFILE.target_p95_ms
    assert result["profile_min_sample_count"] == OFFICIAL_PROFILE.min_sample_count
    assert result["profile_delta_tolerance_ms"] == OFFICIAL_PROFILE.delta_tolerance_ms
    assert result["session_id"] == "SESS-META"
    assert result["aircraft_sn"] == "SN-META"
    assert result["sample_index_first"] == 0
    assert result["sample_index_last"] == 99
    assert result["valid_sample_count"] == 100
    assert result["rejected_line_count"] == 0


# ── judge_official — 공식 profile binding (최종 재검토 P0, 2026-07-28) ──────


def _official_load(n: int = 100) -> FrameTelemetryLoadResult:
    lines = _lines_for_session(n=n, session_id="SESS-1", aircraft_sn="SN-1")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "in.jsonl"
        _write_jsonl(path, lines)
        return load_official_evidence(path)


def test_judge_official_rejects_profile_injection_entirely() -> None:
    """[반증 1·2] 공식 ID 를 단 완화 profile 을 전달할 **인자 자체가 없다** —
    같은 ID 든 다른 ID 든, 어떤 profile 주입도 시그니처 차원에서 불가."""
    forged = AcceptanceProfile(
        profile_id=OFFICIAL_PROFILE.profile_id,  # 공식 ID 위장
        target_p95_ms=100000.0,
        min_sample_count=1,
        delta_tolerance_ms=100000.0,
    )
    with pytest.raises(TypeError):
        judge_official(_official_load(), profile=forged)  # type: ignore[call-arg]


def test_relaxed_tolerance_load_rejected_by_official_judge() -> None:
    """[반증 3] relaxed tolerance 로 로드한 결과는 provenance binding 으로 INVALID."""
    lines = _lines_for_session(n=100, session_id="SESS-1", aircraft_sn="SN-1")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "in.jsonl"
        _write_jsonl(path, lines)
        relaxed = load_exploratory_evidence(path, delta_tolerance_ms=100000.0)
    judgement = judge_official(relaxed)
    assert judgement.evidence_status is EvidenceStatus.INVALID
    assert judgement.acceptance_status is AcceptanceStatus.FAIL
    assert judgement.reason_code is AcceptanceReasonCode.EVIDENCE_INVALID


def test_exploratory_load_rejected_by_official_judge_even_with_official_tolerance() -> None:
    """[반증 4] tolerance 값이 우연히 공식과 같아도 exploratory provenance 는 INVALID
    — 공식 증거는 load_official_evidence 경로로만 만들어진다."""
    lines = _lines_for_session(n=100, session_id="SESS-1", aircraft_sn="SN-1")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "in.jsonl"
        _write_jsonl(path, lines)
        exploratory = load_exploratory_evidence(
            path, delta_tolerance_ms=OFFICIAL_PROFILE.delta_tolerance_ms
        )
    judgement = judge_official(exploratory)
    assert judgement.evidence_status is EvidenceStatus.INVALID


def test_official_evidence_passes_normally() -> None:
    """[반증 5] 정상 공식 로드 증거는 기존 PASS 경로 유지."""
    judgement = judge_official(_official_load(n=100))
    assert judgement.evidence_status is EvidenceStatus.VALID
    assert judgement.acceptance_status is AcceptanceStatus.PASS


def test_official_evidence_fail_and_insufficient_paths_preserved() -> None:
    """[반증 5 계속] FAIL·INSUFFICIENT 경로도 공식 로드에서 그대로 동작."""
    insufficient = judge_official(_official_load(n=50))
    assert insufficient.evidence_status is EvidenceStatus.VALID
    assert insufficient.acceptance_status is AcceptanceStatus.INSUFFICIENT_SAMPLES


# ── build_parser 기본값 스모크 (CLI 구조 확인) ──────────────────────────────


def test_build_parser_summarize_mode_default_is_official() -> None:
    parser = build_parser()
    args = parser.parse_args(["summarize", "--in", "x.jsonl"])
    assert args.mode == "official"
    assert args.target_p95_ms is None
    assert args.min_sample_count is None
    assert args.delta_tolerance_ms is None


def test_default_delta_tolerance_constant_matches_official_profile() -> None:
    # 우연의 일치가 아니라 의도된 것임을 문서화하는 스모크 — 값이 갈라지면
    # 모듈 docstring의 "숫자는 같아도 의미가 다르다" 설명을 갱신해야 한다.
    assert OFFICIAL_PROFILE.delta_tolerance_ms == DEFAULT_DELTA_TOLERANCE_MS


# ── collect --source tap-log 변환 (ADR-KSI-009 D3, edge/psdk-tap NDJSON 계약) ──


def _tap_meta_line(
    *,
    anchor_mono_ns: int = 0,
    anchor_wall_utc: str = "2026-08-04T00:00:00Z",
    frame_sensor_ts: bool = True,
    telemetry_sensor_ts: bool = True,
    sensor_us_domain: str | None = "host_monotonic_us",
) -> str:
    payload: dict[str, object] = {
        "type": "meta",
        "tap_version": 1,
        "psdk_version": "1.0.0",
        "started_at_utc": anchor_wall_utc,
        "aircraft_sn": "SN-TAP",
        "clock": {"mono_ns": anchor_mono_ns, "wall_utc": anchor_wall_utc},
        "capabilities": {
            "frame_sensor_ts": frame_sensor_ts,
            "telemetry_sensor_ts": telemetry_sensor_ts,
        },
    }
    if sensor_us_domain is not None:
        payload["timestamp_contract"] = {"sensor_us_domain": sensor_us_domain}
    return json.dumps(payload)


def _tap_sample_line(
    *,
    i: int,
    frame_recv_mono_ns: int,
    telemetry_recv_mono_ns: int,
    frame_sensor_us: float | None = None,
    telemetry_sensor_us: float | None = None,
    frame_sensor_timestamp_raw_u64: str | None = None,
) -> str:
    return json.dumps(
        {
            "type": "sample",
            "i": i,
            "frame": {
                "recv_mono_ns": frame_recv_mono_ns,
                "sensor_us": frame_sensor_us,
                "sensor_timestamp_raw_u64": frame_sensor_timestamp_raw_u64,
            },
            "telemetry": {
                "recv_mono_ns": telemetry_recv_mono_ns,
                "sensor_us": telemetry_sensor_us,
            },
            "pairing": {"strategy": "nearest", "gap_ns": 0},
        }
    )


def test_convert_tap_log_recv_basis_monotonic_to_utc_is_correct(tmp_path: Path) -> None:
    """단조시계(ns)→UTC 환산이 meta.clock 앵커를 기준으로 정확한가."""
    path = tmp_path / "tap.ndjson"
    lines = [
        _tap_meta_line(anchor_mono_ns=0, anchor_wall_utc="2026-08-04T00:00:00Z"),
        _tap_sample_line(
            i=0, frame_recv_mono_ns=0, telemetry_recv_mono_ns=5_000_000
        ),  # telemetry가 frame보다 5ms 늦게 "수신"
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    samples = convert_tap_log_to_samples(
        path, session_id="SESS-TAP", aircraft_sn="SN-TAP", timestamp_basis="recv"
    )
    assert len(samples) == 1
    s = samples[0]
    assert s.frame_timestamp_utc == "2026-08-04T00:00:00+00:00"
    assert s.telemetry_timestamp_utc == "2026-08-04T00:00:00.005000+00:00"
    assert s.delta_ms == pytest.approx(-5.0)
    assert s.timestamp_basis == "recv"


def test_convert_tap_log_sensor_basis_monotonic_to_utc_is_correct(tmp_path: Path) -> None:
    path = tmp_path / "tap.ndjson"
    lines = [
        _tap_meta_line(anchor_mono_ns=0, anchor_wall_utc="2026-08-04T00:00:00Z"),
        _tap_sample_line(
            i=0,
            frame_recv_mono_ns=0,
            telemetry_recv_mono_ns=0,
            frame_sensor_us=2_000.0,
            telemetry_sensor_us=7_000.0,
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    samples = convert_tap_log_to_samples(
        path, session_id="SESS-TAP", aircraft_sn="SN-TAP", timestamp_basis="sensor"
    )
    assert len(samples) == 1
    s = samples[0]
    assert s.frame_timestamp_utc == "2026-08-04T00:00:00.002000+00:00"
    assert s.telemetry_timestamp_utc == "2026-08-04T00:00:00.007000+00:00"
    assert s.delta_ms == pytest.approx(-5.0)
    assert s.timestamp_basis == "sensor"


def test_convert_tap_log_sensor_basis_fails_closed_on_capability_false(tmp_path: Path) -> None:
    path = tmp_path / "tap.ndjson"
    lines = [
        _tap_meta_line(frame_sensor_ts=False, telemetry_sensor_ts=True),
        _tap_sample_line(
            i=0,
            frame_recv_mono_ns=0,
            telemetry_recv_mono_ns=0,
            frame_sensor_us=1.0,
            telemetry_sensor_us=1.0,
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="fail-closed"):
        convert_tap_log_to_samples(
            path, session_id="S", aircraft_sn="A", timestamp_basis="sensor"
        )


def test_convert_tap_log_sensor_basis_fails_closed_on_unverified_raw_timestamp_domain(
    tmp_path: Path,
) -> None:
    """Perception raw timestamp가 존재해도 host monotonic domain으로 추정하지 않는다."""
    path = tmp_path / "tap.ndjson"
    lines = [
        _tap_meta_line(
            frame_sensor_ts=True,
            telemetry_sensor_ts=True,
            sensor_us_domain="unverified",
        ),
        _tap_sample_line(
            i=0,
            frame_recv_mono_ns=0,
            telemetry_recv_mono_ns=0,
            frame_sensor_us=1.0,
            telemetry_sensor_us=1.0,
            frame_sensor_timestamp_raw_u64="18446744073709551615",
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sensor_us_domain"):
        convert_tap_log_to_samples(
            path, session_id="S", aircraft_sn="A", timestamp_basis="sensor"
        )


def test_convert_tap_log_sensor_basis_fails_closed_without_timestamp_contract(
    tmp_path: Path,
) -> None:
    """v1 meta가 raw sensor field를 주장해도 normalized clock proof 없이는 거부한다."""
    path = tmp_path / "tap.ndjson"
    lines = [
        _tap_meta_line(
            frame_sensor_ts=True,
            telemetry_sensor_ts=True,
            sensor_us_domain=None,
        ),
        _tap_sample_line(
            i=0,
            frame_recv_mono_ns=0,
            telemetry_recv_mono_ns=0,
            frame_sensor_us=1.0,
            telemetry_sensor_us=1.0,
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="timestamp_contract"):
        convert_tap_log_to_samples(
            path, session_id="S", aircraft_sn="A", timestamp_basis="sensor"
        )


def test_convert_tap_log_sensor_basis_fails_closed_on_null_sensor_us(tmp_path: Path) -> None:
    """capability는 true인데 개별 표본의 sensor_us가 null이면 recv로 조용히
    대체하지 않고 중단한다."""
    path = tmp_path / "tap.ndjson"
    lines = [
        _tap_meta_line(frame_sensor_ts=True, telemetry_sensor_ts=True),
        _tap_sample_line(
            i=0,
            frame_recv_mono_ns=0,
            telemetry_recv_mono_ns=0,
            frame_sensor_us=None,
            telemetry_sensor_us=1.0,
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="fail-closed"):
        convert_tap_log_to_samples(
            path, session_id="S", aircraft_sn="A", timestamp_basis="sensor"
        )


def test_convert_tap_log_recv_basis_does_not_require_sensor_capability(tmp_path: Path) -> None:
    """--timestamp-basis recv는 capabilities가 전부 false여도(=sensor_us 전부 null) 동작한다."""
    path = tmp_path / "tap.ndjson"
    lines = [
        _tap_meta_line(frame_sensor_ts=False, telemetry_sensor_ts=False),
        _tap_sample_line(i=0, frame_recv_mono_ns=0, telemetry_recv_mono_ns=1_000_000),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    samples = convert_tap_log_to_samples(
        path, session_id="S", aircraft_sn="A", timestamp_basis="recv"
    )
    assert len(samples) == 1


def test_convert_tap_log_rejects_missing_meta(tmp_path: Path) -> None:
    path = tmp_path / "tap.ndjson"
    lines = [_tap_sample_line(i=0, frame_recv_mono_ns=0, telemetry_recv_mono_ns=0)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="meta"):
        convert_tap_log_to_samples(path, session_id="S", aircraft_sn="A", timestamp_basis="recv")


def test_convert_tap_log_rejects_sample_before_meta(tmp_path: Path) -> None:
    path = tmp_path / "tap.ndjson"
    lines = [
        _tap_sample_line(i=0, frame_recv_mono_ns=0, telemetry_recv_mono_ns=0),
        _tap_meta_line(),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="meta보다 먼저"):
        convert_tap_log_to_samples(path, session_id="S", aircraft_sn="A", timestamp_basis="recv")


def test_convert_tap_log_ignores_stat_records(tmp_path: Path) -> None:
    path = tmp_path / "tap.ndjson"
    lines = [
        _tap_meta_line(),
        _tap_sample_line(i=0, frame_recv_mono_ns=0, telemetry_recv_mono_ns=0),
        json.dumps({"type": "stat", "dropped": 0}),
        _tap_sample_line(
            i=1, frame_recv_mono_ns=1_000_000_000, telemetry_recv_mono_ns=1_000_000_000
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    samples = convert_tap_log_to_samples(
        path, session_id="S", aircraft_sn="A", timestamp_basis="recv"
    )
    assert [s.sample_index for s in samples] == [0, 1]


def test_convert_tap_log_rejects_unknown_record_type(tmp_path: Path) -> None:
    path = tmp_path / "tap.ndjson"
    lines = [_tap_meta_line(), json.dumps({"type": "bogus"})]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="알 수 없는"):
        convert_tap_log_to_samples(path, session_id="S", aircraft_sn="A", timestamp_basis="recv")


def _tap_log_for_official_pass(path: Path, *, n: int = 100) -> None:
    """official PASS 기준(표본 100개 이상, p95 ≤ 50ms)을 만족하는 tap-log를 만든다."""
    lines = [_tap_meta_line()]
    for i in range(n):
        base = i * 1_000_000_000  # 1초 간격
        lines.append(
            _tap_sample_line(
                i=i, frame_recv_mono_ns=base, telemetry_recv_mono_ns=base + 5_000_000
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_converted_recv_samples_pass_load_frame_telemetry_jsonl_validation(tmp_path: Path) -> None:
    """변환된 JSONL이 기존 load_frame_telemetry_jsonl 검증(timestamp 형식·delta
    tolerance 포함)을 그대로 통과해야 한다 — 통과 못 하면 변환 버그다."""
    tap_path = tmp_path / "tap.ndjson"
    _tap_log_for_official_pass(tap_path, n=100)

    out_path = tmp_path / "out.jsonl"
    for sample in convert_tap_log_to_samples(
        tap_path, session_id="SESS-CONV", aircraft_sn="SN-CONV", timestamp_basis="recv"
    ):
        append_sample_jsonl(out_path, sample)

    load_result = load_frame_telemetry_jsonl(
        out_path, delta_tolerance_ms=DEFAULT_DELTA_TOLERANCE_MS
    )
    assert load_result.rejected == ()
    assert len(load_result.samples) == 100
    assert all(s.timestamp_basis == "recv" for s in load_result.samples)


def test_collect_cli_source_tap_log_end_to_end_official_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI 전체 경로: collect --source tap-log → summarize --mode official PASS,
    summary에 timestamp_basis/notice가 전파되는지 확인."""
    tap_path = tmp_path / "tap.ndjson"
    _tap_log_for_official_pass(tap_path, n=100)
    out_path = tmp_path / "out.jsonl"

    rc = main(
        [
            "collect",
            "--source",
            "tap-log",
            "--tap-log",
            str(tap_path),
            "--session-id",
            "SESS-E2E",
            "--aircraft-sn",
            "SN-E2E",
            "--out",
            str(out_path),
            "--timestamp-basis",
            "recv",
        ]
    )
    capsys.readouterr()
    assert rc == 0
    assert out_path.exists()

    rc2 = main(["summarize", "--in", str(out_path)])
    result = json.loads(capsys.readouterr().out)
    assert rc2 == 0
    assert result["evidence_status"] == "VALID"
    assert result["acceptance_status"] == "PASS"
    assert result["timestamp_basis"] == "recv"
    assert result["timestamp_basis_observed"] == ["recv"]
    assert "센서 시각 정합" in result["timestamp_basis_notice"]


def test_collect_cli_source_tap_log_requires_tap_log_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "collect",
            "--source",
            "tap-log",
            "--session-id",
            "S",
            "--aircraft-sn",
            "A",
            "--out",
            str(tmp_path / "out.jsonl"),
            "--timestamp-basis",
            "recv",
        ]
    )
    captured = capsys.readouterr()
    assert rc != 0
    assert "--tap-log" in captured.err


def test_collect_cli_requires_timestamp_basis(tmp_path: Path) -> None:
    """--timestamp-basis는 required=True, 기본값 없음 — 무의식적 선택을 argparse
    레벨에서 차단한다."""
    with pytest.raises(SystemExit):
        main(
            [
                "collect",
                "--session-id",
                "S",
                "--aircraft-sn",
                "A",
                "--out",
                str(tmp_path / "out.jsonl"),
            ]
        )


def test_collect_cli_rejects_invalid_timestamp_basis_choice(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "collect",
                "--session-id",
                "S",
                "--aircraft-sn",
                "A",
                "--out",
                str(tmp_path / "out.jsonl"),
                "--timestamp-basis",
                "bogus",
            ]
        )


def test_collect_cli_default_source_is_psdk_and_still_not_implemented(tmp_path: Path) -> None:
    """--source 기본값(psdk)은 기존 NotImplementedError fail-closed 동작을 유지한다."""
    with pytest.raises(NotImplementedError):
        main(
            [
                "collect",
                "--session-id",
                "S",
                "--aircraft-sn",
                "A",
                "--out",
                str(tmp_path / "out.jsonl"),
                "--num-samples",
                "1",
                "--timestamp-basis",
                "recv",
            ]
        )


def test_summarize_timestamp_basis_fields_are_null_when_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """timestamp_basis 정보가 없는(구버전/psdk 경로) 기존 JSONL은 기존 계약대로
    null/빈 리스트를 낸다 — 새 필드가 기존 파일 로드를 깨지 않는다."""
    path = _official_pass_file(tmp_path)
    rc = main(["summarize", "--in", str(path)])
    result = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert result["timestamp_basis"] is None
    assert result["timestamp_basis_observed"] == []
    assert result["timestamp_basis_notice"] is None
