"""KSI 공통 도메인 Enum·상태전이 SSOT.

코드 식별자는 영어, 주석·docstring은 한국어(KSI 관습). ``StrEnum`` — 멤버가 곧
문자열이라 JSON 직렬화·계약 스키마 값과 그대로 일치한다(ksi-terra
``contracts/enums.py`` 관습 계승).

상태전이는 :func:`assert_event_transition`/:func:`assert_site_transition`/
:func:`assert_triage_transition` 을 통해서만 수행한다 — 각 ``_ALLOWED_*_TRANSITIONS``
전이표가 유일한 진실원천이다(ksi-terra ``contracts/job.py`` ``assert_transition``
패턴 계승). ``EventStatus``는 event-bundle.v1.2 스키마 enum과 1:1 잠금이라 확장하지
않는다 — 서버측 배정 이후 워크플로는 별도 ``TriageStatus``로 분리한다(ADR-KSI-008 §4).
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


class SiteStatus(StrEnum):
    """현장 상태 (MASTER_PRD §6.3 현장 상태, 10종 전체, ADR-KSI-008 §4).

    ``EventStatus``와 대칭 배치. 최초 등록된 현장은 ``UNMAPPED``에서 시작하며
    (§6.1), Detection 단계의 ``None``에 대응하는 sentinel은 두지 않는다 — 현장은
    항상 실제 상태를 가진 레코드로 존재한다.
    """

    UNMAPPED = "UNMAPPED"
    BASELINE_MAPPING = "BASELINE_MAPPING"
    MODEL_PROCESSING = "MODEL_PROCESSING"
    MODEL_VALIDATION = "MODEL_VALIDATION"
    PROVISIONAL_AUTONOMY = "PROVISIONAL_AUTONOMY"
    PATROL_READY = "PATROL_READY"
    PATROL_ACTIVE = "PATROL_ACTIVE"
    MODEL_STALE = "MODEL_STALE"
    REMAP_REQUIRED = "REMAP_REQUIRED"
    SUSPENDED = "SUSPENDED"


class IllegalSiteTransitionError(ValueError):
    """허용되지 않은 SiteStatus 전이 시도 시 발생."""


_ST = SiteStatus

# 허용 전이표(SSOT, MASTER_PRD §6.3/§6.1). PATROL_READY 도달은 반드시
# MODEL_VALIDATION -> PROVISIONAL_AUTONOMY 를 경유해야 한다(§6.1 "7. 품질 검증을
# 통과하면 현장은 PATROL_READY가 된다" — 품질 검증 단계 생략 금지). 따라서
# PATROL_READY 로 들어오는 정적 간선은 PROVISIONAL_AUTONOMY·PATROL_ACTIVE 두
# 곳뿐이며, UNMAPPED 등에서 직행하는 간선은 존재하지 않는다.
#
# MODEL_STALE -> PATROL_READY 직행 간선은 두지 않는다(§6.1 품질검증 우회 금지,
# 재검토 지적 반영). MODEL_STALE 은 "한 번 검증됐으나 모델이 낡은" 상태라
# 재검증 없이 PATROL_READY 로 돌아가면 §6.1 의 품질 검증 의도가 새는 경로가
# 된다. 따라서 MODEL_STALE 은 재처리(MODEL_PROCESSING)·재매핑(REMAP_REQUIRED)·
# 운영중단(SUSPENDED)으로만 이탈하며, PATROL_READY 복귀는 반드시
# MODEL_PROCESSING -> MODEL_VALIDATION -> PROVISIONAL_AUTONOMY 재검증 경로를
# 다시 거친다. PATROL_ACTIVE -> PATROL_READY(정상 복귀, 검증 재수행 아님)는
# 별개 간선으로 유지한다.
#
# SUSPENDED 는 모든 상태에서 진입 가능하지만(운영 중단은 어느 단계에서나
# 발생할 수 있다) 이 표에는 SUSPENDED 로부터의 정적 간선을 두지 않는다 —
# SUSPENDED 복귀는 저장소가 기억한 "직전 상태"로만 허용되는 동적 규칙이라
# assert_site_transition 이 이 표를 거치지 않고 별도로 처리한다(아래 참조).
# 그래도 표 완전성(키 전수=Enum 전수)을 위해 SUSPENDED 키는 빈 set 으로 둔다.
_ALLOWED_SITE_TRANSITIONS: dict[SiteStatus, set[SiteStatus]] = {
    _ST.UNMAPPED: {_ST.BASELINE_MAPPING, _ST.SUSPENDED},
    _ST.BASELINE_MAPPING: {_ST.MODEL_PROCESSING, _ST.SUSPENDED},
    _ST.MODEL_PROCESSING: {_ST.MODEL_VALIDATION, _ST.SUSPENDED},
    _ST.MODEL_VALIDATION: {_ST.PROVISIONAL_AUTONOMY, _ST.REMAP_REQUIRED, _ST.SUSPENDED},
    _ST.PROVISIONAL_AUTONOMY: {_ST.PATROL_READY, _ST.REMAP_REQUIRED, _ST.SUSPENDED},
    _ST.PATROL_READY: {_ST.PATROL_ACTIVE, _ST.MODEL_STALE, _ST.SUSPENDED},
    _ST.PATROL_ACTIVE: {_ST.PATROL_READY, _ST.MODEL_STALE, _ST.SUSPENDED},
    _ST.MODEL_STALE: {_ST.MODEL_PROCESSING, _ST.REMAP_REQUIRED, _ST.SUSPENDED},
    _ST.REMAP_REQUIRED: {_ST.BASELINE_MAPPING, _ST.SUSPENDED},
    _ST.SUSPENDED: set(),
}


def assert_site_transition(
    cur: SiteStatus, nxt: SiteStatus, *, resume_target: SiteStatus | None = None
) -> None:
    """``cur → nxt`` SiteStatus 전이가 허용되는지 검증한다 (MASTER_PRD §6.3/§6.1 강제 지점).

    ``SUSPENDED``는 특수 취급이다 — 저장소 계약: 현장이 ``SUSPENDED``로 진입하는
    순간, 저장소는 진입 직전 상태를 별도로 기억해 두었다가 이후 resume 시
    ``resume_target``으로 그 값을 넘긴다. ``cur == SUSPENDED``이면 이 함수는
    정적 전이표를 쓰지 않고 ``nxt == resume_target``일 때만 허용한다 — 즉
    저장소가 실제로 기억한 직전 상태로 돌아가는 resume만 합법이며, 다른 상태로의
    "SUSPENDED 경유 우회"는 차단된다. ``resume_target``이 ``None``이면(저장소가
    직전 상태를 기억하지 못했거나 누락) 거부한다. ``nxt == SUSPENDED``(SUSPENDED
    재진입)는 ``resume_target`` 일치 여부와 무관하게 항상 거부한다 — resume은
    SUSPENDED를 벗어나는 전이여야 한다.

    ``cur != SUSPENDED``이면 ``resume_target``은 무시하고 정적 전이표
    (``_ALLOWED_SITE_TRANSITIONS``)로 검증한다.

    Args:
        cur: 현재 상태.
        nxt: 목표 상태.
        resume_target: ``cur == SUSPENDED``일 때만 의미를 가지는, 저장소가 기억한
            SUSPENDED 진입 직전 상태.

    Raises:
        IllegalSiteTransitionError: 전이표에 없는 불법 전이이거나(예:
            UNMAPPED→PATROL_READY 직행), SUSPENDED resume 조건을 만족하지 못할 때.
    """
    if cur is _ST.SUSPENDED:
        if nxt is _ST.SUSPENDED or resume_target is None or nxt is not resume_target:
            resume_repr = resume_target.value if resume_target is not None else "(none)"
            raise IllegalSiteTransitionError(
                f"허용되지 않은 SUSPENDED resume 전이: SUSPENDED → {nxt.value} "
                f"(resume_target={resume_repr})"
            )
        return

    allowed = _ALLOWED_SITE_TRANSITIONS.get(cur, set())
    if nxt not in allowed:
        allowed_repr = ", ".join(sorted(s.value for s in allowed)) or "없음"
        raise IllegalSiteTransitionError(
            f"허용되지 않은 현장 상태 전이: {cur.value} → {nxt.value} (허용: {allowed_repr})"
        )


def can_site_transition(
    cur: SiteStatus, nxt: SiteStatus, *, resume_target: SiteStatus | None = None
) -> bool:
    """``cur → nxt`` SiteStatus 전이 허용 여부를 예외 없이 bool로 반환한다."""
    try:
        assert_site_transition(cur, nxt, resume_target=resume_target)
    except IllegalSiteTransitionError:
        return False
    return True


# 자율운영 승인이 필요한 정적 간선(ADR-KSI-015 D2). blast radius 가 큰 대상
# 전이만 가른다 — 일상 현장 진행(매핑·처리·검증·재매핑·순찰 on/off)은 이 표에
# 없으므로 게이트되지 않는다. SUSPENDED 진입/이탈은 이 정적 표가 아니라
# :func:`requires_autonomy_approval` 이 별도로(목적지/출발 상태 기준) 처리한다
# — SUSPENDED 는 이 표에 넣지 않는다(정적 간선표 자체가 SUSPENDED 로부터의
# 간선을 두지 않는 `_ALLOWED_SITE_TRANSITIONS` 관용구와 동형).
_AUTONOMY_APPROVAL_GATED_TRANSITIONS: frozenset[tuple[SiteStatus, SiteStatus]] = frozenset(
    {
        (_ST.MODEL_VALIDATION, _ST.PROVISIONAL_AUTONOMY),  # 자율 시작 승인
        (_ST.PROVISIONAL_AUTONOMY, _ST.PATROL_READY),  # 정식 순찰 승인
    }
)


def requires_autonomy_approval(cur: SiteStatus, nxt: SiteStatus) -> bool:
    """``cur → nxt`` 전이가 자율운영 승인(관리자 전용)을 요구하는지 (ADR-KSI-015 D2).

    **간선(``(from, to)``) 쌍 기준 판정이다 — 목적지 상태만으로 가르지 않는다.**
    ``PATROL_READY`` 로 들어오는 정적 간선이 둘이라(``PROVISIONAL_AUTONOMY →``
    최초 정식 승인, ``PATROL_ACTIVE →`` 순찰 후 정상 복귀) 목적지 상태 하나만
    보면 순찰 복귀까지 잘못 막는다.

    세 갈래로 판정한다:

    - ``nxt is SUSPENDED``: 모든 상태에서의 운영중단 진입은 출발 상태와 무관하게
      게이트된다.
    - ``cur is SUSPENDED``: 운영중단 복귀는 목적지와 무관하게 게이트된다. 실제
      허용되는 유일한 복귀 대상은 저장소가 기억한 ``resume_target`` 뿐이지만
      (:func:`assert_site_transition` 이 별도로 강제) 그 적법성 판정 이전에
      권한부터 확인해도 안전하다 — 둘 다 결국 거부해야 하는 요청을 거부하는
      순서 차이일 뿐이다.
    - 그 외에는 :data:`_AUTONOMY_APPROVAL_GATED_TRANSITIONS` 정적 표를 따른다 —
      예를 들어 ``PATROL_ACTIVE → PATROL_READY``(순찰 복귀)는 이 표에 없으므로
      게이트되지 않는다.

    이 함수는 전이의 **적법성**을 판정하지 않는다(:func:`assert_site_transition`
    소관) — **권한 요구 여부만** 판정한다. 호출자는 두 판정을 모두 통과해야
    실제 전이를 수행할 수 있다.
    """
    if nxt is _ST.SUSPENDED or cur is _ST.SUSPENDED:
        return True
    return (cur, nxt) in _AUTONOMY_APPROVAL_GATED_TRANSITIONS


class TriageStatus(StrEnum):
    """서버측 트리아지 워크플로 상태 (MASTER_PRD §17.2, ADR-KSI-008 §4 2-enum 분리).

    ``EventStatus``(edge 산출물 상태, event-bundle.v1.2 스키마 enum과 1:1 잠금 —
    확장 금지)와는 별개의 서버측 전용 상태다. 배정 이후 전이(``ASSIGNED`` 이후
    전 구간)는 대응 사건의 ``EventStatus == CONFIRMED_EVENT``일 때만 허용된다 —
    이 모듈은 TriageStatus 자체의 전이 적법성만 검증하며, EventStatus와의 결합
    검증(집행)은 저장소 계층의 책임이다.
    """

    NONE = "NONE"
    ASSIGNED = "ASSIGNED"
    ACTION_IN_PROGRESS = "ACTION_IN_PROGRESS"
    REINSPECTION_REQUESTED = "REINSPECTION_REQUESTED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class IllegalTriageTransitionError(ValueError):
    """허용되지 않은 TriageStatus 전이 시도 시 발생."""


_TT = TriageStatus

# 허용 전이표(SSOT, MASTER_PRD §17.2). CLOSED 는 이 스키마 범위에서 종단 상태다.
_ALLOWED_TRIAGE_TRANSITIONS: dict[TriageStatus, set[TriageStatus]] = {
    _TT.NONE: {_TT.ASSIGNED},
    _TT.ASSIGNED: {_TT.ACTION_IN_PROGRESS},
    _TT.ACTION_IN_PROGRESS: {_TT.REINSPECTION_REQUESTED, _TT.RESOLVED},
    _TT.REINSPECTION_REQUESTED: {_TT.ACTION_IN_PROGRESS, _TT.RESOLVED},
    _TT.RESOLVED: {_TT.CLOSED},
    _TT.CLOSED: set(),
}


def assert_triage_transition(cur: TriageStatus, nxt: TriageStatus) -> None:
    """``cur → nxt`` TriageStatus 전이가 허용되는지 검증한다 (MASTER_PRD §17.2 강제 지점).

    배정 이후 전이(``ASSIGNED`` 이후 전 구간)는 대응 사건의
    ``EventStatus == CONFIRMED_EVENT``인 사건에만 허용된다 — 이 결합 규칙의 집행은
    저장소 계층 소관이며, 이 함수는 TriageStatus 값 자체의 전이 적법성만 본다.

    Args:
        cur: 현재 상태.
        nxt: 목표 상태.

    Raises:
        IllegalTriageTransitionError: 전이표에 없는 불법 전이일 때(예: CLOSED
            이후 재오픈, NONE→ACTION_IN_PROGRESS 단계 건너뛰기).
    """
    allowed = _ALLOWED_TRIAGE_TRANSITIONS.get(cur, set())
    if nxt not in allowed:
        allowed_repr = ", ".join(sorted(s.value for s in allowed)) or "없음"
        raise IllegalTriageTransitionError(
            f"허용되지 않은 트리아지 상태 전이: {cur.value} → {nxt.value} (허용: {allowed_repr})"
        )


def can_triage_transition(cur: TriageStatus, nxt: TriageStatus) -> bool:
    """``cur → nxt`` TriageStatus 전이 허용 여부를 예외 없이 bool로 반환한다."""
    try:
        assert_triage_transition(cur, nxt)
    except IllegalTriageTransitionError:
        return False
    return True


class MissionExecutionStatus(StrEnum):
    """임무 1건의 실행 생애주기 (ADR-KSI-019 G2).

    ``MissionRecord``(``ksi_core.mission_records``)는 **발급 기록**이라 "이 임무가
    실제로 날았는가"에 답하지 못했다. 이 enum 이 그 축을 연다.

    ## 없는 상태가 하나 있다 — ``IN_FLIGHT``

    KSI 는 비행 중 텔레메트리를 받지 않는다(INV-001 — 서버는 프레임별 제어·수신
    주체가 아니다). 그래서 "지금 날고 있다"는 서버가 아는 사실이 아니다.
    ``ACTIVATED``(Edge 가 계약을 활성화했다고 서명해 보고한 시점)가 완료 이전
    구간에서 **서버가 실제로 아는 가장 앞선 사실**이고, 그 앞에 없는 상태를
    지어내지 않는다 — 지어내면 화면이 그 값을 사실처럼 보여줄 자리가 생긴다.
    """

    #: 계약·경로가 발급됐다. 실행 레코드가 아직 없는 임무의 기본값이다.
    ISSUED = "ISSUED"
    #: 기체 쪽으로 넘어갔다 — Edge 가 envelope 을 pull 했거나, 운영자가 KMZ 를
    #: 손으로 옮겼다고 신고했다(수동 이관이 아직 공식 경로다, ADR-KSI-019 G3).
    DISPATCHED = "DISPATCHED"
    #: Edge 가 activation receipt 를 서명해 보고했다.
    ACTIVATED = "ACTIVATED"
    #: CoverageReport 가 ``COMPLETED`` 로 접수됐다(INV-010 게이트 통과).
    COMPLETED = "COMPLETED"
    #: CoverageReport 가 접수됐지만 완료가 아니다
    #: (``COMPLETED_WITH_GAPS``·``ABORTED_SAFE``·``FAILED``).
    ENDED_INCOMPLETE = "ENDED_INCOMPLETE"
    #: 사람이 이 임무를 접었다.
    CANCELLED = "CANCELLED"


class IllegalMissionExecutionTransitionError(ValueError):
    """허용되지 않은 MissionExecutionStatus 전이 시도 시 발생."""


_MES = MissionExecutionStatus

# 허용 전이표(SSOT). 이 저장소의 다른 상태머신들과 세 가지가 다르고, 셋 다 의도다:
#
# ① **앞으로 건너뛰기를 허용한다.** 운영자가 KMZ 를 손으로 옮겨 날린 임무는
#    DISPATCHED·ACTIVATED 신호가 아예 없다(ADR-KSI-019 G3 — 실기 확인 전까지 수동
#    이관이 공식 경로다). 그 임무의 완료 보고를 실행 상태 때문에 거부하면 INV-010 의
#    완료 판정 권위가 CoverageReport 원장에서 이 필드로 넘어간다. 이 축은 게이트가
#    아니라 **관측 기록**이다.
#
# ② **COMPLETED ↔ ENDED_INCOMPLETE 는 양방향이다.** 완료 판정의 권위는 CoverageReport
#    원장이고 이 필드는 그 원장의 투영이다. 나중에 접수된 보고가 결론을 바꾸면 투영도
#    따라가야 한다 — 안 따라가면 두 표면이 서로 다른 완료를 말한다. 다만 그 둘에서
#    CANCELLED 로는 가지 않는다: 이미 끝난 비행을 취소하는 것은 뜻이 없다.
#
# ③ **CANCELLED 만 진짜 종단이다.** 사람이 접은 임무를 시스템 신호(장비 pull·커버리지
#    접수)가 되살리지 않는다. 되살려야 하면 새 임무를 발급한다.
#
# 자기 자신으로의 전이는 어디에도 없다 — 중복 신호(같은 envelope 재 pull 등)가 원장에
# 빈 레코드를 쌓지 않게 한다.
_ALLOWED_MISSION_EXECUTION_TRANSITIONS: dict[
    MissionExecutionStatus, set[MissionExecutionStatus]
] = {
    _MES.ISSUED: {
        _MES.DISPATCHED,
        _MES.ACTIVATED,
        _MES.COMPLETED,
        _MES.ENDED_INCOMPLETE,
        _MES.CANCELLED,
    },
    _MES.DISPATCHED: {
        _MES.ACTIVATED,
        _MES.COMPLETED,
        _MES.ENDED_INCOMPLETE,
        _MES.CANCELLED,
    },
    _MES.ACTIVATED: {_MES.COMPLETED, _MES.ENDED_INCOMPLETE, _MES.CANCELLED},
    _MES.COMPLETED: {_MES.ENDED_INCOMPLETE},
    _MES.ENDED_INCOMPLETE: {_MES.COMPLETED},
    _MES.CANCELLED: set(),
}

# 표 완전성 자가검증 — mission_gating.MISSION_TYPE_ALLOWED_SITE_STATUSES 와 동일 관습.
if set(_ALLOWED_MISSION_EXECUTION_TRANSITIONS) != set(MissionExecutionStatus):
    raise AssertionError(
        "_ALLOWED_MISSION_EXECUTION_TRANSITIONS 가 MissionExecutionStatus 전 멤버를 "
        "커버하지 않는다 — 조용한 기본 허용/거부를 만들지 않는다"
    )


def can_mission_execution_transition(
    cur: MissionExecutionStatus, nxt: MissionExecutionStatus
) -> bool:
    """``cur → nxt`` MissionExecutionStatus 전이 허용 여부를 예외 없이 bool 로 반환한다."""
    return nxt in _ALLOWED_MISSION_EXECUTION_TRANSITIONS.get(cur, set())


def assert_mission_execution_transition(
    cur: MissionExecutionStatus, nxt: MissionExecutionStatus
) -> None:
    """``cur → nxt`` 전이가 허용되는지 검증한다 (ADR-KSI-019 G2 강제 지점).

    Raises:
        IllegalMissionExecutionTransitionError: 표에 없는 전이일 때(예: 취소된
            임무의 완료 보고, ACTIVATED → DISPATCHED 역행).
    """
    if not can_mission_execution_transition(cur, nxt):
        allowed = (
            ", ".join(
                sorted(s.value for s in _ALLOWED_MISSION_EXECUTION_TRANSITIONS.get(cur, set()))
            )
            or "없음"
        )
        raise IllegalMissionExecutionTransitionError(
            f"허용되지 않은 임무 실행 상태 전이: {cur.value} → {nxt.value} (허용: {allowed})"
        )
