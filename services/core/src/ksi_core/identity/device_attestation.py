"""Operator-provisioned Ed25519 keys for device evidence attestation.

The bearer-token identity used by the Edge sync channel answers *which device
opened the request*.  This registry answers a different question: whether the
device signed the immutable identity of one evidence artifact.  There is no
HTTP registration surface; operations provision public keys out of band and
Core only reads them at startup.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

_PATH_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_BASE64URL_NOPAD = re.compile(r"^[A-Za-z0-9_-]+$")


class DeviceAttestationError(RuntimeError):
    """Provisioned key material is malformed; Core must refuse startup."""


class DeviceAttestationKeyStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class DeviceEvidenceAttestation(BaseModel):
    """Wire signature block.  Signatures use unpadded RFC 4648 base64url."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    key_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    algorithm: Literal["Ed25519"]
    signature: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class DeviceAttestationKeyRecord:
    device_id: str
    key_id: str
    public_key: Ed25519PublicKey
    status: DeviceAttestationKeyStatus = DeviceAttestationKeyStatus.ACTIVE
    not_before: datetime | None = None
    not_after: datetime | None = None


class DeviceAttestationVerdict(StrEnum):
    VALID = "VALID"
    UNKNOWN_KEY = "UNKNOWN_KEY"
    CROSS_DEVICE_KEY = "CROSS_DEVICE_KEY"
    REVOKED_KEY = "REVOKED_KEY"
    KEY_NOT_YET_VALID = "KEY_NOT_YET_VALID"
    KEY_EXPIRED = "KEY_EXPIRED"
    MALFORMED_SIGNATURE = "MALFORMED_SIGNATURE"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"


@dataclass(frozen=True, slots=True)
class DeviceAttestationVerification:
    verdict: DeviceAttestationVerdict
    key_id: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.verdict is DeviceAttestationVerdict.VALID


class DeviceAttestationRegistry:
    """Immutable ``(deviceId, keyId)`` public-key registry."""

    def __init__(self, records: Iterable[DeviceAttestationKeyRecord] = ()) -> None:
        self._records: dict[tuple[str, str], DeviceAttestationKeyRecord] = {}
        self._key_owners: dict[str, set[str]] = {}
        material_owners: dict[bytes, tuple[str, str]] = {}
        for record in records:
            if not _PATH_SAFE_ID.fullmatch(record.device_id) or not _PATH_SAFE_ID.fullmatch(
                record.key_id
            ):
                raise ValueError("deviceId와 keyId는 경로-안전 식별자여야 한다")
            if record.not_before is not None and record.not_before.tzinfo is None:
                raise ValueError("notBefore는 tz-aware여야 한다")
            if record.not_after is not None and record.not_after.tzinfo is None:
                raise ValueError("notAfter는 tz-aware여야 한다")
            if (
                record.not_before is not None
                and record.not_after is not None
                and record.not_after <= record.not_before
            ):
                raise ValueError("notAfter는 notBefore보다 뒤여야 한다")
            identity = (record.device_id, record.key_id)
            if identity in self._records:
                raise ValueError(f"중복 device attestation key: {identity!r}")
            raw = record.public_key.public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            prior = material_owners.get(raw)
            if prior is not None:
                raise ValueError(
                    f"동일 device attestation 공개키가 {prior!r}와 {identity!r}에 중복됐다"
                )
            material_owners[raw] = identity
            self._records[identity] = record
            self._key_owners.setdefault(record.key_id, set()).add(record.device_id)

    def get(self, device_id: str, key_id: str) -> DeviceAttestationKeyRecord | None:
        return self._records.get((device_id, key_id))

    def key_belongs_to_other_device(self, device_id: str, key_id: str) -> bool:
        owners = self._key_owners.get(key_id, set())
        return bool(owners and device_id not in owners)


def evidence_attestation_payload(
    *,
    device_id: str,
    site_id: str,
    mission_id: str,
    event_key: str,
    artifact_id: str,
    content_type: str,
    content_digest: str,
) -> dict[str, str]:
    """Return the complete and only signed field set for evidence attestation."""

    return {
        "deviceId": device_id,
        "siteId": site_id,
        "missionId": mission_id,
        "eventKey": event_key,
        "artifactId": artifact_id,
        "contentType": content_type,
        "contentDigest": content_digest,
    }


def _decode_signature(value: str) -> bytes | None:
    if "=" in value or not _BASE64URL_NOPAD.fullmatch(value):
        return None
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        return None
    return decoded if len(decoded) == 64 else None


