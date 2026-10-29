"""The additive mask predecoder must not widen the retained DSM/RGB profile."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from ksi_processing_controller.external_tiff_structure import (
    TiffResourceLimitError,
    TiffStructureError,
    parse_sealed_binary_mask_tiff_structure,
    parse_sealed_tiff_structure,
)
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from test_external_analysis_measurement import _envelope


def _mask(
    path: Path,
    *,
    dtype: str = "uint8",
    nodata: int | None = None,
    bands: int = 1,
    stripes: bool = False,
) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=bands,
        dtype=dtype,
        crs="EPSG:5186",
        transform=from_origin(200000, 550000, 1, 1),
        nodata=nodata,
        **({"blockysize": 1} if stripes else {}),
    ) as dataset:
        dataset.write(np.zeros((bands, 16, 16), dtype=dtype))
    return path


def test_uint8_single_band_is_additive_and_still_rejected_by_the_old_profile(
    tmp_path: Path,
) -> None:
    source = _mask(tmp_path / "binary.tif")
    structure = parse_sealed_binary_mask_tiff_structure(source, _envelope())
    assert len(structure.directories) == 1
    assert structure.estimated_sample_bytes == 256
    with pytest.raises(TiffStructureError, match="sample model"):
        parse_sealed_tiff_structure(source, _envelope())


@pytest.mark.parametrize("nodata", [0, 1, 255])
def test_any_raw_nodata_tag_is_rejected_before_native_decode(tmp_path: Path, nodata: int) -> None:
    source = _mask(tmp_path / "nodata.tif", nodata=nodata)
    with pytest.raises(TiffStructureError, match="NoData"):
        parse_sealed_binary_mask_tiff_structure(source, _envelope())


@pytest.mark.parametrize("options", [{"dtype": "float32"}, {"dtype": "uint16"}, {"bands": 3}])
def test_raw_sample_model_cannot_be_normalized_into_a_binary_mask(
    tmp_path: Path, options: dict[str, Any]
) -> None:
    with pytest.raises(TiffStructureError, match="UINT8"):
        parse_sealed_binary_mask_tiff_structure(_mask(tmp_path / "bad.tif", **options), _envelope())


def test_extra_image_directory_is_never_silently_selected_by_native_decoder(tmp_path: Path) -> None:
    source = _mask(tmp_path / "overviews.tif")
    with rasterio.open(source, "r+") as dataset:
        dataset.build_overviews([2], Resampling.nearest)
    with pytest.raises(TiffStructureError, match="extra image directories"):
        parse_sealed_binary_mask_tiff_structure(source, _envelope())


@pytest.mark.parametrize("limit", ["max_tiff_entries", "max_pixels", "max_blocks"])
def test_mask_uses_the_same_structural_resource_caps_before_native_open(
    tmp_path: Path, limit: str
) -> None:
    source = _mask(tmp_path / "strips.tif", stripes=True)
    envelope = _envelope().model_copy(update={limit: 1, "resource_envelope_digest": None}).sealed()
    with pytest.raises(TiffResourceLimitError):
        parse_sealed_binary_mask_tiff_structure(source, envelope)
