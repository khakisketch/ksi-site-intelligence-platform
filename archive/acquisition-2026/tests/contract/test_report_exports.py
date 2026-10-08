"""Browser report-export audit contracts.

The browser retains PDF/CSV bytes. These tests exercise the narrower Core
claim: a durable, organization-scoped record of the exact Core report snapshot
the browser requested to export.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.coverage_reports import (
    CoverageReportVerdict,
    RecordedCoverageReport,
    RejectedCoverageReport,
)
from ksi_core.design_conformance_reports import DesignConformanceStore, RecordedDesignConformance
from ksi_core.design_conformance_requests import DesignConformanceRequestStore
from ksi_core.design_surfaces import DesignSurfaceStore
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionStore
from ksi_core.processing_jobs import ProcessingJobStore
from ksi_core.report_exports import (
    ReportExportCreateRequest,
    ReportExportRecoveryError,
    ReportExportStore,
    ReportExportVerdict,
)
from ksi_core.sites import SiteStore
from ksi_core.source_media import SourceMediaStore
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import current_comparison_policy
from ksi_event_contracts.coverage_report import (
    CompletionState,
    CoverageCell,
    CoverageCellState,
    CoverageReport,
    CoverageSummary,
)
from ksi_event_contracts.design_conformance_report import (
    DesignConformanceReport,
    DesignSurfaceRef,
    DiffRasterRef,
)
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from ksi_event_contracts.volume_change_report import ZoneVolumeDelta
from ksi_mission_contracts.models import SiteFrame
from ksi_mission_contracts.signing import canonical_payload_bytes, sha256_digest

_NOW = datetime(2026, 8, 30, 4, 0, tzinfo=UTC)
_ADMIN_TOKEN = "report-export-admin"  # noqa: S105 -- test fixture
_OTHER_ADMIN_TOKEN = "report-export-other"  # noqa: S105 -- test fixture
_FRAME = SiteFrame(
    crs="EPSG:5186",
    vertical_datum="KNGeoid2018",
    unit="meter",
    transform_version="1.0.0",
)
_DIGEST = "a" * 64
_PREFIXED_DIGEST = f"sha256:{_DIGEST}"


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_token_digest(_ADMIN_TOKEN),
                # OIDC-compatible actor: valid UTF-8 but deliberately not a
                # path-safe identifier. Audit must accept it.
                principal=Principal(
                    principal_id="alice@example.com",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                    organization_id="org-1",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_token_digest(_OTHER_ADMIN_TOKEN),
                principal=Principal(
                    principal_id="다른-운영자@example.com",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                    organization_id="org-2",
                ),
            ),
        ]
    )


class _Storage:
    """Only satisfies the actual design-conformance store's assembly contract."""

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        del content_type, ttl
        return f"https://test.invalid/{object_key}"

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        del ttl
        return f"https://test.invalid/{object_key}"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        del object_key, data, content_type

    def get_bytes(self, object_key: str) -> bytes:
        del object_key
        return b""

    def delete(self, object_key: str) -> None:
        del object_key


@dataclass(frozen=True, slots=True)
class _Catalog:
    requests: dict[str, Any]
    entries: dict[str, RecordedDesignConformance]

    def request_of(self, design_conformance_id: str) -> Any | None:
        return self.requests.get(design_conformance_id)

    def get(self, mission_id: str, design_conformance_id: str) -> RecordedDesignConformance | None:
        request = self.requests.get(design_conformance_id)
        if request is None or request.mission_id != mission_id:
            return None
        return self.entries.get(design_conformance_id)


@dataclass
class _CoverageCatalog:
    records: dict[str, list[RecordedCoverageReport]]
    rejected: dict[str, list[RejectedCoverageReport]]
    planned_ratios: dict[str, float | None]

    def recorded_history(self, mission_id: str) -> list[RecordedCoverageReport]:
        return list(self.records.get(mission_id, ()))

    def rejections(self, mission_id: str) -> list[RejectedCoverageReport]:
        return list(self.rejected.get(mission_id, ()))

    def mission_planned_general_ratio(self, mission_id: str) -> float | None:
        return self.planned_ratios.get(mission_id)


