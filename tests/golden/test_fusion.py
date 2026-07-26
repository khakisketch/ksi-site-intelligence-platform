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
    """같은 공분산 2건이면 정보 가중이 균등해 산술평균이 된다(해석적 진리).

    관측 간격은 각자의 불확실성과 정합해야 한다 — σ²=100(σ=10m)에서 10m 떨어진 두
    관측은 서로 모순되지 않는다. consistency gate가 이 정합성을 요구하므로, 산술평균
    성질을 보이려면 입력 자체가 물리적으로 성립해야 한다.
    """
    loose = (100.0, 0, 0, 0, 100.0, 0, 0, 0, 100.0)
    result = fuse_observations(
        [_obs("o1", (0.0, 0.0, 0.0), loose), _obs("o2", (10.0, 20.0, 4.0), loose)]
    )

    assert result.ok, result.detail
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
    # 부정확 관측의 σ=10m 이므로 10m 차이는 1σ — 두 관측은 서로 모순되지 않는다.
    precise = _obs("o1", (0.0, 0.0, 0.0), (0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01))
    imprecise = _obs("o2", (10.0, 0.0, 0.0), (100.0, 0, 0, 0, 100.0, 0, 0, 0, 100.0))

    result = fuse_observations([precise, imprecise])

    assert result.ok, result.detail
    assert result.position is not None
    # 정보 가중비 = (1/0.01) : (1/100) = 10000 : 0.01 → 정밀 관측이 압도한다.
    assert result.position[0] < 0.5, "정밀 관측 쪽에 훨씬 가까워야 한다"


def test_anisotropic_fusion_uses_per_axis_information() -> None:
    """축별로 정밀도가 다르면 축별로 다른 가중이 적용된다.

    o1은 x축이 정밀(0.01)하고 y축이 부정확(100), o2는 그 반대 — 결과는 x는 o1에,
    y는 o2에 가까워야 한다(축별 독립 가중의 직접 확인).
    """
    o1 = _obs("o1", (0.0, 10.0, 0.0), (0.01, 0, 0, 0, 100.0, 0, 0, 0, 1.0))
    o2 = _obs("o2", (10.0, 0.0, 0.0), (100.0, 0, 0, 0, 0.01, 0, 0, 0, 1.0))

    result = fuse_observations([o1, o2])

    assert result.ok, result.detail
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


def test_zero_covariance_rejected() -> None:
    """전부 0인 공분산은 양의 정부호가 아니다 — SPD 검사가 조건수보다 먼저 잡는다."""
    result = fuse_observations(
        [_obs("o1", (0.0, 0.0, 0.0), (0.0,) * 9), _obs("o2", (1.0, 1.0, 1.0))]
    )
    assert result.status is FusionStatus.NON_POSITIVE_DEFINITE
    assert result.position is None


def test_rank_deficient_covariance_rejected() -> None:
    """한 축의 분산이 0이면(rank 결손) 양의 정부호가 아니다 — 거부."""
    degenerate = (1.0, 0, 0, 0, 1.0, 0, 0, 0, 0.0)  # z축 분산 0
    result = fuse_observations([_obs("o1", (0.0, 0.0, 0.0), degenerate)])
    assert result.status is FusionStatus.NON_POSITIVE_DEFINITE


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


# ── 5. 2차 반증 리뷰 (2026-07-27) — SPD·consistency·중복 ID ────────────────────


def test_negative_definite_covariance_rejected() -> None:
    """[2차 반증 P0] ``-I`` 는 조건수 1이고 가역이지만 공분산이 아니다.

    통과시키면 음수 분산이 만들어져 trace가 음수가 되고, trace만 비교하는 localization
    판정에서 즉시 CONFIRMED 가 된다 — 잘못된 관측이 최고 확신으로 승격되는 경로다.
    """
    negative = (-1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0)
    result = fuse_observations(
        [_obs("o1", (0.0, 0.0, 0.0), negative), _obs("o2", (1.0, 1.0, 1.0), negative)]
    )
    assert result.status is FusionStatus.NON_POSITIVE_DEFINITE
    assert result.position is None
    assert result.position_covariance is None


def test_partially_negative_variance_rejected() -> None:
    """한 축만 음수여도 거부 — 부분적 음수 분산도 공분산이 아니다."""
    mixed = (1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 1.0)
    result = fuse_observations([_obs("o1", (0.0, 0.0, 0.0), mixed)])
    assert result.status is FusionStatus.NON_POSITIVE_DEFINITE


def test_asymmetric_covariance_rejected() -> None:
    """비대칭 행렬은 공분산이 될 수 없다 — 대칭성 검사가 잡는다."""
    asymmetric = (1.0, 0.5, 0.0, 0.1, 1.0, 0.0, 0.0, 0.0, 1.0)
    result = fuse_observations([_obs("o1", (0.0, 0.0, 0.0), asymmetric)])
    assert result.status is FusionStatus.NON_POSITIVE_DEFINITE
    assert result.detail is not None and "대칭" in result.detail


