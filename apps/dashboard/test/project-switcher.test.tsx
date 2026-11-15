/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({
  pathname: "/sites/site-1/spatial-assets",
  search: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useSearchParams: () => navigation.search,
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) =>
    <a href={href} {...props}>{children}</a>,
}));

import { ProjectSwitcher } from "@/components/nav/ProjectSwitcher";
import { SiteListProvider } from "@/components/nav/SiteListContext";
import type { SidebarSite } from "@/components/nav/site-context";

const fingerprint = `v1-${"a".repeat(64)}`;
const sites: SidebarSite[] = [
  { siteId: "site-1", name: "Floreat public sample", status: "UNMAPPED" },
  { siteId: "site-2", name: "Product Sample Field", status: "BASELINE_MAPPING" },
];

function renderSwitcher(list: SidebarSite[] = sites) {
  return render(<SiteListProvider sites={list} fingerprint={fingerprint}><ProjectSwitcher /></SiteListProvider>);
}
const trigger = () => screen.getByRole("button", { name: /프로젝트 (변경|선택)/ });

afterEach(() => {
  cleanup();
  navigation.pathname = "/sites/site-1/spatial-assets";
  navigation.search = new URLSearchParams();
});

describe("header project switcher", () => {
  it("names the current project on the trigger and links its settings separately", () => {
    renderSwitcher();
    expect(trigger().getAttribute("aria-label")).toBe("프로젝트 변경: Floreat public sample");
    expect(screen.getByText("Floreat public sample")).toBeTruthy();
    expect(screen.getByRole("link", { name: "프로젝트 설정" }).getAttribute("href")).toBe("/sites/site-1?section=manage");
  });

  it("lists every visible project, marks the current one and links to all projects", () => {
    renderSwitcher();
    fireEvent.click(trigger());
    const dialog = screen.getByRole("dialog", { name: "프로젝트 변경" });
    expect(within(dialog).getByRole("button", { name: /Floreat public sample/ }).getAttribute("aria-current")).toBe("true");
    expect(within(dialog).getByRole("link", { name: /Product Sample Field/ }).getAttribute("href")).toBe("/sites/site-2");
    expect(within(dialog).getByRole("link", { name: /전체 프로젝트 \(2\)/ }).getAttribute("href")).toBe("/sites");
  });

  it("keeps the analysis section when switching", () => {
    navigation.pathname = "/sites/site-1/analysis";
    renderSwitcher();
    fireEvent.click(trigger());
    expect(screen.getByRole("link", { name: /Product Sample Field/ }).getAttribute("href")).toBe("/sites/site-2/analysis");
  });

  it("keeps the data section when switching", () => {
    navigation.pathname = "/sites/site-1/data";
    navigation.search = new URLSearchParams();
    renderSwitcher();
    fireEvent.click(trigger());
    expect(screen.getByRole("link", { name: /Product Sample Field/ }).getAttribute("href")).toBe("/sites/site-2/data");
  });

  it("filters by name and says so when nothing matches", () => {
    renderSwitcher();
    fireEvent.click(trigger());
    const search = screen.getByRole("searchbox", { name: "프로젝트 검색" });
    fireEvent.change(search, { target: { value: "product" } });
    const dialog = screen.getByRole("dialog", { name: "프로젝트 변경" });
    expect(within(dialog).queryByRole("button", { name: /Floreat/ })).toBeNull();
    expect(within(dialog).getByRole("link", { name: /Product Sample Field/ })).toBeTruthy();
    fireEvent.change(search, { target: { value: "없는 이름" } });
    expect(screen.getByRole("status").textContent).toContain("검색과 맞는 프로젝트가 없습니다");
  });

  it("does not call an empty list a search miss", () => {
    renderSwitcher([]);
    fireEvent.click(trigger());
    expect(screen.getByRole("status").textContent).toContain("접근할 수 있는 프로젝트가 없습니다");
  });

  it("moves focus through the list with the arrow keys", () => {
    renderSwitcher();
    fireEvent.click(trigger());
    const dialog = screen.getByRole("dialog", { name: "프로젝트 변경" });
    const current = within(dialog).getByRole("button", { name: /Floreat public sample/ });
    current.focus();
    fireEvent.keyDown(current, { key: "ArrowDown" });
    expect(document.activeElement).toBe(within(dialog).getByRole("link", { name: /Product Sample Field/ }));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    expect(document.activeElement).toBe(current);
  });

  it("closes with Escape and returns focus to the trigger", () => {
    renderSwitcher();
    fireEvent.click(trigger());
    expect(screen.getByRole("dialog", { name: "프로젝트 변경" })).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "프로젝트 변경" })).toBeNull();
    expect(document.activeElement).toBe(trigger());
  });

  it("closes on an outside pointer press without stealing focus", () => {
    renderSwitcher();
    fireEvent.click(trigger());
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog", { name: "프로젝트 변경" })).toBeNull();
    expect(document.activeElement).not.toBe(trigger());
  });

  it("offers the list but no current project or settings outside a project", () => {
    navigation.pathname = "/sites";
    renderSwitcher();
    expect(trigger().getAttribute("aria-label")).toBe("프로젝트 선택");
    expect(screen.getByText("프로젝트 선택")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "프로젝트 설정" })).toBeNull();
    fireEvent.click(trigger());
    expect(screen.queryByText("현재 프로젝트")).toBeNull();
    expect(screen.getByRole("link", { name: /Floreat public sample/ }).getAttribute("href")).toBe("/sites/site-1");
  });

  it("does not treat the registration route as a project", () => {
    navigation.pathname = "/sites/new";
    renderSwitcher();
    expect(trigger().getAttribute("aria-label")).toBe("프로젝트 선택");
    expect(screen.queryByRole("link", { name: "프로젝트 설정" })).toBeNull();
  });
});
