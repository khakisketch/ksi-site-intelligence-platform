from __future__ import annotations

import base64
import hashlib
import importlib
import json
import os
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import test_external_quantitative_production_flow as production_flow
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_quantitative_authority import (
    CompatibilityRuleDescriptorV1,
    ExternalQuantitativeAuthorityCatalog,
    ExternalQuantitativeCatalogAuthorityRecord,
)
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityRecord,
    PolicySelectionStatus,
    authorized_policy_body_digest,
)
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    PolicyStatus,
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1
from test_external_quantitative_authority import _mapping

NOW = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize("target", ["config", "key"])
def test_provider_rejects_hardlinked_trust_files(tmp_path: Path, target: str) -> None:
    from ksi_core.external_authority_provider import (
        ExternalAuthorityProviderError,
        load_external_authority_provider,
    )

    config = _provider_config(tmp_path)
    path = config if target == "config" else tmp_path / "authority-bundle.pem"
    os.link(path, tmp_path / "extra-link")
    with pytest.raises(ExternalAuthorityProviderError):
        load_external_authority_provider(config, clock=lambda: NOW)


@pytest.mark.parametrize("damage", ["oversized", "writable", "symlink"])
def test_provider_rejects_unsafe_public_key_material(tmp_path: Path, damage: str) -> None:
    from ksi_core.external_authority_provider import (
        ExternalAuthorityProviderError,
        load_external_authority_provider,
    )

    config = _provider_config(tmp_path)
    key = tmp_path / "authority-bundle.pem"
    if damage == "oversized":
        key.write_bytes(key.read_bytes() + b" " * 16_384)
    elif damage == "writable":
        key.chmod(0o666)
    else:
        retained = tmp_path / "retained.pem"
        key.rename(retained)
        key.symlink_to(retained)
    with pytest.raises(ExternalAuthorityProviderError):
        load_external_authority_provider(config, clock=lambda: NOW)


def test_provider_consumes_descriptor_bytes_without_path_reopens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ksi_core.external_authority_provider import load_external_authority_provider

    config = _provider_config(tmp_path)

    def forbidden(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("trust material was reopened by pathname")

    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    provider = load_external_authority_provider(config, clock=lambda: NOW)
    assert provider.status()["status"] == "CONFIG_VALIDATED"


@pytest.mark.parametrize("damage", ["malformed", "synthetic", "wrong_actor", "missing_authority"])
def test_preflight_rejects_unusable_signed_policy_actions(tmp_path: Path, damage: str) -> None:
    from ksi_core.external_authority_provider import (
        ExternalAuthorityProviderError,
        load_external_authority_provider,
    )

    policy, authority = _administrable_policy()
    if damage == "synthetic":
        policy = policy.model_copy(update={"synthetic_test_only": True, "policy_digest": None})
        policy = policy.sealed()
    payload = {} if damage == "malformed" else policy.model_dump(by_alias=True, mode="json")
    config = _provider_config(
        tmp_path,
        policy_records=() if damage == "missing_authority" else (authority.event_payload(),),
        actions=({
            "actionId": "test-policy-admission",
            "kind": "ADMIT_POLICY",
            "effectiveAt": "2026-09-11T00:00:00Z",
            "actorId": "unapproved" if damage == "wrong_actor" else "policy-admin",
            "policy": payload,
        },),
    )
    with pytest.raises(ExternalAuthorityProviderError):
        load_external_authority_provider(config, clock=lambda: NOW)


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.chmod(path, 0o600)


def _provider_config(
    tmp_path: Path,
    *,
    catalog_records: tuple[dict[str, object], ...] = (),
    policy_records: tuple[dict[str, object], ...] = (),
    context_records: tuple[dict[str, object], ...] = (),
    actions: tuple[dict[str, object], ...] = (),
    fixture_signers: list[Ed25519PrivateKey] | None = None,
) -> Path:
    signer = Ed25519PrivateKey.generate()
    if fixture_signers is not None:
        fixture_signers.append(signer)
    public_key = tmp_path / "authority-bundle.pem"
    public_key.write_bytes(
        signer.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    os.chmod(public_key, 0o600)
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
                    "publicKeyFile": public_key.name,
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
        "catalogAuthorities": {
            "records": list(catalog_records),
            "currentDigests": [record["digest"] for record in catalog_records],
        },
        "policyAuthorities": {
            "records": list(policy_records),
            "currentDigests": [record["digest"] for record in policy_records],
        },
        "evidenceContexts": {
            "records": list(context_records),
            "currentDigests": [record["contextDigest"] for record in context_records],
        },
        "quantitativeAdministration": {"actions": list(actions)},
    }
    signature = signer.sign(
        canonical_json_bytes(
            {
                "domain": "ksi.external-authority-provider-snapshot.v1",
                "snapshot": unsigned,
            }
        )
    )
    _write(
        tmp_path / "authority-snapshot.json",
        {**unsigned, "signature": base64.b64encode(signature).decode("ascii")},
    )
    config = tmp_path / "external-authority-provider.json"
    _write(
        config,
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
    return config


def _replace_signed_snapshot(
    tmp_path: Path,
    signer: Ed25519PrivateKey,
    changes: dict[str, object],
) -> str:
    snapshot_path = tmp_path / "authority-snapshot.json"
    current = json.loads(snapshot_path.read_text(encoding="utf-8"))
    unsigned = {key: value for key, value in current.items() if key != "signature"} | changes
    signed = canonical_json_bytes(
        {
            "domain": "ksi.external-authority-provider-snapshot.v1",
            "snapshot": unsigned,
        }
    )
    _write(
        snapshot_path,
        {**unsigned, "signature": base64.b64encode(signer.sign(signed)).decode("ascii")},
    )
    return "sha256:" + hashlib.sha256(signed).hexdigest()


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


def _assert_reconciliation_failure_blocks_guarded_consumers(
    *,
    provider: Any,
    coordinator: ExternalAuthorityCurrentnessCoordinator,
    authority: PolicyAuthorityRecord,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
    trigger: Callable[[], object],
) -> list[Exception]:
    """A failed reconcile must block before a guarded consumer can see the old generation."""
    assert authority.digest is not None
    reconcile_failed = threading.Event()
    release_block = threading.Event()
    release_block_locked = threading.Event()
    block_locked_entered = threading.Event()
    guarded_entered = threading.Event()
    observed: list[PolicyAuthorityRecord | None] = []
    trigger_errors: list[Exception] = []
    guarded_errors: list[Exception] = []
    original_block = provider._block  # noqa: SLF001 - deterministic failure boundary.
    original_block_locked = provider._block_locked  # noqa: SLF001 - deterministic failure boundary.

    def paused_block(*args: object, **kwargs: object) -> None:
        assert release_block.wait(timeout=1)
        original_block(*args, **kwargs)

    def paused_block_locked(*args: object, **kwargs: object) -> None:
        block_locked_entered.set()
        assert release_block_locked.wait(timeout=1)
        original_block_locked(*args, **kwargs)

    def failing_reconcile(*_args: object, **_kwargs: object) -> object:
        reconcile_failed.set()
        raise RuntimeError("injected reconciliation failure")

    monkeypatch.setattr(provider, "_block", paused_block)
    monkeypatch.setattr(provider, "_block_locked", paused_block_locked)
    monkeypatch.setattr(provider, "_reconcile_candidate", failing_reconcile)

    def reconcile() -> None:
        try:
            trigger()
        except Exception as exc:  # pragma: no cover - asserted by callers.
            trigger_errors.append(exc)

    def guarded_consumer() -> None:
        try:
            with coordinator.guarded_read():
                observed.append(
                    provider.participants.policy_authority_port.resolve(authority.digest, now)
                )
                guarded_entered.set()
        except Exception as exc:  # pragma: no cover - asserted below.
            guarded_errors.append(exc)

    reconcile_thread = threading.Thread(target=reconcile)
    guarded_thread = threading.Thread(target=guarded_consumer)
    reconcile_thread.start()
    assert reconcile_failed.wait(timeout=1)
    guarded_thread.start()
    try:
        assert block_locked_entered.wait(timeout=1)
        assert not guarded_entered.wait(timeout=0.2)
    finally:
        release_block.set()
        release_block_locked.set()
        reconcile_thread.join(timeout=1)
        guarded_thread.join(timeout=1)

    assert not reconcile_thread.is_alive()
    assert not guarded_thread.is_alive()
    assert guarded_errors == []
    assert observed == [None]
    assert provider.status()["status"] == "BLOCKED"
    return trigger_errors


def test_reload_reconciliation_failure_blocks_before_guarded_consumers_see_old_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, authority = _administrable_policy()
    fixture_signers: list[Ed25519PrivateKey] = []
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(
            tmp_path,
            policy_records=(authority.event_payload(),),
            fixture_signers=fixture_signers,
        ),
        clock=lambda: NOW + timedelta(minutes=1),
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    provider.bind_receipt_journal(
        DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    )
    provider.attach_app(_empty_app(provider, coordinator))
    first_digest = provider.status()["snapshotDigest"]
    assert isinstance(first_digest, str)
    _replace_signed_snapshot(
        tmp_path,
        fixture_signers[0],
        {
            "sequence": 2,
            "previousSnapshotDigest": first_digest,
            "issuedAt": "2026-09-11T00:01:00Z",
        },
    )

    errors = _assert_reconciliation_failure_blocks_guarded_consumers(
        provider=provider,
        coordinator=coordinator,
        authority=authority,
        now=NOW + timedelta(minutes=2),
        monkeypatch=monkeypatch,
        trigger=lambda: provider.reload_and_reconcile(now=NOW + timedelta(minutes=2)),
    )

    assert errors == []


def test_repeated_attach_failure_blocks_before_guarded_consumers_see_old_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _policy, authority = _administrable_policy()
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path, policy_records=(authority.event_payload(),)),
        clock=lambda: NOW + timedelta(minutes=1),
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    app = _empty_app(provider, coordinator)
    provider.bind_receipt_journal(
        DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    )
    provider.attach_app(app)

    errors = _assert_reconciliation_failure_blocks_guarded_consumers(
        provider=provider,
        coordinator=coordinator,
        authority=authority,
        now=NOW + timedelta(minutes=1),
        monkeypatch=monkeypatch,
        trigger=lambda: provider.attach_app(app),
    )

    assert len(errors) == 1
    assert isinstance(errors[0], provider_module.ExternalAuthorityProviderError)


def _administrable_policy() -> tuple[ExternalValidationPolicyV1, PolicyAuthorityRecord]:
    subject = SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="work-a",
        submission_id="submission-a",
        revision=1,
        submission_digest="sha256:" + "9" * 64,
        manifest_digest="sha256:" + "a" * 64,
    )
    envelope = ResourceEnvelopeV1(
        max_input_bytes=1,
        max_streamed_bytes=1,
        max_tiff_directories=1,
        max_tiff_entries=1,
        max_pixels=1,
        max_bands=1,
        max_blocks=1,
        max_decompressed_bytes=1,
        max_sample_bytes=1,
        max_geometry_vertices=1,
        max_cpu_seconds=1.0,
        max_memory_bytes=1,
        max_workspace_bytes=1,
        max_output_bytes=1,
        max_tenant_concurrency=1,
        max_queue_depth=1,
        max_deadline_seconds=1.0,
        lease_duration_seconds=1.0,
        max_retry_attempts=1,
    ).sealed()
    template = ExternalValidationPolicyV1(
        policy_id="policy-a",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest="sha256:" + "b" * 64,
        grammar_digest="sha256:" + "c" * 64,
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest="sha256:" + "d" * 64,
        inspection_rule_ids=(),
        evidence_rule_ids=(),
        compatibility_mapping_digests=(),
        synthetic_test_only=False,
    ).sealed()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(subject,),
        permitted_uses=("INSPECTION",),
        authorized_actor_ids=("policy-admin",),
        active_from=NOW,
        active_until=NOW + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    assert authority.digest is not None
    return (
        template.model_copy(
            update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
        ).sealed(),
        authority,
    )


