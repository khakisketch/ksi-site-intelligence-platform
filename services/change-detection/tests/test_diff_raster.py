"""diff_raster 왕복 계약 — write_diff_geotiff → read_diff_geotiff.

``read_diff_geotiff`` 는 파일에서 crs·transform·cell_area_m2 를 다시 파싱하지
않고 이미 검증된 ``DiffRasterRef`` 에서 그대로 가져온다(모듈 docstring). 이
파일은 그 왕복이 실제로 값을 보존하는지, 그리고 파일과 ref 가 어긋나면
방어적으로 예외를 던지는지를 본다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from ksi_change_detection.diff_raster import (
    DiffRasterReadError,
    read_diff_geotiff,
    sha256_of_file,
    write_diff_geotiff,
)
from ksi_change_detection.dsm_diff import DiffResult
from ksi_event_contracts.design_conformance_report import DiffRasterRef
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from rasterio import Affine

_TRANSFORM = Affine(1.0, 0.0, 200000.0, 0.0, -1.0, 550000.0)
_VERTICAL = VerticalReference(
    datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
    basis="테스트",
    source=VerticalReferenceSource.PIPELINE_DECLARED,
)


def _diff(*, height: int = 6, width: int = 5) -> DiffResult:
    diff_m = np.zeros((height, width), dtype=np.float64)
    valid = np.ones((height, width), dtype=bool)
    diff_m[0, 0] = 0.3
    diff_m[1, 1] = -0.2
    valid[2, 2] = False  # nodata 셀 — 왕복 후에도 무효로 남아야 한다
    return DiffResult(
        diff_m=diff_m, valid=valid, transform=_TRANSFORM, crs="EPSG:5186", cell_area_m2=1.0
    )


def _ref_from(diff: DiffResult, path: Path) -> DiffRasterRef:
    height, width = diff.diff_m.shape
    return DiffRasterRef(
        diff_raster_id="d-1",
        digest=sha256_of_file(path),
        crs=diff.crs,
        vertical_reference=_VERTICAL,
        width=width,
        height=height,
        pixel_size_x_m=abs(diff.transform.a),
        pixel_size_y_m=abs(diff.transform.e),
        transform=(
            diff.transform.a,
            diff.transform.b,
            diff.transform.c,
            diff.transform.d,
            diff.transform.e,
            diff.transform.f,
        ),
        threshold_m=0.05,
        size_bytes=path.stat().st_size,
        core_verified_digest_at=datetime.now(UTC),
    )


def test_round_trip_preserves_values_and_validity(tmp_path: Path) -> None:
    diff = _diff()
    path = tmp_path / "diff.tif"
    write_diff_geotiff(diff, path)
    ref = _ref_from(diff, path)

    read_back = read_diff_geotiff(path, ref=ref)

    assert read_back.crs == diff.crs
    assert read_back.cell_area_m2 == pytest.approx(diff.cell_area_m2)
    assert read_back.transform.a == pytest.approx(diff.transform.a)
    assert read_back.transform.e == pytest.approx(diff.transform.e)
    assert bool(read_back.valid[2, 2]) is False
    assert np.array_equal(read_back.valid, diff.valid)
    np.testing.assert_allclose(read_back.diff_m[diff.valid], diff.diff_m[diff.valid], atol=1e-6)


def test_round_trip_uses_the_ref_geometry_not_the_file(tmp_path: Path) -> None:
    """crs·transform·cell_area_m2 는 파일이 아니라 ref 에서 온다(모듈 docstring)."""
    diff = _diff()
    path = tmp_path / "diff.tif"
    write_diff_geotiff(diff, path)
    ref = _ref_from(diff, path).model_copy(
        update={"crs": "EPSG:5179", "pixel_size_x_m": 2.0, "pixel_size_y_m": 2.0}
    )

    read_back = read_diff_geotiff(path, ref=ref)

    assert read_back.crs == "EPSG:5179"
    assert read_back.cell_area_m2 == pytest.approx(4.0)


def test_size_mismatch_between_file_and_ref_raises(tmp_path: Path) -> None:
    diff = _diff(height=6, width=5)
    path = tmp_path / "diff.tif"
    write_diff_geotiff(diff, path)
    ref = _ref_from(diff, path).model_copy(update={"height": 99, "width": 5})

    with pytest.raises(DiffRasterReadError, match="크기"):
        read_diff_geotiff(path, ref=ref)
