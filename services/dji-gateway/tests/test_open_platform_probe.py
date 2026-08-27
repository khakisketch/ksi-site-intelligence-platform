"""Read-only Pilot 2 Open Platform probe contract (REQ-ACQ-103/INV-001/041)."""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from http.client import HTTPResponse

import pytest
from ksi_dji_gateway.open_platform_probe import build_probe_server


@contextmanager
def _probe_url() -> Iterator[str]:
    server = build_probe_server(bind="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = int(server.server_address[1])
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _open(request: urllib.request.Request) -> HTTPResponse:
    return urllib.request.urlopen(request, timeout=2)  # noqa: S310 - loopback test server.


def test_probe_serves_static_same_origin_assets_with_fail_closed_headers() -> None:
    with _probe_url() as base_url:
        with _open(urllib.request.Request(f"{base_url}/pilot-connect")) as response:
            html = response.read().decode()
            assert response.status == 200
            assert response.headers["Cache-Control"] == "no-store, max-age=0"
            csp = response.headers["Content-Security-Policy"]
            assert "connect-src 'none'" in csp
            assert "script-src 'self'" in csp
            assert "'unsafe-inline'" not in csp
            assert response.headers["Referrer-Policy"] == "no-referrer"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert 'src="/pilot-connect/probe.js"' in html
            assert 'href="/pilot-connect/probe.css"' in html

        with _open(urllib.request.Request(f"{base_url}/pilot-connect/probe.js")) as response:
            script = response.read().decode()
            assert response.status == 200
            assert "window.djiBridge" in script
            assert "callsPerformed: 0" in script
            assert "identifiersRead: 0" in script
            assert "resultsTransmitted: 0" in script


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_probe_rejects_every_mutating_http_method(method: str) -> None:
    with _probe_url() as base_url:
        request = urllib.request.Request(
            f"{base_url}/pilot-connect", data=b"{}", method=method
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            _open(request)
        assert caught.value.code == 405
        assert caught.value.headers["Allow"] == "GET, HEAD"


def test_probe_javascript_never_calls_bridge_or_exports_sensitive_values() -> None:
    with (
        _probe_url() as base_url,
        _open(urllib.request.Request(f"{base_url}/pilot-connect/probe.js")) as response,
    ):
        script = response.read().decode()

    forbidden = (
        "platformGetRemoteControllerSN",
        "platformGetAircraftSN",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "sendBeacon",
        "localStorage",
        "sessionStorage",
        "getUserMedia",
        "geolocation",
    )
    assert all(token not in script for token in forbidden)
    assert "bridge[name](" not in script
    assert "window.djiBridge." not in script


def test_probe_does_not_serve_files_or_unknown_routes() -> None:
    with _probe_url() as base_url:
        for path in ("/", "/pilot-connect/../secrets", "/.env", "/pilot-connect/result"):
            with pytest.raises(urllib.error.HTTPError) as caught:
                _open(urllib.request.Request(f"{base_url}{path}"))
            assert caught.value.code == 404


def test_probe_head_returns_headers_without_body() -> None:
    with _probe_url() as base_url:
        request = urllib.request.Request(f"{base_url}/pilot-connect", method="HEAD")
        with _open(request) as response:
            assert response.status == 200
            assert response.read() == b""
            assert int(response.headers["Content-Length"]) > 0


def test_probe_server_rejects_invalid_bind_and_port() -> None:
    with pytest.raises(ValueError, match="bind address"):
        build_probe_server(bind="  ", port=8080)
    with pytest.raises(ValueError, match="0..65535"):
        build_probe_server(bind="127.0.0.1", port=65536)
