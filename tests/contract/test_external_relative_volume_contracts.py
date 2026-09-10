"""Immutable external relative-volume contracts stay closed and fail closed.

These tests use only synthetic digests and coordinates.  They establish neither
Core authorization nor an external artifact's eligibility; Core resolves those
facts before issuing a request in a later integration slice.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeExecutionPolicyV1,
    ExternalRelativeVolumeMeasurementPayloadV1,
    ExternalRelativeVolumeReportV1,
    ExternalRelativeVolumeRequestV1,
    ExternalVolumeInputBindingV1,
    ExternalVolumeMetricsV1,
    ExternalVolumeZoneSnapshotV1,
    external_relative_volume_execution_policy_wire_dict,
    external_relative_volume_report_wire_dict,
    external_relative_volume_request_wire_dict,
    external_volume_zone_snapshot_wire_dict,
)
from ksi_event_contracts.work_area import MAX_RING_POSITIONS
from pydantic import ValidationError

_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "contracts/schemas"
_NOW = datetime(2026, 9, 9, 1, 2, 3, tzinfo=UTC)


def _digest(marker: str) -> str:
    return "sha256:" + marker * 64


def _subject(*, work_order_id: str, submission_id: str = "submission-1") -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="organization-1",
        site_id="site-1",
        work_order_id=work_order_id,
        submission_id=submission_id,
        revision=1,
        submission_digest=_digest("a"),
        manifest_digest=_digest("b"),
    )


def _polygon() -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [[[0.0, 2.0], [2.0, 2.0], [2.0, 0.0], [0.0, 0.0], [0.0, 2.0]]],
    }


def _zone() -> ExternalVolumeZoneSnapshotV1:
    return ExternalVolumeZoneSnapshotV1(
        organization_id="organization-1",
        site_id="site-1",
        work_area_id="work-area-1",
        revision=1,
        polygon=_polygon(),
        crs="EPSG:5186",
        observed_crs_digest=_digest("c"),
        analysis_vertical_reference_digest=_digest("d"),
    ).sealed()


def _binding(*, subject: SealedExternalSubjectV1, marker: str) -> ExternalVolumeInputBindingV1:
    return ExternalVolumeInputBindingV1(
        subject=subject,
        inspection_report_digest=_digest(marker),
        dsm_artifact_id=f"dsm-{marker}",
        observed_sha256=_digest("e"),
        observed_size_bytes=128,
        observed_crs_digest=_digest("f"),
        observed_vertical_reference_digest=_digest("d"),
        captured_from=_NOW - timedelta(hours=2),
        captured_to=_NOW - timedelta(hours=1),
    )


def _policy() -> ExternalRelativeVolumeExecutionPolicyV1:
    return ExternalRelativeVolumeExecutionPolicyV1(
        policy_id="relative-volume-policy-1",
        version=1,
        algorithm_build_digest=_digest("1"),
        config_digest=_digest("2"),
        threshold_m=0.0,
        minimum_common_valid_fraction=1.0,
        uncertainty_method="INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1",
        resource_envelope_digest=_digest("3"),
        authority_record_digest=_digest("4"),
        synthetic_test_only=True,
    ).sealed()


def _request() -> ExternalRelativeVolumeRequestV1:
    policy = _policy()
    assert policy.policy_digest is not None
    baseline = _binding(
        subject=_subject(work_order_id="work-order-baseline"), marker="6"
    ).model_copy(
        update={
            "captured_from": _NOW - timedelta(hours=4),
            "captured_to": _NOW - timedelta(hours=3),
        }
    )
    current = _binding(
        subject=_subject(work_order_id="work-order-current", submission_id="submission-2"),
        marker="7",
    ).model_copy(
        update={
            "captured_from": _NOW - timedelta(hours=2),
            "captured_to": _NOW - timedelta(hours=1),
        }
    )
    return ExternalRelativeVolumeRequestV1(
        request_id="relative-volume-request-1",
        current_work_order_id="work-order-current",
        decision_id="relative-volume-decision-1",
        decision_digest=_digest("5"),
        baseline=baseline,
        current=current,
        evidence_record_digests=(_digest("8"), _digest("9")),
        validation_policy_digest=_digest("0"),
        execution_policy_digest=policy.policy_digest,
        zone_snapshot=_zone(),
        issued_at=_NOW,
        idempotency_key="relative-volume-idempotency-1",
    ).sealed()


def _metrics() -> ExternalVolumeMetricsV1:
    return ExternalVolumeMetricsV1(
        zone_cell_count=4,
        common_valid_cell_count=4,
        zone_area_m2=4.0,
        measured_area_m2=4.0,
        common_valid_fraction=1.0,
        cut_m3=1.0,
        fill_m3=5.0,
        net_m3=4.0,
        threshold_m=0.0,
        uncertainty_m3=None,
        uncertainty_note="Independent checkpoint RMSE is unavailable for both epochs.",
    )


def _payload(
    request: ExternalRelativeVolumeRequestV1,
) -> ExternalRelativeVolumeMeasurementPayloadV1:
    assert request.request_digest is not None
    return ExternalRelativeVolumeMeasurementPayloadV1(
        request_digest=request.request_digest,
        decision_digest=request.decision_digest,
        baseline_dsm_digest=request.baseline.observed_sha256,
        current_dsm_digest=request.current.observed_sha256,
        zone_snapshot_digest=request.zone_snapshot.canonical_digest(),
        execution_policy_digest=request.execution_policy_digest,
        algorithm_build_digest=_digest("1"),
        config_digest=_digest("2"),
        metrics=_metrics(),
    )


def _report() -> ExternalRelativeVolumeReportV1:
    request = _request()
    assert request.request_digest is not None
    return ExternalRelativeVolumeReportV1(
        report_id="relative-volume-report-1",
        request_id=request.request_id,
        request_digest=request.request_digest,
        payload=_payload(request),
        worker_instance_id="123e4567-e89b-42d3-a456-426614174000",
        lease_acquisition_id="123e4567-e89b-42d3-a456-426614174002",
        lease_generation=1,
        computed_at=_NOW,
        reported_at=_NOW + timedelta(seconds=1),
    ).sealed()


@pytest.mark.parametrize(
    ("schema_name", "wire"),
    [
        (
            "external-volume-zone-snapshot.v1.json",
            lambda: external_volume_zone_snapshot_wire_dict(_zone()),
        ),
        (
            "external-relative-volume-execution-policy.v1.json",
            lambda: external_relative_volume_execution_policy_wire_dict(_policy()),
        ),
        (
            "external-relative-volume-request.v1.json",
            lambda: external_relative_volume_request_wire_dict(_request()),
        ),
        (
            "external-relative-volume-report.v1.json",
            lambda: external_relative_volume_report_wire_dict(_report()),
        ),
    ],
)
def test_sealed_wire_round_trips_against_its_draft_2020_12_schema(
    schema_name: str, wire: Callable[[], dict[str, Any]]
) -> None:
    """A misspelled or open wire key must not become durable contract state."""
    schema = json.loads((_SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    payload = wire()
    assert isinstance(payload, dict)
    Draft202012Validator(schema).validate(payload)


def test_zone_snapshot_seals_its_definition_and_maps_to_existing_zone_reference() -> None:
    """Changing zone geometry must change the sealed definition that Core later binds."""
    zone = _zone()
    assert zone.definition_digest is not None
    reference = zone.to_zone_reference()
    assert reference.zone_id == "work-area-1"
    assert reference.revision == 1
    assert reference.definition_digest == zone.definition_digest
    assert reference.observed_crs_digest == _digest("c")
    assert reference.observed_vertical_reference_digest == _digest("d")


def test_zone_definition_digest_excludes_the_separately_bound_vertical_reference() -> None:
    """Changing vertical evidence must not rewrite the immutable WorkArea geometry definition."""
    zone = _zone()
    changed_vertical = zone.model_copy(
        update={"analysis_vertical_reference_digest": _digest("e")}
    ).sealed()
    assert changed_vertical.definition_digest == zone.definition_digest
    assert changed_vertical.canonical_digest() != zone.canonical_digest()


def test_request_permits_same_site_cross_work_order_pair() -> None:
    """A historic baseline may belong to an earlier WorkOrder at the same site."""
    request = _request()
    assert request.baseline.subject.work_order_id == "work-order-baseline"
    assert request.current.subject.work_order_id == request.current_work_order_id


def test_input_binding_requires_ordered_utc_capture_timestamps() -> None:
    """An offset timestamp or empty interval cannot be hidden inside an external binding."""
    binding = _binding(subject=_subject(work_order_id="work-order-baseline"), marker="6")
    values = binding.model_dump()
    values["captured_from"] = "2026-09-09T10:00:00+09:00"
    with pytest.raises(ValidationError, match="captured_from"):
        ExternalVolumeInputBindingV1.model_validate(values)
    values = binding.model_dump()
    values["captured_to"] = binding.captured_from
    with pytest.raises(ValidationError, match="capturedFrom"):
        ExternalVolumeInputBindingV1.model_validate(values)


def _request_values(
    *, baseline: ExternalVolumeInputBindingV1, current: ExternalVolumeInputBindingV1
) -> dict[str, Any]:
    values = _request().model_dump()
    values.pop("request_digest")
    values["baseline"] = baseline.model_dump()
    values["current"] = current.model_dump()
    return values


def test_request_allows_exactly_adjacent_baseline_and_current_capture_intervals() -> None:
    """Exact adjacency preserves chronological epochs without manufacturing a time gap."""
    baseline = _binding(subject=_subject(work_order_id="work-order-baseline"), marker="6")
    current = _binding(
        subject=_subject(work_order_id="work-order-current", submission_id="submission-2"),
        marker="7",
    )
    values = _request_values(baseline=baseline, current=current)
    values["baseline"]["captured_from"] = _NOW - timedelta(hours=4)
    values["baseline"]["captured_to"] = _NOW - timedelta(hours=3)
    values["current"]["captured_from"] = _NOW - timedelta(hours=3)
    values["current"]["captured_to"] = _NOW - timedelta(hours=2)
    request = ExternalRelativeVolumeRequestV1.model_validate(values)
    assert request.baseline.captured_to == request.current.captured_from


@pytest.mark.parametrize(
    ("baseline_from", "baseline_to", "current_from", "current_to"),
    [
        (
            _NOW - timedelta(hours=4),
            _NOW - timedelta(hours=2),
            _NOW - timedelta(hours=3),
            _NOW - timedelta(hours=1),
        ),
        (
            _NOW - timedelta(hours=2),
            _NOW - timedelta(hours=1),
            _NOW - timedelta(hours=4),
            _NOW - timedelta(hours=3),
        ),
    ],
)
def test_request_refuses_overlapping_or_reversed_capture_intervals(
    baseline_from: datetime,
    baseline_to: datetime,
    current_from: datetime,
    current_to: datetime,
) -> None:
    """The current-minus-baseline sign convention requires non-overlapping epoch order."""
    values = _request_values(
        baseline=_binding(subject=_subject(work_order_id="work-order-baseline"), marker="6"),
        current=_binding(
            subject=_subject(work_order_id="work-order-current", submission_id="submission-2"),
            marker="7",
        ),
    )
    values["baseline"]["captured_from"] = baseline_from
    values["baseline"]["captured_to"] = baseline_to
    values["current"]["captured_from"] = current_from
    values["current"]["captured_to"] = current_to
    with pytest.raises(ValidationError, match="baseline.capturedTo"):
        ExternalRelativeVolumeRequestV1.model_validate(values)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda values: values.update({"organization_id": "organization-2"}),
        lambda values: values.update({"site_id": "site-2"}),
    ],
)
def test_request_refuses_cross_tenant_or_cross_site_binding(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    """Cross-scope subjects must never be serialized as a single volume request."""
    baseline = _binding(subject=_subject(work_order_id="work-order-baseline"), marker="6")
    values = baseline.subject.model_dump()
    mutate(values)
    cross_scope = SealedExternalSubjectV1.model_validate(values)
    with pytest.raises(ValidationError, match="organization|site"):
        ExternalRelativeVolumeRequestV1.model_validate(
            _request().model_dump()
            | {"baseline": baseline.model_dump() | {"subject": cross_scope.model_dump()}}
        )


def test_request_wire_revalidates_nested_mutable_zone_geometry() -> None:
    """Frozen models do not let a post-validation NaN escape through wire serialization."""
    request = _request()
    request.zone_snapshot.polygon["coordinates"][0][0][0] = math.nan
    with pytest.raises(ValidationError, match="유한하지 않다"):
        external_relative_volume_request_wire_dict(request)


def test_request_wire_refuses_finite_nested_zone_tampering_with_a_stale_digest() -> None:
    """A mutable container cannot alter the sealed zone definition after Core signs it."""
    request = _request()
    request.zone_snapshot.polygon["coordinates"][0][0][0] = 0.25
    request.zone_snapshot.polygon["coordinates"][0][-1][0] = 0.25
    with pytest.raises(ValidationError, match="definitionDigest"):
        external_relative_volume_request_wire_dict(request)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("zone_cell_count", True),
        ("common_valid_cell_count", 1e999),
        ("zone_area_m2", math.nan),
        ("measured_area_m2", math.inf),
        ("common_valid_fraction", 1.1),
        ("threshold_m", -0.1),
    ],
)
def test_metrics_refuse_nonfinite_boolean_and_inconsistent_values(
    field: str, value: object
) -> None:
    """A durable result cannot express a fake count, area, or coverage ratio."""
    values = _metrics().model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        ExternalVolumeMetricsV1.model_validate(values)


def test_metrics_refuse_material_ratio_and_net_inconsistency() -> None:
    """The report must retain the arithmetic that makes its headline net auditable."""
    values = _metrics().model_dump()
    values["common_valid_fraction"] = 0.5
    with pytest.raises(ValidationError, match="commonValidFraction"):
        ExternalVolumeMetricsV1.model_validate(values)
    values = _metrics().model_dump()
    values["net_m3"] = 999.0
    with pytest.raises(ValidationError, match="netM3"):
        ExternalVolumeMetricsV1.model_validate(values)


def test_report_binds_the_payload_to_its_exact_request_and_orders_timestamps() -> None:
    """A worker cannot attach a valid measurement to another sealed request."""
    report = _report()
    wire = external_relative_volume_report_wire_dict(report)
    wire["payload"]["requestDigest"] = _digest("f")
    with pytest.raises(ValidationError, match="requestDigest"):
        ExternalRelativeVolumeReportV1.model_validate(wire)
    wire = external_relative_volume_report_wire_dict(report)
    wire["computedAt"] = (report.reported_at + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValidationError, match="computedAt"):
        ExternalRelativeVolumeReportV1.model_validate(wire)


def test_schema_refuses_hostile_extra_fields_and_missing_digest() -> None:
    """JSON Schema must be closed even for callers that bypass Python models."""
    schema = json.loads(
        (_SCHEMA_DIR / "external-relative-volume-request.v1.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    wire = external_relative_volume_request_wire_dict(_request())
    wire["untrustedEligibility"] = True
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(wire)
    wire = external_relative_volume_request_wire_dict(_request())
    del wire["requestDigest"]
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(wire)


def test_schema_rejects_nonfinite_external_volume_numbers() -> None:
    """Schema-only consumers cannot retain Python JSON infinities as durable measurements."""
    policy_schema = Draft202012Validator(
        json.loads(
            (_SCHEMA_DIR / "external-relative-volume-execution-policy.v1.json").read_text(
                encoding="utf-8"
            )
        )
    )
    policy_wire = external_relative_volume_execution_policy_wire_dict(_policy())
    policy_wire["thresholdM"] = math.inf
    with pytest.raises(JsonSchemaValidationError):
        policy_schema.validate(policy_wire)
    report_schema = Draft202012Validator(
        json.loads(
            (_SCHEMA_DIR / "external-relative-volume-report.v1.json").read_text(encoding="utf-8")
        )
    )
    report_wire = external_relative_volume_report_wire_dict(_report())
    report_wire["payload"]["metrics"]["zoneAreaM2"] = 1e999
    with pytest.raises(JsonSchemaValidationError):
        report_schema.validate(report_wire)


def test_zone_schemas_reject_coordinates_and_rings_beyond_work_area_resource_limits() -> None:
    """Both direct and nested zone schemas retain the closed model's bounded input shape."""
    ring = [[0.0, 0.0]] + [[float(index), 1.0] for index in range(1, 512)] + [[0.0, 0.0]]
    assert len(ring) == MAX_RING_POSITIONS + 1
    zone_wire = external_volume_zone_snapshot_wire_dict(_zone())
    zone_wire["polygon"]["coordinates"] = [ring]
    zone_schema = Draft202012Validator(
        json.loads(
            (_SCHEMA_DIR / "external-volume-zone-snapshot.v1.json").read_text(encoding="utf-8")
        )
    )
    with pytest.raises(JsonSchemaValidationError):
        zone_schema.validate(zone_wire)
    request_wire = external_relative_volume_request_wire_dict(_request())
    request_wire["zoneSnapshot"]["polygon"]["coordinates"] = [ring]
    request_schema = Draft202012Validator(
        json.loads(
            (_SCHEMA_DIR / "external-relative-volume-request.v1.json").read_text(encoding="utf-8")
        )
    )
    with pytest.raises(JsonSchemaValidationError):
        request_schema.validate(request_wire)


