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
  report: vi.fn(),
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
  getExternalRelativeVolumeReport: mocked.report,
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
  WorkOrderOperationsPanel: ({ initialOperations }: { initialOperations: { operationsRevision: number; workflowStatus: string } | null }) => (
    <div data-testid="work-order-operations" data-revision={initialOperations?.operationsRevision ?? ""} data-status={initialOperations?.workflowStatus ?? ""} />
  ),
}));
vi.mock("@/app/field/CopilotPanel", () => ({ CopilotPanel: () => <div data-testid="copilot" /> }));
vi.mock("@/app/field/ExternalReconstructionPanel", () => ({
  ExternalReconstructionPanel: ({ initialReport, newIntentAllowed }: { initialReport?: { reportRef: string }; newIntentAllowed?: boolean }) => (
    <div data-testid="external-upload" data-report-ref={initialReport?.reportRef ?? ""} data-new-intent={String(newIntentAllowed)} />
  ),
}));
vi.mock("@/app/field/OperationsWorkHeader", () => ({ OperationsWorkHeader: ({ children }: { children: React.ReactNode }) => <header>{children}</header> }));
vi.mock("@/components/ui/StatusBadge", () => ({ StateBadge: () => <span /> }));
vi.mock("@/components/responsive/ResponsiveActionBoundary", () => ({ ResponsiveActionBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("@/app/field/OperationsSessionFailure", () => ({
  OperationsSessionFailure: ({ next }: { next: string }) => (
    <div data-testid="session-failure" data-next={next} />
  ),
}));

vi.mock("@/lib/core-api/external-reconstruction", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/core-api/external-reconstruction")>()),
  getExternalReconstructionContext: mocked.context,
}));

import FieldWorkOrderPage from "@/app/field/work-orders/[workOrderId]/page";

const digest = (value: string) => `sha256:${value.repeat(64)}`;
const workOrder = {
  schemaVersion: "1.0" as const,
  workOrderId: "successor-1",
  organizationId: "org-1",
  siteId: "site-1",
  purpose: "PROGRESS_QUANTITY" as const,
  name: "후속 재관측",
  workAreaIds: ["area-1"],
  scheduleId: null,
  executionMode: null,
  cycleNumber: 2,
  status: "APPROVED" as const,
  statusReason: null,
  missionIds: [],
  processingJobIds: [],
  reportRefs: [],
  version: 3,
  createdAt: "2026-09-09T00:00:00Z",
  updatedAt: "2026-09-09T00:00:00Z",
  createdBy: "operator-1",
  approvedAt: null,
  approvedBy: null,
};
const planningBinding = {
  contractVersion: "external-planning-only-work-order-binding.v1" as const,
  mode: "EXTERNAL_REOBSERVATION_PLANNING" as const,
  organizationId: "org-1",
  siteId: "site-1",
  sourceWorkOrderId: "source-1",
  successorWorkOrderId: "successor-1",
  approvalId: "approval-1",
  approvedBy: "operator-1",
  approvedAt: "2026-09-09T00:00:00Z",
  proposalId: "erop-v1-" + "a".repeat(64),
  proposalVersion: 1,
  proposalDigest: digest("a"),
  reportDigest: digest("b"),
  decisionDigest: digest("c"),
  zoneDigest: digest("d"),
  evidenceDigests: [digest("e")],
  targetWorkAreas: [{ workAreaId: "area-1", revision: 1 as const, snapshotDigest: digest("f") }],
  temporalPolicy: null,
  acquisitionRunAllowed: false as const,
  missionIssuanceAllowed: false as const,
  bindingDigest: digest("0"),
};

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue({ kind: "ready", principal: { principalId: "operator-1", organizationId: "org-1", kind: "OPERATOR", role: "ADMIN", deviceId: null, permissions: ["SITES_WRITE"] } });
  mocked.workOrder.mockResolvedValue(workOrder);
  mocked.site.mockResolvedValue(null);
  mocked.drafts.mockResolvedValue([]);
  mocked.progress.mockResolvedValue(null);
  mocked.readiness.mockResolvedValue(null);
  mocked.workspace.mockResolvedValue({ externalResult: { state: "NO_RESULT" } });
  mocked.report.mockResolvedValue(null);
  mocked.singleReport.mockResolvedValue(null);
  mocked.siteProjection.mockResolvedValue({ state: "NO_RESULT" });
  mocked.operations.mockResolvedValue(null);
});
afterEach(cleanup);

