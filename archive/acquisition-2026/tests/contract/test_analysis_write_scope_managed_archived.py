"""Archived managed-flow proof (P3 Task 5 relocation record, RB-08).

Relocated verbatim from
``tests/contract/test_analysis_write_scope.py::
test_weekly_work_orders_and_schedules_enforce_every_granted_area``: it creates
work orders in default (managed) mode and weekly observation schedules —
both retired with the managed assembly (platform creates work orders only in
EXTERNAL_RECONSTRUCTION mode and mounts no schedule routes). The staying
grant-enforcement coverage lives in the adapted
``test_known_work_order_id_cannot_bypass_reconstruction_ingress_grants`` in the
active file. This file is archive-internal (``archive/`` is not a pytest
testpath, import path, or workspace member) and is NOT executed.
"""


def test_weekly_work_orders_and_schedules_enforce_every_granted_area(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        area_b, site_b_area = _add_same_org_site_and_areas(fixture)
        _install_auth(fixture, area_b)
        client = TestClient(fixture.app)
        opaque = _headers(_TOKEN_OPAQUE)
        mapped = _headers(_TOKEN_SITE_A)

        work_order_body = {"name": "Second area order", "workAreaIds": [area_b]}
        order_b = client.post(
            f"/v1/sites/{fixture.site_id}/observation-work-orders",
            headers=opaque,
            json=work_order_body,
        )
        assert order_b.status_code == 201, order_b.text
        order_id = order_b.json()["workOrderId"]
        mixed_order = client.post(
            f"/v1/sites/{fixture.site_id}/observation-work-orders",
            headers=opaque,
            json={
                "name": "Mixed area order",
                "workAreaIds": [fixture.work_area_id, area_b],
            },
        )
        assert mixed_order.status_code == 201, mixed_order.text
        mixed_order_id = mixed_order.json()["workOrderId"]

        schedule_body = {
            "name": "Second area weekly schedule",
            "workAreaIds": [area_b],
            "intervalDays": 7,
            "timezone": "Asia/Seoul",
        }
        schedule_b = client.post(
            f"/v1/sites/{fixture.site_id}/observation-schedules",
            headers=opaque,
            json=schedule_body,
        )
        assert schedule_b.status_code == 201, schedule_b.text
        mixed_schedule = client.post(
            f"/v1/sites/{fixture.site_id}/observation-schedules",
            headers=opaque,
            json={
                "name": "Mixed area weekly schedule",
                "workAreaIds": [fixture.work_area_id, area_b],
                "intervalDays": 7,
                "timezone": "Asia/Seoul",
            },
        )
        assert mixed_schedule.status_code == 201, mixed_schedule.text

        denied_multi_area_order = client.post(
            f"/v1/sites/{fixture.site_id}/observation-work-orders",
            headers=mapped,
            json={"name": "Mixed grant order", "workAreaIds": [fixture.work_area_id, area_b]},
        )
        denied_site_order = client.post(
            "/v1/sites/site-b/observation-work-orders",
            headers=mapped,
            json={"name": "Unauthorized site order", "workAreaIds": [site_b_area]},
        )
        denied_multi_area_schedule = client.post(
            f"/v1/sites/{fixture.site_id}/observation-schedules",
            headers=mapped,
            json={**schedule_body, "workAreaIds": [fixture.work_area_id, area_b]},
        )
        denied_schedule_link = client.post(
            f"/v1/sites/{fixture.site_id}/observation-work-orders",
            headers=mapped,
            json={
                "name": "Order linked to inaccessible schedule",
                "workAreaIds": [fixture.work_area_id],
                "scheduleId": schedule_b.json()["scheduleId"],
            },
        )
        mapped_orders = client.get(
            f"/v1/sites/{fixture.site_id}/observation-work-orders", headers=mapped
        )
        mapped_schedules = client.get(
            f"/v1/sites/{fixture.site_id}/observation-schedules", headers=mapped
        )
        denied_site_orders = client.get("/v1/sites/site-b/observation-work-orders", headers=mapped)
        denied_site_schedules = client.get("/v1/sites/site-b/observation-schedules", headers=mapped)
        denied_global_site_filter = client.get(
            "/v1/observation-work-orders?siteId=site-b", headers=mapped
        )
        denied_known_order = client.get(f"/v1/observation-work-orders/{order_id}", headers=mapped)
        denied_mixed_order = client.get(
            f"/v1/observation-work-orders/{mixed_order_id}", headers=mapped
        )
        global_orders = client.get("/v1/observation-work-orders", headers=mapped)
        empty_order = client.post(
            f"/v1/sites/{fixture.site_id}/observation-work-orders",
            headers=_headers(_TOKEN_EMPTY),
            json={"name": "Empty-scope order", "workAreaIds": [fixture.work_area_id]},
        )
        empty_schedule = client.post(
            f"/v1/sites/{fixture.site_id}/observation-schedules",
            headers=_headers(_TOKEN_EMPTY),
            json={**schedule_body, "workAreaIds": [fixture.work_area_id]},
        )
        assert denied_multi_area_order.status_code == 404
        assert denied_site_order.status_code == 404
        assert denied_multi_area_schedule.status_code == 404
        assert denied_schedule_link.status_code == 404
        assert order_id not in {item["workOrderId"] for item in mapped_orders.json()["workOrders"]}
        assert all(
            item["siteId"] == fixture.site_id
            and set(item["workAreaIds"]).issubset({fixture.work_area_id})
            for item in global_orders.json()["workOrders"]
        )
        assert all(
            set(item["workAreaIds"]).issubset({fixture.work_area_id})
            for item in mapped_schedules.json()["schedules"]
        )
        assert (
            denied_site_orders.status_code,
            denied_site_schedules.status_code,
            denied_global_site_filter.status_code,
            denied_known_order.status_code,
            denied_mixed_order.status_code,
            empty_schedule.status_code,
            empty_order.status_code,
        ) == (404, 404, 404, 404, 404, 404, 404)

        assert site_b_area
        assert (
            client.get(
                f"/v1/sites/{fixture.site_id}/observation-work-orders", headers=opaque
            ).status_code
            == 200
        )
    finally:
        fixture.close()