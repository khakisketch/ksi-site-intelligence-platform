import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ whoami: vi.fn(), pathname: "/sites/site-1/spatial-assets" }));
vi.mock("next/headers", () => ({ headers: async () => new Map([["x-pathname", mocks.pathname]]) }));
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

beforeEach(() => { mocks.pathname = "/sites/site-1/spatial-assets"; mocks.whoami.mockReset(); });

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

  it("keeps a normal search entry and hides repeated failure text on login", async () => {
    mocks.pathname = "/sites/site-1";
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
