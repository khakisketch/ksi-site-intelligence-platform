"""KSI 공통 도메인 Enum·상태전이 SSOT.

코드 식별자는 영어, 주석·docstring은 한국어(KSI 관습). ``StrEnum`` — 멤버가 곧
문자열이라 JSON 직렬화·계약 스키마 값과 그대로 일치한다(ksi-terra
``contracts/enums.py`` 관습 계승).

상태전이는 :func:`assert_event_transition` 을 통해서만 수행한다 —
``_ALLOWED_EVENT_TRANSITIONS`` 전이표가 유일한 진실원천이다
(ksi-terra ``contracts/job.py`` ``assert_transition`` 패턴 계승).
"""

from __future__ import annotations

from enum import StrEnum


class MissionType(StrEnum):
    """임무 종류 (mission-contract.v1.1/v1.2 ``missionType`` enum SSOT 정합)."""

    UNIFIED_SITE_SURVEY = "UNIFIED_SITE_SURVEY"
    BASELINE_MAPPING = "BASELINE_MAPPING"
    SPATIAL_REFRESH = "SPATIAL_REFRESH"
    AUTONOMOUS_PATROL = "AUTONOMOUS_PATROL"
    ASSET_INSPECTION = "ASSET_INSPECTION"
    PROGRESS_CAPTURE = "PROGRESS_CAPTURE"
    INCIDENT_SURVEY = "INCIDENT_SURVEY"
    SURVEY_GRADE_MAPPING = "SURVEY_GRADE_MAPPING"


class Severity(StrEnum):
    """이벤트 심각도 (MASTER_PRD §17.2 심각도 정책 + evidencePolicy 3단계 정합).

    ``CANDIDATE``는 아직 확정되지 않은 관찰(mission-contract ``evidencePolicy.
    candidatePrePostSeconds``에 대응)이며, ``MEDIUM``/``HIGH``/``CRITICAL``은
    §17.2의 확정 심각도 등급이다.
    """

    CANDIDATE = "CANDIDATE"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EventStatus(StrEnum):
    """이벤트 상태 (event-bundle.v1.2 ``status`` enum SSOT 정합, MASTER_PRD §12.8/§17.2).

    Detector 결과(DETECTION)는 이 Enum의 멤버가 아니다 — INV-031: Detector 결과를
    Event로 직접 저장하지 않는다(Detection → Observation → Candidate → … 경유).
    ``assert_event_transition``의 ``cur=None``이 "아직 Event 레코드가 없는 Detection
    단계"를 표현하며, 그 경우 허용되는 유일한 다음 상태는 ``OBSERVATION``이다.
    """

    OBSERVATION = "OBSERVATION"
    CANDIDATE = "CANDIDATE"
    EVIDENCE_COLLECTION = "EVIDENCE_COLLECTION"
    FINDING = "FINDING"
    CONFIRMED_EVENT = "CONFIRMED_EVENT"
    DISMISSED = "DISMISSED"
    UNRESOLVED = "UNRESOLVED"


class IllegalEventTransitionError(ValueError):
    """허용되지 않은 EventStatus 전이 시도 시 발생."""


_S = EventStatus

# 허용 전이표(SSOT, INV-031). 키=현재 상태(None=Detection 단계, 아직 Event 없음),
# 값=허용되는 다음 상태 집합. DISMISSED/CONFIRMED_EVENT는 이 스키마 범위(v1.1)에서
# 종단 상태다. UNRESOLVED는 재관찰을 위해 CANDIDATE로만 복귀할 수 있다(INV-022 —
# 단일 프레임으로 사건을 확정하지 않으므로 재수집 경로가 필요).
_ALLOWED_EVENT_TRANSITIONS: dict[EventStatus | None, set[EventStatus]] = {
    None: {_S.OBSERVATION},
    _S.OBSERVATION: {_S.CANDIDATE, _S.DISMISSED},
    _S.CANDIDATE: {_S.EVIDENCE_COLLECTION, _S.DISMISSED},
    _S.EVIDENCE_COLLECTION: {_S.FINDING, _S.DISMISSED, _S.UNRESOLVED},
    _S.FINDING: {_S.CONFIRMED_EVENT, _S.DISMISSED, _S.UNRESOLVED},
    _S.CONFIRMED_EVENT: set(),
    _S.DISMISSED: set(),
    _S.UNRESOLVED: {_S.CANDIDATE},
}


def assert_event_transition(cur: EventStatus | None, nxt: EventStatus) -> None:
    """``cur → nxt`` EventStatus 전이가 허용되는지 검증한다 (INV-031 강제 지점).

    Args:
        cur: 현재 상태. ``None``이면 아직 Event 레코드가 없는 Detection 단계.
        nxt: 목표 상태.

    Raises:
        IllegalEventTransitionError: 전이표에 없는 불법 전이일 때(예: Detector 결과의
            CONFIRMED_EVENT 직행, OBSERVATION→CONFIRMED_EVENT 직행, DISMISSED→CANDIDATE).
    """
    allowed = _ALLOWED_EVENT_TRANSITIONS.get(cur, set())
    if nxt not in allowed:
        cur_repr = cur.value if cur is not None else "(none/detection)"
        allowed_repr = ", ".join(sorted(s.value for s in allowed)) or "없음"
        raise IllegalEventTransitionError(
            f"허용되지 않은 이벤트 상태 전이: {cur_repr} → {nxt.value} (허용: {allowed_repr})"
        )


def can_event_transition(cur: EventStatus | None, nxt: EventStatus) -> bool:
    """``cur → nxt`` 전이 허용 여부를 예외 없이 bool로 반환한다."""
    return nxt in _ALLOWED_EVENT_TRANSITIONS.get(cur, set())
