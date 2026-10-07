"""Platform Core generated-flow HTTP integration (Task 4).

Runs the existing generated-TIFF inspection lane and the fixed Analysis worker
transport against the NEW platform app built by ``assemble_platform_app``
(Task 2 factory) — not the legacy assembly:

  scoped Site/WorkArea/external WorkOrder (HTTP, restricted router)
  -> two sealed V2 DSM derived revisions (HTTP register/upload-grants/seal)
  -> actual byte inspection through the real DSM inspector lane
  -> Analysis result via HTTP intent plus the fixed worker transport
  -> region-data receipt from the platform-mounted spatial-data wiring
  -> same-area next observation (HTTP)

Returned IDs/digests/extent/limitations and the existing hand-oracle
pixels/numerical meanings (2x2 cells, EPSG:5186+5773, cut/fill approx 0.01)
are frozen here. Existing fixture factories (geotiff bytes, V2 seal helper,
lane driver, worker runner) are INPUTS only: every request traverses the
platform app, and factory/route identity is asserted explicitly
(``assemble_platform_app`` module, restricted-router rejections, exact
journal trace without managed/flight stores).

Negative controls prove the assertions are falsifiable: wrong profile
(managed mode), extra journal open, stale submission digest and changed
input bytes each fail closed.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
from ksi_event_contracts.external_analysis_api import AnalysisObservationSelectorV1
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    PolicyStatus,
    SealedExternalSubjectV1,
)
from ksi_mission_contracts.models import SiteFrame
from rasterio.transform import from_origin
from test_external_analysis_execution_integration import (
    _ORIGIN_X,
    _ORIGIN_Y,
    _geotiff_bytes,
)
from test_external_analysis_http_integration import _local_graph_config
from test_external_analysis_real_inspection_lane_integration import (
    _CoreAndObjectServers,
    _drive_two_epochs_through_lane,
    _post_analysis,
)
from test_external_quantitative_production_flow import (
    _digest,
    _RetainedEvidenceContextAuthority,
    _RetainedPolicyAuthority,
    _workflow,
)

_OP_TOKEN = "platform-flow-operator"  # noqa: S105 -- deterministic test credential
_V2_OP_TOKEN = "analysis-local-fixture-operator"  # noqa: S105 -- reused V2 seal helper header
_WORKER_TOKEN = "platform-flow-analysis-worker"  # noqa: S105 -- deterministic test credential
_VALIDATION_WORKER_TOKEN = (  # noqa: S105 -- deterministic test credential
    "platform-flow-validation-worker"
)
_FOREIGN_TOKEN = "platform-flow-foreign"  # noqa: S105 -- deterministic test credential

_TRANSFORM = from_origin(_ORIGIN_X, _ORIGIN_Y, 0.1, 0.1)


def _record(
    token: str,
    principal_id: str,
    organization_id: str,
    kind: PrincipalKind = PrincipalKind.OPERATOR,
    role: Role | None = Role.ADMIN,
) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        principal=Principal(
            principal_id=principal_id,
            kind=kind,
            role=role,
            device_id=None,
            organization_id=organization_id,
        ),
    )


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            _record(_OP_TOKEN, "platform-flow-operator", "org-a"),
            _record(_V2_OP_TOKEN, "analysis-local-operator", "org-a"),
            _record(
                _WORKER_TOKEN,
                "platform-flow-analysis-worker",
                "org-a",
                kind=PrincipalKind.ANALYSIS_WORKER,
                role=None,
            ),
            _record(
                _VALIDATION_WORKER_TOKEN,
                "platform-flow-validation-worker",
                "org-a",
                kind=PrincipalKind.PROCESSING_WORKER,
                role=None,
            ),
            _record(_FOREIGN_TOKEN, "platform-flow-foreign", "org-b"),
        ]
    )


def _op_headers(key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": "Bearer " + _OP_TOKEN}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


class _PlatformFlowContext:
    """Platform app plus the real-participant material the lane/worker need."""

    def __init__(self, tmp_path: Path, *, with_spatial_data: bool = False) -> None:
        self.now = datetime.now(UTC).replace(microsecond=0)
        self.data_dir = tmp_path
        self.storage = LoopbackObjectStorage()
        self.policy_authority = _RetainedPolicyAuthority()
        self.context_authority = _RetainedEvidenceContextAuthority(self.now)
        self.trace: list[str] = []
        self.opened: list[DurableJournal] = []
        workflow, _catalog, self.envelope, _catalog_authority = _workflow(
            tmp_path,
            now=self.now,
            policy_authority=self.policy_authority,
            context_authority=self.context_authority,
        )
        spatial: Any = None
        if with_spatial_data:
            spatial = _spatial_data_config(self.now)
        try:
            self.app = assemble_platform_app(
                tmp_path,
                journal=self._journal,
                opened=self.opened,
                auth_registry=_registry(),
                evidence_storage=self.storage,
                external_result_workflow=workflow,
                external_analysis_local_graph=_local_graph_config(self.envelope),
                spatial_data=spatial,
            )
        except BaseException:
            for journal in reversed(self.opened):
                journal.close()
            raise
        self.site_id = "site-a"
        self.work_area_id = ""
        # Factory identity: this app must come from the Task 2 platform
        # factory, never the retained legacy assembly.
        assert assemble_platform_app.__module__ == ("ksi_core.composition.platform_assembly")
        assert self.app.state.external_analysis_wiring is not None

    def _journal(self, name: str) -> DurableJournal:
        self.trace.append(name)
        item = DurableJournal(self.data_dir / name)
        self.opened.append(item)
        return item

    def close(self) -> None:
        for journal in reversed(self.opened):
            journal.close()


def _spatial_data_config(now: datetime) -> Any:
    from types import SimpleNamespace as _NS

    from ksi_core.composition.spatial_data_graph import (
        SpatialDataLocalAssemblyConfig,
        SpatialDataLocalGraphConfig,
    )
    from ksi_event_contracts.processing_job import ExecutionLocus
    from spatial_data_fixture import make_activation, make_policy, make_runtime
    from spatial_data_job_fixture import LocalJobAuthority
    from test_spatial_data_worker_api import LocalProvider

    policy = make_policy()
    runtime = make_runtime()
    activation = make_activation(
        organization_id="org-a",
        worker_principal_id="platform-data-worker",
        worker_instance_id="platform-data-instance-1",
        policy_digest=policy.policy_digest,
        runtime_digest=runtime.runtime_digest,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(hours=1),
    )
    return SpatialDataLocalAssemblyConfig(
        config=SpatialDataLocalGraphConfig(
            policy=policy,
            runtime=runtime,
            activation=activation,
            processing_location=ExecutionLocus.SITE_ONPREM,
            clock=lambda: now,
        ),
        build_storage=lambda reconstruction: LocalProvider(_NS(reconstruction=reconstruction)),
        build_currentness=lambda coordinator: LocalJobAuthority(
            _NS(
                coordinator=coordinator,
                principal=Principal(
                    principal_id="platform-data-reader",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                    organization_id="org-a",
                ),
            )
        ),
    )


def _seed_site_and_area(ctx: _PlatformFlowContext) -> str:
    app = ctx.app
    registered = app.state.site_store.register(
        "site-a",
        "Platform generated-flow site",
        SiteFrame(
            crs="EPSG:5186",
            vertical_datum="EGM96 height",
            unit="meter",
            transform_version="fixture-v1",
        ),
        organization_id="org-a",
        actor="platform-flow-operator",
        now=ctx.now - timedelta(minutes=30),
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
        "site-a",
        name="Platform generated-flow area",
        polygon=polygon,
        crs="EPSG:5186",
        supersedes=None,
        actor="platform-flow-operator",
        now=ctx.now - timedelta(minutes=29),
    )
    assert area_result.work_area is not None
    ctx.work_area_id = area_result.work_area.work_area_id
    return ctx.work_area_id


def _create_external_order(client: TestClient, area_id: str, *, key: str) -> dict[str, Any]:
    response = client.post(
        "/v1/sites/site-a/observation-work-orders",
        headers=_op_headers(key),
        json={
            "name": "플랫폼 생성 흐름 관측",
            "workAreaIds": [area_id],
            "scheduleId": None,
            "executionMode": "EXTERNAL_RECONSTRUCTION",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["executionMode"] == "EXTERNAL_RECONSTRUCTION"
    return body


def _store_order(ctx: _PlatformFlowContext, work_order_id: str) -> Any:
    order = ctx.app.state.observation_work_order_store.get(work_order_id, organization_id="org-a")
    assert order is not None
    return order


def _seal_two_dsm_revisions(
    ctx: _PlatformFlowContext, client: TestClient, baseline_order: Any, current_order: Any
) -> tuple[Any, SealedExternalSubjectV1, Any, SealedExternalSubjectV1]:
    baseline_bytes = _geotiff_bytes(np.full((2, 2), 100.0), transform=_TRANSFORM)
    current_bytes = _geotiff_bytes(np.array([[101.0, 99.0], [100.0, 100.0]]), transform=_TRANSFORM)
    baseline_revision, baseline_subject = _register_and_seal_v2_dsm(
        client,
        ctx.app,
        baseline_order,
        "platform-flow-baseline",
        start=ctx.now - timedelta(minutes=20),
        end=ctx.now - timedelta(minutes=15),
        storage=ctx.storage,
        dsm_bytes=baseline_bytes,
        organization_id="org-a",
    )
    current_revision, current_subject = _register_and_seal_v2_dsm(
        client,
        ctx.app,
        current_order,
        "platform-flow-current",
        start=ctx.now - timedelta(minutes=10),
        end=ctx.now - timedelta(minutes=5),
        storage=ctx.storage,
        dsm_bytes=current_bytes,
        organization_id="org-a",
    )
    return baseline_revision, baseline_subject, current_revision, current_subject


def _admit_real_inspection_policy(
    ctx: _PlatformFlowContext,
    subjects: tuple[SealedExternalSubjectV1, SealedExternalSubjectV1],
) -> tuple[Any, Any]:
    from ksi_core.external_quantitative_authority import CompatibilityRuleDescriptorV1
    from ksi_core.external_validation_policy import (
        PolicyAuthorityRecord,
        authorized_policy_body_digest,
    )
    from ksi_processing_controller.external_geotiff_profile import (
        external_geotiff_profile_digest_v1,
    )
    from test_external_inspector_container_entrypoint import _manifest

    manifest = _manifest(ctx.envelope)
    template = ExternalValidationPolicyV1(
        policy_id="external-geotiff-v1",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=manifest.parser_build_digest,
        grammar_digest=external_geotiff_profile_digest_v1(),
        resource_envelope=ctx.envelope,
        resource_envelope_digest=ctx.envelope.resource_envelope_digest,
        authority_record_digest=_digest("unbound-real-inspector-authority"),
        inspection_rule_ids=("EXTERNAL_GEOTIFF_MEASURED_V1",),
        evidence_rule_ids=("CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",),
        compatibility_mapping_digests=(CompatibilityRuleDescriptorV1().canonical_digest(),),
        synthetic_test_only=False,
    ).sealed()
    record = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=tuple(subjects),
        permitted_uses=("INSPECTION", "EVIDENCE", "RELATIVE_VOLUME"),
        authorized_actor_ids=("policy-admin",),
        active_from=ctx.now - timedelta(hours=1),
        active_until=ctx.now + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    assert record.digest is not None
    ctx.policy_authority.add(record)
    policy = template.model_copy(
        update={"authority_record_digest": record.digest, "policy_digest": None},
        deep=True,
    ).sealed()
    admitted = ctx.app.state.external_validation_policy_registry.admit(
        policy, actor="policy-admin", now=ctx.now
    )
    assert admitted.status.value == "ADMITTED"
    return policy, manifest


def _lane_view(
    ctx: _PlatformFlowContext,
    baseline_revision: Any,
    baseline_subject: SealedExternalSubjectV1,
    current_revision: Any,
    current_subject: SealedExternalSubjectV1,
    policy: Any,
    manifest: Any,
) -> SimpleNamespace:
    """Adapter exposing the exact attributes the shared lane driver needs."""
    return SimpleNamespace(
        app=ctx.app,
        storage=ctx.storage,
        set_loopback_object_origin=ctx.storage.set_loopback_origin,
        _inspection_policy=policy,
        _baseline_subject=baseline_subject,
        _current_subject=current_subject,
        _baseline_revision=baseline_revision,
        _current_revision=current_revision,
        _inspector_manifest=manifest,
        _fixture_now=ctx.now,
        malformed_current_dsm=False,
        validation_worker_headers=lambda: {"Authorization": "Bearer " + _VALIDATION_WORKER_TOKEN},
    )


def _analysis_view(
    ctx: _PlatformFlowContext,
    baseline_order: Any,
    current_order: Any,
    *,
    label_prefix: str = "platform-flow",
) -> SimpleNamespace:
    from ksi_core.domains.external.ingress.external_reconstruction import (
        build_external_reconstruction_submission_ref,
    )

    baseline_subject_id = "external-" + label_prefix + "-baseline"
    current_subject_id = "external-" + label_prefix + "-current"
    return SimpleNamespace(
        site_id=ctx.site_id,
        work_area_id=ctx.work_area_id,
        baseline=AnalysisObservationSelectorV1(
            work_order_id=baseline_order.work_order_id,
            submission_ref=build_external_reconstruction_submission_ref(
                organization_id="org-a",
                work_order_id=baseline_order.work_order_id,
                submission_id=baseline_subject_id,
            ),
            revision=1,
        ),
        current=AnalysisObservationSelectorV1(
            work_order_id=current_order.work_order_id,
            submission_ref=build_external_reconstruction_submission_ref(
                organization_id="org-a",
                work_order_id=current_order.work_order_id,
                submission_id=current_subject_id,
            ),
            revision=1,
        ),
        operator_headers=lambda: {"Authorization": "Bearer " + _OP_TOKEN},
    )


def _run_analysis_worker(
    ctx: _PlatformFlowContext, *, core_origin: str, object_origin: str
) -> None:
    from ksi_processing_controller.external_analysis_core_client import (
        ExternalAnalysisCoreClient,
    )
    from ksi_processing_controller.external_analysis_worker import (
        ProcessingWorkerRuntimeIdentityV1,
        run_once,
    )
    from ksi_processing_controller.external_object_streams import (
        ExternalObjectTransportPolicyV1,
        TrustedObjectEndpointV1,
    )

    facts = ctx.app.state.external_analysis_wiring.facade._assessments._runtime  # noqa: SLF001
    envelope = ctx.app.state.external_analysis_wiring.calculations._resource_envelope  # noqa: SLF001
    runtime = ProcessingWorkerRuntimeIdentityV1(
        worker_executable_digest=facts.worker_executable_digest,
        worker_build_digest=facts.worker_build_digest,
        runtime_image_version=facts.runtime_image_version,
        runtime_image_oci_digest=facts.runtime_image_oci_digest,
        dependency_lock_digest=facts.dependency_lock_digest,
    )
    analysis_client = ExternalAnalysisCoreClient(
        base_url=core_origin,
        worker_token=_WORKER_TOKEN,
        worker_instance_id="platform-flow-analysis-worker",
    )
    object_policy = ExternalObjectTransportPolicyV1(
        endpoints=(TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),),
        max_header_bytes=16_384,
        max_object_bytes=envelope.max_input_bytes,
        max_chunk_bytes=min(65_536, envelope.max_input_bytes),
    )
    try:
        assert run_once(analysis_client, runtime, object_policy)
    finally:
        analysis_client.close()


def test_generated_tiff_inspection_feeds_analysis_worker_on_platform_app(
    tmp_path: Path,
) -> None:
    """End-to-end generated flow through the platform factory (not legacy)."""
    import httpx

    ctx = _PlatformFlowContext(tmp_path, with_spatial_data=True)
    try:
        area_id = _seed_site_and_area(ctx)
        with TestClient(ctx.app) as client:
            baseline_created = _create_external_order(client, area_id, key="flow-baseline")
            current_created = _create_external_order(client, area_id, key="flow-current")
            assert baseline_created["workOrderId"] != current_created["workOrderId"]
            # Route identity: the restricted platform router served these
            # creates; the managed schedule mutation surface stays absent.
            assert client.post(
                "/v1/sites/site-a/observation-schedules", headers=_op_headers()
            ).status_code in (404, 405)
            baseline_order = _store_order(ctx, baseline_created["workOrderId"])
            current_order = _store_order(ctx, current_created["workOrderId"])
            revisions = _seal_two_dsm_revisions(ctx, client, baseline_order, current_order)
            baseline_revision, baseline_subject, current_revision, current_subject = revisions
            # Freeze sealed identities: submission/manifest digests are set
            # and the observed bytes hash to the declared manifest entries.
            for revision in (baseline_revision, current_revision):
                assert revision.submission.submission_digest is not None
                assert revision.manifest is not None
                assert revision.manifest.manifest_digest is not None
                assert revision.manifest.entries[0].kind.value == "dsm"
            policy, manifest = _admit_real_inspection_policy(
                ctx, (baseline_subject, current_subject)
            )
            view = _lane_view(
                ctx,
                baseline_revision,
                baseline_subject,
                current_revision,
                current_subject,
                policy,
                manifest,
            )
            with _CoreAndObjectServers(view) as servers:
                reports = _drive_two_epochs_through_lane(
                    view,
                    core_origin=servers.core_origin,
                    object_origin=servers.object_origin,
                    tmp_path=tmp_path,
                )
                assert len(reports) == 2
                # Freeze the actual measured raster geometry (hand oracle:
                # 2x2 generated cells at the fixed origin).
                for report in reports:
                    outcome = report.measurement_payload.outcomes[0]
                    assert outcome.outcome.value == "MEASURED"
                    measured = outcome.measurements
                    assert (measured.width, measured.height, measured.valid_pixel_count) == (
                        2,
                        2,
                        4,
                    )
                    assert measured.transform == (0.1, 0.0, 200000.0, 0.0, -0.1, 550000.0)
                    assert measured.observed_crs_identifier == "EPSG:5186"
                analysis_view = _analysis_view(ctx, baseline_order, current_order)
                intent = _post_analysis(
                    analysis_view, servers.core_origin, "platform-flow-analysis"
                )
                assert intent["suitabilityState"] == "PROVISIONAL_ACCURACY_UNVERIFIED"
                assert intent["executionState"] == "QUEUED"
                analysis_id = intent["analysisId"]
                _run_analysis_worker(
                    ctx,
                    core_origin=servers.core_origin,
                    object_origin=servers.object_origin,
                )
                with httpx.Client(base_url=servers.core_origin, trust_env=False) as operator:
                    detail_url = f"/v1/sites/site-a/analyses/{analysis_id}"
                    detail = operator.get(
                        detail_url, headers={"Authorization": "Bearer " + _OP_TOKEN}
                    )
                    result = operator.get(
                        detail_url + "/result", headers={"Authorization": "Bearer " + _OP_TOKEN}
                    )
                    evidence = operator.get(
                        detail_url + "/evidence", headers={"Authorization": "Bearer " + _OP_TOKEN}
                    )
                assert detail.status_code == result.status_code == evidence.status_code == 200
                assert detail.json()["executionState"] == "COMPLETED"
                # Freeze the existing numerical meanings (hand oracle).
                metrics = result.json()["result"]["metrics"]
                assert metrics["cutM3"] == pytest.approx(0.01)
                assert metrics["fillM3"] == pytest.approx(0.01)
                assert metrics["netM3"] == pytest.approx(0.0)
                assert metrics["uncertaintyM3"] is None
                assert (
                    evidence.json()["baseline"]["inspectionReportDigest"]
                    == reports[0].report_digest
                )
                assert (
                    evidence.json()["current"]["inspectionReportDigest"] == reports[1].report_digest
                )
                for epoch_key, revision in (
                    ("baseline", baseline_revision),
                    ("current", current_revision),
                ):
                    epoch = evidence.json()[epoch_key]
                    entry = revision.manifest.entries[0]
                    assert epoch["observedSha256"] == "sha256:" + entry.observed_sha256
                    assert epoch["observedCrsIdentifier"] == "EPSG:5186"
                    assert epoch["verticalReferenceIdentifier"] == "EPSG:5773"
                    assert epoch["transform"] == [0.1, 0.0, 200000.0, 0.0, -0.1, 550000.0]
            # Region-data receipt from the platform-mounted spatial wiring.
            _assert_region_data_receipt(ctx, current_revision)
            # Same-area next observation stays available through the platform router.
            follow_up = _create_external_order(client, area_id, key="flow-follow-up")
            assert follow_up["workOrderId"] not in {
                baseline_created["workOrderId"],
                current_created["workOrderId"],
            }
            listed = client.get("/v1/sites/site-a/observation-work-orders", headers=_op_headers())
            assert listed.status_code == 200, listed.text
            assert {
                baseline_created["workOrderId"],
                current_created["workOrderId"],
                follow_up["workOrderId"],
            } <= {item["workOrderId"] for item in listed.json()["workOrders"]}
    finally:
        ctx.close()


def _assert_region_data_receipt(ctx: _PlatformFlowContext, current_revision: Any) -> None:
    """Issue/lease/receipt a native region window from the platform data lane."""
    from types import SimpleNamespace as _NS

    from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog
    from spatial_data_fixture import make_grant
    from spatial_data_job_fixture import receipt_for

    lane = ctx.app.state.spatial_data
    assert lane is not None
    assert lane.jobs.coordinator is ctx.app.state.external_authority_currentness
    reader = Principal(
        principal_id="platform-data-reader",
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id="org-a",
    )
    worker = Principal(
        principal_id="platform-data-worker",
        kind=PrincipalKind.SPATIAL_DATA_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )
    items = SpatialAssetCatalog(
        reconstruction=ctx.app.state.external_reconstruction_store,
        work_orders=ctx.app.state.observation_work_order_store,
        sites=ctx.app.state.site_store,
        work_areas=ctx.app.state.work_area_store,
        inspections=ctx.app.state.external_artifact_inspection_store,
    ).items(ctx.site_id, ctx.work_area_id, reader)
    current_items = [
        item
        for item in items
        if item.artifact_id == current_revision.manifest.entries[0].artifact_id
    ]
    assert current_items, "sealed current DSM must be discoverable as a region source"
    candidate = current_items[0]
    source = lane.sources.resolve(
        site_id=ctx.site_id,
        work_area_id=ctx.work_area_id,
        asset_ref=candidate.asset_ref,
        principal=reader,
    )
    measurements = source.inspection.measurements
    assert measurements is not None
    assert (measurements.width, measurements.height) == (2, 2)
    grant = make_grant(
        grant_id="platform-region-grant",
        organization_id="org-a",
        beneficiary_principal_id="platform-data-reader",
        asset_ref=candidate.asset_ref,
        site_id=ctx.site_id,
        work_area_id=ctx.work_area_id,
        allowed_bounds=(
            float(_ORIGIN_X) - 1.0,
            float(_ORIGIN_Y) - 1.0,
            float(_ORIGIN_X) + 1.0,
            float(_ORIGIN_Y) + 1.0,
        ),
        observed_crs_digest=measurements.observed_crs_digest,
        policy_digest=lane.config.policy.policy_digest,
        valid_from=ctx.now - timedelta(minutes=1),
        valid_until=ctx.now + timedelta(hours=1),
    )
    lane.grants.provision(grant)
    from ksi_event_contracts.spatial_data import (
        SpatialDataPurposeV1,
        SpatialDataRequestV1,
    )

    request = SpatialDataRequestV1(
        asset_ref=candidate.asset_ref,
        requested_bounds=(
            float(_ORIGIN_X),
            float(_ORIGIN_Y) - 0.2,
            float(_ORIGIN_X) + 0.2,
            float(_ORIGIN_Y),
        ),
        observed_crs_digest=measurements.observed_crs_digest,
        resolution_mode="NATIVE",
        purpose=SpatialDataPurposeV1.GENERAL_DATA_USE,
    )
    job = lane.jobs.issue(
        site_id=ctx.site_id,
        work_area_id=ctx.work_area_id,
        request=request,
        principal=reader,
        idempotency_key="platform-region",
        now=ctx.now,
    )
    adapter = _NS(
        source=source,
        area=_NS(work_area_id=ctx.work_area_id),
        principal=reader,
        worker=worker,
    )
    attempt = lane.jobs.lease(
        job_id=job.job_id,
        worker=worker,
        instance_id="platform-data-instance-1",
        acquisition_id="platform-region-acquisition-1",
        now=ctx.now,
    )
    receipt = receipt_for(lane.jobs, adapter, job, attempt, now=ctx.now)
    # Freeze the native region geometry (full 2x2 extent, no resampling).
    assert receipt.pixel_window == (0, 2, 0, 2)
    assert receipt.width == 2 and receipt.height == 2
    assert receipt.transform == (0.1, 0.0, float(_ORIGIN_X), 0.0, -0.1, float(_ORIGIN_Y))
    assert receipt.observed_crs_identifier == "EPSG:5186"
    assert receipt.source_sha256 == "sha256:" + current_revision.manifest.entries[0].observed_sha256
    assert receipt.valid_pixel_count == 4


def _v1_wire(order: Any, *, submitted_by: str = "platform-flow-operator") -> dict[str, Any]:
    """V1 declaration wire bound to this file's operator principal identity."""
    import hashlib as _hashlib

    from ksi_core.domains.observations.epoch_identity import observation_epoch_id
    from ksi_event_contracts.external_reconstruction import (
        ExternalReconstructionSubmissionV1 as _V1,
    )

    payload = b"ortho bytes"
    wire = {
        "submissionId": "external-001",
        "revision": 1,
        "organizationId": "org-a",
        "siteId": "site-a",
        "observationEpochId": observation_epoch_id(order),
        "submittedAt": "2026-10-07T00:00:00Z",
        "submittedBy": submitted_by,
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "softwareName": "Customer Mapper",
            "softwareVersion": "1.0",
            "buildIdentifier": None,
            "producerRunIdentifier": None,
            "configurationDigest": None,
            "completedAt": None,
        },
        "inputDeclaration": {
            "rawMediaStoredByKsi": False,
            "originalRetentionLocus": "customer_workstation",
            "localInputManifestDigest": None,
            "imageCount": None,
            "captureStartedAt": "2026-10-07T00:00:00Z",
            "captureEndedAt": "2026-10-07T00:10:00Z",
        },
        "artifacts": [
            {
                "artifactId": "ortho",
                "kind": "ortho",
                "fileName": "ortho.tif",
                "format": "GeoTIFF",
                "contentType": "application/octet-stream",
                "declaredSha256": _hashlib.sha256(payload).hexdigest(),
                "declaredSizeBytes": len(payload),
                "declaredCrs": None,
                "declaredVerticalReference": None,
                "declaredGsdM": None,
            }
        ],
    }
    wire["submissionDigest"] = _V1.digest_for_wire(wire)
    return wire


