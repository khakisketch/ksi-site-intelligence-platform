import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ site: vi.fn(), areas: vi.fn(), permissions: vi.fn() }));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) =>
    createElement("a", { href, ...props }, children),
}));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("NEXT_NOT_FOUND"); } }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/permissions", () => ({ hasAllPermissions: mocked.permissions }));
vi.mock("@/app/sites/[siteId]/work-areas/WorkAreaPanel", () => ({
  WorkAreaPanel: ({ initialWorkAreas, workAreaListError }: { initialWorkAreas: unknown[]; workAreaListError: { message: string } | null }) =>
    createElement("div", { "data-area-count": initialWorkAreas.length, "data-list-error": workAreaListError !== null }, workAreaListError?.message ?? "목록 준비됨"),
}));

import SiteWorkAreasPage from "@/app/sites/[siteId]/work-areas/page";
import { CoreApiError } from "@/lib/core-api/client";

const callPage = () => SiteWorkAreasPage({ params: Promise.resolve({ siteId: "site-1" }) });

beforeEach(() => {
  vi.resetAllMocks();
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "현장 1", status: "BASELINE_MAPPING", aoi: null, resumeTarget: null, siteFrame: { crs: "EPSG:5186", transformVersion: "v1" }, registeredAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z" });
  mocked.areas.mockResolvedValue({ workAreas: [] });
  mocked.permissions.mockResolvedValue(false);
});

describe("work area list load state", () => {
  it("returns to the validated work-area scope without promoting an unknown query", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "동측", status: "ACTIVE" }] });
    const html = renderToStaticMarkup(await SiteWorkAreasPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({ workAreaId: "area-1" }),
    }));
    expect(html).toContain('/sites/site-1?workAreaId=area-1');
    const foreign = renderToStaticMarkup(await SiteWorkAreasPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({ workAreaId: "foreign" }),
    }));
    expect(foreign).not.toContain('workAreaId=foreign');
  });

  it("keeps a successful empty list distinct from a rejected list read", async () => {
    const empty = renderToStaticMarkup(await callPage());
    expect(empty).toContain("data-area-count=\"0\"");
    expect(empty).toContain("data-list-error=\"false\"");

    mocked.areas.mockRejectedValueOnce(new CoreApiError(503, {}, 12));
    const failed = renderToStaticMarkup(await callPage());
    expect(failed).toContain("data-area-count=\"0\"");
    expect(failed).toContain("data-list-error=\"true\"");
    expect(failed).toContain("일시적으로 불러오지 못했습니다.");
  });

  it("gives access-specific guidance for a denied WorkArea read", async () => {
    mocked.areas.mockRejectedValueOnce(new CoreApiError(403, {}));
    const html = renderToStaticMarkup(await callPage());
    expect(html).toContain("현장 담당자에게 조회 권한을 요청하세요.");
    expect(html).toContain("data-list-error=\"true\"");
  });

  it("does not treat a missing WorkArea-list response as an empty site", async () => {
    mocked.areas.mockRejectedValueOnce(new CoreApiError(404, {}));
    const html = renderToStaticMarkup(await callPage());
    expect(html).toContain("현장 작업구역 목록을 확인할 수 없습니다.");
    expect(html).toContain("data-list-error=\"true\"");
  });
});