def _coverage_catalog(mission_id: str = "mission-dcf-latest") -> _CoverageCatalog:
    report = CoverageReport(
        mission_id=mission_id,
        site_id="site-1",
        timestamp=_NOW + timedelta(days=7),
        cells=[
            CoverageCell(cell_id="cell-1", state=CoverageCellState.OBSERVED_HIGH_CONFIDENCE),
            CoverageCell(cell_id="cell-2", state=CoverageCellState.OBSERVED_PARTIAL),
        ],
        summary=CoverageSummary(
            mandatory_hazard_ratio=1.0,
            mandatory_asset_ratio=1.0,
            accessible_general_ratio=0.96,
            completion_state=CompletionState.COMPLETED,
        ),
    )
    return _CoverageCatalog(
        records={
            mission_id: [RecordedCoverageReport(report=report, reported_by="edge-device-1")]
        },
        rejected={
            mission_id: [
                RejectedCoverageReport(
                    mission_id=mission_id,
                    site_id="site-1",
                    verdict=CoverageReportVerdict.UNSUPPORTED_COMPLETION,
                    detail="COMPLETED 주장의 비율이 임계 미만이다",
                    reported_by="edge-device-1",
                    rejected_at=_NOW + timedelta(days=6),
                )
            ]
        },
        planned_ratios={mission_id: 0.98},
    )


def _vertical() -> VerticalReference:
    return VerticalReference(
        datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
        basis="테스트 DSM과 설계면의 공통 기준",
        source=VerticalReferenceSource.PIPELINE_DECLARED,
    )


def _report(
    *, report_id: str, job_id: str, cut_m3: float, computed_at: datetime
) -> DesignConformanceReport:
    policy = current_comparison_policy()
    vertical = _vertical()
    return DesignConformanceReport(
        design_conformance_id=report_id,
        design_surface_ref=DesignSurfaceRef(design_surface_id="surface-1", sha256=_DIGEST),
        current=ArtifactRef(job_id=job_id, artifact_id=f"dsm-{job_id}"),
        crs="EPSG:5186",
        vertical_reference=vertical,
        zones=[
            ZoneVolumeDelta(
                zone_id="zone-1",
                cut_m3=cut_m3,
                fill_m3=1200.0,
                net_m3=1200.0 - cut_m3,
                area_m2=400.0,
                threshold_m=policy.volume_threshold_m,
                uncertainty_m3=None,
                uncertainty_note="설계면은 측정물이 아니라 checkpoint RMSE가 없다",
            )
        ],
        policy=policy,
        diff_raster=DiffRasterRef(
            diff_raster_id=f"raster-{report_id}",
            digest=_PREFIXED_DIGEST,
            crs="EPSG:5186",
            vertical_reference=vertical,
            width=20,
            height=20,
            pixel_size_x_m=1.0,
            pixel_size_y_m=1.0,
            transform=(1.0, 0.0, 200000.0, 0.0, -1.0, 550000.0),
            threshold_m=policy.volume_threshold_m,
            size_bytes=100,
            core_verified_digest_at=computed_at,
        ),
        computed_at=computed_at,
    )


def _catalog(
    *,
    latest_profile: str = _PREFIXED_DIGEST,
    site_id: str = "site-1",
    report_suffix: str = "",
) -> _Catalog:
    baseline = _report(
        report_id=f"dcf-baseline{report_suffix}",
        job_id=f"job-baseline{report_suffix}",
        cut_m3=1000.0,
        computed_at=_NOW,
    )
    latest = _report(
        report_id=f"dcf-latest{report_suffix}",
        job_id=f"job-latest{report_suffix}",
        cut_m3=800.0,
        computed_at=_NOW + timedelta(days=7),
    )

    def request(report: DesignConformanceReport, *, profile: str) -> Any:
        return SimpleNamespace(
            request_id=f"request-{report.design_conformance_id}",
            mission_id=f"mission-{report.design_conformance_id}",
            site_id=site_id,
            design_surface_id="surface-1",
            design_surface_sha256=_DIGEST,
            design_surface_revision="Rev.A",
            design_normalization_profile="ksi-tin-raster-0.5m-v1",
            design_normalization_digest="b" * 64,
            processing_profile_digest=profile,
            source_bundle_digest=f"sha256:{'c' * 64}",
        )

    return _Catalog(
        requests={
            baseline.design_conformance_id: request(baseline, profile=_PREFIXED_DIGEST),
            latest.design_conformance_id: request(latest, profile=latest_profile),
        },
        entries={
            baseline.design_conformance_id: RecordedDesignConformance(
                report=baseline,
                reported_by="worker-1",
                recorded_at=_NOW,
                core_recomputed_digest=_PREFIXED_DIGEST,
            ),
            latest.design_conformance_id: RecordedDesignConformance(
                report=latest,
                reported_by="worker-1",
                recorded_at=_NOW + timedelta(days=7),
                core_recomputed_digest=_PREFIXED_DIGEST,
            ),
        },
    )


