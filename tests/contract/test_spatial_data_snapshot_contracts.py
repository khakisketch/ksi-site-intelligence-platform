"""Exact source/job/receipt bindings, distinct states and immutable snapshots."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from ksi_event_contracts.spatial_data import (
    SpatialDataAvailabilityV1,
    SpatialDataExecutionStateV1,
    SpatialDataJobViewV1,
    SpatialDataPageV1,
)
from pydantic import ValidationError
from spatial_data_fixture import (
    DIGEST,
    JOB_ID,
    NOW,
    make_attempt,
    make_grant,
    make_job,
    make_measurements,
    make_policy,
    make_receipt,
    make_request,
    make_source,
)
from test_spatial_data_contracts import _validator


@pytest.mark.parametrize("factory", [make_source, make_job, make_attempt, make_receipt])
def test_snapshot_roundtrip_and_schema(factory: Callable[..., Any]) -> None:
    snapshot = factory()
    wire = snapshot.model_dump(by_alias=True, mode="json")
    _validator(type(snapshot).__name__, "spatial-data").validate(wire)
    assert type(snapshot).model_validate_json(snapshot.model_dump_json()) == snapshot
    digest_fields = [k for k in type(snapshot).model_fields if k.endswith("_digest")]
    own = {
        make_source: "source_digest",
        make_job: "job_digest",
        make_attempt: "attempt_digest",
        make_receipt: "receipt_digest",
    }[factory]
    assert own in digest_fields
    assert getattr(snapshot, own) == snapshot.canonical_digest()
    wire[type(snapshot).model_fields[own].alias] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError):
        type(snapshot).model_validate(wire)


@pytest.mark.parametrize(
    "changes",
    [
        {"site_id": "other"},
        {"work_order_id": "other"},
        {"revision": 2},
        {"artifact_id": "other"},
        {"observed_sha256": "sha256:" + "0" * 64},
        {"artifact_kind": "mesh"},
        {"observed_size_bytes": True},
        {"capture_started_at": NOW, "capture_ended_at": None},
        {"capture_started_at": NOW, "capture_ended_at": NOW - timedelta(seconds=1)},
    ],
)
def test_source_rejects_identity_or_declared_time_substitution(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_source(**changes)


@pytest.mark.parametrize(
    "measurements",
    [
        {"dtype": "uint8"},
        {"band_count": 3},
        {"layout": "UNSUPPORTED"},
        {"transform": (1.0, 1.0, 0.0, 0.0, -1.0, 10.0)},
        {"transform": (-1.0, 0.0, 0.0, 0.0, -1.0, 10.0)},
    ],
)
def test_source_refuses_unsupported_native_profile(measurements: dict[str, Any]) -> None:
    inspection = make_source().inspection.model_copy(
        update={"measurements": make_measurements(**measurements)}
    )
    with pytest.raises(ValidationError):
        make_source(inspection=inspection)


def test_source_requires_measured_outcome_not_rejected_metadata() -> None:
    inspection = make_source().inspection.model_copy(
        update={"outcome": "REJECTED", "measurements": None, "reason": "UNSUPPORTED_FORMAT"}
    )
    with pytest.raises(ValidationError):
        make_source(inspection=inspection)


def test_orthophoto_can_be_admitted_without_vertical_reference() -> None:
    measurements = make_measurements(dtype="uint8", band_count=4)
    inspection = make_source().inspection.model_copy(update={"measurements": measurements})
    source = make_source(artifact_kind="ortho", inspection=inspection)
    assert source.inspection.measurements is not None
    assert source.inspection.measurements.observed_vertical_reference is None


@pytest.mark.parametrize(
    "changes",
    [
        {"organization_id": "foreign"},
        {"site_id": "other"},
        {"work_area_id": "other"},
        {"requester_principal_id": "other"},
        {"job_id": "arbitrary"},
        {"request": make_request(asset_ref="ksa-v1-" + "0" * 64)},
        {"request_fingerprint": "sha256:" + "0" * 64},
        {"grant": make_grant(policy_digest="sha256:" + "0" * 64)},
        {"deadline": NOW},
        {"deadline": NOW + timedelta(seconds=31)},
        {"policy": make_policy().model_copy(update={"policy_digest": None})},
    ],
)
def test_frozen_job_rejects_mixed_scope_unbound_snapshots_and_deadline(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        make_job(**changes)


def test_attempt_fence_identity_survives_renewal_without_reusing_payload_digest() -> None:
    first = make_attempt()
    renewal = make_attempt(lease_until=NOW + timedelta(seconds=8))
    assert first.fence_digest() == renewal.fence_digest()
    assert first.attempt_digest != renewal.attempt_digest
    assert first.fence_digest() != make_attempt(fence=2).fence_digest()
    assert first.fence_digest() != make_attempt(worker_instance_id="other").fence_digest()
    with pytest.raises(ValidationError):
        make_attempt(lease_until=NOW)
    with pytest.raises(ValidationError):
        make_attempt(fence=True)


@pytest.mark.parametrize(
    "changes",
    [
        {"accuracy_assessed": True},
        {"accuracy_assessed": 0},
        {"output_size_bytes": True},
        {"source_sha256": "a" * 64},
        {"pixel_window": (False, 9, 1, 10)},
        {"width": 2},
        {"height": 2},
        {"valid_pixel_count": 0},
        {"valid_pixel_count": 2},
        {"actual_bounds": (0, 0, 2, 1)},
        {"requested_bounds": (0, 0, 2, 1)},
        {"transform": (1, 1, 0, 0, -1, 1)},
        {"nodata_representation": "FINITE"},
        {"nodata_value": 0.0},
        {"limitations": ()},
        {"band_count": 3},
        {"observed_crs_digest": "sha256:" + "0" * 64},
    ],
)
def test_receipt_refuses_inconsistent_or_accuracy_claiming_output(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_receipt(**changes)


def test_job_view_separates_completed_history_from_current_rights() -> None:
    receipt = make_receipt()
    view = SpatialDataJobViewV1(
        job_id=JOB_ID,
        asset_ref=make_source().asset_ref,
        site_id="site-local",
        work_area_id="area-local",
        created_at=NOW,
        execution_state=SpatialDataExecutionStateV1.COMPLETED,
        availability=SpatialDataAvailabilityV1.ACCESS_REVOKED,
        receipt=receipt,
        reason="ACCESS_REVOKED",
        remediation=("REQUEST_NEW_GRANT",),
    )
    assert view.execution_state == "COMPLETED"
    assert view.availability == "ACCESS_REVOKED"
    wire = view.model_dump(by_alias=True, mode="json")
    assert "objectKey" not in wire and "grant" not in wire and "policy" not in wire
    with pytest.raises(ValidationError):
        SpatialDataJobViewV1.model_validate({**view.model_dump(), "receipt": None})
    with pytest.raises(ValidationError):
        SpatialDataJobViewV1.model_validate({**view.model_dump(), "execution_state": "RUNNING"})
    with pytest.raises(ValidationError):
        SpatialDataPageV1(items=(view,), next_cursor="x" * 2049)


def test_source_facts_are_digest_bound_and_nested_tampering_is_revalidated() -> None:
    original = make_source()
    inspection = original.inspection.model_copy(update={"observed_sha256": DIGEST + "bad"})
    forged = original.model_copy(update={"inspection": inspection})
    with pytest.raises(ValidationError):
        forged.canonical_digest()


def test_receipt_adopts_column_interval_then_row_interval_order() -> None:
    receipt = make_receipt(
        pixel_window=(2, 5, 3, 7),
        width=3,
        height=4,
        valid_pixel_count=12,
        requested_bounds=(2.2, 3.1, 4.1, 6.2),
        actual_bounds=(2, 3, 5, 7),
        transform=(1, 0, 2, 0, -1, 7),
    )
    assert receipt.pixel_window == (2, 5, 3, 7)
    assert (receipt.width, receipt.height) == (3, 4)
    with pytest.raises(ValidationError):
        make_receipt(
            pixel_window=(2, 3, 5, 7),
            width=3,
            height=4,
            valid_pixel_count=12,
            requested_bounds=(2.2, 3.1, 4.1, 6.2),
            actual_bounds=(2, 3, 5, 7),
            transform=(1, 0, 2, 0, -1, 7),
        )


def test_receipt_preserves_original_resolution_and_declared_time_provenance() -> None:
    receipt = make_receipt()
    assert receipt.source_resolution == (1.0, 1.0)
    assert receipt.declaration_recorded_at == NOW
    assert receipt.timestamp_provenance == "SUBMISSION_DECLARATION"
    with pytest.raises(ValidationError):
        make_receipt(source_resolution=(0.5, 1.0))
    with pytest.raises(ValidationError):
        make_receipt(timestamp_provenance="INDEPENDENTLY_VERIFIED")


def test_receipt_rejects_unrepresentable_integer_indices_before_float_arithmetic() -> None:
    with pytest.raises(ValidationError):
        make_receipt(
            pixel_window=(1, 10**1000, 0, 1), width=10**1000 - 1, height=1, valid_pixel_count=1
        )
