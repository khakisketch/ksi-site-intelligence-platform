"""V2 binds two opaque inputs without widening the existing V1 grammar."""

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from ksi_processing_controller.external_inspector_protocol import (
    LocalLeaseFenceV1,
    ProtocolLimitsV1,
)
from ksi_processing_controller.external_measurement_protocol import (
    MeasurementInputV2,
    MeasurementLaunchRequestV2,
    decode_measurement_header,
)
from test_external_inspector_container_entrypoint import _envelope, _manifest, _policy
from test_external_relative_volume_contracts import _policy as _volume_policy
from test_external_relative_volume_contracts import _request as _volume_request


def launch_volume() -> MeasurementLaunchRequestV2:
    envelope = _envelope()
    validation_policy = _policy(_manifest(envelope), envelope)
    execution = (
        _volume_policy()
        .model_copy(
            update={
                "resource_envelope_digest": envelope.resource_envelope_digest,
                "policy_digest": None,
            }
        )
        .sealed()
    )
    volume = (
        _volume_request()
        .model_copy(
            update={
                "validation_policy_digest": validation_policy.policy_digest,
                "execution_policy_digest": execution.policy_digest,
                "request_digest": None,
            }
        )
        .sealed()
    )
    inputs = (
        MeasurementInputV2(
            role="BASELINE_DSM",
            artifact_id=volume.baseline.dsm_artifact_id,
            observed_sha256=volume.baseline.observed_sha256,
            observed_size_bytes=volume.baseline.observed_size_bytes,
        ),
        MeasurementInputV2(
            role="CURRENT_DSM",
            artifact_id=volume.current.dsm_artifact_id,
            observed_sha256=volume.current.observed_sha256,
            observed_size_bytes=volume.current.observed_size_bytes,
        ),
    )
    return MeasurementLaunchRequestV2(
        operation="RELATIVE_VOLUME",
        inputs=inputs,
        validation_policy=validation_policy,
        volume_request=volume,
        volume_execution_policy=execution,
        checkpoint_request=None,
        evidence_context=None,
        volume_evidence_records=(),
        fence=LocalLeaseFenceV1(
            worker_instance_id=str(uuid4()), lease_acquisition_id=str(uuid4()), lease_generation=1
        ),
        attempt_nonce=str(uuid4()),
    ).sealed()


def limits() -> ProtocolLimitsV1:
    return ProtocolLimitsV1(
        max_header_bytes=128 * 1024,
        max_chunk_bytes=1024,
        max_input_bytes=1024,
        max_output_bytes=128 * 1024,
        max_wire_duration_millis=1000,
    )


def test_v2_roundtrip_and_combined_input_bound() -> None:
    request = launch_volume()
    assert request.volume_execution_policy is not None
    assert request.volume_request is not None
    assert decode_measurement_header(request.canonical_bytes(), limits()) == request
    assert request.combined_input_bytes == 256
    with pytest.raises(ValueError):
        decode_measurement_header(
            request.canonical_bytes(), limits().model_copy(update={"max_input_bytes": 200})
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda w: w.update(protocolVersion="inspector-launch.v1"),
        lambda w: w.update(operation="INSPECT"),
        lambda w: w.update(inputs=list(reversed(w["inputs"]))),
        lambda w: w["inputs"][1].update(observedSha256="sha256:" + "f" * 64),
        lambda w: w.update(extraPath="/etc/passwd"),
        lambda w: w.update(canonicalInputDigest=None),
    ],
)
def test_v2_rejects_downgrade_binding_and_extra_fields(
    mutation: Any,
) -> None:
    from ksi_domain.canonical_json import canonical_json_bytes

    wire = launch_volume().model_dump(by_alias=True, mode="json")
    mutation(wire)
    with pytest.raises(ValueError):
        decode_measurement_header(canonical_json_bytes(wire), limits())


