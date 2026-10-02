"""Real production composition with test-owned signed input, never release evidence."""

import hashlib
import json
import multiprocessing
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from ksi_core import production
from ksi_core.external_quantitative_authority import ExternalQuantitativeCatalogAuthorityRecord
from ksi_domain.canonical_json import canonical_json_bytes


def _signed_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fixture_signers: list[Any] | None = None,
    catalog_active_for: timedelta = timedelta(hours=4),
) -> Path:
    from test_external_authority_provider_contract import NOW, _provider_config
    from test_external_result_workflow_config import _catalog_body, _catalog_digest, _write_private
    from test_production_assembly import _apply_env, _valid_env

    def catalog_body(authority_digest: str | None = None) -> dict[str, Any]:
        body = _catalog_body(authority_digest)
        templates: Any = body["executionTemplates"]
        templates[0]["validFrom"] = NOW.isoformat()
        templates[0]["validUntil"] = (NOW + catalog_active_for).isoformat()
        return body

    record = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id="org-a",
        catalog_body_digest=_catalog_digest(catalog_body()),
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=NOW,
        active_until=NOW + catalog_active_for,
        synthetic_test_only=False,
    ).sealed()
    provider_path = _provider_config(
        tmp_path,
        catalog_records=(record.event_payload(),),
        fixture_signers=fixture_signers,
    )
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


def _use_test_clock(
    monkeypatch: pytest.MonkeyPatch, *, elapsed: timedelta = timedelta(minutes=1)
) -> None:
    from test_external_authority_provider_contract import NOW

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> "FixedClock":
            value = NOW + elapsed
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


