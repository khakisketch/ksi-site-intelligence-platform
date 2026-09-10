"""V2 binds two opaque inputs without widening the existing V1 grammar."""

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
