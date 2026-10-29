/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  site: vi.fn(),
  projection: vi.fn(),
  areas: vi.fn(),
  detail: vi.fn(),
  pair: vi.fn(),
  operations: vi.fn(),
  share: vi.fn(),
}));

vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
  useRouter: () => ({ refresh: vi.fn() }),
}));
vi.mock("@/lib/core-api/client", () => ({
  CoreApiError: class extends Error {
    constructor(readonly status: number, _body: unknown, readonly retryAfterSeconds?: number) { super(`Core API ${status}`); }
  },
}));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({
  getSiteExternalRelativeVolumeReport: mocked.projection,
  getExternalRelativeVolumeReport: mocked.detail,
}));
vi.mock("@/lib/core-api/external-report-display", () => ({ resolveExactReportSafeDerivativePair: mocked.pair }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ getObservationWorkOrderOperations: mocked.operations }));
vi.mock("@/components/external-results/TeamReportShare", () => ({
  TeamReportShare: (props: unknown) => { mocked.share(props); return <p data-testid="team-share">share</p>; },
}));
vi.mock("@/app/sites/[siteId]/observations/ExternalObservationHistory", () => ({
  ExternalObservationHistory: () => <p>history</p>,
}));
vi.mock("@/app/sites/[siteId]/observations/[reportRef]/ExternalReportSafeDerivativeComparison", () => ({
  ExternalReportSafeDerivativeComparison: ({ pair }: { pair: { state: string } }) => <p data-testid="display-pair">{pair.state}</p>,
}));
vi.mock("@/app/sites/[siteId]/observations/[reportRef]/ExternalReportFollowupTrace", () => ({
  ExternalReportFollowupTrace: ({ successors }: { successors: Array<{ workflowStatus: string | null }> | null }) => <p data-testid="successor-state">{successors?.[0]?.workflowStatus ?? "none"}</p>,
}));

import SiteObservationDetailPage from "@/app/sites/[siteId]/observations/[reportRef]/page";
import { CoreApiError } from "@/lib/core-api/client";

const reportRef = `external-relative-volume-report-${"a".repeat(32)}`;
const digest = (character: string) => `sha256:${character.repeat(64)}`;

function fullReport(reportDigest = digest("d")) {
  const subject = (workOrderId: string, submissionId: string) => ({
    organizationId: "org-1", siteId: "site-1", workOrderId, submissionId, revision: 1,
    submissionDigest: digest(submissionId === "base" ? "a" : "b"), manifestDigest: digest(submissionId === "base" ? "c" : "e"),
  });
  return {
    request: {
      currentWorkOrderId: "current-order",
      baseline: { subject: subject("source-order", "base") },
      current: { subject: subject("current-order", "current") },
    },
    report: { reportId: reportRef, reportDigest },
    review: { reviewRef: "review-1", reviewDigest: digest("f"), reportRef, report: { reportDigest } },
    proposals: [{
      proposal: { reportRef, reportDigest, reviewRef: "review-1", reviewDigest: digest("f") },
      approvalReceipt: { successorWorkOrderId: "successor-1" },
    }],
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["WORK_ORDERS_WRITE"] } });
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "현장 1" });
  mocked.areas.mockResolvedValue({ workAreas: [] });
  mocked.projection.mockResolvedValue({
    state: "AVAILABLE",
    result: {
      reportRef, reportDigest: digest("d"), sourceWorkOrderId: "current-order", baselineWorkOrderId: "source-order", currentWorkOrderId: "current-order",
    },
  });
  mocked.detail.mockResolvedValue(fullReport());
  mocked.pair.mockResolvedValue({ state: "READY" });
  mocked.operations.mockResolvedValue({ workOrderId: "successor-1", organizationId: "org-1", siteId: "site-1", workflowStatus: "CLOSED", closeNote: "현장 확인 완료" });
});

afterEach(cleanup);

