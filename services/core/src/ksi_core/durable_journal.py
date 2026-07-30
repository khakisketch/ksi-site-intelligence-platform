"""재사용 fail-closed append-only journal (ADR-KSI-008 §1).

:mod:`ksi_core.edge_sync` 의 ``EdgeSyncStore`` 가 이미 구현한 durable journal
6요소 — POSIX short-write 대응 짧은쓰기 루프, fsync(파일 + 신규생성 시 부모
디렉터리), flock 기반 단일 writer 강제, torn-tail 격리, 예외 시 봉인(sealed),
기동 시 fail-closed 재생 — 를 **도메인 비종속**(레코드가 임의 dict) 형태로
대칭 구현한다.

``edge_sync.py`` 자체는 이 모듈이 있어도 재작성하지 않는다 — 무겁게 반증
검토된 코드의 회귀 위험이 공용 베이스 추출 이득보다 크다(ADR-KSI-008 §1).
Site/Mission/Event 저장소(S2)는 ``edge_sync.py`` 를 흉내내지 않고 이 클래스
위에 조립한다.

## 봉인(sealed) 의미론

``append`` 도중 발생한 **임의 예외**(``BaseException`` 포함 — 직렬화 실패인
``json.dumps`` 의 ``ValueError``/``TypeError`` 도 포함된다)는 즉시 journal 을
봉인하고 :class:`JournalSealedError` 를 원인 체인과 함께 던진다. 디스크 쓰기
전 단계(직렬화)에서 실패했더라도 봉인하는 이유는, "이 레코드가 이 journal 에
안전하게 기록될 수 있다"는 불변식이 이미 깨졌다는 신호를 신뢰할 수 없는
상태로 남겨두지 않기 위해서다 — 재시작 전에는 어떤 후속 append 도 조용히
성공한 것처럼 보이지 않는다.

## 재생(replay) 의미론

기동 시 완결 줄(개행으로 끝난 줄)을 전부 파싱해 :class:`dict` 로 반환한다.
하나라도 JSON 파싱 실패거나 최상위 타입이 dict 가 아니면(예: 배열) 오염으로
간주해 :class:`JournalRecoveryError` 로 기동을 거부한다. 개행 없이 끝난 마지막
부분 줄(torn tail)은 완결 write+fsync 전이라 "기록된 적이 없다"로 취급해
잘라내고(경고 로그) 정상 기동한다. :meth:`replay` 는 기동 시 재생분과 이후
같은 인스턴스로 성공한 append 를 모두 포함한 순서 보존 스냅샷을 반환한다.
"""

from __future__ import annotations

import copy
import fcntl
import json
import logging
import os
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# os.write 참조를 모듈 상수로 분리 — short-write fault injection 테스트가 전역
# os 모듈을 건드리지 않고 이 경로만 대체할 수 있게(edge_sync.py:79 관습 대칭).
_WRITE = os.write


class JournalError(Exception):
    """DurableJournal 오류의 공통 기반."""


class JournalRecoveryError(JournalError):
    """journal 재적재/잠금 실패 — 오염·경합 상태로 기동하지 않는다(fail-closed)."""


class JournalSealedError(JournalError):
    """append 중 예외로 봉인됨 — 재시작 전에는 모든 append 가 거부된다."""


