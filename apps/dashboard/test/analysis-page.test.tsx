/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ session: vi.fn(), site: vi.fn(), areas: vi.fn(), observations: vi.fn(), workOrders: vi.fn(), list: vi.fn(), detail: vi.fn(), asset: vi.fn() }));
vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/spatial-assets", () => ({ getSpatialAsset: mocked.asset }));
vi.mock("@/lib/core-api/analysis", () => ({ listAnalysisObservations: mocked.observations, listAnalyses: mocked.list, getAnalysis: mocked.detail }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ listObservationWorkOrders: mocked.workOrders }));
vi.mock("@/app/sites/[siteId]/analysis/AnalysisRequestPanel", () => ({ AnalysisRequestPanel: ({ initialPage, initialAnalysisId, initialSelectedDetail, observations, unattributedObservationCount, workOrderNames, initialWorkAreaId, scopeNotice, ...extra }: { initialPage: { items: Array<{ analysisId: string }> }; initialAnalysisId: string; initialSelectedDetail: { analysisId: string } | null; observations: Array<{ observationEpochId: string; workAreaIds: string[] }>; unattributedObservationCount: number; workOrderNames: Record<string, string>; initialWorkAreaId?: string; scopeNotice?: string | null; [key: string]: unknown }) => <><p>{`${initialAnalysisId}:${initialSelectedDetail?.analysisId ?? "none"}:${initialPage.items.map((item) => item.analysisId).join(",")}`}</p><p data-testid="panel-attribution">{`${observations.map((item) => `${item.observationEpochId}:${item.workAreaIds.join(",")}`).join(";")}|unknown:${unattributedObservationCount}`}</p><p data-testid="panel-work-names">{Object.entries(workOrderNames ?? {}).map(([id, name]) => `${id}=${name}`).join(";")}</p><p data-testid="panel-scope">{`${initialWorkAreaId ?? ""}|${scopeNotice ?? ""}`}</p><p data-testid="panel-exact">{JSON.stringify(extra)}</p></> }));
vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
  useRouter: () => ({ refresh: vi.fn() }),
}));

import SiteAnalysisPage from "@/app/sites/[siteId]/analysis/page";
import { CoreApiError } from "@/lib/core-api/client";

afterEach(() => { cleanup(); vi.resetAllMocks(); });

beforeEach(() => {
  mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ"] } });
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "접근 확인된 현장", status: "BASELINE_MAPPING", aoi: null, resumeTarget: null, siteFrame: { crs: "EPSG:5186", transformVersion: "v1" }, registeredAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z" });
  mocked.areas.mockResolvedValue({ workAreas: [] });
  mocked.observations.mockResolvedValue([]);
  mocked.workOrders.mockResolvedValue([]);
  mocked.list.mockResolvedValue({ siteId: "site-1", items: [], nextCursor: null });
  mocked.detail.mockResolvedValue(null);
  mocked.asset.mockResolvedValue(null);
});

