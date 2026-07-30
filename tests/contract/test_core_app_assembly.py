"""``ksi_core.app.create_app`` fail-closed 결합 규칙 전수 검증 (ADR-KSI-008 §3).

app.py 의 조립 규칙(모듈 docstring "fail-closed 조립" 절, 4항목)이 실제로
``ValueError`` 를 던지는지 이전에는 0건이 검증하고 있었다(재검토 P3) — 오염된
부분 조립(인증 없는 보호 표면·미기록 발급·조용한 유실 표면)이 조용히 기동해도
어떤 테스트도 잡지 못하는 사각지대였다.

이 파일은 4 갈래를 전수 검증한다:
1. 보호 표면(edge_sync_store·event_store·site_store·mission_store) 각각
   단독으로 주어지고 ``auth_registry`` 가 없으면 ``ValueError``.
2. 서명키(+key_id)만 주어지고 ``mission_store``/``site_store`` 가 없으면
   ``ValueError``(고아 발급 금지 규칙이 auth_registry 규칙보다 먼저 걸린다).
3. ``edge_sync_store`` 만 주어지고 ``event_store`` 가 없으면 ``ValueError``
   (조용한 유실 표면 방지 규칙).
4. 위 규칙을 전부 만족하는 전량 정상 조립은 성공한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.edge_sync import EdgeSyncStore
from ksi_core.events import EventStore
from ksi_core.mission_records import MissionStore
from ksi_core.sites import SiteStore


def _digest(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest("assembly-test-token"),
                principal=Principal(
                    principal_id="op-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )


def _event_store(tmp_path: Path) -> EventStore:
    return EventStore(DurableJournal(tmp_path / "events" / "journal.jsonl"))


def _site_store(tmp_path: Path) -> SiteStore:
    return SiteStore(DurableJournal(tmp_path / "sites.jsonl"))


def _mission_store(tmp_path: Path) -> MissionStore:
    return MissionStore(DurableJournal(tmp_path / "missions.jsonl"))


def _edge_sync_store(tmp_path: Path) -> EdgeSyncStore:
    return EdgeSyncStore(tmp_path / "edge-journal.jsonl")


# ── 규칙 1: 보호 표면 각각 단독으로 auth_registry 없이 → ValueError ──────────
#
# edge_sync_store·서명키는 각자 다른 규칙(3·2)이 auth_registry 검사보다 먼저
# 걸리므로, 규칙 1 을 순수하게 격리하려면 그 선행 규칙을 만족시키는 동반 인자를
# 함께 준다(그래도 auth_registry 는 여전히 없다).


def test_event_store_alone_without_auth_registry_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="auth_registry"):
        create_app(event_store=_event_store(tmp_path))


def test_site_store_alone_without_auth_registry_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="auth_registry"):
        create_app(site_store=_site_store(tmp_path))


def test_mission_store_alone_without_auth_registry_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="auth_registry"):
        create_app(mission_store=_mission_store(tmp_path))


def test_edge_sync_store_with_event_store_but_no_auth_registry_raises(tmp_path: Path) -> None:
    """edge_sync_store 규칙(규칙 3)을 만족시켜 규칙 1(auth_registry)만 격리."""
    with pytest.raises(ValueError, match="auth_registry"):
        create_app(
            edge_sync_store=_edge_sync_store(tmp_path),
            event_store=_event_store(tmp_path),
        )


def test_signing_key_with_stores_but_no_auth_registry_raises(tmp_path: Path) -> None:
    """서명키 규칙(규칙 2)을 만족시켜 규칙 1(auth_registry)만 격리."""
    with pytest.raises(ValueError, match="auth_registry"):
        create_app(
            mission_store=_mission_store(tmp_path),
            site_store=_site_store(tmp_path),
            mission_signing_key=Ed25519PrivateKey.generate(),
            mission_signing_key_id="k",
        )


# ── 규칙 2: 서명키만(스토어 없이) → ValueError ────────────────────────────


def test_signing_key_alone_without_stores_raises(tmp_path: Path) -> None:
    del tmp_path
    with pytest.raises(ValueError, match="mission_store.*site_store"):
        create_app(
            mission_signing_key=Ed25519PrivateKey.generate(),
            mission_signing_key_id="k",
        )


def test_signing_key_half_configured_raises(tmp_path: Path) -> None:
    """key 만 있고 key_id 가 없으면(또는 그 반대) 절반 서명 설정으로 조립하지 않는다."""
    del tmp_path
    with pytest.raises(ValueError, match="mission_signing_key"):
        create_app(mission_signing_key=Ed25519PrivateKey.generate())


# ── 규칙 3: edge_sync_store 만(event_store 없이) → ValueError ──────────────


def test_edge_sync_store_alone_without_event_store_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="event_store"):
        create_app(edge_sync_store=_edge_sync_store(tmp_path))


# ── 규칙 4: 전량 정상 조립 → 성공 ──────────────────────────────────────────


def test_full_assembly_succeeds(tmp_path: Path) -> None:
    app = create_app(
        auth_registry=_auth_registry(),
        edge_sync_store=_edge_sync_store(tmp_path),
        event_store=_event_store(tmp_path),
        site_store=_site_store(tmp_path),
        mission_store=_mission_store(tmp_path),
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="assembly-test-key",
    )
    paths = set(app.openapi()["paths"])
    # 전량 조립이면 각 표면의 대표 경로가 전부 장착된다(조건부 라우터 누락 방지).
    assert {
        "/v1/sites",
        "/v1/events",
        "/v1/edge-sync/event-bundles",
        "/v1/missions/contracts",
        "/v1/missions/plans",
        "/v1/missions",
    } <= paths


# ── expose_docs 스위치 (재검토 P2 — "문서 라우트만 공개" 반증에 대한 조치) ──


def test_expose_docs_default_true_exposes_doc_routes() -> None:
    app = create_app(expose_docs=True)
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert {"/openapi.json", "/docs", "/redoc"} <= route_paths


def test_expose_docs_false_removes_doc_routes() -> None:
    app = create_app(expose_docs=False)
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/openapi.json" not in route_paths
    assert "/docs" not in route_paths
    assert "/redoc" not in route_paths
