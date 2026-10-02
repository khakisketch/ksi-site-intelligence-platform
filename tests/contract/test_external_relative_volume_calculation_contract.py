"""The V2 numeric record keeps raster arithmetic separate from execution state."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_relative_volume_calculation import (
    AnalysisExecutionAttemptV2,
    AnalysisExecutionAuthorizationV2,
    RelativeVolumeCalculationReportV2,
    RelativeVolumeCoverageWitnessV2,
    RelativeVolumeMetricsV2,
    RelativeVolumeNumericResultV2,
)
from pydantic import ValidationError


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _witness() -> RelativeVolumeCoverageWitnessV2:
    # Four selected cells occupy the high four bits of the sole big-endian byte.
    return RelativeVolumeCoverageWitnessV2(
        rows=2,
        columns=2,
        row_offset=0,
        column_offset=0,
        selected_mask_b64="8A==",
        common_valid_mask_b64="8A==",
        unavailable_mask_b64="AA==",
        threshold_excluded_mask_b64="AA==",
        selected_cell_count=4,
        common_valid_cell_count=4,
        unavailable_cell_count=0,
        threshold_excluded_cell_count=0,
        cell_area_m2=1.0,
        selected_area_m2=4.0,
        common_valid_area_m2=4.0,
        bounds=(200000.0, 549998.0, 200002.0, 550000.0),
    ).sealed()


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=1_000_000,
        max_streamed_bytes=1_000_000,
        max_tiff_directories=4,
        max_tiff_entries=64,
        max_pixels=1_000_000,
        max_bands=4,
        max_blocks=128,
        max_decompressed_bytes=10_000_000,
        max_sample_bytes=1_000_000,
        max_geometry_vertices=64,
        max_cpu_seconds=10.0,
        max_memory_bytes=10_000_000,
        max_workspace_bytes=10_000_000,
        max_output_bytes=1_000_000,
        max_tenant_concurrency=2,
        max_queue_depth=4,
        max_deadline_seconds=60.0,
        lease_duration_seconds=10.0,
        max_retry_attempts=2,
    ).sealed()


def test_numeric_result_seals_hand_checked_metrics_and_lossless_coverage() -> None:
    """Changing an arithmetic value or witness bit must invalidate the numeric identity."""
    witness = _witness()
    result = RelativeVolumeNumericResultV2(
        calculation_identity_digest=_digest("calculation"),
        profile_digest=_digest("profile"),
        metrics=RelativeVolumeMetricsV2(
            cut_m3=1.0,
            fill_m3=1.0,
            net_m3=0.0,
            threshold_m=0.0,
            uncertainty_m3=None,
        ),
        coverage=witness,
    ).sealed()

    assert result.numeric_result_identity_digest == result.canonical_digest()
    assert result.coverage.selected_cell_count == 4
    assert result.metrics.net_m3 == 0.0

    changed = result.model_dump(by_alias=True)
    changed["metrics"]["fillM3"] = 2.0
    changed["metrics"]["netM3"] = 1.0
    with pytest.raises(ValueError, match="numeric result identity"):
        RelativeVolumeNumericResultV2.model_validate(changed)


def test_coverage_rejects_padding_and_nonzero_threshold_exclusion() -> None:
    """Padding bits or a fixed-profile excluded cell would make the witness ambiguous."""
    payload = _witness().model_dump(by_alias=True)
    payload["selectedMaskB64"] = "/w=="
    with pytest.raises(ValueError, match="padding"):
        RelativeVolumeCoverageWitnessV2.model_validate(payload)

    payload = _witness().model_dump(by_alias=True)
    payload["thresholdExcludedMaskB64"] = "gA=="
    payload["thresholdExcludedCellCount"] = 1
    with pytest.raises(ValueError, match="threshold"):
        RelativeVolumeCoverageWitnessV2.model_validate(payload)


def test_coverage_rejects_noncanonical_base64_pad_bit_alias() -> None:
    """Equivalent decoded bits still need one canonical witness spelling."""
    payload = _witness().model_dump(by_alias=True)
    payload["selectedMaskB64"] = "8B=="
    payload["coverageWitnessDigest"] = None
    with pytest.raises(ValueError, match="canonical base64"):
        RelativeVolumeCoverageWitnessV2.model_validate(payload)


def test_nested_contract_versions_match_the_published_schema_constants() -> None:
    """Python sealing cannot produce nested versions the schema would reject."""
    witness_payload = _witness().model_dump(by_alias=True)
    witness_payload["contractVersion"] = "other-coverage.v2"
    witness_payload["coverageWitnessDigest"] = None
    with pytest.raises(ValidationError):
        RelativeVolumeCoverageWitnessV2.model_validate(witness_payload)

    numeric = RelativeVolumeNumericResultV2(
        calculation_identity_digest=_digest("calculation"),
        profile_digest=_digest("profile"),
        metrics=RelativeVolumeMetricsV2(
            cut_m3=1.0, fill_m3=1.0, net_m3=0.0, threshold_m=0.0
        ),
        coverage=_witness(),
    ).sealed()
    numeric_payload = numeric.model_dump(by_alias=True)
    numeric_payload["contractVersion"] = "other-result.v2"
    numeric_payload["numericResultIdentityDigest"] = None
    with pytest.raises(ValidationError):
        RelativeVolumeNumericResultV2.model_validate(numeric_payload)


def test_coverage_rejects_nonfinite_area_before_result_sealing() -> None:
    """A nonfinite area cannot become a durable numeric report."""
    payload = _witness().model_dump(by_alias=True)
    payload["cellAreaM2"] = float("inf")
    with pytest.raises(ValidationError):
        RelativeVolumeCoverageWitnessV2.model_validate(payload)


def test_report_binds_fenced_attempt_without_changing_numeric_identity() -> None:
    """Changing the resource/lease wrapper cannot be mistaken for new raster arithmetic."""
    numeric = RelativeVolumeNumericResultV2(
        calculation_identity_digest=_digest("calculation"),
        profile_digest=_digest("profile"),
        metrics=RelativeVolumeMetricsV2(
            cut_m3=1.0, fill_m3=1.0, net_m3=0.0, threshold_m=0.0
        ),
        coverage=_witness(),
    ).sealed()
    authorization = AnalysisExecutionAuthorizationV2(
        authorization_id="authorization-1",
        organization_id="org-a",
        calculation_identity_digest=numeric.calculation_identity_digest,
        admission_digest=_digest("admission"),
        resource_envelope=_envelope(),
        resource_envelope_digest=_envelope().canonical_digest(),
        authorized_at=datetime(2026, 9, 21, tzinfo=UTC),
    ).sealed()
    attempt = AnalysisExecutionAttemptV2(
        attempt_id="attempt-1",
        authorization=authorization,
        authorization_digest=authorization.canonical_digest(),
        worker_instance_id="worker-1",
        lease_acquisition_id="lease-1",
        lease_generation=1,
        issued_at=datetime(2026, 9, 21, tzinfo=UTC),
        lease_expires_at=datetime(2026, 9, 21, 0, 1, tzinfo=UTC),
    ).sealed()
    report = RelativeVolumeCalculationReportV2(
        report_id="report-1",
        attempt=attempt,
        attempt_digest=attempt.canonical_digest(),
        numeric_result=numeric,
        numeric_result_identity_digest=numeric.canonical_digest(),
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    ).sealed()

    assert report.numeric_result.canonical_digest() == numeric.canonical_digest()
    assert report.report_digest == report.canonical_digest()

    tampered = report.model_dump(by_alias=True)
    tampered["attempt"]["authorization"]["resourceEnvelope"]["maxPixels"] = 2
    with pytest.raises(ValueError, match="resource envelope"):
        RelativeVolumeCalculationReportV2.model_validate(tampered)


def test_v2_numeric_schema_requires_fixed_threshold_and_sealed_witness() -> None:
    """Wire clients cannot relax the fixed profile or omit coverage provenance."""
    numeric = RelativeVolumeNumericResultV2(
        calculation_identity_digest=_digest("calculation"),
        profile_digest=_digest("profile"),
        metrics=RelativeVolumeMetricsV2(
            cut_m3=1.0, fill_m3=1.0, net_m3=0.0, threshold_m=0.0
        ),
        coverage=_witness(),
    ).sealed()
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "contracts/schemas/external-relative-volume-calculation.v2.json"
    )
    validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    valid = numeric.model_dump(by_alias=True, mode="json")
    assert not list(validator.iter_errors(valid))

    relaxed = json.loads(json.dumps(valid))
    relaxed["metrics"]["thresholdM"] = 0.1
    assert list(validator.iter_errors(relaxed))
    unsealed = {key: value for key, value in valid.items() if key != "numericResultIdentityDigest"}
    assert list(validator.iter_errors(unsealed))
