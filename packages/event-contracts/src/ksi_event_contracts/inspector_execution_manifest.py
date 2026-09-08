"""Frozen, signed inspector execution-manifest contract.

This module describes a reproducible execution profile only.  It neither
verifies cryptographic trust nor starts a container or grants policy authority.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import ConfigDict, Field, StrictInt, StringConstraints, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import (
    Digest,
    ExternalArtifactInspectionReportV1,
    ExternalValidationPolicyV1,
)

_RUNTIME_ENVIRONMENT = (
    ("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR"),
    ("GDAL_DRIVER_PATH", "disable"),
    ("GDAL_PAM_ENABLED", "NO"),
    ("PROJ_NETWORK", "OFF"),
    ("PYTHONDONTWRITEBYTECODE", "1"),
)
_KeyId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$",
    ),
]


class _FrozenManifestModel(_CamelModel):
    """Closed immutable manifest fragments, including nested profile values."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")


class InspectorImageIdentityV1(_FrozenManifestModel):
    """OCI content identity without an image name, registry, tag, URL, or path."""

    oci_manifest_digest: Digest
    oci_config_digest: Digest


class InspectorExecutionHardCeilingsV1(_FrozenManifestModel):
    """Finite hard bounds supplied by the signed profile, never runtime defaults."""

    max_input_bytes: StrictInt = Field(gt=0)
    max_memory_bytes: StrictInt = Field(gt=0)
    max_tmpfs_bytes: StrictInt = Field(gt=0)
    max_pids: StrictInt = Field(gt=0)
    cpu_period_micros: StrictInt = Field(gt=0)
    cpu_quota_micros: StrictInt = Field(gt=0)
    max_wall_time_millis: StrictInt = Field(gt=0)
    max_log_bytes: StrictInt = Field(gt=0)
    max_output_bytes: StrictInt = Field(gt=0)


class InspectorSecurityProfileV1(_FrozenManifestModel):
    """Non-negotiable parser sandbox literals recorded inside the signed body."""

    network_disabled: Literal[True] = True
    read_only_root_filesystem: Literal[True] = True
    privileged: Literal[False] = False
    no_new_privileges: Literal[True] = True
    drop_all_capabilities: Literal[True] = True
    credentials_injected: Literal[False] = False
    remote_vsi_disabled: Literal[True] = True
    plugin_loading_disabled: Literal[True] = True
    gdal_pam_enabled: Literal[False] = False
    clear_inherited_environment: Literal[True] = True

    @model_validator(mode="before")
    @classmethod
    def _require_actual_booleans(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        aliases = (
            ("network_disabled", "networkDisabled"),
            ("read_only_root_filesystem", "readOnlyRootFilesystem"),
            ("privileged", "privileged"),
            ("no_new_privileges", "noNewPrivileges"),
            ("drop_all_capabilities", "dropAllCapabilities"),
            ("credentials_injected", "credentialsInjected"),
            ("remote_vsi_disabled", "remoteVsiDisabled"),
            ("plugin_loading_disabled", "pluginLoadingDisabled"),
            ("gdal_pam_enabled", "gdalPamEnabled"),
            ("clear_inherited_environment", "clearInheritedEnvironment"),
        )
        for snake_case, camel_case in aliases:
            for name in (snake_case, camel_case):
                if name in value and type(value[name]) is not bool:
                    raise ValueError(f"{snake_case} must be a boolean safety literal")
        return value


class InspectorExecutionManifestBodyV1(_FrozenManifestModel):
    """Self-free canonical body whose SHA-256 identifies the parser build."""

    contract_version: Literal["inspector-execution-manifest.v1"] = "inspector-execution-manifest.v1"
    image_identity: InspectorImageIdentityV1
    source_tree_digest: Digest
    build_provenance_digest: Digest
    sbom_digest: Digest
    inspector_protocol_digest: Digest
    backend_profile_digest: Digest
    security_profile_digest: Digest
    resource_envelope_digest: Digest
    backend: Literal["DEDICATED_ROOTLESS_DOCKER_V1"]
    runtime_uid: StrictInt = Field(gt=0)
    runtime_gid: StrictInt = Field(gt=0)
    supplementary_groups: tuple[StrictInt, ...] = ()
    runtime_environment: tuple[tuple[str, str], ...]
    allowed_grid_digests: tuple[Digest, ...] = ()
    security_profile: InspectorSecurityProfileV1
    hard_ceilings: InspectorExecutionHardCeilingsV1

    @model_validator(mode="after")
    def _frozen_runtime_choices_are_exact(self) -> InspectorExecutionManifestBodyV1:
        if self.supplementary_groups:
            raise ValueError("supplementaryGroups must be empty")
        if self.runtime_environment != _RUNTIME_ENVIRONMENT:
            raise ValueError("runtimeEnvironment must contain the exact sorted safe environment")
        if tuple(sorted(self.allowed_grid_digests)) != self.allowed_grid_digests:
            raise ValueError("allowedGridDigests must be sorted")
        if len(set(self.allowed_grid_digests)) != len(self.allowed_grid_digests):
            raise ValueError("allowedGridDigests must be unique")
        return self

    def canonical_body_payload(self) -> dict[str, Any]:
        """Return the signature body, deliberately excluding signature and self-digests."""
        return self.model_dump(by_alias=True, mode="json")

    def canonical_body_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_body_payload())

    def canonical_body_digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.canonical_body_bytes()).hexdigest()


