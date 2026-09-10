"""Strict, versioned operator configuration for the inspector launcher.

The configuration contains public paths, identifiers, capacities, and pinned
digests only.  It intentionally has no credentials, backend selector, command,
image name, URL, environment override, or dynamic import hook.
"""

from __future__ import annotations

import base64
import json
import os
import re
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Never

from ksi_event_contracts.inspector_execution_manifest import (
    SignatureVerificationVerdict,
    parse_inspector_execution_manifest_wire,
)

from ksi_processing_controller.external_inspector_access import UserNamespaceMappingConfigV1
from ksi_processing_controller.external_inspector_catalog import (
    Ed25519InspectorManifestVerifier,
    FileInspectorCatalogConfigV1,
    FileInspectorManifestCatalog,
    InspectorTrustRootV1,
)
from ksi_processing_controller.external_inspector_container_protocol import (
    ContainerInnerFrameLimitsV1,
)
from ksi_processing_controller.external_inspector_daemon import (
    InspectorAdmissionCapacityV1,
    ProductionInspectorConfigV1,
    SystemdActivatedListenerConfigV1,
)
from ksi_processing_controller.external_inspector_docker import (
    CgroupV2RootConfigV1,
    DockerCgroupMeasurementConfigV1,
    FileLocalOciPairResolver,
    FileOciPairResolverConfigV1,
    RootlessDockerSocketConfigV1,
)
from ksi_processing_controller.external_inspector_host_proof import (
    RootlessDockerHostProofConfigV1,
)
from ksi_processing_controller.external_inspector_protocol import ProtocolLimitsV1
from ksi_processing_controller.external_inspector_systemd import UserSystemdBusConfigV1

_VERSION = "external-inspector-operator-config.v1"
_MAX_CONFIG_BYTES = 256 * 1024
_MAX_TEXT = 4096
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")


class OperatorConfigBlockedCode(StrEnum):
    CONFIG_FILE = "CONFIG_FILE"
    CONFIG_SYNTAX = "CONFIG_SYNTAX"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    CONFIG_VALUE = "CONFIG_VALUE"
    CATALOG = "CATALOG"
    OCI_EVIDENCE = "OCI_EVIDENCE"


class OperatorConfigUnavailable(RuntimeError):
    """Non-secret configuration/preflight reason that prevents daemon startup."""

    def __init__(self, code: OperatorConfigBlockedCode) -> None:
        self.code = code
        super().__init__("external inspector operator configuration blocked: " + code.value)


@dataclass(frozen=True, slots=True)
class ExternalInspectorOperatorConfigV1:
    production: ProductionInspectorConfigV1
    host_proof: RootlessDockerHostProofConfigV1


def load_external_inspector_operator_config(path: Path) -> ExternalInspectorOperatorConfigV1:
    """Read one regular 0600 config through a descriptor, with no fallback source."""

    raw = _read_config_file(path)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_SYNTAX) from exc
    try:
        body = _mapping(value, {"version", "production", "hostProof"})
        if _text(body["version"]) != _VERSION:
            raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE)
        config = ExternalInspectorOperatorConfigV1(
            production=_parse_production(_mapping(body["production"], _PRODUCTION_FIELDS)),
            host_proof=_parse_host_proof(_mapping(body["hostProof"], _HOST_PROOF_FIELDS)),
        )
        _validate_cross_binding(config)
        return config
    except OperatorConfigUnavailable:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE) from exc


