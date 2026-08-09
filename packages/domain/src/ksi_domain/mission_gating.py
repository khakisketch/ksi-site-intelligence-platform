"""임무 타입 × 현장 상태 발급 게이트 (MASTER_PRD §6.1/§6.3, INV-052).

"먼저 매핑, 그 다음 사전지도 기반 자율"은 이 제품의 핵심 독트린이다(MASTER_PRD
§6.1 현장 생애주기, `docs/product/DOMAIN_INVARIANTS.md` INV-052). 현장 상태머신
(:mod:`ksi_domain.enums`)은 이미 구현·강제돼 있었지만, 임무 발급이 그 상태를
전혀 보지 않아 ``UNMAPPED`` 현장에도 ``AUTONOMOUS_PATROL`` 계약이 그대로
서명·발급되는 구멍이 있었다 — 이 모듈이 그 게이트의 SSOT다.

:mod:`ksi_domain.enums` 옆(같은 패키지)에 두는 이유: 이 표도 상태전이표와
동형인 도메인 규칙(허용/거부 정적 표 + typed 예외)이고, ``SiteStatus``·
``MissionType`` 둘 다 이미 그 모듈에 있다 — Core 계층(``services/core``)은
이 표를 조회만 하지 정의하지 않는다(``assert_site_transition`` 이 Core가
아니라 여기 있는 것과 같은 배치 원칙).

## 표 도출 근거 (판단이 갈리는 지점은 명시)

- **BASELINE_MAPPING·SURVEY_GRADE_MAPPING** (매핑 계열 — "지도가 아직 없거나
  다시 그려야 한다"): 현장 상태머신이 ``BASELINE_MAPPING`` 상태로 전이 가능한
  상태와 동일하게 맞춘다 — ``UNMAPPED``(§6.1 최초 등록 직후 "3. 시스템이
  Baseline Mapping Mission을 생성한다"), ``REMAP_REQUIRED``(재매핑 사이클,
  ``enums._ALLOWED_SITE_TRANSITIONS[REMAP_REQUIRED] == {BASELINE_MAPPING,
  SUSPENDED}``). ``MODEL_STALE`` 에서는 허용하지 않는다 — 상태머신 자체가
  ``MODEL_STALE → BASELINE_MAPPING`` 직행 간선을 두지 않는다(enums.py 의
  "MODEL_STALE → PATROL_READY 직행 간선은 두지 않는다" 원칙과 동형 — 재매핑이
  필요하면 먼저 ``REMAP_REQUIRED`` 를 거친다). SURVEY_GRADE_MAPPING 은
  BASELINE_MAPPING 과 같은 lawnmower 매핑 계열로 취급한다(mission_plans.py
  ``_LAWNMOWER_TYPES`` 동일 묶음) — **문서에 별도 근거 없음, 보수적으로
  BASELINE_MAPPING과 동일 상태셋을 적용**.
- **SPATIAL_REFRESH·PROGRESS_CAPTURE** (갱신 계열 — "지도는 있고 새로
  찍는다"): 검증된 모델이 존재하는 상태(``PROVISIONAL_AUTONOMY`` 이후) +
  ``MODEL_STALE``. §6.2 "모델이 오래됐거나 큰 변화가 감지되면 부분 또는 전체
  재매핑을 선행한다" — SPATIAL_REFRESH 가 그 "부분 재매핑" 선행 조치 자체이고,
  이는 ``MODEL_STALE → MODEL_PROCESSING`` 간선(재처리 입력이 새 캡처)과
  정합한다. ``UNMAPPED``·``REMAP_REQUIRED`` 는 제외한다(갱신할 기존 모델이
  없다). PROGRESS_CAPTURE 도 §7.4 목적 "공정 변화"가 기존 매핑을 전제로 한
  비교라는 점에서 동일 전제 — **문서에 별도 근거 없음, SPATIAL_REFRESH와
  동일 상태셋으로 보수적 통일**.
- **AUTONOMOUS_PATROL·ASSET_INSPECTION** ("사전지도 기반 자율" 그 자체):
  검증되고 **현재인(stale 하지 않은)** 모델이 필요하다 — ``PROVISIONAL_
  AUTONOMY``·``PATROL_READY``·``PATROL_ACTIVE`` 만 허용하고 ``MODEL_STALE``
  은 제외한다. enums.py 가 이미 ``MODEL_STALE → PATROL_READY`` 직행을 막아둔
  "품질 검증 우회 금지" 원칙을 임무 발급 게이트에도 그대로 적용한다 — 이
  INV-052 가 사실 그 코멘트가 약속한 것의 실제 강제 지점이다(상태 전이표
  자체는 "그 상태로 못 간다"만 막고 "그 상태에서 이 임무를 못 낸다"는 막지
  못했었다). ASSET_INSPECTION 은 자산 위치를 알려면 현재 World Model 이
  필요하다는 점에서 AUTONOMOUS_PATROL 과 동일 전제라 같은 상태셋을 쓴다
  (**문서 명시 없음 — 보수적 유추**; mission_plans.py 는 ASSET_INSPECTION 의
  경로 생성 자체를 아직 미지원으로 거부하므로, 이 게이트는 그 이전에 이미
  현재 계약 단독(contract-only) 발급 우회로를 닫는 역할이 크다).
- **UNIFIED_SITE_SURVEY** ("통합 현장조사"): §6.4 통합 임무 내부 그래프의
  ``BASELINE_OR_REFRESH_CAPTURE`` 스테이지가 baseline/refresh 를 상황에 따라
  스스로 선택한다("사용자에게는 하나의 임무로 보일 수 있지만 각 Stage는 별도
  성공·부분성공·실패 상태를 가진다") — 즉 이 임무 타입은 매핑 계열과 갱신
  계열의 허용 상태를 **합집합**으로 갖도록 설계돼 있다.
- **INCIDENT_SURVEY** ("사고조사") — **판단이 갈리는 지점**(작업 지시가 미리
  짚은 지점). FINAL_DECISION_LEDGER_v1.0 §하드웨어·자율성 "미매핑 공간은
  제한속도·거리·행동으로 탐색"(MASTER_PRD DEC-013 과 동일 문구)이 미매핑
  공간에서의 운용 자체를 이미 architecturally 지원한다는 근거이고, 사고는
  매핑 여부와 무관하게 발생한다(안전관리자 페르소나의 1순위 업무, DEC-005
  "자율 안전순찰 > 지도 최신화"). 이를 근거로 ``SUSPENDED`` 를 제외한 전
  상태에서 허용한다. **주의**: 이 근거는 "임무 타입별 site-status 허용표"를
  문서가 문자 그대로 말한 것이 아니라, 미매핑 공간 운용이 이미 architecturally
  지원된다는 사실로부터의 **추론**이다 — 반대 결정(더 보수적으로 매핑된
  상태에서만 허용)도 방어 가능하며, 대표자 재검토 대상으로 남긴다.
- **MODEL_PROCESSING·MODEL_VALIDATION** (전이 처리 중 — 시스템이 직전 비행
  산출물을 자동 처리·검증하는 과도 상태): INCIDENT_SURVEY 를 제외한 모든
  임무 타입을 보수적으로 막는다 — 직전 캡처가 아직 처리·검증 중인데 새
  매핑/갱신/순찰 임무를 겹쳐 발급해도 되는지에 대한 근거가 문서에 없다
  (INV-040 fail-closed 기본값 — 근거 없는 완료·근거 없는 허용 둘 다 이
  저장소가 경계하는 실패 클래스다).
- **SUSPENDED**: 어떤 임무도 발급하지 않는다(작업 지시 명시) — 운영 중단은
  전부를 멈추는 것이 자연스럽고, 재개(resume)는 이전 상태로 돌아간 뒤에만
  임무 발급이 재개된다.
"""

