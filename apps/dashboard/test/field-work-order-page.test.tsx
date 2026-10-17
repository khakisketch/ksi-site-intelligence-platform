/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  workOrder: vi.fn(),
  operations: vi.fn(),
  drafts: vi.fn(),
  context: vi.fn(),
  submissions: vi.fn(),
  siteReport: vi.fn(),
  report: vi.fn(),
  history: vi.fn(),
  site: vi.fn(),
  areas: vi.fn(),
  resolveContext: vi.fn(),
}));

vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({
  getObservationWorkOrder: mocked.workOrder,
  getObservationWorkOrderOperations: mocked.operations,
  listReobservationDrafts: mocked.drafts,
}));
vi.mock("@/lib/core-api/external-reconstruction", () => ({
  getExternalReconstructionContext: mocked.context,
  listExternalReconstructionSubmissions: mocked.submissions,
  resolveExternalWorkOrderExecutionContext: mocked.resolveContext,
}));
vi.mock("@/lib/core-api/external-result-workflow", () => ({
  getSiteExternalRelativeVolumeReport: mocked.siteReport,
  getExternalRelativeVolumeReport: mocked.report,
  listSiteExternalVolumeHistory: mocked.history,
}));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/app/field/ExternalReconstructionPanel", () => ({
  ExternalReconstructionPanel: ({ initialReport }: { initialReport?: { reportRef: string } }) => <p data-testid="initial-report">{initialReport?.reportRef ?? "none"}</p>,
}));
vi.mock("@/app/field/WorkOrderOperationsPanel", () => ({ WorkOrderOperationsPanel: () => <div data-testid="operations-panel" /> }));
vi.mock("@/app/field/OperationsWorkHeader", () => ({ OperationsWorkHeader: ({ children }: { children: React.ReactNode }) => <header>{children}</header> }));
vi.mock("@/components/external-results/ExternalSiteResultSummary", () => ({ ExternalSiteResultSummary: () => <div data-testid="result-summary" /> }));
vi.mock("@/components/responsive/ResponsiveActionBoundary", () => ({ ResponsiveNotice: () => <div data-testid="responsive-notice" /> }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import FieldWorkOrderPage from "@/app/field/work-orders/[workOrderId]/page";

const reportRef = `external-relative-volume-report-${"a".repeat(32)}`;
const digest = `sha256:${"b".repeat(64)}`;

function reportProjection(overrides: Record<string, unknown> = {}) {
  return {
    state: "AVAILABLE",
    result: {
      reportRef,
      reportDigest: digest,
      sourceWorkOrderId: "baseline-1",
      currentWorkOrderId: "order-1",
      baselineWorkOrderId: "baseline-1",
      workAreaId: "area-1",
      ...overrides,
    },
  };
}

function reportDetail(proposal?: Record<string, unknown>, currentWorkOrderId = "order-1") {
  return {
    request: {
      requestId: "request-1",
      requestDigest: "request-digest",
      currentWorkOrderId,
      baseline: { subject: { organizationId: "org-1", siteId: "site-1", workOrderId: "baseline-1" } },
      current: { subject: { organizationId: "org-1", siteId: "site-1", workOrderId: currentWorkOrderId } },
      zoneSnapshot: { organizationId: "org-1", siteId: "site-1", workAreaId: "area-1" },
    },
    report: { reportId: reportRef, reportDigest: digest, requestId: "request-1", requestDigest: "request-digest" },
    review: null,
    proposals: proposal ? [proposal] : [],
  };
}

const baseOrder = {
  workOrderId: "order-1",
  organizationId: "org-1",
  siteId: "site-1",
  name: "현장 t1",
  workAreaIds: ["area-1"],
  executionMode: "EXTERNAL_RECONSTRUCTION",
  cycleNumber: 1,
  version: 1,
  status: "APPROVED",
  statusReason: null,
  reportRefs: [reportRef],
};

beforeEach(() => {
  mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SITES_WRITE", "WORK_ORDERS_WRITE"] } });
  mocked.workOrder.mockImplementation(async (workOrderId: string) => ({ ...baseOrder, workOrderId }));
  mocked.operations.mockResolvedValue({ workOrderId: "order-1", organizationId: "org-1", siteId: "site-1", workflowStatus: "OPEN", assigneePrincipalId: null, dueAt: null, closedAt: null, closeNote: null });
  mocked.drafts.mockResolvedValue([{ draftId: "draft-1", status: "PENDING", proposedEffort: "재관측 필요", targetRegionRefs: ["region-1"], expiresAt: "2026-09-30T00:00:00Z" }]);
  mocked.context.mockResolvedValue({ workOrderId: "order-1", siteId: "site-1", expectedEpochId: "epoch-1", cycleNumber: 1, workOrderVersion: 1, executionMode: "EXTERNAL_RECONSTRUCTION", externalPlanningBinding: null });
  mocked.submissions.mockResolvedValue([]);
  mocked.siteReport.mockResolvedValue(reportProjection());
  mocked.report.mockResolvedValue(reportDetail());
  mocked.history.mockResolvedValue({ items: [], nextCursor: null });
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "현장 A" });
  mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "동측 구역" }] });
  mocked.resolveContext.mockImplementation((_order: unknown, context: { externalPlanningBinding?: unknown } | null) => context?.externalPlanningBinding ? "EXTERNAL_REOBSERVATION_PLANNING" : "EXTERNAL_INGRESS");
});