describe("analysis deep link", () => {
  it("loads a V2 detail by ID when it is outside the first list page", async () => {
    mocked.list.mockResolvedValue({ siteId: "site-1", items: [{ analysisId: "analysis-recent" }], nextCursor: "cursor" });
    mocked.detail.mockResolvedValue({ analysisId: "analysis-old" });
    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({ analysisId: "analysis-old" }) }));
    expect(mocked.list).toHaveBeenCalledWith("site-1", { limit: 50 });
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "analysis-old");
    expect(screen.getByText("analysis-old:analysis-old:analysis-recent")).toBeTruthy();
  });

  it("shows start guidance from exact loaded records while no analysis exists yet", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [
      { workAreaId: "area-1", name: "1구역" },
      { workAreaId: "area-2", name: "2구역" },
    ] });
    mocked.observations.mockResolvedValue([
      { selector: { workOrderId: "work-1", submissionRef: `ers-v1-${"a".repeat(64)}`, revision: 1 }, observationEpochId: "epoch-1", captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z" },
      { selector: { workOrderId: "work-2", submissionRef: `ers-v1-${"b".repeat(64)}`, revision: 2 }, observationEpochId: "epoch-2", captureStartedAt: "2026-09-08T00:00:00Z", captureEndedAt: "2026-09-08T00:30:00Z" },
    ]);
    mocked.workOrders.mockResolvedValue([
      { workOrderId: "work-1", siteId: "site-1", organizationId: "org-1", workAreaIds: ["area-1"] },
      { workOrderId: "work-2", siteId: "site-1", organizationId: "org-1", workAreaIds: ["area-2"] },
    ]);
    mocked.list.mockResolvedValue({ siteId: "site-1", items: [], nextCursor: null });

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({}) }));

    // 후보·구역이 있어 실제 선택이 먼저이므로 안내는 접힌 도움말로 둔다.
    const summary = screen.getByText("변화 분석 시작 안내");
    expect(summary.closest("details")?.hasAttribute("open")).toBe(false);
    expect(screen.getByText("2개 확인됨")).toBeTruthy();
    expect(screen.getByText("2개 표시됨")).toBeTruthy();
    expect(screen.getByText("표시된 기록 없음")).toBeTruthy();
    expect(screen.getByText(/등록은 검증이나 정량 사용 가능 판정이 아닙니다/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/분석 준비 완료|분석 가능/);
  });

  it("omits start guidance once analyses exist so results lead", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "1구역" }] });
    mocked.observations.mockResolvedValue([
      { selector: { workOrderId: "work-1", submissionRef: `ers-v1-${"a".repeat(64)}`, revision: 1 }, observationEpochId: "epoch-1", captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z" },
    ]);
    mocked.workOrders.mockResolvedValue([
      { workOrderId: "work-1", siteId: "site-1", organizationId: "org-1", workAreaIds: ["area-1"] },
    ]);
    mocked.list.mockResolvedValue({ siteId: "site-1", items: [{ analysisId: "analysis-1" }], nextCursor: null });

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({}) }));

    expect(screen.queryByRole("heading", { name: "변화 분석 시작 안내" })).toBeNull();
  });

  it("passes only Site-verified WorkArea attribution to the analysis selector and counts unknown links", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "1구역" }] });
    mocked.observations.mockResolvedValue([
      { selector: { workOrderId: "work-1", submissionRef: `ers-v1-${"a".repeat(64)}`, revision: 1 }, observationEpochId: "epoch-known", captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z" },
      { selector: { workOrderId: "work-missing", submissionRef: `ers-v1-${"b".repeat(64)}`, revision: 1 }, observationEpochId: "epoch-unknown", captureStartedAt: "2026-09-08T00:00:00Z", captureEndedAt: "2026-09-08T00:30:00Z" },
    ]);
    mocked.workOrders.mockResolvedValue([{ workOrderId: "work-1", siteId: "site-1", organizationId: "org-1", workAreaIds: ["area-1"] }]);

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({}) }));

    expect(screen.getByTestId("panel-attribution").textContent).toBe("epoch-known:area-1|unknown:1");
    expect(screen.getByText("1개 표시됨")).toBeTruthy();
  });

  it("does not treat a mismatched WorkOrder scope as a WorkArea attribution", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "1구역" }] });
    mocked.observations.mockResolvedValue([
      { selector: { workOrderId: "work-1", submissionRef: `ers-v1-${"a".repeat(64)}`, revision: 1 }, observationEpochId: "epoch-1", captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z" },
    ]);
    mocked.workOrders.mockResolvedValue([{ workOrderId: "work-1", siteId: "another-site", organizationId: "org-1", workAreaIds: ["area-1"] }]);

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({}) }));

    expect(screen.getByTestId("panel-attribution").textContent).toBe("|unknown:1");
  });

  it("passes only Site-verified WorkOrder names for display and keeps missing names honest", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "1구역" }] });
    mocked.observations.mockResolvedValue([
      { selector: { workOrderId: "work-1", submissionRef: `ers-v1-${"a".repeat(64)}`, revision: 1 }, observationEpochId: "epoch-1", captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z" },
    ]);
    mocked.workOrders.mockResolvedValue([
      { workOrderId: "work-1", siteId: "site-1", organizationId: "org-1", name: "북측 1차 관측", workAreaIds: ["area-1"] },
      { workOrderId: "work-foreign", siteId: "another-site", organizationId: "org-1", name: "다른 현장 작업", workAreaIds: ["area-1"] },
      { workOrderId: "work-other-org", siteId: "site-1", organizationId: "org-2", name: "다른 조직 작업", workAreaIds: ["area-1"] },
    ]);

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({}) }));

    expect(screen.getByTestId("panel-work-names").textContent).toBe("work-1=북측 1차 관측");
  });

  it("keeps accessible Site context when an optional analysis child returns 404", async () => {
    const calls: string[] = [];
    mocked.site.mockImplementation(async () => { calls.push("site"); return { siteId: "site-1", name: "접근 확인된 현장", status: "BASELINE_MAPPING", aoi: null, resumeTarget: null, siteFrame: { crs: "EPSG:5186", transformVersion: "v1" }, registeredAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z" }; });
    mocked.areas.mockImplementation(async () => { calls.push("areas"); return { workAreas: [] }; });
    mocked.observations.mockImplementation(async () => { calls.push("observations"); throw new CoreApiError(404, { detail: "route unavailable" }); });
    mocked.list.mockImplementation(async () => { calls.push("analyses"); return { siteId: "site-1", items: [], nextCursor: null }; });

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({}) }));

    expect(calls[0]).toBe("site");
    expect(screen.getAllByText("접근 확인된 현장").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { level: 2, name: "현장 변화 분석" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toMatch(/현장 변화 분석/);
    expect(screen.queryByText(/0건|분석 결과/)).toBeNull();
    expect(screen.queryByText(/현장을 찾을 수 없습니다/)).toBeNull();
  });

  it("does not query analysis children or disclose Site context before an inaccessible Site 404", async () => {
    mocked.site.mockRejectedValue(new CoreApiError(404, { detail: "unknown site" }));

    await expect(SiteAnalysisPage({ params: Promise.resolve({ siteId: "foreign-site" }), searchParams: Promise.resolve({}) }))
      .rejects.toThrow("NEXT_NOT_FOUND");

    expect(mocked.areas).not.toHaveBeenCalled();
    expect(mocked.observations).not.toHaveBeenCalled();
    expect(mocked.list).not.toHaveBeenCalled();
    expect(screen.queryByText("접근 확인된 현장")).toBeNull();
  });

  it("shows a retry for transient child failures without inventing an empty result", async () => {
    mocked.list.mockRejectedValue(new CoreApiError(503, { detail: "temporarily unavailable" }, 4));

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({}) }));

    expect(screen.getAllByText("접근 확인된 현장").length).toBeGreaterThan(0);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: /다시 시도/ })).toBeTruthy();
    expect(screen.queryByText(/0건|분석 결과/)).toBeNull();
  });

  it("explains the next step for a denied analysis read without offering a retry", async () => {
    mocked.list.mockRejectedValue(new CoreApiError(403, { detail: "denied" }));

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({}) }));

    expect(screen.getByRole("alert").textContent).toContain("현장 담당자에게 변화 분석 기록 조회 권한을 요청하세요.");
    expect(screen.queryByRole("button", { name: /다시 시도/ })).toBeNull();
    expect(screen.queryByText(/0건|분석 결과/)).toBeNull();
  });

  it("preselects the single ACTIVE area without an explicit query", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "1구역", status: "ACTIVE" }] });

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({}) }));

    expect(screen.getByTestId("panel-scope").textContent).toBe("area-1|선택한 구역에서 시작합니다. 범위가 맞는지 확인하고 필요하면 바꾸세요.");
  });

  it("keeps the scope empty with several ACTIVE areas instead of guessing one", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [
      { workAreaId: "area-1", name: "1구역", status: "ACTIVE" },
      { workAreaId: "area-2", name: "2구역", status: "ACTIVE" },
    ] });

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({}) }));

    expect(screen.getByTestId("panel-scope").textContent).toBe("|");
  });

  it("offers same-area return links when analysis is environmentally unavailable without asserting file validity", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "1구역", status: "ACTIVE" }] });
    mocked.observations.mockRejectedValueOnce(new CoreApiError(404, { detail: "route unavailable" }));

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({ workAreaId: "area-1" }) }));

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("이 환경에서는 현장 변화 분석 기능을 사용할 수 없습니다.");
    expect(alert.textContent).toContain("등록 자료 자체의 문제가 아닙니다.");
    expect(screen.getByRole("link", { name: "등록 자료 보기" }).getAttribute("href")).toBe("/sites/site-1/spatial-assets?workAreaId=area-1");
    expect(screen.getByRole("link", { name: "현장 현황 보기" }).getAttribute("href")).toBe("/sites/site-1?workAreaId=area-1");
    expect(document.body.textContent).not.toMatch(/유효|사용 가능|적합/);
  });

  it("does not call a missing deep-linked record an unavailable analysis environment", async () => {
    mocked.detail.mockRejectedValueOnce(new CoreApiError(404, { detail: "not found" }));
    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({ analysisId: "analysis-missing", workAreaId: "area-1" }) }));
    expect(screen.getByRole("alert").textContent).toContain("선택한 분석 기록을 찾을 수 없거나 접근할 수 없습니다.");
    expect(screen.queryByText(/이 환경에서는 현장 변화 분석 기능을 사용할 수 없습니다/)).toBeNull();
    expect(screen.getByRole("link", { name: "분석 목록 보기" }).getAttribute("href")).toBe("/sites/site-1/analysis?workAreaId=area-1");
  });

  it("keeps return links scopeless for a blank or multi-valued area hint instead of echoing it", async () => {
    mocked.observations.mockRejectedValueOnce(new CoreApiError(404, { detail: "route unavailable" }));

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({ workAreaId: "   " }) }));

    expect(screen.getByRole("link", { name: "등록 자료 보기" }).getAttribute("href")).toBe("/sites/site-1/spatial-assets");
    expect(screen.getByRole("link", { name: "현장 현황 보기" }).getAttribute("href")).toBe("/sites/site-1");

    cleanup();

    mocked.observations.mockRejectedValueOnce(new CoreApiError(404, { detail: "route unavailable" }));

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({ workAreaId: ["area-1", "area-2"] }) }));

    expect(screen.getByRole("link", { name: "등록 자료 보기" }).getAttribute("href")).toBe("/sites/site-1/spatial-assets");
    expect(screen.getByRole("link", { name: "현장 현황 보기" }).getAttribute("href")).toBe("/sites/site-1");
  });
});

