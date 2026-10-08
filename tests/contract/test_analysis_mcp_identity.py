from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    AuthRegistryError,
    Permission,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    principal_permissions,
)
from ksi_core.composition.external_graph import ExternalAnalysisLocalGraphConfig
from ksi_event_contracts.external_analysis_activation import AnalysisActivationV1


def _client_principal(
    *,
    site_ids: frozenset[str] | None = frozenset({"site-a"}),
    work_area_ids: frozenset[str] | None = frozenset({"wa-site-a-0001"}),
    role: Role | None = None,
    device_id: str | None = None,
) -> Principal:
    return Principal(
        principal_id="analysis-mcp-client-a",
        kind=PrincipalKind.ANALYSIS_MCP_CLIENT,
        role=role,
        device_id=device_id,
        organization_id="org-a",
        allowed_site_ids=site_ids,
        allowed_work_area_ids=work_area_ids,
    )


def test_analysis_mcp_client_gets_only_explicit_analysis_permissions() -> None:
    principal = _client_principal()

    assert principal_permissions(principal) == frozenset(
        {Permission.ANALYSIS_API_READ, Permission.ANALYSIS_API_CREATE}
    )


@pytest.mark.parametrize(
    ("site_ids", "work_area_ids"),
    [
        (None, frozenset({"wa-site-a-0001"})),
        (frozenset({"site-a"}), None),
        (frozenset(), frozenset({"wa-site-a-0001"})),
        (frozenset({"site-a"}), frozenset()),
    ],
)
def test_analysis_mcp_client_requires_explicit_scope(
    site_ids: frozenset[str] | None, work_area_ids: frozenset[str] | None
) -> None:
    principal = _client_principal(site_ids=site_ids, work_area_ids=work_area_ids)
    record = PrincipalTokenRecord(
        token_sha256=hashlib.sha256(b"test-analysis-mcp-token").hexdigest(),
        principal=principal,
    )

    with pytest.raises(AuthRegistryError):
        AuthRegistry([record])


def test_analysis_mcp_client_cannot_have_operator_or_device_identity() -> None:
    with pytest.raises(AuthRegistryError):
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(b"role-mcp-token").hexdigest(),
                    principal=_client_principal(role=Role.ADMIN),
                )
            ]
        )


