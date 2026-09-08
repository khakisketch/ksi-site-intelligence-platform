"""Concrete local manifest/trust/revocation readers for inspector admission.

These readers use only operator-provisioned immutable files.  They expose no
network refresh, manifest selection, or permissive trust fallback.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionManifestSignatureV1,
    InspectorExecutionManifestV1,
    SignatureVerificationVerdict,
    parse_inspector_execution_manifest_wire,
)

from ksi_processing_controller.external_inspector_launcher import CatalogStartupStatusV1


class InspectorCatalogUnavailable(RuntimeError):
    """An operator-provisioned catalog, trust root, or revocation record is unavailable."""


@dataclass(frozen=True, slots=True)
class InspectorTrustRootV1:
    """Exact key IDs and raw Ed25519 public bytes; no key discovery is allowed."""

    public_keys: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if not self.public_keys:
            raise ValueError("inspector trust root requires at least one public key")
        for key_id, public_key in self.public_keys.items():
            if not isinstance(key_id, str) or not key_id or not isinstance(public_key, bytes):
                raise ValueError("inspector trust root key is invalid")
            try:
                Ed25519PublicKey.from_public_bytes(public_key)
            except ValueError as exc:
                raise ValueError("inspector trust root key is not Ed25519") from exc


class Ed25519InspectorManifestVerifier:
    """Concrete detached Ed25519 verifier with no unknown-key fallback."""

    def __init__(self, trust_root: InspectorTrustRootV1) -> None:
        self._trust_root = trust_root

    def verify(
        self, payload: bytes, signature: InspectorExecutionManifestSignatureV1
    ) -> SignatureVerificationVerdict:
        key_bytes = self._trust_root.public_keys.get(signature.key_id)
        if key_bytes is None:
            return SignatureVerificationVerdict.UNKNOWN
        if hashlib.sha256(payload).hexdigest() != signature.digest.removeprefix("sha256:"):
            return SignatureVerificationVerdict.INVALID
        try:
            Ed25519PublicKey.from_public_bytes(key_bytes).verify(
                signature.signature_bytes(), payload
            )
        except (InvalidSignature, ValueError):
            return SignatureVerificationVerdict.INVALID
        return SignatureVerificationVerdict.VALID


@dataclass(frozen=True, slots=True)
class FileInspectorCatalogConfigV1:
    manifest_path: Path
    revocation_path: Path
    expected_revocation_sha256: str

    def __post_init__(self) -> None:
        if not self.manifest_path.is_absolute() or not self.revocation_path.is_absolute():
            raise ValueError("inspector catalog paths must be absolute")
        if (
            not isinstance(self.expected_revocation_sha256, str)
            or not self.expected_revocation_sha256.startswith("sha256:")
            or len(self.expected_revocation_sha256) != 71
        ):
            raise ValueError("inspector revocation digest is invalid")


class FileInspectorManifestCatalog:
    """One fixed manifest and a digest-pinned local revocation record."""

    def __init__(self, config: FileInspectorCatalogConfigV1) -> None:
        self._config = config

    def startup_status(self) -> CatalogStartupStatusV1:
        try:
            self._read_manifest()
            self._read_revocations()
        except InspectorCatalogUnavailable:
            return CatalogStartupStatusV1(
                readable=False, trust_root_configured=False, catalog_identity_verified=False
            )
        return CatalogStartupStatusV1(
            readable=True, trust_root_configured=True, catalog_identity_verified=True
        )

    def resolve_exact(
        self, *, parser_build_digest: str, resource_envelope_digest: str
    ) -> InspectorExecutionManifestV1 | None:
        manifest = self._read_manifest()
        if (
            manifest.parser_build_digest != parser_build_digest
            or manifest.body.resource_envelope_digest != resource_envelope_digest
        ):
            return None
        return manifest

    def is_revoked(self, manifest: InspectorExecutionManifestV1) -> bool:
        return manifest.canonical_body_digest() in self._read_revocations()

    def _read_manifest(self) -> InspectorExecutionManifestV1:
        try:
            raw = json.loads(self._config.manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError
            return parse_inspector_execution_manifest_wire(raw)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise InspectorCatalogUnavailable("fixed inspector manifest is unavailable") from exc

    def _read_revocations(self) -> frozenset[str]:
        try:
            raw_bytes = self._config.revocation_path.read_bytes()
        except OSError as exc:
            raise InspectorCatalogUnavailable(
                "fixed inspector revocation record is unavailable"
            ) from exc
        observed = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
        if observed != self._config.expected_revocation_sha256:
            raise InspectorCatalogUnavailable("fixed inspector revocation record digest changed")
        try:
            raw: Any = json.loads(raw_bytes)
            if (
                not isinstance(raw, dict)
                or raw.get("version") != "external-inspector-revocations.v1"
                or not isinstance(raw.get("revokedManifestDigests"), list)
            ):
                raise ValueError
            values = raw["revokedManifestDigests"]
            if any(
                not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71
                for value in values
            ):
                raise ValueError
            if values != sorted(set(values)):
                raise ValueError
            return frozenset(values)
        except (UnicodeDecodeError, ValueError, TypeError) as exc:
            raise InspectorCatalogUnavailable(
                "fixed inspector revocation record is malformed"
            ) from exc


__all__ = [
    "Ed25519InspectorManifestVerifier",
    "FileInspectorCatalogConfigV1",
    "FileInspectorManifestCatalog",
    "InspectorCatalogUnavailable",
    "InspectorTrustRootV1",
]
