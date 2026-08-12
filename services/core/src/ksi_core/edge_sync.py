"""Edge→Core EventBundle 멱등 수신·영속 (서버 제품 트랙 1, core-ingest).

:mod:`ksi_event_contracts.offline_sync` 의 :class:`SyncLedger` 가 고정한 판정
규칙(멱등 4중 신원·순번 보존·digest 정합)의 **서버측 배선**이다 — 규칙을 다시
구현하지 않고 SyncLedger 에 위임한다(규칙 중복 = 계약 위반 경로).

## ACK 는 durable 이후에만 (07_API_AND_CONTRACTS §Reliability)

"Core 가 durable persistence 를 확인한 후에만 Edge 가 로컬 데이터를 삭제한다" —
ACK 를 받았는데 서버가 잃으면 그 이벤트는 세상에서 사라진다(Edge 는 이미
지웠다). 그래서 (반증 리뷰 2026-07-29 반영):

- ``ACCEPTED`` 는 append-only journal 에 **flush+fsync 성공 후에만** 반환한다.
  파일·디렉터리가 새로 만들어지는 경우 **부모 디렉터리도 fsync** 한다 — 파일
  데이터만 fsync 하면 머신 크래시에서 디렉터리 엔트리가 사라져 파일째 소실될
  수 있다(P0-1, POSIX fsync 명세).
- journal 줄은 ``ensure_ascii=True`` 로 쓴다 — U+2028/2029/0085 같은 유니코드
  개행 후보가 raw 로 나가면 재적재의 줄 분리가 깨져 ACK 된 원장이 영구 기동
  불가가 된다(P1-2 실측 재현).
- append 실패 시 그 요청은 ACK 없이 실패하고 store 는 **봉인(sealed)** 된다 —
  메모리 원장에만 반영된 채 다음 요청을 받으면 재전송이
  ``DUPLICATE_IGNORED``(ACK)로 둔갑해 유실이 확정된다. 봉인은 OSError 뿐
  아니라 **어떤 예외에서도** 걸린다(P1-1 — MemoryError 등이 같은 형상을 만든다).

## 재시작 복원 (fail-closed + torn-tail 격리)

journal 의 완결 줄(개행으로 끝난 줄)은 전부 과거 ACCEPTED 항목이어야 하며,
하나라도 거부되면 오염이므로 기동을 거부한다. 단 **개행 없이 끝난 마지막
부분 줄(torn tail)은 정의상 ACK 된 적이 없다** — 완결 write+fsync 후에만 ACK
하므로. 이것까지 기동 거부하면 ENOSPC 부분 쓰기(봉인의 가장 흔한 원인) 뒤
서버가 영원히 못 떠서, Edge 가 아직 들고 있는 항목의 재전송 경로 자체가
사라진다(P1-3). 그래서 torn tail 은 잘라내고(경고 로그) 정상 기동한다.

## 원장 스냅샷 (S4 — ops-serving-hardening)

이 원장의 재기동 비용은 **파일 크기가 아니라 항목당 본문 정규화 + sha256** 이다
(``SyncLedger.ingest`` 가 재적재에서도 ``payload_digest`` 를 다시 계산한다). 그래서
세그먼트 회전(``DurableJournal`` 이 Site/Mission/Event 에 쓰는 방식)으로는 이 비용이
줄지 않는다 — 줄 수를 나눠도 총 계산량은 같다.

``snapshot_every`` 를 주면 그만큼 수락할 때마다 원장 상태(본문 없이 신원·순번만)를
``<journal>.snapshot.json`` 으로 굳힌다. 다음 기동은 그 상태를 복원하고 journal 은
스냅샷 경계 **이후 바이트만** 읽는다. 기본값(``None``)은 스냅샷을
**쓰지 않는다**는 뜻이다 — 이미 있는 스냅샷 파일은 그래도 읽는다(안전한 쪽:
경계와 어긋나면 여전히 기동을 거부한다). 스냅샷을 무시하고 전량 재생으로
검증하려면 파일을 치워야 한다(독립 재검토 P2-F).

신뢰 방향이 이 설계의 핵심이다. **스냅샷은 journal 이 부정하는 것을 주장할 수 없다** —
스냅샷이 깨졌거나 규칙을 어기면 버리고 전량 재생한다(느려질 뿐 상태는 정확하다).
반대로 journal 쪽이 스냅샷 경계와 어긋나면(짧아졌다·경계까지의 내용이 바뀌었다·
스냅샷이 주장하는 건수와 실제 줄 수가 다르다) 기동을 거부한다. append-only 파일이
줄어드는 것은 설명되지 않는 상태이고, 그대로 재생하면 두 정본이 조용히 갈라진
원장으로 서비스가 뜬다.

알려진 한계(독립 재검토에서 확인·수용):
- 스냅샷은 재기동 비용만 잡고 **파일 크기 상한은 주지 않는다** — edge-sync
  journal 은 여전히 단조 증가한다. 세그먼트 회전은 이 원장에 아직 없다.
- ``export_state`` 는 델타가 아니라 **전량**이라 스냅샷 크기가 O(n) 이고, 그
  직렬화·기록이 수신 잠금 안에서 일어난다. 항목이 아주 많아지면 주기마다의
  전량 재작성이 스냅샷이 아끼는 비용을 잠식한다 — 델타 스냅샷 또는 세그먼트
  회전과의 결합이 그때의 해법이고, 지금 규모에서는 도입하지 않았다.

## 단일 writer 강제

journal 은 단일 프로세스 전제다 — 두 프로세스가 같은 파일에 append 하면 원장
진실이 갈린다. 기동 시 flock 배타 잠금을 잡고, 실패하면 기동을 거부한다(P2-3).

## payload 는 EventBundle v1.2 만

payload 가 EventBundle(v1.2, standalone classification lineage 포함)로 검증되지
않으면 원장에 반영하지 않고 ``INVALID_EVENT_BUNDLE`` 로 거부한다(INV-031).
다른 산출물 타입은 별도 엔드포인트로 추가한다.

## 인증 장비 신원 바인딩 — 사전인증 순번 봉쇄 해소 (ADR-KSI-008 §2, 장착부)

이전에는(인증 도입 전) 위조된 큰 device_sequence 1건이 그 장비의 후속 수신을
전부 ``SEQUENCE_REGRESSION`` 으로 막을 수 있었다(P1-4, 원장 risk
edge-sync-preauth-sequence-lockout). 이제 :func:`build_edge_sync_router` 의
수신 라우트는 ``require_permission(Permission.EDGE_SYNC_INGEST)`` 로 인증하고,
인증된 ``EDGE_DEVICE`` Principal 의 ``device_id`` 가 요청 본문의
``edgeDeviceId`` 와 다르면 원장에 반영하기 **전에** typed 403
``DEVICE_MISMATCH`` 로 거부한다 — 위조 순번 주입이 장비 신원 뒤로 차단되어
다른 장비를 사칭한 순번 봉쇄가 불가능해졌다. 장비는 자기 last_sequence 조회
API(``GET /v1/edge-sync/devices/{device_id}/sequence``)로 복구 경로를 갖는다
(``EDGE_DEVICE`` 는 자기 자신만, ``OPERATOR`` 는 ``EVENTS_READ`` 로 임의 장비
조회 가능).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_event_contracts.event_bundle import EventBundle
from ksi_event_contracts.offline_sync import (
    IngestResult,
    IngestVerdict,
    JournalEntry,
    LedgerStateError,
    SyncLedger,
)
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.alias_generators import to_camel

from ksi_core.auth import (
    Permission,
    Principal,
    PrincipalKind,
    principal_permissions,
    require_permission,
    require_principal,
)
from ksi_core.durable_journal import _WRITE, _acquire_writer_lock, _fsync_dir
from ksi_core.events import _STATUS as _EVENT_STATUS
from ksi_core.events import EventStore, EventVerdict, classify_edge_bundle

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


class StoreRecoveryError(RuntimeError):
    """journal 재적재/잠금 실패 — 오염·경합 상태로 기동하지 않는다(fail-closed)."""


class ServerVerdict(StrEnum):
    """SyncLedger 판정 밖의 서버 수준 판정."""

    INVALID_EVENT_BUNDLE = "INVALID_EVENT_BUNDLE"  # payload 가 EventBundle v1.2 가 아님
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"  # durable append 실패로 봉인됨 — ACK 불가
    DEVICE_MISMATCH = "DEVICE_MISMATCH"  # 인증 장비 device_id != 요청 edgeDeviceId


@dataclass(frozen=True, slots=True)
class ServerIngestResult:
    verdict: IngestVerdict | ServerVerdict
    detail: str | None = None


# 스냅샷 파일 표현의 버전 — 표현이 바뀌면 올린다. 옛 버전 스냅샷은 복원하지 않고
# 버린다(전량 재생으로 같은 상태에 도달한다).
_SNAPSHOT_VERSION = 1


def _snapshot_digest(payload: Mapping[str, object]) -> str:
    """``digest`` 를 제외한 스냅샷 본문의 정규 digest.

    스냅샷은 journal 과 달리 사람이 손댈 수 있는 자리다 — 손대면 알아채야 한다.
    ``sort_keys`` 로 키 순서를, ``separators`` 로 공백을 고정해 같은 내용이 항상
    같은 값을 낸다.
    """
    body = {key: value for key, value in payload.items() if key != "digest"}
    canonical = json.dumps(
        body, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    )
    return f"sha256:{hashlib.sha256(canonical.encode('ascii')).hexdigest()}"


def _hash_prefix(path: Path, through: int) -> tuple[str, int]:
    """``[0, through)`` 구간의 sha256 과 완결 줄 수 — 스냅샷↔journal 결합 검사용.

    스트리밍으로 읽어 큰 원장에서도 메모리가 상수다. 반환하는 줄 수는 개행
    개수이므로 "완결된 줄"의 수와 같다(경계는 항상 개행 뒤라 부분 줄이 없다).

    비용 관점: 항목당 ``json.dumps(sort_keys)`` + sha256 + pydantic 파싱을 다시
    하는 것(스냅샷이 없앤 비용)보다 한 자릿수 이상 싸다 — 그래서 이 검사를
    넣어도 스냅샷의 목적이 유지된다.
    """
    digest = hashlib.sha256()
    remaining = through
    newlines = 0
    with path.open("rb") as handle:
        while remaining > 0:
            chunk = handle.read(min(1 << 20, remaining))
            if not chunk:
                break
            digest.update(chunk)
            newlines += chunk.count(b"\n")
            remaining -= len(chunk)
    return digest.hexdigest(), newlines


class EdgeSyncStore:
    """SyncLedger 규칙 + append-only journal 영속 + 단일 writer 잠금.

    동시성: FastAPI sync 라우트는 스레드풀에서 돌므로 프로세스 내 직렬화를 위해
    잠금이 필요하다 — 판정과 append 가 한 임계구역이어야 순번 규칙이 교차 실행으로
    깨지지 않는다. 프로세스 간에는 flock 이 단일 writer 를 강제한다.
    """

    def __init__(self, journal_path: Path, *, snapshot_every: int | None = None) -> None:
        import threading

        if snapshot_every is not None and snapshot_every <= 0:
            # 0·음수를 받으면 append 마다 스냅샷을 다시 써서 수신 경로를 스스로
            # 느리게 만든다 — "스냅샷 없음"을 뜻하려면 None 이어야 한다.
            raise ValueError(
                f"snapshot_every 는 양수여야 한다(스냅샷 없음은 None): {snapshot_every!r}"
            )
        self._path = journal_path
        self._snapshot_path = journal_path.with_suffix(journal_path.suffix + ".snapshot.json")
        self._snapshot_every = snapshot_every
        self._accepted_since_snapshot = 0
        self._ledger = SyncLedger()
        self._sealed_reason: str | None = None
        self._lock = threading.Lock()
        self._acquire_writer_lock()
        try:
            self._recover()
        except BaseException:
            # 재생 실패로 인스턴스가 살아남지 못하면 flock·fd 를 프로세스 수명
            # 내내 들고 있으면 안 된다(독립 재검토 P2-G, DurableJournal 대칭) —
            # 같은 프로세스의 재시도가 진짜 원인 대신 "다른 프로세스가 소유 중"
            # 으로 오도된다. 스냅샷 도입이 raise 지점을 늘려 표면이 넓어졌다.
            import fcntl

            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            raise

    def _acquire_writer_lock(self) -> None:
        """flock 배타 잠금 — 두 프로세스가 같은 journal 에 쓰는 경합을 기동 거부로 막는다.

        획득 로직 자체는 ``durable_journal._acquire_writer_lock`` 공용부다(P0-1
        2단계) — 이 store 는 실패 시 던질 예외 타입만 지정한다.
        """
        self._lock_fd = _acquire_writer_lock(self._path, error_cls=StoreRecoveryError)

    def close(self) -> None:
        """수신 봉인 + 잠금 해제 — 멱등(감사 #51).

        close 후 도착한 요청이 잠금 없이 기록되는 창을 없앤다 — 봉인 사유를
        남겨 이후 수신은 전부 STORE_UNAVAILABLE 이다.
        """
        import fcntl

        with self._lock:
            if self._sealed_reason == "closed":
                return
            self._sealed_reason = "closed"
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)

    def _recover(self) -> None:
        """journal 재적재 — 완결 줄은 전부 ACCEPTED 여야 하고, torn tail 은 격리한다.

        스냅샷이 유효하면 그 지점(바이트 오프셋)부터만 읽는다 — 그 앞의 항목은
        이미 원장에 복원돼 있고, 본문 재정규화·digest 재계산을 건너뛴다.
        """
        resume_at = self._load_snapshot()
        if not self._path.exists():
            return
        try:
            with self._path.open("rb") as handle:
                handle.seek(resume_at)
                raw = handle.read()
        except OSError as exc:
            raise StoreRecoveryError(
                f"{self._path}: journal 읽기 실패 — {type(exc).__name__}: {exc}"
            ) from exc

        complete, _sep, tail = raw.rpartition(b"\n")
        # 좌표는 **파일 기준 바이트 오프셋**이다(독립 재검토 P2-E) — 재생 시작점
        # 이후 몇 번째 줄인지로 적으면, 스냅샷이 100만 줄을 덮은 상태에서
        # "journal.jsonl:3" 이 실제로는 백만 번째 줄을 가리켜 운영자를 오도한다.
        # 기동 거부 상황에서 원장을 손으로 들여다볼 때 쓰는 유일한 좌표다.
        offset = resume_at
        for line in complete.split(b"\n") if complete else []:
            line_offset = offset
            offset += len(line) + 1
            if not line.strip():
                continue
            try:
                entry = JournalEntry.model_validate_json(line)
            except ValidationError as exc:
                raise StoreRecoveryError(
                    f"{self._path}@{line_offset}: journal 줄이 JournalEntry 가 아니다 — {exc}"
                ) from exc
            replayed = self._ledger.ingest(entry)
            if replayed.verdict is not IngestVerdict.ACCEPTED:
                raise StoreRecoveryError(
                    f"{self._path}@{line_offset}: 재적재 거부({replayed.verdict}: "
                    f"{replayed.detail}) — 원장이 오염됐다. 조용히 건너뛰지 않는다"
                )

        if tail.strip():
            # 개행 없이 끝난 마지막 부분 줄 — 완결 write+fsync 후에만 ACK 하므로
            # 이 줄은 ACK 된 적이 없다(Edge 가 아직 들고 있어 재전송으로 복구된다).
            # 남겨두면 다음 append 가 뒤에 이어붙어 진짜 오염이 되므로 잘라낸다.
            logger.warning(
                "%s: ACK 되지 않은 torn tail %d바이트 격리(부분 쓰기 후 중단 흔적) — "
                "해당 항목은 Edge 재전송으로 복구된다",
                self._path,
                len(tail),
            )
            with self._path.open("r+b") as handle:
                # 오프셋 재생이면 잘라낼 지점은 파일 전체 기준이어야 한다 —
                # len(raw) 는 재생 시작점 이후 길이뿐이다.
                handle.truncate(resume_at + len(raw) - len(tail))
                handle.flush()
                os.fsync(handle.fileno())

    # ── 스냅샷 (S4 — ops-serving-hardening) ────────────────────────────────
    #
    # 재기동 비용의 실체는 파일 크기가 아니라 **항목당 본문 정규화 + sha256**
    # 이다(``SyncLedger.ingest`` 가 매 항목 ``payload_digest`` 를 다시 계산한다).
    # 스냅샷은 그 계산 결과(원장 상태)를 들고 있다가 재기동 시 복원하고, journal
    # 은 스냅샷 이후 구간만 읽는다.
    #
    # 신뢰 규칙 — **스냅샷은 journal 이 부정하는 것을 주장할 수 없다.**
    #   - 스냅샷이 깨졌거나(digest 불일치·형식 위반·규칙 위반) 읽을 수 없으면
    #     버리고 전량 재생한다. journal 이 정본이므로 결과 상태는 동일하고,
    #     느려질 뿐이다. 조용히 넘어가지 않고 ERROR 로 남긴다.
    #   - 반대로 **journal 쪽이 스냅샷과 어긋나면**(파일이 줄었다·덮어써진
    #     흔적이 있다) 기동을 거부한다. append-only 파일이 짧아지는 것은
    #     설명되지 않는 상태이고, 그대로 재생하면 조용히 틀린 원장이 된다.

    def _load_snapshot(self) -> int:
        """스냅샷을 복원하고 재생을 시작할 바이트 오프셋을 돌려준다(없으면 0)."""
        if not self._snapshot_path.exists():
            return 0
        try:
            payload = json.loads(self._snapshot_path.read_bytes())
        except (OSError, ValueError) as exc:
            logger.error(
                "%s: 스냅샷을 읽을 수 없어 버리고 전량 재생한다 — %s: %s",
                self._snapshot_path, type(exc).__name__, exc,
            )
            return 0
        if not isinstance(payload, dict) or payload.get("version") != _SNAPSHOT_VERSION:
            logger.error(
                "%s: 알 수 없는 스냅샷 형식/버전 — 버리고 전량 재생한다", self._snapshot_path
            )
            return 0
        declared = payload.get("digest")
        if declared != _snapshot_digest(payload):
            logger.error(
                "%s: 스냅샷 digest 불일치 — 버리고 전량 재생한다", self._snapshot_path
            )
            return 0

        through = payload.get("throughBytes")
        prefix_sha = payload.get("prefixSha256")
        if (
            not isinstance(through, int)
            or isinstance(through, bool)
            or through <= 0
            or not isinstance(prefix_sha, str)
        ):
            logger.error(
                "%s: 스냅샷 경계 값이 유효하지 않다 — 버리고 전량 재생한다",
                self._snapshot_path,
            )
            return 0

        # 여기부터는 journal 쪽 정합 — 어긋나면 전량 재생이 아니라 기동 거부다.
        if not self._path.exists():
            raise StoreRecoveryError(
                f"{self._snapshot_path}: 스냅샷은 있는데 journal({self._path})이 없다 — "
                "원장이 사라진 상태로 기동하지 않는다"
            )
        try:
            size = self._path.stat().st_size
            actual_prefix_sha, line_count = _hash_prefix(self._path, through)
        except OSError as exc:
            raise StoreRecoveryError(
                f"{self._path}: 스냅샷 경계 확인 실패 — {type(exc).__name__}: {exc}"
            ) from exc
        if size < through:
            raise StoreRecoveryError(
                f"{self._path}: append-only journal 이 스냅샷 경계보다 짧다 "
                f"({size} < {through}) — 잘렸거나 교체된 원장으로 기동하지 않는다"
            )
        if actual_prefix_sha != prefix_sha:
            # 경계 **줄 하나**만 검사하던 초안은 그 앞 구간의 in-place 손상을
            # 통째로 놓쳤다(독립 재검토 P1-B) — 스냅샷 없는 경로는 모든 줄을
            # ingest 에 태우므로 어떤 손상이든 기동 거부인데, 스냅샷 경로만
            # 조용히 뜨는 fail-closed 회귀였다. prefix 전체 해시로 그 성질을
            # 되돌린다. 항목당 정규화+sha256+pydantic 파싱보다 한 자릿수 이상
            # 싸므로 스냅샷의 목적(재기동 비용)은 유지된다.
            raise StoreRecoveryError(
                f"{self._path}: 스냅샷 경계까지의 내용이 다르다 — 원장이 교체·손상된 흔적"
            )
        try:
            restored = SyncLedger.from_state(payload.get("ledger"))
        except LedgerStateError as exc:
            # 규칙을 어기는 스냅샷이다. journal 이 정본이므로 버리고 전량 재생하면
            # 상태는 정확해진다 — 다만 조용히 넘어가지 않는다.
            logger.error(
                "%s: 스냅샷 원장이 규칙을 위반해 버린다(전량 재생) — %s",
                self._snapshot_path, exc,
            )
            return 0

        # **원장이 주장하는 건수 == 경계까지의 실제 줄 수** 여야 한다(독립 재검토
        # P1-A). 이게 없으면 digest 만 다시 맞춘 스냅샷이 항목을 덜 주장할 수 있고,
        # 그 구간은 resume_at 때문에 영영 재생되지 않는다 — _last_sequence 가
        # 내려가 이미 ACK 된 항목의 재전송이 ACCEPTED 로 되살아나고, journal 에
        # 중복 줄이 생겨 스냅샷 없이 재기동할 때 영구 기동 불가가 된다.
        # 스냅샷 **내부** 정합(from_state)만으로는 이 결합을 만들 수 없다.
        if restored.accepted_count() != line_count:
            raise StoreRecoveryError(
                f"{self._path}: 스냅샷 원장이 주장하는 건수({restored.accepted_count()})와 "
                f"경계까지의 실제 줄 수({line_count})가 다르다 — 원장과 어긋난 스냅샷"
            )
        self._ledger = restored
        logger.info(
            "%s: 스냅샷에서 %d건 복원 — journal 은 오프셋 %d 부터 재생한다",
            self._snapshot_path, self._ledger.accepted_count(), through,
        )
        return through

    def _write_snapshot(self) -> None:
        """현재 원장 상태를 스냅샷으로 굳힌다(호출자가 잠금 보유).

        경계는 현재 journal 크기다. 그 경계까지의 sha256 과 줄 수를 함께 굳혀,
        다음 기동이 "이 구간이 아직 그대로인가"와 "스냅샷이 이 구간 전체를
        주장하는가"를 둘 다 확인한다.

        실패는 봉인하지 않는다 — 스냅샷은 최적화일 뿐이고, 없으면 전량 재생으로
        정확히 같은 상태에 도달한다. 수신(ACK)을 스냅샷 실패로 멈추는 것은
        durability 와 무관한 사유로 제품을 세우는 일이다.
        """
        try:
            through = self._path.stat().st_size
            prefix_sha, line_count = _hash_prefix(self._path, through)
            payload: dict[str, object] = {
                "version": _SNAPSHOT_VERSION,
                "throughBytes": through,
                "prefixSha256": prefix_sha,
                "ledger": self._ledger.export_state(),
            }
            payload["digest"] = _snapshot_digest(payload)
            tmp = self._snapshot_path.with_suffix(self._snapshot_path.suffix + ".tmp")
            data = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode("ascii")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                view = memoryview(data)
                written = 0
                while written < len(data):
                    count = _WRITE(fd, view[written:])
                    if count <= 0:
                        raise OSError(f"short write: {written}/{len(data)} bytes")
                    written += count
                os.fsync(fd)
            finally:
                os.close(fd)
            # rename 은 같은 디렉터리 안에서 원자적이다 — 반쯤 쓰인 스냅샷이
            # 다음 기동에 보이는 창이 없다.
            os.replace(tmp, self._snapshot_path)
            _fsync_dir(self._snapshot_path.parent)
        except Exception as exc:
            # BaseException 이 아니라 Exception 이다(독립 재검토 P2-H) — 스냅샷
            # 실패가 ACK 를 막으면 안 된다는 목적에는 이걸로 충분하고,
            # KeyboardInterrupt·SystemExit 까지 삼키면 fsync 중 Ctrl-C 가 조용히
            # 사라진다(바로 옆 append 경로는 봉인 후 재전파한다).
            logger.warning(
                "%s: 스냅샷 기록 실패(%s) — 수신은 계속하고 다음 주기에 재시도한다",
                self._snapshot_path, type(exc).__name__,
            )

    @property
    def sealed(self) -> bool:
        return self._sealed_reason is not None

    @property
    def sealed_reason(self) -> str | None:
        """봉인 사유. 미봉인이면 ``None``, ``close()`` 이후면 ``"closed"``.

        ``DurableJournal.sealed_reason`` (durable_journal.py) 과 동일한 모양 —
        ``app_assembly.py`` 의 ``/ready`` 봉인 판정이 ``getattr(j, "sealed_reason",
        None)`` 로 두 원장 타입을 동일하게 취급할 수 있게 한다(P0-1).
        """
        return self._sealed_reason

    def ingest_event_bundle(self, entry: JournalEntry) -> ServerIngestResult:
        """항목 1건 판정+영속. ``ACCEPTED`` 는 durable 성공 후에만 반환된다."""
        with self._lock:
            if self._sealed_reason is not None:
                return ServerIngestResult(
                    ServerVerdict.STORE_UNAVAILABLE,
                    detail=f"durable append 실패로 봉인됨 — 재시작 필요 ({self._sealed_reason})",
                )
            # payload 가 EventBundle v1.2 인지 원장 반영 **전에** 검증한다 —
            # 계보 없는 이벤트가 멱등 원장을 선점하면, Edge 가 수정본을 보내도
            # 같은 키가 IDEMPOTENCY_CONFLICT 로 막힌다.
            try:
                EventBundle.model_validate(entry.payload)
            except ValidationError as exc:
                return ServerIngestResult(
                    ServerVerdict.INVALID_EVENT_BUNDLE,
                    detail=f"payload 가 EventBundle v1.2 가 아니다 — {exc.error_count()}건 위반",
                )

            result: IngestResult = self._ledger.ingest(entry)
            if result.verdict is not IngestVerdict.ACCEPTED:
                # 원장 측 기존 신원(다른 항목의 키·순번·digest)은 응답에 싣지
                # 않는다(감사 #8 — 비인증 표면의 열거 오라클). 전체 사유는 서버
                # 로그로, 클라이언트에는 verdict 와 자기 요청 좌표만.
                logger.info(
                    "ingest 거부 %s (device=%s seq=%s): %s",
                    result.verdict, entry.edge_device_id, entry.device_sequence, result.detail,
                )
                return ServerIngestResult(
                    result.verdict,
                    detail=(
                        f"요청(device={entry.edge_device_id}, seq={entry.device_sequence})이 "
                        f"{result.verdict.value} 로 거부됨 — 상세는 서버 로그"
                    ),
                )

            try:
                self._append_durable(entry)
            except OSError as exc:
                # SyncLedger 메모리에는 반영됐는데 디스크에 없다 — 봉인하지 않으면
                # 재전송이 DUPLICATE_IGNORED(ACK)로 둔갑해 유실이 확정된다.
                # detail 에 예외 메시지를 싣지 않는다(비인증 응답에 경로 노출 방지)
                # — 전체 사유는 서버 로그로.
                self._sealed_reason = type(exc).__name__
                logger.error("durable append 실패로 봉인: %s: %s", type(exc).__name__, exc)
                return ServerIngestResult(
                    ServerVerdict.STORE_UNAVAILABLE,
                    detail="durable append 실패 — ACK 불가, store 봉인(재시작 필요)",
                )
            except BaseException as exc:
                # OSError 밖의 예외(MemoryError 등)도 같은 불일치 형상을 만든다 —
                # 봉인만 하고 그대로 전파한다(P1-1: 무차별 삼킴이 아니라 무차별 봉인).
                self._sealed_reason = type(exc).__name__
                logger.error("durable append 중 예외로 봉인: %s", type(exc).__name__)
                raise
            # 스냅샷은 ACK 이후의 관심사다 — durable append 가 끝난 뒤에만 찍고,
            # 실패해도 이 ACCEPTED 를 취소하지 않는다.
            self._accepted_since_snapshot += 1
            if (
                self._snapshot_every is not None
                and self._accepted_since_snapshot >= self._snapshot_every
            ):
                # 성공·실패와 무관하게 주기를 리셋한다 — 실패가 계속될 때
                # append 마다 재시도해 수신 경로를 느리게 만들지 않는다.
                self._accepted_since_snapshot = 0
                self._write_snapshot()
            return ServerIngestResult(IngestVerdict.ACCEPTED)

    def _append_durable(self, entry: JournalEntry) -> None:
        # ensure_ascii=True: 유니코드 개행 후보(U+2028 등)가 raw 로 나가 재적재의
        # 줄 분리를 깨는 경로를 원천 차단한다(P1-2 실측). digest 는 payload dict
        # 기준이라 표기 차이의 영향이 없다.
        line = json.dumps(
            entry.model_dump(by_alias=True),
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
            # POSIX write 는 예외 없이 짧게 쓸 수 있다(ENOSPC/EDQUOT 페이지 경계 —
            # 감사 반증 실측: 그대로 두면 fsync 가 성공해 부분 줄이 ACK 된다).
            # 전량 기록까지 반복하고, 진전이 없으면 OSError 로 올려 기존 봉인
            # 경로를 태운다 — 이미 쓰인 부분 줄은 개행이 없어 재시작 복원이
            # torn tail 로 격리하므로 ACK 없는 실패로 정확히 수렴한다.
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
            # 새 파일은 디렉터리 엔트리도 durable 해야 ACK 후 머신 크래시에서
            # 파일째 사라지지 않는다(P0-1).
            _fsync_dir(self._path.parent)

    # ── 검증·진단 위임 (공개 API 아님 — 인증 도입 전 노출 최소화) ──────────
    def accepted_count(self) -> int:
        return self._ledger.accepted_count()

    def accepted_sequences(self, edge_device_id: str) -> list[int]:
        return self._ledger.accepted_sequences(edge_device_id)

    def missing_sequences(self, edge_device_id: str) -> list[int]:
        return self._ledger.missing_sequences(edge_device_id)


class IngestResponse(BaseModel):
    verdict: str
    detail: str | None = None


class DeviceSequenceResponse(BaseModel):
    """장비 복구 조회 응답 — 장비는 이걸로 재전송 시작점을 판단한다."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    device_id: str
    last_sequence: int | None


# verdict → HTTP status. ACCEPTED 만 201(신규 반영), 멱등 무시는 200(정상·무효과),
# 충돌류는 409(원장과의 불일치), malformed 류는 422, 봉인은 503, 신원 불일치는 403.
_STATUS: dict[IngestVerdict | ServerVerdict, int] = {
    IngestVerdict.ACCEPTED: 201,
    IngestVerdict.DUPLICATE_IGNORED: 200,
    IngestVerdict.IDEMPOTENCY_CONFLICT: 409,
    IngestVerdict.SEQUENCE_DUPLICATE: 409,
    IngestVerdict.SEQUENCE_REGRESSION: 409,
    IngestVerdict.DIGEST_MISMATCH: 422,
    IngestVerdict.MALFORMED_PAYLOAD: 422,
    ServerVerdict.INVALID_EVENT_BUNDLE: 422,
    ServerVerdict.STORE_UNAVAILABLE: 503,
    ServerVerdict.DEVICE_MISMATCH: 403,
}

_DEVICE_ACCESS_FORBIDDEN_DETAIL = "권한이 부족하다"

# 수신 전 Event 정책 게이트 거부 문구(events.classify_edge_bundle 판정 → 응답).
_POLICY_REJECTION_DETAIL: dict[EventVerdict, str] = {
    EventVerdict.STATUS_NOT_EDGE_ASSERTABLE: (
        "확정/기각 상태는 Edge 가 주장할 수 없다 — 서버 트리아지 전용"
    ),
    EventVerdict.INVALID_EVENT_IDENTITY: (
        "eventId·edgeDeviceId 는 경로-안전 문자만 허용한다(예약 구분자·'/' 등 금지)"
    ),
    EventVerdict.INVALID_EVENT_TIMESTAMP: "occurredAt 은 tz-aware(offset 포함) 여야 한다",
}


def _require_device_sequence_access(
    device_id: str,
    principal: Principal = Depends(require_principal()),  # noqa: B008
) -> Principal:
    """자기 순번은 그 장비 자신만, 타 장비 순번은 ``EVENTS_READ`` 를 가진 OPERATOR 만.

    detail 은 일반 문구로 고정한다(존재 여부·타 장비 신원 힌트를 주지 않는다 —
    auth.py/edge_sync.py 열거 오라클 방지 관습).
    """
    if principal.kind is PrincipalKind.EDGE_DEVICE:
        if principal.device_id == device_id:
            return principal
        raise HTTPException(status_code=403, detail=_DEVICE_ACCESS_FORBIDDEN_DETAIL)
    if Permission.EVENTS_READ in principal_permissions(principal):
        return principal
    raise HTTPException(status_code=403, detail=_DEVICE_ACCESS_FORBIDDEN_DETAIL)


def build_edge_sync_router(store: EdgeSyncStore, *, event_store: EventStore) -> APIRouter:
    router = APIRouter(prefix="/v1/edge-sync", tags=["edge-sync"])

    # 201(신규 수신)·200(멱등 재전송) 둘 다 ACK 다 — 주 경로인 201 을 선언하고
    # 200 은 아래 responses 로 남긴다(sites.py 의 같은 주석 참조).
    @router.post(
        "/event-bundles",
        response_model=IngestResponse,
        status_code=201,
        responses={
            200: {
                "model": IngestResponse,
                "description": "DUPLICATE_IGNORED — 멱등 재전송 ACK",
            }
        },
    )
    def ingest_event_bundle(
        entry: JournalEntry,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.EDGE_SYNC_INGEST)),  # noqa: B008
    ) -> IngestResponse:
        """JournalEntry(payload=EventBundle v1.2) 1건 수신.

        201 ACCEPTED 또는 200 DUPLICATE_IGNORED 만 ACK 다 — Edge 는 이 둘을 받은
        항목만 로컬에서 지운다. 409/422 는 항목 점검 대상, 503 은 재전송 대상.

        인증된 ``EDGE_DEVICE`` 의 ``device_id`` 가 요청 본문의 ``edgeDeviceId`` 와
        다르면 원장에 반영하기 **전에** 403 ``DEVICE_MISMATCH`` 로 거부한다(모듈
        docstring "인증 장비 신원 바인딩" 절 — 위조 순번 주입이 장비 신원 뒤로
        차단된다).

        ACCEPTED·DUPLICATE_IGNORED 는 ACK 반환 **전에** event projection 을
        수행한다(ADR-KSI-008 §3 — "ACK 는 event projection 까지 성공했을 때만
        반환한다"). projection 이 STORE_UNAVAILABLE 이면 edge-sync 자체는
        ACCEPTED 였더라도 ACK 를 내주지 않고 503 으로 뒤집는다 — 수신은 durable
        했는데 트리아지에 안 보이는 조용한 유실 표면을 막는다. UPDATE_DIVERGED 는
        ACK 를 막지 않는다(원문은 이미 edge-sync journal 에 durable — 장비 sync
        를 독살하지 않는다).
        """
        if principal.device_id != entry.edge_device_id:
            response.status_code = _STATUS[ServerVerdict.DEVICE_MISMATCH]
            return IngestResponse(
                verdict=str(ServerVerdict.DEVICE_MISMATCH.value),
                detail="인증 장비 신원이 요청 edgeDeviceId 와 일치하지 않는다",
            )

        # Event 정책 게이트는 원장 반영 **전에** 판정한다 — 정책상 절대 projection
        # 될 수 없는 bundle 이 멱등 원장·순번축을 선점하면 그 항목이 영구 422 가
        # 되어 그 장비 큐 전체가 막힌다(events.classify_edge_bundle docstring).
        policy_verdict = classify_edge_bundle(entry.payload, edge_device_id=entry.edge_device_id)
        if policy_verdict is not None:
            response.status_code = _EVENT_STATUS[policy_verdict]
            return IngestResponse(
                verdict=str(policy_verdict.value),
                detail=_POLICY_REJECTION_DETAIL[policy_verdict],
            )

        result = store.ingest_event_bundle(entry)
        verdict = result.verdict
        detail = result.detail

        if verdict in (IngestVerdict.ACCEPTED, IngestVerdict.DUPLICATE_IGNORED):
            projection_verdict = event_store.project_bundle(
                entry.payload, edge_device_id=entry.edge_device_id, received_at=datetime.now(UTC)
            )
            if projection_verdict is EventVerdict.STORE_UNAVAILABLE:
                response.status_code = _EVENT_STATUS[EventVerdict.STORE_UNAVAILABLE]
                response.headers["Retry-After"] = "30"
                return IngestResponse(
                    verdict=str(ServerVerdict.STORE_UNAVAILABLE.value),
                    detail="event projection 실패 — ACK 불가, store 봉인(재시작 필요)",
                )
            if projection_verdict in _POLICY_REJECTION_DETAIL:
                # 사전 게이트(classify_edge_bundle)를 통과했는데 projection 이
                # 같은 정책으로 거부했다 = 두 판정의 drift. 조용히 ACK 하지 않고
                # typed 422 로 드러낸다(EventStore 가 방어적으로 같은 게이트를
                # 다시 강제하므로 정상 경로에서는 도달하지 않는다).
                logger.error(
                    "정책 게이트 drift: 사전 통과 후 projection 이 %s 로 거부", projection_verdict
                )
                response.status_code = _EVENT_STATUS[projection_verdict]
                return IngestResponse(
                    verdict=str(projection_verdict.value),
                    detail=_POLICY_REJECTION_DETAIL[projection_verdict],
                )
            # PROJECTED/EVENT_UPDATED/DUPLICATE_PROJECTION/UPDATE_DIVERGED 는
            # ACK 를 막지 않는다 — 기존 edge-sync verdict 그대로 진행.

        response.status_code = _STATUS[verdict]
        if verdict is ServerVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return IngestResponse(verdict=str(verdict.value), detail=detail)

    @router.get("/devices/{device_id}/sequence", response_model=DeviceSequenceResponse)
    def get_device_sequence(
        device_id: str,
        principal: Principal = Depends(_require_device_sequence_access),  # noqa: B008
    ) -> DeviceSequenceResponse:
        """그 장비의 마지막 수락 순번 — 재전송 시작점 판단용 복구 경로.

        ``EDGE_DEVICE`` 는 자기 자신만, ``OPERATOR`` 는 ``EVENTS_READ`` 로 임의
        장비를 조회할 수 있다(:func:`_require_device_sequence_access`). 수락
        이력이 없는 장비는 ``lastSequence: null`` — 미지 장비와 구분하지 않는다
        (존재 여부 힌트 금지 관습).
        """
        del principal
        sequences = store.accepted_sequences(device_id)
        return DeviceSequenceResponse(
            device_id=device_id,
            last_sequence=sequences[-1] if sequences else None,
        )

    return router


def mount_edge_sync(app: FastAPI, store: EdgeSyncStore, *, event_store: EventStore) -> None:
    """앱에 edge-sync 라우터를 장착한다 — store 없이는 엔드포인트가 존재하지 않는다.

    ``event_store`` 는 ADR-KSI-008 §3(``edge_sync_store`` ⇒ ``event_store`` 필수)
    강제 지점이다 — 수신은 ACK 했는데 트리아지에 보이지 않는 조용한 유실 표면을
    타입으로 막는다.
    """
    app.state.edge_sync_store = store
    app.state.event_store = event_store
    app.include_router(build_edge_sync_router(store, event_store=event_store))
