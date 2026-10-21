import { describe, expect, it } from "vitest";

import {
  DISPLAY_WINDOW_MAX_PIXELS,
  resolveFullCoverWindows,
  resolvePerEpochWindows,
  resolveViewportWindows,
  type DisplaySourceGrid,
} from "@/lib/spatial-display-viewport";

/**
 * 측정 발자국 — GAP-06 증거의 1022×915 EPSG:7850 격자 그대로다.
 * transform (0.25, 0, 382261.7296, 0, -0.25, 6467541.575):
 * yScale은 t[4]=-0.25, yOrigin은 t[5]=6467541.575다.
 */
const FLOREAT_GRID: DisplaySourceGrid = {
  transform: [0.25, 0, 382261.7296, 0, -0.25, 6467541.575],
  width: 1022,
  height: 915,
};

const LEFT = 382261.7296;
const TOP = 6467541.575;
const RIGHT = LEFT + 0.25 * 1022;
const BOTTOM = TOP - 0.25 * 915;

describe("resolveFullCoverWindows", () => {
  it("covers 1022x915 with exactly 4 windows at <=512", () => {
    const result = resolveViewportWindows(FLOREAT_GRID, [LEFT, BOTTOM, RIGHT, TOP]);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.windows).toHaveLength(4);
    expect(result.windows.map((item) => item.pixelWindow)).toEqual([
      [0, 512, 0, 512],
      [512, 1022, 0, 512],
      [0, 512, 512, 915],
      [512, 1022, 512, 915],
    ]);
    expect(result.windows.map((item) => [item.width, item.height])).toEqual([
      [512, 512],
      [510, 512],
      [512, 403],
      [510, 403],
    ]);
    for (const item of result.windows) {
      expect(item.width).toBeLessThanOrEqual(512);
      expect(item.height).toBeLessThanOrEqual(512);
      expect(item.width * item.height).toBeLessThanOrEqual(DISPLAY_WINDOW_MAX_PIXELS);
    }
    // 픽셀 수 합은 전체 격자와 같다 — 512·510·512·403 분할 그대로다.
    const total = result.windows.reduce((sum, item) => sum + item.width * item.height, 0);
    expect(total).toBe(1022 * 915);
  });

  it("abuts adjacent windows on exact cell edges with no gap or overlap", () => {
    const result = resolveFullCoverWindows(FLOREAT_GRID);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const cells = result.windows.map((item) => item.pixelWindow);
    // 같은 행의 두 창은 열 경계 512를 공유한다.
    expect(cells[0]![1]).toBe(cells[1]![0]);
    expect(cells[2]![1]).toBe(cells[3]![0]);
    // 같은 열의 두 창은 행 경계 512를 공유한다.
    expect(cells[0]![3]).toBe(cells[2]![2]);
    expect(cells[1]![3]).toBe(cells[3]![2]);
    // 행 구간이 겹치지 않는다.
    expect(cells[0]![2]).toBe(0);
    expect(cells[2]![3]).toBe(915);
  });

  it("derives actualBounds exactly from integer windows without re-rounding", () => {
    const result = resolveFullCoverWindows(FLOREAT_GRID);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const first = result.windows[0]!;
    expect(first.actualBounds[0]).toBeCloseTo(LEFT, 9);
    expect(first.actualBounds[3]).toBeCloseTo(TOP, 9);
    expect(first.actualBounds[2]).toBeCloseTo(LEFT + 0.25 * 512, 9);
    expect(first.actualBounds[1]).toBeCloseTo(TOP - 0.25 * 512, 9);
    const last = result.windows[3]!;
    expect(last.actualBounds[2]).toBeCloseTo(RIGHT, 9);
    expect(last.actualBounds[1]).toBeCloseTo(BOTTOM, 9);
  });
});

describe("resolveViewportWindows subsets", () => {
  const unit: DisplaySourceGrid = { transform: [1, 0, 0, 0, -1, 915], width: 1022, height: 915 };

  it("resolves an exactly aligned viewport to one window", () => {
    const result = resolveViewportWindows(unit, [0, 403, 512, 915]);
    expect(result).toEqual({
      ok: true,
      windows: [
        {
          pixelWindow: [0, 512, 0, 512],
          actualBounds: [0, 403, 512, 915],
          width: 512,
          height: 512,
        },
      ],
    });
  });

  it("tiles a partial viewport from the source origin with shared edges", () => {
    const first = resolveViewportWindows(unit, [100.5, 200.5, 700.25, 800.75]);
    const second = resolveViewportWindows(unit, [100.5, 200.5, 700.25, 800.75]);
    expect(first.ok && second.ok).toBe(true);
    if (!first.ok || !second.ok) return;
    // 결정적이다 — 같은 뷰포트는 같은 집합이다.
    expect(first).toEqual(second);
    expect(first.windows.length).toBeGreaterThan(1);
    // 소스 원점 기준 512 경계가 집합 안에 그대로 있다.
    const colEdges = new Set<number>();
    for (const item of first.windows) {
      colEdges.add(item.pixelWindow[0]);
      colEdges.add(item.pixelWindow[1]);
    }
    expect(colEdges.has(512)).toBe(true);
    // 인접 창은 정수 경계를 공유하고 서로 겹치지 않는다.
    const sorted = [...first.windows].sort(
      (a, b) => a.pixelWindow[2] - b.pixelWindow[2] || a.pixelWindow[0] - b.pixelWindow[0],
    );
    for (let i = 0; i + 1 < sorted.length; i += 1) {
      const a = sorted[i]!.pixelWindow;
      const b = sorted[i + 1]!.pixelWindow;
      const sameRow = a[2] === b[2] && a[3] === b[3];
      const sameCol = a[0] === b[0] && a[1] === b[1];
      // 같은 행이면 열 경계 공유, 아니면 다음 행 시작이다.
      if (sameRow) expect(a[1]).toBe(b[0]);
      else expect(sameCol || b[2] >= a[3]).toBe(true);
    }
  });

  it("clips a viewport that sticks out to the footprint instead of guessing outside", () => {
    const result = resolveViewportWindows(unit, [-50, -50, 100, 100]);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.windows).toHaveLength(1);
    expect(result.windows[0]!.pixelWindow).toEqual([0, 100, 815, 915]);
  });
});

