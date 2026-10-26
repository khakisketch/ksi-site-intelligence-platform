/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopSidebar } from "@/components/nav/DesktopSidebar";
import { ShellLayoutMode } from "@/components/nav/ShellPathBoundary";
import { setDesktopNavCollapsed } from "@/components/nav/desktop-nav-preference";

const route = vi.hoisted(() => ({ pathname: "/sites/site-1/spatial-assets", query: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  usePathname: () => route.pathname,
  useSearchParams: () => route.query,
}));
vi.mock("@/components/nav/SidebarSearchTrigger", () => ({ SidebarSearchTrigger: () => <button>검색</button> }));

function shell() { return <><ShellLayoutMode /><DesktopSidebar /></>; }

beforeEach(() => {
  window.localStorage.clear();
  route.pathname = "/sites/site-1/spatial-assets";
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  document.body.className = "";
});

describe("user-controlled desktop navigation", () => {
  it("keeps labelled navigation by default on viewer routes", () => {
    render(shell());
    expect(screen.getByRole("button", { name: "주 메뉴 접기" }).getAttribute("aria-expanded")).toBe("true");
    expect(document.body.classList.contains("viewer-shell")).toBe(true);
    expect(document.body.classList.contains("desktop-nav-collapsed")).toBe(false);
  });

  it("persists explicit choice through dense/viewer navigation, reload and focus return", () => {
    const view = render(shell());
    fireEvent.click(screen.getByRole("button", { name: "주 메뉴 접기" }));
    let expand = screen.getByRole("button", { name: "주 메뉴 펼치기" });
    expect(document.activeElement).toBe(expand);
    expect(document.body.classList.contains("desktop-nav-collapsed")).toBe(true);
    route.pathname = "/field/inbox";
    view.rerender(shell());
    expect(screen.getByRole("button", { name: "주 메뉴 펼치기" })).toBeTruthy();
    expect(document.body.classList.contains("viewer-shell")).toBe(false);
    view.unmount();
    render(shell());
    expand = screen.getByRole("button", { name: "주 메뉴 펼치기" });
    fireEvent.click(expand);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "주 메뉴 접기" }));
    expect(document.body.classList.contains("desktop-nav-collapsed")).toBe(false);
  });

  it("responds to cross-tab preference reset and removes the compact grid at login", () => {
    const view = render(shell());
    act(() => setDesktopNavCollapsed(true));
    act(() => {
      window.localStorage.clear();
      window.dispatchEvent(new StorageEvent("storage", { key: null }));
    });
    expect(screen.getByRole("button", { name: "주 메뉴 접기" })).toBeTruthy();
    act(() => setDesktopNavCollapsed(true));
    route.pathname = "/login";
    view.rerender(shell());
    expect(screen.queryByRole("navigation", { name: "주 메뉴" })).toBeNull();
    expect(document.body.classList.contains("desktop-nav-collapsed")).toBe(false);
  });

  it("still toggles when browser storage is denied", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denied"); });
    act(() => setDesktopNavCollapsed(false));
    render(shell());
    fireEvent.click(screen.getByRole("button", { name: "주 메뉴 접기" }));
    expect(screen.getByRole("button", { name: "주 메뉴 펼치기" })).toBeTruthy();
  });
});
