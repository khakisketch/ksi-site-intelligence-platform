"""장비 클래스 지원단계 등록·전이·조회 — INV-041 의 **런타임** 강제 지점.

## 이 모듈이 채우는 자리

``ksi_domain.capability.assert_support_level_transition`` 은 정확하게 구현돼 있었지만
**프로덕션 호출부가 0건**이었다(호출 4건이 전부 ``test_capability_gate.py``). 즉
설계된 게이트가 테스트 안에서만 존재하고, 실제 운영 경로에서는 장비 지원단계라는
개념 자체가 어디에도 없었다(risk ``capability-support-level-transition-unwired``).
``is_production_supported`` 도 마찬가지로 아무도 부르지 않았다.

이 모듈이 그 둘의 유일한 운영 경로다.

## 왜 이 표면이 안전 표면인가

"이 장비 클래스를 상용으로 지원한다"는 선언은 고객 UI 와 계약에 그대로 실린다
(REQ-MODEL-101, MASTER_PRD §26.7 "장비 지원상태를 고객 UI와 계약에 정직하게 표시").
``00_READ_FIRST.md`` 의 **구현 금지** 목록에 "미검증 장비를 상용지원으로 표시"가
들어 있는 이유가 이것이다 — 잘못된 표시를 나중에 되돌려도, 그 표시를 보고 내린
운용 결정은 되돌아오지 않는다.

그래서 세 가지를 코드로 지킨다:

1. **승급은 한 단계씩, 증거와 함께.** 전이 판정은
   :func:`~ksi_domain.capability.assert_support_level_transition` 하나가 소유한다 —
   이 모듈은 그 함수를 부를 뿐 자체 판정표를 만들지 않는다(SSOT 이중화 금지).
2. **강등은 막지 않는다.** 현장 재검증 실패에 즉시 대응해야 하는 방향이라 증거를
   요구하지 않는다. 다만 그 전이도 원장에 남고, 승급 때 쌓인 증거를 **그대로
   물려받지 않는다** — 강등된 상태가 예전 승급 증거를 달고 있으면 "이 단계는
   검증됐다"는 잘못된 신호가 된다.
3. **표시는 파생값으로만 낸다.** 응답의 ``productionSupported`` 는
   :func:`~ksi_domain.capability.is_production_supported` 가 계산한다 — 화면이
   ``state`` 문자열을 보고 스스로 판단하면 새 단계가 추가되는 날 조용히 틀린다.

## 재생은 **현행** 게이트로 **과거** 레코드를 판정한다 — 알려진 결과

``_replay`` 가 live 와 같은 함수를 부르는 것은 원장 조작 우회를 막는 핵심이지만,
그 대가로 **게이트를 조일 때마다 기존 원장이 기동 불가가 될 수 있다.** 실제로
"동일 단계 재선언에도 증거 필수"(reviewer 지적 F2)가 그 첫 사례다 — 그 조임 이전에
증거 없이 재선언한 레코드가 있었다면 이 저장소는 이제 기동을 거부한다.

이번 조임은 무해함을 확인했다(그 시점에 실원장이 존재하지 않았다). 실운영 원장이
생긴 뒤에 게이트를 조일 때는 그냥 조이면 안 된다 — 레코드에 게이트 버전을 남기거나,
재생 실패 메시지에 마이그레이션 절차를 넣어야 한다(reviewer 재검증 지적 N6).
"느슨하게 재생"은 답이 아니다: 그 순간 원장 조작이 게이트 우회 경로가 된다.

## 등록은 항상 최하위 단계에서 시작한다

``POST`` 는 ``DATASET_AVAILABLE`` 로만 등록한다 — 임의 단계로 바로 등록할 수 있으면
"승급은 한 단계씩"이 등록 한 번으로 우회된다(``PRODUCTION_SUPPORTED`` 로 신규 등록).
그 우회를 막는 것이 이 제약의 전부다.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_domain.capability import (
    EquipmentSupportLevel,
    IllegalSupportLevelTransitionError,
    assert_support_level_transition,
    has_evidence,
    is_demotion,
    is_production_supported,
)
from pydantic import Field

from ksi_core.foundation.api_base import (
    JOURNAL_APPEND_FAILED_DETAIL,
    JOURNAL_SEALED_DETAIL,
    CamelModel,
    iso_utc,
)
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Permission, Principal, require_permission

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger("ksi_core.equipment_support")

_INITIAL_LEVEL = EquipmentSupportLevel.DATASET_AVAILABLE


class EquipmentSupportVerdict(StrEnum):
    RECORDED = "RECORDED"
    UNKNOWN_CLASS = "UNKNOWN_CLASS"
    ALREADY_REGISTERED = "ALREADY_REGISTERED"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[EquipmentSupportVerdict, int] = {
    EquipmentSupportVerdict.RECORDED: 200,
    EquipmentSupportVerdict.UNKNOWN_CLASS: 404,
    EquipmentSupportVerdict.ALREADY_REGISTERED: 409,
    EquipmentSupportVerdict.ILLEGAL_TRANSITION: 422,
    EquipmentSupportVerdict.STORE_UNAVAILABLE: 503,
}


class EquipmentSupportRecoveryError(RuntimeError):
    """equipment-support journal 재생 실패 — 오염된 원장으로 기동하지 않는다."""


@dataclass(frozen=True, slots=True)
class EquipmentSupportRecord:
    """장비 클래스 1건의 현재 지원단계 + 그 단계를 뒷받침하는 증거."""

    class_id: str
    state: EquipmentSupportLevel
    evidence_refs: tuple[str, ...]
    model_version: str | None
    risk_pack_version: str | None
    updated_at: datetime
    updated_by: str

    @property
    def production_supported(self) -> bool:
        """공식 상용 안전지원 표시 여부 — **파생값**이다(모듈 docstring 3항)."""
        return is_production_supported(self.state)


@dataclass(frozen=True, slots=True)
class EquipmentSupportResult:
    verdict: EquipmentSupportVerdict
    detail: str | None = None
    record: EquipmentSupportRecord | None = None


@dataclass(frozen=True, slots=True)
class SupportTransition:
    """전이 1건의 감사 기록 — 무엇에서 무엇으로, 누가, 무슨 증거로."""

    from_state: EquipmentSupportLevel | None
    to_state: EquipmentSupportLevel
    evidence_refs: tuple[str, ...]
    at: datetime
    actor: str


def _normalize_refs(refs: tuple[str, ...]) -> tuple[str, ...]:
    """내용 없는 항목을 버리고 나머지를 strip 한다 — 저장과 판정이 같은 값을 본다.

    두 번의 실측이 이 함수를 지금 모양으로 만들었다:

    1. ``["  ", " "]`` 같은 입력을 그냥 이어붙이면 구분자(``"; "``)가 비공백이라
       ``"  ;  "`` 이 되고, 그 문자열은 증거 검사를 **통과한다** — 공백만인 증거
       두 개로 승급이 되는 구멍이었다(계약 테스트가 잡음).
    2. 항목 필터가 ``str.strip()`` 이면 ``["\u200b", "report://x"]`` 의 보이지 않는
       항목이 그대로 원장에 저장된다 — 전체 판정은 두 번째 항목으로 통과하므로
       아무도 못 본다(reviewer 재검증 지적 N2). 판정과 같은 규칙
       (:func:`~ksi_domain.capability.has_evidence`)으로 걸러야 "원장에 남는 증거는
       전부 실제 내용이 있다"가 성립한다.
    """
    return tuple(ref.strip() for ref in refs if has_evidence(ref))


def _carry_forward(requested: str | None, previous: str | None, demoting: bool) -> str | None:
    """부분 갱신 규칙 — 요청이 말하지 않은 메타데이터를 이어받을지 결정한다.

    승급·재선언은 이어받고, 강등은 이어받지 않는다(:meth:`EquipmentSupportStore.transition`
    의 인라인 주석에 근거).
    """
    if requested is not None:
        return requested
    return None if demoting else previous


def _joined_evidence(refs: tuple[str, ...]) -> str:
    """``assert_support_level_transition`` 에 넘길 단일 증거 문자열(정규화 후)."""
    return "; ".join(refs)


class EquipmentSupportStore:
    """``DurableJournal`` 위의 장비 지원단계 원장 — 전이는 전부 append 된다."""

    def __init__(self, journal: DurableJournal) -> None:
        self._journal = journal
        self._lock = threading.Lock()
        self._records: dict[str, EquipmentSupportRecord] = {}
        self._transitions: dict[str, list[SupportTransition]] = {}
        try:
            self._replay(journal)
        except EquipmentSupportRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise EquipmentSupportRecoveryError(
                f"equipment-support journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw.get("kind")
            if kind == "equipment-support-rejected":
                continue
            if kind not in (None, "equipment-support-registered", "equipment-support-transitioned"):
                raise EquipmentSupportRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")
            class_id = raw["classId"]
            state = EquipmentSupportLevel(raw["state"])
            refs = _normalize_refs(tuple(raw.get("evidenceRefs") or ()))
            at = datetime.fromisoformat(raw["ts"])
            actor = raw["actor"]
            current = self._records.get(class_id)
            if kind == "equipment-support-registered":
                if current is not None:
                    raise EquipmentSupportRecoveryError(
                        f"재생: classId={class_id!r} 가 두 번 등록됐다"
                    )
                if state is not _INITIAL_LEVEL:
                    # 등록은 항상 최하위 단계다(모듈 docstring) — journal 조작으로
                    # PRODUCTION_SUPPORTED 신규 등록이 되살아나는 경로를 막는다.
                    raise EquipmentSupportRecoveryError(
                        f"재생: classId={class_id!r} 등록 단계가 {state.value} 다 — "
                        f"등록은 {_INITIAL_LEVEL.value} 로만 가능하다"
                    )
            else:
                if current is None:
                    raise EquipmentSupportRecoveryError(
                        f"재생: 미등록 classId={class_id!r} 의 전이 레코드"
                    )
                # 재생도 live 와 같은 게이트를 탄다 — 원장 조작이 단계 스킵 승급의
                # 우회 경로가 되지 않는다.
                try:
                    assert_support_level_transition(
                        current.state, state, evidence=_joined_evidence(refs)
                    )
                except IllegalSupportLevelTransitionError as exc:
                    raise EquipmentSupportRecoveryError(
                        f"재생: 허용되지 않는 전이 — classId={class_id!r}: {exc}"
                    ) from exc
            self._records[class_id] = EquipmentSupportRecord(
                class_id=class_id,
                state=state,
                evidence_refs=refs,
                model_version=raw.get("modelVersion"),
                risk_pack_version=raw.get("riskPackVersion"),
                updated_at=at,
                updated_by=actor,
            )
            self._transitions.setdefault(class_id, []).append(
                SupportTransition(
                    from_state=current.state if current is not None else None,
                    to_state=state,
                    evidence_refs=refs,
                    at=at,
                    actor=actor,
                )
            )

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def register(
        self,
        class_id: str,
        *,
        evidence_refs: tuple[str, ...],
        model_version: str | None,
        risk_pack_version: str | None,
        now: datetime,
        actor: str,
    ) -> EquipmentSupportResult:
        """장비 클래스를 ``DATASET_AVAILABLE`` 로 등록한다(모듈 docstring)."""
        evidence_refs = _normalize_refs(evidence_refs)
        with self._lock:
            if self._journal.sealed_reason is not None:
                return EquipmentSupportResult(
                    EquipmentSupportVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            if class_id in self._records:
                return EquipmentSupportResult(
                    EquipmentSupportVerdict.ALREADY_REGISTERED,
                    detail=f"classId={class_id!r} 는 이미 등록돼 있다 — 단계 변경은 PATCH 다",
                )
            return self._append(
                "equipment-support-registered",
                class_id=class_id,
                state=_INITIAL_LEVEL,
                evidence_refs=evidence_refs,
                model_version=model_version,
                risk_pack_version=risk_pack_version,
                now=now,
                actor=actor,
                previous=None,
            )

    def transition(
        self,
        class_id: str,
        target: EquipmentSupportLevel,
        *,
        evidence_refs: tuple[str, ...],
        model_version: str | None,
        risk_pack_version: str | None,
        now: datetime,
        actor: str,
    ) -> EquipmentSupportResult:
        """지원단계를 바꾼다 — 판정은 ``assert_support_level_transition`` 이 한다.

        이 메서드는 전이표를 스스로 갖지 않는다. 도메인 함수가 SSOT 이고, 그
        함수가 던지면 그대로 ``ILLEGAL_TRANSITION`` 이다.
        """
        evidence_refs = _normalize_refs(evidence_refs)
        with self._lock:
            if self._journal.sealed_reason is not None:
                return EquipmentSupportResult(
                    EquipmentSupportVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            current = self._records.get(class_id)
            if current is None:
                return EquipmentSupportResult(
                    EquipmentSupportVerdict.UNKNOWN_CLASS,
                    detail=f"등록된 적 없는 장비 클래스다 (classId={class_id!r})",
                )
            demoting = is_demotion(current.state, target)
            try:
                assert_support_level_transition(
                    current.state, target, evidence=_joined_evidence(evidence_refs)
                )
            except IllegalSupportLevelTransitionError as exc:
                return self._reject(
                    class_id,
                    target,
                    now,
                    actor,
                    EquipmentSupportVerdict.ILLEGAL_TRANSITION,
                    str(exc),
                )
            return self._append(
                "equipment-support-transitioned",
                class_id=class_id,
                state=target,
                evidence_refs=evidence_refs,
                # 승급·재선언은 부분 갱신이다 — 요청이 버전을 말하지 않았으면 이전
                # 값을 이어받는다. 예전엔 무조건 덮어써서, 사다리를 정상적으로 올라간
                # PRODUCTION_SUPPORTED 레코드가 modelVersion=null 로 끝났다(reviewer
                # 지적 F4) — 상용지원 선언을 뒷받침할 모델 버전이 정상 경로로 비워지는
                # 자리였다.
                #
                # **강등에서는 이어받지 않는다.** evidence_refs 를 물려주지 않는 것과
                # 같은 이유다(모듈 docstring 2항): "PRODUCTION_SUPPORTED 를 이 모델로
                # 세웠다"는 사실은 그 단계에서 내려온 뒤에는 더 이상 이 레코드의
                # 근거가 아니다. 모델 회귀로 강등하는 경우가 특히 그렇다 — 방금
                # 못 믿게 된 그 버전이 새 단계의 뒷받침으로 남는다(reviewer 재검증
                # 지적 N3㉡, 정책 확정). 강등 후 값을 다시 붙이려면 요청에 명시한다.
                model_version=_carry_forward(model_version, current.model_version, demoting),
                risk_pack_version=_carry_forward(
                    risk_pack_version, current.risk_pack_version, demoting
                ),
                now=now,
                actor=actor,
                previous=current,
            )

    def _append(
        self,
        kind: str,
        *,
        class_id: str,
        state: EquipmentSupportLevel,
        evidence_refs: tuple[str, ...],
        model_version: str | None,
        risk_pack_version: str | None,
        now: datetime,
        actor: str,
        previous: EquipmentSupportRecord | None,
    ) -> EquipmentSupportResult:
        """``self._lock`` 을 쥔 채로만 호출된다."""
        record = {
            "kind": kind,
            "ts": iso_utc(now),
            "classId": class_id,
            "state": state.value,
            "evidenceRefs": list(evidence_refs),
            "modelVersion": model_version,
            "riskPackVersion": risk_pack_version,
            "actor": actor,
        }
        try:
            self._journal.append(record)
        except JournalSealedError:
            return EquipmentSupportResult(
                EquipmentSupportVerdict.STORE_UNAVAILABLE,
                detail=JOURNAL_APPEND_FAILED_DETAIL,
            )
        # 새 단계의 증거는 이번 전이가 제시한 것만이다 — 승급 때 쌓인 증거를
        # 강등된 상태가 그대로 물려받으면 "이 단계는 검증됐다"는 잘못된 신호가
        # 된다(모듈 docstring 2항).
        stored = EquipmentSupportRecord(
            class_id=class_id,
            state=state,
            evidence_refs=evidence_refs,
            model_version=model_version,
            risk_pack_version=risk_pack_version,
            updated_at=now,
            updated_by=actor,
        )
        self._records[class_id] = stored
        self._transitions.setdefault(class_id, []).append(
            SupportTransition(
                from_state=previous.state if previous is not None else None,
                to_state=state,
                evidence_refs=evidence_refs,
                at=now,
                actor=actor,
            )
        )
        return EquipmentSupportResult(EquipmentSupportVerdict.RECORDED, record=stored)

    def _reject(
        self,
        class_id: str,
        target: EquipmentSupportLevel,
        now: datetime,
        actor: str,
        verdict: EquipmentSupportVerdict,
        detail: str,
    ) -> EquipmentSupportResult:
        """거부도 원장에 남긴다 — 누가 무슨 승급을 시도해 막혔는지가 감사 입력이다."""
        record = {
            "kind": "equipment-support-rejected",
            "ts": iso_utc(now),
            "classId": class_id,
            "attemptedState": target.value,
            "verdict": verdict.value,
            "detail": detail,
            "actor": actor,
        }
        try:
            self._journal.append(record)
        except JournalSealedError:
            return EquipmentSupportResult(
                EquipmentSupportVerdict.STORE_UNAVAILABLE,
                detail=JOURNAL_APPEND_FAILED_DETAIL,
            )
        return EquipmentSupportResult(verdict, detail=detail)

    def get(self, class_id: str) -> EquipmentSupportRecord | None:
        with self._lock:
            return self._records.get(class_id)

    def list_all(self) -> list[EquipmentSupportRecord]:
        """classId 오름차순 — 응답 순서를 결정적으로 고정한다."""
        with self._lock:
            return [self._records[c] for c in sorted(self._records)]

    def transitions(self, class_id: str) -> list[SupportTransition]:
        with self._lock:
            return list(self._transitions.get(class_id, ()))


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class EquipmentSupportRegisterRequest(CamelModel):
    class_id: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    model_version: str | None = None
    risk_pack_version: str | None = None


class EquipmentSupportTransitionRequest(CamelModel):
    state: EquipmentSupportLevel
    evidence_refs: list[str] = Field(default_factory=list)
    model_version: str | None = None
    risk_pack_version: str | None = None


class EquipmentSupportView(CamelModel):
    """계약(``equipment-support-state.v1.json``) 필드 + 파생 표시 플래그.

    ``productionSupported`` 를 서버가 계산해서 내는 이유는 모듈 docstring 3항 —
    화면이 ``state`` 문자열을 보고 스스로 판단하면 단계가 추가되는 날 조용히 틀린다.
    """

    class_id: str
    state: str
    evidence_refs: list[str]
    model_version: str | None
    risk_pack_version: str | None
    production_supported: bool
    updated_at: datetime
    updated_by: str


class EquipmentSupportListView(CamelModel):
    class_count: int
    production_supported_count: int
    classes: list[EquipmentSupportView]


class EquipmentSupportMutationResponse(CamelModel):
    verdict: str
    detail: str | None
    record: EquipmentSupportView | None


# 라우트 두 곳이 같은 의존성을 쓴다 — 모듈 상수로 한 번만 만든다(B008 회피이자,
# 이 표면의 권한이 한 자리에서만 정해지게 하는 장치다).
_require_support_approver = require_permission(Permission.EQUIPMENT_SUPPORT_APPROVE)


def _view(record: EquipmentSupportRecord) -> EquipmentSupportView:
    return EquipmentSupportView(
        class_id=record.class_id,
        state=record.state.value,
        evidence_refs=list(record.evidence_refs),
        model_version=record.model_version,
        risk_pack_version=record.risk_pack_version,
        production_supported=record.production_supported,
        updated_at=record.updated_at,
        updated_by=record.updated_by,
    )


def build_equipment_support_router(store: EquipmentSupportStore) -> APIRouter:
    router = APIRouter(prefix="/v1/equipment-support", tags=["equipment-support"])

    @router.get("", response_model=EquipmentSupportListView)
    def list_equipment_support(
        _principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> EquipmentSupportListView:
        """등록된 장비 클래스 전체 + 각각의 지원단계(MASTER_PRD §26.7).

        ``productionSupported`` 가 ``true`` 인 것만 상용 지원으로 표시해야 한다 —
        나머지는 전부 "검증 중"이다(REQ-MODEL-101).
        """
        records = store.list_all()
        return EquipmentSupportListView(
            class_count=len(records),
            production_supported_count=sum(1 for r in records if r.production_supported),
            classes=[_view(r) for r in records],
        )

    @router.get("/{class_id}", response_model=EquipmentSupportView)
    def get_equipment_support(
        class_id: str,
        _principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> EquipmentSupportView:
        record = store.get(class_id)
        if record is None:
            raise HTTPException(status_code=404, detail="등록된 적 없는 장비 클래스다")
        return _view(record)

    @router.post("", status_code=201)
    def register_equipment_class(
        body: EquipmentSupportRegisterRequest,
        response: Response,
        principal: Principal = Depends(_require_support_approver),  # noqa: B008
    ) -> EquipmentSupportMutationResponse:
        """장비 클래스를 ``DATASET_AVAILABLE`` 로 등록한다.

        임의 단계로 바로 등록할 수 없다 — 가능하면 "승급은 한 단계씩"이 등록 한 번
        으로 우회된다(``PRODUCTION_SUPPORTED`` 신규 등록).
        """
        result = store.register(
            body.class_id,
            evidence_refs=tuple(body.evidence_refs),
            model_version=body.model_version,
            risk_pack_version=body.risk_pack_version,
            now=datetime.now(UTC),
            actor=principal.principal_id,
        )
        response.status_code = (
            201 if result.verdict is EquipmentSupportVerdict.RECORDED else _STATUS[result.verdict]
        )
        return EquipmentSupportMutationResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            record=_view(result.record) if result.record is not None else None,
        )

    @router.patch("/{class_id}")
    def transition_equipment_support(
        class_id: str,
        body: EquipmentSupportTransitionRequest,
        response: Response,
        principal: Principal = Depends(_require_support_approver),  # noqa: B008
    ) -> EquipmentSupportMutationResponse:
        """지원단계 승급/강등 — INV-041 강제 지점.

        승급은 한 단계씩이고 증거가 필수다. 강등은 증거 없이도 허용된다(현장 재검증
        실패에 즉시 대응해야 하는 방향에 마찰을 넣지 않는다) — 다만 그 전이도 원장에
        남고, 강등된 상태는 승급 때의 증거를 물려받지 않는다.
        """
        result = store.transition(
            class_id,
            body.state,
            evidence_refs=tuple(body.evidence_refs),
            model_version=body.model_version,
            risk_pack_version=body.risk_pack_version,
            now=datetime.now(UTC),
            actor=principal.principal_id,
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is EquipmentSupportVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return EquipmentSupportMutationResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            record=_view(result.record) if result.record is not None else None,
        )

    return router


def mount_equipment_support(app: FastAPI, store: EquipmentSupportStore) -> None:
    app.include_router(build_equipment_support_router(store))


__all__ = [
    "EquipmentSupportListView",
    "EquipmentSupportRecord",
    "EquipmentSupportRecoveryError",
    "EquipmentSupportResult",
    "EquipmentSupportStore",
    "EquipmentSupportVerdict",
    "EquipmentSupportView",
    "build_equipment_support_router",
    "mount_equipment_support",
]
