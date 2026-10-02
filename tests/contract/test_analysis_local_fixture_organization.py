"""Organization-scoped V2 DSM selector fixtures for local OIDC integration."""

from __future__ import annotations

from pathlib import Path

from analysis_api_local_fixture import build_local_analysis_api_fixture
from fastapi.testclient import TestClient
from ksi_core.identity.auth import HumanAuthMode
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig
from test_external_analysis_real_inspection_integration import (
    inspect_fixture_epochs_with_real_parser,
)
from test_local_oidc_issuer import _authorize_and_exchange
from test_local_oidc_issuer import _client as local_oidc_client


def test_org_local_pilot_lists_its_real_inspected_dsm_epochs_only(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        organization_id="org-local-pilot",
        v2_dsm_only=True,
        real_inspection=True,
    )
    inspection_root = tmp_path / "actual-inspection"
    inspection_root.mkdir()
    try:
        report_digests = inspect_fixture_epochs_with_real_parser(
            fixture,
            root=inspection_root,
        )
        assert len(report_digests) == 2
        assert all(
            subject.organization_id == "org-local-pilot"
            for subject in (fixture._baseline_subject, fixture._current_subject)
        )

        issuer_client, _issuer_module, secret = local_oidc_client(tmp_path)
        pilot_exchange = _authorize_and_exchange(
            issuer_client,
            secret,
            account="local-field-operator",
            verifier="p" * 43,
        )
        foreign_exchange = _authorize_and_exchange(
            issuer_client,
            secret,
            account="local-empty-org-admin",
            verifier="e" * 43,
        )
        pilot_payload = pilot_exchange["payload"]
        foreign_payload = foreign_exchange["payload"]
        assert isinstance(pilot_payload, dict)
        assert isinstance(foreign_payload, dict)
        pilot_token = pilot_payload["access_token"]
        foreign_token = foreign_payload["access_token"]
        assert isinstance(pilot_token, str)
        assert isinstance(foreign_token, str)
        verifier = OidcJwtVerifier(
            OidcVerifierConfig(
                issuer="http://127.0.0.1:9010",
                audience="ksi-core",
                jwks_url="http://127.0.0.1:9010/jwks.json",
            ),
            fetch_jwks=lambda: issuer_client.get("/jwks.json").json(),
            subject_registry=OidcSubjectRegistry.from_document(
                {
                    "version": "oidc-subject-registry.v1",
                    "subjects": [
                        {
                            "issuer": "http://127.0.0.1:9010",
                            "subject": "local-field-operator",
                            "principalId": "local-field-operator",
                            "organizationId": "org-local-pilot",
                            "role": "FIELD_OPERATOR",
                            "status": "ACTIVE",
                            "allowedSiteIds": ["site-a"],
                            "allowedWorkAreaIds": ["wa-site-a-0001"],
                        },
                        {
                            "issuer": "http://127.0.0.1:9010",
                            "subject": "local-empty-org-admin",
                            "principalId": "local-empty-org-admin",
                            "organizationId": "org-local-empty",
                            "role": "ADMIN",
                            "status": "ACTIVE",
                            "allowedSiteIds": [],
                            "allowedWorkAreaIds": [],
                        },
                    ],
                },
                expected_issuer="http://127.0.0.1:9010",
            ),
        )
        pilot_principal = verifier.verify(pilot_token)
        foreign_principal = verifier.verify(foreign_token)
        assert pilot_principal is not None
        assert foreign_principal is not None
        assert pilot_principal.principal_id == "local-field-operator"
        assert pilot_principal.organization_id == "org-local-pilot"
        assert foreign_principal.principal_id == "local-empty-org-admin"
        assert foreign_principal.organization_id == "org-local-empty"

        # The already assembled app stays intact; only this test switches the human
        # identity resolver to the real local issuer and its loopback JWKS.
        fixture.app.state.human_auth_mode = HumanAuthMode.OIDC
        fixture.app.state.oidc_verifier = verifier
        client = TestClient(fixture.app)
        path = f"/v1/sites/{fixture.site_id}/analysis-observations"
        listed = client.get(path, headers={"Authorization": f"Bearer {pilot_token}"})
        assert listed.status_code == 200, listed.text
        selectors_by_work_order = {
            item["selector"]["workOrderId"]: item["selector"]
            for item in listed.json()["items"]
        }
        assert selectors_by_work_order == {
            fixture.baseline.work_order_id: fixture.baseline.model_dump(
                by_alias=True, mode="json"
            ),
            fixture.current.work_order_id: fixture.current.model_dump(
                by_alias=True, mode="json"
            ),
        }

        foreign = client.get(path, headers={"Authorization": f"Bearer {foreign_token}"})
        assert foreign.status_code == 404
        assert client.get(path, headers=fixture.operator_headers()).status_code == 401
        assert client.get(
            "/v1/internal/analysis-jobs", headers=fixture.worker_headers()
        ).status_code == 200
    finally:
        fixture.close()
