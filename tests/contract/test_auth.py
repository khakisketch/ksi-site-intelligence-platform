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
    _ROLE_PERMISSIONS,
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


def _operator_principal(role: Role = Role.VIEWER, principal_id: str = "op-1") -> Principal:
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
            Permission.SITES_AUTONOMY_APPROVE,
            Permission.EQUIPMENT_SUPPORT_APPROVE,
        }
    )
    assert Permission.EDGE_SYNC_INGEST not in perms


def test_field_operator_permissions() -> None:
    """FIELD_OPERATOR = 구 5역할 중 현장관리·안전관리·드론운영 3역할 통합
    (ADR-KSI-015 D1) — SITES_AUTONOMY_APPROVE 만 없다."""
    perms = principal_permissions(_operator_principal(role=Role.FIELD_OPERATOR))
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
    assert Permission.SITES_AUTONOMY_APPROVE not in perms
    assert Permission.EQUIPMENT_SUPPORT_APPROVE not in perms


def test_viewer_permissions() -> None:
    perms = principal_permissions(_operator_principal(role=Role.VIEWER))
    assert perms == frozenset(
        {Permission.SITES_READ, Permission.MISSIONS_READ, Permission.EVENTS_READ}
    )


def test_edge_device_permissions_fixed_regardless_of_role_table() -> None:
    perms = principal_permissions(_device_principal())
    assert perms == frozenset({Permission.EDGE_SYNC_INGEST})


# ── 구조 불변식(ADR-KSI-015) — 역할 이름과 무관해 다음 재편에도 살아남는다 ──────
#
# 이번 사고(구 현장관리 역할에 MISSIONS_ISSUE 가 빠져 실사용자로 못박힌 현장소장이
# 조사계획을 못 냈다, ADR-KSI-015 맥락)의 재발 방지 그 자체 — "표를 고쳤다"가
# 아니라 "표가 갖춰야 할 성질"을 고정한다.


def test_role_enum_matches_permission_table_keys() -> None:
    """enum 멤버 추가 시 표 누락을 즉시 잡는다 — 새 역할이 조용히 무권한이 되지 않는다."""
    assert set(Role) == set(_ROLE_PERMISSIONS)


def test_admin_is_a_strict_superset_of_field_operator() -> None:
    """ADMIN ⊋ FIELD_OPERATOR — 같아지는 순간 관리자가 라벨로 전락한다(ADR D2)."""
    admin_perms = _ROLE_PERMISSIONS[Role.ADMIN]
    field_operator_perms = _ROLE_PERMISSIONS[Role.FIELD_OPERATOR]
    assert field_operator_perms < admin_perms


def test_viewer_has_no_write_permissions() -> None:
    viewer_perms = _ROLE_PERMISSIONS[Role.VIEWER]
    write_permissions = {
        Permission.SITES_WRITE,
        Permission.MISSIONS_ISSUE,
        Permission.EVENTS_TRIAGE,
        Permission.SITES_AUTONOMY_APPROVE,
    }
    assert viewer_perms.isdisjoint(write_permissions)


_WRITE_PERMISSIONS = (
    Permission.SITES_WRITE,
    Permission.MISSIONS_ISSUE,
    Permission.EVENTS_TRIAGE,
    Permission.SITES_AUTONOMY_APPROVE,
)


@pytest.mark.parametrize("perm", _WRITE_PERMISSIONS)
def test_every_write_permission_has_a_role_without_it(perm: Permission) -> None:
    """쓰기 계열 권한마다 그것을 갖지 않는 OPERATOR 역할이 최소 1개 있어야 한다.

    이게 없으면 어떤 쓰기 권한을 요구하는 엔드포인트도 HTTP 403 음성 케이스를
    쓸 앵커가 사라진다 — 그 상태에서 role→permission 표가 잘못 넓어져도
    (이번 사고처럼) 아무 테스트도 실패하지 않는다.
    """
    assert any(perm not in perms for perms in _ROLE_PERMISSIONS.values())


def test_no_role_has_edge_sync_ingest() -> None:
    """EDGE_DEVICE 전용 권한이 어떤 사람 역할에도 새지 않는다."""
    assert all(Permission.EDGE_SYNC_INGEST not in perms for perms in _ROLE_PERMISSIONS.values())


def test_no_role_has_processing_work() -> None:
    """[핵심] 워커 전용 권한이 어떤 사람 역할에도 새지 않는다.

    이게 깨지면 사람이 처리 작업의 ``SUCCEEDED`` 를 손으로 찍을 수 있게 되고,
    그 순간 그 상태는 실행 근거가 아니라 주장이 된다(processing_jobs.py
    전이 권한표). ADMIN 을 포함한 **모든** 역할이 대상이다.
    """
    assert all(Permission.PROCESSING_WORK not in perms for perms in _ROLE_PERMISSIONS.values())


def _worker(**overrides: object) -> Principal:
    fields: dict[str, object] = {
        "principal_id": "worker-1",
        "kind": PrincipalKind.PROCESSING_WORKER,
        "role": None,
        "device_id": None,
    }
    fields.update(overrides)
    return Principal(**fields)  # type: ignore[arg-type]


def test_processing_worker_permissions_are_fixed() -> None:
    assert principal_permissions(_worker()) == frozenset({Permission.PROCESSING_WORK})


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"role": Role.ADMIN}, "role 을 가질 수 없다"),
        # 재구성 워커는 기체가 아니다 — device_id 를 허용하면 존재하지 않는
        # 기체 식별자가 eventKey 경로로 흘러든다.
        ({"device_id": "drone-1"}, "device_id 를 가질 수 없다"),
    ],
)
def test_processing_worker_rejects_foreign_identity_fields(
    overrides: dict[str, object], match: str
) -> None:
    with pytest.raises(AuthRegistryError, match=match):
        AuthRegistry(
            [PrincipalTokenRecord(token_sha256="a" * 64, principal=_worker(**overrides))]
        )


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
                principal=_operator_principal(role=Role.FIELD_OPERATOR, principal_id="fo-1"),
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
                principal=_operator_principal(role=Role.FIELD_OPERATOR, principal_id="fo-1"),
            )
        ]
    )
    app = _app_with_protected_route(registry)
    client = TestClient(app)

    response = client.get(
        "/v1/sites/_protected", headers={"Authorization": f"Bearer {_OPERATOR_TOKEN}"}
    )

    assert response.status_code == 200
    assert response.json() == {"principalId": "fo-1"}


# ── whoami ────────────────────────────────────────────────────────────


def test_whoami_operator() -> None:
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_OPERATOR_TOKEN),
                principal=_operator_principal(role=Role.FIELD_OPERATOR, principal_id="fo-1"),
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
        "principalId": "fo-1",
        "kind": "OPERATOR",
        "role": "FIELD_OPERATOR",
        "deviceId": None,
        "permissions": sorted(
            [
                "SITES_READ",
                "SITES_WRITE",
                "MISSIONS_READ",
                "MISSIONS_ISSUE",
                "EVENTS_READ",
                "EVENTS_TRIAGE",
            ]
        ),
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
