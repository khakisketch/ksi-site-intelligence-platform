"""P0-6 재생용 합성 fixture — 실영상 없이 결정적 텔레메트리+검출 좌표만 담는다.

대용량 실기록물은 git-lfs/외부 스토리지로 별도 관리한다(Phase 0는 이 작고 결정적인
합성 fixture로 재현성 게이트만 충족한다).
"""

from __future__ import annotations

from harness import DetectionFrame, ReplayFixture
from ksi_domain.enums import Severity
from ksi_geo_core.sync import SourceQuality, TelemetrySample
from ksi_geo_core.timestamps import TimestampSet

_WIDTH, _HEIGHT = 1920, 1080
_NADIR_CENTER = (960.0, 540.0)


def _sample(ts: float, *, lat: float = 37.5, lon: float = 127.0) -> TelemetrySample:
    return TelemetrySample(
        ts=TimestampSet(source_ts_utc=ts, receive_ts_utc=ts, capture_ts_utc=ts),
        drone_lat=lat,
        drone_lon=lon,
        altitude_rel_m=100.0,
        heading_deg=0.0,
        gimbal_pitch_deg=-90.0,
        camera_fov_deg=84.0,
        zoom_factor=1.0,
        rtk_fixed=True,
        source_quality=SourceQuality.FULL,
    )


def confirmed_intrusion_fixture() -> ReplayFixture:
    """6개 연속 관측이 같은 지점을 가리켜 CONFIRMED_EVENT까지 도달하는 정상 경로.

    ``confirm_after_observations=5`` 이므로 5번째 관측에서 CONFIRMED_EVENT 진입,
    6번째는 종단 상태 유지(재전이 없음)를 확인하는 데 쓴다.
    """
    timestamps = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    samples = tuple(_sample(t) for t in timestamps)
    detections = tuple(
        DetectionFrame(frame_id=i, query_ts=t, u_px=_NADIR_CENTER[0], v_px=_NADIR_CENTER[1],
                        width=_WIDTH, height=_HEIGHT)
        for i, t in enumerate(timestamps)
    )
    return ReplayFixture(
        telemetry_samples=samples,
        detections=detections,
        event_type="PERSON_IN_HAZARD_ZONE",
        severity=Severity.HIGH,
        confirm_after_observations=5,
    )


def single_frame_fixture() -> ReplayFixture:
    """단일 프레임만 존재 — INV-022(단일 프레임 즉시확정 금지) 검증용.

    관측이 1건뿐이면 OBSERVATION에서 더 나아가지 않아야 한다(CANDIDATE 진입 조건은
    ``count >= 2``).
    """
    samples = (_sample(0.0),)
    detections = (
        DetectionFrame(frame_id=0, query_ts=0.0, u_px=_NADIR_CENTER[0], v_px=_NADIR_CENTER[1],
                        width=_WIDTH, height=_HEIGHT),
    )
    return ReplayFixture(
        telemetry_samples=samples,
        detections=detections,
        event_type="PERSON_IN_HAZARD_ZONE",
        severity=Severity.HIGH,
    )


def gap_exceeded_fixture() -> ReplayFixture:
    """중간에 텔레메트리 gap이 벌어져 한 프레임이 보간 실패로 drop되는 경우.

    telemetry는 0.0과 10.0에만 존재(gap=10s ≫ max_gap_s=0.5) — query_ts=5.0인 검출은
    ``GAP_EXCEEDED`` 로 drop되어야 한다(외삽 없음, INV-023).
    """
    samples = (_sample(0.0), _sample(10.0))
    detections = (
        DetectionFrame(frame_id=0, query_ts=0.0, u_px=_NADIR_CENTER[0], v_px=_NADIR_CENTER[1],
                        width=_WIDTH, height=_HEIGHT),
        DetectionFrame(frame_id=1, query_ts=5.0, u_px=_NADIR_CENTER[0], v_px=_NADIR_CENTER[1],
                        width=_WIDTH, height=_HEIGHT),
        DetectionFrame(frame_id=2, query_ts=10.0, u_px=_NADIR_CENTER[0], v_px=_NADIR_CENTER[1],
                        width=_WIDTH, height=_HEIGHT),
    )
    return ReplayFixture(
        telemetry_samples=samples,
        detections=detections,
        event_type="PERSON_IN_HAZARD_ZONE",
        severity=Severity.MEDIUM,
        max_gap_s=0.5,
    )


def inconsistent_position_fixture() -> ReplayFixture:
    """두 번째 관측이 첫 관측과 멀리 떨어져 DISMISSED로 귀결되는 경우(오탐 패턴)."""
    timestamps = [0.0, 1.0]
    # 두 번째 프레임은 드론이 다른 위치로 이동한 뒤 촬영 — anchor에서 매우 먼 지점.
    samples = (_sample(0.0, lat=37.5, lon=127.0), _sample(1.0, lat=37.6, lon=127.1))
    detections = tuple(
        DetectionFrame(frame_id=i, query_ts=t, u_px=_NADIR_CENTER[0], v_px=_NADIR_CENTER[1],
                        width=_WIDTH, height=_HEIGHT)
        for i, t in enumerate(timestamps)
    )
    return ReplayFixture(
        telemetry_samples=samples,
        detections=detections,
        event_type="PERSON_IN_HAZARD_ZONE",
        severity=Severity.MEDIUM,
    )
