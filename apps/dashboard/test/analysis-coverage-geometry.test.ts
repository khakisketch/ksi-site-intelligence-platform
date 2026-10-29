import { describe, expect, it } from "vitest";
import { coverageMapShapes } from "@/lib/geo/analysis-coverage-geometry";
import { isCoverageGridReference, type AnalysisCoverageWire, type CoverageGridReference } from "@/lib/analysis-coverage";

const wire: AnalysisCoverageWire = {
  contractVersion: "external-relative-volume-coverage-witness.v2", rows: 2, columns: 3, rowOffset: -1, columnOffset: -1,
  selectedMaskB64: "6A==", commonValidMaskB64: "qA==", unavailableMaskB64: "QA==", thresholdExcludedMaskB64: "AA==",
  selectedCellCount: 4, commonValidCellCount: 3, unavailableCellCount: 1, thresholdExcludedCellCount: 0,
  cellAreaM2: 1, selectedAreaM2: 4, commonValidAreaM2: 3, bounds: [199999, 549999, 200002, 550001], coverageWitnessDigest: null,
};
const reference: CoverageGridReference = { observedCrsIdentifier: "EPSG:5186", transform: [1, 0, 200000, 0, -1, 550000] };

describe("exact coverage location projection", () => {
  it("retains original row/column offsets, holes and the unavailable subset on the known projected CRS", () => {
    const result = coverageMapShapes(wire, reference);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.shapes.map((shape) => shape.state)).toEqual(["COMMON_VALID", "UNAVAILABLE", "COMMON_VALID", "COMMON_VALID"]);
    // Independent pyproj EPSG:5186 -> WGS84 control: (200000,550000).
    expect(result.shapes[3]!.positions[0]![0]).toBeCloseTo(37.54951797596735, 8);
    expect(result.shapes[3]!.positions[0]![1]).toBeCloseTo(127, 8);
  });
  it("does not assign an unverified or unsupported CRS to the witness", () => {
    expect(coverageMapShapes(wire, { ...reference, observedCrsIdentifier: "EPSG:7850" })).toMatchObject({ ok: false });
    expect(coverageMapShapes(wire, { ...reference, transform: [1,0,200100,0,-1,550000] })).toMatchObject({ ok: false });
  });
  it("checks affine area and all window corners, including a rotated baseline grid", () => {
    expect(isCoverageGridReference({ ...reference, transform: [1,0,200000,0,-2,550000] }, wire)).toBe(false);
    const rotated: CoverageGridReference = { ...reference, transform: [0,1,200000,1,0,550000] };
    const rotatedWire = { ...wire, bounds: [199999,549999,200001,550002] as [number,number,number,number] };
    expect(isCoverageGridReference(rotated, rotatedWire)).toBe(true);
    expect(coverageMapShapes(rotatedWire, rotated).ok).toBe(true);
  });
});
