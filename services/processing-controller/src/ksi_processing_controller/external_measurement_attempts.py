"""Exact measurement attempt identity; secondary exists only inside the container.

The durable binding covers both inputs. Only primary has a registered host
allocation; terminating the exact container owns its anonymous secondary spool.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestV1

from ksi_processing_controller.external_inspector_attempts import (
    AttemptJournalError,
    AttemptPhaseV1,
    AttemptRuntimeParentRecoveryPort,
    AttemptRuntimeRecoveryPort,
    AttemptStagingRecoveryPort,
    PrivateStagingRootV1,
    RuntimeParentReceiptV1,
    StagingAllocationPlanV1,
    StagingAllocationReceiptV1,
    StagingFileIdentityV1,
    _AttemptJournalFormat,
    _AttemptRecoveryCore,
    _digest_value,
    _DurableAttemptJournalCore,
    _exact_keys,
    _integer,
    _mapping,
    _RecoverableAttempt,
    _safe_name,
    _string,
    _validate_runtime_parent_receipt,
)
from ksi_processing_controller.external_measurement_protocol import (
    MeasurementInputV2,
    MeasurementLaunchRequestV2,
)


@dataclass(frozen=True, slots=True)
class MeasurementAttemptBindingV2:
    attempt_nonce: str
    canonical_input_digest: str
    operation: str
    owner: str
    container_name: str
    systemd_slice_name: str
    systemd_base_slice: str
    execution_manifest_digest: str
    algorithm_build_digest: str
    oci_manifest_digest: str
    oci_config_digest: str
    backend_profile_digest: str
    security_profile_digest: str
    resource_envelope_digest: str
    inspector_protocol_digest: str
    cpu_budget_counter: int
    staging: StagingAllocationPlanV1
    primary_input: MeasurementInputV2
    secondary_input: MeasurementInputV2

    def __post_init__(self) -> None:
        if self.operation not in {"CHECKPOINT_VALIDATION", "RELATIVE_VOLUME", "SINGLE_VOLUME"}:
            raise ValueError("V2 operation is not a measurement")
        if self.algorithm_build_digest != self.execution_manifest_digest:
            raise ValueError("V2 algorithm build must identify its execution manifest")
        primary = MeasurementInputV2.model_validate(self.primary_input.__dict__)
        secondary = MeasurementInputV2.model_validate(self.secondary_input.__dict__)
        expected_roles = (
            ("BASELINE_DSM", "CURRENT_DSM")
            if self.operation == "RELATIVE_VOLUME"
            else ("TARGET_DSM", "CHECKPOINT_CSV")
        )
        if (primary.role, secondary.role) != expected_roles:
            raise ValueError("V2 input roles are not in fixed operation order")
        stable = hashlib.sha256(self.attempt_nonce.encode("utf-8")).hexdigest()[:32]
        if (
            self.container_name != f"external-measurement-{stable}"
            or self.systemd_slice_name != f"ksi-measurement-a{stable}.slice"
            or self.staging.staging_name != f"measurement-{stable}"
        ):
            raise ValueError("V2 runtime and primary staging namespaces must be exact")
        for value in (
            self.canonical_input_digest,
            self.execution_manifest_digest,
            self.algorithm_build_digest,
            self.oci_manifest_digest,
            self.oci_config_digest,
            self.backend_profile_digest,
            self.security_profile_digest,
            self.resource_envelope_digest,
            self.inspector_protocol_digest,
        ):
            _digest_value(value)
        for value in (
            self.attempt_nonce,
            self.operation,
            self.owner,
            self.container_name,
            self.systemd_slice_name,
            self.systemd_base_slice,
        ):
            _safe_name(value)
        if not self.systemd_slice_name.endswith(".slice") or not self.systemd_base_slice.endswith(
            ".slice"
        ):
            raise ValueError("attempt systemd units must be slice names")
        if type(self.cpu_budget_counter) is not int or self.cpu_budget_counter <= 0:
            raise ValueError("attempt CPU budget is invalid")
        if self.staging.attempt_nonce != self.attempt_nonce or self.staging.owner != self.owner:
            raise ValueError("staging plan must bind this exact attempt owner and nonce")

    def wire(self) -> dict[str, Any]:
        return {
            "attemptNonce": self.attempt_nonce,
            "canonicalInputDigest": self.canonical_input_digest,
            "operation": self.operation,
            "owner": self.owner,
            "containerName": self.container_name,
            "systemdSliceName": self.systemd_slice_name,
            "systemdBaseSlice": self.systemd_base_slice,
            "executionManifestDigest": self.execution_manifest_digest,
            "algorithmBuildDigest": self.algorithm_build_digest,
            "ociManifestDigest": self.oci_manifest_digest,
            "ociConfigDigest": self.oci_config_digest,
            "backendProfileDigest": self.backend_profile_digest,
            "securityProfileDigest": self.security_profile_digest,
            "resourceEnvelopeDigest": self.resource_envelope_digest,
            "inspectorProtocolDigest": self.inspector_protocol_digest,
            "cpuBudgetCounter": self.cpu_budget_counter,
            "staging": self.staging.wire(),
            "primaryInput": self.primary_input.model_dump(mode="json", by_alias=True),
            "secondaryInput": self.secondary_input.model_dump(mode="json", by_alias=True),
        }

    @property
    def runtime_description(self) -> str:
        return "ksi-external-measurement-attempt.v2:" + self.digest

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(canonical_json_bytes(self.wire())).hexdigest()

    @classmethod
    def from_wire(cls, value: dict[str, Any]) -> MeasurementAttemptBindingV2:
        try:
            _exact_keys(
                value,
                {
                    "attemptNonce",
                    "canonicalInputDigest",
                    "operation",
                    "owner",
                    "containerName",
                    "systemdSliceName",
                    "systemdBaseSlice",
                    "executionManifestDigest",
                    "algorithmBuildDigest",
                    "ociManifestDigest",
                    "ociConfigDigest",
                    "backendProfileDigest",
                    "securityProfileDigest",
                    "resourceEnvelopeDigest",
                    "inspectorProtocolDigest",
                    "cpuBudgetCounter",
                    "staging",
                    "primaryInput",
                    "secondaryInput",
                },
            )
            return cls(
                attempt_nonce=_string(value, "attemptNonce"),
                canonical_input_digest=_string(value, "canonicalInputDigest"),
                operation=_string(value, "operation"),
                owner=_string(value, "owner"),
                container_name=_string(value, "containerName"),
                systemd_slice_name=_string(value, "systemdSliceName"),
                systemd_base_slice=_string(value, "systemdBaseSlice"),
                execution_manifest_digest=_string(value, "executionManifestDigest"),
                algorithm_build_digest=_string(value, "algorithmBuildDigest"),
                oci_manifest_digest=_string(value, "ociManifestDigest"),
                oci_config_digest=_string(value, "ociConfigDigest"),
                backend_profile_digest=_string(value, "backendProfileDigest"),
                security_profile_digest=_string(value, "securityProfileDigest"),
                resource_envelope_digest=_string(value, "resourceEnvelopeDigest"),
                inspector_protocol_digest=_string(value, "inspectorProtocolDigest"),
                cpu_budget_counter=_integer(value, "cpuBudgetCounter"),
                staging=StagingAllocationPlanV1.from_wire(_mapping(value, "staging")),
                primary_input=MeasurementInputV2.model_validate(_mapping(value, "primaryInput")),
                secondary_input=MeasurementInputV2.model_validate(
                    _mapping(value, "secondaryInput")
                ),
            )
        except (TypeError, ValueError) as exc:
            raise AttemptJournalError("attempt binding is malformed") from exc


def new_measurement_attempt_binding(
    *,
    request: MeasurementLaunchRequestV2,
    manifest: InspectorExecutionManifestV1,
    root: PrivateStagingRootV1,
    systemd_base_slice: str,
    cpu_budget_counter: int,
    allocation_nonce: str,
) -> MeasurementAttemptBindingV2:
    request.canonical_bytes()
    if request.execution_manifest_digest != manifest.canonical_body_digest():
        raise ValueError("measurement attempt manifest differs from selected authority")
    owner = request.fence.worker_instance_id
    stable = hashlib.sha256(request.attempt_nonce.encode("utf-8")).hexdigest()[:32]
    plan_digest = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {
                    "domain": "external-measurement-primary-allocation.v2",
                    "attemptNonce": request.attempt_nonce,
                    "canonicalInputDigest": request.canonical_input_digest,
                    "owner": owner,
                    "manifest": manifest.canonical_body_digest(),
                }
            )
        ).hexdigest()
    )
    plan = StagingAllocationPlanV1(
        attempt_nonce=request.attempt_nonce,
        binding_digest=plan_digest,
        owner=owner,
        allocation_nonce=allocation_nonce,
        root=root,
        staging_name=f"measurement-{stable}",
        artifact_leaf="artifact",
        provisional_marker_name=f".measurement-{stable}.provisional",
        committed_marker_name=f".measurement-{stable}.committed",
    )
    body = manifest.body
    assert request.canonical_input_digest is not None
    return MeasurementAttemptBindingV2(
        attempt_nonce=request.attempt_nonce,
        canonical_input_digest=request.canonical_input_digest,
        operation=request.operation,
        owner=owner,
        container_name=f"external-measurement-{stable}",
        systemd_slice_name=f"ksi-measurement-a{stable}.slice",
        systemd_base_slice=systemd_base_slice,
        execution_manifest_digest=manifest.canonical_body_digest(),
        algorithm_build_digest=request.execution_manifest_digest,
        oci_manifest_digest=body.image_identity.oci_manifest_digest,
        oci_config_digest=body.image_identity.oci_config_digest,
        backend_profile_digest=body.backend_profile_digest,
        security_profile_digest=body.security_profile_digest,
        resource_envelope_digest=body.resource_envelope_digest,
        inspector_protocol_digest=body.inspector_protocol_digest,
        cpu_budget_counter=cpu_budget_counter,
        staging=plan,
        primary_input=request.inputs[0],
        secondary_input=request.inputs[1],
    )


@dataclass(frozen=True, slots=True)
class MeasurementRuntimeParentReceiptV2(RuntimeParentReceiptV1):
    def __post_init__(self) -> None:
        _validate_runtime_parent_receipt(self, "ksi-external-measurement-attempt.v2:")


@dataclass(frozen=True, slots=True)
class MeasurementRecoverableAttemptV2(
    _RecoverableAttempt[MeasurementAttemptBindingV2, MeasurementRuntimeParentReceiptV2]
):
    pass


def _validate_measurement_primary_observation(
    binding: MeasurementAttemptBindingV2,
    observed_size: int,
    observed_sha256: str,
) -> None:
    if (
        observed_size != binding.primary_input.observed_size_bytes
        or observed_sha256 != binding.primary_input.observed_sha256
    ):
        raise AttemptJournalError("observed primary differs from declared V2 input")


_MEASUREMENT_V2_FORMAT = _AttemptJournalFormat(
    "external-measurement-attempt.v2",
    MeasurementAttemptBindingV2.from_wire,
    MeasurementRuntimeParentReceiptV2.from_wire,
    _validate_measurement_primary_observation,
)


class MeasurementAttemptJournalV2:
    """Fixed-format public journal; durability lives in one private core."""

    def __init__(
        self, path: Path, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._core = _DurableAttemptJournalCore(path, clock=clock, format=_MEASUREMENT_V2_FORMAT)

    def close(self) -> None:
        return self._core.close()

    def phase_of(self, attempt_nonce: str) -> AttemptPhaseV1:
        return self._core.phase_of(attempt_nonce)

    def recoverable_attempts(self) -> tuple[MeasurementRecoverableAttemptV2, ...]:
        return tuple(
            MeasurementRecoverableAttemptV2(
                binding=item.binding,
                phase=item.phase,
                receipt=item.receipt,
                runtime_parent=item.runtime_parent,
                runtime_id=item.runtime_id,
                cleanup_disposition=item.cleanup_disposition,
                cleanup_origin=item.cleanup_origin,
            )
            for item in self._core.recoverable_attempts()
        )

    def intend(self, binding: MeasurementAttemptBindingV2) -> None:
        return self._core.intend(binding)

    def staging_allocated(self, attempt_nonce: str, receipt: StagingAllocationReceiptV1) -> None:
        return self._core.staging_allocated(attempt_nonce, receipt)

    def input_bound(
        self,
        attempt_nonce: str,
        *,
        artifact: StagingFileIdentityV1,
        observed_size_bytes: int,
        observed_sha256: str,
        reader_mapping_witness: str,
    ) -> None:
        return self._core.input_bound(
            attempt_nonce,
            artifact=artifact,
            observed_size_bytes=observed_size_bytes,
            observed_sha256=observed_sha256,
            reader_mapping_witness=reader_mapping_witness,
        )

    def container_bound(self, attempt_nonce: str, runtime_id: str) -> None:
        return self._core.container_bound(attempt_nonce, runtime_id)

    def runtime_parent_bound(self, attempt_nonce: str, receipt: RuntimeParentReceiptV1) -> None:
        return self._core.runtime_parent_bound(
            attempt_nonce, MeasurementRuntimeParentReceiptV2.from_wire(receipt.wire())
        )

    def runtime_parent_creating(self, attempt_nonce: str) -> None:
        return self._core.runtime_parent_creating(attempt_nonce)

    def container_creating(self, attempt_nonce: str) -> None:
        return self._core.container_creating(attempt_nonce)

    def cleanup_required(self, attempt_nonce: str, *, disposition: str) -> None:
        return self._core.cleanup_required(attempt_nonce, disposition=disposition)

    def ownership_uncertain(self, attempt_nonce: str) -> None:
        return self._core.ownership_uncertain(attempt_nonce)

    def cleanup_failed(self, attempt_nonce: str, *, reason: str) -> None:
        return self._core.cleanup_failed(attempt_nonce, reason=reason)

    def cleaned(self, attempt_nonce: str) -> None:
        return self._core.cleaned(attempt_nonce)


class MeasurementAttemptRecoveryV2:
    """Fixed V2 recovery facade over the shared exact ownership algorithm."""

    def __init__(
        self,
        *,
        journal: MeasurementAttemptJournalV2,
        staging: AttemptStagingRecoveryPort,
        runtime_registry: AttemptRuntimeRecoveryPort,
        runtime_parent: AttemptRuntimeParentRecoveryPort,
    ) -> None:
        self._core = _AttemptRecoveryCore(
            journal=journal,
            staging=staging,
            runtime_registry=runtime_registry,
            runtime_parent=runtime_parent,
        )

    def recover_startup(self) -> None:
        self._core.recover_startup()
