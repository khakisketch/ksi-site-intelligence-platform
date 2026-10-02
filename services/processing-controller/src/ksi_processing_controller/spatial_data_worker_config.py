"""Explicit owner-protected data-lane settings, not activation/credential provisioning.

Every load rechecks detached domain signatures, revocation and validity. Trust roots
are operator-pinned configuration, never learned from Core or a source artifact.
"""

from __future__ import annotations

import base64
import json
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ksi_event_contracts._spatial_data import Digest, PositiveInt, PositiveSeconds, SpatialDataModel
from ksi_event_contracts.spatial_data_authority import (
    SpatialDataActivationV1,
    SpatialDataPolicyV1,
    SpatialDataRuntimeV1,
)
from pydantic import Field, model_validator

from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)


class SpatialDataWorkerConfigError(RuntimeError):
    def __init__(self, reason: str = "CONFIG_UNAVAILABLE") -> None:
        self.reason = reason
        super().__init__(reason)


def _path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or "\x00" in value:
        raise ValueError("explicit absolute path required")
    return path


def _open_protected_directory(path: Path) -> int:
    descriptors: list[int] = []
    try:
        path = _path(str(path))
        directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        descriptors.append(directory)
        for component in path.parts[1:]:
            parent = os.fstat(directory)
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory,
            )
            descriptors.append(child)
            observed = os.fstat(child)
            if observed.st_uid not in (0, os.geteuid()):
                raise ValueError("untrusted ancestor")
            if parent.st_mode & 0o022 and not (
                parent.st_mode & stat.S_ISVTX and observed.st_uid == os.geteuid()
            ):
                raise ValueError("substitutable ancestor")
            directory = child
        parent = os.fstat(directory)
        if parent.st_mode & 0o022:
            raise ValueError("substitutable file parent")
        descriptors.remove(directory)
        return directory
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def require_owner_private_directory(path: Path) -> None:
    descriptor = -1
    try:
        descriptor = _open_protected_directory(path)
        node = os.fstat(descriptor)
        if (
            node.st_uid != os.geteuid()
            or node.st_gid != os.getegid()
            or stat.S_IMODE(node.st_mode) != 0o700
        ):
            raise ValueError("existing owner-private workspace required")
    except (OSError, ValueError) as exc:
        raise SpatialDataWorkerConfigError() from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def read_owner_private_file(
    path: Path, *, maximum_bytes: int, allowed_modes: tuple[int, ...] = (0o600,)
) -> bytes:
    """Bounded descriptor read through a no-symlink, non-substitutable directory chain."""
    descriptors: list[int] = []
    try:
        path = _path(str(path))
        directory = _open_protected_directory(path.parent)
        descriptors.append(directory)
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory
        )
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or stat.S_IMODE(before.st_mode) not in allowed_modes
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
        ):
            raise ValueError("private file identity unavailable")
        payload = bytearray()
        while True:
            chunk = os.read(descriptor, min(8192, maximum_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > maximum_bytes:
                raise ValueError("private file over budget")
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(payload) != before.st_size:
            raise ValueError("private file changed")
        return bytes(payload)
    except (ValueError, OSError) as exc:
        raise SpatialDataWorkerConfigError() from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _nonfinite(_: str) -> Any:
    raise ValueError("nonfinite JSON")


def parse_strict_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs, parse_constant=_nonfinite
    )


class _Endpoint(SpatialDataModel):
    origin: str = Field(strict=True, min_length=1, max_length=4096)
    addresses: tuple[str, ...] = Field(min_length=1, max_length=32)


class _ObjectSettings(SpatialDataModel):
    endpoints: tuple[_Endpoint, ...] = Field(min_length=1, max_length=16)
    max_header_bytes: PositiveInt
    max_object_bytes: PositiveInt
    max_chunk_bytes: PositiveInt

    def policy(self) -> ExternalObjectTransportPolicyV1:
        return ExternalObjectTransportPolicyV1(
            endpoints=tuple(
                TrustedObjectEndpointV1(origin=v.origin, addresses=v.addresses)
                for v in self.endpoints
            ),
            max_header_bytes=self.max_header_bytes,
            max_object_bytes=self.max_object_bytes,
            max_chunk_bytes=self.max_chunk_bytes,
        )


class SpatialDataSandboxSettingsV1(SpatialDataModel):
    launcher_path: str = Field(strict=True, min_length=1, max_length=4096)
    launcher_sha256: Digest
    containment_proof_path: str = Field(strict=True, min_length=1, max_length=4096)
    containment_proof_sha256: Digest

    @model_validator(mode="after")
    def _absolute_paths(self) -> Self:
        _path(self.launcher_path)
        _path(self.containment_proof_path)
        return self


class SpatialDataWorkerConfigV1(SpatialDataModel):
    version: Literal["spatial-data-worker-config.v1"]
    core_origin: str = Field(strict=True, min_length=1, max_length=4096)
    maximum_response_bytes: PositiveInt
    request_timeout_seconds: PositiveSeconds
    poll_interval_seconds: PositiveSeconds
    heartbeat_interval_millis: PositiveInt
    workspace_root: str = Field(strict=True, min_length=1, max_length=4096)
    policy: SpatialDataPolicyV1
    runtime: SpatialDataRuntimeV1
    activation: SpatialDataActivationV1
    activation_signature: str = Field(strict=True, min_length=1, max_length=128, repr=False)
    trusted_public_key: str = Field(strict=True, min_length=1, max_length=64, repr=False)
    revoked_activation_digests: tuple[Digest, ...] = Field(max_length=4096)
    object_transport: _ObjectSettings
    sandbox: SpatialDataSandboxSettingsV1

    @property
    def worker_instance_id(self) -> str:
        return self.activation.worker_instance_id

    @property
    def object_policy(self) -> ExternalObjectTransportPolicyV1:
        return self.object_transport.policy()

    def verify_at(self, now: datetime) -> None:
        for snapshot in (self.activation, self.policy, self.runtime):
            if getattr(snapshot, snapshot._digest_field) != snapshot.canonical_digest():
                raise ValueError("sealed data authority required")
        if (
            self.activation.policy_digest != self.policy.policy_digest
            or self.activation.runtime_digest != self.runtime.runtime_digest
            or not self.activation.is_current_at(now)
            or self.activation.activation_digest in self.revoked_activation_digests
            or tuple(sorted(set(self.revoked_activation_digests)))
            != self.revoked_activation_digests
        ):
            raise ValueError("distinct data authority not current")
        key = base64.b64decode(self.trusted_public_key, validate=True)
        signature = base64.b64decode(self.activation_signature, validate=True)
        if (
            len(key) != 32
            or len(signature) != 64
            or base64.b64encode(key).decode("ascii") != self.trusted_public_key
            or base64.b64encode(signature).decode("ascii") != self.activation_signature
        ):
            raise ValueError("canonical detached signature required")
        Ed25519PublicKey.from_public_bytes(key).verify(signature, self.activation.signing_bytes())
        origin = urlsplit(self.core_origin)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username is not None
            or origin.password is not None
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
        ):
            raise ValueError("explicit secure Core origin required")
        require_owner_private_directory(_path(self.workspace_root))
        transport = self.object_policy
        if (
            {v.origin for v in transport.endpoints} != set(self.activation.trusted_endpoint_origins)
            or self.maximum_response_bytes > self.policy.max_snapshot_bytes
            or self.request_timeout_seconds > self.policy.lease_seconds / 2
            or self.heartbeat_interval_millis / 1000 >= self.policy.lease_seconds / 3
            or self.poll_interval_seconds > self.policy.resource_envelope.max_deadline_seconds
            or transport.max_chunk_bytes > self.policy.stream_chunk_bytes
            or not max(self.policy.resource_envelope.max_input_bytes, self.policy.max_output_bytes)
            <= transport.max_object_bytes
            <= max(
                self.policy.resource_envelope.max_input_bytes,
                self.policy.resource_envelope.max_output_bytes,
            )
            or transport.max_header_bytes > 262144
        ):
            raise ValueError("finite connected authority/transport required")


def load_spatial_data_worker_config(path: Path, *, now: datetime) -> SpatialDataWorkerConfigV1:
    from cryptography.exceptions import InvalidSignature

    try:
        raw = read_owner_private_file(path, maximum_bytes=262144)
        config = SpatialDataWorkerConfigV1.model_validate(parse_strict_json(raw))
        config.verify_at(now)
        return config
    except (ValueError, TypeError, RecursionError, InvalidSignature) as exc:
        raise SpatialDataWorkerConfigError() from exc


def read_spatial_data_core_token(path: Path) -> str:
    try:
        token = read_owner_private_file(path, maximum_bytes=4096).decode("ascii").removesuffix("\n")
        if not token or any(ord(c) <= 32 or ord(c) > 126 for c in token):
            raise ValueError("bounded bearer required")
        return token
    except (ValueError, SpatialDataWorkerConfigError) as exc:
        raise SpatialDataWorkerConfigError("TOKEN_UNAVAILABLE") from exc
