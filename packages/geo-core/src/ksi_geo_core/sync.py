"""센서 시간동기·텔레메트리 보간 (P0-2).

PORT: upstream Scout ``ksi_scout/dal/sync.py`` @42ccc0db (``TelemetryInterpolator``) —
버퍼 정렬(bisect 삽입, 역순 도착 허용)·선형 보간·각도(heading/gimbal_yaw) 최단호
보간·스레드 안전(lock) 로직을 이식했다. 아래 "Scout 대비 의도적 차이"는 그대로 옮기지
않고 바꾼 지점이다.

## 전제 — 재구현하지 않는 것

이 모듈은 **DJI PPS(Pulse-Per-Second) 하드웨어 동기가 이미 되어 있는 다중 센서**를
전제한다. 카메라/GPS/IMU 등 개별 센서 클록이 하드웨어 수준에서 공통 기준에 맞춰져 있다고
보고, 여러 독립 클록의 상대 드리프트를 실시간으로 추정·정렬하는 항공기급
Clock Synchronizer 를 여기서 소프트웨어로 재구현하지 않는다. 이 모듈이 실제로 다루는 건:

1. PPS 동기 후에도 남는 잔차 상수 오프셋 보정 (:class:`ksi_geo_core.calibration.CalibrationOffset`)
2. ``capture_ts_utc`` 를 못 주는 소스를 위한 파이프라인 지연 추정
   (:class:`ksi_geo_core.calibration.SensorLatencyProfile`)
3. 프레임 시각에 맞춘 텔레메트리 선형/각도 보간 (Scout PORT, 아래)

PPS 미지원 소스(예: 순수 RTMP 컨슈머 드론)에는 이 모듈의 정확도 보증이 성립하지 않는다 —
그런 소스는 Video-only/Geo-unaware 로 강등되어야 한다(Scout DAL 문서 §4.1과 동일 전제).

## Scout 대비 의도적 차이 (INV-023 — 외삽 금지·fail-closed 강제)

- **범위 밖 쿼리**: Scout ``at()`` 은 가장 가까운 샘플을 복사해 반환한다(상수 외삽에
  해당하는 동작). 여기서는 그 경로를 없애고 ``BEFORE_FIRST_SAMPLE``/``AFTER_LAST_SAMPLE``
  typed 실패를 반환한다 — 값을 주지 않는다.
- **gap 처리**: Scout 은 gap 이 ``max_gap_s*2`` 를 넘으면 DEGRADED 품질로 값은 그대로
  반환한다(연산은 계속). 여기서는 gap 이 ``max_gap_s`` 를 넘으면 ``GAP_EXCEEDED`` typed
  실패로 처리한다 — 신뢰 불가 보간 결과를 조용히 흘려보내지 않는다(fail-closed).
- **품질 병합**: Scout 은 보간 구간의 하위(lo) 샘플 품질만 본다. 여기서는 양끝 중 더
  낮은 신뢰도를 채택한다(낙관적 병합 금지).
- **경계 포함 여부**: 쿼리 시각이 버퍼의 첫/마지막 샘플 시각과 정확히 같으면(등호) 그
  샘플 자체를 ``OK`` 로 반환한다(Scout도 동일 값을 반환하지만 별도 분기 없이 "가장 가까운
  샘플" 경로로 우연히 맞아떨어진다 — 여기서는 명시적으로 경계-포함으로 다룬다).
"""

from __future__ import annotations

import math
import threading
from bisect import bisect_left
from dataclasses import dataclass
from enum import StrEnum

from ksi_geo_core.calibration import CalibrationOffset, SensorLatencyProfile
from ksi_geo_core.timestamps import DerivedTimestamp, SyncedTimestamp


