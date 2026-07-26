"""TimestampSet/TelemetryInterpolator 입력 검증 네거티브 (반증 리뷰 2026-07-26 P0, P0-2).

UTC epoch와 process-local monotonic 시간축을 혼동해 보간 결과에 존재하지 않는
provenance를 만들어내던 결함(:mod:`ksi_geo_core.timestamps` 모듈 docstring 참고)의
재발을 막는다.
"""

from __future__ import annotations

import math

import pytest
from ksi_geo_core.sync import SourceQuality, TelemetryInterpolator, TelemetrySample
from ksi_geo_core.timestamps import DerivedTimestamp, TimestampSet


def _sample(ts: TimestampSet, lat: float) -> TelemetrySample:
    return TelemetrySample(ts=ts, drone_lat=lat, source_quality=SourceQuality.FULL)


def test_receive_monotonic_does_not_affect_sync_ts_utc() -> None:
    """UTC/monotonic 혼합 거부 — receive_monotonic_s는 sync_ts_utc() 계산에 관여하지 않는다."""
    with_monotonic = TimestampSet(
        source_ts_utc=100.0, receive_ts_utc=100.1, receive_monotonic_s=999_999.0
    )
    without_monotonic = TimestampSet(
        source_ts_utc=100.0, receive_ts_utc=100.1, receive_monotonic_s=None
    )

    assert with_monotonic.sync_ts_utc() == without_monotonic.sync_ts_utc()


def test_interpolated_sample_ts_is_derived_not_fabricated_provenance() -> None:
    """보간 결과는 DerivedTimestamp — source/receive/monotonic provenance를 지어내지 않는다."""
    itp = TelemetryInterpolator(max_gap_s=3.0)
    itp.add(_sample(TimestampSet(source_ts_utc=0.0, receive_ts_utc=0.0), 37.5))
    itp.add(_sample(TimestampSet(source_ts_utc=2.0, receive_ts_utc=2.0), 37.6))

    result = itp.at(1.0)

    assert result.ok
    assert result.sample is not None
    assert isinstance(result.sample.ts, DerivedTimestamp)
    assert not hasattr(result.sample.ts, "receive_ts_utc")
    assert not hasattr(result.sample.ts, "receive_monotonic_s")
    assert result.sample.ts.synchronized_ts_utc == 1.0


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"source_ts_utc": math.nan, "receive_ts_utc": 1.0}, "source_ts_utc"),
        ({"source_ts_utc": 1.0, "receive_ts_utc": math.inf}, "receive_ts_utc"),
        (
            {"source_ts_utc": 1.0, "receive_ts_utc": 1.0, "capture_ts_utc": math.nan},
            "capture_ts_utc",
        ),
        (
            {"source_ts_utc": 1.0, "receive_ts_utc": 1.0, "receive_monotonic_s": math.inf},
            "receive_monotonic_s",
        ),
    ],
)
def test_nonfinite_timestamp_rejected(kwargs: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        TimestampSet(**kwargs)


def test_nonfinite_derived_timestamp_rejected() -> None:
    with pytest.raises(ValueError, match="synchronized_ts_utc"):
        DerivedTimestamp(synchronized_ts_utc=math.nan)


def test_nonpositive_max_gap_s_rejected() -> None:
    with pytest.raises(ValueError, match="max_gap_s"):
        TelemetryInterpolator(max_gap_s=0.0)
    with pytest.raises(ValueError, match="max_gap_s"):
        TelemetryInterpolator(max_gap_s=-1.0)


def test_nonpositive_buffer_size_rejected() -> None:
    with pytest.raises(ValueError, match="buffer_size"):
        TelemetryInterpolator(buffer_size=0)
    with pytest.raises(ValueError, match="buffer_size"):
        TelemetryInterpolator(buffer_size=-5)
