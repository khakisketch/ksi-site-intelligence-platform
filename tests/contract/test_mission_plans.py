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
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_plans import (
    MissionPlanRequest,
    _require_wayline_takeoff_height_compatible,
)
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_core.sites import SiteStore
from ksi_geo_core.frames import WGS84_EQUATORIAL_RADIUS_M
from ksi_mission_contracts.models import FlightEnvelope, SiteFrame
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
    # lawnmower 요청은 진행방향 촬영 간격이 필수다(전방 중첩 0 차단) — 그 규칙
    # 자체를 반증하는 테스트는 captureIntervalM 을 명시적으로 넘겨 이 기본값을
    # 우회한다(``in route_overrides`` 검사라 None 을 명시하면 그대로 None 이다).
    if "spacingM" in route and "captureIntervalM" not in route_overrides:
        route["captureIntervalM"] = 15.0
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


_ISSUER_TOKEN = "mission-issuer-token"  # noqa: S105 — 테스트 고정 토큰


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_ISSUER_TOKEN),
                principal=Principal(
                    principal_id="do-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.DRONE_OPERATOR,
                    device_id=None,
                ),
            )
        ]
    )


def _client(tmp_path: Path) -> tuple[TestClient, KeyRegistry]:
    """서명키 + mission_store + site_store + auth_registry 최소 조립(ADR-KSI-008 §3).

    요청 site_id("site-001")는 발급 전 site_store 에 직접 등록한다 — precheck_issuance
    의 site_exists 게이트가 이제 이 저장소로 배선되기 때문.
    """
    key_id = "core-issuer-key-1"
    private_key = Ed25519PrivateKey.generate()
    registry = KeyRegistry()
    registry.register(key_id, private_key.public_key())

    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    site_store.register(
        "site-001",
        "Site 001",
        SiteFrame.model_validate(
            {
                "crs": "EPSG:5186",
                "verticalDatum": "KNGeoid2018",
                "unit": "meter",
                "transformVersion": "1.0.0",
            }
        ),
        actor="test-harness",
        now=datetime.now(UTC),
    )
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))

    app = create_app(
        mission_signing_key=private_key,
        mission_signing_key_id=key_id,
        mission_store=mission_store,
        site_store=site_store,
        auth_registry=_auth_registry(),
    )
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_ISSUER_TOKEN}"})
    return client, registry


def test_plan_issues_contract_and_kmz_pair(tmp_path: Path) -> None:
    client, registry = _client(tmp_path)

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


def test_plan_route_altitude_gated_by_contract_envelope(tmp_path: Path) -> None:
    """경로 고도가 계약 봉투 밖이면 짝 발급 전체가 거부된다 — 계약만 발급되고 KMZ 는
    봉투 밖인 어긋난 쌍이 존재할 수 없다."""
    client, _registry = _client(tmp_path)

    response = client.post("/v1/missions/plans", json=_plan_request(altitudeM=150.0))

    assert response.status_code == 422
    assert "FlightEnvelope" in response.json()["detail"]


def test_mapping_type_uses_lawnmower_and_requires_spacing(tmp_path: Path) -> None:
    client, _registry = _client(tmp_path)

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


def test_unsupported_mission_type_rejected_not_degraded(tmp_path: Path) -> None:
    client, _registry = _client(tmp_path)

    response = client.post(
        "/v1/missions/plans", json=_plan_request(mission_type="ASSET_INSPECTION")
    )

    assert response.status_code == 422
    assert "미지원" in response.json()["detail"]


def test_plans_endpoint_absent_without_signing_key() -> None:
    app = create_app()
    client = TestClient(app)
    assert client.post("/v1/missions/plans", json=_plan_request()).status_code == 404


