# AOL-2 분석 기반 재관측 — 계획 심화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**선행 조건:** `docs/superpowers/plans/2026-08-15-aol-1-mapping-autonomy.md` 완료. 이 계획은 그 계획이 만든 `SpatialModelStatus`·`MissionExecutionStatus` 를 소비한다.

**Goal:** 변화 영역에서 재관측 임무를 만들 때, 서버가 **변화 정도에 맞는 촬영 계획까지** 도출해 초안에 실어 보내고, 그 임무가 어느 분석 결과에서 나왔는지 계보로 남긴다. 운영자가 고도·중복도를 다시 판단해 입력하는 단계를 없앤다.

**Architecture:** 촬영 밀도 도출은 **순수 함수**로 `ksi_mission_planning` 에 둔다 — Core 는 그 함수를 부르기만 하고 규칙을 갖지 않는다. 판정의 근거는 서버가 지어낸 상수가 아니라 **리포트 자신이 싣고 있는 값**(`volume.threshold_m` — 그 체적 계산이 실제로 쓴 노이즈 바닥, `unmeasurable_ratio` — 직전 관측이 못 본 비율)이다. 계보는 새 원장을 만들지 않고 이미 영속되는 `MissionRecord.plan_request` 에 얹는다.

**Tech Stack:** Python 3.12 (uv workspace), Pydantic v2, pytest, Next.js 16 / React 19 / TypeScript / vitest

**Spec:** `docs/architecture/ADR-KSI-019-autonomous-observation-loop.md` (§3 D1 재관측 루프, §4 G5, §5 6번)

---

## Global Constraints

계획 1 의 Global Constraints 를 전부 그대로 상속한다. 이 계획에 추가되는 것:

- **INV-014**: `maxAltitudeM` 은 150m(항공안전법 일반 비행제한 고도)를 넘을 수 없다. 이 계획의 도출은 고도를 **낮추기만** 하지만, 상한 검사를 생략하지 않는다.
- **INV-015**: 매핑 계열 임무는 진행방향 촬영 간격 없이 발급되지 않고, 중복도 하한(전방 0.6 · 측면 0.5)이 강제된다(`ksi_mission_planning.camera` 의 `MIN_FRONT_OVERLAP` · `MIN_SIDE_OVERLAP`). 도출 결과가 하한을 밑돌면 하한으로 잘라내고 **그 사실을 근거 목록에 남긴다**.
- **정책값과 물리 증명을 구분한다**: 이 계획이 도입하는 임계값 두 개는 정책값이다. ADR-KSI-011 D3 가 "고도×1.5 상한은 물리적 불가능의 증명이 아니라 정책값이다"라고 쓴 것과 같은 자리에 같은 문장을 남긴다.
- **ADR-KSI-019 D3 재확인**: 이 계획은 재관측 경로에 공간모델을 쓰지만, 그건 **AOL-2 경로**다. 최초 매핑 경로(AOL-1)는 여전히 공간모델 없이 성립해야 하며 `tests/contract/test_anti_circularity_gate.py` 가 그것을 지킨다 — 이 계획의 어느 Task 도 그 파일을 수정하지 않는다.

---

## File Structure

**신규 생성**

| 파일 | 책임 |
|---|---|
| `packages/mission-planning/src/ksi_mission_planning/reobservation.py` | 변화 신호 → 재관측 촬영 계획 **순수 도출** |
| `tests/contract/test_reobservation_capture.py` | 도출 규칙·경계·클램프 |
| `tests/e2e/test_aol2_reobservation.py` | AOL-2 소프트웨어 종단 1회 |
| `apps/dashboard/test/reobservation-preset.test.ts` | 위저드 자동 채움 |

**수정**

| 파일 | 변경 |
|---|---|
| `packages/mission-planning/src/ksi_mission_planning/__init__.py` | 신규 공개 심볼 export |
| `services/core/src/ksi_core/region_extraction_reports.py` | 초안 응답에 촬영 계획 탑재 |
| `services/core/src/ksi_core/mission_plans.py` | `MissionPlanRequest.derived_from` 수용 |
| `services/core/src/ksi_core/mission_records.py` | `derivedFrom` 조회 노출 + 목록 필터 |
| `contracts/api/openapi-core.yaml` | 초안·임무 응답 스키마 갱신 |
| `apps/dashboard/src/lib/core-api/types.ts` · `region-extraction.ts` · `mission-plans.ts` | 타입·클라이언트 |
| `apps/dashboard/src/app/sites/[siteId]/surveys/new/page.tsx` 및 위저드 컴포넌트 | 촬영 계획 자동 채움 + 근거 표시 |

---

## Task 1: 변화 신호 → 재관측 촬영 계획 순수 도출

**Files:**
- Create: `packages/mission-planning/src/ksi_mission_planning/reobservation.py`
- Modify: `packages/mission-planning/src/ksi_mission_planning/__init__.py`
- Test: `tests/contract/test_reobservation_capture.py`