describe("browse source return scope", () => {
  it("keeps a browse assetRef as header-only return context without changing analysis selection", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "1구역", status: "ACTIVE" }] });

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({ workAreaId: "area-1" }) }));
    const plainScope = screen.getByTestId("panel-scope").textContent;
    const [plainHome] = screen.getAllByRole("link", { name: "작업공간" });
    expect(plainHome?.getAttribute("href")).toBe("/sites/site-1?workAreaId=area-1");
    cleanup();

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({ workAreaId: "area-1", assetRef: "browse-asset-1" }) }));
    // 분석 선택은 그대로 — assetRef는 분석 선택자(analysisId·currentWorkOrderId)가 아니다.
    expect(screen.getByTestId("panel-scope").textContent).toBe(plainScope);
    // 헤더 복귀 링크에는 탐색 출처(구역·관측)가 그대로 실린다.
    expect(screen.getAllByRole("link", { name: "작업공간" })[0]?.getAttribute("href")).toBe(
      "/sites/site-1?workAreaId=area-1&assetRef=browse-asset-1",
    );
    expect(screen.getAllByRole("link", { name: "자료" })[0]?.getAttribute("href")).toBe(
      "/sites/site-1/spatial-assets?workAreaId=area-1&assetRef=browse-asset-1",
    );
  });

  it("drops a browse assetRef outside the validated work area", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "1구역", status: "ACTIVE" }] });

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({ workAreaId: "ghost-area", assetRef: "browse-asset-1" }) }));

    expect(screen.getByTestId("panel-scope").textContent?.startsWith("|")).toBe(true);
    expect(screen.getAllByRole("link", { name: "작업공간" })[0]?.getAttribute("href")).toBe("/sites/site-1");
    expect(screen.getAllByRole("link", { name: "자료" })[0]?.getAttribute("href")).toBe("/sites/site-1/spatial-assets");
  });
});


