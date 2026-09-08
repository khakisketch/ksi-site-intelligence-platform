"""Immutable external-validation wire contracts (synthetic local evidence only)."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    DecisionVerdict,
    ExternalArtifactInspectionReportV1,
    ExternalArtifactInspectionRequestV1,
    ExternalInspectionMeasurementPayloadV1,
    ExternalPairUseDecisionV1,
    ExternalUseDecisionV1,
    ExternalValidationPolicyV1,
    FactClass,
    NodataRepresentation,
    PolicyStatus,
    RasterMeasurementsV1,
    ResourceEnvelopeV1,
    SealedArtifactBindingV1,
    SealedExternalSubjectV1,
    SealedZoneReferenceV1,
    external_artifact_inspection_report_wire_dict,
    external_artifact_inspection_request_wire_dict,
    external_pair_use_decision_wire_dict,
    external_use_decision_wire_dict,
    external_validation_policy_wire_dict,
)
from ksi_event_contracts.external_display_artifact import (
    SanitizedDisplayDeclarationV1,
    SanitizedDisplayReceiptV1,
    sanitized_display_declaration_wire_dict,
    sanitized_display_receipt_wire_dict,
)
from ksi_event_contracts.external_evidence import (
    EvidenceCoreVerdict,
    EvidenceIndependence,
    ExternalEvidenceDeclarationV1,
    ExternalEvidenceManifestV1,
    ExternalEvidenceMeasurementPayloadV1,
    ExternalEvidenceRecordV1,
    ExternalEvidenceValidationRequestV1,
    external_evidence_declaration_wire_dict,
    external_evidence_manifest_wire_dict,
    external_evidence_record_wire_dict,
    external_evidence_validation_request_wire_dict,
)
from pydantic import ValidationError
from rasterio.io import MemoryFile
from support.external_artifact_validation_fixtures import (
    CHECKPOINT_BYTES,
    DSM_SHA256,
    ORTHO_SHA256,
    synthetic_external_artifacts,
)

_SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "contracts" / "schemas"
_SCHEMA_NAMES = (
    "external-artifact-inspection-request.v1.json",
    "external-artifact-inspection-report.v1.json",
    "external-evidence-declaration.v1.json",
    "external-evidence-manifest.v1.json",
    "external-evidence-validation-request.v1.json",
    "external-evidence-record.v1.json",
    "external-validation-policy.v1.json",
    "external-use-decision.v1.json",
    "external-pair-use-decision.v1.json",
    "external-sanitized-display-artifact.v1.json",
)
_NOW = datetime(2026, 9, 7, tzinfo=UTC)


def _digest(letter: str) -> str:
    return "sha256:" + letter * 64


def _sealed_digest(value: str | None) -> str:
    assert value is not None
    return value


def _schema(name: str) -> dict[str, Any]:
    return json.loads((_SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _subject(*, revision: int = 1, marker: str = "a") -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="organization-1",
        site_id="site-1",
        work_order_id="work-order-1",
        submission_id="submission-1",
        revision=revision,
        submission_digest=_digest(marker),
        manifest_digest=_digest("b" if marker == "a" else "c"),
    )


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=1_024,
        max_streamed_bytes=1_024,
        max_tiff_directories=4,
        max_tiff_entries=32,
        max_pixels=1_000,
        max_bands=4,
        max_blocks=64,
        max_decompressed_bytes=8_192,
        max_sample_bytes=8_192,
        max_geometry_vertices=64,
        max_cpu_seconds=2.0,
        max_memory_bytes=16_384,
        max_workspace_bytes=16_384,
        max_output_bytes=16_384,
        max_tenant_concurrency=1,
        max_queue_depth=4,
        max_deadline_seconds=3.0,
        lease_duration_seconds=4.0,
        max_retry_attempts=2,
    ).sealed()


def _policy() -> ExternalValidationPolicyV1:
    envelope = _envelope()
    return ExternalValidationPolicyV1(
        policy_id="policy-1",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=_digest("d"),
        grammar_digest=_digest("e"),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=_digest("f"),
        inspection_rule_ids=("synthetic_test_only",),
        evidence_rule_ids=("synthetic_test_only",),
        compatibility_mapping_digests=(_digest("1"),),
        synthetic_test_only=True,
    ).sealed()


def _request() -> ExternalArtifactInspectionRequestV1:
    policy = _policy()
    return ExternalArtifactInspectionRequestV1(
        request_id="inspection-request-1",
        subject=_subject(),
        inspection_policy_id=policy.policy_id,
        inspection_policy_version=policy.version,
        inspection_policy_digest=_sealed_digest(policy.policy_digest),
        issued_at=_NOW,
        idempotency_key="inspection-idempotency-1",
    )


def _payload() -> ExternalInspectionMeasurementPayloadV1:
    subject = _subject()
    return ExternalInspectionMeasurementPayloadV1(
        fact_class=FactClass.OBSERVED,
        subject_digest=subject.canonical_digest(),
        sealed_manifest_digest=subject.manifest_digest,
        inspection_policy_digest=_sealed_digest(_policy().policy_digest),
        inspector_build_digest=_digest("2"),
        artifact_bindings=(
            SealedArtifactBindingV1(artifact_id="dsm-1", observed_sha256=_digest("3")),
            SealedArtifactBindingV1(artifact_id="ortho-1", observed_sha256=_digest("4")),
        ),
        outcomes=(
            ArtifactInspectionOutcomeV1(
                artifact_id="dsm-1",
                observed_sha256=_digest("3"),
                outcome=ArtifactOutcome.MEASURED,
                measurements=RasterMeasurementsV1(
                    observed_crs_identifier="EPSG:3857",
                    observed_crs_wkt="PROJCRS[synthetic EPSG:3857]",
                    observed_crs_digest=_digest("5"),
                    observed_vertical_reference=None,
                    transform=(1.0, 0.0, 0.0, 0.0, -1.0, 2.0),
                    footprint_wkt="POLYGON((0 0,2 0,2 2,0 2,0 0))",
                    footprint_digest=_digest("7"),
                    width=2,
                    height=2,
                    band_count=1,
                    dtype="float32",
                    layout="striped",
                    nodata_representation=NodataRepresentation.NONE,
                    nodata_value=None,
                    valid_pixel_count=4,
                ),
            ),
            ArtifactInspectionOutcomeV1(
                artifact_id="ortho-1",
                observed_sha256=_digest("4"),
                outcome=ArtifactOutcome.NOT_APPLICABLE,
                reason="UNSUPPORTED_ARTIFACT_KIND",
            ),
        ),
    )


def _report() -> ExternalArtifactInspectionReportV1:
    request = _request()
    payload = _payload()
    return ExternalArtifactInspectionReportV1(
        report_id="inspection-report-1",
        request_id=request.request_id,
        subject=request.subject,
        subject_digest=request.subject.canonical_digest(),
        sealed_manifest_digest=request.subject.manifest_digest,
        inspection_policy_digest=request.inspection_policy_digest,
        inspector_build_digest=payload.inspector_build_digest,
        measurement_payload=payload,
        worker_instance_id="123e4567-e89b-42d3-a456-426614174000",
        lease_acquisition_id="123e4567-e89b-42d3-a456-426614174001",
        lease_generation=1,
        reported_at=_NOW,
    )


def _declaration() -> ExternalEvidenceDeclarationV1:
    subject = _subject()
    return ExternalEvidenceDeclarationV1(
        evidence_id="evidence-1",
        subject=subject,
        subject_digest=subject.canonical_digest(),
        target_dsm_artifact_id="dsm-1",
        target_dsm_observed_sha256=_digest("3"),
        declared_content_digest=_digest("8"),
        declared_content_type="text/csv",
        independence=EvidenceIndependence.DECLARED,
        independence_basis="Customer-declared independent checkpoint origin.",
        declared_at=_NOW,
    ).sealed()


def _evidence_manifest() -> ExternalEvidenceManifestV1:
    declaration = _declaration()
    return ExternalEvidenceManifestV1(
        evidence_manifest_id="evidence-manifest-1",
        evidence_id=declaration.evidence_id,
        declaration_digest=_sealed_digest(declaration.declaration_digest),
        subject=declaration.subject,
        subject_digest=declaration.subject_digest,
        target_dsm_artifact_id=declaration.target_dsm_artifact_id,
        target_dsm_observed_sha256=declaration.target_dsm_observed_sha256,
        observed_object_digest=declaration.declared_content_digest,
        observed_size_bytes=len(CHECKPOINT_BYTES),
        observed_content_type="text/csv",
        server_object_key="external-evidence/opaque-server-key",
        observed_at=_NOW,
    ).sealed()


def _evidence_request() -> ExternalEvidenceValidationRequestV1:
    policy = _policy()
    manifest = _evidence_manifest()
    return ExternalEvidenceValidationRequestV1(
        validation_id="evidence-validation-1",
        evidence_manifest_digest=_sealed_digest(manifest.evidence_manifest_digest),
        subject_digest=manifest.subject_digest,
        target_dsm_observed_sha256=manifest.target_dsm_observed_sha256,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_digest=_sealed_digest(policy.policy_digest),
        issued_at=_NOW,
        idempotency_key="evidence-idempotency-1",
    )


def _evidence_record() -> ExternalEvidenceRecordV1:
    request = _evidence_request()
    measurement = ExternalEvidenceMeasurementPayloadV1(
        fact_class=FactClass.OBSERVED,
        validation_id=request.validation_id,
        evidence_manifest_digest=request.evidence_manifest_digest,
        target_dsm_observed_sha256=request.target_dsm_observed_sha256,
        policy_digest=request.policy_digest,
        measured_checkpoint_count=3,
        mean_error_m=0.0,
        mae_m=0.0,
        rmse_m=0.0,
        max_abs_error_m=0.0,
        measured_at=_NOW,
    )
    return ExternalEvidenceRecordV1(
        evidence_record_id="evidence-record-1",
        validation_id=request.validation_id,
        subject_digest=request.subject_digest,
        evidence_manifest_digest=request.evidence_manifest_digest,
        target_dsm_observed_sha256=request.target_dsm_observed_sha256,
        policy_digest=request.policy_digest,
        measurement_payload=measurement,
        core_verdict=EvidenceCoreVerdict.VALIDATED,
        core_recorded_at=_NOW,
    ).sealed()


def _display_receipt() -> SanitizedDisplayReceiptV1:
    report = _report().sealed()
    declaration = SanitizedDisplayDeclarationV1(
        display_id="display-1",
        request_id=report.request_id,
        source_subject_digest=report.subject_digest,
        source_report_digest=_sealed_digest(report.report_digest),
        policy_digest=report.inspection_policy_digest,
        inspector_build_digest=report.inspector_build_digest,
        declared_derivative_sha256=_digest("9"),
        declared_derivative_size_bytes=123,
        declared_derivative_content_type="image/tiff",
    ).sealed()
    return SanitizedDisplayReceiptV1(
        display_id=declaration.display_id,
        request_id=declaration.request_id,
        declaration_digest=_sealed_digest(declaration.declaration_digest),
        source_subject_digest=declaration.source_subject_digest,
        source_report_digest=declaration.source_report_digest,
        policy_digest=declaration.policy_digest,
        inspector_build_digest=declaration.inspector_build_digest,
        observed_derivative_sha256=declaration.declared_derivative_sha256,
        observed_derivative_size_bytes=declaration.declared_derivative_size_bytes,
        observed_derivative_content_type=declaration.declared_derivative_content_type,
        sanitized_display_ref="sda-v1-opaque-display-reference",
        sealed_at=_NOW,
    ).sealed()


def _single_decision() -> ExternalUseDecisionV1:
    report = _report().sealed()
    evidence = _evidence_record()
    receipt = _display_receipt()
    return ExternalUseDecisionV1(
        decision_id="use-decision-1",
        subject=report.subject,
        subject_digest=report.subject_digest,
        use="DISPLAY",
        policy_digest=report.inspection_policy_digest,
        inspection_report_digest=report.report_digest,
        evidence_record_digests=(_sealed_digest(evidence.evidence_record_digest),),
        sanitized_display_receipt_digest=receipt.receipt_digest,
        verdict=DecisionVerdict.RESTRICTED,
        reasons=("SYNTHETIC_TEST_ONLY",),
        remediations=("AUTHORIZED_POLICY_PROCESS",),
        decided_at=_NOW,
    )


def _pair_decision(
    *,
    use: Literal["VISUAL_COMPARISON", "RELATIVE_VOLUME"] = "RELATIVE_VOLUME",
    verdict: DecisionVerdict = DecisionVerdict.BLOCKED,
) -> ExternalPairUseDecisionV1:
    baseline = _subject(revision=1, marker="a")
    current = _subject(revision=2, marker="c")
    details: dict[str, Any] = {}
    if use == "RELATIVE_VOLUME":
        details["zone"] = SealedZoneReferenceV1(
            zone_id="zone-1",
            revision=1,
            definition_digest=_digest("a"),
            observed_crs_digest=_digest("b"),
            observed_vertical_reference_digest=_digest("c"),
        )
    elif verdict is not DecisionVerdict.BLOCKED:
        details["baseline_sanitized_display_receipt_digest"] = _digest("7")
        details["current_sanitized_display_receipt_digest"] = _digest("8")
    return ExternalPairUseDecisionV1(
        decision_id="pair-decision-1",
        baseline_subject=baseline,
        baseline_subject_digest=baseline.canonical_digest(),
        current_subject=current,
        current_subject_digest=current.canonical_digest(),
        use=use,
        policy_digest=_sealed_digest(_policy().policy_digest),
        baseline_inspection_report_digest=_sealed_digest(_report().sealed().report_digest),
        current_inspection_report_digest=_digest("6"),
        evidence_record_digests=(_sealed_digest(_evidence_record().evidence_record_digest),),
        verdict=verdict,
        reasons=("SYNTHETIC_TEST_ONLY",),
        remediations=("AUTHORIZED_POLICY_PROCESS",),
        decided_at=_NOW,
        **details,
    )


@pytest.mark.parametrize("schema_name", _SCHEMA_NAMES)
def test_schema_files_are_explicit_draft_2020_12_contracts(schema_name: str) -> None:
    """Removing the schema dialect marker must fail this wire-contract test."""
    schema = _schema(schema_name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_contract_wires_conform_to_their_structural_schemas() -> None:
    """Breaking a model's public wire shape must fail this model/schema parity test."""
    policy = _policy()
    request = _request()
    report = _report().sealed()
    declaration = _declaration()
    manifest = _evidence_manifest()
    evidence_request = _evidence_request()
    evidence_record = _evidence_record()
    receipt = _display_receipt()
    declaration_display = SanitizedDisplayDeclarationV1(
        display_id=receipt.display_id,
        request_id=receipt.request_id,
        source_subject_digest=receipt.source_subject_digest,
        source_report_digest=receipt.source_report_digest,
        policy_digest=receipt.policy_digest,
        inspector_build_digest=receipt.inspector_build_digest,
        declared_derivative_sha256=receipt.observed_derivative_sha256,
        declared_derivative_size_bytes=receipt.observed_derivative_size_bytes,
        declared_derivative_content_type=receipt.observed_derivative_content_type,
    ).sealed()
    wires = (
        (
            "external-artifact-inspection-request.v1.json",
            external_artifact_inspection_request_wire_dict(request),
        ),
        (
            "external-artifact-inspection-report.v1.json",
            external_artifact_inspection_report_wire_dict(report),
        ),
        (
            "external-evidence-declaration.v1.json",
            external_evidence_declaration_wire_dict(declaration),
        ),
        ("external-evidence-manifest.v1.json", external_evidence_manifest_wire_dict(manifest)),
        (
            "external-evidence-validation-request.v1.json",
            external_evidence_validation_request_wire_dict(evidence_request),
        ),
        ("external-evidence-record.v1.json", external_evidence_record_wire_dict(evidence_record)),
        ("external-validation-policy.v1.json", external_validation_policy_wire_dict(policy)),
        ("external-use-decision.v1.json", external_use_decision_wire_dict(_single_decision())),
        (
            "external-pair-use-decision.v1.json",
            external_pair_use_decision_wire_dict(_pair_decision()),
        ),
        (
            "external-sanitized-display-artifact.v1.json",
            sanitized_display_declaration_wire_dict(declaration_display),
        ),
        (
            "external-sanitized-display-artifact.v1.json",
            sanitized_display_receipt_wire_dict(receipt),
        ),
    )
    for schema_name, wire in wires:
        Draft202012Validator(_schema(schema_name), format_checker=FormatChecker()).validate(wire)