**Interfaces:**
- Consumes: `ksi_mission_planning.camera` 의 `CameraSpec` · `compute_gsd_m` · `MIN_FRONT_OVERLAP` · `MIN_SIDE_OVERLAP`, `ksi_mission_contracts.models.FlightEnvelope`
- Produces:
  - `class ReobservationGrade(StrEnum)` — `STANDARD` · `DETAILED` · `INTENSIVE`
  - `@dataclass(frozen=True, slots=True) class ChangeSignals` — `area_m2: float`, `cut_m3: float`, `fill_m3: float`, `volume_threshold_m: float`, `unmeasurable_ratio: float`
  - `@dataclass(frozen=True, slots=True) class BaselineCapture` — `altitude_m: float`, `front_overlap: float`, `side_overlap: float`, `camera: CameraSpec`
  - `@dataclass(frozen=True, slots=True) class ReobservationCapturePlan` — `grade`, `altitude_m`, `front_overlap`, `side_overlap`, `gsd_m`, `baseline_gsd_m`, `signal_to_noise: float | None`, `rationale: tuple[str, ...]`
  - `def derive_reobservation_capture(*, baseline: BaselineCapture, signals: ChangeSignals, envelope: FlightEnvelope) -> ReobservationCapturePlan`
  - 상수 `DETAIL_ESCALATION_SNR = 2.0` · `OVERLAP_ESCALATION_UNMEASURABLE_RATIO = 0.2` · `DETAIL_ALTITUDE_FACTOR = 0.7` · `INTENSIVE_FRONT_OVERLAP = 0.85` · `INTENSIVE_SIDE_OVERLAP = 0.8`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/contract/test_reobservation_capture.py`:

```python
"""변화 정도 → 재관측 촬영 계획 도출 (ADR-KSI-019 G5).

이 파일이 지키는 것은 "좋은 밀도"가 아니라 **규칙이 근거를 갖는가**다 — 임계값이
서버가 지어낸 숫자가 아니라 리포트가 싣고 있는 값에서 나오는가, 하한을 넘지
않는가, 왜 그 등급이 나왔는지가 결과에 남는가.
"""

from __future__ import annotations

import pytest
from ksi_mission_planning.camera import MIN_FRONT_OVERLAP, MIN_SIDE_OVERLAP
from ksi_mission_planning.reobservation import (
    DETAIL_ALTITUDE_FACTOR,
    ChangeSignals,
    ReobservationGrade,
    derive_reobservation_capture,
)


