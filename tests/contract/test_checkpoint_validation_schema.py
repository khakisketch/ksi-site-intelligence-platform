from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.checkpoint_validation import (
    CheckpointFileDeclared,
    CheckpointValidation,
    CheckpointValidationObserved,
    CheckpointValidationStatus,
    checkpoint_validation_wire_dict,
)
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)

_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "schemas"
    / "checkpoint-validation.v1.json"
)


def _reference(source: VerticalReferenceSource) -> VerticalReference:
    return VerticalReference(
        datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
        basis="fixture",
        source=source,
    )


def test_checkpoint_validation_wire_matches_draft_2020_12_schema() -> None:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    now = datetime(2026, 8, 29, tzinfo=UTC)
    record = CheckpointValidation(
        validation_id="cv-1",
        organization_id="org-1",
        mission_id="mission-1",
        site_id="site-1",
        dsm=ArtifactRef(job_id="job-1", artifact_id="dsm"),
        dsm_digest="sha256:" + "b" * 64,
        dsm_crs="EPSG:5186",
        dsm_vertical_reference=_reference(VerticalReferenceSource.PIPELINE_DECLARED),
        declared=CheckpointFileDeclared(
            filename="checkpoints.csv",
            sha256="a" * 64,
            size_bytes=120,
            crs="EPSG:5186",
            vertical_reference=_reference(VerticalReferenceSource.USER_DECLARED),
            independent_from_processing_attested=True,
            independence_basis="GCP와 분리된 성과",
        ),
        status=CheckpointValidationStatus.VALIDATED,
        registered_at=now,
        registered_by="operator-1",
        sealed_at=now,
        observed=CheckpointValidationObserved(
            checkpoint_sha256="a" * 64,
            checkpoint_size_bytes=120,
            dsm_digest="sha256:" + "b" * 64,
            dsm_crs="EPSG:5186",
            point_count=3,
            mean_error_m=0.0,
            mae_m=0.03,
            rmse_m=0.04,
            max_abs_error_m=0.06,
            measured_at=now,
            measured_by="worker-1",
        ),
    )
    Draft202012Validator(schema).validate(checkpoint_validation_wire_dict(record))


def test_schema_rejects_pipeline_claim_or_hidden_detail_in_non_rejected_state() -> None:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    now = datetime(2026, 8, 29, tzinfo=UTC)
    record = CheckpointValidation(
        validation_id="cv-1",
        organization_id="org-1",
        mission_id="mission-1",
        site_id="site-1",
        dsm=ArtifactRef(job_id="job-1", artifact_id="dsm"),
        dsm_digest="sha256:" + "b" * 64,
        dsm_crs="EPSG:5186",
        dsm_vertical_reference=_reference(VerticalReferenceSource.PIPELINE_DECLARED),
        declared=CheckpointFileDeclared(
            filename="checkpoints.csv",
            sha256="a" * 64,
            size_bytes=120,
            crs="EPSG:5186",
            vertical_reference=_reference(VerticalReferenceSource.USER_DECLARED),
            independent_from_processing_attested=True,
            independence_basis="GCP와 분리된 성과",
        ),
        status=CheckpointValidationStatus.REGISTERED,
        registered_at=now,
        registered_by="operator-1",
    )
    wire = checkpoint_validation_wire_dict(record)

    pipeline_claim = json.loads(json.dumps(wire))
    pipeline_claim["declared"]["verticalReference"]["source"] = "pipeline_declared"
    with pytest.raises(ValidationError):
        validator.validate(pipeline_claim)

    hidden_detail = json.loads(json.dumps(wire))
    hidden_detail["rejectionDetail"] = "must not survive"
    with pytest.raises(ValidationError):
        validator.validate(hidden_detail)