def verify_device_evidence_attestation(
    attestation: DeviceEvidenceAttestation,
    registry: DeviceAttestationRegistry,
    *,
    payload: Mapping[str, Any],
    device_id: str,
    now: datetime | None = None,
) -> DeviceAttestationVerification:
    """Verify ownership, validity and Ed25519 signature without throwing."""

    record = registry.get(device_id, attestation.key_id)
    if record is None:
        verdict = (
            DeviceAttestationVerdict.CROSS_DEVICE_KEY
            if registry.key_belongs_to_other_device(device_id, attestation.key_id)
            else DeviceAttestationVerdict.UNKNOWN_KEY
        )
        return DeviceAttestationVerification(verdict)
    if record.status is DeviceAttestationKeyStatus.REVOKED:
        return DeviceAttestationVerification(DeviceAttestationVerdict.REVOKED_KEY)
    checked_at = now if now is not None else datetime.now(UTC)
    if checked_at.tzinfo is None:
        return DeviceAttestationVerification(DeviceAttestationVerdict.MALFORMED_SIGNATURE)
    if record.not_before is not None and checked_at < record.not_before:
        return DeviceAttestationVerification(DeviceAttestationVerdict.KEY_NOT_YET_VALID)
    if record.not_after is not None and checked_at > record.not_after:
        return DeviceAttestationVerification(DeviceAttestationVerdict.KEY_EXPIRED)
    signature = _decode_signature(attestation.signature)
    if signature is None:
        return DeviceAttestationVerification(DeviceAttestationVerdict.MALFORMED_SIGNATURE)
    try:
        canonical = canonical_json_bytes(payload)
        record.public_key.verify(signature, canonical)
    except InvalidSignature:
        return DeviceAttestationVerification(DeviceAttestationVerdict.INVALID_SIGNATURE)
    except (TypeError, ValueError, UnicodeError):
        return DeviceAttestationVerification(DeviceAttestationVerdict.MALFORMED_SIGNATURE)
    return DeviceAttestationVerification(DeviceAttestationVerdict.VALID, key_id=record.key_id)


def _aware_time(value: object, *, field: str, index: int) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DeviceAttestationError(f"keys[{index}].{field}는 RFC3339 문자열이어야 한다")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeviceAttestationError(f"keys[{index}].{field}를 파싱할 수 없다") from exc
    if parsed.tzinfo is None:
        raise DeviceAttestationError(f"keys[{index}].{field}는 tz-aware여야 한다")
    return parsed


def load_device_attestation_registry(manifest_path: Path) -> DeviceAttestationRegistry:
    """Load an operator-managed public-key manifest; never loads private keys."""

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeviceAttestationError(
            f"device attestation key manifest를 읽을 수 없다: {manifest_path}"
        ) from exc
    entries = manifest.get("keys") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        raise DeviceAttestationError("device attestation manifest.keys는 배열이어야 한다")
    root = manifest_path.resolve().parent
    records: list[DeviceAttestationKeyRecord] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise DeviceAttestationError(f"keys[{index}]는 object여야 한다")
        device_id = entry.get("deviceId")
        key_id = entry.get("keyId")
        public_key_file = entry.get("publicKeyFile")
        status_raw = entry.get("status", "ACTIVE")
        if (
            not isinstance(device_id, str)
            or not device_id
            or not isinstance(key_id, str)
            or not key_id
            or not isinstance(public_key_file, str)
            or not public_key_file
        ):
            raise DeviceAttestationError(
                f"keys[{index}]의 deviceId/keyId/publicKeyFile은 비어 있지 않은 문자열이어야 한다"
            )
        try:
            status = DeviceAttestationKeyStatus(status_raw)
        except ValueError as exc:
            raise DeviceAttestationError(f"keys[{index}].status가 유효하지 않다") from exc
        key_path = (root / public_key_file).resolve()
        if key_path.parent != root:
            raise DeviceAttestationError(
                f"keys[{index}].publicKeyFile은 manifest 디렉터리 안이어야 한다"
            )
        try:
            loaded = serialization.load_pem_public_key(key_path.read_bytes())
        except (OSError, ValueError, TypeError) as exc:
            raise DeviceAttestationError(f"keys[{index}] 공개키를 읽을 수 없다") from exc
        if not isinstance(loaded, Ed25519PublicKey):
            raise DeviceAttestationError(f"keys[{index}] 공개키는 Ed25519여야 한다")
        records.append(
            DeviceAttestationKeyRecord(
                device_id=device_id,
                key_id=key_id,
                public_key=loaded,
                status=status,
                not_before=_aware_time(entry.get("notBefore"), field="notBefore", index=index),
                not_after=_aware_time(entry.get("notAfter"), field="notAfter", index=index),
            )
        )
    try:
        return DeviceAttestationRegistry(records)
    except ValueError as exc:
        raise DeviceAttestationError(str(exc)) from exc


__all__ = [
    "DeviceAttestationError",
    "DeviceAttestationKeyRecord",
    "DeviceAttestationKeyStatus",
    "DeviceAttestationRegistry",
    "DeviceAttestationVerdict",
    "DeviceEvidenceAttestation",
    "evidence_attestation_payload",
    "load_device_attestation_registry",
    "verify_device_evidence_attestation",
]
