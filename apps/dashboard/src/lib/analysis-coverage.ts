import type { AnalysisCoverageSummary, AnalysisView } from "./core-api/analysis";

// Presentation budgets only; these do not change Core's admission/resource policy.
export const MAX_COVERAGE_CELLS = 262_144;
export const MAX_COVERAGE_BYTES = 262_144;
export const MAX_COVERAGE_AXIS = 4_096;

export type CoverageState = "COMMON_VALID" | "UNAVAILABLE" | "MASK_EXCLUDED" | "OUTSIDE";
export type CoverageGridReference = {
  observedCrsIdentifier: string;
  transform: [number, number, number, number, number, number];
};
export type CoverageGrid = {
  rows: number; columns: number; rowOffset: number; columnOffset: number;
  selected: Uint8Array; common: Uint8Array; unavailable: Uint8Array; excluded: Uint8Array;
  counts: Record<CoverageState, number>;
};

export type AnalysisCoverageWire = {
  contractVersion: "external-relative-volume-coverage-witness.v2";
  rows: number; columns: number; rowOffset: number; columnOffset: number;
  selectedMaskB64: string; commonValidMaskB64: string; unavailableMaskB64: string; thresholdExcludedMaskB64: string;
  selectedCellCount: number; commonValidCellCount: number; unavailableCellCount: number; thresholdExcludedCellCount: number;
  cellAreaM2: number; selectedAreaM2: number; commonValidAreaM2: number;
  bounds: [number, number, number, number]; coverageWitnessDigest: string | null;
};

export type AnalysisCoverageResource = {
  siteId: string; analysisId: string; workAreaId: string;
  resultId: string; reportDigest: string; numericResultIdentityDigest: string;
  coverage: AnalysisCoverageWire;
  gridReference: CoverageGridReference | null;
};

const sharedKeys = ["contractVersion", "rows", "columns", "rowOffset", "columnOffset",
  "commonValidMaskB64", "unavailableMaskB64", "commonValidCellCount", "unavailableCellCount",
  "cellAreaM2", "commonValidAreaM2", "bounds", "coverageWitnessDigest"];
const v2Keys = [...sharedKeys, "selectedMaskB64", "thresholdExcludedMaskB64", "selectedCellCount",
  "thresholdExcludedCellCount", "selectedAreaM2"];
const v3Keys = [...sharedKeys, "originalSelectedMaskB64", "maskExcludedMaskB64", "effectiveSelectedMaskB64",
  "originalSelectedCellCount", "maskExcludedCellCount", "effectiveSelectedCellCount", "originalSelectedAreaM2", "effectiveSelectedAreaM2"];
const digestPattern = /^sha256:[0-9a-f]{64}$/;

function invalid(): never { throw new Error("계산 범위 근거의 형식이나 연결을 확인할 수 없습니다."); }
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function count(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0; }
function close(a: unknown, b: number): boolean {
  return typeof a === "number" && Number.isFinite(a) && a >= 0
    && Math.abs(a - b) <= Math.max(1e-12, 1e-12 * Math.max(Math.abs(a), Math.abs(b)));
}

export function coverageFitsDisplay(rows: number, columns: number): boolean {
  return Number.isSafeInteger(rows) && Number.isSafeInteger(columns) && rows > 0 && columns > 0
    && rows <= MAX_COVERAGE_AXIS && columns <= MAX_COVERAGE_AXIS && rows * columns <= MAX_COVERAGE_CELLS;
}

function mask(value: unknown, cells: number): Uint8Array {
  const length = Math.ceil(cells / 8);
  // Check before decoding: neither whitespace nor alternate base64 padding is accepted.
  if (typeof value !== "string" || value.length !== Math.ceil(length / 3) * 4) return invalid();
  let binary: string;
  try { binary = atob(value); } catch { return invalid(); }
  if (binary.length !== length || btoa(binary) !== value) return invalid();
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  const padding = (8 - cells % 8) % 8;
  if (padding && (bytes[length - 1]! & ((1 << padding) - 1))) return invalid();
  return bytes;
}

