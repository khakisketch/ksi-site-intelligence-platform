"""Event Projection·트리아지·감사 (ADR-KSI-008 §3/§4).

Edge 가 보낸 EventBundle(v1.2)을 :class:`~ksi_core.durable_journal.DurableJournal`
위에 projection 하고, 서버측 트리아지(확정/오탐/배정 이후 워크플로)를 진행한다.
``ksi_core.edge_sync`` 의 durable journal 내부(잠금·fsync·복구 경로)는 재작성하지
않는다 — 이 모듈은 재사용 :class:`~ksi_core.durable_journal.DurableJournal` 위에
조립한다(ADR-KSI-008 §1).

## 감사는 도메인 journal 레코드 자체에 내장된다

별도 audit 저장소를 두지 않는다(ADR-KSI-008 §3) — 모든 상태변화는
``kind``(event-projected/event-updated/event-diverged/event-transitioned)·
``ts``·``actor``(장비 projection 은 ``edge_device_id``, 트리아지는 인증
Principal 의 ``principal_id``)·``before``/``after``·``reason``·evidence
스냅샷을 담은 journal 레코드로 append 된다. 재시작 시 이 레코드들을 순서대로
재생(``_apply``)해 인메모리 projection(:class:`EventRecord`)을 복원한다 —
재생 로직과 실시간 적용 로직이 같은 함수를 공유해 drift 를 만들지 않는다.

## 사건 신원은 장비별로 스코프된다 (event_key)

``eventId`` 는 **장비 로컬 식별자**다 — 실제 생성 규칙이 장비 로컬 track 번호
기반(``evt-ent-1`` 류)이라 장비 간 자연 충돌이 일어난다. 그래서 서버의 정본
신원은 ``event_key = "{edgeDeviceId}::{eventId}"`` 이고, projection·조회·
트리아지 전부 이 키로 돈다. 그 결과 ① 장비 A 의 사건을 장비 B 가 덮어쓰거나
기각해 묻어버리는 경로가 존재하지 않고 ② id 가 겹친 두 장비의 사건이 서로를
가리지 않고 각각 트리아지 표면에 나타난다. ``::`` 를 포함한 식별자는 키를
모호하게 만들므로 typed 거부한다(``INVALID_EVENT_IDENTITY``).

## 확정/기각은 Edge 가 주장할 수 없다 (INV-021 게이트의 유일 관문)

Edge 가 보낸 bundle 의 ``status`` 는 **비종단 상태만** 허용한다 —
``CONFIRMED_EVENT``/``DISMISSED`` 는 서버 트리아지(인증 운영자)의 업무 판정이며
(MASTER_PRD §8.1 "사용자가 업무적으로 확정한다", §7.6 확정/오탐), 종단이라
되돌릴 수 없다. Edge 가 그 값을 실어 보내면 ``STATUS_NOT_EDGE_ASSERTABLE`` 로
거부하고 ACK 하지 않는다(INV-040 fail-closed — 서버가 검증할 수 없는 확정을
조용히 수용하지 않는다). 이 게이트가 없으면 evidence 없는 CRITICAL 이
INV-021 검사를 우회해 확정되거나, 안전 findings 가 기각으로 영구 매장된다.
실제 인지 파이프라인은 ``OBSERVATION``→``CANDIDATE`` 까지만 발행한다.

## Edge update 는 서버 확정/기각을 뒤집지 못한다

서버 트리아지가 이미 ``CONFIRMED_EVENT``/``DISMISSED`` 로 확정한 사건에 대한
Edge 의 후행 update 는 내용이 달라도 무조건 ``UPDATE_DIVERGED`` 로 격리한다 —
저장 상태는 유지하고 divergence 레코드만 append 한다. ACK 는 막지 않는다(원문은
edge-sync journal 에 이미 durable 하므로 장비 sync 를 독살하지 않는다).

## INV-021 확정 게이트

``CONFIRMED_EVENT`` 로의 전이는 전이표 적법성(``assert_event_transition``,
사실상 ``FINDING`` 에서만 도달 가능)에 더해 비공백 확정 근거(``reason``)와
심각도별 Evidence 정책(MASTER_PRD §17.1)을 요구한다 — ``HIGH`` 이상은
``evidence.clips`` 가 비어있으면 거부, ``CRITICAL`` 은
``riskFieldArtifact``/``trajectoryArtifact``/``viewpointHistoryArtifact`` 도
필수다. 통과 시 감사 레코드에 ``spatialContext`` 스냅샷을 남긴다. 서버는
기하학적 위험중첩을 재계산하지 않는다 — 근거 보존과 fail-closed 거부만 소유한다.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from ksi_domain.enums import (
    EventStatus,
    IllegalEventTransitionError,
    IllegalTriageTransitionError,
    Severity,
    TriageStatus,
    assert_event_transition,
    assert_triage_transition,
    can_event_transition,
)
from ksi_event_contracts.event_bundle import EventBundle
from ksi_event_contracts.offline_sync import payload_digest
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.alias_generators import to_camel

from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.durable_journal import JournalSealedError
from ksi_core.identifiers import is_path_safe_identifier

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import FastAPI

    from ksi_core.durable_journal import DurableJournal

logger = logging.getLogger(__name__)


class EventVerdict(StrEnum):
    """Event projection·트리아지 판정 (ADR-KSI-008 §3/§4)."""

    PROJECTED = "PROJECTED"
    EVENT_UPDATED = "EVENT_UPDATED"
    DUPLICATE_PROJECTION = "DUPLICATE_PROJECTION"
    INVALID_EVENT_IDENTITY = "INVALID_EVENT_IDENTITY"
    INVALID_EVENT_TIMESTAMP = "INVALID_EVENT_TIMESTAMP"
    STATUS_NOT_EDGE_ASSERTABLE = "STATUS_NOT_EDGE_ASSERTABLE"
    UPDATE_DIVERGED = "UPDATE_DIVERGED"
    TRANSITIONED = "TRANSITIONED"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    UNKNOWN_EVENT = "UNKNOWN_EVENT"
    INVALID_REQUEST = "INVALID_REQUEST"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


# verdict → HTTP status (edge_sync.py:321 관습 — 모듈 상수 하나가 SSOT).
# PROJECTED/EVENT_UPDATED/DUPLICATE_PROJECTION/UPDATE_DIVERGED/INVALID_EVENT_IDENTITY/
# STATUS_NOT_EDGE_ASSERTABLE 는 project_bundle 전용 결과라 이 라우터에서 직접
# 반환되지 않지만(edge_sync 장착부가 소비), 완전성을 위해 전 멤버를 채운다
# (test_status_map_covers_every_verdict 관습).
_STATUS: dict[EventVerdict, int] = {
    EventVerdict.PROJECTED: 201,
    EventVerdict.EVENT_UPDATED: 200,
    EventVerdict.DUPLICATE_PROJECTION: 200,
    EventVerdict.INVALID_EVENT_IDENTITY: 422,
    EventVerdict.INVALID_EVENT_TIMESTAMP: 422,
    EventVerdict.STATUS_NOT_EDGE_ASSERTABLE: 422,
    EventVerdict.UPDATE_DIVERGED: 200,
    EventVerdict.TRANSITIONED: 200,
    EventVerdict.ILLEGAL_TRANSITION: 409,
    EventVerdict.EVIDENCE_INCOMPLETE: 422,
    EventVerdict.UNKNOWN_EVENT: 404,
    EventVerdict.INVALID_REQUEST: 422,
    EventVerdict.STORE_UNAVAILABLE: 503,
}

_FINALIZED_STATUSES = frozenset({EventStatus.CONFIRMED_EVENT, EventStatus.DISMISSED})
# Edge 가 bundle 로 주장할 수 있는 상태 — 종단(확정/기각)은 서버 트리아지 전용
# (모듈 docstring "확정/기각은 Edge 가 주장할 수 없다" 절, MASTER_PRD §8.1/§7.6).
_EDGE_ASSERTABLE_STATUSES = frozenset(EventStatus) - _FINALIZED_STATUSES
# event_key 구분자 — 식별자에 포함되면 키가 모호해지므로 typed 거부한다.
_EVENT_KEY_SEPARATOR = "::"
_REASON_REQUIRED_STATUSES = frozenset({EventStatus.CONFIRMED_EVENT, EventStatus.DISMISSED})
_EVIDENCE_GATED_SEVERITIES = frozenset({Severity.HIGH, Severity.CRITICAL})
_CRITICAL_ARTIFACT_FIELDS = ("riskFieldArtifact", "trajectoryArtifact", "viewpointHistoryArtifact")

_NOT_FOUND_DETAIL = "이벤트를 찾을 수 없다"


@dataclass(frozen=True, slots=True)
class EventRecord:
    """Event projection 1건 — journal 재생으로 복원되는 인메모리 상태.

    ``transitions`` 는 이 이벤트에 관련된 journal 레코드(projected/updated/
    diverged/transitioned) 전부의 순서 보존 사본이다 — 도메인 journal 자체가
    곧 감사 원장이라는 ADR-KSI-008 §3 원칙을 이 레코드 위에서도 그대로 보인다.
    """

    event_key: str
    event_id: str
    site_id: str
    mission_id: str
    bundle: dict[str, Any]
    status: EventStatus
    triage: TriageStatus
    assignee: str | None
    edge_device_id: str
    occurred_at: datetime
    received_at: datetime
    last_conflict_at: datetime | None
    transitions: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def severity(self) -> Severity | None:
        raw = self.bundle.get("severity")
        return Severity(raw) if raw is not None else None


@dataclass(frozen=True, slots=True)
class TriageTransitionResult:
    verdict: EventVerdict
    detail: str | None = None
    record: EventRecord | None = None


def _require_tz_aware(value: datetime, *, param: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{param} 은 tz-aware 여야 한다")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def make_event_key(edge_device_id: str, event_id: str) -> str:
    """서버 정본 사건 신원 — 장비 로컬 ``eventId`` 를 장비로 스코프한다.

    ``event_key`` 는 그대로 ``/v1/events/{event_key}`` 의 경로 세그먼트가 된다
    (2차 독립 재검토 P1) — 그래서 구성요소 각각이 경로-안전 문자만 허용해야
    한다. ``'/'`` 를 포함한 ``eventId`` 는 이 검증 없이는 durable 기록(PROJECTED)
    까지는 성공하고, 이후 상세 조회·트리아지 전이 라우트에는 영구히 도달할 수
    없는 사건을 만든다(전이 없이는 INV-021 게이트를 통과할 방법이 없어
    영원히 미확정으로 남는다).

    Raises:
        ValueError: 어느 한쪽이 경로-안전 문자 집합(:mod:`ksi_core.identifiers`)
            밖의 문자(``/``·공백·제어문자 등)를 포함할 때. 구분자(``::``)
            자체는 콜론이 경로-안전 집합에 없어 이 검사에 이미 포함된다.
    """
    if not is_path_safe_identifier(edge_device_id) or not is_path_safe_identifier(event_id):
        raise ValueError("edgeDeviceId·eventId 는 경로-안전 문자만 허용한다")
    return f"{edge_device_id}{_EVENT_KEY_SEPARATOR}{event_id}"


def classify_edge_bundle(
    payload: Mapping[str, Any], *, edge_device_id: str
) -> EventVerdict | None:
    """수신 **전** 정책 게이트 — 위반이면 typed verdict, 통과하면 ``None``.

    edge-sync 라우터가 ``EdgeSyncStore.ingest_event_bundle`` 을 호출하기 전에
    쓴다. 정책 위반 bundle 이 멱등 원장·순번축을 먼저 선점하면 그 항목이 영구
    422 가 되어 그 장비의 store-and-forward 큐 전체가 막히기 때문이다(포화→유실).
    스키마 위반은 여기서 판정하지 않는다 — ``EdgeSyncStore`` 의
    ``INVALID_EVENT_BUNDLE`` 이 그 책임을 이미 갖는다(중복 판정 금지).
    """
    try:
        bundle = EventBundle.model_validate(payload)
    except ValidationError:
        return None  # 스키마 위반은 EdgeSyncStore 소관
    try:
        make_event_key(edge_device_id, bundle.event_id)
    except ValueError:
        return EventVerdict.INVALID_EVENT_IDENTITY
    if bundle.occurred_at.tzinfo is None:
        return EventVerdict.INVALID_EVENT_TIMESTAMP
    if bundle.status not in _EDGE_ASSERTABLE_STATUSES:
        return EventVerdict.STATUS_NOT_EDGE_ASSERTABLE
    return None


def _evidence_gate_violation(bundle: dict[str, Any]) -> str | None:
    """MASTER_PRD §17.1 심각도별 Evidence 정책 위반 사유. 위반 없으면 ``None``."""
    severity_raw = bundle.get("severity")
    if severity_raw not in {s.value for s in _EVIDENCE_GATED_SEVERITIES}:
        return None

    evidence = bundle.get("evidence") or {}
    clips = evidence.get("clips")
    if not clips:
        return (
            f"{severity_raw} 이상 확정은 evidence.clips 가 비어있으면 안 된다"
            "(EVIDENCE_INCOMPLETE)"
        )

    if severity_raw == Severity.CRITICAL.value:
        for field_name in _CRITICAL_ARTIFACT_FIELDS:
            if not evidence.get(field_name):
                return (
                    f"CRITICAL 확정은 evidence.{field_name} 이 필수다(EVIDENCE_INCOMPLETE)"
                )
    return None


class EventStore:
    """journal projection + 트리아지 저장소 (ADR-KSI-008 §1/§3/§4).

    동시성: 프로세스 내 직렬화를 위해 인스턴스 잠금으로 판정+append+메모리
    반영을 한 임계구역으로 묶는다(edge_sync.py 관습 대칭). 프로세스 간에는
    주입된 :class:`DurableJournal` 의 flock 이 단일 writer 를 강제한다.
    """

    def __init__(self, journal: DurableJournal) -> None:
        self._journal = journal
        self._events: dict[str, EventRecord] = {}
        self._lock = threading.Lock()
        try:
            for record in journal.replay():
                self._apply(record)
        except BaseException:
            # __init__ 실패 시 journal 이 flock 을 쥔 채 버려지면 프로세스
            # 수명 내내 잔존한다(2차 독립 재검토 P2, sites.py 대칭 조치).
            journal.close()
            raise

    # ── 재생/실시간 공유 적용 로직 ─────────────────────────────────────────

    def _apply(self, record: dict[str, Any]) -> None:
        kind = record["kind"]
        event_key = record["eventKey"]
        if kind == "event-projected":
            after = record["after"]
            self._events[event_key] = EventRecord(
                event_key=event_key,
                event_id=record["eventId"],
                site_id=record["siteId"],
                mission_id=record["missionId"],
                bundle=after["bundle"],
                status=EventStatus(after["status"]),
                triage=TriageStatus(after["triage"]),
                assignee=after["assignee"],
                edge_device_id=record["edgeDeviceId"],
                occurred_at=datetime.fromisoformat(record["occurredAt"]),
                received_at=datetime.fromisoformat(record["receivedAt"]),
                last_conflict_at=None,
                transitions=(record,),
            )
            return

        existing = self._events[event_key]
        if kind == "event-updated":
            after = record["after"]
            self._events[event_key] = replace(
                existing,
                bundle=after["bundle"],
                status=EventStatus(after["status"]),
                transitions=(*existing.transitions, record),
            )
        elif kind == "event-diverged":
            self._events[event_key] = replace(
                existing,
                last_conflict_at=datetime.fromisoformat(record["ts"]),
                transitions=(*existing.transitions, record),
            )
        elif kind == "event-transitioned":
            after = record["after"]
            self._events[event_key] = replace(
                existing,
                status=EventStatus(after["status"]),
                triage=TriageStatus(after["triage"]),
                assignee=after["assignee"],
                transitions=(*existing.transitions, record),
            )
        else:  # pragma: no cover - 방어적, journal 오염이 아닌 이상 도달 불가
            raise ValueError(f"알 수 없는 journal 레코드 kind: {kind!r}")

    def _append_and_apply(self, record: dict[str, Any]) -> None:
        self._journal.append(record)  # 실패 시 JournalSealedError(journal 자체 봉인)
        self._apply(record)

    # ── projection (edge_sync 장착부 전용 진입점) ────────────────────────

    def project_bundle(
        self, payload: Mapping[str, Any], *, edge_device_id: str, received_at: datetime
    ) -> EventVerdict:
        """EventBundle payload 1건을 projection 한다 — edge-sync ACK 전에 호출된다.

        내부 예외(검증·digest 계산·journal append 어느 단계든)는 무차별로
        journal 을 봉인하고 ``STORE_UNAVAILABLE`` 을 반환한다 — edge_sync.py 의
        "무차별 봉인" 관습과 동일 원칙(디스크에 없는 상태를 성공처럼 보이게
        하지 않는다).
        """
        _require_tz_aware(received_at, param="received_at")
        with self._lock:
            try:
                return self._project_bundle_locked(dict(payload), edge_device_id, received_at)
            except JournalSealedError:
                return EventVerdict.STORE_UNAVAILABLE
            except BaseException:
                logger.error("event projection 중 예외로 봉인", exc_info=True)
                self._journal.close()
                return EventVerdict.STORE_UNAVAILABLE

    def _project_bundle_locked(
        self, payload: dict[str, Any], edge_device_id: str, received_at: datetime
    ) -> EventVerdict:
        bundle = EventBundle.model_validate(payload)

        # ① 신원 게이트 — 장비 스코프 키가 모호해지거나 경로-불안전한 식별자는 typed 거부.
        try:
            event_key = make_event_key(edge_device_id, bundle.event_id)
        except ValueError:
            logger.warning("event_key 신원 위반 거부(eventId 미노출)")
            return EventVerdict.INVALID_EVENT_IDENTITY

        # ①b 시각 게이트 — occurredAt 이 naive 면 astimezone(UTC) 이 서버
        # 로컬 타임존으로 조용히 재해석해 감사 시간축을 어긋나게 만든다
        # (2차 독립 재검토 P2). Edge 가 공급하는 유일한 시각이라 여기서만
        # 검증하면 되고, 서버가 만드는 received_at/now 는 이미
        # _require_tz_aware 로 커버된다.
        if bundle.occurred_at.tzinfo is None:
            logger.warning("naive occurredAt 거부(device=%s)", edge_device_id)
            return EventVerdict.INVALID_EVENT_TIMESTAMP

        # ② 권한 게이트 — 확정/기각은 서버 트리아지 전용(INV-021 게이트 우회 차단).
        if bundle.status not in _EDGE_ASSERTABLE_STATUSES:
            logger.warning(
                "Edge 가 주장할 수 없는 종단 상태 거부: %s (device=%s)",
                bundle.status.value,
                edge_device_id,
            )
            return EventVerdict.STATUS_NOT_EDGE_ASSERTABLE

        digest = payload_digest(payload)
        ts_iso = _iso(received_at)
        existing = self._events.get(event_key)

        if existing is None:
            record = {
                "kind": "event-projected",
                "ts": ts_iso,
                "actor": edge_device_id,
                "eventKey": event_key,
                "eventId": bundle.event_id,
                "siteId": bundle.site_id,
                "missionId": bundle.mission_id,
                "edgeDeviceId": edge_device_id,
                "occurredAt": _iso(bundle.occurred_at),
                "receivedAt": ts_iso,
                "before": None,
                "after": {
                    "status": bundle.status.value,
                    "triage": TriageStatus.NONE.value,
                    "assignee": None,
                    "bundle": payload,
                },
                "reason": None,
                "evidenceSnapshot": None,
            }
            self._append_and_apply(record)
            return EventVerdict.PROJECTED

        existing_digest = payload_digest(existing.bundle)
        if existing_digest == digest:
            return EventVerdict.DUPLICATE_PROJECTION

        finalized = existing.status in _FINALIZED_STATUSES
        legal = (not finalized) and can_event_transition(existing.status, bundle.status)

        if legal:
            record = {
                "kind": "event-updated",
                "ts": ts_iso,
                "actor": edge_device_id,
                "eventKey": event_key,
                "eventId": bundle.event_id,
                "before": {"status": existing.status.value, "bundleDigest": existing_digest},
                "after": {
                    "status": bundle.status.value,
                    "bundle": payload,
                    "bundleDigest": digest,
                },
                "reason": "edge bundle update",
                "evidenceSnapshot": None,
            }
            self._append_and_apply(record)
            return EventVerdict.EVENT_UPDATED

        reason = (
            f"서버 트리아지가 이미 확정/기각한 사건(status={existing.status.value})의 후행 update"
            if finalized
            else f"불법 전이 시도: {existing.status.value} -> {bundle.status.value}"
        )
        record = {
            "kind": "event-diverged",
            "ts": ts_iso,
            "actor": edge_device_id,
            "eventKey": event_key,
            "eventId": bundle.event_id,
            "before": {"status": existing.status.value, "bundleDigest": existing_digest},
            "attempted": {
                "status": bundle.status.value,
                "bundle": payload,
                "bundleDigest": digest,
            },
            "reason": reason,
            "evidenceSnapshot": None,
        }
        self._append_and_apply(record)
        return EventVerdict.UPDATE_DIVERGED

    # ── 트리아지 ────────────────────────────────────────────────────────

    def triage_transition(
        self,
        event_key: str,
        *,
        target: EventStatus | None,
        triage_target: TriageStatus | None,
        reason: str | None,
        assignee: str | None,
        actor: Principal,
        now: datetime,
    ) -> TriageTransitionResult:
        """``event_key``(=``{edgeDeviceId}::{eventId}``) 사건의 서버측 전이."""
        _require_tz_aware(now, param="now")
        with self._lock:
            try:
                return self._triage_transition_locked(
                    event_key,
                    target=target,
                    triage_target=triage_target,
                    reason=reason,
                    assignee=assignee,
                    actor=actor,
                    now=now,
                )
            except JournalSealedError:
                return TriageTransitionResult(
                    EventVerdict.STORE_UNAVAILABLE,
                    detail="journal 봉인됨 — 재시작 필요",
                )
            except (IllegalEventTransitionError, IllegalTriageTransitionError):
                raise
            except BaseException:
                logger.error("트리아지 전이 중 예외로 봉인", exc_info=True)
                self._journal.close()
                return TriageTransitionResult(
                    EventVerdict.STORE_UNAVAILABLE,
                    detail="journal 봉인됨 — 재시작 필요",
                )

    def _triage_transition_locked(
        self,
        event_key: str,
        *,
        target: EventStatus | None,
        triage_target: TriageStatus | None,
        reason: str | None,
        assignee: str | None,
        actor: Principal,
        now: datetime,
    ) -> TriageTransitionResult:
        if (target is None) == (triage_target is None):
            return TriageTransitionResult(
                EventVerdict.INVALID_REQUEST,
                detail="targetStatus 와 triageTarget 중 정확히 하나만 지정해야 한다",
            )

        existing = self._events.get(event_key)
        if existing is None:
            return TriageTransitionResult(EventVerdict.UNKNOWN_EVENT, detail=_NOT_FOUND_DETAIL)

        ts_iso = _iso(now)
        actor_id = actor.principal_id

        if target is not None:
            return self._apply_event_status_transition(
                existing, target=target, reason=reason, actor_id=actor_id, ts_iso=ts_iso
            )

        assert triage_target is not None  # noqa: S101 -- 위 XOR 게이트가 보장
        return self._apply_triage_status_transition(
            existing,
            triage_target=triage_target,
            reason=reason,
            assignee=assignee,
            actor_id=actor_id,
            ts_iso=ts_iso,
        )

    def _apply_event_status_transition(
        self,
        existing: EventRecord,
        *,
        target: EventStatus,
        reason: str | None,
        actor_id: str,
        ts_iso: str,
    ) -> TriageTransitionResult:
        try:
            assert_event_transition(existing.status, target)
        except IllegalEventTransitionError as exc:
            return TriageTransitionResult(EventVerdict.ILLEGAL_TRANSITION, detail=str(exc))

        if target in _REASON_REQUIRED_STATUSES and (reason is None or not reason.strip()):
            return TriageTransitionResult(
                EventVerdict.INVALID_REQUEST, detail=f"{target.value} 전이는 reason 이 필수다"
            )

        evidence_snapshot: dict[str, Any] | None = None
        if target is EventStatus.CONFIRMED_EVENT:
            violation = _evidence_gate_violation(existing.bundle)
            if violation is not None:
                return TriageTransitionResult(EventVerdict.EVIDENCE_INCOMPLETE, detail=violation)
            evidence_snapshot = {"spatialContext": existing.bundle.get("spatialContext", {})}

        record = {
            "kind": "event-transitioned",
            "ts": ts_iso,
            "actor": actor_id,
            "eventKey": existing.event_key,
            "eventId": existing.event_id,
            "before": {
                "status": existing.status.value,
                "triage": existing.triage.value,
                "assignee": existing.assignee,
            },
            "after": {
                "status": target.value,
                "triage": existing.triage.value,
                "assignee": existing.assignee,
            },
            "reason": reason,
            "evidenceSnapshot": evidence_snapshot,
        }
        self._append_and_apply(record)
        updated = self._events[existing.event_key]
        return TriageTransitionResult(EventVerdict.TRANSITIONED, record=updated)

    def _apply_triage_status_transition(
        self,
        existing: EventRecord,
        *,
        triage_target: TriageStatus,
        reason: str | None,
        assignee: str | None,
        actor_id: str,
        ts_iso: str,
    ) -> TriageTransitionResult:
        # ASSIGNED 진입·이후 전이 전부 CONFIRMED_EVENT 사건에만 허용(ADR-KSI-008 §4).
        if existing.status is not EventStatus.CONFIRMED_EVENT:
            return TriageTransitionResult(
                EventVerdict.ILLEGAL_TRANSITION,
                detail="트리아지 전이는 CONFIRMED_EVENT 사건에만 허용된다",
            )

        if triage_target is TriageStatus.ASSIGNED and (assignee is None or not assignee.strip()):
            return TriageTransitionResult(
                EventVerdict.INVALID_REQUEST, detail="ASSIGNED 전이는 assignee 가 필수다"
            )

        try:
            assert_triage_transition(existing.triage, triage_target)
        except IllegalTriageTransitionError as exc:
            return TriageTransitionResult(EventVerdict.ILLEGAL_TRANSITION, detail=str(exc))

        new_assignee = assignee if triage_target is TriageStatus.ASSIGNED else existing.assignee

        record = {
            "kind": "event-transitioned",
            "ts": ts_iso,
            "actor": actor_id,
            "eventKey": existing.event_key,
            "eventId": existing.event_id,
            "before": {
                "status": existing.status.value,
                "triage": existing.triage.value,
                "assignee": existing.assignee,
            },
            "after": {
                "status": existing.status.value,
                "triage": triage_target.value,
                "assignee": new_assignee,
            },
            "reason": reason,
            "evidenceSnapshot": None,
        }
        self._append_and_apply(record)
        updated = self._events[existing.event_key]
        return TriageTransitionResult(EventVerdict.TRANSITIONED, record=updated)

    # ── 조회 ────────────────────────────────────────────────────────────

    def get(self, event_key: str) -> EventRecord | None:
        """``event_key``(=``{edgeDeviceId}::{eventId}``)로 1건 조회."""
        with self._lock:
            return self._events.get(event_key)

    def list(  # noqa: A003 -- 저장소 공개 API 관습(edge_sync.py 대칭 이름)
        self,
        *,
        site_id: str | None = None,
        mission_id: str | None = None,
        edge_device_id: str | None = None,
        status: EventStatus | None = None,
        severity: Severity | None = None,
        triage: TriageStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EventRecord]:
        if not (1 <= limit <= 500):
            raise ValueError("limit 은 1..500 범위여야 한다")
        if offset < 0:
            raise ValueError("offset 은 0 이상이어야 한다")

        with self._lock:
            records = list(self._events.values())

        if site_id is not None:
            records = [r for r in records if r.site_id == site_id]
        if mission_id is not None:
            records = [r for r in records if r.mission_id == mission_id]
        if edge_device_id is not None:
            records = [r for r in records if r.edge_device_id == edge_device_id]
        if status is not None:
            records = [r for r in records if r.status is status]
        if severity is not None:
            records = [r for r in records if r.severity is severity]
        if triage is not None:
            records = [r for r in records if r.triage is triage]

        # occurred_at desc → event_key 오름차순 tie-break: 안정 정렬을 이용해
        # 보조키(event_key 오름차순 — 장비 스코프 정본 신원이라 장비 간 id 충돌에도
        # 결정적)를 먼저 적용한 뒤 주키(occurred_at)를 내림차순으로 덮는다.
        records.sort(key=lambda r: r.event_key)
        records.sort(key=lambda r: r.occurred_at, reverse=True)

        return records[offset : offset + limit]


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class EventSummaryResponse(_CamelModel):
    event_key: str
    event_id: str
    site_id: str
    mission_id: str
    status: str
    severity: str | None
    triage: str
    assignee: str | None
    edge_device_id: str
    occurred_at: datetime
    received_at: datetime


class EventDetailResponse(_CamelModel):
    event_key: str
    event_id: str
    site_id: str
    mission_id: str
    status: str
    severity: str | None
    triage: str
    assignee: str | None
    edge_device_id: str
    occurred_at: datetime
    received_at: datetime
    last_conflict_at: datetime | None
    bundle: dict[str, Any]
    transitions: list[dict[str, Any]]


class EventListResponse(_CamelModel):
    events: list[EventSummaryResponse]
    count: int


class EventTransitionRequest(_CamelModel):
    target_status: EventStatus | None = None
    triage_target: TriageStatus | None = None
    reason: str | None = None
    assignee: str | None = None


class TransitionResponse(_CamelModel):
    verdict: str
    detail: str | None = None
    event: EventDetailResponse | None = None


def _to_summary(record: EventRecord) -> EventSummaryResponse:
    severity = record.severity
    return EventSummaryResponse(
        event_key=record.event_key,
        event_id=record.event_id,
        site_id=record.site_id,
        mission_id=record.mission_id,
        status=record.status.value,
        severity=severity.value if severity is not None else None,
        triage=record.triage.value,
        assignee=record.assignee,
        edge_device_id=record.edge_device_id,
        occurred_at=record.occurred_at,
        received_at=record.received_at,
    )


def _to_detail(record: EventRecord) -> EventDetailResponse:
    severity = record.severity
    return EventDetailResponse(
        event_key=record.event_key,
        event_id=record.event_id,
        site_id=record.site_id,
        mission_id=record.mission_id,
        status=record.status.value,
        severity=severity.value if severity is not None else None,
        triage=record.triage.value,
        assignee=record.assignee,
        edge_device_id=record.edge_device_id,
        occurred_at=record.occurred_at,
        received_at=record.received_at,
        last_conflict_at=record.last_conflict_at,
        bundle=record.bundle,
        transitions=list(record.transitions),
    )


def build_events_router(store: EventStore) -> APIRouter:
    router = APIRouter(prefix="/v1/events", tags=["events"])

    @router.get("", response_model=EventListResponse)
    def list_events(
        site_id: str | None = Query(default=None, alias="siteId"),  # noqa: B008
        mission_id: str | None = Query(default=None, alias="missionId"),  # noqa: B008
        edge_device_id: str | None = Query(default=None, alias="edgeDeviceId"),  # noqa: B008
        status: EventStatus | None = Query(default=None),  # noqa: B008
        severity: Severity | None = Query(default=None),  # noqa: B008
        triage: TriageStatus | None = Query(default=None),  # noqa: B008
        limit: int = Query(default=100, ge=1, le=500),  # noqa: B008
        offset: int = Query(default=0, ge=0),  # noqa: B008
        principal: Principal = Depends(require_permission(Permission.EVENTS_READ)),  # noqa: B008
    ) -> EventListResponse:
        del principal  # 인가만 확인 — 응답 본문에 영향 없음
        records = store.list(
            site_id=site_id,
            mission_id=mission_id,
            edge_device_id=edge_device_id,
            status=status,
            severity=severity,
            triage=triage,
            limit=limit,
            offset=offset,
        )
        return EventListResponse(events=[_to_summary(r) for r in records], count=len(records))

    @router.get("/{event_key}", response_model=EventDetailResponse)
    def get_event(
        event_key: str,
        principal: Principal = Depends(require_permission(Permission.EVENTS_READ)),  # noqa: B008
    ) -> EventDetailResponse:
        """``event_key`` = ``{edgeDeviceId}::{eventId}`` (목록 응답의 ``eventKey``)."""
        del principal
        record = store.get(event_key)
        if record is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        return _to_detail(record)

    @router.post("/{event_key}/transitions", response_model=TransitionResponse)
    def transition_event(
        event_key: str,
        request: EventTransitionRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.EVENTS_TRIAGE)),  # noqa: B008
    ) -> TransitionResponse:
        result = store.triage_transition(
            event_key,
            target=request.target_status,
            triage_target=request.triage_target,
            reason=request.reason,
            assignee=request.assignee,
            actor=principal,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is EventVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return TransitionResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            event=_to_detail(result.record) if result.record is not None else None,
        )

    return router


def mount_events(app: FastAPI, store: EventStore) -> None:
    """앱에 Event 조회·트리아지 라우터를 장착한다."""
    app.state.event_store = store
    app.include_router(build_events_router(store))


__all__ = [
    "EventDetailResponse",
    "EventListResponse",
    "EventRecord",
    "EventStore",
    "EventSummaryResponse",
    "EventTransitionRequest",
    "EventVerdict",
    "TransitionResponse",
    "TriageTransitionResult",
    "build_events_router",
    "classify_edge_bundle",
    "make_event_key",
    "mount_events",
]
