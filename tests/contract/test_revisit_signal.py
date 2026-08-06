"""변화 후보 영역 추가 시점 수집 권고 (PRD §15.2 ⑤) — needs_change_candidate_revisit
가 순수 bool 신호로 정확히 동작하는지 골든 벡터로 확인한다."""

from __future__ import annotations

import numpy as np
import pytest
from ksi_change_detection.point_cloud_diff import ChangeDetectionError, detect_change_candidates
from ksi_change_detection.revisit_signal import needs_change_candidate_revisit


def _grid(n: int, *, z: float = 0.0) -> np.ndarray:
    return np.array([[float(i), 0.0, z] for i in range(n)])


def test_no_candidates_never_recommends_revisit_even_at_zero_threshold() -> None:
    """candidate_count == 0 이면 threshold=0.0 이어도 False — 모순 방지."""
    cloud = _grid(10)
    result = detect_change_candidates(
        baseline=cloud, current=cloud.copy(), distance_threshold_m=0.01
    )
    assert result.candidate_count == 0
    assert needs_change_candidate_revisit(result, candidate_ratio_threshold=0.0) is False


def test_ratio_above_threshold_recommends_revisit() -> None:
    """10점 중 1점 후보 → ratio=0.1. threshold=0.05 미만이면 권고, 초과면 비권고."""
    baseline = _grid(10)
    current = _grid(10)
    current[5] = [5.0, 10.0, 0.0]
    result = detect_change_candidates(baseline=baseline, current=current, distance_threshold_m=1.0)
    assert result.candidate_ratio == pytest.approx(0.1)
    assert needs_change_candidate_revisit(result, candidate_ratio_threshold=0.05) is True
    assert needs_change_candidate_revisit(result, candidate_ratio_threshold=0.5) is False


def test_threshold_is_strict_exceed_not_gte() -> None:
    """ratio == threshold 는 권고가 아니다(초과만 권고) — point_cloud_diff 와 동일 규약."""
    baseline = _grid(4)
    current = _grid(4)
    current[0] = [0.0, 10.0, 0.0]  # 4점 중 1점 후보 → ratio 정확히 0.25
    result = detect_change_candidates(baseline=baseline, current=current, distance_threshold_m=1.0)
    assert result.candidate_ratio == pytest.approx(0.25)
    assert needs_change_candidate_revisit(result, candidate_ratio_threshold=0.25) is False
    assert needs_change_candidate_revisit(result, candidate_ratio_threshold=0.2499) is True


def test_all_points_candidates_recommends_revisit_at_any_threshold_below_one() -> None:
    baseline = _grid(5)
    current = _grid(5, z=100.0)
    result = detect_change_candidates(baseline=baseline, current=current, distance_threshold_m=1.0)
    assert result.candidate_ratio == pytest.approx(1.0)
    assert needs_change_candidate_revisit(result, candidate_ratio_threshold=0.999) is True
    assert needs_change_candidate_revisit(result, candidate_ratio_threshold=1.0) is False


@pytest.mark.parametrize("threshold", [-0.01, 1.01, float("nan"), float("inf")])
def test_invalid_threshold_rejected(threshold: float) -> None:
    baseline = _grid(3)
    current = _grid(3)
    current[0] = [0.0, 10.0, 0.0]
    result = detect_change_candidates(baseline=baseline, current=current, distance_threshold_m=1.0)
    with pytest.raises(ChangeDetectionError, match="candidate_ratio_threshold"):
        needs_change_candidate_revisit(result, candidate_ratio_threshold=threshold)
