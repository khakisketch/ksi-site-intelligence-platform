/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ principal: vi.fn() }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) => createElement("a", { href, ...props }, children),
}));
vi.mock("@/app/login/actions", () => ({ logout: vi.fn() }));
vi.mock("@/components/nav/shell-principal", () => ({ readShellPrincipal: mocks.principal }));

import { AccountMenu } from "@/components/nav/AccountMenu";
import { DesktopSidebar } from "@/components/nav/DesktopSidebar";
import { RailAccount } from "@/components/nav/RailAccount";
import { installFakeLocalStorage } from "./storage-fakes";

vi.mock("next/navigation", () => ({ usePathname: () => "/sites/site-1/data", useSearchParams: () => new URLSearchParams() }));

beforeEach(() => {
  installFakeLocalStorage();
  window.localStorage.clear();
  mocks.principal.mockReset();
});
afterEach(cleanup);

describe("계정 메뉴의 두 자리", () => {
  it("레일 자리는 768px 이상에서만 보이고 이름·역할을 항목에 싣는다", () => {
    render(<AccountMenu placement="rail" principalId="local-admin" roleLabel="관리자" />);
    const trigger = screen.getByRole("button", { name: "계정 메뉴: local-admin" });
    expect(trigger.className).toContain("rail-link");
    expect(trigger.getAttribute("data-tip")).toBe("local-admin");
    expect(within(trigger).getByText("관리자")).toBeTruthy();
    const root = trigger.closest("[data-account-menu]") as HTMLElement;
    expect(root.getAttribute("data-account-menu")).toBe("rail");
    expect(root.className).toContain("hidden");
    expect(root.className).toContain("md:flex");
  });

  it("헤더 자리는 768px 미만에서만 보이고 이니셜만 둔다", () => {
    render(<AccountMenu principalId="local-admin" roleLabel="관리자" />);
    const trigger = screen.getByRole("button", { name: "계정 메뉴: local-admin" });
    expect(trigger.textContent).toBe("L");
    expect((trigger.closest("[data-account-menu]") as HTMLElement).className).toContain("md:hidden");
  });

  it("레일에서는 메뉴가 옆으로 열리고 계정·로그아웃을 준다", () => {
    render(<AccountMenu placement="rail" principalId="local-admin" roleLabel="관리자" />);
    fireEvent.click(screen.getByRole("button", { name: "계정 메뉴: local-admin" }));
    const menu = screen.getByRole("menu", { name: "계정" });
    expect(menu.id).toBe("account-menu-rail");
    expect(menu.className).toContain("left-full");
    expect(within(menu).getByRole("menuitem", { name: "계정·도움 안내" }).getAttribute("href")).toBe("/more");
    expect(within(menu).getByRole("menuitem", { name: "로그아웃" })).toBeTruthy();
  });

  it("Esc 로 닫으면 포커스가 트리거로 돌아온다", () => {
    render(<AccountMenu placement="rail" principalId="local-admin" roleLabel="관리자" />);
    const trigger = screen.getByRole("button", { name: "계정 메뉴: local-admin" });
    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

describe("RailAccount", () => {
  it("읽은 신원으로 레일 계정 메뉴를 그린다", async () => {
    mocks.principal.mockResolvedValue({ principalId: "kim", role: "FIELD_OPERATOR", kind: "USER" });
    const html = renderToStaticMarkup(await RailAccount());
    expect(html).toContain('data-account-menu="rail"');
    expect(html).toContain("현장운영자");
  });

  it("신원을 못 읽으면 그리지 않는다 — 복구 안내는 상단바 몫이다", async () => {
    mocks.principal.mockRejectedValue(new Error("down"));
    expect(await RailAccount()).toBeNull();
  });
});

describe("레일의 계정 자리", () => {
  it("계정 슬롯을 접기 버튼 아래, 맨 끝에 둔다", () => {
    render(<DesktopSidebar account={<div data-testid="account-slot" />} />);
    const nav = screen.getByRole("navigation", { name: "주 메뉴" });
    const slot = within(nav).getByTestId("account-slot");
    const toggle = within(nav).getByRole("button", { name: "주 메뉴 접기" });
    expect(toggle.compareDocumentPosition(slot) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
