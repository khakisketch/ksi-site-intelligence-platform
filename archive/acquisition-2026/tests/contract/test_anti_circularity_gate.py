"""ADR-KSI-019 D3 회귀 게이트 — 최초 매핑 임무는 공간모델 없이 생성 가능해야 한다.

## 왜 이 게이트가 별도 파일인가

목표를 "3D/Point Cloud 기반 자율비행"으로 적으면 목표 문장이 순환한다 — 공간모델이
아직 없는 최초 현장에서 3D 를 만들려면 3D 가 먼저 필요해진다(ADR-KSI-019 §1).
2026-08-15 실사 결과 **현재 코드에는 그 순환이 없다**: 경로 생성기(``coverage.py``)
와 짝 발급(``mission_plans.py``) 어디에도 DSM·Point Cloud 입력이 없다.

그래서 이 파일이 지키는 것은 신규 요구가 아니라 **현재 성질의 회귀 금지**다.
AOL-1~3 구현 중 누군가 "지형을 알면 경로가 더 좋아진다"는 이유로 계획 경로에
공간모델 조회를 필수로 끼워 넣으면, 그 순간 최초 현장이 영원히 매핑 불가가 된다.
AOL-3 의 지형 인지 기능은 반드시 **선택적 강화**로 들어가야 하고(D3), 없으면
AOL-1 경로가 그대로 나와야 한다.

## 무엇을 검사하는가

① ``processing_job_store`` 가 조립되지 않은 — 즉 이 현장에 어떤 재구성 epoch 도
존재할 수 없는 — 앱에서 ``UNMAPPED`` 현장에 ``BASELINE_MAPPING`` 짝 발급이 201 로
성공한다. ② 발급 응답이 실제로 웨이포인트와 KMZ 를 담는다(201 만 보고 넘어가면
"빈 경로를 성공이라 부르는" 회귀를 놓친다). ③ 경로 계획 패키지가 재구성·공간모델
모듈에 **의존하기 시작하는 순간**을 의존 방향으로 잡는다.

## fixture 를 공유 conftest 로 빼지 않는 이유

이 게이트는 다른 테스트의 fixture 변경에 영향받지 않고 독립적으로 서 있어야 한다.
``test_mission_plans.py`` 의 조립 관용구를 의도적으로 복제한다 — 중복이 여기서는
비용이 아니라 격리다.
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _site_lifecycle import advance_site_status
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
from ksi_core.mission_records import MissionStore
from ksi_core.sites import SiteStore
from ksi_domain.enums import SiteStatus
from ksi_geo_core.frames import WGS84_EQUATORIAL_RADIUS_M
from ksi_mission_contracts.models import SiteFrame

_LAT0, _LON0 = 37.5000, 127.0000
_M_PER_DEG_LAT = math.radians(1.0) * WGS84_EQUATORIAL_RADIUS_M
_TOKEN = "anti-circularity-issuer-token"  # noqa: S105 — 테스트 고정 토큰
_SITE_FRAME: dict[str, str] = {
    "crs": "EPSG:5186",
    "verticalDatum": "KNGeoid2018",
    "unit": "meter",
    "transformVersion": "1.0.0",
}


def _rect_aoi_vertices() -> list[dict[str, float]]:
    dlat = 100.0 / _M_PER_DEG_LAT
    dlon = 200.0 / (_M_PER_DEG_LAT * math.cos(math.radians(_LAT0)))
    return [
        {"lat_deg": _LAT0, "lon_deg": _LON0},
        {"lat_deg": _LAT0, "lon_deg": _LON0 + dlon},
        {"lat_deg": _LAT0 + dlat, "lon_deg": _LON0 + dlon},
        {"lat_deg": _LAT0 + dlat, "lon_deg": _LON0},
    ]


def _mapping_plan_request() -> dict[str, Any]:
    """최초 매핑 임무 짝 발급 요청 — 공간모델을 가리키는 필드가 하나도 없다."""
    return {
        "contract": {
            "missionId": "mission-anti-circularity-1",
            "siteId": "site-001",
            "missionType": "BASELINE_MAPPING",
            "siteFrame": dict(_SITE_FRAME),
            "flightEnvelope": {
                "allowedVolumes": ["vol-1"],
                "excludedVolumes": [],
                "minAltitudeM": 5.0,
                "maxAltitudeM": 120.0,
            },
            "objectives": ["최초 매핑"],
            "viewpointPolicyId": "vp-1",
            "riskPolicyPackId": "risk-1",
            "fallbackPolicyId": "fb-1",
            "capturePolicyId": "cap-1",
        },
        "aoi": {"vertices": _rect_aoi_vertices()},
        "route": {"altitudeM": 40.0, "spacingM": 20.0, "captureIntervalM": 15.0},
        "drone": {"droneEnumValue": 99, "droneSubEnumValue": 0, "payloadEnumValue": 65534},
        "wayline": {
            "autoFlightSpeedMs": 5.0,
            "takeoffSecurityHeightM": 20.0,
            "globalTransitionalSpeedMs": 10.0,
        },
    }


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_TOKEN.encode("utf-8")).hexdigest(),
                principal=Principal(
                    principal_id="do-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            )
        ]
    )


class _InMemoryKmzStorage:
    """KMZ 보관·조회만 하는 스텁. presigned 경로는 이 파일이 쓰지 않으므로 즉시 실패한다."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        del content_type
        self.objects[object_key] = data

    def get_bytes(self, object_key: str) -> bytes:
        return self.objects[object_key]

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        raise NotImplementedError

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        raise NotImplementedError

    def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)


