"""Synthetic-only deterministic ORTHO sanitizer conformance."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
import rasterio
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_processing_controller.external_tiff_structure import parse_sealed_tiff_structure
from rasterio.transform import from_origin


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=20_000_000,
        max_streamed_bytes=20_000_000,
        max_tiff_directories=32,
        max_tiff_entries=2_048,
        max_pixels=2_000_000,
        max_bands=4,
        max_blocks=2_048,
        max_decompressed_bytes=40_000_000,
        max_sample_bytes=40_000_000,
        max_geometry_vertices=8,
        max_cpu_seconds=1.0,
        max_memory_bytes=40_000_000,
        max_workspace_bytes=40_000_000,
        max_output_bytes=20_000_000,
        max_tenant_concurrency=1,
        max_queue_depth=1,
        max_deadline_seconds=1.0,
        lease_duration_seconds=1.0,
        max_retry_attempts=1,
    ).sealed()


def _digest(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _write_rgba(path: Path, *, dimension: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    # A COG needs more than one physical tile for GDAL to expose `tiled=True`
    # through Rasterio; use four fixed 512-pixel tiles.
    height = width = dimension
    values = np.empty((4, height, width), dtype=np.uint8)
    values[0] = np.indices((height, width))[1] % 251
    values[1] = np.indices((height, width))[0] % 251
    values[2] = 211
    alpha = np.full((height, width), 255, dtype=np.uint8)
    alpha[:128, :256] = 0
    values[3] = alpha
    # Source RGB under invalid alpha deliberately contains nonzero producer bytes.
    values[:3, :128, :256] = 73
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=4,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(100.0, 200.0, 2.0, 2.0),
        tiled=True,
        blockxsize=256,
        blockysize=256,
        compress="DEFLATE",
        predictor=2,
        interleave="pixel",
        photometric="RGB",
        ALPHA="YES",
    ) as dataset:
        dataset.write(values)
        dataset.update_tags(PRODUCER_NOTE="must-not-cross-the-derivative-boundary")
    return values[:3], alpha


def _write_rgb(path: Path) -> np.ndarray:
    values = np.zeros((3, 512, 512), dtype=np.uint8)
    values[0] = 17
    values[1] = np.indices((512, 512))[0] % 253
    values[2] = np.indices((512, 512))[1] % 251
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=512,
        height=512,
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(100.0, 200.0, 2.0, 2.0),
        tiled=True,
        blockxsize=256,
        blockysize=256,
        compress="DEFLATE",
        predictor=2,
        interleave="pixel",
        photometric="RGB",
    ) as dataset:
        dataset.write(values)
    return values


def test_sanitizer_writes_deterministic_cog_rgb_and_binary_internal_mask(tmp_path: Path) -> None:
    """Valid RGB stays exact, invalid RGB zeroes, and source metadata never crosses the boundary."""
    from ksi_processing_controller.external_sanitized_raster import sanitize_measured_ortho

    source = tmp_path / "source.tif"
    output_a = tmp_path / "sanitized-a.tif"
    output_b = tmp_path / "sanitized-b.tif"
    source_rgb, alpha = _write_rgba(source)

    first = sanitize_measured_ortho(
        source_path=source,
        source_observed_sha256=_digest(source),
        artifact_id="ortho",
        output_path=output_a,
        envelope=_envelope(),
    )
    second = sanitize_measured_ortho(
        source_path=source,
        source_observed_sha256=_digest(source),
        artifact_id="ortho",
        output_path=output_b,
        envelope=_envelope(),
    )

    assert output_a.read_bytes() == output_b.read_bytes()
    assert first.output_sha256 == _digest(output_a) == second.output_sha256
    assert first.output_size_bytes == output_a.stat().st_size
    assert first.measurements == second.measurements
    assert first.measurements.width == 1024
    assert first.measurements.height == 1024
    assert first.measurements.band_count == 3
    assert first.measurements.dtype == "uint8"
    assert first.measurements.layout == "COG_PROFILE_V1"
    assert first.measurements.valid_pixel_count == int(np.count_nonzero(alpha == 255))

    with rasterio.open(output_a) as dataset:
        assert dataset.count == 3
        assert dataset.dtypes == ("uint8", "uint8", "uint8")
        assert dataset.transform == from_origin(100.0, 200.0, 2.0, 2.0)
        assert dataset.crs.to_epsg() == 3857
        output_rgb = dataset.read()
        output_mask = dataset.read_masks(1)
        expected_rgb = source_rgb.copy()
        expected_rgb[:, alpha == 0] = 0
        assert np.array_equal(output_rgb, expected_rgb)
        assert np.array_equal(output_mask, alpha)
        assert "PRODUCER_NOTE" not in dataset.tags()
        assert not any(key.upper().startswith("STATISTICS_") for key in dataset.tags())


def test_sanitizer_rejects_candidate_that_changes_pixels_or_declared_hash(
    tmp_path: Path,
) -> None:
    """The local derivative is not a receipt: any post-write drift invalidates the candidate."""
    from ksi_processing_controller.external_sanitized_raster import (
        SanitizedRasterError,
        sanitize_measured_ortho,
        verify_sanitized_ortho,
    )

    source = tmp_path / "source.tif"
    output = tmp_path / "sanitized.tif"
    _write_rgba(source)
    result = sanitize_measured_ortho(
        source_path=source,
        source_observed_sha256=_digest(source),
        artifact_id="ortho",
        output_path=output,
        envelope=_envelope(),
    )
    with rasterio.open(output, "r+", IGNORE_COG_LAYOUT_BREAK="YES") as dataset:
        changed = dataset.read(1)
        changed[200, 200] ^= 1
        dataset.write(changed, 1)

    with pytest.raises(SanitizedRasterError, match="digest|pixel"):
        verify_sanitized_ortho(
            source_path=source,
            source_observed_sha256=_digest(source),
            artifact_id="ortho",
            output_path=output,
            expected_output_sha256=result.output_sha256,
            envelope=_envelope(),
        )


def test_sanitizer_accepts_a_single_tile_cog_when_raw_layout_is_valid(tmp_path: Path) -> None:
    """GDAL's `tiled=False` presentation hint does not turn a valid COG into stripes."""
    from ksi_processing_controller.external_sanitized_raster import sanitize_measured_ortho

    source = tmp_path / "source.tif"
    output = tmp_path / "sanitized.tif"
    _write_rgba(source, dimension=512)

    result = sanitize_measured_ortho(
        source_path=source,
        source_observed_sha256=_digest(source),
        artifact_id="ortho",
        output_path=output,
        envelope=_envelope(),
    )

    assert result.measurements.layout == "COG_PROFILE_V1"


