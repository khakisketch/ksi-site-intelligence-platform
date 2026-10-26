// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HomeAttentionCarousel, type HomeAttentionCardView } from "@/app/HomeAttentionCarousel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

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

describe("HomeAttentionCarousel", () => {
  it("renders content-first briefing without a decorative visual when no image exists", () => {
    render(<HomeAttentionCarousel items={[card()]} />);
    // 현장명·안건·근거 시점·행동이 텍스트로 먼저 읽힌다.
    expect(screen.getByText("A 현장")).toBeTruthy();
    expect(screen.getByText("분석 검토 대기")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "무엇이 달라졌는가" })).toBeTruthy();
    expect(screen.getByText("세부 내용")).toBeTruthy();
    expect(screen.getByText("현장 갱신 2026. 10. 21. 01:17")).toBeTruthy();
    const action = screen.getByRole("link", { name: "분석 결과 검토" });
    expect(action.getAttribute("href")).toBe("/sites/site-1");
    // 장식 figure·img·고정 큰 시각 블록이 없다 — D7 내용 우선.
    // (CTA 화살표 같은 기능 아이콘 svg는 제외한다.)
    expect(document.querySelector("article figure")).toBeNull();
    expect(document.querySelector("article img")).toBeNull();
    expect(document.querySelector("article [class*='min-h-']")).toBeNull();
  });

  it("labels the actual time semantic instead of implying a capture time", () => {
    render(<HomeAttentionCarousel items={[card({ timeLabel: "분석 생성", observedAt: "2026. 10. 15. 10:00" })]} />);
    const article = document.querySelector("article")!;
    expect(article.textContent).toContain("분석 생성 2026. 10. 15. 10:00");
    expect(article.textContent).not.toMatch(/촬영일|촬영 시각|관측일시/);
  });

  it("does not imply missing site artifacts from a null image prop", () => {
    render(<HomeAttentionCarousel items={[card()]} />);
    const article = document.querySelector("article")!;
    // 조회하지 않은 미리보기의 부재를 등록 자료의 부재로 말하지 않는다.
    // 기본 표지는 시각적 자리만 채우며, 실제 영상이 아님을 명시한다.
    expect(article.textContent).not.toMatch(/관측 이미지 없음|관측자료 없음|자료 없음/);
    expect(article.textContent).toContain("기본 표지");
    expect(article.textContent).toContain("실제 영상 아님");
  });

  it("renders a bounded figure only for an authorized evidence image", () => {
    render(
      <HomeAttentionCarousel
        items={[card({ image: { src: "https://evidence.invalid/p?exp=1", alt: "관측 근거 미리보기" } })]}
      />,
    );
    const figure = document.querySelector("article figure");
    expect(figure).not.toBeNull();
    const img = figure!.querySelector("img")!;
    expect(img.getAttribute("src")).toBe("https://evidence.invalid/p?exp=1");
    expect(img.getAttribute("alt")).toBe("관측 근거 미리보기");
    // 경계 있는 작은 figure 다 — 거대 고정 hero 가 아니다.
    expect(img.className).not.toMatch(/min-h-\[/);
    expect(figure!.querySelector("svg")).toBeNull();
  });

  it("gives exactly one pagination signal when several sites are shown", () => {
    render(<HomeAttentionCarousel items={[card({ key: "a" }), card({ key: "b" }), card({ key: "c" })]} />);
    // Dots remain the one interactive position indicator.
    expect(screen.getAllByRole("button", { name: /번째 현장:/ })).toHaveLength(3);
    // The redundant "N / M" numeric counter must be gone.
    expect(screen.queryByText(/1\s*\/\s*3/)).toBeNull();
  });

  it("moves one card at a time with keyboard-focusable controls and announces position", () => {
    const scrollTo = vi.fn();
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false }) as unknown as MediaQueryList));
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 360 });
    render(<HomeAttentionCarousel items={[card({ key: "a" }), card({ key: "b", siteName: "B 현장" })]} />);
    const track = screen.getByRole("region", { name: "확인 필요 현장 캐러셀" });
    track.scrollTo = scrollTo;
    const prev = screen.getByRole("button", { name: "이전 현장" });
    const next = screen.getByRole("button", { name: "다음 현장" });
    expect(prev.hasAttribute("disabled")).toBe(true);
    next.focus();
    expect(document.activeElement).toBe(next);
    fireEvent.click(next);
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ left: 360, behavior: "smooth" }));
    expect(screen.getByRole("button", { name: "2번째 현장: B 현장" }).getAttribute("aria-current")).toBe("true");
    expect(screen.getAllByText("B 현장", { selector: "p" }).length).toBeGreaterThanOrEqual(1);
    delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
  });

  it("honors reduced motion when moving between cards", () => {
    const scrollTo = vi.fn();
    const matchMedia = vi.fn(() => ({ matches: true }) as unknown as MediaQueryList);
    vi.stubGlobal("matchMedia", matchMedia);
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 360 });
    render(<HomeAttentionCarousel items={[card({ key: "a" }), card({ key: "b" })]} />);
    screen.getByRole("region", { name: "확인 필요 현장 캐러셀" }).scrollTo = scrollTo;
    fireEvent.click(screen.getByRole("button", { name: "다음 현장" }));
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: "auto" }));
    expect(matchMedia).toHaveBeenCalledWith("(prefers-reduced-motion: reduce)");
    delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
  });
});