def test_malformed_current_dsm_blocks_analysis_on_platform_app(tmp_path: Path) -> None:
    """The real parser rejection (not a mock) blocks Analysis on the platform app."""
    ctx = _PlatformFlowContext(tmp_path)
    try:
        area_id = _seed_site_and_area(ctx)
        with TestClient(ctx.app) as client:
            baseline_order = _store_order(
                ctx, _create_external_order(client, area_id, key="blocked-baseline")["workOrderId"]
            )
            current_order = _store_order(
                ctx, _create_external_order(client, area_id, key="blocked-current")["workOrderId"]
            )
            baseline_bytes = _geotiff_bytes(np.full((2, 2), 100.0), transform=_TRANSFORM)
            baseline_revision, baseline_subject = _register_and_seal_v2_dsm(
                client,
                ctx.app,
                baseline_order,
                "platform-blocked-baseline",
                start=ctx.now - timedelta(minutes=20),
                end=ctx.now - timedelta(minutes=15),
                storage=ctx.storage,
                dsm_bytes=baseline_bytes,
                organization_id="org-a",
            )
            current_revision, current_subject = _register_and_seal_v2_dsm(
                client,
                ctx.app,
                current_order,
                "platform-blocked-current",
                start=ctx.now - timedelta(minutes=10),
                end=ctx.now - timedelta(minutes=5),
                storage=ctx.storage,
                dsm_bytes=b"malformed-current-dsm",
                organization_id="org-a",
            )
            policy, manifest = _admit_real_inspection_policy(
                ctx, (baseline_subject, current_subject)
            )
            view = _lane_view(
                ctx,
                baseline_revision,
                baseline_subject,
                current_revision,
                current_subject,
                policy,
                manifest,
            )
            view.malformed_current_dsm = True
            with _CoreAndObjectServers(view) as servers:
                reports = _drive_two_epochs_through_lane(
                    view,
                    core_origin=servers.core_origin,
                    object_origin=servers.object_origin,
                    tmp_path=tmp_path,
                )
                assert reports[0].measurement_payload.outcomes[0].outcome.value == "MEASURED"
                assert reports[1].measurement_payload.outcomes[0].outcome.value == "REJECTED"
                assert reports[1].measurement_payload.outcomes[0].reason == "MALFORMED_TIFF"
                analysis_view = _analysis_view(
                    ctx, baseline_order, current_order, label_prefix="platform-blocked"
                )
                intent = _post_analysis(
                    analysis_view, servers.core_origin, "platform-blocked-analysis"
                )
                assert intent["suitabilityState"] == "BLOCKED"
                assert intent["executionState"] == "NOT_STARTED"
                assert intent["result"] is None
                assert any(
                    item["code"] == "ESSENTIAL_INPUT_UNAVAILABLE" for item in intent["blockers"]
                )
    finally:
        ctx.close()


