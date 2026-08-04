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
from ksi_core.evidence import (
    ALLOWED_CONTENT_TYPES,
    DEFAULT_UPLOAD_TTL,
    DEFAULT_VIEW_TTL,
    EvidenceArtifact,
    EvidenceStorage,
    EvidenceStorageError,
    EvidenceVerdict,
    build_object_key,
    expires_at,
    is_valid_artifact_id,
)
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
    STALE_EVENT_VIEW = "STALE_EVENT_VIEW"  # 낙관적 동시성 토큰 불일치
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
    EventVerdict.STALE_EVENT_VIEW: 409,
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

# Evidence 판정 → HTTP (ADR-KSI-010 §1). REGISTERED 는 성공 경로라 여기 없다.
_EVIDENCE_STATUS: dict[EvidenceVerdict, int] = {
    EvidenceVerdict.UNKNOWN_EVENT: 404,
    EvidenceVerdict.UNKNOWN_ARTIFACT: 404,
    EvidenceVerdict.INVALID_ARTIFACT_ID: 422,
    EvidenceVerdict.UNSUPPORTED_CONTENT_TYPE: 415,
    EvidenceVerdict.DUPLICATE_ARTIFACT: 409,
    EvidenceVerdict.ALREADY_TOMBSTONED: 410,
    EvidenceVerdict.REGISTERED: 201,
}


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
    # 등록 순서 보존(ADR-KSI-010 §1) — 폐기된 것도 남는다. "증거가 없다"와
    # "정책대로 폐기했다"는 사고 조사에서 다른 사실이다.
    evidence: tuple[EvidenceArtifact, ...] = field(default_factory=tuple)

    @property
    def severity(self) -> Severity | None:
        raw = self.bundle.get("severity")
        return Severity(raw) if raw is not None else None

    @property
    def event_type(self) -> str | None:
        """무슨 일이 일어났는가 — ``EventBundle.event_type`` 원문.

        계약상 필수 필드(:class:`ksi_event_contracts.event_bundle.EventBundle`)라
        정상 projection 된 레코드에는 항상 있다. 그럼에도 ``None`` 을 허용하는 것은
        이 property 가 조회 경로에서만 쓰이기 때문이다 — 저장된 bundle 이 어떤 이유로든
        이 키를 잃었을 때 목록 **전체**가 500 으로 죽는 것보다, 그 한 건이 '분류 없음'
        으로 보이는 편이 운영에서 낫다(트리아지 대기열은 안전 경로다).

        값은 자유 문자열이다. 사람이 읽을 라벨로의 번역은 표시 계층이 맡는다.
        """
        raw = self.bundle.get("eventType")
        return raw if isinstance(raw, str) and raw else None


@dataclass(frozen=True, slots=True)
class TriageTransitionResult:
    verdict: EventVerdict
    detail: str | None = None
    record: EventRecord | None = None


@dataclass(frozen=True, slots=True)
class EvidenceRegistration:
    """Evidence 등록·폐기 판정 (ADR-KSI-010 §1).

    거부 사유는 :class:`EvidenceVerdict` 로 typed 하게 돌려준다 — 라우터가
    문자열 메시지를 파싱해 상태코드를 정하는 경로를 만들지 않는다.
    """

    verdict: EvidenceVerdict
    artifact: EvidenceArtifact | None = None


