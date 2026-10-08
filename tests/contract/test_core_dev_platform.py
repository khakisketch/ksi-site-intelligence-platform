"""Local platform harness: bounded synthetic OIDC grants and unavailable storage.

These are software/browser fixtures, never live grants or field evidence.
"""

from __future__ import annotations

import hashlib
import importlib.util
import secrets
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    HumanAuthMode,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.evidence import EvidenceStorageError
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig

ROOT = Path(__file__).resolve().parents[2]
ISSUER = "http://localhost:9030"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runner() -> Any:
    return _load("core_dev_platform_test_runner", ROOT / "scripts/run_core_dev.py")


@pytest.fixture
def seeded_dir(tmp_path: Path) -> Path:
    seed = _load(
        "core_dev_platform_test_seed",
        ROOT / "apps/dashboard/e2e/fixtures/seed_operations_console.py",
    )
    seed.seed(tmp_path)
    return tmp_path


def _oidc(runner: Any, *, fixture_scope: bool) -> tuple[OidcJwtVerifier, Any]:
    key = generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()

    def encoded(value: int) -> str:
        return jwt.utils.base64url_encode(
            value.to_bytes((value.bit_length() + 7) // 8, "big")
        ).decode()

    registry = (
        runner._dev_oidc_subject_registry(ISSUER, enable_operations_console_e2e=True)
        if fixture_scope
        else runner._dev_oidc_subject_registry(ISSUER)
    )
    verifier = OidcJwtVerifier(
        OidcVerifierConfig(issuer=ISSUER, audience="ksi-core", jwks_url=f"{ISSUER}/jwks.json"),
        subject_registry=registry,
        fetch_jwks=lambda: {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": "synthetic-harness-key",
                    "n": encoded(numbers.n),
                    "e": encoded(numbers.e),
                }
            ]
        },
    )
    return verifier, key


def _headers(key: Any, subject: str) -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode(
        {"iss": ISSUER, "aud": "ksi-core", "sub": subject, "exp": now + 60, "nbf": now - 5},
        key,
        algorithm="RS256",
        headers={"kid": "synthetic-harness-key"},
    )
    return {"Authorization": f"Bearer {token}"}


def test_opt_in_fixture_scope_exposes_seeded_sites_and_orders(
    runner: Any, seeded_dir: Path
) -> None:
    """Catches missing/wrong grants without weakening Core's resource checks."""
    verifier, key = _oidc(runner, fixture_scope=True)
    assembly = runner.build_dev_app(
        seeded_dir,
        human_auth_mode=HumanAuthMode.OIDC,
        oidc_verifier=verifier,
        segment_bytes=None,
    )
    try:
        with TestClient(assembly.app) as client:
            headers = _headers(key, "local-admin")
            sites = client.get("/v1/sites", headers=headers)
            assert sites.status_code == 200
            assert {site["siteId"] for site in sites.json()["sites"]} == {
                "e2e-site-workspace",
                "e2e-site-review",
                "e2e-site-progress",
                "e2e-site-result",
                "e2e-site-completed",
            }
            orders = client.get("/v1/observation-work-orders", headers=headers)
            assert orders.status_code == 200
            assert len(orders.json()["workOrders"]) == 5
            external = [
                order
                for order in orders.json()["workOrders"]
                if order["executionMode"] == "EXTERNAL_RECONSTRUCTION"
            ]
            assert len(external) == 1
            assert external[0]["name"] == "E2E 외부 산출물 등록"
            assert external[0]["status"] == "APPROVED"
            assert external[0]["missionIds"] == []
            assert external[0]["processingJobIds"] == []
            operations = client.get(
                f"/v1/observation-work-orders/{external[0]['workOrderId']}/operations",
                headers=headers,
            )
            assert operations.status_code == 200
            assert operations.json()["workflowStatus"] == "OPEN"
            context = client.get(
                f"/v1/observation-work-orders/{external[0]['workOrderId']}/external-reconstruction-context",
                headers=headers,
            )
            assert context.status_code == 200
            site = client.get("/v1/sites/e2e-site-workspace", headers=headers)
            assert site.status_code == 200
            areas = client.get("/v1/sites/e2e-site-workspace/work-areas", headers=headers)
            assert areas.status_code == 200
            assert [area["workAreaId"] for area in areas.json()["workAreas"]] == [
                "wa-e2e-site-workspace-0001"
            ]
            for path in ["/v1/missions", "/v1/events", "/capabilities"]:
                assert client.get(path, headers=headers).status_code == 404
    finally:
        assembly.close()


