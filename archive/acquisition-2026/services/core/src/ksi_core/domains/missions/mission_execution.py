"""임무 실행 생애주기 원장 + 조회·선언 표면 (ADR-KSI-019 G2).

:class:`~ksi_core.mission_records.MissionRecord` 는 **발급 기록**이라 "이 임무가
실제로 날았는가"에 답하지 못한다. 이 모듈이 그 축을 별도 원장으로 연다.

## 레코드 부재 = ``ISSUED``

발급 시점에 실행 레코드를 함께 쓰지 않는다. 그러면 ADR-KSI-008 §3 의 "발급 레코드가
durable 기록되기 전에는 201 을 반환하지 않는다" 경로에 **두 번째 원장 쓰기**가
끼어들고, 그 쓰기가 실패할 때 이미 성립한 계약 발급이 실패한다. 대신
:meth:`MissionExecutionStore.effective_status` 가 "레코드 없음"을 ``ISSUED`` 로
읽는다 — ``SiteRecord.aoi`` 가 ``None`` 을 "아직 설정 안 함"으로 읽는 것과 같은
관용구다.

## 이 축은 게이트가 아니다 (INV-010)

완료 판정의 권위는 CoverageReport 하나다. 이 상태를 커버리지 접수·재구성 발급·
원본 미디어 등록의 **전제조건으로 쓰지 않는다.** 쓰기 시작하면 완료 판정의 권위가
조용히 이 필드로 옮겨온다. 여기서 강제하는 것은 전이표뿐이고, 전이표조차 앞으로
건너뛰기를 허용한다(``ksi_domain.enums._ALLOWED_MISSION_EXECUTION_TRANSITIONS``
주석 참조).

그 귀결이 하나 더 있다: **이 원장이 봉인돼도 커버리지 접수는 201 이어야 한다.**
훅 호출자는 반환값을 의도적으로 무시한다(``coverage_reports``·``edge_dispatch``
라우터의 호출부 주석).

## 사람이 선언할 수 있는 상태는 둘뿐

``DISPATCHED``(기체로 넘겼다)와 ``CANCELLED``(접는다)만 사람이 선언한다.
``ACTIVATED`` 는 Edge 의 서명 receipt 가, ``COMPLETED``/``ENDED_INCOMPLETE`` 는
CoverageReport 접수가 만드는 사실이다 — 사람이 찍을 수 있으면 그 상태는 근거가
아니라 주장이 된다(``processing_jobs`` 의 "PROCESSING_WORK 는 어느 Role 에도
없다"와 같은 원칙). 표에 없는 대상 상태는 **누구에게도** 권한이 없다.

## 재생은 fail-closed

live 와 같은 전이표를 다시 태운다 — journal 을 손으로 고쳐 ``CANCELLED`` 를
``COMPLETED`` 로 바꿀 수 없다(``processing_jobs._replay_transition`` 과 동일 원칙).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_domain.enums import (
    IllegalMissionExecutionTransitionError,
    MissionExecutionStatus,
    MissionType,
    assert_mission_execution_transition,
)

from ksi_core.domains.missions.mission_records import (
    MISSION_NOT_FOUND_DETAIL,
    MissionStore,
    reject_lone_surrogates,
)
from ksi_core.foundation.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.metrics import MISSION_EXECUTION_TRANSITIONS
from ksi_core.identity.auth import (
    Permission,
    Principal,
    principal_permissions,
    require_permission,
    require_principal,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.domains.processing.spatial_model import SpatialModelLifecycle

_JOURNAL_KIND = "mission-execution-transitioned"


class MissionExecutionVerdict(StrEnum):
    """전이 시도 판정 — ``TRANSITIONED`` 만 durable 기록 성공이다."""

    TRANSITIONED = "TRANSITIONED"
    #: 발급된 적 없는 임무의 실행 상태는 받지 않는다(coverage_reports 와 같은 원칙 —
    #: 계약 없이 실행 사실만 원장에 남으면 "무슨 근거로 날았나"에 답할 수 없다).
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


#: verdict → HTTP status. ``ILLEGAL_TRANSITION`` 이 409 인 이유는 요청 자체는
#: 구조적으로 유효하고 현재 자원 상태와 충돌하기 때문이다(``mission_records`` 의
#: MISSION_TYPE_SITE_STATUS_MISMATCH 와 같은 분류).
MISSION_EXECUTION_HTTP_STATUS: dict[MissionExecutionVerdict, int] = {
    MissionExecutionVerdict.TRANSITIONED: 200,
    MissionExecutionVerdict.UNKNOWN_MISSION: 404,
    MissionExecutionVerdict.ILLEGAL_TRANSITION: 409,
    MissionExecutionVerdict.STORE_UNAVAILABLE: 503,
}


class MissionExecutionRecoveryError(RuntimeError):
    """journal 재생 중 오염·불법 전이 발견 — 오염된 projection 으로 기동하지 않는다."""


@dataclass(frozen=True, slots=True)
class MissionExecutionRecord:
    """전이 1건 — 무엇에서 무엇으로, 누가, 언제, 왜."""

    mission_id: str
    before: MissionExecutionStatus
    after: MissionExecutionStatus
    updated_at: datetime
    updated_by: str
    detail: str | None

    def __post_init__(self) -> None:
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at 은 tz-aware 여야 한다 — naive datetime 거부")


@dataclass(frozen=True, slots=True)
class MissionExecutionResult:
    verdict: MissionExecutionVerdict
    record: MissionExecutionRecord | None = None
    detail: str | None = None


class MissionExecutionStore:
    """``DurableJournal`` 위의 실행 상태 원장 — append-only, 덮어쓰지 않는다."""

    def __init__(self, journal: DurableJournal, *, mission_store: MissionStore) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._lock = threading.Lock()
        self._status: dict[str, MissionExecutionStatus] = {}
        self._history: dict[str, list[MissionExecutionRecord]] = {}
        try:
            self._replay(journal)
        except BaseException:
            # __init__ 실패 시 journal 이 flock 을 쥔 채 버려지면 프로세스 수명 내내
            # 잔존한다(mission_records·sites 와 대칭 조치).
            journal.close()
            raise

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            try:
                self._apply_locked(raw, replaying=True)
            except (KeyError, ValueError, TypeError) as exc:
                raise MissionExecutionRecoveryError(
                    f"mission-execution journal 재생 실패 — 오염되거나 불법 전이가 기록됨: {exc}"
                ) from exc

    def _apply_locked(
        self, raw: dict[str, Any], *, replaying: bool = False
    ) -> MissionExecutionRecord:
        """journal 레코드 하나를 projection 에 반영한다(재생·live 공용).

        재생 경로에서도 전이표를 다시 태운다 — 손으로 고친 원장이 불법 전이를
        되살릴 수 없게 한다. ``before`` 가 현재 projection 과 어긋나도 거부한다:
        원장이 스스로 모순이면 조용히 덮어쓰지 않는다.
        """
        kind = raw["kind"]
        if kind != _JOURNAL_KIND:
            raise ValueError(f"알 수 없는 kind: {kind!r}")
        mission_id = raw["missionId"]
        before = MissionExecutionStatus(raw["before"])
        after = MissionExecutionStatus(raw["after"])
        if replaying:
            current = self._status.get(mission_id, MissionExecutionStatus.ISSUED)
            if current is not before:
                raise ValueError(
                    f"재생: 기록된 before({before.value})가 현재 상태({current.value})와 "
                    f"다르다 — missionId={mission_id!r}"
                )
            assert_mission_execution_transition(before, after)
        updated_at = datetime.fromisoformat(raw["ts"])
        if updated_at.tzinfo is None:
            raise ValueError(f"ts 는 tz-aware 여야 한다 — missionId={mission_id!r}")
        record = MissionExecutionRecord(
            mission_id=mission_id,
            before=before,
            after=after,
            updated_at=updated_at,
            updated_by=raw["actor"],
            detail=raw.get("detail"),
        )
        self._status[mission_id] = after
        self._history.setdefault(mission_id, []).append(record)
        return record

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def mission_exists(self, mission_id: str) -> bool:
        """발급 원장에 그 임무가 있는가 — 이 모듈이 임무 존재를 판정하지 않는다."""
        return self._mission_store.get(mission_id) is not None

    def status_of(self, mission_id: str) -> MissionExecutionStatus | None:
        """**기록된** 상태 — 전이가 한 번도 없었으면 ``None``."""
        with self._lock:
            return self._status.get(mission_id)

    def effective_status(self, mission_id: str) -> MissionExecutionStatus:
        """레코드 부재를 ``ISSUED`` 로 읽은 실효 상태(모듈 docstring)."""
        with self._lock:
            return self._effective_status_locked(mission_id)

    def _effective_status_locked(self, mission_id: str) -> MissionExecutionStatus:
        return self._status.get(mission_id, MissionExecutionStatus.ISSUED)

    def history(self, mission_id: str) -> list[MissionExecutionRecord]:
        """그 임무의 전이 이력 — 오래된 것부터. 없으면 빈 목록."""
        with self._lock:
            return list(self._history.get(mission_id, ()))

    def transition(
        self,
        mission_id: str,
        target: MissionExecutionStatus,
        *,
        detail: str | None,
        actor: str,
        now: datetime,
    ) -> MissionExecutionResult:
        """실행 상태를 전이한다 — 전이표는 ``ksi_domain.enums`` 가 SSOT.

        실패는 전부 typed verdict 로 돌려주고 예외를 던지지 않는다. 이 원장은
        완료 판정의 권위가 아니라 투영이므로(모듈 docstring), 호출자(커버리지
        접수·장비 pull 훅)가 이 결과 때문에 자기 응답을 바꾸면 안 된다.
        """
        if now.tzinfo is None:
            raise ValueError("now 는 tz-aware 여야 한다 — naive datetime 거부")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return MissionExecutionResult(
                    MissionExecutionVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            if self._mission_store.get(mission_id) is None:
                return MissionExecutionResult(
                    MissionExecutionVerdict.UNKNOWN_MISSION, detail=MISSION_NOT_FOUND_DETAIL
                )
            current = self._effective_status_locked(mission_id)
            try:
                assert_mission_execution_transition(current, target)
            except IllegalMissionExecutionTransitionError as exc:
                return MissionExecutionResult(
                    MissionExecutionVerdict.ILLEGAL_TRANSITION, detail=str(exc)
                )
            raw: dict[str, Any] = {
                "kind": _JOURNAL_KIND,
                "ts": iso_utc(now),
                "missionId": mission_id,
                "before": current.value,
                "after": target.value,
                "detail": detail,
                "actor": actor,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return MissionExecutionResult(
                    MissionExecutionVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            record = self._apply_locked(raw)
            # journal.append 성공 뒤에만 센다 — 시도 수가 아니라 일어난 전이 수여야
            # 이름이 거짓말하지 않는다(processing_jobs 관습).
            MISSION_EXECUTION_TRANSITIONS.inc(target_status=target.value)
            return MissionExecutionResult(
                MissionExecutionVerdict.TRANSITIONED, record=record
            )


#: SSOT — 사람이 직접 선언할 수 있는 실행 상태와 그에 필요한 권한.
#:
#: 표에 **없는 상태는 누구도 선언할 수 없다**(403). ``processing_jobs`` 의
#: ``_TRANSITION_PERMISSION`` 과 같은 관용구다 — "정의되지 않은 전이를 할 권한"은
#: 누구에게도 없다.
#:
#: ``ACTIVATED`` 가 없는 이유: Edge 의 서명 activation receipt 가 만드는 사실이다.
#: ``COMPLETED``·``ENDED_INCOMPLETE`` 가 없는 이유: CoverageReport 접수가 만드는
#: 사실이고(INV-010), 사람이 찍을 수 있으면 그 상태는 근거가 아니라 주장이 된다.
_HUMAN_DECLARABLE: dict[MissionExecutionStatus, Permission] = {
    MissionExecutionStatus.DISPATCHED: Permission.MISSIONS_ISSUE,
    MissionExecutionStatus.CANCELLED: Permission.MISSIONS_ISSUE,
}


class MissionExecutionTransitionRequest(CamelModel):
    """실행 상태 선언 요청 — ``detail`` 은 "어떻게 넘겼는가"를 사람 말로 남기는 자리."""

    target_status: MissionExecutionStatus
    detail: str | None = None


class MissionExecutionHistoryEntry(CamelModel):
    mission_id: str
    before: str
    after: str
    updated_at: str
    updated_by: str
    detail: str | None


class MissionExecutionView(CamelModel):
    """실행 상태 조회 응답 — 현재 상태 + 그렇게 된 이력."""

    mission_id: str
    status: str
    #: 전이가 한 번도 없었으면 ``null`` — 그 경우 status 는 ``ISSUED`` 다.
    updated_at: str | None
    updated_by: str | None
    detail: str | None
    history: list[MissionExecutionHistoryEntry]


def _to_view(
    mission_id: str, store: MissionExecutionStore, *, detail: str | None
) -> MissionExecutionView:
    history = store.history(mission_id)
    last = history[-1] if history else None
    return MissionExecutionView(
        mission_id=mission_id,
        status=store.effective_status(mission_id).value,
        updated_at=last.updated_at.isoformat() if last is not None else None,
        updated_by=last.updated_by if last is not None else None,
        detail=detail if detail is not None else (last.detail if last is not None else None),
        history=[
            MissionExecutionHistoryEntry(
                mission_id=entry.mission_id,
                before=entry.before.value,
                after=entry.after.value,
                updated_at=entry.updated_at.isoformat(),
                updated_by=entry.updated_by,
                detail=entry.detail,
            )
            for entry in history
        ],
    )


def build_mission_execution_router(
    store: MissionExecutionStore,
    *,
    mission_store: MissionStore | None = None,
    site_lifecycle: SpatialModelLifecycle | None = None,
) -> APIRouter:
    """``mission_store``+``site_lifecycle`` 을 함께 주면 매핑 임무의 배포 선언이
    현장을 ``BASELINE_MAPPING`` 으로 전진시킨다(ADR-KSI-019 G1).

    **발급이 아니라 배포가 기준이다** — 발급만 하고 안 날린 임무가 현장 상태를
    옮기면 계획 단계의 문서가 관측 사실을 참칭한다.
    """
    router = APIRouter(prefix="/v1/missions", tags=["missions"])

    @router.post(
        "/{mission_id}/execution-transitions", response_model=MissionExecutionView
    )
    def declare_execution_transition(
        mission_id: str,
        request: MissionExecutionTransitionRequest,
        response: Response,
        principal: Principal = Depends(require_principal()),  # noqa: B008
    ) -> MissionExecutionView:
        """사람이 아는 실행 사실을 선언한다 — ``DISPATCHED``·``CANCELLED`` 만.

        요구 권한이 대상 상태마다 다르고 표에 없는 상태는 아무도 선언할 수 없어서,
        문 앞의 ``require_permission`` 하나로 표현할 수 없다(``processing_jobs``
        전이 라우트와 같은 구조).
        """
        # **durable 기록 전에** 거부한다. ``detail`` 은 제약이 없어 요청 검증을
        # 통과하는데, lone surrogate 가 들어오면 순서가 이렇게 된다 — ①journal 기록
        # 성공(ensure_ascii=True 라 ASCII 이스케이프로 들어간다) ②projection 전이
        # 완료 ③**그 뒤** 응답 직렬화에서 UnicodeEncodeError. 500 이 나가지만 전이는
        # 이미 일어났고, 그 임무의 조회·후속 전이가 영원히 500 이 된다 — 재시작해도
        # replay 가 성공해 그대로 재현되므로 원장을 손으로 고쳐야 복구된다
        # (2026-08-18 실측). 발급 라우터 두 곳이 쓰는 것과 같은 가드다.
        reject_lone_surrogates(request.model_dump(by_alias=True, mode="json", exclude_none=True))
        required = _HUMAN_DECLARABLE.get(request.target_status)
        if required is None:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"{request.target_status.value} 는 사람이 선언할 수 없다 — "
                    "장비 보고·커버리지 접수가 만드는 사실이다"
                ),
            )
        if required not in principal_permissions(principal):
            raise HTTPException(
                status_code=403, detail=f"{request.target_status.value} 선언 권한이 없다"
            )
        result = store.transition(
            mission_id,
            request.target_status,
            detail=request.detail,
            actor=principal.principal_id,
            now=datetime.now(UTC),
        )
        if (
            result.verdict is MissionExecutionVerdict.TRANSITIONED
            and request.target_status is MissionExecutionStatus.DISPATCHED
        ):
            # 매핑 계열 임무가 기체로 넘어갔다 → 현장이 매핑 시작으로 전진한다.
            # 반환값을 의도적으로 무시한다: 현장 전진 실패가 "기체로 넘겼다"는
            # 사실의 기록을 되돌리면 안 된다.
            _advance_site_for_dispatch(
                mission_id,
                mission_store=mission_store,
                site_lifecycle=site_lifecycle,
            )
        response.status_code = MISSION_EXECUTION_HTTP_STATUS[result.verdict]
        if result.verdict is MissionExecutionVerdict.UNKNOWN_MISSION:
            raise HTTPException(status_code=404, detail=MISSION_NOT_FOUND_DETAIL)
        if result.verdict is MissionExecutionVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return _to_view(mission_id, store, detail=result.detail)

    @router.get("/{mission_id}/execution", response_model=MissionExecutionView)
    def get_execution(
        mission_id: str,
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> MissionExecutionView:
        """그 임무의 실행 상태 + 이력. 전이가 없으면 ``ISSUED`` 다(레코드 부재 = ISSUED)."""
        if not store.mission_exists(mission_id):
            raise HTTPException(status_code=404, detail=MISSION_NOT_FOUND_DETAIL)
        return _to_view(mission_id, store, detail=None)

    return router


def advance_site_for_dispatch(
    mission_id: str,
    *,
    mission_store: MissionStore | None,
    site_lifecycle: SpatialModelLifecycle | None,
) -> None:
    """배포된 임무의 타입·현장을 발급 원장에서 읽어 현장 전진을 시도한다.

    두 배포 경로(운영자 선언·장비 pull)가 공유한다. 배선이 없거나 임무·타입을
    해석할 수 없으면 조용히 아무것도 하지 않는다 — 이 함수의 실패는 배포 사실의
    기록을 되돌릴 근거가 못 된다.
    """
    if mission_store is None or site_lifecycle is None:
        return
    record = mission_store.get(mission_id)
    if record is None:
        return
    try:
        mission_type = MissionType(record.mission_type)
    except ValueError:
        # 계약 스키마 밖 임무타입 문자열 — 전진 규칙을 적용할 근거가 없다.
        return
    site_lifecycle.advance_for_mission_dispatched(
        record.site_id, mission_type, mission_id=mission_id, now=datetime.now(UTC)
    )


_advance_site_for_dispatch = advance_site_for_dispatch


def mount_mission_execution(
    app: FastAPI,
    store: MissionExecutionStore,
    *,
    mission_store: MissionStore | None = None,
    site_lifecycle: SpatialModelLifecycle | None = None,
) -> None:
    """앱에 실행 상태 라우터를 장착한다 — store 없이는 엔드포인트가 존재하지 않는다."""
    app.state.mission_execution_store = store
    app.include_router(
        build_mission_execution_router(
            store, mission_store=mission_store, site_lifecycle=site_lifecycle
        )
    )


__all__ = [
    "MISSION_EXECUTION_HTTP_STATUS",
    "advance_site_for_dispatch",
    "MissionExecutionRecord",
    "MissionExecutionRecoveryError",
    "MissionExecutionResult",
    "MissionExecutionStore",
    "MissionExecutionVerdict",
    "MissionExecutionView",
    "build_mission_execution_router",
    "mount_mission_execution",
]
