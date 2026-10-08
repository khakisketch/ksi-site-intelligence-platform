"""Team operations metadata and recipient-only in-app work notices."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
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
from ksi_core.observation_work_orders import (
    ObservationWorkOrderStore,
    WorkOrderOperationsAssignmentAction,
)
from ksi_core.organization_work_roster import (
    OrganizationWorkRoleHint,
    OrganizationWorkRosterStatus,
    OrganizationWorkRosterStore,
)
from ksi_event_contracts.observation_work_order import ObservationWorkOrderExecutionMode


def test_roster_admin_records_active_member_without_granting_identity_permissions(
    tmp_path: Path,
) -> None:
    store = OrganizationWorkRosterStore(DurableJournal(tmp_path / "roster.jsonl"))

    member = store.put_member(
        organization_id="org-a",
        principal_id="operator-b",
        expected_revision=0,
        display_name="현장 담당자 B",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="roster-create",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )

    assert member.principal_id == "operator-b"
    assert member.organization_id == "org-a"
    assert member.revision == 1
    assert store.is_assignable_member("operator-b", organization_id="org-a")
    assert not store.is_assignable_member("operator-b", organization_id="org-b")


def test_roster_replays_and_retries_before_later_revision_preconditions(tmp_path: Path) -> None:
    journal_path = tmp_path / "roster-schema-version.jsonl"
    first = OrganizationWorkRosterStore(DurableJournal(journal_path))
    created = first.put_member(
        organization_id="org-a",
        principal_id="operator-b",
        expected_revision=0,
        display_name="현장 담당자 B",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="original-request",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    first.put_member(
        organization_id="org-a",
        principal_id="operator-b",
        expected_revision=1,
        display_name="현장 담당자 B (비활성)",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.INACTIVE,
        actor="admin-a",
        idempotency_key="later-update",
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
    )
    first._journal.close()  # noqa: SLF001 -- test owns the replay journal

    resumed = OrganizationWorkRosterStore(DurableJournal(journal_path))
    retry = resumed.put_member(
        organization_id="org-a",
        principal_id="operator-b",
        expected_revision=0,
        display_name="현장 담당자 B",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="original-request",
        now=datetime(2026, 9, 10, 2, tzinfo=UTC),
    )

    assert retry == created
    resumed_member = resumed.get_member("operator-b", organization_id="org-a")
    assert resumed_member is not None
    assert resumed_member.revision == 2
    with pytest.raises(RuntimeError, match="ROSTER_IDEMPOTENCY_CONFLICT"):
        resumed.put_member(
            organization_id="org-a",
            principal_id="operator-b",
            expected_revision=0,
            display_name="다른 본문",
            role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
            status=OrganizationWorkRosterStatus.ACTIVE,
            actor="admin-a",
            idempotency_key="original-request",
            now=datetime(2026, 9, 10, 2, tzinfo=UTC),
        )


def test_member_assignment_requires_active_same_organization_roster_entry(tmp_path: Path) -> None:
    roster = OrganizationWorkRosterStore(DurableJournal(tmp_path / "roster.jsonl"))
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            (site_id, organization_id) == ("site-a", "org-a")
        ),
        operations_coordinator=roster.coordinator,
        assignment_member_is_active=roster.is_assignable_member,
    )
    order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="외부 관측",
        work_area_ids=["area-a"],
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        actor="operator-a",
        idempotency_key="create",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    roster.put_member(
        organization_id="org-a",
        principal_id="operator-b",
        expected_revision=0,
        display_name="현장 담당자 B",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )

    assigned = work_orders.assign_operations_to_member(
        order.work_order_id,
        organization_id="org-a",
        expected_operations_revision=1,
        action=WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER,
        assignee_principal_id="operator-b",
        actor="operator-a",
        idempotency_key="assign-member",
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
    )

    assert assigned.assignee_principal_id == "operator-b"


def test_member_assignment_collapses_unknown_and_foreign_roster_targets(tmp_path: Path) -> None:
    roster = OrganizationWorkRosterStore(DurableJournal(tmp_path / "roster.jsonl"))
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            (site_id, organization_id) == ("site-a", "org-a")
        ),
        operations_coordinator=roster.coordinator,
        assignment_member_is_active=roster.is_assignable_member,
    )
    order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="외부 관측",
        work_area_ids=["area-a"],
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        actor="operator-a",
        idempotency_key="create",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    roster.put_member(
        organization_id="org-b",
        principal_id="foreign-operator",
        expected_revision=0,
        display_name="다른 조직 담당자",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-b",
        idempotency_key="foreign-member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    roster.put_member(
        organization_id="org-a",
        principal_id="viewer-a",
        expected_revision=0,
        display_name="조직 내 뷰어",
        role_hint=OrganizationWorkRoleHint.VIEWER,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="viewer-member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )

    def assignment_failure(target: str, idempotency_key: str) -> str:
        with pytest.raises(LookupError) as raised:
            work_orders.assign_operations_to_member(
                order.work_order_id,
                organization_id="org-a",
                expected_operations_revision=1,
                action=WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER,
                assignee_principal_id=target,
                actor="operator-a",
                idempotency_key=idempotency_key,
                now=datetime(2026, 9, 10, 1, tzinfo=UTC),
            )
        return str(raised.value)

    assert (
        assignment_failure("missing-operator", "unknown")
        == assignment_failure("foreign-operator", "foreign")
        == assignment_failure("viewer-a", "viewer")
    )


def test_member_assignment_http_hides_unknown_and_foreign_targets(tmp_path: Path) -> None:
    from ksi_core.observation_work_orders import build_observation_work_order_router

    roster = OrganizationWorkRosterStore(DurableJournal(tmp_path / "roster.jsonl"))
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            (site_id, organization_id) == ("site-a", "org-a")
        ),
        operations_coordinator=roster.coordinator,
        assignment_member_is_active=roster.is_assignable_member,
    )
    order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="외부 관측",
        work_area_ids=["area-a"],
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        actor="operator-a",
        idempotency_key="create",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    roster.put_member(
        organization_id="org-b",
        principal_id="foreign-operator",
        expected_revision=0,
        display_name="다른 조직 담당자",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-b",
        idempotency_key="foreign-member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    app = FastAPI()
    mount_auth(app, AuthRegistry([_token("operator", "operator-a", Role.FIELD_OPERATOR)]))
    app.include_router(build_observation_work_order_router(work_orders))
    client = TestClient(app, raise_server_exceptions=False)

    def post_assignment(target: str, key: str) -> Any:
        return client.post(
            f"/v1/observation-work-orders/{order.work_order_id}/operations/assignment",
            headers={"Authorization": "Bearer operator", "Idempotency-Key": key},
            json={
                "expectedOperationsRevision": 1,
                "action": "ASSIGN_TO_MEMBER",
                "assigneePrincipalId": target,
            },
        )

    absent = post_assignment("missing-operator", "unknown")
    foreign = post_assignment("foreign-operator", "foreign")

    assert (absent.status_code, foreign.status_code) == (404, 404)
    assert (
        absent.json()["detail"]
        == foreign.json()["detail"]
        == "work assignment target was not found"
    )


def test_member_assignment_retry_survives_later_roster_deactivation(tmp_path: Path) -> None:
    roster = OrganizationWorkRosterStore(DurableJournal(tmp_path / "roster.jsonl"))
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            (site_id, organization_id) == ("site-a", "org-a")
        ),
        operations_coordinator=roster.coordinator,
        assignment_member_is_active=roster.is_assignable_member,
    )
    roster.put_member(
        organization_id="org-a",
        principal_id="operator-b",
        expected_revision=0,
        display_name="현장 담당자 B",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="member-active",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="외부 관측",
        work_area_ids=["area-a"],
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        actor="operator-a",
        idempotency_key="create",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    initial = work_orders.assign_operations_to_member(
        order.work_order_id,
        organization_id="org-a",
        expected_operations_revision=1,
        action=WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER,
        assignee_principal_id="operator-b",
        actor="operator-a",
        idempotency_key="assignment",
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
    )
    roster.put_member(
        organization_id="org-a",
        principal_id="operator-b",
        expected_revision=1,
        display_name="현장 담당자 B",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.INACTIVE,
        actor="admin-a",
        idempotency_key="member-inactive",
        now=datetime(2026, 9, 10, 2, tzinfo=UTC),
    )

    retried = work_orders.assign_operations_to_member(
        order.work_order_id,
        organization_id="org-a",
        expected_operations_revision=1,
        action=WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER,
        assignee_principal_id="operator-b",
        actor="operator-a",
        idempotency_key="assignment",
        now=datetime(2026, 9, 10, 3, tzinfo=UTC),
    )

    assert retried == initial
    with pytest.raises(LookupError, match="assignment target"):
        work_orders.assign_operations_to_member(
            order.work_order_id,
            organization_id="org-a",
            expected_operations_revision=2,
            action=WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER,
            assignee_principal_id="operator-b",
            actor="operator-a",
            idempotency_key="new-assignment",
            now=datetime(2026, 9, 10, 3, tzinfo=UTC),
        )


def test_assignment_notice_replays_with_deterministic_recipient_reference(tmp_path: Path) -> None:
    from ksi_core.work_inbox import WorkInboxStore

    roster = OrganizationWorkRosterStore(DurableJournal(tmp_path / "roster.jsonl"))
    orders_path = tmp_path / "orders.jsonl"
    work_orders = ObservationWorkOrderStore(
        DurableJournal(orders_path),
        site_exists=lambda site_id, organization_id: (
            (site_id, organization_id) == ("site-a", "org-a")
        ),
        operations_coordinator=roster.coordinator,
        assignment_member_is_active=roster.is_assignable_member,
    )
    roster.put_member(
        organization_id="org-a",
        principal_id="operator-b",
        expected_revision=0,
        display_name="현장 담당자 B",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="외부 관측",
        work_area_ids=["area-a"],
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        actor="operator-a",
        idempotency_key="create",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    work_orders.assign_operations_to_member(
        order.work_order_id,
        organization_id="org-a",
        expected_operations_revision=1,
        action=WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER,
        assignee_principal_id="operator-b",
        actor="operator-a",
        idempotency_key="assignment",
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
    )
    first = WorkInboxStore(
        DurableJournal(tmp_path / "inbox-first.jsonl"), work_orders=work_orders, roster=roster
    ).list_for_recipient(
        organization_id="org-a", recipient_principal_id="operator-b", unread_only=False
    )
    work_orders._journal.close()  # noqa: SLF001 -- test owns the replay journal
    restarted = ObservationWorkOrderStore(
        DurableJournal(orders_path),
        site_exists=lambda site_id, organization_id: (
            (site_id, organization_id) == ("site-a", "org-a")
        ),
        operations_coordinator=roster.coordinator,
        assignment_member_is_active=roster.is_assignable_member,
    )
    second = WorkInboxStore(
        DurableJournal(tmp_path / "inbox-second.jsonl"), work_orders=restarted, roster=roster
    ).list_for_recipient(
        organization_id="org-a", recipient_principal_id="operator-b", unread_only=False
    )

    assert first.items[0].notification_ref == second.items[0].notification_ref
    assert second.items[0].target.work_order_id == order.work_order_id


def _token(
    token: str,
    principal_id: str,
    role: Role,
    *,
    allowed_site_ids: frozenset[str] | None = None,
    allowed_work_area_ids: frozenset[str] | None = None,
) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        principal=Principal(
            principal_id=principal_id,
            kind=PrincipalKind.OPERATOR,
            role=role,
            device_id=None,
            organization_id="org-a",
            allowed_site_ids=allowed_site_ids,
            allowed_work_area_ids=allowed_work_area_ids,
        ),
    )


def test_roster_api_allows_admin_update_and_hides_inactive_from_normal_read(tmp_path: Path) -> None:
    from ksi_core.organization_work_roster import build_organization_work_roster_router

    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [_token("admin", "admin-a", Role.ADMIN), _token("viewer", "viewer-a", Role.VIEWER)]
        ),
    )
    app.include_router(
        build_organization_work_roster_router(
            OrganizationWorkRosterStore(DurableJournal(tmp_path / "roster.jsonl"))
        )
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin", "Idempotency-Key": "member-create"}

    created = client.put(
        "/v1/organization-work-roster/operator-b",
        headers=headers,
        json={
            "expectedRevision": 0,
            "displayName": "현장 담당자 B",
            "roleHint": "FIELD_OPERATOR",
            "status": "INACTIVE",
        },
    )

    assert created.status_code == 200, created.text
    assert client.get(
        "/v1/organization-work-roster", headers={"Authorization": "Bearer viewer"}
    ).json() == {"members": []}
    admin_list = client.get(
        "/v1/organization-work-roster?includeInactive=true",
        headers={"Authorization": "Bearer admin"},
    )
    assert admin_list.status_code == 200
    assert admin_list.json()["members"][0]["principalId"] == "operator-b"


def test_member_assignment_is_a_recipient_only_inbox_notice(tmp_path: Path) -> None:
    from ksi_core.work_inbox import WorkInboxStore

    roster = OrganizationWorkRosterStore(DurableJournal(tmp_path / "roster.jsonl"))
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            (site_id, organization_id) == ("site-a", "org-a")
        ),
        operations_coordinator=roster.coordinator,
        assignment_member_is_active=roster.is_assignable_member,
    )
    roster.put_member(
        organization_id="org-a",
        principal_id="operator-b",
        expected_revision=0,
        display_name="현장 담당자 B",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="외부 관측",
        work_area_ids=["area-a"],
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        actor="operator-a",
        idempotency_key="create",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    work_orders.assign_operations_to_member(
        order.work_order_id,
        organization_id="org-a",
        expected_operations_revision=1,
        action=WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER,
        assignee_principal_id="operator-b",
        actor="operator-a",
        idempotency_key="assignment",
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
    )
    inbox = WorkInboxStore(
        DurableJournal(tmp_path / "inbox.jsonl"),
        work_orders=work_orders,
        roster=roster,
    )

    notices = inbox.list_for_recipient(
        organization_id="org-a", recipient_principal_id="operator-b", unread_only=False
    )

    assert len(notices.items) == 1
    assert notices.items[0].target.work_order_id == order.work_order_id
    assert notices.items[0].unread


def test_mapped_inbox_filters_assignments_before_pagination_and_rechecks_read_retries(
    tmp_path: Path,
) -> None:
    from ksi_core.work_inbox import WorkInboxStore

    roster = OrganizationWorkRosterStore(DurableJournal(tmp_path / "roster.jsonl"))
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda _site_id, _organization_id: True,
        operations_coordinator=roster.coordinator,
        assignment_member_is_active=roster.is_assignable_member,
    )
    roster.put_member(
        organization_id="org-a",
        principal_id="operator-b",
        expected_revision=0,
        display_name="현장 담당자 B",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    orders = [
        work_orders.create_work_order(
            organization_id="org-a",
            site_id=site_id,
            name=name,
            work_area_ids=areas,
            schedule_id=None,
            execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
            actor="operator-a",
            idempotency_key=f"create-{name}",
            now=datetime(2026, 9, 10, tzinfo=UTC),
        )
        for site_id, name, areas in (
            ("site-a", "allowed", ["area-a"]),
            ("site-a", "hidden-area", ["area-b"]),
            ("site-a", "mixed", ["area-a", "area-b"]),
            ("site-b", "hidden-site", ["area-a"]),
        )
    ]
    for index, order in enumerate(orders, start=1):
        work_orders.assign_operations_to_member(
            order.work_order_id,
            organization_id="org-a",
            expected_operations_revision=1,
            action=WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER,
            assignee_principal_id="operator-b",
            actor="operator-a",
            idempotency_key=f"assign-{order.work_order_id}",
            now=datetime(2026, 9, 10, index, tzinfo=UTC),
        )
    inbox = WorkInboxStore(
        DurableJournal(tmp_path / "inbox.jsonl"), work_orders=work_orders, roster=roster
    )
    scoped_token = _token(
        "scoped-recipient",
        "operator-b",
        Role.FIELD_OPERATOR,
        allowed_site_ids=frozenset({"site-a"}),
        allowed_work_area_ids=frozenset({"area-a"}),
    )
    client = _share_app(inbox, tokens=[scoped_token])

    page = client.get(
        "/v1/work-inbox?limit=1", headers={"Authorization": "Bearer scoped-recipient"}
    )

    assert page.status_code == 200, page.text
    assert [item["target"]["workOrderId"] for item in page.json()["items"]] == [
        orders[0].work_order_id
    ]
    assert page.json()["nextCursor"] is None
    notification_ref = page.json()["items"][0]["notificationRef"]
    headers = {"Authorization": "Bearer scoped-recipient", "Idempotency-Key": "read-once"}
    read = client.post(f"/v1/work-inbox/{notification_ref}/read", headers=headers)
    assert read.status_code == 200

    assert isinstance(client.app, FastAPI)
    client.app.state.auth_registry = AuthRegistry(
        [
            _token(
                "scoped-recipient",
                "operator-b",
                Role.FIELD_OPERATOR,
                allowed_site_ids=frozenset({"site-a"}),
                allowed_work_area_ids=frozenset(),
            )
        ]
    )
    revoked_page = client.get(
        "/v1/work-inbox", headers={"Authorization": "Bearer scoped-recipient"}
    )
    assert revoked_page.status_code == 200, revoked_page.text
    assert revoked_page.json()["items"] == []
    assert (
        client.post(f"/v1/work-inbox/{notification_ref}/read", headers=headers).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/work-inbox/{notification_ref}/read",
            headers={"Authorization": "Bearer scoped-recipient", "Idempotency-Key": "new-key"},
        ).status_code
        == 404
    )


class _ExactReportResolver:
    def resolve_historical_report_ref(
        self, report_ref: str, *, organization_id: str, now: datetime | None = None
    ) -> Any | None:
        del now
        if (report_ref, organization_id) != ("report-a", "org-a"):
            return None
        return SimpleNamespace(
            request=SimpleNamespace(zone_snapshot=SimpleNamespace(site_id="site-a")),
            report=SimpleNamespace(report_digest="sha256:" + "a" * 64),
        )


class _WorkOrderBoundReportResolver:
    def __init__(self, work_order_id: str, *, work_area_id: str = "area-b") -> None:
        self.work_order_id = work_order_id
        self.work_area_id = work_area_id

    def resolve_historical_report_ref(
        self, report_ref: str, *, organization_id: str, now: datetime | None = None
    ) -> Any | None:
        del now
        if (report_ref, organization_id) != ("report-a", "org-a"):
            return None
        return SimpleNamespace(
            request=SimpleNamespace(
                current_work_order_id=self.work_order_id,
                zone_snapshot=SimpleNamespace(
                    organization_id="org-a",
                    site_id="site-a",
                    work_area_id=self.work_area_id,
                ),
            ),
            report=SimpleNamespace(report_digest="sha256:" + "a" * 64),
        )


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fingerprint(value: dict[str, str | int]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
    )


def _empty_inbox_dependencies(
    tmp_path: Path,
) -> tuple[OrganizationWorkRosterStore, ObservationWorkOrderStore]:
    roster = OrganizationWorkRosterStore(DurableJournal(tmp_path / "roster.jsonl"))
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda _site_id, _organization_id: True,
        operations_coordinator=roster.coordinator,
        assignment_member_is_active=roster.is_assignable_member,
    )
    return roster, work_orders


def _assert_inbox_replay_rejected(tmp_path: Path, record: dict[str, object]) -> None:
    from ksi_core.work_inbox import WorkInboxStore, WorkInboxStoreRecoveryError

    inbox_path = tmp_path / "inbox.jsonl"
    writer = DurableJournal(inbox_path)
    writer.append(record)
    writer.close()
    roster, work_orders = _empty_inbox_dependencies(tmp_path)

    with pytest.raises(WorkInboxStoreRecoveryError):
        WorkInboxStore(DurableJournal(inbox_path), work_orders=work_orders, roster=roster)


def _share_record(
    *,
    schema_version: str = "1.0",
    created_at: str = "2026-09-10T00:00:00+00:00",
    fingerprint: str | None = None,
) -> dict[str, object]:
    share = {
        "schemaVersion": schema_version,
        "shareRef": "external-report-share-a",
        "organizationId": "org-a",
        "senderPrincipalId": "operator-a",
        "recipientPrincipalId": "viewer-b",
        "siteId": "site-a",
        "reportRef": "report-a",
        "reportDigest": "sha256:" + "a" * 64,
        "createdAt": created_at,
    }
    return {
        "kind": "external-report-shared",
        "ts": created_at,
        "actor": "operator-a",
        "share": share,
        "idempotency": {
            "keyHash": _digest("share-key"),
            "fingerprint": fingerprint
            or _fingerprint({"recipientPrincipalId": "viewer-b", "reportRef": "report-a"}),
        },
    }


def _read_receipt_record(
    *,
    read_at: str = "2026-09-10T00:00:00+00:00",
    fingerprint: str | None = None,
) -> dict[str, object]:
    receipt = {
        "schemaVersion": "1.0",
        "organizationId": "org-a",
        "recipientPrincipalId": "viewer-b",
        "notificationRef": "work-inbox-share-external-report-share-a",
        "readAt": read_at,
    }
    return {
        "kind": "work-inbox-notification-read",
        "ts": read_at,
        "actor": "viewer-b",
        "receipt": receipt,
        "idempotency": {
            "keyHash": _digest("receipt-key"),
            "fingerprint": fingerprint
            or _fingerprint({"notificationRef": "work-inbox-share-external-report-share-a"}),
        },
    }


def test_work_inbox_cursor_resolves_before_unread_filter_after_cursor_was_read(
    tmp_path: Path,
) -> None:
    from ksi_core.work_inbox import WorkInboxStore

    roster = OrganizationWorkRosterStore(DurableJournal(tmp_path / "roster.jsonl"))
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda _site_id, _organization_id: True,
        operations_coordinator=roster.coordinator,
        assignment_member_is_active=roster.is_assignable_member,
    )
    roster.put_member(
        organization_id="org-a",
        principal_id="viewer-b",
        expected_revision=0,
        display_name="검토자 B",
        role_hint=OrganizationWorkRoleHint.VIEWER,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )

    class MultiReportResolver:
        def resolve_historical_report_ref(
            self, report_ref: str, *, organization_id: str, now: datetime | None = None
        ) -> Any | None:
            del now
            if organization_id != "org-a" or report_ref not in {"report-a", "report-b"}:
                return None
            return SimpleNamespace(
                request=SimpleNamespace(zone_snapshot=SimpleNamespace(site_id="site-a")),
                report=SimpleNamespace(report_digest="sha256:" + "a" * 64),
            )

    inbox = WorkInboxStore(
        DurableJournal(tmp_path / "inbox.jsonl"),
        work_orders=work_orders,
        roster=roster,
        report_resolver=MultiReportResolver(),
    )
    inbox.share_report(
        "report-a",
        organization_id="org-a",
        recipient_principal_id="viewer-b",
        actor="operator-a",
        idempotency_key="share-a",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    inbox.share_report(
        "report-b",
        organization_id="org-a",
        recipient_principal_id="viewer-b",
        actor="operator-a",
        idempotency_key="share-b",
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
    )

    first_page = inbox.list_for_recipient(
        organization_id="org-a",
        recipient_principal_id="viewer-b",
        unread_only=True,
        limit=1,
    )
    assert first_page.next_cursor == first_page.items[0].notification_ref
    inbox.mark_read(
        first_page.items[0].notification_ref,
        organization_id="org-a",
        recipient_principal_id="viewer-b",
        idempotency_key="read-first",
        now=datetime(2026, 9, 10, 2, tzinfo=UTC),
    )

    second_page = inbox.list_for_recipient(
        organization_id="org-a",
        recipient_principal_id="viewer-b",
        unread_only=True,
        after=first_page.next_cursor,
        limit=1,
    )

    assert [item.target.report_ref for item in second_page.items] == ["report-a"]


@pytest.mark.parametrize(
    "record",
    [
        _share_record(schema_version="9.9"),
        _share_record(created_at="2026-09-10T00:00:00"),
        _share_record(fingerprint=_digest("wrong-share-fingerprint")),
        _read_receipt_record(read_at="2026-09-10T00:00:00"),
        _read_receipt_record(fingerprint=_digest("wrong-read-fingerprint")),
        _read_receipt_record(),
    ],
    ids=[
        "share-schema-version",
        "share-naive-created-at",
        "share-fingerprint",
        "receipt-naive-read-at",
        "receipt-fingerprint",
        "orphan-receipt",
    ],
)
def test_work_inbox_replay_rejects_untrusted_durable_fields(
    tmp_path: Path, record: dict[str, object]
) -> None:
    _assert_inbox_replay_rejected(tmp_path, record)


def test_roster_replay_requires_schema_version_and_semantic_fingerprint(tmp_path: Path) -> None:
    from ksi_core.organization_work_roster import OrganizationWorkRosterStoreRecoveryError

    member = {
        "schemaVersion": "9.9",
        "organizationId": "org-a",
        "principalId": "operator-b",
        "displayName": "현장 담당자 B",
        "roleHint": "FIELD_OPERATOR",
        "status": "ACTIVE",
        "revision": 1,
        "updatedAt": "2026-09-10T00:00:00+00:00",
        "updatedBy": "admin-a",
    }
    record = {
        "kind": "organization-work-roster-member-upserted",
        "ts": "2026-09-10T00:00:00+00:00",
        "actor": "admin-a",
        "member": member,
        "idempotency": {
            "keyHash": _digest("roster-key"),
            "fingerprint": _fingerprint(
                {
                    "displayName": "현장 담당자 B",
                    "expectedRevision": 0,
                    "principalId": "operator-b",
                    "roleHint": "FIELD_OPERATOR",
                    "status": "ACTIVE",
                }
            ),
        },
    }
    journal_path = tmp_path / "roster.jsonl"
    writer = DurableJournal(journal_path)
    writer.append(record)
    writer.close()

    with pytest.raises(OrganizationWorkRosterStoreRecoveryError):
        OrganizationWorkRosterStore(DurableJournal(journal_path))

    member["schemaVersion"] = "1.0"
    record["idempotency"] = {
        "keyHash": _digest("roster-key"),
        "fingerprint": _digest("wrong-roster-fingerprint"),
    }
    fingerprint_path = tmp_path / "roster-fingerprint.jsonl"
    writer = DurableJournal(fingerprint_path)
    writer.append(record)
    writer.close()

    with pytest.raises(OrganizationWorkRosterStoreRecoveryError):
        OrganizationWorkRosterStore(DurableJournal(fingerprint_path))


def test_exact_report_share_remains_readable_after_recipient_roster_deactivation(
    tmp_path: Path,
) -> None:
    from ksi_core.work_inbox import WorkInboxStore

    roster = OrganizationWorkRosterStore(DurableJournal(tmp_path / "roster.jsonl"))
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda _site_id, _organization_id: True,
        operations_coordinator=roster.coordinator,
        assignment_member_is_active=roster.is_assignable_member,
    )
    roster.put_member(
        organization_id="org-a",
        principal_id="viewer-b",
        expected_revision=0,
        display_name="검토자 B",
        role_hint=OrganizationWorkRoleHint.VIEWER,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="member-create",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    inbox_path = tmp_path / "inbox.jsonl"
    inbox = WorkInboxStore(
        DurableJournal(inbox_path),
        work_orders=work_orders,
        roster=roster,
        report_resolver=_ExactReportResolver(),
    )
    share = inbox.share_report(
        "report-a",
        organization_id="org-a",
        recipient_principal_id="viewer-b",
        actor="operator-a",
        idempotency_key="share",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    roster.put_member(
        organization_id="org-a",
        principal_id="viewer-b",
        expected_revision=1,
        display_name="검토자 B",
        role_hint=OrganizationWorkRoleHint.VIEWER,
        status=OrganizationWorkRosterStatus.INACTIVE,
        actor="admin-a",
        idempotency_key="member-inactivate",
        now=datetime(2026, 9, 10, 1, tzinfo=UTC),
    )

    retry = inbox.share_report(
        "report-a",
        organization_id="org-a",
        recipient_principal_id="viewer-b",
        actor="operator-a",
        idempotency_key="share",
        now=datetime(2026, 9, 10, 2, tzinfo=UTC),
    )
    page = inbox.list_for_recipient(
        organization_id="org-a", recipient_principal_id="viewer-b", unread_only=False
    )
    receipt = inbox.mark_read(
        page.items[0].notification_ref,
        organization_id="org-a",
        recipient_principal_id="viewer-b",
        idempotency_key="read",
        now=datetime(2026, 9, 10, 3, tzinfo=UTC),
    )

    assert retry == share
    assert page.items[0].target.model_dump(by_alias=True) == {
        "kind": "EXTERNAL_REPORT",
        "workOrderId": None,
        "siteId": "site-a",
        "reportRef": "report-a",
    }
    assert receipt.recipient_principal_id == "viewer-b"
    inbox._journal.close()  # noqa: SLF001 -- test owns the replay journal

    # The retained share identity makes the old receipt valid at replay even
    # when the exact report is no longer a currently displayable resource.
    resumed = WorkInboxStore(
        DurableJournal(inbox_path),
        work_orders=work_orders,
        roster=roster,
        report_resolver=None,
    )

    assert resumed._read_receipts[("org-a", "viewer-b", page.items[0].notification_ref)] == receipt  # noqa: SLF001


_SINGLE_REPORT_REF = "external-single-volume-report-a"


class _SingleVolumeReportResolver:
    """A single-volume-only resolver double, scoped like the real store."""

    def resolve_historical_report_ref(
        self, report_ref: str, *, organization_id: str, now: datetime | None = None
    ) -> Any | None:
        del now
        if (report_ref, organization_id) != (_SINGLE_REPORT_REF, "org-a"):
            return None
        return SimpleNamespace(
            request=SimpleNamespace(zone_snapshot=SimpleNamespace(site_id="site-b")),
            report=SimpleNamespace(report_digest="sha256:" + "b" * 64),
        )


def test_external_volume_report_resolver_dispatches_on_single_prefix_only_when_configured() -> (
    None
):
    from ksi_core.domains.sites.external_report_resolver import ExternalVolumeReportResolver

    relative = _ExactReportResolver()
    single = _SingleVolumeReportResolver()

    composite = ExternalVolumeReportResolver(relative=relative, single=single)
    assert composite.resolve_historical_report_ref(
        "report-a", organization_id="org-a"
    ) == relative.resolve_historical_report_ref("report-a", organization_id="org-a")
    assert composite.resolve_historical_report_ref(
        _SINGLE_REPORT_REF, organization_id="org-a"
    ) == single.resolve_historical_report_ref(_SINGLE_REPORT_REF, organization_id="org-a")
    assert composite.uses(relative, single)
    assert not composite.uses(relative, None)
    assert not composite.uses(None, single)

    # A resolver built with no ``single`` argument never recognizes a
    # single-volume ref — exactly today's (pre-SV-3b) behavior.
    relative_only = ExternalVolumeReportResolver(relative=relative)
    assert (
        relative_only.resolve_historical_report_ref(_SINGLE_REPORT_REF, organization_id="org-a")
        is None
    )
    assert relative_only.uses(relative, None)


def test_work_inbox_shares_single_volume_report_and_replay_keeps_it(tmp_path: Path) -> None:
    from ksi_core.domains.sites.external_report_resolver import ExternalVolumeReportResolver
    from ksi_core.work_inbox import WorkInboxStore

    roster, work_orders = _empty_inbox_dependencies(tmp_path)
    roster.put_member(
        organization_id="org-a",
        principal_id="viewer-b",
        expected_revision=0,
        display_name="검토자 B",
        role_hint=OrganizationWorkRoleHint.VIEWER,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    resolver = ExternalVolumeReportResolver(
        relative=_ExactReportResolver(), single=_SingleVolumeReportResolver()
    )
    inbox_path = tmp_path / "inbox.jsonl"
    inbox = WorkInboxStore(
        DurableJournal(inbox_path),
        work_orders=work_orders,
        roster=roster,
        report_resolver=resolver,
    )

    share = inbox.share_report(
        _SINGLE_REPORT_REF,
        organization_id="org-a",
        recipient_principal_id="viewer-b",
        actor="operator-a",
        idempotency_key="share",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    assert share.site_id == "site-b"
    assert share.report_ref == _SINGLE_REPORT_REF
    assert share.report_digest == "sha256:" + "b" * 64

    page = inbox.list_for_recipient(
        organization_id="org-a", recipient_principal_id="viewer-b", unread_only=False
    )
    assert page.items[0].target.model_dump(by_alias=True) == {
        "kind": "EXTERNAL_REPORT",
        "workOrderId": None,
        "siteId": "site-b",
        "reportRef": _SINGLE_REPORT_REF,
    }
    inbox._journal.close()  # noqa: SLF001 -- test owns the replay journal

    resumed = WorkInboxStore(
        DurableJournal(inbox_path),
        work_orders=work_orders,
        roster=roster,
        report_resolver=resolver,
    )
    resumed_page = resumed.list_for_recipient(
        organization_id="org-a", recipient_principal_id="viewer-b", unread_only=False
    )
    assert resumed_page.items[0].target.report_ref == _SINGLE_REPORT_REF
    assert resumed_page.items[0].target.site_id == "site-b"


def test_work_inbox_share_of_foreign_organization_single_volume_ref_is_not_found(
    tmp_path: Path,
) -> None:
    from ksi_core.domains.sites.external_report_resolver import ExternalVolumeReportResolver
    from ksi_core.work_inbox import WorkInboxStore

    roster, work_orders = _empty_inbox_dependencies(tmp_path)
    roster.put_member(
        organization_id="org-b",
        principal_id="viewer-c",
        expected_revision=0,
        display_name="검토자 C",
        role_hint=OrganizationWorkRoleHint.VIEWER,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-b",
        idempotency_key="member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    resolver = ExternalVolumeReportResolver(
        relative=_ExactReportResolver(), single=_SingleVolumeReportResolver()
    )
    inbox = WorkInboxStore(
        DurableJournal(tmp_path / "inbox.jsonl"),
        work_orders=work_orders,
        roster=roster,
        report_resolver=resolver,
    )

    # Fix round 1 (Important): a genuine single-volume miss — not a
    # family-mismatch — must still read with single-family wording, not the
    # relative family's hardcoded text.
    with pytest.raises(LookupError, match="^external single volume report was not found$"):
        inbox.share_report(
            _SINGLE_REPORT_REF,
            organization_id="org-b",
            recipient_principal_id="viewer-c",
            actor="operator-b",
            idempotency_key="share",
            now=datetime(2026, 9, 10, tzinfo=UTC),
        )


def _share_app(store: Any, *, tokens: list[PrincipalTokenRecord] | None = None) -> TestClient:
    from ksi_core.work_inbox import build_work_inbox_router

    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(tokens or [_token("operator", "operator-a", Role.FIELD_OPERATOR)]),
    )
    app.include_router(build_work_inbox_router(store))
    return TestClient(app, raise_server_exceptions=False)


def _foreign_org_token(token: str, principal_id: str, organization_id: str) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        principal=Principal(
            principal_id=principal_id,
            kind=PrincipalKind.OPERATOR,
            role=Role.FIELD_OPERATOR,
            device_id=None,
            organization_id=organization_id,
        ),
    )


def test_mapped_report_shares_and_notifications_require_current_core_work_area_scope(
    tmp_path: Path,
) -> None:
    from ksi_core.work_inbox import WorkInboxStore

    roster, work_orders = _empty_inbox_dependencies(tmp_path)
    roster.put_member(
        organization_id="org-a",
        principal_id="recipient-b",
        expected_revision=0,
        display_name="검토자 B",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="restricted report work order",
        work_area_ids=["area-b"],
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        actor="operator-a",
        idempotency_key="report-order",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    resolver = _WorkOrderBoundReportResolver(order.work_order_id)
    inbox = WorkInboxStore(
        DurableJournal(tmp_path / "inbox.jsonl"),
        work_orders=work_orders,
        roster=roster,
        report_resolver=resolver,
    )
    client = _share_app(
        inbox,
        tokens=[
            _token(
                "restricted-sender",
                "sender-a",
                Role.FIELD_OPERATOR,
                allowed_site_ids=frozenset({"site-a"}),
                allowed_work_area_ids=frozenset({"area-a"}),
            ),
            _token(
                "area-b-sender",
                "sender-b",
                Role.FIELD_OPERATOR,
                allowed_site_ids=frozenset({"site-a"}),
                allowed_work_area_ids=frozenset({"area-b"}),
            ),
            _token("opaque-sender", "operator-a", Role.FIELD_OPERATOR),
            _token(
                "restricted-recipient",
                "recipient-b",
                Role.FIELD_OPERATOR,
                allowed_site_ids=frozenset({"site-a"}),
                allowed_work_area_ids=frozenset({"area-a"}),
            ),
        ],
    )
    share_path = "/v1/external-relative-volume-reports/report-a/shares"
    body = {"recipientPrincipalId": "recipient-b"}
    denied = client.post(
        share_path,
        headers={"Authorization": "Bearer restricted-sender", "Idempotency-Key": "denied"},
        json=body,
    )
    assert denied.status_code == 404

    resolver.work_order_id = "missing-core-work-order"
    missing_proof = client.post(
        share_path,
        headers={
            "Authorization": "Bearer restricted-sender",
            "Idempotency-Key": "missing-proof",
        },
        json=body,
    )
    assert missing_proof.status_code == 404

    resolver.work_order_id = order.work_order_id
    scoped_share = client.post(
        share_path,
        headers={"Authorization": "Bearer area-b-sender", "Idempotency-Key": "scoped-share"},
        json=body,
    )
    assert scoped_share.status_code == 201, scoped_share.text
    assert isinstance(client.app, FastAPI)
    client.app.state.auth_registry = AuthRegistry(
        [
            _token(
                "area-b-sender",
                "sender-b",
                Role.FIELD_OPERATOR,
                allowed_site_ids=frozenset({"site-a"}),
                allowed_work_area_ids=frozenset({"area-a"}),
            ),
            _token("opaque-sender", "operator-a", Role.FIELD_OPERATOR),
            _token(
                "restricted-recipient",
                "recipient-b",
                Role.FIELD_OPERATOR,
                allowed_site_ids=frozenset({"site-a"}),
                allowed_work_area_ids=frozenset({"area-a"}),
            ),
        ]
    )
    revoked_retry = client.post(
        share_path,
        headers={"Authorization": "Bearer area-b-sender", "Idempotency-Key": "scoped-share"},
        json=body,
    )
    assert revoked_retry.status_code == 404

    resolver.work_order_id = order.work_order_id
    opaque_share = client.post(
        share_path,
        headers={"Authorization": "Bearer opaque-sender", "Idempotency-Key": "opaque"},
        json=body,
    )
    assert opaque_share.status_code == 201, opaque_share.text
    share_ref = opaque_share.json()["shareRef"]
    notification_ref = "work-inbox-share-" + share_ref.removeprefix("external-report-share-")
    scoped_headers = {"Authorization": "Bearer restricted-recipient"}
    page = client.get("/v1/work-inbox", headers=scoped_headers)
    assert page.status_code == 200, page.text
    assert page.json()["items"] == []
    marked = client.post(
        f"/v1/work-inbox/{notification_ref}/read",
        headers={**scoped_headers, "Idempotency-Key": "restricted-read"},
    )
    assert marked.status_code == 404


def test_report_scope_requires_every_core_work_order_area_on_share_and_read_retry(
    tmp_path: Path,
) -> None:
    from ksi_core.work_inbox import WorkInboxStore

    roster, work_orders = _empty_inbox_dependencies(tmp_path)
    roster.put_member(
        organization_id="org-a",
        principal_id="recipient-b",
        expected_revision=0,
        display_name="검토자 B",
        role_hint=OrganizationWorkRoleHint.FIELD_OPERATOR,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="multi-area report work order",
        work_area_ids=["area-a", "area-b"],
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        actor="operator-a",
        idempotency_key="multi-area-report-order",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    resolver = _WorkOrderBoundReportResolver(order.work_order_id, work_area_id="area-a")
    inbox = WorkInboxStore(
        DurableJournal(tmp_path / "inbox.jsonl"),
        work_orders=work_orders,
        roster=roster,
        report_resolver=resolver,
    )
    client = _share_app(
        inbox,
        tokens=[
            _token(
                "partial-sender",
                "partial-sender",
                Role.FIELD_OPERATOR,
                allowed_site_ids=frozenset({"site-a"}),
                allowed_work_area_ids=frozenset({"area-a"}),
            ),
            _token(
                "all-area-sender",
                "all-area-sender",
                Role.FIELD_OPERATOR,
                allowed_site_ids=frozenset({"site-a"}),
                allowed_work_area_ids=frozenset({"area-a", "area-b"}),
            ),
            _token("opaque-sender", "operator-a", Role.FIELD_OPERATOR),
            _token(
                "all-area-recipient",
                "recipient-b",
                Role.FIELD_OPERATOR,
                allowed_site_ids=frozenset({"site-a"}),
                allowed_work_area_ids=frozenset({"area-a", "area-b"}),
            ),
        ],
    )
    share_path = "/v1/external-relative-volume-reports/report-a/shares"
    body = {"recipientPrincipalId": "recipient-b"}
    partial_share = client.post(
        share_path,
        headers={"Authorization": "Bearer partial-sender", "Idempotency-Key": "partial"},
        json=body,
    )
    assert partial_share.status_code == 404

    authorized_share = client.post(
        share_path,
        headers={
            "Authorization": "Bearer all-area-sender",
            "Idempotency-Key": "all-areas-share",
        },
        json=body,
    )
    assert authorized_share.status_code == 201, authorized_share.text
    share_ref = authorized_share.json()["shareRef"]
    notification_ref = "work-inbox-share-" + share_ref.removeprefix("external-report-share-")
    recipient_headers = {"Authorization": "Bearer all-area-recipient"}
    visible = client.get("/v1/work-inbox", headers=recipient_headers)
    assert visible.status_code == 200, visible.text
    assert [item["notificationRef"] for item in visible.json()["items"]] == [notification_ref]
    read_headers = {
        "Authorization": "Bearer all-area-recipient",
        "Idempotency-Key": "read-all-areas",
    }
    assert (
        client.post(f"/v1/work-inbox/{notification_ref}/read", headers=read_headers).status_code
        == 200
    )

    assert isinstance(client.app, FastAPI)
    client.app.state.auth_registry = AuthRegistry(
        [
            _token(
                "all-area-sender",
                "all-area-sender",
                Role.FIELD_OPERATOR,
                allowed_site_ids=frozenset({"site-a"}),
                allowed_work_area_ids=frozenset({"area-a"}),
            ),
            _token("opaque-sender", "operator-a", Role.FIELD_OPERATOR),
            _token(
                "all-area-recipient",
                "recipient-b",
                Role.FIELD_OPERATOR,
                allowed_site_ids=frozenset({"site-a"}),
                allowed_work_area_ids=frozenset({"area-a"}),
            ),
        ]
    )
    revoked_share_retry = client.post(
        share_path,
        headers={
            "Authorization": "Bearer all-area-sender",
            "Idempotency-Key": "all-areas-share",
        },
        json=body,
    )
    assert revoked_share_retry.status_code == 404
    hidden = client.get("/v1/work-inbox", headers={"Authorization": "Bearer all-area-recipient"})
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["items"] == []
    assert (
        client.post(f"/v1/work-inbox/{notification_ref}/read", headers=read_headers).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/work-inbox/{notification_ref}/read",
            headers={
                "Authorization": "Bearer all-area-recipient",
                "Idempotency-Key": "new-read-key",
            },
        ).status_code
        == 404
    )


def test_relative_share_route_rejects_a_single_volume_ref_with_its_pinned_not_found(
    tmp_path: Path,
) -> None:
    """R2: once the resolver is composite, the relative route must keep
    answering a single-volume ref exactly as it did before SV-3b — a plain
    report-not-found 404 — rather than resolving it through the single leg."""
    from ksi_core.domains.sites.external_report_resolver import ExternalVolumeReportResolver
    from ksi_core.work_inbox import WorkInboxStore

    roster, work_orders = _empty_inbox_dependencies(tmp_path)
    roster.put_member(
        organization_id="org-a",
        principal_id="viewer-b",
        expected_revision=0,
        display_name="검토자 B",
        role_hint=OrganizationWorkRoleHint.VIEWER,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    resolver = ExternalVolumeReportResolver(
        relative=_ExactReportResolver(), single=_SingleVolumeReportResolver()
    )
    inbox = WorkInboxStore(
        DurableJournal(tmp_path / "inbox.jsonl"),
        work_orders=work_orders,
        roster=roster,
        report_resolver=resolver,
    )
    client = _share_app(inbox)

    response = client.post(
        f"/v1/external-relative-volume-reports/{_SINGLE_REPORT_REF}/shares",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "k1"},
        json={"recipientPrincipalId": "viewer-b"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "external relative volume report was not found"


def test_single_volume_share_route_creates_recipient_inbox_item(tmp_path: Path) -> None:
    from ksi_core.domains.sites.external_report_resolver import ExternalVolumeReportResolver
    from ksi_core.work_inbox import WorkInboxStore

    roster, work_orders = _empty_inbox_dependencies(tmp_path)
    roster.put_member(
        organization_id="org-a",
        principal_id="viewer-b",
        expected_revision=0,
        display_name="검토자 B",
        role_hint=OrganizationWorkRoleHint.VIEWER,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    resolver = ExternalVolumeReportResolver(
        relative=_ExactReportResolver(), single=_SingleVolumeReportResolver()
    )
    inbox = WorkInboxStore(
        DurableJournal(tmp_path / "inbox.jsonl"),
        work_orders=work_orders,
        roster=roster,
        report_resolver=resolver,
    )
    client = _share_app(inbox)

    response = client.post(
        f"/v1/external-single-volume-reports/{_SINGLE_REPORT_REF}/shares",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "k1"},
        json={"recipientPrincipalId": "viewer-b"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["siteId"] == "site-b"
    assert body["reportRef"] == _SINGLE_REPORT_REF

    page = inbox.list_for_recipient(
        organization_id="org-a", recipient_principal_id="viewer-b", unread_only=False
    )
    assert page.items[0].target.model_dump(by_alias=True) == {
        "kind": "EXTERNAL_REPORT",
        "workOrderId": None,
        "siteId": "site-b",
        "reportRef": _SINGLE_REPORT_REF,
    }


def test_single_volume_share_route_hides_a_foreign_organization_ref(tmp_path: Path) -> None:
    """``_SINGLE_REPORT_REF`` only resolves for org-a; an org-b operator must
    see a plain not-found, never the org-a site id or digest."""
    from ksi_core.domains.sites.external_report_resolver import ExternalVolumeReportResolver
    from ksi_core.work_inbox import WorkInboxStore

    roster, work_orders = _empty_inbox_dependencies(tmp_path)
    roster.put_member(
        organization_id="org-b",
        principal_id="viewer-c",
        expected_revision=0,
        display_name="검토자 C",
        role_hint=OrganizationWorkRoleHint.VIEWER,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-b",
        idempotency_key="member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    resolver = ExternalVolumeReportResolver(
        relative=_ExactReportResolver(), single=_SingleVolumeReportResolver()
    )
    inbox = WorkInboxStore(
        DurableJournal(tmp_path / "inbox.jsonl"),
        work_orders=work_orders,
        roster=roster,
        report_resolver=resolver,
    )
    client = _share_app(
        inbox, tokens=[_foreign_org_token("operator-b", "operator-b", "org-b")]
    )

    response = client.post(
        f"/v1/external-single-volume-reports/{_SINGLE_REPORT_REF}/shares",
        headers={"Authorization": "Bearer operator-b", "Idempotency-Key": "k1"},
        json={"recipientPrincipalId": "viewer-c"},
    )

    assert response.status_code == 404
    # Fix round 1 (Important): family-aware wording, not the relative
    # family's hardcoded text.
    assert response.json()["detail"] == "external single volume report was not found"


def test_relative_share_route_keeps_its_own_not_found_wording_on_a_genuine_miss(
    tmp_path: Path,
) -> None:
    """Fix round 1 (Important): making the single family's not-found wording
    family-aware must not touch the relative family's own genuine-miss
    wording or status — only the ref's own family's detail changes."""
    from ksi_core.domains.sites.external_report_resolver import ExternalVolumeReportResolver
    from ksi_core.work_inbox import WorkInboxStore

    roster, work_orders = _empty_inbox_dependencies(tmp_path)
    roster.put_member(
        organization_id="org-a",
        principal_id="viewer-b",
        expected_revision=0,
        display_name="검토자 B",
        role_hint=OrganizationWorkRoleHint.VIEWER,
        status=OrganizationWorkRosterStatus.ACTIVE,
        actor="admin-a",
        idempotency_key="member",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    resolver = ExternalVolumeReportResolver(
        relative=_ExactReportResolver(), single=_SingleVolumeReportResolver()
    )
    inbox = WorkInboxStore(
        DurableJournal(tmp_path / "inbox.jsonl"),
        work_orders=work_orders,
        roster=roster,
        report_resolver=resolver,
    )
    client = _share_app(inbox)

    response = client.post(
        "/v1/external-relative-volume-reports/report-does-not-exist/shares",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "k1"},
        json={"recipientPrincipalId": "viewer-b"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "external relative volume report was not found"


def test_relative_share_journal_bytes_are_unchanged_by_a_composite_resolver(
    tmp_path: Path,
) -> None:
    """The relative route's durable copy must not shift when the resolver
    gains a single-volume leg it never uses for a relative ref."""
    from ksi_core.domains.sites.external_report_resolver import ExternalVolumeReportResolver
    from ksi_core.work_inbox import WorkInboxStore

    def _share_with(resolver: Any, journal_path: Path) -> bytes:
        roster, work_orders = _empty_inbox_dependencies(journal_path.parent)
        roster.put_member(
            organization_id="org-a",
            principal_id="viewer-b",
            expected_revision=0,
            display_name="검토자 B",
            role_hint=OrganizationWorkRoleHint.VIEWER,
            status=OrganizationWorkRosterStatus.ACTIVE,
            actor="admin-a",
            idempotency_key="member",
            now=datetime(2026, 9, 10, tzinfo=UTC),
        )
        inbox = WorkInboxStore(
            DurableJournal(journal_path),
            work_orders=work_orders,
            roster=roster,
            report_resolver=resolver,
        )
        inbox.share_report(
            "report-a",
            organization_id="org-a",
            recipient_principal_id="viewer-b",
            actor="operator-a",
            idempotency_key="share",
            now=datetime(2026, 9, 10, tzinfo=UTC),
        )
        inbox._journal.close()  # noqa: SLF001 -- test owns the journal
        return journal_path.read_bytes()

    relative_only_dir = tmp_path / "relative-only"
    relative_only_dir.mkdir()
    composite_dir = tmp_path / "composite"
    composite_dir.mkdir()

    relative_only_bytes = _share_with(_ExactReportResolver(), relative_only_dir / "inbox.jsonl")
    composite_bytes = _share_with(
        ExternalVolumeReportResolver(
            relative=_ExactReportResolver(), single=_SingleVolumeReportResolver()
        ),
        composite_dir / "inbox.jsonl",
    )

    assert relative_only_bytes == composite_bytes


def test_relative_share_route_stays_unavailable_without_a_relative_store(tmp_path: Path) -> None:
    """Fix round 1 (Critical): the workspace graph must not wrap a missing
    relative store in a composite resolver — the composite object is never
    ``None``, so the pre-existing ``if self._report_resolver is None`` 503
    guard in ``WorkInboxStore._resolve_exact_report`` would go dead and a
    relative share would 404 instead of 503 in an assembly with no relative
    store configured (the exact shape
    ``tests/contract/test_hostile_input_route_coverage.py``'s
    ``_mounted_write_routes`` uses — no ``external_result_workflow``)."""
    from ksi_core.composition.platform_assembly import assemble_platform_app as assemble_app

    opened: list[Any] = []

    def journal(name: str) -> DurableJournal:
        item = DurableJournal(tmp_path / name)
        opened.append(item)
        return item

    try:
        # P3 Task 5: legacy assemble_app retired — the platform profile boots
        # the same external-only shape (no workflow config → no relative store).
        app = assemble_app(
            tmp_path,
            journal=journal,
            opened=opened,
            auth_registry=AuthRegistry([_token("operator", "operator-a", Role.FIELD_OPERATOR)]),
            # P3 Task 5: shares route 503s before touching storage (no relative
            # store configured) — an opaque handle suffices and keeps the
            # platform assembly's non-None gate satisfied.
            evidence_storage=cast(Any, object()),
        )
        app.state.organization_work_roster_store.put_member(
            organization_id="org-a",
            principal_id="viewer-b",
            expected_revision=0,
            display_name="검토자 B",
            role_hint=OrganizationWorkRoleHint.VIEWER,
            status=OrganizationWorkRosterStatus.ACTIVE,
            actor="admin-a",
            idempotency_key="member",
            now=datetime(2026, 9, 10, tzinfo=UTC),
        )
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/external-relative-volume-reports/report-a/shares",
            headers={"Authorization": "Bearer operator", "Idempotency-Key": "k1"},
            json={"recipientPrincipalId": "viewer-b"},
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "EXTERNAL_REPORT_SHARING_UNAVAILABLE"
    finally:
        for item in opened:
            item.close()
