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
  workspace: vi.fn(),
}));

vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/permissions", () => ({ hasAllPermissions: mocked.permissions }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ listObservationWorkOrders: mocked.orders }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({ listSiteExternalVolumeHistory: mocked.history }));
vi.mock("@/lib/core-api/analysis", () => ({ listAnalyses: mocked.analyses, getAnalysis: mocked.detail }));
vi.mock("@/lib/core-api/spatial-assets", () => ({ listSpatialAssets: mocked.assets }));
vi.mock("@/lib/core-api/spatial-workspace", () => ({ listSpatialWorkspaceObservations: mocked.workspace }));
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

function wireCapture(overrides: Record<string, unknown> = {}) {
  return {
    factClass: "DECLARED_CAPTURE",
    precision: "EXACT_INTERVAL",
    captureStartedAt: "2021-08-17T10:00:00Z",
    captureEndedAt: "2021-08-17T11:00:00Z",
    captureDate: null,
    ...overrides,
  };
}

function wireVersion(assetRef: string, overrides: Record<string, unknown> = {}) {
  return {
    assetRef,
    submissionRef: `s-${assetRef}`,
    revision: 1,
    artifactId: `art-${assetRef}`,
    kind: "dsm",
    lifecycleState: "SEALED",
    capture: wireCapture(),
    declaredCrs: "EPSG:5186",
    declaredVerticalReferencePresent: false,
    declaredGsdM: null,
    submittedAt: "2021-08-18T00:00:00Z",
    observedSha256: null,
    observedSizeBytes: null,
    observedAt: null,
    inspectionState: "COMPLETED",
    inspectionOutcome: "MEASURED",
    inspectionReason: null,
    inspectedRasterAvailable: true,
    displayState: "NOT_SEALED",
    displayReady: false,
    chronology: "EXACT_INTERVAL_CANDIDATE",
    chronologyCandidate: true,
    quantitativeEligibility: "NOT_EVALUATED",
    ...overrides,
  };
}

function wireObservation(epochId: string, assetRefs: string[], overrides: Record<string, unknown> = {}) {
  const versions = assetRefs.map((ref) => wireVersion(ref));
  return {
    observationEpochId: epochId,
    workOrderId: `w-${epochId}`,
    capture: wireCapture(),
    captureSourcesAgree: true,
    versions,
    viewAvailable: true,
    viewUnavailableReason: null,
    viewAssetRef: assetRefs[0],
    newerRevisionPending: false,
    newerRevisionState: null,
    chronologyCandidate: true,
    hasSealedVersion: true,
    ...overrides,
  };
}