def validate_operator_startup_artifacts(config: ExternalInspectorOperatorConfigV1) -> None:
    """Prove signed catalog/revocation and offline OCI records before daemon assembly."""

    try:
        catalog = FileInspectorManifestCatalog(config.production.catalog)
        status = catalog.startup_status()
        if not (
            status.readable is True
            and status.trust_root_configured is True
            and status.catalog_identity_verified is True
        ):
            raise ValueError("catalog startup status is closed")
        manifest_raw = config.production.catalog.manifest_artifact.read()
        manifest_wire = json.loads(
            manifest_raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(manifest_wire, dict):
            raise ValueError("manifest wire is not an object")
        manifest = parse_inspector_execution_manifest_wire(manifest_wire)
        verifier = Ed25519InspectorManifestVerifier(config.production.trust_root)
        if verifier.verify(
            manifest.canonical_body_bytes(), manifest.signature
        ) is not SignatureVerificationVerdict.VALID or catalog.is_revoked(manifest):
            raise ValueError("catalog signature or revocation rejected")
    except (OSError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CATALOG) from exc
    try:
        resolver = FileLocalOciPairResolver(config.production.oci_pairs)
        resolver.resolve_exact(
            manifest_digest=manifest.body.image_identity.oci_manifest_digest,
            config_digest=manifest.body.image_identity.oci_config_digest,
        )
    except Exception as exc:
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.OCI_EVIDENCE) from exc


_PRODUCTION_FIELDS = {
    "requiredWorkerUid",
    "listener",
    "catalog",
    "trustRoot",
    "inputRoot",
    "outputRoot",
    "readerMapping",
    "journalPath",
    "dockerSocket",
    "ociPairs",
    "cgroupRoot",
    "systemdBus",
    "systemdBaseSlice",
    "recoveryTimeoutMillis",
    "admissionCapacity",
    "protocolLimits",
    "frameLimits",
    "cgroupMeasurement",
}
_HOST_PROOF_FIELDS = {
    "launcherUid",
    "launcherGid",
    "workerUid",
    "rootlessDaemonPidPath",
    "daemonUidMapSha256",
    "daemonGidMapSha256",
    "launcherCgroupPath",
    "daemonCgroupPath",
    "systemdBaseSlice",
    "dockerSocketPath",
    "retainedInputMode",
}


