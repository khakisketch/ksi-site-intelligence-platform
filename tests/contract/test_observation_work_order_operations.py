"""Administrative external WorkOrder operations remain separate from sealed observation state."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.acquisition import observation_epoch_id
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_relative_volumes import (
    ExternalRelativeVolumeInputCapabilityIssuer,
    ExternalRelativeVolumeStore,
    build_external_relative_volume_router,
)
from ksi_core.observation_work_orders import (
    ObservationWorkOrderStore,
    ObservationWorkOrderStoreRecoveryError,
)
from ksi_core.site_workspace import SiteWorkspaceProjector
from ksi_core.sites import SiteStore
from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1
from ksi_mission_contracts.models import SiteFrame
from test_external_reconstruction_api import _TOKEN as _RECONSTRUCTION_TOKEN
from test_external_reconstruction_api import _client as _reconstruction_client
from test_external_reconstruction_api import _submission as _reconstruction_submission
from test_external_reobservation_successor import _approve, _store_with_source

_NOW = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
_OPERATOR_A = "operations-operator-a"  # noqa: S105 -- deterministic test token
_OPERATOR_B = "operations-operator-b"  # noqa: S105 -- deterministic test token
_VIEWER_A = "operations-viewer-a"  # noqa: S105 -- deterministic test token
_FRAME = SiteFrame(
    crs="EPSG:5186",
    vertical_datum="KNGeoid2018",
    unit="meter",
    transform_version="1.0.0",
)


def _token(token: str, principal_id: str, organization_id: str, role: Role) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        principal=Principal(
            principal_id=principal_id,
            kind=PrincipalKind.OPERATOR,
            role=role,
            device_id=None,
            organization_id=organization_id,
        ),
    )


def _headers(token: str, *, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _api(tmp_path: Path) -> tuple[TestClient, ObservationWorkOrderStore, SiteStore, Path]:
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    for site_id, organization_id in (("site-a", "org-a"), ("site-b", "org-b")):
        registered = site_store.register(
            site_id,
            site_id,
            _FRAME,
            organization_id=organization_id,
            actor="fixture",
            now=_NOW,
        )
        assert registered.record is not None
    journal_path = tmp_path / "observation-work-orders.jsonl"
    store = ObservationWorkOrderStore(
        DurableJournal(journal_path),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    auth = AuthRegistry(
        [
            _token(_OPERATOR_A, "operator-a", "org-a", Role.FIELD_OPERATOR),
            _token(_OPERATOR_B, "operator-b", "org-b", Role.FIELD_OPERATOR),
            _token(_VIEWER_A, "viewer-a", "org-a", Role.VIEWER),
        ]
    )
    return (
        TestClient(
            create_app(
                auth_registry=auth,
                site_store=site_store,
                observation_work_order_store=store,
            )
        ),
        store,
        site_store,
        journal_path,
    )


def _create_external(client: TestClient, *, key: str = "external-create") -> dict[str, object]:
    response = client.post(
        "/v1/sites/site-a/observation-work-orders",
        headers=_headers(_OPERATOR_A, key=key),
        json={
            "name": "외부 관측 운영",
            "workAreaIds": ["area-a"],
            "scheduleId": None,
            "executionMode": "EXTERNAL_RECONSTRUCTION",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


class _NeverIssueRelativeVolumeStore:
    """Only scope validation should run for the absent/foreign route cases."""

    def is_issue_retry(self, **_kwargs: object) -> bool:
        return False

    def issue(self, **_kwargs: object) -> object:
        raise AssertionError("a missing or foreign WorkOrder must not reach volume issue")


def test_relative_volume_issue_hides_absent_and_foreign_work_orders(
    tmp_path: Path,
) -> None:
    _client_a, work_orders, _, _ = _api(tmp_path)
    created = _create_external(_client_a)
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                _token(_OPERATOR_A, "operator-a", "org-a", Role.FIELD_OPERATOR),
                _token(_OPERATOR_B, "operator-b", "org-b", Role.FIELD_OPERATOR),
            ]
        ),
    )
    app.include_router(
        build_external_relative_volume_router(
            cast(ExternalRelativeVolumeStore, _NeverIssueRelativeVolumeStore()),
            input_capability_issuer=cast(
                ExternalRelativeVolumeInputCapabilityIssuer,
                lambda *_args, **_kwargs: None,
            ),
            work_orders=work_orders,
        )
    )
    client = TestClient(app, raise_server_exceptions=False)
    body = {"decisionRef": "decision-a"}

    absent = client.post(
        "/v1/observation-work-orders/absent-order/relative-volume-requests",
        headers=_headers(_OPERATOR_A, key="absent-volume"),
        json=body,
    )
    foreign = client.post(
        f"/v1/observation-work-orders/{created['workOrderId']}/relative-volume-requests",
        headers=_headers(_OPERATOR_B, key="foreign-volume"),
        json=body,
    )

    assert (absent.status_code, foreign.status_code) == (404, 404)
    assert (
        absent.json()["detail"]
        == foreign.json()["detail"]
        == "relative-volume request was not found"
    )


def test_external_operations_are_idempotent_and_do_not_mutate_sealed_work_order(
    tmp_path: Path,
) -> None:
    client, store, _, journal_path = _api(tmp_path)
    created = _create_external(client)
    work_order_id = str(created["workOrderId"])
    before = store.get(work_order_id, organization_id="org-a")
    assert before is not None
    before_json = before.model_dump_json(by_alias=True)

    initial = client.get(
        f"/v1/observation-work-orders/{work_order_id}/operations",
        headers=_headers(_OPERATOR_A),
    )
    assert initial.status_code == 200, initial.text
    initial_body = initial.json()
    assert {**initial_body, "updatedAt": created["createdAt"]} == {
        "schemaVersion": "1.0",
        "organizationId": "org-a",
        "siteId": "site-a",
        "workOrderId": work_order_id,
        "operationsRevision": 1,
        "workflowStatus": "OPEN",
        "assigneePrincipalId": None,
        "dueAt": None,
        "closedAt": None,
        "closedBy": None,
        "closeNote": None,
        "updatedAt": created["createdAt"],
        "updatedBy": "operator-a",
    }
    assert datetime.fromisoformat(
        initial_body["updatedAt"].replace("Z", "+00:00")
    ) == datetime.fromisoformat(str(created["createdAt"]))

    assignment_body = {"expectedOperationsRevision": 1, "action": "ASSIGN_TO_ME"}
    assigned = client.post(
        f"/v1/observation-work-orders/{work_order_id}/operations/assignment",
        headers=_headers(_OPERATOR_A, key="assignment-retry"),
        json=assignment_body,
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["operationsRevision"] == 2
    assert assigned.json()["assigneePrincipalId"] == "operator-a"

    replayed = client.post(
        f"/v1/observation-work-orders/{work_order_id}/operations/assignment",
        headers=_headers(_OPERATOR_A, key="assignment-retry"),
        json=assignment_body,
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json() == assigned.json()

    conflicting = client.post(
        f"/v1/observation-work-orders/{work_order_id}/operations/assignment",
        headers=_headers(_OPERATOR_A, key="assignment-retry"),
        json={"expectedOperationsRevision": 2, "action": "CLEAR"},
    )
    assert conflicting.status_code == 409

    due = client.put(
        f"/v1/observation-work-orders/{work_order_id}/operations/due-date",
        headers=_headers(_OPERATOR_A, key="due-date"),
        json={"expectedOperationsRevision": 2, "dueAt": "2026-09-11T09:00:00+09:00"},
    )
    assert due.status_code == 200, due.text
    assert datetime.fromisoformat(due.json()["dueAt"].replace("Z", "+00:00")) == datetime(
        2026, 9, 11, tzinfo=UTC
    )

    closed = client.post(
        f"/v1/observation-work-orders/{work_order_id}/operations/close",
        headers=_headers(_OPERATOR_A, key="close"),
        json={"expectedOperationsRevision": 3, "note": "현장 확인 완료"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["workflowStatus"] == "CLOSED"
    assert closed.json()["closedBy"] == "operator-a"
    assert closed.json()["closeNote"] == "현장 확인 완료"

    reopened = client.post(
        f"/v1/observation-work-orders/{work_order_id}/operations/reopen",
        headers=_headers(_OPERATOR_A, key="reopen"),
        json={"expectedOperationsRevision": 4},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["workflowStatus"] == "OPEN"
    assert reopened.json()["closedAt"] is None

    after = store.get(work_order_id, organization_id="org-a")
    assert after is not None
    assert after.model_dump_json(by_alias=True) == before_json
    durable = journal_path.read_text(encoding="utf-8")
    assert "assignment-retry" not in durable and "due-date" not in durable

    store._journal.close()  # noqa: SLF001 -- restart projection contract
    restored = ObservationWorkOrderStore(
        DurableJournal(journal_path),
        site_exists=lambda site_id, organization_id: (
            site_id == "site-a" and organization_id == "org-a"
        ),
    )
    restored_operations = restored.get_operations(work_order_id, organization_id="org-a")
    assert restored_operations is not None
    assert restored_operations.model_dump(by_alias=True, mode="json") == reopened.json()
    restored._journal.close()  # noqa: SLF001 -- test owns replay journal


def test_operations_bulk_scope_preserves_legacy_unknown_and_rejects_invalid_human_intent(
    tmp_path: Path,
) -> None:
    client, _, _, _ = _api(tmp_path)
    external = _create_external(client)
    work_order_id = str(external["workOrderId"])
    managed = client.post(
        "/v1/sites/site-a/observation-work-orders",
        headers=_headers(_OPERATOR_A),
        json={"name": "관리형 이전 작업", "workAreaIds": ["area-b"]},
    )
    assert managed.status_code == 201, managed.text

    bulk = client.get(
        "/v1/observation-work-order-operations?siteId=site-a",
        headers=_headers(_OPERATOR_A),
    )
    assert bulk.status_code == 200, bulk.text
    by_order = {item["workOrderId"]: item for item in bulk.json()["operations"]}
    assert by_order[work_order_id]["workflowStatus"] == "OPEN"
    assert by_order[managed.json()["workOrderId"]] == {
        "schemaVersion": "1.0",
        "organizationId": "org-a",
        "siteId": "site-a",
        "workOrderId": managed.json()["workOrderId"],
        "operationsRevision": 0,
        "workflowStatus": "UNSPECIFIED",
        "assigneePrincipalId": None,
        "dueAt": None,
        "closedAt": None,
        "closedBy": None,
        "closeNote": None,
        "updatedAt": None,
        "updatedBy": None,
    }

    assert (
        client.get(
            f"/v1/observation-work-orders/{work_order_id}/operations",
            headers=_headers(_OPERATOR_B),
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/v1/observation-work-order-operations?siteId=site-b",
            headers=_headers(_OPERATOR_A),
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/observation-work-orders/{work_order_id}/operations/assignment",
            headers=_headers(_VIEWER_A, key="viewer"),
            json={"expectedOperationsRevision": 1, "action": "ASSIGN_TO_ME"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/observation-work-orders/{work_order_id}/operations/assignment",
            headers=_headers(_OPERATOR_A, key="bad-action"),
            json={
                "expectedOperationsRevision": 1,
                "action": "ASSIGN_TO_ME",
                "assigneePrincipalId": "other",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/v1/observation-work-orders/{managed.json()['workOrderId']}/operations/close",
            headers=_headers(_OPERATOR_A, key="managed"),
            json={
                "expectedOperationsRevision": 0,
                "note": "관리형 작업은 이 표면에서 종료하지 않는다",
            },
        ).status_code
        == 409
    )


def test_operations_reject_stale_revision_and_close_field_pair_violations(tmp_path: Path) -> None:
    client, _, _, _ = _api(tmp_path)
    external = _create_external(client)
    work_order_id = str(external["workOrderId"])

    stale = client.put(
        f"/v1/observation-work-orders/{work_order_id}/operations/due-date",
        headers=_headers(_OPERATOR_A, key="stale"),
        json={"expectedOperationsRevision": 0, "dueAt": "2026-09-11T00:00:00Z"},
    )
    assert stale.status_code == 409
    empty_close = client.post(
        f"/v1/observation-work-orders/{work_order_id}/operations/close",
        headers=_headers(_OPERATOR_A, key="empty-close"),
        json={"expectedOperationsRevision": 1, "note": ""},
    )
    assert empty_close.status_code == 422
    close = client.post(
        f"/v1/observation-work-orders/{work_order_id}/operations/close",
        headers=_headers(_OPERATOR_A, key="close"),
        json={"expectedOperationsRevision": 1, "note": "완료"},
    )
    assert close.status_code == 200, close.text
    assert close.json()["closedAt"] is not None
    assert close.json()["closedBy"] == "operator-a"
    assert close.json()["closeNote"] == "완료"
    assert (
        client.post(
            f"/v1/observation-work-orders/{work_order_id}/operations/reopen",
            headers=_headers(_OPERATOR_A, key="reopen-extra"),
            json={"expectedOperationsRevision": 2, "note": "금지"},
        ).status_code
        == 422
    )


@pytest.mark.parametrize("corruption", ["revision-gap", "foreign-scope", "reused-key-hash"])
def test_operations_replay_rejects_revision_scope_and_idempotency_corruption(
    tmp_path: Path, corruption: str
) -> None:
    client, store, _, journal_path = _api(tmp_path)
    work_order_id = str(_create_external(client)["workOrderId"])
    assigned = client.post(
        f"/v1/observation-work-orders/{work_order_id}/operations/assignment",
        headers=_headers(_OPERATOR_A, key="assignment"),
        json={"expectedOperationsRevision": 1, "action": "ASSIGN_TO_ME"},
    )
    assert assigned.status_code == 200, assigned.text
    due = client.put(
        f"/v1/observation-work-orders/{work_order_id}/operations/due-date",
        headers=_headers(_OPERATOR_A, key="due"),
        json={"expectedOperationsRevision": 2, "dueAt": "2026-09-11T00:00:00Z"},
    )
    assert due.status_code == 200, due.text

    records = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    operations_event = records[-1]
    if corruption == "revision-gap":
        operations_event["operations"]["operationsRevision"] = 4
    elif corruption == "foreign-scope":
        operations_event["operations"]["organizationId"] = "org-b"
    else:
        operations_event["idempotency"]["keyHash"] = records[-2]["idempotency"]["keyHash"]
    corrupt_path = tmp_path / f"corrupt-{corruption}.jsonl"
    corrupt_path.write_text(
        "".join(f"{json.dumps(record, ensure_ascii=False)}\n" for record in records),
        encoding="utf-8",
    )

    with pytest.raises(ObservationWorkOrderStoreRecoveryError):
        ObservationWorkOrderStore(
            DurableJournal(corrupt_path),
            site_exists=lambda site_id, organization_id: (
                site_id == "site-a" and organization_id == "org-a"
            ),
        )
    store._journal.close()  # noqa: SLF001 -- test owns replay journal


def test_operations_allow_retained_external_successor_binding_and_close_guard(
    tmp_path: Path,
) -> None:
    _journal, store, authority = _store_with_source(tmp_path)
    successor = _approve(store, authority).successor_work_order
    before = successor.model_dump_json(by_alias=True)

    closed = store.close_operations(
        successor.work_order_id,
        organization_id="org-1",
        expected_operations_revision=0,
        note="검토 완료",
        actor="approver-1",
        idempotency_key="successor-close",
        now=datetime(2026, 9, 9, 3, tzinfo=UTC),
    )

    assert closed.operations_revision == 1
    assert closed.workflow_status.value == "CLOSED"
    assert (
        store.get(successor.work_order_id, organization_id="org-1").model_dump_json(  # type: ignore[union-attr]
            by_alias=True
        )
        == before
    )
    with pytest.raises(RuntimeError, match="EXTERNAL_WORKFLOW_CLOSED"):
        store.assert_new_external_intent_allowed(successor.work_order_id, organization_id="org-1")


def test_closed_external_work_order_blocks_new_registration_but_keeps_exact_retry(
    tmp_path: Path,
) -> None:
    client, _, _, _ = _reconstruction_client(tmp_path)
    work_orders = cast(Any, client.app).state.external_reconstruction_test_work_orders
    external = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="닫힌 외부 관측",
        work_area_ids=["wa-a"],
        schedule_id=None,
        execution_mode="EXTERNAL_RECONSTRUCTION",
        idempotency_key="closed-registration-create",
        actor="operator-a",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    path = (
        f"/v1/observation-work-orders/{external.work_order_id}/external-reconstruction-submissions"
    )
    payload = _reconstruction_submission(
        work_order_id=external.work_order_id,
        epoch_id=observation_epoch_id(external),
        submission_id="closed-registration",
    )
    payload["inputDeclaration"]["captureStartedAt"] = "2026-09-10T00:00:00Z"
    payload["inputDeclaration"]["captureEndedAt"] = "2026-09-10T00:10:00Z"
    payload["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(payload)

    work_orders.close_operations(
        external.work_order_id,
        organization_id="org-a",
        expected_operations_revision=1,
        note="운영 종료",
        actor="operator-a",
        idempotency_key="close-before-registration",
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
    )
    blocked = client.post(
        path, headers={"Authorization": f"Bearer {_RECONSTRUCTION_TOKEN}"}, json=payload
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "EXTERNAL_WORKFLOW_CLOSED"

    work_orders.reopen_operations(
        external.work_order_id,
        organization_id="org-a",
        expected_operations_revision=2,
        actor="operator-a",
        idempotency_key="reopen-registration",
        now=datetime(2026, 9, 10, 2, tzinfo=UTC),
    )
    created = client.post(
        path, headers={"Authorization": f"Bearer {_RECONSTRUCTION_TOKEN}"}, json=payload
    )
    assert created.status_code == 201, created.text

    work_orders.close_operations(
        external.work_order_id,
        organization_id="org-a",
        expected_operations_revision=3,
        note="다시 종료",
        actor="operator-a",
        idempotency_key="close-after-registration",
        now=datetime(2026, 9, 10, 3, tzinfo=UTC),
    )
    retry = client.post(
        path, headers={"Authorization": f"Bearer {_RECONSTRUCTION_TOKEN}"}, json=payload
    )
    assert retry.status_code == 201
    assert retry.json() == created.json()


def test_closed_external_work_order_leaves_site_active_projection_and_next_action(
    tmp_path: Path,
) -> None:
    client, store, site_store, _ = _api(tmp_path)
    created = _create_external(client)
    work_order_id = str(created["workOrderId"])

    # The focused operation fixture intentionally mounts no workspace router;
    # exercise the actual projector against the exact same durable stores.
    projector = SiteWorkspaceProjector(
        site_store=site_store,
        work_order_store=store,
        processing_job_store=None,
        event_store=None,
    )
    before = projector.project("site-a", organization_id="org-a")
    assert before.active_work_order_count == 1
    assert before.next_action.href == f"/field/work-orders/{work_order_id}"

    closed = client.post(
        f"/v1/observation-work-orders/{work_order_id}/operations/close",
        headers=_headers(_OPERATOR_A, key="close-for-site-projection"),
        json={"expectedOperationsRevision": 1, "note": "운영 확인 완료"},
    )
    assert closed.status_code == 200, closed.text

    after = projector.project("site-a", organization_id="org-a")
    assert after.active_work_order_count == 0
    assert after.next_action.href != f"/field/work-orders/{work_order_id}"
