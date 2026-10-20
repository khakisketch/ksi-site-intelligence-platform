import { describe, expect, it } from "vitest";

import {
  canUseWholeGrid,
  initialPixelWindowDims,
  nativeBoundsFromInspection,
  resolveBoundedPixelWindow,
} from "@/lib/spatial-data-request";

describe("nativeBoundsFromInspection", () => {
  it("derives the exact native rectangle from the inspected grid", () => {
    // 1m 픽셀, 원점 (200000, 550000), 32×32 — 남쪽으로 내려간다.
    expect(nativeBoundsFromInspection({ transform: [1, 0, 200000, 0, -1, 550000], width: 32, height: 32 }))
      .toEqual([200000, 549968, 200032, 550000]);
  });

  it("keeps fractional pixel sizes without rounding", () => {
    const bounds = nativeBoundsFromInspection({ transform: [0.05, 0, 500000, 0, -0.05, 4000000], width: 200, height: 100 });
    expect(bounds).not.toBeNull();
    expect(bounds![0]).toBe(500000);
    expect(bounds![1]).toBeCloseTo(3999995, 6);
    expect(bounds![2]).toBeCloseTo(500010, 6);
    expect(bounds![3]).toBe(4000000);
  });

  it("refuses rotated or non-standard grids instead of guessing", () => {
    expect(nativeBoundsFromInspection({ transform: [1, 0.2, 200000, 0.2, -1, 550000], width: 32, height: 32 })).toBeNull();
    expect(nativeBoundsFromInspection({ transform: [-1, 0, 200000, 0, -1, 550000], width: 32, height: 32 })).toBeNull();
    expect(nativeBoundsFromInspection({ transform: [1, 0, 200000, 0, 1, 550000], width: 32, height: 32 })).toBeNull();
  });

  it("refuses non-finite, non-integer or empty grids", () => {
    expect(nativeBoundsFromInspection({ transform: [Number.NaN, 0, 0, 0, -1, 0], width: 1, height: 1 })).toBeNull();
    expect(nativeBoundsFromInspection({ transform: [1, 0, 0, 0, -1, 0], width: 0, height: 4 })).toBeNull();
    expect(nativeBoundsFromInspection({ transform: [1, 0, 0, 0, -1, 0], width: 2.5, height: 4 })).toBeNull();
  });
});

