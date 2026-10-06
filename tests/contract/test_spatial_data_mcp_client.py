"""Client contract tests for the spatial-data MCP adapter (RED first)."""

from __future__ import annotations

import asyncio
import json
import time
from http.server import BaseHTTPRequestHandler
from typing import Any

import pytest
import spatial_data_mcp_fixture as fixture
from spatial_data_mcp_fixture import LoopbackCore, json_response

fixture.ensure_source_path()

SITE = "site-a"
AREA = "area-a"
ASSET = "ksa-v1-" + "a" * 64
JOB = "sdj-v1-12345678-1234-1234-1234-1234567890ab"


def _digest(byte: str = "b") -> str:
    return "sha256:" + byte * 64


def _asset_view(**overrides: Any) -> dict[str, Any]:
    from ksi_event_contracts.spatial_data_ai import SpatialDataAssetViewV1

    payload: dict[str, Any] = {
        "assetRef": ASSET,
        "siteId": SITE,
        "workAreaId": AREA,
        "workOrderId": "wo-a",
        "epochId": "ep-a",
        "submissionRef": "sub-a",
        "revision": 1,
        "artifactKind": "dsm",
        "lifecycleState": "SEALED",
        "observedSha256": _digest("c"),
        "observedSizeBytes": 100,
        "inspectionReportDigest": _digest("d"),
        "inspectorBuildDigest": _digest("e"),
        "observedCrsIdentifier": "EPSG:5186",
        "observedCrsDigest": _digest("f"),
        "observedCrsUnits": "meter",
        "transform": [0.5, 0.0, 100.0, 0.0, -0.5, 200.0],
        "resolution": [0.5, 0.5],
        "bandCount": 1,
        "dtype": "float32",
        "permittedBounds": [0.0, 0.0, 10.0, 10.0],
        "declarationRecordedAt": "2026-10-06T00:00:00Z",
        "permittedOperations": ["READ"],
        "attribution": "fixture attribution",
        "modificationNotice": "fixture notice",
        "accuracyAssessed": False,
    }
    payload.update(overrides)
    return SpatialDataAssetViewV1.model_validate(payload).model_dump(by_alias=True, mode="json")


def _job_view(
    state: str = "QUEUED", availability: str = "NOT_READY", **overrides: Any
) -> dict[str, Any]:
    from ksi_event_contracts.spatial_data import SpatialDataJobViewV1

    payload: dict[str, Any] = {
        "jobId": JOB,
        "assetRef": ASSET,
        "siteId": SITE,
        "workAreaId": AREA,
        "createdAt": "2026-10-06T00:00:00Z",
        "executionState": state,
        "availability": availability,
    }
    payload.update(overrides)
    return SpatialDataJobViewV1.model_validate(payload).model_dump(by_alias=True, mode="json")


def _completed_receipt() -> dict[str, Any]:
    from ksi_event_contracts.spatial_data import SpatialDataReceiptV1

    receipt = SpatialDataReceiptV1.model_validate(
        {
            "jobId": JOB,
            "jobDigest": _digest("1"),
            "sourceDigest": _digest("2"),
            "requestDigest": _digest("3"),
            "runtimeDigest": _digest("4"),
            "policyDigest": _digest("5"),
            "grantDigest": _digest("6"),
            "artifactId": "art-a",
            "artifactKind": "dsm",
            "sourceSha256": _digest("7"),
            "sourceSizeBytes": 10,
            "requestedBounds": [100.0, 198.0, 102.0, 200.0],
            "requestedCrsDigest": _digest("8"),
            "actualBounds": [100.0, 198.0, 102.0, 200.0],
            "pixelWindow": [0, 4, 0, 4],
            "width": 4,
            "height": 4,
            "transform": [0.5, 0.0, 100.0, 0.0, -0.5, 200.0],
            "sourceTransform": [0.5, 0.0, 100.0, 0.0, -0.5, 200.0],
            "sourceResolution": [0.5, 0.5],
            "observedCrsIdentifier": "EPSG:5186",
            "observedCrsDigest": _digest("8"),
            "bandCount": 1,
            "dtype": "float32",
            "nodataRepresentation": "MASK",
            "validPixelCount": 16,
            "outputSha256": _digest("9"),
            "outputSizeBytes": 100,
            "accuracyAssessed": False,
            "preparedAt": "2026-10-06T01:00:00Z",
            "declarationRecordedAt": "2026-10-06T00:00:00Z",
            "attribution": "fixture attribution",
            "modificationNotice": "fixture notice",
            "limitations": ["UNKNOWN_VERTICAL_REFERENCE"],
        }
    ).sealed()
    return receipt.model_dump(by_alias=True, mode="json")


