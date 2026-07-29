"""이원 산출물 짝 발급 계약 (POST /v1/missions/plans, ADR-KSI-007).

초점: ① KMZ 와 계약이 **같은 요청**에서 나와 site_frame·정책이 어긋날 수 없는가
② 경로 고도가 계약 FlightEnvelope 로 게이트되는가(짝 발급의 안전 핵심) ③ 임무
타입→패턴 매핑과 미지원 타입 fail-closed ④ 산출물 자체의 유효성(계약 서명 검증,
KMZ 재파싱).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import zipfile
from datetime import UTC, datetime
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.mission_plans import _require_wayline_takeoff_height_compatible
from ksi_geo_core.frames import WGS84_EQUATORIAL_RADIUS_M
from ksi_mission_contracts.models import FlightEnvelope
from ksi_mission_contracts.signing import (
    KeyRegistry,
    SignatureVerdict,
    canonical_payload_bytes,
    load_verified_contract,
    sha256_digest,
)
from ksi_mission_planning import RouteGenerationError

_LAT0, _LON0 = 37.5000, 127.0000
# 축척은 geo-core frames 와 **동일 상수**에서 유도한다(test_mission_planning.py 와
# 정본 통일 — 재검토가 한 파일만 고쳐 111_194.9(R=6371km 기반, frames 의
# 6378137 과 불일치)가 이 파일에만 남아 있었다).
_M_PER_DEG_LAT = math.radians(1.0) * WGS84_EQUATORIAL_RADIUS_M


def _rect_aoi_vertices() -> list[dict[str, float]]:
    dlat = 100.0 / _M_PER_DEG_LAT
    dlon = 200.0 / (_M_PER_DEG_LAT * math.cos(math.radians(_LAT0)))
    return [
        {"lat_deg": _LAT0, "lon_deg": _LON0},
        {"lat_deg": _LAT0, "lon_deg": _LON0 + dlon},
        {"lat_deg": _LAT0 + dlat, "lon_deg": _LON0 + dlon},
        {"lat_deg": _LAT0 + dlat, "lon_deg": _LON0},
    ]


def _rect_aoi_vertices_camel() -> list[dict[str, float]]:
    """latDeg/lonDeg camelCase 별칭 버전(F.3 전 와이어 camelCase 테스트 전용)."""
    dlat = 100.0 / _M_PER_DEG_LAT
    dlon = 200.0 / (_M_PER_DEG_LAT * math.cos(math.radians(_LAT0)))
    return [
        {"latDeg": _LAT0, "lonDeg": _LON0},
        {"latDeg": _LAT0, "lonDeg": _LON0 + dlon},
        {"latDeg": _LAT0 + dlat, "lonDeg": _LON0 + dlon},
        {"latDeg": _LAT0 + dlat, "lonDeg": _LON0},
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
            "wpmz/res/ksi-mission-pair.json",
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


def test_issued_envelope_carries_altitude_reference() -> None:
    """2026-07-29 대표자 확정 — 발급 계약의 봉투 고도 수직기준은 서버가 고정한다."""
    client, _registry = _client()
    response = client.post("/v1/missions/plans", json=_plan_request())
    envelope = response.json()["contract"]["flightEnvelope"]
    assert envelope["altitudeReference"] == "relativeToStartPoint"


def test_mapping_plan_kmz_contains_capture_actions_patrol_does_not() -> None:
    import xml.etree.ElementTree as ET

    ns = {"kml": "http://www.opengis.net/kml/2.2", "wpml": "http://www.dji.com/wpmz/1.0.2"}
    client, _registry = _client()

    def action_funcs(mission_type: str, **route: object) -> list[str | None]:
        response = client.post(
            "/v1/missions/plans", json=_plan_request(mission_type=mission_type, **route)
        )
        assert response.status_code == 201
        kmz = base64.b64decode(response.json()["kmzBase64"])
        with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
            root = ET.fromstring(archive.read("wpmz/waylines.wpml"))
        return [
            a.findtext("wpml:actionActuatorFunc", namespaces=ns)
            for a in root.findall(".//wpml:action", ns)
        ]

    assert "takePhoto" in action_funcs("BASELINE_MAPPING", spacingM=20.0)
    assert action_funcs("AUTONOMOUS_PATROL") == []


def test_pair_height_semantics_match_between_kmz_and_contract() -> None:
    """재검토 #5 — 한 응답 안에서 KMZ 높이 모드와 계약 altitudeReference 가 같은
    값이어야 한다(F1 의 실제 위험: 두 산출물의 수직기준 무음 이탈)."""
    import xml.etree.ElementTree as ET

    ns = {"kml": "http://www.opengis.net/kml/2.2", "wpml": "http://www.dji.com/wpmz/1.0.2"}
    client, _registry = _client()
    response = client.post("/v1/missions/plans", json=_plan_request())
    body = response.json()

    reference = body["contract"]["flightEnvelope"]["altitudeReference"]
    kmz = base64.b64decode(body["kmzBase64"])
    with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
        template = ET.fromstring(archive.read("wpmz/template.kml"))
        waylines = ET.fromstring(archive.read("wpmz/waylines.wpml"))
    height_mode = template.findtext(
        "kml:Document/kml:Folder/wpml:waylineCoordinateSysParam/wpml:heightMode", namespaces=ns
    )
    execute_mode = waylines.findtext(
        "kml:Document/kml:Folder/wpml:executeHeightMode", namespaces=ns
    )
    assert height_mode == execute_mode == reference == "relativeToStartPoint"


# ── A. 어긋난 쌍 차단 — takeoffSecurityHeightM × flightEnvelope (P1) ─────────


def test_takeoff_security_height_exceeding_envelope_rejected() -> None:
    """P1 반증 — maxAltitudeM=120 계약 + takeoffSecurityHeightM=1500 요청은 이전엔
    조용히 201 로 발급되던 어긋난 쌍이다(이륙 안전고도가 계약 봉투 밖)."""
    client, _registry = _client()
    request = _plan_request()
    request["wayline"]["takeoffSecurityHeightM"] = 1500.0

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 422
    assert "TAKEOFF_HEIGHT_EXCEEDS_ENVELOPE" in response.json()["detail"]


def test_takeoff_security_height_below_minimum_rejected() -> None:
    client, _registry = _client()
    request = _plan_request()
    request["wayline"]["takeoffSecurityHeightM"] = 1.0

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 422
    assert "TAKEOFF_HEIGHT_BELOW_MINIMUM" in response.json()["detail"]


# ── B. 짝 식별자 (P2 — ADR-KSI-007 '동일 site_frame·policy_version 짝'의 실체화) ──


def test_pair_manifest_identifiers_are_deterministic_and_cross_consistent() -> None:
    """P2 반증 — kmzSha256 이 응답 KMZ 재해시와 일치하고, KMZ 안 pair manifest 의
    contractPayloadSha256 이 **ADR-KSI-002 문서화 정규화**(canonical_payload_bytes:
    signature 제외·ensure_ascii=False·sha256:<hex>)로 재현되며 — 독자 정규화가
    아니어야 비-Python 검증기가 ADR 만 보고 짝 검증을 재현할 수 있다(재검증 P2) —
    perimeter 는 coverageRatio 가 null 이다."""
    client, _registry = _client()

    response = client.post("/v1/missions/plans", json=_plan_request())  # perimeter

    assert response.status_code == 201
    body = response.json()
    assert body["coverageRatio"] is None

    kmz = base64.b64decode(body["kmzBase64"])
    assert body["kmzSha256"] == hashlib.sha256(kmz).hexdigest()

    contract_payload_sha256 = sha256_digest(canonical_payload_bytes(body["contract"]))

    with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
        manifest = json.loads(archive.read("wpmz/res/ksi-mission-pair.json"))

    assert manifest["format"] == "ksi-mission-pair/v1"
    assert manifest["contractPayloadSha256"] == contract_payload_sha256
    assert manifest["contractPayloadSha256"].startswith("sha256:")
    assert manifest["siteFrameSha256"].startswith("sha256:")
    assert manifest["missionId"] == body["contract"]["missionId"]
    assert manifest["siteId"] == body["contract"]["siteId"]
    assert manifest["viewpointPolicyId"] == body["contract"]["policies"]["viewpointPolicyId"]
    assert manifest["riskPolicyPackId"] == body["contract"]["policies"]["riskPolicyPackId"]
    assert manifest["fallbackPolicyId"] == body["contract"]["policies"]["fallbackPolicyId"]
    assert manifest["capturePolicyId"] == body["contract"]["policies"]["capturePolicyId"]


def _shear_aoi_vertices() -> list[dict[str, float]]:
    """전단 평행사변형(볼록) — 정확 커버 계산이 [0.95, 1.0) 구간 값을 내는 도형
    (spacing 20 에서 실측 0.9975 — 커버 약속 게이트의 양방향 검증용)."""
    dlat = 100.0 / _M_PER_DEG_LAT
    dlon_w = 200.0 / (_M_PER_DEG_LAT * math.cos(math.radians(_LAT0)))
    dlon_d = 10.0 / (_M_PER_DEG_LAT * math.cos(math.radians(_LAT0)))
    return [
        {"lat_deg": _LAT0, "lon_deg": _LON0},
        {"lat_deg": _LAT0, "lon_deg": _LON0 + dlon_w},
        {"lat_deg": _LAT0 + dlat, "lon_deg": _LON0 + dlon_w + dlon_d},
        {"lat_deg": _LAT0 + dlat, "lon_deg": _LON0 + dlon_d},
    ]


def test_coverage_promise_above_measured_ratio_rejected() -> None:
    """재검증 P2 반증 — 계약이 accessibleGeneralCoverage=1.0 을 약속(서명 대상)하는데
    같은 요청의 실측 커버가 1.0 미만이면, 그 어긋난 쌍은 발급되지 않는다(이륙고도
    게이트와 동일 클래스 — 이전엔 조용히 201 이었다)."""
    client, _registry = _client()
    request = _plan_request(mission_type="BASELINE_MAPPING", spacingM=20.0)
    request["aoi"] = {"vertices": _shear_aoi_vertices()}
    request["contract"]["accessibleGeneralCoverage"] = 1.0

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 422
    assert "COVERAGE_BELOW_CONTRACT_PROMISE" in response.json()["detail"]


def test_coverage_promise_at_default_accepts_imperfect_ratio() -> None:
    """대조 — 같은 도형이라도 약속(기본 0.95)이 실측 이하면 정상 발급된다."""
    client, _registry = _client()
    request = _plan_request(mission_type="BASELINE_MAPPING", spacingM=20.0)
    request["aoi"] = {"vertices": _shear_aoi_vertices()}

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 201
    assert 0.95 <= response.json()["coverageRatio"] < 1.0


def test_takeoff_height_gate_rejects_non_finite() -> None:
    """재검증 P3 — NaN 은 게이트의 두 부등식이 모두 False 라 지나가던 값이다.
    하류(WaylineMissionConfig)의 isfinite 에 기대지 않고 게이트 자신이 막는다."""
    envelope = FlightEnvelope(
        allowed_volumes=["vol-1"],
        excluded_volumes=[],
        min_altitude_m=5.0,
        max_altitude_m=120.0,
    )
    with pytest.raises(RouteGenerationError, match="finite"):
        _require_wayline_takeoff_height_compatible(float("nan"), envelope)


def test_lawnmower_plan_reports_coverage_ratio() -> None:
    client, _registry = _client()

    response = client.post(
        "/v1/missions/plans",
        json=_plan_request(mission_type="BASELINE_MAPPING", spacingM=20.0),
    )

    assert response.status_code == 201
    coverage_ratio = response.json()["coverageRatio"]
    assert coverage_ratio is not None
    assert 0.0 <= coverage_ratio <= 1.0


# ── D. allowedVolumes=[] 거부 (W1 생성기 게이트) ─────────────────────────────


def test_lawnmower_rejects_empty_allowed_volumes() -> None:
    client, _registry = _client()
    request = _plan_request(mission_type="BASELINE_MAPPING", spacingM=20.0)
    request["contract"]["flightEnvelope"]["allowedVolumes"] = []

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 422
    assert "EMPTY_ALLOWED_VOLUMES" in response.json()["detail"]


def test_perimeter_rejects_empty_allowed_volumes() -> None:
    client, _registry = _client()
    request = _plan_request()
    request["contract"]["flightEnvelope"]["allowedVolumes"] = []

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 422
    assert "EMPTY_ALLOWED_VOLUMES" in response.json()["detail"]


# ── F.3 전 와이어 camelCase 통합 테스트 ──────────────────────────────────────


def test_pure_camelcase_wire_body_is_accepted() -> None:
    """와이어 전체가 camelCase 여도 통과한다(W1 의 AreaOfInterest camelCase 별칭
    전제 — aoi.vertices[].latDeg/lonDeg)."""
    client, _registry = _client()
    request = _plan_request()
    request["aoi"] = {"vertices": _rect_aoi_vertices_camel()}

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 201
