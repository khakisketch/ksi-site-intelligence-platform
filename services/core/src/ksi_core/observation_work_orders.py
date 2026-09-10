"""반복 관측 WorkOrder 원장과 사람 승인 경계(REQ-WRK-101, INV-060/061)."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from ksi_event_contracts.external_reobservation import (
    ExternalPlanningOnlyWorkOrderBindingV1,
    ExternalReobservationApprovalInputV1,
    ExternalReobservationApprovalReceiptV1,
    ExternalReobservationProposalAuthorityV1,
)
from ksi_event_contracts.observation_work_order import (
    ObservationPurpose,
    ObservationSchedule,
    ObservationScheduleStatus,
    ObservationWorkOrder,
    ObservationWorkOrderExecutionMode,
    ObservationWorkOrderStatus,
    ReobservationDraft,
    ReobservationDraftStatus,
    TemporalCoherencePolicy,
)
from pydantic import Field, ValidationError, model_validator

from ksi_core.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.auth import Permission, Principal, PrincipalKind, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
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


class ExternalReconstructionExecutionDenied(RuntimeError):
    """An external reconstruction WorkOrder was sent to a managed execution path."""


# Kept as an import-compatible name for the sealed successor boundary.
ExternalReobservationExecutionDenied = ExternalReconstructionExecutionDenied


class WorkOrderWorkflowStatus(StrEnum):
    """Administrative state only; it never changes sealed observation evidence."""

    UNSPECIFIED = "UNSPECIFIED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class WorkOrderOperationsAssignmentAction(StrEnum):
    ASSIGN_TO_ME = "ASSIGN_TO_ME"
    ASSIGN_TO_MEMBER = "ASSIGN_TO_MEMBER"
    CLEAR = "CLEAR"


class ObservationWorkOrderOperations(CamelModel):
    """Durable human operations projection, deliberately separate from ``WorkOrder``."""

    schema_version: Literal["1.0"] = "1.0"
    organization_id: str = Field(min_length=1, max_length=255)
    site_id: str = Field(min_length=1, max_length=255)
    work_order_id: str = Field(min_length=1, max_length=255)
    operations_revision: int = Field(ge=0)
    workflow_status: WorkOrderWorkflowStatus
    assignee_principal_id: str | None = Field(default=None, min_length=1, max_length=255)
    due_at: datetime | None = None
    closed_at: datetime | None = None
    closed_by: str | None = Field(default=None, min_length=1, max_length=255)
    close_note: str | None = Field(default=None, max_length=500)
    updated_at: datetime | None = None
    updated_by: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def _validate_operations_snapshot(self) -> ObservationWorkOrderOperations:
        def require_utc(value: datetime | None, *, field_name: str) -> None:
            if value is not None and (
                value.tzinfo is None or value.utcoffset() != timedelta(0)
            ):
                raise ValueError(f"{field_name} must be a UTC timestamp")

        require_utc(self.due_at, field_name="dueAt")
        require_utc(self.closed_at, field_name="closedAt")
        require_utc(self.updated_at, field_name="updatedAt")
        if self.close_note is not None and not self.close_note.strip():
            raise ValueError("closeNote must not be blank")
        if self.workflow_status is WorkOrderWorkflowStatus.CLOSED:
            if self.closed_at is None or self.closed_by is None:
                raise ValueError("CLOSED operations require closedAt and closedBy")
        elif any(item is not None for item in (self.closed_at, self.closed_by, self.close_note)):
            raise ValueError("non-CLOSED operations cannot retain closure fields")
        if self.operations_revision == 0:
            if self.workflow_status is not WorkOrderWorkflowStatus.UNSPECIFIED:
                raise ValueError("revision 0 operations must be UNSPECIFIED")
            if any(
                item is not None
                for item in (
                    self.assignee_principal_id,
                    self.due_at,
                    self.closed_at,
                    self.closed_by,
                    self.close_note,
                    self.updated_at,
                    self.updated_by,
                )
            ):
                raise ValueError("revision 0 operations must not invent legacy state")
        elif (
            self.workflow_status is WorkOrderWorkflowStatus.UNSPECIFIED
            or self.updated_at is None
            or self.updated_by is None
        ):
            raise ValueError("durable operations require an explicit state and update audit")
        return self


@dataclass(frozen=True)
class WorkOrderAssignmentTransition:
    """Replay-derived recipient notice source; it writes no second WorkOrder event."""

    organization_id: str
    site_id: str
    work_order_id: str
    operations_revision: int
    recipient_principal_id: str
    actor_principal_id: str
    occurred_at: datetime


class ExternalReobservationProposalAuthorityPort(Protocol):
    """Resolve independently persisted accepted authority; callers never supply it."""

    def guard_current(
        self,
        *,
        organization_id: str,
        approval_input: ExternalReobservationApprovalInputV1,
        actor: str,
        evaluated_at: datetime,
    ) -> AbstractContextManager[ExternalReobservationProposalAuthorityV1 | None]:
        """Hold exact current dependencies stable until the approval append completes.

        All revocation/updates must coordinate with this guard. Resolve ACTIVE
        Site/WorkAreas and policy/evidence/proposal here, without WorkOrder calls.
        Lock order is authority guard -> WorkOrder -> journal, never the reverse.
        A collection of uncoordinated snapshot reads cannot implement this port.
        """
        ...

    def resolve_historical(
        self,
        *,
        organization_id: str,
        approval_input: ExternalReobservationApprovalInputV1,
        actor: str,
        approved_at: datetime,
    ) -> ExternalReobservationProposalAuthorityV1 | None: ...


class _ClosedExternalReobservationProposalAuthorityPort:
    @contextmanager
    def guard_current(
        self,
        *,
        organization_id: str,
        approval_input: ExternalReobservationApprovalInputV1,
        actor: str,
        evaluated_at: datetime,
    ) -> Iterator[ExternalReobservationProposalAuthorityV1 | None]:
        del organization_id, approval_input, actor, evaluated_at
        yield None

    def resolve_historical(
        self,
        *,
        organization_id: str,
        approval_input: ExternalReobservationApprovalInputV1,
        actor: str,
        approved_at: datetime,
    ) -> ExternalReobservationProposalAuthorityV1 | None:
        del organization_id, approval_input, actor, approved_at
        return None


@dataclass(frozen=True)
class ExternalReobservationApprovalResult:
    approval_receipt: ExternalReobservationApprovalReceiptV1
    planning_binding: ExternalPlanningOnlyWorkOrderBindingV1
    successor_work_order: ObservationWorkOrder


class ObservationWorkOrderStore:
    """Append-only projection. 모든 public 조회는 organization scope를 요구한다."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        site_exists: Callable[[str, str], bool],
        work_areas_exist: Callable[[str, list[str]], bool] | None = None,
        external_reobservation_authority_port: ExternalReobservationProposalAuthorityPort
        | None = None,
        operations_coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
        assignment_member_is_active: Callable[..., bool] | None = None,
    ) -> None:
        self._journal = journal
        self._site_exists = site_exists
        self._work_areas_exist = work_areas_exist
        self._operations_coordinator = (
            operations_coordinator or ExternalAuthorityCurrentnessCoordinator()
        )
        # This resolver is roster metadata only. It never consults token
        # records and can neither authenticate nor grant permissions.
        self._assignment_member_is_active = assignment_member_is_active
        self._schedules: dict[str, ObservationSchedule] = {}
        self._orders: dict[str, ObservationWorkOrder] = {}
        self._drafts: dict[str, ReobservationDraft] = {}
        self._external_reobservation_authority_port = (
            external_reobservation_authority_port
            if external_reobservation_authority_port is not None
            else _ClosedExternalReobservationProposalAuthorityPort()
        )
        self._external_reobservation_bindings: dict[
            tuple[str, str], ExternalPlanningOnlyWorkOrderBindingV1
        ] = {}
        self._external_reobservation_receipts: dict[
            tuple[str, str], ExternalReobservationApprovalReceiptV1
        ] = {}
        self._external_reobservation_idempotency: dict[
            tuple[str, str, str], ExternalReobservationApprovalReceiptV1
        ] = {}
        self._external_reobservation_proposals: dict[
            tuple[str, str, int], ExternalReobservationApprovalReceiptV1
        ] = {}
        self._create_idempotency: dict[tuple[str, str, str], tuple[str, str]] = {}
        self._operations: dict[tuple[str, str], ObservationWorkOrderOperations] = {}
        self._operation_snapshots: dict[
            tuple[str, str, int], ObservationWorkOrderOperations
        ] = {}
        self._operations_idempotency: dict[
            tuple[str, str, str], tuple[str, ObservationWorkOrderOperations]
        ] = {}
        self._assignment_transitions: list[WorkOrderAssignmentTransition] = []
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

    @property
    def operations_coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        """The coordinator used to serialize administrative close with new intent commits."""

        return self._operations_coordinator

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
                if kind.endswith("created"):
                    create_idempotency = raw.get("createIdempotency")
                    if (
                        order.execution_mode
                        is ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION
                    ):
                        if not isinstance(create_idempotency, dict) or set(create_idempotency) != {
                            "keyHash",
                            "fingerprint",
                        }:
                            raise ValueError("external create idempotency evidence is missing")
                        key_hash = create_idempotency["keyHash"]
                        fingerprint = create_idempotency["fingerprint"]
                        if not self._is_create_digest(key_hash) or not self._is_create_digest(
                            fingerprint
                        ):
                            raise ValueError("external create idempotency evidence is malformed")
                        idempotency_key = (order.organization_id, order.created_by, key_hash)
                        if idempotency_key in self._create_idempotency:
                            raise ValueError("duplicate create idempotency key")
                        self._create_idempotency[idempotency_key] = (
                            order.work_order_id,
                            fingerprint,
                        )
                    elif create_idempotency is not None:
                        if not isinstance(create_idempotency, dict) or set(create_idempotency) != {
                            "keyHash",
                            "fingerprint",
                        }:
                            raise ValueError("create idempotency evidence is malformed")
                        key_hash = create_idempotency["keyHash"]
                        fingerprint = create_idempotency["fingerprint"]
                        if not self._is_create_digest(key_hash) or not self._is_create_digest(
                            fingerprint
                        ):
                            raise ValueError("create idempotency evidence is malformed")
                        idempotency_key = (order.organization_id, order.created_by, key_hash)
                        if idempotency_key in self._create_idempotency:
                            raise ValueError("duplicate create idempotency key")
                        self._create_idempotency[idempotency_key] = (
                            order.work_order_id,
                            fingerprint,
                        )
                if kind.endswith("updated") and "operations" in raw:
                    raise ValueError("WorkOrder update cannot carry operations state")
                self._orders[order.work_order_id] = order
                if kind.endswith("created") and "operations" in raw:
                    self._apply_initial_operations(order, raw["operations"], raw)
            elif kind == "observation-work-order-operations-updated":
                self._apply_operations_update(raw)
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
            elif kind == "external-reobservation-approved-and-next-order-created":
                self._apply_external_reobservation_approval(raw)
            else:
                raise ValueError(f"알 수 없는 kind: {kind!r}")
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ObservationWorkOrderStoreRecoveryError(
                f"observation work-order journal 재생 실패: {exc}"
            ) from exc

    def _append(self, raw: dict[str, Any]) -> None:
        self._journal.append(raw)
        self._apply(raw)

    @staticmethod
    def _legacy_operations(order: ObservationWorkOrder) -> ObservationWorkOrderOperations:
        """A missing old event is unknown, never evidence that the work is open."""

        return ObservationWorkOrderOperations(
            organization_id=order.organization_id,
            site_id=order.site_id,
            work_order_id=order.work_order_id,
            operations_revision=0,
            workflow_status=WorkOrderWorkflowStatus.UNSPECIFIED,
        )

    def _operations_for_order_locked(
        self, order: ObservationWorkOrder
    ) -> ObservationWorkOrderOperations:
        return self._operations.get(
            (order.organization_id, order.work_order_id), self._legacy_operations(order)
        )

    def _is_external_operations_order_locked(self, order: ObservationWorkOrder) -> bool:
        return (
            order.execution_mode is ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION
            or (order.organization_id, order.work_order_id)
            in self._external_reobservation_bindings
        )

    def _apply_initial_operations(
        self,
        order: ObservationWorkOrder,
        raw_operations: object,
        raw_event: dict[str, Any],
    ) -> None:
        if order.execution_mode is not ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION:
            raise ValueError("only a direct external WorkOrder can create operations state")
        operations = ObservationWorkOrderOperations.model_validate(raw_operations)
        if (
            operations.organization_id != order.organization_id
            or operations.site_id != order.site_id
            or operations.work_order_id != order.work_order_id
            or operations.operations_revision != 1
            or operations.workflow_status is not WorkOrderWorkflowStatus.OPEN
            or operations.assignee_principal_id is not None
            or operations.due_at is not None
            or operations.closed_at is not None
            or operations.closed_by is not None
            or operations.close_note is not None
            or operations.updated_at is None
            or operations.updated_by != order.created_by
            or raw_event["actor"] != order.created_by
            or raw_event["ts"] != iso_utc(operations.updated_at)
            or operations.updated_at != datetime.fromisoformat(order.created_at)
        ):
            raise ValueError(
                "initial external operations snapshot does not match WorkOrder creation"
            )
        key = (order.organization_id, order.work_order_id)
        if key in self._operations:
            raise ValueError("duplicate initial operations snapshot")
        self._operations[key] = operations
        self._operation_snapshots[(order.organization_id, order.work_order_id, 1)] = operations

    def _apply_operations_update(self, raw: dict[str, Any]) -> None:
        if set(raw) != {"kind", "ts", "actor", "operations", "idempotency"}:
            raise ValueError("operations update event keys are not exact")
        operations = ObservationWorkOrderOperations.model_validate(raw["operations"])
        order = self._orders.get(operations.work_order_id)
        if (
            order is None
            or order.organization_id != operations.organization_id
            or order.site_id != operations.site_id
            or not self._is_external_operations_order_locked(order)
        ):
            raise ValueError("operations event has an invalid external WorkOrder scope")
        current = self._operations_for_order_locked(order)
        if operations.operations_revision != current.operations_revision + 1:
            raise ValueError("operations revision lineage is invalid")
        if operations.updated_at is None or raw["actor"] != operations.updated_by:
            raise ValueError("operations update audit does not match event actor")
        if raw["ts"] != iso_utc(operations.updated_at):
            raise ValueError("operations update timestamp does not match event")
        binding = raw["idempotency"]
        if not isinstance(binding, dict) or set(binding) != {"keyHash", "fingerprint"}:
            raise ValueError("operations idempotency binding is malformed")
        key_hash = binding["keyHash"]
        fingerprint = binding["fingerprint"]
        if not self._is_create_digest(key_hash) or not self._is_create_digest(fingerprint):
            raise ValueError("operations idempotency binding is malformed")
        idempotency_key = (operations.organization_id, raw["actor"], key_hash)
        if idempotency_key in self._operations_idempotency:
            raise ValueError("duplicate operations idempotency key")
        snapshot_key = (
            operations.organization_id,
            operations.work_order_id,
            operations.operations_revision,
        )
        if snapshot_key in self._operation_snapshots:
            raise ValueError("duplicate operations revision snapshot")
        if (
            operations.assignee_principal_id is not None
            and operations.assignee_principal_id != current.assignee_principal_id
            and operations.assignee_principal_id != raw["actor"]
        ):
            assert operations.updated_at is not None  # snapshot validation above
            self._assignment_transitions.append(
                WorkOrderAssignmentTransition(
                    organization_id=operations.organization_id,
                    site_id=operations.site_id,
                    work_order_id=operations.work_order_id,
                    operations_revision=operations.operations_revision,
                    recipient_principal_id=operations.assignee_principal_id,
                    actor_principal_id=raw["actor"],
                    occurred_at=operations.updated_at,
                )
            )
        self._operations[(operations.organization_id, operations.work_order_id)] = operations
        self._operation_snapshots[snapshot_key] = operations
        self._operations_idempotency[idempotency_key] = (fingerprint, operations)

    @staticmethod
    def _external_successor_id(
        authority: ExternalReobservationProposalAuthorityV1,
    ) -> str:
        material = "\0".join(
            (
                authority.organization_id,
                authority.source_work_order_id,
                authority.proposal_id,
                str(authority.proposal_version),
                authority.proposal_digest,
            )
        )
        return f"obs-work-external-{hashlib.sha256(material.encode()).hexdigest()[:24]}"

    @staticmethod
    def _external_approval_id(
        approval_input: ExternalReobservationApprovalInputV1, idempotency_key: str
    ) -> str:
        material = "\0".join(
            (
                approval_input.organization_id,
                approval_input.source_work_order_id,
                approval_input.proposal_id,
                str(approval_input.proposal_version),
                approval_input.approval_input_digest or "",
                idempotency_key,
            )
        )
        return f"external-reobs-approval-{hashlib.sha256(material.encode()).hexdigest()[:24]}"

    @staticmethod
    def _require_sealed_approval_input(
        approval_input: ExternalReobservationApprovalInputV1,
    ) -> None:
        if (
            approval_input.approval_input_digest is None
            or approval_input.approval_input_digest != approval_input.canonical_digest()
        ):
            raise ValueError("external reobservation approval input must be sealed")

    @staticmethod
    def _require_sealed_authority(
        authority: ExternalReobservationProposalAuthorityV1,
    ) -> None:
        if (
            authority.authority_digest is None
            or authority.authority_digest != authority.canonical_digest()
        ):
            raise ValueError("external reobservation proposal authority must be sealed")

    @staticmethod
    def _approval_input_matches_authority(
        approval_input: ExternalReobservationApprovalInputV1,
        authority: ExternalReobservationProposalAuthorityV1,
    ) -> bool:
        return (
            approval_input.organization_id == authority.organization_id
            and approval_input.site_id == authority.site_id
            and approval_input.source_work_order_id == authority.source_work_order_id
            and approval_input.proposal_id == authority.proposal_id
            and approval_input.proposal_version == authority.proposal_version
            and approval_input.proposal_digest == authority.proposal_digest
            and approval_input.report_digest == authority.report_digest
            and approval_input.decision_digest == authority.decision_digest
            and approval_input.zone_digest == authority.zone_digest
            and approval_input.evidence_digests == authority.evidence_digests
        )

    @staticmethod
    def _require_sealed_binding(binding: ExternalPlanningOnlyWorkOrderBindingV1) -> None:
        if binding.binding_digest is None or binding.binding_digest != binding.canonical_digest():
            raise ValueError("external planning-only binding must be sealed")

    @staticmethod
    def _require_sealed_receipt(receipt: ExternalReobservationApprovalReceiptV1) -> None:
        if receipt.receipt_digest is None or receipt.receipt_digest != receipt.canonical_digest():
            raise ValueError("external reobservation approval receipt must be sealed")

    def _result_for_external_receipt(
        self, receipt: ExternalReobservationApprovalReceiptV1
    ) -> ExternalReobservationApprovalResult:
        binding = self._external_reobservation_bindings.get(
            (receipt.organization_id, receipt.successor_work_order_id)
        )
        successor = self._orders.get(receipt.successor_work_order_id)
        if binding is None or successor is None:
            raise ObservationWorkOrderStoreRecoveryError(
                "external reobservation approval projection is incomplete"
            )
        return ExternalReobservationApprovalResult(
            approval_receipt=receipt.model_copy(deep=True),
            planning_binding=binding.model_copy(deep=True),
            successor_work_order=successor.model_copy(deep=True),
        )

    def _apply_external_reobservation_approval(
        self,
        raw: dict[str, Any],
        *,
        historical_authority: ExternalReobservationProposalAuthorityV1 | None = None,
    ) -> None:
        expected_keys = {
            "kind",
            "ts",
            "actor",
            "approvalInput",
            "authoritySnapshot",
            "approvalReceipt",
            "planningBinding",
            "successorWorkOrder",
        }
        if set(raw) != expected_keys:
            raise ValueError("external reobservation approval event keys are not exact")
        approval_input = ExternalReobservationApprovalInputV1.model_validate(raw["approvalInput"])
        authority = ExternalReobservationProposalAuthorityV1.model_validate(
            raw["authoritySnapshot"]
        )
        receipt = ExternalReobservationApprovalReceiptV1.model_validate(raw["approvalReceipt"])
        binding = ExternalPlanningOnlyWorkOrderBindingV1.model_validate(raw["planningBinding"])
        successor = ObservationWorkOrder.model_validate(raw["successorWorkOrder"])
        self._require_sealed_approval_input(approval_input)
        self._require_sealed_authority(authority)
        self._require_sealed_receipt(receipt)
        self._require_sealed_binding(binding)
        if not self._approval_input_matches_authority(approval_input, authority):
            raise ValueError("approval input does not match sealed proposal authority")
        if historical_authority is None:
            historical_authority = self._external_reobservation_authority_port.resolve_historical(
                organization_id=approval_input.organization_id,
                approval_input=approval_input,
                actor=receipt.approved_by,
                approved_at=receipt.approved_at,
            )
        if historical_authority is None:
            raise ValueError("external reobservation historical authority is unavailable")
        self._require_sealed_authority(historical_authority)
        if historical_authority.authority_digest != authority.authority_digest:
            raise ValueError("external event does not match historical accepted proposal authority")
        source = self._orders.get(approval_input.source_work_order_id)
        if source is None:
            raise ValueError("external successor source WorkOrder is missing")
        if (
            source.organization_id != approval_input.organization_id
            or source.site_id != approval_input.site_id
        ):
            raise ValueError("external successor source scope or WorkArea lineage does not match")
        target_work_area_ids = [item.work_area_id for item in authority.target_work_areas]
        successor_id = self._external_successor_id(authority)
        if successor.work_order_id != successor_id:
            raise ValueError("external successor WorkOrder ID is not deterministic")
        if (
            successor.organization_id != source.organization_id
            or successor.site_id != source.site_id
            or successor.purpose is not ObservationPurpose.PROGRESS_QUANTITY
            or successor.schedule_id is not None
            or successor.execution_mode is ObservationWorkOrderExecutionMode.MANAGED_ACQUISITION
            or successor.status is not ObservationWorkOrderStatus.APPROVED
            or successor.cycle_number != 1
            or successor.work_area_ids != target_work_area_ids
            or successor.temporal_policy != source.temporal_policy
            or successor.approved_by != receipt.approved_by
            or successor.approved_at != iso_utc(receipt.approved_at)
            or successor.created_by != receipt.approved_by
            or successor.created_at != iso_utc(receipt.approved_at)
            or successor.updated_at != iso_utc(receipt.approved_at)
            or successor.version != 1
        ):
            raise ValueError("external successor WorkOrder does not match sealed approval")
        if (
            binding.organization_id != source.organization_id
            or binding.site_id != source.site_id
            or binding.source_work_order_id != source.work_order_id
            or binding.successor_work_order_id != successor.work_order_id
            or binding.approval_id != receipt.approval_id
            or binding.approved_by != receipt.approved_by
            or binding.approved_at != receipt.approved_at
            or binding.proposal_id != authority.proposal_id
            or binding.proposal_version != authority.proposal_version
            or binding.proposal_digest != authority.proposal_digest
            or binding.report_digest != authority.report_digest
            or binding.decision_digest != authority.decision_digest
            or binding.zone_digest != authority.zone_digest
            or binding.evidence_digests != authority.evidence_digests
            or binding.target_work_areas != authority.target_work_areas
            or binding.temporal_policy != source.temporal_policy
            or binding.acquisition_run_allowed is not False
            or binding.mission_issuance_allowed is not False
        ):
            raise ValueError("external planning-only binding does not match sealed authority")
        if (
            receipt.organization_id != source.organization_id
            or receipt.site_id != source.site_id
            or receipt.source_work_order_id != source.work_order_id
            or receipt.successor_work_order_id != successor.work_order_id
            or receipt.proposal_id != authority.proposal_id
            or receipt.proposal_version != authority.proposal_version
            or receipt.proposal_digest != authority.proposal_digest
            or receipt.approval_input_digest != approval_input.approval_input_digest
            or receipt.binding_digest != binding.binding_digest
            or receipt.approval_id
            != self._external_approval_id(approval_input, receipt.idempotency_key)
            or raw["actor"] != receipt.approved_by
            or raw["ts"] != iso_utc(receipt.approved_at)
        ):
            raise ValueError("external reobservation receipt does not match sealed approval")
        successor_key = (source.organization_id, successor.work_order_id)
        idempotency_key = (
            source.organization_id,
            source.work_order_id,
            receipt.idempotency_key,
        )
        proposal_key = (source.organization_id, authority.proposal_id, authority.proposal_version)
        if (
            successor.work_order_id in self._orders
            or successor_key in self._external_reobservation_bindings
            or idempotency_key in self._external_reobservation_idempotency
            or proposal_key in self._external_reobservation_proposals
        ):
            raise ValueError("duplicate external reobservation approval or successor WorkOrder")
        self._orders[successor.work_order_id] = successor
        self._external_reobservation_bindings[successor_key] = binding
        self._external_reobservation_receipts[successor_key] = receipt
        self._external_reobservation_idempotency[idempotency_key] = receipt
        self._external_reobservation_proposals[proposal_key] = receipt

    def _append_external_reobservation_approval(
        self,
        raw: dict[str, Any],
        *,
        historical_authority: ExternalReobservationProposalAuthorityV1,
    ) -> None:
        """Append/apply an externally prevalidated event without calling a port under the lock."""

        self._journal.append(raw)
        self._apply_external_reobservation_approval(raw, historical_authority=historical_authority)

    def _validate_scope(
        self, *, organization_id: str, site_id: str, work_area_ids: list[str]
    ) -> None:
        self._validate_site_scope(organization_id=organization_id, site_id=site_id)
        if any(not is_path_safe_identifier(item) for item in work_area_ids):
            raise ValueError("workAreaIds 는 경로-안전 비공백 식별자여야 한다")
        if self._work_areas_exist is not None and not self._work_areas_exist(
            site_id, work_area_ids
        ):
            raise LookupError("현장에 속한 ACTIVE 작업구역을 찾을 수 없다")

    def _validate_site_scope(self, *, organization_id: str, site_id: str) -> None:
        if not is_path_safe_identifier(organization_id):
            raise ValueError("organizationId 는 경로-안전 비공백 식별자여야 한다")
        if not is_path_safe_identifier(site_id):
            raise ValueError("siteId 는 경로-안전 비공백 식별자여야 한다")
        if not self._site_exists(site_id, organization_id):
            raise LookupError("현장을 찾을 수 없다")

    @staticmethod
    def _is_create_digest(value: object) -> bool:
        return isinstance(value, str) and len(value) == 71 and value.startswith("sha256:") and all(
            character in "0123456789abcdef" for character in value[7:]
        )

    @staticmethod
    def _external_create_fingerprint(
        *,
        site_id: str,
        name: str,
        work_area_ids: list[str],
        schedule_id: str | None,
        temporal_policy: TemporalCoherencePolicy | None,
        execution_mode: ObservationWorkOrderExecutionMode,
    ) -> str:
        """Hash a normalized create body; the raw Idempotency-Key is never retained."""

        normalized = {
            "executionMode": execution_mode.value,
            "name": name.strip(),
            "scheduleId": schedule_id,
            "siteId": site_id,
            "temporalPolicy": (
                temporal_policy.model_dump(mode="json", by_alias=True)
                if temporal_policy is not None
                else None
            ),
            "workAreaIds": work_area_ids,
        }
        material = json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(material).hexdigest()

    @staticmethod
    def _external_create_key_hash(idempotency_key: str) -> str:
        return "sha256:" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()

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
        temporal_policy: TemporalCoherencePolicy | None = None,
        execution_mode: ObservationWorkOrderExecutionMode = (
            ObservationWorkOrderExecutionMode.MANAGED_ACQUISITION
        ),
        idempotency_key: str | None = None,
        actor: str,
        now: datetime,
    ) -> ObservationWorkOrder:
        try:
            normalized_execution_mode = ObservationWorkOrderExecutionMode(execution_mode)
        except ValueError as exc:
            raise ValueError("executionMode is invalid") from exc
        if normalized_execution_mode is ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION:
            if schedule_id is not None:
                raise ValueError("EXTERNAL_RECONSTRUCTION requires scheduleId to be null")
            if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 255:
                raise ValueError("Idempotency-Key is required for EXTERNAL_RECONSTRUCTION")
        elif idempotency_key is not None and (
            not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 255
        ):
            raise ValueError("Idempotency-Key must be between 1 and 255 characters")
        # Retrying a lost response must still find the retained WorkOrder after its
        # WorkArea was archived. Site/org scope remains checked before any replay.
        self._validate_site_scope(organization_id=organization_id, site_id=site_id)
        create_idempotency: dict[str, str] | None = None
        if idempotency_key is not None:
            key_hash = self._external_create_key_hash(idempotency_key)
            fingerprint = self._external_create_fingerprint(
                site_id=site_id,
                name=name,
                work_area_ids=work_area_ids,
                schedule_id=schedule_id,
                temporal_policy=temporal_policy,
                execution_mode=normalized_execution_mode,
            )
            create_idempotency = {"keyHash": key_hash, "fingerprint": fingerprint}
            with self._lock:
                existing = self._create_idempotency.get(
                    (organization_id, actor, key_hash)
                )
                if existing is not None:
                    existing_id, existing_fingerprint = existing
                    if existing_fingerprint != fingerprint:
                        raise RuntimeError("EXTERNAL_CREATE_IDEMPOTENCY_CONFLICT")
                    current = self._orders.get(existing_id)
                    if current is None:
                        raise ObservationWorkOrderStoreRecoveryError(
                            "external create idempotency points to a missing WorkOrder"
                        )
                    return current.model_copy(deep=True)
        self._validate_scope(
            organization_id=organization_id,
            site_id=site_id,
            work_area_ids=work_area_ids,
        )
        with self._lock:
            if create_idempotency is not None:
                existing = self._create_idempotency.get(
                    (organization_id, actor, create_idempotency["keyHash"])
                )
                if existing is not None:
                    existing_id, existing_fingerprint = existing
                    if existing_fingerprint != create_idempotency["fingerprint"]:
                        raise RuntimeError("EXTERNAL_CREATE_IDEMPOTENCY_CONFLICT")
                    current = self._orders.get(existing_id)
                    if current is None:
                        raise ObservationWorkOrderStoreRecoveryError(
                            "external create idempotency points to a missing WorkOrder"
                        )
                    return current.model_copy(deep=True)
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
                temporal_policy=temporal_policy,
                execution_mode=normalized_execution_mode,
                status=(
                    ObservationWorkOrderStatus.APPROVED
                    if normalized_execution_mode
                    is ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION
                    else ObservationWorkOrderStatus.AWAITING_APPROVAL
                ),
                version=1,
                created_at=iso_utc(now),
                updated_at=iso_utc(now),
                created_by=actor,
                approved_at=(
                    iso_utc(now)
                    if normalized_execution_mode
                    is ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION
                    else None
                ),
                approved_by=(
                    actor
                    if normalized_execution_mode
                    is ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION
                    else None
                ),
            )
            raw: dict[str, Any] = {
                "kind": "observation-work-order-created",
                "ts": iso_utc(now),
                "actor": actor,
                "workOrder": order.model_dump(by_alias=True, mode="json"),
            }
            if (
                normalized_execution_mode
                is ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION
            ):
                operations = ObservationWorkOrderOperations(
                    organization_id=organization_id,
                    site_id=site_id,
                    work_order_id=work_order_id,
                    operations_revision=1,
                    workflow_status=WorkOrderWorkflowStatus.OPEN,
                    updated_at=now,
                    updated_by=actor,
                )
                raw["operations"] = operations.model_dump(by_alias=True, mode="json")
            if create_idempotency is not None:
                raw["createIdempotency"] = create_idempotency
            self._append(raw)
            return order

    def get(self, work_order_id: str, *, organization_id: str) -> ObservationWorkOrder | None:
        with self._lock:
            order = self._orders.get(work_order_id)
            if order is None or order.organization_id != organization_id:
                return None
            return order

    @staticmethod
    def _operations_key_hash(idempotency_key: str) -> str:
        return "sha256:" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _operations_fingerprint(
        *,
        work_order_id: str,
        expected_operations_revision: int,
        action: str,
        due_at: datetime | None = None,
        note: str | None = None,
        assignee_principal_id: str | None = None,
    ) -> str:
        material = json.dumps(
            {
                "action": action,
                "assigneePrincipalId": assignee_principal_id,
                "dueAt": iso_utc(due_at) if due_at is not None else None,
                "expectedOperationsRevision": expected_operations_revision,
                "note": note,
                "workOrderId": work_order_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(material).hexdigest()

    @staticmethod
    def _validate_operations_mutation_input(
        *, actor: str, idempotency_key: str, now: datetime, expected_operations_revision: int
    ) -> None:
        if not is_path_safe_identifier(actor):
            raise ValueError("operations actor must be a path-safe identifier")
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key.strip()) <= 255:
            raise ValueError("Idempotency-Key must be a nonblank value up to 255 characters")
        if now.tzinfo is None:
            raise ValueError("operations timestamp must be timezone-aware")
        if (
            type(expected_operations_revision) is not int
            or expected_operations_revision < 0
        ):
            raise ValueError("expectedOperationsRevision must be a nonnegative integer")

    def _require_external_operations_order_locked(
        self, *, work_order_id: str, organization_id: str
    ) -> ObservationWorkOrder:
        order = self._orders.get(work_order_id)
        if order is None or order.organization_id != organization_id:
            raise LookupError("관측 작업을 찾을 수 없다")
        if not self._is_external_operations_order_locked(order):
            raise RuntimeError("EXTERNAL_OPERATIONS_ONLY")
        return order

    def get_operations(
        self, work_order_id: str, *, organization_id: str
    ) -> ObservationWorkOrderOperations:
        with self._lock:
            order = self._require_external_operations_order_locked(
                work_order_id=work_order_id, organization_id=organization_id
            )
            return self._operations_for_order_locked(order).model_copy(deep=True)

    def list_operations(
        self,
        *,
        organization_id: str,
        site_id: str | None = None,
        workflow_status: WorkOrderWorkflowStatus | None = None,
    ) -> list[ObservationWorkOrderOperations]:
        if site_id is not None:
            self._validate_site_scope(organization_id=organization_id, site_id=site_id)
        with self._lock:
            operations = [
                self._operations_for_order_locked(order).model_copy(deep=True)
                for order in self._orders.values()
                if order.organization_id == organization_id
                and (site_id is None or order.site_id == site_id)
            ]
        if workflow_status is not None:
            operations = [
                item for item in operations if item.workflow_status is workflow_status
            ]
        return sorted(
            operations,
            key=lambda item: (
                item.updated_at or datetime.min.replace(tzinfo=UTC),
                item.work_order_id,
            ),
            reverse=True,
        )

    def list_assignment_transitions(
        self, *, organization_id: str, recipient_principal_id: str
    ) -> list[WorkOrderAssignmentTransition]:
        """Return retained assignment transitions addressed to one recipient.

        The list is reconstructed from the WorkOrder operations journal on every
        restart, so a notification does not require a second write or a fragile
        asynchronous outbox.
        """

        with self._lock:
            return [
                item
                for item in self._assignment_transitions
                if item.organization_id == organization_id
                and item.recipient_principal_id == recipient_principal_id
            ]

    def _mutate_operations(
        self,
        work_order_id: str,
        *,
        organization_id: str,
        expected_operations_revision: int,
        actor: str,
        idempotency_key: str,
        now: datetime,
        action: str,
        due_at: datetime | None = None,
        note: str | None = None,
        assignee_principal_id: str | None = None,
    ) -> ObservationWorkOrderOperations:
        self._validate_operations_mutation_input(
            actor=actor,
            idempotency_key=idempotency_key,
            now=now,
            expected_operations_revision=expected_operations_revision,
        )
        if due_at is not None and due_at.tzinfo is None:
            raise ValueError("dueAt must include a timezone")
        normalized_due_at = due_at.astimezone(UTC) if due_at is not None else None
        normalized_note = note.strip() if note is not None else None
        if normalized_note is not None and not normalized_note:
            raise ValueError("close note must not be blank")
        if assignee_principal_id is not None and not is_path_safe_identifier(assignee_principal_id):
            raise ValueError("assigneePrincipalId must be a path-safe identifier")
        key_hash = self._operations_key_hash(idempotency_key)
        fingerprint = self._operations_fingerprint(
            work_order_id=work_order_id,
            expected_operations_revision=expected_operations_revision,
            action=action,
            due_at=normalized_due_at,
            note=normalized_note,
            assignee_principal_id=assignee_principal_id,
        )
        with self._operations_coordinator.mutation(), self._lock:
            prior = self._operations_idempotency.get((organization_id, actor, key_hash))
            if prior is not None:
                prior_fingerprint, prior_operations = prior
                if prior_fingerprint != fingerprint:
                    raise RuntimeError("OPERATIONS_IDEMPOTENCY_CONFLICT")
                return prior_operations.model_copy(deep=True)
            order = self._require_external_operations_order_locked(
                work_order_id=work_order_id, organization_id=organization_id
            )
            current = self._operations_for_order_locked(order)
            if current.operations_revision != expected_operations_revision:
                raise RuntimeError("OPERATIONS_REVISION_CONFLICT")
            if action == WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER.value and (
                assignee_principal_id is None
                or self._assignment_member_is_active is None
                or not self._assignment_member_is_active(
                    assignee_principal_id, organization_id=organization_id
                )
            ):
                # Target identity/organization/inactive status intentionally
                # collapse with a missing scoped target (INV-060).
                raise LookupError("work assignment target was not found")
            if action in {
                WorkOrderOperationsAssignmentAction.ASSIGN_TO_ME.value,
                WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER.value,
                WorkOrderOperationsAssignmentAction.CLEAR.value,
                "SET_DUE_DATE",
            }:
                if current.workflow_status is WorkOrderWorkflowStatus.CLOSED:
                    raise RuntimeError("OPERATIONS_INVALID_STATE")
                workflow_status = WorkOrderWorkflowStatus.OPEN
                assignee_principal_id = (
                    actor
                    if action == WorkOrderOperationsAssignmentAction.ASSIGN_TO_ME.value
                    else assignee_principal_id
                    if action == WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER.value
                    else None
                    if action == WorkOrderOperationsAssignmentAction.CLEAR.value
                    else current.assignee_principal_id
                )
                candidate_due_at = normalized_due_at if action == "SET_DUE_DATE" else current.due_at
                closed_at = closed_by = close_note = None
            elif action == "CLOSE":
                if current.workflow_status not in {
                    WorkOrderWorkflowStatus.UNSPECIFIED,
                    WorkOrderWorkflowStatus.OPEN,
                }:
                    raise RuntimeError("OPERATIONS_INVALID_STATE")
                workflow_status = WorkOrderWorkflowStatus.CLOSED
                assignee_principal_id = current.assignee_principal_id
                candidate_due_at = current.due_at
                closed_at, closed_by, close_note = now.astimezone(UTC), actor, normalized_note
            elif action == "REOPEN":
                if current.workflow_status is not WorkOrderWorkflowStatus.CLOSED:
                    raise RuntimeError("OPERATIONS_INVALID_STATE")
                workflow_status = WorkOrderWorkflowStatus.OPEN
                assignee_principal_id = current.assignee_principal_id
                candidate_due_at = current.due_at
                closed_at = closed_by = close_note = None
            else:
                raise ValueError("operations action is invalid")
            updated = ObservationWorkOrderOperations(
                organization_id=order.organization_id,
                site_id=order.site_id,
                work_order_id=order.work_order_id,
                operations_revision=current.operations_revision + 1,
                workflow_status=workflow_status,
                assignee_principal_id=assignee_principal_id,
                due_at=candidate_due_at,
                closed_at=closed_at,
                closed_by=closed_by,
                close_note=close_note,
                updated_at=now.astimezone(UTC),
                updated_by=actor,
            )
            self._append(
                {
                    "kind": "observation-work-order-operations-updated",
                    "ts": iso_utc(now),
                    "actor": actor,
                    "operations": updated.model_dump(by_alias=True, mode="json"),
                    "idempotency": {"keyHash": key_hash, "fingerprint": fingerprint},
                }
            )
            return updated.model_copy(deep=True)

    def assign_operations_to_me(
        self,
        work_order_id: str,
        *,
        organization_id: str,
        expected_operations_revision: int,
        action: WorkOrderOperationsAssignmentAction,
        actor: str,
        idempotency_key: str,
        now: datetime,
    ) -> ObservationWorkOrderOperations:
        if action not in {
            WorkOrderOperationsAssignmentAction.ASSIGN_TO_ME,
            WorkOrderOperationsAssignmentAction.CLEAR,
        }:
            raise ValueError("assignment action must use assign-to-member route")
        return self._mutate_operations(
            work_order_id,
            organization_id=organization_id,
            expected_operations_revision=expected_operations_revision,
            actor=actor,
            idempotency_key=idempotency_key,
            now=now,
            action=action.value,
        )

    def assign_operations_to_member(
        self,
        work_order_id: str,
        *,
        organization_id: str,
        expected_operations_revision: int,
        action: WorkOrderOperationsAssignmentAction,
        assignee_principal_id: str,
        actor: str,
        idempotency_key: str,
        now: datetime,
    ) -> ObservationWorkOrderOperations:
        if action is not WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER:
            raise ValueError("assignment action must be ASSIGN_TO_MEMBER")
        return self._mutate_operations(
            work_order_id,
            organization_id=organization_id,
            expected_operations_revision=expected_operations_revision,
            actor=actor,
            idempotency_key=idempotency_key,
            now=now,
            action=action.value,
            assignee_principal_id=assignee_principal_id,
        )

    def set_operations_due_date(
        self,
        work_order_id: str,
        *,
        organization_id: str,
        expected_operations_revision: int,
        due_at: datetime | None,
        actor: str,
        idempotency_key: str,
        now: datetime,
    ) -> ObservationWorkOrderOperations:
        return self._mutate_operations(
            work_order_id,
            organization_id=organization_id,
            expected_operations_revision=expected_operations_revision,
            actor=actor,
            idempotency_key=idempotency_key,
            now=now,
            action="SET_DUE_DATE",
            due_at=due_at,
        )

    def close_operations(
        self,
        work_order_id: str,
        *,
        organization_id: str,
        expected_operations_revision: int,
        note: str | None,
        actor: str,
        idempotency_key: str,
        now: datetime,
    ) -> ObservationWorkOrderOperations:
        return self._mutate_operations(
            work_order_id,
            organization_id=organization_id,
            expected_operations_revision=expected_operations_revision,
            actor=actor,
            idempotency_key=idempotency_key,
            now=now,
            action="CLOSE",
            note=note,
        )

    def reopen_operations(
        self,
        work_order_id: str,
        *,
        organization_id: str,
        expected_operations_revision: int,
        actor: str,
        idempotency_key: str,
        now: datetime,
    ) -> ObservationWorkOrderOperations:
        return self._mutate_operations(
            work_order_id,
            organization_id=organization_id,
            expected_operations_revision=expected_operations_revision,
            actor=actor,
            idempotency_key=idempotency_key,
            now=now,
            action="REOPEN",
        )

    @contextmanager
    def guard_new_external_intent(
        self,
        work_order_id: str,
        *,
        organization_id: str,
        is_durable_retry: Callable[[], bool] | None = None,
    ) -> Iterator[None]:
        """Serialize a new external intent with administrative close/reopen.

        The caller's retry probe must perform only retained local reads.  It runs
        under the same coordinator and preserves a previously durable result
        after closure; a fresh mutation receives ``EXTERNAL_WORKFLOW_CLOSED``.
        Lock order is coordinator, WorkOrder, then the caller's own ledger.
        """

        with self._operations_coordinator.guarded_read(), self._lock:
            order = self._orders.get(work_order_id)
            if order is None or order.organization_id != organization_id:
                raise LookupError("관측 작업을 찾을 수 없다")
            if self._is_external_operations_order_locked(order) and (
                self._operations_for_order_locked(order).workflow_status
                is WorkOrderWorkflowStatus.CLOSED
            ) and (is_durable_retry is None or not is_durable_retry()):
                raise RuntimeError("EXTERNAL_WORKFLOW_CLOSED")
            yield

    def assert_new_external_intent_allowed(
        self, work_order_id: str, *, organization_id: str
    ) -> None:
        """One-shot compatibility check; writers should retain ``guard_*`` to commit."""

        with self.guard_new_external_intent(
            work_order_id, organization_id=organization_id
        ):
            return

    def is_external_workflow_closed(
        self, work_order_id: str, *, organization_id: str
    ) -> bool:
        """Read only the administrative closure state; unknown historical rows stay false."""

        with self._lock:
            order = self._orders.get(work_order_id)
            return bool(
                order is not None
                and order.organization_id == organization_id
                and self._is_external_operations_order_locked(order)
                and self._operations_for_order_locked(order).workflow_status
                is WorkOrderWorkflowStatus.CLOSED
            )

    @contextmanager
    def issuance_commit_guard(
        self, work_order_id: str, *, organization_id: str
    ) -> Iterator[ObservationWorkOrder | None]:
        """Mission commit 동안 WorkOrder version/status/cycle 변경을 막는다.

        Site guard 뒤, Acquisition guard 앞에서 획득하는 것이 유일한 허용 순서다.
        반환 객체는 Pydantic immutable snapshot으로 취급하며 coordinator가 witness와
        exact equality를 검사한다.
        """

        with self._lock:
            order = self._orders.get(work_order_id)
            if order is None or order.organization_id != organization_id:
                yield None
                return
            yield order

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
                item for item in self._orders.values() if item.organization_id == organization_id
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
            self._assert_execution_allowed_current(current, supplied_work_order=current)
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

    def approve_external_reobservation(
        self,
        approval_input: ExternalReobservationApprovalInputV1,
        *,
        organization_id: str,
        actor: str,
        now: datetime,
        idempotency_key: str,
    ) -> ExternalReobservationApprovalResult:
        """Atomically create one non-executable external successor WorkOrder.

        ``approval_input`` is constructed by the authenticated adapter, not a
        caller declaration of acceptance. The injected port must resolve both
        current and independently persisted historical accepted authority.
        """

        if now.tzinfo is None:
            raise ValueError("now는 tz-aware여야 한다")
        self._require_sealed_approval_input(approval_input)
        if approval_input.organization_id != organization_id:
            raise LookupError("external reobservation approval organization scope does not match")
        if not is_path_safe_identifier(actor) or not is_path_safe_identifier(idempotency_key):
            raise ValueError("actor와 idempotencyKey는 경로-안전 식별자여야 한다")

        idempotency_map_key = (
            organization_id,
            approval_input.source_work_order_id,
            idempotency_key,
        )
        proposal_map_key = (
            organization_id,
            approval_input.proposal_id,
            approval_input.proposal_version,
        )
        with self._lock:
            idempotent_receipt = self._external_reobservation_idempotency.get(idempotency_map_key)
            if idempotent_receipt is not None:
                if idempotent_receipt.approval_input_digest != approval_input.approval_input_digest:
                    raise RuntimeError("EXTERNAL_REOBSERVATION_APPROVAL_CONFLICT")
                return self._result_for_external_receipt(idempotent_receipt)
            proposal_receipt = self._external_reobservation_proposals.get(proposal_map_key)
            if proposal_receipt is not None:
                if proposal_receipt.approval_input_digest != approval_input.approval_input_digest:
                    raise RuntimeError("EXTERNAL_REOBSERVATION_APPROVAL_CONFLICT")
                return self._result_for_external_receipt(proposal_receipt)

        historical_authority = self._external_reobservation_authority_port.resolve_historical(
            organization_id=organization_id,
            approval_input=approval_input,
            actor=actor,
            approved_at=now,
        )
        if historical_authority is None:
            raise RuntimeError("EXTERNAL_REOBSERVATION_HISTORICAL_AUTHORITY_UNAVAILABLE")
        self._require_sealed_authority(historical_authority)
        if not self._approval_input_matches_authority(approval_input, historical_authority):
            raise RuntimeError("EXTERNAL_REOBSERVATION_AUTHORITY_CONFLICT")

        with self._external_reobservation_authority_port.guard_current(
            organization_id=organization_id,
            approval_input=approval_input,
            actor=actor,
            evaluated_at=now,
        ) as resolved_authority:
            if resolved_authority is None:
                raise RuntimeError("EXTERNAL_REOBSERVATION_AUTHORITY_UNAVAILABLE")
            self._require_sealed_authority(resolved_authority)
            if (
                not self._approval_input_matches_authority(approval_input, resolved_authority)
                or resolved_authority.authority_digest != historical_authority.authority_digest
            ):
                raise RuntimeError("EXTERNAL_REOBSERVATION_AUTHORITY_CONFLICT")

            with self._lock:
                # A competing approval can finish while the authority port resolves.
                idempotent_receipt = self._external_reobservation_idempotency.get(
                    idempotency_map_key
                )
                if idempotent_receipt is not None:
                    if (
                        idempotent_receipt.approval_input_digest
                        != approval_input.approval_input_digest
                    ):
                        raise RuntimeError("EXTERNAL_REOBSERVATION_APPROVAL_CONFLICT")
                    return self._result_for_external_receipt(idempotent_receipt)
                proposal_receipt = self._external_reobservation_proposals.get(proposal_map_key)
                if proposal_receipt is not None:
                    if (
                        proposal_receipt.approval_input_digest
                        != approval_input.approval_input_digest
                    ):
                        raise RuntimeError("EXTERNAL_REOBSERVATION_APPROVAL_CONFLICT")
                    return self._result_for_external_receipt(proposal_receipt)

                source = self._orders.get(approval_input.source_work_order_id)
                if source is None or source.organization_id != organization_id:
                    raise LookupError("관측 작업을 찾을 수 없다")
                if self._is_external_operations_order_locked(source) and (
                    self._operations_for_order_locked(source).workflow_status
                    is WorkOrderWorkflowStatus.CLOSED
                ):
                    raise RuntimeError("EXTERNAL_WORKFLOW_CLOSED")
                target_work_area_ids = [
                    item.work_area_id for item in resolved_authority.target_work_areas
                ]
                # Exact Site/target currentness is already held by the outer guard.
                # Do not call independent scope stores while holding this lock.
                if (
                    source.site_id != resolved_authority.site_id
                    or source.site_id != approval_input.site_id
                ):
                    raise RuntimeError("EXTERNAL_REOBSERVATION_WORK_AREA_CONFLICT")
                successor_work_order_id = self._external_successor_id(resolved_authority)
                if successor_work_order_id in self._orders:
                    raise RuntimeError("EXTERNAL_REOBSERVATION_SUCCESSOR_CONFLICT")
                successor = ObservationWorkOrder(
                    work_order_id=successor_work_order_id,
                    organization_id=organization_id,
                    site_id=source.site_id,
                    purpose=ObservationPurpose.PROGRESS_QUANTITY,
                    name=source.name,
                    work_area_ids=target_work_area_ids,
                    schedule_id=None,
                    temporal_policy=source.temporal_policy,
                    execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
                    cycle_number=1,
                    status=ObservationWorkOrderStatus.APPROVED,
                    version=1,
                    created_at=iso_utc(now),
                    updated_at=iso_utc(now),
                    created_by=actor,
                    approved_at=iso_utc(now),
                    approved_by=actor,
                )
                approval_id = self._external_approval_id(approval_input, idempotency_key)
                binding = ExternalPlanningOnlyWorkOrderBindingV1(
                    organization_id=organization_id,
                    site_id=source.site_id,
                    source_work_order_id=source.work_order_id,
                    successor_work_order_id=successor.work_order_id,
                    approval_id=approval_id,
                    approved_by=actor,
                    approved_at=now,
                    proposal_id=resolved_authority.proposal_id,
                    proposal_version=resolved_authority.proposal_version,
                    proposal_digest=resolved_authority.proposal_digest,
                    report_digest=resolved_authority.report_digest,
                    decision_digest=resolved_authority.decision_digest,
                    zone_digest=resolved_authority.zone_digest,
                    evidence_digests=resolved_authority.evidence_digests,
                    target_work_areas=resolved_authority.target_work_areas,
                    temporal_policy=source.temporal_policy,
                ).sealed()
                assert approval_input.approval_input_digest is not None
                assert binding.binding_digest is not None
                receipt = ExternalReobservationApprovalReceiptV1(
                    approval_id=approval_id,
                    organization_id=organization_id,
                    site_id=source.site_id,
                    source_work_order_id=source.work_order_id,
                    successor_work_order_id=successor.work_order_id,
                    proposal_id=resolved_authority.proposal_id,
                    proposal_version=resolved_authority.proposal_version,
                    proposal_digest=resolved_authority.proposal_digest,
                    approval_input_digest=approval_input.approval_input_digest,
                    binding_digest=binding.binding_digest,
                    idempotency_key=idempotency_key,
                    approved_by=actor,
                    approved_at=now,
                ).sealed()
                raw = {
                    "kind": "external-reobservation-approved-and-next-order-created",
                    "ts": iso_utc(now),
                    "actor": actor,
                    "approvalInput": approval_input.model_dump(by_alias=True, mode="json"),
                    "authoritySnapshot": resolved_authority.model_dump(by_alias=True, mode="json"),
                    "approvalReceipt": receipt.model_dump(by_alias=True, mode="json"),
                    "planningBinding": binding.model_dump(by_alias=True, mode="json"),
                    "successorWorkOrder": successor.model_dump(by_alias=True, mode="json"),
                }
                self._append_external_reobservation_approval(
                    raw, historical_authority=historical_authority
                )
                return self._result_for_external_receipt(receipt)

    def get_external_reobservation_binding(
        self, work_order_id: str, *, organization_id: str
    ) -> ExternalPlanningOnlyWorkOrderBindingV1 | None:
        with self._lock:
            binding = self._external_reobservation_bindings.get((organization_id, work_order_id))
            return binding.model_copy(deep=True) if binding is not None else None

    def get_external_reobservation_approval(
        self,
        proposal_id: str,
        *,
        expected_version: int,
        organization_id: str,
    ) -> ExternalReobservationApprovalReceiptV1 | None:
        """Read the sole kernel-owned approval receipt by exact proposal version.

        Proposal status is a joined projection of this immutable receipt.  This
        accessor appends nothing and deliberately exposes no generic approval
        mutator or callback.
        """

        if type(expected_version) is not int or isinstance(expected_version, bool):
            return None
        with self._lock:
            receipt = self._external_reobservation_proposals.get(
                (organization_id, proposal_id, expected_version)
            )
            return receipt.model_copy(deep=True) if receipt is not None else None

    def uses_external_reobservation_authority(
        self,
        authority: ExternalReobservationProposalAuthorityPort,
    ) -> bool:
        """Constructor-owned authority identity for assembled graph validation."""
        return self._external_reobservation_authority_port is authority

    def external_reobservation_organization_ids(self) -> frozenset[str]:
        """Enumerate retained binding owners independently of current Site state."""
        with self._lock:
            return frozenset(org for org, _ in self._external_reobservation_bindings)

    def list_external_reobservation_bindings(
        self, *, organization_id: str, site_id: str | None = None
    ) -> list[ExternalPlanningOnlyWorkOrderBindingV1]:
        with self._lock:
            bindings = [
                binding
                for (
                    binding_organization_id,
                    _,
                ), binding in self._external_reobservation_bindings.items()
                if binding_organization_id == organization_id
                and (site_id is None or binding.site_id == site_id)
            ]
        return sorted(
            (item.model_copy(deep=True) for item in bindings),
            key=lambda item: item.successor_work_order_id,
        )

    def _assert_execution_allowed_current(
        self,
        current: ObservationWorkOrder,
        *,
        supplied_work_order: ObservationWorkOrder,
    ) -> None:
        if current != supplied_work_order:
            raise RuntimeError("WORK_ORDER_SNAPSHOT_MISMATCH")
        if current.execution_mode is ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION:
            raise ExternalReconstructionExecutionDenied("EXTERNAL_RECONSTRUCTION_ONLY")
        if (
            current.organization_id,
            current.work_order_id,
        ) in self._external_reobservation_bindings:
            raise ExternalReconstructionExecutionDenied("EXTERNAL_RECONSTRUCTION_ONLY")

    def assert_execution_allowed(self, work_order: ObservationWorkOrder) -> None:
        """Reject a planning-only successor even when the caller hands in a clone."""

        with self._lock:
            current = self._orders.get(work_order.work_order_id)
            if current is None or current.organization_id != work_order.organization_id:
                raise LookupError("관측 작업을 찾을 수 없다")
            self._assert_execution_allowed_current(current, supplied_work_order=work_order)

    def assert_execution_allowed_under_guard(self, work_order: ObservationWorkOrder) -> None:
        """Guard-only variant for callers already inside ``issuance_commit_guard``."""

        self._assert_execution_allowed_current(work_order, supplied_work_order=work_order)

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

    def bind_status_listener(self, listener: Callable[[ObservationWorkOrder], None]) -> None:
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
            self._assert_execution_allowed_current(current, supplied_work_order=current)
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
            self._assert_execution_allowed_current(current, supplied_work_order=current)
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
            self._assert_execution_allowed_current(current, supplied_work_order=current)
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
            self._assert_execution_allowed_current(order, supplied_work_order=order)
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
    temporal_policy: TemporalCoherencePolicy | None = None
    execution_mode: ObservationWorkOrderExecutionMode = (
        ObservationWorkOrderExecutionMode.MANAGED_ACQUISITION
    )


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


class WorkOrderOperationsListResponse(CamelModel):
    operations: list[ObservationWorkOrderOperations]


class WorkOrderOperationsAssignmentRequest(CamelModel):
    expected_operations_revision: int = Field(ge=0)
    action: WorkOrderOperationsAssignmentAction
    assignee_principal_id: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def _member_target_matches_action(self) -> WorkOrderOperationsAssignmentRequest:
        if self.action is WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER:
            if self.assignee_principal_id is None or not is_path_safe_identifier(
                self.assignee_principal_id
            ):
                raise ValueError("ASSIGN_TO_MEMBER requires a path-safe assigneePrincipalId")
        elif self.assignee_principal_id is not None:
            raise ValueError("assigneePrincipalId is only valid with ASSIGN_TO_MEMBER")
        return self


class WorkOrderOperationsDueDateRequest(CamelModel):
    expected_operations_revision: int = Field(ge=0)
    due_at: datetime | None = None


class WorkOrderOperationsCloseRequest(CamelModel):
    expected_operations_revision: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=500)