@dataclass
class _Fixture:
    client: TestClient
    store: ReportExportStore
    catalog: _Catalog
    coverage: _CoverageCatalog
    journals: list[DurableJournal]

    def close(self) -> None:
        self.client.close()
        for journal in reversed(self.journals):
            journal.close()


@pytest.fixture
def fixture(tmp_path: Path) -> Iterator[_Fixture]:
    journals: list[DurableJournal] = []

    def open_journal(name: str) -> DurableJournal:
        journal = DurableJournal(tmp_path / name)
        journals.append(journal)
        return journal

    sites = SiteStore(open_journal("sites.jsonl"))
    assert sites.register(
        "site-1", "Site 1", _FRAME, organization_id="org-1", actor="fixture", now=_NOW
    ).record is not None
    assert sites.register(
        "site-2", "Site 2", _FRAME, organization_id="org-2", actor="fixture", now=_NOW
    ).record is not None
    assert sites.register(
        "site-3", "Site 3", _FRAME, organization_id="org-1", actor="fixture", now=_NOW
    ).record is not None
    missions = MissionStore(open_journal("missions.jsonl"))
    source_media = SourceMediaStore(open_journal("source-media.jsonl"), mission_store=missions)
    processing = ProcessingJobStore(
        open_journal("processing-jobs.jsonl"), source_media_store=source_media, site_store=sites
    )
    surfaces = DesignSurfaceStore(open_journal("surfaces.jsonl"), site_store=sites)
    request_store = DesignConformanceRequestStore(
        open_journal("design-conformance-requests.jsonl"),
        mission_store=missions,
        processing_job_store=processing,
        design_surface_store=surfaces,
    )
    storage = _Storage()
    report_store = DesignConformanceStore(
        open_journal("design-conformance.jsonl"),
        mission_store=missions,
        processing_job_store=processing,
        request_store=request_store,
        storage=storage,
    )
    catalog = _catalog()
    coverage = _coverage_catalog()
    export_store = ReportExportStore(
        open_journal("report-exports.jsonl"),
        site_store=sites,
        design_conformance_store=catalog,
        coverage_report_store=coverage,
    )
    app = create_app(
        auth_registry=_registry(),
        site_store=sites,
        mission_store=missions,
        evidence_storage=storage,
        source_media_store=source_media,
        processing_job_store=processing,
        design_surface_store=surfaces,
        design_conformance_request_store=request_store,
        design_conformance_report_store=report_store,
        report_export_store=export_store,
    )
    value = _Fixture(TestClient(app), export_store, catalog, coverage, journals)
    try:
        yield value
    finally:
        value.close()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "exportId": "export-001",
        "exportFormat": "PDF",
        "baselineDesignConformanceId": "dcf-baseline",
        "latestDesignConformanceId": "dcf-latest",
    }
    payload.update(overrides)
    return payload


_HOSTILE_JSON_BODIES: list[tuple[str, str]] = [
    ("NaN", '{"x": NaN}'),
    ("Infinity", '{"x": Infinity}'),
    ("-Infinity", '{"x": -Infinity}'),
    ("overflow literal", '{"x": 1e400}'),
    ("lone surrogate", '{"x": "a\\ud800b"}'),
    ("nested lone surrogate", '{"x": {"y": ["a\\udfffb"]}}'),
]


@pytest.mark.parametrize(
    ("label", "raw"), _HOSTILE_JSON_BODIES, ids=[case[0] for case in _HOSTILE_JSON_BODIES]
)
def test_report_export_hostile_bodies_are_machine_readable_422(
    fixture: _Fixture, label: str, raw: str
) -> None:
    """The newly mounted POST route rejects all validation-hostile JSON as JSON 422.

    This is intentionally direct rather than relying on the cross-route gate:
    a missing report-export router must not turn an apparently-green hostile-input
    test into a 404.
    """
    response = fixture.client.post(
        "/v1/sites/site-1/report-exports",
        content=raw.encode("utf-8", "surrogatepass"),
        headers={**_headers(_ADMIN_TOKEN), "Content-Type": "application/json"},
    )
    assert response.status_code == 422, f"{label}: {response.status_code} {response.text[:200]}"
    assert response.headers["content-type"].startswith("application/json")
    json.loads(response.text)


