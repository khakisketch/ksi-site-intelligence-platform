from __future__ import annotations

import math
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    NodataRepresentation,
    ObservedVerticalReferenceV1,
    RasterMeasurementsV1,
    ResourceEnvelopeV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_geo_spatial.external_native_window import NativeWindowError, _stable_pixel_index
from pyproj import CRS
from rasterio.transform import from_origin


def _digest_bytes(payload: bytes) -> str:
    return "sha256:" + sha256(payload).hexdigest()


def _footprint(transform: Any, width: int, height: int) -> str:
    a, b, c, d, e, f = transform[:6]
    corners = ((0, 0), (width, 0), (width, height), (0, height), (0, 0))
    points = [
        f"{('0' if a * col + b * row + c == 0 else format(a * col + b * row + c, '.17g'))} "
        f"{('0' if d * col + e * row + f == 0 else format(d * col + e * row + f, '.17g'))}"
        for col, row in corners
    ]
    return "POLYGON ((" + ", ".join(points) + "))"


def _envelope(**overrides: object) -> ResourceEnvelopeV1:
    values: dict[str, object] = {
        "max_input_bytes": 1_000_000,
        "max_streamed_bytes": 1_000_000,
        "max_tiff_directories": 16,
        "max_tiff_entries": 512,
        "max_pixels": 10_000,
        "max_bands": 4,
        "max_blocks": 1_000,
        "max_decompressed_bytes": 10_000_000,
        "max_sample_bytes": 1_000_000,
        "max_geometry_vertices": 8,
        "max_cpu_seconds": 10.0,
        "max_memory_bytes": 10_000_000,
        "max_workspace_bytes": 2_000_000,
        "max_output_bytes": 1_000_000,
        "max_tenant_concurrency": 1,
        "max_queue_depth": 1,
        "max_deadline_seconds": 30.0,
        "lease_duration_seconds": 30.0,
        "max_retry_attempts": 1,
    }
    values.update(overrides)
    return ResourceEnvelopeV1.model_validate(values).sealed()


def _write_dsm(
    path: Path, *, nodata: float = -9999.0, transform: Any = None
) -> tuple[np.ndarray, str, str]:
    values = np.arange(100, dtype=np.float32).reshape(10, 10)
    values[4, 4] = nodata
    transform = transform or from_origin(100.0, 200.0, 2.0, 2.0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=transform,
        nodata=nodata,
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="DEFLATE",
    ) as dataset:
        dataset.write(values, 1)
        dataset.update_tags(PRODUCER_NOTE="must not leak into the derivative")
    wkt = CRS.from_epsg(3857).to_wkt(version="WKT2_2019", pretty=False, output_axis_rule=True)
    return values, wkt, _digest_bytes(wkt.encode("utf-8"))


def _inspection(
    path: Path,
    *,
    artifact_kind: ProcessingArtifactKind = ProcessingArtifactKind.DSM,
    vertical_reference: ObservedVerticalReferenceV1 | None = None,
) -> ArtifactInspectionOutcomeV1:
    with rasterio.open(path) as dataset:
        epsg = CRS.from_user_input(dataset.crs).to_epsg()
        assert epsg is not None
        wkt = CRS.from_epsg(epsg).to_wkt(
            version="WKT2_2019", pretty=False, output_axis_rule=True
        )
        crs_digest = _digest_bytes(wkt.encode("utf-8"))
        transform = dataset.transform
        measurements = RasterMeasurementsV1(
            observed_crs_identifier="EPSG:3857",
            observed_crs_wkt=wkt,
            observed_crs_digest=crs_digest,
            observed_vertical_reference=vertical_reference,
            transform=(
                transform.a,
                transform.b,
                transform.c,
                transform.d,
                transform.e,
                transform.f,
            ),
            footprint_wkt=_footprint(dataset.transform, dataset.width, dataset.height),
            footprint_digest=_digest_bytes(
                _footprint(dataset.transform, dataset.width, dataset.height).encode("utf-8")
            ),
            width=dataset.width,
            height=dataset.height,
            band_count=dataset.count,
            dtype=dataset.dtypes[0],
            layout="GEOTIFF_TILED_V1",
            nodata_representation=(
                NodataRepresentation.MASK
                if artifact_kind is ProcessingArtifactKind.ORTHO
                else NodataRepresentation.FINITE
            ),
            nodata_value=float(dataset.nodata) if dataset.nodata is not None else None,
            valid_pixel_count=int(np.count_nonzero(dataset.dataset_mask() == 255)),
        )
    return ArtifactInspectionOutcomeV1(
        artifact_id="dsm-1",
        observed_sha256=_digest_bytes(path.read_bytes()),
        outcome=ArtifactOutcome.MEASURED,
        measurements=measurements,
    )


