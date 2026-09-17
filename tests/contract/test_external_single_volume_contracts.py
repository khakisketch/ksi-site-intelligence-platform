"""Immutable external single-volume contracts stay closed and fail closed.

These tests use only synthetic digests and coordinates.  They establish neither
Core authorization nor an external artifact's eligibility; Core resolves those
facts before a SINGLE_VOLUME decision or request exists.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from external_single_volume_contract_fixture import (
    _binding,
    _decision,
    _digest,
    _metrics,
    _policy,
    _report,
    _request,
)
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from ksi_event_contracts.external_artifact_validation import DecisionVerdict
from ksi_event_contracts.external_single_volume import (
    ExternalSingleVolumeMetricsV1,
    external_single_volume_decision_wire_dict,
    external_single_volume_execution_policy_wire_dict,
    external_single_volume_report_wire_dict,
    external_single_volume_request_wire_dict,
)
from pydantic import ValidationError

_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "contracts/schemas"


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
