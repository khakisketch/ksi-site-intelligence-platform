"""변화 후보 영역 추가 시점 수집 권고 (PRD §15.2 ⑤ "변화 후보 영역은 추가 시점 수집").

## 권고 신호일 뿐 — 재비행을 트리거하지 않는다

:func:`needs_change_candidate_revisit` 는 :meth:`CoverageReport.needs_coverage_recovery`
(``packages/event-contracts/src/ksi_event_contracts/coverage_report.py`` — 정의 위치.
``services/core/src/ksi_core/coverage_reports.py`` 는 이를 ``recoveryRecommended``
API 필드로 소비만 한다)와 동형 아키텍처다 — 순수 bool 반환, 부작용 0건. 실제 추가
수집은 기존 ``POST /v1/missions/plans``(SPATIAL_REFRESH, 원본 site AOI)를 그대로
재사용해 운영자/오퍼레이터가 발급한다.

## 판정 규칙의 정본은 여기가 아니다

규칙 자체는 ``ksi_event_contracts.change_detection_result.exceeds_revisit_threshold``
가 소유하고, 이 함수는 numpy 계산 결과(:class:`ChangeCandidateResult`)를 그 규칙에
그대로 먹이는 편의 어댑터다. 운영자가 실제로 보는 값은
``GET /v1/missions/{id}/change-detection`` 의 ``revisitRecommended`` 인데
(``services/core/src/ksi_core/change_detection.py``), 그쪽도 같은 함수를 부른다 —
규칙이 두 곳에 있으면 한쪽만 고쳐지는 순간 "계산한 값"과 "화면에 뜬 값"이
갈라지고 그 갈라짐은 어느 화면에서도 보이지 않는다.

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

from ksi_event_contracts.change_detection_result import exceeds_revisit_threshold

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
    try:
        return exceeds_revisit_threshold(
            candidate_count=result.candidate_count,
            candidate_ratio=result.candidate_ratio,
            candidate_ratio_threshold=candidate_ratio_threshold,
        )
    except ValueError as exc:
        # 규칙은 계약 패키지가 소유하지만 **이 모듈의 예외 타입 계약**은 유지한다 —
        # 호출자는 이 도메인의 실패를 ChangeDetectionError 로 잡는다.
        raise ChangeDetectionError(str(exc)) from exc


__all__ = ["needs_change_candidate_revisit"]
