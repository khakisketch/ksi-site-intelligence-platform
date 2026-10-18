import { describe, expect, it } from "vitest";

import { nativeBoundsFromInspection } from "@/lib/spatial-data-request";

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
