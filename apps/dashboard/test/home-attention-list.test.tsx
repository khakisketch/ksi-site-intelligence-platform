// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { HomeAttentionList, type HomeAttentionCardView } from "@/app/HomeAttentionList";

afterEach(cleanup);

function card(overrides: Partial<HomeAttentionCardView> = {}): HomeAttentionCardView {
  return {
    key: "card-1",
    siteName: "A 현장",
    label: "분석 검토 대기",
    title: "무엇이 달라졌는가",
    detail: "세부 내용",
    timeLabel: "현장 갱신",
    observedAt: "2026. 10. 21. 01:17",
    href: "/sites/site-1",
    actionLabel: "분석 결과 검토",
    image: null,
    ...overrides,
  };
}

describe("HomeAttentionList", () => {
  it("reads site, agenda kind, time basis, title, detail and action as text without a large cover", () => {
    render(<HomeAttentionList items={[card()]} />);
    expect(screen.getByText("A 현장")).toBeTruthy();
    expect(screen.getByText("분석 검토 대기")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "무엇이 달라졌는가" })).toBeTruthy();
    expect(screen.getByText("세부 내용")).toBeTruthy();
    expect(screen.getByText("현장 갱신 2026. 10. 21. 01:17")).toBeTruthy();
    expect(screen.getByRole("link", { name: "분석 결과 검토" }).getAttribute("href")).toBe("/sites/site-1");
    const article = document.querySelector("article")!;
    expect(article.querySelector("figure")).toBeNull();
    expect(article.querySelector("img")).toBeNull();
    expect(article.querySelector("[class*='min-h-[']")).toBeNull();
  });

  it("is a vertical list with one article per agenda and no paging controls", () => {
    render(<HomeAttentionList items={[card({ key: "a" }), card({ key: "b", siteName: "B 현장" }), card({ key: "c" })]} />);
    const region = screen.getByRole("region", { name: "확인 필요 현장 목록" });
    expect(within(region).getAllByRole("article")).toHaveLength(3);
    expect(within(region).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("button", { name: /이전 현장|다음 현장|번째 현장/ })).toBeNull();
    expect(region.querySelector("[class*='overflow-x-auto'], [class*='snap-']")).toBeNull();
  });

  it("keeps the caller's priority order", () => {
    render(<HomeAttentionList items={[card({ key: "first", title: "첫째" }), card({ key: "second", title: "둘째" })]} />);
    const headings = screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent);
    expect(headings).toEqual(["첫째", "둘째"]);
  });

  it("labels the actual time semantic instead of implying a capture time", () => {
    render(<HomeAttentionList items={[card({ timeLabel: "분석 생성", observedAt: "2026. 10. 15. 10:00" })]} />);
    const article = document.querySelector("article")!;
    expect(article.textContent).toContain("분석 생성 2026. 10. 15. 10:00");
    expect(article.textContent).not.toMatch(/촬영일|촬영 시각|관측일시/);
  });

  it("does not imply missing site artifacts from a null image prop", () => {
    render(<HomeAttentionList items={[card()]} />);
    const article = document.querySelector("article")!;
    expect(article.textContent).not.toMatch(/관측 이미지 없음|관측자료 없음|자료 없음/);
    // 표식은 사진이 아님을 보조기술에 밝힌다.
    expect(within(article).getByRole("img").getAttribute("aria-label")).toContain("실제 영상 미리보기가 아닙니다");
  });

  it("renders a bounded thumbnail only for an authorized evidence image", () => {
    render(<HomeAttentionList items={[card({ image: { src: "https://evidence.invalid/p?exp=1", alt: "관측 근거 미리보기" } })]} />);
    const figure = document.querySelector("article figure");
    expect(figure).not.toBeNull();
    const img = figure!.querySelector("img")!;
    expect(img.getAttribute("src")).toBe("https://evidence.invalid/p?exp=1");
    expect(img.getAttribute("alt")).toBe("관측 근거 미리보기");
    expect(img.className).not.toMatch(/min-h-\[/);
  });

  it("offers technical references only when present, folded", () => {
    const { rerender } = render(<HomeAttentionList items={[card()]} />);
    expect(screen.queryByText("식별 상세")).toBeNull();
    rerender(<HomeAttentionList items={[card({ technicalRef: "analysis-1 · area-2" })]} />);
    expect(screen.getByText("식별 상세").closest("details")).not.toBeNull();
  });
});
