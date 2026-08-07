"""장비·기능 지원 상태 2-enum (P0-5, INV-041).

``CapabilityVerificationState``(기능 검증 상태)와 ``EquipmentSupportLevel``(장비 지원
단계)은 **서로 다른 축의 개념이며 절대 통합하지 않는다**(대표자 반영사항 9):

- ``CapabilityVerificationState``: DJI/Manifold **API·연동 기능**이 실기로 검증됐는지
  (MASTER_PRD §20.3 Capability Gate). "이 SDK 호출이 실제로 동작하는가"의 축.
- ``EquipmentSupportLevel``: **장비 종류**(탐지 대상 — 크레인·굴착기 등)가 얼마나 깊이
  검증됐는지(MASTER_PRD §23.3, ``contracts/schemas/equipment-support-state.v1.json``
  SSOT 정합). "이 장비를 상용으로 지원할 수 있는가"의 축.

한 capability의 API가 VERIFIED라고 해서 그 API가 다루는 장비 클래스가
PRODUCTION_SUPPORTED가 되는 것은 아니다 — 역방향도 마찬가지다. 두 enum을 같은 필드에
섞어 쓰거나 하나로 매핑하려는 시도는 이 모듈이 표현하는 불변식을 깨뜨린다.
"""

from __future__ import annotations

import unicodedata
from enum import StrEnum

# 유니코드 카테고리 첫 글자 — Z(구분자/공백)·C(제어·format·미할당)는 '내용 없음'.
_EMPTY_CATEGORY_PREFIXES = frozenset({"Z", "C"})


class CapabilityVerificationState(StrEnum):
    """장비 기능(API·연동)의 검증 상태 (MASTER_PRD §20.3).

    ``VERIFIED``가 되기 전 운영 UI에 노출하지 않는다(INV-041) — 노출 게이트는
    :meth:`ksi_core.capability.registry.CapabilityRegistry.list_operational` 이 강제한다.
    """

    VERIFIED = "VERIFIED"
    SPIKE_REQUIRED = "SPIKE_REQUIRED"
    BLOCKED = "BLOCKED"


class EquipmentSupportLevel(StrEnum):
    """장비 클래스(탐지 대상)의 지원 단계 (MASTER_PRD §23.3).

    값은 ``contracts/schemas/equipment-support-state.v1.json`` ``state`` enum과
    정확히 정합해야 한다 — 이 파일이 어긋나면 계약 왕복 테스트가 실패한다.
    ``PRODUCTION_SUPPORTED``만 공식 상용 안전지원으로 표시한다(REQ-MODEL-101).
    """

    DATASET_AVAILABLE = "DATASET_AVAILABLE"
    BASELINE_DETECTION = "BASELINE_DETECTION"
    FIELD_VALIDATED = "FIELD_VALIDATED"
    GEO_VALIDATED = "GEO_VALIDATED"
    RISK_VALIDATED = "RISK_VALIDATED"
    PRODUCTION_SUPPORTED = "PRODUCTION_SUPPORTED"


class IllegalCapabilityTransitionError(ValueError):
    """허용되지 않은 ``CapabilityVerificationState`` 전이 또는 증거 누락."""


class IllegalSupportLevelTransitionError(ValueError):
    """허용되지 않은 ``EquipmentSupportLevel`` 전이(스킵 승급 등)."""


_CV = CapabilityVerificationState

# 허용 전이표(SSOT). 모든 전이는 evidence(검증 증거 참조) 필수 — 증거 없는 전이는
# 무엇으로도 허용되지 않는다(INV-041 "증거 없는 전이 거부").
_ALLOWED_CAPABILITY_TRANSITIONS: dict[_CV, set[_CV]] = {
    _CV.SPIKE_REQUIRED: {_CV.VERIFIED, _CV.BLOCKED},
    _CV.BLOCKED: {_CV.SPIKE_REQUIRED},
    _CV.VERIFIED: {_CV.BLOCKED},  # 회귀 발견 시 재차단
}


def assert_capability_transition(
    cur: CapabilityVerificationState,
    nxt: CapabilityVerificationState,
    *,
    evidence: str | None,
) -> None:
    """``cur → nxt`` 전이가 허용되는지 + evidence가 있는지 검증한다 (INV-041 강제 지점).

    Raises:
        IllegalCapabilityTransitionError: 전이표 밖의 전이이거나 evidence가 비어있을 때.
    """
    if not has_evidence(evidence):
        raise IllegalCapabilityTransitionError(
            f"{cur.value} → {nxt.value} 전이에는 검증 증거(evidence)가 필수다"
        )
    allowed = _ALLOWED_CAPABILITY_TRANSITIONS.get(cur, set())
    if nxt not in allowed:
        allowed_repr = ", ".join(sorted(s.value for s in allowed)) or "없음"
        raise IllegalCapabilityTransitionError(
            f"허용되지 않은 capability 전이: {cur.value} → {nxt.value} (허용: {allowed_repr})"
        )


