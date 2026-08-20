"""Capture Policy/Quality Python model ↔ JSON Schema conformance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from ksi_event_contracts.capture_quality import (
    CapturePolicyPack,
    CaptureQualityMeasurement,
    CaptureQualityReport,
    CaptureQualityStatus,
    CaptureRecoveryAction,
)
from pydantic import ValidationError

_ROOT = Path(__file__).parents[2]


def _schema(name: str) -> dict[str, object]:
    return json.loads((_ROOT / "contracts" / "schemas" / name).read_text(encoding="utf-8"))


def _policy() -> CapturePolicyPack:
    return CapturePolicyPack(
        policy_id="capture-policy-1",
        max_attempts_per_target=2,
        max_extra_time_seconds=60,
        minimum_battery_reserve_percent=25,
        maximum_gsd_cm_per_px=2.0,
        minimum_overlap_ratio=0.75,
        maximum_blur_score=0.2,
        maximum_occlusion_ratio=0.3,
        maximum_gimbal_adjustment_deg=15,
        allowed_actions=[
            CaptureRecoveryAction.RECAPTURE_SAME_POSE,
            CaptureRecoveryAction.SELECT_PREAUTHORIZED_VIEWPOINT,
        ],
        preauthorized_viewpoint_ids=["viewpoint-2"],
        signature_key_id="edge-policy-key-1",
        signature="AbCdEf_123-xy",
    )


def test_policy_model_and_schema_are_wire_compatible() -> None:
    schema = _schema("capture-policy-pack.v1.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_policy().model_dump(by_alias=True, mode="json"))


def test_preauthorized_action_requires_unique_viewpoints_and_unpadded_signature() -> None:
    with pytest.raises(ValidationError, match="preauthorizedViewpointIds"):
        _policy().model_copy(update={"preauthorized_viewpoint_ids": []}).__class__.model_validate(
            _policy().model_dump()
            | {
                "preauthorized_viewpoint_ids": [],
            }
        )
    with pytest.raises(ValidationError, match="preauthorizedViewpointIds"):
        CapturePolicyPack.model_validate(
            _policy().model_dump() | {"preauthorized_viewpoint_ids": ["viewpoint-2", "viewpoint-2"]}
        )
    with pytest.raises(ValidationError, match="signature"):
        CapturePolicyPack.model_validate(_policy().model_dump() | {"signature": "abcd=="})


def test_quality_status_lineage_and_report_window_fail_closed() -> None:
    accepted = CaptureQualityMeasurement(
        artifact_id="artifact-1",
        captured_at="2026-08-20T01:00:00+00:00",
        blur_score=0.1,
        exposure_ok=True,
        gsd_cm_per_px=1.8,
        overlap_ratio=0.8,
        occlusion_ratio=0.1,
        status=CaptureQualityStatus.ACCEPTED,
    )
    recovered = CaptureQualityMeasurement(
        artifact_id="artifact-2",
        captured_at="2026-08-20T01:00:01+00:00",
        blur_score=0.1,
        exposure_ok=True,
        gsd_cm_per_px=1.8,
        overlap_ratio=0.8,
        occlusion_ratio=0.1,
        status=CaptureQualityStatus.RECOVERED,
        gap_reasons=["BLUR"],
        action=CaptureRecoveryAction.RECAPTURE_SAME_POSE,
        attempt=1,
    )
    report = CaptureQualityReport(
        report_id="capture-quality-1",
        organization_id="org-a",
        site_id="site-a",
        work_order_id="work-1",
        mission_id="mission-1",
        device_id="device-1",
        capture_policy_id="capture-policy-1",
        measurements=[accepted, recovered],
        started_at="2026-08-20T01:00:00+00:00",
        completed_at="2026-08-20T01:01:00+00:00",
    )
    schema = _schema("capture-quality-report.v1.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(report.model_dump(by_alias=True, mode="json"))

    with pytest.raises(ValidationError, match="ACCEPTED"):
        CaptureQualityMeasurement.model_validate(
            accepted.model_dump() | {"action": "GIMBAL_ADJUST", "attempt": 1}
        )
    with pytest.raises(ValidationError, match="completedAt"):
        CaptureQualityReport.model_validate(
            report.model_dump()
            | {
                "started_at": "2026-08-20T02:00:00+00:00",
                "completed_at": "2026-08-20T01:00:00+00:00",
            }
        )