def test_wrong_profile_cannot_enter_generated_flow(tmp_path: Path) -> None:
    """Managed-mode creation/operations are rejected by the platform profile.

    The restricted router — not the store — enforces the profile: a retained
    managed row stays readable as history but cannot gain operations or a
    managed schedule mutation through this app.
    """
    ctx = _PlatformFlowContext(tmp_path)
    try:
        area_id = _seed_site_and_area(ctx)
        with TestClient(ctx.app) as client:
            explicit = client.post(
                "/v1/sites/site-a/observation-work-orders",
                headers=_op_headers("wrong-explicit"),
                json={
                    "name": "관리 관측",
                    "workAreaIds": [area_id],
                    "scheduleId": None,
                    "executionMode": "MANAGED_ACQUISITION",
                },
            )
            assert explicit.status_code == 422, explicit.text
            assert explicit.json()["detail"] == "EXTERNAL_RECONSTRUCTION_REQUIRED"
            omitted = client.post(
                "/v1/sites/site-a/observation-work-orders",
                headers=_op_headers("wrong-omitted"),
                json={"name": "기본 관측", "workAreaIds": [area_id], "scheduleId": None},
            )
            assert omitted.status_code == 422, omitted.text
            assert omitted.json()["detail"] == "EXTERNAL_RECONSTRUCTION_REQUIRED"
            # Managed mutation routes are absent from the platform surface.
            assert client.post(
                "/v1/sites/site-a/observation-schedules", headers=_op_headers()
            ).status_code in (404, 405)
            store = ctx.app.state.observation_work_order_store
            managed = store.create_work_order(
                organization_id="org-a",
                site_id="site-a",
                name="Retained managed row",
                work_area_ids=[area_id],
                schedule_id=None,
                actor="fixture",
                now=ctx.now,
            )
            readable = client.get(
                f"/v1/observation-work-orders/{managed.work_order_id}", headers=_op_headers()
            )
            assert readable.status_code == 200, readable.text
            operations = client.get(
                f"/v1/observation-work-orders/{managed.work_order_id}/operations",
                headers=_op_headers(),
            )
            assert operations.status_code == 409, operations.text
            assert operations.json()["detail"] == "EXTERNAL_OPERATIONS_ONLY"
            assignment = client.post(
                f"/v1/observation-work-orders/{managed.work_order_id}/operations/assignment",
                headers=_op_headers("wrong-assign"),
                json={"expectedOperationsRevision": 1, "action": "ASSIGN_TO_ME"},
            )
            assert assignment.status_code == 409, assignment.text
    finally:
        ctx.close()