def _provider_policy_admission(
    *,
    subjects: tuple[SealedExternalSubjectV1, SealedExternalSubjectV1],
    envelope: ResourceEnvelopeV1,
    now: datetime,
) -> tuple[ExternalValidationPolicyV1, PolicyAuthorityRecord, dict[str, object]]:
    """Build a non-synthetic signed action; admission itself remains provider-driven."""
    template = ExternalValidationPolicyV1(
        policy_id="external-geotiff-v1",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=production_flow._digest("inspector-build-1"),
        grammar_digest=production_flow._digest("grammar-1"),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=production_flow._digest("unbound-policy-authority"),
        inspection_rule_ids=("EXTERNAL_GEOTIFF_MEASURED_V1",),
        evidence_rule_ids=("CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",),
        compatibility_mapping_digests=(CompatibilityRuleDescriptorV1().canonical_digest(),),
        synthetic_test_only=False,
    ).sealed()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=subjects,
        permitted_uses=("INSPECTION", "EVIDENCE", "RELATIVE_VOLUME"),
        authorized_actor_ids=("policy-admin",),
        active_from=now - timedelta(hours=1),
        active_until=now + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    assert authority.digest is not None
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    return (
        policy,
        authority,
        {
            "actionId": "provider-admit-policy",
            "kind": "ADMIT_POLICY",
            "effectiveAt": now.isoformat().replace("+00:00", "Z"),
            "actorId": "policy-admin",
            "policy": policy.model_dump(by_alias=True, mode="json"),
        },
    )


def test_loader_builds_a_signed_empty_provider_without_creating_receipts(tmp_path: Path) -> None:
    # Removing the new loader would make this test fail at its real API boundary.
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    receipt_path = tmp_path / "external-authority-provider-receipts.jsonl"

    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path), clock=lambda: NOW + timedelta(minutes=1)
    )

    assert provider.organization_id == "org-a"
    status = provider.status()
    assert status == {
        "status": "CONFIG_VALIDATED",
        "organizationId": "org-a",
        "snapshotSequence": 1,
        "snapshotDigest": status["snapshotDigest"],
        "businessEligible": False,
    }
    assert isinstance(status["snapshotDigest"], str)
    assert status["snapshotDigest"].startswith("sha256:")
    assert provider.participants.catalog_administration_actor_id == "catalog-admin"
    assert provider.participants.queue_policy.max_attempts == 3
    assert not receipt_path.exists()


