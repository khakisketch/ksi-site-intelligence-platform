"""The public result is canonical, exact-request-bound and aggregate-only."""

from copy import deepcopy
from typing import Any

import pytest
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_processing_controller.external_inspector_protocol import (
    ProtocolViolation,
)
from ksi_processing_controller.external_measurement_container_protocol import (
    build_failed_frame_v2,
    build_prepare_frame_v2,
)
from ksi_processing_controller.external_measurement_result import (
    RelativeVolumeAggregateV2,
    build_measurement_result,
    decode_measurement_result,
)
from test_external_measurement_protocol import limits, measurement_manifest_request


def result_fixture() -> tuple[Any, Any, Any]:
    manifest, request = measurement_manifest_request()
    assert request.volume_request is not None
    assert request.volume_execution_policy is not None
    terminal = build_failed_frame_v2(
        prepare=build_prepare_frame_v2(request=request, manifest=manifest),
        reason="INSUFFICIENT_COMMON_VALID_COVERAGE",
    )
    result = build_measurement_result(
        terminal=terminal, request=request, manifest=manifest, limits=limits()
    )
    return manifest, request, result


def test_failed_result_round_trip_has_no_metrics_or_raw_inner_fields() -> None:
    manifest, request, result = result_fixture()
    encoded = result.canonical_bytes(request=request, manifest=manifest, limits=limits())
    assert (
        decode_measurement_result(encoded, request=request, manifest=manifest, limits=limits())
        == result
    )
    body = result.model_dump(by_alias=True, mode="json")
    assert body["status"] == "FAILED" and body["aggregate"] is None
    assert body["reason"] == "INSUFFICIENT_COMMON_VALID_COVERAGE"
    assert body["inputs"] == [i.model_dump(by_alias=True, mode="json") for i in request.inputs]
    assert "prepareDigest" not in body and "frame" not in body


@pytest.mark.parametrize(
    "field,value",
    [
        ("requestId", "foreign"),
        ("attemptNonce", "other"),
        ("executionManifestDigest", "sha256:" + "a" * 64),
        ("canonicalInputDigest", "sha256:" + "b" * 64),
        ("operation", "CHECKPOINT_VALIDATION"),
        ("reason", "private /host/path"),
        ("status", "COMPLETED"),
    ],
)
def test_result_rejects_substitution(field: str, value: Any) -> None:
    manifest, request, result = result_fixture()
    body = result.model_dump(by_alias=True, mode="json")
    body[field] = value
    with pytest.raises(ProtocolViolation):
        decode_measurement_result(
            canonical_json_bytes(body),
            request=request,
            manifest=manifest,
            limits=limits(),
        )


def test_result_rejects_raw_extra_and_noncanonical_bytes() -> None:
    manifest, request, result = result_fixture()
    body = result.model_dump(by_alias=True, mode="json")
    extra = deepcopy(body)
    extra["coordinates"] = [[1, 2]]
    for encoded in (canonical_json_bytes(extra), b" " + canonical_json_bytes(body)):
        with pytest.raises(ProtocolViolation):
            decode_measurement_result(encoded, request=request, manifest=manifest, limits=limits())


def test_completed_volume_roundtrip_revalidates_coverage_uncertainty_and_metrics() -> None:
    from ksi_processing_controller.external_measurement_container_protocol import (
        build_completed_frame_v2,
    )

    manifest, request = measurement_manifest_request()
    assert request.volume_request is not None
    assert request.volume_execution_policy is not None
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
    terminal = build_completed_frame_v2(
        prepare=build_prepare_frame_v2(request=request, manifest=manifest),
        input_bindings=[i.model_dump(by_alias=True, mode="json") for i in request.inputs],
        aggregate=aggregate,
    )
    result = build_measurement_result(
        terminal=terminal, request=request, manifest=manifest, limits=limits()
    )
    encoded = result.canonical_bytes(request=request, manifest=manifest, limits=limits())
    decoded = decode_measurement_result(
        encoded, request=request, manifest=manifest, limits=limits()
    )
    assert isinstance(decoded.aggregate, RelativeVolumeAggregateV2)
    assert decoded.aggregate.metrics.net_m3 == 4.0
    for field, value in (
        ("netM3", 9.0),
        ("uncertaintyM3", 0.0),
        ("thresholdM", 999.0),
        ("commonValidFraction", 0.1),
    ):
        body = deepcopy(result.model_dump(by_alias=True, mode="json"))
        body["aggregate"]["metrics"][field] = value
        with pytest.raises(ProtocolViolation):
            decode_measurement_result(
                canonical_json_bytes(body), request=request, manifest=manifest, limits=limits()
            )


def test_result_respects_output_cap_even_when_header_cap_is_larger() -> None:
    manifest, request, result = result_fixture()
    restricted = limits().model_copy(update={"max_output_bytes": 1})
    with pytest.raises(ProtocolViolation):
        result.canonical_bytes(request=request, manifest=manifest, limits=restricted)
