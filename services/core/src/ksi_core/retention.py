"""보관 정책 집행 (ADR-KSI-010 §3, ``contracts/schemas/retention-policy.v1.json``).

보관 기간이 지난 증거를 **폐기 표시하고 객체를 삭제한다**. 원장 레코드 자체는
수정도 삭제도 하지 않는다 — append-only 원장에서 과거를 고쳐 쓰는 순간 감사
추적이 감사 대상이 된다.

## 판정과 실행을 나눈다

:func:`plan_expiry` 는 **순수 함수**다. 무엇이 만료됐는지만 답하고 아무것도
바꾸지 않는다. :func:`execute_expiry` 만 부수효과를 낸다.

데이터를 지우는 코드는 지우기 전에 무엇을 지울지 보여줄 수 있어야 한다.
둘을 한 함수에 묶으면 dry-run 이 "실행하되 마지막에 롤백"이 되고, 그건
dry-run 이 아니다.

## 자동 스케줄러를 두지 않는다

집행은 명시적 호출이다. 데이터를 지우는 코드가 아무도 부르지 않았는데 도는
것보다, 운영자가 부르는 편이 낫다 — 잘못된 정책값이 배포되면 스케줄러는
그걸 즉시 집행하지만 수동 실행은 사람이 한 번 본다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ksi_domain.enums import EventStatus

from .evidence import EvidenceStorageError, EvidenceVerdict

if TYPE_CHECKING:
    from .events import EventRecord, EventStore
    from .evidence import EvidenceStorage

logger = logging.getLogger(__name__)

# 확정 이벤트는 다른 축의 보관 기간을 쓴다 — 사고와 직결되는 증거라 후행 조사·
# 분쟁 대응 기간이 훨씬 길다(retention-policy.v1 의 confirmedEventDays).
_CONFIRMED_STATUSES = frozenset({EventStatus.CONFIRMED_EVENT})


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """``retention-policy.v1`` 의 실행 표현.

    스키마의 6개 필드 중 이 모듈이 **집행하는 것은 둘뿐이다** —
    ``candidateDays``·``confirmedEventDays``. 나머지(patrolRaw·telemetryMission·
    auditAction·spatialArtifact)는 Core 원장이 아직 소유하지 않는 데이터라
    집행 대상이 없다. 값은 읽어두되 쓰지 않는다는 사실을 여기 남긴다 —
    "정책에 있으니 집행되고 있겠지"가 가장 위험한 오해다.
    """

    candidate_days: int
    patrol_raw_days: int
    confirmed_event_days: int
    telemetry_mission_days: int
    audit_action_days: int
    spatial_artifact_after_contract_days: int

    @property
    def enforced_fields(self) -> tuple[str, ...]:
        """이 구현이 실제로 집행하는 정책 필드."""
        return ("candidateDays", "confirmedEventDays")

    def retention_for(self, status: EventStatus) -> timedelta:
        days = (
            self.confirmed_event_days
            if status in _CONFIRMED_STATUSES
            else self.candidate_days
        )
        return timedelta(days=days)


def load_policy(path: Path) -> RetentionPolicy:
    """정책 파일을 읽는다 — 필드 누락·음수는 기동을 거부한다(fail-closed).

    기본값으로 조용히 채우지 않는다. 보관 기간은 법적 의무와 얽힌 값이라,
    "파일에 없어서 30일로 봤다"가 나중에 설명 가능한 사유가 되지 않는다.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: retention policy 는 object 여야 한다")
    fields = {
        "candidate_days": "candidateDays",
        "patrol_raw_days": "patrolRawDays",
        "confirmed_event_days": "confirmedEventDays",
        "telemetry_mission_days": "telemetryMissionDays",
        "audit_action_days": "auditActionDays",
        "spatial_artifact_after_contract_days": "spatialArtifactAfterContractDays",
    }
    values: dict[str, int] = {}
    for attr, key in fields.items():
        if key not in raw:
            raise ValueError(f"{path}: 필수 보관 기간 누락 — {key}")
        value = raw[key]
        # bool 은 int 의 서브클래스라 따로 막는다(True 가 1일로 통과하는 경로).
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{path}: {key} 는 0 이상의 정수여야 한다 — {value!r}")
        values[attr] = value
    return RetentionPolicy(**values)


# EventStore.list 의 limit 상한. 이보다 큰 값은 422 로 거부된다(events.py).
_PAGE_SIZE = 500


