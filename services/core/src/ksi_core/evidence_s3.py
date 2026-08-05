"""S3 호환 Evidence 스토리지 어댑터 (ADR-KSI-010 §1).

:class:`ksi_core.evidence.EvidenceStorage` 포트의 **유일한 실제 구현체**다.
엔드포인트가 현장 MinIO 인지 클라우드인지 이 모듈만 알고, Core 의 나머지는
포트만 본다 — 고객이 클라우드를 원하면 여기 설정만 바뀐다.

boto3 는 **모듈 최상단에서 import 하지 않는다.** Core 는 evidence_storage 없이도
조립되고(그 경우 증거 라우트가 장착되지 않는다), 그런 배포에 S3 SDK 를 강제로
끌고 들어갈 이유가 없다. 설치는 ``ksi-core[s3]`` extra 다.

## presigned URL 은 그 자체가 인가다

수명은 분 단위이고(evidence.py 의 DEFAULT_* TTL), 발급은 항상 권한 검사 뒤에
온다. 이 어댑터는 **누가 요청했는지 모른다** — 그 판단은 라우터가 이미 끝냈다.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from .evidence import EvidenceStorageError

if TYPE_CHECKING:  # pragma: no cover - 타입 전용
    from mypy_boto3_s3.client import S3Client


class S3EvidenceStorage:
    """S3 호환 오브젝트 스토리지 어댑터.

    Args:
        bucket: 버킷 이름. 존재 여부는 여기서 확인하지 않는다 — 기동 시점의
            네트워크 왕복을 강제하면 오프라인 부팅이 막힌다(ADR-KSI-005).
            버킷이 없으면 첫 발급에서 :class:`EvidenceStorageError` 로 드러난다.
        client: 주입된 boto3 S3 client. ``None`` 이면 ``endpoint_url`` 로 만든다.
        endpoint_url: MinIO 등 S3 호환 엔드포인트. 클라우드 S3 면 ``None``.
    """

    def __init__(
        self,
        *,
        bucket: str,
        client: Any | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("bucket 이름이 비어 있다")
        self._bucket = bucket
        if client is not None:
            self._client: S3Client = client
        else:
            import boto3  # noqa: PLC0415 -- 지연 import(모듈 docstring 참조)

            self._client = boto3.client("s3", endpoint_url=endpoint_url)

    def _presign(self, operation: str, params: dict[str, Any], ttl: timedelta) -> str:
        seconds = int(ttl.total_seconds())
        if seconds <= 0:
            # 만료된 URL 을 발급하면 호출자는 "발급 성공"을 받고 사용은 실패한다 —
            # 그 조합이 가장 진단하기 어렵다.
            raise ValueError(f"ttl 은 양수여야 한다: {ttl!r}")
        try:
            url = self._client.generate_presigned_url(
                operation, Params=params, ExpiresIn=seconds
            )
        except Exception as exc:  # noqa: BLE001 -- botocore 예외 계층이 넓다(아래 주석)
            # botocore 는 자격증명 부재(NoCredentialsError)·설정 오류·네트워크를
            # 서로 다른 계층에서 던진다. 여기서 종류를 가려봐야 호출자가 할 수 있는
            # 일은 같으므로(503 으로 정직하게 실패) 하나로 묶되, 원인은 체인에 남긴다.
            raise EvidenceStorageError(
                f"presigned URL 발급 실패({operation}): {type(exc).__name__}"
            ) from exc
        return str(url)

    def presigned_put(self, object_key: str, *, content_type: str, ttl: timedelta) -> str:
        # ContentType 을 서명에 포함한다 — 포함하지 않으면 업로더가 임의 타입으로
        # 올릴 수 있어 라우터의 MIME allowlist 가 발급 시점 장식이 된다.
        return self._presign(
            "put_object",
            {"Bucket": self._bucket, "Key": object_key, "ContentType": content_type},
            ttl,
        )

    def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
        return self._presign(
            "get_object", {"Bucket": self._bucket, "Key": object_key}, ttl
        )

    def delete(self, object_key: str) -> None:
        """객체 삭제 — 이미 없으면 성공으로 본다(S3 delete_object 는 멱등이다)."""
        try:
            self._client.delete_object(Bucket=self._bucket, Key=object_key)
        except Exception as exc:  # noqa: BLE001 -- 위 _presign 과 같은 이유
            raise EvidenceStorageError(
                f"객체 삭제 실패({object_key}): {type(exc).__name__}"
            ) from exc


__all__ = ["S3EvidenceStorage"]