function workspacePage(overrides: Record<string, unknown> = {}) {
  return {
    contractVersion: "site-spatial-workspace-page.v1",
    siteId: "site-1",
    workAreaId: "tiny-1",
    scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY",
    scopeNote: "",
    observations: [],
    entryDefault: {
      observationEpochId: null,
      viewAssetRef: null,
      reason: "NO_OBSERVATIONS",
      detail: "No observations are registered for this Site/WorkArea scope.",
      tiedObservationEpochIds: [],
    },
    nextCursor: null,
    hasMore: false,
    ...overrides,
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
  mocked.workspace.mockResolvedValue(workspacePage());
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

  it("reads the projection once per selected area with a bounded limit", async () => {
    await renderOverview({});
    expect(mocked.workspace).toHaveBeenCalledTimes(1);
    expect(mocked.workspace).toHaveBeenCalledWith("site-1", "tiny-1", { limit: 50 });
  });

  it("uses the server default display version for the first viewport", async () => {
    mocked.workspace.mockResolvedValue(workspacePage({
      observations: [
        wireObservation("epoch-2021", ["disp-2021"], { capture: wireCapture() }),
        wireObservation("epoch-2022", ["disp-2022"], { capture: wireCapture({ captureStartedAt: "2022-08-24T10:00:00Z", captureEndedAt: "2022-08-24T11:00:00Z" }) }),
      ],
      entryDefault: {
        observationEpochId: "epoch-2022",
        viewAssetRef: "disp-2022",
        reason: "LATEST_EXACT_VIEW_AVAILABLE",
        detail: "Latest view-available observation by exact capture interval.",
        tiedObservationEpochIds: [],
      },
    }));
    mocked.assets.mockResolvedValue({ ...EMPTY_CATALOG, assets: [rasterAsset("first-raster"), rasterAsset("disp-2022")] });
    await renderOverview({});
    const panel = screen.getByRole("region", { name: "기본 관측 선택 상태" });
    expect(panel.textContent).toContain("보여주는 관측");
    expect(panel.textContent).toContain("등록 순서로 고르지 않았습니다");
    expect(panel.textContent).toContain("사유 코드 · LATEST_EXACT_VIEW_AVAILABLE");
    const selected = screen.getByRole("link", { name: /선택 중/ });
    expect(selected.getAttribute("href")).toContain("assetRef=disp-2022");
  });

  it("shows a truthful no-view state without calling anything latest", async () => {
    mocked.workspace.mockResolvedValue(workspacePage({
      observations: [wireObservation("epoch-2021", ["v1"], {
        viewAvailable: false,
        viewUnavailableReason: "NO_DISPLAY_READY_VERSION",
        viewAssetRef: null,
        versions: [wireVersion("v1")],
      })],
      entryDefault: {
        observationEpochId: null,
        viewAssetRef: null,
        reason: "NO_VIEW_AVAILABLE_OBSERVATION",
        detail: "Observations exist but none has a display-ready version.",
        tiedObservationEpochIds: [],
      },
    }));
    mocked.assets.mockResolvedValue({ ...EMPTY_CATALOG, assets: [rasterAsset("asset-1")] });
    await renderOverview({});
    const panel = screen.getByRole("region", { name: "기본 관측 선택 상태" });
    // "자료가 없다"가 아니라 "표시용 파생물이 아직 없다"로 구분한다 — 확인된
    // 관측이 있는 현장인데도 없는 것처럼 읽히면 안 된다.
    expect(panel.textContent).toContain("표시용 파생물이 아직 준비되지 않았습니다");
    expect(panel.textContent).toContain("확인된 관측은 1건입니다");
    expect(panel.textContent).toContain("구역 자료 준비에서 직접 요청하세요");
    expect(panel.textContent).toContain("표시용 출력의 봉인이 끝나지 않았습니다");
    expect(panel.textContent).toContain("서버가 정한 기본 관측이 아닙니다");
    expect(screen.queryByText(/최신/)).toBeNull();
    // 자료가 있는 현장에서 "관측이 없습니다"로 읽히면 안 된다.
    expect(panel.textContent).not.toContain("관측이 없습니다");
  });

  it("shows registration guidance only for real absence", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [areaFixture()] });
    await renderOverview({});
    const panel = screen.getByRole("region", { name: "기본 관측 선택 상태" });
    expect(panel.textContent).toContain("등록된 관측이 없습니다");
  });

  it("states ambiguity with the tied candidates instead of picking one", async () => {
    mocked.workspace.mockResolvedValue(workspacePage({
      observations: [
        wireObservation("epoch-a", ["va"], { capture: wireCapture() }),
        wireObservation("epoch-b", ["vb"], { capture: wireCapture() }),
      ],
      entryDefault: {
        observationEpochId: null,
        viewAssetRef: null,
        reason: "CAPTURE_TIE_AMBIGUOUS",
        detail: "Two or more view-available observations share the same exact capture interval.",
        tiedObservationEpochIds: ["epoch-a", "epoch-b"],
      },
    }));
    await renderOverview({});
    const panel = screen.getByRole("region", { name: "기본 관측 선택 상태" });
    expect(panel.textContent).toContain("자동으로 고르지 않았습니다");
    expect(panel.textContent).not.toContain("보여주는 관측");
  });
});

