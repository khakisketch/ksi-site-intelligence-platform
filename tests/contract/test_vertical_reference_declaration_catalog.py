"""수직 기준 선언 — 실제 자료 카탈로그·등록 저장소·조직 격리 위에서 선언한다.

가짜 자료 포트가 아니라 실제 ``SpatialAssetCatalog`` 를 쓴다. 파일 검사 결과만 합성 대역이다.
이 시험은 연결의 증거이지 측량 정확도·고객 수락의 증거가 아니다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.domains.external.ingress.external_artifact_inspections import (
    ExternalArtifactInspectionStore,
)
from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog
from ksi_core.domains.external.ingress.vertical_reference_declarations import (
    CatalogDeclarationAssetPort,
    VerticalReferenceDeclarationStore,
    mount_vertical_reference_declarations,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import ObjectStorageObservation
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_event_contracts.external_artifact_validation import ArtifactOutcome
from ksi_event_contracts.external_reconstruction import (
    ExternalReconstructionSubmissionV1,
    ExternalReconstructionSubmissionV2,
)
from test_spatial_asset_catalog import (
    _CONTENT,
    _NOW,
    _setup,
    _Storage,
    order_epoch,
)

TOKENS = {
    "operator": ("tok-op", "org-a", Role.ADMIN),
    "viewer": ("tok-viewer", "org-a", Role.VIEWER),
    "other": ("tok-other", "org-b", Role.ADMIN),
}


class _Inspections(ExternalArtifactInspectionStore):
    """파일 검사 결과 대역: DSM 한 개를 측정됨으로 보고하고 수직 기준 유무를 고른다."""

    def __init__(self) -> None:
        self.mode = "measured_without_vertical"
        self.artifact_id = "dsm"

    def public_snapshot_bounded(self, subject: Any, **_: Any) -> Any:
        del subject
        if self.mode == "pending":
            return SimpleNamespace(state="INSPECTION_PENDING", report=None)
        vertical = (
            SimpleNamespace(identifier="EPSG:5703", basis="NAVD88 height")
            if self.mode == "measured_with_vertical"
            else None
        )
        measurements = SimpleNamespace(
            observed_crs_identifier="EPSG:5186",
            observed_crs_wkt=None,
            observed_crs_digest="sha256:" + "1" * 64,
            observed_vertical_reference=vertical,
            transform=(0.5, 0.0, 100.0, 0.0, -0.5, 200.0),
            footprint_wkt="POLYGON ((100 200, 110 200, 110 210, 100 210, 100 200))",
            footprint_digest="sha256:" + "2" * 64,
            width=20,
            height=20,
        )
        outcome = SimpleNamespace(
            artifact_id="dsm",
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


def _dsm_submission(
    order: Any, kind: str = "dsm"
) -> ExternalReconstructionSubmissionV1 | ExternalReconstructionSubmissionV2:
    raw = {
        "submissionId": "submission-dsm",
        "revision": 1,
        "organizationId": order.organization_id,
        "siteId": order.site_id,
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
                "artifactId": kind,
                "kind": kind,
                "fileName": "dsm.tif",
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
    # 한 제출에 DSM 이 필요한 V2 와 정사영상이 필요한 V1 중 종류에 맞는 계약을 쓴다.
    contract = (
        ExternalReconstructionSubmissionV2 if kind == "dsm" else ExternalReconstructionSubmissionV1
    )
    raw["submissionDigest"] = contract.digest_for_wire(raw)
    return contract.model_validate(raw)


def _seal(order: Any, storage: _Storage, reconstruction: Any, kind: str = "dsm") -> None:
    submission = _dsm_submission(order, kind)
    assert reconstruction.register(
        submission, work_order=order, registered_by="catalog-owner", now=_NOW
    ).revision
    grant = reconstruction.upload_grants(
        order.work_order_id,
        submission.submission_id,
        1,
        organization_id=order.organization_id,
        site_id=order.site_id,
        storage=storage,
    )
    key = grant.grants[0].object_key
    storage.bytes[key] = _CONTENT
    storage.objects[key] = ObjectStorageObservation(
        object_key=key,
        exists=True,
        size_bytes=len(_CONTENT),
        sha256="sha256:" + hashlib.sha256(_CONTENT).hexdigest(),
        content_type="application/octet-stream",
    )
    assert reconstruction.seal(
        order.work_order_id,
        submission.submission_id,
        1,
        organization_id=order.organization_id,
        site_id=order.site_id,
        storage=storage,
        now=_NOW,
    ).revision


class Env:
    def __init__(self, tmp_path: Path, kind: str = "dsm") -> None:
        (_, order, storage, reconstruction, area_a, _b, work_orders, sites, areas) = _setup(
            tmp_path
        )
        _seal(order, storage, reconstruction, kind)
        self.order, self.area = order, area_a
        self.inspections = _Inspections()
        self.inspections.artifact_id = kind
        self.catalog = SpatialAssetCatalog(
            reconstruction=reconstruction,
            work_orders=work_orders,
            sites=sites,
            work_areas=areas,
            inspections=self.inspections,
        )
        self.store = VerticalReferenceDeclarationStore(
            DurableJournal(tmp_path / "declarations.jsonl"),
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )
        self.asset_ref = self._asset_ref()
        self.base = (
            f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}"
            f"/spatial-assets/{self.asset_ref}/vertical-reference"
        )
        app = FastAPI()
        records = [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(),
                principal=Principal(
                    principal_id=name,
                    kind=PrincipalKind.OPERATOR,
                    role=role,
                    device_id=None,
                    organization_id=org,
                ),
            )
            for name, (token, org, role) in TOKENS.items()
        ]
        mount_auth(app, AuthRegistry(records))
        mount_vertical_reference_declarations(
            app, self.store, CatalogDeclarationAssetPort(self.catalog), clock=lambda: _NOW
        )
        self.client = TestClient(app)

    def _asset_ref(self) -> str:
        principal = Principal(
            principal_id="operator",
            kind=PrincipalKind.OPERATOR,
            role=Role.ADMIN,
            device_id=None,
            organization_id="org-a",
        )
        items = self.catalog.items(self.order.site_id, self.area.work_area_id, principal)
        assert len(items) == 1
        return items[0].asset_ref

    def headers(self, name: str = "operator", key: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {TOKENS[name][0]}"}
        if key:
            headers["Idempotency-Key"] = key
        return headers


BODY = {
    "datum": "orthometric_kngeoid2018",
    "unit": "metre",
    "basis": "Terra에서 정표고(KNGeoid18)로 내보냄",
    "expectedSequence": 0,
}


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def test_a_measured_dsm_without_a_vertical_reference_can_be_declared(env: Env) -> None:
    state = env.client.get(env.base, headers=env.headers("viewer")).json()
    assert state == {"assetRef": env.asset_ref, "observed": False, "current": None, "history": []}
    created = env.client.post(env.base + "/declarations", json=BODY, headers=env.headers(key="k1"))
    assert created.status_code == 201, created.text
    record = created.json()["declaration"]
    assert record["assetRef"] == env.asset_ref and record["status"] == "ACTIVE"
    assert record["siteId"] == env.order.site_id
    assert record["workAreaId"] == env.area.work_area_id
    current = env.store.current(
        organization_id="org-a", site_id=env.order.site_id, asset_ref=env.asset_ref
    )
    assert current is not None and current.declaration_id == record["declarationId"]


def test_a_file_that_already_carries_a_vertical_reference_takes_none(env: Env) -> None:
    env.inspections.mode = "measured_with_vertical"
    assert env.client.get(env.base, headers=env.headers("viewer")).json()["observed"] is True
    refused = env.client.post(env.base + "/declarations", json=BODY, headers=env.headers(key="k1"))
    assert refused.status_code == 409 and refused.json()["verdict"] == "OBSERVED_REFERENCE_PRESENT"


def test_an_uninspected_asset_cannot_be_declared(env: Env) -> None:
    env.inspections.mode = "pending"
    refused = env.client.post(env.base + "/declarations", json=BODY, headers=env.headers(key="k1"))
    assert refused.status_code == 409 and refused.json()["verdict"] == "NOT_MEASURED"


def test_a_non_dsm_asset_cannot_be_declared(tmp_path: Path) -> None:
    env = Env(tmp_path, kind="ortho")
    refused = env.client.post(env.base + "/declarations", json=BODY, headers=env.headers(key="k1"))
    assert refused.status_code == 409 and refused.json()["verdict"] == "NOT_A_DSM"


def test_another_organization_and_a_made_up_reference_see_a_plain_404(env: Env) -> None:
    other = env.client.post(
        env.base + "/declarations", json=BODY, headers=env.headers("other", "k1")
    )
    assert other.status_code == 404
    assert env.client.get(env.base, headers=env.headers("other")).status_code == 404
    unknown = env.base.replace(env.asset_ref, "ksa-v1-" + "c" * 64)
    assert env.client.get(unknown, headers=env.headers()).status_code == 404
    assert (
        env.client.post(
            unknown + "/declarations", json=BODY, headers=env.headers(key="k1")
        ).status_code
        == 404
    )
    malformed = env.base.replace(env.asset_ref, "not-an-asset")
    assert env.client.get(malformed, headers=env.headers()).status_code == 404
    wrong_area = env.base.replace(env.area.work_area_id, "wa-other")
    assert env.client.get(wrong_area, headers=env.headers()).status_code == 404
    assert (
        env.store.history(
            organization_id="org-a", site_id=env.order.site_id, asset_ref=env.asset_ref
        )
        == ()
    )


def test_a_viewer_can_read_but_not_declare(env: Env) -> None:
    assert env.client.get(env.base, headers=env.headers("viewer")).status_code == 200
    denied = env.client.post(
        env.base + "/declarations", json=BODY, headers=env.headers("viewer", "k1")
    )
    assert denied.status_code == 403


def test_the_asset_reference_a_decision_derives_is_the_one_the_catalog_serves(env: Env) -> None:
    """판정은 봉인 대상(subject)에서 자료 참조를 만든다. 카탈로그가 내 주는 참조와 같아야 선언이 닿는다."""
    from ksi_core.domains.external.ingress.spatial_asset_catalog import asset_ref_for_subject

    subject = SimpleNamespace(
        organization_id="org-a",
        site_id=env.order.site_id,
        work_order_id=env.order.work_order_id,
        submission_id="submission-dsm",
        revision=1,
    )
    assert asset_ref_for_subject(subject, "dsm") == env.asset_ref
    assert asset_ref_for_subject(subject, "other") != env.asset_ref
    assert asset_ref_for_subject(SimpleNamespace(**{**vars(subject), "revision": 2}), "dsm") != (
        env.asset_ref
    )
    assert (
        asset_ref_for_subject(
            SimpleNamespace(**{**vars(subject), "organization_id": "org-b"}), "dsm"
        )
        != env.asset_ref
    )
