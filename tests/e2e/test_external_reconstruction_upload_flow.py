"""Loopback S3-shaped byte-flow evidence for external reconstruction ingress."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import boto3
import pytest
from botocore.config import Config
from ksi_core.evidence_s3 import S3EvidenceStorage


def _api_helpers() -> Any:
    path = Path(__file__).parents[1] / "contract" / "test_external_reconstruction_api.py"
    spec = importlib.util.spec_from_file_location("external_api_helpers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _LoopbackS3Server:
    """Minimal S3-shaped fixture: it verifies bytes/checksum, not AWS signatures."""

    def __init__(self, bucket: str) -> None:
        self.bucket = bucket
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.head_keys: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _key(self) -> str | None:
                path = unquote(urlparse(self.path).path).lstrip("/")
                bucket, separator, key = path.partition("/")
                return key if bucket == outer.bucket and separator else None

            def do_PUT(self) -> None:  # noqa: N802 -- HTTP method hook
                key = self._key()
                if key is None:
                    self.send_error(404)
                    return
                body = self.rfile.read(int(self.headers["Content-Length"]))
                checksum = self.headers.get("x-amz-checksum-sha256")
                actual = base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")
                if checksum != actual:
                    self.send_error(400, "checksum mismatch")
                    return
                outer.objects[key] = (body, self.headers["Content-Type"])
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_HEAD(self) -> None:  # noqa: N802 -- HTTP method hook
                key = self._key()
                if key is None or key not in outer.objects:
                    self.send_response(404)
                    self.send_header("x-amz-error-code", "NoSuchKey")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                outer.head_keys.append(key)
                body, content_type = outer.objects[key]
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Type", content_type)
                self.send_header(
                    "x-amz-checksum-sha256",
                    base64.b64encode(hashlib.sha256(body).digest()).decode("ascii"),
                )
                self.end_headers()

            def log_message(self, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()


def _storage(server: _LoopbackS3Server) -> S3EvidenceStorage:
    client = boto3.client(
        "s3",
        endpoint_url=server.url,
        aws_access_key_id="loopback-access-key",
        aws_secret_access_key="loopback-secret-key",
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return S3EvidenceStorage(bucket=server.bucket, client=client)


def _close_api_journals(client: Any) -> None:
    app = client.app
    app.state.external_reconstruction_store._journal.close()
    app.state.external_reconstruction_test_work_orders._journal.close()
    app.state.external_reconstruction_test_sites._journal.close()
    client.close()


@pytest.mark.parametrize(
    "submission_id",
    ["customer/run-1", "x/revisions/1", "..", "a%2Fb", "고객 실행 1"],
)
def test_real_boto3_presign_http_head_and_restart_preserve_the_authenticated_seal(
    tmp_path: Path,
    submission_id: str,
) -> None:
    """Replacing boto3/HTTP HEAD or restart replay breaks the observed-byte seal proof."""
    helpers = _api_helpers()
    server = _LoopbackS3Server(bucket="loopback-evidence")
    storage = _storage(server)
    try:
        client, _unused_storage, order_id, epoch_id = helpers._client(tmp_path, storage=storage)
        path = f"/v1/observation-work-orders/{order_id}/external-reconstruction-submissions"
        submitted = helpers._submission(
            work_order_id=order_id,
            epoch_id=epoch_id,
            submission_id=submission_id,
        )
        from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1

        submitted["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(
            submitted
        )
        registered = client.post(path, headers=helpers._headers(), json=submitted)
        assert registered.status_code == 201
        submission_ref = registered.json()["submissionRef"]
        grant_response = client.post(
            f"{path}/{submission_ref}/revisions/1/upload-grants",
            headers=helpers._headers(),
        )
        assert grant_response.status_code == 200, grant_response.text
        grant = grant_response.json()["grants"][0]
        assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in grant["uploadUrl"]
        assert "x-amz-checksum-sha256" in grant["requiredHeaders"]
        assert (
            client.post(
                f"{path}/{submission_ref}/revisions/1/seal", headers=helpers._headers()
            ).status_code
            == 422
        )

        wrong = Request(
            grant["uploadUrl"],
            data=b"wrong bytes",
            method="PUT",
            headers=grant["requiredHeaders"],
        )
        with pytest.raises(HTTPError, match="400"):
            urlopen(wrong)  # noqa: S310 -- loopback fixture URL only
        assert (
            client.post(
                f"{path}/{submission_ref}/revisions/1/seal", headers=helpers._headers()
            ).status_code
            == 422
        )

        valid = Request(
            grant["uploadUrl"],
            data=b"ortho bytes",
            method="PUT",
            headers=grant["requiredHeaders"],
        )
        with urlopen(valid) as response:  # noqa: S310 -- loopback fixture URL only
            assert response.status == 200
        sealed = client.post(
            f"{path}/{submission_ref}/revisions/1/seal", headers=helpers._headers()
        )
        assert sealed.status_code == 200, sealed.text
        sealed_body = sealed.json()
        assert server.head_keys == [grant["objectKey"]]
        assert (
            sealed_body["manifest"]["entries"][0]["observedSha256"]
            == hashlib.sha256(b"ortho bytes").hexdigest()
        )
        _close_api_journals(client)

        reopened, _unused_storage, reopened_order_id, _epoch = helpers._client(
            tmp_path, storage=storage
        )
        assert reopened_order_id == order_id
        detail = reopened.get(
            f"{path}/{submission_ref}/revisions/1",
            headers=helpers._headers(),
        )
        assert detail.status_code == 200, detail.text
        assert (
            detail.json()["submission"]["submissionDigest"]
            == sealed_body["submission"]["submissionDigest"]
        )
        assert (
            detail.json()["manifest"]["manifestDigest"] == sealed_body["manifest"]["manifestDigest"]
        )
        assert detail.json()["submission"]["submissionId"] == submission_id
        assert detail.json()["submissionRef"] == submission_ref
        _close_api_journals(reopened)
    finally:
        server.close()