def test_issued_envelope_carries_altitude_reference(tmp_path: Path) -> None:
    """2026-07-29 대표자 확정 — 발급 계약의 봉투 고도 수직기준은 서버가 고정한다."""
    client, _registry = _client(tmp_path)
    response = client.post("/v1/missions/plans", json=_plan_request())
    envelope = response.json()["contract"]["flightEnvelope"]
    assert envelope["altitudeReference"] == "relativeToStartPoint"


def test_mapping_plan_kmz_contains_capture_actions_patrol_does_not(tmp_path: Path) -> None:
    import xml.etree.ElementTree as ET

    ns = {"kml": "http://www.opengis.net/kml/2.2", "wpml": "http://www.dji.com/wpmz/1.0.2"}
    client, _registry = _client(tmp_path)

    def action_funcs(mission_type: str, **route: object) -> list[str | None]:
        # 서로 다른 missionId — mission_store 가 이제 발급을 영속하므로 같은
        # missionId 재사용은 두 번째 호출을 409 MISSION_ID_CONFLICT 로 거부한다.
        request = _plan_request(mission_type=mission_type, **route)
        request["contract"]["missionId"] = f"mission-{mission_type.lower()}"
        response = client.post("/v1/missions/plans", json=request)
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


def test_pair_height_semantics_match_between_kmz_and_contract(tmp_path: Path) -> None:
    """재검토 #5 — 한 응답 안에서 KMZ 높이 모드와 계약 altitudeReference 가 같은
    값이어야 한다(F1 의 실제 위험: 두 산출물의 수직기준 무음 이탈)."""
    import xml.etree.ElementTree as ET

    ns = {"kml": "http://www.opengis.net/kml/2.2", "wpml": "http://www.dji.com/wpmz/1.0.2"}
    client, _registry = _client(tmp_path)
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


def test_takeoff_security_height_exceeding_envelope_rejected(tmp_path: Path) -> None:
    """P1 반증 — maxAltitudeM=120 계약 + takeoffSecurityHeightM=1500 요청은 이전엔
    조용히 201 로 발급되던 어긋난 쌍이다(이륙 안전고도가 계약 봉투 밖)."""
    client, _registry = _client(tmp_path)
    request = _plan_request()
    request["wayline"]["takeoffSecurityHeightM"] = 1500.0

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 422
    assert "TAKEOFF_HEIGHT_EXCEEDS_ENVELOPE" in response.json()["detail"]


def test_takeoff_security_height_below_minimum_rejected(tmp_path: Path) -> None:
    client, _registry = _client(tmp_path)
    request = _plan_request()
    request["wayline"]["takeoffSecurityHeightM"] = 1.0

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 422
    assert "TAKEOFF_HEIGHT_BELOW_MINIMUM" in response.json()["detail"]


# ── B. 짝 식별자 (P2 — ADR-KSI-007 '동일 site_frame·policy_version 짝'의 실체화) ──


def test_pair_manifest_identifiers_are_deterministic_and_cross_consistent(tmp_path: Path) -> None:
    """P2 반증 — kmzSha256 이 응답 KMZ 재해시와 일치하고, KMZ 안 pair manifest 의
    contractPayloadSha256 이 **ADR-KSI-002 문서화 정규화**(canonical_payload_bytes:
    signature 제외·ensure_ascii=False·sha256:<hex>)로 재현되며 — 독자 정규화가
    아니어야 비-Python 검증기가 ADR 만 보고 짝 검증을 재현할 수 있다(재검증 P2) —
    perimeter 는 plannedCoverageRatio 가 null 이다."""
    client, _registry = _client(tmp_path)

    response = client.post("/v1/missions/plans", json=_plan_request())  # perimeter

    assert response.status_code == 201
    body = response.json()
    assert body["plannedCoverageRatio"] is None

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


