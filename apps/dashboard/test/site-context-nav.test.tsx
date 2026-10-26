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

import { SiteContextNav } from "@/components/nav/SiteContextNav";
import type { SidebarSite } from "@/components/nav/site-context";

const sites: SidebarSite[] = [
  { siteId: "site-1", name: "Floreat public sample", status: "UNMAPPED" },
  { siteId: "site-2", name: "Product Sample Field", status: "BASELINE_MAPPING" },
];

afterEach(() => {
  cleanup();
  navigation.pathname = "/sites/site-1/spatial-assets";
  navigation.search = new URLSearchParams();
});

describe("site context in the desktop rail", () => {
  it("shows the current site and the four site sections with the active one marked", () => {
    render(<SiteContextNav sites={sites} />);
    expect(screen.getByText("Floreat public sample")).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: "현재 현장 메뉴" });
    expect(within(nav).getByRole("link", { name: "자료" }).getAttribute("aria-current")).toBe("page");
    expect(within(nav).getByRole("link", { name: "작업공간" }).getAttribute("aria-current")).toBeNull();
    expect(within(nav).getByRole("link", { name: "관측 작업" }).getAttribute("href")).toBe("/sites/site-1?section=work-orders");
    expect(within(nav).getByRole("link", { name: "결과" }).getAttribute("href")).toBe("/sites/site-1/analysis");
  });

  it("keeps the section when switching to another site", () => {
    render(<SiteContextNav sites={sites} />);
    fireEvent.click(screen.getByRole("button", { name: /현장 변경: Floreat public sample/ }));
    const dialog = screen.getByRole("dialog", { name: "현장 변경" });
    expect(within(dialog).getByRole("button", { name: /Floreat public sample/ }).getAttribute("aria-current")).toBe("true");
    expect(within(dialog).getByRole("link", { name: /Product Sample Field/ }).getAttribute("href")).toBe(
      "/sites/site-2/spatial-assets",
    );
    expect(within(dialog).getByRole("link", { name: /전체 현장/ }).getAttribute("href")).toBe("/sites");
  });

  it("marks the work ledger section from the site query", () => {
    navigation.pathname = "/sites/site-1";
    navigation.search = new URLSearchParams("section=work-orders");
    render(<SiteContextNav sites={sites} />);
    const nav = screen.getByRole("navigation", { name: "현재 현장 메뉴" });
    expect(within(nav).getByRole("link", { name: "관측 작업" }).getAttribute("aria-current")).toBe("page");
  });

  it("closes the switcher with Escape and returns focus to its trigger", () => {
    render(<SiteContextNav sites={sites} />);
    const trigger = screen.getByRole("button", { name: /현장 변경: Floreat public sample/ });
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "현장 변경" })).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes the switcher on an outside pointer press", () => {
    render(<SiteContextNav sites={sites} />);
    fireEvent.click(screen.getByRole("button", { name: /현장 변경: Floreat public sample/ }));
    expect(screen.getByRole("dialog", { name: "현장 변경" })).toBeTruthy();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
  });

  it("does not offer a switcher when only one site is visible", () => {
    render(<SiteContextNav sites={[sites[0]!]} />);
    expect(screen.queryByRole("button", { name: /현장 변경/ })).toBeNull();
    expect(screen.getByText("Floreat public sample")).toBeTruthy();
  });

  it("renders nothing outside a site route or without a matching site", () => {
    navigation.pathname = "/sites";
    const { container, rerender } = render(<SiteContextNav sites={sites} />);
    expect(container.innerHTML).toBe("");
    navigation.pathname = "/sites/site-1";
    rerender(<SiteContextNav sites={[]} />);
    expect(container.innerHTML).toBe("");
  });
});
