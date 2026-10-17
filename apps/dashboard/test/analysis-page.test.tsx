/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ session: vi.fn(), site: vi.fn(), areas: vi.fn(), observations: vi.fn(), workOrders: vi.fn(), list: vi.fn(), detail: vi.fn() }));
vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/analysis", () => ({ listAnalysisObservations: mocked.observations, listAnalyses: mocked.list, getAnalysis: mocked.detail }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ listObservationWorkOrders: mocked.workOrders }));
vi.mock("@/app/sites/[siteId]/analysis/AnalysisRequestPanel", () => ({ AnalysisRequestPanel: ({ initialPage, initialAnalysisId, initialSelectedDetail, observations, unattributedObservationCount, workOrderNames }: { initialPage: { items: Array<{ analysisId: string }> }; initialAnalysisId: string; initialSelectedDetail: { analysisId: string } | null; observations: Array<{ observationEpochId: string; workAreaIds: string[] }>; unattributedObservationCount: number; workOrderNames: Record<string, string> }) => <><p>{`${initialAnalysisId}:${initialSelectedDetail?.analysisId ?? "none"}:${initialPage.items.map((item) => item.analysisId).join(",")}`}</p><p data-testid="panel-attribution">{`${observations.map((item) => `${item.observationEpochId}:${item.workAreaIds.join(",")}`).join(";")}|unknown:${unattributedObservationCount}`}</p><p data-testid="panel-work-names">{Object.entries(workOrderNames ?? {}).map(([id, name]) => `${id}=${name}`).join(";")}</p></> }));
vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
  useRouter: () => ({ refresh: vi.fn() }),
}));

import SiteAnalysisPage from "@/app/sites/[siteId]/analysis/page";
import { CoreApiError } from "@/lib/core-api/client";

afterEach(() => { cleanup(); vi.resetAllMocks(); });

beforeEach(() => {
  mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ"] } });
  mocked.site.mockResolvedValue({ name: "접근 확인된 현장" });
  mocked.areas.mockResolvedValue({ workAreas: [] });
  mocked.observations.mockResolvedValue([]);
  mocked.workOrders.mockResolvedValue([]);
  mocked.list.mockResolvedValue({ siteId: "site-1", items: [], nextCursor: null });
  mocked.detail.mockResolvedValue(null);
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

    expect(screen.getByRole("heading", { name: "변화 분석 시작 안내" })).toBeTruthy();
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
    mocked.site.mockImplementation(async () => { calls.push("site"); return { name: "접근 확인된 현장" }; });
    mocked.areas.mockImplementation(async () => { calls.push("areas"); return { workAreas: [] }; });
    mocked.observations.mockImplementation(async () => { calls.push("observations"); throw new CoreApiError(404, { detail: "route unavailable" }); });
    mocked.list.mockImplementation(async () => { calls.push("analyses"); return { siteId: "site-1", items: [], nextCursor: null }; });

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({}) }));

    expect(calls[0]).toBe("site");
    expect(screen.getByText("접근 확인된 현장")).toBeTruthy();
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

    expect(screen.getByText("접근 확인된 현장")).toBeTruthy();
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
});