def test_coverage_promise_above_measured_ratio_rejected(tmp_path: Path) -> None:
    """재검증 P2 반증 — 계약이 accessibleGeneralCoverage=1.0 을 약속(서명 대상)하는데
    같은 요청의 실측 커버가 1.0 미만이면, 그 어긋난 쌍은 발급되지 않는다(이륙고도
    게이트와 동일 클래스 — 이전엔 조용히 201 이었다)."""
    client, _registry = _client(tmp_path)
    request = _plan_request(mission_type="BASELINE_MAPPING", spacingM=20.0)
    request["aoi"] = {"vertices": _shear_aoi_vertices()}
    request["contract"]["accessibleGeneralCoverage"] = 1.0

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 422
    assert "COVERAGE_BELOW_CONTRACT_PROMISE" in response.json()["detail"]


def test_coverage_promise_at_default_accepts_imperfect_ratio(tmp_path: Path) -> None:
    """대조 — 같은 도형이라도 약속(기본 0.95)이 실측 이하면 정상 발급된다."""
    client, _registry = _client(tmp_path)
    request = _plan_request(mission_type="BASELINE_MAPPING", spacingM=20.0)
    request["aoi"] = {"vertices": _shear_aoi_vertices()}

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 201
    assert 0.95 <= response.json()["plannedCoverageRatio"] < 1.0


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


def test_lawnmower_plan_reports_planned_coverage_ratio(tmp_path: Path) -> None:
    client, _registry = _client(tmp_path)

    response = client.post(
        "/v1/missions/plans",
        json=_plan_request(mission_type="BASELINE_MAPPING", spacingM=20.0),
    )

    assert response.status_code == 201
    planned_coverage_ratio = response.json()["plannedCoverageRatio"]
    assert planned_coverage_ratio is not None
    assert 0.0 <= planned_coverage_ratio <= 1.0


# ── D. allowedVolumes=[] 거부 (W1 생성기 게이트) ─────────────────────────────


def test_lawnmower_rejects_empty_allowed_volumes(tmp_path: Path) -> None:
    client, _registry = _client(tmp_path)
    request = _plan_request(mission_type="BASELINE_MAPPING", spacingM=20.0)
    request["contract"]["flightEnvelope"]["allowedVolumes"] = []

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 422
    assert "EMPTY_ALLOWED_VOLUMES" in response.json()["detail"]


def test_perimeter_rejects_empty_allowed_volumes(tmp_path: Path) -> None:
    client, _registry = _client(tmp_path)
    request = _plan_request()
    request["contract"]["flightEnvelope"]["allowedVolumes"] = []

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 422
    assert "EMPTY_ALLOWED_VOLUMES" in response.json()["detail"]


# ── F.3 전 와이어 camelCase 통합 테스트 ──────────────────────────────────────


def test_pure_camelcase_wire_body_is_accepted(tmp_path: Path) -> None:
    """와이어 전체가 camelCase 여도 통과한다(W1 의 AreaOfInterest camelCase 별칭
    전제 — aoi.vertices[].latDeg/lonDeg)."""
    client, _registry = _client(tmp_path)
    request = _plan_request()
    request["aoi"] = {"vertices": _rect_aoi_vertices_camel()}

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 201


# ── E. 진행방향 촬영 간격 (독립 재검토 P1-1 — 게이트·배선이 무테스트였다) ────


def test_lawnmower_without_capture_interval_is_rejected(tmp_path: Path) -> None:
    """[핵심] 매핑 임무는 촬영 간격 없이는 발급되지 않는다.

    이 테스트가 없으면 fail-closed 블록을 통째로 지워도 스위트가 초록이다
    (실제로 변이 실험에서 그랬다) — 전방 중첩 0 결함이 조용히 되돌아온다.
    """
    client, _registry = _client(tmp_path)

    response = client.post(
        "/v1/missions/plans",
        json=_plan_request(
            mission_type="BASELINE_MAPPING", spacingM=20.0, captureIntervalM=None
        ),
    )

    assert response.status_code == 422
    assert "captureIntervalM" in response.json()["detail"]


