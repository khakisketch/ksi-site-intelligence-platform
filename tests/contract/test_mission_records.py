"""Mission 발급 영속·목록/이력 조회 계약 (ADR-KSI-008 §1/§3, ADR-KSI-007 짝 무결성).

수동 조립(``FastAPI()`` + ``mount_auth`` + ``mount_mission_issuance``/
``mount_mission_plans``(``mission_store``/``site_lookup`` 주입)+
``mount_mission_records``)으로 발급→durable 기록→조회 왕복을 검증한다. 초점:
① 발급 응답과 조회 응답의 계약 dict 가 정확 일치(INV-011, 재계산·재서명 없음)
② 재기동 복구 ③ mission_id 중복이 기존 레코드를 덮지 않음(replay 로 증명)
④ UNKNOWN_SITE 422 ⑤ journal 봉인 시 503+미기록(고아 발급 금지) ⑥ 401/403
(MISSIONS_ISSUE 없는 역할 발급 거부·VIEWER 조회 허용) ⑦ pair·contract 두
artifact_kind 모두 커버.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.coverage_reports import CoverageReportStore
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_issuance import mount_mission_issuance
from ksi_core.mission_plans import mount_mission_plans
from ksi_core.mission_records import (
    MissionIssuanceSequenceStore,
    MissionRecord,
    MissionSequenceRecoveryError,
    MissionStore,
    MissionStoreRecoveryError,
    SiteLookupResult,
    mount_mission_records,
)
from ksi_domain.enums import SiteStatus
from ksi_event_contracts.coverage_report import CoverageReport
from ksi_geo_core.frames import WGS84_EQUATORIAL_RADIUS_M
from ksi_mission_contracts.signing import canonical_payload_bytes, sha256_digest

_LAT0, _LON0 = 37.5000, 127.0000
_M_PER_DEG_LAT = math.radians(1.0) * WGS84_EQUATORIAL_RADIUS_M
_KEY_ID = "core-issuer-key-1"

_FIELD_OPERATOR_TOKEN = "field-operator-token"  # noqa: S105 — 테스트 고정 토큰
_VIEWER_TOKEN = "viewer-token"  # noqa: S105

# 등록된 site 의 canonical siteFrame + 상태 — _contract_request 의 siteFrame 과
# frame 이 동일해야 발급이 SITE_FRAME_MISMATCH 없이 통과한다(짝 무결성 대조).
# status 는 PATROL_READY 로 고정한다 — 이 파일의 초점은 발급 영속·조회 왕복이지
# 임무타입×현장상태 게이트(INV-052) 자체가 아니고, 이 파일 전체가 기본
# missionType(AUTONOMOUS_PATROL)을 공유하므로 그 타입이 발급 가능한 상태를
# 골랐다(게이트 반증은 `test_mission_site_status_gate.py` 가 별도로 맡는다).
_REGISTERED_SITES: dict[str, SiteLookupResult] = {
    "site-001": SiteLookupResult(
        site_frame={
            "crs": "EPSG:5186",
            "verticalDatum": "KNGeoid2018",
            "unit": "meter",
            "transformVersion": "1.0.0",
        },
        status=SiteStatus.PATROL_READY,
    )
}


class _MutableSiteLookup:
    """``site_lookup`` 콜백이지만 status 를 나중에 바꿀 수 있다(독립 재검토 D1 재현용).

    ``_REGISTERED_SITES`` 는 이 파일 전체가 공유하는 상태 고정 dict라, "발급 이후
    site 상태가 전이된다"는 시나리오(멱등 재발급이 게이트보다 나중에 걸리던 버그)를
    재현할 수 없었다 — 이 클래스가 그 재현을 가능하게 한다.
    """

    def __init__(self, site_frame: dict[str, str], status: SiteStatus) -> None:
        self._site_frame = site_frame
        self._status = status

    def __call__(self, site_id: str) -> SiteLookupResult | None:
        if site_id != "site-001":
            return None
        return SiteLookupResult(site_frame=self._site_frame, status=self._status)

    def set_status(self, status: SiteStatus) -> None:
        self._status = status


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_FIELD_OPERATOR_TOKEN),
                principal=Principal(
                    principal_id="do-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="vw-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                ),
            ),
        ]
    )


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _post_json_with_lone_surrogate(
    client: TestClient, url: str, payload: dict[str, Any], *, headers: dict[str, str]
) -> Any:
    """lone surrogate 를 포함한 payload 를 서버까지 보낸다.

    httpx 의 ``json=`` 파라미터는 ``ensure_ascii=False`` 로 인코딩해 lone
    surrogate 를 만나면 **클라이언트 쪽**에서 ``UnicodeEncodeError`` 로 죽는다
    (서버에 도달하기 전) — 실 와이어에서는 JSON 의 ``\\uXXXX`` escape 로 도착해
    ``json.loads`` 가 그대로 파이썬 str 안의 lone surrogate 로 복원한다. 그
    실제 경로를 재현하려면 ``ensure_ascii=True`` 로 직접 직렬화(순수 ASCII
    바이트, encode 실패 없음)한 뒤 ``content=`` 로 보낸다.
    """
    body = json.dumps(payload, ensure_ascii=True).encode("ascii")
    return client.post(
        url, content=body, headers={**headers, "content-type": "application/json"}
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


def _contract_request(
    mission_id: str = "mission-001", site_id: str = "site-001", **overrides: Any
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "missionId": mission_id,
        "siteId": site_id,
        "missionType": "AUTONOMOUS_PATROL",
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
    }
    base.update(overrides)
    return base


def _plan_request(
    mission_id: str = "mission-001", site_id: str = "site-001", **contract_overrides: Any
) -> dict[str, Any]:
    return {
        "contract": _contract_request(mission_id=mission_id, site_id=site_id, **contract_overrides),
        "aoi": {"vertices": _rect_aoi_vertices()},
        # AUTONOMOUS_PATROL(이 파일의 기본 missionType)은 Spatial Refresh Backbone
        # 이 필수다(MASTER_PRD §15.2). 50.0 은 altitudeM=40.0 의 운용 상한
        # (1.5×40=60m, risk patrol-capture-interval-direct-no-quality-floor) 안 —
        # 500.0(상한 도입 전 "웨이포인트 안 늘어남" 편의값)은 더 이상 허용되지 않는다.
        "route": {"altitudeM": 40.0, "captureIntervalM": 50.0},
        "drone": {"droneEnumValue": 99, "droneSubEnumValue": 0, "payloadEnumValue": 65534},
        "wayline": {
            "autoFlightSpeedMs": 5.0,
            "takeoffSecurityHeightM": 20.0,
            "globalTransitionalSpeedMs": 10.0,
        },
    }


def _open_store(path: Path) -> tuple[DurableJournal, MissionStore]:
    journal = DurableJournal(path)
    return journal, MissionStore(journal)


def _build_app(
    *,
    private_key: Ed25519PrivateKey,
    mission_store: MissionStore,
    site_lookup: Callable[[str], SiteLookupResult | None] | None = None,
    coverage_report_store: CoverageReportStore | None = None,
) -> FastAPI:
    resolved_lookup = (
        site_lookup if site_lookup is not None else (lambda site_id: _REGISTERED_SITES.get(site_id))
    )
    app = FastAPI()
    mount_auth(app, _auth_registry())
    mount_mission_issuance(
        app,
        private_key=private_key,
        key_id=_KEY_ID,
        mission_store=mission_store,
        site_lookup=resolved_lookup,
    )
    mount_mission_plans(
        app,
        private_key=private_key,
        key_id=_KEY_ID,
        mission_store=mission_store,
        site_lookup=resolved_lookup,
    )
    mount_mission_records(
        app, mission_store=mission_store, coverage_report_store=coverage_report_store
    )
    return app


def _client(tmp_path: Path, **kwargs: Any) -> tuple[TestClient, MissionStore, DurableJournal]:
    private_key = Ed25519PrivateKey.generate()
    journal, store = _open_store(tmp_path / "missions.jsonl")
    app = _build_app(private_key=private_key, mission_store=store, **kwargs)
    return TestClient(app), store, journal


# ── ① 발급→조회 왕복, 계약 dict 정확 일치(INV-011) — pair ──────────────────


def test_pair_issuance_round_trips_through_query_endpoints(tmp_path: Path) -> None:
    client, _store, journal = _client(tmp_path)

    issue = client.post(
        "/v1/missions/plans",
        json=_plan_request(),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert issue.status_code == 201
    issued = issue.json()

    listing = client.get(
        "/v1/missions", params={"siteId": "site-001"}, headers=_auth_header(_VIEWER_TOKEN)
    )
    assert listing.status_code == 200
    entries = listing.json()
    assert len(entries) == 1
    assert entries[0]["missionId"] == "mission-001"
    assert entries[0]["artifactKind"] == "pair"
    assert entries[0]["kmzSha256"] == issued["kmzSha256"]
    assert entries[0]["routePattern"] == issued["routePattern"]
    assert entries[0]["waypointCount"] == issued["waypointCount"]
    assert entries[0]["plannedCoverageRatio"] == issued["plannedCoverageRatio"]

    # 존재하지 않는 site 로 필터링하면 빈 목록.
    empty = client.get(
        "/v1/missions", params={"siteId": "no-such-site"}, headers=_auth_header(_VIEWER_TOKEN)
    )
    assert empty.json() == []

    detail = client.get("/v1/missions/mission-001", headers=_auth_header(_VIEWER_TOKEN))
    assert detail.status_code == 200
    assert detail.json()["missionId"] == "mission-001"

    contract = client.get(
        "/v1/missions/mission-001/contract", headers=_auth_header(_VIEWER_TOKEN)
    )
    assert contract.status_code == 200
    assert contract.json() == issued["contract"], (
        "저장된 계약이 발급 응답과 정확 일치해야 한다(INV-011)"
    )

    journal.close()


# ── ① contract-only 경로도 동일하게 왕복(두 artifact_kind 모두 커버) ────────


def test_contract_only_issuance_round_trips(tmp_path: Path) -> None:
    client, _store, journal = _client(tmp_path)

    issue = client.post(
        "/v1/missions/contracts",
        json=_contract_request(mission_id="mission-c1"),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert issue.status_code == 201
    issued_contract = issue.json()

    detail = client.get("/v1/missions/mission-c1", headers=_auth_header(_VIEWER_TOKEN))
    assert detail.status_code == 200
    body = detail.json()
    assert body["artifactKind"] == "contract"
    assert body["kmzSha256"] is None
    assert body["routePattern"] is None
    assert body["waypointCount"] is None
    assert body["plannedCoverageRatio"] is None

    contract = client.get(
        "/v1/missions/mission-c1/contract", headers=_auth_header(_VIEWER_TOKEN)
    )
    assert contract.status_code == 200
    assert contract.json() == issued_contract

    journal.close()


_PLAN_REQUEST_STUB: dict[str, Any] = {"route": {"altitudeM": 40.0}, "marker": "replay-fixture"}


# ── ② 재기동 복구 ────────────────────────────────────────────────────────


def test_mission_store_replay_recovers_after_restart(tmp_path: Path) -> None:
    journal_path = tmp_path / "missions.jsonl"
    journal, store = _open_store(journal_path)

    record_a = MissionRecord(
        mission_id="mission-a",
        site_id="site-001",
        mission_type="AUTONOMOUS_PATROL",
        artifact_kind="contract",
        contract={"schemaVersion": "1.2", "missionId": "mission-a"},
        kmz_sha256=None,
        route_pattern=None,
        waypoint_count=None,
        planned_coverage_ratio=None,
        issued_at=datetime.now(UTC),
        issued_by="do-1",
    )
    record_b = MissionRecord(
        mission_id="mission-b",
        site_id="site-002",
        mission_type="BASELINE_MAPPING",
        artifact_kind="pair",
        contract={"schemaVersion": "1.2", "missionId": "mission-b"},
        kmz_sha256="deadbeef",
        route_pattern="lawnmower",
        waypoint_count=42,
        planned_coverage_ratio=0.97,
        issued_at=datetime.now(UTC),
        issued_by="do-1",
        # 짝 레코드는 KMZ 재생성 입력을 반드시 들고 있다(멱등 재발급이 기대는
        # 불변식) — 재생 경로가 이제 그것과 digest 정합을 함께 강제한다.
        plan_request=_PLAN_REQUEST_STUB,
        plan_request_digest=sha256_digest(canonical_payload_bytes(_PLAN_REQUEST_STUB)),
    )
    assert store.record_issuance(record_a).value == "RECORDED"
    assert store.record_issuance(record_b).value == "RECORDED"
    journal.close()

    reborn_journal, reborn_store = _open_store(journal_path)
    assert reborn_store.get("mission-a") == record_a
    assert reborn_store.get("mission-b") == record_b
    expected_order = sorted([record_a, record_b], key=lambda r: (r.issued_at, r.mission_id))
    assert reborn_store.list() == expected_order
    reborn_journal.close()


# ── ①-보강 재검토 P2 item① — journal 오염은 fail-closed 로 기동을 거부한다 ──


def test_mission_store_rejects_duplicate_mission_id_found_in_journal_on_replay(
    tmp_path: Path,
) -> None:
    """journal 자체에 (버그·수동조작으로) 같은 missionId 가 두 번 기록되면 재생이
    조용히 두 번째로 덮어쓰지 않고 기동을 거부한다(SiteStore 의
    SiteStoreRecoveryError 와 대칭)."""
    journal_path = tmp_path / "missions.jsonl"
    journal = DurableJournal(journal_path)
    raw = {
        "missionId": "mission-dup-journal",
        "siteId": "site-001",
        "missionType": "AUTONOMOUS_PATROL",
        "artifactKind": "contract",
        "contract": {"schemaVersion": "1.2"},
        "kmzSha256": None,
        "routePattern": None,
        "waypointCount": None,
        "plannedCoverageRatio": None,
        "issuedAt": datetime.now(UTC).isoformat(),
        "issuedBy": "do-1",
    }
    journal.append(raw)
    journal.append(raw)  # 같은 missionId 재기록 — 오염
    journal.close()

    reopened = DurableJournal(journal_path)
    with pytest.raises(MissionStoreRecoveryError):
        MissionStore(reopened)
    reopened.close()


def test_mission_store_rejects_invalid_artifact_kind_on_replay(tmp_path: Path) -> None:
    journal_path = tmp_path / "missions.jsonl"
    journal = DurableJournal(journal_path)
    journal.append(
        {
            "missionId": "mission-bad-kind",
            "siteId": "site-001",
            "missionType": "AUTONOMOUS_PATROL",
            "artifactKind": "not-a-kind",
            "contract": {"schemaVersion": "1.2"},
            "kmzSha256": None,
            "routePattern": None,
            "waypointCount": None,
            "plannedCoverageRatio": None,
            "issuedAt": datetime.now(UTC).isoformat(),
            "issuedBy": "do-1",
        }
    )
    journal.close()

    reopened = DurableJournal(journal_path)
    with pytest.raises(MissionStoreRecoveryError):
        MissionStore(reopened)
    reopened.close()


def test_mission_store_rejects_non_dict_contract_on_replay(tmp_path: Path) -> None:
    journal_path = tmp_path / "missions.jsonl"
    journal = DurableJournal(journal_path)
    journal.append(
        {
            "missionId": "mission-bad-contract",
            "siteId": "site-001",
            "missionType": "AUTONOMOUS_PATROL",
            "artifactKind": "contract",
            "contract": "not-a-dict",
            "kmzSha256": None,
            "routePattern": None,
            "waypointCount": None,
            "plannedCoverageRatio": None,
            "issuedAt": datetime.now(UTC).isoformat(),
            "issuedBy": "do-1",
        }
    )
    journal.close()

    reopened = DurableJournal(journal_path)
    with pytest.raises(MissionStoreRecoveryError):
        MissionStore(reopened)
    reopened.close()


# ── ③ mission_id 중복은 기존 레코드를 덮지 않는다(replay 로 증명) ──────────


def test_mission_store_duplicate_mission_id_does_not_overwrite_and_survives_restart(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "missions.jsonl"
    journal, store = _open_store(journal_path)

    original = MissionRecord(
        mission_id="mission-dup",
        site_id="site-001",
        mission_type="AUTONOMOUS_PATROL",
        artifact_kind="contract",
        contract={"schemaVersion": "1.2", "missionId": "mission-dup", "note": "original"},
        kmz_sha256=None,
        route_pattern=None,
        waypoint_count=None,
        planned_coverage_ratio=None,
        issued_at=datetime.now(UTC),
        issued_by="do-1",
    )
    impostor = MissionRecord(
        mission_id="mission-dup",
        site_id="site-999",
        mission_type="INCIDENT_SURVEY",
        artifact_kind="pair",
        contract={"schemaVersion": "1.2", "missionId": "mission-dup", "note": "impostor"},
        kmz_sha256="not-original",
        route_pattern="perimeter",
        waypoint_count=5,
        planned_coverage_ratio=None,
        issued_at=datetime.now(UTC),
        issued_by="do-2",
    )

    assert store.record_issuance(original).value == "RECORDED"
    assert store.record_issuance(impostor).value == "MISSION_ID_CONFLICT"
    assert store.get("mission-dup") == original
    assert len(store.list()) == 1
    journal.close()

    reborn_journal, reborn_store = _open_store(journal_path)
    assert reborn_store.get("mission-dup") == original, (
        "impostor 가 journal 에 남았다면 replay 가 덮어썼을 것"
    )
    assert len(reborn_store.list()) == 1
    reborn_journal.close()


def test_duplicate_mission_id_with_different_request_via_api_returns_409(
    tmp_path: Path,
) -> None:
    """서로 다른 요청(다른 digest)이 같은 missionId 를 재사용하면 여전히 409 —
    멱등 재반환(재검토 P2 item③)은 '동일 요청의 재시도'로만 한정된다."""
    client, _store, journal = _client(tmp_path)

    first = client.post(
        "/v1/missions/plans", json=_plan_request(), headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert first.status_code == 201

    second_request = _plan_request()
    second_request["route"]["altitudeM"] = 41.0  # 원 요청과 다른 digest
    second = client.post(
        "/v1/missions/plans", json=second_request, headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "MISSION_ID_CONFLICT"

    journal.close()


def test_duplicate_mission_id_via_contracts_endpoint_still_returns_409(tmp_path: Path) -> None:
    """contract-only 발급은 멱등 재발급 대상이 아니다(KMZ 가 없어 유실 위험도 없다) —
    동일 요청 재시도라도 여전히 409."""
    client, _store, journal = _client(tmp_path)

    first = client.post(
        "/v1/missions/contracts",
        json=_contract_request(mission_id="mission-contract-dup"),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert first.status_code == 201

    second = client.post(
        "/v1/missions/contracts",
        json=_contract_request(mission_id="mission-contract-dup"),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "MISSION_ID_CONFLICT"

    journal.close()


def test_identical_retry_of_pair_issuance_is_idempotent(tmp_path: Path) -> None:
    """재검토 P2 item③ 폐쇄 — 201 응답이 네트워크에서 유실돼도, 같은 missionId+
    동일 요청 digest 재시도는 KMZ 를 재생성해 그대로 재반환한다(짝의 절반이
    영구 소실되지 않는다). ``kmzBase64`` 실 바이트 비교로 재생성 결정성도
    함께 증명한다(build_kmz 계열은 시각·난수·UUID 의존이 없다)."""
    client, store, journal = _client(tmp_path)
    request_body = _plan_request()

    first = client.post(
        "/v1/missions/plans", json=request_body, headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert first.status_code == 201
    first_body = first.json()

    retry = client.post(
        "/v1/missions/plans", json=request_body, headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert retry.status_code == 200, "동일 요청 재시도는 새 레코드를 만들지 않고 멱등 200"
    retry_body = retry.json()

    assert retry_body["contract"] == first_body["contract"]
    assert retry_body["kmzSha256"] == first_body["kmzSha256"]
    assert retry_body["kmzBase64"] == first_body["kmzBase64"], (
        "재생성 KMZ 바이트가 원본과 동일해야 한다(결정성 — sha256 뿐 아니라 실 바이트로 증명)"
    )
    assert retry_body["routePattern"] == first_body["routePattern"]
    assert retry_body["waypointCount"] == first_body["waypointCount"]
    assert retry_body["plannedCoverageRatio"] == first_body["plannedCoverageRatio"]

    # journal 에는 한 건만 남는다 — 재시도가 새 레코드를 append 하지 않는다.
    assert len(store.list()) == 1

    journal.close()


# ── ⑫ 독립 재검토 D1 — 멱등 재발급이 게이트보다 먼저다 ─────────────────────

_D1_SITE_FRAME: dict[str, str] = {
    "crs": "EPSG:5186",
    "verticalDatum": "KNGeoid2018",
    "unit": "meter",
    "transformVersion": "1.0.0",
}


def _d1_plan_request(mission_id: str, **route_overrides: Any) -> dict[str, Any]:
    route: dict[str, Any] = {"altitudeM": 40.0, "spacingM": 20.0, "captureIntervalM": 15.0}
    route.update(route_overrides)
    return {
        "contract": _contract_request(mission_id=mission_id, missionType="BASELINE_MAPPING"),
        "aoi": {"vertices": _rect_aoi_vertices()},
        "route": route,
        "drone": {"droneEnumValue": 99, "droneSubEnumValue": 0, "payloadEnumValue": 65534},
        "wayline": {
            "autoFlightSpeedMs": 5.0,
            "takeoffSecurityHeightM": 20.0,
            "globalTransitionalSpeedMs": 10.0,
        },
    }


def test_idempotent_retry_survives_site_status_transition_away_from_gate_pair(
    tmp_path: Path,
) -> None:
    """[D1 회귀] UNMAPPED 현장에 BASELINE_MAPPING 짝 발급 201 → 응답 유실 가정 →
    현장이 BASELINE_MAPPING 으로 정상 전이(그 상태에서는 BASELINE_MAPPING 이
    더는 허용되지 않는다, ``mission_gating._MAPPING_FROM_SCRATCH ==
    {UNMAPPED, REMAP_REQUIRED}``) → 클라이언트가 동일 요청(같은 digest)으로
    재시도 → 여전히 멱등 200 이어야 한다. 인가는 발급 시점에 이미 내려져
    원장에 기록됐다 — 게이트가 먼저 걸려 이미 기록된 임무에 사실과 다른
    사유(409 MISSION_TYPE_SITE_STATUS_MISMATCH)를 주면 안 된다(수정 전에는
    이 재시도가 409 였다 — precheck_issuance 가 게이트를 mission_id 충돌보다
    먼저 봤기 때문)."""
    lookup = _MutableSiteLookup(site_frame=_D1_SITE_FRAME, status=SiteStatus.UNMAPPED)
    client, store, journal = _client(tmp_path, site_lookup=lookup)
    request_body = _d1_plan_request("mission-d1")

    first = client.post(
        "/v1/missions/plans", json=request_body, headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert first.status_code == 201, first.text
    first_body = first.json()

    lookup.set_status(SiteStatus.BASELINE_MAPPING)

    retry = client.post(
        "/v1/missions/plans", json=request_body, headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert retry.status_code == 200, (
        f"게이트가 멱등 재반환보다 먼저 걸리면 안 된다: {retry.status_code} {retry.text}"
    )
    retry_body = retry.json()
    assert retry_body["contract"] == first_body["contract"]
    assert retry_body["kmzSha256"] == first_body["kmzSha256"]

    # journal 에는 한 건만 남는다 — 재시도가 새 레코드를 append 하지 않는다.
    assert len(store.list()) == 1

    journal.close()


def test_different_digest_retry_after_site_status_transition_still_conflicts(
    tmp_path: Path,
) -> None:
    """[D1 보강] 위와 같은 전이 상황에서도 **다른** 요청(다른 digest)이 같은
    missionId 를 재사용하면 여전히 409 MISSION_ID_CONFLICT 다 — 멱등 재반환이
    '아무 재시도나 통과'로 퇴화하지 않는다."""
    lookup = _MutableSiteLookup(site_frame=_D1_SITE_FRAME, status=SiteStatus.UNMAPPED)
    client, _store, journal = _client(tmp_path, site_lookup=lookup)
    request_body = _d1_plan_request("mission-d1b")

    first = client.post(
        "/v1/missions/plans", json=request_body, headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert first.status_code == 201, first.text

    lookup.set_status(SiteStatus.BASELINE_MAPPING)

    different_body = _d1_plan_request("mission-d1b", spacingM=21.0)
    retry = client.post(
        "/v1/missions/plans", json=different_body, headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert retry.status_code == 409, retry.text
    assert retry.json()["detail"] == "MISSION_ID_CONFLICT"

    journal.close()


def test_contract_only_retry_after_site_status_transition_reports_conflict_not_gate_mismatch(
    tmp_path: Path,
) -> None:
    """[D1 보강 — 계약 단독 발급] contract-only 발급은 멱등 재반환 대상이 아니므로
    (``mission_issuance.py`` 에 그 경로가 없다) 재시도는 여전히 409지만, 그 사유가
    이제는 정확하다 — 게이트가 먼저 걸려 "현재 상태에서 허용 안 됨"이라 말하지
    않고, mission_id 가 이미 쓰였다는 사실(MISSION_ID_CONFLICT)을 말한다."""
    lookup = _MutableSiteLookup(site_frame=_D1_SITE_FRAME, status=SiteStatus.UNMAPPED)
    client, _store, journal = _client(tmp_path, site_lookup=lookup)

    first = client.post(
        "/v1/missions/contracts",
        json=_contract_request(mission_id="mission-d1c", missionType="BASELINE_MAPPING"),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert first.status_code == 201, first.text

    lookup.set_status(SiteStatus.BASELINE_MAPPING)

    retry = client.post(
        "/v1/missions/contracts",
        json=_contract_request(mission_id="mission-d1c", missionType="BASELINE_MAPPING"),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert retry.status_code == 409, retry.text
    assert retry.json()["detail"] == "MISSION_ID_CONFLICT", (
        "게이트가 먼저 걸리면 MISSION_TYPE_SITE_STATUS_MISMATCH 가 되어 이미 기록된 "
        "임무에 사실과 다른 사유를 준다"
    )

    journal.close()


# ── ④ UNKNOWN_SITE 422 ──────────────────────────────────────────────────


def test_unknown_site_rejected_422_for_plans_and_contracts(tmp_path: Path) -> None:
    client, _store, journal = _client(tmp_path)

    plan_response = client.post(
        "/v1/missions/plans",
        json=_plan_request(site_id="no-such-site"),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert plan_response.status_code == 422
    assert plan_response.json()["detail"] == "UNKNOWN_SITE"

    contract_response = client.post(
        "/v1/missions/contracts",
        json=_contract_request(mission_id="mission-x", site_id="no-such-site"),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert contract_response.status_code == 422
    assert contract_response.json()["detail"] == "UNKNOWN_SITE"

    journal.close()


# ── ⑤ journal 봉인 → 503 + 산출물 미반환(고아 발급 금지) ────────────────────


def test_journal_write_failure_seals_and_returns_503_without_artifact(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client, store, journal = _client(tmp_path)

    def broken_write(_fd: int, _data: Any) -> int:
        raise OSError("disk full (주입 실패)")

    from ksi_core import durable_journal as durable_journal_module

    monkeypatch.setattr(durable_journal_module, "_WRITE", broken_write)

    response = client.post(
        "/v1/missions/plans", json=_plan_request(), headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )

    assert response.status_code == 503
    body = response.json()
    assert body["detail"] == "STORE_UNAVAILABLE"
    assert "contract" not in body, "봉인 시 서명 산출물이 반환되면 안 된다(미기록 발급 금지)"
    assert "kmzBase64" not in body
    assert store.get("mission-001") is None, "durable 기록 실패는 인메모리에도 반영되지 않아야 한다"

    monkeypatch.undo()
    journal.close()


# ── ⑥ 401/403 — MISSIONS_ISSUE 없는 역할 발급 거부·VIEWER 조회 허용 ────────


def test_issue_requires_authentication_401(tmp_path: Path) -> None:
    client, _store, journal = _client(tmp_path)

    response = client.post("/v1/missions/plans", json=_plan_request())

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"

    journal.close()


def test_issue_forbidden_for_role_without_missions_issue_403(tmp_path: Path) -> None:
    client, _store, journal = _client(tmp_path)

    response = client.post(
        "/v1/missions/plans", json=_plan_request(), headers=_auth_header(_VIEWER_TOKEN)
    )

    assert response.status_code == 403

    contract_response = client.post(
        "/v1/missions/contracts",
        json=_contract_request(),
        headers=_auth_header(_VIEWER_TOKEN),
    )
    assert contract_response.status_code == 403

    journal.close()


def test_viewer_can_read_but_not_issue(tmp_path: Path) -> None:
    client, _store, journal = _client(tmp_path)

    issued = client.post(
        "/v1/missions/plans", json=_plan_request(), headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert issued.status_code == 201

    read_list = client.get("/v1/missions", headers=_auth_header(_VIEWER_TOKEN))
    assert read_list.status_code == 200

    read_detail = client.get("/v1/missions/mission-001", headers=_auth_header(_VIEWER_TOKEN))
    assert read_detail.status_code == 200

    read_contract = client.get(
        "/v1/missions/mission-001/contract", headers=_auth_header(_VIEWER_TOKEN)
    )
    assert read_contract.status_code == 200

    issue_attempt = client.post(
        "/v1/missions/plans",
        json=_plan_request(mission_id="mission-002"),
        headers=_auth_header(_VIEWER_TOKEN),
    )
    assert issue_attempt.status_code == 403

    journal.close()


def test_get_missing_mission_returns_generic_404(tmp_path: Path) -> None:
    client, _store, journal = _client(tmp_path)

    response = client.get("/v1/missions/no-such-mission", headers=_auth_header(_VIEWER_TOKEN))

    assert response.status_code == 404
    contract_response = client.get(
        "/v1/missions/no-such-mission/contract", headers=_auth_header(_VIEWER_TOKEN)
    )
    assert contract_response.status_code == 404

    journal.close()


# ── ⑧ SITE_FRAME_MISMATCH — 등록 좌표계와 어긋난 발급 차단(ADR-KSI-007 짝 무결성) ──


def test_site_frame_mismatch_rejected_for_plans_and_contracts(tmp_path: Path) -> None:
    """요청 siteFrame 이 등록본과 다르면 서명 전에 422 SITE_FRAME_MISMATCH.

    transformVersion 하나만 달라도 거부된다 — 계약·KMZ 짝이 현장 등록 좌표계와
    어긋난 채(사일런트 drift) 발급되는 경로가 존재하지 않음을 증명한다.
    """
    client, store, journal = _client(tmp_path)
    drifted = {
        "crs": "EPSG:5186",
        "verticalDatum": "KNGeoid2018",
        "unit": "meter",
        "transformVersion": "2.0.0",  # 등록본은 1.0.0
    }

    plan_response = client.post(
        "/v1/missions/plans",
        json=_plan_request(siteFrame=drifted),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert plan_response.status_code == 422
    assert plan_response.json()["detail"] == "SITE_FRAME_MISMATCH"

    contract_response = client.post(
        "/v1/missions/contracts",
        json=_contract_request(siteFrame=drifted),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert contract_response.status_code == 422
    assert contract_response.json()["detail"] == "SITE_FRAME_MISMATCH"

    # 거부된 발급은 어떤 레코드도 남기지 않는다(고아·drift 기록 부재).
    assert store.list() == []

    journal.close()


def test_matching_site_frame_still_issues(tmp_path: Path) -> None:
    """등록본과 정확히 일치하는 siteFrame 은 정상 발급된다(대조 게이트의 반대 방향)."""
    client, _store, journal = _client(tmp_path)

    response = client.post(
        "/v1/missions/contracts",
        json=_contract_request(),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )

    assert response.status_code == 201
    journal.close()


# ── ⑨ 재검토 P2 item② — mission_id/site_id 문자 제약(URL 경로 안전) ─────────


def test_mission_id_with_slash_rejected_422_not_trapped_404(tmp_path: Path) -> None:
    """'/' 를 포함한 missionId 는 과거엔 201 로 기록됐지만 상세·계약 조회가
    영구 404 가 되는 트랩이었다 — 발급 시점에 typed 422 로 거부한다."""
    client, store, journal = _client(tmp_path)

    response = client.post(
        "/v1/missions/plans",
        json=_plan_request(mission_id="mission/001"),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "INVALID_MISSION_IDENTITY"
    assert store.list() == []

    journal.close()


def test_mission_id_with_whitespace_rejected_for_both_endpoints(tmp_path: Path) -> None:
    client, _store, journal = _client(tmp_path)

    plan_response = client.post(
        "/v1/missions/plans",
        json=_plan_request(mission_id="mission 001"),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert plan_response.status_code == 422
    assert plan_response.json()["detail"] == "INVALID_MISSION_IDENTITY"

    contract_response = client.post(
        "/v1/missions/contracts",
        json=_contract_request(mission_id="mission 002", site_id="site-001"),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert contract_response.status_code == 422
    assert contract_response.json()["detail"] == "INVALID_MISSION_IDENTITY"

    journal.close()


def test_site_id_with_invalid_characters_rejected_422(tmp_path: Path) -> None:
    """siteId 도 동일 제약을 받는다(missionId 만이 아니다)."""
    client, _store, journal = _client(tmp_path)

    response = client.post(
        "/v1/missions/plans",
        json=_plan_request(site_id="site/001"),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "INVALID_MISSION_IDENTITY"

    journal.close()


# ── ⑩ 재검토 P2 item④ — lone surrogate 는 500 이 아니라 422 ─────────────────


def test_lone_surrogate_in_objectives_rejected_422_not_500(tmp_path: Path) -> None:
    """objectives 에 lone surrogate(짝이 없는 \\ud800)가 있으면 서명 정규화가
    UnicodeEncodeError→500 이 되던 경로 — 발급 경계에서 선제 422 로 거부한다."""
    client, store, journal = _client(tmp_path)

    response = _post_json_with_lone_surrogate(
        client,
        "/v1/missions/plans",
        _plan_request(objectives=["\ud800 손상된 서로게이트"]),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "INVALID_TEXT_ENCODING"
    assert store.list() == []

    journal.close()


def test_lone_surrogate_in_site_frame_rejected_for_contracts_endpoint(tmp_path: Path) -> None:
    client, _store, journal = _client(tmp_path)

    response = _post_json_with_lone_surrogate(
        client,
        "/v1/missions/contracts",
        _contract_request(
            siteFrame={
                "crs": "EPSG:5186\ud800",
                "verticalDatum": "KNGeoid2018",
                "unit": "meter",
                "transformVersion": "1.0.0",
            }
        ),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "INVALID_TEXT_ENCODING"

    journal.close()


def test_lone_surrogate_in_derived_from_rejected_422_not_500(tmp_path: Path) -> None:
    """derivedFrom 은 ``request.contract`` 의 형제 필드라 계약 서브객체 검사만으로는
    잡히지 않는다 — 잡히지 않으면 ``_request_digest``→``canonical_payload_bytes``
    가 전체 요청을 UTF-8 로 strict encode 하다 UnicodeEncodeError 로 죽어 (500)
    발급 경계의 선제 422 를 우회한다.

    ``captureGrade`` 를 고른다: ``sourceMissionId``/``changeRegionSetId``/
    ``regionId`` 는 ``Field(min_length=1)`` 제약이 있어 pydantic-core 가 lone
    surrogate 를 핸들러 진입 **전** ``string_unicode`` 검증 오류로 먼저
    거부한다(그 오류 자체가 원문을 그대로 에코하다 별개의 500 을 낸다 — 이
    파일의 초점인 핸들러 내부 digest 경로가 아니다). 제약 없는 plain
    ``str | None`` 필드만 pydantic 검증을 그대로 통과해 핸들러까지 도달하고,
    거기서 이 회귀가 실제로 재현된다."""
    client, store, journal = _client(tmp_path)

    plan_request = _plan_request()
    plan_request["derivedFrom"] = {
        "sourceMissionId": "mission-000",
        "changeRegionSetId": "crs-1",
        "regionId": "region-1",
        "captureGrade": "A\ud800",
    }

    response = _post_json_with_lone_surrogate(
        client,
        "/v1/missions/plans",
        plan_request,
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "INVALID_TEXT_ENCODING"
    assert store.list() == []

    journal.close()


# ── ⑥-보강 INV-011 — 재기동(새 MissionStore) 후 실 계약 왕복 정확 일치 ──────


def test_issued_contract_survives_restart_and_matches_exactly(tmp_path: Path) -> None:
    """INV-011 강화(재검토 P3) — 발급 응답과 조회 응답의 동일 객체 비교는 journal
    왕복을 실제로 통과하지 않는다. 재기동(완전히 새로운 MissionStore/앱)한 뒤
    조회한 계약이 발급 응답과 정확히 일치해야 한다(stub 이 아닌 실 계약)."""
    journal_path = tmp_path / "missions.jsonl"
    private_key = Ed25519PrivateKey.generate()
    journal, store = _open_store(journal_path)
    app = _build_app(private_key=private_key, mission_store=store)
    client = TestClient(app)

    issue = client.post(
        "/v1/missions/plans", json=_plan_request(), headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert issue.status_code == 201
    issued = issue.json()
    journal.close()

    reborn_journal, reborn_store = _open_store(journal_path)
    reborn_app = _build_app(private_key=private_key, mission_store=reborn_store)
    reborn_client = TestClient(reborn_app)

    contract = reborn_client.get(
        "/v1/missions/mission-001/contract", headers=_auth_header(_VIEWER_TOKEN)
    )
    assert contract.status_code == 200
    assert contract.json() == issued["contract"], (
        "재기동 후 조회한 계약이 발급 응답과 정확 일치해야 한다(실 journal 왕복)"
    )

    detail = reborn_client.get("/v1/missions/mission-001", headers=_auth_header(_VIEWER_TOKEN))
    assert detail.status_code == 200
    assert detail.json()["kmzSha256"] == issued["kmzSha256"]
    assert detail.json()["waypointCount"] == issued["waypointCount"]

    reborn_journal.close()


def test_replay_failure_releases_journal_lock(tmp_path: Path) -> None:
    """[2차 독립 재검토 P2] MissionStore 기동 실패 시 journal flock 이 해제된다."""
    path = tmp_path / "missions.jsonl"
    seed = DurableJournal(path)
    seed.append({"missionId": "m-1", "siteId": "site-001", "artifactKind": "contract"})
    seed.append({"missionId": "m-1", "siteId": "site-001", "artifactKind": "contract"})
    seed.close()

    with pytest.raises(MissionStoreRecoveryError):
        MissionStore(DurableJournal(path))

    # 잠금이 해제됐다면 재조립이 flock 경합 없이 같은 예외로 재실패한다.
    with pytest.raises(MissionStoreRecoveryError):
        MissionStore(DurableJournal(path))


# ── ②-보강 s2-residual-hardening #3 — 짝 레코드 무결성을 재생에서도 강제한다 ──


def _write_raw_record(path: Path, record: dict[str, Any]) -> None:
    """journal 에 레코드 1줄을 직접 쓴다 — 원장 조작·과거 버그 상황 재현용."""
    journal = DurableJournal(path)
    journal.append(record)
    journal.close()


def _pair_record_dict(**overrides: Any) -> dict[str, Any]:
    plan_request: dict[str, Any] = {"route": {"altitudeM": 40.0}, "marker": "tamper-fixture"}
    base: dict[str, Any] = {
        "missionId": "mission-p",
        "siteId": "site-001",
        "missionType": "BASELINE_MAPPING",
        "artifactKind": "pair",
        "contract": {"schemaVersion": "1.2", "missionId": "mission-p"},
        "kmzSha256": "deadbeef",
        "routePattern": "lawnmower",
        "waypointCount": 42,
        "plannedCoverageRatio": 0.97,
        "issuedAt": datetime.now(UTC).isoformat(),
        "issuedBy": "do-1",
        "planRequest": plan_request,
        "planRequestDigest": sha256_digest(canonical_payload_bytes(plan_request)),
    }
    base.update(overrides)
    return base


def test_replay_rejects_plan_request_digest_mismatch(tmp_path: Path) -> None:
    """[핵심] digest 와 planRequest 가 어긋난 레코드로는 기동하지 않는다.

    그대로 재생하면 이후 재시도가 '같은 요청'으로 판정되고 **다른** 입력으로
    KMZ 를 재생성해 돌려준다 — 클라이언트가 보낸 적 없는 경로를 자기 요청의
    멱등 응답으로 받는 경로다.
    """
    path = tmp_path / "missions.jsonl"
    tampered = _pair_record_dict()
    tampered["planRequest"] = {"route": {"altitudeM": 999.0}, "marker": "swapped"}
    _write_raw_record(path, tampered)

    with pytest.raises(MissionStoreRecoveryError, match="planRequestDigest"):
        MissionStore(DurableJournal(path))


def test_replay_rejects_pair_record_without_plan_request(tmp_path: Path) -> None:
    """짝 레코드는 KMZ 재생성 입력을 반드시 들고 있어야 한다 — 없으면 기동 거부.

    없는 채로 재생되면 그 사건은 멱등 재발급 시점에야 assert 로 터진다(500).
    기동 시점에 거부하는 편이 진단 가능하다.
    """
    path = tmp_path / "missions.jsonl"
    record = _pair_record_dict()
    record.pop("planRequest")
    record.pop("planRequestDigest")
    _write_raw_record(path, record)

    with pytest.raises(MissionStoreRecoveryError, match="planRequest 가 없다"):
        MissionStore(DurableJournal(path))


def test_replay_accepts_intact_pair_record(tmp_path: Path) -> None:
    """[비공허 대조] 온전한 짝 레코드는 그대로 재생된다 — 위 두 게이트가 과잉이 아니다."""
    path = tmp_path / "missions.jsonl"
    _write_raw_record(path, _pair_record_dict())

    journal = DurableJournal(path)
    store = MissionStore(journal)
    try:
        loaded = store.get("mission-p")
        assert loaded is not None
        assert loaded.plan_request is not None
    finally:
        journal.close()


# ── ⑪ 파생 필드 coverageCompletionState — CoverageReportStore 조회(INV-010) ──
#
# MissionRecord 에 실행 상태 필드를 새로 만들지 않는다 — 완료 판정의 권위는
# CoverageReport 하나다. 이 필드는 조회 시점에 CoverageReportStore.latest() 를
# 계산해 실을 뿐, journal 에는 아무것도 추가로 적지 않는다.


def _coverage_report_payload(
    mission_id: str, site_id: str, *, completion: str = "COMPLETED"
) -> dict[str, Any]:
    return {
        "missionId": mission_id,
        "siteId": site_id,
        "timestamp": "2026-08-05T02:00:00+00:00",
        "cells": [{"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"}],
        "summary": {
            "mandatoryHazardRatio": 1.0,
            "mandatoryAssetRatio": 1.0,
            "accessibleGeneralRatio": 1.0,
            "completionState": completion,
        },
    }


def test_coverage_completion_state_is_null_without_any_report(tmp_path: Path) -> None:
    """보고가 하나도 없으면 목록·상세 둘 다 null — "—" 로 조용히 넘어가지 않는다."""
    private_key = Ed25519PrivateKey.generate()
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    coverage_store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"), mission_store=mission_store
    )
    app = _build_app(
        private_key=private_key,
        mission_store=mission_store,
        coverage_report_store=coverage_store,
    )
    client = TestClient(app)

    issue = client.post(
        "/v1/missions/plans", json=_plan_request(), headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert issue.status_code == 201

    listing = client.get("/v1/missions", headers=_auth_header(_VIEWER_TOKEN))
    assert listing.json()[0]["coverageCompletionState"] is None

    detail = client.get("/v1/missions/mission-001", headers=_auth_header(_VIEWER_TOKEN))
    assert detail.json()["coverageCompletionState"] is None


def test_coverage_completion_state_reflects_latest_recorded_report(tmp_path: Path) -> None:
    """[핵심] 커버리지 보고가 오면 목록·상세가 서버 판정을 그대로 반영한다(재계산 없음).

    두 번째 보고가 최신이 되는 것도 함께 증명한다(덮어쓰지 않고 append, latest()
    가 가장 최근 것을 낸다) — 재비행 뒤 목록이 낡은 상태로 멎지 않는다.
    """
    private_key = Ed25519PrivateKey.generate()
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    coverage_store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"), mission_store=mission_store
    )
    app = _build_app(
        private_key=private_key,
        mission_store=mission_store,
        coverage_report_store=coverage_store,
    )
    client = TestClient(app)

    issue = client.post(
        "/v1/missions/plans", json=_plan_request(), headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert issue.status_code == 201

    first = coverage_store.record(
        CoverageReport.model_validate(
            _coverage_report_payload("mission-001", "site-001", completion="COMPLETED_WITH_GAPS")
        ),
        now=datetime.now(UTC),
    )
    assert first.verdict.value == "RECORDED"

    listing = client.get("/v1/missions", headers=_auth_header(_VIEWER_TOKEN))
    assert listing.json()[0]["coverageCompletionState"] == "COMPLETED_WITH_GAPS"

    second = coverage_store.record(
        CoverageReport.model_validate(
            _coverage_report_payload("mission-001", "site-001", completion="COMPLETED")
        ),
        now=datetime.now(UTC),
    )
    assert second.verdict.value == "RECORDED"

    detail = client.get("/v1/missions/mission-001", headers=_auth_header(_VIEWER_TOKEN))
    assert detail.json()["coverageCompletionState"] == "COMPLETED"


def test_coverage_completion_state_is_null_when_store_not_wired(tmp_path: Path) -> None:
    """coverage_report_store 를 조립에 주지 않으면(선택 파라미터) 필드는 항상 null이다
    — 배선 자체가 없는 구성에서도 응답 스키마가 깨지지 않는다."""
    client, _store, journal = _client(tmp_path)

    issue = client.post(
        "/v1/missions/plans", json=_plan_request(), headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert issue.status_code == 201

    listing = client.get("/v1/missions", headers=_auth_header(_VIEWER_TOKEN))
    assert listing.json()[0]["coverageCompletionState"] is None

    journal.close()


# ── 임무 계보 (ADR-KSI-019 G5) ──────────────────────────────────────────


def test_pair_issuance_records_the_change_region_it_came_from(tmp_path: Path) -> None:
    """[핵심] 재관측 임무가 어느 분석 결과에서 나왔는지 원장이 안다.

    없으면 "이 비행은 왜 했나"에 원장이 답하지 못하고, 폐루프가 사람의 기억에
    의존한다.
    """
    client, _store, _journal = _client(tmp_path)
    payload = _plan_request(mission_id="mission-derived-1")
    payload["derivedFrom"] = {
        "sourceMissionId": "mission-source-1",
        "changeRegionSetId": "crs-1",
        "regionId": "r-1",
        "captureGrade": "DETAILED",
    }

    issue = client.post(
        "/v1/missions/plans", json=payload, headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )

    assert issue.status_code == 201, issue.json()
    detail = client.get(
        "/v1/missions/mission-derived-1", headers=_auth_header(_VIEWER_TOKEN)
    ).json()
    assert detail["derivedFrom"] == {
        "sourceMissionId": "mission-source-1",
        "changeRegionSetId": "crs-1",
        "regionId": "r-1",
        "captureGrade": "DETAILED",
    }


def test_derivation_is_optional(tmp_path: Path) -> None:
    """최초 매핑 임무는 계보가 없다 — 없다고 발급을 막지 않는다."""
    client, _store, _journal = _client(tmp_path)

    issue = client.post(
        "/v1/missions/plans",
        json=_plan_request(mission_id="mission-no-derivation"),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )

    assert issue.status_code == 201, issue.json()
    detail = client.get(
        "/v1/missions/mission-no-derivation", headers=_auth_header(_VIEWER_TOKEN)
    ).json()
    assert detail["derivedFrom"] is None


def test_derivation_does_not_enter_the_signed_contract(tmp_path: Path) -> None:
    """[핵심] 계보는 운영 메타데이터이지 서명 계약의 일부가 아니다.

    ``assigned_device_id``·``kmz_sha256`` 과 같은 지위다. 계약에 넣으면 Manifold 가
    받는 신뢰 경계 안으로 서버측 분석 산출물이 들어가고, 계약 스키마도 바뀐다.
    """
    client, _store, _journal = _client(tmp_path)
    payload = _plan_request(mission_id="mission-derived-2")
    payload["derivedFrom"] = {
        "sourceMissionId": "mission-source-1",
        "changeRegionSetId": "crs-1",
        "regionId": "r-1",
    }
    client.post("/v1/missions/plans", json=payload, headers=_auth_header(_FIELD_OPERATOR_TOKEN))

    contract = client.get(
        "/v1/missions/mission-derived-2/contract", headers=_auth_header(_VIEWER_TOKEN)
    ).json()

    assert "derivedFrom" not in contract
    # 계보를 담은 필드 이름이 다른 이름으로도 새지 않는지 — mission-contract
    # 스키마가 아는 필드 밖의 것은 전부 거부한다(계약 모델 자체가 extra="forbid").
    assert "sourceMissionId" not in contract
    assert "changeRegionSetId" not in contract


def test_missions_can_be_filtered_by_source_region(tmp_path: Path) -> None:
    client, _store, _journal = _client(tmp_path)
    derived_payload = _plan_request(mission_id="mission-from-r1")
    derived_payload["derivedFrom"] = {
        "sourceMissionId": "mission-source-1",
        "changeRegionSetId": "crs-1",
        "regionId": "r-1",
    }
    client.post(
        "/v1/missions/plans", json=derived_payload, headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    client.post(
        "/v1/missions/plans",
        json=_plan_request(mission_id="mission-unrelated"),
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )

    listed = client.get(
        "/v1/missions",
        params={"derivedFromRegion": "r-1"},
        headers=_auth_header(_VIEWER_TOKEN),
    )

    assert listed.status_code == 200, listed.json()
    assert [m["missionId"] for m in listed.json()] == ["mission-from-r1"]


def test_idempotent_reissue_keeps_the_same_derivation(tmp_path: Path) -> None:
    """같은 요청 재전송이 계보를 지우거나 바꾸지 않는다(멱등 재발급 경로)."""
    client, _store, _journal = _client(tmp_path)
    payload = _plan_request(mission_id="mission-derived-idem")
    payload["derivedFrom"] = {
        "sourceMissionId": "mission-source-1",
        "changeRegionSetId": "crs-1",
        "regionId": "r-1",
    }

    first = client.post(
        "/v1/missions/plans", json=payload, headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    second = client.post(
        "/v1/missions/plans", json=payload, headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )

    assert first.status_code == 201, first.json()
    assert second.status_code == 200, "동일 요청 재시도는 멱등 200"
    detail = client.get(
        "/v1/missions/mission-derived-idem", headers=_auth_header(_VIEWER_TOKEN)
    ).json()
    assert detail["derivedFrom"]["regionId"] == "r-1"


def test_v13_site_sequence_reservations_are_durable_and_allow_gaps(tmp_path: Path) -> None:
    path = tmp_path / "mission-sequences.jsonl"
    journal = DurableJournal(path)
    store = MissionIssuanceSequenceStore(journal)
    now = datetime.now(UTC)

    assert store.reserve(issuer_id="core-1", site_id="site-001", reserved_at=now) == 1
    # 이 번호로 서명/기록하지 않아도 예약은 이미 내구화됐다. 다음 발급이 재사용하면 안 된다.
    assert store.reserve(issuer_id="core-1", site_id="site-001", reserved_at=now) == 2
    assert store.reserve(issuer_id="core-1", site_id="site-002", reserved_at=now) == 1
    assert store.reserve(issuer_id="core-2", site_id="site-001", reserved_at=now) == 1
    journal.close()

    reopened_journal = DurableJournal(path)
    reopened = MissionIssuanceSequenceStore(reopened_journal)
    assert reopened.reserve(issuer_id="core-1", site_id="site-001", reserved_at=now) == 3
    reopened_journal.close()


def test_v13_site_sequence_replay_rejects_duplicate_or_lower_values(tmp_path: Path) -> None:
    path = tmp_path / "mission-sequences.jsonl"
    journal = DurableJournal(path)
    now = datetime.now(UTC)
    record = {
        "kind": "MISSION_SITE_SEQUENCE_RESERVED",
        "issuerId": "core-1",
        "siteId": "site-001",
        "siteSequence": 2,
        "reservedAt": now.isoformat(),
    }
    journal.append(record)
    journal.append({**record, "siteSequence": 2})
    journal.close()

    with pytest.raises(MissionSequenceRecoveryError, match="단조 증가"):
        MissionIssuanceSequenceStore(DurableJournal(path))