afterEach(() => { cleanup(); vi.clearAllMocks(); });

async function renderPage(search: { reportRef?: string | string[] } = {}, workOrderId = "order-1") {
  render(await FieldWorkOrderPage({
    params: Promise.resolve({ workOrderId }),
    searchParams: Promise.resolve(search),
  }));
}

describe("관측 작업 페이지 follow-up", () => {
  it("resolves and passes a same-Site, same-work-order report deep link to the existing panel", async () => {
    await renderPage({ reportRef });

    expect(screen.getByTestId("initial-report").textContent).toBe(reportRef);
    expect(screen.queryByText(/비교 결과를 이 작업에 결속하지 못했습니다/)).toBeNull();
    expect(screen.getByRole("heading", { name: "플랫폼 작업 상태" })).toBeTruthy();
    expect(screen.getAllByText("외부 산출물 등록 준비")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "결과와 제안 결정으로 이동" }).getAttribute("href")).toBe("#external-result");
    expect(mocked.siteReport).toHaveBeenCalledWith("site-1", reportRef);
    expect(mocked.report).toHaveBeenCalledWith(reportRef);
  });

  it("shows a recovery notice instead of silently dropping a malformed or mismatched report reference", async () => {
    await renderPage({ reportRef: "not-a-report-ref" });
    expect(screen.getByTestId("initial-report").textContent).toBe("none");
    expect(screen.getByRole("status").textContent).toContain("주소를 확인하지 못했습니다");
    expect(mocked.siteReport).not.toHaveBeenCalled();

    cleanup();
    mocked.siteReport.mockResolvedValueOnce(reportProjection({ currentWorkOrderId: "another-order", sourceWorkOrderId: "another-order" }));
    await renderPage({ reportRef });
    expect(screen.getByTestId("initial-report").textContent).toBe("none");
    expect(screen.getByRole("status").textContent).toContain("이 작업에 결속하지 못했습니다");

    cleanup();
    mocked.siteReport.mockResolvedValueOnce(reportProjection({ workAreaId: "another-area" }));
    await renderPage({ reportRef });
    expect(screen.getByTestId("initial-report").textContent).toBe("none");
    expect(screen.getByRole("status").textContent).toContain("이 작업에 결속하지 못했습니다");
  });

  it("links pending drafts to the existing decision anchor", async () => {
    await renderPage();

    expect(screen.getByRole("link", { name: "비교 요청·제안 상태로 이동" }).getAttribute("href")).toBe("#external-volume");
    expect(document.body.textContent).toContain("1개 구역 · 만료 2026. 9. 30. 09:00");
    expect(document.body.textContent).not.toContain("2026-09-30T00:00:00Z");
  });

  it("moves to (not auto-opens) operations disclosure and passes scoped area names to intake", async () => {
    await renderPage();

    // 앵커는 스크롤 이동만 약속한다 — disclosure를 대신 열어주지 않는다.
    expect(screen.getByRole("link", { name: "작업 운영으로 이동" }).getAttribute("href")).toBe("#work-operations");
    const operations = screen.getByTestId("operations-panel");
    const disclosure = operations.closest("details");
    expect(disclosure?.id).toBe("work-operations");
    expect(disclosure?.open).toBe(false);
    expect(disclosure?.querySelector("summary")?.textContent).toContain("작업 운영");
  });

  it("uses the shared count format for WorkAreas and draft regions", async () => {
    mocked.workOrder.mockResolvedValueOnce({ ...baseOrder, workAreaIds: Array.from({ length: 1_234 }, (_, index) => `area-${index}`) });
    mocked.drafts.mockResolvedValueOnce([{ draftId: "draft-1", status: "PENDING", proposedEffort: "재관측 필요", targetRegionRefs: Array.from({ length: 1_234 }, (_, index) => `region-${index}`), expiresAt: "2026-09-30T00:00:00Z" }]);

    await renderPage();

    expect(document.body.textContent).toContain("현장 A · 동측 구역 외 1,233개 구역 · 1회차");
    expect(document.body.textContent).toContain("1,234개 구역 · 만료 2026. 9. 30. 09:00");
  });

  it("shows a compact successor banner with the exact source proposal and next analysis step", async () => {
    const successorOrder = { ...baseOrder, workOrderId: "successor-1", name: "현장 t2 준비", cycleNumber: 2, version: 2 };
    const sourceOrder = { ...baseOrder, workOrderId: "source-1", name: "현장 t1", cycleNumber: 1, reportRefs: [reportRef] };
    const binding = {
      contractVersion: "external-planning-only-work-order-binding.v1",
      mode: "EXTERNAL_REOBSERVATION_PLANNING",
      organizationId: "org-1",
      siteId: "site-1",
      sourceWorkOrderId: "source-1",
      successorWorkOrderId: "successor-1",
      approvalId: "approval-1",
      approvedBy: "reviewer-1",
      approvedAt: "2026-09-01T00:00:00Z",
      proposalId: "proposal-1",
      proposalVersion: 2,
      proposalDigest: "proposal-digest",
      reportDigest: digest,
      decisionDigest: "decision-digest",
      zoneDigest: "zone-digest",
      evidenceDigests: [],
      targetWorkAreas: [{ workAreaId: "area-1", revision: 1, snapshotDigest: null }],
      temporalPolicy: null,
      acquisitionRunAllowed: false,
      missionIssuanceAllowed: false,
      bindingDigest: "binding-digest",
    };
    mocked.workOrder.mockImplementation(async (workOrderId: string) => workOrderId === "successor-1" ? successorOrder : sourceOrder);
    mocked.context.mockResolvedValue({ workOrderId: "successor-1", siteId: "site-1", expectedEpochId: "epoch-2", cycleNumber: 2, workOrderVersion: 2, executionMode: "EXTERNAL_RECONSTRUCTION", externalPlanningBinding: binding });
    mocked.siteReport.mockResolvedValue(reportProjection({ currentWorkOrderId: "source-1" }));
    mocked.report.mockResolvedValue(reportDetail({
      proposal: {
        proposalRef: "proposal-1",
        version: 2,
        proposalDigest: "proposal-digest",
        reportRef,
        reportDigest: digest,
        decisionDigest: "decision-digest",
      },
      approvalReceipt: { successorWorkOrderId: "successor-1" },
    }, "source-1"));

    await renderPage({}, "successor-1");

    expect(screen.getByText("산출물 제출을 마친 뒤 변화 분석 화면에서 기준 자료→비교 자료 분석을 요청하세요.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "원본 결과·제안 보기" }).getAttribute("href")).toBe(`/field/work-orders/source-1?reportRef=${reportRef}#external-result`);
    expect(screen.getByRole("link", { name: "비교 요청·제안 상태로 이동" }).getAttribute("href")).toBe("#external-volume");
    expect(screen.getByRole("link", { name: "변화 분석 열기" }).getAttribute("href")).toBe("/sites/site-1/analysis#new-analysis-request");
    expect(screen.getByRole("link", { name: "이 범위로 관측 자료 등록" }).getAttribute("href")).toBe("/sites/site-1/observations/new?repeatWorkOrderId=successor-1");
  });

  it("keeps failed proposal and history reads unknown rather than silently empty", async () => {
    mocked.drafts.mockRejectedValue(new Error("unavailable"));
    mocked.history.mockRejectedValue(new Error("unavailable"));
    await renderPage();
    expect(screen.getByRole("alert").textContent).toContain("재관측 제안·보존된 결과 목록 확인 불가");
    expect(screen.getByRole("alert").textContent).toContain("해당 기록이 없다는 뜻이 아닙니다");
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy();
  });
});