def _require_tz_aware(value: datetime, *, param: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{param} 은 tz-aware 여야 한다")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class EventStoreRecoveryError(RuntimeError):
    """event journal 재생 실패 — 오염·불법 전이가 기록된 원장으로 기동하지 않는다.

    ``SiteStoreRecoveryError``/``MissionStoreRecoveryError`` 대응물(독립 재검토
    P2-6). 이게 없으면 재생 게이트가 던지는 ``ValueError``·전이 예외가 raw 로
    새어나가 호출자가 "기동 거부"와 "우연한 버그"를 구분할 수 없다.
    """


def _require_aware_iso(raw: Any, field_name: str, event_key: str) -> datetime:
    """journal 의 ISO 시각을 tz-aware datetime 으로 — naive·비문자열은 기동 거부.

    naive 값 하나가 재생되면 그 뒤 목록 조회의 ``sort(key=occurred_at)`` 이
    aware/naive 비교 ``TypeError`` 로 죽어 **조회 표면 전체가 500** 이 된다
    (독립 재검토 P2-6). 죽는 자리를 기동 시점으로 당긴다.
    """
    if not isinstance(raw, str):
        raise EventStoreRecoveryError(
            f"재생: {field_name} 가 문자열이 아니다({type(raw).__name__}) — eventKey={event_key}"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise EventStoreRecoveryError(
            f"재생: {field_name} 가 ISO 시각이 아니다({raw!r}) — eventKey={event_key}"
        ) from exc
    if parsed.tzinfo is None:
        raise EventStoreRecoveryError(
            f"재생: {field_name} 가 naive datetime — eventKey={event_key}"
        )
    return parsed


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
        except EventStoreRecoveryError:
            journal.close()
            raise
        except (KeyError, ValueError, TypeError, IllegalEventTransitionError,
                IllegalTriageTransitionError) as exc:
            # 재생 실패는 전부 typed 로 묶는다(독립 재검토 P2-6) — sites.py 의
            # SiteStoreRecoveryError·mission_records.py 의 MissionStoreRecoveryError
            # 와 대칭. raw 예외가 새면 호출자가 "기동 거부"와 "우연한 버그"를
            # 구분할 수 없다.
            journal.close()
            raise EventStoreRecoveryError(
                f"event journal 재생 실패 — 오염되거나 불법 전이가 기록됨: {exc}"
            ) from exc
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
            projected_status = EventStatus(after["status"])
            # 재생 경로도 live 의 ② 권한 게이트를 태운다(독립 재검토 P1-1) —
            # 확정/기각은 Edge 가 주장할 수 없고(INV-021 우회 차단), 그 규칙이
            # projection 레코드에만 빠져 있으면 "journal 한 줄로 확정 사건 만들기"가
            # 그대로 성립한다. transitioned 만 막았던 것이 비대칭이었다.
            if projected_status not in _EDGE_ASSERTABLE_STATUSES:
                raise EventStoreRecoveryError(
                    f"재생: Edge 가 주장할 수 없는 상태로 projection 됨 "
                    f"({projected_status.value}) — eventKey={event_key}"
                )
            projected_triage = TriageStatus(after["triage"])
            if projected_triage is not TriageStatus.NONE or after["assignee"] is not None:
                # live projection 은 항상 NONE/None 이다 — 다른 값이 기록돼 있으면
                # "트리아지 전이는 CONFIRMED_EVENT 사건에만" 규칙을 projection 한
                # 줄로 우회한 것이다(2차 재검토 P1-4 부차).
                raise EventStoreRecoveryError(
                    f"재생: projection 이 트리아지 상태를 주장한다 "
                    f"({projected_triage.value}/{after['assignee']!r}) — eventKey={event_key}"
                )
            occurred_at = _require_aware_iso(record["occurredAt"], "occurredAt", event_key)
            self._events[event_key] = EventRecord(
                event_key=event_key,
                event_id=record["eventId"],
                site_id=record["siteId"],
                mission_id=record["missionId"],
                bundle=after["bundle"],
                status=projected_status,
                triage=projected_triage,
                assignee=after["assignee"],
                edge_device_id=record["edgeDeviceId"],
                occurred_at=occurred_at,
                received_at=_require_aware_iso(record["receivedAt"], "receivedAt", event_key),
                last_conflict_at=None,
                transitions=(record,),
            )
            return

        existing = self._events[event_key]
        if kind == "event-updated":
            after = record["after"]
            updated_status = EventStatus(after["status"])
            # 재생에서도 live 와 같은 전이 규칙을 태운다(독립 재검토 P1-1). live
            # (_project_bundle_locked)는 종단 상태의 후행 update 를 diverge 로
            # 격리하고 불법 전이를 거부하는데, 재생만 무검사면 그 두 규칙이
            # journal 한 줄로 우회된다 — evidence 없는 CONFIRMED_EVENT 가
            # update 레코드로 되살아나는 경로가 정확히 이것이다.
            if existing.status in _FINALIZED_STATUSES:
                raise EventStoreRecoveryError(
                    f"재생: 확정/기각된 사건({existing.status.value})에 update 레코드가 "
                    f"적용될 수 없다 — eventKey={event_key}"
                )
            if updated_status not in _EDGE_ASSERTABLE_STATUSES:
                # live 가 가장 먼저 강제하는 게이트인데(STATUS_NOT_EDGE_ASSERTABLE)
                # 재생의 update 분기에만 빠져 있었다(2차 독립 재검토 P1-4, 실측
                # 재현됨). FINDING projection + CONFIRMED_EVENT update 두 줄이면
                # 전이표는 통과하므로, 이 검사가 없으면 evidence 게이트도 reason
                # 요구도 없이 확정 사건이 만들어진다 — INV-021 우회 그 자체다.
                raise EventStoreRecoveryError(
                    f"재생: Edge 가 주장할 수 없는 상태로 update 됨 "
                    f"({updated_status.value}) — eventKey={event_key}"
                )
            if updated_status is not existing.status and not can_event_transition(
                existing.status, updated_status
            ):
                raise EventStoreRecoveryError(
                    f"재생: 불법 update 전이 {existing.status.value} -> "
                    f"{updated_status.value} — eventKey={event_key}"
                )
            # 레코드 메타를 새 bundle 에 맞춘다(s2-residual-hardening #6). 예전에는
            # bundle 만 갈아끼워서, Edge 가 siteId·missionId 를 고쳐 보낸 뒤 목록
            # (레코드 메타 기준)과 상세(bundle 기준)가 서로 다른 현장을 보이는 상태가
            # 남았다. 값은 **기록 시점에 파싱된 모델**에서 나온 레코드 필드를 쓴다 —
            # raw bundle dict 를 다시 읽으면 projection(파싱된 모델)과 update(raw)가
            # 서로 다른 진실을 보게 된다(독립 재검토 P2-2).
            #
            # ``occurredAt`` 은 **동기화하지 않는다.** 후행 update 한 번으로 그 값이
            # 움직이면 감사 시간축이 Edge 재량이 된다(독립 재검토 P1-3).
            #
            # 주의 — 이 값 자체는 여전히 **Edge 가 준 시각**이다(최초 projection 의
            # bundle.occurredAt). 그래서 보관 정책의 만료 기준은 이 값이 아니라
            # 서버 수신 시각을 쓴다(``retention.py`` 참조, 2차 독립 재검토 P1-5).
            self._events[event_key] = replace(
                existing,
                bundle=after["bundle"],
                site_id=record.get("siteId", existing.site_id),
                mission_id=record.get("missionId", existing.mission_id),
                status=updated_status,
                transitions=(*existing.transitions, record),
            )
        elif kind == "event-diverged":
            self._events[event_key] = replace(
                existing,
                last_conflict_at=_require_aware_iso(record["ts"], "ts", event_key),
                transitions=(*existing.transitions, record),
            )
        elif kind == "event-transitioned":
            after = record["after"]
            target_status = EventStatus(after["status"])
            target_triage = TriageStatus(after["triage"])
            # 재생 경로에서도 전이 적법성과 INV-021 확정 게이트를 다시 태운다
            # (s2-residual-hardening #1 — sites.py 는 이미 이렇게 하는데 여기만
            # 비대칭이었다). journal 직접 조작이나 과거 버그로 불법 전이가 기록돼
            # 있으면 조용히 되살아나는 대신 기동이 거부돼야 한다 — 특히 evidence
            # 없는 CONFIRMED_EVENT 는 재생만으로 확정 사건이 되어 INV-021 을
            # 우회한다.
            if target_status is not existing.status:
                assert_event_transition(existing.status, target_status)
                if target_status is EventStatus.CONFIRMED_EVENT:
                    violation = _evidence_gate_violation(existing.bundle)
                    if violation is not None:
                        raise ValueError(f"재생: INV-021 확정 게이트 위반 — {violation}")
            if target_triage is not existing.triage:
                if existing.status is not EventStatus.CONFIRMED_EVENT:
                    raise ValueError(
                        "재생: 트리아지 전이는 CONFIRMED_EVENT 사건에만 허용된다 "
                        f"(status={existing.status.value})"
                    )
                assert_triage_transition(existing.triage, target_triage)
            self._events[event_key] = replace(
                existing,
                status=target_status,
                triage=target_triage,
                assignee=after["assignee"],
                transitions=(*existing.transitions, record),
            )
        elif kind == "evidence-registered":
            artifact = EvidenceArtifact(
                artifact_id=record["artifactId"],
                event_key=event_key,
                site_id=record["siteId"],
                object_key=record["objectKey"],
                content_type=record["contentType"],
                registered_at=_require_aware_iso(record["ts"], "ts", event_key),
                registered_by=record["registeredBy"],
            )
            self._events[event_key] = replace(
                existing,
                evidence=(*existing.evidence, artifact),
                transitions=(*existing.transitions, record),
            )
        elif kind == "evidence-tombstoned":
            # 레코드를 지우지 않고 폐기 사실을 덧씌운다(ADR-KSI-010 §3) —
            # 원장에서 과거를 고쳐 쓰면 감사 추적이 감사 대상이 된다.
            artifact_id = record["artifactId"]
            tombstoned_at = _require_aware_iso(record["ts"], "ts", event_key)
            self._events[event_key] = replace(
                existing,
                evidence=tuple(
                    replace(
                        artifact,
                        tombstoned_at=tombstoned_at,
                        tombstone_reason=record["reason"],
                    )
                    if artifact.artifact_id == artifact_id
                    else artifact
                    for artifact in existing.evidence
                ),
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
                # projection 과 **같은 출처**(파싱된 모델)에서 메타를 싣는다 —
                # 재생이 raw bundle dict 를 다시 읽으면 두 경로가 서로 다른 진실을
                # 본다(populate_by_name 때문에 snake_case payload 도 통과한다,
                # 독립 재검토 P2-2). occurredAt 은 싣지 않는다(P1-3 — 보관 정책
                # 만료 기준이라 Edge 입력으로 움직이면 안 된다).
                "siteId": bundle.site_id,
                "missionId": bundle.mission_id,
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
        expected_bundle_digest: str | None = None,
    ) -> TriageTransitionResult:
        """``event_key``(=``{edgeDeviceId}::{eventId}``) 사건의 서버측 전이."""
        _require_tz_aware(now, param="now")
        with self._lock:
            try:
                return self._triage_transition_locked(
                    event_key,
                    target=target,
                    triage_target=triage_target,
                    expected_bundle_digest=expected_bundle_digest,
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
        expected_bundle_digest: str | None = None,
    ) -> TriageTransitionResult:
        if (target is None) == (triage_target is None):
            return TriageTransitionResult(
                EventVerdict.INVALID_REQUEST,
                detail="targetStatus 와 triageTarget 중 정확히 하나만 지정해야 한다",
            )

        existing = self._events.get(event_key)
        if existing is None:
            return TriageTransitionResult(EventVerdict.UNKNOWN_EVENT, detail=_NOT_FOUND_DETAIL)

        # 낙관적 동시성 — 운영자가 본 bundle 이 그 사이 바뀌었으면 전이하지 않는다
        # (s2-residual-hardening #7). 판정은 잠금 안에서 하므로, 통과 후 굳는
        # evidenceSnapshot 은 검사한 그 bundle 의 것이다.
        if expected_bundle_digest is not None:
            actual_digest = payload_digest(existing.bundle)
            if actual_digest != expected_bundle_digest:
                return TriageTransitionResult(
                    EventVerdict.STALE_EVENT_VIEW,
                    detail=(
                        "화면에 표시된 이후 사건 내용이 갱신됐다 — 새로고침 후 다시 "
                        "시도하라(전이는 적용되지 않았다)"
                    ),
                )

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

    # ── Evidence (ADR-KSI-010 §1) ───────────────────────────────────────

    def register_evidence(
        self,
        *,
        event_key: str,
        artifact_id: str,
        content_type: str,
        registered_by: str,
        now: datetime,
    ) -> EvidenceRegistration:
        """증거물 1건을 원장에 등록하고 그 객체 키를 돌려준다.

        **URL 발급은 하지 않는다** — 이 저장소는 스토리지를 모른다. 라우터가
        객체 키를 받아 :class:`EvidenceStorage` 에 presigned 발급을 요청한다.
        원장 기록과 URL 발급을 한 함수에 묶으면, 스토리지 장애가 원장 기록까지
        롤백해야 하는지가 모호해진다(여기서는 명확하다 — 원장이 먼저다).
        """
        _require_tz_aware(now, param="now")
        if not is_valid_artifact_id(artifact_id):
            return EvidenceRegistration(EvidenceVerdict.INVALID_ARTIFACT_ID)
        if content_type not in ALLOWED_CONTENT_TYPES:
            # 임의 MIME 을 통과시키면 열람 URL 에서 브라우저가 스크립트로 해석할
            # 수 있는 타입(text/html·image/svg+xml)까지 들어온다.
            return EvidenceRegistration(EvidenceVerdict.UNSUPPORTED_CONTENT_TYPE)

        with self._lock:
            existing = self._events.get(event_key)
            if existing is None:
                return EvidenceRegistration(EvidenceVerdict.UNKNOWN_EVENT)
            if any(a.artifact_id == artifact_id for a in existing.evidence):
                # 같은 id 로 다시 등록하면 앞선 증거의 객체 키를 가리키게 되어
                # 조용한 덮어쓰기가 된다 — 폐기된 것이어도 재사용을 막는다.
                return EvidenceRegistration(EvidenceVerdict.DUPLICATE_ARTIFACT)
            try:
                object_key = build_object_key(
                    site_id=existing.site_id,
                    event_key=event_key,
                    artifact_id=artifact_id,
                )
            except ValueError:
                return EvidenceRegistration(EvidenceVerdict.INVALID_ARTIFACT_ID)

            record = {
                "kind": "evidence-registered",
                "ts": _iso(now),
                "eventKey": event_key,
                "siteId": existing.site_id,
                "artifactId": artifact_id,
                "objectKey": object_key,
                "contentType": content_type,
                "registeredBy": registered_by,
            }
            self._append_and_apply(record)
            artifact = self._events[event_key].evidence[-1]
        return EvidenceRegistration(EvidenceVerdict.REGISTERED, artifact=artifact)

    def tombstone_evidence(
        self, *, event_key: str, artifact_id: str, reason: str, now: datetime
    ) -> EvidenceRegistration:
        """보관 기간이 지난 증거를 폐기 표시한다(ADR-KSI-010 §3).

        **객체 삭제는 호출자의 몫이다.** 원장 기록이 먼저고, 실제 스토리지
        삭제가 실패해도 "폐기하기로 했다"는 사실은 남아야 한다 — 반대로 하면
        객체는 사라졌는데 원장은 아무 말도 못 하는 상태가 생긴다.
        """
        _require_tz_aware(now, param="now")
        if not reason.strip():
            # 이유 없는 폐기는 기록의 값어치를 없앤다(전이 reason 관습 대칭).
            return EvidenceRegistration(EvidenceVerdict.UNKNOWN_ARTIFACT)
        with self._lock:
            existing = self._events.get(event_key)
            if existing is None:
                return EvidenceRegistration(EvidenceVerdict.UNKNOWN_EVENT)
            target = next(
                (a for a in existing.evidence if a.artifact_id == artifact_id), None
            )
            if target is None:
                return EvidenceRegistration(EvidenceVerdict.UNKNOWN_ARTIFACT)
            if target.is_tombstoned:
                return EvidenceRegistration(EvidenceVerdict.ALREADY_TOMBSTONED, artifact=target)

            record = {
                "kind": "evidence-tombstoned",
                "ts": _iso(now),
                "eventKey": event_key,
                "artifactId": artifact_id,
                "objectKey": target.object_key,
                "reason": reason,
            }
            self._append_and_apply(record)
            updated = next(
                a for a in self._events[event_key].evidence if a.artifact_id == artifact_id
            )
        return EvidenceRegistration(EvidenceVerdict.REGISTERED, artifact=updated)

    def get_evidence(self, event_key: str, artifact_id: str) -> EvidenceArtifact | None:
        with self._lock:
            record = self._events.get(event_key)
            if record is None:
                return None
            return next((a for a in record.evidence if a.artifact_id == artifact_id), None)

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
    # 대기열 목록의 1순위 정보 — 이게 없으면 운영자가 목록에서 '무슨 일인지'를 알 수 없고
    # 매 건마다 상세를 열어야 한다. bundle 전체를 목록에 실을 수는 없으므로 이 한 필드만
    # 승격한다(2026-08-04 대표자 결정).
    event_type: str | None
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
    # bundle 안에도 있지만 최상위로 승격한다 — 목록과 상세가 같은 필드명으로 읽히게 해서
    # 표시 계층이 두 응답을 분기 없이 다루게 한다.
    event_type: str | None
    status: str
    severity: str | None
    triage: str
    assignee: str | None
    edge_device_id: str
    occurred_at: datetime
    received_at: datetime
    last_conflict_at: datetime | None
    bundle: dict[str, Any]
    # 낙관적 동시성 토큰의 **현재 값**(독립 재검토 P2-3) — 이게 없으면 클라이언트가
    # 전이 요청의 expectedBundleDigest 를 얻을 방법이 없어 그 기능을 쓸 수 없다.
    # 정규화 규약(payload_digest)을 클라이언트가 재구현하게 두면 JSON 표기 차이
    # 하나로 영구 409 가 되므로, 서버가 계산해 그대로 돌려준다.
    bundle_digest: str
    transitions: list[dict[str, Any]]
    # 폐기된 것도 포함한다 — "증거가 없다"와 "정책대로 폐기했다"는 다른 사실이라
    # 목록에서 사라지면 안 된다(ADR-KSI-010 §3). 열람 URL 은 여기 없다:
    # 발급은 권한 검사를 통과한 별도 요청에서만 한다(URL 이 곧 인가다).
    evidence: list[EvidenceSummary]


class EventListResponse(_CamelModel):
    events: list[EventSummaryResponse]
    count: int


class EventTransitionRequest(_CamelModel):
    """트리아지 전이 요청.

    ``expected_bundle_digest``: 낙관적 동시성 토큰(s2-residual-hardening #7).
    운영자가 화면에서 본 bundle 의 digest 를 그대로 실어 보내면, 그 사이 Edge 의
    후행 update 가 bundle 을 바꿨을 때 전이가 409 로 거부된다. 없으면 검사하지
    않는다 — 기존 클라이언트를 깨지 않기 위해 optional 이다.

    이 토큰이 필요한 이유는 확정(CONFIRMED_EVENT) 전이가 **그 시점의 bundle** 로
    INV-021 증거 게이트를 통과시키고 ``evidenceSnapshot`` 을 굳히기 때문이다 —
    좁은 경합창에서 운영자가 본 증거와 실제로 굳는 증거가 다를 수 있다.
    """

    target_status: EventStatus | None = None
    triage_target: TriageStatus | None = None
    reason: str | None = None
    assignee: str | None = None
    expected_bundle_digest: str | None = None


class TransitionResponse(_CamelModel):
    verdict: str
    detail: str | None = None
    event: EventDetailResponse | None = None


class EvidenceSummary(_CamelModel):
    """상세 응답에 실리는 증거 1건. 열람 URL 은 담지 않는다(별도 발급 경로)."""

    artifact_id: str
    content_type: str
    registered_at: datetime
    registered_by: str
    tombstoned_at: datetime | None
    tombstone_reason: str | None


class EvidenceUploadRequest(_CamelModel):
    """증거 업로드 등록 요청 (ADR-KSI-010 §1).

    ``artifactId`` 는 호출자가 정한다 — 같은 증거를 재전송할 때 중복 등록을
    피하려면 멱등 키가 필요하고, 그 키를 아는 것은 올리는 쪽뿐이다. 대신
    **객체 키는 서버가 만든다**(이 값이 경로에 그대로 들어가지 않는다).
    """

    artifact_id: str
    content_type: str


class EvidenceUploadResponse(_CamelModel):
    artifact_id: str
    object_key: str
    upload_url: str
    expires_at: datetime


class EvidenceViewResponse(_CamelModel):
    artifact_id: str
    content_type: str
    view_url: str
    expires_at: datetime
    registered_at: datetime
    registered_by: str


def _to_summary(record: EventRecord) -> EventSummaryResponse:
    severity = record.severity
    return EventSummaryResponse(
        event_key=record.event_key,
        event_id=record.event_id,
        site_id=record.site_id,
        mission_id=record.mission_id,
        event_type=record.event_type,
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
        event_type=record.event_type,
        status=record.status.value,
        severity=severity.value if severity is not None else None,
        triage=record.triage.value,
        assignee=record.assignee,
        edge_device_id=record.edge_device_id,
        occurred_at=record.occurred_at,
        received_at=record.received_at,
        last_conflict_at=record.last_conflict_at,
        bundle=record.bundle,
        bundle_digest=payload_digest(record.bundle),
        transitions=list(record.transitions),
        evidence=[
            EvidenceSummary(
                artifact_id=a.artifact_id,
                content_type=a.content_type,
                registered_at=a.registered_at,
                registered_by=a.registered_by,
                tombstoned_at=a.tombstoned_at,
                tombstone_reason=a.tombstone_reason,
            )
            for a in record.evidence
        ],
    )


def build_events_router(
    store: EventStore, *, evidence_storage: EvidenceStorage | None = None
) -> APIRouter:
    """Event 조회·트리아지 라우터. ``evidence_storage`` 가 없으면 증거 경로를 **장착하지 않는다**.

    미장착이면 404 다 — 스토리지 없이 라우트만 살려두면 "업로드했는데 어디에도
    없다"가 성공(2xx)으로 보이는 경로가 생긴다. 조립되지 않은 기능은 존재하지
    않는 편이 정직하다(create_app 의 fail-closed 조립 관습, ADR-KSI-008 §5).
    """
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
            expected_bundle_digest=request.expected_bundle_digest,
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is EventVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return TransitionResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            event=_to_detail(result.record) if result.record is not None else None,
        )

    if evidence_storage is not None:
        _mount_evidence_routes(router, store, evidence_storage)

    return router


def _mount_evidence_routes(
    router: APIRouter, store: EventStore, storage: EvidenceStorage
) -> None:
    """증거 업로드·열람 경로 (ADR-KSI-010 §1).

    Core 는 바이트를 중계하지 않는다 — 원장에 등록한 뒤 presigned URL 만 준다.
    **원장 기록이 먼저다**: 스토리지가 URL 을 못 내주면 5xx 로 실패하되, 이미
    기록된 등록 사실은 남는다(업로드되지 않은 artifact 로 조회된다). 반대로
    했다면 URL 은 나갔는데 원장은 모르는 객체가 생긴다.
    """

    # status_code 로 선언한다 — response.status_code 동적 지정만 하면 OpenAPI 에
    # 200 으로 남아 계약이 실제와 다른 코드를 말한다(sites.py 의 같은 주석 참조).
    @router.post(
        "/{event_key}/evidence", response_model=EvidenceUploadResponse, status_code=201
    )
    def register_evidence(
        event_key: str,
        request: EvidenceUploadRequest,
        principal: Principal = Depends(require_permission(Permission.EVENTS_TRIAGE)),  # noqa: B008
    ) -> EvidenceUploadResponse:
        now = datetime.now(UTC)
        result = store.register_evidence(
            event_key=event_key,
            artifact_id=request.artifact_id,
            content_type=request.content_type,
            registered_by=principal.principal_id,
            now=now,
        )
        if result.verdict is not EvidenceVerdict.REGISTERED or result.artifact is None:
            raise HTTPException(
                status_code=_EVIDENCE_STATUS[result.verdict], detail=result.verdict.value
            )
        try:
            url = storage.presigned_put(
                result.artifact.object_key,
                content_type=request.content_type,
                ttl=DEFAULT_UPLOAD_TTL,
            )
        except EvidenceStorageError as exc:
            # 스토리지 장애를 '증거 없음'으로 뭉개지 않는다 — 등록은 원장에
            # 남았고 업로드만 못 한 상태이므로, 재시도는 URL 재발급으로 한다.
            raise HTTPException(status_code=503, detail="EVIDENCE_STORAGE_UNAVAILABLE") from exc
        return EvidenceUploadResponse(
            artifact_id=result.artifact.artifact_id,
            object_key=result.artifact.object_key,
            upload_url=url,
            expires_at=expires_at(now, DEFAULT_UPLOAD_TTL),
        )

    @router.get("/{event_key}/evidence/{artifact_id}", response_model=EvidenceViewResponse)
    def view_evidence(
        event_key: str,
        artifact_id: str,
        principal: Principal = Depends(require_permission(Permission.EVENTS_READ)),  # noqa: B008
    ) -> EvidenceViewResponse:
        del principal
        artifact = store.get_evidence(event_key, artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        if artifact.is_tombstoned:
            # "없음"이 아니라 "폐기됨"이다 — 410 Gone 이 정확히 그 뜻이고,
            # 사고 조사에서 이 둘을 구분하지 못하면 원장의 값어치가 없다.
            raise HTTPException(status_code=410, detail=EvidenceVerdict.ALREADY_TOMBSTONED.value)
        now = datetime.now(UTC)
        try:
            url = storage.presigned_get(artifact.object_key, ttl=DEFAULT_VIEW_TTL)
        except EvidenceStorageError as exc:
            raise HTTPException(status_code=503, detail="EVIDENCE_STORAGE_UNAVAILABLE") from exc
        return EvidenceViewResponse(
            artifact_id=artifact.artifact_id,
            content_type=artifact.content_type,
            view_url=url,
            expires_at=expires_at(now, DEFAULT_VIEW_TTL),
            registered_at=artifact.registered_at,
            registered_by=artifact.registered_by,
        )


def mount_events(
    app: FastAPI, store: EventStore, *, evidence_storage: EvidenceStorage | None = None
) -> None:
    """앱에 Event 조회·트리아지(+ 스토리지가 있으면 증거) 라우터를 장착한다."""
    app.state.event_store = store
    app.state.evidence_storage = evidence_storage
    app.include_router(build_events_router(store, evidence_storage=evidence_storage))


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