describe("resolveBoundedPixelWindow", () => {
  const grid = { transform: [1, 0, 200000, 0, -1, 550000], width: 1024, height: 1024 };

  it("derives the exact native rectangle for the chosen window without rounding", () => {
    const result = resolveBoundedPixelWindow(grid, { width: 512, height: 512, col: 256, row: 256 });
    expect(result).toEqual({
      ok: true,
      value: {
        window: [256, 256, 512, 512],
        requestedBounds: [200256, 549232, 200768, 549744],
        width: 512,
        height: 512,
      },
    });
  });

  it("supports rectangular windows and whole tiny grids", () => {
    expect(resolveBoundedPixelWindow(
      { transform: [1, 0, 200000, 0, -1, 550000], width: 2, height: 3 },
      { width: 2, height: 3, col: 0, row: 0 },
    )).toEqual({
      ok: true,
      value: {
        window: [0, 0, 2, 3],
        requestedBounds: [200000, 549997, 200002, 550000],
        width: 2,
        height: 3,
      },
    });
    expect(resolveBoundedPixelWindow(
      { transform: [1, 0, 200000, 0, -1, 550000], width: 64, height: 64 },
      { width: 64, height: 64, col: 0, row: 0 },
    ).ok).toBe(true);
  });

  it("keeps fractional pixel sizes without rounding", () => {
    const fractional = { transform: [0.05, 0, 500000, 0, -0.05, 4000000], width: 4000, height: 4000 };
    const result = resolveBoundedPixelWindow(fractional, { width: 512, height: 256, col: 0, row: 0 });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.requestedBounds[0]).toBe(500000);
      expect(result.value.requestedBounds[1]).toBeCloseTo(3999987.2, 6);
      expect(result.value.requestedBounds[2]).toBeCloseTo(500025.6, 6);
      expect(result.value.requestedBounds[3]).toBe(4000000);
    }
  });

  it("refuses a missing inspection instead of guessing bounds", () => {
    expect(resolveBoundedPixelWindow(null, { width: 512, height: 512, col: 0, row: 0 }))
      .toEqual({ ok: false, reason: "NO_INSPECTION" });
  });

  it("refuses rotated or non-standard grids instead of guessing", () => {
    expect(resolveBoundedPixelWindow({ ...grid, transform: [1, 0.2, 200000, 0.2, -1, 550000] }, { width: 512, height: 512, col: 0, row: 0 }))
      .toEqual({ ok: false, reason: "ROTATED_GRID" });
    expect(resolveBoundedPixelWindow({ ...grid, transform: [-1, 0, 200000, 0, -1, 550000] }, { width: 512, height: 512, col: 0, row: 0 }).ok).toBe(false);
    expect(resolveBoundedPixelWindow({ transform: [Number.NaN, 0, 0, 0, -1, 0], width: 8, height: 8 }, { width: 8, height: 8, col: 0, row: 0 }))
      .toEqual({ ok: false, reason: "INVALID_GRID" });
    expect(resolveBoundedPixelWindow({ transform: [1, 0, 0, 0, -1, 0], width: 0, height: 8 }, { width: 8, height: 8, col: 0, row: 0 }))
      .toEqual({ ok: false, reason: "INVALID_GRID" });
  });

  it("refuses non-finite window shapes and sizes above the cap", () => {
    expect(resolveBoundedPixelWindow(grid, { width: 0, height: 512, col: 0, row: 0 })).toEqual({ ok: false, reason: "INVALID_WINDOW" });
    expect(resolveBoundedPixelWindow(grid, { width: 513, height: 512, col: 0, row: 0 })).toEqual({ ok: false, reason: "INVALID_WINDOW" });
    expect(resolveBoundedPixelWindow(grid, { width: 512, height: 513, col: 0, row: 0 })).toEqual({ ok: false, reason: "INVALID_WINDOW" });
    expect(resolveBoundedPixelWindow(grid, { width: 512.5, height: 512, col: 0, row: 0 })).toEqual({ ok: false, reason: "INVALID_WINDOW" });
    expect(resolveBoundedPixelWindow(grid, { width: 512, height: 512, col: -1, row: 0 })).toEqual({ ok: false, reason: "INVALID_WINDOW" });
    expect(resolveBoundedPixelWindow(grid, { width: 512, height: 512, col: 0.5, row: 0 })).toEqual({ ok: false, reason: "INVALID_WINDOW" });
  });

  it("refuses windows outside the inspected grid instead of clamping silently", () => {
    expect(resolveBoundedPixelWindow(grid, { width: 512, height: 512, col: 513, row: 0 })).toEqual({ ok: false, reason: "OUT_OF_BOUNDS" });
    expect(resolveBoundedPixelWindow(grid, { width: 512, height: 512, col: 0, row: 513 })).toEqual({ ok: false, reason: "OUT_OF_BOUNDS" });
    expect(resolveBoundedPixelWindow(grid, { width: 512, height: 256, col: 513, row: 0 })).toEqual({ ok: false, reason: "OUT_OF_BOUNDS" });
    // 가장자리 딱 맞기는 허용한다.
    expect(resolveBoundedPixelWindow(grid, { width: 512, height: 512, col: 512, row: 512 }).ok).toBe(true);
  });
});

describe("initialPixelWindowDims", () => {
  it("returns the whole grid for small rasters without a fictitious minimum", () => {
    expect(initialPixelWindowDims(2, 3)).toEqual({ width: 2, height: 3, col: 0, row: 0 });
    expect(initialPixelWindowDims(64, 64)).toEqual({ width: 64, height: 64, col: 0, row: 0 });
    expect(initialPixelWindowDims(512, 200)).toEqual({ width: 512, height: 200, col: 0, row: 0 });
  });

  it("centers a bounded window on large or narrow grids", () => {
    expect(initialPixelWindowDims(5000, 4000)).toEqual({ width: 512, height: 512, col: 2244, row: 1744 });
    expect(initialPixelWindowDims(100, 2000)).toEqual({ width: 100, height: 512, col: 0, row: 744 });
  });

  it("refuses invalid grids", () => {
    expect(initialPixelWindowDims(0, 100)).toBeNull();
    expect(initialPixelWindowDims(2.5, 3)).toBeNull();
  });
});

describe("canUseWholeGrid", () => {
  it("allows whole grids at or below the cap in both dims", () => {
    expect(canUseWholeGrid(2, 3)).toBe(true);
    expect(canUseWholeGrid(64, 64)).toBe(true);
    expect(canUseWholeGrid(512, 512)).toBe(true);
    expect(canUseWholeGrid(513, 10)).toBe(false);
    expect(canUseWholeGrid(100, 2000)).toBe(false);
    expect(canUseWholeGrid(0, 10)).toBe(false);
  });
});
