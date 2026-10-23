"""Private derived index over the authoritative download-audit journal.

The journal stays the sole authority; this sqlite file is a reconstructible
projection that lets the working-set store serve historical queries and
identity lookups with bounded seeks instead of full-history RAM or scans.
It is never proof of absence: every lookup miss on a validated-current index
means genuinely-absent-only because the index is transactionally committed
with each journal append and re-validated on boot. Missing, corrupt or stale
derived state is rebuilt within explicit bounds or refuses.

No audit meaning lives here — the store decides terminality, equality and
admission. This module only stores addressed rows and enforces its own
storage bounds (page cap) and crash atomicity (single transaction per
commit, validated checkpoint).
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import stat
from collections.abc import Callable
from pathlib import Path


class AuditIndexError(RuntimeError):
    """Derived-index storage failure — the caller seals and refuses."""


class AuditIndexCorruption(AuditIndexError):
    """Derived state contradicts itself or the journal — rebuild or refuse."""


class AuditIndexFull(AuditIndexError):
    """Derived storage hit its explicit page budget — deny bytes, never spill."""


_FORMAT_VERSION = "audit-history-index.v1"
_PAGE_SIZE = 4096

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
    session_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    terminal_action TEXT,
    last_seq INTEGER NOT NULL,
    event_count INTEGER NOT NULL,
    created_seq INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_active_created ON sessions(created_seq)
    WHERE terminal_action IS NULL;
CREATE TABLE IF NOT EXISTS events(
    event_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    session_id TEXT NOT NULL,
    file_index INTEGER NOT NULL,
    offset INTEGER NOT NULL,
    length INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_seq ON events(seq);
CREATE TABLE IF NOT EXISTS session_order(
    session_id TEXT NOT NULL,
    session_seq INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    PRIMARY KEY(session_id, session_seq)
);
CREATE INDEX IF NOT EXISTS session_order_by_seq ON session_order(seq);
CREATE INDEX IF NOT EXISTS sessions_by_created ON sessions(created_seq);
CREATE INDEX IF NOT EXISTS events_by_session ON events(session_id);
"""


def _private_dir_ok(directory: Path) -> None:
    """Owner-private directory chain — reject symlinks and substitutable ancestors.

    Mirrors the download spool gate: every component must be owned by root or
    the caller, no group/other-writable ancestor without the sticky bit plus
    caller-owned child, and the leaf must be an owner-private 0700 directory.
    """
    descriptors: list[int] = []
    try:
        if not directory.is_absolute() or ".." in directory.parts:
            raise AuditIndexError("index directory must be an absolute path")
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        descriptors.append(parent)
        for part in directory.parts[1:]:
            previous = os.fstat(parent)
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
            )
            descriptors.append(child)
            current = os.fstat(child)
            if current.st_uid not in (0, os.geteuid()) or (
                previous.st_mode & 0o022
                and not (previous.st_mode & stat.S_ISVTX and current.st_uid == os.geteuid())
            ):
                raise AuditIndexError("substitutable index ancestor")
            parent = child
        root = os.fstat(parent)
        if (
            root.st_uid != os.geteuid()
            or root.st_gid != os.getegid()
            or stat.S_IMODE(root.st_mode) != 0o700
        ):
            raise AuditIndexError("index directory must be owner-private 0700")
    except OSError as exc:
        raise AuditIndexError(f"cannot validate index directory: {exc}") from exc
    finally:
        for fd in reversed(descriptors):
            with contextlib.suppress(OSError):
                os.close(fd)


