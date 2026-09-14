from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_domain.canonical_json import canonical_json_bytes

NOW = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.chmod(path, 0o600)


def _provider_config(tmp_path: Path, *, signer_out: list[Ed25519PrivateKey] | None = None) -> Path:
    signer = Ed25519PrivateKey.generate()
    if signer_out is not None:
        signer_out.append(signer)
    public_key_path = tmp_path / "authority-bundle.pem"
    public_key_path.write_bytes(
        signer.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    os.chmod(public_key_path, 0o600)
    _write(
        tmp_path / "authority-keys.json",
        {
            "version": "external-authority-key-registry.v1",
            "keys": [
                {
                    "keyId": "authority-key-1",
                    "role": "AUTHORITY_BUNDLE",
                    "algorithm": "Ed25519",
                    "status": "ACTIVE",
                    "publicKeyFile": public_key_path.name,
                    "notBefore": "2026-09-10T00:00:00Z",
                    "notAfter": "2026-09-12T00:00:00Z",
                }
            ],
        },
    )
    unsigned = {
        "version": "external-authority-provider-snapshot.v1",
        "organizationId": "org-a",
        "sequence": 1,
        "previousSnapshotDigest": None,
        "issuedAt": "2026-09-11T00:00:00Z",
        "validUntil": "2026-09-11T01:00:00Z",
        "keyId": "authority-key-1",
        "catalogAuthorities": {"records": [], "currentDigests": []},
        "policyAuthorities": {"records": [], "currentDigests": []},
        "evidenceContexts": {"records": [], "currentDigests": []},
        "quantitativeAdministration": {"actions": []},
    }
    _write(
        tmp_path / "authority-snapshot.json",
        {
            **unsigned,
            "signature": base64.b64encode(
                signer.sign(
                    canonical_json_bytes(
                        {
                            "domain": "ksi.external-authority-provider-snapshot.v1",
                            "snapshot": unsigned,
                        }
                    )
                )
            ).decode("ascii"),
        },
    )
    config_path = tmp_path / "external-authority-provider.json"
    _write(
        config_path,
        {
            "version": "external-authority-provider-config.v1",
            "organizationId": "org-a",
            "keyRegistryPath": str(tmp_path / "authority-keys.json"),
            "snapshotPath": str(tmp_path / "authority-snapshot.json"),
            "catalogAdministrationActorId": "catalog-admin",
            "leaseTtlSeconds": 60,
            "deadlineAfterIssueSeconds": 120,
            "maxAttempts": 3,
            "maxActiveRequestsPerOrganization": 2,
        },
    )
    return config_path


def _replace_signed_snapshot(
    tmp_path: Path, signer: Ed25519PrivateKey, changes: dict[str, object]
) -> None:
    snapshot_path = tmp_path / "authority-snapshot.json"
    raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    unsigned = {key: value for key, value in raw.items() if key != "signature"} | changes
    _write(
        snapshot_path,
        {
            **unsigned,
            "signature": base64.b64encode(
                signer.sign(
                    canonical_json_bytes(
                        {
                            "domain": "ksi.external-authority-provider-snapshot.v1",
                            "snapshot": unsigned,
                        }
                    )
                )
            ).decode("ascii"),
        },
    )


def _empty_app(provider: Any, coordinator: ExternalAuthorityCurrentnessCoordinator) -> Any:
    app = type("_App", (), {})()
    app.state = type("_State", (), {})()
    app.state.external_authority_currentness = coordinator
    app.state.external_validation_policy_registry = type(
        "_Registry",
        (),
        {
            "coordinator": coordinator,
            "authority_currentness_port": provider.participants.build_policy_authority_currentness(
                coordinator
            ),
        },
    )()
    app.state.external_artifact_inspection_store = type(
        "_Inspections", (), {"coordinator": coordinator, "reconcile_sealed": lambda _self, _now: 0}
    )()
    app.state.external_evidence_store = type(
        "_EvidenceStore",
        (),
        {"coordinator": coordinator, "sealed_items_snapshot": lambda _self: ()},
    )()
    app.state.external_evidence_validation_store = type(
        "_Evidence",
        (),
        {"coordinator": coordinator, "issue_after_seal": lambda _self, _ref, *, now: None},
    )()
    app.state.external_relative_volume_mapping_authority = type(
        "_Catalog", (), {"currentness_coordinator": coordinator}
    )()
    return app


def test_restart_rejects_a_signed_same_sequence_snapshot_substitution(tmp_path: Path) -> None:
    fixture_signers: list[Ed25519PrivateKey] = []
    from ksi_core.external_authority_provider import (
        ExternalAuthorityProviderError,
        load_external_authority_provider,
    )

    config_path = _provider_config(tmp_path, signer_out=fixture_signers)
    provider = load_external_authority_provider(
        config_path, clock=lambda: NOW + timedelta(minutes=1)
    )
    receipts_path = tmp_path / "external-authority-provider-receipts.jsonl"
    receipts = DurableJournal(receipts_path)
    provider.bind_receipt_journal(receipts)
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    provider.attach_app(_empty_app(provider, coordinator))
    receipts.close()
    _replace_signed_snapshot(
        tmp_path,
        fixture_signers[0],
        {"validUntil": "2026-09-11T00:30:00Z"},
    )

    restarted = load_external_authority_provider(
        config_path, clock=lambda: NOW + timedelta(minutes=1)
    )
    with pytest.raises(ExternalAuthorityProviderError, match="receipt history is blocked"):
        restarted.bind_receipt_journal(DurableJournal(receipts_path))

    assert restarted.status()["status"] == "BLOCKED"


def test_restart_rejects_tampered_receipt_history(tmp_path: Path) -> None:
    from ksi_core.external_authority_provider import (
        ExternalAuthorityProviderError,
        load_external_authority_provider,
    )

    config_path = _provider_config(tmp_path)
    provider = load_external_authority_provider(
        config_path, clock=lambda: NOW + timedelta(minutes=1)
    )
    receipts_path = tmp_path / "external-authority-provider-receipts.jsonl"
    receipts = DurableJournal(receipts_path)
    provider.bind_receipt_journal(receipts)
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    provider.attach_app(_empty_app(provider, coordinator))
    receipts.close()
    receipt = json.loads(receipts_path.read_text(encoding="utf-8"))
    receipt["sequence"] = 2
    receipts_path.write_text(json.dumps(receipt, separators=(",", ":")) + "\n", encoding="utf-8")
    os.chmod(receipts_path, 0o600)

    restarted = load_external_authority_provider(
        config_path, clock=lambda: NOW + timedelta(minutes=1)
    )
    with pytest.raises(ExternalAuthorityProviderError, match="receipt history is blocked"):
        restarted.bind_receipt_journal(DurableJournal(receipts_path))

    assert restarted.status()["status"] == "BLOCKED"


def test_restart_rejects_reused_key_id_with_different_public_material(tmp_path: Path) -> None:
    fixture_signers: list[Ed25519PrivateKey] = []
    from ksi_core.external_authority_provider import (
        ExternalAuthorityProviderError,
        load_external_authority_provider,
    )

    config_path = _provider_config(tmp_path, signer_out=fixture_signers)
    provider = load_external_authority_provider(
        config_path, clock=lambda: NOW + timedelta(minutes=1)
    )
    receipts_path = tmp_path / "external-authority-provider-receipts.jsonl"
    receipts = DurableJournal(receipts_path)
    provider.bind_receipt_journal(receipts)
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    provider.attach_app(_empty_app(provider, coordinator))
    first_digest = provider.status()["snapshotDigest"]
    assert isinstance(first_digest, str)
    receipts.close()
    replacement_signer = Ed25519PrivateKey.generate()
    public_key_path = tmp_path / "authority-bundle.pem"
    public_key_path.write_bytes(
        replacement_signer.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    os.chmod(public_key_path, 0o600)
    _replace_signed_snapshot(
        tmp_path,
        replacement_signer,
        {
            "sequence": 2,
            "previousSnapshotDigest": first_digest,
            "issuedAt": "2026-09-11T00:01:00Z",
        },
    )

    restarted = load_external_authority_provider(
        config_path, clock=lambda: NOW + timedelta(minutes=2)
    )
    with pytest.raises(ExternalAuthorityProviderError, match="receipt history is blocked"):
        restarted.bind_receipt_journal(DurableJournal(receipts_path))

    assert restarted.status()["status"] == "BLOCKED"
