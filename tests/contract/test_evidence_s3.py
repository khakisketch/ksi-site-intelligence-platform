"""S3 호환 어댑터 계약 (ADR-KSI-010 §1).

**네트워크를 타지 않는다** — boto3 client 를 주입해 어댑터가 SDK 에 무엇을
넘기는지만 본다. 실제 MinIO 왕복은 배포 검증(HIL/스테이징) 소관이고, 여기서
잡으려는 것은 "어댑터가 계약을 어기는" 클래스다:

- ContentType 을 서명에서 빠뜨리면 라우터의 MIME allowlist 가 장식이 된다.
- 만료된 TTL 로 URL 을 내주면 발급은 성공하고 사용만 실패한다.
- SDK 예외가 그대로 새어나가면 Core 가 그걸 '증거 없음'으로 번역한다.
"""

from __future__ import annotations

import base64
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from ksi_core.evidence import EvidenceStorageError
from ksi_core.evidence_s3 import S3EvidenceStorage


class FakeS3Client:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.presign_calls: list[tuple[str, dict[str, Any], int]] = []
        self.deleted: list[dict[str, str]] = []
        self._fail = fail

    def generate_presigned_url(
        self, operation: str, *, Params: dict[str, Any], ExpiresIn: int
    ) -> str:
        if self._fail is not None:
            raise self._fail
        self.presign_calls.append((operation, Params, ExpiresIn))
        query: dict[str, str | int] = {"op": operation, "exp": ExpiresIn}
        if "ChecksumSHA256" in Params:
            # Digest-bound capabilities must be SigV4 signed headers, not a
            # checksum-looking query parameter. This mirrors S3's wire form.
            query.update(
                {
                    "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
                    "X-Amz-SignedHeaders": "content-type;host;x-amz-checksum-sha256",
                }
            )
        return f"https://s3.invalid/{Params['Key']}?{urlencode(query)}"

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        if self._fail is not None:
            raise self._fail
        self.deleted.append({"bucket": Bucket, "key": Key})


def _storage(client: FakeS3Client) -> S3EvidenceStorage:
    return S3EvidenceStorage(bucket="ksi-evidence", client=client)


def test_upload_url_signs_content_type() -> None:
    """ContentType 이 서명에 없으면 업로더가 임의 타입으로 올릴 수 있다."""
    client = FakeS3Client()
    url = _storage(client).presigned_put(
        "sites/s1/events/d1/e1/clip", content_type="video/mp4", ttl=timedelta(minutes=15)
    )
    operation, params, expires = client.presign_calls[0]
    assert operation == "put_object"
    assert params["ContentType"] == "video/mp4"
    assert params["Bucket"] == "ksi-evidence"
    assert params["Key"] == "sites/s1/events/d1/e1/clip"
    assert expires == 900
    assert url.startswith("https://s3.invalid/")


def test_digest_bound_upload_signs_checksum_and_returns_required_headers() -> None:
    """Edge capability binds the durable hex digest to the actual S3 PUT body."""
    client = FakeS3Client()
    digest = "sha256:" + "a" * 64
    capability = _storage(client).presigned_put_bound_digest(
        "sites/s1/events/d1/e1/clip",
        content_type="video/mp4",
        content_digest=digest,
        ttl=timedelta(minutes=15),
    )
    operation, params, expires = client.presign_calls[0]
    expected_checksum = base64.b64encode(bytes.fromhex("a" * 64)).decode("ascii")
    assert operation == "put_object"
    assert params["ChecksumSHA256"] == expected_checksum
    assert params["ContentType"] == "video/mp4"
    assert expires == 900
    assert capability.upload_url.startswith("https://s3.invalid/")
    assert capability.required_headers == {
        "Content-Type": "video/mp4",
        "x-amz-checksum-sha256": expected_checksum,
    }


@pytest.mark.parametrize("digest", ["sha256:ABC", "sha256:" + "a" * 63, "not-a-digest"])
def test_digest_bound_upload_refuses_malformed_digest(digest: str) -> None:
    client = FakeS3Client()
    with pytest.raises(ValueError, match="content digest"):
        _storage(client).presigned_put_bound_digest(
            "k", content_type="image/png", content_digest=digest, ttl=timedelta(minutes=1)
        )
    assert not client.presign_calls


class SigV2LikeS3Client(FakeS3Client):
    """A deterministic injected-client regression for botocore's SigV2 fallback."""

    def generate_presigned_url(
        self, operation: str, *, Params: dict[str, Any], ExpiresIn: int
    ) -> str:
        if self._fail is not None:
            raise self._fail
        self.presign_calls.append((operation, Params, ExpiresIn))
        return (
            f"https://s3.invalid/{Params['Key']}?"
            "AWSAccessKeyId=test&Expires=123&Signature=legacy&"
            "x-amz-checksum-sha256=looks-bound-but-is-not"
        )


def test_digest_bound_upload_refuses_injected_non_sigv4_presigner() -> None:
    """A checksum query value is not a replacement for a signed checksum header."""
    with pytest.raises(EvidenceStorageError, match="requires SigV4"):
        _storage(SigV2LikeS3Client()).presigned_put_bound_digest(
            "k",
            content_type="image/png",
            content_digest="sha256:" + "a" * 64,
            ttl=timedelta(minutes=1),
        )