from __future__ import annotations

from ksi_domain.enums import MissionType, SiteStatus

_ST = SiteStatus
_MT = MissionType

# 매핑 계열 — "지도가 아직 없거나 다시 그려야 한다"(BASELINE_MAPPING 상태로
# 전이 가능한 현장 상태와 동일, enums._ALLOWED_SITE_TRANSITIONS 참조).
_MAPPING_FROM_SCRATCH: frozenset[SiteStatus] = frozenset({_ST.UNMAPPED, _ST.REMAP_REQUIRED})

# 갱신 계열 — "지도는 있고 새로 찍는다". MODEL_STALE 은 staleness 를 해소하는
# 정정 조치 자체이므로 포함한다.
_REFRESH_EXISTING_MODEL: frozenset[SiteStatus] = frozenset(
    {_ST.PROVISIONAL_AUTONOMY, _ST.PATROL_READY, _ST.PATROL_ACTIVE, _ST.MODEL_STALE}
)

# "사전지도 기반 자율" 그 자체 — 검증되고 현재인 모델만 인정한다(MODEL_STALE 제외,
# enums.py 의 "MODEL_STALE → PATROL_READY 직행 금지" 원칙과 동형).
_AUTONOMOUS_READY: frozenset[SiteStatus] = frozenset(
    {_ST.PROVISIONAL_AUTONOMY, _ST.PATROL_READY, _ST.PATROL_ACTIVE}
)