def test_platform_opens_no_extra_journal(tmp_path: Path) -> None:
    """The fully-wired platform graph opens exactly its fixed journal set."""
    ctx = _PlatformFlowContext(tmp_path, with_spatial_data=True)
    try:
        basenames = sorted(Path(name).name for name in ctx.trace)
        assert basenames == [
            "external-analysis-assessments.jsonl",
            "external-analysis-calculations.jsonl",
            "external-analysis-intents.jsonl",
            "external-analysis-reviews.jsonl",
            "external-artifact-inspections.jsonl",
            "external-evidence-validations.jsonl",
            "external-evidence.jsonl",
            "external-reconstruction.jsonl",
            "external-relative-volumes.jsonl",
            "external-reobservation-proposals.jsonl",
            "external-result-reviews.jsonl",
            "external-sanitized-display-artifacts.jsonl",
            "external-single-volumes.jsonl",
            "external-use-decisions.jsonl",
            "external-validation-policy.jsonl",
            "observation-work-orders.jsonl",
            "organization-work-roster.jsonl",
            "quantitative-authority.jsonl",
            "sites.jsonl",
            "spatial-data-grants.jsonl",
            "spatial-data-jobs.jsonl",
            "spatial-data-metadata-audit.jsonl",
            "work-areas.jsonl",
            "work-inbox.jsonl",
        ]
        for name in basenames:
            lowered = name.lower()
            for denied in (
                "mission",
                "edge",
                "flight",
                "acquisition",
                "processing",
                "source-media",
                "capability",
                "device",
                "copilot",
            ):
                assert denied not in lowered, name
    finally:
        ctx.close()


