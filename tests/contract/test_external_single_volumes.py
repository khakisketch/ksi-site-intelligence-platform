"""External single-epoch volume ledger: exact authority, fenced reports, replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from external_single_volume_fixture import (
    _NOW,
    _authority,
    _AuthorityPort,
    _binding,
    _digest,
    _execution_policy,
    _issue_and_claim,
    _metrics,
    _payload,
    _principal,
    _store,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    mount_auth,
)
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeInputCapability,
    ExternalRelativeVolumeVerdict,
)
from ksi_core.domains.external.quantity.external_single_volumes import (
    ExternalSingleVolumeExecutionAuthority,
    ExternalSingleVolumeObservedReportInput,
    ExternalSingleVolumeRecoveryError,
    ExternalSingleVolumeStore,
    SingleVolumeWorkerLaunchMaterialResolver,
    build_external_single_volume_router,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_validation_policy import PolicySelection, PolicySelectionStatus
from ksi_core.leasing import LeaseFence
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    PolicyStatus,
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence import (
    EvidenceCoreVerdict,
    ExternalEvidenceMeasurementPayloadV1,
    ExternalEvidenceRecordV1,
)
from ksi_event_contracts.external_evidence_context import (
    ExternalEvidenceMeasurementContextV1,
    ExternalIndependenceAttestationV1,
)
from ksi_event_contracts.external_relative_volume import (
    ExternalVolumeInputBindingV1,
)

_OPERATOR_TOKEN = "single-volume-operator"  # noqa: S105 -- deterministic test token
_WORKER_TOKEN = "single-volume-worker"  # noqa: S105 -- deterministic test token


def test_authority_snapshot_round_trips_and_rejects_non_canonical_values() -> None:
    authority = _authority()
    snapshot = authority.snapshot_payload()
    assert ExternalSingleVolumeExecutionAuthority.from_snapshot(snapshot) == authority
    widened = json.loads(json.dumps(snapshot))
    widened["maximumZoneAreaM2"] = 100_000
    with pytest.raises(ValueError, match="non-canonical float"):
        ExternalSingleVolumeExecutionAuthority.from_snapshot(widened)
    extra = {**snapshot, "baseline": snapshot["target"]}
    with pytest.raises(ValueError, match="invalid object shape"):
        ExternalSingleVolumeExecutionAuthority.from_snapshot(extra)
    with pytest.raises(ValueError, match="exactly one evidence"):
        replace(authority, evidence_record_digests=(_digest("a"), _digest("b")))


def test_issue_is_durable_idempotent_and_conflicts_on_a_changed_decision(tmp_path: Path) -> None:
    port = _AuthorityPort(_authority())
    store = _store(tmp_path, port)
    first = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="key-a",
        now=_NOW,
    )
    assert first.verdict is ExternalRelativeVolumeVerdict.ISSUED and first.record is not None
    request = first.record.request
    assert request.request_id.startswith("external-single-volume-")
    assert request.contract_version == "external-single-volume-request.v1"
    assert request.target == port.authority.target
    retry = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="key-a",
        now=_NOW,
    )
    assert retry.verdict is ExternalRelativeVolumeVerdict.ALREADY_ISSUED
    alias = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="key-b",
        now=_NOW,
    )
    assert alias.verdict is ExternalRelativeVolumeVerdict.ALREADY_ISSUED
    assert alias.record is not None and alias.record.request == request
    conflict = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-other",
        idempotency_key="key-a",
        now=_NOW,
    )
    assert conflict.verdict is ExternalRelativeVolumeVerdict.IDEMPOTENCY_CONFLICT
    assert [raw["kind"] for raw in store.journal_records()] == [
        "external-single-volume-issued",
        "external-single-volume-idempotency-bound",
    ]
    port.revoked = True
    assert (
        store.issue(
            principal=_principal(),
            current_work_order_id="work-current",
            decision_ref="decision-a",
            idempotency_key="key-new",
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
    )


def test_fenced_report_is_accepted_with_the_exact_boundary_base_bound(tmp_path: Path) -> None:
    port = _AuthorityPort(_authority())
    store = _store(tmp_path, port)
    request_id, request_digest, fence = _issue_and_claim(store)
    reported = store.record_observed_report(
        request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=fence,
        observed=ExternalSingleVolumeObservedReportInput(
            payload=_payload(request_digest, port.authority), computed_at=_NOW
        ),
        now=_NOW,
    )
    assert reported.verdict is ExternalRelativeVolumeVerdict.REPORTED, reported.detail
    assert reported.record is not None and reported.record.report is not None
    report = reported.record.report
    assert report.report_id.startswith("external-single-volume-report-")
    assert report.contract_version == "external-single-volume-report.v1"
    resolved = store.resolve_historical_report_ref(
        report.report_id, organization_id="org-a", now=_NOW
    )
    assert resolved is not None and resolved.report == report
    assert store.report_refs_for_site("site-a", organization_id="org-a") == (report.report_id,)


@pytest.mark.parametrize(
    ("metrics_overrides", "target_digest", "detail"),
    [
        ({"uncertainty_m3": 99.0}, None, "boundary-base bound"),
        ({"uncertainty_m3": None}, None, "boundary-base bound"),
        ({"boundary_samples": 5}, None, "boundary coverage"),
        ({}, "wrong", "sealed request authority"),
    ],
)
def test_report_that_breaks_the_sealed_authority_is_rejected(
    tmp_path: Path, metrics_overrides: dict[str, Any], target_digest: str | None, detail: str
) -> None:
    port = _AuthorityPort(_authority())
    store = _store(tmp_path, port)
    request_id, request_digest, fence = _issue_and_claim(store)
    metrics = _metrics(port.authority, **metrics_overrides)
    result = store.record_observed_report(
        request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=fence,
        observed=ExternalSingleVolumeObservedReportInput(
            payload=_payload(
                request_digest,
                port.authority,
                metrics,
                target_dsm_digest=_digest(target_digest) if target_digest else None,
            ),
            computed_at=_NOW,
        ),
        now=_NOW,
    )
    assert result.verdict is ExternalRelativeVolumeVerdict.INVALID_REPORT
    assert result.detail is not None and detail in result.detail


def test_unknown_target_rmse_requires_unknown_uncertainty(tmp_path: Path) -> None:
    port = _AuthorityPort(_authority(target_rmse_m=None))
    store = _store(tmp_path, port)
    request_id, request_digest, fence = _issue_and_claim(store)
    rejected = store.record_observed_report(
        request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=fence,
        observed=ExternalSingleVolumeObservedReportInput(
            payload=_payload(
                request_digest, port.authority, _metrics(port.authority, uncertainty_m3=1.0)
            ),
            computed_at=_NOW,
        ),
        now=_NOW,
    )
    assert rejected.verdict is ExternalRelativeVolumeVerdict.INVALID_REPORT
    accepted = store.record_observed_report(
        request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=fence,
        observed=ExternalSingleVolumeObservedReportInput(
            payload=_payload(request_digest, port.authority), computed_at=_NOW
        ),
        now=_NOW,
    )
    assert accepted.verdict is ExternalRelativeVolumeVerdict.REPORTED


def test_stale_fence_and_incomplete_failure(tmp_path: Path) -> None:
    port = _AuthorityPort(_authority())
    store = _store(tmp_path, port)
    request_id, request_digest, fence = _issue_and_claim(store)
    stale = LeaseFence(fence.worker_instance_id, str(uuid4()), fence.lease_generation)
    denied = store.record_observed_report(
        request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=stale,
        observed=ExternalSingleVolumeObservedReportInput(
            payload=_payload(request_digest, port.authority), computed_at=_NOW
        ),
        now=_NOW,
    )
    assert denied.verdict is ExternalRelativeVolumeVerdict.STALE_LEASE_ACQUISITION
    failed = store.record_incomplete_failure(
        request_id,
        organization_id="org-a",
        principal_id="worker-principal",
        fence=fence,
        reason="BOUNDARY_SAMPLES_INSUFFICIENT",
        now=_NOW,
    )
    assert failed.verdict is ExternalRelativeVolumeVerdict.FAILED
    assert failed.record is not None
    assert failed.record.failure_reason == "BOUNDARY_SAMPLES_INSUFFICIENT"


def test_replay_restores_records_and_rejects_a_forged_issue(tmp_path: Path) -> None:
    port = _AuthorityPort(_authority())
    store = _store(tmp_path, port)
    request_id, request_digest, fence = _issue_and_claim(store)
    assert (
        store.record_observed_report(
            request_id,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=fence,
            observed=ExternalSingleVolumeObservedReportInput(
                payload=_payload(request_digest, port.authority), computed_at=_NOW
            ),
            now=_NOW,
        ).verdict
        is ExternalRelativeVolumeVerdict.REPORTED
    )
    before = store.get(request_id, organization_id="org-a")
    store._journal.close()  # noqa: SLF001 - reopen the same durable journal.

    reopened = _store(tmp_path, port)
    assert reopened.get(request_id, organization_id="org-a") == before
    reopened._journal.close()  # noqa: SLF001

    path = tmp_path / "external-single-volumes.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    events[0]["authority"]["targetRmseM"] = 0.5
    payload = {key: value for key, value in events[0].items() if key != "eventDigest"}
    events[0]["eventDigest"] = "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    path.write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )
    with pytest.raises(ExternalSingleVolumeRecoveryError):
        _store(tmp_path, port)


# -- HTTP worker input -----------------------------------------------------------------


class _Registry:
    def __init__(
        self,
        policy: ExternalValidationPolicyV1,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self.policy = policy
        self.coordinator = coordinator
        self.subjects: tuple[SealedExternalSubjectV1, ...] = ()

    def select_for_use(
        self, use: str, subjects: tuple[SealedExternalSubjectV1, ...]
    ) -> PolicySelection:
        assert use == "SINGLE_VOLUME" and subjects == self.subjects
        return PolicySelection(PolicySelectionStatus.ACTIVE, self.policy, None)

    def resolve(self, digest: str) -> PolicySelection:
        if digest != self.policy.policy_digest:
            return PolicySelection(PolicySelectionStatus.POLICY_NOT_FOUND, None, "POLICY_NOT_FOUND")
        return PolicySelection(PolicySelectionStatus.ACTIVE, self.policy, None)

    def locally_current_use_permitted(
        self, digest: str, *, use: str, subjects: tuple[SealedExternalSubjectV1, ...], at: datetime
    ) -> bool:
        del at
        return (
            digest == self.policy.policy_digest
            and use == "SINGLE_VOLUME"
            and subjects == self.subjects
        )


class _Evidence:
    def __init__(
        self,
        records: dict[str, tuple[ExternalEvidenceRecordV1, ExternalEvidenceMeasurementContextV1]],
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self.records = records
        self.coordinator = coordinator

    def record_for_current_use(
        self, digest: str, *, subject: SealedExternalSubjectV1, policy_digest: str
    ) -> tuple[ExternalEvidenceRecordV1, ExternalEvidenceMeasurementContextV1] | None:
        value = self.records.get(digest)
        if (
            value is None
            or value[0].subject_digest != subject.canonical_digest()
            or value[0].policy_digest != policy_digest
        ):
            return None
        return value

    record_for_locally_current_use = record_for_current_use


def _validation_policy() -> ExternalValidationPolicyV1:
    envelope = ResourceEnvelopeV1(
        max_input_bytes=1_024,
        max_streamed_bytes=1_024,
        max_tiff_directories=4,
        max_tiff_entries=32,
        max_pixels=1_000,
        max_bands=4,
        max_blocks=64,
        max_decompressed_bytes=8_192,
        max_sample_bytes=8_192,
        max_geometry_vertices=64,
        max_cpu_seconds=2.0,
        max_memory_bytes=16_384,
        max_workspace_bytes=16_384,
        max_output_bytes=16_384,
        max_tenant_concurrency=1,
        max_queue_depth=4,
        max_deadline_seconds=60.0,
        lease_duration_seconds=5.0,
        max_retry_attempts=1,
    ).sealed()
    return ExternalValidationPolicyV1(
        policy_id="validation-policy-a",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=_digest("policy-parser"),
        grammar_digest=_digest("policy-grammar"),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=_digest("validation-policy-authority"),
        inspection_rule_ids=(),
        evidence_rule_ids=("CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",),
        compatibility_mapping_digests=(),
        synthetic_test_only=True,
    ).sealed()


def _evidence(
    binding: ExternalVolumeInputBindingV1, policy: ExternalValidationPolicyV1, *, attested: bool
) -> tuple[ExternalEvidenceRecordV1, ExternalEvidenceMeasurementContextV1]:
    assert policy.policy_digest is not None
    manifest_digest = _digest("evidence-manifest")
    payload = ExternalEvidenceMeasurementPayloadV1(
        validation_id="validation-target",
        evidence_manifest_digest=manifest_digest,
        target_dsm_observed_sha256=binding.observed_sha256,
        policy_digest=policy.policy_digest,
        measured_checkpoint_count=3,
        mean_error_m=0.01,
        mae_m=0.04,
        rmse_m=0.05,
        max_abs_error_m=0.08,
        measured_at=_NOW,
    )
    record = ExternalEvidenceRecordV1(
        evidence_record_id="record-target",
        validation_id="validation-target",
        subject_digest=binding.subject.canonical_digest(),
        evidence_manifest_digest=manifest_digest,
        target_dsm_observed_sha256=binding.observed_sha256,
        policy_digest=policy.policy_digest,
        measurement_payload=payload,
        core_verdict=EvidenceCoreVerdict.VALIDATED,
        core_recorded_at=_NOW,
    ).sealed()
    attestation = (
        ExternalIndependenceAttestationV1(
            attestation_id="attestation-target",
            evidence_manifest_digest=manifest_digest,
            subject_digest=binding.subject.canonical_digest(),
            target_dsm_observed_sha256=binding.observed_sha256,
            confirmed_by_actor_id="independent-validator",
            confirmed_at=_NOW - timedelta(hours=1),
            reconstruction_exclusion_basis="Independent survey outside reconstruction.",
            synthetic_test_only=True,
        ).sealed()
        if attested
        else None
    )
    context = ExternalEvidenceMeasurementContextV1(
        context_id="context-target",
        subject=binding.subject,
        evidence_manifest_digest=manifest_digest,
        evidence_observed_sha256=_digest("evidence-bytes"),
        evidence_observed_size_bytes=10,
        target_dsm_artifact_id=binding.dsm_artifact_id,
        target_dsm_observed_sha256=binding.observed_sha256,
        policy_digest=policy.policy_digest,
        measurement_execution_manifest_digest=_digest("measurement-manifest"),
        rule_id="CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",
        csv_horizontal_crs="EPSG:5186",
        csv_vertical_reference_digest=_digest("csv-vertical"),
        minimum_checkpoint_count=3,
        maximum_checkpoint_count=10,
        maximum_rmse_m=0.5,
        maximum_abs_mean_error_m=0.2,
        maximum_abs_error_m=1.0,
        independent_attestation=attestation,
        authorized_actor_ids=("independent-validator",),
        active_from=_NOW - timedelta(minutes=1),
        active_until=_NOW + timedelta(minutes=10),
        synthetic_test_only=True,
    ).sealed()
    return record, context


def _launch_client(
    tmp_path: Path, *, attested: bool = True
) -> tuple[TestClient, ExternalSingleVolumeStore, str]:
    policy = _validation_policy()
    assert policy.policy_digest is not None
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "single-volume-work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_id == "site-a" and organization_id == "org-a"
        ),
        work_areas_exist=lambda _site_id, _work_area_ids: True,
    )
    order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="Single volume fixture",
        work_area_ids=["work-area-a"],
        schedule_id=None,
        actor="operator-a",
        now=_NOW,
    )
    evidence_record, context = _evidence(_binding(order.work_order_id), policy, attested=attested)
    assert evidence_record.evidence_record_digest is not None
    authority = _authority(
        work_order_id=order.work_order_id,
        evidence_digest=evidence_record.evidence_record_digest,
        validation_policy_digest=policy.policy_digest,
        execution_policy=_execution_policy(
            resource_envelope_digest=policy.resource_envelope_digest
        ),
    )
    port = _AuthorityPort(authority)
    registry = _Registry(policy, port.currentness_coordinator)
    registry.subjects = (authority.target.subject,)
    resolver = SingleVolumeWorkerLaunchMaterialResolver(
        policy_registry=cast(Any, registry),
        evidence_validations=cast(
            Any,
            _Evidence(
                {evidence_record.evidence_record_digest: (evidence_record, context)},
                port.currentness_coordinator,
            ),
        ),
        currentness_coordinator=port.currentness_coordinator,
    )
    store = _store(tmp_path, port, resolver=resolver)
    app = FastAPI()
    worker = Principal("worker-principal", PrincipalKind.PROCESSING_WORKER, None, None, "org-a")
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(_OPERATOR_TOKEN.encode()).hexdigest(),
                    principal=_principal(),
                ),
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(_WORKER_TOKEN.encode()).hexdigest(),
                    principal=worker,
                ),
            ]
        ),
    )

    def capabilities(
        record: Any,
        material: Any,
        *,
        fence: LeaseFence,
        principal: Principal,
        now: datetime,
    ) -> tuple[ExternalRelativeVolumeInputCapability, ExternalRelativeVolumeInputCapability]:
        del record, fence, principal, now
        assert material.evidence_record == evidence_record
        return (
            ExternalRelativeVolumeInputCapability(
                role="TARGET_DSM",
                download_url="https://storage.invalid/target",
                required_headers={},
                expires_at=_NOW + timedelta(minutes=5),
            ),
            ExternalRelativeVolumeInputCapability(
                role="CHECKPOINT_CSV",
                download_url="https://storage.invalid/checkpoints",
                required_headers={},
                expires_at=_NOW + timedelta(minutes=5),
            ),
        )

    app.include_router(
        build_external_single_volume_router(
            store,
            input_capability_issuer=capabilities,
            work_orders=work_orders,
            clock=lambda: _NOW,
        )
    )
    return TestClient(app), store, order.work_order_id


def _auth(token: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **extra}


def test_http_issue_lease_input_and_report_round_trip(tmp_path: Path) -> None:
    client, store, work_order_id = _launch_client(tmp_path)
    issued = client.post(
        f"/v1/observation-work-orders/{work_order_id}/single-volume-requests",
        headers=_auth(_OPERATOR_TOKEN, **{"Idempotency-Key": "http-single"}),
        json={"decisionRef": "decision-a"},
    )
    assert issued.status_code == 201, issued.text
    request_ref = issued.json()["request"]["requestRef"]
    listed = client.get(
        f"/v1/observation-work-orders/{work_order_id}/single-volume-requests",
        headers=_auth(_OPERATOR_TOKEN),
    )
    assert [item["requestRef"] for item in listed.json()["items"]] == [request_ref]
    pending = client.get(
        "/v1/internal/external-validation/single-volumes", headers=_auth(_WORKER_TOKEN)
    )
    assert [item["requestRef"] for item in pending.json()["items"]] == [request_ref]
    initial = LeaseFence(str(uuid4()), str(uuid4()), 0)
    lease = client.post(
        f"/v1/internal/external-validation/single-volumes/{request_ref}/lease",
        headers=_auth(_WORKER_TOKEN),
        json={
            "workerInstanceId": initial.worker_instance_id,
            "leaseAcquisitionId": initial.lease_acquisition_id,
            "leaseGeneration": 0,
        },
    )
    assert lease.status_code == 201, lease.text
    fence = lease.json()["fence"]
    fence_headers = {
        "X-KSI-Worker-Instance-Id": fence["workerInstanceId"],
        "X-KSI-Lease-Acquisition-Id": fence["leaseAcquisitionId"],
        "X-KSI-Lease-Generation": str(fence["leaseGeneration"]),
    }
    worker_input = client.get(
        f"/v1/internal/external-validation/single-volumes/{request_ref}/input",
        headers=_auth(_WORKER_TOKEN, **fence_headers),
    )
    assert worker_input.status_code == 200, worker_input.text
    body = worker_input.json()["input"]
    assert body["request"]["contractVersion"] == "external-single-volume-request.v1"
    assert body["executionPolicy"]["baseSurfaceMethod"] == "BOUNDARY_LINEAR_INTERPOLATION_V1"
    assert [item["role"] for item in body["inputs"]] == ["TARGET_DSM", "CHECKPOINT_CSV"]
    assert body["evidenceRecord"]["measurementPayload"]["rmseM"] == 0.05

    record = store.get(request_ref, organization_id="org-a")
    assert record is not None and record.request.request_digest is not None
    payload = _payload(record.request.request_digest, record.authority)
    report = client.post(
        f"/v1/internal/external-validation/single-volumes/{request_ref}/report",
        headers=_auth(_WORKER_TOKEN, **fence_headers),
        json={
            "payload": payload.model_dump(by_alias=True, mode="json"),
            "computedAt": "2026-09-17T00:00:00Z",
        },
    )
    assert report.status_code == 201, report.text
    assert report.json()["request"]["status"] == "SUCCEEDED"
    assert report.json()["request"]["reportRef"].startswith("external-single-volume-report-")


def test_http_input_is_withheld_without_attested_evidence(tmp_path: Path) -> None:
    client, _store_, work_order_id = _launch_client(tmp_path, attested=False)
    issued = client.post(
        f"/v1/observation-work-orders/{work_order_id}/single-volume-requests",
        headers=_auth(_OPERATOR_TOKEN, **{"Idempotency-Key": "http-unattested"}),
        json={"decisionRef": "decision-a"},
    )
    request_ref = issued.json()["request"]["requestRef"]
    initial = LeaseFence(str(uuid4()), str(uuid4()), 0)
    fence = client.post(
        f"/v1/internal/external-validation/single-volumes/{request_ref}/lease",
        headers=_auth(_WORKER_TOKEN),
        json={
            "workerInstanceId": initial.worker_instance_id,
            "leaseAcquisitionId": initial.lease_acquisition_id,
            "leaseGeneration": 0,
        },
    ).json()["fence"]
    response = client.get(
        f"/v1/internal/external-validation/single-volumes/{request_ref}/input",
        headers=_auth(
            _WORKER_TOKEN,
            **{
                "X-KSI-Worker-Instance-Id": fence["workerInstanceId"],
                "X-KSI-Lease-Acquisition-Id": fence["leaseAcquisitionId"],
                "X-KSI-Lease-Generation": str(fence["leaseGeneration"]),
            },
        ),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "AUTHORITY_UNAVAILABLE"