def test_binding_requires_the_fixed_receipt_journal_filename(tmp_path: Path) -> None:
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path), clock=lambda: NOW
    )
    wrong_journal = DurableJournal(tmp_path / "wrong-receipts.jsonl")

    try:
        with pytest.raises(ValueError, match="fixed absolute receipt path name"):
            provider.bind_receipt_journal(wrong_journal)
    finally:
        wrong_journal.close()


def test_participant_factories_are_identity_stable_for_one_core_coordinator(
    tmp_path: Path,
) -> None:
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path), clock=lambda: NOW
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    other = ExternalAuthorityCurrentnessCoordinator()

    assert provider.participants.build_catalog_authority_currentness(
        coordinator
    ) is provider.participants.build_catalog_authority_currentness(coordinator)
    assert provider.participants.build_evidence_context_authority(
        coordinator
    ) is provider.participants.build_evidence_context_authority(coordinator)
    assert provider.participants.build_policy_authority_currentness(
        coordinator
    ) is provider.participants.build_policy_authority_currentness(coordinator)
    with pytest.raises(ValueError, match="cannot cross Core coordinators"):
        provider.participants.build_evidence_context_authority(other)
    with pytest.raises(ValueError, match="cannot cross Core coordinators"):
        provider.participants.build_policy_authority_currentness(other)


def test_loader_rejects_a_tampered_snapshot_signature(tmp_path: Path) -> None:
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    config_path = _provider_config(tmp_path)
    snapshot_path = tmp_path / "authority-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["validUntil"] = "2026-09-11T02:00:00Z"
    _write(snapshot_path, snapshot)

    with pytest.raises(provider_module.ExternalAuthorityProviderError):
        provider_module.load_external_authority_provider(config_path, clock=lambda: NOW)


def test_loader_rejects_synthetic_evidence_context_even_when_the_bundle_is_signed(
    tmp_path: Path,
) -> None:
    subject = SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="work-a",
        submission_id="submission-a",
        revision=1,
        submission_digest="sha256:" + "1" * 64,
        manifest_digest="sha256:" + "2" * 64,
    )
    context = ExternalEvidenceMeasurementContextV1(
        context_id="context-synthetic",
        subject=subject,
        evidence_manifest_digest="sha256:" + "3" * 64,
        evidence_observed_sha256="sha256:" + "4" * 64,
        evidence_observed_size_bytes=64,
        target_dsm_artifact_id="dsm-a",
        target_dsm_observed_sha256="sha256:" + "5" * 64,
        policy_digest="sha256:" + "6" * 64,
        measurement_execution_manifest_digest="sha256:" + "7" * 64,
        rule_id="CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",
        csv_horizontal_crs="EPSG:5186",
        csv_vertical_reference_digest="sha256:" + "8" * 64,
        minimum_checkpoint_count=1,
        maximum_checkpoint_count=2,
        maximum_rmse_m=1.0,
        maximum_abs_mean_error_m=1.0,
        maximum_abs_error_m=1.0,
        independent_attestation=None,
        authorized_actor_ids=("context-admin",),
        active_from=NOW,
        active_until=NOW + timedelta(hours=1),
        synthetic_test_only=True,
    ).sealed()
    provider_module = importlib.import_module("ksi_core.external_authority_provider")

    with pytest.raises(provider_module.ExternalAuthorityProviderError):
        provider_module.load_external_authority_provider(
            _provider_config(
                tmp_path,
                context_records=(context.model_dump(by_alias=True, mode="json"),),
            ),
            clock=lambda: NOW,
        )


def test_loader_rejects_an_ambiguous_authority_key_id(tmp_path: Path) -> None:
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    config_path = _provider_config(tmp_path)
    keys_path = tmp_path / "authority-keys.json"
    registry = json.loads(keys_path.read_text(encoding="utf-8"))
    registry["keys"].append(dict(registry["keys"][0]))
    _write(keys_path, registry)

    with pytest.raises(provider_module.ExternalAuthorityProviderError):
        provider_module.load_external_authority_provider(config_path, clock=lambda: NOW)


def test_status_fails_closed_when_the_current_snapshot_expires(tmp_path: Path) -> None:
    clock_now = [NOW + timedelta(minutes=1)]
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path), clock=lambda: clock_now[0]
    )

    assert provider.status()["status"] == "CONFIG_VALIDATED"
    clock_now[0] = NOW + timedelta(hours=1)

    assert provider.status() == {
        "status": "BLOCKED",
        "organizationId": "org-a",
        "snapshotSequence": None,
        "snapshotDigest": None,
        "businessEligible": False,
    }


def test_disk_key_revocation_requires_explicit_reload_and_never_mutates_status(
    tmp_path: Path,
) -> None:
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path), clock=lambda: NOW + timedelta(minutes=1)
    )
    registry_path = tmp_path / "authority-keys.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["keys"][0]["status"] = "REVOKED"
    _write(registry_path, registry)

    assert provider.status()["status"] == "CONFIG_VALIDATED"
    assert provider.reload_and_reconcile(now=NOW + timedelta(minutes=1)) == {
        "status": "BLOCKED",
        "sequence": None,
        "snapshotDigest": None,
    }
    assert provider.status()["status"] == "BLOCKED"


def test_attach_fails_closed_when_a_reconciliation_store_raises(tmp_path: Path) -> None:
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path), clock=lambda: NOW + timedelta(minutes=1)
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()

    class _FailingInspections:
        def __init__(self) -> None:
            self.coordinator = coordinator

        def reconcile_sealed(self, now: datetime) -> int:
            del now
            raise RuntimeError("inspection projection failed")

    app = _empty_app(provider, coordinator)
    app.state.external_artifact_inspection_store = _FailingInspections()
    provider.bind_receipt_journal(
        DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    )

    with pytest.raises(
        provider_module.ExternalAuthorityProviderError, match="reconciliation failed"
    ):
        provider.attach_app(app)

    assert provider.status()["status"] == "BLOCKED"


def test_attach_blocks_and_clears_its_app_identity_when_the_clock_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path), clock=lambda: NOW + timedelta(minutes=1)
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    app = _empty_app(provider, coordinator)
    provider.bind_receipt_journal(
        DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    )

    def failing_clock() -> datetime:
        raise RuntimeError("injected clock failure")

    monkeypatch.setattr(provider, "_clock", failing_clock)
    with pytest.raises(
        provider_module.ExternalAuthorityProviderError,
        match="reconciliation failed",
    ):
        provider.attach_app(app)

    assert provider._app is None  # noqa: SLF001 - attachment failure must not retain identity.
    assert provider._blocked_reason == "RuntimeError"  # noqa: SLF001 - fail-closed publication.


def test_catalog_authority_record_round_trips_only_its_exact_sealed_event_payload() -> None:
    record = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id="org-a",
        catalog_body_digest="sha256:" + "a" * 64,
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=NOW,
        active_until=NOW + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()

    restored = ExternalQuantitativeCatalogAuthorityRecord.from_event_payload(record.event_payload())

    assert restored == record


