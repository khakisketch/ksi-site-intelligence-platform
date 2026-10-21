import { describe, expect, it } from "vitest";

import {
  clampDisplayView,
  DISPLAY_VIEW_DEFAULT,
  displayDragFractions,
  displayViewTransform,
  displayZoomPercent,
  isDisplayViewMoved,
  panDisplayView,
  resetDisplayView,
  zoomDisplayView,
} from "@/lib/spatial-display-view";

describe("display view state", () => {
  it("stays on the full frame by default and reports no movement", () => {
    expect(DISPLAY_VIEW_DEFAULT).toEqual({ zoom: 1, cx: 0.5, cy: 0.5 });
    expect(displayViewTransform(DISPLAY_VIEW_DEFAULT)).toBe("translate(0% , 0%) scale(1)");
    expect(displayZoomPercent(DISPLAY_VIEW_DEFAULT)).toBe(100);
    expect(isDisplayViewMoved(DISPLAY_VIEW_DEFAULT)).toBe(false);
  });

  it("zooms about the current center in doubling steps to a bounded max", () => {
    const first = zoomDisplayView(DISPLAY_VIEW_DEFAULT, 1);
    expect(first).toEqual({ view: { zoom: 2, cx: 0.5, cy: 0.5 }, moved: true });
    const second = zoomDisplayView(first.view, 1);
    expect(second.view.zoom).toBe(4);
    expect(second.moved).toBe(true);
    // 상한에서 더 확대해도 원본 버퍼는 그대로 둔다.
    const capped = zoomDisplayView(second.view, 1);
    expect(capped.view.zoom).toBe(4);
    expect(capped.moved).toBe(false);
    const back = zoomDisplayView(capped.view, -1);
    expect(back.view.zoom).toBe(2);
  });

  it("pans in visible-window fractions and clamps at the source edge with stable aspect", () => {
    const zoomed = zoomDisplayView(DISPLAY_VIEW_DEFAULT, 1).view;
    // 보이는 창의 1/4만큼 오른쪽을 본다.
    const panned = panDisplayView(zoomed, 0.25, 0);
    expect(panned.moved).toBe(true);
    expect(panned.view.cx).toBeCloseTo(0.5 + 0.25 / 2, 10);
    expect(panned.view.cy).toBe(0.5);
    expect(panned.view.zoom).toBe(2);
    // 끝까지 민 뒤에는 같은 안내 규칙으로 멈춘다(크기 축소 없음).
    const edge = panDisplayView(panned.view, 10, 0);
    expect(edge.view.cx).toBe(0.75);
    expect(edge.moved).toBe(true);
    const stuck = panDisplayView(edge.view, 10, 0);
    expect(stuck.moved).toBe(false);
    expect(stuck.view.cx).toBe(0.75);
    // 전체 보기에서는 이동이 성립하지 않는다.
    expect(panDisplayView(DISPLAY_VIEW_DEFAULT, 0.25, 0).moved).toBe(false);
  });

  it("ignores non-finite drag input instead of inventing a view", () => {
    expect(displayDragFractions(Number.NaN, 0, 400, 300)).toBeNull();
    expect(displayDragFractions(0, 0, 0, 300)).toBeNull();
    // 내용은 커서를 따라간다: 오른쪽·아래 드래그는 중심을 왼쪽·위로 둔다.
    expect(displayDragFractions(100, 60, 400, 300)).toEqual({ fx: -0.25, fy: -0.2 });
  });

  it("renders the transform from the same state without resizing the source", () => {
    const zoomed = zoomDisplayView(DISPLAY_VIEW_DEFAULT, 1).view;
    const moved = panDisplayView(zoomed, 0.25, 0.25).view;
    expect(displayViewTransform(moved)).toContain("scale(2)");
    expect(displayZoomPercent(moved)).toBe(200);
    expect(isDisplayViewMoved(moved)).toBe(true);
    // 리셋은 전체 보기로 정확히 돌아간다.
    expect(resetDisplayView()).toEqual(DISPLAY_VIEW_DEFAULT);
    expect(clampDisplayView({ zoom: 99, cx: -1, cy: 2 })).toEqual({ zoom: 4, cx: 0.125, cy: 0.875 });
    expect(clampDisplayView({ zoom: 0.5, cx: 0.5, cy: 0.5 })).toEqual(DISPLAY_VIEW_DEFAULT);
  });
});
