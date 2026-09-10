"""Trusted checkpoint context binds actual scope, thresholds and attestations."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ksi_event_contracts.external_evidence_context import (
    ExternalEvidenceMeasurementContextV1,
    ExternalIndependenceAttestationV1,
)
from support.external_artifact_inspection_fixtures import digest, subject


def context_wire() -> dict[str, Any]:
    return dict(
        context_id="context-1",
        subject=subject(include_dsm=True),
        evidence_manifest_digest=digest("a"),
        evidence_observed_sha256=digest("e"),
        evidence_observed_size_bytes=321,
        target_dsm_artifact_id="dsm",
        target_dsm_observed_sha256=digest("b"),
        policy_digest=digest("c"),
        measurement_execution_manifest_digest=digest("f"),
        rule_id="CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",
        csv_horizontal_crs="EPSG:5186",
        csv_vertical_reference_digest=digest("d"),
        minimum_checkpoint_count=3,
        maximum_checkpoint_count=100,
        maximum_rmse_m=0.5,
        maximum_abs_mean_error_m=0.2,
        maximum_abs_error_m=1.0,
        independent_attestation=None,
        authorized_actor_ids=("validator-owner",),
        active_from=datetime(2026, 9, 9, tzinfo=UTC),
        active_until=datetime(2026, 9, 10, tzinfo=UTC),
        synthetic_test_only=True,
    )


def test_context_without_attestation_cannot_claim_independence() -> None:
    context = ExternalEvidenceMeasurementContextV1(**context_wire()).sealed()
    assert context.independent_attestation is None
    assert context.evidence_observed_sha256 == digest("e")
    assert context.evidence_observed_size_bytes == 321
    assert context.measurement_execution_manifest_digest == digest("f")
    assert context.context_digest == context.canonical_digest()


@pytest.mark.parametrize(
    "changes",
    [
        {"maximum_rmse_m": float("inf")},
        {"maximum_checkpoint_count": 2},
        {"minimum_checkpoint_count": True},
        {"active_until": datetime(2026, 9, 8, tzinfo=UTC)},
        {"active_from": 0},
        {"csv_horizontal_crs": ""},
        {"authorized_actor_ids": ()},
        {"context_digest": digest("f")},
    ],
)
def test_context_rejects_unbounded_or_unsealed_authority(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ExternalEvidenceMeasurementContextV1(**(context_wire() | changes))


def test_context_rejects_attestation_for_another_dsm() -> None:
    wire = context_wire()
    attestation = ExternalIndependenceAttestationV1(
        attestation_id="attestation-1",
        evidence_manifest_digest=wire["evidence_manifest_digest"],
        subject_digest=wire["subject"].canonical_digest(),
        target_dsm_observed_sha256=digest("e"),
        confirmed_by_actor_id="validator-owner",
        confirmed_at=wire["active_from"] - timedelta(hours=1),
        reconstruction_exclusion_basis="Independent synthetic check points excluded from inputs",
        synthetic_test_only=True,
    ).sealed()
    with pytest.raises(ValueError, match="attestation"):
        ExternalEvidenceMeasurementContextV1(**(wire | {"independent_attestation": attestation}))
