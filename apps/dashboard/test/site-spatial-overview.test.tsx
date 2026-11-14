/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  site: vi.fn(),
  permissions: vi.fn(),
  areas: vi.fn(),
  orders: vi.fn(),
  history: vi.fn(),
  analyses: vi.fn(),
  assets: vi.fn(),
}));

vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/permissions", () => ({ hasAllPermissions: mocked.permissions }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ listObservationWorkOrders: mocked.orders }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({ listSiteExternalVolumeHistory: mocked.history }));
vi.mock("@/lib/core-api/analysis", () => ({ listAnalyses: mocked.analyses }));
vi.mock("@/lib/core-api/spatial-assets", () => ({ listSpatialAssets: mocked.assets }));
vi.mock("@/components/map/AoiPolygonMap", () => ({
  AoiPolygonMap: ({ value }: { value: unknown }) => (
    <div data-testid="aoi-map" data-vertices={JSON.stringify(value)} />
  ),
}));
vi.mock("next/navigation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next/navigation")>();
  return { ...actual, notFound: () => { throw new Error("NEXT_NOT_FOUND"); }, useRouter: () => ({ refresh: () => {} }) };
});

import SiteDetailPage from "@/app/sites/[siteId]/page";
import { analysisStateLabel } from "@/app/sites/[siteId]/SiteSpatialOverview";
import { CoreApiError } from "@/lib/core-api/client";

const TINY_5186 = {
  type: "Polygon",
  coordinates: [[[200000, 549999.8], [200010, 549999.8], [200010, 550009.8], [200000, 549999.8]]],
};

const EMPTY_CATALOG = {
  contractVersion: "spatial-asset-catalog-page.v1",
  siteId: "site-1",
  workAreaId: "tiny-1",
  scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY",
  scopeNote: "",
  assets: [],
  nextCursor: null,
  hasMore: false,
};

function areaFixture(overrides: Record<string, unknown> = {}) {
  return {
    schemaVersion: "1.0",
    siteId: "site-1",
    workAreaId: "tiny-1",
    name: "미세 분석 구역",
    polygon: TINY_5186,
    crs: "EPSG:5186",
    status: "ACTIVE",
    supersedes: null,
    createdAt: "2026-10-10T00:00:00Z",
    ...overrides,
  };
}

afterEach(() => { cleanup(); vi.resetAllMocks(); });

beforeEach(() => {
  mocked.site.mockResolvedValue({
    siteId: "site-1",
    name: "현장 하나",
    status: "BASELINE_MAPPING",
    aoi: null,
    resumeTarget: null,
    siteFrame: { crs: "EPSG:5186", transformVersion: "v1" },
    registeredAt: "2026-10-01T00:00:00Z",
    updatedAt: "2026-10-01T00:00:00Z",
  });
  mocked.permissions.mockResolvedValue(false);
  mocked.areas.mockResolvedValue({ workAreas: [areaFixture()] });
  mocked.orders.mockResolvedValue([]);
  mocked.history.mockResolvedValue({ items: [], nextCursor: null });
  mocked.analyses.mockResolvedValue({ siteId: "site-1", items: [], nextCursor: null });
  mocked.assets.mockResolvedValue(EMPTY_CATALOG);
});

async function renderDefaultTab(searchParams: Record<string, string> = {}) {
  render(await SiteDetailPage({
    params: Promise.resolve({ siteId: "site-1" }),
    searchParams: Promise.resolve(searchParams),
  }));
}

describe("Site spatial overview data bounds", () => {
  it("reads analyses once and selected-area assets once with small limits", async () => {
    await renderDefaultTab({});
    expect(mocked.analyses).toHaveBeenCalledTimes(1);
    expect(mocked.analyses).toHaveBeenCalledWith("site-1", { limit: 50 });
    expect(mocked.assets).toHaveBeenCalledTimes(1);
    expect(mocked.assets).toHaveBeenCalledWith("site-1", "tiny-1", { limit: 50 });
  });

  it("renders an action-ready empty stage without treating it as an observation", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [] });
    await renderDefaultTab({});
    expect(screen.getByRole("heading", { name: "등록된 작업구역이 없습니다" })).toBeTruthy();
    expect(screen.getByRole("list", { name: "자료 등록 순서" })).toBeTruthy();
    expect(mocked.assets).not.toHaveBeenCalled();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("announces an unknown scope once without exposing the requested identifier", async () => {
    await renderDefaultTab({ workAreaId: "no-such-area" });
    expect(screen.getAllByText(/요청한 작업구역이 조회 범위에 없습니다/)).toHaveLength(1);
    expect(screen.queryByText(/no-such-area/)).toBeNull();
    expect(mocked.assets).toHaveBeenCalledWith("site-1", "tiny-1", { limit: 50 });
  });

  it("uses the bound area before a newer empty area", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [
      areaFixture({ workAreaId: "bound-1", name: "기록 있는 구역", createdAt: "2026-09-01T00:00:00Z" }),
      areaFixture({ workAreaId: "empty-new", name: "새 빈 구역", createdAt: "2026-10-12T00:00:00Z" }),
    ] });
    mocked.orders.mockResolvedValue([{ workOrderId: "w1", workAreaIds: ["bound-1"] }]);
    await renderDefaultTab({});
    expect(mocked.assets).toHaveBeenCalledWith("site-1", "bound-1", { limit: 50 });
    expect(screen.getByRole("button", { name: "작업구역 · 기록 있는 구역" })).toBeTruthy();
  });

  it("keeps denial distinct from a truly empty catalog", async () => {
    mocked.assets.mockRejectedValue(new CoreApiError(403, { code: "FORBIDDEN", message: "denied" }));
    await renderDefaultTab({ panel: "materials" });
    expect(screen.getAllByText(/조회 권한/).length).toBeGreaterThan(0);
    expect(screen.queryByText("조회된 자료가 없습니다.")).toBeNull();
  });

  it("sends legacy area sections to real routes without extra reads", async () => {
    // '등록 자료'·'분석·검토 기록' 영역은 실제 라우트가 주인이다 — 중간 진입
    // 화면을 두지 않고 범위만 실어 보낸다. 추가 카탈로그 읽기 없음.
    const error = await SiteDetailPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({ section: "analysis" }),
    }).catch((thrown: unknown) => thrown);
    expect(String((error as { digest?: unknown }).digest)).toContain("/sites/site-1/analysis");
    expect(mocked.analyses).not.toHaveBeenCalled();
    expect(mocked.assets).not.toHaveBeenCalled();
  });
});

describe("analysis status labels", () => {
  it("keeps suitability and execution visible as distinct facts", () => {
    expect(analysisStateLabel({ executionState: "COMPLETED", suitabilityState: "REASSESSMENT_REQUIRED" })).toBe("사용 조건 재확인 필요");
    expect(analysisStateLabel({ executionState: "FAILED", suitabilityState: "REASSESSMENT_REQUIRED" })).toBe("처리 실패");
  });
});
