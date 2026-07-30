"""Bearer 토큰 인증·역할 권한 계약 (ADR-KSI-008 §2).

green≠작동 초점: 레지스트리 불변식(생성 거부)뿐 아니라 **HTTP 경계에서** 401/403
이 사유별로 정확히 갈리는지, WWW-Authenticate 헤더가 실리는지, 존재 여부 힌트가
detail 에 새지 않는지를 확인한다. 수동 조립(app=FastAPI(); mount_auth(...))으로
edge_sync.py 류의 "무인증 표면은 존재할 수 없다" fail-closed 배선을 직접 검증한다.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    AuthRegistryError,
    Permission,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    build_auth_router,
    mount_auth,
    principal_permissions,
    require_permission,
    require_principal,
)

_OPERATOR_TOKEN = "operator-plaintext-token"
_DEVICE_TOKEN = "device-plaintext-token"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _operator_principal(role: Role = Role.SITE_MANAGER, principal_id: str = "op-1") -> Principal:
    return Principal(
        principal_id=principal_id, kind=PrincipalKind.OPERATOR, role=role, device_id=None
    )


def _device_principal(device_id: str = "dev-1", principal_id: str = "dev-principal-1") -> Principal:
    return Principal(
        principal_id=principal_id, kind=PrincipalKind.EDGE_DEVICE, role=None, device_id=device_id
    )


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_OPERATOR_TOKEN),
                principal=_operator_principal(role=Role.VIEWER, principal_id="viewer-1"),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_DEVICE_TOKEN),
                principal=_device_principal(),
            ),
        ]
    )


def _app_with_protected_route(registry: AuthRegistry) -> FastAPI:
    """mount_auth + 보호 라우트 1개를 수동 조립한다(스펙 요구 수동 조립 검증)."""
    app = FastAPI()
    mount_auth(app, registry)

    @app.get("/v1/sites/_protected")
    def protected(
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> dict[str, str]:
        return {"principalId": principal.principal_id}

    return app


# ── AuthRegistry 불변식 ──────────────────────────────────────────────────


def test_operator_requires_role() -> None:
    with pytest.raises(AuthRegistryError):
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=_digest("t1"),
                    principal=Principal(
                        principal_id="p1", kind=PrincipalKind.OPERATOR, role=None, device_id=None
                    ),
                )
            ]
        )


def test_operator_forbids_device_id() -> None:
    with pytest.raises(AuthRegistryError):
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=_digest("t1"),
                    principal=Principal(
                        principal_id="p1",
                        kind=PrincipalKind.OPERATOR,
                        role=Role.VIEWER,
                        device_id="dev-1",
                    ),
                )
            ]
        )


def test_edge_device_requires_device_id() -> None:
    with pytest.raises(AuthRegistryError):
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=_digest("t1"),
                    principal=Principal(
                        principal_id="p1",
                        kind=PrincipalKind.EDGE_DEVICE,
                        role=None,
                        device_id=None,
                    ),
                )
            ]
        )


def test_edge_device_forbids_role() -> None:
    with pytest.raises(AuthRegistryError):
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=_digest("t1"),
                    principal=Principal(
                        principal_id="p1",
                        kind=PrincipalKind.EDGE_DEVICE,
                        role=Role.VIEWER,
                        device_id="dev-1",
                    ),
                )
            ]
        )


@pytest.mark.parametrize(
    "bad_digest",
    [
        "A" * 64,  # 대문자 거부
        "z" * 64,  # hex 밖 문자
        "a" * 63,  # 길이 부족
        "a" * 65,  # 길이 초과
        "not-a-digest-at-all",  # 원문/경로 형태
        "../../etc/passwd",  # 경로 형태
        "",  # 빈 문자열
    ],
)
def test_rejects_malformed_token_digest(bad_digest: str) -> None:
    with pytest.raises(AuthRegistryError):
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=bad_digest,
                    principal=_operator_principal(),
                )
            ]
        )


def test_rejects_duplicate_digest() -> None:
    digest = _digest("shared-token")
    with pytest.raises(AuthRegistryError):
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=digest, principal=_operator_principal(Role.VIEWER, "p1")
                ),
                PrincipalTokenRecord(
                    token_sha256=digest, principal=_operator_principal(Role.VIEWER, "p2")
                ),
            ]
        )


def test_rejects_duplicate_principal_id() -> None:
    with pytest.raises(AuthRegistryError):
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=_digest("t1"), principal=_operator_principal(Role.VIEWER, "dup")
                ),
                PrincipalTokenRecord(
                    token_sha256=_digest("t2"), principal=_operator_principal(Role.VIEWER, "dup")
                ),
            ]
        )


def test_rejects_empty_principal_id() -> None:
    with pytest.raises(AuthRegistryError):
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=_digest("t1"),
                    principal=Principal(
                        principal_id="",
                        kind=PrincipalKind.OPERATOR,
                        role=Role.VIEWER,
                        device_id=None,
                    ),
                )
            ]
        )


def test_resolve_unknown_token_returns_none() -> None:
    registry = _registry()
    assert registry.resolve("no-such-token") is None


def test_resolve_known_token_returns_principal() -> None:
    registry = _registry()
    principal = registry.resolve(_OPERATOR_TOKEN)
    assert principal is not None
    assert principal.principal_id == "viewer-1"


# ── principal_permissions 표 정합 ────────────────────────────────────────


def test_admin_has_all_operator_permissions_except_edge_ingest() -> None:
    perms = principal_permissions(_operator_principal(role=Role.ADMIN))
    assert perms == frozenset(
        {
            Permission.SITES_READ,
            Permission.SITES_WRITE,
            Permission.MISSIONS_READ,
            Permission.MISSIONS_ISSUE,
            Permission.EVENTS_READ,
            Permission.EVENTS_TRIAGE,
        }
    )
    assert Permission.EDGE_SYNC_INGEST not in perms


def test_site_manager_permissions() -> None:
    perms = principal_permissions(_operator_principal(role=Role.SITE_MANAGER))
    assert perms == frozenset(
        {
            Permission.SITES_READ,
            Permission.SITES_WRITE,
            Permission.MISSIONS_READ,
            Permission.EVENTS_READ,
            Permission.EVENTS_TRIAGE,
        }
    )


def test_safety_manager_permissions() -> None:
    perms = principal_permissions(_operator_principal(role=Role.SAFETY_MANAGER))
    assert perms == frozenset(
        {
            Permission.SITES_READ,
            Permission.MISSIONS_READ,
            Permission.EVENTS_READ,
            Permission.EVENTS_TRIAGE,
        }
    )


def test_drone_operator_permissions() -> None:
    perms = principal_permissions(_operator_principal(role=Role.DRONE_OPERATOR))
    assert perms == frozenset(
        {Permission.SITES_READ, Permission.MISSIONS_READ, Permission.MISSIONS_ISSUE}
    )


def test_viewer_permissions() -> None:
    perms = principal_permissions(_operator_principal(role=Role.VIEWER))
    assert perms == frozenset(
        {Permission.SITES_READ, Permission.MISSIONS_READ, Permission.EVENTS_READ}
    )


def test_edge_device_permissions_fixed_regardless_of_role_table() -> None:
    perms = principal_permissions(_device_principal())
    assert perms == frozenset({Permission.EDGE_SYNC_INGEST})


# ── HTTP 경계: 401 3분기 + WWW-Authenticate ──────────────────────────────


def test_401_when_authorization_header_missing() -> None:
    app = _app_with_protected_route(_registry())
    client = TestClient(app)

    response = client.get("/v1/sites/_protected")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_401_when_authorization_header_malformed() -> None:
    app = _app_with_protected_route(_registry())
    client = TestClient(app)

    response = client.get(
        "/v1/sites/_protected", headers={"Authorization": f"Basic {_OPERATOR_TOKEN}"}
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_401_when_token_unknown() -> None:
    app = _app_with_protected_route(_registry())
    client = TestClient(app)

    response = client.get(
        "/v1/sites/_protected", headers={"Authorization": "Bearer no-such-token"}
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_401_detail_does_not_hint_token_existence() -> None:
    """세 401 분기가 동일한 일반 문구 — detail 로 토큰 존재 여부를 유추할 수 없다."""
    app = _app_with_protected_route(_registry())
    client = TestClient(app)

    missing = client.get("/v1/sites/_protected")
    malformed = client.get("/v1/sites/_protected", headers={"Authorization": "Basic xyz"})
    unknown = client.get("/v1/sites/_protected", headers={"Authorization": "Bearer bogus"})

    assert missing.json()["detail"] == malformed.json()["detail"] == unknown.json()["detail"]


def test_bearer_scheme_case_insensitive() -> None:
    """RFC 7235 — scheme 이름은 대소문자 무관해야 한다."""
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_OPERATOR_TOKEN),
                principal=_operator_principal(role=Role.SITE_MANAGER, principal_id="sm-1"),
            )
        ]
    )
    app = _app_with_protected_route(registry)
    client = TestClient(app)

    response = client.get(
        "/v1/sites/_protected", headers={"Authorization": f"BEARER {_OPERATOR_TOKEN}"}
    )

    assert response.status_code == 200


# ── 403 (인증은 됐으나 권한 부족) ─────────────────────────────────────────


def test_403_when_viewer_lacks_sites_write() -> None:
    app = _app_with_protected_route(_registry())
    client = TestClient(app)

    response = client.get(
        "/v1/sites/_protected", headers={"Authorization": f"Bearer {_OPERATOR_TOKEN}"}
    )

    assert response.status_code == 403


def test_200_when_principal_has_permission() -> None:
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_OPERATOR_TOKEN),
                principal=_operator_principal(role=Role.SITE_MANAGER, principal_id="sm-1"),
            )
        ]
    )
    app = _app_with_protected_route(registry)
    client = TestClient(app)

    response = client.get(
        "/v1/sites/_protected", headers={"Authorization": f"Bearer {_OPERATOR_TOKEN}"}
    )

    assert response.status_code == 200
    assert response.json() == {"principalId": "sm-1"}


# ── whoami ────────────────────────────────────────────────────────────


def test_whoami_operator() -> None:
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_OPERATOR_TOKEN),
                principal=_operator_principal(role=Role.DRONE_OPERATOR, principal_id="do-1"),
            )
        ]
    )
    app = FastAPI()
    mount_auth(app, registry)
    client = TestClient(app)

    response = client.get(
        "/v1/auth/whoami", headers={"Authorization": f"Bearer {_OPERATOR_TOKEN}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "principalId": "do-1",
        "kind": "OPERATOR",
        "role": "DRONE_OPERATOR",
        "deviceId": None,
        "permissions": sorted(["SITES_READ", "MISSIONS_READ", "MISSIONS_ISSUE"]),
    }


def test_whoami_edge_device() -> None:
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_DEVICE_TOKEN),
                principal=_device_principal(device_id="rig-42", principal_id="edge-rig-42"),
            )
        ]
    )
    app = FastAPI()
    mount_auth(app, registry)
    client = TestClient(app)

    response = client.get(
        "/v1/auth/whoami", headers={"Authorization": f"Bearer {_DEVICE_TOKEN}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "principalId": "edge-rig-42",
        "kind": "EDGE_DEVICE",
        "role": None,
        "deviceId": "rig-42",
        "permissions": ["EDGE_SYNC_INGEST"],
    }


# ── 조립 결함: state 미설정 ────────────────────────────────────────────


def test_require_principal_raises_runtime_error_without_registry_state() -> None:
    """auth_registry 없이 보호 라우트를 장착하면 조립 결함 — 조용히 통과하지 않는다."""
    app = FastAPI()

    @app.get("/unwired")
    def unwired(
        principal: Principal = Depends(require_principal()),  # noqa: B008
    ) -> dict[str, str]:
        return {"principalId": principal.principal_id}

    client = TestClient(app, raise_server_exceptions=True)

    with pytest.raises(RuntimeError):
        client.get("/unwired", headers={"Authorization": "Bearer whatever"})


def test_build_auth_router_is_reusable_without_mount() -> None:
    """build_auth_router() 는 순수 라우터 조립 — mount_auth 없이도 호출 가능해야 한다."""
    router = build_auth_router()
    assert any(route.path == "/v1/auth/whoami" for route in router.routes)  # type: ignore[attr-defined]


def test_edge_device_id_must_be_path_safe() -> None:
    """[3차 최종검토 P3] '/' 포함 device_id 는 provisioning 시점에 거부된다.

    device_id 는 event_key(={deviceId}::{eventId})의 절반으로 /v1/events/
    {event_key} 경로 세그먼트가 된다 — 검증 없이 provisioning 되면 그 장비의
    모든 ingest 가 런타임에 영구 거부되는(잘못된 경계의 fail-closed) 장비가
    만들어진다.
    """
    with pytest.raises(AuthRegistryError, match="경로-안전"):
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=_digest("t1"),
                    principal=Principal(
                        principal_id="p1",
                        kind=PrincipalKind.EDGE_DEVICE,
                        role=None,
                        device_id="edge/1",
                    ),
                )
            ]
        )