async function renderPage(reportRef?: string) {
  render(await FieldWorkOrderPage({
    params: Promise.resolve({ workOrderId: "successor-1" }),
    searchParams: Promise.resolve(reportRef ? { reportRef } : {}),
  }));
}

describe("external planning-only WorkOrder page", () => {
  it("keeps only a valid exact report reference in a blocked-session return", async () => {
    const reportRef = `external-relative-volume-report-${"a".repeat(32)}`;
    mocked.session.mockResolvedValue({ kind: "blocked", verdict: "LOGIN_REQUIRED" });

    await renderPage(reportRef);

    expect(screen.getByTestId("session-failure").getAttribute("data-next")).toBe(
      `/field/work-orders/successor-1?reportRef=${reportRef}#external-result`,
    );
    expect(mocked.workOrder).not.toHaveBeenCalled();

    cleanup();
    mocked.workOrder.mockClear();
    await renderPage("https://untrusted.example/report");

    expect(screen.getByTestId("session-failure").getAttribute("data-next")).toBe(
      "/field/work-orders/successor-1",
    );
    expect(mocked.workOrder).not.toHaveBeenCalled();
  });

  it("presents an approved planning-only successor as the next external upload without managed flight preparation", async () => {
    mocked.context.mockResolvedValue({ workOrderId: "successor-1", siteId: "site-1", expectedEpochId: "epoch-1", cycleNumber: 2, workOrderVersion: 3, executionMode: null, externalPlanningBinding: planningBinding });
    mocked.operations.mockResolvedValue({ operationsRevision: 0, workflowStatus: "UNSPECIFIED" });
    await renderPage();
    expect(screen.getByRole("heading", { name: "승인된 재관측 산출물 등록" })).toBeTruthy();
    expect(screen.getByText("승인된 재관측에 필요한 산출물을 등록하세요. 이 작업에서는 비행이나 장비를 실행하지 않습니다.")).toBeTruthy();
    expect(screen.queryByText("비행 계획 준비")).toBeNull();
    expect(screen.queryByText("장비 준비를 확인한 뒤 WorkOrder 정보가 채워진 비행 계획을 사람이 검토합니다.")).toBeNull();
    expect(screen.getByText(/승인된 재관측의 후속 작업/)).toBeTruthy();
    expect(screen.getByTestId("external-upload")).toBeTruthy();
    expect(screen.getByTestId("work-order-operations").getAttribute("data-revision")).toBe("0");
    expect(screen.getByTestId("work-order-operations").getAttribute("data-status")).toBe("UNSPECIFIED");
    expect(mocked.operations).toHaveBeenCalledWith("successor-1");
    expect(screen.queryByTestId("managed-action")).toBeNull();
    expect(screen.queryByTestId("managed-progress")).toBeNull();
    expect(screen.queryByTestId("managed-readiness")).toBeNull();
    expect(screen.queryByTestId("copilot")).toBeNull();
    expect(screen.queryByText("전문가 복구 정보")).toBeNull();
  });

  it("preserves managed verified-null presentation and controls", async () => {
    mocked.context.mockResolvedValue({ workOrderId: "successor-1", siteId: "site-1", expectedEpochId: "epoch-1", cycleNumber: 2, workOrderVersion: 3, executionMode: null, externalPlanningBinding: null });
    await renderPage();
    expect(screen.getByRole("heading", { name: "비행 계획 준비" })).toBeTruthy();
    expect(screen.getByText("장비 준비를 확인한 뒤 WorkOrder 정보가 채워진 비행 계획을 사람이 검토합니다.")).toBeTruthy();
    expect(screen.getByTestId("managed-action")).toBeTruthy();
    expect(screen.getByTestId("managed-progress")).toBeTruthy();
    expect(screen.getByTestId("managed-readiness")).toBeTruthy();
    expect(screen.getByText("전문가 복구 정보")).toBeTruthy();
    expect(screen.queryByText(/외부 재관측 계획 후속 작업/)).toBeNull();
  });

  it("does not present flight readiness when Core execution context is unverified", async () => {
    mocked.context.mockResolvedValue(null);
    await renderPage();
    expect(screen.getByRole("heading", { name: "작업 실행 정보 확인 필요" })).toBeTruthy();
    expect(screen.getByText("작업 실행 정보를 확인하지 못했습니다. 비행이나 장비 실행 준비 상태를 표시하지 않습니다.")).toBeTruthy();
    expect(screen.queryByText("비행 계획 준비")).toBeNull();
    expect(screen.queryByText("장비 준비를 확인한 뒤 WorkOrder 정보가 채워진 비행 계획을 사람이 검토합니다.")).toBeNull();
    expect(screen.queryByTestId("managed-action")).toBeNull();
  });

  it("presents an initial external ingress as upload-only without managed controls", async () => {
    mocked.workOrder.mockResolvedValue({ ...workOrder, executionMode: "EXTERNAL_RECONSTRUCTION" });
    mocked.context.mockResolvedValue({ workOrderId: "successor-1", siteId: "site-1", expectedEpochId: "epoch-1", cycleNumber: 2, workOrderVersion: 3, executionMode: "EXTERNAL_RECONSTRUCTION", externalPlanningBinding: null });

    await renderPage();

    expect(screen.getByRole("heading", { name: "외부 산출물 등록 준비" })).toBeTruthy();
    expect(screen.getByText(/외부에서 준비한 재구성 산출물을 등록하기 위한 작업입니다/)).toBeTruthy();
    expect(screen.getByTestId("external-upload")).toBeTruthy();
    expect(screen.queryByTestId("managed-action")).toBeNull();
    expect(screen.queryByTestId("managed-progress")).toBeNull();
  });

  it("presents an initially closed external task as closed and blocks only new intentions", async () => {
    mocked.workOrder.mockResolvedValue({ ...workOrder, executionMode: "EXTERNAL_RECONSTRUCTION" });
    mocked.context.mockResolvedValue({ workOrderId: "successor-1", siteId: "site-1", expectedEpochId: "epoch-1", cycleNumber: 2, workOrderVersion: 3, executionMode: "EXTERNAL_RECONSTRUCTION", externalPlanningBinding: null });
    mocked.operations.mockResolvedValue({ operationsRevision: 2, workflowStatus: "CLOSED" });

    await renderPage();

    expect(screen.getByRole("heading", { name: "업무 종료" })).toBeTruthy();
    expect(screen.getByText(/새 산출물 등록과 비교·검토 요청은 시작할 수 없으며/)).toBeTruthy();
    expect(screen.getByTestId("external-upload").getAttribute("data-new-intent")).toBe("false");
  });

  it("opens an exact result only when the exact Site projection and retained report bind to this WorkOrder", async () => {
    const reportRef = `external-relative-volume-report-${"a".repeat(32)}`;
    const reportDigest = digest("r");
    mocked.context.mockResolvedValue({ workOrderId: "successor-1", siteId: "site-1", expectedEpochId: "epoch-1", cycleNumber: 2, workOrderVersion: 3, executionMode: null, externalPlanningBinding: planningBinding });
    mocked.siteProjection.mockResolvedValue({
      state: "AVAILABLE",
      result: { reportRef, reportDigest, requestRef: "request-1", requestDigest: digest("q"), currentWorkOrderId: "successor-1" },
    });
    mocked.report.mockResolvedValue({
      request: { currentWorkOrderId: "successor-1", requestId: "request-1", requestDigest: digest("q") },
      report: { reportId: reportRef, reportDigest },
    });

    await renderPage(reportRef);

    expect(screen.getByTestId("external-upload").getAttribute("data-report-ref")).toBe(reportRef);
    expect(mocked.siteProjection).toHaveBeenCalledWith("site-1", reportRef);
  });
});
