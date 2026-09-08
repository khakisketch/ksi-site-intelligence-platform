"""Closed, versioned grammar identity for synthetic GeoTIFF v1 conformance.

The profile is deliberately code-owned rather than a caller-supplied runtime
option.  Policy and signed execution manifests bind its canonical digest before
any staged bytes can reach a backend.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ksi_domain.canonical_json import canonical_json_bytes


def external_geotiff_profile_body_v1() -> dict[str, Any]:
    """Return a fresh closed v1 body so callers cannot mutate future checks."""
    return {
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


def external_geotiff_profile_canonical_bytes_v1() -> bytes:
    """Serialize the closed body through the repository's finite canonical JSON."""
    return canonical_json_bytes(external_geotiff_profile_body_v1())


def external_geotiff_profile_digest_v1() -> str:
    """Return the policy/manifest grammar binding for this exact v1 body."""
    return "sha256:" + hashlib.sha256(external_geotiff_profile_canonical_bytes_v1()).hexdigest()


__all__ = [
    "external_geotiff_profile_body_v1",
    "external_geotiff_profile_canonical_bytes_v1",
    "external_geotiff_profile_digest_v1",
]
