/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  site: vi.fn(),
  workspace: vi.fn(),
  surfaces: vi.fn(),
  workAreas: vi.fn(),
}));

vi.mock("next/navigation", () => ({ notFound: vi.fn() }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/site-workspace", () => ({ getSiteWorkspace: mocked.workspace }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.workAreas }));
vi.mock("@/lib/core-api/design", () => ({
  getDesignConformance: vi.fn(),
  getDesignProgress: vi.fn(),
  listDesignSurfaces: mocked.surfaces,
}));
vi.mock("@/components/external-results/ExternalSiteResultSummary", () => ({
  ExternalSiteResultSummary: ({ externalResult }: { externalResult: { state: string } }) => (
    <section data-testid="external-result">외부 결과: {externalResult.state}</section>
  ),
}));

import SiteReportPage from "@/app/sites/[siteId]/report/page";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SiteReportPage external result", () => {
  it("keeps a retained external result visible when no managed design surface has been selected", async () => {
    mocked.site.mockResolvedValue({ siteId: "site-1", name: "서부 현장" });
    mocked.workspace.mockResolvedValue({ externalResult: { state: "NO_RESULT" } });
    mocked.surfaces.mockResolvedValue({ surfaces: [] });
    mocked.workAreas.mockResolvedValue({ workAreas: [] });

    render(await SiteReportPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({}),
    }));

    expect(screen.getByTestId("external-result").textContent).toBe("외부 결과: NO_RESULT");
    expect(screen.getByText("어느 설계 기준면 보고서를 만들까요?")).toBeTruthy();
  });

  it("prints from the shared header when managed report data is unavailable", async () => {
    const print = vi.fn();
    vi.stubGlobal("print", print);
    mocked.site.mockResolvedValue({ siteId: "site-1", name: "서부 현장" });
    mocked.workspace.mockResolvedValue({ externalResult: { state: "NO_RESULT" } });
    mocked.surfaces.mockResolvedValue({ surfaces: [] });
    mocked.workAreas.mockResolvedValue({ workAreas: [] });

    render(await SiteReportPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({}),
    }));

    fireEvent.click(screen.getByRole("button", { name: "인쇄·PDF 저장" }));
    expect(print).toHaveBeenCalledOnce();
  });
});