def test_mcp_identity_controls_live_egress_scope_and_analysis_only_routes(tmp_path: Path) -> None:
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=True)
    try:
        client = TestClient(fixture.app)
        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "mcp-v2-existing"},
            json={
                "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                "current": fixture.current.model_dump(by_alias=True, mode="json"),
            },
        )
        assert created.status_code == 202, created.text
        analysis_id = created.json()["analysisId"]
        observations_path = f"/v1/sites/{fixture.site_id}/analysis-observations"
        mcp_headers = fixture.mcp_client_headers()
        observations = client.get(observations_path, headers=mcp_headers)
        assert observations.status_code == 200, observations.text
        assert observations.headers["X-KSI-External-AI-Egress"] == "ALLOWED"
        for path in (
            f"/v2/sites/{fixture.site_id}/analyses",
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}",
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
        ):
            response = client.get(path, headers=mcp_headers)
            assert response.status_code == 200, response.text
            assert response.headers["X-KSI-External-AI-Egress"] == "ALLOWED"

        other_area_scope = client.get(
            observations_path,
            headers=fixture.mcp_other_area_headers(),
        )
        assert other_area_scope.status_code == 200, other_area_scope.text
        assert other_area_scope.json()["items"] == []
        assert other_area_scope.headers["X-KSI-External-AI-Egress"] == "ALLOWED"
        other_area_list = client.get(
            f"/v2/sites/{fixture.site_id}/analyses",
            headers=fixture.mcp_other_area_headers(),
        )
        assert other_area_list.status_code == 200
        assert other_area_list.json()["items"] == []
        other_area_detail = client.get(
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}",
            headers=fixture.mcp_other_area_headers(),
        )
        assert other_area_detail.status_code == 404
        wrong_site_detail = client.get(
            f"/v2/sites/site-outside-grant/analyses/{analysis_id}", headers=mcp_headers
        )
        assert wrong_site_detail.status_code == 404

        operator_with_forged_purpose = client.get(
            observations_path,
            headers={
                **fixture.operator_headers(),
                "X-KSI-Access-Purpose": "EXTERNAL_AI",
            },
        )
        assert operator_with_forged_purpose.status_code == 200
        assert "X-KSI-External-AI-Egress" not in operator_with_forged_purpose.headers

        denied_site_discovery = client.get("/v1/sites", headers=mcp_headers)
        assert denied_site_discovery.status_code == 403
        denied_site_write = client.put(
            f"/v1/sites/{fixture.site_id}/aoi", headers=mcp_headers, json={}
        )
        assert denied_site_write.status_code == 403
        denied_consent_creation = client.post(
            "/v1/sites",
            headers=mcp_headers,
            json={
                "siteId": "site-mcp-cannot-create",
                "name": "MCP cannot register or consent a Site",
                "siteFrame": {
                    "crs": "EPSG:5186",
                    "verticalDatum": "EGM96 height",
                    "unit": "meter",
                    "transformVersion": "fixture-v1",
                },
                "aiEgressAllowed": True,
            },
        )
        assert denied_consent_creation.status_code == 403

        wrong_site = client.get(
            "/v1/sites/site-outside-grant/analysis-observations", headers=mcp_headers
        )
        assert wrong_site.status_code == 404
        wrong_work_area = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/wa-outside-grant/analyses",
            headers={**mcp_headers, "Idempotency-Key": "out-of-scope-work-area"},
            json={
                "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                "current": fixture.current.model_dump(by_alias=True, mode="json"),
            },
        )
        assert wrong_work_area.status_code == 403
        site_store = fixture.app.state.site_store
        site = site_store.get_scoped(fixture.site_id, fixture.organization_id)
        assert site is not None and site.ai_egress_allowed
        site_store._sites[fixture.site_id] = replace(site, ai_egress_allowed=False)
        consent_revoked_v2 = client.get(
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
            headers=mcp_headers,
        )
        assert consent_revoked_v2.status_code == 403
        assert consent_revoked_v2.json()["detail"] == "AI_EGRESS_NOT_ALLOWED"
        assert "X-KSI-External-AI-Egress" not in consent_revoked_v2.headers

        for worker_headers in (
            fixture.worker_headers(),
            fixture.validation_worker_headers(),
        ):
            worker_claim = client.get(
                observations_path,
                headers={**worker_headers, "X-KSI-Access-Purpose": "EXTERNAL_AI"},
            )
            assert worker_claim.status_code == 403
            assert "X-KSI-External-AI-Egress" not in worker_claim.headers
    finally:
        fixture.close()


