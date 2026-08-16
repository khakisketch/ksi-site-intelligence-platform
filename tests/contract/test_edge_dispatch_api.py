"""Core Edge dispatch·activation receipt·장비 소유 evidence 계약 테스트."""

from __future__ import annotations

import base64
import hashlib
import json
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
from ksi_core.mission_execution import MissionExecutionStore
from ksi_core.mission_records import MissionRecord, MissionRecordVerdict, MissionStore
from ksi_core.sites import SiteStore
from ksi_domain.enums import MissionExecutionStatus, SiteStatus
from ksi_mission_contracts.dispatch import (
    DispatchValidity,
    DispatchVerdict,
    build_mission_dispatch_envelope,
    verify_mission_dispatch_envelope,
)
from ksi_mission_contracts.models import SiteFrame
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


def _client_with_site(
    tmp_path: Path,
    *,
    evidence_storage: _LegacyStorage | None = None,
    with_site: bool = True,
    kmz_sha256: str | None = None,
) -> tuple[
    TestClient, KeyRegistry, EventStore, EdgeDispatchStore, MissionExecutionStore, SiteStore | None
]:
    """``create_app`` 조립 그대로 — site_store 를 함께 넘겨 현장 전진 배선까지 켠다.

    ``kmz_sha256`` 을 주면 발급 레코드가 짝(pair) 산출물을 가진 것으로 기록된다
    (KMZ 를 가진 임무가 dispatch 발급 경로를 실제로 타는 시험 전용 — 기본은 기존
    계약 단독 발급과 동일하게 ``None``).
    """
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
                artifact_kind="pair" if kmz_sha256 is not None else "contract",
                contract=signed,
                kmz_sha256=kmz_sha256,
                route_pattern="perimeter" if kmz_sha256 is not None else None,
                waypoint_count=5 if kmz_sha256 is not None else None,
                planned_coverage_ratio=None,
                issued_at=now,
                issued_by="admin-principal",
                assigned_device_id=_EDGE_ID,
                plan_request=(
                    {"note": "test-fixture-plan-request"} if kmz_sha256 is not None else None
                ),
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
    execution_store = MissionExecutionStore(
        DurableJournal(tmp_path / "mission-execution.jsonl"), mission_store=mission_store
    )
    site_store = None
    if with_site:
        site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
        assert (
            site_store.register(
                "site-001",
                "테스트 현장",
                SiteFrame.model_validate(
                    {
                        "crs": "EPSG:5186",
                        "verticalDatum": "KNGeoid2018",
                        "unit": "meter",
                        "transformVersion": "1.0.0",
                    }
                ),
                actor="test-harness",
                now=now,
            ).verdict.value
            == "REGISTERED"
        )
    app = create_app(
        auth_registry=_auth(),
        mission_store=mission_store,
        event_store=event_store,
        evidence_storage=evidence_storage if evidence_storage is not None else _Storage(),
        edge_dispatch_store=dispatch_store,
        mission_execution_store=execution_store,
        site_store=site_store,
    )
    registry = KeyRegistry()
    registry.register("mission-key", mission_key.public_key())
    registry.register("dispatch-key", dispatch_key.public_key())
    return TestClient(app), registry, event_store, dispatch_store, execution_store, site_store