def test_large_change_keeps_the_baseline_capture(baseline, envelope) -> None:
    """노이즈 바닥보다 충분히 큰 변화는 직전과 같은 촬영으로 확인된다.

    변화가 이미 뚜렷하면 더 조여서 얻을 게 없다 — 비행 시간만 늘어난다.
    """
    signals = ChangeSignals(
        area_m2=1000.0, cut_m3=0.0, fill_m3=900.0,  # 평균 |Δz| = 0.9m
        volume_threshold_m=0.05, unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(baseline=baseline, signals=signals, envelope=envelope)

    assert plan.grade is ReobservationGrade.STANDARD
    assert plan.altitude_m == baseline.altitude_m
    assert plan.front_overlap == baseline.front_overlap


def test_change_near_the_noise_floor_escalates_resolution(baseline, envelope) -> None:
    """[핵심] 노이즈 바닥에 가까운 변화는 더 조여야 확인된다.

    직관과 반대로 보이지만 맞다 — 작은 변화일수록 그것이 진짜인지 재구성 오차인지
    가르려면 더 나은 해상도가 필요하다. 기준은 서버가 지어낸 값이 아니라 그 체적
    계산이 실제로 쓴 ``threshold_m`` 이다.
    """
    signals = ChangeSignals(
        area_m2=1000.0, cut_m3=30.0, fill_m3=30.0,  # 평균 |Δz| = 0.06m
        volume_threshold_m=0.05, unmeasurable_ratio=0.0,  # SNR = 1.2 < 2.0
    )

    plan = derive_reobservation_capture(baseline=baseline, signals=signals, envelope=envelope)

    assert plan.grade is ReobservationGrade.DETAILED
    assert plan.altitude_m == pytest.approx(baseline.altitude_m * DETAIL_ALTITUDE_FACTOR)
    assert plan.gsd_m < plan.baseline_gsd_m
    assert plan.front_overlap == baseline.front_overlap  # 해상도 문제이지 겹침 문제가 아니다


def test_high_unmeasurable_ratio_escalates_overlap(baseline, envelope) -> None:
    """직전 관측이 못 본 비율이 높으면 겹침을 올린다 — 가림·기하 문제다."""
    signals = ChangeSignals(
        area_m2=1000.0, cut_m3=0.0, fill_m3=900.0,
        volume_threshold_m=0.05, unmeasurable_ratio=0.35,
    )

    plan = derive_reobservation_capture(baseline=baseline, signals=signals, envelope=envelope)

    assert plan.grade is ReobservationGrade.INTENSIVE
    assert plan.front_overlap > baseline.front_overlap
    assert plan.side_overlap > baseline.side_overlap


def test_both_signals_produce_intensive(baseline, envelope) -> None:
    signals = ChangeSignals(
        area_m2=1000.0, cut_m3=30.0, fill_m3=30.0,
        volume_threshold_m=0.05, unmeasurable_ratio=0.35,
    )

    plan = derive_reobservation_capture(baseline=baseline, signals=signals, envelope=envelope)

    assert plan.grade is ReobservationGrade.INTENSIVE
    assert plan.altitude_m < baseline.altitude_m
    assert plan.front_overlap > baseline.front_overlap


def test_zero_threshold_does_not_escalate_and_says_why(baseline, envelope) -> None:
    """[핵심] 노이즈 바닥이 0 이면 신호대잡음을 계산할 수 없다 — 지어내지 않는다."""
    signals = ChangeSignals(
        area_m2=1000.0, cut_m3=1.0, fill_m3=1.0,
        volume_threshold_m=0.0, unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(baseline=baseline, signals=signals, envelope=envelope)

    assert plan.signal_to_noise is None
    assert plan.grade is ReobservationGrade.STANDARD
    assert any("노이즈 바닥" in r for r in plan.rationale)


def test_altitude_is_clamped_to_the_envelope_minimum(baseline_low, envelope_tight) -> None:
    """[핵심] 도출이 비행 봉투 아래로 내려가지 않는다 — 그리고 잘렸다고 말한다."""
    signals = ChangeSignals(
        area_m2=1000.0, cut_m3=30.0, fill_m3=30.0,
        volume_threshold_m=0.05, unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(
        baseline=baseline_low, signals=signals, envelope=envelope_tight
    )

    assert plan.altitude_m == envelope_tight.min_altitude_m
    assert any("봉투 하한" in r for r in plan.rationale)


def test_overlap_never_falls_below_the_floor(baseline_thin_overlap, envelope) -> None:
    """직전이 하한 근처였어도 결과는 하한 위다(INV-015)."""
    signals = ChangeSignals(
        area_m2=1000.0, cut_m3=0.0, fill_m3=900.0,
        volume_threshold_m=0.05, unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(
        baseline=baseline_thin_overlap, signals=signals, envelope=envelope
    )

    assert plan.front_overlap >= MIN_FRONT_OVERLAP
    assert plan.side_overlap >= MIN_SIDE_OVERLAP


def test_result_never_exceeds_the_regulatory_ceiling(baseline_high, envelope) -> None:
    """이 도출은 고도를 낮추기만 하지만, 상한 검사를 생략하지 않는다(INV-014)."""
    signals = ChangeSignals(
        area_m2=1000.0, cut_m3=0.0, fill_m3=900.0,
        volume_threshold_m=0.05, unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(baseline=baseline_high, signals=signals, envelope=envelope)

    assert plan.altitude_m <= envelope.max_altitude_m
    assert plan.altitude_m <= 150.0


def test_rationale_is_never_empty(baseline, envelope) -> None:
    """왜 그 등급인지가 항상 결과에 남는다 — 근거 없는 자동 판정은 쓰지 않는다."""
    signals = ChangeSignals(
        area_m2=1000.0, cut_m3=0.0, fill_m3=900.0,
        volume_threshold_m=0.05, unmeasurable_ratio=0.0,
    )

    plan = derive_reobservation_capture(baseline=baseline, signals=signals, envelope=envelope)

    assert plan.rationale


def test_non_positive_area_is_refused(baseline, envelope) -> None:
    with pytest.raises(ValueError, match="area_m2"):
        derive_reobservation_capture(
            baseline=baseline,
            signals=ChangeSignals(
                area_m2=0.0, cut_m3=1.0, fill_m3=1.0,
                volume_threshold_m=0.05, unmeasurable_ratio=0.0,
            ),
            envelope=envelope,
        )
```

fixture:

```python
@pytest.fixture
def camera():
    from ksi_mission_planning.camera import CameraSpec

    # DJI M4D 광각 계열에 가까운 값 — 이 테스트가 검증하는 것은 규칙이지
    # 특정 기체의 스펙 정확도가 아니다(스펙 정본은 장비 레지스트리 소관).
    return CameraSpec(
        sensor_width_mm=17.3, focal_length_mm=12.29, image_width_px=5280, image_height_px=3956
    )


@pytest.fixture
def baseline(camera):
    from ksi_mission_planning.reobservation import BaselineCapture

    return BaselineCapture(
        altitude_m=80.0, front_overlap=0.8, side_overlap=0.7, camera=camera
    )


@pytest.fixture
def envelope():
    from ksi_mission_contracts.models import FlightEnvelope

    return FlightEnvelope(
        allowedVolumes=["site-a"], excludedVolumes=[],
        minAltitudeM=20.0, maxAltitudeM=120.0,
        altitudeReference="relativeToStartPoint",
    )
```

`baseline_low`(고도 25m) · `envelope_tight`(min 20m) · `baseline_thin_overlap`(front 0.62 / side 0.52) · `baseline_high`(고도 145m, envelope max 150m) 도 같은 모양으로 만든다.

- [ ] **Step 2: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_reobservation_capture.py -v`
기대: `ModuleNotFoundError: No module named 'ksi_mission_planning.reobservation'`

- [ ] **Step 3: 도출 모듈을 만든다**

`packages/mission-planning/src/ksi_mission_planning/reobservation.py`:

```python
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

    if signals.volume_threshold_m > 0.0:
        snr: float | None = mean_abs_dz / signals.volume_threshold_m
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
```

`packages/mission-planning/src/ksi_mission_planning/__init__.py` 에 위 공개 심볼을 export 한다(그 파일의 기존 관용구대로).

- [ ] **Step 4: 통과를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_reobservation_capture.py -v`
기대: 10 passed

- [ ] **Step 5: 정적 검사와 커밋**

```bash
uv run ruff check packages/mission-planning tests/contract/test_reobservation_capture.py
uv run ruff format packages/mission-planning/src/ksi_mission_planning/reobservation.py tests/contract/test_reobservation_capture.py
uv run mypy
git add packages/mission-planning tests/contract/test_reobservation_capture.py
git commit -m "feat(mission-planning): derive reobservation capture from change signals

판정 근거를 서버가 지어내지 않는다 — 그 체적 계산이 쓴 노이즈 바닥과 직전
관측의 측정 불가 비율만 본다. 두 신호가 각각 해상도와 겹침을 움직인다.
임계값 두 개는 정책값이며 물리적 증명이 아니라고 명시한다(ADR-KSI-011 D3 선례)."
```

---

## Task 2: 재관측 초안에 촬영 계획 탑재

**Files:**
- Modify: `services/core/src/ksi_core/region_extraction_reports.py`
- Modify: `contracts/api/openapi-core.yaml`
- Test: `tests/contract/test_region_extraction_end_to_end.py` (기존 파일에 추가)

**Interfaces:**
- Consumes: Task 1 의 `derive_reobservation_capture`, `MissionStore.get(mission_id).plan_request`
- Produces: `SpatialRefreshDraftResponse` 에 필드 추가 —
  - `capture_grade: str | None`
  - `capture_altitude_m: float | None`
  - `capture_front_overlap: float | None`
  - `capture_side_overlap: float | None`
  - `capture_gsd_m: float | None`
  - `baseline_gsd_m: float | None`
  - `capture_signal_to_noise: float | None`
  - `capture_rationale: list[str]` (기본 `[]`)
  - `capture_unavailable_reason: str | None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_spatial_refresh_draft_carries_a_capture_plan(api_client, recorded_region_report) -> None:
    """초안이 AOI 만 주고 끝나지 않는다 — 촬영 조건까지 함께 준다."""
    body = api_client.get_json(_draft_url(recorded_region_report, region_id="r-1"))

    assert body["verdict"] == "DRAFT_READY"
    assert body["aoi"] is not None
    assert body["captureGrade"] in {"STANDARD", "DETAILED", "INTENSIVE"}
    assert body["captureAltitudeM"] > 0
    assert body["captureRationale"], "근거 없는 자동 초안은 검토할 수 없다"


def test_draft_without_a_baseline_says_why_instead_of_guessing(
    api_client, region_report_from_contract_only_mission
) -> None:
    """[핵심] 직전 촬영 조건을 모르면 지어내지 않는다.

    계약 단독 발급(``artifactKind="contract"``)에는 ``planRequest`` 가 없어 고도·
    중복도·카메라를 알 수 없다. 그때 기본값을 꽂으면 그 값이 어디서 왔는지 아무도
    모르는 채로 비행 계획이 된다 — ``ChangeRegion.aoi_draft_unavailable_reason``
    이 hull 실패를 다루는 방식과 같은 관용구로 사유를 낸다.
    """
    body = api_client.get_json(_draft_url(region_report_from_contract_only_mission, "r-1"))

    assert body["aoi"] is not None  # AOI 는 여전히 나온다
    assert body["captureGrade"] is None
    assert body["captureUnavailableReason"] == "BASELINE_CAPTURE_UNKNOWN"
    assert body["captureRationale"] == []


def test_draft_capture_never_exceeds_the_source_mission_envelope(
    api_client, recorded_region_report
) -> None:
    """초안 고도가 그 임무 계약의 비행 봉투 안이다."""
    body = api_client.get_json(_draft_url(recorded_region_report, "r-1"))
    envelope = api_client.mission_envelope(recorded_region_report.mission_id)

    assert envelope["minAltitudeM"] <= body["captureAltitudeM"] <= envelope["maxAltitudeM"]


def test_hull_failure_still_takes_precedence(api_client, region_report_with_failed_hull) -> None:
    """hull 이 없으면 409 다 — 촬영 계획을 붙인다고 그 판정이 바뀌지 않는다."""
    assert api_client.get(_draft_url(region_report_with_failed_hull, "r-1")).status_code == 409
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_region_extraction_end_to_end.py -k capture -v`
기대: `KeyError: 'captureGrade'`

- [ ] **Step 3: baseline 추출 헬퍼를 만든다**

`region_extraction_reports.py` 에:

```python
#: 직전 촬영 조건을 알 수 없을 때의 사유 코드. ``ChangeRegion.
#: aoi_draft_unavailable_reason`` 과 같은 관용구다 — 모르는 값을 기본값으로
#: 채우지 않고 "모른다"를 코드로 낸다.
_BASELINE_UNKNOWN = "BASELINE_CAPTURE_UNKNOWN"


def _baseline_capture_of(record: MissionRecord) -> BaselineCapture | None:
    """그 임무의 발급 요청에서 촬영 조건을 읽는다 — 없으면 ``None``.

    ``plan_request`` 는 짝 발급(``artifactKind="pair"``)에만 있다. 계약 단독
    발급은 경로가 없으므로 고도·카메라도 없다.
    """
    plan_request = record.plan_request
    if not isinstance(plan_request, dict):
        return None
    route = plan_request.get("route")
    camera = (route or {}).get("camera")
    if not isinstance(route, dict) or not isinstance(camera, dict):
        return None
    try:
        return BaselineCapture(
            altitude_m=float(route["altitudeM"]),
            front_overlap=float(camera.get("frontOverlap", DEFAULT_FRONT_OVERLAP)),
            side_overlap=float(camera.get("sideOverlap", DEFAULT_SIDE_OVERLAP)),
            camera=CameraSpec(
                sensor_width_mm=float(camera["sensorWidthMm"]),
                focal_length_mm=float(camera["focalLengthMm"]),
                image_width_px=int(camera["imageWidthPx"]),
                image_height_px=int(camera["imageHeightPx"]),
            ),
        )
    except (KeyError, TypeError, ValueError, CameraSpecError):
        # 요청이 카메라를 직접 지정하지 않고 간격을 직접 준 경로다(INV-015 의
        # "직접 지정 경로"). GSD 를 계산할 근거가 없으므로 모른다고 답한다.
        return None
```

`FlightEnvelope` 는 `record.contract["flightEnvelope"]` 에서 읽는다(서명된 계약 전문이 무변형 보존돼 있다 — `mission_records.py` "contract 필드는 무변형 보존").

- [ ] **Step 4: 초안 라우트에 붙인다**

`get_spatial_refresh_draft` 에서 AOI 를 만든 뒤:

```python
        capture: ReobservationCapturePlan | None = None
        capture_unavailable: str | None = None
        mission = mission_store.get(mission_id)
        baseline = _baseline_capture_of(mission) if mission is not None else None
        if baseline is None:
            capture_unavailable = _BASELINE_UNKNOWN
        else:
            try:
                capture = derive_reobservation_capture(
                    baseline=baseline,
                    signals=ChangeSignals(
                        area_m2=region.volume.area_m2,
                        cut_m3=region.volume.cut_m3,
                        fill_m3=region.volume.fill_m3,
                        volume_threshold_m=region.volume.threshold_m,
                        unmeasurable_ratio=region.unmeasurable_ratio,
                    ),
                    envelope=FlightEnvelope.model_validate(
                        mission.contract["flightEnvelope"]
                    ),
                )
            except (ValueError, ValidationError) as exc:
                # 도출 실패가 AOI 초안까지 죽이지 않는다 — AOI 는 그 자체로 유용하다.
                capture_unavailable = "CAPTURE_DERIVATION_FAILED"
                logger.warning("재관측 촬영 계획 도출 실패 mission=%s: %s", mission_id, exc)
```

`build_region_extraction_reports_router` 시그니처에 `mission_store: MissionStore` 를 추가한다(이미 store 가 `mission_store` 를 들고 있으면 그걸 쓴다 — Step 3 전에 파일에서 확인).

- [ ] **Step 5: openapi 를 갱신한다**

`/v1/missions/{mission_id}/region-extraction/{change_region_set_id}/regions/{region_id}/spatial-refresh-draft` 응답 스키마에 새 필드 9개를 추가한다.

- [ ] **Step 6: 통과를 확인한다**

Run:
```bash
ulimit -n 8192 && uv run pytest tests/contract/test_region_extraction_end_to_end.py tests/contract/test_change_region_report.py tests/contract/test_api_contract_sync.py -q
```

- [ ] **Step 7: 커밋**

```bash
git add services/core/src/ksi_core/region_extraction_reports.py contracts/api/openapi-core.yaml tests/contract/test_region_extraction_end_to_end.py
git commit -m "feat(core): attach a derived capture plan to spatial-refresh drafts

초안이 AOI 에서 멈추지 않고 고도·중복도·GSD 와 그 근거까지 준다. 직전 촬영
조건을 모르면 기본값을 꽂지 않고 BASELINE_CAPTURE_UNKNOWN 으로 답한다."
```

---

## Task 3: 재관측 임무의 계보

**Files:**
- Modify: `services/core/src/ksi_core/mission_plans.py`, `services/core/src/ksi_core/mission_records.py`
- Modify: `contracts/api/openapi-core.yaml`
- Test: `tests/contract/test_mission_plans.py` (기존 파일에 추가)

**Interfaces:**
- Consumes: 기존 `MissionRecord.plan_request` 영속 경로
- Produces:
  - `class MissionDerivation(CamelModel)` — `sourceMissionId: str`, `changeRegionSetId: str`, `regionId: str`, `captureGrade: str | None`
  - `MissionPlanRequest.derived_from: MissionDerivation | None = None`
  - `MissionRecordResponse.derived_from` 노출
  - `GET /v1/missions?derivedFromRegion={regionId}` 필터

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_pair_issuance_records_the_change_region_it_came_from(api_client) -> None:
    """[핵심] 재관측 임무가 어느 분석 결과에서 나왔는지 원장이 안다.

    없으면 "이 비행은 왜 했나"에 원장이 답하지 못하고, 폐루프가 사람의 기억에
    의존한다.
    """
    body = api_client.issue_pair(
        mission_id="m-2",
        mission_type="SPATIAL_REFRESH",
        derived_from={
            "sourceMissionId": "m-1",
            "changeRegionSetId": "crs-1",
            "regionId": "r-1",
            "captureGrade": "DETAILED",
        },
    )

    assert body["missionId"] == "m-2"
    detail = api_client.get_json("/v1/missions/m-2")
    assert detail["derivedFrom"]["sourceMissionId"] == "m-1"
    assert detail["derivedFrom"]["regionId"] == "r-1"


def test_derivation_is_optional(api_client) -> None:
    """최초 매핑 임무는 계보가 없다 — 없다고 발급을 막지 않는다."""
    api_client.issue_pair(mission_id="m-1", mission_type="BASELINE_MAPPING")

    assert api_client.get_json("/v1/missions/m-1")["derivedFrom"] is None


def test_derivation_does_not_enter_the_signed_contract(api_client) -> None:
    """[핵심] 계보는 운영 메타데이터이지 서명 계약의 일부가 아니다.

    ``assigned_device_id``·``kmz_sha256`` 과 같은 지위다. 계약에 넣으면 Manifold 가
    받는 신뢰 경계 안으로 서버측 분석 산출물이 들어가고, 계약 스키마
    (mission-contract.v1.2)도 바뀐다.
    """
    api_client.issue_pair(
        mission_id="m-2",
        mission_type="SPATIAL_REFRESH",
        derived_from={"sourceMissionId": "m-1", "changeRegionSetId": "crs-1", "regionId": "r-1"},
    )

    contract = api_client.get_json("/v1/missions/m-2/contract")
    assert "derivedFrom" not in contract


def test_missions_can_be_filtered_by_source_region(api_client) -> None:
    api_client.issue_pair(mission_id="m-2", mission_type="SPATIAL_REFRESH",
                          derived_from={"sourceMissionId": "m-1",
                                        "changeRegionSetId": "crs-1", "regionId": "r-1"})
    api_client.issue_pair(mission_id="m-3", mission_type="BASELINE_MAPPING")

    listed = api_client.get_json("/v1/missions?derivedFromRegion=r-1")

    assert [m["missionId"] for m in listed] == ["m-2"]


def test_idempotent_reissue_keeps_the_same_derivation(api_client) -> None:
    """같은 요청 재전송이 계보를 지우거나 바꾸지 않는다(멱등 재발급 경로)."""
    request = _pair_request(mission_id="m-2", derived_from={"sourceMissionId": "m-1",
                            "changeRegionSetId": "crs-1", "regionId": "r-1"})

    api_client.post_json("/v1/missions/plans", request)
    api_client.post_json("/v1/missions/plans", request)

    assert api_client.get_json("/v1/missions/m-2")["derivedFrom"]["regionId"] == "r-1"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_mission_plans.py -k derived -v`
기대: `extra="forbid"` 로 422 (요청 모델이 `derivedFrom` 을 모른다)

- [ ] **Step 3: 요청 모델에 필드를 추가한다**

`mission_plans.py` 에:

```python
class MissionDerivation(CamelModel):
    """이 임무가 어느 분석 결과에서 나왔는가 — **서명 계약의 일부가 아니다.**

    ``assigned_device_id``·``kmz_sha256`` 과 같은 지위의 운영 메타데이터다. 계약에
    넣으면 Manifold 가 받는 신뢰 경계 안으로 서버측 분석 산출물이 들어가고,
    mission-contract 스키마 자체가 바뀐다 — 계보를 아는 것은 Core 의 일이지 기체의
    일이 아니다.

    값의 실재를 발급 시점에 대조하지 **않는다**: 변화영역 리포트는 회전·보관 정책을
    따로 타므로 나중에 없을 수 있고, 그때 계보 기록이 무효가 되면 안 된다
    (``coverage_reports`` 가 재생 시 ⑤임무 대조를 다시 하지 않는 것과 같은 이유).
    """

    source_mission_id: str = Field(min_length=1)
    change_region_set_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    #: 초안이 제안한 등급. 운영자가 값을 고쳐도 이 필드는 "무엇을 제안받았나"로 남는다.
    capture_grade: str | None = None
```

`MissionPlanRequest` 에 `derived_from: MissionDerivation | None = None` 을 추가한다.

`plan_request` 는 요청 전문을 그대로 영속하므로 **추가 저장 코드가 필요 없다** — 이 필드가 자동으로 원장에 남는다. 그 사실을 `MissionPlanRequest` docstring 에 한 줄로 적는다.

- [ ] **Step 4: 조회 노출과 필터를 만든다**

`mission_records.py` 의 `MissionRecordResponse` 에 `derived_from: dict[str, Any] | None = None` 을 추가하고, `_to_response` 에서 `record.plan_request` 에서 꺼낸다:

```python
def _derivation_of(record: MissionRecord) -> dict[str, Any] | None:
    """발급 요청에 실려 영속된 계보 — 계약이 아니라 요청에서 읽는다."""
    plan_request = record.plan_request
    if not isinstance(plan_request, dict):
        return None
    derived = plan_request.get("derivedFrom")
    return derived if isinstance(derived, dict) else None
```

목록 라우트에 쿼리 파라미터를 추가한다:

```python
    def list_missions(
        site_id: str | None = Query(default=None, alias="siteId"),
        derived_from_region: str | None = Query(default=None, alias="derivedFromRegion"),
        ...
    ):
```
필터는 `_derivation_of(record) or {}` 의 `regionId` 대조 한 줄이다.

- [ ] **Step 5: openapi 를 갱신한다**

`/v1/missions/plans` 요청 스키마에 `derivedFrom` 을, `/v1/missions` 에 `derivedFromRegion` 쿼리를, `/v1/missions/{mission_id}` 응답에 `derivedFrom` 을 추가한다.

- [ ] **Step 6: 통과를 확인한다**

Run:
```bash
ulimit -n 8192 && uv run pytest tests/contract/test_mission_plans.py tests/contract/test_contract_signing.py tests/contract/test_api_contract_sync.py -q
```
기대: 전부 통과. 특히 서명 계약 테스트가 깨지지 않아야 한다 — 깨지면 계보가 계약에 새어 들어간 것이다.

- [ ] **Step 7: 커밋**

```bash
git add services/core/src/ksi_core/mission_plans.py services/core/src/ksi_core/mission_records.py contracts/api/openapi-core.yaml tests/contract/test_mission_plans.py
git commit -m "feat(core): record which change region a reobservation mission came from

계보는 이미 영속되는 planRequest 에 얹고 새 원장을 만들지 않는다. 서명 계약에는
넣지 않는다 — 계보를 아는 것은 Core 의 일이지 기체의 일이 아니다."
```

---

## Task 4: 위저드 자동 채움과 근거 표시

**Files:**
- Modify: `apps/dashboard/src/lib/core-api/types.ts` · `region-extraction.ts` · `mission-plans.ts` · `surveyEntryPreset.ts`
- Modify: `apps/dashboard/src/app/sites/[siteId]/surveys/new/page.tsx` 및 위저드 컴포넌트
- Test: `apps/dashboard/test/reobservation-preset.test.ts` (신규)

**Interfaces:**
- Consumes: Task 2 의 초안 응답, Task 3 의 `derivedFrom`
- Produces:
  - `export const REOBSERVATION_GRADES = ["STANDARD", "DETAILED", "INTENSIVE"] as const`
  - `resolveReobservationPreset(draft): SurveyPreset | null`
  - 위저드가 고도·중복도를 미리 채우고 근거를 보여준다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`apps/dashboard/test/reobservation-preset.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { resolveReobservationPreset } from "@/lib/core-api/surveyEntryPreset";

describe("재관측 위저드 자동 채움", () => {
  it("초안이 촬영 조건을 주면 고도와 중복도를 미리 채운다", () => {
    const preset = resolveReobservationPreset({
      aoi: { type: "Polygon", coordinates: [] },
      captureGrade: "DETAILED",
      captureAltitudeM: 56,
      captureFrontOverlap: 0.8,
      captureSideOverlap: 0.7,
      captureRationale: ["평균 표고 변화가 노이즈 바닥의 1.2배"],
      captureUnavailableReason: null,
    });

    expect(preset).toMatchObject({
      missionType: "SPATIAL_REFRESH",
      altitudeM: 56,
      frontOverlap: 0.8,
      sideOverlap: 0.7,
    });
    expect(preset?.rationale).toHaveLength(1);
  });

  it("촬영 조건을 모르면 값을 지어내지 않고 사유만 넘긴다", () => {
    const preset = resolveReobservationPreset({
      aoi: { type: "Polygon", coordinates: [] },
      captureGrade: null,
      captureAltitudeM: null,
      captureFrontOverlap: null,
      captureSideOverlap: null,
      captureRationale: [],
      captureUnavailableReason: "BASELINE_CAPTURE_UNKNOWN",
    });

    expect(preset?.altitudeM).toBeNull();
    expect(preset?.unavailableReason).toBe("BASELINE_CAPTURE_UNKNOWN");
  });

  it("AOI 가 없으면 프리셋을 만들지 않는다", () => {
    expect(
      resolveReobservationPreset({
        aoi: null,
        captureGrade: null,
        captureAltitudeM: null,
        captureFrontOverlap: null,
        captureSideOverlap: null,
        captureRationale: [],
        captureUnavailableReason: null,
      }),
    ).toBeNull();
  });
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd apps/dashboard && npm run test`
기대: `resolveReobservationPreset` 미정의

- [ ] **Step 3: 프리셋 해석기를 만든다**

`surveyEntryPreset.ts` 에 추가한다. 기존 파일이 이미 "신뢰 경계 밖 입력을 화이트리스트로 좁힌다"는 원칙을 갖고 있으므로, 등급 값도 같은 방식으로 좁힌다:

```typescript
const REOBSERVATION_GRADES = ["STANDARD", "DETAILED", "INTENSIVE"] as const;
```

`captureAltitudeM` 등 숫자 값은 화면 표시·초기값 용도이고, **최종 검증은 서버가 한다**(`mission_plans` 의 봉투·중복도·커버리지 게이트). 그 사실을 함수 주석에 남긴다 — 클라이언트 검증을 서버 게이트의 대체로 읽지 않게.

- [ ] **Step 4: 화면에 붙인다**

변화영역 화면의 "재관측 계획" 진입점이 초안 API 를 부르고, 그 응답을 위저드로 넘긴다(기존 `surveyEntryPreset` 경로 재사용). 위저드의 촬영 단계에:
- 고도·중복도를 미리 채운다
- **근거를 접히지 않은 상태로 보여준다** — 자동 제안을 검토 없이 통과시키지 않기 위해서다
- `captureUnavailableReason` 이 있으면 "직전 촬영 조건을 알 수 없어 값을 제안하지 못했습니다" 를 그 자리에 낸다(빈 칸을 이유 없이 두지 않는다)
- 운영자가 값을 고치면 제안값과 다르다는 표시를 남긴다(제안이 사실처럼 굳지 않게)

발급 시 `derivedFrom` 을 함께 보낸다.

- [ ] **Step 5: 라벨을 한국어 일상어로 쓴다**

| 등급 | 라벨 | 설명 |
|---|---|---|
| `STANDARD` | 직전과 동일 | 변화가 뚜렷해서 지난번과 같은 조건으로 확인할 수 있습니다 |
| `DETAILED` | 더 자세히 | 변화가 작아서 더 낮게 날아 더 선명하게 찍습니다 |
| `INTENSIVE` | 자세히 + 촘촘히 | 지난번에 못 본 부분이 많아 더 낮게, 더 겹쳐서 찍습니다 |

`captureUnavailableReason` 은 코드를 그대로 노출하지 않고 문장으로 바꾼다.

- [ ] **Step 6: 통과를 확인한다**

Run:
```bash
cd apps/dashboard && npm run test && npm run lint && npm run build
```

- [ ] **Step 7: 커밋**

```bash
git add apps/dashboard
git commit -m "feat(dashboard): prefill the reobservation wizard from the derived capture plan

근거를 접지 않고 보여준다 — 자동 제안을 검토 없이 통과시키지 않기 위해서다.
직전 촬영 조건을 모르면 빈 칸에 이유를 적는다."
```

---

## Task 5: AOL-2 소프트웨어 종단 1회

**Files:**
- Create: `tests/e2e/test_aol2_reobservation.py`
- Modify: `docs/architecture/ADR-KSI-019-autonomous-observation-loop.md`

**Interfaces:**
- Consumes: 계획 1 의 종단 fixture(`aol1_client`) + 이 계획의 Task 1~4

- [ ] **Step 1: 종단 테스트를 쓴다**

```python
"""AOL-2 분석 기반 재관측 — 소프트웨어 종단 1회 (ADR-KSI-019 §5 6번).

공간모델 + 분석 → 대상 영역 → 재관측 경로 → 승인 → 재촬영 → 모델 갱신까지
한 번 통과한다. 계획 1 의 AOL-1 루프를 먼저 돌려 첫 epoch 를 만든 뒤 이어간다.

실기는 범위 밖이다 — 계획 1 과 같은 이유이고 같은 대역을 쓴다.
"""


def test_reobservation_loop_completes_and_updates_the_model(aol2_client) -> None:
    c = aol2_client

    # 1. 첫 epoch — 계획 1 의 루프를 그대로 돌린다
    c.run_aol1_loop(site_id="site-a", mission_id="m-1")
    assert c.spatial_model("site-a")["state"] == "FRESH"
    first_epoch = c.spatial_model("site-a")["epochJobId"]

    # 2. 설계 대비 잔량 → 변화 영역 추출
    c.submit_design_conformance("m-1")
    region_set = c.extract_change_regions("m-1")
    assert region_set["regions"], "변화 영역이 하나도 없으면 이 테스트는 공허하다"

    # 3. 재관측 초안 — AOI 와 촬영 조건이 함께 나온다
    draft = c.spatial_refresh_draft("m-1", region_set["changeRegionSetId"], "r-1")
    assert draft["aoi"] is not None
    assert draft["captureGrade"] in {"STANDARD", "DETAILED", "INTENSIVE"}
    assert draft["captureRationale"]

    # 4. 그 초안 그대로 재관측 임무 짝 발급 — 사람이 값을 다시 판단하지 않는다
    plan = c.issue_pair_from_draft(draft, mission_id="m-2", source_mission_id="m-1")
    assert plan["waypointCount"] > 0
    assert c.mission("m-2")["derivedFrom"]["regionId"] == "r-1"

    # 5. 재관측 실행 → 촬영 회수 → 재구성
    c.dispatch_and_fly("m-2", device_id="dev-1")
    c.run_ingest_watch()
    c.worker_run_and_succeed(c.latest_job_id("m-2"))

    # 6. 공간모델이 갱신됐다 — 새 epoch 가 최신이다
    model = c.spatial_model("site-a")
    assert model["state"] == "FRESH"
    assert model["epochJobId"] != first_epoch
    assert model["succeededEpochCount"] == 2


def test_reobservation_did_not_regress_the_site_to_baseline_mapping(aol2_client) -> None:
    """[핵심] 재관측이 현장을 매핑 시작으로 되돌리지 않는다.

    SPATIAL_REFRESH 는 매핑 계열이 아니다(``MAPPING_FROM_SCRATCH_MISSION_TYPES``).
    되돌리면 이미 검증된 모델을 가진 현장이 재관측 한 번에 처음으로 돌아간다.
    """
    c = aol2_client
    c.run_aol1_loop(site_id="site-a", mission_id="m-1")
    c.approve_autonomy("site-a")
    assert c.site_status("site-a") == "PATROL_READY"

    _run_reobservation(c, mission_id="m-2")

    assert c.site_status("site-a") != "BASELINE_MAPPING"


def test_capture_plan_is_a_proposal_not_a_gate(aol2_client) -> None:
    """운영자가 제안과 다른 값으로 발급해도 막히지 않는다 — 서버 게이트만 남는다."""
    c = aol2_client
    c.run_aol1_loop(site_id="site-a", mission_id="m-1")
    c.submit_design_conformance("m-1")
    region_set = c.extract_change_regions("m-1")
    draft = c.spatial_refresh_draft("m-1", region_set["changeRegionSetId"], "r-1")

    plan = c.issue_pair_from_draft(
        draft, mission_id="m-2", source_mission_id="m-1",
        altitude_override=draft["captureAltitudeM"] + 10.0,
    )

    assert plan["waypointCount"] > 0


def test_capture_plan_below_the_overlap_floor_is_still_refused_by_the_server(
    aol2_client,
) -> None:
    """[핵심] 초안이 제안값을 준다고 서버 게이트가 느슨해지지 않는다(INV-015)."""
    c = aol2_client
    c.run_aol1_loop(site_id="site-a", mission_id="m-1")
    c.submit_design_conformance("m-1")
    region_set = c.extract_change_regions("m-1")
    draft = c.spatial_refresh_draft("m-1", region_set["changeRegionSetId"], "r-1")

    response = c.issue_pair_from_draft_raw(
        draft, mission_id="m-2", source_mission_id="m-1", front_overlap_override=0.3
    )

    assert response.status_code == 422
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/e2e/test_aol2_reobservation.py -v`
기대: fixture 미정의로 ERROR

- [ ] **Step 3: fixture 를 만든다**

`aol2_client` 는 계획 1 의 `aol1_client` 를 상속·확장한다(`run_aol1_loop` 헬퍼로 감싼다). `submit_design_conformance`·`extract_change_regions` 는 `tests/contract/test_region_extraction_end_to_end.py` 가 이미 쓰는 관용구를 재사용한다 — 새 대역을 만들지 않는다.

- [ ] **Step 4: 통과를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/e2e/ -v`
기대: 계획 1 의 3건 + 이 계획의 4건 전부 통과

- [ ] **Step 5: 전체 게이트를 돌린다**

Run:
```bash
ulimit -n 8192
uv run pytest -q
uv run ruff check .
uv run mypy
cd apps/dashboard && npm run test && npm run lint && npm run build
```
기대: 전부 통과. 실패가 있으면 **여기서 멈추고 고친다.**

- [ ] **Step 6: ADR 을 갱신한다**

`ADR-KSI-019` §4 의 G5 행과 §5 의 6번에 완료 표시와 근거 테스트 경로를 적는다. 함께 남길 것:
- 이 계획이 도입한 임계값 두 개(`DETAIL_ESCALATION_SNR`·`OVERLAP_ESCALATION_UNMEASURABLE_RATIO`)가 **정책값이며 현장 데이터로 보정될 대상**이라는 사실. 대표자 재검토 항목으로 §4 아래에 한 줄 남긴다.
- 완료 등급은 `Backend Ready` + `Product Ready` 이고 `HIL Proven` 이 아니라는 사실(ADR-KSI-018 완료 판정 규율).
- 남은 것: §5 의 7번(실제 현장 검증)과 8번(G6 AOL-3), 그리고 G3(기체 배포·실기 관문).

- [ ] **Step 7: 커밋**

```bash
git add tests/e2e/test_aol2_reobservation.py docs/architecture/ADR-KSI-019-autonomous-observation-loop.md
git commit -m "test(e2e): complete the AOL-2 reobservation loop in software

공간모델 → 분석 → 대상 영역 → 촬영 조건 도출 → 재관측 발급 → 재촬영 →
모델 갱신까지 한 번 통과한다. 제안은 게이트가 아니고 서버 게이트는 그대로다.

임계값 두 개를 대표자 재검토 항목으로 ADR 에 남긴다."
```

---

## 이 계획이 하지 않는 것 (명시)

- **재관측 임무의 자동 발급**: 초안까지 자동이고 발급은 사람이 승인한다. ADR-KSI-019 D4 가 "비행 시작 전 승인"을 사람의 책임으로 고정했고, 이 계획은 그 경계를 넓히지 않는다. 없앤 것은 승인이 아니라 **값을 다시 판단해 입력하는 단계**다.
- **임계값의 현장 보정**: 두 정책값은 보수적 시작점이고, 보정하려면 실제 현장 데이터가 필요하다(§5 7번 이후).
- **영역별로 다른 촬영 조건의 단일 임무 병합**: 한 비행에서 영역마다 고도를 바꾸는 것은 지형 인지 경로계획(G6/AOL-3)의 영역이다. 이 계획은 영역 하나에 임무 하나다.
- **AOL-3 지형 인지**: ADR-KSI-019 D2 가 순서를 고정했다.
