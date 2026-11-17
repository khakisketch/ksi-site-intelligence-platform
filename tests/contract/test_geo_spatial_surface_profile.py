"""표면 단면 계약 — 선을 따라 표고를 읽되, 모르면 값을 지어내지 않고 읽는 양을 제한한다.

모든 래스터는 합성이며 해석해로 값을 검증한다(원점 (200000, 500000), 셀 1m, EPSG:5186).
이 시험은 계산 도구의 계약이지 측량 정확도·고객 수락의 증거가 아니다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from ksi_event_contracts.external_artifact_validation import (
    NodataRepresentation,
    ObservedVerticalReferenceV1,
    RasterMeasurementsV1,
)
from ksi_geo_spatial.crs import reproject_point
from ksi_geo_spatial.surface_profile import (
    ComparisonInvalidReason,
    SampleInvalidReason,
    SurfaceProfileError,
    SurfaceProfileErrorReason,
    SurfaceProfilePlan,
    SurfaceProfilePolicy,
    compare_surface_profiles,
    inspect_profile_source,
    locate_profile_samples,
    neighbour_window,
    plan_surface_profile,
    profile_support_blocker,
    sample_surface_profile,
)
from rasterio.transform import Affine, from_origin

_NODATA = -9999.0
_ORIGIN_X, _ORIGIN_Y = 200_000.0, 500_000.0
_POLICY = SurfaceProfilePolicy(
    maximum_vertices=50,
    maximum_samples=2_000,
    maximum_line_length_m=5_000.0,
    maximum_window_cells=1_000_000,
    maximum_source_block_cells=4_000_000,
)


def _write(
    path: Path,
    values: np.ndarray,
    *,
    crs: str | None = "EPSG:5186",
    nodata: float | None = _NODATA,
    dtype: str = "float32",
    cell: float = 1.0,
    transform: Affine | None = None,
    tiled: bool = False,
) -> Path:
    height, width = values.shape
    options: dict[str, object] = {}
    if tiled:
        options.update(tiled=True, blockxsize=128, blockysize=128)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=dtype,
        crs=crs,
        nodata=nodata,
        transform=transform or from_origin(_ORIGIN_X, _ORIGIN_Y, cell, cell),
        **options,
    ) as dataset:
        dataset.write(values.astype(dtype), 1)
    return path


def _plane(rows: int = 20, cols: int = 30) -> np.ndarray:
    """z = 100 + 0.5·col + 0.25·row — 이중선형 보간이 정확히 복원하는 평면(float32 정확 표현값)."""
    row_index, col_index = np.mgrid[0:rows, 0:cols]
    return 100.0 + 0.5 * col_index + 0.25 * row_index


def _centre(col: float, row: float) -> tuple[float, float]:
    return (_ORIGIN_X + col + 0.5, _ORIGIN_Y - row - 0.5)


def _line(*cells: tuple[float, float]) -> list[tuple[float, float]]:
    return [_centre(col, row) for col, row in cells]


def _plan(
    vertices: Sequence[Any],
    *,
    spacing: Any = 1.0,
    crs: str = "EPSG:5186",
    policy: SurfaceProfilePolicy = _POLICY,
) -> SurfaceProfilePlan:
    return plan_surface_profile(
        vertices,
        vertices_crs=crs,
        horizontal_crs="EPSG:5186",
        sample_spacing_m=spacing,
        policy=policy,
    )


def _reason(excinfo: pytest.ExceptionInfo[SurfaceProfileError]) -> SurfaceProfileErrorReason:
    return excinfo.value.reason


# ── 값의 정확성 ──────────────────────────────────────────────────────────────


def test_planar_surface_is_reproduced_between_cell_centres(tmp_path: Path) -> None:
    raster = _write(tmp_path / "dsm.tif", _plane())
    plan = _plan(_line((2, 2), (9, 2)))
    profile = sample_surface_profile(raster, plan, policy=_POLICY)

    assert [s.distance_m for s in profile.samples] == pytest.approx([0, 1, 2, 3, 4, 5, 6, 7])
    for sample in profile.samples:
        col = sample.x - _ORIGIN_X - 0.5
        row = _ORIGIN_Y - sample.y - 0.5
        assert sample.elevation_m == pytest.approx(100.0 + 0.5 * col + 0.25 * row, abs=1e-4)
        assert sample.invalid_reason is None


def test_off_centre_samples_are_bilinear_not_nearest(tmp_path: Path) -> None:
    raster = _write(tmp_path / "dsm.tif", _plane())
    plan = _plan([_centre(3.25, 4.5), _centre(8.75, 4.5)], spacing=1.375)
    profile = sample_surface_profile(raster, plan, policy=_POLICY)
    for sample in profile.samples:
        col = sample.x - _ORIGIN_X - 0.5
        row = _ORIGIN_Y - sample.y - 0.5
        assert sample.elevation_m == pytest.approx(100.0 + 0.5 * col + 0.25 * row, abs=1e-4)


def test_vertices_and_end_are_always_sampled(tmp_path: Path) -> None:
    raster = _write(tmp_path / "dsm.tif", _plane())
    vertices = _line((2, 2), (8, 2), (8, 7))  # 6m 다음 5m — 간격 4 는 어느 쪽도 나누지 못한다
    plan = _plan(vertices, spacing=4.0)

    assert plan.line_length_m == pytest.approx(11.0)
    for expected in (0.0, 4.0, 6.0, 8.0, 11.0):  # 0, 4, 꼭짓점 6, 8, 끝 11
        assert any(math.isclose(d, expected, abs_tol=1e-9) for d in plan.distances_m)
    assert plan.distances_m == tuple(sorted(plan.distances_m))
    assert plan.points[-1] == vertices[-1]
    profile = sample_surface_profile(raster, plan, policy=_POLICY)
    assert profile.valid_count == len(profile.samples)


def test_duplicate_consecutive_vertices_are_collapsed(tmp_path: Path) -> None:
    plan = _plan(_line((2, 2), (2, 2), (6, 2), (6, 2)))
    assert plan.line_length_m == pytest.approx(4.0)


def test_default_spacing_follows_the_grid_resolution(tmp_path: Path) -> None:
    fine = inspect_profile_source(_write(tmp_path / "a.tif", _plane(), cell=1.0))
    coarse = inspect_profile_source(_write(tmp_path / "b.tif", _plane(), cell=2.5))
    assert fine.ground_sample_distance_m == pytest.approx(1.0)
    assert coarse.ground_sample_distance_m == pytest.approx(2.5)
    assert fine.horizontal_crs == "EPSG:5186"


def test_geographic_line_gives_the_same_profile_as_the_projected_line(tmp_path: Path) -> None:
    raster = _write(tmp_path / "dsm.tif", _plane())
    projected = _line((3, 3), (12, 8))
    geographic = [
        reproject_point(x, y, from_crs="EPSG:5186", to_crs="EPSG:4326") for x, y in projected
    ]

    a = sample_surface_profile(raster, _plan(projected, spacing=2.0), policy=_POLICY)
    b = sample_surface_profile(
        raster, _plan(geographic, spacing=2.0, crs="EPSG:4326"), policy=_POLICY
    )

    assert len(a.samples) == len(b.samples)
    for left, right in zip(a.samples, b.samples, strict=True):
        assert right.distance_m == pytest.approx(left.distance_m, abs=1e-5)
        assert right.elevation_m == pytest.approx(left.elevation_m, abs=1e-4)


def test_integer_raster_is_read_as_numbers_and_nodata_is_masked(tmp_path: Path) -> None:
    values = (np.arange(30 * 20).reshape(20, 30) % 50).astype("int16")
    values[5, 5] = -32768
    raster = _write(tmp_path / "dsm.tif", values, dtype="int16", nodata=-32768)
    profile = sample_surface_profile(raster, _plan(_line((2, 5), (9, 5))), policy=_POLICY)
    by_distance = {round(s.distance_m): s for s in profile.samples}
    assert by_distance[0].elevation_m == pytest.approx(float(values[5, 2]))
    assert by_distance[3].elevation_m is None  # 셀 (5,5) 위 — 센티널 -32768 을 표고로 읽지 않는다
    assert by_distance[3].invalid_reason is SampleInvalidReason.NODATA


# ── 모르면 값이 없다 ─────────────────────────────────────────────────────────


def test_part_of_the_line_outside_the_surface_has_no_value(tmp_path: Path) -> None:
    raster = _write(tmp_path / "dsm.tif", _plane())  # 가로 30m — x ∈ [200000, 200030]
    vertices = [(_ORIGIN_X - 5.0, _centre(0, 5)[1]), _centre(9, 5)]
    profile = sample_surface_profile(raster, _plan(vertices, spacing=1.0), policy=_POLICY)

    outside = [s for s in profile.samples if s.x < _ORIGIN_X]
    assert outside and all(s.elevation_m is None for s in outside)
    assert all(s.invalid_reason is SampleInvalidReason.OUTSIDE_SURFACE for s in outside)
    inside_valid = [s for s in profile.samples if s.x >= _ORIGIN_X + 0.5]
    assert inside_valid and all(s.elevation_m is not None for s in inside_valid)


def test_line_entirely_outside_reads_nothing_and_returns_no_values(tmp_path: Path) -> None:
    raster = _write(tmp_path / "dsm.tif", _plane())
    profile = sample_surface_profile(
        raster, _plan([(300_000.0, 400_000.0), (300_010.0, 400_000.0)]), policy=_POLICY
    )
    assert profile.valid_count == 0
    assert profile.window_cells_read == 0
    assert all(s.invalid_reason is SampleInvalidReason.OUTSIDE_SURFACE for s in profile.samples)


def test_half_cell_edge_band_is_not_extrapolated(tmp_path: Path) -> None:
    raster = _write(tmp_path / "dsm.tif", _plane())
    edge = (_ORIGIN_X + 0.25, _ORIGIN_Y - 5.5)  # 범위 안이지만 첫 셀 중심보다 왼쪽
    plan = _plan([edge, (_ORIGIN_X + 4.5, _ORIGIN_Y - 5.5)], spacing=1.0)
    first = sample_surface_profile(raster, plan, policy=_POLICY).samples[0]
    assert first.elevation_m is None
    assert first.invalid_reason is SampleInvalidReason.INSUFFICIENT_NEIGHBORS


def test_nodata_hole_never_becomes_a_number(tmp_path: Path) -> None:
    values = _plane()
    values[5, 8:11] = _NODATA
    raster = _write(tmp_path / "dsm.tif", values)
    profile = sample_surface_profile(raster, _plan(_line((2, 5), (16, 5))), policy=_POLICY)

    holes = [s for s in profile.samples if s.invalid_reason is SampleInvalidReason.NODATA]
    assert holes, "구멍을 지나는 선인데 NoData 표본이 하나도 없다"
    assert all(s.elevation_m is None for s in holes)
    assert all(
        s.elevation_m is None or s.elevation_m > 0 for s in profile.samples
    )  # -9999 가 새지 않는다
    assert profile.samples[0].elevation_m == pytest.approx(values[5, 2])
    assert profile.samples[-1].elevation_m == pytest.approx(values[5, 16])


def test_nan_cells_without_declared_nodata_are_also_unknown(tmp_path: Path) -> None:
    values = _plane()
    values[5, 6] = np.nan
    raster = _write(tmp_path / "dsm.tif", values, nodata=None)
    profile = sample_surface_profile(raster, _plan(_line((4, 5), (8, 5))), policy=_POLICY)
    assert any(
        s.invalid_reason is SampleInvalidReason.NODATA and s.elevation_m is None
        for s in profile.samples
    )
    assert all(s.elevation_m is None or math.isfinite(s.elevation_m) for s in profile.samples)


# ── 입력 거부(typed) ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("vertices", "reason"),
    [
        ([(200_001.0, 499_990.0)], SurfaceProfileErrorReason.INVALID_LINE),
        ([(200_001.0, 499_990.0), (200_001.0, 499_990.0)], SurfaceProfileErrorReason.INVALID_LINE),
        (
            [(200_001.0, 499_990.0), (float("nan"), 499_990.0)],
            SurfaceProfileErrorReason.INVALID_LINE,
        ),
        (
            [(200_001.0, 499_990.0), (float("inf"), 499_990.0)],
            SurfaceProfileErrorReason.INVALID_LINE,
        ),
        ([(200_001.0, 499_990.0), "ab"], SurfaceProfileErrorReason.INVALID_LINE),
        ([(200_001.0, 499_990.0), (True, 1.0)], SurfaceProfileErrorReason.INVALID_LINE),
        ([(float(i), 0.0) for i in range(60)], SurfaceProfileErrorReason.TOO_MANY_VERTICES),
    ],
)
def test_bad_lines_are_refused(vertices: list[Any], reason: SurfaceProfileErrorReason) -> None:
    with pytest.raises(SurfaceProfileError) as excinfo:
        _plan(vertices)
    assert _reason(excinfo) is reason


@pytest.mark.parametrize("spacing", [0.0, -1.0, float("nan"), float("inf"), True, "1"])
def test_bad_spacing_is_refused(spacing: Any) -> None:
    with pytest.raises(SurfaceProfileError) as excinfo:
        _plan(_line((2, 2), (9, 2)), spacing=spacing)
    assert _reason(excinfo) is SurfaceProfileErrorReason.INVALID_SAMPLING


def test_limits_refuse_instead_of_quietly_coarsening() -> None:
    with pytest.raises(SurfaceProfileError) as too_many:
        _plan(_line((2, 2), (9, 2)), spacing=0.001)  # 7m / 1mm = 7000 > 2000
    assert _reason(too_many) is SurfaceProfileErrorReason.TOO_MANY_SAMPLES

    tight = SurfaceProfilePolicy(
        maximum_vertices=50,
        maximum_samples=2_000,
        maximum_line_length_m=5.0,
        maximum_window_cells=1_000_000,
        maximum_source_block_cells=4_000_000,
    )
    with pytest.raises(SurfaceProfileError) as too_long:
        _plan(_line((2, 2), (9, 2)), policy=tight)
    assert _reason(too_long) is SurfaceProfileErrorReason.LINE_TOO_LONG


def test_unsupported_coordinate_systems_are_refused() -> None:
    with pytest.raises(SurfaceProfileError) as web_mercator:
        _plan([(14_000_000.0, 4_000_000.0), (14_000_100.0, 4_000_000.0)], crs="EPSG:3857")
    assert _reason(web_mercator) is SurfaceProfileErrorReason.UNSUPPORTED_CRS

    with pytest.raises(SurfaceProfileError) as geographic_target:
        plan_surface_profile(
            _line((2, 2), (9, 2)),
            vertices_crs="EPSG:5186",
            horizontal_crs="EPSG:4326",
            sample_spacing_m=1.0,
            policy=_POLICY,
        )
    assert _reason(geographic_target) is SurfaceProfileErrorReason.UNSUPPORTED_CRS


def test_policy_must_be_finite_and_explicit() -> None:
    with pytest.raises(ValueError, match="maximum_samples"):
        SurfaceProfilePolicy(
            maximum_vertices=10,
            maximum_samples=0,
            maximum_line_length_m=10.0,
            maximum_window_cells=10,
            maximum_source_block_cells=10,
        )
    with pytest.raises(ValueError, match="maximum_line_length_m"):
        SurfaceProfilePolicy(
            maximum_vertices=10,
            maximum_samples=10,
            maximum_line_length_m=float("inf"),
            maximum_window_cells=10,
            maximum_source_block_cells=10,
        )


def test_unreadable_or_unsupported_rasters_are_refused(tmp_path: Path) -> None:
    plan = _plan(_line((2, 2), (9, 2)))
    cases = {
        "missing": (tmp_path / "missing.tif", SurfaceProfileErrorReason.UNREADABLE_RASTER),
        "geographic": (
            _write(
                tmp_path / "geo.tif",
                _plane(),
                crs="EPSG:4326",
                transform=from_origin(127.0, 37.0, 1e-5, 1e-5),
            ),
            SurfaceProfileErrorReason.UNSUPPORTED_CRS,
        ),
        "no_crs": (
            _write(tmp_path / "nocrs.tif", _plane(), crs=None),
            SurfaceProfileErrorReason.UNSUPPORTED_CRS,
        ),
        "rotated": (
            _write(
                tmp_path / "rot.tif",
                _plane(),
                transform=Affine(1.0, 0.2, _ORIGIN_X, 0.2, -1.0, _ORIGIN_Y),
            ),
            SurfaceProfileErrorReason.UNSUPPORTED_RASTER,
        ),
        "flipped": (
            _write(
                tmp_path / "flip.tif",
                _plane(),
                transform=Affine(1.0, 0.0, _ORIGIN_X, 0.0, 1.0, _ORIGIN_Y),
            ),
            SurfaceProfileErrorReason.UNSUPPORTED_RASTER,
        ),
    }
    for _, (path, reason) in cases.items():
        with pytest.raises(SurfaceProfileError) as excinfo:
            sample_surface_profile(path, plan, policy=_POLICY)
        assert _reason(excinfo) is reason, path.name


def test_multiband_and_scaled_rasters_are_refused(tmp_path: Path) -> None:
    plan = _plan(_line((2, 2), (9, 2)))
    two_band = tmp_path / "two.tif"
    with rasterio.open(
        two_band,
        "w",
        driver="GTiff",
        height=20,
        width=30,
        count=2,
        dtype="float32",
        crs="EPSG:5186",
        transform=from_origin(_ORIGIN_X, _ORIGIN_Y, 1.0, 1.0),
    ) as dataset:
        dataset.write(_plane().astype("float32"), 1)
        dataset.write(_plane().astype("float32"), 2)
    with pytest.raises(SurfaceProfileError) as multi:
        sample_surface_profile(two_band, plan, policy=_POLICY)
    assert _reason(multi) is SurfaceProfileErrorReason.UNSUPPORTED_RASTER

    scaled = _write(tmp_path / "scaled.tif", _plane())
    with rasterio.open(scaled, "r+") as dataset:
        dataset.scales = (0.01,)
    with pytest.raises(SurfaceProfileError) as scale:
        sample_surface_profile(scaled, plan, policy=_POLICY)
    assert _reason(scale) is SurfaceProfileErrorReason.UNSUPPORTED_RASTER


def test_plan_in_another_crs_is_not_read_from_this_raster(tmp_path: Path) -> None:
    raster = _write(tmp_path / "dsm.tif", _plane())
    other = plan_surface_profile(
        [(200_001.0, 499_990.0), (200_010.0, 499_990.0)],
        vertices_crs="EPSG:5187",
        horizontal_crs="EPSG:5187",
        sample_spacing_m=1.0,
        policy=_POLICY,
    )
    with pytest.raises(SurfaceProfileError) as excinfo:
        sample_surface_profile(raster, other, policy=_POLICY)
    assert _reason(excinfo) is SurfaceProfileErrorReason.CRS_MISMATCH


# ── 읽는 양의 제한 ───────────────────────────────────────────────────────────


def test_reading_window_is_bounded_and_reported(tmp_path: Path) -> None:
    big = np.full((400, 400), 50.0)
    raster = _write(tmp_path / "big.tif", big, tiled=True)
    profile = sample_surface_profile(raster, _plan(_line((100, 100), (105, 100))), policy=_POLICY)
    # 한 번의 작은 창만 읽는다 — 래스터 전체(160000셀)가 아니다.
    assert 0 < profile.window_cells_read <= 14
    assert profile.valid_count == len(profile.samples)


def test_window_over_the_limit_is_refused_before_any_value_is_returned(tmp_path: Path) -> None:
    raster = _write(tmp_path / "dsm.tif", _plane())
    tight = SurfaceProfilePolicy(
        maximum_vertices=50,
        maximum_samples=2_000,
        maximum_line_length_m=5_000.0,
        maximum_window_cells=20,
        maximum_source_block_cells=4_000_000,
    )
    with pytest.raises(SurfaceProfileError) as excinfo:
        sample_surface_profile(raster, _plan(_line((2, 2), (25, 15))), policy=tight)
    assert _reason(excinfo) is SurfaceProfileErrorReason.WINDOW_TOO_LARGE


def test_large_source_blocks_are_refused_because_small_windows_still_read_whole_blocks(
    tmp_path: Path,
) -> None:
    raster = _write(tmp_path / "striped.tif", np.full((300, 300), 10.0))
    facts = inspect_profile_source(raster)
    assert facts.block_rows * facts.block_cols > 50
    tight = SurfaceProfilePolicy(
        maximum_vertices=50,
        maximum_samples=2_000,
        maximum_line_length_m=5_000.0,
        maximum_window_cells=1_000_000,
        maximum_source_block_cells=50,
    )
    with pytest.raises(SurfaceProfileError) as excinfo:
        sample_surface_profile(raster, _plan(_line((2, 2), (9, 2))), policy=tight)
    assert _reason(excinfo) is SurfaceProfileErrorReason.SOURCE_BLOCK_TOO_LARGE

    # 래스터 전체가 한도 이하이면 블록 검사를 건너뛴다(통째로 읽어도 한도 안).
    small = _write(tmp_path / "small.tif", np.full((5, 8), 10.0))
    profile = sample_surface_profile(
        small,
        _plan(_line((1, 2), (5, 2))),
        policy=tight.__class__(
            maximum_vertices=50,
            maximum_samples=2_000,
            maximum_line_length_m=5_000.0,
            maximum_window_cells=1_000_000,
            maximum_source_block_cells=50,
        ),
    )
    assert profile.valid_count == len(profile.samples)


def test_same_inputs_give_identical_profiles(tmp_path: Path) -> None:
    raster = _write(tmp_path / "dsm.tif", _plane())
    plan = _plan(_line((2, 2), (9, 6)), spacing=1.5)
    assert sample_surface_profile(raster, plan, policy=_POLICY) == sample_surface_profile(
        raster, plan, policy=_POLICY
    )


# ── 두 표면 비교 ─────────────────────────────────────────────────────────────


def test_two_surfaces_difference_is_current_minus_baseline(tmp_path: Path) -> None:
    baseline = _plane()
    current = _plane()
    current[:, 12:] += 2.0  # 오른쪽은 2m 높아짐
    current[:, :6] -= 1.5  # 왼쪽은 1.5m 낮아짐
    base_path = _write(tmp_path / "t0.tif", baseline)
    cur_path = _write(tmp_path / "t1.tif", current)
    plan = _plan(_line((1, 5), (20, 5)))

    comparison = compare_surface_profiles(
        sample_surface_profile(base_path, plan, policy=_POLICY),
        sample_surface_profile(cur_path, plan, policy=_POLICY),
    )
    assert comparison.valid_count == len(comparison.samples)
    assert comparison.largest_rise_m == pytest.approx(2.0, abs=1e-4)
    assert comparison.largest_drop_m == pytest.approx(-1.5, abs=1e-4)
    zero = [s for s in comparison.samples if 7 <= s.distance_m + 1 <= 10]
    assert zero and all(s.difference_m == pytest.approx(0.0, abs=1e-6) for s in zero)


def test_unknown_on_either_side_is_not_a_zero_difference(tmp_path: Path) -> None:
    baseline = _plane()
    current = _plane()
    baseline[5, 8] = _NODATA
    current[5, 8] = _NODATA
    current[5, 12] = _NODATA
    plan = _plan(_line((6, 5), (14, 5)))
    comparison = compare_surface_profiles(
        sample_surface_profile(_write(tmp_path / "t0.tif", baseline), plan, policy=_POLICY),
        sample_surface_profile(_write(tmp_path / "t1.tif", current), plan, policy=_POLICY),
    )
    reasons = {s.invalid_reason for s in comparison.samples}
    assert ComparisonInvalidReason.BOTH_UNAVAILABLE in reasons
    assert ComparisonInvalidReason.CURRENT_UNAVAILABLE in reasons
    for sample in comparison.samples:
        if sample.invalid_reason is not None:
            assert sample.difference_m is None
    assert comparison.valid_count < len(comparison.samples)
    # 같은 높이만 있고 상승/하강이 없으면 최대값은 지어내지 않는다.
    assert comparison.largest_rise_m is None
    assert comparison.largest_drop_m is None


def test_only_profiles_read_with_the_same_plan_can_be_compared(tmp_path: Path) -> None:
    path = _write(tmp_path / "dsm.tif", _plane())
    a = sample_surface_profile(path, _plan(_line((2, 5), (12, 5))), policy=_POLICY)
    b = sample_surface_profile(path, _plan(_line((2, 6), (12, 6))), policy=_POLICY)
    with pytest.raises(SurfaceProfileError) as excinfo:
        compare_surface_profiles(a, b)
    assert _reason(excinfo) is SurfaceProfileErrorReason.PLAN_MISMATCH


def test_profiles_in_different_crs_are_not_compared(tmp_path: Path) -> None:
    a_path = _write(tmp_path / "a.tif", _plane())
    b_path = _write(tmp_path / "b.tif", _plane(), crs="EPSG:5187")
    a = sample_surface_profile(a_path, _plan(_line((2, 5), (12, 5))), policy=_POLICY)
    plan_b = plan_surface_profile(
        [(200_002.5, 499_994.5), (200_012.5, 499_994.5)],
        vertices_crs="EPSG:5187",
        horizontal_crs="EPSG:5187",
        sample_spacing_m=1.0,
        policy=_POLICY,
    )
    b = sample_surface_profile(b_path, plan_b, policy=_POLICY)
    with pytest.raises(SurfaceProfileError) as excinfo:
        compare_surface_profiles(a, b)
    assert _reason(excinfo) is SurfaceProfileErrorReason.CRS_MISMATCH


# ── 경계값: 예외가 아니라 typed 거부 ────────────────────────────────────────────


def test_denormal_spacing_is_refused_not_an_overflow() -> None:
    with pytest.raises(SurfaceProfileError) as excinfo:
        _plan(_line((2, 2), (9, 2)), spacing=5e-324)
    assert _reason(excinfo) is SurfaceProfileErrorReason.TOO_MANY_SAMPLES


def test_a_line_shorter_than_the_distance_tolerance_is_not_a_profile() -> None:
    x, y = _centre(2, 2)
    with pytest.raises(SurfaceProfileError) as excinfo:
        _plan([(x, y), (x + 1e-10, y)])
    assert _reason(excinfo) is SurfaceProfileErrorReason.INVALID_LINE


def test_the_shortest_accepted_line_keeps_both_ends() -> None:
    x, y = _centre(2, 2)
    plan = _plan([(x, y), (x + 3e-9, y)])
    assert len(plan.distances_m) >= 2 and plan.distances_m[0] == 0.0


# ── 지원하지 않는 값 유형·수직 성분 ──────────────────────────────────────────────


def test_complex_raster_is_refused_not_cast_to_real_heights(tmp_path: Path) -> None:
    path = tmp_path / "complex.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=5,
        width=5,
        count=1,
        dtype="complex64",
        crs="EPSG:5186",
        transform=from_origin(_ORIGIN_X, _ORIGIN_Y, 1.0, 1.0),
    ) as dataset:
        dataset.write(np.full((5, 5), 7 + 9j, dtype="complex64"), 1)
    with pytest.raises(SurfaceProfileError) as excinfo:
        inspect_profile_source(path)
    assert _reason(excinfo) is SurfaceProfileErrorReason.UNSUPPORTED_RASTER


def _compound(path: Path, vertical: str) -> Path:
    from pyproj.crs import CompoundCRS

    crs = CompoundCRS("합성 수평+수직", components=["EPSG:5186", vertical])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=20,
        width=30,
        count=1,
        dtype="float32",
        crs=crs.to_wkt(),
        nodata=_NODATA,
        transform=from_origin(_ORIGIN_X, _ORIGIN_Y, 1.0, 1.0),
    ) as dataset:
        dataset.write(_plane().astype("float32"), 1)
    return path


def test_compound_crs_with_a_metre_vertical_is_read_on_its_horizontal_part(
    tmp_path: Path,
) -> None:
    raster = _compound(tmp_path / "compound.tif", "EPSG:5773")
    facts = inspect_profile_source(raster)
    assert facts.horizontal_crs == "EPSG:5186"
    assert facts.vertical_crs == "EPSG:5773"
    profile = sample_surface_profile(raster, _plan(_line((2, 3), (12, 3))), policy=_POLICY)
    assert profile.valid_count == len(profile.samples)


def test_plain_horizontal_crs_has_no_vertical_claim(tmp_path: Path) -> None:
    facts = inspect_profile_source(_write(tmp_path / "plain.tif", _plane()))
    assert facts.vertical_crs is None


def test_compound_crs_with_a_foot_vertical_is_refused_not_labelled_metres(
    tmp_path: Path,
) -> None:
    # EPSG:6360 은 US survey foot 수직축 — 값을 m 로 읽어 주면 3.28배 틀린다.
    raster = _compound(tmp_path / "foot.tif", "EPSG:6360")
    with pytest.raises(SurfaceProfileError) as excinfo:
        inspect_profile_source(raster)
    assert _reason(excinfo) is SurfaceProfileErrorReason.UNSUPPORTED_CRS


# ── Core 사전 확인: 보고서 사실만으로 이 엔진이 읽을 수 있는가 ──────────────────────


def _measured(
    *,
    crs: str = "EPSG:5186",
    transform: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 0.0, -1.0, 10.0),
    dtype: str = "float32",
    bands: int = 1,
    vertical: bool = True,
) -> RasterMeasurementsV1:
    return RasterMeasurementsV1(
        observed_crs_identifier=crs,
        observed_crs_digest="sha256:" + "c" * 64,
        observed_vertical_reference=(
            ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")
            if vertical
            else None
        ),
        transform=transform,
        footprint_wkt="POLYGON((0 0,10 0,10 10,0 10,0 0))",
        footprint_digest="sha256:" + "d" * 64,
        width=10,
        height=10,
        band_count=bands,
        dtype=dtype,
        layout="GEOTIFF_TILED_V1",
        nodata_representation=NodataRepresentation.NONE,
        valid_pixel_count=100,
    )


def test_a_supported_measurement_passes_the_preflight() -> None:
    assert profile_support_blocker(_measured()) is None
    assert profile_support_blocker(_measured(crs="EPSG:5179", dtype="float64")) is None


@pytest.mark.parametrize(
    ("variant", "reason"),
    [
        (dict(crs="EPSG:3857"), SurfaceProfileErrorReason.UNSUPPORTED_CRS),
        (dict(crs="EPSG:5174"), SurfaceProfileErrorReason.UNSUPPORTED_CRS),  # 구 측지계
        (dict(crs="EPSG:4326"), SurfaceProfileErrorReason.UNSUPPORTED_CRS),
        (dict(vertical=False), SurfaceProfileErrorReason.UNSUPPORTED_CRS),
        (
            dict(transform=(1.0, 0.2, 0.0, 0.0, -1.0, 10.0)),
            SurfaceProfileErrorReason.UNSUPPORTED_RASTER,
        ),
        (
            dict(transform=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0)),
            SurfaceProfileErrorReason.UNSUPPORTED_RASTER,
        ),
        (dict(bands=3), SurfaceProfileErrorReason.UNSUPPORTED_RASTER),
        (dict(dtype="uint8"), SurfaceProfileErrorReason.UNSUPPORTED_RASTER),
    ],
)
def test_the_preflight_names_why_the_engine_cannot_read_a_measured_dsm(
    variant: dict[str, Any], reason: SurfaceProfileErrorReason
) -> None:
    assert profile_support_blocker(_measured(**variant)) is reason


def test_a_current_declaration_stands_in_only_for_the_missing_vertical_reference() -> None:
    missing = _measured(vertical=False)
    assert profile_support_blocker(missing) is SurfaceProfileErrorReason.UNSUPPORTED_CRS
    assert profile_support_blocker(missing, vertical_declared=True) is None
    # 선언은 수직 기준 자리만 채운다 — 엔진이 읽지 못하는 격자·좌표계를 열지 않는다.
    assert (
        profile_support_blocker(_measured(vertical=False, crs="EPSG:3857"), vertical_declared=True)
        is SurfaceProfileErrorReason.UNSUPPORTED_CRS
    )
    assert (
        profile_support_blocker(_measured(vertical=False, bands=3), vertical_declared=True)
        is SurfaceProfileErrorReason.UNSUPPORTED_RASTER
    )
    # 파일이 스스로 갖고 있으면 선언 표시와 무관하다.
    assert profile_support_blocker(_measured(), vertical_declared=False) is None


def test_the_preflight_agrees_with_what_the_reader_actually_accepts(tmp_path: Path) -> None:
    """사전 확인이 통과시키는 파일은 읽을 수 있고, 거르는 파일은 읽기도 거부한다."""
    cases: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
        ("ok", {}, {}),
        ("web-mercator", {"crs": "EPSG:3857"}, {"crs": "EPSG:3857"}),
        (
            "rotated",
            {"transform": Affine(1.0, 0.2, _ORIGIN_X, 0.0, -1.0, _ORIGIN_Y)},
            {"transform": (1.0, 0.2, _ORIGIN_X, 0.0, -1.0, _ORIGIN_Y)},
        ),
    ]
    for name, file_options, measured_options in cases:
        path = _write(tmp_path / f"{name}.tif", _plane(), **file_options)
        with rasterio.open(path) as dataset:
            transform = tuple(float(v) for v in tuple(dataset.transform)[:6])
            crs = f"EPSG:{dataset.crs.to_epsg()}"
        blocker = profile_support_blocker(_measured(crs=crs, transform=transform))  # type: ignore[arg-type]
        try:
            inspect_profile_source(path)
            readable = True
        except SurfaceProfileError:
            readable = False
        assert (blocker is None) == readable, (name, blocker, readable, measured_options)


# ── Core 와 워커가 같은 위치 분류·같은 읽기 창을 쓴다 ───────────────────────────────


def _geometry_of(path: Path, plan: SurfaceProfilePlan) -> tuple[Any, ...]:
    with rasterio.open(path) as dataset:
        t = dataset.transform
        return locate_profile_samples(
            plan,
            left=float(t.c),
            top=float(t.f),
            cell_size_x=float(t.a),
            cell_size_y=float(-t.e),
            width=dataset.width,
            height=dataset.height,
        )


@pytest.mark.parametrize(
    "cells",
    [
        ((2.0, 3.0), (12.0, 3.0)),
        ((2.0, 3.0), (12.4, 9.7)),
        ((-4.0, 3.0), (6.0, 3.0)),  # 일부는 표면 밖
        ((0.0, 0.0), (29.0, 19.0)),  # 가장자리 반 픽셀 띠를 지난다
        ((40.0, 40.0), (50.0, 40.0)),  # 전부 밖
    ],
)
def test_locate_and_window_agree_with_what_the_sampler_reads(
    tmp_path: Path, cells: tuple[tuple[float, float], ...]
) -> None:
    path = _write(tmp_path / "dsm.tif", _plane())
    plan = _plan(_line(*cells))
    located = _geometry_of(path, plan)
    profile = sample_surface_profile(path, plan, policy=_POLICY)

    assert len(located) == len(profile.samples)
    for item, sample in zip(located, profile.samples, strict=True):
        if item.reason is not None:
            assert (sample.elevation_m, sample.invalid_reason) == (None, item.reason)
    window = neighbour_window(located)
    if window is None:
        assert profile.window_cells_read == 0
    else:
        col0, col1, row0, row1 = window
        assert (col1 - col0) * (row1 - row0) == profile.window_cells_read
