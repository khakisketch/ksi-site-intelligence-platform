"""Evidence 미디어 스토리지 경계 (ADR-KSI-010 §1).

Core 는 미디어 바이트를 **중계하지 않는다**. 업로드도 열람도 짧은 수명의
presigned URL 만 발급하고, Edge/브라우저가 스토리지와 직접 주고받는다. 이
모듈은 그 경계의 두 조각을 갖는다:

1. :class:`EvidenceStorage` — Core 가 의존하는 유일한 포트. S3 호환 어댑터가
   구현체이고, 테스트는 가짜 구현으로 돈다(네트워크·컨테이너 없이).
2. 객체 키 생성·검증 — **서버가 만든다.** 클라이언트가 준 문자열을 키에
   그대로 쓰면 경로 탈출(``../``)과 타 현장 덮어쓰기가 열린다. S2 재검토가
   같은 클래스(event_key 경로 세그먼트)를 P1 으로 잡았던 사고를 반복하지 않는다.

## presigned URL 은 그 자체가 인가다

URL 을 아는 것과 권한을 가진 것이 같아지므로, 수명은 분 단위로 짧게 두고
발급 경로를 유일한 관문으로 만든다 — 발급은 **항상 권한 검사 뒤에** 온다.
스토리지는 URL 이 유효한지만 보지, 누가 쓰는지 모른다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from .identifiers import is_path_safe_identifier

# presigned URL 기본 수명. 업로드는 대용량 전송을 견뎌야 해서 열람보다 길다.
DEFAULT_UPLOAD_TTL = timedelta(minutes=15)
DEFAULT_VIEW_TTL = timedelta(minutes=5)

# 허용 MIME — 임의 타입을 그대로 스토리지에 넘기면 브라우저가 열람 URL 에서
# 스크립트로 해석할 수 있는 것(text/html·image/svg+xml)까지 들어온다.
# 증거는 사진·영상·포인트클라우드뿐이므로 allowlist 로 좁힌다.
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "video/mp4",
        "video/webm",
        "application/octet-stream",  # las/laz·독자 포맷 — 브라우저가 해석하지 않는다
    }
)

_ARTIFACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class EvidenceVerdict(StrEnum):
    """Evidence 경로의 typed 거부 사유 — 문자열 메시지로 분기하지 않는다."""

    REGISTERED = "REGISTERED"
    UNKNOWN_EVENT = "UNKNOWN_EVENT"
    INVALID_ARTIFACT_ID = "INVALID_ARTIFACT_ID"
    UNSUPPORTED_CONTENT_TYPE = "UNSUPPORTED_CONTENT_TYPE"
    DUPLICATE_ARTIFACT = "DUPLICATE_ARTIFACT"
    UNKNOWN_ARTIFACT = "UNKNOWN_ARTIFACT"
    ALREADY_TOMBSTONED = "ALREADY_TOMBSTONED"


class EvidenceStorageError(Exception):
    """스토리지 접근 실패 — Core 는 이 예외를 5xx 로 번역한다.

    스토리지 장애를 '증거 없음'으로 뭉개지 않는다. 둘은 사고 조사에서 완전히
    다른 사실이고, 조용한 성공은 이 제품에서 가장 나쁜 거짓말이다.
    """


class EvidenceStorage(Protocol):
    """Core 가 의존하는 오브젝트 스토리지 포트 (ADR-KSI-010 §1).

    구현체는 S3 호환 어댑터 하나뿐이다. 엔드포인트가 현장 MinIO 인지 클라우드
    인지 **Core 는 알지 않는다** — 고객이 클라우드를 원하면 어댑터 설정만 바뀐다.
    """

    def presigned_put(self, object_key: str, *, content_type: str, ttl: timedelta) -> str:
        """업로드용 URL. 실패는 :class:`EvidenceStorageError`."""
        ...

    def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
        """열람용 URL. 실패는 :class:`EvidenceStorageError`."""
        ...

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        """Core 가 **직접** 바이트를 쓴다. 실패는 :class:`EvidenceStorageError`.

        다른 세 메서드와 성격이 다르다 — presigned URL 은 "클라이언트가 올리고
        내려받게 한다"이고 이건 "서버가 만든 산출물을 서버가 보관한다"이다. 그
        구분이 필요해진 이유는 KMZ 다: 발급 시점에만 존재하는 바이트를 서버가
        보관하지 않으면, 서버 안전상수 한 줄이 바뀌는 순간 그 이전 발급분 전량이
        재생성 불가가 되어 다운로드가 영구 409 가 된다(risk
        kmz-regeneration-determinism-timebomb — phase-2 에서 실제로 발화했다).
        클라이언트가 올려줄 수 있는 바이트가 아니므로 presigned_put 으로는 못 채운다.
        """
        ...

    def get_bytes(self, object_key: str) -> bytes:
        """Core 가 **직접** 바이트를 읽는다. 실패·부재는 :class:`EvidenceStorageError`.

        :meth:`put_bytes` 의 짝이다 — 서버가 보관한 산출물을 서버가 다시 판단에
        쓰는 경로(KMZ 다운로드가 재생성 대신 보관본을 내려줄지 정하는 자리)라,
        presigned URL 로는 성립하지 않는다. **부재도 오류다**: "없다"를 조용히
        빈 바이트로 돌려주면 호출부가 그걸 유효한 파일로 취급한다.
        """
        ...

    def delete(self, object_key: str) -> None:
        """객체 삭제(보관 정책 집행 — ADR-KSI-010 §3). 이미 없으면 성공으로 본다."""
        ...


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    """등록된 증거물 한 건.

    ``tombstoned_at`` 이 있으면 **폐기된 것**이다 — "증거가 없다"와 "정책대로
    폐기했다"는 다른 사실이라, 레코드를 지우지 않고 이 필드로 구분한다.
    """

    artifact_id: str
    event_key: str
    site_id: str
    object_key: str
    content_type: str
    registered_at: datetime
    registered_by: str
    tombstoned_at: datetime | None = None
    tombstone_reason: str | None = None

    @property
    def is_tombstoned(self) -> bool:
        return self.tombstoned_at is not None


def is_valid_artifact_id(value: str) -> bool:
    """artifact id 가 객체 키 세그먼트로 안전한지.

    ``identifiers.is_path_safe_identifier`` 와 같은 규칙이다. 별도 함수로 두는
    이유는 이 값이 URL 경로가 아니라 **객체 키**로도 쓰이기 때문 — 두 용도가
    갈라질 때 한쪽만 느슨해지는 것을 막으려면 지금 같은 규칙임을 명시해 둔다.
    """
    return _ARTIFACT_ID_PATTERN.fullmatch(value) is not None


def build_object_key(*, site_id: str, event_key: str, artifact_id: str) -> str:
    """객체 키를 **서버가** 만든다 — 클라이언트 문자열을 키에 직접 쓰지 않는다.

    구성요소 셋을 전부 재검증한다. 호출부가 이미 검증했더라도 여기서 한 번 더
    보는 이유는, 이 함수가 경로 탈출을 막는 마지막 지점이기 때문이다 — 검증을
    호출부에 미루면 새 호출부가 생길 때마다 같은 실수가 반복된다.

    ``event_key`` 는 ``{edgeDeviceId}::{eventId}`` 합성키라 ``::`` 를 포함한다.
    구성요소 각각을 검증하고 키에는 ``/`` 로 펼쳐 넣는다 — 스토리지에서
    "이 장비의 이 사건"이 디렉터리로 보이는 편이 운영에서도 낫다.
    """
    if not is_path_safe_identifier(site_id):
        raise ValueError(f"경로-안전하지 않은 siteId: {site_id!r}")
    if not is_valid_artifact_id(artifact_id):
        raise ValueError(f"경로-안전하지 않은 artifactId: {artifact_id!r}")
    device_id, separator, event_id = event_key.partition("::")
    if (
        not separator
        or not is_path_safe_identifier(device_id)
        or not is_path_safe_identifier(event_id)
    ):
        raise ValueError(f"경로-안전하지 않은 eventKey: {event_key!r}")
    return f"sites/{site_id}/events/{device_id}/{event_id}/{artifact_id}"


def expires_at(now: datetime, ttl: timedelta) -> datetime:
    """URL 만료 시각 — 호출자가 남은 시간을 계산할 수 있게 절대 시각으로 준다."""
    return now + ttl


__all__ = [
    "ALLOWED_CONTENT_TYPES",
    "DEFAULT_UPLOAD_TTL",
    "DEFAULT_VIEW_TTL",
    "EvidenceArtifact",
    "EvidenceStorage",
    "EvidenceStorageError",
    "EvidenceVerdict",
    "build_object_key",
    "expires_at",
    "is_valid_artifact_id",
]
