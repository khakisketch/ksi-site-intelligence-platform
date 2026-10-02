"""Pure Core-side planning must preserve exact native-cell boundaries."""

import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from ksi_geo_spatial.external_native_window_geometry import (
    NativeWindowError,
    plan_external_native_window,
)
from spatial_data_fixture import DIGEST, make_measurements


@pytest.mark.parametrize(
    "bounds,window,actual",
    [
        ((0.1, 8.1, 0.9, 8.9), (0, 1, 1, 2), (0, 8, 1, 9)),
        ((2.2, 3.1, 4.1, 6.2), (2, 5, 3, 7), (2, 3, 5, 7)),
        ((2, 3, 5, 7), (2, 5, 3, 7), (2, 3, 5, 7)),
        ((0, 0, 10, 10), (0, 10, 0, 10), (0, 0, 10, 10)),
    ],
)
def test_exact_native_edges_and_asymmetric_window_order(
    bounds: Any, window: Any, actual: Any
) -> None:
    geometry = plan_external_native_window(
        requested_bounds=bounds, measurements=make_measurements(), requested_crs_digest=DIGEST
    )
    # Adopt original order: column half-open interval followed by row interval.
    assert geometry.pixel_window == window
    assert geometry.actual_bounds == actual
    assert geometry.transform == (1, 0, actual[0], 0, -1, actual[3])


def test_nextafter_subpixel_is_not_rounded_to_an_exact_cell_edge() -> None:
    bounds = (2, 3, math.nextafter(5.0, math.inf), 7)
    geometry = plan_external_native_window(
        requested_bounds=bounds, measurements=make_measurements(), requested_crs_digest=DIGEST
    )
    assert geometry.pixel_window == (2, 6, 3, 7)
    assert geometry.actual_bounds == (2, 3, 6, 7)


@pytest.mark.parametrize(
    "bounds",
    [
        (True, 0, 1, 1),
        ("0", 0, 1, 1),
        (0, 0, math.nan, 1),
        (0, 0, math.inf, 1),
        (0, 0, 0, 1),
        (0, 0, 1, 0),
        (1, 0, 0, 1),
        (0, 0, 1),
    ],
)
def test_bad_bounds_fail_with_typed_reason(bounds: Any) -> None:
    with pytest.raises(NativeWindowError) as error:
        plan_external_native_window(
            requested_bounds=bounds, measurements=make_measurements(), requested_crs_digest=DIGEST
        )
    assert error.value.reason == "INVALID_REQUEST_BOUNDS"


@pytest.mark.parametrize(
    "bounds", [(-0.1, 0, 1, 1), (0, 0, 11, 1), (0, -0.1, 1, 1), (0, 0, 1, 10.1)]
)
def test_outside_source_is_never_clipped(bounds: Any) -> None:
    with pytest.raises(NativeWindowError) as error:
        plan_external_native_window(
            requested_bounds=bounds, measurements=make_measurements(), requested_crs_digest=DIGEST
        )
    assert error.value.reason == "REQUEST_OUTSIDE_SOURCE"


@pytest.mark.parametrize(
    "transform", [(1, 0.1, 0, 0, -1, 10), (-1, 0, 0, 0, -1, 10), (1, 0, 0, 0, 1, 10)]
)
def test_rotated_or_inverted_grid_refused(transform: Any) -> None:
    with pytest.raises(NativeWindowError) as error:
        plan_external_native_window(
            requested_bounds=(0, 0, 1, 1),
            measurements=make_measurements(transform=transform),
            requested_crs_digest=DIGEST,
        )
    assert error.value.reason == "UNSUPPORTED_GRID"


def test_exact_crs_not_customer_label_is_required() -> None:
    with pytest.raises(NativeWindowError) as error:
        plan_external_native_window(
            requested_bounds=(0, 0, 1, 1),
            measurements=make_measurements(),
            requested_crs_digest="sha256:" + "0" * 64,
        )
    assert error.value.reason == "CRS_MISMATCH"


def test_large_origin_uses_generated_edges_not_quotient_tolerance() -> None:
    x, y, step = 1e12, 1e12, 0.125
    geometry = plan_external_native_window(
        requested_bounds=(x + 2 * step, y - 7 * step, x + 5 * step, y - 3 * step),
        measurements=make_measurements(transform=(step, 0, x, 0, -step, y)),
        requested_crs_digest=DIGEST,
    )
    assert geometry.pixel_window == (2, 5, 3, 7)


