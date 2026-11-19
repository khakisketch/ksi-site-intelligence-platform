"""Signed profile-difference authority reaches real Core owners and revokes cleanly.

Every authority key and every DSM/checkpoint fixture is created in this test. The
test proves normal signature, Core evidence, WorkArea, mapping, decision, and
history boundaries. It does not represent customer or field acceptance.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from analysis_api_local_fixture import (
    _envelope,
    _evidence_context,
    _principal,
    _record_evidence_validation,
    _register_and_seal_v2_dsm,
    _seal_evidence,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core.domains.external.authority.external_authority_provider import (
    load_external_authority_provider,
)
from ksi_core.domains.external.authority.external_result_workflow_config import (
    load_external_result_workflow_config,
)
from ksi_core.domains.external.ingress.external_validation_policy import (
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from ksi_core.domains.external.quantity.external_quantitative_authority import (
    CompatibilityRuleDescriptorV1,
    ExternalQuantitativeCatalogAuthorityRecord,
    ExternalQuantitativeCompatibilityRecord,
)
from ksi_core.durable_journal import DurableJournal
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    PolicyStatus,
)
from ksi_event_contracts.external_relative_volume import (
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller.external_geotiff_profile import external_geotiff_profile_digest_v1
from test_external_analysis_real_inspection_lane_integration import _CoreAndObjectServers
from test_external_inspector_container_entrypoint import _manifest
from test_external_result_workflow_config import _catalog_body, _catalog_digest
from test_platform_core_http_integration import (
    _create_external_order,
    _lane_view,
    _seed_site_and_area,
    _store_order,
)
from test_surface_profile_comparison_http import _ORIGIN_X, _ORIGIN_Y, _surface
from test_surface_profile_http_integration import (
    _feature_ref,
    _height_decision_id,
    _provision_surface_grant,
    _reader_headers,
    _ReadyFlow,
    _retain_real_parser_report,
    _run_surface_worker,
    _sealed_object_key,
)

_SNAPSHOT_DOMAIN = "ksi.external-authority-provider-snapshot.v1"


def _digest(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _write_private(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    path.chmod(0o600)


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _time_after(previous: datetime) -> datetime:
    """Use a current timestamp at least one whole second after an event."""
    while True:
        candidate = datetime.now(UTC).replace(microsecond=0)
        if candidate > previous:
            return candidate
        time.sleep(0.05)


def _signed_provider_files(
    root: Path, *, now: datetime
) -> tuple[Path, Path, Path, Ed25519PrivateKey]:
    signer = Ed25519PrivateKey.generate()
    public_key_path = root / "authority-public.pem"
    public_key_path.write_bytes(
        signer.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    public_key_path.chmod(0o600)
    key_registry_path = root / "authority-keys.json"
    _write_private(
        key_registry_path,
        {
            "version": "external-authority-key-registry.v1",
            "keys": [
                {
                    "keyId": "profile-difference-test-key",
                    "role": "AUTHORITY_BUNDLE",
                    "algorithm": "Ed25519",
                    "status": "ACTIVE",
                    "publicKeyFile": public_key_path.name,
                    "notBefore": _utc(now - timedelta(days=1)),
                    "notAfter": _utc(now + timedelta(days=2)),
                }
            ],
        },
    )

    catalog_body = _catalog_body()
    templates = cast(list[dict[str, object]], catalog_body["executionTemplates"])
    template = templates[0]
    template["validFrom"] = _utc(now - timedelta(hours=1))
    template["validUntil"] = _utc(now + timedelta(hours=1))
    catalog_authority = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id="org-a",
        catalog_body_digest=_catalog_digest(catalog_body),
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=now - timedelta(hours=1),
        active_until=now + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    assert catalog_authority.digest is not None
    catalog_body = _catalog_body(catalog_authority.digest)
    templates = cast(list[dict[str, object]], catalog_body["executionTemplates"])
    template = templates[0]
    template["validFrom"] = _utc(now - timedelta(hours=1))
    template["validUntil"] = _utc(now + timedelta(hours=1))
    catalog_path = root / "catalog.json"
    _write_private(
        catalog_path,
        {
            "version": "external-quantitative-catalog.v1",
            "authorityRecordDigest": catalog_authority.digest,
            "body": catalog_body,
        },
    )
    workflow_path = root / "workflow.json"
    _write_private(
        workflow_path,
        {
            "version": "external-result-workflow-config.v1",
            "authorityJournalPath": str(root / "quantitative-authority.jsonl"),
            "catalogPath": str(catalog_path),
        },
    )

    unsigned: dict[str, object] = {
        "version": "external-authority-provider-snapshot.v1",
        "organizationId": "org-a",
        "sequence": 1,
        "previousSnapshotDigest": None,
        "issuedAt": _utc(now - timedelta(seconds=1)),
        "validUntil": _utc(now + timedelta(hours=1)),
        "keyId": "profile-difference-test-key",
        "catalogAuthorities": {
            "records": [catalog_authority.event_payload()],
            "currentDigests": [catalog_authority.digest],
        },
        "policyAuthorities": {"records": [], "currentDigests": []},
        "evidenceContexts": {"records": [], "currentDigests": []},
        "quantitativeAdministration": {"actions": []},
    }
    signature = signer.sign(
        canonical_json_bytes({"domain": _SNAPSHOT_DOMAIN, "snapshot": unsigned})
    )
    snapshot_path = root / "authority-snapshot.json"
    _write_private(
        snapshot_path,
        {**unsigned, "signature": base64.b64encode(signature).decode("ascii")},
    )
    config_path = root / "authority-provider.json"
    _write_private(
        config_path,
        {
            "version": "external-authority-provider-config.v1",
            "organizationId": "org-a",
            "keyRegistryPath": str(key_registry_path),
            "snapshotPath": str(snapshot_path),
            "catalogAdministrationActorId": "catalog-admin",
            "leaseTtlSeconds": 60,
            "deadlineAfterIssueSeconds": 600,
            "maxAttempts": 3,
            "maxActiveRequestsPerOrganization": 2,
        },
    )
    return config_path, workflow_path, snapshot_path, signer


def _publish_snapshot(
    *,
    provider: Any,
    snapshot_path: Path,
    signer: Ed25519PrivateKey,
    now: datetime,
    fields: dict[str, object],
) -> str:
    current = json.loads(snapshot_path.read_text(encoding="utf-8"))
    unsigned = {key: value for key, value in current.items() if key != "signature"}
    snapshot_digest = provider.status()["snapshotDigest"]
    assert isinstance(snapshot_digest, str)
    unsigned["sequence"] = int(unsigned["sequence"]) + 1
    unsigned["previousSnapshotDigest"] = snapshot_digest
    unsigned["issuedAt"] = _utc(now)
    unsigned.update(fields)
    signature = signer.sign(
        canonical_json_bytes({"domain": _SNAPSHOT_DOMAIN, "snapshot": unsigned})
    )
    _write_private(
        snapshot_path,
        {**unsigned, "signature": base64.b64encode(signature).decode("ascii")},
    )
    from ksi_core.domains.external.authority.provider_loading import _snapshot_from_path

    _snapshot_from_path(provider._config, clock=lambda: now)
    result = provider.reload_and_reconcile(now=now)
    assert result["status"] == "PROVIDER_CONFIGURED", {
        **result,
        "blockedReason": provider._blocked_reason,
    }
    return str(result["snapshotDigest"])


def _signed_policy(
    *,
    subjects: tuple[Any, Any],
    envelope: Any,
    now: datetime,
) -> tuple[ExternalValidationPolicyV1, PolicyAuthorityRecord]:
    inspector_manifest = _manifest(envelope)
    template = ExternalValidationPolicyV1(
        policy_id="profile-difference-geotiff-v1",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=inspector_manifest.parser_build_digest,
        grammar_digest=external_geotiff_profile_digest_v1(),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=_digest("unbound-profile-policy-authority"),
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
        permitted_uses=(
            "INSPECTION",
            "EVIDENCE",
            "HEIGHT",
            "RELATIVE_VOLUME",
            "PROFILE_DIFFERENCE",
        ),
        authorized_actor_ids=("policy-admin",),
        active_from=now - timedelta(hours=1),
        active_until=now + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    assert authority.digest is not None
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    return policy, authority


def _mapping_record(
    *,
    subjects: tuple[Any, Any],
    revisions: tuple[Any, Any],
    reports: tuple[Any, Any],
    evidence_records: tuple[Any, Any],
    policy: ExternalValidationPolicyV1,
    area: Any,
    catalog_digest: str,
    now: datetime,
) -> ExternalQuantitativeCompatibilityRecord:
    bindings = []
    for subject, revision, report in zip(subjects, revisions, reports, strict=True):
        dsm = next(
            entry for entry in revision.manifest.entries if entry.kind is ProcessingArtifactKind.DSM
        )
        outcome = next(
            item
            for item in report.measurement_payload.outcomes
            if item.artifact_id == dsm.artifact_id
        )
        measurements = outcome.measurements
        assert measurements is not None and measurements.observed_vertical_reference is not None
        declaration = revision.submission.input_declaration
        assert (
            declaration.capture_started_at is not None and declaration.capture_ended_at is not None
        )
        bindings.append(
            ExternalVolumeInputBindingV1(
                subject=subject,
                inspection_report_digest=report.report_digest,
                dsm_artifact_id=dsm.artifact_id,
                observed_sha256="sha256:" + dsm.observed_sha256,
                observed_size_bytes=dsm.observed_size_bytes,
                observed_crs_digest=measurements.observed_crs_digest,
                observed_vertical_reference_digest=(
                    measurements.observed_vertical_reference.canonical_digest()
                ),
                captured_from=declaration.capture_started_at,
                captured_to=declaration.capture_ended_at,
            )
        )
    crs_digest = bindings[0].observed_crs_digest
    vertical_digest = bindings[0].observed_vertical_reference_digest
    assert bindings[1].observed_crs_digest == crs_digest
    assert bindings[1].observed_vertical_reference_digest == vertical_digest
    assert policy.policy_digest is not None
    zone = ExternalVolumeZoneSnapshotV1(
        organization_id="org-a",
        site_id=subjects[0].site_id,
        work_area_id=area.work_area_id,
        polygon=area.polygon,
        crs=area.crs,
        observed_crs_digest=crs_digest,
        analysis_vertical_reference_digest=vertical_digest,
    ).sealed()
    record = ExternalQuantitativeCompatibilityRecord(
        organization_id="org-a",
        site_id=subjects[0].site_id,
        baseline=bindings[0],
        current=bindings[1],
        zone_snapshot=zone,
        validation_policy_digest=policy.policy_digest,
        external_profile="external-geotiff-profile.v1",
        grammar_digest=policy.grammar_digest,
        inspector_build_digest=policy.parser_build_digest,
        evidence_record_digests=tuple(item.evidence_record_digest for item in evidence_records),
        execution_policy_ref=catalog_digest,
        valid_from=now - timedelta(minutes=30),
        valid_until=now + timedelta(minutes=30),
    ).sealed()
    return record


def test_signed_provider_gates_profile_decisions_and_retains_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a signed mapping plus current independent Core evidence permits use."""
    import test_platform_core_http_integration as platform_fixture

    initial_now = datetime.now(UTC).replace(microsecond=0)
    config_path, workflow_path, snapshot_path, signer = _signed_provider_files(
        tmp_path, now=initial_now
    )
    provider_clock = [initial_now]
    provider_box: list[Any] = []

    def make_workflow(
        path: Path,
        *,
        now: datetime,
        organization_id: str = "org-a",
        policy_authority: Any,
        context_authority: Any,
    ) -> tuple[Any, None, Any, None]:
        del path, organization_id, policy_authority, context_authority
        provider_clock[0] = now
        provider = load_external_authority_provider(config_path, clock=lambda: provider_clock[0])
        provider_box.append(provider)
        receipts = DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
        receipt_journals.append(receipts)
        provider.bind_receipt_journal(receipts)
        workflow = load_external_result_workflow_config(
            workflow_path,
            participants=provider.participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
        )
        return workflow, None, _envelope(), None

    receipt_journals: list[DurableJournal] = []

    monkeypatch.setattr(platform_fixture, "_workflow", make_workflow)

    flow = _ReadyFlow(tmp_path / "platform", build_profile_difference_authority=None)
    try:
        ctx = flow.ctx
        provider = provider_box[-1]
        provider.attach_app(ctx.app)
        assert provider.status()["status"] == "PROVIDER_CONFIGURED"
        with TestClient(ctx.app) as setup:
            area_id = _seed_site_and_area(ctx, extent_m=48.0)
            epochs = []
            for side, days in (("baseline", 3), ("current", 1)):
                order = _store_order(
                    ctx,
                    _create_external_order(setup, area_id, key="profile-" + side)["workOrderId"],
                )
                start = ctx.now - timedelta(days=days)
                raw = _surface(current=side == "current")
                revision, subject = _register_and_seal_v2_dsm(
                    setup,
                    ctx.app,
                    order,
                    "signed-profile-" + side,
                    start=start,
                    end=start + timedelta(minutes=5),
                    storage=ctx.storage,
                    dsm_bytes=raw,
                )
                epochs.append((order, revision, subject))

        subjects = (epochs[0][2], epochs[1][2])
        policy, policy_authority = _signed_policy(
            subjects=subjects, envelope=ctx.envelope, now=ctx.now
        )
        policy_action = {
            "actionId": "profile-policy-admission",
            "kind": "ADMIT_POLICY",
            "effectiveAt": _utc(ctx.now),
            "actorId": "policy-admin",
            "policy": policy.model_dump(by_alias=True, mode="json"),
        }
        provider_clock[0] = ctx.now
        policy_snapshot_digest = _publish_snapshot(
            provider=provider,
            snapshot_path=snapshot_path,
            signer=signer,
            now=provider_clock[0],
            fields={
                "policyAuthorities": {
                    "records": [policy_authority.event_payload()],
                    "currentDigests": [policy_authority.digest],
                },
                "quantitativeAdministration": {"actions": [policy_action]},
            },
        )
        assert policy_snapshot_digest

        manifest = _manifest(ctx.envelope)
        flow.area_id = area_id
        flow.view = _lane_view(
            ctx,
            epochs[0][1],
            subjects[0],
            epochs[1][1],
            subjects[1],
            policy,
            manifest,
        )
        reports = []
        for _, revision, subject in epochs:
            _retain_real_parser_report(flow, subject=subject, revision=revision)
            reports.append(
                ctx.app.state.external_artifact_inspection_store.public_snapshot(subject).report
            )
        assert all(report is not None for report in reports)

        evidence_items = tuple(
            _seal_evidence(
                ctx.app,
                revision=revision,
                subject=subject,
                now=ctx.now,
                storage=ctx.storage,
                label="signed-profile-" + side,
            )
            for side, (_, revision, subject) in zip(("baseline", "current"), epochs, strict=True)
        )
        contexts = tuple(
            _evidence_context(
                item,
                subject=subject,
                policy=policy,
                now=ctx.now,
                label="signed-profile-" + side,
            )
            for side, item, subject in zip(
                ("baseline", "current"), evidence_items, subjects, strict=True
            )
        )
        # Keep the authority snapshot aligned with the app's frozen Core clock;
        # later signed actions advance both clocks explicitly before requests.
        provider_clock[0] = ctx.now
        context_snapshot_digest = _publish_snapshot(
            provider=provider,
            snapshot_path=snapshot_path,
            signer=signer,
            now=provider_clock[0],
            fields={
                "evidenceContexts": {
                    "records": [item.model_dump(by_alias=True, mode="json") for item in contexts],
                    "currentDigests": [item.context_digest for item in contexts],
                },
                "quantitativeAdministration": {"actions": []},
            },
        )
        assert context_snapshot_digest
        validations = ctx.app.state.external_evidence_validation_store
        validation_issues = tuple(
            validations.issue_after_seal(item.evidence_ref, now=provider_clock[0])
            for item in evidence_items
        )
        assert all(issue.request is not None for issue in validation_issues), [
            issue.verdict.value for issue in validation_issues
        ]
        evidence_records = tuple(
            _record_evidence_validation(
                ctx.app,
                item=item,
                now=provider_clock[0],
                checkpoint_count=3,
            )
            for item in evidence_items
        )

        area = ctx.app.state.work_area_store.get(area_id)
        assert area is not None
        record = _mapping_record(
            subjects=subjects,
            revisions=(epochs[0][1], epochs[1][1]),
            reports=(reports[0], reports[1]),
            evidence_records=evidence_records,
            policy=policy,
            area=area,
            catalog_digest=provider.participants.catalog_authority_port.resolve(
                json.loads((tmp_path / "catalog.json").read_text())["authorityRecordDigest"],
                provider_clock[0],
            ).digest,
            now=provider_clock[0],
        )
        assert record.mapping_digest is not None
        assert (
            record.compatibility_rule_digest == CompatibilityRuleDescriptorV1().canonical_digest()
        )

        with TestClient(ctx.app) as setup:
            feature_response = setup.post(
                f"/v1/sites/site-a/work-areas/{area_id}/measurement-features",
                headers=_reader_headers("signed-profile-line"),
                json={
                    "workAreaId": area_id,
                    "name": "서명 권한 단면 시험선",
                    "line": {
                        "crs": "EPSG:5186",
                        "vertices": [
                            [_ORIGIN_X + 1.5, _ORIGIN_Y - 7.5],
                            [_ORIGIN_X + 45.5, _ORIGIN_Y - 7.5],
                        ],
                    },
                },
            )
        assert feature_response.status_code == 201, feature_response.text
        flow.feature = feature_response.json()["revision"]

        flow.servers = _CoreAndObjectServers(flow.view)
        flow.servers.__enter__()
        flow.http = httpx.Client(
            base_url=flow.servers.core_origin,
            trust_env=False,
            timeout=10,
        )
        flow.now_box[0] = max(ctx.now, datetime.now(UTC).replace(microsecond=0))
        job_ids = []
        for side, (order, revision, subject) in zip(("baseline", "current"), epochs, strict=True):
            asset_ref = _provision_surface_grant(ctx, area_id, revision, extent_m=48.0)
            decision_id = _height_decision_id(
                flow.http, order, subject, key="signed-height-" + side
            )
            job_response = flow.http.post(
                flow.requester_base,
                headers=_reader_headers("signed-profile-job-" + side),
                json={
                    "assetRef": asset_ref,
                    "feature": _feature_ref(flow.feature),
                    "heightDecisionId": decision_id,
                    "sampleSpacingM": 1.0,
                },
            )
            assert job_response.status_code == 200, job_response.text
            job_ids.append(job_response.json()["jobId"])
            dsm = next(
                entry
                for entry in revision.manifest.entries
                if entry.kind is ProcessingArtifactKind.DSM
            )
            flow.source_bytes["sha256:" + dsm.observed_sha256] = ctx.storage.object_bytes(
                _sealed_object_key(ctx, revision)
            )
        for _ in epochs:
            assert _run_surface_worker(flow, flow.servers.core_origin)

        comparison_base = f"/v1/sites/site-a/work-areas/{area_id}/surface-profile-comparisons"
        comparison_body = {
            "baselineJobId": job_ids[0],
            "currentJobId": job_ids[1],
        }
        volume_map_now = _time_after(max(provider_clock[0], flow.now_box[0]))
        volume_map_action = {
            "actionId": "volume-only-mapping-admission",
            "kind": "ADMIT_MAPPING",
            "effectiveAt": _utc(volume_map_now),
            "actorId": "catalog-admin",
            "mapping": {
                "mappingRecordDigest": record.mapping_digest,
                **record.canonical_payload(),
            },
        }
        provider_clock[0] = volume_map_now
        volume_mapping_snapshot_digest = _publish_snapshot(
            provider=provider,
            snapshot_path=snapshot_path,
            signer=signer,
            now=provider_clock[0],
            fields={"quantitativeAdministration": {"actions": [volume_map_action]}},
        )
        assert volume_mapping_snapshot_digest
        flow.now_box[0] = volume_map_now
        blocked = flow.http.post(
            comparison_base,
            headers=_reader_headers("signed-comparison-before-map"),
            json=comparison_body,
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["verdict"] == "BLOCKED"
        assert blocked.json()["result"] is None
        assert "COMPATIBILITY_MAPPING_MISSING" in blocked.json()["reasons"]

        first_dsm = next(
            item
            for item in epochs[0][1].manifest.entries
            if item.kind is ProcessingArtifactKind.DSM
        )
        second_dsm = next(
            item
            for item in epochs[1][1].manifest.entries
            if item.kind is ProcessingArtifactKind.DSM
        )

        map_now = _time_after(max(provider_clock[0], flow.now_box[0]))
        map_action = {
            "actionId": "profile-mapping-admission",
            "kind": "ADMIT_PROFILE_MAPPING",
            "effectiveAt": _utc(map_now),
            "actorId": "catalog-admin",
            "mapping": {"mappingRecordDigest": record.mapping_digest, **record.canonical_payload()},
        }
        provider_clock[0] = map_now
        admitted_snapshot_digest = _publish_snapshot(
            provider=provider,
            snapshot_path=snapshot_path,
            signer=signer,
            now=provider_clock[0],
            fields={"quantitativeAdministration": {"actions": [map_action]}},
        )
        assert admitted_snapshot_digest
        flow.now_box[0] = map_now
        response = flow.http.post(
            comparison_base,
            headers=_reader_headers("signed-comparison-after-map"),
            json=comparison_body,
        )
        assert response.status_code == 200, response.text
        comparison = response.json()
        assert comparison["verdict"] == "ELIGIBLE", comparison["reasons"]
        result = comparison["result"]
        assert len(result["samples"]) == 45
        assert result["validCount"] == 41
        assert result["largestRiseM"] == pytest.approx(2.75)
        assert result["largestDropM"] == pytest.approx(-2.75)
        invalid_columns = {11, 12, 30, 31}
        for index, sample in enumerate(result["samples"]):
            column = index + 1
            if column in invalid_columns:
                assert sample["differenceM"] is None
                assert sample["invalidReason"] == (
                    "BASELINE_UNAVAILABLE" if column in {11, 12} else "CURRENT_UNAVAILABLE"
                )
            else:
                assert sample["invalidReason"] is None
                assert sample["differenceM"] == pytest.approx((column - 23) / 8.0)
        comparison_params = {
            "baseline_job_id": job_ids[0],
            "current_job_id": job_ids[1],
            "decision_id": comparison["decisionId"],
        }
        saved_comparison = flow.http.get(
            comparison_base,
            headers=_reader_headers(),
            params=comparison_params,
        )
        assert saved_comparison.status_code == 200
        assert saved_comparison.json() == comparison
        eligible = ctx.app.state.external_use_decision_store.get_scoped(
            comparison["decisionId"],
            principal=_principal(),
            site_id=subjects[0].site_id,
        )
        assert eligible is not None and eligible.verdict.value == "ELIGIBLE"
        assert eligible.compatibility_mapping_digest == record.mapping_digest
        assert eligible.profile_work_area_id == area_id
        assert len(eligible.evidence_record_digests) == 2

        revoke_at = _time_after(max(eligible.decided_at, flow.now_box[0]))
        revoke_action = {
            "actionId": "profile-mapping-revocation",
            "kind": "REVOKE_PROFILE_MAPPING",
            "effectiveAt": _utc(revoke_at),
            "actorId": "catalog-admin",
            "mappingDigest": record.mapping_digest,
        }
        provider_clock[0] = revoke_at
        revoked_snapshot_digest = _publish_snapshot(
            provider=provider,
            snapshot_path=snapshot_path,
            signer=signer,
            now=provider_clock[0],
            fields={"quantitativeAdministration": {"actions": [revoke_action]}},
        )
        assert revoked_snapshot_digest
        flow.now_box[0] = revoke_at
        withdrawn = flow.http.get(
            comparison_base,
            headers=_reader_headers(),
            params=comparison_params,
        )
        assert withdrawn.status_code == 409, withdrawn.text
        assert withdrawn.json()["reason"] == "PROFILE_COMPARISON_NO_LONGER_ELIGIBLE"
        assert "differenceM" not in withdrawn.text
        retry = flow.http.post(
            comparison_base,
            headers=_reader_headers("signed-comparison-after-map"),
            json=comparison_body,
        )
        assert retry.status_code == 409, retry.text
        assert "differenceM" not in retry.text

        historical = ctx.app.state.external_use_decision_store.resolve_historical_pair(
            organization_id="org-a",
            site_id=subjects[0].site_id,
            decision_id=eligible.decision_id,
            decision_digest=eligible.decision_digest,
        )
        assert historical == eligible
        authority = (
            ctx.app.state.external_relative_volume_mapping_authority.profile_difference_port()
        )
        historical_authority = authority.resolve_historical_for_decision(eligible)
        assert historical_authority is not None
        assert historical_authority.compatibility_mapping_digest == record.mapping_digest
        assert historical_authority.work_area_id == area_id

        flow.close()
        receipt_journals.pop().close()
        provider_box.clear()
        flow = _ReadyFlow(tmp_path / "platform", build_profile_difference_authority=None)
        restarted = flow.ctx
        restarted_provider = provider_box[-1]
        restarted_provider.attach_app(restarted.app)
        assert restarted_provider.status()["status"] == "PROVIDER_CONFIGURED"
        replayed = restarted.app.state.external_use_decision_store.resolve_historical_pair(
            organization_id="org-a",
            site_id=subjects[0].site_id,
            decision_id=eligible.decision_id,
            decision_digest=eligible.decision_digest,
        )
        assert replayed == eligible
        restarted_profile_authority = (
            restarted.app.state.external_relative_volume_mapping_authority.profile_difference_port()
        )
        restarted_authority = restarted_profile_authority.resolve_historical_for_decision(eligible)
        assert restarted_authority is not None
        assert restarted_authority.compatibility_mapping_digest == record.mapping_digest
        assert restarted_authority.work_area_id == area_id
        assert eligible.profile_comparison_binding_digest is not None
        assert (
            restarted.app.state.external_use_evaluator.resolve_eligible_pair_for_execution(
                eligible.decision_id,
                principal=_principal(),
                site_id=subjects[0].site_id,
                observed_crs_digest=record.baseline.observed_crs_digest,
                observed_vertical_reference_digest=record.baseline.observed_vertical_reference_digest,
                baseline_artifact_id=first_dsm.artifact_id,
                baseline_source_sha256="sha256:" + first_dsm.observed_sha256,
                current_artifact_id=second_dsm.artifact_id,
                current_source_sha256="sha256:" + second_dsm.observed_sha256,
                profile_comparison_binding_digest=eligible.profile_comparison_binding_digest,
                profile_work_area_id=area_id,
            )
            is None
        )

        evidence = {
            "schema": "ksi.local-profile-difference-qa-evidence.v1",
            "evidenceClass": "LOCAL_SYNTHETIC_FIXTURE",
            "authorityPath": "signed provider configuration and Core-owned decisions",
            "customerOrFieldAcceptance": False,
            "profileJobsCompleted": len(job_ids),
            "mappingDigest": record.mapping_digest,
            "compatibilityRuleDigest": record.compatibility_rule_digest,
            "policyDigest": policy.policy_digest,
            "comparison": {
                "httpStatus": response.status_code,
                "decisionDigest": eligible.decision_digest,
                "resultDigest": result["comparisonDigest"],
                "sampleCount": len(result["samples"]),
                "validCount": result["validCount"],
                "invalidCount": len(result["samples"]) - result["validCount"],
                "largestRiseM": result["largestRiseM"],
                "largestDropM": result["largestDropM"],
                "savedReadStatus": saved_comparison.status_code,
            },
            "beforeMapping": {
                "httpStatus": blocked.status_code,
                "verdict": blocked.json()["verdict"],
                "reason": "COMPATIBILITY_MAPPING_MISSING",
                "numericResultReleased": False,
                "volumeOnlyMappingAdmissionAccepted": bool(volume_mapping_snapshot_digest),
            },
            "afterRevocation": {
                "savedReadStatus": withdrawn.status_code,
                "reason": withdrawn.json()["reason"],
                "numericResultReleased": False,
                "retryStatus": retry.status_code,
            },
            "history": {
                "decisionReplayedAfterRestart": replayed == eligible,
                "mappingRetainedForHistoricalReplay": restarted_authority is not None,
                "currentNumericUseDenied": True,
            },
            "volumeExecution": "NOT_REQUESTED",
        }
        evidence_path = tmp_path / "signed-profile-lifecycle.json"
        evidence_path.write_text(json.dumps(evidence, sort_keys=True, indent=2), encoding="utf-8")
        evidence_path.chmod(0o600)
    finally:
        flow.close()
        for receipt_journal in receipt_journals:
            receipt_journal.close()
