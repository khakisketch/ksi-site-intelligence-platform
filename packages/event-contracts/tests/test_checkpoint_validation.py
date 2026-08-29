from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.checkpoint_validation import (
    CHECKPOINT_VALIDATION_PROFILE_DIGEST,
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

_NOW = datetime(2026, 8, 29, 3, 0, tzinfo=UTC)
_HEX = "a" * 64
_DSM_DIGEST = "sha256:" + "b" * 64


def _vertical(source: VerticalReferenceSource) -> VerticalReference:
    return VerticalReference(
        datum=VerticalDatum.ELLIPSOIDAL,
        basis="독립 측량 성과표와 처리 파이프라인 기록",
        source=source,
    )


def _declared() -> CheckpointFileDeclared:
    return CheckpointFileDeclared(
        filename="epoch-01-checkpoints.csv",
        sha256=_HEX,
        size_bytes=128,
        crs="EPSG:5186",
        vertical_reference=_vertical(VerticalReferenceSource.USER_DECLARED),
        independent_from_processing_attested=True,
        independence_basis="재구성 GCP와 분리해 별도 토털스테이션 관측",
    )


def _observed(**changes: object) -> CheckpointValidationObserved:
    values: dict[str, object] = {
        "checkpoint_sha256": _HEX,
        "checkpoint_size_bytes": 128,
        "dsm_digest": _DSM_DIGEST,
        "dsm_crs": "EPSG:5186",
        "point_count": 4,
        "mean_error_m": 0.02,
        "mae_m": 0.04,
        "rmse_m": 0.05,
        "max_abs_error_m": 0.08,
        "measured_at": _NOW,
        "measured_by": "worker-1",
    }
    values.update(changes)
    return CheckpointValidationObserved.model_validate(values)


def _validated() -> CheckpointValidation:
    return CheckpointValidation(
        validation_id="mission-1-job1-cp1",
        organization_id="org-1",
        mission_id="mission-1",
        site_id="site-1",
        dsm=ArtifactRef(job_id="mission-1-job1", artifact_id="dsm"),
        dsm_digest=_DSM_DIGEST,
        dsm_crs="EPSG:5186",
        dsm_vertical_reference=_vertical(VerticalReferenceSource.PIPELINE_DECLARED),
        declared=_declared(),
        status=CheckpointValidationStatus.VALIDATED,
        registered_at=_NOW,
        registered_by="operator-1",
        sealed_at=_NOW,
        observed=_observed(),
    )


def test_validated_checkpoint_roundtrips_canonical_wire() -> None:
    record = _validated()
    wire = checkpoint_validation_wire_dict(record)

    assert wire["validationProfileDigest"] == CHECKPOINT_VALIDATION_PROFILE_DIGEST
    assert wire["declared"]["independentFromProcessingAttested"] is True
    assert wire["observed"]["rmseM"] == 0.05
    assert CheckpointValidation.model_validate(wire) == record


def test_independence_attestation_must_be_explicitly_true() -> None:
    payload = _declared().model_dump()
    payload["independent_from_processing_attested"] = False
    with pytest.raises(ValueError, match="independent_from_processing_attested"):
        CheckpointFileDeclared.model_validate(payload)


def test_user_cannot_declare_pipeline_vertical_provenance() -> None:
    payload = _declared().model_dump()
    payload["vertical_reference"] = _vertical(VerticalReferenceSource.PIPELINE_DECLARED)
    with pytest.raises(ValueError, match="user_declared"):
        CheckpointFileDeclared.model_validate(payload)


@pytest.mark.parametrize("filename", ["points.txt", "../points.csv", "a/b.csv", " points.csv"])
def test_checkpoint_filename_is_plain_csv(filename: str) -> None:
    payload = _declared().model_dump()
    payload["filename"] = filename
    with pytest.raises(ValueError):
        CheckpointFileDeclared.model_validate(payload)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"mean_error_m": 0.06}, "meanErrorM"),
        ({"mae_m": 0.06}, "maeM"),
        ({"max_abs_error_m": 0.04}, "rmseM"),
        ({"rmse_m": float("nan")}, "finite"),
    ],
)
def test_observed_metrics_reject_internal_contradictions(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _observed(**changes)


def test_status_cannot_claim_validated_without_observation() -> None:
    payload = _validated().model_dump()
    payload["observed"] = None
    with pytest.raises(ValueError, match="VALIDATED"):
        CheckpointValidation.model_validate(payload)


@pytest.mark.parametrize(
    "status",
    [
        CheckpointValidationStatus.REGISTERED,
        CheckpointValidationStatus.SEALED,
        CheckpointValidationStatus.VALIDATED,
    ],
)
def test_non_rejected_states_cannot_carry_rejection_detail(
    status: CheckpointValidationStatus,
) -> None:
    payload = _validated().model_dump()
    payload["status"] = status
    payload["rejection_detail"] = "hidden rejection"
    if status is CheckpointValidationStatus.REGISTERED:
        payload["sealed_at"] = None
        payload["observed"] = None
    elif status is CheckpointValidationStatus.SEALED:
        payload["observed"] = None
    with pytest.raises(ValueError, match=status.value):
        CheckpointValidation.model_validate(payload)
