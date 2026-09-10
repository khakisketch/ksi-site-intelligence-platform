"""V2 manifest admission separate from inspection policy's V1 parser identity."""

from dataclasses import dataclass
from typing import Protocol

from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionManifestV1,
    InspectorExecutionManifestVerifier,
    verify_inspector_execution_manifest_signature,
)

from ksi_processing_controller.external_inspector_container_protocol import (
    compiled_security_profile_digest_v1,
)
from ksi_processing_controller.external_inspector_launcher import (
    CatalogStartupStatusV1,
    InspectorEffectiveLimitsV1,
)
from ksi_processing_controller.external_inspector_protocol import (
    ProtocolDeadline,
    ProtocolLimitsV1,
    ProtocolViolation,
)
from ksi_processing_controller.external_measurement_protocol import (
    MeasurementLaunchRequestV2,
    compiled_measurement_backend_profile_digest_v2,
    compiled_measurement_protocol_digest_v2,
    compiled_volume_config_digest_v2,
)


class MeasurementManifestCatalogPort(Protocol):
    def startup_status(self) -> CatalogStartupStatusV1: ...

    def resolve_manifest_exact(
        self, *, execution_manifest_digest: str, resource_envelope_digest: str
    ) -> InspectorExecutionManifestV1 | None: ...

    def is_revoked(self, manifest: InspectorExecutionManifestV1) -> bool: ...


@dataclass(frozen=True, slots=True)
class MeasurementAdmissionV2:
    manifest: InspectorExecutionManifestV1
    effective_limits: InspectorEffectiveLimitsV1


def admit_measurement_request(
    request: MeasurementLaunchRequestV2,
    *,
    catalog: MeasurementManifestCatalogPort,
    verifier: InspectorExecutionManifestVerifier,
    limits: ProtocolLimitsV1,
    deadline: ProtocolDeadline,
) -> MeasurementAdmissionV2:
    """Re-resolve fixed catalog authority and derive all signed execution ceilings.

    This method is called again before create and publication. It neither stages
    input nor grants device authority. All checks consume the receiver's budget.
    """
    try:
        deadline.remaining()
        request = MeasurementLaunchRequestV2.model_validate(request.__dict__)
        status = catalog.startup_status()
        deadline.remaining()
        if not isinstance(status, CatalogStartupStatusV1) or not status.available:
            raise ProtocolViolation("measurement catalog is unavailable")
        envelope = request.validation_policy.resource_envelope
        assert envelope is not None and envelope.resource_envelope_digest is not None
        manifest = catalog.resolve_manifest_exact(
            execution_manifest_digest=request.execution_manifest_digest,
            resource_envelope_digest=envelope.resource_envelope_digest,
        )
        deadline.remaining()
        if manifest is None:
            raise ProtocolViolation("exact measurement manifest is unavailable")
        revoked = catalog.is_revoked(manifest)
        deadline.remaining()
        admit_measurement_manifest(
            request, manifest, verifier=verifier, revoked=revoked, limits=limits
        )
        deadline.remaining()
        hard = manifest.body.hard_ceilings
        effective = InspectorEffectiveLimitsV1(
            max_input_bytes=min(
                limits.max_input_bytes,
                envelope.max_input_bytes,
                envelope.max_streamed_bytes,
                hard.max_input_bytes,
            ),
            max_memory_bytes=min(envelope.max_memory_bytes, hard.max_memory_bytes),
            max_workspace_bytes=min(envelope.max_workspace_bytes, hard.max_tmpfs_bytes),
            max_output_bytes=min(
                limits.max_output_bytes, envelope.max_output_bytes, hard.max_output_bytes
            ),
            max_wall_time_millis=min(
                limits.max_wire_duration_millis,
                int(envelope.max_deadline_seconds * 1000),
                hard.max_wall_time_millis,
            ),
            max_pids=hard.max_pids,
            cpu_period_micros=hard.cpu_period_micros,
            cpu_quota_micros=hard.cpu_quota_micros,
            max_log_bytes=hard.max_log_bytes,
            max_cpu_seconds=envelope.max_cpu_seconds,
        )
        deadline.remaining()
        return MeasurementAdmissionV2(manifest=manifest, effective_limits=effective)
    except ProtocolViolation:
        raise
    except Exception as exc:
        raise ProtocolViolation("measurement admission authority is unavailable") from exc


def admit_measurement_manifest(
    request: MeasurementLaunchRequestV2,
    manifest: InspectorExecutionManifestV1,
    *,
    verifier: InspectorExecutionManifestVerifier,
    revoked: bool,
    limits: ProtocolLimitsV1,
) -> None:
    """Validate all local/signature/build ceilings before any input is staged.

    ``revoked`` must be observed from the trusted fixed catalog and rechecked
    throughout execution. This function grants no runtime/host proof by itself.
    """
    request = MeasurementLaunchRequestV2.model_validate(request.__dict__)
    manifest = InspectorExecutionManifestV1.model_validate(manifest.__dict__)
    body = manifest.body
    envelope = request.validation_policy.resource_envelope
    assert envelope is not None
    if (
        request.canonical_input_digest is None
        or type(revoked) is not bool
        or revoked
        or not verify_inspector_execution_manifest_signature(manifest, verifier)
        or body.canonical_body_digest() != request.execution_manifest_digest
        or body.inspector_protocol_digest != compiled_measurement_protocol_digest_v2()
        or body.backend_profile_digest != compiled_measurement_backend_profile_digest_v2()
        or body.security_profile_digest != compiled_security_profile_digest_v1()
        or body.resource_envelope_digest != envelope.resource_envelope_digest
    ):
        raise ProtocolViolation("V2 execution manifest authority unavailable or mismatched")
    if (
        request.volume_execution_policy is not None
        and request.volume_execution_policy.config_digest != compiled_volume_config_digest_v2()
    ):
        raise ProtocolViolation("V2 volume algorithm configuration differs")
    if request.combined_input_bytes > min(
        limits.max_input_bytes,
        body.hard_ceilings.max_input_bytes,
        envelope.max_input_bytes,
        envelope.max_streamed_bytes,
    ):
        raise ProtocolViolation("V2 combined input exceeds effective ceiling")
    if request.inputs[1].observed_size_bytes > min(
        body.hard_ceilings.max_tmpfs_bytes,
        envelope.max_workspace_bytes,
    ):
        raise ProtocolViolation("V2 secondary spool exceeds effective workspace")
