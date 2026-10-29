"""Purpose-separated activation is a strict, signed, time-bounded Core authority.

Covers the NEW quantitative extension activation only
(``MASKED_ANALYSIS_V3`` / ``DELTA_PUBLICATION_V1``):

- domain-separated signatures: the new ``ksi.quantitative-extension-activation``
  domain never verifies old-V2-domain bytes and vice versa;
- the old V2 activation shape (no ``purpose``) never authorizes new purposes;
- exact pins (organization, purpose, policy/runtime/envelope digests,
  designated ``ANALYSIS_WORKER``) with explicit validity, key id, and
  canonical Ed25519 signature;
- fail-closed file handling: temporary owner-private directories, fresh
  synthetic (non-production) keys per test, re-verification on every current
  check, startup and post-startup revocation/rotation, TOCTOU-protected reads.

Genuine signed key material is unavailable in this environment, so every key
below is generated fresh inside the test's private directory and every
signature is minted inside the test. Nothing here is production authority.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator
from ksi_core.domains.external.quantity.external_quantitative_extension_activation import (
    QuantitativeExtensionDeltaPublicationAuthority,
    is_quantitative_extension_current,
    load_quantitative_extension_activation,
    verified_purpose_snapshot,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, principal_permissions
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_quantitative_extension_activation import (
    QuantitativeExtensionActivationV1,
)

_NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
_KEY_ID = "quantitative-extension-activation-key-1"
_NEW_REGISTRY_VERSION = "quantitative-extension-activation-key-registry.v1"
_NEW_KEY_ROLE = "QUANTITATIVE_EXTENSION_ACTIVATION_VERIFY"
_NEW_DOMAIN = "ksi.quantitative-extension-activation.v1"
_OLD_DOMAIN = "ksi.analysis-activation.v1"
_OLD_V2_REGISTRY_VERSION = "analysis-activation-key-registry.v1"
_OLD_V2_KEY_ROLE = "ANALYSIS_ACTIVATION_VERIFY"


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


_POLICY_DIGEST = _digest("extension-policy")
_RUNTIME_DIGEST = _digest("extension-runtime")
_ENVELOPE_DIGEST = _digest("extension-envelope")


def _worker() -> Principal:
    return Principal(
        principal_id="analysis-worker-a",
        kind=PrincipalKind.ANALYSIS_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )


def _write_files(
    root: Path,
    *,
    unsigned: dict[str, Any],
    signing_domain: str = _NEW_DOMAIN,
    key_id: str = _KEY_ID,
    registry_version: str = _NEW_REGISTRY_VERSION,
    key_role: str = _NEW_KEY_ROLE,
    key_status: str = "ACTIVE",
    extra_registry_keys: list[dict[str, Any]] | None = None,
    private_key: Ed25519PrivateKey | None = None,
) -> tuple[Path, Path, Ed25519PrivateKey, QuantitativeExtensionActivationV1]:
    """Mint a fresh synthetic key, sign the payload, and lay out protected files."""
    assert principal_permissions(_worker()) == frozenset({Permission.ANALYSIS_WORK})
    signing_key = private_key or Ed25519PrivateKey.generate()
    unsigned = {**unsigned, "keyId": key_id}
    if signing_domain == _NEW_DOMAIN:
        signing_model = QuantitativeExtensionActivationV1.model_validate(
            {**unsigned, "signature": base64.b64encode(b"x" * 64).decode("ascii")}
        )
        signing_bytes = signing_model.signing_bytes()
    else:
        signing_bytes = canonical_json_bytes({"domain": signing_domain, "payload": unsigned})
    signature = base64.b64encode(signing_key.sign(signing_bytes)).decode("ascii")
    activation = QuantitativeExtensionActivationV1.model_validate(
        {**unsigned, "signature": signature}
    )

    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    activation_path = root / "quantitative-extension-activation.json"
    activation_path.write_text(
        json.dumps(activation.model_dump(by_alias=True, mode="json")), encoding="utf-8"
    )
    activation_path.chmod(0o600)
    keys = [
        {
            "keyId": key_id,
            "role": key_role,
            "algorithm": "Ed25519",
            "status": key_status,
            "publicKeyFile": f"{key_id}.public.pem",
            "notBefore": "2026-09-01T00:00:00Z",
            "notAfter": "2027-01-01T00:00:00Z",
        }
    ]
    if extra_registry_keys:
        keys.extend(extra_registry_keys)
    registry_path = root / "verification-keys.json"
    registry_path.write_text(
        json.dumps({"version": registry_version, "keys": keys}), encoding="utf-8"
    )
    registry_path.chmod(0o600)
    public_path = root / f"{key_id}.public.pem"
    public_path.write_bytes(
        signing_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    public_path.chmod(0o644)
    return activation_path, registry_path, signing_key, activation


def _unsigned(
    *,
    purpose: str = "MASKED_ANALYSIS_V3",
    organization_id: str = "org-a",
    policy_digest: str = _POLICY_DIGEST,
    runtime_digest: str = _RUNTIME_DIGEST,
    envelope_digest: str = _ENVELOPE_DIGEST,
    worker_principal_id: str = "analysis-worker-a",
    issued_at: datetime = _NOW,
    valid_until: datetime = _NOW + timedelta(hours=1),
) -> dict[str, Any]:
    return {
        "version": 1,
        "activationId": "extension-activation-test-1",
        "organizationId": organization_id,
        "purpose": purpose,
        "policyDigest": policy_digest,
        "runtimeDigest": runtime_digest,
        "resourceEnvelopeDigest": envelope_digest,
        "workerPrincipalId": worker_principal_id,
        "issuedAt": issued_at.isoformat().replace("+00:00", "Z"),
        "validUntil": valid_until.isoformat().replace("+00:00", "Z"),
    }


def _pins(**overrides: Any) -> dict[str, Any]:
    pins: dict[str, Any] = {
        "organization_id": "org-a",
        "purpose": "MASKED_ANALYSIS_V3",
        "policy_digest": _POLICY_DIGEST,
        "runtime_digest": _RUNTIME_DIGEST,
        "resource_envelope_digest": _ENVELOPE_DIGEST,
        "worker_principal": _worker(),
        "now": _NOW,
    }
    pins.update(overrides)
    return pins


def test_signing_bytes_are_domain_separated_and_window_is_half_open() -> None:
    activation = QuantitativeExtensionActivationV1.model_validate(
        {
            **_unsigned(),
            "keyId": _KEY_ID,
            "signature": base64.b64encode(b"s" * 64).decode("ascii"),
        }
    )
    payload = activation.canonical_payload()
    assert payload["purpose"] == "MASKED_ANALYSIS_V3"
    assert "signature" not in payload
    assert activation.signing_bytes() == canonical_json_bytes(
        {"domain": _NEW_DOMAIN, "payload": payload}
    )
    assert _NEW_DOMAIN != _OLD_DOMAIN
    assert activation.is_current_at(_NOW)
    assert activation.is_current_at(_NOW + timedelta(hours=1) - timedelta(microseconds=1))
    assert not activation.is_current_at(_NOW + timedelta(hours=1))
    assert not activation.is_current_at(_NOW - timedelta(microseconds=1))
    with pytest.raises(ValueError):
        activation.is_current_at(datetime(2026, 9, 29, 12, 0, 0))


def test_loader_verifies_signed_activation_and_schema(tmp_path: Path) -> None:
    activation_path, registry_path, _, activation = _write_files(tmp_path, unsigned=_unsigned())
    loaded = load_quantitative_extension_activation(activation_path, registry_path, **_pins())
    assert loaded == activation
    assert loaded.purpose == "MASKED_ANALYSIS_V3"
    schema = json.loads(
        Path("contracts/schemas/external-quantitative-extension-activation.v1.json").read_text()
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(loaded.model_dump(by_alias=True, mode="json"))


def test_cross_purpose_activation_is_rejected(tmp_path: Path) -> None:
    activation_path, registry_path, _, _ = _write_files(
        tmp_path, unsigned=_unsigned(purpose="MASKED_ANALYSIS_V3")
    )
    with pytest.raises(ValueError, match="exact trusted execution graph"):
        load_quantitative_extension_activation(
            activation_path, registry_path, **_pins(purpose="DELTA_PUBLICATION_V1")
        )


def test_purpose_tampering_after_signing_fails_closed(tmp_path: Path) -> None:
    activation_path, registry_path, _, _ = _write_files(
        tmp_path, unsigned=_unsigned(purpose="DELTA_PUBLICATION_V1")
    )
    record = json.loads(activation_path.read_text())
    record["purpose"] = "MASKED_ANALYSIS_V3"
    activation_path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        load_quantitative_extension_activation(
            activation_path, registry_path, **_pins(purpose="MASKED_ANALYSIS_V3")
        )
    with pytest.raises(ValueError):
        load_quantitative_extension_activation(
            activation_path, registry_path, **_pins(purpose="DELTA_PUBLICATION_V1")
        )


def test_old_v2_activation_shape_and_signing_domain_never_authorize(tmp_path: Path) -> None:
    # A V2-shaped file carries no purpose at all: shape error, not a fallback.
    activation_path, registry_path, _, _ = _write_files(tmp_path, unsigned=_unsigned())
    record = json.loads(activation_path.read_text())
    del record["purpose"]
    activation_path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        load_quantitative_extension_activation(activation_path, registry_path, **_pins())

    # Even with the new shape, bytes signed under the old V2 domain never verify.
    old_domain_path, old_domain_registry, _, _ = _write_files(
        tmp_path / "old-domain",
        unsigned=_unsigned(),
        signing_domain=_OLD_DOMAIN,
    )
    with pytest.raises(ValueError, match="signature verification failed"):
        load_quantitative_extension_activation(old_domain_path, old_domain_registry, **_pins())

    # The old V2 registry version and key role are not this authority.
    _, v2_registry, _, _ = _write_files(
        tmp_path / "v2-registry",
        unsigned=_unsigned(),
        registry_version=_OLD_V2_REGISTRY_VERSION,
        key_role=_OLD_V2_KEY_ROLE,
    )
    v2_activation = tmp_path / "v2-registry" / "quantitative-extension-activation.json"
    with pytest.raises(ValueError, match="unknown quantitative extension activation"):
        load_quantitative_extension_activation(v2_activation, v2_registry, **_pins())


@pytest.mark.parametrize(
    "field,value",
    [
        ("organizationId", "org-b"),
        ("purpose", "DELTA_PUBLICATION_V1"),
        ("policyDigest", _digest("other-policy")),
        ("runtimeDigest", _digest("other-runtime")),
        ("resourceEnvelopeDigest", _digest("other-envelope")),
        ("workerPrincipalId", "other-analysis-worker"),
    ],
)
def test_loader_rejects_substituted_binding(tmp_path: Path, field: str, value: str) -> None:
    activation_path, registry_path, _, _ = _write_files(tmp_path, unsigned=_unsigned())
    record = json.loads(activation_path.read_text())
    record[field] = value
    activation_path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        load_quantitative_extension_activation(activation_path, registry_path, **_pins())


def test_loader_rejects_wrong_org_worker_and_generic_workers(tmp_path: Path) -> None:
    activation_path, registry_path, _, _ = _write_files(tmp_path, unsigned=_unsigned())
    other_org_worker = Principal(
        principal_id="analysis-worker-a",
        kind=PrincipalKind.ANALYSIS_WORKER,
        role=None,
        device_id=None,
        organization_id="org-b",
    )
    with pytest.raises(ValueError, match="dedicated organization worker"):
        load_quantitative_extension_activation(
            activation_path, registry_path, **_pins(worker_principal=other_org_worker)
        )
    processing_worker = Principal(
        principal_id="analysis-worker-a",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )
    with pytest.raises(ValueError, match="dedicated organization worker"):
        load_quantitative_extension_activation(
            activation_path, registry_path, **_pins(worker_principal=processing_worker)
        )
    with pytest.raises(ValueError, match="dedicated organization worker"):
        load_quantitative_extension_activation(
            activation_path, registry_path, **_pins(organization_id="")
        )


def test_loader_rejects_expired_future_and_naive_time(tmp_path: Path) -> None:
    activation_path, registry_path, _, activation = _write_files(tmp_path, unsigned=_unsigned())
    assert activation.activation_id == "extension-activation-test-1"
    with pytest.raises(ValueError, match="not current"):
        load_quantitative_extension_activation(
            activation_path, registry_path, **_pins(now=_NOW + timedelta(hours=1))
        )
    assert not is_quantitative_extension_current(
        activation_path,
        registry_path,
        **_pins(now=_NOW + timedelta(hours=1)),
    )
    assert is_quantitative_extension_current(activation_path, registry_path, **_pins())

    future_path, future_registry, _, _ = _write_files(
        tmp_path / "future",
        unsigned=_unsigned(
            issued_at=_NOW + timedelta(minutes=1),
            valid_until=_NOW + timedelta(hours=1, minutes=1),
        ),
    )
    with pytest.raises(ValueError, match="not current"):
        load_quantitative_extension_activation(future_path, future_registry, **_pins())

    naive = datetime(2026, 9, 29, 12, 0, 0)
    with pytest.raises(ValueError, match="UTC-aware"):
        load_quantitative_extension_activation(
            activation_path,
            registry_path,
            **_pins(now=naive),
        )
    assert not is_quantitative_extension_current(
        activation_path,
        registry_path,
        **_pins(now=naive),
    )


def test_loader_verifies_expired_activation_for_read_only_history_replay(tmp_path: Path) -> None:
    activation_path, registry_path, _, activation = _write_files(tmp_path, unsigned=_unsigned())
    loaded = load_quantitative_extension_activation(
        activation_path,
        registry_path,
        **_pins(now=_NOW + timedelta(hours=1), allow_out_of_window=True),
    )
    assert loaded == activation
    assert not loaded.is_current_at(_NOW + timedelta(hours=1))


def test_loader_rejects_signature_tampering_and_unknown_fields(tmp_path: Path) -> None:
    activation_path, registry_path, _, activation = _write_files(tmp_path, unsigned=_unsigned())
    record = json.loads(activation_path.read_text())
    replacement = "A" if activation.signature[0] != "A" else "B"
    record["signature"] = replacement + activation.signature[1:]
    activation_path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="signature"):
        load_quantitative_extension_activation(activation_path, registry_path, **_pins())

    activation_path2, registry_path2, _, _ = _write_files(
        tmp_path / "unknown-field", unsigned=_unsigned()
    )
    record2 = json.loads(activation_path2.read_text())
    record2["unexpectedField"] = "injected"
    activation_path2.write_text(json.dumps(record2))
    with pytest.raises(ValueError):
        load_quantitative_extension_activation(activation_path2, registry_path2, **_pins())


def test_loader_rejects_duplicate_fields_and_missing_files(tmp_path: Path) -> None:
    activation_path, registry_path, _, _ = _write_files(tmp_path, unsigned=_unsigned())
    registry = json.loads(registry_path.read_text())
    registry["keys"][0]["keyId"] = "different-key-id"
    registry_path.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="missing or ambiguous"):
        load_quantitative_extension_activation(activation_path, registry_path, **_pins())

    activation_path.write_text('{"version":1,"version":1}')
    with pytest.raises(ValueError, match="strict protected JSON"):
        load_quantitative_extension_activation(activation_path, registry_path, **_pins())

    # No genuine signed material and no defaults: missing files fail closed.
    with pytest.raises(ValueError):
        load_quantitative_extension_activation(
            tmp_path / "absent-activation.json",
            registry_path,
            **_pins(),
        )
    with pytest.raises(ValueError):
        load_quantitative_extension_activation(
            activation_path,
            tmp_path / "absent-registry.json",
            **_pins(),
        )


def test_symlink_and_non_regular_activation_fail_closed(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    activation_path, registry_path, _, _ = _write_files(real_dir, unsigned=_unsigned())
    link_dir = tmp_path / "linked"
    link_dir.mkdir(mode=0o700)
    linked = link_dir / "quantitative-extension-activation.json"
    linked.symlink_to(activation_path)
    with pytest.raises(ValueError, match="strict protected JSON"):
        load_quantitative_extension_activation(linked, registry_path, **_pins())

    directory_as_file = tmp_path / "a-directory"
    directory_as_file.mkdir(mode=0o700)
    with pytest.raises(ValueError):
        load_quantitative_extension_activation(directory_as_file, registry_path, **_pins())


def test_startup_revocation_and_unknown_key_fail_closed(tmp_path: Path) -> None:
    activation_path, revoked_registry, _, _ = _write_files(
        tmp_path / "revoked", unsigned=_unsigned(), key_status="REVOKED"
    )
    with pytest.raises(ValueError, match="required verification role"):
        load_quantitative_extension_activation(activation_path, revoked_registry, **_pins())
    assert not is_quantitative_extension_current(activation_path, revoked_registry, **_pins())


def test_post_startup_revocation_fails_the_next_check(tmp_path: Path) -> None:
    activation_path, registry_path, _, _ = _write_files(tmp_path, unsigned=_unsigned())
    assert is_quantitative_extension_current(activation_path, registry_path, **_pins())
    registry = json.loads(registry_path.read_text())
    registry["keys"][0]["status"] = "REVOKED"
    registry_path.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="required verification role"):
        load_quantitative_extension_activation(activation_path, registry_path, **_pins())
    assert not is_quantitative_extension_current(activation_path, registry_path, **_pins())


def test_key_rotation_rekey_and_removal(tmp_path: Path) -> None:
    new_key = Ed25519PrivateKey.generate()
    new_public_pem = new_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    activation_path, registry_path, _, _ = _write_files(tmp_path, unsigned=_unsigned())
    registry = json.loads(registry_path.read_text())
    registry["keys"].append(
        {
            "keyId": "quantitative-extension-activation-key-2",
            "role": _NEW_KEY_ROLE,
            "algorithm": "Ed25519",
            "status": "ACTIVE",
            "publicKeyFile": "quantitative-extension-activation-key-2.public.pem",
            "notBefore": "2026-09-01T00:00:00Z",
            "notAfter": "2027-01-01T00:00:00Z",
        }
    )
    registry_path.write_text(json.dumps(registry))
    second_public = tmp_path / "quantitative-extension-activation-key-2.public.pem"
    second_public.write_bytes(new_public_pem)
    second_public.chmod(0o644)

    rotated_path, _, _, rotated = _write_files(
        tmp_path / "rotated",
        unsigned=_unsigned(),
        key_id="quantitative-extension-activation-key-2",
        private_key=new_key,
    )
    # The rotated activation verifies against its own registry copy.
    assert (
        load_quantitative_extension_activation(
            rotated_path, tmp_path / "rotated" / "verification-keys.json", **_pins()
        )
        == rotated
    )
    # Removing the original key breaks the original activation: no fallback.
    registry = json.loads(registry_path.read_text())
    registry["keys"] = [key for key in registry["keys"] if key["keyId"] != _KEY_ID]
    registry_path.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="missing or ambiguous"):
        load_quantitative_extension_activation(activation_path, registry_path, **_pins())


def test_verified_purpose_snapshot_projects_verified_activation_only(tmp_path: Path) -> None:
    activation_path, registry_path, _, activation = _write_files(tmp_path, unsigned=_unsigned())
    loaded = load_quantitative_extension_activation(activation_path, registry_path, **_pins())
    snapshot = verified_purpose_snapshot(loaded)
    assert snapshot.purpose == "MASKED_ANALYSIS_V3"
    assert snapshot.activation_id == activation.activation_id
    assert snapshot.organization_id == "org-a"
    assert snapshot.worker_principal_id == "analysis-worker-a"
    assert snapshot.policy_digest == _POLICY_DIGEST
    assert snapshot.runtime_digest == _RUNTIME_DIGEST
    assert snapshot.resource_envelope_digest == _ENVELOPE_DIGEST
    assert snapshot.is_current_at(_NOW)
    assert not snapshot.is_current_at(_NOW + timedelta(hours=1))
    with pytest.raises(ValueError):
        snapshot.is_current_at(datetime(2026, 9, 29, 12, 0, 0))
    with pytest.raises(ValueError, match="verified quantitative extension activation"):
        verified_purpose_snapshot(activation="not-an-activation")  # type: ignore[arg-type]


def _delta_authority(
    activation_path: Path,
    registry_path: Path,
    coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
) -> QuantitativeExtensionDeltaPublicationAuthority:
    return QuantitativeExtensionDeltaPublicationAuthority(
        activation_path=activation_path,
        verification_keys_path=registry_path,
        organization_id="org-a",
        policy_digest=_POLICY_DIGEST,
        runtime_digest=_RUNTIME_DIGEST,
        resource_envelope_digest=_ENVELOPE_DIGEST,
        worker_principal=_worker(),
        coordinator=coordinator,
    )


def test_delta_authority_adapter_reports_policy_and_runtime_currency(tmp_path: Path) -> None:
    activation_path, registry_path, _, _ = _write_files(
        tmp_path, unsigned=_unsigned(purpose="DELTA_PUBLICATION_V1")
    )
    authority = _delta_authority(
        activation_path, registry_path, ExternalAuthorityCurrentnessCoordinator()
    )
    assert authority.purpose == "DELTA_PUBLICATION_V1"
    assert authority.is_policy_current(policy_digest=_POLICY_DIGEST, now=_NOW)
    assert not authority.is_policy_current(policy_digest=_digest("other-policy"), now=_NOW)
    assert not authority.is_policy_current(policy_digest="not-a-digest", now=_NOW)
    assert authority.is_runtime_current(now=_NOW)
    assert authority.is_runtime_current(
        now=_NOW,
        worker_principal_id="analysis-worker-a",
        publication_id="delta-pub-1",
        lease_generation=3,
    )
    # Actual lease liveness belongs to the publication store: a shape-valid
    # generation reports activation currency, not lease rights.
    assert authority.is_runtime_current(now=_NOW, lease_generation=999)
    assert not authority.is_runtime_current(now=_NOW + timedelta(hours=1), lease_generation=1)


def test_delta_authority_adapter_rejects_wrong_attempt_shapes(tmp_path: Path) -> None:
    activation_path, registry_path, _, _ = _write_files(
        tmp_path, unsigned=_unsigned(purpose="DELTA_PUBLICATION_V1")
    )
    authority = _delta_authority(activation_path, registry_path)
    assert not authority.is_runtime_current(now=_NOW, worker_principal_id="other-worker")
    assert not authority.is_runtime_current(now=_NOW, publication_id="../escape")
    assert not authority.is_runtime_current(now=_NOW, publication_id="https://example.invalid/x")
    assert not authority.is_runtime_current(now=_NOW, lease_generation=0)
    assert not authority.is_runtime_current(now=_NOW, lease_generation=True)
    assert not authority.is_runtime_current(now=_NOW, lease_generation="3")  # type: ignore[arg-type]
    naive = datetime(2026, 9, 29, 12, 0, 0)
    assert not authority.is_runtime_current(now=naive)
    assert not authority.is_policy_current(policy_digest=_POLICY_DIGEST, now=naive)


def test_delta_authority_adapter_rejects_masked_purpose_and_revocation(tmp_path: Path) -> None:
    activation_path, registry_path, _, _ = _write_files(
        tmp_path, unsigned=_unsigned(purpose="MASKED_ANALYSIS_V3")
    )
    authority = _delta_authority(activation_path, registry_path)
    assert not authority.is_policy_current(policy_digest=_POLICY_DIGEST, now=_NOW)
    assert not authority.is_runtime_current(now=_NOW)

    delta_path, delta_registry, _, _ = _write_files(
        tmp_path / "delta", unsigned=_unsigned(purpose="DELTA_PUBLICATION_V1")
    )
    live = _delta_authority(delta_path, delta_registry)
    assert live.is_policy_current(policy_digest=_POLICY_DIGEST, now=_NOW)
    registry = json.loads(delta_registry.read_text())
    registry["keys"][0]["status"] = "REVOKED"
    delta_registry.write_text(json.dumps(registry))
    assert not live.is_policy_current(policy_digest=_POLICY_DIGEST, now=_NOW)
    assert not live.is_runtime_current(now=_NOW)


def test_delta_authority_adapter_constructor_pins_and_protocol_shape(tmp_path: Path) -> None:
    activation_path, registry_path, _, _ = _write_files(
        tmp_path, unsigned=_unsigned(purpose="DELTA_PUBLICATION_V1")
    )
    with pytest.raises(ValueError):
        QuantitativeExtensionDeltaPublicationAuthority(
            activation_path=activation_path,
            verification_keys_path=registry_path,
            organization_id="org-a",
            policy_digest="not-a-digest",
            runtime_digest=_RUNTIME_DIGEST,
            resource_envelope_digest=_ENVELOPE_DIGEST,
            worker_principal=_worker(),
        )
    processing_worker = Principal(
        principal_id="analysis-worker-a",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )
    with pytest.raises(ValueError, match="dedicated organization worker"):
        QuantitativeExtensionDeltaPublicationAuthority(
            activation_path=activation_path,
            verification_keys_path=registry_path,
            organization_id="org-a",
            policy_digest=_POLICY_DIGEST,
            runtime_digest=_RUNTIME_DIGEST,
            resource_envelope_digest=_ENVELOPE_DIGEST,
            worker_principal=processing_worker,
        )
    # Structural protocol conformance: the publication store only requires the
    # two currency callables, which the adapter provides.
    authority = _delta_authority(activation_path, registry_path)
    assert callable(authority.is_policy_current)
    assert callable(authority.is_runtime_current)


def test_store_authority_path_accepts_real_adapter_and_fails_closed_on_revocation(
    tmp_path: Path,
) -> None:
    from ksi_core.domains.external.quantity.external_delta_publications import (
        DeltaPublicationPolicy,
        ExternalDeltaPublicationStore,
    )
    from ksi_core.foundation.durable_journal import DurableJournal

    activation_path, registry_path, _, _ = _write_files(
        tmp_path / "activation", unsigned=_unsigned(purpose="DELTA_PUBLICATION_V1")
    )

    class _Source:
        def resolve_current_source(self, **kwargs: Any) -> None:
            return None

    class _Egress:
        def is_egress_allowed(self, **kwargs: Any) -> bool:
            return True

    class _Bytes:
        def stage_stream(self, **kwargs: Any) -> Path:
            raise AssertionError("not exercised")

        def commit(self, **kwargs: Any) -> None:
            raise AssertionError("not exercised")

        def discard(self, **kwargs: Any) -> None:
            raise AssertionError("not exercised")

        def exists(self, **kwargs: Any) -> bool:
            return False

        def open_read(self, **kwargs: Any) -> Any:
            raise AssertionError("not exercised")

    class _Observations:
        def resolve_output_observation(self, **kwargs: Any) -> None:
            return None

    policy = DeltaPublicationPolicy(
        policy_id="delta-pub-policy",
        version=1,
        max_output_bytes=1_000_000,
        max_grid_cells=10_000,
        max_lifetime_seconds=3600,
        max_active_publications=4,
        upload_lease_duration_seconds=60,
        max_upload_attempts=4,
    )
    journal = DurableJournal(tmp_path / "journal" / "delta-publications.jsonl")
    try:
        store = ExternalDeltaPublicationStore(
            journal,
            source_witness=_Source(),
            authority=_delta_authority(activation_path, registry_path),
            egress=_Egress(),
            byte_store=_Bytes(),
            observations=_Observations(),
            policy=policy,
            clock=lambda: _NOW,
        )
        assert store._authority_is_current(_NOW, _POLICY_DIGEST) is True
        registry = json.loads(registry_path.read_text())
        registry["keys"][0]["status"] = "REVOKED"
        registry_path.write_text(json.dumps(registry))
        assert store._authority_is_current(_NOW, _POLICY_DIGEST) is False
    finally:
        journal.close()
