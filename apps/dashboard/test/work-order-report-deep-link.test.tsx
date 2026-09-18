/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  context: vi.fn(),
  workOrder: vi.fn(),
  session: vi.fn(),
  site: vi.fn(),
  drafts: vi.fn(),
  progress: vi.fn(),
  readiness: vi.fn(),
  workspace: vi.fn(),
  relativeReport: vi.fn(),
  singleReport: vi.fn(),
  siteProjection: vi.fn(),
  operations: vi.fn(),
}));

vi.mock("next/navigation", () => ({ notFound: vi.fn() }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({
  getObservationWorkOrder: mocked.workOrder,
  getObservationWorkOrderOperations: mocked.operations,
  listReobservationDrafts: mocked.drafts,
}));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/site-workspace", () => ({
  getSiteWorkspace: mocked.workspace,
  getLatestSiteBriefing: () => Promise.reject(new Error("no briefing in this test")),
}));
vi.mock("@/lib/core-api/external-result-workflow", () => ({
  getExternalRelativeVolumeReport: mocked.relativeReport,
  getExternalSingleVolumeReport: mocked.singleReport,
  getSiteExternalRelativeVolumeReport: mocked.siteProjection,
}));
vi.mock("@/lib/core-api/acquisition-coordination", () => ({ getAcquisitionProgress: mocked.progress }));
vi.mock("@/lib/core-api/acquisition-connectivity", () => ({ getAcquisitionReadiness: mocked.readiness }));
vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("@/app/field/WorkOrderActionPanel", () => ({ WorkOrderActionPanel: () => <div data-testid="managed-action" /> }));
vi.mock("@/app/field/AcquisitionProgressCard", () => ({ AcquisitionProgressCard: () => <div data-testid="managed-progress" /> }));
vi.mock("@/app/field/AcquisitionReadinessCard", () => ({ AcquisitionReadinessCard: () => <div data-testid="managed-readiness" /> }));
vi.mock("@/app/field/WorkOrderOperationsPanel", () => ({
  WorkOrderOperationsPanel: () => <div data-testid="work-order-operations" />,
}));
vi.mock("@/app/field/CopilotPanel", () => ({ CopilotPanel: () => <div data-testid="copilot" /> }));
vi.mock("@/app/field/ExternalReconstructionPanel", () => ({
  ExternalReconstructionPanel: ({ initialReport }: { initialReport?: { reportRef: string } }) => (
    <div data-testid="external-upload" data-report-ref={initialReport?.reportRef ?? ""} />
  ),
}));
vi.mock("@/app/field/OperationsWorkHeader", () => ({ OperationsWorkHeader: ({ children }: { children: React.ReactNode }) => <header>{children}</header> }));
vi.mock("@/components/ui/StatusBadge", () => ({ StateBadge: () => <span /> }));
vi.mock("@/components/responsive/ResponsiveActionBoundary", () => ({ ResponsiveActionBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("@/app/field/OperationsSessionFailure", () => ({
  OperationsSessionFailure: ({ next }: { next: string }) => <div data-testid="session-failure" data-next={next} />,
}));

vi.mock("@/lib/core-api/external-reconstruction", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/core-api/external-reconstruction")>()),
  getExternalReconstructionContext: mocked.context,
}));

import FieldWorkOrderPage from "@/app/field/work-orders/[workOrderId]/page";

const digest = (value: string) => `sha256:${value.repeat(64)}`;
const workOrder = {
  schemaVersion: "1.0" as const,
  workOrderId: "wo-1",
  organizationId: "org-1",
  siteId: "site-1",
  purpose: "PROGRESS_QUANTITY" as const,
  name: "구역 재관측",
  workAreaIds: ["area-1"],
  scheduleId: null,
  executionMode: null,
  cycleNumber: 1,
  status: "APPROVED" as const,
  statusReason: null,
  missionIds: [],
  processingJobIds: [],
  reportRefs: [],
  version: 1,
  createdAt: "2026-09-09T00:00:00Z",
  updatedAt: "2026-09-09T00:00:00Z",
  createdBy: "operator-1",
  approvedAt: null,
  approvedBy: null,
};
const verifiedNullContext = {
  workOrderId: "wo-1",
  siteId: "site-1",
  expectedEpochId: "epoch-1",
  cycleNumber: 1,
  workOrderVersion: 1,
  executionMode: null,
  externalPlanningBinding: null,
};

const relativeReportRef = `external-relative-volume-report-${"a".repeat(32)}`;
const singleReportRef = `external-single-volume-report-${"b".repeat(32)}`;

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue({ kind: "ready", principal: { principalId: "operator-1", organizationId: "org-1", kind: "OPERATOR", role: "ADMIN", deviceId: null, permissions: ["SITES_WRITE"] } });
  mocked.workOrder.mockResolvedValue(workOrder);
  mocked.site.mockResolvedValue(null);
  mocked.drafts.mockResolvedValue([]);
  mocked.progress.mockResolvedValue(null);
  mocked.readiness.mockResolvedValue(null);
  mocked.workspace.mockResolvedValue({ externalResult: { state: "NO_RESULT" } });
  mocked.relativeReport.mockResolvedValue(null);
  mocked.singleReport.mockResolvedValue(null);
  mocked.siteProjection.mockResolvedValue({ state: "NO_RESULT" });
  mocked.operations.mockResolvedValue(null);
  mocked.context.mockResolvedValue(verifiedNullContext);
});
afterEach(cleanup);

