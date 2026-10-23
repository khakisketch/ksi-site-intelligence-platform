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
  detail: vi.fn(),
  assets: vi.fn(),
  workspace: vi.fn(),
  prepared: vi.fn(),
}));

vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/permissions", () => ({ hasAllPermissions: mocked.permissions }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ listObservationWorkOrders: mocked.orders }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({ listSiteExternalVolumeHistory: mocked.history }));
vi.mock("@/lib/core-api/analysis", () => ({ listAnalyses: mocked.analyses, getAnalysis: mocked.detail }));
vi.mock("@/lib/core-api/spatial-assets", () => ({ listSpatialAssets: mocked.assets }));
vi.mock("@/lib/core-api/spatial-workspace", () => ({ listSpatialWorkspaceObservations: mocked.workspace }));
vi.mock("@/lib/core-api/spatial-data-requests", () => ({ listSpatialDataRequests: mocked.prepared }));
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

function areaFixture(workAreaId: string, name: string) {
  return {
    schemaVersion: "1.0",
    siteId: "site-1",
    workAreaId,
    name,
    polygon: TINY_5186,
    crs: "EPSG:5186",
    status: "ACTIVE",
    supersedes: null,
    createdAt: "2026-10-10T00:00:00Z",
  };
}

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
    captureStartedAt: "2021-08-17T10:00:00Z",
    captureEndedAt: "2021-08-17T11:00:00Z",
    ...overrides,
  };
}

