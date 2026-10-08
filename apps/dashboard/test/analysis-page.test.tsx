/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ session: vi.fn(), site: vi.fn(), areas: vi.fn(), observations: vi.fn(), list: vi.fn(), detail: vi.fn() }));
vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/analysis", () => ({ listAnalysisObservations: mocked.observations, listAnalyses: mocked.list, getAnalysis: mocked.detail }));
vi.mock("@/app/sites/[siteId]/analysis/AnalysisRequestPanel", () => ({ AnalysisRequestPanel: ({ initialPage, initialAnalysisId, initialSelectedDetail }: { initialPage: { items: Array<{ analysisId: string }> }; initialAnalysisId: string; initialSelectedDetail: { analysisId: string } | null }) => <p>{`${initialAnalysisId}:${initialSelectedDetail?.analysisId ?? "none"}:${initialPage.items.map((item) => item.analysisId).join(",")}`}</p> }));
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

  it("keeps accessible Site context when an optional analysis child returns 404", async () => {
    const calls: string[] = [];
    mocked.site.mockImplementation(async () => { calls.push("site"); return { name: "접근 확인된 현장" }; });
    mocked.areas.mockImplementation(async () => { calls.push("areas"); return { workAreas: [] }; });
    mocked.observations.mockImplementation(async () => { calls.push("observations"); throw new CoreApiError(404, { detail: "route unavailable" }); });
    mocked.list.mockImplementation(async () => { calls.push("analyses"); return { siteId: "site-1", items: [], nextCursor: null }; });

    render(await SiteAnalysisPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve({}) }));

    expect(calls[0]).toBe("site");
    expect(screen.getByText("접근 확인된 현장")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "현장 분석" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toMatch(/현장 분석/);
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
});
