"""External reconstruction declaration and observation contracts (ADR-KSI-036).

These tests deliberately cover only additive import contracts.  They do not
make registration a ProcessingJob, source authority, validation result, or
quantitative-eligibility decision.
"""

from __future__ import annotations

import copy
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ksi_event_contracts.external_reconstruction import (
    ExternalArtifactDeclarationV1,
    ExternalDeclaredVerticalReferenceV1,
    ExternalReconstructionManifestEntryV1,
    ExternalReconstructionManifestV1,
    ExternalReconstructionSubmissionV1,
    ExternalReconstructionSubmissionV1Input,
    ExternalReconstructionSubmissionV1Producer,
    ExternalReconstructionSubmissionV2,
    external_reconstruction_manifest_wire_dict,
    external_reconstruction_submission_v2_wire_dict,
    external_reconstruction_submission_wire_dict,
    parse_external_reconstruction_submission_v2,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReferenceSource,
)
from pydantic import ValidationError

_SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "contracts" / "schemas"
_SUBMISSION_SCHEMA = "external-reconstruction-submission.v1.json"
_SUBMISSION_V2_SCHEMA = "external-reconstruction-submission.v2.json"
_MANIFEST_SCHEMA = "external-reconstruction-manifest.v1.json"
_SHA_A = "a" * 64
_SHA_B = "b" * 64


class _ManifestFactoryOptions(TypedDict):
    manifest_id: str
    observed_at: datetime
    observed_by_service: str
    organization_id: str
    site_id: str
    observation_epoch_id: str


def _vertical_reference() -> ExternalDeclaredVerticalReferenceV1:
    return ExternalDeclaredVerticalReferenceV1(
        datum=VerticalDatum.ELLIPSOIDAL,
        basis="Customer export metadata declares ellipsoidal elevations.",
        source=VerticalReferenceSource.USER_DECLARED,
    )


def _artifact(
    artifact_id: str,
    kind: ProcessingArtifactKind,
    sha256: str,
    size_bytes: int,
    *,
    filename: str | None = None,
) -> ExternalArtifactDeclarationV1:
    return ExternalArtifactDeclarationV1(
        artifact_id=artifact_id,
        kind=kind,
        file_name=filename or f"{artifact_id}.tif",
        format="GeoTIFF",
        content_type="image/tiff",
        declared_sha256=sha256,
        declared_size_bytes=size_bytes,
        declared_crs="EPSG:5186",
        declared_vertical_reference=_vertical_reference(),
        declared_gsd_m=0.025,
    )


def _submission(
    artifacts: tuple[ExternalArtifactDeclarationV1, ...] | None = None,
) -> ExternalReconstructionSubmissionV1:
    submitted_at = datetime(2026, 9, 6, 3, 4, 5, tzinfo=UTC)
    return ExternalReconstructionSubmissionV1(
        submission_id="external-submission-1",
        revision=1,
        organization_id="organization-1",
        site_id="site-1",
        observation_epoch_id="epoch-1",
        submitted_at=submitted_at,
        submitted_by="operator-1",
        producer_declaration=ExternalReconstructionSubmissionV1Producer(
            software_name="Customer Reconstruction",
            software_version="2026.9",
            build_identifier=None,
            producer_run_identifier="customer-run-1",
            configuration_digest="sha256:" + _SHA_A,
            completed_at=submitted_at,
        ),
        input_declaration=ExternalReconstructionSubmissionV1Input(
            raw_media_stored_by_ksi=False,
            original_retention_locus="customer_workstation",
            local_input_manifest_digest=None,
            image_count=None,
            capture_started_at=None,
            capture_ended_at=None,
        ),
        artifacts=artifacts
        or (
            _artifact(
                "ortho-1",
                ProcessingArtifactKind.ORTHO,
                _SHA_A,
                100,
            ),
        ),
    ).sealed()


def _submission_v2(
    artifacts: tuple[ExternalArtifactDeclarationV1, ...],
) -> ExternalReconstructionSubmissionV2:
    submitted_at = datetime(2026, 9, 6, 3, 4, 5, tzinfo=UTC)
    return ExternalReconstructionSubmissionV2(
        submission_id="external-submission-v2",
        revision=1,
        organization_id="organization-1",
        site_id="site-1",
        observation_epoch_id="epoch-1",
        submitted_at=submitted_at,
        submitted_by="operator-1",
        producer_declaration=ExternalReconstructionSubmissionV1Producer(
            software_name="Customer Reconstruction",
            software_version="2026.9",
            build_identifier=None,
            producer_run_identifier="customer-run-1",
            configuration_digest="sha256:" + _SHA_A,
            completed_at=submitted_at,
        ),
        input_declaration=ExternalReconstructionSubmissionV1Input(
            raw_media_stored_by_ksi=False,
            original_retention_locus="customer_workstation",
            local_input_manifest_digest=None,
            image_count=None,
            capture_started_at=None,
            capture_ended_at=None,
        ),
        artifacts=artifacts,
    ).sealed()


