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
  ExternalObservationCreateForm: ({ initialWorkAreaIds, temporalPolicy, suggestedName, templateNotice }: {
    initialWorkAreaIds: string[];
    temporalPolicy: unknown;
    suggestedName?: string | null;
    templateNotice?: string | null;
  }) => <div data-testid="create-form" data-areas={initialWorkAreaIds.join(",")} data-policy={JSON.stringify(temporalPolicy)} data-name={suggestedName ?? ""} data-notice={templateNotice ?? ""} />,
}));

import NewObservationPage from "@/app/sites/[siteId]/observations/new/page";

const reportRef = `external-relative-volume-report-${"a".repeat(32)}`;

beforeEach(() => {
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "현장 A" });
  mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "절성토 구역" }] });
  mocked.canCreate.mockResolvedValue(true);
  mocked.workOrder.mockResolvedValue({ workOrderId: "legacy-work-1", siteId: "site-1", name: "1차 관측", cycleNumber: 1, executionMode: "EXTERNAL_RECONSTRUCTION", workAreaIds: ["area-1"], temporalPolicy: { schemaVersion: "1.0", maxCaptureSpanSeconds: 600 } });
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
    expect(form.getAttribute("data-name")).toBe("1차 관측 · 2회차");
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

  it("uses a same-site external work order as an explicit scope template", async () => {
    mocked.workOrder.mockResolvedValueOnce({ workOrderId: "work-order-2", siteId: "site-1", executionMode: "EXTERNAL_RECONSTRUCTION", workAreaIds: ["area-1"], temporalPolicy: { schemaVersion: "1.0", maxCaptureSpanSeconds: 600 } });
    await renderPage({ repeatWorkOrderId: "work-order-2" });

    const form = screen.getByTestId("create-form");
    expect(form.getAttribute("data-areas")).toBe("area-1");
    expect(form.getAttribute("data-policy")).toBe('{"schemaVersion":"1.0","maxCaptureSpanSeconds":600}');
    expect(form.getAttribute("data-notice")).toContain("미리 골랐습니다");
    expect(mocked.workOrder).toHaveBeenCalledWith("work-order-2");
    expect(mocked.report).not.toHaveBeenCalled();
  });

  it("does not reuse a cross-site work order and explains the manual recovery", async () => {
    mocked.workOrder.mockResolvedValueOnce({
      workOrderId: "work-order-2",
      siteId: "another-site",
      executionMode: "EXTERNAL_RECONSTRUCTION",
      workAreaIds: ["area-1"],
      temporalPolicy: null,
    });
    await renderPage({ repeatWorkOrderId: "work-order-2" });

    const form = screen.getByTestId("create-form");
    expect(form.getAttribute("data-areas")).toBe("");
    expect(form.getAttribute("data-notice")).toContain("범위를 확인하지 못했습니다");
  });

  it("omits the cycle suffix when the source cycle is not derivable", async () => {
    mocked.workOrder.mockResolvedValue({ workOrderId: "legacy-work-1", siteId: "site-1", name: "기존 작업", cycleNumber: Number.NaN, executionMode: "EXTERNAL_RECONSTRUCTION", workAreaIds: ["area-1"], temporalPolicy: null });
    await renderPage({ repeatReportRef: reportRef });

    expect(screen.getByTestId("create-form").getAttribute("data-name")).toBe("기존 작업");
  });
});