def test_report_payload_digest_excludes_only_its_own_digest() -> None:
    """Including envelope lease/worker fields in the payload digest must fail this test."""
    report = _report().sealed()
    assert report.measurement_payload_digest == report.measurement_payload_canonical_digest()
    assert report.fact_class == "OBSERVED"

    retry = report.model_dump(by_alias=True, mode="json")
    retry["workerInstanceId"] = "123e4567-e89b-42d3-a456-426614174002"
    retry["leaseAcquisitionId"] = "123e4567-e89b-42d3-a456-426614174003"
    retry["leaseGeneration"] = 2
    retry["reportedAt"] = "2026-09-07T00:01:00Z"
    retry.pop("reportDigest")
    assert ExternalArtifactInspectionReportV1.model_validate(retry).measurement_payload_digest == (
        report.measurement_payload_digest
    )


def test_report_binds_subject_manifest_to_report_and_payload() -> None:
    """Decoupling subject/manifest identity from the report must fail this exact-binding test."""
    report = external_artifact_inspection_report_wire_dict(_report().sealed())
    report["sealedManifestDigest"] = _digest("0")
    report["measurementPayload"]["sealedManifestDigest"] = _digest("0")
    report.pop("measurementPayloadDigest")
    report.pop("reportDigest")
    with pytest.raises(ValidationError, match="sealedManifestDigest"):
        ExternalArtifactInspectionReportV1.model_validate(report)

    subject_rebound = external_artifact_inspection_report_wire_dict(_report().sealed())
    subject_rebound["subject"]["manifestDigest"] = _digest("0")
    subject_rebound["subjectDigest"] = SealedExternalSubjectV1.model_validate(
        subject_rebound["subject"]
    ).canonical_digest()
    subject_rebound["measurementPayload"]["subjectDigest"] = subject_rebound["subjectDigest"]
    subject_rebound.pop("measurementPayloadDigest")
    subject_rebound.pop("reportDigest")
    with pytest.raises(ValidationError, match="sealedManifestDigest"):
        ExternalArtifactInspectionReportV1.model_validate(subject_rebound)


