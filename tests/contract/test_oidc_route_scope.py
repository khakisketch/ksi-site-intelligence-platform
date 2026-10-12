"""Customer OIDC principals reach only reviewed, scoped Core routes."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
from analysis_api_local_fixture import build_local_analysis_api_fixture
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, generate_private_key
from fastapi import Depends
from fastapi.testclient import TestClient
from ksi_core.auth import HumanAuthMode, Principal, PrincipalKind, Role, require_principal
from ksi_core.domains.external.workflow.external_result_projection_models import (
    ExternalPendingDecisionItem,
    ExternalPendingDecisionsView,
)
from ksi_core.domains.external.workflow.external_result_workflow_api import (
    _scoped_pending_items,
)
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
            # Untrusted authority claims must not affect the protected mapping —
            # role·조직·capability 위조 claim 은 registry 매핑을 이기지 못한다.
            "ksi_role": "ADMIN",
            "ksi_organization_id": "attacker-org",
            "ksi_capabilities": ["SITE_BOOTSTRAP"],
        },
        key,
        algorithm="RS256",
        headers={"kid": "pilot-route-scope-key"},
    )


def _install_oidc_v2(
    fixture: Any,
    *,
    capabilities: list[str],
    site_ids: list[str] | None,
    area_ids: list[str] | None,
    organization_id: str | None = None,
) -> tuple[str, RSAPrivateKey]:
    """v2 registry(F-01) 로 매핑 신원을 세운다 — null scope 도 검토된 matrix 안이다."""
    key = generate_private_key(public_exponent=65537, key_size=2048)
    registry = OidcSubjectRegistry.from_document(
        {
            "version": "oidc-subject-registry.v2",
            "subjects": [
                {
                    "issuer": _ISSUER,
                    "subject": "pilot-operator-subject",
                    "principalId": "pilot-mapped-operator",
                    "organizationId": (
                        organization_id if organization_id is not None else fixture.organization_id
                    ),
                    "role": "FIELD_OPERATOR",
                    "status": "ACTIVE",
                    "capabilities": capabilities,
                    "allowedSiteIds": site_ids,
                    "allowedWorkAreaIds": area_ids,
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
    return _oidc_token(key), key


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
            ("GET", "/v1/external-decisions/pending"),
            ("GET", "/v1/observation-work-orders/{work_order_id}/relative-volume-requests"),
            ("GET", "/v1/observation-work-orders/{work_order_id}/single-volume-requests"),
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
            client.get("/v1/external-decisions/pending", headers=headers).status_code,
            client.get(
                f"/v1/observation-work-orders/{fixture.baseline.work_order_id}/relative-volume-requests",
                headers=headers,
            ).status_code,
            client.get(
                f"/v1/observation-work-orders/{fixture.baseline.work_order_id}/single-volume-requests",
                headers=headers,
            ).status_code,
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


# ── F-01 v2: null scope 와 capability 조건부 bootstrap 경계 ────────────


def test_v2_null_scope_without_capability_stays_in_reviewed_matrix(tmp_path: Path) -> None:
    """명시 null(자기 조직 전체)은 opaque unscoped 처럼 미검토 route 로 새지 않는다."""
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        token, _key = _install_oidc_v2(
            fixture, capabilities=[], site_ids=None, area_ids=None
        )
        client = TestClient(fixture.app)
        headers = {"Authorization": f"Bearer {token}"}

        whoami = client.get("/v1/auth/whoami", headers=headers)
        assert whoami.status_code == 200
        body = whoami.json()
        assert body["registryScoped"] is True
        assert body["capabilities"] == []
        assert body["siteScopeLevel"] == "ORG_ALL"
        # 조직 전체 scope 라도 매트릭스 밖 route 는 403 이고, capability 조건부
        # Site 생성도 capability 가 없으면 403 이다(위조 JWT claim 포함).
        assert client.get("/v1/organization-work-roster", headers=headers).status_code == 403
        assert (
            client.post(
                f"/v1/sites/{fixture.site_id}/transitions",
                headers=headers,
                json={"targetStatus": "SUSPENDED", "evidence": "x", "reason": "x"},
            ).status_code
            == 403
        )
        assert client.get("/v1/sites", headers=headers).status_code == 200
        denied_create = client.post(
            "/v1/sites",
            headers=headers,
            json={
                "bootstrapRequestId": "0f8fad5b-d9cb-469f-a165-70867728950e",
                "name": "거부",
                "siteFrame": fixture.app.state.site_store.get_scoped(
                    fixture.site_id, fixture.organization_id
                ).site_frame,
            },
        )
        assert denied_create.status_code == 403
    finally:
        fixture.close()


def test_v2_capability_opens_only_conditional_bootstrap_route(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        token, _key = _install_oidc_v2(
            fixture, capabilities=["SITE_BOOTSTRAP"], site_ids=None, area_ids=None
        )
        client = TestClient(fixture.app)
        headers = {"Authorization": f"Bearer {token}"}

        whoami = client.get("/v1/auth/whoami", headers=headers)
        assert whoami.status_code == 200
        assert whoami.json()["capabilities"] == ["SITE_BOOTSTRAP"]
        # capability 는 승인된 조건부 route 하나만 연다 — 다른 미검토 route 는
        # 여전히 403 이다.
        assert client.get("/v1/organization-work-roster", headers=headers).status_code == 403

        site = fixture.app.state.site_store.get_scoped(
            fixture.site_id, fixture.organization_id
        )
        assert site is not None
        request_id = "6f1c8f3a-4c1e-4c9e-8f0a-2b7d5e9a1c33"
        created = client.post(
            "/v1/sites",
            headers=headers,
            json={
                "bootstrapRequestId": request_id,
                "name": "부트스트랩 현장",
                "siteFrame": site.site_frame,
            },
        )
        assert created.status_code == 201, created.text
        site_id = created.json()["site"]["siteId"]
        assert site_id.startswith("site-")

        retry = client.post(
            "/v1/sites",
            headers=headers,
            json={
                "bootstrapRequestId": request_id,
                "name": "부트스트랩 현장",
                "siteFrame": site.site_frame,
            },
        )
        assert retry.status_code == 201
        assert retry.json()["site"]["siteId"] == site_id
        listed_ids = {
            item["siteId"] for item in client.get("/v1/sites", headers=headers).json()["sites"]
        }
        assert {fixture.site_id, site_id} <= listed_ids
    finally:
        fixture.close()


def test_v2_explicit_list_level_and_site_list_scope(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        token, _key = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=[fixture.site_id],
            area_ids=[fixture.work_area_id],
        )
        client = TestClient(fixture.app)
        headers = {"Authorization": f"Bearer {token}"}

        whoami = client.get("/v1/auth/whoami", headers=headers)
        assert whoami.status_code == 200
        assert whoami.json()["siteScopeLevel"] == "EXPLICIT"
        listed = client.get("/v1/sites", headers=headers)
        assert [item["siteId"] for item in listed.json()["sites"]] == [fixture.site_id]
    finally:
        fixture.close()


# ── 2026-10-12: 외부 결과 read 표면의 mapped 신원 경계 ─────────────────


def test_scoped_volume_reads_require_exact_work_order_grants(tmp_path: Path) -> None:
    """매핑 신원은 정확한 WorkOrder site/area grant 없이는 volume 목록을 볼 수 없다."""
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        client = TestClient(fixture.app)
        work_order_id = fixture.baseline.work_order_id
        relative = f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests"
        single = f"/v1/observation-work-orders/{work_order_id}/single-volume-requests"

        token, _key = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=[fixture.site_id],
            area_ids=[fixture.work_area_id],
        )
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get(relative, headers=headers).status_code == 200
        assert client.get(single, headers=headers).status_code == 200

        # 같은 Site grant 라도 WorkOrder 의 area 가 grant 밖이면 동일 404 다.
        token, _key = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=[fixture.site_id],
            area_ids=["wa-ungranted-0001"],
        )
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get(relative, headers=headers).status_code == 404
        assert client.get(single, headers=headers).status_code == 404

        # area grant 는 맞아도 Site grant 가 다르면 404 다.
        token, _key = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=["site-foreign-grant"],
            area_ids=[fixture.work_area_id],
        )
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get(relative, headers=headers).status_code == 404
        assert client.get(single, headers=headers).status_code == 404

        # 교차 조직 신원은 이 조직의 WorkOrder 를 해석하지 못한다(404 비노출).
        token, _key = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=[fixture.site_id],
            area_ids=[fixture.work_area_id],
            organization_id="other-organization",
        )
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get(relative, headers=headers).status_code == 404
        assert client.get(single, headers=headers).status_code == 404
    finally:
        fixture.close()


def test_scoped_pending_decisions_filter_by_site_and_work_area() -> None:
    """검토 대기 목록은 매핑 신원의 Site/WorkArea grant 안의 행만 남긴다."""

    def item(site_id: str, work_area_id: str) -> ExternalPendingDecisionItem:
        return ExternalPendingDecisionItem(
            site_id=site_id,
            report_ref=f"report-{site_id}-{work_area_id}",
            kind="EXTERNAL_RELATIVE_VOLUME",
            stage="AWAITING_REVIEW",
            reported_at=datetime.now(UTC),
            net_m3=0.0,
            uncertainty_m3=None,
            work_area_id=work_area_id,
        )

    view = ExternalPendingDecisionsView(
        items=[item("site-a", "wa-a-0001"), item("site-b", "wa-b-0001")]
    )
    scoped = Principal(
        principal_id="scoped-operator",
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id="org-a",
        allowed_site_ids=frozenset({"site-a"}),
        allowed_work_area_ids=frozenset({"wa-a-0001"}),
    )
    assert [row.site_id for row in _scoped_pending_items(scoped, view)] == ["site-a"]

    area_denied = replace(scoped, allowed_work_area_ids=frozenset({"wa-other-0001"}))
    assert _scoped_pending_items(area_denied, view) == []

    unscoped = Principal(
        principal_id="legacy-operator",
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id="org-a",
    )
    assert _scoped_pending_items(unscoped, view) == view.items
