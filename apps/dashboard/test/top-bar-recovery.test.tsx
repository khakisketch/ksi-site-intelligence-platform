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
vi.mock("next/navigation", () => ({ usePathname: () => mocks.pathname }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => createElement("a", { href }, children) }));
vi.mock("@/lib/core-api/auth", () => ({ whoAmI: mocks.whoami }));
vi.mock("@/lib/core-api/session", () => ({ MissingSessionError: class MissingSessionError extends Error {} }));
vi.mock("@/components/nav/BackButton", () => ({ BackButton: () => null }));
vi.mock("@/components/nav/PageTitle", () => ({ PageTitle: ({ fallback }: { fallback: string }) => createElement("span", null, fallback) }));
vi.mock("@/components/nav/TopBarSearchTrigger", () => ({ TopBarSearchTrigger: () => createElement("button", null, "검색 · 이동") }));

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

  it("keeps a normal search entry and hides repeated failure text on login", async () => {
    // 정확한 현장 작업공간 경로는 집중 모드라서 정상행을 접는다 — 검색 입구는
    // 작업환경 맥락막대가 맡는다. 일반 경로에서는 정상행을 둔다.
    mocks.pathname = "/sites/site-1";
    mocks.whoami.mockResolvedValueOnce({ kind: "OPERATOR" });
    expect(renderToStaticMarkup(await TopBar())).toBe("");
    mocks.pathname = "/sites";
    mocks.whoami.mockResolvedValueOnce({ kind: "OPERATOR" });
    expect(renderToStaticMarkup(await TopBar())).toContain("검색 · 이동");
    mocks.pathname = "/login";
    mocks.whoami.mockRejectedValueOnce(new Error("network"));
    expect(renderToStaticMarkup(await TopBar())).toBe("");
  });

  it("hides only the normal row in focus mode but keeps the auth alert visible", async () => {
    mocks.pathname = "/sites/site-1/spatial-assets";
    mocks.whoami.mockResolvedValueOnce({ kind: "OPERATOR" });
    expect(renderToStaticMarkup(await TopBar())).toBe("");
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
