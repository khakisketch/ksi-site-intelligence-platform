"""Distinct data authority and exact route boundaries; no live credential provisioning."""

from dataclasses import replace
from hashlib import sha256
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from ksi_core.identity.auth import (
    AuthRegistry,
    AuthRegistryError,
    Permission,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    principal_permissions,
    require_principal,
)

BASE = "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests"
ROUTES = (
    ("GET", BASE),
    ("POST", BASE),
    ("GET", BASE + "/{request_id}"),
    ("POST", BASE + "/{request_id}/cancel"),
    ("GET", BASE + "/{request_id}/file"),
    ("HEAD", BASE + "/{request_id}/file"),
)


def data_client() -> Principal:
    return Principal(
        "reader-local",
        PrincipalKind.SPATIAL_DATA_CLIENT,
        None,
        None,
        "org-local",
        allowed_site_ids=frozenset({"site-local"}),
        allowed_work_area_ids=frozenset({"area-local"}),
    )


def registry(principal: Principal) -> AuthRegistry:
    return AuthRegistry([PrincipalTokenRecord(sha256(b"test-token").hexdigest(), principal)])


def test_data_worker_and_client_permissions_do_not_borrow_processing_authority() -> None:
    worker = Principal("worker", PrincipalKind.SPATIAL_DATA_WORKER, None, None, "org-local")
    assert principal_permissions(worker) == frozenset({Permission.SPATIAL_DATA_WORK})
    assert registry(worker).resolve("test-token") == worker
    assert principal_permissions(data_client()) == frozenset(
        {Permission.SPATIAL_DATA_READ, Permission.SPATIAL_DATA_REQUEST}
    )
    for kind in (PrincipalKind.PROCESSING_WORKER, PrincipalKind.EDGE_DEVICE):
        old = Principal("old", kind, None, "device" if kind == PrincipalKind.EDGE_DEVICE else None)
        assert not {
            Permission.SPATIAL_DATA_READ,
            Permission.SPATIAL_DATA_REQUEST,
            Permission.SPATIAL_DATA_WORK,
        } & principal_permissions(old)


@pytest.mark.parametrize("role", list(Role))
def test_operator_data_permissions_preserve_read_write_distinction(role: Role) -> None:
    permissions = principal_permissions(Principal("operator", PrincipalKind.OPERATOR, role, None))
    assert Permission.SPATIAL_DATA_READ in permissions
    assert (Permission.SPATIAL_DATA_REQUEST in permissions) == (role != Role.VIEWER)
    assert Permission.SPATIAL_DATA_WORK not in permissions


@pytest.mark.parametrize("field", ["allowed_site_ids", "allowed_work_area_ids"])
@pytest.mark.parametrize("value", [None, frozenset(), {"site-local"}, frozenset({"bad/path"})])
def test_data_client_requires_explicit_immutable_nonempty_scopes(field: str, value: Any) -> None:
    with pytest.raises(AuthRegistryError):
        registry(replace(data_client(), **{field: value}))


@pytest.mark.parametrize("kind", ["SPATIAL_DATA_CLIENT", "SPATIAL_DATA_WORKER"])
@pytest.mark.parametrize("field,value", [("role", Role.ADMIN), ("device_id", "device")])
def test_data_principals_cannot_pose_as_human_or_device(
    kind: PrincipalKind, field: str, value: Any
) -> None:
    principal = replace(data_client(), kind=PrincipalKind(kind), **{field: value})
    with pytest.raises(AuthRegistryError):
        registry(principal)


def test_data_scope_change_cannot_hide_in_token_rotation() -> None:
    first = data_client()
    changed = replace(first, allowed_work_area_ids=frozenset({"other"}))
    with pytest.raises(AuthRegistryError):
        AuthRegistry(
            [
                PrincipalTokenRecord(sha256(b"first").hexdigest(), first),
                PrincipalTokenRecord(sha256(b"second").hexdigest(), changed),
            ]
        )


@pytest.mark.parametrize("method,path", ROUTES)
def test_only_exact_data_route_templates_are_allowed(method: str, path: str) -> None:
    app = FastAPI()
    app.state.auth_registry = registry(data_client())

    def handler(principal: Principal = Depends(require_principal())) -> dict[str, str]:  # noqa: B008
        return {"principal": principal.principal_id}

    app.add_api_route(path, handler, methods=[method])
    concrete = path.format(site_id="site-local", work_area_id="area-local", request_id="job")
    with TestClient(app) as client:
        assert (
            client.request(
                method, concrete, headers={"Authorization": "Bearer test-token"}
            ).status_code
            == 200
        )


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/v1/sites"),
        ("GET", BASE + "/{request_id}/file/extra"),
        ("DELETE", BASE + "/{request_id}"),
        ("POST", "/v1/internal/spatial-data-jobs/job/lease"),
    ],
)
@pytest.mark.parametrize("scoped_operator", [False, True])
def test_data_scope_denies_unreviewed_routes_but_preserves_reviewed_human_sites(
    method: str, path: str, scoped_operator: bool
) -> None:
    principal = data_client()
    if scoped_operator:
        principal = replace(principal, kind=PrincipalKind.OPERATOR, role=Role.ADMIN)
    app = FastAPI()
    app.state.auth_registry = registry(principal)

    def handler(principal: Principal = Depends(require_principal())) -> dict[str, str]:  # noqa: B008
        return {"principal": principal.principal_id}

    app.add_api_route(path, handler, methods=[method])
    concrete = path.format(site_id="site-local", work_area_id="area-local", request_id="job")
    with TestClient(app) as client:
        assert client.request(
            method, concrete, headers={"Authorization": "Bearer test-token"}
        ).status_code == (
            200 if scoped_operator and (method, path) == ("GET", "/v1/sites") else 403
        )