def test_digest_bound_upload_uses_real_sigv4_signed_headers_without_network() -> None:
    """botocore가 checksum header를 실제 SigV4 signed-header set에 넣는지 본다."""
    boto3 = pytest.importorskip("boto3")
    from botocore.config import Config

    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key",
        config=Config(signature_version="s3v4"),
    )
    capability = S3EvidenceStorage(bucket="ksi-evidence", client=client).presigned_put_bound_digest(
        "sites/s1/events/d1/e1/clip",
        content_type="video/mp4",
        content_digest="sha256:" + "a" * 64,
        ttl=timedelta(minutes=5),
    )
    query = parse_qs(urlparse(capability.upload_url).query)
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-SignedHeaders"] == ["content-type;host;x-amz-checksum-sha256"]


def test_view_url_does_not_sign_content_type() -> None:
    client = FakeS3Client()
    _storage(client).presigned_get("sites/s1/events/d1/e1/clip", ttl=timedelta(minutes=5))
    operation, params, expires = client.presign_calls[0]
    assert operation == "get_object"
    assert "ContentType" not in params
    assert expires == 300


def test_public_presigner_is_separate_from_internal_storage_client() -> None:
    """현장에 반환하는 URL이 Docker 내부 DNS를 포함하지 않도록 signer를 분리한다."""
    internal = FakeS3Client()
    public = FakeS3Client()
    storage = S3EvidenceStorage(
        bucket="ksi-evidence", client=internal, presign_client=public
    )
    storage.presigned_get("sites/s1/image.jpg", ttl=timedelta(minutes=5))
    assert internal.presign_calls == []
    assert public.presign_calls[0][0] == "get_object"


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1), timedelta(milliseconds=500)])
def test_non_positive_ttl_is_refused(ttl: timedelta) -> None:
    """발급은 성공하고 사용만 실패하는 조합이 가장 진단하기 어렵다."""
    client = FakeS3Client()
    with pytest.raises(ValueError, match="ttl"):
        _storage(client).presigned_get("k", ttl=ttl)
    assert not client.presign_calls


def test_sdk_failure_becomes_storage_error() -> None:
    """SDK 예외가 그대로 새면 Core 가 '증거 없음'으로 번역한다 — 장애는 장애여야 한다."""
    client = FakeS3Client(fail=RuntimeError("NoCredentialsError"))
    with pytest.raises(EvidenceStorageError, match="presigned URL 발급 실패"):
        _storage(client).presigned_put("k", content_type="image/png", ttl=timedelta(minutes=1))


def test_delete_passes_bucket_and_key() -> None:
    client = FakeS3Client()
    _storage(client).delete("sites/s1/events/d1/e1/clip")
    assert client.deleted == [{"bucket": "ksi-evidence", "key": "sites/s1/events/d1/e1/clip"}]


def test_delete_failure_becomes_storage_error() -> None:
    client = FakeS3Client(fail=RuntimeError("EndpointConnectionError"))
    with pytest.raises(EvidenceStorageError, match="객체 삭제 실패"):
        _storage(client).delete("k")


def test_empty_bucket_is_refused() -> None:
    with pytest.raises(ValueError, match="bucket"):
        S3EvidenceStorage(bucket="", client=FakeS3Client())


def test_adapter_satisfies_port() -> None:
    """포트 계약 — Core 는 이 세 메서드만 본다."""
    from ksi_core.evidence import DigestBoundEvidenceStorage, EvidenceStorage

    storage: EvidenceStorage = _storage(FakeS3Client())
    assert callable(storage.presigned_put)
    assert callable(storage.presigned_get)
    assert callable(storage.delete)
    bound_storage: DigestBoundEvidenceStorage = _storage(FakeS3Client())
    assert callable(bound_storage.presigned_put_bound_digest)


def test_default_constructed_client_signs_with_sigv4() -> None:
    """[회귀] client 를 안 주면(운영 경로) SigV4 로 서명하는 client 를 스스로 만든다.

    2026-08-08 에 signature_version 을 명시하지 않은 채 boto3.client 를 직접
    구성해 MinIO 가 SigV2 스타일 presigned URL 을 403 으로 거부하는 걸 실측으로
    발견했다(evidence_s3.py 참조) — 그 회귀를 이 테스트 없이는 다시 잡을 수
    없었다. 네트워크는 타지 않는다: boto3 client 구성은 로컬 동작이고,
    ``endpoint_url`` 로 향하는 실제 호출은 여기서 만들지 않는다.
    """
    storage = S3EvidenceStorage(bucket="ksi-evidence", endpoint_url="http://minio.invalid:9000")
    config = storage._client.meta.config  # noqa: SLF001
    assert config.signature_version == "s3v4"  # type: ignore[attr-defined]


def test_default_constructed_public_presigner_uses_public_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")
    storage = S3EvidenceStorage(
        bucket="ksi-evidence",
        endpoint_url="http://minio:9000",
        public_endpoint_url="https://objects.example.test",
    )
    url = storage.presigned_get("sites/s1/image.jpg", ttl=timedelta(minutes=5))
    assert url.startswith("https://objects.example.test/ksi-evidence/")
    assert "minio:9000" not in url
