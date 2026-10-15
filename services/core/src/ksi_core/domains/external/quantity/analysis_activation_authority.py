"""Strict verification of the separately authorized Analysis execution graph."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_analysis_activation import AnalysisActivationV1
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_relative_volume_analysis import AnalysisPolicyV2

from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    AnalysisRuntimeIdentityV2,
)
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, principal_permissions

_MAX_FILE_BYTES = 64 * 1024
_REGISTRY_VERSION = "analysis-activation-key-registry.v1"
_KEY_ROLE = "ANALYSIS_ACTIVATION_VERIFY"


def _no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _no_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _protected_bytes(path: Path, *, name: str, maximum: int, private: bool) -> bytes:
    if not path.is_absolute() or ".." in path.parts or path != path.resolve(strict=False):
        raise ValueError(f"{name} path must be absolute and normalized")
    directory = -1
    descriptor = -1
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        directory = os.open("/", flags | os.O_DIRECTORY)
        for part in path.parent.parts[1:]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
            parent = os.fstat(directory)
            if parent.st_uid not in {0, os.geteuid()} or (
                parent.st_mode & 0o022 and not parent.st_mode & stat.S_ISVTX
            ):
                raise ValueError(f"{name} has an unprotected parent")
        descriptor = os.open(path.name, flags | os.O_NONBLOCK, dir_fd=directory)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid not in {0, os.geteuid()}
            or not before.st_mode & stat.S_IRUSR
            or before.st_mode & (0o077 if private else 0o022)
            or not 0 < before.st_size <= maximum
        ):
            raise ValueError(f"{name} is not bounded protected regular material")
        content = bytearray()
        while len(content) <= maximum:
            chunk = os.read(descriptor, min(65536, maximum + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
        before_state = (
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
        )
        after_state = (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_nlink,
        )
        if len(content) != before.st_size or after_state != before_state:
            raise ValueError(f"{name} changed during its bounded read")
        return bytes(content)
    except OSError as exc:
        raise ValueError(f"{name} is unavailable or unsafe") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory >= 0:
            os.close(directory)


def _strict_json(path: Path, *, name: str, private: bool) -> object:
    try:
        raw = _protected_bytes(path, name=name, maximum=_MAX_FILE_BYTES, private=private)
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicate_object,
            parse_constant=_no_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{name} is not strict protected JSON") from exc


def _exact_mapping(value: object, fields: frozenset[str], *, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} has missing or unknown fields")
    return cast(dict[str, object], value)


def _utc(value: object, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be a UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{name} must be a UTC timestamp")
    return parsed


def _runtime_digest(runtime: AnalysisRuntimeIdentityV2) -> str:
    exact_runtime_identity = {
        "workerExecutableDigest": runtime.worker_executable_digest,
        "workerBuildDigest": runtime.worker_build_digest,
        "runtimeImageVersion": runtime.runtime_image_version,
        "runtimeImageOciDigest": runtime.runtime_image_oci_digest,
        "dependencyLockDigest": runtime.dependency_lock_digest,
    }
    return "sha256:" + hashlib.sha256(canonical_json_bytes(exact_runtime_identity)).hexdigest()


def _registry_key(
    registry_path: Path,
    registry: object,
    *,
    key_id: str,
    now: datetime,
    issued_at: datetime,
    valid_until: datetime,
    allow_out_of_window: bool,
) -> Ed25519PublicKey:
    body = _exact_mapping(
        registry,
        frozenset({"version", "keys"}),
        name="Analysis activation verification-key registry",
    )
    if body["version"] != _REGISTRY_VERSION or not isinstance(body["keys"], list):
        raise ValueError("unknown Analysis activation verification-key registry")
    if len(body["keys"]) > 64:
        raise ValueError("Analysis activation key registry exceeds its key limit")
    matches: list[dict[str, object]] = []
    expected_fields = frozenset(
        {"keyId", "role", "algorithm", "status", "publicKeyFile", "notBefore", "notAfter"}
    )
    for item in body["keys"]:
        key = _exact_mapping(item, expected_fields, name="Analysis activation key")
        if key["keyId"] == key_id:
            matches.append(key)
    if len(matches) != 1:
        raise ValueError("Analysis activation key identity is missing or ambiguous")
    key = matches[0]
    if (
        key["role"] != _KEY_ROLE
        or key["algorithm"] != "Ed25519"
        or key["status"] != "ACTIVE"
        or not isinstance(key["publicKeyFile"], str)
        or Path(key["publicKeyFile"]).name != key["publicKeyFile"]
        or key["publicKeyFile"] in {".", ".."}
        or not key["publicKeyFile"].endswith(".pem")
    ):
        raise ValueError("Analysis activation key does not have the required verification role")
    not_before = _utc(key["notBefore"], name="key notBefore")
    not_after = _utc(key["notAfter"], name="key notAfter")
    if not_before >= not_after or not (
        not_before <= issued_at < valid_until <= not_after
    ):
        raise ValueError("Analysis activation was not issued within its signing key validity")
    if not allow_out_of_window and not (not_before <= now < not_after):
        raise ValueError("Analysis activation verification key is not currently valid")
    public_path = registry_path.parent / key["publicKeyFile"]
    if public_path.parent != registry_path.parent:
        raise ValueError("Analysis activation public key escapes its registry directory")
    public_bytes = _protected_bytes(
        public_path, name="Analysis activation public key", maximum=16 * 1024, private=False
    )
    loaded = serialization.load_pem_public_key(public_bytes)
    if not isinstance(loaded, Ed25519PublicKey):
        raise ValueError("Analysis activation public key is not Ed25519")
    return loaded


def load_analysis_activation(
    activation_path: Path,
    verification_keys_path: Path,
    *,
    organization_id: str,
    policy: AnalysisPolicyV2,
    runtime: AnalysisRuntimeIdentityV2,
    resource_envelope: ResourceEnvelopeV1,
    worker_principal: Principal,
    now: datetime,
    allow_out_of_window: bool = False,
) -> AnalysisActivationV1:
    """Load and verify activation against explicit, trusted Core graph bindings.

    The returned record remains historical evidence; callers decide whether its signed
    half-open validity window permits a new operation by calling ``is_current_at``.
    No ambient authority bundle, local config, or generic processing identity is consulted.
    """
    if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
        raise ValueError("Analysis activation verification requires a UTC-aware time")
    if (
        not organization_id
        or worker_principal.kind is not PrincipalKind.ANALYSIS_WORKER
        or Permission.ANALYSIS_WORK not in principal_permissions(worker_principal)
        or worker_principal.organization_id != organization_id
    ):
        raise ValueError("Analysis activation requires the dedicated organization worker")
    if policy.policy_digest != policy.canonical_digest():
        raise ValueError("Analysis policy must be sealed to its canonical digest")
    if resource_envelope.resource_envelope_digest != resource_envelope.canonical_digest():
        raise ValueError("Analysis resource envelope must be sealed to its canonical digest")

    raw_activation = _strict_json(
        activation_path, name="Analysis activation record", private=True
    )
    activation = AnalysisActivationV1.model_validate(raw_activation)
    if not allow_out_of_window and not activation.is_current_at(now):
        raise ValueError("Analysis activation is not current")
    if (
        activation.organization_id != organization_id
        or activation.organization_id != worker_principal.organization_id
        or activation.policy_digest != policy.canonical_digest()
        or activation.runtime_digest != _runtime_digest(runtime)
        or activation.resource_envelope_digest != resource_envelope.canonical_digest()
        or activation.worker_principal_id != worker_principal.principal_id
    ):
        raise ValueError("Analysis activation does not bind the exact trusted execution graph")

    registry = _strict_json(
        verification_keys_path,
        name="Analysis activation verification-key registry",
        private=True,
    )
    public_key = _registry_key(
        verification_keys_path,
        registry,
        key_id=activation.key_id,
        now=now,
        issued_at=activation.issued_at,
        valid_until=activation.valid_until,
        allow_out_of_window=allow_out_of_window,
    )
    try:
        public_key.verify(
            base64.b64decode(activation.signature, validate=True),
            activation.signing_bytes(),
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("Analysis activation signature verification failed") from exc
    return activation
