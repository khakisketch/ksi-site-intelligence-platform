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

import json
import logging
import os
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
from ksi_core.events import _STATUS as _EVENT_STATUS
from ksi_core.events import EventStore, EventVerdict, classify_edge_bundle

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# os.write 참조를 모듈 상수로 분리 — short-write fault injection 테스트가 전역
# os 모듈을 건드리지 않고 이 경로만 대체할 수 있게(감사 finding #1 회귀 고정).
_WRITE = os.write


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


def _fsync_dir(directory: Path) -> None:
    """디렉터리 엔트리를 durable 하게 만든다 — 파일 fsync 만으로는 부족하다(P0-1)."""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class EdgeSyncStore:
    """SyncLedger 규칙 + append-only journal 영속 + 단일 writer 잠금.

    동시성: FastAPI sync 라우트는 스레드풀에서 돌므로 프로세스 내 직렬화를 위해
    잠금이 필요하다 — 판정과 append 가 한 임계구역이어야 순번 규칙이 교차 실행으로
    깨지지 않는다. 프로세스 간에는 flock 이 단일 writer 를 강제한다.
    """

    def __init__(self, journal_path: Path) -> None:
        import threading

        self._path = journal_path
        self._ledger = SyncLedger()
        self._sealed_reason: str | None = None
        self._lock = threading.Lock()
        self._acquire_writer_lock()
        self._recover()

    def _acquire_writer_lock(self) -> None:
        """flock 배타 잠금 — 두 프로세스가 같은 journal 에 쓰는 경합을 기동 거부로 막는다."""
        import fcntl

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # 잠금 파일 fd 는 store 수명 동안 유지된다(닫히면 잠금이 풀린다).
            self._lock_fd = os.open(
                self._path.with_suffix(self._path.suffix + ".lock"), os.O_CREAT | os.O_RDWR, 0o600
            )
        except OSError as exc:
            raise StoreRecoveryError(f"잠금 파일 생성 실패: {type(exc).__name__}: {exc}") from exc
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self._lock_fd)
            raise StoreRecoveryError(
                f"{self._path}: 다른 프로세스가 journal 을 소유 중 — 단일 writer 위반"
            ) from exc

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
        """journal 재적재 — 완결 줄은 전부 ACCEPTED 여야 하고, torn tail 은 격리한다."""
        if not self._path.exists():
            return
        try:
            raw = self._path.read_bytes()
        except OSError as exc:
            raise StoreRecoveryError(
                f"{self._path}: journal 읽기 실패 — {type(exc).__name__}: {exc}"
            ) from exc

        complete, _sep, tail = raw.rpartition(b"\n")
        for line_no, line in enumerate(complete.split(b"\n") if complete else [], start=1):
            if not line.strip():
                continue
            try:
                entry = JournalEntry.model_validate_json(line)
            except ValidationError as exc:
                raise StoreRecoveryError(
                    f"{self._path}:{line_no}: journal 줄이 JournalEntry 가 아니다 — {exc}"
                ) from exc
            replayed = self._ledger.ingest(entry)
            if replayed.verdict is not IngestVerdict.ACCEPTED:
                raise StoreRecoveryError(
                    f"{self._path}:{line_no}: 재적재 거부({replayed.verdict}: "
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
                handle.truncate(len(raw) - len(tail))
                handle.flush()
                os.fsync(handle.fileno())

    @property
    def sealed(self) -> bool:
        return self._sealed_reason is not None

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

    @router.post("/event-bundles", response_model=IngestResponse)
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