def _prepare(
    path: Path,
    output: Path,
    *,
    bounds: tuple[float, float, float, float] = (102.1, 183.9, 108.1, 193.9),
    artifact_kind: ProcessingArtifactKind = ProcessingArtifactKind.DSM,
    **kwargs: Any,
) -> Any:
    from ksi_geo_spatial.external_native_window import prepare_external_native_window

    inspection = kwargs.pop("inspection", _inspection(path, artifact_kind=artifact_kind))
    with rasterio.open(path) as dataset:
        epsg = CRS.from_user_input(dataset.crs).to_epsg()
        assert epsg is not None
        crs_digest = _digest_bytes(
            CRS.from_epsg(epsg)
            .to_wkt(version="WKT2_2019", pretty=False, output_axis_rule=True)
            .encode("utf-8")
        )
    requested_crs_digest = kwargs.pop("requested_crs_digest", crs_digest)
    envelope = kwargs.pop("envelope", _envelope())
    max_output_pixels = kwargs.pop("max_output_pixels", 100)
    max_output_bytes = kwargs.pop("max_output_bytes", 500_000)
    return prepare_external_native_window(
        source_path=path,
        source_observed_sha256=_digest_bytes(path.read_bytes()),
        source_size_bytes=path.stat().st_size,
        inspection=inspection,
        artifact_kind=artifact_kind,
        requested_bounds=bounds,
        requested_crs_digest=requested_crs_digest,
        output_path=output,
        envelope=envelope,
        max_output_pixels=max_output_pixels,
        max_output_bytes=max_output_bytes,
        **kwargs,
    )


def _write_ortho(path: Path) -> np.ndarray:
    values = np.zeros((3, 10, 10), dtype=np.uint8)
    values[0] = 17
    values[1] = np.indices((10, 10))[0]
    values[2] = np.indices((10, 10))[1]
    with (
        rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True),
        rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=10,
            height=10,
            count=3,
            dtype="uint8",
            crs="EPSG:3857",
            transform=from_origin(100.0, 200.0, 2.0, 2.0),
            tiled=True,
            blockxsize=16,
            blockysize=16,
            compress="DEFLATE",
            photometric="RGB",
        ) as dataset,
    ):
        dataset.write(values)
        mask = np.full((10, 10), 255, dtype=np.uint8)
        mask[2, 2] = 0
        dataset.write_mask(mask)
    return values


def test_native_window_uses_half_open_pixel_edges_and_preserves_nodata(tmp_path: Path) -> None:
    source = tmp_path / "source.tif"
    output = tmp_path / "window.tif"
    values, _, _ = _write_dsm(source)

    result = _prepare(source, output)

    assert result.receipt.pixel_window == (1, 5, 3, 9)
    assert result.receipt.requested_bounds == (102.1, 183.9, 108.1, 193.9)
    assert result.receipt.actual_bounds == (102.0, 182.0, 110.0, 194.0)
    assert result.receipt.transform == (2.0, 0.0, 102.0, 0.0, -2.0, 194.0)
    assert result.receipt.accuracy_assessed is False
    assert result.receipt.output_sha256 == _digest_bytes(output.read_bytes())
    assert result.receipt.output_size_bytes == output.stat().st_size
    with rasterio.open(output) as dataset:
        np.testing.assert_array_equal(dataset.read(1), values[3:9, 1:5])
        assert dataset.nodata == -9999.0
        assert dataset.read_masks(1)[1, 3] == 0
        assert "PRODUCER_NOTE" not in dataset.tags()


def test_native_window_preserves_orthophoto_mask_and_pixel_values(tmp_path: Path) -> None:
    source = tmp_path / "ortho.tif"
    output = tmp_path / "window.tif"
    values = _write_ortho(source)

    result = _prepare(
        source,
        output,
        bounds=(100.0, 190.0, 108.0, 200.0),
        artifact_kind=ProcessingArtifactKind.ORTHO,
    )

    assert result.receipt.artifact_kind is ProcessingArtifactKind.ORTHO
    assert result.receipt.valid_pixel_count == 19
    with rasterio.open(output) as dataset:
        np.testing.assert_array_equal(dataset.read(), values[:, 0:5, 0:4])
        assert dataset.read_masks(1)[2, 2] == 0
        assert "PRODUCER_NOTE" not in dataset.tags()