class SourceQuality(StrEnum):
    """상위 Geo Engine 이 라이브/정밀 tier 를 선택하는 핵심 신호.

    PORT: Scout ``contracts/telemetry.py`` SourceQuality 이식(값·의미 동일).
    """

    FULL = "full"  # RTK 고정 등, 정밀 tier 가능
    PARTIAL = "partial"  # 단순 RTMP 등, 라이브 tier 까지
    DEGRADED = "degraded"  # 시각 동기화 오차 큼
    UNAVAILABLE = "unavailable"  # 텔레메트리 없음 (Video-only)


_QUALITY_RANK: dict[SourceQuality, int] = {
    SourceQuality.UNAVAILABLE: 0,
    SourceQuality.DEGRADED: 1,
    SourceQuality.PARTIAL: 2,
    SourceQuality.FULL: 3,
}


def _worse_quality(a: SourceQuality, b: SourceQuality) -> SourceQuality:
    """둘 중 더 낮은 신뢰도를 채택(낙관적 병합 금지)."""
    return a if _QUALITY_RANK[a] <= _QUALITY_RANK[b] else b


@dataclass(frozen=True)
class TelemetrySample:
    """시간동기된 텔레메트리 한 점.

    PORT: Scout ``NormalizedTelemetry`` 대응 — 단일 ``timestamp_utc: float`` 대신
    :class:`~ksi_geo_core.timestamps.SyncedTimestamp` (``TimestampSet`` 실제 수신 샘플
    또는 ``DerivedTimestamp`` 보간 파생 샘플)을 쓴다는 점이 유일한 구조적 차이다.
    """

    ts: SyncedTimestamp
    drone_lat: float | None = None  # WGS84 (EPSG:4326)
    drone_lon: float | None = None
    altitude_msl_m: float | None = None
    altitude_rel_m: float | None = None
    heading_deg: float | None = None  # 진북 기준, 최단호 보간
    gimbal_pitch_deg: float | None = None
    gimbal_yaw_deg: float | None = None  # 최단호 보간
    gimbal_roll_deg: float | None = None
    camera_fov_deg: float | None = None
    zoom_factor: float | None = None
    rtk_fixed: bool = False
    gnss_accuracy_m: float | None = None
    source_quality: SourceQuality = SourceQuality.UNAVAILABLE


class InterpolationStatus(StrEnum):
    """:class:`InterpolationResult` 의 성공/실패 사유. INV-023 강제의 핵심 타입."""

    OK = "ok"
    GAP_EXCEEDED = "gap_exceeded"  # 양쪽 최근접 샘플 간 gap이 max_gap_s 초과
    BEFORE_FIRST_SAMPLE = "before_first_sample"  # 쿼리 시각 < 버퍼의 첫 샘플 시각
    AFTER_LAST_SAMPLE = "after_last_sample"  # 쿼리 시각 > 버퍼의 마지막 샘플 시각
    NO_SAMPLES = "no_samples"  # 버퍼가 비어 있음


@dataclass(frozen=True)
class InterpolationResult:
    """보간 결과. 실패는 ``None`` 이 아니라 이 typed 값으로 표현한다(INV-023).

    ``status`` 가 :attr:`InterpolationStatus.OK` 일 때만 ``sample``/``quality`` 가 채워진다.
    그 외 상태는 값을 반환하지 않는다 — 외삽하지 않는다. ``gap_s`` 는 실패 사유 진단을
    위해 (가능하면) 항상 채운다: OK/GAP_EXCEEDED 는 보간 구간의 실제 간격, BEFORE/AFTER
    는 쿼리 시각과 버퍼 경계 사이의 거리.
    """

    status: InterpolationStatus
    query_ts: float
    sample: TelemetrySample | None = None
    quality: SourceQuality | None = None
    gap_s: float | None = None

    @property
    def ok(self) -> bool:
        return self.status is InterpolationStatus.OK


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_opt(a: float | None, b: float | None, t: float) -> float | None:
    if a is None or b is None:
        return None
    return _lerp(a, b, t)