function popcount(bytes: Uint8Array): number {
  let total = 0;
  for (let byte of bytes) { while (byte) { total += byte & 1; byte >>>= 1; } }
  return total;
}

/** Decode only the existing frozen V2/V3 witnesses; never infer cells from counts/bounds. */
export function decodeAnalysisCoverage(value: unknown): CoverageGrid {
  if (!record(value)) return invalid();
  const v3 = value.contractVersion === "external-masked-volume-coverage-witness.v3";
  if (!v3 && value.contractVersion !== "external-relative-volume-coverage-witness.v2") return invalid();
  const keys = v3 ? v3Keys : v2Keys;
  if (Object.keys(value).length !== keys.length || !keys.every((key) => Object.hasOwn(value, key))) return invalid();
  const { rows, columns, rowOffset, columnOffset, cellAreaM2, bounds } = value;
  if (typeof rows !== "number" || typeof columns !== "number" || !coverageFitsDisplay(rows, columns)
    || typeof rowOffset !== "number" || !Number.isSafeInteger(rowOffset)
    || typeof columnOffset !== "number" || !Number.isSafeInteger(columnOffset)
    || !Number.isSafeInteger(rowOffset + rows - 1) || !Number.isSafeInteger(columnOffset + columns - 1)
    || typeof cellAreaM2 !== "number" || !Number.isFinite(cellAreaM2) || cellAreaM2 <= 0
    || !Array.isArray(bounds) || bounds.length !== 4 || !bounds.every((x) => typeof x === "number" && Number.isFinite(x))
    || bounds[0] >= bounds[2] || bounds[1] >= bounds[3]
    || !(value.coverageWitnessDigest === null || typeof value.coverageWitnessDigest === "string" && digestPattern.test(value.coverageWitnessDigest))) return invalid();
  const cells = rows * columns;
  const selected = mask(v3 ? value.originalSelectedMaskB64 : value.selectedMaskB64, cells);
  const common = mask(value.commonValidMaskB64, cells);
  const unavailable = mask(value.unavailableMaskB64, cells);
  const excluded = mask(v3 ? value.maskExcludedMaskB64 : value.thresholdExcludedMaskB64, cells);
  const effective = v3 ? mask(value.effectiveSelectedMaskB64, cells) : selected;
  const selectedCount = v3 ? value.originalSelectedCellCount : value.selectedCellCount;
  const excludedCount = v3 ? value.maskExcludedCellCount : value.thresholdExcludedCellCount;
  const declared = [selectedCount, value.commonValidCellCount, value.unavailableCellCount, excludedCount];
  if (!declared.every(count) || [selected, common, unavailable, excluded].map(popcount).join() !== declared.join()) return invalid();
  for (let i = 0; i < selected.length; i++) {
    if ((excluded[i]! & ~selected[i]!) || effective[i] !== (selected[i]! & ~excluded[i]!)
      || (common[i]! & ~effective[i]!) || unavailable[i] !== (effective[i]! & ~common[i]!)) return invalid();
  }
  if (!v3 && excludedCount !== 0) return invalid(); // V2's fixed zero threshold stays frozen.
  if (v3 && (!count(value.effectiveSelectedCellCount) || popcount(effective) !== value.effectiveSelectedCellCount
    || !value.effectiveSelectedCellCount || value.unavailableCellCount !== 0
    || value.commonValidCellCount !== value.effectiveSelectedCellCount
    || !close(value.effectiveSelectedAreaM2, value.effectiveSelectedCellCount * cellAreaM2))) return invalid();
  if (!close(v3 ? value.originalSelectedAreaM2 : value.selectedAreaM2, (selectedCount as number) * cellAreaM2)
    || !close(value.commonValidAreaM2, (value.commonValidCellCount as number) * cellAreaM2)) return invalid();
  return { rows, columns, rowOffset, columnOffset, selected, common, unavailable, excluded,
    counts: { COMMON_VALID: value.commonValidCellCount as number, UNAVAILABLE: value.unavailableCellCount as number,
      MASK_EXCLUDED: v3 ? excludedCount as number : 0, OUTSIDE: cells - (selectedCount as number) } };
}

