"""변화 정도 → 재관측 촬영 계획 도출 (ADR-KSI-019 G5).

이 파일이 지키는 것은 "좋은 밀도"가 아니라 **규칙이 근거를 갖는가**다 — 임계값이
서버가 지어낸 숫자가 아니라 리포트가 싣고 있는 값에서 나오는가, 하한을 넘지
않는가, 왜 그 등급이 나왔는지가 결과에 남는가.
"""

from __future__ import annotations

import pytest
from ksi_mission_contracts.models import FlightEnvelope
from ksi_mission_planning.camera import MIN_FRONT_OVERLAP, MIN_SIDE_OVERLAP, CameraSpec
from ksi_mission_planning.reobservation import (
    DETAIL_ALTITUDE_FACTOR,
    BaselineCapture,
    ChangeSignals,
    ReobservationGrade,
    derive_reobservation_capture,
)


@pytest.fixture
def camera() -> CameraSpec:
    # DJI M4D 광각 계열에 가까운 값 — 이 테스트가 검증하는 것은 규칙이지
    # 특정 기체의 스펙 정확도가 아니다(스펙 정본은 장비 레지스트리 소관).
    return CameraSpec(
        sensor_width_mm=17.3, focal_length_mm=12.29, image_width_px=5280, image_height_px=3956
    )


@pytest.fixture
def baseline(camera: CameraSpec) -> BaselineCapture:
    return BaselineCapture(altitude_m=80.0, front_overlap=0.8, side_overlap=0.7, camera=camera)


@pytest.fixture
def baseline_low(camera: CameraSpec) -> BaselineCapture:
    return BaselineCapture(altitude_m=25.0, front_overlap=0.8, side_overlap=0.7, camera=camera)


@pytest.fixture
def baseline_high(camera: CameraSpec) -> BaselineCapture:
    return BaselineCapture(altitude_m=145.0, front_overlap=0.8, side_overlap=0.7, camera=camera)


@pytest.fixture
def baseline_thin_overlap(camera: CameraSpec) -> BaselineCapture:
    return BaselineCapture(altitude_m=80.0, front_overlap=0.62, side_overlap=0.52, camera=camera)


@pytest.fixture
def envelope() -> FlightEnvelope:
    return FlightEnvelope(
        allowed_volumes=["site-a"],
        excluded_volumes=[],
        min_altitude_m=20.0,
        max_altitude_m=120.0,
        altitude_reference="relativeToStartPoint",
    )


@pytest.fixture
def envelope_tight() -> FlightEnvelope:
    return FlightEnvelope(
        allowed_volumes=["site-a"],
        excluded_volumes=[],
        min_altitude_m=20.0,
        max_altitude_m=120.0,
        altitude_reference="relativeToStartPoint",
    )


