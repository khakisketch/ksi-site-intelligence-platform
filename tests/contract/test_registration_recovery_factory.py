"""Factory startup configuration, exercised with generated local data only."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from ksi_core.durable_journal import DurableJournal
from test_platform_core_assembly import _Storage
from test_platform_core_production import _apply_env, _platform_env
from test_registration_recovery_stop import AREA, FRAME, close
from test_site_bootstrap_and_work_area_grant_levels import _bootstrap_body, _install_mapped_v2

SETTING = "KSI_CORE_REGISTRATION_STOPPED"


@pytest.fixture
def local_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Any, list[Any]]]:
    import ksi_core.evidence_s3 as evidence_s3
    from ksi_core.composition import platform_production

    for name in tuple(os.environ):
        if name.startswith("KSI_CORE_"):
            monkeypatch.delenv(name, raising=False)
    _apply_env(monkeypatch, _platform_env(tmp_path))
    monkeypatch.setattr(evidence_s3, "S3EvidenceStorage", lambda **_kwargs: _Storage())
    opened: list[Any] = []
    original = DurableJournal

    def journal(*args: Any, **kwargs: Any) -> Any:
        item = original(*args, **kwargs)
        opened.append(item)
        return item

    monkeypatch.setattr(platform_production, "DurableJournal", journal)
    yield platform_production.build_platform_production_app, opened
    close(opened)


@pytest.mark.parametrize("value", [None, "false"])
def test_factory_default_and_explicit_false_allow_registration(
    local_factory: tuple[Any, list[Any]], monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    build, _opened = local_factory
    if value is not None:
        monkeypatch.setenv(SETTING, value)
    app = build()
    with TestClient(app) as client:
        response = client.post(
            "/v1/sites",
            json={"siteId": f"site-{uuid4()}", "name": "Synthetic", "siteFrame": FRAME},
            headers={"Authorization": "Bearer platform-prod-admin-token"},
        )
        assert response.status_code == 201


@pytest.mark.parametrize("value", ["", "1", "0", "TRUE", " true", "false ", "yes"])
def test_factory_invalid_stop_fails_before_resources(
    local_factory: tuple[Any, list[Any]], monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    import ksi_core.evidence_s3 as evidence_s3

    build, opened = local_factory
    calls: list[str] = []
    monkeypatch.setattr(evidence_s3, "S3EvidenceStorage", lambda **_kwargs: calls.append("S3"))
    monkeypatch.setenv(SETTING, value)
    with pytest.raises(RuntimeError, match=SETTING):
        build()
    assert opened == [] and calls == []


def test_factory_stop_guards_http_and_replays_across_restart(
    local_factory: tuple[Any, list[Any]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    build, opened = local_factory
    app = build()
    token, _ = _install_mapped_v2(
        app, capabilities=["SITE_BOOTSTRAP"], site_ids=None, area_ids=None
    )
    body = _bootstrap_body()
    with TestClient(app) as client:
        response = client.post("/v1/sites", headers={"Authorization": f"Bearer {token}"}, json=body)
        assert response.status_code == 201
        site = response.json()["site"]["siteId"]
    close(opened)
    opened.clear()
    monkeypatch.setenv(SETTING, "true")
    app = build()
    token, _ = _install_mapped_v2(
        app, capabilities=["SITE_BOOTSTRAP"], site_ids=None, area_ids=None
    )
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        before = (tmp_path / "data" / "sites.jsonl").read_bytes()
        area_journal = tmp_path / "data" / "work-areas.jsonl"
        area_before = area_journal.read_bytes() if area_journal.exists() else None
        assert client.get(f"/v1/sites/{site}", headers=headers).status_code == 200
        assert client.get(f"/v1/sites/{site}/work-areas", headers=headers).status_code == 200
        replay = client.post("/v1/sites", headers=headers, json=body)
        assert replay.status_code == 201 and replay.json()["site"]["siteId"] == site
        assert client.post("/v1/sites", headers=headers, json=_bootstrap_body()).status_code == 503
        assert (
            client.post(f"/v1/sites/{site}/work-areas", headers=headers, json=AREA).status_code
            == 503
        )
        opaque_headers = {"Authorization": "Bearer platform-prod-admin-token"}
        assert (
            client.post(
                "/v1/sites",
                headers=opaque_headers,
                json={"siteId": f"site-{uuid4()}", "name": "Synthetic", "siteFrame": FRAME},
            ).status_code
            == 503
        )
        assert client.post("/v1/sites", json=body).status_code == 401
        token, _ = _install_mapped_v2(
            app, capabilities=["SITE_BOOTSTRAP"], site_ids=[], area_ids=[]
        )
        assert (
            client.post(
                "/v1/sites", headers={"Authorization": f"Bearer {token}"}, json=body
            ).status_code
            == 404
        )
        token, _ = _install_mapped_v2(
            app,
            capabilities=["SITE_BOOTSTRAP"],
            site_ids=None,
            area_ids=None,
            organization_id="another-synthetic-org",
        )
        other_headers = {"Authorization": f"Bearer {token}"}
        missing = f"site-{uuid4()}"
        hidden_read = client.get(f"/v1/sites/{site}", headers=other_headers)
        missing_read = client.get(f"/v1/sites/{missing}", headers=other_headers)
        assert hidden_read.status_code == missing_read.status_code == 404
        assert hidden_read.json() == missing_read.json()
        hidden_write = client.post(f"/v1/sites/{site}/work-areas", headers=other_headers, json=AREA)
        missing_write = client.post(
            f"/v1/sites/{missing}/work-areas", headers=other_headers, json=AREA
        )
        assert hidden_write.status_code == missing_write.status_code == 404
        assert hidden_write.json() == missing_write.json()
        monkeypatch.setenv(SETTING, "false")
        assert (
            client.post(
                "/v1/sites",
                headers=opaque_headers,
                json={"siteId": f"site-{uuid4()}", "name": "Synthetic", "siteFrame": FRAME},
            ).status_code
            == 503
        )
        assert (tmp_path / "data" / "sites.jsonl").read_bytes() == before
        assert (area_journal.read_bytes() if area_journal.exists() else None) == area_before
    close(opened)
    opened.clear()
    resumed = build()
    with TestClient(resumed) as client:
        assert (
            client.post(
                "/v1/sites",
                headers={"Authorization": "Bearer platform-prod-admin-token"},
                json={"siteId": f"site-{uuid4()}", "name": "Synthetic", "siteFrame": FRAME},
            ).status_code
            == 201
        )
