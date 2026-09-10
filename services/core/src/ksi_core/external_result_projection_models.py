"""Additive, read-only DTOs for externally produced relative-volume results."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from ksi_core.api_base import CamelModel


class ExternalResultProjectionState(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NO_RESULT = "NO_RESULT"
    AVAILABLE = "AVAILABLE"
    HISTORICAL_SOURCE_UNAVAILABLE = "HISTORICAL_SOURCE_UNAVAILABLE"


class ExternalResultMetricsView(CamelModel):
    zone_cell_count: int
    common_valid_cell_count: int
    zone_area_m2: float
    measured_area_m2: float
    common_valid_fraction: float
    cut_m3: float
    fill_m3: float
    net_m3: float
    threshold_m: float
    uncertainty_m3: float | None
    uncertainty_note: str


class ExternalResultExecutionPolicyView(CamelModel):
    policy_id: str
    version: int
    policy_digest: str
    algorithm_build_digest: str
    config_digest: str
    uncertainty_method: str


class ExternalResultSummaryView(CamelModel):
    kind: str = "EXTERNAL_RELATIVE_VOLUME"
    report_ref: str
    report_digest: str
    request_ref: str
    request_digest: str
    source_work_order_id: str
    current_work_order_id: str
    baseline_work_order_id: str
    decision_id: str
    decision_digest: str
    work_area_id: str
    zone_definition_digest: str
    crs: str
    observed_crs_digest: str
    vertical_reference_digest: str
    baseline_captured_from: datetime
    baseline_captured_to: datetime
    current_captured_from: datetime
    current_captured_to: datetime
    reported_at: datetime
    measurement_status: str
    measurement_reason: str | None
    metrics: ExternalResultMetricsView | None
    execution_policy: ExternalResultExecutionPolicyView
    review_ref: str | None
    review_digest: str | None
    reviewed_at: datetime | None
    proposal_count: int
    approved_proposal_count: int


class ExternalResultProjectionView(CamelModel):
    state: ExternalResultProjectionState
    result: ExternalResultSummaryView | None = None


__all__ = [
    "ExternalResultExecutionPolicyView",
    "ExternalResultMetricsView",
    "ExternalResultProjectionState",
    "ExternalResultProjectionView",
    "ExternalResultSummaryView",
]
