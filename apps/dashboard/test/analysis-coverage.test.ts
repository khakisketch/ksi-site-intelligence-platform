import { describe, expect, it } from "vitest";
import { decodeAnalysisCoverage, coverageCell, MAX_COVERAGE_CELLS } from "@/lib/analysis-coverage";

export function coverageFixture() {
  return {
    contractVersion: "external-relative-volume-coverage-witness.v2",
    rows: 2, columns: 3, rowOffset: 7, columnOffset: 11,
    selectedMaskB64: "6A==", commonValidMaskB64: "qA==",
    unavailableMaskB64: "QA==", thresholdExcludedMaskB64: "AA==",
    selectedCellCount: 4, commonValidCellCount: 3, unavailableCellCount: 1,
    thresholdExcludedCellCount: 0, cellAreaM2: 2,
    selectedAreaM2: 8, commonValidAreaM2: 6, bounds: [10, 20, 16, 24],
    coverageWitnessDigest: `sha256:${"a".repeat(64)}`,
  };
}

describe("exact analysis coverage projection", () => {
  it("keeps the Core row-major, big-endian cells, holes and unavailable cells distinct", () => {
    const grid = decodeAnalysisCoverage(coverageFixture());
    expect(grid.rows).toBe(2);
    expect(grid.rowOffset).toBe(7);
    expect([0, 1, 2, 3, 4, 5].map((i) => coverageCell(grid, Math.floor(i / 3), i % 3)))
      .toEqual(["COMMON_VALID", "UNAVAILABLE", "COMMON_VALID", "OUTSIDE", "COMMON_VALID", "OUTSIDE"]);
    expect(() => coverageCell(grid, 2, 0)).toThrow();
    expect(() => coverageCell(grid, 0, 0.5)).toThrow();
  });

  it.each([
    { rows: 0 }, { rows: MAX_COVERAGE_CELLS + 1 }, { rows: 1e12, columns: 1e12 },
    { columns: 1.5 }, { rowOffset: 0.5 }, { selectedCellCount: 3 },
    { commonValidMaskB64: "6A==" }, { unavailableMaskB64: "AA==" },
    { selectedMaskB64: "6B==" }, { selectedMaskB64: "6A==\n" },
    { selectedMaskB64: "6AAA" }, { thresholdExcludedMaskB64: "gA==", thresholdExcludedCellCount: 1 },
    { bounds: [0, 0, Infinity, 1] }, { bounds: [1, 0, 0, 1] },
    { cellAreaM2: NaN }, { selectedAreaM2: 0 }, { coverageWitnessDigest: "fake" },
    { extra: true }, { contractVersion: "unknown" },
  ])("refuses inconsistent or oversized witnesses before rendering: %j", (override) => {
    expect(() => decodeAnalysisCoverage({ ...coverageFixture(), ...override })).toThrow();
  });

  it("preserves V3 mask exclusion separately from the original WorkArea and from unavailable data", () => {
    const shared: Record<string, unknown> = { ...coverageFixture() };
    for (const key of ["selectedMaskB64", "thresholdExcludedMaskB64", "selectedCellCount", "thresholdExcludedCellCount", "selectedAreaM2"]) delete shared[key];
    const grid = decodeAnalysisCoverage({
      ...shared, contractVersion: "external-masked-volume-coverage-witness.v3",
      originalSelectedMaskB64: "6A==", maskExcludedMaskB64: "QA==",
      effectiveSelectedMaskB64: "qA==", unavailableMaskB64: "AA==",
      originalSelectedCellCount: 4, maskExcludedCellCount: 1, effectiveSelectedCellCount: 3,
      unavailableCellCount: 0, originalSelectedAreaM2: 8, effectiveSelectedAreaM2: 6,
    });
    expect(coverageCell(grid, 0, 1)).toBe("MASK_EXCLUDED");
    expect(coverageCell(grid, 1, 0)).toBe("OUTSIDE");
    expect(grid.counts).toEqual({ COMMON_VALID: 3, UNAVAILABLE: 0, MASK_EXCLUDED: 1, OUTSIDE: 2 });
  });
});
