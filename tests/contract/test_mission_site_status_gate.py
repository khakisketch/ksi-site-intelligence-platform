"""임무 타입 × 현장상태 발급 게이트 (INV-052, ADR-KSI-014) — 결정론적 수용기준.

"먼저 매핑, 그 다음 사전지도 기반 자율" 독트린의 실제 강제 지점을 반증한다.
초점: ① `UNMAPPED` 현장에 `AUTONOMOUS_PATROL` 짝 발급이 거부되는가 ② 같은
조합이 계약 단독 발급(`/v1/missions/contracts`)에서도 거부되는가(우회로 폐쇄)
③ `BASELINE_MAPPING`은 `UNMAPPED`에서 정상 발급되는가(기존 흐름 비파괴) ④
매핑이 끝난 상태에서 `AUTONOMOUS_PATROL`이 정상 발급되는가 ⑤ 등록되지 않은
현장 ID로는 발급되지 않는가. 표 자체의 근거는
`packages/domain/src/ksi_domain/mission_gating.py` 모듈 docstring이 SSOT다.
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _site_lifecycle import advance_site_status  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionStore
from ksi_core.sites import SiteStore
from ksi_domain.enums import SiteStatus
from ksi_geo_core.frames import WGS84_EQUATORIAL_RADIUS_M
from ksi_mission_contracts.models import SiteFrame

_LAT0, _LON0 = 37.5000, 127.0000
_M_PER_DEG_LAT = math.radians(1.0) * WGS84_EQUATORIAL_RADIUS_M
_SITE_ID = "site-gate-001"
_ISSUER_TOKEN = "gate-test-issuer-token"  # noqa: S105 — 테스트 고정 토큰

_SITE_FRAME: dict[str, str] = {
    "crs": "EPSG:5186",
    "verticalDatum": "KNGeoid2018",
    "unit": "meter",
    "transformVersion": "1.0.0",
}


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_ISSUER_TOKEN),
                principal=Principal(
                    principal_id="do-gate-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            )
        ]
    )


def _rect_aoi_vertices() -> list[dict[str, float]]:
    dlat = 100.0 / _M_PER_DEG_LAT
    dlon = 200.0 / (_M_PER_DEG_LAT * math.cos(math.radians(_LAT0)))
    return [
        {"latDeg": _LAT0, "lonDeg": _LON0},
        {"latDeg": _LAT0, "lonDeg": _LON0 + dlon},
        {"latDeg": _LAT0 + dlat, "lonDeg": _LON0 + dlon},
        {"latDeg": _LAT0 + dlat, "lonDeg": _LON0},
    ]


def _client(
    tmp_path: Path,
    *,
    site_status: SiteStatus | None = SiteStatus.UNMAPPED,
    register_site: bool = True,
) -> tuple[TestClient, SiteStore]:
    """서명키 + mission_store + site_store + auth_registry 최소 조립.

    ``site_status=None`` 이면 site 를 아예 등록하지 않는다(수용기준 5 —
    등록되지 않은 현장 ID 로는 발급되지 않는다).
    """
    private_key = Ed25519PrivateKey.generate()
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    if register_site:
        site_store.register(
            _SITE_ID,
            "게이트 테스트 현장",
            SiteFrame.model_validate(_SITE_FRAME),
            actor="test-harness",
            now=datetime.now(UTC),
        )
        assert site_status is not None
        advance_site_status(site_store, _SITE_ID, site_status)
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))

    app = create_app(
        mission_signing_key=private_key,
        mission_signing_key_id="gate-test-key-1",
        mission_store=mission_store,
        site_store=site_store,
        auth_registry=_auth_registry(),
    )
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_ISSUER_TOKEN}"})
    return client, site_store


def _contract_request(
    mission_id: str, mission_type: str, *, site_id: str = _SITE_ID
) -> dict[str, Any]:
    return {
        "missionId": mission_id,
        "siteId": site_id,
        "missionType": mission_type,
        "siteFrame": _SITE_FRAME,
        "flightEnvelope": {
            "allowedVolumes": ["vol-1"],
            "excludedVolumes": [],
            "minAltitudeM": 5.0,
            "maxAltitudeM": 120.0,
        },
        "objectives": ["게이트 테스트"],
        "viewpointPolicyId": "vp-1",
        "riskPolicyPackId": "risk-1",
        "fallbackPolicyId": "fb-1",
        "capturePolicyId": "cap-1",
    }


def _plan_request(mission_id: str, mission_type: str, **route_overrides: Any) -> dict[str, Any]:
    route: dict[str, Any] = {"altitudeM": 40.0}
    route.update(route_overrides)
    if "spacingM" in route and "captureIntervalM" not in route_overrides:
        route["captureIntervalM"] = 15.0
    return {
        "contract": _contract_request(mission_id, mission_type),
        "aoi": {"vertices": _rect_aoi_vertices()},
        "route": route,
        "drone": {"droneEnumValue": 99, "droneSubEnumValue": 0, "payloadEnumValue": 65534},
        "wayline": {
            "autoFlightSpeedMs": 5.0,
            "takeoffSecurityHeightM": 20.0,
            "globalTransitionalSpeedMs": 10.0,
        },
    }


# ── 수용기준 1 — UNMAPPED 현장에 AUTONOMOUS_PATROL 짝 발급 거부 ─────────────


def test_autonomous_patrol_pair_issuance_rejected_at_unmapped_site(tmp_path: Path) -> None:
    client, _store = _client(tmp_path, site_status=SiteStatus.UNMAPPED)

    response = client.post(
        "/v1/missions/plans", json=_plan_request("mission-ap-1", "AUTONOMOUS_PATROL")
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "MISSION_TYPE_SITE_STATUS_MISMATCH"


# ── 수용기준 2 — 같은 조합이 계약 단독 발급에서도 거부(우회로 폐쇄) ─────────


def test_autonomous_patrol_contract_only_issuance_rejected_at_unmapped_site(
    tmp_path: Path,
) -> None:
    client, _store = _client(tmp_path, site_status=SiteStatus.UNMAPPED)

    response = client.post(
        "/v1/missions/contracts", json=_contract_request("mission-ap-2", "AUTONOMOUS_PATROL")
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "MISSION_TYPE_SITE_STATUS_MISMATCH"


# ── 수용기준 3 — BASELINE_MAPPING 은 UNMAPPED 에서 정상 발급(기존 흐름 비파괴) ──


def test_baseline_mapping_still_issues_at_unmapped_site_pair(tmp_path: Path) -> None:
    client, _store = _client(tmp_path, site_status=SiteStatus.UNMAPPED)

    response = client.post(
        "/v1/missions/plans",
        json=_plan_request("mission-bm-1", "BASELINE_MAPPING", spacingM=20.0),
    )

    assert response.status_code == 201, response.text


def test_baseline_mapping_still_issues_at_unmapped_site_contract_only(tmp_path: Path) -> None:
    client, _store = _client(tmp_path, site_status=SiteStatus.UNMAPPED)

    response = client.post(
        "/v1/missions/contracts", json=_contract_request("mission-bm-2", "BASELINE_MAPPING")
    )

    assert response.status_code == 201, response.text


# ── 수용기준 4 — 매핑이 끝난 상태에서 AUTONOMOUS_PATROL 정상 발급 ───────────


def test_autonomous_patrol_issues_at_patrol_ready_site_pair(tmp_path: Path) -> None:
    client, _store = _client(tmp_path, site_status=SiteStatus.PATROL_READY)

    response = client.post(
        "/v1/missions/plans", json=_plan_request("mission-ap-3", "AUTONOMOUS_PATROL")
    )

    assert response.status_code == 201, response.text


def test_autonomous_patrol_issues_at_patrol_ready_site_contract_only(tmp_path: Path) -> None:
    client, _store = _client(tmp_path, site_status=SiteStatus.PATROL_READY)

    response = client.post(
        "/v1/missions/contracts", json=_contract_request("mission-ap-4", "AUTONOMOUS_PATROL")
    )

    assert response.status_code == 201, response.text


def test_autonomous_patrol_also_issues_at_provisional_autonomy_and_patrol_active(
    tmp_path: Path,
) -> None:
    """PATROL_READY 하나만이 아니라 허용표의 다른 두 상태도 실제로 통과한다."""
    for status in (SiteStatus.PROVISIONAL_AUTONOMY, SiteStatus.PATROL_ACTIVE):
        client, _store = _client(tmp_path / status.value, site_status=status)
        response = client.post(
            "/v1/missions/contracts",
            json=_contract_request(f"mission-ap-{status.value.lower()}", "AUTONOMOUS_PATROL"),
        )
        assert response.status_code == 201, f"{status.value}: {response.text}"


def test_autonomous_patrol_rejected_at_model_stale(tmp_path: Path) -> None:
    """MODEL_STALE 은 모델이 있지만 낡았다 — 재검증을 우회해 순찰을 내보내지 않는다."""
    client, _store = _client(tmp_path, site_status=SiteStatus.MODEL_STALE)

    response = client.post(
        "/v1/missions/contracts", json=_contract_request("mission-ap-stale", "AUTONOMOUS_PATROL")
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "MISSION_TYPE_SITE_STATUS_MISMATCH"


# ── 수용기준 5 — 등록되지 않은 현장 ID 로는 발급되지 않는다 ─────────────────


def test_unregistered_site_id_rejected_for_both_endpoints(tmp_path: Path) -> None:
    """site 를 아예 등록하지 않은 조립 — UNKNOWN_SITE 가 이 게이트보다 먼저 걸린다."""
    client, _store = _client(tmp_path, register_site=False)

    plan_response = client.post(
        "/v1/missions/plans", json=_plan_request("mission-unk-1", "AUTONOMOUS_PATROL")
    )
    assert plan_response.status_code == 422, plan_response.text
    assert plan_response.json()["detail"] == "UNKNOWN_SITE"

    contract_response = client.post(
        "/v1/missions/contracts", json=_contract_request("mission-unk-2", "AUTONOMOUS_PATROL")
    )
    assert contract_response.status_code == 422, contract_response.text
    assert contract_response.json()["detail"] == "UNKNOWN_SITE"


def test_unregistered_site_id_rejected_even_for_baseline_mapping(tmp_path: Path) -> None:
    """미매핑 계열(BASELINE_MAPPING)도 site 자체가 없으면 여전히 거부된다 —
    이 게이트가 site 존재 확인을 우회하는 새 구멍이 되지 않는다."""
    client, _store = _client(tmp_path, register_site=False)

    response = client.post(
        "/v1/missions/contracts", json=_contract_request("mission-unk-3", "BASELINE_MAPPING")
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "UNKNOWN_SITE"


# ── 보강 — SUSPENDED 는 임무 타입과 무관하게 전부 거부 ──────────────────────


def test_suspended_site_rejects_every_mission_type(tmp_path: Path) -> None:
    client, _store = _client(tmp_path, site_status=SiteStatus.SUSPENDED)

    for mission_type in ("BASELINE_MAPPING", "AUTONOMOUS_PATROL", "INCIDENT_SURVEY"):
        response = client.post(
            "/v1/missions/contracts",
            json=_contract_request(f"mission-susp-{mission_type.lower()}", mission_type),
        )
        assert response.status_code == 409, f"{mission_type}: {response.text}"
        assert response.json()["detail"] == "MISSION_TYPE_SITE_STATUS_MISMATCH"


# ── 보강 — INCIDENT_SURVEY 는 UNMAPPED 에서도 허용(판단이 갈리는 지점, ADR-KSI-014) ──


def test_incident_survey_allowed_at_unmapped_site(tmp_path: Path) -> None:
    client, _store = _client(tmp_path, site_status=SiteStatus.UNMAPPED)

    response = client.post(
        "/v1/missions/plans", json=_plan_request("mission-incident-1", "INCIDENT_SURVEY")
    )

    assert response.status_code == 201, response.text
