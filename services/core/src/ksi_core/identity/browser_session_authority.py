"""Core-local durable atomic browser-session authority (unmounted).

현지 진단(동일 화면 지연 응답이 다른 계정 로그인 뒤에 이전 계정을 복원)에서
공유 브라우저-세션 권한이 없다는 사실이 확인됐다. 이 모듈은 그 빈자리를 메우는
**Core 소유의 로컬 영속 세션 권한**이다 — 장착된 HTTP 라우터가 아니라 라이브러리
클래스다. FastAPI 를 import 하지 않으며 스스로 리스너·스케줄러·기본 경로를
갖지 않는다(조립자가 명시 경로·키·기간을 준다).

보관하는 것(개별 비밀·계보 펜싱·암호화·단조 상태):

- lineage 자격(브라우저 쿠키 범위 1개 — 탭이 아니라 같은 브라우저가 공유하는
  범위)과 세션 비밀·refresh 토큰·예약 id 는 각각 **독립 비밀**이다. 파일에는
  ``sha256`` 검증자만 남고 원문은 남지 않는다. 탭들이 lineage 를 공유해도
  세대는 단조 증가하므로, 먼저 완성된 탭보다 오래된 지연 완성은 거부된다.
- 로그인 의도(nonce)는 리다이렉트 전 단계라 계정을 갖지 않고 lineage 에만
  묶인다. 검증된 주체·조직은 provider 콜백 뒤 ``complete`` 에서만 묶이며,
  호출자가 기대 계정을 알면 함께 확인한다(다르면 의도를 소진하지 않는다).
- 같은 lineage 의 새 완성은 이전 세션을 파기한다(supersession) — 지연된 A
  응답이 B 로그인 뒤에 A 권한을 되살릴 수 없다.
- 로그아웃은 세션을 파기하고 같은 lineage 의 미완성 의도를 전부 펜싱한다.
  비밀만 맞으면 만료 뒤에도 허가된다. 무효로 파기된 세션은 lineage·세대·
  비밀 검증자를 품은 자격-승인 표식을 만료·보존 기한까지 남기므로, 뒤늦은
  로그아웃도 펜싱할 수 있다(재시도 토큰은 주지 않는다). 표식 세대보다 새
  세션이 완성됐으면 펜싱하지 않고 거부한다 — 오래된 자격이 새 세대의
  의도를 펜싱할 수 없다.
- 파기 기록 상한에서는 만료·일반 기록만 치우고 살아있는 자격 표식은 절대
  버리지 않는다. 표식만 남았는데도 자리가 없으면 전체를 봉인하고 거부한다
  (재시작 뒤 purge·재시도로 복구한다 — 디스크는 커밋 전 상태 그대로다).
  재기동 정리만 표식을 버리지 않고 넘침을 허용한다 — 파일 바이트 상한과
  보존 기한이 전체를 묶고, 다음 purge·재기동이 치울 수 있는 것만 치운다.
- refresh 회전은 2단계이며 새 토큰을 **발명하지 않는다**. ``begin_refresh`` 는
  예약을 영속에 먼저 커밋한 뒤에야 보관 중인 **실제 provider 토큰**을 호출자에게
  돌려준다(호출자가 provider 에 제시용). ``complete_refresh`` 는 예약 id·세대가
  정확히 맞을 때 provider 가 돌려준 **실제 후계 토큰**을 받아 저장한다. 같은
  세션의 살아있는 예약이 있으면 새 예약은 충돌로 닫힌다(세션은 산다 — 예약
  보유자가 완료하면 된다). 만료·불일치·소실 등 어떤 모호함에서도 세션을 영구
  무효로 닫고 재시도를 허용하지 않는다 — provider 가 이미 구 토큰을 소비했을 수
  있으므로 구 토큰 replay 는 절대 없다. 예약을 남긴 채 재기동해도 그 세션은
  영구 무효다.
- 파일 전체가 AES-GCM-256 밀봉문이다 — 세션 밀봉문뿐 아니라 주체·계정·만료·
  의도 같은 메타데이터까지 인증된다. 변조·잘림·키 불일치는 기동을 거부한다.
- **롤백 고지**: AEAD 는 최신성을 증명하지 않는다. 이 파일의 오래된 복사본을
  덮어쓰는 복원은 탐지할 수 없고, 파기·회전된 자격이 되살아날 수 있다.
  백업 복원 뒤에는 전 세션 재로그인을 요구하는 운영 절차가 필요하다.
- 쓰기 전 상한: 평문 바이트·개수를 커밋 전에 검사하고 초과는 봉인으로 닫는다.
- 오류 문구는 고정 문자열뿐이라 토큰·비밀·nonce 가 예외·로그·파일에 새지
  않는다. 인증 실패는 사유를 가리지 않는 동일 문구다(열거 오라클 방지).
- ``close`` 는 이후 모든 동작을 거부한다(읽기 포함). 닫힌 인스턴스로 파일에
  쓰는 일은 없다. fork 자식은 생성자 pid 와 달라 거부된다(상속 flock 오용 방지).
- 시작 상태가 모호하면 fresh 로 넘기지 않는다 — 상태 파일이 없는데 잠금·임시
  파일이 있으면 삭제·경로 착오로 보고 기동을 거부한다. 상대 경로는 받지 않는다.
- 부모 디렉터리는 미리 존재하는 owner-private 여야 한다 — 만들지 않는다.
  검증 뒤 디렉터리 fd 를 고정(O_NOFOLLOW|O_DIRECTORY)하고 이후 모든 파일
  동작은 그 fd 기준 상대 경로로 수행해 조상 교체·심볼릭 재지정을 무력화한다.
- 경로 검증: 기존 조상·기존 파일이 owner-private 가 아니면 기동을 거부한다
  (그룹 쓰기 조상 거부 — chmod 로 고치지 않는다).

충돌·파손은 fail-closed: 잠금 경합(두 writer)·형식 위반·잘린 파일·복호 실패·
보존 상한 초과는 모두 기동을 거부하거나 현재 호출을 거부한다. 봉인된 뒤에는
재시작 전까지 모든 변경이 거부된다(``DurableJournal`` 봉인 관습 대칭).
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import errno
import fcntl
import hashlib
import hmac
import json
import logging
import os
import secrets
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ksi_core.foundation.identifiers import is_path_safe_identifier

logger = logging.getLogger("ksi_core.browser_session_authority")

_SCHEMA_VERSION = "browser-session-authority.v1"
_SNAPSHOT_AAD = b"browser-session-authority.v1:snapshot"
_MAX_FILE_BYTES = 320 * 1024
_MAX_PLAINTEXT_BYTES = 256 * 1024
_MAX_B64_NONCE_CHARS = 64
_MAX_B64_SESSION_CT_CHARS = 6_144
_MAX_LINEAGES = 256
_MAX_SESSIONS = 256
_MAX_INTENTS = 256
_MAX_REVOCATIONS = 1_024
_MAX_TEXT_LENGTH = 2_048
_MAX_TOKEN_CHARS = 4_096
_MIN_TOKEN_CHARS = 16
_SEAL_KEY_BYTES = 32
_ID_BYTES = 18
_CREDENTIAL_BYTES = 32
_REVOCATION_REASONS = frozenset(
    {
        "logout",
        "superseded",
        "lineage-forgotten",
        "session-expired",
        "refresh-reservation-pending-at-restart",
        "refresh-reservation-expired",
        "refresh-completion-uncertain",
    }
)


class SessionAuthorityError(Exception):
    """세션 권한 오류의 공통 기반 — 문구는 고정 문자열만 쓴다."""


class SessionRecoveryError(SessionAuthorityError):
    """영속 상태 오염·경합·복구 실패 — fail-closed, 기동/호출을 거부한다."""


class SessionAuthError(SessionAuthorityError):
    """인증 실패 — 사유를 가리지 않는 동일 일반 문구(열거 오라클 방지)."""


class SessionConflictError(SessionAuthorityError):
    """회전 경합·예약 불일치 — 구 토큰 관용 없이 닫는다."""


@dataclass(frozen=True, slots=True)
class LineageCredential:
    """``create_lineage`` 가 딱 한 번 반환하는 lineage 자격 — 탭 1개당 1개."""

    lineage_id: str
    lineage_secret: str

    def __repr__(self) -> str:
        return f"LineageCredential(lineage_id={self.lineage_id!r}, lineage_secret=<redacted>)"


@dataclass(frozen=True, slots=True)
class SessionCredential:
    """``complete_login`` 이 딱 한 번 반환하는 자격 — 호출자가 안전하게 전달."""

    session_id: str
    session_secret: str

    def __repr__(self) -> str:
        return f"SessionCredential(session_id={self.session_id!r}, session_secret=<redacted>)"


@dataclass(frozen=True, slots=True)
class RefreshReservation:
    """``begin_refresh`` 가 돌려주는 예약 — 보관 중인 실제 provider 토큰과
    예약 id 를 함께 담는다. 둘 다 비밀이므로 repr 에서 가린다."""

    reservation_id: str
    provider_refresh_token: str

    def __repr__(self) -> str:
        return "RefreshReservation(reservation_id=<redacted>, provider_refresh_token=<redacted>)"


@dataclass(frozen=True, slots=True)
class SessionView:
    """인증된 세션의 비밀 없는 투영 — 서비스 접근 판정에만 쓴다."""

    session_id: str
    lineage_id: str
    principal_id: str
    organization_id: str
    generation: int
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class StoreCounts:
    """비밀을 포함하지 않는 개수 스냅샷."""

    sessions: int = 0
    intents: int = 0
    reservations: int = 0
    revocations: int = 0
    lineages: int = 0


@dataclass(frozen=True, slots=True)
class PurgeReport:
    """만료 정리 결과 — 판정과 실행이 같은 명시 호출 안에서만 일어난다."""

    sessions: int = 0
    intents: int = 0
    reservations: int = 0
    revocations: int = 0
    lineages: int = 0


def generate_seal_key() -> bytes:
    """AES-GCM-256 밀봉 키 1개를 생성한다(테스트용 포함 — 운영 키는 조립자 소관)."""
    return AESGCM.generate_key(bit_length=256)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SessionAuthorityError(f"{name} 는 tz-aware datetime 이어야 한다")
    return value


def _require_account_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT_LENGTH:
        raise SessionAuthorityError(f"{name} 형식이 올바르지 않다")
    if not is_path_safe_identifier(value):
        raise SessionAuthorityError(f"{name} 형식이 올바르지 않다")
    return value


def _require_token_text(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not (_MIN_TOKEN_CHARS <= len(value) <= _MAX_TOKEN_CHARS)
        or not value.isascii()
    ):
        raise SessionAuthorityError(f"{name} 형식이 올바르지 않다")
    return value


def _b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64decode(value: object, name: str, *, max_chars: int) -> bytes:
    """base64 복호 — 호출자가 허용 길이를 명시한다(전역 상한 하나로 스냅샷·
    장기 토큰 밀봉문을 재단하지 않는다)."""
    if not isinstance(value, str) or len(value) > max_chars:
        raise SessionRecoveryError(f"{name} 형식이 올바르지 않다")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SessionRecoveryError(f"{name} 형식이 올바르지 않다") from exc


def _b64_nonce(value: object, name: str) -> bytes:
    """12바이트 nonce 복호 — 허용 길이를 한곳에 둔다."""
    return _b64decode(value, name, max_chars=_MAX_B64_NONCE_CHARS)


def _b64_session_ct(value: object, name: str) -> bytes:
    """세션 밀봉문 복호 — 최대 토큰 한도까지만 허용한다."""
    return _b64decode(value, name, max_chars=_MAX_B64_SESSION_CT_CHARS)


def _parse_instant(value: object, name: str) -> datetime:
    if not isinstance(value, str) or len(value) > _MAX_TEXT_LENGTH:
        raise SessionRecoveryError(f"{name} 형식이 올바르지 않다")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SessionRecoveryError(f"{name} 형식이 올바르지 않다") from exc
    if parsed.tzinfo is None:
        raise SessionRecoveryError(f"{name} 형식이 올바르지 않다")
    return parsed


def _require_digest(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise SessionRecoveryError(f"{name} 형식이 올바르지 않다")
    return value


def _require_generation(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SessionRecoveryError(f"{name} 형식이 올바르지 않다")
    return value


def _fd_name_exists(dir_fd: int, name: str) -> bool:
    """고정 디렉터리 기준 존재 확인 — 조상 교체와 무관하게 고정 fd 를 본다."""
    try:
        os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise SessionRecoveryError("세션 저장소 조회 실패") from exc
    return True


def _check_pinned_dir(fd: int, euid: int, *, strict: bool) -> None:
    """고정된 디렉터리 fd 를 fstat 으로 검증한다 — 경로 문자열이 아니라
    실제 열린 디렉터리를 본다(고정 뒤 조상 교체와 무관하다).

    중간 조상은 euid·root 소유에 스티키 없는 쓰기만 거부하고, 최종 부모
    디렉터리는 euid 소유·그룹/타인 권한 없음(strict)을 요구한다.
    """
    try:
        status = os.fstat(fd)
    except OSError as exc:
        raise SessionRecoveryError("고정된 디렉터리 조회 실패") from exc
    if not stat.S_ISDIR(status.st_mode):
        raise SessionRecoveryError("고정된 디렉터리가 아니다 — fail-closed")
    if strict:
        if status.st_uid != euid or (status.st_mode & 0o077):
            raise SessionRecoveryError("부모 디렉터리가 owner-private 가 아니다 — fail-closed")
        return
    if status.st_uid != euid and status.st_uid != 0:
        raise SessionRecoveryError("세션 저장소 경로 소유자가 올바르지 않다 — fail-closed")
    if (status.st_mode & 0o022) and not (status.st_mode & stat.S_ISVTX):
        # 그룹·타인 쓰기 조상은 sticky 없이는 교체 공격에 열린다(775 계열).
        # sticky(/tmp 1777)는 소유자 외 교체를 막으므로 허용한다.
        raise SessionRecoveryError("세션 저장소 경로에 쓰기 가능 조상이 있다 — fail-closed")


def _open_pinned_child(name: str, dir_fd: int) -> int:
    """고정 디렉터리 아래 구성 요소 1개를 no-follow 로 열어 고정한다.

    심볼릭 링크(조상·최종 불문)는 ELOOP 로 거부한다 — 검사와 사용이 같은
    호출이라 교체 race 가 없다.
    """
    try:
        return os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise SessionRecoveryError("경로에 심볼릭 링크가 있다 — fail-closed") from exc
        raise SessionRecoveryError("세션 저장소 디렉터리 고정 실패") from exc


class LocalSessionAuthority:
    """단일 writer 로컬 세션 권한 — ``open`` 경로 1개당 인스턴스 1개( flock 강제).

    프로세스 안의 스레드 경합은 인스턴스 잠금으로 직렬화하므로, 같은 구
    refresh 의 동시 예약은 정확히 하나만 열린다. ``close`` 뒤에는 읽기 포함
    모든 동작이 거부된다.
    """

    _dir_fd: int | None
    _name: str
    _lock_name: str
    _tmp_name: str
    _seal_key: bytes
    _session_ttl: timedelta
    _intent_ttl: timedelta
    _retention: timedelta
    _reservation_ttl: timedelta
    _mutex: threading.Lock
    _sealed_reason: str | None
    _closed: bool
    _lock_fd: int | None
    _creator_pid: int
    _lock_preexisted: bool
    _tmp_preexisted: bool
    _lineages: dict[str, dict[str, Any]]
    _sessions: dict[str, dict[str, Any]]
    _intents: dict[str, dict[str, Any]]
    _reservations: dict[str, dict[str, Any]]
    _revocations: dict[str, dict[str, Any]]

    def __init__(self) -> None:  # pragma: no cover - 직접 생성 금지, open() 사용
        raise SessionAuthorityError("LocalSessionAuthority.open() 으로만 생성한다")

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        seal_key: bytes,
        session_ttl: timedelta,
        intent_ttl: timedelta,
        retention: timedelta,
        refresh_reservation_ttl: timedelta,
        now: datetime,
    ) -> LocalSessionAuthority:
        """영속 파일을 열고 스냅샷 전체를 복호·검증한다 — 오염·잘림·키 불일치는
        기동을 거부한다. 미완료 refresh 예약이 남아 있으면 그 세션을 영구
        무효로 정리한 뒤 기동한다(모호함은 살리지 않는다).

        ``now`` 는 호출자가 보증하는 신뢰 시각이다 — 파일 mtime 을 시각으로
        쓰지 않는다(mtime 은 위조·복원될 수 있다). 재기동 정리·파기 기록의
        보존 판정은 모두 이 시각 기준이며, 미완료 예약의 파기 표식도 이
        시각으로 기록된다. 경로 조상은 구성 요소별 no-follow 디렉터리 fd로
        열고, 최종 파일과 잠금 파일도 고정 fd 기준으로 검증한다.
        """
        if not isinstance(path, Path):
            raise SessionAuthorityError("세션 상태 경로는 Path 로 준다")
        if not path.is_absolute():
            # 상대 경로는 호출자의 cwd 에 따라 다른 파일을 가리킨다 — 절대 경로만 받는다.
            raise SessionAuthorityError("세션 상태 경로는 절대 경로로 준다")
        _require_aware(now, "now")
        if ".." in path.parts or not path.name:
            raise SessionRecoveryError("세션 상태 경로 형식이 올바르지 않다")
        resolved = path
        if not isinstance(seal_key, bytes) or len(seal_key) != _SEAL_KEY_BYTES:
            raise SessionAuthorityError("밀봉 키 형식이 올바르지 않다")
        for name, value in (
            ("session_ttl", session_ttl),
            ("intent_ttl", intent_ttl),
            ("retention", retention),
            ("refresh_reservation_ttl", refresh_reservation_ttl),
        ):
            if not isinstance(value, timedelta) or value <= timedelta(0):
                raise SessionAuthorityError(f"{name} 은 양의 기간이어야 한다")

        instance = cls.__new__(cls)
        instance._name = resolved.name
        instance._lock_name = resolved.with_suffix(resolved.suffix + ".lock").name
        instance._tmp_name = resolved.name + ".tmp"
        instance._seal_key = bytes(seal_key)
        instance._session_ttl = session_ttl
        instance._intent_ttl = intent_ttl
        instance._retention = retention
        instance._reservation_ttl = refresh_reservation_ttl
        instance._mutex = threading.Lock()
        instance._sealed_reason = None
        instance._closed = False
        instance._dir_fd = None
        instance._lock_fd = None
        instance._creator_pid = os.getpid()
        instance._lock_preexisted = False
        instance._tmp_preexisted = False
        instance._lineages = {}
        instance._sessions = {}
        instance._intents = {}
        instance._reservations = {}
        instance._revocations = {}

        euid = os.geteuid()
        dir_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            _check_pinned_dir(dir_fd, euid, strict=False)
            parts = resolved.parent.parts[1:]
            for index, part in enumerate(parts):
                child_fd = _open_pinned_child(part, dir_fd)
                os.close(dir_fd)
                dir_fd = child_fd
                _check_pinned_dir(dir_fd, euid, strict=index == len(parts) - 1)
            if not parts:
                _check_pinned_dir(dir_fd, euid, strict=True)
        except BaseException:
            os.close(dir_fd)
            raise
        instance._dir_fd = dir_fd
        # 시작 상태가 모호하면 fresh 로 넘기지 않는다 — 잠금·임시 파일이 있다는
        # 것은 이 경로에 이전 저장소가 있었다는 뜻이므로, 상태 파일 부재는
        # 삭제·경로 착오로 보고 기동을 거부한다.
        try:
            instance._lock_preexisted = _fd_name_exists(dir_fd, instance._lock_name)
            instance._tmp_preexisted = _fd_name_exists(dir_fd, instance._tmp_name)
            if instance._tmp_preexisted:
                raise SessionRecoveryError("세션 임시 파일이 남아 있다 — 복구 필요")
        except BaseException:
            os.close(dir_fd)
            instance._dir_fd = None
            raise
        try:
            lock_fd = os.open(
                instance._lock_name,
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
                dir_fd=dir_fd,
            )
        except OSError as exc:
            os.close(dir_fd)
            instance._dir_fd = None
            raise SessionRecoveryError("세션 잠금 파일 생성 실패") from exc
        try:
            lock_status = os.fstat(lock_fd)
        except OSError as exc:
            os.close(lock_fd)
            os.close(dir_fd)
            instance._lock_fd = None
            instance._dir_fd = None
            raise SessionRecoveryError("세션 잠금 파일 조회 실패") from exc
        if (
            not stat.S_ISREG(lock_status.st_mode)
            or lock_status.st_uid != euid
            or lock_status.st_nlink != 1
            or (lock_status.st_mode & 0o077)
        ):
            # 잠금 경로는 일반 파일만 허용한다 — 심볼릭·특수 파일·타인
            # 접근 가능 파일을 따라가지 않고 거부한다(파일을 지우지 않는다).
            os.close(lock_fd)
            os.close(dir_fd)
            instance._lock_fd = None
            instance._dir_fd = None
            raise SessionRecoveryError("세션 잠금 파일이 안전하지 않다 — fail-closed")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(lock_fd)
            os.close(dir_fd)
            instance._dir_fd = None
            raise SessionRecoveryError(
                "다른 프로세스가 세션 저장소를 소유 중 — 단일 writer 위반"
            ) from exc
        instance._lock_fd = lock_fd

        try:
            instance._replay_locked(now)
        except BaseException:
            os.close(lock_fd)
            os.close(dir_fd)
            instance._lock_fd = None
            instance._dir_fd = None
            raise
        return instance

    # -- 내부 상태 ---------------------------------------------------------

    def _check_pid(self) -> None:
        # fork 자식은 잠금 fd·뮤텍스를 상속받지만 소유자가 아니다 — 뮤텍스를
        # 잡기 전에 거부한다(잡힌 뮤텍스 뒤에서 데드락하지 않는다).
        if os.getpid() != self._creator_pid:
            raise SessionRecoveryError("fork 뒤 인스턴스 사용 거부 — fail-closed")

    def _enter_locked(self) -> None:
        # 뮤텍스 안쪽의 2차 검사 — 정상 경로에서는 위 검사와 같은 pid 다.
        if os.getpid() != self._creator_pid:
            raise SessionRecoveryError("fork 뒤 인스턴스 사용 거부 — fail-closed")
        if self._closed:
            raise SessionRecoveryError("세션 권한이 닫힘 — 닫힌 뒤 동작은 거부된다")
        if self._sealed_reason is not None:
            raise SessionRecoveryError("세션 저장소가 봉인됨 — 재시작 전까지 변경 거부")

    def _replay_locked(self, now: datetime) -> None:
        dir_fd = self._dir_fd
        if dir_fd is None:
            raise SessionRecoveryError("세션 저장소가 열려 있지 않다 — fail-closed")
        try:
            state_status = os.stat(self._name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            if self._lock_preexisted or self._tmp_preexisted:
                raise SessionRecoveryError("세션 저장소 시작 상태 모호 — fail-closed") from None
            self._persist_locked()
            return
        except OSError as exc:
            raise SessionRecoveryError("세션 상태 조회 실패") from exc
        if not stat.S_ISREG(state_status.st_mode):
            raise SessionRecoveryError("세션 상태가 일반 파일이 아니다 — fail-closed")
        if state_status.st_size > _MAX_FILE_BYTES:
            raise SessionRecoveryError("세션 상태 크기 상한 초과 — fail-closed")
        raw = self._read_state_locked()
        if len(raw) > _MAX_FILE_BYTES:
            raise SessionRecoveryError("세션 상태 크기 상한 초과 — fail-closed")
        try:
            outer = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            # 잘린 꼬리(torn tail)·손상 모두 "기록된 적 없는 상태"로 넘기지 않고
            # 기동을 거부한다 — 어느 세션이 살아있는지 추측하지 않는다.
            raise SessionRecoveryError("세션 상태 손상 — fail-closed") from exc
        if not isinstance(outer, dict):
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        if outer.get("schema_version") != _SCHEMA_VERSION:
            raise SessionRecoveryError("세션 상태 스키마 버전이 올바르지 않다")
        try:
            plaintext = AESGCM(self._seal_key).decrypt(
                _b64_nonce(outer.get("sealed_nonce"), "sealed_nonce"),
                _b64decode(outer.get("sealed_ct"), "sealed_ct", max_chars=_MAX_FILE_BYTES),
                _SNAPSHOT_AAD,
            )
        except InvalidTag as exc:
            # 변조·키 불일치 — 어느 쪽이든 스냅샷을 살리지 않는다.
            raise SessionRecoveryError("세션 스냅샷 검증 실패 — fail-closed") from exc
        try:
            document = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다") from exc
        if not isinstance(document, dict):
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")

        lineages = self._checked_list(document, "lineages")
        intents = self._checked_list(document, "intents")
        sessions = self._checked_list(document, "sessions")
        reservations = self._checked_list(document, "reservations")
        revocations = self._checked_list(document, "revocations")
        if (
            len(lineages) > _MAX_LINEAGES
            or len(sessions) > _MAX_SESSIONS
            or len(intents) > _MAX_INTENTS
            or len(reservations) > _MAX_SESSIONS
        ):
            raise SessionRecoveryError("세션 상태 개수 상한 초과 — fail-closed")
        # 파기 기록은 여기서 개수 거부하지 않는다 — 재기동 정리가 살아있는
        # 표식을 남기며 넘칠 수 있어, 그 파일을 거부하면 복구가 막힌다.
        # 대신 아래에서 치워도 되는 것만 치우고, 살아있는 표식만 남으면
        # 그대로 둔다(파일 바이트 상한과 보존 기한이 전체를 묶는다).

        loaded_lineages: dict[str, dict[str, Any]] = {}
        for entry in lineages:
            record = self._checked_lineage_entry(entry)
            if record["lineage_id"] in loaded_lineages:
                raise SessionRecoveryError("중복 lineage 기록 — fail-closed")
            loaded_lineages[record["lineage_id"]] = record

        loaded_intents: dict[str, dict[str, Any]] = {}
        for entry in intents:
            record = self._checked_intent_entry(entry)
            lineage = loaded_lineages.get(str(record["lineage_id"]))
            if lineage is None:
                raise SessionRecoveryError("주인 없는 로그인 의도 — fail-closed")
            if int(record["generation"]) > int(lineage["current_generation"]):
                raise SessionRecoveryError("의도 세대 역전 — fail-closed")
            if record["nonce_sha256"] in loaded_intents:
                raise SessionRecoveryError("중복 로그인 의도 — fail-closed")
            loaded_intents[record["nonce_sha256"]] = record

        cipher = AESGCM(self._seal_key)
        loaded_sessions: dict[str, dict[str, Any]] = {}
        for entry in sessions:
            record = self._checked_session_entry(entry)
            if loaded_lineages.get(str(record["lineage_id"])) is None:
                raise SessionRecoveryError("주인 없는 세션 — fail-closed")
            # 세션 밀봉문 복호에 실패하면 키 불일치·변조 — 세션을 살리지 않는다.
            try:
                token_bytes = cipher.decrypt(
                    _b64_nonce(record["sealed_nonce"], "sealed_nonce"),
                    _b64_session_ct(record["sealed_ct"], "sealed_ct"),
                    self._session_aad(str(record["session_id"]), int(record["generation"])),
                )
            except InvalidTag as exc:
                raise SessionRecoveryError("세션 밀봉 검증 실패 — fail-closed") from exc
            if _digest(token_bytes.decode("utf-8", errors="strict")) != record["refresh_sha256"]:
                raise SessionRecoveryError("세션 검증자 불일치 — fail-closed")
            if record["session_id"] in loaded_sessions:
                raise SessionRecoveryError("중복 세션 기록 — fail-closed")
            loaded_sessions[record["session_id"]] = record

        loaded_reservations: dict[str, dict[str, Any]] = {}
        for entry in reservations:
            record = self._checked_reservation_entry(entry)
            session = loaded_sessions.get(str(record["session_id"]))
            if session is None:
                raise SessionRecoveryError("주인 없는 refresh 예약 — fail-closed")
            if int(record["from_generation"]) != int(session["generation"]):
                raise SessionRecoveryError("예약 세대 불일치 — fail-closed")
            if record["session_id"] in loaded_reservations:
                raise SessionRecoveryError("중복 refresh 예약 — fail-closed")
            loaded_reservations[record["session_id"]] = record

        loaded_revocations: dict[str, dict[str, Any]] = {}
        for entry in revocations:
            if not isinstance(entry, dict):
                raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
            session_id = entry.get("session_id")
            revoked_at = entry.get("revoked_at")
            reason = entry.get("reason", "logout")
            if (
                not isinstance(session_id, str)
                or not is_path_safe_identifier(session_id)
                or not isinstance(revoked_at, str)
            ):
                raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
            _parse_instant(revoked_at, "revoked_at")
            if not isinstance(reason, str) or reason not in _REVOCATION_REASONS:
                raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
            marker: dict[str, Any] = {
                "session_id": session_id,
                "revoked_at": revoked_at,
                "reason": reason,
            }
            # 자격-승인 파기 표식: 넷이 함께 있을 때만 유효하고, 넷 중
            # 하나라도 있으면 넷 다 있어야 한다(부분 표식은 오염으로 본다).
            marker_keys = (
                "lineage_id",
                "lineage_generation",
                "secret_sha256",
                "session_expires_at",
            )
            marker_values = [entry.get(key) for key in marker_keys]
            if any(value is not None for value in marker_values):
                lineage_id, lineage_generation, secret_sha256, session_expires_at = marker_values
                if not isinstance(lineage_id, str) or not is_path_safe_identifier(lineage_id):
                    raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
                lineage_generation = _require_generation(lineage_generation, "lineage_generation")
                if lineage_generation < 1:
                    raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
                _require_digest(secret_sha256, "secret_sha256")
                _parse_instant(session_expires_at, "session_expires_at")
                marker["lineage_id"] = lineage_id
                marker["lineage_generation"] = lineage_generation
                marker["secret_sha256"] = secret_sha256
                marker["session_expires_at"] = session_expires_at
            if session_id in loaded_revocations:
                raise SessionRecoveryError("중복 파기 기록 — fail-closed")
            loaded_revocations[session_id] = marker

        self._lineages = loaded_lineages
        self._sessions = loaded_sessions
        self._intents = loaded_intents
        self._reservations = loaded_reservations
        self._revocations = loaded_revocations

        # 미완료 refresh 예약을 남긴 채 재기동하면 그 세션은 영구 무효다 —
        # 예약이 커밋됐는지 알 수 없으므로 구 토큰도 새 토큰도 살리지 않는다.
        # 파기 표식은 자격-승인 표식으로 남겨 로그아웃 펜싱에 쓸 수 있다.
        # 복구 경로는 표식을 버리지 않고 넘침을 허용한다 —
        # 치워도 되는 것만 치우고 살아있는 표식은 남긴다.
        if loaded_reservations:
            for session_id in sorted(loaded_reservations):
                session = self._sessions.pop(session_id, None)
                if session is not None and session_id not in self._revocations:
                    self._revocations[session_id] = {
                        "session_id": session_id,
                        "revoked_at": now.isoformat(),
                        "reason": "refresh-reservation-pending-at-restart",
                        "lineage_id": str(session["lineage_id"]),
                        "lineage_generation": int(session["lineage_generation"]),
                        "secret_sha256": str(session["secret_sha256"]),
                        "session_expires_at": str(session["expires_at"]),
                    }
            self._reservations = {}
        if loaded_reservations or self._trim_evictible_revocations_locked(now) > 0:
            self._persist_locked()

    @staticmethod
    def _checked_list(document: dict[str, Any], key: str) -> list[Any]:
        value = document.get(key)
        if not isinstance(value, list):
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        return value

    @staticmethod
    def _checked_lineage_entry(entry: Any) -> dict[str, Any]:
        if not isinstance(entry, dict):
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        lineage_id = entry.get("lineage_id")
        if not isinstance(lineage_id, str) or not is_path_safe_identifier(lineage_id):
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        _require_digest(entry.get("lineage_secret_sha256"), "lineage_secret_sha256")
        current = _require_generation(entry.get("current_generation"), "current_generation")
        completed = _require_generation(entry.get("completed_generation"), "completed_generation")
        fenced = _require_generation(entry.get("fenced_through"), "fenced_through")
        if completed > current or fenced > current:
            raise SessionRecoveryError("lineage 세대 역전 — fail-closed")
        _parse_instant(entry.get("created_at"), "created_at")
        _parse_instant(entry.get("last_activity"), "last_activity")
        return {
            "lineage_id": lineage_id,
            "lineage_secret_sha256": entry.get("lineage_secret_sha256"),
            "current_generation": current,
            "completed_generation": completed,
            "fenced_through": fenced,
            "created_at": entry.get("created_at"),
            "last_activity": entry.get("last_activity"),
        }

    @staticmethod
    def _checked_intent_entry(entry: Any) -> dict[str, Any]:
        if not isinstance(entry, dict):
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        _require_digest(entry.get("nonce_sha256"), "nonce_sha256")
        lineage_id = entry.get("lineage_id")
        if not isinstance(lineage_id, str) or not is_path_safe_identifier(lineage_id):
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        generation = _require_generation(entry.get("generation"), "generation")
        if generation < 1:
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        # 의도는 리다이렉트 전 단계라 계정을 갖지 않는다 — 검증된 주체는
        # complete 에서만 묶인다.
        _parse_instant(entry.get("created_at"), "created_at")
        _parse_instant(entry.get("expires_at"), "expires_at")
        return {
            "nonce_sha256": entry.get("nonce_sha256"),
            "lineage_id": lineage_id,
            "generation": generation,
            "created_at": entry.get("created_at"),
            "expires_at": entry.get("expires_at"),
        }

    @staticmethod
    def _checked_session_entry(entry: Any) -> dict[str, Any]:
        if not isinstance(entry, dict):
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        session_id = entry.get("session_id")
        lineage_id = entry.get("lineage_id")
        if not isinstance(session_id, str) or not is_path_safe_identifier(session_id):
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        if not isinstance(lineage_id, str) or not is_path_safe_identifier(lineage_id):
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        lineage_generation = _require_generation(
            entry.get("lineage_generation"), "lineage_generation"
        )
        if lineage_generation < 1:
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        for key in ("principal_id", "organization_id"):
            value = entry.get(key)
            if (
                not isinstance(value, str)
                or not value
                or len(value) > _MAX_TEXT_LENGTH
                or not is_path_safe_identifier(value)
            ):
                raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        _require_digest(entry.get("secret_sha256"), "secret_sha256")
        _require_digest(entry.get("refresh_sha256"), "refresh_sha256")
        _b64_nonce(entry.get("sealed_nonce"), "sealed_nonce")
        _b64_session_ct(entry.get("sealed_ct"), "sealed_ct")
        generation = _require_generation(entry.get("generation"), "generation")
        if generation < 1:
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        _parse_instant(entry.get("created_at"), "created_at")
        _parse_instant(entry.get("expires_at"), "expires_at")
        return {
            "session_id": session_id,
            "lineage_id": lineage_id,
            "lineage_generation": lineage_generation,
            "principal_id": entry.get("principal_id"),
            "organization_id": entry.get("organization_id"),
            "secret_sha256": entry.get("secret_sha256"),
            "refresh_sha256": entry.get("refresh_sha256"),
            "sealed_nonce": entry.get("sealed_nonce"),
            "sealed_ct": entry.get("sealed_ct"),
            "generation": generation,
            "created_at": entry.get("created_at"),
            "expires_at": entry.get("expires_at"),
        }

    @staticmethod
    def _checked_reservation_entry(entry: Any) -> dict[str, Any]:
        if not isinstance(entry, dict):
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        _require_digest(entry.get("reservation_sha256"), "reservation_sha256")
        session_id = entry.get("session_id")
        if not isinstance(session_id, str) or not is_path_safe_identifier(session_id):
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        from_generation = _require_generation(entry.get("from_generation"), "from_generation")
        if from_generation < 1:
            raise SessionRecoveryError("세션 상태 형식이 올바르지 않다")
        _parse_instant(entry.get("created_at"), "created_at")
        _parse_instant(entry.get("expires_at"), "expires_at")
        return {
            "reservation_sha256": entry.get("reservation_sha256"),
            "session_id": session_id,
            "from_generation": from_generation,
            "created_at": entry.get("created_at"),
            "expires_at": entry.get("expires_at"),
        }

    @staticmethod
    def _session_aad(session_id: str, generation: int) -> bytes:
        # 세션 밀봉문을 세션·세대에 묶는다 — A 세션의 밀봉문을 B 로 잘라 붙일 수 없다.
        return f"session:{session_id}:{generation}".encode()

    def _seal_session_refresh(
        self, session_id: str, generation: int, refresh_token: str
    ) -> tuple[str, str]:
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._seal_key).encrypt(
            nonce, refresh_token.encode(), self._session_aad(session_id, generation)
        )
        return _b64encode(nonce), _b64encode(ciphertext)

    def _drop_session_locked(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._reservations.pop(session_id, None)

    def _revocation_expired_locked(self, entry: dict[str, Any], now: datetime) -> bool:
        """표식 만료 판정 — 세션 만료와 보존 기한 중 늦은 쪽까지 산다."""
        horizon = _parse_instant(str(entry["revoked_at"]), "revoked_at") + self._retention
        session_expires_at = entry.get("session_expires_at")
        if session_expires_at is not None:
            horizon = max(horizon, _parse_instant(str(session_expires_at), "session_expires_at"))
        return horizon <= now

    def _invalidate_session_locked(
        self, session_id: str, reason: str, now: datetime, *, marker: bool = False
    ) -> None:
        """세션을 영구 무효로 닫는다 — 모호함 뒤 재시도를 허용하지 않는다.

        ``marker`` 가 참이면 lineage·세대·비밀 검증자·세션 만료를 품은
        자격-승인 표식을 남긴다. 표식 로그아웃은 표식 세대보다 새 세션이
        완성되지 않았을 때만 펜싱한다. 파기 기록이 가득 차서 표식을 둘 수
        없으면 전체를 봉인하고 거부한다(살아있는 표식을 버리지 않는다).
        """
        record = self._sessions.get(session_id)
        if record is None:
            return
        entry: dict[str, Any] = {
            "session_id": session_id,
            "revoked_at": now.isoformat(),
            "reason": reason,
        }
        if marker:
            entry["lineage_id"] = str(record["lineage_id"])
            entry["lineage_generation"] = int(record["lineage_generation"])
            entry["secret_sha256"] = str(record["secret_sha256"])
            entry["session_expires_at"] = str(record["expires_at"])
        self._record_revocation_locked(entry, now)
        self._drop_session_locked(session_id)

    def _read_state_locked(self) -> bytes:
        """고정 디렉터리 fd 기준 상대 경로로만 읽는다 — 조상 교체·심볼릭
        재지정과 무관하게 고정 시점의 디렉터리를 본다."""
        dir_fd = self._dir_fd
        if dir_fd is None:
            raise SessionRecoveryError("세션 저장소가 열려 있지 않다 — fail-closed")
        try:
            fd = os.open(self._name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        except OSError as exc:
            raise SessionRecoveryError("세션 상태 읽기 실패") from exc
        try:
            status = os.fstat(fd)
            if not stat.S_ISREG(status.st_mode):
                raise SessionRecoveryError("세션 상태가 일반 파일이 아니다 — fail-closed")
            if status.st_uid != os.geteuid():
                raise SessionRecoveryError("세션 상태 파일 소유자가 올바르지 않다 — fail-closed")
            if status.st_mode & 0o077:
                raise SessionRecoveryError("세션 상태 파일에 그룹·타인 권한이 있다 — fail-closed")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > _MAX_FILE_BYTES:
                    break
            return b"".join(chunks)
        except OSError as exc:
            raise SessionRecoveryError("세션 상태 읽기 실패") from exc
        finally:
            os.close(fd)

    def _atomic_write_locked(self, payload: bytes) -> None:
        """tmp 기록 + fsync + 원자 교체 + 디렉터리 fsync — 고정 fd 기준이라
        부분 쓰기를 남기지 않고 교체 대상이 바뀌지 않는다."""
        dir_fd = self._dir_fd
        if dir_fd is None:
            raise SessionRecoveryError("세션 저장소가 열려 있지 않다 — fail-closed")
        try:
            fd = os.open(
                self._tmp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=dir_fd,
            )
        except OSError as exc:
            raise SessionRecoveryError("세션 상태 임시 파일 생성 실패") from exc
        try:
            with os.fdopen(fd, "wb") as handle:
                view = memoryview(payload)
                while view:
                    written = os.write(handle.fileno(), view)
                    view = view[written:]
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(self._tmp_name, self._name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            os.fsync(dir_fd)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(self._tmp_name, dir_fd=dir_fd)
            raise

    def _persist_locked(self) -> None:
        inner = {
            "lineages": [self._lineages[key] for key in sorted(self._lineages)],
            "intents": [self._intents[key] for key in sorted(self._intents)],
            "sessions": [self._sessions[key] for key in sorted(self._sessions)],
            "reservations": [self._reservations[key] for key in sorted(self._reservations)],
            "revocations": [self._revocations[key] for key in sorted(self._revocations)],
        }
        try:
            plaintext = json.dumps(inner, sort_keys=True, separators=(",", ":")).encode()
        except (TypeError, ValueError) as exc:
            self._sealed_reason = "serialize-failure"
            raise SessionRecoveryError("세션 상태 직렬화 실패 — 봉인됨") from exc
        # 쓰기 전 상한: 평문과 최종 파일 바이트를 커밋 전에 검사한다. 어느 쪽이든
        # 초과는 봉인으로 닫는다 — 메모리·디스크가 엇갈린 채로 다음 동작을
        # 받지 않는다.
        if len(plaintext) > _MAX_PLAINTEXT_BYTES:
            self._sealed_reason = "oversize"
            raise SessionRecoveryError("세션 상태 상한 초과 — 봉인됨")
        try:
            nonce = secrets.token_bytes(12)
            ciphertext = AESGCM(self._seal_key).encrypt(nonce, plaintext, _SNAPSHOT_AAD)
            outer = {
                "schema_version": _SCHEMA_VERSION,
                "sealed_nonce": _b64encode(nonce),
                "sealed_ct": _b64encode(ciphertext),
            }
            payload = json.dumps(outer, sort_keys=True, separators=(",", ":")).encode()
            if len(payload) > _MAX_FILE_BYTES:
                self._sealed_reason = "oversize"
                raise SessionRecoveryError("세션 상태 상한 초과 — 봉인됨")
            self._atomic_write_locked(payload)
        except SessionRecoveryError:
            # 임시 파일 생성 실패를 포함한 모든 영속 실패는 봉인으로 닫는다 —
            # 메모리 변경 뒤 디스크가 뒤처진 채로 다음 동작을 받지 않는다.
            if self._sealed_reason is None:
                self._sealed_reason = "persist-failure"
            raise
        except BaseException as exc:
            # 디스크 쓰기 실패 뒤의 메모리·디스크 불일치는 봉인으로 닫는다.
            if self._sealed_reason is None:
                self._sealed_reason = "persist-failure"
            raise SessionRecoveryError("세션 상태 영속 실패 — 봉인됨") from exc

    # -- 수명주기 -----------------------------------------------------------

    def close(self) -> None:
        """writer 잠금을 내려놓고 인스턴스를 닫는다 — 이후 모든 동작이 거부된다.

        fork 자식은 상속 fd 를 닫기만 하고 LOCK_UN 하지 않는다(뮤텍스도 잡지
        않는다). 부모 잠금은 그대로 유지되고, 부모가 죽으면 커널이 fd 를 닫아
        잠금이 풀린다.
        """
        if os.getpid() != self._creator_pid:
            if self._lock_fd is not None:
                with contextlib.suppress(OSError):
                    os.close(self._lock_fd)
                self._lock_fd = None
            if self._dir_fd is not None:
                with contextlib.suppress(OSError):
                    os.close(self._dir_fd)
                self._dir_fd = None
            self._closed = True
            return
        with self._mutex:
            if self._closed:
                return
            self._closed = True
            if self._lock_fd is not None:
                try:
                    fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(self._lock_fd)
                    self._lock_fd = None
            if self._dir_fd is not None:
                try:
                    os.close(self._dir_fd)
                finally:
                    self._dir_fd = None

    def counts(self) -> StoreCounts:
        """비밀을 포함하지 않는 개수 스냅샷."""
        self._check_pid()
        with self._mutex:
            self._enter_locked()
            return StoreCounts(
                sessions=len(self._sessions),
                intents=len(self._intents),
                reservations=len(self._reservations),
                revocations=len(self._revocations),
                lineages=len(self._lineages),
            )

    # -- lineage ------------------------------------------------------------

    def create_lineage(self, *, now: datetime) -> LineageCredential:
        """브라우저 쿠키 범위 1개당 lineage 1개를 연다 — 탭이 아니라 브라우저
        공유 범위다. lineage 비밀은 독립 비밀이다."""
        _require_aware(now, "now")
        self._check_pid()
        with self._mutex:
            self._enter_locked()
            if len(self._lineages) >= _MAX_LINEAGES:
                self._reclaim_idle_lineages_locked(now)
            if len(self._lineages) >= _MAX_LINEAGES:
                raise SessionAuthorityError("lineage 상한 초과 — 나중에 다시 시도한다")
            lineage_id = "lin_" + secrets.token_urlsafe(_ID_BYTES)
            lineage_secret = secrets.token_urlsafe(_CREDENTIAL_BYTES)
            if lineage_id in self._lineages:  # pragma: no cover - 144비트 충돌
                raise SessionAuthorityError("lineage 발급 실패 — 다시 시도한다")
            self._lineages[lineage_id] = {
                "lineage_id": lineage_id,
                "lineage_secret_sha256": _digest(lineage_secret),
                "current_generation": 0,
                "completed_generation": 0,
                "fenced_through": 0,
                "created_at": now.isoformat(),
                "last_activity": now.isoformat(),
            }
            self._persist_locked()
            return LineageCredential(lineage_id=lineage_id, lineage_secret=lineage_secret)

    def forget_lineage(self, lineage_id: str, lineage_secret: str, *, now: datetime) -> None:
        """lineage 를 접는다 — 세션·의도·예약을 함께 파기한다(명시 호출만)."""
        _require_aware(now, "now")
        self._check_pid()
        with self._mutex:
            self._enter_locked()
            lineage = self._authenticated_lineage_locked(lineage_id, lineage_secret)
            for session_id in [
                key
                for key, record in self._sessions.items()
                if str(record["lineage_id"]) == str(lineage["lineage_id"])
            ]:
                self._invalidate_session_locked(session_id, "lineage-forgotten", now)
            for key in [
                key
                for key, record in self._intents.items()
                if str(record["lineage_id"]) == str(lineage["lineage_id"])
            ]:
                del self._intents[key]
            del self._lineages[str(lineage["lineage_id"])]
            self._persist_locked()

    def _authenticated_lineage_locked(self, lineage_id: str, lineage_secret: str) -> dict[str, Any]:
        lineage = self._lineages.get(lineage_id) if isinstance(lineage_id, str) else None
        if lineage is None:
            raise SessionAuthError("인증에 실패했다")
        if not isinstance(lineage_secret, str) or not hmac.compare_digest(
            str(lineage["lineage_secret_sha256"]), _digest(lineage_secret)
        ):
            raise SessionAuthError("인증에 실패했다")
        return lineage

    # -- 로그인 의도(펜싱) ----------------------------------------------------

    def begin_login(
        self,
        lineage_id: str,
        lineage_secret: str,
        *,
        now: datetime,
    ) -> str:
        """lineage 에 묶인 1회용 로그인 의도를 연다 — 리다이렉트 전 단계라
        계정을 받지 않는다. 세대는 단조 증가하며, 검증된 주체는 complete 에서만
        묶인다."""
        _require_aware(now, "now")
        self._check_pid()
        with self._mutex:
            self._enter_locked()
            lineage = self._authenticated_lineage_locked(lineage_id, lineage_secret)
            if len(self._intents) >= _MAX_INTENTS:
                self._reclaim_expired_intents_locked(now)
            if len(self._intents) >= _MAX_INTENTS:
                raise SessionAuthorityError("로그인 의도 상한 초과 — 나중에 다시 시도한다")
            generation = int(lineage["current_generation"]) + 1
            nonce = secrets.token_urlsafe(_CREDENTIAL_BYTES)
            digest = _digest(nonce)
            if digest in self._intents:  # pragma: no cover - 256비트 충돌
                raise SessionAuthorityError("로그인 의도 발급 실패 — 다시 시도한다")
            self._intents[digest] = {
                "nonce_sha256": digest,
                "lineage_id": str(lineage["lineage_id"]),
                "generation": generation,
                "created_at": now.isoformat(),
                "expires_at": (now + self._intent_ttl).isoformat(),
            }
            lineage["current_generation"] = generation
            lineage["last_activity"] = now.isoformat()
            self._persist_locked()
            return nonce

    def complete_login(
        self,
        nonce: str,
        principal_id: str,
        organization_id: str,
        refresh_token: str,
        *,
        now: datetime,
        expected_principal_id: str | None = None,
        expected_organization_id: str | None = None,
    ) -> SessionCredential:
        """의도 1개를 정확히 한 세션으로 바꾼다 — provider 콜백에서 검증된 주체를
        이때 묶는다. 오래된 세대·재사용·만료는 거부된다. 호출자가 기대 계정을
        알면 함께 주고, 검증된 계정과 다르면 의도를 소진하지 않고 거부된다.
        같은 lineage 의 이전 세션은 이때 파기된다."""
        _require_account_text(principal_id, "principal_id")
        _require_account_text(organization_id, "organization_id")
        if expected_principal_id is not None:
            _require_account_text(expected_principal_id, "expected_principal_id")
        if expected_organization_id is not None:
            _require_account_text(expected_organization_id, "expected_organization_id")
        _require_token_text(refresh_token, "refresh_token")
        _require_aware(now, "now")
        if not isinstance(nonce, str) or not nonce:
            raise SessionAuthError("인증에 실패했다")
        self._check_pid()
        with self._mutex:
            self._enter_locked()
            digest = _digest(nonce)
            record = self._intents.get(digest)
            if record is None:
                raise SessionAuthError("인증에 실패했다")
            lineage = self._lineages.get(str(record["lineage_id"]))
            if lineage is None:
                raise SessionRecoveryError("주인 없는 로그인 의도 — fail-closed")
            if (expected_principal_id is not None and expected_principal_id != principal_id) or (
                expected_organization_id is not None and expected_organization_id != organization_id
            ):
                # 호출자의 기대와 검증된 계정이 다르면 묶지 않는다. 의도는
                # 소진하지 않는다 — 정상 지연 응답의 화면 착오까지 파기하지
                # 않기 위해서다(재시도해도 같은 불일치로 닫힌다).
                raise SessionAuthError("인증에 실패했다")
            generation = int(record["generation"])
            if generation <= int(lineage["completed_generation"]) or generation <= int(
                lineage["fenced_through"]
            ):
                # 단조 펜싱: 먼저 완성·펜싱된 세대보다 오래된 지연 완성은 거부된다.
                # 다시 완성될 수 없으므로 의도를 소진한다.
                del self._intents[digest]
                self._persist_locked()
                raise SessionAuthError("인증에 실패했다")
            if _parse_instant(record["expires_at"], "expires_at") <= now:
                del self._intents[digest]
                self._persist_locked()
                raise SessionAuthError("인증에 실패했다")
            if len(self._sessions) >= _MAX_SESSIONS:
                self._reclaim_expired_sessions_locked(now)
            # 같은 lineage 대체는 제거 뒤를 투영한다 — supersession 으로 사라질
            # 자리를 상한에 미리 반영하므로, 같은 lineage 교체는 상한에서도 된다.
            superseded = sum(
                1
                for entry in self._sessions.values()
                if str(entry["lineage_id"]) == str(lineage["lineage_id"])
            )
            if len(self._sessions) - superseded >= _MAX_SESSIONS:
                raise SessionAuthorityError("세션 상한 초과 — 나중에 다시 시도한다")
            session_id = "sess_" + secrets.token_urlsafe(_ID_BYTES)
            session_secret = secrets.token_urlsafe(_CREDENTIAL_BYTES)
            refresh_generation = 1
            sealed_nonce, sealed_ct = self._seal_session_refresh(
                session_id, refresh_generation, refresh_token
            )
            stamp = now.isoformat()
            # supersession: 같은 lineage 의 이전 세션은 모두 파기된다.
            for previous_id in [
                key
                for key, entry in self._sessions.items()
                if str(entry["lineage_id"]) == str(lineage["lineage_id"])
            ]:
                self._invalidate_session_locked(previous_id, "superseded", now)
            self._sessions[session_id] = {
                "session_id": session_id,
                "lineage_id": str(lineage["lineage_id"]),
                "lineage_generation": generation,
                "principal_id": principal_id,
                "organization_id": organization_id,
                "secret_sha256": _digest(session_secret),
                "refresh_sha256": _digest(refresh_token),
                "sealed_nonce": sealed_nonce,
                "sealed_ct": sealed_ct,
                "generation": refresh_generation,
                "created_at": stamp,
                "expires_at": (now + self._session_ttl).isoformat(),
            }
            lineage["completed_generation"] = max(int(lineage["completed_generation"]), generation)
            lineage["last_activity"] = stamp
            del self._intents[digest]
            self._persist_locked()
            return SessionCredential(session_id=session_id, session_secret=session_secret)

    # -- 인증·refresh 예약·로그아웃 ---------------------------------------------

    def _authenticated_locked(
        self,
        session_id: str,
        session_secret: str,
        *,
        expected_principal_id: str | None,
        expected_organization_id: str | None,
        now: datetime,
    ) -> dict[str, Any]:
        record = self._sessions.get(session_id) if isinstance(session_id, str) else None
        if record is None:
            raise SessionAuthError("인증에 실패했다")
        if not isinstance(session_secret, str) or not hmac.compare_digest(
            str(record["secret_sha256"]), _digest(session_secret)
        ):
            # 개별 비밀: A 세션의 비밀은 B 세션의 어떤 문도 열지 않는다.
            raise SessionAuthError("인증에 실패했다")
        if _parse_instant(record["expires_at"], "expires_at") <= now:
            raise SessionAuthError("인증에 실패했다")
        if expected_principal_id is not None and not hmac.compare_digest(
            str(record["principal_id"]), expected_principal_id
        ):
            # 지연된 A 응답이 B 로그인 뒤에 덮어쓰는 경로를 여기서 끊는다 —
            # 잡은 자격이 다른 계정의 권한이 되지 않는다.
            raise SessionAuthError("인증에 실패했다")
        if expected_organization_id is not None and not hmac.compare_digest(
            str(record["organization_id"]), expected_organization_id
        ):
            raise SessionAuthError("인증에 실패했다")
        pending = self._reservations.get(str(record["session_id"]))
        if pending is not None and _parse_instant(pending["expires_at"], "expires_at") <= now:
            # 만료된 예약을 안고 직접 인증만 받는 경우도 세션을 닫는다 —
            # provider 가 구 토큰을 소비했을 수 있어 읽기라고 살리지 않는다.
            # 자격-승인 표식을 남겨 뒤늦은 로그아웃이 펜싱할 수 있다.
            key = str(record["session_id"])
            self._invalidate_session_locked(key, "refresh-reservation-expired", now, marker=True)
            self._persist_locked()
            raise SessionAuthError("인증에 실패했다")
        return record

    def authenticate(
        self,
        session_id: str,
        session_secret: str,
        *,
        expected_principal_id: str | None = None,
        expected_organization_id: str | None = None,
        now: datetime,
    ) -> SessionView:
        """세션 비밀을 확인하고 비밀 없는 투영을 돌린다.

        만료된 예약을 안고 있으면 세션을 닫고 거부한다(읽기라도 살리지 않는다 —
        provider 가 구 토큰을 소비했을 수 있다).
        """
        if expected_principal_id is not None:
            _require_account_text(expected_principal_id, "expected_principal_id")
        if expected_organization_id is not None:
            _require_account_text(expected_organization_id, "expected_organization_id")
        _require_aware(now, "now")
        self._check_pid()
        with self._mutex:
            self._enter_locked()
            record = self._authenticated_locked(
                session_id,
                session_secret,
                expected_principal_id=expected_principal_id,
                expected_organization_id=expected_organization_id,
                now=now,
            )
            return SessionView(
                session_id=str(record["session_id"]),
                lineage_id=str(record["lineage_id"]),
                principal_id=str(record["principal_id"]),
                organization_id=str(record["organization_id"]),
                generation=int(record["generation"]),
                created_at=_parse_instant(record["created_at"], "created_at"),
                expires_at=_parse_instant(record["expires_at"], "expires_at"),
            )

    def begin_refresh(
        self,
        session_id: str,
        session_secret: str,
        *,
        now: datetime,
    ) -> RefreshReservation:
        """보관 중인 실제 provider refresh 토큰을 돌려준다 — 예약을 영속에 먼저
        커밋한 뒤에야 토큰이 호출자에게 나간다(호출자가 provider 에 제시용).

        새 토큰을 발명하지 않는다. 같은 세션의 살아있는 예약이 있으면 새
        예약은 충돌로 닫힌다(세션은 산다 — 예약 보유자가 완료하면 된다).
        만료된 예약이 남아 있으면 세션을 영구 무효로 닫는다 — provider 가 이미
        구 토큰을 소비했을 수 있어, 예약을 지우고 재시도하게 두지 않는다.
        """
        _require_aware(now, "now")
        self._check_pid()
        with self._mutex:
            self._enter_locked()
            record = self._authenticated_locked(
                session_id,
                session_secret,
                expected_principal_id=None,
                expected_organization_id=None,
                now=now,
            )
            key = str(record["session_id"])
            pending = self._reservations.get(key)
            if pending is not None:
                if _parse_instant(pending["expires_at"], "expires_at") > now:
                    raise SessionConflictError(
                        "진행 중인 refresh 예약이 있다 — 완료 뒤에 다시 시도한다"
                    )
                self._invalidate_session_locked(
                    key, "refresh-reservation-expired", now, marker=True
                )
                self._persist_locked()
                raise SessionAuthError("인증에 실패했다")
            reservation_id = "r_" + secrets.token_urlsafe(_ID_BYTES)
            digest = _digest(reservation_id)
            if digest in {entry["reservation_sha256"] for entry in self._reservations.values()}:
                # pragma: no cover - 150비트 충돌
                raise SessionAuthorityError("refresh 예약 발급 실패 — 다시 시도한다")
            self._reservations[key] = {
                "reservation_sha256": digest,
                "session_id": key,
                "from_generation": int(record["generation"]),
                "created_at": now.isoformat(),
                "expires_at": (now + self._reservation_ttl).isoformat(),
            }
            try:
                provider_token = (
                    AESGCM(self._seal_key)
                    .decrypt(
                        _b64_nonce(record["sealed_nonce"], "sealed_nonce"),
                        _b64_session_ct(record["sealed_ct"], "sealed_ct"),
                        self._session_aad(key, int(record["generation"])),
                    )
                    .decode()
                )
            except (InvalidTag, UnicodeDecodeError) as exc:
                self._sealed_reason = "decrypt-failure"
                raise SessionRecoveryError("세션 밀봉 복호 실패 — 봉인됨") from exc
            lineage = self._lineages.get(str(record["lineage_id"]))
            if lineage is not None:
                lineage["last_activity"] = now.isoformat()
            self._persist_locked()
            return RefreshReservation(
                reservation_id=reservation_id, provider_refresh_token=provider_token
            )

    def complete_refresh(
        self,
        session_id: str,
        session_secret: str,
        reservation_id: str,
        new_provider_refresh_token: str,
        *,
        now: datetime,
    ) -> None:
        """provider 가 돌려준 실제 후계 토큰을 저장한다 — 예약 id·세대가 정확히
        맞을 때만 커밋하며 1회용이다.

        예약 소실·불일치·만료·세대 어긋남 등 어떤 모호함에서도 세션을 영구
        무효로 닫는다 — 성공 뒤 중복 완료의 재시도도 살리지 않는다(재로그인).
        세션이 로그아웃·대체로 사라졌으면 거부된다.
        """
        _require_token_text(new_provider_refresh_token, "new_provider_refresh_token")
        _require_aware(now, "now")
        if not isinstance(reservation_id, str) or not reservation_id:
            raise SessionAuthorityError("예약 id 형식이 올바르지 않다")
        self._check_pid()
        with self._mutex:
            self._enter_locked()
            record = self._authenticated_locked(
                session_id,
                session_secret,
                expected_principal_id=None,
                expected_organization_id=None,
                now=now,
            )
            key = str(record["session_id"])
            reservation = self._reservations.get(key)
            uncertain = (
                reservation is None
                or not hmac.compare_digest(
                    str(reservation["reservation_sha256"]), _digest(reservation_id)
                )
                or _parse_instant(reservation["expires_at"], "expires_at") <= now
                or int(reservation["from_generation"]) != int(record["generation"])
            )
            if uncertain:
                self._invalidate_session_locked(
                    key, "refresh-completion-uncertain", now, marker=True
                )
                self._persist_locked()
                raise SessionAuthError("인증에 실패했다")
            next_generation = int(record["generation"]) + 1
            sealed_nonce, sealed_ct = self._seal_session_refresh(
                key, next_generation, new_provider_refresh_token
            )
            record["generation"] = next_generation
            record["refresh_sha256"] = _digest(new_provider_refresh_token)
            record["sealed_nonce"] = sealed_nonce
            record["sealed_ct"] = sealed_ct
            del self._reservations[key]
            lineage = self._lineages.get(str(record["lineage_id"]))
            if lineage is not None:
                lineage["last_activity"] = now.isoformat()
            self._persist_locked()

    def logout(self, session_id: str, session_secret: str, *, now: datetime) -> None:
        """세션을 파기하고 같은 lineage 의 미완성 의도를 전부 펜싱한다.

        비밀만 맞으면 허가된다 — 세션 만료·예약 만료 뒤에도 파기+펜싱한다.
        세션이 이미 표식으로만 남았으면 표식의 비밀·기한·세대를 확인하고
        펜싱한 뒤 표식을 일반 파기 기록으로 격하시킨다(재펜싱 방지).
        표식 세대보다 새 세션이 완성됐으면 펜싱하지 않고 거부한다 —
        오래된 자격이 새 세대의 의도를 펜싱할 수 없다.
        """
        _require_aware(now, "now")
        self._check_pid()
        with self._mutex:
            self._enter_locked()
            record = self._sessions.get(session_id) if isinstance(session_id, str) else None
            if (
                record is not None
                and isinstance(session_secret, str)
                and hmac.compare_digest(str(record["secret_sha256"]), _digest(session_secret))
            ):
                lineage = self._lineages.get(str(record["lineage_id"]))
                if lineage is not None:
                    lineage["fenced_through"] = int(lineage["current_generation"])
                    lineage["last_activity"] = now.isoformat()
                self._invalidate_session_locked(str(record["session_id"]), "logout", now)
                self._persist_locked()
                return
            marker = self._revocations.get(session_id) if isinstance(session_id, str) else None
            if (
                marker is not None
                and isinstance(session_secret, str)
                and marker.get("lineage_id") is not None
                and marker.get("lineage_generation") is not None
                and marker.get("secret_sha256") is not None
                and hmac.compare_digest(str(marker["secret_sha256"]), _digest(session_secret))
                and not self._revocation_expired_locked(marker, now)
            ):
                lineage = self._lineages.get(str(marker["lineage_id"]))
                if lineage is None or int(lineage["completed_generation"]) > int(
                    marker["lineage_generation"]
                ):
                    # lineage 가 사라졌거나 표식보다 새 세션이 완성됐다 —
                    # 오래된 표식으로 펜싱하지 않고 거부한다.
                    raise SessionAuthError("인증에 실패했다")
                lineage["fenced_through"] = int(lineage["current_generation"])
                lineage["last_activity"] = now.isoformat()
                for consumed in (
                    "lineage_id",
                    "lineage_generation",
                    "secret_sha256",
                    "session_expires_at",
                ):
                    marker.pop(consumed, None)
                self._persist_locked()
                return
            raise SessionAuthError("인증에 실패했다")

    # -- 보존 ------------------------------------------------------------------

    def _evictible_revocation_keys_locked(self, now: datetime) -> list[str]:
        """치워도 되는 파기 기록 — 만료(보존 기한 경과) 먼저, 다음은 일반(자격
        없는) 기록 중 revoked_at 오래된 순. 살아있는 자격-승인 표식은 절대
        포함하지 않는다."""
        expired = [
            key
            for key, entry in self._revocations.items()
            if self._revocation_expired_locked(entry, now)
        ]
        expired_set = set(expired)
        ordinary = sorted(
            (
                key
                for key in self._revocations
                if "secret_sha256" not in self._revocations[key] and key not in expired_set
            ),
            key=lambda key: str(self._revocations[key]["revoked_at"]),
        )
        return expired + ordinary

    def _trim_evictible_revocations_locked(self, now: datetime) -> int:
        """치워도 되는 파기 기록만 치워 상한에 맞춘다 — 살아있는 표식은 남긴다.

        만료된 것부터, 다음은 일반 기록 중 오래된 순. 치운 개수를 돌려준다.
        """
        removed = 0
        for key in self._evictible_revocation_keys_locked(now):
            if len(self._revocations) <= _MAX_REVOCATIONS:
                break
            del self._revocations[key]
            removed += 1
        return removed

    def _purge_revocations_locked(self, now: datetime) -> int:
        """만료된 파기 기록을 모두 지운다 — 만료 판정은 보존 기한+세션 만료 중
        늦은 쪽을 쓴다. 살아있는 표식은 건드리지 않는다."""
        doomed = [
            key
            for key, entry in self._revocations.items()
            if self._revocation_expired_locked(entry, now)
        ]
        for key in doomed:
            del self._revocations[key]
        return len(doomed)

    def _record_revocation_locked(self, entry: dict[str, Any], now: datetime) -> None:
        """파기 기록 1건을 둔다 — 상한이면 치워도 되는 것부터 치운다.

        살아있는 자격-승인 표식만 남았는데도 자리가 없으면 전체 권한을
        봉인하고 거부한다(조용히 버리지 않는다). 봉인 뒤에는 재시작 뒤
        purge·재시도로 복구한다(디스크는 커밋 전 상태 그대로다).
        """
        key = str(entry["session_id"])
        existing = self._revocations.get(key)
        if existing is not None:
            if "secret_sha256" in existing:
                return  # 살아있는 표식은 절대 덮어쓰지 않는다.
            if "secret_sha256" not in entry:
                return  # 일반 기록끼리는 먼저 것을 둔다.
            self._revocations[key] = entry  # 일반 → 표식 승격(개수 불변).
            return
        if len(self._revocations) < _MAX_REVOCATIONS:
            self._revocations[key] = entry
            return
        for victim in self._evictible_revocation_keys_locked(now):
            del self._revocations[victim]
            if len(self._revocations) < _MAX_REVOCATIONS:
                break
        if len(self._revocations) < _MAX_REVOCATIONS:
            self._revocations[key] = entry
            return
        self._sealed_reason = "revocations-full"
        raise SessionRecoveryError("파기 기록 상한 초과 — 봉인됨. 재시작 뒤 정리하고 다시 시도한다")

    def _reclaim_idle_lineages_locked(self, now: datetime) -> None:
        """상한 도달 때만 쓰는 예상 교체 — 유휴·보존기한 경과 lineage 만 치운다."""
        for key in [
            key
            for key, lineage in self._lineages.items()
            if not any(
                str(entry.get("lineage_id")) == key
                for entry in list(self._sessions.values()) + list(self._intents.values())
            )
            and _parse_instant(str(lineage["last_activity"]), "last_activity") + self._retention
            <= now
        ]:
            del self._lineages[key]

    def _reclaim_expired_intents_locked(self, now: datetime) -> None:
        for key in [
            key
            for key, record in self._intents.items()
            if _parse_instant(record["expires_at"], "expires_at") <= now
        ]:
            del self._intents[key]

    def _reclaim_expired_sessions_locked(self, now: datetime) -> None:
        # 조용히 버리지 않고 자격-승인 표식으로 남긴다 — 뒤늦은 로그아웃이
        # 대기 의도를 펜싱할 수 있게 한다(상한 도달 때의 예상 교체).
        for key in [
            key
            for key, record in self._sessions.items()
            if _parse_instant(record["expires_at"], "expires_at") <= now
        ]:
            self._invalidate_session_locked(key, "session-expired", now, marker=True)

    def purge_expired(self, now: datetime) -> PurgeReport:
        """만료 세션·의도·예약·보존기한 지난 묘비·유휴 lineage 를 지운다 — 명시
        호출만 집행한다."""
        _require_aware(now, "now")
        self._check_pid()
        with self._mutex:
            self._enter_locked()
            # 파기 기록 만료분부터 치운다 — 뒤따르는 표식 기록이 상한에
            # 걸리지 않게 한다(살아있는 표식은 건드리지 않는다).
            before_revocations = len(self._revocations)
            self._purge_revocations_locked(now)
            expired_sessions = [
                key
                for key, record in self._sessions.items()
                if _parse_instant(record["expires_at"], "expires_at") <= now
            ]
            # 만료된 세션도 자격-승인 표식으로 남긴다 — 뒤늦은 로그아웃이
            # 의도를 펜싱할 수 있게 한다.
            for key in expired_sessions:
                self._invalidate_session_locked(key, "session-expired", now, marker=True)
            expired_intents = [
                key
                for key, record in self._intents.items()
                if _parse_instant(record["expires_at"], "expires_at") <= now
            ]
            for key in expired_intents:
                del self._intents[key]
            expired_reservations = [
                key
                for key, record in self._reservations.items()
                if _parse_instant(record["expires_at"], "expires_at") <= now
            ]
            # 만료된 예약은 치우고 끝이 아니라 세션까지 영구 무효로 닫는다 —
            # provider 가 구 토큰을 소비했을 수 있어 재시도는 없다.
            invalidated = 0
            for key in expired_reservations:
                self._reservations.pop(key, None)
                if key in self._sessions:
                    self._invalidate_session_locked(
                        key, "refresh-reservation-expired", now, marker=True
                    )
                    invalidated += 1
            idle_lineages = [
                key
                for key, lineage in self._lineages.items()
                if not any(
                    str(entry.get("lineage_id")) == key
                    for entry in list(self._sessions.values()) + list(self._intents.values())
                )
                and _parse_instant(str(lineage["last_activity"]), "last_activity") + self._retention
                <= now
            ]
            for key in idle_lineages:
                del self._lineages[key]
            report = PurgeReport(
                sessions=len(expired_sessions) + invalidated,
                intents=len(expired_intents),
                reservations=len(expired_reservations),
                revocations=before_revocations - len(self._revocations),
                lineages=len(idle_lineages),
            )
            if (
                report.sessions
                or report.intents
                or report.reservations
                or before_revocations != len(self._revocations)
                or report.lineages
            ):
                self._persist_locked()
            return report


__all__ = [
    "LocalSessionAuthority",
    "LineageCredential",
    "PurgeReport",
    "RefreshReservation",
    "SessionAuthError",
    "SessionAuthorityError",
    "SessionConflictError",
    "SessionCredential",
    "SessionRecoveryError",
    "SessionView",
    "StoreCounts",
    "generate_seal_key",
]
