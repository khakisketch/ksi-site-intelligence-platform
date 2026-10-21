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
  wheelZoomFactor,
  zoomDisplayView,
  zoomDisplayViewAt,
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

  it("keeps the zoom point under the cursor instead of always recentering", () => {
    // 왼쪽 가장자리에서 확대하면 보이는 중심이 왼쪽으로 간다.
    const zoomed = zoomDisplayViewAt(DISPLAY_VIEW_DEFAULT, 2, 0, 0.5);
    expect(zoomed.moved).toBe(true);
    expect(zoomed.view.zoom).toBe(2);
    expect(zoomed.view.cx).toBeLessThan(0.5);
    expect(zoomed.view.cy).toBe(0.5);
    // 오른쪽 가장자리면 반대로 간다.
    const right = zoomDisplayViewAt(DISPLAY_VIEW_DEFAULT, 2, 1, 0.5);
    expect(right.view.cx).toBeGreaterThan(0.5);
    // 범위를 벗어난 커서는 프레임 안으로 둔다.
    expect(zoomDisplayViewAt(DISPLAY_VIEW_DEFAULT, 2, -5, 99).view.cx).toBe(
      zoomDisplayViewAt(DISPLAY_VIEW_DEFAULT, 2, 0, 1).view.cx,
    );
    // 1이 아닌 배율은 그대로 두지 않는다.
    expect(zoomDisplayViewAt(DISPLAY_VIEW_DEFAULT, 0, 0.5, 0.5).moved).toBe(false);
    expect(zoomDisplayViewAt(DISPLAY_VIEW_DEFAULT, Number.NaN, 0.5, 0.5).moved).toBe(false);
  });

  it("converts wheel deltas to smooth bounded steps without 2x jumps", () => {
    expect(wheelZoomFactor(0, 0)).toBe(1);
    expect(wheelZoomFactor(100, 0)).toBeCloseTo(Math.SQRT1_2, 10);
    expect(wheelZoomFactor(-100, 0)).toBeCloseTo(Math.SQRT2, 10);
    // 트랙패드 작은 델타는 작은 단계다.
    expect(wheelZoomFactor(-10, 0)).toBeGreaterThan(1);
    expect(wheelZoomFactor(-10, 0)).toBeLessThan(1.1);
    // 큰 델타도 한 번에 한 걸음까지만 둔다.
    expect(wheelZoomFactor(-1000, 0)).toBe(wheelZoomFactor(-100, 0));
    expect(wheelZoomFactor(Number.NaN, 0)).toBe(1);
  });

  it("pans in visible-window fractions and clamps at the visible edge, not the source edge", () => {
    const zoomed = zoomDisplayView(DISPLAY_VIEW_DEFAULT, 1).view;
    // 보이는 창의 1/4만큼 오른쪽을 본다.
    const panned = panDisplayView(zoomed, 0.25, 0);
    expect(panned.moved).toBe(true);
    expect(panned.view.cx).toBeCloseTo(0.5 + 0.25 / 2, 10);
    expect(panned.view.cy).toBe(0.5);
    expect(panned.view.zoom).toBe(2);
    // 전체 보기에서도 자연스럽게 움직인다 — 빈 곳은 미확인 범위다.
    const fromFull = panDisplayView(DISPLAY_VIEW_DEFAULT, 0.25, 0);
    expect(fromFull.moved).toBe(true);
    expect(fromFull.view.cx).toBeCloseTo(0.75, 10);
    // 끝까지 민 뒤에는 같은 안내 규칙으로 멈춘다(버퍼를 버리지 않는다).
    const edge = panDisplayView(fromFull.view, 10, 0);
    expect(edge.view.cx).toBeCloseTo(1.25, 10);
    expect(edge.moved).toBe(true);
    const stuck = panDisplayView(edge.view, 10, 0);
    expect(stuck.moved).toBe(false);
    expect(stuck.view.cx).toBeCloseTo(1.25, 10);
    // 위·아래도 같은 규칙이다.
    expect(panDisplayView(DISPLAY_VIEW_DEFAULT, 0, -10).view.cy).toBeCloseTo(-0.25, 10);
  });

  it("ignores non-finite drag input instead of inventing a view", () => {
    expect(displayDragFractions(Number.NaN, 0, 400, 300)).toBeNull();
    expect(displayDragFractions(0, 0, 0, 300)).toBeNull();
    // 내용은 커서를 따라간다: 오른쪽·아래 드래그는 중심을 왼쪽·위로 둔다.
    // 분모는 늘이기 전 그림 자체의 너비다(바깥 프레임이 아니다).
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
    expect(clampDisplayView({ zoom: 99, cx: -1, cy: 2 })).toEqual({ zoom: 4, cx: -0.0625, cy: 1.0625 });
    expect(clampDisplayView({ zoom: 0.5, cx: 0.5, cy: 0.5 })).toEqual(DISPLAY_VIEW_DEFAULT);
  });
});