def _parse_production(value: dict[str, Any]) -> ProductionInspectorConfigV1:
    listener = _mapping(value["listener"], {"socketPath", "expectedOwnerUid"})
    catalog = _mapping(
        value["catalog"], {"manifestPath", "revocationPath", "expectedRevocationSha256"}
    )
    trust_root = _mapping(value["trustRoot"], {"publicKeys"})
    reader_mapping = _mapping(
        value["readerMapping"], {"uidMapPath", "gidMapPath", "maximumMapBytes"}
    )
    docker_socket = _mapping(
        value["dockerSocket"],
        {"socketPath", "expectedOwnerUid", "expectedMode", "maximumResponseBytes"},
    )
    oci_pairs = _mapping(value["ociPairs"], {"proofPath", "expectedSha256"})
    cgroup_root = _mapping(value["cgroupRoot"], {"root", "baseControlGroup", "maximumControlBytes"})
    systemd_bus = _mapping(
        value["systemdBus"],
        {"busKind", "socketPath", "expectedOwnerUid", "expectedMode", "timeoutMicros"},
    )
    admission = _mapping(
        value["admissionCapacity"],
        {"maximumRequestUnits", "maximumConcurrencyUnits", "maximumSpoolBytes"},
    )
    protocol = _mapping(
        value["protocolLimits"],
        {
            "maxHeaderBytes",
            "maxChunkBytes",
            "maxInputBytes",
            "maxOutputBytes",
            "maxWireDurationMillis",
        },
    )
    frame = _mapping(value["frameLimits"], {"maximumFrameBytes", "maximumStderrBytes"})
    measurement = _mapping(
        value["cgroupMeasurement"],
        {"monitorIntervalMillis", "stableFinalSamples", "cleanupTimeoutMillis"},
    )
    return ProductionInspectorConfigV1(
        required_worker_uid=_integer(value["requiredWorkerUid"]),
        listener=SystemdActivatedListenerConfigV1(
            socket_path=_path(listener["socketPath"]),
            expected_owner_uid=_integer(listener["expectedOwnerUid"]),
        ),
        catalog=FileInspectorCatalogConfigV1(
            manifest_path=_path(catalog["manifestPath"]),
            revocation_path=_path(catalog["revocationPath"]),
            expected_revocation_sha256=_digest(catalog["expectedRevocationSha256"]),
        ),
        trust_root=InspectorTrustRootV1(_public_keys(trust_root["publicKeys"])),
        input_root=_path(value["inputRoot"]),
        output_root=_path(value["outputRoot"]),
        reader_mapping=UserNamespaceMappingConfigV1(
            uid_map_path=_path(reader_mapping["uidMapPath"]),
            gid_map_path=_path(reader_mapping["gidMapPath"]),
            maximum_map_bytes=_integer(reader_mapping["maximumMapBytes"]),
        ),
        journal_path=_path(value["journalPath"]),
        docker_socket=RootlessDockerSocketConfigV1(
            socket_path=_path(docker_socket["socketPath"]),
            expected_owner_uid=_integer(docker_socket["expectedOwnerUid"]),
            expected_mode=_integer(docker_socket["expectedMode"]),
            maximum_response_bytes=_integer(docker_socket["maximumResponseBytes"]),
        ),
        oci_pairs=FileOciPairResolverConfigV1(
            proof_path=_path(oci_pairs["proofPath"]),
            expected_sha256=_digest(oci_pairs["expectedSha256"]),
        ),
        cgroup_root=CgroupV2RootConfigV1(
            root=_path(cgroup_root["root"]),
            base_control_group=_text(cgroup_root["baseControlGroup"]),
            maximum_control_bytes=_integer(cgroup_root["maximumControlBytes"]),
        ),
        systemd_bus=UserSystemdBusConfigV1(
            bus_kind=_text(systemd_bus["busKind"]),
            socket_path=_path(systemd_bus["socketPath"]),
            expected_owner_uid=_integer(systemd_bus["expectedOwnerUid"]),
            expected_mode=_integer(systemd_bus["expectedMode"]),
            timeout_micros=_integer(systemd_bus["timeoutMicros"]),
        ),
        systemd_base_slice=_text(value["systemdBaseSlice"]),
        recovery_timeout_millis=_integer(value["recoveryTimeoutMillis"]),
        admission_capacity=InspectorAdmissionCapacityV1(
            maximum_request_units=_integer(admission["maximumRequestUnits"]),
            maximum_concurrency_units=_integer(admission["maximumConcurrencyUnits"]),
            maximum_spool_bytes=_integer(admission["maximumSpoolBytes"]),
        ),
        protocol_limits=ProtocolLimitsV1(
            max_header_bytes=_integer(protocol["maxHeaderBytes"]),
            max_chunk_bytes=_integer(protocol["maxChunkBytes"]),
            max_input_bytes=_integer(protocol["maxInputBytes"]),
            max_output_bytes=_integer(protocol["maxOutputBytes"]),
            max_wire_duration_millis=_integer(protocol["maxWireDurationMillis"]),
        ),
        frame_limits=ContainerInnerFrameLimitsV1(
            maximum_frame_bytes=_integer(frame["maximumFrameBytes"]),
            maximum_stderr_bytes=_integer(frame["maximumStderrBytes"]),
        ),
        cgroup_measurement=DockerCgroupMeasurementConfigV1(
            monitor_interval_millis=_integer(measurement["monitorIntervalMillis"]),
            stable_final_samples=_integer(measurement["stableFinalSamples"]),
            cleanup_timeout_millis=_integer(measurement["cleanupTimeoutMillis"]),
        ),
    )


def _parse_host_proof(value: dict[str, Any]) -> RootlessDockerHostProofConfigV1:
    return RootlessDockerHostProofConfigV1(
        launcher_uid=_integer(value["launcherUid"]),
        launcher_gid=_integer(value["launcherGid"]),
        worker_uid=_integer(value["workerUid"]),
        rootless_daemon_pid_path=_path(value["rootlessDaemonPidPath"]),
        daemon_uid_map_sha256=_digest(value["daemonUidMapSha256"]),
        daemon_gid_map_sha256=_digest(value["daemonGidMapSha256"]),
        launcher_cgroup_path=_text(value["launcherCgroupPath"]),
        daemon_cgroup_path=_text(value["daemonCgroupPath"]),
        systemd_base_slice=_text(value["systemdBaseSlice"]),
        docker_socket_path=_path(value["dockerSocketPath"]),
        retained_input_mode=_integer(value["retainedInputMode"]),
    )


