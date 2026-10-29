"""An empty visible list does not establish that an organization has no sites."""

from pathlib import Path

from analysis_api_local_fixture import build_local_analysis_api_fixture
from fastapi.testclient import TestClient
from test_oidc_route_scope import _install_oidc_v2


def test_explicit_scope_can_hide_an_existing_site_from_the_list(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        assert fixture.app.state.site_store.get_scoped(fixture.site_id, fixture.organization_id)
        token, _key = _install_oidc_v2(
            fixture,
            capabilities=[],
            site_ids=["site-not-granted-to-this-principal"],
            area_ids=None,
        )
        client = TestClient(fixture.app)
        headers = {"Authorization": f"Bearer {token}"}

        visible = client.get("/v1/sites", headers=headers)
        assert visible.status_code == 200
        assert visible.json()["sites"] == []
        assert client.get(f"/v1/sites/{fixture.site_id}", headers=headers).status_code == 404

        # With an organization-wide scope the same existing site is visible;
        # neither fixture identity nor the UI should infer this from an empty list.
        token, _key = _install_oidc_v2(
            fixture, capabilities=[], site_ids=None, area_ids=None
        )
        authorized = client.get("/v1/sites", headers={"Authorization": f"Bearer {token}"})
        assert authorized.status_code == 200
        assert fixture.site_id in {site["siteId"] for site in authorized.json()["sites"]}
    finally:
        fixture.close()