def test_export_audit_is_core_derived_idempotent_and_never_claims_file_bytes(
    fixture: _Fixture,
) -> None:
    path = "/v1/sites/site-1/report-exports"
    first = fixture.client.post(path, json=_payload(), headers=_headers(_ADMIN_TOKEN))
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["verdict"] == "RECORDED"
    assert body["contentProducedByServer"] is False
    assert body["snapshotDigest"].startswith("sha256:")
    assert body["snapshot"]["schemaVersion"] == "1.1"
    assert body["snapshot"]["coverage"]["availability"] == "REPORTED"
    assert body["snapshot"]["coverage"]["reportCount"] == 1
    assert body["snapshot"]["coverage"]["rejectionCount"] == 1

    # A network retry with the same immutable export identity does not write a
    # second audit fact.
    again = fixture.client.post(path, json=_payload(), headers=_headers(_ADMIN_TOKEN))
    assert again.status_code == 200, again.text
    assert again.json()["verdict"] == "ALREADY_RECORDED"

    listed = fixture.client.get(path, headers=_headers(_ADMIN_TOKEN))
    assert listed.status_code == 200, listed.text
    exports = listed.json()["exports"]
    assert len(exports) == 1
    assert exports[0]["actor"] == "alice@example.com"
    assert exports[0]["contentProducedByServer"] is False
    assert exports[0]["snapshot"]["baseline"]["reportDigest"].startswith("sha256:")
    assert exports[0]["snapshot"]["latest"]["processingProfileDigest"] == _PREFIXED_DIGEST
    assert exports[0]["snapshot"]["coverage"]["reportedBy"] == "edge-device-1"
    assert "organizationId" not in exports[0]


def test_export_audit_rejects_body_org_and_hides_cross_organization_records(
    fixture: _Fixture,
) -> None:
    path = "/v1/sites/site-1/report-exports"
    # The API has no organizationId input at all; extra values fail before a
    # journal append and cannot move a record across principal scope.
    invalid = fixture.client.post(
        path,
        json=_payload(organizationId="org-2"),
        headers=_headers(_ADMIN_TOKEN),
    )
    assert invalid.status_code == 422
    recorded = fixture.client.post(path, json=_payload(), headers=_headers(_ADMIN_TOKEN))
    assert recorded.status_code == 201

    hidden = fixture.client.get(path, headers=_headers(_OTHER_ADMIN_TOKEN))
    assert hidden.status_code == 404
    # An existing foreign site does not allow a foreign report ID to become an
    # audit event either.
    foreign = fixture.client.post(
        "/v1/sites/site-2/report-exports",
        json=_payload(exportId="export-foreign"),
        headers=_headers(_OTHER_ADMIN_TOKEN),
    )
    assert foreign.status_code == 404
    assert fixture.store.history(organization_id="org-2", site_id="site-2") == []


