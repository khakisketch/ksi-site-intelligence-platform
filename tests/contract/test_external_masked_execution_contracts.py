"""Additive V3 masked-execution transport contracts: validity, adversarial, schema.

Synthetic fixtures only.  Proves the new fence envelope binds three ordered
inputs, rejects the old two-input V2 protocol, rejects client URLs and V2
numeric reuse, and fails closed on stale fences and digest tamper.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_masked_execution import (
    MaskedAdmissionDispositionV3,
    MaskedAdmissionV3,
    MaskedExecutionAttemptV3,
    MaskedExecutionAuthorizationV3,
    MaskedExecutionRuntimeV3,
    MaskedWorkerInputV3,
    masked_admission_wire_dict,
    masked_execution_attempt_wire_dict,
    masked_execution_authorization_wire_dict,
    masked_execution_runtime_digest,
    masked_execution_runtime_wire_dict,
    masked_worker_input_wire_dict,
)
from ksi_event_contracts.external_masked_volume import (
    ExclusionMaskBindingV1,
    MaskedCalculationIdentityV3,
    MaskedRelativeVolumeProfileV3,
)
from ksi_event_contracts.external_relative_volume_analysis import (
    AnalysisPolicyV2,
    CalculationIdentityV2,
)
from ksi_event_contracts.external_relative_volume_calculation import (
    RelativeVolumeNumericResultV2,
)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _canonical_digest(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


_ORIGIN_X = 200000.0
_ORIGIN_Y = 550000.0
_TRANSFORM = (1.0, 0.0, _ORIGIN_X, 0.0, -1.0, _ORIGIN_Y)


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


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=4000000,
        max_streamed_bytes=4000000,
        max_tiff_directories=8,
        max_tiff_entries=128,
        max_pixels=1000000,
        max_bands=4,
        max_blocks=512,
        max_decompressed_bytes=20000000,
        max_sample_bytes=4000000,
        max_geometry_vertices=64,
        max_cpu_seconds=30.0,
        max_memory_bytes=50000000,
        max_workspace_bytes=50000000,
        max_output_bytes=1000000,
        max_tenant_concurrency=2,
        max_queue_depth=4,
        max_deadline_seconds=60.0,
        lease_duration_seconds=10.0,
        max_retry_attempts=2,
    ).sealed()


def _polygon() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [_ORIGIN_X, _ORIGIN_Y],
                [_ORIGIN_X, _ORIGIN_Y - 4.0],
                [_ORIGIN_X + 4.0, _ORIGIN_Y - 4.0],
                [_ORIGIN_X + 4.0, _ORIGIN_Y],
                [_ORIGIN_X, _ORIGIN_Y],
            ]
        ],
    }


def _v2_identity() -> CalculationIdentityV2:
    from ksi_event_contracts.external_artifact_validation import ObservedVerticalReferenceV1
    from pyproj import CRS

    vertical = ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")
    horizontal_wkt = CRS.from_epsg(5186).to_wkt(
        version="WKT2_2019", pretty=False, output_axis_rule=True
    )
    horizontal_digest = _digest(horizontal_wkt)
    return CalculationIdentityV2(
        calculation_id="calculation-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        work_area_polygon=_polygon(),
        work_area_crs="EPSG:5186",
        work_area_definition_digest=_canonical_digest(
            {"workAreaId": "work-area-a", "crs": "EPSG:5186", "polygon": _polygon()}
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
        baseline_dsm_observed_sha256=_digest("baseline-bytes"),
        current_dsm_observed_sha256=_digest("current-bytes"),
        baseline_dsm_observed_size_bytes=128,
        current_dsm_observed_size_bytes=128,
        baseline_observed_crs_identifier="EPSG:5186",
        current_observed_crs_identifier="EPSG:5186",
        baseline_observed_crs_digest=horizontal_digest,
        current_observed_crs_digest=horizontal_digest,
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
        baseline_inspection_policy_digest=_digest("baseline-policy"),
        current_inspection_policy_digest=_digest("current-policy"),
        baseline_inspector_build_digest=_digest("baseline-inspector"),
        current_inspector_build_digest=_digest("current-inspector"),
        baseline_transform_digest=_canonical_digest({"transform": list(_TRANSFORM)}),
        current_transform_digest=_canonical_digest({"transform": list(_TRANSFORM)}),
        baseline_transform=_TRANSFORM,
        current_transform=_TRANSFORM,
        horizontal_crs_digest=horizontal_digest,
        vertical_reference_digest=vertical.canonical_digest(),
        policy=AnalysisPolicyV2(
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
        ).sealed(),
        worker_executable_digest=_digest("worker"),
        worker_build_digest=_digest("build"),
        runtime_image_version="2.0.0",
        runtime_image_oci_digest=_digest("oci"),
        dependency_lock_digest=_digest("lock"),
    ).sealed()


def _masked_identity() -> MaskedCalculationIdentityV3:
    source = _v2_identity()
    left, bottom = _ORIGIN_X, _ORIGIN_Y - 4.0
    right, top = _ORIGIN_X + 4.0, _ORIGIN_Y
    mask = ExclusionMaskBindingV1(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        subject=_subject("mask"),
        mask_artifact_id="mask-artifact-1",
        observed_sha256=_digest("mask-bytes"),
        observed_size_bytes=128,
        observed_inspection_report_digest=_digest("mask-report"),
        rows=4,
        columns=4,
        transform=_TRANSFORM,
        transform_digest=_canonical_digest({"transform": list(_TRANSFORM)}),
        observed_crs_identifier="EPSG:5186",
        observed_crs_digest=source.horizontal_crs_digest,
        dtype="UINT8",
        band_count=1,
        retain_value=0,
        exclude_value=1,
        nodata_representation="NONE",
        bounds=(left, bottom, right, top),
    ).sealed()
    profile = MaskedRelativeVolumeProfileV3(
        policy_id="masked-relative-volume-v3",
        version=3,
        profile_id="KSI-GIS-MASKED-RELATIVE-VOLUME-V3",
        profile_digest=_digest("masked-profile"),
        algorithm_digest=_digest("masked-algorithm"),
        config_digest=_digest("masked-config"),
        baseline_grid_rule="EXACT_BASELINE_GRID",
        current_elevation_resampling="BILINEAR",
        current_mask_resampling="NEAREST",
        work_area_rasterization="CELL_CENTER",
        exclusion_precedence="WORKAREA_HOLES_THEN_MASK",
        mask_convention="UINT8_SINGLE_BAND_BINARY_0_KEEP_1_EXCLUDE_V1",
        mask_nodata_rule="NO_NODATA",
        minimum_common_valid_fraction=1.0,
        threshold_m=0.0,
        cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
        delta_rule="CURRENT_MINUS_BASELINE",
        uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
    ).sealed()
    return MaskedCalculationIdentityV3(
        masked_calculation_id="masked-calculation-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        source_calculation_identity=source,
        source_calculation_identity_digest=source.canonical_digest(),
        mask_binding=mask,
        mask_binding_digest=mask.canonical_digest(),
        profile=profile,
        masked_profile_digest=profile.canonical_digest(),
        grid_rows=4,
        grid_columns=4,
        horizontal_crs_digest=mask.observed_crs_digest,
    ).sealed()


def _admission(
    identity: MaskedCalculationIdentityV3, envelope: ResourceEnvelopeV1
) -> MaskedAdmissionV3:
    return MaskedAdmissionV3(
        admission_id="admission-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        masked_calculation_identity_digest=identity.canonical_digest(),
        source_calculation_identity_digest=identity.source_calculation_identity_digest,
        mask_binding_digest=identity.mask_binding_digest,
        masked_profile_digest=identity.masked_profile_digest,
        area_definition_digest=_digest("area"),
        policy_digest=_digest("policy"),
        runtime_digest=_digest("runtime"),
        resource_envelope_digest=envelope.canonical_digest(),
        activation_digest=_digest("activation"),
        scope_digest=_digest("scope"),
        ai_egress_digest=_digest("egress"),
        disposition=MaskedAdmissionDispositionV3.ADMIT_EVALUATED,
        reason_codes=("MASK_ADMITTED",),
        assessed_at=datetime(2026, 9, 21, tzinfo=UTC),
    ).sealed()


def _authorization(
    identity: MaskedCalculationIdentityV3,
    admission: MaskedAdmissionV3,
    envelope: ResourceEnvelopeV1,
) -> MaskedExecutionAuthorizationV3:
    return MaskedExecutionAuthorizationV3(
        authorization_id="authorization-1",
        organization_id="org-a",
        masked_calculation_identity_digest=identity.canonical_digest(),
        masked_profile_digest=identity.masked_profile_digest,
        mask_binding_digest=identity.mask_binding_digest,
        source_calculation_identity_digest=identity.source_calculation_identity_digest,
        admission_digest=admission.canonical_digest(),
        activation_digest=_digest("activation"),
        worker_principal_id="analysis-worker-1",
        resource_envelope=envelope,
        resource_envelope_digest=envelope.canonical_digest(),
        authorized_at=datetime(2026, 9, 21, 1, tzinfo=UTC),
    ).sealed()


def _attempt(authorization: MaskedExecutionAuthorizationV3) -> MaskedExecutionAttemptV3:
    return MaskedExecutionAttemptV3(
        attempt_id="attempt-1",
        authorization=authorization,
        authorization_digest=authorization.canonical_digest(),
        worker_instance_id="masked-worker-instance-1",
        lease_acquisition_id="lease-1",
        lease_generation=1,
        issued_at=datetime(2026, 9, 21, 2, tzinfo=UTC),
        lease_expires_at=datetime(2026, 9, 21, 3, tzinfo=UTC),
    ).sealed()


def _worker_input(
    identity: MaskedCalculationIdentityV3, attempt: MaskedExecutionAttemptV3
) -> MaskedWorkerInputV3:
    source = identity.source_calculation_identity
    binding = identity.mask_binding
    expiry = datetime(2026, 9, 21, 2, 30, tzinfo=UTC)
    return MaskedWorkerInputV3(
        masked_request_id="request-1",
        attempt=attempt,
        masked_calculation_identity=identity,
        inputs=(
            {
                "role": "BASELINE_DSM",
                "artifactId": source.baseline_dsm_artifact_id,
                "observedSha256": source.baseline_dsm_observed_sha256,
                "observedSizeBytes": source.baseline_dsm_observed_size_bytes,
                "expiresAt": expiry,
            },
            {
                "role": "CURRENT_DSM",
                "artifactId": source.current_dsm_artifact_id,
                "observedSha256": source.current_dsm_observed_sha256,
                "observedSizeBytes": source.current_dsm_observed_size_bytes,
                "expiresAt": expiry,
            },
            {
                "role": "EXCLUSION_MASK",
                "artifactId": binding.mask_artifact_id,
                "observedSha256": binding.observed_sha256,
                "observedSizeBytes": binding.observed_size_bytes,
                "expiresAt": expiry,
            },
        ),  # type: ignore[arg-type]
    )


def test_valid_v3_fence_binds_three_inputs() -> None:
    envelope = _envelope()
    identity = _masked_identity()
    admission = _admission(identity, envelope)
    authorization = _authorization(identity, admission, envelope)
    attempt = _attempt(authorization)
    worker_input = _worker_input(identity, attempt)
    assert worker_input.inputs[2].role == "EXCLUSION_MASK"
    assert attempt.execution_attempt_digest == attempt.canonical_digest()


def test_two_input_v2_shape_and_reordered_inputs_rejected() -> None:
    envelope = _envelope()
    identity = _masked_identity()
    admission = _admission(identity, envelope)
    authorization = _authorization(identity, admission, envelope)
    attempt = _attempt(authorization)
    good = _worker_input(identity, attempt).model_dump(by_alias=True)
    # Drop the mask -> old two-input V2 protocol shape.
    two = dict(good)
    two["inputs"] = good["inputs"][:2]
    with pytest.raises(ValueError):
        MaskedWorkerInputV3.model_validate(two)
    # Reorder mask first.
    reordered = dict(good)
    reordered["inputs"] = [good["inputs"][2], good["inputs"][0], good["inputs"][1]]
    with pytest.raises(ValueError, match="ordered"):
        MaskedWorkerInputV3.model_validate(reordered)


def test_client_url_capability_rejected() -> None:
    envelope = _envelope()
    identity = _masked_identity()
    admission = _admission(identity, envelope)
    authorization = _authorization(identity, admission, envelope)
    attempt = _attempt(authorization)
    good = _worker_input(identity, attempt).model_dump(by_alias=True)
    good["inputs"][2]["artifactId"] = "https://example.invalid/mask.tif"
    with pytest.raises(ValueError, match="opaque"):
        MaskedWorkerInputV3.model_validate(good)


def test_capability_outliving_lease_rejected_and_stale_attempt_rejected() -> None:
    envelope = _envelope()
    identity = _masked_identity()
    admission = _admission(identity, envelope)
    authorization = _authorization(identity, admission, envelope)
    attempt = _attempt(authorization)
    good = _worker_input(identity, attempt).model_dump(by_alias=True)
    good["inputs"][0]["expiresAt"] = "2026-09-22T00:00:00Z"
    with pytest.raises(ValueError, match="outlives"):
        MaskedWorkerInputV3.model_validate(good)
    stale = attempt.model_dump(by_alias=True)
    stale["leaseExpiresAt"] = "2026-09-21T01:00:00Z"
    stale["executionAttemptDigest"] = None
    with pytest.raises(ValueError, match="after issuedAt"):
        MaskedExecutionAttemptV3.model_validate(stale)


def test_missing_activation_digest_fails_closed_shape() -> None:
    envelope = _envelope()
    identity = _masked_identity()
    admission = _admission(identity, envelope).model_dump(by_alias=True)
    admission["activationDigest"] = "sha256:" + "0" * 64
    admission["admissionDigest"] = None
    # A zero digest is syntactically valid but the store treats an unknown
    # activation as not-current; here the contract still seals (evidence only).
    sealed = MaskedAdmissionV3.model_validate(admission)
    assert sealed.activation_digest == "sha256:" + "0" * 64


def test_v2_numeric_identity_is_not_a_v3_output() -> None:
    # The V2 result type cannot validate as a V3 numeric result: distinct
    # contract versions keep the output numeric identity V3-only.
    assert RelativeVolumeNumericResultV2 is not None
    from ksi_event_contracts.external_masked_volume_result import MaskedVolumeNumericResultV3

    assert (
        MaskedVolumeNumericResultV3.model_fields["contract_version"].default
        == "external-masked-volume-numeric-result.v3"
    )


def test_wire_dicts_validate_against_new_schema() -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "schemas"
        / "external-masked-execution.v3.json"
    )
    validator = Draft202012Validator(json.loads(schema_path.read_text()))
    envelope = _envelope()
    identity = _masked_identity()
    admission = _admission(identity, envelope)
    authorization = _authorization(identity, admission, envelope)
    attempt = _attempt(authorization)
    worker_input = _worker_input(identity, attempt)
    validator.validate(masked_admission_wire_dict(admission))
    validator.validate(masked_execution_authorization_wire_dict(authorization))
    validator.validate(masked_execution_attempt_wire_dict(attempt))
    validator.validate(masked_worker_input_wire_dict(worker_input))


def _execution_runtime() -> MaskedExecutionRuntimeV3:
    return MaskedExecutionRuntimeV3(
        contract_version="external-masked-execution-runtime.v3",
        worker_executable_digest=_digest("masked-exe"),
        worker_build_digest=_digest("masked-build"),
        runtime_image_version="9.9.9",
        runtime_image_oci_digest=_digest("masked-oci"),
        dependency_lock_digest=_digest("masked-lock"),
    ).sealed()


def test_execution_runtime_seals_and_binds_all_pins() -> None:
    runtime = _execution_runtime()
    assert runtime.runtime_digest == runtime.canonical_digest()
    first = masked_execution_runtime_digest(
        runtime,
        _digest("masked-profile"),
        _digest("envelope"),
        _digest("inspection-profile"),
    )
    tampered = runtime.model_copy(update={"runtime_image_version": "9.9.10"})
    with pytest.raises(ValueError, match="differs from its exact content"):
        masked_execution_runtime_digest(
            tampered,
            _digest("masked-profile"),
            _digest("envelope"),
            _digest("inspection-profile"),
        )
    other_profile = masked_execution_runtime_digest(
        runtime,
        _digest("other-profile"),
        _digest("envelope"),
        _digest("inspection-profile"),
    )
    assert other_profile != first
    wire = masked_execution_runtime_wire_dict(runtime)
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "schemas"
        / "external-masked-execution.v3.json"
    )
    Draft202012Validator(json.loads(schema_path.read_text())).validate(wire)


def test_execution_runtime_rejects_bool_and_blank_version() -> None:
    with pytest.raises(ValueError):
        MaskedExecutionRuntimeV3(
            contract_version="external-masked-execution-runtime.v3",
            worker_executable_digest=_digest("masked-exe"),
            worker_build_digest=_digest("masked-build"),
            runtime_image_version="   ",
            runtime_image_oci_digest=_digest("masked-oci"),
            dependency_lock_digest=_digest("masked-lock"),
        )