def test_extra_field_or_naive_time_is_rejected() -> None:
    """Relaxing closed fields or timezone-bearing wire time must fail this test."""
    with pytest.raises(ValidationError):
        ExternalValidationPolicyV1.model_validate(
            {**external_validation_policy_wire_dict(_policy()), "extra": True}
        )
    raw = external_artifact_inspection_request_wire_dict(_request())
    raw["issuedAt"] = "2026-09-07T00:00:00"
    with pytest.raises(ValidationError):
        ExternalArtifactInspectionRequestV1.model_validate(raw)

    raw = external_artifact_inspection_request_wire_dict(_request())
    raw["issuedAt"] = "2026-09-07T09:00:00+09:00"
    with pytest.raises(ValidationError):
        ExternalArtifactInspectionRequestV1.model_validate(raw)

    raw = external_artifact_inspection_request_wire_dict(_request())
    raw["issuedAt"] = "2026-09-07T00:00:00-00:00"
    with pytest.raises(ValidationError):
        ExternalArtifactInspectionRequestV1.model_validate(raw)


def test_model_rejects_digest_and_relational_tampering_that_schema_cannot_recompute() -> None:
    """Removing digest/binding checks must fail this model-only relational contract test."""
    report = external_artifact_inspection_report_wire_dict(_report().sealed())
    report["measurementPayload"]["outcomes"].append(
        copy.deepcopy(report["measurementPayload"]["outcomes"][0])
    )
    Draft202012Validator(_schema("external-artifact-inspection-report.v1.json")).validate(report)
    with pytest.raises(ValidationError, match="outcome"):
        ExternalArtifactInspectionReportV1.model_validate(report)

    stale = external_artifact_inspection_report_wire_dict(_report().sealed())
    stale["measurementPayload"]["outcomes"][0]["measurements"]["footprintWkt"] = (
        "POLYGON((0 0,3 0,3 3,0 3,0 0))"
    )
    Draft202012Validator(_schema("external-artifact-inspection-report.v1.json")).validate(stale)
    with pytest.raises(ValidationError, match="measurementPayloadDigest"):
        ExternalArtifactInspectionReportV1.model_validate(stale)


