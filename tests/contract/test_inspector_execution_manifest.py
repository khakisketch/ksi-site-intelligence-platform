"""Immutable inspector execution-manifest contract tests."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    ExternalArtifactInspectionReportV1,
    ExternalInspectionMeasurementPayloadV1,
    ExternalValidationPolicyV1,
    PolicyStatus,
    ResourceEnvelopeV1,
    SealedArtifactBindingV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionHardCeilingsV1,
    InspectorExecutionManifestBodyV1,
    InspectorExecutionManifestSignatureV1,
    InspectorExecutionManifestV1,
    InspectorImageIdentityV1,
    InspectorSecurityProfileV1,
    SignatureVerificationVerdict,
    inspector_execution_manifest_wire_dict,
    parse_inspector_execution_manifest_wire,
    validate_inspector_execution_binding,
    verify_inspector_execution_manifest_signature,
)
from pydantic import ValidationError

_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "schemas"
    / "inspector-execution-manifest.v1.json"
)


def _digest(letter: str) -> str:
    return "sha256:" + letter * 64


def _body() -> InspectorExecutionManifestBodyV1:
    """Removing an execution boundary from the signed body must break this fixture."""
    return InspectorExecutionManifestBodyV1(
        image_identity=InspectorImageIdentityV1(
            oci_manifest_digest=_digest("a"), oci_config_digest=_digest("b")
        ),
        source_tree_digest=_digest("c"),
        build_provenance_digest=_digest("d"),
        sbom_digest=_digest("e"),
        inspector_protocol_digest=_digest("f"),
        backend_profile_digest=_digest("1"),
        security_profile_digest=_digest("2"),
        resource_envelope_digest=_digest("3"),
        backend="DEDICATED_ROOTLESS_DOCKER_V1",
        runtime_uid=10001,
        runtime_gid=10001,
        supplementary_groups=(),
        runtime_environment=(
            ("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR"),
            ("GDAL_DRIVER_PATH", "disable"),
            ("GDAL_PAM_ENABLED", "NO"),
            ("PROJ_NETWORK", "OFF"),
            ("PYTHONDONTWRITEBYTECODE", "1"),
        ),
        allowed_grid_digests=(),
        security_profile=InspectorSecurityProfileV1(),
        hard_ceilings=InspectorExecutionHardCeilingsV1(
            max_input_bytes=1,
            max_memory_bytes=1,
            max_tmpfs_bytes=1,
            max_pids=1,
            cpu_period_micros=1,
            cpu_quota_micros=1,
            max_wall_time_millis=1,
            max_log_bytes=1,
            max_output_bytes=1,
        ),
    )


def test_body_has_the_independent_canonical_known_vector_and_no_hash_cycle() -> None:
    """Changing a body field or adding self/signature content would break this fixed vector."""
    body = _body()
    expected_payload = {
        "allowedGridDigests": [],
        "backend": "DEDICATED_ROOTLESS_DOCKER_V1",
        "backendProfileDigest": _digest("1"),
        "buildProvenanceDigest": _digest("d"),
        "contractVersion": "inspector-execution-manifest.v1",
        "hardCeilings": {
            "cpuPeriodMicros": 1,
            "cpuQuotaMicros": 1,
            "maxInputBytes": 1,
            "maxLogBytes": 1,
            "maxMemoryBytes": 1,
            "maxOutputBytes": 1,
            "maxPids": 1,
            "maxTmpfsBytes": 1,
            "maxWallTimeMillis": 1,
        },
        "imageIdentity": {"ociConfigDigest": _digest("b"), "ociManifestDigest": _digest("a")},
        "inspectorProtocolDigest": _digest("f"),
        "resourceEnvelopeDigest": _digest("3"),
        "runtimeEnvironment": [
            ["GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR"],
            ["GDAL_DRIVER_PATH", "disable"],
            ["GDAL_PAM_ENABLED", "NO"],
            ["PROJ_NETWORK", "OFF"],
            ["PYTHONDONTWRITEBYTECODE", "1"],
        ],
        "runtimeGid": 10001,
        "runtimeUid": 10001,
        "sbomDigest": _digest("e"),
        "securityProfile": {
            "clearInheritedEnvironment": True,
            "credentialsInjected": False,
            "dropAllCapabilities": True,
            "gdalPamEnabled": False,
            "networkDisabled": True,
            "noNewPrivileges": True,
            "pluginLoadingDisabled": True,
            "privileged": False,
            "readOnlyRootFilesystem": True,
            "remoteVsiDisabled": True,
        },
        "securityProfileDigest": _digest("2"),
        "sourceTreeDigest": _digest("c"),
        "supplementaryGroups": [],
    }
    expected_bytes = json.dumps(
        expected_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")

    assert body.contract_version == "inspector-execution-manifest.v1"
    assert body.canonical_body_bytes() == expected_bytes
    assert hashlib.sha256(expected_bytes).hexdigest() == (
        "d42b63031466a9c1d51594f0d8be8d4a0f75b871c562bdf56dad5a491ca073be"
    )
    assert body.canonical_body_digest() == (
        "sha256:d42b63031466a9c1d51594f0d8be8d4a0f75b871c562bdf56dad5a491ca073be"
    )
    assert _manifest().parser_build_digest == body.canonical_body_digest()
    assert _manifest().inspector_build_digest == body.canonical_body_digest()
    assert "signature" not in body.canonical_body_payload()
    assert "parserBuildDigest" not in body.canonical_body_payload()
    assert "inspectorBuildDigest" not in body.canonical_body_payload()


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("max_input_bytes", 0),
        ("max_memory_bytes", True),
        ("max_tmpfs_bytes", -1),
        ("max_pids", 0),
        ("cpu_period_micros", 0),
        ("cpu_quota_micros", 0),
        ("max_wall_time_millis", 0),
        ("max_log_bytes", 0),
        ("max_output_bytes", 0),
    ],
)
def test_hard_ceilings_reject_unbounded_or_non_strict_values(field: str, bad_value: object) -> None:
    """Permitting zero, negative, or boolean ceilings would make a runnable profile unbounded."""
    values = _body().hard_ceilings.model_dump()
    values[field] = bad_value

    with pytest.raises(ValidationError):
        InspectorExecutionHardCeilingsV1.model_validate(values)


def test_body_rejects_substituted_runtime_profile_choices() -> None:
    """Reject caller-controlled backend, environment, or supplementary-group choices."""
    raw = _body().model_dump()
    raw["backend"] = "BWRAP"
    with pytest.raises(ValidationError):
        InspectorExecutionManifestBodyV1.model_validate(raw)

    raw = _body().model_dump()
    raw["runtime_environment"] = (("PROJ_NETWORK", "ON"),)
    with pytest.raises(ValidationError):
        InspectorExecutionManifestBodyV1.model_validate(raw)

    raw = _body().model_dump()
    raw["supplementary_groups"] = (10002,)
    with pytest.raises(ValidationError):
        InspectorExecutionManifestBodyV1.model_validate(raw)

    raw = _body().model_dump()
    raw["image_identity"]["registry"] = "registry.example"
    with pytest.raises(ValidationError):
        InspectorExecutionManifestBodyV1.model_validate(raw)


@pytest.mark.parametrize("bad_value", [False, 0, 1, "true"])
def test_security_constants_reject_false_or_non_boolean_substitutes(bad_value: object) -> None:
    """Relaxing a mandatory safety literal would permit an unpinned security profile."""
    raw = InspectorSecurityProfileV1().model_dump()
    raw["network_disabled"] = bad_value

    with pytest.raises(ValidationError):
        InspectorSecurityProfileV1.model_validate(raw)


@pytest.mark.parametrize("bad_value", [0, 1, "true"])
def test_security_constants_reject_non_boolean_camel_case_wire_substitutes(
    bad_value: object,
) -> None:
    """Coercing camelCase wire 0/1 values would weaken the published safety boundary."""
    raw = InspectorSecurityProfileV1().model_dump(by_alias=True)
    raw["networkDisabled"] = bad_value

    with pytest.raises(ValidationError):
        InspectorSecurityProfileV1.model_validate(raw)


def test_signature_must_bind_the_body_digest_and_canonical_ed25519_bytes() -> None:
    """A signature for a different body or non-canonical key bytes must not enter the manifest."""
    body = _body()
    raw = {
        "algorithm": "Ed25519",
        "key_id": "local-test-key",
        "digest": _digest("0"),
        "signature": base64.b64encode(b"x" * 64).decode("ascii"),
    }
    signature = InspectorExecutionManifestSignatureV1.model_validate(raw)

    with pytest.raises(ValidationError, match="digest"):
        InspectorExecutionManifestV1(body=body, signature=signature)


def _manifest() -> InspectorExecutionManifestV1:
    body = _body()
    return InspectorExecutionManifestV1(
        body=body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id="local-test-key",
            digest=body.canonical_body_digest(),
            signature=base64.b64encode(b"x" * 64).decode("ascii"),
        ),
    )


def _manifest_for_body(body: InspectorExecutionManifestBodyV1) -> InspectorExecutionManifestV1:
    return InspectorExecutionManifestV1(
        body=body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id="local-test-key",
            digest=body.canonical_body_digest(),
            signature=base64.b64encode(b"x" * 64).decode("ascii"),
        ),
    )


@pytest.mark.parametrize(
    "field,replacement",
    [
        (
            "image_identity",
            InspectorImageIdentityV1(
                oci_manifest_digest=_digest("0"), oci_config_digest=_digest("b")
            ),
        ),
        ("source_tree_digest", _digest("0")),
        ("build_provenance_digest", _digest("0")),
        ("sbom_digest", _digest("0")),
        ("inspector_protocol_digest", _digest("0")),
        ("backend_profile_digest", _digest("0")),
        ("security_profile_digest", _digest("0")),
        ("resource_envelope_digest", _digest("0")),
        ("runtime_uid", 10002),
        ("runtime_gid", 10002),
        ("allowed_grid_digests", (_digest("0"),)),
        (
            "hard_ceilings",
            InspectorExecutionHardCeilingsV1(
                max_input_bytes=2,
                max_memory_bytes=1,
                max_tmpfs_bytes=1,
                max_pids=1,
                cpu_period_micros=1,
                cpu_quota_micros=1,
                max_wall_time_millis=1,
                max_log_bytes=1,
                max_output_bytes=1,
            ),
        ),
    ],
)
def test_each_bound_identity_or_profile_mutation_changes_digest_and_rejects_stale_signature(
    field: str, replacement: object
) -> None:
    """Leaving any bound identity/profile field out would permit stale signed execution."""
    manifest = _manifest()
    mutated_body = manifest.body.model_copy(update={field: replacement}, deep=True)
    stale_signature_manifest = manifest.model_copy(update={"body": mutated_body}, deep=True)

    assert mutated_body.canonical_body_digest() != manifest.canonical_body_digest()
    with pytest.raises(ValidationError, match="signature digest"):
        parse_inspector_execution_manifest_wire(
            stale_signature_manifest.model_dump(by_alias=True, mode="json")
        )


@pytest.mark.parametrize(
    "field",
    [
        "max_input_bytes",
        "max_memory_bytes",
        "max_tmpfs_bytes",
        "max_pids",
        "cpu_period_micros",
        "cpu_quota_micros",
        "max_wall_time_millis",
        "max_log_bytes",
        "max_output_bytes",
    ],
)
def test_hard_ceilings_reject_missing_required_fields(field: str) -> None:
    """Defaulting a missing execution limit would turn a signed profile into an implicit default."""
    raw = _body().hard_ceilings.model_dump()
    del raw[field]

    with pytest.raises(ValidationError):
        InspectorExecutionHardCeilingsV1.model_validate(raw)


class _Verifier:
    def __init__(self, verdict: SignatureVerificationVerdict | Exception) -> None:
        self.verdict = verdict

    def verify(
        self, payload: bytes, signature: InspectorExecutionManifestSignatureV1
    ) -> SignatureVerificationVerdict:
        assert payload == _manifest().canonical_body_bytes()
        assert signature.algorithm == "Ed25519"
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


@pytest.mark.parametrize(
    "verdict",
    [
        cast(SignatureVerificationVerdict, False),
        SignatureVerificationVerdict.INVALID,
        SignatureVerificationVerdict.UNKNOWN,
        cast(SignatureVerificationVerdict, "VALID"),
    ],
)
def test_signature_verification_fails_closed_without_a_valid_closed_verdict(
    verdict: SignatureVerificationVerdict,
) -> None:
    """Treating false, unknown, or forged verifier output as success would admit unsigned bytes."""
    assert verify_inspector_execution_manifest_signature(_manifest(), _Verifier(verdict)) is False


def test_signature_verification_accepts_only_the_explicit_valid_verdict() -> None:
    """Rejecting the verifier's sole valid closed verdict would disable the later trust boundary."""
    assert (
        verify_inspector_execution_manifest_signature(
            _manifest(), _Verifier(SignatureVerificationVerdict.VALID)
        )
        is True
    )


