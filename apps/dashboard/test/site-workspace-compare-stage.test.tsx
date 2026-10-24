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
  it("puts each date select and layer control at its own pane with inline controls", () => {
    render(shell(shellProps()));
    const stage = screen.getByRole("region", { name: "두 시점 비교" });
    // 각 칸의 관측 선택은 그 칸 바로 위의 직접 GET 폼이다 — 큰 제출 벽을 두지 않는다.
    const selectA = within(stage).getByLabelText("관측 A 관측 선택") as HTMLSelectElement;
    const selectB = within(stage).getByLabelText("관측 B 관측 선택") as HTMLSelectElement;
    expect(selectA.value).toBe(REFA);
    expect(selectB.value).toBe(REFB);
    // 날짜 정밀도는 선택지에 그대로 둔다.
    expect(selectA.textContent).toContain("2021");
    // 폼마다 같은 구역·반대쪽 참조를 싣고, 제출하면 그 칸만 바뀐다.
    for (const [select, name, sibling] of [
      [selectA, "visualAAssetRef", "visualBAssetRef"],
      [selectB, "visualBAssetRef", "visualAAssetRef"],
    ] as const) {
      const form = select.closest("form")!;
      expect(form.method).toBe("get");
      expect(form.querySelector('input[name="mode"][value="compare"]')).toBeTruthy();
      expect(form.querySelector('input[name="workAreaId"][value="tiny-1"]')).toBeTruthy();
      expect(form.querySelector(`select[name="${name}"]`)).toBe(select);
      expect(form.querySelector(`input[name="${sibling}"]`)).toBeTruthy();
    }
    expect(within(stage).queryByRole("button", { name: "독립 보기로 나란히 두기" })).toBeNull();
    // 층 전환은 각 칸의 내장 제어로 그 칸에 붙는다 — 전역 포털 대상 없음.
    const layerGroups = within(stage).getAllByRole("group", { name: "자료 층 전환" });
    expect(layerGroups).toHaveLength(2);
    for (const group of layerGroups) {
      expect(group.getAttribute("data-workbench-pane-controls")).not.toBeNull();
      expect(group.closest("#workbench-catalog")).toBeNull();
    }
    expect(document.getElementById("workbench-catalog")).toBeNull();
    // 같은 사유 회복은 하나로 둔다 — 읽기 권한이 없어 두 칸이 함께 막혔다.
    expect(within(stage).getByText("이미 준비된 창을 볼 권한이 없습니다.")).toBeTruthy();
  });

  it("carries the opposite side exactly in each pane form, never its own ref", () => {
    render(shell(shellProps()));
    const stage = screen.getByRole("region", { name: "두 시점 비교" });
    // A 폼의 반대쪽 hidden은 B의 정확한 참조여야 한다 — A를 고르면 B가 바뀌면 안 된다.
    const formA = within(stage).getByLabelText("관측 A 관측 선택").closest("form")!;
    expect(formA.querySelector('select[name="visualAAssetRef"]')).toBeTruthy();
    expect(formA.querySelector('input[name="visualBAssetRef"]')?.getAttribute("value")).toBe(REFB);
    expect(formA.querySelector('input[name="visualAAssetRef"]')).toBeNull();
    // B 폼의 반대쪽 hidden은 A의 정확한 참조여야 한다.
    const formB = within(stage).getByLabelText("관측 B 관측 선택").closest("form")!;
    expect(formB.querySelector('select[name="visualBAssetRef"]')).toBeTruthy();
    expect(formB.querySelector('input[name="visualAAssetRef"]')?.getAttribute("value")).toBe(REFA);
    expect(formB.querySelector('input[name="visualBAssetRef"]')).toBeNull();
    // GET 제출 주소는 정확히 그 칸만 바꾼다.
    expect(formA.getAttribute("action")).toBe("/sites/site-1");
  });

  it("states the ready pair as two independent views without borrowing the materials mode name", () => {
    render(shell(shellProps()));
    // 작업공간 쌍 설명은 '나란히'(자료 화면 보기 방식 이름)를 쓰지 않는다.
    expect(screen.getByText(/독립된 두 보기로 둡니다/)).toBeTruthy();
    expect(screen.queryByText(/나란히 둡니다/)).toBeNull();
  });

  it("carries the opposite time-ordered side exactly in each pane form", () => {
    const props = shellProps({
      comparison: {
        status: "ready",
        workAreaId: "tiny-1",
        baseline: { observationEpochId: "epoch-a", workAreaId: "tiny-1", workOrderId: "w1", assetRef: "base-1", submissionRef: "s1", revision: 1, kind: "dsm", displayReady: true, inspectedRasterAvailable: true, chronologyCandidate: true, captureSourcesAgree: true, viewAvailable: true, viewUnavailableReason: null, viewAssetRef: "base-1", newerRevisionPending: false, newerRevisionState: null, captureStartedAt: "2021-08-17T10:00:00Z", captureEndedAt: "2021-08-17T11:00:00Z", captureDate: null },
        current: { observationEpochId: "epoch-b", workAreaId: "tiny-1", workOrderId: "w1", assetRef: "curr-1", submissionRef: "s1", revision: 1, kind: "dsm", displayReady: true, inspectedRasterAvailable: true, chronologyCandidate: true, captureSourcesAgree: true, viewAvailable: true, viewUnavailableReason: null, viewAssetRef: "curr-1", newerRevisionPending: false, newerRevisionState: null, captureStartedAt: "2022-08-24T10:00:00Z", captureEndedAt: "2022-08-24T11:00:00Z", captureDate: null },
      },
      baselineRequestedRef: "base-1",
      currentRequestedRef: "curr-1",
      visualPair: { status: "prompt" },
      visualARequestedRef: null,
      visualBRequestedRef: null,
    });
    render(shell(props));
    const stage = screen.getByRole("region", { name: "두 시점 비교" });
    const formBase = within(stage).getByLabelText("기준 자료 관측 선택").closest("form")!;
    expect(formBase.querySelector('input[name="currentAssetRef"]')?.getAttribute("value")).toBe("curr-1");
    expect(formBase.querySelector('input[name="baselineAssetRef"]')).toBeNull();
    const formCurr = within(stage).getByLabelText("비교 자료 관측 선택").closest("form")!;
    expect(formCurr.querySelector('input[name="baselineAssetRef"]')?.getAttribute("value")).toBe("base-1");
    expect(formCurr.querySelector('input[name="currentAssetRef"]')).toBeNull();
  });

  it("refuses an invalid side ref without substituting the other side", () => {
    render(shell(shellProps({ visualARequestedRef: "ghost-ref", visualPair: { status: "unresolvable", intent: "comparison", reason: "malformed", headline: "쌍을 확인하지 못했습니다", detail: "독립 보기 지시를 확인하세요." } })));
    const stage = screen.getByRole("region", { name: "두 시점 비교" });
    // 실패한 쪽 선택은 비어 있고(조용히 바꾸지 않음), 살아 있는 B는 그대로 싣는다.
    const selectA = within(stage).getByLabelText("관측 A 관측 선택") as HTMLSelectElement;
    expect(selectA.value).toBe("");
    const formA = selectA.closest("form")!;
    expect(formA.querySelector('input[name="visualBAssetRef"]')?.getAttribute("value")).toBe(REFB);
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("does not coalesce when an old expired record coexists with a newer available one", () => {
    const expired = (assetRef: string, jobId: string) => ({
      jobId, assetRef, executionState: "EXPIRED", availability: "RETENTION_EXPIRED",
      createdAt: "2026-10-21T00:00:00Z", receipt: null,
    });
    const available = (assetRef: string, jobId: string) => ({
      jobId, assetRef, executionState: "COMPLETED", availability: "AVAILABLE",
      createdAt: "2026-10-22T00:00:00Z", receipt: null,
    });
    // A에는 오래된 만료와 새 사용 가능본이 함께 있다 — 만료로 묶으면 유효 픽셀이 숨겨진다.
    render(shell(shellProps({
      canReadData: true, canRequestData: false,
      preparedJobs: [expired(REFA, "sdj-exp-a"), available(REFA, "sdj-av-a"), expired(REFB, "sdj-exp-b")],
    })));
    const stage = screen.getByRole("region", { name: "두 시점 비교" });
    // 같은 사유 묶음이 아니다 — 공유 바(둘 칸 한 줄)가 없다. 각 칸 뷰어가 그대로 마운트된다.
    expect(within(stage).queryByText(/두 칸의 불러온 준비 기록/)).toBeNull();
    expect(within(stage).getAllByLabelText(/임시 시각화 어댑터/)).toHaveLength(2);
    expect(within(stage).getByLabelText("관측 A 관측 선택")).toBeTruthy();
    expect(within(stage).getByLabelText("관측 B 관측 선택")).toBeTruthy();
  });

  it("keeps viewers when one side expired and the other only has an unreadable record", () => {
    const expired = (assetRef: string, jobId: string) => ({
      jobId, assetRef, executionState: "EXPIRED", availability: "RETENTION_EXPIRED",
      createdAt: "2026-10-21T00:00:00Z", receipt: null,
    });
    const pending = (assetRef: string, jobId: string) => ({
      jobId, assetRef, executionState: "RUNNING", availability: "NOT_READY",
      createdAt: "2026-10-22T00:00:00Z", receipt: null,
    });
    render(shell(shellProps({
      canReadData: true, canRequestData: false,
      preparedJobs: [expired(REFA, "sdj-exp-a"), pending(REFB, "sdj-run-b")],
    })));
    const stage = screen.getByRole("region", { name: "두 시점 비교" });
    expect(within(stage).queryByText(/두 칸의 불러온 준비 기록/)).toBeNull();
    // 각 칸 뷰어가 그대로 마운트된다 — 공유 바 없이 각자 자기 사유만 말한다.
    expect(within(stage).getAllByLabelText(/임시 시각화 어댑터/)).toHaveLength(2);
    expect(within(stage).getByLabelText("관측 A 관측 선택")).toBeTruthy();
    expect(within(stage).getByLabelText("관측 B 관측 선택")).toBeTruthy();
  });

  it("coalesces only when every known job for both sides expired", () => {
    const expired = (assetRef: string, jobId: string) => ({
      jobId, assetRef, executionState: "EXPIRED", availability: "RETENTION_EXPIRED",
      createdAt: "2026-10-21T00:00:00Z", receipt: null,
    });
    render(shell(shellProps({
      canReadData: true, canRequestData: false,
      preparedJobs: [expired(REFA, "sdj-exp-a"), expired(REFB, "sdj-exp-b")],
    })));
    const stage = screen.getByRole("region", { name: "두 시점 비교" });
    expect(within(stage).getAllByText(/두 칸의 불러온 준비 기록/)).toHaveLength(1);
    expect(within(stage).getAllByText(/미리보기 보관 기간이 끝났습니다/)).toHaveLength(1);
    // 뷰어는 접히고 헤드(관측 선택·층)만 남는다 — 같은 사유 회복 하나만 둔다.
    expect(within(stage).getByText("관측 A 관측 선택")).toBeTruthy();
    expect(within(stage).getByText("관측 B 관측 선택")).toBeTruthy();
    // 쌍 동작은 칸·회복보다 먼저 둔다 — 실패 무대를 스크롤해야 보이지 않는다.
    const markup = stage.innerHTML;
    expect(markup.indexOf("이 쌍으로 분석 조건 확인")).toBeGreaterThan(-1);
    expect(markup.indexOf("이 쌍으로 분석 조건 확인")).toBeLessThan(markup.indexOf("관측 A 관측 선택"));
    expect(markup.indexOf("이 쌍으로 분석 조건 확인")).toBeLessThan(markup.indexOf("미리보기 보관 기간이 끝났습니다"));
  });

  it("keeps the denied list state instead of an expired claim when the list itself is denied", () => {
    render(shell(shellProps({ jobsState: "denied" })));
    const stage = screen.getByRole("region", { name: "두 시점 비교" });
    expect(within(stage).getByText(/준비 기록을 조회할 권한이 없습니다/)).toBeTruthy();
    expect(within(stage).queryByText(/미리보기 보관 기간이 끝났습니다/)).toBeNull();
  });

  it("keeps the request entry once in the stage and folds pair conditions into info", () => {
    render(shell(shellProps()));
    // 무대에는 명시적 요청 진입 하나만 둔다.
    const ctas = screen.getAllByRole("link", { name: "이 쌍으로 분석 조건 확인" });
    expect(ctas).toHaveLength(1);
    expect(ctas[0]!.closest("details")).toBeNull();
    expect(ctas[0]!.getAttribute("href")).toBe("/sites/site-1/analysis?workAreaId=tiny-1");
    // 칸 카드·조건 펼침은 정보 서랍의 한 면에 둔다.
    expect(screen.queryByText("독립 보기 자료·조건 확인")).toBeNull();
    expect(screen.queryByText("비교 자료·조건 확인")).toBeNull();
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