def test_native_window_does_not_add_a_pixel_for_exact_cell_edges(tmp_path: Path) -> None:
    source = tmp_path / "source.tif"
    output = tmp_path / "window.tif"
    _write_dsm(source)

    result = _prepare(source, output, bounds=(102.0, 190.0, 108.0, 194.0))

    assert result.receipt.pixel_window == (1, 4, 3, 5)
    assert result.receipt.actual_bounds == (102.0, 190.0, 108.0, 194.0)


def test_fractional_affine_exact_east_and_south_edges_stay_half_open(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fractional.tif"
    output = tmp_path / "window.tif"
    transform = rasterio.Affine(0.1, 0.0, 0.1, 0.0, -0.1, 0.3)
    _write_dsm(source, transform=transform)
    east = transform.c + transform.a * 2
    south = transform.f + transform.e * 2

    result = _prepare(source, output, bounds=(transform.c, south, east, transform.f))

    assert result.receipt.pixel_window == (0, 2, 0, 2)
    assert result.receipt.actual_bounds == (
        transform.c,
        south,
        east,
        transform.f,
    )


def test_fractional_bbox_just_outside_source_edge_is_rejected_not_clipped(
    tmp_path: Path,
) -> None:
    from ksi_geo_spatial.external_native_window import NativeWindowError

    source = tmp_path / "fractional.tif"
    output = tmp_path / "window.tif"
    transform = rasterio.Affine(0.1, 0.0, 0.1, 0.0, -0.1, 0.3)
    _write_dsm(source, transform=transform)
    east = transform.c + transform.a * 10
    beyond_east = math.nextafter(east, math.inf)

    with pytest.raises(NativeWindowError) as raised:
        _prepare(source, output, bounds=(transform.c, 0.0, beyond_east, transform.f))

    assert raised.value.reason == "REQUEST_OUTSIDE_SOURCE"
    assert not output.exists()


@pytest.mark.parametrize("axis", ["east", "south"])
def test_fractional_request_just_beyond_internal_edge_keeps_full_coverage(
    tmp_path: Path, axis: str
) -> None:
    source = tmp_path / "fractional.tif"
    output = tmp_path / "window.tif"
    transform = rasterio.Affine(0.1, 0.0, 0.1, 0.0, -0.1, 0.3)
    _write_dsm(source, transform=transform)
    east_edge = transform.c + transform.a * 2
    south_edge = transform.f + transform.e * 2
    east = math.nextafter(east_edge, math.inf) if axis == "east" else east_edge
    south = math.nextafter(south_edge, -math.inf) if axis == "south" else south_edge

    result = _prepare(
        source,
        output,
        bounds=(transform.c, south, east, transform.f),
    )

    if axis == "east":
        assert result.receipt.pixel_window == (0, 3, 0, 2)
        assert result.receipt.actual_bounds[2] >= east
    else:
        assert result.receipt.pixel_window == (0, 2, 0, 3)
        assert result.receipt.actual_bounds[1] <= south


@pytest.mark.parametrize("axis", ["east", "south"])
def test_offset_fractional_exact_internal_edge_stays_half_open(tmp_path: Path, axis: str) -> None:
    source = tmp_path / "offset-fractional.tif"
    output = tmp_path / "window.tif"
    transform = rasterio.Affine(0.1, 0.0, 1000.1, 0.0, -0.1, 1000.3)
    _write_dsm(source, transform=transform)
    east_edge = transform.c + transform.a
    south_edge = transform.f + transform.e
    east = east_edge if axis == "east" else transform.c + transform.a * 2
    south = south_edge if axis == "south" else transform.f + transform.e * 2

    result = _prepare(
        source,
        output,
        bounds=(transform.c, south, east, transform.f),
    )

    if axis == "east":
        assert result.receipt.pixel_window == (0, 1, 0, 2)
        assert result.receipt.actual_bounds[2] == east_edge
    else:
        assert result.receipt.pixel_window == (0, 2, 0, 1)
        assert result.receipt.actual_bounds[1] == south_edge


@pytest.mark.parametrize("axis", ["east", "south"])
def test_offset_fractional_just_outside_internal_edge_keeps_full_coverage(
    tmp_path: Path, axis: str
) -> None:
    source = tmp_path / "offset-fractional.tif"
    output = tmp_path / "window.tif"
    transform = rasterio.Affine(0.1, 0.0, 1000.1, 0.0, -0.1, 1000.3)
    _write_dsm(source, transform=transform)
    east_edge = transform.c + transform.a
    south_edge = transform.f + transform.e
    east = math.nextafter(east_edge, math.inf) if axis == "east" else east_edge
    south = math.nextafter(south_edge, -math.inf) if axis == "south" else south_edge

    result = _prepare(
        source,
        output,
        bounds=(transform.c, south, east, transform.f),
    )

    if axis == "east":
        assert result.receipt.pixel_window == (0, 2, 0, 1)
        assert result.receipt.actual_bounds[2] >= east
    else:
        assert result.receipt.pixel_window == (0, 1, 0, 2)
        assert result.receipt.actual_bounds[1] <= south


def test_pixel_index_rejects_grid_with_collapsed_float_boundaries() -> None:
    with pytest.raises(NativeWindowError) as raised:
        _stable_pixel_index(1e16, 1e16, 0.5, 10, rounding="floor")

    assert raised.value.reason == "UNREPRESENTABLE_GRID"


@pytest.mark.parametrize(
    ("bounds", "reason"),
    [
        ((99.0, 181.0, 103.0, 189.0), "REQUEST_OUTSIDE_SOURCE"),
        ((108.0, 190.0, 108.0, 194.0), "INVALID_REQUEST_BOUNDS"),
        ((float("nan"), 190.0, 108.0, 194.0), "INVALID_REQUEST_BOUNDS"),
    ],
)
def test_native_window_rejects_invalid_or_outside_bounds(
    tmp_path: Path, bounds: tuple[float, float, float, float], reason: str
) -> None:
    from ksi_geo_spatial.external_native_window import NativeWindowError

    source = tmp_path / "source.tif"
    output = tmp_path / "window.tif"
    _write_dsm(source)

    with pytest.raises(NativeWindowError) as raised:
        _prepare(source, output, bounds=bounds)

    assert raised.value.reason == reason
    assert not output.exists()


def test_native_window_rejects_byte_substitution_after_inspection(tmp_path: Path) -> None:
    from ksi_geo_spatial.external_native_window import NativeWindowError

    source = tmp_path / "source.tif"
    output = tmp_path / "window.tif"
    _write_dsm(source)
    inspection = _inspection(source)
    source.write_bytes(source.read_bytes() + b"substitution")

    with pytest.raises(NativeWindowError) as raised:
        _prepare(source, output, inspection=inspection)

    assert raised.value.reason == "SOURCE_BYTES_MISMATCH"
    assert not output.exists()


def test_native_window_rejects_crs_digest_and_rotated_grid_mismatch(tmp_path: Path) -> None:
    from ksi_geo_spatial.external_native_window import NativeWindowError

    source = tmp_path / "source.tif"
    output = tmp_path / "window.tif"
    _write_dsm(source)
    inspection = _inspection(source)

    with pytest.raises(NativeWindowError) as raised:
        _prepare(source, output, inspection=inspection, requested_crs_digest="sha256:" + "0" * 64)
    assert raised.value.reason == "CRS_MISMATCH"

    rotated_path = tmp_path / "rotated.tif"
    _write_dsm(rotated_path, transform=rasterio.Affine(2.0, 0.25, 100.0, 0.0, -2.0, 200.0))
    rotated = _inspection(rotated_path)
    with pytest.raises(NativeWindowError) as raised:
        _prepare(rotated_path, output, inspection=rotated)
    assert raised.value.reason == "UNSUPPORTED_GRID"
    assert not output.exists()


def test_native_window_rejects_explicit_vertical_reference_mismatch(tmp_path: Path) -> None:
    from ksi_geo_spatial.external_native_window import NativeWindowError

    source = tmp_path / "source.tif"
    output = tmp_path / "window.tif"
    _write_dsm(source)
    observed_vertical = ObservedVerticalReferenceV1(identifier="EPSG:5703", basis="NAVD88 height")

    with pytest.raises(NativeWindowError) as raised:
        _prepare(
            source,
            output,
            inspection=_inspection(source, vertical_reference=observed_vertical),
            expected_vertical_reference_digest="sha256:" + "0" * 64,
        )

    assert raised.value.reason == "VERTICAL_REFERENCE_MISMATCH"
    assert not output.exists()


def test_native_window_rejects_limits_and_cleans_output_on_cancel(tmp_path: Path) -> None:
    from ksi_geo_spatial.external_native_window import NativeWindowError

    source = tmp_path / "source.tif"
    output = tmp_path / "window.tif"
    _write_dsm(source)

    with pytest.raises(NativeWindowError) as raised:
        _prepare(source, output, bounds=(100.0, 180.0, 120.0, 200.0), max_output_pixels=99)
    assert raised.value.reason == "OUTPUT_PIXEL_LIMIT_EXCEEDED"
    assert not output.exists()

    with pytest.raises(NativeWindowError) as raised:
        _prepare(source, output, is_cancelled=lambda: True)
    assert raised.value.reason == "CANCELLED"
    assert not output.exists()


def test_native_window_removes_private_partial_candidate_when_cancelled_mid_run(
    tmp_path: Path,
) -> None:
    from ksi_geo_spatial.external_native_window import NativeWindowError

    source = tmp_path / "source.tif"
    output = tmp_path / "window.tif"
    _write_dsm(source)
    checks = 0

    def cancel_during_verification() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 6

    with pytest.raises(NativeWindowError) as raised:
        _prepare(source, output, is_cancelled=cancel_during_verification)

    assert raised.value.reason == "CANCELLED"
    assert not output.exists()
    assert not tuple(tmp_path.glob(".ksi-window-*"))


def test_gdal_read_write_and_candidate_verification_use_offline_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.tif"
    output = tmp_path / "window.tif"
    _write_dsm(source)
    inspection = _inspection(source)
    real_env = rasterio.Env
    observed_settings: list[dict[str, object]] = []

    class EnvironmentProbe:
        def __init__(self, **options: object) -> None:
            self.environment = real_env(**options)

        def __enter__(self) -> Any:
            result = self.environment.__enter__()
            observed_settings.append(rasterio.env.getenv())
            return result

        def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
            return self.environment.__exit__(exc_type, exc_value, traceback)

    monkeypatch.setattr(rasterio, "Env", EnvironmentProbe)
    _prepare(source, output, inspection=inspection)

    assert len(observed_settings) >= 3
    for settings in observed_settings:
        assert settings.get("PROJ_NETWORK") == "OFF"
        assert settings.get("GDAL_PAM_ENABLED") == "NO"
        assert settings.get("GDAL_DRIVER_PATH") == "disable"
        assert settings.get("GDAL_DISABLE_READDIR_ON_OPEN") == "EMPTY_DIR"


def test_cleanup_failure_suppresses_receipt_and_removes_published_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_geo_spatial.external_native_window as native_window

    source = tmp_path / "source.tif"
    output = tmp_path / "window.tif"
    _write_dsm(source)
    inspection = _inspection(source)
    real_rmtree = shutil.rmtree

    def fail_cleanup(path: Path, *args: Any, **kwargs: Any) -> None:
        raise PermissionError("simulated private workspace cleanup failure")

    monkeypatch.setattr(native_window.shutil, "rmtree", fail_cleanup)
    with pytest.raises(native_window.NativeWindowError) as raised:
        _prepare(source, output, inspection=inspection)

    assert raised.value.reason == "PRIVATE_WORKSPACE_CLEANUP_FAILED"
    assert not output.exists()
    leftovers = tuple(tmp_path.glob(".ksi-window-*"))
    assert len(leftovers) == 1
    monkeypatch.setattr(native_window.shutil, "rmtree", real_rmtree)
    for private_dir in leftovers:
        real_rmtree(private_dir)


def test_native_window_requires_measured_raster_and_nonempty_valid_window(tmp_path: Path) -> None:
    from ksi_geo_spatial.external_native_window import NativeWindowError

    source = tmp_path / "source.tif"
    output = tmp_path / "window.tif"
    _write_dsm(source)
    rejected = ArtifactInspectionOutcomeV1(
        artifact_id="dsm-1",
        observed_sha256=_digest_bytes(source.read_bytes()),
        outcome=ArtifactOutcome.REJECTED,
        reason="UNSUPPORTED_RASTER",
    )

    with pytest.raises(NativeWindowError) as raised:
        _prepare(source, output, inspection=rejected)
    assert raised.value.reason == "SOURCE_NOT_MEASURED"

    with pytest.raises(NativeWindowError) as raised:
        _prepare(source, output, bounds=(108.1, 190.1, 108.2, 190.2))
    assert raised.value.reason == "EMPTY_VALID_WINDOW"
    assert not output.exists()
