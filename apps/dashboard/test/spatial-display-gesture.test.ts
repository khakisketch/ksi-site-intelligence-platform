import { describe, expect, it } from "vitest";

import {
  DISPLAY_GESTURE_HINT,
  displayGestureKeyAction,
  displayWheelReady,
  DISPLAY_WHEEL_THROTTLE_MS,
  dragToViewportFractions,
  isDisplayZoomWheelIntent,
} from "@/lib/spatial-display-gesture";

describe("display gesture rules", () => {
  it("maps arrow keys to the same quarter-step pan as the buttons", () => {
    expect(displayGestureKeyAction("ArrowLeft")).toEqual({ kind: "pan", dCol: -0.25, dRow: 0 });
    expect(displayGestureKeyAction("ArrowRight")).toEqual({ kind: "pan", dCol: 0.25, dRow: 0 });
    expect(displayGestureKeyAction("ArrowUp")).toEqual({ kind: "pan", dCol: 0, dRow: 0.25 });
    expect(displayGestureKeyAction("ArrowDown")).toEqual({ kind: "pan", dCol: 0, dRow: -0.25 });
  });

  it("maps plus/minus to the same zoom steps and Home to full view", () => {
    expect(displayGestureKeyAction("+")).toEqual({ kind: "zoom", factor: 0.5 });
    expect(displayGestureKeyAction("=")).toEqual({ kind: "zoom", factor: 0.5 });
    expect(displayGestureKeyAction("-")).toEqual({ kind: "zoom", factor: 2 });
    expect(displayGestureKeyAction("_")).toEqual({ kind: "zoom", factor: 2 });
    expect(displayGestureKeyAction("Home")).toEqual({ kind: "reset" });
  });

  it("leaves every other key to the page (no keyboard hijack)", () => {
    for (const key of [" ", "Enter", "Tab", "a", "Escape", "PageDown", "0"]) {
      expect(displayGestureKeyAction(key)).toBeNull();
    }
  });

  it("converts a mouse drag into viewport fractions with content following the cursor", () => {
    // 100px right on a 400px-wide view moves the viewport a quarter left.
    expect(dragToViewportFractions(100, 0, 400, 300)).toEqual({ dCol: -0.25, dRow: 0 });
    expect(dragToViewportFractions(0, 60, 400, 300)).toEqual({ dCol: -0, dRow: 0.2 });
    expect(dragToViewportFractions(0, 0, 0, 300)).toBeNull();
    expect(dragToViewportFractions(Number.NaN, 0, 400, 300)).toBeNull();
  });

  it("zooms by wheel only with focus or Ctrl, never trapping a plain scroll", () => {
    expect(isDisplayZoomWheelIntent({ focused: true, ctrlKey: false })).toBe(true);
    expect(isDisplayZoomWheelIntent({ focused: false, ctrlKey: true })).toBe(true);
    expect(isDisplayZoomWheelIntent({ focused: false, ctrlKey: false })).toBe(false);
  });

  it("throttles wheel zoom so one flick does not cascade", () => {
    const now = 1_000;
    expect(displayWheelReady(now - DISPLAY_WHEEL_THROTTLE_MS, now)).toBe(true);
    expect(displayWheelReady(now - DISPLAY_WHEEL_THROTTLE_MS + 1, now)).toBe(false);
  });

  it("hints only supported gestures — no pinch or touch-drag promise", () => {
    expect(DISPLAY_GESTURE_HINT).toContain("마우스");
    expect(DISPLAY_GESTURE_HINT).toContain("방향키");
    expect(DISPLAY_GESTURE_HINT).not.toContain("핀치");
    expect(DISPLAY_GESTURE_HINT).not.toContain("터치");
    expect(DISPLAY_GESTURE_HINT).toContain("측정값이 아닙니다");
  });
});
