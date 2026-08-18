"""CoverageReport — 비행 후 "무엇을 실제로 관찰했나" 보고 (INV-010, MASTER_PRD §15.5).

## 왜 이 계약이 완료 판정의 권위인가

발급 시점의 ``plannedCoverageRatio`` 는 각 스캔선이 ±spacing/2 를 덮는다는 **가정**
하의 기하 추정치이고, 그 간격은 요청자가 준 값이다. 실제로 무엇을 봤는지는 날아본
기체만 안다 — 가림·접근 불가·안전 중단·배터리 한계·이벤트 분기로 생긴 공백은
계획에 나타나지 않는다.

MASTER_PRD §15.5 가 이를 명시한다: **"임무 완료는 경로 완료가 아니라 Coverage,
Evidence, Safety와 데이터 품질 기준으로 판단한다."** 그 판단의 입력이 이 보고서다.

## Cell 상태는 곧 원인코드다

미관찰 Cell 은 이유 없이 남을 수 없다(PRD "모든 미관찰 Cell에 원인코드와 후속처리
기록"). 그래서 상태 enum 이 관찰 결과와 미관찰 **사유**를 함께 담는다:

- 관찰됨: ``OBSERVED_HIGH_CONFIDENCE``·``OBSERVED_PARTIAL``·``RECONSTRUCTION_READY``·
  ``EVENT_INSPECTED``
- 사유 있는 미관찰: ``OCCLUDED``·``UNREACHABLE``·``UNSAFE``·``SENSOR_LIMITED``·
  ``TIME_LIMITED``·``BATTERY_LIMITED``
- **사유 없는 미관찰**: ``NOT_OBSERVED`` — "그냥 못 봤다". 이 상태가 남은 채
  ``COMPLETED`` 를 주장하는 보고서는 서버가 거부한다.

계약 정본은 ``contracts/schemas/coverage-report.v1.1.json`` 이고 이 모듈은 그
스키마의 Python 표현이다 — 필드가 갈라지면 계약 대조 테스트가 잡는다.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from ksi_event_contracts._base import _CamelModel

# INV-010 완료 임계 — 요청·보고서가 바꿀 수 없는 서버 고정값이다.
MANDATORY_HAZARD_MIN = 1.0
MANDATORY_ASSET_MIN = 1.0
ACCESSIBLE_GENERAL_MIN = 0.95

# 부동소수 직렬화 잔차 허용치 — mission_plans.py 의 "+ 1e-9" 관례와 동일.
_RATIO_EPS = 1e-9


class CoverageCellState(StrEnum):
    """Coverage Cell 상태 — 관찰 결과 또는 **미관찰 사유**(MASTER_PRD §15.5)."""

    OBSERVED_HIGH_CONFIDENCE = "OBSERVED_HIGH_CONFIDENCE"
    OBSERVED_PARTIAL = "OBSERVED_PARTIAL"
    RECONSTRUCTION_READY = "RECONSTRUCTION_READY"
    EVENT_INSPECTED = "EVENT_INSPECTED"
    OCCLUDED = "OCCLUDED"
    UNREACHABLE = "UNREACHABLE"
    NOT_OBSERVED = "NOT_OBSERVED"
    UNSAFE = "UNSAFE"
    SENSOR_LIMITED = "SENSOR_LIMITED"
    TIME_LIMITED = "TIME_LIMITED"
    BATTERY_LIMITED = "BATTERY_LIMITED"


# 사유 없는 미관찰 — 이 상태로 남은 Cell 이 있으면 COMPLETED 를 주장할 수 없다.
UNEXPLAINED_GAP_STATES = frozenset({CoverageCellState.NOT_OBSERVED})
# 실제로 관찰된 것으로 치는 상태 — 나머지는 전부 "못 봤다"(사유 유무만 다르다).
OBSERVED_STATES = frozenset(
    {
        CoverageCellState.OBSERVED_HIGH_CONFIDENCE,
        CoverageCellState.OBSERVED_PARTIAL,
        CoverageCellState.RECONSTRUCTION_READY,
        CoverageCellState.EVENT_INSPECTED,
    }
)


class CompletionState(StrEnum):
    """임무 종료 상태(MASTER_PRD §15.5)."""

    COMPLETED = "COMPLETED"
    COMPLETED_WITH_GAPS = "COMPLETED_WITH_GAPS"
    ABORTED_SAFE = "ABORTED_SAFE"
    FAILED = "FAILED"


class CoverageCell(_CamelModel):
    """Cell 1개의 관찰 결과.

    ``quality`` 는 선택이다 — 관찰 등급이 상태로 이미 표현되고, 수치 품질은
    센서·재구성 파이프라인이 확정한 뒤에야 의미가 생긴다.
    """

    cell_id: str = Field(min_length=1)
    state: CoverageCellState
    quality: float | None = None
    geometry_ref: str | None = None


class CoverageSummary(_CamelModel):
    """구역 분류별 관찰 비율 + 기체가 판단한 종료 상태.

    비율은 **기체가 계산한 값**이다 — 서버는 Cell 분류(위험구역/자산/일반)를 갖고
    있지 않아 재계산할 수 없다. 대신 서버는 이 비율들이 ``completion_state`` 주장을
    **뒷받침하는지**를 검사한다(:mod:`ksi_core.coverage_reports`) — 근거 없는 완료
    주장을 그대로 받지 않는다는 뜻이고, 확정 이벤트를 Edge 가 주장할 수 없게 한
    것과 같은 원칙이다.
    """

    mandatory_hazard_ratio: float = Field(ge=0.0, le=1.0)
    mandatory_asset_ratio: float = Field(ge=0.0, le=1.0)
    accessible_general_ratio: float = Field(ge=0.0, le=1.0)
    completion_state: CompletionState


class CoverageReport(_CamelModel):
    """비행 1회의 커버리지 보고 — 완료 판정의 입력."""

    schema_version: Literal["1.1"] = "1.1"
    mission_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    timestamp: datetime
    cells: list[CoverageCell]
    summary: CoverageSummary

    def unexplained_gap_cells(self) -> list[str]:
        """사유 없이 미관찰로 남은 Cell id 목록(순서 보존)."""
        return [c.cell_id for c in self.cells if c.state in UNEXPLAINED_GAP_STATES]

    def meets_completion_thresholds(self) -> bool:
        """INV-010 임계를 요약 비율이 전부 만족하는가."""
        return (
            self.summary.mandatory_hazard_ratio >= MANDATORY_HAZARD_MIN
            and self.summary.mandatory_asset_ratio >= MANDATORY_ASSET_MIN
            and self.summary.accessible_general_ratio >= ACCESSIBLE_GENERAL_MIN
        )

    def unobserved_cells(self) -> list[str]:
        """관찰되지 않은 Cell id — 사유가 있든 없든 전부(순서 보존)."""
        return [c.cell_id for c in self.cells if c.state not in OBSERVED_STATES]

    def needs_coverage_recovery(self) -> bool:
        """Coverage Recovery 재발급이 권고되는가(MASTER_PRD §15.2 "분기로 인한
        촬영공백을 Coverage Recovery가 보완").

        이 판정은 **권고일 뿐 자동 재발급을 트리거하지 않는다** — 재발급은 기존
        ``POST /v1/missions/plans``(SPATIAL_REFRESH, 원본 site AOI)를 그대로
        쓴다. 사유 없는 미관찰(``NOT_OBSERVED``)만 보는 게 아니라 사유 있는
        미관찰(``OCCLUDED``·``TIME_LIMITED`` 등)도 포함한다 — 사유가 있어도
        "못 본 곳"인 사실은 변하지 않는다.

        ``completion_state is not COMPLETED`` 를 독립적으로 본다 —
        ``COMPLETED_WITH_GAPS``·``ABORTED_SAFE``·``FAILED`` 전부 포함한다.
        judge_report 는 이 셋 모두에 Cell 존재나 임계 검사를 걸지 않으므로(그
        검사는 ``COMPLETED`` 주장에만 걸린다), cells 가 비어 있거나 전부
        관찰됨으로 채워져 있어도 completion_state 자체가 "온전히 끝나지 않았다"
        는 신호다 — 특히 ``ABORTED_SAFE``/``FAILED`` 는 재커버가 가장 명백히
        필요한 케이스라 여기서 빠지면 거짓음성이 된다(리뷰 지적 P1-a).
        """
        return (
            self.summary.completion_state is not CompletionState.COMPLETED
            or bool(self.unobserved_cells())
        )

    def contradicts_full_coverage(self) -> bool:
        """요약이 전 구역 100% 를 말하는데 관찰 안 된 Cell 이 있는가.

        서버는 Cell 분류(위험구역/자산/일반)를 몰라 비율을 재계산할 수 없지만,
        **세 비율이 모두 1.0 인데 관찰상태가 아닌 Cell 이 존재하면 어떤 가중치
        에서도 모순**이다 — 이건 분류를 몰라도 판정할 수 있다(독립 재검토 B-1).
        """
        summary = self.summary
        all_full = (
            summary.mandatory_hazard_ratio >= 1.0
            and summary.mandatory_asset_ratio >= 1.0
            and summary.accessible_general_ratio >= 1.0
        )
        return all_full and bool(self.unobserved_cells())

    def has_impossible_fractional_ratio(self) -> bool:
        """칸 총수가 2개 미만인데 비율이 0과 1 사이(양 끝 제외)면 산술적으로
        불가능하다.

        분수 k/d(d ≤ 전체 칸 수)로 표현 가능한 값 중 d<2 일 때 만들 수 있는 건
        0.0과 1.0뿐이다 — **카테고리별 칸 수를 몰라도 성립하는 순수 산술**이다
        (서버는 위험구역/자산/일반 분류를 갖고 있지 않다, INV-010). 카테고리 배정을
        전제하는 더 정밀한 판정(칸 수 ≥ 2인 경우의 Farey 분수 도달 가능성)은
        연속값으로 계산된 실사용 비율에 대해 false positive 위험이 커 채택하지
        않는다 — 이 함수가 닫는 건 이 경계 사례 하나다.
        """
        if len(self.cells) >= 2:
            return False
        ratios = (
            self.summary.mandatory_hazard_ratio,
            self.summary.mandatory_asset_ratio,
            self.summary.accessible_general_ratio,
        )
        return any(_RATIO_EPS < r < 1.0 - _RATIO_EPS for r in ratios)