def test_analysis_mcp_client_cannot_reach_unbounded_v1_analysis_views(tmp_path: Path) -> None:
    from analysis_api_local_fixture import build_local_analysis_api_fixture
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from ksi_core.auth import require_principal

    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=True)
    try:
        client = TestClient(fixture.app)
        body = {
            "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
            "current": fixture.current.model_dump(by_alias=True, mode="json"),
        }
        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "operator-v1-compat"},
            json=body,
        )
        assert created.status_code == 202, created.text
        analysis_id = created.json()["analysisId"]
        client_token = fixture.mcp_client_headers()
        v1_paths = (
            ("POST", f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses"),
            ("GET", f"/v1/sites/{fixture.site_id}/analyses"),
            ("GET", f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}"),
            ("GET", f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/result"),
            ("GET", f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/evidence"),
        )
        responses = [
            client.request(
                method,
                path,
                headers={
                    **client_token,
                    **({"Idempotency-Key": "mcp-v1-denied"} if method == "POST" else {}),
                },
                json=body if method == "POST" else None,
            )
            for method, path in v1_paths
        ]
        assert [response.status_code for response in responses] == [403] * len(v1_paths)
        assert all("X-KSI-External-AI-Egress" not in response.headers for response in responses)

        @fixture.app.get("/v1/sites/{site_id}/analyses/{analysis_id}/evidence/export")
        def v1_path_lookalike(
            principal: Principal = Depends(require_principal()),  # noqa: B008
        ) -> dict[str, str]:
            return {"principalId": principal.principal_id}

        lookalike = client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/evidence/export",
            headers=client_token,
        )
        assert lookalike.status_code == 403
        assert "X-KSI-External-AI-Egress" not in lookalike.headers

        operator_reads = [
            client.get(path, headers=fixture.operator_headers())
            for _, path in v1_paths[1:]
        ]
        assert [response.status_code for response in operator_reads] == [200] * len(operator_reads)
        assert all(
            "X-KSI-External-AI-Egress" not in response.headers for response in operator_reads
        )
    finally:
        fixture.close()


def test_mcp_identity_requires_current_site_consent_without_purpose_header(tmp_path: Path) -> None:
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=False)
    try:
        client = TestClient(fixture.app)
        path = f"/v1/sites/{fixture.site_id}/analysis-observations"

        mcp_denied = client.get(path, headers=fixture.mcp_client_headers())
        assert mcp_denied.status_code == 403
        assert mcp_denied.json()["detail"] == "AI_EGRESS_NOT_ALLOWED"

        operator_read = client.get(
            path,
            headers={
                **fixture.operator_headers(),
                "X-KSI-Access-Purpose": "EXTERNAL_AI",
            },
        )
        assert operator_read.status_code == 200
        assert "X-KSI-External-AI-Egress" not in operator_read.headers
    finally:
        fixture.close()


def test_mcp_identity_rechecks_site_consent_on_each_request(tmp_path: Path) -> None:
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=True)
    try:
        client = TestClient(fixture.app)
        path = f"/v1/sites/{fixture.site_id}/analysis-observations"
        first = client.get(path, headers=fixture.mcp_client_headers())
        assert first.status_code == 200
        assert first.headers["X-KSI-External-AI-Egress"] == "ALLOWED"

        site_store = fixture.app.state.site_store
        site = site_store.get_scoped(fixture.site_id, fixture.organization_id)
        assert site is not None and site.ai_egress_allowed
        site_store._sites[fixture.site_id] = replace(site, ai_egress_allowed=False)

        after_revocation = client.get(path, headers=fixture.mcp_client_headers())
        assert after_revocation.status_code == 403
        assert after_revocation.json()["detail"] == "AI_EGRESS_NOT_ALLOWED"
        assert "X-KSI-External-AI-Egress" not in after_revocation.headers
    finally:
        fixture.close()


def test_analysis_stores_enforce_mcp_permission_and_site_work_area_scope(tmp_path: Path) -> None:
    from analysis_api_local_fixture import build_local_analysis_api_fixture
    from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
        AnalysisAssessmentRequestV2,
        AnalysisEpochSelectionV2,
    )

    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=True)
    try:
        client = TestClient(fixture.app)
        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "mcp-scope-store"},
            json={
                "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                "current": fixture.current.model_dump(by_alias=True, mode="json"),
            },
        )
        assert created.status_code == 202, created.text
        analysis_id = created.json()["analysisId"]
        principal = _client_principal()
        wiring = fixture.app.state.external_analysis_wiring

        assert wiring.assessments.get_history_for_principal(
            analysis_id, principal=principal
        ) is not None
        out_of_area = _client_principal(work_area_ids=frozenset({"wa-site-a-9999"}))
        assert wiring.assessments.get_history_for_principal(
            analysis_id, principal=out_of_area
        ) is None

        request = AnalysisAssessmentRequestV2(
            request_id="mcp-direct-cross-area",
            work_area_id=fixture.work_area_id,
            baseline=AnalysisEpochSelectionV2(subject=fixture._baseline_subject),
            current=AnalysisEpochSelectionV2(subject=fixture._current_subject),
            idempotency_key="mcp-direct-cross-area",
        )
        with pytest.raises(PermissionError, match="outside client scope"):
            wiring.assessments.assess_and_record(
                principal=out_of_area, request=request, now=fixture._fixture_now
            )

        calculation_request_id = created.json()["authority"]["calculationRequestId"]
        assert calculation_request_id
        with pytest.raises(PermissionError, match="outside client scope"):
            wiring.calculations.get_history_for_principal(
                calculation_request_id, principal=out_of_area
            )
    finally:
        fixture.close()


