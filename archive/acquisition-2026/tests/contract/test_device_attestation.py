"""Device evidence attestation registry and canonical signature negatives."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.device_attestation import (
    DeviceAttestationError,
    DeviceAttestationKeyRecord,
    DeviceAttestationKeyStatus,
    DeviceAttestationRegistry,
    DeviceAttestationVerdict,
    DeviceEvidenceAttestation,
    evidence_attestation_payload,
    load_device_attestation_registry,
    verify_device_evidence_attestation,
)
from ksi_domain.canonical_json import canonical_json_bytes


def _payload(**overrides: str) -> dict[str, str]:
    value = evidence_attestation_payload(
        device_id="edge-001",
        site_id="site-001",
        mission_id="mission-001",
        event_key="edge-001::event-001",
        artifact_id="risk-001.json",
        content_type="application/json",
        content_digest="sha256:" + "a" * 64,
    )
    value.update(overrides)
    return value


def _attestation(
    key: Ed25519PrivateKey, payload: dict[str, str], key_id: str = "key-001"
) -> DeviceEvidenceAttestation:
    signature = (
        base64.urlsafe_b64encode(key.sign(canonical_json_bytes(payload)))
        .decode()
        .rstrip("=")
    )
    return DeviceEvidenceAttestation(
        key_id=key_id, algorithm="Ed25519", signature=signature
    )


@pytest.mark.parametrize(
    ("changed"),
    [
        {"contentDigest": "sha256:" + "b" * 64},
        {"eventKey": "edge-001::event-002"},
        {"artifactId": "risk-002.json"},
        {"missionId": "mission-002"},
        {"siteId": "site-002"},
        {"deviceId": "edge-002"},
    ],
)
def test_identity_or_digest_mutation_invalidates_signature(changed: dict[str, str]) -> None:
    key = Ed25519PrivateKey.generate()
    registry = DeviceAttestationRegistry(
        [DeviceAttestationKeyRecord("edge-001", "key-001", key.public_key())]
    )
    signed = _attestation(key, _payload())
    result = verify_device_evidence_attestation(
        signed,
        registry,
        payload=_payload(**changed),
        device_id="edge-001",
    )
    assert result.verdict is DeviceAttestationVerdict.INVALID_SIGNATURE


def test_unknown_cross_device_revoked_and_expired_keys_are_distinct() -> None:
    now = datetime.now(UTC)
    active = Ed25519PrivateKey.generate()
    revoked = Ed25519PrivateKey.generate()
    expired = Ed25519PrivateKey.generate()
    registry = DeviceAttestationRegistry(
        [
            DeviceAttestationKeyRecord("edge-002", "cross-key", active.public_key()),
            DeviceAttestationKeyRecord(
                "edge-001",
                "revoked-key",
                revoked.public_key(),
                status=DeviceAttestationKeyStatus.REVOKED,
            ),
            DeviceAttestationKeyRecord(
                "edge-001",
                "expired-key",
                expired.public_key(),
                not_after=now - timedelta(seconds=1),
            ),
        ]
    )
    cases = (
        (_attestation(active, _payload(), "unknown-key"), DeviceAttestationVerdict.UNKNOWN_KEY),
        (_attestation(active, _payload(), "cross-key"), DeviceAttestationVerdict.CROSS_DEVICE_KEY),
        (_attestation(revoked, _payload(), "revoked-key"), DeviceAttestationVerdict.REVOKED_KEY),
        (_attestation(expired, _payload(), "expired-key"), DeviceAttestationVerdict.KEY_EXPIRED),
    )
    for attestation, expected in cases:
        assert (
            verify_device_evidence_attestation(
                attestation,
                registry,
                payload=_payload(),
                device_id="edge-001",
                now=now,
            ).verdict
            is expected
        )


def test_signature_must_be_unpadded_base64url() -> None:
    key = Ed25519PrivateKey.generate()
    registry = DeviceAttestationRegistry(
        [DeviceAttestationKeyRecord("edge-001", "key-001", key.public_key())]
    )
    valid = _attestation(key, _payload())
    malformed = valid.model_copy(update={"signature": valid.signature + "="})
    assert (
        verify_device_evidence_attestation(
            malformed, registry, payload=_payload(), device_id="edge-001"
        ).verdict
        is DeviceAttestationVerdict.MALFORMED_SIGNATURE
    )


def test_manifest_loads_public_keys_and_rejects_path_escape(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    public_path = tmp_path / "edge-001.public.pem"
    public_path.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    manifest = tmp_path / "device-keys.json"
    manifest.write_text(
        json.dumps(
            {
                "keys": [
                    {
                        "deviceId": "edge-001",
                        "keyId": "key-001",
                        "publicKeyFile": public_path.name,
                        "status": "ACTIVE",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert load_device_attestation_registry(manifest).get("edge-001", "key-001") is not None

    manifest.write_text(
        json.dumps(
            {
                "keys": [
                    {
                        "deviceId": "edge-001",
                        "keyId": "key-001",
                        "publicKeyFile": "../outside.pem",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(DeviceAttestationError, match="manifest 디렉터리"):
        load_device_attestation_registry(manifest)
