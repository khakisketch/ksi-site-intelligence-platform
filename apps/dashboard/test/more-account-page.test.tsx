import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ whoami: vi.fn() }));
vi.mock("@/lib/core-api/auth", () => ({ whoAmI: mocks.whoami }));
vi.mock("@/lib/core-api/session", () => ({ MissingSessionError: class MissingSessionError extends Error { constructor(message?: string) { super(message); } } }));
vi.mock("@/app/login/actions", () => ({ logout: async () => {} }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => createElement("a", { href }, children),
}));

import MorePage from "@/app/more/page";
import { CoreApiError } from "@/lib/core-api/client";
import { MissingSessionError } from "@/lib/core-api/session";

beforeEach(() => { mocks.whoami.mockReset(); });

describe("account and help page", () => {
  it("shows the real principal, role and a reachable logout", async () => {
    mocks.whoami.mockResolvedValue({ kind: "OPERATOR", principalId: "operator-1", role: "FIELD_OPERATOR", organizationId: "org-1" });
    const html = renderToStaticMarkup(await MorePage());
    expect(html).toContain("operator-1");
    expect(html).toContain("로그아웃");
    expect(html).toContain("현장운영자");
    expect(html).not.toContain("로그인이 필요");
  });

  it("offers login on 401 but keeps the logout entry instead of vanishing", async () => {
    mocks.whoami.mockRejectedValue(new MissingSessionError());
    const html = renderToStaticMarkup(await MorePage());
    expect(html).toContain("/login");
    expect(html).toContain("로그아웃");
    expect(html).not.toContain("operator-1");
    for (const paragraph of html.match(/<p\b[^>]*>[\s\S]*?<\/p>/g) ?? []) {
      expect(paragraph).not.toMatch(/<(form|div|section)\b/);
    }
  });

  it("stays honest when the account cannot be read for a server reason", async () => {
    mocks.whoami.mockRejectedValue(new CoreApiError(503, { detail: "private core detail" }));
    const html = renderToStaticMarkup(await MorePage());
    expect(html).toContain("확인할 수 없습니다");
    expect(html).toContain("/login");
    expect(html).toContain("로그아웃");
    expect(html).not.toContain("private core detail");
  });

  it("links real tasks and keeps the product-boundary notice secondary", async () => {
    mocks.whoami.mockResolvedValue({ kind: "OPERATOR", principalId: "operator-1", role: "VIEWER", organizationId: "org-1" });
    const html = renderToStaticMarkup(await MorePage());
    for (const href of ["/sites", "/field", "/field/inbox", "/coming-soon/fleet"]) {
      expect(html).toContain(`href="${href}"`);
    }
    expect(html).not.toContain('href="/field/team"');
    expect(html).toContain("제품 범위 밖");
    expect(html).not.toContain("준비 중");
  });

  it("keeps the team shortcut consistent with the work navigation's known authority", async () => {
    mocks.whoami.mockResolvedValue({ kind: "OPERATOR", principalId: "operator-1", role: "FIELD_OPERATOR", organizationId: "org-1", permissions: ["WORK_ORDERS_WRITE"] });
    const html = renderToStaticMarkup(await MorePage());
    expect(html).toContain('href="/field/team"');
  });
});
