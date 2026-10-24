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
import { SiteExploreCanvas } from "@/app/sites/[siteId]/SiteExploreCanvas";
import { CoreApiError } from "@/lib/core-api/client";
import {
  DISPLAY_GESTURE_HINT,
  displayGestureKeyAction,
} from "@/lib/spatial-display-gesture";

const TINY_5186 = {
  type: "Polygon",
  coordinates: [[[200000, 549999.8], [200010, 549999.8], [200010, 550009.8], [200000, 549999.8]]],
};

function areaFixture(workAreaId: string, name: string, overrides: Record<string, unknown> = {}) {
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
    ...overrides,
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
    items: [],
    nextCursor: null,
  });
});

async function renderOverview(searchParams: Record<string, string> = {}) {
  render(await SiteDetailPage({
    params: Promise.resolve({ siteId: "site-1" }),
    searchParams: Promise.resolve(searchParams),
  }));
}

describe("explore declutter: primary action leads the side column", () => {
  it("puts the next-action nav first in the scope column with one primary button", async () => {
    // 고정 선택 레일을 접고 실제 화면을 먼저 둔다 — 다음 행동은 정보 서랍의
    // 한 면에 둔다. 옛 '자료·범위 상세' 펼침 벽은 두지 않는다.
    await renderOverview({});
    expect(screen.queryByRole("region", { name: "선택 관측 화면" })).toBeNull();
    expect(screen.getByRole("region", { name: "선택 관측 보기" })).toBeTruthy();
    expect(screen.queryByText("자료·범위 상세")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "정보" }));
    const nav = within(screen.getByRole("region", { name: "작업공간 정보" }))
      .getByRole("navigation", { name: "탐색 다음 행동" });
    const primary = nav.querySelector("a.btn-primary");
    expect(primary?.textContent).toContain("관측 자료 등록");
    expect(nav.querySelectorAll("a.btn-primary")).toHaveLength(1);
  });
});

describe("explore declutter: identity and three-area navigation stay reachable", () => {
  it("keeps one site-name heading and all three labelled areas", async () => {
    await renderOverview({});
    expect(screen.getAllByRole("heading", { name: "현장 하나" })).toHaveLength(1);
    expect(screen.queryByText("현장 정보·범위")).toBeNull();
    expect(screen.getByText("설정·정보")).toBeTruthy();
    const menu = screen.getByRole("navigation", { name: "현장 업무 메뉴" });
    const links = within(menu).getAllByRole("link");
    expect(links).toHaveLength(3);
    for (const label of ["작업공간", "자료", "결과"]) {
      expect(within(menu).getByRole("link", { name: label })).toBeTruthy();
    }
    expect(within(menu).getAllByRole("link", { current: "page" })).toHaveLength(1);
  });
});

describe("explore declutter: decision limits stay visible next to what they constrain", () => {
  it("keeps the footprint-mismatch notice outside any disclosure", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [areaFixture("tiny-1", "미세 분석 구역", { crs: "EPSG:9999" })] });
    await renderOverview({});
    // 정보 서랍의 한 면에서 한 번만 말한다 — 카드 안 펼침에 묻지 않는다.
    fireEvent.click(screen.getByRole("button", { name: "정보" }));
    const notice = within(screen.getByRole("region", { name: "작업공간 정보" }))
      .getByText("위치 기준이 맞지 않아 파일 범위를 겹쳐 표시하지 않았습니다.");
    expect(notice.closest("details")).toBeNull();
    expect(screen.queryByText("선택한 파일이 포함하는 범위를 함께 표시합니다.")).toBeNull();
  });
});

