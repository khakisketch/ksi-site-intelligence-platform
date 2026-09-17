"""Durable external result review and planning-only proposal authority tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_reobservation_proposals import (
    CoreExternalReobservationProposalAuthorityPort,
    ExternalReobservationProposalRecoveryError,
    ExternalReobservationProposalService,
    ExternalReobservationProposalStore,
    ExternalReobservationProposalUnavailableError,
    build_external_reobservation_proposal_router,
    verify_external_reobservation_organization_graph,
)
from ksi_core.external_result_reviews import (
    ExternalResultReviewRecoveryError,
    ExternalResultReviewSource,
    ExternalResultReviewSourceV1,
    ExternalResultReviewStore,
)
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore
from ksi_core.work_areas import WorkAreaStore
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    ExternalPairUseDecisionV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeExecutionPolicyV1,
    ExternalRelativeVolumeMeasurementPayloadV1,
    ExternalRelativeVolumeReportV1,
    ExternalRelativeVolumeRequestV1,
    ExternalVolumeInputBindingV1,
    ExternalVolumeMetricsV1,
    ExternalVolumeZoneSnapshotV1,
)
from ksi_event_contracts.external_reobservation import (
    ExternalReobservationApprovalInputV1,
    ExternalWorkAreaSnapshotV1,
)
from ksi_event_contracts.external_result_review import (
    ExternalReobservationProposalV1,
    ExternalResultReviewAuthorityV1,
    ExternalResultReviewReceiptV1,
    external_reobservation_proposal_wire_dict,
    external_result_review_receipt_wire_dict,
)
from ksi_event_contracts.observation_work_order import TemporalCoherencePolicy
from ksi_mission_contracts.models import SiteFrame

_NOW = datetime(2026, 9, 9, 12, tzinfo=UTC)
_TOKEN = "external-proposal-admin"  # noqa: S105 -- deterministic test credential


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _event_digest(raw: dict[str, object]) -> str:
    payload = {key: value for key, value in raw.items() if key != "eventDigest"}
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _principal(*, organization_id: str = "org-a", principal_id: str = "operator-a") -> Principal:
    return Principal(
        principal_id=principal_id,
        kind=PrincipalKind.OPERATOR,
        role=Role.ADMIN,
        device_id=None,
        organization_id=organization_id,
    )


def _token_record() -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(_TOKEN.encode("utf-8")).hexdigest(),
        principal=_principal(),
    )


def _subject(work_order_id: str, label: str) -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id=work_order_id,
        submission_id=f"submission-{label}",
        revision=1,
        submission_digest=_digest(f"submission-{label}"),
        manifest_digest=_digest(f"manifest-{label}"),
    )


def _binding(work_order_id: str, label: str, hour: int) -> ExternalVolumeInputBindingV1:
    return ExternalVolumeInputBindingV1(
        subject=_subject(work_order_id, label),
        inspection_report_digest=_digest(f"inspection-{label}"),
        dsm_artifact_id=f"dsm-{label}",
        observed_sha256=_digest(f"dsm-bytes-{label}"),
        observed_size_bytes=10,
        observed_crs_digest=_digest("crs"),
        observed_vertical_reference_digest=_digest("vertical"),
        captured_from=_NOW + timedelta(hours=hour),
        captured_to=_NOW + timedelta(hours=hour + 1),
    )


def _sealed_source(
    *,
    source_work_order_id: str,
    work_area_id: str,
    polygon: dict[str, object],
) -> ExternalResultReviewSourceV1:
    zone = ExternalVolumeZoneSnapshotV1(
        organization_id="org-a",
        site_id="site-a",
        work_area_id=work_area_id,
        polygon=polygon,
        crs="EPSG:5186",
        observed_crs_digest=_digest("crs"),
        analysis_vertical_reference_digest=_digest("vertical"),
    ).sealed()
    policy = ExternalRelativeVolumeExecutionPolicyV1(
        policy_id="volume-policy-a",
        version=1,
        algorithm_build_digest=_digest("algorithm"),
        config_digest=_digest("config"),
        threshold_m=0.1,
        minimum_common_valid_fraction=0.8,
        uncertainty_method="INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1",
        resource_envelope_digest=_digest("resources"),
        authority_record_digest=_digest("policy-authority"),
        synthetic_test_only=True,
    ).sealed()
    baseline = _binding("work-baseline", "baseline", 0)
    current = _binding(source_work_order_id, "current", 2)
    evidence_digests = (_digest("evidence-baseline"), _digest("evidence-current"))
    validation_policy_digest = _digest("validation-policy")
    decision = ExternalPairUseDecisionV1(
        decision_id="decision-a",
        baseline_subject=baseline.subject,
        baseline_subject_digest=baseline.subject.canonical_digest(),
        current_subject=current.subject,
        current_subject_digest=current.subject.canonical_digest(),
        use="RELATIVE_VOLUME",
        policy_digest=validation_policy_digest,
        baseline_inspection_report_digest=baseline.inspection_report_digest,
        current_inspection_report_digest=current.inspection_report_digest,
        evidence_record_digests=evidence_digests,
        zone=zone.to_zone_reference(),
        compatibility_mapping_digest=_digest("compatibility-map"),
        verdict=DecisionVerdict.ELIGIBLE,
        reasons=("ELIGIBLE",),
        remediations=("NONE",),
        decided_at=_NOW,
    ).sealed()
    authority = ExternalResultReviewAuthorityV1(
        organization_id="org-a",
        site_id="site-a",
        current_work_order_id=source_work_order_id,
        decision_id="decision-a",
        decision_digest=decision.decision_digest or "",
        compatibility_mapping_digest=_digest("compatibility-map"),
        baseline=baseline,
        current=current,
        evidence_record_digests=evidence_digests,
        validation_policy_digest=validation_policy_digest,
        zone_snapshot=zone,
        execution_policy=policy,
        authorized_actor_ids=("operator-a",),
        # The route uses the production wall clock; the explicit ``live``
        # switch below controls revocation in these deterministic tests.
        valid_from=_NOW - timedelta(days=1),
        valid_until=_NOW + timedelta(days=1),
        historical_authority_digest=_digest("historical-authority"),
        baseline_rmse_m=0.3,
        current_rmse_m=0.4,
        maximum_zone_cell_count=1_000,
        maximum_zone_area_m2=1_000.0,
        synthetic_test_only=True,
    ).sealed()
    request = ExternalRelativeVolumeRequestV1(
        request_id="relative-volume-request-a",
        current_work_order_id=source_work_order_id,
        decision_id=authority.decision_id,
        decision_digest=authority.decision_digest,
        baseline=baseline,
        current=current,
        evidence_record_digests=authority.evidence_record_digests,
        validation_policy_digest=authority.validation_policy_digest,
        execution_policy_digest=policy.policy_digest or "",
        zone_snapshot=zone,
        issued_at=_NOW,
        idempotency_key="relative-volume-request-key-a",
    ).sealed()
    payload = ExternalRelativeVolumeMeasurementPayloadV1(
        request_digest=request.request_digest or "",
        decision_digest=decision.decision_digest or "",
        baseline_dsm_digest=baseline.observed_sha256,
        current_dsm_digest=current.observed_sha256,
        zone_snapshot_digest=zone.canonical_digest(),
        execution_policy_digest=policy.canonical_digest(),
        algorithm_build_digest=policy.algorithm_build_digest,
        config_digest=policy.config_digest,
        metrics=ExternalVolumeMetricsV1(
            zone_cell_count=10,
            common_valid_cell_count=10,
            zone_area_m2=10.0,
            measured_area_m2=10.0,
            common_valid_fraction=1.0,
            cut_m3=1.0,
            fill_m3=5.0,
            net_m3=4.0,
            threshold_m=policy.threshold_m,
            uncertainty_m3=5.0,
            uncertainty_note="independent epoch RMSE bound",
        ),
    )
    report = ExternalRelativeVolumeReportV1(
        report_id="relative-volume-report-a",
        request_id=request.request_id,
        request_digest=request.request_digest or "",
        payload=payload,
        worker_instance_id=str(UUID("123e4567-e89b-42d3-a456-426614174000")),
        lease_acquisition_id=str(UUID("123e4567-e89b-42d3-a456-426614174001")),
        lease_generation=1,
        computed_at=_NOW,
        reported_at=_NOW,
    ).sealed()
    return ExternalResultReviewSourceV1(
        report_ref="report-ref-a",
        request=request,
        report=report,
        authority=authority,
        decision=decision,
    )


class _SyntheticSourcePort:
    """Only a typed synthetic source fixture; production stays closed by default."""

    def __init__(self) -> None:
        self.source: ExternalResultReviewSourceV1 | None = None
        self.live = True
        self.current_resolutions = 0
        self.historical_not_after: datetime | None = None
        self.historical_evaluations: list[datetime] = []

    def resolve_current(
        self,
        *,
        organization_id: str,
        report_ref: str,
        principal: Principal,
        evaluated_at: datetime,
    ) -> ExternalResultReviewSourceV1 | None:
        self.current_resolutions += 1
        source = self.source
        if (
            source is None
            or not self.live
            or organization_id != source.authority.organization_id
            or report_ref != source.report_ref
            or principal.organization_id != organization_id
            or principal.principal_id not in source.authority.authorized_actor_ids
            or not source.authority.is_active_at(evaluated_at)
        ):
            return None
        return source

    def resolve_historical(
        self,
        *,
        organization_id: str,
        report_ref: str,
        report_digest: str,
        evaluated_at: datetime,
    ) -> ExternalResultReviewSourceV1 | None:
        self.historical_evaluations.append(evaluated_at)
        source = self.source
        if (
            source is None
            or (self.historical_not_after is not None and evaluated_at > self.historical_not_after)
            or organization_id != source.authority.organization_id
            or report_ref != source.report_ref
            or report_digest != source.report.report_digest
        ):
            return None
        return source

    def is_current(
        self, source: ExternalResultReviewSource, *, principal: Principal, evaluated_at: datetime
    ) -> bool:
        return bool(
            self.live
            and source == self.source
            and source.authority.is_active_at(evaluated_at)
            and principal.organization_id == source.authority.organization_id
            and principal.principal_id in source.authority.authorized_actor_ids
        )


@dataclass
class _Harness:
    coordinator: ExternalAuthorityCurrentnessCoordinator
    source_port: _SyntheticSourcePort
    sites: SiteStore
    work_areas: WorkAreaStore
    reviews: ExternalResultReviewStore
    proposals: ExternalReobservationProposalStore
    work_orders: ObservationWorkOrderStore
    authority_port: CoreExternalReobservationProposalAuthorityPort
    service: ExternalReobservationProposalService
    source: ExternalResultReviewSourceV1


def _approval_input(
    proposal: ExternalReobservationProposalV1,
) -> ExternalReobservationApprovalInputV1:
    authority = proposal.approval_authority()
    return ExternalReobservationApprovalInputV1(
        organization_id=authority.organization_id,
        site_id=authority.site_id,
        source_work_order_id=authority.source_work_order_id,
        proposal_id=authority.proposal_id,
        proposal_version=authority.proposal_version,
        proposal_digest=authority.proposal_digest,
        report_digest=authority.report_digest,
        decision_digest=authority.decision_digest,
        zone_digest=authority.zone_digest,
        evidence_digests=authority.evidence_digests,
    ).sealed()


def _harness(tmp_path: Path) -> _Harness:
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    sites = SiteStore(DurableJournal(tmp_path / "sites.jsonl"), coordinator=coordinator)
    registered_site = sites.register(
        "site-a",
        "Site A",
        SiteFrame(
            crs="EPSG:5186",
            vertical_datum="LOCAL",
            unit="meter",
            transform_version="v1",
        ),
        organization_id="org-a",
        actor="operator-a",
        now=_NOW - timedelta(hours=1),
    )
    assert registered_site.record is not None
    work_areas = WorkAreaStore(
        DurableJournal(tmp_path / "work-areas.jsonl"),
        site_exists=lambda site_id: sites.get(site_id) is not None,
        coordinator=coordinator,
    )
    polygon: dict[str, object] = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [0.0, 0.0]]],
    }
    registered_area = work_areas.register(
        "site-a",
        name="Measured zone",
        polygon=polygon,
        crs="EPSG:5186",
        supersedes=None,
        actor="operator-a",
        now=_NOW - timedelta(minutes=50),
    )
    assert registered_area.work_area is not None
    source_port = _SyntheticSourcePort()
    reviews = ExternalResultReviewStore(
        DurableJournal(tmp_path / "reviews.jsonl"),
        source_port=source_port,
        coordinator=coordinator,
    )
    proposals = ExternalReobservationProposalStore(
        DurableJournal(tmp_path / "proposals.jsonl"), coordinator=coordinator
    )
    authority_port = CoreExternalReobservationProposalAuthorityPort(
        reviews=reviews,
        proposals=proposals,
        sites=sites,
        work_areas=work_areas,
        coordinator=coordinator,
    )
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            sites.get_scoped(site_id, organization_id) is not None
        ),
        work_areas_exist=lambda site_id, work_area_ids: all(
            (area := work_areas.get(work_area_id)) is not None
            and area.site_id == site_id
            and area.status.value == "ACTIVE"
            for work_area_id in work_area_ids
        ),
        external_reobservation_authority_port=authority_port,
    )
    source_order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="Original observed work",
        work_area_ids=[registered_area.work_area.work_area_id],
        schedule_id=None,
        temporal_policy=TemporalCoherencePolicy(max_capture_span_seconds=600),
        actor="operator-a",
        now=_NOW - timedelta(minutes=40),
    )
    source = _sealed_source(
        source_work_order_id=source_order.work_order_id,
        work_area_id=registered_area.work_area.work_area_id,
        polygon=polygon,
    )
    source_port.source = source
    reviewed = reviews.review(
        organization_id="org-a",
        report_ref=source.report_ref,
        principal=_principal(),
        evaluated_at=_NOW,
    )
    assert reviewed.report_ref == source.report_ref
    service = ExternalReobservationProposalService(
        reviews=reviews,
        proposals=proposals,
        sites=sites,
        work_areas=work_areas,
        work_orders=work_orders,
        authority_port=authority_port,
        coordinator=coordinator,
    )
    return _Harness(
        coordinator=coordinator,
        source_port=source_port,
        sites=sites,
        work_areas=work_areas,
        reviews=reviews,
        proposals=proposals,
        work_orders=work_orders,
        authority_port=authority_port,
        service=service,
        source=source,
    )


def test_human_route_creates_grounded_proposal_and_one_kernel_successor(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    app = FastAPI()
    mount_auth(app, AuthRegistry([_token_record()]))
    app.include_router(
        build_external_reobservation_proposal_router(harness.service, clock=lambda: _NOW)
    )
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {_TOKEN}", "Idempotency-Key": "proposal-key-a"}

    created = client.post(
        "/v1/external-reobservation-proposals",
        headers=headers,
        json={
            "reportRef": harness.source.report_ref,
            "targetWorkAreaIds": [harness.source.authority.zone_snapshot.work_area_id],
            "reason": "HUMAN_REVIEW_REQUIRED",
        },
    )

    assert created.status_code == 201
    proposal = created.json()["proposal"]
    assert proposal["reportRef"] == harness.source.report_ref
    assert (
        proposal["targetWorkAreas"][0]["workAreaId"]
        == harness.source.authority.zone_snapshot.work_area_id
    )
    assert proposal["reportDigest"] == harness.source.report.report_digest
    assert "compatibilityMappingDigest" not in proposal
    assert set(created.json()) == {"proposal", "approvalReceipt"}

    rejected_body = client.post(
        "/v1/external-reobservation-proposals/approve",
        headers={"Authorization": f"Bearer {_TOKEN}", "Idempotency-Key": "approval-key-a"},
        json={
            "proposalRef": proposal["proposalRef"],
            "expectedVersion": 1,
            "organizationId": "org-b",
        },
    )
    assert rejected_body.status_code == 422
    assert harness.work_orders.list_external_reobservation_bindings(organization_id="org-a") == []

    approved = client.post(
        "/v1/external-reobservation-proposals/approve",
        headers={"Authorization": f"Bearer {_TOKEN}", "Idempotency-Key": "approval-key-a"},
        json={"proposalRef": proposal["proposalRef"], "expectedVersion": 1},
    )

    assert approved.status_code == 200
    receipt = approved.json()["approvalReceipt"]
    assert receipt["proposalId"] == proposal["proposalRef"]
    assert (
        len(harness.work_orders.list_external_reobservation_bindings(organization_id="org-a")) == 1
    )
    assert [raw["kind"] for raw in harness.work_orders._journal.replay()].count(
        "external-reobservation-approved-and-next-order-created"
    ) == 1


def test_exact_approved_retry_survives_later_current_source_revocation(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    proposal = harness.service.create(
        organization_id="org-a",
        report_ref=harness.source.report_ref,
        target_work_area_ids=(harness.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="proposal-key-a",
    )
    first = harness.service.approve(
        organization_id="org-a",
        proposal_ref=proposal.proposal_ref,
        expected_version=proposal.version,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="approval-key-a",
    )
    resolutions_before_retry = harness.source_port.current_resolutions
    harness.source_port.live = False

    retried = harness.service.approve(
        organization_id="org-a",
        proposal_ref=proposal.proposal_ref,
        expected_version=proposal.version,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="approval-key-a",
    )

    assert retried == first
    assert harness.source_port.current_resolutions == resolutions_before_retry
    assert (
        len(harness.work_orders.list_external_reobservation_bindings(organization_id="org-a")) == 1
    )


def test_new_approval_is_blocked_when_current_source_is_revoked(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    proposal = harness.service.create(
        organization_id="org-a",
        report_ref=harness.source.report_ref,
        target_work_area_ids=(harness.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="proposal-key-a",
    )
    harness.source_port.live = False

    with pytest.raises(ExternalReobservationProposalUnavailableError):
        harness.service.approve(
            organization_id="org-a",
            proposal_ref=proposal.proposal_ref,
            expected_version=proposal.version,
            principal=_principal(),
            actor="operator-a",
            now=_NOW,
            idempotency_key="approval-key-a",
        )

    assert harness.work_orders.list_external_reobservation_bindings(organization_id="org-a") == []


def test_kernel_approval_without_authenticated_preflight_is_closed(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    proposal = harness.service.create(
        organization_id="org-a",
        report_ref=harness.source.report_ref,
        target_work_area_ids=(harness.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="proposal-key-a",
    )
    approval_input = _approval_input(proposal)

    with pytest.raises(RuntimeError, match="EXTERNAL_REOBSERVATION_AUTHORITY_UNAVAILABLE"):
        harness.work_orders.approve_external_reobservation(
            approval_input,
            organization_id="org-a",
            actor="operator-a",
            now=_NOW,
            idempotency_key="approval-key-a",
        )

    assert harness.work_orders.list_external_reobservation_bindings(organization_id="org-a") == []


def test_denied_nested_preflight_cannot_reuse_outer_actor_witness(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    proposal = harness.service.create(
        organization_id="org-a",
        report_ref=harness.source.report_ref,
        target_work_area_ids=(harness.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="proposal-key-a",
    )
    approval_input = _approval_input(proposal)

    with harness.authority_port.preflight_approval(
        principal=_principal(),
        organization_id="org-a",
        approval_input=approval_input,
        evaluated_at=_NOW,
    ) as outer_available:
        assert outer_available
        with harness.authority_port.preflight_approval(
            principal=_principal(principal_id="operator-b"),
            organization_id="org-a",
            approval_input=approval_input,
            evaluated_at=_NOW,
        ) as denied_available:
            assert not denied_available
            with pytest.raises(RuntimeError):
                harness.work_orders.approve_external_reobservation(
                    approval_input,
                    organization_id="org-a",
                    actor="operator-b",
                    now=_NOW,
                    idempotency_key="approval-key-b",
                )

    assert harness.work_orders.list_external_reobservation_bindings(organization_id="org-a") == []


def test_denied_nested_preflight_cannot_reuse_outer_organization_witness(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    proposal = harness.service.create(
        organization_id="org-a",
        report_ref=harness.source.report_ref,
        target_work_area_ids=(harness.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="proposal-key-a",
    )
    approval_input = _approval_input(proposal)

    with harness.authority_port.preflight_approval(
        principal=_principal(),
        organization_id="org-a",
        approval_input=approval_input,
        evaluated_at=_NOW,
    ) as outer_available:
        assert outer_available
        with harness.authority_port.preflight_approval(
            principal=_principal(organization_id="org-b"),
            organization_id="org-b",
            approval_input=approval_input,
            evaluated_at=_NOW,
        ) as denied_available:
            assert not denied_available
            with pytest.raises(RuntimeError):
                harness.work_orders.approve_external_reobservation(
                    approval_input,
                    organization_id="org-a",
                    actor="operator-a",
                    now=_NOW,
                    idempotency_key="approval-key-b",
                )

    assert harness.work_orders.list_external_reobservation_bindings(organization_id="org-a") == []


def test_approval_history_requires_source_at_actual_approval_time(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    proposed_at = _NOW + timedelta(seconds=1)
    proposal = harness.service.create(
        organization_id="org-a",
        report_ref=harness.source.report_ref,
        target_work_area_ids=(harness.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=proposed_at,
        idempotency_key="proposal-key-a",
    )
    approved_at = _NOW + timedelta(seconds=3)
    harness.source_port.historical_not_after = _NOW + timedelta(seconds=2)

    with pytest.raises(
        RuntimeError, match="EXTERNAL_REOBSERVATION_HISTORICAL_AUTHORITY_UNAVAILABLE"
    ):
        harness.service.approve(
            organization_id="org-a",
            proposal_ref=proposal.proposal_ref,
            expected_version=proposal.version,
            principal=_principal(),
            actor="operator-a",
            now=approved_at,
            idempotency_key="approval-key-a",
        )

    assert proposed_at in harness.source_port.historical_evaluations
    assert approved_at in harness.source_port.historical_evaluations
    assert harness.work_orders.list_external_reobservation_bindings(organization_id="org-a") == []


def test_preflight_witness_is_request_scoped_and_principal_bound(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    proposal = harness.service.create(
        organization_id="org-a",
        report_ref=harness.source.report_ref,
        target_work_area_ids=(harness.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="proposal-key-a",
    )
    approval_input = _approval_input(proposal)

    with harness.authority_port.preflight_approval(
        principal=_principal(),
        organization_id="org-a",
        approval_input=approval_input,
        evaluated_at=_NOW,
    ) as available:
        assert available
        with harness.authority_port.guard_current(
            organization_id="org-a",
            approval_input=approval_input,
            actor="operator-a",
            evaluated_at=_NOW,
        ) as authority:
            assert authority == proposal.approval_authority()
        with harness.authority_port.guard_current(
            organization_id="org-b",
            approval_input=approval_input,
            actor="operator-a",
            evaluated_at=_NOW,
        ) as authority:
            assert authority is None
        mismatched_input = approval_input.model_copy(
            update={"proposal_digest": _digest("different-proposal"), "approval_input_digest": None}
        ).sealed()
        with harness.authority_port.guard_current(
            organization_id="org-a",
            approval_input=mismatched_input,
            actor="operator-a",
            evaluated_at=_NOW,
        ) as authority:
            assert authority is None
        with harness.authority_port.preflight_approval(
            principal=_principal(principal_id="operator-b"),
            organization_id="org-a",
            approval_input=approval_input,
            evaluated_at=_NOW,
        ) as other_actor_available:
            assert not other_actor_available

    with harness.authority_port.guard_current(
        organization_id="org-a",
        approval_input=approval_input,
        actor="operator-a",
        evaluated_at=_NOW,
    ) as authority:
        assert authority is None
    with pytest.raises(
        ValueError, match="approval actor must be the scoped authenticated principal"
    ):
        harness.service.approve(
            organization_id="org-a",
            proposal_ref=proposal.proposal_ref,
            expected_version=proposal.version,
            principal=_principal(),
            actor="operator-b",
            now=_NOW,
            idempotency_key="approval-key-a",
        )
    assert harness.work_orders.list_external_reobservation_bindings(organization_id="org-a") == []


def test_preflight_exception_resets_the_shadowed_witness(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    proposal = harness.service.create(
        organization_id="org-a",
        report_ref=harness.source.report_ref,
        target_work_area_ids=(harness.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="proposal-key-a",
    )
    approval_input = _approval_input(proposal)

    with (
        pytest.raises(RuntimeError, match="preflight probe"),
        harness.authority_port.preflight_approval(
            principal=_principal(),
            organization_id="org-a",
            approval_input=approval_input,
            evaluated_at=_NOW,
        ) as available,
    ):
        assert available
        raise RuntimeError("preflight probe")

    with harness.authority_port.guard_current(
        organization_id="org-a",
        approval_input=approval_input,
        actor="operator-a",
        evaluated_at=_NOW,
    ) as authority:
        assert authority is None


def test_historical_lineage_replays_after_current_source_revocation(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    proposal = harness.service.create(
        organization_id="org-a",
        report_ref=harness.source.report_ref,
        target_work_area_ids=(harness.source.authority.zone_snapshot.work_area_id,),
        reason="REVIEWED",
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="proposal-key-a",
    )
    approved = harness.service.approve(
        organization_id="org-a",
        proposal_ref=proposal.proposal_ref,
        expected_version=proposal.version,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="approval-key-a",
    )
    harness.source_port.live = False
    for store in (
        harness.sites,
        harness.work_areas,
        harness.reviews,
        harness.proposals,
        harness.work_orders,
    ):
        store._journal.close()  # noqa: SLF001 -- restart uses the same durable histories

    coordinator = ExternalAuthorityCurrentnessCoordinator()
    sites = SiteStore(DurableJournal(tmp_path / "sites.jsonl"), coordinator=coordinator)
    work_areas = WorkAreaStore(
        DurableJournal(tmp_path / "work-areas.jsonl"),
        site_exists=lambda site_id: sites.get(site_id) is not None,
        coordinator=coordinator,
    )
    reviews = ExternalResultReviewStore(
        DurableJournal(tmp_path / "reviews.jsonl"),
        source_port=harness.source_port,
        coordinator=coordinator,
    )
    proposals = ExternalReobservationProposalStore(
        DurableJournal(tmp_path / "proposals.jsonl"), coordinator=coordinator
    )
    authority_port = CoreExternalReobservationProposalAuthorityPort(
        reviews=reviews,
        proposals=proposals,
        sites=sites,
        work_areas=work_areas,
        coordinator=coordinator,
    )
    recovered_review = reviews.get_for_report(proposal.report_ref, organization_id="org-a")
    recovered_proposal = proposals.get_scoped(proposal.proposal_ref, organization_id="org-a")
    assert recovered_review is not None
    assert recovered_proposal == proposal
    assert sites.historical_scoped_identity("site-a", organization_id="org-a", at=_NOW) is not None
    historical_area = work_areas.historical_active(
        proposal.target_work_areas[0].work_area_id, site_id="site-a", at=_NOW
    )
    assert historical_area is not None
    assert historical_area.work_area_id == proposal.target_work_areas[0].work_area_id
    assert historical_area.polygon == proposal.target_work_areas[0].polygon
    assert historical_area.crs == proposal.target_work_areas[0].crs
    assert (
        authority_port.resolve_historical(
            organization_id="org-a",
            approval_input=_approval_input(recovered_proposal),
            actor="operator-a",
            approved_at=approved.approval_receipt.approved_at,
        )
        == proposal.approval_authority()
    )
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            sites.get_scoped(site_id, organization_id) is not None
        ),
        work_areas_exist=lambda _site_id, _work_area_ids: True,
        external_reobservation_authority_port=authority_port,
    )

    recovered = work_orders.get_external_reobservation_approval(
        proposal.proposal_ref,
        expected_version=proposal.version,
        organization_id="org-a",
    )
    assert recovered == approved.approval_receipt
    verify_external_reobservation_organization_graph(
        organization_id="org-a",
        work_orders=work_orders,
        authority_port=authority_port,
    )


def test_graph_verifier_rejects_dangling_historical_source_before_mount(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    proposal = harness.service.create(
        organization_id="org-a",
        report_ref=harness.source.report_ref,
        target_work_area_ids=(harness.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="proposal-key-a",
    )
    harness.service.approve(
        organization_id="org-a",
        proposal_ref=proposal.proposal_ref,
        expected_version=proposal.version,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="approval-key-a",
    )
    harness.source_port.source = None

    with pytest.raises(
        ExternalReobservationProposalRecoveryError,
        match="durable review historical lineage is invalid",
    ):
        verify_external_reobservation_organization_graph(
            organization_id="org-a",
            work_orders=harness.work_orders,
            authority_port=harness.authority_port,
        )


@pytest.mark.parametrize("version", [True, 1.0])
def test_review_replay_rejects_non_integer_rehashed_event_version(
    tmp_path: Path, version: object
) -> None:
    harness = _harness(tmp_path)
    harness.reviews._journal.close()  # noqa: SLF001 -- temporary replay corruption
    journal_path = tmp_path / "reviews.jsonl"
    raw = json.loads(journal_path.read_text().strip())
    raw["version"] = version
    raw["eventDigest"] = _event_digest(raw)
    journal_path.write_text(json.dumps(raw, separators=(",", ":")) + "\n")

    with pytest.raises(ExternalResultReviewRecoveryError):
        ExternalResultReviewStore(
            DurableJournal(journal_path),
            source_port=harness.source_port,
            coordinator=harness.coordinator,
        )


def test_proposal_store_rejects_rehashed_invalid_review_and_target_before_append(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    review = harness.reviews.get_for_report(harness.source.report_ref, organization_id="org-a")
    assert review is not None
    target = ExternalWorkAreaSnapshotV1(
        work_area_id=review.authority.zone_snapshot.work_area_id,
        revision=1,
        polygon=review.authority.zone_snapshot.polygon,
        crs=review.authority.zone_snapshot.crs,
    ).sealed()
    bad_limitations = review.model_copy(
        update={
            "factual_limitations": ("UNSUPPORTED", "LIMITATION", "VALUES"),
            "review_digest": None,
        }
    )
    bad_limitations = bad_limitations.model_copy(
        update={"review_digest": bad_limitations.canonical_digest()}
    )
    bad_authority = review.authority.model_copy(
        update={"maximum_zone_cell_count": True, "authority_digest": None}
    )
    bad_authority = bad_authority.model_copy(
        update={"authority_digest": bad_authority.canonical_digest()}
    )
    bad_numeric = review.model_copy(update={"authority": bad_authority, "review_digest": None})
    bad_numeric = bad_numeric.model_copy(update={"review_digest": bad_numeric.canonical_digest()})
    bad_target = target.model_copy(update={"revision": True, "snapshot_digest": None})
    bad_target = bad_target.model_copy(update={"snapshot_digest": bad_target.canonical_digest()})

    for invalid_review, invalid_target, key in (
        (bad_limitations, target, "invalid-limitations"),
        (bad_numeric, target, "invalid-numeric"),
        (review, bad_target, "invalid-target"),
    ):
        with pytest.raises(ValueError):
            harness.proposals.create(
                review=invalid_review,
                target=invalid_target,
                reason=None,
                actor="operator-a",
                created_at=_NOW,
                idempotency_key=key,
            )

    assert harness.proposals._journal.replay() == []  # noqa: SLF001 -- zero preappend events
    valid_proposal = harness.proposals.create(
        review=review,
        target=target,
        reason=None,
        actor="operator-a",
        created_at=_NOW,
        idempotency_key="valid-proposal",
    )
    harness.proposals._journal.close()  # noqa: SLF001 -- restart the same valid history
    recovered = ExternalReobservationProposalStore(
        DurableJournal(tmp_path / "proposals.jsonl"), coordinator=harness.coordinator
    )
    assert (
        recovered.get_scoped(valid_proposal.proposal_ref, organization_id="org-a") == valid_proposal
    )


def test_graph_verifier_checks_review_only_and_unapproved_proposal_lineage(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.source_port.source = None

    with pytest.raises(ExternalReobservationProposalRecoveryError):
        verify_external_reobservation_organization_graph(
            organization_id="org-a",
            work_orders=harness.work_orders,
            authority_port=harness.authority_port,
        )

    harness = _harness(tmp_path / "proposal")
    harness.service.create(
        organization_id="org-a",
        report_ref=harness.source.report_ref,
        target_work_area_ids=(harness.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="proposal-key-a",
    )
    harness.source_port.source = None

    with pytest.raises(ExternalReobservationProposalRecoveryError):
        verify_external_reobservation_organization_graph(
            organization_id="org-a",
            work_orders=harness.work_orders,
            authority_port=harness.authority_port,
        )


def test_sealed_review_and_proposal_wires_validate_published_contract_schemas(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    review = harness.reviews.get_for_report(harness.source.report_ref, organization_id="org-a")
    assert isinstance(review, ExternalResultReviewReceiptV1)
    proposal = harness.service.create(
        organization_id="org-a",
        report_ref=harness.source.report_ref,
        target_work_area_ids=(harness.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="proposal-schema-key-a",
    )
    root = Path(__file__).resolve().parents[2]
    receipt_schema = json.loads(
        (root / "contracts/schemas/external-result-review-receipt.v1.json").read_text()
    )
    proposal_schema = json.loads(
        (root / "contracts/schemas/external-reobservation-proposal.v1.json").read_text()
    )

    Draft202012Validator(receipt_schema).validate(external_result_review_receipt_wire_dict(review))
    Draft202012Validator(proposal_schema).validate(
        external_reobservation_proposal_wire_dict(proposal)
    )


def test_proposal_replay_rejects_a_tampered_event_digest(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.service.create(
        organization_id="org-a",
        report_ref=harness.source.report_ref,
        target_work_area_ids=(harness.source.authority.zone_snapshot.work_area_id,),
        reason=None,
        principal=_principal(),
        actor="operator-a",
        now=_NOW,
        idempotency_key="proposal-tamper-key-a",
    )
    harness.proposals._journal.close()  # noqa: SLF001 -- corrupt only the temporary test journal
    journal_path = tmp_path / "proposals.jsonl"
    raw = json.loads(journal_path.read_text().strip())
    raw["proposal"]["reason"] = "CHANGED"
    journal_path.write_text(json.dumps(raw, separators=(",", ":")) + "\n")

    with pytest.raises(ExternalReobservationProposalRecoveryError):
        ExternalReobservationProposalStore(
            DurableJournal(journal_path), coordinator=harness.coordinator
        )


def test_historical_site_and_work_area_reads_require_timestamped_existence(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    work_area_id = harness.source.authority.zone_snapshot.work_area_id

    assert (
        harness.sites.historical_scoped_identity(
            "site-a", organization_id="org-a", at=_NOW - timedelta(hours=2)
        )
        is None
    )
    assert (
        harness.work_areas.historical_active(
            work_area_id, site_id="site-a", at=_NOW - timedelta(hours=2)
        )
        is None
    )
    assert (
        harness.sites.historical_scoped_identity("site-a", organization_id="org-a", at=_NOW)
        is not None
    )
    assert harness.work_areas.historical_active(work_area_id, site_id="site-a", at=_NOW) is not None