def test_symmetric_with_negative_eigenvalue_rejected() -> None:
    """대칭이지만 음의 고유값을 갖는 행렬 — Cholesky가 잡는다."""
    # [[1, 2], [2, 1]] 블록은 고유값 3, -1 → 양의 정부호 아님
    indefinite = (1.0, 2.0, 0.0, 2.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    result = fuse_observations([_obs("o1", (0.0, 0.0, 0.0), indefinite)])
    assert result.status is FusionStatus.NON_POSITIVE_DEFINITE


def test_valid_correlated_covariance_still_accepted() -> None:
    """상관이 있는 정상 공분산(대칭 SPD)은 거부되지 않아야 한다 — 과잉 차단 방지."""
    correlated = (2.0, 0.5, 0.0, 0.5, 2.0, 0.0, 0.0, 0.0, 1.0)
    result = fuse_observations([_obs("o1", (0.0, 0.0, 0.0), correlated)])
    assert result.ok, result.detail


def test_mutually_contradictory_observations_rejected() -> None:
    """[2차 반증 P0] 0m(σ²=0.01)와 100m(σ²=0.01)는 서로 완전히 모순된다.

    information-form은 "둘 다 정확한 독립 관측"으로 가정해 50m에 σ²=0.005 라는 **더
    정밀한** 결과를 낸다. 이상치 제거가 범위 밖이라도 이 집합을 정상 융합으로 승인하면
    안 된다.
    """
    tight = (0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01)
    result = fuse_observations(
        [_obs("o1", (0.0, 0.0, 0.0), tight), _obs("o2", (100.0, 0.0, 0.0), tight)]
    )
    assert result.status is FusionStatus.INCONSISTENT_OBSERVATIONS
    assert result.position is None, "모순 집합에서 위치를 산출하면 안 된다"
    assert result.detail is not None and "모순" in result.detail


def test_one_outlier_among_consistent_observations_rejected() -> None:
    """다수가 일치하고 하나만 크게 튀어도 집합 전체를 거부한다.

    어느 관측이 틀렸는지 판정하지 않는 것이 이 단계의 선택이다 — 근거 없이 하나를
    버리는 것이 더 위험하다(이상치 선별은 이후 단계).
    """
    tight = (0.04, 0, 0, 0, 0.04, 0, 0, 0, 0.04)  # σ=0.2m
    result = fuse_observations(
        [
            _obs("o1", (0.0, 0.0, 0.0), tight),
            _obs("o2", (0.1, 0.0, 0.0), tight),
            _obs("o3", (50.0, 0.0, 0.0), tight),  # 이상치
        ]
    )
    assert result.status is FusionStatus.INCONSISTENT_OBSERVATIONS


def test_consistent_observations_within_uncertainty_accepted() -> None:
    """불확실성과 정합하는 산포는 통과 — gate가 정상 관측을 막지 않는다."""
    sigma_one = (1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0)  # σ=1m
    result = fuse_observations(
        [
            _obs("o1", (0.0, 0.0, 0.0), sigma_one),
            _obs("o2", (0.8, 0.0, 0.0), sigma_one),
            _obs("o3", (-0.5, 0.3, 0.0), sigma_one),
        ]
    )
    assert result.ok, result.detail


def test_residual_threshold_is_injectable() -> None:
    """문턱을 넓히면 통과, 좁히면 거부 — gate가 실제로 그 값을 쓰는지 확인."""
    sigma_one = (1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0)
    observations = [_obs("o1", (0.0, 0.0, 0.0), sigma_one), _obs("o2", (5.0, 0.0, 0.0), sigma_one)]

    assert fuse_observations(observations, max_normalized_residual=10.0).ok
    strict = fuse_observations(observations, max_normalized_residual=1.0)
    assert strict.status is FusionStatus.INCONSISTENT_OBSERVATIONS


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_invalid_residual_threshold_rejected(bad: float) -> None:
    result = fuse_observations([_obs("o1", (0.0, 0.0, 0.0))], max_normalized_residual=bad)
    assert result.status is FusionStatus.NONFINITE_INPUT


def test_duplicate_observation_id_rejected() -> None:
    """[2차 반증 P0] 같은 관측 중복은 정보를 두 번 더해 공분산을 인위적으로 줄인다.

    멱등성 결함이 공간 확신 결함으로 전파되는 경로 — 거부한다.
    """
    result = fuse_observations([_obs("obs-a", (0.0, 0.0, 0.0)), _obs("obs-a", (0.0, 0.0, 0.0))])
    assert result.status is FusionStatus.DUPLICATE_OBSERVATION_ID
    assert result.position_covariance is None
    assert result.detail is not None and "obs-a" in result.detail


def test_duplicate_id_among_many_rejected() -> None:
    result = fuse_observations(
        [
            _obs("o1", (0.0, 0.0, 0.0)),
            _obs("o2", (0.1, 0.0, 0.0)),
            _obs("o1", (0.2, 0.0, 0.0)),  # 중복
        ]
    )
    assert result.status is FusionStatus.DUPLICATE_OBSERVATION_ID


def test_ok_covariance_is_positive_definite_and_trace_positive() -> None:
    """OK 결과의 공분산은 항상 양의 정부호이며 trace가 양수여야 한다."""
    result = fuse_observations(
        [_obs("o1", (0.0, 0.0, 0.0)), _obs("o2", (0.5, 0.2, 0.1))]
    )
    assert result.ok
    assert result.position_covariance is not None
    assert covariance_trace(result.position_covariance) > 0.0
