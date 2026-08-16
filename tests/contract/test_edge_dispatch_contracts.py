"""MissionDispatchEnvelope/RiskPolicyPack/RiskField v1.1 계약 반증.

Mission Contract v1.2의 기존 wire는 그대로 두고, 새 Edge 배포 경계가 장비 binding,
양쪽 digest, 키 상태, TTL을 하나라도 빠뜨리지 않는지를 확인한다.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import ssl
import threading
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID
from jsonschema import Draft202012Validator, RefResolver
from ksi_equipment_intelligence.risk_field import (
    RiskField,
    RiskFieldGeometry,
    RiskFieldLineage,
    RiskFieldValidity,
    RiskModel,
    risk_field_wire_dict,
)
from ksi_mission_contracts import edge_activation, edge_dispatch_sync
from ksi_mission_contracts.consumer import ContractInputError, MissionContractConsumer
from ksi_mission_contracts.dispatch import (
    DispatchValidity,
    DispatchVerdict,
    build_mission_dispatch_envelope,
    verify_mission_dispatch_envelope,
)
from ksi_mission_contracts.edge_activation import activate_mission_dispatch_file
from ksi_mission_contracts.edge_dispatch_sync import (
    CoreDispatchHttpResponse,
    CoreDispatchTransportError,
    EdgeDispatchSyncVerdict,
    PinnedHttpsEdgeDispatchTransport,
    PrivateBearerTokenVerdict,
    load_private_bearer_token_file,
    synchronize_edge_dispatch_once,
)
from ksi_mission_contracts.risk_policy import RiskPolicyPackV1, risk_policy_pack_wire_dict
from ksi_mission_contracts.runtime_profile import (
    EdgeRuntimeProfileV1,
    edge_runtime_profile_wire_dict,
)
from ksi_mission_contracts.signing import KeyRegistry, sign_contract

_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


def _unsigned_contract() -> dict[str, Any]:
    return {
        "schemaVersion": "1.2",
        "missionId": "mission-edge-001",
        "siteId": "site-001",
        "missionType": "UNIFIED_SITE_SURVEY",
        "validity": {"notBefore": "2026-08-14T00:00:00Z", "notAfter": "2026-08-15T00:00:00Z"},
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
        "objectives": ["evidence"],
        "policies": {
            "viewpointPolicyId": "vp-1",
            "riskPolicyPackId": "risk-pack-1",
            "fallbackPolicyId": "fb-1",
            "capturePolicyId": "capture-1",
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


def _pack() -> RiskPolicyPackV1:
    return RiskPolicyPackV1.model_validate(
        {
            "schemaVersion": "1.0",
            "riskPolicyPackId": "risk-pack-1",
            "validity": {"notBefore": "2026-08-14T00:00:00Z", "notAfter": "2026-08-15T00:00:00Z"},
            "calibrationProfileId": "cal-001",
            "equipmentPolicies": [
                {
                    "equipmentClass": "Excavator",
                    "riskFieldPolicyId": "excavator-v1",
                    "footprint": {"lengthM": 9.0, "widthM": 3.0, "heightM": 4.0},
                    "prediction": {"horizonSeconds": 5.0, "samplePeriodSeconds": 0.25},
                    "covarianceSigmaMultiplier": 3.0,
                    "occlusionExpansionM": 1.0,
                    "severity": 0.8,
                }
            ],
        }
    )


def _profile() -> EdgeRuntimeProfileV1:
    return EdgeRuntimeProfileV1.model_validate(
        {
            "schemaVersion": "1.0",
            "edgeRuntimeProfileId": "runtime-profile-001",
            "validity": {"notBefore": "2026-08-14T00:00:00Z", "notAfter": "2026-08-15T00:00:00Z"},
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


def _registry(mission_key: Ed25519PrivateKey, dispatch_key: Ed25519PrivateKey) -> KeyRegistry:
    registry = KeyRegistry()
    registry.register("mission-key", mission_key.public_key())
    registry.register("dispatch-key", dispatch_key.public_key())
    return registry


def _envelope() -> tuple[dict[str, Any], KeyRegistry, Ed25519PrivateKey]:
    mission_key = Ed25519PrivateKey.generate()
    dispatch_key = Ed25519PrivateKey.generate()
    signed_contract = sign_contract(_unsigned_contract(), mission_key, "mission-key")
    envelope = build_mission_dispatch_envelope(
        dispatch_id="dispatch-001",
        edge_device_id="edge-001",
        mission_contract=signed_contract,
        risk_policy_pack=_pack(),
        edge_runtime_profile=_profile(),
        validity=DispatchValidity(
            not_before=_NOW - timedelta(minutes=1), not_after=_NOW + timedelta(minutes=20)
        ),
        private_key=dispatch_key,
        key_id="dispatch-key",
    )
    return (
        envelope.model_dump(by_alias=True, mode="json"),
        _registry(mission_key, dispatch_key),
        dispatch_key,
    )


def _envelope_with_pack(
    pack: RiskPolicyPackV1,
    *,
    mission_key: Ed25519PrivateKey,
    dispatch_key: Ed25519PrivateKey,
    dispatch_id: str,
) -> dict[str, Any]:
    """Same shape as :func:`_envelope`, but with caller-chosen keys/pack.

    Reusing the same keys (and therefore the same :class:`KeyRegistry`) across
    two calls is what makes "activate envelope A, then try to activate an
    older-policy envelope B for the same mission" a same-device, same-trust
    scenario rather than a key-mismatch one.
    """
    signed_contract = sign_contract(_unsigned_contract(), mission_key, "mission-key")
    envelope = build_mission_dispatch_envelope(
        dispatch_id=dispatch_id,
        edge_device_id="edge-001",
        mission_contract=signed_contract,
        risk_policy_pack=pack,
        edge_runtime_profile=_profile(),
        validity=DispatchValidity(
            not_before=_NOW - timedelta(minutes=1), not_after=_NOW + timedelta(minutes=20)
        ),
        private_key=dispatch_key,
        key_id="dispatch-key",
    )
    return envelope.model_dump(by_alias=True, mode="json")


def _resign_outer(raw: dict[str, Any], signing_key: Ed25519PrivateKey) -> dict[str, Any]:
    unsigned = {field: value for field, value in raw.items() if field != "signature"}
    return sign_contract(unsigned, signing_key, "dispatch-key")


class _FakeDispatchTransport:
    """Exact Core routes in a deterministic activation-time transport fixture."""

    def __init__(
        self,
        pulls: list[CoreDispatchHttpResponse | CoreDispatchTransportError],
        receipts: list[CoreDispatchHttpResponse | CoreDispatchTransportError],
        kmz: list[CoreDispatchHttpResponse | CoreDispatchTransportError] | None = None,
    ) -> None:
        self._pulls = pulls
        self._receipts = receipts
        # 봉투가 kmzSha256 을 선언하지 않으면 companion 은 이 경로를 아예 타지
        # 않는다 — 기본 빈 목록이 그 사실을 시험이 되짚게 한다(호출되면 IndexError).
        self._kmz = kmz if kmz is not None else []
        self.paths: list[str] = []
        self.receipts: list[tuple[str, dict[str, Any]]] = []

    @staticmethod
    def _next(
        responses: list[CoreDispatchHttpResponse | CoreDispatchTransportError],
    ) -> CoreDispatchHttpResponse:
        response = responses.pop(0)
        if isinstance(response, CoreDispatchTransportError):
            raise response
        return response

    def pull_next(self) -> CoreDispatchHttpResponse:
        self.paths.append("GET /v1/edge-sync/missions/next")
        return self._next(self._pulls)

    def download_mission_kmz(self, mission_id: str) -> CoreDispatchHttpResponse:
        self.paths.append(f"GET /v1/missions/{mission_id}/kmz")
        return self._next(self._kmz)

    def record_activation(
        self, dispatch_id: str, receipt: Any
    ) -> CoreDispatchHttpResponse:
        self.paths.append(f"POST /v1/edge-sync/missions/{dispatch_id}/activation-receipts")
        self.receipts.append((dispatch_id, receipt.model_dump(by_alias=True, mode="json")))
        return self._next(self._receipts)


def _private_state_directory(tmp_path: Path) -> Path:
    state_directory = tmp_path / "activation-state"
    state_directory.mkdir(mode=0o700)
    state_directory.chmod(0o700)
    return state_directory


def _write_local_tls_material(tmp_path: Path) -> tuple[Path, Path, str]:
    """Write a short-lived loopback CA leaf and return its exact SPKI pin."""

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    issued_at = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(issued_at - timedelta(minutes=1))
        .not_valid_after(issued_at + timedelta(minutes=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    certificate_path = tmp_path / "local-core-ca.pem"
    key_path = tmp_path / "local-core-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    subject_public_key_info = certificate.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pin = "sha256//" + base64.b64encode(
        hashlib.sha256(subject_public_key_info).digest()
    ).decode("ascii")
    return certificate_path, key_path, pin


def test_new_contract_schemas_validate_wire() -> None:
    raw, _registry_, _key = _envelope()
    schemas = _ROOT / "contracts" / "schemas"
    store = {
        "https://ksi.example/schemas/mission-contract.v1.2.json": json.loads(
            (schemas / "mission-contract.v1.2.json").read_text(encoding="utf-8")
        ),
        "https://ksi.example/schemas/risk-policy-pack.v1.json": json.loads(
            (schemas / "risk-policy-pack.v1.json").read_text(encoding="utf-8")
        ),
        "https://ksi.example/schemas/edge-runtime-profile.v1.json": json.loads(
            (schemas / "edge-runtime-profile.v1.json").read_text(encoding="utf-8")
        ),
    }
    schema = json.loads(
        (schemas / "mission-dispatch-envelope.v1.1.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema, resolver=RefResolver.from_schema(schema, store=store))
    validator.validate(raw)
    Draft202012Validator(store["https://ksi.example/schemas/risk-policy-pack.v1.json"]).validate(
        risk_policy_pack_wire_dict(_pack())
    )
    Draft202012Validator(store["https://ksi.example/schemas/edge-runtime-profile.v1.json"]).validate(
        edge_runtime_profile_wire_dict(_profile())
    )


def test_valid_dispatch_binds_device_contract_policy_and_ttl() -> None:
    raw, registry, _key = _envelope()
    result = verify_mission_dispatch_envelope(
        raw, registry, expected_edge_device_id="edge-001", now=_NOW
    )
    assert result.verdict is DispatchVerdict.VALID
    assert result.envelope is not None


def test_dispatch_sync_pulls_verifies_activates_and_records_exact_receipt(tmp_path: Path) -> None:
    raw, registry, _key = _envelope()
    transport = _FakeDispatchTransport(
        [
            CoreDispatchHttpResponse(
                200,
                json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                "application/json; charset=utf-8",
            )
        ],
        [CoreDispatchHttpResponse(201)],
    )
    state_directory = _private_state_directory(tmp_path)

    result = synchronize_edge_dispatch_once(
        transport=transport,
        registry=registry,
        state_directory=state_directory,
        edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )

    assert result.verdict is EdgeDispatchSyncVerdict.ACTIVATED_AND_RECORDED
    assert result.dispatch_verdict is DispatchVerdict.VALID
    assert result.http_status == 201
    assert transport.paths == [
        "GET /v1/edge-sync/missions/next",
        "POST /v1/edge-sync/missions/dispatch-001/activation-receipts",
    ]
    assert transport.receipts == [
        (
            "dispatch-001",
            {
                "schemaVersion": "1.0",
                "dispatchId": "dispatch-001",
                "edgeDeviceId": "edge-001",
                "missionId": "mission-edge-001",
                "missionContractDigest": raw["missionContractDigest"],
                "riskPolicyPackDigest": raw["riskPolicyPackDigest"],
                "activatedAt": "2026-08-14T12:00:00Z",
                "runtimeVersion": "edge-runtime-0.1",
            },
        )
    ]
    assert (state_directory / "active-dispatch.native.v1").is_file()
    assert not list(state_directory.glob(".mission-dispatch-*.json"))


def test_dispatch_sync_real_tls_transport_round_trip(tmp_path: Path) -> None:
    """Exercise the real pinned HTTPS client against an actual TLS socket.

    The Core router's contract tests separately own route authorization and
    persistence.  This focused loopback server instead proves that the native
    activation companion can complete the exact pull/verify/receipt exchange
    through CA hostname verification, an SPKI pin, and fragmented HTTP reads
    without a monkeypatched transport.
    """

    raw, registry, _key = _envelope()
    dispatch_body = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    certificate_path, key_path, spki_pin = _write_local_tls_material(tmp_path)
    observed_requests: list[tuple[str, str, bytes, str | None]] = []

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return None

        def _respond(self, status: int, body: bytes = b"") -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
            observed_requests.append(
                (self.command, self.path, b"", self.headers.get("Authorization"))
            )
            self._respond(200, dispatch_body)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length)
            observed_requests.append(
                (self.command, self.path, body, self.headers.get("Authorization"))
            )
            self._respond(201)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls_context.load_cert_chain(certfile=str(certificate_path), keyfile=str(key_path))
    server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    token_file = tmp_path / "edge-bearer.token"
    token_file.write_text("edge-token\n", encoding="ascii")
    token_file.chmod(0o600)
    try:
        token = load_private_bearer_token_file(token_file)
        assert token.verdict is PrivateBearerTokenVerdict.LOADED
        assert token.bearer_token is not None
        transport = PinnedHttpsEdgeDispatchTransport(
            core_base_url=f"https://127.0.0.1:{server.server_address[1]}",
            ca_bundle=certificate_path,
            core_spki_pin=spki_pin,
            bearer_token=token.bearer_token,
        )
        result = synchronize_edge_dispatch_once(
            transport=transport,
            registry=registry,
            state_directory=_private_state_directory(tmp_path),
            edge_device_id="edge-001",
            runtime_version="edge-runtime-0.1",
            now=_NOW,
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    expected_receipt = {
        "schemaVersion": "1.0",
        "dispatchId": "dispatch-001",
        "edgeDeviceId": "edge-001",
        "missionId": "mission-edge-001",
        "missionContractDigest": raw["missionContractDigest"],
        "riskPolicyPackDigest": raw["riskPolicyPackDigest"],
        "activatedAt": "2026-08-14T12:00:00Z",
        "runtimeVersion": "edge-runtime-0.1",
    }
    assert result.verdict is EdgeDispatchSyncVerdict.ACTIVATED_AND_RECORDED
    assert result.dispatch_verdict is DispatchVerdict.VALID
    assert result.http_status == 201
    assert observed_requests == [
        ("GET", "/v1/edge-sync/missions/next", b"", "Bearer edge-token"),
        (
            "POST",
            "/v1/edge-sync/missions/dispatch-001/activation-receipts",
            json.dumps(expected_receipt, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            "Bearer edge-token",
        ),
    ]
    assert (tmp_path / "activation-state" / "active-dispatch.native.v1").is_file()
    assert not server_thread.is_alive()


def test_dispatch_sync_retains_activation_when_receipt_retry_is_needed(tmp_path: Path) -> None:
    raw, registry, _key = _envelope()
    body = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    transport = _FakeDispatchTransport(
        [
            CoreDispatchHttpResponse(200, body, "application/json"),
            CoreDispatchHttpResponse(200, body, "application/json"),
        ],
        [CoreDispatchHttpResponse(503), CoreDispatchHttpResponse(200)],
    )
    state_directory = _private_state_directory(tmp_path)

    first = synchronize_edge_dispatch_once(
        transport=transport,
        registry=registry,
        state_directory=state_directory,
        edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )
    retry = synchronize_edge_dispatch_once(
        transport=transport,
        registry=registry,
        state_directory=state_directory,
        edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )

    assert first.verdict is EdgeDispatchSyncVerdict.ACTIVATED_RECEIPT_PENDING
    assert not first.activation_reused
    assert retry.verdict is EdgeDispatchSyncVerdict.ACTIVATED_AND_RECORDED
    assert retry.activation_reused
    assert transport.receipts[0] == transport.receipts[1]
    assert (state_directory / "active-dispatch.native.v1").is_file()


def test_dispatch_sync_rejects_cross_device_or_non_json_pull_without_receipt(
    tmp_path: Path,
) -> None:
    raw, registry, dispatch_key = _envelope()
    raw["edgeDeviceId"] = "edge-other"
    cross_device_body = json.dumps(_resign_outer(raw, dispatch_key)).encode("utf-8")
    cross_device = _FakeDispatchTransport(
        [CoreDispatchHttpResponse(200, cross_device_body, "application/json")], []
    )

    rejected = synchronize_edge_dispatch_once(
        transport=cross_device,
        registry=registry,
        state_directory=_private_state_directory(tmp_path),
        edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )

    assert rejected.verdict is EdgeDispatchSyncVerdict.ACTIVATION_REJECTED
    assert cross_device.receipts == []

    no_json = _FakeDispatchTransport([CoreDispatchHttpResponse(200, b"{}", "text/plain")], [])
    next_tmp_path = tmp_path / "next"
    next_tmp_path.mkdir()
    non_json = synchronize_edge_dispatch_once(
        transport=no_json,
        registry=registry,
        state_directory=_private_state_directory(next_tmp_path),
        edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )
    assert non_json.verdict is EdgeDispatchSyncVerdict.PULL_REJECTED
    assert no_json.receipts == []


def test_dispatch_sync_no_mission_and_private_token_fail_closed(tmp_path: Path) -> None:
    no_mission = _FakeDispatchTransport([CoreDispatchHttpResponse(204)], [])
    raw, registry, _key = _envelope()
    del raw
    result = synchronize_edge_dispatch_once(
        transport=no_mission,
        registry=registry,
        state_directory=tmp_path / "not-required-for-empty-queue",
        edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )
    assert result.verdict is EdgeDispatchSyncVerdict.NO_MISSION
    assert no_mission.paths == ["GET /v1/edge-sync/missions/next"]

    token_file = tmp_path / "edge.token"
    token_file.write_text("token-_.~/+=\n", encoding="ascii")
    token_file.chmod(0o600)
    loaded = load_private_bearer_token_file(token_file)
    assert loaded.verdict is PrivateBearerTokenVerdict.LOADED
    assert loaded.bearer_token == "token-_.~/+="
    token_file.chmod(0o640)
    assert (
        load_private_bearer_token_file(token_file).verdict
        is PrivateBearerTokenVerdict.UNSAFE_FILE
    )

    with pytest.raises(ValueError, match="HTTPS origin"):
        PinnedHttpsEdgeDispatchTransport(
            core_base_url="http://core.example",
            ca_bundle=tmp_path / "unused.pem",
            core_spki_pin="sha256//" + "A" * 44,
            bearer_token="token",
        )
    with pytest.raises(ValueError, match="SPKI pin"):
        PinnedHttpsEdgeDispatchTransport(
            core_base_url="https://core.example",
            ca_bundle=tmp_path / "unused.pem",
            core_spki_pin="not-a-pin",
            bearer_token="token",
        )


def test_pinned_transport_validates_spki_before_sending_bearer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []

    class _Certificate:
        class _PublicKey:
            @staticmethod
            def public_bytes(*_args: object) -> bytes:
                return b"test-spki"

        @staticmethod
        def public_key() -> _Certificate._PublicKey:
            return _Certificate._PublicKey()

    class _Socket:
        @staticmethod
        def getpeercert(*, binary_form: bool) -> bytes:
            assert binary_form
            return b"test-certificate"

    class _Response:
        status = 200

        def __init__(self) -> None:
            self._remaining = b"{}"

        def read(self, maximum: int) -> bytes:
            chunk = self._remaining[:maximum]
            self._remaining = self._remaining[len(chunk) :]
            return chunk

        @staticmethod
        def getheader(name: str, default: str) -> str:
            assert name == "Content-Type"
            return default

    class _Connection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.sock: _Socket | None = None

        def connect(self) -> None:
            calls.append("connect")
            self.sock = _Socket()

        @staticmethod
        def getresponse() -> _Response:
            return _Response()

        @staticmethod
        def close() -> None:
            calls.append("close")

        @staticmethod
        def request(
            method: str, route: str, *, body: bytes | None, headers: dict[str, str]
        ) -> None:
            calls.append((method, route, body, headers))

    monkeypatch.setattr(
        edge_dispatch_sync.ssl, "create_default_context", lambda **_kwargs: object()
    )
    monkeypatch.setattr(
        edge_dispatch_sync.x509, "load_der_x509_certificate", lambda _raw: _Certificate()
    )
    monkeypatch.setattr(edge_dispatch_sync.http.client, "HTTPSConnection", _Connection)
    pin = "sha256//" + base64.b64encode(hashlib.sha256(b"test-spki").digest()).decode("ascii")
    transport = PinnedHttpsEdgeDispatchTransport(
        core_base_url="https://core.example",
        ca_bundle=tmp_path / "unused.pem",
        core_spki_pin=pin,
        bearer_token="edge-token",
    )

    response = transport.pull_next()

    assert response == CoreDispatchHttpResponse(200, b"{}")
    assert calls[0] == "connect"
    assert calls[1] == (
        "GET",
        "/v1/edge-sync/missions/next",
        None,
        {
            "Accept": "application/json",
            "Authorization": "Bearer edge-token",
            "Host": "core.example",
        },
    )
    assert calls[2] == "close"

    calls.clear()
    wrong_pin = "sha256//" + base64.b64encode(b"x" * 32).decode("ascii")
    rejected = PinnedHttpsEdgeDispatchTransport(
        core_base_url="https://core.example",
        ca_bundle=tmp_path / "unused.pem",
        core_spki_pin=wrong_pin,
        bearer_token="edge-token",
    )
    with pytest.raises(CoreDispatchTransportError) as raised:
        rejected.pull_next()
    assert not raised.value.retryable
    assert calls == ["connect", "close"]


def test_pinned_transport_rejects_fragmented_response_above_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A short HTTP read must not let the response-size cap be bypassed."""

    class _Certificate:
        class _PublicKey:
            @staticmethod
            def public_bytes(*_args: object) -> bytes:
                return b"test-spki"

        @staticmethod
        def public_key() -> _Certificate._PublicKey:
            return _Certificate._PublicKey()

    class _Socket:
        @staticmethod
        def getpeercert(*, binary_form: bool) -> bytes:
            assert binary_form
            return b"test-certificate"

    class _Response:
        status = 200

        def __init__(self) -> None:
            self._remaining = b"1234"

        def read(self, _maximum: int) -> bytes:
            chunk = self._remaining[:1]
            self._remaining = self._remaining[1:]
            return chunk

        @staticmethod
        def getheader(_name: str, default: str) -> str:
            return default

    class _Connection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.sock: _Socket | None = None

        def connect(self) -> None:
            self.sock = _Socket()

        @staticmethod
        def getresponse() -> _Response:
            return _Response()

        @staticmethod
        def close() -> None:
            return None

        @staticmethod
        def request(
            _method: str, _route: str, *, body: bytes | None, headers: dict[str, str]
        ) -> None:
            assert body is None
            assert headers["Authorization"] == "Bearer edge-token"

    monkeypatch.setattr(
        edge_dispatch_sync.ssl, "create_default_context", lambda **_kwargs: object()
    )
    monkeypatch.setattr(
        edge_dispatch_sync.x509, "load_der_x509_certificate", lambda _raw: _Certificate()
    )
    monkeypatch.setattr(edge_dispatch_sync.http.client, "HTTPSConnection", _Connection)
    pin = "sha256//" + base64.b64encode(hashlib.sha256(b"test-spki").digest()).decode("ascii")
    transport = PinnedHttpsEdgeDispatchTransport(
        core_base_url="https://core.example",
        ca_bundle=tmp_path / "unused.pem",
        core_spki_pin=pin,
        bearer_token="edge-token",
    )

    with pytest.raises(CoreDispatchTransportError) as raised:
        transport._request(
            method="GET",
            route="/v1/edge-sync/missions/next",
            body=None,
            maximum_response_bytes=3,
        )
    assert not raised.value.retryable