def _client(
    tmp_path: Path,
    *,
    evidence_storage: _LegacyStorage | None = None,
    kmz_sha256: str | None = None,
) -> tuple[TestClient, KeyRegistry, EventStore, EdgeDispatchStore, MissionExecutionStore]:
    """현장 원장 없이 조립 — 기존 dispatch 테스트들이 쓰는 좁은 형태."""
    client, registry, events, dispatch, execution, _site = _client_with_site(
        tmp_path, evidence_storage=evidence_storage, with_site=False, kmz_sha256=kmz_sha256
    )
    return client, registry, events, dispatch, execution


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_edge_receives_only_its_signed_dispatch_and_activation_is_idempotent(
    tmp_path: Path,
) -> None:
    client, key_registry, _event_store, _dispatch_store, _execution_store = _client(tmp_path)
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
    client, _key_registry, _event_store, _dispatch_store, _execution_store = _client(tmp_path)
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
    client, _key_registry, _event_store, dispatch_store, _execution_store = _client(tmp_path)
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
    client, _key_registry, _event_store, dispatch_store, _execution_store = _client(tmp_path)
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
    client, _registry, _event_store, _dispatch_store, _execution_store = _client(tmp_path)
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
    client, _registry, event_store, _dispatch_store, _execution_store = _client(
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


# ── 임무 실행 생애주기 결선 (ADR-KSI-019 G2) ──────────────────────────


def test_edge_pull_marks_the_mission_dispatched(tmp_path: Path) -> None:
    """[핵심] 장비가 envelope 을 가져가면 서버가 그 임무를 '배포됨'으로 안다.

    이게 없으면 임무 원장에 '발급했다'만 남고 '날았는지 모른다'가 영구히 남는다.
    """
    client, _registry, _events, _dispatch, execution = _client(tmp_path)
    assert execution.effective_status("mission-edge-001") is MissionExecutionStatus.ISSUED

    assert (
        client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN)).status_code
        == 200
    )

    assert execution.effective_status("mission-edge-001") is MissionExecutionStatus.DISPATCHED


def test_activation_receipt_marks_the_mission_activated(tmp_path: Path) -> None:
    client, _registry, _events, _dispatch, execution = _client(tmp_path)
    envelope = client.get(
        "/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN)
    ).json()
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

    assert (
        client.post(
            f"/v1/edge-sync/missions/{envelope['dispatchId']}/activation-receipts",
            json=receipt,
            headers=_headers(_EDGE_TOKEN),
        ).status_code
        == 201
    )

    assert execution.effective_status("mission-edge-001") is MissionExecutionStatus.ACTIVATED


def test_repeated_pull_does_not_pile_up_execution_records(tmp_path: Path) -> None:
    """중복 신호가 원장에 빈 레코드를 쌓지 않는다 — 자기 자신으로의 전이는 없다."""
    client, _registry, _events, _dispatch, execution = _client(tmp_path)

    client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN))
    client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN))

    assert len(execution.history("mission-edge-001")) == 1


def test_cancelled_mission_is_not_resurrected_by_a_device_pull(tmp_path: Path) -> None:
    """[핵심] 사람이 접은 임무를 장비 신호가 되살리지 않는다 — 그래도 pull 은 200 이다.

    전이표가 되살림을 막고, 그 거부가 장비의 임무 수신 응답을 바꾸지 않는다는 것이
    함께 중요하다 — 이 축은 게이트가 아니라 관측 기록이기 때문이다.
    """
    client, _registry, _events, _dispatch, execution = _client(tmp_path)
    execution.transition(
        "mission-edge-001",
        MissionExecutionStatus.CANCELLED,
        detail=None,
        actor="op-1",
        now=datetime.now(UTC),
    )

    response = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN))

    assert response.status_code == 200
    assert execution.effective_status("mission-edge-001") is MissionExecutionStatus.CANCELLED


def test_mapping_mission_pull_also_starts_the_site_mapping(tmp_path: Path) -> None:
    """[핵심] 매핑 계열 임무 배포가 현장을 BASELINE_MAPPING 으로 전진시킨다.

    이 fixture 의 임무 타입은 UNIFIED_SITE_SURVEY 로 매핑 계열이다
    (``MAPPING_FROM_SCRATCH_MISSION_TYPES``). **배포가 기준인 것이 요점이다** —
    발급만 하고 안 날린 임무가 현장 상태를 옮기면 계획 문서가 관측 사실을 참칭한다.

    ``create_app`` 을 그대로 쓴다 — 훅을 손으로 재현하면 실제 배선의 결함을 놓친다.
    """
    client, _registry, _events, _dispatch, execution, site_store = _client_with_site(tmp_path)
    assert site_store is not None
    before = site_store.get("site-001")
    assert before is not None
    assert before.status is SiteStatus.UNMAPPED

    assert (
        client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN)).status_code
        == 200
    )

    assert execution.effective_status("mission-edge-001") is MissionExecutionStatus.DISPATCHED
    record = site_store.get("site-001")
    assert record is not None
    assert record.status is SiteStatus.BASELINE_MAPPING


# ── ADR-KSI-007 짝 불변식의 발행 쪽 기계 검증 (HIGH — 발행 쪽에 시험 0건) ────