def _all_events(store: EventStore) -> Iterator[EventRecord]:
    """이벤트 원장 **전체**를 페이지로 순회한다.

    한 번의 ``store.list(limit=500)`` 으로 끝내면 안 된다 — 그 목록은 occurred_at
    **내림차순**이라 최신 500건이고, 만료 대상은 정의상 **가장 오래된** 것들이다.
    즉 이벤트가 500건을 넘는 순간 만료 후보가 구조적으로 창 밖으로 밀려나고,
    재실행해도 창은 항상 최신 500건이라 **영영 복귀하지 않는다** — 게다가 도구는
    "만료된 증거 없음"이라는 거짓 clean 리포트를 낸다(독립 재검토 2026-08-04 F1,
    501건 시드로 재현 확인).

    순회 중 새 이벤트가 들어오면 페이지가 밀릴 수 있다. 정렬이 최신 우선이라
    밀림은 **앞쪽**(최근)에서 일어나고 만료 대상은 뒤쪽이므로, 최악의 결과는
    이번 회차에서 몇 건을 덜 보는 것(under-report)이다 — 삭제 과다 방향이 아니다.
    """
    offset = 0
    while True:
        page = store.list(limit=_PAGE_SIZE, offset=offset)
        if not page:
            return
        yield from page
        if len(page) < _PAGE_SIZE:
            return
        offset += len(page)


@dataclass(frozen=True, slots=True)
class ExpiryAction:
    """폐기 대상 1건 — 판정 결과이지 실행 결과가 아니다."""

    event_key: str
    artifact_id: str
    object_key: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExpiryReport:
    """집행 결과.

    ``storage_failures`` 가 비어 있지 않아도 tombstone 은 이미 기록됐다 —
    원장이 먼저이기 때문이다(:func:`execute_expiry` docstring). 호출자는 이
    목록을 보고 객체 삭제만 재시도하면 된다.
    """

    tombstoned: tuple[ExpiryAction, ...] = ()
    storage_failures: tuple[tuple[ExpiryAction, str], ...] = ()
    skipped: tuple[tuple[ExpiryAction, str], ...] = ()


def plan_expiry(
    store: EventStore, policy: RetentionPolicy, *, now: datetime
) -> list[ExpiryAction]:
    """만료된 증거 목록 — **순수 판정, 아무것도 바꾸지 않는다.**

    기준 시각은 증거 등록 시각이 아니라 **사건 발생 시각**(``occurredAt``)이다.
    보관 의무는 "언제 일어난 일인가"에 걸리지, 증거를 언제 업로드했는지에
    걸리지 않는다 — 뒤늦게 올라온 증거가 그 사건의 다른 증거보다 오래 남으면
    같은 사건의 증거가 서로 다른 시점에 사라진다.
    """
    if now.tzinfo is None:
        raise ValueError("now 는 tz-aware 여야 한다")
    actions: list[ExpiryAction] = []
    for record in _all_events(store):
        retention = policy.retention_for(record.status)
        expires_at = record.occurred_at + retention
        if now < expires_at:
            continue
        field = (
            "confirmedEventDays" if record.status in _CONFIRMED_STATUSES else "candidateDays"
        )
        # 사유에 **어느 정책 필드로 몇 일이 지났는지**를 남긴다 — 나중에 "이건
        # 왜 지워졌나"에 답할 수 있어야 tombstone 이 기록으로서 값어치를 갖는다.
        reason = (
            f"retention-policy.v1 {field} {retention.days}일 경과"
            f" (occurredAt {record.occurred_at.isoformat()})"
        )
        for artifact in record.evidence:
            if artifact.is_tombstoned:
                continue
            actions.append(
                ExpiryAction(
                    event_key=record.event_key,
                    artifact_id=artifact.artifact_id,
                    object_key=artifact.object_key,
                    reason=reason,
                )
            )
    return actions


def execute_expiry(
    store: EventStore,
    storage: EvidenceStorage,
    actions: list[ExpiryAction],
    *,
    now: datetime,
) -> ExpiryReport:
    """폐기를 집행한다 — **원장이 먼저, 객체 삭제가 나중.**

    순서를 뒤집으면 객체는 사라졌는데 원장은 아무 말도 못 하는 상태가 생긴다.
    반대로 이 순서에서는 삭제가 실패해도 "폐기하기로 했다"는 사실이 남고,
    재시도는 객체 삭제만 하면 된다.
    """
    tombstoned: list[ExpiryAction] = []
    failures: list[tuple[ExpiryAction, str]] = []
    skipped: list[tuple[ExpiryAction, str]] = []

    for action in actions:
        result = store.tombstone_evidence(
            event_key=action.event_key,
            artifact_id=action.artifact_id,
            reason=action.reason,
            now=now,
        )
        if result.verdict is not EvidenceVerdict.REGISTERED:
            # 이미 폐기됐거나 사라진 대상 — 판정과 집행 사이에 상태가 바뀐 경우다.
            skipped.append((action, result.verdict.value))
            continue
        try:
            storage.delete(action.object_key)
        except EvidenceStorageError as exc:
            logger.warning(
                "증거 객체 삭제 실패(원장 tombstone 은 기록됨): %s — %s",
                action.object_key,
                type(exc).__name__,
            )
            failures.append((action, type(exc).__name__))
        tombstoned.append(action)

    return ExpiryReport(
        tombstoned=tuple(tombstoned),
        storage_failures=tuple(failures),
        skipped=tuple(skipped),
    )


__all__ = [
    "ExpiryAction",
    "ExpiryReport",
    "RetentionPolicy",
    "execute_expiry",
    "load_policy",
    "plan_expiry",
]
