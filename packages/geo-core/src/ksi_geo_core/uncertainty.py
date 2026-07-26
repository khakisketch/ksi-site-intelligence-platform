"""Geo 투영 불확실성(confidence·오차반경) 합성 (P0-4).

PORT: upstream Scout ``ksi_scout/geo/projection.py`` @42ccc0db 의 ``project_foot_point``
내 confidence/오차반경 계산부를 :func:`~ksi_geo_core.projection.project_foot_point` 에서
분리해 독립 테스트 가능하게 만들었다 — 로직은 동일, 위치만 옮겼다.

INV-021(불확실성 유지 시에만 Confirmed) 강제를 위해, confidence는 **광선이 지평선에
가까워질수록·거리가 멀어질수록 비증가**해야 한다(단조성). ``tests/golden/
test_geo_core_uncertainty.py`` 가 파라미터 스윕으로 이를 검증한다.
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from ksi_geo_core.sync import SourceQuality

_SOURCE_QUALITY_FACTOR: dict[SourceQuality, float] = {
    SourceQuality.FULL: 1.0,
    SourceQuality.PARTIAL: 0.7,
    SourceQuality.DEGRADED: 0.4,
    SourceQuality.UNAVAILABLE: 0.0,
}
"""PORT: Scout ``_SQ`` 딕셔너리(값 동일)."""


def pitch_confidence_factor(ray_world_down: npt.NDArray[np.float64]) -> float:
    """월드 광선(East,North,Up)의 하강 성분 비율 — nadir(정수직)일수록 1에 근접.

    PORT: Scout ``horiz = abs(d_world[2]) / norm`` — "sin(하강각)"에 해당.
    지평선에 가까워질수록(수평 성분이 지배적일수록) 0에 수렴 → 단조 감소.
    """
    norm = float(np.linalg.norm(ray_world_down))
    horiz = abs(float(ray_world_down[2])) / norm
    return float(np.clip(horiz, 0.05, 1.0))


def range_confidence_factor(horizontal_distance_m: float, altitude_m: float) -> float:
    """수평거리/고도 비가 커질수록(더 비스듬히, 더 멀리 볼수록) 감소.

    PORT: Scout ``c_range`` 식 그대로.
    """
    ratio = horizontal_distance_m / max(altitude_m, 1e-3)
    return float(np.clip(1.0 / (1.0 + ratio**2 * 0.05), 0.05, 1.0))


def fov_confidence_factor(camera_fov_deg_known: bool) -> float:
    """카메라 FOV 메타데이터가 있으면 1.0, 기본값으로 강등했으면 0.5. PORT: Scout ``c_fov``."""
    return 1.0 if camera_fov_deg_known else 0.5


def metadata_confidence_factor(
    gimbal_yaw_deg_known: bool, source_quality: SourceQuality
) -> float:
    """짐벌 yaw 메타 유무 × 소스 품질. PORT: Scout ``c_meta`` 식 그대로."""
    yaw_factor = 1.0 if gimbal_yaw_deg_known else 0.8
    return yaw_factor * _SOURCE_QUALITY_FACTOR[source_quality]


def gnss_confidence_factor(rtk_fixed: bool, gnss_accuracy_m: float | None) -> float:
    """RTK Fix면 1.0, GNSS 정확도가 있으면 그에 반비례, 없으면 보수적 기본값 0.6.

    PORT: Scout ``c_gnss`` 식 그대로. RTK Fix는 정확도 *신호*일 뿐 절대정확도 보증이
    아니라는 INV-024는 이 값이 아니라 상위 Spatial Quality Report의 책무다.
    """
    if rtk_fixed:
        return 1.0
    if gnss_accuracy_m is not None:
        return float(np.clip(1 - gnss_accuracy_m / 10, 0.3, 1.0))
    return 0.6


def composite_confidence(
    ray_world_down: npt.NDArray[np.float64],
    *,
    horizontal_distance_m: float,
    altitude_m: float,
    camera_fov_deg_known: bool,
    gimbal_yaw_deg_known: bool,
    source_quality: SourceQuality,
    rtk_fixed: bool,
    gnss_accuracy_m: float | None,
) -> float:
    """다섯 factor의 product, [0,1] 클립. PORT: Scout ``conf`` 산출식 그대로."""
    conf = (
        pitch_confidence_factor(ray_world_down)
        * range_confidence_factor(horizontal_distance_m, altitude_m)
        * fov_confidence_factor(camera_fov_deg_known)
        * metadata_confidence_factor(gimbal_yaw_deg_known, source_quality)
        * gnss_confidence_factor(rtk_fixed, gnss_accuracy_m)
    )
    return float(np.clip(conf, 0.0, 1.0))


def position_error_radius_m(
    ray_world_down: npt.NDArray[np.float64],
    *,
    horizontal_distance_m: float,
    rtk_fixed: bool,
    gnss_accuracy_m: float | None,
) -> float:
    """RSS(root-sum-square) 오차반경. PORT: Scout ``err_radius`` 식 그대로.

    GNSS 오차 + (고도오차 × cot(하강각)) + (거리×각오차) 를 직교 오차원으로 합성한다 —
    지평선에 가까울수록(cot 발산) 오차가 커진다(confidence와 같은 방향의 단조성).
    """
    e = float(ray_world_down[2])
    horiz_norm = math.hypot(float(ray_world_down[0]), float(ray_world_down[1]))
    theta_down = math.atan2(abs(e), horiz_norm)
    e_gnss = 0.1 if rtk_fixed else (gnss_accuracy_m or 5.0)
    e_alt = 1.0 if rtk_fixed else 3.0
    cot = 1.0 / math.tan(theta_down) if theta_down > 1e-3 else 1e6
    return math.sqrt(
        e_gnss**2
        + (e_alt * cot) ** 2
        + (horizontal_distance_m * math.radians(1.5)) ** 2
        + 1.0
    )
