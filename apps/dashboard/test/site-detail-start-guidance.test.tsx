/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  site: vi.fn(),
  permissions: vi.fn(),
  areas: vi.fn(),
  orders: vi.fn(),
  history: vi.fn(),
}));

vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/permissions", () => ({ hasAllPermissions: mocked.permissions }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ listObservationWorkOrders: mocked.orders }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({ listSiteExternalVolumeHistory: mocked.history }));
vi.mock("@/app/sites/[siteId]/SiteHeader", () => ({ SiteHeader: () => <div data-testid="site-header" /> }));
vi.mock("@/app/sites/[siteId]/observations/ExternalObservationHistory", () => ({ ExternalObservationHistory: () => <div /> }));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("NEXT_NOT_FOUND"); } }));

import SiteDetailPage from "@/app/sites/[siteId]/page";
import { CoreApiError } from "@/lib/core-api/client";

afterEach(() => { cleanup(); vi.resetAllMocks(); });

beforeEach(() => {
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
  mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "구역 1" }] });
  mocked.orders.mockResolvedValue([{ workOrderId: "work-1" }]);
  mocked.history.mockResolvedValue({ items: [{ reportRef: "report-1", result: null }], nextCursor: null });
});

describe("Site detail start guidance", () => {
  it("appears on the default Site view with scoped records and bounded history", async () => {
    mocked.history.mockResolvedValue({
      items: Array.from({ length: 50 }, (_, index) => ({ reportRef: `report-${index + 1}`, result: null })),
      nextCursor: "older-results",
    });

    render(await SiteDetailPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({}),
    }));

    const guide = within(screen.getByRole("region", { name: "현장 시작 안내" }));
    expect(guide.getAllByText("1개 목록됨")).toHaveLength(2);
    expect(guide.getByText("최근 페이지 50개 · 더 있음")).toBeTruthy();
    expect(guide.getByRole("link", { name: "분석 후보와 상태 확인" }).getAttribute("href")).toBe("/sites/site-1/analysis");
    expect(screen.queryByRole("link", { name: "새 관측 시작" })).toBeNull();
    expect(mocked.history).toHaveBeenCalledWith("site-1", { limit: 50 });
  });

  it("keeps failed child reads unknown instead of rendering false empty guidance", async () => {
    mocked.areas.mockRejectedValue(new CoreApiError(503, { detail: "unavailable" }));
    mocked.orders.mockRejectedValue(new CoreApiError(403, { detail: "denied" }));
    mocked.history.mockRejectedValue(new CoreApiError(503, { detail: "unavailable" }));

    render(await SiteDetailPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({}),
    }));

    expect(screen.getByRole("region", { name: "현장 시작 안내" })).toBeTruthy();
    expect(screen.getAllByText("확인 불가")).toHaveLength(3);
    expect(screen.queryByText("등록된 작업구역이 없습니다")).toBeNull();
    expect(screen.queryByText("등록된 관측 작업이 없습니다")).toBeNull();
    expect(screen.queryByText("외부 관측 결과가 없습니다")).toBeNull();
    expect(screen.queryByRole("link", { name: "새 관측 시작" })).toBeNull();
  });

  it("does not duplicate entry guidance on other Site tabs", async () => {
    render(await SiteDetailPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({ section: "analysis" }),
    }));

    expect(screen.queryByRole("region", { name: "현장 시작 안내" })).toBeNull();
    expect(screen.getByText("현장 분석 화면에서 관측 쌍, 작업구역, 분석 기록과 근거를 확인합니다.")).toBeTruthy();
  });
});
