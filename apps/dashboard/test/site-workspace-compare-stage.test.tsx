/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: () => {} }) }));
vi.mock("@/components/map/AoiPolygonMap", () => ({
  AoiPolygonMap: ({ value }: { value: unknown }) => (
    <div data-testid="aoi-map" data-vertices={JSON.stringify(value)} />
  ),
}));

import { SiteWorkspaceShell } from "@/app/sites/[siteId]/SiteWorkspaceShell";

const REFA = `ksa-v1-${"a".repeat(64)}`;
const REFB = `ksa-v1-${"b".repeat(64)}`;

function fact(assetRef: string, epochId: string) {
  return {
    observationEpochId: epochId,
    workAreaId: "tiny-1",
    workOrderId: "w1",
    assetRef,
    submissionRef: "s1",
    revision: 1,
    kind: "dsm",
    captureStartedAt: "2021-08-17T10:00:00Z",
    captureEndedAt: "2021-08-17T11:00:00Z",
    captureDate: null,
    displayReady: false,
    inspectedRasterAvailable: true,
    chronologyCandidate: false,
    captureSourcesAgree: true,
    viewAvailable: true,
    viewUnavailableReason: null,
    viewAssetRef: assetRef,
    newerRevisionPending: false,
    newerRevisionState: null,
  };
}

