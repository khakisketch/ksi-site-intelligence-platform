"""Additive orchestration DTOs. No geometry, policy or numerical authority."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_analysis_api import (
    AnalysisObservationOptionV1,
    AnalysisReadinessViewV1,
    CreateAnalysisRequestV1,
)
from ksi_event_contracts.external_analysis_api_v2 import AnalysisViewV2

Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._~-]*$")
]
TaskId = Annotated[str, StringConstraints(pattern=r"^st-[0-9a-f]{32}$")]


class SpatialTaskPurposeV1(StrEnum):
    CLARIFY = "CLARIFY"
    OBSERVED_CHANGE = "OBSERVED_CHANGE"
    DESIGN_REMAINING = "DESIGN_REMAINING"
    DAILY_TARGET = "DAILY_TARGET"


class SpatialTaskSelectionV1(_CamelModel):
    purpose: SpatialTaskPurposeV1 = SpatialTaskPurposeV1.CLARIFY
    work_area_id: Identifier | None = None
    inputs: CreateAnalysisRequestV1 | None = None


class CreateSpatialTaskV1(SpatialTaskSelectionV1):
    pass


class SelectSpatialTaskV1(SpatialTaskSelectionV1):
    expected_revision: int = Field(strict=True, ge=1)


class RunSpatialTaskV1(_CamelModel):
    expected_revision: int = Field(strict=True, ge=1)


class SpatialTaskV1(_CamelModel):
    task_id: TaskId
    site_id: Identifier
    revision: int = Field(strict=True, ge=1)
    selection: SpatialTaskSelectionV1
    analysis_id: Identifier | None = None
    execution_requested: bool = False
    created_at: datetime
    expires_at: datetime

    @field_validator("created_at", "expires_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("task time must be UTC")
        return value


class SpatialTaskViewV1(_CamelModel):
    task: SpatialTaskV1
    state: Literal[
        "PURPOSE_REQUIRED",
        "UNSUPPORTED_PURPOSE",
        "AREA_REQUIRED",
        "OBSERVATIONS_REQUIRED",
        "CHECK_REQUIRED",
        "ANALYSIS_PENDING",
        "ANALYSIS_LINKED",
        "SELECTION_UNAVAILABLE",
    ]
    selection_href: str = Field(pattern=r"^/sites/[A-Za-z0-9._~-]+/spatial-tasks/st-[0-9a-f]{32}$")
    analysis_href: str | None = Field(default=None, pattern=r"^/sites/[A-Za-z0-9._~/?=&-]+$")
    readiness: AnalysisReadinessViewV1 | None = None
    analysis: AnalysisViewV2 | None = None

    @model_validator(mode="after")
    def _bound_projection(self) -> Self:
        task, selected = self.task, self.task.selection
        if self.selection_href != f"/sites/{task.site_id}/spatial-tasks/{task.task_id}":
            raise ValueError("selection href is not task-bound")
        expected_href = (
            f"/sites/{task.site_id}/analysis?analysisId={task.analysis_id}"
            if task.analysis_id
            else None
        )
        if self.analysis_href != expected_href:
            raise ValueError("analysis href is not task-bound")
        for projection in (self.readiness, self.analysis):
            if projection is not None and (
                selected.inputs is None
                or projection.site_id != task.site_id
                or projection.work_area_id != selected.work_area_id
                or projection.baseline != selected.inputs.baseline
                or projection.current != selected.inputs.current
            ):
                raise ValueError("projection is not selection-bound")
        if self.analysis is not None and self.analysis.analysis_id != task.analysis_id:
            raise ValueError("analysis identity mismatch")
        return self


class SpatialTaskAreaV1(_CamelModel):
    work_area_id: Identifier
    name: str = Field(min_length=1, max_length=255)


class SpatialTaskObservationV1(AnalysisObservationOptionV1):
    work_area_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=64)


class SpatialTaskOptionsV1(_CamelModel):
    site_id: Identifier
    areas: tuple[SpatialTaskAreaV1, ...] = Field(max_length=64)
    observations: tuple[SpatialTaskObservationV1, ...] = Field(max_length=32)
    next_offset: int | None = Field(default=None, ge=0)


class SpatialTaskSiteV1(_CamelModel):
    site_id: Identifier
    name: str = Field(min_length=1, max_length=255)


class SpatialTaskSitesV1(_CamelModel):
    items: tuple[SpatialTaskSiteV1, ...] = Field(max_length=32)
    next_offset: int | None = Field(default=None, ge=0)