def test_report_requires_canonical_uuid4_lease_fence_identifiers() -> None:
    """Relaxing fenced report ownership to arbitrary worker strings must fail this test."""
    raw = external_artifact_inspection_report_wire_dict(_report().sealed())
    raw["workerInstanceId"] = "not-a-worker-instance"
    with pytest.raises(ValidationError, match="UUIDv4"):
        ExternalArtifactInspectionReportV1.model_validate(raw)


@pytest.mark.parametrize("bad_value", (math.inf, math.nan, -1.0))
def test_active_policy_requires_finite_positive_resource_envelope(bad_value: float) -> None:
    """Admitting an unlimited/negative active envelope must fail this policy snapshot test."""
    raw = external_validation_policy_wire_dict(_policy())
    raw["resourceEnvelope"]["maxCpuSeconds"] = bad_value
    raw.pop("policyDigest")
    with pytest.raises(ValidationError):
        ExternalValidationPolicyV1.model_validate(raw)

    raw = external_validation_policy_wire_dict(_policy())
    raw["syntheticTestOnly"] = 1
    raw.pop("policyDigest")
    with pytest.raises(ValidationError):
        ExternalValidationPolicyV1.model_validate(raw)


def test_evidence_declared_observed_and_core_verdict_remain_distinct() -> None:
    """Promoting a declaration or measurement to independently validated must fail this test."""
    declaration = _declaration()
    manifest = _evidence_manifest()
    record = _evidence_record()
    assert declaration.fact_class == "DECLARED"
    assert manifest.fact_class == "OBSERVED"
    assert record.core_verdict == EvidenceCoreVerdict.VALIDATED

    raw = external_evidence_declaration_wire_dict(declaration)
    raw["independence"] = "OBSERVED"
    raw.pop("declarationDigest")
    with pytest.raises(ValidationError):
        ExternalEvidenceDeclarationV1.model_validate(raw)

    forged = external_evidence_record_wire_dict(record)
    forged["independentEvidenceSatisfied"] = True
    with pytest.raises(ValidationError):
        ExternalEvidenceRecordV1.model_validate(forged)

    rejected = external_evidence_record_wire_dict(record)
    rejected["coreVerdict"] = "REJECTED"
    rejected["coreReason"] = "human explanation is not a stable rejection code"
    rejected.pop("evidenceRecordDigest")
    with pytest.raises(ValidationError, match="coreReason"):
        ExternalEvidenceRecordV1.model_validate(rejected)


