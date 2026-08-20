"""서명 계약 안의 촬영 품질 보충 계약(REQ-ACQ-102)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel


class CaptureRecoveryAction(StrEnum):
    RECAPTURE_SAME_POSE = "RECAPTURE_SAME_POSE"
    GIMBAL_ADJUST = "GIMBAL_ADJUST"
    SELECT_PREAUTHORIZED_VIEWPOINT = "SELECT_PREAUTHORIZED_VIEWPOINT"


class CaptureQualityStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    GAP = "GAP"
    RECOVERED = "RECOVERED"
    UNRECOVERABLE = "UNRECOVERABLE"


class CapturePolicyPack(_CamelModel):
    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    policy_id: str = Field(min_length=1)
    max_attempts_per_target: int = Field(ge=0, le=10)
    max_extra_time_seconds: int = Field(ge=0, le=900)
    minimum_battery_reserve_percent: float = Field(ge=15, le=100)
    maximum_gsd_cm_per_px: float = Field(gt=0)
    minimum_overlap_ratio: float = Field(ge=0, le=1)
    maximum_blur_score: float = Field(ge=0)
    maximum_occlusion_ratio: float = Field(ge=0, le=1)
    maximum_gimbal_adjustment_deg: float = Field(ge=0, le=180)
    allowed_actions: list[CaptureRecoveryAction] = Field(min_length=1, max_length=3)
    preauthorized_viewpoint_ids: list[str] = Field(default_factory=list, max_length=128)
    signature_key_id: str = Field(min_length=1)
    signature: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")

    @model_validator(mode="after")
    def _actions_are_unique(self) -> CapturePolicyPack:
        if len(set(self.allowed_actions)) != len(self.allowed_actions):
            raise ValueError("allowedActions 에 중복이 있다")
        if len(set(self.preauthorized_viewpoint_ids)) != len(self.preauthorized_viewpoint_ids):
            raise ValueError("preauthorizedViewpointIds 에 중복이 있다")
        if (
            CaptureRecoveryAction.SELECT_PREAUTHORIZED_VIEWPOINT in self.allowed_actions
            and not self.preauthorized_viewpoint_ids
        ):
            raise ValueError("사전승인 관측점 행동에는 preauthorizedViewpointIds 가 필요하다")
        return self


class CaptureQualityMeasurement(_CamelModel):
    artifact_id: str = Field(min_length=1)
    captured_at: str = Field(min_length=1)
    blur_score: float = Field(ge=0)
    exposure_ok: bool
    gsd_cm_per_px: float = Field(gt=0)
    overlap_ratio: float = Field(ge=0, le=1)
    occlusion_ratio: float = Field(ge=0, le=1)
    status: CaptureQualityStatus
    gap_reasons: list[str] = Field(default_factory=list, max_length=16)
    action: CaptureRecoveryAction | None = None
    attempt: int = Field(default=0, ge=0, le=10)
    viewpoint_id: str | None = None

    @model_validator(mode="after")
    def _status_matches_recovery(self) -> CaptureQualityMeasurement:
        if self.status is CaptureQualityStatus.ACCEPTED and (
            self.gap_reasons or self.action is not None or self.attempt != 0
        ):
            raise ValueError("ACCEPTED 측정은 gap/action/attempt를 가질 수 없다")
        if self.status is CaptureQualityStatus.RECOVERED and (
            self.action is None or self.attempt < 1
        ):
            raise ValueError("RECOVERED 측정은 action과 양의 attempt가 필요하다")
        return self


class CaptureQualityReport(_CamelModel):
    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    report_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    work_order_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    capture_policy_id: str = Field(min_length=1)
    measurements: list[CaptureQualityMeasurement] = Field(min_length=1, max_length=10000)
    started_at: str = Field(min_length=1)
    completed_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def _time_window_is_ordered(self) -> CaptureQualityReport:
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.completed_at)
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("startedAt/completedAt은 tz-aware 시각이어야 한다")
        if end < start:
            raise ValueError("completedAt은 startedAt보다 이를 수 없다")
        return self


__all__ = [
    "CapturePolicyPack",
    "CaptureQualityMeasurement",
    "CaptureQualityReport",
    "CaptureQualityStatus",
    "CaptureRecoveryAction",
]
