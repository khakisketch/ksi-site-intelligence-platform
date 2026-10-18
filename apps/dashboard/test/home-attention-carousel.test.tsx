// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { HomeAttentionCarousel, type HomeAttentionCardView } from "@/app/HomeAttentionCarousel";

afterEach(cleanup);

function card(overrides: Partial<HomeAttentionCardView> = {}): HomeAttentionCardView {
  return {
    key: "card-1",
    siteName: "A 현장",
    label: "관측 근거",
    title: "무엇이 달라졌는가",
    detail: "세부 내용",
    observedAt: "9.17. 09:00",
    href: "/sites/site-1",
    actionLabel: "현장 열기",
    image: null,
    imageFallback: { label: "관측 이미지 없음", detail: "현장 상태는 기록되어 있습니다." },
    ...overrides,
  };
}

describe("HomeAttentionCarousel", () => {
  it("applies a decorative default visual when no observation image exists", () => {
    render(<HomeAttentionCarousel items={[card()]} />);
    const positioningWrapper = screen.getByText("관측 이미지 없음").closest("div")?.parentElement;
    expect(positioningWrapper?.className).not.toContain("place-items-center");
    // Approved height stays; the notice remains a corner badge, not a box over the area.
    expect(positioningWrapper?.className).toContain("lg:min-h-[330px]");
    // 기본 표시는 장식이다 — 이름을 따로 붙이지 않고(같은 말을 두 번 읽지 않음),
    // 데이터로 오인될 측정점·경계 폴리곤을 그리지 않는다.
    const visual = positioningWrapper?.querySelector("svg");
    expect(visual).not.toBeNull();
    expect(visual?.parentElement?.getAttribute("aria-hidden")).toBe("true");
    expect(visual?.parentElement?.getAttribute("role")).toBeNull();
    expect(visual?.querySelector("circle, polygon, line")).toBeNull();
    expect(positioningWrapper?.textContent).toContain("A 현장");
    expect(positioningWrapper?.textContent).toContain("9.17. 09:00");
  });

  it("gives exactly one pagination signal when several sites are shown", () => {
    render(<HomeAttentionCarousel items={[card({ key: "a" }), card({ key: "b" }), card({ key: "c" })]} />);
    // Dots remain the one interactive position indicator.
    expect(screen.getAllByRole("button", { name: /번째 현장:/ })).toHaveLength(3);
    // The redundant "N / M" numeric counter must be gone.
    expect(screen.queryByText(/1\s*\/\s*3/)).toBeNull();
  });
});
