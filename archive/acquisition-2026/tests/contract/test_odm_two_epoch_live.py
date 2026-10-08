"""Foreign-CRS two-acquisition benchmark without weakening Korean project CRS policy.

This test is deliberately opt-in because its inputs are large external datasets.  It proves that
the exact v1 engine can reconstruct two real epochs with the same immutable options, produce the
required lineage, and yield overlapping finite DSM cells.  A foreign benchmark CRS never becomes a
KSI quantitative result: the production CRS whitelist is asserted to reject it (INV-020/053).

Run with owner-held data outside Git::

    KSI_NODEODM_URL=http://127.0.0.1:3972 \
    KSI_ODM_EPOCH_A_IMAGES=/private/epoch-a \
    KSI_ODM_EPOCH_B_IMAGES=/private/epoch-b \
    KSI_ODM_BENCHMARK_CRS=EPSG:32632 \
      uv run pytest -q -s tests/contract/test_odm_two_epoch_live.py

Set both ``KSI_ODM_EPOCH_{A,B}_GCP`` variables when the licensed source includes ODM-compatible
image observations. Leave both unset only for a technical benchmark whose source JPEGs carry EXIF
GNSS; that mode does not satisfy the separate camera-original or field-acceptance contract.
"""

from __future__ import annotations

import functools
import hashlib
import http.server
import json
import os
import shutil
import threading
import time
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pytest
import rasterio
from ksi_core.processing_profiles import ksi_odm_civil_v1
from ksi_geo_spatial.crs import UnsupportedCrsError, assert_supported_project_crs
from ksi_processing_controller.gsd import resolve_gsd
from ksi_processing_controller.http_node_odm import HttpNodeOdmClient
from ksi_processing_controller.odm import (
    GroundControlFile,
    OdmTaskStatus,
    SourceImage,
    assert_engine_matches,
    assert_ground_control_matches,
    plan_artifacts,
)
from rasterio.warp import Resampling, reproject

_URL = os.environ.get("KSI_NODEODM_URL", "").rstrip("/")
_EPOCH_A_IMAGES = os.environ.get("KSI_ODM_EPOCH_A_IMAGES", "")
_EPOCH_B_IMAGES = os.environ.get("KSI_ODM_EPOCH_B_IMAGES", "")
_EPOCH_A_GCP = os.environ.get("KSI_ODM_EPOCH_A_GCP", "")
_EPOCH_B_GCP = os.environ.get("KSI_ODM_EPOCH_B_GCP", "")
_BENCHMARK_CRS = os.environ.get("KSI_ODM_BENCHMARK_CRS", "")
_GCP_PAIR_VALID = bool(_EPOCH_A_GCP) == bool(_EPOCH_B_GCP)
_READY = all((_URL, _EPOCH_A_IMAGES, _EPOCH_B_IMAGES, _BENCHMARK_CRS)) and _GCP_PAIR_VALID
_PROFILE = ksi_odm_civil_v1()
_OPTIONS: dict[str, object] = dict(_PROFILE.processing_params)
_RASTER_ENTRIES = {
    "orthophoto": "odm_orthophoto/odm_orthophoto.tif",
    "dsm": "odm_dem/dsm.tif",
    "dtm": "odm_dem/dtm.tif",
}

pytestmark = pytest.mark.skipif(
    not _READY,
    reason=(
        "two-epoch live benchmark inputs are not configured; this does not prove or disprove "
        "Korean civil field acceptance"
    ),
)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


@dataclass(frozen=True)
class _EpochResult:
    dsm_path: Path
    dsm_sha256: str
    archive_sha256: str
    artifact_digests: dict[str, str]
    artifact_count: int
    image_count: int
    source_bundle_sha256: str


