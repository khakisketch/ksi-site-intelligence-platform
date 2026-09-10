"""Shared dev/production composition retains planning-only execution authority."""

from datetime import UTC, datetime

import ksi_core.app_assembly as assembly
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.auth import AuthRegistry
from ksi_core.durable_journal import DurableJournal
from ksi_core.observation_work_orders import ExternalReobservationExecutionDenied
from test_external_reobservation_successor import _approve, _store_with_source


def test_shared_assembly_denies_actual_planning_only_successor_without_run(tmp_path, monkeypatch):
    order_journal, orders, authority = _store_with_source(tmp_path)
    successor = _approve(orders, authority).successor_work_order
    assert successor is not None
    # Supply an already verified authority-backed WorkOrder journal. All other
    # graph nodes and the acquisition constructor are the actual shared assembly.
    monkeypatch.setattr(assembly, "ObservationWorkOrderStore", lambda *args, **kwargs: orders)
    opened = [order_journal]

    def journal(name):
        value = DurableJournal(tmp_path / name)
        opened.append(value)
        return value

    try:
        app = assembly.assemble_app(
            tmp_path,
            journal=journal,
            opened=opened,
            edge_sync_snapshot_every=None,
            auth_registry=AuthRegistry([]),
            evidence_storage=None,
            mission_signing_key=Ed25519PrivateKey.generate(),
            mission_signing_key_id="synthetic-assembly-key",
        )
        runs = app.state.acquisition_coordination_store
        run_path = tmp_path / "acquisition-runs.jsonl"
        before = run_path.read_bytes() if run_path.exists() else b""
        orders_before = (tmp_path / "work-orders.jsonl").read_bytes()
        with pytest.raises(ExternalReobservationExecutionDenied, match="PLANNING_ONLY"):
            runs.ensure_run(successor, actor="fixture", now=datetime(2026, 9, 9, 3, tzinfo=UTC))
        assert (run_path.read_bytes() if run_path.exists() else b"") == before
        assert (tmp_path / "work-orders.jsonl").read_bytes() == orders_before
    finally:
        for resource in reversed(opened):
            resource.close()
