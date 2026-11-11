"""2시점 DSM 전수 조사의 고정 파라미터 — ``region_extraction_policy.py`` 와 같은 자리, 같은 원칙.

## 왜 설계 경로의 ``RegionExtractionPolicy`` 를 그대로 쓰지 않는가

전수 조사는 설계 대비 잔량이 아니라 두 실측 DSM 의 차분(``DiffResult`` 전체
스캔)을 읽는다. 설계 경로의 정책이 "설계 대비 잔량에서 무엇을 걸러낼까"의
기준이라면, 조사 정책은 "실측 차분에서 무엇을 후보로 올릴까"의 기준이다 —
같은 숫자라도 근거가 다르면 같은 타입에 싣지 않는다(대표자 확정 대신, Task 1
바인딩 판정: survey 출력은 기존 계약을 그대로 쓰고, 정책 타입과 진입 경로만
새로 둔다).

## 문턱값이 정책 안에 들어 있는 이유

설계 경로는 문턱값을 ``ComparisonPolicy.volumeThresholdM`` 에서 가져오고
추출 정책은 최소면적·연결성만 담는다. 조사에는 ``ComparisonPolicy`` 가 없으므로
문턱값을 따로 인자로 받으면 "스냅샷된 정책과 실제 쓴 값"이 갈라질 수 있다
(``run_design_conformance.compute_design_conformance`` docstring의 같은
교훈). 그래서 조사 정책은 문턱값을 함께 묶는다 — 리포트의 ``thresholdM`` 과
정책 스냅샷이 갈라질 자리가 없다.

## 값의 성격 — 누락 없는 쪽에서 시작한다

전수 조사는 후보 발견이다. 못 본 변화는 되돌릴 수 없지만, 과다 후보는
``minRegionAreaM2`` 를 올려 다시 계산하면 된다(``MAX_REGIONS`` fail-closed와
같은 방향). 그래서 기본값은 설계 경로와 같은 자릿수에서 출발한다:
문턱 0.05 m(``comparison_policy.DEFAULT_VOLUME_THRESHOLD_M`` 과 동일),
최소면적 1.0 m²(``DEFAULT_MIN_REGION_AREA_M2`` 와 동일), 연결성 8(대각선
아티팩트 회피, 같은 근거).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

#: 이 상수 묶음의 이름표 — 값을 바꾸면 이것도 함께 올린다(``region_extraction_
#: policy`` 와 같은 관습). 리포트의 ``extractionPolicy.policyVersion`` 에 그대로
#: 실려 이 리포트가 설계 경로가 아니라 전수 조사에서 나왔음을 표시한다.
SURVEY_EXTRACTION_POLICY_VERSION = "survey-extraction-policy-v1"

#: 이 값 미만의 표고차는 변화로 세지 않는다(재구성 노이즈).
#: ``comparison_policy.DEFAULT_VOLUME_THRESHOLD_M`` 과 같은 출발점 — 관측
#: 편의값이지 캘리브레이션된 수치가 아니다.
DEFAULT_SURVEY_THRESHOLD_M = 0.05

#: 이 값 미만의 연결영역은 결과에서 걸러진다(m²). **관측 편의값이다** —
#: ``region_extraction_policy.DEFAULT_MIN_REGION_AREA_M2`` 와 같은 지위로,
#: "이 정도로 작은 조각은 촬영 노이즈·마스킹 경계 잡음일 가능성이 크다"는
#: 출발점이다. 걸러진 개수는 숨기지 않고 항상 노출한다
#: (``ChangeRegionSetReport.filteredRegionCount``).
DEFAULT_SURVEY_MIN_REGION_AREA_M2 = 1.0

#: 연결영역 판정의 인접 규칙. 4 는 상하좌우만, 8 은 대각선도 인접으로 본다.
#: 기본값을 8 로 두는 이유: 대각선-전용으로만 이어진 변화 경계를 4-연결이
#: 체스판 무늬로 쪼개는 아티팩트를 피한다(설계 경로와 같은 근거).
DEFAULT_SURVEY_CONNECTIVITY: Literal[4, 8] = 8


class SurveyExtractionPolicy(BaseModel):
    """전수 조사가 실제로 쓴 추출 기준값 한 벌 — 문턱 포함.

    화면은 이 값을 읽기 전용으로 표시만 한다(대표자 확정의 설계 경로 관례를
    준용: 사용자는 이 값을 입력하지 않고, 시스템 고정값을 쓰되 결과에 "이 값을
    썼다"를 표시한다).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    policy_version: str = Field(min_length=1)
    #: 이 값 미만의 표고차는 변화로 세지 않는다(m) — 리포트의 ``thresholdM`` 과
    #: 같은 값이 된다(모듈 docstring).
    threshold_m: float = Field(ge=0.0)
    #: 이 값 미만인 연결영역은 걸러진다(m²).
    min_region_area_m2: float = Field(gt=0.0)
    connectivity: Literal[4, 8]


def current_survey_extraction_policy() -> SurveyExtractionPolicy:
    """지금 이 배포의 전수 조사가 실제로 쓰는 기준값.

    조회·계산·기록 판정이 이 함수 하나만 부른다 — 여러 경로가 각자 상수를
    읽으면 "화면이 본 값"과 "계산이 쓴 값"이 갈릴 수 있다(``current_region_
    extraction_policy`` 와 같은 이유).
    """
    return SurveyExtractionPolicy(
        policy_version=SURVEY_EXTRACTION_POLICY_VERSION,
        threshold_m=DEFAULT_SURVEY_THRESHOLD_M,
        min_region_area_m2=DEFAULT_SURVEY_MIN_REGION_AREA_M2,
        connectivity=DEFAULT_SURVEY_CONNECTIVITY,
    )


__all__ = [
    "DEFAULT_SURVEY_CONNECTIVITY",
    "DEFAULT_SURVEY_MIN_REGION_AREA_M2",
    "DEFAULT_SURVEY_THRESHOLD_M",
    "SURVEY_EXTRACTION_POLICY_VERSION",
    "SurveyExtractionPolicy",
    "current_survey_extraction_policy",
]