def _schema(name: str) -> dict[str, Any]:
    return json.loads((_SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _unchecked_submission(
    submission: ExternalReconstructionSubmissionV1, **updates: object
) -> ExternalReconstructionSubmissionV1:
    """Forge a matching self-digest around deliberately unchecked nested state."""
    values = submission.__dict__ | updates | {"submission_digest": None}
    unsealed = ExternalReconstructionSubmissionV1.model_construct(**values)
    return unsealed.model_copy(update={"submission_digest": unsealed.canonical_digest()})


def _factory_entry() -> ExternalReconstructionManifestEntryV1:
    return ExternalReconstructionManifestEntryV1(
        artifact_id="ortho-1",
        kind=ProcessingArtifactKind.ORTHO,
        object_key="exports/ortho-1.tif",
        observed_sha256=_SHA_A,
        observed_size_bytes=100,
        observed_content_type="image/tiff",
    )


def _bind(submission: ExternalReconstructionSubmissionV1) -> ExternalReconstructionManifestV1:
    return ExternalReconstructionManifestV1.from_submission(
        submission,
        manifest_id="manifest-nested-revalidation",
        observed_at=datetime.now(UTC),
        observed_by_service="core-object-observer",
        organization_id="organization-1",
        site_id="site-1",
        observation_epoch_id="epoch-1",
        entries=(_factory_entry(),),
    )


@pytest.mark.parametrize(
    "schema_name", (_SUBMISSION_SCHEMA, _SUBMISSION_V2_SCHEMA, _MANIFEST_SCHEMA)
)
def test_schema_files_are_explicit_draft_2020_12_contracts(schema_name: str) -> None:
    """Removing the schema dialect marker must fail this contract-file test."""
    schema = _schema(schema_name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_ortho_only_submission_round_trips_its_schema_without_eligibility_claim() -> None:
    """Removing the explicit external declaration boundary must fail this test."""
    submission = _submission()

    wire = external_reconstruction_submission_wire_dict(submission)

    assert [artifact["kind"] for artifact in wire["artifacts"]] == ["ortho"]
    assert "eligible" not in wire
    assert "processingJobId" not in wire
    Draft202012Validator(_schema(_SUBMISSION_SCHEMA)).validate(wire)


def test_v2_dsm_only_and_optional_ortho_round_trip_with_order_independent_digest() -> None:
    dsm = _artifact("dsm-1", ProcessingArtifactKind.DSM, _SHA_A, 200)
    ortho = _artifact("ortho-1", ProcessingArtifactKind.ORTHO, _SHA_B, 100)
    dsm_only = _submission_v2((dsm,))
    with_ortho = _submission_v2((ortho, dsm))
    reordered = _submission_v2((dsm, ortho))

    dsm_wire = external_reconstruction_submission_v2_wire_dict(dsm_only)
    ortho_wire = external_reconstruction_submission_v2_wire_dict(with_ortho)
    assert dsm_wire["contractVersion"] == "external-reconstruction-submission.v2"
    assert [item["kind"] for item in dsm_wire["artifacts"]] == ["dsm"]
    assert [item["kind"] for item in ortho_wire["artifacts"]] == ["dsm", "ortho"]
    assert with_ortho.submission_digest == reordered.submission_digest
    assert "eligible" not in dsm_wire
    Draft202012Validator(_schema(_SUBMISSION_V2_SCHEMA)).validate(dsm_wire)
    Draft202012Validator(_schema(_SUBMISSION_V2_SCHEMA)).validate(ortho_wire)


def test_v1_manifest_binds_v2_dsm_submission_digest_and_exact_artifact() -> None:
    dsm = _artifact("dsm-1", ProcessingArtifactKind.DSM, _SHA_A, 200)
    submission = _submission_v2((dsm,))

    manifest = ExternalReconstructionManifestV1.from_submission(
        submission,
        manifest_id="manifest-v2-dsm",
        observed_at=datetime.now(UTC),
        observed_by_service="core-object-observer",
        organization_id="organization-1",
        site_id="site-1",
        observation_epoch_id="epoch-1",
        entries=(
            ExternalReconstructionManifestEntryV1(
                artifact_id="dsm-1",
                kind=ProcessingArtifactKind.DSM,
                object_key="exports/dsm-1.tif",
                observed_sha256=_SHA_A,
                observed_size_bytes=200,
                observed_content_type="image/tiff",
            ),
        ),
    )

    assert manifest.contract_version == "external-reconstruction-manifest.v1"
    assert manifest.submission_digest == submission.submission_digest
    assert [(entry.artifact_id, entry.kind) for entry in manifest.entries] == [
        ("dsm-1", ProcessingArtifactKind.DSM)
    ]
    Draft202012Validator(_schema(_MANIFEST_SCHEMA)).validate(
        external_reconstruction_manifest_wire_dict(manifest)
    )


@pytest.mark.parametrize(
    "missing_field",
    ("submissionDigest", "contractVersion", "executionResponsibility", "executionLocus"),
)
def test_v2_wire_parser_requires_schema_required_top_level_fields(missing_field: str) -> None:
    dsm = _artifact("dsm-1", ProcessingArtifactKind.DSM, _SHA_A, 200)
    wire = external_reconstruction_submission_v2_wire_dict(_submission_v2((dsm,)))
    wire.pop(missing_field)

    with pytest.raises(Exception):  # noqa: B017,PT011 - jsonschema ValidationError
        Draft202012Validator(_schema(_SUBMISSION_V2_SCHEMA)).validate(wire)
    with pytest.raises(ValueError, match=missing_field):
        parse_external_reconstruction_submission_v2(wire)


@pytest.mark.parametrize(
    ("section", "missing_field"),
    (
        ("inputDeclaration", "localInputManifestDigest"),
        ("artifacts", "declaredCrs"),
    ),
)
def test_v2_wire_parser_requires_schema_required_fields_with_model_defaults(
    section: str, missing_field: str
) -> None:
    dsm = _artifact("dsm-1", ProcessingArtifactKind.DSM, _SHA_A, 200)
    wire = external_reconstruction_submission_v2_wire_dict(_submission_v2((dsm,)))
    if section == "artifacts":
        wire[section][0].pop(missing_field)
    else:
        wire[section].pop(missing_field)

    with pytest.raises(Exception):  # noqa: B017,PT011 - jsonschema ValidationError
        Draft202012Validator(_schema(_SUBMISSION_V2_SCHEMA)).validate(wire)
    with pytest.raises(ValueError, match=missing_field):
        parse_external_reconstruction_submission_v2(wire)


def test_v2_wire_parser_rejects_null_digest_even_though_model_can_build_candidates() -> None:
    dsm = _artifact("dsm-1", ProcessingArtifactKind.DSM, _SHA_A, 200)
    wire = external_reconstruction_submission_v2_wire_dict(_submission_v2((dsm,)))
    wire["submissionDigest"] = None

    with pytest.raises(Exception):  # noqa: B017,PT011 - jsonschema ValidationError
        Draft202012Validator(_schema(_SUBMISSION_V2_SCHEMA)).validate(wire)
    with pytest.raises(ValueError, match="submissionDigest is required"):
        parse_external_reconstruction_submission_v2(wire)


def test_v2_rejects_missing_or_duplicate_dsm_and_duplicate_artifact_identity() -> None:
    dsm_a = _artifact("dsm-a", ProcessingArtifactKind.DSM, _SHA_A, 200)
    dsm_b = _artifact("dsm-b", ProcessingArtifactKind.DSM, _SHA_B, 201)
    ortho = _artifact("ortho-1", ProcessingArtifactKind.ORTHO, _SHA_A, 100)
    with pytest.raises(ValidationError, match="exactly one dsm"):
        _submission_v2((ortho,))
    with pytest.raises(ValidationError, match="at most one ortho"):
        second_ortho = _artifact("ortho-2", ProcessingArtifactKind.ORTHO, _SHA_B, 101)
        _submission_v2((dsm_a, ortho, second_ortho))
    with pytest.raises(ValidationError, match="exactly one dsm"):
        _submission_v2((dsm_a, dsm_b))
    with pytest.raises(ValidationError, match="artifactId values must be unique"):
        _submission_v2((dsm_a, _artifact("dsm-a", ProcessingArtifactKind.ORTHO, _SHA_B, 100)))
    report_a = _artifact("report-a", ProcessingArtifactKind.REPORT, _SHA_A, 50)
    report_b = _artifact("report-b", ProcessingArtifactKind.REPORT, _SHA_B, 60)
    with pytest.raises(ValidationError, match="each artifact kind may appear at most once"):
        _submission_v2((dsm_a, report_a, report_b))

    schema = Draft202012Validator(_schema(_SUBMISSION_V2_SCHEMA))
    missing_dsm = external_reconstruction_submission_v2_wire_dict(_submission_v2((dsm_a,)))
    missing_dsm["artifacts"] = [item for item in missing_dsm["artifacts"] if item["kind"] != "dsm"]
    with pytest.raises(Exception):  # noqa: B017,PT011 - jsonschema ValidationError
        schema.validate(missing_dsm)
    duplicate_dsm = external_reconstruction_submission_v2_wire_dict(_submission_v2((dsm_a,)))
    duplicate_dsm["artifacts"].append(
        external_reconstruction_submission_v2_wire_dict(_submission_v2((dsm_b,)))["artifacts"][0]
    )
    with pytest.raises(Exception):  # noqa: B017,PT011 - jsonschema ValidationError
        schema.validate(duplicate_dsm)
    duplicate_report = external_reconstruction_submission_v2_wire_dict(
        _submission_v2((dsm_a, report_a))
    )
    duplicate_report["artifacts"].append(
        external_reconstruction_submission_v2_wire_dict(
            _submission_v2((dsm_a, report_b))
        )["artifacts"][0]
    )
    with pytest.raises(Exception):  # noqa: B017,PT011 - jsonschema ValidationError
        schema.validate(duplicate_report)

    duplicate_id = external_reconstruction_submission_v2_wire_dict(
        _submission_v2((dsm_a, ortho))
    )
    duplicate_id["artifacts"][1]["artifactId"] = duplicate_id["artifacts"][0]["artifactId"]
    duplicate_id["submissionDigest"] = "sha256:" + _SHA_B
    schema.validate(duplicate_id)  # JSON Schema cannot enforce uniqueness by one property.
    with pytest.raises(ValidationError, match="artifactId values must be unique"):
        parse_external_reconstruction_submission_v2(duplicate_id)


def test_v2_rejects_forged_digest_and_v1_contract_digest_is_unchanged() -> None:
    dsm = _artifact("dsm-1", ProcessingArtifactKind.DSM, _SHA_A, 200)
    v2_wire = external_reconstruction_submission_v2_wire_dict(_submission_v2((dsm,)))
    v2_wire["artifacts"][0]["declaredSizeBytes"] = 201
    with pytest.raises(ValidationError, match="submissionDigest"):
        ExternalReconstructionSubmissionV2.model_validate(v2_wire)

    v1 = _submission()
    expected_v1_digest = (
        "sha256:cd1d1c6da7c2001014ad98b406567bd1662028c8bf5e36ec3fd508de9eeef8b9"
    )
    assert v1.submission_digest == expected_v1_digest
    v1_wire = external_reconstruction_submission_wire_dict(v1)
    assert v1_wire["contractVersion"] == "external-reconstruction-submission.v1"
    Draft202012Validator(_schema(_SUBMISSION_SCHEMA)).validate(v1_wire)


def test_submission_schema_rejects_boolean_values_for_integer_fields() -> None:
    """Relaxing JSON integer fields to accept booleans must fail this test."""
    schema = Draft202012Validator(_schema(_SUBMISSION_SCHEMA))
    revision_boolean = external_reconstruction_submission_wire_dict(_submission())
    revision_boolean["revision"] = True
    with pytest.raises(Exception):  # noqa: B017,PT011 - jsonschema ValidationError
        schema.validate(revision_boolean)

    size_boolean = external_reconstruction_submission_wire_dict(_submission())
    size_boolean["artifacts"][0]["declaredSizeBytes"] = True
    with pytest.raises(Exception):  # noqa: B017,PT011 - jsonschema ValidationError
        schema.validate(size_boolean)


def test_submission_canonical_digest_is_order_independent_and_detects_tampering() -> None:
    """Removing canonical ordering or self-digest validation must fail this test."""
    ortho = _artifact("ortho-1", ProcessingArtifactKind.ORTHO, _SHA_A, 100)
    dsm = _artifact("dsm-1", ProcessingArtifactKind.DSM, _SHA_B, 200)
    ordered = _submission((ortho, dsm))
    reordered = _submission((dsm, ortho))

    assert ordered.submission_digest == reordered.submission_digest
    assert ordered.artifacts[0].artifact_id == "dsm-1"

    tampered = external_reconstruction_submission_wire_dict(ordered)
    tampered["artifacts"][0]["declaredSizeBytes"] = 999
    with pytest.raises(ValidationError, match="submissionDigest"):
        ExternalReconstructionSubmissionV1.model_validate(tampered)


@pytest.mark.parametrize(
    "timestamp",
    ("2026-09-06T03:04:05Z", "2026-09-06T03:04:05+00:00", "2026-09-06T03:04:05.000Z"),
)
def test_digest_for_wire_uses_validated_canonical_submission_representation(timestamp: str) -> None:
    """Hashing raw timestamp or numeric spellings must fail this sealed round-trip test."""
    raw = external_reconstruction_submission_wire_dict(_submission())
    raw["submittedAt"] = timestamp
    raw["producerDeclaration"]["completedAt"] = timestamp
    raw["inputDeclaration"]["captureStartedAt"] = timestamp
    raw["inputDeclaration"]["captureEndedAt"] = timestamp
    raw["artifacts"][0]["declaredGsdM"] = 1
    raw["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(raw)

    submission = ExternalReconstructionSubmissionV1.model_validate(raw)
    wire = external_reconstruction_submission_wire_dict(submission)

    assert wire["submissionDigest"] == submission.submission_digest
    Draft202012Validator(_schema(_SUBMISSION_SCHEMA)).validate(wire)


def test_digest_for_wire_normalizes_omitted_nullable_defaults_and_whitespace() -> None:
    """Manual wire replacements instead of model canonicalization must fail this test."""
    raw = external_reconstruction_submission_wire_dict(_submission())
    raw["submittedBy"] = " operator-1 "
    for field in (
        "localInputManifestDigest",
        "imageCount",
        "captureStartedAt",
        "captureEndedAt",
    ):
        raw["inputDeclaration"].pop(field)
    for field in ("declaredCrs", "declaredVerticalReference", "declaredGsdM"):
        raw["artifacts"][0].pop(field)
    raw["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(raw)

    submission = ExternalReconstructionSubmissionV1.model_validate(raw)
    wire = external_reconstruction_submission_wire_dict(submission)

    assert wire["submittedBy"] == "operator-1"
    Draft202012Validator(_schema(_SUBMISSION_SCHEMA)).validate(wire)


def test_sealing_and_wire_revalidate_model_copy_or_construct_and_reject_stale_digest() -> None:
    """Removing pre-seal revalidation must fail this model-copy/model-construct bypass test."""
    sealed = _submission()
    stale = sealed.model_copy(update={"submission_digest": "sha256:" + _SHA_B})
    with pytest.raises(ValidationError, match="submissionDigest"):
        stale.sealed()
    with pytest.raises(ValidationError, match="submissionDigest"):
        external_reconstruction_submission_wire_dict(stale)

    unchecked = ExternalReconstructionSubmissionV1.model_construct(
        **(sealed.__dict__ | {"revision": True})
    )
    with pytest.raises(ValidationError):
        unchecked.sealed()

    manifest = ExternalReconstructionManifestV1.from_submission(
        sealed,
        manifest_id="manifest-stale",
        observed_at=datetime.now(UTC),
        observed_by_service="core-object-observer",
        organization_id="organization-1",
        site_id="site-1",
        observation_epoch_id="epoch-1",
        entries=(
            ExternalReconstructionManifestEntryV1(
                artifact_id="ortho-1",
                kind=ProcessingArtifactKind.ORTHO,
                object_key="exports/ortho-1.tif",
                observed_sha256=_SHA_A,
                observed_size_bytes=100,
                observed_content_type="image/tiff",
            ),
        ),
    )
    stale_manifest = manifest.model_copy(update={"manifest_digest": "sha256:" + _SHA_B})
    with pytest.raises(ValidationError, match="manifestDigest"):
        stale_manifest.sealed()
    with pytest.raises(ValidationError, match="manifestDigest"):
        external_reconstruction_manifest_wire_dict(stale_manifest)


def test_owned_external_declarations_are_frozen_at_the_boundary() -> None:
    """Removing frozen owned contract models must fail this mutation test."""
    submission = _submission()
    with pytest.raises(ValidationError):
        submission.producer_declaration.software_name = "reassigned"
    vertical = submission.artifacts[0].declared_vertical_reference
    assert vertical is not None
    with pytest.raises(ValidationError):
        vertical.basis = "reassigned"


def test_nullable_producer_fields_are_preserved_as_explicit_unknowns() -> None:
    """Replacing explicit producer unknowns with inferred values must fail this test."""
    raw = external_reconstruction_submission_wire_dict(_submission())
    raw["producerDeclaration"].update(
        {
            "producerRunIdentifier": None,
            "configurationDigest": None,
            "completedAt": None,
        }
    )
    raw["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(raw)

    submission = ExternalReconstructionSubmissionV1.model_validate(raw)

    assert submission.producer_declaration.producer_run_identifier is None
    assert submission.producer_declaration.configuration_digest is None
    assert submission.producer_declaration.completed_at is None
    assert external_reconstruction_submission_wire_dict(submission)["producerDeclaration"] == {
        "softwareName": "Customer Reconstruction",
        "softwareVersion": "2026.9",
        "buildIdentifier": None,
        "producerRunIdentifier": None,
        "configurationDigest": None,
        "completedAt": None,
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("inputDeclaration", "rawMediaStoredByKsi"), 0),
        (("submittedAt",), 0),
        (("submittedAt",), True),
        (("producerDeclaration", "completedAt"), 0),
        (("inputDeclaration", "captureStartedAt"), 0),
        (("inputDeclaration", "captureEndedAt"), 0),
    ],
)
def test_submission_rejects_non_boolean_custody_and_numeric_timestamps(
    path: tuple[str, ...], value: object
) -> None:
    """Removing strict wire-type guards must fail this no-inferred-claims test."""
    raw = external_reconstruction_submission_wire_dict(_submission())
    raw.pop("submissionDigest")
    target: dict[str, Any] = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    if path == ("inputDeclaration", "captureStartedAt"):
        raw["inputDeclaration"]["captureEndedAt"] = 1
    if path == ("inputDeclaration", "captureEndedAt"):
        raw["inputDeclaration"]["captureStartedAt"] = 0
    with pytest.raises(ValidationError):
        ExternalReconstructionSubmissionV1.model_validate(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("revision", True),
        ("revision", 0),
        ("submitted_at", datetime(2026, 9, 6, 3, 4, 5)),
        ("submitted_by", " "),
    ],
)
def test_submission_rejects_strict_invalid_scalar_values(field: str, value: object) -> None:
    """Removing strict scalar and aware-time checks must fail this test."""
    raw = external_reconstruction_submission_wire_dict(_submission())
    aliases = {"revision": "revision", "submitted_at": "submittedAt", "submitted_by": "submittedBy"}
    raw[aliases[field]] = value
    with pytest.raises(ValidationError):
        ExternalReconstructionSubmissionV1.model_validate(raw)


def test_submission_rejects_unsafe_or_duplicate_artifacts_and_nonfinite_gsd() -> None:
    """Removing artifact identity, path, or finite-GSD checks must fail this test."""
    with pytest.raises(ValidationError):
        _submission(
            (
                _artifact("ortho-1", ProcessingArtifactKind.ORTHO, _SHA_A, 100),
                _artifact("ortho-2", ProcessingArtifactKind.ORTHO, _SHA_B, 200),
            )
        )
    with pytest.raises(ValidationError):
        _submission(
            (
                _artifact(
                    "ortho-1",
                    ProcessingArtifactKind.ORTHO,
                    _SHA_A,
                    100,
                    filename="../escape.tif",
                ),
            )
        )
    raw = external_reconstruction_submission_wire_dict(_submission())
    raw["artifacts"][0]["declaredGsdM"] = math.inf
    with pytest.raises(ValidationError):
        ExternalReconstructionSubmissionV1.model_validate(raw)


def test_gsd_accepts_finite_json_numbers_but_rejects_booleans_and_strings() -> None:
    """Relaxing strict numeric GSD parsing must fail this declared-metadata test."""
    integer_gsd = external_reconstruction_submission_wire_dict(_submission())
    integer_gsd["artifacts"][0]["declaredGsdM"] = 1
    integer_gsd["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(
        integer_gsd
    )
    accepted = ExternalReconstructionSubmissionV1.model_validate(integer_gsd)
    assert accepted.artifacts[0].declared_gsd_m == 1.0

    for invalid_gsd in (True, "0.025"):
        raw = external_reconstruction_submission_wire_dict(_submission())
        raw["artifacts"][0]["declaredGsdM"] = invalid_gsd
        with pytest.raises(ValidationError):
            ExternalReconstructionSubmissionV1.model_validate(raw)
    raw = external_reconstruction_submission_wire_dict(_submission())
    raw["artifacts"][0]["declaredSizeBytes"] = True
    with pytest.raises(ValidationError):
        ExternalReconstructionSubmissionV1.model_validate(raw)


def test_submission_rejects_managed_authority_profile_and_invalid_capture_pair() -> None:
    """Removing anti-impersonation and ordered-capture checks must fail this test."""
    raw = external_reconstruction_submission_wire_dict(_submission())
    for forbidden in (
        "processingJobId",
        "sourceBundleDigest",
        "processingProfileId",
        "clientObjectKey",
    ):
        forged = copy.deepcopy(raw)
        forged[forbidden] = "forged"
        with pytest.raises(ValidationError):
            ExternalReconstructionSubmissionV1.model_validate(forged)

    raw["inputDeclaration"]["captureStartedAt"] = "2026-09-06T03:05:00Z"
    raw["inputDeclaration"]["captureEndedAt"] = "2026-09-06T03:04:00Z"
    with pytest.raises(ValidationError, match="capture"):
        ExternalReconstructionSubmissionV1.model_validate(raw)


def test_observed_manifest_factory_binds_exact_submission_scope_and_declared_bytes() -> None:
    """Removing factory scope/hash/size binding must fail this test."""
    submission = _submission()
    manifest = ExternalReconstructionManifestV1.from_submission(
        submission,
        manifest_id="manifest-1",
        observed_at=datetime(2026, 9, 6, 3, 6, 5, tzinfo=UTC),
        observed_by_service="core-object-observer",
        organization_id="organization-1",
        site_id="site-1",
        observation_epoch_id="epoch-1",
        entries=(
            ExternalReconstructionManifestEntryV1(
                artifact_id="ortho-1",
                kind=ProcessingArtifactKind.ORTHO,
                object_key="organizations/organization-1/exports/ortho-1.tif",
                observed_sha256=_SHA_A,
                observed_size_bytes=100,
                observed_content_type="image/tiff",
            ),
        ),
    )

    wire = external_reconstruction_manifest_wire_dict(manifest)
    assert wire["submissionDigest"] == submission.submission_digest
    assert "eligible" not in wire
    Draft202012Validator(_schema(_MANIFEST_SCHEMA)).validate(wire)

    mismatched = ExternalReconstructionManifestEntryV1(
        artifact_id="ortho-1",
        kind=ProcessingArtifactKind.ORTHO,
        object_key="organizations/organization-1/exports/ortho-1.tif",
        observed_sha256=_SHA_B,
        observed_size_bytes=100,
        observed_content_type="image/tiff",
    )
    with pytest.raises(ValueError, match="observedSha256"):
        ExternalReconstructionManifestV1.from_submission(
            submission,
            manifest_id="manifest-2",
            observed_at=datetime.now(UTC),
            observed_by_service="core-object-observer",
            organization_id="organization-1",
            site_id="site-1",
            observation_epoch_id="epoch-1",
            entries=(mismatched,),
        )
    wrong_size = mismatched.model_copy(
        update={"observed_sha256": _SHA_A, "observed_size_bytes": 101}
    )
    with pytest.raises(ValueError, match="observedSizeBytes"):
        ExternalReconstructionManifestV1.from_submission(
            submission,
            manifest_id="manifest-3",
            observed_at=datetime.now(UTC),
            observed_by_service="core-object-observer",
            organization_id="organization-1",
            site_id="site-1",
            observation_epoch_id="epoch-1",
            entries=(wrong_size,),
        )


def test_manifest_rejects_scope_substitution_unsafe_key_and_digest_tampering() -> None:
    """Removing manifest scope, relative-key, or self-digest checks must fail this test."""
    submission = _submission()
    entry = ExternalReconstructionManifestEntryV1(
        artifact_id="ortho-1",
        kind=ProcessingArtifactKind.ORTHO,
        object_key="exports/ortho-1.tif",
        observed_sha256=_SHA_A,
        observed_size_bytes=100,
        observed_content_type="image/tiff",
    )
    manifest = ExternalReconstructionManifestV1.from_submission(
        submission,
        manifest_id="manifest-1",
        observed_at=datetime.now(UTC),
        observed_by_service="core-object-observer",
        organization_id="organization-1",
        site_id="site-1",
        observation_epoch_id="epoch-1",
        entries=(entry,),
    )
    with pytest.raises(ValueError, match="organizationId"):
        ExternalReconstructionManifestV1.from_submission(
            submission,
            manifest_id="manifest-other-org",
            observed_at=datetime.now(UTC),
            observed_by_service="core-object-observer",
            organization_id="organization-2",
            site_id="site-1",
            observation_epoch_id="epoch-1",
            entries=(entry,),
        )

    for unsafe_key in (
        "../other-org/ortho.tif",
        "https://storage.invalid/ortho.tif",
        "exports/./ortho.tif",
        "exports/",
    ):
        entry_raw = entry.model_dump(by_alias=True, mode="json")
        entry_raw["objectKey"] = unsafe_key
        with pytest.raises(ValidationError):
            ExternalReconstructionManifestEntryV1.model_validate(entry_raw)
    entry_raw = entry.model_dump(by_alias=True, mode="json")
    entry_raw["observedSizeBytes"] = True
    with pytest.raises(ValidationError):
        ExternalReconstructionManifestEntryV1.model_validate(entry_raw)

    raw = external_reconstruction_manifest_wire_dict(manifest)
    raw["entries"][0]["observedSizeBytes"] = 999
    with pytest.raises(ValidationError, match="manifestDigest"):
        ExternalReconstructionManifestV1.model_validate(raw)


def test_manifest_factory_revalidates_unchecked_submission_and_entry_models() -> None:
    """Removing factory revalidation must fail this model-copy/model-construct bypass test."""
    submission = _submission()
    entry = ExternalReconstructionManifestEntryV1(
        artifact_id="ortho-1",
        kind=ProcessingArtifactKind.ORTHO,
        object_key="exports/ortho-1.tif",
        observed_sha256=_SHA_A,
        observed_size_bytes=100,
        observed_content_type="image/tiff",
    )
    unchecked_submission = ExternalReconstructionSubmissionV1.model_construct(
        **(submission.__dict__ | {"submission_digest": "sha256:" + _SHA_B})
    )
    unchecked_entry = entry.model_copy(update={"observed_size_bytes": 999})
    for rejected_submission, rejected_entry in (
        (unchecked_submission, entry),
        (submission, unchecked_entry),
    ):
        with pytest.raises((ValidationError, ValueError)):
            ExternalReconstructionManifestV1.from_submission(
                rejected_submission,
                manifest_id="manifest-unchecked",
                observed_at=datetime.now(UTC),
                observed_by_service="core-object-observer",
                organization_id="organization-1",
                site_id="site-1",
                observation_epoch_id="epoch-1",
                entries=(rejected_entry,),
            )


def test_manifest_factory_revalidates_every_owned_nested_submission_model() -> None:
    """Removing recursive owned-model revalidation must fail this forged-digest test."""
    submission = _submission()
    bad_artifact = submission.artifacts[0].model_copy(update={"file_name": "../escape.tif"})
    bad_producer = submission.producer_declaration.model_copy(update={"software_name": " "})
    bad_input = submission.input_declaration.model_copy(update={"raw_media_stored_by_ksi": 0})
    vertical = submission.artifacts[0].declared_vertical_reference
    assert vertical is not None
    bad_vertical = vertical.model_copy(update={"basis": " "})
    bad_artifact_vertical = submission.artifacts[0].model_copy(
        update={"declared_vertical_reference": bad_vertical}
    )

    for forged in (
        _unchecked_submission(submission, artifacts=(bad_artifact,)),
        _unchecked_submission(submission, producer_declaration=bad_producer),
        _unchecked_submission(submission, input_declaration=bad_input),
        _unchecked_submission(submission, artifacts=(bad_artifact_vertical,)),
    ):
        with pytest.raises(ValidationError):
            _bind(forged)


@pytest.mark.parametrize(
    ("path", "other_capture"),
    [
        (("submittedAt",), None),
        (("producerDeclaration", "completedAt"), None),
        (("inputDeclaration", "captureStartedAt"), ("captureEndedAt", "2026-09-06T03:04:05Z")),
        (("inputDeclaration", "captureEndedAt"), ("captureStartedAt", "1970-01-01T00:00:00Z")),
    ],
)
@pytest.mark.parametrize("numeric_text", ("0", "1700000000"))
def test_submission_rejects_numeric_timestamp_strings_before_datetime_parsing(
    path: tuple[str, ...], other_capture: tuple[str, str] | None, numeric_text: str
) -> None:
    """Accepting numeric timestamp strings must fail this lexical-wire test."""
    raw = external_reconstruction_submission_wire_dict(_submission())
    target: dict[str, Any] = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = numeric_text
    if other_capture is not None:
        raw["inputDeclaration"][other_capture[0]] = other_capture[1]
    raw.pop("submissionDigest")
    with pytest.raises(ValidationError):
        ExternalReconstructionSubmissionV1.model_validate(raw)


@pytest.mark.parametrize(
    "timestamp",
    ("2026-09-06T03:04:05Z", "2026-09-06T12:04:05+09:00", "2026-09-06T03:04:05.123Z"),
)
def test_submission_accepts_timezone_bearing_iso_timestamp_forms(timestamp: str) -> None:
    """Rejecting valid UTC, offset, or fractional ISO timestamps must fail this test."""
    raw = external_reconstruction_submission_wire_dict(_submission())
    raw["submittedAt"] = timestamp
    raw.pop("submissionDigest")
    assert ExternalReconstructionSubmissionV1.model_validate(raw).submitted_at.tzinfo is not None


@pytest.mark.parametrize("numeric_text", ("0", "1700000000"))
def test_manifest_rejects_numeric_timestamp_strings_before_datetime_parsing(
    numeric_text: str,
) -> None:
    """Accepting numeric observedAt strings must fail this lexical-wire test."""
    manifest = _bind(_submission())
    raw = external_reconstruction_manifest_wire_dict(manifest)
    raw["observedAt"] = numeric_text
    raw.pop("manifestDigest")
    with pytest.raises(ValidationError):
        ExternalReconstructionManifestV1.model_validate(raw)
    with pytest.raises(Exception):  # noqa: B017,PT011 - jsonschema ValidationError
        Draft202012Validator(
            _schema(_MANIFEST_SCHEMA), format_checker=FormatChecker()
        ).validate({**raw, "manifestDigest": manifest.manifest_digest})


def test_manifest_digest_is_entry_order_independent_and_factory_rejects_unbound_entries() -> None:
    """Removing entry sorting or exact artifact binding must fail this factory test."""
    submission = _submission(
        (
            _artifact("ortho-1", ProcessingArtifactKind.ORTHO, _SHA_A, 100),
            _artifact("mesh-1", ProcessingArtifactKind.MESH, _SHA_B, 200),
        )
    )
    ortho = ExternalReconstructionManifestEntryV1(
        artifact_id="ortho-1",
        kind=ProcessingArtifactKind.ORTHO,
        object_key="exports/ortho-1.tif",
        observed_sha256=_SHA_A,
        observed_size_bytes=100,
        observed_content_type="image/tiff",
    )
    mesh = ExternalReconstructionManifestEntryV1(
        artifact_id="mesh-1",
        kind=ProcessingArtifactKind.MESH,
        object_key="exports/mesh-1.glb",
        observed_sha256=_SHA_B,
        observed_size_bytes=200,
        observed_content_type="model/gltf-binary",
    )
    options: _ManifestFactoryOptions = {
        "manifest_id": "manifest-permutation",
        "observed_at": datetime.now(UTC),
        "observed_by_service": "core-object-observer",
        "organization_id": "organization-1",
        "site_id": "site-1",
        "observation_epoch_id": "epoch-1",
    }
    ordered = ExternalReconstructionManifestV1.from_submission(
        submission, entries=(ortho, mesh), **options
    )
    reordered = ExternalReconstructionManifestV1.from_submission(
        submission, entries=(mesh, ortho), **options
    )
    assert ordered.manifest_digest == reordered.manifest_digest
    wrong_kind = mesh.model_copy(update={"kind": ProcessingArtifactKind.DSM})
    unknown_id = mesh.model_copy(update={"artifact_id": "unbound-1"})
    for entries in ((ortho,), (ortho, mesh, unknown_id), (ortho, wrong_kind)):
        with pytest.raises(ValueError):
            ExternalReconstructionManifestV1.from_submission(submission, entries=entries, **options)


def test_manifest_rejects_duplicate_observed_object_key_for_distinct_artifacts() -> None:
    """Removing one-object-to-one-artifact binding must fail this test."""
    submission = _submission(
        (
            _artifact("ortho-1", ProcessingArtifactKind.ORTHO, _SHA_A, 100),
            _artifact("mesh-1", ProcessingArtifactKind.MESH, _SHA_B, 200),
        )
    )
    entries = (
        ExternalReconstructionManifestEntryV1(
            artifact_id="ortho-1",
            kind=ProcessingArtifactKind.ORTHO,
            object_key="exports/shared.bin",
            observed_sha256=_SHA_A,
            observed_size_bytes=100,
            observed_content_type="image/tiff",
        ),
        ExternalReconstructionManifestEntryV1(
            artifact_id="mesh-1",
            kind=ProcessingArtifactKind.MESH,
            object_key="exports/shared.bin",
            observed_sha256=_SHA_B,
            observed_size_bytes=200,
            observed_content_type="model/gltf-binary",
        ),
    )
    with pytest.raises(ValidationError, match="objectKey"):
        ExternalReconstructionManifestV1.from_submission(
            submission,
            manifest_id="manifest-duplicate-key",
            observed_at=datetime.now(UTC),
            observed_by_service="core-object-observer",
            organization_id="organization-1",
            site_id="site-1",
            observation_epoch_id="epoch-1",
            entries=entries,
        )


def test_schema_rejects_non_structural_contract_violations_at_the_model_layer() -> None:
    """Replacing relational model checks with schema-only validation must fail this test."""
    submission = external_reconstruction_submission_wire_dict(_submission())
    submission["artifacts"].append(copy.deepcopy(submission["artifacts"][0]))
    submission["artifacts"][1]["artifactId"] = "second-ortho"
    Draft202012Validator(_schema(_SUBMISSION_SCHEMA)).validate(submission)
    with pytest.raises(ValidationError, match="ortho"):
        ExternalReconstructionSubmissionV1.model_validate(submission)