def test_catalog_port_resolves_only_the_exact_signed_current_catalog_record(tmp_path: Path) -> None:
    record = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id="org-a",
        catalog_body_digest="sha256:" + "b" * 64,
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=NOW,
        active_until=NOW + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    assert record.digest is not None
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path, catalog_records=(record.event_payload(),)),
        clock=lambda: NOW + timedelta(minutes=1),
    )

    assert provider.participants.catalog_authority_port.resolve(record.digest, NOW) == record
    assert provider.participants.catalog_authority_port.resolve("sha256:" + "c" * 64, NOW) is None


def test_bind_then_attach_records_the_verified_initial_snapshot_before_configuring(
    tmp_path: Path,
) -> None:
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path), clock=lambda: NOW + timedelta(minutes=1)
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    app = type("_App", (), {})()
    app.state = type("_State", (), {})()
    app.state.external_authority_currentness = coordinator
    app.state.external_validation_policy_registry = type(
        "_Registry", (), {"coordinator": coordinator}
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
    receipts = DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")

    provider.bind_receipt_journal(receipts)
    provider.attach_app(app)

    assert provider.status()["status"] == "PROVIDER_CONFIGURED"
    assert app.state.external_authority_provider is provider
    assert len(receipts.replay()) == 1


def test_policy_port_resolves_only_exact_signed_current_authority_records(tmp_path: Path) -> None:
    subject = SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="work-a",
        submission_id="submission-a",
        revision=1,
        submission_digest="sha256:" + "d" * 64,
        manifest_digest="sha256:" + "e" * 64,
    )
    authority = PolicyAuthorityRecord(
        policy_id="policy-a",
        policy_version=1,
        authorized_policy_body_digest="sha256:" + "f" * 64,
        permitted_subjects=(subject,),
        permitted_uses=("INSPECTION",),
        authorized_actor_ids=("policy-admin",),
        active_from=NOW,
        active_until=NOW + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    assert authority.digest is not None
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path, policy_records=(authority.event_payload(),)),
        clock=lambda: NOW + timedelta(minutes=1),
    )

    assert provider.participants.policy_authority_port is not None
    assert provider.participants.policy_authority_port.resolve(authority.digest, NOW) is None
    assert (
        provider.participants.policy_authority_port.resolve_historical(authority.digest, NOW)
        == authority
    )


def test_evidence_context_port_resolves_a_single_exact_signed_context(tmp_path: Path) -> None:
    subject = SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="work-a",
        submission_id="submission-a",
        revision=1,
        submission_digest="sha256:" + "1" * 64,
        manifest_digest="sha256:" + "2" * 64,
    )
    context = ExternalEvidenceMeasurementContextV1(
        context_id="context-a",
        subject=subject,
        evidence_manifest_digest="sha256:" + "3" * 64,
        evidence_observed_sha256="sha256:" + "4" * 64,
        evidence_observed_size_bytes=64,
        target_dsm_artifact_id="dsm-a",
        target_dsm_observed_sha256="sha256:" + "5" * 64,
        policy_digest="sha256:" + "6" * 64,
        measurement_execution_manifest_digest="sha256:" + "7" * 64,
        rule_id="CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",
        csv_horizontal_crs="EPSG:5186",
        csv_vertical_reference_digest="sha256:" + "8" * 64,
        minimum_checkpoint_count=1,
        maximum_checkpoint_count=2,
        maximum_rmse_m=1.0,
        maximum_abs_mean_error_m=1.0,
        maximum_abs_error_m=1.0,
        independent_attestation=None,
        authorized_actor_ids=("context-admin",),
        active_from=NOW,
        active_until=NOW + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    assert context.context_digest is not None
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(
            tmp_path,
            context_records=(context.model_dump(by_alias=True, mode="json"),),
        ),
        clock=lambda: NOW + timedelta(minutes=1),
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    port = provider.participants.build_evidence_context_authority(coordinator)
    provider.bind_receipt_journal(
        DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    )
    provider.attach_app(_empty_app(provider, coordinator))

    assert (
        port.resolve_for_validation(
            subject=subject,
            evidence_manifest_digest=context.evidence_manifest_digest,
            target_dsm_artifact_id=context.target_dsm_artifact_id,
            target_dsm_observed_sha256=context.target_dsm_observed_sha256,
            policy_digest=context.policy_digest,
            now=NOW,
        )
        == context
    )


def test_signed_snapshot_rollover_retains_sealed_context_for_historical_validation(
    tmp_path: Path,
) -> None:
    subject = SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="work-a",
        submission_id="submission-a",
        revision=1,
        submission_digest="sha256:" + "1" * 64,
        manifest_digest="sha256:" + "2" * 64,
    )
    context = ExternalEvidenceMeasurementContextV1(
        context_id="context-a",
        subject=subject,
        evidence_manifest_digest="sha256:" + "3" * 64,
        evidence_observed_sha256="sha256:" + "4" * 64,
        evidence_observed_size_bytes=64,
        target_dsm_artifact_id="dsm-a",
        target_dsm_observed_sha256="sha256:" + "5" * 64,
        policy_digest="sha256:" + "6" * 64,
        measurement_execution_manifest_digest="sha256:" + "7" * 64,
        rule_id="CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",
        csv_horizontal_crs="EPSG:5186",
        csv_vertical_reference_digest="sha256:" + "8" * 64,
        minimum_checkpoint_count=1,
        maximum_checkpoint_count=2,
        maximum_rmse_m=1.0,
        maximum_abs_mean_error_m=1.0,
        maximum_abs_error_m=1.0,
        independent_attestation=None,
        authorized_actor_ids=("context-admin",),
        active_from=NOW,
        active_until=NOW + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    assert context.context_digest is not None
    fixture_signers: list[Ed25519PrivateKey] = []
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(
            tmp_path,
            context_records=(context.model_dump(by_alias=True, mode="json"),),
            fixture_signers=fixture_signers,
        ),
        clock=lambda: NOW + timedelta(minutes=2),
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    port = provider.participants.build_evidence_context_authority(coordinator)
    receipts = DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")

    provider.bind_receipt_journal(receipts)
    provider.attach_app(_empty_app(provider, coordinator))
    first_digest = provider.status()["snapshotDigest"]
    assert isinstance(first_digest, str)
    _replace_signed_snapshot(
        tmp_path,
        fixture_signers[0],
        {
            "sequence": 2,
            "previousSnapshotDigest": first_digest,
            "issuedAt": "2026-09-11T00:01:00Z",
            "catalogAuthorities": {"records": [], "currentDigests": []},
            "policyAuthorities": {"records": [], "currentDigests": []},
            "evidenceContexts": {"records": [], "currentDigests": []},
        },
    )

    assert provider.reload_and_reconcile(now=NOW + timedelta(minutes=2))["status"] == (
        "PROVIDER_CONFIGURED"
    )
    assert (
        port.resolve_historical_for_validation(
            context_digest=context.context_digest,
            subject=subject,
            evidence_manifest_digest=context.evidence_manifest_digest,
            target_dsm_artifact_id=context.target_dsm_artifact_id,
            target_dsm_observed_sha256=context.target_dsm_observed_sha256,
            policy_digest=context.policy_digest,
            issued_at=NOW + timedelta(minutes=1),
        )
        == context
    )


def test_reload_validates_a_replacement_snapshot_at_its_explicit_reconciliation_time(
    tmp_path: Path,
) -> None:
    fixture_signers: list[Ed25519PrivateKey] = []
    clock_now = [NOW + timedelta(minutes=1)]
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path, fixture_signers=fixture_signers),
        clock=lambda: clock_now[0],
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    provider.bind_receipt_journal(
        DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    )
    provider.attach_app(_empty_app(provider, coordinator))
    prior_digest = provider.status()["snapshotDigest"]
    assert isinstance(prior_digest, str)
    _replace_signed_snapshot(
        tmp_path,
        fixture_signers[0],
        {
            "sequence": 2,
            "previousSnapshotDigest": prior_digest,
            "issuedAt": "2026-09-11T00:02:00Z",
        },
    )

    clock_now[0] = NOW + timedelta(minutes=2)
    result = provider.reload_and_reconcile(now=NOW + timedelta(minutes=2))
    assert result == {
        "status": "PROVIDER_CONFIGURED",
        "sequence": 2,
        "snapshotDigest": result["snapshotDigest"],
    }


