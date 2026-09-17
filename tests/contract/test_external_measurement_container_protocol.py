"""Closed framed grammar for the contained two-input measurement image."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

import pytest
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_processing_controller.external_measurement_container_protocol import (
    MeasurementContainerFrameLimitsV2,
    MeasurementContainerProtocolViolation,
    build_completed_frame_v2,
    build_execute_frame_v2,
    build_failed_frame_v2,
    build_prepare_frame_v2,
    build_secondary_begin_frame,
    decode_measurement_container_frame,
    encode_measurement_container_frame,
    validate_prepare_frame_v2,
    validate_terminal_frame_v2,
)
from test_external_measurement_protocol import measurement_manifest_request


def test_prepare_is_closed_canonical_and_binds_both_ordered_inputs() -> None:
    manifest, request = measurement_manifest_request()
    assert request.volume_request is not None
    assert request.volume_execution_policy is not None
    limits = MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000)

    prepare = build_prepare_frame_v2(request=request, manifest=manifest)

    assert set(prepare) == {
        "protocolVersion",
        "frame",
        "requestId",
        "attemptNonce",
        "outerCanonicalInputDigest",
        "operation",
        "fence",
        "measurementRequest",
        "executionManifestBody",
        "executionManifestDigest",
        "prepareDigest",
    }
    assert prepare["measurementRequest"]["inputs"] == [
        item.model_dump(by_alias=True, mode="json") for item in request.inputs
    ]
    validate_prepare_frame_v2(prepare, expected=prepare, limits=limits)
    assert (
        decode_measurement_container_frame(
            encode_measurement_container_frame(prepare, limits=limits), limits=limits
        )
        == prepare
    )


def test_secondary_and_execute_frames_can_only_echo_the_prepared_tokens() -> None:
    manifest, request = measurement_manifest_request()
    prepare = build_prepare_frame_v2(request=request, manifest=manifest)

    secondary = build_secondary_begin_frame(prepare=prepare)
    execute = build_execute_frame_v2(prepare=prepare)

    assert secondary == {
        "protocolVersion": "external-measurement-container.v2",
        "frame": "SECONDARY_BEGIN",
        "attemptNonce": request.attempt_nonce,
        "outerCanonicalInputDigest": request.canonical_input_digest,
        "prepareDigest": prepare["prepareDigest"],
        "role": "CURRENT_DSM",
        "artifactId": request.inputs[1].artifact_id,
        "expectedSizeBytes": request.inputs[1].observed_size_bytes,
        "expectedSha256": request.inputs[1].observed_sha256,
    }
    assert canonical_json_bytes(execute) == canonical_json_bytes(
        {
            "protocolVersion": "external-measurement-container.v2",
            "frame": "EXECUTE_V2",
            "requestId": request.request_id,
            "attemptNonce": request.attempt_nonce,
            "outerCanonicalInputDigest": request.canonical_input_digest,
            "prepareDigest": prepare["prepareDigest"],
            "operation": request.operation,
            "fence": request.fence.model_dump(by_alias=True, mode="json"),
        }
    )


@pytest.mark.parametrize(
    "field",
    (
        "protocolVersion",
        "frame",
        "requestId",
        "attemptNonce",
        "outerCanonicalInputDigest",
        "operation",
        "fence",
        "measurementRequest",
        "executionManifestBody",
        "executionManifestDigest",
        "prepareDigest",
    ),
)
def test_prepare_rejects_every_missing_required_field_with_a_typed_error(field: str) -> None:
    manifest, request = measurement_manifest_request()
    limits = MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000)
    prepare = build_prepare_frame_v2(request=request, manifest=manifest)
    malformed = deepcopy(prepare)
    malformed.pop(field)
    if field != "prepareDigest":
        body = {key: value for key, value in malformed.items() if key != "prepareDigest"}
        malformed["prepareDigest"] = "sha256:" + sha256(canonical_json_bytes(body)).hexdigest()

    with pytest.raises(MeasurementContainerProtocolViolation, match="PREPARE_V2"):
        validate_prepare_frame_v2(malformed, expected=malformed, limits=limits)


def test_terminal_validator_rejects_raw_fields_and_semantic_mismatches() -> None:
    manifest, request = measurement_manifest_request()
    assert request.volume_request is not None
    assert request.volume_execution_policy is not None
    limits = MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000)
    prepare = build_prepare_frame_v2(request=request, manifest=manifest)
    aggregate = {
        "metricType": "RELATIVE_VOLUME_AGGREGATE_V2",
        "zoneId": request.volume_request.zone_snapshot.work_area_id,
        "metrics": {
            "zoneCellCount": 4,
            "commonValidCellCount": 4,
            "zoneAreaM2": 4.0,
            "measuredAreaM2": 4.0,
            "commonValidFraction": 1.0,
            "cutM3": 1.0,
            "fillM3": 5.0,
            "netM3": 4.0,
            "thresholdM": request.volume_execution_policy.threshold_m,
            "uncertaintyM3": None,
            "uncertaintyNote": "Independent checkpoint RMSE is unavailable for one or both epochs.",
        },
    }
    bindings = [
        {
            "role": item.role,
            "artifactId": item.artifact_id,
            "observedSha256": item.observed_sha256,
            "observedSizeBytes": item.observed_size_bytes,
        }
        for item in request.inputs
    ]
    completed = build_completed_frame_v2(
        prepare=prepare,
        input_bindings=bindings,
        aggregate=aggregate,
    )

    assert validate_terminal_frame_v2(completed, prepare=prepare, limits=limits) == completed

    raw = deepcopy(completed)
    raw["aggregate"]["rawCoordinates"] = [[1, 2]]
    with pytest.raises(MeasurementContainerProtocolViolation, match="aggregate"):
        validate_terminal_frame_v2(raw, prepare=prepare, limits=limits)

    mismatched = deepcopy(completed)
    mismatched["aggregate"]["metrics"]["thresholdM"] = 99.0
    with pytest.raises(MeasurementContainerProtocolViolation, match="aggregate"):
        validate_terminal_frame_v2(mismatched, prepare=prepare, limits=limits)

    undercovered = deepcopy(completed)
    undercovered["aggregate"]["metrics"].update(
        {
            "commonValidCellCount": 1,
            "measuredAreaM2": 1.0,
            "commonValidFraction": 0.25,
        }
    )
    with pytest.raises(MeasurementContainerProtocolViolation, match="aggregate"):
        build_completed_frame_v2(
            prepare=prepare,
            input_bindings=bindings,
            aggregate=undercovered["aggregate"],
        )

    unsupported_uncertainty = deepcopy(completed)
    unsupported_uncertainty["aggregate"]["metrics"].update(
        {
            "uncertaintyM3": 987.0,
            "uncertaintyNote": "Independent validated checkpoint RMSE was used for both epochs.",
        }
    )
    with pytest.raises(MeasurementContainerProtocolViolation, match="aggregate"):
        build_completed_frame_v2(
            prepare=prepare,
            input_bindings=bindings,
            aggregate=unsupported_uncertainty["aggregate"],
        )

    boolean_fence = deepcopy(completed)
    boolean_fence["fence"]["leaseGeneration"] = True
    with pytest.raises(MeasurementContainerProtocolViolation, match="authority echoes"):
        validate_terminal_frame_v2(boolean_fence, prepare=prepare, limits=limits)

    failed = build_failed_frame_v2(prepare=prepare, reason="RESOURCE_LIMIT_EXCEEDED")
    hostile_failed = deepcopy(failed)
    hostile_failed["rawCoordinates"] = [[1, 2]]
    with pytest.raises(MeasurementContainerProtocolViolation, match="failed fields"):
        validate_terminal_frame_v2(hostile_failed, prepare=prepare, limits=limits)

    with pytest.raises(MeasurementContainerProtocolViolation, match="failure reason"):
        build_failed_frame_v2(
            prepare=prepare,
            reason="rawCoordinates=[[1,2]]; synthetic-secret=x",
        )

    malformed_kind = deepcopy(completed)
    malformed_kind["frame"] = []
    with pytest.raises(MeasurementContainerProtocolViolation, match="frame shape"):
        validate_terminal_frame_v2(malformed_kind, prepare=prepare, limits=limits)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("measurementRequest", {"invalid": True}),
        ("executionManifestBody", {"invalid": True}),
        ("fence", []),
    ),
)
def test_prepare_normalizes_malformed_nested_authority_to_a_typed_error(
    field: str, value: object
) -> None:
    manifest, request = measurement_manifest_request()
    limits = MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000)
    malformed = build_prepare_frame_v2(request=request, manifest=manifest)
    malformed[field] = value
    body = {key: item for key, item in malformed.items() if key != "prepareDigest"}
    malformed["prepareDigest"] = "sha256:" + sha256(canonical_json_bytes(body)).hexdigest()

    with pytest.raises(MeasurementContainerProtocolViolation, match="PREPARE_V2"):
        validate_prepare_frame_v2(malformed, expected=malformed, limits=limits)


def _single_volume_aggregate(request: object) -> dict[str, object]:
    import numpy as np

    assert hasattr(request, "single_volume_request")
    single = request.single_volume_request  # type: ignore[attr-defined]
    execution = request.single_volume_execution_policy  # type: ignore[attr-defined]
    records = request.volume_evidence_records  # type: ignore[attr-defined]
    assert single is not None and execution is not None
    assert records[0].measurement_payload is not None
    rmse = records[0].measurement_payload.rmse_m
    return {
        "metricType": "SINGLE_VOLUME_AGGREGATE_V2",
        "zoneId": single.zone_snapshot.work_area_id,
        "metrics": {
            "zoneCellCount": 4,
            "commonValidCellCount": 4,
            "zoneAreaM2": 4.0,
            "measuredAreaM2": 4.0,
            "commonValidFraction": 1.0,
            "cutM3": 1.0,
            "fillM3": 5.0,
            "netM3": 4.0,
            "thresholdM": execution.threshold_m,
            "uncertaintyM3": 4.0 * float(np.hypot(0.02, rmse)),
            "uncertaintyNote": (
                "Validated target-epoch checkpoint RMSE and boundary base "
                "roughness were used."
            ),
            "baseRoughnessM": 0.02,
            "boundaryCellCount": 4,
            "boundarySampleCount": 4,
            "boundaryValidFraction": 1.0,
        },
    }


def _single_volume_unknown_request() -> tuple[object, object]:
    from ksi_event_contracts.external_evidence import EvidenceCoreVerdict
    from test_external_measurement_protocol import single_volume_manifest_request

    manifest, request = single_volume_manifest_request()
    assert request.single_volume_request is not None
    record = request.volume_evidence_records[0].model_copy(
        update={
            "core_verdict": EvidenceCoreVerdict.REJECTED,
            "core_reason": "CHECKPOINT_UNAVAILABLE",
            "evidence_record_digest": None,
        }
    ).sealed()
    single = request.single_volume_request.model_copy(
        update={
            "evidence_record_digests": (record.evidence_record_digest,),
            "request_digest": None,
        }
    ).sealed()
    return manifest, request.model_copy(
        update={
            "volume_evidence_records": (record,),
            "single_volume_request": single,
            "canonical_input_digest": None,
        }
    ).sealed()


def test_single_volume_terminal_passes_with_the_exact_metric_field_set() -> None:
    from test_external_measurement_protocol import single_volume_manifest_request

    manifest, request = single_volume_manifest_request()
    limits = MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000)
    prepare = build_prepare_frame_v2(request=request, manifest=manifest)
    aggregate = _single_volume_aggregate(request)
    bindings = [
        {
            "role": item.role,
            "artifactId": item.artifact_id,
            "observedSha256": item.observed_sha256,
            "observedSizeBytes": item.observed_size_bytes,
        }
        for item in request.inputs  # type: ignore[attr-defined]
    ]
    completed = build_completed_frame_v2(
        prepare=prepare, input_bindings=bindings, aggregate=aggregate
    )
    assert validate_terminal_frame_v2(completed, prepare=prepare, limits=limits) == completed
    assert set(completed["aggregate"]["metrics"]) == {
        "zoneCellCount",
        "commonValidCellCount",
        "zoneAreaM2",
        "measuredAreaM2",
        "commonValidFraction",
        "cutM3",
        "fillM3",
        "netM3",
        "thresholdM",
        "uncertaintyM3",
        "uncertaintyNote",
        "baseRoughnessM",
        "boundaryCellCount",
        "boundarySampleCount",
        "boundaryValidFraction",
    }


def test_single_volume_terminal_branches_on_known_vs_unknown_target_rmse() -> None:
    from test_external_measurement_protocol import single_volume_manifest_request

    limits = MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000)
    manifest, request = single_volume_manifest_request()
    prepare = build_prepare_frame_v2(request=request, manifest=manifest)
    bindings = [
        {
            "role": item.role,
            "artifactId": item.artifact_id,
            "observedSha256": item.observed_sha256,
            "observedSizeBytes": item.observed_size_bytes,
        }
        for item in request.inputs
    ]
    known = build_completed_frame_v2(
        prepare=prepare, input_bindings=bindings, aggregate=_single_volume_aggregate(request)
    )
    assert validate_terminal_frame_v2(known, prepare=prepare, limits=limits) == known

    unknown_manifest, unknown = _single_volume_unknown_request()
    unknown_prepare = build_prepare_frame_v2(request=unknown, manifest=unknown_manifest)
    unknown_bindings = [
        {
            "role": item.role,
            "artifactId": item.artifact_id,
            "observedSha256": item.observed_sha256,
            "observedSizeBytes": item.observed_size_bytes,
        }
        for item in unknown.inputs  # type: ignore[attr-defined]
    ]
    aggregate = _single_volume_aggregate(unknown)
    aggregate["metrics"] = {
        **aggregate["metrics"],  # type: ignore[dict-item]
        "uncertaintyM3": None,
        "uncertaintyNote": (
            "Independent target-epoch checkpoint RMSE is unavailable; uncertainty is unknown."
        ),
    }
    missing = build_completed_frame_v2(
        prepare=unknown_prepare, input_bindings=unknown_bindings, aggregate=aggregate
    )
    assert validate_terminal_frame_v2(missing, prepare=unknown_prepare, limits=limits) == missing

    claimed = deepcopy(aggregate)
    claimed["metrics"] = {**claimed["metrics"], "uncertaintyM3": 1.0}  # type: ignore[dict-item]
    with pytest.raises(MeasurementContainerProtocolViolation, match="aggregate"):
        build_completed_frame_v2(
            prepare=unknown_prepare, input_bindings=unknown_bindings, aggregate=claimed
        )
    misnoted = deepcopy(_single_volume_aggregate(request))
    misnoted["metrics"] = {  # type: ignore[dict-item]
        **misnoted["metrics"],  # type: ignore[dict-item]
        "uncertaintyNote": (
            "Independent target-epoch checkpoint RMSE is unavailable; uncertainty is unknown."
        ),
    }
    with pytest.raises(MeasurementContainerProtocolViolation, match="aggregate"):
        build_completed_frame_v2(
            prepare=prepare, input_bindings=bindings, aggregate=misnoted
        )


def test_single_volume_terminal_rejects_altered_uncertainty_fields_and_drift() -> None:
    import numpy as np
    from test_external_measurement_protocol import single_volume_manifest_request

    manifest, request = single_volume_manifest_request()
    prepare = build_prepare_frame_v2(request=request, manifest=manifest)
    bindings = [
        {
            "role": item.role,
            "artifactId": item.artifact_id,
            "observedSha256": item.observed_sha256,
            "observedSizeBytes": item.observed_size_bytes,
        }
        for item in request.inputs
    ]
    aggregate = _single_volume_aggregate(request)
    assert request.volume_evidence_records[0].measurement_payload is not None
    rmse = request.volume_evidence_records[0].measurement_payload.rmse_m

    altered = deepcopy(aggregate)
    altered["metrics"] = {**altered["metrics"], "uncertaintyM3": 4.0 * rmse}  # type: ignore[dict-item]
    with pytest.raises(MeasurementContainerProtocolViolation, match="aggregate"):
        build_completed_frame_v2(
            prepare=prepare, input_bindings=bindings, aggregate=altered
        )
    assert float(np.hypot(0.02, rmse)) != rmse

    missing = deepcopy(aggregate)
    del missing["metrics"]["baseRoughnessM"]  # type: ignore[attr-defined]
    with pytest.raises(MeasurementContainerProtocolViolation, match="aggregate"):
        build_completed_frame_v2(
            prepare=prepare, input_bindings=bindings, aggregate=missing
        )

    extra = deepcopy(aggregate)
    extra["metrics"]["extraField"] = 1.0  # type: ignore[attr-defined]
    with pytest.raises(MeasurementContainerProtocolViolation, match="aggregate"):
        build_completed_frame_v2(prepare=prepare, input_bindings=bindings, aggregate=extra)

    drifted = deepcopy(aggregate)
    drifted["metrics"] = {  # type: ignore[dict-item]
        **drifted["metrics"],  # type: ignore[dict-item]
        "commonValidCellCount": 1,
        "measuredAreaM2": 1.0,
        "commonValidFraction": 0.25,
    }
    with pytest.raises(MeasurementContainerProtocolViolation, match="aggregate"):
        build_completed_frame_v2(
            prepare=prepare, input_bindings=bindings, aggregate=drifted
        )

    threshold = deepcopy(aggregate)
    threshold["metrics"] = {**threshold["metrics"], "thresholdM": 99.0}  # type: ignore[dict-item]
    with pytest.raises(MeasurementContainerProtocolViolation, match="aggregate"):
        build_completed_frame_v2(
            prepare=prepare, input_bindings=bindings, aggregate=threshold
        )

    zone = deepcopy(aggregate)
    zone["zoneId"] = "other-zone"
    with pytest.raises(MeasurementContainerProtocolViolation, match="aggregate"):
        build_completed_frame_v2(prepare=prepare, input_bindings=bindings, aggregate=zone)

    count = deepcopy(aggregate)
    count["metrics"] = {  # type: ignore[dict-item]
        **count["metrics"],  # type: ignore[dict-item]
        "boundarySampleCount": 1,
        "boundaryValidFraction": 0.25,
    }
    with pytest.raises(MeasurementContainerProtocolViolation, match="aggregate"):
        build_completed_frame_v2(prepare=prepare, input_bindings=bindings, aggregate=count)
