"""반복 관측을 한 사용자 작업으로 묶는 계약(REQ-WRK-101)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel


class ObservationPurpose(StrEnum):
    PROGRESS_QUANTITY = "PROGRESS_QUANTITY"


class ObservationScheduleStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class TemporalCoherencePolicy(_CamelModel):
    """한 ObservationEpoch 안에서 허용할 촬영 시각 범위.

    정책이 없는 과거 WorkOrder도 읽을 수 있게 이 타입 자체는 optional 필드로
    붙인다. 다만 Analysis Readiness는 정책이 없으면 READY를 주장하지 않는다
    (REQ-INT-103, INV-018).
    """

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    max_capture_span_seconds: int = Field(ge=1, le=86_400)


class ObservationWorkOrderStatus(StrEnum):
    DRAFT = "DRAFT"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    DISPATCHED = "DISPATCHED"
    START_REPORTED = "START_REPORTED"
    MEDIA_RECEIVING = "MEDIA_RECEIVING"
    PROCESSING = "PROCESSING"
    REVIEW_READY = "REVIEW_READY"
    REOBSERVATION_PENDING = "REOBSERVATION_PENDING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class ObservationWorkOrderExecutionMode(StrEnum):
    """Durable execution boundary; nullable only for records written before this field existed."""

    MANAGED_ACQUISITION = "MANAGED_ACQUISITION"
    EXTERNAL_RECONSTRUCTION = "EXTERNAL_RECONSTRUCTION"


class ReobservationDraftStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class ObservationSchedule(_CamelModel):
    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    schedule_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    purpose: ObservationPurpose = ObservationPurpose.PROGRESS_QUANTITY
    name: str = Field(min_length=1, max_length=200)
    work_area_ids: list[str] = Field(min_length=1, max_length=64)
    interval_days: int = Field(ge=1, le=365)
    timezone: str = Field(min_length=1, max_length=100)
    approved_policy_version: str | None = None
    status: ObservationScheduleStatus
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_work_areas(self) -> ObservationSchedule:
        if len(set(self.work_area_ids)) != len(self.work_area_ids):
            raise ValueError("workAreaIds 에 중복이 있다")
        return self


class ObservationWorkOrder(_CamelModel):
    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    work_order_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    purpose: ObservationPurpose = ObservationPurpose.PROGRESS_QUANTITY
    name: str = Field(min_length=1, max_length=200)
    work_area_ids: list[str] = Field(min_length=1, max_length=64)
    schedule_id: str | None = None
    temporal_policy: TemporalCoherencePolicy | None = None
    execution_mode: ObservationWorkOrderExecutionMode | None = None
    cycle_number: int = Field(default=1, ge=1)
    status: ObservationWorkOrderStatus
    status_reason: str | None = Field(default=None, max_length=1000)
    mission_ids: list[str] = Field(default_factory=list, max_length=64)
    processing_job_ids: list[str] = Field(default_factory=list, max_length=64)
    report_refs: list[str] = Field(default_factory=list, max_length=128)
    version: int = Field(ge=1)
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
    approved_at: str | None = None
    approved_by: str | None = None

    @model_validator(mode="after")
    def _lineage_is_consistent(self) -> ObservationWorkOrder:
        if len(set(self.work_area_ids)) != len(self.work_area_ids):
            raise ValueError("workAreaIds 에 중복이 있다")
        if (self.approved_at is None) != (self.approved_by is None):
            raise ValueError("approvedAt 과 approvedBy 는 함께 있어야 한다")
        return self


class ReobservationDraft(_CamelModel):
    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    draft_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    work_order_id: str = Field(min_length=1)
    reason_refs: list[str] = Field(min_length=1, max_length=64)
    target_region_refs: list[str] = Field(min_length=1, max_length=64)
    proposed_effort: str = Field(min_length=1, max_length=500)
    planner_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    expires_at: str = Field(min_length=1)
    status: ReobservationDraftStatus
    version: int = Field(ge=1)
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
    approved_at: str | None = None
    approved_by: str | None = None


__all__ = [
    "ObservationPurpose",
    "ObservationSchedule",
    "ObservationScheduleStatus",
    "ObservationWorkOrder",
    "ObservationWorkOrderExecutionMode",
    "ObservationWorkOrderStatus",
    "ReobservationDraft",
    "ReobservationDraftStatus",
    "TemporalCoherencePolicy",
]
