/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  site: vi.fn(),
  permissions: vi.fn(),
  areas: vi.fn(),
  orders: vi.fn(),
  history: vi.fn(),
  analyses: vi.fn(),
  detail: vi.fn(),
  assets: vi.fn(),
}));

vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/permissions", () => ({ hasAllPermissions: mocked.permissions }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ listObservationWorkOrders: mocked.orders }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({ listSiteExternalVolumeHistory: mocked.history }));
vi.mock("@/lib/core-api/analysis", () => ({ listAnalyses: mocked.analyses, getAnalysis: mocked.detail }));
vi.mock("@/lib/core-api/spatial-assets", () => ({ listSpatialAssets: mocked.assets }));
vi.mock("@/components/map/AoiPolygonMap", () => ({
  AoiPolygonMap: ({ value }: { value: unknown }) => (
    <div data-testid="aoi-map" data-vertices={JSON.stringify(value)} />
  ),
}));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("NEXT_NOT_FOUND"); }, useRouter: () => ({ refresh: () => {} }) }));

import SiteDetailPage from "@/app/sites/[siteId]/page";
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

function declared(overrides: Record<string, unknown> = {}) {
  return {
    factClass: "DECLARED",
    fileName: "tile.tif",
    format: "GeoTIFF",
    contentType: "image/tiff",
    sha256: "aa",
    sizeBytes: 10,
    crs: "EPSG:5186",
    verticalReference: null,
    gsdM: null,
    submittedAt: "2026-10-11T00:00:00Z",
    producerCompletedAt: null,
    captureStartedAt: "2026-10-10T00:00:00Z",
    captureEndedAt: "2026-10-10T01:00:00Z",
    ...overrides,
  };
}

function rasterAsset(assetRef: string, declaredOverrides: Record<string, unknown> = {}, observedCrs = "EPSG:5186") {
  return {
    assetRef,
    siteId: "site-1",
    workAreaId: "tiny-1",
    workOrderId: "w1",
    observationEpochId: `epoch-${assetRef}`,
    submissionRef: "s1",
    revision: 2,
    artifactId: "art-1",
    kind: "dsm",
    lifecycleState: "SEALED",
    declared: declared(declaredOverrides),
    observed: null,
    inspection: {
      state: "COMPLETED",
      reportDigest: null,
      outcome: "MEASURED",
      reason: null,
      inspectorBuildDigest: null,
      raster: {
        factClass: "INSPECTED",
        sourceReportDigest: "rr",
        observedCrsIdentifier: observedCrs,
        observedCrsWkt: null,
        observedCrsDigest: "dd",
        observedVerticalReference: null,
        transform: [200000, 10, 0, 550010, 0, -10],
        footprintWkt: "POLYGON ((200000 550000, 200010 550000, 200010 550010, 200000 550000))",
        footprintDigest: "fd",
        width: 100,
        height: 100,
      },
    },
    dataAccess: "NOT_AVAILABLE_FROM_CATALOG",
    analysisStatus: "NOT_EVALUATED",
    supportedActions: ["VIEW_METADATA"],
  };
}

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

function analysisItem(overrides: Record<string, unknown> = {}) {
  return {
    analysisId: "a1",
    siteId: "site-1",
    workAreaId: "tiny-1",
    executionState: "COMPLETED",
    suitabilityState: "REASSESSMENT_REQUIRED",
    createdAt: "2026-10-14T00:00:00Z",
    resultId: "res-1",
    metrics: null,
    limitationCount: 1,
    analysisHref: "/sites/site-1/analysis?analysisId=a1",
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
  mocked.detail.mockRejectedValue(new CoreApiError(404, { detail: "not found" }));
  mocked.assets.mockResolvedValue(EMPTY_CATALOG);
});

async function renderOverview(searchParams: Record<string, string> = {}) {
  render(await SiteDetailPage({
    params: Promise.resolve({ siteId: "site-1" }),
    searchParams: Promise.resolve(searchParams),
  }));
}

