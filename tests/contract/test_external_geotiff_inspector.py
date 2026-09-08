"""Synthetic-only conformance tests for the lead-adopted GeoTIFF v1 grammar."""

from __future__ import annotations

import importlib.util
import struct
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    ResourceEnvelopeV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller.external_tiff_structure import TiffDirectoryV1, TiffEntryV1
from pyproj import CRS
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin

_EXPECTED_PROFILE = {
    "contractVersion": "external-geotiff-profile.v1",
    "canonicalization": "ksi-domain-canonical-json-bytes.v1",
    "artifactKinds": ["ORTHO", "DSM"],
    "tiff": {
        "containers": ["CLASSIC_TIFF", "BIGTIFF"],
        "byteOrders": ["II", "MM"],
        "fullResolutionImages": 1,
        "externalSidecars": False,
    },
    "raster": {
        "imageCompression": ["NONE", "LZW", "DEFLATE", "ZSTD", "JPEG"],
        "integerPredictors": [1, 2],
        "floatPredictors": [1, 3],
        "interleave": "PIXEL",
    },
    "ortho": {
        "models": ["UINT8_RGB3", "UINT8_RGBA4_BINARY_ALPHA"],
        "nodata": "FORBIDDEN",
        "internalMask": "OPTIONAL_1BIT",
    },
    "dsm": {
        "models": ["FLOAT32_1", "FLOAT64_1"],
        "scale": 1,
        "offset": 0,
        "nodata": ["NONE", "FINITE", "NAN", "MASK"],
    },
    "scan": {
        "base": "REQUIRED",
        "mask": "WHEN_PRESENT",
        "overviews": "ALL",
        "unmaskedSamples": "FINITE",
    },
    "georeference": {
        "horizontal": ["EPSG_2D_GEOGRAPHIC", "EPSG_2D_PROJECTED"],
        "dsmHorizontal": "EPSG_2D_PROJECTED_METRE",
        "vertical": "OPTIONAL_COMPOUND_EPSG_1D_METRE",
    },
    "cog": {
        "layout": "IFDS_BEFORE_DATA",
        "blockLeader": "SIZE_AS_UINT4",
        "blockTrailer": "LAST_4_BYTES_REPEATED",
        "maskedBlockOrder": "MASK_INTERLEAVED_WITH_IMAGERY",
    },
    "sanitizer": {
        "fullResolutionResampling": "NONE",
        "outputBands": "RGB3",
        "outputMask": "BINARY_INTERNAL_MASK",
    },
}


def test_positive_profile_module_is_present_for_a_closed_grammar() -> None:
    """Removing the profile would let an implementation invent runtime defaults."""
    assert (
        importlib.util.find_spec("ksi_processing_controller.external_geotiff_profile") is not None
    )


def test_profile_bytes_and_digest_bind_the_exact_closed_v1_body() -> None:
    """Changing a profile member or positional rule must change admission identity."""
    from ksi_processing_controller.external_geotiff_profile import (
        external_geotiff_profile_body_v1,
        external_geotiff_profile_canonical_bytes_v1,
        external_geotiff_profile_digest_v1,
    )

    expected = canonical_json_bytes(_EXPECTED_PROFILE)
    assert external_geotiff_profile_body_v1() == _EXPECTED_PROFILE
    assert external_geotiff_profile_canonical_bytes_v1() == expected
    assert external_geotiff_profile_digest_v1() == "sha256:" + sha256(expected).hexdigest()


def test_host_worker_core_and_launcher_cannot_import_the_synthetic_decoder() -> None:
    """Only the future container entrypoint may make the decoder production-reachable."""
    root = Path(__file__).parents[2]
    host_paths = (
        root / "services/processing-controller/src/ksi_processing_controller/"
        "external_artifact_inspection_worker.py",
        root / "services/processing-controller/src/ksi_processing_controller/"
        "external_inspector_launcher.py",
        root / "services/core/src/ksi_core/external_artifact_inspections.py",
    )
    for host_path in host_paths:
        source = host_path.read_text(encoding="utf-8")
        assert "external_geotiff_inspector" not in source
        assert "import rasterio" not in source


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=1_000_000,
        max_streamed_bytes=1_000_000,
        max_tiff_directories=16,
        max_tiff_entries=512,
        max_pixels=1_000_000,
        max_bands=4,
        max_blocks=1_000,
        max_decompressed_bytes=10_000_000,
        max_sample_bytes=10_000_000,
        max_geometry_vertices=8,
        max_cpu_seconds=1.0,
        max_memory_bytes=10_000_000,
        max_workspace_bytes=10_000_000,
        max_output_bytes=1_000_000,
        max_tenant_concurrency=1,
        max_queue_depth=1,
        max_deadline_seconds=1.0,
        lease_duration_seconds=1.0,
        max_retry_attempts=1,
    ).sealed()


def test_synthetic_conformance_measures_a_supported_tiled_rgb_geotiff(tmp_path: Path) -> None:
    """A supported RGB byte stream must produce observed, finite measurement facts."""
    raster_path = tmp_path / "sealed.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(100.0, 200.0, 2.0, 2.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="DEFLATE",
        predictor=2,
        interleave="pixel",
    ) as dataset:
        dataset.write(np.full((3, 16, 16), 17, dtype=np.uint8))

    spec = importlib.util.find_spec("ksi_processing_controller.external_geotiff_inspector")
    assert spec is not None
    module = importlib.import_module("ksi_processing_controller.external_geotiff_inspector")
    inspect = module.inspect_synthetic_sealed_geotiff
    payload = raster_path.read_bytes()
    outcome = inspect(
        raster_path,
        artifact_id="ortho",
        observed_sha256="sha256:" + sha256(payload).hexdigest(),
        artifact_kind=ProcessingArtifactKind.ORTHO,
        envelope=_envelope(),
    )

    assert outcome.outcome is ArtifactOutcome.MEASURED
    assert outcome.measurements is not None
    assert outcome.measurements.observed_crs_identifier == "EPSG:3857"
    assert outcome.measurements.observed_crs_wkt == CRS.from_epsg(3857).to_wkt(
        version="WKT2_2019", pretty=False, output_axis_rule=True
    )
    assert outcome.measurements.transform == (2.0, 0.0, 100.0, 0.0, -2.0, 200.0)
    assert outcome.measurements.footprint_wkt == (
        "POLYGON ((100 200, 132 200, 132 168, 100 168, 100 200))"
    )
    assert outcome.measurements.valid_pixel_count == 256


