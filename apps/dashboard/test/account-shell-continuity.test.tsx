// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
vi.mock("next/link", () => ({default: ({href,children,...props}: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={href} {...props}>{children}</a>}));
vi.mock("next/navigation", () => ({usePathname: () => "/sites/site-1/work-areas", useRouter: () => ({push: vi.fn()}), useSearchParams: () => new URLSearchParams()}));
import { MobileBottomNav } from "@/components/nav/MobileBottomNav";
import { DesktopSidebar } from "@/components/nav/DesktopSidebar";
import { CommandPalette } from "@/components/console/CommandPalette";
import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import { SiteListProvider } from "@/components/nav/SiteListContext";
import { AccountDisplayBoundary } from "@/components/nav/AccountDisplayBoundary";
const A = `v1-${"a".repeat(64)}`, B = `v1-${"b".repeat(64)}`;
const name = "Local Analysis API fixture site";
const sites = [{siteId:"site-1", name, status:"UNMAPPED" as const}, {siteId:"site-2", name:"다른 현장", status:"UNMAPPED" as const}];
const site = {siteId:"site-1",name,status:"UNMAPPED",resumeTarget:null,aoi:null} as never;
const response = (fingerprint:string) => new Response(JSON.stringify({fingerprint}), {status:200});
function Shell() { return <AccountDisplayBoundary fingerprint={A}><SiteListProvider sites={sites}><DesktopSidebar sites={sites} /><MobileBottomNav /><SiteHeader site={site} selectedEpochId={null} tab="manage" canCreateWorkOrder={false} canEditAoi={false}/><input aria-label="원문" defaultValue="original"/><CommandPalette items={[{key:"site",label:name,group:"현장",href:"/sites/site-1"}]}/></SiteListProvider></AccountDisplayBoundary>; }
const root = () => document.querySelector<HTMLElement>("[data-account-display-root]")!;
beforeEach(() => { vi.spyOn(document, "hasFocus").mockReturnValue(true); HTMLElement.prototype.scrollIntoView = vi.fn(); vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => response(A))); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
describe("account shell continuity", () => {
  it("SSR leaves the actual shell hidden until hydration verifies the account", () => {
    const html = renderToString(<Shell/>);
    expect(html).toMatch(/data-account-display-root="" hidden="" inert="" style="display:none"/);
    expect(html).toContain(name);
    expect(html).toContain("계정 확인을 위해 JavaScript가 필요합니다.");
  });
  it("hides shell synchronously on visible blur, blocks shortcuts and restores the same input only for A", async () => {
    render(<Shell/>);
    await waitFor(() => expect(screen.queryByText("계정 다시 확인")).toBeNull());
    expect(root().hidden).toBe(false);
    const input = screen.getByLabelText("원문") as HTMLInputElement;
    fireEvent.change(input, {target:{value:"pending original"}});
    fireEvent.click(screen.getAllByRole("button", {name:`현장 변경: ${name}`})[0]);
    const switcher = screen.getByRole("dialog", {name:"현장 변경"});
    expect(root().contains(switcher)).toBe(true);
    fireEvent.keyDown(window, {key:"Escape"});
    fireEvent.keyDown(window, {key:"k",ctrlKey:true});
    expect(screen.getByRole("dialog", {name:"검색 및 이동"})).toBeTruthy();
    vi.mocked(fetch).mockResolvedValue(response(B));
    act(() => {
      window.dispatchEvent(new Event("blur"));
      // Assert before React has committed the state update.
      expect(root().hidden).toBe(true);
      expect(root().inert).toBe(true);
    });
    expect(switcher.isConnected && !switcher.closest("[hidden]")).toBe(false);
    fireEvent.focus(window);
    await waitFor(() => expect(screen.getByRole("status").getAttribute("data-account-display-state")).toBe("locked"));
    expect(root().hidden).toBe(true);
    fireEvent.keyDown(window, {key:"k",ctrlKey:true});
    expect(root().hidden).toBe(true);
    const retry = screen.getByText("계정 다시 확인");
    retry.focus();
    expect(document.activeElement).toBe(retry);
    vi.mocked(fetch).mockResolvedValue(response(A));
    fireEvent.click(screen.getByText("계정 다시 확인"));
    await waitFor(() => expect(root().hidden).toBe(false));
    expect(screen.getByLabelText("원문")).toBe(input);
    expect(input.value).toBe("pending original");
  });
  it("does not open the palette while locked", async () => {
    render(<Shell/>);
    await waitFor(() => expect(screen.queryByText("계정 다시 확인")).toBeNull());
    fireEvent.blur(window);
    fireEvent.keyDown(window, {key:"k",ctrlKey:true});
    expect(root().querySelector('[role="dialog"]')).toBeNull();
    window.dispatchEvent(new Event("ksi:palette-open"));
    expect(root().querySelector('[role="dialog"]')).toBeNull();
  });
  it("locks through pagehide and does not reveal while the window is unfocused", async () => {
    render(<Shell/>);
    await waitFor(() => expect(screen.queryByText("계정 다시 확인")).toBeNull());
    fireEvent(window, new Event("pagehide"));
    expect(root().hidden).toBe(true);
    vi.mocked(document.hasFocus).mockReturnValue(false);
    fireEvent(window, new Event("pageshow"));
    await waitFor(() => expect(screen.getByText("계정 다시 확인")).toBeTruthy());
    expect(root().hidden).toBe(true);
    vi.mocked(document.hasFocus).mockReturnValue(true);
    fireEvent.focus(window);
    await waitFor(() => expect(root().hidden).toBe(false));
  });
  it("keeps a pending response mounted while a different account is active", async () => {
    let settle!: (value: string) => void;
    const pending = new Promise<string>(resolve => { settle = resolve; });
    function PendingChild() {
      const [result, setResult] = React.useState("pending");
      React.useEffect(() => { void pending.then(setResult); }, []);
      return <p>{result}</p>;
    }
    render(<AccountDisplayBoundary fingerprint={A}><PendingChild /></AccountDisplayBoundary>);
    await waitFor(() => expect(root().hidden).toBe(false));
    vi.mocked(fetch).mockImplementation(async () => response(B));
    fireEvent.blur(window);
    fireEvent.focus(window);
    await act(async () => settle("원래 응답"));
    await waitFor(() => expect(screen.getByRole("status").getAttribute("data-account-display-state")).toBe("locked"));
    expect(root().hidden).toBe(true);
    expect(root().textContent).toContain("원래 응답");
    vi.mocked(fetch).mockImplementation(async () => response(A));
    fireEvent.click(screen.getByText("계정 다시 확인"));
    await waitFor(() => expect(root().hidden).toBe(false));
    expect(screen.getByText("원래 응답")).toBeTruthy();
  });
  it("does not rebind an existing subtree to a changed server fingerprint", async () => {
    const view = render(<AccountDisplayBoundary fingerprint={A}><input aria-label="보존" defaultValue="raw" /></AccountDisplayBoundary>);
    await waitFor(() => expect(root().hidden).toBe(false));
    const input = screen.getByLabelText("보존") as HTMLInputElement;
    vi.mocked(fetch).mockResolvedValue(response(B));
    view.rerender(<AccountDisplayBoundary fingerprint={B}><input aria-label="보존" defaultValue="raw" /></AccountDisplayBoundary>);
    expect(root().hidden).toBe(true);
    await waitFor(() => expect(screen.getByText("계정 다시 확인")).toBeTruthy());
    expect(input.isConnected).toBe(true);
    expect(input.value).toBe("raw");
  });
  it("ignores stale identity replies and remains closed on lookup failure", async () => {
    let resolve!: (response: Response) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(r => {resolve = r;}));
    render(<Shell/>);
    fireEvent.blur(window);
    vi.mocked(fetch).mockRejectedValue(new Error("offline"));
    fireEvent.focus(window);
    await act(async () => resolve(response(A)));
    await waitFor(() => expect(root().hidden).toBe(true));
    expect(screen.getByText("계정 다시 확인")).toBeTruthy();
  });
});