def test_stale_submission_digest_rejected(tmp_path: Path) -> None:
    """A declaration mutated after its digest was computed is rejected."""
    ctx = _PlatformFlowContext(tmp_path)
    try:
        area_id = _seed_site_and_area(ctx)
        with TestClient(ctx.app) as client:
            order = _store_order(
                ctx, _create_external_order(client, area_id, key="stale")["workOrderId"]
            )
            wire = _v1_wire(order)
            wire["artifacts"][0]["declaredSizeBytes"] = 999
            base = (
                f"/v1/observation-work-orders/{order.work_order_id}/"
                "external-reconstruction-submissions"
            )
            rejected = client.post(base, headers=_op_headers(), json=wire)
            assert rejected.status_code == 422, rejected.text
            listed = client.get(base, headers=_op_headers())
            assert listed.status_code == 200, listed.text
            assert listed.json().get("submissions", []) == []
    finally:
        ctx.close()


def test_changed_input_bytes_fail_seal_closed(tmp_path: Path) -> None:
    """Bytes that do not match the declaration never produce a sealed revision."""
    ctx = _PlatformFlowContext(tmp_path)
    try:
        area_id = _seed_site_and_area(ctx)
        with TestClient(ctx.app) as client:
            order = _store_order(
                ctx, _create_external_order(client, area_id, key="changed")["workOrderId"]
            )
            wire = _v1_wire(order)
            base = (
                f"/v1/observation-work-orders/{order.work_order_id}/"
                "external-reconstruction-submissions"
            )
            registered = client.post(base, headers=_op_headers(), json=wire)
            assert registered.status_code == 201, registered.text
            revision_path = f"{base}/{registered.json()['submissionRef']}/revisions/1"
            grants = client.post(revision_path + "/upload-grants", headers=_op_headers())
            assert grants.status_code == 200, grants.text
            ctx.storage.put_bytes(
                grants.json()["grants"][0]["objectKey"],
                b"tampered-bytes",
                content_type="application/octet-stream",
            )
            sealed = client.post(revision_path + "/seal", headers=_op_headers())
            assert sealed.status_code == 422, sealed.text
            assert sealed.json()["detail"] == "OBSERVATION_MISMATCH"
            fetched = client.get(revision_path, headers=_op_headers())
            assert fetched.status_code == 200, fetched.text
            assert fetched.json()["manifest"] is None
            inspection = client.get(revision_path + "/inspection", headers=_op_headers())
            assert inspection.status_code == 200, inspection.text
            assert inspection.json()["inspection"]["state"] == "INSPECTION_PENDING_SEAL"
    finally:
        ctx.close()