@contextmanager
def _serve(directory: Path) -> Iterator[str]:
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _images(directory: Path, base_url: str) -> tuple[list[SourceImage], str]:
    paths = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
    )
    assert len(paths) >= 5, f"real reconstruction needs at least five images, got {len(paths)}"
    names = [path.name for path in paths]
    assert len(names) == len(set(names)), "GCP binding requires unique image basenames"
    bundle_digest = hashlib.sha256()
    for path in paths:
        bundle_digest.update(path.name.encode("utf-8"))
        bundle_digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                bundle_digest.update(chunk)
    return (
        [
            SourceImage(
                media_id=path.name,
                download_url=f"{base_url}/{quote(path.relative_to(directory).as_posix())}",
            )
            for path in paths
        ],
        bundle_digest.hexdigest(),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_epoch(
    *,
    client: HttpNodeOdmClient,
    images_dir: Path,
    ground_control_path: Path | None,
    crs: str,
    output_dir: Path,
) -> _EpochResult:
    ground_control: GroundControlFile | None = None
    if ground_control_path is not None:
        ground_control_bytes = ground_control_path.read_bytes()
        assert_ground_control_matches(ground_control_bytes, declared_crs=crs)
        ground_control = GroundControlFile(crs=crs, content=ground_control_bytes)
    task_id: str | None = None
    with _serve(images_dir) as base_url:
        source_images, source_bundle_digest = _images(images_dir, base_url)
        task_id = client.new_task(
            source_images,
            _OPTIONS,
            ground_control=ground_control,
        )
        try:
            deadline = time.monotonic() + 7200
            state = client.task_info(task_id)
            while (
                state.status
                not in {
                    OdmTaskStatus.COMPLETED,
                    OdmTaskStatus.FAILED,
                    OdmTaskStatus.CANCELED,
                }
                and time.monotonic() < deadline
            ):
                time.sleep(15)
                state = client.task_info(task_id)
            assert state.status is OdmTaskStatus.COMPLETED, (
                f"two-epoch benchmark reconstruction failed (task {task_id}): {state}"
            )
            archive = client.download_archive(task_id, output_dir / "all.zip")
            dsm_path = output_dir / "dsm.tif"
            with zipfile.ZipFile(archive) as bundle:
                present = set(bundle.namelist())
                for artifact_id, entry in _RASTER_ENTRIES.items():
                    if entry not in present:
                        continue
                    extracted = (
                        dsm_path if artifact_id == "dsm" else output_dir / f"{artifact_id}.tif"
                    )
                    with bundle.open(entry) as source, extracted.open("wb") as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
            reports = plan_artifacts(archive, crs=crs, gsd_by_artifact=resolve_gsd(archive))
            required = {"point-cloud", "dsm", "dtm"}
            assert required <= {report.artifact_id for report in reports}
            return _EpochResult(
                dsm_path=dsm_path,
                dsm_sha256=_sha256(dsm_path),
                archive_sha256=_sha256(archive),
                artifact_digests={report.artifact_id: report.digest for report in reports},
                artifact_count=len(reports),
                image_count=len(source_images),
                source_bundle_sha256=source_bundle_digest,
            )
        finally:
            if task_id is not None:
                client.remove_task(task_id)


def test_two_epoch_foreign_crs_benchmark_preserves_the_product_gate(tmp_path: Path) -> None:
    """Two real epochs run; production quantity creation remains correctly unavailable."""

    with pytest.raises(UnsupportedCrsError):
        assert_supported_project_crs(_BENCHMARK_CRS)

    client = HttpNodeOdmClient(_URL)
    try:
        info = client.info()
        assert info.node_version == _PROFILE.node_odm_version
        assert_engine_matches(info, expected_version=_PROFILE.engine_version)
        baseline = _run_epoch(
            client=client,
            images_dir=Path(_EPOCH_A_IMAGES),
            ground_control_path=Path(_EPOCH_A_GCP) if _EPOCH_A_GCP else None,
            crs=_BENCHMARK_CRS,
            output_dir=tmp_path / "baseline",
        )
        current = _run_epoch(
            client=client,
            images_dir=Path(_EPOCH_B_IMAGES),
            ground_control_path=Path(_EPOCH_B_GCP) if _EPOCH_B_GCP else None,
            crs=_BENCHMARK_CRS,
            output_dir=tmp_path / "current",
        )
    finally:
        client.close()

    assert baseline.dsm_sha256 != current.dsm_sha256, (
        "distinct epochs unexpectedly produced identical DSM bytes"
    )
    with rasterio.open(baseline.dsm_path) as base, rasterio.open(current.dsm_path) as curr:
        assert base.crs is not None and curr.crs is not None
        assert base.crs.to_string() == _BENCHMARK_CRS
        assert curr.crs.to_string() == _BENCHMARK_CRS
        current_on_base = np.full((base.height, base.width), np.nan, dtype=np.float64)
        reproject(
            source=curr.read(1).astype(np.float64),
            destination=current_on_base,
            src_transform=curr.transform,
            src_crs=curr.crs,
            dst_transform=base.transform,
            dst_crs=base.crs,
            src_nodata=curr.nodata,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
        base_values = base.read(1).astype(np.float64)
        valid = np.isfinite(base_values) & np.isfinite(current_on_base)
        if base.nodata is not None:
            valid &= base_values != base.nodata
        assert int(valid.sum()) > 0, "two reconstructed DSM epochs have no common valid cells"
        mean_absolute_delta = float(np.abs(current_on_base[valid] - base_values[valid]).mean())
        assert np.isfinite(mean_absolute_delta)

    print(
        json.dumps(
            {
                "status": "BENCHMARK_PASS",
                "scope": "NON_PRODUCTION_FOREIGN_CRS_BENCHMARK_ONLY",
                "fieldAcceptance": "NOT_EVALUATED",
                "nodeOdmVersion": info.node_version,
                "odmVersion": info.engine_version,
                "processingProfileId": _PROFILE.processing_profile_id,
                "processingProfileDigest": _PROFILE.profile_digest,
                "crs": _BENCHMARK_CRS,
                "baselineArchiveSha256": baseline.archive_sha256,
                "currentArchiveSha256": current.archive_sha256,
                "baselineDsmSha256": baseline.dsm_sha256,
                "currentDsmSha256": current.dsm_sha256,
                "baselineArtifactDigests": baseline.artifact_digests,
                "currentArtifactDigests": current.artifact_digests,
                "baselineArtifactCount": baseline.artifact_count,
                "currentArtifactCount": current.artifact_count,
                "baselineImageCount": baseline.image_count,
                "currentImageCount": current.image_count,
                "baselineSourceBundleSha256": baseline.source_bundle_sha256,
                "currentSourceBundleSha256": current.source_bundle_sha256,
                "commonValidCellCount": int(valid.sum()),
                "meanAbsoluteDeltaM": round(mean_absolute_delta, 6),
                "georeferencingMode": "GCP" if _EPOCH_A_GCP else "EXIF_GNSS",
                "productQuantitativeComparisonExecutable": False,
            },
            sort_keys=True,
        )
    )