def measurement_manifest_request() -> tuple[Any, MeasurementLaunchRequestV2]:
    import base64

    from ksi_event_contracts.inspector_execution_manifest import (
        InspectorExecutionManifestSignatureV1,
        InspectorExecutionManifestV1,
    )
    from ksi_processing_controller.external_measurement_protocol import (
        compiled_measurement_backend_profile_digest_v2,
        compiled_measurement_protocol_digest_v2,
        compiled_volume_config_digest_v2,
    )

    request = launch_volume()
    assert request.volume_execution_policy is not None
    assert request.volume_request is not None
    body = _manifest(_envelope()).body.model_copy(
        update={
            "inspector_protocol_digest": compiled_measurement_protocol_digest_v2(),
            "backend_profile_digest": compiled_measurement_backend_profile_digest_v2(),
        }
    )
    manifest = InspectorExecutionManifestV1(
        body=body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id="synthetic-key",
            digest=body.canonical_body_digest(),
            signature=base64.b64encode(b"x" * 64).decode(),
        ),
    )
    execution = request.volume_execution_policy.model_copy(
        update={
            "algorithm_build_digest": body.canonical_body_digest(),
            "config_digest": compiled_volume_config_digest_v2(),
            "policy_digest": None,
        }
    ).sealed()
    volume = request.volume_request.model_copy(
        update={
            "execution_policy_digest": execution.policy_digest,
            "request_digest": None,
        }
    ).sealed()
    request = request.model_copy(
        update={
            "volume_execution_policy": execution,
            "volume_request": volume,
            "canonical_input_digest": None,
        }
    ).sealed()
    return manifest, request


@pytest.mark.parametrize("revoked,valid", [(False, True), (True, True), (False, False)])
def test_measurement_manifest_requires_signature_and_nonrevocation(
    revoked: bool, valid: bool
) -> None:
    from ksi_event_contracts.inspector_execution_manifest import SignatureVerificationVerdict
    from ksi_processing_controller.external_measurement_admission import admit_measurement_manifest

    manifest, request = measurement_manifest_request()

    class Verifier:
        def verify(self, payload: bytes, signature: Any) -> Any:
            assert payload == manifest.canonical_body_bytes()
            return (
                SignatureVerificationVerdict.VALID
                if valid
                else SignatureVerificationVerdict.INVALID
            )

    if revoked or not valid:
        with pytest.raises(ValueError):
            admit_measurement_manifest(
                request, manifest, verifier=Verifier(), revoked=revoked, limits=limits()
            )
    else:
        admit_measurement_manifest(
            request, manifest, verifier=Verifier(), revoked=False, limits=limits()
        )
        # Inspection parser identity stays distinct from the measurement runtime.
        assert request.validation_policy.parser_build_digest != request.execution_manifest_digest


def test_measurement_rejects_v1_manifest_even_with_exact_new_build_selection() -> None:
    from ksi_event_contracts.inspector_execution_manifest import SignatureVerificationVerdict
    from ksi_processing_controller.external_measurement_admission import admit_measurement_manifest

    request = launch_volume()
    manifest = _manifest(_envelope())
    assert request.volume_execution_policy is not None
    assert request.volume_request is not None
    execution = request.volume_execution_policy.model_copy(
        update={
            "algorithm_build_digest": manifest.canonical_body_digest(),
            "policy_digest": None,
        }
    ).sealed()
    volume = request.volume_request.model_copy(
        update={
            "execution_policy_digest": execution.policy_digest,
            "request_digest": None,
        }
    ).sealed()
    request = request.model_copy(
        update={
            "volume_request": volume,
            "volume_execution_policy": execution,
            "canonical_input_digest": None,
        }
    ).sealed()

    class Verifier:
        def verify(self, payload: bytes, signature: Any) -> Any:
            return SignatureVerificationVerdict.VALID

    with pytest.raises(ValueError, match="manifest"):
        admit_measurement_manifest(
            request, manifest, verifier=Verifier(), revoked=False, limits=limits()
        )


