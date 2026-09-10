/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  site: vi.fn(),
  areas: vi.fn(),
  canCreate: vi.fn(),
  workOrder: vi.fn(),
  report: vi.fn(),
}));

vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/permissions", () => ({ hasAllPermissions: mocked.canCreate }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ getObservationWorkOrder: mocked.workOrder }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({ getSiteExternalRelativeVolumeReport: mocked.report }));
vi.mock("@/app/sites/[siteId]/observations/new/ExternalObservationCreateForm", () => ({
  ExternalObservationCreateForm: ({ initialWorkAreaIds, temporalPolicy, templateNotice }: {
    initialWorkAreaIds: string[];
    temporalPolicy: unknown;
    templateNotice?: string | null;
  }) => <div data-testid="create-form" data-areas={initialWorkAreaIds.join(",")} data-policy={JSON.stringify(temporalPolicy)} data-notice={templateNotice ?? ""} />,
}));

import NewObservationPage from "@/app/sites/[siteId]/observations/new/page";

const reportRef = `external-relative-volume-report-${"a".repeat(32)}`;

beforeEach(() => {
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "현장 A" });
  mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "절성토 구역" }] });
  mocked.canCreate.mockResolvedValue(true);
  mocked.workOrder.mockResolvedValue({ siteId: "site-1", executionMode: null, workAreaIds: ["area-1"], temporalPolicy: { schemaVersion: "1.0", maxCaptureSpanSeconds: 600 } });
  mocked.report.mockResolvedValue({ state: "AVAILABLE", result: { reportRef, currentWorkOrderId: "legacy-work-1", workAreaId: "area-1" } });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

async function renderPage(searchParams: { repeatReportRef?: string; repeatWorkOrderId?: string }) {
  render(await NewObservationPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve(searchParams) }));
}

describe("보관된 결과에서 새 관측 준비", () => {
  it("retained legacy report uses its active area and same-site temporal policy as a template", async () => {
    await renderPage({ repeatReportRef: reportRef });

    const form = screen.getByTestId("create-form");
    expect(form.getAttribute("data-areas")).toBe("area-1");
    expect(form.getAttribute("data-policy")).toBe('{"schemaVersion":"1.0","maxCaptureSpanSeconds":600}');
    expect(form.getAttribute("data-notice")).toContain("이전 비교");
    expect(mocked.report).toHaveBeenCalledWith("site-1", reportRef);
    expect(mocked.workOrder).toHaveBeenCalledWith("legacy-work-1");
  });

  it("keeps an unavailable retained report explicit and does not preselect a range", async () => {
    mocked.report.mockResolvedValue({ state: "HISTORICAL_SOURCE_UNAVAILABLE", result: null });
    await renderPage({ repeatReportRef: reportRef });

    const form = screen.getByTestId("create-form");
    expect(form.getAttribute("data-areas")).toBe("");
    expect(form.getAttribute("data-notice")).toContain("확인하지 못했습니다");
    expect(mocked.workOrder).not.toHaveBeenCalled();
  });

  it("keeps a missing scoped report explicit and does not use another template", async () => {
    mocked.report.mockRejectedValue(new Error("not found"));
    await renderPage({ repeatReportRef: reportRef });

    const form = screen.getByTestId("create-form");
    expect(form.getAttribute("data-areas")).toBe("");
    expect(form.getAttribute("data-notice")).toContain("확인하지 못했습니다");
    expect(mocked.workOrder).not.toHaveBeenCalled();
  });
});