def _validate_cross_binding(config: ExternalInspectorOperatorConfigV1) -> None:
    production = config.production
    proof = config.host_proof
    if (
        production.required_worker_uid != proof.worker_uid
        or production.docker_socket.socket_path != proof.docker_socket_path
        or production.docker_socket.expected_owner_uid != proof.launcher_uid
        or production.docker_socket.expected_mode != 0o600
        or production.systemd_bus.expected_owner_uid != proof.launcher_uid
        or production.listener.expected_owner_uid != proof.launcher_uid
        or production.systemd_base_slice != proof.systemd_base_slice
        or not production.cgroup_root.base_control_group.endswith("/" + proof.systemd_base_slice)
    ):
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE)


def _read_config_file(path: Path) -> bytes:
    if not isinstance(path, Path) or not path.is_absolute():
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_FILE)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_FILE) from exc
    try:
        node = os.fstat(descriptor)
        if (
            not stat.S_ISREG(node.st_mode)
            or node.st_uid != os.geteuid()
            or node.st_gid != os.getegid()
            or (node.st_mode & 0o777) != 0o600
            or node.st_nlink != 1
        ):
            raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_FILE)
        return _read_descriptor(descriptor, _MAX_CONFIG_BYTES)
    except OSError as exc:
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_FILE) from exc
    finally:
        os.close(descriptor)


def _read_regular_file(path: Path, maximum_bytes: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise ValueError("operator artifact unavailable") from exc
    try:
        node = os.fstat(descriptor)
        if not stat.S_ISREG(node.st_mode) or node.st_nlink != 1:
            raise ValueError("operator artifact identity is invalid")
        return _read_descriptor(descriptor, maximum_bytes)
    finally:
        os.close(descriptor)


def _read_descriptor(descriptor: int, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    while True:
        chunk = os.read(descriptor, min(8192, maximum_bytes - observed + 1))
        if not chunk:
            return b"".join(chunks)
        observed += len(chunk)
        if observed > maximum_bytes:
            raise ValueError("bounded file exceeds configured maximum")
        chunks.append(chunk)


def _mapping(value: Any, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE)
    keys = set(value)
    if keys - expected:
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.UNKNOWN_FIELD)
    if keys != expected:
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE)
    if any(not isinstance(key, str) for key in value):
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE)
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT or value.strip() != value:
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE)
    return value


def _path(value: Any) -> Path:
    text = _text(value)
    path = Path(text)
    if not path.is_absolute() or ".." in path.parts or "\x00" in text:
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE)
    return path


def _integer(value: Any) -> int:
    if type(value) is not int or value < 0 or value > 2**63 - 1:
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE)
    return value


def _digest(value: Any) -> str:
    text = _text(value)
    if _DIGEST.fullmatch(text) is None:
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE)
    return text


def _public_keys(value: Any) -> dict[str, bytes]:
    if not isinstance(value, dict) or not value or len(value) > 64:
        raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE)
    keys: dict[str, bytes] = {}
    for key_id, encoded in value.items():
        if (
            not isinstance(key_id, str)
            or _KEY_ID.fullmatch(key_id) is None
            or not isinstance(encoded, str)
        ):
            raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE)
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE) from exc
        if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != encoded:
            raise OperatorConfigUnavailable(OperatorConfigBlockedCode.CONFIG_VALUE)
        keys[key_id] = decoded
    return keys


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> Never:
    del value
    raise ValueError("non-finite JSON constant")


__all__ = [
    "ExternalInspectorOperatorConfigV1",
    "OperatorConfigBlockedCode",
    "OperatorConfigUnavailable",
    "load_external_inspector_operator_config",
    "validate_operator_startup_artifacts",
]
