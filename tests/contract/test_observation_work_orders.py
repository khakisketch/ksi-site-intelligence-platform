"""REQ-WRK-101 관측 작업 원장과 INV-060/061 승인 경계."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore
from ksi_event_contracts.observation_work_order import (
    ObservationWorkOrder,
    ObservationWorkOrderStatus,
)
from ksi_mission_contracts.models import SiteFrame

_TOKEN_A = "observation-org-a-token"  # noqa: S105
_TOKEN_B = "observation-org-b-token"  # noqa: S105
_VIEWER_TOKEN = "observation-viewer-token"  # noqa: S105
_NOW = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
_FRAME = SiteFrame(
    crs="EPSG:5186",
    vertical_datum="KNGeoid2018",
    unit="meter",
    transform_version="1.0.0",
)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _principal(
    token: str, principal_id: str, organization_id: str, role: Role
) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=_digest(token),
        principal=Principal(
            principal_id=principal_id,
            kind=PrincipalKind.OPERATOR,
            role=role,
            device_id=None,
            organization_id=organization_id,
        ),
    )


def _api(tmp_path: Path) -> tuple[TestClient, ObservationWorkOrderStore]:
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    for site_id, organization_id in (("site-a", "org-a"), ("site-b", "org-b")):
        result = site_store.register(
            site_id,
            site_id,
            _FRAME,
            organization_id=organization_id,
            actor="fixture",
            now=_NOW,
        )
        assert result.record is not None
    store = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "observation-work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    auth = AuthRegistry(
        [
            _principal(_TOKEN_A, "operator-a", "org-a", Role.FIELD_OPERATOR),
            _principal(_TOKEN_B, "operator-b", "org-b", Role.FIELD_OPERATOR),
            _principal(_VIEWER_TOKEN, "viewer-a", "org-a", Role.VIEWER),
        ]
    )
    return TestClient(
        create_app(
            auth_registry=auth,
            site_store=site_store,
            observation_work_order_store=store,
        )
    ), store


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_api_is_organization_scoped_and_approval_is_optimistic(tmp_path: Path) -> None:
    client, _ = _api(tmp_path)
    created = client.post(
        "/v1/sites/site-a/observation-work-orders",
        headers=_headers(_TOKEN_A),
        json={
            "name": "주간 토공 관측",
            "workAreaIds": ["wa-site-a-0001"],
            "temporalPolicy": {"maxCaptureSpanSeconds": 600},
        },
    )
    assert created.status_code == 201, created.text
    work_order_id = created.json()["workOrderId"]
    assert created.json()["temporalPolicy"] == {
        "schemaVersion": "1.0",
        "maxCaptureSpanSeconds": 600,
    }

    assert (
        client.get(
            f"/v1/observation-work-orders/{work_order_id}", headers=_headers(_TOKEN_B)
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/v1/sites/site-a/observation-work-orders", headers=_headers(_TOKEN_B)
        ).status_code
        == 404
    )
    assert (
        client.get("/v1/sites/site-a/observation-schedules", headers=_headers(_TOKEN_B)).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/sites/site-a/observation-work-orders",
            headers=_headers(_TOKEN_B),
            json={"name": "침범 시도", "workAreaIds": ["wa-site-a-0001"]},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/sites/site-a/observation-work-orders",
            headers=_headers(_VIEWER_TOKEN),
            json={"name": "권한 없는 생성", "workAreaIds": ["wa-site-a-0001"]},
        ).status_code
        == 403
    )

    conflict = client.post(
        f"/v1/observation-work-orders/{work_order_id}/approve",
        headers=_headers(_TOKEN_A),
        json={"expectedVersion": 9},
    )
    assert conflict.status_code == 409
    approved = client.post(
        f"/v1/observation-work-orders/{work_order_id}/approve",
        headers=_headers(_TOKEN_A),
        json={"expectedVersion": 1},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["approvedBy"] == "operator-a"


def test_global_work_queue_scopes_before_filtering(tmp_path: Path) -> None:
    client, _ = _api(tmp_path)
    draft_a = client.post(
        "/v1/sites/site-a/observation-work-orders",
        headers=_headers(_TOKEN_A),
        json={"name": "승인 대기 작업", "workAreaIds": ["wa-site-a-0001"]},
    )
    approved_a = client.post(
        "/v1/sites/site-a/observation-work-orders",
        headers=_headers(_TOKEN_A),
        json={"name": "진행 작업", "workAreaIds": ["wa-site-a-0002"]},
    )
    draft_b = client.post(
        "/v1/sites/site-b/observation-work-orders",
        headers=_headers(_TOKEN_B),
        json={"name": "다른 조직 작업", "workAreaIds": ["wa-site-b-0001"]},
    )
    assert draft_a.status_code == approved_a.status_code == draft_b.status_code == 201

    approved = client.post(
        f"/v1/observation-work-orders/{approved_a.json()['workOrderId']}/approve",
        headers=_headers(_TOKEN_A),
        json={"expectedVersion": 1},
    )
    assert approved.status_code == 200, approved.text

    all_for_a = client.get("/v1/observation-work-orders", headers=_headers(_TOKEN_A))
    assert all_for_a.status_code == 200, all_for_a.text
    assert {item["name"] for item in all_for_a.json()["workOrders"]} == {
        "승인 대기 작업",
        "진행 작업",
    }

    awaiting_approval = client.get(
        "/v1/observation-work-orders?status=AWAITING_APPROVAL",
        headers=_headers(_TOKEN_A),
    )
    assert [item["name"] for item in awaiting_approval.json()["workOrders"]] == ["승인 대기 작업"]

    in_progress = client.get(
        "/v1/observation-work-orders?actionGroup=IN_PROGRESS",
        headers=_headers(_TOKEN_A),
    )
    assert [item["name"] for item in in_progress.json()["workOrders"]] == ["진행 작업"]

    cross_organization_site = client.get(
        "/v1/observation-work-orders?siteId=site-b",
        headers=_headers(_TOKEN_A),
    )
    assert cross_organization_site.status_code == 404


def test_reobservation_draft_requires_human_approval_and_replays_atomically(
    tmp_path: Path,
) -> None:
    path = tmp_path / "observation-work-orders.jsonl"
    journal = DurableJournal(path)
    store = ObservationWorkOrderStore(
        journal,
        site_exists=lambda site_id, organization_id: (
            site_id == "site-a" and organization_id == "org-a"
        ),
    )
    order = store.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="주간 관측",
        work_area_ids=["wa-site-a-0001"],
        schedule_id=None,
        actor="operator-a",
        now=_NOW,
    )
    order = store.approve(
        order.work_order_id,
        organization_id="org-a",
        expected_version=order.version,
        actor="operator-a",
        now=_NOW + timedelta(minutes=1),
    )
    for status in (
        ObservationWorkOrderStatus.DISPATCHED,
        ObservationWorkOrderStatus.START_REPORTED,
        ObservationWorkOrderStatus.MEDIA_RECEIVING,
        ObservationWorkOrderStatus.PROCESSING,
        ObservationWorkOrderStatus.REVIEW_READY,
    ):
        order = store.record_status(
            order.work_order_id,
            organization_id="org-a",
            status=status,
            status_reason=None,
            mission_ids=["mission-1"],
            processing_job_ids=["job-1"],
            report_refs=["volume-report-1"],
            actor="verified-adapter",
            now=_NOW + timedelta(minutes=order.version),
        )

    draft = store.create_reobservation_draft(
        order.work_order_id,
        organization_id="org-a",
        reason_refs=["volume-report-1#gap-2"],
        target_region_refs=["wa-site-a-0001"],
        proposed_effort="동측 절토면 1회 추가 촬영",
        planner_version="planner-1",
        policy_version="capture-policy-1",
        expires_at=_NOW + timedelta(hours=2),
        actor="copilot:conversation-1",
        now=_NOW + timedelta(minutes=10),
    )
    assert store.get(order.work_order_id, organization_id="org-a").status is (  # type: ignore[union-attr]
        ObservationWorkOrderStatus.REOBSERVATION_PENDING
    )
    approved = store.approve_reobservation(
        draft.draft_id,
        organization_id="org-a",
        expected_version=1,
        actor="operator-a",
        now=_NOW + timedelta(minutes=20),
    )
    assert approved.approved_by == "operator-a"
    reopened = store.get(order.work_order_id, organization_id="org-a")
    assert reopened is not None
    assert reopened.status is ObservationWorkOrderStatus.APPROVED
    assert reopened.cycle_number == 2

    records = journal.replay()
    assert sum(item["kind"] == "reobservation-draft-and-order-created" for item in records) == 1
    assert sum(item["kind"] == "reobservation-draft-and-order-approved" for item in records) == 1
    journal.close()

    replay_journal = DurableJournal(path)
    replayed = ObservationWorkOrderStore(
        replay_journal,
        site_exists=lambda _site_id, _organization_id: True,
    )
    replayed_order = replayed.get(order.work_order_id, organization_id="org-a")
    assert replayed_order is not None
    assert replayed_order.status is ObservationWorkOrderStatus.APPROVED
    assert replayed_order.cycle_number == 2
    replay_journal.close()


def test_post_commit_status_listener_failure_does_not_rollback_work_order(
    tmp_path: Path,
) -> None:
    store = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "listener-isolation.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_id == "site-a" and organization_id == "org-a"
        ),
    )
    observed: list[ObservationWorkOrderStatus] = []

    def listener(order: ObservationWorkOrder) -> None:
        observed.append(order.status)
        if order.status is ObservationWorkOrderStatus.REVIEW_READY:
            raise RuntimeError("briefing provider unavailable")

    store.bind_status_listener(listener)
    order = store.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="원장 우선 작업",
        work_area_ids=["wa-site-a-0001"],
        schedule_id=None,
        actor="operator-a",
        now=_NOW,
    )
    order = store.approve(
        order.work_order_id,
        organization_id="org-a",
        expected_version=order.version,
        actor="operator-a",
        now=_NOW + timedelta(minutes=1),
    )
    for status in (
        ObservationWorkOrderStatus.DISPATCHED,
        ObservationWorkOrderStatus.START_REPORTED,
        ObservationWorkOrderStatus.MEDIA_RECEIVING,
        ObservationWorkOrderStatus.PROCESSING,
        ObservationWorkOrderStatus.REVIEW_READY,
    ):
        order = store.record_status(
            order.work_order_id,
            organization_id="org-a",
            status=status,
            status_reason=None,
            mission_ids=[],
            processing_job_ids=[],
            report_refs=[],
            actor="verified-adapter",
            now=_NOW + timedelta(minutes=order.version),
        )

    committed = store.get(order.work_order_id, organization_id="org-a")
    assert committed is not None
    assert committed.status is ObservationWorkOrderStatus.REVIEW_READY
    assert observed[-1] is ObservationWorkOrderStatus.REVIEW_READY


def test_expired_reobservation_draft_cannot_change_safe_state(tmp_path: Path) -> None:
    journal = DurableJournal(tmp_path / "orders.jsonl")
    store = ObservationWorkOrderStore(journal, site_exists=lambda _site, _org: True)
    order = store.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="만료 테스트",
        work_area_ids=["wa-site-a-0001"],
        schedule_id=None,
        actor="operator-a",
        now=_NOW,
    )
    order = store.approve(
        order.work_order_id,
        organization_id="org-a",
        expected_version=1,
        actor="operator-a",
        now=_NOW,
    )
    for status in (
        ObservationWorkOrderStatus.DISPATCHED,
        ObservationWorkOrderStatus.START_REPORTED,
        ObservationWorkOrderStatus.MEDIA_RECEIVING,
        ObservationWorkOrderStatus.PROCESSING,
        ObservationWorkOrderStatus.BLOCKED,
    ):
        order = store.record_status(
            order.work_order_id,
            organization_id="org-a",
            status=status,
            status_reason="fixture",
            mission_ids=None,
            processing_job_ids=None,
            report_refs=None,
            actor="fixture",
            now=_NOW,
        )
    draft = store.create_reobservation_draft(
        order.work_order_id,
        organization_id="org-a",
        reason_refs=["evidence-1"],
        target_region_refs=["wa-site-a-0001"],
        proposed_effort="한 컷",
        planner_version="planner-1",
        policy_version="policy-1",
        expires_at=_NOW + timedelta(minutes=1),
        actor="copilot",
        now=_NOW,
    )
    with pytest.raises(RuntimeError, match="DRAFT_EXPIRED"):
        store.approve_reobservation(
            draft.draft_id,
            organization_id="org-a",
            expected_version=1,
            actor="operator-a",
            now=_NOW + timedelta(minutes=2),
        )
    current = store.get(order.work_order_id, organization_id="org-a")
    assert current is not None
    assert current.status is ObservationWorkOrderStatus.REOBSERVATION_PENDING
    journal.close()


def test_initial_external_work_order_is_approved_once_and_replays_lost_response(
    tmp_path: Path,
) -> None:
    client, store = _api(tmp_path)
    headers = {**_headers(_TOKEN_A), "Idempotency-Key": "external-create-1"}
    payload = {
        "name": "외부 정사영상 비교",
        "workAreaIds": ["wa-site-a-0001"],
        "scheduleId": None,
        "executionMode": "EXTERNAL_RECONSTRUCTION",
    }

    created = client.post("/v1/sites/site-a/observation-work-orders", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["executionMode"] == "EXTERNAL_RECONSTRUCTION"
    assert body["status"] == "APPROVED"
    assert body["createdBy"] == body["approvedBy"] == "operator-a"
    assert body["createdAt"] == body["approvedAt"]

    retried = client.post("/v1/sites/site-a/observation-work-orders", headers=headers, json=payload)
    assert retried.status_code == 201, retried.text
    assert retried.json() == body
    assert len(store.list_for_site("site-a", organization_id="org-a")) == 1

    changed_body = client.post(
        "/v1/sites/site-a/observation-work-orders",
        headers=headers,
        json={**payload, "name": "다른 요청 본문"},
    )
    assert changed_body.status_code == 409

    assert (
        client.post(
            "/v1/sites/site-a/observation-work-orders",
            headers=_headers(_TOKEN_A),
            json=payload,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/sites/site-a/observation-work-orders",
            headers={**_headers(_TOKEN_A), "Idempotency-Key": "external-create-2"},
            json={**payload, "scheduleId": "obs-schedule-00000001"},
        ).status_code
        == 422
    )


def test_managed_create_optional_idempotency_is_ordered_and_never_retains_raw_key(
    tmp_path: Path,
) -> None:
    active = True
    journal = DurableJournal(tmp_path / "managed-create-idempotency.jsonl")
    store = ObservationWorkOrderStore(
        journal,
        site_exists=lambda _site, _org: True,
        work_areas_exist=lambda _site, _areas: active,
    )
    key = "managed-retry-key"
    created = store.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="현장 관측",
        work_area_ids=["wa-site-a-0002", "wa-site-a-0001"],
        schedule_id=None,
        idempotency_key=key,
        actor="operator-a",
        now=_NOW,
    )
    active = False
    replayed = store.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="현장 관측",
        work_area_ids=["wa-site-a-0002", "wa-site-a-0001"],
        schedule_id=None,
        idempotency_key=key,
        actor="operator-a",
        now=_NOW,
    )
    assert replayed == created
    with pytest.raises(RuntimeError, match="EXTERNAL_CREATE_IDEMPOTENCY_CONFLICT"):
        store.create_work_order(
            organization_id="org-a",
            site_id="site-a",
            name="현장 관측",
            work_area_ids=["wa-site-a-0001", "wa-site-a-0002"],
            schedule_id=None,
            idempotency_key=key,
            actor="operator-a",
            now=_NOW,
        )
    records = journal.replay()
    assert len(records) == 1
    assert records[0]["createIdempotency"].keys() == {"keyHash", "fingerprint"}
    assert key not in json.dumps(records, ensure_ascii=False)
    journal.close()


def test_initial_external_work_order_replay_keeps_execution_guard_and_legacy_is_nullable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "external-work-order.jsonl"
    store = ObservationWorkOrderStore(DurableJournal(path), site_exists=lambda _site, _org: True)
    external = store.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="외부 산출물 등록",
        work_area_ids=["wa-site-a-0001"],
        schedule_id=None,
        execution_mode="EXTERNAL_RECONSTRUCTION",
        idempotency_key="external-replay-1",
        actor="operator-a",
        now=_NOW,
    )
    assert external.status is ObservationWorkOrderStatus.APPROVED
    for action in (
        lambda: store.approve(
            external.work_order_id,
            organization_id="org-a",
            expected_version=external.version,
            actor="operator-a",
            now=_NOW,
        ),
        lambda: store.link_mission(
            external.work_order_id,
            organization_id="org-a",
            cycle_number=1,
            mission_id="mission-1",
            mission_site_id="site-a",
            actor="operator-a",
            now=_NOW,
            require_approved=True,
        ),
        lambda: store.record_status(
            external.work_order_id,
            organization_id="org-a",
            status=ObservationWorkOrderStatus.DISPATCHED,
            status_reason=None,
            mission_ids=None,
            processing_job_ids=None,
            report_refs=None,
            actor="adapter",
            now=_NOW,
        ),
    ):
        with pytest.raises(RuntimeError, match="EXTERNAL_RECONSTRUCTION_ONLY"):
            action()

    store._journal.close()  # noqa: SLF001 -- restart/replay contract
    replayed = ObservationWorkOrderStore(DurableJournal(path), site_exists=lambda _site, _org: True)
    restored = replayed.get(external.work_order_id, organization_id="org-a")
    assert restored is not None
    assert restored.execution_mode is not None
    assert restored.execution_mode.value == "EXTERNAL_RECONSTRUCTION"
    replayed._journal.close()  # noqa: SLF001 -- fixture closes its durable handle

    legacy = ObservationWorkOrder.model_validate(
        {
            "schemaVersion": "1.0",
            "workOrderId": "legacy-work-order",
            "organizationId": "org-a",
            "siteId": "site-a",
            "purpose": "PROGRESS_QUANTITY",
            "name": "기존 작업",
            "workAreaIds": ["wa-site-a-0001"],
            "scheduleId": None,
            "cycleNumber": 1,
            "status": "AWAITING_APPROVAL",
            "statusReason": None,
            "missionIds": [],
            "processingJobIds": [],
            "reportRefs": [],
            "version": 1,
            "createdAt": _NOW.isoformat(),
            "updatedAt": _NOW.isoformat(),
            "createdBy": "operator-a",
            "approvedAt": None,
            "approvedBy": None,
        }
    )
    assert legacy.execution_mode is None
