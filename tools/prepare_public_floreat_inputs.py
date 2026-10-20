"""Prepare bounded, separately identified inputs from licensed Floreat source files.

Offline converter only: no downloading, Core writes, inspection, policy or numerical admission.
Originals are hash-verified and never modified. Capture dates remain publisher declarations.
Example: python tools/prepare_public_floreat_inputs.py --output .dev-data/floreat-inputs-new
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import ColorInterp, Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject

ROOT = Path(__file__).resolve().parents[1]
MAX_PIXELS = 4_194_304


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(manifest_path: Path, output: Path, resolution: float = 0.25) -> dict[str, Any]:
    """Export four bounded rasters and provenance, refusing an existing destination."""
    if not math.isfinite(resolution) or not 0.1 <= resolution <= 10:
        raise ValueError("resolution must be finite and between 0.1 and 10 source metres")
    manifest = json.loads(manifest_path.read_text())
    sources = manifest["originals"]
    if len(sources) != 4:
        raise ValueError("exactly four recorded source files are required")
    dates = {source["captureDate"] for source in sources}
    pairs = {(source["kind"], source["captureDate"]) for source in sources}
    if len(dates) != 2 or pairs != {
        (kind, date) for kind in ("orthomosaic", "DSM") for date in dates
    }:
        raise ValueError("one ortho and one DSM for each of two dates are required")
    paths: list[Path] = []
    bounds = []
    for source in sources:
        path = (ROOT / source["localIgnoredOriginal"]).resolve()
        if path.stat().st_size != source["bytes"] or sha256(path) != source["sha256"]:
            raise ValueError("source identity differs from its recorded identity")
        if output.resolve().is_relative_to(path.parent):
            raise ValueError("output must not be inside the original source directory")
        with rasterio.open(path) as dataset:
            if dataset.crs is None or dataset.crs.to_epsg() != 7850:
                raise ValueError("expected observed EPSG:7850, without relabelling")
            if dataset.transform.b != 0 or dataset.transform.d != 0:
                raise ValueError("rotated sources are outside this bounded converter")
            bounds.append(dataset.bounds)
        paths.append(path)
    left = max(b.left for b in bounds)
    bottom = max(b.bottom for b in bounds)
    right = min(b.right for b in bounds)
    top = min(b.top for b in bounds)
    width = math.floor((right - left) / resolution)
    height = math.floor((top - bottom) / resolution)
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise ValueError("common extent is empty or exceeds the finite export pixel budget")
    transform = from_origin(left, top, resolution, resolution)
    output.mkdir(parents=True, exist_ok=False)
    exported: list[dict[str, Any]] = []
    for source, path in zip(sources, paths, strict=True):
        is_ortho = source["kind"] == "orthomosaic"
        name = f"floreat-f3-{source['captureDate']}-{'ortho' if is_ortho else 'dsm'}-derived.tif"
        target = output / name
        with rasterio.open(path) as dataset:
            count, dtype = (4, "uint8") if is_ortho else (1, "float32")
            profile = {
                "driver": "GTiff",
                "width": width,
                "height": height,
                "count": count,
                "dtype": dtype,
                "crs": dataset.crs,
                "transform": transform,
                "compress": "DEFLATE",
                "tiled": True,
                "blockxsize": 256,
                "blockysize": 256,
                "interleave": "pixel",
            }
            if is_ortho:
                if dataset.count != 4:
                    raise ValueError("this source profile requires original RGBA orthomosaics")
                profile["photometric"] = "RGB"
            else:
                if dataset.count != 1 or dataset.nodata is None:
                    raise ValueError("this source profile requires a single-band DSM with NoData")
                profile["nodata"] = dataset.nodata
            with rasterio.open(target, "w", **profile) as destination:
                for band in range(1, count + 1):
                    pixels = np.zeros((height, width), dtype=dtype)
                    if not is_ortho:
                        pixels.fill(dataset.nodata)
                    reproject(
                        source=rasterio.band(dataset, band),
                        destination=pixels,
                        src_transform=dataset.transform,
                        src_crs=dataset.crs,
                        dst_transform=transform,
                        dst_crs=dataset.crs,
                        src_nodata=dataset.nodata,
                        dst_nodata=dataset.nodata,
                        resampling=Resampling.bilinear
                        if is_ortho and band < 4
                        else Resampling.nearest,
                    )
                    if is_ortho and band == 4:
                        # Conservative display validity: never promote semitransparent pixels.
                        pixels = np.where(pixels == 255, 255, 0).astype("uint8")
                    destination.write(pixels, band)
                if is_ortho:
                    destination.colorinterp = (
                        ColorInterp.red,
                        ColorInterp.green,
                        ColorInterp.blue,
                        ColorInterp.alpha,
                    )
        target.chmod(0o400)
        exported.append(
            {
                "file": name,
                "kind": source["kind"],
                "bytes": target.stat().st_size,
                "sha256": sha256(target),
                "captureDate": source["captureDate"],
                "captureDateBasis": source["captureDateBasis"],
                "captureStartedAt": None,
                "captureEndedAt": None,
                "upstreamSoftwareName": None,
                "upstreamSoftwareVersion": None,
                "sourceFilename": path.name,
                "sourceSha256": source["sha256"],
                "sourceCatalogueUrl": source["catalogueUrl"],
                "inspectionOutcome": None,
            }
        )
    for source, path in zip(sources, paths, strict=True):
        if sha256(path) != source["sha256"]:
            raise ValueError("source identity changed during preparation")
    record = {
        "purpose": "Separately identified sample inputs; NOT inspection or analysis evidence",
        "exportedAt": datetime.now(UTC).isoformat(),
        "publisher": manifest["publisher"],
        "license": manifest["license"],
        "licenseUrl": manifest["licenseUrl"],
        "attribution": manifest["attribution"],
        "exporter": {
            "tool": "prepare_public_floreat_inputs.py",
            "version": "1",
            "rasterio": rasterio.__version__,
            "gdal": rasterio.__gdal_version__,
        },
        "settings": {
            "horizontalCrs": "EPSG:7850",
            "verticalReference": None,
            "operation": "common-extent crop and explicit display-oriented resampling",
            "resolutionMetres": resolution,
            "width": width,
            "height": height,
            "bounds": [left, top - height * resolution, left + width * resolution, top],
            "rgbResampling": "bilinear",
            "dsmAndAlphaResampling": "nearest",
            "alphaValidity": "255 only; semitransparent source pixels excluded",
            "compression": "DEFLATE",
            "maxPixels": MAX_PIXELS,
        },
        "quantitativeSuitabilityClaim": False,
        "files": exported,
    }
    (output / "preparation.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "docs/design/DEMO_MATERIALS.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolution", type=float, default=0.25)
    args = parser.parse_args()
    record = prepare(args.manifest, args.output, args.resolution)
    print(
        f"Prepared {len(record['files'])} derived inputs; "
        "originals unchanged; not inspection evidence"
    )


if __name__ == "__main__":
    main()
