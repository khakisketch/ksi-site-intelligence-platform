"""Local-only restart stop: synthetic durable stores and real Core ASGI routes."""

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, Role
from ksi_core.domains.sites.sites import SiteStore
from ksi_core.domains.sites.work_areas import WorkAreaStore
from ksi_core.foundation.durable_journal import DurableJournal, JournalRecoveryError
from test_platform_core_assembly import _FRAME, _POLYGON, _assemble, _headers, _record
from test_site_bootstrap_and_work_area_grant_levels import _bootstrap_body, _install_mapped_v2

NOW = datetime(2026, 10, 29, tzinfo=UTC)
FRAME = {
    "crs": "EPSG:5186",
    "verticalDatum": "KNGeoid2018",
    "unit": "meter",
    "transformVersion": "1.0.0",
}
AREA = {"name": "Synthetic area", "polygon": _POLYGON, "crs": "EPSG:5186", "supersedes": None}


def close(opened: list[Any]) -> None:
    for journal in reversed(opened):
        journal.close()


def test_stop_allows_existing_aoi_and_archive_with_original_authorization(tmp_path: Path) -> None:
    site = f"site-{uuid4()}"
    writer, viewer, foreign = (str(uuid4()) for _ in range(3))
    registry = AuthRegistry(
        [
            _record(writer, "writer", "org-a", Role.FIELD_OPERATOR),
            _record(viewer, "viewer", "org-a", Role.VIEWER),
            _record(foreign, "foreign", "org-b", Role.ADMIN),
        ]
    )
    opened: list[Any] = []
    app = _assemble(tmp_path, [], opened, auth_registry=registry)
    try:
        with TestClient(app) as client:
            headers = _headers(writer)
            created = client.post(
                "/v1/sites",
                headers=headers,
                json={"siteId": site, "name": "Synthetic", "siteFrame": FRAME},
            )
            assert created.status_code == 201
            registered = client.post(f"/v1/sites/{site}/work-areas", headers=headers, json=AREA)
            assert registered.status_code == 201
            area_id = registered.json()["workArea"]["workAreaId"]
    finally:
        close(opened)

    opened = []
    app = _assemble(tmp_path, [], opened, auth_registry=registry, registration_stopped=True)
    try:
        with TestClient(app) as client:
            aoi_url = f"/v1/sites/{site}/aoi"
            archive_url = f"/v1/sites/{site}/work-areas/{area_id}/archive"
            aoi_body = {
                "siteFrame": FRAME,
                "aoi": {
                    "vertices": [
                        {"latDeg": 37.5, "lonDeg": 127.0},
                        {"latDeg": 37.5, "lonDeg": 127.001},
                        {"latDeg": 37.501, "lonDeg": 127.001},
                        {"latDeg": 37.501, "lonDeg": 127.0},
                    ]
                },
            }
            site_before = (tmp_path / "sites.jsonl").read_bytes()
            area_before = (tmp_path / "work-areas.jsonl").read_bytes()
            for token, expected in ((None, 401), (viewer, 403), (foreign, 404)):
                headers = _headers(token) if token else {}
                assert client.put(aoi_url, headers=headers, json=aoi_body).status_code == expected
                assert client.post(archive_url, headers=headers).status_code == expected
            assert (tmp_path / "sites.jsonl").read_bytes() == site_before
            assert (tmp_path / "work-areas.jsonl").read_bytes() == area_before

            headers = _headers(writer)
            changed = client.put(aoi_url, headers=headers, json=aoi_body)
            archived = client.post(archive_url, headers=headers)
            assert changed.status_code == 200 and changed.json()["verdict"] == "AOI_SET"
            assert archived.status_code == 200 and archived.json()["verdict"] == "ARCHIVED"
            read_site = client.get(f"/v1/sites/{site}", headers=headers)
            read_areas = client.get(
                f"/v1/sites/{site}/work-areas?include_archived=true", headers=headers
            )
            assert read_site.json()["aoi"] == aoi_body["aoi"]
            assert read_areas.json()["workAreas"][0]["status"] == "ARCHIVED"
            assert (tmp_path / "sites.jsonl").read_bytes().startswith(site_before)
            assert (tmp_path / "work-areas.jsonl").read_bytes().startswith(area_before)
            assert (tmp_path / "sites.jsonl").read_bytes() != site_before
            assert (tmp_path / "work-areas.jsonl").read_bytes() != area_before
    finally:
        close(opened)