def test_evidence_measurement_requires_real_checkpoint_math_and_validated_payload() -> None:
    """Allowing empty or mathematically impossible checkpoint evidence must fail this test."""
    request = _evidence_request()
    impossible = ExternalEvidenceMeasurementPayloadV1(
        validation_id=request.validation_id,
        evidence_manifest_digest=request.evidence_manifest_digest,
        target_dsm_observed_sha256=request.target_dsm_observed_sha256,
        policy_digest=request.policy_digest,
        measured_checkpoint_count=3,
        mean_error_m=0.5,
        mae_m=0.5,
        rmse_m=0.5,
        max_abs_error_m=0.5,
        measured_at=_NOW,
    ).model_dump(
        by_alias=True,
        mode="json",
    )
    impossible["measuredCheckpointCount"] = 0
    with pytest.raises(ValidationError):
        ExternalEvidenceMeasurementPayloadV1.model_validate(impossible)

    impossible["measuredCheckpointCount"] = 3
    impossible["meanErrorM"] = 0.75
    impossible["maeM"] = 0.5
    with pytest.raises(ValidationError):
        ExternalEvidenceMeasurementPayloadV1.model_validate(impossible)

    record = external_evidence_record_wire_dict(_evidence_record())
    record["measurementPayload"] = None
    record.pop("evidenceRecordDigest")
    with pytest.raises(ValidationError, match="VALIDATED"):
        ExternalEvidenceRecordV1.model_validate(record)

    record["coreVerdict"] = "REJECTED"
    record["coreReason"] = "INVALID_CHECKPOINT_CSV"
    assert ExternalEvidenceRecordV1.model_validate(record).measurement_payload is None


