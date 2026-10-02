"""HTTP resource-scope checks for explicitly mapped OIDC principals."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from analysis_api_local_fixture import LocalAnalysisApiFixture, build_local_analysis_api_fixture
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_mission_contracts.models import SiteFrame

_MAPPED_TOKEN = "analysis-resource-scope-mapped"
_OTHER_AREA_TOKEN = "analysis-resource-scope-other-area"
_EMPTY_TOKEN = "analysis-resource-scope-empty"
_CROSS_ORG_TOKEN = "analysis-resource-scope-cross-org"
_OPAQUE_TOKEN = "analysis-resource-scope-opaque"
_OTHER_AREA_ID = "wa-site-a-0002"
_FOREIGN_SITE_ID = "site-foreign-org"
_FOREIGN_AREA_ID = "wa-site-foreign-org-0001"
_NOW = datetime(2026, 9, 28, tzinfo=UTC)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _install_test_identities(fixture: LocalAnalysisApiFixture) -> None:
    fixture.app.state.auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_MAPPED_TOKEN),
                principal=Principal(
                    principal_id="mapped-site-a",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                    organization_id=fixture.organization_id,
                    allowed_site_ids=frozenset({fixture.site_id}),
                    allowed_work_area_ids=frozenset({fixture.work_area_id}),
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OTHER_AREA_TOKEN),
                principal=Principal(
                    principal_id="mapped-other-area",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                    organization_id=fixture.organization_id,
                    allowed_site_ids=frozenset({fixture.site_id}),
                    allowed_work_area_ids=frozenset({_OTHER_AREA_ID}),
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_EMPTY_TOKEN),
                principal=Principal(
                    principal_id="mapped-empty-scope",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                    organization_id=fixture.organization_id,
                    allowed_site_ids=frozenset(),
                    allowed_work_area_ids=frozenset(),
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_CROSS_ORG_TOKEN),
                principal=Principal(
                    principal_id="mapped-cross-org-error",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                    organization_id=fixture.organization_id,
                    allowed_site_ids=frozenset({_FOREIGN_SITE_ID}),
                    allowed_work_area_ids=frozenset({_FOREIGN_AREA_ID}),
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OPAQUE_TOKEN),
                principal=Principal(
                    principal_id="opaque-legacy",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                    organization_id=fixture.organization_id,
                ),
            ),
        ]
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_analysis_routes_apply_explicit_site_and_work_area_grants(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=True)
    try:
        _install_test_identities(fixture)
        client = TestClient(fixture.app)
        site = fixture.app.state.site_store.get_scoped(
            fixture.site_id, fixture.organization_id
        )
        assert site is not None
        frame = SiteFrame.model_validate(site.site_frame)
        other_site_id = "site-b"
        assert fixture.app.state.site_store.register(
            other_site_id,
            "Other site",
            frame,
            organization_id=fixture.organization_id,
            ai_egress_allowed=True,
            actor="opaque-legacy",
            now=_NOW,
        ).record is not None

        area = fixture.app.state.work_area_store.get(fixture.work_area_id)
        assert area is not None
        other_area = fixture.app.state.work_area_store.register(
            fixture.site_id,
            name="Other area",
            polygon=area.polygon,
            crs=area.crs,
            supersedes=None,
            now=_NOW,
            actor="opaque-legacy",
        )
        assert other_area.work_area is not None
        assert fixture.app.state.site_store.register(
            _FOREIGN_SITE_ID,
            "Foreign organization site",
            frame,
            organization_id="org-unrelated",
            actor="foreign-admin",
            now=_NOW,
        ).record is not None
        foreign_area = fixture.app.state.work_area_store.register(
            _FOREIGN_SITE_ID,
            name="Foreign organization area",
            polygon=area.polygon,
            crs=area.crs,
            supersedes=None,
            now=_NOW,
            actor="foreign-admin",
        )
        assert foreign_area.work_area is not None
        assert foreign_area.work_area.work_area_id == _FOREIGN_AREA_ID
        assert other_area.work_area.work_area_id == _OTHER_AREA_ID

        # The existing fixture selector order is modeled as a valid multi-area
        # WorkOrder so this mapped principal owns the target area but not every
        # area included by either persisted selector.
        work_orders = fixture.app.state.observation_work_order_store
        selector_order = work_orders.get(
            fixture.baseline.work_order_id, organization_id=fixture.organization_id
        )
        assert selector_order is not None
        work_orders._orders[selector_order.work_order_id] = selector_order.model_copy(
            update={"work_area_ids": [fixture.work_area_id, _OTHER_AREA_ID]}
        )

        body = {
            "baseline": fixture.baseline.model_dump(by_alias=True),
            "current": fixture.current.model_dump(by_alias=True),
        }
        opaque = _headers(_OPAQUE_TOKEN)
        mapped = _headers(_MAPPED_TOKEN)
        calculations = fixture.app.state.external_analysis_wiring.facade._calculations
        issue = calculations.issue

        def fail_before_nx_append(**kwargs: object) -> object:
            del kwargs
            raise RuntimeError("simulated interruption before NX append")

        calculations.issue = fail_before_nx_append
        with pytest.raises(RuntimeError, match="simulated interruption before NX append"):
            client.post(
                f"/v1/sites/{fixture.site_id}/work-areas/{other_area.work_area.work_area_id}/analyses",
                headers={**opaque, "Idempotency-Key": "opaque-second-area"},
                json=body,
            )
        calculations.issue = issue
        pending_intents = fixture.app.state.external_analysis_wiring.intents.list(
            organization_id=fixture.organization_id, site_id=fixture.site_id
        )
        assert len(pending_intents) == 1
        hidden_analysis_id = pending_intents[0].analysis_id

        # Target WorkArea B is granted, but each selector's WorkOrder includes
        # ungranted WorkArea A. Retry and all historical reads must remain hidden.
        scoped_retry = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{_OTHER_AREA_ID}/analyses",
            headers={
                **_headers(_OTHER_AREA_TOKEN),
                "Idempotency-Key": "opaque-second-area",
            },
            json=body,
        )
        scoped_list = client.get(
            f"/v1/sites/{fixture.site_id}/analyses", headers=_headers(_OTHER_AREA_TOKEN)
        )
        scoped_reads = [
            client.get(
                f"/v1/sites/{fixture.site_id}/analyses/{hidden_analysis_id}{suffix}",
                headers=_headers(_OTHER_AREA_TOKEN),
            ).status_code
            for suffix in ("", "/result", "/evidence")
        ]
        assert (
            scoped_retry.status_code,
            [item["analysisId"] for item in scoped_list.json()["items"]],
            scoped_reads,
            calculations.get_history(hidden_analysis_id, organization_id=fixture.organization_id),
        ) == (404, [], [404, 404, 404], None)

        assert client.get(
            f"/v1/sites/{other_site_id}/analysis-observations", headers=mapped
        ).status_code == 404
        assert client.get(
            f"/v1/sites/{other_site_id}/analyses", headers=mapped
        ).status_code == 404
        assert client.get(
            f"/v1/sites/{other_site_id}/analyses",
            headers={**mapped, "X-KSI-Access-Purpose": "EXTERNAL_AI"},
        ).status_code == 404
        assert client.get(f"/v1/sites/{fixture.site_id}/analyses", headers=mapped).json()[
            "items"
        ] == []
        for suffix in ("", "/result", "/evidence"):
            response = client.get(
                f"/v1/sites/{fixture.site_id}/analyses/{hidden_analysis_id}{suffix}",
                headers=mapped,
            )
            assert response.status_code == 404, (suffix, response.text)

        denied_create = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{other_area.work_area.work_area_id}/analyses",
            headers={**mapped, "Idempotency-Key": "mapped-second-area"},
            json=body,
        )
        assert denied_create.status_code == 404, denied_create.text
        selector_scope_denied = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{_OTHER_AREA_ID}/analyses",
            headers={
                **_headers(_OTHER_AREA_TOKEN),
                "Idempotency-Key": "mapped-selectors-outside-grant",
            },
            json=body,
        )
        assert selector_scope_denied.status_code == 404, selector_scope_denied.text
        inaccessible_options = client.get(
            f"/v1/sites/{fixture.site_id}/analysis-observations",
            headers=_headers(_OTHER_AREA_TOKEN),
        )
        assert inaccessible_options.status_code == 200, inaccessible_options.text
        assert inaccessible_options.json()["items"] == []
        operator_ai_header = client.get(
            f"/v1/sites/{fixture.site_id}/analysis-observations",
            headers={**mapped, "X-KSI-Access-Purpose": "EXTERNAL_AI"},
        )
        assert operator_ai_header.status_code == 200
        assert "X-KSI-External-AI-Egress" not in operator_ai_header.headers
        empty = _headers(_EMPTY_TOKEN)
        assert client.get("/v1/sites", headers=empty).json()["sites"] == []
        assert client.get(f"/v1/sites/{fixture.site_id}", headers=empty).status_code == 404
        assert client.get(
            f"/v1/sites/{fixture.site_id}/work-areas", headers=empty
        ).status_code == 404
        assert client.get(
            f"/v1/sites/{fixture.site_id}/analyses", headers=empty
        ).status_code == 404
        assert [
            item["siteId"] for item in client.get("/v1/sites", headers=mapped).json()["sites"]
        ] == [fixture.site_id]
        assert client.get(f"/v1/sites/{other_site_id}", headers=mapped).status_code == 404
        assert client.get(
            f"/v1/sites/{_FOREIGN_SITE_ID}/work-areas", headers=_headers(_CROSS_ORG_TOKEN)
        ).status_code == 404
    finally:
        fixture.close()


def test_site_and_work_area_lists_filter_explicit_grants_but_keep_opaque_behavior(
    tmp_path: Path,
) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        _install_test_identities(fixture)
        client = TestClient(fixture.app)
        site = fixture.app.state.site_store.get_scoped(
            fixture.site_id, fixture.organization_id
        )
        assert site is not None
        frame = SiteFrame.model_validate(site.site_frame)
        other_site_id = "site-b"
        assert fixture.app.state.site_store.register(
            other_site_id,
            "Other site",
            frame,
            organization_id=fixture.organization_id,
            actor="opaque-legacy",
            now=_NOW,
        ).record is not None
        area = fixture.app.state.work_area_store.get(fixture.work_area_id)
        assert area is not None
        other_area = fixture.app.state.work_area_store.register(
            fixture.site_id,
            name="Other area",
            polygon=area.polygon,
            crs=area.crs,
            supersedes=None,
            now=_NOW,
            actor="opaque-legacy",
        )
        assert other_area.work_area is not None

        mapped_sites = client.get("/v1/sites", headers=_headers(_MAPPED_TOKEN))
        assert mapped_sites.status_code == 200
        assert [item["siteId"] for item in mapped_sites.json()["sites"]] == [fixture.site_id]
        mapped_areas = client.get(
            f"/v1/sites/{fixture.site_id}/work-areas", headers=_headers(_MAPPED_TOKEN)
        )
        assert mapped_areas.status_code == 200
        assert [item["workAreaId"] for item in mapped_areas.json()["workAreas"]] == [
            fixture.work_area_id
        ]
        assert client.get(
            f"/v1/sites/{other_site_id}/work-areas", headers=_headers(_MAPPED_TOKEN)
        ).status_code == 404
        opaque_sites = client.get("/v1/sites", headers=_headers(_OPAQUE_TOKEN))
        assert [item["siteId"] for item in opaque_sites.json()["sites"]] == [
            fixture.site_id,
            other_site_id,
        ]
        opaque_areas = client.get(
            f"/v1/sites/{fixture.site_id}/work-areas", headers=_headers(_OPAQUE_TOKEN)
        )
        assert [item["workAreaId"] for item in opaque_areas.json()["workAreas"]] == [
            fixture.work_area_id,
            other_area.work_area.work_area_id,
        ]
    finally:
        fixture.close()