def test_edge_dispatch_envelope_carries_the_missions_kmz_sha256(tmp_path: Path) -> None:
    """[핵심] 발행 경로가 KMZ 를 가진 임무의 ``kmzSha256`` 을 실제로 실어 나른다.

    ``EdgeDispatchStore.next_for_device`` 의 ``kmz_sha256=mission.kmz_sha256`` 한 줄이
    "ADR-KSI-007 짝 불변식이 처음으로 기계 검증된다"는 트랙 전체 주장을 떠받치는데,
    그 줄을 ``kmz_sha256=None`` 으로 바꿔 전체 스위트를 돌려도 그대로 통과했다 —
    유일한 ``MissionRecord`` 픽스처가 ``kmz_sha256=None`` 이라 KMZ 를 가진 임무가
    발급 경로를 타는 시험이 하나도 없었기 때문이다. 이 시험은 그 결함을 직접 겨눈다.
    """
    kmz_digest = hashlib.sha256(b"golden-wayline-kmz-bytes").hexdigest()
    client, key_registry, _events, _dispatch, _execution = _client(tmp_path, kmz_sha256=kmz_digest)

    envelope = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN)).json()

    assert envelope["kmzSha256"] == kmz_digest
    assert (
        verify_mission_dispatch_envelope(
            envelope, key_registry, expected_edge_device_id=_EDGE_ID, now=datetime.now(UTC)
        ).verdict
        is DispatchVerdict.VALID
    )

    # 짝: KMZ 가 없는 계약 단독 발급은 그 사실이 null 로 그대로 실린다 — "아직
    # 모른다"가 아니라 "이 임무엔 KMZ 가 없다"는 확정 사실이어야 한다(모듈
    # docstring, MissionDispatchEnvelopeV1.kmz_sha256 필드 주석).
    no_kmz_client, *_rest = _client(tmp_path / "no-kmz")
    no_kmz_envelope = no_kmz_client.get(
        "/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN)
    ).json()
    assert no_kmz_envelope["kmzSha256"] is None


# ── v1.0 dispatch journal 재생 경로 (MEDIUM — 계획 이탈의 근거 시나리오 미검증) ──


