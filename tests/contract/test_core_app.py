"""KSI Core FastAPI 골격 검증 (Stage C-2).

green≠작동 초점: "앱이 뜬다"가 아니라 **INV-041 노출 게이트가 HTTP 경계에서도 실제로
막는지**를 확인한다 — 레지스트리 단위 테스트(test_capability_gate.py)가 통과해도
API 계층이 list_all()을 잘못 부르면 미검증 기능이 새어나간다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.capability.registry import CapabilityRegistry, seed_prd_spikes
from ksi_domain.capability import CapabilityVerificationState


@pytest.fixture
def seeded_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    seed_prd_spikes(registry)
    return registry


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_capabilities_empty_when_only_spikes_seeded(seeded_registry: CapabilityRegistry) -> None:
    """[INV-041] PRD §20.3 SPIKE 9종을 시드해도 운영 API 노출은 0건이어야 한다."""
    client = TestClient(create_app(registry=seeded_registry))

    response = client.get("/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["capabilities"] == []
    # 레지스트리에는 9건이 존재하지만(감사용) API로는 하나도 나가지 않는다.
    assert len(seeded_registry.list_all()) == 9


def test_default_app_seeds_spikes_and_exposes_none() -> None:
    """registry 미주입 기본 앱도 시드 직후 노출 0건 — 안전한 기본값."""
    client = TestClient(create_app())
    body = client.get("/capabilities").json()
    assert body["count"] == 0


def test_verified_capability_appears_in_api(seeded_registry: CapabilityRegistry) -> None:
    capability_id = seeded_registry.list_all()[0].capability_id
    seeded_registry.transition(
        capability_id,
        CapabilityVerificationState.VERIFIED,
        evidence="HIL 2026-07-26 실기 검증 로그 #99",
        firmware="v08.02.0100",
        sdk="PSDK 3.9",
        aircraft="Matrice 4D",
    )
    client = TestClient(create_app(registry=seeded_registry))

    body = client.get("/capabilities").json()

    assert body["count"] == 1
    entry = body["capabilities"][0]
    assert entry["capabilityId"] == capability_id
    assert entry["state"] == "VERIFIED"
    assert entry["aircraft"] == "Matrice 4D"
    assert entry["verifiedAt"] is not None


def test_blocked_capability_never_appears_in_api(seeded_registry: CapabilityRegistry) -> None:
    """[INV-041] BLOCKED는 감사 목록에만 있고 운영 API에는 절대 없다."""
    capability_id = seeded_registry.list_all()[0].capability_id
    seeded_registry.transition(
        capability_id,
        CapabilityVerificationState.BLOCKED,
        evidence="DJI Cloud API 제3자 Payload 미지원 확인",
    )
    client = TestClient(create_app(registry=seeded_registry))

    body = client.get("/capabilities").json()

    assert body["count"] == 0
    assert all(entry["capabilityId"] != capability_id for entry in body["capabilities"])


def test_regressed_capability_disappears_from_api(seeded_registry: CapabilityRegistry) -> None:
    """VERIFIED→BLOCKED 회귀가 API 노출에서도 즉시 사라져야 한다."""
    capability_id = seeded_registry.list_all()[0].capability_id
    seeded_registry.transition(
        capability_id, CapabilityVerificationState.VERIFIED, evidence="최초 HIL 통과"
    )
    client = TestClient(create_app(registry=seeded_registry))
    assert client.get("/capabilities").json()["count"] == 1

    seeded_registry.transition(
        capability_id, CapabilityVerificationState.BLOCKED, evidence="후속 펌웨어 회귀 발견"
    )

    assert client.get("/capabilities").json()["count"] == 0


def test_core_exposes_no_flight_control_routes() -> None:
    """[INV-001] Core에 프레임별 비행제어 경로가 존재하지 않는다 — 라우트 목록으로 확인."""
    app = create_app()
    paths = {route.path for route in app.routes}  # type: ignore[attr-defined]

    forbidden_fragments = ("command", "control", "flight", "velocity", "attitude", "waypoint")
    offending = [
        path
        for path in paths
        if any(fragment in path.lower() for fragment in forbidden_fragments)
    ]
    assert offending == [], f"Core에 비행제어로 보이는 경로가 있다: {offending}"