def test_signature_verification_fails_closed_when_the_verifier_raises() -> None:
    """Letting a trust-port exception pass would turn an unavailable verifier into authorization."""
    assert (
        verify_inspector_execution_manifest_signature(
            _manifest(), _Verifier(RuntimeError("offline"))
        )
        is False
    )


def test_nested_values_are_immutable_and_grid_digests_are_sorted_unique() -> None:
    """Reject mutable nested profile data and unordered or duplicate grid digests."""
    with pytest.raises(ValidationError, match="allowedGridDigests"):
        InspectorExecutionManifestBodyV1.model_validate(
            {
                **_body().model_dump(),
                "allowed_grid_digests": (_digest("b"), _digest("a")),
            }
        )
    with pytest.raises(ValidationError, match="allowedGridDigests"):
        InspectorExecutionManifestBodyV1.model_validate(
            {
                **_body().model_dump(),
                "allowed_grid_digests": (_digest("a"), _digest("a")),
            }
        )
    with pytest.raises(ValidationError):
        _body().hard_ceilings.max_pids = 2


def test_manifest_wire_conforms_to_the_closed_json_schema() -> None:
    """Ensure every model wire field has an equivalent published schema shape."""
    schema: dict[str, Any] = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(inspector_execution_manifest_wire_dict(_manifest()))


