"""ZoneProgress — 구역 하나의 계획 대비 진척 (M4-C).

## 이것은 **저장되는 사실이 아니라 파생값**이다

원장에 이 모양으로 기록되는 것은 없다. 두 개의 ``DesignConformanceReport`` —
원지형 기준 시점의 것과 최신 시점의 것 — 을 같은 구역끼리 이어 뺀 결과다.
그래서 이 모듈에는 계산이 없고 **뺄셈의 뜻과 그 뜻이 깨지는 조건**만 있다.

.. code-block:: text

    계획(planned)  = 원지형 기준 리포트의 그 구역 잔량
    잔여(remaining) = 최신 리포트의 그 구역 잔량
    완료(done)     = 계획 − 잔여
    진척률          = 완료 / 계획

## 왜 "완료"가 음수일 수 있는가 — 그리고 왜 막지 않는가

되메우기·재시공·붕괴가 있으면 잔여가 계획보다 커져 완료가 음수가 된다. 이것은
계산 오류가 아니라 **현장에서 실제로 일어나는 일**이라, 계약이 막으면 제품이
현장을 틀렸다고 우기게 된다. 그대로 싣고 화면이 그 사실을 말한다.

## 진척률이 ``None`` 인 자리

계획이 0이면 나눌 수 없다. 그 구역에서 그 방향의 작업이 애초에 없었다는 뜻이고
(예: 순수 절토 구역의 성토 계획), ``0%`` 로 적으면 "할 일이 있는데 하나도 안
했다"로 읽힌다 — 정반대의 뜻이다. :attr:`ZoneProgress.basis` 가 그 이유를 사람
말로 적는다(``ZoneVolumeDelta.uncertainty_note`` 가 null 인 이유를 적는 것과 같은
자리 — 숫자 없는 칸을 설명 없이 두지 않는다).

## 이 값이 답하지 않는 것

- **흙 물량만 센다.** 구조물·포장·배관은 이 계산에 없다. 토공 진척률을 공정
  진척률로 읽으면 현장이 실제보다 앞서 보인다.
- **정산·기성 근거가 아니다**(INV-024 연장). 설계면은 측정물이 아니라 검증된
  오차한계가 없고, 그래서 ``DesignConformanceReport`` 의 ``uncertaintyM3`` 도
  항상 ``None`` 이다. 그 한계를 물려받는다.
- **기준 시점이 원지형이라는 보장은 제품이 아니라 사람이 준다.** 이미 일부
  시공된 뒤의 시점을 기준으로 고르면 계획이 그만큼 과소 계상된다 — 그래서
  :attr:`DesignProgress.baseline_computed_at` 이 필수이고 화면이 항상 함께 띄운다.
"""

from __future__ import annotations

import math

from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel

#: 계획이 이 값 이하이면 진척률을 내지 않는다. 0 과 정확히 비교하지 않는 이유는
#: 계획 자체가 셀 단위 합산 float 이라, 실질적으로 없는 물량이 1e-9 m³ 같은 값으로
#: 남을 수 있어서다 — 그걸로 나누면 진척률이 천문학적 숫자가 된다.
PLANNED_EPSILON_M3 = 1e-6


