"""EventBundle v1.1 Pydantic v2 모델 (contracts/schemas/event-bundle.v1.1.json SSOT).

camelCase 표현(``alias_generator=to_camel``, ``populate_by_name=True``), ``model_config``
``extra="forbid"``. ``lineage``는 필수 필드다 — INV-042: 모든 결과는 Mission/Model/
Policy/Calibration Version 계보를 가진다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from ksi_domain.enums import EventStatus, Severity
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class ClipPolicy(_CamelModel):
    pre_seconds: float
    post_seconds: float


class Evidence(_CamelModel):
    """INV-030 — 저장 실패는 숨기지 않고 ``EVIDENCE_DEGRADED``(bundle_digest 등)로 기록."""

    context_images: list[str] | None = None
    detail_images: list[str] | None = None
    clips: list[str] | None = None
    trajectory_artifact: str | None = None
    clip_policy: ClipPolicy | None = None
    risk_field_artifact: str | None = None
    viewpoint_history_artifact: str | None = None
    bundle_digest: str | None = None
    edge_signature: str | None = None


class Lineage(_CamelModel):
    """INV-042 — 모든 결과는 Mission/Model/Policy/Calibration Version 계보를 가진다."""

    edge_version: str
    model_versions: dict[str, Any]
    policy_version: str
    calibration_profile_id: str


class Timing(_CamelModel):
    candidate_latency_ms: float | None = None
    local_alert_latency_ms: float | None = None
    server_notification_latency_ms: float | None = None


class EventBundle(_CamelModel):
    """EventBundle v1.1 — 상태전이는 :func:`ksi_domain.enums.assert_event_transition` 을 경유."""

    schema_version: Literal["1.1"] = "1.1"
    event_id: str
    mission_id: str
    site_id: str
    event_type: str
    severity: Severity | None = None
    occurred_at: datetime
    status: EventStatus
    entities: list[str]
    spatial_context: dict[str, Any]
    reasoning: dict[str, Any]
    evidence: Evidence
    lineage: Lineage
    review: dict[str, Any] | None = None
    timing: Timing | None = None