def test_v2_header_rejects_noncanonical_json_whitespace() -> None:
    from ksi_processing_controller.external_inspector_protocol import ProtocolViolation

    request = launch_volume()
    payload = b" " + request.canonical_bytes()
    with pytest.raises(ProtocolViolation):
        decode_measurement_header(payload, limits())


def launch_single_volume() -> MeasurementLaunchRequestV2:
    """One sealed SINGLE_VOLUME launch: TARGET_DSM primary plus one bound record."""
    from datetime import UTC, datetime

    from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
    from ksi_event_contracts.external_evidence import (
        EvidenceCoreVerdict,
        ExternalEvidenceMeasurementPayloadV1,
        ExternalEvidenceRecordV1,
    )
    from ksi_event_contracts.external_relative_volume import (
        ExternalVolumeInputBindingV1,
        ExternalVolumeZoneSnapshotV1,
    )
    from ksi_event_contracts.external_single_volume import (
        ExternalSingleVolumeExecutionPolicyV1,
        ExternalSingleVolumeRequestV1,
    )

    envelope = _envelope()
    validation_policy = _policy(_manifest(envelope), envelope)
    assert validation_policy.policy_digest is not None
    assert validation_policy.resource_envelope_digest is not None
    now = datetime(2026, 9, 9, 1, 2, 3, tzinfo=UTC)
    subject = SealedExternalSubjectV1(
        organization_id="organization-1",
        site_id="site-1",
        work_order_id="work-order-1",
        submission_id="submission-1",
        revision=1,
        submission_digest="sha256:" + "a" * 64,
        manifest_digest="sha256:" + "b" * 64,
    )
    zone = ExternalVolumeZoneSnapshotV1(
        organization_id="organization-1",
        site_id="site-1",
        work_area_id="work-area-1",
        revision=1,
        polygon={
            "type": "Polygon",
            "coordinates": [[[0.0, 2.0], [2.0, 2.0], [2.0, 0.0], [0.0, 0.0], [0.0, 2.0]]],
        },
        crs="EPSG:5186",
        observed_crs_digest="sha256:" + "c" * 64,
        analysis_vertical_reference_digest="sha256:" + "d" * 64,
    ).sealed()
    target = ExternalVolumeInputBindingV1(
        subject=subject,
        inspection_report_digest="sha256:" + "e" * 64,
        dsm_artifact_id="dsm-target-1",
        observed_sha256="sha256:" + "f" * 64,
        observed_size_bytes=128,
        observed_crs_digest="sha256:" + "c" * 64,
        observed_vertical_reference_digest="sha256:" + "d" * 64,
        captured_from=now - timedelta(hours=2),
        captured_to=now - timedelta(hours=1),
    )
    execution = ExternalSingleVolumeExecutionPolicyV1(
        policy_id="single-volume-policy-1",
        version=1,
        algorithm_build_digest="sha256:" + "1" * 64,
        config_digest="sha256:" + "2" * 64,
        threshold_m=0.0,
        minimum_common_valid_fraction=1.0,
        minimum_boundary_valid_fraction=0.8,
        uncertainty_method="SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1",
        base_surface_method="BOUNDARY_LINEAR_INTERPOLATION_V1",
        resource_envelope_digest=validation_policy.resource_envelope_digest,
        authority_record_digest="sha256:" + "4" * 64,
        synthetic_test_only=True,
    ).sealed()
    assert execution.policy_digest is not None
    payload = ExternalEvidenceMeasurementPayloadV1(
        validation_id="validation-single-0",
        evidence_manifest_digest="sha256:" + "0" * 64,
        target_dsm_observed_sha256=target.observed_sha256,
        policy_digest=validation_policy.policy_digest,
        measured_checkpoint_count=3,
        mean_error_m=0.0,
        mae_m=0.1,
        rmse_m=0.1,
        max_abs_error_m=0.1,
        measured_at=now,
    )
    record = ExternalEvidenceRecordV1(
        evidence_record_id="record-single-0",
        validation_id=payload.validation_id,
        subject_digest=subject.canonical_digest(),
        evidence_manifest_digest=payload.evidence_manifest_digest,
        target_dsm_observed_sha256=target.observed_sha256,
        policy_digest=validation_policy.policy_digest,
        measurement_payload=payload,
        core_verdict=EvidenceCoreVerdict.VALIDATED,
        core_recorded_at=payload.measured_at,
    ).sealed()
    assert record.evidence_record_digest is not None
    single = ExternalSingleVolumeRequestV1(
        request_id="external-single-volume-1",
        current_work_order_id="work-order-1",
        decision_id="single-volume-decision-1",
        decision_digest="sha256:" + "5" * 64,
        target=target,
        evidence_record_digests=(record.evidence_record_digest,),
        validation_policy_digest=validation_policy.policy_digest,
        execution_policy_digest=execution.policy_digest,
        zone_snapshot=zone,
        issued_at=now,
        idempotency_key="single-volume-idempotency-1",
    ).sealed()
    return MeasurementLaunchRequestV2(
        operation="SINGLE_VOLUME",
        inputs=(
            MeasurementInputV2(
                role="TARGET_DSM",
                artifact_id=target.dsm_artifact_id,
                observed_sha256=target.observed_sha256,
                observed_size_bytes=target.observed_size_bytes,
            ),
            MeasurementInputV2(
                role="CHECKPOINT_CSV",
                artifact_id="checkpoint-evidence-1",
                observed_sha256="sha256:" + "c" * 64,
                observed_size_bytes=128,
            ),
        ),
        validation_policy=validation_policy,
        volume_request=None,
        volume_execution_policy=None,
        checkpoint_request=None,
        evidence_context=None,
        volume_evidence_records=(record,),
        single_volume_request=single,
        single_volume_execution_policy=execution,
        fence=LocalLeaseFenceV1(
            worker_instance_id=str(uuid4()), lease_acquisition_id=str(uuid4()), lease_generation=1
        ),
        attempt_nonce=str(uuid4()),
    ).sealed()


