"""Consumer must reject substituted transport/receipts, never overwrite local work."""

import json
from pathlib import Path

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