def test_synthetic_conformance_classifies_a_masked_multilevel_cog(tmp_path: Path) -> None:
    """The physical base/mask/image-overview/mask-overview COG order is stricter than GeoTIFF."""
    source = tmp_path / "source.tif"
    cog = tmp_path / "sealed-cog.tif"
    with (
        rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True),
        rasterio.open(
            source,
            "w",
            driver="GTiff",
            width=256,
            height=256,
            count=3,
            dtype="uint8",
            crs="EPSG:3857",
            transform=from_origin(0.0, 256.0, 1.0, 1.0),
            tiled=True,
            blockxsize=16,
            blockysize=16,
            compress="DEFLATE",
            predictor=2,
            interleave="pixel",
        ) as dataset,
    ):
        dataset.write(np.full((3, 256, 256), 31, dtype=np.uint8))
        dataset.write_mask(np.where(np.indices((256, 256))[0] < 128, 255, 0).astype("uint8"))
    raster_copy(
        source,
        cog,
        driver="COG",
        BLOCKSIZE=16,
        COMPRESS="DEFLATE",
        PREDICTOR=2,
        OVERVIEWS="IGNORE_EXISTING",
        OVERVIEW_RESAMPLING="AVERAGE",
    )
    payload = cog.read_bytes()
    from ksi_processing_controller.external_geotiff_inspector import (
        inspect_synthetic_sealed_geotiff,
    )

    outcome = inspect_synthetic_sealed_geotiff(
        cog,
        artifact_id="ortho",
        observed_sha256="sha256:" + sha256(payload).hexdigest(),
        artifact_kind=ProcessingArtifactKind.ORTHO,
        envelope=_envelope(),
    )

    assert outcome.outcome is ArtifactOutcome.MEASURED
    assert outcome.measurements is not None
    assert outcome.measurements.layout == "COG_PROFILE_V1"
    assert outcome.measurements.valid_pixel_count == 32_768


def test_cog_trailer_mutation_downgrades_only_the_optional_cog_classification(
    tmp_path: Path,
) -> None:
    """A broken COG trailer leaves a structurally valid GeoTIFF measured but non-COG."""
    source = tmp_path / "source.tif"
    cog = tmp_path / "sealed-cog.tif"
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=256,
        height=256,
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(0.0, 256.0, 1.0, 1.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="DEFLATE",
        predictor=2,
        interleave="pixel",
    ) as dataset:
        dataset.write(np.full((3, 256, 256), 3, dtype=np.uint8))
    raster_copy(source, cog, driver="COG", BLOCKSIZE=16, COMPRESS="DEFLATE", PREDICTOR=2)
    from ksi_processing_controller.external_tiff_structure import parse_sealed_tiff_structure

    structure = parse_sealed_tiff_structure(cog, _envelope())
    first_offset = structure.directories[0].entries[324].integers("<")[0]
    first_size = structure.directories[0].entries[325].integers("<")[0]
    payload = bytearray(cog.read_bytes())
    payload[first_offset + first_size] ^= 0x01
    cog.write_bytes(payload)

    outcome = _inspect(cog, ProcessingArtifactKind.ORTHO)

    assert outcome.outcome is ArtifactOutcome.MEASURED
    assert outcome.measurements is not None
    assert outcome.measurements.layout == "GEOTIFF_TILED_V1"


def _inspect(path: Path, kind: ProcessingArtifactKind) -> ArtifactInspectionOutcomeV1:
    from ksi_processing_controller.external_geotiff_inspector import (
        inspect_synthetic_sealed_geotiff,
    )

    payload = path.read_bytes()
    return inspect_synthetic_sealed_geotiff(
        path,
        artifact_id="dsm" if kind is ProcessingArtifactKind.DSM else "ortho",
        observed_sha256="sha256:" + sha256(payload).hexdigest(),
        artifact_kind=kind,
        envelope=_envelope(),
    )


def _write_dsm(
    path: Path, values: np.ndarray, *, crs: str = "EPSG:3857", masked: bool = False
) -> None:
    with (
        rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True),
        rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=16,
            height=16,
            count=1,
            dtype="float32",
            crs=crs,
            transform=from_origin(0.0, 16.0, 1.0, 1.0),
            tiled=True,
            blockxsize=16,
            blockysize=16,
            compress="DEFLATE",
            predictor=3,
            interleave="pixel",
        ) as dataset,
    ):
        dataset.write(values[np.newaxis, ...])
        if masked:
            dataset.write_mask(np.where(np.indices((16, 16))[0] == 0, 0, 255).astype("uint8"))


def test_masked_nan_is_measured_with_nullable_vertical_reference(tmp_path: Path) -> None:
    """Masked non-finite DSM samples do not turn a structural observation into an accuracy claim."""
    raster_path = tmp_path / "masked-dsm.tif"
    values = np.ones((16, 16), dtype=np.float32)
    values[0, :] = np.nan
    _write_dsm(raster_path, values, masked=True)

    outcome = _inspect(raster_path, ProcessingArtifactKind.DSM)

    assert outcome.outcome is ArtifactOutcome.MEASURED
    assert outcome.measurements is not None
    assert outcome.measurements.nodata_representation.value == "MASK"
    assert outcome.measurements.valid_pixel_count == 240
    assert outcome.measurements.observed_vertical_reference is None


