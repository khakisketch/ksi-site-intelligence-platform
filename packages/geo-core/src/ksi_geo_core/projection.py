"""픽셀 → 지면 좌표 투영 — 평지 raycast 기준 구현 (P0-4).

PORT: upstream Scout ``ksi_scout/geo/projection.py`` @42ccc0db (``project_foot_point``) —
회전행렬 합성(``Rz_cw·Rx·R0·Rroll``)·핀홀 광선·z=0 평지 교차·confidence/오차반경 산출
로직을 그대로 이식했다(수식 불변, 타입만 typed 실패로 강화).

## 좌표계 규약 (Scout 부호 검산 그대로 계승)

- World = ENU 로컬 접평면(x=East, y=North, z=Up). 드론=(0,0,h), 지면 z=0 평지 가정.
- Camera = OpenCV 관습(x=right, y=down, z=forward), 이미지 y는 아래로 증가(부호 반전 금지).
- heading/gimbal_yaw: 진북 0, 시계방향 → ``_Rz_cw`` (sin 부호 뒤집힘).
- gimbal_pitch: 수평 0, nadir -90(아래로 음수) → ``_Rx``.
- 회전 합성: ``R = Rz_cw(ψ)·Rx(pitch)·R0·Rroll(φ)``, ``R0=[[1,0,0],[0,0,1],[0,-1,0]]``.

## KSI Site Intelligence 범위 — 이 모듈이 아닌 것

이 함수는 **평지(z=0) raycast 기준 구현**이다. Master PRD §10.4의 전체 파이프라인
(Terrain/Mesh/BIM Surface Raycast → 다중 시점 삼각측량 → covariance)의 첫 단계일 뿐이며,
이 단계 자체를 최종 SSOT로 오인하면 안 된다(KSI_PLATFORM_REUSE_AUDIT §2.4).

**ZoneLayer(폴리곤 내/외 판정)는 이 모듈의 책무가 아니다.** Scout ``LiveGeoProjector.project``의
zone 판정(INSIDE/OUTSIDE/NEAR_BOUNDARY/GEO_LOW_CONFIDENCE)은 Master PRD DEC-026·§12.6에 따라
"고정 정책구역 Fallback"으로 격하되고, 동적 위험은 장비 기구학 기반 Risk Field(Phase 3)로
대체될 예정이다 — 지금 이식하면 곧 버릴 코드를 만드는 셈이라 P0-4 범위에서 명시적으로
제외했다(``tests/golden/test_geo_core_projection.py`` 의 skip 사유 참고).

외삽 절대 금지: 광선이 지평선 위/평행이면 ``ABOVE_HORIZON`` (INV-023).
confidence 와 error_radius_m 은 별개로 산출·노출한다(둘 다 fail-closed 판단에 쓰이되
서로 다른 실패 모드를 표현한다).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from ksi_geo_core.frames import enu_to_wgs84
from ksi_geo_core.sync import TelemetrySample
from ksi_geo_core.uncertainty import composite_confidence, position_error_radius_m

_R0 = np.array([[1.0, 0, 0], [0, 0, 1.0], [0, -1.0, 0]])  # cam(x-r,y-d,z-f) → ENU 북향수평


def _rx(angle_rad: float) -> npt.NDArray[np.float64]:  # ENU East(x)축 회전(gimbal pitch)
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return np.array([[1.0, 0, 0], [0, c, -s], [0, s, c]])


def _rz_clockwise(angle_rad: float) -> npt.NDArray[np.float64]:  # 진북 시계방향(heading/yaw)
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return np.array([[c, s, 0], [-s, c, 0], [0, 0, 1.0]])


def _rroll(angle_rad: float) -> npt.NDArray[np.float64]:  # boresight 둘레(roll)
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


class ProjectionStatus(StrEnum):
    """:class:`ProjectionResult` 의 성공/실패 사유. 값은 PORT 원천(Scout ``GeoPoint.reason``)의
    문자열과 동일하게 맞춰 골든벡터 회귀 비교를 직접적으로 만든다."""

    OK = "ok"
    GEO_UNAVAILABLE_TELEMETRY = "geo_unavailable_telemetry"
    INVALID_ALTITUDE = "altitude"
    ABOVE_HORIZON = "horizon"
    INVALID_IMAGE_DIMENSIONS = "invalid_image_dimensions"
    INVALID_PIXEL = "invalid_pixel"
    INVALID_INTRINSICS = "invalid_intrinsics"
    NONFINITE_INPUT = "nonfinite_input"
    INVALID_GEO_RANGE = "invalid_geo_range"


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """투영 결과. 실패는 ``None`` 대신 이 typed 값(INV-023, P0-2 InterpolationResult와 동형)."""

    status: ProjectionStatus
    lat: float | None = None
    lon: float | None = None
    east_m: float | None = None
    north_m: float | None = None
    confidence: float = 0.0
    error_radius_m: float | None = None

    @property
    def ok(self) -> bool:
        return self.status is ProjectionStatus.OK


def _geo_capable(sample: TelemetrySample) -> bool:
    """PORT: Scout ``NormalizedTelemetry.geo_capable`` — 라이브 Geo 투영 최소 입력 충족 여부."""
    return (
        sample.drone_lat is not None
        and sample.drone_lon is not None
        and sample.altitude_rel_m is not None
        and sample.heading_deg is not None
        and sample.gimbal_pitch_deg is not None
    )


def project_foot_point(
    u_px: float,
    v_px: float,
    width: int,
    height: int,
    sample: TelemetrySample,
    *,
    default_fov_deg: float = 84.0,
    fov_is_diagonal: bool = False,
) -> ProjectionResult:
    """이미지 픽셀 (u,v) → 지면 (lat,lon) + confidence + 오차반경. 외삽 금지.

    PORT: Scout ``project_foot_point`` — 입력이 :class:`~ksi_geo_core.sync.TelemetrySample`
    (Scout ``NormalizedTelemetry`` 대응)로 바뀐 것 외 수식·게이트 순서는 동일하다.

    입력 검증(반증 리뷰 2026-07-26 P0 — 이전 구현은 NaN/Inf·비정상 치수·intrinsics·
    위경도 범위를 검사하지 않아 ``OK`` + NaN 좌표를 반환할 수 있었다)은 telemetry와
    무관한 순서로 가장 먼저 실행한다: 이미지 치수 → 픽셀 유한성 → 기본 FOV 범위
    → (geo_capable) → 고도 → 나머지 자세각·intrinsics 유한성 → 위경도 범위 →
    실효 FOV 범위. 마지막으로 산출된 좌표·confidence·오차반경도 유한성을 재확인한다
    (알고리즘 경로 자체의 예상 밖 발산까지 잡는 최종 안전망).
    """
    if width <= 0 or height <= 0:
        return ProjectionResult(status=ProjectionStatus.INVALID_IMAGE_DIMENSIONS)
    if not (math.isfinite(u_px) and math.isfinite(v_px)):
        return ProjectionResult(status=ProjectionStatus.INVALID_PIXEL)
    if not math.isfinite(default_fov_deg) or not (0.0 < default_fov_deg < 180.0):
        return ProjectionResult(status=ProjectionStatus.INVALID_INTRINSICS)

    if not _geo_capable(sample):
        return ProjectionResult(status=ProjectionStatus.GEO_UNAVAILABLE_TELEMETRY)

    altitude_m = sample.altitude_rel_m
    if altitude_m is None or not math.isfinite(altitude_m) or altitude_m <= 0:
        return ProjectionResult(status=ProjectionStatus.INVALID_ALTITUDE)

    lat0, lon0 = sample.drone_lat, sample.drone_lon
    heading_deg, pitch_deg = sample.heading_deg, sample.gimbal_pitch_deg
    assert lat0 is not None and lon0 is not None  # _geo_capable 이 보장 (타입 좁히기)
    assert heading_deg is not None and pitch_deg is not None

    roll_deg = sample.gimbal_roll_deg or 0.0
    yaw_deg = sample.gimbal_yaw_deg if sample.gimbal_yaw_deg is not None else heading_deg
    zoom_raw = sample.zoom_factor if sample.zoom_factor is not None else 1.0
    camera_fov_deg = (
        sample.camera_fov_deg if sample.camera_fov_deg is not None else default_fov_deg
    )
    if not all(
        math.isfinite(v)
        for v in (lat0, lon0, heading_deg, pitch_deg, roll_deg, yaw_deg, zoom_raw, camera_fov_deg)
    ):
        return ProjectionResult(status=ProjectionStatus.NONFINITE_INPUT)
    if not (-90.0 <= lat0 <= 90.0) or not (-180.0 <= lon0 <= 180.0):
        return ProjectionResult(status=ProjectionStatus.INVALID_GEO_RANGE)
    if not (0.0 < camera_fov_deg < 180.0):
        return ProjectionResult(status=ProjectionStatus.INVALID_INTRINSICS)

    fov_deg = camera_fov_deg
    zoom = max(zoom_raw, 1.0)
    fov_effective = 2 * math.atan(math.tan(math.radians(fov_deg) / 2) / zoom)
    if fov_is_diagonal:
        focal = (math.hypot(width, height) / 2) / math.tan(fov_effective / 2)
        fx = fy = focal
    else:
        fx = fy = (width / 2) / math.tan(fov_effective / 2)

    d_cam = np.array([(u_px - width / 2) / fx, (v_px - height / 2) / fy, 1.0])

    psi = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    roll = math.radians(roll_deg)

    rotation = _rz_clockwise(psi) @ _rx(pitch) @ _R0 @ _rroll(roll)
    d_world = rotation @ d_cam  # (East, North, Up)

    if d_world[2] >= -1e-6:  # 지평선 위/평행 — 비교차, 외삽 금지
        return ProjectionResult(status=ProjectionStatus.ABOVE_HORIZON)

    t = -altitude_m / d_world[2]
    east_m, north_m = float(t * d_world[0]), float(t * d_world[1])
    lat, lon = enu_to_wgs84(lat0, lon0, east_m, north_m)

    horizontal_distance_m = math.hypot(east_m, north_m)
    confidence = composite_confidence(
        d_world,
        horizontal_distance_m=horizontal_distance_m,
        altitude_m=altitude_m,
        camera_fov_deg_known=sample.camera_fov_deg is not None,
        gimbal_yaw_deg_known=sample.gimbal_yaw_deg is not None,
        source_quality=sample.source_quality,
        rtk_fixed=sample.rtk_fixed,
        gnss_accuracy_m=sample.gnss_accuracy_m,
    )
    error_radius_m = position_error_radius_m(
        d_world,
        horizontal_distance_m=horizontal_distance_m,
        rtk_fixed=sample.rtk_fixed,
        gnss_accuracy_m=sample.gnss_accuracy_m,
    )

    # 최종 안전망 — 위 입력 검증을 전부 통과했어도 알고리즘 경로 자체가 예상 밖으로
    # 발산해 비유한 결과를 낼 가능성을 차단한다. OK는 절대 NaN/Inf를 반환하지 않는다.
    if not all(math.isfinite(v) for v in (east_m, north_m, lat, lon, confidence, error_radius_m)):
        return ProjectionResult(status=ProjectionStatus.NONFINITE_INPUT)

    return ProjectionResult(
        status=ProjectionStatus.OK,
        lat=lat,
        lon=lon,
        east_m=east_m,
        north_m=north_m,
        confidence=confidence,
        error_radius_m=error_radius_m,
    )