def _completed_job_view() -> dict[str, Any]:
    return _job_view(
        "COMPLETED",
        "AVAILABLE",
        receipt=_completed_receipt(),
    )


def _client(origin: str, **overrides: Any) -> Any:
    from ksi_spatial_data_mcp.config import AdapterConfig
    from ksi_spatial_data_mcp.core_client import CoreSpatialDataClient

    token = fixture.write_token(f"client-{len(overrides)}-{time.time_ns()}")
    path = fixture.write_adapter_config(
        f"client-{time.time_ns()}.json",
        origin=origin,
        token_path=token,
        overrides=overrides or None,
    )
    return CoreSpatialDataClient(AdapterConfig.from_file(path))


def test_tool_maps_are_closed_and_typed_before_transport() -> None:
    from ksi_spatial_data_mcp.core_client import (
        CoreAdapterError,
        validate_tool_arguments,
    )
    from ksi_spatial_data_mcp.tool_models import (
        TOOL_ARGUMENT_MODELS,
        TOOL_RESULT_MODELS,
    )

    assert set(TOOL_ARGUMENT_MODELS) == {
        "ksi_list_spatial_data_assets",
        "ksi_get_spatial_data_asset",
        "ksi_create_spatial_data_request",
        "ksi_list_spatial_data_requests",
        "ksi_get_spatial_data_request",
        "ksi_cancel_spatial_data_request",
    }
    assert set(TOOL_RESULT_MODELS) == set(TOOL_ARGUMENT_MODELS)
    with pytest.raises(CoreAdapterError, match="UNKNOWN_TOOL"):
        validate_tool_arguments("ksi_download_raster", {"siteId": SITE})
    with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
        validate_tool_arguments(
            "ksi_create_spatial_data_request",
            {
                "siteId": SITE,
                "workAreaId": AREA,
                "assetRef": ASSET,
                "requestedBounds": [0.0, 0.0, 4.0, 4.0],
                "observedCrsDigest": _digest(),
                "idempotencyKey": "key-a",
                "purpose": "GENERAL_DATA_USE",
            },
        )
    with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
        validate_tool_arguments(
            "ksi_list_spatial_data_assets",
            {"siteId": SITE, "workAreaId": AREA, "cursor": "Bearer abc"},
        )
    for bad in (".", "../x", "a/b", "x" * 256):
        with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
            validate_tool_arguments(
                "ksi_get_spatial_data_request",
                {"siteId": bad, "workAreaId": AREA, "jobId": JOB},
            )