def test_replayed_v1_0_dispatch_still_verifies_and_returns_byte_identical_envelope(
    tmp_path: Path,
) -> None:
    """[핵심] dispatch journal 에 남은 v1.0 레코드가 재생 뒤에도 그대로 나간다.

    검토자가 ``JSONResponse(content=result.envelope)`` → 모델 재검증·재직렬화 경로로,
    ``copy.deepcopy`` → ``model_dump`` 재직렬화로 두 이탈(dispatch.py/edge_dispatch.py
    모듈 docstring이 근거로 든 계획 이탈)을 동시에 원복했는데 tests/contract 2900건이
    전부 통과했다 — dispatch journal 에 남은 v1.0 레코드의 재생을 실제로 재현하는
    시험이 하나도 없었기 때문이다. journal 에 v1.0 형태 레코드를 직접 써 넣고 새
    ``EdgeDispatchStore`` 로 재생시켜 ①서명 검증이 여전히 통과하고 ②HTTP 응답
    바이트가 저장된 원문과 정확히 같은지(재직렬화가 optional 필드를 끼워 넣어 서명
    대상을 벗어나지 않는지) 확인한다.
    """
    now = datetime.now(UTC)
    mission_key = Ed25519PrivateKey.generate()
    dispatch_key = Ed25519PrivateKey.generate()
    signed_contract = sign_contract(_contract(now), mission_key, "mission-key")

    v1_1 = build_mission_dispatch_envelope(
        dispatch_id="dispatch-legacy-001",
        edge_device_id=_EDGE_ID,
        mission_contract=signed_contract,
        risk_policy_pack=_pack(now),
        edge_runtime_profile=_profile(now),
        validity=DispatchValidity(
            not_before=now - timedelta(seconds=1), not_after=now + timedelta(minutes=5)
        ),
        private_key=dispatch_key,
        key_id="dispatch-key",
    ).model_dump(by_alias=True, mode="json")
    # v1.0 은 "kmzSha256 자리가 아예 없는 봉투"로만 유효하다(dispatch.py 모듈
    # docstring) — 필드를 없애고 나머지 필드에 대해 다시 서명해야 실제 v1.0
    # 레코드(kmzSha256 도입 이전 발행분)를 재현한 것이 된다.
    unsigned_v1_0 = {
        field: value for field, value in v1_1.items() if field not in ("kmzSha256", "signature")
    }
    unsigned_v1_0["schemaVersion"] = "1.0"
    legacy_envelope = sign_contract(unsigned_v1_0, dispatch_key, "dispatch-key")

    dispatch_journal_path = tmp_path / "edge-dispatch.jsonl"
    seed = DurableJournal(dispatch_journal_path)
    seed.append({"kind": "dispatch-issued", "ts": now.isoformat(), "envelope": legacy_envelope})
    seed.close()

    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    dispatch_store = EdgeDispatchStore(
        DurableJournal(dispatch_journal_path),
        mission_store=mission_store,
        risk_policy_packs=RiskPolicyPackRegistry([_pack(now)]),
        edge_runtime_profiles=EdgeRuntimeProfileRegistry([_profile(now)]),
        private_key=dispatch_key,
        key_id="dispatch-key",
    )
    key_registry = KeyRegistry()
    key_registry.register("mission-key", mission_key.public_key())
    key_registry.register("dispatch-key", dispatch_key.public_key())
    app = create_app(
        auth_registry=_auth(), mission_store=mission_store, edge_dispatch_store=dispatch_store
    )
    client = TestClient(app)

    response = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN))

    assert response.status_code == 200
    # DurableJournal.append 과 Starlette JSONResponse 모두 key 순서를 바꾸지 않고
    # sort_keys 도 쓰지 않는다 — 그래서 원문 dict 를 그대로 다시 인코딩한 바이트열이
    # "재직렬화 없이 나간 원본"의 정확한 기준선이다.
    expected_bytes = json.dumps(
        legacy_envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    assert response.content == expected_bytes
    assert (
        verify_mission_dispatch_envelope(
            response.json(), key_registry, expected_edge_device_id=_EDGE_ID, now=now
        ).verdict
        is DispatchVerdict.VALID
    )


# ── flight-start-receipts (ADR-KSI-021 §9) ──────────────────────────────


def _flight_start_receipt(
    envelope: dict[str, Any],
    *,
    verdict: str = "STARTED",
    reported_at: datetime | None = None,
    action_return_code: str | None = "0",
    edge_device_id: str = _EDGE_ID,
    dispatch_id: str | None = None,
) -> dict[str, Any]:
    """activation-receipts 와 같은 binding 필드 + START 시도의 원인(``verdict``).

    ``verdict != STARTED`` 인 호출부는 ``action_return_code=None`` 을 명시로
    넘겨야 한다 — 호출에 도달하지 못한 시도는 반환값을 실을 수 없다(모델
    validator 가 강제하는 것과 같은 사실을 시험 fixture 에서도 지킨다).
    """
    receipt: dict[str, Any] = {
        "schemaVersion": "1.0",
        "dispatchId": dispatch_id if dispatch_id is not None else envelope["dispatchId"],
        "edgeDeviceId": edge_device_id,
        "missionId": envelope["missionId"],
        "missionContractDigest": envelope["missionContractDigest"],
        "riskPolicyPackDigest": envelope["riskPolicyPackDigest"],
        "reportedAt": (reported_at if reported_at is not None else datetime.now(UTC)).isoformat(),
        "runtimeVersion": "manifold-runtime-test",
        "verdict": verdict,
    }
    if action_return_code is not None:
        receipt["actionReturnCode"] = action_return_code
    return receipt


def _activate(client: TestClient, envelope: dict[str, Any]) -> None:
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
    assert (
        client.post(
            f"/v1/edge-sync/missions/{envelope['dispatchId']}/activation-receipts",
            json=receipt,
            headers=_headers(_EDGE_TOKEN),
        ).status_code
        == 201
    )


def test_flight_start_receipt_is_idempotent_and_does_not_move_execution_status(
    tmp_path: Path,
) -> None:
    """[핵심] 재수신은 200, 그리고 이 receipt 는 실행 상태를 어디로도 옮기지 않는다.

    ADR-KSI-021 §9: ``IN_FLIGHT`` 는 만들지 않는다 — 이 receipt 가 성공(``STARTED``)
    이어도 ``MissionExecutionStatus`` 는 activation-receipts 가 만든 ``ACTIVATED``
    에 그대로 머문다.
    """
    client, _registry, _events, dispatch_store, execution = _client(tmp_path)
    envelope = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN)).json()
    _activate(client, envelope)
    assert execution.effective_status("mission-edge-001") is MissionExecutionStatus.ACTIVATED

    path = f"/v1/edge-sync/missions/{envelope['dispatchId']}/flight-start-receipts"
    receipt = _flight_start_receipt(envelope)

    first = client.post(path, json=receipt, headers=_headers(_EDGE_TOKEN))
    assert first.status_code == 201
    assert first.json()["verdict"] == "FLIGHT_START_RECORDED"
    assert first.json()["outcome"] == "STARTED"

    second = client.post(path, json=receipt, headers=_headers(_EDGE_TOKEN))
    assert second.status_code == 200
    assert second.json()["verdict"] == "FLIGHT_START_ALREADY_RECORDED"
    assert second.json()["outcome"] == "STARTED"

    # 상태가 아니라 영수증이다 — 성공 보고도 실행 상태를 옮기지 않는다.
    assert execution.effective_status("mission-edge-001") is MissionExecutionStatus.ACTIVATED
    stored = dispatch_store.flight_start_receipt_of(envelope["dispatchId"])
    assert stored is not None
    assert stored["outcome"] == "STARTED"