@pytest.mark.parametrize("dimension", [513, 777, 1025])
def test_sanitizer_builds_the_required_ceil_overview_chain_for_odd_dimensions(
    tmp_path: Path,
    dimension: int,
) -> None:
    """Every measurable source geometry remains within the fixed sanitizer lane."""
    from ksi_processing_controller.external_sanitized_raster import sanitize_measured_ortho

    source = tmp_path / "source.tif"
    output = tmp_path / "sanitized.tif"
    _write_rgba(source, dimension=dimension)

    result = sanitize_measured_ortho(
        source_path=source,
        source_observed_sha256=_digest(source),
        artifact_id="ortho",
        output_path=output,
        envelope=_envelope(),
    )

    assert result.measurements.width == dimension
    assert result.measurements.height == dimension
    assert result.measurements.layout == "COG_PROFILE_V1"


def test_sanitizer_handles_non_aligned_binary_mask_boundaries(tmp_path: Path) -> None:
    """Average image and nearest-mask overviews share the fixed validity semantics."""
    from ksi_processing_controller.external_sanitized_raster import sanitize_measured_ortho

    source = tmp_path / "source.tif"
    output = tmp_path / "sanitized.tif"
    _write_rgba(source)
    with rasterio.open(source, "r+") as dataset:
        alpha = dataset.read(4)
        alpha[401:404, 501:504] = 0
        dataset.write(alpha, 4)

    result = sanitize_measured_ortho(
        source_path=source,
        source_observed_sha256=_digest(source),
        artifact_id="ortho",
        output_path=output,
        envelope=_envelope(),
    )

    assert result.measurements.layout == "COG_PROFILE_V1"