describe("workspace compare mode", () => {
  function readyProjection() {
    return workspacePage({
      observations: [
        wireObservation("epoch-2021", ["exact-1"], {
          capture: wireCapture(),
          versions: [wireVersion("exact-1", { displayReady: true, displayState: "SEALED" })],
        }),
        wireObservation("epoch-2022", ["date-only-2"], {
          capture: wireCapture({ precision: "DATE_ONLY", captureStartedAt: null, captureEndedAt: null, captureDate: "2021-08-17" }),
          chronologyCandidate: false,
          viewAvailable: false,
          viewUnavailableReason: "NO_DISPLAY_READY_VERSION",
          viewAssetRef: null,
          versions: [wireVersion("date-only-2", { capture: wireCapture({ precision: "DATE_ONLY", captureStartedAt: null, captureEndedAt: null, captureDate: "2021-08-17" }), chronologyCandidate: false })],
        }),
      ],
      entryDefault: {
        observationEpochId: "epoch-2021",
        viewAssetRef: "exact-1",
        reason: "LATEST_EXACT_VIEW_AVAILABLE",
        detail: "Latest view-available observation by exact capture interval.",
        tiedObservationEpochIds: [],
      },
    });
  }

  it("renders one coherent prompt with an honest unavailable-sync notice", async () => {
    mocked.workspace.mockResolvedValue(readyProjection());
    await renderOverview({ mode: "compare" });
    expect(screen.getByText(/비교할 기준 자료와 비교 자료를 아래에서 고르세요/)).toBeTruthy();
    // 고르기 전에는 빈 칸 두 개를並べ지 않는다 — 한 개의 안내만 둔다.
    expect(screen.queryByRole("region", { name: "기준 자료" })).toBeNull();
    expect(screen.queryByRole("region", { name: "비교 자료" })).toBeNull();
    expect(screen.getByText(/탐색에서 날짜·층별로 확인/)).toBeTruthy();
    expect(screen.getByText(/동기화된 공간 비교\(같은 범위 맞춤·같은 색 눈금\)는 지원하지 않습니다/)).toBeTruthy();
    expect(screen.getByText(/나란히 보기 안내/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "구역 자료 준비" }).getAttribute("href")).toBe(
      "/sites/site-1/spatial-data-requests?workAreaId=tiny-1",
    );
  });

  it("renders two equal-weight map slots once both inputs are chosen", async () => {
    mocked.workspace.mockResolvedValue(workspacePage({
      observations: [
        wireObservation("epoch-2021", ["exact-1"], {
          capture: wireCapture(),
          versions: [wireVersion("exact-1", { displayReady: true, displayState: "SEALED" })],
        }),
        wireObservation("epoch-2022", ["exact-2"], {
          capture: wireCapture({ captureStartedAt: "2022-08-24T10:00:00Z", captureEndedAt: "2022-08-24T11:00:00Z" }),
          versions: [wireVersion("exact-2", {
            capture: wireCapture({ captureStartedAt: "2022-08-24T10:00:00Z", captureEndedAt: "2022-08-24T11:00:00Z" }),
            displayReady: true,
            displayState: "SEALED",
          })],
        }),
      ],
      entryDefault: {
        observationEpochId: "epoch-2022",
        viewAssetRef: "exact-2",
        reason: "LATEST_EXACT_VIEW_AVAILABLE",
        detail: "Latest view-available observation by exact capture interval.",
        tiedObservationEpochIds: [],
      },
    }));
    await renderOverview({ mode: "compare", baselineAssetRef: "exact-1", currentAssetRef: "exact-2" });
    expect(screen.getByRole("region", { name: "기준 자료" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "비교 자료" })).toBeTruthy();
  });

  it("lists orderable candidates and keeps date-only observations browsable at real precision", async () => {
    mocked.workspace.mockResolvedValue(readyProjection());
    mocked.assets.mockResolvedValue({
      ...EMPTY_CATALOG,
      assets: [rasterAsset("exact-1"), rasterAsset("date-only-2", { captureStartedAt: null, captureEndedAt: null, captureDate: "2021-08-17" })],
    });
    await renderOverview({ mode: "compare", baselineAssetRef: "exact-1", currentAssetRef: "ghost-asset" });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("요청한 비교 대상을 확인할 수 없습니다");
    expect(alert.textContent).toContain("자동으로 다른 자료로 바꾸지 않았습니다");
    expect(screen.getByText(/시간 순서 비교 후보는 아니지만 둘러볼 수 있습니다/)).toBeTruthy();
    expect(screen.getAllByText(/날짜만 확인 · 시각 미상/).length).toBeGreaterThan(0);
  });

  it("fails closed on an unknown explicit comparison without substituting another asset", async () => {
    mocked.workspace.mockResolvedValue(readyProjection());
    await renderOverview({ mode: "compare", baselineAssetRef: "exact-1", currentAssetRef: "ghost-asset" });
    expect(screen.queryByText(/선택 중/)).toBeNull();
    // 빈 칸 두 개+경고 쌓기가 아니라 하나의 막힘 안내만 둔다.
    expect(screen.queryByRole("region", { name: "기준 자료" })).toBeNull();
    expect(screen.queryByRole("region", { name: "비교 자료" })).toBeNull();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("fails closed when both sides name the same version", async () => {
    mocked.workspace.mockResolvedValue(readyProjection());
    await renderOverview({ mode: "compare", baselineAssetRef: "exact-1", currentAssetRef: "exact-1" });
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

  it("shows the recorded quantities with their limitation on the first results screen", async () => {
    mocked.analyses.mockResolvedValue({
      siteId: "site-1",
      items: [analysisItem({
        metrics: { cutM3: 0, fillM3: 800, netM3: 800, thresholdM: 0, uncertaintyM3: null },
        suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED",
        limitationCount: 1,
      })],
      nextCursor: null,
    });
    await renderOverview({ mode: "results" });
    const filled = screen.getByText("성토").closest("div");
    expect(filled?.textContent).toContain("800 m³");
    const net = screen.getByText("순변화").closest("div");
    expect(net?.textContent).toContain("800 m³");
    // 수치 옆에 한계가 함께 있어야 한다 — 값만 떼어 내지 않는다.
    expect(screen.getByText(/정확도 평가는 아직 확인되지 않았습니다/)).toBeTruthy();
    expect(screen.getByText(/물량 정확도 보증·측량 승인·정산 근거가 아닙니다/)).toBeTruthy();
  });

  it("restores an exact explicit result with its original inputs matched to the projection", async () => {
    mocked.analyses.mockResolvedValue({ siteId: "site-1", items: [], nextCursor: null });
    mocked.workspace.mockResolvedValue(workspacePage({
      observations: [
        wireObservation("epoch-base", ["base-v"], { workOrderId: "w1", versions: [wireVersion("base-v", { submissionRef: "s1", revision: 1 })] }),
        wireObservation("epoch-cur", ["cur-v"], { workOrderId: "w2", versions: [wireVersion("cur-v", { submissionRef: "s2", revision: 1 })] }),
      ],
    }));
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
    expect(screen.getByText(/원래 입력 2건이 현재 관측 목록에 있습니다/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "분석 기록 열기" }).getAttribute("href")).toBe(
      "/sites/site-1/analysis?analysisId=a9",
    );
  });

  it("keeps the record when its original inputs left the current list", async () => {
    mocked.analyses.mockResolvedValue({ siteId: "site-1", items: [], nextCursor: null });
    mocked.detail.mockResolvedValue({
      analysisId: "a9",
      siteId: "site-1",
      workAreaId: "tiny-1",
      baseline: { workOrderId: "w-gone", submissionRef: "s-gone", revision: 9 },
      current: { workOrderId: "w-gone", submissionRef: "s-gone", revision: 9 },
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
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(/원래 입력을 현재 목록에서 확인할 수 없습니다. 기록은 그대로 둡니다/)).toBeTruthy();
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