def test_compound_dsm_crs_records_the_observed_metred_vertical_component(tmp_path: Path) -> None:
    """A resolvable one-dimensional EPSG vertical component is an observation, never accuracy."""
    raster_path = tmp_path / "compound-dsm.tif"
    _write_dsm(raster_path, np.ones((16, 16), dtype=np.float32), crs="EPSG:7415")

    outcome = _inspect(raster_path, ProcessingArtifactKind.DSM)

    assert outcome.outcome is ArtifactOutcome.MEASURED
    assert outcome.measurements is not None
    assert outcome.measurements.observed_crs_identifier == "EPSG:28992"
    assert outcome.measurements.observed_vertical_reference is not None
    assert outcome.measurements.observed_vertical_reference.identifier == "EPSG:5709"
    assert outcome.measurements.observed_vertical_reference.basis == "NAP height"


def test_unmasked_nan_is_rejected(tmp_path: Path) -> None:
    """An unmasked non-finite DSM sample cannot be reported as a partial positive measurement."""
    raster_path = tmp_path / "unmasked-dsm.tif"
    values = np.ones((16, 16), dtype=np.float32)
    values[3, 3] = np.nan
    _write_dsm(raster_path, values)

    outcome = _inspect(raster_path, ProcessingArtifactKind.DSM)

    assert outcome.outcome is ArtifactOutcome.REJECTED
    assert outcome.reason == "UNMASKED_NONFINITE_SAMPLE"


def test_unmasked_nonfinite_overview_sample_is_rejected_after_full_ifd_scan(tmp_path: Path) -> None:
    """Overview payloads are scanned as data, not merely counted as an IFD chain."""
    raster_path = tmp_path / "overview-dsm.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=64,
        height=64,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(0.0, 64.0, 1.0, 1.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="NONE",
        predictor=1,
        interleave="pixel",
    ) as dataset:
        dataset.write(np.ones((1, 64, 64), dtype=np.float32))
        dataset.build_overviews([2], rasterio.enums.Resampling.nearest)
    from ksi_processing_controller.external_tiff_structure import parse_sealed_tiff_structure

    structure = parse_sealed_tiff_structure(raster_path, _envelope())
    overview = structure.directories[1]
    overview_offset = overview.entries[324].integers("<")[0]
    payload = bytearray(raster_path.read_bytes())
    payload[overview_offset : overview_offset + 4] = np.float32(np.nan).tobytes()
    raster_path.write_bytes(payload)

    outcome = _inspect(raster_path, ProcessingArtifactKind.DSM)

    assert outcome.outcome is ArtifactOutcome.REJECTED
    assert outcome.reason == "UNMASKED_NONFINITE_SAMPLE"


def test_geographic_dsm_is_rejected_even_when_the_bytes_decode(tmp_path: Path) -> None:
    """DSM requires projected metre axes; decoded geographic data cannot widen the profile."""
    raster_path = tmp_path / "geographic-dsm.tif"
    _write_dsm(raster_path, np.ones((16, 16), dtype=np.float32), crs="EPSG:4326")

    outcome = _inspect(raster_path, ProcessingArtifactKind.DSM)

    assert outcome.outcome is ArtifactOutcome.REJECTED
    assert outcome.reason == "AMBIGUOUS_GEOREFERENCE"


def test_singular_affine_is_rejected_before_measurement(tmp_path: Path) -> None:
    """A finite but non-invertible affine cannot supply a deterministic footprint."""
    raster_path = tmp_path / "singular-dsm.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=rasterio.Affine(1.0, 1.0, 0.0, 1.0, 1.0, 0.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="DEFLATE",
        predictor=3,
        interleave="pixel",
    ) as dataset:
        dataset.write(np.ones((1, 16, 16), dtype=np.float32))

    outcome = _inspect(raster_path, ProcessingArtifactKind.DSM)

    assert outcome.outcome is ArtifactOutcome.REJECTED
    assert outcome.reason == "AMBIGUOUS_GEOREFERENCE"


def test_malformed_ifd_offset_and_external_sidecar_are_rejected(tmp_path: Path) -> None:
    """The preflight must reject corrupt offsets and never consult a sibling overview."""
    raster_path = tmp_path / "sealed.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(0.0, 16.0, 1.0, 1.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="DEFLATE",
        predictor=2,
        interleave="pixel",
    ) as dataset:
        dataset.write(np.ones((3, 16, 16), dtype=np.uint8))
    malformed = tmp_path / "malformed.tif"
    payload = bytearray(raster_path.read_bytes())
    payload[4:8] = (len(payload) + 1).to_bytes(4, "little")
    malformed.write_bytes(payload)

    malformed_outcome = _inspect(malformed, ProcessingArtifactKind.ORTHO)
    assert malformed_outcome.outcome is ArtifactOutcome.REJECTED
    assert malformed_outcome.reason == "MALFORMED_TIFF"

    (tmp_path / "sealed.tif.ovr").write_bytes(b"not a trusted internal overview")
    sidecar_outcome = _inspect(raster_path, ProcessingArtifactKind.ORTHO)
    assert sidecar_outcome.outcome is ArtifactOutcome.REJECTED
    assert sidecar_outcome.reason == "UNSAFE_EXTERNAL_REFERENCE"


def test_vrt_or_vsi_named_input_is_rejected_without_decoder_reachability(tmp_path: Path) -> None:
    """The parser core accepts only a sealed TIFF pathname, never a VRT or VSI namespace."""
    raster_path = tmp_path / "sealed.tif"
    _write_dsm(raster_path, np.ones((16, 16), dtype=np.float32), masked=True)
    vrt_named = tmp_path / "sealed.vrt"
    vrt_named.write_bytes(raster_path.read_bytes())

    outcome = _inspect(vrt_named, ProcessingArtifactKind.DSM)

    assert outcome.outcome is ArtifactOutcome.REJECTED
    assert outcome.reason == "UNSAFE_EXTERNAL_REFERENCE"