_SUPPORT_LEVEL_ORDER: list[EquipmentSupportLevel] = [
    EquipmentSupportLevel.DATASET_AVAILABLE,
    EquipmentSupportLevel.BASELINE_DETECTION,
    EquipmentSupportLevel.FIELD_VALIDATED,
    EquipmentSupportLevel.GEO_VALIDATED,
    EquipmentSupportLevel.RISK_VALIDATED,
    EquipmentSupportLevel.PRODUCTION_SUPPORTED,
]
_SUPPORT_LEVEL_INDEX: dict[EquipmentSupportLevel, int] = {
    level: i for i, level in enumerate(_SUPPORT_LEVEL_ORDER)
}


def has_evidence(evidence: str | None) -> bool:
    """증거 문자열이 실제 내용을 담고 있는가.

    ``str.strip()`` 만으로는 부족하다 — U+200B(ZWSP)·U+FEFF(BOM)·U+200C/D 같은
    **format 카테고리(Cf)** 문자는 ``isspace()`` 가 False 라 strip 이 지우지 않는데,
    화면에는 빈 문자열로 렌더된다. 즉 ``evidence="\u200b"`` 가 "증거 있음"으로
    통과하면서 사람 눈에는 아무것도 없는 상태가 만들어진다(2026-08-08 reviewer
    지적 F3, 실측 재현: ZWSP·BOM 둘 다 승급 통과).

    그래서 공백(Z*)·제어(Cc)·format(Cf) 을 전부 "내용 없음"으로 보고, 그 밖의
    문자가 하나라도 있어야 증거로 인정한다. U+00A0(NBSP)·U+3000 은 Zs 라
    ``strip()`` 도 이미 걸렀지만 여기서도 같은 규칙으로 걸린다.
    """
    if not evidence:
        return False
    return any(unicodedata.category(ch)[0] not in _EMPTY_CATEGORY_PREFIXES for ch in evidence)


def assert_support_level_transition(
    cur: EquipmentSupportLevel,
    nxt: EquipmentSupportLevel,
    *,
    evidence: str | None = None,
) -> None:
    """``cur → nxt`` 승급/**동일 단계 재선언**/강등이 허용되는지 검증한다.

    - **승급**은 순차적이어야 한다(단계 스킵 금지) + evidence 필수.
    - **동일 단계 재선언**(``cur == nxt``)도 evidence 필수다. 이건 강등이 아니라
      "이 단계가 여전히 유효하다"는 **주장**이고, 증거 없이 통과시키면 그 단계의
      근거만 지워진 채 단계 표시가 남는다 — 실제로
      ``PATCH {state: PRODUCTION_SUPPORTED, evidenceRefs: []}`` 가
      ``productionSupported: true`` + ``evidenceRefs: []`` 를 만들었다(2026-08-08
      reviewer 지적 F2, 실측 재현). 예전 구현은 ``nxt_idx <= cur_idx`` 로 동일
      단계를 강등과 같이 취급해서 생긴 구멍이다.
    - **강등**(하위 단계로 되돌리기)은 언제나 허용된다 — 현장 재검증 실패 등으로
      즉시 대응해야 하는 방향에 마찰을 넣지 않는다.

    Raises:
        IllegalSupportLevelTransitionError: 단계를 건너뛴 승급이거나, 승급·동일 단계
            재선언에 evidence가 없을 때.
    """
    cur_idx, nxt_idx = _SUPPORT_LEVEL_INDEX[cur], _SUPPORT_LEVEL_INDEX[nxt]
    if nxt_idx < cur_idx:
        return  # 강등 — 항상 허용
    if nxt_idx == cur_idx:
        if not has_evidence(evidence):
            raise IllegalSupportLevelTransitionError(
                f"{cur.value} 단계 재선언에도 검증 증거(evidence)가 필수다 — 증거 없이"
                " 통과시키면 단계 표시만 남고 그 근거가 지워진다"
            )
        return
    if nxt_idx != cur_idx + 1:
        raise IllegalSupportLevelTransitionError(
            f"단계 스킵 승급 금지: {cur.value} → {nxt.value} "
            f"(다음 단계는 {_SUPPORT_LEVEL_ORDER[cur_idx + 1].value} 이어야 한다)"
        )
    if not has_evidence(evidence):
        raise IllegalSupportLevelTransitionError(
            f"{cur.value} → {nxt.value} 승급에는 검증 증거(evidence)가 필수다"
        )


def is_production_supported(level: EquipmentSupportLevel) -> bool:
    """``PRODUCTION_SUPPORTED``만 공식 상용 안전지원으로 표시한다 (REQ-MODEL-101)."""
    return level is EquipmentSupportLevel.PRODUCTION_SUPPORTED
