/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SiteFootprint, projectFootprint } from "@/components/site/SiteFootprint";

afterEach(cleanup);

const SQUARE = [
  { latDeg: 37.5, lonDeg: 127.0 },
  { latDeg: 37.5, lonDeg: 127.001 },
  { latDeg: 37.501, lonDeg: 127.001 },
  { latDeg: 37.501, lonDeg: 127.0 },
];
const BOX = { w: 320, h: 180, pad: 28 };

describe("projectFootprint", () => {
  it("keeps every vertex inside the padded box and puts north up", () => {
    const points = projectFootprint(SQUARE, BOX)!;
    expect(points).toHaveLength(4);
    for (const [x, y] of points) {
      expect(x).toBeGreaterThanOrEqual(BOX.pad - 0.01);
      expect(x).toBeLessThanOrEqual(BOX.w - BOX.pad + 0.01);
      expect(y).toBeGreaterThanOrEqual(BOX.pad - 0.01);
      expect(y).toBeLessThanOrEqual(BOX.h - BOX.pad + 0.01);
    }
    // 위도가 큰 꼭짓점(북쪽)이 화면 위쪽(작은 y)에 놓인다.
    expect(points[2]![1]).toBeLessThan(points[0]![1]);
    // 경도가 큰 꼭짓점(동쪽)이 화면 오른쪽에 놓인다.
    expect(points[1]![0]).toBeGreaterThan(points[0]![0]);
  });

  it("refuses to invent a shape from fewer than three or degenerate vertices", () => {
    expect(projectFootprint(null, BOX)).toBeNull();
    expect(projectFootprint(SQUARE.slice(0, 2), BOX)).toBeNull();
    expect(projectFootprint([SQUARE[0]!, SQUARE[0]!, SQUARE[0]!], BOX)).toBeNull();
    expect(projectFootprint([...SQUARE.slice(0, 2), { latDeg: Number.NaN, lonDeg: 127 }], BOX)).toBeNull();
  });
});

describe("SiteFootprint", () => {
  it("draws the registered boundary and says it is not imagery or evidence", () => {
    render(<SiteFootprint vertices={SQUARE} siteName="A 현장" />);
    const figure = screen.getByRole("img");
    expect(figure.getAttribute("aria-label")).toContain("A 현장 등록 경계 도형");
    expect(figure.getAttribute("aria-label")).toContain("실제 영상 미리보기가 아닙니다");
    expect(figure.getAttribute("aria-label")).toContain("측량·정확도 근거가 아닙니다");
    expect(figure.getAttribute("data-site-footprint")).toBe("shape");
    expect(figure.querySelector("polygon")).not.toBeNull();
    expect(screen.getByText("등록 경계")).toBeTruthy();
    expect(screen.getByText("영상 아님")).toBeTruthy();
  });

  it("does not print coordinates, area or scale", () => {
    render(<SiteFootprint vertices={SQUARE} siteName="A 현장" />);
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/37\.5|127\.0|㎡|m²|ha\b|축척/);
    expect(document.querySelector("image, img, foreignObject")).toBeNull();
  });

  it("says no boundary is registered instead of implying missing data", () => {
    render(<SiteFootprint vertices={null} siteName="B 현장" />);
    const figure = screen.getByRole("img");
    expect(figure.getAttribute("data-site-footprint")).toBe("none");
    expect(figure.getAttribute("aria-label")).toContain("등록 경계 없음");
    expect(figure.querySelector("polygon")).toBeNull();
    expect(screen.getByText("경계 미등록")).toBeTruthy();
    expect(figure.textContent).not.toMatch(/자료 없음|관측 없음/);
  });

  it("shows the preview state as a chip with its tone and can be hidden from assistive tech", () => {
    const { rerender } = render(<SiteFootprint vertices={SQUARE} siteName="A 현장" stateLabel="미리보기 권한 없음" tone="refused" />);
    expect(screen.getByText("미리보기 권한 없음").className).toContain("bg-crit-bg");
    expect(screen.getByRole("img").getAttribute("data-site-visual-placeholder")).toBe("refused");
    rerender(<SiteFootprint vertices={SQUARE} siteName="A 현장" size="row" decorative />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(document.querySelector("[aria-hidden='true'][data-site-footprint]")).not.toBeNull();
  });
});
