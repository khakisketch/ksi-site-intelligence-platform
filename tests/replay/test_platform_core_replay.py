"""Platform Core restart/replay coverage (Task 4).

Mirrors the authorized-cycle-across-restart recipe
(``test_external_quantitative_real_participants_complete_authorized_cycle_across_restart``)
with ``assemble_platform_app`` (Task 2 factory) swapped in for the legacy
assembly — same stores, same helpers, same wire contracts:

  V1 sealed pair (store-level, existing helpers) + V2 sealed DSM (HTTP) ->
  inspection/evidence -> mapping/decision/execution -> terminal volume report
  -> platform restart (reassembled on the same data dir) ->
  review -> reobservation proposal -> approved successor.

Post-restart the test proves, through the platform HTTP surface and the
mounted services: external history remains readable under exact grants;
retained managed WorkOrder rows are byte-identical, readable, and not
executable; permission/AI-consent/currentness revocation keeps history
while denying fresh metadata/bytes/new use; tenant-hidden pagination
cursors disclose nothing; corrupt/unknown journal records fail closed
(never a permissive legacy decoder).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pytest
from analysis_api_local_fixture import LoopbackObjectStorage, _register_and_seal_v2_dsm
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.composition.platform_assembly import assemble_platform_app
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_relative_volumes import (
    ExternalRelativeVolumeObservedReportInput,
    ExternalRelativeVolumeVerdict,
)
from ksi_core.leasing import LeaseFence
from ksi_core.observation_work_orders import ExternalReobservationExecutionDenied
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeMeasurementPayloadV1,
    ExternalVolumeMetricsV1,
)
from ksi_mission_contracts.models import SiteFrame
from test_external_analysis_execution_integration import _geotiff_bytes
from test_external_analysis_http_integration import _local_graph_config
from test_external_quantitative_production_flow import (
    _EPOCH_RSS_UNCERTAINTY_M3,
    _KNOWN_UNCERTAINTY_NOTE,
    _admit_policy,
    _inspect,
    _mapping,
    _principal,
    _restarted_policy_authority,
    _RetainedEvidenceContextAuthority,
    _RetainedPolicyAuthority,
    _sealed_revision,
    _validate_evidence,
    _workflow,
)
from test_platform_core_http_integration import _TRANSFORM


def _op_headers(key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": "Bearer " + _OP_TOKEN}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _create_external_order(client: TestClient, area_id: str, *, key: str) -> dict[str, Any]:
    response = client.post(
        "/v1/sites/site-a/observation-work-orders",
        headers=_op_headers(key),
        json={
            "name": "플랫폼 재생 관측",
            "workAreaIds": [area_id],
            "scheduleId": None,
            "executionMode": "EXTERNAL_RECONSTRUCTION",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["executionMode"] == "EXTERNAL_RECONSTRUCTION"
    return body


_OP_TOKEN = "platform-replay-operator"  # noqa: S105 -- deterministic test credential
_V2_OP_TOKEN = "analysis-local-fixture-operator"  # noqa: S105 -- reused V2 seal helper header
_FOREIGN_TOKEN = "platform-replay-foreign"  # noqa: S105 -- deterministic test credential
_MCP_TOKEN = "platform-replay-mcp-client"  # noqa: S105 -- deterministic test credential


def _record(
    token: str,
    principal: Principal,
) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        principal=principal,
    )


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            _record(
                _OP_TOKEN,
                Principal(
                    principal_id="platform-replay-operator",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                    organization_id="org-a",
                ),
            ),
            _record(
                _V2_OP_TOKEN,
                Principal(
                    principal_id="analysis-local-operator",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                    organization_id="org-a",
                ),
            ),
            _record(
                _FOREIGN_TOKEN,
                Principal(
                    principal_id="platform-replay-foreign",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                    organization_id="org-b",
                ),
            ),
            _record(
                _MCP_TOKEN,
                Principal(
                    principal_id="platform-replay-mcp",
                    kind=PrincipalKind.ANALYSIS_MCP_CLIENT,
                    role=None,
                    device_id=None,
                    organization_id="org-a",
                    allowed_site_ids=frozenset({"site-a", "site-c"}),
                    allowed_work_area_ids=frozenset({"wa-site-a-0001", "wa-site-c-0001"}),
                ),
            ),
        ]
    )


def _foreign_headers() -> dict[str, str]:
    return {"Authorization": "Bearer " + _FOREIGN_TOKEN}


def _mcp_headers() -> dict[str, str]:
    return {"Authorization": "Bearer " + _MCP_TOKEN}


class _ReplayBoot:
    """One platform assembly generation over a data dir."""

    def __init__(
        self,
        data_dir: Path,
        *,
        workflow: Any,
        envelope: Any,
        policy_authority: Any,
        context_authority: Any,
        storage: Any,
    ) -> None:
        self.trace: list[str] = []
        self.opened: list[DurableJournal] = []

        def journal(name: str) -> DurableJournal:
            self.trace.append(name)
            item = DurableJournal(data_dir / name)
            self.opened.append(item)
            return item

        # Factory identity: the replayed generations must both come from
        # the Task 2 platform factory, never the legacy assembly.
        assert assemble_platform_app.__module__ == "ksi_core.composition.platform_assembly"
        self.app = assemble_platform_app(
            data_dir,
            journal=journal,
            opened=self.opened,
            auth_registry=_registry(),
            evidence_storage=storage,
            external_result_workflow=workflow,
            external_analysis_local_graph=_local_graph_config(envelope),
        )

    def close(self) -> None:
        for journal in reversed(self.opened):
            journal.close()


def _seed_site(app: Any, site_id: str, name: str, *, ai_egress_allowed: bool, now: datetime) -> str:
    from test_external_analysis_execution_integration import _ORIGIN_X, _ORIGIN_Y

    registered = app.state.site_store.register(
        site_id,
        name,
        SiteFrame(
            crs="EPSG:5186",
            vertical_datum="EGM96 height",
            unit="meter",
            transform_version="fixture-v1",
        ),
        organization_id="org-a",
        ai_egress_allowed=ai_egress_allowed,
        actor="platform-replay-operator",
        now=now - timedelta(minutes=30),
    )
    assert registered.record is not None
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [_ORIGIN_X - 0.01, _ORIGIN_Y + 0.01],
                [_ORIGIN_X - 0.01, _ORIGIN_Y - 0.2],
                [_ORIGIN_X + 0.2, _ORIGIN_Y - 0.2],
                [_ORIGIN_X + 0.2, _ORIGIN_Y + 0.01],
                [_ORIGIN_X - 0.01, _ORIGIN_Y + 0.01],
            ]
        ],
    }
    area_result = app.state.work_area_store.register(
        site_id,
        name=name + " area",
        polygon=polygon,
        crs="EPSG:5186",
        supersedes=None,
        actor="platform-replay-operator",
        now=now - timedelta(minutes=29),
    )
    assert area_result.work_area is not None
    return area_result.work_area.work_area_id


def _journal_bytes(data_dir: Path, names: list[str]) -> dict[str, bytes | None]:
    """Snapshot journal bytes; journals that never materialized map to None.

    Some journals (e.g. display-artifacts) are created lazily on first
    write, so a name in the trace may have no file yet. The pre/post
    comparison is symmetric: same keys, same bytes-or-None.
    """
    snapshot: dict[str, bytes | None] = {}
    for name in names:
        path = data_dir / name
        snapshot[name] = path.read_bytes() if path.exists() else None
    return snapshot


def _fresh_boot(data_dir: Path, storage: Any) -> _ReplayBoot:
    """Assemble with throwaway authorities and workflow (boot-failure probes only)."""
    now = datetime.now(UTC).replace(microsecond=0)
    policy_authority = _RetainedPolicyAuthority()
    context_authority = _RetainedEvidenceContextAuthority(now)
    workflow, _catalog, envelope, _ = _workflow(
        data_dir,
        now=now,
        policy_authority=policy_authority,
        context_authority=context_authority,
    )
    return _ReplayBoot(
        data_dir,
        workflow=workflow,
        envelope=envelope,
        policy_authority=policy_authority,
        context_authority=context_authority,
        storage=storage,
    )


def test_external_history_review_followup_survive_platform_restart(tmp_path: Path) -> None:
    """V1/V2 history, terminal report, review and successor replay on the platform app."""
    now = datetime.now(UTC).replace(microsecond=0)
    storage = LoopbackObjectStorage()
    policy_authority = _RetainedPolicyAuthority()
    context_authority = _RetainedEvidenceContextAuthority(now)
    workflow, catalog_record, envelope, _catalog_authority = _workflow(
        tmp_path,
        now=now,
        policy_authority=policy_authority,
        context_authority=context_authority,
    )
    boot = _ReplayBoot(
        tmp_path,
        workflow=workflow,
        envelope=envelope,
        policy_authority=policy_authority,
        context_authority=context_authority,
        storage=storage,
    )
    try:
        app = boot.app
        area_id = _seed_site(app, "site-a", "Replay site", ai_egress_allowed=True, now=now)
        _seed_site(app, "site-c", "No-AI-consent site", ai_egress_allowed=False, now=now)
        with TestClient(app) as client:
            baseline_created = _create_external_order(client, area_id, key="replay-baseline")
            current_created = _create_external_order(client, area_id, key="replay-current")
            v2_created = _create_external_order(client, area_id, key="replay-v2")
        orders = app.state.observation_work_order_store
        baseline_order = orders.get(baseline_created["workOrderId"], organization_id="org-a")
        current_order = orders.get(current_created["workOrderId"], organization_id="org-a")
        v2_order = orders.get(v2_created["workOrderId"], organization_id="org-a")
        assert baseline_order is not None and current_order is not None and v2_order is not None
        # V1 sealed pair through the existing store helpers (recipe-exact).
        baseline_revision, baseline_subject = _sealed_revision(
            app,
            baseline_order,
            "replay-baseline",
            start=now - timedelta(minutes=20),
            end=now - timedelta(minutes=15),
            storage=storage,
        )
        current_revision, current_subject = _sealed_revision(
            app,
            current_order,
            "replay-current",
            start=now - timedelta(minutes=10),
            end=now - timedelta(minutes=5),
            storage=storage,
        )
        # V2 sealed DSM through platform HTTP (generated bytes, upload-grant flow).
        with TestClient(app) as client:
            dsm_bytes = _geotiff_bytes(np.full((2, 2), 100.0), transform=_TRANSFORM)
            v2_revision, v2_subject = _register_and_seal_v2_dsm(
                client,
                app,
                v2_order,
                "replay-v2dsm",
                start=now - timedelta(minutes=4),
                end=now - timedelta(minutes=2),
                storage=storage,
                dsm_bytes=dsm_bytes,
                organization_id="org-a",
            )
        assert v2_revision.manifest is not None
        policy = _admit_policy(
            app,
            subjects=(baseline_subject, current_subject),
            envelope=envelope,
            authority=policy_authority,
            now=now,
        )
        baseline_report = _inspect(
            app, revision=baseline_revision, subject=baseline_subject, policy=policy, now=now
        )
        current_report = _inspect(
            app, revision=current_revision, subject=current_subject, policy=policy, now=now
        )
        baseline_evidence = _validate_evidence(
            app,
            revision=baseline_revision,
            subject=baseline_subject,
            policy=policy,
            context_authority=context_authority,
            now=now,
            storage=storage,
        )
        current_evidence = _validate_evidence(
            app,
            revision=current_revision,
            subject=current_subject,
            policy=policy,
            context_authority=context_authority,
            now=now,
            storage=storage,
        )
        mapping = _mapping(
            subjects=(baseline_subject, current_subject),
            revisions=(baseline_revision, current_revision),
            reports=(baseline_report, current_report),
            evidence_records=(baseline_evidence, current_evidence),
            policy=policy,
            area=app.state.work_area_store.get(area_id),
            now=now,
            catalog_digest=catalog_record.digest,
        )
        catalog = app.state.external_relative_volume_mapping_authority
        admitted = catalog.admit_mapping(mapping, actor="catalog-admin", now=now)
        assert admitted is not None and admitted.mapping_digest == mapping.mapping_digest
        active_now = now + timedelta(seconds=2)
        decision = app.state.external_use_evaluator.request_pair(
            baseline_subject,
            current_subject,
            use="RELATIVE_VOLUME",
            zone_id=area_id,
            idempotency_key="replay-quantitative-decision",
            principal=_principal(),
            now=active_now,
        )
        assert decision.verdict.value == "ELIGIBLE" and decision.decision_digest is not None
        execution = catalog.activate_execution(
            decision_ref=decision.decision_id,
            principal=_principal(),
            current_work_order_id=current_order.work_order_id,
            now=active_now,
        )
        assert execution is not None
        issued = app.state.external_relative_volume_store.issue(
            principal=_principal(),
            current_work_order_id=current_order.work_order_id,
            decision_ref=decision.decision_id,
            idempotency_key="replay-quantitative-volume",
            now=active_now,
        )
        assert issued.verdict is ExternalRelativeVolumeVerdict.ISSUED and issued.record is not None
        leased = app.state.external_relative_volume_store.claim(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="volume-worker",
            fence=LeaseFence(str(uuid4()), str(uuid4()), 0),
            now=active_now,
        )
        assert leased.fence is not None and leased.record is not None
        request = leased.record.request
        payload = ExternalRelativeVolumeMeasurementPayloadV1(
            request_digest=request.request_digest,
            decision_digest=request.decision_digest,
            baseline_dsm_digest=request.baseline.observed_sha256,
            current_dsm_digest=request.current.observed_sha256,
            zone_snapshot_digest=request.zone_snapshot.canonical_digest(),
            execution_policy_digest=request.execution_policy_digest,
            algorithm_build_digest=execution.execution_policy.algorithm_build_digest,
            config_digest=execution.execution_policy.config_digest,
            metrics=ExternalVolumeMetricsV1(
                zone_cell_count=10,
                common_valid_cell_count=10,
                zone_area_m2=10.0,
                measured_area_m2=10.0,
                common_valid_fraction=1.0,
                cut_m3=1.0,
                fill_m3=5.0,
                net_m3=4.0,
                threshold_m=execution.execution_policy.threshold_m,
                uncertainty_m3=_EPOCH_RSS_UNCERTAINTY_M3,
                uncertainty_note=_KNOWN_UNCERTAINTY_NOTE,
            ),
        )
        reported = app.state.external_relative_volume_store.record_observed_report(
            request.request_id,
            organization_id="org-a",
            principal_id="volume-worker",
            fence=leased.fence,
            observed=ExternalRelativeVolumeObservedReportInput(
                payload=payload, computed_at=active_now
            ),
            now=active_now,
        )
        assert reported.record is not None and reported.record.report is not None
        report_ref = reported.record.report.report_id
        assert reported.record.report.payload.metrics.net_m3 == 4.0
        # Retained managed row: readable history, never executable here.
        managed = orders.create_work_order(
            organization_id="org-a",
            site_id="site-a",
            name="Retained managed row",
            work_area_ids=[area_id],
            schedule_id=None,
            actor="fixture",
            now=now,
        )
        journals_before = _journal_bytes(tmp_path, boot.trace)
        for journal in reversed(boot.opened):
            journal.close()
        boot.opened.clear()

        # ---- restart: reassemble the platform app on the same data dir ----
        restarted_context = _RetainedEvidenceContextAuthority(active_now)
        for context in context_authority.retained_contexts():
            restarted_context.add(context)
        restarted_policy_authority = _restarted_policy_authority(policy_authority)
        restarted_workflow, _, _, _ = _workflow(
            tmp_path,
            now=now,
            policy_authority=restarted_policy_authority,
            context_authority=restarted_context,
        )
        reboot = _ReplayBoot(
            tmp_path,
            workflow=restarted_workflow,
            envelope=envelope,
            policy_authority=restarted_policy_authority,
            context_authority=restarted_context,
            storage=storage,
        )
        try:
            # Replay writes nothing: journals are byte-identical after reopen.
            assert _journal_bytes(tmp_path, reboot.trace) == journals_before
            restarted = reboot.app
            service = restarted.state.external_result_workflow_service
            review = service.reviews.review(
                organization_id="org-a",
                report_ref=report_ref,
                principal=_principal(),
                evaluated_at=active_now,
            )
            proposal = service.create(
                organization_id="org-a",
                report_ref=report_ref,
                target_work_area_ids=(area_id,),
                reason="Review of measured external quantity result requires a reobservation plan.",
                principal=_principal(),
                actor="operator-a",
                now=active_now,
                idempotency_key="replay-quantitative-proposal",
            )
            approval = service.approve(
                organization_id="org-a",
                proposal_ref=proposal.proposal_ref,
                expected_version=proposal.version,
                principal=_principal(),
                actor="operator-a",
                now=active_now,
                idempotency_key="replay-quantitative-approval",
            )
            assert approval.planning_binding.report_digest == review.report.report_digest
            successor_id = approval.approval_receipt.successor_work_order_id
            assert successor_id == approval.successor_work_order.work_order_id
            work_order_journal = tmp_path / "observation-work-orders.jsonl"
            approval_prefix = work_order_journal.read_bytes()
            idempotent = service.approve(
                organization_id="org-a",
                proposal_ref=proposal.proposal_ref,
                expected_version=proposal.version,
                principal=_principal(),
                actor="operator-a",
                now=active_now,
                idempotency_key="replay-quantitative-approval",
            )
            assert idempotent == approval
            assert work_order_journal.read_bytes() == approval_prefix
            with pytest.raises(
                ExternalReobservationExecutionDenied, match="EXTERNAL_RECONSTRUCTION_ONLY"
            ):
                restarted.state.observation_work_order_store.assert_execution_allowed(
                    approval.successor_work_order
                )
            # Managed row survived byte-identical: its journal line is
            # still present verbatim and the row stays non-executable.
            reread = work_order_journal.read_bytes()
            before_lines = journals_before["observation-work-orders.jsonl"].decode().splitlines()
            managed_lines = [line for line in before_lines if managed.work_order_id in line]
            assert len(managed_lines) == 1
            assert managed_lines[0] in reread.decode()
            with TestClient(restarted) as client:
                _assert_post_restart_history(
                    client,
                    area_id,
                    baseline_order,
                    current_order,
                    v2_order,
                    report_ref,
                    review,
                    proposal,
                    successor_id,
                    managed,
                    active_now,
                )
                _assert_revocation_distinctions(
                    client,
                    restarted,
                    active_now,
                    decision,
                    area_id,
                    baseline_subject,
                    current_subject,
                    policy,
                    restarted_context,
                    current_order,
                )
        finally:
            reboot.close()
    finally:
        for journal in boot.opened:
            journal.close()


def _assert_post_restart_history(
    client: TestClient,
    area_id: str,
    baseline_order: Any,
    current_order: Any,
    v2_order: Any,
    report_ref: str,
    review: Any,
    proposal: Any,
    successor_id: str,
    managed: Any,
    active_now: datetime,
) -> None:
    """Exact-grant reads stay 200 after restart; foreign reads stay 404."""
    owner = _op_headers("history")
    foreign = _foreign_headers()
    # V1 submissions + sealed revision history.
    v1_base = (
        f"/v1/observation-work-orders/{baseline_order.work_order_id}/"
        "external-reconstruction-submissions"
    )
    listed = client.get(v1_base, headers=owner)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["submissions"]) == 1
    submission_ref = listed.json()["submissions"][0]["submissionRef"]
    revision = client.get(f"{v1_base}/{submission_ref}/revisions/1", headers=owner)
    assert revision.status_code == 200, revision.text
    assert revision.json()["manifest"]["manifestDigest"] is not None
    assert client.get(v1_base, headers=foreign).status_code == 404
    # V2 submission history is retained under the same grants.
    v2_base = (
        f"/v1/observation-work-orders/{v2_order.work_order_id}/external-reconstruction-submissions"
    )
    v2_listed = client.get(v2_base, headers=owner)
    assert v2_listed.status_code == 200, v2_listed.text
    assert len(v2_listed.json()["submissions"]) == 1
    assert client.get(v2_base, headers=foreign).status_code == 404
    # Report history with cursor pagination; cursors disclose nothing.
    history_path = "/v1/sites/site-a/external-relative-volume-reports"
    page = client.get(history_path, headers={**owner}, params={"limit": 1})
    assert page.status_code == 200, page.text
    assert len(page.json()["items"]) == 1
    item = page.json()["items"][0]
    assert item["reportRef"] == report_ref
    assert item["state"] == "AVAILABLE"
    assert item["result"]["reviewRef"] == review.review_ref
    assert item["result"]["proposalCount"] == 1
    assert item["result"]["approvedProposalCount"] == 1
    cursor = page.json().get("nextCursor")
    if cursor is not None:
        second = client.get(history_path, headers=owner, params={"limit": 1, "after": cursor})
        assert second.status_code == 200, second.text
    assert client.get(history_path, headers=foreign).status_code == 404
    assert client.get(history_path, headers=foreign, params={"limit": 1}).status_code == 404
    # Foreign cursors are useless: a fabricated cursor stays non-disclosing.
    assert (
        client.get(
            history_path, headers=foreign, params={"limit": 1, "after": "fabricated-cursor"}
        ).status_code
        == 404
    )
    # Report detail carries the frozen measured numbers plus the
    # review/proposal join counts.
    detail = client.get(f"/v1/sites/site-a/observations/{report_ref}", headers=owner)
    assert detail.status_code == 200, detail.text
    assert detail.json()["result"]["metrics"]["netM3"] == 4.0
    assert detail.json()["result"]["reviewRef"] == review.review_ref
    assert detail.json()["result"]["proposalCount"] == 1
    assert (
        client.get(f"/v1/sites/site-a/observations/{report_ref}", headers=foreign).status_code
        == 404
    )
    # Review/proposal follow-up is readable history, not re-executable success:
    # a second review conflicts, the approved successor is recorded.
    again = client.post(f"/v1/external-relative-volume-reports/{report_ref}/reviews", headers=owner)
    assert again.status_code == 409, again.text
    successor = client.get(f"/v1/observation-work-orders/{successor_id}", headers=owner)
    assert successor.status_code == 200, successor.text
    # Managed row: readable, still not executable after restart.
    readable = client.get(f"/v1/observation-work-orders/{managed.work_order_id}", headers=owner)
    assert readable.status_code == 200, readable.text
    operations = client.get(
        f"/v1/observation-work-orders/{managed.work_order_id}/operations", headers=owner
    )
    assert operations.status_code == 409, operations.text
    assert operations.json()["detail"] == "EXTERNAL_OPERATIONS_ONLY"


def _assert_revocation_distinctions(
    client: TestClient,
    restarted: Any,
    active_now: datetime,
    decision: Any,
    area_id: str,
    baseline_subject: Any,
    current_subject: Any,
    policy: Any,
    restarted_context: Any,
    current_order: Any,
) -> None:
    """History stays readable while fresh unauthorized use is denied."""
    from ksi_core.external_relative_volumes import ExternalRelativeVolumeVerdict

    owner = _op_headers("post-revoke")
    catalog = restarted.state.external_relative_volume_mapping_authority
    resolved = catalog.resolve_for_use(
        baseline=baseline_subject,
        current=current_subject,
        zone_id=area_id,
        policy=policy,
        now=active_now,
    )
    assert resolved is not None
    # Currentness revoked: resolution closes, history reads stay open.
    retained = restarted_context.retained_contexts()[0]
    assert retained.context_digest is not None
    restarted_context.revoke(retained.context_digest)
    assert (
        catalog.resolve_for_use(
            baseline=baseline_subject,
            current=current_subject,
            zone_id=area_id,
            policy=policy,
            now=active_now,
        )
        is None
    )
    history_path = "/v1/sites/site-a/external-relative-volume-reports"
    assert client.get(history_path, headers=owner).status_code == 200
    v1_base = (
        f"/v1/observation-work-orders/{baseline_subject.work_order_id}/"
        "external-reconstruction-submissions"
    )
    assert client.get(v1_base, headers=owner).status_code == 200
    restarted_context.add(retained)
    assert (
        catalog.resolve_for_use(
            baseline=baseline_subject,
            current=current_subject,
            zone_id=area_id,
            policy=policy,
            now=active_now,
        )
        is not None
    )
    # Permission revoked (policy): fresh issue is unavailable, the recorded
    # idempotent retry stays a historical read, history stays readable.
    revoked = restarted.state.external_validation_policy_registry.revoke(
        policy.policy_id,
        policy.version,
        actor="policy-admin",
        now=active_now + timedelta(seconds=1),
    )
    assert revoked.status.value == "REVOKED"
    assert not catalog.is_current_for_use(resolved, now=active_now + timedelta(seconds=1))
    assert (
        restarted.state.external_relative_volume_store.issue(
            principal=_principal(),
            current_work_order_id=current_order.work_order_id,
            decision_ref=decision.decision_id,
            idempotency_key="revoked-policy-fresh-issue",
            now=active_now + timedelta(seconds=1),
        ).verdict
        is ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
    )
    assert (
        restarted.state.external_relative_volume_store.issue(
            principal=_principal(),
            current_work_order_id=current_order.work_order_id,
            decision_ref=decision.decision_id,
            idempotency_key="replay-quantitative-volume",
            now=active_now + timedelta(seconds=1),
        ).verdict
        is ExternalRelativeVolumeVerdict.ALREADY_ISSUED
    )
    assert client.get(history_path, headers=owner).status_code == 200
    # AI consent: the MCP client reads the consented site but not the
    # unconsented one; operator history reads are unaffected by consent.
    # (Route choice mirrors the existing MCP consent contract.)
    assert (
        client.get("/v1/sites/site-a/analysis-observations", headers=_mcp_headers()).status_code
        == 200
    )
    denied = client.get("/v1/sites/site-c/analysis-observations", headers=_mcp_headers())
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"] == "AI_EGRESS_NOT_ALLOWED"
    assert (
        client.get(
            "/v1/sites/site-c/analysis-observations",
            headers={**_op_headers("consent"), "X-KSI-Access-Purpose": "EXTERNAL_AI"},
        ).status_code
        == 200
    )


def test_platform_replay_rejects_corrupt_and_unknown_journal_records(tmp_path: Path) -> None:
    """Corrupt/unknown journal records fail closed on platform boot."""
    import shutil as _shutil

    from ksi_core.durable_journal import JournalRecoveryError

    src = tmp_path / "src"
    src.mkdir(mode=0o700)
    now = datetime.now(UTC).replace(microsecond=0)
    storage = LoopbackObjectStorage()
    policy_authority = _RetainedPolicyAuthority()
    context_authority = _RetainedEvidenceContextAuthority(now)
    workflow, _catalog, envelope, _ = _workflow(
        src,
        now=now,
        policy_authority=policy_authority,
        context_authority=context_authority,
    )
    seed = _ReplayBoot(
        src,
        workflow=workflow,
        envelope=envelope,
        policy_authority=policy_authority,
        context_authority=context_authority,
        storage=storage,
    )
    try:
        area_id = _seed_site(seed.app, "site-a", "Replay site", ai_egress_allowed=True, now=now)
        with TestClient(seed.app) as client:
            _create_external_order(client, area_id, key="corrupt")
    finally:
        seed.close()
    # Garbage bytes: the journal layer refuses to decode.
    garbage_dir = tmp_path / "garbage"
    _shutil.copytree(src, garbage_dir)
    with open(garbage_dir / "observation-work-orders.jsonl", "a", encoding="utf-8") as handle:
        handle.write("not json at all\n")
    with pytest.raises(JournalRecoveryError):
        _fresh_boot(garbage_dir, LoopbackObjectStorage()).close()
    # Unknown record type: the owning store refuses to invent a decoder.
    unknown_dir = tmp_path / "unknown"
    _shutil.copytree(src, unknown_dir)
    with open(unknown_dir / "observation-work-orders.jsonl", "a", encoding="utf-8") as handle:
        handle.write('{"eventType": "unknown-future-event", "foo": 1}\n')
    with pytest.raises(Exception, match="kind|재생 실패|replay|Recovery|recover"):
        _fresh_boot(unknown_dir, LoopbackObjectStorage()).close()
    # The pristine source still boots: corruption never touched it.
    boot = _fresh_boot(src, LoopbackObjectStorage())
    try:
        with TestClient(boot.app) as client:
            listed = client.get("/v1/sites/site-a/observation-work-orders", headers=_op_headers())
            assert listed.status_code == 200, listed.text
            assert len(listed.json()["workOrders"]) == 1
    finally:
        boot.close()
