"""Consumer must reject substituted transport/receipts, never overwrite local work."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from spatial_data_http_fixture import client_module, http_lane, mounted_transport


@pytest.mark.parametrize(
    "mutation", ["bytes", "truncated", "redirect", "compressed", "headers", "oversize"]
)
def test_http_only_consumer_rejects_wrong_file_and_removes_private_partial(
    tmp_path: Path, mutation: str
) -> None:
    with http_lane(tmp_path) as lane:
        status = lane.request_and_run()
        original = mounted_transport(lane.http)

        def response(request: httpx.Request) -> httpx.Response:
            raw = original.handle_request(request)
            data = raw.read()
            headers = dict(raw.headers)
            code = raw.status_code
            if request.url.path.endswith("/file"):
                if mutation == "bytes":
                    data = b"x" * len(data)
                elif mutation == "truncated":
                    data = data[:-1]
                elif mutation == "oversize":
                    data += b"x"
                elif mutation == "redirect":
                    code, headers = 302, {"Location": "https://foreign.invalid/private"}
                elif mutation == "compressed":
                    headers["content-encoding"] = "gzip"
                else:
                    headers["x-content-sha256"] = "sha256:" + "f" * 64
            return httpx.Response(code, headers=headers, stream=httpx.ByteStream(data))

        lane.consumer.http.close()
        lane.consumer.http = httpx.Client(
            base_url="https://core.invalid",
            headers=lane.auth,
            transport=httpx.MockTransport(response),
            follow_redirects=False,
        )
        directory = tmp_path / "consumer"
        with pytest.raises(RuntimeError):
            lane.consumer.download(status=status, output_dir=directory)
        assert not directory.exists() or list(directory.iterdir()) == []


def test_http_only_consumer_preserves_existing_local_copy_instead_of_overwriting(
    tmp_path: Path,
) -> None:
    with http_lane(tmp_path) as lane:
        status = lane.request_and_run()
        directory = tmp_path / "consumer"
        directory.mkdir(mode=0o700)
        original = directory / (status["jobId"] + ".tif")
        original.write_bytes(b"caller work")
        with pytest.raises(RuntimeError, match="DOWNLOAD_UNAVAILABLE"):
            lane.consumer.download(status=status, output_dir=directory)
        assert original.read_bytes() == b"caller work" and list(directory.iterdir()) == [original]


@pytest.mark.parametrize(
    "payload", [b'{"jobId":"a","jobId":"b"}', b'{"x":NaN}', b"\xff", b"x" * 65537]
)
def test_http_only_consumer_refuses_unbounded_duplicate_nonfinite_and_non_utf8_json(
    payload: bytes,
) -> None:
    module = client_module()
    client = module.NativeWindowClient(
        base_url="https://core.invalid",
        site_id="site",
        work_area_id="area",
        token="private-token",
        max_json_bytes=65536,
        max_file_bytes=4096,
        timeout_seconds=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=httpx.ByteStream(payload))
        ),
    )
    try:
        with pytest.raises(RuntimeError) as failure:
            client.issue(request={}, idempotency_key="one")
        assert "private-token" not in str(failure.value)
    finally:
        client.close()


def test_consumer_error_reason_cannot_reflect_untrusted_private_fields() -> None:
    module = client_module()
    client = module.NativeWindowClient(
        base_url="https://core.invalid",
        site_id="site",
        work_area_id="area",
        token="private-token",
        max_json_bytes=4096,
        max_file_bytes=4096,
        timeout_seconds=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                403, stream=httpx.ByteStream(json.dumps({"reason": "/private/key"}).encode())
            )
        ),
    )
    try:
        with pytest.raises(RuntimeError, match="REQUEST_DENIED"):
            client.issue(request={}, idempotency_key="one")
    finally:
        client.close()


@pytest.mark.parametrize("state", ["FAILED", "CANCELED", "EXPIRED"])
@pytest.mark.parametrize(
    "reason",
    [
        "/synthetic/private/path",
        "generated+untrusted-value",
        "two\nlines",
        {"private": "synthetic-marker"},
        ["synthetic-marker"],
        True,
        7,
        "A" * 81,
        None,
        "",
    ],
)
def test_consumer_terminal_status_never_reflects_untrusted_reason(
    state: str, reason: object
) -> None:
    module = client_module()
    job_id = "sdj-v1-00000000-0000-0000-0000-000000000001"
    body = {"jobId": job_id, "executionState": state, "reason": reason}
    client = module.NativeWindowClient(
        base_url="https://core.invalid",
        site_id="site",
        work_area_id="area",
        token="generated-test-only",
        max_json_bytes=4096,
        max_file_bytes=4096,
        timeout_seconds=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))
        ),
    )
    try:
        with pytest.raises(module.NativeWindowClientError) as failure:
            client.wait(job_id, timeout_seconds=1)
        assert failure.value.reason == "PREPARATION_FAILED"
        assert str(failure.value) == "PREPARATION_FAILED"
    finally:
        client.close()


@pytest.mark.parametrize("state", ["FAILED", "CANCELED", "EXPIRED"])
def test_consumer_terminal_status_preserves_safe_machine_reason(state: str) -> None:
    module = client_module()
    job_id = "sdj-v1-00000000-0000-0000-0000-000000000001"
    body = {"jobId": job_id, "executionState": state, "reason": "ACCESS_REVOKED"}
    client = module.NativeWindowClient(
        base_url="https://core.invalid",
        site_id="site",
        work_area_id="area",
        token="generated-test-only",
        max_json_bytes=4096,
        max_file_bytes=4096,
        timeout_seconds=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))
        ),
    )
    try:
        with pytest.raises(module.NativeWindowClientError, match="^ACCESS_REVOKED$"):
            client.wait(job_id, timeout_seconds=1)
    finally:
        client.close()


def test_consumer_cli_does_not_print_terminal_response_private_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = client_module()
    job_id = "sdj-v1-00000000-0000-0000-0000-000000000001"
    marker = "/synthetic/untrusted-terminal-field"
    body = {"jobId": job_id, "executionState": "FAILED", "reason": marker}
    original_client = httpx.Client

    def transported_client(**kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(
            lambda _: httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))
        )
        return original_client(**kwargs)

    monkeypatch.setattr(module.httpx, "Client", transported_client)
    token = tmp_path / "client.token"
    token.write_text("generated-test-only")
    token.chmod(0o600)
    request = tmp_path / "request.json"
    request.write_text("{}")
    output = tmp_path / "unused-output"
    code = module.main(
        [
            "--core-url",
            "https://core.invalid",
            "--site-id",
            "site",
            "--work-area-id",
            "area",
            "--token-file",
            str(token),
            "--request-file",
            str(request),
            "--idempotency-key",
            "generated-only-key",
            "--output-dir",
            str(output),
            "--max-file-bytes",
            "4096",
            "--deadline-seconds",
            "2",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert json.loads(captured.out) == {"status": "blocked", "reason": "PREPARATION_FAILED"}
    assert marker not in captured.out + captured.err
    assert "generated-test-only" not in captured.out + captured.err
    assert not output.exists()


def test_consumer_token_refuses_symlinked_parent_before_reading_secret(tmp_path: Path) -> None:
    module = client_module()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    token = private / "token"
    token.write_text("test-secret")
    token.chmod(0o600)
    linked = tmp_path / "substitution"
    linked.symlink_to(private, target_is_directory=True)
    with pytest.raises((RuntimeError, OSError)):
        module.private_token(linked / "token")