@pytest.mark.parametrize(
    "fixture_scope,subject",
    [
        (False, "local-admin"),
        (True, "local-empty-org-admin"),
    ],
)
def test_default_and_empty_organization_cannot_see_seeded_resources(
    runner: Any,
    seeded_dir: Path,
    fixture_scope: bool,
    subject: str,
) -> None:
    verifier, key = _oidc(runner, fixture_scope=fixture_scope)
    assembly = runner.build_dev_app(
        seeded_dir,
        human_auth_mode=HumanAuthMode.OIDC,
        oidc_verifier=verifier,
        segment_bytes=None,
    )
    try:
        with TestClient(assembly.app) as client:
            headers = _headers(key, subject)
            assert client.get("/v1/sites", headers=headers).json() == {"sites": []}
            assert client.get("/v1/observation-work-orders", headers=headers).json() == {
                "workOrders": []
            }
            assert client.get("/v1/sites/e2e-site-workspace", headers=headers).status_code == 404
            assert (
                client.get(
                    "/v1/observation-work-orders/obs-work-00000001",
                    headers=headers,
                ).status_code
                == 404
            )
    finally:
        assembly.close()


def test_fixture_scope_does_not_grant_arbitrary_same_org_ids(runner: Any) -> None:
    registry = runner._dev_oidc_subject_registry(ISSUER, enable_operations_console_e2e=True)
    principal = registry.resolve(ISSUER, "local-admin")
    assert principal is not None
    assert principal.allowed_site_ids is not None
    assert principal.allowed_work_area_ids is not None
    assert "ungranted-same-org-site" not in principal.allowed_site_ids
    assert "wa-e2e-site-workspace-0002" not in principal.allowed_work_area_ids
    assert registry.resolve(ISSUER, "unmapped-subject") is None


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/v1/events"),
        ("GET", "/v1/events/generated-retired-event"),
        ("POST", "/v1/events/generated-retired-event/transitions"),
        ("GET", "/v1/missions"),
        ("POST", "/v1/missions/plans"),
        ("POST", "/v1/missions/generated-retired-mission/execution-transitions"),
    ],
)
def test_retired_event_and_mission_actions_are_absent_even_for_an_admin(
    runner: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    """Catches remounting acquisition authority, rather than comparing a retired TS mirror."""
    token = secrets.token_urlsafe(24)
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(),
                principal=Principal(
                    principal_id="generated-boundary-admin",
                    organization_id="generated-boundary-org",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )
    monkeypatch.setattr(runner, "_auth_registry", lambda: registry)
    assembly = runner.build_dev_app(tmp_path, segment_bytes=None)
    try:
        with TestClient(assembly.app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/v1/auth/whoami", headers=headers).status_code == 200
            assert client.get("/v1/sites", headers=headers).status_code == 200
            assert client.request(method, path, headers=headers).status_code == 404
    finally:
        assembly.close()


def test_unconfigured_platform_boot_does_not_open_s3_credentials(
    runner: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import boto3

    def forbidden_client(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("An unconfigured dev boot must not open an S3 client")

    monkeypatch.setattr(boto3, "client", forbidden_client)
    assembly = runner.build_dev_app(tmp_path, segment_bytes=None)
    try:
        with TestClient(assembly.app) as client:
            assert client.get("/ready").status_code == 200
    finally:
        assembly.close()


def test_e2e_scope_flag_rejects_non_loopback_host_before_creating_state(tmp_path: Path) -> None:
    target = tmp_path / "must-not-exist"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_core_dev.py"),
            "--host",
            "0.0.0.0",
            "--data-dir",
            str(target),
            "--oidc-operations-console-e2e",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert "requires a loopback bind" in result.stderr
    assert not target.exists()


@pytest.mark.parametrize("operation", ["get", "put", "delete", "read", "write"])
def test_unconfigured_evidence_storage_issues_no_capability(runner: Any, operation: str) -> None:
    storage = runner._UnavailableEvidenceStorage()
    with pytest.raises(EvidenceStorageError, match="not configured"):
        if operation == "get":
            storage.presigned_get("owned-synthetic-key", ttl=timedelta(minutes=1))
        elif operation == "put":
            storage.presigned_put(
                "owned-synthetic-key",
                content_type="image/png",
                ttl=timedelta(minutes=1),
            )
        elif operation == "delete":
            storage.delete("owned-synthetic-key")
        elif operation == "read":
            storage.get_bytes("owned-synthetic-key")
        else:
            storage.put_bytes("owned-synthetic-key", b"synthetic", content_type="image/png")