class InspectorExecutionManifestSignatureV1(_FrozenManifestModel):
    """Detached Ed25519 wire signature; validity is delegated to an explicit port."""

    algorithm: Literal["Ed25519"]
    key_id: _KeyId
    digest: Digest
    signature: str = Field(
        min_length=88,
        max_length=88,
        pattern=r"^[A-Za-z0-9+/]{85}[AQgw]==$",
    )

    @model_validator(mode="after")
    def _signature_is_canonical_ed25519_bytes(self) -> InspectorExecutionManifestSignatureV1:
        try:
            decoded = base64.b64decode(self.signature, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("signature must be canonical base64") from exc
        if len(decoded) != 64 or base64.b64encode(decoded).decode("ascii") != self.signature:
            raise ValueError("signature must encode exactly 64 Ed25519 bytes")
        return self

    def signature_bytes(self) -> bytes:
        return base64.b64decode(self.signature, validate=True)


class InspectorExecutionManifestV1(_FrozenManifestModel):
    """Envelope binding one immutable body to its detached signature."""

    body: InspectorExecutionManifestBodyV1
    signature: InspectorExecutionManifestSignatureV1

    @model_validator(mode="after")
    def _signature_binds_exact_body(self) -> InspectorExecutionManifestV1:
        if self.signature.digest != self.body.canonical_body_digest():
            raise ValueError("signature digest must match canonical manifest body")
        return self

    def canonical_body_payload(self) -> dict[str, Any]:
        return self.body.canonical_body_payload()

    def canonical_body_bytes(self) -> bytes:
        return self.body.canonical_body_bytes()

    def canonical_body_digest(self) -> str:
        return self.body.canonical_body_digest()

    @property
    def parser_build_digest(self) -> str:
        return self.canonical_body_digest()

    @property
    def inspector_build_digest(self) -> str:
        return self.canonical_body_digest()


class SignatureVerificationVerdict(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class InspectorExecutionManifestVerifier(Protocol):
    """Trust boundary for a later provisioned verifier; this package supplies no default."""

    def verify(
        self,
        payload: bytes,
        signature: InspectorExecutionManifestSignatureV1,
    ) -> SignatureVerificationVerdict: ...


def verify_inspector_execution_manifest_signature(
    manifest: InspectorExecutionManifestV1,
    verifier: InspectorExecutionManifestVerifier,
) -> bool:
    """Fail closed for invalid, unknown, malformed, or exceptional verifier results."""
    validated = InspectorExecutionManifestV1.model_validate(manifest.__dict__)
    try:
        return (
            verifier.verify(validated.canonical_body_bytes(), validated.signature)
            is SignatureVerificationVerdict.VALID
        )
    except Exception:
        return False


def validate_inspector_execution_binding(
    policy: ExternalValidationPolicyV1,
    manifest: InspectorExecutionManifestV1,
    report: ExternalArtifactInspectionReportV1 | None = None,
) -> bool:
    """Validate exact semantic equality only; this is neither admission nor trust proof."""
    validated_policy = ExternalValidationPolicyV1.model_validate(policy.__dict__)
    validated_manifest = InspectorExecutionManifestV1.model_validate(manifest.__dict__)
    expected_build_digest = validated_manifest.canonical_body_digest()
    if validated_policy.parser_build_digest != expected_build_digest:
        raise ValueError("policy parserBuildDigest must match manifest canonical body")
    if (
        validated_policy.resource_envelope_digest
        != validated_manifest.body.resource_envelope_digest
    ):
        raise ValueError("policy resourceEnvelopeDigest must match manifest resourceEnvelopeDigest")
    if report is not None:
        validated_report = ExternalArtifactInspectionReportV1.model_validate(report.__dict__)
        if validated_report.inspector_build_digest != expected_build_digest:
            raise ValueError("report inspectorBuildDigest must match manifest canonical body")
    return True


def inspector_execution_manifest_wire_dict(
    manifest: InspectorExecutionManifestV1,
) -> dict[str, Any]:
    """Return a revalidated complete wire envelope without deriving or sealing new data."""
    return parse_inspector_execution_manifest_wire(manifest.__dict__).model_dump(
        by_alias=True, mode="json"
    )


def parse_inspector_execution_manifest_wire(
    wire: Mapping[str, Any],
) -> InspectorExecutionManifestV1:
    """Strict structural and semantic wire parser required after JSON Schema validation.

    Draft 2020-12 cannot compare grid ordering or recompute the body/signature
    digest.  Consumers therefore must pass schema-valid wire records through
    this frozen-model parser before treating them as an execution manifest.
    """
    return InspectorExecutionManifestV1.model_validate(wire)


__all__ = [
    "InspectorExecutionHardCeilingsV1",
    "InspectorExecutionManifestBodyV1",
    "InspectorExecutionManifestSignatureV1",
    "InspectorExecutionManifestV1",
    "InspectorExecutionManifestVerifier",
    "InspectorImageIdentityV1",
    "InspectorSecurityProfileV1",
    "SignatureVerificationVerdict",
    "inspector_execution_manifest_wire_dict",
    "parse_inspector_execution_manifest_wire",
    "validate_inspector_execution_binding",
    "verify_inspector_execution_manifest_signature",
]