def test_fixed_method_path_map_and_exact_call_ids() -> None:
    routes: dict[str, tuple[tuple[str, str], Any]] = {
        "ksi_list_spatial_data_assets": (
            ("GET", f"/v1/sites/{SITE}/work-areas/{AREA}/spatial-data-assets?limit=10"),
            {"items": [], "nextCursor": "cursor-a"},
        ),
        "ksi_get_spatial_data_asset": (
            ("GET", f"/v1/sites/{SITE}/work-areas/{AREA}/spatial-data-assets/{ASSET}"),
            _asset_view(),
        ),
        "ksi_list_spatial_data_requests": (
            ("GET", f"/v1/sites/{SITE}/work-areas/{AREA}/spatial-data-requests?limit=10"),
            {"items": [_job_view()], "nextCursor": None},
        ),
        "ksi_get_spatial_data_request": (
            ("GET", f"/v1/sites/{SITE}/work-areas/{AREA}/spatial-data-requests/{JOB}"),
            _job_view(),
        ),
        "ksi_cancel_spatial_data_request": (
            (
                "POST",
                f"/v1/sites/{SITE}/work-areas/{AREA}/spatial-data-requests/{JOB}/cancel",
            ),
            _job_view("CANCELED", "UNAVAILABLE"),
        ),
    }

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        for _name, ((expected_method, expected_path), payload) in routes.items():
            if path == expected_path:
                assert method == expected_method
                return json_response(payload)
        return json_response({"reason": "NOT_FOUND"}, status=404, ack=False)

    core = LoopbackCore(responder).start()
    try:
        client = _client(core.origin)
        args: dict[str, dict[str, Any]] = {
            "ksi_list_spatial_data_assets": {
                "siteId": SITE,
                "workAreaId": AREA,
                "limit": 10,
            },
            "ksi_get_spatial_data_asset": {
                "siteId": SITE,
                "workAreaId": AREA,
                "assetRef": ASSET,
            },
            "ksi_list_spatial_data_requests": {
                "siteId": SITE,
                "workAreaId": AREA,
                "limit": 10,
            },
            "ksi_get_spatial_data_request": {
                "siteId": SITE,
                "workAreaId": AREA,
                "jobId": JOB,
            },
            "ksi_cancel_spatial_data_request": {
                "siteId": SITE,
                "workAreaId": AREA,
                "jobId": JOB,
            },
        }
        for name, arguments in args.items():
            result = asyncio.run(client.invoke(name, arguments))
            assert isinstance(result, dict)
        assert len(core.requests) == 5
        cancel = next(r for r in core.requests if r["path"].endswith("/cancel"))
        assert cancel["method"] == "POST"
        assert cancel["body"] == b""
        listed = asyncio.run(
            client.invoke(
                "ksi_list_spatial_data_assets",
                {"siteId": SITE, "workAreaId": AREA, "limit": 10},
            )
        )
        assert listed["nextCursor"] == "cursor-a"
    finally:
        core.close()


def test_create_supplies_native_external_ai_and_returns_queued_job() -> None:
    seen: dict[str, Any] = {}

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        assert method == "POST"
        assert path == f"/v1/sites/{SITE}/work-areas/{AREA}/spatial-data-requests"
        seen["body"] = json.loads(body)
        seen["idempotency"] = headers.get("Idempotency-Key")
        return json_response(_job_view(), status=201)

    core = LoopbackCore(responder).start()
    try:
        result = asyncio.run(
            _client(core.origin).invoke(
                "ksi_create_spatial_data_request",
                {
                    "siteId": SITE,
                    "workAreaId": AREA,
                    "assetRef": ASSET,
                    "requestedBounds": [0.0, 0.0, 4.0, 4.0],
                    "observedCrsDigest": _digest(),
                    "idempotencyKey": "stable-key-a",
                },
            )
        )
        assert result["jobId"] == JOB
        assert seen["body"]["resolutionMode"] == "NATIVE"
        assert seen["body"]["purpose"] == "EXTERNAL_AI"
        assert seen["body"]["assetRef"] == ASSET
        assert seen["idempotency"] == "stable-key-a"
    finally:
        core.close()


