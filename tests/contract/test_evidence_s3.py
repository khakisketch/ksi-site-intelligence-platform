"""S3 호환 어댑터 계약 (ADR-KSI-010 §1).

**네트워크를 타지 않는다** — boto3 client 를 주입해 어댑터가 SDK 에 무엇을
넘기는지만 본다. 실제 MinIO 왕복은 배포 검증(HIL/스테이징) 소관이고, 여기서
잡으려는 것은 "어댑터가 계약을 어기는" 클래스다:

- ContentType 을 서명에서 빠뜨리면 라우터의 MIME allowlist 가 장식이 된다.
- 만료된 TTL 로 URL 을 내주면 발급은 성공하고 사용만 실패한다.
- SDK 예외가 그대로 새어나가면 Core 가 그걸 '증거 없음'으로 번역한다.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

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
        return f"https://s3.invalid/{Params['Key']}?op={operation}&exp={ExpiresIn}"

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


def test_view_url_does_not_sign_content_type() -> None:
    client = FakeS3Client()
    _storage(client).presigned_get("sites/s1/events/d1/e1/clip", ttl=timedelta(minutes=5))
    operation, params, expires = client.presign_calls[0]
    assert operation == "get_object"
    assert "ContentType" not in params
    assert expires == 300


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
    from ksi_core.evidence import EvidenceStorage

    storage: EvidenceStorage = _storage(FakeS3Client())
    assert callable(storage.presigned_put)
    assert callable(storage.presigned_get)
    assert callable(storage.delete)