async function renderPage(reportRef?: string) {
  render(await FieldWorkOrderPage({
    params: Promise.resolve({ workOrderId: "wo-1" }),
    searchParams: Promise.resolve(reportRef ? { reportRef } : {}),
  }));
}

describe("WorkOrder page exact report deep link", () => {
  it("accepts a RELATIVE_VOLUME report that is not the Site's latest result", async () => {
    const reportDigest = digest("r");
    mocked.relativeReport.mockResolvedValue({
      request: { currentWorkOrderId: "wo-1", zoneSnapshot: { workAreaId: "area-1" } },
      report: { reportId: relativeReportRef, reportDigest },
    });
    mocked.siteProjection.mockResolvedValue({
      state: "AVAILABLE",
      result: { reportRef: relativeReportRef, reportDigest, currentWorkOrderId: "wo-1", requestRef: "request-1", requestDigest: digest("q") },
    });

    await renderPage(relativeReportRef);

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByTestId("external-upload").getAttribute("data-report-ref")).toBe(relativeReportRef);
    expect(mocked.siteProjection).toHaveBeenCalledWith("site-1", relativeReportRef);
    expect(mocked.singleReport).not.toHaveBeenCalled();
  });

  it("accepts a SINGLE_VOLUME report without a rejection notice", async () => {
    const reportDigest = digest("s");
    mocked.singleReport.mockResolvedValue({
      request: { currentWorkOrderId: "wo-1", zoneSnapshot: { workAreaId: "area-1" } },
      report: { reportId: singleReportRef, reportDigest },
    });
    mocked.siteProjection.mockResolvedValue({
      state: "AVAILABLE",
      result: { reportRef: singleReportRef, reportDigest, currentWorkOrderId: "wo-1", requestRef: "request-1", requestDigest: digest("q") },
    });

    await renderPage(singleReportRef);

    expect(screen.queryByRole("alert")).toBeNull();
    expect(mocked.siteProjection).toHaveBeenCalledWith("site-1", singleReportRef);
    expect(mocked.relativeReport).not.toHaveBeenCalled();
    // The trusted-link panel is RELATIVE_VOLUME-only today (Task 6/7 wiring);
    // a verified SINGLE_VOLUME ref is accepted but not yet threaded through.
    expect(screen.getByTestId("external-upload").getAttribute("data-report-ref")).toBe("");
  });

  it("rejects a report whose exact Site projection digest does not match the retained report", async () => {
    mocked.relativeReport.mockResolvedValue({
      request: { currentWorkOrderId: "wo-1", zoneSnapshot: { workAreaId: "area-1" } },
      report: { reportId: relativeReportRef, reportDigest: digest("mismatched-report") },
    });
    mocked.siteProjection.mockResolvedValue({
      state: "AVAILABLE",
      result: { reportRef: relativeReportRef, reportDigest: digest("mismatched-projection"), currentWorkOrderId: "wo-1", requestRef: "request-1", requestDigest: digest("q") },
    });

    await renderPage(relativeReportRef);

    expect(screen.getByRole("alert").textContent).toBe(
      "이 작업에서 확인할 수 있는 최신 비교 결과인지 검증하지 못했습니다. 현장 결과 목록에서 다시 열어 주세요.",
    );
    expect(screen.getByTestId("external-upload").getAttribute("data-report-ref")).toBe("");
  });

  it("rejects a report whose exact fetch does not bind to this WorkOrder", async () => {
    const reportDigest = digest("r");
    mocked.relativeReport.mockResolvedValue({
      request: { currentWorkOrderId: "other-work-order", zoneSnapshot: { workAreaId: "area-1" } },
      report: { reportId: relativeReportRef, reportDigest },
    });
    mocked.siteProjection.mockResolvedValue({
      state: "AVAILABLE",
      result: { reportRef: relativeReportRef, reportDigest, currentWorkOrderId: "wo-1", requestRef: "request-1", requestDigest: digest("q") },
    });

    await renderPage(relativeReportRef);

    expect(screen.getByRole("alert").textContent).toBe(
      "이 작업에서 확인할 수 있는 최신 비교 결과인지 검증하지 못했습니다. 현장 결과 목록에서 다시 열어 주세요.",
    );
    expect(screen.getByTestId("external-upload").getAttribute("data-report-ref")).toBe("");
  });
});
