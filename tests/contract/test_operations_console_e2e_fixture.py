"""Operations Console E2E fixture stays scoped, deterministic, and fail-closed."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import boto3
import pytest
from ksi_core.durable_journal import DurableJournal
from ksi_core.events import EventStore
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore

_FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "apps"
    / "dashboard"
    / "e2e"
    / "fixtures"
    / "seed_operations_console.py"
)


def _fixture_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_operations_console", _FIXTURE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture_uses_real_store_transitions_and_local_oidc_scope(tmp_path: Path) -> None:
    fixture = _fixture_module()
    fixture.seed(tmp_path)

    site_journal = DurableJournal(tmp_path / "sites.jsonl")
    event_journal = DurableJournal(tmp_path / "events.jsonl")
    work_order_journal = DurableJournal(tmp_path / "observation-work-orders.jsonl")
    try:
        sites = SiteStore(site_journal)
        events = EventStore(event_journal)
        work_orders = ObservationWorkOrderStore(
            work_order_journal,
            site_exists=lambda site_id, organization_id: (
                sites.get_scoped(site_id, organization_id) is not None
            ),
        )

        scoped_sites = sites.list_scoped(fixture.ORGANIZATION_ID)
        assert len(scoped_sites) == 5
        assert all(not site.ai_egress_allowed for site in scoped_sites)
        assert {site.status.value for site in scoped_sites} == {"UNMAPPED", "BASELINE_MAPPING"}
        assert sites.list_scoped("legacy") == []

        scoped_orders = work_orders.list_scoped(organization_id=fixture.ORGANIZATION_ID)
        assert {order.status.value for order in scoped_orders} == {
            "AWAITING_APPROVAL",
            "APPROVED",
            "REVIEW_READY",
            "COMPLETED",
        }
        assert all(order.mission_ids == [] for order in scoped_orders)
        assert all(order.processing_job_ids == [] for order in scoped_orders)
        assert all(order.report_refs == [] for order in scoped_orders)

        scoped_events = events.list(organization_id=fixture.ORGANIZATION_ID)
        assert len(scoped_events) == 1
        assert scoped_events[0].status.value == "FINDING"
        assert len(scoped_events[0].evidence) == 1
        assert events.list(organization_id="legacy") == []
    finally:
        work_order_journal.close()
        event_journal.close()
        site_journal.close()


def test_fixture_refuses_to_mix_with_existing_ledgers(tmp_path: Path) -> None:
    fixture = _fixture_module()
    (tmp_path / "sites.jsonl").write_text("occupied\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="requires empty ledgers"):
        fixture.seed(tmp_path)


def test_phase2_fixture_scopes_ai_egress_and_uploads_real_synthetic_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture_module()
    put_calls: list[dict[str, Any]] = []

    class FakeS3:
        def put_object(self, **kwargs: Any) -> None:
            put_calls.append(kwargs)

    def fake_client(service: str, **kwargs: Any) -> FakeS3:
        assert service == "s3"
        assert kwargs["endpoint_url"] == "http://minio.test:9000"
        return FakeS3()

    monkeypatch.setattr(boto3, "client", fake_client)
    fixture.seed(
        tmp_path,
        enable_synthetic_ai_egress=True,
        s3_endpoint="http://minio.test:9000",
        s3_bucket="synthetic-evidence",
    )

    site_journal = DurableJournal(tmp_path / "sites.jsonl")
    event_journal = DurableJournal(tmp_path / "events.jsonl")
    try:
        sites = SiteStore(site_journal)
        scoped_sites = sites.list_scoped(fixture.ORGANIZATION_ID)
        assert {
            site.site_id for site in scoped_sites if site.ai_egress_allowed
        } == {"e2e-site-workspace"}

        events = EventStore(event_journal)
        evidence = events.list(organization_id=fixture.ORGANIZATION_ID)[0].evidence[0]
        assert evidence.content_type == "image/png"
        assert evidence.content_digest == (
            "sha256:" + hashlib.sha256(fixture.SYNTHETIC_EVIDENCE_BYTES).hexdigest()
        )
        assert put_calls == [
            {
                "Bucket": "synthetic-evidence",
                "Key": evidence.object_key,
                "Body": fixture.SYNTHETIC_EVIDENCE_BYTES,
                "ContentType": "image/png",
            }
        ]
    finally:
        event_journal.close()
        site_journal.close()


def test_phase2_fixture_requires_complete_s3_configuration(tmp_path: Path) -> None:
    fixture = _fixture_module()
    with pytest.raises(ValueError, match="configured together"):
        fixture.seed(tmp_path, s3_endpoint="http://minio.test:9000")