def test_get_wraps_completed_available_receipt_and_rejects_swapped_ids() -> None:
    from ksi_spatial_data_mcp.core_client import CoreAdapterError

    completed = _completed_job_view()

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        if path.endswith(f"/spatial-data-requests/{JOB}"):
            return json_response(completed)
        return json_response({"reason": "NOT_FOUND"}, status=404, ack=False)

    core = LoopbackCore(responder).start()
    try:
        result = asyncio.run(
            _client(core.origin).invoke(
                "ksi_get_spatial_data_request",
                {"siteId": SITE, "workAreaId": AREA, "jobId": JOB},
            )
        )
        reference = result["fileReference"]
        assert reference["referenceVersion"] == "spatial-data-file-reference.v1"
        assert reference["method"] == "GET"
        assert (
            reference["relativePath"]
            == f"/v1/sites/{SITE}/work-areas/{AREA}/spatial-data-requests/{JOB}/file"
        )
        assert reference["outputSha256"] == _digest("9")
        assert reference["outputSizeBytes"] == 100
        assert reference["authenticationRequired"] is True
        assert reference["rangeSupported"] is False

        swapped = dict(completed)
        other_job = "sdj-v1-aaaaaaaa-1234-1234-1234-1234567890ab"
        swapped["jobId"] = other_job
        core2 = LoopbackCore(
            lambda m, p, h, b: json_response(swapped),
        ).start()
        try:
            with pytest.raises(CoreAdapterError, match="INVALID_CORE_RESPONSE"):
                asyncio.run(
                    _client(core2.origin).invoke(
                        "ksi_get_spatial_data_request",
                        {"siteId": SITE, "workAreaId": AREA, "jobId": JOB},
                    )
                )
        finally:
            core2.close()

        foreign_asset = _asset_view(siteId="site-b")
        core3 = LoopbackCore(lambda m, p, h, b: json_response(foreign_asset)).start()
        try:
            with pytest.raises(CoreAdapterError, match="INVALID_CORE_RESPONSE"):
                asyncio.run(
                    _client(core3.origin).invoke(
                        "ksi_get_spatial_data_asset",
                        {"siteId": SITE, "workAreaId": AREA, "assetRef": ASSET},
                    )
                )
        finally:
            core3.close()
    finally:
        core.close()


def test_framing_defenses_reject_bad_json_and_missing_ack() -> None:
    from ksi_spatial_data_mcp.core_client import CoreAdapterError

    secret = "LOOPBACK_SECRET_BODY"
    cases: dict[str, Any] = {
        "no-ack": (b'{"items":[]}', 200, {}, None),
        "wrong-ack": (b'{"items":[]}', 200, {"X-KSI-Spatial-Data-AI-Egress": "DENIED"}, None),
        "duplicate": (b'{"items":[],"items":[]}', 200, None, None),
        "infinite": (b'{"items":NaN}', 200, None, None),
        "deep": (b"[" * 300 + b"]" * 300, 200, None, None),
        "compressed": (b'{"items":[]}', 200, {"Content-Encoding": "gzip"}, None),
        "html": (b"<html></html>", 200, {"Content-Type": "text/html"}, None),
        "truncated": (b'{"items":', 200, None, 10_000),
        "server-secret": (secret.encode(), 500, None, None),
    }

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        marker = path.split("?")[0].split("/")[3]
        raw, status, extra, declared = cases[marker]
        response_headers = {"Content-Type": "application/json"}
        if marker not in {"no-ack", "server-secret"}:
            response_headers["X-KSI-Spatial-Data-AI-Egress"] = "ALLOWED"
        if extra:
            response_headers.update(extra)
        if marker == "truncated":
            return status, response_headers, raw, declared
        return status, response_headers, raw

    class TruncatingCore(LoopbackCore):
        def _build_handler(self) -> type[BaseHTTPRequestHandler]:
            outer = self

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self) -> None:  # noqa: N802
                    length = int(self.headers.get("Content-Length") or 0)
                    if length:
                        self.rfile.read(length)
                    parts: tuple[Any, ...] = outer._responder(
                        self.command, self.path, dict(self.headers), b""
                    )
                    status, headers, raw = parts[0], parts[1], parts[2]
                    declared = parts[3] if len(parts) > 3 else len(raw)
                    outer.requests.append({"method": self.command, "path": self.path, "body": b""})
                    self.send_response(status)
                    for key, value in headers.items():
                        self.send_header(key, value)
                    self.send_header("Content-Length", str(declared))
                    self.end_headers()
                    try:
                        self.wfile.write(raw)
                        self.connection.close()
                    except (BrokenPipeError, ConnectionResetError):
                        pass

                def log_message(self, _format: str, *_args: object) -> None:
                    return

            return Handler

    core = TruncatingCore(responder).start()
    try:
        client = _client(core.origin)
        expected = {
            "no-ack": "AI_EGRESS_UNACKNOWLEDGED",
            "wrong-ack": "AI_EGRESS_UNACKNOWLEDGED",
            "duplicate": "INVALID_CORE_RESPONSE",
            "infinite": "INVALID_CORE_RESPONSE",
            "deep": "INVALID_CORE_RESPONSE",
            "compressed": "INVALID_CORE_RESPONSE",
            "html": "INVALID_CORE_RESPONSE",
            "truncated": "CORE_UNAVAILABLE",
            "server-secret": "CORE_UNAVAILABLE",
        }
        for marker, code in expected.items():
            with pytest.raises(CoreAdapterError, match=code) as raised:
                asyncio.run(
                    client.invoke(
                        "ksi_list_spatial_data_assets",
                        {"siteId": marker, "workAreaId": AREA},
                    )
                )
            assert raised.value.code == code
            assert secret not in str(raised.value)
            assert secret not in repr(raised.value)
    finally:
        core.close()