class ZoneProgress(_CamelModel):
    """구역 하나의 계획·완료·잔여·진척률. 절토와 성토를 **합치지 않는다**.

    합계 하나로 뭉개면 "5000 깎고 5000 쌓는" 현장과 "아무것도 안 한" 현장이 같은
    숫자가 된다(net 이 둘 다 0이다). 토공에서 절토와 성토는 다른 작업이고 다른
    장비가 하며 다른 날에 끝난다.
    """

    zone_id: str = Field(min_length=1)
    #: 사람이 읽는 구역 이름 — ``zone_id`` 가 작업구역 id 일 때 그 이름이 실린다.
    #: 등록된 작업구역 없이 즉석 폴리곤으로 낸 리포트면 ``None``.
    zone_name: str | None = None

    planned_cut_m3: float = Field(ge=0.0)
    planned_fill_m3: float = Field(ge=0.0)
    remaining_cut_m3: float = Field(ge=0.0)
    remaining_fill_m3: float = Field(ge=0.0)
    #: 계획 − 잔여. **음수일 수 있다**(되메우기·재시공·붕괴) — 모듈 docstring 참조.
    done_cut_m3: float
    done_fill_m3: float
    #: 완료/계획. 계획이 없으면 ``None``. 1.0 을 넘을 수 있다(계획보다 더 깎은 경우).
    cut_progress_ratio: float | None = None
    fill_progress_ratio: float | None = None
    #: 이 행의 숫자를 어떻게 읽어야 하는가 — 비율이 ``None`` 인 이유, 완료가
    #: 음수인 이유 같은 것. **비워둘 수 없다.**
    basis: str = Field(min_length=1)

    @model_validator(mode="after")
    def _done_matches_planned_minus_remaining(self) -> ZoneProgress:
        """계약이 스스로 볼 수 있는 모순 — 네 값 중 셋이 넷째를 정한다.

        ``ZoneVolumeDelta._net_matches_cut_and_fill`` 과 같은 자리다. 파생값이라
        계산이 한 곳에만 있지만, 그 한 곳이 틀렸을 때 **조용히 그럴듯한 표**가
        나오는 것을 막는다.
        """
        for name, value in (
            ("plannedCutM3", self.planned_cut_m3),
            ("plannedFillM3", self.planned_fill_m3),
            ("remainingCutM3", self.remaining_cut_m3),
            ("remainingFillM3", self.remaining_fill_m3),
            ("doneCutM3", self.done_cut_m3),
            ("doneFillM3", self.done_fill_m3),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} 은 finite 여야 한다 (got {value!r})")

        for label, done, planned, remaining, ratio in (
            (
                "cut",
                self.done_cut_m3,
                self.planned_cut_m3,
                self.remaining_cut_m3,
                self.cut_progress_ratio,
            ),
            (
                "fill",
                self.done_fill_m3,
                self.planned_fill_m3,
                self.remaining_fill_m3,
                self.fill_progress_ratio,
            ),
        ):
            expected = planned - remaining
            tolerance = 1e-6 * max(1.0, abs(expected))
            if not math.isclose(done, expected, abs_tol=tolerance):
                raise ValueError(
                    f"done{label.capitalize()}M3 가 계획−잔여와 다르다: "
                    f"{done} != {planned} - {remaining}"
                )
            has_plan = planned > PLANNED_EPSILON_M3
            if not has_plan and ratio is not None:
                raise ValueError(
                    f"{label} 계획이 없는데 진척률이 있다({ratio}) — 0으로 나눌 수 없고, "
                    "0% 로 적으면 '할 일이 있는데 안 했다'는 반대 뜻이 된다"
                )
            if has_plan:
                if ratio is None:
                    raise ValueError(
                        f"{label} 계획이 {planned} 인데 진척률이 없다 — 낼 수 있는 값을 "
                        "비워두면 화면이 이유를 지어낸다"
                    )
                expected_ratio = done / planned
                if not math.isclose(ratio, expected_ratio, rel_tol=1e-9, abs_tol=1e-9):
                    raise ValueError(
                        f"{label}ProgressRatio 가 완료/계획과 다르다: "
                        f"{ratio} != {done}/{planned}"
                    )
        return self


class DesignProgress(_CamelModel):
    """한 설계면에 대한 현장 전체의 진척 — 구역 목록 + 두 기준 시점.

    두 시각이 필수인 이유: 이 표의 모든 숫자는 "언제부터 언제까지"의 값이고, 그
    구간을 모르면 진척률은 아무 뜻이 없다. 특히 기준 시점이 이미 시공이 시작된
    뒤라면 계획 자체가 과소 계상된다 — 그 사실을 사람이 판단할 수 있어야 한다.
    """

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    site_id: str = Field(min_length=1)
    design_surface_id: str = Field(min_length=1)
    #: 어느 판의 설계면인가. 기준·최신 두 리포트가 **같은 해시**를 봤을 때만 이 표가
    #: 성립한다 — 설계가 바뀌면 계획 물량 자체가 바뀌므로 이어 붙이면 거짓이 된다.
    design_surface_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_design_conformance_id: str = Field(min_length=1)
    baseline_computed_at: str = Field(min_length=1)
    latest_design_conformance_id: str = Field(min_length=1)
    latest_computed_at: str = Field(min_length=1)
    #: 두 리포트가 공유하는 집계 문턱. 다르면 이 표를 만들지 않는다(다른 자로 잰 값).
    threshold_m: float = Field(ge=0.0)
    zones: list[ZoneProgress] = Field(min_length=1)

    @model_validator(mode="after")
    def _zone_ids_are_unique(self) -> DesignProgress:
        zone_ids = [zone.zone_id for zone in self.zones]
        if len(set(zone_ids)) != len(zone_ids):
            raise ValueError(f"zoneId 가 중복된다: {zone_ids} — 같은 구역이 두 번 집계된다")
        if self.baseline_design_conformance_id == self.latest_design_conformance_id:
            raise ValueError(
                "기준과 최신이 같은 리포트다 — 자기 자신 대비 진척은 항상 0이라 "
                "화면에 '아무것도 안 했다'로 나온다. 다른 시점을 골라야 한다"
            )
        return self


__all__ = [
    "PLANNED_EPSILON_M3",
    "DesignProgress",
    "ZoneProgress",
]