describe("workspace shell structure", () => {
  it("shows each mode once without duplicating the site-name heading", async () => {
    await renderOverview({});
    const modeNav = screen.getByRole("navigation", { name: "공간 작업 방식" });
    const modeLinks = within(modeNav).getAllByRole("link");
    expect(modeLinks.map((link) => link.textContent)).toEqual(["탐색", "비교", "결과"]);
    expect(within(modeNav).getByRole("link", { name: "탐색" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getAllByRole("heading", { name: "현장 하나" })).toHaveLength(1);
    expect(mocked.detail).not.toHaveBeenCalled();
  });

  it("leads explore with real inspection-backed spatial content", async () => {
    mocked.assets.mockResolvedValue({ ...EMPTY_CATALOG, assets: [rasterAsset("asset-1")] });
    await renderOverview({});
    expect(screen.getByRole("img", { name: /작업구역 경계/ })).toBeTruthy();
    expect(screen.getByText("선택한 파일이 포함하는 범위를 함께 표시합니다.")).toBeTruthy();
  });

  it("keeps the denied-catalog scope readable in explore without inventing emptiness", async () => {
    mocked.assets.mockRejectedValue(new CoreApiError(403, { detail: "denied" }));
    await renderOverview({});
    expect(screen.getByText(/등록 자료를 조회할 권한이 없습니다/)).toBeTruthy();
    expect(screen.getByText("등록된 구역명 · 미세 분석 구역")).toBeTruthy();
  });
});

describe("workspace compare mode", () => {
  it("renders two equal-weight map slots with an honest unavailable-sync notice", async () => {
    await renderOverview({ mode: "compare" });
    expect(screen.getByText(/비교할 기준 자료와 비교 자료를 아래에서 고르세요/)).toBeTruthy();
    expect(screen.getByRole("region", { name: "기준 자료" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "비교 자료" })).toBeTruthy();
    expect(screen.getByText(/동기화된 공간 비교\(같은 범위 맞춤·같은 색 눈금\)는 지원하지 않습니다/)).toBeTruthy();
    expect(screen.getByText(/나란히 보기 안내/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "구역 자료 준비" }).getAttribute("href")).toBe(
      "/sites/site-1/spatial-data-requests?workAreaId=tiny-1",
    );
  });

  it("restores two exact versions and labels a calendar-only capture at its real precision", async () => {
    mocked.assets.mockResolvedValue({
      ...EMPTY_CATALOG,
      assets: [
        rasterAsset("exact-1"),
        rasterAsset("date-only-2", { captureStartedAt: null, captureEndedAt: null, captureDate: "2021-08-17" }, "EPSG:5186"),
      ],
    });
    await renderOverview({ mode: "compare", baselineAssetRef: "exact-1", currentAssetRef: "date-only-2" });
    expect(screen.queryByRole("alert")).toBeNull();
    const baseline = within(screen.getByRole("region", { name: "기준 자료" }));
    const current = within(screen.getByRole("region", { name: "비교 자료" }));
    expect(baseline.getAllByText(/촬영/).length).toBeGreaterThan(0);
    expect(current.getAllByText(/2021\. 8\. 17\./).length).toBeGreaterThan(0);
    expect(current.getAllByText(/날짜만 확인 · 시각 미상/).length).toBeGreaterThan(0);
    expect(current.queryByText(/10:00/)).toBeNull();
  });

  it("labels an unknown capture without rendering a date or time", async () => {
    mocked.assets.mockResolvedValue({
      ...EMPTY_CATALOG,
      assets: [
        rasterAsset("exact-1"),
        rasterAsset("unknown-2", { captureStartedAt: null, captureEndedAt: null }),
      ],
    });
    await renderOverview({ mode: "compare", baselineAssetRef: "exact-1", currentAssetRef: "unknown-2" });
    const current = within(screen.getByRole("region", { name: "비교 자료" }));
    expect(current.getAllByText(/포착 시점을 확인할 수 없습니다/).length).toBeGreaterThan(0);
  });

  it("fails closed on an unknown explicit comparison without substituting another asset", async () => {
    mocked.assets.mockResolvedValue({ ...EMPTY_CATALOG, assets: [rasterAsset("asset-1"), rasterAsset("asset-2")] });
    await renderOverview({ mode: "compare", baselineAssetRef: "asset-1", currentAssetRef: "ghost-asset" });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("요청한 비교 대상을 확인할 수 없습니다");
    expect(alert.textContent).toContain("자동으로 다른 자료로 바꾸지 않았습니다");
    expect(screen.getAllByText(/아직 고르지 않았습니다/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/선택 중/)).toBeNull();
  });

  it("fails closed when both sides name the same version", async () => {
    mocked.assets.mockResolvedValue({ ...EMPTY_CATALOG, assets: [rasterAsset("asset-1")] });
    await renderOverview({ mode: "compare", baselineAssetRef: "asset-1", currentAssetRef: "asset-1" });
    expect(screen.getByRole("alert").textContent).toContain("요청한 비교 대상을 확인할 수 없습니다");
  });
});

describe("workspace results mode", () => {
  it("shows existing record content with limitations before any new-request form", async () => {
    mocked.analyses.mockResolvedValue({ siteId: "site-1", items: [analysisItem()], nextCursor: null });
    await renderOverview({ mode: "results" });
    expect(screen.getByRole("heading", { name: /결과와 근거/ })).toBeTruthy();
    expect(screen.getByText("사용 조건 재확인 필요")).toBeTruthy();
    expect(screen.getByText(/제한 1건/)).toBeTruthy();
    const openLink = screen.getByRole("link", { name: "분석 기록 열기" });
    expect(openLink.getAttribute("href")).toBe("/sites/site-1/analysis?analysisId=a1");
    expect(screen.getByRole("heading", { name: "새 비교 요청" })).toBeTruthy();
    expect(screen.getByText(/새 비교는 기준·현재 두 시점을 다시 고릅니다/)).toBeTruthy();
  });

  it("restores an exact explicit result with its original record", async () => {
    mocked.analyses.mockResolvedValue({ siteId: "site-1", items: [], nextCursor: null });
    mocked.detail.mockResolvedValue({
      analysisId: "a9",
      siteId: "site-1",
      workAreaId: "tiny-1",
      baseline: { workOrderId: "w1", submissionRef: "s1", revision: 1 },
      current: { workOrderId: "w2", submissionRef: "s2", revision: 1 },
      executionState: "COMPLETED",
      suitabilityState: "EVALUATED",
      blockers: [],
      result: null,
      evidenceRevision: 1,
      evidenceDigest: "ed",
      evidenceHref: "/evidence",
      coverageHref: null,
      createdAt: "2026-10-13T00:00:00Z",
    });
    await renderOverview({ mode: "results", analysisId: "a9" });
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "a9");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(/링크의 원래 기록을 그대로 보여줍니다/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "분석 기록 열기" }).getAttribute("href")).toBe(
      "/sites/site-1/analysis?analysisId=a9",
    );
  });

  it("fails closed on an unknown explicit result without substituting the latest", async () => {
    mocked.analyses.mockResolvedValue({ siteId: "site-1", items: [analysisItem()], nextCursor: null });
    mocked.detail.mockRejectedValue(new CoreApiError(404, { detail: "not found" }));
    await renderOverview({ mode: "results", analysisId: "ghost-analysis" });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("요청한 분석 기록을 확인할 수 없습니다");
    expect(alert.textContent).toContain("자동으로 최근 기록으로 바꾸지 않았습니다");
  });
});
