"""ENU 로컬 접평면 ↔ WGS84 좌표 변환 (P0-4).

PORT: upstream Scout ``ksi_scout/geo/projection.py`` @42ccc0db 의 인라인 ENU→WGS84 식
(``lat = lat0 + degrees(north/R)``, ``lon = lon0 + degrees(east/(R·cos(lat0)))``)을
재사용 가능한 순수 함수로 추출했다. 역변환(WGS84→ENU)은 Scout에 없던 함수이지만
같은 등장방형(equirectangular) 근사의 대수적 역(inverse)이다 — 상세 도출은
``packages/test-vectors/vectors/ksi_correctness/enu_wgs84_roundtrip.json`` 의
``derivation_basis`` 참고.

이 근사는 **로컬 접평면**(현장 스케일, 수 km 이내) 전용이다 — 측지선(geodesic) 정밀
변환이 아니며, 대현장·장거리에는 성립하지 않는다(INV-020 CRS 명시 원칙과 별개로,
이 모듈 자체가 그 스케일 제약을 갖는다는 점을 호출자가 알아야 한다).
"""

from __future__ import annotations

import math

WGS84_EQUATORIAL_RADIUS_M = 6378137.0
"""PORT: Scout ``_RE``. 등장방형 근사에 쓰는 지구 반경(구체 근사, 타원체 미보정)."""


def enu_to_wgs84(
    origin_lat_deg: float, origin_lon_deg: float, east_m: float, north_m: float
) -> tuple[float, float]:
    """ENU 오프셋(원점 기준 동/북, m) → WGS84 (lat, lon) 도.

    PORT: Scout ``project_foot_point`` 내 ENU→WGS84 변환식.
    """
    lat = origin_lat_deg + math.degrees(north_m / WGS84_EQUATORIAL_RADIUS_M)
    lon = origin_lon_deg + math.degrees(
        east_m / (WGS84_EQUATORIAL_RADIUS_M * math.cos(math.radians(origin_lat_deg)))
    )
    return lat, lon


def wgs84_to_enu(
    origin_lat_deg: float, origin_lon_deg: float, lat_deg: float, lon_deg: float
) -> tuple[float, float]:
    """WGS84 (lat, lon) 도 → 원점 기준 ENU 오프셋(동/북, m).

    :func:`enu_to_wgs84` 의 대수적 역함수 — 같은 등장방형 근사, 같은 정밀도 제약.
    """
    east = (
        WGS84_EQUATORIAL_RADIUS_M
        * math.radians(lon_deg - origin_lon_deg)
        * math.cos(math.radians(origin_lat_deg))
    )
    north = WGS84_EQUATORIAL_RADIUS_M * math.radians(lat_deg - origin_lat_deg)
    return east, north


def great_circle_distance_m(
    lat1_deg: float, lon1_deg: float, lat2_deg: float, lon2_deg: float
) -> float:
    """두 WGS84 좌표 간 대권거리(m) — haversine. PORT: Scout ``geo_distance_m``."""
    p1, p2 = math.radians(lat1_deg), math.radians(lat2_deg)
    d_phi = math.radians(lat2_deg - lat1_deg)
    d_lambda = math.radians(lon2_deg - lon1_deg)
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    return 2 * WGS84_EQUATORIAL_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))