@pytest.mark.parametrize("dimension", [1024, 777, 1025])
def test_sanitizer_materializes_nearest_physical_mask_overviews_for_irregular_masks(
    tmp_path: Path,
    dimension: int,
) -> None:
    """Every physical mask IFD is the approved nearest binary derivative."""
    from ksi_processing_controller.external_sanitized_raster import sanitize_measured_ortho

    source = tmp_path / "source.tif"
    output = tmp_path / "sanitized.tif"
    _write_rgba(source, dimension=dimension)
    with rasterio.open(source, "r+") as dataset:
        alpha = dataset.read(4)
        alpha[401:420, 501:520] = np.random.default_rng(42).choice(
            np.array([0, 255], dtype=np.uint8),
            size=(19, 19),
        )
        dataset.write(alpha, 4)

    result = sanitize_measured_ortho(
        source_path=source,
        source_observed_sha256=_digest(source),
        artifact_id="ortho",
        output_path=output,
        envelope=_envelope(),
    )

    assert result.measurements.layout == "COG_PROFILE_V1"
    _assert_physical_mask_overviews_are_nearest(output)


@pytest.mark.parametrize("dimension", [777, 1024, 1025])
def test_sanitizer_first_physical_mask_overview_matches_gdal_nearest_fixture(
    tmp_path: Path,
    dimension: int,
) -> None:
    """The physical first mask IFD matches a separately generated GDAL NEAREST IFD."""
    from ksi_processing_controller.external_sanitized_raster import sanitize_measured_ortho

    source = tmp_path / "source.tif"
    output = tmp_path / "sanitized.tif"
    nearest = tmp_path / "nearest.tif"
    _write_rgba(source, dimension=dimension)
    binary_mask = np.random.default_rng(601).choice(
        np.array([0, 255], dtype=np.uint8),
        size=(dimension, dimension),
    )
    with rasterio.open(source, "r+") as dataset:
        dataset.write(binary_mask, 4)
    with rasterio.open(
        nearest,
        "w",
        driver="GTiff",
        width=dimension,
        height=dimension,
        count=1,
        dtype="uint8",
        tiled=True,
        blockxsize=256,
        blockysize=256,
        compress="DEFLATE",
        predictor=2,
    ) as fixture:
        fixture.write((binary_mask == 255).astype(np.uint8), 1)
        fixture.build_overviews([2], rasterio.enums.Resampling.nearest)

    sanitize_measured_ortho(
        source_path=source,
        source_observed_sha256=_digest(source),
        artifact_id="ortho",
        output_path=output,
        envelope=_envelope(),
    )

    candidate_index = _first_physical_mask_overview_index(output)
    # The independently built one-band fixture has its base IFD first and its
    # only physical overview second; no closed-profile parser normalizes it.
    with (
        rasterio.open(f"GTIFF_DIR:2:{nearest}", "r") as expected,
        rasterio.open(f"GTIFF_DIR:{candidate_index}:{output}", "r") as observed,
    ):
        assert observed.width == expected.width
        assert observed.height == expected.height
        assert np.array_equal(observed.read(1), expected.read(1))


def test_sanitizer_turns_rgb_without_nodata_into_an_all_valid_internal_mask(tmp_path: Path) -> None:
    """The fixed derivative always carries its fresh binary validity band."""
    from ksi_processing_controller.external_sanitized_raster import sanitize_measured_ortho

    source = tmp_path / "source.tif"
    output = tmp_path / "sanitized.tif"
    source_rgb = _write_rgb(source)

    result = sanitize_measured_ortho(
        source_path=source,
        source_observed_sha256=_digest(source),
        artifact_id="ortho",
        output_path=output,
        envelope=_envelope(),
    )

    assert result.measurements.nodata_representation.value == "MASK"
    assert result.measurements.valid_pixel_count == 512 * 512
    with rasterio.open(output) as dataset:
        assert np.array_equal(dataset.read(), source_rgb)
        assert np.array_equal(dataset.read_masks(1), np.full((512, 512), 255, dtype=np.uint8))