def test_schema_rejects_unsafe_runtime_environment_and_supplementary_groups() -> None:
    """Relaxing the schema's closed runtime choices would let another language bypass the model."""
    schema: dict[str, Any] = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    unsafe_environment = inspector_execution_manifest_wire_dict(_manifest())
    unsafe_environment["body"]["runtimeEnvironment"][3][1] = "ON"
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(unsafe_environment)

    supplementary_group = inspector_execution_manifest_wire_dict(_manifest())
    supplementary_group["body"]["supplementaryGroups"] = [10002]
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(supplementary_group)

    non_boolean_literal = inspector_execution_manifest_wire_dict(_manifest())
    non_boolean_literal["body"]["securityProfile"]["networkDisabled"] = 1
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(non_boolean_literal)


@pytest.mark.parametrize(
    "signature",
    [
        "!" + base64.b64encode(b"x" * 64).decode("ascii")[1:],
        base64.b64encode(b"x" * 64).decode("ascii")[:-2] + "AA",
        base64.b64encode(b"x" * 64).decode("ascii")[:-1],
    ],
)
def test_schema_and_model_reject_malformed_signature_syntax(signature: str) -> None:
    """Reject malformed Base64 syntax to keep the detached signature unambiguous."""
    schema: dict[str, Any] = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    wire = inspector_execution_manifest_wire_dict(_manifest())
    wire["signature"]["signature"] = signature

    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(wire)
    with pytest.raises(ValidationError):
        parse_inspector_execution_manifest_wire(wire)


