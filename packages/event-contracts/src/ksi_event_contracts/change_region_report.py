"""ChangeRegionSetReport — 설계 대비 잔량의 diffRaster에서 뽑은 "어디가 바뀌었나" (M4-E).

## DesignConformanceReport 의 파생이지 새 원본이 아니다

이 리포트는 새 측정이 아니라 이미 기록된 :class:`~ksi_event_contracts.
design_conformance_report.DesignConformanceReport` 의 ``diffRaster`` 를
문턱→연결영역→최소면적으로 다시 읽은 것이다. 그래서 값 하나를 새로 재는 대신
**참조 셋의 일치**가 이 계약의 핵심이다: ``designConformanceId``·``diffRasterId``·
``crs``·``thresholdM`` 이 원본 리포트와 갈라지면 "이 영역이 어느 지도에서
나왔는지"가 되짚어지지 않는다(``design_conformance_report.py`` 모듈
docstring과 같은 근거).

## ``ChangeRegion.volume`` 이 ``ZoneVolumeDelta`` 를 재사용하는 이유

절토·성토·순증감의 부호 규약과 자기정합 검증(``_net_matches_cut_and_fill``)이
이미 있다. 새로 정의하면 같은 뜻의 값이 두 벌 생기고 한쪽만 고쳐지는 날이
온다(``design_conformance_report.py`` 가 같은 이유로 이 클래스를 재사용한
전례를 그대로 따른다). ``zoneId`` 자리에는 ``regionId`` 를 싣는다.

## ``hullOvercaptureRatio`` — 볼록 껍질이 실제보다 얼마나 넓게 도는가

이 저장소는 비볼록 대응 정공법(boustrophedon 셀 분할 등)을 채택하지 않는다
(M4-E 확정 설계 §명시적으로 범위 밖). 대신 영역의 볼록 껍질을 그대로
재관찰 초안(AOI)으로 쓰고, 그 껍질이 실제 변화 영역보다 얼마나 과대한지를
이 비율로 드러낸다 — 자동 거부 문턱은 없다(이 저장소에 "얼마나 넓으면 너무
넓다"의 선례가 없어 임의 숫자를 새로 짓지 않는다). 볼록 껍질은 원본보다
좁을 수 없으므로 이 값은 항상 1.0 이상이어야 하고, 부동소수 여유를 두고
0.999 이상을 강제한다.

## ``unmeasurableRatio`` 는 라벨 자신이 아니라 bounding box 로 잰다

라벨 자신의 셀은 마스크 구성상 전부 valid 다(``diff.valid`` 를 문턱 판정
이전에 이미 AND 로 걸었으므로) — 그래서 라벨 셀만으로 재면 항상 0 이 나와
무의미하다. bounding box 로 넓혀서 재면 "이 경계 바로 옆에 데이터 구멍이 있어
실제 변화가 더 이어졌을 수 있다"는 신호가 된다.

## ``filteredRegionCount`` 를 숨기지 않는다

``minRegionAreaM2`` 미만이라 걸러진 라벨의 존재를 결과에서 지우면, 화면은
"작은 변화가 없었다"와 "있었지만 걸렀다"를 구분할 수 없다. 값을 숨기지
않는다는 이 저장소의 원칙(``diff_raster.py`` "문턱 미만 셀은 지우지 않는다")을
집계 결과에도 그대로 적용한다.

## ``MAX_REGIONS`` — fail-closed, 조용한 상위-N 절단 없음

생존 영역이 이 상수를 넘으면 계산 계층(``ksi_change_detection.region_
extraction``)이 예외를 던진다. 조용히 상위 N개만 골라 리포트를 만들면
"몇 개가 더 있었는지"가 영원히 사라진다 — 호출자가 ``minRegionAreaM2`` 를
올려 다시 계산해야 한다.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.region_extraction_policy import RegionExtractionPolicy
from ksi_event_contracts.volume_change_report import ZoneVolumeDelta

#: 생존 영역 개수 상한 — 초과 시 컴퓨트 계층이 예외로 fail-closed 한다(모듈 docstring).
MAX_REGIONS = 500

#: threshold 대조 허용 오차 — ``design_conformance_report._THRESHOLD_TOLERANCE_M`` 과
#: 같은 자릿수(같은 상수에서 복사된 값들이라 원래 비트까지 같지만, JSON 왕복
#: 가능성을 감안한 아주 좁은 절대 오차).
_THRESHOLD_TOLERANCE_M = 1e-12

#: 볼록 껍질 면적 / 실제 영역 면적의 하한 — 볼록 껍질은 원본보다 좁을 수 없다
#: (부동소수 여유, 모듈 docstring).
_MIN_HULL_OVERCAPTURE_RATIO = 0.999


class ChangeRegion(_CamelModel):
    """변화 영역 한 건 — 폴리곤·체적·hull 초안·측정 불가 신호를 함께 싣는다."""

    region_id: str = Field(min_length=1)
    #: 절토·성토·순증감 — ``ZoneVolumeDelta`` 재사용(모듈 docstring), ``zoneId``
    #: 자리에 ``regionId`` 를 싣는다.
    volume: ZoneVolumeDelta
    pixel_count: int = Field(ge=1)
    #: 이 영역의 실제 경계(native CRS, GeoJSON Polygon/MultiPolygon).
    polygon: dict[str, Any]
    #: 볼록 껍질 초안(native CRS) — hull 계산이 실패했을 때만 ``None``.
    convex_hull_polygon: dict[str, Any] | None = None
    #: 볼록 껍질 초안(WGS84) — 재관찰 AOI 초안이 되는 자리. hull 계산이 실패했을
    #: 때만 ``None``.
    convex_hull_polygon_wgs84: dict[str, Any] | None = None
    #: 볼록 껍질 면적 / 실제 영역 면적 — hull 계산이 실패했을 때만 ``None``.
    hull_overcapture_ratio: float | None = None
    #: hull 계산이 실패했을 때만 채워지는 사유(예: ``HULL_CONSISTENCY_CHECK_FAILED``).
    #: 채워지면 위 세 필드는 전부 ``None`` 이다 — 실패한 hull 을 절반만 실으면
    #: 화면이 그 절반을 유효한 값으로 읽는다.
    aoi_draft_unavailable_reason: str | None = None
    #: 이 영역의 bounding box 안에서 측정 불가(nodata) 셀의 비율 — 라벨 셀
    #: 자신이 아니라 bbox 기준이다(모듈 docstring).
    unmeasurable_ratio: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_hull_consistency(self) -> ChangeRegion:
        if self.aoi_draft_unavailable_reason is not None and (
            self.convex_hull_polygon is not None
            or self.convex_hull_polygon_wgs84 is not None
            or self.hull_overcapture_ratio is not None
        ):
            raise ValueError(
                f"{self.region_id}: aoiDraftUnavailableReason 이 있으면 hull 관련 필드는 "
                "전부 null 이어야 한다 — 실패한 hull 을 절반만 실으면 화면이 그 절반을 "
                "유효한 값으로 읽는다"
            )
        return self


class ChangeRegionSetReport(_CamelModel):
    """contracts 왕복 대상 — 설계 대비 잔량 diffRaster 하나에서 뽑은 변화 영역 전체."""

    schema_version: Literal["1.0"] = "1.0"
    change_region_set_id: str = Field(min_length=1)
    #: 이 diffRaster 를 낸 설계 대비 잔량 리포트 — 참조가 아니라 이 리포트가
    #: "어느 지도에서 나왔는지"를 스스로 답하기 위한 앵커다.
    design_conformance_id: str = Field(min_length=1)
    diff_raster_id: str = Field(min_length=1)
    crs: str = Field(min_length=1)
    threshold_m: float = Field(ge=0.0)
    #: 이 계산이 실제로 쓴 추출 기준값 스냅샷 — 화면은 이 값을 읽기 전용으로
    #: 표시한다(대표자 확정, ``region_extraction_policy.py`` 모듈 docstring).
    extraction_policy: RegionExtractionPolicy
    #: 0개도 유효하다 — "변화가 없었다"와 "아직 계산 안 됐다"는 다른 사실이고,
    #: 빈 리스트가 후자를 뜻하지 않는다(이 리포트 자체의 존재가 "계산했다"다).
    regions: list[ChangeRegion] = Field(default_factory=list)
    #: minRegionAreaM2 미만이라 걸러진 라벨 개수 — 항상 노출한다(모듈 docstring).
    filtered_region_count: int = Field(ge=0)
    #: 전체 풋프린트 기준 측정 불가 셀 비율(``ChangeRegion.unmeasurableRatio`` 와
    #: 달리 영역이 아니라 래스터 전체 기준).
    unmeasurable_cell_ratio: float = Field(ge=0.0, le=1.0)
    unmeasurable_area_m2: float = Field(ge=0.0)
    total_cell_count: int = Field(ge=1)
    computed_at: datetime

    @model_validator(mode="after")
    def _check_self_consistency(self) -> ChangeRegionSetReport:
        if self.computed_at.tzinfo is None:
            raise ValueError("computedAt 은 tz-aware(offset 포함) 여야 한다")

        region_ids = [r.region_id for r in self.regions]
        if len(set(region_ids)) != len(region_ids):
            raise ValueError(f"regionId 가 중복된다: {region_ids} — 같은 영역이 두 번 실렸다")

        divergent = [
            r.region_id
            for r in self.regions
            if not math.isclose(
                r.volume.threshold_m, self.threshold_m, abs_tol=_THRESHOLD_TOLERANCE_M
            )
        ]
        if divergent:
            raise ValueError(
                f"영역의 volume.thresholdM 이 리포트의 thresholdM({self.threshold_m}) 과 "
                f"다르다: {divergent} — 범례가 말하는 기준과 집계에 쓴 기준이 다르면 지도와 "
                "표가 조용히 갈린다"
            )

        for region in self.regions:
            ratio = region.hull_overcapture_ratio
            if ratio is None:
                continue
            if not math.isfinite(ratio):
                raise ValueError(f"{region.region_id}.hullOvercaptureRatio 는 finite 여야 한다")
            if ratio < _MIN_HULL_OVERCAPTURE_RATIO:
                raise ValueError(
                    f"{region.region_id}.hullOvercaptureRatio({ratio}) 가 "
                    f"{_MIN_HULL_OVERCAPTURE_RATIO} 미만이다 — 볼록 껍질은 원본 영역보다 "
                    "좁을 수 없다"
                )
        return self


__all__ = [
    "MAX_REGIONS",
    "ChangeRegion",
    "ChangeRegionSetReport",
]