describe("routed independent-pair analysis handoff", () => {
  const a = `ksa-v1-${"a".repeat(64)}`, b = `ksa-v1-${"b".repeat(64)}`;
  const sa = `ers-v1-${"a".repeat(64)}`, sb = `ers-v1-${"b".repeat(64)}`;
  const base = { workOrderId: "work-a", submissionRef: sa, revision: 1 };
  const current = { workOrderId: "work-b", submissionRef: sb, revision: 2 };
  const hints = { hintBaselineWorkOrderId: "work-a", hintBaselineSubmissionRef: sa, hintBaselineRevision: "1",
    hintCurrentWorkOrderId: "work-b", hintCurrentSubmissionRef: sb, hintCurrentRevision: "2" };
  function setupPair() {
    mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "북측", status: "ACTIVE" }] });
    mocked.observations.mockResolvedValue([
      { selector: base, observationEpochId: "epoch-a", captureStartedAt: "2026-10-06T00:00:00Z", captureEndedAt: "2026-10-06T01:00:00Z" },
      { selector: current, observationEpochId: "epoch-b", captureStartedAt: "2026-10-13T00:00:00Z", captureEndedAt: "2026-10-13T01:00:00Z" },
    ]);
    mocked.workOrders.mockResolvedValue(["work-a", "work-b"].map((workOrderId) => ({ workOrderId, siteId: "site-1", organizationId: "org-1", workAreaIds: ["area-1"] })));
    const assetByRef: Record<string, unknown> = Object.fromEntries([a, b].map((assetRef, index) => [assetRef, {
      assetRef, siteId: "site-1", workAreaId: "area-1",
      workOrderId: index === 0 ? "work-a" : "work-b",
      observationEpochId: index === 0 ? "epoch-a" : "epoch-b",
      submissionRef: index === 0 ? sa : sb, revision: index === 0 ? 1 : 2,
      kind: "dsm",
      declared: { fileName: `tile-${index}.tif`, captureStartedAt: "2026-10-06T00:00:00Z", captureEndedAt: "2026-10-06T01:00:00Z", captureDate: null },
      inspection: { outcome: "MEASURED", raster: { observedVerticalReference: { identifier: "KNGEO2002", basis: "geoid" } } },
    }]));
    mocked.asset.mockImplementation(async (_siteId: string, _workAreaId: string, assetRef: string) => assetByRef[assetRef] ?? null);
  }
  const panelProps = () => JSON.parse(screen.getByTestId("panel-exact").textContent!);
  it("does not create a missing-hint warning or extra catalogue request on an ordinary visit", async () => {
    setupPair();
    render(await SiteAnalysisPage({ params: Promise.resolve({siteId:"site-1"}), searchParams: Promise.resolve({workAreaId:"area-1"}) }));
    expect(panelProps().exactHintNotice).toBeNull();
    expect(panelProps().initialBaselineSelector).toBeNull();
    expect(mocked.asset).not.toHaveBeenCalled();
  });
  it("validates exact draft selectors and the separate return pair at the receiving route", async () => {
    setupPair();
    render(await SiteAnalysisPage({ params: Promise.resolve({siteId:"site-1"}), searchParams: Promise.resolve({workAreaId:"area-1", visualAAssetRef:a, visualBAssetRef:b, ...hints}) }));
    const props = panelProps();
    expect(props.initialBaselineSelector).toEqual(base);
    expect(props.initialCurrentSelector).toEqual(current);
    expect(props.exactHintNotice).toBeNull();
    expect(props.visualContext).toEqual({workAreaId:"area-1",visualAAssetRef:a,visualBAssetRef:b});
    expect(props.visualReturnHref).toContain(`visualAAssetRef=${a}`);
    // 정확한 참조 조회로 바인딩하므로 목록 페이지와 무관하게 풀린다.
    expect(mocked.asset).toHaveBeenCalledWith("site-1", "area-1", a);
    expect(mocked.asset).toHaveBeenCalledWith("site-1", "area-1", b);
    // 바인딩된 시각 쌍은 카탈로그 사실로도 풀어 읽기 전용 확인에 싣는다.
    expect(props.catalogPair.workAreaId).toBe("area-1");
    expect(props.catalogPair.a.selector).toEqual(base);
    expect(props.catalogPair.b.selector).toEqual(current);
    expect(props.catalogPair.a.assetRef).toBe(a);
    expect(props.catalogPair.b.assetRef).toBe(b);
  });
  it("rejects repeated exact hints and never falls back to a WorkOrder approximation", async () => {
    setupPair();
    render(await SiteAnalysisPage({ params: Promise.resolve({siteId:"site-1"}), searchParams: Promise.resolve({workAreaId:"area-1", ...hints, hintBaselineRevision:["1","2"], currentWorkOrderId:"work-b"}) }));
    const props = panelProps();
    expect(props.initialBaselineSelector).toBeNull();
    expect(props.initialCurrentSelector).toBeNull();
    expect(props.initialCurrentWorkOrderId).toBeNull();
    expect(props.exactHintNotice).toContain("직접 선택");
  });
  it("drops return context when the exact lookup contradicts its scope", async () => {
    setupPair();
    mocked.asset.mockImplementation(async (_siteId: string, _workAreaId: string, assetRef: string) => ({
      assetRef, siteId: "other-site", workAreaId: "area-1",
      workOrderId: "work-a", observationEpochId: "epoch-a",
      submissionRef: sa, revision: 1, kind: "dsm",
      declared: { fileName: "tile-0.tif", captureStartedAt: "2026-10-06T00:00:00Z", captureEndedAt: "2026-10-06T01:00:00Z", captureDate: null },
      inspection: { outcome: "MEASURED", raster: null },
    }));
    render(await SiteAnalysisPage({ params: Promise.resolve({siteId:"site-1"}), searchParams: Promise.resolve({workAreaId:"area-1",visualAAssetRef:a,visualBAssetRef:b}) }));
    expect(panelProps().visualContext).toBeNull();
    expect(panelProps().visualReturnHref).toBeNull();
    expect(panelProps().visualContextNotice).toContain("확인하지 못");
  });
  it("passes an unmatched browsed pair to the panel as display context, not a blank form", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "북측", status: "ACTIVE" }] });
    mocked.observations.mockResolvedValue([]);
    mocked.workOrders.mockResolvedValue([]);
    mocked.asset.mockImplementation(async (_siteId: string, _workAreaId: string, assetRef: string) => ({
      assetRef, siteId: "site-1", workAreaId: "area-1",
      workOrderId: assetRef === a ? "work-a" : "work-b",
      observationEpochId: assetRef === a ? "epoch-a" : "epoch-b",
      submissionRef: assetRef === a ? sa : sb, revision: assetRef === a ? 1 : 2,
      kind: "dsm",
      declared: { fileName: "tile.tif", captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z", captureDate: null },
      inspection: { outcome: "MEASURED", raster: null },
    }));
    render(await SiteAnalysisPage({ params: Promise.resolve({siteId:"site-1"}), searchParams: Promise.resolve({workAreaId:"area-1", visualAAssetRef:a, visualBAssetRef:b, ...hints}) }));
    const props = panelProps();
    // 후보에 맞지 않아 미리 고르지는 않는다 — 부적합 판정이 아니다.
    expect(props.initialBaselineSelector).toBeNull();
    expect(props.initialCurrentSelector).toBeNull();
    expect(props.exactHintNotice).toContain("정확히 맞지 않아");
    // 가져온 쌍이 무엇이었는지는 표시용으로 넘긴다.
    expect(props.broughtSelectors).toEqual({
      baseline: { workOrderId: "work-a", submissionRef: sa, revision: 1 },
      baselineMatched: false,
      current: { workOrderId: "work-b", submissionRef: sb, revision: 2 },
      currentMatched: false,
    });
    // 후보 목록이 비어도 바인딩된 쌍은 카탈로그 사실로 풀린다.
    expect(props.catalogPair.workAreaId).toBe("area-1");
    expect(props.catalogPair.a.selector).toEqual({ workOrderId: "work-a", submissionRef: sa, revision: 1 });
    expect(props.catalogPair.b.selector).toEqual({ workOrderId: "work-b", submissionRef: sb, revision: 2 });
  });
});