def test_capture_interval_changes_issued_waypoint_count(tmp_path: Path) -> None:
    """[핵심] 촬영 간격이 실제 발급 산출물에 도달한다 — 배선 회귀 고정.

    간격을 좁히면 웨이포인트가 늘어야 한다. 이 단언이 없으면 생성기 호출에서
    capture_interval_m 인자를 빼도(스캔선당 2점으로 되돌아가도) 아무도 모른다.
    """
    client, _registry = _client(tmp_path)

    def issue(mission_id: str, interval: float) -> int:
        request = _plan_request(
            mission_type="BASELINE_MAPPING", spacingM=20.0, captureIntervalM=interval
        )
        request["contract"]["missionId"] = mission_id
        response = client.post("/v1/missions/plans", json=request)
        assert response.status_code == 201, response.text
        return int(response.json()["waypointCount"])

    coarse = issue("mission-coarse", 20.0)
    fine = issue("mission-fine", 5.0)

    assert fine > coarse, f"간격을 좁혔는데 웨이포인트가 늘지 않았다({coarse} → {fine})"
    # 스캔선당 2점(끝점만)이면 선 수의 2배가 상한이다 — 실제로 채워졌음을 고정한다.
    assert coarse > 2 * 6, f"채움이 일어나지 않았다(웨이포인트 {coarse})"


def test_capture_interval_wider_than_spacing_is_rejected(tmp_path: Path) -> None:
    """상한이 없으면 큰 값으로 전방 중첩 0 을 그대로 재현할 수 있다(재검토 P1-2)."""
    client, _registry = _client(tmp_path)

    response = client.post(
        "/v1/missions/plans",
        json=_plan_request(
            mission_type="BASELINE_MAPPING", spacingM=20.0, captureIntervalM=500.0
        ),
    )

    assert response.status_code == 422
    assert "capture_interval_m" in response.json()["detail"]


def test_retry_of_record_that_current_policy_cannot_reissue_is_409_not_500(
    tmp_path: Path,
) -> None:
    """[핵심] 정책이 바뀌어 저장된 요청을 재생성할 수 없으면 500 이 아니라 409 다.

    오늘 이전에 발급된 매핑 짝 레코드에는 captureIntervalM 이 없다 — 그 상태로
    같은 요청이 재도착하면 멱등 재발급이 생성기 예외로 죽어 "서버 버그"처럼
    보인다(독립 재검토 P2-7). 실제로는 정책이 달라진 것이므로 그 사실을 알린다.
    """
    # 옛 규칙으로 발급됐던 요청 — 진행방향 촬영 간격이 없다. 저장 형태는 서버가
    # 실제로 굳히는 것과 같아야 digest 가 맞는다(model_dump exclude_none).
    stale_request = MissionPlanRequest.model_validate(
        _plan_request(mission_type="BASELINE_MAPPING", spacingM=20.0, captureIntervalM=None)
    ).model_dump(by_alias=True, mode="json", exclude_none=True)

    private_key = Ed25519PrivateKey.generate()
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    site_store.register(
        "site-001",
        "Site 001",
        SiteFrame.model_validate(
            {
                "crs": "EPSG:5186",
                "verticalDatum": "KNGeoid2018",
                "unit": "meter",
                "transformVersion": "1.0.0",
            }
        ),
        actor="test-harness",
        now=datetime.now(UTC),
    )
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    assert (
        mission_store.record_issuance(
            MissionRecord(
                mission_id="mission-001",
                site_id="site-001",
                mission_type="BASELINE_MAPPING",
                artifact_kind="pair",
                contract={"schemaVersion": "1.2", "missionId": "mission-001"},
                kmz_sha256="deadbeef",
                route_pattern="lawnmower",
                waypoint_count=10,
                planned_coverage_ratio=1.0,
                issued_at=datetime.now(UTC),
                issued_by="do-1",
                plan_request=stale_request,
                plan_request_digest=sha256_digest(canonical_payload_bytes(stale_request)),
            )
        ).value
        == "RECORDED"
    )

    app = create_app(
        mission_signing_key=private_key,
        mission_signing_key_id="core-issuer-key-1",
        mission_store=mission_store,
        site_store=site_store,
        auth_registry=_auth_registry(),
    )
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_ISSUER_TOKEN}"})

    # 저장된(옛) 요청과 **같은** 요청이 재도착한 상황 — digest 가 일치해 멱등
    # 재발급 분기로 들어가지만, 현재 규칙으로는 그 요청을 다시 만들 수 없다.
    retry = client.post("/v1/missions/plans", json=stale_request)

    assert retry.status_code == 409, retry.text
    assert "현재 정책" in retry.json()["detail"]