def test_preflight_resource_cap_rejects_before_decoder_measurement(tmp_path: Path) -> None:
    """The structural block count cap is enforced before Rasterio can expand a tile."""
    raster_path = tmp_path / "sealed.tif"
    _write_dsm(raster_path, np.ones((16, 16), dtype=np.float32), masked=True)
    from ksi_processing_controller.external_geotiff_inspector import (
        inspect_synthetic_sealed_geotiff,
    )

    payload = raster_path.read_bytes()
    outcome = inspect_synthetic_sealed_geotiff(
        raster_path,
        artifact_id="dsm",
        observed_sha256="sha256:" + sha256(payload).hexdigest(),
        artifact_kind=ProcessingArtifactKind.DSM,
        envelope=ResourceEnvelopeV1(
            **{
                **_envelope().model_dump(exclude={"resource_envelope_digest"}),
                "max_blocks": 1,
            }
        ).sealed(),
    )

    assert outcome.outcome is ArtifactOutcome.REJECTED
    assert outcome.reason == "RESOURCE_LIMIT_EXCEEDED"


def test_cancellation_raises_without_returning_a_partial_measurement(tmp_path: Path) -> None:
    """Cancellation is terminal and cannot be presented as a measured GeoTIFF outcome."""
    raster_path = tmp_path / "sealed.tif"
    _write_dsm(raster_path, np.ones((16, 16), dtype=np.float32))
    from ksi_processing_controller.external_geotiff_inspector import (
        SyntheticGeoTiffInspectionIncomplete,
        inspect_synthetic_sealed_geotiff,
    )

    with pytest.raises(SyntheticGeoTiffInspectionIncomplete):
        inspect_synthetic_sealed_geotiff(
            raster_path,
            artifact_id="dsm",
            observed_sha256="sha256:" + sha256(raster_path.read_bytes()).hexdigest(),
            artifact_kind=ProcessingArtifactKind.DSM,
            envelope=_envelope(),
            is_cancelled=lambda: True,
        )


@pytest.mark.parametrize("creation_options", [{"BIGTIFF": "YES"}, {"ENDIANNESS": "BIG"}])
def test_classic_bigtiff_and_both_byte_orders_use_the_same_profile(
    tmp_path: Path, creation_options: dict[str, str]
) -> None:
    """Container width and byte order cannot select a more permissive decode path."""
    raster_path = tmp_path / ("-".join(creation_options).lower() + ".tif")
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(0.0, 16.0, 1.0, 1.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="DEFLATE",
        predictor=2,
        interleave="pixel",
        **creation_options,
    ) as dataset:
        dataset.write(np.full((3, 16, 16), 11, dtype=np.uint8))

    outcome = _inspect(raster_path, ProcessingArtifactKind.ORTHO)

    assert outcome.outcome is ArtifactOutcome.MEASURED