class AuditHistoryIndex:
    """Bounded on-disk session/event/offset index with a validated checkpoint."""

    def __init__(
        self,
        path: Path,
        *,
        max_pages: int,
        create: bool = False,
        deadline: Callable[[], bool] | None = None,
    ) -> None:
        if type(max_pages) is not int or max_pages <= 0:
            raise ValueError("index page budget must be a positive integer")
        if deadline is not None and not callable(deadline):
            raise ValueError("index deadline watch requires a callable")
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("index path must be absolute")
        _private_dir_ok(path.parent)
        if path.is_symlink():
            raise AuditIndexError("index file must not be a symlink")
        if not create and not path.exists():
            raise AuditIndexError("index file is missing")
        if create and not path.exists():
            # Owner-private from the first byte: no umask-dependent window
            # and no follow of a planted alias.
            try:
                fd = os.open(
                    path,
                    os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_RDWR,
                    0o600,
                )
            except FileExistsError:
                pass
            except OSError as exc:
                raise AuditIndexError(f"cannot create index file: {exc}") from exc
            else:
                os.close(fd)
        try:
            self._validate_file(path)
            connection = sqlite3.connect(
                str(path), check_same_thread=False, isolation_level=None, timeout=0
            )
        except AuditIndexError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise AuditIndexError(f"cannot open index: {exc}") from exc
        self._connection = connection
        self._path = path
        self._closed = False
        try:
            if deadline is not None:
                # Enforce the shared boot budget before any potentially
                # costly SQL below (pragmas, page-budget probes, schema
                # build): a long statement must abort on wall OR CPU
                # exhaustion, not merely be noticed by a later
                # between-operations check.
                self.watch_deadline(deadline)
            self._configure(max_pages)
            fresh_schema = create and self._is_empty()
            # Files we refuse (wrong page size, oversize budget) are never
            # written: the budget check runs before any schema statement.
            self._check_page_budget(max_pages)
            # The schema is ensured on every accepted open, not just on
            # creation, so an index file written by an older revision gains
            # the covering indexes new verification queries rely on (tables
            # and indexes are all IF NOT EXISTS; user_version stays the same
            # compatible lineage). Content rows are never touched here.
            self._connection.executescript(_SCHEMA)
            if fresh_schema:
                self._connection.execute("PRAGMA user_version = 1")
        except AuditIndexError:
            self._close_quiet()
            raise
        except sqlite3.Error as exc:
            self._close_quiet()
            raise AuditIndexError(f"cannot initialize index: {exc}") from exc

    @staticmethod
    def _validate_file(path: Path) -> None:
        """Owner-private regular file, created 0600 by its owner — refuse the rest.

        쓰기 전에 별칭을 고정한다: 심볼릭 링크·디렉터리·하드링크(``st_nlink``)
        는 모두 거부한다. 하드링크된 인덱스에 쓰면 같은 바이트를 가리키는
        다른 경로가 파생 상태와 어긋나게 바뀔 수 있으므로, 쓰기 가능한
        열기는 링크 수 1인 단일 경로에서만 허용한다.
        """
        try:
            entry = os.lstat(path)
        except OSError as exc:
            raise AuditIndexError(f"cannot inspect index file: {exc}") from exc
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode):
            raise AuditIndexError("index file must be a regular file, never an alias")
        if entry.st_uid != os.geteuid() or stat.S_IMODE(entry.st_mode) != 0o600:
            raise AuditIndexError("index file must be 0600 owned by the caller")
        if entry.st_nlink != 1:
            raise AuditIndexError("index file must not be hard-linked before writable open")

    def _is_empty(self) -> bool:
        try:
            return self._path.stat().st_size == 0
        except OSError as exc:
            raise AuditIndexError(f"cannot stat index file: {exc}") from exc

    def _check_page_budget(self, max_pages: int) -> None:
        if self.page_size() != _PAGE_SIZE:
            raise AuditIndexCorruption(
                f"index page size is not {_PAGE_SIZE} — rebuild, never reinterpret"
            )
        if self.page_count() > max_pages:
            raise AuditIndexCorruption(
                "index already exceeds its page budget — refuse, never grow past it"
            )

    def page_size(self) -> int:
        try:
            row = self._connection.execute("PRAGMA page_size").fetchone()
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index page-size probe failed: {exc}") from exc
        try:
            return int(row[0])
        except (TypeError, ValueError) as exc:
            raise AuditIndexCorruption(f"index page size unreadable: {row!r}") from exc

    def page_count(self) -> int:
        try:
            row = self._connection.execute("PRAGMA page_count").fetchone()
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index page-count probe failed: {exc}") from exc
        try:
            return int(row[0])
        except (TypeError, ValueError) as exc:
            raise AuditIndexCorruption(f"index page count unreadable: {row!r}") from exc

    def _configure(self, max_pages: int) -> None:
        cur = self._connection.cursor()
        try:
            cur.execute("PRAGMA journal_mode = DELETE")
            if cur.fetchone()[0].lower() != "delete":
                raise AuditIndexError("index requires rollback-journal mode")
            cur.execute("PRAGMA synchronous = FULL")
            cur.execute(f"PRAGMA page_size = {_PAGE_SIZE}")
            cur.execute("PRAGMA cache_size = -32")
            cur.execute("PRAGMA temp_store = MEMORY")
            # Native memory is bounded structurally, not by assertion: no
            # memory-mapped I/O, a fixed 32 KiB page cache, in-RAM temp that
            # the indexed query plans below never spill into, and a hard
            # page budget. Every setting is read back — a silent ignore
            # would void the accounting the store reports.
            cur.execute("PRAGMA mmap_size = 0")
            cur.execute("PRAGMA mmap_size")
            if int(cur.fetchone()[0]) != 0:
                raise AuditIndexCorruption("index mmap could not be disabled")
            cur.execute("PRAGMA busy_timeout = 0")
            cur.execute("PRAGMA busy_timeout")
            if int(cur.fetchone()[0]) != 0:
                raise AuditIndexCorruption("index busy wait could not be disabled")
            cur.execute(f"PRAGMA max_page_count = {max_pages}")
            # 적용 거부는 조용히 넘기지 않는다 — 예산 밖 증가는 무한정 자라기
            # 전에 여기서 드러나야 한다.
            cur.execute("PRAGMA max_page_count")
            applied = cur.fetchone()[0]
            try:
                applied_pages = int(applied)
            except (TypeError, ValueError) as exc:
                raise AuditIndexCorruption(
                    f"index page budget unreadable: {applied!r}"
                ) from exc
            if applied_pages != max_pages:
                raise AuditIndexCorruption(
                    f"index page budget refused: wanted {max_pages}, store reports {applied_pages}"
                )
            cur.execute("PRAGMA foreign_keys = OFF")
        finally:
            cur.close()

    def _close_quiet(self) -> None:
        with contextlib.suppress(sqlite3.Error):
            self._connection.close()
        self._closed = True

    def close(self) -> None:
        if not self._closed:
            self._close_quiet()

    @property
    def path(self) -> Path:
        return self._path

    def file_bytes(self) -> int:
        try:
            return self._path.stat().st_size
        except OSError as exc:
            raise AuditIndexError(f"cannot stat index: {exc}") from exc

    def quick_check(self) -> None:
        """Bounded integrity probe (file is page-capped, so this scan is bounded)."""
        try:
            row = self._connection.execute("PRAGMA quick_check").fetchone()
        except sqlite3.Error as exc:
            raise AuditIndexCorruption(f"index integrity probe failed: {exc}") from exc
        if row is None or row[0] != "ok":
            raise AuditIndexCorruption(f"index integrity probe refused: {row!r}")

    def user_version(self) -> int:
        try:
            return int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise AuditIndexCorruption(f"cannot read index version: {exc}") from exc

    def data_version(self) -> int:
        """SQLite ``data_version`` — 이 연결 밖의 쓰기를 감지하는 상수 크기 표식.

        저장소는 자체 커밋마다 이 값을 갱신한다. RUN 중 값이 달라져 있으면
        다른 작성자가 파생 상태를 건드린 것이므로 miss 를 신뢰하지 않고
        봉인한다. 래핑될 수 있어 단독 증거는 아니고 체크포인트·저널 표식과
        함께 사용한다.
        """
        try:
            row = self._connection.execute("PRAGMA data_version").fetchone()
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index data-version probe failed: {exc}") from exc
        try:
            return int(row[0])
        except (TypeError, ValueError) as exc:
            raise AuditIndexCorruption(f"index data version unreadable: {row!r}") from exc

    def verify_linkage(self) -> None:
        """세션/이벤트/순서 행의 상호 참조를 존재성 SQL 로 검증한다.

        행 삭제·잘못된 세션 귀속 같은 논리 rows divergence 는 여기서 걸린다 —
        부팅 대응 검증이 이 검사를 통과해야 인덱스 부재를 진짜 부재로 믿는다.
        모든 검사는 인덱스 탐색 + 존재성 단락이라 파이썬 RAM 을 쓰지 않고,
        임시 정렬도 없다(``session_order_by_seq``·PK·``events_by_seq`` 사용).
        세션 요약 필드는 이 검사가 아니라 저널 바이트와 대조하는 대응
        검증이 담당한다.
        """
        checks = (
            "SELECT 1 FROM events e WHERE NOT EXISTS"
            " (SELECT 1 FROM sessions s WHERE s.session_id = e.session_id) LIMIT 1",
            "SELECT 1 FROM session_order o WHERE NOT EXISTS"
            " (SELECT 1 FROM sessions s WHERE s.session_id = o.session_id) LIMIT 1",
            "SELECT 1 FROM session_order o WHERE NOT EXISTS"
            " (SELECT 1 FROM events e WHERE e.seq = o.seq"
            " AND e.session_id = o.session_id) LIMIT 1",
            "SELECT 1 FROM events e WHERE NOT EXISTS"
            " (SELECT 1 FROM session_order o WHERE o.seq = e.seq"
            " AND o.session_id = e.session_id) LIMIT 1",
            "SELECT seq FROM session_order GROUP BY seq HAVING COUNT(*) > 1 LIMIT 1",
        )
        try:
            for query in checks:
                if self._connection.execute(query).fetchone() is not None:
                    raise AuditIndexCorruption(
                        f"indexed session/event/order linkage diverged: {query[:48]}..."
                    )
        except AuditIndexCorruption:
            raise
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index linkage probe failed: {exc}") from exc

    def explain_has_temp_sort(self, query: str, params: tuple = ()) -> bool:
        """해당 쿼리 계획에 임시 B-TREE 정렬이 있는지 — 메모리 상한 테스트용."""
        try:
            plan = "\n".join(
                str(row)
                for row in self._connection.execute(
                    "EXPLAIN QUERY PLAN " + query, params
                ).fetchall()
            )
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index plan probe failed: {exc}") from exc
        return "TEMP B-TREE" in plan

    # -- Transaction boundaries: the store holds these across its critical
    # sections so a hot external writer blocks or fails BEFORE the journal
    # is touched, instead of forking history underneath a check-then-act.

    def begin_write(self) -> None:
        """서술형 쓰기 경계 시작 — 외부 작성자는 여기서 막히거나 실패한다."""
        try:
            self._connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index write boundary refused: {exc}") from exc

    def commit_write(self) -> None:
        try:
            self._connection.execute("COMMIT")
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index write commit failed: {exc}") from exc

    def rollback_write(self) -> None:
        with contextlib.suppress(sqlite3.Error):
            self._connection.execute("ROLLBACK")

    def begin_read(self) -> None:
        """읽기 스냅샷 경계 — 판독 중 외부 커밋이 보여주는 값을 바꾸지 못한다."""
        try:
            self._connection.execute("BEGIN")
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index read boundary refused: {exc}") from exc

    def end_read(self) -> None:
        try:
            self._connection.execute("COMMIT")
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.Error):
                self._connection.execute("ROLLBACK")
            raise AuditIndexError(f"index read boundary failed: {exc}") from exc

    def watch_deadline(self, is_past: object) -> None:
        """VM 진행 감시 — 기한이 지나면 진행 중인 SQL 을 즉시 중단한다.

        ``is_past`` 는 무인자 호출 가능자여야 하며 기한 초과 시 참을
        돌려준다. 중단은 ``sqlite3.OperationalError`` 로 표면화되고,
        호출자가 기한 초과 여부를 재확인해 fail-closed 로 분류한다.
        """
        if not callable(is_past):
            raise ValueError("deadline watch requires a callable")
        try:
            self._connection.set_progress_handler(lambda: 1 if is_past() else 0, 1000)
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index deadline watch failed: {exc}") from exc

    def unwatch_deadline(self) -> None:
        with contextlib.suppress(sqlite3.Error):
            self._connection.set_progress_handler(None, 0)

    def get_meta(self, key: str) -> str | None:
        try:
            row = self._connection.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index meta read failed: {exc}") from exc
        return row[0] if row is not None else None

    def commit_event(
        self,
        *,
        seq: int,
        event_id: str,
        session_id: str,
        organization_id: str,
        terminal_action: str | None,
        file_index: int,
        offset: int,
        length: int,
        session_position: int,
        checkpoint_meta: dict[str, str],
    ) -> None:
        """Index one journal record and advance the checkpoint atomically.

        ``session_position`` is the event's 0-based order inside its session.
        Re-committing the identical row is an exact no-op; a conflicting row
        under the same key is corruption, never an overwrite.
        """
        if (
            type(seq) is not int
            or seq <= 0
            or type(file_index) is not int
            or file_index < 0
            or type(offset) is not int
            or offset < 0
            or type(length) is not int
            or length <= 0
            or type(session_position) is not int
            or session_position < 0
        ):
            raise AuditIndexCorruption("indexed address must use explicit bounded integers")
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._commit_event_locked(
                    connection,
                    seq=seq,
                    event_id=event_id,
                    session_id=session_id,
                    organization_id=organization_id,
                    terminal_action=terminal_action,
                    file_index=file_index,
                    offset=offset,
                    length=length,
                    session_position=session_position,
                    checkpoint_meta=checkpoint_meta,
                )
                connection.execute("COMMIT")
            except BaseException:
                with contextlib.suppress(sqlite3.Error):
                    connection.execute("ROLLBACK")
                raise
        except AuditIndexCorruption:
            raise
        except sqlite3.Error as exc:
            if isinstance(exc, sqlite3.OperationalError) and "full" in str(exc).lower():
                raise AuditIndexFull(f"index page budget exhausted: {exc}") from exc
            raise AuditIndexError(f"index commit failed: {exc}") from exc

    def commit_event_in_write_txn(
        self,
        *,
        seq: int,
        event_id: str,
        session_id: str,
        organization_id: str,
        terminal_action: str | None,
        file_index: int,
        offset: int,
        length: int,
        session_position: int,
        checkpoint_meta: dict[str, str],
    ) -> None:
        """``commit_event`` without its own transaction — the caller holds one.

        The store's append path holds ``begin_write`` from binding validation
        through the journal fsync to this commit, so a hot external writer
        blocks or fails before the journal is ever touched. Validation,
        failure mapping and the exact-noop/conflict rules are identical.
        """
        if (
            type(seq) is not int
            or seq <= 0
            or type(file_index) is not int
            or file_index < 0
            or type(offset) is not int
            or offset < 0
            or type(length) is not int
            or length <= 0
            or type(session_position) is not int
            or session_position < 0
        ):
            raise AuditIndexCorruption("indexed address must use explicit bounded integers")
        try:
            self._commit_event_locked(
                self._connection,
                seq=seq,
                event_id=event_id,
                session_id=session_id,
                organization_id=organization_id,
                terminal_action=terminal_action,
                file_index=file_index,
                offset=offset,
                length=length,
                session_position=session_position,
                checkpoint_meta=checkpoint_meta,
            )
        except AuditIndexCorruption:
            raise
        except sqlite3.Error as exc:
            if isinstance(exc, sqlite3.OperationalError) and "full" in str(exc).lower():
                raise AuditIndexFull(f"index page budget exhausted: {exc}") from exc
            raise AuditIndexError(f"index commit failed: {exc}") from exc

    @staticmethod
    def _commit_event_locked(
        connection: sqlite3.Connection,
        *,
        seq: int,
        event_id: str,
        session_id: str,
        organization_id: str,
        terminal_action: str | None,
        file_index: int,
        offset: int,
        length: int,
        session_position: int,
        checkpoint_meta: dict[str, str],
    ) -> None:
        """Single-transaction event+session+checkpoint commit (no BEGIN/COMMIT)."""
        existing_session = connection.execute(
            "SELECT organization_id, terminal_action, last_seq, event_count"
            " FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if existing_session is None:
            if session_position != 0:
                raise AuditIndexCorruption("new indexed session must start at position 0")
            connection.execute(
                "INSERT INTO sessions(session_id, organization_id, terminal_action,"
                " last_seq, event_count, created_seq) VALUES(?, ?, ?, ?, 1, ?)",
                (session_id, organization_id, terminal_action, seq, seq),
            )
        else:
            if existing_session[0] != organization_id:
                raise AuditIndexCorruption("indexed session changed organization")
            if existing_session[1] is not None:
                raise AuditIndexCorruption("indexed session already terminal")
            if session_position != existing_session[3]:
                raise AuditIndexCorruption("indexed session position diverged")
            connection.execute(
                "UPDATE sessions SET terminal_action = ?, last_seq = ?,"
                " event_count = event_count + 1 WHERE session_id = ?",
                (terminal_action, seq, session_id),
            )
        existing_event = connection.execute(
            "SELECT seq, session_id, file_index, offset, length FROM events"
            " WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if existing_event is None:
            connection.execute(
                "INSERT INTO events(event_id, seq, session_id, file_index, offset,"
                " length) VALUES(?, ?, ?, ?, ?, ?)",
                (event_id, seq, session_id, file_index, offset, length),
            )
            connection.execute(
                "INSERT INTO session_order(session_id, session_seq, seq) VALUES(?, ?, ?)",
                (session_id, session_position, seq),
            )
        elif tuple(existing_event) != (seq, session_id, file_index, offset, length):
            raise AuditIndexCorruption("indexed event identity diverged")
        for key, value in checkpoint_meta.items():
            connection.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def find_event(self, event_id: str) -> tuple[int, str, int, int, int] | None:
        """(seq, session_id, file_index, offset, length) or None when absent."""
        try:
            row = self._connection.execute(
                "SELECT seq, session_id, file_index, offset, length FROM events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index event lookup failed: {exc}") from exc
        return tuple(row) if row is not None else None

    def has_session(self, session_id: str) -> bool:
        try:
            row = self._connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index session lookup failed: {exc}") from exc
        return row is not None

    def session_terminal(self, session_id: str) -> str | None:
        """Terminal action, None for unfinished; raises when the session is unknown."""
        try:
            row = self._connection.execute(
                "SELECT organization_id, terminal_action FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index session lookup failed: {exc}") from exc
        if row is None:
            raise AuditIndexCorruption("indexed session vanished")
        return row[1]

    def session_organization(self, session_id: str) -> str:
        try:
            row = self._connection.execute(
                "SELECT organization_id FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index session lookup failed: {exc}") from exc
        if row is None:
            raise AuditIndexCorruption("indexed session vanished")
        return str(row[0])

    def session_events(
        self, session_id: str, *, limit: int
    ) -> list[tuple[int, str, int, int, int]]:
        """Ordered (seq, row session, file_index, offset, length), bounded by ``limit``.

        The row session is returned so callers can prove the addressed record
        still belongs to the queried session instead of trusting the pointer.
        """
        if type(limit) is not int or limit <= 0:
            raise ValueError("session query limit must be a positive integer")
        try:
            rows = self._connection.execute(
                "SELECT e.seq, e.session_id, e.file_index, e.offset, e.length"
                " FROM session_order o JOIN events e ON e.seq = o.seq"
                " WHERE o.session_id = ? ORDER BY o.session_seq LIMIT ?",
                (session_id, limit),
            ).fetchall()
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index session query failed: {exc}") from exc
        return [(int(a), str(b), int(c), int(d), int(e)) for a, b, c, d, e in rows]

    def unfinished(self, *, limit: int) -> list[tuple[str, str, int]]:
        """(session_id, organization_id, last_seq) for non-terminal sessions.

        Admission order (``created_seq``) is preserved to match the legacy
        live projection; the partial index serves the filter and the order
        without scanning retained history.
        """
        if type(limit) is not int or limit <= 0:
            raise ValueError("unfinished query limit must be a positive integer")
        try:
            rows = self._connection.execute(
                "SELECT session_id, organization_id, last_seq FROM sessions"
                " WHERE terminal_action IS NULL ORDER BY created_seq LIMIT ?",
                (limit,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index unfinished query failed: {exc}") from exc
        return [(str(a), str(b), int(c)) for a, b, c in rows]

    def stats(self) -> tuple[int, int, int]:
        """(session_count, event_count, max_seq) for boot accounting."""
        try:
            sessions = self._connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            events = self._connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            maximum = self._connection.execute("SELECT MAX(seq) FROM events").fetchone()[0]
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index stats failed: {exc}") from exc
        return int(sessions), int(events), int(maximum or 0)

    def sessions_page(
        self, offset: int, limit: int
    ) -> list[tuple[str, str, str | None, int, int, int]]:
        """One page of session summaries in admission order (``created_seq``).

        Each row is ``(session_id, organization_id, terminal_action,
        last_seq, event_count, created_seq)``. The correspondence check pages
        through every session and re-proves each summary against the
        authoritative journal bytes — a forged ``terminal_action`` or count
        can neither hide unfinished reservations nor invent terminality.
        The ``sessions_by_created`` index serves the order with no temp sort.
        """
        if (
            type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or limit <= 0
        ):
            raise ValueError("session page offset and limit must be bounded integers")
        try:
            rows = self._connection.execute(
                "SELECT session_id, organization_id, terminal_action,"
                " last_seq, event_count, created_seq FROM sessions"
                " ORDER BY created_seq LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index session page failed: {exc}") from exc
        return [
            (str(a), str(b), c if c is None else str(c), int(d), int(e), int(f))
            for a, b, c, d, e, f in rows
        ]

    def event_at(self, session_id: str, session_seq: int) -> str | None:
        """Event ID bound to one ordered session position, or None when absent."""
        try:
            row = self._connection.execute(
                "SELECT e.event_id FROM session_order o JOIN events e ON e.seq = o.seq"
                " WHERE o.session_id = ? AND o.session_seq = ?",
                (session_id, session_seq),
            ).fetchone()
        except sqlite3.Error as exc:
            raise AuditIndexError(f"index order lookup failed: {exc}") from exc
        return str(row[0]) if row is not None else None

    def checkpoint_seq(self) -> int:
        value = self.get_meta("max_seq")
        try:
            return int(value) if value is not None else 0
        except (TypeError, ValueError) as exc:
            raise AuditIndexCorruption(f"index checkpoint is not an integer: {value!r}") from exc

    def set_meta(self, mapping: dict[str, str]) -> None:
        """Write binding/checkpoint keys atomically (boot activation trace)."""
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self.set_meta_in_write_txn(mapping)
                self._connection.execute("COMMIT")
            except BaseException:
                with contextlib.suppress(sqlite3.Error):
                    self._connection.execute("ROLLBACK")
                raise
        except sqlite3.Error as exc:
            if isinstance(exc, sqlite3.OperationalError) and "full" in str(exc).lower():
                raise AuditIndexFull(f"index page budget exhausted: {exc}") from exc
            raise AuditIndexError(f"index meta write failed: {exc}") from exc

    def set_meta_in_write_txn(self, mapping: dict[str, str]) -> None:
        """Upsert binding keys without its own transaction — caller holds one.

        Lets the boot proof adopt its activation trace under the same writer
        boundary as the verification, so no foreign commit can land between
        the proof and the adopted binding. The caller's single releasing
        commit applies these writes atomically.
        """
        try:
            for key, value in mapping.items():
                self._connection.execute(
                    "INSERT INTO meta(key, value) VALUES(?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
        except sqlite3.Error as exc:
            if isinstance(exc, sqlite3.OperationalError) and "full" in str(exc).lower():
                raise AuditIndexFull(f"index page budget exhausted: {exc}") from exc
            raise AuditIndexError(f"index meta write failed: {exc}") from exc
