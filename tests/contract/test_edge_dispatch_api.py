"""Core Edge dispatch·activation receipt·장비 소유 evidence 계약 테스트."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.edge_dispatch import (
    EdgeDispatchRecoveryError,
    EdgeDispatchStore,
    EdgeRuntimeProfileRegistry,
    RiskPolicyPackRegistry,
)
from ksi_core.events import EventStore, EventVerdict, make_event_key
from ksi_core.evidence import DigestBoundUploadCapability
from ksi_core.mission_records import MissionRecord, MissionRecordVerdict, MissionStore
from ksi_mission_contracts.dispatch import DispatchVerdict, verify_mission_dispatch_envelope
from ksi_mission_contracts.risk_policy import RiskPolicyPackV1
from ksi_mission_contracts.runtime_profile import EdgeRuntimeProfileV1
from ksi_mission_contracts.signing import KeyRegistry, sign_contract

_EDGE_TOKEN = "edge-token"  # noqa: S105 -- test-only fixed credential
_OTHER_EDGE_TOKEN = "other-edge-token"  # noqa: S105 -- test-only fixed credential
_ADMIN_TOKEN = "admin-token"  # noqa: S105 -- test-only fixed credential
_EDGE_ID = "edge-001"
_OTHER_EDGE_ID = "edge-002"


class _LegacyStorage:
    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        del content_type, ttl
        return f"https://evidence.example/put/{object_key}"

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        del ttl
        return f"https://evidence.example/get/{object_key}"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        del object_key, data, content_type

    def get_bytes(self, object_key: str) -> bytes:
        del object_key
        return b""

    def delete(self, object_key: str) -> None:
        del object_key


class _Storage(_LegacyStorage):
    def __init__(self) -> None:
        self.bound_calls: list[tuple[str, str, str]] = []

    def presigned_put_bound_digest(
        self,
        object_key: str,
        *,
        content_type: str,
        content_digest: str,
        ttl: Any,
    ) -> DigestBoundUploadCapability:
        del ttl
        self.bound_calls.append((object_key, content_type, content_digest))
        checksum = base64.b64encode(
            bytes.fromhex(content_digest.removeprefix("sha256:"))
        ).decode("ascii")
        return DigestBoundUploadCapability(
            upload_url=f"https://evidence.example/put/{object_key}",
            required_headers={
                "Content-Type": content_type,
                "x-amz-checksum-sha256": checksum,
            },
        )


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_EDGE_TOKEN),
                principal=Principal(
                    principal_id="edge-principal",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id=_EDGE_ID,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OTHER_EDGE_TOKEN),
                principal=Principal(
                    principal_id="other-edge-principal",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id=_OTHER_EDGE_ID,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_ADMIN_TOKEN),
                principal=Principal(
                    principal_id="admin-principal",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            ),
        ]
    )


def _pack(now: datetime) -> RiskPolicyPackV1:
    return RiskPolicyPackV1.model_validate(
        {
            "schemaVersion": "1.0",
            "riskPolicyPackId": "risk-pack-1",
            "validity": {
                "notBefore": (now - timedelta(minutes=1)).isoformat(),
                "notAfter": (now + timedelta(hours=1)).isoformat(),
            },
            "calibrationProfileId": "cal-001",
            "equipmentPolicies": [
                {
                    "equipmentClass": "Excavator",
                    "riskFieldPolicyId": "excavator-v1",
                    "footprint": {"lengthM": 9, "widthM": 3, "heightM": 4},
                    "prediction": {"horizonSeconds": 5, "samplePeriodSeconds": 0.25},
                    "covarianceSigmaMultiplier": 3,
                    "occlusionExpansionM": 1,
                    "severity": 0.8,
                }
            ],
        }
    )


def _contract(now: datetime) -> dict[str, Any]:
    return {
        "schemaVersion": "1.2",
        "missionId": "mission-edge-001",
        "siteId": "site-001",
        "missionType": "UNIFIED_SITE_SURVEY",
        "validity": {
            "notBefore": (now - timedelta(minutes=1)).isoformat(),
            "notAfter": (now + timedelta(hours=1)).isoformat(),
        },
        "siteFrame": {
            "crs": "EPSG:5186",
            "verticalDatum": "KNGeoid2018",
            "unit": "meter",
            "transformVersion": "1.0.0",
        },
        "flightEnvelope": {
            "allowedVolumes": ["vol-1"],
            "excludedVolumes": [],
            "minAltitudeM": 5.0,
            "maxAltitudeM": 120.0,
        },
        "objectives": ["observe"],
        "policies": {
            "viewpointPolicyId": "vp-1",
            "riskPolicyPackId": "risk-pack-1",
            "fallbackPolicyId": "fb-1",
            "capturePolicyId": "cp-1",
            "coveragePolicy": {
                "mandatoryHazardCoverage": 1.0,
                "mandatoryAssetCoverage": 1.0,
                "accessibleGeneralCoverage": 0.95,
            },
            "communicationLossPolicy": {
                "serverLink": "CONTINUE_WHILE_CONTRACT_AND_SAFETY_VALID",
                "rcCommandLink": "DELEGATE_TO_DJI_FLIGHT_CONTROLLER",
            },
            "batteryPolicy": {"mode": "RETURN_ENERGY_PLUS_RESERVE", "defaultReservePercent": 30},
            "unknownObstaclePolicy": {"initialAction": "STOP", "unresolvedAction": "DEFER_AREA"},
            "evidencePolicy": {
                "candidatePrePostSeconds": 3,
                "highPrePostSeconds": 5,
                "criticalPrePostSeconds": 10,
            },
        },
        "artifacts": {"modelPackId": "model-pack-001", "calibrationProfileId": "cal-001"},
    }


def _bundle(now: datetime) -> dict[str, Any]:
    return {
        "schemaVersion": "1.2",
        "eventId": "evt-001",
        "missionId": "mission-edge-001",
        "siteId": "site-001",
        "eventType": "PERSON_PRESENT",
        "occurredAt": now.isoformat(),
        "status": "CANDIDATE",
        "entities": ["ent-1"],
        "spatialContext": {},
        "reasoning": {},
        "evidence": {},
        "lineage": {
            "edgeVersion": "edge-test",
            "modelVersions": {"detector": "test"},
            "policyVersion": "risk-pack-1",
            "calibrationProfileId": "cal-001",
            "classification": {
                "ent-1": {
                    "entityClass": "Person",
                    "ontologyVersion": "ksi-ontology-v1",
                    "source": {
                        "taxonomy": "COCO-2017",
                        "sourceClassIds": [0],
                        "sourceClassNames": ["person"],
                    },
                    "entityFingerprint": "a" * 64,
                }
            },
        },
    }


def _profile(now: datetime) -> EdgeRuntimeProfileV1:
    return EdgeRuntimeProfileV1.model_validate(
        {
            "schemaVersion": "1.0",
            "edgeRuntimeProfileId": "runtime-profile-001",
            "validity": {
                "notBefore": (now - timedelta(minutes=1)).isoformat(),
                "notAfter": (now + timedelta(hours=1)).isoformat(),
            },
            "siteId": "site-001",
            "model": {
                "modelPackId": "model-pack-001",
                "modelId": "ksi-person-detector-dfine-s-coco",
                "onnxArtifactId": "dfine-s.onnx",
                "registeredOnnxDigest": "sha256:" + "a" * 64,
                "engineArtifactId": "dfine-s.engine",
                "maxOnnxBytes": 104857600,
                "maxEngineBytes": 209715200,
                "workspaceBytes": 104857600,
                "tensorContract": {
                    "inputWidth": 640,
                    "inputHeight": 640,
                    "queryCount": 300,
                    "classCount": 80,
                },
                "classBindings": [
                    {
                        "sourceClassId": 0,
                        "sourceClassName": "excavator",
                        "equipmentClass": "Excavator",
                        "measuredDimensions": {"lengthM": 9.0, "widthM": 3.0, "heightM": 4.0},
                    }
                ],
                "scoreThreshold": 0.5,
                "topK": 10,
                "ontologyVersion": "ksi-ontology-v1",
                "sourceTaxonomy": "COCO-2017",
                "tensorRtDifferential": {
                    "verificationProfileId": "ksi-dfine-tensorrt-onnx-semantic-v1",
                    "evidenceDigest": "sha256:" + "b" * 64,
                    "registeredOnnxDigest": "sha256:" + "a" * 64,
                    "preprocessingContractId": "rtdetr-rgb-bilinear-1over255-v1",
                    "preprocessingConfigDigest": "sha256:" + "c" * 64,
                    "corpusId": "dfine-onnx-corpus-v1",
                    "corpusDigest": "sha256:" + "d" * 64,
                    "sampleCount": 10,
                    "status": "PASS",
                    "confidenceAtol": 0.001,
                    "bboxAtolPx": 0.5,
                },
            },
            "calibration": {
                "calibrationProfileId": "cal-001",
                "siteFrame": {
                    "crs": "EPSG:5186",
                    "verticalDatum": "KNGeoid2018",
                    "unit": "meter",
                    "transformVersion": "1.0.0",
                },
                "wgs84Origin": {"latitudeRad": 0.5, "longitudeRad": 1.0, "altitudeM": 20.0},
                "enuToSite": {
                    "rotation": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                    "translationM": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
                "groundPlaneUpM": 0.0,
                "intrinsics": {
                    "referenceWidth": 1920,
                    "referenceHeight": 1080,
                    "focalXPx": 1000.0,
                    "focalYPx": 1000.0,
                    "principalXPx": 960.0,
                    "principalYPx": 540.0,
                },
                "cameraToGimbal": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
                "cameraOffsetInGimbalM": {"x": 0.0, "y": 0.0, "z": 0.0},
                "positionSigmaM": 1.0,
                "angularSigmaRad": 0.01,
                "pixelSigmaPx": 1.0,
                "maxPoseAgeMs": 500,
            },
            "timing": {"requireSensorAlignment": True, "maxAlignmentMs": 50},
        }
    )


def _client(
    tmp_path: Path, *, evidence_storage: _LegacyStorage | None = None
) -> tuple[TestClient, KeyRegistry, EventStore, EdgeDispatchStore]:
    now = datetime.now(UTC)
    mission_key = Ed25519PrivateKey.generate()
    dispatch_key = Ed25519PrivateKey.generate()
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    signed = sign_contract(_contract(now), mission_key, "mission-key")
    assert (
        mission_store.record_issuance(
            MissionRecord(
                mission_id="mission-edge-001",
                site_id="site-001",
                mission_type="UNIFIED_SITE_SURVEY",
                artifact_kind="contract",
                contract=signed,
                kmz_sha256=None,
                route_pattern=None,
                waypoint_count=None,
                planned_coverage_ratio=None,
                issued_at=now,
                issued_by="admin-principal",
                assigned_device_id=_EDGE_ID,
            )
        )
        is MissionRecordVerdict.RECORDED
    )
    event_store = EventStore(DurableJournal(tmp_path / "events.jsonl"))
    assert (
        event_store.project_bundle(_bundle(now), edge_device_id=_EDGE_ID, received_at=now)
        is EventVerdict.PROJECTED
    )
    dispatch_store = EdgeDispatchStore(
        DurableJournal(tmp_path / "edge-dispatch.jsonl"),
        mission_store=mission_store,
        risk_policy_packs=RiskPolicyPackRegistry([_pack(now)]),
        edge_runtime_profiles=EdgeRuntimeProfileRegistry([_profile(now)]),
        private_key=dispatch_key,
        key_id="dispatch-key",
    )
    app = create_app(
        auth_registry=_auth(),
        mission_store=mission_store,
        event_store=event_store,
        evidence_storage=evidence_storage if evidence_storage is not None else _Storage(),
        edge_dispatch_store=dispatch_store,
    )
    registry = KeyRegistry()
    registry.register("mission-key", mission_key.public_key())
    registry.register("dispatch-key", dispatch_key.public_key())
    return TestClient(app), registry, event_store, dispatch_store


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_edge_receives_only_its_signed_dispatch_and_activation_is_idempotent(
    tmp_path: Path,
) -> None:
    client, key_registry, _event_store, _dispatch_store = _client(tmp_path)
    first = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN))
    assert first.status_code == 200
    envelope = first.json()
    assert (
        verify_mission_dispatch_envelope(
            envelope, key_registry, expected_edge_device_id=_EDGE_ID, now=datetime.now(UTC)
        ).verdict
        is DispatchVerdict.VALID
    )
    second = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN))
    assert second.status_code == 200
    assert second.json()["dispatchId"] == envelope["dispatchId"]

    receipt = {
        "schemaVersion": "1.0",
        "dispatchId": envelope["dispatchId"],
        "edgeDeviceId": _EDGE_ID,
        "missionId": envelope["missionId"],
        "missionContractDigest": envelope["missionContractDigest"],
        "riskPolicyPackDigest": envelope["riskPolicyPackDigest"],
        "activatedAt": datetime.now(UTC).isoformat(),
        "runtimeVersion": "manifold-runtime-test",
    }
    path = f"/v1/edge-sync/missions/{envelope['dispatchId']}/activation-receipts"
    assert client.post(path, json=receipt, headers=_headers(_EDGE_TOKEN)).status_code == 201
    assert client.post(path, json=receipt, headers=_headers(_EDGE_TOKEN)).status_code == 200
    assert (
        client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN)).status_code == 204
    )


def test_future_dated_activation_receipt_is_rejected_without_consuming_dispatch(
    tmp_path: Path,
) -> None:
    client, _key_registry, _event_store, _dispatch_store = _client(tmp_path)
    mission = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN))
    assert mission.status_code == 200
    envelope = mission.json()
    path = f"/v1/edge-sync/missions/{envelope['dispatchId']}/activation-receipts"

    receipt = {
        "schemaVersion": "1.0",
        "dispatchId": envelope["dispatchId"],
        "edgeDeviceId": _EDGE_ID,
        "missionId": envelope["missionId"],
        "missionContractDigest": envelope["missionContractDigest"],
        "riskPolicyPackDigest": envelope["riskPolicyPackDigest"],
        "activatedAt": (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        "runtimeVersion": "manifold-runtime-test",
    }
    rejected = client.post(path, json=receipt, headers=_headers(_EDGE_TOKEN))
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "RECEIPT_MISMATCH"

    # A rejected clock claim must not consume the one pending dispatch.
    pending = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN))
    assert pending.status_code == 200
    assert pending.json()["dispatchId"] == envelope["dispatchId"]

    receipt["activatedAt"] = datetime.now(UTC).isoformat()
    assert client.post(path, json=receipt, headers=_headers(_EDGE_TOKEN)).status_code == 201


def test_replay_rejects_historical_future_dated_activation_receipt(tmp_path: Path) -> None:
    """A pre-hardening journal must not restore an impossible audit assertion."""
    client, _key_registry, _event_store, dispatch_store = _client(tmp_path)
    mission = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN))
    assert mission.status_code == 200
    envelope = mission.json()
    receipt = {
        "schemaVersion": "1.0",
        "dispatchId": envelope["dispatchId"],
        "edgeDeviceId": _EDGE_ID,
        "missionId": envelope["missionId"],
        "missionContractDigest": envelope["missionContractDigest"],
        "riskPolicyPackDigest": envelope["riskPolicyPackDigest"],
        "activatedAt": (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        "runtimeVersion": "manifold-runtime-test",
    }
    # Synthetic historical record: current admission rejects it, but an older
    # deployment could have durably written this claim before the hardening.
    dispatch_store._journal.append(  # noqa: SLF001 -- recovery boundary fixture
        {
            "kind": "dispatch-activated",
            "ts": datetime.now(UTC).isoformat(),
            "dispatchId": envelope["dispatchId"],
            "receipt": receipt,
        }
    )
    client.close()
    dispatch_store._journal.close()  # noqa: SLF001 -- release test writer lock

    with pytest.raises(EdgeDispatchRecoveryError, match="미래 activation receipt"):
        EdgeDispatchStore(
            DurableJournal(tmp_path / "edge-dispatch.jsonl"),
            mission_store=dispatch_store._mission_store,  # noqa: SLF001 -- immutable fixture deps
            risk_policy_packs=dispatch_store._risk_policy_packs,  # noqa: SLF001
            edge_runtime_profiles=dispatch_store._edge_runtime_profiles,  # noqa: SLF001
            private_key=dispatch_store._private_key,  # noqa: SLF001
            key_id=dispatch_store._key_id,  # noqa: SLF001
        )


def test_replay_rejects_activation_journal_timestamp_outside_dispatch_ttl(
    tmp_path: Path,
) -> None:
    """Receipt and Core journal time must both remain inside the dispatch TTL."""
    client, _key_registry, _event_store, dispatch_store = _client(tmp_path)
    mission = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN))
    assert mission.status_code == 200
    envelope = mission.json()
    receipt = {
        "schemaVersion": "1.0",
        "dispatchId": envelope["dispatchId"],
        "edgeDeviceId": _EDGE_ID,
        "missionId": envelope["missionId"],
        "missionContractDigest": envelope["missionContractDigest"],
        "riskPolicyPackDigest": envelope["riskPolicyPackDigest"],
        "activatedAt": datetime.now(UTC).isoformat(),
        "runtimeVersion": "manifold-runtime-test",
    }
    # A receipt can be timely while a forged or legacy journal acceptance time
    # lies beyond the five-minute dispatch TTL; neither record is restorable.
    dispatch_store._journal.append(  # noqa: SLF001 -- recovery boundary fixture
        {
            "kind": "dispatch-activated",
            "ts": (datetime.now(UTC) + timedelta(minutes=6)).isoformat(),
            "dispatchId": envelope["dispatchId"],
            "receipt": receipt,
        }
    )
    client.close()
    dispatch_store._journal.close()  # noqa: SLF001 -- release test writer lock

    with pytest.raises(EdgeDispatchRecoveryError, match="TTL 불일치"):
        EdgeDispatchStore(
            DurableJournal(tmp_path / "edge-dispatch.jsonl"),
            mission_store=dispatch_store._mission_store,  # noqa: SLF001 -- immutable fixture deps
            risk_policy_packs=dispatch_store._risk_policy_packs,  # noqa: SLF001
            edge_runtime_profiles=dispatch_store._edge_runtime_profiles,  # noqa: SLF001
            private_key=dispatch_store._private_key,  # noqa: SLF001
            key_id=dispatch_store._key_id,  # noqa: SLF001
        )


def test_cross_device_mission_and_evidence_are_hidden_and_operator_has_no_edge_permissions(
    tmp_path: Path,
) -> None:
    client, _registry, _event_store, _dispatch_store = _client(tmp_path)
    own = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN))
    assert own.status_code == 200
    dispatch_id = own.json()["dispatchId"]

    assert (
        client.get("/v1/edge-sync/missions/next", headers=_headers(_OTHER_EDGE_TOKEN)).status_code
        == 204
    )
    wrong_receipt = {
        "schemaVersion": "1.0",
        "dispatchId": dispatch_id,
        "edgeDeviceId": _OTHER_EDGE_ID,
        "missionId": "mission-edge-001",
        "missionContractDigest": own.json()["missionContractDigest"],
        "riskPolicyPackDigest": own.json()["riskPolicyPackDigest"],
        "activatedAt": datetime.now(UTC).isoformat(),
        "runtimeVersion": "test",
    }
    assert (
        client.post(
            f"/v1/edge-sync/missions/{dispatch_id}/activation-receipts",
            json=wrong_receipt,
            headers=_headers(_OTHER_EDGE_TOKEN),
        ).status_code
        == 404
    )
    assert (
        client.get("/v1/edge-sync/missions/next", headers=_headers(_ADMIN_TOKEN)).status_code == 403
    )

    event_key = make_event_key(_EDGE_ID, "evt-001")
    digest = "sha256:" + "c" * 64
    body = {
        "artifactId": "clip-001.mp4",
        "contentType": "video/mp4",
        "contentDigest": digest,
    }
    evidence_path = f"/v1/edge-sync/events/{event_key}/evidence"
    first = client.post(evidence_path, json=body, headers=_headers(_EDGE_TOKEN))
    assert first.status_code == 201
    assert first.json()["reusedRegistration"] is False
    assert first.json()["contentDigest"] == digest
    assert first.json()["requiredUploadHeaders"] == {
        "Content-Type": "video/mp4",
        "x-amz-checksum-sha256": base64.b64encode(bytes.fromhex("c" * 64)).decode("ascii"),
    }
    retry = client.post(evidence_path, json=body, headers=_headers(_EDGE_TOKEN))
    assert retry.status_code == 200
    assert retry.json()["reusedRegistration"] is True
    assert (
        client.post(
            evidence_path,
            json={**body, "contentDigest": "sha256:" + "d" * 64},
            headers=_headers(_EDGE_TOKEN),
        ).status_code
        == 409
    )
    assert (
        client.post(evidence_path, json=body, headers=_headers(_OTHER_EDGE_TOKEN)).status_code
        == 404
    )


def test_edge_evidence_requires_checksum_bound_storage_before_registration(tmp_path: Path) -> None:
    """Legacy presigned PUT alone cannot support an Edge digest claim."""
    client, _registry, event_store, _dispatch_store = _client(
        tmp_path, evidence_storage=_LegacyStorage()
    )
    event_key = make_event_key(_EDGE_ID, "evt-001")
    body = {
        "artifactId": "clip-001.mp4",
        "contentType": "video/mp4",
        "contentDigest": "sha256:" + "c" * 64,
    }
    path = f"/v1/edge-sync/events/{event_key}/evidence"
    assert client.post(path, json=body).status_code == 401
    response = client.post(path, json=body, headers=_headers(_EDGE_TOKEN))
    assert response.status_code == 503
    assert response.json()["detail"] == "EVIDENCE_DIGEST_BINDING_UNAVAILABLE"
    assert event_store.get_evidence(event_key, body["artifactId"]) is None
