import { describe, expect, it } from "vitest";

import {
  clampSwipeBoundary,
  swipeBoundaryFromPointer,
  swipeBoundaryStep,
  swipeClipInset,
  swipeGripLeft,
  swipeValueText,
} from "@/lib/spatial-swipe";

describe("swipe boundary pure rules", () => {
  it("clamps the boundary to 0‥100 and neutralizes non-numbers", () => {
    expect(clampSwipeBoundary(50)).toBe(50);
    expect(clampSwipeBoundary(-5)).toBe(0);
    expect(clampSwipeBoundary(140)).toBe(100);
    expect(clampSwipeBoundary(Number.NaN)).toBe(50);
    expect(clampSwipeBoundary(Number.POSITIVE_INFINITY)).toBe(50);
  });

  it("moves the boundary by relative pointer delta without jumping", () => {
    // 가장자리에서 그립이 잘려 있어도 잡은 자리 기준 상대분만 쓴다.
    expect(swipeBoundaryFromPointer(0, 22, 62, 400)).toBe(10);
    expect(swipeBoundaryFromPointer(100, 378, 338, 400)).toBe(90);
    expect(swipeBoundaryFromPointer(50, 200, 200, 400)).toBe(50);
    // 폭을 모르면 그대로 둔다 — 0으로 나누지 않는다.
    expect(swipeBoundaryFromPointer(50, 200, 300, 0)).toBe(50);
    expect(swipeBoundaryFromPointer(95, 0, 400, 400)).toBe(100);
  });

  it("steps the slider by key without inventing other keys", () => {
    expect(swipeBoundaryStep(50, "ArrowRight", false)).toBe(51);
    expect(swipeBoundaryStep(50, "ArrowLeft", false)).toBe(49);
    expect(swipeBoundaryStep(50, "ArrowUp", false)).toBe(51);
    expect(swipeBoundaryStep(50, "ArrowDown", false)).toBe(49);
    expect(swipeBoundaryStep(50, "ArrowRight", true)).toBe(60);
    expect(swipeBoundaryStep(50, "PageUp", false)).toBe(60);
    expect(swipeBoundaryStep(50, "PageDown", false)).toBe(40);
    expect(swipeBoundaryStep(50, "Home", false)).toBe(0);
    expect(swipeBoundaryStep(50, "End", false)).toBe(100);
    expect(swipeBoundaryStep(0, "ArrowLeft", false)).toBe(0);
    expect(swipeBoundaryStep(100, "ArrowRight", true)).toBe(100);
    expect(swipeBoundaryStep(50, "Enter", false)).toBeNull();
    expect(swipeBoundaryStep(50, "a", false)).toBeNull();
  });

  it("clips the left layer in screen space and keeps the grip inside the stage", () => {
    expect(swipeClipInset(25)).toBe("inset(0 75% 0 0)");
    expect(swipeClipInset(0)).toBe("inset(0 100% 0 0)");
    expect(swipeClipInset(100)).toBe("inset(0 0% 0 0)");
    // 클립은 양끝까지 가되, 44px 그립 표시는 무대 안에 둔다.
    expect(swipeGripLeft(0)).toBe("clamp(26px, 0%, calc(100% - 26px))");
    expect(swipeGripLeft(100)).toBe("clamp(26px, 100%, calc(100% - 26px))");
  });

  it("reads the value as A/B percents without ranking them", () => {
    expect(swipeValueText(50, "A 2021-08-17", "B 2022-08-24")).toBe("A 2021-08-17 50% · B 2022-08-24 50%");
    expect(swipeValueText(0, "A", "B")).toBe("A 0% · B 100%");
  });
});