function rasterAsset(assetRef: string) {
  return {
    assetRef,
    siteId: "site-1",
    workAreaId: "tiny-1",
    workOrderId: "w1",
    observationEpochId: "epoch-2021",
    submissionRef: "s1",
    revision: 2,
    artifactId: "art-1",
    kind: "dsm",
    lifecycleState: "SEALED",
    declared: declared(),
    observed: null,
    inspection: {
      state: "COMPLETED",
      reportDigest: null,
      outcome: "MEASURED",
      reason: null,
      inspectorReportDigest: null,
      raster: {
        factClass: "INSPECTED",
        sourceReportDigest: "rr",
        observedCrsIdentifier: "EPSG:5186",
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

function wireCapture() {
  return {
    factClass: "DECLARED_CAPTURE",
    precision: "EXACT_INTERVAL",
    captureStartedAt: "2021-08-17T10:00:00Z",
    captureEndedAt: "2021-08-17T11:00:00Z",
    captureDate: null,
  };
}

function workspaceReadyPage() {
  return {
    contractVersion: "site-spatial-workspace-page.v1",
    siteId: "site-1",
    workAreaId: "tiny-1",
    scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY",
    scopeNote: "",
    observations: [{
      observationEpochId: "epoch-2021",
      workOrderId: "w1",
      capture: wireCapture(),
      captureSourcesAgree: true,
      versions: [{
        assetRef: "disp-2022",
        submissionRef: "s1",
        revision: 1,
        artifactId: "art-1",
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
        displayState: "SEALED",
        displayReady: true,
        chronology: "EXACT_INTERVAL_CANDIDATE",
        chronologyCandidate: true,
        quantitativeEligibility: "NOT_EVALUATED",
        viewAssetRef: "disp-2022",
        viewAvailable: true,
        viewUnavailableReason: null,
      }],
      viewAvailable: true,
      viewUnavailableReason: null,
      viewAssetRef: "disp-2022",
      newerRevisionPending: false,
      newerRevisionState: null,
      chronologyCandidate: true,
      hasSealedVersion: true,
    },
    {
      observationEpochId: "epoch-2022",
      workOrderId: "w2",
      capture: { factClass: "DECLARED_CAPTURE", precision: "DATE_ONLY", captureStartedAt: null, captureEndedAt: null, captureDate: "2022-08-24" },
      captureSourcesAgree: true,
      versions: [{
        assetRef: "disp-2022b",
        submissionRef: "s2",
        revision: 1,
        artifactId: "art-2",
        kind: "dsm",
        lifecycleState: "SEALED",
        capture: { factClass: "DECLARED_CAPTURE", precision: "DATE_ONLY", captureStartedAt: null, captureEndedAt: null, captureDate: "2022-08-24" },
        declaredCrs: "EPSG:5186",
        declaredVerticalReferencePresent: false,
        declaredGsdM: null,
        submittedAt: "2022-08-25T00:00:00Z",
        observedSha256: null,
        observedSizeBytes: null,
        observedAt: null,
        inspectionState: "COMPLETED",
        inspectionOutcome: "MEASURED",
        inspectionReason: null,
        inspectedRasterAvailable: true,
        displayState: "SEALED",
        displayReady: false,
        chronology: "DATE_ONLY",
        chronologyCandidate: false,
        quantitativeEligibility: "NOT_EVALUATED",
        viewAssetRef: "disp-2022b",
        viewAvailable: false,
        viewUnavailableReason: "NO_DISPLAY_READY_VERSION",
      }],
      viewAvailable: false,
      viewUnavailableReason: "NO_DISPLAY_READY_VERSION",
      viewAssetRef: "disp-2022b",
      newerRevisionPending: false,
      newerRevisionState: null,
      chronologyCandidate: false,
      hasSealedVersion: true,
    }],
    entryDefault: {
      observationEpochId: "epoch-2021",
      viewAssetRef: "disp-2022",
      reason: "LATEST_EXACT_VIEW_AVAILABLE",
      detail: "Latest view-available observation by exact capture interval.",
      tiedObservationEpochIds: [],
    },
    nextCursor: null,
    hasMore: false,
  };
}

function preparedJobView() {
  const pixelWindow: [number, number, number, number] = [0, 100, 0, 100];
  return {
    jobId: "sdj-v1-00000000-0000-0000-000000000011",
    siteId: "site-1",
    workAreaId: "tiny-1",
    assetRef: "disp-2022",
    executionState: "COMPLETED",
    availability: "AVAILABLE",
    createdAt: "2026-10-21T00:00:00Z",
    receipt: {
      jobId: "sdj-v1-00000000-0000-0000-000000000011",
      receiptDigest: null,
      artifactKind: "dsm",
      outputSizeBytes: 30000,
      outputSha256: `sha256:${"a".repeat(64)}`,
      requestedBounds: [200000, 549010, 201000, 550010],
      actualBounds: [200000, 549010, 201000, 550010],
      pixelWindow,
      width: 100,
      height: 100,
      observedCrsIdentifier: "EPSG:5186",
      observedCrsDigest: "dd",
      accuracyAssessed: false,
      attribution: "attr",
      modificationNotice: "mod",
      limitations: [],
      preparedAt: "2026-10-21T00:00:00Z",
    },
  };
}

function analysisItem(analysisId: string, createdAt: string) {
  return {
    analysisId,
    siteId: "site-1",
    workAreaId: "tiny-1",
    executionState: "COMPLETED",
    suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED",
    createdAt,
    resultId: "res-1",
    metrics: { cutM3: 0, fillM3: 800, netM3: 800, thresholdM: 0, uncertaintyM3: null },
    limitationCount: 1,
    analysisHref: `/sites/site-1/analysis?analysisId=${analysisId}`,
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
  mocked.permissions.mockResolvedValue(true);
  mocked.areas.mockResolvedValue({ workAreas: [areaFixture("tiny-1", "미세 분석 구역")] });
  mocked.orders.mockResolvedValue([]);
  mocked.history.mockResolvedValue({ items: [], nextCursor: null });
  mocked.analyses.mockResolvedValue({ siteId: "site-1", items: [], nextCursor: null });
  mocked.detail.mockRejectedValue(new CoreApiError(404, { detail: "not found" }));
  mocked.assets.mockResolvedValue({
    contractVersion: "spatial-asset-catalog-page.v1",
    siteId: "site-1",
    workAreaId: "tiny-1",
    scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY",
    scopeNote: "",
    assets: [rasterAsset("disp-2022")],
    nextCursor: null,
    hasMore: false,
  });
  mocked.workspace.mockResolvedValue(workspaceReadyPage());
  mocked.prepared.mockResolvedValue({
    siteId: "site-1",
    workAreaId: "tiny-1",
    items: [preparedJobView()],
    nextCursor: null,
  });
});

async function renderOverview(searchParams: Record<string, string> = {}) {
  render(await SiteDetailPage({
    params: Promise.resolve({ siteId: "site-1" }),
    searchParams: Promise.resolve(searchParams),
  }));
}

describe("usability-first explore", () => {
  it("shows the actual canvas before the technical disclosure", async () => {
    await renderOverview({});
    const canvas = screen.getByRole("region", { name: "선택 관측 보기" });
    const detail = screen.getByText("자료·범위 상세").closest("details")!;
    expect(canvas.compareDocumentPosition(detail) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // 실제 화면 자리가 기술 벽보다 먼저다.
    const text = document.body.textContent ?? "";
    // 이어 보기와 이미 준비된 부분 보기 모두 실제 표시 경로다(canvas 무대 포함).
    const mosaic = text.includes("이어 보기 — 여러 창의 나란한 배치")
      ? text.indexOf("이어 보기 — 여러 창의 나란한 배치")
      : text.includes("준비된 일부 범위")
        ? text.indexOf("준비된 일부 범위")
        : text.indexOf("일부 범위");
    const conditions = text.indexOf("표시 조건·근거");
    expect(mosaic).toBeGreaterThanOrEqual(0);
    expect(conditions).toBeGreaterThan(mosaic);
  });

  it("switches capture from the first task bar with actual refs and precision", async () => {
    await renderOverview({});
    const select = screen.getByLabelText("관측 시점") as HTMLSelectElement;
    const options = Array.from(select.options).map((option) => option.textContent);
    // 실제 관측 선택지이며 날짜만 아는 정밀도 그대로 둔다.
    expect(options.some((text) => text?.includes("날짜만 확인"))).toBe(true);
    // 값은 정확한 assetRef이며, 선택 상태가 현재 선택을 가리킨다.
    expect(select.value).toBe("disp-2022");
    // 폼은 같은 GET 경로에 구역 범위를 함께 싣는다 — Back/새로고침이 의도를 살린다.
    const form = select.closest("form")!;
    expect(form.getAttribute("method")).toBe("get");
    expect(form.querySelector('input[name="workAreaId"]')).toBeTruthy();
    expect(form.querySelector('select[name="assetRef"]')).toBeTruthy();
  });

  it("keeps the compact header to one site name without a redundant label", async () => {
    await renderOverview({});
    expect(screen.getAllByRole("heading", { name: "현장 하나" })).toHaveLength(1);
    expect(screen.queryByText("현장명")).toBeNull();
    // 집중 모드 한 줄 머리 — 기본 머리의 펼침 대신 설정 메뉴를 둔다.
    expect(screen.getByText("설정·정보")).toBeTruthy();
    expect(screen.queryByText("현장 정보·범위")).toBeNull();
  });
});

describe("usability-first results", () => {
  it("leads with the latest record and folds older ones into history", async () => {
    mocked.analyses.mockResolvedValue({
      siteId: "site-1",
      items: [
        analysisItem("a3", "2026-10-14T00:00:00Z"),
        analysisItem("a2", "2026-10-13T00:00:00Z"),
        analysisItem("a1", "2026-10-12T00:00:00Z"),
      ],
      nextCursor: null,
    });
    await renderOverview({ mode: "results" });
    const filled = screen.getAllByText("성토")[0]!.closest("div");
    expect(filled?.textContent).toContain("800 m³");
    expect(screen.getAllByText(/정확도 평가는 아직 확인되지 않았습니다/)[0]).toBeTruthy();
    expect(screen.getByText("이전 기록 2건")).toBeTruthy();
    // 최신 기록의 근거 링크는 원래 선택자 그대로다.
    expect(screen.getAllByRole("link", { name: "자료·근거와 검토 보기" })[0]!.getAttribute("href")).toBe(
      "/sites/site-1/analysis?workAreaId=tiny-1&analysisId=a3",
    );
  });

  it("shows the lead record's actual comparison period from its original selectors", async () => {
    mocked.analyses.mockResolvedValue({
      siteId: "site-1",
      items: [analysisItem("a3", "2026-10-14T00:00:00Z")],
      nextCursor: null,
    });
    mocked.detail.mockResolvedValue({
      analysisId: "a3",
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
      createdAt: "2026-10-14T00:00:00Z",
    });
    await renderOverview({ mode: "results" });
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "a3");
    // 실제 포착 구간(10/6→10/13이 아니라 픽스처의 2021/2022)을 그대로 둔다.
    const text = document.body.textContent ?? "";
    expect(text).toContain("2021");
    expect(text).toContain("2022");
    expect(text).toContain("기준");
    expect(text).toContain("현재");
  });

  it("does not infer unevaluated accuracy from a null volume uncertainty", async () => {
    // EVALUATED + 불확도 null — "미확인"으로 읽으면 안 된다.
    mocked.analyses.mockResolvedValue({
      siteId: "site-1",
      items: [{
        ...analysisItem("a9", "2026-10-15T00:00:00Z"),
        suitabilityState: "EVALUATED",
        metrics: { cutM3: 0, fillM3: 800, netM3: 800, thresholdM: 0, uncertaintyM3: null },
      }],
      nextCursor: null,
    });
    await renderOverview({ mode: "results" });
    expect(screen.getByText(/분석 조건 확인 결과가 있습니다/)).toBeTruthy();
    expect(screen.queryByText(/정확도 평가는 아직 확인되지 않았습니다/)).toBeNull();
  });
});
