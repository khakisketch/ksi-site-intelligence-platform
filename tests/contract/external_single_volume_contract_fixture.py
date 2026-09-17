"""Synthetic, Core-free single-volume contract builders shared by contract tests.

Only synthetic digests and coordinates; nothing here establishes Core
authorization or an external artifact's eligibility.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

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
)

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


def _report(request: ExternalSingleVolumeRequestV1 | None = None) -> ExternalSingleVolumeReportV1:
    request = _request() if request is None else request
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
