/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({ pathname: "/", search: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useSearchParams: () => navigation.search,
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) =>
    <a href={href} {...props}>{children}</a>,
}));

import { DesktopSidebar } from "@/components/nav/DesktopSidebar";
import { setDesktopNavCollapsed } from "@/components/nav/desktop-nav-preference";
import { installFakeLocalStorage } from "./storage-fakes";

const rail = () => screen.getByRole("navigation", { name: "주 메뉴" });

beforeEach(() => {
  // 이 jsdom 설정에는 localStorage가 없으므로 가짜를 깐다.
  installFakeLocalStorage();
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
  window.localStorage.clear();
  navigation.pathname = "/";
  navigation.search = new URLSearchParams();
});

describe("좌측 레일 (ADR-KSI-043)", () => {
  it("프로젝트 안에서는 공간·자료·분석을 위에, 작업·도움말을 아래에 둔다", () => {
    navigation.pathname = "/sites/site-1/analysis";
    render(<DesktopSidebar />);
    const links = within(rail()).getAllByRole("link").map((link) => [link.textContent, link.getAttribute("href")]);
    expect(links).toEqual([
      ["공간", "/sites/site-1"],
      ["자료", "/sites/site-1/data"],
      ["분석", "/sites/site-1/analysis"],
      ["작업", "/field"],
      ["도움말", "/help"],
    ]);
    expect(within(rail()).getByRole("link", { name: "분석" }).getAttribute("aria-current")).toBe("page");
    expect(within(rail()).getByRole("link", { name: "공간" }).getAttribute("aria-current")).toBeNull();
  });

  it("자료 화면과 공간의 자료 패널은 자료가 현재 위치다", () => {
    navigation.pathname = "/sites/site-1/data";
    navigation.search = new URLSearchParams("workAreaId=a1");
    const first = render(<DesktopSidebar />);
    expect(within(rail()).getByRole("link", { name: "자료" }).getAttribute("aria-current")).toBe("page");
    first.unmount();
    navigation.pathname = "/sites/site-1";
    navigation.search = new URLSearchParams("panel=materials");
    render(<DesktopSidebar />);
    expect(within(rail()).getByRole("link", { name: "자료" }).getAttribute("aria-current")).toBe("page");
    expect(within(rail()).getByRole("link", { name: "공간" }).getAttribute("aria-current")).toBeNull();
  });

  it("프로젝트 설정 화면에서는 어느 섹션도 현재 위치로 표시하지 않는다", () => {
    navigation.pathname = "/sites/site-1";
    navigation.search = new URLSearchParams("section=manage");
    render(<DesktopSidebar />);
    for (const name of ["공간", "자료", "분석"]) {
      expect(within(rail()).getByRole("link", { name }).getAttribute("aria-current")).toBeNull();
    }
  });

  it("프로젝트 밖에서는 홈·프로젝트를 위에 두고 프로젝트 섹션을 숨긴다", () => {
    navigation.pathname = "/sites";
    render(<DesktopSidebar counts={{ sites: { value: 3 } }} />);
    const links = within(rail()).getAllByRole("link").map((link) => link.getAttribute("href"));
    expect(links).toEqual(["/", "/sites", "/field", "/help"]);
    expect(within(rail()).queryByRole("link", { name: "공간" })).toBeNull();
    expect(within(rail()).getByRole("link", { name: /프로젝트/ }).textContent).toContain("3");
    expect(within(rail()).getByRole("link", { name: /프로젝트/ }).getAttribute("aria-current")).toBe("page");
  });

  it("등록 화면(/sites/new)은 프로젝트 안이 아니다", () => {
    navigation.pathname = "/sites/new";
    render(<DesktopSidebar />);
    expect(within(rail()).queryByRole("link", { name: "공간" })).toBeNull();
  });

  it("건수가 없으면 배지를 그리지 않는다(0 과 모름을 같게 보이지 않는다)", () => {
    navigation.pathname = "/sites";
    const { container } = render(<DesktopSidebar counts={{}} />);
    expect(container.querySelector(".rail-count")).toBeNull();
  });

  it("긴급 건수는 긴급 표시를 단다", () => {
    navigation.pathname = "/";
    const { container } = render(<DesktopSidebar counts={{ work: { value: 2, urgent: true } }} />);
    expect(container.querySelector('.rail-count[data-urgent="true"]')?.textContent).toBe("2");
    expect(container.querySelector('.rail-dot[data-urgent="true"]')).not.toBeNull();
  });

  it("접으면 라벨 대신 이름·건수를 aria-label로 읽히고 툴팁 글을 단다", () => {
    navigation.pathname = "/";
    setDesktopNavCollapsed(true);
    render(<DesktopSidebar counts={{ work: { value: 2 } }} />);
    expect(rail().getAttribute("data-collapsed")).toBe("true");
    expect(rail().getAttribute("data-compact-rail")).toBe("true");
    const work = within(rail()).getByRole("link", { name: "작업, 2건" });
    expect(work.getAttribute("data-tip")).toBe("작업");
    expect(within(rail()).getByRole("button", { name: "주 메뉴 펼치기" }).getAttribute("aria-expanded")).toBe("false");
  });

  it("펼친 상태에서도 이름을 aria-label 로 둔다(1024px 미만에서는 라벨이 CSS 로 감춰진다)", () => {
    navigation.pathname = "/";
    render(<DesktopSidebar />);
    expect(rail().getAttribute("data-collapsed")).toBe("false");
    expect(within(rail()).getByRole("link", { name: "홈" }).getAttribute("aria-label")).toBe("홈");
    expect(within(rail()).getByRole("button", { name: "주 메뉴 접기" }).getAttribute("aria-expanded")).toBe("true");
  });

  it("로그인 화면에는 레일이 없다", () => {
    navigation.pathname = "/login";
    const { container } = render(<DesktopSidebar />);
    expect(container.innerHTML).toBe("");
  });
});