def _exercise_expired_boot_and_reload(signer_bytes: bytes, expected_receipt: bytes) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from test_external_authority_provider_contract import NOW

    monkeypatch = pytest.MonkeyPatch()
    _use_test_clock(monkeypatch, elapsed=timedelta(hours=2))
    app = production.build_production_app()
    receipt = Path(app.state.external_authority_provider._receipt_journal._path)
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        assert client.get("/ready/external-authority").status_code == 503
        provider = app.state.external_authority_provider
        assert provider.status()["status"] == "BLOCKED"
        assert receipt.read_bytes() == expected_receipt
        workflow_path = Path(os.environ["KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG"])
        catalog = json.loads(workflow_path.read_text(encoding="utf-8"))
        catalog_path = Path(catalog["catalogPath"])
        catalog_digest = json.loads(catalog_path.read_text())["authorityRecordDigest"]
        assert provider.participants.catalog_authority_port.resolve(
            catalog_digest, production.datetime.now(UTC)
        ) is None

        snapshot_path = Path(os.environ["KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG"])
        # The provider config is separate from the signed snapshot; resolve its
        # exact configured path before replacing the fixture with sequence 2.
        config = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot = Path(config["snapshotPath"])
        raw = json.loads(snapshot.read_text(encoding="utf-8"))
        unsigned = {key: value for key, value in raw.items() if key != "signature"}
        previous_digest = "sha256:" + hashlib.sha256(
            canonical_json_bytes(
                {
                    "domain": "ksi.external-authority-provider-snapshot.v1",
                    "snapshot": unsigned,
                }
            )
        ).hexdigest()
        _replace_snapshot_for_test(
            snapshot,
            Ed25519PrivateKey.from_private_bytes(signer_bytes),
            {
                "sequence": 2,
                "previousSnapshotDigest": previous_digest,
                "issuedAt": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                "validUntil": (NOW + timedelta(hours=4)).isoformat().replace("+00:00", "Z"),
            },
        )
        from ksi_core.external_authority_provider import load_external_authority_provider

        load_external_authority_provider(
            Path(os.environ["KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG"]),
            clock=lambda: production.datetime.now(UTC),
        )
        response = client.post(
            "/v1/operations/external-authority/reload",
            json={},
            headers={"Authorization": "Bearer prod-admin-token"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "PROVIDER_CONFIGURED", response.json()
        assert client.get("/ready/external-authority").status_code == 200
        assert receipt.read_bytes() != expected_receipt


def test_expired_signed_authority_degrades_external_readiness_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_signers: list[Any] = []
    _signed_environment(tmp_path, monkeypatch, fixture_signers=fixture_signers)
    receipt = tmp_path / "production/data/external-authority-provider-receipts.jsonl"
    context = multiprocessing.get_context("spawn")
    first = context.Process(target=_exercise_signed_production)
    first.start()
    try:
        first.join(timeout=15)
        assert not first.is_alive(), "initial production probe timed out"
        assert first.exitcode == 0
    finally:
        if first.is_alive():
            first.terminate()
            first.join(timeout=5)
    initial_receipt = receipt.read_bytes()

    signer_bytes = fixture_signers[0].private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    second = context.Process(
        target=_exercise_expired_boot_and_reload, args=(signer_bytes, initial_receipt)
    )
    second.start()
    second.join(timeout=15)
    try:
        assert not second.is_alive(), "expired production probe timed out"
        assert second.exitcode == 0
    finally:
        if second.is_alive():
            second.terminate()
            second.join(timeout=5)


def _exercise_expired_catalog_production(expected_receipt: bytes) -> None:
    monkeypatch = pytest.MonkeyPatch()
    _use_test_clock(monkeypatch, elapsed=timedelta(minutes=40))
    app = production.build_production_app()
    receipt = Path(app.state.external_authority_provider._receipt_journal._path)
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        assert client.get("/ready/external-authority").json() == {
            "status": "PROVIDER_CONFIGURED"
        }
        workflow_path = Path(os.environ["KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG"])
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        catalog = json.loads(Path(workflow["catalogPath"]).read_text(encoding="utf-8"))
        digest = catalog["authorityRecordDigest"]
        provider = app.state.external_authority_provider
        now = production.datetime.now(UTC)
        assert provider.participants.catalog_authority_port.resolve(digest, now) is None
        assert receipt.read_bytes() == expected_receipt


def _exercise_recovered_catalog_production(expected_catalog_digest: str) -> None:
    monkeypatch = pytest.MonkeyPatch()
    _use_test_clock(monkeypatch, elapsed=timedelta(minutes=40))
    app = production.build_production_app()
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        assert client.get("/ready/external-authority").json() == {
            "status": "PROVIDER_CONFIGURED"
        }
        provider = app.state.external_authority_provider
        authority = provider.participants.catalog_authority_port.resolve(
            expected_catalog_digest, production.datetime.now(UTC)
        )
        assert authority is not None and authority.digest == expected_catalog_digest


def test_expired_catalog_with_current_snapshot_keeps_core_ready_and_denies_live_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_signers: list[Any] = []
    _signed_environment(
        tmp_path,
        monkeypatch,
        fixture_signers=fixture_signers,
        catalog_active_for=timedelta(minutes=30),
    )
    context = multiprocessing.get_context("spawn")
    initial = context.Process(target=_exercise_signed_production)
    initial.start()
    try:
        initial.join(timeout=15)
        assert not initial.is_alive(), "initial provider probe timed out"
        assert initial.exitcode == 0
    finally:
        if initial.is_alive():
            initial.terminate()
            initial.join(timeout=5)
    receipt_path = tmp_path / "production/data/external-authority-provider-receipts.jsonl"
    receipt_before_expiry = receipt_path.read_bytes()
    expired = context.Process(
        target=_exercise_expired_catalog_production, args=(receipt_before_expiry,)
    )
    expired.start()
    try:
        expired.join(timeout=15)
        assert not expired.is_alive(), "expired catalog probe timed out"
        assert expired.exitcode == 0
    finally:
        if expired.is_alive():
            expired.terminate()
            expired.join(timeout=5)
    assert receipt_path.read_bytes() == receipt_before_expiry

    from test_external_authority_provider_contract import NOW
    from test_external_result_workflow_config import _catalog_digest, _write_private

    workflow_path = tmp_path / "workflow.json"
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    catalog_path = Path(workflow["catalogPath"])
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    body = catalog["body"]
    valid_until = (NOW + timedelta(hours=4)).isoformat().replace("+00:00", "Z")
    for collection in ("executionTemplates", "singleExecutionTemplates"):
        for template in body.get(collection, []):
            template["validUntil"] = valid_until
            template["executionPolicy"].pop("authorityRecordDigest", None)
    record = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id="org-a",
        catalog_body_digest=_catalog_digest(body),
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=NOW,
        active_until=NOW + timedelta(hours=4),
        synthetic_test_only=False,
    ).sealed()
    assert record.digest is not None
    for collection in ("executionTemplates", "singleExecutionTemplates"):
        for template in body.get(collection, []):
            template["executionPolicy"]["authorityRecordDigest"] = record.digest
    catalog["authorityRecordDigest"] = record.digest
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    _write_private(catalog_path, catalog)

    provider_config = json.loads(
        (tmp_path / "external-authority-provider.json").read_text(encoding="utf-8")
    )
    snapshot_path = Path(provider_config["snapshotPath"])
    raw_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    unsigned_snapshot = {
        key: value for key, value in raw_snapshot.items() if key != "signature"
    }
    previous_digest = "sha256:" + hashlib.sha256(
        canonical_json_bytes(
            {
                "domain": "ksi.external-authority-provider-snapshot.v1",
                "snapshot": unsigned_snapshot,
            }
        )
    ).hexdigest()
    _replace_snapshot_for_test(
        snapshot_path,
        fixture_signers[0],
        {
            "sequence": 2,
            "previousSnapshotDigest": previous_digest,
            "issuedAt": (NOW + timedelta(minutes=20)).isoformat().replace("+00:00", "Z"),
            "catalogAuthorities": {
                "records": [record.event_payload()],
                "currentDigests": [record.digest],
            },
        },
    )
    recovered = context.Process(
        target=_exercise_recovered_catalog_production, args=(record.digest,)
    )
    recovered.start()
    try:
        recovered.join(timeout=15)
        assert not recovered.is_alive(), "recovered catalog probe timed out"
        assert recovered.exitcode == 0
    finally:
        if recovered.is_alive():
            recovered.terminate()
            recovered.join(timeout=5)
    assert receipt_path.read_bytes() != receipt_before_expiry


def test_historical_catalog_binding_rejects_mismatched_signed_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot_path = _signed_environment(
        tmp_path, monkeypatch, catalog_active_for=timedelta(minutes=30)
    )
    from test_external_authority_provider_contract import NOW
    from test_external_result_workflow_config import _catalog_digest

    _use_test_clock(monkeypatch, elapsed=timedelta(minutes=40))
    from ksi_core.external_authority_provider import load_external_authority_provider

    provider = load_external_authority_provider(
        tmp_path / "external-authority-provider.json",
        clock=lambda: NOW + timedelta(minutes=40),
    )
    workflow = json.loads((tmp_path / "workflow.json").read_text(encoding="utf-8"))
    catalog = json.loads(Path(workflow["catalogPath"]).read_text(encoding="utf-8"))
    authority_digest = catalog["authorityRecordDigest"]
    body = deepcopy(catalog["body"])
    for collection in ("executionTemplates", "singleExecutionTemplates"):
        for template in body.get(collection, []):
            template["executionPolicy"].pop("authorityRecordDigest", None)
    body_digest = _catalog_digest(body)
    historical_binding = getattr(
        provider.participants.catalog_authority_port, "resolve_historical_configuration", None
    )
    assert callable(historical_binding)
    assert historical_binding(
        authority_digest,
        catalog_body_digest=body_digest,
        organization_id="org-a",
        administration_actor_id="catalog-admin",
    )
    assert not historical_binding(
        authority_digest,
        catalog_body_digest="sha256:" + "0" * 64,
        organization_id="org-a",
        administration_actor_id="catalog-admin",
    )
    assert not historical_binding(
        authority_digest,
        catalog_body_digest=body_digest,
        organization_id="org-b",
        administration_actor_id="catalog-admin",
    )
    assert not historical_binding(
        authority_digest,
        catalog_body_digest=body_digest,
        organization_id="org-a",
        administration_actor_id="unapproved-actor",
    )
    assert snapshot_path.is_file()


def _replace_snapshot_for_test(
    path: Path, signer: Any, changes: dict[str, object]
) -> None:
    from test_external_authority_provider_contract import _replace_signed_snapshot

    # Existing helper uses the canonical fixture filename under the same root.
    _replace_signed_snapshot(path.parent, signer, changes)


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
