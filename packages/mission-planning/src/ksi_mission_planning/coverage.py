"""구역→커버리지 경로 생성 — 임무 타입별 패턴 (ADR-KSI-007, INV-010 지원 지점).

- **lawnmower** (BASELINE_MAPPING/SPATIAL_REFRESH 계열): 평행 스캔선 왕복. 간격은
  ``spacing_m`` 로 직접 받는다 — 겹침률/GSD→간격 산정은 카메라 스펙(실기 검증
  대상)이 필요해 이 층에 두지 않는다(전문가 모드 조정 항목, PRD §7.4).
- **perimeter** (AUTONOMOUS_PATROL 계열): 외곽 꼭짓점 순회 + 폐루프. 관심점(POI)
  경유는 Mission Contract viewpoint 정책이 소유하는 상위 결정이라 여기 없다.

## 이 생성기가 보증하는 것 / 하지 않는 것 (자율 재검토 F5 정정, lawnmower 는 재검토 A 로 갱신)

보증: **고도 창** — 경로 고도가 envelope [min, max] 안이다. **exclusion 부재 선언**
— ``excluded_volumes`` 가 비어있지 않으면 생성을 거부한다(경로 기하는 volume ID 를
해석할 수 없어 회피를 보증할 수 없고, 조용히 무시하면 배제구역 관통 경로가 KMZ 로
성립한다 — KMZ 는 서명이 없다). **lawnmower 커버리지** — 두 게이트의 결합으로만
보증한다: ① 입력 AOI 가 볼록이 아니면 typed 거부(비볼록에서는 스캔선 사이/바깥
밴드가 무음 미커버를 낼 수 있어 커버 보장 자체가 성립하지 않는다) ② 스캔선 확정
후 회전 프레임에서 스와스∩AOI 면적을 **해석적으로 정확 계산**해
``_MIN_COVERAGE_RATIO`` 미만이면 거부한다(볼록이어도 sweep 방향이 도형과 어긋나면
— 예: 전단 평행사변형 — 대면적 미커버가 날 수 있어 "스캔선 폭 ±spacing/2 가
전체를 덮는다"는 기하학적 직관만으로는 보증이 안 된다). 두 게이트를 통과한
:class:`LawnmowerResult` 만 성립한 임무다 — ``coverage_ratio`` 는 그 정확값이며
1.0 미만이어도 임계값 이상이면 통과한다.

스와스 모델(최종 반증 F-3): 각 스캔선의 커버 사각형은 along-track 으로 비행
세그먼트 **끝점에서 종료**로 모델링한다 — 실기는 끝점 웨이포인트에서도 촬영하므로
footprint 절반만큼 더 덮는 **보수적 과소보고**다(거짓 증명서 방향이 아니라 안전
방향). 그 결과 경사변 도형(삼각형·사다리꼴)은 어떤 sweep 에서도 모서리 손실이
남는다 — 끝점 ±footprint/2 확장 여부는 카메라 스펙(H4) 결정 종속.

임계값의 지위(재검증 P3): ``_MIN_COVERAGE_RATIO`` 는 INV-010 의 **접근가능
일반영역 ≥95%** 조항이다. 같은 불변식의 "필수 위험구역 100%·필수 자산/표면
100%" 는 이 계획 층이 강제하지 못한다 — AOI·요청에 구역 등급 입력이 없고, 그
조항은 비행 후 CoverageReport 완료 게이트 소관(미구현)이다. 응답의
``coverageRatio`` 를 그 조항의 증명으로 읽으면 안 된다.

보증하지 않음: standoff(구조물·사람 이격) — 이는 비행 중 Edge(Manifold) 정책
집행 영역이다(계약의 minimum*StandoffM 은 Edge 소비 필드). 경로 생성기는 구조물
위치를 모른다. 이 경계는 docstring 선언이지 코드 게이트가 아님을 명시해 둔다.

## 고도의 수직기준 (자율 재검토 F1 — 2026-07-29 대표자 확정)

모든 고도(route altitude·envelope min/max)는 **이륙점 상대(relativeToStartPoint)**
다 — 계약 스키마 v1.2 의 ``flightEnvelope.altitudeReference``(const) 로 명문화됐고
발급기(mission_issuance)가 항상 채운다. WPML 산출(wpml.py)도 같은 모드다.
siteFrame.verticalDatum(정표고)은 세계모델 좌표 전용으로 분리된다(INV-020).

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
from pydantic import BaseModel, ConfigDict

from ksi_mission_planning.geometry import AreaOfInterest


class RouteGenerationError(ValueError):
    """경로 생성 불가 — 입력 파라미터·봉투 위반의 typed 실패."""


# 스캔선 간격 하한(m) — 미인증 입력의 스캔선 수 폭발(OOM) 차단. 실 GSD 간격은 m 단위.
_MIN_SPACING_M = 0.1
# 진행방향(along-track) 촬영 간격 하한(m) — 같은 이유의 웨이포인트 폭발 차단.
_MIN_CAPTURE_INTERVAL_M = 0.1
# 스캔선 간격의 고도 대비 상한 배수(2차 독립 재검토 P1-2).
#
# 커버리지 실측은 각 스캔선이 ±spacing/2 를 덮는다고 **가정**하는데, spacing 이
# 요청 입력이라 요청이 자기 커버리지 증명서를 스스로 써주는 구조였다 — 실제로
# spacing=300·capture=300 을 주면 2ha 구역이 사진 2장에 coverage_ratio 1.0 으로
# 발급됐다(실측 재현).
#
# 카메라 스펙 없이도 쓸 수 있는 물리 상한이 하나 있다: 지상 촬영폭은
# 2·고도·tan(HFOV/2) 이고, 매핑에 쓰는 어떤 기체 카메라도 수평화각 120°(계수
# 3.46)를 넘지 않는다. 즉 spacing 이 고도의 3.46배를 넘으면 그 커버 주장은
# **어떤 카메라로도 성립할 수 없다**. 이건 "적정 겹침"의 기준이 아니라 물리적
# 불가능만 거르는 하한선이다 — 실제 겹침률 산정은 여전히 호출자 몫이고, 카메라
# 실측 확정(H4) 후에 고도·렌즈 기반으로 좁힌다.
_MAX_SPACING_PER_ALTITUDE = 3.46
# 웨이포인트 수 상한 — WPML index 스펙 범위 [0, 65535].
_MAX_WAYPOINTS = 65_536
# INV-010 일반영역 커버리지 하한 — 요청으로 바꿀 수 없는 모듈 상수(자율 재검토 A-2).
_MIN_COVERAGE_RATIO = 0.95
# usable(=폭-spacing) 이 이 근방이면 부동소수 잡음 수준이라 스캔선 2개가 사실상
# 동일 좌표(웨이포인트 쌍 중복)가 된다 — 이때만 중앙선 1개로 접는다. 그 이상의
# usable(예: 0 < usable <= 0.1)은 접지 않고 선 2개를 유지해야 커버가 수학적으로
# 유지된다(재검토 B — 과거엔 이 문턱이 스캔선 간격 하한 ``_MIN_SPACING_M`` 을
# 재사용해 spacing<height<=spacing+0.1 밴드 전체를 접어버려 양끝 최대 5cm 미커버를
# 냈다. A-2 실측 게이트는 일반영역 하한 0.95 를 보므로 이 정도 미세 결손을 항상
# 잡는다는 보장이 없어 문턱 자체를 고쳤다).
_FOLD_EPSILON_M = 1e-6
# 볼록성 판정 외적(m²) 0 허용오차 — geometry.py 의 자기교차 판정과 같은 규모.
_CONVEXITY_EPSILON_M2 = 1e-6
# 커버 비율 1.0 스냅의 절대 상한(m²) — 상대 1e-9 와 결합해 작은 쪽만 스냅한다
# (최종 반증 F-1: 상대 기준 단독은 최대 AOI 에서 0.3 m² 미커버를 숨긴다).
_SNAP_MAX_ABS_M2 = 0.01


@dataclass(frozen=True, slots=True)
class RouteWaypoint:
    """경로 한 점. ``altitude_m`` 는 이륙점 상대 고도다."""

    lat_deg: float
    lon_deg: float
    altitude_m: float


class LawnmowerResult(BaseModel):
    """lawnmower_route 반환값 — 웨이포인트 + 실측 커버 비율(자율 재검토 A-2).

    ``coverage_ratio`` 는 ``_MIN_COVERAGE_RATIO`` 이상임이 이미 게이트로 보증된
    값이다(그 미만은 :class:`RouteGenerationError` 로 거부되어 이 모델이 생성되지
    않는다) — 호출자는 이 값을 감사·로그용으로만 쓰면 되고, 재검증할 필요는 없다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    waypoints: list[RouteWaypoint]
    coverage_ratio: float


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
    if not envelope.allowed_volumes:
        # allowed_volumes 는 '현장 전체를 덮는 허용 구역' 전제(모듈 docstring)의
        # 실체다 — 빈 목록은 '아무 데도 허용되지 않음'이므로 어떤 경로도 그 전제를
        # 만족할 수 없다(재검토: 조용히 생성되던 경로를 fail-closed 로 전환).
        raise RouteGenerationError(
            "EMPTY_ALLOWED_VOLUMES — allowedVolumes 가 빈 봉투에서는 어떤 경로도 "
            "허용 구역 전제를 만족할 수 없다. 허용 volume 을 선언한 봉투로 발급하라"
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


def _is_convex_ring(ring: list[tuple[float, float]]) -> bool:
    """인접 변의 외적 부호가 전 꼭짓점에서 일관되면 볼록(재검토 A-1).

    공선 꼭짓점(외적≈0)은 부호 판정에서 제외한다 — AreaOfInterest 가 이미 자기교차·
    (연속·비연속) 중복 꼭짓점을 거부하므로, 여기 남을 수 있는 공선은 볼록 변 위에
    얹힌 여분 꼭짓점뿐이고 그건 볼록성을 해치지 않는다.
    """
    n = len(ring)
    sign = 0
    for i in range(n):
        ax, ay = ring[i - 1]
        bx, by = ring[i]
        cx, cy = ring[(i + 1) % n]
        cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(cross) <= _CONVEXITY_EPSILON_M2:
            continue
        current_sign = 1 if cross > 0 else -1
        if sign == 0:
            sign = current_sign
        elif current_sign != sign:
            return False
    return True


def _polygon_area(ring: list[tuple[float, float]]) -> float:
    """shoelace 면적(절댓값, m²) — 꼭짓점 3개 미만은 0."""
    n = len(ring)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _clip_axis(
    poly: list[tuple[float, float]], bound: float, *, axis: int, keep_le: bool
) -> list[tuple[float, float]]:
    """Sutherland–Hodgman 반평면 한 축 클리핑 — 볼록 폴리곤 전용 보조."""
    out: list[tuple[float, float]] = []
    n = len(poly)
    for i in range(n):
        cur = poly[i]
        nxt = poly[(i + 1) % n]
        cur_in = (cur[axis] <= bound) if keep_le else (cur[axis] >= bound)
        nxt_in = (nxt[axis] <= bound) if keep_le else (nxt[axis] >= bound)
        if cur_in:
            out.append(cur)
        if cur_in != nxt_in:
            t = (bound - cur[axis]) / (nxt[axis] - cur[axis])
            out.append((cur[0] + t * (nxt[0] - cur[0]), cur[1] + t * (nxt[1] - cur[1])))
    return out


def _rect_clip_area(
    ring: list[tuple[float, float]],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> float:
    """볼록 폴리곤 ∩ 축정렬 직사각형의 면적 — 반평면 4회 클리핑 후 shoelace."""
    poly = ring
    for bound, axis, keep_le in (
        (x_min, 0, False),
        (x_max, 0, True),
        (y_min, 1, False),
        (y_max, 1, True),
    ):
        poly = _clip_axis(poly, bound, axis=axis, keep_le=keep_le)
        if len(poly) < 3:
            return 0.0
    return _polygon_area(poly)


def _measure_lawnmower_coverage_ratio(
    rotated_ring: list[tuple[float, float]],
    scan_ys: list[float],
    scan_segments: list[list[tuple[float, float]]],
    *,
    spacing_m: float,
) -> float:
    """회전 프레임에서 스와스∩AOI 면적을 **해석적으로 정확** 계산한다(재검증 정정).

    초기 구현은 격자 샘플링이었으나 재검증이 두 방향의 파탄을 적발했다 — step 이
    spacing 에 묶여 있어 spacing ≥ 2×(AOI 높이)면 격자가 1행/0행으로 붕괴, 전단
    도형 실커버 66.7% 가 1.0 으로 통과(거짓 증명서)하고 완전 커버 임무가 0.0 으로
    거부됐다. 샘플링을 버리고 정확 계산으로 교체한다(무한 CPU 우려도 함께 해소 —
    비용은 O(스캔선×꼭짓점), 두 인자 모두 기존 상한이 유계한다).

    각 스캔선의 스와스는 회전 프레임에서 축정렬 직사각형(세그먼트 x구간 ×
    ``y±spacing/2``)이다. 볼록 AOI 전제(볼록성 게이트 뒤에서만 호출됨)에서
    스캔선당 세그먼트는 1개이므로, 커버 면적 = Σ(AOI∩R_i) − Σ(AOI∩R_i∩R_{i+1})
    의 포함-배제가 정확하다 — 스캔선 실간격(effective)이 선 3개 이상일 때 항상
    spacing/2 초과라 비인접 스와스는 y 로 서로소이고(2·effective > spacing),
    선 2개뿐일 때는 쌍별 포함-배제 자체가 완전하다.
    """
    aoi_area = _polygon_area(rotated_ring)
    if aoi_area <= 0.0:
        # AreaOfInterest 검증(면적 0 거부)을 통과했다면 도달 불가 — 방어적 fail-closed.
        raise RouteGenerationError("AOI 면적이 0 — 커버 비율을 정의할 수 없다")

    half_swath = spacing_m / 2.0
    rects: list[tuple[float, float, float, float]] = []
    for y, segments in zip(scan_ys, scan_segments, strict=True):
        if not segments:
            continue
        if len(segments) != 1:
            # 볼록 AOI 의 수평 단면은 구간 1개다 — 2개 이상은 전제 붕괴(fail-closed).
            raise RouteGenerationError(
                f"볼록 AOI 인데 스캔선 y={y:.3f} 의 구간이 {len(segments)}개 — "
                "볼록성 전제 위반"
            )
        a, b = segments[0]
        lo, hi = (a, b) if a <= b else (b, a)
        rects.append((lo, hi, y - half_swath, y + half_swath))

    covered = 0.0
    for i, (xa, xb, ya, yb) in enumerate(rects):
        covered += _rect_clip_area(rotated_ring, xa, xb, ya, yb)
        if i + 1 < len(rects):
            nxa, nxb, nya, nyb = rects[i + 1]
            ox_lo, ox_hi = max(xa, nxa), min(xb, nxb)
            oy_lo, oy_hi = max(ya, nya), min(yb, nyb)
            if ox_lo < ox_hi and oy_lo < oy_hi:
                covered -= _rect_clip_area(rotated_ring, ox_lo, ox_hi, oy_lo, oy_hi)

    # 부동소수 잔차 처리 — 정확식이라 오차는 클리핑 연쇄의 ulp 수준뿐이다. 1.0
    # 근방은 1.0 으로 스냅한다: 완전 커버 도형이 0.99999999999998 로 보고되면
    # '약속 1.0 대조' 같은 등호 비교가 노이즈에 흔들린다. 스냅 폭은 상대 1e-9 와
    # **절대 0.01 m² 중 작은 쪽** — 상대 기준만 쓰면 최대 AOI(반경 10km, ~3e8 m²)
    # 에서 0.3 m²(사람 발자국 규모)의 진짜 미커버가 숨을 수 있다(최종 반증 F-1).
    uncovered = aoi_area - covered
    if uncovered <= min(aoi_area * 1e-9, _SNAP_MAX_ABS_M2):
        return 1.0
    return max(0.0, min(1.0, covered / aoi_area))


def _capture_xs(
    x_start: float, x_end: float, capture_interval_m: float | None
) -> list[float]:
    """스캔선 한 구간 위의 웨이포인트 x 목록 — 촬영 간격이 있으면 그 간격으로 채운다.

    간격 규약은 ``spacing_m`` 과 같다: 실제 간격은 요청값 **이하**로만 조밀해진다
    (``ceil`` 로 구간 수를 올린 뒤 균등 분할). 성기어지는 방향의 이탈은 곧 중첩
    부족이고, 중첩 부족은 재구성이 조용히 실패하는 방식이기 때문이다.

    끝점은 항상 포함한다 — 구간 끝이 곧 AOI 경계라 그 지점의 사진이 빠지면
    경계 밴드가 재구성에서 잘린다. 방향(x_start>x_end, 홀수 스캔선의 역순)도
    그대로 보존한다.
    """
    if capture_interval_m is None:
        return [x_start, x_end]
    span = abs(x_end - x_start)
    # 간격보다 짧은 구간은 끝점 2장으로 이미 간격 조건을 만족한다.
    if span <= capture_interval_m:
        return [x_start, x_end]
    steps = math.ceil(span / capture_interval_m)
    if steps + 1 > _MAX_WAYPOINTS:
        # 세그먼트 **하나**가 상한을 넘는 경우를 리스트 생성 **전에** 끊는다
        # (독립 재검토 P2-2) — 호출자의 루프 안 검사는 세그먼트 간에만 유효해서,
        # 여기서 먼저 materialize 하면 그 검사가 도는 시점엔 이미 할당이 끝나 있다.
        raise RouteGenerationError(
            f"한 스캔선에 웨이포인트 {steps + 1}개 — WPML index 상한"
            f"({_MAX_WAYPOINTS})을 넘는다. captureIntervalM 을 키워라"
        )
    return [x_start + (x_end - x_start) * k / steps for k in range(steps + 1)]


def lawnmower_route(
    aoi: AreaOfInterest,
    *,
    spacing_m: float,
    altitude_m: float,
    envelope: FlightEnvelope,
    sweep_direction_deg: float | None = None,
    capture_interval_m: float | None = None,
) -> LawnmowerResult:
    """평행 스캔선 왕복(boustrophedon) 매핑 경로.

    Args:
        spacing_m: 스캔선 간격 상한(m) — 실제 간격은 전체 커버를 위해 이하로만
            조밀해질 수 있고 초과하지 않는다. 겹침률→간격 환산은 호출자 몫.
            이 값이 정하는 것은 **측면(side) 중첩**이다.

            고도 대비 물리 상한(``_MAX_SPACING_PER_ALTITUDE``)을 넘으면 거부한다 —
            커버리지 실측이 ±spacing/2 스와스를 가정하므로, 상한이 없으면 요청이
            자기 커버리지 증명서를 스스로 써주게 된다.
        capture_interval_m: 진행방향(along-track) 촬영 간격 상한(m). 주면 스캔선
            **위에도** 그 간격 이하로 웨이포인트를 채운다 — 촬영 액션이 웨이포인트
            도달 시점에 걸리므로(``wpml.py`` 의 ``reachPoint`` 트리거), 이 값이
            없으면 스캔선당 사진은 양 끝 2장뿐이고 **전방 중첩이 0** 이 되어
            정사영상·3D 재구성이 성립하지 않는다(원장 risk
            ``mapping-forward-overlap-zero``). ``None`` 이면 끝점만 — 촬영이
            목적이 아닌 경로(이동·순찰)에서만 맞다.

            간격→중첩 환산(카메라 footprint × (1−전방중첩))은 카메라 스펙 종속이라
            이 층이 하지 않는다 — ``spacing_m`` 과 같은 규약이다.

            *알려진 비효율*: 지금은 촬영 지점마다 웨이포인트를 두므로 turn mode
            (``toPointAndStop...``)상 매 지점 정지·촬영이 된다. 웨이포인트 없이
            거리 간격으로 촬영을 거는 WPML 트리거가 있다고 알려져 있으나, 그
            enum·파라미터는 이 저장소 어디에서도 raw 스펙으로 확인되지 않았다 —
            H4(실기 Pilot 2 export 대조)에서 확정한 뒤 최적화한다. 미검증 값을
            매핑 기본 경로에 박지 않는다.
        sweep_direction_deg: 스캔선 방향 — **수학 규약(동=0, 반시계, 도)** 이다.
            나침반 방위(heading, 북=0 시계)가 아니다(자율 재검토 F8 — 이름을
            direction 으로 강제해 규약 혼동을 API 표면에서 차단). ``None`` 이면
            가장 긴 변 방향을 자동 선택.

    Returns:
        :class:`LawnmowerResult` — 스캔선 교대 순회 웨이포인트 + 실측 커버 비율.
        AOI 는 볼록이어야 한다(비볼록은 ``NON_CONVEX_AOI`` 로 typed 거부 — 재검토
        A-1, 스캔선 사이/바깥 밴드 무음 미커버 방지). 볼록이어도 실측 커버 비율이
        ``_MIN_COVERAGE_RATIO`` 미만이면 ``COVERAGE_BELOW_MINIMUM`` 으로 거부한다
        (재검토 A-2, sweep 방향이 도형과 어긋난 경우 등).

    Raises:
        RouteGenerationError: 비볼록 AOI · 커버 비율 미달 · 그 밖 typed 위반.
    """
    _require_envelope_compatible(altitude_m, envelope)
    if not (math.isfinite(spacing_m) and spacing_m >= _MIN_SPACING_M):
        raise RouteGenerationError(
            f"spacing_m 는 {_MIN_SPACING_M}m 이상의 finite 여야 한다 (got {spacing_m!r}) — "
            "하한은 스캔선 수 폭발(자원 소진) 차단"
        )
    spacing_ceiling = _MAX_SPACING_PER_ALTITUDE * altitude_m
    if spacing_m > spacing_ceiling:
        raise RouteGenerationError(
            f"spacing_m({spacing_m}) 가 고도 {altitude_m}m 에서의 물리 상한"
            f"({spacing_ceiling:.1f}m = 고도×{_MAX_SPACING_PER_ALTITUDE})을 넘는다 — "
            "이 간격으로 전체를 덮었다는 커버리지는 어떤 카메라로도 성립하지 않는다"
        )
    if capture_interval_m is not None:
        if not (
            math.isfinite(capture_interval_m) and capture_interval_m >= _MIN_CAPTURE_INTERVAL_M
        ):
            raise RouteGenerationError(
                f"capture_interval_m 는 {_MIN_CAPTURE_INTERVAL_M}m 이상의 finite 여야 한다 "
                f"(got {capture_interval_m!r}) — 하한은 웨이포인트 수 폭발(자원 소진) 차단"
            )
        if capture_interval_m > spacing_m:
            # **상한이 없으면 이 인자는 fail-closed 시늉만 한다**(독립 재검토 P1-2):
            # 아주 큰 값을 주면 구간이 통째로 "간격보다 짧다"로 떨어져 끝점 2개만
            # 남고, 전방 중첩 0 이 그대로 재현되는데 coverage_ratio 는 여전히 1.0 을
            # 보고한다(실측이 스캔선 스와스만 보고 진행방향 샘플링은 보지 않는다).
            #
            # 카메라 스펙 없이 쓸 수 있는 상한이 하나 있다 — **측면 간격**이다.
            # 사진측량에서 전방 중첩은 통상 측면보다 크게 잡으므로 진행방향 간격이
            # 측면 간격을 넘는 구성은 어떤 카메라에서도 의도된 매핑이 아니다.
            # 이 결합으로 진행방향 샘플링이 최소한 측면만큼 조밀해져, 스와스 모델
            # 기반 coverage_ratio 의 "보수적 과소보고" 전제도 유지된다.
            raise RouteGenerationError(
                f"capture_interval_m({capture_interval_m}) > spacing_m({spacing_m}) — "
                "진행방향 간격이 측면 간격보다 성기면 전방 중첩이 측면보다 나빠져 "
                "사진측량 산출물이 성립하지 않는다(카메라 실측 확정 전 사용 가능한 상한)"
            )

    ring = aoi._to_enu_ring()
    anchor = aoi.anchor()

    if not _is_convex_ring(ring):
        raise RouteGenerationError(
            "NON_CONVEX_AOI — lawnmower 는 볼록 AOI 에서만 전체 커버를 보증할 수 "
            "있다(비볼록은 스캔선 사이·바깥 밴드가 무음으로 미커버될 수 있다). "
            "볼록 조각으로 분할해 별도 임무로 발급하라"
        )

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

    # 스캔선 y 배치(자율 재검토 F6, B 로 문턱 정정): 각 스캔선의 커버 폭이
    # ±spacing/2 라는 전제(볼록 AOI + A-2 실측 게이트가 이 전제의 실제 성립을
    # 최종 확인한다)에서 첫/마지막 선을 경계에서 spacing/2 안쪽에 두되, 선 수는
    # ceil 로 올려 실제 간격이 spacing **이하**가 되게 한다 — 간격이 성기어지는
    # 방향의 이탈은 커버리지 구멍(INV-010 위반)이므로 허용하지 않고, 조밀해지는
    # 방향만 허용한다. 스캔선이 경계 위에 정확히 놓이는 퇴화도 함께 제거된다.
    height = max_y - min_y
    usable = height - spacing_m
    # usable 이 부동소수 잡음 수준(_FOLD_EPSILON_M)일 때만 중앙선 1개로 접는다.
    # 그 이상(예: 0 < usable <= 0.1)은 접지 않고 선 2개를 유지해야 위 전제가
    # 수학적으로 유지된다 — usable<=0.1 을 통째로 접던 과거 문턱은 spacing<height
    # <=spacing+0.1 밴드 양끝에서 최대 5cm 미커버를 냈다(P3).
    if usable <= _FOLD_EPSILON_M:
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
    # 커버리지 실측(A-2)용 — 선별 세그먼트를 scan_ys 와 같은 순서로 보관한다(순서
    # 반전 전 원본, 즉 x_start<x_end 유지 — 구간 포함 검사가 단순해진다).
    all_segments: list[list[tuple[float, float]]] = []
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
                "sweep_direction_deg 를 조정해 재시도하라"
            )

        # 길이 0 퇴화 구간(스캔선이 국소최소 꼭짓점에 정확히 접함 — xs 에 같은 x 2개)
        # 은 동일 좌표 웨이포인트 쌍만 만들므로 버린다(자율 재검토 P2).
        segments = [
            (xs[k], xs[k + 1]) for k in range(0, len(xs), 2) if xs[k + 1] - xs[k] > 1e-9
        ]
        all_segments.append(segments)
        if line_index % 2 == 1:
            segments = [(b, a) for a, b in reversed(segments)]

        for x_start, x_end in segments:
            for x in _capture_xs(x_start, x_end, capture_interval_m):
                # 상한 검사를 루프 안에서 — 비볼록 다중 세그먼트(선당 2점 초과)
                # 에서도 대량 할당 전에 끊는다(재검토: 선 수 상한만으로는 볼록
                # 가정이라 톱니형 폴리곤이 우회했다).
                if len(waypoints) >= _MAX_WAYPOINTS:
                    raise RouteGenerationError(
                        f"웨이포인트가 WPML index 상한({_MAX_WAYPOINTS})을 넘는다 — "
                        "spacing·captureIntervalM 을 키우거나 구역을 나눠라"
                    )
                east, north = _rotate(x, y, angle)
                lat, lon = enu_to_wgs84(anchor.lat_deg, anchor.lon_deg, east, north)
                waypoints.append(
                    RouteWaypoint(lat_deg=lat, lon_deg=lon, altitude_m=altitude_m)
                )

    if not waypoints:
        raise RouteGenerationError("스캔선이 폴리곤과 교차하지 않았다 — 구역·간격을 확인하라")

    coverage_ratio = _measure_lawnmower_coverage_ratio(
        rotated, scan_ys, all_segments, spacing_m=spacing_m
    )
    if coverage_ratio < _MIN_COVERAGE_RATIO:
        raise RouteGenerationError(
            f"COVERAGE_BELOW_MINIMUM — 실측 커버 비율 {coverage_ratio:.4f} 가 하한 "
            f"{_MIN_COVERAGE_RATIO} 미만이다. 원인 후보: ① sweep_direction_deg 가 "
            "도형과 어긋남(조정하거나 자동 선택에 맡겨라) ② 경사변 도형(삼각형·"
            "사다리꼴)은 스와스가 세그먼트 끝점에서 종료로 모델링돼 어떤 sweep "
            "에서도 모서리 손실이 남는다 — spacing 을 줄이거나 구역을 나눠라"
        )

    return LawnmowerResult(waypoints=waypoints, coverage_ratio=coverage_ratio)
