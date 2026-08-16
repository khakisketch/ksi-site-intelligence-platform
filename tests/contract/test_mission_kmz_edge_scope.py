"""KMZ 다운로드의 **장비 경로** 범위 계약 (ADR-KSI-008 §2 권한 표).

사람 손으로 조종기에 파일을 옮기는 단계를 없애려면 기체 컴퓨터가 KMZ 를 직접
받아야 한다. 그 표면을 여는 방법은 두 가지였다 — 장비에 ``MISSIONS_READ`` 를
주거나, 자기 임무 하나로 범위가 좁은 권한을 새로 만들거나. 전자는 장비 하나가
뚫렸을 때 전 현장의 임무 목록·좌표·원본 미디어가 함께 새기 때문에 후자를 택했다.

이 파일이 고정하는 것은 그 선택이 **실제로 좁은가**다:

1. 배정된 장비는 사람과 **같은 바이트**를 받는다 — 해석 경로가 하나라는 증거.
2. 다른 장비의 임무는 403 이 아니라 **404** — 403 은 "그 임무는 존재한다"를
   알려주는 존재 오라클이고, 장비 토큰 하나로 임무 식별자 공간을 훑게 한다.
3. 배정이 아예 없는 임무도 장비에겐 404 — 미배정을 "아무나 가져가도 되는 것"으로
   읽지 않는다(``EdgeDispatchStore.next_for_device`` 와 같은 판정, INV-011/012).
4. 새 권한은 KMZ 하나만 연다 — 같은 토큰으로 임무 **상세**는 여전히 못 읽는다.
   이게 깨지면 ``MISSIONS_READ`` 를 주지 않은 이유 자체가 사라진다.
5. 어느 KMZ 권한도 없는 주체는 403, 미인증은 401 — 401/403/404 세 층이 서로
   구분된 채로 남아 있는가.
"""

from __future__ import annotations

import base64
import hashlib
import math
from datetime import UTC, datetime
from typing import Any

from _site_lifecycle import advance_site_status
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    Permission,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    principal_permissions,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionStore
from ksi_core.sites import SiteStore
from ksi_domain.enums import SiteStatus
from ksi_geo_core.frames import WGS84_EQUATORIAL_RADIUS_M
from ksi_mission_contracts.models import SiteFrame

_ASSIGNED_DEVICE_ID = "edge-assigned-001"
_OTHER_DEVICE_ID = "edge-other-002"

_OPERATOR_TOKEN = "kmz-scope-operator-token"  # noqa: S105 — 테스트 고정 토큰
_ASSIGNED_DEVICE_TOKEN = "kmz-scope-assigned-device-token"  # noqa: S105
_OTHER_DEVICE_TOKEN = "kmz-scope-other-device-token"  # noqa: S105
_WORKER_TOKEN = "kmz-scope-worker-token"  # noqa: S105

_LAT0, _LON0 = 37.5000, 127.0000
_M_PER_DEG_LAT = math.radians(1.0) * WGS84_EQUATORIAL_RADIUS_M

