"""Fixed no-network child entrypoint. Import the decoder only after containment proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ksi_event_contracts.spatial_data import SpatialDataFrozenJobV1, SpatialDataReceiptV1


def prepare_native_candidate(
    *,
    job: SpatialDataFrozenJobV1,
    source_path: Path,
    output_parent: Path,
    prepared_at: datetime,
    is_current: Callable[[], bool],
) -> SpatialDataReceiptV1:
    """Private child operation; direct test callers may supply trusted generated TIFFs only."""
    from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
    from ksi_geo_spatial.external_native_window import prepare_external_native_window

    source = job.source
    measured = source.inspection.measurements
    assert measured is not None
    native = prepare_external_native_window(
        source_path=source_path,
        source_observed_sha256=source.observed_sha256,
        source_size_bytes=source.observed_size_bytes,
        inspection=source.inspection,
        artifact_kind=ProcessingArtifactKind(source.artifact_kind),
        requested_bounds=job.request.requested_bounds,
        requested_crs_digest=job.request.observed_crs_digest,
        output_path=output_parent / "candidate.tif",
        envelope=job.policy.resource_envelope,
        max_output_pixels=job.policy.max_output_pixels,
        max_output_bytes=job.policy.max_output_bytes,
        is_cancelled=lambda: is_current() is not True,
    )
    facts = native.receipt
    return SpatialDataReceiptV1.model_validate(
        dict(
            job_id=job.job_id,
            job_digest=job.job_digest,
            source_digest=source.source_digest,
            request_digest=job.request.canonical_digest(),
            runtime_digest=job.runtime.runtime_digest,
            policy_digest=job.policy.policy_digest,
            grant_digest=job.grant.grant_digest,
            artifact_id=facts.artifact_id,
            artifact_kind=facts.artifact_kind.value,
            source_sha256=facts.source_sha256,
            source_size_bytes=facts.source_size_bytes,
            requested_bounds=facts.requested_bounds,
            requested_crs_digest=facts.requested_crs_digest,
            actual_bounds=facts.actual_bounds,
            pixel_window=facts.pixel_window,
            width=facts.width,
            height=facts.height,
            transform=facts.transform,
            source_transform=measured.transform,
            source_resolution=(measured.transform[0], -measured.transform[4]),
            observed_crs_identifier=facts.observed_crs_identifier,
            observed_crs_digest=facts.observed_crs_digest,
            observed_vertical_reference=facts.observed_vertical_reference,
            band_count=facts.band_count,
            dtype=facts.dtype,
            nodata_representation=facts.nodata_representation,
            nodata_value=facts.nodata_value,
            valid_pixel_count=facts.valid_pixel_count,
            output_sha256=facts.output_sha256,
            output_size_bytes=facts.output_size_bytes,
            accuracy_assessed=False,
            prepared_at=prepared_at,
            declaration_recorded_at=source.declaration_recorded_at,
            capture_started_at=source.capture_started_at,
            capture_ended_at=source.capture_ended_at,
            producer_processed_at=source.producer_processed_at,
            attribution=job.grant.attribution,
            modification_notice=(
                "Native-grid rectangular crop; no resampling, reprojection or height adjustment."
            ),
            limitations=("ACCURACY_NOT_ASSESSED",)
            + (
                ("UNKNOWN_VERTICAL_REFERENCE",) if facts.observed_vertical_reference is None else ()
            ),
        )
    ).sealed()


def main(argv: list[str] | None = None) -> int:
    from ksi_geo_spatial.external_native_window_geometry import NativeWindowError

    from ksi_processing_controller.spatial_data_sandbox import (
        SpatialDataContainmentProofV1,
        apply_spatial_data_rlimits,
        verify_process_containment,
    )
    from ksi_processing_controller.spatial_data_worker_config import parse_strict_json

    parser = argparse.ArgumentParser(description="Fixed isolated data child; launcher-only")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--containment-proof-fd", required=True, type=int)
    args = parser.parse_args(argv)

    def emit(body: dict[str, Any]) -> None:
        raw = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
        if len(raw) > 262144:
            raise ValueError("child result over budget")
        sys.stdout.buffer.write(struct.pack(">I", len(raw)) + raw)
        sys.stdout.buffer.flush()

    try:
        proof_raw = os.read(args.containment_proof_fd, 262145)
        os.close(args.containment_proof_fd)
        if len(proof_raw) > 262144:
            return 2
        proof = SpatialDataContainmentProofV1.model_validate(parse_strict_json(proof_raw))
        apply_spatial_data_rlimits(proof.resource_envelope, max_output_bytes=proof.max_output_bytes)
        emit({"version": "spatial-data-sandbox-ready.v1", "pid": os.getpid(), "ready": True})
        prefix = sys.stdin.buffer.read(4)
        if len(prefix) != 4:
            return 2
        length = struct.unpack(">I", prefix)[0]
        if not 0 < length <= 262144:
            return 2
        raw = sys.stdin.buffer.read(length)
        if len(raw) != length or sys.stdin.buffer.read(1):
            return 2
        request = parse_strict_json(raw)
        if (
            not isinstance(request, dict)
            or set(request) != {"version", "job", "preparedAt", "containmentProofSha256"}
            or request["version"] != "spatial-data-sandbox-request.v1"
        ):
            return 2
        if request["containmentProofSha256"] != "sha256:" + hashlib.sha256(proof_raw).hexdigest():
            return 2
        job = SpatialDataFrozenJobV1.model_validate(request["job"])
        if job.job_digest != job.canonical_digest() or not verify_process_containment(
            pid=os.getpid(), job=job, proof=proof, now=datetime.now(UTC), authority_pid=os.getppid()
        ):
            return 2
        workspace = Path(args.workspace)
        if not workspace.is_absolute() or workspace.is_symlink() or not workspace.is_dir():
            return 2
        prepared = datetime.fromisoformat(request["preparedAt"])
        receipt = prepare_native_candidate(
            job=job,
            source_path=workspace / "source.tif",
            output_parent=workspace,
            prepared_at=prepared,
            is_current=lambda: datetime.now(UTC) < min(job.deadline, proof.valid_until),
        )
        emit(
            {
                "version": "spatial-data-sandbox-result.v1",
                "receipt": receipt.model_dump(by_alias=True, mode="json"),
                "reason": None,
            }
        )
        return 0
    except NativeWindowError as exc:
        emit({"version": "spatial-data-sandbox-result.v1", "receipt": None, "reason": exc.reason})
        return 1
    except Exception:
        return 2  # No private exceptions, logs or tracebacks in the control channel.


if __name__ == "__main__":
    raise SystemExit(main())
