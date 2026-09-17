"""Immutable external single-volume contracts stay closed and fail closed.

These tests use only synthetic digests and coordinates.  They establish neither
Core authorization nor an external artifact's eligibility; Core resolves those
facts before a SINGLE_VOLUME decision or request exists.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_relative_volume import (
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
)
from ksi_event_contracts.external_single_volume import (
    ExternalSingleVolumeDecisionV1,
    ExternalSingleVolumeExecutionPolicyV1,
    ExternalSingleVolumeMeasurementPayloadV1,
    ExternalSingleVolumeMetricsV1,
    ExternalSingleVolumeReportV1,
    ExternalSingleVolumeRequestV1,
    external_single_volume_decision_wire_dict,
    external_single_volume_execution_policy_wire_dict,
    external_single_volume_report_wire_dict,
    external_single_volume_request_wire_dict,
)
from pydantic import ValidationError

_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "contracts/schemas"
_NOW = datetime(2026, 9, 17, 1, 2, 3, tzinfo=UTC)
_WORKER_ID = str(uuid.uuid4())
_LEASE_ID = str(uuid.uuid4())


def _digest(marker: str) -> str:
    return "sha256:" + marker * 64


def _subject() -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="organization-1",
        site_id="site-1",
        work_order_id="work-order-1",
        submission_id="submission-1",
        revision=1,
        submission_digest=_digest("a"),
        manifest_digest=_digest("b"),
    )


def _zone() -> ExternalVolumeZoneSnapshotV1:
    return ExternalVolumeZoneSnapshotV1(
        organization_id="organization-1",
        site_id="site-1",
        work_area_id="zone-1",
        polygon={
            "type": "Polygon",
            "coordinates": [[[0.0, 2.0], [2.0, 2.0], [2.0, 0.0], [0.0, 0.0], [0.0, 2.0]]],
        },
        crs="EPSG:5186",
        observed_crs_digest=_digest("c"),
        analysis_vertical_reference_digest=_digest("d"),
    ).sealed()


def _binding() -> ExternalVolumeInputBindingV1:
    return ExternalVolumeInputBindingV1(
        subject=_subject(),
        inspection_report_digest=_digest("e"),
        dsm_artifact_id="dsm-1",
        observed_sha256=_digest("f"),
        observed_size_bytes=64,
        observed_crs_digest=_digest("c"),
        observed_vertical_reference_digest=_digest("d"),
        captured_from=_NOW - timedelta(hours=2),
        captured_to=_NOW - timedelta(hours=1),
    )


def _policy() -> ExternalSingleVolumeExecutionPolicyV1:
    return ExternalSingleVolumeExecutionPolicyV1(
        policy_id="single-policy-1",
        version=1,
        algorithm_build_digest=_digest("1"),
        config_digest=_digest("2"),
        threshold_m=0.05,
        minimum_common_valid_fraction=0.9,
        minimum_boundary_valid_fraction=0.8,
        uncertainty_method="SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1",
        base_surface_method="BOUNDARY_LINEAR_INTERPOLATION_V1",
        resource_envelope_digest=_digest("3"),
        authority_record_digest=_digest("4"),
        synthetic_test_only=False,
    ).sealed()


def _decision(
    *, verdict: DecisionVerdict = DecisionVerdict.ELIGIBLE
) -> ExternalSingleVolumeDecisionV1:
    eligible = verdict is not DecisionVerdict.BLOCKED
    return ExternalSingleVolumeDecisionV1(
        decision_id="decision-1",
        subject=_subject(),
        subject_digest=_subject().canonical_digest(),
        policy_digest=_digest("5") if eligible else None,
        inspection_report_digest=_digest("e") if eligible else None,
        evidence_record_digests=(_digest("6"),) if eligible else (),
        zone=_zone().to_zone_reference() if eligible else None,
        compatibility_mapping_digest=_digest("7") if eligible else None,
        verdict=verdict,
        reasons=("USE_ELIGIBLE",) if eligible else ("POLICY_UNAVAILABLE",),
        remediations=("CURRENT_DEPENDENCIES_RETAINED",) if eligible else ("AUTHORIZE_POLICY",),
        decided_at=_NOW,
    ).sealed()


def _request() -> ExternalSingleVolumeRequestV1:
    policy = _policy()
    assert policy.policy_digest is not None
    return ExternalSingleVolumeRequestV1(
        request_id="external-single-volume-1",
        current_work_order_id="work-order-1",
        decision_id="decision-1",
        decision_digest=_digest("8"),
        target=_binding(),
        evidence_record_digests=(_digest("6"),),
        validation_policy_digest=_digest("5"),
        execution_policy_digest=policy.policy_digest,
        zone_snapshot=_zone(),
        issued_at=_NOW,
        idempotency_key="key-1",
    ).sealed()


def _metrics() -> ExternalSingleVolumeMetricsV1:
    return ExternalSingleVolumeMetricsV1(
        zone_cell_count=36,
        common_valid_cell_count=36,
        zone_area_m2=36.0,
        measured_area_m2=36.0,
        common_valid_fraction=1.0,
        cut_m3=0.0,
        fill_m3=12.0,
        net_m3=12.0,
        threshold_m=0.0,
        uncertainty_m3=1.8,
        uncertainty_note="single epoch: area x hypot(dsm rmse, base roughness)",
        base_roughness_m=0.0,
        boundary_cell_count=20,
        boundary_sample_count=20,
        boundary_valid_fraction=1.0,
    )


def _report() -> ExternalSingleVolumeReportV1:
    request = _request()
    assert request.request_digest is not None
    payload = ExternalSingleVolumeMeasurementPayloadV1(
        request_digest=request.request_digest,
        decision_digest=request.decision_digest,
        target_dsm_digest=request.target.observed_sha256,
        zone_snapshot_digest=request.zone_snapshot.canonical_digest(),
        execution_policy_digest=request.execution_policy_digest,
        algorithm_build_digest=_digest("1"),
        config_digest=_digest("2"),
        metrics=_metrics(),
    )
    return ExternalSingleVolumeReportV1(
        report_id="report-1",
        request_id=request.request_id,
        request_digest=request.request_digest,
        payload=payload,
        worker_instance_id=_WORKER_ID,
        lease_acquisition_id=_LEASE_ID,
        lease_generation=1,
        computed_at=_NOW,
        reported_at=_NOW,
    ).sealed()


@pytest.mark.parametrize(
    ("schema_name", "wire"),
    [
        (
            "external-single-volume-decision.v1.json",
            lambda: external_single_volume_decision_wire_dict(_decision()),
        ),
        (
            "external-single-volume-decision.v1.json",
            lambda: external_single_volume_decision_wire_dict(
                _decision(verdict=DecisionVerdict.BLOCKED)
            ),
        ),
        (
            "external-single-volume-execution-policy.v1.json",
            lambda: external_single_volume_execution_policy_wire_dict(_policy()),
        ),
        (
            "external-single-volume-request.v1.json",
            lambda: external_single_volume_request_wire_dict(_request()),
        ),
        (
            "external-single-volume-report.v1.json",
            lambda: external_single_volume_report_wire_dict(_report()),
        ),
    ],
)
def test_sealed_wire_round_trips_against_its_schema(
    schema_name: str, wire: Callable[[], dict[str, Any]]
) -> None:
    """A misspelled or open wire key must not become durable contract state."""
    schema = json.loads((_SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    raw = wire()
    validator.validate(raw)
    raw["unexpected"] = 1
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(raw)


def test_decision_digest_is_stable_and_binds_subject() -> None:
    first, second = _decision(), _decision()
    assert first.decision_digest == second.decision_digest
    assert first.decision_digest == first.canonical_digest()
    assert first.use == "SINGLE_VOLUME"
    with pytest.raises(ValidationError, match="subjectDigest"):
        _decision().model_copy(
            update={"subject_digest": _digest("9"), "decision_digest": None}, deep=True
        ).sealed()


def test_eligible_decision_requires_zone_mapping_and_exactly_one_evidence_record() -> None:
    base = _decision()
    for update, message in (
        ({"zone": None}, "exact zone"),
        ({"compatibility_mapping_digest": None}, "compatibilityMappingDigest"),
        ({"evidence_record_digests": ()}, "exactly one"),
        ({"evidence_record_digests": (_digest("6"), _digest("7"))}, "exactly one"),
    ):
        with pytest.raises(ValidationError, match=message):
            base.model_copy(update={**update, "decision_digest": None}, deep=True).sealed()


def test_blocked_decision_forbids_mapping_zone_and_evidence() -> None:
    blocked = _decision(verdict=DecisionVerdict.BLOCKED)
    with pytest.raises(ValidationError, match="BLOCKED"):
        blocked.model_copy(
            update={"compatibility_mapping_digest": _digest("7"), "decision_digest": None},
            deep=True,
        ).sealed()
    with pytest.raises(ValidationError, match="BLOCKED"):
        blocked.model_copy(
            update={"evidence_record_digests": (_digest("6"),), "decision_digest": None},
            deep=True,
        ).sealed()


def test_request_requires_one_evidence_record_and_target_bound_to_work_order() -> None:
    request = _request()
    with pytest.raises(ValidationError, match="at least 1 item"):
        request.model_copy(
            update={"evidence_record_digests": (), "request_digest": None}, deep=True
        ).sealed()
    with pytest.raises(ValidationError, match="at most 1 item"):
        request.model_copy(
            update={
                "evidence_record_digests": (_digest("6"), _digest("7")),
                "request_digest": None,
            },
            deep=True,
        ).sealed()
    with pytest.raises(ValidationError, match="currentWorkOrderId"):
        request.model_copy(
            update={"current_work_order_id": "other", "request_digest": None}, deep=True
        ).sealed()
    with pytest.raises(ValidationError, match="vertical"):
        request.model_copy(
            update={
                "target": _binding().model_copy(
                    update={"observed_vertical_reference_digest": _digest("9")}
                ),
                "request_digest": None,
            },
            deep=True,
        ).sealed()


def test_metrics_bind_boundary_fraction_to_counts() -> None:
    body = _metrics().model_dump()
    with pytest.raises(ValidationError, match="boundaryValidFraction"):
        ExternalSingleVolumeMetricsV1.model_validate({**body, "boundary_valid_fraction": 0.5})
    with pytest.raises(ValidationError, match="boundarySampleCount"):
        ExternalSingleVolumeMetricsV1.model_validate({**body, "boundary_sample_count": 21})


def test_report_seals_payload_and_binds_request_digest() -> None:
    report = _report()
    assert report.measurement_payload_digest == report.payload.canonical_digest()
    assert report.report_digest == report.canonical_digest()
    with pytest.raises(ValidationError, match="requestDigest"):
        report.model_copy(
            update={
                "request_digest": _digest("0"),
                "report_digest": None,
                "measurement_payload_digest": None,
            },
            deep=True,
        ).sealed()