function catalogItem(assetRef: string, epochId: string, kind = "dsm") {
  return {
    assetRef: kind === "dsm" ? assetRef : `${assetRef}-ortho`,
    siteId: "site-1",
    workAreaId: "tiny-1",
    workOrderId: "w1",
    observationEpochId: epochId,
    submissionRef: "s1",
    revision: 1,
    artifactId: "art-1",
    kind,
    lifecycleState: "SEALED",
    declared: {
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

const AREA = {
  schemaVersion: "1.0",
  siteId: "site-1",
  workAreaId: "tiny-1",
  name: "미세 분석 구역",
  polygon: null,
  crs: "",
  status: "ACTIVE",
  supersedes: null,
  createdAt: "2026-10-10T00:00:00Z",
};

const NO_ENTRY = {
  status: "no-server-default",
  reason: "NO_OBSERVATIONS",
  detail: null,
  tiedObservationEpochIds: [],
  defaultNotOnPage: false,
} as const;

function shellProps(overrides: Record<string, unknown> = {}) {
  const factA = fact(REFA, "epoch-a");
  const factB = fact(REFB, "epoch-b");
  return {
    sitePath: "/sites/site-1",
    mode: "compare",
    areas: [AREA],
    areasKnown: true,
    orders: [],
    analyses: [],
    analysesKnown: true,
    analysesHasMore: false,
    legacy: [],
    legacyHasMore: false,
    assetsState: {
      status: "ready",
      page: {
        contractVersion: "spatial-asset-catalog-page.v1",
        siteId: "site-1",
        workAreaId: "tiny-1",
        scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY",
        scopeNote: "",
        assets: [
          catalogItem(REFA, "epoch-a", "dsm"),
          catalogItem(REFA, "epoch-a", "ortho"),
          catalogItem(REFB, "epoch-b", "dsm"),
          catalogItem(REFB, "epoch-b", "ortho"),
        ],
        nextCursor: null,
        hasMore: false,
      },
    },
    selectedWorkAreaId: "tiny-1",
    selectedAssetRef: null,
    canCreateWorkOrder: false,
    canCreateAnalysis: false,
    scopeNotice: false,
    facts: {
      siteId: "site-1",
      authorizedWorkAreaIds: ["tiny-1"],
      entryDefault: null,
      observations: [factA, factB],
      analyses: [],
    },
    ordinaryEntry: NO_ENTRY,
    projectionState: "ready",
    workspaceHasMore: false,
    transitionalSelection: false,
    baselineRequestedRef: null,
    currentRequestedRef: null,
    comparison: { status: "prompt" },
    visualARequestedRef: REFA,
    visualBRequestedRef: REFB,
    visualPair: {
      status: "ready",
      basis: "explicit-visual",
      workAreaId: "tiny-1",
      sideA: factA,
      sideB: factB,
    },
    explicitResult: null,
    explicitDetail: null,
    leadDetail: null,
    scopedCompareHref: "/sites/site-1/analysis?workAreaId=tiny-1",
    preparedJobs: [],
    jobsState: "ready",
    canReadData: false,
    canRequestData: false,
    ...overrides,
  } as unknown as Parameters<typeof SiteWorkspaceShell>[0];
}

function shell(props: Parameters<typeof SiteWorkspaceShell>[0]) {
  return <SiteWorkspaceShell {...props} />;
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("compare stage pair controls", () => {
  it("puts each layer row and date caption at its own pane with inline controls", () => {
    render(shell(shellProps()));
    const stage = screen.getByRole("region", { name: "두 시점 비교" });
    // 각 칸의 날짜·버전 표식은 그 칸 바로 위에 있으며, 드로어 기준선에 든다.
    const captions = [
      ...within(stage).getAllByText(/^관측 A ·/),
      ...within(stage).getAllByText(/^관측 B ·/),
    ];
    expect(captions).toHaveLength(2);
    for (const caption of captions) {
      expect(caption.textContent).toContain("등록 버전 1");
      expect(caption.closest("[data-workbench-pane-controls]")).toBeTruthy();
    }
    // 층 전환은 각 칸의 내장 제어로 그 칸에 붙는다 — 전역 포털 대상 없음.
    const layerGroups = within(stage).getAllByRole("group", { name: "자료 층 전환" });
    expect(layerGroups).toHaveLength(2);
    for (const group of layerGroups) {
      expect(group.getAttribute("data-workbench-pane-controls")).not.toBeNull();
      expect(group.closest("#workbench-catalog")).toBeNull();
    }
    expect(document.getElementById("workbench-catalog")).toBeNull();
  });

  it("folds the ready visual pair into a disclosure and keeps the CTA once", () => {
    render(shell(shellProps()));
    const folded = screen.getByText("독립 보기 자료·조건 확인").closest("details")!;
    expect(folded).toBeTruthy();
    // 바깥 진입 하나 + 접힌 안의 기존 안내 — 새로 늘리지 않는다.
    const ctas = screen.getAllByRole("link", { name: "이 쌍으로 분석 조건 확인" });
    expect(ctas).toHaveLength(2);
    expect(ctas[0]!.closest("details")).toBeNull();
    expect(ctas[1]!.closest("details")).toBe(folded);
    // 임계 고지는 접히지 않은 채 무대에 남는다(픽셀 비교 한 줄).
    expect(screen.getByText(/각 칸은 독립된 보기입니다/)).toBeTruthy();
  });

  it("keeps an unresolvable visual pair visible instead of folding it", () => {
    render(shell(shellProps({
      visualPair: {
        status: "unresolvable",
        intent: "comparison",
        reason: "malformed",
        headline: "쌍을 확인하지 못했습니다",
        detail: "독립 보기 지시를 확인하세요.",
      },
    })));
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("쌍을 확인하지 못했습니다");
    expect(alert.closest("details")).toBeNull();
    expect(screen.queryByText("독립 보기 자료·조건 확인")).toBeNull();
  });

  it("shows the scope fallback banner in the stage without opening the catalog", () => {
    render(shell(shellProps({ scopeNotice: true })));
    const stage = screen.getByRole("region", { name: "두 시점 비교" });
    const banner = within(stage).getByText(/요청한 구역·자료가 조회 범위에 없어/);
    expect(banner.textContent).toContain("작업구역 · 미세 분석 구역");
    expect(banner.closest('[role="status"]')).toBeTruthy();
    expect(document.getElementById("workbench-catalog")).toBeNull();
  });
});

describe("explore empty state", () => {
  function exploreProps(overrides: Record<string, unknown> = {}) {
    return shellProps({
      mode: "explore",
      assetsState: {
        status: "ready",
        page: {
          contractVersion: "spatial-asset-catalog-page.v1",
          siteId: "site-1",
          workAreaId: "tiny-1",
          scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY",
          scopeNote: "",
          assets: [],
          nextCursor: null,
          hasMore: false,
        },
      },
      facts: {
        siteId: "site-1",
        authorizedWorkAreaIds: ["tiny-1"],
        entryDefault: null,
        observations: [],
        analyses: [],
      },
      visualPair: { status: "prompt" },
      visualARequestedRef: null,
      visualBRequestedRef: null,
      canCreateWorkOrder: true,
      ...overrides,
    });
  }

  it("puts the explicit register path in the main stage for a true empty area", () => {
    render(shell(exploreProps()));
    const stage = screen.getByRole("region", { name: "선택 관측 보기" });
    expect(within(stage).getByText("이 구역에 확인할 관측이 없습니다")).toBeTruthy();
    const navs = within(stage).getAllByRole("navigation", { name: "탐색 다음 행동" });
    expect(navs).toHaveLength(1);
    const primary = within(navs[0]!).getByRole("link", { name: "관측 자료 등록" });
    expect(primary.getAttribute("href")).toBe("/sites/site-1/observations/new?workAreaId=tiny-1");
    expect(primary.className).toContain("btn-primary");
  });

  it("does not show an empty register path when the list is denied", () => {
    render(shell(exploreProps({
      projectionState: "denied",
      jobsState: "denied",
      ordinaryEntry: { ...NO_ENTRY, reason: "NO_PROJECTION" },
    })));
    expect(screen.queryByText("이 구역에 확인할 관측이 없습니다")).toBeNull();
    expect(screen.getByText(/준비 기록을 조회할 권한이 없습니다/)).toBeTruthy();
  });

  it("shows the catalog permission reason before the generic no-layer copy", () => {
    render(shell(exploreProps({
      assetsState: { status: "denied" },
      ordinaryEntry: { ...NO_ENTRY, reason: "NO_PROJECTION" },
    })));
    const stage = screen.getByRole("region", { name: "선택 관측 보기" });
    expect(within(stage).getByText(/등록 자료 목록을 조회할 권한이 없습니다/)).toBeTruthy();
    expect(within(stage).queryByText(/이 관측에서 화면에 둘 정사영상/)).toBeNull();
    expect(screen.queryByText("이 구역에 확인할 관측이 없습니다")).toBeNull();
  });

  it("shows the catalog refetch state before the generic no-layer copy", () => {
    render(shell(exploreProps({
      assetsState: { status: "unavailable" },
      ordinaryEntry: { ...NO_ENTRY, reason: "NO_PROJECTION" },
    })));
    const stage = screen.getByRole("region", { name: "선택 관측 보기" });
    expect(within(stage).getByText(/등록 자료 목록을 불러오지 못했습니다/)).toBeTruthy();
    expect(within(stage).queryByText(/이 관측에서 화면에 둘 정사영상/)).toBeNull();
    expect(screen.queryByText("이 구역에 확인할 관측이 없습니다")).toBeNull();
  });

  it("does not show an empty register path when the list is unavailable", () => {
    render(shell(exploreProps({
      projectionState: "unavailable",
      jobsState: "unavailable",
      ordinaryEntry: { ...NO_ENTRY, reason: "NO_PROJECTION" },
    })));
    expect(screen.queryByText("이 구역에 확인할 관측이 없습니다")).toBeNull();
    expect(screen.getByText(/준비 기록을 불러오지 못했습니다/)).toBeTruthy();
  });
});
