"""Pure contract tests for the native C++ artifact replay oracle."""

from __future__ import annotations

import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "edge"))

from verify_native_artifact_oracle import (  # noqa: E402
    verify_native_event_payload,
    verify_native_vertical_slice,
    verify_payload,
)


def _payload() -> dict[str, object]:
    timestamp = datetime(2024, 8, 30, 6, 40, tzinfo=UTC).isoformat()
    return {
        "worldEntity": {
            "schemaVersion": "1.0",
            "entityId": "edge-track-7-1",
            "class": "Vehicle_Truck",
            "timestamp": timestamp,
            "siteFrame": "site-frame-v1",
            "pose": {"position": [10.0, 20.0, 5.0], "velocity": [2.0, 1.0, 0.0]},
            "uncertainty": {
                "positionCovariance": [1.0, 0.0, 0.0, 0.0, 4.0, 0.0, 0.0, 0.0, 0.25],
                "classificationConfidence": 0.9,
                "localizationState": "INSUFFICIENT_OBSERVATION",
            },
            "lineage": {
                "trackId": "edge-track-7-1",
                "modelVersions": {"dfine": "sha256:model"},
                "calibrationProfileId": "cal-v1",
                "observationIds": ["obs-1"],
                "classificationOntologyVersion": "ksi-ontology-v1",
                "classificationSource": {
                    "taxonomy": "COCO-2017",
                    "sourceClassIds": [7],
                    "sourceClassNames": ["truck"],
                },
            },
        },
        "riskField": {
            "schemaVersion": "1.1",
            "riskFieldId": "risk-edge-track-7-1-1725000000000",
            "type": "PREDICTED",
            "hazardType": "EQUIPMENT_FOOTPRINT",
            "sourceEntityIds": ["edge-track-7-1"],
            "validity": {"from": timestamp, "to": "2024-08-30T06:40:02Z"},
            "geometry": {
                "format": "EXTRUDED_POLYGON",
                "payload": {
                    "vertices": [[4.0, 15.0], [20.0, 15.0], [20.0, 27.0], [4.0, 27.0]],
                    "zMinM": 0.0,
                    "zMaxM": 10.0,
                },
            },
            "riskModel": {
                "policyId": "risk-truck-v1",
                "severity": 0.7,
                "predictionHorizonSeconds": 2.0,
            },
            "uncertainty": {"marginM": 4.0, "occlusionExpanded": False},
            "lineage": {
                "riskPolicyPackDigest": "sha256:" + "a" * 64,
                "calibrationProfileId": "cal-v1",
                "sourceTimestamp": timestamp,
            },
        },
    }


def test_oracle_accepts_cross_bound_v1_1_artifacts() -> None:
    fingerprint, risk_field_id = verify_payload(_payload())
    assert len(fingerprint) == 64
    assert risk_field_id.startswith("risk-edge-track")


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("riskField", "sourceEntityIds"), ["other-track"], "sourceEntityIds"),
        (("riskField", "lineage", "calibrationProfileId"), "cal-other", "calibrationProfileId"),
        (("riskField", "lineage", "sourceTimestamp"), "2024-08-30T06:40:01Z", "sourceTimestamp"),
    ],
)
def test_oracle_rejects_cross_artifact_lineage_drift(
    path: tuple[str, ...], value: object, message: str
) -> None:
    payload = deepcopy(_payload())
    target: object = payload
    for key in path[:-1]:
        assert isinstance(target, dict)
        target = target[key]
    assert isinstance(target, dict)
    target[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        verify_payload(payload)


def _event_payload() -> dict[str, object]:
    return {
        "schemaVersion": "1.2",
        "eventId": "evt-edge-001",
        "missionId": "mission-edge-001",
        "siteId": "site-001",
        "eventType": "EQUIPMENT_RISK_OBSERVATION",
        "occurredAt": "2024-08-30T06:40:00.000Z",
        "status": "CANDIDATE",
        "entities": ["edge-track-7-1"],
        "spatialContext": {"riskFieldId": "risk-edge-track-7-1-1"},
        "reasoning": {"riskFieldId": "risk-edge-track-7-1-1"},
        "evidence": {"riskFieldArtifact": "risk-edge-track-7-1-1"},
        "lineage": {
            "edgeVersion": "edge-runtime-test",
            "modelVersions": {"dfine": "sha256:model"},
            "policyVersion": "risk-truck-v1",
            "calibrationProfileId": "cal-v1",
            "classification": {
                "edge-track-7-1": {
                    "entityClass": "Vehicle_Truck",
                    "ontologyVersion": "ksi-ontology-v1",
                    "entityFingerprint": "a" * 64,
                    "source": {
                        "taxonomy": "COCO-2017",
                        "sourceClassIds": [7],
                        "sourceClassNames": ["truck"],
                    },
                }
            },
        },
    }


def test_event_oracle_accepts_candidate_with_exact_risk_field_identity() -> None:
    digest = verify_native_event_payload(_event_payload())
    assert digest.startswith("sha256:")


def test_event_oracle_rejects_risk_field_artifact_lineage_drift() -> None:
    payload = _event_payload()
    assert isinstance(payload["evidence"], dict)
    payload["evidence"]["riskFieldArtifact"] = "other-risk-field"
    with pytest.raises(ValueError, match="RiskField artifact reference"):
        verify_native_event_payload(payload)


def test_vertical_slice_oracle_requires_event_to_name_the_native_risk_field() -> None:
    artifacts = _payload()
    event = _event_payload()
    assert isinstance(artifacts["riskField"], dict)
    risk_field_id = artifacts["riskField"]["riskFieldId"]
    assert isinstance(risk_field_id, str)
    assert isinstance(event["evidence"], dict)
    assert isinstance(event["reasoning"], dict)
    assert isinstance(event["spatialContext"], dict)
    event["evidence"]["riskFieldArtifact"] = risk_field_id
    event["reasoning"]["riskFieldId"] = risk_field_id
    event["spatialContext"]["riskFieldId"] = risk_field_id
    _fingerprint, resolved_risk_id, digest = verify_native_vertical_slice(artifacts, event)
    assert resolved_risk_id == risk_field_id
    assert digest.startswith("sha256:")


def test_vertical_slice_oracle_rejects_cross_fixture_risk_identity_drift() -> None:
    with pytest.raises(ValueError, match="does not name native RiskField"):
        verify_native_vertical_slice(_payload(), _event_payload())
