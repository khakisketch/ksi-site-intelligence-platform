"""변화 정도에 맞춘 재관측 촬영 계획 도출 (ADR-KSI-019 G5).

## 왜 순수 함수인가

이 규칙은 Core 의 저장소나 HTTP 표면과 아무 관계가 없다 — 입력은 숫자 몇 개고
출력도 숫자 몇 개다. ``camera.compute_grid_spacing`` 이 같은 이유로 이 패키지에
있고, Core 는 그 함수를 부르기만 한다. 규칙을 Core 에 두면 규칙을 테스트하기 위해
앱을 조립해야 하고, 그 순간 규칙이 바뀌기 어려워진다.

## 판정 근거를 서버가 지어내지 않는다

두 신호만 본다. 둘 다 **리포트 자신이 싣고 있는 값**이다.

① ``volume.threshold_m`` — 그 체적 계산이 실제로 쓴 노이즈 바닥이다("기준면 대비
   이 값보다 작은 표고차는 변화로 세지 않는다", ``ZoneVolumeDelta``). 이 영역의
   평균 표고 변화량이 그 바닥에 가까우면, 직전 해상도로는 그 변화가 진짜인지
   재구성 오차인지 가를 수 없었다는 뜻이다 — 더 조인 촬영이 필요하다.

   직관과 반대로 보이는 지점이다: **작은 변화일수록 더 좋은 해상도가 필요하다.**
   큰 변화는 이미 뚜렷하므로 더 조여도 얻는 게 없고 비행 시간만 늘어난다.

② ``unmeasurable_ratio`` — 직전 관측이 아예 못 본 비율이다. 이건 해상도 문제가
   아니라 가림·기하 문제라서 고도가 아니라 **겹침**을 올려야 한다. 두 신호가
   서로 다른 레버를 움직이는 것이 이 규칙의 요점이다.

## 임계값 두 개는 정책값이다 — 물리적 증명이 아니다

``DETAIL_ESCALATION_SNR`` 과 ``OVERLAP_ESCALATION_UNMEASURABLE_RATIO`` 는 관측
데이터로 보정된 값이 아니라 **보수적으로 고른 시작점**이다. ADR-KSI-011 D3 가
"측면 간격이 고도×1.5 를 넘을 수 없다는 상한은 물리적 불가능의 증명이 아니라
정책값이다"라고 쓴 것과 정확히 같은 지위다. 실제 현장 데이터가 쌓이면 대표자
결정으로 고친다.

## 이 함수는 계약을 발급하지 않는다

결과는 **초안**이다. 운영자가 위저드에서 그대로 쓰거나 고칠 수 있고, 최종 게이트
(INV-014 고도 상한·INV-015 중복도 하한·계획 커버리지 사전 게이트)는 여전히
``mission_plans.build_mission_plan`` 이 건다. 여기서 하한·상한을 잘라내는 것은
그 게이트를 대신하려는 게 아니라 **사람에게 이미 불가능한 값을 보여주지 않기**
위해서다 — 위저드 마지막 단계에서 422 를 만나지 않게 하는 ADR-KSI-011 원칙과 같다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ksi_mission_planning.camera import (
    MIN_FRONT_OVERLAP,
    MIN_SIDE_OVERLAP,
    CameraSpec,
    compute_gsd_m,
)

if TYPE_CHECKING:
    from ksi_mission_contracts.models import FlightEnvelope

#: 평균 표고 변화량이 노이즈 바닥의 이 배수 미만이면 해상도를 조인다.
#: **정책값이다**(모듈 docstring) — 2.0 은 "신호가 바닥의 두 배는 돼야 그 값을
#: 믿는다"는 보수적 시작점이고, 현장 데이터로 보정될 대상이다.
DETAIL_ESCALATION_SNR = 2.0

#: 직전 관측의 측정 불가 비율이 이 값을 넘으면 겹침을 올린다. **정책값이다.**
OVERLAP_ESCALATION_UNMEASURABLE_RATIO = 0.2

#: 해상도를 조일 때 고도에 곱하는 계수. GSD 는 고도에 선형이므로 0.7 은
#: "지상표본거리를 30% 줄인다"와 같은 말이다. **정책값이다.**
DETAIL_ALTITUDE_FACTOR = 0.7

#: 겹침을 올릴 때 쓰는 값. 하한(0.6/0.5)이 아니라 기본값(0.8/0.7)보다 위다 —
#: 가림이 있는 영역은 기본보다 더 겹쳐야 재구성이 성립한다.
INTENSIVE_FRONT_OVERLAP = 0.85
INTENSIVE_SIDE_OVERLAP = 0.8


class ReobservationGrade(StrEnum):
    """재관측 촬영 등급 3단계 — 두 신호가 각각 다른 레버를 움직인 결과다."""

    #: 직전 매핑과 같은 촬영으로 충분하다.
    STANDARD = "STANDARD"
    #: 해상도를 조인다(고도↓). 변화가 노이즈 바닥에 가까울 때.
    DETAILED = "DETAILED"
    #: 해상도와 겹침을 함께 올린다. 측정 불가 비율이 높을 때(+ 필요하면 해상도도).
    INTENSIVE = "INTENSIVE"


@dataclass(frozen=True, slots=True)
class ChangeSignals:
    """이 영역에 대해 리포트가 싣고 있는 값들 — 전부 ``ChangeRegion`` 에서 온다."""

    area_m2: float
    cut_m3: float
    fill_m3: float
    #: 그 체적 계산이 쓴 노이즈 바닥(``ZoneVolumeDelta.threshold_m``). 0 이면
    #: 신호대잡음을 계산할 수 없다 — 지어내지 않고 ``None`` 을 낸다.
    volume_threshold_m: float
    unmeasurable_ratio: float

    def __post_init__(self) -> None:
        if self.volume_threshold_m < 0.0:
            raise ValueError(f"volume_threshold_m 는 음수일 수 없다: {self.volume_threshold_m}")
        if not (0.0 <= self.unmeasurable_ratio <= 1.0):
            raise ValueError(
                f"unmeasurable_ratio 는 0..1 범위여야 한다: {self.unmeasurable_ratio}"
            )
        if self.cut_m3 < 0.0 or self.fill_m3 < 0.0:
            raise ValueError("cut_m3·fill_m3 는 음수일 수 없다 — ZoneVolumeDelta 부호 규약")


@dataclass(frozen=True, slots=True)
class BaselineCapture:
    """이 영역을 마지막으로 찍은 임무의 촬영 조건 — 재관측의 출발점이다."""

    altitude_m: float
    front_overlap: float
    side_overlap: float
    camera: CameraSpec


@dataclass(frozen=True, slots=True)
class ReobservationCapturePlan:
    """도출 결과 — 값과 **왜 그 값인지**를 함께 들고 다닌다."""

    grade: ReobservationGrade
    altitude_m: float
    front_overlap: float
    side_overlap: float
    gsd_m: float
    baseline_gsd_m: float
    #: 평균 |Δz| / 노이즈 바닥. 바닥이 0 이면 ``None``.
    signal_to_noise: float | None
    #: 사람이 읽는 근거 문장들. **절대 비어 있지 않다** — 근거 없는 자동 판정은
    #: 운영자가 검토할 수 없고, 검토할 수 없는 초안은 승인 단계를 형식으로 만든다.
    rationale: tuple[str, ...]


def derive_reobservation_capture(
    *,
    baseline: BaselineCapture,
    signals: ChangeSignals,
    envelope: FlightEnvelope,
) -> ReobservationCapturePlan:
    """변화 신호에서 재관측 촬영 조건을 도출한다 — 순수 함수.

    Raises:
        ValueError: ``area_m2`` 가 0 이하일 때(평균 표고 변화량이 정의되지 않는다).
    """
    if signals.area_m2 <= 0.0:
        raise ValueError(f"area_m2 는 양수여야 한다: {signals.area_m2}")

    rationale: list[str] = []
    baseline_gsd = compute_gsd_m(baseline.camera, baseline.altitude_m)

    # 평균 표고 변화량 — cut·fill 둘 다 양수로 실리므로 합이 곧 총 변화량이다
    # (net 은 방향이라 여기서 쓰면 절토와 성토가 서로 상쇄돼 "변화 없음"이 된다).
    mean_abs_dz = (signals.cut_m3 + signals.fill_m3) / signals.area_m2

    snr: float | None
    if signals.volume_threshold_m > 0.0:
        snr = mean_abs_dz / signals.volume_threshold_m
        needs_resolution = snr < DETAIL_ESCALATION_SNR
        if needs_resolution:
            rationale.append(
                f"평균 표고 변화 {mean_abs_dz:.3f}m 가 노이즈 바닥 "
                f"{signals.volume_threshold_m:.3f}m 의 {snr:.1f}배로 "
                f"{DETAIL_ESCALATION_SNR}배 미만 — 직전 해상도로는 확정하기 어렵다"
            )
        else:
            rationale.append(
                f"평균 표고 변화 {mean_abs_dz:.3f}m 가 노이즈 바닥의 {snr:.1f}배 — "
                "직전 촬영 조건으로 확인 가능하다"
            )
    else:
        snr = None
        needs_resolution = False
        rationale.append(
            "노이즈 바닥(threshold)이 0 이라 신호대잡음을 계산할 수 없다 — "
            "해상도를 조일 근거가 없어 직전 조건을 유지한다"
        )

    needs_overlap = signals.unmeasurable_ratio > OVERLAP_ESCALATION_UNMEASURABLE_RATIO
    if needs_overlap:
        rationale.append(
            f"직전 관측의 측정 불가 비율 {signals.unmeasurable_ratio:.0%} 가 "
            f"{OVERLAP_ESCALATION_UNMEASURABLE_RATIO:.0%} 를 넘는다 — "
            "가림·기하 문제라 겹침을 올린다"
        )

    if needs_overlap:
        grade = ReobservationGrade.INTENSIVE
    elif needs_resolution:
        grade = ReobservationGrade.DETAILED
    else:
        grade = ReobservationGrade.STANDARD

    altitude = baseline.altitude_m
    if grade is not ReobservationGrade.STANDARD:
        altitude = baseline.altitude_m * DETAIL_ALTITUDE_FACTOR

    front = baseline.front_overlap
    side = baseline.side_overlap
    if grade is ReobservationGrade.INTENSIVE:
        front = max(front, INTENSIVE_FRONT_OVERLAP)
        side = max(side, INTENSIVE_SIDE_OVERLAP)

    # --- 클램프. 사람에게 이미 불가능한 값을 보여주지 않기 위한 것이지
    #     mission_plans 의 게이트를 대신하려는 게 아니다(모듈 docstring).
    if altitude < envelope.min_altitude_m:
        rationale.append(
            f"도출 고도 {altitude:.1f}m 가 비행 봉투 하한 "
            f"{envelope.min_altitude_m:.1f}m 아래라 하한으로 잘라냈다 — "
            "이 영역에서는 원하는 해상도에 도달하지 못한다"
        )
        altitude = envelope.min_altitude_m
    if altitude > envelope.max_altitude_m:
        # 이 도출은 고도를 낮추기만 하므로 정상 경로에서는 발생하지 않는다.
        # 그래도 검사한다 — 검사하지 않는 상한은 상한이 아니다(INV-014).
        rationale.append(
            f"도출 고도가 비행 봉투 상한 {envelope.max_altitude_m:.1f}m 를 넘어 잘라냈다"
        )
        altitude = envelope.max_altitude_m

    if front < MIN_FRONT_OVERLAP:
        rationale.append(f"전방 중복도를 하한 {MIN_FRONT_OVERLAP} 로 올렸다(INV-015)")
        front = MIN_FRONT_OVERLAP
    if side < MIN_SIDE_OVERLAP:
        rationale.append(f"측면 중복도를 하한 {MIN_SIDE_OVERLAP} 로 올렸다(INV-015)")
        side = MIN_SIDE_OVERLAP

    return ReobservationCapturePlan(
        grade=grade,
        altitude_m=altitude,
        front_overlap=front,
        side_overlap=side,
        gsd_m=compute_gsd_m(baseline.camera, altitude),
        baseline_gsd_m=baseline_gsd,
        signal_to_noise=snr,
        rationale=tuple(rationale),
    )


__all__ = [
    "DETAIL_ALTITUDE_FACTOR",
    "DETAIL_ESCALATION_SNR",
    "INTENSIVE_FRONT_OVERLAP",
    "INTENSIVE_SIDE_OVERLAP",
    "OVERLAP_ESCALATION_UNMEASURABLE_RATIO",
    "BaselineCapture",
    "ChangeSignals",
    "ReobservationCapturePlan",
    "ReobservationGrade",
    "derive_reobservation_capture",
]
