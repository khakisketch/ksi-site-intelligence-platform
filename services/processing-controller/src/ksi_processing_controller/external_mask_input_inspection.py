"""Contained binary-mask inspection primitive (P2 mask ingress, additive).

Runs inside the separately verified contained mask-inspection runtime.  It
proves one sealed binary-mask TIFF with the bounded binary-mask structural
preflight (:func:`parse_sealed_binary_mask_tiff_structure`) BEFORE any GDAL
open, then re-enforces strict single-band uint8 NO_NODATA binary facts on
the decoded view.  It never parses a DSM, never parses ortho imagery, and
never treats a DSM/ortho report as mask evidence: the output is the narrow
``MaskObservationReportV1`` only.

The expected grid (transform/digest + CRS identifier/digest) is an explicit
Core input derived from the baseline anchor.  The file must match it
exactly; no resampling, no filling, no silent reinterpretation.  Helper
byte-identity checks here establish byte/grid conformance only and must
never be read as an OS sandbox claim: containment itself is verified
separately.

Resource discipline: structural memory is charged before allocation/parse,
watchdog cancellation is honored, and all byte caps come from the sealed
resource envelope.  No network, no sidecars, no virtual paths.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_mask_input import MaskInspectionProfileV1
from ksi_event_contracts.external_mask_input_report import (
    MaskObservationMeasurementsV1,
    MaskObservationReportV1,
)
from ksi_geo_spatial.crs import assert_same_crs, assert_supported_project_crs
from rasterio.transform import Affine

from ksi_processing_controller.external_measurement_algorithms import MeasurementWatchdogV2
from ksi_processing_controller.external_tiff_structure import (
    TiffResourceLimitError,
    TiffStructureError,
    parse_sealed_binary_mask_tiff_structure,
)

_MASK_BYTES_PER_PIXEL = 4
_MASK_WORKING_BYTES = 2 * 1024 * 1024
_MASK_STRUCTURE_DIRECTORY_OBJECT_BYTES = 4 * 1024
_MASK_STRUCTURE_ENTRY_OBJECT_BYTES = 128


class MaskInspectionError(RuntimeError):
    """Contained mask inspection failed closed; carries the typed reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _require_sealed_envelope(envelope: object) -> ResourceEnvelopeV1:
    if not isinstance(envelope, ResourceEnvelopeV1):
        raise MaskInspectionError("RESOURCE_LIMIT_EXCEEDED")
    if (
        envelope.resource_envelope_digest is None
        or envelope.resource_envelope_digest != envelope.canonical_digest()
    ):
        raise MaskInspectionError("RESOURCE_LIMIT_EXCEEDED")
    return envelope


def _require_watchdog(watchdog: object) -> MeasurementWatchdogV2:
    if not isinstance(watchdog, MeasurementWatchdogV2):
        raise MaskInspectionError("RESOURCE_LIMIT_EXCEEDED")
    if isinstance(watchdog, bool):
        raise MaskInspectionError("RESOURCE_LIMIT_EXCEEDED")
    return watchdog


def _require_utc(value: datetime, name: str) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise MaskInspectionError("STALE_LEASE")
    return value


@contextmanager
def _offline_gdal_environment() -> Iterator[None]:
    with rasterio.Env(
        PROJ_NETWORK="OFF",
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_PAM_ENABLED="NO",
        GDAL_DRIVER_PATH="disable",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS="",
    ):
        yield


def _structure_base_dimensions(structure: Any) -> tuple[int, int]:
    try:
        base = structure.directories[0]
        byte_order = "<" if structure.byte_order == "II" else ">"
        width_values = base.entries[256].integers(byte_order)
        height_values = base.entries[257].integers(byte_order)
        if len(width_values) != 1 or len(height_values) != 1:
            raise MaskInspectionError("MASK_BYTES_MISMATCH")
        return int(width_values[0]), int(height_values[0])
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise MaskInspectionError("MASK_BYTES_MISMATCH") from exc


