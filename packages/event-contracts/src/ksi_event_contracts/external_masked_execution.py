"""Additive V3 masked-execution transport: admission, authorization, attempt, inputs.

Separate fenced envelope for the masked (P2) calculation path.  The numeric
V3 report (``MaskedVolumeCalculationReportV3``) carries no fence fields, so
this module carries the admission, authorization, lease attempt, and the three
ordered input capabilities that bind the exact original baseline DSM, current
DSM, and exclusion-mask bytes.

Transport rules, enforced by shape:

- Three capabilities only, ordered baseline then current then mask.  The old
  two-input V2 protocol is rejected: a two-item input, a reordered input, or
  any input that binds a V2 worker identity is a shape error.
- No URLs are provided by the client and no client URL is accepted here.
  Capabilities bind opaque artifact ids plus observed SHA-256/size and an
  expiry; Core resolves bytes through its protected storage port.
- The numeric output identity is V3 only
  (``external-masked-volume-numeric-result.v3``).  A V2 numeric identity is
  never accepted as the masked result key.
- A missing signed activation fails closed: authorization without a
  distinct activation digest is rejected, and no default is inferred.

Validity versus authority: sealed records are evidence, never permission.
Admission currentness, revocation, scope, and AI-egress are checked by Core
before admission and again at fenced completion; publication state never
rewrites numeric state.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import (
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import Digest, ResourceEnvelopeV1
from ksi_event_contracts.external_masked_volume import MaskedCalculationIdentityV3

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
Reason = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]{0,127}$"
    ),
]


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _require_opaque_artifact_id(value: str) -> str:
    lowered = value.lower()
    if (
        "://" in value
        or value.startswith(("/", "\\"))
        or ".." in value
        or "\\" in value
        or "\n" in value
        or "\r" in value
        or lowered.startswith(("http:", "https:", "s3:", "file:", "cap:"))
    ):
        raise ValueError(
            "artifactId must be an opaque identifier, never a URL, path, or capability"
        )
    return value


class _FrozenMaskedExecutionModel(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    def _payload(self, digest_field: str) -> dict[str, Any]:
        raw = self.model_dump(by_alias=True, mode="json")
        alias = self.__class__.model_fields[digest_field].alias or digest_field
        raw.pop(alias, None)
        return raw

    def _seal(self, digest_field: str) -> Self:
        return self.model_copy(update={digest_field: _digest(self._payload(digest_field))})

    @staticmethod
    def _require_utc(value: datetime, name: str) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError(f"{name} must be UTC")
        return value


class MaskedAdmissionDispositionV3(StrEnum):
    ADMIT_PROVISIONAL = "ADMIT_PROVISIONAL"
    ADMIT_EVALUATED = "ADMIT_EVALUATED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    BLOCKED = "BLOCKED"


class MaskedAdmissionV3(_FrozenMaskedExecutionModel):
    """Numeric-free suitability decision for one exact masked calculation."""

    contract_version: Literal["external-masked-execution-admission.v3"] = (
        "external-masked-execution-admission.v3"
    )
    admission_id: Text
    organization_id: Text
    site_id: Text
    work_area_id: Text
    masked_calculation_identity_digest: Digest
    source_calculation_identity_digest: Digest
    mask_binding_digest: Digest
    masked_profile_digest: Digest
    area_definition_digest: Digest
    policy_digest: Digest
    runtime_digest: Digest
    resource_envelope_digest: Digest
    activation_digest: Digest
    scope_digest: Digest
    ai_egress_digest: Digest
    disposition: MaskedAdmissionDispositionV3
    reason_codes: tuple[Reason, ...] = Field(min_length=1, max_length=64)
    assessed_at: datetime
    admission_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_exact_masked_admission(self) -> Self:
        self._require_utc(self.assessed_at, "assessedAt")
        if self.admission_digest is not None and (self.admission_digest != self.canonical_digest()):
            raise ValueError("admission digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("admission_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("admission_digest")


class MaskedExecutionAuthorizationV3(_FrozenMaskedExecutionModel):
    """Core-selected V3 limits bound to a current admission plus signed activation."""

    contract_version: Literal["external-masked-execution-authorization.v3"] = (
        "external-masked-execution-authorization.v3"
    )
    authorization_id: Text
    organization_id: Text
    masked_calculation_identity_digest: Digest
    masked_profile_digest: Digest
    mask_binding_digest: Digest
    source_calculation_identity_digest: Digest
    admission_digest: Digest
    activation_digest: Digest
    worker_principal_id: Text
    resource_envelope: ResourceEnvelopeV1
    resource_envelope_digest: Digest
    authorized_at: datetime
    execution_authorization_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_sealed_masked_execution_limits(self) -> Self:
        self._require_utc(self.authorized_at, "authorizedAt")
        envelope = self.resource_envelope
        if envelope.resource_envelope_digest is None or (
            envelope.resource_envelope_digest != envelope.canonical_digest()
        ):
            raise ValueError("resource envelope must be sealed")
        if self.resource_envelope_digest != envelope.resource_envelope_digest:
            raise ValueError("resource envelope digest does not bind the supplied envelope")
        if self.execution_authorization_digest is not None and (
            self.execution_authorization_digest != self.canonical_digest()
        ):
            raise ValueError("execution authorization digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("execution_authorization_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("execution_authorization_digest")


class MaskedExecutionAttemptV3(_FrozenMaskedExecutionModel):
    """A fenced masked-worker ownership interval for exactly one V3 authorization."""

    contract_version: Literal["external-masked-execution-attempt.v3"] = (
        "external-masked-execution-attempt.v3"
    )
    attempt_id: Text
    authorization: MaskedExecutionAuthorizationV3
    authorization_digest: Digest
    worker_instance_id: Text
    lease_acquisition_id: Text
    lease_generation: StrictInt = Field(ge=1)
    issued_at: datetime
    lease_expires_at: datetime
    execution_attempt_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_exact_authorization_and_fence_interval(self) -> Self:
        self._require_utc(self.issued_at, "issuedAt")
        self._require_utc(self.lease_expires_at, "leaseExpiresAt")
        if self.lease_expires_at <= self.issued_at:
            raise ValueError("leaseExpiresAt must be after issuedAt")
        authorization = self.authorization
        if authorization.execution_authorization_digest is None or (
            authorization.execution_authorization_digest != authorization.canonical_digest()
        ):
            raise ValueError("execution authorization must be sealed")
        if self.authorization_digest != authorization.execution_authorization_digest:
            raise ValueError("authorization digest does not bind the supplied authorization")
        if self.execution_attempt_digest is not None and (
            self.execution_attempt_digest != self.canonical_digest()
        ):
            raise ValueError("execution attempt digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("execution_attempt_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("execution_attempt_digest")


class MaskedWorkerInputCapabilityV3(_FrozenMaskedExecutionModel):
    """One Core-bound opaque input: role, artifact identity, observed bytes, expiry.

    No download URL appears here: the client never supplies URLs, and this
    transport does not borrow the V2 two-input URL protocol.  Core resolves
    bytes through its protected storage port.
    """

    role: Literal["BASELINE_DSM", "CURRENT_DSM", "EXCLUSION_MASK"]
    artifact_id: Text
    observed_sha256: Digest
    observed_size_bytes: StrictInt = Field(gt=0)
    expires_at: datetime

    @field_validator("artifact_id")
    @classmethod
    def _artifact_id_is_opaque(cls, value: str) -> str:
        return _require_opaque_artifact_id(value)

    @field_validator("expires_at")
    @classmethod
    def _expires_at_is_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("expiresAt must be UTC")
        return value


class MaskedWorkerInputV3(_FrozenMaskedExecutionModel):
    """Exact V3 attempt, masked identity, and three ordered bounded inputs."""

    contract_version: Literal["external-masked-execution-input.v3"] = (
        "external-masked-execution-input.v3"
    )
    masked_request_id: Text
    attempt: MaskedExecutionAttemptV3
    masked_calculation_identity: MaskedCalculationIdentityV3
    inputs: tuple[
        MaskedWorkerInputCapabilityV3,
        MaskedWorkerInputCapabilityV3,
        MaskedWorkerInputCapabilityV3,
    ]

    @model_validator(mode="after")
    def _binds_exact_attempt_identity_and_inputs(self) -> Self:
        identity = self.masked_calculation_identity
        if (
            identity.masked_calculation_identity_digest is None
            or identity.masked_calculation_identity_digest != identity.canonical_digest()
            or self.attempt.authorization.masked_calculation_identity_digest
            != identity.masked_calculation_identity_digest
        ):
            raise ValueError("worker input identity does not bind its exact attempt")
        baseline, current, mask = self.inputs
        if (baseline.role, current.role, mask.role) != (
            "BASELINE_DSM",
            "CURRENT_DSM",
            "EXCLUSION_MASK",
        ):
            raise ValueError("worker inputs must be ordered baseline, current, then mask")
        source = identity.source_calculation_identity
        binding = identity.mask_binding
        expected = (
            (
                source.baseline_dsm_artifact_id,
                source.baseline_dsm_observed_sha256,
                source.baseline_dsm_observed_size_bytes,
            ),
            (
                source.current_dsm_artifact_id,
                source.current_dsm_observed_sha256,
                source.current_dsm_observed_size_bytes,
            ),
            (
                binding.mask_artifact_id,
                binding.observed_sha256,
                binding.observed_size_bytes,
            ),
        )
        supplied = tuple(
            (item.artifact_id, item.observed_sha256, item.observed_size_bytes)
            for item in self.inputs
        )
        if supplied != expected:
            raise ValueError("worker capabilities do not bind the calculation identity")
        if any(item.expires_at > self.attempt.lease_expires_at for item in self.inputs):
            raise ValueError("worker capability outlives its lease")
        return self


class MaskedExecutionRuntimeV3(_FrozenMaskedExecutionModel):
    """Explicit new contained runtime identity for masked execution (all 5 pins).

    Never the old V2 ``AnalysisRuntimeIdentityV2``: a V2 runtime record cannot
    authorize the V3 lane.  The closed digest binds exactly these five fields;
    the lane constructor in :func:`masked_execution_runtime_digest` additionally
    binds the masked profile, envelope, and inspection profile/grammar.
    """

    contract_version: Literal["external-masked-execution-runtime.v3"] = (
        "external-masked-execution-runtime.v3"
    )
    worker_executable_digest: Digest
    worker_build_digest: Digest
    runtime_image_version: Text
    runtime_image_oci_digest: Digest
    dependency_lock_digest: Digest
    runtime_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_exact_runtime(self) -> Self:
        if not self.runtime_image_version.strip():
            raise ValueError("runtime image version must be non-empty")
        if self.runtime_digest is not None and (self.runtime_digest != self.canonical_digest()):
            raise ValueError("runtime digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("runtime_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("runtime_digest")


def masked_execution_runtime_digest(
    runtime: MaskedExecutionRuntimeV3,
    masked_profile_digest: str,
    resource_envelope_digest: str,
    inspection_profile_digest: str,
) -> str:
    """Closed lane runtime binding: exact 5-field worker plus profile/envelope/inspection.

    Mirrors the closed 5-field worker hash discipline (exact
    ``workerExecutableDigest``/``workerBuildDigest``/``runtimeImageVersion``/
    ``runtimeImageOciDigest``/``dependencyLockDigest`` object, no ambient
    widening) and additionally binds the independent masked profile digest,
    the resource envelope digest, and the narrow inspection profile digest.
    The signed activation's ``runtimeDigest`` must equal exactly this value;
    authority can never be derived from a desired profile alone.
    """
    sealed = MaskedExecutionRuntimeV3.model_validate(runtime.model_dump(by_alias=True))
    if sealed.runtime_digest is None or sealed.runtime_digest != sealed.canonical_digest():
        raise ValueError("execution runtime must be sealed")
    for label, value in (
        ("masked profile", masked_profile_digest),
        ("resource envelope", resource_envelope_digest),
        ("inspection profile", inspection_profile_digest),
    ):
        if _DIGEST_RE.fullmatch(value) is None:
            raise ValueError(f"{label} digest is invalid")
    return _digest(
        {
            "workerExecutableDigest": sealed.worker_executable_digest,
            "workerBuildDigest": sealed.worker_build_digest,
            "runtimeImageVersion": sealed.runtime_image_version,
            "runtimeImageOciDigest": sealed.runtime_image_oci_digest,
            "dependencyLockDigest": sealed.dependency_lock_digest,
            "maskedProfileDigest": masked_profile_digest,
            "resourceEnvelopeDigest": resource_envelope_digest,
            "inspectionProfileDigest": inspection_profile_digest,
        }
    )


def _wire(model: _FrozenMaskedExecutionModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=False)


def masked_execution_runtime_wire_dict(runtime: MaskedExecutionRuntimeV3) -> dict[str, Any]:
    return _wire(runtime.sealed())


def masked_admission_wire_dict(admission: MaskedAdmissionV3) -> dict[str, Any]:
    return _wire(admission.sealed())


def masked_execution_authorization_wire_dict(
    authorization: MaskedExecutionAuthorizationV3,
) -> dict[str, Any]:
    return _wire(authorization.sealed())


def masked_execution_attempt_wire_dict(attempt: MaskedExecutionAttemptV3) -> dict[str, Any]:
    return _wire(attempt.sealed())


def masked_worker_input_wire_dict(input_value: MaskedWorkerInputV3) -> dict[str, Any]:
    return _wire(input_value)


__all__ = [
    "MaskedAdmissionDispositionV3",
    "MaskedAdmissionV3",
    "MaskedExecutionAttemptV3",
    "MaskedExecutionAuthorizationV3",
    "MaskedExecutionRuntimeV3",
    "MaskedWorkerInputCapabilityV3",
    "MaskedWorkerInputV3",
    "masked_admission_wire_dict",
    "masked_execution_attempt_wire_dict",
    "masked_execution_authorization_wire_dict",
    "masked_execution_runtime_digest",
    "masked_execution_runtime_wire_dict",
    "masked_worker_input_wire_dict",
]