def single_volume_manifest_request() -> tuple[Any, MeasurementLaunchRequestV2]:
    """Bind the single-volume execution authority to the signed manifest body."""
    import base64

    from ksi_event_contracts.inspector_execution_manifest import (
        InspectorExecutionManifestSignatureV1,
        InspectorExecutionManifestV1,
    )
    from ksi_processing_controller.external_measurement_protocol import (
        compiled_measurement_backend_profile_digest_v2,
        compiled_measurement_protocol_digest_v2,
        compiled_single_volume_config_digest_v2,
    )

    request = launch_single_volume()
    assert request.single_volume_request is not None
    assert request.single_volume_execution_policy is not None
    body = _manifest(_envelope()).body.model_copy(
        update={
            "inspector_protocol_digest": compiled_measurement_protocol_digest_v2(),
            "backend_profile_digest": compiled_measurement_backend_profile_digest_v2(),
        }
    )
    manifest = InspectorExecutionManifestV1(
        body=body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id="synthetic-key",
            digest=body.canonical_body_digest(),
            signature=base64.b64encode(b"x" * 64).decode(),
        ),
    )
    execution = request.single_volume_execution_policy.model_copy(
        update={
            "algorithm_build_digest": body.canonical_body_digest(),
            "config_digest": compiled_single_volume_config_digest_v2(),
            "policy_digest": None,
        }
    ).sealed()
    single = request.single_volume_request.model_copy(
        update={
            "execution_policy_digest": execution.policy_digest,
            "request_digest": None,
        }
    ).sealed()
    request = request.model_copy(
        update={
            "single_volume_execution_policy": execution,
            "single_volume_request": single,
            "canonical_input_digest": None,
        }
    ).sealed()
    return manifest, request


