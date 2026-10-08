"""Archived edge-ingest guard proof (P3 Task 5 relocation record, RB-08).

Relocated verbatim from ``tests/contract/test_recorded_pipeline.py::
test_offline_pipeline_output_is_rejected_by_core_production_ingest``: it proves
replay bundles are rejected by production edge ingest (422
NON_PRODUCTION_EVIDENCE) using the REAL ``EdgeSyncStore``/``EventStore``
constructors — both retired to ``archive/acquisition-2026/`` with the managed
set. The staying replay/pipeline coverage lives in the active file. This file
is archive-internal (``archive/`` is not a pytest testpath, import path, or
workspace member) and is NOT executed.
"""


def test_offline_pipeline_output_is_rejected_by_core_production_ingest(tmp_path: Path) -> None:
    """run_vertical_slice의 contract-shaped bundle은 production 원장을 선점하지 않는다.

    replay와 production이 같은 EventBundle wire를 쓰는 것은 conformance를 위한 것이지
    replay 결과를 현장 evidence로 승격하는 권한이 아니다.
    """
    import hashlib

    from fastapi.testclient import TestClient
    from ksi_core.app import create_app
    from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.edge_sync import EdgeSyncStore
    from ksi_core.events import EventStore
    from ksi_event_contracts.offline_sync import JournalEntry, payload_digest

    edge_device_id = "e2e-edge-001"
    edge_token = "e2e-recorded-pipeline-edge-token"  # noqa: S105 — 테스트 고정 토큰
    auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(edge_token.encode("utf-8")).hexdigest(),
                principal=Principal(
                    principal_id="edge-principal-e2e-recorded-pipeline",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id=edge_device_id,
                ),
            )
        ]
    )

    result = run_vertical_slice(
        frames=[
            recorded_pipeline.SliceFrame(
                frame_id=i, capture_ts_utc=i * 0.2, width=1920, height=1080
            )
            for i in range(2)
        ],
        detector=ScriptedDetector(
            {
                i: [
                    person_detection(
                        x_min=900.0 + i * 4, y_min=500.0, x_max=980.0 + i * 4, y_max=700.0
                    )
                ]
                for i in range(2)
            }
        ),
        telemetry=synthetic_telemetry([0.0, 0.2]),
        drone_position=(100.0, 200.0, 60.0),
        context=make_run_context(),
    )
    [bundle] = result.bundles

    from ksi_event_contracts.event_bundle import event_bundle_wire_dict

    payload = event_bundle_wire_dict(bundle)
    entry = JournalEntry(
        idempotency_key=f"e2e:{bundle.event_id}",
        device_sequence=0,
        edge_device_id=edge_device_id,
        payload_digest=payload_digest(payload),
        payload=payload,
    )
    store = EdgeSyncStore(tmp_path / "journal.jsonl")
    event_store = EventStore(DurableJournal(tmp_path / "events" / "journal.jsonl"))
    client = TestClient(
        create_app(edge_sync_store=store, event_store=event_store, auth_registry=auth_registry)
    )
    request_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {edge_token}",
    }
    rejected = client.post(
        "/v1/edge-sync/event-bundles",
        content=entry.model_dump_json(by_alias=True),
        headers=request_headers,
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["verdict"] == "NON_PRODUCTION_EVIDENCE"
    assert store.accepted_count() == 0
    assert event_store.get(f"{edge_device_id}::{bundle.event_id}") is None
