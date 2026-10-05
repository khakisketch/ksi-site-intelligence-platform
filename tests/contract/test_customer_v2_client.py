"""Customer example transport/backoff regressions; loopback synthetic bytes only."""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "analysis"))
import customer_v2  # noqa: E402
from customer_v2 import CustomerHttpError, CustomerV2Client  # noqa: E402


@pytest.fixture
def server() -> Iterator[SimpleNamespace]:
    state = SimpleNamespace(requests=[], status=204, views=[], cookie=False)

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self) -> None:
            data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            state.requests.append((self.path, dict(self.headers), data))
            self.send_response(state.status)
            if state.cookie:
                self.send_header("Set-Cookie", "session=storage-secret; Path=/")
            if state.status == 307:
                self.send_header("Location", "/redirected?signature=other-secret")
            self.end_headers()
            if state.status != 204:
                self.wfile.write(b"error includes signature=do-not-expose")

        def do_GET(self) -> None:
            state.requests.append((self.path, dict(self.headers), b""))
            view = state.views.pop(0) if len(state.views) > 1 else state.views[0]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(view).encode())

        def log_message(self, *_args: object) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.origin = f"http://127.0.0.1:{httpd.server_port}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture
def client(server: SimpleNamespace) -> Iterator[CustomerV2Client]:
    with CustomerV2Client(
        server.origin, site_id="site-a", work_area_id="wa-a", token="test-only-token"
    ) as consumer:
        yield consumer


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer nope"},
        {"COOKIE": "session=nope"},
        {"Proxy-Authorization": "Basic nope"},
        {"Host": "another-origin.test"},
        {"X-Api-Key": "nope"},
        {"X-Arbitrary": "nope"},
        {"Content-Type": "text/csv", "content-type": "text/plain"},
        {"x-amz-checksum-sha256": "bad\nvalue"},
        {"x-amz-checksum-sha256": "bad\x00value"},
        {"Content-Length": "4"},
        {"Content-Length": "-1"},
        {"Content-Length": "garbage"},
    ],
)
def test_upload_rejects_unsupported_or_ambiguous_headers_before_io(
    client: CustomerV2Client, server: SimpleNamespace, headers: dict[str, str]
) -> None:
    with pytest.raises(ValueError):
        client.put_object_bytes(
            server.origin + "/object", b"abc", content_type="text/csv", required_headers=headers
        )
    assert server.requests == []


def test_upload_rejects_url_credentials_before_io(
    client: CustomerV2Client, server: SimpleNamespace
) -> None:
    url = server.origin.replace("http://", "http://user:password@") + "/object"
    with pytest.raises(ValueError):
        client.put_object_bytes(url, b"abc", content_type="text/csv")
    assert server.requests == []


def test_upload_preserves_allowlisted_content_binding(
    client: CustomerV2Client, server: SimpleNamespace
) -> None:
    client.put_object_bytes(
        server.origin + "/object?signature=synthetic",
        b"abc",
        content_type="application/octet-stream",
        required_headers={
            "content-type": "text/csv",
            "Content-Length": "3",
            "X-Amz-Checksum-Sha256": "synthetic-checksum",
        },
    )
    _, headers, data = server.requests[0]
    lowered = {key.lower(): value for key, value in headers.items()}
    assert lowered["content-type"] == "text/csv"
    assert lowered["content-length"] == "3"
    assert lowered["x-amz-checksum-sha256"] == "synthetic-checksum"
    assert "authorization" not in lowered and "cookie" not in lowered
    assert data == b"abc"


def test_storage_cookie_is_never_forwarded_on_later_upload(
    client: CustomerV2Client, server: SimpleNamespace
) -> None:
    server.cookie = True
    for _ in range(2):
        client.put_object_bytes(server.origin + "/object", b"abc", content_type="text/csv")
    assert len(server.requests) == 2
    assert all("cookie" not in {k.lower() for k in r[1]} for r in server.requests)


