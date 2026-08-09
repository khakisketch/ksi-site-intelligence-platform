"""Point cloud C2C(Cloud-to-Cloud) 변화탐지 — Phase 4 시계열 변화(PRD §15.4 "이전
모델 변화", `workers/change-detection` 스텁의 실구현 위치).

## 선택한 방법과 그 이유

M3C2(국소 표면 법선 + 다중 스케일 이웃 + 통계적 신뢰구간)가 학계·CloudCompare 의
표준이지만, 이 모듈은 그보다 단순한 **C2C(점-대-최근접점) 거리**만 구현한다:

- Open3D 는 이 워크스페이스 환경(Python 3.12, aarch64 linux)에 호환 wheel이 없다
  (2026-08-06 실측 — ``uv pip install --dry-run open3d`` 가 cp312/manylinux_aarch64
  조합의 wheel 부재를 보고했다. pyproject.toml 참고).
- CloudCompare(M3C2 표준 구현)는 GPL 이라 이 프로젝트의 AGPL/GPL 프로세스경계 정책
  (ADR-KSI-012 D2)과 같은 이유로 배제 대상이다.
- ``scipy.spatial.cKDTree``(BSD-3)로 직접 구현 가능한 것이 C2C 까지다 — 법선 추정·
  통계적 유의성 검정은 이 모듈의 범위 밖이다(필요해지면 별도 모듈로 추가한다).

## C2C 가 갖는 한계 (문서화된 알려진 성질)

법선을 쓰지 않으므로 완만한 경사면에서 실제 변화가 없어도 샘플링 밀도 차이만으로
거리가 발생할 수 있다(M3C2 가 이 문제를 법선+다중스케일로 완화한다). 이 모듈의
산출물은 **"변화 후보"이지 "확정된 변화"가 아니다** — 임계값을 넘는 거리를 가진
점을 후보로만 표시한다.

## 하지 않는 것 — 정합(registration)

이 함수는 두 point cloud 를 정렬(ICP 등)하지 않는다. 같은 site_frame(공통 좌표계)
로 이미 정합된 두 산출물을 받는다는 전제이며, 그 보증은
``ProcessingArtifact.crs``(packages/event-contracts)의 몫이다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import cKDTree


class ChangeDetectionError(ValueError):
    """입력 point cloud·파라미터가 유효하지 않을 때."""


@dataclass(frozen=True, slots=True)
class ChangeCandidateResult:
    """C2C 비교 결과 — baseline 대비 current 의 점별 최근접 거리와 변화 후보 마스크."""

    distances_m: NDArray[np.float64]  # current 각 점 → baseline 최근접 거리(m), shape (N,)
    is_candidate: NDArray[np.bool_]  # distances_m > threshold, shape (N,)
    candidate_count: int
    candidate_ratio: float  # candidate_count / len(current)


def _validate_point_cloud(points: NDArray[np.float64], *, name: str) -> None:
    if points.ndim != 2 or points.shape[1] != 3:
        raise ChangeDetectionError(
            f"{name} 은 (N, 3) 형태의 점 배열이어야 한다 (got shape={points.shape!r})"
        )
    if points.shape[0] == 0:
        raise ChangeDetectionError(f"{name} 이 비어 있다 — 빈 point cloud는 비교 대상이 아니다")
    if not np.all(np.isfinite(points)):
        raise ChangeDetectionError(f"{name} 에 비유한 좌표가 있다")


def detect_change_candidates(
    *,
    baseline: NDArray[np.float64],
    current: NDArray[np.float64],
    distance_threshold_m: float,
) -> ChangeCandidateResult:
    """baseline 대비 current 의 각 점이 얼마나 떨어져 있는지 계산하고 후보를 표시한다.

    Args:
        baseline: 이전 시점 point cloud, shape (M, 3).
        current: 비교 대상(최신) point cloud, shape (N, 3).
        distance_threshold_m: 이 거리를 **초과**하면 변화 후보로 표시(경계값 자체는
            후보가 아니다 — 엄격 부등호).

    Raises:
        ChangeDetectionError: 입력이 (N,3) 형태가 아니거나 비었거나 비유한 좌표를
            포함하거나, distance_threshold_m 이 음수·비유한일 때.
    """
    _validate_point_cloud(baseline, name="baseline")
    _validate_point_cloud(current, name="current")
    if not (math.isfinite(distance_threshold_m) and distance_threshold_m >= 0):
        raise ChangeDetectionError(
            f"distance_threshold_m 은 0 이상의 finite 값이어야 한다 "
            f"(got {distance_threshold_m!r})"
        )
    tree = cKDTree(baseline)
    raw_distances, _indices = tree.query(current, k=1)
    # current 가 (N,3) 2차원임을 이미 검증했으므로 query 는 항상 (N,) 배열을
    # 반환한다 — scipy-stubs 의 오버로드는 1차원(단일 점) 입력의 스칼라 반환도
    # 포함해 정적으로는 float|ndarray 로 보인다(런타임 분기 아님, 타입 정규화).
    distances: NDArray[np.float64] = np.asarray(raw_distances, dtype=np.float64)
    is_candidate: NDArray[np.bool_] = distances > distance_threshold_m
    candidate_count = int(np.count_nonzero(is_candidate))
    return ChangeCandidateResult(
        distances_m=distances,
        is_candidate=is_candidate,
        candidate_count=candidate_count,
        candidate_ratio=candidate_count / len(current),
    )


__all__ = ["ChangeCandidateResult", "ChangeDetectionError", "detect_change_candidates"]