def test_error_envelope_preserves_only_validated_reasons() -> None:
    from ksi_spatial_data_mcp.core_client import CoreAdapterError

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        marker = path.split("?")[0].split("/")[3]
        if marker == "denied":
            return json_response(
                {
                    "reason": "AI_EGRESS_DENIED",
                    "message": "no ai rights",
                    "retryable": False,
                    "remediation": ["CHECK_AI_CONSENT"],
                },
                status=403,
                ack=False,
            )
        if marker == "stale":
            return json_response(
                {
                    "reason": "SPATIAL_DATA_CURSOR_STALE",
                    "message": "cursor changed",
                    "retryable": False,
                    "remediation": ["RETRY_REQUEST"],
                },
                status=409,
                ack=False,
            )
        if marker == "grant":
            return json_response(
                {
                    "reason": "GRANT_REQUIRED",
                    "message": "no current grant",
                    "retryable": False,
                    "remediation": ["REQUEST_NEW_GRANT"],
                },
                status=403,
                ack=False,
            )
        if marker == "forged":
            return json_response(
                {"reason": "GRANT_REQUIRED", "remediation": ["CHECK_AI_CONSENT"]},
                status=403,
                ack=False,
            )
        return json_response({"reason": "NOT_FOUND"}, status=404, ack=False)

    core = LoopbackCore(responder).start()
    try:
        client = _client(core.origin)
        with pytest.raises(CoreAdapterError) as denied:
            asyncio.run(
                client.invoke(
                    "ksi_list_spatial_data_assets",
                    {"siteId": "denied", "workAreaId": AREA},
                )
            )
        assert denied.value.code == "AI_EGRESS_DENIED"
        with pytest.raises(CoreAdapterError) as stale:
            asyncio.run(
                client.invoke(
                    "ksi_list_spatial_data_assets",
                    {"siteId": "stale", "workAreaId": AREA},
                )
            )
        assert stale.value.code == "SPATIAL_DATA_CURSOR_STALE"
        # Forged remediation outside the closed model still yields the reason,
        # never the unvalidated remediation text.
        with pytest.raises(CoreAdapterError) as forged:
            asyncio.run(
                client.invoke(
                    "ksi_list_spatial_data_assets",
                    {"siteId": "forged", "workAreaId": AREA},
                )
            )
        assert forged.value.code == "AI_EGRESS_DENIED"
        with pytest.raises(CoreAdapterError) as grant:
            asyncio.run(
                client.invoke(
                    "ksi_list_spatial_data_assets",
                    {"siteId": "grant", "workAreaId": AREA},
                )
            )
        assert grant.value.code == "GRANT_REQUIRED"
        with pytest.raises(CoreAdapterError) as missing:
            asyncio.run(
                client.invoke(
                    "ksi_get_spatial_data_asset",
                    {"siteId": "gone", "workAreaId": AREA, "assetRef": ASSET},
                )
            )
        assert missing.value.code == "NOT_FOUND"
    finally:
        core.close()


