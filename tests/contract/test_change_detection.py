"""Point cloud C2C 변화탐지 (Phase 4, PRD §15.4) — scipy cKDTree 기반 최근접거리
계산이 실제로 맞는지, 임계값 경계·fail-closed 검증까지 확인한다."""

from __future__ import annotations

import numpy as np
import pytest
from ksi_change_detection.point_cloud_diff import ChangeDetectionError, detect_change_candidates


def _grid(n: int, *, z: float = 0.0) -> np.ndarray:
    """x=0..n-1, y=0, z=z 인 점 n개 — 손계산 가능한 단순 배치."""
    return np.array([[float(i), 0.0, z] for i in range(n)])


def test_identical_clouds_have_zero_distance_and_no_candidates() -> None:
    cloud = _grid(10)
    result = detect_change_candidates(
        baseline=cloud, current=cloud.copy(), distance_threshold_m=0.01
    )
    assert np.allclose(result.distances_m, 0.0)
    assert result.candidate_count == 0
    assert result.candidate_ratio == pytest.approx(0.0)


def test_single_moved_point_is_flagged_others_are_not() -> None:
    """baseline 은 x=0..9 격자, current 는 같은 격자에서 점 하나만 (5,0,0)->(5,10,0)
    로 이동 — 손계산: 그 점의 최근접 baseline 거리는 정확히 10.0(직상방 이동)."""
    baseline = _grid(10)
    current = _grid(10)
    current[5] = [5.0, 10.0, 0.0]
    result = detect_change_candidates(baseline=baseline, current=current, distance_threshold_m=1.0)
    assert result.candidate_count == 1
    assert bool(result.is_candidate[5]) is True
    assert result.distances_m[5] == pytest.approx(10.0)
    for i in range(10):
        if i != 5:
            assert bool(result.is_candidate[i]) is False
            assert result.distances_m[i] == pytest.approx(0.0)
    assert result.candidate_ratio == pytest.approx(0.1)


def test_threshold_is_strict_exceed_not_gte() -> None:
    """거리 == threshold 는 후보가 아니다(초과만 후보) — 경계값 명시 검증."""
    baseline = np.array([[0.0, 0.0, 0.0]])
    current = np.array([[2.0, 0.0, 0.0]])  # 거리 정확히 2.0
    at_boundary = detect_change_candidates(
        baseline=baseline, current=current, distance_threshold_m=2.0
    )
    assert at_boundary.candidate_count == 0
    just_below = detect_change_candidates(
        baseline=baseline, current=current, distance_threshold_m=1.999
    )
    assert just_below.candidate_count == 1


def test_all_points_moved_beyond_threshold() -> None:
    baseline = _grid(5)
    current = _grid(5, z=100.0)  # 전부 z+100 이동
    result = detect_change_candidates(baseline=baseline, current=current, distance_threshold_m=1.0)
    assert result.candidate_count == 5
    assert result.candidate_ratio == pytest.approx(1.0)
    assert np.allclose(result.distances_m, 100.0)


@pytest.mark.parametrize(
    "bad_shape",
    [
        np.zeros((5, 2)),  # 2D 좌표(z 없음)
        np.zeros((5,)),  # 1차원
        np.zeros((5, 4)),  # 여분 컬럼
    ],
)
def test_wrong_shape_rejected(bad_shape: np.ndarray) -> None:
    good = _grid(3)
    with pytest.raises(ChangeDetectionError, match="\\(N, 3\\)"):
        detect_change_candidates(baseline=good, current=bad_shape, distance_threshold_m=1.0)
    with pytest.raises(ChangeDetectionError, match="\\(N, 3\\)"):
        detect_change_candidates(baseline=bad_shape, current=good, distance_threshold_m=1.0)


def test_empty_cloud_rejected() -> None:
    good = _grid(3)
    empty = np.zeros((0, 3))
    with pytest.raises(ChangeDetectionError, match="비어"):
        detect_change_candidates(baseline=good, current=empty, distance_threshold_m=1.0)


def test_non_finite_coordinates_rejected() -> None:
    good = _grid(3)
    bad = _grid(3)
    bad[0, 0] = float("nan")
    with pytest.raises(ChangeDetectionError, match="비유한"):
        detect_change_candidates(baseline=good, current=bad, distance_threshold_m=1.0)


@pytest.mark.parametrize("threshold", [-1.0, float("nan"), float("inf")])
def test_invalid_threshold_rejected(threshold: float) -> None:
    good = _grid(3)
    with pytest.raises(ChangeDetectionError, match="distance_threshold_m"):
        detect_change_candidates(baseline=good, current=good.copy(), distance_threshold_m=threshold)


def test_zero_threshold_flags_any_nonzero_distance() -> None:
    baseline = np.array([[0.0, 0.0, 0.0]])
    current = np.array([[0.001, 0.0, 0.0]])
    result = detect_change_candidates(baseline=baseline, current=current, distance_threshold_m=0.0)
    assert result.candidate_count == 1
