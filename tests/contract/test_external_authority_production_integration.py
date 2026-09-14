"""Real production composition with test-owned signed input, never release evidence."""

import json
import multiprocessing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ksi_core import production
from ksi_core.external_quantitative_authority import ExternalQuantitativeCatalogAuthorityRecord


def _signed_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from test_external_authority_provider_contract import NOW, _provider_config
    from test_external_result_workflow_config import _catalog_body, _catalog_digest, _write_private
    from test_production_assembly import _apply_env, _valid_env

    def catalog_body(authority_digest: str | None = None) -> dict[str, Any]:
        body = _catalog_body(authority_digest)
        templates: Any = body["executionTemplates"]
        templates[0]["validFrom"] = NOW.isoformat()
        templates[0]["validUntil"] = (NOW + timedelta(hours=1)).isoformat()
        return body

    record = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id="org-a",
        catalog_body_digest=_catalog_digest(catalog_body()),
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=NOW,
        active_until=NOW + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    provider_path = _provider_config(tmp_path, catalog_records=(record.event_payload(),))
    catalog = tmp_path / "catalog.json"
    _write_private(catalog, {
        "version": "external-quantitative-catalog.v1",
        "authorityRecordDigest": record.digest,
        "body": catalog_body(record.digest),
    })
    workflow = tmp_path / "workflow.json"
    _write_private(workflow, {
        "version": "external-result-workflow-config.v1",
        "authorityJournalPath": str(tmp_path / "authority.jsonl"),
        "catalogPath": str(catalog),
    })
    environment = _valid_env(tmp_path / "production")
    principals = json.loads(environment["KSI_CORE_PRINCIPAL_TOKENS_JSON"])
    principals[0]["organizationId"] = "org-a"
    environment["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(principals)
    environment["KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG"] = str(workflow)
    environment["KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG"] = str(provider_path)
    _apply_env(monkeypatch, environment)
    _use_test_clock(monkeypatch)
    return tmp_path / "authority-snapshot.json"


def _use_test_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from test_external_authority_provider_contract import NOW

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> "FixedClock":
            value = NOW + timedelta(minutes=1)
            selected = value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)
            return cls.fromisoformat(selected.isoformat())

    monkeypatch.setattr(production, "datetime", FixedClock)
    # Operations uses the same test instant; signature verification and stores are real.
    import ksi_core.external_authority_operations as operations

    monkeypatch.setattr(operations, "datetime", FixedClock)


def _exercise_signed_production() -> None:
    # A spawned interpreter receives the prepared environment and real files,
    # but installs its own deterministic clock without inheriting thread locks.
    monkeypatch = pytest.MonkeyPatch()
    _use_test_clock(monkeypatch)
    app = production.build_production_app()
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        assert client.get("/ready/external-authority").json() == {
            "status": "PROVIDER_CONFIGURED"
        }
        status = app.state.external_authority_provider.status()
        assert status["businessEligible"] is False
        response = client.post(
            "/v1/operations/external-authority/reload", json={},
            headers={"Authorization": "Bearer prod-admin-token"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "PROVIDER_CONFIGURED"


def test_signed_provider_attaches_to_real_production_and_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _signed_environment(tmp_path, monkeypatch)
    receipt = tmp_path / "production/data/external-authority-provider-receipts.jsonl"
    # Production journals are process-owned. Use actual process termination to
    # release their locks, retaining the signed files and journals for restart.
    # Spawn avoids inheriting locks from the full suite's background threads.
    # The parent opens no journal and the child installs the same test clock.
    context = multiprocessing.get_context("spawn")
    for _ in range(2):
        process = context.Process(target=_exercise_signed_production)
        process.start()
        try:
            process.join(timeout=15)
            assert not process.is_alive(), "production restart probe timed out"
            assert process.exitcode == 0
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        assert receipt.is_file()
        if _ == 0:
            initial_receipt = receipt.read_bytes()
        else:
            assert receipt.read_bytes() == initial_receipt


def test_invalid_reload_closes_provider_without_forging_process_unhealthiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _signed_environment(tmp_path, monkeypatch)
    with TestClient(production.build_production_app()) as client:
        snapshot.write_text("{}", encoding="utf-8")
        response = client.post(
            "/v1/operations/external-authority/reload", json={},
            headers={"Authorization": "Bearer prod-admin-token"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "BLOCKED"
        assert client.get("/ready/external-authority").status_code == 503
        assert client.get("/ready").status_code == 200