def test_flight_start_receipt_without_prior_activation_is_refused_without_consuming_dispatch(
    tmp_path: Path,
) -> None:
    """activation 사실이 없는 기체가 무엇을 START 했다는 것인지 Core 는 설명할 수 없다."""
    client, _registry, _events, _dispatch_store, execution = _client(tmp_path)
    envelope = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN)).json()

    path = f"/v1/edge-sync/missions/{envelope['dispatchId']}/flight-start-receipts"
    rejected = client.post(
        path, json=_flight_start_receipt(envelope), headers=_headers(_EDGE_TOKEN)
    )

    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "NOT_ACTIVATED"
    assert execution.effective_status("mission-edge-001") is MissionExecutionStatus.DISPATCHED

    # 거부된 시도가 아직 미해결인 dispatch 를 소비하지 않는다.
    pending = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN))
    assert pending.status_code == 200
    assert pending.json()["dispatchId"] == envelope["dispatchId"]


def test_flight_start_refusal_is_stored_in_the_same_shape_as_success(tmp_path: Path) -> None:
    """[핵심] 거부(REFUSED_<verdict>)도 성공과 같은 저널 형식으로 남는다(§9).

    안 그러면 "아무도 시도 안 했다"와 "게이트가 막았다"가 구분되지 않는다 — ADR의
    바로 그 문구가 이 시험의 근거다.
    """
    client, _registry, _events, dispatch_store, _execution = _client(tmp_path)
    envelope = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN)).json()
    _activate(client, envelope)

    path = f"/v1/edge-sync/missions/{envelope['dispatchId']}/flight-start-receipts"
    refused_receipt = _flight_start_receipt(
        envelope, verdict="ARMING_TOKEN_INVALID", action_return_code=None
    )
    response = client.post(path, json=refused_receipt, headers=_headers(_EDGE_TOKEN))

    assert response.status_code == 201
    assert response.json()["verdict"] == "FLIGHT_START_RECORDED"
    assert response.json()["outcome"] == "REFUSED_ARMING_TOKEN_INVALID"

    stored = dispatch_store.flight_start_receipt_of(envelope["dispatchId"])
    assert stored is not None
    assert stored["outcome"] == "REFUSED_ARMING_TOKEN_INVALID"
    # 같은 형식: 성공 레코드와 동일한 키 집합(receipt·outcome)으로 저장된다.
    assert set(stored) == {"receipt", "outcome"}
    assert stored["receipt"]["verdict"] == "ARMING_TOKEN_INVALID"


