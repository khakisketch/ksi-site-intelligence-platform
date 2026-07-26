"""다중 시점 융합 검증 (P1-1, MASTER_PRD §10.9).

세 층으로 본다:

1. **해석적 진리** — 손으로 유도 가능한 값(동일 공분산 2관측의 융합은 산술평균,
   등방 공분산 N개 융합은 1/N 배 등). 골든벡터 없이도 참인 것들이다.
2. **불확실성 단조성(INV-021)** — 관측을 더할수록 공분산 trace가 줄어야 한다.
   information-form 산술 구조상 보장되지만, 구현이 그 구조를 실제로 유지하는지
   확인한다.
3. **결정성(P0-6 규약)** — 입력 순서가 달라도 비트 동일한 결과.
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest
from ksi_geo_core.fusion import (
    FusionObservation,
    FusionStatus,
    covariance_trace,
    fuse_observations,
)

_ISOTROPIC = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
_FRAME = "EPSG:5186+KNGeoid2018@1.0.0"


def _obs(
    observation_id: str,
    position: tuple[float, float, float],
    covariance: tuple[float, ...] = _ISOTROPIC,
    site_frame: str = _FRAME,
) -> FusionObservation:
    return FusionObservation(
        observation_id=observation_id,
        site_frame=site_frame,
        position=position,
        position_covariance=covariance,  # type: ignore[arg-type]
    )


# ── 1. 해석적 진리 ────────────────────────────────────────────────────────────


def test_single_observation_returns_itself() -> None:
    """융합할 것이 하나면 그 값 그대로 — 공분산도 변하지 않는다."""
    result = fuse_observations([_obs("o1", (10.0, 20.0, 1.7))])

    assert result.ok
    assert result.position == pytest.approx((10.0, 20.0, 1.7))
    assert result.position_covariance == pytest.approx(_ISOTROPIC)
    assert result.observation_ids == ("o1",)
    assert result.site_frame == _FRAME


def test_two_equal_covariance_observations_fuse_to_arithmetic_mean() -> None:
    """같은 공분산 2건이면 정보 가중이 균등해 산술평균이 된다(해석적 진리)."""
    result = fuse_observations(
        [_obs("o1", (0.0, 0.0, 0.0)), _obs("o2", (10.0, 20.0, 4.0))]
    )

    assert result.ok
    assert result.position == pytest.approx((5.0, 10.0, 2.0))


def test_isotropic_n_observations_reduce_covariance_by_one_over_n() -> None:
    """등방 공분산 σ²I 를 N개 융합하면 σ²/N · I 가 된다 — 해석적으로 정확한 값."""
    for n in (2, 3, 5, 10):
        observations = [_obs(f"o{i:02d}", (1.0, 2.0, 3.0)) for i in range(n)]
        result = fuse_observations(observations)

        assert result.ok
        assert result.position_covariance is not None
        expected_diagonal = 1.0 / n
        assert result.position_covariance[0] == pytest.approx(expected_diagonal)
        assert result.position_covariance[4] == pytest.approx(expected_diagonal)
        assert result.position_covariance[8] == pytest.approx(expected_diagonal)


def test_precise_observation_dominates_imprecise_one() -> None:
    """공분산이 작은(정밀한) 관측이 결과를 더 강하게 끌어당긴다."""
    precise = _obs("o1", (0.0, 0.0, 0.0), (0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01))
    imprecise = _obs("o2", (100.0, 0.0, 0.0), (100.0, 0, 0, 0, 100.0, 0, 0, 0, 100.0))

    result = fuse_observations([precise, imprecise])

    assert result.ok
    assert result.position is not None
    # 정보 가중비 = (1/0.01) : (1/100) = 10000 : 0.01 → 정밀 관측이 압도한다.
    assert result.position[0] < 0.5, "정밀 관측 쪽에 훨씬 가까워야 한다"


def test_anisotropic_fusion_uses_per_axis_information() -> None:
    """축별로 정밀도가 다르면 축별로 다른 가중이 적용된다.

    o1은 x축이 정밀(0.01)하고 y축이 부정확(100), o2는 그 반대 — 결과는 x는 o1에,
    y는 o2에 가까워야 한다(축별 독립 가중의 직접 확인).
    """
    o1 = _obs("o1", (0.0, 100.0, 0.0), (0.01, 0, 0, 0, 100.0, 0, 0, 0, 1.0))
    o2 = _obs("o2", (100.0, 0.0, 0.0), (100.0, 0, 0, 0, 0.01, 0, 0, 0, 1.0))

    result = fuse_observations([o1, o2])

    assert result.ok
    assert result.position is not None
    assert result.position[0] < 1.0, "x는 x축 정밀한 o1(0.0)에 가까워야 한다"
    assert result.position[1] < 1.0, "y는 y축 정밀한 o2(0.0)에 가까워야 한다"


# ── 2. 불확실성 단조성 (INV-021) ──────────────────────────────────────────────


def test_adding_observations_never_increases_uncertainty() -> None:
    """관측을 하나씩 더할 때 공분산 trace가 단조 비증가해야 한다."""
    traces: list[float] = []
    accumulated: list[FusionObservation] = []
    for i in range(6):
        accumulated.append(_obs(f"o{i:02d}", (float(i), float(i), 0.0)))
        result = fuse_observations(list(accumulated))
        assert result.ok
        assert result.position_covariance is not None
        traces.append(covariance_trace(result.position_covariance))

    for earlier, later in pairwise(traces):
        assert later <= earlier + 1e-12, f"관측 추가로 불확실성이 커졌다: {traces}"


def test_fused_covariance_is_smaller_than_every_input() -> None:
    """융합 결과는 어떤 개별 입력보다도 불확실성이 작아야 한다(정보가 더해지므로)."""
    observations = [
        _obs("o1", (0.0, 0.0, 0.0), (4.0, 0, 0, 0, 4.0, 0, 0, 0, 4.0)),
        _obs("o2", (1.0, 1.0, 1.0), (9.0, 0, 0, 0, 9.0, 0, 0, 0, 9.0)),
        _obs("o3", (0.5, 0.5, 0.5), (2.0, 0, 0, 0, 2.0, 0, 0, 0, 2.0)),
    ]
    result = fuse_observations(observations)

    assert result.ok
    assert result.position_covariance is not None
    fused_trace = covariance_trace(result.position_covariance)
    for observation in observations:
        assert fused_trace < covariance_trace(observation.position_covariance)


# ── 3. 결정성 (P0-6 규약) ─────────────────────────────────────────────────────


def test_input_order_does_not_change_result_bit_exactly() -> None:
    """입력 순서를 뒤집어도 **비트 동일한** 결과여야 한다(부동소수 누산 순서 정규화)."""
    observations = [
        _obs("o1", (1.1, 2.2, 3.3), (1.3, 0, 0, 0, 2.7, 0, 0, 0, 0.9)),
        _obs("o2", (4.4, 5.5, 6.6), (0.7, 0, 0, 0, 1.9, 0, 0, 0, 3.1)),
        _obs("o3", (7.7, 8.8, 9.9), (2.3, 0, 0, 0, 0.5, 0, 0, 0, 1.7)),
    ]

    forward = fuse_observations(observations)
    reversed_order = fuse_observations(list(reversed(observations)))
    shuffled = fuse_observations([observations[1], observations[2], observations[0]])

    assert forward.position == reversed_order.position == shuffled.position
    assert (
        forward.position_covariance
        == reversed_order.position_covariance
        == shuffled.position_covariance
    )
    assert forward.observation_ids == reversed_order.observation_ids == shuffled.observation_ids


def test_observation_ids_are_canonically_sorted() -> None:
    """결과의 observation_ids 는 정렬돼 있어 fingerprint 계산이 순서에 흔들리지 않는다."""
    result = fuse_observations(
        [_obs("zz", (0.0, 0.0, 0.0)), _obs("aa", (1.0, 1.0, 1.0)), _obs("mm", (2.0, 2.0, 2.0))]
    )
    assert result.observation_ids == ("aa", "mm", "zz")


def test_repeated_fusion_is_stable() -> None:
    """같은 입력을 두 번 융합하면 같은 결과 — 내부 상태가 없다."""
    observations = [_obs("o1", (1.0, 2.0, 3.0)), _obs("o2", (4.0, 5.0, 6.0))]
    first = fuse_observations(observations)
    second = fuse_observations(observations)
    assert first == second


# ── 4. 네거티브 (fail-closed) ─────────────────────────────────────────────────


def test_empty_observation_list_rejected() -> None:
    result = fuse_observations([])
    assert result.status is FusionStatus.NO_OBSERVATIONS
    assert result.position is None


def test_crs_mismatch_rejected() -> None:
    """[INV-020] 서로 다른 좌표계 관측을 섞으면 무의미한 좌표가 나온다 — 거부."""
    result = fuse_observations(
        [
            _obs("o1", (0.0, 0.0, 0.0), site_frame="EPSG:5186+KNGeoid2018@1.0.0"),
            _obs("o2", (1.0, 1.0, 1.0), site_frame="EPSG:4326+WGS84@1.0.0"),
        ]
    )
    assert result.status is FusionStatus.CRS_MISMATCH
    assert result.position is None
    assert result.detail is not None and "site_frame" in result.detail


def test_same_frame_different_transform_version_rejected() -> None:
    """같은 EPSG라도 transform 버전이 다르면 다른 프레임이다 — 문자열 동일성으로 판정."""
    result = fuse_observations(
        [
            _obs("o1", (0.0, 0.0, 0.0), site_frame="EPSG:5186+KNGeoid2018@1.0.0"),
            _obs("o2", (1.0, 1.0, 1.0), site_frame="EPSG:5186+KNGeoid2018@2.0.0"),
        ]
    )
    assert result.status is FusionStatus.CRS_MISMATCH


def test_zero_covariance_rejected_as_singular() -> None:
    """전부 0인 공분산은 역행렬이 불가능 — 조용히 거대한 가중치를 주지 않고 거부."""
    result = fuse_observations(
        [_obs("o1", (0.0, 0.0, 0.0), (0.0,) * 9), _obs("o2", (1.0, 1.0, 1.0))]
    )
    assert result.status is FusionStatus.SINGULAR_COVARIANCE
    assert result.position is None


def test_rank_deficient_covariance_rejected() -> None:
    """한 축의 분산이 0이면(rank 결손) 조건수가 발산 — 거부."""
    degenerate = (1.0, 0, 0, 0, 1.0, 0, 0, 0, 0.0)  # z축 분산 0
    result = fuse_observations([_obs("o1", (0.0, 0.0, 0.0), degenerate)])
    assert result.status is FusionStatus.SINGULAR_COVARIANCE


def test_extremely_ill_conditioned_covariance_rejected() -> None:
    """조건수가 상한을 넘으면 역행렬의 유효자리가 남지 않는다 — 거부."""
    ill = (1e15, 0, 0, 0, 1.0, 0, 0, 0, 1e-15)
    result = fuse_observations([_obs("o1", (0.0, 0.0, 0.0), ill)])
    assert result.status is FusionStatus.SINGULAR_COVARIANCE


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nonfinite_position_rejected(bad: float) -> None:
    result = fuse_observations([_obs("o1", (bad, 0.0, 0.0)), _obs("o2", (1.0, 1.0, 1.0))])
    assert result.status is FusionStatus.NONFINITE_INPUT
    assert result.position is None


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nonfinite_covariance_rejected(bad: float) -> None:
    covariance = (bad, 0, 0, 0, 1.0, 0, 0, 0, 1.0)
    result = fuse_observations([_obs("o1", (0.0, 0.0, 0.0), covariance)])
    assert result.status is FusionStatus.NONFINITE_INPUT


def test_ok_result_is_always_finite() -> None:
    """OK 결과는 위치·공분산 전부 finite여야 한다."""
    result = fuse_observations(
        [
            _obs("o1", (1.0, 2.0, 3.0), (0.5, 0, 0, 0, 1.5, 0, 0, 0, 2.5)),
            _obs("o2", (1.2, 2.1, 3.4), (1.1, 0, 0, 0, 0.6, 0, 0, 0, 1.9)),
        ]
    )
    assert result.ok
    assert result.position is not None
    assert result.position_covariance is not None
    assert all(math.isfinite(v) for v in result.position)
    assert all(math.isfinite(v) for v in result.position_covariance)