def test_response_too_large_token_rotation_and_redirect() -> None:
    from ksi_spatial_data_mcp.core_client import CoreAdapterError

    seen_tokens: list[str] = []

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        seen_tokens.append(headers.get("Authorization", ""))
        if "/sites/redirect-me/" in path:
            return 302, {"Location": "/elsewhere"}, b""
        if "/sites/big/" in path:
            items = [_asset_view() for _ in range(4)]
            return json_response({"items": items})
        return json_response({"items": []})

    core = LoopbackCore(responder).start()
    try:
        small = _client(core.origin, maxStructuredResponseBytes=1024)
        with pytest.raises(CoreAdapterError, match="CORE_RESPONSE_TOO_LARGE"):
            asyncio.run(
                small.invoke(
                    "ksi_list_spatial_data_assets",
                    {"siteId": "big", "workAreaId": AREA},
                )
            )
        with pytest.raises(CoreAdapterError) as redirect:
            asyncio.run(
                small.invoke(
                    "ksi_list_spatial_data_assets",
                    {"siteId": "redirect-me", "workAreaId": AREA},
                )
            )
        assert redirect.value.code == "CORE_UNAVAILABLE"

        from ksi_spatial_data_mcp.config import AdapterConfig

        token = fixture.write_token("rotation-token", "rotation-first")
        path = fixture.write_adapter_config(
            f"rotation-{time.time_ns()}.json",
            origin=core.origin,
            token_path=token,
        )
        from ksi_spatial_data_mcp.core_client import CoreSpatialDataClient

        rotating = CoreSpatialDataClient(AdapterConfig.from_file(path))
        asyncio.run(
            rotating.invoke(
                "ksi_list_spatial_data_assets",
                {"siteId": SITE, "workAreaId": AREA},
            )
        )
        token.write_text("rotation-second\n", encoding="ascii")
        token.chmod(0o600)
        asyncio.run(
            rotating.invoke(
                "ksi_list_spatial_data_assets",
                {"siteId": SITE, "workAreaId": AREA},
            )
        )
        assert seen_tokens[-2] == "Bearer rotation-first"
        assert seen_tokens[-1] == "Bearer rotation-second"
        token.unlink()
        with pytest.raises(CoreAdapterError, match="CONFIGURATION_UNAVAILABLE"):
            asyncio.run(
                rotating.invoke(
                    "ksi_list_spatial_data_assets",
                    {"siteId": SITE, "workAreaId": AREA},
                )
            )
    finally:
        core.close()


def test_request_budget_concurrency_deadline_and_cleanup() -> None:
    from ksi_spatial_data_mcp.core_client import CoreAdapterError

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        return json_response({"items": []})

    core = LoopbackCore(responder).start()
    try:
        tiny = _client(core.origin, maxRequestBytes=32)
        with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
            asyncio.run(
                tiny.invoke(
                    "ksi_list_spatial_data_assets",
                    {"siteId": SITE, "workAreaId": AREA},
                )
            )

        limited = _client(core.origin, maxConcurrentCalls=1, callDeadlineSeconds=0.5)

        async def contention() -> None:
            # Hold the single slot: a queued call must fail closed within its
            # deadline instead of reserving work forever.
            await limited._semaphore.acquire()
            try:
                with pytest.raises(CoreAdapterError, match="CONCURRENCY_LIMIT_EXCEEDED"):
                    await limited.invoke(
                        "ksi_list_spatial_data_assets",
                        {"siteId": SITE, "workAreaId": AREA},
                    )
                # Cancelled queued work must not leak the reservation either.
                pending = asyncio.create_task(
                    limited.invoke(
                        "ksi_list_spatial_data_assets",
                        {"siteId": SITE, "workAreaId": AREA},
                    )
                )
                await asyncio.sleep(0.1)
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            finally:
                limited._semaphore.release()

        asyncio.run(contention())
        # Slot released: a later call succeeds.
        done = asyncio.run(
            limited.invoke(
                "ksi_list_spatial_data_assets",
                {"siteId": SITE, "workAreaId": AREA},
            )
        )
        assert done["items"] == []
    finally:
        core.close()


def test_queued_get_returns_wrapper_with_null_reference() -> None:
    """A queued job without a receipt succeeds with fileReference null."""

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        return json_response(_job_view())

    core = LoopbackCore(responder).start()
    try:
        result = asyncio.run(
            _client(core.origin).invoke(
                "ksi_get_spatial_data_request",
                {"siteId": SITE, "workAreaId": AREA, "jobId": JOB},
            )
        )
        assert result["job"]["jobId"] == JOB
        assert result["job"]["executionState"] == "QUEUED"
        assert result["fileReference"] is None
    finally:
        core.close()


