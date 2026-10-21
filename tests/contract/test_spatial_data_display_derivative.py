"""Display-derivative identity layer: determinism, pinning, fail-closed registration.

Covers the FIRST implementation unit of the display/LOD contract proposal
(2026-10-21): the identity records only. No tile/LOD table, no cache, no
registration method is implemented or asserted here.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ksi_core.domains.external.delivery.display_derivative import (
    display_binding_for,
    pair_is_registered,
    project_display_derivative,
)
from ksi_event_contracts._spatial_data import SpatialDataModel
from ksi_event_contracts.spatial_data_display import (
    DisplayDerivativeBindingV1,
    DisplayDerivativeV1,
    DisplayLodV1,
    DisplaySpatialViewV1,
    DisplayStyleV1,
    DisplayValidityV1,
    PairRegistrationNoneV1,
    PairRegistrationStatusV1,
    PairRegistrationV1,
)
from pydantic import ValidationError
from pydantic.json_schema import models_json_schema
from spatial_data_fixture import (
    ASSET,
    DIGEST,
    make_job,
    make_measurements,
    make_receipt,
    make_source,
)

ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL_HASH = "sha256:" + "d" * 64
OTHER_DIGEST = "sha256:" + "e" * 64
OTHER_ASSET = "ksa-v1-" + "f" * 64


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((ROOT / "contracts/schemas/spatial-data-display.v1.json").read_text())
    return Draft202012Validator(
        {"$ref": f"#/$defs/{name}", "$defs": schema["$defs"]}, format_checker=FormatChecker()
    )


def make_lod(**overrides: Any) -> DisplayLodV1:
    payload: dict[str, Any] = dict(
        level=0,
        lod_table_version="local-lod-table-v1",
        resampling_kernel_id="MEAN_DSM_PINNED_V1",
        target_metres_per_pixel=1.0,
    )
    payload.update(overrides)
    return DisplayLodV1(**payload)


def make_style(**overrides: Any) -> DisplayStyleV1:
    payload: dict[str, Any] = dict(
        band_mapping_id="dsm-singleband",
        colour_ramp_id="local-ramp",
        colour_ramp_version=1,
        stretch_id="local-stretch",
        stretch_version=1,
        no_data_mask_rule_id="local-nodata-rule-v1",
        unit_label_id="metre",
        vertical_basis_statement_id="local-vertical-basis-v1",
    )
    payload.update(overrides)
    return DisplayStyleV1(**payload)


def make_validity(**overrides: Any) -> DisplayValidityV1:
    payload: dict[str, Any] = dict(
        mask_source_digest=DIGEST,
        valid_area_rule_version="local-valid-area-v1",
        excluded_rule_version="local-excluded-v1",
    )
    payload.update(overrides)
    return DisplayValidityV1(**payload)


def make_none(**overrides: Any) -> PairRegistrationNoneV1:
    payload: dict[str, Any] = dict(
        statement="독립 보기 — 정합 근거 없음",
    )
    payload.update(overrides)
    return PairRegistrationNoneV1(**payload)


def make_pair_registered(**overrides: Any) -> PairRegistrationV1:
    payload: dict[str, Any] = dict(
        baseline_asset_ref=ASSET,
        current_asset_ref=OTHER_ASSET,
        method_id="local-method",
        method_version=1,
        transform_parameters=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        valid_area_rule_version="local-valid-area-v1",
        status=PairRegistrationStatusV1.REGISTERED,
        evidence_digests=(DIGEST,),
    )
    payload.update(overrides)
    return PairRegistrationV1(**payload)


def make_derivative(**overrides: Any) -> DisplayDerivativeV1:
    job, receipt = make_job(), make_receipt()
    params: dict[str, Any] = dict(
        job=job,
        receipt=receipt,
        lod=make_lod(),
        style=make_style(),
        validity=make_validity(),
        registration=make_none(),
        prepared_for_principal_hash=PRINCIPAL_HASH,
    )
    params.update(overrides)
    return project_display_derivative(**params)


def test_sealed_derivative_binds_job_and_receipt() -> None:
    derivative = make_derivative()
    assert derivative.derivative_id == derivative.canonical_digest()
    assert derivative.source.asset_ref == ASSET
    assert derivative.source.observed_sha256 == DIGEST
    assert derivative.source.observed_crs_digest == DIGEST
    assert derivative.source.revision == 1
    assert derivative.window.pixel_window == make_receipt().pixel_window
    assert derivative.window.actual_bounds == make_receipt().actual_bounds
    assert derivative.permission.purpose == "GENERAL_DATA_USE"
    assert derivative.provenance.prepare_job_id == make_job().job_id
    assert derivative.provenance.receipt_digest == make_receipt().receipt_digest
    _validator("DisplayDerivativeV1").validate(derivative.model_dump(by_alias=True, mode="json"))


def test_identical_pins_reproduce_identical_id() -> None:
    first, second = make_derivative(), make_derivative()
    assert first.derivative_id == second.derivative_id
    assert first == second


@pytest.mark.parametrize(
    "mutate",
    [
        lambda kw: {"lod": make_lod(level=1)},
        lambda kw: {"lod": make_lod(lod_table_version="local-lod-table-v2")},
        lambda kw: {"style": make_style(colour_ramp_version=2)},
        lambda kw: {"style": make_style(stretch_id="other-stretch")},
        lambda kw: {"validity": make_validity(valid_area_rule_version="local-valid-area-v2")},
        lambda kw: {"validity": make_validity(mask_source_digest=OTHER_DIGEST)},
        lambda kw: {
            "registration": PairRegistrationV1(
                baseline_asset_ref=ASSET,
                current_asset_ref=OTHER_ASSET,
                method_id="local-method",
                method_version=1,
                transform_parameters=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                valid_area_rule_version="local-valid-area-v1",
                status=PairRegistrationStatusV1.UNREGISTERED,
            )
        },
        lambda kw: {"prepared_for_principal_hash": OTHER_DIGEST},
    ],
    ids=[
        "lod-level",
        "lod-table-version",
        "style-version",
        "style-id",
        "validity-rule",
        "validity-mask",
        "registration",
        "principal-hash",
    ],
)
def test_any_changed_display_pin_yields_different_id(
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    base = make_derivative()
    changed = make_derivative(**mutate({}))
    assert changed.derivative_id != base.derivative_id


def test_display_change_leaves_source_identity_byte_identical() -> None:
    job, receipt = make_job(), make_receipt()
    source_digest_before = job.source.source_digest
    receipt_digest_before = receipt.receipt_digest
    first = project_display_derivative(
        job=job,
        receipt=receipt,
        lod=make_lod(),
        style=make_style(),
        validity=make_validity(),
        registration=make_none(),
        prepared_for_principal_hash=PRINCIPAL_HASH,
    )
    second = project_display_derivative(
        job=job,
        receipt=receipt,
        lod=make_lod(level=2),
        style=make_style(colour_ramp_version=3),
        validity=make_validity(valid_area_rule_version="local-valid-area-v9"),
        registration=make_none(),
        prepared_for_principal_hash=PRINCIPAL_HASH,
    )
    assert first.derivative_id != second.derivative_id
    assert first.source == second.source
    assert first.source.model_dump(by_alias=True, mode="json") == second.source.model_dump(
        by_alias=True, mode="json"
    )
    assert job.source.source_digest == source_digest_before
    assert receipt.receipt_digest == receipt_digest_before


def test_corrective_source_revision_yields_different_source_identity() -> None:
    from ksi_event_contracts.external_artifact_validation import (
        ArtifactInspectionOutcomeV1,
        ArtifactOutcome,
    )

    corrected_source = make_source(
        observed_sha256=OTHER_DIGEST,
        inspection=ArtifactInspectionOutcomeV1(
            artifact_id="artifact-local",
            observed_sha256=OTHER_DIGEST,
            outcome=ArtifactOutcome.MEASURED,
            measurements=make_measurements(),
        ),
    )
    assert corrected_source.source_digest != make_source().source_digest
    corrected_job = make_job(source=corrected_source)
    old, new = (
        make_derivative(),
        make_derivative(
            job=corrected_job,
            receipt=make_receipt(
                job_digest=corrected_job.job_digest,
                source_digest=corrected_source.source_digest,
                source_sha256=OTHER_DIGEST,
            ),
        ),
    )
    assert old.source != new.source
    assert old.derivative_id != new.derivative_id


def test_registered_without_evidence_is_refused() -> None:
    with pytest.raises(ValidationError):
        make_pair_registered(evidence_digests=())


def test_unregistered_with_evidence_is_refused() -> None:
    with pytest.raises(ValidationError):
        PairRegistrationV1(
            baseline_asset_ref=ASSET,
            current_asset_ref=OTHER_ASSET,
            method_id="local-method",
            method_version=1,
            transform_parameters=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
            valid_area_rule_version="local-valid-area-v1",
            status=PairRegistrationStatusV1.UNREGISTERED,
            evidence_digests=(DIGEST,),
        )


def test_self_pair_is_refused() -> None:
    with pytest.raises(ValidationError):
        make_pair_registered(current_asset_ref=ASSET)


def test_registration_status_cannot_name_unbacked_registration() -> None:
    assert {member.value for member in PairRegistrationStatusV1} == {
        "REGISTERED",
        "UNREGISTERED",
    }


def test_none_marker_is_explicit_and_never_registered() -> None:
    none = make_none()
    assert none.registration_kind == "NONE"
    assert not pair_is_registered(none)
    unregistered = PairRegistrationV1(
        baseline_asset_ref=ASSET,
        current_asset_ref=OTHER_ASSET,
        method_id="local-method",
        method_version=1,
        transform_parameters=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        valid_area_rule_version="local-valid-area-v1",
        status=PairRegistrationStatusV1.UNREGISTERED,
    )
    assert not pair_is_registered(unregistered)
    assert pair_is_registered(make_pair_registered())


def test_equal_crs_is_not_registration() -> None:
    first = make_derivative()
    second_job = make_job()
    second = make_derivative(job=second_job, receipt=make_receipt())
    assert first.source.observed_crs_digest == second.source.observed_crs_digest == DIGEST
    assert not pair_is_registered(first.registration)
    assert not pair_is_registered(second.registration)


def test_registration_must_include_derivative_source() -> None:
    foreign = make_pair_registered(
        baseline_asset_ref=OTHER_ASSET,
        current_asset_ref="ksa-v1-" + "9" * 64,
    )
    with pytest.raises(ValidationError):
        make_derivative(registration=foreign)


def test_binding_carries_no_composite_flag_and_no_suitability() -> None:
    binding = display_binding_for(
        derivative=make_derivative(),
        job=make_job(),
        receipt=make_receipt(),
        spatial_view=DisplaySpatialViewV1.AVAILABLE,
    )
    assert binding.source_digest == make_job().source.source_digest
    assert binding.spatial_view is DisplaySpatialViewV1.AVAILABLE
    assert {member.value for member in DisplaySpatialViewV1} == {
        "AVAILABLE",
        "NOT_READY",
        "UNRENDERABLE",
    }
    forbidden = {
        "ready",
        "status",
        "verified",
        "operational",
        "healthy",
        "suitable",
        "suitability",
        "eligible",
        "eligibility",
    }
    for model in (DisplayDerivativeV1, DisplayDerivativeBindingV1):
        _, schema = models_json_schema([(model, "validation")], by_alias=True)
        names = {
            prop.lower()
            for name, defn in schema["$defs"].items()
            # PairRegistrationV1.status is the section-8-mandated registration
            # claim state (REGISTERED | UNREGISTERED), not a composite flag.
            if name != "PairRegistrationV1"
            for prop in defn.get("properties", {})
        }
        assert not (names & forbidden), names & forbidden
    binding_names = {prop.lower() for prop in type(binding).model_fields}
    assert not (binding_names & forbidden), binding_names & forbidden


def test_binding_refuses_drifted_or_unsealed_inputs() -> None:
    job, receipt = make_job(), make_receipt()
    derivative = make_derivative()
    drifted = make_receipt(
        pixel_window=(0, 1, 8, 10),
        width=1,
        height=2,
        actual_bounds=(0, 0, 1, 2),
        transform=(1.0, 0.0, 0.0, 0.0, -1.0, 2.0),
    )
    with pytest.raises(ValueError):
        display_binding_for(
            derivative=derivative,
            job=make_job(),
            receipt=drifted,
            spatial_view=DisplaySpatialViewV1.AVAILABLE,
        )
    tampered = derivative.model_copy(update={"derivative_id": OTHER_DIGEST})
    with pytest.raises(ValueError):
        display_binding_for(
            derivative=tampered,
            job=job,
            receipt=receipt,
            spatial_view=DisplaySpatialViewV1.AVAILABLE,
        )


def test_projection_refuses_unbound_receipt() -> None:
    other_job = make_job(job_id="sdj-v1-00000000-0000-4000-8000-000000000002")
    with pytest.raises(ValueError):
        make_derivative(job=other_job, receipt=make_receipt())


def test_schema_is_exactly_generated_from_exported_models() -> None:
    import ksi_event_contracts.spatial_data_display as namespace

    models: list[tuple[type[SpatialDataModel], Literal["validation"]]] = [
        (value, "validation")
        for value in vars(namespace).values()
        if isinstance(value, type)
        and issubclass(value, SpatialDataModel)
        and value.__module__ == namespace.__name__
        and not value.__name__.startswith("_")
    ]
    assert {model.__name__ for model, _ in models} == {
        "DisplayDerivativeV1",
        "DisplayDerivativeSourceV1",
        "DisplayDerivativeWindowV1",
        "DisplayLodV1",
        "DisplayStyleV1",
        "DisplayValidityV1",
        "DisplayPermissionV1",
        "DisplayProvenanceV1",
        "DisplayDerivativeBindingV1",
        "PairRegistrationV1",
        "PairRegistrationNoneV1",
    }
    _, expected = models_json_schema(models, by_alias=True)
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    actual = json.loads((ROOT / "contracts/schemas/spatial-data-display.v1.json").read_text())
    assert actual == expected


def test_wire_rejects_extra_fields() -> None:
    derivative = make_derivative()
    payload = derivative.model_dump(by_alias=True, mode="json")
    _validator("DisplayDerivativeV1").validate(payload)
    payload["callerAuthority"] = True
    assert not _validator("DisplayDerivativeV1").is_valid(payload)
    with pytest.raises(ValidationError):
        DisplayDerivativeV1.model_validate(payload)
