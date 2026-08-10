"""두 시점 비교의 고정 기준값 — **계산 코드와 조회 표면이 공유하는 단 하나의 자리**.

## 왜 이 값들이 여기 사는가

거리 문턱·재방문 비율은 원래 세 곳에 흩어진 파이썬 상수였다(계산 쪽
``run_change_detection``·``run_volume_change``, Core 쪽 ``change_detection``).
숫자가 같은 동안은 아무 문제가 없지만, 화면이 그 값을 **읽기 전용으로 보여줘야**
하는 순간(W2-3 필수조건) 문제가 드러난다: 화면이 자기 코드에 0.05 를 적으면
계산 쪽이 0.03 으로 바뀌어도 화면은 계속 0.05 라고 말하고, **그 거짓말은 어느
화면에서도 보이지 않는다**. 이 저장소가 ``exceeds_revisit_threshold``(재방문 판정
규칙)를 계약 패키지로 끌어올린 것과 정확히 같은 이유다 — 규칙이든 상수든, 두
소비자가 있으면 정본은 하나여야 한다.

계산 서비스(``ksi-change-detection``)와 Core(``ksi-core``)가 **둘 다 이미 의존하는
유일한 경량 패키지**가 이 패키지라, 여기가 그 하나뿐인 자리다. Core 가 계산
서비스를 직접 import 하면 scipy·rasterio 가 control plane 으로 딸려온다
(``change_detection_result.py`` 모듈 docstring "왜 계약 패키지에 사는가").

## 고정값이지 정책 엔진이 아니다

대표자 확정(2026-08-10): 사용자는 이 값을 화면에서 입력하지 않는다. 시스템
고정값을 쓰되 **결과·제출 화면 양쪽에 "이 값을 썼다"를 반드시 표시한다** — 고정값
이라고 숨기지 않는다. 그래서 이 모듈은 값을 고르는 로직이 없고, 지금 무엇이
쓰이는지 말해주는 것이 전부다.

## 버전을 붙이는 이유

``COMPARISON_POLICY_VERSION`` 은 이 상수 묶음의 이름표다. 비교 요청은 생성 시점의
정책을 **값으로 스냅샷**해 레코드에 남기므로(``comparison_requests.py``), 나중에
이 값들이 바뀌어도 이미 만들어진 요청·결과는 "그때 무슨 기준으로 쟀는지"를
스스로 답할 수 있다 — zones 를 참조가 아니라 값으로 저장하는 것과 같은 원칙이다.
값을 바꿀 때는 이 버전 문자열도 함께 올린다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

#: 이 상수 묶음의 이름표 — 값을 바꾸면 이것도 함께 올린다(모듈 docstring).
COMPARISON_POLICY_VERSION = "comparison-policy-v1"

#: 점군 C2C 후보 거리 문턱(m). **정책값이 아니라 출발점**이다 — 현장·엔진·GSD 에
#: 따라 달라지고, 0.05m 는 재구성 노이즈 하한의 관측 편의값이지 캘리브레이션된
#: 수치가 아니다. 이 정직성은 화면에도 그대로 표시된다.
DEFAULT_DISTANCE_THRESHOLD_M = 0.05

#: DSM 차분에서 이 값보다 작은 표고차는 변화로 세지 않는다(m). 위와 같은 지위 —
#: 재구성 노이즈를 변화로 읽으면 아무것도 안 한 날에도 체적이 나온다.
DEFAULT_VOLUME_THRESHOLD_M = 0.05

#: 변화 후보 비율이 이 값을 **초과**하면 추가 시점 수집을 권고한다.
#: "점 20개 중 1개가 문턱을 넘으면 눈에 띄는 변화"라는 관측 편의값이다.
DEFAULT_REVISIT_RATIO_THRESHOLD = 0.05


class ComparisonPolicy(BaseModel):
    """지금 쓰이는 기준값 한 벌 — 조회 표면과 요청 스냅샷이 같은 모양을 쓴다.

    화면은 이 값을 **읽기 전용으로 표시만** 한다(대표자 확정). 필드를 개별 상수로
    흩지 않고 한 벌로 묶은 이유는, 비교 요청이 이 묶음을 통째로 스냅샷해야
    "그때 무슨 기준이었나"가 온전히 복원되기 때문이다.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    policy_version: str = Field(min_length=1)
    distance_threshold_m: float = Field(ge=0.0)
    volume_threshold_m: float = Field(ge=0.0)
    revisit_ratio_threshold: float = Field(ge=0.0, le=1.0)


def current_comparison_policy() -> ComparisonPolicy:
    """지금 이 배포가 실제로 쓰는 기준값.

    조회 endpoint 도, 비교 요청 생성 시 스냅샷도 이 함수 하나만 부른다 — 두
    경로가 각자 상수를 읽으면 "화면이 본 값"과 "계산이 쓴 값"이 갈라질 수 있다.
    """
    return ComparisonPolicy(
        policy_version=COMPARISON_POLICY_VERSION,
        distance_threshold_m=DEFAULT_DISTANCE_THRESHOLD_M,
        volume_threshold_m=DEFAULT_VOLUME_THRESHOLD_M,
        revisit_ratio_threshold=DEFAULT_REVISIT_RATIO_THRESHOLD,
    )


__all__ = [
    "COMPARISON_POLICY_VERSION",
    "DEFAULT_DISTANCE_THRESHOLD_M",
    "DEFAULT_REVISIT_RATIO_THRESHOLD",
    "DEFAULT_VOLUME_THRESHOLD_M",
    "ComparisonPolicy",
    "current_comparison_policy",
]
