import { coverageCell, decodeAnalysisCoverage, isCoverageGridReference, type AnalysisCoverageWire, type CoverageState, type CoverageGridReference } from "../analysis-coverage";
import { toDisplayVertices } from "./display-geometry";

export type CoverageMapShape = { state: Exclude<CoverageState, "OUTSIDE">; positions: [number, number][] };
export const MAX_COVERAGE_MAP_RUNS = 4_096;

/** Read-only geographic display of exact cell-edge row runs; no raster resampling or quantity calculation. */
export function coverageMapShapes(wire: AnalysisCoverageWire, reference: CoverageGridReference):
  { ok: true; shapes: CoverageMapShape[] } | { ok: false; reason: string } {
  if (!isCoverageGridReference(reference, wire)) return { ok: false, reason: "계산 격자와 위치 근거가 일치하지 않아 지도에 그리지 않습니다." };
  let grid;
  try { grid = decodeAnalysisCoverage(wire); } catch { return { ok: false, reason: "계산 범위 근거를 확인할 수 없습니다." }; }
  const shapes: CoverageMapShape[] = [];
  const [a, b, x, d, e, y] = reference.transform;
  const point = (column: number, row: number) => {
    const c = column + wire.columnOffset, r = row + wire.rowOffset;
    return [a * c + b * r + x, d * c + e * r + y];
  };
  for (let row = 0; row < grid.rows; row++) {
    let start = 0;
    while (start < grid.columns) {
      const state = coverageCell(grid, row, start);
      let end = start + 1;
      while (end < grid.columns && coverageCell(grid, row, end) === state) end++;
      if (state !== "OUTSIDE") {
        if (shapes.length >= MAX_COVERAGE_MAP_RUNS) return { ok: false, reason: "셀 경계가 지도 표시 한도를 넘었습니다. 계산 격자에서 전체 분포를 확인하세요. 일부만 그리지 않습니다." };
        const ring = [point(start, row), point(end, row), point(end, row + 1), point(start, row + 1), point(start, row)];
        const converted = toDisplayVertices({ type: "Polygon", coordinates: [ring] }, reference.observedCrsIdentifier);
        if (!converted.ok) return { ok: false, reason: `${converted.reason} 계산 격자 보기는 유지됩니다.` };
        shapes.push({ state, positions: converted.vertices.map(({ latDeg, lonDeg }) => [latDeg, lonDeg]) });
      }
      start = end;
    }
  }
  if (!shapes.length) return { ok: false, reason: "지도에 표시할 선택 셀이 없습니다. 계산 격자와 근거를 확인하세요." };
  return { ok: true, shapes };
}
