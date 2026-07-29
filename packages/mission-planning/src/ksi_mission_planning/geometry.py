"""AOI(Area of Interest) 폴리곤 지오메트리 — 구역→경로 생성의 입력 전제 (ADR-KSI-007).

좌표는 **WGS84 위경도**다 — 구역은 지도에서 그려지고(WGS84), WPML 웨이라인도
WGS84 고정(coordinateMode)이라 이 패키지 안에서는 변환이 필요 없다. site_frame
(EPSG:5186 등) 세계모델과의 연계는 Mission Contract 의 siteFrame 메타데이터가
소유하며, 여기서는 다루지 않는다.

미터 단위 계산(간격·거리)은 ``ksi_geo_core.frames`` 의 등장방형 근사 ENU 변환을
재사용한다 — 현장 스케일(수 km 이내)에서 충분한 정밀도이며, 새 지오데시 코드를
만들지 않는다(참고: frames.py 의 PORT 주석).

검증은 생성 시점 fail-closed 다: 비유한 좌표·범위 밖 위경도·꼭짓점 부족·중복
꼭짓점·자기교차·퇴화(면적 0) 폴리곤은 typed ``ValidationError`` 로 거부된다 —
잘못된 구역이 조용히 경로 생성기에 들어가면 그 산출물이 서명된 임무로 성립해
버리기 때문에, 게이트는 가장 이른 지점에 둔다.
"""

from __future__ import annotations

import math

from ksi_geo_core.frames import wgs84_to_enu
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

# "사실상 같은 점" 판정 거리(m) — 부동소수 잡음만 흡수하고 실제 기하는 바꾸지 않는 규모.
_EPSILON_M = 1e-6
# orient(외적, m²) 0 판정 허용오차 — 애매하면 교차로 본다(fail-closed 방향).
_EPSILON_M2 = 1e-6
# anchor 기준 최대 반경(m) — frames.py 등장방형 근사의 유효범위("수 km 이내") 강제.
# 날짜변경선 걸친 AOI(경도차 ~360°→east 수천 km)는 이 상한이 잡는다. **극지 퇴화는
# 이 상한이 잡지 않는다**(자율 재검토 C 정정 — 과거 주석은 거짓이었다: east 계산이
# anchor 위도의 cos(lat) 로 나뉘어 있어 극지 근방에서는 경도차가 커도 east 값이
# 오히려 작아지므로 이 반경 게이트를 통과해버린다). 극지는 아래
# ``_MAX_ABS_LATITUDE_DEG`` 게이트가 별도로 막는다.
_MAX_EXTENT_M = 10_000.0
# 꼭짓점 수 상한 — 자기교차 검사가 O(n²)라 미인증 입력의 CPU 소진 벡터가 되지 않게.
_MAX_VERTICES = 256
# 등장방형(equirectangular) 근사 유효권 상한(|위도|, 도) — cos(lat)→0 인 극지 근방은
# 동서 축척이 무너져(wgs84_to_enu 의 east 항이 cos(origin_lat) 로 나뉜다) 이 근사가
# 성립하지 않는다(자율 재검토 C). 80° 는 근사가 뚜렷이 붕괴하기 전의 보수적 여유.
_MAX_ABS_LATITUDE_DEG = 80.0


