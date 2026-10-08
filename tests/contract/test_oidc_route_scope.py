"""Customer OIDC principals reach only reviewed, scoped Core routes."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
from analysis_api_local_fixture import build_local_analysis_api_fixture
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, generate_private_key
from fastapi import Depends
from fastapi.testclient import TestClient
from ksi_core.auth import HumanAuthMode, Principal, require_principal
from ksi_core.identity.auth import _OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig
from ksi_event_contracts.site_frame import SiteFrame

_ISSUER = "https://pilot-oidc.example.test"
_AUDIENCE = "ksi-core-pilot"


def _jwk(key: RSAPrivateKey) -> dict[str, str]:
    numbers = key.public_key().public_numbers()

    def encode(value: int) -> str:
        return jwt.utils.base64url_encode(
            value.to_bytes((value.bit_length() + 7) // 8, "big")
        ).decode()

    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": "pilot-route-scope-key",
        "n": encode(numbers.n),
        "e": encode(numbers.e),
    }


def _oidc_token(key: RSAPrivateKey) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "pilot-operator-subject",
            "exp": now + 600,
            "nbf": now - 5,
            # Untrusted authority claims must not affect the protected mapping.
            "ksi_role": "ADMIN",
            "ksi_organization_id": "attacker-org",
        },
        key,
        algorithm="RS256",
        headers={"kid": "pilot-route-scope-key"},
    )


def _install_oidc(fixture: Any) -> tuple[str, RSAPrivateKey]:
    key = generate_private_key(public_exponent=65537, key_size=2048)
    registry = OidcSubjectRegistry.from_document(
        {
            "version": "oidc-subject-registry.v1",
            "subjects": [
                {
                    "issuer": _ISSUER,
                    "subject": "pilot-operator-subject",
                    "principalId": "pilot-mapped-operator",
                    "organizationId": fixture.organization_id,
                    "role": "FIELD_OPERATOR",
                    "status": "ACTIVE",
                    "allowedSiteIds": [fixture.site_id],
                    "allowedWorkAreaIds": [fixture.work_area_id],
                }
            ],
        },
        expected_issuer=_ISSUER,
    )
    fixture.app.state.human_auth_mode = HumanAuthMode.OIDC
    fixture.app.state.oidc_verifier = OidcJwtVerifier(
        OidcVerifierConfig(
            issuer=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=f"{_ISSUER}/jwks.json",
        ),
        fetch_jwks=lambda: {"keys": [_jwk(key)]},
        subject_registry=registry,
    )

    @fixture.app.get("/v1/sites/{site_id}/analyses/result/export")
    def unreviewed_analysis_export(
        site_id: str,
        principal: Principal = Depends(require_principal()),  # noqa: B008
    ) -> dict[str, str]:
        return {"siteId": site_id, "principalId": principal.principal_id}

    return _oidc_token(key), key


def test_mapped_oidc_is_limited_to_exact_reviewed_pilot_route_templates(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        operator_client = TestClient(fixture.app)
        created = operator_client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "oidc-v2-scoped-history"},
            json={
                "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                "current": fixture.current.model_dump(by_alias=True, mode="json"),
            },
        )
        assert created.status_code == 202, created.text
        analysis_id = created.json()["analysisId"]
        token, _key = _install_oidc(fixture)
        headers = {"Authorization": f"Bearer {token}"}
        client = TestClient(fixture.app)
        mounted_routes = {
            (method.upper(), path)
            for path, operations in fixture.app.openapi()["paths"].items()
            for method in operations
        }
        reviewed_fixture_routes = {
            ("GET", "/v1/auth/whoami"),
            ("GET", "/v1/sites"),
            ("GET", "/v1/sites/{site_id}"),
            ("GET", "/v1/sites/{site_id}/work-areas"),
            ("GET", "/v1/sites/{site_id}/analysis-observations"),
            ("GET", "/v1/sites/{site_id}/analyses"),
            ("GET", "/v2/sites/{site_id}/analyses"),
            ("GET", "/v2/sites/{site_id}/analyses/{analysis_id}"),
            ("GET", "/v2/sites/{site_id}/analyses/{analysis_id}/evidence"),
            ("GET", "/v2/sites/{site_id}/analyses/{analysis_id}/coverage"),
            ("GET", "/v1/observation-work-orders/{work_order_id}"),
            (
                "GET",
                "/v1/observation-work-orders/{work_order_id}/external-reconstruction-context",
            ),
            (
                "GET",
                "/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions",
            ),
            ("GET", "/v1/work-inbox"),
        }
        spatial_catalog_routes = {
            ("GET", "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-assets"),
            (
                "GET",
                "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-assets/{asset_ref}",
            ),
        }
        assert reviewed_fixture_routes <= mounted_routes
        assert reviewed_fixture_routes <= _OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST
        assert spatial_catalog_routes <= _OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST
        site = fixture.app.state.site_store.get_scoped(fixture.site_id, fixture.organization_id)
        assert site is not None
        site_frame = SiteFrame.model_validate(site.site_frame)
        second_site_id = "pilot-same-org-ungranted-site"
        assert (
            fixture.app.state.site_store.register(
                second_site_id,
                "Same organization, ungranted site",
                site_frame,
                organization_id=fixture.organization_id,
                actor="test-setup",
                now=datetime.now(UTC),
            ).record
            is not None
        )

        # These endpoints have their own Site/WorkArea grant enforcement.
        allowed = [
            client.get("/v1/auth/whoami", headers=headers).status_code,
            client.get("/v1/sites", headers=headers).status_code,
            client.get(f"/v1/sites/{fixture.site_id}", headers=headers).status_code,
            client.get(f"/v1/sites/{fixture.site_id}/work-areas", headers=headers).status_code,
            client.get(
                f"/v1/sites/{fixture.site_id}/analysis-observations", headers=headers
            ).status_code,
            client.get(f"/v1/sites/{fixture.site_id}/analyses", headers=headers).status_code,
            client.get(f"/v2/sites/{fixture.site_id}/analyses", headers=headers).status_code,
            client.get(
                f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}", headers=headers
            ).status_code,
            client.get(
                f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
                headers=headers,
            ).status_code,
            client.get(
                f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/coverage",
                headers=headers,
            ).status_code,
            client.get(
                f"/v1/observation-work-orders/{fixture.baseline.work_order_id}",
                headers=headers,
            ).status_code,
            client.get(
                f"/v1/observation-work-orders/{fixture.baseline.work_order_id}/external-reconstruction-context",
                headers=headers,
            ).status_code,
            client.get(
                f"/v1/observation-work-orders/{fixture.baseline.work_order_id}/external-reconstruction-submissions",
                headers=headers,
            ).status_code,
            client.get("/v1/work-inbox", headers=headers).status_code,
        ]
        assert allowed[:9] == [200] * 9
        assert allowed[9] == 404
        assert allowed[10:] == [200] * (len(allowed) - 10)

        # Site visibility remains resource-scoped within the same organization.
        assert client.get(f"/v1/sites/{second_site_id}", headers=headers).status_code == 404
        assert (
            client.get(f"/v1/sites/{second_site_id}/work-areas", headers=headers).status_code == 404
        )

        # Unscoped authenticated reads, Site writes, and lookalike templates fail
        # at the principal request boundary before their handlers run.
        # P3 Task 5: /v1/processing-resource-policies retired with the managed
        # assembly (platform mounts no processing routes) — the roster route is
        # the staying generic surface an unscoped principal must be denied.
        denied = [
            client.get("/v1/organization-work-roster", headers=headers).status_code,
            client.get(
                f"/v1/sites/{fixture.site_id}/analyses/result/export", headers=headers
            ).status_code,
            client.post(
                "/v1/sites",
                headers=headers,
                json={
                    "siteId": "unapproved-new-site",
                    "name": "Unapproved",
                    "siteFrame": site.site_frame,
                },
            ).status_code,
            client.post(
                f"/v1/sites/{fixture.site_id}/transitions",
                headers=headers,
                json={"targetStatus": "SUSPENDED", "evidence": "x", "reason": "x"},
            ).status_code,
            client.put(f"/v1/sites/{fixture.site_id}/aoi", headers=headers, json={}).status_code,
            client.put(
                f"/v1/sites/{fixture.site_id}/model-age-policy",
                headers=headers,
                json={"maxAgeDays": 30},
            ).status_code,
        ]
        assert denied == [403] * len(denied)

        # Legacy opaque operators keep their existing authenticated Core access
        # (P3 Task 5: the processing policy route retired with the managed
        # assembly; the sites list is the staying generic authenticated read).
        fixture.app.state.human_auth_mode = HumanAuthMode.OPAQUE
        opaque_headers = fixture.operator_headers()
        opaque_sites_read = client.get("/v1/sites", headers=opaque_headers)
        assert opaque_sites_read.status_code == 200
    finally:
        fixture.close()
