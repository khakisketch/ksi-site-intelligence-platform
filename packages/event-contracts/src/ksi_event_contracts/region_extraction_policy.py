"""변화 영역 자동 추출의 고정 파라미터 — ``comparison_policy.py`` 와 같은 자리, 같은 원칙 (M4-E).

## 왜 이 값들이 여기 사는가

문턱→연결영역→최소면적 추출은 결정적이어야 하고, 그 결정성은 파라미터가
호출마다 흔들리지 않을 때만 성립한다. 계산 서비스(``ksi-change-detection``)와
Core(``ksi-core``)가 같은 값을 봐야 "화면이 말하는 최소면적"과 "실제로 걸러진
최소면적"이 갈리지 않는다 — ``comparison_policy.py`` 모듈 docstring이 설명하는
바로 그 이유다.

## 고정값이지 정책 엔진이 아니다

대표자 확정(2026-08-10, ``comparison_policy.py``)을 그대로 적용한다: 사용자는
이 값을 화면에서 입력하지 않는다. 요청 본문에 이 값을 받는 자리를 두지 않고,
시스템 고정값을 쓰되 결과 화면에 "이 값을 썼다"를 표시한다.

## 버전을 붙이는 이유

``REGION_EXTRACTION_POLICY_VERSION`` 은 이 상수 묶음의 이름표다. 값을 바꿀
때는 이 버전 문자열도 함께 올린다(``comparison_policy.py`` 와 같은 관습).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

#: 이 상수 묶음의 이름표 — 값을 바꾸면 이것도 함께 올린다(모듈 docstring).
REGION_EXTRACTION_POLICY_VERSION = "region-extraction-policy-v1"

#: 이 값 미만의 연결영역은 결과에서 걸러진다(m²). **관측 편의값이다** —
#: ``DEFAULT_VOLUME_THRESHOLD_M`` 과 같은 지위로, 캘리브레이션된 수치가
#: 아니라 "이 정도로 작은 조각은 촬영 노이즈·마스킹 경계 잡음일 가능성이
#: 크다"는 출발점이다. 걸러진 개수는 숨기지 않고 항상 노출한다
#: (``ChangeRegionSetReport.filteredRegionCount``).
DEFAULT_MIN_REGION_AREA_M2 = 1.0

#: 연결영역 판정의 인접 규칙. 4 는 상하좌우만, 8 은 대각선도 인접으로 본다.
#: 기본값을 8 로 두는 이유: 대각선-전용으로만 이어진 절토/성토 경계를 4-연결이
#: 체스판 무늬로 쪼개는 아티팩트를 피한다.
DEFAULT_CONNECTIVITY: Literal[4, 8] = 8


class RegionExtractionPolicy(BaseModel):
    """지금 쓰이는 추출 기준값 한 벌 — 조회 표면과 결과 스냅샷이 같은 모양을 쓴다.

    화면은 이 값을 읽기 전용으로 표시만 한다(대표자 확정). 요청에 스냅샷을
    남기지 않는다 — ``comparison_policy``/``design_conformance`` 와 달리 이
    값은 요청 시점이 아니라 **리포트 기록 시점**의 ``current_region_extraction_
    policy()`` 와 대조된다(policy-owned 기반안 — region_extraction_reports.py
    참조). 값을 개별 상수로 흩지 않고 한 벌로 묶는 이유는 그 대조가 통째로
    한 번에 일어나야 하기 때문이다.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    policy_version: str = Field(min_length=1)
    #: 이 값 미만인 연결영역은 걸러진다(m²).
    min_region_area_m2: float = Field(gt=0.0)
    connectivity: Literal[4, 8]


def current_region_extraction_policy() -> RegionExtractionPolicy:
    """지금 이 배포가 실제로 쓰는 추출 기준값.

    조회·계산·기록 판정이 이 함수 하나만 부른다 — 여러 경로가 각자 상수를
    읽으면 "화면이 본 값"과 "계산이 쓴 값"이 갈릴 수 있다(``current_
    comparison_policy`` 와 같은 이유).
    """
    return RegionExtractionPolicy(
        policy_version=REGION_EXTRACTION_POLICY_VERSION,
        min_region_area_m2=DEFAULT_MIN_REGION_AREA_M2,
        connectivity=DEFAULT_CONNECTIVITY,
    )


__all__ = [
    "DEFAULT_CONNECTIVITY",
    "DEFAULT_MIN_REGION_AREA_M2",
    "REGION_EXTRACTION_POLICY_VERSION",
    "RegionExtractionPolicy",
    "current_region_extraction_policy",
]