describe("resolveViewportWindows invalid input", () => {
  const unit: DisplaySourceGrid = { transform: [1, 0, 0, 0, -1, 915], width: 1022, height: 915 };

  it("refuses empty or non-finite viewports", () => {
    expect(resolveViewportWindows(unit, [0, 0, 0, 10])).toEqual({
      ok: false,
      reason: "INVALID_VIEWPORT",
    });
    expect(resolveViewportWindows(unit, [10, 0, 0, 10])).toEqual({
      ok: false,
      reason: "INVALID_VIEWPORT",
    });
    expect(resolveViewportWindows(unit, [0, 0, Number.NaN, 10])).toEqual({
      ok: false,
      reason: "INVALID_VIEWPORT",
    });
  });

  it("reports no coverage when the viewport misses the footprint", () => {
    expect(resolveViewportWindows(unit, [5000, 5000, 6000, 6000])).toEqual({
      ok: false,
      reason: "NO_COVERAGE",
    });
  });

  it("refuses missing, rotated, or broken grids without guessing", () => {
    expect(resolveViewportWindows(null, [0, 403, 512, 915])).toEqual({
      ok: false,
      reason: "NO_INSPECTION",
    });
    expect(
      resolveViewportWindows({ transform: [1, 0.2, 0, 0.2, -1, 915], width: 1022, height: 915 }, [0, 403, 512, 915]),
    ).toEqual({ ok: false, reason: "ROTATED_GRID" });
    expect(
      resolveViewportWindows({ transform: [Number.NaN, 0, 0, 0, -1, 915], width: 8, height: 8 }, [0, 0, 8, 8]),
    ).toEqual({ ok: false, reason: "INVALID_GRID" });
  });

  it("enforces the per-output pixel cap", () => {
    expect(
      resolveViewportWindows(unit, [0, 403, 512, 915], { maxPixels: 100 }),
    ).toEqual({ ok: false, reason: "OVER_PIXEL_CAP" });
  });
});

describe("resolvePerEpochWindows", () => {
  it("resolves each epoch in its own native grid", () => {
    const grids = {
      e2021: { transform: [0.25, 0, 100, 0, -0.25, 200], width: 1022, height: 915 } as DisplaySourceGrid,
      // 같은 숫자 범위라도 격자가 다르면(0.5m) 다른 픽셀 창이다.
      e2022: { transform: [0.5, 0, 100, 0, -0.5, 200], width: 512, height: 458 } as DisplaySourceGrid,
    };
    const extent: [number, number, number, number] = [100, 100, 200, 200];
    const result = resolvePerEpochWindows(grids, { e2021: extent, e2022: extent });
    expect(result.e2021!.ok && result.e2022!.ok).toBe(true);
    if (!result.e2021!.ok || !result.e2022!.ok) return;
    // 한 시점의 픽셀 창을 다른 시점에 재해석하지 않는다 — 결과가 다르다.
    expect(result.e2021!.windows).not.toEqual(result.e2022!.windows);
    for (const item of result.e2022!.windows) {
      expect(item.pixelWindow[1]).toBeLessThanOrEqual(512);
      expect(item.pixelWindow[3]).toBeLessThanOrEqual(458);
    }
  });

  it("re-resolving on epoch switch uses the new epoch grid, never the old pixels", () => {
    const oldGrid: DisplaySourceGrid = { transform: [0.25, 0, 100, 0, -0.25, 200], width: 1022, height: 915 };
    const newGrid: DisplaySourceGrid = { transform: [0.5, 0, 100, 0, -0.5, 200], width: 512, height: 458 };
    const before = resolveViewportWindows(oldGrid, [100, 100, 200, 200]);
    // 시점 전환 = 새 격자로 다시 해석이다.
    const after = resolveViewportWindows(newGrid, [100, 100, 200, 200]);
    expect(before.ok && after.ok).toBe(true);
    if (!before.ok || !after.ok) return;
    expect(after.windows).not.toEqual(before.windows);
  });

  it("reports no observation per epoch without touching the other epoch", () => {
    const grids = {
      e2021: { transform: [1, 0, 0, 0, -1, 100], width: 100, height: 100 } as DisplaySourceGrid,
      e2022: { transform: [1, 0, 1000, 0, -1, 1100], width: 100, height: 100 } as DisplaySourceGrid,
    };
    const result = resolvePerEpochWindows(grids, {
      e2021: [0, 0, 50, 50],
      e2022: [0, 0, 50, 50],
    });
    expect(result.e2021).toEqual({
      ok: true,
      windows: [
        { pixelWindow: [0, 50, 50, 100], actualBounds: [0, 0, 50, 50], width: 50, height: 50 },
      ],
    });
    // 겹치지 않는 범위는 명시적 무관측이다 — 늘리거나 옮기지 않는다.
    expect(result.e2022).toEqual({ ok: false, reason: "NO_COVERAGE" });
  });
});
