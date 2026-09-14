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

## 세그먼트 회전 (S4 — ops-serving-hardening)

``max_segment_bytes`` 를 주면 활성 파일이 그 크기를 넘어설 때 봉인된 세그먼트
(``<이름>.0001.jsonl``)로 rename 하고 새 활성 파일을 시작한다. 재생은 세그먼트
번호 오름차순 + 활성 파일 순으로 이어 붙이므로 **레코드 순서는 회전 전후로
보존된다**. 기본값(``None``)은 회전 없음 — 기존 조립은 그대로 동작한다.

회전은 **무엇도 지우지 않는다.** 오래된 세그먼트의 폐기는 보관 정책
(``contracts/schemas/retention-policy.v1.json``)의 소관이고, 이 클래스는
"한 파일이 무한히 커져 재기동이 선형으로 느려지는 것"만 막는다. 감사 원장을
스스로 지우는 코드를 여기 두지 않는 게 이 분리의 요점이다.

회전 실패는 봉인하지 않는다 — append 는 이미 fsync 로 durable 하고, rename 이
실패해도 기록된 데이터는 온전하다. 봉인하면 durability 와 무관한 사유로 수신을
멈추게 된다. 대신 경고를 남기고 다음 append 에서 다시 시도한다.
"""

from __future__ import annotations

import copy
import fcntl
import json
import logging
import os
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger("ksi_core.durable_journal")

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


def _acquire_writer_lock(path: Path, *, error_cls: type[Exception]) -> int:
    """flock 배타 잠금 fd 획득 — 두 프로세스가 같은 journal 에 쓰는 경합을 기동 거부로 막는다.

    ``DurableJournal`` 과 ``edge_sync.EdgeSyncStore`` 가 동형으로 구현하던 잠금
    획득부의 공용화(P0-1 2단계). 두 원장은 실패 시 던지는 예외 타입이 다르므로
    (``JournalRecoveryError`` / ``StoreRecoveryError`` — 각자의 호출자·테스트가
    구체 타입으로 잡는다) 호출자가 ``error_cls`` 로 지정한다. 메시지 문면은
    두 원장에서 원래 동일했으므로 그대로 보존한다.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # 잠금 파일 fd 는 인스턴스 수명 동안 유지된다(닫히면 잠금이 풀린다).
        lock_fd = os.open(
            path.with_suffix(path.suffix + ".lock"), os.O_CREAT | os.O_RDWR, 0o600
        )
    except OSError as exc:
        raise error_cls(f"잠금 파일 생성 실패: {type(exc).__name__}: {exc}") from exc
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(lock_fd)
        raise error_cls(
            f"{path}: 다른 프로세스가 journal 을 소유 중 — 단일 writer 위반"
        ) from exc
    return lock_fd


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

    @classmethod
    def open_read_only(cls, path: Path) -> DurableJournal:
        """**잠금 없이** 재생만 하는 인스턴스 — 서버가 도는 중에도 읽을 수 있다.

        보관 정책 dry-run(``tools/enforce_retention.py``)처럼 "무엇이 지워질지"를
        먼저 보여줘야 하는 경로가 실제로 필요로 한다. 그 확인이 서버 정지를
        요구하면 아무도 보지 않게 되고, 그러면 dry-run 이 있으나 마나다.

        읽기 전용이라는 사실은 **봉인으로 표현한다** — 이 인스턴스의 ``append`` 는
        항상 :class:`JournalSealedError` 다. flock 을 잡지 않으므로 쓰기가 허용되면
        단일 writer 불변식이 조용히 깨진다.

        torn tail 도 **격리하지 않는다**(truncate 는 쓰기다) — 완결 줄까지만 읽고
        멈춘다. 그 결과는 "쓰기 소유자가 다음 기동에서 격리할 부분을 아직 못 본
        상태"이고, 읽기 전용 소비자에게는 그게 정확한 뷰다.
        """
        instance = cls.__new__(cls)
        instance._path = path
        instance._max_segment_bytes = None
        instance._sealed_reason = "read-only"
        instance._records = []
        instance._lock = threading.Lock()
        instance._lock_fd = -1  # 잠금 없음 — close() 가 이 값을 보고 해제를 건너뛴다
        instance._recover(tolerate_torn_tail=False, read_only=True)
        return instance

    def __init__(self, path: Path, *, max_segment_bytes: int | None = None) -> None:
        if max_segment_bytes is not None and max_segment_bytes <= 0:
            # 0 이나 음수를 받으면 append 마다 회전해 세그먼트를 무한히 만든다 —
            # "회전 없음"을 뜻하려면 None 이어야 한다(조용히 해석하지 않는다).
            raise ValueError(
                f"max_segment_bytes 는 양수여야 한다(회전 없음은 None): {max_segment_bytes!r}"
            )
        self._path = path
        self._max_segment_bytes = max_segment_bytes
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
        self._lock_fd = _acquire_writer_lock(self._path, error_cls=JournalRecoveryError)

    def _segment_path(self, sequence: int) -> Path:
        """봉인된 세그먼트 경로 — ``journal.jsonl`` → ``journal.0001.jsonl``."""
        return self._path.with_name(f"{self._path.stem}.{sequence:04d}{self._path.suffix}")

    def _existing_segments(self) -> list[tuple[int, Path]]:
        """번호 오름차순 세그먼트 목록.

        ``.lock`` 파일(``journal.jsonl.lock``)은 suffix 가 달라 여기 걸리지 않는다.
        번호 자리가 숫자가 아닌 동명 파일(사람이 만든 ``journal.backup.jsonl`` 등)은
        세그먼트가 아니므로 건너뛴다 — 재생 대상에 남의 파일을 끌어들이지 않는다.
        """
        stem, suffix = re.escape(self._path.stem), re.escape(self._path.suffix)
        pattern = re.compile(rf"^{stem}\.(\d+){suffix}$")
        found: list[tuple[int, Path]] = []
        for candidate in self._path.parent.glob(f"{self._path.stem}.*{self._path.suffix}"):
            match = pattern.match(candidate.name)
            if match is not None:
                found.append((int(match.group(1)), candidate))
        return sorted(found)

    def _recover(self, *, tolerate_torn_tail: bool = True, read_only: bool = False) -> None:
        """journal 재적재 — 봉인 세그먼트를 번호순으로 먼저, 활성 파일을 마지막에.

        순서가 곧 원장의 의미다(멱등 판정·상태 전이가 순서에 의존한다) — 세그먼트를
        번호순으로 이어 붙여야 회전 전후로 같은 재생 결과가 나온다.
        """
        records: list[dict[str, Any]] = []
        for _sequence, segment in self._existing_segments():
            # 봉인된 세그먼트에는 torn tail 이 있을 수 없다 — 회전은 append 가
            # fsync 로 완결된 뒤에만 일어나고 rename 은 원자적이다. 그런데도 부분
            # 줄이 있다면 설명되지 않는 상태이므로 조용히 잘라내지 않고 거부한다.
            records.extend(self._read_records(segment, tolerate_torn_tail=False))
        if self._path.exists():
            records.extend(
                self._read_records(
                    self._path,
                    tolerate_torn_tail=tolerate_torn_tail and not read_only,
                    truncate_torn_tail=not read_only,
                )
            )
        self._records = records

    def _read_records(
        self, path: Path, *, tolerate_torn_tail: bool, truncate_torn_tail: bool = True
    ) -> list[dict[str, Any]]:
        """한 파일의 완결 레코드 — 오염은 거부하고, 활성 파일의 torn tail 만 격리한다."""
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise JournalRecoveryError(
                f"{path}: journal 읽기 실패 — {type(exc).__name__}: {exc}"
            ) from exc

        complete, _sep, tail = raw.rpartition(b"\n")
        records: list[dict[str, Any]] = []
        for line_no, line in enumerate(complete.split(b"\n") if complete else [], start=1):
            if not line.strip():
                continue
            try:
                parsed: Any = json.loads(line)
            except (ValueError, RecursionError) as exc:
                # RecursionError 도 잡는다(2026-08-18 재조사 F4) — 깊게 중첩된
                # 원장 줄에서 json.loads 가 던지는 것은 ValueError 가 아니라서,
                # 안 잡으면 JournalRecoveryError 로 감싸이지 못하고 날것으로
                # 올라가 운영자가 어느 파일 어느 줄인지 볼 수 없다.
                raise JournalRecoveryError(
                    f"{path}:{line_no}: journal 줄이 JSON 이 아니다 — {exc}"
                ) from exc
            if not isinstance(parsed, dict):
                raise JournalRecoveryError(
                    f"{path}:{line_no}: journal 레코드가 object 가 아니다 "
                    f"({type(parsed).__name__}) — 오염된 원장은 조용히 건너뛰지 않는다"
                )
            records.append(parsed)

        if tail.strip():
            if not truncate_torn_tail:
                # 읽기 전용 — 완결 줄까지만 읽고 멈춘다(truncate 는 쓰기다).
                logger.info(
                    "%s: 읽기 전용 재생 — torn tail %d바이트는 건너뛴다", path, len(tail)
                )
                return records
            if not tolerate_torn_tail:
                raise JournalRecoveryError(
                    f"{path}: 봉인된 세그먼트에 완결되지 않은 줄이 있다 "
                    f"({len(tail)}바이트) — 회전은 fsync 완결 후에만 일어나므로 "
                    "설명되지 않는 상태다"
                )
            # 개행 없이 끝난 마지막 부분 줄 — 완결 write+fsync 후에만 성공으로
            # 치므로 이 줄은 "기록된 적이 없다"와 동치다. 남겨두면 다음 append 가
            # 뒤에 이어붙어 진짜 오염이 되므로 잘라낸다.
            logger.warning(
                "%s: torn tail %d바이트 격리(부분 쓰기 후 중단 흔적) — 완결되지 않은 레코드",
                path,
                len(tail),
            )
            try:
                with path.open("r+b") as handle:
                    handle.truncate(len(raw) - len(tail))
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                # raw OSError 를 그대로 누출하지 않는다 — 이 실패도 재생 실패의
                # 한 형태이므로 다른 재생 오류와 동일하게 fail-closed 로 묶는다.
                raise JournalRecoveryError(
                    f"{path}: torn tail 격리(truncate) 실패 — "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

        return records

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
                # deepcopy — dict(record) 는 top-level 만 복사한다. record 안에 중첩
                # dict/list(예: siteFrame)가 있으면 호출자가 원본을 나중에 변형할 때
                # 이미 durable 하게 기록된 감사 레코드까지 조용히 바뀌는 경로가 생긴다.
                #
                # deepcopy 가 try **안**에 있는 이유(2026-08-18 재조사 F4): 깊게
                # 중첩된 레코드에서 deepcopy 는 RecursionError 를 낼 수 있는데,
                # 그 시점엔 durable 기록이 이미 성공한 뒤다. try 밖이면 "디스크에는
                # 있는데 메모리에는 없는" 불일치가 봉인 없이 지나가고, 그 예외가
                # 호출자 스택으로 날것으로 올라간다. 안에 있으면 봉인으로 승격돼
                # 불일치가 fail-closed 로 드러난다(재기동 재적재가 디스크 기준으로
                # 상태를 복원한다).
                self._records.append(copy.deepcopy(dict(record)))
            except BaseException as exc:
                self._sealed_reason = type(exc).__name__
                logger.error("durable append 중 예외로 봉인: %s", type(exc).__name__)
                raise JournalSealedError(
                    f"{self._path}: append 실패로 봉인됨 — {type(exc).__name__}"
                ) from exc
            # 회전은 append 가 durable 해진 **뒤에** 한다 — 실패해도 방금 기록한
            # 레코드는 안전하다. 그래서 봉인하지 않는다(모듈 docstring 참조).
            self._rotate_if_needed()

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

    def _rotate_if_needed(self) -> None:
        """활성 파일이 임계를 넘었으면 봉인 세그먼트로 넘긴다(호출자가 잠금 보유).

        임계는 **넘어선 뒤** 검사한다 — 레코드를 쪼개 걸치게 하지 않으려면
        경계에서 자를 수 없고, 한 레코드가 임계보다 커도 반드시 한 파일에
        온전히 들어가야 하기 때문이다. 그래서 세그먼트는 임계보다 조금 크다.
        """
        if self._max_segment_bytes is None:
            return
        try:
            size = self._path.stat().st_size
        except OSError as exc:
            logger.warning("%s: 회전 판단용 stat 실패 — %s", self._path, type(exc).__name__)
            return
        if size < self._max_segment_bytes:
            return

        segments = self._existing_segments()
        target = self._segment_path(segments[-1][0] + 1 if segments else 1)
        try:
            # rename 은 같은 디렉터리 안에서 원자적이다 — 재생이 활성 파일과
            # 세그먼트 양쪽에서 같은 레코드를 두 번 읽는 창이 생기지 않는다.
            os.rename(self._path, target)
            # rename 자체를 durable 하게 — 디렉터리 엔트리가 fsync 되지 않으면
            # 크래시 후 활성 파일과 세그먼트가 **둘 다** 보이거나 둘 다 사라질 수 있다.
            _fsync_dir(self._path.parent)
        except OSError as exc:
            # 데이터는 온전하다(회전 전 파일 그대로) — 수신을 멈추지 않고
            # 다음 append 에서 다시 시도한다. 다만 조용히 넘어가지는 않는다.
            logger.warning(
                "%s: 세그먼트 회전 실패(%s) — 다음 append 에서 재시도, 기록된 데이터는 온전하다",
                self._path,
                type(exc).__name__,
            )
            return
        logger.info("%s: %d바이트에서 %s 로 회전", self._path, size, target.name)

    @property
    def sealed_reason(self) -> str | None:
        """봉인 사유. 미봉인이면 ``None``, ``close()`` 이후면 ``"closed"``."""
        return self._sealed_reason

    def _release_writer_lock(self) -> None:
        """(read-only 인스턴스는 잡은 잠금이 없어 이 함수를 타지 않는다 — close 참조.)
        flock 해제 + 잠금 fd 닫기 — ``__init__`` 복구 실패 경로와 :meth:`close` 공용.

        재생(``_recover``) 실패로 인스턴스가 살아남지 못하는 경우에도 호출돼,
        flock·fd 가 실패한 인스턴스와 함께 프로세스 수명 내내 남는 것을 막는다.
        """
        lock_fd = self._lock_fd
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            try:
                os.close(lock_fd)
            finally:
                # A failed constructor and the GC fallback must never close a
                # descriptor number that the process has since reused.
                self._lock_fd = -1

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
            was_read_only = self._lock_fd < 0
            self._sealed_reason = "closed"
            if not was_read_only:
                self._release_writer_lock()

    def __del__(self) -> None:
        """Best-effort lock release when an owner abandons the journal.

        Application assembly still owns deterministic ``close()``.  This is a
        last-resort resource-safety boundary for failed assembly and short-lived
        tooling/tests: an integer file descriptor is otherwise left open even
        after the Python object becomes unreachable.
        """

        try:
            if getattr(self, "_lock", None) is not None:
                self.close()
        except Exception:
            # Destructors run during partial construction and interpreter
            # shutdown; they must never turn cleanup into an unraisable error.
            pass