def test_volume_binds_ordered_pair_and_exact_zone() -> None:
    """Allowing reversed/equal pair subjects or a missing volume zone must fail this test."""
    value = _pair_decision(use="RELATIVE_VOLUME", verdict=DecisionVerdict.RESTRICTED)
    assert value.baseline_subject_digest != value.current_subject_digest
    assert value.zone is not None
    assert value.zone.definition_digest.startswith("sha256:")

    raw = external_pair_use_decision_wire_dict(value)
    raw["currentSubject"] = copy.deepcopy(raw["baselineSubject"])
    raw["currentSubjectDigest"] = raw["baselineSubjectDigest"]
    with pytest.raises(ValidationError, match="ordered"):
        ExternalPairUseDecisionV1.model_validate(raw)

    raw = external_pair_use_decision_wire_dict(value)
    raw.pop("zone")
    with pytest.raises(ValidationError, match="zone"):
        ExternalPairUseDecisionV1.model_validate(raw)


@pytest.mark.parametrize(
    "verdict", (DecisionVerdict.ELIGIBLE, DecisionVerdict.RESTRICTED)
)
def test_nonblocked_visual_pair_binds_two_named_display_receipts(
    verdict: DecisionVerdict,
) -> None:
    """Pair binds receipt digests; Core receipt-provenance lookup is outside this contract."""
    value = _pair_decision(use="VISUAL_COMPARISON", verdict=verdict)
    wire = external_pair_use_decision_wire_dict(value)
    assert wire["baselineSanitizedDisplayReceiptDigest"] == _digest("7")
    assert wire["currentSanitizedDisplayReceiptDigest"] == _digest("8")
    Draft202012Validator(_schema("external-pair-use-decision.v1.json")).validate(wire)
    round_trip = ExternalPairUseDecisionV1.model_validate(wire)
    assert round_trip.baseline_sanitized_display_receipt_digest == _digest("7")
    assert round_trip.current_sanitized_display_receipt_digest == _digest("8")

    for field in (
        "baselineSanitizedDisplayReceiptDigest",
        "currentSanitizedDisplayReceiptDigest",
    ):
        missing = copy.deepcopy(wire)
        missing[field] = None
        missing.pop("decisionDigest")
        with pytest.raises(ValidationError, match=field):
            ExternalPairUseDecisionV1.model_validate(missing)

    both_missing = copy.deepcopy(wire)
    both_missing["baselineSanitizedDisplayReceiptDigest"] = None
    both_missing["currentSanitizedDisplayReceiptDigest"] = None
    both_missing.pop("decisionDigest")
    with pytest.raises(ValidationError, match="baselineSanitizedDisplayReceiptDigest"):
        ExternalPairUseDecisionV1.model_validate(both_missing)


