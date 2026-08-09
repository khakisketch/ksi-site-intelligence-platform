// CoverageReport 의 Cell 상태를 사람이 읽을 요약으로 묶는다 — 도메인 규칙 SSOT
// (triage.ts 와 같은 자리). 서버(ksi_event_contracts.coverage_report)의 분류를
// 그대로 옮긴다 — 새 판정을 만들지 않는다:
//
//   관찰됨            OBSERVED_HIGH_CONFIDENCE·OBSERVED_PARTIAL·
//                     RECONSTRUCTION_READY·EVENT_INSPECTED
//   사유 있는 미관찰   OCCLUDED·UNREACHABLE·UNSAFE·SENSOR_LIMITED·
//                     TIME_LIMITED·BATTERY_LIMITED
//   사유 없는 미관찰   NOT_OBSERVED — COMPLETED 주장이면 서버가 애초에 거부한다
//
// 이 요약은 표시 그룹핑일 뿐이다 — mandatoryHazardRatio 같은 비율이나 completionState
// 판정을 다시 계산하지 않는다(그건 서버가 이미 했다, INV-010).

import type { CoverageCell, CoverageCellState } from "./types";

const OBSERVED_STATES = new Set<CoverageCellState>([
  "OBSERVED_HIGH_CONFIDENCE",
  "OBSERVED_PARTIAL",
  "RECONSTRUCTION_READY",
  "EVENT_INSPECTED",
]);

const UNEXPLAINED_GAP_STATES = new Set<CoverageCellState>(["NOT_OBSERVED"]);

export interface CoverageCellSummary {
  total: number;
  observed: number;
  explainedGap: number;
  unexplainedGap: number;
  /** 0건인 상태는 뺀다 — 있었던 상태만 사람이 스캔한다. */
  byState: Array<{ state: CoverageCellState; count: number }>;
}

export function summarizeCoverageCells(cells: CoverageCell[]): CoverageCellSummary {
  const counts = new Map<CoverageCellState, number>();
  let observed = 0;
  let explainedGap = 0;
  let unexplainedGap = 0;

  for (const cell of cells) {
    counts.set(cell.state, (counts.get(cell.state) ?? 0) + 1);
    if (OBSERVED_STATES.has(cell.state)) observed += 1;
    else if (UNEXPLAINED_GAP_STATES.has(cell.state)) unexplainedGap += 1;
    else explainedGap += 1;
  }

  const byState = Array.from(counts.entries())
    .map(([state, count]) => ({ state, count }))
    .sort((a, b) => b.count - a.count);

  return { total: cells.length, observed, explainedGap, unexplainedGap, byState };
}