def _client_without_processing_jobs(tmp_path: Path) -> TestClient:
    """재구성 원장이 **존재하지 않는** 조립 — 이 앱에는 공간모델이 있을 수 없다.

    ``create_app`` 에 ``processing_job_store`` 를 넘기지 않으므로 처리 작업 표면
    자체가 장착되지 않는다. 이 앱에서 매핑 임무가 발급된다면, 발급 경로가 공간모델을
    필요로 하지 않는다는 뜻이다.
    """
    private_key = Ed25519PrivateKey.generate()
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    site_store.register(
        "site-001",
        "Site 001",
        SiteFrame.model_validate(dict(_SITE_FRAME)),
        actor="test-harness",
        now=datetime.now(UTC),
    )
    advance_site_status(site_store, "site-001", SiteStatus.UNMAPPED)

    app = create_app(
        mission_signing_key=private_key,
        mission_signing_key_id="core-issuer-key-1",
        mission_store=MissionStore(DurableJournal(tmp_path / "missions.jsonl")),
        site_store=site_store,
        auth_registry=_auth_registry(),
        evidence_storage=_InMemoryKmzStorage(),
    )
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


def test_baseline_mapping_pair_issues_without_any_spatial_model(tmp_path: Path) -> None:
    """[핵심] 재구성 원장이 아예 없는 조립에서도 최초 매핑 임무가 발급된다."""
    client = _client_without_processing_jobs(tmp_path)

    response = client.post("/v1/missions/plans", json=_mapping_plan_request())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["routePattern"] == "lawnmower"
    assert body["waypointCount"] > 0, "경로가 비어 있으면 발급 성공이 거짓말이다"
    assert body["kmzSha256"], "KMZ 가 없으면 DJI 가 읽을 비행파일이 없다"

    kmz = base64.b64decode(body["kmzBase64"])
    with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
        assert "wpmz/waylines.wpml" in archive.namelist()


def test_processing_job_surface_is_really_absent_in_that_assembly(tmp_path: Path) -> None:
    """공허 방지 — 위 테스트의 조립이 정말로 재구성 표면을 갖지 않는지 확인한다.

    이걸 확인하지 않으면 "공간모델 없이 발급된다"는 주장이 그저 "그 앱에도 재구성
    원장이 있었지만 비어 있었다"였을 수 있다.
    """
    client = _client_without_processing_jobs(tmp_path)

    assert client.get("/v1/processing-jobs/whatever").status_code == 404
    assert client.get("/v1/sites/site-001/processing-jobs").status_code == 404


def test_mission_planning_package_does_not_import_spatial_model_modules() -> None:
    """경로 계획 패키지가 공간모델·재구성 모듈에 의존하기 시작하면 실패한다.

    런타임 호출을 못 잡는 대신 **의존 방향**을 잡는다 — 계획기가 재구성 산출물
    모듈을 import 하는 순간이 ADR-KSI-019 D3 가 깨지기 시작하는 지점이다.
    """
    planning_src = Path(__file__).resolve().parents[2] / "packages" / "mission-planning" / "src"
    assert planning_src.is_dir(), f"경로 계획 패키지를 찾지 못했다: {planning_src}"

    forbidden = (
        "ksi_core.processing_jobs",
        "ksi_core.spatial_model",
        "processing_artifact",
        "point_cloud",
    )
    offenders: list[str] = []
    scanned = 0
    for path in sorted(planning_src.rglob("*.py")):
        scanned += 1
        text = path.read_text(encoding="utf-8")
        offenders.extend(f"{path.name}: {needle}" for needle in forbidden if needle in text)

    assert scanned > 0, "스캔한 파일이 0건이면 이 테스트는 공허하다"
    assert not offenders, (
        "경로 계획 패키지가 공간모델/재구성 모듈에 의존한다 — ADR-KSI-019 D3 위반. "
        "지형 인지는 선택적 강화로만 들어가야 하고, 없으면 AOL-1 경로가 그대로 "
        f"나와야 한다: {offenders}"
    )