def test_concurrent_reload_serializes_protected_reads_before_candidate_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later reload cannot read a newer chain member before its predecessor publishes."""
    fixture_signers: list[Ed25519PrivateKey] = []
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    clock_now = [NOW + timedelta(minutes=1)]
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path, fixture_signers=fixture_signers),
        clock=lambda: clock_now[0],
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    provider.bind_receipt_journal(
        DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    )
    provider.attach_app(_empty_app(provider, coordinator))
    first_digest = provider.status()["snapshotDigest"]
    assert isinstance(first_digest, str)
    first_candidate_digest = _replace_signed_snapshot(
        tmp_path,
        fixture_signers[0],
        {
            "sequence": 2,
            "previousSnapshotDigest": first_digest,
            "issuedAt": "2026-09-11T00:01:00Z",
        },
    )
    original_load = provider_module._load
    first_loaded = threading.Event()
    release_first = threading.Event()
    second_read = threading.Event()
    calls = 0

    def delayed_load(*args: object, **kwargs: object) -> Any:
        nonlocal calls
        result = original_load(*args, **kwargs)
        calls += 1
        if calls == 1:
            first_loaded.set()
            assert release_first.wait(timeout=1)
        elif calls == 2:
            second_read.set()
        return result

    monkeypatch.setattr(provider_module, "_load", delayed_load)
    first_result: list[dict[str, object]] = []
    first = threading.Thread(
        target=lambda: first_result.append(
            provider.reload_and_reconcile(now=NOW + timedelta(minutes=2))
        )
    )
    first.start()
    assert first_loaded.wait(timeout=1)
    latest_digest = _replace_signed_snapshot(
        tmp_path,
        fixture_signers[0],
        {
            "sequence": 3,
            "previousSnapshotDigest": first_candidate_digest,
            "issuedAt": "2026-09-11T00:02:00Z",
        },
    )

    latest_result: list[dict[str, object]] = []
    latest = threading.Thread(
        target=lambda: latest_result.append(
            provider.reload_and_reconcile(now=NOW + timedelta(minutes=3))
        )
    )
    latest.start()
    clock_now[0] = NOW + timedelta(minutes=3)
    try:
        assert not second_read.wait(timeout=0.2)
    finally:
        release_first.set()
        first.join(timeout=1)
        latest.join(timeout=1)

    assert not first.is_alive()
    assert not latest.is_alive()
    assert first_result == [
        {
            "status": "PROVIDER_CONFIGURED",
            "sequence": 2,
            "snapshotDigest": first_candidate_digest,
        }
    ]
    assert latest_result == [
        {
            "status": "PROVIDER_CONFIGURED",
            "sequence": 3,
            "snapshotDigest": latest_digest,
        }
    ]
    assert provider.status()["snapshotDigest"] == latest_digest


def test_reload_serializes_a_second_protected_read_until_first_reconciliation_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newer reload cannot read mutable signed input during an older reconcile."""
    fixture_signers: list[Ed25519PrivateKey] = []
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    clock_now = [NOW + timedelta(minutes=1)]
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path, fixture_signers=fixture_signers),
        clock=lambda: clock_now[0],
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    provider.bind_receipt_journal(
        DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    )
    provider.attach_app(_empty_app(provider, coordinator))
    initial_digest = provider.status()["snapshotDigest"]
    assert isinstance(initial_digest, str)
    first_digest = _replace_signed_snapshot(
        tmp_path,
        fixture_signers[0],
        {
            "sequence": 2,
            "previousSnapshotDigest": initial_digest,
            "issuedAt": "2026-09-11T00:01:00Z",
        },
    )

    reconcile_entered = threading.Event()
    release_reconcile = threading.Event()
    second_protected_read = threading.Event()
    original_reconcile = provider._reconcile_candidate  # noqa: SLF001 - race boundary.
    original_load = provider_module._load
    reads = 0

    def paused_reconcile(candidate: object, *, now: datetime) -> Any:
        reconcile_entered.set()
        assert release_reconcile.wait(timeout=1)
        return original_reconcile(candidate, now=now)

    def observed_load(*args: object, **kwargs: object) -> Any:
        nonlocal reads
        reads += 1
        if reads == 2:
            second_protected_read.set()
        return original_load(*args, **kwargs)

    monkeypatch.setattr(provider, "_reconcile_candidate", paused_reconcile)
    monkeypatch.setattr(provider_module, "_load", observed_load)
    first = threading.Thread(
        target=lambda: provider.reload_and_reconcile(now=NOW + timedelta(minutes=2))
    )
    first.start()
    assert reconcile_entered.wait(timeout=1)
    latest_digest = _replace_signed_snapshot(
        tmp_path,
        fixture_signers[0],
        {
            "sequence": 3,
            "previousSnapshotDigest": first_digest,
            "issuedAt": "2026-09-11T00:02:00Z",
        },
    )
    clock_now[0] = NOW + timedelta(minutes=3)
    second_result: list[dict[str, object]] = []
    second = threading.Thread(
        target=lambda: second_result.append(
            provider.reload_and_reconcile(now=NOW + timedelta(minutes=3))
        )
    )
    second.start()
    try:
        assert not second_protected_read.wait(timeout=0.2)
    finally:
        release_reconcile.set()
        first.join(timeout=1)
        second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert second_result == [
        {
            "status": "PROVIDER_CONFIGURED",
            "sequence": 3,
            "snapshotDigest": latest_digest,
        }
    ]
    assert provider.status()["snapshotDigest"] == latest_digest


def test_failed_graph_attachment_does_not_claim_provider_identity(
    tmp_path: Path,
) -> None:
    """A failed graph check leaves a verified provider attachable to its real app."""
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path), clock=lambda: NOW + timedelta(minutes=1)
    )
    provider.bind_receipt_journal(
        DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    )
    invalid_app = type("_InvalidApp", (), {})()

    with pytest.raises(ValueError, match="assembled FastAPI application"):
        provider.attach_app(invalid_app)

    assert provider.status()["status"] == "CONFIG_VALIDATED"
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    valid_app = _empty_app(provider, coordinator)
    provider.attach_app(valid_app)

    assert provider.status()["status"] == "PROVIDER_CONFIGURED"
    assert valid_app.state.external_authority_provider is provider


