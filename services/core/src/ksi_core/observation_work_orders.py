"""반복 관측 WorkOrder 원장과 사람 승인 경계(REQ-WRK-101, INV-060/061)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from ksi_event_contracts.observation_work_order import (
    ObservationPurpose,
    ObservationSchedule,
    ObservationScheduleStatus,
    ObservationWorkOrder,
    ObservationWorkOrderStatus,
    ReobservationDraft,
    ReobservationDraftStatus,
)
from pydantic import Field, ValidationError

from ksi_core.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identifiers import is_path_safe_identifier

logger = logging.getLogger(__name__)

_STATUS_TRANSITIONS: dict[ObservationWorkOrderStatus, frozenset[ObservationWorkOrderStatus]] = {
    ObservationWorkOrderStatus.APPROVED: frozenset(
        {ObservationWorkOrderStatus.DISPATCHED, ObservationWorkOrderStatus.BLOCKED}
    ),
    ObservationWorkOrderStatus.DISPATCHED: frozenset(
        {ObservationWorkOrderStatus.START_REPORTED, ObservationWorkOrderStatus.BLOCKED}
    ),
    ObservationWorkOrderStatus.START_REPORTED: frozenset(
        {ObservationWorkOrderStatus.MEDIA_RECEIVING, ObservationWorkOrderStatus.BLOCKED}
    ),
    ObservationWorkOrderStatus.MEDIA_RECEIVING: frozenset(
        {ObservationWorkOrderStatus.PROCESSING, ObservationWorkOrderStatus.BLOCKED}
    ),
    ObservationWorkOrderStatus.PROCESSING: frozenset(
        {ObservationWorkOrderStatus.REVIEW_READY, ObservationWorkOrderStatus.BLOCKED}
    ),
    ObservationWorkOrderStatus.REVIEW_READY: frozenset(
        {ObservationWorkOrderStatus.COMPLETED, ObservationWorkOrderStatus.BLOCKED}
    ),
}


class WorkOrderActionGroup(StrEnum):
    DECISION_REQUIRED = "DECISION_REQUIRED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


_ACTION_GROUP_STATUSES: dict[WorkOrderActionGroup, frozenset[ObservationWorkOrderStatus]] = {
    WorkOrderActionGroup.DECISION_REQUIRED: frozenset(
        {
            ObservationWorkOrderStatus.DRAFT,
            ObservationWorkOrderStatus.AWAITING_APPROVAL,
            ObservationWorkOrderStatus.REVIEW_READY,
            ObservationWorkOrderStatus.REOBSERVATION_PENDING,
            ObservationWorkOrderStatus.BLOCKED,
        }
    ),
    WorkOrderActionGroup.IN_PROGRESS: frozenset(
        {
            ObservationWorkOrderStatus.APPROVED,
            ObservationWorkOrderStatus.DISPATCHED,
            ObservationWorkOrderStatus.START_REPORTED,
            ObservationWorkOrderStatus.MEDIA_RECEIVING,
            ObservationWorkOrderStatus.PROCESSING,
        }
    ),
    WorkOrderActionGroup.COMPLETED: frozenset(
        {ObservationWorkOrderStatus.COMPLETED, ObservationWorkOrderStatus.CANCELLED}
    ),
}


class ObservationWorkOrderStoreRecoveryError(RuntimeError):
    pass


class ObservationWorkOrderStore:
    """Append-only projection. 모든 public 조회는 organization scope를 요구한다."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        site_exists: Callable[[str, str], bool],
        work_areas_exist: Callable[[str, list[str]], bool] | None = None,
    ) -> None:
        self._journal = journal
        self._site_exists = site_exists
        self._work_areas_exist = work_areas_exist
        self._schedules: dict[str, ObservationSchedule] = {}
        self._orders: dict[str, ObservationWorkOrder] = {}
        self._drafts: dict[str, ReobservationDraft] = {}
        self._lock = threading.Lock()
        self._status_listeners: list[Callable[[ObservationWorkOrder], None]] = []
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException:
            journal.close()
            raise

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def _apply(self, raw: dict[str, Any]) -> None:
        try:
            kind = raw["kind"]
            if kind == "observation-schedule-created":
                schedule = ObservationSchedule.model_validate(raw["schedule"])
                if schedule.schedule_id in self._schedules:
                    raise ValueError("중복 scheduleId")
                self._schedules[schedule.schedule_id] = schedule
            elif kind in {"observation-work-order-created", "observation-work-order-updated"}:
                order = ObservationWorkOrder.model_validate(raw["workOrder"])
                current = self._orders.get(order.work_order_id)
                if kind.endswith("created") and current is not None:
                    raise ValueError("중복 workOrderId")
                if kind.endswith("updated") and (
                    current is None or order.version != current.version + 1
                ):
                    raise ValueError("work order version 계보 불일치")
                self._orders[order.work_order_id] = order
            elif kind in {"reobservation-draft-created", "reobservation-draft-updated"}:
                draft = ReobservationDraft.model_validate(raw["draft"])
                current_draft = self._drafts.get(draft.draft_id)
                if kind.endswith("created") and current_draft is not None:
                    raise ValueError("중복 draftId")
                if kind.endswith("updated") and (
                    current_draft is None or draft.version != current_draft.version + 1
                ):
                    raise ValueError("draft version 계보 불일치")
                self._drafts[draft.draft_id] = draft
            elif kind in {
                "reobservation-draft-and-order-created",
                "reobservation-draft-and-order-approved",
            }:
                draft = ReobservationDraft.model_validate(raw["draft"])
                order = ObservationWorkOrder.model_validate(raw["workOrder"])
                current_draft = self._drafts.get(draft.draft_id)
                current_order = self._orders.get(order.work_order_id)
                if current_order is None or order.version != current_order.version + 1:
                    raise ValueError("work order version 계보 불일치")
                if kind.endswith("created"):
                    if current_draft is not None:
                        raise ValueError("중복 draftId")
                elif current_draft is None or draft.version != current_draft.version + 1:
                    raise ValueError("draft version 계보 불일치")
                self._drafts[draft.draft_id] = draft
                self._orders[order.work_order_id] = order
            else:
                raise ValueError(f"알 수 없는 kind: {kind!r}")
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ObservationWorkOrderStoreRecoveryError(
                f"observation work-order journal 재생 실패: {exc}"
            ) from exc

    def _append(self, raw: dict[str, Any]) -> None:
        self._journal.append(raw)
        self._apply(raw)

    def _validate_scope(
        self, *, organization_id: str, site_id: str, work_area_ids: list[str]
    ) -> None:
        if not is_path_safe_identifier(organization_id):
            raise ValueError("organizationId 는 경로-안전 비공백 식별자여야 한다")
        if not is_path_safe_identifier(site_id):
            raise ValueError("siteId 는 경로-안전 비공백 식별자여야 한다")
        if not self._site_exists(site_id, organization_id):
            raise LookupError("현장을 찾을 수 없다")
        if any(not is_path_safe_identifier(item) for item in work_area_ids):
            raise ValueError("workAreaIds 는 경로-안전 비공백 식별자여야 한다")
        if self._work_areas_exist is not None and not self._work_areas_exist(
            site_id, work_area_ids
        ):
            raise LookupError("현장에 속한 ACTIVE 작업구역을 찾을 수 없다")

    def create_schedule(
        self,
        *,
        organization_id: str,
        site_id: str,
        name: str,
        work_area_ids: list[str],
        interval_days: int,
        timezone: str,
        approved_policy_version: str | None,
        actor: str,
        now: datetime,
    ) -> ObservationSchedule:
        self._validate_scope(
            organization_id=organization_id,
            site_id=site_id,
            work_area_ids=work_area_ids,
        )
        with self._lock:
            schedule_id = f"obs-schedule-{len(self._schedules) + 1:08d}"
            schedule = ObservationSchedule(
                schedule_id=schedule_id,
                organization_id=organization_id,
                site_id=site_id,
                name=name,
                work_area_ids=work_area_ids,
                interval_days=interval_days,
                timezone=timezone,
                approved_policy_version=approved_policy_version,
                status=ObservationScheduleStatus.ACTIVE,
                created_at=iso_utc(now),
                created_by=actor,
            )
            self._append(
                {
                    "kind": "observation-schedule-created",
                    "ts": iso_utc(now),
                    "actor": actor,
                    "schedule": schedule.model_dump(by_alias=True, mode="json"),
                }
            )
            return schedule

    def create_work_order(
        self,
        *,
        organization_id: str,
        site_id: str,
        name: str,
        work_area_ids: list[str],
        schedule_id: str | None,
        actor: str,
        now: datetime,
    ) -> ObservationWorkOrder:
        self._validate_scope(
            organization_id=organization_id,
            site_id=site_id,
            work_area_ids=work_area_ids,
        )
        with self._lock:
            if schedule_id is not None:
                schedule = self._schedules.get(schedule_id)
                if (
                    schedule is None
                    or schedule.organization_id != organization_id
                    or schedule.site_id != site_id
                ):
                    raise LookupError("관측 일정을 찾을 수 없다")
            work_order_id = f"obs-work-{len(self._orders) + 1:08d}"
            order = ObservationWorkOrder(
                work_order_id=work_order_id,
                organization_id=organization_id,
                site_id=site_id,
                purpose=ObservationPurpose.PROGRESS_QUANTITY,
                name=name,
                work_area_ids=work_area_ids,
                schedule_id=schedule_id,
                status=ObservationWorkOrderStatus.AWAITING_APPROVAL,
                version=1,
                created_at=iso_utc(now),
                updated_at=iso_utc(now),
                created_by=actor,
            )
            self._append(
                {
                    "kind": "observation-work-order-created",
                    "ts": iso_utc(now),
                    "actor": actor,
                    "workOrder": order.model_dump(by_alias=True, mode="json"),
                }
            )
            return order

    def get(self, work_order_id: str, *, organization_id: str) -> ObservationWorkOrder | None:
        with self._lock:
            order = self._orders.get(work_order_id)
            if order is None or order.organization_id != organization_id:
                return None
            return order

    def list_for_site(self, site_id: str, *, organization_id: str) -> list[ObservationWorkOrder]:
        if not self._site_exists(site_id, organization_id):
            raise LookupError("현장을 찾을 수 없다")
        with self._lock:
            return sorted(
                (
                    order
                    for order in self._orders.values()
                    if order.site_id == site_id and order.organization_id == organization_id
                ),
                key=lambda item: item.work_order_id,
            )

    def list_scoped(
        self,
        *,
        organization_id: str,
        site_id: str | None = None,
        status: ObservationWorkOrderStatus | None = None,
        action_group: WorkOrderActionGroup | None = None,
    ) -> list[ObservationWorkOrder]:
        """Global Work queue with organization scope applied before every filter."""
        with self._lock:
            records = [
                item
                for item in self._orders.values()
                if item.organization_id == organization_id
            ]
        if site_id is not None:
            # Preserve cross-organization 404 semantics for a requested Site scope.
            if not self._site_exists(site_id, organization_id):
                raise LookupError("현장을 찾을 수 없다")
            records = [item for item in records if item.site_id == site_id]
        if status is not None:
            records = [item for item in records if item.status is status]
        if action_group is not None:
            records = [
                item for item in records if item.status in _ACTION_GROUP_STATUSES[action_group]
            ]
        return sorted(
            records,
            key=lambda item: (item.updated_at, item.work_order_id),
            reverse=True,
        )

    def list_schedules(self, site_id: str, *, organization_id: str) -> list[ObservationSchedule]:
        if not self._site_exists(site_id, organization_id):
            raise LookupError("현장을 찾을 수 없다")
        with self._lock:
            return sorted(
                (
                    item
                    for item in self._schedules.values()
                    if item.site_id == site_id and item.organization_id == organization_id
                ),
                key=lambda item: item.schedule_id,
            )

    def list_reobservation_drafts(
        self, work_order_id: str, *, organization_id: str
    ) -> list[ReobservationDraft]:
        with self._lock:
            order = self._orders.get(work_order_id)
            if order is None or order.organization_id != organization_id:
                raise LookupError("관측 작업을 찾을 수 없다")
            return sorted(
                (
                    item
                    for item in self._drafts.values()
                    if item.work_order_id == work_order_id
                    and item.organization_id == organization_id
                ),
                key=lambda item: item.draft_id,
            )

    def approve(
        self,
        work_order_id: str,
        *,
        organization_id: str,
        expected_version: int,
        actor: str,
        now: datetime,
    ) -> ObservationWorkOrder:
        with self._lock:
            current = self._orders.get(work_order_id)
            if current is None or current.organization_id != organization_id:
                raise LookupError("관측 작업을 찾을 수 없다")
            if current.version != expected_version:
                raise RuntimeError("VERSION_CONFLICT")
            if current.status not in {
                ObservationWorkOrderStatus.AWAITING_APPROVAL,
                ObservationWorkOrderStatus.REOBSERVATION_PENDING,
            }:
                raise RuntimeError("INVALID_STATE")
            updated = current.model_copy(
                update={
                    "status": ObservationWorkOrderStatus.APPROVED,
                    "status_reason": None,
                    "version": current.version + 1,
                    "updated_at": iso_utc(now),
                    "approved_at": iso_utc(now),
                    "approved_by": actor,
                }
            )
            self._append(
                {
                    "kind": "observation-work-order-updated",
                    "ts": iso_utc(now),
                    "actor": actor,
                    "workOrder": updated.model_dump(by_alias=True, mode="json"),
                }
            )
        self._notify_status_listeners(updated)
        return updated

    def _notify_status_listeners(self, updated: ObservationWorkOrder) -> None:
        """Run post-commit projections without changing the WorkOrder verdict."""
        for listener in tuple(self._status_listeners):
            try:
                listener(updated)
            except Exception:
                logger.exception(
                    "work order status listener failed",
                    extra={
                        "work_order_id": updated.work_order_id,
                        "status": updated.status.value,
                    },
                )

    def bind_status_listener(
        self, listener: Callable[[ObservationWorkOrder], None]
    ) -> None:
        """Bind a post-commit projection listener; WorkOrder remains authoritative."""
        with self._lock:
            if listener not in self._status_listeners:
                self._status_listeners.append(listener)

    def link_mission(
        self,
        work_order_id: str,
        *,
        organization_id: str,
        cycle_number: int,
        mission_id: str,
        mission_site_id: str,
        actor: str,
        now: datetime,
        require_approved: bool,
    ) -> ObservationWorkOrder:
        """Idempotently preserve Mission lineage without changing human approval.

        Mission issuance and this WorkOrder journal cannot be one filesystem
        transaction. A retry therefore calls this method again; an existing
        missionId is returned without a second append.
        """

        if now.tzinfo is None:
            raise ValueError("now는 tz-aware여야 한다")
        if not is_path_safe_identifier(mission_id):
            raise ValueError("missionId는 경로-안전 식별자여야 한다")
        with self._lock:
            current = self._orders.get(work_order_id)
            if current is None or current.organization_id != organization_id:
                raise LookupError("관측 작업을 찾을 수 없다")
            if current.site_id != mission_site_id:
                raise ValueError("WorkOrder와 Mission의 Site가 다르다")
            if require_approved and current.cycle_number != cycle_number:
                raise RuntimeError("WORK_ORDER_CYCLE_MISMATCH")
            if require_approved and current.status is not ObservationWorkOrderStatus.APPROVED:
                raise RuntimeError("WORK_ORDER_NOT_APPROVED")
            if mission_id in current.mission_ids:
                return current
            updated = current.model_copy(
                update={
                    "mission_ids": [*current.mission_ids, mission_id],
                    "version": current.version + 1,
                    "updated_at": iso_utc(now),
                }
            )
            self._append(
                {
                    "kind": "observation-work-order-updated",
                    "ts": iso_utc(now),
                    "actor": actor,
                    "workOrder": updated.model_dump(by_alias=True, mode="json"),
                }
            )
        self._notify_status_listeners(updated)
        return updated

    def record_status(
        self,
        work_order_id: str,
        *,
        organization_id: str,
        status: ObservationWorkOrderStatus,
        status_reason: str | None,
        mission_ids: list[str] | None,
        processing_job_ids: list[str] | None,
        report_refs: list[str] | None,
        actor: str,
        now: datetime,
    ) -> ObservationWorkOrder:
        """검증된 내부 어댑터/워커가 보고한 단조 상태 전이만 반영한다."""
        with self._lock:
            current = self._orders.get(work_order_id)
            if current is None or current.organization_id != organization_id:
                raise LookupError("관측 작업을 찾을 수 없다")
            if status not in _STATUS_TRANSITIONS.get(current.status, frozenset()):
                raise RuntimeError("INVALID_STATE")
            updated = current.model_copy(
                update={
                    "status": status,
                    "status_reason": status_reason,
                    "mission_ids": mission_ids if mission_ids is not None else current.mission_ids,
                    "processing_job_ids": processing_job_ids
                    if processing_job_ids is not None
                    else current.processing_job_ids,
                    "report_refs": report_refs if report_refs is not None else current.report_refs,
                    "version": current.version + 1,
                    "updated_at": iso_utc(now),
                }
            )
            self._append(
                {
                    "kind": "observation-work-order-updated",
                    "ts": iso_utc(now),
                    "actor": actor,
                    "workOrder": updated.model_dump(by_alias=True, mode="json"),
                }
            )
        self._notify_status_listeners(updated)
        return updated

    def create_reobservation_draft(
        self,
        work_order_id: str,
        *,
        organization_id: str,
        reason_refs: list[str],
        target_region_refs: list[str],
        proposed_effort: str,
        planner_version: str,
        policy_version: str,
        expires_at: datetime,
        actor: str,
        now: datetime,
    ) -> ReobservationDraft:
        if expires_at.tzinfo is None or expires_at <= now:
            raise ValueError("expiresAt 은 현재 이후의 tz-aware 시각이어야 한다")
        with self._lock:
            current = self._orders.get(work_order_id)
            if current is None or current.organization_id != organization_id:
                raise LookupError("관측 작업을 찾을 수 없다")
            if current.status not in {
                ObservationWorkOrderStatus.REVIEW_READY,
                ObservationWorkOrderStatus.COMPLETED,
                ObservationWorkOrderStatus.BLOCKED,
            }:
                raise RuntimeError("INVALID_STATE")
            draft = ReobservationDraft(
                draft_id=f"reobs-draft-{len(self._drafts) + 1:08d}",
                organization_id=organization_id,
                site_id=current.site_id,
                work_order_id=work_order_id,
                reason_refs=reason_refs,
                target_region_refs=target_region_refs,
                proposed_effort=proposed_effort,
                planner_version=planner_version,
                policy_version=policy_version,
                expires_at=iso_utc(expires_at),
                status=ReobservationDraftStatus.PENDING,
                version=1,
                created_at=iso_utc(now),
                created_by=actor,
            )
            pending = current.model_copy(
                update={
                    "status": ObservationWorkOrderStatus.REOBSERVATION_PENDING,
                    "status_reason": "근거가 연결된 재관측 초안이 사람 승인을 기다린다",
                    "version": current.version + 1,
                    "updated_at": iso_utc(now),
                }
            )
            self._append(
                {
                    "kind": "reobservation-draft-and-order-created",
                    "ts": iso_utc(now),
                    "actor": actor,
                    "draft": draft.model_dump(by_alias=True, mode="json"),
                    "workOrder": pending.model_dump(by_alias=True, mode="json"),
                }
            )
            return draft

    def approve_reobservation(
        self,
        draft_id: str,
        *,
        organization_id: str,
        expected_version: int,
        actor: str,
        now: datetime,
    ) -> ReobservationDraft:
        with self._lock:
            current = self._drafts.get(draft_id)
            if current is None or current.organization_id != organization_id:
                raise LookupError("재관측 초안을 찾을 수 없다")
            if current.version != expected_version:
                raise RuntimeError("VERSION_CONFLICT")
            if current.status is not ReobservationDraftStatus.PENDING:
                raise RuntimeError("INVALID_STATE")
            if datetime.fromisoformat(current.expires_at) <= now:
                raise RuntimeError("DRAFT_EXPIRED")
            order = self._orders[current.work_order_id]
            if order.status is not ObservationWorkOrderStatus.REOBSERVATION_PENDING:
                raise RuntimeError("INVALID_STATE")
            approved = current.model_copy(
                update={
                    "status": ReobservationDraftStatus.APPROVED,
                    "version": current.version + 1,
                    "approved_at": iso_utc(now),
                    "approved_by": actor,
                }
            )
            reopened = order.model_copy(
                update={
                    "status": ObservationWorkOrderStatus.APPROVED,
                    "status_reason": None,
                    "cycle_number": order.cycle_number + 1,
                    "version": order.version + 1,
                    "updated_at": iso_utc(now),
                    "approved_at": iso_utc(now),
                    "approved_by": actor,
                }
            )
            self._append(
                {
                    "kind": "reobservation-draft-and-order-approved",
                    "ts": iso_utc(now),
                    "actor": actor,
                    "draft": approved.model_dump(by_alias=True, mode="json"),
                    "workOrder": reopened.model_dump(by_alias=True, mode="json"),
                }
            )
            return approved