def test_single_volume_launch_round_trip_and_sealed_bindings() -> None:
    request = launch_single_volume()
    assert request.single_volume_request is not None
    assert request.single_volume_execution_policy is not None
    assert request.request_id == request.single_volume_request.request_id
    assert request.request_id == "external-single-volume-1"
    assert (
        request.execution_manifest_digest
        == request.single_volume_execution_policy.algorithm_build_digest
    )
    assert [item.role for item in request.inputs] == ["TARGET_DSM", "CHECKPOINT_CSV"]
    assert decode_measurement_header(request.canonical_bytes(), limits()) == request
    assert len(request.volume_evidence_records) == 1
    record = request.volume_evidence_records[0]
    assert record.evidence_record_digest is not None
    assert record.evidence_record_digest == record.canonical_digest()
    assert (record.evidence_record_digest,) == request.single_volume_request.evidence_record_digests


def test_single_volume_rejects_conflicting_family_fields() -> None:
    from datetime import UTC, datetime

    from ksi_event_contracts.external_evidence import ExternalEvidenceValidationRequestV1

    base = launch_single_volume()
    assert base.single_volume_request is not None
    assert base.validation_policy.policy_digest is not None
    with pytest.raises(ValueError, match="conflicting"):
        base.model_copy(update={"volume_request": launch_volume().volume_request}).sealed()
    checkpoint = ExternalEvidenceValidationRequestV1(
        validation_id="checkpoint-validation-1",
        evidence_manifest_digest="sha256:" + "c" * 64,
        subject_digest="sha256:" + "d" * 64,
        target_dsm_observed_sha256="sha256:" + "e" * 64,
        policy_id=base.validation_policy.policy_id,
        policy_version=base.validation_policy.version,
        policy_digest=base.validation_policy.policy_digest,
        issued_at=datetime(2026, 9, 9, 1, tzinfo=UTC),
        idempotency_key="checkpoint-idempotency-1",
    )
    with pytest.raises(ValueError, match="conflicting"):
        base.model_copy(update={"checkpoint_request": checkpoint}).sealed()


@pytest.mark.parametrize(
    "roles", [(("CHECKPOINT_CSV", "TARGET_DSM")), (("BASELINE_DSM", "CURRENT_DSM"))]
)
def test_single_volume_rejects_wrong_role_order(roles: tuple[str, str]) -> None:
    base = launch_single_volume()
    swapped = (
        base.inputs[0].model_copy(update={"role": roles[0]}),
        base.inputs[1].model_copy(update={"role": roles[1]}),
    )
    with pytest.raises(ValueError, match="bindings differ"):
        base.model_copy(update={"inputs": swapped, "canonical_input_digest": None}).sealed()


@pytest.mark.parametrize("field", ["artifact_id", "observed_sha256", "observed_size_bytes"])
def test_single_volume_rejects_primary_identity_mismatch(field: str) -> None:
    base = launch_single_volume()
    if field == "artifact_id":
        mutated = base.inputs[0].model_copy(update={"artifact_id": "other-artifact"})
    elif field == "observed_sha256":
        mutated = base.inputs[0].model_copy(update={"observed_sha256": "sha256:" + "0" * 64})
    else:
        mutated = base.inputs[0].model_copy(update={"observed_size_bytes": 129})
    with pytest.raises(ValueError, match="bindings differ"):
        base.model_copy(
            update={"inputs": (mutated, base.inputs[1]), "canonical_input_digest": None}
        ).sealed()