describe("explore declutter: technical identifiers live in disclosures", () => {
  it("keeps file and identifier facts present but only inside a disclosure", async () => {
    await renderOverview({});
    // 파일 사실은 무대가 아니라 오른쪽 정보 드로어에서만 둔다 — 드로어를 연다.
    const stage = screen.getByRole("region", { name: "선택 관측 보기" });
    for (const pattern of [/등록 파일명/, /자료 식별자/]) {
      expect(within(stage).queryByText(pattern)).toBeNull();
    }
    fireEvent.click(screen.getByRole("button", { name: "정보" }));
    const inspector = document.getElementById("workspace-inspector")!;
    for (const pattern of [/등록 파일명/, /자료 식별자/]) {
      const matches = within(inspector).getAllByText(pattern);
      expect(matches.length).toBeGreaterThan(0);
    }
    // 무대에서 옮겨온 뷰어 상세가 서랍 자리에서 펼침으로 살아 있다.
    // (식별자 원문은 정보 본문의 버전 펼침이, 등록 파일명은 옮겨온 표시 조건이 둔다.)
    const host = document.getElementById("workspace-inspector-details")!;
    expect(host.querySelectorAll("details").length).toBeGreaterThan(0);
    const inFolded = within(host).getAllByText(/등록 파일명/);
    expect(inFolded.length).toBeGreaterThan(0);
    for (const match of inFolded) expect(match.closest("details")).toBeTruthy();
  });
});

describe("explore declutter: failed reads stay failures, never empty", () => {
  it("says the catalog could not be read instead of claiming no materials", async () => {
    mocked.assets.mockRejectedValue(new CoreApiError(503, { detail: "unavailable" }));
    await renderOverview({});
    // 무대 1차 영역에 조회 실패를 둔다 — 빈 목록으로 단정하지 않는다.
    expect(screen.getByText(/등록 자료 목록을 불러오지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText("이 구역에 조회된 등록 자료가 없습니다.")).toBeNull();
  });
});

describe("explore declutter: selectors keep exact values and routes", () => {
  it("submits the same workAreaId and assetRef through the same GET path", () => {
    const areas = [
      areaFixture("w-1", "구역 가"),
      areaFixture("w-2", "구역 나"),
    ] as never;
    render(
      <SiteExploreCanvas
        sitePath="/sites/site-1"
        areas={areas}
        selectedWorkAreaId="w-1"
        captureOptions={[
          { assetRef: "a-1", label: "2021 포착", title: "t1", selected: true },
          { assetRef: "a-2", label: "2022 포착", title: "t2", selected: false },
        ]}
        selectedCaption="등록 버전 1"
        coverageNote={null}
      >
        <div>canvas</div>
      </SiteExploreCanvas>,
    );
    const areaSelect = screen.getByLabelText("작업구역") as HTMLSelectElement;
    expect(Array.from(areaSelect.options).map((o) => o.value)).toEqual(["w-1", "w-2"]);
    expect(areaSelect.closest("form")?.getAttribute("action")).toBe("/sites/site-1");
    expect(areaSelect.closest("form")?.getAttribute("method")).toBe("get");
    const captureSelect = screen.getByLabelText("관측 시점") as HTMLSelectElement;
    expect(Array.from(captureSelect.options).map((o) => o.value)).toEqual(["a-1", "a-2"]);
    expect(captureSelect.value).toBe("a-1");
    const captureForm = captureSelect.closest("form")!;
    expect(captureForm.getAttribute("action")).toBe("/sites/site-1");
    expect(captureForm.querySelector('input[name="workAreaId"]')?.getAttribute("value")).toBe("w-1");
  });
});

describe("explore declutter: no duplicated titles in the default view", () => {
  it("prints the site name and the explore mode once each", async () => {
    await renderOverview({});
    expect(screen.getAllByRole("heading", { name: "현장 하나" })).toHaveLength(1);
    expect(screen.getAllByText("설정·정보")).toHaveLength(1);
    const modeNav = screen.getByRole("navigation", { name: "보기 방식" });
    const labels = within(modeNav).getAllByRole("link").map((link) => link.textContent);
    expect(new Set(labels).size).toBe(labels.length);
  });
});

describe("explore declutter: gesture hint stays truthful", () => {
  it("describes only implemented gestures and keeps the display-only warning", () => {
    for (const fragment of ["끌어서", "휠", "두 손가락", "두 번 두드리기", "방향키", "Home", "측정값이 아닙니다"]) {
      expect(DISPLAY_GESTURE_HINT).toContain(fragment);
    }
    for (const absent of ["동기화", "정확도", "측량", "승인"]) {
      expect(DISPLAY_GESTURE_HINT).not.toContain(absent);
    }
    expect(displayGestureKeyAction("ArrowLeft")).not.toBeNull();
    expect(displayGestureKeyAction("Home")).not.toBeNull();
    expect(displayGestureKeyAction("+")).not.toBeNull();
    expect(displayGestureKeyAction("-")).not.toBeNull();
  });
});