def test_zone_schemas_reject_nonfinite_coordinate_values() -> None:
    """Wire-schema consumers reject parser infinities before semantic geometry checks."""
    zone_schema = Draft202012Validator(
        json.loads(
            (_SCHEMA_DIR / "external-volume-zone-snapshot.v1.json").read_text(encoding="utf-8")
        )
    )
    request_schema = Draft202012Validator(
        json.loads(
            (_SCHEMA_DIR / "external-relative-volume-request.v1.json").read_text(encoding="utf-8")
        )
    )
    zone_wire = external_volume_zone_snapshot_wire_dict(_zone())
    zone_wire["polygon"]["coordinates"][0][0][0] = math.inf
    with pytest.raises(JsonSchemaValidationError):
        zone_schema.validate(zone_wire)
    request_wire = external_relative_volume_request_wire_dict(_request())
    request_wire["zoneSnapshot"]["polygon"]["coordinates"][0][0][0] = math.inf
    with pytest.raises(JsonSchemaValidationError):
        request_schema.validate(request_wire)


def test_zone_model_rejects_finite_coordinates_beyond_the_wire_schema_limit() -> None:
    """The canonical model and schema share the same JSON-safe coordinate bound."""
    wire = external_volume_zone_snapshot_wire_dict(_zone())
    wire["polygon"]["coordinates"][0][0][0] = 1e301
    wire["polygon"]["coordinates"][0][-1][0] = 1e301
    with pytest.raises(ValidationError, match="wire limit"):
        ExternalVolumeZoneSnapshotV1.model_validate(wire)


