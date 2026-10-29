"""Customer OIDC principals reach only reviewed, scoped Core routes."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from analysis_api_local_fixture import build_local_analysis_api_fixture
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, generate_private_key
from fastapi import Depends, HTTPException
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
    role: str = "FIELD_OPERATOR",
    status: str = "ACTIVE",
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
                    "role": role,
                    "status": status,
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
            (
                "POST",
                "/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions-v3",
            ),
            ("GET", "/v1/work-inbox"),
            ("GET", "/v1/external-decisions/pending"),
            ("GET", "/v1/observation-work-orders/{work_order_id}/relative-volume-requests"),
            ("GET", "/v1/observation-work-orders/{work_order_id}/single-volume-requests"),
            (
                "GET",
                "/v1/observation-work-orders/{work_order_id}/relative-volume-requests/{request_ref}",
            ),
            (
                "GET",
                "/v1/observation-work-orders/{work_order_id}/single-volume-requests/{request_ref}",
            ),
            ("POST", "/v1/external-relative-volume-reports/{report_ref}/reviews"),
            ("POST", "/v1/external-single-volume-reports/{report_ref}/reviews"),
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
        token, _key = _install_oidc_v2(fixture, capabilities=[], site_ids=None, area_ids=None)
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

        site = fixture.app.state.site_store.get_scoped(fixture.site_id, fixture.organization_id)
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

        # 한쪽 차원만 설정되면 None 차원은 제한하지 않는다(F-01 관례).
        token, _key = _install_oidc_v2(
            fixture, capabilities=[], site_ids=[fixture.site_id], area_ids=None
        )
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get(relative, headers=headers).status_code == 200
        assert client.get(single, headers=headers).status_code == 200

        token, _key = _install_oidc_v2(
            fixture, capabilities=[], site_ids=None, area_ids=[fixture.work_area_id]
        )
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get(relative, headers=headers).status_code == 200
        assert client.get(single, headers=headers).status_code == 200

        token, _key = _install_oidc_v2(
            fixture, capabilities=[], site_ids=None, area_ids=["wa-ungranted-0001"]
        )
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get(relative, headers=headers).status_code == 404
        assert client.get(single, headers=headers).status_code == 404

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


def test_mapped_oidc_volume_detail_and_review_routes_reach_their_handlers(tmp_path: Path) -> None:
    """2026-10-13 승인 확장: volume 상세·검토 route는 mapped 신원도 도달하지만,
    핸들러(WorkOrder grant guard·review source authority)가 그대로 fail-closed한다."""
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        client = TestClient(fixture.app)
        work_order_id = fixture.baseline.work_order_id
        relative_detail = (
            f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests/req-x"
        )
        single_detail = f"/v1/observation-work-orders/{work_order_id}/single-volume-requests/req-x"
        relative_review = "/v1/external-relative-volume-reports/req-x/reviews"
        single_review = "/v1/external-single-volume-reports/req-x/reviews"

        # legacy opaque 신원: 같은 route가 일반 핸들러 판정(404/409)이다(경계 대조).
        legacy_headers = fixture.operator_headers()
        assert client.get(relative_detail, headers=legacy_headers).status_code == 404
        assert client.get(single_detail, headers=legacy_headers).status_code == 404
        assert client.post(relative_review, headers=legacy_headers).status_code == 409
        assert client.post(single_review, headers=legacy_headers).status_code == 409

        token, _key = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=[fixture.site_id],
            area_ids=[fixture.work_area_id],
        )
        headers = {"Authorization": f"Bearer {token}"}
        # 분석 경계 403이 아니라 핸들러 판정으로 fail-closed한다 — 존재하지 않는
        # ref는 단건 상세 404, review는 source authority 부재 409다.
        assert client.get(relative_detail, headers=headers).status_code == 404
        assert client.get(single_detail, headers=headers).status_code == 404
        assert client.post(relative_review, headers=headers).status_code == 409
        assert client.post(single_review, headers=headers).status_code == 409

        # 단건 상세도 목록과 같은 WorkOrder site/area guard를 통과해야 한다:
        # 불일치 grant는 존재 여부를 드러내지 않고 404로 접힌다.
        other_area_token, _key2 = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=[fixture.site_id],
            area_ids=["wa-other-0001"],
        )
        other_headers = {"Authorization": f"Bearer {other_area_token}"}
        assert client.get(relative_detail, headers=other_headers).status_code == 404
        assert client.get(single_detail, headers=other_headers).status_code == 404
    finally:
        fixture.close()


def test_scoped_volume_detail_with_recorded_request_matches_list_guard(
    tmp_path: Path,
) -> None:
    """기록된 요청이 있어도 단건 상세는 목록과 같은 WorkOrder site/area guard를 둔다.

    2026-10-28 회귀: 상세 route가 guard 없이 store/org 필터만으로 200을
    반환하던 노출을 고정한다. 존재하지 않는 ref(`req-x`, 위 테스트)는
    guard 없이도 404라 이 케이스만으로는 회귀를 잡지 못한다 — 실제
    issue된 request ref로 목록/상세를 같은 grant matrix에 둔다.
    """
    import hashlib
    from dataclasses import replace as _replace

    import external_single_volume_fixture as _sing
    import test_external_relative_volumes as _rel
    from fastapi import FastAPI
    from ksi_core.auth import AuthRegistry, PrincipalTokenRecord, mount_auth
    from ksi_core.domains.external.quantity.external_relative_volumes import (
        ExternalRelativeVolumeInputCapability,
        ExternalRelativeVolumeQueuePolicy,
        ExternalRelativeVolumeStore,
        build_external_relative_volume_router,
    )
    from ksi_core.domains.external.quantity.external_single_volumes import (
        ExternalSingleVolumeStore,
        build_external_single_volume_router,
    )
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.observation_work_orders import ObservationWorkOrderStore

    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "scoped-detail-work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            organization_id == "org-a" and site_id in {"site-a", "site-b"}
        ),
        work_areas_exist=lambda _site_id, _work_area_ids: True,
    )
    victim = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="Scoped detail victim",
        work_area_ids=["wa-a-0001", "wa-a-0002"],
        schedule_id=None,
        actor="operator-a",
        now=_rel._NOW,
    )
    other_site = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-b",
        name="Scoped detail other site",
        work_area_ids=["wa-b-0001"],
        schedule_id=None,
        actor="operator-a",
        now=_rel._NOW,
    )

    rel_authority = _rel._authority()
    rel_authority = _replace(
        rel_authority,
        current_work_order_id=victim.work_order_id,
        current=rel_authority.current.model_copy(
            update={
                "subject": rel_authority.current.subject.model_copy(
                    update={"work_order_id": victim.work_order_id}
                )
            }
        ),
    )
    rel_port = _rel._AuthorityPort(rel_authority)
    rel_store = ExternalRelativeVolumeStore(
        DurableJournal(tmp_path / "scoped-detail-relative.jsonl"),
        authority_port=rel_port,
        currentness_coordinator=rel_port.currentness_coordinator,
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(minutes=5),
            deadline_after_issue=timedelta(hours=1),
            max_attempts=3,
            max_active_requests_per_organization=8,
        ),
        clock=lambda: _rel._NOW,
    )
    issued_rel = rel_store.issue(
        principal=_rel._principal(),
        current_work_order_id=victim.work_order_id,
        decision_ref="decision-a",
        idempotency_key="scoped-detail-rel",
        now=_rel._NOW,
    )
    assert issued_rel.record is not None
    rel_ref = issued_rel.record.request.request_id

    sing_authority = _sing._authority(work_order_id=victim.work_order_id)
    sing_port = _sing._AuthorityPort(sing_authority)
    sing_store = ExternalSingleVolumeStore(
        DurableJournal(tmp_path / "scoped-detail-single.jsonl"),
        authority_port=sing_port,
        currentness_coordinator=sing_port.currentness_coordinator,
        queue_policy=_sing._queue_policy(),
        clock=lambda: _sing._NOW,
    )
    issued_sing = sing_store.issue(
        principal=_sing._principal(),
        current_work_order_id=victim.work_order_id,
        decision_ref="decision-a",
        idempotency_key="scoped-detail-sing",
        now=_sing._NOW,
    )
    assert issued_sing.record is not None
    sing_ref = issued_sing.record.request.request_id

    def _capabilities(*_args: Any, **_kwargs: Any) -> Any:
        return (
            ExternalRelativeVolumeInputCapability(
                role="BASELINE_DSM",
                download_url="https://storage.invalid/baseline",
                required_headers={},
                expires_at=_rel._NOW + timedelta(minutes=5),
            ),
            ExternalRelativeVolumeInputCapability(
                role="CURRENT_DSM",
                download_url="https://storage.invalid/current",
                required_headers={},
                expires_at=_rel._NOW + timedelta(minutes=5),
            ),
        )

    legacy_principal = _rel._principal()
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(b"scoped-detail-legacy").hexdigest(),
                    principal=legacy_principal,
                )
            ]
        ),
    )
    app.include_router(
        build_external_relative_volume_router(
            rel_store,
            input_capability_issuer=_capabilities,
            work_orders=work_orders,
            clock=lambda: _rel._NOW,
        )
    )
    app.include_router(
        build_external_single_volume_router(
            sing_store,
            input_capability_issuer=_capabilities,
            work_orders=work_orders,
            clock=lambda: _sing._NOW,
        )
    )
    client = TestClient(app)
    pseudo = SimpleNamespace(app=app, organization_id="org-a")
    rel_list = f"/v1/observation-work-orders/{victim.work_order_id}/relative-volume-requests"
    sing_list = f"/v1/observation-work-orders/{victim.work_order_id}/single-volume-requests"
    rel_detail = rel_list + f"/{rel_ref}"
    sing_detail = sing_list + f"/{sing_ref}"

    def _headers_for(
        *,
        site_ids: list[str] | None,
        area_ids: list[str] | None,
        organization_id: str = "org-a",
    ) -> dict[str, str]:
        token, _key = _install_oidc_v2(
            pseudo,
            capabilities=[],
            site_ids=site_ids,
            area_ids=area_ids,
            organization_id=organization_id,
        )
        return {"Authorization": f"Bearer {token}"}

    # 같은 grant: 목록·상세 모두 200(양 family).
    granted = _headers_for(site_ids=["site-a"], area_ids=["wa-a-0001", "wa-a-0002"])
    assert client.get(rel_list, headers=granted).status_code == 200
    assert client.get(rel_detail, headers=granted).status_code == 200
    assert client.get(sing_list, headers=granted).status_code == 200
    assert client.get(sing_detail, headers=granted).status_code == 200

    # 외지 grant: 목록이 404면 기록이 있어도 상세는 존재 여부를 드러내지 않는다.
    for label, grant in (
        ("foreign-site", {"site_ids": ["site-foreign"], "area_ids": ["wa-a-0001", "wa-a-0002"]}),
        ("other-area", {"site_ids": ["site-a"], "area_ids": ["wa-other-0001"]}),
        ("partial-area", {"site_ids": ["site-a"], "area_ids": ["wa-a-0001"]}),
    ):
        headers = _headers_for(**grant)  # type: ignore[arg-type]
        assert client.get(rel_list, headers=headers).status_code == 404, label
        assert client.get(rel_detail, headers=headers).status_code == 404, label
        assert client.get(sing_list, headers=headers).status_code == 404, label
        assert client.get(sing_detail, headers=headers).status_code == 404, label
        # 404 본문도 존재하지 않는 ref와 동일해야 한다(열거 오라클 방지).
        for path in (rel_detail, sing_detail):
            denied = client.get(path, headers=headers)
            missing = client.get(path.rsplit("/", 1)[0] + "/req-missing", headers=headers)
            assert denied.status_code == missing.status_code == 404, label
            assert denied.json() == missing.json(), label

    # 교차 조직: 조직 필터로 404(기존 동작 유지).
    cross = _headers_for(
        site_ids=["site-a"],
        area_ids=["wa-a-0001", "wa-a-0002"],
        organization_id="other-organization",
    )
    assert client.get(rel_list, headers=cross).status_code == 404
    assert client.get(rel_detail, headers=cross).status_code == 404
    assert client.get(sing_list, headers=cross).status_code == 404
    assert client.get(sing_detail, headers=cross).status_code == 404

    # 존재하지 않는 ref·다른 WorkOrder 경로: grant가 있어도 404(기존 동작 유지).
    # (위 loop의 _install_oidc_v2 호출이 verifier 키를 교체하므로 granted 갱신)
    granted = _headers_for(site_ids=["site-a"], area_ids=["wa-a-0001", "wa-a-0002"])
    assert client.get(rel_list + "/req-missing", headers=granted).status_code == 404
    assert client.get(sing_list + "/req-missing", headers=granted).status_code == 404
    both = _headers_for(
        site_ids=["site-a", "site-b"],
        area_ids=["wa-a-0001", "wa-a-0002", "wa-b-0001"],
    )
    assert (
        client.get(
            f"/v1/observation-work-orders/{other_site.work_order_id}"
            f"/relative-volume-requests/{rel_ref}",
            headers=both,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/v1/observation-work-orders/{other_site.work_order_id}"
            f"/single-volume-requests/{sing_ref}",
            headers=both,
        ).status_code
        == 404
    )

    # legacy opaque unscoped: 기존 조직 필터 동작 유지(목록·상세 200).
    app.state.human_auth_mode = HumanAuthMode.OPAQUE
    legacy_headers = {"Authorization": "Bearer scoped-detail-legacy"}
    assert client.get(rel_list, headers=legacy_headers).status_code == 200
    assert client.get(rel_detail, headers=legacy_headers).status_code == 200
    assert client.get(sing_list, headers=legacy_headers).status_code == 200
    assert client.get(sing_detail, headers=legacy_headers).status_code == 200


def _closable_review_probe(
    tmp_path: Path,
    *,
    record_reports: bool = True,
    clock: Callable[[], datetime] | None = None,
) -> SimpleNamespace:
    """Wire a closable review graph: real stores/services/router, synthetic providers.

    A first EXTERNAL_RECONSTRUCTION work order and a baseline work order are
    predicted and bound into the sealed source/authorities so the former can
    later be closed; both volume families record one report each. Mirrors the
    product-loop assembly wiring. With ``record_reports=False`` the relative
    request is only issued+claimed, and the helper returns its fence plus the
    deterministic future report ref for interleaving tests.
    """
    import hashlib
    from dataclasses import fields as _fields
    from dataclasses import replace as _replace

    import external_product_loop_fixture as _loop
    from external_product_loop_fixture import LoopGraph, _History
    from external_single_volume_fixture import (
        _authority as _sing_authority_fn,
    )
    from external_single_volume_fixture import (
        _store as _sing_store,
    )
    from fastapi import FastAPI
    from ksi_core.auth import AuthRegistry, PrincipalTokenRecord, mount_auth
    from ksi_core.domains.external.quantity.external_relative_volumes import (
        ExternalRelativeVolumeExecutionAuthority,
        ExternalRelativeVolumeObservedReportInput,
        ExternalRelativeVolumeQueuePolicy,
        ExternalRelativeVolumeStore,
    )
    from ksi_core.domains.external.workflow.external_result_workflow_api import (
        build_external_result_workflow_router,
    )
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
    from ksi_core.external_reobservation_proposals import (
        CoreExternalReobservationProposalAuthorityPort,
        ExternalReobservationProposalService,
        ExternalReobservationProposalStore,
        verify_external_reobservation_organization_graph,
    )
    from ksi_core.external_result_review_sources import CoreExternalResultReviewSourceAdapter
    from ksi_core.external_result_reviews import ExternalResultReviewStore
    from ksi_core.external_use_decisions import ExternalDecisionIntent, ExternalUseDecisionStore
    from ksi_core.observation_work_orders import ObservationWorkOrderStore
    from ksi_core.sites import SiteStore
    from ksi_core.work_areas import WorkAreaStore
    from ksi_event_contracts.observation_work_order import ObservationWorkOrderExecutionMode
    from test_external_relative_volumes import (
        _AuthorityPort,
        _fence,
    )
    from test_external_relative_volumes import (
        _payload as _rel_payload,
    )
    from test_external_result_review_proposals import (
        _NOW as _REVIEW_NOW,
    )
    from test_external_result_review_proposals import (
        _principal as _review_principal,
    )
    from test_external_result_review_proposals import (
        _sealed_source,
    )
    from test_external_single_volume_result_reviews import (
        _decision as _sing_decision,
    )
    from test_external_single_volume_result_reviews import (
        _record_single,
        _SingleAuthority,
    )
    from test_external_use_decisions import _SyntheticHistoryVerifier

    journals: list[DurableJournal] = []

    def _journal(name: str) -> DurableJournal:
        item = DurableJournal(tmp_path / name)
        journals.append(item)
        return item

    coordinator = ExternalAuthorityCurrentnessCoordinator()
    sites = SiteStore(_journal("closed-review-sites.jsonl"), coordinator=coordinator)
    sites.register(
        "site-a",
        "Closed review probe site",
        SiteFrame(crs="EPSG:5186", vertical_datum="LOCAL", unit="meter", transform_version="v1"),
        organization_id="org-a",
        actor="operator-a",
        now=_REVIEW_NOW - timedelta(hours=1),
    )
    areas = WorkAreaStore(
        _journal("closed-review-areas.jsonl"),
        site_exists=lambda _: True,
        coordinator=coordinator,
    )
    area = areas.register(
        "site-a",
        name="Closed review zone",
        polygon=_loop.POLYGON,
        crs="EPSG:5186",
        supersedes=None,
        actor="operator-a",
        now=_REVIEW_NOW - timedelta(minutes=50),
    ).work_area
    assert area is not None
    other_area = areas.register(
        "site-a",
        name="Closed review baseline-only zone",
        polygon=_loop.POLYGON,
        crs="EPSG:5186",
        supersedes=None,
        actor="operator-a",
        now=_REVIEW_NOW - timedelta(minutes=49),
    ).work_area
    assert other_area is not None
    # Work-order ID는 store별 순차 Deterministic — 첫 두 WO를 예측해 봉인된
    # source/authority에 바인딩하고 생성 시 단언한다. baseline WO는 현재 zone
    # area에 더해 별도 area를 품어, current만 grant된 경우와 baseline까지
    # grant된 경우를 가르는 회귀 재료가 된다(읽기 투영과 같은 subset 규칙).
    predicted_wo_id = "obs-work-00000001"
    predicted_baseline_wo_id = "obs-work-00000002"
    source = _sealed_source(
        source_work_order_id=predicted_wo_id,
        baseline_work_order_id=predicted_baseline_wo_id,
        work_area_id=area.work_area_id,
        polygon=_loop.POLYGON,
    )
    values = {
        field.name: getattr(source.authority, field.name)
        for field in _fields(ExternalRelativeVolumeExecutionAuthority)
    }
    values["authorized_actor_ids"] = frozenset(values["authorized_actor_ids"])
    authority = ExternalRelativeVolumeExecutionAuthority(**values)
    port = _AuthorityPort(authority)
    port.currentness_coordinator = coordinator
    decisions = ExternalUseDecisionStore(
        _journal("closed-review-decisions.jsonl"),
        coordinator=coordinator,
        history_verifier=_SyntheticHistoryVerifier(),
    )
    volumes = ExternalRelativeVolumeStore(
        _journal("closed-review-volumes.jsonl"),
        authority_port=port,
        currentness_coordinator=coordinator,
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(minutes=5),
            deadline_after_issue=timedelta(hours=1),
            max_attempts=3,
            max_active_requests_per_organization=8,
        ),
        clock=lambda: _REVIEW_NOW,
    )

    history = _History(authority)
    sing_auth = _sing_authority_fn(
        work_order_id=predicted_wo_id,
        work_area_id=area.work_area_id,
        now=_REVIEW_NOW,
        captured_to=_REVIEW_NOW - timedelta(hours=1),
    )
    sing_decision = _sing_decision(sing_auth)
    assert sing_decision.decision_digest is not None
    sing_auth = _replace(
        sing_auth,
        decision_id="decision-single",
        decision_digest=sing_decision.decision_digest,
    )
    sing_port = _SingleAuthority(sing_auth)
    sing_port.currentness_coordinator = coordinator
    sing_port.use_revoked_at = None
    single = _sing_store(tmp_path, sing_port, now=_REVIEW_NOW)
    journals.append(single._journal)  # noqa: SLF001 -- graph-owned durable journal
    adapter = CoreExternalResultReviewSourceAdapter(
        volume_store=volumes,
        decisions=decisions,
        historical_use_authority=history,
        coordinator=coordinator,
        single_volume_store=single,
        single_historical_use_authority=sing_port,
    )
    reviews = ExternalResultReviewStore(
        _journal("closed-review-reviews.jsonl"), source_port=adapter, coordinator=coordinator
    )
    proposals = ExternalReobservationProposalStore(
        _journal("closed-review-proposals.jsonl"), coordinator=coordinator
    )
    proposal_authority = CoreExternalReobservationProposalAuthorityPort(
        reviews=reviews,
        proposals=proposals,
        sites=sites,
        work_areas=areas,
        coordinator=coordinator,
    )
    orders = ObservationWorkOrderStore(
        _journal("closed-review-orders.jsonl"),
        site_exists=lambda site, org: site == "site-a" and org == "org-a",
        work_areas_exist=lambda *_: True,
        external_reobservation_authority_port=proposal_authority,
    )
    order = orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="Closable review WO",
        work_area_ids=[area.work_area_id],
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        idempotency_key="closed-review-wo",
        actor="operator-a",
        now=_REVIEW_NOW - timedelta(minutes=40),
    )
    assert order.work_order_id == predicted_wo_id
    baseline_order = orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="Closable review baseline WO",
        work_area_ids=[area.work_area_id, other_area.work_area_id],
        schedule_id=None,
        execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
        idempotency_key="closed-review-baseline-wo",
        actor="operator-a",
        now=_REVIEW_NOW - timedelta(minutes=39),
    )
    assert baseline_order.work_order_id == predicted_baseline_wo_id
    service = ExternalReobservationProposalService(
        reviews=reviews,
        proposals=proposals,
        sites=sites,
        work_areas=areas,
        work_orders=orders,
        authority_port=proposal_authority,
        coordinator=coordinator,
    )
    verify_external_reobservation_organization_graph(
        organization_id="org-a", work_orders=orders, authority_port=proposal_authority
    )
    graph = LoopGraph(
        service,
        volumes,
        decisions,
        history,
        port,
        journals,
        source,
        single_volumes=single,
        single_history=sing_port,
    )
    decisions.stage_evaluated(
        source.decision,
        intent=ExternalDecisionIntent.from_candidate(source.decision),
        principal=_review_principal(),
        idempotency_key="closed-review-decision",
    )
    decisions.reconcile_pending()
    issued = volumes.issue(
        principal=_review_principal(),
        current_work_order_id=order.work_order_id,
        decision_ref="decision-a",
        idempotency_key="closed-review-volume",
        now=_REVIEW_NOW,
    )
    assert issued.record is not None
    request = issued.record.request
    assert request.request_digest is not None
    fence = _fence()
    volumes.claim(
        request.request_id,
        organization_id="org-a",
        principal_id="worker",
        fence=fence,
        now=_REVIEW_NOW,
    )
    predicted_rel_ref = (
        "external-relative-volume-report-"
        + hashlib.sha256((request.request_id + "\0report").encode()).hexdigest()[:32]
    )
    if record_reports:
        reported = volumes.record_observed_report(
            request.request_id,
            organization_id="org-a",
            principal_id="worker",
            fence=fence,
            observed=ExternalRelativeVolumeObservedReportInput(
                payload=_rel_payload(request.request_digest, authority),
                computed_at=_REVIEW_NOW,
            ),
            now=_REVIEW_NOW,
        )
        assert reported.record is not None and reported.record.report is not None
        assert reported.record.report.report_id == predicted_rel_ref
        rel_ref = reported.record.report.report_id
    else:
        rel_ref = predicted_rel_ref
    sing_report = _record_single(graph, single, sing_port)
    sing_ref = sing_report.report_id

    operator_b = Principal("operator-b", PrincipalKind.OPERATOR, Role.FIELD_OPERATOR, None, "org-a")
    route_clock = clock if clock is not None else (lambda: _REVIEW_NOW)
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(b"closed-review-a").hexdigest(),
                    principal=_review_principal(),
                ),
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(b"closed-review-b").hexdigest(),
                    principal=operator_b,
                ),
            ]
        ),
    )
    app.include_router(
        build_external_result_workflow_router(
            volumes, service, single_volumes=single, clock=route_clock
        )
    )
    client = TestClient(app)
    journal_path = tmp_path / "closed-review-reviews.jsonl"

    def _journal_size() -> int:
        return journal_path.stat().st_size if journal_path.exists() else 0

    return SimpleNamespace(
        graph=graph,
        single=single,
        service=service,
        order=order,
        area=area,
        other_area=other_area,
        baseline_order=baseline_order,
        port=port,
        history=history,
        sing_port=sing_port,
        app=app,
        client=client,
        ahead={"Authorization": "Bearer closed-review-a"},
        bhead={"Authorization": "Bearer closed-review-b"},
        pseudo=SimpleNamespace(app=app, organization_id="org-a"),
        rel_ref=rel_ref,
        sing_ref=sing_ref,
        pending_request=request,
        pending_fence=fence,
        pending_payload=_rel_payload(request.request_digest, authority),
        rel_review=f"/v1/external-relative-volume-reports/{rel_ref}/reviews",
        sing_review=f"/v1/external-single-volume-reports/{sing_ref}/reviews",
        journal_path=journal_path,
        journal_size=_journal_size,
    )


def _install_oidc_as(
    app: Any,
    *,
    principal_id: str,
    site_ids: list[str] | None,
    area_ids: list[str] | None,
) -> dict[str, str]:
    """Map one OIDC subject to a chosen principal with explicit grants (test-only)."""
    key = generate_private_key(public_exponent=65537, key_size=2048)
    registry = OidcSubjectRegistry.from_document(
        {
            "version": "oidc-subject-registry.v2",
            "subjects": [
                {
                    "issuer": _ISSUER,
                    "subject": "granted-operator-subject",
                    "principalId": principal_id,
                    "organizationId": "org-a",
                    "role": "FIELD_OPERATOR",
                    "status": "ACTIVE",
                    "capabilities": [],
                    "allowedSiteIds": site_ids,
                    "allowedWorkAreaIds": area_ids,
                }
            ],
        },
        expected_issuer=_ISSUER,
    )
    app.state.human_auth_mode = HumanAuthMode.OIDC
    app.state.oidc_verifier = OidcJwtVerifier(
        OidcVerifierConfig(
            issuer=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=f"{_ISSUER}/jwks.json",
        ),
        fetch_jwks=lambda: {"keys": [_jwk(key)]},
        subject_registry=registry,
    )
    raw = jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "granted-operator-subject",
            "exp": int(time.time()) + 600,
            "nbf": int(time.time()) - 5,
        },
        key,
        algorithm="RS256",
        headers={"kid": "pilot-route-scope-key"},
    )
    return {"Authorization": f"Bearer {raw}"}


def test_closed_workflow_review_retry_keeps_actor_and_source_gates(
    tmp_path: Path,
) -> None:
    """폐쇄 후 review 재조회는 같은 actor·유효 source의冪등만 허용한다.

    2026-10-28 회귀: `_review_report`의 폐쇄 조기반환이
    `resolve_current`의 actor/currentness/history 검사를 건너뛰어, 폐쇄 후에는
    권한 없는 같은 조직 operator나 외지 grant 신원도 다른 actor의 retained
    review 전문을 201로 받을 수 있었다. 폐쇄 전에는 같은 호출이 409다.
    수정은 폐쇄 분기에서도 `preflight_current_source`로 같은 gate를 두고,
    coordinator 아래 `local_source_is_current`로 retained/현행성을 재확인한다:
    정당한 같은 actor의 폐쇄冪등(저널 불변)은 유지하고, 권한 없음·외지
    grant·취소/만료 source는 409로 fail-closed한다.
    """
    from test_external_result_review_proposals import (
        _NOW as _REVIEW_NOW,
    )

    probe = _closable_review_probe(tmp_path)
    graph, single, service = probe.graph, probe.single, probe.service
    order, history, sing_port = probe.order, probe.history, probe.sing_port
    app, client = probe.app, probe.client
    ahead, bhead, pseudo = probe.ahead, probe.bhead, probe.pseudo
    rel_review, sing_review = probe.rel_review, probe.sing_review
    _journal_size = probe.journal_size
    try:
        # 폐쇄 전: 원 actor만 201, 권한 없는 같은 조직 actor·외지 grant는
        # source gate에서 409 — 이게 기존 동작 계약이다.
        first_rel = client.post(rel_review, headers=ahead)
        first_sing = client.post(sing_review, headers=ahead)
        assert first_rel.status_code == 201, first_rel.text
        assert first_sing.status_code == 201, first_sing.text
        sealed_size = _journal_size()
        assert sealed_size > 0
        retry_rel = client.post(rel_review, headers=ahead)
        assert retry_rel.status_code == 201 and retry_rel.json() == first_rel.json()
        assert _journal_size() == sealed_size  # 冪등 재조회는 append 없다
        assert client.post(rel_review, headers=bhead).status_code == 409
        assert client.post(sing_review, headers=bhead).status_code == 409
        foreign = _install_oidc_v2(
            pseudo, capabilities=[], site_ids=["site-foreign"], area_ids=["wa-foreign"]
        )[0]
        foreign_headers = {"Authorization": f"Bearer {foreign}"}
        assert client.post(rel_review, headers=foreign_headers).status_code == 409
        assert client.post(sing_review, headers=foreign_headers).status_code == 409
        app.state.human_auth_mode = HumanAuthMode.OPAQUE
        assert (
            client.post(
                "/v1/external-relative-volume-reports/missing-x/reviews", headers=ahead
            ).status_code
            == 409
        )
        assert _journal_size() == sealed_size

        operations = service.work_orders.get_operations(
            order.work_order_id, organization_id="org-a"
        )
        service.work_orders.close_operations(
            order.work_order_id,
            organization_id="org-a",
            expected_operations_revision=operations.operations_revision,
            note=None,
            actor="operator-a",
            idempotency_key="closed-review-close",
            now=_REVIEW_NOW,
        )
        assert service.work_orders.is_external_workflow_closed(
            order.work_order_id, organization_id="org-a"
        )

        # 폐쇄 후: 정당한 같은 actor의 冪등만 201·동일 본문·저널 불변.
        app.state.human_auth_mode = HumanAuthMode.OPAQUE
        again_rel = client.post(rel_review, headers=ahead)
        again_sing = client.post(sing_review, headers=ahead)
        assert again_rel.status_code == 201 and again_rel.json() == first_rel.json()
        assert again_sing.status_code == 201 and again_sing.json() == first_sing.json()
        assert _journal_size() == sealed_size

        # 권한 없는 같은 조직 actor·외지 grant 신원은 폐쇄 후에도 409 —
        # 조기반환이 actor/source gate를 건너뛰던 노출의 회귀선이다.
        denied_rel = client.post(rel_review, headers=bhead)
        denied_sing = client.post(sing_review, headers=bhead)
        assert denied_rel.status_code == 409, denied_rel.text
        assert denied_sing.status_code == 409, denied_sing.text
        assert denied_rel.json() == {"detail": "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"}
        foreign = _install_oidc_v2(
            pseudo, capabilities=[], site_ids=["site-foreign"], area_ids=["wa-foreign"]
        )[0]
        foreign_headers = {"Authorization": f"Bearer {foreign}"}
        denied_foreign_rel = client.post(rel_review, headers=foreign_headers)
        denied_foreign_sing = client.post(sing_review, headers=foreign_headers)
        assert denied_foreign_rel.status_code == 409, denied_foreign_rel.text
        assert denied_foreign_sing.status_code == 409, denied_foreign_sing.text
        assert denied_foreign_rel.json() == {"detail": "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"}
        assert _journal_size() == sealed_size

        # 취소/만료된 source는 같은 actor라도 409 — 폐쇄 冪등이 만료 면책이 아니다.
        history.revoked_at = _REVIEW_NOW - timedelta(seconds=1)
        sing_port.use_revoked_at = _REVIEW_NOW - timedelta(seconds=1)
        app.state.human_auth_mode = HumanAuthMode.OPAQUE
        assert client.post(rel_review, headers=ahead).status_code == 409
        assert client.post(sing_review, headers=ahead).status_code == 409
        assert _journal_size() == sealed_size
    finally:
        single._journal.close()  # noqa: SLF001 -- test owns this real journal
        graph.close()


def test_closed_review_retry_rechecks_source_under_coordinator(
    tmp_path: Path,
) -> None:
    """폐쇄 분기는 preflight와 반환 사이 변경을 coordinator 아래서 거부한다.

    2026-10-28 회귀(2): `preflight_current_source`는 coordinator 밖에서
    독립 조회를 수행하므로, preflight 통과 후 반환 전에 authority가
    바뀌면/취소되면 stale receipt가 노출될 수 있다. 정상 `review()`가
    반환/append 직전 coordinator 안에서 `is_current`로 재확인하듯, 폐쇄
    분기도 같은 `evaluated_at`으로 `local_source_is_current`를 재확인한다.
    preflight를 통과한 source라도 최종 가드에서 바뀌었으면 409다.
    """
    from dataclasses import replace

    from test_external_result_review_proposals import (
        _NOW as _REVIEW_NOW,
    )

    probe = _closable_review_probe(tmp_path)
    graph, single, service = probe.graph, probe.single, probe.service
    order, sing_port = probe.order, probe.sing_port
    port = probe.port
    client = probe.client
    ahead = probe.ahead
    rel_review, sing_review = probe.rel_review, probe.sing_review
    _journal_size = probe.journal_size
    try:
        first_rel = client.post(rel_review, headers=ahead)
        first_sing = client.post(sing_review, headers=ahead)
        assert first_rel.status_code == 201, first_rel.text
        assert first_sing.status_code == 201, first_sing.text
        sealed_size = _journal_size()
        assert sealed_size > 0

        operations = service.work_orders.get_operations(
            order.work_order_id, organization_id="org-a"
        )
        service.work_orders.close_operations(
            order.work_order_id,
            organization_id="org-a",
            expected_operations_revision=operations.operations_revision,
            note=None,
            actor="operator-a",
            idempotency_key="closed-review-recheck-close",
            now=_REVIEW_NOW,
        )
        assert service.work_orders.is_external_workflow_closed(
            order.work_order_id, organization_id="org-a"
        )
        honest = client.post(rel_review, headers=ahead)
        assert honest.status_code == 201 and honest.json() == first_rel.json()
        assert _journal_size() == sealed_size

        # preflight와 반환 사이 authority 변경: 두 family 모두 최종 가드에서
        # 409로 거부한다. wrapper가 실제 preflight를 먼저 통과시켜 창(window)이
        # 실재함을 보인다 — preflight만으로는 201이었을 노출이다.
        real_preflight = service.reviews.preflight_current_source
        seen: dict[str, object] = {}
        rel_original = port.authority

        def _wrap_change_relative(receipt: Any, **kwargs: Any) -> Any | None:
            resolved = real_preflight(receipt, **kwargs)
            seen["relative"] = resolved
            port.authority = replace(rel_original, decision_id="withdrawn-history")
            return resolved

        service.reviews.preflight_current_source = _wrap_change_relative
        try:
            changed_rel = client.post(rel_review, headers=ahead)
        finally:
            service.reviews.preflight_current_source = real_preflight
            port.authority = rel_original
        assert seen["relative"] is not None  # preflight는 통과했다
        assert changed_rel.status_code == 409, changed_rel.text
        assert changed_rel.json() == {"detail": "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"}
        assert _journal_size() == sealed_size

        sing_original = sing_port.authority

        def _wrap_change_single(receipt: Any, **kwargs: Any) -> Any | None:
            resolved = real_preflight(receipt, **kwargs)
            seen["single"] = resolved
            sing_port.authority = replace(sing_original, decision_id="withdrawn-history")
            return resolved

        service.reviews.preflight_current_source = _wrap_change_single
        try:
            changed_sing = client.post(sing_review, headers=ahead)
        finally:
            service.reviews.preflight_current_source = real_preflight
            sing_port.authority = sing_original
        assert seen["single"] is not None  # preflight는 통과했다
        assert changed_sing.status_code == 409, changed_sing.text
        assert changed_sing.json() == {"detail": "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"}
        assert _journal_size() == sealed_size

        # 창이 닫히면(복원 후) 같은 actor 冪등은 다시 201이다.
        assert client.post(rel_review, headers=ahead).json() == first_rel.json()
        assert client.post(sing_review, headers=ahead).json() == first_sing.json()
        assert _journal_size() == sealed_size

        # 존재하지 않는 ref는 그대로 409다.
        assert (
            client.post(
                "/v1/external-single-volume-reports/missing-x/reviews", headers=ahead
            ).status_code
            == 409
        )
    finally:
        single._journal.close()  # noqa: SLF001 -- test owns this real journal
        graph.close()


def test_closed_review_enforces_grants_for_authorized_actor(
    tmp_path: Path,
) -> None:
    """인가된 actor라도 grant 밖이면 review 전문을 받지 못한다.

    2026-10-28 회귀(3): review POST는 actor/source gate만 두어, authorized
    actor이면서 Site/WorkArea grant이 맞지 않는 신원도 폐쇄 전·후 모두 201로
    retained review 전문을 받을 수 있었다. 허용 목록의 일반 규칙(핸들러의
    Site/WorkArea 집행)과 /shares와 같은 posture가 요구하는 fail-closed
    grant 검사를 review 쓰기에도 둔다 — 읽기와 같은 범위(report_join 상당:
    provenance·site/zone·baseline/current WO subset). grant가 맞으면 201
    (개방·폐쇄 모두), grant 밖이면 409 — 존재하지 않는 ref와 같은 응답으로
    열거 오라클이 없다. legacy unscoped 동작은 그대로다.
    """
    from test_external_result_review_proposals import (
        _NOW as _REVIEW_NOW,
    )

    probe = _closable_review_probe(tmp_path)
    graph, single, service = probe.graph, probe.single, probe.service
    order, area = probe.order, probe.area
    other_area = probe.other_area
    app, client = probe.app, probe.client
    ahead = probe.ahead
    rel_review, sing_review = probe.rel_review, probe.sing_review
    _journal_size = probe.journal_size
    both_areas = [area.work_area_id, other_area.work_area_id]

    try:
        first_rel = client.post(rel_review, headers=ahead)
        first_sing = client.post(sing_review, headers=ahead)
        assert first_rel.status_code == 201, first_rel.text
        assert first_sing.status_code == 201, first_sing.text
        sealed_size = _journal_size()
        assert sealed_size > 0

        # 폐쇄 전: grant가 맞는 매핑 신원은 같은 actor로서 201(개방 경로의
        # grant 통과 + 冪등 반환), 외지 grant는 409다. baseline WO까지 품은
        # grant와 현재 WO만 품은 grant를 가른다: 후자는 single만 201이다.
        granted_headers = _install_oidc_as(
            app,
            principal_id="operator-a",
            site_ids=["site-a"],
            area_ids=both_areas,
        )
        assert client.post(rel_review, headers=granted_headers).status_code == 201
        assert client.post(sing_review, headers=granted_headers).status_code == 201
        assert _journal_size() == sealed_size
        current_only_headers = _install_oidc_as(
            app,
            principal_id="operator-a",
            site_ids=["site-a"],
            area_ids=[area.work_area_id],
        )
        assert client.post(sing_review, headers=current_only_headers).status_code == 201
        assert client.post(rel_review, headers=current_only_headers).status_code == 409
        assert _journal_size() == sealed_size
        foreign_headers = _install_oidc_as(
            app,
            principal_id="operator-a",
            site_ids=["site-foreign"],
            area_ids=["wa-foreign"],
        )
        assert client.post(rel_review, headers=foreign_headers).status_code == 409
        assert client.post(sing_review, headers=foreign_headers).status_code == 409
        assert _journal_size() == sealed_size

        operations = service.work_orders.get_operations(
            order.work_order_id, organization_id="org-a"
        )
        service.work_orders.close_operations(
            order.work_order_id,
            organization_id="org-a",
            expected_operations_revision=operations.operations_revision,
            note=None,
            actor="operator-a",
            idempotency_key="closed-review-grant-close",
            now=_REVIEW_NOW,
        )
        assert service.work_orders.is_external_workflow_closed(
            order.work_order_id, organization_id="org-a"
        )

        # 폐쇄 후: grant가 맞는 actor는 201·동일 본문·저널 불변.
        app.state.human_auth_mode = HumanAuthMode.OPAQUE
        assert client.post(rel_review, headers=ahead).json() == first_rel.json()
        assert client.post(sing_review, headers=ahead).json() == first_sing.json()
        granted_headers = _install_oidc_as(
            app,
            principal_id="operator-a",
            site_ids=["site-a"],
            area_ids=both_areas,
        )
        granted_rel = client.post(rel_review, headers=granted_headers)
        granted_sing = client.post(sing_review, headers=granted_headers)
        assert granted_rel.status_code == 201, granted_rel.text
        assert granted_sing.status_code == 201, granted_sing.text
        assert granted_rel.json() == first_rel.json()
        assert granted_sing.json() == first_sing.json()
        assert _journal_size() == sealed_size

        # 폐쇄 후: 현재 WO만 grant된 actor는 single만 201, relative는 409 —
        # baseline WO subset이 빠지면 retained baseline 행을 받을 수 없다.
        current_only_headers = _install_oidc_as(
            app,
            principal_id="operator-a",
            site_ids=["site-a"],
            area_ids=[area.work_area_id],
        )
        assert client.post(sing_review, headers=current_only_headers).status_code == 201
        denied_baseline = client.post(rel_review, headers=current_only_headers)
        assert denied_baseline.status_code == 409, denied_baseline.text
        assert denied_baseline.json() == {"detail": "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"}
        assert _journal_size() == sealed_size

        # 폐쇄 후: 인가된 actor라도 외지 site/area grant는 409 — 본문·저널 불변.
        for label, grant in (
            ("foreign-site", {"site_ids": ["site-foreign"], "area_ids": [area.work_area_id]}),
            ("foreign-area", {"site_ids": ["site-a"], "area_ids": ["wa-foreign"]}),
        ):
            scoped = _install_oidc_as(app, principal_id="operator-a", **grant)
            denied_rel = client.post(rel_review, headers=scoped)
            denied_sing = client.post(sing_review, headers=scoped)
            assert denied_rel.status_code == 409, (label, denied_rel.text)
            assert denied_sing.status_code == 409, (label, denied_sing.text)
            assert denied_rel.json() == {"detail": "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"}
            assert _journal_size() == sealed_size, label
        assert _journal_size() == sealed_size
    finally:
        single._journal.close()  # noqa: SLF001 -- test owns this real journal
        graph.close()


def test_open_review_denies_scoped_principal_when_report_lands_mid_request(
    tmp_path: Path,
) -> None:
    """resolver가 None을 반환한 뒤 review()가 resolve하기 전 보고가 생겨도 409다.

    2026-10-28 회귀(4): 개방 경로에서 `resolver()`가 None이면 scope 검사 없이
    바로 `service.reviews.review()`를 호출한다. 그 사이 worker가 보고를
    남기면 live gate가 통과되어, grant 밖의 인가 actor도 201로 전문을 받고
    review까지 기록된다. 스레드+게이트로 재현을 결정적으로 고정한다: route의
    resolver가 먼저 None을 반환한 뒤에야 worker가 실제 store method로 보고를
    남기고, route 내부 preflight는 worker 완료를 기다렸다가 진행한다.
    grant 밖 scoped 신원은 409이며 journal에 쓰지 않고, unscoped 동일 actor는
    기존대로 201을 받는다(보고가 실재함이 증명된다).
    """
    import threading

    from ksi_core.domains.external.quantity.external_relative_volumes import (
        ExternalRelativeVolumeObservedReportInput,
    )
    from test_external_result_review_proposals import (
        _NOW as _REVIEW_NOW,
    )

    probe = _closable_review_probe(tmp_path, record_reports=False)
    graph, single = probe.graph, probe.single
    client = probe.client
    ahead = probe.ahead
    rel_review = probe.rel_review
    request, fence, payload = probe.pending_request, probe.pending_fence, probe.pending_payload
    predicted_ref = probe.rel_ref
    journal_size = probe.journal_size
    try:
        assert journal_size() == 0

        real_resolver = graph.volumes.resolve_historical_report_ref
        real_resolve = graph.service.reviews.source_port.resolve_current
        resolver_ran = threading.Event()
        worker_done = threading.Event()

        def _gated_resolver(*args: Any, **kwargs: Any) -> Any | None:
            resolved = real_resolver(*args, **kwargs)
            assert resolved is None  # 보고는 아직 없어야 한다
            resolver_ran.set()
            return resolved

        def _gated_resolve(**kwargs: Any) -> Any | None:
            assert worker_done.wait(timeout=30)
            return real_resolve(**kwargs)

        graph.volumes.resolve_historical_report_ref = _gated_resolver
        graph.service.reviews.source_port.resolve_current = _gated_resolve
        try:

            def _worker() -> None:
                assert resolver_ran.wait(timeout=30)
                landed = graph.volumes.record_observed_report(
                    request.request_id,
                    organization_id="org-a",
                    principal_id="worker",
                    fence=fence,
                    observed=ExternalRelativeVolumeObservedReportInput(
                        payload=payload, computed_at=_REVIEW_NOW
                    ),
                    now=_REVIEW_NOW,
                )
                assert landed.record is not None and landed.record.report is not None
                assert landed.record.report.report_id == predicted_ref
                worker_done.set()

            thread = threading.Thread(target=_worker)
            thread.start()
            try:
                scoped = _install_oidc_as(
                    probe.app,
                    principal_id="operator-a",
                    site_ids=["site-foreign"],
                    area_ids=["wa-foreign"],
                )
                denied = client.post(rel_review, headers=scoped)
            finally:
                thread.join(timeout=30)
            assert worker_done.is_set()  # worker가 실제로 보고를 남겼다
            assert denied.status_code == 409, denied.text
            assert denied.json() == {"detail": "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"}
            assert journal_size() == 0  # fail-closed: 쓰기 없음
        finally:
            graph.volumes.resolve_historical_report_ref = real_resolver
            graph.service.reviews.source_port.resolve_current = real_resolve

        # 같은 보고는 실재한다: unscoped 동일 actor는 기존대로 201을 받는다.
        probe.app.state.human_auth_mode = HumanAuthMode.OPAQUE
        created = client.post(rel_review, headers=ahead)
        assert created.status_code == 201, created.text
        assert journal_size() > 0
    finally:
        single._journal.close()  # noqa: SLF001 -- test owns this real journal
        graph.close()


def test_production_guard_current_revalidates_revocation_under_coordinator(
    tmp_path: Path,
) -> None:
    """실제 제품 catalog port: revoke는 같은 coordinator 아래 최종 guard에서 재확인된다.

    closed-review 분기가 의존하는 바로 그 메커니즘이다(preflight는 밖,
    최종 확인은 안). synthetic history double이 아니라 실제
    ExternalQuantitativeAuthorityCatalog + 공유 coordinator로 검증한다:
    revoke 전 guard는 통과, revoke 후 같은 coordinator 아래 guard는 거부한다.
    revoke 자체가 coordinator.mutation을 잡으므로 guarded_read 안에서는
    끼어들 수 없고, guard는 항상 최신 revoked_at을 다시 읽는다.
    """
    import hashlib
    from datetime import timedelta as _timedelta

    import test_external_quantitative_authority as _cat
    from ksi_core.auth import Principal, PrincipalKind, Role
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
    from ksi_core.external_quantitative_authority import ExternalQuantitativeAuthorityCatalog

    now = _cat._NOW
    later = now + _timedelta(minutes=1)
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "guard-catalog.jsonl"),
        currentness_coordinator=coordinator,
        mapping_admission_validator=lambda _record, _at: True,
        execution_template_resolver=lambda _record, _at: _cat._template(),
    )
    mapping = _cat._mapping()
    assert catalog.admit_mapping(mapping, actor="authority-a", now=now) is not None
    decision_digest = "sha256:" + hashlib.sha256(b"decision-a").hexdigest()
    catalog.bind_decision_resolver(
        lambda decision_id, principal, current_work_order_id: (
            {
                "decisionId": "decision-a",
                "decisionDigest": decision_digest,
                "organizationId": "org-a",
                "siteId": "site-a",
                "baseline": mapping.baseline.subject,
                "current": mapping.current.subject,
                "zoneDigest": mapping.zone_snapshot.definition_digest,
                "policyDigest": mapping.validation_policy_digest,
                "compatibilityMappingDigest": mapping.mapping_digest,
                "decisionUse": "RELATIVE_VOLUME",
                "decisionVerdict": "ELIGIBLE",
                "decidedAt": now,
            }
            if (decision_id, principal.organization_id, current_work_order_id)
            == ("decision-a", "org-a", "work-current")
            else None
        )
    )
    operator = Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-a")
    execution = catalog.activate_execution(
        decision_ref="decision-a",
        principal=operator,
        current_work_order_id="work-current",
        now=now,
    )
    assert execution is not None

    # preflight 성격: coordinator 없이 보면 아직 유효하다.
    with catalog.guard_current(authority=execution, principal=operator, now=now) as first:
        assert first == execution

    # revoke는 같은 coordinator의 mutation 아래 기록된다.
    assert catalog.revoke_execution(
        execution.historical_authority_digest, actor="authority-a", now=later
    )

    # 최종 guard는 공유 coordinator 아래 최신 revoked_at을 다시 읽어 거부한다.
    with (
        coordinator.guarded_read(),
        catalog.guard_current(authority=execution, principal=operator, now=later) as second,
    ):
        assert second is None


def test_closed_review_guard_uses_fresh_time_not_preflight_time(tmp_path: Path) -> None:
    """폐쇄 분기의 최종 확인은 반환 직전 시각으로 평가한다.

    2026-10-28 회귀(4): preflight 통과와 최종 guard가 같은 `at`을 쓰면,
    preflight 이후·반환 이전에 커밋된 revoke/만료가 guard에서 보이지 않는다
    (production `active_at`은 revoked_at 이후 시각에만 거부하므로). 실제
    제품 catalog probe로 확인한 메커니즘이다. 수정은 guard를 반환 직전의
    fresh 시각으로 평가한다(worker-input 최종 확인과 같은 accepted pattern).
    스크립트 clock으로 preflight는 T0에 통과시키고 guard는 T0+2일에 평가
    하게 하면, 정당한 actor의 폐쇄 冪등도 409로 fail-closed한다(저널 불변).
    single-at 코드에서는 201이 되어 이 테스트가 실패한다.
    """
    from test_external_result_review_proposals import (
        _NOW as _REVIEW_NOW,
    )
    from test_external_result_review_proposals import (
        _principal as _review_principal,
    )

    t0 = _REVIEW_NOW
    t2 = _REVIEW_NOW + timedelta(days=2)
    calls: list[datetime] = []

    def _scripted_clock() -> datetime:
        calls.append(t0 if len(calls) == 0 else t2)
        return calls[-1]

    probe = _closable_review_probe(tmp_path, clock=_scripted_clock)
    graph, single, service = probe.graph, probe.single, probe.service
    order = probe.order
    client = probe.client
    ahead = probe.ahead
    rel_review = probe.rel_review
    _journal_size = probe.journal_size
    try:
        receipt = service.reviews.review(
            organization_id="org-a",
            report_ref=probe.rel_ref,
            principal=_review_principal(),
            evaluated_at=t0,
        )
        sealed_size = _journal_size()
        assert sealed_size > 0

        service.work_orders.close_operations(
            order.work_order_id,
            organization_id="org-a",
            expected_operations_revision=service.work_orders.get_operations(
                order.work_order_id, organization_id="org-a"
            ).operations_revision,
            note=None,
            actor="operator-a",
            idempotency_key="closed-review-fresh-time-close",
            now=t0,
        )
        assert service.work_orders.is_external_workflow_closed(
            order.work_order_id, organization_id="org-a"
        )

        # preflight(T0)는 통과하지만 최종 guard(T0+2일, 두 family 유효기간 밖)는
        # 거부한다 — guard가 preflight 시각을 재사용했다면 201이었을 것이다.
        denied = client.post(rel_review, headers=ahead)
        assert denied.status_code == 409, denied.text
        assert denied.json() == {"detail": "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"}
        assert _journal_size() == sealed_size
        # receipt 자체는 그대로 retained되어 있다.
        assert service.reviews.get_for_report(probe.rel_ref, organization_id="org-a") == receipt
    finally:
        single._journal.close()  # noqa: SLF001 -- test owns this real journal
        graph.close()


def test_legacy_unscoped_volume_lists_keep_organization_behavior(tmp_path: Path) -> None:
    """opaque unscoped 신원은 volume 목록의 기존 조직 필터 동작을 유지한다."""
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        client = TestClient(fixture.app)
        work_order_id = fixture.baseline.work_order_id
        headers = fixture.operator_headers()
        assert (
            client.get(
                f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests",
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.get(
                f"/v1/observation-work-orders/{work_order_id}/single-volume-requests",
                headers=headers,
            ).status_code
            == 200
        )
    finally:
        fixture.close()


def test_scoped_work_order_guard_semantics() -> None:
    """volume 목록 가드: area 부분집합·site 불일치·의존성 부재·legacy 조기 반환."""
    from ksi_core.domains.external.quantity.external_relative_volumes import (
        _require_scoped_work_order,
    )
    from ksi_core.domains.external.quantity.external_single_volumes import (
        _require_scoped_work_order as _require_single_volume_work_order,
    )

    order = SimpleNamespace(site_id="site-a", work_area_ids=["wa-a", "wa-b"])

    class _Store:
        def get(self, work_order_id: str, *, organization_id: str) -> Any:
            return order if work_order_id == "wo-1" else None

    scoped = Principal(
        principal_id="scoped-operator",
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id="org-a",
        allowed_site_ids=frozenset({"site-a"}),
        allowed_work_area_ids=frozenset({"wa-a", "wa-b"}),
    )
    _require_scoped_work_order(_Store(), scoped, "wo-1")

    partial = replace(scoped, allowed_work_area_ids=frozenset({"wa-a"}))
    with pytest.raises(HTTPException) as partial_exc:
        _require_scoped_work_order(_Store(), partial, "wo-1")
    assert partial_exc.value.status_code == 404  # 부분 겹침은 통과가 아니다

    foreign_site = replace(scoped, allowed_site_ids=frozenset({"site-b"}))
    with pytest.raises(HTTPException) as site_exc:
        _require_scoped_work_order(_Store(), foreign_site, "wo-1")
    assert site_exc.value.status_code == 404

    with pytest.raises(HTTPException) as none_exc:
        _require_scoped_work_order(None, scoped, "wo-1")
    assert none_exc.value.status_code == 404  # 의존성 부재는 fail-closed

    legacy = Principal(
        principal_id="legacy-operator",
        kind=PrincipalKind.OPERATOR,
        role=Role.ADMIN,
        device_id=None,
        organization_id="org-a",
    )
    _require_scoped_work_order(None, legacy, "wo-1")  # legacy는 store 없이 조기 반환

    _require_single_volume_work_order(_Store(), scoped, "wo-1")  # 단일 체적 가드도 동일


# ── 2026-10-20: V3 불완전 메타데이터 ingress 의 mapped 신원 경계 ─────────


def test_mapped_oidc_v3_ingress_follows_v2_scope_matrix(tmp_path: Path) -> None:
    """V3 등록·업로드·봉인은 V2와 같은 Site/WorkArea grant 가드 안에서만 열린다.

    허용 목록은 정확한 V3 템플릿 하나만 추가한다(접두어 확장 없음). 매핑된
    FIELD_OPERATOR는 같은 Site/WorkArea grant로 register→grants→seal을 마치지만,
    외지 Site/area·교차 조직은 존재 여부를 드러내지 않고 404로 접히며 저널에
    쓰지 않는다. VIEWER는 403, REVOKED 신원은 401로 fail-closed한다.
    """
    from test_external_reconstruction_v3_incomplete_metadata import _v3_wire

    v3_route = (
        "POST",
        "/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions-v3",
    )
    assert v3_route in _OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST
    assert (
        "POST",
        "/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions-v2",
    ) in _OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST
    assert (
        sum(1 for entry in _OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST if "submissions-v3" in entry[1])
        == 1
    )

    fixture = build_local_analysis_api_fixture(tmp_path, v2_dsm_only=True)
    try:
        client = TestClient(fixture.app)
        order_id = fixture.baseline.work_order_id
        epoch_id = fixture._baseline_revision.submission.observation_epoch_id
        register_path = (
            f"/v1/observation-work-orders/{order_id}/external-reconstruction-submissions-v3"
        )

        def journal_sizes() -> dict[str, int]:
            return {
                str(path.relative_to(tmp_path)): path.stat().st_size
                for path in sorted(tmp_path.rglob("*.jsonl"))
            }

        token, _key = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=[fixture.site_id],
            area_ids=[fixture.work_area_id],
        )
        headers = {"Authorization": f"Bearer {token}"}
        wire = _v3_wire(
            epoch_id=epoch_id,
            submission_id="oidc-v3-allowed",
            submitted_by="pilot-mapped-operator",
        )
        registered = client.post(register_path, headers=headers, json=wire)
        assert registered.status_code == 201, registered.text
        ref = registered.json()["submissionRef"]
        revision_path = (
            f"/v1/observation-work-orders/{order_id}/"
            f"external-reconstruction-submissions/{ref}/revisions/1"
        )
        grants = client.post(revision_path + "/upload-grants", headers=headers)
        assert grants.status_code == 200, grants.text
        object_key = grants.json()["grants"][0]["objectKey"]
        fixture.storage.put_bytes(
            object_key, b"v3 ortho bytes", content_type="application/octet-stream"
        )
        sealed = client.post(revision_path + "/seal", headers=headers)
        assert sealed.status_code == 200, sealed.text
        assert sealed.json()["submission"]["contractVersion"] == (
            "external-reconstruction-submission.v3"
        )

        before = journal_sizes()

        # 외지 area grant: 같은 Site라도 WorkOrder area가 grant 밖이면 404.
        foreign_area_token, _ = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=[fixture.site_id],
            area_ids=["wa-ungranted-0001"],
        )
        foreign_area = client.post(
            register_path,
            headers={"Authorization": f"Bearer {foreign_area_token}"},
            json=_v3_wire(
                epoch_id=epoch_id,
                submission_id="oidc-v3-foreign-area",
                submitted_by="pilot-mapped-operator",
            ),
        )
        assert foreign_area.status_code == 404
        assert journal_sizes() == before

        # 외지 Site grant: area가 맞아도 Site가 다르면 404.
        foreign_site_token, _ = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=["site-foreign-grant"],
            area_ids=[fixture.work_area_id],
        )
        foreign_site = client.post(
            register_path,
            headers={"Authorization": f"Bearer {foreign_site_token}"},
            json=_v3_wire(
                epoch_id=epoch_id,
                submission_id="oidc-v3-foreign-site",
                submitted_by="pilot-mapped-operator",
            ),
        )
        assert foreign_site.status_code == 404
        assert journal_sizes() == before

        # 교차 조직 신원: 이 조직의 WorkOrder를 해석하지 못한다(404 비노출).
        cross_org_token, _ = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=[fixture.site_id],
            area_ids=[fixture.work_area_id],
            organization_id="other-organization",
        )
        cross_org = client.post(
            register_path,
            headers={"Authorization": f"Bearer {cross_org_token}"},
            json=_v3_wire(
                epoch_id=epoch_id,
                submission_id="oidc-v3-cross-org",
                submitted_by="pilot-mapped-operator",
            ),
        )
        assert cross_org.status_code == 404
        assert journal_sizes() == before

        # VIEWER 매핑: route는 열려도 SITES_WRITE 핸들러 게이트가 403으로 막는다.
        viewer_token, _ = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=[fixture.site_id],
            area_ids=[fixture.work_area_id],
            role="VIEWER",
        )
        viewer_denied = client.post(
            register_path,
            headers={"Authorization": f"Bearer {viewer_token}"},
            json=_v3_wire(
                epoch_id=epoch_id,
                submission_id="oidc-v3-viewer",
                submitted_by="pilot-mapped-operator",
            ),
        )
        assert viewer_denied.status_code == 403
        assert journal_sizes() == before

        # REVOKED 매핑: 신원 자체가 해소되지 않아 401로 fail-closed한다.
        revoked_token, _ = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=[fixture.site_id],
            area_ids=[fixture.work_area_id],
            status="REVOKED",
        )
        revoked = client.post(
            register_path,
            headers={"Authorization": f"Bearer {revoked_token}"},
            json=_v3_wire(
                epoch_id=epoch_id,
                submission_id="oidc-v3-revoked",
                submitted_by="pilot-mapped-operator",
            ),
        )
        assert revoked.status_code == 401
        assert journal_sizes() == before
    finally:
        fixture.close()