def test_retained_unavailable_history_returns_null_reference() -> None:
    """COMPLETED+UNAVAILABLE history keeps its metadata with no file promise."""
    view = _job_view("COMPLETED", "UNAVAILABLE", receipt=_completed_receipt())

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        return json_response(view)

    core = LoopbackCore(responder).start()
    try:
        result = asyncio.run(
            _client(core.origin).invoke(
                "ksi_get_spatial_data_request",
                {"siteId": SITE, "workAreaId": AREA, "jobId": JOB},
            )
        )
        assert result["job"]["availability"] == "UNAVAILABLE"
        assert result["job"]["receipt"]["outputSha256"] == _digest("9")
        assert result["fileReference"] is None
    finally:
        core.close()


def test_canceled_and_expired_have_no_reference() -> None:
    views = [
        _job_view("CANCELED", "UNAVAILABLE"),
        _job_view("EXPIRED", "RETENTION_EXPIRED"),
    ]

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        return json_response(views.pop(0))

    core = LoopbackCore(responder).start()
    try:
        for _ in range(2):
            result = asyncio.run(
                _client(core.origin).invoke(
                    "ksi_get_spatial_data_request",
                    {"siteId": SITE, "workAreaId": AREA, "jobId": JOB},
                )
            )
            assert result["fileReference"] is None
    finally:
        core.close()


def test_idempotency_key_over_identifier_budget_rejected_before_transport() -> None:
    from ksi_spatial_data_mcp.core_client import CoreAdapterError

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        return json_response(_job_view(), status=201)

    core = LoopbackCore(responder).start()
    try:
        client = _client(core.origin, maxIdentifierBytes=72)
        with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
            asyncio.run(
                client.invoke(
                    "ksi_create_spatial_data_request",
                    {
                        "siteId": SITE,
                        "workAreaId": AREA,
                        "assetRef": ASSET,
                        "requestedBounds": [0.0, 0.0, 4.0, 4.0],
                        "observedCrsDigest": _digest(),
                        "idempotencyKey": "k" * 100,
                    },
                )
            )
        assert core.requests == []
    finally:
        core.close()


def test_non_hex_digest_rejected_before_transport() -> None:
    from ksi_spatial_data_mcp.core_client import CoreAdapterError, validate_tool_arguments

    with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
        validate_tool_arguments(
            "ksi_create_spatial_data_request",
            {
                "siteId": SITE,
                "workAreaId": AREA,
                "assetRef": ASSET,
                "requestedBounds": [0.0, 0.0, 4.0, 4.0],
                "observedCrsDigest": "sha256:" + "Z" * 64,
                "idempotencyKey": "key-a",
            },
        )


def test_bearer_scheme_refused_but_safe_identifier_allowed() -> None:
    from ksi_spatial_data_mcp.core_client import CoreAdapterError, validate_tool_arguments

    parsed = validate_tool_arguments(
        "ksi_list_spatial_data_assets",
        {"siteId": "site-bearer-a", "workAreaId": AREA},
    )
    assert parsed.model_dump(by_alias=True)["siteId"] == "site-bearer-a"
    with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
        validate_tool_arguments(
            "ksi_list_spatial_data_assets",
            {"siteId": SITE, "workAreaId": AREA, "cursor": "Bearer abc"},
        )


def test_missing_content_type_refused() -> None:
    from ksi_spatial_data_mcp.core_client import CoreAdapterError

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        return 200, {}, b'{"items":[]}'

    core = LoopbackCore(responder).start()
    try:
        with pytest.raises(CoreAdapterError, match="INVALID_CORE_RESPONSE"):
            asyncio.run(
                _client(core.origin).invoke(
                    "ksi_list_spatial_data_assets",
                    {"siteId": SITE, "workAreaId": AREA},
                )
            )
    finally:
        core.close()


