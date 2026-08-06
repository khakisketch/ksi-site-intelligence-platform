"""S2 최종 조립 E2E (ADR-KSI-008) — 실여정으로 전체 도메인 표면을 왕복한다.

단위/계약 테스트는 각 모듈(auth·sites·mission_records·events·edge_sync)을 개별
조립으로 검증한다. 이 파일은 그와 달리 :func:`ksi_core.app.create_app` **최대
조립 하나**로 실제 운영 여정을 처음부터 끝까지 통과시킨다 — "green≠작동"
원칙(개별 단위 테스트가 통과해도 조립이 깨질 수 있다)의 폐쇄 지점이다:

1. 운영자가 site 를 등록하고 10상태 머신을 PATROL_READY 까지 승격한다.
2. 운영자가 이원 산출물(KMZ+계약)을 발급하고 목록·계약을 조회한다.
3. 인증된 장비가 EventBundle 을 수신시키고, 운영자가 조회→FINDING 확정→배정한다.
4. **프로세스 재기동**(동일 tmp 경로에서 journal 을 새로 열어 재생)해도 site·
   mission·event 전 상태와 감사 레코드(transitions)가 원문 그대로 보존된다.
5. 타 장비 토큰으로 다른 장비를 사칭한 수신은 원장에 반영되지 않고 403.
6. 보호 경로 전수가 무인증 요청을 401 로 거부한다(파라미터라이즈).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
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
from ksi_core.edge_sync import EdgeSyncStore
from ksi_core.events import EventStore, make_event_key
from ksi_core.mission_records import MissionStore
from ksi_core.sites import SiteStore
from ksi_geo_core.frames import WGS84_EQUATORIAL_RADIUS_M
from ksi_mission_contracts.signing import KeyRegistry, SignatureVerdict, load_verified_contract

_LAT0, _LON0 = 37.5000, 127.0000
_M_PER_DEG_LAT = math.radians(1.0) * WGS84_EQUATORIAL_RADIUS_M

_FIELD_OPERATOR_TOKEN = "e2e-field-operator-token"  # noqa: S105 — 테스트 고정 토큰
_MISSION_ISSUER_TOKEN = "e2e-mission-issuer-token"  # noqa: S105 — FIELD_OPERATOR, 다른 사람
_ADMIN_TOKEN = "e2e-admin-token"  # noqa: S105 — 자율운영 승인 게이트(ADR-KSI-015 D2) 전용
_EDGE_TOKEN = "e2e-edge-device-token"  # noqa: S105
_OTHER_EDGE_TOKEN = "e2e-other-edge-device-token"  # noqa: S105

_EDGE_DEVICE_ID = "edge-e2e-001"
_OTHER_EDGE_DEVICE_ID = "edge-e2e-002"
_SITE_ID = "site-e2e-001"
_MISSION_ID = "mission-e2e-001"
_EVENT_ID = "evt-e2e-001"
_KEY_ID = "core-e2e-issuer-key-1"
# 서버 정본 사건 신원(ADR-KSI-008 §3) — event_key = "{edgeDeviceId}::{eventId}".
_EVENT_KEY = make_event_key(_EDGE_DEVICE_ID, _EVENT_ID)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_FIELD_OPERATOR_TOKEN),
                principal=Principal(
                    principal_id="sm-e2e-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_MISSION_ISSUER_TOKEN),
                principal=Principal(
                    principal_id="do-e2e-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_ADMIN_TOKEN),
                principal=Principal(
                    principal_id="admin-e2e-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_EDGE_TOKEN),
                principal=Principal(
                    principal_id="edge-principal-e2e-1",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id=_EDGE_DEVICE_ID,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OTHER_EDGE_TOKEN),
                principal=Principal(
                    principal_id="edge-principal-e2e-2",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id=_OTHER_EDGE_DEVICE_ID,
                ),
            ),
        ]
    )


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _site_frame() -> dict[str, str]:
    return {
        "crs": "EPSG:5186",
        "verticalDatum": "KNGeoid2018",
        "unit": "meter",
        "transformVersion": "1.0.0",
    }


def _rect_aoi_vertices() -> list[dict[str, float]]:
    dlat = 100.0 / _M_PER_DEG_LAT
    dlon = 200.0 / (_M_PER_DEG_LAT * math.cos(math.radians(_LAT0)))
    return [
        {"latDeg": _LAT0, "lonDeg": _LON0},
        {"latDeg": _LAT0, "lonDeg": _LON0 + dlon},
        {"latDeg": _LAT0 + dlat, "lonDeg": _LON0 + dlon},
        {"latDeg": _LAT0 + dlat, "lonDeg": _LON0},
    ]


def _plan_request() -> dict[str, Any]:
    return {
        "contract": {
            "missionId": _MISSION_ID,
            "siteId": _SITE_ID,
            "missionType": "AUTONOMOUS_PATROL",
            "siteFrame": _site_frame(),
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
        # AUTONOMOUS_PATROL 은 Spatial Refresh Backbone 이 필수다(MASTER_PRD §15.2) —
        # 500.0 은 이 파일의 고정 rect AOI 최장 변(200m)보다 커서 추가 웨이포인트를
        # 만들지 않는다.
        "route": {"altitudeM": 40.0, "captureIntervalM": 500.0},
        "drone": {"droneEnumValue": 99, "droneSubEnumValue": 0, "payloadEnumValue": 65534},
        "wayline": {
            "autoFlightSpeedMs": 5.0,
            "takeoffSecurityHeightM": 20.0,
            "globalTransitionalSpeedMs": 10.0,
        },
    }


def _bundle_payload(event_id: str = _EVENT_ID) -> dict[str, Any]:
    """OBSERVATION 상태의 유효 EventBundle v1.2 — 서버 트리아지가 전 구간을 승격한다."""
    return {
        "schemaVersion": "1.2",
        "eventId": event_id,
        "missionId": _MISSION_ID,
        "siteId": _SITE_ID,
        "eventType": "PERSON_PRESENT",
        "occurredAt": "2026-07-30T06:00:00Z",
        "status": "OBSERVATION",
        "entities": ["ent-e2e-001"],
        "spatialContext": {},
        "reasoning": {},
        "evidence": {},
        "lineage": {
            "edgeVersion": "e2e-edge-1.0",
            "modelVersions": {"detector": "stub"},
            "policyVersion": "e2e-policy-1",
            "calibrationProfileId": "e2e-cal-1",
            "classification": {
                "ent-e2e-001": {
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


@dataclass(frozen=True, slots=True)
class _Assembly:
    """네 도메인 저장소 + 그 journal(재기동 재현용 ``close()`` 대상)의 묶음."""

    site_journal: DurableJournal
    site_store: SiteStore
    mission_journal: DurableJournal
    mission_store: MissionStore
    event_journal: DurableJournal
    event_store: EventStore
    edge_sync_store: EdgeSyncStore

    def close(self) -> None:
        """프로세스 종료 재현(flock 해제) — test_mission_records.py 관습 대칭."""
        self.site_journal.close()
        self.mission_journal.close()
        self.event_journal.close()
        self.edge_sync_store.close()


def _open_stores(tmp_path: Path) -> _Assembly:
    """네 도메인 저장소를 명시 경로로 연다 — journal 은 별도 보관해 재기동 재현시
    ``close()`` 로 직접 닫을 수 있게 한다(test_mission_records.py ``_open_store`` 관습)."""
    site_journal = DurableJournal(tmp_path / "sites.jsonl")
    mission_journal = DurableJournal(tmp_path / "missions.jsonl")
    event_journal = DurableJournal(tmp_path / "events.jsonl")
    return _Assembly(
        site_journal=site_journal,
        site_store=SiteStore(site_journal),
        mission_journal=mission_journal,
        mission_store=MissionStore(mission_journal),
        event_journal=event_journal,
        event_store=EventStore(event_journal),
        edge_sync_store=EdgeSyncStore(tmp_path / "edge-sync.jsonl"),
    )


def _build_app(assembly: _Assembly, *, private_key: Ed25519PrivateKey) -> FastAPI:
    return create_app(
        auth_registry=_auth_registry(),
        site_store=assembly.site_store,
        mission_store=assembly.mission_store,
        event_store=assembly.event_store,
        edge_sync_store=assembly.edge_sync_store,
        mission_signing_key=private_key,
        mission_signing_key_id=_KEY_ID,
    )


def test_full_lifecycle_survives_process_restart(tmp_path: Path) -> None:  # noqa: PLR0915
    private_key = Ed25519PrivateKey.generate()
    key_registry = KeyRegistry()
    key_registry.register(_KEY_ID, private_key.public_key())

    assembly = _open_stores(tmp_path)
    app = _build_app(assembly, private_key=private_key)
    client = TestClient(app)

    # ── ① 운영자: site 등록 → 10상태 머신 승격 → PATROL_READY ────────────────
    # 자율 시작 승인(→PROVISIONAL_AUTONOMY)·정식 순찰 승인(→PATROL_READY) 은
    # ADR-KSI-015 D2 게이트로 관리자 전용이다 — 그 두 간선만 ADMIN 토큰을 쓴다.
    _ADMIN_GATED_TARGETS = {"PROVISIONAL_AUTONOMY", "PATROL_READY"}

    register = client.post(
        "/v1/sites",
        json={"siteId": _SITE_ID, "name": "E2E 현장", "siteFrame": _site_frame()},
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert register.status_code == 201, register.text

    for target in (
        "BASELINE_MAPPING",
        "MODEL_PROCESSING",
        "MODEL_VALIDATION",
        "PROVISIONAL_AUTONOMY",
        "PATROL_READY",
    ):
        token = _ADMIN_TOKEN if target in _ADMIN_GATED_TARGETS else _FIELD_OPERATOR_TOKEN
        transition = client.post(
            f"/v1/sites/{_SITE_ID}/transitions",
            json={"targetStatus": target, "evidence": f"{target} 증거", "reason": f"{target} 사유"},
            headers=_auth_header(token),
        )
        assert transition.status_code == 200, transition.text
        assert transition.json()["site"]["status"] == target

    # ── ② 운영자: 이원 산출물(pair) 발급 → 목록/계약 조회 ─────────────────────
    issue = client.post(
        "/v1/missions/plans", json=_plan_request(), headers=_auth_header(_MISSION_ISSUER_TOKEN)
    )
    assert issue.status_code == 201, issue.text
    issued = issue.json()
    loaded = load_verified_contract(issued["contract"], key_registry, now=datetime.now(UTC))
    assert loaded.verdict is SignatureVerdict.VALID, loaded.detail

    listing = client.get(
        "/v1/missions", params={"siteId": _SITE_ID}, headers=_auth_header(_MISSION_ISSUER_TOKEN)
    )
    assert listing.status_code == 200
    assert [m["missionId"] for m in listing.json()] == [_MISSION_ID]

    contract = client.get(
        f"/v1/missions/{_MISSION_ID}/contract", headers=_auth_header(_MISSION_ISSUER_TOKEN)
    )
    assert contract.status_code == 200
    assert contract.json() == issued["contract"]

    # ── ③ 장비: EventBundle 수신 → 운영자: 조회 → FINDING 확정 → 배정 ─────────
    ingest = client.post(
        "/v1/edge-sync/event-bundles",
        json={
            "idempotencyKey": f"{_EDGE_DEVICE_ID}:0",
            "deviceSequence": 0,
            "edgeDeviceId": _EDGE_DEVICE_ID,
            "payloadDigest": _digest_payload(_bundle_payload()),
            "payload": _bundle_payload(),
        },
        headers=_auth_header(_EDGE_TOKEN),
    )
    assert ingest.status_code == 201, ingest.text

    events_list = client.get("/v1/events", headers=_auth_header(_FIELD_OPERATOR_TOKEN))
    assert events_list.status_code == 200
    assert events_list.json()["count"] == 1

    event_detail = client.get(
        f"/v1/events/{_EVENT_KEY}", headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert event_detail.status_code == 200
    assert event_detail.json()["status"] == "OBSERVATION"

    for target in ("CANDIDATE", "EVIDENCE_COLLECTION", "FINDING"):
        step = client.post(
            f"/v1/events/{_EVENT_KEY}/transitions",
            json={"targetStatus": target},
            headers=_auth_header(_FIELD_OPERATOR_TOKEN),
        )
        assert step.status_code == 200, step.text
        assert step.json()["event"]["status"] == target

    confirm = client.post(
        f"/v1/events/{_EVENT_KEY}/transitions",
        json={"targetStatus": "CONFIRMED_EVENT", "reason": "현장 확인 완료"},
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["event"]["status"] == "CONFIRMED_EVENT"

    assign = client.post(
        f"/v1/events/{_EVENT_KEY}/transitions",
        json={"triageTarget": "ASSIGNED", "assignee": "field-ops-1", "reason": "배정"},
        headers=_auth_header(_FIELD_OPERATOR_TOKEN),
    )
    assert assign.status_code == 200, assign.text
    assert assign.json()["event"]["triage"] == "ASSIGNED"

    # ── ④ 프로세스 재기동(동일 tmp 경로 재조립) — 전 상태·감사 레코드 보존 ─────
    assembly.close()

    reborn = _open_stores(tmp_path)

    site_record = reborn.site_store.get(_SITE_ID)
    assert site_record is not None
    assert site_record.status.value == "PATROL_READY"

    mission_record = reborn.mission_store.get(_MISSION_ID)
    assert mission_record is not None
    assert mission_record.contract == issued["contract"]
    assert mission_record.issued_by == "do-e2e-1"

    event_record = reborn.event_store.get(_EVENT_KEY)
    assert event_record is not None
    assert event_record.status.value == "CONFIRMED_EVENT"
    assert event_record.triage.value == "ASSIGNED"
    assert event_record.assignee == "field-ops-1"
    # 감사 레코드 실재: projection 1 + status 전이 4(CANDIDATE/EVIDENCE_COLLECTION/
    # FINDING/CONFIRMED_EVENT) + triage 전이 1(ASSIGNED) = 6, 각 actor·ts·before/
    # after 를 보존한 journal 레코드가 재생을 통과했다(아니면 SiteStoreRecoveryError
    # 류로 기동 자체가 거부됐을 것 — fail-closed 재생이 이미 무결성을 증명한다).
    assert len(event_record.transitions) == 6
    assert event_record.transitions[0]["kind"] == "event-projected"
    confirmed_record = next(
        r for r in event_record.transitions if r.get("after", {}).get("status") == "CONFIRMED_EVENT"
    )
    assert confirmed_record["reason"] == "현장 확인 완료"
    assert confirmed_record["actor"] == "sm-e2e-1"

    reborn_app = _build_app(reborn, private_key=private_key)
    reborn_client = TestClient(reborn_app)
    reborn_site = reborn_client.get(
        f"/v1/sites/{_SITE_ID}", headers=_auth_header(_FIELD_OPERATOR_TOKEN)
    )
    assert reborn_site.status_code == 200
    assert reborn_site.json()["status"] == "PATROL_READY"

    reborn.close()


def _digest_payload(payload: dict[str, Any]) -> str:
    from ksi_event_contracts.offline_sync import payload_digest

    return payload_digest(payload)


def test_impostor_device_ingest_rejected_without_ledger_effect(tmp_path: Path) -> None:
    """[edge-sync-preauth-sequence-lockout 해소] 타 장비 토큰으로 다른 장비를 사칭한
    수신은 원장에 반영되지 않고 403 DEVICE_MISMATCH — 위조 순번 주입이 장비 신원
    뒤로 차단된다."""
    private_key = Ed25519PrivateKey.generate()
    assembly = _open_stores(tmp_path)
    app = _build_app(assembly, private_key=private_key)
    client = TestClient(app)

    payload = _bundle_payload("evt-impostor-001")
    response = client.post(
        "/v1/edge-sync/event-bundles",
        json={
            "idempotencyKey": f"{_EDGE_DEVICE_ID}:0",
            "deviceSequence": 0,
            "edgeDeviceId": _EDGE_DEVICE_ID,  # 타 장비(edge-e2e-001)를 자칭
            "payloadDigest": _digest_payload(payload),
            "payload": payload,
        },
        headers=_auth_header(_OTHER_EDGE_TOKEN),  # 인증은 edge-e2e-002
    )

    assert response.status_code == 403
    assert response.json()["verdict"] == "DEVICE_MISMATCH"
    assert assembly.edge_sync_store.accepted_count() == 0
    assert assembly.event_store.get(make_event_key(_EDGE_DEVICE_ID, "evt-impostor-001")) is None


# ── 무인증 401 전수 — 하드코딩 목록이 아니라 app.routes 파생(P3→구조화) ─────────
#
# 최대 조립 app 의 모든 (method, path) 를 열거해 공개 allowlist(FastAPI 기본
# 문서/헬스 표면) 밖 전부가 무인증 401 을 반환함을 요구한다. 신규 라우트가
# 보호 없이 추가되면 이 목록에 자동으로 잡혀 실패한다 — 그게 이 테스트의 목적이다
# (하드코딩 목록은 새 라우트 추가를 "깜빡"할 수 있지만 파생 목록은 그럴 수 없다).

_PUBLIC_ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("GET", "/capabilities"),
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
        ("GET", "/docs/oauth2-redirect"),
        ("GET", "/redoc"),
    }
)

# path 파라미터 치환용 더미 값 — 실존 여부와 무관하게 인증 게이트가 먼저 걸린다
# (auth Depends 가 본문/리소스 조회보다 먼저 평가된다 — 실측 확인).
_PATH_PARAM_DUMMIES: dict[str, str] = {
    "site_id": _SITE_ID,
    "mission_id": _MISSION_ID,
    "event_key": "edge-001::evt-x",
    "device_id": _EDGE_DEVICE_ID,
}

# 알려진 라우트의 유효한 요청 본문(문서화 목적) — 없으면 POST 류는 빈 dict 로
# 안전하게 폴백한다(무인증 401 은 본문 유효성과 무관하게 먼저 걸린다).
_REQUEST_BODIES: dict[tuple[str, str], dict[str, Any] | None] = {
    ("POST", "/v1/sites"): {"siteId": "s", "name": "n", "siteFrame": _site_frame()},
    ("POST", "/v1/sites/{site_id}/transitions"): {
        "targetStatus": "BASELINE_MAPPING",
        "evidence": "e",
        "reason": "r",
    },
    ("POST", "/v1/edge-sync/event-bundles"): {
        "idempotencyKey": "k",
        "deviceSequence": 0,
        "edgeDeviceId": _EDGE_DEVICE_ID,
        "payloadDigest": "sha256:" + "0" * 64,
        "payload": {},
    },
    ("POST", "/v1/events/{event_key}/transitions"): {"targetStatus": "CANDIDATE"},
    ("POST", "/v1/missions/contracts"): _plan_request()["contract"],
    ("POST", "/v1/missions/plans"): _plan_request(),
}


def _walk_routes(routes: list[Any]) -> Any:
    """APIRoute 리프까지 재귀 — FastAPI 버전에 따라 ``_IncludedRouter``
    (``original_router.routes``) 또는 평탄화된 ``APIRouter``(``routes``) 로 include
    된 서브라우터를 감싼다. 둘 다 대응해야 최대 조립의 전 라우트를 놓치지 않는다."""
    for route in routes:
        methods = getattr(route, "methods", None)
        if methods and hasattr(route, "path"):
            yield route
        elif hasattr(route, "original_router"):
            yield from _walk_routes(route.original_router.routes)
        elif hasattr(route, "routes"):
            yield from _walk_routes(route.routes)


def _maximal_app_route_pairs() -> list[tuple[str, str]]:
    """최대 조립 app 의 (method, path template) 전수 — 실제 라우트 등록에서 파생."""
    import tempfile as _tempfile

    tmp_path = Path(_tempfile.mkdtemp())
    private_key = Ed25519PrivateKey.generate()
    assembly = _open_stores(tmp_path)
    app = _build_app(assembly, private_key=private_key)
    assembly.close()

    pairs: list[tuple[str, str]] = []
    for route in _walk_routes(app.routes):
        for method in route.methods:
            if method == "HEAD":  # GET 과 동일 보호 표면 — 중복 케이스 불요
                continue
            pairs.append((method, route.path))
    return pairs


def _protected_route_cases() -> list[tuple[str, str, dict[str, Any] | None]]:
    cases: list[tuple[str, str, dict[str, Any] | None]] = []
    for method, template in sorted(set(_maximal_app_route_pairs())):
        if (method, template) in _PUBLIC_ALLOWLIST:
            continue
        path = template
        for name, value in _PATH_PARAM_DUMMIES.items():
            path = path.replace("{" + name + "}", value)
        default_body: dict[str, Any] | None = {} if method != "GET" else None
        body = _REQUEST_BODIES.get((method, template), default_body)
        cases.append((method, path, body))
    return cases


@pytest.mark.parametrize(("method", "path", "json_body"), _protected_route_cases())
def test_all_protected_routes_reject_unauthenticated_requests(
    method: str, path: str, json_body: dict[str, Any] | None, tmp_path: Path
) -> None:
    private_key = Ed25519PrivateKey.generate()
    assembly = _open_stores(tmp_path)
    app = _build_app(assembly, private_key=private_key)
    client = TestClient(app)

    response = client.request(method, path, json=json_body)

    assert response.status_code == 401, f"{method} {path} 가 무인증을 거부하지 않았다"
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["www-authenticate"] == "Bearer"