def _fsync_dir(directory: Path) -> None:
    """디렉터리 엔트리를 durable 하게 만든다 — 파일 fsync 만으로는 부족하다(POSIX)."""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class DurableJournal:
    """append-only journal — 단일 writer 잠금 + fail-closed 재생 + 예외 시 봉인.

    파일 위치는 조립 시 명시 경로만 받는다(기본 경로 상수 금지 — repo hygiene,
    ADR-KSI-008 §1). 부모 디렉터리는 ``edge_sync.py`` 관습을 따라 **이 클래스가
    직접 생성**한다(``mkdir(parents=True, exist_ok=True)``) — 호출자가 미리
    만들어둘 필요가 없다.

    동시성: flock 은 프로세스 간 단일 writer 를 강제한다. 프로세스 내부에서
    여러 스레드가 같은 인스턴스를 공유할 수 있으므로(FastAPI sync 라우트는
    스레드풀에서 돈다) ``append``/``close`` 는 인스턴스 잠금으로 직렬화한다.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._sealed_reason: str | None = None
        self._records: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._acquire_writer_lock()
        try:
            self._recover()
        except BaseException:
            # 재생(fail-closed) 실패로 인스턴스가 살아남지 못하면 flock·fd 를
            # 프로세스 수명 내내 들고 있으면 안 된다 — 다음 시도(재시작 없이도)가
            # "다른 프로세스가 소유 중"으로 영구히 막히는 것을 방지한다.
            self._release_writer_lock()
            raise

    def _acquire_writer_lock(self) -> None:
        """flock 배타 잠금 — 두 프로세스가 같은 journal 에 쓰는 경합을 기동 거부로 막는다."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # 잠금 파일 fd 는 인스턴스 수명 동안 유지된다(닫히면 잠금이 풀린다).
            self._lock_fd = os.open(
                self._path.with_suffix(self._path.suffix + ".lock"),
                os.O_CREAT | os.O_RDWR,
                0o600,
            )
        except OSError as exc:
            raise JournalRecoveryError(
                f"잠금 파일 생성 실패: {type(exc).__name__}: {exc}"
            ) from exc
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self._lock_fd)
            raise JournalRecoveryError(
                f"{self._path}: 다른 프로세스가 journal 을 소유 중 — 단일 writer 위반"
            ) from exc

    def _recover(self) -> None:
        """journal 재적재 — 완결 줄은 전부 파싱 가능한 dict 여야 하고, torn tail 은 격리한다."""
        if not self._path.exists():
            return
        try:
            raw = self._path.read_bytes()
        except OSError as exc:
            raise JournalRecoveryError(
                f"{self._path}: journal 읽기 실패 — {type(exc).__name__}: {exc}"
            ) from exc

        complete, _sep, tail = raw.rpartition(b"\n")
        records: list[dict[str, Any]] = []
        for line_no, line in enumerate(complete.split(b"\n") if complete else [], start=1):
            if not line.strip():
                continue
            try:
                parsed: Any = json.loads(line)
            except ValueError as exc:
                raise JournalRecoveryError(
                    f"{self._path}:{line_no}: journal 줄이 JSON 이 아니다 — {exc}"
                ) from exc
            if not isinstance(parsed, dict):
                raise JournalRecoveryError(
                    f"{self._path}:{line_no}: journal 레코드가 object 가 아니다 "
                    f"({type(parsed).__name__}) — 오염된 원장은 조용히 건너뛰지 않는다"
                )
            records.append(parsed)

        if tail.strip():
            # 개행 없이 끝난 마지막 부분 줄 — 완결 write+fsync 후에만 성공으로
            # 치므로 이 줄은 "기록된 적이 없다"와 동치다. 남겨두면 다음 append 가
            # 뒤에 이어붙어 진짜 오염이 되므로 잘라낸다.
            logger.warning(
                "%s: torn tail %d바이트 격리(부분 쓰기 후 중단 흔적) — 완결되지 않은 레코드",
                self._path,
                len(tail),
            )
            try:
                with self._path.open("r+b") as handle:
                    handle.truncate(len(raw) - len(tail))
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                # raw OSError 를 그대로 누출하지 않는다 — 이 실패도 재생 실패의
                # 한 형태이므로 다른 재생 오류와 동일하게 fail-closed 로 묶는다.
                raise JournalRecoveryError(
                    f"{self._path}: torn tail 격리(truncate) 실패 — "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

        self._records = records

    def replay(self) -> list[dict[str, Any]]:
        """순서 보존된 완결 레코드 스냅샷(기동 시 재생분 + 이후 성공한 append).

        ``deepcopy`` 로 반환한다 — top-level 얕은 복사만으로는 레코드 내부의
        가변 객체(중첩 dict/list, 예: siteFrame)가 호출자와 공유돼, 호출자가
        반환값을 변형하면 감사 원장의 내부 상태까지 조용히 오염될 수 있다.
        """
        with self._lock:
            return copy.deepcopy(self._records)

    def append(self, record: Mapping[str, Any]) -> None:
        """레코드 1건을 durable 하게 기록한다.

        성공은 fsync 이후에만 반환된다. 도중 발생한 임의 예외는 journal 을
        봉인하고 :class:`JournalSealedError` 를 원인 체인과 함께 던진다 —
        디스크에 없는 상태로 "성공"처럼 보이는 경로를 만들지 않는다.
        """
        with self._lock:
            if self._sealed_reason is not None:
                raise JournalSealedError(
                    f"{self._path}: 봉인됨({self._sealed_reason}) — append 거부"
                )
            try:
                self._append_durable(record)
            except BaseException as exc:
                self._sealed_reason = type(exc).__name__
                logger.error("durable append 중 예외로 봉인: %s", type(exc).__name__)
                raise JournalSealedError(
                    f"{self._path}: append 실패로 봉인됨 — {type(exc).__name__}"
                ) from exc
            # deepcopy — dict(record) 는 top-level 만 복사한다. record 안에 중첩
            # dict/list(예: siteFrame)가 있으면 호출자가 원본을 나중에 변형할 때
            # 이미 durable 하게 기록된 감사 레코드까지 조용히 바뀌는 경로가 생긴다.
            self._records.append(copy.deepcopy(dict(record)))

    def _append_durable(self, record: Mapping[str, Any]) -> None:
        # ensure_ascii=True: 유니코드 개행 후보(U+2028 등)가 raw 로 나가 재적재의
        # 줄 분리를 깨는 경로를 원천 차단한다(edge_sync.py 실측 관습).
        # allow_nan=False: NaN/Infinity 는 JSON 표준 밖이라 거부한다(재적재 시
        # 다른 파서와의 상호운용을 fail-closed 로 지킨다).
        line = json.dumps(
            dict(record),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        creating = not self._path.exists()
        if creating:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        data = (line + "\n").encode("ascii")
        fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            # POSIX write 는 예외 없이 짧게 쓸 수 있다(ENOSPC/EDQUOT 페이지 경계) —
            # 반환값을 무시하면 부분 줄이 기록된 채 fsync 가 성공해 "완결"로
            # 오인될 수 있다(edge_sync.py 감사 #1 실측). 전량 기록까지 반복하고,
            # 진전이 없으면 OSError 로 올려 위 봉인 경로를 태운다 — 이미 쓰인
            # 부분 줄은 개행이 없어 재시작 복원이 torn tail 로 격리한다.
            view = memoryview(data)
            written = 0
            while written < len(data):
                count = _WRITE(fd, view[written:])
                if count <= 0:
                    raise OSError(
                        f"short write: {written}/{len(data)} bytes — 전량 기록 실패"
                    )
                written += count
            os.fsync(fd)
        finally:
            os.close(fd)
        if creating:
            # 새 파일은 디렉터리 엔트리도 durable 해야 성공 응답 후 머신
            # 크래시에서 파일째 사라지지 않는다(POSIX fsync 명세).
            _fsync_dir(self._path.parent)

    @property
    def sealed_reason(self) -> str | None:
        """봉인 사유. 미봉인이면 ``None``, ``close()`` 이후면 ``"closed"``."""
        return self._sealed_reason

    def _release_writer_lock(self) -> None:
        """flock 해제 + 잠금 fd 닫기 — ``__init__`` 복구 실패 경로와 :meth:`close` 공용.

        재생(``_recover``) 실패로 인스턴스가 살아남지 못하는 경우에도 호출돼,
        flock·fd 가 실패한 인스턴스와 함께 프로세스 수명 내내 남는 것을 막는다.
        """
        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        os.close(self._lock_fd)

    def close(self) -> None:
        """수신 봉인 + 잠금 해제 — 멱등.

        close 후 도착한 append 가 잠금 없이 기록되는 창을 없앤다 — 이후 모든
        append 는 :class:`JournalSealedError` (사유 ``"closed"``)다. 이미 다른
        사유로 봉인돼 있어도 사유를 ``"closed"`` 로 덮어쓰고 잠금을 해제한다
        (edge_sync.py 관습 대칭 — fd 는 아직 열려 있으므로 안전하다).
        """
        with self._lock:
            if self._sealed_reason == "closed":
                return
            self._sealed_reason = "closed"
            self._release_writer_lock()
