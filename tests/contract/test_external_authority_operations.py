"""Only an in-tenant administrator may reload fixed external authority inputs."""

import hashlib
from datetime import datetime

import pytest
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


class _ReloadBoundary:
    """Records reload effects, supplies no measurement or authority records."""
    organization_id = "org-a"

    def __init__(self) -> None:
        self.calls = 0
        self.available = True

    def status(self) -> dict[str, object]:
        return {"status": "PROVIDER_CONFIGURED" if self.available else "BLOCKED"}

    def reload_and_reconcile(self, *, now: datetime) -> dict[str, object]:
        assert now.utcoffset() is not None
        self.calls += 1
        return {
            "status": "PROVIDER_CONFIGURED", "sequence": 1,
            "snapshotDigest": "sha256:" + "a" * 64,
        }


def _client(role: Role, organization: str = "org-a") -> tuple[TestClient, _ReloadBoundary]:
    from ksi_core.external_authority_operations import mount_external_authority_operations

    app = FastAPI()
    mount_auth(app, AuthRegistry([PrincipalTokenRecord(
        token_sha256=hashlib.sha256(b"operations-test-token").hexdigest(),
        principal=Principal(
            principal_id="operator", kind=PrincipalKind.OPERATOR, role=role,
            device_id=None, organization_id=organization,
        ),
    )]))
    controller = _ReloadBoundary()
    mount_external_authority_operations(app, controller)
    return TestClient(app), controller


@pytest.mark.parametrize("role", [Role.VIEWER, Role.FIELD_OPERATOR])
def test_nonadministrator_cannot_reload(role: Role) -> None:
    client, controller = _client(role)
    with client:
        response = client.post("/v1/operations/external-authority/reload", json={}, headers={
            "Authorization": "Bearer operations-test-token"
        })
    assert response.status_code == 403
    assert controller.calls == 0


def test_other_tenant_admin_cannot_reload() -> None:
    client, controller = _client(Role.ADMIN, "org-b")
    with client:
        response = client.post("/v1/operations/external-authority/reload", json={}, headers={
            "Authorization": "Bearer operations-test-token"
        })
    assert response.status_code == 404
    assert controller.calls == 0


def test_in_tenant_admin_reloads_only_fixed_inputs() -> None:
    client, controller = _client(Role.ADMIN)
    with client:
        denied = client.post("/v1/operations/external-authority/reload", json={})
        assert denied.status_code == 401
        injected = client.post("/v1/operations/external-authority/reload", json={
            "path": "/unapproved/authority.json"
        }, headers={"Authorization": "Bearer operations-test-token"})
        assert injected.status_code == 422
        assert controller.calls == 0
        accepted = client.post("/v1/operations/external-authority/reload", json={}, headers={
            "Authorization": "Bearer operations-test-token"
        })
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "PROVIDER_CONFIGURED"
    assert controller.calls == 1


def test_runtime_readiness_is_current_and_exposes_no_authority_records() -> None:
    client, controller = _client(Role.ADMIN)
    with client:
        available = client.get("/ready/external-authority")
        assert available.status_code == 200
        assert available.json() == {"status": "PROVIDER_CONFIGURED"}
        controller.available = False
        unavailable = client.get("/ready/external-authority")
        assert unavailable.status_code == 503
        assert unavailable.json() == {"detail": "EXTERNAL_AUTHORITY_UNAVAILABLE"}
