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

function rasterAsset(assetRef: string, footprintWkt = "POLYGON ((200000 550000, 200010 550000, 200010 550010, 200000 550000))", fileName = "tile.tif", observedCrs = "EPSG:5186") {
  return {
    assetRef,
    siteId: "site-1",
    workAreaId: "tiny-1",
    workOrderId: "w1",
    observationEpochId: "e1",
    submissionRef: "s1",
    revision: 2,
    artifactId: "art-1",
    kind: "dsm",
    lifecycleState: "SEALED",
    declared: {
      factClass: "DECLARED",
      fileName,
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
    },
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
        inspectorBuildDigest: "ib",
        observedCrsIdentifier: observedCrs,
        observedCrsWkt: null,
        observedCrsDigest: "dd",
        observedVerticalReference: null,
        transform: [200000, 10, 0, 550010, 0, -10],
        footprintWkt,
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

  it("hides the selector and links directly to work areas when none exist", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [] });
    await renderDefaultTab({});
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: "구역 보기" })).toBeNull();
    expect(screen.queryByText("등록된 작업구역이 없습니다")).toBeTruthy();
    const overview = within(screen.getByRole("region", { name: "선택 구역 공간 확인" }));
    expect(overview.getByRole("link", { name: "작업구역 확인" }).getAttribute("href")).toBe("/sites/site-1/work-areas");
    expect(mocked.assets).not.toHaveBeenCalled();
  });

  it("announces an unknown scope query once without echoing the raw id", async () => {
    await renderDefaultTab({ workAreaId: "no-such-area-evil'\"><" });
    expect(screen.getByRole("status").textContent).toContain("요청한 대상을 확인할 수 없어 조회 가능한 구역을 표시합니다");
    expect(screen.queryByText(/no-such-area/)).toBeNull();
    expect(mocked.assets).toHaveBeenCalledWith("site-1", "tiny-1", { limit: 50 });
    expect(screen.getByText("등록된 구역명 · 미세 분석 구역")).toBeTruthy();
  });

  it("announces an unknown asset query while keeping the valid default footprint", async () => {
    mocked.assets.mockResolvedValue({ ...EMPTY_CATALOG, assets: [rasterAsset("asset-1")] });
    await renderDefaultTab({ assetRef: "ghost-asset" });
    expect(screen.getByRole("status").textContent).toContain("요청한 대상을 확인할 수 없어 조회 가능한 구역을 표시합니다");
    expect(screen.getByText("선택한 파일이 포함하는 범위를 함께 표시합니다.")).toBeTruthy();
  });

  it("prefers the bound area over a newer empty one when choosing the default", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [
      areaFixture({ workAreaId: "bound-1", name: "기록 있는 구역", createdAt: "2026-09-01T00:00:00Z" }),
      areaFixture({ workAreaId: "empty-new", name: "새 빈 구역", createdAt: "2026-10-12T00:00:00Z" }),
    ] });
    mocked.orders.mockResolvedValue([{ workOrderId: "w1", workAreaIds: ["bound-1"] }]);
    await renderDefaultTab({});
    expect(mocked.assets).toHaveBeenCalledWith("site-1", "bound-1", { limit: 50 });
    expect(screen.getByText("등록된 구역명 · 기록 있는 구역")).toBeTruthy();
  });

  it("skips extra reads on non-default tabs", async () => {
    render(await SiteDetailPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({ section: "analysis" }),
    }));
    expect(mocked.analyses).not.toHaveBeenCalled();
    expect(mocked.assets).not.toHaveBeenCalled();
  });
});