@pytest.mark.parametrize("extra_component", ["bad-z", True, math.inf, 1e301])
def test_zone_model_rejects_hostile_later_coordinate_components(
    extra_component: object,
) -> None:
    """Every component admitted by WorkArea geometry is bounded for the external wire."""
    wire = external_volume_zone_snapshot_wire_dict(_zone())
    for position in wire["polygon"]["coordinates"][0]:
        position.append(extra_component)
    schema = Draft202012Validator(
        json.loads(
            (_SCHEMA_DIR / "external-volume-zone-snapshot.v1.json").read_text(encoding="utf-8")
        )
    )
    with pytest.raises(JsonSchemaValidationError):
        schema.validate(wire)
    with pytest.raises(ValidationError, match="coordinate"):
        ExternalVolumeZoneSnapshotV1.model_validate(wire)


def test_zone_model_and_schema_preserve_finite_later_coordinate_components() -> None:
    """External validation retains the WorkArea-compatible dimensionality semantics."""
    polygon = _polygon()
    for index, position in enumerate(polygon["coordinates"][0]):
        position.extend([float(index), -20.0])
    zone = ExternalVolumeZoneSnapshotV1(
        organization_id="organization-1",
        site_id="site-1",
        work_area_id="work-area-1",
        revision=1,
        polygon=polygon,
        crs="EPSG:5186",
        observed_crs_digest=_digest("c"),
        analysis_vertical_reference_digest=_digest("d"),
    ).sealed()
    schema = Draft202012Validator(
        json.loads(
            (_SCHEMA_DIR / "external-volume-zone-snapshot.v1.json").read_text(encoding="utf-8")
        )
    )
    schema.validate(external_volume_zone_snapshot_wire_dict(zone))