@pytest.mark.parametrize("status", [400, 403, 307])
def test_upload_error_is_redacted_with_artifact_context_and_no_redirect(
    client: CustomerV2Client, server: SimpleNamespace, status: int
) -> None:
    server.status = status
    with pytest.raises(CustomerHttpError) as failure:
        client.put_object_bytes(
            server.origin + "/object?signature=secret",
            b"abc",
            content_type="text/csv",
            artifact_id="artifact-1",
        )
    assert failure.value.status == status
    assert failure.value.artifact_id == "artifact-1"
    assert failure.value.path == "<granted-object-url>"
    assert "signature" not in str(failure.value)
    assert "test-only-token" not in str(failure.value)
    assert len(server.requests) == 1


def test_upload_transport_error_hides_grant_url(
    client: CustomerV2Client, server: SimpleNamespace
) -> None:
    # Only the failing external transport is substituted; request construction remains real.
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed connecting to {request.url}", request=request)

    client._objects.close()
    client._objects = httpx.Client(transport=httpx.MockTransport(fail))
    with pytest.raises(CustomerHttpError) as failure:
        client.put_object_bytes(
            server.origin + "/object?signature=secret",
            b"abc",
            content_type="text/csv",
            artifact_id="artifact-2",
        )
    assert failure.value.status == 0  # no HTTP response
    assert failure.value.artifact_id == "artifact-2"
    assert failure.value.__suppress_context__
    assert "signature" not in str(failure.value)
    assert "secret" not in str(failure.value)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(now=0.0, sleeps=[])

    def sleep(seconds: float) -> None:
        state.sleeps.append(seconds)
        state.now += seconds

    monkeypatch.setattr(
        customer_v2, "time", SimpleNamespace(monotonic=lambda: state.now, sleep=sleep)
    )
    return state


def test_poll_backoff_reduces_long_running_request_load(
    client: CustomerV2Client, server: SimpleNamespace, clock: SimpleNamespace
) -> None:
    server.views = [{"executionState": "RUNNING"}] * 6 + [{"executionState": "COMPLETED"}]
    result = client.wait_for_analysis("analysis-a", timeout_seconds=20)
    assert result["executionState"] == "COMPLETED"
    assert clock.sleeps == [0.2, 0.4, 0.8, 1.6, 2.0, 2.0]
    assert len(server.requests) == 7


def test_poll_deadline_caps_last_sleep_and_prevents_another_request(
    client: CustomerV2Client, server: SimpleNamespace, clock: SimpleNamespace
) -> None:
    server.views = [{"executionState": "RUNNING"}]
    with pytest.raises(TimeoutError):
        client.wait_for_analysis("analysis-a", timeout_seconds=0.5)
    assert clock.sleeps == [0.2, 0.3]
    assert len(server.requests) == 2


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf"), True])
def test_invalid_poll_timeout_fails_before_io(
    client: CustomerV2Client, server: SimpleNamespace, timeout: float
) -> None:
    server.views = [{"executionState": "COMPLETED"}]
    with pytest.raises(ValueError):
        client.wait_for_analysis("analysis-a", timeout_seconds=timeout)
    assert server.requests == []


@pytest.mark.parametrize(
    "view",
    [
        {"executionState": "COMPLETED"},
        {"executionState": "FAILED"},
        {"executionState": "NOT_STARTED", "suitabilityState": "BLOCKED"},
        {"executionState": "NOT_STARTED", "suitabilityState": "REMEDIATION_REQUIRED"},
        {"executionState": "NOT_STARTED", "suitabilityState": "REASSESSMENT_REQUIRED"},
    ],
)
def test_poll_returns_terminal_or_actionable_view_without_sleep(
    client: CustomerV2Client, server: SimpleNamespace, clock: SimpleNamespace, view: dict[str, str]
) -> None:
    server.views = [view]
    assert client.wait_for_analysis("analysis-a") == view
    assert clock.sleeps == []
    assert len(server.requests) == 1
