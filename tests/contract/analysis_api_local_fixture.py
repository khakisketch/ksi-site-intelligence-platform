"""Reusable fully assembled local Analysis API fixture for HTTP/browser tests.

It is test-only.  The fixture supplies explicit local runtime material and
actual GeoTIFF bytes; it neither reads production configuration nor claims a
signed release/runtime proof.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.domains.external.ingress.external_reconstruction import (
    build_external_reconstruction_submission_ref,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_quantitative_authority import CompatibilityRuleDescriptorV1
from ksi_core.external_validation_policy import PolicyAuthorityRecord, authorized_policy_body_digest
from ksi_event_contracts.external_analysis_api import AnalysisObservationSelectorV1
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    ObservedVerticalReferenceV1,
    PolicyStatus,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1
from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV2
from ksi_event_contracts.observation_work_order import ObservationWorkOrderExecutionMode
from ksi_mission_contracts.models import SiteFrame
from pyproj import CRS
from rasterio.io import MemoryFile
from rasterio.transform import Affine, from_origin
from test_external_analysis_execution_integration import _ORIGIN_X, _ORIGIN_Y, _geotiff_bytes
from test_external_analysis_http_integration import (
    _assemble_local_analysis_app,
    _local_graph_config,
)
from test_external_quantitative_production_flow import (
    _admit_policy,
    _digest,
    _inspect,
    _LocalObjectStorage,
    _RetainedEvidenceContextAuthority,
    _RetainedPolicyAuthority,
    _sealed_revision,
    _submission,
    _validate_evidence,
    _workflow,
)

_OPERATOR_TOKEN = "analysis-local-fixture-operator"
_WORKER_TOKEN = "analysis-local-fixture-worker"
_VALIDATION_WORKER_TOKEN = "analysis-local-fixture-validation-worker"
_VIEWER_TOKEN = "analysis-local-fixture-viewer"
_MCP_CLIENT_TOKEN = "analysis-local-fixture-mcp-client"
_MCP_OTHER_AREA_TOKEN = "analysis-local-fixture-mcp-other-area"


def _geotiff_with_measured_spatial_case(
    values: np.ndarray, *, transform: Any, crs: str, nodata: float | None = None
) -> bytes:
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=values.shape[0],
            width=values.shape[1],
            count=1,
            dtype="float64",
            crs=CRS.from_user_input(crs),
            transform=transform,
            nodata=nodata,
        ) as dataset:
            dataset.write(values, 1)
        return memory.read()


class LoopbackObjectStorage(_LocalObjectStorage):
    """Test storage with real retained bytes and an explicitly set loopback URL origin."""

    def __init__(self) -> None:
        super().__init__()
        self._loopback_origin: str | None = None

    def set_loopback_origin(self, origin: str) -> None:
        if not origin.startswith("http://127.0.0.1:"):
            raise ValueError(
                "local Analysis fixture only permits an explicit loopback object origin"
            )
        self._loopback_origin = origin.rstrip("/")

    def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
        del ttl
        if self._loopback_origin is None:
            # Setup helpers may resolve input capabilities while sealing the
            # fixture.  That URL is never given to a worker before the test
            # configures its own loopback server.
            return "http://127.0.0.1:0/objects/" + quote(object_key, safe="")
        return self._loopback_origin + "/objects/" + quote(object_key, safe="")

    def object_bytes(self, object_key: str) -> bytes:
        return self.get_bytes(object_key)


@dataclass(slots=True)
class LocalAnalysisApiFixture:
    """Assembled local graph, scoped selectors, and test credentials without token logging."""

    app: FastAPI
    opened: list[DurableJournal]
    storage: LoopbackObjectStorage
    site_id: str
    work_area_id: str
    organization_id: str
    baseline: AnalysisObservationSelectorV1
    current: AnalysisObservationSelectorV1
    third: AnalysisObservationSelectorV1 | None
    v2_dsm_only: bool
    failed_checkpoint_current: bool
    failed_checkpoint_baseline: bool
    passed_and_failed_checkpoint_current: bool
    passed_checkpoint_epochs: tuple[str, ...]
    synthetic_inspection_report_digests: tuple[str, ...] = field(repr=False)
    synthetic_epoch_chronology: tuple[
        tuple[datetime, datetime, datetime, datetime], ...
    ] = field(repr=False)
    synthetic_policy_admitted_at: datetime = field(repr=False)
    _current_revision: Any = field(repr=False)
    _current_subject: Any = field(repr=False)
    _baseline_revision: Any = field(repr=False)
    _baseline_subject: Any = field(repr=False)
    _third_revision: Any = field(repr=False)
    _third_subject: Any = field(repr=False)
    _inspection_policy: Any = field(repr=False)
    _inspector_manifest: Any = field(repr=False)
    real_inspection: bool
    malformed_current_dsm: bool
    current_dsm_spatial_case: str
    _fixture_now: datetime = field(repr=False)
    _operator_token: str = field(repr=False)
    _worker_token: str = field(repr=False)
    _validation_worker_token: str = field(repr=False)
    _viewer_token: str = field(repr=False)
    _mcp_client_token: str = field(repr=False)
    _mcp_other_area_token: str = field(repr=False)
    _context_authority: _RetainedEvidenceContextAuthority = field(repr=False)
    _retained_policy_records: tuple[PolicyAuthorityRecord, ...] = field(repr=False)
    _retained_contexts: tuple[ExternalEvidenceMeasurementContextV1, ...] = field(repr=False)

    def operator_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self._operator_token}

    def worker_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self._worker_token}

    def validation_worker_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self._validation_worker_token}

    def viewer_headers(self) -> dict[str, str]:
        """Return a scoped read-only credential for authorization-boundary tests."""
        return {"Authorization": "Bearer " + self._viewer_token}

    def mcp_client_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self._mcp_client_token}

    def mcp_other_area_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self._mcp_other_area_token}

    def set_loopback_object_origin(self, origin: str) -> None:
        self.storage.set_loopback_origin(origin)

    def revoke_evidence_context(self, context_digest: str) -> None:
        """Test-only currentness mutation for exact AP/NX transition coverage."""
        self._context_authority.revoke(context_digest)

    def restore_evidence_context(self, context_digest: str) -> None:
        """Restore one initially retained test context without inventing a record."""
        context = next(
            (
                item
                for item in self._retained_contexts
                if getattr(item, "context_digest", None) == context_digest
            ),
            None,
        )
        if context is None:
            raise LookupError("fixture context is not retained")
        self._context_authority.add(context)

    def append_failed_current_checkpoint_evaluation(self) -> Any:
        """Append a later Core REJECTED evaluation for the exact current DSM bytes."""
        if not self.v2_dsm_only:
            raise ValueError("late checkpoint evaluation requires the V2 DSM-only fixture")
        now = max(
            datetime.now(UTC).replace(microsecond=0),
            self._fixture_now + timedelta(seconds=1),
        )
        record = _validate_evidence(
            self.app,
            revision=self._current_revision,
            subject=self._current_subject,
            policy=self._inspection_policy,
            context_authority=self._context_authority,
            now=now,
            storage=self.storage,
            label="analysis-local-current-late-rejected-checkpoint",
            checkpoint_count=1,
            organization_id=self.organization_id,
        )
        self._retained_contexts = self._context_authority.retained_contexts()
        return record

    def close(self) -> None:
        for journal in reversed(self.opened):
            journal.close()


def _register_and_seal_v2_dsm(
    client: TestClient,
    app: FastAPI,
    order: Any,
    label: str,
    *,
    start: datetime,
    end: datetime,
    storage: LoopbackObjectStorage,
    dsm_bytes: bytes,
    organization_id: str = "org-a",
) -> tuple[Any, SealedExternalSubjectV1]:
    """Exercise V2 HTTP registration and shared digest-bound upload/seal routes."""
    candidate, contents = _submission(
        order, label, start=start, end=end, dsm_bytes=dsm_bytes
    )
    wire = candidate.model_dump(by_alias=True, mode="json")
    wire["contractVersion"] = "external-reconstruction-submission.v2"
    wire["submittedBy"] = "analysis-local-operator"
    wire["organizationId"] = organization_id
    wire["artifacts"] = [artifact for artifact in wire["artifacts"] if artifact["kind"] == "dsm"]
    wire["submissionDigest"] = ExternalReconstructionSubmissionV2.digest_for_wire(wire)

    v2_path = (
        f"/v1/observation-work-orders/{order.work_order_id}/"
        "external-reconstruction-submissions-v2"
    )
    registered = client.post(
        v2_path,
        headers={"Authorization": "Bearer " + _OPERATOR_TOKEN},
        json=wire,
    )
    assert registered.status_code == 201, registered.text
    response_body = registered.json()
    assert response_body["submission"]["contractVersion"] == (
        "external-reconstruction-submission.v2"
    )
    assert [item["kind"] for item in response_body["submission"]["artifacts"]] == ["dsm"]

    submission_ref = response_body["submissionRef"]
    shared_path = (
        f"/v1/observation-work-orders/{order.work_order_id}/"
        f"external-reconstruction-submissions/{submission_ref}/revisions/1"
    )
    fetched = client.get(shared_path, headers={"Authorization": "Bearer " + _OPERATOR_TOKEN})
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["submission"] == response_body["submission"]
    grants = client.post(
        shared_path + "/upload-grants",
        headers={"Authorization": "Bearer " + _OPERATOR_TOKEN},
    )
    assert grants.status_code == 200, grants.text
    assert len(grants.json()["grants"]) == 1
    grant = grants.json()["grants"][0]
    assert grant["artifactId"] == response_body["submission"]["artifacts"][0]["artifactId"]
    storage.put_bytes(
        grant["objectKey"],
        contents[grant["artifactId"]],
        content_type="application/octet-stream",
    )
    sealed = client.post(
        shared_path + "/seal",
        headers={"Authorization": "Bearer " + _OPERATOR_TOKEN},
    )
    assert sealed.status_code == 200, sealed.text
    assert [entry["kind"] for entry in sealed.json()["manifest"]["entries"]] == ["dsm"]

    record = app.state.external_reconstruction_store.get(
        order.work_order_id,
        candidate.submission_id,
        1,
        organization_id=organization_id,
        site_id="site-a",
    )
    assert record is not None and record.manifest is not None
    assert record.submission.submission_digest == wire["submissionDigest"]
    subject = SealedExternalSubjectV1(
        organization_id=organization_id,
        site_id="site-a",
        work_order_id=order.work_order_id,
        submission_id=candidate.submission_id,
        revision=1,
        submission_digest=record.submission.submission_digest,
        manifest_digest=record.manifest.manifest_digest,
    )
    return record, subject


def build_local_analysis_api_fixture(
    tmp_path: Path,
    *,
    v2_dsm_only: bool | None = None,
    include_third_epoch: bool | None = None,
    failed_checkpoint_current: bool = False,
    failed_checkpoint_baseline: bool = False,
    passed_and_failed_checkpoint_current: bool = False,
    passed_checkpoint_epochs: tuple[str, ...] = (),
    ai_egress_allowed: bool = False,
    retained_policy_records: tuple[PolicyAuthorityRecord, ...] = (),
    retained_contexts: tuple[ExternalEvidenceMeasurementContextV1, ...] = (),
    replay_of: LocalAnalysisApiFixture | None = None,
    real_inspection: bool = False,
    malformed_current_dsm: bool = False,
    current_dsm_spatial_case: str = "VALID",
    organization_id: str | None = None,
    analysis_activation: Any = None,
) -> LocalAnalysisApiFixture:
    """Seed inspected/sealed epochs backed by real 2×2 GeoTIFF bytes for local API tests."""
    if replay_of is not None:
        if organization_id is not None and organization_id != replay_of.organization_id:
            raise ValueError("replay fixture must preserve its source organization")
        if retained_policy_records or retained_contexts:
            raise ValueError("replay fixture retains its source policy/context records itself")
        if v2_dsm_only is not None and v2_dsm_only != replay_of.v2_dsm_only:
            raise ValueError("replay fixture must preserve its source reconstruction contract")
        if include_third_epoch is not None and include_third_epoch != (replay_of.third is not None):
            raise ValueError("replay fixture must preserve its source observation epochs")
        if failed_checkpoint_current and not replay_of.failed_checkpoint_current:
            raise ValueError("replay fixture cannot add a failed checkpoint evaluation")
        if failed_checkpoint_baseline and not replay_of.failed_checkpoint_baseline:
            raise ValueError("replay fixture cannot add a failed checkpoint evaluation")
        if (
            passed_and_failed_checkpoint_current
            and not replay_of.passed_and_failed_checkpoint_current
        ):
            raise ValueError("replay fixture cannot add checkpoint evaluations")
        if not set(passed_checkpoint_epochs).issubset(replay_of.passed_checkpoint_epochs):
            raise ValueError("replay fixture cannot add checkpoint evaluations")
        if real_inspection and not replay_of.real_inspection:
            raise ValueError("replay fixture cannot change its inspection evidence source")
        if malformed_current_dsm and not replay_of.malformed_current_dsm:
            raise ValueError("replay fixture cannot change its sealed DSM bytes")
        if (
            current_dsm_spatial_case != "VALID"
            and current_dsm_spatial_case != replay_of.current_dsm_spatial_case
        ):
            raise ValueError("replay fixture cannot change its sealed DSM spatial metadata")
        v2_dsm_only = replay_of.v2_dsm_only
        include_third_epoch = replay_of.third is not None
        failed_checkpoint_current = replay_of.failed_checkpoint_current
        failed_checkpoint_baseline = replay_of.failed_checkpoint_baseline
        passed_and_failed_checkpoint_current = replay_of.passed_and_failed_checkpoint_current
        passed_checkpoint_epochs = replay_of.passed_checkpoint_epochs
        real_inspection = replay_of.real_inspection
        malformed_current_dsm = replay_of.malformed_current_dsm
        current_dsm_spatial_case = replay_of.current_dsm_spatial_case
        organization_id = replay_of.organization_id
        retained_policy_records = replay_of._retained_policy_records
        retained_contexts = replay_of._retained_contexts
    elif v2_dsm_only is None:
        v2_dsm_only = False
    if organization_id is None:
        organization_id = "org-a"
    if organization_id != "org-a" and not v2_dsm_only:
        raise ValueError("non-default organization fixture requires the V2 DSM-only fixture")
    if include_third_epoch is None:
        include_third_epoch = False
    if include_third_epoch and not v2_dsm_only:
        raise ValueError("third epoch reuse requires the V2 DSM-only fixture")
    if (
        failed_checkpoint_current
        or failed_checkpoint_baseline
        or passed_and_failed_checkpoint_current
        or passed_checkpoint_epochs
    ) and not v2_dsm_only:
        raise ValueError("checkpoint evaluation requires the V2 DSM-only fixture")
    if set(passed_checkpoint_epochs) - {"BASELINE", "CURRENT"}:
        raise ValueError("passed checkpoint epochs must be BASELINE and/or CURRENT")
    if len(set(passed_checkpoint_epochs)) != len(passed_checkpoint_epochs):
        raise ValueError("passed checkpoint epochs must be unique")
    if passed_checkpoint_epochs and (
        failed_checkpoint_current
        or failed_checkpoint_baseline
        or passed_and_failed_checkpoint_current
    ):
        raise ValueError("passed and failed checkpoint fixture modes cannot be combined")
    if real_inspection and not v2_dsm_only:
        raise ValueError("real inspection integration requires the V2 DSM-only fixture")
    if malformed_current_dsm and not real_inspection:
        raise ValueError("malformed DSM fixture requires real byte inspection")
    if current_dsm_spatial_case not in {
        "VALID",
        "MISSING_VERTICAL_REFERENCE",
        "HORIZONTAL_CRS_MISMATCH",
        "NON_OVERLAPPING_GRID",
        "ROTATED_OVERLAPPING_GRID",
        "OVERLAPPING_CURRENT_NODATA_CELL",
    }:
        raise ValueError("unsupported current DSM spatial case")
    if current_dsm_spatial_case != "VALID" and not (v2_dsm_only and real_inspection):
        raise ValueError("spatial DSM fixture variants require real V2 byte inspection")
    if current_dsm_spatial_case != "VALID" and malformed_current_dsm:
        raise ValueError("spatial DSM variants cannot also be malformed")
    now = datetime.now(UTC).replace(microsecond=0)
    storage = LoopbackObjectStorage()
    policy_authority = _RetainedPolicyAuthority()
    context_authority = _RetainedEvidenceContextAuthority(now)
    for record in retained_policy_records:
        policy_authority.add(record)
    for context in retained_contexts:
        context_authority.add(context)
    workflow, _catalog, envelope, _catalog_authority = _workflow(
        tmp_path,
        now=now,
        policy_authority=policy_authority,
        context_authority=context_authority,
        organization_id=organization_id,
    )
    operator = Principal(
        principal_id="analysis-local-operator",
        kind=PrincipalKind.OPERATOR,
        role=Role.ADMIN,
        device_id=None,
        organization_id=organization_id,
    )
    worker = Principal(
        principal_id="analysis-local-worker",
        kind=PrincipalKind.ANALYSIS_WORKER,
        role=None,
        device_id=None,
        organization_id=organization_id,
    )
    validation_worker = Principal(
        principal_id="analysis-local-validation-worker",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id=organization_id,
    )
    viewer = Principal(
        principal_id="analysis-local-viewer",
        kind=PrincipalKind.OPERATOR,
        role=Role.VIEWER,
        device_id=None,
        organization_id="org-a",
    )
    mcp_client = Principal(
        principal_id="analysis-local-mcp-client",
        kind=PrincipalKind.ANALYSIS_MCP_CLIENT,
        role=None,
        device_id=None,
        organization_id=organization_id,
        allowed_site_ids=frozenset({"site-a"}),
        allowed_work_area_ids=frozenset({"wa-site-a-0001"}),
    )
    mcp_other_area = Principal(
        principal_id="analysis-local-mcp-other-area-client",
        kind=PrincipalKind.ANALYSIS_MCP_CLIENT,
        role=None,
        device_id=None,
        organization_id=organization_id,
        allowed_site_ids=frozenset({"site-a"}),
        allowed_work_area_ids=frozenset({"wa-site-a-9999"}),
    )
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_OPERATOR_TOKEN.encode()).hexdigest(),
                principal=operator,
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_WORKER_TOKEN.encode()).hexdigest(), principal=worker
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_VALIDATION_WORKER_TOKEN.encode()).hexdigest(),
                principal=validation_worker,
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_VIEWER_TOKEN.encode()).hexdigest(), principal=viewer
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_MCP_CLIENT_TOKEN.encode()).hexdigest(),
                principal=mcp_client,
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_MCP_OTHER_AREA_TOKEN.encode()).hexdigest(),
                principal=mcp_other_area,
            ),
        ]
    )
    local_graph_config = _local_graph_config(envelope)
    if callable(analysis_activation):
        analysis_activation = analysis_activation(local_graph_config, worker)
    app, opened = _assemble_local_analysis_app(
        tmp_path,
        workflow=workflow,
        storage=storage,
        config=local_graph_config,
        auth_registry=registry,
        analysis_activation=analysis_activation,
    )
    assert isinstance(app, FastAPI)
    try:
        if replay_of is not None:
            return LocalAnalysisApiFixture(
                app=app,
                opened=opened,
                storage=storage,
                site_id=replay_of.site_id,
                work_area_id=replay_of.work_area_id,
                organization_id=replay_of.organization_id,
                baseline=replay_of.baseline.model_copy(deep=True),
                current=replay_of.current.model_copy(deep=True),
                third=(replay_of.third.model_copy(deep=True) if replay_of.third else None),
                v2_dsm_only=replay_of.v2_dsm_only,
                failed_checkpoint_current=replay_of.failed_checkpoint_current,
                failed_checkpoint_baseline=replay_of.failed_checkpoint_baseline,
                passed_and_failed_checkpoint_current=(
                    replay_of.passed_and_failed_checkpoint_current
                ),
                passed_checkpoint_epochs=replay_of.passed_checkpoint_epochs,
                synthetic_inspection_report_digests=(
                    replay_of.synthetic_inspection_report_digests
                ),
                synthetic_epoch_chronology=replay_of.synthetic_epoch_chronology,
                synthetic_policy_admitted_at=replay_of.synthetic_policy_admitted_at,
                _current_revision=replay_of._current_revision,
                _current_subject=replay_of._current_subject,
                _baseline_revision=replay_of._baseline_revision,
                _baseline_subject=replay_of._baseline_subject,
                _third_revision=replay_of._third_revision,
                _third_subject=replay_of._third_subject,
                _inspection_policy=replay_of._inspection_policy,
                _inspector_manifest=replay_of._inspector_manifest,
                real_inspection=replay_of.real_inspection,
                malformed_current_dsm=replay_of.malformed_current_dsm,
                current_dsm_spatial_case=replay_of.current_dsm_spatial_case,
                _fixture_now=replay_of._fixture_now,
                _operator_token=_OPERATOR_TOKEN,
                _worker_token=_WORKER_TOKEN,
                _validation_worker_token=_VALIDATION_WORKER_TOKEN,
                _viewer_token=_VIEWER_TOKEN,
                _mcp_client_token=_MCP_CLIENT_TOKEN,
                _mcp_other_area_token=_MCP_OTHER_AREA_TOKEN,
                _context_authority=context_authority,
                _retained_policy_records=policy_authority.retained_records(),
                _retained_contexts=context_authority.retained_contexts(),
            )
        site_registration = app.state.site_store.register(
            "site-a",
            "Local Analysis API fixture site",
            SiteFrame(
                crs="EPSG:5186",
                vertical_datum="EGM96 height",
                unit="meter",
                transform_version="fixture-v1",
            ),
            organization_id=organization_id,
            ai_egress_allowed=ai_egress_allowed,
            actor=operator.principal_id,
            now=now - timedelta(minutes=30),
        )
        assert (
            site_registration.record is not None
            or app.state.site_store.get_scoped("site-a", organization_id) is not None
        )
        transform = from_origin(_ORIGIN_X, _ORIGIN_Y, 0.1, 0.1)
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
            name="Local Analysis fixture area",
            polygon=polygon,
            crs="EPSG:5186",
            supersedes=None,
            actor=operator.principal_id,
            now=now - timedelta(minutes=29),
        )
        assert area_result.work_area is not None
        area = area_result.work_area
        orders = app.state.observation_work_order_store
        execution_mode = (
            ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION
            if v2_dsm_only
            else ObservationWorkOrderExecutionMode.MANAGED_ACQUISITION
        )

        def create_observation_order(label: str, created_at: datetime) -> Any:
            return orders.create_work_order(
                organization_id=organization_id,
                site_id="site-a",
                name="Local Analysis " + label,
                work_area_ids=[area.work_area_id],
                schedule_id=None,
                execution_mode=execution_mode,
                idempotency_key=("local-analysis-" + label if v2_dsm_only else None),
                actor=operator.principal_id,
                now=created_at,
            )

        baseline_order = create_observation_order("baseline", now - timedelta(minutes=28))
        current_order = create_observation_order("current", now - timedelta(minutes=27))
        third_order = (
            create_observation_order("third", now - timedelta(minutes=26))
            if include_third_epoch
            else None
        )
        baseline_bytes = _geotiff_bytes(np.full((2, 2), 100.0), transform=transform)
        current_values = np.array([[101.0, 99.0], [100.0, 100.0]])
        if malformed_current_dsm:
            current_bytes = b"malformed-current-dsm"
        elif current_dsm_spatial_case == "VALID":
            current_bytes = _geotiff_bytes(current_values, transform=transform)
        else:
            current_crs = {
                "MISSING_VERTICAL_REFERENCE": "EPSG:5186",
                "HORIZONTAL_CRS_MISMATCH": "EPSG:32652+5773",
                "NON_OVERLAPPING_GRID": "EPSG:5186+5773",
                "ROTATED_OVERLAPPING_GRID": "EPSG:5186+5773",
                "OVERLAPPING_CURRENT_NODATA_CELL": "EPSG:5186+5773",
            }[current_dsm_spatial_case]
            current_transform = transform
            if current_dsm_spatial_case == "NON_OVERLAPPING_GRID":
                current_transform = from_origin(
                    _ORIGIN_X + 1000.0, _ORIGIN_Y + 1000.0, 0.1, 0.1
                )
            elif current_dsm_spatial_case == "ROTATED_OVERLAPPING_GRID":
                current_transform = Affine(
                    0.1,
                    0.025,
                    _ORIGIN_X - 0.01,
                    0.025,
                    -0.1,
                    _ORIGIN_Y + 0.01,
                )
            current_nodata = None
            if current_dsm_spatial_case == "OVERLAPPING_CURRENT_NODATA_CELL":
                current_values[0, 0] = -9999.0
                current_nodata = -9999.0
            current_bytes = _geotiff_with_measured_spatial_case(
                current_values,
                transform=current_transform,
                crs=current_crs,
                nodata=current_nodata,
            )
        third_bytes = _geotiff_bytes(
            np.array([[103.0, 97.0], [100.0, 100.0]]), transform=transform
        )
        if v2_dsm_only:
            with TestClient(app) as ingress_client:
                baseline_revision, baseline_subject = _register_and_seal_v2_dsm(
                    ingress_client,
                    app,
                    baseline_order,
                    "analysis-local-baseline",
                    start=now - timedelta(minutes=20),
                    end=now - timedelta(minutes=15),
                    storage=storage,
                    dsm_bytes=baseline_bytes,
                    organization_id=organization_id,
                )
                current_revision, current_subject = _register_and_seal_v2_dsm(
                    ingress_client,
                    app,
                    current_order,
                    "analysis-local-current",
                    start=now - timedelta(minutes=10),
                    end=now - timedelta(minutes=5),
                    storage=storage,
                    dsm_bytes=current_bytes,
                    organization_id=organization_id,
                )
                if third_order is not None:
                    third_revision, third_subject = _register_and_seal_v2_dsm(
                        ingress_client,
                        app,
                        third_order,
                        "analysis-local-third",
                        start=now - timedelta(minutes=4),
                        end=now - timedelta(minutes=2),
                        storage=storage,
                        dsm_bytes=third_bytes,
                        organization_id=organization_id,
                    )
                else:
                    third_revision, third_subject = None, None
        else:
            baseline_revision, baseline_subject = _sealed_revision(
                app,
                baseline_order,
                "analysis-local-baseline",
                start=now - timedelta(minutes=20),
                end=now - timedelta(minutes=15),
                storage=storage,
                dsm_bytes=baseline_bytes,
            )
            current_revision, current_subject = _sealed_revision(
                app,
                current_order,
                "analysis-local-current",
                start=now - timedelta(minutes=10),
                end=now - timedelta(minutes=5),
                storage=storage,
                dsm_bytes=current_bytes,
            )
            if third_order is not None:
                third_revision, third_subject = _sealed_revision(
                    app,
                    third_order,
                    "analysis-local-third",
                    start=now - timedelta(minutes=4),
                    end=now - timedelta(minutes=2),
                    storage=storage,
                    dsm_bytes=third_bytes,
                )
            else:
                third_revision, third_subject = None, None
        epoch_pairs = [
            (baseline_revision, baseline_subject),
            (current_revision, current_subject),
        ]
        if third_revision is not None and third_subject is not None:
            epoch_pairs.append((third_revision, third_subject))
        policy_admitted_at = datetime.now(UTC) if include_third_epoch else now
        inspector_manifest = None
        if real_inspection:
            from ksi_processing_controller.external_geotiff_profile import (
                external_geotiff_profile_digest_v1,
            )
            from test_external_inspector_container_entrypoint import _manifest

            inspector_manifest = _manifest(envelope)
            template = ExternalValidationPolicyV1(
                policy_id="external-geotiff-v1",
                version=1,
                status=PolicyStatus.ACTIVE,
                parser_build_digest=inspector_manifest.parser_build_digest,
                grammar_digest=external_geotiff_profile_digest_v1(),
                resource_envelope=envelope,
                resource_envelope_digest=envelope.resource_envelope_digest,
                authority_record_digest=_digest("unbound-real-inspector-authority"),
                inspection_rule_ids=("EXTERNAL_GEOTIFF_MEASURED_V1",),
                evidence_rule_ids=("CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",),
                compatibility_mapping_digests=(CompatibilityRuleDescriptorV1().canonical_digest(),),
                synthetic_test_only=False,
            ).sealed()
            authority_record = PolicyAuthorityRecord(
                policy_id=template.policy_id,
                policy_version=template.version,
                authorized_policy_body_digest=authorized_policy_body_digest(template),
                permitted_subjects=tuple(subject for _revision, subject in epoch_pairs),
                permitted_uses=("INSPECTION", "EVIDENCE", "RELATIVE_VOLUME"),
                authorized_actor_ids=("policy-admin",),
                active_from=policy_admitted_at - timedelta(hours=1),
                active_until=policy_admitted_at + timedelta(hours=1),
                synthetic_test_only=False,
            ).sealed()
            assert authority_record.digest is not None
            policy_authority.add(authority_record)
            inspection_policy = template.model_copy(
                update={
                    "authority_record_digest": authority_record.digest,
                    "policy_digest": None,
                },
                deep=True,
            ).sealed()
            admitted = app.state.external_validation_policy_registry.admit(
                inspection_policy, actor="policy-admin", now=policy_admitted_at
            )
            assert admitted.status.value == "ADMITTED"
        else:
            inspection_policy = _admit_policy(
                app,
                subjects=tuple(subject for _revision, subject in epoch_pairs),
                envelope=envelope,
                authority=policy_authority,
                now=policy_admitted_at,
            )
        inspection_resource_envelope = inspection_policy.resource_envelope
        assert inspection_resource_envelope is not None
        vertical = ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")
        horizontal_digest = _digest(
            CRS.from_epsg(5186).to_wkt(version="WKT2_2019", pretty=False, output_axis_rule=True)
        )
        inspection_report_digests: list[str] = []
        epoch_chronology: list[tuple[datetime, datetime, datetime, datetime]] = []
        inspection_spacing = timedelta(
            seconds=inspection_resource_envelope.lease_duration_seconds + 1
        )
        for index, (revision, subject) in enumerate(epoch_pairs):
            if real_inspection:
                capture_start = revision.submission.input_declaration.capture_started_at
                capture_end = revision.submission.input_declaration.capture_ended_at
                if capture_start is None or capture_end is None or revision.manifest is None:
                    raise AssertionError(
                        "fixture epoch must have capture bounds and a sealed manifest"
                    )
                epoch_chronology.append(
                    (capture_start, capture_end, revision.manifest.observed_at, policy_admitted_at)
                )
                continue
            if include_third_epoch:
                if index:
                    time.sleep(inspection_spacing.total_seconds())
                inspection_now = datetime.now(UTC)
            else:
                # Preserve the original two-epoch fixture clock exactly for V1 and V2.
                inspection_now = now
            report = _inspect(
                app,
                revision=revision,
                subject=subject,
                policy=inspection_policy,
                now=inspection_now,
                transform=tuple(transform)[:6],
                vertical_reference=vertical,
                observed_crs_digest=horizontal_digest,
            )
            # This synthetic helper records a Core report; it does not read or
            # independently validate the underlying artifact bytes.
            inspection_report_digests.append(report.report_digest)
            capture_start = revision.submission.input_declaration.capture_started_at
            capture_end = revision.submission.input_declaration.capture_ended_at
            if capture_start is None or capture_end is None or revision.manifest is None:
                raise AssertionError("fixture epoch must have capture bounds and a sealed manifest")
            epoch_chronology.append(
                (capture_start, capture_end, revision.manifest.observed_at, report.reported_at)
            )
            if not v2_dsm_only:
                _validate_evidence(
                    app,
                    revision=revision,
                    subject=subject,
                    policy=inspection_policy,
                    context_authority=context_authority,
                    now=inspection_now,
                    storage=storage,
                    label="analysis-local-" + subject.submission_id,
                    organization_id=organization_id,
                )
            elif failed_checkpoint_baseline and subject == baseline_subject:
                # This test helper deliberately records a failed Core verdict
                # from synthetic checkpoint metrics; it is not field survey evidence.
                rejected = _validate_evidence(
                    app,
                    revision=revision,
                    subject=subject,
                    policy=inspection_policy,
                    context_authority=context_authority,
                    now=inspection_now,
                    storage=storage,
                    label="analysis-local-baseline-rejected-checkpoint",
                    checkpoint_count=1,
                    organization_id=organization_id,
                )
                assert rejected.core_verdict.value == "REJECTED"
                assert rejected.core_reason == "CHECKPOINT_COUNT_OUT_OF_RANGE"
            elif subject == baseline_subject and "BASELINE" in passed_checkpoint_epochs:
                # Generated checkpoint bytes exercise Core validation without
                # claiming survey or field accuracy evidence.
                passed = _validate_evidence(
                    app,
                    revision=revision,
                    subject=subject,
                    policy=inspection_policy,
                    context_authority=context_authority,
                    now=inspection_now,
                    storage=storage,
                    label="analysis-local-baseline-passed-checkpoint",
                    checkpoint_count=3,
                    organization_id=organization_id,
                )
                assert passed.core_verdict.value == "VALIDATED"
                assert passed.core_reason is None
            elif subject == current_subject and "CURRENT" in passed_checkpoint_epochs:
                # Generated checkpoint bytes exercise Core validation without
                # claiming survey or field accuracy evidence.
                passed = _validate_evidence(
                    app,
                    revision=revision,
                    subject=subject,
                    policy=inspection_policy,
                    context_authority=context_authority,
                    now=inspection_now,
                    storage=storage,
                    label="analysis-local-current-passed-checkpoint",
                    checkpoint_count=3,
                    organization_id=organization_id,
                )
                assert passed.core_verdict.value == "VALIDATED"
                assert passed.core_reason is None
            elif (failed_checkpoint_current or passed_and_failed_checkpoint_current) and (
                subject == current_subject
            ):
                if passed_and_failed_checkpoint_current:
                    accepted = _validate_evidence(
                        app,
                        revision=revision,
                        subject=subject,
                        policy=inspection_policy,
                        context_authority=context_authority,
                        now=inspection_now,
                        storage=storage,
                        label="analysis-local-current-passed-checkpoint",
                        checkpoint_count=3,
                        organization_id=organization_id,
                    )
                    assert accepted.core_verdict.value == "VALIDATED"
                # This test helper deliberately records a failed Core verdict
                # from synthetic checkpoint metrics; it is not field survey evidence.
                rejected = _validate_evidence(
                    app,
                    revision=revision,
                    subject=subject,
                    policy=inspection_policy,
                    context_authority=context_authority,
                    now=inspection_now,
                    storage=storage,
                    label="analysis-local-current-rejected-checkpoint",
                    checkpoint_count=1,
                    organization_id=organization_id,
                )
                assert rejected.core_verdict.value == "REJECTED"
                assert rejected.core_reason == "CHECKPOINT_COUNT_OUT_OF_RANGE"
        return LocalAnalysisApiFixture(
            app=app,
            opened=opened,
            storage=storage,
            site_id="site-a",
            work_area_id=area.work_area_id,
            organization_id=organization_id,
            baseline=AnalysisObservationSelectorV1(
                work_order_id=baseline_order.work_order_id,
                submission_ref=build_external_reconstruction_submission_ref(
                    organization_id=organization_id,
                    work_order_id=baseline_order.work_order_id,
                    submission_id=baseline_subject.submission_id,
                ),
                revision=baseline_subject.revision,
            ),
            current=AnalysisObservationSelectorV1(
                work_order_id=current_order.work_order_id,
                submission_ref=build_external_reconstruction_submission_ref(
                    organization_id=organization_id,
                    work_order_id=current_order.work_order_id,
                    submission_id=current_subject.submission_id,
                ),
                revision=current_subject.revision,
            ),
            third=(
                AnalysisObservationSelectorV1(
                    work_order_id=third_order.work_order_id,
                    submission_ref=build_external_reconstruction_submission_ref(
                        organization_id=organization_id,
                        work_order_id=third_order.work_order_id,
                        submission_id=third_subject.submission_id,
                    ),
                    revision=third_subject.revision,
                )
                if third_order is not None and third_subject is not None
                else None
            ),
            v2_dsm_only=v2_dsm_only,
            failed_checkpoint_current=failed_checkpoint_current,
            failed_checkpoint_baseline=failed_checkpoint_baseline,
            passed_and_failed_checkpoint_current=passed_and_failed_checkpoint_current,
            passed_checkpoint_epochs=passed_checkpoint_epochs,
            synthetic_inspection_report_digests=tuple(inspection_report_digests),
            synthetic_epoch_chronology=tuple(epoch_chronology),
            synthetic_policy_admitted_at=policy_admitted_at,
            _current_revision=current_revision,
            _current_subject=current_subject,
            _baseline_revision=baseline_revision,
            _baseline_subject=baseline_subject,
            _third_revision=third_revision,
            _third_subject=third_subject,
            _inspection_policy=inspection_policy,
            _inspector_manifest=inspector_manifest,
            real_inspection=real_inspection,
            malformed_current_dsm=malformed_current_dsm,
            current_dsm_spatial_case=current_dsm_spatial_case,
            _fixture_now=now,
            _operator_token=_OPERATOR_TOKEN,
            _worker_token=_WORKER_TOKEN,
            _validation_worker_token=_VALIDATION_WORKER_TOKEN,
            _viewer_token=_VIEWER_TOKEN,
            _mcp_client_token=_MCP_CLIENT_TOKEN,
            _mcp_other_area_token=_MCP_OTHER_AREA_TOKEN,
            _context_authority=context_authority,
            _retained_policy_records=policy_authority.retained_records(),
            _retained_contexts=context_authority.retained_contexts(),
        )
    except BaseException:
        for journal in reversed(opened):
            journal.close()
        raise


__all__ = ["LocalAnalysisApiFixture", "LoopbackObjectStorage", "build_local_analysis_api_fixture"]