def test_flight_start_receipt_forbids_action_return_code_before_a_started_call(
    tmp_path: Path,
) -> None:
    """Action(START) 호출에 도달하지 못한 거부는 그 호출의 반환값을 실을 수 없다."""
    client, _registry, _events, _dispatch_store, _execution = _client(tmp_path)
    envelope = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN)).json()
    _activate(client, envelope)

    path = f"/v1/edge-sync/missions/{envelope['dispatchId']}/flight-start-receipts"
    invalid_receipt = _flight_start_receipt(
        envelope, verdict="SUPERVISOR_NOT_READY", action_return_code="0"
    )

    response = client.post(path, json=invalid_receipt, headers=_headers(_EDGE_TOKEN))

    assert response.status_code == 422


def test_flight_start_receipt_rejects_conflicting_resubmission(tmp_path: Path) -> None:
    """재수신은 내용이 같을 때만 멱등이다 — 다른 내용의 재수신은 덮어쓰지 않고 거부한다."""
    client, _registry, _events, dispatch_store, _execution = _client(tmp_path)
    envelope = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN)).json()
    _activate(client, envelope)

    path = f"/v1/edge-sync/missions/{envelope['dispatchId']}/flight-start-receipts"
    first = _flight_start_receipt(envelope)
    assert client.post(path, json=first, headers=_headers(_EDGE_TOKEN)).status_code == 201

    conflicting = _flight_start_receipt(
        envelope, verdict="KMZ_DIGEST_MISMATCH", action_return_code=None
    )
    response = client.post(path, json=conflicting, headers=_headers(_EDGE_TOKEN))

    assert response.status_code == 422
    assert response.json()["detail"] == "RECEIPT_MISMATCH"
    # 원래 저장된(성공) 레코드가 그대로 남아 있다 — 충돌 재수신이 덮어쓰지 않는다.
    stored = dispatch_store.flight_start_receipt_of(envelope["dispatchId"])
    assert stored is not None
    assert stored["outcome"] == "STARTED"


def test_flight_start_receipt_is_hidden_across_devices_and_requires_edge_permission(
    tmp_path: Path,
) -> None:
    client, _registry, _events, _dispatch_store, _execution = _client(tmp_path)
    own = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN)).json()
    _activate(client, own)

    path = f"/v1/edge-sync/missions/{own['dispatchId']}/flight-start-receipts"
    wrong_device_receipt = _flight_start_receipt(own, edge_device_id=_OTHER_EDGE_ID)
    cross_device = client.post(
        path, json=wrong_device_receipt, headers=_headers(_OTHER_EDGE_TOKEN)
    )
    assert cross_device.status_code == 404

    operator_attempt = client.post(
        path, json=_flight_start_receipt(own), headers=_headers(_ADMIN_TOKEN)
    )
    assert operator_attempt.status_code == 403


def test_replay_rejects_flight_start_report_recorded_before_activation(tmp_path: Path) -> None:
    """§9 전제(activation 이 먼저 성립해야 한다)는 재생 경로에서도 다시 태운다."""
    client, _registry, _events, dispatch_store, _execution = _client(tmp_path)
    envelope = client.get("/v1/edge-sync/missions/next", headers=_headers(_EDGE_TOKEN)).json()
    # 의도적으로 activation-receipts 를 건너뛴다 — 손으로 고친(또는 손상된) 원장이
    # 이 순서를 되살릴 수 없어야 한다.
    receipt = _flight_start_receipt(envelope)
    dispatch_store._journal.append(  # noqa: SLF001 -- recovery boundary fixture
        {
            "kind": "dispatch-flight-start-reported",
            "ts": datetime.now(UTC).isoformat(),
            "dispatchId": envelope["dispatchId"],
            "outcome": "STARTED",
            "receipt": receipt,
        }
    )
    client.close()
    dispatch_store._journal.close()  # noqa: SLF001 -- release test writer lock

    with pytest.raises(EdgeDispatchRecoveryError, match="activation 이전의 flight-start 보고"):
        EdgeDispatchStore(
            DurableJournal(tmp_path / "edge-dispatch.jsonl"),
            mission_store=dispatch_store._mission_store,  # noqa: SLF001 -- immutable fixture deps
            risk_policy_packs=dispatch_store._risk_policy_packs,  # noqa: SLF001
            edge_runtime_profiles=dispatch_store._edge_runtime_profiles,  # noqa: SLF001
            private_key=dispatch_store._private_key,  # noqa: SLF001
            key_id=dispatch_store._key_id,  # noqa: SLF001
        )