describe("exact site report detail", () => {
  it("loads the Site before dependent report and WorkArea reads", async () => {
    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));

    expect(mocked.site.mock.invocationCallOrder[0]).toBeLessThan(mocked.projection.mock.invocationCallOrder[0]);
    expect(mocked.site.mock.invocationCallOrder[0]).toBeLessThan(mocked.areas.mock.invocationCallOrder[0]);
  });

  it.each([
    ["report", "projection"],
  ] as const)("preserves Site context and provides a non-retryable history exit after a %s 403", async (_label, target) => {
    mocked[target].mockRejectedValue(new CoreApiError(403, {}));

    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));

    expect(screen.getByText("현장 1")).toBeTruthy();
    expect(screen.getByText("이 관측 결과를 확인할 권한이 없습니다.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "관측 이력" }).getAttribute("href")).toBe("/sites/site-1/observations");
    expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull();
    expect(mocked.share).not.toHaveBeenCalled();
    expect(mocked.pair).not.toHaveBeenCalled();
    expect(mocked.operations).not.toHaveBeenCalled();
  });

  it("keeps the verified report visible with a notice when only WorkArea names are denied", async () => {
    mocked.areas.mockRejectedValue(new CoreApiError(403, {}));

    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));

    // 보관 결과는 그대로 보이고, 이름 실패만 따로 알린다. 이름 없는 행은
    // '작업구역'으로 표시되며 권한 없는 이름은 노출되지 않는다.
    expect(screen.getByText("현장 1")).toBeTruthy();
    expect(screen.queryByText("이 관측 결과를 확인할 권한이 없습니다.")).toBeNull();
    expect(screen.getByRole("status").textContent).toMatch(/작업구역 이름을 불러오지 못했습니다/);
    expect(screen.getByTestId("display-pair")).toBeTruthy();
  });

  it("keeps a dependent 404 in the Site-scoped unavailable state rather than declaring the Site missing", async () => {
    mocked.projection.mockRejectedValue(new CoreApiError(404, {}));

    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));

    expect(screen.getByText("현장 1")).toBeTruthy();
    expect(screen.getByText("관측 결과를 확인할 수 없습니다.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "관측 이력" })).toBeTruthy();
  });

  it("preserves Site context on exact-detail 403 without rendering unverified derived or successor views", async () => {
    mocked.detail.mockRejectedValue(new CoreApiError(403, {}));

    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));

    expect(screen.getByText("현장 1")).toBeTruthy();
    expect(screen.getByText("상세 근거를 확인할 권한이 없습니다.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "관측 이력" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull();
    expect(screen.queryByTestId("display-pair")).toBeNull();
    expect(screen.queryByTestId("successor-state")).toBeNull();
    const trace = screen.getByRole("heading", { name: "검토·재관측 흐름" }).closest("section")!;
    expect(trace.textContent).toContain("상세 근거를 확인할 수 없어 검토·재관측 상태를 표시하지 않습니다.");
    expect(within(trace).queryByRole("link", { name: "승인된 후속 작업 보기" })).toBeNull();
    expect(mocked.pair).not.toHaveBeenCalled();
    expect(mocked.share).not.toHaveBeenCalled();
    expect(mocked.operations).not.toHaveBeenCalled();
  });

  it("keeps the verified report visible when only WorkArea names fail transiently", async () => {
    mocked.areas.mockRejectedValue(new CoreApiError(503, {}, 12));

    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));

    // 보관 결과는 그대로 보이고, 이름 실패만 따로 알린다.
    expect(screen.getByText("현장 1")).toBeTruthy();
    expect(screen.queryByText("관측 결과를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")).toBeNull();
    expect(screen.getByRole("status").textContent).toMatch(/작업구역 이름을 불러오지 못했습니다/);
    expect(screen.getByTestId("display-pair")).toBeTruthy();
  });

  it("uses the exact verified report for a safe display pair and retained successor operation state", async () => {
    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));
    expect(screen.getByTestId("display-pair").textContent).toBe("READY");
    expect(mocked.pair).toHaveBeenCalledWith(expect.anything(), { organizationId: "org-1", siteId: "site-1" });
    expect(mocked.operations).toHaveBeenCalledWith("successor-1");
    expect(screen.getByTestId("successor-state").textContent).toBe("CLOSED");
    expect(mocked.share).toHaveBeenCalledWith({ reportRef, siteId: "site-1", organizationId: "org-1", principalId: "operator-1", canWrite: true });
  });

  it("fails closed and hides derived or successor views when the full report digest diverges from the site projection", async () => {
    mocked.detail.mockResolvedValue(fullReport(digest("0")));
    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));
    expect(screen.queryByTestId("display-pair")).toBeNull();
    expect(mocked.pair).not.toHaveBeenCalled();
    expect(mocked.operations).not.toHaveBeenCalled();
    expect(screen.queryByTestId("successor-state")).toBeNull();
    expect(mocked.share).not.toHaveBeenCalled();
  });

  it("fails closed when the projection source work order is not the current report work order", async () => {
    mocked.projection.mockResolvedValue({
      state: "AVAILABLE",
      result: {
        reportRef, reportDigest: digest("d"), sourceWorkOrderId: "foreign-order", baselineWorkOrderId: "source-order", currentWorkOrderId: "current-order",
      },
    });
    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));
    expect(screen.queryByTestId("display-pair")).toBeNull();
    expect(mocked.pair).not.toHaveBeenCalled();
    expect(mocked.operations).not.toHaveBeenCalled();
    expect(screen.queryByTestId("successor-state")).toBeNull();
    expect(mocked.share).not.toHaveBeenCalled();
  });

  it("fails closed when a report detail echoes a foreign organization instead of the resolved operator scope", async () => {
    const foreignDetail = fullReport();
    foreignDetail.request.baseline.subject.organizationId = "foreign-org";
    foreignDetail.request.current.subject.organizationId = "foreign-org";
    mocked.detail.mockResolvedValue(foreignDetail);
    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));
    expect(screen.queryByTestId("display-pair")).toBeNull();
    expect(mocked.pair).not.toHaveBeenCalled();
    expect(mocked.operations).not.toHaveBeenCalled();
    expect(screen.queryByTestId("successor-state")).toBeNull();
    expect(mocked.share).not.toHaveBeenCalled();
  });

  it("preserves read-only permission for an exact report viewer", async () => {
    mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "viewer-1", permissions: ["SITES_READ"] } });
    render(await SiteObservationDetailPage({ params: Promise.resolve({ siteId: "site-1", reportRef }) }));
    expect(mocked.share).toHaveBeenCalledWith(expect.objectContaining({ principalId: "viewer-1", canWrite: false }));
  });
});
