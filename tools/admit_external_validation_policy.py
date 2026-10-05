#!/usr/bin/env python3
"""Admit one ACTIVE external-validation policy under a fresh authority key.

Deployment scope only (external-runtime candidate step 4).  Builds, with the
REAL Core/contract models:

* a new Ed25519 authority key pair (private key stays in ``--out-dir`` only),
* an ACTIVE ``external-validation-policy.v1`` bound to operator-pinned
  inspector digests (parser/grammar/envelope verified against the deployed
  inspector execution manifest before anything is written),
* its ``PolicyAuthorityRecord`` (exact sealed-subject allowlist semantics —
  see below), and
* a new signed provider snapshot (sequence+1, ``previousSnapshotDigest``
  chained, one ``ADMIT_POLICY`` action) plus the extended key registry.

The tool proves the new snapshot with the REAL provider loader
(``load_external_authority_provider``) on a staging copy and proves the
embedded ``ADMIT_POLICY`` action admits (``ADMITTED`` receipt) through a real
``ExternalValidationPolicyRegistry`` before printing digests.  Placement and
the ``/v1/operations/external-authority/reload`` call remain manual steps so
the operator reviews digests first.

Subject-scope semantics (read from
``external_validation_policy.py::permits_selection``): there is NO wildcard
or site/work-area scope matching.  ``INSPECTION`` requires the requested
sealed subject's canonical digest to equal one permitted subject digest;
``RELATIVE_VOLUME`` requires the exact ordered subject tuple to equal the
permitted tuple.  Sealed subjects bind ``submissionDigest``/``manifestDigest``
which only exist after upload+seal, so a pre-seal admission (this tool's
default ``--inert-subjects``) is ACTIVE but never selectable.  The selectable
admission (same ``policy_id``, next version, exact sealed subjects) happens
after seal; this tool accepts ``--subjects-json`` for that leg.
``SealedExternalSubjectV1`` has no work-area field, so a "work area" scope
cannot be expressed at all.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "core" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "domain" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "event-contracts" / "src"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from ksi_domain.canonical_json import canonical_json_bytes  # noqa: E402
from ksi_event_contracts.external_artifact_validation import (  # noqa: E402
    ExternalValidationPolicyV1,
    PolicyStatus,
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)

SNAPSHOT_DOMAIN = "ksi.external-authority-provider-snapshot.v1"

# Exact issuance envelope values (tools/issue_external_runtime_deployment.py::
# _build_envelope_digest).  NOT invented here: the tool recomputes the digest
# and refuses to continue unless it equals the inspector manifest's pinned
# resourceEnvelopeDigest.
PINNED_ENVELOPE_KWARGS: dict[str, object] = {
    "max_input_bytes": 20_000_000,
    "max_streamed_bytes": 20_000_000,
    "max_tiff_directories": 32,
    "max_tiff_entries": 2_048,
    "max_pixels": 2_000_000,
    "max_bands": 4,
    "max_blocks": 2_048,
    "max_decompressed_bytes": 40_000_000,
    "max_sample_bytes": 40_000_000,
    "max_geometry_vertices": 8,
    "max_cpu_seconds": 1.0,
    "max_memory_bytes": 40_000_000,
    "max_workspace_bytes": 40_000_000,
    "max_output_bytes": 20_000_000,
    "max_tenant_concurrency": 1,
    "max_queue_depth": 1,
    "max_deadline_seconds": 1.0,
    "lease_duration_seconds": 1.0,
    "max_retry_attempts": 1,
}


def _write_private_json(path: Path, payload: object) -> None:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    fd = os.open(os.fspath(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def _wire_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_all(
    *,
    current_registry: dict,
    current_snapshot: dict,
    inspector_manifest: dict,
    key_id: str,
    signer: Ed25519PrivateKey,
    parser_build_digest: str | None,
    envelope_kwargs: dict | None,
    subjects: list[SealedExternalSubjectV1],
    policy_id: str,
    policy_version: int,
    actor_id: str,
    permitted_uses: tuple[str, ...],
    inspection_rule_ids: tuple[str, ...],
    evidence_rule_ids: tuple[str, ...],
    compatibility_mapping_digests: tuple[str, ...],
    now: datetime,
    snapshot_valid_days: int,
    authority_active_days: int,
    key_valid_days: int,
) -> dict[str, object]:
    from ksi_core.domains.external.ingress.external_validation_policy import (
        PolicyAuthorityRecord,
        authorized_policy_body_digest,
    )

    manifest_body = inspector_manifest["body"]
    pinned_envelope_digest = manifest_body["resourceEnvelopeDigest"]
    envelope = ResourceEnvelopeV1(  # type: ignore[arg-type]
        **(envelope_kwargs or PINNED_ENVELOPE_KWARGS)
    ).sealed()
    if envelope.resource_envelope_digest != pinned_envelope_digest:
        raise ValueError(
            "issuance envelope values do not reproduce the manifest-pinned "
            f"resourceEnvelopeDigest (got {envelope.resource_envelope_digest}, "
            f"manifest pins {pinned_envelope_digest}) — refusing to invent an envelope"
        )
    manifest_canonical = canonical_json_bytes(manifest_body)
    manifest_body_digest = "sha256:" + hashlib.sha256(manifest_canonical).hexdigest()
    if inspector_manifest.get("signature", {}).get("digest") != manifest_body_digest:
        raise ValueError("inspector manifest signature digest does not match recomputed body")

    template = ExternalValidationPolicyV1(
        policy_id=policy_id,
        version=policy_version,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=parser_build_digest or manifest_body_digest,
        grammar_digest=manifest_body["backendProfileDigest"],
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest="sha256:" + "0" * 64,
        inspection_rule_ids=inspection_rule_ids,
        evidence_rule_ids=evidence_rule_ids,
        compatibility_mapping_digests=compatibility_mapping_digests,
        synthetic_test_only=False,
    ).sealed()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=tuple(subjects),
        permitted_uses=permitted_uses,
        authorized_actor_ids=(actor_id,),
        active_from=now - timedelta(hours=1),
        active_until=now + timedelta(days=authority_active_days),
        synthetic_test_only=False,
    ).sealed()
    assert authority.digest is not None
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    assert policy.policy_digest is not None

    action = {
        "actionId": f"admit-{policy_id}-v{policy_version}",
        "kind": "ADMIT_POLICY",
        "effectiveAt": _wire_time(now),
        "actorId": actor_id,
        "policy": policy.model_dump(by_alias=True, mode="json"),
    }
    not_before = now - timedelta(minutes=5)
    not_after = now + timedelta(days=key_valid_days)
    registry = copy.deepcopy(current_registry)
    registry["keys"].append(
        {
            "keyId": key_id,
            "role": "AUTHORITY_BUNDLE",
            "algorithm": "Ed25519",
            "status": "ACTIVE",
            "publicKeyFile": f"{key_id}.public.pem",
            "notBefore": _wire_time(not_before),
            "notAfter": _wire_time(not_after),
        }
    )
    unsigned = {
        "version": "external-authority-provider-snapshot.v1",
        "organizationId": current_snapshot["organizationId"],
        "sequence": int(current_snapshot["sequence"]) + 1,
        "previousSnapshotDigest": None,  # filled below from the real loader
        "issuedAt": _wire_time(now),
        "validUntil": _wire_time(now + timedelta(days=snapshot_valid_days)),
        "keyId": key_id,
        "catalogAuthorities": copy.deepcopy(current_snapshot["catalogAuthorities"]),
        "policyAuthorities": {
            # Carry every previously admitted authority forward: each snapshot
            # is cumulative, so earlier issued records stay current and their
            # leases do not fail with POLICY_UNAVAILABLE.
            "records": [
                *current_snapshot["policyAuthorities"]["records"],
                authority.event_payload(),
            ],
            "currentDigests": [
                *current_snapshot["policyAuthorities"]["currentDigests"],
                authority.digest,
            ],
        },
        "evidenceContexts": copy.deepcopy(current_snapshot["evidenceContexts"]),
        "quantitativeAdministration": {"actions": [action]},
    }
    return {
        "registry": registry,
        "unsigned_snapshot": unsigned,
        "policy": policy,
        "authority": authority,
        "action": action,
        "not_before": not_before,
        "not_after": not_after,
    }


def prove_with_real_loader(
    *, staging_dir: Path, provider_config: dict, registry: dict, unsigned: dict,
    public_pem: bytes, signer: Ed25519PrivateKey, previous_digest: str,
    clock_now: datetime,
) -> dict[str, str]:
    """Stage files with staging paths, sign, and prove via the REAL loader."""
    from ksi_core.external_authority_provider import load_external_authority_provider

    staging_dir.mkdir(parents=True, exist_ok=True)
    registry_path = staging_dir / "authority-keys.json"
    snapshot_path = staging_dir / "authority-snapshot.json"
    pem_path = staging_dir / f"{registry['keys'][-1]['keyId']}.public.pem"
    _write_private_json(registry_path, registry)
    pem_fd = os.open(os.fspath(pem_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(pem_fd, public_pem)
    finally:
        os.close(pem_fd)
    os.chmod(pem_path, 0o600)
    # The registry on disk must reference the sibling PEM by file name only,
    # exactly like production (contents are path-free except publicKeyFile).
    staged_registry = copy.deepcopy(registry)
    unsigned = {**unsigned, "previousSnapshotDigest": previous_digest}
    signed = canonical_json_bytes({"domain": SNAPSHOT_DOMAIN, "snapshot": unsigned})
    snapshot_digest = "sha256:" + hashlib.sha256(signed).hexdigest()
    _write_private_json(
        snapshot_path,
        {**unsigned, "signature": base64.b64encode(signer.sign(signed)).decode("ascii")},
    )
    staged_config = {
        **provider_config,
        "keyRegistryPath": str(registry_path),
        "snapshotPath": str(snapshot_path),
    }
    config_path = staging_dir / "external-authority-provider.json"
    _write_private_json(config_path, staged_config)
    provider = load_external_authority_provider(config_path, clock=lambda: clock_now)
    status = provider.status()
    if status.get("snapshotDigest") != snapshot_digest:
        raise ValueError("loader snapshot digest differs from locally computed digest")
    return {"snapshotDigest": snapshot_digest, "status": str(status.get("status"))}


def prove_admission(*, policy: ExternalValidationPolicyV1, authority, actor_id: str,
                    effective_at: datetime) -> str:
    """Admit the exact action payload through a real registry; expect ADMITTED."""
    from ksi_core.domains.external.ingress.external_validation_policy import (
        ExternalValidationPolicyRegistry,
        PolicyAuthorityPort,
    )
    from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
    from ksi_core.foundation.durable_journal import DurableJournal
    import tempfile

    retained = {authority.digest: authority}

    class _Port(PolicyAuthorityPort):
        """Retained authority port + coordinator-bound currentness projection."""

        def __init__(self) -> None:
            self._coordinator: ExternalAuthorityCurrentnessCoordinator | None = None

        def bind(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> "_Port":
            self._coordinator = coordinator
            return self

        @property
        def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator | None:
            return self._coordinator

        def resolve(self, digest: str, now: datetime):
            record = retained.get(digest)
            return record if record is not None and record.is_active_at(now) else None

        def resolve_historical(self, digest: str, at: datetime):
            record = retained.get(digest)
            return record if record is not None and record.is_active_at(at) else None

        def is_current(self, record, now: datetime) -> bool:
            return (
                record.digest is not None
                and retained.get(record.digest) == record
                and record.is_active_at(now)
            )

    with tempfile.TemporaryDirectory() as tmp:
        journal = DurableJournal(Path(tmp) / "policy-journal.jsonl")
        coordinator = ExternalAuthorityCurrentnessCoordinator()
        port = _Port().bind(coordinator)
        registry = ExternalValidationPolicyRegistry(
            journal,
            authority_port=port,
            authority_currentness_port=port,
            coordinator=coordinator,
        )
        receipt = registry.admit(policy, actor_id, effective_at)
        journal.close()
    if receipt.status.value not in ("ADMITTED", "IDEMPOTENT"):
        raise ValueError(f"local admission proof failed: {receipt.status.value}")
    return receipt.status.value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-dir", required=True)
    parser.add_argument("--inspector-manifest", required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--subjects-json", default=None)
    parser.add_argument(
        "--envelope-json",
        default=None,
        help="override the policy resource envelope (JSON of ResourceEnvelopeV1 "
        "fields); the envelope digest must match the deployed inspector manifest",
    )
    parser.add_argument(
        "--parser-build-digest",
        default=None,
        help="override the policy parser build digest (defaults to the inspector "
        "manifest body digest); the running worker enforces its pinned value",
    )
    parser.add_argument("--policy-id", default="external-geotiff-v1")
    parser.add_argument("--policy-version", type=int, default=1)
    parser.add_argument("--actor-id", default="policy-admin")
    parser.add_argument("--snapshot-valid-days", type=int, default=7)
    parser.add_argument("--authority-active-days", type=int, default=7)
    parser.add_argument("--key-valid-days", type=int, default=30)
    args = parser.parse_args()

    from ksi_core.external_authority_provider import load_external_authority_provider

    now = datetime.now(UTC).replace(microsecond=0)
    operator_dir = Path(args.operator_dir)
    current_registry = json.loads((operator_dir / "authority-key-registry.json").read_text())
    current_snapshot = json.loads((operator_dir / "authority-snapshot.json").read_text())
    provider_config = json.loads((operator_dir / "provider.json").read_text())
    inspector_manifest = json.loads(Path(args.inspector_manifest).read_text())

    if args.subjects_json is not None:
        subjects = [
            SealedExternalSubjectV1.model_validate(item)
            for item in json.loads(Path(args.subjects_json).read_text())
        ]
    else:
        subjects = [
            SealedExternalSubjectV1(
                organization_id=current_snapshot["organizationId"],
                site_id="site-a",
                work_order_id="step4-inert-subject",
                submission_id="step4-inert-submission",
                revision=1,
                submission_digest="sha256:" + "0" * 63 + "1",
                manifest_digest="sha256:" + "0" * 63 + "2",
            )
        ]
    from ksi_core.domains.external.quantity.external_quantitative_authority import (
        CompatibilityRuleDescriptorV1,
    )
    from ksi_core.domains.external.quantity.external_single_volume_authority import (
        SingleVolumeCompatibilityRuleDescriptorV1,
    )

    signer = Ed25519PrivateKey.generate()
    built = build_all(
        current_registry=current_registry,
        current_snapshot=current_snapshot,
        inspector_manifest=inspector_manifest,
        key_id=args.key_id,
        signer=signer,
        parser_build_digest=args.parser_build_digest,
        envelope_kwargs=(
            json.loads(Path(args.envelope_json).read_text())
            if args.envelope_json is not None else None
        ),
        subjects=subjects,
        policy_id=args.policy_id,
        policy_version=args.policy_version,
        actor_id=args.actor_id,
        permitted_uses=("INSPECTION", "EVIDENCE", "RELATIVE_VOLUME", "SINGLE_VOLUME"),
        inspection_rule_ids=("EXTERNAL_GEOTIFF_MEASURED_V1",),
        evidence_rule_ids=("CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",),
        compatibility_mapping_digests=(
            CompatibilityRuleDescriptorV1().canonical_digest(),
            SingleVolumeCompatibilityRuleDescriptorV1().canonical_digest(),
        ),
        now=now,
        snapshot_valid_days=args.snapshot_valid_days,
        authority_active_days=args.authority_active_days,
        key_valid_days=args.key_valid_days,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = out_dir / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    # Carried-over registry keys reference sibling PEMs by file name; the
    # staged loader resolves them next to the staged registry file.
    for pem in operator_dir.glob("*.public.pem"):
        target = staging_dir / pem.name
        target.write_bytes(pem.read_bytes())
        os.chmod(target, 0o600)
    # previousSnapshotDigest from the REAL loader against current files first.
    prove_dir = out_dir / "prove-current"
    prove_dir.mkdir(parents=True, exist_ok=True)
    cur_paths = {}
    for name in ("authority-key-registry.json", "authority-snapshot.json", "provider.json"):
        target = prove_dir / name
        _write_private_json(target, json.loads((operator_dir / name).read_text()))
        cur_paths[name] = target
    for pem in operator_dir.glob("*.public.pem"):
        (prove_dir / pem.name).write_bytes(pem.read_bytes())
        os.chmod(prove_dir / pem.name, 0o600)
    prove_config = json.loads((prove_dir / "provider.json").read_text())
    prove_config["keyRegistryPath"] = str(prove_dir / "authority-key-registry.json")
    prove_config["snapshotPath"] = str(prove_dir / "authority-snapshot.json")
    prove_config_path = prove_dir / "external-authority-provider.json"
    _write_private_json(prove_config_path, prove_config)
    current_provider = load_external_authority_provider(prove_config_path, clock=lambda: now)
    previous_digest = current_provider.status()["snapshotDigest"]
    assert isinstance(previous_digest, str)

    public_pem = signer.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    loader_proof = prove_with_real_loader(
        staging_dir=staging_dir,
        provider_config=provider_config,
        registry=built["registry"],
        unsigned=built["unsigned_snapshot"],
        public_pem=public_pem,
        signer=signer,
        previous_digest=previous_digest,
        clock_now=now,
    )
    admission_proof = prove_admission(
        policy=built["policy"],
        authority=built["authority"],
        actor_id=args.actor_id,
        effective_at=now,
    )
    _write_private_json(out_dir / "authority-key-registry.json", built["registry"])
    _write_private_json(
        out_dir / "authority-snapshot.json",
        {
            **built["unsigned_snapshot"],
            "previousSnapshotDigest": previous_digest,
            "signature": base64.b64encode(
                signer.sign(
                    canonical_json_bytes(
                        {
                            "domain": SNAPSHOT_DOMAIN,
                            "snapshot": {
                                **built["unsigned_snapshot"],
                                "previousSnapshotDigest": previous_digest,
                            },
                        }
                    )
                )
            ).decode("ascii"),
        },
    )
    private_pem = signer.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_path = out_dir / f"{args.key_id}.public.pem"
    fd = os.open(os.fspath(pub_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, public_pem)
    finally:
        os.close(fd)
    os.chmod(pub_path, 0o600)
    priv_path = out_dir / f"{args.key_id}.private.pem"
    fd = os.open(os.fspath(priv_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, private_pem)
    finally:
        os.close(fd)
    os.chmod(priv_path, 0o600)
    print(
        json.dumps(
            {
                "keyId": args.key_id,
                "previousSnapshotDigest": previous_digest,
                "snapshotDigest": loader_proof["snapshotDigest"],
                "loaderStatus": loader_proof["status"],
                "admission": admission_proof,
                "policyDigest": built["policy"].policy_digest,
                "authorityRecordDigest": built["authority"].digest,
                "parserBuildDigest": built["policy"].parser_build_digest,
                "grammarDigest": built["policy"].grammar_digest,
                "resourceEnvelopeDigest": built["policy"].resource_envelope_digest,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