def test_rgba_requires_exact_color_interpretation_and_counts_binary_alpha(tmp_path: Path) -> None:
    """A normal RGBA image is accepted, while a fourth undefined band is not alpha."""
    rgba = tmp_path / "rgba.tif"
    with rasterio.open(
        rgba,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=4,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(0.0, 16.0, 1.0, 1.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="DEFLATE",
        predictor=2,
        interleave="pixel",
        photometric="RGB",
        ALPHA="YES",
    ) as dataset:
        values = np.full((4, 16, 16), 15, dtype=np.uint8)
        values[3, :8] = 0
        values[3, 8:] = 255
        dataset.write(values)
        dataset.colorinterp = (
            rasterio.enums.ColorInterp.red,
            rasterio.enums.ColorInterp.green,
            rasterio.enums.ColorInterp.blue,
            rasterio.enums.ColorInterp.alpha,
        )

    accepted = _inspect(rgba, ProcessingArtifactKind.ORTHO)

    assert accepted.outcome is ArtifactOutcome.MEASURED
    assert accepted.measurements is not None
    assert accepted.measurements.valid_pixel_count == 128
    assert accepted.measurements.nodata_representation.value == "MASK"

    undefined = tmp_path / "undefined-four-band.tif"
    with rasterio.open(
        undefined,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=4,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(0.0, 16.0, 1.0, 1.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="DEFLATE",
        predictor=2,
        interleave="pixel",
    ) as dataset:
        dataset.write(np.full((4, 16, 16), 15, dtype=np.uint8))

    rejected = _inspect(undefined, ProcessingArtifactKind.ORTHO)

    assert rejected.outcome is ArtifactOutcome.REJECTED
    assert rejected.reason == "UNSUPPORTED_RASTER"


def test_rgba_alpha_is_binary_in_every_overview_not_only_the_base(tmp_path: Path) -> None:
    """A non-binary alpha sample hidden in an overview invalidates the entire ORTHO."""
    raster_path = tmp_path / "rgba-overview.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=64,
        height=64,
        count=4,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(0.0, 64.0, 1.0, 1.0),
        compress="NONE",
        predictor=1,
        interleave="pixel",
        photometric="RGB",
        ALPHA="YES",
    ) as dataset:
        values = np.full((4, 64, 64), 17, dtype=np.uint8)
        values[3] = 255
        dataset.write(values)
        dataset.build_overviews([2], rasterio.enums.Resampling.nearest)
    from ksi_processing_controller.external_tiff_structure import parse_sealed_tiff_structure

    structure = parse_sealed_tiff_structure(raster_path, _envelope())
    overview_offset_entry = (
        structure.directories[1].entries.get(324) or structure.directories[1].entries[273]
    )
    overview_offset = overview_offset_entry.integers("<")[0]
    payload = bytearray(raster_path.read_bytes())
    payload[overview_offset + 3] = 128
    raster_path.write_bytes(payload)

    outcome = _inspect(raster_path, ProcessingArtifactKind.ORTHO)

    assert outcome.outcome is ArtifactOutcome.REJECTED
    assert outcome.reason == "UNSUPPORTED_RASTER"


def test_three_dimensional_horizontal_epsg_is_rejected(tmp_path: Path) -> None:
    """EPSG:4979 has three horizontal axes and cannot masquerade as a 2D ORTHO CRS."""
    raster_path = tmp_path / "ortho-4979.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=3,
        dtype="uint8",
        crs="EPSG:4979",
        transform=from_origin(0.0, 16.0, 1.0, 1.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="DEFLATE",
        predictor=2,
        interleave="pixel",
    ) as dataset:
        dataset.write(np.ones((3, 16, 16), dtype=np.uint8))

    outcome = _inspect(raster_path, ProcessingArtifactKind.ORTHO)

    assert outcome.outcome is ArtifactOutcome.REJECTED
    assert outcome.reason == "AMBIGUOUS_GEOREFERENCE"


def test_geometry_vertex_cap_rejects_the_fixed_five_point_footprint(tmp_path: Path) -> None:
    """A cap below the canonical closed ring cannot publish an abbreviated geometry."""
    raster_path = tmp_path / "sealed.tif"
    _write_dsm(raster_path, np.ones((16, 16), dtype=np.float32))
    tight = ResourceEnvelopeV1(
        **{
            **_envelope().model_dump(exclude={"resource_envelope_digest"}),
            "max_geometry_vertices": 4,
        }
    ).sealed()
    from ksi_processing_controller.external_geotiff_inspector import (
        inspect_synthetic_sealed_geotiff,
    )

    outcome = inspect_synthetic_sealed_geotiff(
        raster_path,
        artifact_id="dsm",
        observed_sha256="sha256:" + sha256(raster_path.read_bytes()).hexdigest(),
        artifact_kind=ProcessingArtifactKind.DSM,
        envelope=tight,
    )

    assert outcome.outcome is ArtifactOutcome.REJECTED
    assert outcome.reason == "RESOURCE_LIMIT_EXCEEDED"


def test_global_tiff_entry_cap_and_cross_ifd_block_overlap_reject_before_decode(
    tmp_path: Path,
) -> None:
    """Per-IFD limits cannot hide an aggregate entry or image/overview allocation attack."""
    raster_path = tmp_path / "overview.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=64,
        height=64,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(0.0, 64.0, 1.0, 1.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="DEFLATE",
        predictor=3,
        interleave="pixel",
    ) as dataset:
        dataset.write(np.ones((1, 64, 64), dtype=np.float32))
        dataset.build_overviews([2], rasterio.enums.Resampling.nearest)
    from ksi_processing_controller.external_tiff_structure import parse_sealed_tiff_structure

    structure = parse_sealed_tiff_structure(raster_path, _envelope())
    assert len(structure.directories) == 2
    aggregate_limited = ResourceEnvelopeV1(
        **{
            **_envelope().model_dump(exclude={"resource_envelope_digest"}),
            "max_tiff_entries": max(len(directory.entries) for directory in structure.directories),
        }
    ).sealed()
    from ksi_processing_controller.external_geotiff_inspector import (
        inspect_synthetic_sealed_geotiff,
    )

    aggregate_outcome = inspect_synthetic_sealed_geotiff(
        raster_path,
        artifact_id="dsm",
        observed_sha256="sha256:" + sha256(raster_path.read_bytes()).hexdigest(),
        artifact_kind=ProcessingArtifactKind.DSM,
        envelope=aggregate_limited,
    )
    assert aggregate_outcome.reason == "RESOURCE_LIMIT_EXCEEDED"

    payload = bytearray(raster_path.read_bytes())
    base_first_offset = structure.directories[0].entries[324].integers("<")[0]
    overview_offsets_location = _classic_external_tag_value_location(
        payload, structure.directories[1].offset, 324
    )
    payload[overview_offsets_location : overview_offsets_location + 4] = struct.pack(
        "<I", base_first_offset
    )
    raster_path.write_bytes(payload)

    overlap_outcome = _inspect(raster_path, ProcessingArtifactKind.DSM)
    assert overlap_outcome.outcome is ArtifactOutcome.REJECTED
    assert overlap_outcome.reason == "MALFORMED_TIFF"


def test_late_out_of_line_metadata_downgrades_cog_without_accepting_interleaved_index_data(
    tmp_path: Path,
) -> None:
    """A valid TIFF whose metadata index moves after its first payload cannot stay COG."""
    source = tmp_path / "source.tif"
    cog = tmp_path / "cog.tif"
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=256,
        height=256,
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(0.0, 256.0, 1.0, 1.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="DEFLATE",
        predictor=2,
        interleave="pixel",
    ) as dataset:
        dataset.write(np.full((3, 256, 256), 9, dtype=np.uint8))
    raster_copy(source, cog, driver="COG", BLOCKSIZE=16, COMPRESS="DEFLATE", PREDICTOR=2)
    from ksi_processing_controller.external_tiff_structure import parse_sealed_tiff_structure

    original_cog = bytearray(cog.read_bytes())
    structure = parse_sealed_tiff_structure(cog, _envelope())
    metadata = structure.directories[0].entries[42112]
    assert metadata.field_type == 2
    metadata_location = _classic_external_tag_value_location(
        bytearray(cog.read_bytes()), structure.directories[0].offset, 42112
    )
    payload = bytearray(cog.read_bytes())
    moved_offset = len(payload)
    payload.extend(payload[metadata_location : metadata_location + metadata.count])
    _set_classic_tag_value_offset(payload, structure.directories[0].offset, 42112, moved_offset)
    cog.write_bytes(payload)

    outcome = _inspect(cog, ProcessingArtifactKind.ORTHO)

    assert outcome.outcome is ArtifactOutcome.MEASURED
    assert outcome.measurements is not None
    assert outcome.measurements.layout == "GEOTIFF_TILED_V1"

    # Point two independently declared metadata values at the same external
    # storage.  The raw bytes are harmless ASCII, so rejection proves the
    # global allocation ledger rather than text decoding alone.
    metadata_overlap = tmp_path / "metadata-overlap.tif"
    metadata_offset = _classic_external_tag_value_location(
        original_cog, structure.directories[0].offset, 42112
    )
    geotiff_ascii_offset = _classic_external_tag_value_location(
        original_cog, structure.directories[0].offset, 34737
    )
    _set_classic_tag_value_offset(
        original_cog, structure.directories[0].offset, 42112, geotiff_ascii_offset
    )
    metadata_overlap.write_bytes(original_cog)

    overlap = _inspect(metadata_overlap, ProcessingArtifactKind.ORTHO)
    assert metadata_offset != geotiff_ascii_offset
    assert overlap.outcome is ArtifactOutcome.REJECTED
    assert overlap.reason == "MALFORMED_TIFF"


@pytest.mark.parametrize(
    ("kind", "count", "dtype", "compression", "predictor", "photometric"),
    [
        (ProcessingArtifactKind.ORTHO, 3, "uint8", "NONE", 1, "RGB"),
        (ProcessingArtifactKind.ORTHO, 3, "uint8", "LZW", 1, "RGB"),
        (ProcessingArtifactKind.ORTHO, 3, "uint8", "LZW", 2, "RGB"),
        (ProcessingArtifactKind.ORTHO, 3, "uint8", "DEFLATE", 1, "RGB"),
        (ProcessingArtifactKind.ORTHO, 3, "uint8", "DEFLATE", 2, "RGB"),
        (ProcessingArtifactKind.ORTHO, 3, "uint8", "ZSTD", 1, "RGB"),
        (ProcessingArtifactKind.ORTHO, 3, "uint8", "ZSTD", 2, "RGB"),
        (ProcessingArtifactKind.ORTHO, 3, "uint8", "JPEG", 1, "YCBCR"),
        (ProcessingArtifactKind.DSM, 1, "float32", "NONE", 1, None),
        (ProcessingArtifactKind.DSM, 1, "float32", "LZW", 1, None),
        (ProcessingArtifactKind.DSM, 1, "float32", "LZW", 3, None),
        (ProcessingArtifactKind.DSM, 1, "float32", "DEFLATE", 1, None),
        (ProcessingArtifactKind.DSM, 1, "float32", "DEFLATE", 3, None),
        (ProcessingArtifactKind.DSM, 1, "float32", "ZSTD", 1, None),
        (ProcessingArtifactKind.DSM, 1, "float32", "ZSTD", 3, None),
    ],
)
def test_closed_codec_predictor_matrix_accepts_only_the_supported_on_disk_models(
    tmp_path: Path,
    kind: ProcessingArtifactKind,
    count: int,
    dtype: str,
    compression: str,
    predictor: int,
    photometric: str | None,
) -> None:
    """Each permitted codec/predictor is read from TIFF tags, including a stripped JPEG YCbCr."""
    raster_path = tmp_path / f"{kind.value}-{compression}-{predictor}.tif"
    options: dict[str, object] = {
        "driver": "GTiff",
        "width": 16,
        "height": 16,
        "count": count,
        "dtype": dtype,
        "crs": "EPSG:3857",
        "transform": from_origin(0.0, 16.0, 1.0, 1.0),
        # Deliberately omitted tiling: striped data is part of the accepted base grammar.
        "compress": compression,
        "predictor": predictor,
        "interleave": "pixel",
    }
    if photometric is not None:
        options["photometric"] = photometric
    with rasterio.open(raster_path, "w", **options) as dataset:
        dataset.write(np.ones((count, 16, 16), dtype=dtype))

    outcome = _inspect(raster_path, kind)

    assert outcome.outcome is ArtifactOutcome.MEASURED


def test_rejects_jpeg_rgb_and_mutated_unsupported_predictor_before_decode(tmp_path: Path) -> None:
    """JPEG needs YCbCr on disk, and an integer predictor cannot use the float-only code 3."""
    jpeg_rgb = tmp_path / "jpeg-rgb.tif"
    with rasterio.open(
        jpeg_rgb,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(0.0, 16.0, 1.0, 1.0),
        compress="JPEG",
        predictor=1,
        photometric="RGB",
        interleave="pixel",
    ) as dataset:
        dataset.write(np.ones((3, 16, 16), dtype=np.uint8))
    assert _inspect(jpeg_rgb, ProcessingArtifactKind.ORTHO).reason == "UNSUPPORTED_RASTER"

    rgb = tmp_path / "bad-predictor.tif"
    with rasterio.open(
        rgb,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(0.0, 16.0, 1.0, 1.0),
        compress="DEFLATE",
        predictor=2,
        interleave="pixel",
    ) as dataset:
        dataset.write(np.ones((3, 16, 16), dtype=np.uint8))
    from ksi_processing_controller.external_tiff_structure import parse_sealed_tiff_structure

    structure = parse_sealed_tiff_structure(rgb, _envelope())
    payload = bytearray(rgb.read_bytes())
    predictor_location = _classic_external_tag_value_location(
        payload, structure.directories[0].offset, 317
    )
    payload[predictor_location : predictor_location + 2] = struct.pack("<H", 3)
    rgb.write_bytes(payload)

    bad_predictor = _inspect(rgb, ProcessingArtifactKind.ORTHO)
    assert bad_predictor.outcome is ArtifactOutcome.REJECTED
    assert bad_predictor.reason == "UNSUPPORTED_RASTER"


@pytest.mark.parametrize(("nodata", "expected"), [(-999.0, "FINITE"), (float("nan"), "NAN")])
def test_dsm_finite_and_nan_nodata_models_are_measured(
    tmp_path: Path, nodata: float, expected: str
) -> None:
    """The report preserves the one allowed DSM nodata representation without combining a mask."""
    raster_path = tmp_path / f"nodata-{expected}.tif"
    values = np.ones((1, 16, 16), dtype=np.float32)
    values[0, 0, 0] = nodata
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(0.0, 16.0, 1.0, 1.0),
        compress="DEFLATE",
        predictor=3,
        nodata=nodata,
    ) as dataset:
        dataset.write(values)

    outcome = _inspect(raster_path, ProcessingArtifactKind.DSM)

    assert outcome.outcome is ArtifactOutcome.MEASURED
    assert outcome.measurements is not None
    assert outcome.measurements.nodata_representation.value == expected
    assert outcome.measurements.valid_pixel_count == 255


