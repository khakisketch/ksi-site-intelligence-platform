"""WorkArea — 현장에 영구적으로 사는 작업구역 1건 (M4-C).

## 왜 필요한가 — 구역이 매번 달라지면 시계열이 없다

지금까지 비교 구역은 **요청마다 사용자가 지도에 새로 그리는 값**이었다
(``comparison_requests``·``design_conformance_requests`` 의 ``zones``). 그 설계
자체는 옳다 — 이미 낸 리포트는 "그때 어느 범위로 쟀는지"를 스스로 답해야 하므로
구역은 참조가 아니라 값이어야 한다(대표자 확정 2026-08-10).

문제는 **다음 주의 같은 구역**이다. 사람이 폴리곤을 다시 그리면 좌표가 미세하게
달라지고, ``zone_fingerprint`` 는 좌표 문자열이라 그 둘은 서로 다른 구역이 된다.
그러면 "A공구가 지난주 대비 얼마나 진행됐나"를 이어 붙일 방법이 원리적으로 없다.

이 계약은 그 사이를 메운다 — **구역을 한 번 등록해 이름을 주고, 요청은 그것을
고른다.** 요청에 실리는 것은 여전히 폴리곤 **값**이고(계약·워커는 한 줄도 안
바뀐다), 달라지는 것은 그 값의 출처가 매번 새로 그린 그림이 아니라 등록된 자산이
된다는 점뿐이다.

## 기하는 불변이다 — 이름만 바꿀 수 있다

:attr:`WorkArea.polygon` 은 등록 후 바뀌지 않는다. 잘못 그렸으면 **새 구역을 만들고
:attr:`WorkArea.supersedes` 로 이전 것을 가리킨다**(:class:`DesignSurface` 가
REJECTED 의 복구 경로를 "되돌리기"가 아니라 "새 revision 재등록"으로 둔 것과 같은
규율). 기하를 제자리에서 고칠 수 있게 하면, 이미 그 구역으로 낸 리포트들이 가리키는
범위가 사후에 바뀌어 **과거 숫자가 조용히 다른 뜻이 된다.**

반대로 :attr:`WorkArea.name` 은 바뀔 수 있다 — 이름은 측정값이 아니라 라벨이고,
'A공구'를 'A공구(1차)'로 고쳐 부른다고 잰 범위가 달라지지 않는다.

## 이 계약이 검사하는 것과 검사하지 않는 것

검사한다: GeoJSON ``Polygon`` 타입 · 외곽 고리가 닫혀 있고 위치 4개 이상 ·
좌표가 유한한 수 · ``EPSG:4326`` 이면 경위도 범위. 이것들은 **통과시키면 나중에
래스터 마스킹 단계에서 사람이 이해할 수 없는 예외로 터지는** 것들이다.

검사하지 않는다: 자기교차(bow-tie) · 고리 방향(CW/CCW) · 구역 간 겹침 · 현장
AOI 안에 드는지. 앞의 둘은 rasterio 가 관용적으로 처리하고, 뒤의 둘은 **정당한
운용**이다 — 절토부와 성토부가 경계에서 겹칠 수 있고, 진입도로는 현장 외곽을
넘어갈 수 있다. 여기서 막으면 제품이 현장을 틀렸다고 우기게 된다.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel

#: 외곽 고리의 최대 위치 수. ``AreaOfInterest`` 의 꼭짓점 상한과 같은 성격의
#: 방어값이다 — 정상 작업구역은 수십 점이면 충분하고, 이보다 큰 입력은 실수이거나
#: 저장소를 부풀리려는 시도다.
MAX_RING_POSITIONS = 512

#: 이 계약이 경위도 범위를 검사하는 좌표계. 다른 투영좌표계는 값의 범위가
#: 제각각이라 여기서 판정하지 않는다(그 판정은 래스터와 맞춰보는 단계의 일이다).
_LONLAT_CRS = "EPSG:4326"


class WorkAreaStatus(StrEnum):
    """ACTIVE = 새 비교에 고를 수 있다. ARCHIVED = 고를 수 없되 과거 리포트는 그대로 남는다.

    삭제가 없는 이유 — 이 구역으로 낸 리포트들이 ``zoneId`` 로 이 id 를 들고 있다.
    지우면 그 리포트들이 "무슨 범위였는지"를 잃는다.
    """

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class WorkArea(_CamelModel):
    """작업구역 1건 — 현장 자산이며 요청마다 값으로 복사돼 나간다."""

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    work_area_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    #: 사람이 읽는 이름(예: 'A공구 절토부'). 유일성을 강제하지 않는다 — 같은 이름의
    #: 구역이 두 개인 것은 현장에서 실제로 일어나고, 그걸 막으면 등록이 실패한다.
    #: 화면이 이름과 함께 등록 시각을 보여 사람이 가른다.
    name: str = Field(min_length=1, max_length=200)
    #: GeoJSON Polygon. 요청의 ``zones[zoneId]`` 에 이 값이 그대로 복사된다.
    polygon: dict[str, Any]
    #: ``polygon`` 좌표의 좌표계. 요청의 ``zoneCrs`` 가 된다.
    crs: str = Field(min_length=1)
    status: WorkAreaStatus
    #: 이 구역이 대체하는 이전 구역의 id — 기하를 고칠 때 생기는 사슬.
    #: ``None`` 이면 최초 등록이다. 진척 시계열은 이 사슬을 **자동으로 잇지 않는다**
    #: (범위가 달라졌으므로 이어 붙이면 다른 것을 비교하게 된다) — 화면이 사슬을
    #: 보여주고 사람이 판단한다.
    supersedes: str | None = None
    created_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def _polygon_is_usable(self) -> WorkArea:
        _assert_polygon(self.polygon, crs=self.crs)
        if self.supersedes is not None and self.supersedes == self.work_area_id:
            raise ValueError(
                f"supersedes 가 자기 자신을 가리킨다: {self.work_area_id!r} — "
                "사슬이 순환하면 계보를 되짚을 수 없다"
            )
        return self


def _assert_polygon(polygon: dict[str, Any], *, crs: str) -> None:
    """래스터 마스킹까지 살아남을 수 있는 폴리곤인지 — 아니면 여기서 사람 말로 거부한다.

    이 검사가 없으면 같은 결함이 ``dsm_diff.volume_delta_in_polygon`` 의
    ``features.geometry_mask`` 에서 터지는데, 그건 **비교를 제출하고 워커가 돌기를
    기다린 뒤**다. 등록 시점에 잡으면 사용자가 지도를 아직 보고 있을 때 안다.
    """
    if not isinstance(polygon, dict):
        raise ValueError("polygon 은 GeoJSON object 여야 한다")
    geom_type = polygon.get("type")
    if geom_type != "Polygon":
        raise ValueError(
            f"polygon.type 은 'Polygon' 이어야 한다: {geom_type!r} — "
            "MultiPolygon·Feature 는 이 계약이 받지 않는다(구역 하나가 폴리곤 하나다)"
        )
    extra_keys = set(polygon) - {"type", "coordinates"}
    if extra_keys:
        raise ValueError(
            f"polygon 에 알 수 없는 키가 있다: {sorted(extra_keys)} — "
            "GeoJSON Polygon 은 type·coordinates 만 갖는다"
        )
    rings = polygon.get("coordinates")
    if not isinstance(rings, list) or not rings:
        raise ValueError("polygon.coordinates 는 비어 있지 않은 고리 배열이어야 한다")

    for index, ring in enumerate(rings):
        where = "외곽 고리" if index == 0 else f"구멍 고리 {index}"
        if not isinstance(ring, list):
            raise ValueError(f"{where}: 배열이 아니다")
        if len(ring) < 4:
            raise ValueError(
                f"{where}: 위치가 {len(ring)}개다 — 닫힌 폴리곤은 4개 이상이어야 한다"
                "(마지막이 첫 위치와 같아야 하므로 삼각형도 4개다)"
            )
        if len(ring) > MAX_RING_POSITIONS:
            raise ValueError(
                f"{where}: 위치가 {len(ring)}개로 상한 {MAX_RING_POSITIONS}개를 넘는다"
            )
        for position in ring:
            _assert_position(position, crs=crs, where=where)
        if list(ring[0][:2]) != list(ring[-1][:2]):
            raise ValueError(
                f"{where}: 닫혀 있지 않다 — 마지막 위치가 첫 위치와 같아야 한다"
                f"(첫 {ring[0][:2]}, 마지막 {ring[-1][:2]})"
            )


def _assert_position(position: Any, *, crs: str, where: str) -> None:
    if not isinstance(position, list | tuple) or len(position) < 2:
        raise ValueError(f"{where}: 위치는 [x, y] 형태여야 한다 — {position!r}")
    x, y = position[0], position[1]
    for value, axis in ((x, "x"), (y, "y")):
        # bool 은 int 의 하위형이라 isinstance 로는 걸러지지 않는다 — 좌표에
        # True 가 들어오면 1.0 으로 조용히 통과한다.
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{where}: {axis} 좌표가 수가 아니다 — {value!r}")
        if not math.isfinite(value):
            raise ValueError(f"{where}: {axis} 좌표가 유한하지 않다 — {value!r}")
    if crs.strip().upper() == _LONLAT_CRS:
        if not -180.0 <= float(x) <= 180.0:
            raise ValueError(f"{where}: 경도가 범위 밖이다 — {x!r}")
        if not -90.0 <= float(y) <= 90.0:
            raise ValueError(f"{where}: 위도가 범위 밖이다 — {y!r}")


__all__ = [
    "MAX_RING_POSITIONS",
    "WorkArea",
    "WorkAreaStatus",
]