def test_large_change_keeps_the_baseline_capture(
    baseline: BaselineCapture, envelope: FlightEnvelope
) -> None:
    """노이즈 바닥보다 충분히 큰 변화는 직전과 같은 촬영으로 확인된다.

    변화가 이미 뚜렷하면 더 조여서 얻을 게 없다 — 비행 시간만 늘어난다.
    """
    signals = ChangeSignals(
        area_m2=1000.0,
        cut_m3=0.0,
        fill_m3=900.0,  # 평균 |Δz| = 0.9m
        volume_threshold_m=0.05,
        unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(baseline=baseline, signals=signals, envelope=envelope)

    assert plan.grade is ReobservationGrade.STANDARD
    assert plan.altitude_m == baseline.altitude_m
    assert plan.front_overlap == baseline.front_overlap
    assert plan.capture_interval_m > 0.0


def test_change_near_the_noise_floor_escalates_resolution(
    baseline: BaselineCapture, envelope: FlightEnvelope
) -> None:
    """[핵심] 노이즈 바닥에 가까운 변화는 더 조여야 확인된다.

    직관과 반대로 보이지만 맞다 — 작은 변화일수록 그것이 진짜인지 재구성 오차인지
    가르려면 더 나은 해상도가 필요하다. 기준은 서버가 지어낸 값이 아니라 그 체적
    계산이 실제로 쓴 ``threshold_m`` 이다.
    """
    signals = ChangeSignals(
        area_m2=1000.0,
        cut_m3=30.0,
        fill_m3=30.0,  # 평균 |Δz| = 0.06m
        volume_threshold_m=0.05,  # SNR = 1.2 < 2.0
        unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(baseline=baseline, signals=signals, envelope=envelope)

    assert plan.grade is ReobservationGrade.DETAILED
    assert plan.altitude_m == pytest.approx(baseline.altitude_m * DETAIL_ALTITUDE_FACTOR)
    assert plan.gsd_m < plan.baseline_gsd_m
    assert plan.front_overlap == baseline.front_overlap  # 해상도 문제이지 겹침 문제가 아니다
    assert plan.capture_interval_m < derive_reobservation_capture(
        baseline=baseline,
        signals=ChangeSignals(
            area_m2=1000.0,
            cut_m3=0.0,
            fill_m3=900.0,
            volume_threshold_m=0.05,
            unmeasurable_ratio=0.0,
        ),
        envelope=envelope,
    ).capture_interval_m


def test_high_unmeasurable_ratio_escalates_overlap(
    baseline: BaselineCapture, envelope: FlightEnvelope
) -> None:
    """직전 관측이 못 본 비율이 높으면 겹침을 올린다 — 가림·기하 문제다."""
    signals = ChangeSignals(
        area_m2=1000.0,
        cut_m3=0.0,
        fill_m3=900.0,
        volume_threshold_m=0.05,
        unmeasurable_ratio=0.35,
    )

    plan = derive_reobservation_capture(baseline=baseline, signals=signals, envelope=envelope)

    assert plan.grade is ReobservationGrade.INTENSIVE
    assert plan.front_overlap > baseline.front_overlap
    assert plan.side_overlap > baseline.side_overlap


def test_both_signals_produce_intensive(
    baseline: BaselineCapture, envelope: FlightEnvelope
) -> None:
    signals = ChangeSignals(
        area_m2=1000.0,
        cut_m3=30.0,
        fill_m3=30.0,
        volume_threshold_m=0.05,
        unmeasurable_ratio=0.35,
    )

    plan = derive_reobservation_capture(baseline=baseline, signals=signals, envelope=envelope)

    assert plan.grade is ReobservationGrade.INTENSIVE
    assert plan.altitude_m < baseline.altitude_m
    assert plan.front_overlap > baseline.front_overlap


def test_zero_threshold_does_not_escalate_and_says_why(
    baseline: BaselineCapture, envelope: FlightEnvelope
) -> None:
    """[핵심] 노이즈 바닥이 0 이면 신호대잡음을 계산할 수 없다 — 지어내지 않는다."""
    signals = ChangeSignals(
        area_m2=1000.0,
        cut_m3=1.0,
        fill_m3=1.0,
        volume_threshold_m=0.0,
        unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(baseline=baseline, signals=signals, envelope=envelope)

    assert plan.signal_to_noise is None
    assert plan.grade is ReobservationGrade.STANDARD
    assert any("노이즈 바닥" in r for r in plan.rationale)


def test_altitude_is_clamped_to_the_envelope_minimum(
    baseline_low: BaselineCapture, envelope_tight: FlightEnvelope
) -> None:
    """[핵심] 도출이 비행 봉투 아래로 내려가지 않는다 — 그리고 잘렸다고 말한다."""
    signals = ChangeSignals(
        area_m2=1000.0,
        cut_m3=30.0,
        fill_m3=30.0,
        volume_threshold_m=0.05,
        unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(
        baseline=baseline_low, signals=signals, envelope=envelope_tight
    )

    assert plan.altitude_m == envelope_tight.min_altitude_m
    assert any("봉투 하한" in r for r in plan.rationale)


def test_overlap_never_falls_below_the_floor(
    baseline_thin_overlap: BaselineCapture, envelope: FlightEnvelope
) -> None:
    """직전이 하한 근처였어도 결과는 하한 위다(INV-015)."""
    signals = ChangeSignals(
        area_m2=1000.0,
        cut_m3=0.0,
        fill_m3=900.0,
        volume_threshold_m=0.05,
        unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(
        baseline=baseline_thin_overlap, signals=signals, envelope=envelope
    )

    assert plan.front_overlap >= MIN_FRONT_OVERLAP
    assert plan.side_overlap >= MIN_SIDE_OVERLAP


def test_result_never_exceeds_the_regulatory_ceiling(
    baseline_high: BaselineCapture, envelope: FlightEnvelope
) -> None:
    """이 도출은 고도를 낮추기만 하지만, 상한 검사를 생략하지 않는다(INV-014)."""
    signals = ChangeSignals(
        area_m2=1000.0,
        cut_m3=0.0,
        fill_m3=900.0,
        volume_threshold_m=0.05,
        unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(baseline=baseline_high, signals=signals, envelope=envelope)

    assert plan.altitude_m <= envelope.max_altitude_m
    assert plan.altitude_m <= 150.0


def test_rationale_is_never_empty(baseline: BaselineCapture, envelope: FlightEnvelope) -> None:
    """왜 그 등급인지가 항상 결과에 남는다 — 근거 없는 자동 판정은 쓰지 않는다."""
    signals = ChangeSignals(
        area_m2=1000.0,
        cut_m3=0.0,
        fill_m3=900.0,
        volume_threshold_m=0.05,
        unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(baseline=baseline, signals=signals, envelope=envelope)

    assert plan.rationale


def test_non_positive_area_is_refused(
    baseline: BaselineCapture, envelope: FlightEnvelope
) -> None:
    with pytest.raises(ValueError, match="area_m2"):
        derive_reobservation_capture(
            baseline=baseline,
            signals=ChangeSignals(
                area_m2=0.0,
                cut_m3=1.0,
                fill_m3=1.0,
                volume_threshold_m=0.05,
                unmeasurable_ratio=0.0,
            ),
            envelope=envelope,
        )


def test_exactly_at_the_snr_threshold_does_not_escalate(
    baseline: BaselineCapture, envelope: FlightEnvelope
) -> None:
    """경계는 표준 쪽이다 — SNR == 임계값이면 아직 조이지 않는다."""
    # mean_abs_dz = threshold * DETAIL_ESCALATION_SNR 이 되도록 구성.
    signals = ChangeSignals(
        area_m2=1000.0,
        cut_m3=50.0,
        fill_m3=50.0,  # 평균 |Δz| = 0.1m = 0.05 * 2.0
        volume_threshold_m=0.05,
        unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(baseline=baseline, signals=signals, envelope=envelope)

    assert plan.grade is ReobservationGrade.STANDARD


def test_negative_threshold_is_refused(
    baseline: BaselineCapture, envelope: FlightEnvelope
) -> None:
    with pytest.raises(ValueError, match="volume_threshold_m"):
        ChangeSignals(
            area_m2=1000.0,
            cut_m3=1.0,
            fill_m3=1.0,
            volume_threshold_m=-0.01,
            unmeasurable_ratio=0.0,
        )


def test_baseline_capture_rejects_nan_front_overlap(camera: CameraSpec) -> None:
    """회귀 시험(2026-08-16): NaN 은 `< MIN_FRONT_OVERLAP` 비교를 조용히 통과해

    INV-015 하한 클램프를 우회했다 — 생성 시점에 fail closed 로 막는다.
    """
    with pytest.raises(ValueError, match="front_overlap"):
        BaselineCapture(
            altitude_m=80.0, front_overlap=float("nan"), side_overlap=0.7, camera=camera
        )


def test_baseline_capture_rejects_nan_side_overlap(camera: CameraSpec) -> None:
    with pytest.raises(ValueError, match="side_overlap"):
        BaselineCapture(
            altitude_m=80.0, front_overlap=0.8, side_overlap=float("nan"), camera=camera
        )


def test_baseline_capture_rejects_infinite_overlap(camera: CameraSpec) -> None:
    with pytest.raises(ValueError, match="front_overlap"):
        BaselineCapture(
            altitude_m=80.0, front_overlap=float("inf"), side_overlap=0.7, camera=camera
        )


def test_unmeasurable_ratio_out_of_range_is_refused(
    baseline: BaselineCapture, envelope: FlightEnvelope
) -> None:
    with pytest.raises(ValueError, match="unmeasurable_ratio"):
        ChangeSignals(
            area_m2=1000.0,
            cut_m3=1.0,
            fill_m3=1.0,
            volume_threshold_m=0.05,
            unmeasurable_ratio=1.5,
        )