def test_analysis_mcp_client_is_denied_auth_only_and_unrelated_generic_routes(
    tmp_path: Path,
) -> None:
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=True)
    try:
        client = TestClient(fixture.app)
        headers = fixture.mcp_client_headers()
        # P3 Task 5: /v1/processing-resource-policies retired with the managed
        # assembly (platform mounts no processing routes) — the roster route is
        # the staying generic surface the MCP client must still be denied.
        paths = ("/v1/auth/whoami", "/v1/organization-work-roster", "/v1/sites")
        responses = [client.get(path, headers=headers) for path in paths]
        assert [response.status_code for response in responses] == [403, 403, 403]
        # The retired managed route is absent entirely (404), not merely denied.
        retired = client.get("/v1/processing-resource-policies", headers=headers)
        assert retired.status_code == 404
        assert all("X-KSI-External-AI-Egress" not in response.headers for response in responses)
    finally:
        fixture.close()


def test_analysis_mcp_client_can_use_only_the_six_analysis_routes(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    from analysis_api_local_fixture import build_local_analysis_api_fixture
    from test_external_analysis_activation import _write_activation

    def active_activation(
        config: ExternalAnalysisLocalGraphConfig, worker: Principal
    ) -> AnalysisActivationV1:
        now = datetime.now(UTC)
        return _write_activation(
            tmp_path / "mcp-v2-activation",
            bindings={
                "organization_id": "org-a",
                "policy": config.policy,
                "runtime": config.runtime,
                "resource_envelope": config.resource_envelope,
                "worker_principal": worker,
            },
            activation_fields={
                "issuedAt": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "validUntil": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            },
        )[2]

    fixture = build_local_analysis_api_fixture(
        tmp_path,
        ai_egress_allowed=True,
        analysis_activation=active_activation,
    )
    try:
        client = TestClient(fixture.app)
        headers = fixture.mcp_client_headers()
        observations = client.get(
            f"/v1/sites/{fixture.site_id}/analysis-observations", headers=headers
        )
        listed = client.get(f"/v2/sites/{fixture.site_id}/analyses", headers=headers)
        created = client.post(
            f"/v2/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**headers, "Idempotency-Key": "mcp-six-route-allowlist"},
            json={
                "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                "current": fixture.current.model_dump(by_alias=True, mode="json"),
            },
        )
        assert created.status_code == 202, created.text
        analysis_id = created.json()["analysisId"]
        read_paths = (
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}",
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
        )
        reads = [client.get(path, headers=headers) for path in read_paths]
        coverage = client.get(
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/coverage",
            headers={**headers, "Range": "bytes=0-0"},
        )
        assert observations.status_code == 200
        assert listed.status_code == 200
        assert [response.status_code for response in reads] == [200, 200]
        assert coverage.status_code == 404
        assert coverage.json()["detail"] == "ANALYSIS_RESOURCE_NOT_FOUND"
        assert all(
            response.headers.get("X-KSI-External-AI-Egress") == "ALLOWED"
            for response in (observations, listed, created, *reads)
        )
    finally:
        fixture.close()

    with pytest.raises(AuthRegistryError):
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(b"device-mcp-token").hexdigest(),
                    principal=_client_principal(device_id="device-1"),
                )
            ]
        )