class WorkOrderOperationsReopenRequest(CamelModel):
    expected_operations_revision: int = Field(ge=0)


class ScheduleListResponse(CamelModel):
    schedules: list[ObservationSchedule]


class ReobservationDraftListResponse(CamelModel):
    drafts: list[ReobservationDraft]


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ExternalReobservationExecutionDenied):
        return HTTPException(status_code=409, detail=str(exc))
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
    if str(exc) == "EXTERNAL_CREATE_IDEMPOTENCY_CONFLICT":
        return HTTPException(
            status_code=409, detail="Idempotency-Key가 다른 생성 본문에 이미 사용됐다"
        )
    if str(exc) == "OPERATIONS_IDEMPOTENCY_CONFLICT":
        return HTTPException(
            status_code=409, detail="Idempotency-Key가 다른 운영 요청에 이미 사용됐다"
        )
    if str(exc) == "OPERATIONS_REVISION_CONFLICT":
        return HTTPException(
            status_code=409,
            detail="expectedOperationsRevision 이 현재 revision 과 다르다",
        )
    if str(exc) in {
        "OPERATIONS_INVALID_STATE",
        "EXTERNAL_OPERATIONS_ONLY",
        "EXTERNAL_WORKFLOW_CLOSED",
    }:
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _require_operations_human(principal: Principal) -> Principal:
    """Operations are human administrative intent, never a device or worker action."""

    if principal.kind is not PrincipalKind.OPERATOR:
        raise HTTPException(status_code=403, detail="HUMAN_AUTHORITY_REQUIRED")
    return principal


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
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008,E501
    ) -> ObservationWorkOrder:
        try:
            return store.create_work_order(
                organization_id=principal.organization_id,
                site_id=site_id,
                name=request.name,
                work_area_ids=request.work_area_ids,
                schedule_id=request.schedule_id,
                temporal_policy=request.temporal_policy,
                execution_mode=request.execution_mode,
                idempotency_key=idempotency_key,
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

    @router.get(
        "/v1/observation-work-orders/{work_order_id}/operations",
        response_model=ObservationWorkOrderOperations,
    )
    def get_work_order_operations(
        work_order_id: str,
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008,E501
    ) -> ObservationWorkOrderOperations:
        _require_operations_human(principal)
        try:
            return store.get_operations(work_order_id, organization_id=principal.organization_id)
        except (LookupError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc

    @router.get(
        "/v1/observation-work-order-operations",
        response_model=WorkOrderOperationsListResponse,
    )
    def list_work_order_operations(
        site_id: str | None = Query(default=None, alias="siteId"),  # noqa: B008
        workflow_status: WorkOrderWorkflowStatus | None = Query(  # noqa: B008
            default=None, alias="workflowStatus"
        ),
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008,E501
    ) -> WorkOrderOperationsListResponse:
        _require_operations_human(principal)
        try:
            return WorkOrderOperationsListResponse(
                operations=store.list_operations(
                    organization_id=principal.organization_id,
                    site_id=site_id,
                    workflow_status=workflow_status,
                )
            )
        except (LookupError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/v1/observation-work-orders/{work_order_id}/operations/assignment",
        response_model=ObservationWorkOrderOperations,
    )
    def assign_work_order_operations(
        work_order_id: str,
        request: WorkOrderOperationsAssignmentRequest,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008,E501
    ) -> ObservationWorkOrderOperations:
        _require_operations_human(principal)
        try:
            if request.action is WorkOrderOperationsAssignmentAction.ASSIGN_TO_MEMBER:
                assert request.assignee_principal_id is not None  # validated request
                return store.assign_operations_to_member(
                    work_order_id,
                    organization_id=principal.organization_id,
                    expected_operations_revision=request.expected_operations_revision,
                    action=request.action,
                    assignee_principal_id=request.assignee_principal_id,
                    actor=principal.principal_id,
                    idempotency_key=idempotency_key,
                    now=datetime.now(UTC),
                )
            return store.assign_operations_to_me(
                work_order_id,
                organization_id=principal.organization_id,
                expected_operations_revision=request.expected_operations_revision,
                action=request.action,
                actor=principal.principal_id,
                idempotency_key=idempotency_key,
                now=datetime.now(UTC),
            )
        except (JournalSealedError, LookupError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc

    @router.put(
        "/v1/observation-work-orders/{work_order_id}/operations/due-date",
        response_model=ObservationWorkOrderOperations,
    )
    def set_work_order_operations_due_date(
        work_order_id: str,
        request: WorkOrderOperationsDueDateRequest,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008,E501
    ) -> ObservationWorkOrderOperations:
        _require_operations_human(principal)
        try:
            return store.set_operations_due_date(
                work_order_id,
                organization_id=principal.organization_id,
                expected_operations_revision=request.expected_operations_revision,
                due_at=request.due_at,
                actor=principal.principal_id,
                idempotency_key=idempotency_key,
                now=datetime.now(UTC),
            )
        except (JournalSealedError, LookupError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/v1/observation-work-orders/{work_order_id}/operations/close",
        response_model=ObservationWorkOrderOperations,
    )
    def close_work_order_operations(
        work_order_id: str,
        request: WorkOrderOperationsCloseRequest,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008,E501
    ) -> ObservationWorkOrderOperations:
        _require_operations_human(principal)
        try:
            return store.close_operations(
                work_order_id,
                organization_id=principal.organization_id,
                expected_operations_revision=request.expected_operations_revision,
                note=request.note,
                actor=principal.principal_id,
                idempotency_key=idempotency_key,
                now=datetime.now(UTC),
            )
        except (JournalSealedError, LookupError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/v1/observation-work-orders/{work_order_id}/operations/reopen",
        response_model=ObservationWorkOrderOperations,
    )
    def reopen_work_order_operations(
        work_order_id: str,
        request: WorkOrderOperationsReopenRequest,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008,E501
    ) -> ObservationWorkOrderOperations:
        _require_operations_human(principal)
        try:
            return store.reopen_operations(
                work_order_id,
                organization_id=principal.organization_id,
                expected_operations_revision=request.expected_operations_revision,
                actor=principal.principal_id,
                idempotency_key=idempotency_key,
                now=datetime.now(UTC),
            )
        except (JournalSealedError, LookupError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc

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
