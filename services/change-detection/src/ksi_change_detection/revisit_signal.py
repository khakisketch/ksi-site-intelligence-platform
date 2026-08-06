"""변화 후보 영역 추가 시점 수집 권고 (PRD §15.2 ⑤ "변화 후보 영역은 추가 시점 수집").

## 권고 신호일 뿐 — 재비행을 트리거하지 않는다

:func:`needs_change_candidate_revisit` 는 :meth:`CoverageReport.needs_coverage_recovery`
(``packages/event-contracts/src/ksi_event_contracts/coverage_report.py`` — 정의 위치.
``services/core/src/ksi_core/coverage_reports.py`` 는 이를 ``recoveryRecommended``
API 필드로 소비만 한다)와 동형 아키텍처다 — 순수 bool 반환, 부작용 0건. 실제 추가
수집은 기존 ``POST /v1/missions/plans``(SPATIAL_REFRESH, 원본 site AOI)를 그대로
재사용해 운영자/오퍼레이터가 발급한다.

## 현재 상태 — 소비자 없음 (알려진 스코프 경계)

이 함수는 현재 어떤 API 엔드포인트·리포트 스키마·워커에서도 호출되지 않는다
(``services/change-detection/`` 에는 change-detection 결과를 노출하는 엔드포인트가
아직 없다 — ``workers/change-detection/README.md`` 참고, 스캐폴딩만 존재).
``needs_coverage_recovery`` 는 ``recoveryRecommended`` 로 운영자가 실제로 볼 수 있는
반면, 이 함수는 아직 그런 노출 경로가 없다 — "권고만 하고 트리거하지 않는다"는
설계와 별개로, "권고를 아무도 읽을 수 없다"는 것은 별도의 갭이다. Change-detection
결과를 노출하는 API/리포트 스키마가 생기면 그 표면에 이 신호를 연결해야 한다.

Control boundary(CLAUDE.md) 때문에 이 함수는 변화 후보 지점(raw XYZ)을 방문
좌표나 세부 재촬영 구역 폴리곤으로 변환하지 않는다 — Coverage Recovery 가 같은
이유(Cell 지오메트리 저장소 부재)로 정밀 gap 영역 계산을 하지 않은 것과 동일한
근거다. 변화 후보 점들을 재촬영 폴리곤으로 뭉치는 것(clustering/영역화)은 이
모듈의 범위 밖이며, 별도 데이터모델 결정이 선행돼야 한다.

## 임계값은 호출자가 명시한다

``candidate_ratio_threshold`` 에 기본값을 두지 않는다 — "변화 후보 비율이 얼마면
재방문이 필요한가"는 사이트/자산 종류에 따라 달라질 정책 값이라, 이 모듈이
임의로 지어내지 않는다(예: 소음이 큰 야외 스캔은 임계값을 높게, 정밀 자산
점검은 낮게 잡을 수 있다 — 그 결정은 호출자/정책 계층 소관).
"""

from __future__ import annotations

import math

from ksi_change_detection.point_cloud_diff import ChangeCandidateResult, ChangeDetectionError


def needs_change_candidate_revisit(
    result: ChangeCandidateResult,
    *,
    candidate_ratio_threshold: float,
) -> bool:
    """변화 후보 비율이 임계값을 **초과**하면 추가 시점 수집을 권고한다.

    ``candidate_count == 0`` 이면(변화 후보가 하나도 없으면) 비율과 무관하게
    항상 ``False`` — 임계값이 0으로 설정된 경우에도 "후보가 없는데 재방문
    권고"라는 모순을 만들지 않는다.

    :func:`ksi_change_detection.point_cloud_diff.detect_change_candidates` 와
    동일하게 **엄격 부등호**를 쓴다(경계값 자체는 권고 트리거가 아니다).

    Raises:
        ChangeDetectionError: ``candidate_ratio_threshold`` 가 ``[0, 1]`` 범위의
            finite 값이 아닐 때.
    """
    if not (math.isfinite(candidate_ratio_threshold) and 0.0 <= candidate_ratio_threshold <= 1.0):
        raise ChangeDetectionError(
            "candidate_ratio_threshold 는 0.0~1.0 범위의 finite 값이어야 한다 "
            f"(got {candidate_ratio_threshold!r})"
        )
    if result.candidate_count == 0:
        return False
    return result.candidate_ratio > candidate_ratio_threshold


__all__ = ["needs_change_candidate_revisit"]
