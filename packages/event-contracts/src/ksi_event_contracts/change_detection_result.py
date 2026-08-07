"""ChangeDetectionResult — 두 시점 point cloud C2C 비교의 요약 (PRD §15.4).

## 왜 계약 패키지에 사는가

계산은 ``services/change-detection``(scipy cKDTree)이 하고, 수신·조회는
``services/core`` 가 한다. 계약이 계산 쪽에 있으면 Core 가 그 서비스에 의존해
``scipy`` 가 control plane 으로 딸려온다 — ``defect_candidate.py`` 를 여기로 옮긴
것과 같은 이유다(그쪽 모듈 docstring 참고).

## 점별 배열은 wire 에 싣지 않는다

:class:`~ksi_change_detection.point_cloud_diff.ChangeCandidateResult` 는 점마다
거리(``distances_m``)와 후보 여부(``is_candidate``)를 들고 있다 — 수백만 원소짜리
배열이다. 이 계약은 그 요약(개수·비율·최댓값)만 나른다. :class:`DefectCandidate` 가
마스크 래스터 대신 polygon 을 싣는 것과 같은 원칙이고, 원본 배열이 필요한 소비자는
``baseline``/``current`` 산출물을 직접 읽는다.

## 재방문 권고 규칙의 정본은 여기다

``needs_change_candidate_revisit`` (services/change-detection)는 numpy 결과 객체를
받는 편의 함수이고, **판정 규칙 자체**는 :meth:`ChangeDetectionResult.needs_revisit`
이 소유한다. 규칙이 두 곳에 있으면 한쪽만 고쳐지는 순간 "계산한 값"과 "API 가
노출한 값"이 갈라지고, 그 갈라짐은 화면에서 보이지 않는다 —
:meth:`CoverageReport.needs_coverage_recovery` 가 계약 모델의 메서드인 것과 같은
자리다(``coverage_report.py``).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

# candidateRatio 재계산 대조 허용 오차 — 제출자가 float32 로 계산했을 수 있고
# JSON 직렬화도 유한 자릿수라, 비트 단위 일치를 요구하면 정직한 결과가 거부된다.
# 반대로 너무 느슨하면 자기모순 검출이 무의미해진다. 1e-9 는 배정밀도 왕복
# 오차보다 크고 "카운트 하나 차이"(1/pointCount ≥ 1e-9 는 pointCount ≤ 10억)보다
# 작다 — 그 사이면 어떤 값이든 같은 판정을 낸다.
RATIO_TOLERANCE = 1e-9


def exceeds_revisit_threshold(
    *, candidate_count: int, candidate_ratio: float, candidate_ratio_threshold: float
) -> bool:
    """재방문 권고 판정 규칙의 **정본** (PRD §15.2 ⑤).

    :meth:`ChangeDetectionResult.needs_revisit`(API 가 노출하는 값)와
    ``ksi_change_detection.revisit_signal.needs_change_candidate_revisit``(numpy
    계산 결과에 바로 쓰는 편의 함수)가 둘 다 이 함수를 부른다. 규칙이 두 곳에
    있으면 한쪽만 고쳐지는 순간 "계산한 값"과 "화면에 뜬 값"이 갈라지고, 그
    갈라짐은 어느 화면에서도 보이지 않는다.

    ``candidate_count == 0`` 이면 비율과 무관하게 항상 ``False`` — 임계값이 0
    이어도 "후보가 없는데 재방문 권고"라는 모순을 만들지 않는다.
    ``detect_change_candidates`` 와 동일하게 **엄격 부등호**를 쓴다(경계값 자체는
    권고 트리거가 아니다).

    Raises:
        ValueError: ``candidate_ratio_threshold`` 가 ``[0, 1]`` 범위의 finite 가 아닐 때.
    """
    if not (math.isfinite(candidate_ratio_threshold) and 0.0 <= candidate_ratio_threshold <= 1.0):
        raise ValueError(
            "candidate_ratio_threshold 는 0.0~1.0 범위의 finite 값이어야 한다 "
            f"(got {candidate_ratio_threshold!r})"
        )
    if candidate_count == 0:
        return False
    return candidate_ratio > candidate_ratio_threshold


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ArtifactRef(_CamelModel):
    """산출물 참조 — ``artifactId`` 는 처리 작업 단위로만 고유하다.

    ``processing_jobs.py`` 의 중복 검사는 같은 작업 안에서만 돈다
    (``_check_artifact_identity_locked``). 그래서 산출물을 저장소 전역에서 해석하려면
    ``jobId`` 가 반드시 함께 있어야 한다 — id 하나만 들고 다니면 "그 id 를 가진
    산출물이 여러 작업에 있을 때 어느 것인가"에 답할 수 없다.
    """

    job_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)


class ChangeDetectionResult(_CamelModel):
    """contracts/schemas/change-detection-result.v1.json 왕복 대상."""

    schema_version: Literal["1.0"] = "1.0"
    change_detection_id: str = Field(min_length=1)
    baseline: ArtifactRef
    current: ArtifactRef
    distance_threshold_m: float = Field(ge=0.0)
    point_count: int = Field(ge=1)
    candidate_count: int = Field(ge=0)
    candidate_ratio: float = Field(ge=0.0, le=1.0)
    max_distance_m: float | None = Field(default=None, ge=0.0)
    computed_at: datetime

    @model_validator(mode="after")
    def _check_self_consistency(self) -> ChangeDetectionResult:
        """카운트와 비율이 서로를 뒷받침하는가 — 계약이 스스로 볼 수 있는 모순.

        ``candidateCount``·``pointCount``·``candidateRatio`` 는 독립된 세 값이
        아니라 둘이 셋째를 결정한다. 셋을 그대로 받아 적으면 "후보 0건인데 비율
        0.9" 같은 결과가 원장에 남고, 그 비율로 재방문 권고가 켜진다 — 어떤
        화면에서도 이상해 보이지 않는다.

        ``computed_at`` 이 naive 면 거부한다 — 시간대 없는 시각은 나중에 어느
        시점인지 복원할 수 없다(``coverage_report`` 의 INVALID_TIMESTAMP 와 동일 사유).
        """
        if self.computed_at.tzinfo is None:
            raise ValueError("computedAt 은 tz-aware(offset 포함) 여야 한다")
        if self.candidate_count > self.point_count:
            raise ValueError(
                f"candidateCount({self.candidate_count}) 가 pointCount({self.point_count})"
                " 보다 클 수 없다"
            )
        expected = self.candidate_count / self.point_count
        if not math.isclose(self.candidate_ratio, expected, abs_tol=RATIO_TOLERANCE):
            raise ValueError(
                f"candidateRatio({self.candidate_ratio}) 가 candidateCount/pointCount"
                f"({expected}) 와 다르다 — 세 값이 서로를 뒷받침하지 않는다"
            )
        if self.max_distance_m is not None:
            if not math.isfinite(self.max_distance_m):
                raise ValueError("maxDistanceM 은 finite 여야 한다")
            if self.candidate_count > 0 and self.max_distance_m <= self.distance_threshold_m:
                raise ValueError(
                    f"후보가 {self.candidate_count}건인데 maxDistanceM"
                    f"({self.max_distance_m}) 이 문턱({self.distance_threshold_m}) 이하다"
                    " — 문턱을 초과한 점이 하나라도 있으면 최댓값은 문턱보다 크다"
                )
        return self

    def needs_revisit(self, *, candidate_ratio_threshold: float) -> bool:
        """변화 후보 비율이 임계값을 **초과**하면 추가 시점 수집을 권고한다
        (PRD §15.2 ⑤ "변화 후보 영역은 추가 시점 수집").

        **권고일 뿐 재비행을 트리거하지 않는다** — 실제 추가 수집은 운영자가 기존
        ``POST /v1/missions/plans``(SPATIAL_REFRESH, 원본 site AOI)로 발급한다.
        Control boundary(CLAUDE.md) 때문에 이 판정은 변화 후보 지점을 방문 좌표나
        재촬영 폴리곤으로 변환하지 않는다.

        ``candidate_count == 0`` 이면 비율과 무관하게 항상 ``False`` — 임계값이 0
        이어도 "후보가 없는데 재방문 권고"라는 모순을 만들지 않는다.
        ``detect_change_candidates`` 와 동일하게 **엄격 부등호**를 쓴다.

        임계값에 기본값을 두지 않는다 — "변화 후보 비율이 얼마면 재방문이 필요한가"는
        사이트·자산 종류에 따라 달라질 정책 값이라 이 계약이 지어내지 않는다.

        Raises:
            ValueError: ``candidate_ratio_threshold`` 가 ``[0, 1]`` 범위의 finite 가 아닐 때.
        """
        return exceeds_revisit_threshold(
            candidate_count=self.candidate_count,
            candidate_ratio=self.candidate_ratio,
            candidate_ratio_threshold=candidate_ratio_threshold,
        )


__all__ = [
    "RATIO_TOLERANCE",
    "ArtifactRef",
    "ChangeDetectionResult",
    "exceeds_revisit_threshold",
]