def _classic_external_tag_value_location(
    payload: bytearray, directory_offset: int, tag: int
) -> int:
    entry_count = struct.unpack_from("<H", payload, directory_offset)[0]
    for index in range(entry_count):
        entry_offset = directory_offset + 2 + 12 * index
        found_tag, field_type, count, value_offset = struct.unpack_from(
            "<HHII", payload, entry_offset
        )
        if found_tag == tag:
            byte_count = count * {
                1: 1,
                2: 1,
                3: 2,
                4: 4,
                5: 8,
                6: 1,
                7: 1,
                8: 2,
                9: 4,
                10: 8,
                11: 4,
                12: 8,
            }[field_type]
            return value_offset if byte_count > 4 else entry_offset + 8
    raise AssertionError(f"classic TIFF tag {tag} is absent")


def _set_classic_tag_value_offset(
    payload: bytearray, directory_offset: int, tag: int, value_offset: int
) -> None:
    entry_count = struct.unpack_from("<H", payload, directory_offset)[0]
    for index in range(entry_count):
        entry_offset = directory_offset + 2 + 12 * index
        if struct.unpack_from("<H", payload, entry_offset)[0] == tag:
            struct.pack_into("<I", payload, entry_offset + 8, value_offset)
            return
    raise AssertionError(f"classic TIFF tag {tag} is absent")