def test_reconciliation_candidate_is_invisible_to_other_threads_until_receipt_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The thread-local reconciliation permit cannot become a cross-thread live port."""
    policy, authority = _administrable_policy()
    assert authority.digest is not None
    replacement_authority = replace(
        authority, policy_id="policy-replacement", digest=None
    ).sealed()
    assert replacement_authority.digest is not None
    fixture_signers: list[Ed25519PrivateKey] = []
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(
            tmp_path,
            policy_records=(authority.event_payload(),),
            fixture_signers=fixture_signers,
        ),
        clock=lambda: NOW + timedelta(minutes=1),
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    provider.bind_receipt_journal(
        DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    )
    provider.attach_app(_empty_app(provider, coordinator))
    first_digest = provider.status()["snapshotDigest"]
    assert isinstance(first_digest, str)
    _replace_signed_snapshot(
        tmp_path,
        fixture_signers[0],
        {
            "sequence": 2,
            "previousSnapshotDigest": first_digest,
            "issuedAt": "2026-09-11T00:01:00Z",
            "policyAuthorities": {
                "records": [replacement_authority.event_payload()],
                "currentDigests": [replacement_authority.digest],
            },
        },
    )
    entered = threading.Event()
    release = threading.Event()
    original_apply = provider._apply_policy_actions  # noqa: SLF001 - deterministic barrier.

    def delayed_apply(registry: object, candidate: object) -> None:
        entered.set()
        assert release.wait(timeout=1)
        original_apply(registry, candidate)

    monkeypatch.setattr(provider, "_apply_policy_actions", delayed_apply)
    reload_thread = threading.Thread(
        target=lambda: provider.reload_and_reconcile(now=NOW + timedelta(minutes=2))
    )
    reload_thread.start()
    assert entered.wait(timeout=1)
    assert (
        provider.participants.policy_authority_port.resolve(
            replacement_authority.digest, NOW + timedelta(minutes=2)
        )
        is None
    )
    release.set()
    reload_thread.join(timeout=1)

    assert not reload_thread.is_alive()
    assert provider.participants.policy_authority_port.resolve(
        replacement_authority.digest, NOW + timedelta(minutes=2)
    ) == replacement_authority


def test_blocked_provider_recovers_a_signed_policy_admission_without_exposing_it_early(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the reconciliation thread may use a corrective staged authority."""
    policy, authority = _administrable_policy()
    assert policy.policy_digest is not None
    assert authority.digest is not None
    fixture_signers: list[Ed25519PrivateKey] = []
    clock_now = [NOW + timedelta(minutes=1)]
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(tmp_path, fixture_signers=fixture_signers),
        clock=lambda: clock_now[0],
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policies.jsonl"),
        authority_port=provider.participants.policy_authority_port,
        authority_currentness_port=provider.participants.build_policy_authority_currentness(
            coordinator
        ),
        clock=lambda: clock_now[0],
        coordinator=coordinator,
    )
    app = _empty_app(provider, coordinator)
    app.state.external_validation_policy_registry = registry
    receipts = DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    provider.bind_receipt_journal(receipts)
    provider.attach_app(app)
    initial_digest = provider.status()["snapshotDigest"]
    assert isinstance(initial_digest, str)
    valid_changes = {
        "sequence": 2,
        "previousSnapshotDigest": initial_digest,
        "issuedAt": "2026-09-11T00:01:00Z",
        "policyAuthorities": {
            "records": [authority.event_payload()],
            "currentDigests": [authority.digest],
        },
        "quantitativeAdministration": {
            "actions": [
                {
                    "actionId": "recover-admit-policy",
                    "kind": "ADMIT_POLICY",
                    "effectiveAt": "2026-09-11T00:02:00Z",
                    "actorId": "policy-admin",
                    "policy": policy.model_dump(by_alias=True, mode="json"),
                }
            ]
        },
    }
    valid_digest = _replace_signed_snapshot(tmp_path, fixture_signers[0], valid_changes)
    snapshot_path = tmp_path / "authority-snapshot.json"
    malformed = json.loads(snapshot_path.read_text(encoding="utf-8"))
    malformed["signature"] = "not-a-valid-ed25519-signature"
    _write(snapshot_path, malformed)

    try:
        clock_now[0] = NOW + timedelta(minutes=2)
        assert provider.reload_and_reconcile(now=clock_now[0])["status"] == "BLOCKED"
        assert (
            provider.participants.policy_authority_port.resolve(
                authority.digest, clock_now[0]
            )
            is None
        )
        assert registry._journal.replay() == []  # noqa: SLF001 - no malformed action persists.
        assert len(receipts.replay()) == 1

        assert _replace_signed_snapshot(tmp_path, fixture_signers[0], valid_changes) == valid_digest
        entered = threading.Event()
        release = threading.Event()
        original_apply = provider._apply_policy_actions  # noqa: SLF001 - publication barrier.

        def delayed_apply(registry: object, candidate: object) -> None:
            entered.set()
            assert release.wait(timeout=1)
            original_apply(registry, candidate)

        monkeypatch.setattr(provider, "_apply_policy_actions", delayed_apply)
        recovery = threading.Thread(
            target=lambda: provider.reload_and_reconcile(now=clock_now[0])
        )
        recovery.start()
        assert entered.wait(timeout=1)
        assert (
            provider.participants.policy_authority_port.resolve(
                authority.digest, clock_now[0]
            )
            is None
        )
        release.set()
        recovery.join(timeout=1)

        assert not recovery.is_alive()
        assert provider.status()["snapshotDigest"] == valid_digest
        assert registry.resolve(policy.policy_digest).status is PolicySelectionStatus.ACTIVE
        assert len(receipts.replay()) == 2
    finally:
        receipts.close()
        registry._journal.close()  # noqa: SLF001 - close owned journal fixture.


