"""Additive exact-asset description: enriched metadata without new authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
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
from ksi_core.domains.external.ingress.spatial_asset_description import (
    horizontal_units_from_inspected_crs,
    pixel_resolution_from_transform,
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
    ExternalReconstructionSubmissionV2,
    ExternalReconstructionSubmissionV3,
)
from ksi_event_contracts.observation_work_order import ObservationWorkOrderExecutionMode
from ksi_event_contracts.site_frame import SiteFrame

_NOW = datetime(2026, 9, 30, tzinfo=UTC)
_TOKEN = "spatial-description-owner"  # noqa: S105 -- fixed test credential
_LIMITED_TOKEN = "spatial-description-limited"  # noqa: S105
_OTHER_TOKEN = "spatial-description-other"  # noqa: S105
_CONTENT = b"sealed description bytes"
_DSM_CONTENT = b"sealed dsm bytes"
_DIGEST = "sha256:" + "9" * 64


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
        raise NotImplementedError("fixture accepts only digest-bound upload signing")

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        raise NotImplementedError("fixture cannot create server artifacts")

    def delete(self, object_key: str) -> None:
        raise NotImplementedError("fixture cannot delete evidence")


class _InspectionSpy:
    """In-memory inspection source with full genuine measurement payloads."""

    def __init__(self, measurements_by_artifact: dict[str, Any] | None = None) -> None:
        self.measurements_by_artifact = measurements_by_artifact or {}
        self.calls = 0

    def public_snapshot_bounded(self, subject: Any, **budgets: Any) -> Any:
        assert budgets["max_records"] == 128
        assert budgets["max_policy_records"] == 64
        self.calls += 1
        outcomes = []
        for artifact_id, measurements in self.measurements_by_artifact.items():
            outcomes.append(
                SimpleNamespace(
                    artifact_id=artifact_id,
                    outcome=ArtifactOutcome.MEASURED,
                    reason=None,
                    measurements=measurements,
                )
            )
        report = None
        if outcomes:
            report = SimpleNamespace(
                report_digest="sha256:" + "3" * 64,
                inspector_build_digest="sha256:" + "4" * 64,
                measurement_payload=SimpleNamespace(outcomes=tuple(outcomes)),
            )
        return SimpleNamespace(
            state="INSPECTION_REPORTED" if report else "INSPECTION_PENDING", report=report
        )


def _measurements(
    *,
    crs_identifier: str = "EPSG:5186",
    crs_wkt: str | None = "KEEP",
    transform: tuple[float, float, float, float, float, float] = (
        0.5,
        0.0,
        100.0,
        0.0,
        -0.5,
        200.0,
    ),
    vertical: tuple[str, str] | None = None,
    band_count: int = 1,
    dtype: str = "uint16",
    layout: str = "GEOTIFF_STRIPED_V1",
    nodata: tuple[str, float | None] = ("FINITE", -9999.0),
    valid_pixels: int = 380,
) -> SimpleNamespace:
    from pyproj import CRS

    wkt = CRS.from_user_input(crs_identifier).to_wkt() if crs_wkt == "KEEP" else crs_wkt
    representation, value = nodata
    return SimpleNamespace(
        observed_crs_identifier=crs_identifier,
        observed_crs_wkt=wkt,
        observed_crs_digest="sha256:" + "1" * 64,
        observed_vertical_reference=(
            SimpleNamespace(identifier=vertical[0], basis=vertical[1]) if vertical else None
        ),
        transform=transform,
        footprint_wkt="POLYGON ((100 200, 110 200, 110 210, 100 210, 100 200))",
        footprint_digest="sha256:" + "2" * 64,
        width=20,
        height=20,
        band_count=band_count,
        dtype=dtype,
        layout=layout,
        nodata_representation=representation,
        nodata_value=value,
        valid_pixel_count=valid_pixels,
    )


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


def _artifact(
    artifact_id: str, kind: str, content: bytes, crs: str | None = "EPSG:5186"
) -> dict[str, Any]:
    return {
        "artifactId": artifact_id,
        "kind": kind,
        "fileName": f"{artifact_id}.tif",
        "format": "GeoTIFF",
        "contentType": "application/octet-stream",
        "declaredSha256": hashlib.sha256(content).hexdigest(),
        "declaredSizeBytes": len(content),
        "declaredCrs": crs,
        "declaredVerticalReference": None,
        "declaredGsdM": 0.05,
    }


def _submission_v1(*, site_id: str, order: Any, submission_id: str) -> Any:
    raw = {
        "submissionId": submission_id,
        "revision": 1,
        "organizationId": order.organization_id,
        "siteId": site_id,
        "observationEpochId": _epoch(order),
        "submittedAt": "2026-09-30T00:00:00Z",
        "submittedBy": "description-owner",
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "softwareName": "Terra",
            "softwareVersion": "test",
            "buildIdentifier": "build-7",
            "producerRunIdentifier": "run-9",
            "configurationDigest": "sha256:" + "a" * 64,
            "completedAt": "2026-09-30T00:30:00Z",
        },
        "inputDeclaration": {
            "rawMediaStoredByKsi": False,
            "originalRetentionLocus": "customer_workstation",
            "localInputManifestDigest": None,
            "imageCount": 12,
            "captureStartedAt": "2026-09-29T00:00:00Z",
            "captureEndedAt": "2026-09-29T00:10:00Z",
        },
        "artifacts": [_artifact("ortho", "ortho", _CONTENT)],
    }
    raw["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(raw)
    return ExternalReconstructionSubmissionV1.model_validate(raw)


def _submission_v2(*, site_id: str, order: Any, submission_id: str) -> Any:
    raw = {
        "submissionId": submission_id,
        "revision": 1,
        "organizationId": order.organization_id,
        "siteId": site_id,
        "observationEpochId": _epoch(order),
        "submittedAt": "2026-09-30T00:00:00Z",
        "submittedBy": "description-owner",
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "softwareName": "Metashape",
            "softwareVersion": "2.1",
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
            "captureStartedAt": None,
            "captureEndedAt": None,
        },
        "artifacts": [_artifact("dsm", "dsm", _DSM_CONTENT)],
    }
    raw["submissionDigest"] = ExternalReconstructionSubmissionV2.digest_for_wire(raw)
    return ExternalReconstructionSubmissionV2.model_validate(raw)


def _submission_v3(
    *,
    site_id: str,
    order: Any,
    submission_id: str,
    producer: dict[str, Any],
    capture: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> Any:
    raw = {
        "submissionId": submission_id,
        "revision": 1,
        "organizationId": order.organization_id,
        "siteId": site_id,
        "observationEpochId": _epoch(order),
        "submittedAt": "2026-09-30T00:00:00Z",
        "submittedBy": "description-owner",
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": producer,
        "inputDeclaration": capture,
        "artifacts": artifacts,
    }
    raw["submissionDigest"] = ExternalReconstructionSubmissionV3.digest_for_wire(raw)
    return ExternalReconstructionSubmissionV3.model_validate(raw)


def _v3_unknown_producer() -> dict[str, Any]:
    return {
        "producerKnowledge": "UNKNOWN",
        "softwareName": None,
        "softwareVersion": None,
        "buildIdentifier": None,
        "producerRunIdentifier": None,
        "configurationDigest": None,
        "completedAt": None,
        "sourceNote": None,
    }


def _v3_partial_producer() -> dict[str, Any]:
    return {
        "producerKnowledge": "PARTIAL",
        "softwareName": "Pix4D",
        "softwareVersion": None,
        "buildIdentifier": None,
        "producerRunIdentifier": None,
        "configurationDigest": None,
        "completedAt": None,
        "sourceNote": "publisher page names the tool but no version",
    }


def _v3_declared_producer() -> dict[str, Any]:
    return {
        "producerKnowledge": "DECLARED",
        "softwareName": "OpenDroneMap",
        "softwareVersion": "3.5",
        "buildIdentifier": "odm-3.5",
        "producerRunIdentifier": "run-odm-1",
        "configurationDigest": "sha256:" + "b" * 64,
        "completedAt": "2026-09-28T12:00:00Z",
        "sourceNote": "customer run log",
    }


def _v3_capture_date_only() -> dict[str, Any]:
    return {
        "rawMediaStoredByKsi": False,
        "originalRetentionLocus": "upstream_source",
        "originalRetentionDetail": "public portal fixture",
        "localInputManifestDigest": None,
        "imageCount": None,
        "captureStartedAt": None,
        "captureEndedAt": None,
        "captureDate": "2021-08-17",
        "captureBasis": "DATE_ONLY",
        "upstreamSource": {
            "sourceUri": "https://portal.example.test/exports/ortho-17",
            "sourceSha256": None,
            "licenceDeclaration": "publisher states open reuse",
            "retrievalNote": "exported 2021-08-18 with LocalExporter 1.2",
        },
        "derivativeExport": {
            "toolName": "LocalExporter",
            "toolVersion": "1.2",
            "settingsDigest": None,
            "exportedAt": "2021-08-18T00:00:00Z",
            "exportNote": "compressed overviews for viewing",
        },
    }


def _v3_capture_unknown() -> dict[str, Any]:
    return {
        "rawMediaStoredByKsi": False,
        "originalRetentionLocus": "unknown",
        "originalRetentionDetail": None,
        "localInputManifestDigest": None,
        "imageCount": None,
        "captureStartedAt": None,
        "captureEndedAt": None,
        "captureDate": None,
        "captureBasis": "UNKNOWN",
        "upstreamSource": None,
        "derivativeExport": None,
    }


def _epoch(order: Any) -> str:
    from ksi_core.domains.observations.epoch_identity import observation_epoch_id

    return observation_epoch_id(order)


def _setup(
    tmp_path: Path, *, multi_area: bool = False, inspections: Any = None
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
        work_area_ids=[
            area_a.work_area.work_area_id,
            *([area_b.work_area.work_area_id] if multi_area else []),
        ],
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        idempotency_key="description-order",
        actor="fixture",
        now=_NOW,
    )
    storage = _Storage()
    reconstruction = ExternalReconstructionStore(DurableJournal(tmp_path / "reconstruction.jsonl"))
    records = [
        _auth_record(_TOKEN, principal_id="description-owner", organization_id="org-a"),
        _auth_record(
            _LIMITED_TOKEN,
            principal_id="description-limited",
            organization_id="org-a",
            allowed_site_ids=frozenset({"site-a"}),
            allowed_work_area_ids=frozenset({area_a.work_area.work_area_id}),
        ),
        _auth_record(_OTHER_TOKEN, principal_id="other", organization_id="org-b"),
    ]
    kwargs: dict[str, Any] = {}
    if inspections is not None:
        from ksi_core.domains.external.ingress.external_display_artifacts import (
            ExternalDisplayArtifactStore,
        )

        kwargs["external_artifact_inspection_store"] = inspections
        # Placeholder satisfying the assembly-table non-None assert: the
        # description projection under test reads the inspection stub only
        # and never touches display routes.
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


def _headers(token: str = _TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register_and_seal(order: Any, storage: _Storage, reconstruction: Any, submission: Any) -> None:
    registered = reconstruction.register(
        submission, work_order=order, registered_by="description-owner", now=_NOW
    )
    assert registered.revision is not None
    content_by_artifact = {
        artifact.artifact_id: (
            _DSM_CONTENT
            if artifact.kind.value == "dsm"
            and len(submission.artifacts) == 1
            and artifact.artifact_id == "dsm"
            else _CONTENT
        )
        for artifact in submission.artifacts
    }
    grant = reconstruction.upload_grants(
        order.work_order_id,
        submission.submission_id,
        1,
        organization_id=order.organization_id,
        site_id=order.site_id,
        storage=storage,
    )
    assert grant.grants
    for item in grant.grants:
        data = content_by_artifact[item.artifact_id]
        storage.bytes[item.object_key] = data
        storage.objects[item.object_key] = ObjectStorageObservation(
            object_key=item.object_key,
            exists=True,
            size_bytes=len(data),
            sha256="sha256:" + hashlib.sha256(data).hexdigest(),
            content_type="application/octet-stream",
        )
    sealed = reconstruction.seal(
        order.work_order_id,
        submission.submission_id,
        1,
        organization_id=order.organization_id,
        site_id=order.site_id,
        storage=storage,
        now=_NOW,
    )
    assert sealed.revision is not None and sealed.revision.manifest is not None


def _root(order: Any, area: Any) -> str:
    return f"/v2/sites/{order.site_id}/work-areas/{area.work_area_id}/spatial-assets"


def _schema() -> Any:
    return json.loads(Path("contracts/schemas/spatial-asset-description.v1.json").read_text())


def test_describe_v1_preserves_catalog_facts_and_adds_provenance(tmp_path: Path) -> None:
    client, order, storage, reconstruction, area_a, _, _, _, _ = _setup(tmp_path)
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v1(site_id=order.site_id, order=order, submission_id="desc-v1"),
    )

    listed = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=_headers(),
    )
    assert listed.status_code == 200
    asset_ref = listed.json()["assets"][0]["assetRef"]

    response = client.get(f"{_root(order, area_a)}/{asset_ref}", headers=_headers())
    assert response.status_code == 200, response.text
    Draft202012Validator(_schema()).validate(response.json())
    assert len(response.content) <= 512 * 1024
    body = response.json()

    assert body["contractVersion"] == "spatial-asset-description.v1"
    v1_detail = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets/{asset_ref}",
        headers=_headers(),
    ).json()
    for field in (
        "assetRef",
        "siteId",
        "workAreaId",
        "workOrderId",
        "observationEpochId",
        "submissionRef",
        "revision",
        "artifactId",
        "kind",
        "lifecycleState",
        "declared",
        "observed",
        "inspection",
        "dataAccess",
        "analysisStatus",
    ):
        assert body[field] == v1_detail[field], field
    assert body["semanticKindNote"] == "SEMANTIC_KIND_IS_DECLARED"
    assert body["limitations"] == [
        "SEMANTIC_KIND_IS_DECLARED",
        "ANALYSIS_NOT_EVALUATED",
        "NO_ORIGINAL_STORAGE_OR_DOWNLOAD_FROM_THIS_ENDPOINT",
    ]
    assert body["supportedActions"] == ["VIEW_METADATA"]

    producer = body["producer"]
    assert producer["factClass"] == "DECLARED"
    assert producer["producerKnowledge"] == "DECLARED"
    assert producer["softwareName"] == "Terra"
    assert producer["softwareVersion"] == "test"
    assert producer["buildIdentifier"] == "build-7"
    assert producer["producerRunIdentifier"] == "run-9"
    assert producer["configurationDigest"] == "sha256:" + "a" * 64
    assert producer["completedAt"] == "2026-09-30T00:30:00Z"
    assert producer["sourceNote"] is None

    capture = body["capture"]
    assert capture["factClass"] == "DECLARED"
    assert capture["captureBasis"] == "EXACT_INTERVAL"
    assert capture["captureStartedAt"] == "2026-09-29T00:00:00Z"
    assert capture["captureEndedAt"] == "2026-09-29T00:10:00Z"
    assert capture["captureDate"] is None
    assert capture["rawMediaStoredByKsi"] is False
    assert capture["originalRetentionLocus"] == "customer_workstation"
    assert capture["imageCount"] == 12

    assert body["upstreamSource"] is None
    assert body["derivativeExport"] is None
    assert body["raster"] is None  # no inspection store configured
    assert body["inspection"]["state"] == "INSPECTION_NOT_CONFIGURED"

    text = response.text
    for leaked in ("objectKey", "uploadUrl", "presigned", "token", "capability", "submission-one"):
        assert leaked not in text


def test_describe_v2_dsm_without_capture_times_and_v3_unknown_stays_null(tmp_path: Path) -> None:
    client, order, storage, reconstruction, area_a, _, _, _, _ = _setup(tmp_path)
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v2(site_id=order.site_id, order=order, submission_id="desc-v2"),
    )
    v3 = _submission_v3(
        site_id=order.site_id,
        order=order,
        submission_id="desc-v3-unknown",
        producer=_v3_unknown_producer(),
        capture=_v3_capture_unknown(),
        artifacts=[_artifact("ortho", "ortho", _CONTENT)],
    )
    _register_and_seal(order, storage, reconstruction, v3)

    refs = {
        item["artifactId"]: item["assetRef"]
        for item in client.get(
            f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
            headers=_headers(),
        ).json()["assets"]
    }

    dsm = client.get(f"{_root(order, area_a)}/{refs['dsm']}", headers=_headers()).json()
    assert dsm["kind"] == "dsm"
    assert dsm["capture"]["captureBasis"] == "UNKNOWN"
    assert dsm["capture"]["captureStartedAt"] is None
    assert dsm["capture"]["captureEndedAt"] is None
    assert dsm["capture"]["captureDate"] is None
    assert (
        dsm["producer"]["producerKnowledge"] == "DECLARED"
        and dsm["producer"]["softwareName"] == "Metashape"
    )
    assert dsm["producer"]["completedAt"] is None

    ortho = client.get(f"{_root(order, area_a)}/{refs['ortho']}", headers=_headers()).json()
    assert ortho["producer"]["producerKnowledge"] == "UNKNOWN"
    assert ortho["producer"]["softwareName"] is None
    assert ortho["producer"]["softwareVersion"] is None
    # Unknown stays typed nulls; the fabricated label "unknown" never appears
    # in a name/version string (the knowledge enum carries it instead).
    assert (
        "unknown"
        not in json.dumps(
            {k: v for k, v in ortho["producer"].items() if k != "producerKnowledge"}
        ).lower()
    )
    assert ortho["capture"]["captureBasis"] == "UNKNOWN"
    assert ortho["capture"]["originalRetentionLocus"] == "unknown"
    assert ortho["raster"] is None


def test_describe_v3_partial_and_declared_producers_with_upstream_and_date_only(
    tmp_path: Path,
) -> None:
    client, order, storage, reconstruction, area_a, _, _, _, _ = _setup(tmp_path)
    partial = _submission_v3(
        site_id=order.site_id,
        order=order,
        submission_id="desc-v3-partial",
        producer=_v3_partial_producer(),
        capture=_v3_capture_date_only(),
        artifacts=[_artifact("ortho", "ortho", _CONTENT)],
    )
    _register_and_seal(order, storage, reconstruction, partial)

    asset_ref = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=_headers(),
    ).json()["assets"][0]["assetRef"]
    body = client.get(f"{_root(order, area_a)}/{asset_ref}", headers=_headers()).json()

    assert body["producer"]["producerKnowledge"] == "PARTIAL"
    assert body["producer"]["softwareName"] == "Pix4D"
    assert body["producer"]["softwareVersion"] is None
    assert body["producer"]["sourceNote"] == "publisher page names the tool but no version"
    assert body["capture"]["captureBasis"] == "DATE_ONLY"
    assert body["capture"]["captureDate"] == "2021-08-17"
    assert body["capture"]["captureStartedAt"] is None
    assert body["capture"]["captureEndedAt"] is None
    # The source URI is carried exactly as declared and never fetched: no fetch
    # surface exists on this read path, and the stored bytes stay untouched.
    assert body["upstreamSource"]["sourceUri"] == "https://portal.example.test/exports/ortho-17"
    assert body["upstreamSource"]["licenceDeclaration"] == "publisher states open reuse"
    assert body["derivativeExport"]["toolName"] == "LocalExporter"
    assert body["derivativeExport"]["toolVersion"] == "1.2"


def test_describe_projects_measured_raster_with_units_and_rotation(tmp_path: Path) -> None:
    inspections = _InspectionSpy(
        {
            "ortho": _measurements(
                transform=(0.5, 0.1, 100.0, 0.05, -0.5, 200.0),
                vertical=("EPSG:5186+KNGeoid2018", "parser observed geoid model"),
            ),
            "dsm": _measurements(
                transform=(0.5, 0.0, 100.0, 0.0, -0.5, 200.0),
                vertical=None,
            ),
        }
    )
    client, order, storage, reconstruction, area_a, _, _, _, _ = _setup(
        tmp_path, inspections=inspections
    )
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v1(site_id=order.site_id, order=order, submission_id="desc-rot"),
    )
    v2 = _submission_v2(site_id=order.site_id, order=order, submission_id="desc-dsm-missing")
    _register_and_seal(order, storage, reconstruction, v2)

    refs = {
        item["artifactId"]: item["assetRef"]
        for item in client.get(
            f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
            headers=_headers(),
        ).json()["assets"]
    }

    ortho = client.get(f"{_root(order, area_a)}/{refs['ortho']}", headers=_headers()).json()
    raster = ortho["raster"]
    assert raster["factClass"] == "INSPECTED"
    assert raster["sourceReportDigest"] == "sha256:" + "3" * 64
    assert raster["inspectorBuildDigest"] == "sha256:" + "4" * 64
    assert raster["bandCount"] == 1
    assert raster["dtype"] == "uint16"
    assert raster["layout"] == "GEOTIFF_STRIPED_V1"
    assert raster["nodataRepresentation"] == "FINITE"
    assert raster["nodataValue"] == -9999.0
    assert raster["validPixelCount"] == 380
    assert raster["horizontalUnits"] == "metre"
    resolution = raster["pixelResolution"]
    assert resolution["transformIsRotated"] is True
    import math

    assert resolution["resolutionX"] == pytest.approx(math.hypot(0.5, 0.05))
    assert resolution["resolutionY"] == pytest.approx(math.hypot(0.1, -0.5))
    # The naive abs(a)/abs(e) reading would claim exactly 0.5/0.5 here.
    assert resolution["resolutionX"] != 0.5
    assert raster["observedVerticalReference"] == {
        "identifier": "EPSG:5186+KNGeoid2018",
        "basis": "parser observed geoid model",
    }

    # DSM-only record without observed vertical: reference stays null while
    # the remaining measured facts (bands, units, resolution) are preserved.
    dsm = client.get(f"{_root(order, area_a)}/{refs['dsm']}", headers=_headers()).json()
    assert dsm["raster"]["observedVerticalReference"] is None
    assert dsm["raster"]["horizontalUnits"] == "metre"
    assert dsm["raster"]["pixelResolution"]["transformIsRotated"] is False
    assert dsm["raster"]["pixelResolution"]["resolutionX"] == pytest.approx(0.5)
    assert dsm["raster"]["pixelResolution"]["resolutionY"] == pytest.approx(0.5)


def test_describe_units_come_from_inspected_crs_only() -> None:
    from pyproj import CRS

    wkt_5186 = CRS.from_user_input("EPSG:5186").to_wkt()
    wkt_4326 = CRS.from_user_input("EPSG:4326").to_wkt()
    assert (
        horizontal_units_from_inspected_crs(crs_identifier="EPSG:5186", crs_wkt=wkt_5186) == "metre"
    )
    assert horizontal_units_from_inspected_crs(crs_identifier="EPSG:5186", crs_wkt=None) is None
    assert horizontal_units_from_inspected_crs(crs_identifier="EPSG:5186", crs_wkt=wkt_4326) is None
    assert horizontal_units_from_inspected_crs(crs_identifier="not-a-crs", crs_wkt=wkt_5186) is None


def test_describe_pixel_resolution_guards() -> None:
    good = pixel_resolution_from_transform(
        transform=(0.5, 0.0, 0.0, 0.0, -0.5, 0.0),
        source_report_digest=_DIGEST,
        inspector_build_digest=_DIGEST,
    )
    assert good is not None and good.transform_is_rotated is False
    assert good.resolution_x == 0.5 and good.resolution_y == 0.5
    degenerate = pixel_resolution_from_transform(
        transform=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        source_report_digest=_DIGEST,
        inspector_build_digest=_DIGEST,
    )
    assert degenerate is None


def test_describe_rejects_foreign_stale_and_malformed_refs(tmp_path: Path) -> None:
    client, order, storage, reconstruction, area_a, area_b, _, _, _ = _setup(tmp_path)
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v1(site_id=order.site_id, order=order, submission_id="desc-scope"),
    )
    asset_ref = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=_headers(),
    ).json()["assets"][0]["assetRef"]

    assert client.get(f"{_root(order, area_a)}/{asset_ref}").status_code == 401
    assert (
        client.get(
            f"{_root(order, area_a)}/{asset_ref}", headers=_headers(_OTHER_TOKEN)
        ).status_code
        == 404
    )
    # The integrated route allowlist admits scoped read-only operators to
    # the handler. Own-area metadata is readable; a foreign area remains the
    # same opaque 404 as an absent asset (never a wider grant or MCP privilege).
    foreign_area = client.get(
        f"/v2/sites/{order.site_id}/work-areas/{area_b.work_area_id}/spatial-assets/{asset_ref}",
        headers=_headers(_LIMITED_TOKEN),
    )
    assert foreign_area.status_code == 404
    allowed = client.get(
        f"/v2/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets/{asset_ref}",
        headers=_headers(_LIMITED_TOKEN),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json() == client.get(
        f"{_root(order, area_a)}/{asset_ref}", headers=_headers()
    ).json()
    assert client.get(f"{_root(order, area_a)}/not-a-ref", headers=_headers()).status_code == 404
    missing = "ksa-v1-" + "0" * 64
    absent = client.get(f"{_root(order, area_a)}/{missing}", headers=_headers())
    assert absent.status_code == 404
    assert foreign_area.json() == absent.json()

    multi_client, multi_order, multi_storage, multi_store, multi_area_a, _, _, _, _ = _setup(
        tmp_path / "multi", multi_area=True
    )
    _register_and_seal(
        multi_order,
        multi_storage,
        multi_store,
        _submission_v1(site_id=multi_order.site_id, order=multi_order, submission_id="desc-multi"),
    )
    multi_ref = "ksa-v1-" + "1" * 64
    assert (
        multi_client.get(
            f"/v2/sites/{multi_order.site_id}/work-areas/{multi_area_a.work_area_id}"
            f"/spatial-assets/{multi_ref}",
            headers=_headers(),
        ).status_code
        == 404
    )


def test_describe_unsealed_has_provenance_but_no_observed_or_raster(tmp_path: Path) -> None:
    client, order, _storage, reconstruction, area_a, _, _, _, _ = _setup(tmp_path)
    submission = _submission_v1(site_id=order.site_id, order=order, submission_id="desc-unsealed")
    assert (
        reconstruction.register(
            submission, work_order=order, registered_by="description-owner", now=_NOW
        ).revision
        is not None
    )
    asset_ref = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=_headers(),
    ).json()["assets"][0]["assetRef"]
    body = client.get(f"{_root(order, area_a)}/{asset_ref}", headers=_headers()).json()

    assert body["lifecycleState"] == "UNSEALED"
    assert body["observed"] is None
    assert body["inspection"]["state"] == "PENDING_SEAL"
    assert body["raster"] is None
    assert body["producer"]["softwareName"] == "Terra"
    assert body["capture"]["captureBasis"] == "EXACT_INTERVAL"


def test_describe_is_read_only_repeatable_and_restart_stable(tmp_path: Path) -> None:
    client, order, storage, reconstruction, area_a, _, _, _, _ = _setup(tmp_path)
    _register_and_seal(
        order,
        storage,
        reconstruction,
        _submission_v1(site_id=order.site_id, order=order, submission_id="desc-stable"),
    )
    asset_ref = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=_headers(),
    ).json()["assets"][0]["assetRef"]
    target = f"{_root(order, area_a)}/{asset_ref}"

    before = {path.name: path.read_bytes() for path in tmp_path.glob("*.jsonl")}
    first = client.get(target, headers=_headers())
    second = client.get(target, headers=_headers())
    after = {path.name: path.read_bytes() for path in tmp_path.glob("*.jsonl")}
    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json()
    assert before == after

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
    # The replayed app reuses identical grants over copied journals with fresh
    # in-memory stores: the stable address and exact source identity must
    # reproduce byte-for-byte, proving restart consistency.
    replayed = TestClient(
        create_app(
            auth_registry=AuthRegistry(
                [_auth_record(_TOKEN, principal_id="description-owner", organization_id="org-a")]
            ),
            site_store=replayed_sites,
            work_area_store=replayed_areas,
            observation_work_order_store=replayed_orders,
            evidence_storage=_Storage(),
            external_reconstruction_store=replayed_reconstruction,
        )
    )
    replayed_response = replayed.get(target, headers=_headers())
    assert replayed_response.status_code == 200
    assert replayed_response.json() == first.json()


def test_describe_openapi_declares_v2_route_and_schema(tmp_path: Path) -> None:
    import yaml

    client, order, _, _, area_a, _, _, _, _ = _setup(tmp_path)
    app = client.app
    assert (
        "/v2/sites/{site_id}/work-areas/{work_area_id}/spatial-assets/{asset_ref}"
        in app.openapi()["paths"]
    )
    document = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "contracts/api/openapi-core.yaml").read_text()
    )
    # The shared handwritten contract is parent-owned: this only pins the
    # in-code response model the insertion must mirror, without editing it.
    live = app.openapi()["components"]["schemas"]
    assert "SpatialAssetDescriptionV1" in live
    assert (
        live["SpatialAssetDescriptionV1"]["properties"]["contractVersion"]["const"]
        == "spatial-asset-description.v1"
    )
    assert (
        "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-assets/{asset_ref}"
        in document["paths"]
    )
