"""TelemetryInterpolator 골든 테스트 (P0-2, INV-023 강제 지점).

두 층으로 구성된다:

- ``ksi_correctness`` (이 파일 대부분): 선형/각도 보간·gap·경계 처리의 해석적 진리 —
  손으로 유도 가능한 값을 직접 assert한다.
- ``legacy_compat`` (파일 맨 아래): upstream Scout ``TelemetryInterpolator`` 를 실제
  실행해 캡처한 ``packages/test-vectors/vectors/legacy_compat/telemetry_interpolation.json``
  을 재생한다. Scout와 값이 같아야 하는 구간(범위 안 보간)은 동등성을, KSI가 의도적으로
  달라지는 구간(범위 밖·gap 초과 — INV-023)은 그 차이 자체를 assert한다
  (``sync.py`` 모듈 docstring "Scout 대비 의도적 차이" 참고).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from ksi_geo_core.calibration import CalibrationOffset, SensorLatencyProfile
from ksi_geo_core.sync import (
    InterpolationStatus,
    SourceQuality,
    TelemetryInterpolator,
    TelemetrySample,
)
from ksi_geo_core.timestamps import TimestampSet

VECTOR_PATH = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "test-vectors"
    / "vectors"
    / "legacy_compat"
    / "telemetry_interpolation.json"
)


def _sample(
    ts: float,
    *,
    lat: float | None = None,
    lon: float | None = None,
    alt_rel: float | None = None,
    heading: float | None = None,
    gimbal_yaw: float | None = None,
    rtk_fixed: bool = False,
    quality: SourceQuality = SourceQuality.PARTIAL,
) -> TelemetrySample:
    """테스트 편의 헬퍼: source_ts=capture_ts=ts로 두어 PPS 동기 전제를 그대로 쓴다."""
    return TelemetrySample(
        ts=TimestampSet(source_ts=ts, receive_ts=ts, monotonic_ts=ts, capture_ts=ts),
        drone_lat=lat,
        drone_lon=lon,
        altitude_rel_m=alt_rel,
        heading_deg=heading,
        gimbal_yaw_deg=gimbal_yaw,
        rtk_fixed=rtk_fixed,
        source_quality=quality,
    )


# ── 선형 보간 정확성 ──────────────────────────────────────────────────────────


def test_linear_interpolation_midpoint() -> None:
    itp = TelemetryInterpolator(max_gap_s=2.0)
    itp.add(_sample(0.0, lat=36.0000, alt_rel=40.0))
    itp.add(_sample(1.0, lat=36.0010, alt_rel=50.0))

    result = itp.at(0.5)

    assert result.status is InterpolationStatus.OK
    assert result.sample is not None
    assert abs(result.sample.drone_lat - 36.0005) < 1e-9  # type: ignore[operator]
    assert abs(result.sample.altitude_rel_m - 45.0) < 1e-9  # type: ignore[operator]
    assert result.gap_s == pytest.approx(1.0)


def test_linear_interpolation_nonmidpoint() -> None:
    itp = TelemetryInterpolator(max_gap_s=20.0)
    itp.add(_sample(10.0, lat=36.0, alt_rel=40.0))
    itp.add(_sample(20.0, lat=36.001, alt_rel=60.0))

    result = itp.at(13.0)  # t = 0.3

    assert result.status is InterpolationStatus.OK
    assert result.sample is not None
    assert abs(result.sample.drone_lat - 36.0003) < 1e-9  # type: ignore[operator]
    assert abs(result.sample.altitude_rel_m - 46.0) < 1e-9  # type: ignore[operator]


# ── 각도 wraparound (최단호) ──────────────────────────────────────────────────


def test_heading_wraparound_forward_through_zero() -> None:
    """179°→-179°(=181°)는 최단호로 2°만 지나 t=0.5에서 ±180° 경계에 온다."""
    itp = TelemetryInterpolator(max_gap_s=2.0)
    itp.add(_sample(0.0, heading=179.0))
    itp.add(_sample(1.0, heading=-179.0))

    result = itp.at(0.5)

    assert result.status is InterpolationStatus.OK
    assert result.sample is not None
    heading = result.sample.heading_deg
    assert heading is not None
    # 최단호 중간점은 180°(또는 부동소수 표현상 -180°와 동일한 지점)이어야 한다.
    assert abs(heading - 180.0) < 1e-6 or abs(heading - (-180.0)) < 1e-6


def test_heading_wraparound_backward_symmetric() -> None:
    """-170°→170°(=190°) 도 최단호로 0°를 지나며, 정방향 케이스와 대칭이어야 한다."""
    itp = TelemetryInterpolator(max_gap_s=2.0)
    itp.add(_sample(0.0, heading=-170.0))
    itp.add(_sample(1.0, heading=170.0))

    result = itp.at(0.5)

    assert result.status is InterpolationStatus.OK
    assert result.sample is not None
    heading = result.sample.heading_deg
    assert heading is not None
    assert abs(heading - 180.0) < 1e-6 or abs(heading - (-180.0)) < 1e-6


def test_gimbal_yaw_wraparound_shortest_arc_through_zero() -> None:
    """350°→10° 최단호는 0°를 지난다(340° 쪽이 아님) — gimbal_yaw도 heading과 동일 로직."""
    itp = TelemetryInterpolator(max_gap_s=2.0)
    itp.add(_sample(0.0, gimbal_yaw=350.0))
    itp.add(_sample(1.0, gimbal_yaw=10.0))

    result = itp.at(0.5)

    assert result.status is InterpolationStatus.OK
    assert result.sample is not None
    yaw = result.sample.gimbal_yaw_deg
    assert yaw is not None
    assert abs(yaw - 0.0) < 1e-6


# ── gap 초과 → GAP_EXCEEDED (INV-023 fail-closed) ────────────────────────────


def test_gap_exceeded_reports_status_and_actual_gap() -> None:
    itp = TelemetryInterpolator(max_gap_s=0.5)
    itp.add(_sample(0.0, lat=36.0))
    itp.add(_sample(5.0, lat=36.0))

    result = itp.at(2.5)

    assert result.status is InterpolationStatus.GAP_EXCEEDED
    assert result.sample is None  # 실패는 값을 주지 않는다 — 외삽 금지
    assert result.gap_s == pytest.approx(5.0)


def test_gap_within_threshold_still_interpolates() -> None:
    itp = TelemetryInterpolator(max_gap_s=0.5)
    itp.add(_sample(0.0, lat=36.0))
    itp.add(_sample(0.4, lat=36.001))

    result = itp.at(0.2)

    assert result.status is InterpolationStatus.OK
    assert result.sample is not None
    assert result.gap_s == pytest.approx(0.4)


# ── 범위 밖 → BEFORE/AFTER, 값 반환 없음 (외삽 금지 검증) ────────────────────


def test_before_first_sample_returns_no_value() -> None:
    itp = TelemetryInterpolator()
    itp.add(_sample(10.0, lat=36.0))
    itp.add(_sample(11.0, lat=36.001))

    result = itp.at(5.0)

    assert result.status is InterpolationStatus.BEFORE_FIRST_SAMPLE
    assert result.sample is None
    assert result.quality is None
    assert result.gap_s == pytest.approx(5.0)


def test_after_last_sample_returns_no_value() -> None:
    itp = TelemetryInterpolator()
    itp.add(_sample(10.0, lat=36.0))
    itp.add(_sample(11.0, lat=36.001))

    result = itp.at(20.0)

    assert result.status is InterpolationStatus.AFTER_LAST_SAMPLE
    assert result.sample is None
    assert result.quality is None
    assert result.gap_s == pytest.approx(9.0)


def test_exact_boundary_timestamp_is_ok_not_before() -> None:
    """쿼리 시각이 첫 샘플과 정확히 같으면 경계-포함(OK)이어야 한다 — BEFORE가 아니다."""
    itp = TelemetryInterpolator()
    itp.add(_sample(10.0, lat=36.0))
    itp.add(_sample(11.0, lat=36.001))

    result = itp.at(10.0)

    assert result.status is InterpolationStatus.OK
    assert result.sample is not None
    assert result.sample.drone_lat == pytest.approx(36.0)
    assert result.gap_s == pytest.approx(0.0)


# ── 빈 버퍼 ───────────────────────────────────────────────────────────────────


def test_empty_buffer_returns_no_samples() -> None:
    itp = TelemetryInterpolator()

    result = itp.at(0.0)

    assert result.status is InterpolationStatus.NO_SAMPLES
    assert result.sample is None


# ── 역순 삽입 ─────────────────────────────────────────────────────────────────


def test_out_of_order_insertion_same_result_as_sorted() -> None:
    sorted_itp = TelemetryInterpolator(max_gap_s=2.0)
    for ts in (0.0, 1.0, 2.0, 3.0, 4.0):
        sorted_itp.add(_sample(ts, lat=36.0 + ts * 0.001))

    shuffled_itp = TelemetryInterpolator(max_gap_s=2.0)
    for ts in (4.0, 1.0, 3.0, 0.0, 2.0):
        shuffled_itp.add(_sample(ts, lat=36.0 + ts * 0.001))

    for query in (0.5, 1.5, 2.5, 3.5):
        a = sorted_itp.at(query)
        b = shuffled_itp.at(query)
        assert a.status is b.status is InterpolationStatus.OK
        assert a.sample is not None and b.sample is not None
        assert a.sample.drone_lat == pytest.approx(b.sample.drone_lat)


# ── CalibrationOffset 적용 ────────────────────────────────────────────────────


def test_calibration_offset_shifts_time_axis() -> None:
    """CalibrationOffset(+10s) 적용 시, 미보정 좌표계 쿼리는 범위 밖이 되고
    보정된(+10s) 좌표계 쿼리만 성공해야 한다 — 오프셋이 실제로 add()/at() 정렬 키에
    적용되고 있음을 증명한다."""
    offset = CalibrationOffset(sensor_id="gimbal-1", time_offset_s=10.0, uncertainty_s=0.01)
    itp = TelemetryInterpolator(max_gap_s=2.0, calibration=offset)
    itp.add(_sample(0.0, lat=36.0))
    itp.add(_sample(1.0, lat=36.001))

    # 미보정 좌표계에서의 0.5는 이제 (10.5) 로 저장돼 있으므로 범위 밖(BEFORE)이다.
    uncalibrated = itp.at(0.5)
    assert uncalibrated.status is InterpolationStatus.BEFORE_FIRST_SAMPLE

    # 보정된 좌표계(원래 시각 + 10s)로 쿼리하면 정상 보간된다.
    calibrated = itp.at(10.5)
    assert calibrated.status is InterpolationStatus.OK
    assert calibrated.sample is not None
    assert abs(calibrated.sample.drone_lat - 36.0005) < 1e-9  # type: ignore[operator]


def test_calibration_offset_negative_direction() -> None:
    offset = CalibrationOffset(sensor_id="gimbal-1", time_offset_s=-3.0, uncertainty_s=0.0)
    itp = TelemetryInterpolator(max_gap_s=3.0, calibration=offset)
    itp.add(_sample(10.0, lat=36.0))
    itp.add(_sample(12.0, lat=36.002))

    result = itp.at(8.0)  # 10.0 - 3.0 + 1.0 = 8.0 → 원 시각 11.0 지점(t=0.5)에 해당

    assert result.status is InterpolationStatus.OK
    assert result.sample is not None
    assert abs(result.sample.drone_lat - 36.001) < 1e-9  # type: ignore[operator]


def test_sensor_latency_profile_estimates_capture_ts_when_missing() -> None:
    """capture_ts가 없으면 SensorLatencyProfile로 receive_ts에서 역추정한다."""
    profile = SensorLatencyProfile(sensor_id="osd-link", latency_s=0.2, uncertainty_s=0.05)
    itp = TelemetryInterpolator(max_gap_s=2.0, latency_profile=profile)
    # capture_ts=None → receive_ts(=1.0)에서 latency_s(0.2)만큼 거슬러 0.8로 정렬돼야 한다.
    lo = TelemetrySample(
        ts=TimestampSet(source_ts=1.0, receive_ts=1.0, monotonic_ts=1.0, capture_ts=None),
        drone_lat=36.0,
    )
    hi = TelemetrySample(
        ts=TimestampSet(source_ts=2.0, receive_ts=2.0, monotonic_ts=2.0, capture_ts=None),
        drone_lat=36.001,
    )
    itp.add(lo)
    itp.add(hi)

    result = itp.at(1.3)  # (0.8, 1.8) 구간의 중간점

    assert result.status is InterpolationStatus.OK
    assert result.sample is not None
    assert abs(result.sample.drone_lat - 36.0005) < 1e-9  # type: ignore[operator]


# ── 스레드 안전 ───────────────────────────────────────────────────────────────


def test_concurrent_add_and_at_no_corruption() -> None:
    """PORT: Scout test_sync_threadsafe.py 의 동시성 계약을 재확인한다."""
    itp = TelemetryInterpolator(buffer_size=100_000)
    n_per_writer = 500
    n_writers = 4
    errors: list[BaseException] = []
    stop = threading.Event()

    def writer(base: int) -> None:
        try:
            for i in range(n_per_writer):
                itp.add(_sample(float(base + i * n_writers), lat=float(base + i * n_writers)))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def reader() -> None:
        try:
            while not stop.is_set():
                itp.at(1234.5)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    writers = [threading.Thread(target=writer, args=(w,)) for w in range(n_writers)]
    readers = [threading.Thread(target=reader) for _ in range(3)]
    for r in readers:
        r.start()
    for w in writers:
        w.start()
    for w in writers:
        w.join()
    stop.set()
    for r in readers:
        r.join()

    assert not errors, f"동시 접근 중 예외 발생: {errors[:3]}"
    assert len(itp._ts) == len(itp._samples)  # noqa: SLF001
    assert len(itp._ts) == n_per_writer * n_writers  # noqa: SLF001


# ── legacy_compat: Scout 실행 캡처 벡터 재생 ─────────────────────────────────


def _load_vectors() -> dict[str, Any]:
    with VECTOR_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _sample_from_vector(entry: dict[str, Any]) -> TelemetrySample:
    ts = entry["timestamp_utc"]
    return TelemetrySample(
        ts=TimestampSet(source_ts=ts, receive_ts=ts, monotonic_ts=ts, capture_ts=ts),
        drone_lat=entry.get("drone_lat"),
        drone_lon=entry.get("drone_lon"),
        altitude_rel_m=entry.get("altitude_rel_m"),
        heading_deg=entry.get("heading_deg"),
        gimbal_yaw_deg=entry.get("gimbal_yaw_deg"),
        rtk_fixed=entry.get("rtk_fixed", False),
        gnss_accuracy_m=entry.get("gnss_accuracy_m"),
        source_quality=SourceQuality(entry.get("source_quality", "unavailable")),
    )


@pytest.mark.skipif(not VECTOR_PATH.exists(), reason="legacy_compat 벡터 파일이 아직 생성되지 않음")
def test_legacy_compat_vectors_replay() -> None:
    """Scout 실행 캡처 벡터를 KSI TelemetryInterpolator로 재생.

    ``tag == "ok_within_gap"`` 인 케이스는 Scout가 실제로 계산한 보간값과 동등해야
    한다(선형/각도 산술은 그대로 이식했으므로). ``tag == "gap_exceeds"`` 인 케이스는
    Scout는 DEGRADED 품질로 값을 반환하지만 KSI는 INV-023에 따라 GAP_EXCEEDED로
    거부해야 한다 — 이 차이 자체가 의도된 설계 개선이다(sync.py 모듈 docstring 참고).
    """
    vectors = _load_vectors()
    abs_tol = float(vectors["tolerance"]["abs"])

    for case in vectors["cases"]:
        case_input = case["input"]
        itp = TelemetryInterpolator(max_gap_s=case_input["config"]["max_gap_s"])
        for entry in case_input["add_sequence"]:
            itp.add(_sample_from_vector(entry["telemetry"]))

        result = itp.at(case_input["query_ts"])
        tag = case["tag"]

        if tag == "gap_exceeds":
            assert result.status is InterpolationStatus.GAP_EXCEEDED, case["id"]
            assert result.sample is None, case["id"]
            continue

        assert tag == "ok_within_gap", f"unknown vector tag: {tag}"
        assert result.status is InterpolationStatus.OK, case["id"]
        assert result.sample is not None, case["id"]

        scout_output = case["output"]
        assert scout_output is not None, case["id"]

        for field in ("drone_lat", "drone_lon", "altitude_rel_m"):
            expected = scout_output.get(field)
            actual = getattr(result.sample, field)
            if expected is None:
                assert actual is None, case["id"]
            else:
                assert actual is not None, case["id"]
                assert abs(actual - expected) <= abs_tol, (case["id"], field, actual, expected)

        for field in ("heading_deg", "gimbal_yaw_deg"):
            expected = scout_output.get(field)
            actual = getattr(result.sample, field)
            if expected is None:
                assert actual is None, case["id"]
            else:
                assert actual is not None, case["id"]
                # 각도는 wraparound 표현 차이(0 vs 360 등)가 있을 수 있어 mod 360 비교.
                diff = abs((actual - expected + 180.0) % 360.0 - 180.0)
                assert diff <= max(abs_tol, 1e-6), (case["id"], field, actual, expected)