def test_blocked_visual_pair_allows_null_display_receipts() -> None:
    """A blocker must not fabricate either display receipt before it exists."""
    wire = external_pair_use_decision_wire_dict(
        _pair_decision(use="VISUAL_COMPARISON", verdict=DecisionVerdict.BLOCKED)
    )
    assert wire["baselineSanitizedDisplayReceiptDigest"] is None
    assert wire["currentSanitizedDisplayReceiptDigest"] is None
    Draft202012Validator(_schema("external-pair-use-decision.v1.json")).validate(wire)


def test_volume_forbids_display_receipts_without_repurposing_quantitative_evidence() -> None:
    """Volume preserves its evidence records; display receipts are a separate visual binding."""
    volume = _pair_decision(use="RELATIVE_VOLUME", verdict=DecisionVerdict.RESTRICTED)
    wire = external_pair_use_decision_wire_dict(volume)
    assert wire["evidenceRecordDigests"] == [
        _sealed_digest(_evidence_record().evidence_record_digest)
    ]
    wire["baselineSanitizedDisplayReceiptDigest"] = _digest("7")
    wire["currentSanitizedDisplayReceiptDigest"] = _digest("8")
    wire.pop("decisionDigest")
    with pytest.raises(ValidationError, match="RELATIVE_VOLUME"):
        ExternalPairUseDecisionV1.model_validate(wire)


def test_blocked_decisions_allow_missing_prerequisites_but_nonblocked_bind_exact_inputs() -> None:
    """Fabricating missing policy/report/receipt/zone digests for blockers must fail this test."""
    single = external_use_decision_wire_dict(_single_decision())
    single["verdict"] = "BLOCKED"
    single["policyDigest"] = None
    single["inspectionReportDigest"] = None
    single["sanitizedDisplayReceiptDigest"] = None
    single["evidenceRecordDigests"] = []
    single.pop("decisionDigest")
    blocked_single = ExternalUseDecisionV1.model_validate(single)
    assert blocked_single.policy_digest is None

    single["verdict"] = "RESTRICTED"
    with pytest.raises(ValidationError, match="policyDigest"):
        ExternalUseDecisionV1.model_validate(single)

    display_without_checkpoint_evidence = external_use_decision_wire_dict(_single_decision())
    display_without_checkpoint_evidence["evidenceRecordDigests"] = []
    display_without_checkpoint_evidence.pop("decisionDigest")
    assert (
        ExternalUseDecisionV1.model_validate(display_without_checkpoint_evidence).verdict
        is DecisionVerdict.RESTRICTED
    )

    pair = external_pair_use_decision_wire_dict(_pair_decision())
    pair["verdict"] = "BLOCKED"
    pair["policyDigest"] = None
    pair["baselineInspectionReportDigest"] = None
    pair["currentInspectionReportDigest"] = None
    pair["zone"] = None
    pair["evidenceRecordDigests"] = []
    pair.pop("decisionDigest")
    assert ExternalPairUseDecisionV1.model_validate(pair).zone is None

    pair["verdict"] = "RESTRICTED"
    with pytest.raises(ValidationError, match="policyDigest"):
        ExternalPairUseDecisionV1.model_validate(pair)


