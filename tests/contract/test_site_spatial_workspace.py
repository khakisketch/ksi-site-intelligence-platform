"""SWX-1 Core observation/version/view-availability projection.

Server-owned read-only projection: what observations exist for a Site/WorkArea,
which asset versions each carries at real capture precision, what is
view-available, and which observation is the ordinary-entry default. The client
must never invent quality ranking, dates, versions, or eligibility.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.domains.external.ingress.external_artifact_inspections import (
    ExternalArtifactInspectionStore,
)
from ksi_core.domains.external.ingress.external_display_artifacts import (
    ExternalDisplayArtifactStore,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import ObjectStorageObservation
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore
from ksi_core.work_areas import WorkAreaStore
from ksi_event_contracts.external_artifact_validation import ArtifactOutcome
from ksi_event_contracts.external_reconstruction import (
    ExternalReconstructionSubmissionV1,
    ExternalReconstructionSubmissionV3,
)
from ksi_event_contracts.observation_work_order import ObservationWorkOrderExecutionMode
from ksi_event_contracts.site_frame import SiteFrame

_NOW = datetime(2026, 9, 30, tzinfo=UTC)
_TOKEN = "spatial-workspace-owner"  # noqa: S105 -- fixed test credential
_LIMITED_TOKEN = "spatial-workspace-limited"  # noqa: S105
_OTHER_TOKEN = "spatial-workspace-other"  # noqa: S105
_CONTENT = b"sealed workspace ortho bytes"


class _Storage:
    def __init__(self) -> None:
        self.objects: dict[str, ObjectStorageObservation] = {}
        self.bytes: dict[str, bytes] = {}

    def presigned_put_bound_digest(
        self, object_key: str, *, content_type: str, content_digest: str, ttl: Any
    ) -> Any:
        del content_type, content_digest, ttl
        return type(
            "Grant", (), {"upload_url": "https://storage.invalid", "required_headers": {}}
        )()

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        del object_key, ttl
        return "https://storage.invalid"

    def observe_object(self, object_key: str) -> ObjectStorageObservation:
        return self.objects.get(
            object_key, ObjectStorageObservation(object_key=object_key, exists=False)
        )

    def get_bytes(self, object_key: str) -> bytes:
        return self.bytes[object_key]

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        raise NotImplementedError("Workspace fixture accepts only digest-bound upload signing")

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        raise NotImplementedError("Workspace fixture cannot create server artifacts")

    def delete(self, object_key: str) -> None:
        raise NotImplementedError("Workspace fixture cannot delete evidence")


class _DisplayStub(ExternalArtifactInspectionStore):
    """Owner-API-shaped inspection/display stub; readiness is fixture-explicit."""

    def __init__(
        self,
        *,
        ready: frozenset[tuple[str, int]] = frozenset(),
        measured: bool = False,
    ) -> None:
        self._ready = set(ready)
        self._measured = measured

    def public_snapshot_bounded(
        self,
        subject: Any,
        *,
        max_records: int,
        max_policy_records: int | None = None,
        max_retained_policies: int | None = None,
    ) -> Any:
        del subject, max_records, max_policy_records, max_retained_policies
        report = None
        if self._measured:
            measurements = SimpleNamespace(
                observed_crs_identifier="EPSG:5186",
                observed_crs_wkt=None,
                observed_crs_digest="sha256:" + "1" * 64,
                observed_vertical_reference=None,
                transform=(0.5, 0.0, 100.0, 0.0, -0.5, 200.0),
                footprint_wkt="POLYGON ((100 200, 110 200, 110 210, 100 210, 100 200))",
                footprint_digest="sha256:" + "2" * 64,
                width=20,
                height=20,
            )
            outcome = SimpleNamespace(
                artifact_id="ortho",
                outcome=ArtifactOutcome.MEASURED,
                reason=None,
                measurements=measurements,
            )
            report = SimpleNamespace(
                report_digest="sha256:" + "3" * 64,
                inspector_build_digest="sha256:" + "4" * 64,
                measurement_payload=SimpleNamespace(outcomes=(outcome,)),
            )
        return SimpleNamespace(state="INSPECTION_REPORTED", report=report)

    def public_display_state(self, subject: Any) -> tuple[str, Any | None]:
        if (subject.submission_id, subject.revision) in self._ready:
            return "SEALED", SimpleNamespace()
        return "QUEUED", None


def _auth_record(
    token: str,
    *,
    principal_id: str,
    organization_id: str,
    allowed_site_ids: frozenset[str] | None = None,
    allowed_work_area_ids: frozenset[str] | None = None,
) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        principal=Principal(
            principal_id=principal_id,
            kind=PrincipalKind.OPERATOR,
            role=Role.VIEWER,
            device_id=None,
            organization_id=organization_id,
            allowed_site_ids=allowed_site_ids,
            allowed_work_area_ids=allowed_work_area_ids,
        ),
    )


def _submission_v1(
    *,
    site_id: str,
    order: Any,
    submission_id: str,
    revision: int = 1,
    capture_start: str = "2026-09-29T00:00:00Z",
    capture_end: str = "2026-09-29T00:10:00Z",
    submitted_at: str = "2026-09-30T00:00:00Z",
) -> ExternalReconstructionSubmissionV1:
    raw = {
        "submissionId": submission_id,
        "revision": revision,
        "organizationId": order.organization_id,
        "siteId": site_id,
        "observationEpochId": _epoch(order),
        "submittedAt": submitted_at,
        "submittedBy": "workspace-owner",
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "softwareName": "Terra",
            "softwareVersion": "test",
            "buildIdentifier": None,
            "producerRunIdentifier": None,
            "configurationDigest": None,
            "completedAt": "2026-09-30T00:30:00Z",
        },
        "inputDeclaration": {
            "rawMediaStoredByKsi": False,
            "originalRetentionLocus": "customer_workstation",
            "localInputManifestDigest": None,
            "imageCount": None,
            "captureStartedAt": capture_start,
            "captureEndedAt": capture_end,
        },
        "artifacts": [
            {
                "artifactId": "ortho",
                "kind": "ortho",
                "fileName": "ortho.tif",
                "format": "GeoTIFF",
                "contentType": "application/octet-stream",
                "declaredSha256": hashlib.sha256(_CONTENT).hexdigest(),
                "declaredSizeBytes": len(_CONTENT),
                "declaredCrs": "EPSG:5186",
                "declaredVerticalReference": None,
                "declaredGsdM": 0.05,
            }
        ],
    }
    raw["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(raw)
    return ExternalReconstructionSubmissionV1.model_validate(raw)


def _submission_v3(
    *,
    site_id: str,
    order: Any,
    submission_id: str,
    capture_date: str | None,
    capture_basis: str,
    capture_start: str | None = None,
    capture_end: str | None = None,
    submitted_at: str = "2026-09-30T00:00:00Z",
) -> ExternalReconstructionSubmissionV3:
    raw = {
        "submissionId": submission_id,
        "revision": 1,
        "organizationId": order.organization_id,
        "siteId": site_id,
        "observationEpochId": _epoch(order),
        "submittedAt": submitted_at,
        "submittedBy": "workspace-owner",
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "producerKnowledge": "UNKNOWN",
            "softwareName": None,
            "softwareVersion": None,
            "buildIdentifier": None,
            "producerRunIdentifier": None,
            "configurationDigest": None,
            "completedAt": None,
            "sourceNote": None,
        },
        "inputDeclaration": {
            "rawMediaStoredByKsi": False,
            "originalRetentionLocus": "upstream_source",
            "originalRetentionDetail": "public portal fixture",
            "localInputManifestDigest": None,
            "imageCount": None,
            "captureStartedAt": capture_start,
            "captureEndedAt": capture_end,
            "captureDate": capture_date,
            "captureBasis": capture_basis,
            "upstreamSource": None,
            "derivativeExport": None,
        },
        "artifacts": [
            {
                "artifactId": "ortho",
                "kind": "ortho",
                "fileName": "ortho.tif",
                "format": "GeoTIFF",
                "contentType": "application/octet-stream",
                "declaredSha256": hashlib.sha256(_CONTENT).hexdigest(),
                "declaredSizeBytes": len(_CONTENT),
                "declaredCrs": "EPSG:5186",
                "declaredVerticalReference": None,
                "declaredGsdM": 0.05,
            }
        ],
    }
    raw["submissionDigest"] = ExternalReconstructionSubmissionV3.digest_for_wire(raw)
    return ExternalReconstructionSubmissionV3.model_validate(raw)


def _epoch(order: Any) -> str:
    from ksi_core.domains.observations.epoch_identity import observation_epoch_id

    return observation_epoch_id(order)


def _setup(
    tmp_path: Path, *, inspections: Any | None = None
) -> tuple[TestClient, Any, Any, Any, Any, Any, Any, Any, Any]:
    sites = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    frame = SiteFrame(
        crs="EPSG:5186", vertical_datum="KNGeoid2018", unit="meter", transform_version="1.0.0"
    )
    assert sites.register(
        "site-a", "Site A", frame, organization_id="org-a", actor="fixture", now=_NOW
    ).record
    areas = WorkAreaStore(
        DurableJournal(tmp_path / "areas.jsonl"),
        site_exists=lambda site_id: sites.get_scoped(site_id, "org-a") is not None,
    )
    area_a = areas.register(
        "site-a",
        name="Area A",
        polygon={"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 0]]]},
        crs="EPSG:5186",
        supersedes=None,
        now=_NOW,
        actor="fixture",
    )
    assert area_a.work_area is not None
    area_b = areas.register(
        "site-a",
        name="Area B",
        polygon={"type": "Polygon", "coordinates": [[[20, 0], [30, 0], [30, 10], [20, 0]]]},
        crs="EPSG:5186",
        supersedes=None,
        now=_NOW,
        actor="fixture",
    )
    assert area_b.work_area is not None
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            sites.get_scoped(site_id, organization_id) is not None
        ),
        work_areas_exist=lambda site_id, ids: all(
            (area := areas.get(item)) is not None and area.site_id == site_id for item in ids
        ),
    )
    order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="External survey",
        work_area_ids=[area_a.work_area.work_area_id],
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        idempotency_key="workspace-order",
        actor="fixture",
        now=_NOW,
    )
    storage = _Storage()
    reconstruction = ExternalReconstructionStore(DurableJournal(tmp_path / "reconstruction.jsonl"))
    records = [
        _auth_record(_TOKEN, principal_id="workspace-owner", organization_id="org-a"),
        _auth_record(
            _LIMITED_TOKEN,
            principal_id="workspace-limited",
            organization_id="org-a",
            allowed_site_ids=frozenset({"site-a"}),
            allowed_work_area_ids=frozenset({area_a.work_area.work_area_id}),
        ),
        _auth_record(_OTHER_TOKEN, principal_id="other", organization_id="org-b"),
    ]
    kwargs: dict[str, Any] = {}
    if inspections is not None:
        kwargs["external_artifact_inspection_store"] = inspections
        # Placeholder satisfying the assembly-table non-None assert: the
        # workspace projection under test reads the inspection stub only
        # (public_display_state) and never touches display routes.
        kwargs["external_display_artifact_store"] = cast(
            ExternalDisplayArtifactStore, SimpleNamespace()
        )
    app = create_app(
        auth_registry=AuthRegistry(records),
        site_store=sites,
        work_area_store=areas,
        observation_work_order_store=work_orders,
        evidence_storage=storage,
        external_reconstruction_store=reconstruction,
        **kwargs,
    )
    return (
        TestClient(app),
        order,
        storage,
        reconstruction,
        area_a.work_area,
        area_b.work_area,
        work_orders,
        sites,
        areas,
    )


def _extra_order(work_orders: Any, area_id: str, *, key: str, name: str) -> Any:
    return work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name=name,
        work_area_ids=[area_id],
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        idempotency_key=key,
        actor="fixture",
        now=_NOW,
    )


def _register_and_seal(
    order: Any,
    storage: _Storage,
    reconstruction: Any,
    submission: Any,
) -> None:
    registered = reconstruction.register(
        submission, work_order=order, registered_by="workspace-owner", now=_NOW
    )
    assert registered.revision is not None
    grant = reconstruction.upload_grants(
        order.work_order_id,
        submission.submission_id,
        submission.revision,
        organization_id=order.organization_id,
        site_id=order.site_id,
        storage=storage,
    )
    assert grant.grants
    key = grant.grants[0].object_key
    storage.bytes[key] = _CONTENT
    storage.objects[key] = ObjectStorageObservation(
        object_key=key,
        exists=True,
        size_bytes=len(_CONTENT),
        sha256="sha256:" + hashlib.sha256(_CONTENT).hexdigest(),
        content_type=submission.artifacts[0].content_type,
    )
    sealed = reconstruction.seal(
        order.work_order_id,
        submission.submission_id,
        submission.revision,
        organization_id=order.organization_id,
        site_id=order.site_id,
        storage=storage,
        now=_NOW,
    )
    assert sealed.revision is not None and sealed.revision.manifest is not None


def _root(order: Any, area: Any) -> str:
    return (
        f"/v1/sites/{order.site_id}/work-areas/{area.work_area_id}"
        "/spatial-workspace-observations"
    )


def _headers(token: str = _TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_workspace_groups_by_epoch_with_real_precision(tmp_path: Path) -> None:
    inspections = _DisplayStub(ready=frozenset({("exact-one", 1), ("date-only-one", 1)}))
    client, order, storage, reconstruction, area_a, _, work_orders, _, _ = _setup(
        tmp_path, inspections=inspections
    )
    order_two = _extra_order(work_orders, area_a.work_area_id, key="ws-two", name="Second")
    order_three = _extra_order(work_orders, area_a.work_area_id, key="ws-three", name="Third")
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v1(site_id=order.site_id, order=order, submission_id="exact-one"),
    )
    _register_and_seal(
        order_two,
        storage,
        reconstruction,
        _submission_v3(
            site_id=order_two.site_id,
            order=order_two,
            submission_id="date-only-one",
            capture_date="2021-08-17",
            capture_basis="DATE_ONLY",
        ),
    )
    _register_and_seal(
        order_three,
        storage,
        reconstruction,
        _submission_v3(
            site_id=order_three.site_id,
            order=order_three,
            submission_id="unknown-one",
            capture_date=None,
            capture_basis="UNKNOWN",
        ),
    )

    response = client.get(_root(order, area_a), headers=_headers())
    assert response.status_code == 200, response.text
    body = response.json()
    schema = json.loads(Path("contracts/schemas/site-spatial-workspace.v1.json").read_text())
    Draft202012Validator(schema).validate(body)
    assert len(body["observations"]) == 3

    by_epoch = {item["observationEpochId"]: item for item in body["observations"]}
    exact = by_epoch[_epoch(order)]
    date_only = by_epoch[_epoch(order_two)]
    unknown = by_epoch[_epoch(order_three)]

    assert exact["capture"]["precision"] == "EXACT_INTERVAL"
    assert exact["capture"]["captureStartedAt"] == "2026-09-29T00:00:00Z"
    assert exact["capture"]["captureEndedAt"] == "2026-09-29T00:10:00Z"
    assert exact["capture"]["captureDate"] is None
    assert exact["captureSourcesAgree"] is True
    assert exact["viewAvailable"] is True
    assert exact["chronologyCandidate"] is True
    assert exact["versions"][0]["chronology"] == "EXACT_INTERVAL_CANDIDATE"

    assert date_only["capture"]["precision"] == "DATE_ONLY"
    assert date_only["capture"]["captureDate"] == "2021-08-17"
    assert date_only["capture"]["captureStartedAt"] is None
    assert date_only["viewAvailable"] is True
    assert date_only["chronologyCandidate"] is False
    assert date_only["versions"][0]["chronology"] == "DATE_ONLY_NOT_ORDERABLE"

    assert unknown["capture"]["precision"] == "UNKNOWN"
    assert unknown["capture"]["captureDate"] is None
    assert unknown["viewAvailable"] is False
    assert unknown["chronologyCandidate"] is False

    # The exact view-available observation is the entry default; the
    # date-only one stays browsable but can never select it.
    default = body["entryDefault"]
    assert default["reason"] == "LATEST_EXACT_VIEW_AVAILABLE"
    assert default["observationEpochId"] == _epoch(order)
    assert default["viewAssetRef"] == exact["viewAssetRef"]


def test_workspace_default_ignores_registration_order(tmp_path: Path) -> None:
    inspections = _DisplayStub(ready=frozenset({("older-capture", 1), ("newer-capture", 1)}))
    client, order, storage, reconstruction, area_a, _, work_orders, _, _ = _setup(
        tmp_path, inspections=inspections
    )
    order_new = _extra_order(work_orders, area_a.work_area_id, key="ws-new", name="New capture")
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v1(
            site_id=order.site_id,
            order=order,
            submission_id="older-capture",
            capture_start="2026-09-01T00:00:00Z",
            capture_end="2026-09-01T00:10:00Z",
            submitted_at="2026-09-30T00:00:00Z",
        ),
    )
    _register_and_seal(
        order_new,
        storage,
        reconstruction,
        _submission_v1(
            site_id=order_new.site_id,
            order=order_new,
            submission_id="newer-capture",
            capture_start="2026-09-15T00:00:00Z",
            capture_end="2026-09-15T00:10:00Z",
            submitted_at="2026-09-02T00:00:00Z",
        ),
    )

    body = client.get(_root(order, area_a), headers=_headers()).json()
    by_epoch = {item["observationEpochId"]: item for item in body["observations"]}
    # Registration order is inverted relative to capture order; the payload
    # keeps submittedAt visible so the client can see the distinction.
    assert by_epoch[_epoch(order)]["versions"][0]["submittedAt"] == "2026-09-30T00:00:00Z"
    assert by_epoch[_epoch(order_new)]["versions"][0]["submittedAt"] == "2026-09-02T00:00:00Z"
    assert body["entryDefault"]["observationEpochId"] == _epoch(order_new)
    assert body["entryDefault"]["reason"] == "LATEST_EXACT_VIEW_AVAILABLE"


def test_workspace_capture_tie_is_ambiguous(tmp_path: Path) -> None:
    inspections = _DisplayStub(ready=frozenset({("tie-a", 1), ("tie-b", 1)}))
    client, order, storage, reconstruction, area_a, _, work_orders, _, _ = _setup(
        tmp_path, inspections=inspections
    )
    order_b = _extra_order(work_orders, area_a.work_area_id, key="ws-tie-b", name="Tie B")
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v1(site_id=order.site_id, order=order, submission_id="tie-a"),
    )
    _register_and_seal(
        order_b,
        storage,
        reconstruction,
        _submission_v1(site_id=order_b.site_id, order=order_b, submission_id="tie-b"),
    )

    body = client.get(_root(order, area_a), headers=_headers()).json()
    default = body["entryDefault"]
    assert default["reason"] == "CAPTURE_TIE_AMBIGUOUS"
    assert default["observationEpochId"] is None
    assert sorted(default["tiedObservationEpochIds"]) == sorted([_epoch(order), _epoch(order_b)])


def test_workspace_no_exact_candidate_reports_reason(tmp_path: Path) -> None:
    inspections = _DisplayStub(ready=frozenset({("date-only-one", 1)}))
    client, order, storage, reconstruction, area_a, _, work_orders, _, _ = _setup(
        tmp_path, inspections=inspections
    )
    order_two = _extra_order(work_orders, area_a.work_area_id, key="ws-d", name="D")
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v3(
            site_id=order.site_id,
            order=order,
            submission_id="date-only-one",
            capture_date="2022-08-24",
            capture_basis="DATE_ONLY",
        ),
    )
    _register_and_seal(
        order_two,
        storage,
        reconstruction,
        _submission_v3(
            site_id=order_two.site_id,
            order=order_two,
            submission_id="unknown-one",
            capture_date=None,
            capture_basis="UNKNOWN",
        ),
    )

    body = client.get(_root(order, area_a), headers=_headers()).json()
    assert len(body["observations"]) == 2
    assert body["entryDefault"]["reason"] == "NO_EXACT_CAPTURE_CANDIDATE"
    assert body["entryDefault"]["observationEpochId"] is None


def test_workspace_corrective_revision_keeps_one_observation(tmp_path: Path) -> None:
    inspections = _DisplayStub(ready=frozenset({("submission-one", 1)}), measured=True)
    client, order, storage, reconstruction, area_a, _, _, _, _ = _setup(
        tmp_path, inspections=inspections
    )
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v1(site_id=order.site_id, order=order, submission_id="submission-one"),
    )
    corrected = _submission_v1(
        site_id=order.site_id, order=order, submission_id="submission-one", revision=2
    )
    result = reconstruction.register(
        corrected, work_order=order, registered_by="workspace-owner", now=_NOW
    )
    assert result.revision is not None

    body = client.get(_root(order, area_a), headers=_headers()).json()
    assert len(body["observations"]) == 1
    observation = body["observations"][0]
    assert observation["observationEpochId"] == _epoch(order)
    by_revision = {item["revision"]: item for item in observation["versions"]}
    # The correction does not become a new observation and the earlier
    # version remains visible as SUPERSEDED with its sealed bytes.
    assert set(by_revision) == {1, 2}
    assert by_revision[1]["lifecycleState"] == "SUPERSEDED"
    assert by_revision[1]["observedSha256"] is not None
    assert by_revision[1]["observedAt"] is not None
    assert by_revision[1]["inspectedRasterAvailable"] is True
    assert by_revision[1]["displayReady"] is True
    assert by_revision[2]["lifecycleState"] == "UNSEALED"
    assert by_revision[2]["observedSha256"] is None
    assert by_revision[2]["observedAt"] is None
    assert by_revision[2]["displayReady"] is False
    # The newer UNSEALED revision never displaces the displayable one, and
    # its state stays visible on the observation.
    assert observation["newerRevisionPending"] is True
    assert "UNSEALED" in (observation["newerRevisionState"] or "")
    assert observation["viewAssetRef"] == by_revision[1]["assetRef"]
    assert body["entryDefault"]["observationEpochId"] == _epoch(order)


def test_workspace_no_view_available_reports_reason(tmp_path: Path) -> None:
    client, order, storage, reconstruction, area_a, _, _, _, _ = _setup(tmp_path)
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v1(site_id=order.site_id, order=order, submission_id="exact-one"),
    )

    body = client.get(_root(order, area_a), headers=_headers()).json()
    assert body["entryDefault"]["reason"] == "NO_VIEW_AVAILABLE_OBSERVATION"
    assert body["entryDefault"]["observationEpochId"] is None
    assert body["observations"][0]["viewAvailable"] is False
    assert body["observations"][0]["viewAssetRef"] is None


def test_workspace_empty_scope_reports_no_observations(tmp_path: Path) -> None:
    client, order, _, _, area_a, _, _, _, _ = _setup(tmp_path)
    body = client.get(_root(order, area_a), headers=_headers()).json()
    assert body["observations"] == []
    assert body["entryDefault"]["reason"] == "NO_OBSERVATIONS"


def test_workspace_quantitative_stays_unevaluated(tmp_path: Path) -> None:
    inspections = _DisplayStub(ready=frozenset({("exact-one", 1)}))
    client, order, storage, reconstruction, area_a, _, _, _, _ = _setup(
        tmp_path, inspections=inspections
    )
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v1(site_id=order.site_id, order=order, submission_id="exact-one"),
    )

    body = client.get(_root(order, area_a), headers=_headers()).json()
    version = body["observations"][0]["versions"][0]
    assert version["quantitativeEligibility"] == "NOT_EVALUATED"
    assert version["chronologyCandidate"] is True
    assert version["displayReady"] is True
    assert version["lifecycleState"] == "SEALED"
    assert "analysisStatus" not in version


def test_workspace_scope_fail_closed_without_leakage(tmp_path: Path) -> None:
    inspections = _DisplayStub(ready=frozenset({("exact-one", 1), ("exact-two", 1)}))
    client, order, storage, reconstruction, area_a, area_b, work_orders, _, _ = _setup(
        tmp_path, inspections=inspections
    )
    order_two = _extra_order(work_orders, area_a.work_area_id, key="ws-scope", name="Scope")
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v1(site_id=order.site_id, order=order, submission_id="exact-one"),
    )
    _register_and_seal(
        order_two,
        storage,
        reconstruction,
        _submission_v1(site_id=order_two.site_id, order=order_two, submission_id="exact-two"),
    )
    root = _root(order, area_a)

    assert client.get(root, headers=_headers(_OTHER_TOKEN)).status_code == 404
    assert client.get(_root(order, area_b), headers=_headers(_LIMITED_TOKEN)).status_code == 404
    assert client.get(root + "?limit=51", headers=_headers()).status_code == 422
    assert client.get(root + "?cursor=%%%", headers=_headers()).status_code == 400

    first = client.get(root + "?limit=1", headers=_headers()).json()
    assert first["nextCursor"]
    assert (
        client.get(
            _root(order, area_b) + "?cursor=" + first["nextCursor"], headers=_headers()
        ).status_code
        == 400
    )

    text = client.get(root, headers=_headers()).text
    for forbidden in ("objectKey", "uploadUrl", "presigned", "signedUrl", "downloadUrl"):
        assert forbidden not in text


def test_workspace_catalog_carries_declared_calendar_date(tmp_path: Path) -> None:
    client, order, storage, reconstruction, area_a, _, work_orders, _, _ = _setup(tmp_path)
    order_two = _extra_order(work_orders, area_a.work_area_id, key="ws-cat", name="Cat")
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v3(
            site_id=order.site_id,
            order=order,
            submission_id="date-only-one",
            capture_date="2021-08-17",
            capture_basis="DATE_ONLY",
        ),
    )
    _register_and_seal(
        order_two,
        storage,
        reconstruction,
        _submission_v1(site_id=order_two.site_id, order=order_two, submission_id="exact-one"),
    )

    catalog = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=_headers(),
    )
    assert catalog.status_code == 200
    schema = json.loads(Path("contracts/schemas/spatial-asset-catalog.v1.json").read_text())
    Draft202012Validator(schema).validate(catalog.json())
    declared = {
        item["submissionRef"]: item["declared"] for item in catalog.json()["assets"]
    }
    assert len(declared) == 2
    date_declared = next(
        value
        for key, value in declared.items()
        if value["captureDate"] == "2021-08-17"
    )
    assert date_declared["captureStartedAt"] is None
    assert date_declared["captureEndedAt"] is None
    exact_declared = next(value for value in declared.values() if value["captureDate"] is None)
    assert exact_declared["captureStartedAt"] == "2026-09-29T00:00:00Z"


def test_workspace_openapi_declares_route_and_schema(tmp_path: Path) -> None:
    import yaml

    client, order, _, _, area_a, _, _, _, _ = _setup(tmp_path)
    app = cast(FastAPI, client.app)
    assert (
        "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-workspace-observations"
        in app.openapi()["paths"]
    )
    document = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "contracts/api/openapi-core.yaml").read_text()
    )
    path = document["paths"][
        "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-workspace-observations"
    ]
    assert path["get"]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SiteSpatialWorkspacePageV1"
    }
    live = app.openapi()["components"]["schemas"]
    for name in (
        "SiteSpatialWorkspacePageV1",
        "WorkspaceObservationViewV1",
        "WorkspaceAssetVersionViewV1",
        "WorkspaceCaptureFactsV1",
        "WorkspaceEntryDefaultV1",
    ):
        assert document["components"]["schemas"][name] == live[name]


def test_workspace_entry_default_pure_empty() -> None:
    from ksi_core.domains.external.ingress.site_spatial_workspace import SiteSpatialWorkspace

    assert SiteSpatialWorkspace.entry_default(()).reason.value == "NO_OBSERVATIONS"


def test_workspace_projection_survives_journal_replay(tmp_path: Path) -> None:
    inspections = _DisplayStub(ready=frozenset({("exact-one", 1)}))
    client, order, storage, reconstruction, area_a, _, work_orders, sites, areas = _setup(
        tmp_path, inspections=inspections
    )
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v1(site_id=order.site_id, order=order, submission_id="exact-one"),
    )
    before = client.get(_root(order, area_a), headers=_headers()).json()

    replay_dir = tmp_path / "replay"
    replay_dir.mkdir()
    for name in ("sites.jsonl", "areas.jsonl", "orders.jsonl", "reconstruction.jsonl"):
        (replay_dir / name).write_bytes((tmp_path / name).read_bytes())
    replayed_sites = SiteStore(DurableJournal(replay_dir / "sites.jsonl"))
    replayed_areas = WorkAreaStore(
        DurableJournal(replay_dir / "areas.jsonl"),
        site_exists=lambda site_id: replayed_sites.get_scoped(site_id, "org-a") is not None,
    )
    replayed_orders = ObservationWorkOrderStore(
        DurableJournal(replay_dir / "orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            replayed_sites.get_scoped(site_id, organization_id) is not None
        ),
        work_areas_exist=lambda site_id, ids: all(
            (area := replayed_areas.get(item)) is not None and area.site_id == site_id
            for item in ids
        ),
    )
    replayed_reconstruction = ExternalReconstructionStore(
        DurableJournal(replay_dir / "reconstruction.jsonl")
    )
    assert (
        len(
            replayed_reconstruction.list(
                order.work_order_id, organization_id="org-a", site_id="site-a"
            )
        )
        == 1
    )
    replayed_app = create_app(
        auth_registry=AuthRegistry(
            [_auth_record(_TOKEN, principal_id="workspace-owner", organization_id="org-a")]
        ),
        site_store=replayed_sites,
        work_area_store=replayed_areas,
        observation_work_order_store=replayed_orders,
        evidence_storage=_Storage(),
        external_reconstruction_store=replayed_reconstruction,
        external_artifact_inspection_store=_DisplayStub(ready=frozenset({("exact-one", 1)})),
        # Same placeholder rationale as _setup: replay compares projections only.
        external_display_artifact_store=cast(
            ExternalDisplayArtifactStore, SimpleNamespace()
        ),
    )
    again = TestClient(replayed_app).get(_root(order, area_a), headers=_headers()).json()
    assert again == before


def test_workspace_budget_refusal_carries_no_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_core.domains.external.ingress.site_spatial_workspace as workspace_module

    inspections = _DisplayStub(ready=frozenset({("exact-one", 1)}))
    client, order, storage, reconstruction, area_a, _, _, _, _ = _setup(
        tmp_path, inspections=inspections
    )
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v1(site_id=order.site_id, order=order, submission_id="exact-one"),
    )
    monkeypatch.setattr(workspace_module, "_MAX_PAGE_BYTES", 32)
    refused = client.get(_root(order, area_a), headers=_headers())
    assert refused.status_code == 503
    assert "observationEpochId" not in refused.text