# SUSPENDED 를 제외한 전 상태(INCIDENT_SURVEY 전용 — 모듈 docstring 판단 근거 참조).
_ALL_EXCEPT_SUSPENDED: frozenset[SiteStatus] = frozenset(SiteStatus) - {_ST.SUSPENDED}

#: SSOT — ``mission_type`` 이 발급 가능한 ``SiteStatus`` 집합. 8개 MissionType
#: 멤버 전수를 키로 갖는다(``enums.py`` 의 ``_ALLOWED_*_TRANSITIONS`` 관습과
#: 동일하게 표 완전성을 유지 — 새 MissionType 이 추가되면 이 표에도 명시적으로
#: 추가해야 한다, 조용한 기본 허용 없음).
MISSION_TYPE_ALLOWED_SITE_STATUSES: dict[MissionType, frozenset[SiteStatus]] = {
    _MT.BASELINE_MAPPING: _MAPPING_FROM_SCRATCH,
    _MT.SURVEY_GRADE_MAPPING: _MAPPING_FROM_SCRATCH,
    _MT.SPATIAL_REFRESH: _REFRESH_EXISTING_MODEL,
    _MT.PROGRESS_CAPTURE: _REFRESH_EXISTING_MODEL,
    _MT.AUTONOMOUS_PATROL: _AUTONOMOUS_READY,
    _MT.ASSET_INSPECTION: _AUTONOMOUS_READY,
    _MT.UNIFIED_SITE_SURVEY: _MAPPING_FROM_SCRATCH | _REFRESH_EXISTING_MODEL,
    _MT.INCIDENT_SURVEY: _ALL_EXCEPT_SUSPENDED,
}

# 표 완전성 자가검증 — MissionType 멤버가 늘었는데 표를 안 고치면 여기서 즉시
# ImportError 로 드러난다(assert_site_transition 의 SUSPENDED 키 완전성 유지
# 관습과 동일 정신, "조용한 기본 허용" 방지).
if set(MISSION_TYPE_ALLOWED_SITE_STATUSES) != set(MissionType):
    raise AssertionError(
        "MISSION_TYPE_ALLOWED_SITE_STATUSES 가 MissionType 전 멤버를 커버하지 않는다"
    )


class MissionTypeNotAllowedForSiteStatusError(ValueError):
    """현재 현장 상태에서 허용되지 않는 임무 타입 발급 시도."""


def is_mission_type_allowed_at_site_status(
    mission_type: MissionType, site_status: SiteStatus
) -> bool:
    """``mission_type`` 이 ``site_status`` 에서 발급 가능한지 예외 없이 bool 로 반환한다."""
    return site_status in MISSION_TYPE_ALLOWED_SITE_STATUSES[mission_type]


def assert_mission_type_allowed_at_site_status(
    mission_type: MissionType, site_status: SiteStatus
) -> None:
    """``mission_type`` × ``site_status`` 조합이 허용되는지 검증한다(INV-052 강제 지점).

    :func:`~ksi_domain.enums.assert_site_transition` 과 동일한 관용구 — 표에
    없는 조합이면 typed 예외, 있으면 무동작.

    Raises:
        MissionTypeNotAllowedForSiteStatusError: 예) ``UNMAPPED`` 현장에
            ``AUTONOMOUS_PATROL`` 발급 시도.
    """
    if not is_mission_type_allowed_at_site_status(mission_type, site_status):
        allowed = ", ".join(
            sorted(s.value for s in MISSION_TYPE_ALLOWED_SITE_STATUSES[mission_type])
        )
        raise MissionTypeNotAllowedForSiteStatusError(
            f"{mission_type.value} 는 현장 상태 {site_status.value} 에서 발급할 수 없다"
            f"(허용 상태: {allowed})"
        )


__all__ = [
    "MISSION_TYPE_ALLOWED_SITE_STATUSES",
    "MissionTypeNotAllowedForSiteStatusError",
    "assert_mission_type_allowed_at_site_status",
    "is_mission_type_allowed_at_site_status",
]