# ── F. 카메라로 서버가 격자를 계산한다 (ADR-KSI-011 D2, 3순위) ───────────────


def _camera_params(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "sensorWidthMm": 13.2,
        "focalLengthMm": 8.8,
        "imageWidthPx": 5472,
        "imageHeightPx": 3648,
    }
    base.update(overrides)
    return base


def test_camera_lets_server_compute_spacing(tmp_path: Path) -> None:
    """[핵심] 카메라를 주면 간격을 안 줘도 발급되고, 계산 근거가 응답에 실린다.

    간격을 요청자가 적으면 서버는 그 값이 적정한지 판단할 근거가 없다 — 실제로
    40ha 가 사진 10장으로 발급됐다. 카메라를 받으면 그 판단이 가능해진다.
    """
    client, _registry = _client(tmp_path)
    request = _plan_request(mission_type="BASELINE_MAPPING")
    request["route"] = {"altitudeM": 40.0, "camera": _camera_params()}

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 201, response.text
    body = response.json()
    basis = body["gridBasis"]
    assert basis is not None, "계산 근거가 응답에 없다 — 왜 이 간격인지 검증 불가"
    # 고도 40m·표준 중복도(0.8/0.7) → 촬영폭 60×40m → 라인 18m·사진 8m 규모
    assert basis["spacingM"] == pytest.approx(18.0, rel=0.02)
    assert basis["captureIntervalM"] == pytest.approx(8.0, rel=0.02)
    assert basis["footprintAcrossM"] == pytest.approx(60.0, rel=0.02)
    assert body["waypointCount"] > 0


def test_camera_and_explicit_spacing_together_is_rejected(tmp_path: Path) -> None:
    """두 출처가 있으면 서버가 조용히 하나를 고르게 된다 — 그 선택을 하지 않는다."""
    client, _registry = _client(tmp_path)
    request = _plan_request(mission_type="BASELINE_MAPPING")
    request["route"] = {"altitudeM": 40.0, "camera": _camera_params(), "spacingM": 20.0}

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 422
    assert "함께 줄 수 없다" in response.json()["detail"]


def test_insufficient_overlap_is_rejected_at_api(tmp_path: Path) -> None:
    """재구성이 성립하지 않는 중복도는 발급 단계에서 막는다."""
    client, _registry = _client(tmp_path)
    request = _plan_request(mission_type="BASELINE_MAPPING")
    request["route"] = {
        "altitudeM": 40.0,
        "camera": _camera_params(frontOverlap=0.2, sideOverlap=0.7),
    }

    response = client.post("/v1/missions/plans", json=request)

    assert response.status_code == 422
    assert "front_overlap" in response.json()["detail"]


def test_explicit_spacing_still_works_without_camera(tmp_path: Path) -> None:
    """[비회귀] 카메라 없이 간격을 직접 주는 기존 경로는 그대로 동작한다."""
    client, _registry = _client(tmp_path)
    response = client.post(
        "/v1/missions/plans",
        json=_plan_request(mission_type="BASELINE_MAPPING", spacingM=20.0),
    )
    assert response.status_code == 201, response.text
    assert response.json()["gridBasis"] is None, "직접 지정인데 계산 근거가 실렸다"
