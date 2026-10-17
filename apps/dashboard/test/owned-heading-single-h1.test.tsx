/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SiteView } from "@/lib/core-api/types";

const mockedSession = vi.hoisted(() => ({
  resolve: async (): Promise<unknown> => ({ kind: "ready", principal: { kind: "OPERATOR", organizationId: "org-1", role: "ADMIN", principalId: "operator-a", deviceId: null, permissions: ["SITES_READ", "SITES_WRITE", "WORK_ORDERS_WRITE"] } }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/sites/site-1/observations/new",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/app/field/resolve-session", () => ({
  resolveFieldSession: () => mockedSession.resolve(),
}));
vi.mock("@/lib/core-api/cached", () => ({
  listSitesCached: async (): Promise<SiteView[]> => [],
}));

import { MainPageTitle } from "@/components/nav/PageTitle";
import FieldNewObservationPage from "@/app/field/new/page";
import { ExternalObservationCreateForm } from "@/app/sites/[siteId]/observations/new/ExternalObservationCreateForm";

afterEach(cleanup);

describe("owned single-h1 hierarchy", () => {
  it("keeps one shell h1 and a contextual h2 on the external observation form", () => {
    render(<main><MainPageTitle fallback="새 관측" /><ExternalObservationCreateForm
      siteId="site-1"
      siteName="A 현장"
      workAreas={[{ workAreaId: "area-1", name: "1구역" }]}
    /></main>);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 2, name: "A 현장 · 관측 자료 등록" })).toBeTruthy();
  });

  it("hands a compact reader to the exact notebook target without promising features", () => {
    render(<main><MainPageTitle fallback="새 관측" /><ExternalObservationCreateForm
      siteId="site-1"
      siteName="A 현장"
      workAreas={[{ workAreaId: "area-1", name: "1구역" }]}
    /></main>);
    const notice = screen.getByText(/노트북에서 같은 계정으로/);
    expect(notice.textContent).toContain("A 현장");
    expect(notice.textContent).toContain("/sites/site-1/observations/new");
  });

  it("keeps one shell h1 and a contextual h2 on field/new", async () => {
    render(<main><MainPageTitle fallback="새 관측" />{await FieldNewObservationPage()}</main>);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 2, name: "현장 선택" })).toBeTruthy();
  });
});
