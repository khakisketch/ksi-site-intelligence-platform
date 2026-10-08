"""The read-only spatial asset catalog projects existing Core authority."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    HumanAuthMode,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.domains.external.ingress.external_artifact_inspections import (
    ExternalArtifactInspectionStore,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import ObjectStorageObservation
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig
from ksi_core.sites import SiteStore
from ksi_core.work_areas import WorkAreaStore
from ksi_event_contracts.external_artifact_validation import ArtifactOutcome
from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1
from ksi_event_contracts.observation_work_order import ObservationWorkOrderExecutionMode
from ksi_event_contracts.site_frame import SiteFrame

_NOW = datetime(2026, 9, 30, tzinfo=UTC)
_TOKEN = "spatial-catalog-owner"  # noqa: S105 -- fixed test credential
_LIMITED_TOKEN = "spatial-catalog-limited"  # noqa: S105
_OTHER_TOKEN = "spatial-catalog-other"  # noqa: S105
_CONTENT = b"sealed ortho bytes"


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

    def presigned_put(self, object_key: str, *, content_type: str, ttl: timedelta) -> str:
        raise NotImplementedError("Catalog fixture accepts only digest-bound upload signing")

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        raise NotImplementedError("Catalog fixture cannot create server artifacts")

    def delete(self, object_key: str) -> None:
        raise NotImplementedError("Catalog fixture cannot delete evidence")


class _InspectionSpy(ExternalArtifactInspectionStore):
    def __init__(self, *, measured: bool = False) -> None:
        self.calls = 0
        self.measured = measured

    def public_snapshot_bounded(
        self,
        subject: Any,
        *,
        max_records: int,
        max_policy_records: int | None = None,
        max_retained_policies: int | None = None,
    ) -> Any:
        del subject
        assert max_records == 128
        assert max_policy_records == 64
        self.calls += 1
        report = None
        if self.measured:
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
        return SimpleNamespace(
            state="INSPECTION_REPORTED" if report else "INSPECTION_PENDING", report=report
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


def _submission(
    *,
    site_id: str,
    order: Any,
    submission_id: str,
    revision: int = 1,
    artifact_id: str = "ortho",
) -> ExternalReconstructionSubmissionV1:
    raw = {
        "submissionId": submission_id,
        "revision": revision,
        "organizationId": order.organization_id,
        "siteId": site_id,
        "observationEpochId": order_epoch(order),
        "submittedAt": "2026-09-30T00:00:00Z",
        "submittedBy": "catalog-owner",
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
            "captureStartedAt": "2026-09-29T00:00:00Z",
            "captureEndedAt": "2026-09-29T00:10:00Z",
        },
        "artifacts": [
            {
                "artifactId": artifact_id,
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


def order_epoch(order: Any) -> str:
    from ksi_core.domains.observations.epoch_identity import observation_epoch_id

    return observation_epoch_id(order)


def _setup(
    tmp_path: Path, *, multi_area: bool = False
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
        idempotency_key="catalog-order",
        actor="fixture",
        now=_NOW,
    )
    storage = _Storage()
    reconstruction = ExternalReconstructionStore(DurableJournal(tmp_path / "reconstruction.jsonl"))
    records = [
        _auth_record(_TOKEN, principal_id="catalog-owner", organization_id="org-a"),
        _auth_record(
            _LIMITED_TOKEN,
            principal_id="catalog-limited",
            organization_id="org-a",
            allowed_site_ids=frozenset({"site-a"}),
            allowed_work_area_ids=frozenset({area_a.work_area.work_area_id}),
        ),
        _auth_record(_OTHER_TOKEN, principal_id="other", organization_id="org-b"),
    ]
    app = create_app(
        auth_registry=AuthRegistry(records),
        site_store=sites,
        work_area_store=areas,
        observation_work_order_store=work_orders,
        evidence_storage=storage,
        external_reconstruction_store=reconstruction,
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


def _enable_mapped_oidc(app: Any, *, site_id: str, work_area_id: str) -> str:
    issuer = "https://catalog-oidc.example.test"
    audience = "ksi-catalog-test"
    subject = "catalog-mapped-user"
    key = generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_numbers()

    def b64(value: int) -> str:
        return jwt.utils.base64url_encode(
            value.to_bytes((value.bit_length() + 7) // 8, "big")
        ).decode()

    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": "catalog-key",
        "n": b64(public.n),
        "e": b64(public.e),
    }
    registry = OidcSubjectRegistry.from_document(
        {
            "version": "oidc-subject-registry.v1",
            "subjects": [
                {
                    "issuer": issuer,
                    "subject": subject,
                    "principalId": "mapped-catalog-user",
                    "organizationId": "org-a",
                    "role": "FIELD_OPERATOR",
                    "status": "ACTIVE",
                    "allowedSiteIds": [site_id],
                    "allowedWorkAreaIds": [work_area_id],
                }
            ],
        },
        expected_issuer=issuer,
    )
    app.state.human_auth_mode = HumanAuthMode.OIDC
    app.state.oidc_verifier = OidcJwtVerifier(
        OidcVerifierConfig(issuer=issuer, audience=audience, jwks_url=f"{issuer}/jwks"),
        fetch_jwks=lambda: {"keys": [jwk]},
        subject_registry=registry,
    )
    now = int(time.time())
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": subject,
            "exp": now + 600,
            "nbf": now - 5,
            "ksi_role": "ADMIN",
            "ksi_organization_id": "org-b",
        },
        key,
        algorithm="RS256",
        headers={"kid": "catalog-key"},
    )


def _register_and_seal(
    order: Any,
    storage: _Storage,
    reconstruction: Any,
    *,
    sealed: bool,
    submission_id: str = "submission-one",
) -> None:
    submission = _submission(site_id=order.site_id, order=order, submission_id=submission_id)
    registered = reconstruction.register(
        submission, work_order=order, registered_by="catalog-owner", now=_NOW
    )
    assert registered.revision is not None
    if not sealed:
        return
    grant = reconstruction.upload_grants(
        order.work_order_id,
        submission.submission_id,
        1,
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
        content_type="application/octet-stream",
    )
    sealed_result = reconstruction.seal(
        order.work_order_id,
        submission.submission_id,
        1,
        organization_id=order.organization_id,
        site_id=order.site_id,
        storage=storage,
        now=_NOW,
    )
    assert sealed_result.revision is not None and sealed_result.revision.manifest is not None


def _register_only(
    order: Any,
    reconstruction: Any,
    *,
    submission_id: str,
    revision: int = 1,
    artifact_id: str = "ortho",
) -> None:
    submission = _submission(
        site_id=order.site_id,
        order=order,
        submission_id=submission_id,
        revision=revision,
        artifact_id=artifact_id,
    )
    result = reconstruction.register(
        submission, work_order=order, registered_by="catalog-owner", now=_NOW
    )
    assert result.revision is not None


def test_catalog_projects_declared_and_observed_facts_without_storage_capability(
    tmp_path: Path,
) -> None:
    client, order, storage, reconstruction, area_a, _, _, _, _ = _setup(tmp_path)
    _register_and_seal(order, storage, reconstruction, sealed=True)

    response = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    schema = json.loads(Path("contracts/schemas/spatial-asset-catalog.v1.json").read_text())
    Draft202012Validator(schema).validate(body)
    assert len(body["assets"]) == 1
    asset = body["assets"][0]
    assert asset["declared"]["factClass"] == "DECLARED"
    assert asset["declared"]["sha256"] == hashlib.sha256(_CONTENT).hexdigest()
    assert asset["observed"]["factClass"] == "OBSERVED"
    assert asset["observed"]["sha256"] == hashlib.sha256(_CONTENT).hexdigest()
    assert asset["inspection"]["state"] == "INSPECTION_NOT_CONFIGURED"
    assert asset["declared"]["producerCompletedAt"] == "2026-09-30T00:30:00Z"
    assert asset["dataAccess"] == "NOT_AVAILABLE_FROM_CATALOG"
    assert asset["analysisStatus"] == "NOT_EVALUATED"
    assert "objectKey" not in response.text and "uploadUrl" not in response.text
    assert len(response.content) <= 512 * 1024

    detail = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets/{asset['assetRef']}",
        headers=_headers(),
    )
    assert detail.status_code == 200
    assert detail.json() == asset
    Draft202012Validator(schema).validate(detail.json())


def test_catalog_keeps_unsealed_declaration_distinct_and_multi_area_unattributed(
    tmp_path: Path,
) -> None:
    client, order, storage, reconstruction, area_a, _, _, _, _ = _setup(tmp_path)
    _register_and_seal(order, storage, reconstruction, sealed=False)

    response = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=_headers(),
    )

    assert response.status_code == 200
    asset = response.json()["assets"][0]
    assert asset["lifecycleState"] == "UNSEALED"
    assert asset["observed"] is None
    assert asset["inspection"]["state"] == "PENDING_SEAL"
    assert asset["dataAccess"] == "NOT_AVAILABLE_FROM_CATALOG"

    multi_client, multi_order, multi_storage, multi_store, multi_area_a, _, _, _, _ = _setup(
        tmp_path / "multi", multi_area=True
    )
    _register_and_seal(multi_order, multi_storage, multi_store, sealed=True)
    limited = multi_client.get(
        f"/v1/sites/{multi_order.site_id}/work-areas/{multi_area_a.work_area_id}/spatial-assets",
        headers=_headers(),
    )
    assert limited.status_code == 200
    assert limited.json()["assets"] == []
    assert "multi-area records" in limited.json()["scopeNote"]


def test_catalog_rechecks_grants_and_rejects_invalid_or_foreign_cursors(tmp_path: Path) -> None:
    client, order, storage, reconstruction, area_a, area_b, _, _, _ = _setup(tmp_path)
    _register_and_seal(order, storage, reconstruction, sealed=True)
    root = f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets"

    assert client.get(root + "?limit=51", headers=_headers()).status_code == 422
    assert client.get(root + "?cursor=%%%", headers=_headers()).status_code == 400
    denied = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_b.work_area_id}/spatial-assets",
        headers=_headers(_LIMITED_TOKEN),
    )
    assert denied.status_code == 404
    foreign_site = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_b.work_area_id}/spatial-assets",
        headers=_headers(_OTHER_TOKEN),
    )
    assert foreign_site.status_code == 404


def test_catalog_pages_stably_and_keeps_customer_artifact_ids_out_of_route_refs(
    tmp_path: Path,
) -> None:
    client, order, _storage, reconstruction, area_a, area_b, _, _, _ = _setup(tmp_path)
    for index in range(51):
        _register_only(
            order,
            reconstruction,
            submission_id=f"submission-{index:03d}",
            artifact_id="ortho/../customer id",
        )
    root = f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets"

    first = client.get(root + "?limit=50", headers=_headers())
    assert first.status_code == 200, first.text
    first_page = first.json()
    assert len(first_page["assets"]) == 50
    assert first_page["hasMore"] is True
    assert len(first.content) <= 512 * 1024
    refs = [item["assetRef"] for item in first_page["assets"]]
    assert refs == sorted(refs)
    assert all("/" not in ref and ".." not in ref for ref in refs)
    assert first_page["assets"][0]["artifactId"] == "ortho/../customer id"

    second = client.get(root + "?limit=50&cursor=" + first_page["nextCursor"], headers=_headers())
    assert second.status_code == 200, second.text
    assert len(second.json()["assets"]) == 1
    assert second.json()["assets"][0]["assetRef"] not in refs
    foreign_cursor = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_b.work_area_id}/spatial-assets"
        + "?cursor="
        + first_page["nextCursor"],
        headers=_headers(),
    )
    assert foreign_cursor.status_code == 400


def test_newer_revision_marks_older_asset_superseded_without_claiming_access(
    tmp_path: Path,
) -> None:
    client, order, storage, reconstruction, area_a, _, _, _, _ = _setup(tmp_path)
    _register_and_seal(order, storage, reconstruction, sealed=True)
    _register_only(
        order,
        reconstruction,
        submission_id="submission-one",
        revision=2,
    )

    response = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=_headers(),
    )
    assert response.status_code == 200
    by_revision = {item["revision"]: item for item in response.json()["assets"]}
    assert by_revision[1]["lifecycleState"] == "SUPERSEDED"
    assert by_revision[1]["observed"] is not None
    assert by_revision[1]["dataAccess"] == "NOT_AVAILABLE_FROM_CATALOG"
    assert by_revision[2]["lifecycleState"] == "UNSEALED"
    assert by_revision[2]["observed"] is None


def test_mapped_oidc_can_read_only_its_granted_catalog_scope(tmp_path: Path) -> None:
    client, order, _storage, _reconstruction, area_a, area_b, _, _, _ = _setup(tmp_path)
    token = _enable_mapped_oidc(client.app, site_id=order.site_id, work_area_id=area_a.work_area_id)
    headers = _headers(token)

    allowed = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=headers,
    )
    denied_area = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_b.work_area_id}/spatial-assets",
        headers=headers,
    )
    denied_site = client.get(
        f"/v1/sites/site-not-granted/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=headers,
    )

    assert allowed.status_code == 200
    assert denied_area.status_code == 404
    assert denied_site.status_code == 404


def test_catalog_only_inspects_selected_page_and_projects_measured_raster_provenance(
    tmp_path: Path,
) -> None:
    inspections = _InspectionSpy(measured=True)
    _client, order, storage, reconstruction, area_a, _, work_orders, sites, areas = _setup(tmp_path)
    _register_and_seal(order, storage, reconstruction, sealed=True, submission_id="inspection-one")

    from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog

    catalog = SpatialAssetCatalog(
        reconstruction=reconstruction,
        work_orders=work_orders,
        sites=sites,
        work_areas=areas,
        inspections=inspections,
    )
    principal = _auth_record(
        _TOKEN, principal_id="catalog-owner", organization_id=order.organization_id
    ).principal
    items = catalog.items(order.site_id, area_a.work_area_id, principal)
    assert inspections.calls == 0
    page = [catalog.with_inspection(item, principal) for item in items[:50]]

    assert inspections.calls == 1
    raster = page[0].model_dump(by_alias=True, mode="json")["inspection"]["raster"]
    assert raster["factClass"] == "INSPECTED"
    assert raster["sourceReportDigest"] == "sha256:" + "3" * 64
    assert raster["inspectorBuildDigest"] == "sha256:" + "4" * 64
    assert raster["observedCrsIdentifier"] == "EPSG:5186"
    assert raster["transform"] == [0.5, 0.0, 100.0, 0.0, -0.5, 200.0]
    assert raster["footprintWkt"].startswith("POLYGON")
    assert raster["width"] == 20 and raster["height"] == 20


def test_catalog_http_list_and_detail_inspect_only_returned_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog

    inspection_calls = 0
    original_inspection = SpatialAssetCatalog._inspection

    def count_inspection(self: Any, record: Any, artifact_id: str) -> Any:
        nonlocal inspection_calls
        inspection_calls += 1
        return original_inspection(self, record, artifact_id)

    monkeypatch.setattr(SpatialAssetCatalog, "_inspection", count_inspection)
    client, order, storage, reconstruction, area_a, _, _, _, _ = _setup(tmp_path)
    for index in range(55):
        _register_and_seal(
            order,
            storage,
            reconstruction,
            sealed=True,
            submission_id=f"http-inspection-{index:03d}",
        )

    root = f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets"
    listed = client.get(root + "?limit=50", headers=_headers())
    assert listed.status_code == 200
    assert len(listed.json()["assets"]) == 50
    assert inspection_calls == 50

    detail = client.get(root + "/" + listed.json()["assets"][0]["assetRef"], headers=_headers())
    assert detail.status_code == 200
    assert inspection_calls == 51


def test_catalog_fails_explicitly_before_exceeding_work_order_or_revision_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_core.domains.external.ingress.spatial_asset_catalog as catalog_module

    inspections = _InspectionSpy()
    client, order, _storage, reconstruction, area_a, _, work_orders, _, _ = _setup(tmp_path)
    extra = work_orders.create_work_order(
        organization_id=order.organization_id,
        site_id=order.site_id,
        name="Second bounded WorkOrder",
        work_area_ids=list(order.work_area_ids),
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        idempotency_key="catalog-order-two",
        actor="fixture",
        now=_NOW,
    )
    assert extra.work_order_id != order.work_order_id
    monkeypatch.setattr(catalog_module, "_MAX_SITE_WORK_ORDERS", 1)

    over_order_budget = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=_headers(),
    )
    assert over_order_budget.status_code == 503
    assert over_order_budget.json()["detail"] == "SPATIAL_ASSET_SOURCE_BUDGET_EXCEEDED"
    assert inspections.calls == 0

    monkeypatch.setattr(catalog_module, "_MAX_SITE_WORK_ORDERS", 10)
    monkeypatch.setattr(catalog_module, "_MAX_SITE_REVISIONS", 1)
    _register_only(order, reconstruction, submission_id="revision-budget", revision=1)
    _register_only(order, reconstruction, submission_id="revision-budget", revision=2)
    over_revision_budget = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=_headers(),
    )
    assert over_revision_budget.status_code == 503
    assert over_revision_budget.json()["detail"] == "SPATIAL_ASSET_SOURCE_BUDGET_EXCEEDED"
    assert inspections.calls == 0

    monkeypatch.setattr(catalog_module, "_MAX_SITE_REVISIONS", 10)
    monkeypatch.setattr(catalog_module, "_MAX_SUBMISSIONS_PER_WORK_ORDER", 1)
    _register_only(order, reconstruction, submission_id="second-submission-budget")
    over_submission_budget = client.get(
        f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}/spatial-assets",
        headers=_headers(),
    )
    assert over_submission_budget.status_code == 503
    assert over_submission_budget.json()["detail"] == "SPATIAL_ASSET_SOURCE_BUDGET_EXCEEDED"
    assert inspections.calls == 0
