"""Site briefings are readable without a copilot and scoped to the principal organization."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

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
from ksi_core.durable_journal import DurableJournal
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.site_workspace import SiteBriefingStore, SiteWorkspaceProjector, mount_site_workspace
from ksi_core.sites import SiteStore
from ksi_event_contracts.copilot import CopilotCitation, SiteBriefingStatus
from ksi_mission_contracts.models import SiteFrame

_NOW = datetime(2026, 9, 17, 9, 0, tzinfo=UTC)
_TOKEN_A = "token-org-a"
_TOKEN_B = "token-org-b"


def _principal(organization_id: str) -> Principal:
    return Principal(
        principal_id=f"viewer-{organization_id}",
        kind=PrincipalKind.OPERATOR,
        role=Role.VIEWER,
        device_id=None,
        organization_id=organization_id,
    )


def _record(store: SiteBriefingStore, organization_id: str, site_id: str, when: datetime) -> None:
    store.record(
        organization_id=organization_id,
        site_id=site_id,
        status=SiteBriefingStatus.READY,
        what_changed=f"{site_id} 변화",
        why_it_matters="중요",
        decision_prompt="검토하세요.",
        citations=[
            CopilotCitation(
                citation_id="c-1",
                object_type="external-relative-volume-report",
                object_id="report-1",
                label="보고서",
                source_path="/v1/external-relative-volume-reports/report-1",
            )
        ],
        uncertainty="±1 m³",
        source_watermark=f"external-report:sha256:{site_id}:REPORTED",
        missing_data=[],
        actor="test",
        now=when,
    )


def _app(tmp_path: Path) -> TestClient:
    sites = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    seeds = (("org-a", "site-a1"), ("org-a", "site-a2"), ("org-b", "site-b1"))
    for organization_id, site_id in seeds:
        sites.register(
            site_id,
            f"Site {site_id}",
            SiteFrame(
                crs="EPSG:5186", vertical_datum="LOCAL", unit="meter", transform_version="v1"
            ),
            organization_id=organization_id,
            actor="test",
            now=_NOW,
        )
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            sites.get_scoped(site_id, organization_id) is not None
        ),
    )
    projector = SiteWorkspaceProjector(
        site_store=sites, work_order_store=work_orders, processing_job_store=None, event_store=None
    )
    briefings = SiteBriefingStore(
        DurableJournal(tmp_path / "site-briefings.jsonl"), site_store=sites
    )
    _record(briefings, "org-a", "site-a1", _NOW)
    _record(briefings, "org-a", "site-a2", _NOW.replace(hour=10))
    _record(briefings, "org-b", "site-b1", _NOW.replace(hour=11))
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(_TOKEN_A.encode()).hexdigest(),
                    principal=_principal("org-a"),
                ),
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(_TOKEN_B.encode()).hexdigest(),
                    principal=_principal("org-b"),
                ),
            ]
        ),
    )
    mount_site_workspace(app, projector=projector, briefing_service=None, briefing_store=briefings)
    return TestClient(app)


def test_latest_briefings_are_readable_without_copilot_and_organization_scoped(
    tmp_path: Path,
) -> None:
    client = _app(tmp_path)
    headers = {"Authorization": f"Bearer {_TOKEN_A}"}
    assert client.get("/v1/site-briefings/latest").status_code == 401
    listed = client.get("/v1/site-briefings/latest", headers=headers)
    assert listed.status_code == 200
    assert [item["siteId"] for item in listed.json()["items"]] == ["site-a2", "site-a1"]
    limited = client.get("/v1/site-briefings/latest?limit=1", headers=headers)
    assert [item["siteId"] for item in limited.json()["items"]] == ["site-a2"]
    single = client.get("/v1/sites/site-a1/briefings/latest", headers=headers)
    assert single.status_code == 200 and single.json()["whatChanged"] == "site-a1 변화"
    assert client.get("/v1/sites/site-b1/briefings/latest", headers=headers).status_code == 404
    assert client.post("/v1/sites/site-a1/briefings/refresh", headers=headers).status_code == 404
    other = client.get("/v1/site-briefings/latest", headers={"Authorization": f"Bearer {_TOKEN_B}"})
    assert [item["siteId"] for item in other.json()["items"]] == ["site-b1"]