def test_cog_overview_dimensions_must_equal_the_selected_integer_factor_ceiling() -> None:
    """The observed size cannot be reverse-rounded into a seemingly valid COG factor."""
    from ksi_processing_controller.external_geotiff_inspector import _has_cog_logical_chain

    base = _directory_with_dimensions(100, 100)
    dataset = SimpleNamespace(width=100, height=100)
    for factor in range(2, 11):
        expected = (100 + factor - 1) // factor
        for candidate in (expected - 1, expected, expected + 1):
            assert _has_cog_logical_chain(
                dataset,
                [base, _directory_with_dimensions(candidate, candidate)],
                (factor,),
                "<",
                100,
            ) is (candidate == expected)


@pytest.mark.parametrize("same_values", [True, False])
def test_raw_dual_affine_models_reject_before_rasterio_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, same_values: bool
) -> None:
    """Rasterio precedence cannot resolve simultaneous transformation and scale/tiepoint tags."""
    raster_path = _write_raw_validation_rgb(tmp_path / f"dual-{same_values}.tif")
    _append_classic_model_transformation(
        raster_path,
        _matching_model_transformation() if same_values else _conflicting_model_transformation(),
    )

    outcome = _inspect_without_decoder(monkeypatch, raster_path, ProcessingArtifactKind.ORTHO)

    assert outcome.outcome is ArtifactOutcome.REJECTED
    assert outcome.reason == "MALFORMED_TIFF"