def _lerp_angle_opt(a: float | None, b: float | None, t: float) -> float | None:
    """각도(도) 최단호 보간. PORT: Scout ``_lerp_angle_opt`` 동일 로직.

    350°→10° 는 0°를 지나는 20° 최단호를 택한다(340° 쪽이 아님).
    """
    if a is None or b is None:
        return None
    delta = ((b - a + 180.0) % 360.0) - 180.0
    return (a + delta * t) % 360.0


class TelemetryInterpolator:
    """타임스탬프 정렬 버퍼에 텔레메트리를 모으고, 임의 시각의 값을 보간한다.

    PORT: Scout ``TelemetryInterpolator`` 이식 + INV-023 강제(위 모듈 docstring의
    "Scout 대비 의도적 차이" 참고) + :class:`TimestampSet`/``CalibrationOffset``/
    ``SensorLatencyProfile`` 을 통한 시간동기 확장.

    스레드 안전: MQTT 콜백 스레드(``add``)와 소비 스레드(``at``)가 같은 버퍼를 동시에
    만질 수 있다. Lock 없이는 ``add`` 의 두 리스트(``_ts``/``_samples``) 삽입 사이에
    ``at`` 이 끼어들어 인덱스가 어긋난다. Lock 안에서는 필요한 값만 지역변수로 스냅샷하고,
    보간 연산(나눗셈·lerp)은 Lock 밖에서 한다 — 콜백 스레드를 오래 막지 않기 위해서다.
    """

    def __init__(
        self,
        *,
        max_gap_s: float = 0.5,
        buffer_size: int = 600,
        latency_profile: SensorLatencyProfile | None = None,
        calibration: CalibrationOffset | None = None,
    ) -> None:
        if not (math.isfinite(max_gap_s) and max_gap_s > 0):
            raise ValueError(f"max_gap_s는 finite한 양수여야 한다 (got {max_gap_s!r})")
        if isinstance(buffer_size, bool) or not isinstance(buffer_size, int) or buffer_size <= 0:
            raise ValueError(f"buffer_size는 양의 정수(bool 제외)여야 한다 (got {buffer_size!r})")
        self._max_gap = max_gap_s
        self._buffer_size = buffer_size
        self._latency_profile = latency_profile
        self._calibration = calibration
        self._samples: list[TelemetrySample] = []
        self._ts: list[float] = []
        self._lock = threading.Lock()

    def add(self, sample: TelemetrySample) -> None:
        """샘플을 정렬 버퍼에 삽입한다. 역순/뒤섞여 도착해도 시각 순서를 유지한다.

        정렬·삽입 키는 ``sample.ts.sync_ts_utc(...)`` — capture_ts_utc 우선 해석 +
        CalibrationOffset 적용까지 끝난 최종 UTC 시각이다(``TimestampSet.sync_ts_utc`` 참고).
        """
        ts = sample.ts.sync_ts_utc(
            latency_profile=self._latency_profile, calibration=self._calibration
        )
        with self._lock:
            # bisect 로 시각 순서 유지 → 늦게/역순으로 도착한 샘플도 올바른 위치에 삽입.
            pos = bisect_left(self._ts, ts)
            self._ts.insert(pos, ts)
            self._samples.insert(pos, sample)
            # 버퍼 상한 초과 시 오래된 것부터 제거
            while len(self._ts) > self._buffer_size:
                self._ts.pop(0)
                self._samples.pop(0)

    def at(self, query_ts: float) -> InterpolationResult:
        """쿼리 시각에 맞춘 텔레메트리를 보간한다.

        버퍼가 비면 ``NO_SAMPLES``. 쿼리 시각이 버퍼 범위 밖이면 ``BEFORE_FIRST_SAMPLE``/
        ``AFTER_LAST_SAMPLE`` — 외삽하지 않는다(INV-023). 범위 안이면 선형/각도 보간하되,
        양쪽 최근접 샘플 간 gap이 ``max_gap_s`` 를 넘으면 ``GAP_EXCEEDED``.
        """
        with self._lock:
            n = len(self._ts)
            if n == 0:
                return InterpolationResult(status=InterpolationStatus.NO_SAMPLES, query_ts=query_ts)

            if query_ts < self._ts[0]:
                gap = self._ts[0] - query_ts
                return InterpolationResult(
                    status=InterpolationStatus.BEFORE_FIRST_SAMPLE, query_ts=query_ts, gap_s=gap
                )
            if query_ts > self._ts[-1]:
                gap = query_ts - self._ts[-1]
                return InterpolationResult(
                    status=InterpolationStatus.AFTER_LAST_SAMPLE, query_ts=query_ts, gap_s=gap
                )

            pos = bisect_left(self._ts, query_ts)
            if pos < n and self._ts[pos] == query_ts:
                # 쿼리 시각이 버퍼 안 어떤 샘플과 정확히 같다 — 경계(첫/끝) 포함, 보간 불필요.
                sample = self._samples[pos]
                return InterpolationResult(
                    status=InterpolationStatus.OK,
                    query_ts=query_ts,
                    sample=sample,
                    quality=sample.source_quality,
                    gap_s=0.0,
                )

            # 0 < pos < n 이 보장된다: query_ts 는 ts[0]과 ts[-1] 사이이고 어떤 샘플과도
            # 정확히 일치하지 않으므로, pos-1/pos 둘 다 유효한 이웃 인덱스다.
            lo, hi = self._samples[pos - 1], self._samples[pos]
            lo_ts, hi_ts = self._ts[pos - 1], self._ts[pos]

        span = hi_ts - lo_ts
        if span <= 0 or span > self._max_gap:
            # span<=0 은 동일/역행 타임스탬프(데이터 이상) — 보간 신뢰 불가로 같이 처리.
            return InterpolationResult(
                status=InterpolationStatus.GAP_EXCEEDED, query_ts=query_ts, gap_s=span
            )

        t = (query_ts - lo_ts) / span
        quality = _worse_quality(lo.source_quality, hi.source_quality)
        interpolated = TelemetrySample(
            # 파생 샘플 — 실제 수신 이벤트가 없으므로 source/receive/monotonic
            # provenance를 지어내지 않는다(DerivedTimestamp, 반증 리뷰 2026-07-26 P0).
            ts=DerivedTimestamp(synchronized_ts_utc=query_ts),
            drone_lat=_lerp_opt(lo.drone_lat, hi.drone_lat, t),
            drone_lon=_lerp_opt(lo.drone_lon, hi.drone_lon, t),
            altitude_msl_m=_lerp_opt(lo.altitude_msl_m, hi.altitude_msl_m, t),
            altitude_rel_m=_lerp_opt(lo.altitude_rel_m, hi.altitude_rel_m, t),
            heading_deg=_lerp_angle_opt(lo.heading_deg, hi.heading_deg, t),
            gimbal_pitch_deg=_lerp_opt(lo.gimbal_pitch_deg, hi.gimbal_pitch_deg, t),
            gimbal_yaw_deg=_lerp_angle_opt(lo.gimbal_yaw_deg, hi.gimbal_yaw_deg, t),
            gimbal_roll_deg=_lerp_opt(lo.gimbal_roll_deg, hi.gimbal_roll_deg, t),
            camera_fov_deg=_lerp_opt(lo.camera_fov_deg, hi.camera_fov_deg, t),
            zoom_factor=_lerp_opt(lo.zoom_factor, hi.zoom_factor, t),
            rtk_fixed=lo.rtk_fixed and hi.rtk_fixed,
            gnss_accuracy_m=_lerp_opt(lo.gnss_accuracy_m, hi.gnss_accuracy_m, t),
            source_quality=quality,
        )
        return InterpolationResult(
            status=InterpolationStatus.OK,
            query_ts=query_ts,
            sample=interpolated,
            quality=quality,
            gap_s=span,
        )