describe("Site spatial overview honesty", () => {
  it("leads with the native plane for tiny footprints and keeps the map secondary", async () => {
    await renderDefaultTab({});
    const map = screen.getByTestId("aoi-map");
    const vertices = JSON.parse(map.getAttribute("data-vertices") ?? "[]") as Array<{ latDeg: number; lonDeg: number }>;
    expect(vertices).toHaveLength(3);
    for (const vertex of vertices) {
      expect(vertex.latDeg).toBeGreaterThan(30);
      expect(vertex.latDeg).toBeLessThan(45);
      expect(vertex.lonDeg).toBeGreaterThan(120);
      expect(vertex.lonDeg).toBeLessThan(135);
    }
    // Tiny projected footprint: the native vector plane is the primary visual evidence.
    expect(screen.getByRole("img", { name: /작업구역 경계/ })).toBeTruthy();
    expect(screen.getByText(/EPSG:5186 · 단위 m/).closest("details")).toBeTruthy();
    expect(screen.getByText(/배경 지도에서 위치 확인/)).toBeTruthy();
  });

  it("disambiguates colliding area names with full ids and nowhere else", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [
      areaFixture({ workAreaId: "dup-1", name: "같은 구역", createdAt: "2026-09-01T00:00:00Z" }),
      areaFixture({ workAreaId: "dup-2", name: "같은 구역", createdAt: "2026-09-02T00:00:00Z" }),
    ] });
    await renderDefaultTab({});
    const options = screen.getByRole("combobox").querySelectorAll("option");
    expect([...options].map((o) => o.textContent)).toEqual(["같은 구역 · dup-1", "같은 구역 · dup-2"]);
  });

  it("disambiguates colliding file labels with file names before opaque refs and uses kind labels", async () => {
    mocked.assets.mockResolvedValue({
      ...EMPTY_CATALOG,
      assets: [
        { ...rasterAsset("ref-aaa"), declared: { ...rasterAsset("ref-aaa").declared, fileName: "same.tif", captureStartedAt: "2026-10-10T00:00:00Z", captureEndedAt: "2026-10-10T01:00:00Z" } },
        { ...rasterAsset("ref-bbb"), declared: { ...rasterAsset("ref-bbb").declared, fileName: "same.tif", captureStartedAt: "2026-10-10T00:00:00Z", captureEndedAt: "2026-10-10T01:00:00Z" } },
      ],
    });
    await renderDefaultTab({});
    const links = screen.getAllByRole("link", { name: /same\.tif/ });
    expect(links).toHaveLength(2);
    expect(links[0].textContent).toContain("등록 버전 2");
    expect(links[1].textContent).toContain("등록 버전 2");
    // 파일명까지 겹치면 짧은 결정적 식별자로 가른다 — 전체 참조는 href에 남는다.
    expect(links[0].textContent).toContain("#ref-aaa");
    expect(links[1].textContent).toContain("#ref-bbb");
    expect(links[0].getAttribute("href")).toContain("assetRef=ref-aaa");
    expect(links[1].getAttribute("href")).toContain("assetRef=ref-bbb");
    expect(screen.queryByText(/^\s*dsm\s*·/)).toBeNull();
  });

  it("prefers declared file names when captures are missing instead of opaque refs", async () => {
    mocked.assets.mockResolvedValue({
      ...EMPTY_CATALOG,
      assets: [
        { ...rasterAsset("ref-aaa"), declared: { ...rasterAsset("ref-aaa").declared, fileName: "floreat-2021.tif", captureStartedAt: null, captureEndedAt: null } },
        { ...rasterAsset("ref-bbb"), declared: { ...rasterAsset("ref-bbb").declared, fileName: "floreat-2022.tif", captureStartedAt: null, captureEndedAt: null } },
      ],
    });
    await renderDefaultTab({});
    const first = screen.getByRole("link", { name: /floreat-2021\.tif/ });
    const second = screen.getByRole("link", { name: /floreat-2022\.tif/ });
    expect(first.getAttribute("href")).toContain("assetRef=ref-aaa");
    expect(second.getAttribute("href")).toContain("assetRef=ref-bbb");
    // 파일명에서 촬영 연도를 추론하지 않는다 — 제목은 미기재 그대로 둔다.
    expect(first.textContent).toContain("촬영 구간 미기재");
    expect(first.textContent).not.toMatch(/2021\. /);
  });

  it("states unsupported CRS honestly and still draws the native plane from actual vertices", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [areaFixture({ crs: "EPSG:9999" })] });
    await renderDefaultTab({});
    expect(screen.queryByTestId("aoi-map")).toBeNull();
    expect(screen.getByText(/미리보기를 지원하지 않습니다/)).toBeTruthy();
    expect(screen.getByText(/EPSG:9999 · 단위 미확인/)).toBeTruthy();
    expect(screen.getByText(/단위 미확인/)).toBeTruthy();
  });

  it("says coincident file and area boundaries overlap instead of drawing two lines", async () => {
    mocked.assets.mockResolvedValue({
      ...EMPTY_CATALOG,
      assets: [rasterAsset("asset-1", "POLYGON ((200000 549999.8, 200010 549999.8, 200010 550009.8, 200000 549999.8))")],
    });
    await renderDefaultTab({});
    expect(screen.getByText(/선택 자료의 포함 범위와 겹칩니다/)).toBeTruthy();
  });

  it("keeps scope context useful on catalog permission denial without inventing emptiness", async () => {
    mocked.assets.mockRejectedValue(new CoreApiError(403, { detail: "denied" }));
    await renderDefaultTab({});
    expect(screen.getByText(/등록 자료를 조회할 권한이 없습니다/)).toBeTruthy();
    expect(screen.getByText("등록된 구역명 · 미세 분석 구역")).toBeTruthy();
    expect(screen.queryByText("이 구역에 조회된 공간 자산이 없습니다")).toBeNull();
    expect(screen.queryByText("조회된 자산·외부 비교 기록이 없습니다.")).toBeNull();
    expect(screen.getByText(/조회하지 못한 출처의 자료는 판단하지 않습니다/)).toBeTruthy();
  });

  it("does not claim a mismatched footprint was drawn just because raster metadata exists", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [areaFixture({ crs: "EPSG:9999" })] });
    mocked.assets.mockResolvedValue({ ...EMPTY_CATALOG, assets: [rasterAsset("asset-1")] });
    await renderDefaultTab({});
    expect(screen.getByText("위치 기준이 맞지 않아 파일 범위를 겹쳐 표시하지 않았습니다.")).toBeTruthy();
    expect(screen.queryByText("선택한 파일이 포함하는 범위를 함께 표시합니다.")).toBeNull();
  });

  it("selects an asset footprint through the scoped query instead of only linking out", async () => {
    mocked.assets.mockResolvedValue({ ...EMPTY_CATALOG, assets: [rasterAsset("asset-1")] });
    await renderDefaultTab({ assetRef: "asset-1" });
    const selected = screen.getByRole("link", { name: /선택 중/ });
    expect(selected.getAttribute("href")).toBe("/sites/site-1?workAreaId=tiny-1&assetRef=asset-1");
    expect(selected.getAttribute("aria-current")).toBe("true");
    expect(screen.getByRole("heading", { name: "선택된 자료" })).toBeTruthy();
    expect(selected.textContent).not.toMatch(/tile\.tif|revision|등록 버전/);
    expect(screen.getByText("등록 파일명 · tile.tif").closest("details")).toBeTruthy();
    expect(screen.getByText("등록 버전 2").closest("details")).toBeTruthy();
  });

  it("defaults to the first inspected raster so caption and selection always match", async () => {
    mocked.assets.mockResolvedValue({ ...EMPTY_CATALOG, assets: [rasterAsset("asset-1"), rasterAsset("asset-2", undefined, "ortho-2.tif")] });
    await renderDefaultTab({});
    const selected = screen.getByRole("link", { name: /선택 중/ });
    expect(selected.getAttribute("href")).toBe("/sites/site-1?workAreaId=tiny-1&assetRef=asset-1");
    expect(screen.getByText("선택한 파일이 포함하는 범위를 함께 표시합니다.")).toBeTruthy();
  });

  it("keeps known asset dates when the legacy read failed", async () => {
    mocked.history.mockRejectedValue(new CoreApiError(503, { detail: "unavailable" }));
    mocked.assets.mockResolvedValue({
      ...EMPTY_CATALOG,
      assets: [{
        assetRef: "asset-1",
        kind: "dsm",
        revision: 1,
        lifecycleState: "SEALED",
        declared: {
          fileName: "tile.tif",
          captureStartedAt: "2026-10-10T00:00:00Z",
          captureEndedAt: "2026-10-10T01:00:00Z",
          submittedAt: "2026-10-11T00:00:00Z",
        },
      }],
    });
    await renderDefaultTab({});
    expect(screen.getByRole("link", { name: /촬영/ }).getAttribute("href")).toContain("assetRef=asset-1");
    expect(screen.getByText(/외부 비교 기록을 조회하지 못했습니다/)).toBeTruthy();
  });

  it("keeps V2 analysis records separate from an empty legacy history", async () => {
    mocked.analyses.mockResolvedValue({
      siteId: "site-1",
      items: [{
        analysisId: "a1",
        siteId: "site-1",
        workAreaId: "tiny-1",
        executionState: "COMPLETED",
        suitabilityState: "EVALUATED",
        createdAt: "2026-10-14T00:00:00Z",
        resultId: "res-1",
        metrics: null,
        limitationCount: 0,
        analysisHref: "/sites/site-1/analysis?analysisId=a1",
      }],
      nextCursor: null,
    });
    await renderDefaultTab({});
    const v2 = within(screen.getByRole("heading", { name: "이 구역의 최근 분석" }).closest("div") as HTMLElement);
    expect(v2.getByText("분석 조건 확인 결과 있음")).toBeTruthy();
    expect(screen.getByRole("link", { name: "이 구역의 최근 분석 확인" }).getAttribute("href")).toBe("/sites/site-1/analysis?workAreaId=tiny-1&analysisId=a1");
    expect(screen.queryByText("외부 관측 결과가 없습니다")).toBeNull();
  });

  it("maps raw analysis states to Korean without inventing review status", async () => {
    mocked.analyses.mockResolvedValue({
      siteId: "site-1",
      items: [{
        analysisId: "a1",
        siteId: "site-1",
        workAreaId: "tiny-1",
        executionState: "COMPLETED",
        suitabilityState: "REASSESSMENT_REQUIRED",
        createdAt: "2026-10-14T00:00:00Z",
        resultId: null,
        metrics: null,
        limitationCount: 1,
        analysisHref: "/sites/site-1/analysis?analysisId=a1",
      }],
      nextCursor: null,
    });
    await renderDefaultTab({});
    expect(screen.getByText("사용 조건 재확인 필요")).toBeTruthy();
    expect(screen.queryByText(/REASSESSMENT_REQUIRED/)).toBeNull();
  });

  it("shows one latest analysis with a full-list link instead of a card stack", async () => {
    mocked.analyses.mockResolvedValue({
      siteId: "site-1",
      items: Array.from({ length: 8 }, (_, i) => ({
        analysisId: `a${i + 1}`,
        siteId: "site-1",
        workAreaId: "tiny-1",
        executionState: "COMPLETED",
        suitabilityState: "EVALUATED",
        createdAt: `2026-10-${String(14 - i).padStart(2, "0")}T00:00:00Z`,
        resultId: `res-${i + 1}`,
        metrics: null,
        limitationCount: 0,
        analysisHref: `/sites/site-1/analysis?analysisId=a${i + 1}`,
      })),
      nextCursor: null,
    });
    await renderDefaultTab({});
    expect(screen.getAllByRole("link", { name: "이 구역의 최근 분석 확인" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "현장 분석 기록 보기" })).toBeTruthy();
  });

  it("offers one primary next action with the rest as inline links", async () => {
    await renderDefaultTab({});
    const actions = within(screen.getByRole("navigation", { name: "선택 구역 다음 확인" }));
    expect(actions.getByRole("link", { name: "변화 분석 보기" }).className).toContain("btn-primary");
    expect(actions.getByRole("link", { name: "등록 자료 보기" })).toBeTruthy();
    expect(actions.getByRole("link", { name: "외부 비교 기록" })).toBeTruthy();
  });

  it("links the header to the preserved AOI anchor on the manage tab", async () => {
    await renderDefaultTab({});
    expect(screen.getByRole("link", { name: "현장 전체 범위 보기" }).getAttribute("href"))
      .toBe("/sites/site-1?section=manage#site-aoi");
  });

  function grantPermissions(...perms: string[]) {
    mocked.permissions.mockImplementation((perm: string) => Promise.resolve(perms.includes(perm)));
  }

  function analysisResultFixture() {
    return {
      siteId: "site-1",
      items: [{
        analysisId: "a1",
        siteId: "site-1",
        workAreaId: "tiny-1",
        executionState: "COMPLETED",
        suitabilityState: "EVALUATED",
        createdAt: "2026-10-14T00:00:00Z",
        resultId: "res-1",
        metrics: null,
        limitationCount: 0,
        analysisHref: "/sites/site-1/analysis?analysisId=a1",
      }],
      nextCursor: null,
    };
  }

  it("hides the duplicate register link when the primary action already registers this scope", async () => {
    grantPermissions("WORK_ORDERS_WRITE");
    await renderDefaultTab({});
    const actions = within(screen.getByRole("navigation", { name: "선택 구역 다음 확인" }));
    const registerHrefs = actions.getAllByRole("link").map((link) => link.getAttribute("href"));
    expect(registerHrefs.filter((href) => href === "/sites/site-1/observations/new?workAreaId=tiny-1")).toHaveLength(1);
    expect(actions.queryByRole("link", { name: "이 구역 자료 등록" })).toBeNull();
  });

  it("gives viewers one accurate Site-history link, not a dead form anchor or a false filtered-list claim", async () => {
    mocked.analyses.mockResolvedValue(analysisResultFixture());
    await renderDefaultTab({});
    const actions = within(screen.getByRole("navigation", { name: "선택 구역 다음 확인" }));
    expect(actions.queryByRole("link", { name: "이 구역 변화 비교" })).toBeNull();
    const listLink = screen.getByRole("link", { name: "현장 분석 기록 보기" });
    expect(listLink.getAttribute("href")).toBe("/sites/site-1/analysis?workAreaId=tiny-1");
    expect(listLink.getAttribute("href")).not.toContain("#new-analysis-request");
    expect(actions.getByRole("link", { name: "이 구역의 최근 분석 확인" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "이 구역 분석 기록 보기" })).toBeNull();
  });

  it("shows the scoped compare entry to analysis writers without registration permission", async () => {
    grantPermissions("SITES_WRITE");
    await renderDefaultTab({});
    const actions = within(screen.getByRole("navigation", { name: "선택 구역 다음 확인" }));
    expect(actions.queryByRole("link", { name: "이 구역 자료 등록" })).toBeNull();
    const compare = actions.getByRole("link", { name: "이 구역 변화 비교" });
    expect(compare.getAttribute("href")).toBe("/sites/site-1/analysis?workAreaId=tiny-1#new-analysis-request");
  });

  it("keeps both scoped entries distinct for writers with a prior result", async () => {
    grantPermissions("WORK_ORDERS_WRITE", "SITES_WRITE");
    mocked.analyses.mockResolvedValue(analysisResultFixture());
    await renderDefaultTab({});
    const actions = within(screen.getByRole("navigation", { name: "선택 구역 다음 확인" }));
    expect(actions.getByRole("link", { name: "이 구역 자료 등록" }).getAttribute("href"))
      .toBe("/sites/site-1/observations/new?workAreaId=tiny-1");
    expect(actions.getByRole("link", { name: "이 구역 변화 비교" }).getAttribute("href"))
      .toBe("/sites/site-1/analysis?workAreaId=tiny-1#new-analysis-request");
    expect(actions.queryByRole("link", { name: "이 구역 분석 기록 보기" })).toBeNull();
  });

  it("keeps an archived scope readable without offering new registration or a dead comparison form", async () => {
    grantPermissions("WORK_ORDERS_WRITE", "SITES_WRITE");
    mocked.areas.mockResolvedValue({ workAreas: [areaFixture({ status: "ARCHIVED" })] });
    await renderDefaultTab({ workAreaId: "tiny-1" });
    const actions = within(screen.getByRole("navigation", { name: "선택 구역 다음 확인" }));
    expect(actions.getAllByRole("link").every((link) => !/observations\/new|#new-analysis-request/.test(link.getAttribute("href") ?? ""))).toBe(true);
    expect(actions.getByRole("link", { name: "등록 자료 보기" }).getAttribute("href")).toContain("workAreaId=tiny-1");
    expect(actions.getByText(/보관된 구역입니다/)).toBeTruthy();
  });
});
