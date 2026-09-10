"""Strict, non-secret configuration for the external validation worker.

This boundary accepts no host defaults, environment values, dynamic factories,
or credentials.  It only turns one owner-protected JSON document and one
separately protected Core token into closed local transport settings.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import json
import math
import os
import re
import select
import socket
import stat
import struct
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from time import monotonic
from typing import Any, Never
from urllib.parse import urlsplit
from uuid import UUID

from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionManifestV1,
    SignatureVerificationVerdict,
    parse_inspector_execution_manifest_wire,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

from ksi_processing_controller.external_artifact_inspection_worker import (
    InspectorWorkerOperationProfilePort,
    WorkerAuthorityLimitsV1,
)
from ksi_processing_controller.external_geotiff_profile import external_geotiff_profile_digest_v1
from ksi_processing_controller.external_inspector_catalog import (
    Ed25519InspectorManifestVerifier,
    InspectorTrustRootV1,
)
from ksi_processing_controller.external_inspector_container_protocol import (
    compiled_security_profile_digest_v1,
)
from ksi_processing_controller.external_inspector_launcher import InspectorOperationProfileDecision
from ksi_processing_controller.external_inspector_protocol import (
    InspectorOperation,
    ProtocolLimitsV1,
)
from ksi_processing_controller.external_measurement_protocol import (
    compiled_measurement_backend_profile_digest_v2,
    compiled_measurement_protocol_digest_v2,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from ksi_processing_controller.external_validation_runner import RunnerPolicy

_VERSION = "external-validation-worker-config.v1"
_MAX_CONFIG_BYTES = 256 * 1024
_MAX_TOKEN_BYTES = 4_096
_MAX_TEXT = 4_096
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ExternalValidationWorkerConfigBlockedCode(StrEnum):
    CONFIG_FILE = "CONFIG_FILE"
    CONFIG_SYNTAX = "CONFIG_SYNTAX"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    CONFIG_VALUE = "CONFIG_VALUE"
    TOKEN_FILE = "TOKEN_FILE"


class ExternalValidationWorkerConfigBlocked(RuntimeError):
    """A safe pre-assembly configuration failure without paths or secrets."""

    def __init__(self, code: ExternalValidationWorkerConfigBlockedCode) -> None:
        self.code = code
        super().__init__("external validation worker configuration blocked: " + code.value)


@dataclass(frozen=True, slots=True)
class ExternalValidationCoreSettingsV1:
    base_url: str
    maximum_response_bytes: int
    request_timeout_seconds: float

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("external Core endpoint must be a secure origin")
        if not 128 <= self.maximum_response_bytes <= 4_194_304:
            raise ValueError("Core response ceiling is invalid")
        if (
            not math.isfinite(self.request_timeout_seconds)
            or self.request_timeout_seconds <= 0
            or self.request_timeout_seconds > 60
        ):
            raise ValueError("Core request timeout is invalid")


@dataclass(frozen=True, slots=True)
class LocalWorkerSocketIdentityV1:
    """One already-provisioned UDS peer; no listener is ever created here."""

    path: Path
    owner_uid: int
    owner_gid: int
    mode: int
    peer_uid: int

    def __post_init__(self) -> None:
        if (
            not self.path.is_absolute()
            or ".." in self.path.parts
            or len(str(self.path).encode("utf-8")) > 107
            or any(
                type(value) is not int or value < 0
                for value in (self.owner_uid, self.owner_gid, self.peer_uid)
            )
            or self.mode not in {0o600, 0o660}
        ):
            raise ValueError("fixed local worker socket identity is invalid")


class FixedInspectionUdsConnector:
    """Connect to one pre-provisioned inspector socket after identity checks."""

    def __init__(self, identity: LocalWorkerSocketIdentityV1) -> None:
        self._identity = identity

    def __call__(
        self,
        deadline_monotonic: float,
        *,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> socket.socket:
        if (
            isinstance(deadline_monotonic, bool)
            or not isinstance(deadline_monotonic, (int, float))
            or not math.isfinite(deadline_monotonic)
        ):
            raise ConnectionError("inspection socket deadline is invalid")
        if type(heartbeat_interval_millis) is not int or heartbeat_interval_millis <= 0:
            raise ConnectionError("inspection socket heartbeat interval is invalid")

        def require_current() -> None:
            if wait_is_current() is not True:
                raise ConnectionAbortedError("inspection socket authority changed")

        def remaining() -> float:
            value = deadline_monotonic - monotonic()
            if value <= 0:
                raise TimeoutError("inspection socket deadline elapsed")
            return value

        def wait_timeout() -> float:
            return min(remaining(), heartbeat_interval_millis / 1_000)

        require_current()
        before = self._socket_identity()
        require_current()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.setblocking(False)
            while True:
                require_current()
                result = connection.connect_ex(str(self._identity.path))
                require_current()
                if result in {0, errno.EISCONN}:
                    break
                if result in {errno.EAGAIN, errno.EWOULDBLOCK}:
                    select.select([], [], [], wait_timeout())
                    require_current()
                    continue
                if result not in {errno.EINPROGRESS, errno.EALREADY, errno.EINTR}:
                    raise ConnectionError("inspection socket unavailable")
                _readable, writable, errors = select.select(
                    [], [connection], [connection], wait_timeout()
                )
                require_current()
                if (
                    errors
                    or not writable
                    or connection.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                ):
                    raise ConnectionError("inspection socket unavailable")
                connection.getpeername()
                require_current()
                break
            remaining()
            require_current()
            credentials = connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
            )
            require_current()
            if (
                struct.unpack("3i", credentials)[1] != self._identity.peer_uid
                or self._socket_identity() != before
            ):
                raise ConnectionError("inspection socket identity differs")
            return connection
        except BaseException:
            connection.close()
            raise

    def _socket_identity(self) -> tuple[int, int]:
        try:
            observed = self._identity.path.lstat()
        except OSError as exc:
            raise ConnectionError("inspection socket unavailable") from exc
        if (
            not stat.S_ISSOCK(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != self._identity.mode
            or observed.st_uid != self._identity.owner_uid
            or observed.st_gid != self._identity.owner_gid
        ):
            raise ConnectionError("inspection socket identity differs")
        return observed.st_dev, observed.st_ino


@dataclass(frozen=True, slots=True)
class PinnedInspectionProfileV1(InspectorWorkerOperationProfilePort):
    """Code-owned GeoTIFF rules bound to exact operator-pinned digests."""

    parser_build_digest: str
    grammar_digest: str

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.parser_build_digest) is None or (
            self.grammar_digest != external_geotiff_profile_digest_v1()
        ):
            raise ValueError("inspection profile binding is invalid")

    def allows(
        self,
        *,
        parser_build_digest: str,
        grammar_digest: str,
        artifact_kind: ProcessingArtifactKind,
        content_type: str,
        operation: InspectorOperation,
        deadline_monotonic: float,
    ) -> InspectorOperationProfileDecision:
        if (
            isinstance(deadline_monotonic, bool)
            or not isinstance(deadline_monotonic, (int, float))
            or not math.isfinite(deadline_monotonic)
            or parser_build_digest != self.parser_build_digest
            or grammar_digest != self.grammar_digest
            or content_type not in {"image/tiff", "application/octet-stream"}
            or artifact_kind not in {ProcessingArtifactKind.ORTHO, ProcessingArtifactKind.DSM}
        ):
            return InspectorOperationProfileDecision.DENY
        if operation is InspectorOperation.INSPECT:
            return InspectorOperationProfileDecision.ALLOW
        if (
            operation is InspectorOperation.SANITIZE
            and artifact_kind is ProcessingArtifactKind.ORTHO
        ):
            return InspectorOperationProfileDecision.ALLOW
        return InspectorOperationProfileDecision.DENY


@dataclass(frozen=True, slots=True)
class InspectionLaneSettingsV1:
    socket: LocalWorkerSocketIdentityV1
    private_output_root: Path
    protocol_limits: ProtocolLimitsV1
    worker_limits: WorkerAuthorityLimitsV1
    profile: PinnedInspectionProfileV1

    def __post_init__(self) -> None:
        if not self.private_output_root.is_absolute() or ".." in self.private_output_root.parts:
            raise ValueError("private inspection output root is invalid")


@dataclass(frozen=True, slots=True)
class PinnedMeasurementManifestV1:
    path: Path
    expected_sha256: str
    expected_body_digest: str
    revocation_path: Path
    expected_revocation_sha256: str
    trust_root: InspectorTrustRootV1

    def __post_init__(self) -> None:
        if (
            not self.path.is_absolute()
            or ".." in self.path.parts
            or _DIGEST.fullmatch(self.expected_sha256) is None
            or _DIGEST.fullmatch(self.expected_body_digest) is None
            or not self.revocation_path.is_absolute()
            or ".." in self.revocation_path.parts
            or _DIGEST.fullmatch(self.expected_revocation_sha256) is None
        ):
            raise ValueError("measurement manifest pin is invalid")


@dataclass(frozen=True, slots=True)
class MeasurementLaneSettingsV1:
    socket: LocalWorkerSocketIdentityV1
    protocol_limits: ProtocolLimitsV1
    heartbeat_interval_millis: int
    manifest: PinnedMeasurementManifestV1

    def __post_init__(self) -> None:
        if type(self.heartbeat_interval_millis) is not int or self.heartbeat_interval_millis <= 0:
            raise ValueError("measurement heartbeat interval is invalid")


@dataclass(frozen=True, slots=True)
class ExternalValidationWorkerConfigV1:
    core: ExternalValidationCoreSettingsV1
    worker_instance_id: str
    runner_policy: RunnerPolicy
    object_policy: ExternalObjectTransportPolicyV1
    inspection: InspectionLaneSettingsV1
    measurement: MeasurementLaneSettingsV1

    def __post_init__(self) -> None:
        try:
            parsed = UUID(self.worker_instance_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("worker identity must be a canonical UUID4") from exc
        if parsed.version != 4 or str(parsed) != self.worker_instance_id:
            raise ValueError("worker identity must be a canonical UUID4")


def load_external_validation_worker_config(path: Path) -> ExternalValidationWorkerConfigV1:
    """Parse exactly one 0600 regular config before any client/socket is built."""

    raw = _read_private_regular(
        path, _MAX_CONFIG_BYTES, ExternalValidationWorkerConfigBlockedCode.CONFIG_FILE
    )
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ExternalValidationWorkerConfigBlocked(
            ExternalValidationWorkerConfigBlockedCode.CONFIG_SYNTAX
        ) from exc
    try:
        body = _mapping(
            value,
            {"version", "core", "worker", "runner", "objectTransport", "inspection", "measurement"},
        )
        if _text(body["version"]) != _VERSION:
            raise ValueError("unsupported configuration version")
        return ExternalValidationWorkerConfigV1(
            core=_parse_core(
                _mapping(body["core"], {"baseUrl", "maximumResponseBytes", "requestTimeoutMillis"})
            ),
            worker_instance_id=_text(_mapping(body["worker"], {"instanceId"})["instanceId"]),
            runner_policy=_parse_runner(_mapping(body["runner"], _RUNNER_FIELDS)),
            object_policy=_parse_object_policy(
                _mapping(body["objectTransport"], _OBJECT_POLICY_FIELDS)
            ),
            inspection=_parse_inspection(_mapping(body["inspection"], _INSPECTION_FIELDS)),
            measurement=_parse_measurement(_mapping(body["measurement"], _MEASUREMENT_FIELDS)),
        )
    except ExternalValidationWorkerConfigBlocked:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalValidationWorkerConfigBlocked(
            ExternalValidationWorkerConfigBlockedCode.CONFIG_VALUE
        ) from exc


def read_external_validation_core_token(path: Path) -> str:
    """Read one explicit non-empty ASCII bearer secret without putting it in config."""

    raw = _read_private_regular(
        path, _MAX_TOKEN_BYTES, ExternalValidationWorkerConfigBlockedCode.TOKEN_FILE
    )
    try:
        token = raw.decode("ascii").removesuffix("\n")
    except UnicodeDecodeError as exc:
        raise ExternalValidationWorkerConfigBlocked(
            ExternalValidationWorkerConfigBlockedCode.TOKEN_FILE
        ) from exc
    if (
        not token
        or len(token) > _MAX_TOKEN_BYTES - 1
        or token.strip() != token
        or "\n" in token
        or "\r" in token
        or any(ord(char) <= 32 or ord(char) > 126 for char in token)
    ):
        raise ExternalValidationWorkerConfigBlocked(
            ExternalValidationWorkerConfigBlockedCode.TOKEN_FILE
        )
    return token


def load_pinned_measurement_manifest(
    settings: MeasurementLaneSettingsV1,
) -> InspectorExecutionManifestV1:
    """Read and verify one signature/revocation-pinned V2 manifest before graph assembly."""

    try:
        raw = _read_regular(settings.manifest.path, _MAX_CONFIG_BYTES)
        if "sha256:" + hashlib.sha256(raw).hexdigest() != settings.manifest.expected_sha256:
            raise ValueError("measurement manifest file digest differs")
        wire = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(wire, dict):
            raise ValueError("measurement manifest wire is invalid")
        manifest = parse_inspector_execution_manifest_wire(wire)
        if manifest.canonical_body_digest() != settings.manifest.expected_body_digest:
            raise ValueError("measurement manifest body differs")
        if (
            manifest.body.inspector_protocol_digest != compiled_measurement_protocol_digest_v2()
            or manifest.body.backend_profile_digest
            != compiled_measurement_backend_profile_digest_v2()
            or manifest.body.security_profile_digest != compiled_security_profile_digest_v1()
            or manifest.body.backend != "DEDICATED_ROOTLESS_DOCKER_V1"
        ):
            raise ValueError("measurement manifest V2 profile differs")
        verifier = Ed25519InspectorManifestVerifier(settings.manifest.trust_root)
        if (
            verifier.verify(manifest.canonical_body_bytes(), manifest.signature)
            is not SignatureVerificationVerdict.VALID
        ):
            raise ValueError("measurement manifest signature is invalid")
        revocations = _read_revocations(settings.manifest)
        if manifest.canonical_body_digest() in revocations:
            raise ValueError("measurement manifest is revoked")
        return manifest
    except Exception as exc:
        raise ExternalValidationWorkerConfigBlocked(
            ExternalValidationWorkerConfigBlockedCode.CONFIG_VALUE
        ) from exc


_RUNNER_FIELDS = {
    "turnBudgetMillis",
    "claimRetryMillis",
    "idleBackoffMillis",
    "failureBackoffMillis",
}
_OBJECT_POLICY_FIELDS = {"endpoints", "maxHeaderBytes", "maxObjectBytes", "maxChunkBytes"}
_INSPECTION_FIELDS = {
    "uds",
    "privateOutputRoot",
    "protocolLimits",
    "workerLimits",
    "pinnedProfile",
}
_MEASUREMENT_FIELDS = {"uds", "protocolLimits", "heartbeatIntervalMillis", "manifest"}
_SOCKET_FIELDS = {"socketPath", "ownerUid", "ownerGid", "socketMode", "peerUid"}
_PROTOCOL_FIELDS = {
    "maxHeaderBytes",
    "maxChunkBytes",
    "maxInputBytes",
    "maxOutputBytes",
    "maxWireDurationMillis",
}


def _parse_core(value: dict[str, Any]) -> ExternalValidationCoreSettingsV1:
    return ExternalValidationCoreSettingsV1(
        base_url=_text(value["baseUrl"]),
        maximum_response_bytes=_bounded_integer(
            value["maximumResponseBytes"], minimum=128, maximum=4_194_304
        ),
        request_timeout_seconds=_bounded_integer(
            value["requestTimeoutMillis"], minimum=1, maximum=60_000
        )
        / 1_000,
    )


def _parse_runner(value: dict[str, Any]) -> RunnerPolicy:
    return RunnerPolicy(
        turn_budget_seconds=_bounded_integer(
            value["turnBudgetMillis"], minimum=1, maximum=3_600_000
        )
        / 1_000,
        claim_retry_seconds=_bounded_integer(
            value["claimRetryMillis"], minimum=1, maximum=3_600_000
        )
        / 1_000,
        idle_backoff_seconds=_bounded_integer(value["idleBackoffMillis"], minimum=1, maximum=60_000)
        / 1_000,
        failure_backoff_seconds=_bounded_integer(
            value["failureBackoffMillis"], minimum=1, maximum=60_000
        )
        / 1_000,
    )


def _parse_object_policy(value: dict[str, Any]) -> ExternalObjectTransportPolicyV1:
    endpoints_raw = value["endpoints"]
    if not isinstance(endpoints_raw, list) or not 1 <= len(endpoints_raw) <= 32:
        raise ValueError("object endpoint set is invalid")
    endpoints = tuple(
        TrustedObjectEndpointV1(
            origin=_text(_mapping(raw, {"origin", "addresses"})["origin"]),
            addresses=_ip_addresses(_mapping(raw, {"origin", "addresses"})["addresses"]),
        )
        for raw in endpoints_raw
    )
    return ExternalObjectTransportPolicyV1(
        endpoints=endpoints,
        max_header_bytes=_bounded_integer(value["maxHeaderBytes"], minimum=128, maximum=262_144),
        max_object_bytes=_bounded_integer(value["maxObjectBytes"], minimum=1, maximum=2**31),
        max_chunk_bytes=_bounded_integer(value["maxChunkBytes"], minimum=1, maximum=2**20),
    )


def _parse_inspection(value: dict[str, Any]) -> InspectionLaneSettingsV1:
    worker = _mapping(value["workerLimits"], {"heartbeatIntervalMillis", "maxAuthorityWaitMillis"})
    profile = _mapping(value["pinnedProfile"], {"parserBuildDigest", "grammarDigest"})
    return InspectionLaneSettingsV1(
        socket=_parse_socket(_mapping(value["uds"], _SOCKET_FIELDS)),
        private_output_root=_path(value["privateOutputRoot"]),
        protocol_limits=_parse_protocol(_mapping(value["protocolLimits"], _PROTOCOL_FIELDS)),
        worker_limits=WorkerAuthorityLimitsV1(
            heartbeat_interval_millis=_bounded_integer(
                worker["heartbeatIntervalMillis"], minimum=1, maximum=60_000
            ),
            max_authority_wait_millis=_bounded_integer(
                worker["maxAuthorityWaitMillis"], minimum=1, maximum=3_600_000
            ),
        ),
        profile=PinnedInspectionProfileV1(
            parser_build_digest=_digest(profile["parserBuildDigest"]),
            grammar_digest=_digest(profile["grammarDigest"]),
        ),
    )


def _parse_measurement(value: dict[str, Any]) -> MeasurementLaneSettingsV1:
    manifest = _mapping(
        value["manifest"],
        {
            "path",
            "expectedSha256",
            "expectedBodyDigest",
            "revocationPath",
            "expectedRevocationSha256",
            "trustedPublicKeys",
        },
    )
    return MeasurementLaneSettingsV1(
        socket=_parse_socket(_mapping(value["uds"], _SOCKET_FIELDS)),
        protocol_limits=_parse_protocol(_mapping(value["protocolLimits"], _PROTOCOL_FIELDS)),
        heartbeat_interval_millis=_bounded_integer(
            value["heartbeatIntervalMillis"], minimum=1, maximum=60_000
        ),
        manifest=PinnedMeasurementManifestV1(
            path=_path(manifest["path"]),
            expected_sha256=_digest(manifest["expectedSha256"]),
            expected_body_digest=_digest(manifest["expectedBodyDigest"]),
            revocation_path=_path(manifest["revocationPath"]),
            expected_revocation_sha256=_digest(manifest["expectedRevocationSha256"]),
            trust_root=InspectorTrustRootV1(_public_keys(manifest["trustedPublicKeys"])),
        ),
    )


def _parse_socket(value: dict[str, Any]) -> LocalWorkerSocketIdentityV1:
    return LocalWorkerSocketIdentityV1(
        path=_path(value["socketPath"]),
        owner_uid=_bounded_integer(value["ownerUid"], minimum=0, maximum=2**31 - 1),
        owner_gid=_bounded_integer(value["ownerGid"], minimum=0, maximum=2**31 - 1),
        mode=_bounded_integer(value["socketMode"], minimum=0o600, maximum=0o660),
        peer_uid=_bounded_integer(value["peerUid"], minimum=0, maximum=2**31 - 1),
    )


def _parse_protocol(value: dict[str, Any]) -> ProtocolLimitsV1:
    return ProtocolLimitsV1(
        max_header_bytes=_bounded_integer(value["maxHeaderBytes"], minimum=1, maximum=262_144),
        max_chunk_bytes=_bounded_integer(value["maxChunkBytes"], minimum=1, maximum=2**20),
        max_input_bytes=_bounded_integer(value["maxInputBytes"], minimum=1, maximum=2**31),
        max_output_bytes=_bounded_integer(value["maxOutputBytes"], minimum=1, maximum=2**31),
        max_wire_duration_millis=_bounded_integer(
            value["maxWireDurationMillis"], minimum=1, maximum=3_600_000
        ),
    )


def _read_private_regular(
    path: Path, maximum_bytes: int, code: ExternalValidationWorkerConfigBlockedCode
) -> bytes:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ExternalValidationWorkerConfigBlocked(code)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise ExternalValidationWorkerConfigBlocked(code) from exc
    try:
        node = os.fstat(descriptor)
        if (
            not stat.S_ISREG(node.st_mode)
            or node.st_uid != os.geteuid()
            or node.st_gid != os.getegid()
            or stat.S_IMODE(node.st_mode) != 0o600
            or node.st_nlink != 1
        ):
            raise ExternalValidationWorkerConfigBlocked(code)
        return _read_descriptor(descriptor, maximum_bytes)
    except OSError as exc:
        raise ExternalValidationWorkerConfigBlocked(code) from exc
    finally:
        os.close(descriptor)


def _read_regular(path: Path, maximum_bytes: int) -> bytes:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("pinned operator artifact path is invalid")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise ValueError("pinned operator artifact is unavailable") from exc
    try:
        node = os.fstat(descriptor)
        if not stat.S_ISREG(node.st_mode) or node.st_nlink != 1:
            raise ValueError("pinned operator artifact identity is invalid")
        return _read_descriptor(descriptor, maximum_bytes)
    finally:
        os.close(descriptor)


def _read_revocations(manifest: PinnedMeasurementManifestV1) -> frozenset[str]:
    raw = _read_regular(manifest.revocation_path, _MAX_CONFIG_BYTES)
    if "sha256:" + hashlib.sha256(raw).hexdigest() != manifest.expected_revocation_sha256:
        raise ValueError("measurement revocation digest differs")
    wire = json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_json_constant
    )
    body = _mapping(wire, {"version", "revokedManifestDigests"})
    if _text(body["version"]) != "external-inspector-revocations.v1":
        raise ValueError("measurement revocation version is invalid")
    values = body["revokedManifestDigests"]
    if not isinstance(values, list) or len(values) > 4_096:
        raise ValueError("measurement revocations are invalid")
    digests = tuple(_digest(value) for value in values)
    if tuple(sorted(set(digests))) != digests:
        raise ValueError("measurement revocations are not canonical")
    return frozenset(digests)


def _read_descriptor(descriptor: int, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    while True:
        chunk = os.read(descriptor, min(8_192, maximum_bytes - observed + 1))
        if not chunk:
            return b"".join(chunks)
        observed += len(chunk)
        if observed > maximum_bytes:
            raise ValueError("bounded private file exceeds its limit")
        chunks.append(chunk)


def _mapping(value: Any, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("configuration object is invalid")
    keys = set(value)
    if keys - expected:
        raise ExternalValidationWorkerConfigBlocked(
            ExternalValidationWorkerConfigBlockedCode.UNKNOWN_FIELD
        )
    if keys != expected:
        raise ValueError("configuration object has missing fields")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT or value.strip() != value:
        raise ValueError("configuration text is invalid")
    return value


def _path(value: Any) -> Path:
    text = _text(value)
    path = Path(text)
    if not path.is_absolute() or ".." in path.parts or "\x00" in text:
        raise ValueError("configuration path is invalid")
    return path


def _digest(value: Any) -> str:
    text = _text(value)
    if _DIGEST.fullmatch(text) is None:
        raise ValueError("configuration digest is invalid")
    return text


def _bounded_integer(value: Any, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("configuration integer is invalid")
    return value


def _ip_addresses(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        raise ValueError("configured object addresses are invalid")
    return tuple(_text(item) for item in value)


def _public_keys(value: Any) -> dict[str, bytes]:
    if not isinstance(value, dict) or not 1 <= len(value) <= 64:
        raise ValueError("measurement trust root is invalid")
    result: dict[str, bytes] = {}
    for key_id, encoded in value.items():
        if (
            not isinstance(key_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,254}", key_id) is None
            or not isinstance(encoded, str)
        ):
            raise ValueError("measurement trust root is invalid")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("measurement trust root is invalid") from exc
        if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != encoded:
            raise ValueError("measurement trust root is invalid")
        result[key_id] = decoded
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Never:
    del value
    raise ValueError("non-finite JSON constant")


__all__ = [
    "ExternalValidationCoreSettingsV1",
    "ExternalValidationWorkerConfigBlocked",
    "ExternalValidationWorkerConfigBlockedCode",
    "ExternalValidationWorkerConfigV1",
    "FixedInspectionUdsConnector",
    "InspectionLaneSettingsV1",
    "LocalWorkerSocketIdentityV1",
    "MeasurementLaneSettingsV1",
    "PinnedInspectionProfileV1",
    "PinnedMeasurementManifestV1",
    "load_external_validation_worker_config",
    "load_pinned_measurement_manifest",
    "read_external_validation_core_token",
]