def test_decision_digest_rejects_tampering_and_pair_has_named_report_and_display_slots() -> None:
    """Pair seals cover ordered report and visual-display receipt bindings."""
    decision = external_use_decision_wire_dict(_single_decision())
    decision["reasons"] = ["OTHER_REASON"]
    with pytest.raises(ValidationError, match="decisionDigest"):
        ExternalUseDecisionV1.model_validate(decision)

    pair = external_pair_use_decision_wire_dict(_pair_decision())
    assert pair["baselineInspectionReportDigest"]
    assert pair["currentInspectionReportDigest"]
    pair["inspectionReportDigests"] = [_digest("1"), _digest("2"), _digest("3")]
    with pytest.raises(ValidationError):
        ExternalPairUseDecisionV1.model_validate(pair)

    visual = external_pair_use_decision_wire_dict(
        _pair_decision(use="VISUAL_COMPARISON", verdict=DecisionVerdict.ELIGIBLE)
    )
    original_digest = visual["decisionDigest"]
    visual["baselineSanitizedDisplayReceiptDigest"] = _digest("9")
    with pytest.raises(ValidationError, match="decisionDigest"):
        ExternalPairUseDecisionV1.model_validate(visual)

    visual.pop("decisionDigest")
    resealed = ExternalPairUseDecisionV1.model_validate(visual).sealed()
    assert resealed.decision_digest != original_digest


def test_display_artifact_never_serializes_object_key_or_url() -> None:
    """Adding a public object location to a display journal wire must fail this test."""
    receipt = _display_receipt()
    wire = sanitized_display_receipt_wire_dict(receipt)
    assert "objectKey" not in wire
    assert "url" not in wire
    wire["objectKey"] = "external/secret-key"
    with pytest.raises(ValidationError):
        SanitizedDisplayReceiptV1.model_validate(wire)

    wire = sanitized_display_receipt_wire_dict(receipt)
    wire["sanitizedDisplayRef"] = "https://storage.invalid/display.tif"
    wire.pop("receiptDigest")
    with pytest.raises(ValidationError):
        SanitizedDisplayReceiptV1.model_validate(wire)


def test_synthetic_fixture_contains_real_raster_and_explicit_hostile_variants() -> None:
    """Replacing the GeoTIFF fixture with text pretending to be raster must fail this test."""
    artifacts = synthetic_external_artifacts()
    assert ORTHO_SHA256 == "294dfae5089bcf19d0cf016704e5e426cda3e277876fb42a9dcf6d8a4b054fb2"
    assert DSM_SHA256 == "e76f96ad0464976a33e7bfa46ab384521cd0e5229a861bec1b8bdcf009ec7205"
    assert artifacts.checkpoint_csv == CHECKPOINT_BYTES
    with MemoryFile(artifacts.geotiff) as memory, memory.open() as dataset:
        assert dataset.crs.to_epsg() == 3857
        assert dataset.transform.to_gdal() == (0.0, 1.0, 0.0, 2.0, 0.0, -1.0)
        assert (dataset.width, dataset.height, dataset.count) == (2, 2, 1)
    assert artifacts.geotiff_sha256 == hashlib.sha256(artifacts.geotiff).hexdigest()
    assert (
        artifacts.masked_nodata_geotiff_sha256
        == hashlib.sha256(artifacts.masked_nodata_geotiff).hexdigest()
    )
    assert (
        artifacts.unmasked_nan_geotiff_sha256
        == hashlib.sha256(artifacts.unmasked_nan_geotiff).hexdigest()
    )
    assert artifacts.malformed_tiff.startswith(b"II*\x00")
    assert artifacts.malformed_tiff == b"II*\x00truncated"
    assert len(artifacts.malformed_tiff) < len(artifacts.geotiff)
    with MemoryFile(artifacts.masked_nodata_geotiff) as memory, memory.open() as dataset:
        assert dataset.nodata == -9999.0
        assert bool(dataset.read(masked=True).mask[0, 0, 0])
    with MemoryFile(artifacts.unmasked_nan_geotiff) as memory, memory.open() as dataset:
        assert dataset.nodata is None
        assert math.isnan(float(dataset.read(1)[0, 0]))
    assert artifacts.vrt.startswith(b"<VRTDataset")
    assert artifacts.zip_archive.startswith(b"PK")
