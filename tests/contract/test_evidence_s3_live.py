"""실제 S3 호환 스토리지(MinIO) 대상 Evidence 어댑터 계약 (ADR-KSI-010 §1).

``tests/contract/test_evidence_s3.py`` 는 ``FakeS3Client`` 로 **어떤 파라미터를
넘겼는지**만 확인한다. 그것으로는 presigned URL 이 실제로 동작하는지도, 서명이
무엇을 강제하는지도 알 수 없다 — 특히 이 주장은 가짜 클라이언트로 증명 불가다:

    "ContentType 을 서명에 포함한다 — 포함하지 않으면 업로더가 임의 타입으로
    올릴 수 있어 라우터의 MIME allowlist 가 발급 시점 장식이 된다."
    (``evidence_s3.presigned_put``)

allowlist 는 이 저장소의 실제 보안 통제다(``evidence.ALLOWED_CONTENT_TYPES``:
``text/html``·``image/svg+xml`` 을 막아 열람 URL 에서 스크립트가 실행되지 않게
한다). 그 통제가 서명으로 강제되는지는 **진짜 스토리지가 거부해 봐야** 안다.

## 이 파일이 확인하는 것

1. presigned PUT 으로 실제 업로드가 되고 GET 으로 같은 바이트가 돌아온다.
2. **서명된 것과 다른 Content-Type 으로 올리면 거부된다** — 위 주장의 실측.
3. 만료된 URL 은 거부된다(TTL 이 장식이 아니다).
4. ``delete`` 는 없는 객체에도 성공한다(멱등).
5. 없는 버킷은 발급이 아니라 **사용** 시점에 드러난다(기동 시 왕복 없음 —
   ADR-KSI-005 오프라인 부팅).

## 돌리는 법

    docker run -d --name ksi-minio -p 127.0.0.1:9190:9000 \\
      -e MINIO_ROOT_USER=ksitest -e MINIO_ROOT_PASSWORD=ksitest12345 \\
      minio/minio server /data
    KSI_S3_ENDPOINT=http://127.0.0.1:9190 KSI_S3_KEY=ksitest \\
      KSI_S3_SECRET=ksitest12345 uv run pytest tests/contract/test_evidence_s3_live.py

환경변수가 없으면 **skip** 한다 — CI 기본 경로를 컨테이너에 묶지 않는다. 대신
skip 사유에 "확인되지 않았다"를 적어, 초록불이 확인으로 읽히지 않게 한다.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import uuid as uuid_mod
from datetime import timedelta

import httpx
import pytest
from ksi_core.evidence import ALLOWED_CONTENT_TYPES, EvidenceStorageError
from ksi_core.evidence_s3 import S3EvidenceStorage

_ENDPOINT = os.environ.get("KSI_S3_ENDPOINT", "").rstrip("/")
_KEY = os.environ.get("KSI_S3_KEY", "")
_SECRET = os.environ.get("KSI_S3_SECRET", "")

pytestmark = pytest.mark.skipif(
    not (_ENDPOINT and _KEY and _SECRET),
    reason=(
        "KSI_S3_ENDPOINT/KEY/SECRET 미설정 — presigned URL 이 실제로 동작하는지,"
        " ContentType 서명이 실제로 강제되는지는 확인되지 않았다"
        " (모듈 docstring 의 docker run 참조)"
    ),
)

_BUCKET = "ksi-evidence-live"


@pytest.fixture(scope="module")
def s3_client() -> object:
    boto3 = pytest.importorskip("boto3")
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=_ENDPOINT,
        aws_access_key_id=_KEY,
        aws_secret_access_key=_SECRET,
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    )
    with contextlib.suppress(Exception):  # 이미 있으면 그대로 쓴다
        client.create_bucket(Bucket=_BUCKET)
    return client


@pytest.fixture
def storage(s3_client: object) -> S3EvidenceStorage:
    return S3EvidenceStorage(bucket=_BUCKET, client=s3_client)


def _key() -> str:
    return f"sites/site-live/events/dev-1/evt-1/{uuid_mod.uuid4().hex}.jpg"


def test_presigned_put_then_get_round_trips_the_bytes(
    storage: S3EvidenceStorage,
) -> None:
    """[기본] 발급한 URL 로 실제 업로드·열람이 된다."""
    key = _key()
    payload = b"\xff\xd8\xff\xe0 KSI evidence bytes"

    put_url = storage.presigned_put(
        key, content_type="image/jpeg", ttl=timedelta(minutes=5)
    )
    put = httpx.put(put_url, content=payload, headers={"Content-Type": "image/jpeg"})
    assert put.status_code == 200, put.text

    get_url = storage.presigned_get(key, ttl=timedelta(minutes=5))
    got = httpx.get(get_url)
    assert got.status_code == 200
    assert got.content == payload
    assert got.headers["content-type"] == "image/jpeg"


def test_digest_bound_put_rejects_different_bytes_at_storage(
    storage: S3EvidenceStorage,
) -> None:
    """[핵심] Edge가 주장한 sha256와 다른 본문은 스토리지가 받아서는 안 된다.

    가짜 SDK 테스트는 ``ChecksumSHA256`` 파라미터가 전달됐다는 사실까지만
    보장한다. 이 실기동 테스트는 presigned capability의 헤더와 실제 PUT body가
    불일치할 때 S3 호환 스토리지가 거부하는지를 확인한다.
    """
    payload = b"checksum-bound evidence"
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    good_key = _key()
    good = storage.presigned_put_bound_digest(
        good_key,
        content_type="image/jpeg",
        content_digest=digest,
        ttl=timedelta(minutes=5),
    )
    good_response = httpx.put(good.upload_url, content=payload, headers=good.required_headers)
    assert good_response.status_code == 200, good_response.text

    forged_key = _key()
    forged = storage.presigned_put_bound_digest(
        forged_key,
        content_type="image/jpeg",
        content_digest=digest,
        ttl=timedelta(minutes=5),
    )
    forged_response = httpx.put(
        forged.upload_url, content=b"different bytes", headers=forged.required_headers
    )
    assert 400 <= forged_response.status_code < 500, (
        "checksum-bound presigned PUT이 다른 바이트를 수락했다 — "
        f"status={forged_response.status_code}, body={forged_response.text}"
    )
    storage.delete(good_key)
    storage.delete(forged_key)


@pytest.mark.parametrize(
    "forged_type",
    [
        # allowlist 가 막으려는 바로 그 두 타입 — 열람 URL 에서 스크립트로
        # 해석될 수 있는 것들(evidence.ALLOWED_CONTENT_TYPES 주석).
        "text/html",
        "image/svg+xml",
        "application/x-www-form-urlencoded",
    ],
)
def test_signature_actually_rejects_a_different_content_type(
    storage: S3EvidenceStorage, forged_type: str
) -> None:
    """[핵심] 서명과 다른 Content-Type 업로드가 **스토리지에서** 거부된다.

    이 단언이 ``presigned_put`` 주석의 보안 주장을 실측한다 — 가짜 클라이언트로는
    "ContentType 을 Params 에 넣었다"까지만 알 수 있고, 그게 강제되는지는 알 수
    없다. 여기가 깨지면 MIME allowlist 는 발급 시점 장식이 된다.
    """
    assert forged_type not in ALLOWED_CONTENT_TYPES
    key = _key()
    put_url = storage.presigned_put(
        key, content_type="image/jpeg", ttl=timedelta(minutes=5)
    )
    response = httpx.put(
        put_url, content=b"<script>alert(1)</script>",
        headers={"Content-Type": forged_type},
    )
    assert response.status_code == 403, (
        f"서명과 다른 Content-Type({forged_type})이 통과했다 — "
        f"MIME allowlist 가 강제되지 않는다 (status={response.status_code})"
    )


def test_omitting_the_content_type_header_is_also_rejected(
    storage: S3EvidenceStorage,
) -> None:
    """헤더를 아예 빼는 것도 서명 불일치다 — 빈틈으로 우회되지 않는다."""
    key = _key()
    put_url = storage.presigned_put(
        key, content_type="image/jpeg", ttl=timedelta(minutes=5)
    )
    # httpx 는 content 가 있으면 기본 Content-Type 을 붙이므로 명시적으로 지운다.
    response = httpx.put(put_url, content=b"x", headers={"Content-Type": ""})
    assert response.status_code == 403


def test_expired_url_is_refused(storage: S3EvidenceStorage) -> None:
    """[핵심] TTL 이 장식이 아니다 — presigned URL 은 그 자체가 인가이고 수명이 있다."""
    key = _key()
    payload = b"evidence"
    put_url = storage.presigned_put(
        key, content_type="image/jpeg", ttl=timedelta(minutes=5)
    )
    httpx.put(put_url, content=payload, headers={"Content-Type": "image/jpeg"})

    expired = storage.presigned_get(key, ttl=timedelta(seconds=1))
    import time

    time.sleep(2)
    response = httpx.get(expired)
    assert response.status_code == 403, (
        f"만료된 URL 이 아직 유효하다(status={response.status_code}) — "
        "짧은 수명이 통제로 작동하지 않는다"
    )


def test_delete_is_idempotent_against_a_real_bucket(
    storage: S3EvidenceStorage,
) -> None:
    """없는 객체 삭제도 성공이다 — 보관정책 집행이 재시도 가능해야 한다."""
    key = _key()
    put_url = storage.presigned_put(
        key, content_type="image/jpeg", ttl=timedelta(minutes=5)
    )
    httpx.put(put_url, content=b"x", headers={"Content-Type": "image/jpeg"})

    storage.delete(key)
    storage.delete(key)  # 두 번째도 예외가 아니다

    assert httpx.get(storage.presigned_get(key, ttl=timedelta(minutes=5))).status_code == 404


def test_missing_bucket_surfaces_on_use_not_on_construction(
    s3_client: object,
) -> None:
    """[수용기준] 기동 시 네트워크 왕복이 없다 — 오프라인 부팅이 막히지 않는다.

    ADR-KSI-005. 없는 버킷은 조립이 아니라 **사용** 시점에 드러난다.
    """
    storage = S3EvidenceStorage(bucket="ksi-no-such-bucket-live", client=s3_client)
    # 생성 자체는 통과한다(왕복 없음).
    url = storage.presigned_put(
        "a/b/c.jpg", content_type="image/jpeg", ttl=timedelta(minutes=1)
    )
    # presign 도 로컬 서명이라 통과한다 — 실제 사용에서 드러난다.
    response = httpx.put(url, content=b"x", headers={"Content-Type": "image/jpeg"})
    assert response.status_code == 404


def test_sdk_failure_is_translated_not_leaked(s3_client: object) -> None:
    """실제 SDK 예외도 EvidenceStorageError 로 번역된다(내부 타입이 새지 않는다)."""
    del s3_client
    boto3 = pytest.importorskip("boto3")
    broken = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:1",  # 닫힌 포트
        aws_access_key_id=_KEY,
        aws_secret_access_key=_SECRET,
        region_name="us-east-1",
    )
    storage = S3EvidenceStorage(bucket=_BUCKET, client=broken)
    with pytest.raises(EvidenceStorageError):
        storage.delete("a/b/c.jpg")
