"""V2 analysis-policy contracts remain frozen, numeric-free evidence records."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    _observed_vertical_unit,
)
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ObservedVerticalReferenceV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_relative_volume_analysis import (
    AdmissionDispositionV2,
    AdmissionV2,
    AnalysisPolicyV2,
    CalculationIdentityV2,
)
from pydantic import ValidationError


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _canonical_digest(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _policy() -> AnalysisPolicyV2:
    return AnalysisPolicyV2(
        policy_id="relative-volume-v2",
        version=2,
        profile_id="KSI-GIS-RELATIVE-VOLUME-V2",
        profile_digest=_digest("profile"),
        algorithm_digest=_digest("algorithm"),
        config_digest=_digest("config"),
        baseline_grid_rule="BASELINE_NATIVE_NORTH_UP_AFFINE_V1",
        current_elevation_resampling="BILINEAR",
        current_mask_resampling="NEAREST",
        work_area_rasterization="CELL_CENTER",
        minimum_common_valid_fraction=1.0,
        threshold_m=0.0,
        cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
        delta_rule="CURRENT_MINUS_BASELINE",
        uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
    ).sealed()


def _subject(label: str) -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="order-" + label,
        submission_id="submission-" + label,
        revision=1,
        submission_digest=_digest("submission-" + label),
        manifest_digest=_digest("manifest-" + label),
    )


def _identity() -> CalculationIdentityV2:
    vertical = ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")
    return CalculationIdentityV2(
        calculation_id="calculation-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        work_area_polygon={
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]],
        },
        work_area_crs="EPSG:5186",
        work_area_definition_digest=_digest(
            '{"crs":"EPSG:5186","polygon":{"coordinates":[[[0.0,0.0],[0.0,1.0],[1.0,1.0],[0.0,0.0]]],"type":"Polygon"},"workAreaId":"work-area-a"}'
        ),
        baseline_subject=_subject("baseline"),
        current_subject=_subject("current"),
        baseline_capture_started_at=datetime(2026, 9, 19, tzinfo=UTC),
        baseline_capture_ended_at=datetime(2026, 9, 19, 1, tzinfo=UTC),
        current_capture_started_at=datetime(2026, 9, 20, tzinfo=UTC),
        current_capture_ended_at=datetime(2026, 9, 20, 1, tzinfo=UTC),
        baseline_dsm_artifact_id="dsm-baseline",
        current_dsm_artifact_id="dsm-current",
        baseline_input_digest=_digest("baseline-input"),
        current_input_digest=_digest("current-input"),
        baseline_dsm_observed_sha256=_digest("baseline-dsm"),
        current_dsm_observed_sha256=_digest("current-dsm"),
        baseline_dsm_observed_size_bytes=1,
        current_dsm_observed_size_bytes=1,
        baseline_observed_crs_identifier="EPSG:5186",
        current_observed_crs_identifier="EPSG:5186",
        baseline_observed_crs_digest=_digest("horizontal-crs"),
        current_observed_crs_digest=_digest("horizontal-crs"),
        baseline_projected_unit="metre",
        current_projected_unit="metre",
        baseline_vertical_reference=vertical,
        current_vertical_reference=vertical,
        baseline_vertical_reference_digest=vertical.canonical_digest(),
        current_vertical_reference_digest=vertical.canonical_digest(),
        baseline_vertical_unit="metre",
        current_vertical_unit="metre",
        baseline_vertical_unit_provenance="OBSERVED_VERTICAL_CRS_AXIS",
        current_vertical_unit_provenance="OBSERVED_VERTICAL_CRS_AXIS",
        baseline_inspection_report_digest=_digest("baseline-report"),
        current_inspection_report_digest=_digest("current-report"),
        baseline_inspection_policy_digest=_digest("baseline-inspection-policy"),
        current_inspection_policy_digest=_digest("current-inspection-policy"),
        baseline_inspector_build_digest=_digest("baseline-inspector"),
        current_inspector_build_digest=_digest("current-inspector"),
        baseline_transform_digest=_canonical_digest(
            {"transform": [1.0, 0.0, 0.0, 0.0, -1.0, 1.0]}
        ),
        current_transform_digest=_canonical_digest(
            {"transform": [1.0, 0.0, 0.0, 0.0, -1.0, 1.0]}
        ),
        baseline_transform=(1.0, 0.0, 0.0, 0.0, -1.0, 1.0),
        current_transform=(1.0, 0.0, 0.0, 0.0, -1.0, 1.0),
        horizontal_crs_digest=_digest("horizontal-crs"),
        vertical_reference_digest=vertical.canonical_digest(),
        policy=_policy(),
        worker_executable_digest=_digest("worker"),
        worker_build_digest=_digest("build"),
        runtime_image_version="2.0.0",
        runtime_image_oci_digest=_digest("oci"),
        dependency_lock_digest=_digest("lock"),
    ).sealed()


def test_v2_admission_is_digest_bound_and_cannot_carry_a_volume_number() -> None:
    """Adding a numeric result or changing frozen provenance must fail closed."""
    identity = _identity()
    admission = AdmissionV2(
        admission_id="admission-1",
        calculation_identity=identity,
        evaluation_revisions=(),
        disposition=AdmissionDispositionV2.ADMIT_PROVISIONAL,
        reason_codes=("CHECKPOINT_EVIDENCE_ABSENT",),
        assessed_at=datetime(2026, 9, 20, tzinfo=UTC),
    ).sealed()

    assert admission.calculation_identity_digest == identity.canonical_digest()
    assert "netM3" not in admission.model_dump(by_alias=True)

    with pytest.raises(ValidationError, match="extra"):
        AdmissionV2.model_validate(
            {
                **admission.model_dump(by_alias=True),
                "netM3": 12.5,
            }
        )

    with pytest.raises(ValueError, match="identity digest"):
        CalculationIdentityV2.model_validate(
            {
                **identity.model_dump(by_alias=True),
                "runtimeImageVersion": "2.0.1",
            }
        )


def test_v2_profile_rejects_a_relaxed_coverage_or_nonzero_threshold() -> None:
    """A caller cannot silently change the fixed first-profile semantics."""
    payload = _policy().model_dump(by_alias=True)
    payload["minimumCommonValidFraction"] = 0.99
    with pytest.raises(ValueError, match="100%"):
        AnalysisPolicyV2.model_validate(payload)

    payload = _policy().model_dump(by_alias=True)
    payload["thresholdM"] = 0.01
    with pytest.raises(ValueError, match="zero"):
        AnalysisPolicyV2.model_validate(payload)


def test_v2_schema_rejects_relaxed_fixed_profile_values() -> None:
    """Schema consumers receive the same non-relaxable profile bounds as Python."""
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "contracts/schemas/external-relative-volume-analysis.v2.json"
    )
    validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    valid = _policy().model_dump(by_alias=True, mode="json")
    assert not list(validator.iter_errors(valid))

    relaxed_coverage = {**valid, "minimumCommonValidFraction": 0.99}
    assert list(validator.iter_errors(relaxed_coverage))
    relaxed_threshold = {**valid, "thresholdM": 0.001}
    assert list(validator.iter_errors(relaxed_threshold))


def test_v2_schema_requires_sealed_digests_and_zulu_timestamps() -> None:
    """Wire clients cannot submit an unsealed identity or offset timestamp."""
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "contracts/schemas/external-relative-volume-analysis.v2.json"
    )
    validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    valid = _identity().model_dump(by_alias=True, mode="json")
    assert not list(validator.iter_errors(valid))

    missing_digest = {key: value for key, value in valid.items() if key != "currentInputDigest"}
    assert list(validator.iter_errors(missing_digest))
    offset_time = {**valid, "currentCaptureStartedAt": "2026-09-20T00:00:00+09:00"}
    assert list(validator.iter_errors(offset_time))


def test_vertical_unit_requires_the_parser_observed_vertical_epsg_axis() -> None:
    """Free-text, wrong-basis, and foot-axis references cannot become metres."""
    assert _observed_vertical_unit(
        ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")
    ) == ("metre", "OBSERVED_VERTICAL_CRS_AXIS")
    assert _observed_vertical_unit(
        ObservedVerticalReferenceV1(identifier="KNGeoid2018", basis="site datum")
    ) is None
    assert _observed_vertical_unit(
        ObservedVerticalReferenceV1(identifier="EPSG:6360", basis="NAVD88 height (ftUS)")
    ) is None
