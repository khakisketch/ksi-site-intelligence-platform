"""설계 대비 잔량 또는 2시점 DSM 차분의 diff 격자에서 변화 영역을 뽑는다
— 문턱→연결영역→최소면적→정렬 (M4-E + 전수 조사 Task 1).

## 새 원본이 아니라 이미 계산된 격자를 다시 읽는 것

``DesignConformanceReport.diffRaster`` 가 이미 담고 있는 표고차 격자를 읽어
"어디가 바뀌었나"를 구역이 아니라 **연결영역**으로 뽑는다. 그래서 설계 경로
모듈은 DSM 을 다시 차분하지 않는다 — 입력은 ``diff_raster.read_diff_geotiff``
가 돌려주는 :class:`~ksi_change_detection.dsm_diff.DiffResult` 하나뿐이다.
전수 조사 진입점(:func:`compute_survey_regions`)도 같은 ``DiffResult`` 를
읽는다 — 다만 설계 잔량이 아니라 ``align_and_diff`` 로 맞춘 2시점 DSM 차분
전체를 스캔한다. 라벨링·최소면적·``MAX_REGIONS``·cut/fill·벡터화·bbox·hull
초안은 두 경로가 하나의 코어(``_extract``)를 공유한다.

## 결정적이어야 한다 — AI/학습 모델을 쓰지 않는다

문턱값 비교·``scipy.ndimage.label``·픽셀 개수 필터·``rasterio.features.
shapes`` 벡터화는 전부 같은 입력에 같은 출력을 낸다. 이 결정성이 이 모듈의
유일한 계약 조건이다(테스트: 같은 diff 격자를 2회 추출해 region_id
집합·폴리곤 좌표열·cut/fill 값이 완전히 동일함을 강제한다).

## 절토·성토 산식은 ``volume_delta_in_polygon`` 과 동형이되 공유 헬퍼로 뽑지 않는다

``dsm_diff.volume_delta_in_polygon`` 의 cut/fill 계산 한 줄을 여기서도 그대로
쓴다(``fill = Σ(delta>0)·cellArea``, ``cut = -Σ(delta<0)·cellArea``). 그 함수를
공유 헬퍼로 리팩터하지 않는 이유는 그 파일에 기존 테스트가 이미 의존하고
있어서다 — 건드리는 위험이 재사용의 이득보다 크다(M4-E 확정 설계).

## 원본 값은 지우지 않는다

문턱 미만이거나 min_region_area_m2 미만이라 걸러진 라벨의 ``diff_m`` 값은
그대로 둔다 — ``diff_raster.py`` 의 "문턱 미만 셀은 지우지 않는다" 관례와
동형이다. 걸러진 개수만 ``filtered_region_count`` 로 노출한다.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

import numpy as np
from ksi_event_contracts.change_region_report import (
    MAX_REGIONS,
    ChangeRegion,
    ChangeRegionSetReport,
)
from ksi_event_contracts.region_extraction_policy import RegionExtractionPolicy
from ksi_event_contracts.survey_extraction_policy import SurveyExtractionPolicy
from ksi_event_contracts.volume_change_report import ZoneVolumeDelta
from ksi_geo_spatial.crs import ReprojectionFailedError, normalise_crs, reproject_geometry
from rasterio import features
from scipy import ndimage

from ksi_change_detection.convex_hull import ConvexHullError, convex_hull_2d
from ksi_change_detection.dsm_diff import DiffResult

logger = logging.getLogger(__name__)

#: hull 계산 또는 재검증 실패 시 리포트에 싣는 사유 코드.
HULL_CONSISTENCY_CHECK_FAILED = "HULL_CONSISTENCY_CHECK_FAILED"

#: 영역의 오차한계 — 설계 대비 잔량 diffRaster 에서 파생된 값이라 원본 리포트와
#: 같은 이유로 항상 없다(``run_design_conformance.DESIGN_SURFACE_NOT_MEASURED_
#: NOTE`` 와 같은 지위 — INV-024, 설계면은 측정물이 아니다).
_REGION_UNCERTAINTY_NOTE = (
    "이 영역은 설계 대비 잔량 diffRaster 에서 파생됐다 — 원본 리포트와 같은 이유로 "
    "오차한계가 없다(설계면은 측정물이 아니라 검증된 RMSE 가 없다, INV-024)"
)

#: 영역의 오차한계 — 전수 조사 diff 에서 파생된 값이라 항상 없다. 설계 경로와
#: 달리 양쪽 입력이 실측 DSM 이지만, 양 epoch 모두 검증된 RMSE 를 갖지 않으면
#: 차분의 오차를 말할 수 없다(INV-024, ``dsm_diff`` 모듈 docstring).
_SURVEY_UNCERTAINTY_NOTE = (
    "이 영역은 2시점 DSM 전수 조사 diff 에서 파생됐다 — 양 epoch 의 검증된 "
    "RMSE 가 없어 오차한계가 없다(INV-024)"
)

#: 전수 조사 리포트의 계보 앵커(``ChangeRegionSetReport.designConformanceId``
#: 자리)에 싣는 접두사. 조사에는 설계 대비 계산이 없으므로 그 id 를 그대로
#: 싣는 대신 ``survey:<surveyId>`` 형태로 싣는다 — 설계 리포트로 오인되지
#: 않게(접두사 없는 값은 설계 리포트 id 로 해석될 수 있다), 그리고 이 값으로
#: 설계 리포트를 조회하면 존재하지 않아 fail-closed 로 막히게. 계약 필드의
#: 타입·필수 조건은 그대로 두고, 값의 출처만 명시한다.
_SURVEY_ANCHOR_PREFIX = "survey:"

_WGS84_CRS = "EPSG:4326"


class RegionExtractionError(RuntimeError):
    """변화 영역 추출이 성립하지 않는다 — 부분 결과를 리포트로 만들지 않는다."""


def compute_change_regions(
    diff: DiffResult,
    *,
    threshold_m: float,
    policy: RegionExtractionPolicy,
    change_region_set_id: str,
    diff_raster_id: str,
    design_conformance_id: str,
    computed_at: datetime,
) -> ChangeRegionSetReport:
    """diff 격자에서 변화 영역을 뽑는다.

    순서(모듈 docstring): 문턱 비교 → 연결영역 라벨링 → 픽셀 개수로 최소면적
    미달 사전 필터(벡터화 이전에 걸러 비싼 연산을 생존자에게만 돌린다) →
    ``MAX_REGIONS`` 상한 검사(초과 시 fail-closed) → 생존 라벨마다 절토/성토·
    벡터화·bbox 측정불가율·hull 초안.

    Raises:
        RegionExtractionError: ``threshold_m`` 이 유효하지 않거나, 생존 영역이
            ``MAX_REGIONS`` 를 넘거나, 벡터화가 빈 결과를 냈다(마스크·라벨
            불일치 — 발생하면 이 함수의 버그다).
    """
    return _extract(
        diff,
        threshold_m=threshold_m,
        min_region_area_m2=policy.min_region_area_m2,
        connectivity=policy.connectivity,
        extraction_policy=policy,
        uncertainty_note=_REGION_UNCERTAINTY_NOTE,
        change_region_set_id=change_region_set_id,
        design_conformance_id=design_conformance_id,
        diff_raster_id=diff_raster_id,
        computed_at=computed_at,
    )


def compute_survey_regions(
    diff: DiffResult,
    *,
    policy: SurveyExtractionPolicy,
    change_region_set_id: str,
    survey_id: str,
    diff_raster_id: str,
    computed_at: datetime,
) -> ChangeRegionSetReport:
    """2시점 DSM 차분 전체를 스캔해 후보 구역을 뽑는다 — 설계 정합 전제 없음.

    설계 경로(:func:`compute_change_regions`)와 라벨링·최소면적·``MAX_REGIONS``
    fail-closed·per-label cut/fill·벡터화·bbox·hull 초안 코어(``_extract``)를
    공유한다. 다른 점은 셋뿐이다: 문턱값이 조사 정책 안에서 오고(따로 받지
    않는다 — 갈라질 자리가 없다), 오차한계 없음의 근거 문구가 조사 사유이며,
    계보 앵커(``designConformanceId`` 자리)에 설계 리포트 id 대신
    ``survey:<surveyId>`` 를 싣는다(모듈 상수 ``_SURVEY_ANCHOR_PREFIX``).

    Args:
        diff: ``align_and_diff`` 로 맞춘 2시점 DSM 차분 전체.
        policy: 이번 조사가 쓰는 기준값 한 벌 — 문턱 포함.
        change_region_set_id: 결과 리포트의 id — 호출자가 준다(이 함수가 만들면
            재실행마다 다른 리포트가 된다).
        survey_id: 이 조사를 낸 전수 조사 실행의 id — 계보 앵커의 뒷부분.
        diff_raster_id: 이 차분 격자를 낸 2시점 diff 자산 id — 새로 만들지 않고
            그대로 싣는다(이 함수는 새 래스터를 쓰지 않는다).
        computed_at: 결정성을 위해 인자로 받는다.

    Raises:
        RegionExtractionError: 유효 셀이 하나도 없거나(``align_and_diff`` 가 이미
            막은 all-NoData 가 어떤 경로로든 여기까지 오면 숫자를 내지 않는다 —
            "변화 0" 과 "잴 수 없음" 은 다른 사실이다), 문턱값이 유효하지
            않거나, 생존 영역이 ``MAX_REGIONS`` 를 넘거나, 벡터화가 빈 결과를
            냈다. INV-053 위반·CRS/수직기준 불일치·무효 중첩은 이 함수 앞단
            (``align_and_diff``·수직기준 브리지·Core preflight)의 기존 typed
            blocker/fail-closed 가 그대로 맡는다 — 이 함수는 그 게이트를
            우회하는 숫자를 만들지 않는다.
    """
    if not survey_id:
        raise RegionExtractionError("survey_id 가 비었다 — 계보 앵커를 지을 수 없다")
    if not diff.valid.any():
        raise RegionExtractionError(
            "차분에 유효 셀이 하나도 없다 — 전부 nodata 거나 겹치는 영역이 없다. "
            "'변화 0' 이 아니라 '잴 수 없음' 이므로 리포트를 만들지 않는다"
        )
    return _extract(
        diff,
        threshold_m=policy.threshold_m,
        min_region_area_m2=policy.min_region_area_m2,
        connectivity=policy.connectivity,
        extraction_policy=RegionExtractionPolicy(
            policy_version=policy.policy_version,
            min_region_area_m2=policy.min_region_area_m2,
            connectivity=policy.connectivity,
        ),
        uncertainty_note=_SURVEY_UNCERTAINTY_NOTE,
        change_region_set_id=change_region_set_id,
        design_conformance_id=f"{_SURVEY_ANCHOR_PREFIX}{survey_id}",
        diff_raster_id=diff_raster_id,
        computed_at=computed_at,
    )


def _extract(
    diff: DiffResult,
    *,
    threshold_m: float,
    min_region_area_m2: float,
    connectivity: int,
    extraction_policy: RegionExtractionPolicy,
    uncertainty_note: str,
    change_region_set_id: str,
    design_conformance_id: str,
    diff_raster_id: str,
    computed_at: datetime,
) -> ChangeRegionSetReport:
    """두 진입점이 공유하는 추출 코어 — 순서·산식·fail-closed 가 여기 하나뿐이다.

    순서(모듈 docstring): 문턱 비교 → 연결영역 라벨링 → 픽셀 개수로 최소면적
    미달 사전 필터(벡터화 이전에 걸러 비싼 연산을 생존자에게만 돌린다) →
    ``MAX_REGIONS`` 상한 검사(초과 시 fail-closed) → 생존 라벨마다 절토/성토·
    벡터화·bbox 측정불가율·hull 초안.
    """
    if threshold_m < 0.0 or not math.isfinite(threshold_m):
        raise RegionExtractionError(f"threshold_m 은 0 이상의 finite 여야 한다: {threshold_m!r}")

    binary = diff.valid & (np.abs(diff.diff_m) >= threshold_m)
    structure = ndimage.generate_binary_structure(2, 1 if connectivity == 4 else 2)
    labeled, n_labels = ndimage.label(binary, structure=structure)

    counts = np.bincount(labeled.ravel(), minlength=n_labels + 1)
    min_pixels = max(1, math.ceil(min_region_area_m2 / diff.cell_area_m2))
    survivor_labels = [label for label in range(1, n_labels + 1) if counts[label] >= min_pixels]
    filtered_region_count = n_labels - len(survivor_labels)

    if len(survivor_labels) > MAX_REGIONS:
        raise RegionExtractionError(
            f"생존 영역이 {len(survivor_labels)}개로 상한({MAX_REGIONS})을 넘는다 — "
            "minRegionAreaM2 를 올려 다시 시도해야 한다(조용한 상위-N 절단은 하지 않는다)"
        )

    bboxes = ndimage.find_objects(labeled)

    regions: list[ChangeRegion] = []
    for label in survivor_labels:
        mask = labeled == label
        pixel_count = int(counts[label])
        delta = diff.diff_m[mask]
        fill_m3 = float(delta[delta > 0].sum() * diff.cell_area_m2)
        cut_m3 = float(-delta[delta < 0].sum() * diff.cell_area_m2)
        area_m2 = float(pixel_count * diff.cell_area_m2)

        unmeasurable_ratio = _bbox_unmeasurable_ratio(diff, bboxes, label)
        polygon = _vectorize_label(mask, diff.transform)
        hull_polygon, hull_polygon_wgs84, hull_ratio, hull_failure = _try_build_hull(
            polygon, crs=diff.crs, region_area_m2=area_m2
        )

        region_id = f"{change_region_set_id}-r{label}"
        regions.append(
            ChangeRegion(
                region_id=region_id,
                volume=ZoneVolumeDelta(
                    zone_id=region_id,
                    cut_m3=cut_m3,
                    fill_m3=fill_m3,
                    net_m3=fill_m3 - cut_m3,
                    area_m2=area_m2,
                    threshold_m=threshold_m,
                    uncertainty_m3=None,
                    uncertainty_note=uncertainty_note,
                ),
                pixel_count=pixel_count,
                polygon=polygon,
                convex_hull_polygon=hull_polygon,
                convex_hull_polygon_wgs84=hull_polygon_wgs84,
                hull_overcapture_ratio=hull_ratio,
                aoi_draft_unavailable_reason=hull_failure,
                unmeasurable_ratio=unmeasurable_ratio,
            )
        )

    total_cell_count = int(diff.valid.size)
    valid_cell_count = int(diff.valid.sum())
    unmeasurable_cell_ratio = 1.0 - (valid_cell_count / total_cell_count)
    unmeasurable_area_m2 = float((total_cell_count - valid_cell_count) * diff.cell_area_m2)

    report = ChangeRegionSetReport(
        change_region_set_id=change_region_set_id,
        design_conformance_id=design_conformance_id,
        diff_raster_id=diff_raster_id,
        crs=diff.crs,
        threshold_m=threshold_m,
        extraction_policy=extraction_policy,
        regions=regions,
        filtered_region_count=filtered_region_count,
        unmeasurable_cell_ratio=unmeasurable_cell_ratio,
        unmeasurable_area_m2=unmeasurable_area_m2,
        total_cell_count=total_cell_count,
        computed_at=computed_at,
    )
    logger.info(
        "변화 영역 추출 완료: id=%s 생존 %d개(걸러짐 %d개)",
        change_region_set_id,
        len(regions),
        filtered_region_count,
    )
    return report


def _bbox_unmeasurable_ratio(diff: DiffResult, bboxes: list[Any], label: int) -> float:
    """라벨의 bounding box 안에서 측정 불가(nodata) 셀 비율 — 라벨 셀 자신이
    아니라 bbox 기준이다(``ChangeRegion.unmeasurableRatio`` 모듈 docstring)."""
    bbox = bboxes[label - 1]
    if bbox is None:  # pragma: no cover -- 생존 라벨은 항상 자기 bbox 를 갖는다
        return 0.0
    row_slice, col_slice = bbox
    bbox_cell_count = (row_slice.stop - row_slice.start) * (col_slice.stop - col_slice.start)
    if bbox_cell_count <= 0:  # pragma: no cover -- find_objects 는 빈 슬라이스를 내지 않는다
        return 0.0
    invalid_in_bbox = int((~diff.valid[bbox]).sum())
    return invalid_in_bbox / bbox_cell_count


def _vectorize_label(mask: np.ndarray, transform: Any) -> dict[str, Any]:
    """라벨 하나의 boolean 마스크를 GeoJSON 폴리곤으로 벡터화한다.

    ``connectivity=8`` 을 고정한다 — 이 마스크는 이미 한 라벨(scipy 의 연결
    규칙으로 이미 하나의 연결영역)만 True 이므로, 여기서 연결성을 더 관대하게
    잡아도 다른 라벨과 섞일 일이 없다. 대신 같은 라벨 안에서 대각선으로만
    이어진 셀들을 GDAL 이 하나의 폴리곤으로 그리게 해, 불필요하게 조각난
    MultiPolygon 을 피한다.

    그래서 아래 MultiPolygon 결합 분기는 ``compute_change_regions`` 경로에서는
    실행되지 않는다 — 라벨 마스크는 4-연결이든 8-연결이든 항상 하나의 8-연결
    성분이고, GDAL 은 그런 성분을 Polygon 하나로 낸다(대각선 계단·코너 접촉·
    도넛·체커보드 전부 단일 Polygon 으로 나오는 것을 실측했다. 구멍과 자기접촉은
    같은 폴리곤의 내부 링이 되지, 별도 shape 로 갈라지지 않는다). 이 분기는
    그 GDAL 동작이 바뀌었을 때를 대비한 방어이고, 테스트가 이 함수를 직접 불러
    계약으로 고정한다(``test_region_extraction.py`` 의
    ``test_the_multipolygon_join_is_defensive_and_stays_correct_downstream``).
    """
    shapes = [
        geom
        for geom, value in features.shapes(
            mask.astype(np.uint8), mask=mask, connectivity=8, transform=transform
        )
        if value == 1
    ]
    if not shapes:  # pragma: no cover -- 생존 라벨은 최소 1픽셀을 갖는다
        raise RegionExtractionError("생존 라벨의 벡터화 결과가 비었다 — 마스크와 라벨이 불일치한다")
    if len(shapes) == 1:
        return dict(shapes[0])

    polygons: list[Any] = []
    for geom in shapes:
        if geom["type"] == "Polygon":
            polygons.append(geom["coordinates"])
        # pragma 이유는 아래 else 와 같다 — features.shapes 는 Polygon 만 낸다
        # (무작위 마스크 4,000회 전수 검사에서 MultiPolygon 0건).
        elif geom["type"] == "MultiPolygon":  # pragma: no cover
            polygons.extend(geom["coordinates"])
        else:  # pragma: no cover -- GDAL 이 이 두 타입 외에는 내지 않는다
            raise RegionExtractionError(
                f"벡터화가 알 수 없는 지오메트리 타입을 냈다: {geom['type']!r}"
            )
    return {"type": "MultiPolygon", "coordinates": polygons}


def _exterior_points(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    """폴리곤(또는 멀티폴리곤)의 모든 외곽선 꼭짓점 — hull 입력이다."""
    if geometry["type"] == "Polygon":
        rings = [geometry["coordinates"][0]]
    elif geometry["type"] == "MultiPolygon":
        rings = [part[0] for part in geometry["coordinates"]]
    else:  # pragma: no cover -- _vectorize_label 은 이 두 타입만 낸다
        raise RegionExtractionError(f"알 수 없는 폴리곤 타입: {geometry['type']!r}")
    points: list[tuple[float, float]] = []
    for ring in rings:
        points.extend((float(x), float(y)) for x, y in ring)
    return points


def _close_ring_as_polygon(ring: list[tuple[float, float]]) -> dict[str, Any]:
    closed = [[x, y] for x, y in ring] + [[ring[0][0], ring[0][1]]]
    return {"type": "Polygon", "coordinates": [closed]}


def _polygon_area(ring: list[tuple[float, float]]) -> float:
    """shoelace 면적(절댓값, m²) — 열린 링(첫 점 반복 없음) 입력."""
    n = len(ring)
    total = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _try_build_hull(
    polygon: dict[str, Any], *, crs: str, region_area_m2: float
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, float | None, str | None]:
    """볼록 껍질 초안 — 실패하면 ``(None, None, None, 사유)`` 로 폴백한다.

    영역 하나의 기하 실패가 전체 응답을 죽이면 안 된다(M4-E 확정 설계) —
    ``ConvexHullError``(계산·재검증 실패) 와 ``ReprojectionFailedError``
    (``reproject_geometry`` 가 inf/nan 을 냈다, ``ksi_geo_spatial.crs`` 가
    이번 세션에 fail-closed 로 고친 그 예외) 를 함께 이 폴백 경로에서 처리한다.
    """
    try:
        points = _exterior_points(polygon)
        hull_ring = convex_hull_2d(points)
        hull_polygon = _close_ring_as_polygon(hull_ring)
        hull_polygon_wgs84 = (
            hull_polygon
            if normalise_crs(crs) == normalise_crs(_WGS84_CRS)
            else reproject_geometry(hull_polygon, from_crs=crs, to_crs=_WGS84_CRS)
        )
    except (ConvexHullError, ReprojectionFailedError) as exc:
        logger.info("영역 hull 계산이 실패해 이 영역만 초안 없이 넘어간다: %s", exc)
        return None, None, None, HULL_CONSISTENCY_CHECK_FAILED

    hull_area_m2 = _polygon_area(hull_ring)
    ratio = hull_area_m2 / region_area_m2 if region_area_m2 > 0.0 else None
    return hull_polygon, hull_polygon_wgs84, ratio, None


__all__ = [
    "HULL_CONSISTENCY_CHECK_FAILED",
    "RegionExtractionError",
    "compute_change_regions",
    "compute_survey_regions",
]
