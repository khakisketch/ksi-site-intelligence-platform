"""First-pilot Site/WorkArea write and ingress scope checks for mapped identities."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from analysis_api_local_fixture import LocalAnalysisApiFixture, build_local_analysis_api_fixture
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_event_contracts.site_frame import SiteFrame

_TOKEN_SITE_A = "write-scope-site-a"
_TOKEN_AREA_B = "write-scope-area-b"
_TOKEN_EMPTY = "write-scope-empty"
_TOKEN_OPAQUE = "write-scope-opaque"
_NOW = datetime(2026, 9, 29, tzinfo=UTC)


def _principal_token(
    token: str,
    principal_id: str,
    organization_id: str,
    *,
    sites: frozenset[str] | None,
    work_areas: frozenset[str] | None,
) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        principal=Principal(
            principal_id=principal_id,
            kind=PrincipalKind.OPERATOR,
            role=Role.ADMIN,
            device_id=None,
            organization_id=organization_id,
            allowed_site_ids=sites,
            allowed_work_area_ids=work_areas,
        ),
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _add_same_org_site_and_areas(fixture: LocalAnalysisApiFixture) -> tuple[str, str]:
    site = fixture.app.state.site_store.get_scoped(fixture.site_id, fixture.organization_id)
    assert site is not None
    frame = SiteFrame.model_validate(site.site_frame)
    assert (
        fixture.app.state.site_store.register(
            "site-b",
            "Second pilot site",
            frame,
            organization_id=fixture.organization_id,
            actor="setup",
            now=_NOW,
        ).record
        is not None
    )
    area_a = fixture.app.state.work_area_store.get(fixture.work_area_id)
    assert area_a is not None
    area_b_result = fixture.app.state.work_area_store.register(
        fixture.site_id,
        name="Second WorkArea",
        polygon=area_a.polygon,
        crs=area_a.crs,
        supersedes=None,
        now=_NOW,
        actor="setup",
    )
    assert area_b_result.work_area is not None
    area_b = fixture.app.state.work_area_store.register(
        "site-b",
        name="Second site WorkArea",
        polygon=area_a.polygon,
        crs=area_a.crs,
        supersedes=None,
        now=_NOW,
        actor="setup",
    )
    assert area_b.work_area is not None
    assert area_b_result.work_area.work_area_id == "wa-site-a-0002"
    assert area_b.work_area.work_area_id == "wa-site-b-0001"
    return area_b_result.work_area.work_area_id, area_b.work_area.work_area_id


def _install_auth(fixture: LocalAnalysisApiFixture, area_b: str) -> None:
    fixture.app.state.auth_registry = AuthRegistry(
        [
            _principal_token(
                _TOKEN_SITE_A,
                "mapped-site-a",
                fixture.organization_id,
                sites=frozenset({fixture.site_id}),
                work_areas=frozenset({fixture.work_area_id}),
            ),
            _principal_token(
                _TOKEN_AREA_B,
                "mapped-area-b",
                fixture.organization_id,
                sites=frozenset({fixture.site_id}),
                work_areas=frozenset({area_b}),
            ),
            _principal_token(
                _TOKEN_EMPTY,
                "mapped-empty",
                fixture.organization_id,
                sites=frozenset(),
                work_areas=frozenset(),
            ),
            _principal_token(
                _TOKEN_OPAQUE,
                "opaque-legacy",
                fixture.organization_id,
                sites=None,
                work_areas=None,
            ),
        ]
    )


def test_work_area_writes_require_site_and_existing_area_grants(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        area_b, _ = _add_same_org_site_and_areas(fixture)
        _install_auth(fixture, area_b)
        client = TestClient(fixture.app)
        body = {
            "name": "Unauthorized new area",
            "polygon": fixture.app.state.work_area_store.get(fixture.work_area_id).polygon,
            "crs": "EPSG:5186",
        }
        denied_site_create = client.post(
            "/v1/sites/site-b/work-areas", headers=_headers(_TOKEN_SITE_A), json=body
        )
        denied_supersede = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas",
            headers=_headers(_TOKEN_SITE_A),
            json={**body, "supersedes": area_b},
        )
        denied_archive = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{area_b}/archive",
            headers=_headers(_TOKEN_SITE_A),
        )
        empty_site_create = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas",
            headers=_headers(_TOKEN_EMPTY),
            json=body,
        )
        empty_archive = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/archive",
            headers=_headers(_TOKEN_EMPTY),
        )
        assert (
            denied_site_create.status_code,
            denied_supersede.status_code,
            denied_archive.status_code,
            empty_site_create.status_code,
            empty_archive.status_code,
        ) == (404, 404, 404, 404, 404)

        mapped_new_area = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas",
            headers=_headers(_TOKEN_SITE_A),
            json=body,
        )
        assert mapped_new_area.status_code == 201, mapped_new_area.text

        legacy_create = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas",
            headers=_headers(_TOKEN_OPAQUE),
            json=body,
        )
        assert legacy_create.status_code == 201, legacy_create.text
    finally:
        fixture.close()


def test_known_work_order_id_cannot_bypass_reconstruction_ingress_grants(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        area_b, _ = _add_same_org_site_and_areas(fixture)
        _install_auth(fixture, area_b)
        client = TestClient(fixture.app)
        work_order_id = fixture.baseline.work_order_id
        submission_ref = fixture.baseline.submission_ref
        revision = fixture.baseline.revision
        record = fixture._baseline_revision
        payload = record.submission.model_dump(by_alias=True, mode="json")
        work_orders = fixture.app.state.observation_work_order_store
        order = work_orders.get(work_order_id, organization_id=fixture.organization_id)
        assert order is not None
        work_orders._orders[work_order_id] = order.model_copy(
            update={"work_area_ids": [fixture.work_area_id, area_b]}
        )
        collection = (
            f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
        )
        revision_path = f"{collection}/{submission_ref}/revisions/{revision}"
        mapped = _headers(_TOKEN_AREA_B)

        responses = [
            client.get(
                f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-context",
                headers=mapped,
            ),
            client.post(collection, headers=mapped, json=payload),
            client.get(collection, headers=mapped),
            client.get(revision_path, headers=mapped),
            client.post(revision_path + "/upload-grants", headers=mapped),
            client.post(revision_path + "/seal", headers=mapped),
            client.get(
                f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-context",
                headers=_headers(_TOKEN_EMPTY),
            ),
        ]
        assert [response.status_code for response in responses] == [404] * len(responses)

        site_b_area = "wa-site-b-0001"
        site_b_order = client.post(
            "/v1/sites/site-b/observation-work-orders",
            headers={**_headers(_TOKEN_OPAQUE), "Idempotency-Key": "write-scope-site-b"},
            # P3 Task 5: the platform profile only creates work orders in
            # EXTERNAL_RECONSTRUCTION mode (direct managed creation is 422).
            json={
                "name": "Known order on Site B",
                "workAreaIds": [site_b_area],
                "executionMode": "EXTERNAL_RECONSTRUCTION",
            },
        )
        assert site_b_order.status_code == 201, site_b_order.text
        denied_site_context = client.get(
            "/v1/observation-work-orders/"
            f"{site_b_order.json()['workOrderId']}/external-reconstruction-context",
            headers=_headers(_TOKEN_SITE_A),
        )
        assert denied_site_context.status_code == 404
    finally:
        fixture.close()
