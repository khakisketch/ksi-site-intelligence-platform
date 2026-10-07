"""Task5 RED: genuine end-to-end parity over real loopback HTTP + official SDK stdio.

Every test composes the real Core app (genuine generated TIFF inspection,
real journals/authority/grants, actual AI egress/discovery routers), a
separately started worker, official SDK stdio calls, and a separate
HTTP-only consumer. No model-only doubles, no mocked success bodies.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
import spatial_data_mcp_fixture as fixture

fixture.ensure_source_path()

ACK = "X-KSI-Spatial-Data-AI-Egress"
SDK_TOOLS = (
    "ksi_list_spatial_data_assets",
    "ksi_get_spatial_data_asset",
    "ksi_create_spatial_data_request",
    "ksi_list_spatial_data_requests",
    "ksi_get_spatial_data_request",
    "ksi_cancel_spatial_data_request",
)


def _sdk_config(lane: Any, name: str) -> Path:
    return fixture.task5_sdk_config(lane.origin, name=name)


def _expected_oracle(lane: Any, asset: str = "primary") -> dict[str, Any]:
    """Hand-derived expectation from the KNOWN 10x10 fixture grid (pre-worker).

    Grid constants (fixture writers): west origin 100.0, north origin 200.0,
    pixel size 2.0. Request bounds (102.1, 183.9, 108.1, 193.9) select, by
    half-open floor/ceil cell coverage:
      c0 = floor((102.1-100)/2) = floor(1.05) = 1
      c1 =  ceil((108.1-100)/2) =  ceil(4.05) = 5
      r0 = floor((200-193.9)/2) = floor(3.05) = 3
      r1 =  ceil((200-183.9)/2) =  ceil(8.05) = 9
    so pixel_window [1, 5, 3, 9], actual bounds west/north-anchored
    (102.0, 182.0, 110.0, 194.0), window transform
    (2.0, 0.0, 102.0, 0.0, -2.0, 194.0). Deliberately NOT computed with the
    production geometry helper under test; the literal tripwire below plus
    the receipt comparisons genuinely validate that helper instead. Only the
    genuine source file itself is read (rasterio slice + mask).
    """
    import math

    import rasterio

    origin_west, origin_north, pixel = 100.0, 200.0, 2.0
    west, south, east, north = (float(v) for v in fixture.TASK5_REQUEST_BOUNDS)
    c0 = math.floor((west - origin_west) / pixel)
    c1 = math.ceil((east - origin_west) / pixel)
    r0 = math.floor((origin_north - north) / pixel)
    r1 = math.ceil((origin_north - south) / pixel)
    assert [c0, c1, r0, r1] == [1, 5, 3, 9]
    actual_bounds = [
        origin_west + c0 * pixel,
        origin_north - r1 * pixel,
        origin_west + c1 * pixel,
        origin_north - r0 * pixel,
    ]
    transform = [pixel, 0.0, actual_bounds[0], 0.0, -pixel, actual_bounds[3]]
    entry = lane.assets[asset]
    source_path = entry.get("source_path", lane.source_path)
    with rasterio.open(source_path) as original:
        array = original.read()[:, r0:r1, c0:c1].copy()
        mask = original.dataset_mask()[r0:r1, c0:c1].copy()
        crs, nodata = original.crs, original.nodata
    return {
        "array": array,
        "mask": mask,
        "pixel_window": [c0, c1, r0, r1],
        "actual_bounds": actual_bounds,
        "transform": transform,
        "crs": crs,
        "nodata": nodata,
    }


def _check_oracle(
    lane: Any, status: dict[str, Any], downloaded: Path, asset: str = "primary"
) -> None:
    import numpy as np
    import rasterio

    expected = _expected_oracle(lane, asset)
    receipt = status["receipt"]
    assert list(receipt["pixelWindow"]) == expected["pixel_window"]
    assert list(receipt["actualBounds"]) == expected["actual_bounds"]
    assert list(receipt["transform"]) == expected["transform"]
    assert downloaded.stat().st_size == receipt["outputSizeBytes"]
    assert "sha256:" + sha256(downloaded.read_bytes()).hexdigest() == receipt["outputSha256"]
    with rasterio.open(downloaded) as output:
        np.testing.assert_array_equal(output.read(), expected["array"])
        np.testing.assert_array_equal(output.dataset_mask(), expected["mask"])
        assert tuple(output.transform)[:6] == tuple(expected["transform"])
        assert tuple(output.bounds) == tuple(expected["actual_bounds"])
        assert output.crs == expected["crs"] and output.nodata == expected["nodata"]
        assert "PRODUCER_NOTE" not in output.tags()
        assert int(np.count_nonzero(output.dataset_mask())) == receipt["validPixelCount"]


def _assert_no_raster_bytes(payload: Any) -> None:
    """SDK results carry IDs/digests/references only — never raster payloads or links."""
    forbidden = {
        "bytes",
        "base64",
        "blob",
        "data",
        "dataUrl",
        "content",
        "downloadUrl",
        "uploadUrl",
        "storageKey",
        "objectKey",
        "sourceUrl",
    }

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                assert key not in forbidden, key
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            assert len(value.encode()) <= 4096, "oversized string value in SDK result"

    walk(payload)


@pytest.mark.parametrize("kind", ["dsm", "rgb", "rgba"])
def test_sdk_discovery_prepare_receipt_http_consumer_parity(tmp_path: Path, kind: str) -> None:
    import asyncio

    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    with fixture.task5_ai_lane(tmp_path, kind=kind) as lane:
        oracle = _expected_oracle(lane)
        assert oracle["pixel_window"] == [1, 5, 3, 9]
        config = _sdk_config(lane, f"parity-{kind}")

        async def exercise() -> dict[str, Any]:
            async with (
                stdio_client(fixture.task5_sdk_parameters(config)) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                listed = await session.call_tool(
                    "ksi_list_spatial_data_assets",
                    {"siteId": "site-1", "workAreaId": lane.area_id, "limit": 2},
                )
                assert listed.is_error is not True and listed.structured_content is not None
                page = listed.structured_content
                refs = [item["assetRef"] for item in page["items"]]
                assert refs == [lane.assets["primary"]["asset_ref"]]
                detail = await session.call_tool(
                    "ksi_get_spatial_data_asset",
                    {
                        "siteId": "site-1",
                        "workAreaId": lane.area_id,
                        "assetRef": refs[0],
                    },
                )
                assert detail.is_error is not True and detail.structured_content is not None
                asset = detail.structured_content
                assert asset["observedCrsDigest"] == lane.assets["primary"]["observed_crs_digest"]
                created = await session.call_tool(
                    "ksi_create_spatial_data_request",
                    {
                        "siteId": "site-1",
                        "workAreaId": lane.area_id,
                        "assetRef": refs[0],
                        "requestedBounds": list(fixture.TASK5_REQUEST_BOUNDS),
                        "observedCrsDigest": asset["observedCrsDigest"],
                        "idempotencyKey": f"parity-{kind}",
                    },
                )
                assert created.is_error is not True and created.structured_content is not None
                return {
                    "job": created.structured_content,
                    "call": (session, refs[0]),
                }

        sdk = asyncio.run(exercise())
        job_id = sdk["job"]["jobId"]
        status = lane.run_worker(job_id)
        assert status["executionState"] == "COMPLETED"

        async def fetch() -> dict[str, Any]:
            async with (
                stdio_client(fixture.task5_sdk_parameters(config)) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                gotten = await session.call_tool(
                    "ksi_get_spatial_data_request",
                    {"siteId": "site-1", "workAreaId": lane.area_id, "jobId": job_id},
                )
                assert gotten.is_error is not True and gotten.structured_content is not None
                return gotten.structured_content

        view = asyncio.run(fetch())
        assert view["job"] == status
        reference = view["fileReference"]
        assert reference is not None
        assert reference["referenceVersion"] == "spatial-data-file-reference.v1"
        assert reference["method"] == "GET" and reference["authenticationRequired"] is True
        assert reference["rangeSupported"] is False
        assert reference["relativePath"] == lane.file_url(status)
        assert reference["outputSha256"] == status["receipt"]["outputSha256"]
        assert reference["outputSizeBytes"] == status["receipt"]["outputSizeBytes"]
        _assert_no_raster_bytes(view)
        _assert_no_raster_bytes(sdk["job"])
        downloaded = lane.consumer.download(status=status, output_dir=tmp_path / "consumer")
        assert downloaded.name == job_id + ".tif"
        _check_oracle(lane, status, downloaded)
        assert lane.provider.uploads == 1
        assert list(lane.workspace.iterdir()) == []


def test_rgba_ingress_reports_four_band_alpha_facts(tmp_path: Path) -> None:
    """Genuine inspector facts for the canonical RGBA (complements full parity).

    This test asserts MEASURED ingress facts only — 4-band/uint8/source
    affine/CRS/MASK representation — and performs no issuance. Byte-delivery
    parity itself is proven by the rgba case of
    test_sdk_discovery_prepare_receipt_http_consumer_parity (no metadata-only
    substitution; see task-5-report.md label correction).
    """
    with fixture.task5_ai_lane(tmp_path, kind="rgba") as lane:
        measurements = lane.assets["primary"]["measurements"]
        assert measurements.band_count == 4
        assert measurements.dtype == "uint8"
        assert tuple(measurements.transform) == (2.0, 0.0, 100.0, 0.0, -2.0, 200.0)
        assert measurements.observed_crs_identifier == "EPSG:3857"
        assert measurements.observed_crs_digest == lane.assets["primary"]["observed_crs_digest"]
        assert measurements.nodata_representation.value == "MASK"
        assert measurements.nodata_value is None
        assert measurements.width == 10 and measurements.height == 10


def test_restart_preserves_job_and_rejects_changed_body(tmp_path: Path) -> None:
    """Same body+key returns the same ID after participant restart; changed body 409s."""
    import asyncio

    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    with fixture.task5_ai_lane(tmp_path, kind="dsm") as lane:
        status = lane.request_and_run(key="restart-1")
        job_id = status["jobId"]
        before = lane.consumer.download(status=status, output_dir=tmp_path / "before").read_bytes()
        assert lane.provider.uploads == 1
        lane.restart()
        assert lane.origin is not None
        # Consent is journaled only at site registration (Core has no durable
        # post-registration consent setter); the restart genuinely reopens it as
        # denied, and the operator re-affirmation below is the explicit act.
        lane.set_consent(True)
        repeated = lane.consumer.issue(request=lane.request_body(), idempotency_key="restart-1")
        assert repeated["jobId"] == job_id
        again = lane.consumer.status(job_id)
        assert again["receipt"] == status["receipt"]
        assert again["executionState"] == "COMPLETED"
        after = lane.consumer.download(status=again, output_dir=tmp_path / "after").read_bytes()
        assert after == before and lane.provider.uploads == 1

        altered = dict(lane.request_body())
        altered["requestedBounds"] = [103.0, 184.0, 107.0, 192.0]
        try:
            lane.consumer.issue(request=altered, idempotency_key="restart-1")
        except Exception as exc:  # noqa: BLE001  (closed NativeWindowClientError reason below)
            assert getattr(exc, "reason", "") == "IDEMPOTENCY_CONFLICT"
        else:
            raise AssertionError("changed body with same key must conflict")

        config = _sdk_config(lane, "restart")
        lane.provider.source = lane.source_bytes

        async def exercise() -> None:
            async with (
                stdio_client(fixture.task5_sdk_parameters(config)) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                same = await session.call_tool(
                    "ksi_create_spatial_data_request",
                    {
                        "siteId": "site-1",
                        "workAreaId": lane.area_id,
                        "assetRef": lane.assets["primary"]["asset_ref"],
                        "requestedBounds": list(fixture.TASK5_REQUEST_BOUNDS),
                        "observedCrsDigest": lane.assets["primary"]["observed_crs_digest"],
                        "idempotencyKey": "restart-1",
                    },
                )
                assert same.is_error is not True and same.structured_content is not None
                assert same.structured_content["jobId"] == job_id
                changed = await session.call_tool(
                    "ksi_create_spatial_data_request",
                    {
                        "siteId": "site-1",
                        "workAreaId": lane.area_id,
                        "assetRef": lane.assets["primary"]["asset_ref"],
                        "requestedBounds": [103.0, 184.0, 107.0, 192.0],
                        "observedCrsDigest": lane.assets["primary"]["observed_crs_digest"],
                        "idempotencyKey": "restart-1",
                    },
                )
                assert changed.is_error is True
                assert changed.structured_content["code"] == "IDEMPOTENCY_CONFLICT"

        asyncio.run(exercise())


def test_next_observation_gets_new_source_and_result(tmp_path: Path) -> None:
    """A new epoch binds a new asset/source/job/receipt; history is never substituted."""
    with fixture.task5_ai_lane(tmp_path, kind="dsm") as lane:
        first = lane.request_and_run(key="epoch-1")
        assert first["executionState"] == "COMPLETED"
        second_info = lane.advance_observation()
        assert second_info["asset_ref"] != lane.assets["primary"]["asset_ref"]
        assert lane.assets["epoch2"]["epoch_id"] != lane.assets["primary"]["epoch_id"]
        import httpx

        probe = httpx.Client(
            base_url=lane.origin,
            headers={"Authorization": "Bearer " + fixture.TASK5_AI_TOKEN},
            timeout=10,
            trust_env=False,
        )
        try:
            page = probe.get(lane.asset_base, params={"limit": 2})
            assert page.status_code == 200
            refs = sorted(item["assetRef"] for item in page.json()["items"])
            assert refs == sorted(
                [lane.assets["primary"]["asset_ref"], lane.assets["epoch2"]["asset_ref"]]
            )
            assert page.headers.get(ACK) == "ALLOWED"
        finally:
            probe.close()
        second = lane.request_and_run(key="epoch-2", asset="epoch2")
        assert second["executionState"] == "COMPLETED"
        assert second["jobId"] != first["jobId"]
        assert second["receipt"] != first["receipt"]
        assert second["receipt"]["outputSha256"] != first["receipt"]["outputSha256"]
        assert second["receipt"]["sourceSha256"] != first["receipt"]["sourceSha256"]
        assert second["assetRef"] == lane.assets["epoch2"]["asset_ref"]
        retained = lane.consumer.status(first["jobId"])
        assert retained["receipt"] == first["receipt"]
        assert retained["executionState"] == "COMPLETED"
        downloaded = lane.consumer.download(status=second, output_dir=tmp_path / "epoch2")
        _check_oracle(lane, second, downloaded, asset="epoch2")


def _raw_client(lane: Any, token: str = fixture.TASK5_AI_TOKEN) -> Any:
    import httpx

    return httpx.Client(
        base_url=lane.origin,
        headers={"Authorization": "Bearer " + token},
        timeout=10,
        trust_env=False,
    )


def _denied(response: Any, *, status: int, reason: str | None) -> None:
    assert response.status_code == status
    if reason is not None:
        assert response.json()["reason"] == reason
    assert response.headers.get(ACK) is None


def test_rights_negative_matrix_closes_all_http_pairs_and_sdk_tools(tmp_path: Path) -> None:
    """Consent/grant matrix over real loopback HTTP + official SDK stdio.

    Eight route-method pairs fail closed on consent revoke (restored after
    each), six SDK tools fail closed on grant revoke (lists filter to empty
    pages, details deny), and expiry/replacement/READ-only/ambiguity/foreign/
    scope/purpose cases deny without ack, bytes, or mutation. Work-order
    confusion has no route on this surface (site/work-area scoped); the
    foreign-org + wrong-site + wrong-area cases cover the scope class.
    """
    import asyncio

    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    lane_root = tmp_path / "matrix"
    lane_root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(lane_root, kind="dsm") as lane:
        base = lane.request_and_run(key="matrix-base")
        assert base["executionState"] == "COMPLETED"
        job_id = base["jobId"]
        asset_ref = lane.assets["primary"]["asset_ref"]
        client = _raw_client(lane)
        try:
            control = client.get(lane.base + "/" + job_id)
            assert control.status_code == 200 and control.headers.get(ACK) == "ALLOWED"

            cancel_target = lane.consumer.issue(
                request=lane.request_body(), idempotency_key="matrix-cancel"
            )
            assert cancel_target["executionState"] == "QUEUED"
            pairs: list[tuple[str, str, dict[str, Any]]] = [
                ("GET", lane.asset_base, {"params": {"limit": 2}}),
                ("GET", lane.asset_base + "/" + asset_ref, {}),
                ("POST", lane.base, {"json": None, "key": "matrix-pair"}),
                ("GET", lane.base, {"params": {"limit": 2}}),
                ("GET", lane.base + "/" + job_id, {}),
                ("POST", lane.base + "/" + cancel_target["jobId"] + "/cancel", {}),
                ("GET", lane.file_url(base), {}),
                ("HEAD", lane.file_url(base), {}),
            ]
            for index, (method, path, options) in enumerate(pairs):
                options = dict(options)
                extra = options.pop("key", None)
                if extra is not None:
                    options["json"] = lane.request_body()
                    options["headers"] = {"Idempotency-Key": f"{extra}-{index}"}
                lane.set_consent(False)
                try:
                    denied = client.request(method, path, **options)
                    _denied(
                        denied,
                        status=403,
                        reason=None if method == "HEAD" else "AI_EGRESS_DENIED",
                    )
                finally:
                    lane.set_consent(True)
                if method != "HEAD":
                    _assert_no_raster_bytes(denied.json())
            assert lane.consumer.status(cancel_target["jobId"])["executionState"] == "QUEUED"
            canceled = client.post(lane.base + "/" + cancel_target["jobId"] + "/cancel")
            assert canceled.status_code == 200 and canceled.headers.get(ACK) == "ALLOWED"
            assert lane.consumer.status(cancel_target["jobId"])["executionState"] == "CANCELED"

            downgraded = dict(lane.request_body())
            downgraded["purpose"] = "GENERAL_DATA_USE"
            refused = client.post(
                lane.base, json=downgraded, headers={"Idempotency-Key": "matrix-downgrade"}
            )
            _denied(refused, status=403, reason="PERMISSION_DENIED")
            _assert_no_raster_bytes(refused.json())

            foreign = _raw_client(lane, token=fixture.TASK5_FOREIGN_TOKEN)
            try:
                _denied(foreign.get(lane.base + "/" + job_id), status=404, reason="NOT_FOUND")
                foreign_file = foreign.get(lane.file_url(base))
                assert foreign_file.status_code == 404
                assert foreign_file.headers.get(ACK) is None
            finally:
                foreign.close()
            wrong_site = lane.base.replace("site-1", "site-9")
            missing = client.get(wrong_site + "/" + job_id)
            assert missing.status_code == 404 and missing.headers.get(ACK) is None
            wrong_area = lane.base.replace(lane.area_id, "area-9")
            missing_area = client.get(wrong_area + "/" + job_id)
            assert missing_area.status_code == 404 and missing_area.headers.get(ACK) is None

            outdir = tmp_path / "matrix-denied-bytes"
            outdir.mkdir(mode=0o700)
            lane.set_consent(False)
            try:
                with pytest.raises(RuntimeError, match="INVALID_FILE_RESPONSE"):
                    lane.consumer.download(status=base, output_dir=outdir)
                assert [path for path in outdir.iterdir() if path.suffix == ".tif"] == []
            finally:
                lane.set_consent(True)
        finally:
            client.close()

    grant_root = tmp_path / "grant"
    grant_root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(grant_root, kind="dsm") as lane:
        asset_ref = lane.assets["primary"]["asset_ref"]
        old = lane.request_and_run(key="grant-old")
        assert old["executionState"] == "COMPLETED"
        lane.revoke_grant()
        config = _sdk_config(lane, "matrix-revoked")

        async def revoked_tools() -> dict[str, Any]:
            results: dict[str, Any] = {}
            async with (
                stdio_client(fixture.task5_sdk_parameters(config)) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                calls = [
                    ("ksi_list_spatial_data_assets", {"limit": 2}),
                    ("ksi_get_spatial_data_asset", {"assetRef": asset_ref}),
                    (
                        "ksi_create_spatial_data_request",
                        {
                            "assetRef": asset_ref,
                            "requestedBounds": list(fixture.TASK5_REQUEST_BOUNDS),
                            "observedCrsDigest": lane.assets["primary"]["observed_crs_digest"],
                            "idempotencyKey": "matrix-revoked",
                        },
                    ),
                    ("ksi_list_spatial_data_requests", {"limit": 2}),
                    ("ksi_get_spatial_data_request", {"jobId": old["jobId"]}),
                    ("ksi_cancel_spatial_data_request", {"jobId": old["jobId"]}),
                ]
                for tool, extra in calls:
                    args: dict[str, Any] = {"siteId": "site-1", "workAreaId": lane.area_id}
                    args.update(extra)
                    result = await session.call_tool(tool, args)
                    content = result.structured_content
                    results[tool] = (result.is_error, content)
                    if result.is_error is not True:
                        assert content is not None
                        _assert_no_raster_bytes(content)
            return results

        verdicts = asyncio.run(revoked_tools())
        assert verdicts["ksi_list_spatial_data_assets"][0] is not True
        assert verdicts["ksi_list_spatial_data_assets"][1]["items"] == []
        assert verdicts["ksi_list_spatial_data_requests"][0] is not True
        assert verdicts["ksi_list_spatial_data_requests"][1]["items"] == []
        assert verdicts["ksi_get_spatial_data_asset"][0] is True
        assert verdicts["ksi_get_spatial_data_asset"][1]["code"] == "NOT_FOUND"
        assert verdicts["ksi_create_spatial_data_request"][0] is True
        assert verdicts["ksi_create_spatial_data_request"][1]["code"] == "GRANT_REQUIRED"
        assert verdicts["ksi_get_spatial_data_request"][0] is True
        assert verdicts["ksi_get_spatial_data_request"][1]["code"] == "ACCESS_REVOKED"
        assert verdicts["ksi_cancel_spatial_data_request"][0] is True
        assert verdicts["ksi_cancel_spatial_data_request"][1]["code"] == "ACCESS_REVOKED"

        lane.replace_grant()
        renewed = lane.consumer.issue(request=lane.request_body(), idempotency_key="matrix-renewed")
        assert renewed["executionState"] == "QUEUED" and renewed["jobId"] != old["jobId"]
        with pytest.raises(RuntimeError, match="ACCESS_REVOKED"):
            lane.consumer.status(old["jobId"])

    expiry_root = tmp_path / "expiry"
    expiry_root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(expiry_root, kind="dsm") as lane:
        from datetime import timedelta as _timedelta

        now = lane._now()  # noqa: SLF001
        lane.revoke_grant()
        lane.replace_grant(
            valid_from=now - _timedelta(minutes=10), valid_until=now - _timedelta(minutes=5)
        )
        client = _raw_client(lane)
        try:
            listed = client.get(lane.asset_base, params={"limit": 2})
            assert listed.status_code == 200 and listed.json()["items"] == []
            detail = client.get(lane.asset_base + "/" + lane.assets["primary"]["asset_ref"])
            _denied(detail, status=404, reason="NOT_FOUND")
            expired_create = client.post(
                lane.base, json=lane.request_body(), headers={"Idempotency-Key": "matrix-expired"}
            )
            _denied(expired_create, status=403, reason="GRANT_REQUIRED")
        finally:
            client.close()

    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(readonly_root, kind="dsm") as lane:
        lane.revoke_grant()
        lane.replace_grant(operations=("READ",))
        client = _raw_client(lane)
        try:
            allowed = client.get(lane.asset_base + "/" + lane.assets["primary"]["asset_ref"])
            assert allowed.status_code == 200 and allowed.headers.get(ACK) == "ALLOWED"
            refused = client.post(
                lane.base, json=lane.request_body(), headers={"Idempotency-Key": "matrix-readonly"}
            )
            _denied(refused, status=403, reason="GRANT_REQUIRED")
        finally:
            client.close()

    ambiguous_root = tmp_path / "ambiguous"
    ambiguous_root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(ambiguous_root, kind="dsm") as lane:
        lane.replace_grant()
        client = _raw_client(lane)
        try:
            clash = client.post(
                lane.base, json=lane.request_body(), headers={"Idempotency-Key": "matrix-ambiguous"}
            )
            _denied(clash, status=403, reason="AMBIGUOUS_GRANT")
            clash_read = client.get(lane.asset_base + "/" + lane.assets["primary"]["asset_ref"])
            _denied(clash_read, status=403, reason="AMBIGUOUS_GRANT")
        finally:
            client.close()

    mismatch_root = tmp_path / "mismatch"
    mismatch_root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(mismatch_root, kind="dsm", mutation="source") as lane:
        failed = lane.request_and_run(key="matrix-mismatch")
        assert failed["executionState"] == "FAILED"
        assert failed["reason"] == "SOURCE_BYTES_MISMATCH"
        assert failed["receipt"] is None and lane.provider.uploads == 0


def test_revoked_bytes_abort_midstream_without_partial_file(tmp_path: Path) -> None:
    """Revoking consent mid-download aborts the byte stream; no partial file."""
    import httpx

    stream_root = tmp_path / "midstream"
    stream_root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(stream_root, kind="dsm", stream_chunk_bytes=64) as lane:
        done = lane.request_and_run(key="midstream-base")
        assert done["executionState"] == "COMPLETED"
        size = done["receipt"]["outputSizeBytes"]
        assert size > 64
        client = _raw_client(lane)
        try:
            received = 0
            with client.stream("GET", lane.file_url(done)) as response:
                assert response.status_code == 200
                assert response.headers.get(ACK) == "ALLOWED"
                for chunk in response.iter_raw(chunk_size=64):
                    received += len(chunk)
                    if received >= 64:
                        lane.set_consent(False)
            raise AssertionError("revoked stream must abort before the full body")
        except (httpx.RemoteProtocolError, httpx.StreamError, httpx.TransportError):
            assert received < size
        finally:
            lane.set_consent(True)
            client.close()
        outdir = tmp_path / "midstream-denied"
        outdir.mkdir(mode=0o700)
        lane.set_consent(False)
        try:
            with pytest.raises(RuntimeError, match="INVALID_FILE_RESPONSE"):
                lane.consumer.download(status=done, output_dir=outdir)
            assert [path for path in outdir.iterdir() if path.suffix == ".tif"] == []
        finally:
            lane.set_consent(True)


# ---------------------------------------------------------------------------
# SUBTASKA bounded matrix: pagination / current-consent / downgrade /
# work-order binding / cross-work-order bytes / missing-ack.
#
# Converted from genuine read-only probes (task5-fix1/probe_{pagination,
# consent,workorder,noack,stale_wo_header,stale2}.py): every status/reason/ack
# below was observed against the real Core lane before being encoded here.
# No mocked success bodies, no Core changes to force 4xx.
# ---------------------------------------------------------------------------


def _subtaska_page_urls(client: Any, base: str, *, limit: int = 1) -> tuple[list[Any], Any]:
    response = client.get(base, params={"limit": limit})
    assert response.status_code == 200
    assert response.headers.get(ACK) == "ALLOWED"
    body = response.json()
    return [item for item in body["items"]], body.get("nextCursor")


def test_pagination_traverses_two_assets_and_jobs_via_http_and_sdk(
    tmp_path: Path,
) -> None:
    """Stable 2-asset/2-job pagination over real HTTP and official SDK stdio.

    Unordered-set completeness plus ordered-ID stability against the current
    full listing; stale cursors after a new job, a canceled status change and
    a grant revocation are typed 409 conflicts; malformed cursors are 422 and
    limit overage is refused. Cross-endpoint cursor reuse is stale, never
    access.
    """
    import asyncio

    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    lane_root = tmp_path / "pages"
    lane_root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(lane_root, kind="dsm") as lane:
        first = lane.request_and_run(key="pages-1")
        lane.advance_observation()
        second = lane.request_and_run(key="pages-2", asset="epoch2")
        refs = sorted([lane.assets["primary"]["asset_ref"], lane.assets["epoch2"]["asset_ref"]])
        job_ids = sorted([first["jobId"], second["jobId"]])
        client = _raw_client(lane)
        try:
            page_one, cursor = _subtaska_page_urls(client, lane.asset_base)
            assert len(page_one) == 1 and cursor
            page_two = client.get(lane.asset_base, params={"limit": 1, "cursor": cursor})
            assert page_two.status_code == 200
            assert page_two.headers.get(ACK) == "ALLOWED"
            assert not page_two.json().get("nextCursor")
            walked = [
                page_one[0]["assetRef"],
                page_two.json()["items"][0]["assetRef"],
            ]
            assert sorted(walked) == refs
            current = client.get(lane.asset_base, params={"limit": 2}).json()
            assert [item["assetRef"] for item in current["items"]] == walked
            assert client.get(lane.asset_base, params={"limit": 1}).json()["items"] == page_one

            jobs_one, jobs_cursor = _subtaska_page_urls(client, lane.base)
            assert len(jobs_one) == 1 and jobs_cursor
            jobs_two = client.get(lane.base, params={"limit": 1, "cursor": jobs_cursor})
            assert jobs_two.status_code == 200
            walked_jobs = [
                jobs_one[0]["jobId"],
                jobs_two.json()["items"][0]["jobId"],
            ]
            assert sorted(walked_jobs) == job_ids

            malformed = client.get(lane.asset_base, params={"limit": 1, "cursor": "not-a-cursor"})
            assert malformed.status_code == 422
            assert malformed.json()["reason"] == "INVALID_REQUEST_BOUNDS"
            assert malformed.headers.get(ACK) is None
            over = client.get(lane.asset_base, params={"limit": 10})
            assert over.status_code == 422
            assert over.json()["reason"] == "RESOURCE_LIMIT_EXCEEDED"
            assert over.headers.get(ACK) is None
            cross = client.get(lane.asset_base, params={"limit": 1, "cursor": jobs_cursor})
            assert cross.status_code == 409
            assert cross.json()["reason"] == "SPATIAL_DATA_CURSOR_STALE"
            assert cross.headers.get(ACK) is None
        finally:
            client.close()

        config = _sdk_config(lane, "pages-sdk")

        async def exercise() -> None:
            async with (
                stdio_client(fixture.task5_sdk_parameters(config)) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                scope = {"siteId": "site-1", "workAreaId": lane.area_id, "limit": 1}
                first_page = await session.call_tool("ksi_list_spatial_data_assets", dict(scope))
                assert first_page.is_error is not True
                content = first_page.structured_content or {}
                assets_cursor = content.get("nextCursor")
                assert assets_cursor
                sdk_walked = [content["items"][0]["assetRef"]]
                _assert_no_raster_bytes(content)
                second_page = await session.call_tool(
                    "ksi_list_spatial_data_assets",
                    dict(scope, cursor=assets_cursor),
                )
                assert second_page.is_error is not True
                second_content = second_page.structured_content or {}
                sdk_walked.append(second_content["items"][0]["assetRef"])
                assert sorted(sdk_walked) == refs

                jobs_first = await session.call_tool("ksi_list_spatial_data_requests", dict(scope))
                assert jobs_first.is_error is not True
                sdk_jobs: list[str] = []
                pending: Any = None
                for _ in range(4):
                    page_call = await session.call_tool(
                        "ksi_list_spatial_data_requests",
                        dict(scope) if pending is None else dict(scope, cursor=pending),
                    )
                    assert page_call.is_error is not True
                    page_content = page_call.structured_content or {}
                    sdk_jobs.extend(item["jobId"] for item in page_content["items"])
                    _assert_no_raster_bytes(page_content)
                    pending = page_content.get("nextCursor")
                    if not pending:
                        break
                assert sorted(sdk_jobs) == sorted([first["jobId"], second["jobId"]])

                malformed_sdk = await session.call_tool(
                    "ksi_list_spatial_data_assets",
                    dict(scope, cursor="not-a-cursor"),
                )
                assert malformed_sdk.is_error is True
                assert (malformed_sdk.structured_content or {})["code"] == "INVALID_REQUEST_BOUNDS"
                over_sdk = await session.call_tool(
                    "ksi_list_spatial_data_assets", dict(scope, limit=10)
                )
                assert over_sdk.is_error is True
                assert (over_sdk.structured_content or {})["code"] == ("RESOURCE_LIMIT_EXCEEDED")
                cross_sdk = await session.call_tool(
                    "ksi_list_spatial_data_assets",
                    dict(scope, cursor=jobs_cursor),
                )
                assert cross_sdk.is_error is True
                assert (cross_sdk.structured_content or {})["code"] == ("SPATIAL_DATA_CURSOR_STALE")

        asyncio.run(exercise())

        drift_client = _raw_client(lane)
        try:
            fresh_jobs = drift_client.get(lane.base, params={"limit": 1}).json()["nextCursor"]
            third = lane.consumer.issue(request=lane.request_body(), idempotency_key="pages-third")
            assert third["executionState"] == "QUEUED"
            grown = drift_client.get(lane.base, params={"limit": 1, "cursor": fresh_jobs})
            assert grown.status_code == 409
            assert grown.json()["reason"] == "SPATIAL_DATA_CURSOR_STALE"
            assert grown.headers.get(ACK) is None

            before_cancel = drift_client.get(lane.base, params={"limit": 1}).json()["nextCursor"]
            canceled = drift_client.post(lane.base + "/" + third["jobId"] + "/cancel")
            assert canceled.status_code == 200
            drifted = drift_client.get(lane.base, params={"limit": 1, "cursor": before_cancel})
            assert drifted.status_code == 409
            assert drifted.json()["reason"] == "SPATIAL_DATA_CURSOR_STALE"
            assert drifted.headers.get(ACK) is None
        finally:
            drift_client.close()

        fresh_client = _raw_client(lane)
        try:
            assets_cursor_now = fresh_client.get(lane.asset_base, params={"limit": 1}).json()[
                "nextCursor"
            ]
            lane.revoke_grant()
            try:
                stale = fresh_client.get(
                    lane.asset_base,
                    params={"limit": 1, "cursor": assets_cursor_now},
                )
                assert stale.status_code == 409
                assert stale.json()["reason"] == "SPATIAL_DATA_CURSOR_STALE"
                assert stale.headers.get(ACK) is None
            finally:
                lane.replace_grant()
        finally:
            fresh_client.close()


def test_current_consent_revoked_denies_each_sdk_tool(tmp_path: Path) -> None:
    """CURRENT-consent revoke before EACH SDK call denies all six tools.

    Even list pages and known completed/queued jobs fail closed with
    AI_EGRESS_DENIED (never an empty-page bypass); restore returns to
    COMPLETED/QUEUED with no issued/canceled journal mutation, no new
    uploads and no raw bytes. The original grant-revocation sweep stays as
    the separate valid empty-list control inside the rights matrix test.
    """
    import asyncio

    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    lane_root = tmp_path / "consent"
    lane_root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(lane_root, kind="dsm") as lane:
        base = lane.request_and_run(key="consent-base")
        assert base["executionState"] == "COMPLETED"
        queued = lane.consumer.issue(request=lane.request_body(), idempotency_key="consent-queued")
        assert queued["executionState"] == "QUEUED"
        asset_ref = lane.assets["primary"]["asset_ref"]
        jobs_journal = lane_root / "jobs.jsonl"
        jobs_before = jobs_journal.read_bytes()
        uploads_before = lane.provider.uploads
        config = _sdk_config(lane, "consent-sweep")

        async def sweep() -> dict[str, Any]:
            verdicts: dict[str, Any] = {}
            async with (
                stdio_client(fixture.task5_sdk_parameters(config)) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                calls = [
                    ("ksi_list_spatial_data_assets", {"limit": 2}),
                    ("ksi_get_spatial_data_asset", {"assetRef": asset_ref}),
                    (
                        "ksi_create_spatial_data_request",
                        {
                            "assetRef": asset_ref,
                            "requestedBounds": list(fixture.TASK5_REQUEST_BOUNDS),
                            "observedCrsDigest": lane.assets["primary"]["observed_crs_digest"],
                            "idempotencyKey": "consent-sweep-create",
                        },
                    ),
                    ("ksi_list_spatial_data_requests", {"limit": 2}),
                    ("ksi_get_spatial_data_request", {"jobId": base["jobId"]}),
                    ("ksi_cancel_spatial_data_request", {"jobId": queued["jobId"]}),
                ]
                for tool, extra in calls:
                    args: dict[str, Any] = {
                        "siteId": "site-1",
                        "workAreaId": lane.area_id,
                    }
                    args.update(extra)
                    lane.set_consent(False)
                    try:
                        result = await session.call_tool(tool, args)
                    finally:
                        lane.set_consent(True)
                    content = result.structured_content or {}
                    verdicts[tool] = (result.is_error, content.get("code"))
                    assert result.is_error is True
                    assert content.get("code") == "AI_EGRESS_DENIED"
                    _assert_no_raster_bytes(content)
                assert jobs_journal.read_bytes() == jobs_before
                assert lane.provider.uploads == uploads_before
                control = await session.call_tool(
                    "ksi_get_spatial_data_request",
                    {
                        "siteId": "site-1",
                        "workAreaId": lane.area_id,
                        "jobId": base["jobId"],
                    },
                )
                assert control.is_error is not True
                assert (control.structured_content or {})["job"]["executionState"] == "COMPLETED"
                listed = await session.call_tool(
                    "ksi_list_spatial_data_requests",
                    {"siteId": "site-1", "workAreaId": lane.area_id, "limit": 2},
                )
                assert listed.is_error is not True
                states = {
                    item["jobId"]: item["executionState"]
                    for item in (listed.structured_content or {})["items"]
                }
                assert states == {
                    base["jobId"]: "COMPLETED",
                    queued["jobId"]: "QUEUED",
                }
                canceled = await session.call_tool(
                    "ksi_cancel_spatial_data_request",
                    {
                        "siteId": "site-1",
                        "workAreaId": lane.area_id,
                        "jobId": queued["jobId"],
                    },
                )
                assert canceled.is_error is not True
                assert (canceled.structured_content or {})["executionState"] == "CANCELED"
            return verdicts

        verdicts = asyncio.run(sweep())
        assert set(verdicts) == set(SDK_TOOLS)
        assert all(flag is True and code == "AI_EGRESS_DENIED" for flag, code in verdicts.values())
        assert lane.provider.uploads == uploads_before
        assert lane.consumer.status(queued["jobId"])["executionState"] == "CANCELED"


def test_header_and_purpose_downgrade_cannot_unlock_general(
    tmp_path: Path,
) -> None:
    """Downgraded purpose plus a forged ack request header stay denied.

    GENERAL_DATA_USE is refused with PERMISSION_DENIED whether or not the
    caller forges the ack header as a request header; a forged header never
    overrides revoked CURRENT consent. No ack and no bytes on any refusal.
    """
    lane_root = tmp_path / "downgrade"
    lane_root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(lane_root, kind="dsm") as lane:
        base = lane.request_and_run(key="downgrade-base")
        assert base["executionState"] == "COMPLETED"
        asset_ref = lane.assets["primary"]["asset_ref"]
        client = _raw_client(lane)
        try:
            control = client.get(lane.asset_base + "/" + asset_ref)
            assert control.status_code == 200
            assert control.headers.get(ACK) == "ALLOWED"
            downgraded = dict(lane.request_body())
            downgraded["purpose"] = "GENERAL_DATA_USE"
            refused = client.post(
                lane.base,
                json=downgraded,
                headers={"Idempotency-Key": "downgrade-plain"},
            )
            assert refused.status_code == 403
            assert refused.json()["reason"] == "PERMISSION_DENIED"
            assert refused.headers.get(ACK) is None
            _assert_no_raster_bytes(refused.json())
            forged = client.post(
                lane.base,
                json=downgraded,
                headers={
                    "Idempotency-Key": "downgrade-forged",
                    "X-KSI-Spatial-Data-AI-Egress": "ALLOWED",
                },
            )
            assert forged.status_code == 403
            assert forged.json()["reason"] == "PERMISSION_DENIED"
            assert forged.headers.get(ACK) is None
            _assert_no_raster_bytes(forged.json())
            lane.set_consent(False)
            try:
                held = client.get(
                    lane.asset_base + "/" + asset_ref,
                    headers={"X-KSI-Spatial-Data-AI-Egress": "ALLOWED"},
                )
                assert held.status_code == 403
                assert held.json()["reason"] == "AI_EGRESS_DENIED"
                assert held.headers.get(ACK) is None
            finally:
                lane.set_consent(True)
            restored = client.get(lane.asset_base + "/" + asset_ref)
            assert restored.status_code == 200
            assert restored.headers.get(ACK) == "ALLOWED"
        finally:
            client.close()


def test_owner_work_order_mismatch_denies_metadata_and_issue(
    tmp_path: Path,
) -> None:
    """Authentic owner work-order mismatch denies metadata and issuance.

    The routes carry no WorkOrder field, yet the source's owner work order
    must bind exactly ``[workAreaId]``: a wrong area and a multi-area (ALL)
    record both fail closed with NOT_FOUND, while the SDK surface maps the
    same boundary. Restoring the genuine record restores 200 + ack.
    """
    import asyncio

    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    lane_root = tmp_path / "workorder"
    lane_root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(lane_root, kind="dsm") as lane:
        base = lane.request_and_run(key="workorder-base")
        assert base["executionState"] == "COMPLETED"
        asset_ref = lane.assets["primary"]["asset_ref"]
        work_order_id = lane.graph.source.work_order_id
        order = lane.graph.work_orders.get(work_order_id, organization_id="organization-1")
        assert order is not None
        assert list(order.work_area_ids) == [lane.area_id]
        client = _raw_client(lane)
        try:
            control = client.get(lane.asset_base + "/" + asset_ref)
            assert control.status_code == 200
            assert control.headers.get(ACK) == "ALLOWED"
            lane.graph.work_orders._orders[work_order_id] = order.model_copy(  # noqa: SLF001
                update={"work_area_ids": ["area-9"]}
            )
            try:
                wrong = client.get(lane.asset_base + "/" + asset_ref)
                assert wrong.status_code == 404
                assert wrong.json()["reason"] == "NOT_FOUND"
                assert wrong.headers.get(ACK) is None
                refused = client.post(
                    lane.base,
                    json=lane.request_body(),
                    headers={"Idempotency-Key": "workorder-wrong-area"},
                )
                assert refused.status_code == 404
                assert refused.json()["reason"] == "NOT_FOUND"
                assert refused.headers.get(ACK) is None
            finally:
                lane.graph.work_orders._orders[work_order_id] = order  # noqa: SLF001
            lane.graph.work_orders._orders[work_order_id] = order.model_copy(  # noqa: SLF001
                update={"work_area_ids": [lane.area_id, "area-9"]}
            )
            try:
                broad = client.get(lane.asset_base + "/" + asset_ref)
                assert broad.status_code == 404
                assert broad.json()["reason"] == "NOT_FOUND"
                assert broad.headers.get(ACK) is None
            finally:
                lane.graph.work_orders._orders[work_order_id] = order  # noqa: SLF001
            restored = client.get(lane.asset_base + "/" + asset_ref)
            assert restored.status_code == 200
            assert restored.headers.get(ACK) == "ALLOWED"
        finally:
            client.close()

        lane.graph.work_orders._orders[work_order_id] = order.model_copy(  # noqa: SLF001
            update={"work_area_ids": ["area-9"]}
        )
        try:
            config = _sdk_config(lane, "workorder-sdk")

            async def exercise() -> Any:
                async with (
                    stdio_client(fixture.task5_sdk_parameters(config)) as (
                        read,
                        write,
                    ),
                    ClientSession(read, write) as session,
                ):
                    await session.initialize()
                    return await session.call_tool(
                        "ksi_get_spatial_data_asset",
                        {
                            "siteId": "site-1",
                            "workAreaId": lane.area_id,
                            "assetRef": asset_ref,
                        },
                    )

            detail = asyncio.run(exercise())
            assert detail.is_error is True
            assert (detail.structured_content or {})["code"] == "NOT_FOUND"
        finally:
            lane.graph.work_orders._orders[work_order_id] = order  # noqa: SLF001


def test_cross_work_order_bytes_fail_worker_integrity(tmp_path: Path) -> None:
    """Bytes from another work order fail the worker integrity gate.

    Additional byte-plane negative only: it never replaces the owner-record
    boundary above. A job issued for the epoch-2 source but served the
    primary epoch's bytes reaches the worker and fails FAILED /
    INTEGRITY_MISMATCH with no receipt and no new upload.
    """
    lane_root = tmp_path / "crossbytes"
    lane_root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(lane_root, kind="dsm") as lane:
        lane.advance_observation()
        primary_ref = lane.assets["primary"]["asset_ref"]
        epoch2_ref = lane.assets["epoch2"]["asset_ref"]
        client = _raw_client(lane)
        try:
            for ref in (primary_ref, epoch2_ref):
                detail = client.get(lane.asset_base + "/" + ref)
                assert detail.status_code == 200
                assert detail.headers.get(ACK) == "ALLOWED"
        finally:
            client.close()
        lane.provider.source = lane.epoch_bytes[epoch2_ref]
        issued_control = lane.consumer.issue(
            request=lane.request_body(asset="epoch2"),
            idempotency_key="crossbytes-control",
        )
        control = lane.run_worker(issued_control["jobId"])
        assert control["executionState"] == "COMPLETED"
        assert control["receipt"] is not None
        uploads_after_control = lane.provider.uploads
        lane.provider.source = lane.epoch_bytes[primary_ref]
        issued = lane.consumer.issue(
            request=lane.request_body(asset="epoch2"),
            idempotency_key="crossbytes-mismatch",
        )
        assert issued["executionState"] == "QUEUED"
        status = lane.run_worker(issued["jobId"])
        assert status["executionState"] == "FAILED"
        assert status["reason"] == "INTEGRITY_MISMATCH"
        assert status["receipt"] is None
        assert lane.provider.uploads == uploads_after_control


def test_missing_ack_refuses_without_body_reflection(tmp_path: Path) -> None:
    """A stripped genuine ack makes the SDK refuse without reflecting the body.

    The fixture serves the SAME live Core app with only the
    ``http.response.start`` ack removed from a valid 200 response (no mocked
    success body): the official SDK returns AI_EGRESS_UNACKNOWLEDGED for both
    get and list, carrying only the closed code/remediation. Restoring the
    direct listener restores success.
    """
    import asyncio
    import json as _json

    import httpx
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    lane_root = tmp_path / "noack"
    lane_root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(lane_root, kind="dsm") as lane:
        base = lane.request_and_run(key="noack-base")
        assert base["executionState"] == "COMPLETED"
        job_id = base["jobId"]
        probe = _raw_client(lane)
        try:
            control = probe.get(lane.base + "/" + job_id)
            assert control.status_code == 200
            assert control.headers.get(ACK) == "ALLOWED"
        finally:
            probe.close()
        with fixture.serve_without_ack(lane):
            stripped = httpx.Client(
                base_url=lane.origin,
                headers={"Authorization": "Bearer " + fixture.TASK5_AI_TOKEN},
                timeout=10,
                trust_env=False,
            )
            try:
                raw = stripped.get(lane.base + "/" + job_id)
                assert raw.status_code == 200
                assert raw.headers.get(ACK) is None
                assert raw.json()["jobId"] == job_id
            finally:
                stripped.close()
            config = _sdk_config(lane, "noack-stripped")

            async def exercise() -> dict[str, Any]:
                outcomes: dict[str, Any] = {}
                async with (
                    stdio_client(fixture.task5_sdk_parameters(config)) as (
                        read,
                        write,
                    ),
                    ClientSession(read, write) as session,
                ):
                    await session.initialize()
                    gotten = await session.call_tool(
                        "ksi_get_spatial_data_request",
                        {
                            "siteId": "site-1",
                            "workAreaId": lane.area_id,
                            "jobId": job_id,
                        },
                    )
                    listed = await session.call_tool(
                        "ksi_list_spatial_data_requests",
                        {
                            "siteId": "site-1",
                            "workAreaId": lane.area_id,
                            "limit": 2,
                        },
                    )
                    outcomes["get"] = gotten
                    outcomes["listed"] = listed
                return outcomes

            outcomes = asyncio.run(exercise())
            for name in ("get", "listed"):
                result = outcomes[name]
                assert result.is_error is True
                content = result.structured_content or {}
                assert content.get("code") == "AI_EGRESS_UNACKNOWLEDGED"
                assert "jobId" not in _json.dumps(content)
                assert "job" not in content and "items" not in content
                _assert_no_raster_bytes(content)
        restored_config = _sdk_config(lane, "noack-restored")

        async def restored() -> None:
            async with (
                stdio_client(fixture.task5_sdk_parameters(restored_config)) as (
                    read,
                    write,
                ),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                gotten = await session.call_tool(
                    "ksi_get_spatial_data_request",
                    {"siteId": "site-1", "workAreaId": lane.area_id, "jobId": job_id},
                )
                assert gotten.is_error is not True
                assert (gotten.structured_content or {})["job"]["executionState"] == "COMPLETED"

        asyncio.run(restored())