def test_single_volume_requires_exactly_one_sealed_evidence_record() -> None:
    from ksi_event_contracts.external_evidence import EvidenceCoreVerdict

    base = launch_single_volume()
    assert base.single_volume_request is not None
    record = base.volume_evidence_records[0]
    with pytest.raises(ValueError, match="exactly one"):
        base.model_copy(
            update={"volume_evidence_records": (), "canonical_input_digest": None}
        ).sealed()
    with pytest.raises(ValueError, match="exactly one"):
        base.model_copy(
            update={
                "volume_evidence_records": (record, record),
                "canonical_input_digest": None,
            }
        ).sealed()
    unsealed = record.model_copy(update={"evidence_record_digest": None})
    with pytest.raises(ValueError, match="differs from its target or policy"):
        base.model_copy(
            update={"volume_evidence_records": (unsealed,), "canonical_input_digest": None}
        ).sealed()
    forged = record.model_copy(update={"evidence_record_digest": "sha256:" + "9" * 64})
    with pytest.raises(ValueError, match="does not match canonical evidence record"):
        base.model_copy(
            update={"volume_evidence_records": (forged,), "canonical_input_digest": None}
        ).sealed()
    assert EvidenceCoreVerdict.VALIDATED is not None


@pytest.mark.parametrize("kind", ["subject", "target", "policy"])
def test_single_volume_rejects_record_subject_target_policy_mismatch(kind: str) -> None:
    base = launch_single_volume()
    record = base.volume_evidence_records[0]
    if kind == "subject":
        mutated = record.model_copy(
            update={"subject_digest": "sha256:" + "9" * 64, "evidence_record_digest": None}
        ).sealed()
    elif kind == "target":
        digest = "sha256:" + "9" * 64
        assert record.measurement_payload is not None
        mutated = record.model_copy(
            update={
                "target_dsm_observed_sha256": digest,
                "measurement_payload": record.measurement_payload.model_copy(
                    update={"target_dsm_observed_sha256": digest}
                ),
                "evidence_record_digest": None,
            }
        ).sealed()
    else:
        digest = "sha256:" + "9" * 64
        assert record.measurement_payload is not None
        mutated = record.model_copy(
            update={
                "policy_digest": digest,
                "measurement_payload": record.measurement_payload.model_copy(
                    update={"policy_digest": digest}
                ),
                "evidence_record_digest": None,
            }
        ).sealed()
    with pytest.raises(ValueError, match="differs from its target or policy"):
        base.model_copy(
            update={"volume_evidence_records": (mutated,), "canonical_input_digest": None}
        ).sealed()


@pytest.mark.parametrize(
    "kind", ["execution_policy_digest", "validation_policy_digest", "resource_envelope_digest"]
)
def test_single_volume_rejects_policy_digest_mismatch(kind: str) -> None:
    base = launch_single_volume()
    assert base.single_volume_request is not None
    assert base.single_volume_execution_policy is not None
    if kind == "execution_policy_digest":
        single = base.single_volume_request.model_copy(
            update={
                "execution_policy_digest": "sha256:" + "9" * 64,
                "request_digest": None,
            }
        ).sealed()
        with pytest.raises(ValueError, match="execution bindings differ"):
            base.model_copy(
                update={"single_volume_request": single, "canonical_input_digest": None}
            ).sealed()
    elif kind == "validation_policy_digest":
        single = base.single_volume_request.model_copy(
            update={
                "validation_policy_digest": "sha256:" + "9" * 64,
                "request_digest": None,
            }
        ).sealed()
        with pytest.raises(ValueError, match="execution bindings differ"):
            base.model_copy(
                update={"single_volume_request": single, "canonical_input_digest": None}
            ).sealed()
    else:
        execution = base.single_volume_execution_policy.model_copy(
            update={
                "resource_envelope_digest": "sha256:" + "9" * 64,
                "policy_digest": None,
            }
        ).sealed()
        single = base.single_volume_request.model_copy(
            update={
                "execution_policy_digest": execution.policy_digest,
                "request_digest": None,
            }
        ).sealed()
        with pytest.raises(ValueError, match="execution bindings differ"):
            base.model_copy(
                update={
                    "single_volume_execution_policy": execution,
                    "single_volume_request": single,
                    "canonical_input_digest": None,
                }
            ).sealed()
