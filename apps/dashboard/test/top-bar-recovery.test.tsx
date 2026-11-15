import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ whoami: vi.fn(), pathname: "/sites/site-1/spatial-assets", returnTo: null as string | null }));
vi.mock("next/headers", () => ({
  headers: async () => new Map([
    ["x-pathname", mocks.pathname],
    ...(mocks.returnTo === null ? [] : [["x-return-to", mocks.returnTo]] as Array<[string, string]>),
  ]),
}));
vi.mock("next/navigation", () => ({ usePathname: () => mocks.pathname, useSearchParams: () => new URLSearchParams() }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => createElement("a", { href }, children) }));
vi.mock("@/lib/core-api/auth", () => ({ whoAmI: mocks.whoami }));
vi.mock("@/lib/core-api/session", () => ({ MissingSessionError: class MissingSessionError extends Error {} }));
vi.mock("@/components/nav/BackButton", () => ({ BackButton: () => null }));
vi.mock("@/components/nav/PageTitle", () => ({ PageTitle: ({ fallback }: { fallback: string }) => createElement("span", null, fallback) }));
vi.mock("@/components/nav/TopBarSearchTrigger", () => ({ TopBarSearchTrigger: () => createElement("button", null, "검색 · 이동") }));
vi.mock("@/components/nav/HeaderSearchTrigger", () => ({ HeaderSearchTrigger: () => createElement("button", null, "데스크톱 검색") }));
vi.mock("@/components/nav/ProjectSwitcher", () => ({ ProjectSwitcher: () => createElement("button", null, "프로젝트 전환") }));
vi.mock("@/components/nav/AccountMenu", () => ({ AccountMenu: ({ principalId, roleLabel }: { principalId: string; roleLabel: string }) => createElement("button", null, `계정 ${principalId} ${roleLabel}`) }));

import { TopBar } from "@/components/nav/TopBar";
import { CoreApiError } from "@/lib/core-api/client";
import { MissingSessionError } from "@/lib/core-api/session";

beforeEach(() => { mocks.pathname = "/sites/site-1/spatial-assets"; mocks.returnTo = null; mocks.whoami.mockReset(); });

