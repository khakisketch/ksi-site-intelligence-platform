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
import math
import os
import re
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from time import monotonic, process_time
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


def _checked_line_validator(
    line_validator: Callable[[bytes], None] | None, path: Path
) -> Callable[[bytes], None] | None:
    """Validate an owner-supplied raw-line structural gate (or pass ``None``).

    The gate runs on raw line bytes BEFORE any JSON parse, so an inflated
    shape is refused before objects accumulate. ``None`` keeps the legacy
    parse-then-validate behavior exactly. Strict syntax is untouched: a gate
    rejection surfaces as journal corruption, never as a skip.
    """
    if line_validator is None:
        return None
    if not callable(line_validator):
        raise ValueError(f"{path}: line validator must be a callable or None")
    return line_validator


def _run_line_validator(
    line_validator: Callable[[bytes], None] | None,
    path: Path,
    line_no: int,
    line: bytes,
) -> None:
    if line_validator is None:
        return
    try:
        line_validator(line)
    except ValueError as exc:
        raise JournalRecoveryError(
            f"{path}:{line_no}: journal 줄이 구조 상한을 위반 — {exc}"
        ) from exc


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
    def open_read_only(
        cls, path: Path, *, line_validator: Callable[[bytes], None] | None = None
    ) -> DurableJournal:
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
        instance._retain_records = True
        instance._max_line_bytes = None
        instance._max_recover_bytes = None
        instance._recover_deadline = None
        instance._recover_cpu_budget = None
        instance._line_validator = _checked_line_validator(line_validator, path)
        instance._open_monotonic = monotonic()
        instance._open_process_time = process_time()
        instance._recover_cpu_start = instance._open_process_time
        instance._tolerate_torn_tail = True
        instance._sealed_reason = "read-only"
        instance._records = []
        instance._record_count = 0
        instance._stream_resume_offset = 0
        instance._lock = threading.Lock()
        instance._lock_fd = -1  # 잠금 없음 — close() 가 이 값을 보고 해제를 건너뛴다
        instance._recover(tolerate_torn_tail=False, read_only=True)
        return instance

    def __init__(
        self,
        path: Path,
        *,
        max_segment_bytes: int | None = None,
        retain_records: bool = True,
        max_line_bytes: int | None = None,
        max_recover_bytes: int | None = None,
        recover_deadline: float | None = None,
        recover_cpu_budget: float | None = None,
        recover_cpu_start: float | None = None,
        tolerate_torn_tail: bool = True,
        line_validator: Callable[[bytes], None] | None = None,
    ) -> None:
        open_monotonic = monotonic()
        open_process_time = process_time()
        self._line_validator = _checked_line_validator(line_validator, path)
        if max_segment_bytes is not None and max_segment_bytes <= 0:
            # 0 이나 음수를 받으면 append 마다 회전해 세그먼트를 무한히 만든다 —
            # "회전 없음"을 뜻하려면 None 이어야 한다(조용히 해석하지 않는다).
            raise ValueError(
                f"max_segment_bytes 는 양수여야 한다(회전 없음은 None): {max_segment_bytes!r}"
            )
        if type(retain_records) is not bool:
            raise ValueError("retain_records must be an explicit boolean")
        if max_line_bytes is not None and (type(max_line_bytes) is not int or max_line_bytes <= 0):
            raise ValueError("max_line_bytes must be a positive integer or None")
        if max_recover_bytes is not None and (
            type(max_recover_bytes) is not int or max_recover_bytes <= 0
        ):
            raise ValueError("max_recover_bytes must be a positive integer or None")
        if recover_deadline is not None and (
            type(recover_deadline) not in (int, float)
            or not math.isfinite(recover_deadline)
            or recover_deadline <= 0
        ):
            raise ValueError(
                "recover_deadline must be a positive finite monotonic timestamp or None"
            )
        if recover_cpu_budget is not None and (
            type(recover_cpu_budget) not in (int, float)
            or not math.isfinite(recover_cpu_budget)
            or recover_cpu_budget <= 0
        ):
            raise ValueError(
                "recover_cpu_budget must be a positive finite CPU-seconds budget or None"
            )
        if recover_cpu_start is not None and (
            type(recover_cpu_start) not in (int, float)
            or not math.isfinite(recover_cpu_start)
        ):
            raise ValueError("recover_cpu_start must be a finite process-time stamp or None")
        if type(tolerate_torn_tail) is not bool:
            raise ValueError("tolerate_torn_tail must be an explicit boolean")
        if not retain_records and max_line_bytes is None:
            # 비보관 모드는 줄 단위 상한 없이 기동할 수 없다 — 무한한 carry 가
            # RAM 상한을 깨기 때문이다. 상한은 호출자(원장 의미의 소유자)가 명시한다.
            raise ValueError("non-retaining open requires an explicit max_line_bytes")
        if not retain_records and (
            max_recover_bytes is None
            or recover_deadline is None
            or tolerate_torn_tail is not False
        ):
            # 비보관 모드는 기동 전에 전체를 스캔하므로 총량·기한 상한도
            # 호출자가 명시해야 한다 — Audit 뒤가 아니라 최초 open 부터다.
            # torn tail 허용도 명시적 False 여야 한다: 비보관 감사는
            # 잘라내기 전에 거부해야지 조용히 수리하면 안 된다. 레거시
            # 보관 모드 기본값(retain True / tolerate True)은 그대로다.
            raise ValueError(
                "non-retaining open requires explicit max_recover_bytes,"
                " recover_deadline and tolerate_torn_tail=False"
            )
        self._path = path
        self._max_segment_bytes = max_segment_bytes
        self._retain_records = retain_records
        self._max_line_bytes = max_line_bytes
        self._max_recover_bytes = max_recover_bytes
        self._recover_deadline = float(recover_deadline) if recover_deadline is not None else None
        self._recover_cpu_budget = (
            float(recover_cpu_budget) if recover_cpu_budget is not None else None
        )
        self._open_monotonic = open_monotonic
        self._open_process_time = open_process_time
        self._recover_cpu_start = (
            float(recover_cpu_start) if recover_cpu_start is not None else open_process_time
        )
        self._tolerate_torn_tail = tolerate_torn_tail
        self._sealed_reason: str | None = None
        self._records: list[dict[str, Any]] = []
        self._record_count = 0
        self._lock = threading.Lock()
        self._acquire_writer_lock()
        try:
            self._recover(tolerate_torn_tail=tolerate_torn_tail)
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

        ``retain_records=False`` 로 열린 인스턴스는 같은 검증을 스트리밍으로
        수행하고 레코드 목록은 보관하지 않는다(개수·활성 파일 재개점만 유지).
        오염·torn tail 판단은 유지 모드와 동일하다. 비보관 모드에서는 생성자
        바운드(줄 상한·스캔 상한·기한) 안에서만 검증하고, 초과는 오염과
        동일하게 기동을 거부한다.
        """
        tolerate = tolerate_torn_tail and self._tolerate_torn_tail
        if self._retain_records:
            records: list[dict[str, Any]] = []
            for _sequence, segment in self._existing_segments():
                # 봉인된 세그먼트에는 torn tail 이 있을 수 없다 — 회전은 append 가
                # fsync 로 완결된 뒤에만 일어나고 rename 은 원자적이다. 그런데도 부분
                # 줄이 있다면 설명되지 않는 상태이므로 조용히 잘라내지 않고 거부한다.
                records.extend(
                    self._read_records(
                        segment, tolerate_torn_tail=False, max_line_bytes=self._max_line_bytes
                    )
                )
            if self._path.exists():
                records.extend(
                    self._read_records(
                        self._path,
                        tolerate_torn_tail=tolerate and not read_only,
                        truncate_torn_tail=not read_only,
                        max_line_bytes=self._max_line_bytes,
                    )
                )
            self._records = records
            self._record_count = len(records)
        else:
            scanned = [0]
            count = 0
            for _sequence, segment in self._existing_segments():
                count += self._validate_stream(segment, tolerate_torn_tail=False, scanned=scanned)
            if self._path.exists():
                count += self._validate_stream(
                    self._path,
                    tolerate_torn_tail=tolerate and not read_only,
                    truncate_torn_tail=not read_only,
                    scanned=scanned,
                )
            self._record_count = count
        try:
            self._stream_resume_offset = self._path.stat().st_size if self._path.exists() else 0
        except OSError:
            self._stream_resume_offset = 0

    def _check_recover_budget(self, scanned: int) -> None:
        if self._max_recover_bytes is not None and scanned > self._max_recover_bytes:
            raise JournalRecoveryError(
                f"{self._path}: 재생 스캔이 바이트 예산({self._max_recover_bytes})을 초과 — "
                "기동 거부"
            )
        if self._recover_deadline is not None and monotonic() > self._recover_deadline:
            raise JournalRecoveryError(f"{self._path}: 재생이 기한을 초과 — 기동 거부")
        if (
            self._recover_cpu_budget is not None
            and process_time() - self._recover_cpu_start > self._recover_cpu_budget
        ):
            raise JournalRecoveryError(f"{self._path}: 재생이 CPU 예산을 초과 — 기동 거부")

    def _read_records(
        self,
        path: Path,
        *,
        tolerate_torn_tail: bool,
        truncate_torn_tail: bool = True,
        max_line_bytes: int | None = None,
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
            if max_line_bytes is not None and len(line) > max_line_bytes:
                raise JournalRecoveryError(
                    f"{path}:{line_no}: journal 줄이 줄 상한({max_line_bytes}바이트)을 초과 — "
                    "오염된 원장은 조용히 건너뛰지 않는다"
                )
            _run_line_validator(self._line_validator, path, line_no, line)
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

    _STREAM_CHUNK_BYTES = 65536

    def _validate_stream(
        self,
        path: Path,
        *,
        tolerate_torn_tail: bool,
        truncate_torn_tail: bool = True,
        scanned: list[int] | None = None,
        max_line_bytes: int | None = None,
    ) -> int:
        """한 파일의 완결 레코드 개수 — 내용은 보관하지 않고 검증만 스트리밍한다.

        오염 판단·torn tail 격리 의미는 :meth:`_read_records` 와 동일하다. RAM
        사용량은 청크 상수에 묶이며 파일 크기와 무관하다. 줄 상한을 넘긴
        완결 줄/부분 tail 은 오염으로 거부한다. 개행 없는 부분 줄(carry)은
        매 청크마다 상한을 검사하므로 — EOF 를 기다리지 않으므로 — 개행 없는
        수십 MB 입력이 RAM 에 누적되는 경로가 없다.
        """
        count = 0
        carry = b""
        line_no = 0
        # 비보관 모드 생성자가 강제하므로 항상 설정된다. 보관 모드는 이 경로를
        # 타지 않는다(``_recover`` 보관 분기는 ``_read_records`` 사용).
        line_cap = self._max_line_bytes if max_line_bytes is None else max_line_bytes
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                remaining = size
                while remaining > 0:
                    if self._recover_deadline is not None and monotonic() > self._recover_deadline:
                        raise JournalRecoveryError(f"{path}: 재생 검증이 기한을 초과 — 기동 거부")
                    if (
                        self._recover_cpu_budget is not None
                        and process_time() - self._recover_cpu_start
                        > self._recover_cpu_budget
                    ):
                        raise JournalRecoveryError(
                            f"{path}: 재생 검증이 CPU 예산을 초과 — 기동 거부"
                        )
                    piece = handle.read(min(self._STREAM_CHUNK_BYTES, remaining))
                    if not piece:
                        raise JournalRecoveryError(
                            f"{path}: journal 읽기 중 예기치 않은 EOF "
                            f"({remaining}바이트 남음) — 단일 writer 불변식 위반"
                        )
                    remaining -= len(piece)
                    if scanned is not None:
                        scanned[0] += len(piece)
                        self._check_recover_budget(scanned[0])
                    data = carry + piece
                    *lines, carry = data.split(b"\n")
                    if line_cap is not None and len(carry) > line_cap:
                        # 아직 개행이 오지 않은 부분 줄이 이미 상한을 넘었다 —
                        # 뒤에 개행이 와도 완결 줄 검사를 통과할 수 없으므로
                        # 여기서 거부한다(EOF 까지 누적하지 않는다).
                        raise JournalRecoveryError(
                            f"{path}: 개행 없는 부분 줄이 줄 상한({line_cap}바이트)을 초과 — "
                            "오염된 원장은 조용히 건너뛰지 않는다"
                        )
                    for line in lines:
                        if not line.strip():
                            continue
                        line_no += 1
                        if line_cap is not None and len(line) > line_cap:
                            raise JournalRecoveryError(
                                f"{path}:{line_no}: journal 줄이 줄 상한"
                                f"({line_cap}바이트)을 초과 — 오염된 원장은 "
                                "조용히 건너뛰지 않는다"
                            )
                        count += self._validate_line(path, line_no, line)
            if self._recover_deadline is not None and monotonic() > self._recover_deadline:
                raise JournalRecoveryError(f"{path}: 재생 검증이 기한을 초과 — 기동 거부")
            if (
                self._recover_cpu_budget is not None
                and process_time() - self._recover_cpu_start > self._recover_cpu_budget
            ):
                raise JournalRecoveryError(f"{path}: 재생 검증이 CPU 예산을 초과 — 기동 거부")
        except OSError as exc:
            raise JournalRecoveryError(
                f"{path}: journal 읽기 실패 — {type(exc).__name__}: {exc}"
            ) from exc
        if carry.strip():
            if line_cap is not None and len(carry) > line_cap:
                raise JournalRecoveryError(
                    f"{path}: torn tail 이 줄 상한({line_cap}바이트)을 초과 — "
                    "오염된 원장은 조용히 건너뛰지 않는다"
                )
            if not truncate_torn_tail:
                return count
            if not tolerate_torn_tail:
                raise JournalRecoveryError(
                    f"{path}: 봉인된 세그먼트에 완결되지 않은 줄이 있다 "
                    f"({len(carry)}바이트) — 회전은 fsync 완결 후에만 일어나므로 "
                    "설명되지 않는 상태다"
                )
            logger.warning(
                "%s: torn tail %d바이트 격리(부분 쓰기 후 중단 흔적) — 완결되지 않은 레코드",
                path,
                len(carry),
            )
            try:
                with path.open("r+b") as handle:
                    handle.truncate(size - len(carry))
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise JournalRecoveryError(
                    f"{path}: torn tail 격리(truncate) 실패 — {type(exc).__name__}: {exc}"
                ) from exc
        return count

    def _validate_line(self, path: Path, line_no: int, line: bytes) -> int:
        """한 완결 줄의 형식 검증 — 오염은 거부한다(건너뛰지 않는다)."""
        _run_line_validator(self._line_validator, path, line_no, line)
        try:
            parsed: Any = json.loads(line)
        except (ValueError, RecursionError) as exc:
            raise JournalRecoveryError(
                f"{path}:{line_no}: journal 줄이 JSON 이 아니다 — {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise JournalRecoveryError(
                f"{path}:{line_no}: journal 레코드가 object 가 아니다 "
                f"({type(parsed).__name__}) — 오염된 원장은 조용히 건너뛰지 않는다"
            )
        return 1

    def replay(self) -> list[dict[str, Any]]:
        """순서 보존된 완결 레코드 스냅샷(기동 시 재생분 + 이후 성공한 append).

        ``deepcopy`` 로 반환한다 — top-level 얕은 복사만으로는 레코드 내부의
        가변 객체(중첩 dict/list, 예: siteFrame)가 호출자와 공유돼, 호출자가
        반환값을 변형하면 감사 원장의 내부 상태까지 조용히 오염될 수 있다.

        ``retain_records=False`` 로 열린 인스턴스는 전체 목록을 보관하지
        않으므로 재생을 거부한다(fail-closed) — 호출자는 :meth:`stream_records`
        와 :meth:`read_record_at` 의 bounded 읽기를 사용해야 한다.
        """
        with self._lock:
            if not self._retain_records:
                raise JournalError(
                    f"{self._path}: retained record list disabled for this bounded "
                    "instance — use bounded stream reads"
                )
            return copy.deepcopy(self._records)

    @property
    def record_count(self) -> int:
        """기동 시 재생분 + 이후 성공한 append 의 총 개수(보관 모드와 무관)."""
        with self._lock:
            return self._record_count

    @property
    def retains_records(self) -> bool:
        """재생 목록 보관 여부 — False 면 전체 재생이 거부되고 bounded 읽기만 된다."""
        return self._retain_records

    @property
    def file_count(self) -> int:
        """재생 순서의 파일 수 — 봉인 세그먼트 수 + 활성 파일 1."""
        with self._lock:
            return len(self._ordered_files())

    def _ordered_files(self) -> list[tuple[Path, bool]]:
        """재생 순서의 파일 목록 — 봉인 세그먼트 오름차순 + 활성 파일."""
        return [(path, False) for _, path in self._existing_segments()] + [(self._path, True)]

    def stream_records(
        self,
        cursor: tuple[int, int],
        *,
        limit_records: int,
        limit_bytes: int,
        max_line_bytes: int,
    ) -> tuple[list[tuple[int, int, int, dict[str, Any]]], tuple[int, int], bool]:
        """(existing parsed-batch API — see :meth:`stream_record_bytes`.)"""
        return self._stream_records_impl(
            cursor,
            limit_records=limit_records,
            limit_bytes=limit_bytes,
            max_line_bytes=max_line_bytes,
            parse=True,
        )

    def stream_record_bytes(
        self,
        cursor: tuple[int, int],
        *,
        limit_records: int,
        limit_bytes: int,
        max_line_bytes: int,
    ) -> tuple[list[tuple[int, int, int, bytes]], tuple[int, int], bool]:
        """Cursor-bounded forward read returning RAW line bytes, no parsing.

        Delivery-mode audit boot uses this instead of :meth:`stream_records`:
        the caller validates one raw line at a time (structural pre-gate plus
        ``model_validate_json``), so a malicious structural shape is refused
        before any generic parsed object — let alone a deep copy of it — is
        ever accumulated. Byte accounting (``limit_bytes``, ``consumed``) and
        cursor/torn-tail semantics are identical to the parsed variant.
        """
        return self._stream_records_impl(
            cursor,
            limit_records=limit_records,
            limit_bytes=limit_bytes,
            max_line_bytes=max_line_bytes,
            parse=False,
        )

    def _stream_records_impl(
        self,
        cursor: tuple[int, int],
        *,
        limit_records: int,
        limit_bytes: int,
        max_line_bytes: int,
        parse: bool,
    ) -> tuple[list[tuple[int, int, int, Any]], tuple[int, int], bool]:
        """커서 이후의 bounded 순방향 읽기 — 전체 재생 없이 꼬리/이력 인덱싱용.

        ``cursor`` 는 ``(file_index, offset)`` 이며 ``file_index`` 는 봉인
        세그먼트 오름차순 뒤 활성 파일을 이은 순서다. 반환은
        ``(items, next_cursor, eof)`` 이고 각 item 은
        ``(file_index, record_offset, record_length, record_dict)`` 다. RAM
        사용량은 요청 한도와 청크 상수에 묶이며 저널 크기와 무관하다.

        커서는 항상 정확한 다음 미판독 바이트를 가리킨다: 한도 도달·청크
        경계·torn tail 어디에서 멈추든 읽지 않은 바이트는 버려지지 않으며,
        ``eof`` 는 모든 파일이 완전히 소비되고 남은 부분 줄이 없을 때만 참이다.
        완결 줄 검증(JSON/dict)은 전체 재생과 동일하고, 활성 파일 끝의 torn
        tail 은 잘라내지 않고 멈춘다(격리는 writer 기동의 소관). 세그먼트 끝의
        부분 줄·순서 밖 파일 목록 변경은 오염/경합으로 거부한다. 줄 상한을
        넘는 줄은 오염으로 거부한다(``max_line_bytes`` 는 반드시 호출자 한도
        이하여야 하며, 상한 초과 줄 때문에 한도를 넘겨 읽지 않는다).
        """
        if (
            type(cursor) is not tuple
            or len(cursor) != 2
            or any(type(value) is not int or value < 0 for value in cursor)
        ):
            raise ValueError("stream cursor must be a (file_index, offset) int pair")
        if (
            type(limit_records) is not int
            or limit_records <= 0
            or type(limit_bytes) is not int
            or limit_bytes <= 0
            or type(max_line_bytes) is not int
            or max_line_bytes <= 0
        ):
            raise ValueError("stream limits must be positive integers")
        if max_line_bytes > limit_bytes:
            raise ValueError("max_line_bytes must fit inside the caller byte budget")
        with self._lock:
            files = self._ordered_files()
            file_index, offset = cursor
            items: list[tuple[int, int, int, Any]] = []
            consumed = 0
            while file_index < len(files):
                path, active = files[file_index]
                if active and offset == 0 and not path.exists():
                    # The active file is created lazily on first append; a
                    # missing file at offset zero is an empty tail, not corruption.
                    file_index += 1
                    continue
                size = self._stream_file_size(path)
                if offset > size:
                    raise JournalRecoveryError(
                        f"{path}: stream offset {offset}이 파일 크기 {size}를 초과 — "
                        "회전/교체 후 오래된 커서"
                    )
                offset, consumed, file_done = self._stream_file_chunk(
                    path,
                    file_index,
                    active,
                    offset,
                    size,
                    items,
                    consumed,
                    limit_records,
                    limit_bytes,
                    max_line_bytes,
                    parse,
                )
                if file_done:
                    file_index += 1
                    offset = 0
                else:
                    break
            return items, (file_index, offset), file_index >= len(files)

    def _stream_file_chunk(
        self,
        path: Path,
        file_index: int,
        active: bool,
        offset: int,
        size: int,
        items: list[tuple[int, int, int, Any]],
        consumed: int,
        limit_records: int,
        limit_bytes: int,
        max_line_bytes: int,
        parse: bool,
    ) -> tuple[int, int, bool]:
        """한 파일에서 한도까지 완결 줄을 읽는다 — (다음offset, 누적소비, 완료여부).

        다음offset 은 정확히 다음 미판독 바이트다: 한도에 걸려 멈추면 멈춘
        줄의 시작을, torn tail 에 걸리면 tail 시작을, 끝까지 읽으면 파일 끝을
        가리킨다.
        """
        with path.open("rb") as handle:
            handle.seek(offset)
            file_pos = offset
            pending = b""
            pending_off = offset
            while len(items) < limit_records and consumed < limit_bytes:
                if file_pos >= size:
                    break
                read_size = min(self._STREAM_CHUNK_BYTES, size - file_pos, limit_bytes - consumed)
                if read_size <= 0:
                    break
                piece = handle.read(read_size)
                if not piece:
                    raise JournalRecoveryError(
                        f"{path}: journal 읽기 중 예기치 않은 EOF — 단일 writer 불변식 위반"
                    )
                file_pos += len(piece)
                consumed += len(piece)
                data = pending + piece
                base = pending_off
                pos = 0
                exhausted = False
                while True:
                    newline = data.find(b"\n", pos)
                    if newline == -1:
                        pending = data[pos:]
                        pending_off = base + pos
                        if len(pending) > max_line_bytes:
                            raise JournalRecoveryError(
                                f"{path}: offset {pending_off}의 부분 줄이 줄 상한"
                                f"({max_line_bytes}바이트)을 초과 — 오염된 원장은 "
                                "조용히 건너뛰지 않는다"
                            )
                        break
                    line = data[pos:newline]
                    line_off = base + pos
                    pos = newline + 1
                    if len(line) > max_line_bytes:
                        raise JournalRecoveryError(
                            f"{path}: offset {line_off}의 줄이 줄 상한"
                            f"({max_line_bytes}바이트)을 초과 — 오염된 원장은 "
                            "조용히 건너뛰지 않는다"
                        )
                    if not line.strip():
                        continue
                    if len(items) >= limit_records:
                        pending = data[line_off - base :]
                        pending_off = line_off
                        exhausted = True
                        break
                    items.append(
                        (
                            file_index,
                            line_off,
                            len(line) + 1,
                            self._parse_stream_line(path, line_off, line)
                            if parse
                            else bytes(line),
                        )
                    )
                if exhausted:
                    return pending_off, consumed, False
                pending = data[pos:]
                pending_off = base + pos
                if len(pending) > max_line_bytes:
                    # 한도·청크 경계에서 멈춘 부분 줄도 여기서 검사한다 —
                    # 다음 호출이 재개하기 전에 상한 초과를 확정하므로
                    # 개행 없는 입력이 호출을 거듭해도 누적되지 않는다.
                    raise JournalRecoveryError(
                        f"{path}: offset {pending_off}의 부분 줄이 줄 상한"
                        f"({max_line_bytes}바이트)을 초과 — 오염된 원장은 "
                        "조용히 건너뛰지 않는다"
                    )
            if file_pos >= size and not pending:
                return file_pos, consumed, True
            if file_pos >= size and pending:
                if not active:
                    raise JournalRecoveryError(
                        f"{path}: 봉인된 세그먼트에 완결되지 않은 줄이 있다 ({len(pending)}바이트)"
                    )
                return pending_off, consumed, False
            return pending_off if pending else file_pos, consumed, False

    @staticmethod
    def _parse_stream_line(path: Path, record_offset: int, line: bytes) -> dict[str, Any]:
        try:
            parsed: Any = json.loads(line)
        except (ValueError, RecursionError) as exc:
            raise JournalRecoveryError(
                f"{path}: offset {record_offset}의 줄이 JSON 이 아니다 — {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise JournalRecoveryError(
                f"{path}: offset {record_offset}의 레코드가 object 가 아니다 "
                f"({type(parsed).__name__}) — 오염된 원장은 조용히 건너뛰지 않는다"
            )
        return copy.deepcopy(parsed)

    @staticmethod
    def _stream_file_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError as exc:
            raise JournalRecoveryError(
                f"{path}: journal 크기 조회 실패 — {type(exc).__name__}: {exc}"
            ) from exc

    def read_record_at(
        self, file_index: int, offset: int, length: int, *, max_bytes: int
    ) -> dict[str, Any]:
        """인덱스가 가리킨 단일 레코드의 bounded 읽기 — 이력 조회용.

        정확히 ``length`` 바이트를 읽어 개행 종결·JSON·object 를 검증한다.
        범위 밖·형식 위반은 오염으로 거부한다. 호출자 잠금과 직렬화된다.
        """
        if (
            type(file_index) is not int
            or file_index < 0
            or type(offset) is not int
            or offset < 0
            or type(length) is not int
            or length <= 0
            or type(max_bytes) is not int
            or max_bytes <= 0
            or length > max_bytes
        ):
            raise ValueError("record address and bounds must be positive integers")
        with self._lock:
            files = self._ordered_files()
            if file_index >= len(files):
                raise JournalRecoveryError(
                    f"{self._path}: 레코드 주소의 파일 번호 {file_index}가 범위 밖 — "
                    "회전/교체 후 오래된 인덱스"
                )
            path, _active = files[file_index]
            try:
                with path.open("rb") as handle:
                    handle.seek(offset)
                    raw = handle.read(length)
            except OSError as exc:
                raise JournalRecoveryError(
                    f"{path}: offset {offset} 읽기 실패 — {type(exc).__name__}: {exc}"
                ) from exc
            if len(raw) != length or not raw.endswith(b"\n"):
                raise JournalRecoveryError(
                    f"{path}: offset {offset}의 레코드 {length}바이트가 완결되지 않았다"
                )
            return self._parse_stream_line(path, offset, raw[:-1])

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
                if self._retain_records:
                    self._records.append(copy.deepcopy(dict(record)))
                self._record_count += 1
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

    @property
    def path(self) -> Path:
        """저널 파일 경로 — 파생 인덱스 파일 배치 등 조립용 읽기 전용 공개."""
        return self._path

    @property
    def recover_deadline(self) -> float | None:
        """기동 스캔의 절대 기한 — 호출자가 명시한 monotonic 시점 그대로.

        감사 저장소는 이 값을 부팅 전체(재생·인덱스 검증·재구축·적재)의
        유일한 wall 기한으로 재사용한다 — 새 타이머를 만들지 않으므로
        단계별 합산 초과가 생기지 않는다. ``None`` 은 레거시 보관 열기다.
        """
        return self._recover_deadline

    @property
    def open_monotonic(self) -> float:
        """저널 생성자가 열린 wall 시점 — 감사 부팅과 공유하는 절대 기한의 기준.

        감사 저장소는 이 시점에 작업집합 ``max_boot_seconds`` 를 더해 wall
        기한을 재구성하므로(조립이 명시 기한을 주지 않은 레거시 열기 포함),
        재생에 이미 쓴 시간이 부팅 예산 밖으로 빠지지 않는다.
        """
        return self._open_monotonic

    @property
    def open_cpu_start(self) -> float:
        """저널 생성자가 열린 CPU 시점 — 감사 부팅과 공유하는 CPU 예산의 기준."""
        return self._open_process_time

    @property
    def recover_cpu_start(self) -> float:
        """재생 CPU 측정의 기준 — 호출자 지정이 없으면 open 시점과 같다."""
        return self._recover_cpu_start

    @property
    def recover_cpu_budget(self) -> float | None:
        """재생·감사 부팅이 공유하는 CPU 예산 — ``None`` 은 레거시 무제한."""
        return self._recover_cpu_budget

    @property
    def max_recover_bytes(self) -> int | None:
        """기동 스캔의 총 바이트 예산 — 호출자가 명시한 값 그대로."""
        return self._max_recover_bytes

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