def test_restart_stop_guards_direct_and_http_writes_and_replays(tmp_path: Path) -> None:
    opened: list[Any] = []
    first = _assemble(tmp_path, [], opened)
    key = str(uuid4())
    old = first.state.site_store.register_bootstrap(
        key,
        "Synthetic",
        _FRAME,
        organization_id="org-a",
        actor="operator-a",
        allowed_site_ids=None,
        now=NOW,
    )
    assert old.record is not None
    site = old.record.site_id
    direct = first.state.work_area_store.register(
        site,
        name="Original",
        polygon=_POLYGON,
        crs="EPSG:5186",
        supersedes=None,
        actor="operator-a",
        now=NOW,
    )
    assert direct.work_area is not None
    close(opened)

    opened = []
    app = _assemble(tmp_path, [], opened, registration_stopped=True)
    try:
        with TestClient(app) as client:
            site_before = (tmp_path / "sites.jsonl").read_bytes()
            area_before = (tmp_path / "work-areas.jsonl").read_bytes()
            headers = _headers()
            assert client.get(f"/v1/sites/{site}", headers=headers).status_code == 200
            assert client.get(f"/v1/sites/{site}/work-areas", headers=headers).status_code == 200
            assert (
                client.post(
                    "/v1/sites", json={"siteId": "new-site", "name": "New", "siteFrame": FRAME}
                ).status_code
                == 401
            )
            site_response = client.post(
                "/v1/sites",
                json={"siteId": "new-site", "name": "New", "siteFrame": FRAME},
                headers=headers,
            )
            area_response = client.post(f"/v1/sites/{site}/work-areas", json=AREA, headers=headers)
            replacement = client.post(
                f"/v1/sites/{site}/work-areas",
                json={**AREA, "supersedes": direct.work_area.work_area_id},
                headers=headers,
            )
            assert (
                site_response.status_code
                == area_response.status_code
                == replacement.status_code
                == 503
            )
            assert (
                site_response.json()["verdict"]
                == area_response.json()["verdict"]
                == "STORE_UNAVAILABLE"
            )
            assert (
                app.state.site_store.register(
                    "other-site", "Other", _FRAME, actor="direct", now=NOW
                ).verdict
                == "STORE_UNAVAILABLE"
            )
            assert (
                app.state.work_area_store.register(
                    site,
                    name="Direct",
                    polygon=_POLYGON,
                    crs="EPSG:5186",
                    supersedes=None,
                    actor="direct",
                    now=NOW,
                ).verdict
                == "STORE_UNAVAILABLE"
            )
            replay = app.state.site_store.register_bootstrap(
                key,
                "Synthetic",
                _FRAME,
                organization_id="org-a",
                actor="operator-a",
                allowed_site_ids=None,
                now=NOW,
            )
            assert replay.record is not None and replay.record.site_id == site
            fresh = app.state.site_store.register_bootstrap(
                str(uuid4()),
                "New",
                _FRAME,
                organization_id="org-a",
                actor="operator-a",
                allowed_site_ids=None,
                now=NOW,
            )
            assert fresh.verdict == "STORE_UNAVAILABLE"
            assert (tmp_path / "sites.jsonl").read_bytes() == site_before
            assert (tmp_path / "work-areas.jsonl").read_bytes() == area_before
    finally:
        close(opened)
    opened = []
    app = _assemble(tmp_path, [], opened)
    try:
        with TestClient(app) as client:
            assert (
                client.post(
                    f"/v1/sites/{site}/work-areas", json=AREA, headers=_headers()
                ).status_code
                == 201
            )
    finally:
        close(opened)


@pytest.mark.parametrize("value", [None, 0, 1, "false", "true"])
def test_ambiguous_stop_configuration_refused_before_journals(tmp_path: Path, value: Any) -> None:
    trace: list[str] = []
    opened: list[Any] = []
    with pytest.raises(ValueError, match="registration_stopped"):
        _assemble(tmp_path, trace, opened, registration_stopped=value)
    assert trace == []


