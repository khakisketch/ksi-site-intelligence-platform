"""수평 좌표계 — EPSG 투영좌표계 재투영과 혼용 차단 (INV-020 수평축).

## 왜 화이트리스트인가

한국의 평면직각좌표계는 **두 세대가 공존한다**. 현행은 KGD2002(GRS80) 기반의
EPSG:5185~5188(서부/중부/동부/동해 원점)과 EPSG:5179(UTM-K)이고, 그 이전에는
Bessel 1841 타원체 기반의 EPSG:5173~5177 계열이 쓰였다. 두 세대의 좌표값은
**같은 지점에서 수백 미터 차이가 난다**.

문제는 이 차이가 눈에 안 띈다는 것이다. 어느 쪽 좌표든 X 는 20만m 대, Y 는
50~60만m 대의 그럴듯한 값이라 사람이 숫자만 보고는 판별하지 못한다. 도면·과거
성과가 구 좌표계로 들어오는 일은 실제로 흔하고, 그것을 KGD2002 로 착각해
현재 측량 결과와 섞으면 조용히 틀린 채로 모든 후속 계산이 진행된다.

그래서 `to_crs`/`from_crs` 를 자유 문자열로 열어두지 않고 **투영좌표계 쪽은
화이트리스트로 막는다.** 구 좌표계를 다뤄야 할 일이 실제로 생기면 그때 명시적
변환 경로를 설계해서 추가한다 — 조용히 통과시키지 않는다.

지리좌표계(EPSG:4326 등)는 입력·출력으로 자유롭게 허용한다. AOI 폴리곤이
WGS84 로 들어오고 래스터가 투영좌표계인 것이 정상 경로이기 때문이다.

## 축 순서

`Transformer.from_crs(..., always_xy=True)` 로 고정한다. EPSG 정의상 일부
좌표계의 공식 축 순서는 (북, 동)이라 이 플래그가 없으면 x/y 가 조용히 뒤바뀐다.
계약 테스트가 좌표값의 크기 범위로 이 실수를 잡는다.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError

# 중부원점 — 현장 대부분이 이 대역에 있어 기본값으로 둔다.
DEFAULT_CRS = "EPSG:5186"

# KGD2002(GRS80) 기반 현행 평면직각좌표계만 허용한다. Bessel 계열(5173~5177)은
# 의도적으로 제외 — 모듈 docstring 참조.
SUPPORTED_PROJECT_CRS = frozenset(
    {
        "EPSG:5185",  # 서부원점
        "EPSG:5186",  # 중부원점
        "EPSG:5187",  # 동부원점
        "EPSG:5188",  # 동해(울릉)원점
        "EPSG:5179",  # UTM-K (전국 단일)
    }
)


class UnsupportedCrsError(ValueError):
    """화이트리스트 밖이거나 해석할 수 없는 좌표계 — fail-closed."""


class CrsMismatchError(ValueError):
    """서로 다른 좌표계를 직접 비교·병합하려 했다 (INV-020)."""


def normalise_crs(crs: str) -> str:
    """``epsg:5186`` 같은 표기 차이를 정규 형태로 맞춘다.

    대소문자·공백 차이는 좌표계의 차이가 아니다 — 같은 좌표계를 다르다고
    거부하면 정당한 비교까지 막힌다.
    """
    if not crs or not crs.strip():
        raise UnsupportedCrsError("빈 문자열은 좌표계가 아니다")
    text = crs.strip()
    try:
        parsed = CRS.from_user_input(text)
    except CRSError as exc:
        raise UnsupportedCrsError(f"해석할 수 없는 좌표계: {crs!r}") from exc

    authority = parsed.to_authority()
    if authority is None:
        # EPSG 코드로 환원되지 않는 임의 WKT/PROJ 문자열. 계보를 문자열로
        # 비교할 수 없으므로 이 경로는 받지 않는다.
        raise UnsupportedCrsError(
            f"EPSG 권위 코드로 환원되지 않는 좌표계는 쓰지 않는다: {crs!r}"
        )
    return f"{authority[0]}:{authority[1]}"


def assert_supported_project_crs(crs: str) -> str:
    """투영좌표계 화이트리스트 검사. 통과하면 정규화된 값을 돌려준다."""
    normalised = normalise_crs(crs)
    if normalised not in SUPPORTED_PROJECT_CRS:
        raise UnsupportedCrsError(
            f"{normalised} 은 지원 투영좌표계가 아니다 — 허용: "
            f"{sorted(SUPPORTED_PROJECT_CRS)}. 구 측지계(Bessel, EPSG:5173~5177)를 "
            "현행 KGD2002 와 섞으면 수백 미터 오차가 조용히 들어온다"
        )
    return normalised


def assert_same_crs(*crs_values: str) -> str:
    """모든 값이 같은 좌표계인지 확인하고 정규 값을 돌려준다 (INV-020 강제 지점).

    비교·병합 연산의 입구에서 부른다. 표기만 다른 같은 좌표계는 통과시키고
    (:func:`normalise_crs`), 실제로 다른 좌표계는 거부한다.
    """
    if not crs_values:
        raise ValueError("비교할 좌표계가 주어지지 않았다 — 빈 비교를 '같다'로 답하지 않는다")

    normalised = [normalise_crs(value) for value in crs_values]
    first = normalised[0]
    mismatched = [value for value in normalised if value != first]
    if mismatched:
        raise CrsMismatchError(
            f"좌표계가 서로 다르다: {sorted(set(normalised))} — CRS 가 다른 산출물을 "
            "직접 비교·병합하지 않는다(INV-020). 한쪽을 먼저 재투영하라"
        )
    return first


@lru_cache(maxsize=64)
def _transformer(from_crs: str, to_crs: str) -> Transformer:
    """Transformer 생성은 비싸다 — 정규화된 쌍으로 캐시한다."""
    return Transformer.from_crs(from_crs, to_crs, always_xy=True)


def reproject_point(
    x: float, y: float, *, from_crs: str, to_crs: str
) -> tuple[float, float]:
    """점 하나를 재투영한다. 좌표 순서는 항상 (x=경도/동, y=위도/북)이다."""
    source = normalise_crs(from_crs)
    target = normalise_crs(to_crs)
    new_x, new_y = _transformer(source, target).transform(x, y)
    return (float(new_x), float(new_y))


def _reproject_ring(
    ring: list[Any], *, from_crs: str, to_crs: str
) -> list[list[float]]:
    converted: list[list[float]] = []
    for position in ring:
        x, y = reproject_point(
            float(position[0]), float(position[1]), from_crs=from_crs, to_crs=to_crs
        )
        converted.append([x, y])
    return converted


def reproject_geometry(
    geometry: dict[str, Any], *, from_crs: str, to_crs: str
) -> dict[str, Any]:
    """GeoJSON 지오메트리를 재투영한다.

    AOI 폴리곤(WGS84)을 래스터 좌표계로 옮겨 마스킹에 쓰는 것이 주 용도라
    ``Polygon``·``MultiPolygon``·``Point`` 만 다룬다. **모르는 타입은 통과시키지
    않는다** — 좌표가 변환되지 않은 채 "변환했다"고 흘러가면 마스크가 엉뚱한
    곳에 걸린다.

    3차원 좌표의 Z 값은 **변환하지 않고 버린다** — 이 함수는 수평축 전용이고,
    수직기준 변환은 :mod:`ksi_geo_spatial.vertical` 의 몫이다. 여기서 Z 를
    그대로 실어 보내면 "높이도 변환됐다"는 오해가 생긴다.
    """
    geometry_type = geometry.get("type")

    if geometry_type == "Point":
        x, y = reproject_point(
            float(geometry["coordinates"][0]),
            float(geometry["coordinates"][1]),
            from_crs=from_crs,
            to_crs=to_crs,
        )
        return {"type": "Point", "coordinates": [x, y]}

    if geometry_type == "Polygon":
        return {
            "type": "Polygon",
            "coordinates": [
                _reproject_ring(ring, from_crs=from_crs, to_crs=to_crs)
                for ring in geometry["coordinates"]
            ],
        }

    if geometry_type == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    _reproject_ring(ring, from_crs=from_crs, to_crs=to_crs)
                    for ring in polygon
                ]
                for polygon in geometry["coordinates"]
            ],
        }

    raise ValueError(
        f"재투영할 줄 모르는 지오메트리 타입: {geometry_type!r} — "
        "Point/Polygon/MultiPolygon 만 다룬다(변환되지 않은 좌표를 "
        "변환됐다고 흘려보내지 않는다)"
    )


__all__ = [
    "DEFAULT_CRS",
    "SUPPORTED_PROJECT_CRS",
    "CrsMismatchError",
    "UnsupportedCrsError",
    "assert_same_crs",
    "assert_supported_project_crs",
    "normalise_crs",
    "reproject_geometry",
    "reproject_point",
]
