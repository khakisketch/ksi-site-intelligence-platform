"""이원 산출물 짝 발급 계약 (POST /v1/missions/plans, ADR-KSI-007).

초점: ① KMZ 와 계약이 **같은 요청**에서 나와 site_frame·정책이 어긋날 수 없는가
② 경로 고도가 계약 FlightEnvelope 로 게이트되는가(짝 발급의 안전 핵심) ③ 임무
타입→패턴 매핑과 미지원 타입 fail-closed ④ 산출물 자체의 유효성(계약 서명 검증,
KMZ 재파싱).
"""

from __future__ import annotations

import base64
import io
import math
import zipfile
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_mission_contracts.signing import KeyRegistry, SignatureVerdict, load_verified_contract

_LAT0, _LON0 = 37.5000, 127.0000


def _rect_aoi_vertices() -> list[dict[str, float]]:
    dlat = 100.0 / 111_194.9
    dlon = 200.0 / (111_194.9 * math.cos(math.radians(_LAT0)))
    return [
        {"lat_deg": _LAT0, "lon_deg": _LON0},
        {"lat_deg": _LAT0, "lon_deg": _LON0 + dlon},
        {"lat_deg": _LAT0 + dlat, "lon_deg": _LON0 + dlon},
        {"lat_deg": _LAT0 + dlat, "lon_deg": _LON0},
    ]


def _plan_request(
    mission_type: str = "AUTONOMOUS_PATROL", **route_overrides: Any
) -> dict[str, Any]:
    route: dict[str, Any] = {"altitudeM": 40.0}
    route.update(route_overrides)
    return {
        "contract": {
            "missionId": "mission-001",
            "siteId": "site-001",
            "missionType": mission_type,
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
            "objectives": ["외곽 순찰"],
            "viewpointPolicyId": "vp-1",
            "riskPolicyPackId": "risk-1",
            "fallbackPolicyId": "fb-1",
            "capturePolicyId": "cap-1",
        },
        "aoi": {"vertices": _rect_aoi_vertices()},
        "route": route,
        "drone": {"droneEnumValue": 99, "droneSubEnumValue": 0, "payloadEnumValue": 65534},
        "wayline": {
            "autoFlightSpeedMs": 5.0,
            "takeoffSecurityHeightM": 20.0,
            "globalTransitionalSpeedMs": 10.0,
        },
    }


def _client() -> tuple[TestClient, KeyRegistry]:
    key_id = "core-issuer-key-1"
    private_key = Ed25519PrivateKey.generate()
    registry = KeyRegistry()
    registry.register(key_id, private_key.public_key())
    app = create_app(mission_signing_key=private_key, mission_signing_key_id=key_id)
    return TestClient(app), registry


def test_plan_issues_contract_and_kmz_pair() -> None:
    client, registry = _client()

    response = client.post("/v1/missions/plans", json=_plan_request())

    assert response.status_code == 201
    body = response.json()
    assert body["routePattern"] == "perimeter"
    assert body["waypointCount"] == 5  # 꼭짓점 4 + 폐루프 1

    loaded = load_verified_contract(body["contract"], registry, now=datetime.now(UTC))
    assert loaded.verdict is SignatureVerdict.VALID, loaded.detail

    kmz = base64.b64decode(body["kmzBase64"])
    with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
        assert set(archive.namelist()) == {
            "wpmz/template.kml",
            "wpmz/waylines.wpml",
            "wpmz/res/",
        }


def test_plan_route_altitude_gated_by_contract_envelope() -> None:
    """경로 고도가 계약 봉투 밖이면 짝 발급 전체가 거부된다 — 계약만 발급되고 KMZ 는
    봉투 밖인 어긋난 쌍이 존재할 수 없다."""
    client, _registry = _client()

    response = client.post("/v1/missions/plans", json=_plan_request(altitudeM=150.0))

    assert response.status_code == 422
    assert "FlightEnvelope" in response.json()["detail"]


def test_mapping_type_uses_lawnmower_and_requires_spacing() -> None:
    client, _registry = _client()

    missing_spacing = client.post(
        "/v1/missions/plans", json=_plan_request(mission_type="BASELINE_MAPPING")
    )
    assert missing_spacing.status_code == 422
    assert "spacingM" in missing_spacing.json()["detail"]

    with_spacing = client.post(
        "/v1/missions/plans",
        json=_plan_request(mission_type="BASELINE_MAPPING", spacingM=20.0),
    )
    assert with_spacing.status_code == 201
    assert with_spacing.json()["routePattern"] == "lawnmower"


def test_unsupported_mission_type_rejected_not_degraded() -> None:
    client, _registry = _client()

    response = client.post(
        "/v1/missions/plans", json=_plan_request(mission_type="ASSET_INSPECTION")
    )

    assert response.status_code == 422
    assert "미지원" in response.json()["detail"]


def test_plans_endpoint_absent_without_signing_key() -> None:
    app = create_app()
    client = TestClient(app)
    assert client.post("/v1/missions/plans", json=_plan_request()).status_code == 404