def test_schema_valid_wire_still_requires_the_strict_semantic_parser() -> None:
    """Schema-only validation cannot order grids or recompute a body/signature digest."""
    schema: dict[str, Any] = json.loads(_SCHEMA.read_text(encoding="utf-8"))

    unsorted_grids = inspector_execution_manifest_wire_dict(
        _manifest_for_body(
            _body().model_copy(update={"allowed_grid_digests": (_digest("a"), _digest("b"))})
        )
    )
    unsorted_grids["body"]["allowedGridDigests"] = [_digest("b"), _digest("a")]
    Draft202012Validator(schema).validate(unsorted_grids)
    with pytest.raises(ValidationError, match="allowedGridDigests"):
        parse_inspector_execution_manifest_wire(unsorted_grids)

    mismatched_signature = inspector_execution_manifest_wire_dict(_manifest())
    mismatched_signature["signature"]["digest"] = _digest("0")
    Draft202012Validator(schema).validate(mismatched_signature)
    with pytest.raises(ValidationError, match="signature digest"):
        parse_inspector_execution_manifest_wire(mismatched_signature)


def test_parser_revalidates_a_model_copy_with_invalid_nested_hard_ceiling() -> None:
    """Trusting a model_copy bypass would allow invalid nested limits into a signed envelope."""
    manifest = _manifest()
    copied_invalid_ceiling = manifest.body.hard_ceilings.model_copy(update={"max_pids": 0})
    copied_invalid_body = manifest.body.model_copy(
        update={"hard_ceilings": copied_invalid_ceiling}, deep=True
    )
    copied_invalid_manifest = manifest.model_copy(update={"body": copied_invalid_body}, deep=True)

    with pytest.raises(ValidationError, match="maxPids"):
        parse_inspector_execution_manifest_wire(
            copied_invalid_manifest.model_dump(by_alias=True, mode="json")
        )


def _resource_envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=1,
        max_streamed_bytes=1,
        max_tiff_directories=1,
        max_tiff_entries=1,
        max_pixels=1,
        max_bands=1,
        max_blocks=1,
        max_decompressed_bytes=1,
        max_sample_bytes=1,
        max_geometry_vertices=1,
        max_cpu_seconds=1.0,
        max_memory_bytes=1,
        max_workspace_bytes=1,
        max_output_bytes=1,
        max_tenant_concurrency=1,
        max_queue_depth=1,
        max_deadline_seconds=1.0,
        lease_duration_seconds=1.0,
        max_retry_attempts=1,
    ).sealed()


