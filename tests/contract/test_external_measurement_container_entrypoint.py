"""Direct synthetic conformance tests for the contained two-input V2 image."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pytest
import rasterio
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence import (
    EvidenceCoreVerdict,
    ExternalEvidenceMeasurementPayloadV1,
    ExternalEvidenceRecordV1,
    ExternalEvidenceValidationRequestV1,
)
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1
from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestV1
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller import (
    external_geotiff_inspector,
    external_measurement_container_entrypoint,
)
from ksi_processing_controller.external_geotiff_inspector import inspect_synthetic_sealed_geotiff
from ksi_processing_controller.external_inspector_protocol import LocalLeaseFenceV1
from ksi_processing_controller.external_measurement_algorithms import (
    MeasurementAlgorithmError,
    MeasurementWatchdogV2,
    _validated_epoch_rmses,
    align_masked_dsm_difference,
)
from ksi_processing_controller.external_measurement_container_entrypoint import (
    MeasurementContainerEntrypointError,
    run_measurement_container_entrypoint,
)
from ksi_processing_controller.external_measurement_container_protocol import (
    MeasurementContainerFrameLimitsV2,
    build_execute_frame_v2,
    build_prepare_frame_v2,
    build_secondary_begin_frame,
    decode_measurement_container_frame,
    encode_measurement_container_frame,
)
from ksi_processing_controller.external_measurement_protocol import (
    MeasurementInputV2,
    MeasurementLaunchRequestV2,
)
from pyproj import CRS
from rasterio.transform import from_origin
from test_external_inspector_container_entrypoint import _envelope
from test_external_measurement_protocol import measurement_manifest_request

_NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def _digest_bytes(payload: bytes) -> str:
    return "sha256:" + sha256(payload).hexdigest()


def _digest_canonical(value: Mapping[str, Any]) -> str:
    return "sha256:" + sha256(canonical_json_bytes(value)).hexdigest()


def _write_compound_dsm(
    path: Path,
    values: np.ndarray,
    *,
    masked: bool = False,
    compress: str = "DEFLATE",
) -> None:
    height, width = values.shape
    if height % 16 or width % 16:
        raise ValueError("synthetic DSM dimensions must be multiples of the fixed tile size")
    crs = CRS.from_user_input("EPSG:5186+5709")
    with (
        rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True),
        rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=1,
            dtype="float32",
            crs=crs,
            transform=from_origin(200_000.0, 500_000.0, 1.0, 1.0),
            tiled=True,
            blockxsize=16,
            blockysize=16,
            compress=compress,
            predictor=3,
            interleave="pixel",
        ) as dataset,
    ):
        dataset.write(values[np.newaxis, ...])
        if masked:
            dataset.write_mask(
                np.where(np.indices((height, width))[0] == 0, 0, 255).astype("uint8")
            )


def _observed(path: Path) -> tuple[str, int, str, str]:
    outcome = inspect_synthetic_sealed_geotiff(
        path,
        artifact_id="synthetic",
        observed_sha256=_digest_bytes(path.read_bytes()),
        artifact_kind=ProcessingArtifactKind.DSM,
        envelope=_envelope(),
    )
    assert outcome.measurements is not None
    vertical = outcome.measurements.observed_vertical_reference
    assert vertical is not None
    return (
        _digest_bytes(path.read_bytes()),
        path.stat().st_size,
        outcome.measurements.observed_crs_digest,
        _digest_canonical(vertical.model_dump(by_alias=True, mode="json")),
    )


def _limits() -> MeasurementContainerFrameLimitsV2:
    return MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000)


def _frame(frame: dict[str, object]) -> bytes:
    return encode_measurement_container_frame(frame, limits=_limits())


def _decode_frames(stream: BytesIO) -> list[dict[str, object]]:
    raw = stream.getvalue()
    frames: list[dict[str, object]] = []
    while raw:
        size = int.from_bytes(raw[:4], "big")
        frames.append(decode_measurement_container_frame(raw[: 4 + size], limits=_limits()))
        raw = raw[4 + size :]
    return frames


def _volume_request(
    *, baseline: Path, current: Path
) -> tuple[InspectorExecutionManifestV1, MeasurementLaunchRequestV2]:
    manifest, original = measurement_manifest_request()
    base_digest, base_size, crs_digest, vertical_digest = _observed(baseline)
    current_digest, current_size, current_crs_digest, current_vertical_digest = _observed(current)
    assert (crs_digest, vertical_digest) == (current_crs_digest, current_vertical_digest)
    volume = original.volume_request
    assert volume is not None
    zone = volume.zone_snapshot.model_copy(
        update={
            "polygon": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [200_000.0, 500_000.0],
                        [200_002.0, 500_000.0],
                        [200_002.0, 499_998.0],
                        [200_000.0, 499_998.0],
                        [200_000.0, 500_000.0],
                    ]
                ],
            },
            "crs": "EPSG:5186",
            "observed_crs_digest": crs_digest,
            "analysis_vertical_reference_digest": vertical_digest,
            "definition_digest": None,
        }
    ).sealed()
    baseline_binding = volume.baseline.model_copy(
        update={
            "observed_sha256": base_digest,
            "observed_size_bytes": base_size,
            "observed_crs_digest": crs_digest,
            "observed_vertical_reference_digest": vertical_digest,
        }
    )
    current_binding = volume.current.model_copy(
        update={
            "observed_sha256": current_digest,
            "observed_size_bytes": current_size,
            "observed_crs_digest": crs_digest,
            "observed_vertical_reference_digest": vertical_digest,
        }
    )
    sealed_volume = volume.model_copy(
        update={
            "baseline": baseline_binding,
            "current": current_binding,
            "zone_snapshot": zone,
            "request_digest": None,
        }
    ).sealed()
    request = original.model_copy(
        update={
            "inputs": (
                MeasurementInputV2(
                    role="BASELINE_DSM",
                    artifact_id=baseline_binding.dsm_artifact_id,
                    observed_sha256=base_digest,
                    observed_size_bytes=base_size,
                ),
                MeasurementInputV2(
                    role="CURRENT_DSM",
                    artifact_id=current_binding.dsm_artifact_id,
                    observed_sha256=current_digest,
                    observed_size_bytes=current_size,
                ),
            ),
            "volume_request": sealed_volume,
            "canonical_input_digest": None,
        }
    ).sealed()
    return manifest, request


def _rebind_volume_current(
    request: MeasurementLaunchRequestV2, current: Path
) -> MeasurementLaunchRequestV2:
    """Keep sealed V2 request bindings exact after a synthetic byte mutation."""

    volume = request.volume_request
    assert volume is not None
    binding = volume.current.model_copy(
        update={
            "observed_sha256": _digest_bytes(current.read_bytes()),
            "observed_size_bytes": current.stat().st_size,
        }
    )
    volume = volume.model_copy(update={"current": binding, "request_digest": None}).sealed()
    return request.model_copy(
        update={
            "inputs": (
                request.inputs[0],
                MeasurementInputV2(
                    role="CURRENT_DSM",
                    artifact_id=binding.dsm_artifact_id,
                    observed_sha256=binding.observed_sha256,
                    observed_size_bytes=binding.observed_size_bytes,
                ),
            ),
            "volume_request": volume,
            "canonical_input_digest": None,
        }
    ).sealed()


def _with_manifest_memory_ceiling(
    manifest: InspectorExecutionManifestV1,
    request: MeasurementLaunchRequestV2,
    *,
    max_memory_bytes: int,
) -> tuple[InspectorExecutionManifestV1, MeasurementLaunchRequestV2]:
    """Rebind V2 execution authority to a deliberately smaller signed ceiling."""

    ceilings = manifest.body.hard_ceilings.model_copy(update={"max_memory_bytes": max_memory_bytes})
    body = manifest.body.model_copy(update={"hard_ceilings": ceilings})
    signature = manifest.signature.model_copy(update={"digest": body.canonical_body_digest()})
    manifest = manifest.model_copy(update={"body": body, "signature": signature})
    execution = request.volume_execution_policy
    volume = request.volume_request
    assert execution is not None and volume is not None
    execution = execution.model_copy(
        update={"algorithm_build_digest": body.canonical_body_digest(), "policy_digest": None}
    ).sealed()
    volume = volume.model_copy(
        update={"execution_policy_digest": execution.policy_digest, "request_digest": None}
    ).sealed()
    request = request.model_copy(
        update={
            "volume_execution_policy": execution,
            "volume_request": volume,
            "canonical_input_digest": None,
        }
    ).sealed()
    return manifest, request


def _with_checkpoint_manifest_memory_ceiling(
    manifest: InspectorExecutionManifestV1,
    request: MeasurementLaunchRequestV2,
    *,
    max_memory_bytes: int,
) -> tuple[InspectorExecutionManifestV1, MeasurementLaunchRequestV2]:
    ceilings = manifest.body.hard_ceilings.model_copy(update={"max_memory_bytes": max_memory_bytes})
    body = manifest.body.model_copy(update={"hard_ceilings": ceilings})
    signature = manifest.signature.model_copy(update={"digest": body.canonical_body_digest()})
    manifest = manifest.model_copy(update={"body": body, "signature": signature})
    context = request.evidence_context
    assert context is not None
    context = context.model_copy(
        update={
            "measurement_execution_manifest_digest": body.canonical_body_digest(),
            "context_digest": None,
        }
    ).sealed()
    request = request.model_copy(
        update={"evidence_context": context, "canonical_input_digest": None}
    ).sealed()
    return manifest, request


def _validated_volume_record(
    request: MeasurementLaunchRequestV2,
    *,
    binding_index: int,
    record_id: str,
    rmse_m: float,
    subject_digest: str | None = None,
    dsm_digest: str | None = None,
    policy_digest: str | None = None,
) -> ExternalEvidenceRecordV1:
    volume = request.volume_request
    assert volume is not None and request.validation_policy.policy_digest is not None
    binding = (volume.baseline, volume.current)[binding_index]
    subject = subject_digest or binding.subject.canonical_digest()
    dsm = dsm_digest or binding.observed_sha256
    policy = policy_digest or request.validation_policy.policy_digest
    payload = ExternalEvidenceMeasurementPayloadV1(
        validation_id=f"validation-{record_id}",
        evidence_manifest_digest="sha256:" + "c" * 64,
        target_dsm_observed_sha256=dsm,
        policy_digest=policy,
        measured_checkpoint_count=3,
        mean_error_m=0.0,
        mae_m=rmse_m,
        rmse_m=rmse_m,
        max_abs_error_m=rmse_m,
        measured_at=_NOW,
    )
    return ExternalEvidenceRecordV1(
        evidence_record_id=f"record-{record_id}",
        validation_id=payload.validation_id,
        subject_digest=subject,
        evidence_manifest_digest=payload.evidence_manifest_digest,
        target_dsm_observed_sha256=dsm,
        policy_digest=policy,
        measurement_payload=payload,
        core_verdict=EvidenceCoreVerdict.VALIDATED,
        core_reason=None,
        core_recorded_at=_NOW,
    ).sealed()


def _with_volume_evidence(
    request: MeasurementLaunchRequestV2, records: tuple[ExternalEvidenceRecordV1, ...]
) -> MeasurementLaunchRequestV2:
    volume = request.volume_request
    assert volume is not None
    volume = volume.model_copy(
        update={
            "evidence_record_digests": tuple(record.evidence_record_digest for record in records),
            "request_digest": None,
        }
    ).sealed()
    return request.model_copy(
        update={
            "volume_request": volume,
            "volume_evidence_records": records,
            "canonical_input_digest": None,
        }
    ).sealed()


def _checkpoint_request(
    *, primary: Path, checkpoint_csv: bytes, context_vertical_digest: str | None = None
) -> tuple[InspectorExecutionManifestV1, MeasurementLaunchRequestV2]:
    manifest, original = measurement_manifest_request()
    primary_digest, primary_size, _, vertical_digest = _observed(primary)
    policy = original.validation_policy.model_copy(
        update={
            "evidence_rule_ids": ("CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",),
            "policy_digest": None,
        }
    ).sealed()
    assert policy.policy_digest is not None
    subject = SealedExternalSubjectV1(
        organization_id="organization-1",
        site_id="site-1",
        work_order_id="work-order-1",
        submission_id="submission-1",
        revision=1,
        submission_digest="sha256:" + "a" * 64,
        manifest_digest="sha256:" + "b" * 64,
    )
    context = ExternalEvidenceMeasurementContextV1(
        context_id="checkpoint-context-1",
        subject=subject,
        evidence_manifest_digest="sha256:" + "c" * 64,
        evidence_observed_sha256=_digest_bytes(checkpoint_csv),
        evidence_observed_size_bytes=len(checkpoint_csv),
        target_dsm_artifact_id="target-dsm-1",
        target_dsm_observed_sha256=primary_digest,
        policy_digest=policy.policy_digest,
        measurement_execution_manifest_digest=manifest.canonical_body_digest(),
        rule_id="CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",
        csv_horizontal_crs="EPSG:5186",
        csv_vertical_reference_digest=context_vertical_digest or vertical_digest,
        minimum_checkpoint_count=3,
        maximum_checkpoint_count=3,
        maximum_rmse_m=100.0,
        maximum_abs_mean_error_m=100.0,
        maximum_abs_error_m=100.0,
        independent_attestation=None,
        authorized_actor_ids=("actor-1",),
        active_from=_NOW - timedelta(minutes=1),
        active_until=_NOW + timedelta(minutes=1),
        synthetic_test_only=True,
    ).sealed()
    evidence = ExternalEvidenceValidationRequestV1(
        validation_id="checkpoint-validation-1",
        evidence_manifest_digest=context.evidence_manifest_digest,
        subject_digest=subject.canonical_digest(),
        target_dsm_observed_sha256=primary_digest,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_digest=policy.policy_digest,
        issued_at=_NOW,
        idempotency_key="checkpoint-idempotency-1",
    )
    request = MeasurementLaunchRequestV2(
        operation="CHECKPOINT_VALIDATION",
        inputs=(
            MeasurementInputV2(
                role="TARGET_DSM",
                artifact_id=context.target_dsm_artifact_id,
                observed_sha256=primary_digest,
                observed_size_bytes=primary_size,
            ),
            MeasurementInputV2(
                role="CHECKPOINT_CSV",
                artifact_id="checkpoint-evidence-1",
                observed_sha256=_digest_bytes(checkpoint_csv),
                observed_size_bytes=len(checkpoint_csv),
            ),
        ),
        validation_policy=policy,
        checkpoint_request=evidence,
        evidence_context=context,
        volume_request=None,
        volume_execution_policy=None,
        volume_evidence_records=(),
        fence=LocalLeaseFenceV1(
            worker_instance_id=str(uuid4()),
            lease_acquisition_id=str(uuid4()),
            lease_generation=1,
        ),
        attempt_nonce=str(uuid4()),
    ).sealed()
    return manifest, request


def _run(
    *,
    manifest: InspectorExecutionManifestV1,
    request: MeasurementLaunchRequestV2,
    primary: Path,
    secondary: bytes,
    workspace: Path,
) -> list[dict[str, object]]:
    prepare = build_prepare_frame_v2(request=request, manifest=manifest)
    stream = BytesIO(
        _frame(prepare)
        + _frame(build_secondary_begin_frame(prepare=prepare))
        + secondary
        + _frame(build_execute_frame_v2(prepare=prepare))
    )
    stdout = BytesIO()
    run_measurement_container_entrypoint(
        stdin=stream,
        stdout=stdout,
        artifact_path=primary,
        workspace=workspace,
        limits=_limits(),
    )
    return _decode_frames(stdout)


def test_direct_entrypoint_checkpoint_returns_only_known_aggregate_metrics(tmp_path: Path) -> None:
    primary = tmp_path / "target.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    values = np.full((16, 16), 10.0, dtype=np.float32)
    values[0, 1] = 20.0
    values[1, 0] = 30.0
    _write_compound_dsm(primary, values)
    checkpoint_csv = (
        b"checkpoint_id,easting_m,northing_m,elevation_m\n"
        b"a,200000.5,499999.5,9\n"
        b"b,200001.5,499999.5,18\n"
        b"c,200000.5,499998.5,31\n"
    )
    manifest, request = _checkpoint_request(primary=primary, checkpoint_csv=checkpoint_csv)

    frames = _run(
        manifest=manifest,
        request=request,
        primary=primary,
        secondary=checkpoint_csv,
        workspace=workspace,
    )

    assert [frame["frame"] for frame in frames] == [
        "SECONDARY_STAGED",
        "PRIMARY_MOUNT_VERIFIED",
        "COMPLETED",
    ]
    aggregate = frames[-1]["aggregate"]
    assert aggregate == {
        "metricType": "CHECKPOINT_VALIDATION_AGGREGATE_V2",
        "measuredCheckpointCount": 3,
        "meanErrorM": 2 / 3,
        "maeM": 4 / 3,
        "rmseM": np.sqrt(2.0),
        "maxAbsErrorM": 2.0,
    }
    assert not list(workspace.iterdir())


def test_direct_entrypoint_volume_preserves_masked_coverage_and_cut_fill_sign(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.tif"
    current = tmp_path / "current.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    base = np.full((16, 16), 10.0, dtype=np.float32)
    current_values = base.copy()
    current_values[0, 0] = 9.0
    current_values[0, 1] = 15.0
    _write_compound_dsm(baseline, base)
    _write_compound_dsm(current, current_values)
    manifest, request = _volume_request(baseline=baseline, current=current)

    frames = _run(
        manifest=manifest,
        request=request,
        primary=baseline,
        secondary=current.read_bytes(),
        workspace=workspace,
    )

    assert [frame["frame"] for frame in frames] == [
        "SECONDARY_STAGED",
        "PRIMARY_MOUNT_VERIFIED",
        "COMPLETED",
    ]
    metrics = cast(dict[str, Any], frames[-1]["aggregate"])["metrics"]
    assert metrics["cutM3"] == 1.0
    assert metrics["fillM3"] == 5.0
    assert metrics["netM3"] == 4.0
    assert metrics["commonValidCellCount"] == 4
    assert not list(workspace.iterdir())


def test_direct_entrypoint_volume_binds_known_uncertainty_to_matching_epoch_rmses(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.tif"
    current = tmp_path / "current.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    values = np.full((16, 16), 10.0, dtype=np.float32)
    _write_compound_dsm(baseline, values)
    _write_compound_dsm(current, values)
    manifest, request = _volume_request(baseline=baseline, current=current)
    baseline_record = _validated_volume_record(
        request, binding_index=0, record_id="baseline", rmse_m=1.0
    )
    current_record = _validated_volume_record(
        request, binding_index=1, record_id="current", rmse_m=2.0
    )
    request = _with_volume_evidence(request, (baseline_record, current_record))

    frames = _run(
        manifest=manifest,
        request=request,
        primary=baseline,
        secondary=current.read_bytes(),
        workspace=workspace,
    )

    metrics = cast(dict[str, Any], frames[-1]["aggregate"])["metrics"]
    assert metrics["uncertaintyM3"] == 4.0 * np.hypot(1.0, 2.0)
    assert metrics["uncertaintyNote"] == (
        "Independent validated checkpoint RMSE was used for both epochs."
    )


@pytest.mark.parametrize("compress", ("LZMA", "LERC"))
def test_direct_entrypoint_rejects_secondary_codec_outside_the_signed_dsm_profile(
    tmp_path: Path, compress: str
) -> None:
    baseline = tmp_path / "baseline.tif"
    current = tmp_path / "current.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    values = np.full((16, 16), 10.0, dtype=np.float32)
    _write_compound_dsm(baseline, values)
    _write_compound_dsm(current, values)
    manifest, request = _volume_request(baseline=baseline, current=current)

    # LZMA remains a valid TIFF for Rasterio, but lies outside the V1 signed DSM
    # codec allowlist which the anonymous current DSM must share before decode.
    _write_compound_dsm(current, values, compress=compress)
    request = _rebind_volume_current(request, current)
    frames = _run(
        manifest=manifest,
        request=request,
        primary=baseline,
        secondary=current.read_bytes(),
        workspace=workspace,
    )

    assert frames[-1] == {
        "protocolVersion": "external-measurement-container.v2",
        "frame": "FAILED",
        "requestId": request.request_id,
        "attemptNonce": request.attempt_nonce,
        "outerCanonicalInputDigest": request.canonical_input_digest,
        "prepareDigest": build_prepare_frame_v2(request=request, manifest=manifest)[
            "prepareDigest"
        ],
        "operation": "RELATIVE_VOLUME",
        "executionManifestDigest": request.execution_manifest_digest,
        "fence": request.fence.model_dump(by_alias=True, mode="json"),
        "reason": "SECONDARY_DSM_REJECTED",
    }


def test_manifest_memory_ceiling_is_effective_before_volume_grid_allocations(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.tif"
    current = tmp_path / "current.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    values = np.full((16, 16), 10.0, dtype=np.float32)
    _write_compound_dsm(baseline, values)
    _write_compound_dsm(current, values)
    manifest, request = _volume_request(baseline=baseline, current=current)
    manifest, request = _with_manifest_memory_ceiling(manifest, request, max_memory_bytes=1)

    frames = _run(
        manifest=manifest,
        request=request,
        primary=baseline,
        secondary=current.read_bytes(),
        workspace=workspace,
    )

    assert frames[-1]["frame"] == "FAILED"
    assert frames[-1]["reason"] == "RESOURCE_LIMIT_EXCEEDED"


def test_manifest_memory_ceiling_blocks_raster_pixel_reads_before_decode(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.tif"
    current = tmp_path / "current.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    values = np.full((16, 16), 10.0, dtype=np.float32)
    _write_compound_dsm(baseline, values)
    _write_compound_dsm(current, values)
    manifest, request = _volume_request(baseline=baseline, current=current)
    manifest, request = _with_manifest_memory_ceiling(manifest, request, max_memory_bytes=1)
    reads: list[int] = []
    original: Callable[..., object] = external_geotiff_inspector._scan_base_and_internal_mask

    class _DatasetReadProbe:
        def __init__(self, dataset: rasterio.io.DatasetReader) -> None:
            self._dataset = dataset

        def __getattr__(self, name: str) -> object:
            return getattr(self._dataset, name)

        def read(self, *args: object, **kwargs: object) -> np.ndarray:
            value = self._dataset.read(*args, **kwargs)
            reads.append(value.nbytes)
            return value

        def read_masks(self, *args: object, **kwargs: object) -> np.ndarray:
            value = self._dataset.read_masks(*args, **kwargs)
            reads.append(value.nbytes)
            return value

    def _probe_scan(dataset: rasterio.io.DatasetReader, *args: object, **kwargs: object) -> object:
        return original(cast(Any, _DatasetReadProbe(dataset)), *args, **kwargs)

    with patch.object(external_geotiff_inspector, "_scan_base_and_internal_mask", _probe_scan):
        frames = _run(
            manifest=manifest,
            request=request,
            primary=baseline,
            secondary=current.read_bytes(),
            workspace=workspace,
        )

    assert frames[-1]["reason"] == "RESOURCE_LIMIT_EXCEEDED"
    assert reads == []


def test_manifest_memory_ceiling_rejects_checkpoint_materialization(tmp_path: Path) -> None:
    primary = tmp_path / "target.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    _write_compound_dsm(primary, np.full((16, 16), 10.0, dtype=np.float32))
    checkpoint_csv = (
        b"checkpoint_id,easting_m,northing_m,elevation_m\n"
        b"a,200000.5,499999.5,10\n"
        b"b,200001.5,499999.5,10\n"
        b"c,200000.5,499998.5,10\n"
    )
    manifest, request = _checkpoint_request(primary=primary, checkpoint_csv=checkpoint_csv)
    manifest, request = _with_checkpoint_manifest_memory_ceiling(
        manifest, request, max_memory_bytes=1
    )

    frames = _run(
        manifest=manifest,
        request=request,
        primary=primary,
        secondary=checkpoint_csv,
        workspace=workspace,
    )

    assert frames[-1]["frame"] == "FAILED"
    assert frames[-1]["reason"] == "RESOURCE_LIMIT_EXCEEDED"


def test_unequal_source_grids_are_charged_before_any_alignment_allocation(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.tif"
    current = tmp_path / "current.tif"
    _write_compound_dsm(baseline, np.full((16, 16), 10.0, dtype=np.float32))
    _write_compound_dsm(current, np.full((32, 32), 10.0, dtype=np.float32))
    envelope = (
        _envelope()
        .model_copy(update={"max_memory_bytes": 20_000, "resource_envelope_digest": None})
        .sealed()
    )

    with pytest.raises(MeasurementAlgorithmError, match="RESOURCE_LIMIT_EXCEEDED"):
        align_masked_dsm_difference(
            baseline_path=baseline,
            current_path=current,
            envelope=envelope,
            watchdog=MeasurementWatchdogV2.from_envelope(envelope),
        )


def test_volume_uncertainty_uses_only_the_ordered_matching_validated_records() -> None:
    _, request = measurement_manifest_request()
    baseline = _validated_volume_record(request, binding_index=0, record_id="base", rmse_m=1.0)
    current = _validated_volume_record(request, binding_index=1, record_id="current", rmse_m=2.0)
    request = _with_volume_evidence(request, (baseline, current))

    assert _validated_epoch_rmses(request) == (1.0, 2.0)


@pytest.mark.parametrize(
    "kind",
    ("cross_subject", "cross_dsm", "cross_policy", "duplicate_epoch", "reversed"),
)
def test_volume_uncertainty_rejects_unrelated_or_misordered_validated_records(kind: str) -> None:
    _, request = measurement_manifest_request()
    baseline = _validated_volume_record(request, binding_index=0, record_id="base", rmse_m=1.0)
    current = _validated_volume_record(request, binding_index=1, record_id="current", rmse_m=2.0)
    if kind == "cross_subject":
        baseline = _validated_volume_record(
            request,
            binding_index=0,
            record_id="wrong-subject",
            rmse_m=1.0,
            subject_digest="sha256:" + "f" * 64,
        )
    elif kind == "cross_dsm":
        current = _validated_volume_record(
            request,
            binding_index=1,
            record_id="wrong-dsm",
            rmse_m=2.0,
            dsm_digest=_digest_bytes(b"unrelated-dsm"),
        )
    elif kind == "cross_policy":
        current = _validated_volume_record(
            request,
            binding_index=1,
            record_id="wrong-policy",
            rmse_m=2.0,
            policy_digest="sha256:" + "d" * 64,
        )
    elif kind == "duplicate_epoch":
        current = _validated_volume_record(
            request, binding_index=0, record_id="base-again", rmse_m=2.0
        )
    else:
        baseline, current = current, baseline
    # The integrated outer request now rejects these bindings before launch.
    with pytest.raises(ValueError):
        _with_volume_evidence(request, (baseline, current))
    # Retain the algorithm's defensive check against an unsafe in-memory object.
    unsafe = request.model_copy(update={"volume_evidence_records": (baseline, current)})
    with pytest.raises(MeasurementAlgorithmError, match="VOLUME_EVIDENCE_BINDING_MISMATCH"):
        _validated_epoch_rmses(unsafe)


def test_direct_entrypoint_refuses_masked_full_zone_undercoverage_without_metrics(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.tif"
    current = tmp_path / "current.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    values = np.full((16, 16), 10.0, dtype=np.float32)
    _write_compound_dsm(baseline, values)
    _write_compound_dsm(current, values, masked=True)
    manifest, request = _volume_request(baseline=baseline, current=current)

    frames = _run(
        manifest=manifest,
        request=request,
        primary=baseline,
        secondary=current.read_bytes(),
        workspace=workspace,
    )

    assert [frame["frame"] for frame in frames] == [
        "SECONDARY_STAGED",
        "PRIMARY_MOUNT_VERIFIED",
        "FAILED",
    ]
    assert frames[-1]["reason"] == "INSUFFICIENT_COMMON_VALID_COVERAGE"
    assert "aggregate" not in frames[-1]


def test_entrypoint_rejects_pre_report_vertical_mismatch_and_trailing_bytes(tmp_path: Path) -> None:
    primary = tmp_path / "target.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    _write_compound_dsm(primary, np.full((16, 16), 10.0, dtype=np.float32))
    checkpoint_csv = (
        b"checkpoint_id,easting_m,northing_m,elevation_m\n"
        b"a,200000.5,499999.5,10\n"
        b"b,200001.5,499999.5,10\n"
        b"c,200000.5,499998.5,10\n"
    )
    manifest, request = _checkpoint_request(
        primary=primary,
        checkpoint_csv=checkpoint_csv,
        context_vertical_digest="sha256:" + "f" * 64,
    )
    frames = _run(
        manifest=manifest,
        request=request,
        primary=primary,
        secondary=checkpoint_csv,
        workspace=workspace,
    )
    assert frames[-1]["frame"] == "FAILED"
    assert frames[-1]["reason"] == "CHECKPOINT_VERTICAL_REFERENCE_MISMATCH"

    valid_manifest, valid_request = _checkpoint_request(
        primary=primary,
        checkpoint_csv=checkpoint_csv,
    )
    prepare = build_prepare_frame_v2(request=valid_request, manifest=valid_manifest)
    stdin = BytesIO(
        _frame(prepare)
        + _frame(build_secondary_begin_frame(prepare=prepare))
        + checkpoint_csv
        + _frame(build_execute_frame_v2(prepare=prepare))
        + b"trailing"
    )
    stdout = BytesIO()
    with pytest.raises(MeasurementContainerEntrypointError, match="trailing"):
        run_measurement_container_entrypoint(
            stdin=stdin,
            stdout=stdout,
            artifact_path=primary,
            workspace=workspace,
            limits=_limits(),
        )
    assert [frame["frame"] for frame in _decode_frames(stdout)] == [
        "SECONDARY_STAGED",
        "PRIMARY_MOUNT_VERIFIED",
    ]


def test_entrypoint_rejects_secondary_underflow_and_same_size_digest_substitution(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "target.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    _write_compound_dsm(primary, np.full((16, 16), 10.0, dtype=np.float32))
    checkpoint_csv = (
        b"checkpoint_id,easting_m,northing_m,elevation_m\n"
        b"a,200000.5,499999.5,10\n"
        b"b,200001.5,499999.5,10\n"
        b"c,200000.5,499998.5,10\n"
    )
    manifest, request = _checkpoint_request(primary=primary, checkpoint_csv=checkpoint_csv)
    prepare = build_prepare_frame_v2(request=request, manifest=manifest)
    prefix = _frame(prepare) + _frame(build_secondary_begin_frame(prepare=prepare))
    with pytest.raises(MeasurementContainerEntrypointError, match="ended early"):
        run_measurement_container_entrypoint(
            stdin=BytesIO(prefix + checkpoint_csv[:-1]),
            stdout=BytesIO(),
            artifact_path=primary,
            workspace=workspace,
            limits=_limits(),
        )

    substituted = checkpoint_csv.replace(b",10\n", b",11\n", 1)
    stdout = BytesIO()
    run_measurement_container_entrypoint(
        stdin=BytesIO(prefix + substituted + _frame(build_execute_frame_v2(prepare=prepare))),
        stdout=stdout,
        artifact_path=primary,
        workspace=workspace,
        limits=_limits(),
    )
    frames = _decode_frames(stdout)
    assert [frame["frame"] for frame in frames] == ["FAILED"]
    assert frames[-1]["reason"] == "SECONDARY_SPOOL_DIGEST_MISMATCH"


@pytest.mark.parametrize(
    "missing_field",
    (
        "protocolVersion",
        "frame",
        "requestId",
        "attemptNonce",
        "outerCanonicalInputDigest",
        "operation",
        "fence",
        "measurementRequest",
        "executionManifestBody",
        "executionManifestDigest",
        "prepareDigest",
    ),
)
def test_entrypoint_turns_every_missing_prepare_field_into_a_closed_error(
    tmp_path: Path, missing_field: str
) -> None:
    primary = tmp_path / "target.tif"
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    _write_compound_dsm(primary, np.full((16, 16), 10.0, dtype=np.float32))
    manifest, request = measurement_manifest_request()
    prepare = build_prepare_frame_v2(request=request, manifest=manifest)
    malformed = dict(prepare)
    malformed.pop(missing_field)
    if missing_field != "prepareDigest":
        body = {key: value for key, value in malformed.items() if key != "prepareDigest"}
        malformed["prepareDigest"] = _digest_canonical(body)
    stdout = BytesIO()

    with pytest.raises(MeasurementContainerEntrypointError, match="PREPARE_V2"):
        run_measurement_container_entrypoint(
            stdin=BytesIO(_frame(malformed)),
            stdout=stdout,
            artifact_path=primary,
            workspace=workspace,
            limits=_limits(),
        )

    assert stdout.getvalue() == b""


def test_main_returns_closed_failure_without_a_traceback_for_malformed_prepare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, request = measurement_manifest_request()
    prepare = build_prepare_frame_v2(request=request, manifest=manifest)
    prepare.pop("executionManifestBody")
    body = {key: value for key, value in prepare.items() if key != "prepareDigest"}
    prepare["prepareDigest"] = _digest_canonical(body)
    stdout = BytesIO()
    monkeypatch.setattr(
        external_measurement_container_entrypoint.sys,
        "stdin",
        SimpleNamespace(buffer=BytesIO(_frame(prepare))),
    )
    monkeypatch.setattr(
        external_measurement_container_entrypoint.sys,
        "stdout",
        SimpleNamespace(buffer=stdout),
    )

    assert external_measurement_container_entrypoint.main() == 2
    assert stdout.getvalue() == b""


@pytest.mark.parametrize(
    "payload",
    (b"\xff", b'{"x":1e999}', b'{"x":"\\ud800"}', b"[" * 1_100 + b"]" * 1_100),
)
def test_actual_entrypoint_process_closes_malformed_frame_bytes(payload: bytes) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ksi_processing_controller.external_measurement_container_entrypoint",
        ],
        input=len(payload).to_bytes(4, "big") + payload,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == b""
    assert b"Traceback (most recent call last)" not in result.stderr