_SITE_FRAME = {
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
                token_sha256=_digest(_OPERATOR_TOKEN),
                principal=Principal(
                    principal_id="fo-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_ASSIGNED_DEVICE_TOKEN),
                principal=Principal(
                    principal_id="edge-assigned",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id=_ASSIGNED_DEVICE_ID,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OTHER_DEVICE_TOKEN),
                principal=Principal(
                    principal_id="edge-other",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id=_OTHER_DEVICE_ID,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_WORKER_TOKEN),
                principal=Principal(
                    principal_id="worker-1",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    role=None,
                    device_id=None,
                ),
            ),
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


def _plan_request(mission_id: str, *, assigned_device_id: str | None) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "missionId": mission_id,
        "siteId": "site-001",
        "missionType": "AUTONOMOUS_PATROL",
        "siteFrame": _SITE_FRAME,
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
    if assigned_device_id is not None:
        contract["assignedDeviceId"] = assigned_device_id
    return {
        "contract": contract,
        "aoi": {"vertices": _rect_aoi_vertices()},
        "route": {"altitudeM": 40.0, "captureIntervalM": 50.0},
        "drone": {"droneEnumValue": 99, "droneSubEnumValue": 0, "payloadEnumValue": 65534},
        "wayline": {
            "autoFlightSpeedMs": 5.0,
            "takeoffSecurityHeightM": 20.0,
            "globalTransitionalSpeedMs": 10.0,
        },
    }


def _client(tmp_path: Any) -> TestClient:
    private_key = Ed25519PrivateKey.generate()
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    site_store.register(
        "site-001",
        "Site 001",
        SiteFrame.model_validate(_SITE_FRAME),
        actor="test-harness",
        now=datetime.now(UTC),
    )
    advance_site_status(site_store, "site-001", SiteStatus.PATROL_READY)
    app = create_app(
        mission_signing_key=private_key,
        mission_signing_key_id="core-issuer-key-1",
        mission_store=MissionStore(DurableJournal(tmp_path / "missions.jsonl")),
        site_store=site_store,
        auth_registry=_auth_registry(),
    )
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_OPERATOR_TOKEN}"})
    return client


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _issue(
    client: TestClient, mission_id: str, *, assigned_device_id: str | None
) -> dict[str, Any]:
    response = client.post(
        "/v1/missions/plans",
        json=_plan_request(mission_id, assigned_device_id=assigned_device_id),
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# ── ① 배정된 장비는 사람과 같은 바이트를 받는다 ────────────────────────────


def test_assigned_device_downloads_the_same_bytes_the_operator_gets(tmp_path: Any) -> None:
    """[핵심] 사람 경로와 장비 경로가 **같은 해석 경로**를 쓴다는 증거.

    두 응답의 바이트가 같고 둘 다 발급 시 기록된 ``kmzSha256`` 과 일치한다. 장비용
    라우터를 따로 만들었다면 폴백 4단(캐시→재생성→해시대조→보관본) 중 하나가
    한쪽에만 남아 여기서 갈렸을 것이다.
    """
    client = _client(tmp_path)
    issued = _issue(client, "mission-assigned", assigned_device_id=_ASSIGNED_DEVICE_ID)

    by_device = client.get(
        "/v1/missions/mission-assigned/kmz", headers=_headers(_ASSIGNED_DEVICE_TOKEN)
    )
    by_operator = client.get("/v1/missions/mission-assigned/kmz")

    assert by_device.status_code == 200
    assert by_device.headers["content-type"] == "application/vnd.google-earth.kmz"
    assert hashlib.sha256(by_device.content).hexdigest() == issued["kmzSha256"]
    assert by_device.content == base64.b64decode(issued["kmzBase64"])
    assert by_operator.status_code == 200
    assert by_operator.content == by_device.content


# ── ② 다른 장비의 임무는 404 (403 이 아니다) ───────────────────────────────


def test_other_device_gets_the_same_404_as_a_mission_that_does_not_exist(
    tmp_path: Any,
) -> None:
    """[핵심] 존재하는 남의 임무와 존재하지 않는 임무가 **구분되지 않는다**.

    403 이면 "그 missionId 는 실재한다"가 응답으로 새어, 장비 토큰 하나로 임무
    식별자 공간을 열거할 수 있다(edge_dispatch.py 의 cross-device event 를 일반
    404 로 접는 것과 같은 관습).
    """
    client = _client(tmp_path)
    _issue(client, "mission-assigned", assigned_device_id=_ASSIGNED_DEVICE_ID)

    existing = client.get(
        "/v1/missions/mission-assigned/kmz", headers=_headers(_OTHER_DEVICE_TOKEN)
    )
    absent = client.get(
        "/v1/missions/mission-does-not-exist/kmz", headers=_headers(_OTHER_DEVICE_TOKEN)
    )

    assert existing.status_code == 404
    assert absent.status_code == 404
    assert existing.json() == absent.json(), "실재하는 남의 임무와 없는 임무가 구분된다"
    assert "content-disposition" not in existing.headers


# ── ③ 미배정 임무도 장비에겐 404 ───────────────────────────────────────────


def test_unassigned_mission_is_not_open_to_any_device(tmp_path: Any) -> None:
    """배정 없음을 "아무 장비나 가져가도 되는 임무"로 읽지 않는다(INV-011/012).

    사람은 같은 임무를 정상적으로 받는다 — 막히는 것은 장비 축 하나뿐이다.
    """
    client = _client(tmp_path)
    _issue(client, "mission-unassigned", assigned_device_id=None)

    by_device = client.get(
        "/v1/missions/mission-unassigned/kmz", headers=_headers(_ASSIGNED_DEVICE_TOKEN)
    )
    by_operator = client.get("/v1/missions/mission-unassigned/kmz")

    assert by_device.status_code == 404
    assert by_operator.status_code == 200


# ── ④ 새 권한은 KMZ 하나만 연다 ────────────────────────────────────────────


def test_kmz_permission_does_not_open_the_mission_record_surface(tmp_path: Any) -> None:
    """[핵심] 장비는 자기 임무의 KMZ 는 받지만 그 임무의 **상세는 못 읽는다**.

    이게 깨지면 ``MISSIONS_READ`` 대신 좁은 권한을 새로 만든 이유 자체가 사라진다
    — 상세 표면이 열리는 순간 장비 하나가 뚫렸을 때의 노출 범위가 목록·좌표·원본
    미디어로 되돌아간다. 권한 집합 자체와 실제 라우트 응답을 함께 본다(집합만 보면
    라우트가 다른 권한으로 열려 있어도 통과한다).
    """
    client = _client(tmp_path)
    _issue(client, "mission-assigned", assigned_device_id=_ASSIGNED_DEVICE_ID)
    device = Principal(
        principal_id="edge-assigned",
        kind=PrincipalKind.EDGE_DEVICE,
        role=None,
        device_id=_ASSIGNED_DEVICE_ID,
    )

    granted = principal_permissions(device)

    assert Permission.EDGE_MISSION_KMZ_READ in granted
    assert Permission.MISSIONS_READ not in granted
    assert (
        client.get(
            "/v1/missions/mission-assigned/kmz", headers=_headers(_ASSIGNED_DEVICE_TOKEN)
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/v1/missions/mission-assigned", headers=_headers(_ASSIGNED_DEVICE_TOKEN)
        ).status_code
        == 403
    )


# ── ⑤ 401 / 403 / 404 가 서로 구분된 채로 남는다 ───────────────────────────


def test_unauthenticated_is_401_and_permissionless_principal_is_403(tmp_path: Any) -> None:
    """세 층이 한 층으로 뭉개지지 않았는가.

    PROCESSING_WORKER 는 권한 고정집합이 ``{PROCESSING_WORK}`` 뿐이라, 두 KMZ
    권한 어느 쪽도 없는 유일한 주체다 — 사람 역할 3개는 전부 ``MISSIONS_READ`` 를
    갖는다.
    """
    client = _client(tmp_path)
    _issue(client, "mission-assigned", assigned_device_id=_ASSIGNED_DEVICE_ID)
    anonymous = TestClient(client.app)

    assert anonymous.get("/v1/missions/mission-assigned/kmz").status_code == 401
    assert (
        client.get(
            "/v1/missions/mission-assigned/kmz", headers=_headers(_WORKER_TOKEN)
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/v1/missions/mission-assigned/kmz", headers=_headers(_ASSIGNED_DEVICE_TOKEN)
        ).status_code
        == 200
    )