export function coverageCell(grid: CoverageGrid, row: number, column: number): CoverageState {
  if (!count(row) || !count(column) || row >= grid.rows || column >= grid.columns) return invalid();
  const index = row * grid.columns + column, bit = 1 << (7 - index % 8), offset = Math.floor(index / 8);
  if (!(grid.selected[offset]! & bit)) return "OUTSIDE";
  if (grid.excluded[offset]! & bit) return "MASK_EXCLUDED";
  if (grid.unavailable[offset]! & bit) return "UNAVAILABLE";
  return "COMMON_VALID";
}

export function coverageMatchesSummary(wire: AnalysisCoverageWire, summary: AnalysisCoverageSummary): boolean {
  const keys = ["rows", "columns", "selectedCellCount", "commonValidCellCount", "unavailableCellCount",
    "thresholdExcludedCellCount", "cellAreaM2", "selectedAreaM2", "commonValidAreaM2"] as const;
  return keys.every((key) => wire[key] === summary[key])
    && wire.bounds.every((value, index) => value === summary.bounds[index])
    && (wire.coverageWitnessDigest === null || wire.coverageWitnessDigest === summary.coverageWitnessDigest);
}

/** The baseline affine must describe this exact witness window, not just have a matching CRS label. */
export function isCoverageGridReference(value: unknown, wire: AnalysisCoverageWire): value is CoverageGridReference {
  if (!record(value) || typeof value.observedCrsIdentifier !== "string" || value.observedCrsIdentifier.length > 255
    || !Array.isArray(value.transform) || value.transform.length !== 6
    || !value.transform.every((x) => typeof x === "number" && Number.isFinite(x))) return false;
  const [a, b, x, d, e, y] = value.transform as number[];
  const area = Math.abs(a! * e! - b! * d!);
  if (!Number.isFinite(area) || area <= 0 || Math.abs(area - wire.cellAreaM2) > Math.max(1e-12, area * 1e-12)) return false;
  const points = [[wire.columnOffset, wire.rowOffset], [wire.columnOffset + wire.columns, wire.rowOffset],
    [wire.columnOffset + wire.columns, wire.rowOffset + wire.rows], [wire.columnOffset, wire.rowOffset + wire.rows]]
    .map(([c, r]) => [a! * c! + b! * r! + x!, d! * c! + e! * r! + y!]);
  const bounds = [Math.min(...points.map((p) => p[0]!)), Math.min(...points.map((p) => p[1]!)),
    Math.max(...points.map((p) => p[0]!)), Math.max(...points.map((p) => p[1]!))];
  return bounds.every((actual, index) => Number.isFinite(actual) && Math.abs(actual - wire.bounds[index]!) <= Math.max(1e-8, Math.abs(actual) * 1e-12));
}

export function isCoverageResourceFor(value: unknown, detail: AnalysisView): value is AnalysisCoverageResource {
  if (!record(value) || !detail.result || detail.executionState !== "COMPLETED"
    || !["PROVISIONAL_ACCURACY_UNVERIFIED", "EVALUATED"].includes(detail.suitabilityState)
    || value.siteId !== detail.siteId || value.analysisId !== detail.analysisId || value.workAreaId !== detail.workAreaId
    || value.resultId !== detail.result.resultId || value.reportDigest !== detail.result.reportDigest
    || value.numericResultIdentityDigest !== detail.result.numericResultIdentityDigest || !record(value.coverage)
    || value.coverage.contractVersion !== "external-relative-volume-coverage-witness.v2") return false;
  try { decodeAnalysisCoverage(value.coverage); } catch { return false; }
  return coverageMatchesSummary(value.coverage as AnalysisCoverageWire, detail.result.coverage)
    && (value.gridReference === null || isCoverageGridReference(value.gridReference, value.coverage as AnalysisCoverageWire));
}
