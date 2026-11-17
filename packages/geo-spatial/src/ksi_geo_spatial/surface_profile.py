"""표면 단면(profile) — 사용자가 그은 선을 따라 DSM/DTM 한 장의 표고를 읽는다.

이 모듈은 **순수 계산 도구**다. 자료 접근 권한, 고객 권리, 반출 동의, 정확도 승인을
만들지 않는다. 호출자(Core 가 승인한 워커)가 정확한 자산의 비공개 바이트 경로와
유한한 정책을 넘기며, 수직기준·처리 프로필의 호환성(INV-053)은 호출 전에 Core 가
판정한다. 여기서 나오는 숫자는 "이 격자에서 이 선을 따라 읽은 표고"일 뿐 측량
정확도가 아니다.

## 지키는 규칙

- **모르면 값이 없다.** 표면 밖·NoData·보간 이웃 부족은 ``elevation_m=None`` 과 사유다.
  0 이나 이웃 값, 직선 연결로 메우지 않는다. 격자 가장자리 반 픽셀 안은 외삽하지
  않는다(``terrain.py`` 와 같은 픽셀 중심 이중선형 보간).
- **읽는 양을 제한한다.** rasterio 는 1×1 창도 그 창이 걸친 저장 블록 전체를 읽는다.
  그래서 표본 수만이 아니라 (1) 모든 표본을 덮는 **한 번의 창** 크기와 (2) 원본의
  **저장 블록** 크기를 정책으로 막는다. 한도를 넘으면 조용히 줄이지 않고 거부한다.
- **수평축은 투영좌표계 화이트리스트만.** 거리를 미터로 말하려면 투영좌표계여야 한다.
  지리좌표계 래스터는 거부한다(도 단위 거리를 미터로 오해하지 않게).
- **두 표면 비교는 같은 계획으로 읽은 결과끼리만** 한다. 같은 선·같은 표본 위치가
  아니면 거부하고, 좌표계가 다르면 INV-020 대로 거부한다.
- **회전·배율 래스터는 받지 않는다.** 북쪽이 위인 정방 격자만 읽는다. 스케일/오프셋
  메타데이터가 있으면 조용히 무시하지 않고 거부한다.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np
import rasterio
from rasterio.errors import RasterioIOError
from rasterio.windows import Window

from ksi_geo_spatial.crs import (
    SUPPORTED_PROJECT_CRS,
    CrsMismatchError,
    ReprojectionFailedError,
    UnsupportedCrsError,
    assert_same_crs,
    assert_supported_project_crs,
    normalise_crs,
    reproject_point,
)

_WGS84 = "EPSG:4326"
#: 부동소수 오차로 격자 중심 표본이 "거의 중심"이 되어 이웃을 요구하지 않게 하는 허용치(픽셀 단위).
_CENTRE_SNAP = 1e-9
#: 같은 거리로 보는 표본 간격 허용치(m).
_DISTANCE_TOLERANCE_M = 1e-9


class SurfaceProfileErrorReason(StrEnum):
    INVALID_LINE = "INVALID_LINE"
    INVALID_SAMPLING = "INVALID_SAMPLING"
    TOO_MANY_VERTICES = "TOO_MANY_VERTICES"
    TOO_MANY_SAMPLES = "TOO_MANY_SAMPLES"
    LINE_TOO_LONG = "LINE_TOO_LONG"
    UNSUPPORTED_CRS = "UNSUPPORTED_CRS"
    REPROJECTION_FAILED = "REPROJECTION_FAILED"
    CRS_MISMATCH = "CRS_MISMATCH"
    UNREADABLE_RASTER = "UNREADABLE_RASTER"
    UNSUPPORTED_RASTER = "UNSUPPORTED_RASTER"
    SOURCE_BLOCK_TOO_LARGE = "SOURCE_BLOCK_TOO_LARGE"
    WINDOW_TOO_LARGE = "WINDOW_TOO_LARGE"
    PLAN_MISMATCH = "PLAN_MISMATCH"


class SurfaceProfileError(ValueError):
    """단면을 만들 수 없다 — 사유는 typed, 값은 지어내지 않는다."""

    def __init__(self, reason: SurfaceProfileErrorReason, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail


class SampleInvalidReason(StrEnum):
    #: 표본점이 래스터 범위 밖이다.
    OUTSIDE_SURFACE = "OUTSIDE_SURFACE"
    #: 범위 안이지만 이중선형 보간에 필요한 이웃 셀이 격자 밖이다(가장자리 반 픽셀).
    #: 외삽하지 않는다.
    INSUFFICIENT_NEIGHBORS = "INSUFFICIENT_NEIGHBORS"
    #: 보간에 필요한 이웃 셀 중 NoData·비유한 값이 있다.
    NODATA = "NODATA"


class ComparisonInvalidReason(StrEnum):
    BASELINE_UNAVAILABLE = "BASELINE_UNAVAILABLE"
    CURRENT_UNAVAILABLE = "CURRENT_UNAVAILABLE"
    BOTH_UNAVAILABLE = "BOTH_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class SurfaceProfilePolicy:
    """서버가 정하는 유한한 한도. 기본값을 두지 않는다 — 호출자가 반드시 정한다."""

    maximum_vertices: int
    maximum_samples: int
    maximum_line_length_m: float
    #: 모든 표본을 덮는 단일 읽기 창의 최대 셀 수.
    maximum_window_cells: int
    #: 원본 한 저장 블록의 최대 셀 수. 래스터 전체가 이 값 이하이면 블록 검사를 건너뛴다.
    maximum_source_block_cells: int

    def __post_init__(self) -> None:
        for name in (
            "maximum_vertices",
            "maximum_samples",
            "maximum_window_cells",
            "maximum_source_block_cells",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} 은 1 이상의 정수여야 한다")
        if self.maximum_vertices < 2:
            raise ValueError("maximum_vertices 는 2 이상이어야 한다")
        if not (math.isfinite(self.maximum_line_length_m) and self.maximum_line_length_m > 0):
            raise ValueError("maximum_line_length_m 은 유한한 양수여야 한다")


@dataclass(frozen=True, slots=True)
class SurfaceProfilePlan:
    """같은 선·같은 표본 위치 — 여러 표면을 같은 위치에서 읽고 비교하기 위한 고정 계획."""

    horizontal_crs: str
    line_length_m: float
    sample_spacing_m: float
    distances_m: tuple[float, ...]
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class ProfileSourceFacts:
    horizontal_crs: str
    width: int
    height: int
    cell_size_x: float
    cell_size_y: float
    block_rows: int
    block_cols: int

    @property
    def ground_sample_distance_m(self) -> float:
        """표본 간격 기본값으로 쓰는 격자 해상도(큰 쪽)."""
        return max(self.cell_size_x, self.cell_size_y)


@dataclass(frozen=True, slots=True)
class ProfileSample:
    index: int
    distance_m: float
    x: float
    y: float
    elevation_m: float | None
    invalid_reason: SampleInvalidReason | None


@dataclass(frozen=True, slots=True)
class SurfaceProfile:
    plan: SurfaceProfilePlan
    source: ProfileSourceFacts
    samples: tuple[ProfileSample, ...]
    #: 실제로 읽은 창의 셀 수(0 이면 읽지 않음). 한도 검증의 증거로 보존한다.
    window_cells_read: int

    @property
    def valid_count(self) -> int:
        return sum(1 for sample in self.samples if sample.elevation_m is not None)


@dataclass(frozen=True, slots=True)
class ComparisonSample:
    index: int
    distance_m: float
    x: float
    y: float
    baseline_m: float | None
    current_m: float | None
    #: current − baseline. 둘 중 하나라도 없으면 None 이다(0 이 아니다).
    difference_m: float | None
    invalid_reason: ComparisonInvalidReason | None


@dataclass(frozen=True, slots=True)
class SurfaceProfileComparison:
    plan: SurfaceProfilePlan
    samples: tuple[ComparisonSample, ...]
    valid_count: int
    #: 양수 쪽 최대(현재가 더 높음)와 음수 쪽 최대(현재가 더 낮음). 유효 표본이 없으면 None.
    largest_rise_m: float | None
    largest_drop_m: float | None


def _fail(reason: SurfaceProfileErrorReason, detail: str) -> SurfaceProfileError:
    return SurfaceProfileError(reason, detail)


def _accept_line_crs(crs: str) -> str:
    try:
        normalised = normalise_crs(crs)
    except UnsupportedCrsError as exc:
        raise _fail(
            SurfaceProfileErrorReason.UNSUPPORTED_CRS, f"선 좌표계를 해석할 수 없다: {exc}"
        ) from exc
    if normalised != _WGS84 and normalised not in SUPPORTED_PROJECT_CRS:
        raise _fail(
            SurfaceProfileErrorReason.UNSUPPORTED_CRS,
            f"{normalised} 은 선 좌표계로 지원하지 않는다 — "
            f"허용: EPSG:4326 및 {sorted(SUPPORTED_PROJECT_CRS)}",
        )
    return normalised


def _finite_vertices(vertices: Sequence[Sequence[float]]) -> list[tuple[float, float]]:
    parsed: list[tuple[float, float]] = []
    for vertex in vertices:
        try:
            if isinstance(vertex, (str, bytes)) or len(vertex) != 2:
                raise TypeError("vertex 는 (x, y) 두 값이다")
            x, y = vertex
            if isinstance(x, bool) or isinstance(y, bool):
                raise TypeError("bool 은 좌표가 아니다")
            parsed_x, parsed_y = float(x), float(y)
        except (TypeError, ValueError) as exc:
            raise _fail(
                SurfaceProfileErrorReason.INVALID_LINE, f"꼭짓점을 읽을 수 없다: {vertex!r}"
            ) from exc
        if not (math.isfinite(parsed_x) and math.isfinite(parsed_y)):
            raise _fail(SurfaceProfileErrorReason.INVALID_LINE, "꼭짓점 좌표는 유한해야 한다")
        parsed.append((parsed_x, parsed_y))
    return parsed


def plan_surface_profile(
    vertices: Sequence[Sequence[float]],
    *,
    vertices_crs: str,
    horizontal_crs: str,
    sample_spacing_m: float,
    policy: SurfaceProfilePolicy,
) -> SurfaceProfilePlan:
    """선 꼭짓점과 표본 간격에서 고정된 표본 위치 계획을 만든다.

    - 꼭짓점은 ``horizontal_crs``(투영좌표계 화이트리스트)로 옮긴 뒤 그 평면에서 거리를 잰다.
    - 표본은 시작점에서 ``sample_spacing_m`` 간격이며, 모든 꼭짓점과 끝점을 반드시 포함한다.
    - 연속한 같은 꼭짓점(더블클릭)은 하나로 합친다. 길이가 0이면 거부한다.
    - 한도를 넘으면 간격을 조용히 늘리지 않고 거부한다.
    """
    if isinstance(sample_spacing_m, bool) or not (
        isinstance(sample_spacing_m, (int, float))
        and math.isfinite(sample_spacing_m)
        and sample_spacing_m > 0
    ):
        raise _fail(
            SurfaceProfileErrorReason.INVALID_SAMPLING, "표본 간격은 유한한 양수(m)여야 한다"
        )
    if len(vertices) > policy.maximum_vertices:
        raise _fail(
            SurfaceProfileErrorReason.TOO_MANY_VERTICES,
            f"꼭짓점 {len(vertices)}개가 한도 {policy.maximum_vertices}개를 넘는다",
        )
    parsed = _finite_vertices(vertices)
    source_crs = _accept_line_crs(vertices_crs)
    try:
        target_crs = assert_supported_project_crs(horizontal_crs)
    except UnsupportedCrsError as exc:
        raise _fail(SurfaceProfileErrorReason.UNSUPPORTED_CRS, str(exc)) from exc

    if source_crs != target_crs:
        try:
            parsed = [
                reproject_point(x, y, from_crs=source_crs, to_crs=target_crs) for x, y in parsed
            ]
        except (ReprojectionFailedError, UnsupportedCrsError) as exc:
            raise _fail(SurfaceProfileErrorReason.REPROJECTION_FAILED, str(exc)) from exc

    collapsed: list[tuple[float, float]] = []
    for point in parsed:
        if not collapsed or point != collapsed[-1]:
            collapsed.append(point)
    if len(collapsed) < 2:
        raise _fail(
            SurfaceProfileErrorReason.INVALID_LINE,
            "서로 다른 꼭짓점이 2개 이상 필요하다(길이 0 선은 단면이 아니다)",
        )

    cumulative = [0.0]
    for (x0, y0), (x1, y1) in zip(collapsed, collapsed[1:], strict=False):
        cumulative.append(cumulative[-1] + math.hypot(x1 - x0, y1 - y0))
    length = cumulative[-1]
    if not (math.isfinite(length) and length > 0):
        raise _fail(SurfaceProfileErrorReason.INVALID_LINE, "선 길이를 계산할 수 없다")
    if length > policy.maximum_line_length_m:
        raise _fail(
            SurfaceProfileErrorReason.LINE_TOO_LONG,
            f"선 길이 {length:.1f}m 가 한도 {policy.maximum_line_length_m:.1f}m 를 넘는다",
        )
    # 표본 수를 목록을 만들기 전에 막는다 — 간격이 아주 작아도 메모리를 먼저 쓰지 않는다.
    if int(length // sample_spacing_m) + 1 > policy.maximum_samples:
        raise _fail(
            SurfaceProfileErrorReason.TOO_MANY_SAMPLES,
            f"간격 {sample_spacing_m}m 로는 표본이 한도 {policy.maximum_samples}개를 넘는다 — "
            "간격을 키우거나 선을 나눠라",
        )

    candidates = [k * sample_spacing_m for k in range(int(length // sample_spacing_m) + 1)]
    candidates.extend(cumulative)
    candidates.sort()
    distances: list[float] = []
    for value in candidates:
        if value >= length - _DISTANCE_TOLERANCE_M:
            continue
        if not distances or value - distances[-1] > _DISTANCE_TOLERANCE_M:
            distances.append(value)
    distances.append(length)
    if len(distances) > policy.maximum_samples:
        raise _fail(
            SurfaceProfileErrorReason.TOO_MANY_SAMPLES,
            f"꼭짓점을 포함하면 표본 {len(distances)}개가 한도 {policy.maximum_samples}개를 넘는다",
        )

    points: list[tuple[float, float]] = []
    for distance in distances:
        index = min(bisect_right(cumulative, distance) - 1, len(collapsed) - 2)
        x0, y0 = collapsed[index]
        x1, y1 = collapsed[index + 1]
        segment = cumulative[index + 1] - cumulative[index]
        t = (distance - cumulative[index]) / segment
        points.append((x1, y1) if t >= 1.0 else (x0 + t * (x1 - x0), y0 + t * (y1 - y0)))

    return SurfaceProfilePlan(
        horizontal_crs=target_crs,
        line_length_m=length,
        sample_spacing_m=float(sample_spacing_m),
        distances_m=tuple(distances),
        points=tuple(points),
    )


def _facts(dataset: rasterio.DatasetReader) -> ProfileSourceFacts:
    if dataset.count != 1:
        raise _fail(
            SurfaceProfileErrorReason.UNSUPPORTED_RASTER,
            f"단일 밴드 표고 래스터여야 한다(밴드 {dataset.count}개)",
        )
    if dataset.crs is None:
        raise _fail(
            SurfaceProfileErrorReason.UNSUPPORTED_CRS,
            "좌표계 정보가 없는 래스터다 — 파일이 어느 좌표계인지 말하지 않는다",
        )
    try:
        crs = assert_supported_project_crs(dataset.crs.to_wkt())
    except UnsupportedCrsError as exc:
        raise _fail(
            SurfaceProfileErrorReason.UNSUPPORTED_CRS,
            f"래스터 좌표계가 투영좌표계 화이트리스트 밖이다(거리를 m 로 말할 수 없다): {exc}",
        ) from exc
    transform = dataset.transform
    if transform.b != 0.0 or transform.d != 0.0 or not (transform.a > 0.0 and transform.e < 0.0):
        raise _fail(
            SurfaceProfileErrorReason.UNSUPPORTED_RASTER,
            "북쪽이 위인 정방 격자만 읽는다(회전·반전 래스터 거부)",
        )
    if dataset.scales[0] != 1.0 or dataset.offsets[0] != 0.0:
        raise _fail(
            SurfaceProfileErrorReason.UNSUPPORTED_RASTER,
            "스케일/오프셋 메타데이터가 있는 래스터는 값을 조용히 바꾸지 않기 위해 거부한다",
        )
    block_rows, block_cols = dataset.block_shapes[0]
    return ProfileSourceFacts(
        horizontal_crs=crs,
        width=dataset.width,
        height=dataset.height,
        cell_size_x=float(transform.a),
        cell_size_y=float(-transform.e),
        block_rows=int(block_rows),
        block_cols=int(block_cols),
    )


def inspect_profile_source(raster_path: Path) -> ProfileSourceFacts:
    """표본 간격·좌표계 결정에 필요한 래스터 사실만 읽는다(픽셀은 읽지 않는다)."""
    try:
        with rasterio.open(raster_path) as dataset:
            return _facts(dataset)
    except RasterioIOError as exc:
        raise _fail(
            SurfaceProfileErrorReason.UNREADABLE_RASTER, f"래스터를 열 수 없다: {exc}"
        ) from exc


def sample_surface_profile(
    raster_path: Path,
    plan: SurfaceProfilePlan,
    *,
    policy: SurfaceProfilePolicy,
) -> SurfaceProfile:
    """계획한 표본 위치에서 래스터 표고를 읽는다.

    모든 표본을 덮는 **하나의 창**만 한 번 읽는다. 창이 정책 한도를 넘거나 원본 저장
    블록이 한도를 넘으면 읽기 전에 거부한다.
    """
    try:
        with rasterio.open(raster_path) as dataset:
            facts = _facts(dataset)
            try:
                assert_same_crs(plan.horizontal_crs, facts.horizontal_crs)
            except CrsMismatchError as exc:
                raise _fail(SurfaceProfileErrorReason.CRS_MISMATCH, str(exc)) from exc
            raster_cells = facts.width * facts.height
            block_cells = facts.block_rows * facts.block_cols
            if (
                raster_cells > policy.maximum_source_block_cells
                and block_cells > policy.maximum_source_block_cells
            ):
                raise _fail(
                    SurfaceProfileErrorReason.SOURCE_BLOCK_TOO_LARGE,
                    f"원본 저장 블록 {facts.block_rows}×{facts.block_cols} 이 "
                    f"한도 {policy.maximum_source_block_cells}셀을 넘는다 — 작은 창도 블록 전체를 "
                    "읽으므로 거부한다(승인된 타일 파생본이 필요하다)",
                )

            transform = dataset.transform
            left, top = float(transform.c), float(transform.f)
            width, height = facts.width, facts.height
            right = left + facts.cell_size_x * width
            bottom = top - facts.cell_size_y * height

            count = len(plan.points)
            reasons: list[SampleInvalidReason | None] = [None] * count
            cols0 = np.zeros(count, dtype=np.int64)
            rows0 = np.zeros(count, dtype=np.int64)
            frac_x = np.zeros(count, dtype=np.float64)
            frac_y = np.zeros(count, dtype=np.float64)
            readable: list[int] = []

            for i, (x, y) in enumerate(plan.points):
                if not (left <= x <= right and bottom <= y <= top):
                    reasons[i] = SampleInvalidReason.OUTSIDE_SURFACE
                    continue
                col_f = (x - left) / facts.cell_size_x - 0.5
                row_f = (top - y) / facts.cell_size_y - 0.5
                if abs(col_f - round(col_f)) < _CENTRE_SNAP:
                    col_f = float(round(col_f))
                if abs(row_f - round(row_f)) < _CENTRE_SNAP:
                    row_f = float(round(row_f))
                col0, row0 = math.floor(col_f), math.floor(row_f)
                fx, fy = col_f - col0, row_f - row0
                col1 = col0 + 1 if fx > 0.0 else col0
                row1 = row0 + 1 if fy > 0.0 else row0
                if col0 < 0 or row0 < 0 or col1 > width - 1 or row1 > height - 1:
                    reasons[i] = SampleInvalidReason.INSUFFICIENT_NEIGHBORS
                    continue
                cols0[i], rows0[i], frac_x[i], frac_y[i] = col0, row0, fx, fy
                readable.append(i)

            values = np.full(count, np.nan, dtype=np.float64)
            window_cells = 0
            if readable:
                idx = np.asarray(readable)
                col_min = int(cols0[idx].min())
                row_min = int(rows0[idx].min())
                col_max = int((cols0[idx] + (frac_x[idx] > 0.0)).max())
                row_max = int((rows0[idx] + (frac_y[idx] > 0.0)).max())
                window_cells = (col_max - col_min + 1) * (row_max - row_min + 1)
                if window_cells > policy.maximum_window_cells:
                    raise _fail(
                        SurfaceProfileErrorReason.WINDOW_TOO_LARGE,
                        f"선을 덮는 읽기 창 {window_cells}셀이 한도 "
                        f"{policy.maximum_window_cells}셀을 넘는다 — 선을 나눠라",
                    )
                window = Window(col_min, row_min, col_max - col_min + 1, row_max - row_min + 1)
                block = dataset.read(1, window=window, masked=True)
                data = np.ma.filled(block.astype(np.float64), np.nan)
                valid = np.isfinite(data) & ~np.ma.getmaskarray(block)
                for i in readable:
                    r, c = int(rows0[i]) - row_min, int(cols0[i]) - col_min
                    fx, fy = float(frac_x[i]), float(frac_y[i])
                    c1 = c + 1 if fx > 0.0 else c
                    r1 = r + 1 if fy > 0.0 else r
                    if not (valid[r, c] and valid[r, c1] and valid[r1, c] and valid[r1, c1]):
                        reasons[i] = SampleInvalidReason.NODATA
                        continue
                    top_value = (1.0 - fx) * data[r, c] + fx * data[r, c1]
                    bottom_value = (1.0 - fx) * data[r1, c] + fx * data[r1, c1]
                    values[i] = (1.0 - fy) * top_value + fy * bottom_value
    except RasterioIOError as exc:
        raise _fail(
            SurfaceProfileErrorReason.UNREADABLE_RASTER, f"래스터를 열거나 읽을 수 없다: {exc}"
        ) from exc

    samples = tuple(
        ProfileSample(
            index=i,
            distance_m=plan.distances_m[i],
            x=plan.points[i][0],
            y=plan.points[i][1],
            elevation_m=None if reasons[i] is not None else float(values[i]),
            invalid_reason=reasons[i],
        )
        for i in range(count)
    )
    return SurfaceProfile(plan=plan, source=facts, samples=samples, window_cells_read=window_cells)


def compare_surface_profiles(
    baseline: SurfaceProfile, current: SurfaceProfile
) -> SurfaceProfileComparison:
    """같은 계획으로 읽은 두 단면의 높이 차이(current − baseline).

    수직기준·처리 프로필의 호환성(INV-053)은 이 함수가 판정하지 않는다 — Core 의 비교
    전제 확인이 끝난 입력에만 쓴다. 이 함수는 같은 좌표계·같은 표본 위치인지만 막는다.
    """
    try:
        assert_same_crs(baseline.plan.horizontal_crs, current.plan.horizontal_crs)
    except CrsMismatchError as exc:
        raise _fail(SurfaceProfileErrorReason.CRS_MISMATCH, str(exc)) from exc
    if baseline.plan != current.plan:
        raise _fail(
            SurfaceProfileErrorReason.PLAN_MISMATCH,
            "두 단면은 같은 선·같은 표본 위치 계획으로 읽어야 한다",
        )

    rows: list[ComparisonSample] = []
    differences: list[float] = []
    for before, after in zip(baseline.samples, current.samples, strict=True):
        before_value, after_value = before.elevation_m, after.elevation_m
        if before_value is None and after_value is None:
            reason: ComparisonInvalidReason | None = ComparisonInvalidReason.BOTH_UNAVAILABLE
        elif before_value is None:
            reason = ComparisonInvalidReason.BASELINE_UNAVAILABLE
        elif after_value is None:
            reason = ComparisonInvalidReason.CURRENT_UNAVAILABLE
        else:
            reason = None
        difference = None if reason is not None else after_value - before_value  # type: ignore[operator]
        if difference is not None:
            differences.append(difference)
        rows.append(
            ComparisonSample(
                index=before.index,
                distance_m=before.distance_m,
                x=before.x,
                y=before.y,
                baseline_m=before_value,
                current_m=after_value,
                difference_m=difference,
                invalid_reason=reason,
            )
        )
    return SurfaceProfileComparison(
        plan=baseline.plan,
        samples=tuple(rows),
        valid_count=len(differences),
        largest_rise_m=max((d for d in differences if d > 0.0), default=None),
        largest_drop_m=min((d for d in differences if d < 0.0), default=None),
    )


__all__ = [
    "ComparisonInvalidReason",
    "ComparisonSample",
    "ProfileSample",
    "ProfileSourceFacts",
    "SampleInvalidReason",
    "SurfaceProfile",
    "SurfaceProfileComparison",
    "SurfaceProfileError",
    "SurfaceProfileErrorReason",
    "SurfaceProfilePlan",
    "SurfaceProfilePolicy",
    "compare_surface_profiles",
    "inspect_profile_source",
    "plan_surface_profile",
    "sample_surface_profile",
]
