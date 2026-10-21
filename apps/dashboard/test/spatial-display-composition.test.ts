import { describe, expect, it } from "vitest";

import {
  composeDisplayWindows,
  DISPLAY_ASSEMBLY_LABEL,
  DISPLAY_ASSEMBLY_NOTE,
  missingCoverCells,
  windowsAbut,
  windowsOverlap,
  type ReceiptVerifiedWindow,
} from "@/lib/spatial-display-composition";

function verified(key: string, pixelWindow: [number, number, number, number]): ReceiptVerifiedWindow {
  const [c0, c1, r0, r1] = pixelWindow;
  return {
    key,
    pixelWindow,
    actualBounds: [c0, r1, c1, r0],
    width: c1 - c0,
    height: r1 - r0,
    receiptVerified: true,
  };
}

describe("windowsOverlap/windowsAbut", () => {
  it("shares exact cell edges without gaps or overlaps", () => {
    expect(windowsOverlap([0, 512, 0, 512], [512, 1022, 0, 512])).toBe(false);
    expect(windowsAbut([0, 512, 0, 512], [512, 1022, 0, 512])).toBe(true);
    expect(windowsAbut([0, 512, 0, 512], [0, 512, 512, 915])).toBe(true);
    // 모서리만 닿으면 나란하지 않다.
    expect(windowsAbut([0, 512, 0, 512], [512, 1022, 512, 915])).toBe(false);
    // 겹치면 나란함이 아니다.
    expect(windowsOverlap([0, 512, 0, 512], [510, 1022, 0, 512])).toBe(true);
    expect(windowsAbut([0, 512, 0, 512], [510, 1022, 0, 512])).toBe(false);
  });
});

describe("composeDisplayWindows", () => {
  it("places adjacent receipt-verified windows edge to edge with no smoothing", () => {
    const plan = composeDisplayWindows([
      verified("a", [0, 512, 0, 512]),
      verified("b", [512, 1022, 0, 512]),
      verified("c", [0, 512, 512, 915]),
      verified("d", [512, 1022, 512, 915]),
    ]);
    expect(plan.overlapErrors).toEqual([]);
    expect(plan.seamless).toBe(true);
    expect(plan.gaps).toEqual([]);
    // 배치는 입력 창의 동일성이다 — 늘이기·보정이 없다.
    expect(plan.placed.map((item) => item.key)).toEqual(["a", "b", "c", "d"]);
  });

  it("leaves a missing window as an explicit gap, never interpolated", () => {
    const cover: Array<[number, number, number, number]> = [
      [0, 512, 0, 512],
      [512, 1022, 0, 512],
      [0, 512, 512, 915],
      [512, 1022, 512, 915],
    ];
    const placed = [
      verified("a", [0, 512, 0, 512]),
      verified("b", [512, 1022, 0, 512]),
      verified("c", [0, 512, 512, 915]),
    ];
    const gaps = missingCoverCells(cover, placed, "PREPARE_FAILED");
    expect(gaps).toHaveLength(1);
    expect(gaps[0]!.pixelWindow).toEqual([512, 1022, 512, 915]);
    const plan = composeDisplayWindows(placed, gaps);
    expect(plan.seamless).toBe(true);
    expect(plan.gaps).toHaveLength(1);
    expect(plan.gaps[0]!.reason).toBe("PREPARE_FAILED");
    expect(plan.gaps[0]!.message).toBeTruthy();
    // 빠진 창 자리에 이웃 창을 늘이지 않는다 — 배치된 창은 그대로다.
    expect(plan.placed).toHaveLength(3);
  });

  it("turns an unverified receipt into an explicit gap instead of painting it", () => {
    const plan = composeDisplayWindows([
      verified("a", [0, 512, 0, 512]),
      { ...verified("b", [512, 1022, 0, 512]), receiptVerified: false },
    ]);
    expect(plan.placed.map((item) => item.key)).toEqual(["a"]);
    expect(plan.gaps).toHaveLength(1);
    expect(plan.gaps[0]!.reason).toBe("RECEIPT_MISMATCH");
  });

  it("reports overlaps as errors instead of blending them", () => {
    const plan = composeDisplayWindows([
      verified("a", [0, 512, 0, 512]),
      verified("b", [510, 1022, 0, 512]),
    ]);
    expect(plan.overlapErrors).toHaveLength(1);
    expect(plan.seamless).toBe(false);
  });

  it("labels the composition as display assembly, never a validated dataset", () => {
    expect(DISPLAY_ASSEMBLY_LABEL).toMatch(/이음새 보정·재표본화 없음/);
    expect(DISPLAY_ASSEMBLY_NOTE).toMatch(/하나의 검증된 자료가 아니며/);
    expect(DISPLAY_ASSEMBLY_NOTE).toMatch(/정량 계산을 하지 않습니다/);
  });
});