def _bound_manifest_and_policy() -> tuple[InspectorExecutionManifestV1, ExternalValidationPolicyV1]:
    envelope = _resource_envelope()
    body = _body().model_copy(
        update={"resource_envelope_digest": envelope.resource_envelope_digest}, deep=True
    )
    manifest = InspectorExecutionManifestV1(
        body=body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id="local-test-key",
            digest=body.canonical_body_digest(),
            signature=base64.b64encode(b"x" * 64).decode("ascii"),
        ),
    )
    policy = ExternalValidationPolicyV1(
        policy_id="policy-1",
        version=1,
        status=PolicyStatus.DRAFT,
        parser_build_digest=manifest.canonical_body_digest(),
        grammar_digest=_digest("4"),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        inspection_rule_ids=(),
        evidence_rule_ids=(),
        compatibility_mapping_digests=(),
    ).sealed()
    return manifest, policy


def _matching_report(manifest: InspectorExecutionManifestV1) -> ExternalArtifactInspectionReportV1:
    subject = SealedExternalSubjectV1(
        organization_id="organization-1",
        site_id="site-1",
        work_order_id="work-order-1",
        submission_id="submission-1",
        revision=1,
        submission_digest=_digest("a"),
        manifest_digest=_digest("b"),
    )
    payload = ExternalInspectionMeasurementPayloadV1(
        subject_digest=subject.canonical_digest(),
        sealed_manifest_digest=subject.manifest_digest,
        inspection_policy_digest=_digest("c"),
        inspector_build_digest=manifest.canonical_body_digest(),
        artifact_bindings=(
            SealedArtifactBindingV1(artifact_id="artifact-1", observed_sha256=_digest("d")),
        ),
        outcomes=(
            ArtifactInspectionOutcomeV1(
                artifact_id="artifact-1",
                observed_sha256=_digest("d"),
                outcome=ArtifactOutcome.NOT_APPLICABLE,
                reason="UNSUPPORTED_ARTIFACT_KIND",
            ),
        ),
    )
    return ExternalArtifactInspectionReportV1(
        report_id="report-1",
        request_id="request-1",
        subject=subject,
        subject_digest=subject.canonical_digest(),
        sealed_manifest_digest=subject.manifest_digest,
        inspection_policy_digest=_digest("c"),
        inspector_build_digest=manifest.canonical_body_digest(),
        measurement_payload=payload,
        worker_instance_id="123e4567-e89b-42d3-a456-426614174000",
        lease_acquisition_id="123e4567-e89b-42d3-a456-426614174001",
        lease_generation=1,
        reported_at=datetime(2026, 9, 7, tzinfo=UTC),
    )


def test_binding_requires_exact_policy_manifest_report_and_envelope_digests() -> None:
    """Reject policy, report, or envelope digests from a different execution profile."""
    manifest, policy = _bound_manifest_and_policy()
    report = _matching_report(manifest)
    assert validate_inspector_execution_binding(policy, manifest, report) is True

    stale_policy = policy.model_copy(
        update={"parser_build_digest": _digest("0"), "policy_digest": None}
    )
    with pytest.raises(ValueError, match="parserBuildDigest"):
        validate_inspector_execution_binding(stale_policy, manifest)

    stale_payload = report.measurement_payload.model_copy(
        update={"inspector_build_digest": _digest("0")}
    )
    stale_report = report.model_copy(
        update={
            "inspector_build_digest": _digest("0"),
            "measurement_payload": stale_payload,
            "report_digest": None,
        }
    )
    with pytest.raises(ValueError, match="inspectorBuildDigest"):
        validate_inspector_execution_binding(policy, manifest, stale_report)

    stale_body = manifest.body.model_copy(update={"resource_envelope_digest": _digest("0")})
    stale_manifest = manifest.model_copy(
        update={
            "body": stale_body,
            "signature": manifest.signature.model_copy(
                update={"digest": stale_body.canonical_body_digest()}
            ),
        }
    )
    stale_envelope_policy = policy.model_copy(
        update={
            "parser_build_digest": stale_manifest.canonical_body_digest(),
            "policy_digest": None,
        }
    )
    with pytest.raises(ValueError, match="resourceEnvelopeDigest"):
        validate_inspector_execution_binding(stale_envelope_policy, stale_manifest)
