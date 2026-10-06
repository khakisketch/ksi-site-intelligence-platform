"""Isolated Spatial Data MCP client identity: fixed permissions and exact routes."""

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

DATA_BASE = "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests"
ASSET_BASE = "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-assets"
MCP_ROUTES = (
    ("GET", DATA_BASE),
    ("POST", DATA_BASE),
    ("GET", DATA_BASE + "/{request_id}"),
    ("POST", DATA_BASE + "/{request_id}/cancel"),
    ("GET", DATA_BASE + "/{request_id}/file"),
    ("HEAD", DATA_BASE + "/{request_id}/file"),
    ("GET", ASSET_BASE),
    ("GET", ASSET_BASE + "/{asset_ref}"),
)
DENIED_ROUTES = (
    ("GET", "/v1/sites"),
    ("GET", "/v1/sites/{site_id}/analysis-observations"),
    ("POST", "/v2/sites/{site_id}/work-areas/{work_area_id}/analyses"),
    ("GET", "/v2/sites/{site_id}/analyses"),
    ("GET", "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-assets"),
    ("GET", "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-assets/{asset_ref}"),
    ("GET", DATA_BASE + "/{request_id}/file/extra"),
    ("GET", ASSET_BASE + "/{asset_id}"),
    ("DELETE", DATA_BASE + "/{request_id}"),
    ("POST", "/v1/internal/spatial-data-jobs/job/lease"),
    ("POST", "/v1/sites/{site_id}/work-areas"),
)


def mcp_client() -> Principal:
    return Principal(
        "spatial-data-mcp-client-local",
        PrincipalKind.SPATIAL_DATA_MCP_CLIENT,
        None,
        None,
        "org-local",
        allowed_site_ids=frozenset({"site-local"}),
        allowed_work_area_ids=frozenset({"area-local"}),
    )


def registry(principal: Principal) -> AuthRegistry:
    return AuthRegistry([PrincipalTokenRecord(sha256(b"mcp-test-token").hexdigest(), principal)])


def _app(principal: Principal) -> FastAPI:
    app = FastAPI()
    app.state.auth_registry = registry(principal)
    return app


def _get(app: FastAPI, method: str, path: str) -> int:
    def handler(principal: Principal = Depends(require_principal())) -> dict[str, str]:  # noqa: B008
        return {"principal": principal.principal_id}

    app.add_api_route(path, handler, methods=[method])
    concrete = path.format(
        site_id="site-local",
        work_area_id="area-local",
        request_id="job",
        asset_ref="asset",
        asset_id="asset",
    )
    with TestClient(app) as client:
        return client.request(
            method, concrete, headers={"Authorization": "Bearer mcp-test-token"}
        ).status_code


def test_ai_identity_exact_routes() -> None:
    assert {PrincipalKind.SPATIAL_DATA_MCP_CLIENT.value} == {"SPATIAL_DATA_MCP_CLIENT"}
    assert len(MCP_ROUTES) == 8
    for method, path in MCP_ROUTES:
        assert _get(_app(mcp_client()), method, path) == 200


@pytest.mark.parametrize("method,path", DENIED_ROUTES)
def test_ai_identity_denies_analysis_catalog_internal_and_global_routes(
    method: str, path: str
) -> None:
    assert _get(_app(mcp_client()), method, path) == 403


def test_ai_identity_requires_explicit_scope() -> None:
    from dataclasses import replace

    registry(mcp_client())  # sanity: valid scopes build
    for field, value in [
        ("allowed_site_ids", None),
        ("allowed_work_area_ids", None),
        ("allowed_site_ids", frozenset()),
        ("allowed_work_area_ids", frozenset()),
        ("allowed_site_ids", {"site-local"}),
        ("allowed_work_area_ids", {"area-local"}),
        ("allowed_site_ids", frozenset({"bad/path"})),
        ("allowed_work_area_ids", frozenset({"other\x00area"})),
    ]:
        principal = mcp_client()
        with pytest.raises(AuthRegistryError):
            registry(replace(principal, **{field: value}))


@pytest.mark.parametrize("field,value", [("role", Role.ADMIN), ("device_id", "device")])
def test_ai_identity_has_no_role_or_device(field: str, value: Any) -> None:
    from dataclasses import replace

    with pytest.raises(AuthRegistryError):
        registry(replace(mcp_client(), **{field: value}))


def test_ai_identity_fixed_permissions_and_old_identities_unchanged() -> None:
    assert principal_permissions(mcp_client()) == frozenset(
        {Permission.SPATIAL_DATA_READ, Permission.SPATIAL_DATA_REQUEST}
    )
    assert Permission.SITES_READ not in principal_permissions(mcp_client())
    assert Permission.ANALYSIS_API_READ not in principal_permissions(mcp_client())
    worker = Principal("worker", PrincipalKind.SPATIAL_DATA_WORKER, None, None, "org-local")
    assert principal_permissions(worker) == frozenset({Permission.SPATIAL_DATA_WORK})
    reader = Principal(
        "reader-local",
        PrincipalKind.SPATIAL_DATA_CLIENT,
        None,
        None,
        "org-local",
        allowed_site_ids=frozenset({"site-local"}),
        allowed_work_area_ids=frozenset({"area-local"}),
    )
    assert principal_permissions(reader) == frozenset(
        {Permission.SPATIAL_DATA_READ, Permission.SPATIAL_DATA_REQUEST}
    )
    analysis_mcp = Principal(
        "analysis-mcp-client-a",
        PrincipalKind.ANALYSIS_MCP_CLIENT,
        None,
        None,
        "org-a",
        allowed_site_ids=frozenset({"site-a"}),
        allowed_work_area_ids=frozenset({"wa-site-a-0001"}),
    )
    assert principal_permissions(analysis_mcp) == frozenset(
        {Permission.ANALYSIS_API_READ, Permission.ANALYSIS_API_CREATE}
    )
    for role in list(Role):
        permissions = principal_permissions(
            Principal("operator", PrincipalKind.OPERATOR, role, None)
        )
        assert Permission.SPATIAL_DATA_READ in permissions
        assert (Permission.SPATIAL_DATA_REQUEST in permissions) == (role != Role.VIEWER)


def test_old_data_client_keeps_six_routes_and_misses_discovery() -> None:
    reader = Principal(
        "reader-local",
        PrincipalKind.SPATIAL_DATA_CLIENT,
        None,
        None,
        "org-local",
        allowed_site_ids=frozenset({"site-local"}),
        allowed_work_area_ids=frozenset({"area-local"}),
    )
    for method, path in MCP_ROUTES[:6]:
        assert _get(_app(reader), method, path) == 200
    for path in (ASSET_BASE, ASSET_BASE + "/{asset_ref}"):
        assert _get(_app(reader), "GET", path) == 403


def test_ai_scope_change_cannot_hide_in_token_rotation() -> None:
    from dataclasses import replace

    first = mcp_client()
    changed = replace(first, allowed_work_area_ids=frozenset({"other"}))
    with pytest.raises(AuthRegistryError):
        AuthRegistry(
            [
                PrincipalTokenRecord(sha256(b"first").hexdigest(), first),
                PrincipalTokenRecord(sha256(b"second").hexdigest(), changed),
            ]
        )
