"""Additive mask child-resource ingress contracts: validity, adversarial, schema.

Synthetic fixtures only.  No field, customer, or production data.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.external_mask_input import (
    MaskChildDeclarationV1,
    MaskInspectionProfileV1,
    MaskObservedManifestV1,
    mask_child_declaration_wire_dict,
    mask_inspection_profile_wire_dict,
    mask_observed_manifest_wire_dict,
)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _canonical_digest(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _subject(label: str, org: str = "org-a", site: str = "site-a") -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id=org,
        site_id=site,
        work_order_id="order-" + label,
        submission_id="submission-" + label,
        revision=1,
        submission_digest=_digest("submission-" + label),
        manifest_digest=_digest("manifest-" + label),
    )


_TRANSFORM = (1.0, 0.0, 200000.0, 0.0, -1.0, 550000.0)


def _profile(envelope_digest: str) -> MaskInspectionProfileV1:
    return MaskInspectionProfileV1(
        profile_id="KSI-MASK-INSPECTION-V1",
        version=1,
        contained_protocol="CONTAINED_MASK_INSPECTION_V1",
        runtime_image_version="9.9.9",
        runtime_image_oci_digest=_digest("oci"),
        worker_executable_digest=_digest("exe"),
        worker_build_digest=_digest("build"),
        dependency_lock_digest=_digest("lock"),
        mask_grammar_digest=_digest("mask-grammar-v1"),
        mask_convention="UINT8_SINGLE_BAND_BINARY_0_KEEP_1_EXCLUDE_V1",
        mask_nodata_rule="NO_NODATA",
        resource_envelope_digest=envelope_digest,
    ).sealed()


def _declaration() -> MaskChildDeclarationV1:
    return MaskChildDeclarationV1(
        declaration_id="decl-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        child_kind="MASK_CHILD",
        mask_child_id="mask-child-1",
        mask_artifact_id="mask-artifact-1",
        parent_subject=_subject("parent"),
        target_baseline_subject=_subject("baseline"),
        target_baseline_dsm_artifact_id="dsm-baseline",
        declared_sha256=_digest("mask-bytes"),
        declared_size_bytes=128,
    ).sealed()


def _manifest(profile_digest: str) -> MaskObservedManifestV1:
    left, bottom = 200000.0, 550000.0 - 4.0
    right, top = 200000.0 + 4.0, 550000.0
    parent = _subject("parent")
    baseline = _subject("baseline")
    return MaskObservedManifestV1(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        child_kind="MASK_CHILD",
        mask_child_id="mask-child-1",
        mask_artifact_id="mask-artifact-1",
        subject=parent,
        parent_subject_digest=parent.canonical_digest(),
        target_baseline_dsm_artifact_id="dsm-baseline",
        target_baseline_subject_digest=baseline.canonical_digest(),
        observed_sha256=_digest("mask-bytes"),
        observed_size_bytes=128,
        observed_inspection_report_digest=_digest("report"),
        inspection_profile_digest=profile_digest,
        rows=4,
        columns=4,
        transform=_TRANSFORM,
        transform_digest=_canonical_digest({"transform": list(_TRANSFORM)}),
        observed_crs_identifier="EPSG:5186",
        observed_crs_digest=_digest("crs"),
        dtype="UINT8",
        band_count=1,
        retain_value=0,
        exclude_value=1,
        nodata_representation="NONE",
        bounds=(left, bottom, right, top),
    ).sealed()


def test_valid_declaration_profile_manifest_bind() -> None:
    envelope_digest = _digest("envelope")
    profile = _profile(envelope_digest)
    declaration = _declaration()
    manifest = _manifest(profile.canonical_digest())
    assert declaration.declaration_digest == declaration.canonical_digest()
    assert manifest.manifest_digest == manifest.canonical_digest()
    assert manifest.parent_subject_digest == declaration.parent_subject.canonical_digest()


def test_declaration_rejects_url_artifact_and_accepts_baseline_parent() -> None:
    parent = _subject("parent")
    with pytest.raises(ValueError):
        MaskChildDeclarationV1(
            declaration_id="decl-x",
            organization_id="org-a",
            site_id="site-a",
            work_area_id="work-area-a",
            child_kind="MASK_CHILD",
            mask_child_id="mask-child-x",
            mask_artifact_id="https://example.invalid/mask.tif",
            parent_subject=parent,
            target_baseline_subject=_subject("baseline"),
            target_baseline_dsm_artifact_id="dsm-baseline",
            declared_sha256=_digest("b"),
            declared_size_bytes=10,
        )
    # A mask may legitimately belong to the baseline epoch itself: sharing
    # the parent and baseline subject is valid product scope, not a fake.
    baseline_parent = MaskChildDeclarationV1(
        declaration_id="decl-y",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        child_kind="MASK_CHILD",
        mask_child_id="mask-child-y",
        mask_artifact_id="mask-artifact-y",
        parent_subject=parent,
        target_baseline_subject=parent,
        target_baseline_dsm_artifact_id="dsm-baseline",
        declared_sha256=_digest("b"),
        declared_size_bytes=10,
    ).sealed()
    assert baseline_parent.declaration_digest == baseline_parent.canonical_digest()
    # A fabricated subject outside the declared organization/site is still
    # rejected by shape (no V2 identity is borrowed, no epoch is invented).
    foreign = _subject("parent").model_copy(
        update={"organization_id": "org-other", "site_id": "site-other"}
    )
    with pytest.raises(ValueError, match="bind the declared organization and site"):
        MaskChildDeclarationV1(
            declaration_id="decl-z",
            organization_id="org-a",
            site_id="site-a",
            work_area_id="work-area-a",
            child_kind="MASK_CHILD",
            mask_child_id="mask-child-z",
            mask_artifact_id="mask-artifact-z",
            parent_subject=foreign,
            target_baseline_subject=_subject("baseline"),
            target_baseline_dsm_artifact_id="dsm-baseline",
            declared_sha256=_digest("b"),
            declared_size_bytes=10,
        )


def test_manifest_rejects_bool_literals_and_bad_grid() -> None:
    profile = _profile(_digest("envelope"))
    base = _manifest(profile.canonical_digest()).model_dump(by_alias=True)
    base["bandCount"] = True
    base["manifestDigest"] = None
    with pytest.raises(ValueError, match="boolean"):
        MaskObservedManifestV1.model_validate(base)
    base2 = _manifest(profile.canonical_digest()).model_dump(by_alias=True)
    base2["transform"] = [1.0, 0.5, 200000.0, 0.0, -1.0, 550000.0]
    base2["transformDigest"] = _canonical_digest({"transform": base2["transform"]})
    base2["manifestDigest"] = None
    with pytest.raises(ValueError, match="rotation"):
        MaskObservedManifestV1.model_validate(base2)


def test_profile_requires_explicit_contained_binding() -> None:
    with pytest.raises(ValueError):
        MaskInspectionProfileV1(
            profile_id="KSI-MASK-INSPECTION-V1",
            version=1,
            contained_protocol="CONTAINED_MASK_INSPECTION_V1",
            runtime_image_version="9.9.9",
            runtime_image_oci_digest=_digest("oci"),
            worker_executable_digest=_digest("exe"),
            worker_build_digest=_digest("build"),
            dependency_lock_digest=_digest("lock"),
            mask_grammar_digest=_digest("mask-grammar-v1"),
            mask_convention="UINT8_SINGLE_BAND_BINARY_0_KEEP_1_EXCLUDE_V1",
            mask_nodata_rule="ALLOW",  # type: ignore[arg-type]
            resource_envelope_digest=_digest("envelope"),
        )


def test_wire_dicts_validate_against_new_schema() -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "schemas"
        / "external-mask-input.v1.json"
    )
    schema = json.loads(schema_path.read_text())
    validator = Draft202012Validator(schema)
    profile = _profile(_digest("envelope"))
    declaration = _declaration()
    manifest = _manifest(profile.canonical_digest())
    for wire in (
        mask_child_declaration_wire_dict(declaration),
        mask_inspection_profile_wire_dict(profile),
        mask_observed_manifest_wire_dict(manifest),
    ):
        validator.validate(wire)


def test_digest_tamper_fails_closed() -> None:
    declaration = _declaration()
    tampered = declaration.model_dump(by_alias=True)
    tampered["declarationDigest"] = _digest("other")
    with pytest.raises(ValueError, match="digest"):
        MaskChildDeclarationV1.model_validate(tampered)


def test_narrow_report_rejects_naive_timestamp_and_bool_band() -> None:
    from datetime import UTC, datetime

    from ksi_event_contracts.external_mask_input_report import (
        MaskObservationMeasurementsV1,
        MaskObservationReportV1,
    )

    measurements = MaskObservationMeasurementsV1(
        observed_crs_identifier="EPSG:5186",
        observed_crs_digest=_digest("crs"),
        transform=_TRANSFORM,
        transform_digest=_canonical_digest({"transform": list(_TRANSFORM)}),
        width=4,
        height=4,
        band_count=1,
        dtype="UINT8",
        nodata_representation="NONE",
        bounds=(200000.0, 549996.0, 200004.0, 550000.0),
    )
    base = dict(
        report_id="report-1",
        mask_child_id="mask-child-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        subject=_subject("parent"),
        subject_digest=_subject("parent").canonical_digest(),
        mask_artifact_id="mask-artifact-1",
        observed_sha256=_digest("mask-bytes"),
        observed_size_bytes=128,
        inspection_profile_digest=_digest("profile"),
        contained_runtime_digest=_digest("runtime"),
        inspector_build_digest=_digest("inspector"),
        measurements=measurements,
        reported_at=datetime(2026, 10, 26, tzinfo=UTC),
    )
    assert MaskObservationReportV1.model_validate(base).sealed().report_digest is not None
    naive = dict(base, reported_at=datetime(2026, 10, 26))
    with pytest.raises(ValueError, match="UTC"):
        MaskObservationReportV1.model_validate(naive)
    bad_band = measurements.model_dump(by_alias=True)
    bad_band["bandCount"] = True
    with pytest.raises(ValueError, match="boolean"):
        MaskObservationMeasurementsV1.model_validate(bad_band)
