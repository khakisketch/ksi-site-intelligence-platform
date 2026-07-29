"""구역→커버리지 경로 생성 — 임무 타입별 패턴 (ADR-KSI-007, INV-010 지원 지점).

- **lawnmower** (BASELINE_MAPPING/SPATIAL_REFRESH 계열): 평행 스캔선 왕복. 간격은
  ``spacing_m`` 로 직접 받는다 — 겹침률/GSD→간격 산정은 카메라 스펙(실기 검증
  대상)이 필요해 이 층에 두지 않는다(전문가 모드 조정 항목, PRD §7.4).
- **perimeter** (AUTONOMOUS_PATROL 계열): 외곽 꼭짓점 순회 + 폐루프. 관심점(POI)
  경유는 Mission Contract viewpoint 정책이 소유하는 상위 결정이라 여기 없다.

## 이 생성기가 보증하는 것 / 하지 않는 것 (자율 재검토 F5 정정)

보증: **고도 창** — 경로 고도가 envelope [min, max] 안이다. **exclusion 부재 선언**
— ``excluded_volumes`` 가 비어있지 않으면 생성을 거부한다(경로 기하는 volume ID 를
해석할 수 없어 회피를 보증할 수 없고, 조용히 무시하면 배제구역 관통 경로가 KMZ 로
성립한다 — KMZ 는 서명이 없다).

보증하지 않음: standoff(구조물·사람 이격) — 이는 비행 중 Edge(Manifold) 정책
집행 영역이다(계약의 minimum*StandoffM 은 Edge 소비 필드). 경로 생성기는 구조물
위치를 모른다. 이 경계는 docstring 선언이지 코드 게이트가 아님을 명시해 둔다.

## 고도의 수직기준 (자율 재검토 F1 — 대표자 확정 대기)

모든 고도(route altitude·envelope min/max)는 **이륙점 상대(relativeToStartPoint)**
로 해석한다 — 지형 데이터 없이 안전한 유일한 모드이며 WPML 산출(wpml.py)도 같은
모드다. envelope 고도를 정표고(siteFrame verticalDatum)로 해석하는 계약과는
비교가 성립하지 않으므로(INV-020), 이 해석은 원장 risk
``route-altitude-vertical-reference`` 로 기록되어 대표자 확정(스키마 명문화) 전까지
잠정 규약이다. 이 줄을 지우려면 그 risk 를 먼저 해소하라.

비볼록 폴리곤 한계(문서화된 알려진 제약): 스캔선이 폴리곤을 여러 구간으로
끊는 오목 구역에서는 **스캔선마다 1회씩** 구간 사이 이동이 구역 밖을 지난다 —
allowed_volumes 가 현장 전체를 덮는 전제에서 안전하고, 구역 밖 비행 최소화가
요구되면 폴리곤을 볼록 조각으로 나눠 별개 임무로 발급하는 것이 정책이다(정석은
boustrophedon cell decomposition — 필요 시점에 도입).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ksi_geo_core.frames import enu_to_wgs84
from ksi_mission_contracts.models import FlightEnvelope

from ksi_mission_planning.geometry import AreaOfInterest


class RouteGenerationError(ValueError):
    """경로 생성 불가 — 입력 파라미터·봉투 위반의 typed 실패."""


# 스캔선 간격 하한(m) — 미인증 입력의 스캔선 수 폭발(OOM) 차단. 실 GSD 간격은 m 단위.
_MIN_SPACING_M = 0.1
# 웨이포인트 수 상한 — WPML index 스펙 범위 [0, 65535].
_MAX_WAYPOINTS = 65_536


@dataclass(frozen=True, slots=True)
class RouteWaypoint:
    """경로 한 점. ``altitude_m`` 는 이륙점 상대 고도다."""

    lat_deg: float
    lon_deg: float
    altitude_m: float


def _require_envelope_compatible(altitude_m: float, envelope: FlightEnvelope) -> None:
    if not math.isfinite(altitude_m):
        raise RouteGenerationError(f"altitude_m 는 finite 여야 한다 (got {altitude_m!r})")
    if not (envelope.min_altitude_m <= altitude_m <= envelope.max_altitude_m):
        raise RouteGenerationError(
            f"고도 {altitude_m}m 는 FlightEnvelope [{envelope.min_altitude_m}, "
            f"{envelope.max_altitude_m}]m 밖이다 — 봉투 밖 경로는 생성하지 않는다"
        )
    if envelope.excluded_volumes:
        raise RouteGenerationError(
            f"excludedVolumes {envelope.excluded_volumes!r} 가 선언된 봉투 — 경로 기하는 "
            "volume 회피를 보증할 수 없다(모듈 docstring). 배제구역 없는 봉투로 발급하거나 "
            "구역을 나눠 발급하라"
        )


def perimeter_route(
    aoi: AreaOfInterest, *, altitude_m: float, envelope: FlightEnvelope
) -> list[RouteWaypoint]:
    """외곽 순찰 경로 — 꼭짓점 순회 후 첫 점으로 복귀(폐루프)."""
    _require_envelope_compatible(altitude_m, envelope)
    points = [
        RouteWaypoint(lat_deg=v.lat_deg, lon_deg=v.lon_deg, altitude_m=altitude_m)
        for v in aoi.vertices
    ]
    return [*points, points[0]]


def _rotate(x: float, y: float, angle_rad: float) -> tuple[float, float]:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return x * c - y * s, x * s + y * c


def _dominant_edge_angle_rad(ring: list[tuple[float, float]]) -> float:
    """가장 긴 변의 방향각 — 스캔선을 이 방향으로 놓으면 선회 횟수가 최소화되는
    경향이 있다(직사각형류 현장에서 정확히 최소)."""
    best_angle = 0.0
    best_len = -1.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        length = math.hypot(x2 - x1, y2 - y1)
        if length > best_len:
            best_len = length
            best_angle = math.atan2(y2 - y1, x2 - x1)
    return best_angle


def lawnmower_route(
    aoi: AreaOfInterest,
    *,
    spacing_m: float,
    altitude_m: float,
    envelope: FlightEnvelope,
    sweep_direction_deg: float | None = None,
) -> list[RouteWaypoint]:
    """평행 스캔선 왕복(boustrophedon) 매핑 경로.

    Args:
        spacing_m: 스캔선 간격 상한(m) — 실제 간격은 전체 커버를 위해 이하로만
            조밀해질 수 있고 초과하지 않는다. 겹침률→간격 환산은 호출자 몫.
        sweep_direction_deg: 스캔선 방향 — **수학 규약(동=0, 반시계, 도)** 이다.
            나침반 방위(heading, 북=0 시계)가 아니다(자율 재검토 F8 — 이름을
            direction 으로 강제해 규약 혼동을 API 표면에서 차단). ``None`` 이면
            가장 긴 변 방향을 자동 선택.

    Returns:
        스캔선 교대 순회 웨이포인트. 각 스캔선은 폴리곤과의 교차 구간 끝점 쌍으로
        표현된다(비볼록이면 한 선에 구간 여러 개 — 모듈 docstring 의 한계 참조).
    """
    _require_envelope_compatible(altitude_m, envelope)
    if not (math.isfinite(spacing_m) and spacing_m >= _MIN_SPACING_M):
        raise RouteGenerationError(
            f"spacing_m 는 {_MIN_SPACING_M}m 이상의 finite 여야 한다 (got {spacing_m!r}) — "
            "하한은 스캔선 수 폭발(자원 소진) 차단"
        )

    ring = aoi._to_enu_ring()
    anchor = aoi.anchor()

    if sweep_direction_deg is not None and not math.isfinite(sweep_direction_deg):
        raise RouteGenerationError(
            f"sweep_direction_deg 는 finite 여야 한다 ({sweep_direction_deg!r})"
        )
    angle = (
        math.radians(sweep_direction_deg)
        if sweep_direction_deg is not None
        else _dominant_edge_angle_rad(ring)
    )

    # 스캔선이 x축과 평행해지도록 -angle 회전한 좌표계에서 작업한다.
    rotated = [_rotate(x, y, -angle) for x, y in ring]
    min_y = min(y for _, y in rotated)
    max_y = max(y for _, y in rotated)

    # 전체 커버 보장(자율 재검토 F6): 각 스캔선의 커버 폭이 ±spacing/2 라는 전제에서
    # 첫/마지막 선을 경계에서 spacing/2 안쪽에 두되, 선 수는 ceil 로 올려 실제 간격이
    # spacing **이하**가 되게 한다 — 간격이 성기어지는 방향의 이탈은 커버리지 구멍
    # (INV-010 위반)이므로 허용하지 않고, 조밀해지는 방향만 허용한다. 스캔선이 경계
    # 위에 정확히 놓이는 퇴화도 함께 제거된다. 폭이 spacing 이하면 중앙선 1개.
    height = max_y - min_y
    usable = height - spacing_m
    if usable <= 0:
        scan_ys = [(min_y + max_y) / 2.0]
    else:
        count = math.ceil(usable / spacing_m) + 1
        if count > _MAX_WAYPOINTS // 2:
            raise RouteGenerationError(
                f"스캔선 {count}개는 웨이포인트 상한({_MAX_WAYPOINTS}, WPML index 범위)을 "
                "넘는다 — spacing 을 키우거나 구역을 나눠라"
            )
        effective = usable / (count - 1)
        scan_ys = [min_y + spacing_m / 2.0 + k * effective for k in range(count)]

    n = len(rotated)
    waypoints: list[RouteWaypoint] = []
    for line_index, y in enumerate(scan_ys):
        # 수평선 y 와 폴리곤 변들의 교차 x 목록 (half-open 규약: 변의 y 구간
        # [min, max) 에 걸릴 때만 카운트 — 꼭짓점 정확 통과 시 이중 카운트 방지).
        xs: list[float] = []
        for i in range(n):
            x1, y1 = rotated[i]
            x2, y2 = rotated[(i + 1) % n]
            if y1 == y2:
                continue  # 수평 변은 교차점 대신 이웃 변이 담당
            lo, hi = (y1, y2) if y1 < y2 else (y2, y1)
            if not (lo <= y < hi):
                continue
            t = (y - y1) / (y2 - y1)
            xs.append(x1 + t * (x2 - x1))
        xs.sort()
        if len(xs) % 2 != 0:
            # half-open 규약으로도 부동소수 경계에서 홀수가 나오면 그 선은 신뢰할
            # 수 없다 — 조용히 버리면 커버리지 구멍이 무음으로 생기므로 실패한다.
            raise RouteGenerationError(
                f"스캔선 y={y:.3f} 교차점이 홀수({len(xs)}) — 경계 퇴화, "
                "sweep_heading_deg 를 조정해 재시도하라"
            )

        # 길이 0 퇴화 구간(스캔선이 국소최소 꼭짓점에 정확히 접함 — xs 에 같은 x 2개)
        # 은 동일 좌표 웨이포인트 쌍만 만들므로 버린다(자율 재검토 P2).
        segments = [
            (xs[k], xs[k + 1]) for k in range(0, len(xs), 2) if xs[k + 1] - xs[k] > 1e-9
        ]
        if line_index % 2 == 1:
            segments = [(b, a) for a, b in reversed(segments)]

        for x_start, x_end in segments:
            for x in (x_start, x_end):
                east, north = _rotate(x, y, angle)
                lat, lon = enu_to_wgs84(anchor.lat_deg, anchor.lon_deg, east, north)
                waypoints.append(
                    RouteWaypoint(lat_deg=lat, lon_deg=lon, altitude_m=altitude_m)
                )

    if not waypoints:
        raise RouteGenerationError("스캔선이 폴리곤과 교차하지 않았다 — 구역·간격을 확인하라")
    if len(waypoints) > _MAX_WAYPOINTS:
        raise RouteGenerationError(
            f"웨이포인트 {len(waypoints)}개는 WPML index 상한({_MAX_WAYPOINTS})을 넘는다 — "
            "spacing 을 키우거나 구역을 나눠라"
        )
    return waypoints