def inspect_mask_bytes_v1(
    *,
    path: Path | str,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
    organization_id: str,
    site_id: str,
    work_area_id: str,
    mask_child_id: str,
    mask_artifact_id: str,
    subject: dict[str, Any] | Any,
    inspection_profile: MaskInspectionProfileV1,
    contained_runtime_digest: str,
    inspector_build_digest: str,
    expected_crs_identifier: str,
    expected_crs_digest: str,
    expected_transform: tuple[float, float, float, float, float, float],
    expected_transform_digest: str,
    report_id: str,
    reported_at: datetime,
) -> MaskObservationReportV1:
    """Inspect one sealed mask file against Core's exact expected grid.

    Returns the sealed narrow observation report.  The observed SHA-256/size
    are computed from the file bytes here; the grid/CRS facts are proved
    against ``expected_*`` and echoed.  Any mismatch fails closed.
    """
    from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1

    try:
        envelope = _require_sealed_envelope(envelope)
        watchdog = _require_watchdog(watchdog)
        watchdog.check()
        _require_utc(reported_at, "reportedAt")
        if isinstance(subject, dict):
            sealed_subject = SealedExternalSubjectV1.model_validate(subject)
        elif isinstance(subject, SealedExternalSubjectV1):
            sealed_subject = SealedExternalSubjectV1.model_validate(
                subject.model_dump(by_alias=True)
            )
        else:
            raise MaskInspectionError("MASK_BYTES_MISMATCH")
        profile = MaskInspectionProfileV1.model_validate(
            inspection_profile.model_dump(by_alias=True)
        )
        if (
            profile.inspection_profile_digest is None
            or profile.inspection_profile_digest != profile.canonical_digest()
        ):
            raise MaskInspectionError("MASK_BYTES_MISMATCH")
        if not all(
            isinstance(value, str) and value.strip() and len(value) <= 255
            for value in (
                organization_id,
                site_id,
                work_area_id,
                mask_child_id,
                mask_artifact_id,
                report_id,
            )
        ):
            raise MaskInspectionError("MASK_BYTES_MISMATCH")
        if sealed_subject.organization_id != organization_id or sealed_subject.site_id != site_id:
            raise MaskInspectionError("MASK_BYTES_MISMATCH")
        if expected_transform_digest != _digest({"transform": list(expected_transform)}):
            raise MaskInspectionError("MASK_BYTES_MISMATCH")
        file_path = Path(path)
        size_bytes = file_path.stat().st_size
        if size_bytes <= 0 or size_bytes > min(
            envelope.max_input_bytes, envelope.max_streamed_bytes
        ):
            raise MaskInspectionError("RESOURCE_LIMIT_EXCEEDED")
        required = (
            2 * size_bytes
            + envelope.max_tiff_directories * _MASK_STRUCTURE_DIRECTORY_OBJECT_BYTES
            + envelope.max_tiff_entries * _MASK_STRUCTURE_ENTRY_OBJECT_BYTES
            + _MASK_WORKING_BYTES
        )
        if required > envelope.max_memory_bytes:
            raise MaskInspectionError("RESOURCE_LIMIT_EXCEEDED")
        try:
            structure = parse_sealed_binary_mask_tiff_structure(file_path, envelope)
        except TiffResourceLimitError as exc:
            raise MaskInspectionError("RESOURCE_LIMIT_EXCEEDED") from exc
        except (OSError, TiffStructureError, ValueError) as exc:
            raise MaskInspectionError("MASK_BYTES_MISMATCH") from exc
        width, height = _structure_base_dimensions(structure)
        if width * height > envelope.max_pixels:
            raise MaskInspectionError("RESOURCE_LIMIT_EXCEEDED")
        try:
            with (
                _offline_gdal_environment(),
                rasterio.open(file_path, "r", driver="GTiff") as dataset,
            ):
                if dataset.subdatasets:
                    raise MaskInspectionError("MASK_BYTES_MISMATCH")
                if dataset.width != width or dataset.height != height:
                    raise MaskInspectionError("MASK_BYTES_MISMATCH")
                if dataset.width * dataset.height > envelope.max_pixels:
                    raise MaskInspectionError("RESOURCE_LIMIT_EXCEEDED")
                if dataset.count > envelope.max_bands:
                    raise MaskInspectionError("RESOURCE_LIMIT_EXCEEDED")
                if (
                    dataset.width * dataset.height * _MASK_BYTES_PER_PIXEL + _MASK_WORKING_BYTES
                    > envelope.max_memory_bytes
                ):
                    raise MaskInspectionError("RESOURCE_LIMIT_EXCEEDED")
                if dataset.count != 1:
                    raise MaskInspectionError("MASK_BYTES_MISMATCH")
                if dataset.dtypes != ("uint8",):
                    raise MaskInspectionError("MASK_BYTES_MISMATCH")
                if dataset.nodata is not None:
                    raise MaskInspectionError("MASK_NODATA_REJECTED")
                if (dataset.width, dataset.height) != (width, height):
                    raise MaskInspectionError("MASK_BYTES_MISMATCH")
                if dataset.transform != Affine(*expected_transform):
                    raise MaskInspectionError("MASK_BYTES_MISMATCH")
                try:
                    crs_object = dataset.crs
                    if crs_object is None:
                        raise MaskInspectionError("MASK_BYTES_MISMATCH")
                    observed_crs = assert_supported_project_crs(crs_object.to_string())
                    assert_same_crs(observed_crs, expected_crs_identifier)
                except ValueError as exc:
                    raise MaskInspectionError("MASK_BYTES_MISMATCH") from exc
                if expected_crs_digest.strip() == "" or not expected_crs_digest.startswith(
                    "sha256:"
                ):
                    raise MaskInspectionError("MASK_BYTES_MISMATCH")
                if dataset.scales != (1.0,) or dataset.offsets != (0.0,):
                    raise MaskInspectionError("MASK_BYTES_MISMATCH")
                gcps, _ = dataset.gcps
                if gcps or dataset.tags(ns="GEOLOCATION"):
                    raise MaskInspectionError("MASK_BYTES_MISMATCH")
                actual_masks = dataset.read_masks(1)
                if bool((actual_masks != 255).any()):
                    raise MaskInspectionError("MASK_NODATA_REJECTED")
                watchdog.check()
                values = dataset.read(1, masked=False)
                file_transform = (
                    dataset.transform.a,
                    dataset.transform.b,
                    dataset.transform.c,
                    dataset.transform.d,
                    dataset.transform.e,
                    dataset.transform.f,
                )
        except MaskInspectionError:
            raise
        except (OSError, ValueError) as exc:
            raise MaskInspectionError("MASK_BYTES_MISMATCH") from exc
        if (
            not isinstance(values, np.ndarray)
            or values.dtype != np.dtype(np.uint8)
            or values.ndim != 2
        ):
            raise MaskInspectionError("MASK_BYTES_MISMATCH")
        unique = np.unique(values)
        if unique.size == 0 or bool(((unique != 0) & (unique != 1)).any()):
            raise MaskInspectionError("MASK_BYTES_MISMATCH")
        if values.shape != (height, width):
            raise MaskInspectionError("MASK_BYTES_MISMATCH")
        if tuple(float(v) for v in file_transform) != tuple(float(v) for v in expected_transform):
            raise MaskInspectionError("MASK_BYTES_MISMATCH")
        digest = hashlib.sha256()
        total = 0
        with open(file_path, "rb") as handle:
            while True:
                watchdog.check()
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
        if total != size_bytes:
            raise MaskInspectionError("MASK_BYTES_MISMATCH")
        observed_sha256 = "sha256:" + digest.hexdigest()
        left = expected_transform[2]
        top = expected_transform[5]
        bounds = (
            left,
            top + expected_transform[4] * height,
            left + expected_transform[0] * width,
            top,
        )
        measurements = MaskObservationMeasurementsV1(
            observed_crs_identifier=expected_crs_identifier,
            observed_crs_digest=expected_crs_digest,
            transform=expected_transform,
            transform_digest=expected_transform_digest,
            width=width,
            height=height,
            band_count=1,
            dtype="UINT8",
            nodata_representation="NONE",
            bounds=bounds,
        )
        return MaskObservationReportV1(
            report_id=report_id,
            mask_child_id=mask_child_id,
            organization_id=organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            subject=sealed_subject,
            subject_digest=sealed_subject.canonical_digest(),
            mask_artifact_id=mask_artifact_id,
            observed_sha256=observed_sha256,
            observed_size_bytes=size_bytes,
            inspection_profile_digest=profile.canonical_digest(),
            contained_runtime_digest=contained_runtime_digest,
            inspector_build_digest=inspector_build_digest,
            measurements=measurements,
            reported_at=reported_at,
        ).sealed()
    except MaskInspectionError:
        raise


__all__ = ["MaskInspectionError", "inspect_mask_bytes_v1"]
