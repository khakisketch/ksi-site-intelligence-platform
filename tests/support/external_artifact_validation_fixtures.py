"""Synthetic-only byte fixtures for external artifact validation contracts.

The values here are deliberately generated in memory.  They are not customer
exports, compatibility evidence, capacity evidence, or parser acceptance data.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass, field
from typing import Final

import numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import Affine

NOW: Final = "2026-09-07T00:00:00Z"
CHECKPOINT_BYTES: Final = (
    b"checkpoint_id,easting_m,northing_m,elevation_m\n"
    b"p1,0.5,1.5,10.0\n"
    b"p2,1.5,1.5,10.0\n"
    b"p3,0.5,0.5,10.0\n"
)
ORTHO_BYTES: Final = b"ortho"
DSM_BYTES: Final = b"dsm"
ORTHO_SHA256: Final = hashlib.sha256(ORTHO_BYTES).hexdigest()
DSM_SHA256: Final = hashlib.sha256(DSM_BYTES).hexdigest()
CHECKPOINT_SHA256: Final = hashlib.sha256(CHECKPOINT_BYTES).hexdigest()
SYNTHETIC_VERTICAL_REFERENCE: Final = {
    "datum": "ellipsoidal",
    "basis": "Synthetic-only fixture vertical reference.",
    "source": "user_declared",
}


@dataclass
class FakeStorage:
    """Minimal in-memory storage fake; it never exposes a filesystem path."""

    objects: dict[str, bytes] = field(default_factory=dict)

    def put(self, key: str, value: bytes) -> None:
        self.objects[key] = value

    def get(self, key: str) -> bytes:
        return self.objects[key]


def _geotiff_bytes(*, masked_nodata: bool = False, unmasked_nan: bool = False) -> bytes:
    values = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float32)
    nodata: float | None = None
    if masked_nodata:
        values[0, 0] = -9999.0
        nodata = -9999.0
    if unmasked_nan:
        values[0, 0] = np.nan
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=2,
            height=2,
            count=1,
            dtype="float32",
            crs="EPSG:3857",
            transform=Affine(1, 0, 0, 0, -1, 2),
            nodata=nodata,
        ) as dataset:
            dataset.write(values, 1)
        return memory.read()


@dataclass(frozen=True)
class SyntheticExternalArtifacts:
    """Fixed synthetic inputs for local contract/worker tests only."""

    storage: FakeStorage
    geotiff: bytes
    masked_nodata_geotiff: bytes
    unmasked_nan_geotiff: bytes
    malformed_tiff: bytes
    vrt: bytes
    zip_archive: bytes
    geotiff_sha256: str
    masked_nodata_geotiff_sha256: str
    unmasked_nan_geotiff_sha256: str
    checkpoint_csv: bytes = CHECKPOINT_BYTES


def synthetic_external_artifacts() -> SyntheticExternalArtifacts:
    """Build real in-memory GeoTIFF bytes plus hostile synthetic byte variants."""
    geotiff = _geotiff_bytes()
    masked_nodata_geotiff = _geotiff_bytes(masked_nodata=True)
    unmasked_nan_geotiff = _geotiff_bytes(unmasked_nan=True)
    vrt = b'<VRTDataset rasterXSize="2" rasterYSize="2"></VRTDataset>'
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("synthetic.tif", geotiff)
    storage = FakeStorage(
        {
            "synthetic/ortho.tif": geotiff,
            "synthetic/dsm.tif": geotiff,
            "synthetic/checkpoints.csv": CHECKPOINT_BYTES,
        }
    )
    return SyntheticExternalArtifacts(
        storage=storage,
        geotiff=geotiff,
        masked_nodata_geotiff=masked_nodata_geotiff,
        unmasked_nan_geotiff=unmasked_nan_geotiff,
        malformed_tiff=b"II*\x00truncated",
        vrt=vrt,
        zip_archive=archive_buffer.getvalue(),
        geotiff_sha256=hashlib.sha256(geotiff).hexdigest(),
        masked_nodata_geotiff_sha256=hashlib.sha256(masked_nodata_geotiff).hexdigest(),
        unmasked_nan_geotiff_sha256=hashlib.sha256(unmasked_nan_geotiff).hexdigest(),
    )