def test_export_idempotency_key_is_scoped_to_the_site_endpoint(fixture: _Fixture) -> None:
    """One organization may use the same client action ID at two different sites."""
    other = _catalog(site_id="site-3", report_suffix="-site-3")
    fixture.catalog.requests.update(other.requests)
    fixture.catalog.entries.update(other.entries)

    first = fixture.client.post(
        "/v1/sites/site-1/report-exports",
        json=_payload(exportId="shared-action-id"),
        headers=_headers(_ADMIN_TOKEN),
    )
    second = fixture.client.post(
        "/v1/sites/site-3/report-exports",
        json=_payload(
            exportId="shared-action-id",
            baselineDesignConformanceId="dcf-baseline-site-3",
            latestDesignConformanceId="dcf-latest-site-3",
        ),
        headers=_headers(_ADMIN_TOKEN),
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert len(fixture.store.history(organization_id="org-1", site_id="site-1")) == 1
    assert len(fixture.store.history(organization_id="org-1", site_id="site-3")) == 1


def test_export_audit_fails_closed_when_report_anchors_are_not_comparable(tmp_path: Path) -> None:
    sites_journal = DurableJournal(tmp_path / "sites.jsonl")
    sites = SiteStore(sites_journal)
    assert sites.register(
        "site-1", "Site 1", _FRAME, organization_id="org-1", actor="fixture", now=_NOW
    ).record is not None
    export_journal = DurableJournal(tmp_path / "exports.jsonl")
    store = ReportExportStore(
        export_journal,
        site_store=sites,
        design_conformance_store=_catalog(latest_profile=f"sha256:{'d' * 64}"),
        coverage_report_store=_coverage_catalog(),
    )
    try:
        result = store.record(
            ReportExportCreateRequest.model_validate(_payload()),
            organization_id="org-1",
            site_id="site-1",
            actor="alice@example.com",
            now=_NOW,
        )
        assert result.verdict is ReportExportVerdict.SNAPSHOT_NOT_COMPARABLE
        assert store.history(organization_id="org-1", site_id="site-1") == []
    finally:
        export_journal.close()
        sites_journal.close()


def test_replay_revalidates_the_complete_server_snapshot(tmp_path: Path) -> None:
    sites_journal = DurableJournal(tmp_path / "sites.jsonl")
    sites = SiteStore(sites_journal)
    assert sites.register(
        "site-1", "Site 1", _FRAME, organization_id="org-1", actor="fixture", now=_NOW
    ).record is not None
    catalog = _catalog()
    coverage = _coverage_catalog()
    export_path = tmp_path / "exports.jsonl"
    writer_journal = DurableJournal(export_path)
    writer = ReportExportStore(
        writer_journal,
        site_store=sites,
        design_conformance_store=catalog,
        coverage_report_store=coverage,
    )
    request = ReportExportCreateRequest.model_validate(_payload())
    assert writer.record(
        request,
        organization_id="org-1",
        site_id="site-1",
        actor="alice@example.com",
        now=_NOW,
    ).verdict is ReportExportVerdict.RECORDED

    # Same mission may receive a later partial/final report or another rejected
    # claim. That append-only suffix must not invalidate the earlier export.
    mission_id = "mission-dcf-latest"
    coverage.records[mission_id].append(coverage.records[mission_id][0])
    coverage.rejected[mission_id].append(coverage.rejected[mission_id][0])
    assert writer.record(
        request,
        organization_id="org-1",
        site_id="site-1",
        actor="alice@example.com",
        now=_NOW,
    ).verdict is ReportExportVerdict.ALREADY_RECORDED
    writer_journal.close()

    revived = ReportExportStore(
        DurableJournal(export_path),
        site_store=sites,
        design_conformance_store=catalog,
        coverage_report_store=coverage,
    )
    try:
        rows = revived.history(organization_id="org-1", site_id="site-1")
        assert len(rows) == 1
        assert rows[0].snapshot.baseline.report_digest.startswith("sha256:")
        assert rows[0].snapshot.coverage is not None
        assert rows[0].snapshot.coverage.report_count == 1
        assert rows[0].snapshot.coverage.rejection_count == 1
    finally:
        revived._journal.close()  # noqa: SLF001 -- this test owns the journal instance

    raw = json.loads(export_path.read_text(encoding="utf-8"))
    raw["snapshot"]["latest"]["reportDigest"] = f"sha256:{'e' * 64}"
    export_path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    with pytest.raises(ReportExportRecoveryError, match="snapshot 또는 digest"):
        ReportExportStore(
            DurableJournal(export_path),
            site_store=sites,
            design_conformance_store=catalog,
            coverage_report_store=coverage,
        )
    sites_journal.close()


def test_replay_preserves_pre_coverage_schema_v1_snapshot(tmp_path: Path) -> None:
    sites_journal = DurableJournal(tmp_path / "sites.jsonl")
    sites = SiteStore(sites_journal)
    assert sites.register(
        "site-1", "Site 1", _FRAME, organization_id="org-1", actor="fixture", now=_NOW
    ).record is not None
    catalog = _catalog()
    coverage = _coverage_catalog()
    export_path = tmp_path / "exports.jsonl"
    journal = DurableJournal(export_path)
    writer = ReportExportStore(
        journal,
        site_store=sites,
        design_conformance_store=catalog,
        coverage_report_store=coverage,
    )
    assert writer.record(
        ReportExportCreateRequest.model_validate(_payload()),
        organization_id="org-1",
        site_id="site-1",
        actor="alice@example.com",
        now=_NOW,
    ).verdict is ReportExportVerdict.RECORDED
    journal.close()

    raw = json.loads(export_path.read_text(encoding="utf-8"))
    raw["snapshot"]["schemaVersion"] = "1.0"
    raw["snapshot"].pop("coverage")
    raw["snapshotDigest"] = sha256_digest(canonical_payload_bytes(raw["snapshot"]))
    export_path.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    revived = ReportExportStore(
        DurableJournal(export_path),
        site_store=sites,
        design_conformance_store=catalog,
        coverage_report_store=coverage,
    )
    try:
        record = revived.history(organization_id="org-1", site_id="site-1")[0]
        assert record.snapshot.schema_version == "1.0"
        assert record.snapshot.coverage is None
    finally:
        revived._journal.close()  # noqa: SLF001 -- test owns journal
        sites_journal.close()