def test_raw_bits_per_sample_cardinality_rejects_before_rasterio_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A one-value RGB BitsPerSample tag cannot undercount three uint8 samples."""
    raster_path = _write_raw_validation_rgb(tmp_path / "bits-one-rgb.tif")
    payload = bytearray(raster_path.read_bytes())
    directory_offset = struct.unpack_from("<I", payload, 4)[0]
    bits_entry = _classic_entry_offset(payload, directory_offset, 258)
    struct.pack_into("<I", payload, bits_entry + 4, 1)
    raster_path.write_bytes(payload)

    outcome = _inspect_without_decoder(monkeypatch, raster_path, ProcessingArtifactKind.ORTHO)

    assert outcome.outcome is ArtifactOutcome.REJECTED
    assert outcome.reason == "MALFORMED_TIFF"


@pytest.mark.parametrize(
    "mutation", ["extra_strip", "missing_strip", "rows_per_strip", "missing_tile"]
)
def test_raw_block_count_must_match_geometry_before_rasterio_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    """Offsets/counts must match strips or partial-edge tiles before GDAL sees malformed data."""
    if mutation == "missing_tile":
        raster_path = _write_raw_validation_rgb(
            tmp_path / "partial-tiles.tif", width=17, height=17, tiled=True
        )
        from ksi_processing_controller.external_tiff_structure import parse_sealed_tiff_structure

        assert parse_sealed_tiff_structure(raster_path, _envelope()).allocated_block_count == 4
        payload = bytearray(raster_path.read_bytes())
        directory_offset = struct.unpack_from("<I", payload, 4)[0]
        tile_offset_entry = _classic_entry_offset(payload, directory_offset, 324)
        tile_count_entry = _classic_entry_offset(payload, directory_offset, 325)
        # A 17x17 raster with 16x16 tiles has four physical edge-inclusive tiles.
        struct.pack_into("<I", payload, tile_offset_entry + 4, 3)
        struct.pack_into("<I", payload, tile_count_entry + 4, 3)
    else:
        raster_path = _write_raw_validation_rgb(
            tmp_path / f"{mutation}.tif",
            height=32 if mutation == "missing_strip" else 16,
        )
        payload = bytearray(raster_path.read_bytes())
        directory_offset = struct.unpack_from("<I", payload, 4)[0]
        if mutation == "extra_strip":
            extra_block_offset = len(payload)
            payload.extend(b"extra")
            _append_classic_long_block_value(
                payload,
                directory_offset,
                273,
                _classic_tag_values(payload, directory_offset, 273) + (extra_block_offset,),
            )
            _append_classic_long_block_value(
                payload,
                directory_offset,
                279,
                _classic_tag_values(payload, directory_offset, 279) + (5,),
            )
        elif mutation == "missing_strip":
            rows_entry = _classic_entry_offset(payload, directory_offset, 278)
            struct.pack_into("<I", payload, rows_entry + 8, 16)
        else:
            rows_entry = _classic_entry_offset(payload, directory_offset, 278)
            struct.pack_into("<I", payload, rows_entry + 8, 8)
    raster_path.write_bytes(payload)

    outcome = _inspect_without_decoder(monkeypatch, raster_path, ProcessingArtifactKind.ORTHO)

    assert outcome.outcome is ArtifactOutcome.REJECTED
    assert outcome.reason == "MALFORMED_TIFF"


def _directory_with_dimensions(width: int, height: int) -> TiffDirectoryV1:
    return TiffDirectoryV1(
        offset=0,
        entries={
            256: TiffEntryV1(256, 3, 1, struct.pack("<H", width)),
            257: TiffEntryV1(257, 3, 1, struct.pack("<H", height)),
        },
        next_offset=0,
        storage_ranges=(),
    )


def _write_raw_validation_rgb(
    path: Path,
    *,
    width: int = 16,
    height: int = 16,
    tiled: bool = False,
) -> Path:
    options: dict[str, object] = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": 3,
        "dtype": "uint8",
        "crs": "EPSG:3857",
        "transform": from_origin(0.0, float(height), 1.0, 1.0),
        "compress": "NONE",
        "interleave": "pixel",
    }
    if tiled:
        options.update(tiled=True, blockxsize=16, blockysize=16)
    with rasterio.open(path, "w", **options) as dataset:
        dataset.write(np.ones((3, height, width), dtype=np.uint8))
    return path


def _inspect_without_decoder(
    monkeypatch: pytest.MonkeyPatch, path: Path, kind: ProcessingArtifactKind
) -> ArtifactInspectionOutcomeV1:
    module = importlib.import_module("ksi_processing_controller.external_geotiff_inspector")
    opened = False

    def forbidden_decoder(*args: object, **kwargs: object) -> object:
        nonlocal opened
        del args, kwargs
        opened = True
        raise AssertionError("raw-invalid TIFF reached Rasterio")

    monkeypatch.setattr(module.rasterio, "open", forbidden_decoder)
    outcome = module.inspect_synthetic_sealed_geotiff(
        path,
        artifact_id="ortho",
        observed_sha256="sha256:" + sha256(path.read_bytes()).hexdigest(),
        artifact_kind=kind,
        envelope=_envelope(),
    )
    assert opened is False
    return outcome


def _append_classic_model_transformation(path: Path, matrix: tuple[float, ...]) -> None:
    assert len(matrix) == 16
    payload = bytearray(path.read_bytes())
    directory_offset = struct.unpack_from("<I", payload, 4)[0]
    entry_count = struct.unpack_from("<H", payload, directory_offset)[0]
    entries_start = directory_offset + 2
    next_offset = struct.unpack_from("<I", payload, entries_start + entry_count * 12)[0]
    appended_offset = len(payload)
    if appended_offset % 2:
        payload.append(0)
        appended_offset += 1
    value_offset = appended_offset + 2 + (entry_count + 1) * 12 + 4
    payload.extend(struct.pack("<H", entry_count + 1))
    payload.extend(payload[entries_start : entries_start + entry_count * 12])
    payload.extend(struct.pack("<HHII", 34264, 12, 16, value_offset))
    payload.extend(struct.pack("<I", next_offset))
    payload.extend(struct.pack("<16d", *matrix))
    struct.pack_into("<I", payload, 4, appended_offset)
    path.write_bytes(payload)


def _matching_model_transformation() -> tuple[float, ...]:
    return (
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        -1.0,
        0.0,
        16.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def _conflicting_model_transformation() -> tuple[float, ...]:
    return (
        2.0,
        0.0,
        0.0,
        1.0,
        0.0,
        -2.0,
        0.0,
        15.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def _classic_entry_offset(payload: bytearray, directory_offset: int, tag: int) -> int:
    entry_count = struct.unpack_from("<H", payload, directory_offset)[0]
    for index in range(entry_count):
        entry_offset = directory_offset + 2 + 12 * index
        if struct.unpack_from("<H", payload, entry_offset)[0] == tag:
            return entry_offset
    raise AssertionError(f"classic TIFF tag {tag} is absent")


def _classic_tag_values(payload: bytearray, directory_offset: int, tag: int) -> tuple[int, ...]:
    entry_offset = _classic_entry_offset(payload, directory_offset, tag)
    found_tag, field_type, count, value_offset = struct.unpack_from(
        "<HHII", payload, entry_offset
    )
    assert found_tag == tag and field_type == 4
    if count == 1:
        return (value_offset,)
    return struct.unpack_from("<" + "I" * count, payload, value_offset)


def _append_classic_long_block_value(
    payload: bytearray, directory_offset: int, tag: int, values: tuple[int, ...]
) -> None:
    entry_offset = _classic_entry_offset(payload, directory_offset, tag)
    value_offset = len(payload)
    payload.extend(struct.pack("<" + "I" * len(values), *values))
    struct.pack_into("<I", payload, entry_offset + 4, len(values))
    struct.pack_into("<I", payload, entry_offset + 8, value_offset)