def test_attach_reconciles_a_signed_policy_admission_through_the_actual_registry(
    tmp_path: Path,
) -> None:
    subject = SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="work-a",
        submission_id="submission-a",
        revision=1,
        submission_digest="sha256:" + "9" * 64,
        manifest_digest="sha256:" + "a" * 64,
    )
    envelope = ResourceEnvelopeV1(
        max_input_bytes=1,
        max_streamed_bytes=1,
        max_tiff_directories=1,
        max_tiff_entries=1,
        max_pixels=1,
        max_bands=1,
        max_blocks=1,
        max_decompressed_bytes=1,
        max_sample_bytes=1,
        max_geometry_vertices=1,
        max_cpu_seconds=1.0,
        max_memory_bytes=1,
        max_workspace_bytes=1,
        max_output_bytes=1,
        max_tenant_concurrency=1,
        max_queue_depth=1,
        max_deadline_seconds=1.0,
        lease_duration_seconds=1.0,
        max_retry_attempts=1,
    ).sealed()
    template = ExternalValidationPolicyV1(
        policy_id="policy-a",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest="sha256:" + "b" * 64,
        grammar_digest="sha256:" + "c" * 64,
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest="sha256:" + "d" * 64,
        inspection_rule_ids=(),
        evidence_rule_ids=(),
        compatibility_mapping_digests=(),
        synthetic_test_only=False,
    ).sealed()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(subject,),
        permitted_uses=("INSPECTION",),
        authorized_actor_ids=("policy-admin",),
        active_from=NOW,
        active_until=NOW + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    assert authority.digest is not None
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(
            tmp_path,
            policy_records=(authority.event_payload(),),
            actions=(
                {
                    "actionId": "action-policy-a",
                    "kind": "ADMIT_POLICY",
                    "effectiveAt": "2026-09-11T00:01:00Z",
                    "actorId": "policy-admin",
                    "policy": policy.model_dump(by_alias=True, mode="json"),
                },
            ),
        ),
        clock=lambda: NOW + timedelta(minutes=1),
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policies.jsonl"),
        authority_port=provider.participants.policy_authority_port,
        authority_currentness_port=provider.participants.build_policy_authority_currentness(
            coordinator
        ),
        clock=lambda: NOW + timedelta(minutes=1),
        coordinator=coordinator,
    )
    app = type("_App", (), {})()
    app.state = type("_State", (), {})()
    app.state.external_authority_currentness = coordinator
    app.state.external_validation_policy_registry = registry
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

    provider.bind_receipt_journal(
        DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    )
    provider.attach_app(app)

    assert policy.policy_digest is not None
    assert registry.resolve(policy.policy_digest).status is PolicySelectionStatus.ACTIVE
    assert provider.status()["status"] == "PROVIDER_CONFIGURED"


