/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  site: vi.fn(),
  permissions: vi.fn(),
  areas: vi.fn(),
  orders: vi.fn(),
  history: vi.fn(),
  analyses: vi.fn(),
  assets: vi.fn(),
  header: vi.fn(),
}));

vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/permissions", () => ({ hasAllPermissions: mocked.permissions }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ listObservationWorkOrders: mocked.orders }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({ listSiteExternalVolumeHistory: mocked.history }));
vi.mock("@/lib/core-api/analysis", () => ({ listAnalyses: mocked.analyses }));
vi.mock("@/lib/core-api/spatial-assets", () => ({ listSpatialAssets: mocked.assets }));
vi.mock("@/app/sites/[siteId]/SiteHeader", () => ({ SiteHeader: mocked.header }));
vi.mock("@/app/sites/[siteId]/observations/ExternalObservationHistory", () => ({ ExternalObservationHistory: () => <div /> }));
vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
  useRouter: () => ({ refresh: () => {} }),
  redirect: (url: string) => {
    const error = new Error(`NEXT_REDIRECT;replace;${url};307;`);
    (error as Error & { digest: string }).digest = `NEXT_REDIRECT;replace;${url};307;`;
    throw error;
  },
}));

import SiteDetailPage from "@/app/sites/[siteId]/page";
import { CoreApiError } from "@/lib/core-api/client";

afterEach(() => { cleanup(); vi.resetAllMocks(); });

beforeEach(() => {
  mocked.header.mockReturnValue(<div data-testid="site-header" />);
  mocked.site.mockResolvedValue({
    siteId: "site-1",
    name: "현장 하나",
    status: "UNMAPPED",
    aoi: null,
    resumeTarget: null,
    siteFrame: { crs: "EPSG:5186", transformVersion: "v1" },
    registeredAt: "2026-10-01T00:00:00Z",
    updatedAt: "2026-10-01T00:00:00Z",
  });
  mocked.permissions.mockResolvedValue(false);
  mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "구역 1", status: "ACTIVE", createdAt: "2026-10-01T00:00:00Z" }] });
  mocked.orders.mockResolvedValue([{ workOrderId: "work-1" }]);
  mocked.history.mockResolvedValue({ items: [{ reportRef: "report-1", result: null }], nextCursor: null });
  mocked.analyses.mockResolvedValue({ siteId: "site-1", items: [], nextCursor: null });
  mocked.assets.mockResolvedValue({
    contractVersion: "spatial-asset-catalog-page.v1",
    siteId: "site-1",
    workAreaId: "area-1",
    scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY",
    scopeNote: "",
    assets: [],
    nextCursor: null,
    hasMore: false,
  });
});

describe("Site detail start guidance", () => {
  it("keeps the read-only manage tab quiet and reveals the state-change reason on click", async () => {
    render(await SiteDetailPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({ tab: "manage" }),
    }));
    expect(screen.queryByText(/현재 계정으로는 현장 상태를 변경할 수 없습니다/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /현장 상태 변경/ }));
    expect(screen.getByText(/현재 계정으로는 현장 상태를 변경할 수 없습니다/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "상태 전이" })).toBeNull();
  });
  const openSite = (query: Record<string, string>) => SiteDetailPage({
    params: Promise.resolve({ siteId: "site-1" }),
    searchParams: Promise.resolve(query),
  });

  it("carries the legacy materials scope into the space panel", async () => {
    const assetRef = `ksa-v1-${"a".repeat(64)}`;
    await expect(openSite({ section: "materials", workAreaId: "area-1", assetRef }))
      .rejects.toThrow(`/sites/site-1?panel=materials&workAreaId=area-1&assetRef=${assetRef}`);
  });

  it("routes the old work ledger to registration progress in the space panel", async () => {
    await expect(openSite({ section: "work-orders", workAreaId: "area-1" }))
      .rejects.toThrow("/sites/site-1?panel=intake&workAreaId=area-1");
  });

  it("routes old analysis and external-comparison links to their respective tabs", async () => {
    await expect(openSite({ section: "analysis" })).rejects.toThrow("/sites/site-1/analysis");
    await expect(openSite({ section: "external-results", workAreaId: "area-1" }))
      .rejects.toThrow("/sites/site-1/observations;307");
  });

  it("shows this site's active registration stages with a link to the work queue", async () => {
    mocked.orders.mockResolvedValue([
      { workOrderId: "work-1", siteId: "site-1", name: "주간 관측", status: "APPROVED", executionMode: "EXTERNAL_RECONSTRUCTION" },
      { workOrderId: "work-2", siteId: "site-1", name: "완료된 관측", status: "COMPLETED", executionMode: "EXTERNAL_RECONSTRUCTION" },
      { workOrderId: "work-3", siteId: "other", name: "다른 현장 작업", status: "APPROVED", executionMode: "EXTERNAL_RECONSTRUCTION" },
    ]);
    render(await openSite({ panel: "intake" }));
    const progress = within(screen.getByRole("region", { name: "등록 진행 중인 작업" }));
    expect(progress.getByRole("link", { name: "주간 관측" }).getAttribute("href")).toBe("/field/work-orders/work-1");
    expect(progress.getByText("파일 제출·검사").closest("li")?.getAttribute("aria-current")).toBe("step");
    expect(progress.queryByText("완료된 관측")).toBeNull();
    expect(progress.queryByText("다른 현장 작업")).toBeNull();
    expect(progress.getByRole("link", { name: "전체 작업에서 보기" }).getAttribute("href")).toBe("/field?site=site-1");
    fireEvent.click(screen.getByRole("button", { name: "자료", pressed: false }));
    expect(screen.getByRole("region", { name: "자료 목록" })).toBeTruthy();
  });

  it("keeps failed work and area reads distinct from verified empty states", async () => {
    mocked.orders.mockRejectedValue(new CoreApiError(403, {}));
    mocked.areas.mockRejectedValue(new CoreApiError(503, {}));
    render(await openSite({ panel: "intake" }));
    expect(screen.getByText(/등록 진행 상태를 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.getByText(/작업구역 목록을 불러오지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText("진행 중인 작업이 없습니다.")).toBeNull();
    expect(screen.queryByText("등록된 작업구역이 없습니다")).toBeNull();
  });

  it("keeps the settings page to extent, state and a WorkArea management entry", async () => {
    render(await openSite({ section: "manage" }));
    expect(screen.getByRole("heading", { name: "현장 설정" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "현장 범위" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: /^현장 상태/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: "작업구역 관리" }).getAttribute("href")).toBe("/sites/site-1/work-areas");
    expect(screen.queryByText("자료 보기")).toBeNull();
  });
});