def test_cancel_during_stalled_call_cleans_up() -> None:
    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        time.sleep(10)
        return json_response({"items": []})

    core = LoopbackCore(responder).start()
    try:
        client = _client(core.origin, callDeadlineSeconds=30.0, readTimeoutSeconds=30.0)

        async def scenario() -> None:
            pending = asyncio.create_task(
                client.invoke(
                    "ksi_list_spatial_data_assets",
                    {"siteId": SITE, "workAreaId": AREA},
                )
            )
            await asyncio.sleep(0.5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(pending, timeout=5.0)

        asyncio.run(scenario())
        done = asyncio.run(
            client.invoke(
                "ksi_list_spatial_data_assets",
                {"siteId": SITE, "workAreaId": AREA},
            )
        )
        assert done["items"] == []
    finally:
        core.close()


def test_unexpected_transport_error_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from ksi_spatial_data_mcp.config import AdapterConfig
    from ksi_spatial_data_mcp.core_client import CoreAdapterError

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        return json_response({"items": []})

    core = LoopbackCore(responder).start()
    try:
        client = _client(core.origin)

        def broken_factory(self: AdapterConfig) -> Any:
            raise RuntimeError("synthetic-transport-failure")

        monkeypatch.setattr(AdapterConfig, "new_http_client", broken_factory)
        with pytest.raises(CoreAdapterError) as raised:
            asyncio.run(
                client.invoke(
                    "ksi_list_spatial_data_assets",
                    {"siteId": SITE, "workAreaId": AREA},
                )
            )
        assert raised.value.code == "CORE_UNAVAILABLE"
        assert "synthetic-transport-failure" not in str(raised.value)
    finally:
        core.close()


def test_nonfinite_arguments_rejected_before_transport() -> None:
    from ksi_spatial_data_mcp.core_client import CoreAdapterError, validate_tool_arguments

    with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
        validate_tool_arguments(
            "ksi_create_spatial_data_request",
            {
                "siteId": SITE,
                "workAreaId": AREA,
                "assetRef": ASSET,
                "requestedBounds": [0.0, 0.0, float("nan"), 4.0],
                "observedCrsDigest": _digest(),
                "idempotencyKey": "key-a",
            },
        )


def test_received_remediation_preserved_not_remapped() -> None:
    """A validated Core reason keeps its received remediation facts."""
    from ksi_spatial_data_mcp.core_client import CoreAdapterError
    from ksi_spatial_data_mcp.server import _error_result

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        return json_response(
            {
                "reason": "AI_EGRESS_DENIED",
                "message": "no ai rights",
                "retryable": False,
                "remediation": ["CONTACT_OPERATOR"],
            },
            status=403,
            ack=False,
        )

    core = LoopbackCore(responder).start()
    try:
        with pytest.raises(CoreAdapterError) as raised:
            asyncio.run(
                _client(core.origin).invoke(
                    "ksi_list_spatial_data_assets",
                    {"siteId": SITE, "workAreaId": AREA},
                )
            )
        assert raised.value.code == "AI_EGRESS_DENIED"
        assert tuple(raised.value.remediation) == ("CONTACT_OPERATOR",)
        envelope = _error_result(raised.value.code, raised.value.remediation)
        assert envelope.structured_content == {
            "code": "AI_EGRESS_DENIED",
            "remediation": ["CONTACT_OPERATOR"],
        }
    finally:
        core.close()


def test_remediation_pinning_matches_core_table() -> None:
    """Adapter remediation defaults stay value-identical to Core's AI table."""
    from ksi_core.domains.external.delivery.errors import ai_remediation_for
    from ksi_spatial_data_mcp.core_client import remediation_for

    for reason in (
        "AI_EGRESS_DENIED",
        "ACCESS_REVOKED",
        "ACCESS_EXPIRED",
        "GRANT_REQUIRED",
        "PROCESSING_LOCATION_DENIED",
        "NOT_READY",
        "SPATIAL_DATA_CURSOR_STALE",
        "IDEMPOTENCY_CONFLICT",
        "RETENTION_EXPIRED",
        "INVALID_REQUEST_BOUNDS",
        "RESOURCE_LIMIT_EXCEEDED",
        "OUTPUT_BYTE_LIMIT_EXCEEDED",
        "OUTPUT_PIXEL_LIMIT_EXCEEDED",
        "CONCURRENCY_LIMIT_EXCEEDED",
        "WORKSPACE_LIMIT_EXCEEDED",
    ):
        assert tuple(remediation_for(reason)) == tuple(ai_remediation_for(reason))