def _walk_routes(container: Any) -> list[Any]:
    """Unfold ``_IncludedRouter`` wrappers (FastAPI 0.140) to the real routes."""
    found: list[Any] = []
    for route in getattr(container, "routes", None) or []:
        if getattr(route, "methods", None) and getattr(route, "path", None):
            found.append(route)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            found.extend(_walk_routes(inner))
    return found


def test_platform_route_inventory_has_no_flight_or_managed_mutation_surface(
    tmp_path: Path,
) -> None:
    """Route/OpenAPI inventory on the fully-wired platform app."""
    ctx = _PlatformFlowContext(tmp_path, with_spatial_data=True)
    try:
        inventory = {(route.path, next(iter(route.methods))) for route in _walk_routes(ctx.app)}
        paths = {path for path, _ in inventory}
        # Real platform surface is present (external flow + analysis + data).
        assert ("/v1/sites/{site_id}/observation-work-orders", "POST") in inventory
        assert (
            "/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions",
            "POST",
        ) in inventory
        assert ("/v1/sites/{site_id}/work-areas/{work_area_id}/analyses", "POST") in inventory
        assert (
            "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests",
            "POST",
        ) in inventory
        assert ("/v1/external-relative-volume-reports/{report_ref}/reviews", "POST") in inventory
        assert ("/health", "GET") in inventory
        # Managed mutation surface is absent.
        assert ("/v1/sites/{site_id}/observation-schedules", "POST") not in inventory
        assert ("/v1/observation-work-orders/{work_order_id}/approve", "POST") not in inventory
        assert (
            "/v1/observation-work-orders/{work_order_id}/reobservation-drafts",
            "POST",
        ) not in inventory
        assert ("/v1/reobservation-drafts/{draft_id}/approve", "POST") not in inventory
        # No flight or managed-processing surface, no capability catalog.
        # Segment-exact matching: naive substrings collide with legitimate
        # words (e.g. "mission" in "submissions").
        assert "/capabilities" not in paths
        denied_segments = {
            "flight",
            "flights",
            "missions",
            "edges",
            "acquisitions",
            "copilot",
            "processing-jobs",
            "processing-job",
            "source-media",
            "comparisons",
            "capabilities",
            "devices",
        }
        for path in paths:
            segments = set(path.lower().split("/"))
            assert not (segments & denied_segments), path
    finally:
        ctx.close()