class ScheduleCreateRequest(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    work_area_ids: list[str] = Field(min_length=1, max_length=64)
    interval_days: int = Field(ge=1, le=365)
    timezone: str = Field(min_length=1, max_length=100)
    approved_policy_version: str | None = None


class WorkOrderCreateRequest(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    work_area_ids: list[str] = Field(min_length=1, max_length=64)
    schedule_id: str | None = None


class VersionedApprovalRequest(CamelModel):
    expected_version: int = Field(ge=1)


class ReobservationDraftCreateRequest(CamelModel):
    reason_refs: list[str] = Field(min_length=1, max_length=64)
    target_region_refs: list[str] = Field(min_length=1, max_length=64)
    proposed_effort: str = Field(min_length=1, max_length=500)
    planner_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    expires_at: datetime


class WorkOrderListResponse(CamelModel):
    work_orders: list[ObservationWorkOrder]


class ScheduleListResponse(CamelModel):
    schedules: list[ObservationSchedule]


class ReobservationDraftListResponse(CamelModel):
    drafts: list[ReobservationDraft]


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, JournalSealedError):
        return HTTPException(
            status_code=503, detail=JOURNAL_SEALED_DETAIL, headers={"Retry-After": "30"}
        )
    if str(exc) == "VERSION_CONFLICT":
        return HTTPException(status_code=409, detail="expectedVersion 이 현재 version 과 다르다")
    if str(exc) == "DRAFT_EXPIRED":
        return HTTPException(status_code=409, detail="재관측 초안이 만료됐다")
    if str(exc) == "INVALID_STATE":
        return HTTPException(status_code=409, detail="현재 상태에서는 요청한 전이를 수행할 수 없다")
    return HTTPException(status_code=422, detail=str(exc))


def build_observation_work_order_router(
    store: ObservationWorkOrderStore,
    *,
    on_approved: Callable[[ObservationWorkOrder, str, datetime], None] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["observation-work-orders"])

    @router.post(
        "/v1/sites/{site_id}/observation-schedules",
        response_model=ObservationSchedule,
        status_code=201,
    )
    def create_schedule(
        site_id: str,
        request: ScheduleCreateRequest,
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008,E501
    ) -> ObservationSchedule:
        try:
            return store.create_schedule(
                organization_id=principal.organization_id,
                site_id=site_id,
                name=request.name,
                work_area_ids=request.work_area_ids,
                interval_days=request.interval_days,
                timezone=request.timezone,
                approved_policy_version=request.approved_policy_version,
                actor=principal.principal_id,
                now=datetime.now(UTC),
            )
        except (JournalSealedError, LookupError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc

    @router.get("/v1/sites/{site_id}/observation-schedules", response_model=ScheduleListResponse)
    def list_schedules(
        site_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> ScheduleListResponse:
        try:
            return ScheduleListResponse(
                schedules=store.list_schedules(site_id, organization_id=principal.organization_id)
            )
        except LookupError as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/v1/sites/{site_id}/observation-work-orders",
        response_model=ObservationWorkOrder,
        status_code=201,
    )
    def create_work_order(
        site_id: str,
        request: WorkOrderCreateRequest,
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008,E501
    ) -> ObservationWorkOrder:
        try:
            return store.create_work_order(
                organization_id=principal.organization_id,
                site_id=site_id,
                name=request.name,
                work_area_ids=request.work_area_ids,
                schedule_id=request.schedule_id,
                actor=principal.principal_id,
                now=datetime.now(UTC),
            )
        except (JournalSealedError, LookupError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc

    @router.get("/v1/sites/{site_id}/observation-work-orders", response_model=WorkOrderListResponse)
    def list_work_orders(
        site_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> WorkOrderListResponse:
        try:
            return WorkOrderListResponse(
                work_orders=store.list_for_site(site_id, organization_id=principal.organization_id)
            )
        except LookupError as exc:
            raise _http_error(exc) from exc

    @router.get("/v1/observation-work-orders", response_model=WorkOrderListResponse)
    def list_global_work_orders(
        site_id: str | None = Query(default=None, alias="siteId"),  # noqa: B008
        status: ObservationWorkOrderStatus | None = Query(default=None),  # noqa: B008
        action_group: WorkOrderActionGroup | None = Query(  # noqa: B008
            default=None, alias="actionGroup"
        ),
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> WorkOrderListResponse:
        try:
            return WorkOrderListResponse(
                work_orders=store.list_scoped(
                    organization_id=principal.organization_id,
                    site_id=site_id,
                    status=status,
                    action_group=action_group,
                )
            )
        except LookupError as exc:
            raise _http_error(exc) from exc

    @router.get("/v1/observation-work-orders/{work_order_id}", response_model=ObservationWorkOrder)
    def get_work_order(
        work_order_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> ObservationWorkOrder:
        order = store.get(work_order_id, organization_id=principal.organization_id)
        if order is None:
            raise HTTPException(status_code=404, detail="관측 작업을 찾을 수 없다")
        return order

    @router.post(
        "/v1/observation-work-orders/{work_order_id}/approve", response_model=ObservationWorkOrder
    )
    def approve_work_order(
        work_order_id: str,
        request: VersionedApprovalRequest,
        principal: Principal = Depends(require_permission(Permission.REOBSERVATION_APPROVE)),  # noqa: B008,E501
    ) -> ObservationWorkOrder:
        now = datetime.now(UTC)
        try:
            approved = store.approve(
                work_order_id,
                organization_id=principal.organization_id,
                expected_version=request.expected_version,
                actor=principal.principal_id,
                now=now,
            )
        except (JournalSealedError, LookupError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc
        if on_approved is not None:
            try:
                on_approved(approved, principal.principal_id, now)
            except Exception:
                # The approval was already durably recorded. Coordinator recovery
                # happens on acquisition-progress GET; never ask a person to
                # repeat a completed approval because a secondary journal failed.
                logger.exception(
                    "WorkOrder approval succeeded but AcquisitionRun creation failed: %s",
                    approved.work_order_id,
                )
        return approved

    @router.post(
        "/v1/observation-work-orders/{work_order_id}/reobservation-drafts",
        response_model=ReobservationDraft,
        status_code=201,
    )
    def create_reobservation_draft(
        work_order_id: str,
        request: ReobservationDraftCreateRequest,
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008,E501
    ) -> ReobservationDraft:
        try:
            return store.create_reobservation_draft(
                work_order_id,
                organization_id=principal.organization_id,
                reason_refs=request.reason_refs,
                target_region_refs=request.target_region_refs,
                proposed_effort=request.proposed_effort,
                planner_version=request.planner_version,
                policy_version=request.policy_version,
                expires_at=request.expires_at,
                actor=principal.principal_id,
                now=datetime.now(UTC),
            )
        except (JournalSealedError, LookupError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc

    @router.get(
        "/v1/observation-work-orders/{work_order_id}/reobservation-drafts",
        response_model=ReobservationDraftListResponse,
    )
    def list_reobservation_drafts(
        work_order_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> ReobservationDraftListResponse:
        try:
            return ReobservationDraftListResponse(
                drafts=store.list_reobservation_drafts(
                    work_order_id, organization_id=principal.organization_id
                )
            )
        except LookupError as exc:
            raise _http_error(exc) from exc

    @router.post("/v1/reobservation-drafts/{draft_id}/approve", response_model=ReobservationDraft)
    def approve_reobservation(
        draft_id: str,
        request: VersionedApprovalRequest,
        principal: Principal = Depends(require_permission(Permission.REOBSERVATION_APPROVE)),  # noqa: B008,E501
    ) -> ReobservationDraft:
        now = datetime.now(UTC)
        try:
            approved_draft = store.approve_reobservation(
                draft_id,
                organization_id=principal.organization_id,
                expected_version=request.expected_version,
                actor=principal.principal_id,
                now=now,
            )
        except (JournalSealedError, LookupError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc
        reopened = store.get(
            approved_draft.work_order_id, organization_id=principal.organization_id
        )
        if on_approved is not None and reopened is not None:
            try:
                on_approved(reopened, principal.principal_id, now)
            except Exception:
                logger.exception(
                    "Reobservation approval succeeded but AcquisitionRun creation failed: %s",
                    reopened.work_order_id,
                )
        return approved_draft

    return router


def mount_observation_work_orders(
    app: Any,
    store: ObservationWorkOrderStore,
    *,
    on_approved: Callable[[ObservationWorkOrder, str, datetime], None] | None = None,
) -> None:
    app.state.observation_work_order_store = store
    app.include_router(build_observation_work_order_router(store, on_approved=on_approved))


__all__ = [
    "ObservationWorkOrderStore",
    "ObservationWorkOrderStoreRecoveryError",
    "mount_observation_work_orders",
]