class GeoPoint(BaseModel):
    """WGS84 좌표 한 점. 순서 혼동(lat/lon ↔ lon/lat)을 필드명으로 차단한다."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, frozen=True, extra="forbid"
    )

    lat_deg: float = Field(ge=-90.0, le=90.0)
    lon_deg: float = Field(ge=-180.0, le=180.0)

    @model_validator(mode="after")
    def _must_be_finite(self) -> GeoPoint:
        if not (math.isfinite(self.lat_deg) and math.isfinite(self.lon_deg)):
            raise ValueError(f"좌표는 finite 여야 한다 (got {self.lat_deg!r}, {self.lon_deg!r})")
        return self


def _orient(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(
    a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]
) -> bool:
    """공선 전제에서 p 가 선분 ab 위(끝점 포함)에 있는가."""
    return (
        min(a[0], b[0]) - _EPSILON_M <= p[0] <= max(a[0], b[0]) + _EPSILON_M
        and min(a[1], b[1]) - _EPSILON_M <= p[1] <= max(a[1], b[1]) + _EPSILON_M
    )


def _segments_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    q1: tuple[float, float],
    q2: tuple[float, float],
) -> bool:
    """두 선분의 교차 여부 — 내부 교차뿐 아니라 **T-접촉·공선 중첩도 교차로 본다**.

    비인접 변 사이에는 어떤 접촉도 단순 폴리곤에서 성립하지 않으므로(끝점 공유는
    인접 변에서만 정당), 여기서는 관대할 이유가 없다. proper-교차만 보던 이전
    판정은 꼭짓점이 다른 변 위에 얹힌 폴리곤(자율 재검토 F3)을 통과시켰다.
    """
    d1 = _orient(q1, q2, p1)
    d2 = _orient(q1, q2, p2)
    d3 = _orient(p1, p2, q1)
    d4 = _orient(p1, p2, q2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True  # proper 교차
    # 접촉·공선: orient≈0 인 점이 상대 선분 위에 있으면 교차다
    if abs(d1) <= _EPSILON_M2 and _on_segment(q1, q2, p1):
        return True
    if abs(d2) <= _EPSILON_M2 and _on_segment(q1, q2, p2):
        return True
    if abs(d3) <= _EPSILON_M2 and _on_segment(p1, p2, q1):
        return True
    return bool(abs(d4) <= _EPSILON_M2 and _on_segment(p1, p2, q2))


class AreaOfInterest(BaseModel):
    """닫힌 단순 폴리곤 구역 — 마지막 꼭짓점→첫 꼭짓점 변이 암묵적으로 닫는다."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, frozen=True, extra="forbid"
    )

    vertices: list[GeoPoint] = Field(min_length=3, max_length=_MAX_VERTICES)

    @model_validator(mode="after")
    def _must_be_simple_polygon(self) -> AreaOfInterest:
        n = len(self.vertices)

        # 극지 게이트(자율 재검토 C) — ENU 계산 전에 먼저 걸러 다른 게이트의
        # 오판정(예: 극지 근방에서 실제로는 유효범위 밖인데 east 축소로 통과)을
        # 원천 차단한다.
        for v in self.vertices:
            if abs(v.lat_deg) > _MAX_ABS_LATITUDE_DEG:
                raise ValueError(
                    f"위도 {v.lat_deg}° 는 극지 게이트(|위도|<= {_MAX_ABS_LATITUDE_DEG}°) 밖이다 "
                    "— 등장방형 근사(equirectangular, cos(lat)→0 인 극지에서 동서 축척이 "
                    "무너진다) 유효권 밖은 구역이 될 수 없다"
                )

        enu = self._to_enu_ring()

        # 등장방형 근사 유효범위(frames.py "수 km 이내") + 날짜변경선 퇴화 차단
        # (극지 퇴화는 위에서 별도 게이트로 이미 처리됐다 — 이 게이트가 함께 잡지
        # 않는다, 자율 재검토 C).
        for east, north in enu:
            if math.hypot(east, north) > _MAX_EXTENT_M:
                raise ValueError(
                    f"AOI 가 anchor 기준 {_MAX_EXTENT_M/1000:.0f}km 를 벗어난다 — "
                    "등장방형 근사 유효범위 밖(대구역·날짜변경선·극지)은 구역이 될 수 없다"
                )

        # 중복 꼭짓점: 연속뿐 아니라 **비연속 재방문도** 거부한다(자율 재검토 F3 —
        # 같은 점을 두 번 지나는 링은 두 로브가 한 점에서 만나는 비단순 도형이다).
        for i in range(n):
            for j in range(i + 1, n):
                if math.hypot(enu[i][0] - enu[j][0], enu[i][1] - enu[j][1]) < _EPSILON_M:
                    kind = "연속" if j == i + 1 or (i == 0 and j == n - 1) else "비연속"
                    raise ValueError(
                        f"{kind} 중복 꼭짓점 (index {i}↔{j}) — 같은 점을 재방문하는 링은 "
                        "단순 폴리곤이 아니다"
                    )

        # 자기교차: 인접하지 않은 변 쌍의 교차(내부 교차 + T-접촉 + 공선 중첩)를
        # 전수 검사한다. O(n²)이지만 꼭짓점 상한이 _MAX_VERTICES 라 유계다.
        for i in range(n):
            for j in range(i + 1, n):
                if (j + 1) % n == i or (i + 1) % n == j:
                    continue  # 인접 변(끝점 공유)은 제외
                if _segments_intersect(enu[i], enu[(i + 1) % n], enu[j], enu[(j + 1) % n]):
                    raise ValueError(
                        f"자기교차 폴리곤 (변 {i}↔{j}) — 내부가 정의되지 않아 구역이 될 수 없다"
                    )

        if abs(self._signed_area_m2()) <= 0.0:
            raise ValueError("면적 0 폴리곤 — 구역이 아니다 (일직선 꼭짓점들)")
        return self

    # ── 파생 기하 (검증 통과 후에만 의미) ──────────────────────────────────

    def anchor(self) -> GeoPoint:
        """ENU 원점으로 쓸 기준점 — 꼭짓점 산술 평균(검증용 근사 중심)."""
        n = len(self.vertices)
        return GeoPoint(
            lat_deg=sum(v.lat_deg for v in self.vertices) / n,
            lon_deg=sum(v.lon_deg for v in self.vertices) / n,
        )

    def _to_enu_ring(self) -> list[tuple[float, float]]:
        """anchor 원점 기준 (east, north) m 꼭짓점 목록."""
        n = len(self.vertices)
        origin_lat = sum(v.lat_deg for v in self.vertices) / n
        origin_lon = sum(v.lon_deg for v in self.vertices) / n
        return [
            wgs84_to_enu(origin_lat, origin_lon, v.lat_deg, v.lon_deg) for v in self.vertices
        ]

    def _signed_area_m2(self) -> float:
        """shoelace 부호 면적(m²) — CCW 양수."""
        ring = self._to_enu_ring()
        total = 0.0
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            total += x1 * y2 - x2 * y1
        return total / 2.0

    def area_m2(self) -> float:
        return abs(self._signed_area_m2())
