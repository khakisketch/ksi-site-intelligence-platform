"""Additive masked-volume contracts: independent mask binding, fixed profile, identity, output."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ObservedVerticalReferenceV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_masked_volume import (
    DeltaRasterPublicationV1,
    ExclusionMaskBindingV1,
    MaskedCalculationIdentityV3,
    MaskedRelativeVolumeProfileV3,
    delta_raster_publication_wire_dict,
    exclusion_mask_binding_wire_dict,
    masked_calculation_identity_wire_dict,
    masked_relative_volume_profile_wire_dict,
)
from ksi_event_contracts.external_relative_volume_analysis import (
    AnalysisPolicyV2,
    CalculationIdentityV2,
)
from pydantic import ValidationError


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _canonical_digest(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


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


def _v2_policy() -> AnalysisPolicyV2:
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


def _v2_identity() -> CalculationIdentityV2:
    vertical = ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")
    polygon = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]],
    }
    return CalculationIdentityV2(
        calculation_id="calculation-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        work_area_polygon=polygon,
        work_area_crs="EPSG:5186",
        work_area_definition_digest=_canonical_digest(
            {"workAreaId": "work-area-a", "crs": "EPSG:5186", "polygon": polygon}
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
            {"transform": [1.0, 0.0, 100.0, 0.0, -1.0, 200.0]}
        ),
        current_transform_digest=_canonical_digest(
            {"transform": [1.0, 0.0, 100.0, 0.0, -1.0, 200.0]}
        ),
        baseline_transform=(1.0, 0.0, 100.0, 0.0, -1.0, 200.0),
        current_transform=(1.0, 0.0, 100.0, 0.0, -1.0, 200.0),
        horizontal_crs_digest=_digest("horizontal-crs"),
        vertical_reference_digest=vertical.canonical_digest(),
        policy=_v2_policy(),
        worker_executable_digest=_digest("worker"),
        worker_build_digest=_digest("build"),
        runtime_image_version="2.0.0",
        runtime_image_oci_digest=_digest("oci"),
        dependency_lock_digest=_digest("lock"),
    ).sealed()


def _mask() -> ExclusionMaskBindingV1:
    return ExclusionMaskBindingV1(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        subject=_subject("mask"),
        mask_artifact_id="mask-artifact-1",
        observed_sha256=_digest("mask-bytes"),
        observed_size_bytes=16,
        observed_inspection_report_digest=_digest("mask-report"),
        rows=4,
        columns=4,
        transform=(1.0, 0.0, 100.0, 0.0, -1.0, 200.0),
        transform_digest=_canonical_digest({"transform": [1.0, 0.0, 100.0, 0.0, -1.0, 200.0]}),
        observed_crs_identifier="EPSG:5186",
        observed_crs_digest=_digest("horizontal-crs"),
        dtype="UINT8",
        band_count=1,
        retain_value=0,
        exclude_value=1,
        nodata_representation="NONE",
        bounds=(100.0, 196.0, 104.0, 200.0),
    ).sealed()


def _profile() -> MaskedRelativeVolumeProfileV3:
    return MaskedRelativeVolumeProfileV3(
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


def _masked_identity() -> MaskedCalculationIdentityV3:
    source = _v2_identity()
    mask = _mask()
    profile = _profile()
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
        horizontal_crs_digest=_digest("horizontal-crs"),
    ).sealed()


def _publication() -> DeltaRasterPublicationV1:
    return DeltaRasterPublicationV1(
        publication_id="publication-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        source_contract_version="external-masked-volume-calculation-identity.v3",
        source_calculation_identity_digest=_masked_identity().canonical_digest(),
        source_numeric_result_identity_digest=_digest("numeric"),
        source_coverage_witness_digest=_digest("coverage"),
        delta_sign="CURRENT_MINUS_BASELINE",
        grid_rows=4,
        grid_columns=4,
        transform=(1.0, 0.0, 100.0, 0.0, -1.0, 200.0),
        transform_digest=_canonical_digest({"transform": [1.0, 0.0, 100.0, 0.0, -1.0, 200.0]}),
        grid_crs_identifier="EPSG:5186",
        grid_crs_digest=_digest("horizontal-crs"),
        bounds=(100.0, 196.0, 104.0, 200.0),
        vertical_unit="metre",
        dtype="FLOAT64",
        output_id="protected-output-01",
        output_sha256=_digest("output-bytes"),
        output_size_bytes=1024,
        issued_at=datetime(2026, 10, 1, tzinfo=UTC),
        expires_at=datetime(2026, 11, 1, tzinfo=UTC),
        publication_policy_digest=_digest("publication-policy"),
    ).sealed()


def _resealed_mask(**overrides: object) -> dict[str, object]:
    """Return a sealed mask wire dict with overrides applied before sealing."""
    payload = _mask().model_dump(by_alias=True, mode="json")
    payload.update(overrides)
    payload["maskBindingDigest"] = None
    sealed = ExclusionMaskBindingV1.model_validate(payload).sealed()
    return sealed.model_dump(by_alias=True, mode="json")


def _schema_validator() -> Draft202012Validator:
    schema_path = (
        Path(__file__).resolve().parents[2] / "contracts/schemas/external-masked-volume.v3.json"
    )
    return Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))


def test_mask_binding_seals_and_digest_mutation_fails_closed() -> None:
    """Changing observed mask bytes or size must invalidate the sealed binding."""
    mask = _mask()
    assert mask.mask_binding_digest == mask.canonical_digest()

    tampered = mask.model_dump(by_alias=True)
    tampered["observedSha256"] = _digest("other-mask-bytes")
    with pytest.raises(ValidationError, match="mask binding digest"):
        ExclusionMaskBindingV1.model_validate(tampered)


def test_mask_binding_rejects_unknown_fields_and_malformed_digest() -> None:
    """Closed shape: no extra fields, no malformed digest escapes validation."""
    payload = _mask().model_dump(by_alias=True)
    payload["userDeclaredInspection"] = "ELIGIBLE"
    with pytest.raises(ValidationError):
        ExclusionMaskBindingV1.model_validate(payload)

    payload = _mask().model_dump(by_alias=True)
    payload["observedSha256"] = "not-a-digest"
    payload["maskBindingDigest"] = None
    with pytest.raises(ValidationError):
        ExclusionMaskBindingV1.model_validate(payload)


def test_mask_binding_rejects_nonfinite_transform_and_unordered_bounds() -> None:
    """Non-finite affine values or unordered bounds cannot become a sealed binding."""
    payload = _mask().model_dump(by_alias=True)
    payload["transform"] = [float("inf"), 0.0, 100.0, 0.0, -1.0, 200.0]
    payload["maskBindingDigest"] = None
    with pytest.raises(ValidationError):
        ExclusionMaskBindingV1.model_validate(payload)

    payload = _mask().model_dump(by_alias=True)
    payload["bounds"] = [104.0, 196.0, 100.0, 200.0]
    payload["maskBindingDigest"] = None
    with pytest.raises(ValidationError, match="bounds"):
        ExclusionMaskBindingV1.model_validate(payload)


def test_mask_binding_rejects_scope_mismatch_and_nodata_convention() -> None:
    """The mask subject must bind the declared scope; NoData is a blocker, not a value."""
    payload = _mask().model_dump(by_alias=True)
    payload["organizationId"] = "org-other"
    payload["maskBindingDigest"] = None
    with pytest.raises(ValidationError, match="organization and site"):
        ExclusionMaskBindingV1.model_validate(payload)

    payload = _mask().model_dump(by_alias=True)
    payload["nodataRepresentation"] = "MASK"
    payload["maskBindingDigest"] = None
    with pytest.raises(ValidationError):
        ExclusionMaskBindingV1.model_validate(payload)


def test_masked_profile_seals_fixed_policy_without_authorization_claim() -> None:
    """The sealed profile pins the fixed masked mathematics and carries no admission."""
    profile = _profile()
    assert profile.masked_profile_digest == profile.canonical_digest()
    assert profile.profile_id == "KSI-GIS-MASKED-RELATIVE-VOLUME-V3"
    assert "admission" not in profile.model_dump(by_alias=True, mode="json")
    assert "authorization" not in json.dumps(profile.model_dump(by_alias=True, mode="json")).lower()

    payload = profile.model_dump(by_alias=True)
    payload["minimumCommonValidFraction"] = 0.99
    payload["maskedProfileDigest"] = None
    with pytest.raises(ValidationError, match="100% common valid"):
        MaskedRelativeVolumeProfileV3.model_validate(payload)

    payload = profile.model_dump(by_alias=True)
    payload["thresholdM"] = 0.1
    payload["maskedProfileDigest"] = None
    with pytest.raises(ValidationError, match="zero threshold"):
        MaskedRelativeVolumeProfileV3.model_validate(payload)


def test_masked_identity_binds_sealed_source_mask_and_profile() -> None:
    """Unsealed parts or a tampered source digest cannot become a masked identity."""
    identity = _masked_identity()
    assert identity.masked_calculation_identity_digest == identity.canonical_digest()
    assert identity.masked_calculation_identity_digest != (
        identity.source_calculation_identity.canonical_digest()
    )

    tampered = identity.model_dump(by_alias=True)
    tampered["sourceCalculationIdentityDigest"] = _digest("other-calculation")
    with pytest.raises(ValidationError, match="source calculation identity digest"):
        MaskedCalculationIdentityV3.model_validate(tampered)


def test_masked_identity_rejects_scope_transform_and_dimension_mismatch() -> None:
    """Organization/site/area, baseline-grid binding, and dimensions must match exactly."""
    payload = _masked_identity().model_dump(by_alias=True)
    payload["workAreaId"] = "work-area-other"
    payload["maskedCalculationIdentityDigest"] = None
    with pytest.raises(ValidationError, match="organization, site, and work area"):
        MaskedCalculationIdentityV3.model_validate(payload)

    rotated_mask = _resealed_mask(
        transform=[2.0, 0.0, 100.0, 0.0, -1.0, 200.0],
        transformDigest=_canonical_digest({"transform": [2.0, 0.0, 100.0, 0.0, -1.0, 200.0]}),
        bounds=[100.0, 196.0, 108.0, 200.0],
    )
    payload = _masked_identity().model_dump(by_alias=True)
    payload["maskBinding"] = rotated_mask
    payload["maskBindingDigest"] = rotated_mask["maskBindingDigest"]
    payload["maskedCalculationIdentityDigest"] = None
    with pytest.raises(ValidationError, match="exact baseline transform"):
        MaskedCalculationIdentityV3.model_validate(payload)

    payload = _masked_identity().model_dump(by_alias=True)
    payload["gridRows"] = 8
    payload["maskedCalculationIdentityDigest"] = None
    with pytest.raises(ValidationError, match="sealed mask dimensions"):
        MaskedCalculationIdentityV3.model_validate(payload)


def test_masked_identity_rejects_cross_field_permutation() -> None:
    """Swapped org/site/area with an identical set must not bind the source grid.

    The previous set-based scope check accepted any permutation of the three
    scope values; ordered tuple equality rejects it.
    """
    payload = _masked_identity().model_dump(by_alias=True, mode="json")
    payload["organizationId"] = "site-a"
    payload["siteId"] = "work-area-a"
    payload["workAreaId"] = "org-a"
    assert set(payload[k] for k in ("organizationId", "siteId", "workAreaId")) == {
        "org-a",
        "site-a",
        "work-area-a",
    }
    payload["maskedCalculationIdentityDigest"] = None
    with pytest.raises(ValidationError, match="in order"):
        MaskedCalculationIdentityV3.model_validate(payload)


def test_mask_binding_rejects_bool_and_string_numeric_coercion() -> None:
    """Booleans and strings must never bless mask literals, thresholds, or affines."""
    for field, value in (
        ("retainValue", True),
        ("excludeValue", False),
        ("bandCount", True),
    ):
        payload = _mask().model_dump(by_alias=True, mode="json")
        payload[field] = value
        payload["maskBindingDigest"] = None
        with pytest.raises(ValidationError, match="boolean is not an integer literal"):
            ExclusionMaskBindingV1.model_validate(payload)

    for value in (True, "0.0"):
        payload = _profile().model_dump(by_alias=True, mode="json")
        payload["thresholdM"] = value
        payload["maskedProfileDigest"] = None
        with pytest.raises(ValidationError):
            MaskedRelativeVolumeProfileV3.model_validate(payload)

    # Integer wire spellings normalize to the same canonical float identity
    # (StrictFloat coerces int to float before digesting), so only bool/str
    # coercion is rejected above; ints cannot bless a distinct identity.
    assert (
        _mask().canonical_digest()
        == ExclusionMaskBindingV1.model_validate(
            {
                **_mask().model_dump(by_alias=True, mode="json"),
                "transform": [1, 0, 100, 0, -1, 200],
                "maskBindingDigest": None,
            }
        ).canonical_digest()
    )


def test_mask_grid_must_be_native_north_up_with_matching_bounds() -> None:
    """Rotated, south-up, or bounds-mismatched grids cannot become a sealed binding."""
    rotated = [1.0, 0.5, 100.0, 0.5, -1.0, 200.0]
    payload = _mask().model_dump(by_alias=True, mode="json")
    payload["transform"] = rotated
    payload["transformDigest"] = _canonical_digest({"transform": rotated})
    payload["maskBindingDigest"] = None
    with pytest.raises(ValidationError, match="without rotation"):
        ExclusionMaskBindingV1.model_validate(payload)

    south_up = [1.0, 0.0, 100.0, 0.0, 1.0, 196.0]
    payload = _mask().model_dump(by_alias=True, mode="json")
    payload["transform"] = south_up
    payload["transformDigest"] = _canonical_digest({"transform": south_up})
    payload["maskBindingDigest"] = None
    with pytest.raises(ValidationError, match="negative northward"):
        ExclusionMaskBindingV1.model_validate(payload)

    payload = _mask().model_dump(by_alias=True, mode="json")
    payload["bounds"] = [100.0, 196.0, 104.0, 201.0]
    payload["maskBindingDigest"] = None
    with pytest.raises(ValidationError, match="rows/columns affine extent"):
        ExclusionMaskBindingV1.model_validate(payload)

    payload = _publication().model_dump(by_alias=True, mode="json")
    payload["bounds"] = [100.0, 196.0, 104.0, 201.0]
    payload["publicationDigest"] = None
    with pytest.raises(ValidationError, match="rows/columns affine extent"):
        DeltaRasterPublicationV1.model_validate(payload)


def test_masked_identity_rejects_crs_identifier_mismatch() -> None:
    """The mask CRS identifier must match the source baseline identifier, not just its digest."""
    payload = _masked_identity().model_dump(by_alias=True, mode="json")
    resealed = _resealed_mask(observedCrsIdentifier="EPSG:5187")
    payload["maskBinding"] = resealed
    payload["maskBindingDigest"] = resealed["maskBindingDigest"]
    payload["maskedCalculationIdentityDigest"] = None
    with pytest.raises(ValidationError, match="CRS identifier"):
        MaskedCalculationIdentityV3.model_validate(payload)


def test_publication_rejects_non_opaque_output_ids() -> None:
    """Relative slashes, colons, dot-dot, URLs, and spaces are never output ids."""
    for output_id in (
        "abc/def",
        "out:01",
        "a..b",
        "..",
        "https://example.invalid/o.tif",
        "out tif",
        "",
    ):
        payload = _publication().model_dump(by_alias=True, mode="json")
        payload["outputId"] = output_id
        payload["publicationDigest"] = None
        with pytest.raises(ValidationError):
            DeltaRasterPublicationV1.model_validate(payload)


def test_masked_identity_treats_v2_policy_as_source_evidence_only() -> None:
    """The embedded V2 policy keeps its V2 profile id; it is never masked admission."""
    identity = _masked_identity()
    assert identity.source_calculation_identity.policy.profile_id == "KSI-GIS-RELATIVE-VOLUME-V2"
    assert identity.profile.profile_id == "KSI-GIS-MASKED-RELATIVE-VOLUME-V3"
    wire = identity.model_dump(by_alias=True, mode="json")
    assert "admissionDigest" not in json.dumps(wire)


def test_publication_seals_and_mutation_fails_closed() -> None:
    """Changing output bytes or lifetime must invalidate the sealed descriptor."""
    publication = _publication()
    assert publication.publication_digest == publication.canonical_digest()

    tampered = publication.model_dump(by_alias=True)
    tampered["outputSha256"] = _digest("other-output-bytes")
    with pytest.raises(ValidationError, match="publication digest"):
        DeltaRasterPublicationV1.model_validate(tampered)


def test_publication_rejects_float32_url_output_and_lifetime_violations() -> None:
    """Float32 drift, URL/path output ids, and expired lifetimes cannot be sealed."""
    payload = _publication().model_dump(by_alias=True)
    payload["dtype"] = "FLOAT32"
    payload["publicationDigest"] = None
    with pytest.raises(ValidationError):
        DeltaRasterPublicationV1.model_validate(payload)

    for output_id in (
        "https://example.invalid/out.tif",
        "/abs/path.tif",
        "..\\escape",
        "abc/def",
        "out:01",
        "out tif",
        "",
    ):
        payload = _publication().model_dump(by_alias=True)
        payload["outputId"] = output_id
        payload["publicationDigest"] = None
        with pytest.raises(ValidationError):
            DeltaRasterPublicationV1.model_validate(payload)

    for output_id in ("..", "a..b"):
        payload = _publication().model_dump(by_alias=True)
        payload["outputId"] = output_id
        payload["publicationDigest"] = None
        with pytest.raises(ValidationError, match="opaque identifier"):
            DeltaRasterPublicationV1.model_validate(payload)

    payload = _publication().model_dump(by_alias=True)
    payload["expiresAt"] = payload["issuedAt"]
    payload["publicationDigest"] = None
    with pytest.raises(ValidationError, match="expiresAt must be after issuedAt"):
        DeltaRasterPublicationV1.model_validate(payload)

    payload = _publication().model_dump(by_alias=True)
    payload["issuedAt"] = "2026-10-01T00:00:00"
    payload["publicationDigest"] = None
    with pytest.raises(ValidationError, match="must be UTC"):
        DeltaRasterPublicationV1.model_validate(payload)


def test_publication_rejects_nonfinite_transform_and_unknown_fields() -> None:
    """Non-finite grid affine and extra fields fail closed before sealing."""
    payload = _publication().model_dump(by_alias=True)
    payload["transform"] = [1.0, 0.0, float("nan"), 0.0, -1.0, 200.0]
    payload["publicationDigest"] = None
    with pytest.raises(ValidationError):
        DeltaRasterPublicationV1.model_validate(payload)

    payload = _publication().model_dump(by_alias=True)
    payload["downloadUrl"] = "https://example.invalid/out.tif"
    with pytest.raises(ValidationError):
        DeltaRasterPublicationV1.model_validate(payload)


def test_wire_helpers_return_sealed_dicts() -> None:
    """Wire helpers seal; unsealed models never reach the wire."""
    assert (
        exclusion_mask_binding_wire_dict(_mask().model_copy(update={"mask_binding_digest": None}))[
            "maskBindingDigest"
        ]
        == _mask().canonical_digest()
    )
    assert (
        masked_relative_volume_profile_wire_dict(
            _profile().model_copy(update={"masked_profile_digest": None})
        )["maskedProfileDigest"]
        == _profile().canonical_digest()
    )
    assert (
        masked_calculation_identity_wire_dict(
            _masked_identity().model_copy(update={"masked_calculation_identity_digest": None})
        )["maskedCalculationIdentityDigest"]
        == _masked_identity().canonical_digest()
    )
    assert (
        delta_raster_publication_wire_dict(
            _publication().model_copy(update={"publication_digest": None})
        )["publicationDigest"]
        == _publication().canonical_digest()
    )


def test_schema_accepts_all_four_sealed_models_and_rejects_relaxations() -> None:
    """The published schema admits exactly the sealed additive wire shapes."""
    validator = _schema_validator()
    valid = [
        exclusion_mask_binding_wire_dict(_mask()),
        masked_relative_volume_profile_wire_dict(_profile()),
        masked_calculation_identity_wire_dict(_masked_identity()),
        delta_raster_publication_wire_dict(_publication()),
    ]
    for document in valid:
        assert not list(validator.iter_errors(document)), document.get("contractVersion")

    relaxed = dict(valid[1])
    relaxed["thresholdM"] = 0.1
    assert list(validator.iter_errors(relaxed))

    unsealed = {key: value for key, value in valid[0].items() if key != "maskBindingDigest"}
    assert list(validator.iter_errors(unsealed))

    extra = dict(valid[3])
    extra["downloadUrl"] = "https://example.invalid/out.tif"
    assert list(validator.iter_errors(extra))

    float32 = dict(valid[3])
    float32["dtype"] = "FLOAT32"
    assert list(validator.iter_errors(float32))

    relative_path = dict(valid[3])
    relative_path["outputId"] = "abc/def"
    assert list(validator.iter_errors(relative_path))

    dot_dot = dict(valid[3])
    dot_dot["outputId"] = "a..b"
    assert list(validator.iter_errors(dot_dot))

    unbounded = {key: value for key, value in valid[3].items() if key != "bounds"}
    assert list(validator.iter_errors(unbounded))