@pytest.mark.parametrize("kind", ["site", "area"])
def test_old_writer_in_flight_must_finish_before_guarded_restart(
    tmp_path: Path, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "sites.jsonl"
    journal = DurableJournal(path)
    store: Any = SiteStore(journal) if kind == "site" else WorkAreaStore(journal)
    entered, release, close_started, close_finished = Event(), Event(), Event(), Event()
    append = journal._append_durable

    def paused(record: Mapping[str, Any]) -> None:
        entered.set()
        assert release.wait(10)
        append(record)

    monkeypatch.setattr(journal, "_append_durable", paused)

    def shutdown() -> None:
        close_started.set()
        journal.close()
        close_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        if kind == "site":
            pending = pool.submit(
                store.register, "old-site", "Old", _FRAME, actor="synthetic", now=NOW
            )
        else:
            pending = pool.submit(
                store.register,
                "old-site",
                name="Old",
                polygon=_POLYGON,
                crs="EPSG:5186",
                supersedes=None,
                actor="synthetic",
                now=NOW,
            )
        try:
            assert entered.wait(10)
            closing = pool.submit(shutdown)
            assert close_started.wait(10)
            assert not close_finished.wait(0.1)
            with pytest.raises(JournalRecoveryError):
                DurableJournal(path)
        finally:
            release.set()
        assert pending.result(timeout=10).verdict == "REGISTERED"
        closing.result(timeout=10)
    replacement_journal = DurableJournal(path)
    guarded: Any = (
        SiteStore(replacement_journal, registration_stopped=True)
        if kind == "site"
        else WorkAreaStore(replacement_journal, registration_stopped=True)
    )
    try:
        if kind == "site":
            assert guarded.get("old-site") is not None
            result = guarded.register("blocked-site", "Blocked", _FRAME, actor="synthetic", now=NOW)
        else:
            assert len(guarded.list_for_site("old-site")) == 1
            result = guarded.register(
                "old-site",
                name="Blocked",
                polygon=_POLYGON,
                crs="EPSG:5186",
                supersedes=None,
                actor="synthetic",
                now=NOW,
            )
        assert result.verdict == "STORE_UNAVAILABLE"
    finally:
        replacement_journal.close()


def test_http_bootstrap_replay_and_scope_under_stop(tmp_path: Path) -> None:
    opened: list[Any] = []
    app = _assemble(tmp_path, [], opened)
    token, _ = _install_mapped_v2(
        app, capabilities=["SITE_BOOTSTRAP"], site_ids=None, area_ids=None
    )
    body = _bootstrap_body()
    try:
        with TestClient(app) as client:
            created = client.post(
                "/v1/sites", headers={"Authorization": f"Bearer {token}"}, json=body
            )
            assert created.status_code == 201
            site = created.json()["site"]["siteId"]
    finally:
        close(opened)
    opened = []
    app = _assemble(tmp_path, [], opened, registration_stopped=True)
    try:
        with TestClient(app) as client:
            before = (tmp_path / "sites.jsonl").read_bytes()
            token, _ = _install_mapped_v2(
                app, capabilities=["SITE_BOOTSTRAP"], site_ids=None, area_ids=None
            )
            headers = {"Authorization": f"Bearer {token}"}
            replay = client.post("/v1/sites", headers=headers, json=body)
            assert replay.status_code == 201 and replay.json()["site"]["siteId"] == site
            fresh = client.post("/v1/sites", headers=headers, json=_bootstrap_body())
            assert fresh.status_code == 503 and fresh.json()["verdict"] == "STORE_UNAVAILABLE"
            token, _ = _install_mapped_v2(
                app, capabilities=["SITE_BOOTSTRAP"], site_ids=[], area_ids=[]
            )
            denied = client.post(
                "/v1/sites", headers={"Authorization": f"Bearer {token}"}, json=body
            )
            assert denied.status_code == 404 and denied.json().get("site") is None
            token, _ = _install_mapped_v2(app, capabilities=[], site_ids=None, area_ids=None)
            assert (
                client.post(
                    "/v1/sites", headers={"Authorization": f"Bearer {token}"}, json=body
                ).status_code
                == 403
            )
            assert (tmp_path / "sites.jsonl").read_bytes() == before
    finally:
        close(opened)