def test_unrepresentable_neighboring_cells_fail_closed() -> None:
    with pytest.raises(NativeWindowError) as error:
        plan_external_native_window(
            requested_bounds=(1e16, 0, 1e16 + 4, 1),
            measurements=make_measurements(transform=(1, 0, 1e16, 0, -1, 10)),
            requested_crs_digest=DIGEST,
        )
    assert error.value.reason == "UNREPRESENTABLE_GRID"


def test_geometry_import_has_no_raster_decoder_dependencies() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import ksi_geo_spatial.external_native_window_geometry; "
                "assert not {'rasterio', 'numpy', 'pyproj'} & set(sys.modules)"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_native_primitive_uses_the_same_typed_error_boundary(tmp_path: Path) -> None:
    from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
    from ksi_geo_spatial.external_native_window import prepare_external_native_window
    from spatial_data_fixture import make_policy, make_source
    invalid_bounds: Any = (0, 0, 1)

    source = make_source()
    with pytest.raises(NativeWindowError) as error:
        prepare_external_native_window(
            source_path=tmp_path / "missing.tif",
            source_observed_sha256=DIGEST,
            source_size_bytes=source.observed_size_bytes,
            inspection=source.inspection,
            artifact_kind=ProcessingArtifactKind.DSM,
            requested_bounds=invalid_bounds,
            requested_crs_digest=DIGEST,
            output_path=tmp_path / "candidate.tif",
            envelope=make_policy().resource_envelope,
            max_output_pixels=10,
            max_output_bytes=4096,
        )
    assert error.value.reason == "INVALID_REQUEST_BOUNDS"


def test_real_native_candidate_receipt_preserves_asymmetric_pixel_intervals(tmp_path: Path) -> None:
    from dataclasses import asdict
    from hashlib import sha256

    from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
    from ksi_geo_spatial.external_native_window import prepare_external_native_window
    from spatial_data_fixture import make_receipt
    from test_external_native_window import _envelope, _inspection, _write_dsm

    tmp_path.chmod(0o700)
    path = tmp_path / "source.tif"
    _, _, crs_digest = _write_dsm(path)
    inspection = _inspection(path)
    assert inspection.measurements is not None
    bounds = (104, 186, 110, 194)
    prepared = prepare_external_native_window(
        source_path=path,
        source_observed_sha256="sha256:" + sha256(path.read_bytes()).hexdigest(),
        source_size_bytes=path.stat().st_size,
        inspection=inspection,
        artifact_kind=ProcessingArtifactKind.DSM,
        requested_bounds=bounds,
        requested_crs_digest=crs_digest,
        output_path=tmp_path / "candidate.tif",
        envelope=_envelope(),
        max_output_pixels=100,
        max_output_bytes=1_000_000,
    )
    facts = asdict(prepared.receipt)
    del facts["contract_version"]
    facts["source_resolution"] = (2.0, 2.0)
    facts["source_transform"] = inspection.measurements.transform
    receipt = make_receipt(**facts)
    geometry = plan_external_native_window(
        requested_bounds=bounds,
        measurements=inspection.measurements,
        requested_crs_digest=crs_digest,
    )
    assert receipt.pixel_window == geometry.pixel_window == (2, 5, 3, 7)
    assert receipt.actual_bounds == geometry.actual_bounds == bounds
    assert (receipt.width, receipt.height) == (3, 4)
    assert (
        receipt.output_sha256 == "sha256:" + sha256(prepared.output_path.read_bytes()).hexdigest()
    )


def test_real_fractional_grid_receipt_binds_source_edges_without_tolerance(tmp_path: Path) -> None:
    from dataclasses import asdict

    from rasterio.transform import from_origin
    from spatial_data_fixture import make_receipt
    from test_external_native_window import _inspection, _prepare, _write_dsm

    tmp_path.chmod(0o700)
    path = tmp_path / "fractional.tif"
    origin, step = 1000.123, 0.07
    _write_dsm(path, transform=from_origin(origin, 10.0, step, step))
    inspection = _inspection(path)
    assert inspection.measurements is not None
    bounds = (origin + step, 10.0 - step, origin + 2 * step, 10.0)
    candidate = _prepare(path, tmp_path / "candidate.tif", inspection=inspection, bounds=bounds)
    facts = asdict(candidate.receipt)
    del facts["contract_version"]
    facts["source_resolution"] = (step, step)
    facts["source_transform"] = inspection.measurements.transform
    receipt = make_receipt(**facts)
    assert receipt.actual_bounds == bounds
    assert receipt.pixel_window == (1, 2, 0, 1)
    assert receipt.source_transform == inspection.measurements.transform
    # One rounding unit differs on recomputation from the translated output origin.
    assert receipt.actual_bounds[2] != receipt.transform[2] + step * receipt.width