def test_sanitizer_rejects_changed_physical_overview_with_new_digest(
    tmp_path: Path,
) -> None:
    """Rebinding a candidate hash cannot bless stale or altered overview pixels."""
    from ksi_processing_controller.external_sanitized_raster import (
        SanitizedRasterError,
        _require_fresh_overviews,
        sanitize_measured_ortho,
        verify_sanitized_ortho,
    )

    source = tmp_path / "source.tif"
    output = tmp_path / "sanitized.tif"
    _write_rgba(source)
    sanitize_measured_ortho(
        source_path=source,
        source_observed_sha256=_digest(source),
        artifact_id="ortho",
        output_path=output,
        envelope=_envelope(),
    )
    mask_index = _first_physical_mask_overview_index(output)
    with rasterio.open(
        f"GTIFF_DIR:{mask_index}:{output}", "r+", IGNORE_COG_LAYOUT_BREAK="YES"
    ) as overview:
        changed = overview.read(1)
        changed[200, 200] ^= 1
        overview.write(changed, 1)

    with pytest.raises(SanitizedRasterError, match="nearest-mask"):
        _require_fresh_overviews(
            output_path=output,
            envelope=_envelope(),
            is_cancelled=None,
        )

    with pytest.raises(SanitizedRasterError, match="overview|layout"):
        verify_sanitized_ortho(
            source_path=source,
            source_observed_sha256=_digest(source),
            artifact_id="ortho",
            output_path=output,
            expected_output_sha256=_digest(output),
            envelope=_envelope(),
        )


def _first_physical_mask_overview_index(path: Path) -> int:
    return _overview_directory_index(path, subtype=5)


def _overview_directory_index(path: Path, *, subtype: int) -> int:
    structure = parse_sealed_tiff_structure(path, _envelope())
    byte_order = "<" if structure.byte_order == "II" else ">"
    for index, directory in enumerate(structure.directories, start=1):
        subtype_entry = directory.entries.get(254)
        if subtype_entry is not None and subtype_entry.integers(byte_order) == (subtype,):
            return index
    raise AssertionError(f"fixture has no physical subtype-{subtype} overview")


def _assert_physical_mask_overviews_are_nearest(path: Path) -> None:
    structure = parse_sealed_tiff_structure(path, _envelope())
    byte_order = "<" if structure.byte_order == "II" else ">"
    image_overviews: list[int] = []
    mask_overviews: dict[tuple[int, int], int] = {}
    for index, directory in enumerate(structure.directories, start=1):
        subtype = directory.entries.get(254)
        value = 0 if subtype is None else subtype.integers(byte_order)[0]
        width = directory.entries[256].integers(byte_order)
        height = directory.entries[257].integers(byte_order)
        assert len(width) == len(height) == 1
        if value == 1:
            image_overviews.append(index)
        elif value == 5:
            mask_overviews[(width[0], height[0])] = index

    with rasterio.open(path, "r") as base:
        expected = (base.read_masks(1) == 255).astype(np.uint8)
        assert image_overviews
        for image_index in image_overviews:
            with rasterio.open(f"GTIFF_DIR:{image_index}:{path}", "r") as image:
                rows = _gdal_nearest_indices(expected.shape[0], image.height)
                columns = _gdal_nearest_indices(expected.shape[1], image.width)
                expected = expected[np.ix_(rows, columns)]
                mask_index = mask_overviews[(image.width, image.height)]
                with rasterio.open(f"GTIFF_DIR:{mask_index}:{path}", "r") as mask:
                    assert np.array_equal(mask.read(1), expected)


def _gdal_nearest_indices(source_size: int, destination_size: int) -> np.ndarray:
    """Independent exact integer form of GDAL's nearest overview index mapping."""
    destination = np.arange(destination_size, dtype=np.int64)
    return (2 * destination * source_size + destination_size) // (2 * destination_size)