describe("TopBar distinguishes identity expiry from server recovery", () => {
  it.each([new Error("ECONNREFUSED private details"), new CoreApiError(503, { detail: "private storage information" })])("never calls a server/network failure an expired session", async (error) => {
    mocks.whoami.mockRejectedValue(error);
    const html = renderToStaticMarkup(await TopBar());
    expect(html).toContain("서버 연결을 확인하지 못했습니다");
    expect(html).not.toContain("세션이 만료");
    expect(html).not.toContain("다시 로그인");
    expect(html).not.toContain("private");
    expect(mocks.whoami).toHaveBeenCalledTimes(1);
  });

  it.each([new MissingSessionError(), new CoreApiError(401, { detail: "Unauthorized" })])("retains the scoped re-login exit for a missing/expired identity", async (error) => {
    mocks.whoami.mockRejectedValue(error);
    const html = renderToStaticMarkup(await TopBar());
    expect(html).toContain("세션이 만료되었습니다");
    expect(html).toContain("/login?next=%2Fsites%2Fsite-1%2Fspatial-assets");
  });

  it("distinguishes permission denial without claiming the credentials expired", async () => {
    mocks.whoami.mockRejectedValue(new CoreApiError(403, { detail: "Forbidden" }));
    const html = renderToStaticMarkup(await TopBar());
    expect(html).toContain("다른 계정으로 로그인");
    expect(html).not.toContain("세션이 만료");
  });

  it("preserves the exact compare context in the re-login return", async () => {
    const visualA = `ksa-v1-${"a".repeat(64)}`;
    const visualB = `ksa-v1-${"b".repeat(64)}`;
    mocks.pathname = "/sites/site-1";
    mocks.returnTo = `/sites/site-1?mode=compare&workAreaId=w1&visualAAssetRef=${visualA}&visualBAssetRef=${visualB}`;
    mocks.whoami.mockRejectedValue(new MissingSessionError());
    const html = renderToStaticMarkup(await TopBar());
    expect(html).toContain("세션이 만료되었습니다");
    const href = html.match(/<a[^>]*href="([^"]+)"[^>]*>다시 로그인<\/a>/)?.[1] ?? "";
    expect(decodeURIComponent(href.replace("/login?next=", ""))).toBe(mocks.returnTo);
  });

  it("falls back to the bare pathname when no return header is present", async () => {
    mocks.pathname = "/sites/site-1/spatial-assets";
    mocks.returnTo = null;
    mocks.whoami.mockRejectedValue(new MissingSessionError());
    const html = renderToStaticMarkup(await TopBar());
    expect(html).toContain("/login?next=%2Fsites%2Fsite-1%2Fspatial-assets");
  });

  it("renders the normal search row on every authenticated console path", async () => {
    // The shell no longer has a path-based compact/focus mode: site workspace
    // and materials keep the same global top bar as every other console page.
    mocks.pathname = "/sites/site-1";
    mocks.whoami.mockResolvedValueOnce({ kind: "OPERATOR", principalId: "op-1", role: "FIELD_OPERATOR" });
    expect(renderToStaticMarkup(await TopBar())).toContain("검색 · 이동");
    mocks.pathname = "/sites/site-1/spatial-assets";
    mocks.whoami.mockResolvedValueOnce({ kind: "OPERATOR", principalId: "op-1", role: "FIELD_OPERATOR" });
    expect(renderToStaticMarkup(await TopBar())).toContain("검색 · 이동");
    mocks.pathname = "/login";
    mocks.whoami.mockRejectedValueOnce(new Error("network"));
    expect(renderToStaticMarkup(await TopBar())).toBe("");
  });

  it("shows the project switcher, search and the signed-in account on a healthy session", async () => {
    mocks.whoami.mockResolvedValueOnce({ kind: "OPERATOR", principalId: "op-1", role: "ADMIN" });
    const html = renderToStaticMarkup(await TopBar());
    expect(html).toContain('data-session-state="ok"');
    expect(html).toContain("프로젝트 전환");
    expect(html).toContain("데스크톱 검색");
    expect(html).toContain("계정 op-1");
  });

  it("falls back to the principal kind when the identity has no role", async () => {
    mocks.whoami.mockResolvedValueOnce({ kind: "DEVICE", principalId: "dev-1", role: null });
    expect(renderToStaticMarkup(await TopBar())).toContain("계정 dev-1 DEVICE");
  });

  it.each([new MissingSessionError(), new CoreApiError(403, { detail: "Forbidden" })])("hides every normal tool while the session needs recovery", async (error) => {
    mocks.whoami.mockRejectedValueOnce(error);
    const html = renderToStaticMarkup(await TopBar());
    expect(html).not.toContain("프로젝트 전환");
    expect(html).not.toContain("데스크톱 검색");
    expect(html).not.toContain("계정 ");
    expect(html).not.toContain("검색 · 이동");
  });

  it("keeps the auth alert visible on workspace and materials paths", async () => {
    mocks.pathname = "/sites/site-1/spatial-assets";
    mocks.whoami.mockRejectedValueOnce(new MissingSessionError());
    const html = renderToStaticMarkup(await TopBar());
    expect(html).toContain("세션이 만료되었습니다");
    expect(html).toContain("/login?next=%2Fsites%2Fsite-1%2Fspatial-assets");
    mocks.whoami.mockRejectedValueOnce(new Error("ECONNREFUSED private details"));
    const unreachable = renderToStaticMarkup(await TopBar());
    expect(unreachable).toContain("서버 연결을 확인하지 못했습니다");
    expect(unreachable).not.toContain("private");
  });
});