def test_pinned_transport_download_mission_kmz_issues_exact_route_method_and_accept_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[MEDIUM] ``download_mission_kmz`` 의 실제 HTTP 호출부를 실측 대조한다.

    새 sync 시험은 전부 ``_FakeDispatchTransport`` 를 지나는데, 그 대역은 라우트
    문자열 ``f"GET /v1/missions/{mission_id}/kmz"`` 를 **자기가 다시 만들어** 기록하고
    시험은 그 기록을 대조할 뿐이었다 — 실제 라우트를 오타로 바꾸거나 mission_id
    가드를 통째로 지워도 대역을 지나는 시험은 전부 통과했다. ``pull_next`` 를 실측
    대조하는 위 시험(``test_pinned_transport_validates_spki_before_sending_bearer``)과
    같은 관습을 ``download_mission_kmz`` 에도 편다 — 진짜 HTTP 클라이언트
    (``http.client.HTTPSConnection``)를 지나는 GET method·정확한 경로 문자열·
    Accept 헤더를 대조한다.
    """
    calls: list[object] = []
    kmz_body = b"PK\x03\x04kmz-golden-bytes"

    class _Certificate:
        class _PublicKey:
            @staticmethod
            def public_bytes(*_args: object) -> bytes:
                return b"test-spki"

        @staticmethod
        def public_key() -> _Certificate._PublicKey:
            return _Certificate._PublicKey()

    class _Socket:
        @staticmethod
        def getpeercert(*, binary_form: bool) -> bytes:
            assert binary_form
            return b"test-certificate"

    class _Response:
        status = 200

        def __init__(self) -> None:
            self._remaining = kmz_body

        def read(self, maximum: int) -> bytes:
            chunk = self._remaining[:maximum]
            self._remaining = self._remaining[len(chunk) :]
            return chunk

        @staticmethod
        def getheader(name: str, default: str) -> str:
            assert name == "Content-Type"
            return "application/vnd.google-earth.kmz"

    class _Connection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.sock: _Socket | None = None

        def connect(self) -> None:
            calls.append("connect")
            self.sock = _Socket()

        @staticmethod
        def getresponse() -> _Response:
            return _Response()

        @staticmethod
        def close() -> None:
            calls.append("close")

        @staticmethod
        def request(
            method: str, route: str, *, body: bytes | None, headers: dict[str, str]
        ) -> None:
            calls.append((method, route, body, headers))

    monkeypatch.setattr(
        edge_dispatch_sync.ssl, "create_default_context", lambda **_kwargs: object()
    )
    monkeypatch.setattr(
        edge_dispatch_sync.x509, "load_der_x509_certificate", lambda _raw: _Certificate()
    )
    monkeypatch.setattr(edge_dispatch_sync.http.client, "HTTPSConnection", _Connection)
    pin = "sha256//" + base64.b64encode(hashlib.sha256(b"test-spki").digest()).decode("ascii")
    transport = PinnedHttpsEdgeDispatchTransport(
        core_base_url="https://core.example",
        ca_bundle=tmp_path / "unused.pem",
        core_spki_pin=pin,
        bearer_token="edge-token",
    )

    response = transport.download_mission_kmz("mission-edge-001")

    assert response == CoreDispatchHttpResponse(
        200, kmz_body, "application/vnd.google-earth.kmz"
    )
    assert calls[0] == "connect"
    assert calls[1] == (
        "GET",
        "/v1/missions/mission-edge-001/kmz",
        None,
        {
            "Accept": "application/vnd.google-earth.kmz",
            "Authorization": "Bearer edge-token",
            "Host": "core.example",
        },
    )
    assert calls[2] == "close"

    # mission_id 는 경로-안전 문자 집합 밖으로 나가면 아예 요청을 만들지 않는다 —
    # 그 가드가 지워지면 검증되지 않은 문자열이 그대로 경로에 꽂힌다.
    calls.clear()
    with pytest.raises(CoreDispatchTransportError) as raised:
        transport.download_mission_kmz("../etc/passwd")
    assert not raised.value.retryable
    assert calls == []


def test_pinned_transport_download_mission_kmz_enforces_8mib_response_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """8MiB 를 넘는 KMZ 응답은 조각난 TCP 배달로도 상한을 빠져나가지 못한다."""

    class _Certificate:
        class _PublicKey:
            @staticmethod
            def public_bytes(*_args: object) -> bytes:
                return b"test-spki"

        @staticmethod
        def public_key() -> _Certificate._PublicKey:
            return _Certificate._PublicKey()

    class _Socket:
        @staticmethod
        def getpeercert(*, binary_form: bool) -> bytes:
            assert binary_form
            return b"test-certificate"

    oversized = b"k" * (edge_activation._MAX_MISSION_KMZ_BYTES + 1)

    class _Response:
        status = 200

        def __init__(self) -> None:
            self._remaining = oversized

        def read(self, maximum: int) -> bytes:
            chunk = self._remaining[:maximum]
            self._remaining = self._remaining[len(chunk) :]
            return chunk

        @staticmethod
        def getheader(_name: str, default: str) -> str:
            return "application/vnd.google-earth.kmz"

    class _Connection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.sock: _Socket | None = None

        def connect(self) -> None:
            self.sock = _Socket()

        @staticmethod
        def getresponse() -> _Response:
            return _Response()

        @staticmethod
        def close() -> None:
            return None

        @staticmethod
        def request(
            _method: str, _route: str, *, body: bytes | None, headers: dict[str, str]
        ) -> None:
            assert body is None
            assert headers["Accept"] == "application/vnd.google-earth.kmz"

    monkeypatch.setattr(
        edge_dispatch_sync.ssl, "create_default_context", lambda **_kwargs: object()
    )
    monkeypatch.setattr(
        edge_dispatch_sync.x509, "load_der_x509_certificate", lambda _raw: _Certificate()
    )
    monkeypatch.setattr(edge_dispatch_sync.http.client, "HTTPSConnection", _Connection)
    pin = "sha256//" + base64.b64encode(hashlib.sha256(b"test-spki").digest()).decode("ascii")
    transport = PinnedHttpsEdgeDispatchTransport(
        core_base_url="https://core.example",
        ca_bundle=tmp_path / "unused.pem",
        core_spki_pin=pin,
        bearer_token="edge-token",
    )

    with pytest.raises(CoreDispatchTransportError) as raised:
        transport.download_mission_kmz("mission-edge-001")
    assert not raised.value.retryable


def test_dispatch_sync_rejects_oversize_pull_and_unavailable_state_directory(
    tmp_path: Path,
) -> None:
    raw, registry, _key = _envelope()
    oversize = _FakeDispatchTransport(
        [CoreDispatchHttpResponse(200, b"{" + b" " * (1024 * 1024), "application/json")], []
    )
    too_large = synchronize_edge_dispatch_once(
        transport=oversize,
        registry=registry,
        state_directory=tmp_path / "not-used-for-oversize",
        edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )
    assert too_large.verdict is EdgeDispatchSyncVerdict.PULL_REJECTED
    assert oversize.receipts == []

    body = json.dumps(raw).encode("utf-8")
    unavailable_state = _FakeDispatchTransport(
        [CoreDispatchHttpResponse(200, body, "application/json")], []
    )
    unavailable = synchronize_edge_dispatch_once(
        transport=unavailable_state,
        registry=registry,
        state_directory=tmp_path / "missing-state-directory",
        edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )
    assert unavailable.verdict is EdgeDispatchSyncVerdict.ACTIVATION_REJECTED
    assert unavailable_state.receipts == []


def test_runtime_profile_rejects_reflection_or_scale_in_site_transform() -> None:
    raw = edge_runtime_profile_wire_dict(_profile())
    raw["calibration"]["enuToSite"]["rotation"][0][0] = -1.0
    with pytest.raises(ValueError, match="proper rotation"):
        EdgeRuntimeProfileV1.model_validate(raw)

    raw = edge_runtime_profile_wire_dict(_profile())
    raw["calibration"]["enuToSite"]["rotation"][1][1] = 2.0
    with pytest.raises(ValueError, match="unit length"):
        EdgeRuntimeProfileV1.model_validate(raw)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda model: model.pop("tensorRtDifferential"),
            "tensorRtDifferential",
        ),
        (
            lambda model: model["tensorRtDifferential"].__setitem__(
                "registeredOnnxDigest", "sha256:" + "e" * 64
            ),
            "must equal",
        ),
        (
            lambda model: model["tensorRtDifferential"].__setitem__("status", "FAIL"),
            "status",
        ),
        (
            lambda model: model["tensorRtDifferential"].__setitem__(
                "confidenceAtol", 0.0011
            ),
            "confidenceAtol",
        ),
    ],
)
def test_runtime_profile_requires_bound_tensorrt_differential_attestation(
    mutator: Any, message: str
) -> None:
    raw = edge_runtime_profile_wire_dict(_profile())
    model = raw["model"]
    assert isinstance(model, dict)
    mutator(model)
    with pytest.raises(ValueError, match=message):
        EdgeRuntimeProfileV1.model_validate(raw)


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (
            lambda payload: payload.__setitem__("missionContractDigest", "sha256:" + "0" * 64),
            DispatchVerdict.MISSION_CONTRACT_DIGEST_MISMATCH,
        ),
        (
            lambda payload: payload.__setitem__("riskPolicyPackDigest", "sha256:" + "0" * 64),
            DispatchVerdict.RISK_POLICY_PACK_DIGEST_MISMATCH,
        ),
        (
            lambda payload: payload.__setitem__(
                "edgeRuntimeProfileDigest", "sha256:" + "0" * 64
            ),
            DispatchVerdict.EDGE_RUNTIME_PROFILE_DIGEST_MISMATCH,
        ),
    ],
)
def test_digest_mismatch_is_fail_closed_after_valid_outer_resign(
    mutator: Any, expected: DispatchVerdict
) -> None:
    raw, registry, dispatch_key = _envelope()
    mutator(raw)
    result = verify_mission_dispatch_envelope(_resign_outer(raw, dispatch_key), registry, now=_NOW)
    assert result.verdict is expected


def test_cross_device_dispatch_is_rejected() -> None:
    raw, registry, _key = _envelope()
    result = verify_mission_dispatch_envelope(
        raw, registry, expected_edge_device_id="edge-other", now=_NOW
    )
    assert result.verdict is DispatchVerdict.DEVICE_MISMATCH


def test_dispatch_activation_uses_upstream_consumer_and_preserves_exact_retry_receipt(
    tmp_path: Path,
) -> None:
    raw, registry, _key = _envelope()
    dispatch_path = tmp_path / "dispatch.json"
    dispatch_path.write_text(json.dumps(raw), encoding="utf-8")
    consumer = MissionContractConsumer(registry=registry, state_dir=tmp_path / "state")

    first = activate_mission_dispatch_file(
        dispatch_path,
        consumer=consumer,
        registry=registry,
        expected_edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )

    assert first.dispatch_verdict is DispatchVerdict.VALID
    assert first.activated and not first.reused_activation
    assert first.activation_receipt is not None
    assert consumer.load_active(now=_NOW).is_valid
    assert first.active_snapshot_path is not None and first.active_snapshot_path.is_file()
    native_snapshot = consumer.active_path.parent / "active-dispatch.native.v1"
    native_profile = consumer.active_path.parent / "active-edge-runtime-profile.native.v1"
    assert native_snapshot.is_file()
    assert native_profile.is_file()
    native_lines = native_snapshot.read_text(encoding="ascii").splitlines()
    assert native_lines[0] == "KSI_EDGE_NATIVE_ACTIVATION_V1"
    native_fields = dict(line.split("=", 1) for line in native_lines[1:])
    assert native_fields["activated_at_utc_ms"] == "1786708800000"
    assert native_fields["dispatch_id_b64"] == "ZGlzcGF0Y2gtMDAx"
    assert native_fields["edge_device_id_b64"] == "ZWRnZS0wMDE"
    assert (
        native_fields["mission_contract_digest"]
        == first.activation_receipt.mission_contract_digest
    )
    assert native_fields["mission_id_b64"] == "bWlzc2lvbi1lZGdlLTAwMQ"
    assert (
        native_fields["risk_policy_pack_digest"]
        == first.activation_receipt.risk_policy_pack_digest
    )
    assert native_fields["risk_policy_pack_id_b64"] == "cmlzay1wYWNrLTE"
    assert native_fields["risk_policy_calibration_profile_id_b64"] == "Y2FsLTAwMQ"
    assert native_fields["risk_policy_count"] == "1"
    assert native_fields["risk_policy_0_equipment_class_b64"] == "RXhjYXZhdG9y"
    assert native_fields["risk_policy_0_risk_field_policy_id_b64"] == "ZXhjYXZhdG9yLXYx"
    assert native_fields["risk_policy_0_footprint_length_bits"] == "4022000000000000"
    assert native_fields["risk_policy_0_prediction_horizon_bits"] == "4014000000000000"
    assert native_fields["risk_policy_0_severity_bits"] == "3fe999999999999a"
    assert native_fields["runtime_version_b64"] == "ZWRnZS1ydW50aW1lLTAuMQ"
    assert native_fields["valid_from_utc_ms"] == "1786708740000"
    assert native_fields["valid_until_utc_ms"] == "1786710000000"
    native_profile_fields = dict(
        line.split("=", 1)
        for line in native_profile.read_text(encoding="ascii").splitlines()[1:]
    )
    assert first.active_snapshot_path is not None
    active_snapshot_wire = json.loads(first.active_snapshot_path.read_text(encoding="utf-8"))
    assert native_profile_fields["edge_runtime_profile_digest"] == active_snapshot_wire[
        "edgeRuntimeProfileDigest"
    ]
    assert native_profile_fields["calibration_enu_to_site_r00_bits"] == "3ff0000000000000"
    assert native_profile_fields["calibration_enu_to_site_r12_bits"] == "0000000000000000"
    assert (
        native_profile_fields["model_tensorrt_differential_status"] == "PASS"
    )
    assert (
        native_profile_fields[
            "model_tensorrt_differential_registered_onnx_digest"
        ] == "sha256:" + "a" * 64
    )

    retry = activate_mission_dispatch_file(
        dispatch_path,
        consumer=consumer,
        registry=registry,
        expected_edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )
    assert retry.activated and retry.reused_activation
    assert retry.activation_receipt == first.activation_receipt


# ── RiskPolicyPack/EdgeRuntimeProfile rollback defense ──────────────────────
# risk riskpolicypack-edgeruntimeprofile-no-rollback-defense (2026-08-14) — the
# same threat 09fe5a7 closed for the inner Mission Contract
# (ActivationRefusal.SUPERSEDED_CONTRACT), on the two axes only the outer
# dispatch envelope carries.


def _older_pack(*, not_before: str, risk_policy_pack_id: str = "risk-pack-1") -> RiskPolicyPackV1:
    return RiskPolicyPackV1.model_validate(
        {
            "schemaVersion": "1.0",
            "riskPolicyPackId": risk_policy_pack_id,
            "validity": {"notBefore": not_before, "notAfter": "2026-08-15T00:00:00Z"},
            "calibrationProfileId": "cal-001",
            "equipmentPolicies": [
                {
                    "equipmentClass": "Excavator",
                    "riskFieldPolicyId": "excavator-v1",
                    "footprint": {"lengthM": 9.0, "widthM": 3.0, "heightM": 4.0},
                    # 예비량/문턱류를 흉내 낸 값 — 실제 반증 사례(mission-contract
                    # rollback, 예비량 40%→10%)와 같은 계열의 "약해진 정책"을 상징한다.
                    "prediction": {"horizonSeconds": 1.0, "samplePeriodSeconds": 0.25},
                    "covarianceSigmaMultiplier": 1.0,
                    "occlusionExpansionM": 0.1,
                    "severity": 0.2,
                }
            ],
        }
    )


def test_older_risk_policy_pack_is_rejected_as_rollback(tmp_path: Path) -> None:
    """이미 활성인 RiskPolicyPack보다 이른 후보는 서명이 유효해도 거부된다."""
    mission_key = Ed25519PrivateKey.generate()
    dispatch_key = Ed25519PrivateKey.generate()
    registry = _registry(mission_key, dispatch_key)
    consumer = MissionContractConsumer(registry=registry, state_dir=tmp_path / "state")

    current = _envelope_with_pack(
        _older_pack(not_before="2026-08-14T00:00:00Z"),
        mission_key=mission_key,
        dispatch_key=dispatch_key,
        dispatch_id="dispatch-current",
    )
    current_path = tmp_path / "current.json"
    current_path.write_text(json.dumps(current), encoding="utf-8")
    first = activate_mission_dispatch_file(
        current_path,
        consumer=consumer,
        registry=registry,
        expected_edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )
    assert first.dispatch_verdict is DispatchVerdict.VALID and first.activated

    # 서명은 진짜고 TTL도 안 지났다 — 단지 이전에 발급된, 더 이른 정책이다.
    older = _envelope_with_pack(
        _older_pack(not_before="2026-08-13T00:00:00Z"),
        mission_key=mission_key,
        dispatch_key=dispatch_key,
        dispatch_id="dispatch-rollback",
    )
    older_path = tmp_path / "older.json"
    older_path.write_text(json.dumps(older), encoding="utf-8")
    rollback_attempt = activate_mission_dispatch_file(
        older_path,
        consumer=consumer,
        registry=registry,
        expected_edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )

    assert rollback_attempt.dispatch_verdict is DispatchVerdict.SUPERSEDED_RISK_POLICY_PACK
    assert not rollback_attempt.activated
    # 거부됐으니 활성 스냅샷은 여전히 첫 번째(강한 정책) 것이다.
    assert first.active_snapshot_path is not None
    still_active = json.loads(first.active_snapshot_path.read_text(encoding="utf-8"))
    assert still_active["riskPolicyPackDigest"] == json.loads(current_path.read_text())[
        "riskPolicyPackDigest"
    ]


def test_older_edge_runtime_profile_is_rejected_as_rollback(tmp_path: Path) -> None:
    """이미 활성인 EdgeRuntimeProfile보다 이른 후보도 같은 이유로 거부된다."""
    mission_key = Ed25519PrivateKey.generate()
    dispatch_key = Ed25519PrivateKey.generate()
    registry = _registry(mission_key, dispatch_key)
    consumer = MissionContractConsumer(registry=registry, state_dir=tmp_path / "state")

    def _profile_with(not_before: str) -> EdgeRuntimeProfileV1:
        raw = _profile().model_dump(by_alias=True, mode="json")
        raw["validity"]["notBefore"] = not_before
        return EdgeRuntimeProfileV1.model_validate(raw)

    def _envelope_with_profile(
        profile: EdgeRuntimeProfileV1, *, dispatch_id: str
    ) -> dict[str, Any]:
        signed_contract = sign_contract(_unsigned_contract(), mission_key, "mission-key")
        envelope = build_mission_dispatch_envelope(
            dispatch_id=dispatch_id,
            edge_device_id="edge-001",
            mission_contract=signed_contract,
            risk_policy_pack=_pack(),
            edge_runtime_profile=profile,
            validity=DispatchValidity(
                not_before=_NOW - timedelta(minutes=1), not_after=_NOW + timedelta(minutes=20)
            ),
            private_key=dispatch_key,
            key_id="dispatch-key",
        )
        return envelope.model_dump(by_alias=True, mode="json")

    current_path = tmp_path / "current.json"
    current_path.write_text(
        json.dumps(
            _envelope_with_profile(
                _profile_with("2026-08-14T00:00:00Z"), dispatch_id="dispatch-current"
            )
        ),
        encoding="utf-8",
    )
    first = activate_mission_dispatch_file(
        current_path,
        consumer=consumer,
        registry=registry,
        expected_edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )
    assert first.dispatch_verdict is DispatchVerdict.VALID and first.activated

    older_path = tmp_path / "older.json"
    older_path.write_text(
        json.dumps(
            _envelope_with_profile(
                _profile_with("2026-08-13T00:00:00Z"), dispatch_id="dispatch-rollback"
            )
        ),
        encoding="utf-8",
    )
    rollback_attempt = activate_mission_dispatch_file(
        older_path,
        consumer=consumer,
        registry=registry,
        expected_edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )

    assert rollback_attempt.dispatch_verdict is DispatchVerdict.SUPERSEDED_EDGE_RUNTIME_PROFILE
    assert not rollback_attempt.activated


def test_reactivating_the_unchanged_risk_policy_pack_is_not_a_rollback(tmp_path: Path) -> None:
    """digest가 같은(내용이 안 바뀐) pack 재전송은 rollback 판정에 걸리지 않는다.

    ``notBefore`` 단조성 검사가 ``digest`` 변경분에만 적용되는지 고정한다 —
    안 걸면 정상적인 재활성화(같은 mission, 새 dispatch_id, 동일 pack)까지
    막힌다.
    """
    mission_key = Ed25519PrivateKey.generate()
    dispatch_key = Ed25519PrivateKey.generate()
    registry = _registry(mission_key, dispatch_key)
    consumer = MissionContractConsumer(registry=registry, state_dir=tmp_path / "state")
    pack = _older_pack(not_before="2026-08-14T00:00:00Z")

    first_path = tmp_path / "first.json"
    first_path.write_text(
        json.dumps(
            _envelope_with_pack(
                pack, mission_key=mission_key, dispatch_key=dispatch_key, dispatch_id="dispatch-a"
            )
        ),
        encoding="utf-8",
    )
    first = activate_mission_dispatch_file(
        first_path,
        consumer=consumer,
        registry=registry,
        expected_edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )
    assert first.activated

    # 새 dispatch_id, 같은(digest 동일) pack — 재발급이지 rollback이 아니다.
    second_path = tmp_path / "second.json"
    second_path.write_text(
        json.dumps(
            _envelope_with_pack(
                pack, mission_key=mission_key, dispatch_key=dispatch_key, dispatch_id="dispatch-b"
            )
        ),
        encoding="utf-8",
    )
    second = activate_mission_dispatch_file(
        second_path,
        consumer=consumer,
        registry=registry,
        expected_edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )

    assert second.dispatch_verdict is DispatchVerdict.VALID
    assert second.activated


def test_native_handoff_is_repaired_on_idempotent_retry_and_removed_before_replacement_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, registry, dispatch_key = _envelope()
    dispatch_path = tmp_path / "dispatch.json"
    dispatch_path.write_text(json.dumps(raw), encoding="utf-8")
    consumer = MissionContractConsumer(registry=registry, state_dir=tmp_path / "state")
    first = activate_mission_dispatch_file(
        dispatch_path,
        consumer=consumer,
        registry=registry,
        expected_edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )
    assert first.activated
    native_snapshot = consumer.active_path.parent / "active-dispatch.native.v1"
    native_snapshot.unlink()
    retry = activate_mission_dispatch_file(
        dispatch_path,
        consumer=consumer,
        registry=registry,
        expected_edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )
    assert retry.activated and retry.reused_activation and native_snapshot.is_file()

    replacement = deepcopy(raw)
    replacement["dispatchId"] = "dispatch-002"
    dispatch_path.write_text(json.dumps(_resign_outer(replacement, dispatch_key)), encoding="utf-8")

    def _fail_native_write(*_args: object, **_kwargs: object) -> None:
        raise ContractInputError("synthetic native handoff write failure")

    monkeypatch.setattr(edge_activation, "_write_native_snapshot_atomically", _fail_native_write)
    with pytest.raises(ContractInputError, match="synthetic native handoff write failure"):
        activate_mission_dispatch_file(
            dispatch_path,
            consumer=consumer,
            registry=registry,
            expected_edge_device_id="edge-001",
            runtime_version="edge-runtime-0.1",
            now=_NOW,
        )
    assert not native_snapshot.exists(), "new active contract beside old native dispatch is unsafe"


def test_tampered_dispatch_never_replaces_active_contract_or_snapshot(tmp_path: Path) -> None:
    raw, registry, _key = _envelope()
    dispatch_path = tmp_path / "dispatch.json"
    dispatch_path.write_text(json.dumps(raw), encoding="utf-8")
    consumer = MissionContractConsumer(registry=registry, state_dir=tmp_path / "state")
    active = activate_mission_dispatch_file(
        dispatch_path,
        consumer=consumer,
        registry=registry,
        expected_edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )
    assert active.activated and active.active_snapshot_path is not None
    active_contract = consumer.active_path.read_bytes()
    active_snapshot = active.active_snapshot_path.read_bytes()

    tampered = deepcopy(raw)
    tampered["edgeDeviceId"] = "edge-other"
    dispatch_path.write_text(json.dumps(tampered), encoding="utf-8")
    rejected = activate_mission_dispatch_file(
        dispatch_path,
        consumer=consumer,
        registry=registry,
        expected_edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )

    assert not rejected.activated
    assert rejected.dispatch_verdict is DispatchVerdict.MALFORMED_DISPATCH
    assert consumer.active_path.read_bytes() == active_contract
    assert active.active_snapshot_path.read_bytes() == active_snapshot


def test_unknown_and_revoked_dispatch_keys_are_rejected() -> None:
    raw, registry, _key = _envelope()
    unknown = KeyRegistry()
    assert (
        verify_mission_dispatch_envelope(raw, unknown, now=_NOW).verdict
        is DispatchVerdict.UNKNOWN_DISPATCH_KEY
    )

    registry.revoke("dispatch-key")
    assert (
        verify_mission_dispatch_envelope(raw, registry, now=_NOW).verdict
        is DispatchVerdict.REVOKED_DISPATCH_KEY
    )


def test_revoked_inner_contract_key_is_not_accepted_by_outer_dispatch_signature() -> None:
    raw, registry, _key = _envelope()
    registry.revoke("mission-key")
    assert (
        verify_mission_dispatch_envelope(raw, registry, now=_NOW).verdict
        is DispatchVerdict.MISSION_CONTRACT_INVALID
    )


def test_risk_field_v1_1_requires_lineage_and_extruded_geometry() -> None:
    field = RiskField(
        schema_version="1.1",
        risk_field_id="rf-edge-001",
        type="PREDICTED",
        source_entity_ids=["eq-1"],
        validity=RiskFieldValidity(from_=_NOW, to=_NOW + timedelta(seconds=5)),  # type: ignore[call-arg]
        geometry=RiskFieldGeometry(
            format="EXTRUDED_POLYGON",
            payload={
                "vertices": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]],
                "zMinM": 0.0,
                "zMaxM": 4.0,
            },
        ),
        risk_model=RiskModel(
            policy_id="excavator-v1", severity=0.8, prediction_horizon_seconds=5.0
        ),
        uncertainty={"occluded": False},
        lineage=RiskFieldLineage(
            risk_policy_pack_digest="sha256:" + "a" * 64,
            calibration_profile_id="cal-001",
            source_timestamp=_NOW,
        ),
    )
    schema = json.loads(
        (_ROOT / "contracts/schemas/risk-field.v1.1.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(risk_field_wire_dict(field))

    with pytest.raises(Exception, match="lineage"):
        RiskField.model_validate({**risk_field_wire_dict(field), "lineage": None})
    with pytest.raises(Exception, match="EXTRUDED_POLYGON"):
        RiskField.model_validate(
            {**risk_field_wire_dict(field), "geometry": {"format": "GEOJSON_2D", "payload": {}}}
        )


# ── KMZ digest 결속 (ADR-KSI-007 짝 불변식의 첫 기계 검증) ──────────────────
#
# KMZ 는 서명이 없다. 지금까지 "계약과 KMZ 가 같은 요청에서 나온 짝"이라는 것은
# 발급 시점 서버 내부의 규약일 뿐이었고, 전달 경로 어디에서도 검증되지 않았다 —
# 사람이 조종기에 옮긴 파일이 그 계약의 짝인지 확인할 방법이 아무 데도 없었다.
# 아래 시험들이 고정하는 것은 그 검증이 **활성화를 실제로 막는가**다.

_KMZ_BODY = b"PK\x03\x04ksi-golden-wayline-bytes"
_KMZ_SHA256 = hashlib.sha256(_KMZ_BODY).hexdigest()


def _envelope_with_kmz(
    *,
    kmz_sha256: str | None,
    dispatch_id: str = "dispatch-001",
    mission_key: Ed25519PrivateKey | None = None,
    dispatch_key: Ed25519PrivateKey | None = None,
) -> tuple[dict[str, Any], KeyRegistry, Ed25519PrivateKey]:
    """:func:`_envelope` 와 같은 모양이되 KMZ digest 를 고른다.

    같은 키를 두 번 넘길 수 있게 열어둔 이유는 "KMZ 를 실은 봉투를 활성화한 뒤 같은
    장비·같은 신뢰로 KMZ 없는 봉투를 활성화한다"가 키 불일치 시나리오가 아니라
    정상 재배포 시나리오여야 하기 때문이다.
    """
    mission_key = mission_key if mission_key is not None else Ed25519PrivateKey.generate()
    dispatch_key = dispatch_key if dispatch_key is not None else Ed25519PrivateKey.generate()
    signed_contract = sign_contract(_unsigned_contract(), mission_key, "mission-key")
    envelope = build_mission_dispatch_envelope(
        dispatch_id=dispatch_id,
        edge_device_id="edge-001",
        mission_contract=signed_contract,
        risk_policy_pack=_pack(),
        edge_runtime_profile=_profile(),
        validity=DispatchValidity(
            not_before=_NOW - timedelta(minutes=1), not_after=_NOW + timedelta(minutes=20)
        ),
        private_key=dispatch_key,
        key_id="dispatch-key",
        kmz_sha256=kmz_sha256,
    )
    return (
        envelope.model_dump(by_alias=True, mode="json"),
        _registry(mission_key, dispatch_key),
        dispatch_key,
    )


def _candidate_file(tmp_path: Path, raw: dict[str, Any], name: str = "dispatch.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def _activate(
    candidate: Path,
    state_directory: Path,
    registry: KeyRegistry,
    *,
    kmz_bytes: bytes | None,
) -> Any:
    return activate_mission_dispatch_file(
        candidate,
        consumer=MissionContractConsumer(registry=registry, state_dir=state_directory),
        registry=registry,
        expected_edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        kmz_bytes=kmz_bytes,
        now=_NOW,
    )


def test_activation_binds_the_kmz_and_publishes_its_marker_last(tmp_path: Path) -> None:
    """[핵심] 정상 경로 — 바이트·사이드카가 남고, 활성화 표식이 **마지막**이다.

    순서가 중요한 이유: 표식이 먼저 생기면 KMZ 쓰기가 실패한 순간 C++ 은 "활성화됐다"
    고 읽으면서 경로는 이전 임무 것을 보게 된다.
    """
    raw, registry, _key = _envelope_with_kmz(kmz_sha256=_KMZ_SHA256)
    state_directory = _private_state_directory(tmp_path)

    result = _activate(
        _candidate_file(tmp_path, raw), state_directory, registry, kmz_bytes=_KMZ_BODY
    )

    assert result.activated is True
    assert result.dispatch_verdict is DispatchVerdict.VALID
    kmz_path = state_directory / "active-mission.kmz"
    sidecar_path = state_directory / "active-mission-kmz.native.v1"
    assert kmz_path.read_bytes() == _KMZ_BODY
    assert kmz_path.stat().st_mode & 0o077 == 0
    sidecar = sidecar_path.read_text(encoding="ascii")
    assert sidecar.startswith("KSI_EDGE_NATIVE_MISSION_KMZ_V1\n")
    assert f"kmz_sha256={_KMZ_SHA256}\n" in sidecar
    assert f"kmz_byte_count={len(_KMZ_BODY)}\n" in sidecar
    assert f"mission_contract_digest={raw['missionContractDigest']}\n" in sidecar
    assert (state_directory / "active-dispatch.native.v1").is_file()


def test_wrong_kmz_bytes_refuse_the_whole_activation_without_touching_local_state(
    tmp_path: Path,
) -> None:
    """[핵심] digest 불일치는 계약까지 포함해 활성화 **전체**를 거부한다.

    거부가 판정 순서상 어디에 있는지가 이 시험의 요점이다: 로컬 상태가 하나도 움직이지
    않았다는 것(활성 계약 파일 자체가 생기지 않았다는 것)이 "계약만 활성화되고 경로는
    낡은 채로 남는" 상태를 구조적으로 배제한다.
    """
    raw, registry, _key = _envelope_with_kmz(kmz_sha256=_KMZ_SHA256)
    state_directory = _private_state_directory(tmp_path)

    result = _activate(
        _candidate_file(tmp_path, raw), state_directory, registry, kmz_bytes=b"not-that-file"
    )

    assert result.activated is False
    assert result.dispatch_verdict is DispatchVerdict.KMZ_DIGEST_MISMATCH
    assert not (state_directory / "active-mission.kmz").exists()
    assert not (state_directory / "active-mission-kmz.native.v1").exists()
    assert not (state_directory / "active-contract.json").exists()
    assert not (state_directory / "active-dispatch.native.v1").exists()


def test_declared_kmz_digest_with_no_bytes_is_refused_not_treated_as_no_kmz(
    tmp_path: Path,
) -> None:
    """못 받은 것과 받을 필요가 없는 것은 다르다.

    봉투가 digest 를 선언했는데 바이트가 없으면, 그 임무를 "KMZ 없는 임무"로 강등해
    활성화하는 순간 이 결속은 바이트를 빼는 것만으로 우회된다.
    """
    raw, registry, _key = _envelope_with_kmz(kmz_sha256=_KMZ_SHA256)
    state_directory = _private_state_directory(tmp_path)

    result = _activate(_candidate_file(tmp_path, raw), state_directory, registry, kmz_bytes=None)

    assert result.activated is False
    assert result.dispatch_verdict is DispatchVerdict.KMZ_DIGEST_MISMATCH


def test_kmz_bytes_for_an_envelope_that_declares_none_are_refused(tmp_path: Path) -> None:
    """반대 방향도 막는다 — 서명이 "KMZ 없음"이라고 말하는데 파일이 하나 있으면
    그 파일의 출처를 설명하는 서명이 어디에도 없다."""
    raw, registry, _key = _envelope_with_kmz(kmz_sha256=None)
    state_directory = _private_state_directory(tmp_path)

    result = _activate(
        _candidate_file(tmp_path, raw), state_directory, registry, kmz_bytes=_KMZ_BODY
    )

    assert result.activated is False
    assert result.dispatch_verdict is DispatchVerdict.KMZ_DIGEST_MISMATCH


def test_crash_between_kmz_publish_and_activation_marker_recovers_on_retry(
    tmp_path: Path,
) -> None:
    """[핵심, 부분 쓰기 복구] 표식만 없는 상태에서 재시도하면 그대로 복구된다.

    활성화 도중 프로세스가 죽으면 "계약·경로는 새것, 표식은 없음"이 남는다 — C++ 에게는
    capture-only 다. Core 는 ACK 없는 같은 dispatch 를 계속 돌려주므로 다음 호출이
    같은 자리에서 재시도하고, 그때 **계약 검증을 다시 하지 않고** 표식만 다시 세운다
    (``reused_activation``). 이 복구가 없으면 크래시 한 번이 임무를 영구히 막는다.
    """
    raw, registry, _key = _envelope_with_kmz(kmz_sha256=_KMZ_SHA256)
    state_directory = _private_state_directory(tmp_path)
    candidate = _candidate_file(tmp_path, raw)
    first = _activate(candidate, state_directory, registry, kmz_bytes=_KMZ_BODY)
    assert first.activated is True

    # 표식 직전에 죽은 상태를 그대로 재현한다.
    (state_directory / "active-dispatch.native.v1").unlink()
    (state_directory / "active-mission-kmz.native.v1").unlink()

    retried = _activate(candidate, state_directory, registry, kmz_bytes=_KMZ_BODY)

    assert retried.activated is True
    assert retried.reused_activation is True
    assert retried.activation_receipt == first.activation_receipt
    assert (state_directory / "active-dispatch.native.v1").is_file()
    assert (state_directory / "active-mission-kmz.native.v1").is_file()
    assert (state_directory / "active-mission.kmz").read_bytes() == _KMZ_BODY


def test_null_digest_removes_the_kmz_a_previous_mission_left_behind(tmp_path: Path) -> None:
    """[핵심, null digest 정리] 계약 단독 발급은 남아 있던 경로를 **지운다**.

    지우지 않으면 KMZ 없는 임무를 활성화한 기체의 디스크에 이전 임무의 비행경로가
    같은 파일명으로 남는다 — 그 파일을 집어 올리는 코드가 나중에 생기면 그 순간
    "활성 계약과 다른 임무의 경로"가 성립한다. 없앨 수 있을 때 없앤다.
    """
    mission_key = Ed25519PrivateKey.generate()
    dispatch_key = Ed25519PrivateKey.generate()
    state_directory = _private_state_directory(tmp_path)
    with_kmz, registry, _key = _envelope_with_kmz(
        kmz_sha256=_KMZ_SHA256, mission_key=mission_key, dispatch_key=dispatch_key
    )
    assert _activate(
        _candidate_file(tmp_path, with_kmz, "a.json"),
        state_directory,
        registry,
        kmz_bytes=_KMZ_BODY,
    ).activated
    assert (state_directory / "active-mission.kmz").is_file()

    without_kmz, _registry2, _key2 = _envelope_with_kmz(
        kmz_sha256=None,
        dispatch_id="dispatch-002",
        mission_key=mission_key,
        dispatch_key=dispatch_key,
    )
    result = _activate(
        _candidate_file(tmp_path, without_kmz, "b.json"), state_directory, registry, kmz_bytes=None
    )

    assert result.activated is True
    assert not (state_directory / "active-mission.kmz").exists()
    assert not (state_directory / "active-mission-kmz.native.v1").exists()


def test_dispatch_sync_fetches_the_kmz_over_the_same_pinned_transport(tmp_path: Path) -> None:
    """컴패니언이 봉투 pull 직후 같은 연결 설정으로 KMZ 를 받아 활성화까지 잇는다.

    호출 순서 자체를 고정한다 — KMZ 경로에 쓰이는 missionId 는 **검증을 통과한**
    봉투에서 나와야 하므로, pull 과 활성화 사이에 정확히 한 번 들어간다.
    """
    raw, registry, _key = _envelope_with_kmz(kmz_sha256=_KMZ_SHA256)
    transport = _FakeDispatchTransport(
        [
            CoreDispatchHttpResponse(
                200,
                json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                "application/json; charset=utf-8",
            )
        ],
        [CoreDispatchHttpResponse(201)],
        [CoreDispatchHttpResponse(200, _KMZ_BODY, "application/vnd.google-earth.kmz")],
    )
    state_directory = _private_state_directory(tmp_path)

    result = synchronize_edge_dispatch_once(
        transport=transport,
        registry=registry,
        state_directory=state_directory,
        edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )

    assert result.verdict is EdgeDispatchSyncVerdict.ACTIVATED_AND_RECORDED
    assert transport.paths == [
        "GET /v1/edge-sync/missions/next",
        "GET /v1/missions/mission-edge-001/kmz",
        "POST /v1/edge-sync/missions/dispatch-001/activation-receipts",
    ]
    assert (state_directory / "active-mission.kmz").read_bytes() == _KMZ_BODY


def test_dispatch_sync_kmz_fetch_failure_does_not_activate_anything(tmp_path: Path) -> None:
    """KMZ 를 못 받은 것은 "짝이 틀렸다"가 아니라 "아직 손에 없다"다.

    활성화를 시도조차 하지 않고(영수증도 보내지 않고) 다음 호출로 미룬다 — Core 는
    ACK 없는 같은 dispatch 를 계속 돌려주므로 재시도가 성립한다.
    """
    raw, registry, _key = _envelope_with_kmz(kmz_sha256=_KMZ_SHA256)
    transport = _FakeDispatchTransport(
        [
            CoreDispatchHttpResponse(
                200,
                json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                "application/json; charset=utf-8",
            )
        ],
        [CoreDispatchHttpResponse(201)],
        [CoreDispatchTransportError(retryable=True)],
    )
    state_directory = _private_state_directory(tmp_path)

    result = synchronize_edge_dispatch_once(
        transport=transport,
        registry=registry,
        state_directory=state_directory,
        edge_device_id="edge-001",
        runtime_version="edge-runtime-0.1",
        now=_NOW,
    )

    assert result.verdict is EdgeDispatchSyncVerdict.KMZ_FETCH_RETRYABLE_FAILURE
    assert transport.paths == [
        "GET /v1/edge-sync/missions/next",
        "GET /v1/missions/mission-edge-001/kmz",
    ]
    assert not (state_directory / "active-contract.json").exists()
    assert not (state_directory / "active-mission.kmz").exists()


def test_v1_0_envelope_still_verifies_after_the_v1_1_field_was_added(tmp_path: Path) -> None:
    """이미 발행돼 저널에 남은 v1.0 봉투가 계속 검증된다.

    dispatch journal 은 append-only 라 재생이 과거 발행분 **전부**를 다시 통과시킨다 —
    새 필드를 필수로 좁히면 안전과 무관한 이유로 Core 가 기동하지 못한다. 대신 v1.0 은
    "kmzSha256 자리가 아예 없는 봉투"로만 유효하고, 그 봉투는 KMZ 없는 임무와 같은
    취급을 받는다(활성화는 되고 남아 있던 경로는 지워진다).
    """
    raw, registry, dispatch_key = _envelope_with_kmz(kmz_sha256=None)
    legacy = {key: value for key, value in raw.items() if key != "kmzSha256"}
    legacy["schemaVersion"] = "1.0"
    legacy = _resign_outer(legacy, dispatch_key)

    verification = verify_mission_dispatch_envelope(
        legacy, registry, expected_edge_device_id="edge-001", now=_NOW
    )

    assert verification.verdict is DispatchVerdict.VALID
    assert verification.envelope is not None
    assert verification.envelope.kmz_sha256 is None
    state_directory = _private_state_directory(tmp_path)
    assert _activate(
        _candidate_file(tmp_path, legacy), state_directory, registry, kmz_bytes=None
    ).activated


def test_v1_1_envelope_that_omits_the_kmz_field_is_malformed() -> None:
    """v1.1 인데 필드를 통째로 뺀 봉투는 거부된다.

    "있으면 대조하고 없으면 넘어간다"였다면 이 결속은 키 하나를 지우는 것만으로
    무력화된다 — 그래서 null 도 **선언**이어야 한다.
    """
    raw, registry, dispatch_key = _envelope_with_kmz(kmz_sha256=_KMZ_SHA256)
    stripped = _resign_outer(
        {key: value for key, value in raw.items() if key != "kmzSha256"}, dispatch_key
    )

    result = verify_mission_dispatch_envelope(
        stripped, registry, expected_edge_device_id="edge-001", now=_NOW
    )

    assert result.verdict is DispatchVerdict.MALFORMED_DISPATCH
