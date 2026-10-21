import { describe, expect, it } from "vitest";

import {
  DISPLAY_GESTURE_HINT,
  displayGestureKeyAction,
} from "@/lib/spatial-display-gesture";

describe("display gesture rules", () => {
  it("maps arrow keys to the same quarter-step pan as the buttons", () => {
    expect(displayGestureKeyAction("ArrowLeft")).toEqual({ kind: "pan", dCol: -0.25, dRow: 0 });
    expect(displayGestureKeyAction("ArrowRight")).toEqual({ kind: "pan", dCol: 0.25, dRow: 0 });
    expect(displayGestureKeyAction("ArrowUp")).toEqual({ kind: "pan", dCol: 0, dRow: 0.25 });
    expect(displayGestureKeyAction("ArrowDown")).toEqual({ kind: "pan", dCol: 0, dRow: -0.25 });
  });

  it("maps plus/minus to zoom steps and Home to full view", () => {
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

  it("hints only implemented gestures", () => {
    expect(DISPLAY_GESTURE_HINT).toContain("끌어서");
    expect(DISPLAY_GESTURE_HINT).toContain("휠");
    expect(DISPLAY_GESTURE_HINT).toContain("두 손가락");
    expect(DISPLAY_GESTURE_HINT).toContain("두 번 두드리기");
    expect(DISPLAY_GESTURE_HINT).toContain("방향키");
    expect(DISPLAY_GESTURE_HINT).toContain("측정값이 아닙니다");
  });
});
