"""평면 점 집합의 볼록 껍질 — scipy 로 계산하고, 로컬로 다시 검증한다 (M4-E).

## scipy 를 쓰고 손으로 짜지 않는다

``scipy.spatial.ConvexHull`` (Qhull 바인딩)이 change-detection 의 기존
의존이다(``pyproject.toml`` — point cloud C2C 최근접거리에 이미 ``scipy.
spatial.cKDTree`` 를 쓴다) — 새 의존이 아니다. monotone chain 을 손으로
새로 짜지 않는다.

## 왜 scipy 결과를 그대로 믿지 않는가

Qhull 은 부동소수 경계 케이스(거의 공선인 점들, 중복에 가까운 점들)에서
자기모순적인 결과를 낼 수 있다. 그래서 hull 을 낸 뒤 인접 변의 외적 부호가
전 꼭짓점에서 일관되는지(볼록성) 로컬로 다시 검증한다 — 재검증 실패는
예외로 fail-closed 한다.

## ``packages/mission-planning`` 의 ``_is_convex_ring`` 을 import 하지 않는다

같은 판정(인접 변 외적 부호 일관성)을 그 패키지가 이미 갖고 있지만, 여기서
가져다 쓰지 않는다 — event-contracts/change-detection 과 mission-planning
사이에 새 결합을 만들지 않기 위해서다. 판정 자체는 몇 줄이라 독립적으로
재구현하는 비용이 결합의 비용보다 작다.
"""

from __future__ import annotations

from collections.abc import Sequence

from scipy.spatial import ConvexHull, QhullError

#: 인접 변 외적 부호 판정 허용오차(m²) — ``ksi_mission_planning.coverage.
#: _CONVEXITY_EPSILON_M2`` 와 같은 크기의 오차 여유이되, 모듈 docstring의
#: 이유로 독립적으로 재정의한다.
_CONVEXITY_EPSILON_M2 = 1e-6


class ConvexHullError(ValueError):
    """볼록 껍질 계산 또는 로컬 재검증이 실패했다 — 이 점 집합의 hull 은 만들 수 없다."""


def convex_hull_2d(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """평면 점 집합의 볼록 껍질 — CCW 순서, 닫히지 않은(첫 점을 반복하지 않는) 꼭짓점 목록.

    실패(점 부족, ``scipy.spatial.QhullError``, 로컬 볼록성 재검증 실패)는
    전부 :class:`ConvexHullError` 로 통일해 던진다 — 호출부가 예외 타입 하나만
    보고 폴백 경로를 탈 수 있게 한다.
    """
    if len(points) < 3:
        raise ConvexHullError(f"볼록 껍질을 만들려면 점이 3개 이상 필요하다: {len(points)}개")
    try:
        hull = ConvexHull(points)
    except QhullError as exc:
        raise ConvexHullError(f"scipy ConvexHull 계산이 실패했다: {exc}") from exc

    ring = [(float(points[int(i)][0]), float(points[int(i)][1])) for i in hull.vertices]
    if not _is_convex_ring(ring):
        raise ConvexHullError(
            "scipy 가 낸 hull 이 로컬 볼록성 재검증을 통과하지 못했다 — 부동소수 경계 "
            "케이스일 수 있다"
        )
    return ring


def _is_convex_ring(ring: list[tuple[float, float]]) -> bool:
    """인접 변의 외적 부호가 전 꼭짓점에서 일관되면 볼록.

    ``ksi_mission_planning.coverage._is_convex_ring`` 과 같은 판정이지만
    독립적으로 재구현한다(모듈 docstring). 공선 꼭짓점(외적≈0)은 부호 판정에서
    제외한다 — scipy hull 의 꼭짓점 목록에는 이론상 공선 점이 남지 않지만,
    부동소수 잡음으로 거의 공선인 점이 남을 수 있다.
    """
    n = len(ring)
    if n < 3:
        return False
    sign = 0
    for i in range(n):
        ax, ay = ring[i - 1]
        bx, by = ring[i]
        cx, cy = ring[(i + 1) % n]
        cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(cross) <= _CONVEXITY_EPSILON_M2:
            continue
        current_sign = 1 if cross > 0 else -1
        if sign == 0:
            sign = current_sign
        elif current_sign != sign:
            return False
    return sign != 0


__all__ = ["ConvexHullError", "convex_hull_2d"]