def test_schema_rejects_timestamp_suffixes_without_rfc3339_utc_structure() -> None:
    """Default Draft validation enforces the lexical UTC pattern without format opt-in."""
    request_schema = Draft202012Validator(
        json.loads(
            (_SCHEMA_DIR / "external-relative-volume-request.v1.json").read_text(encoding="utf-8")
        )
    )
    request_wire = external_relative_volume_request_wire_dict(_request())
    request_wire["issuedAt"] = "not-a-dateZ"
    with pytest.raises(JsonSchemaValidationError):
        request_schema.validate(request_wire)
    request_wire = external_relative_volume_request_wire_dict(_request())
    request_wire["baseline"]["capturedFrom"] = "not-a-date+00:00"
    with pytest.raises(JsonSchemaValidationError):
        request_schema.validate(request_wire)
    report_schema = Draft202012Validator(
        json.loads(
            (_SCHEMA_DIR / "external-relative-volume-report.v1.json").read_text(encoding="utf-8")
        )
    )
    report_wire = external_relative_volume_report_wire_dict(_report())
    report_wire["computedAt"] = "not-a-dateZ"
    with pytest.raises(JsonSchemaValidationError):
        report_schema.validate(report_wire)


def test_schema_lexical_and_model_semantic_timestamp_validation_are_distinct() -> None:
    """Schema format is annotation by default; the canonical model parses UTC calendar semantics."""
    bad_timestamp = "2026-02-30T01:02:03Z"
    request_schema = json.loads(
        (_SCHEMA_DIR / "external-relative-volume-request.v1.json").read_text(encoding="utf-8")
    )
    request_wire = external_relative_volume_request_wire_dict(_request())
    request_wire["issuedAt"] = bad_timestamp
    Draft202012Validator(request_schema).validate(request_wire)
    with pytest.raises(ValidationError):
        ExternalRelativeVolumeRequestV1.model_validate(request_wire)


def test_schema_uses_model_semantic_geometry_validation_for_ring_closure() -> None:
    """Draft 2020-12 checks structure; the canonical model owns cross-item ring closure."""
    wire = external_volume_zone_snapshot_wire_dict(_zone())
    wire["polygon"]["coordinates"][0][-1] = [1.0, 0.0]
    schema = Draft202012Validator(
        json.loads(
            (_SCHEMA_DIR / "external-volume-zone-snapshot.v1.json").read_text(encoding="utf-8")
        )
    )
    schema.validate(wire)
    with pytest.raises(ValidationError, match="닫혀 있지 않다"):
        ExternalVolumeZoneSnapshotV1.model_validate(wire)