def test_attach_reconciles_a_signed_mapping_admission_through_the_actual_catalog(
    tmp_path: Path,
) -> None:
    """Provider actions admit only through the assembled production participants."""
    now = datetime.now(UTC).replace(microsecond=0)
    source_policy_authority = production_flow._RetainedPolicyAuthority()
    context_authority = production_flow._RetainedEvidenceContextAuthority(now)
    workflow, catalog_record, envelope, _catalog_authority = production_flow._workflow(
        tmp_path,
        now=now,
        policy_authority=source_policy_authority,
        context_authority=context_authority,
    )
    fixture_signers: list[Ed25519PrivateKey] = []
    clock_now = [now]
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    config_path = _provider_config(
        tmp_path,
        catalog_records=(catalog_record.event_payload(),),
        fixture_signers=fixture_signers,
    )
    key_registry_path = tmp_path / "authority-keys.json"
    key_registry = json.loads(key_registry_path.read_text(encoding="utf-8"))
    key_registry["keys"][0].update(
        {
            "notBefore": (now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "notAfter": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        }
    )
    _write(key_registry_path, key_registry)
    _replace_signed_snapshot(
        tmp_path,
        fixture_signers[0],
        {
            "issuedAt": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "validUntil": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        },
    )
    provider = provider_module.load_external_authority_provider(
        config_path, clock=lambda: clock_now[0]
    )
    workflow = replace(
        workflow,
        policy_authority_port=provider.participants.policy_authority_port,
        build_policy_authority_currentness=provider.participants.build_policy_authority_currentness,
    )
    storage = production_flow._LocalObjectStorage()
    app, opened = production_flow._assemble(tmp_path, workflow, storage)
    receipts = DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    try:
        provider.bind_receipt_journal(receipts)
        provider.attach_app(app)
        area_store = app.state.work_area_store
        orders = app.state.observation_work_order_store
        assert (
            app.state.site_store.register(
                "site-a",
                "External source site",
                production_flow.SiteFrame(
                    crs="EPSG:5186",
                    vertical_datum="KNGeoid2018",
                    unit="meter",
                    transform_version="1.0.0",
                ),
                organization_id="org-a",
                actor="operator-a",
                now=now - timedelta(minutes=30),
            ).record
            is not None
        )
        area_result = area_store.register(
            "site-a",
            name="Provider mapping area",
            polygon=production_flow._POLYGON,
            crs="EPSG:5186",
            supersedes=None,
            actor="operator-a",
            now=now - timedelta(minutes=29),
        )
        assert area_result.work_area is not None
        area = area_result.work_area
        baseline_order = orders.create_work_order(
            organization_id="org-a",
            site_id="site-a",
            name="Provider baseline survey",
            work_area_ids=[area.work_area_id],
            schedule_id=None,
            actor="operator-a",
            now=now - timedelta(minutes=28),
        )
        current_order = orders.create_work_order(
            organization_id="org-a",
            site_id="site-a",
            name="Provider current survey",
            work_area_ids=[area.work_area_id],
            schedule_id=None,
            actor="operator-a",
            now=now - timedelta(minutes=27),
        )
        baseline_revision, baseline_subject = production_flow._sealed_revision(
            app,
            baseline_order,
            "provider-baseline",
            start=now - timedelta(minutes=20),
            end=now - timedelta(minutes=15),
            storage=storage,
        )
        current_revision, current_subject = production_flow._sealed_revision(
            app,
            current_order,
            "provider-current",
            start=now - timedelta(minutes=10),
            end=now - timedelta(minutes=5),
            storage=storage,
        )
        policy, authority, policy_action = _provider_policy_admission(
            subjects=(baseline_subject, current_subject), envelope=envelope, now=now
        )
        initial_digest = provider.status()["snapshotDigest"]
        assert isinstance(initial_digest, str)
        second_digest = _replace_signed_snapshot(
            tmp_path,
            fixture_signers[0],
            {
                "sequence": 2,
                "previousSnapshotDigest": initial_digest,
                "issuedAt": now.isoformat().replace("+00:00", "Z"),
                "policyAuthorities": {
                    "records": [authority.event_payload()],
                    "currentDigests": [authority.digest],
                },
                "quantitativeAdministration": {"actions": [policy_action]},
            },
        )
        assert provider.reload_and_reconcile(now=now)["snapshotDigest"] == second_digest
        assert provider.participants.policy_authority_port is not None
        assert (
            provider.participants.policy_authority_port.resolve(authority.digest, now)
            == authority
        )
        assert policy.policy_digest is not None
        assert authority.permits_selection(
            policy, use="INSPECTION", subjects=(baseline_subject,), now=now
        )
        assert (
            app.state.external_validation_policy_registry.resolve(policy.policy_digest).status
            is PolicySelectionStatus.ACTIVE
        )
        assert (
            app.state.external_validation_policy_registry.select_for_inspection(baseline_subject).status
            is PolicySelectionStatus.ACTIVE
        )

        baseline_report = production_flow._inspect(
            app, revision=baseline_revision, subject=baseline_subject, policy=policy, now=now
        )
        current_report = production_flow._inspect(
            app, revision=current_revision, subject=current_subject, policy=policy, now=now
        )
        baseline_evidence = production_flow._validate_evidence(
            app,
            revision=baseline_revision,
            subject=baseline_subject,
            policy=policy,
            context_authority=context_authority,
            now=now,
            storage=storage,
        )
        current_evidence = production_flow._validate_evidence(
            app,
            revision=current_revision,
            subject=current_subject,
            policy=policy,
            context_authority=context_authority,
            now=now,
            storage=storage,
        )
        mapping = production_flow._mapping(
            subjects=(baseline_subject, current_subject),
            revisions=(baseline_revision, current_revision),
            reports=(baseline_report, current_report),
            evidence_records=(baseline_evidence, current_evidence),
            policy=policy,
            area=area,
            now=now,
            catalog_digest=catalog_record.digest,
        )
        assert mapping.mapping_digest is not None
        mapping_action = {
            "actionId": "provider-admit-mapping",
            "kind": "ADMIT_MAPPING",
            "effectiveAt": now.isoformat().replace("+00:00", "Z"),
            "actorId": "catalog-admin",
            "mapping": {
                "mappingRecordDigest": mapping.mapping_digest,
                **mapping.canonical_payload(),
            },
        }
        third_digest = _replace_signed_snapshot(
            tmp_path,
            fixture_signers[0],
            {
                "sequence": 3,
                "previousSnapshotDigest": second_digest,
                "issuedAt": now.isoformat().replace("+00:00", "Z"),
                "quantitativeAdministration": {"actions": [policy_action, mapping_action]},
            },
        )
        assert provider.reload_and_reconcile(now=now)["snapshotDigest"] == third_digest
        catalog = app.state.external_relative_volume_mapping_authority
        assert isinstance(catalog, ExternalQuantitativeAuthorityCatalog)
        assert [event["kind"] for event in catalog._journal.replay()] == [  # noqa: SLF001
            "external-quantitative-mapping-activated"
        ]

        invalid = replace(
            mapping,
            evidence_record_digests=("sha256:" + "f" * 64, mapping.evidence_record_digests[1]),
            mapping_record_digest=None,
        ).sealed()
        assert invalid.mapping_digest is not None
        invalid_action = {
            "actionId": "provider-reject-mapping-without-evidence",
            "kind": "ADMIT_MAPPING",
            "effectiveAt": (now + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "actorId": "catalog-admin",
            "mapping": {
                "mappingRecordDigest": invalid.mapping_digest,
                **invalid.canonical_payload(),
            },
        }
        clock_now[0] = now + timedelta(minutes=1)
        _replace_signed_snapshot(
            tmp_path,
            fixture_signers[0],
            {
                "sequence": 4,
                "previousSnapshotDigest": third_digest,
                "issuedAt": clock_now[0].isoformat().replace("+00:00", "Z"),
                "quantitativeAdministration": {
                    "actions": [policy_action, mapping_action, invalid_action]
                },
            },
        )
        assert provider.reload_and_reconcile(now=clock_now[0])["status"] == "BLOCKED"
        assert [event["kind"] for event in catalog._journal.replay()] == [  # noqa: SLF001
            "external-quantitative-mapping-activated"
        ]
    finally:
        receipts.close()
        for journal in opened:
            journal.close()


def test_attach_refuses_a_signed_administration_action_before_its_effective_time(
    tmp_path: Path,
) -> None:
    mapping = replace(
        _mapping(),
        valid_from=NOW,
        valid_until=NOW + timedelta(hours=1),
        mapping_record_digest=None,
    ).sealed()
    assert mapping.mapping_digest is not None
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    provider = provider_module.load_external_authority_provider(
        _provider_config(
            tmp_path,
            actions=(
                {
                    "actionId": "action-mapping-future",
                    "kind": "ADMIT_MAPPING",
                    "effectiveAt": "2026-09-11T00:02:00Z",
                    "actorId": "catalog-admin",
                    "mapping": {
                        "mappingRecordDigest": mapping.mapping_digest,
                        **mapping.canonical_payload(),
                    },
                },
            ),
        ),
        clock=lambda: NOW + timedelta(minutes=1),
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policies.jsonl"),
        authority_port=provider.participants.policy_authority_port,
        authority_currentness_port=provider.participants.build_policy_authority_currentness(
            coordinator
        ),
        clock=lambda: NOW + timedelta(minutes=1),
        coordinator=coordinator,
    )
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=coordinator,
    )
    app = _empty_app(provider, coordinator)
    app.state.external_validation_policy_registry = registry
    app.state.external_relative_volume_mapping_authority = catalog

    provider.bind_receipt_journal(
        DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    )
    with pytest.raises(provider_module.ExternalAuthorityProviderError, match="not yet effective"):
        provider.attach_app(app)

    assert provider.status()["status"] == "BLOCKED"
    assert catalog._journal.replay() == []  # noqa: SLF001


def test_restart_recovers_exactly_after_policy_actions_persist_but_receipt_append_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, authority = _administrable_policy()
    assert policy.policy_digest is not None
    provider_module = importlib.import_module("ksi_core.external_authority_provider")
    config_path = _provider_config(
        tmp_path,
        policy_records=(authority.event_payload(),),
        actions=(
            {
                "actionId": "admit-policy-a",
                "kind": "ADMIT_POLICY",
                "effectiveAt": "2026-09-11T00:01:00Z",
                "actorId": "policy-admin",
                "policy": policy.model_dump(by_alias=True, mode="json"),
            },
            {
                "actionId": "revoke-policy-a",
                "kind": "REVOKE_POLICY",
                "effectiveAt": "2026-09-11T00:02:00Z",
                "actorId": "policy-admin",
                "policyId": policy.policy_id,
                "policyVersion": policy.version,
            },
        ),
    )

    def clock() -> datetime:
        return NOW + timedelta(minutes=3)

    provider = provider_module.load_external_authority_provider(config_path, clock=clock)
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    policies_path = tmp_path / "policies.jsonl"
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(policies_path),
        authority_port=provider.participants.policy_authority_port,
        authority_currentness_port=provider.participants.build_policy_authority_currentness(
            coordinator
        ),
        clock=clock,
        coordinator=coordinator,
    )
    app = _empty_app(provider, coordinator)
    app.state.external_validation_policy_registry = registry
    receipts = DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    provider.bind_receipt_journal(receipts)

    def fail_receipt_append(_event: dict[str, object]) -> None:
        raise RuntimeError("injected receipt append failure")

    monkeypatch.setattr(receipts, "append", fail_receipt_append)

    with pytest.raises(
        provider_module.ExternalAuthorityProviderError, match="receipt append failed"
    ):
        provider.attach_app(app)

    assert provider.status()["status"] == "BLOCKED"
    assert [event["kind"] for event in registry._journal.replay()] == [  # noqa: SLF001
        "external-validation-policy-admitted",
        "external-validation-policy-revoked",
    ]
    registry._journal.close()  # noqa: SLF001
    receipts.close()

    restarted = provider_module.load_external_authority_provider(config_path, clock=clock)
    restarted_coordinator = ExternalAuthorityCurrentnessCoordinator()
    restarted_registry = ExternalValidationPolicyRegistry(
        DurableJournal(policies_path),
        authority_port=restarted.participants.policy_authority_port,
        authority_currentness_port=restarted.participants.build_policy_authority_currentness(
            restarted_coordinator
        ),
        clock=clock,
        coordinator=restarted_coordinator,
    )
    restarted_app = _empty_app(restarted, restarted_coordinator)
    restarted_app.state.external_validation_policy_registry = restarted_registry
    restarted_receipts = DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    restarted.bind_receipt_journal(restarted_receipts)
    restarted.attach_app(restarted_app)

    assert restarted.status()["status"] == "PROVIDER_CONFIGURED"
    assert len(restarted_receipts.replay()) == 1
    assert len(restarted_registry._journal.replay()) == 2  # noqa: SLF001
