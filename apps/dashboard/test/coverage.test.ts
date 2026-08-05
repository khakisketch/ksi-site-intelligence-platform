import { describe, expect, it } from "vitest";

import { summarizeCoverageCells } from "@/lib/core-api/coverage";
import type { CoverageCell, CoverageCellState } from "@/lib/core-api/types";

// 서버(ksi_event_contracts.coverage_report)의 3분류를 그대로 옮긴 요약이다 —
// 이 테스트가 깨지면 대시보드가 관찰/미관찰을 서버와 다르게 세고 있다는 뜻이다.

function cell(state: CoverageCellState, cellId = "c"): CoverageCell {
  return { cellId, state };
}

describe("summarizeCoverageCells", () => {
  it("빈 배열은 전부 0이다", () => {
    expect(summarizeCoverageCells([])).toEqual({
      total: 0,
      observed: 0,
      explainedGap: 0,
      unexplainedGap: 0,
      byState: [],
    });
  });

  it("관찰 상태 4종을 전부 '관찰됨'으로 센다", () => {
    const cells: CoverageCell[] = [
      cell("OBSERVED_HIGH_CONFIDENCE"),
      cell("OBSERVED_PARTIAL"),
      cell("RECONSTRUCTION_READY"),
      cell("EVENT_INSPECTED"),
    ];
    const summary = summarizeCoverageCells(cells);
    expect(summary.observed).toBe(4);
    expect(summary.explainedGap).toBe(0);
    expect(summary.unexplainedGap).toBe(0);
  });

  it("사유 있는 미관찰(OCCLUDED 등)은 explainedGap 이지 unexplainedGap 이 아니다", () => {
    const cells: CoverageCell[] = [
      cell("OCCLUDED"),
      cell("UNREACHABLE"),
      cell("UNSAFE"),
      cell("SENSOR_LIMITED"),
      cell("TIME_LIMITED"),
      cell("BATTERY_LIMITED"),
    ];
    const summary = summarizeCoverageCells(cells);
    expect(summary.explainedGap).toBe(6);
    expect(summary.unexplainedGap).toBe(0);
    expect(summary.observed).toBe(0);
  });

  it("NOT_OBSERVED 만 unexplainedGap 이다 — 서버가 COMPLETED 주장이면 거부하는 그 상태", () => {
    const summary = summarizeCoverageCells([cell("NOT_OBSERVED")]);
    expect(summary.unexplainedGap).toBe(1);
    expect(summary.explainedGap).toBe(0);
  });

  it("byState 는 0건 상태를 빼고 개수 내림차순이다", () => {
    const cells: CoverageCell[] = [
      cell("OCCLUDED", "a"),
      cell("OCCLUDED", "b"),
      cell("OBSERVED_HIGH_CONFIDENCE", "c"),
    ];
    const summary = summarizeCoverageCells(cells);
    expect(summary.byState).toEqual([
      { state: "OCCLUDED", count: 2 },
      { state: "OBSERVED_HIGH_CONFIDENCE", count: 1 },
    ]);
  });

  it("total 은 전체 cell 수와 같다", () => {
    const cells: CoverageCell[] = [
      cell("OBSERVED_HIGH_CONFIDENCE", "a"),
      cell("NOT_OBSERVED", "b"),
      cell("OCCLUDED", "c"),
    ];
    expect(summarizeCoverageCells(cells).total).toBe(3);
  });
});
