"""The chain-renewal tool regenerates authority windows and fails closed.

Builds a minimal signed F-03-generation provider (one policy authority record,
one evidence context, one catalog authority, a signed sequence-1 snapshot) and
verifies that ``tools/regenerate_external_validation_chain.py``:

  - renews the policy body to the next version and re-binds every digest,
  - rebinds the evidence context to the renewed policy,
  - rebuilds the catalog authority against the same catalog body,
  - advances the snapshot exactly one sequence,
  - passes the real provider loader preflight,
  - refuses a chain whose retained receipt head does not match the snapshot,
  - leaves files untouched in ``--check-only`` mode.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.domains.external.authority.external_result_workflow_config import (
    catalog_admission_body_digest,
)
from ksi_core.domains.external.authority.provider_loading import _snapshot_from_path
from ksi_core.domains.external.authority.provider_types import (
    _ProviderConfig,
    _VerifiedSnapshot,
)
from ksi_core.domains.external.ingress.external_validation_policy import (
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from ksi_core.domains.external.quantity.external_quantitative_authority import (
    ExternalQuantitativeCatalogAuthorityRecord,
)
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeQueuePolicy,
)
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import regenerate_external_validation_chain as tool  # noqa: E402 -- tools/ 를 sys.path 에 넣은 뒤에만 해석 가능

_DOMAIN = "ksi.external-authority-provider-snapshot.v1"


@dataclass(frozen=True, slots=True)
class _ProviderFiles:
    provider: Path
    core_data: Path
    snapshot_digest: str
    policy_digest: str | None


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _write_private(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.chmod(path, 0o600)


def _snapshot_digest(snapshot: dict[str, object]) -> str:
    unsigned = {key: value for key, value in snapshot.items() if key != "signature"}
    return (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes({"domain": _DOMAIN, "snapshot": unsigned})
        ).hexdigest()
    )


@pytest.fixture()
def provider(tmp_path: Path) -> _ProviderFiles:
    """Minimal signed provider with one policy/context/catalog generation."""
    now = datetime.now(UTC).replace(microsecond=0)
    signer = Ed25519PrivateKey.generate()
    bundle = tmp_path / "authority-bundle.pem"
    bundle.write_bytes(
        signer.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    os.chmod(bundle, 0o600)
    signer_path = tmp_path / "authority-signer.private.pem"
    signer_path.write_bytes(
        signer.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(signer_path, 0o600)
    _write_private(
        tmp_path / "authority-keys.json",
        {
            "version": "external-authority-key-registry.v1",
            "keys": [
                {
                    "keyId": "test-authority-key-1",
                    "role": "AUTHORITY_BUNDLE",
                    "algorithm": "Ed25519",
                    "status": "ACTIVE",
                    "publicKeyFile": bundle.name,
                    "notBefore": (now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                    "notAfter": (now + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
                }
            ],
        },
    )

    subject = SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="wo-1",
        submission_id="sub-1",
        revision=1,
        submission_digest=_digest("submission-1"),
        manifest_digest=_digest("manifest-1"),
    )
    policy_body = {
        "contractVersion": "external-validation-policy.v1",
        "policyId": "external-geotiff-v1",
        "version": 1,
        "status": "ACTIVE",
        "parserBuildDigest": _digest("parser-build-1"),
        "grammarDigest": _digest("grammar-1"),
        "resourceEnvelope": {
            "maxInputBytes": 4_000_000,
            "maxStreamedBytes": 4_000_000,
            "maxTiffDirectories": 32,
            "maxTiffEntries": 2048,
            "maxPixels": 2_000_000,
            "maxBands": 4,
            "maxBlocks": 2048,
            "maxDecompressedBytes": 40_000_000,
            "maxSampleBytes": 40_000_000,
            "maxGeometryVertices": 64,
            "maxCpuSeconds": 60.0,
            "maxMemoryBytes": 400_000_000,
            "maxWorkspaceBytes": 400_000_000,
            "maxOutputBytes": 20_000_000,
            "maxTenantConcurrency": 1,
            "maxQueueDepth": 4,
            "maxDeadlineSeconds": 600.0,
            "leaseDurationSeconds": 60.0,
            "maxRetryAttempts": 2,
        },
        "authorityRecordDigest": "sha256:" + "0" * 64,
        "inspectionRuleIds": ["EXTERNAL_GEOTIFF_MEASURED_V1"],
        "evidenceRuleIds": ["CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1"],
        "compatibilityMappingDigests": [_digest("rule-1")],
        "syntheticTestOnly": False,
    }
    from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1

    envelope = ResourceEnvelopeV1(
        max_input_bytes=4_000_000,
        max_streamed_bytes=4_000_000,
        max_tiff_directories=32,
        max_tiff_entries=2_048,
        max_pixels=2_000_000,
        max_bands=4,
        max_blocks=2_048,
        max_decompressed_bytes=40_000_000,
        max_sample_bytes=40_000_000,
        max_geometry_vertices=64,
        max_cpu_seconds=60.0,
        max_memory_bytes=400_000_000,
        max_workspace_bytes=400_000_000,
        max_output_bytes=20_000_000,
        max_tenant_concurrency=1,
        max_queue_depth=4,
        max_deadline_seconds=600.0,
        lease_duration_seconds=60.0,
        max_retry_attempts=2,
    ).sealed()
    placeholder = ExternalValidationPolicyV1.model_validate(
        {
            **policy_body,
            "resourceEnvelope": envelope.model_dump(by_alias=True, mode="json"),
            "resourceEnvelopeDigest": envelope.resource_envelope_digest,
            "policyDigest": None,
        }
    )
    body_digest = authorized_policy_body_digest(placeholder)
    expired_from = now - timedelta(hours=8)
    expired_until = now - timedelta(hours=1)
    record = PolicyAuthorityRecord(
        policy_id="external-geotiff-v1",
        policy_version=1,
        authorized_policy_body_digest=body_digest,
        permitted_subjects=(subject,),
        permitted_uses=("INSPECTION", "EVIDENCE", "RELATIVE_VOLUME"),
        authorized_actor_ids=("policy-admin",),
        active_from=expired_from,
        active_until=expired_until,
        synthetic_test_only=False,
    ).sealed()
    assert record.digest
    sealed_v1 = placeholder.model_copy(
        update={"authority_record_digest": record.digest}, deep=True
    ).sealed()
    body_file = sealed_v1.model_dump(by_alias=True, mode="json")
    context = ExternalEvidenceMeasurementContextV1.model_validate(
        {
            "contractVersion": "external-evidence-measurement-context.v1",
            "contextId": "context-wo-1",
            "subject": subject.model_dump(by_alias=True, mode="json"),
            "evidenceManifestDigest": _digest("evidence-manifest-1"),
            "evidenceObservedSha256": _digest("evidence-bytes-1"),
            "evidenceObservedSizeBytes": 128,
            "targetDsmArtifactId": "dsm",
            "targetDsmObservedSha256": _digest("dsm-bytes-1"),
            "policyDigest": _digest("policy-1"),
            "measurementExecutionManifestDigest": _digest("measurement-manifest-1"),
            "ruleId": "CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",
            "csvHorizontalCrs": "EPSG:5186",
            "csvVerticalReferenceDigest": _digest("vertical-1"),
            "minimumCheckpointCount": 3,
            "maximumCheckpointCount": 100,
            "maximumRmseM": 0.5,
            "maximumAbsMeanErrorM": 0.2,
            "maximumAbsErrorM": 1.0,
            "independentAttestation": None,
            "authorizedActorIds": ["independent-validator"],
            "activeFrom": expired_from.isoformat().replace("+00:00", "Z"),
            "activeUntil": expired_until.isoformat().replace("+00:00", "Z"),
            "syntheticTestOnly": False,
        }
    ).sealed()
    assert context.context_digest

    catalog = {
        "version": "external-quantitative-catalog.v1",
        "authorityRecordDigest": _digest("catalog-placeholder"),
        "body": {
            "organizationId": "org-a",
            "executionTemplates": [
                {
                    "executionPolicy": {
                        "contractVersion": "external-relative-volume-execution-policy.v1",
                        "policyId": "external-volume-policy",
                        "version": 1,
                        "algorithmBuildDigest": _digest("volume-algorithm"),
                        "configDigest": _digest("volume-config"),
                        "thresholdM": 0.1,
                        "minimumCommonValidFraction": 0.8,
                        "uncertaintyMethod": "INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1",
                        "resourceEnvelopeDigest": _digest("volume-envelope"),
                        "authorityRecordDigest": _digest("catalog-placeholder"),
                        "syntheticTestOnly": False,
                    },
                    "authorizedActorIds": ["operator-a"],
                    "validFrom": expired_from.isoformat().replace("+00:00", "Z"),
                    "validUntil": expired_until.isoformat().replace("+00:00", "Z"),
                    "maximumZoneCellCount": 10_000,
                    "maximumZoneAreaM2": 1_000_000.0,
                }
            ],
        },
    }
    catalog_body_digest = catalog_admission_body_digest(catalog)
    catalog_authority = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id="org-a",
        catalog_body_digest=catalog_body_digest,
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=expired_from,
        active_until=expired_until,
        synthetic_test_only=False,
    ).sealed()
    assert catalog_authority.digest
    catalog["authorityRecordDigest"] = catalog_authority.digest
    catalog_body = cast(dict[str, object], catalog["body"])
    templates = cast(list[dict[str, object]], catalog_body["executionTemplates"])
    cast(dict[str, object], templates[0]["executionPolicy"])["authorityRecordDigest"] = (
        catalog_authority.digest
    )
    assert catalog_admission_body_digest(catalog) == catalog_body_digest

    unsigned: dict[str, object] = {
        "version": "external-authority-provider-snapshot.v1",
        "organizationId": "org-a",
        "sequence": 1,
        "previousSnapshotDigest": None,
        "issuedAt": expired_from.isoformat().replace("+00:00", "Z"),
        "validUntil": expired_until.isoformat().replace("+00:00", "Z"),
        "keyId": "test-authority-key-1",
        "catalogAuthorities": {
            "records": [catalog_authority.event_payload()],
            "currentDigests": [catalog_authority.digest],
        },
        "policyAuthorities": {
            "records": [record.event_payload()],
            "currentDigests": [record.digest],
        },
        "evidenceContexts": {
            "records": [context.model_dump(by_alias=True, mode="json")],
            "currentDigests": [context.context_digest],
        },
        "quantitativeAdministration": {"actions": []},
    }
    signature = signer.sign(canonical_json_bytes({"domain": _DOMAIN, "snapshot": unsigned}))
    snapshot = {**unsigned, "signature": base64.b64encode(signature).decode("ascii")}

    _write_private(tmp_path / "policy-valid.json", body_file)
    _write_private(tmp_path / "catalog.json", catalog)
    _write_private(tmp_path / "authority-snapshot.json", snapshot)
    core_data = tmp_path / "core-data"
    core_data.mkdir(mode=0o700)
    receipts = core_data / "external-authority-provider-receipts.jsonl"
    receipts.write_text(
        json.dumps(
            {
                "kind": "external-authority-provider-receipt",
                "version": 1,
                "sequence": 1,
                "snapshotDigest": _snapshot_digest(snapshot),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(receipts, 0o600)
    return _ProviderFiles(
        provider=tmp_path,
        core_data=core_data,
        snapshot_digest=_snapshot_digest(snapshot),
        policy_digest=sealed_v1.policy_digest,
    )


def _verify_with_loader(provider: Path) -> _VerifiedSnapshot:
    config = _ProviderConfig(
        organization_id="org-a",
        key_registry_path=provider / "authority-keys.json",
        snapshot_path=provider / "authority-snapshot.json",
        catalog_administration_actor_id="catalog-admin",
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(seconds=60),
            deadline_after_issue=timedelta(seconds=3600),
            max_attempts=3,
            max_active_requests_per_organization=2,
        ),
    )
    return _snapshot_from_path(config, clock=lambda: datetime.now(UTC))


def test_renewal_rebinds_every_digest_and_advances_one_sequence(provider: _ProviderFiles) -> None:
    provider_dir = provider.provider
    before = (provider_dir / "authority-snapshot.json").read_bytes()
    exit_code = tool.main(
        [
            "--provider-dir",
            str(provider_dir),
            "--core-data-dir",
            str(provider.core_data),
        ]
    )
    assert exit_code == 0

    snapshot = json.loads((provider_dir / "authority-snapshot.json").read_text())
    body_file = json.loads((provider_dir / "policy-valid.json").read_text())
    catalog = json.loads((provider_dir / "catalog.json").read_text())
    assert (provider_dir / "authority-snapshot.json").read_bytes() != before
    assert snapshot["sequence"] == 2
    assert snapshot["previousSnapshotDigest"] == provider.snapshot_digest

    verified = _verify_with_loader(provider_dir)
    assert verified.sequence == 2
    assert body_file["version"] == 2
    new_record_digest = snapshot["policyAuthorities"]["currentDigests"][0]
    assert body_file["authorityRecordDigest"] == new_record_digest
    # The context now binds the renewed policy and a fresh window.
    context = snapshot["evidenceContexts"]["records"][0]
    assert context["policyDigest"] == body_file["policyDigest"]
    earlier = json.loads(before)
    assert context["contextDigest"] != earlier["evidenceContexts"]["currentDigests"][0]
    # The catalog body digest is preserved; only the authority window changed.
    assert catalog["authorityRecordDigest"] != earlier["catalogAuthorities"]["currentDigests"][0]
    assert [action["kind"] for action in snapshot["quantitativeAdministration"]["actions"]] == [
        "ADMIT_POLICY"
    ]


def test_check_only_leaves_files_untouched(provider: _ProviderFiles) -> None:
    provider_dir = provider.provider
    before = (provider_dir / "authority-snapshot.json").read_bytes()
    assert (
        tool.main(
            [
                "--provider-dir",
                str(provider_dir),
                "--core-data-dir",
                str(provider.core_data),
                "--check-only",
            ]
        )
        == 0
    )
    assert (provider_dir / "authority-snapshot.json").read_bytes() == before


def test_stale_receipt_head_refuses_the_renewal(provider: _ProviderFiles) -> None:
    provider_dir = provider.provider
    # First renewal succeeds (head matches), then the retained head is stale.
    assert (
        tool.main(["--provider-dir", str(provider_dir), "--core-data-dir", str(provider.core_data)])
        == 0
    )
    assert stat.S_IMODE((provider_dir / "authority-snapshot.json").stat().st_mode) == 0o600
    with pytest.raises(SystemExit):
        tool.main(["--provider-dir", str(provider_dir), "--core-data-dir", str(provider.core_data)])


def test_snapshot_digest_continuity_is_verified(provider: _ProviderFiles) -> None:
    """A receipt head whose digest does not match the snapshot is refused."""
    receipts = provider.core_data / "external-authority-provider-receipts.jsonl"
    receipts.write_text(
        json.dumps(
            {
                "kind": "external-authority-provider-receipt",
                "version": 1,
                "sequence": 1,
                "snapshotDigest": _digest("substituted"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(receipts, 0o600)
    with pytest.raises(SystemExit):
        tool.main(
            [
                "--provider-dir",
                str(provider.provider),
                "--core-data-dir",
                str(provider.core_data),
                "--check-only",
            ]
        )


def _subject_payload(
    submission_id: str, submission_label: str, manifest_label: str
) -> dict[str, object]:
    return SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="f03-flow-site",
        work_order_id="wo-public",
        submission_id=submission_id,
        revision=1,
        submission_digest=_digest(submission_label),
        manifest_digest=_digest(manifest_label),
    ).model_dump(by_alias=True, mode="json")


def test_add_subject_file_appends_subject_with_prior_order_and_dedup(
    provider: _ProviderFiles,
) -> None:
    """The explicit signing step retains priors, appends, dedups, stays deterministic."""
    provider_dir = provider.provider
    added = _subject_payload("sub-public", "submission-public", "manifest-public")
    prior_duplicate = SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="wo-1",
        submission_id="sub-1",
        revision=1,
        submission_digest=_digest("submission-1"),
        manifest_digest=_digest("manifest-1"),
    ).model_dump(by_alias=True, mode="json")
    # canonical_digest() is deterministic across validations of the same payload.
    first = SealedExternalSubjectV1.model_validate(added).canonical_digest()
    assert SealedExternalSubjectV1.model_validate(added).canonical_digest() == first
    assert (
        SealedExternalSubjectV1.model_validate(prior_duplicate).canonical_digest()
        != first
    )
    subjects_file = provider_dir / "add-subjects.json"
    subjects_file.write_text(
        json.dumps([added, prior_duplicate]), encoding="utf-8"
    )
    state_file = provider_dir / "renew-state.json"
    assert (
        tool.main(
            [
                "--provider-dir",
                str(provider_dir),
                "--core-data-dir",
                str(provider.core_data),
                "--add-subject-file",
                str(subjects_file),
                "--state-file",
                str(state_file),
            ]
        )
        == 0
    )
    snapshot = json.loads((provider_dir / "authority-snapshot.json").read_text())
    subjects = snapshot["policyAuthorities"]["records"][0]["permittedSubjects"]
    # Prior subject retained first, added subject appended, duplicate dropped.
    assert [item["submissionId"] for item in subjects] == ["sub-1", "sub-public"]
    assert SealedExternalSubjectV1.model_validate(subjects[0]).canonical_digest() != first
    assert SealedExternalSubjectV1.model_validate(subjects[1]).canonical_digest() == first
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["addedSubjectDigests"] == [first]
    verified = _verify_with_loader(provider_dir)
    assert verified.sequence == 2


def test_absent_add_subject_file_preserves_prior_subjects_only(
    provider: _ProviderFiles,
) -> None:
    """Without the option the renewal carries the prior subjects unchanged."""
    provider_dir = provider.provider
    state_file = provider_dir / "renew-state.json"
    assert (
        tool.main(
            [
                "--provider-dir",
                str(provider_dir),
                "--core-data-dir",
                str(provider.core_data),
                "--state-file",
                str(state_file),
            ]
        )
        == 0
    )
    snapshot = json.loads((provider_dir / "authority-snapshot.json").read_text())
    subjects = snapshot["policyAuthorities"]["records"][0]["permittedSubjects"]
    assert [item["submissionId"] for item in subjects] == ["sub-1"]
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["addedSubjectDigests"] == []
