"""Closed, manifest-derived configuration for the future inspector runtime adapter.

This module performs no Docker, namespace, cgroup, or procfs operation.  Task 5c
must supply that host evidence before an adapter can treat this configuration as
an executable runtime.  In particular, this protocol carries Task 3's live
borrowed-FD capability and deliberately has no host pathname field.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from typing import Any

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ExternalValidationPolicyV1
from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionManifestV1,
)

from ksi_processing_controller.external_inspector_runtime import (
    CpuCounterUnitV1,
    RuntimeControlUnavailable,
    cpu_seconds_to_counter_budget,
)
from ksi_processing_controller.external_inspector_staging import (
    InspectorBorrowedSourcePort,
    InspectorReadOnlyBindV1,
)

_INNER_PROTOCOL_VERSION = "inspector-container.v1"


def compiled_inner_protocol_body_v1() -> dict[str, Any]:
    """The concrete launcher-owned inner frame grammar and attach transport."""
    return {
        "contractVersion": _INNER_PROTOCOL_VERSION,
        "canonicalization": "ksi-domain-canonical-json-bytes.v1",
        "dockerEngineApi": "1.44",
        "transport": {
            "stdin": "RAW_CANONICAL_BE32_PREPARE_THEN_EXECUTE",
            "stdoutStream": 1,
            "stderrStream": 2,
            "stdout": "CANONICAL_BE32_CONTROL_THEN_SANITIZE_RAW_BYTES",
            "stderr": "BOUNDED_AND_REQUIRED_EMPTY_AT_TERMINAL_EOF",
            "partialTransportFrameEof": "REJECT",
        },
        "sequence": ["PREPARE", "MOUNT_VERIFIED", "EXECUTE", "COMPLETED_OR_FAILED", "EOF"],
        "frames": {
            "PREPARE": {
                "fields": [
                    "protocolVersion",
                    "frame",
                    "attemptNonce",
                    "outerCanonicalInputDigest",
                    "operation",
                    "sealedByteBinding",
                    "policy",
                    "executionManifestBody",
                    "executionManifestDigest",
                    "prepareDigest",
                ],
                "prepareDigest": "SHA256_CANONICAL_JSON_EXCLUDING_PREPARE_DIGEST",
            },
            "MOUNT_VERIFIED": {
                "fields": [
                    "protocolVersion",
                    "frame",
                    "attemptNonce",
                    "outerCanonicalInputDigest",
                    "prepareDigest",
                    "artifactId",
                    "actualSizeBytes",
                    "actualSha256",
                ]
            },
            "EXECUTE": {
                "fields": [
                    "protocolVersion",
                    "frame",
                    "attemptNonce",
                    "outerCanonicalInputDigest",
                    "prepareDigest",
                    "operation",
                ]
            },
            "COMPLETED_INSPECT": {
                "fields": [
                    "protocolVersion",
                    "frame",
                    "attemptNonce",
                    "outerCanonicalInputDigest",
                    "prepareDigest",
                    "operation",
                    "inspectorBuildDigest",
                    "outcome",
                    "outputSizeBytes",
                ],
                "outputSizeBytes": 0,
            },
            "COMPLETED_SANITIZE": {
                "fields": [
                    "protocolVersion",
                    "frame",
                    "attemptNonce",
                    "outerCanonicalInputDigest",
                    "prepareDigest",
                    "operation",
                    "inspectorBuildDigest",
                    "outcome",
                    "outputSizeBytes",
                    "outputSha256",
                ],
                "rawOutput": "EXACT_DECLARED_SIZE_AND_SHA256_THEN_EOF",
            },
            "FAILED": {
                "fields": [
                    "protocolVersion",
                    "frame",
                    "attemptNonce",
                    "outerCanonicalInputDigest",
                    "prepareDigest",
                    "operation",
                    "reason",
                ]
            },
        },
    }


def compiled_inner_protocol_digest_v1() -> str:
    return _canonical_digest(compiled_inner_protocol_body_v1())


def compiled_security_profile_body_v1() -> dict[str, Any]:
    """The literal Docker API 1.44 configuration this launcher emits and rereads."""
    return {
        "contractVersion": "external-inspector-security-profile.v1",
        "canonicalization": "ksi-domain-canonical-json-bytes.v1",
        "networkDisabled": True,
        "readOnlyRootFilesystem": True,
        "privileged": False,
        "noNewPrivileges": True,
        "dropAllCapabilities": True,
        "credentialsInjected": False,
        "remoteVsiDisabled": True,
        "pluginLoadingDisabled": True,
        "gdalPamEnabled": False,
        "clearInheritedEnvironment": True,
        "dockerEngineApi": "1.44",
        "containerConfig": {
            "tty": False,
            "openStdin": True,
            "stdinOnce": True,
            "attachStdin": True,
            "attachStdout": True,
            "attachStderr": True,
            "volumes": "ABSENT_OR_EMPTY",
        },
        "hostConfig": {
            "networkMode": "none",
            "readOnlyRootfs": True,
            "privileged": False,
            "autoRemove": False,
            "groupAdd": [],
            "capAdd": [],
            "capDrop": ["ALL"],
            "securityOpt": ["no-new-privileges:true"],
            "logDriver": "none",
            "inputMount": {
                "type": "bind",
                "target": "/input/artifact.tif",
                "readOnly": True,
                "nonRecursive": True,
            },
            "workspaceTmpfs": {
                "hostConfigField": "Tmpfs",
                "target": "/work",
                "mode": "0700",
                "flags": ["rw", "nodev", "nosuid", "noexec"],
            },
            "memorySwap": "EQUAL_MEMORY",
            "cgroupParent": "JOURNALED_ATTEMPT_SLICE_UNIT_NAME",
        },
        "resourceFields": [
            "Memory",
            "MemorySwap",
            "PidsLimit",
            "CpuPeriod",
            "CpuQuota",
            "Tmpfs:/work:size",
        ],
    }


def compiled_security_profile_digest_v1() -> str:
    return _canonical_digest(compiled_security_profile_body_v1())


class ContainerInnerProtocolViolation(ValueError):
    """The fixed launcher-to-entrypoint frame is malformed, reordered, or unbound."""


@dataclass(frozen=True, slots=True)
class ContainerInnerFrameLimitsV1:
    maximum_frame_bytes: int
    maximum_stderr_bytes: int

    def __post_init__(self) -> None:
        if (
            type(self.maximum_frame_bytes) is not int
            or self.maximum_frame_bytes <= 0
            or type(self.maximum_stderr_bytes) is not int
            or self.maximum_stderr_bytes < 0
        ):
            raise ValueError("fixed inner frame limits are required")


def build_prepare_frame(
    *,
    attempt_nonce: str,
    outer_canonical_input_digest: str,
    operation: str,
    sealed_byte_binding: dict[str, Any],
    policy: ExternalValidationPolicyV1,
    manifest: InspectorExecutionManifestV1,
    admitted_backend_profile_digest: str,
    admitted_security_profile_digest: str,
    admitted_inner_protocol_digest: str,
) -> dict[str, Any]:
    """Build the complete canonical PREPARE contract without caller-selected fields."""
    manifest_digest = manifest.canonical_body_digest()
    if (
        manifest.parser_build_digest != manifest_digest
        or policy.parser_build_digest != manifest_digest
        or policy.grammar_digest != admitted_backend_profile_digest
        or manifest.body.backend_profile_digest != admitted_backend_profile_digest
        or manifest.body.security_profile_digest != admitted_security_profile_digest
        or manifest.body.inspector_protocol_digest != admitted_inner_protocol_digest
        or policy.resource_envelope_digest != manifest.body.resource_envelope_digest
        or policy.resource_envelope is None
    ):
        raise ContainerInnerProtocolViolation("admitted PREPARE bindings are inconsistent")
    frame: dict[str, Any] = {
        "protocolVersion": _INNER_PROTOCOL_VERSION,
        "frame": "PREPARE",
        "attemptNonce": attempt_nonce,
        "outerCanonicalInputDigest": outer_canonical_input_digest,
        "operation": operation,
        "sealedByteBinding": sealed_byte_binding,
        "policy": policy.model_dump(by_alias=True, mode="json"),
        "executionManifestBody": manifest.body.model_dump(by_alias=True, mode="json"),
        "executionManifestDigest": manifest_digest,
    }
    frame["prepareDigest"] = _canonical_digest(frame)
    return frame


def validate_prepare_frame(
    frame: dict[str, Any],
    *,
    expected: dict[str, Any],
    limits: ContainerInnerFrameLimitsV1,
) -> None:
    """Accept only byte-for-byte canonical equality with the admitted PREPARE frame."""
    decoded = decode_inner_frame(encode_inner_frame(frame, limits=limits), limits=limits)
    if decoded != frame or canonical_json_bytes(frame) != canonical_json_bytes(expected):
        raise ContainerInnerProtocolViolation("PREPARE frame differs from admitted binding")
    digest = frame.get("prepareDigest")
    body = {key: value for key, value in frame.items() if key != "prepareDigest"}
    if digest != _canonical_digest(body):
        raise ContainerInnerProtocolViolation("PREPARE digest is invalid")


def build_execute_frame(*, prepare: dict[str, Any]) -> dict[str, Any]:
    """EXECUTE contains only the three tokens already bound by PREPARE."""
    _require_prepare_shape(prepare)
    return {
        "protocolVersion": _INNER_PROTOCOL_VERSION,
        "frame": "EXECUTE",
        "attemptNonce": prepare["attemptNonce"],
        "outerCanonicalInputDigest": prepare["outerCanonicalInputDigest"],
        "prepareDigest": prepare["prepareDigest"],
        "operation": prepare["operation"],
    }


def validate_mount_verified_frame(
    frame: dict[str, Any],
    *,
    prepare: dict[str, Any],
    artifact_id: str,
    actual_size_bytes: int,
    actual_sha256: str,
) -> None:
    """The entrypoint must echo the one mounted sealed artifact before EXECUTE."""
    _require_prepare_shape(prepare)
    expected = {
        "protocolVersion": _INNER_PROTOCOL_VERSION,
        "frame": "MOUNT_VERIFIED",
        "attemptNonce": prepare["attemptNonce"],
        "outerCanonicalInputDigest": prepare["outerCanonicalInputDigest"],
        "prepareDigest": prepare["prepareDigest"],
        "artifactId": artifact_id,
        "actualSizeBytes": actual_size_bytes,
        "actualSha256": actual_sha256,
    }
    if canonical_json_bytes(frame) != canonical_json_bytes(expected):
        raise ContainerInnerProtocolViolation("MOUNT_VERIFIED frame differs from sealed bind")


def encode_inner_frame(frame: dict[str, Any], *, limits: ContainerInnerFrameLimitsV1) -> bytes:
    payload = canonical_json_bytes(frame)
    if len(payload) > limits.maximum_frame_bytes:
        raise ContainerInnerProtocolViolation("inner frame exceeds configured bound")
    return struct.pack(">I", len(payload)) + payload


def decode_inner_frame(payload: bytes, *, limits: ContainerInnerFrameLimitsV1) -> dict[str, Any]:
    """Decode exactly one BE32 canonical-JSON frame; trailing bytes are forbidden."""
    if len(payload) < 4:
        raise ContainerInnerProtocolViolation("inner frame header is truncated")
    length = struct.unpack(">I", payload[:4])[0]
    if length > limits.maximum_frame_bytes or len(payload) != 4 + length:
        raise ContainerInnerProtocolViolation("inner frame length is invalid")
    body = payload[4:]
    try:
        frame = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ContainerInnerProtocolViolation("inner frame JSON is invalid") from exc
    if not isinstance(frame, dict) or canonical_json_bytes(frame) != body:
        raise ContainerInnerProtocolViolation("inner frame JSON is not canonical")
    return frame


def _require_prepare_shape(prepare: dict[str, Any]) -> None:
    if (
        prepare.get("protocolVersion") != _INNER_PROTOCOL_VERSION
        or prepare.get("frame") != "PREPARE"
        or not isinstance(prepare.get("attemptNonce"), str)
        or not isinstance(prepare.get("outerCanonicalInputDigest"), str)
        or not isinstance(prepare.get("prepareDigest"), str)
        or prepare.get("operation") not in {"INSPECT", "SANITIZE"}
    ):
        raise ContainerInnerProtocolViolation("PREPARE frame shape is invalid")


def _canonical_digest(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class ContainerProtocolUnavailable(RuntimeError):
    """A fixed signed runtime cannot be represented without changing a literal."""


@dataclass(frozen=True, slots=True)
class FixedRuntimeLimitsV1:
    """The already-admitted finite limits used by the fixed runtime only."""

    max_memory_bytes: int
    max_workspace_bytes: int
    max_output_bytes: int
    max_wall_time_millis: int
    max_pids: int
    cpu_period_micros: int
    cpu_quota_micros: int
    max_log_bytes: int
    max_cpu_seconds: float

    def __post_init__(self) -> None:
        for value in (
            self.max_memory_bytes,
            self.max_workspace_bytes,
            self.max_output_bytes,
            self.max_wall_time_millis,
            self.max_pids,
            self.cpu_period_micros,
            self.cpu_quota_micros,
            self.max_log_bytes,
        ):
            if type(value) is not int or value <= 0:
                raise ContainerProtocolUnavailable(
                    "runtime limits must be positive finite integers"
                )
        if (
            type(self.max_cpu_seconds) is not float
            or not math.isfinite(self.max_cpu_seconds)
            or self.max_cpu_seconds <= 0.0
        ):
            raise ContainerProtocolUnavailable("runtime CPU limit must be positive and finite")


@dataclass(frozen=True, slots=True)
class FixedInputMountV1:
    """The single input mount remains an opaque live capability, never a host path."""

    source: InspectorBorrowedSourcePort
    target_path: str
    read_only: bool
    observed_sha256: str
    observed_size_bytes: int
    source_device: int
    source_inode: int
    reader_mapping_witness: str

    def __post_init__(self) -> None:
        if self.target_path != "/input/artifact.tif" or self.read_only is not True:
            raise ContainerProtocolUnavailable(
                "fixed runtime input mount must be read-only at /input/artifact.tif"
            )
        if not callable(getattr(self.source, "read_at", None)) or not callable(
            getattr(self.source, "consume_fd", None)
        ):
            raise ContainerProtocolUnavailable(
                "fixed runtime input mount lacks a borrowed capability"
            )
        if not isinstance(self.observed_sha256, str) or not self.observed_sha256.startswith(
            "sha256:"
        ):
            raise ContainerProtocolUnavailable("fixed runtime input digest is unavailable")
        if type(self.observed_size_bytes) is not int or self.observed_size_bytes <= 0:
            raise ContainerProtocolUnavailable("fixed runtime input size is unavailable")
        if (
            type(self.source_device) is not int
            or self.source_device < 0
            or type(self.source_inode) is not int
            or self.source_inode < 0
            or not isinstance(self.reader_mapping_witness, str)
            or not self.reader_mapping_witness
        ):
            raise ContainerProtocolUnavailable("fixed runtime input identity is unavailable")


@dataclass(frozen=True, slots=True)
class FixedContainerConfigurationV1:
    """All runtime choices are copied from one verified execution manifest."""

    image_manifest_digest: str
    image_config_digest: str
    runtime_uid: int
    runtime_gid: int
    supplementary_groups: tuple[int, ...]
    runtime_environment: tuple[tuple[str, str], ...]
    allowed_grid_digests: tuple[str, ...]
    input_mount: FixedInputMountV1
    extra_mounts: tuple[()] = ()
    socket_mounts: tuple[()] = ()
    network_disabled: bool = True
    read_only_root_filesystem: bool = True
    privileged: bool = False
    no_new_privileges: bool = True
    drop_all_capabilities: bool = True
    credentials_injected: bool = False
    remote_vsi_disabled: bool = True
    plugin_loading_disabled: bool = True
    gdal_pam_enabled: bool = False
    clear_inherited_environment: bool = True
    memory_bytes: int = 0
    tmpfs_bytes: int = 0
    swap_bytes: int = 0
    pids: int = 0
    cpu_period_micros: int = 0
    cpu_quota_micros: int = 0
    wall_time_millis: int = 0
    log_bytes: int = 0
    output_bytes: int = 0
    cpu_counter_unit: CpuCounterUnitV1 = CpuCounterUnitV1.CPU_USEC
    cpu_budget_counter: int = 0

    def __post_init__(self) -> None:
        if self.supplementary_groups:
            raise ContainerProtocolUnavailable("fixed runtime permits no supplementary groups")
        if self.extra_mounts or self.socket_mounts:
            raise ContainerProtocolUnavailable("fixed runtime permits no extra mounts or sockets")
        if (
            self.network_disabled is not True
            or self.read_only_root_filesystem is not True
            or self.privileged is not False
            or self.no_new_privileges is not True
            or self.drop_all_capabilities is not True
            or self.credentials_injected is not False
            or self.remote_vsi_disabled is not True
            or self.plugin_loading_disabled is not True
            or self.gdal_pam_enabled is not False
            or self.clear_inherited_environment is not True
        ):
            raise ContainerProtocolUnavailable("fixed runtime security literals changed")
        if self.swap_bytes != 0:
            raise ContainerProtocolUnavailable("fixed runtime swap is disabled")
        for value in (
            self.memory_bytes,
            self.tmpfs_bytes,
            self.pids,
            self.cpu_period_micros,
            self.cpu_quota_micros,
            self.wall_time_millis,
            self.log_bytes,
            self.output_bytes,
            self.cpu_budget_counter,
        ):
            if type(value) is not int or value <= 0:
                raise ContainerProtocolUnavailable("fixed runtime bound is unavailable")
        if self.cpu_counter_unit is not CpuCounterUnitV1.CPU_USEC:
            raise ContainerProtocolUnavailable("fixed runtime CPU counter unit is unavailable")


def build_fixed_container_configuration(
    *,
    manifest: InspectorExecutionManifestV1,
    limits: FixedRuntimeLimitsV1,
    input_bind: InspectorReadOnlyBindV1,
) -> FixedContainerConfigurationV1:
    """Construct one closed configuration without deriving a daemon-visible pathname."""
    body = manifest.body
    hard = body.hard_ceilings
    if (
        limits.max_memory_bytes > hard.max_memory_bytes
        or limits.max_workspace_bytes > hard.max_tmpfs_bytes
        or limits.max_output_bytes > hard.max_output_bytes
        or limits.max_wall_time_millis > hard.max_wall_time_millis
        or limits.max_pids > hard.max_pids
        or limits.cpu_period_micros != hard.cpu_period_micros
        or limits.cpu_quota_micros != hard.cpu_quota_micros
        or limits.max_log_bytes > hard.max_log_bytes
    ):
        raise ContainerProtocolUnavailable("fixed runtime limits exceed signed hard ceilings")
    try:
        cpu_budget_counter = cpu_seconds_to_counter_budget(
            limits.max_cpu_seconds, CpuCounterUnitV1.CPU_USEC
        )
    except RuntimeControlUnavailable as exc:
        raise ContainerProtocolUnavailable("fixed runtime CPU budget is unavailable") from exc
    mount = FixedInputMountV1(
        source=input_bind.source,
        target_path=input_bind.target_path,
        read_only=input_bind.read_only,
        observed_sha256=input_bind.observed_sha256,
        observed_size_bytes=input_bind.observed_size_bytes,
        source_device=input_bind.source_device,
        source_inode=input_bind.source_inode,
        reader_mapping_witness=input_bind.reader_mapping_witness,
    )
    security = body.security_profile
    return FixedContainerConfigurationV1(
        image_manifest_digest=body.image_identity.oci_manifest_digest,
        image_config_digest=body.image_identity.oci_config_digest,
        runtime_uid=body.runtime_uid,
        runtime_gid=body.runtime_gid,
        supplementary_groups=body.supplementary_groups,
        runtime_environment=body.runtime_environment,
        allowed_grid_digests=body.allowed_grid_digests,
        input_mount=mount,
        network_disabled=security.network_disabled,
        read_only_root_filesystem=security.read_only_root_filesystem,
        privileged=security.privileged,
        no_new_privileges=security.no_new_privileges,
        drop_all_capabilities=security.drop_all_capabilities,
        credentials_injected=security.credentials_injected,
        remote_vsi_disabled=security.remote_vsi_disabled,
        plugin_loading_disabled=security.plugin_loading_disabled,
        gdal_pam_enabled=security.gdal_pam_enabled,
        clear_inherited_environment=security.clear_inherited_environment,
        memory_bytes=limits.max_memory_bytes,
        tmpfs_bytes=limits.max_workspace_bytes,
        swap_bytes=0,
        pids=limits.max_pids,
        cpu_period_micros=limits.cpu_period_micros,
        cpu_quota_micros=limits.cpu_quota_micros,
        wall_time_millis=limits.max_wall_time_millis,
        log_bytes=limits.max_log_bytes,
        output_bytes=limits.max_output_bytes,
        cpu_counter_unit=CpuCounterUnitV1.CPU_USEC,
        cpu_budget_counter=cpu_budget_counter,
    )


__all__ = [
    "compiled_inner_protocol_body_v1",
    "compiled_inner_protocol_digest_v1",
    "compiled_security_profile_body_v1",
    "compiled_security_profile_digest_v1",
    "ContainerProtocolUnavailable",
    "FixedContainerConfigurationV1",
    "FixedInputMountV1",
    "FixedRuntimeLimitsV1",
    "build_fixed_container_configuration",
]
